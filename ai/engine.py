"""AIEngine v2.2 — secure, validated, with train/test split."""

import gc
import hashlib
import hmac
import logging
import threading
import time
import warnings
from typing import Any, Dict, List, Optional

try:
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        GradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
except ImportError:
    StandardScaler = None
    RandomForestClassifier = None
    ExtraTreesClassifier = None
    GradientBoostingClassifier = None
    train_test_split = None

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
    globals()["train_test_split"] = __import__(
        "sklearn.model_selection", fromlist=["train_test_split"]
    ).train_test_split
    _sklearn_loaded = True


def _get_signing_key() -> bytes:
    """Get HMAC key from SECRET_KEY env var."""
    key = Config.SECRET_KEY.encode() if Config.SECRET_KEY else b""
    if len(key) < 32:
        logger.warning("SECRET_KEY is too short for secure HMAC signing")
    return key


def _sign_data(data: bytes) -> bytes:
    """Sign serialized data with HMAC-SHA256."""
    key = _get_signing_key()
    if not key:
        raise RuntimeError("Cannot sign data: SECRET_KEY not configured")
    sig = hmac.new(key, data, hashlib.sha256).digest()
    return sig + data


def _verify_data(data: bytes) -> bytes:
    """Verify HMAC signature and return payload."""
    if len(data) < 32:
        raise ValueError("Data too short to contain signature")
    key = _get_signing_key()
    if not key:
        raise RuntimeError("Cannot verify data: SECRET_KEY not configured")
    sig, payload = data[:32], data[32:]
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("HMAC signature verification failed — possible tampering")
    return payload


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
        self._models: Dict[str, Any] = {}
        self._scaler: Optional[Any] = None
        self._trained = False
        self._examples: List[Dict] = []
        self._last_train = 0.0
        self._n_features = n_features

    def pretrain(self, ohlcv: List[dict], on_progress=None) -> bool:
        _ensure_sklearn()
        from ai.features import build_training_data

        X, y = build_training_data(ohlcv, profit_bias_pct=2.0)
        if X is None or len(X) < 20:
            logger.warning(
                "Not enough data for pretrain (%s samples)",
                len(X) if X is not None else 0,
            )
            return False

        # Train/test split to prevent overfitting
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        with self._lock:
            self._scaler = StandardScaler()
            Xs_train = self._scaler.fit_transform(X_train)
            Xs_test = self._scaler.transform(X_test)
            self._models = {
                "rf": RandomForestClassifier(
                    n_estimators=50, max_depth=6, random_state=42, n_jobs=1
                ),
                "et": ExtraTreesClassifier(
                    n_estimators=50, max_depth=6, random_state=42, n_jobs=1
                ),
                "gb": GradientBoostingClassifier(
                    n_estimators=40, max_depth=3, random_state=42
                ),
            }
            for name, model in self._models.items():
                try:
                    model.fit(Xs_train, y_train)
                    train_acc = model.score(Xs_train, y_train)
                    test_acc = model.score(Xs_test, y_test)
                    logger.info(
                        "%s pre-trained (train_acc=%.3f, test_acc=%.3f, gap=%.3f)",
                        name,
                        train_acc,
                        test_acc,
                        train_acc - test_acc,
                    )
                    # Warn if overfitting detected (>10% gap)
                    if train_acc - test_acc > 0.1:
                        logger.warning(
                            "%s shows signs of overfitting (gap=%.3f)",
                            name,
                            train_acc - test_acc,
                        )
                except Exception as exc:
                    logger.warning("%s pretrain failed: %s", name, exc)
            self._trained = True
            self._last_train = time.time()
        if on_progress:
            on_progress({"stage": "pretrain", "done": True, "samples": len(X)})
        return True

    def analyze(self, ohlcv: List[dict], **kwargs) -> Dict[str, Any]:
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

    def feedback(self, features: List[float], label: int) -> None:
        self._examples.append({"features": features, "label": label, "ts": time.time()})
        if len(self._examples) > 5000:
            self._examples = self._examples[-4000:]

    def capture_buy_context(self, ohlcv: List[dict], **kwargs) -> Optional[List[float]]:
        from ai.features import extract_features

        feat = extract_features(ohlcv, self._n_features)
        return feat[0].tolist() if feat is not None else None

    def export_experience(self) -> bytes:
        """Export models with HMAC-SHA256 integrity signature."""
        try:
            import joblib
        except ImportError:
            logger.error("joblib not installed — cannot export experience")
            return b""
        with self._lock:
            state = {
                "examples": self._examples,
                "models": {k: joblib.dumps(v) for k, v in self._models.items()},
                "scaler": joblib.dumps(self._scaler) if self._scaler else None,
                "trained": self._trained,
                "version": 2,
            }
            payload = joblib.dumps(state)
            return _sign_data(payload)

    def import_experience(self, data: bytes) -> bool:
        """Import only if HMAC signature is valid."""
        try:
            import joblib
        except ImportError:
            logger.error("joblib not installed — cannot import experience")
            return False
        try:
            payload = _verify_data(data)
            state = joblib.loads(payload)
            with self._lock:
                self._examples = state.get("examples", [])
                self._trained = state.get("trained", False)
                if state.get("scaler"):
                    self._scaler = joblib.loads(state["scaler"])
                for k, v in state.get("models", {}).items():
                    self._models[k] = joblib.loads(v)
            logger.info("Experience imported (v%d)", state.get("version", 1))
            return True
        except ValueError as exc:
            logger.error("Import BLOCKED: %s", exc)
            return False
        except Exception as exc:
            logger.warning("import_experience failed: %s", exc)
            return False

    def load_deep_models(self) -> bool:
        return False

    def _default_signal(self) -> Dict[str, Any]:
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
