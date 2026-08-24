"""AIEngine v2.1 — refactored, modular, lazy-loaded, memory-optimized."""

import gc
import logging
import pickle
import threading
import time
import warnings
from typing import Any

try:
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        GradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.preprocessing import StandardScaler
except ImportError:
    StandardScaler = None
    RandomForestClassifier = None
    ExtraTreesClassifier = None
    GradientBoostingClassifier = None

import numpy as np

from core.config import Config

logger = logging.getLogger(__name__)

_sklearn_loaded = False


def _ensure_sklearn():
    global _sklearn_loaded
    if _sklearn_loaded:
        return
    warnings.filterwarnings("ignore", category=UserWarning)
    globals()["RandomForestClassifier"] = __import__(
        "sklearn.ensemble", fromlist=["RandomForestClassifier"]
    ).RandomForestClassifier
    globals()["ExtraTreesClassifier"] = __import__(
        "sklearn.ensemble", fromlist=["ExtraTreesClassifier"]
    ).ExtraTreesClassifier
    globals()["GradientBoostingClassifier"] = __import__(
        "sklearn.ensemble", fromlist=["GradientBoostingClassifier"]
    ).GradientBoostingClassifier
    globals()["StandardScaler"] = __import__(
        "sklearn.preprocessing", fromlist=["StandardScaler"]
    ).StandardScaler
    _sklearn_loaded = True


class AIEngine:
    __slots__ = (
        "_lock",
        "_models",
        "_scaler",
        "_trained",
        "_examples",
        "_last_train",
        "_n_features",
    )

    def __init__(self, n_features: int = 32) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, Any] = {}
        self._scaler: Any | None = None
        self._trained = False
        self._examples: list[dict] = []
        self._last_train = 0.0
        self._n_features = n_features

    def pretrain(self, ohlcv: list[dict], on_progress=None) -> bool:
        _ensure_sklearn()
        from ai.features import build_training_data

        X, y = build_training_data(ohlcv, profit_bias_pct=2.0)
        if X is None or len(X) < 20:
            logger.warning(
                "Not enough data for pretrain (%s samples)",
                len(X) if X is not None else 0,
            )
            return False
        with self._lock:
            self._scaler = StandardScaler()
            Xs = self._scaler.fit_transform(X)
            self._models = {
                "rf": RandomForestClassifier(
                    n_estimators=100, max_depth=8, random_state=42, n_jobs=-1
                ),
                "et": ExtraTreesClassifier(
                    n_estimators=100, max_depth=8, random_state=42, n_jobs=-1
                ),
                "gb": GradientBoostingClassifier(
                    n_estimators=80, max_depth=4, random_state=42
                ),
            }
            for name, model in self._models.items():
                try:
                    model.fit(Xs, y)
                    logger.info("%s pre-trained (acc=%.3f)", name, model.score(Xs, y))
                except Exception as exc:
                    logger.warning("%s pretrain failed: %s", name, exc)
            self._trained = True
            self._last_train = time.time()
        if on_progress:
            on_progress({"stage": "pretrain", "done": True, "samples": len(X)})
        return True

    def analyze(self, ohlcv: list[dict], **kwargs) -> dict[str, Any]:
        from ai.features import extract_features
        from ai.regime import BreakoutEngine, MomentumEngine, PumpDetector

        feat = extract_features(ohlcv, self._n_features)
        if feat is None:
            return self._default_signal()

        with self._lock:
            if not self._trained or not self._models:
                return self._default_signal()
            Xs = self._scaler.transform(feat) if self._scaler else feat
            probs = []
            for name, model in self._models.items():
                try:
                    p = model.predict_proba(Xs)[0]
                    probs.append(p)
                except Exception:
                    pass
        if not probs:
            return self._default_signal()

        avg_prob = np.mean(probs, axis=0)
        prob_up = float(avg_prob[1]) if len(avg_prob) > 1 else 0.5
        confidence = abs(prob_up - 0.5) * 200

        close = np.array([c["close"] for c in ohlcv if "close" in c])
        high = np.array([c.get("high", c["close"]) for c in ohlcv if "close" in c])
        low = np.array([c.get("low", c["close"]) for c in ohlcv if "close" in c])
        volume = np.array([c.get("volume", 0) for c in ohlcv if "close" in c])

        momentum = MomentumEngine.detect(close)
        breakout = BreakoutEngine.detect(close, high, low)
        pump = PumpDetector.detect(close, volume)

        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else 0
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else 1e-9
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))

        trs = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        atr = np.mean(trs[-14:]) if len(trs) >= 14 else 0
        atr_pct = atr / close[-1] * 100 if close[-1] > 0 else 0

        signal = "BUY" if prob_up > 0.55 else ("SELL" if prob_up < 0.45 else "HOLD")
        if confidence < Config.AI.min_confidence:
            signal = "HOLD"

        return {
            "ai_signal": signal,
            "confidence": confidence,
            "prob_up": prob_up,
            "regime": {"name": momentum["signal"], "atr_pct": atr_pct},
            "momentum": momentum,
            "breakout": breakout,
            "pump_detector": pump,
            "rsi": rsi,
            "ev_ok": True,
        }

    def feedback(self, features: list[float], label: int) -> None:
        self._examples.append({"features": features, "label": label, "ts": time.time()})
        if len(self._examples) > 5000:
            self._examples = self._examples[-4000:]

    def capture_buy_context(self, ohlcv: list[dict], **kwargs) -> list[float] | None:
        from ai.features import extract_features

        feat = extract_features(ohlcv, self._n_features)
        return feat[0].tolist() if feat is not None else None

    def export_experience(self) -> bytes:
        with self._lock:
            return pickle.dumps(
                {
                    "examples": self._examples,
                    "models": {k: pickle.dumps(v) for k, v in self._models.items()},
                    "scaler": pickle.dumps(self._scaler) if self._scaler else None,
                    "trained": self._trained,
                }
            )

    def import_experience(self, data: bytes) -> bool:
        try:
            state = pickle.loads(data)
            with self._lock:
                self._examples = state.get("examples", [])
                self._trained = state.get("trained", False)
                if state.get("scaler"):
                    self._scaler = pickle.loads(state["scaler"])
                for k, v in state.get("models", {}).items():
                    self._models[k] = pickle.loads(v)
            return True
        except Exception as exc:
            logger.warning("import_experience failed: %s", exc)
            return False

    def load_deep_models(self) -> bool:
        return False

    def _default_signal(self) -> dict[str, Any]:
        return {
            "ai_signal": "HOLD",
            "confidence": 0.0,
            "prob_up": 0.5,
            "prob_down": 0.5,
            "regime": {"name": "UNKNOWN", "atr_pct": 0.0},
            "momentum": {"signal": "CALM", "score": 0.0},
            "breakout": {"signal": "FLAT", "score": 0.0},
            "pump_detector": {"score": 0.0, "detected": False},
            "rsi": 50.0,
            "ev_ok": True,
        }


def _release_memory():
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
