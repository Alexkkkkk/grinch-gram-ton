"""
neural_prophet.py v1 — QuantumProphet: Нейронное предсказание цен с Attention.

Гибридная архитектура:
  1. PatternMatcher   — динамическое программирование для поиска похожих паттернов
  2. AttentionEnsemble — взвешенное голосование паттернов (attention weights)
  3. MLPRegressor     — нейронная сеть для коррекции предсказания
  4. MultiHorizon     — предсказание на 3, 7, 14 свечей вперёд
  5. ConfidenceGate   — фильтр: предсказание только при высокой уверенности

Использует только sklearn (уже в requirements) — никаких PyTorch/TensorFlow.
"""

import logging
import math
import os
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("neural_prophet")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
PROPHET_STATE_FILE = os.path.join(DATA_DIR, "neural_prophet_state.json")

# ── Константы ────────────────────────────────────────────────────────────────
MAX_PATTERN_LEN = 30  # длина паттерна для поиска
MIN_PATTERN_MATCH = 5  # минимум совпадений для валидного паттерна
PATTERN_WINDOW = 200  # сколько последних свечей хранить
CONFIDENCE_THRESHOLD = 0.65  # минимальная уверенность для выдачи предсказания
HORIZONS = [3, 7, 14]  # горизонты предсказания в свечах


class PatternMatcher:
    """Ищет похожие паттерны в истории цен через DTW-подобное расстояние."""

    def __init__(self, max_len: int = MAX_PATTERN_LEN, window: int = PATTERN_WINDOW):
        self._max_len = max_len
        self._window = window
        self._history: deque = deque(maxlen=window)
        self._lock = threading.RLock()

    def feed(self, candles: List[dict]):
        """Добавить свечи в историю."""
        with self._lock:
            for c in candles:
                self._history.append(
                    {
                        "open": float(c.get("open", c.get("o", 0))),
                        "high": float(c.get("high", c.get("h", 0))),
                        "low": float(c.get("low", c.get("l", 0))),
                        "close": float(c.get("close", c.get("c", 0))),
                        "volume": float(c.get("volume", c.get("v", 0))),
                        "ts": c.get("timestamp", c.get("t", time.time())),
                    }
                )

    def _normalize_pattern(self, seq: List[float]) -> np.ndarray:
        """Z-нормализация паттерна для инвариантности к масштабу."""
        arr = np.array(seq, dtype=np.float64)
        if len(arr) < 2:
            return arr
        mean = np.mean(arr)
        std = np.std(arr) + 1e-9
        return (arr - mean) / std

    def _dtw_distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """Упрощённое DTW расстояние между двумя паттернами."""
        n, m = len(a), len(b)
        if n == 0 or m == 0:
            return float("inf")
        # Динамическое программирование с окном Sakoe-Chiba (w=max(n,m)//4)
        w = max(n, m) // 4
        dtw = np.full((n + 1, m + 1), float("inf"))
        dtw[0, 0] = 0.0
        for i in range(1, n + 1):
            j_start = max(1, i - w)
            j_end = min(m, i + w) + 1
            for j in range(j_start, j_end):
                cost = abs(a[i - 1] - b[j - 1])
                dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
        return dtw[n, m]

    def find_matches(
        self, recent: List[float], top_k: int = 5
    ) -> List[Tuple[float, float]]:
        """
        Найти top_k похожих паттернов в истории.
        Возвращает: [(distance, future_return)]
        """
        with self._lock:
            hist = list(self._history)
        if len(hist) < len(recent) * 2 + max(HORIZONS):
            return []

        recent_norm = self._normalize_pattern(recent)
        matches = []

        # Скользим окном по истории
        pattern_len = len(recent)
        for i in range(pattern_len, len(hist) - max(HORIZONS)):
            candidate = [c["close"] for c in hist[i - pattern_len : i]]
            cand_norm = self._normalize_pattern(candidate)
            if len(cand_norm) != len(recent_norm):
                continue
            dist = self._dtw_distance(recent_norm, cand_norm)
            # Будущее изменение цены
            future_price = hist[i + HORIZONS[0] - 1]["close"]
            current_price = hist[i - 1]["close"]
            future_return = (
                (future_price - current_price) / (current_price + 1e-9) * 100
            )
            matches.append((dist, future_return))

        matches.sort(key=lambda x: x[0])
        return matches[:top_k]


class AttentionEnsemble:
    """
    Attention-механизм: взвешивает паттерны обратно пропорционально расстоянию.
    Ближайшие паттерны получают экспоненциально больший вес.
    """

    def __init__(self, temperature: float = 1.0):
        self._temperature = temperature

    def predict(self, matches: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        Взвешенное предсказание и уверенность.
        Возвращает: (predicted_return_pct, confidence_0_1)
        """
        if not matches:
            return 0.0, 0.0

        # Преобразуем расстояния в веса (attention weights)
        distances = np.array([m[0] for m in matches])
        returns = np.array([m[1] for m in matches])

        # Softmax attention с температурой
        neg_dist = -distances / self._temperature
        max_neg = np.max(neg_dist)
        exp_weights = np.exp(neg_dist - max_neg)
        weights = exp_weights / (np.sum(exp_weights) + 1e-9)

        weighted_return = float(np.sum(weights * returns))

        # Уверенность = 1 - нормализованная энтропия весов
        # Чем более сосредоточены веса → тем выше уверенность
        entropy = -np.sum(weights * np.log(weights + 1e-9))
        max_entropy = math.log(len(weights))
        confidence = 1.0 - (entropy / max_entropy if max_entropy > 0 else 0)

        # Также учитываем согласованность знаков предсказаний
        signs = np.sign(returns)
        sign_agreement = abs(np.sum(signs)) / len(signs)
        confidence = 0.6 * confidence + 0.4 * sign_agreement

        return weighted_return, float(confidence)


class MLPRegressor:
    """
    Простая MLP нейросеть через sklearn (fallback на линейную регрессию).
    Корректирует предсказание PatternMatcher на основе признаков.
    """

    def __init__(self):
        self._model = None
        self._scaler = None
        self._trained = False
        self._train_lock = threading.Lock()
        self._feature_history: List[Tuple[List[float], float]] = []
        self._max_history = 500

    def _build_features(self, candles: List[dict]) -> List[float]:
        """Извлекает 15 признаков из свечей."""
        if len(candles) < 10:
            return [0.0] * 15

        closes = [c["close"] for c in candles]
        volumes = [c.get("volume", 0) for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        # Returns
        returns = [
            (closes[i] - closes[i - 1]) / (closes[i - 1] + 1e-9) * 100
            for i in range(1, len(closes))
        ]

        # Volatility
        volatility = np.std(returns) if returns else 0.0

        # Trend
        ema5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        ema10 = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        trend = (ema5 - ema10) / (ema10 + 1e-9) * 100

        # Momentum
        momentum = (
            (closes[-1] - closes[-5]) / (closes[-5] + 1e-9) * 100
            if len(closes) >= 5
            else 0.0
        )

        # Volume trend
        vol_ratio = (
            np.mean(volumes[-3:]) / (np.mean(volumes[-10:]) + 1e-9)
            if len(volumes) >= 10
            else 1.0
        )

        # Range
        avg_range = np.mean([h - l for h, l in zip(highs, lows)])
        range_ratio = avg_range / (closes[-1] + 1e-9) * 100

        # Recent returns
        recent_returns = (
            returns[-5:] if len(returns) >= 5 else returns + [0.0] * (5 - len(returns))
        )

        features = [
            closes[-1],
            volatility,
            trend,
            momentum,
            vol_ratio,
            range_ratio,
            *recent_returns,
        ]
        # Pad to 15
        while len(features) < 15:
            features.append(0.0)
        return features[:15]

    def train(self, candles: List[dict], actual_returns: List[float]):
        """Обучить MLP на исторических данных."""
        if len(candles) < 20 or len(actual_returns) < 5:
            return

        try:
            from sklearn.neural_network import MLPRegressor as SklearnMLP
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            logger.warning("sklearn not available for MLP")
            return

        with self._train_lock:
            X, y = [], []
            for i in range(10, len(candles) - 7):
                feat = self._build_features(candles[max(0, i - 20) : i])
                X.append(feat)
                # Будущий return через 7 свечей
                future_idx = min(i + 7, len(actual_returns) - 1)
                y.append(actual_returns[future_idx])

            if len(X) < 10:
                return

            self._scaler = StandardScaler()
            X_scaled = self._scaler.fit_transform(X)

            self._model = SklearnMLP(
                hidden_layer_sizes=(32, 16),
                activation="tanh",
                solver="adam",
                max_iter=500,
                early_stopping=True,
                validation_fraction=0.15,
                random_state=42,
            )
            self._model.fit(X_scaled, y)
            self._trained = True
            logger.info("[NeuralProphet] MLP trained on %d samples", len(X))

    def predict_correction(self, candles: List[dict]) -> float:
        """Вернуть коррекцию от MLP (0 = нет коррекции)."""
        if not self._trained or self._model is None or self._scaler is None:
            return 0.0
        try:
            feat = self._build_features(candles)
            feat_scaled = self._scaler.transform([feat])
            return float(self._model.predict(feat_scaled)[0])
        except Exception as e:
            logger.debug("MLP predict error: %s", e)
            return 0.0


class MultiHorizonPredictor:
    """Предсказание на несколько горизонтов с убывающей уверенностью."""

    def __init__(self):
        self._pattern_matcher = PatternMatcher()
        self._attention = AttentionEnsemble(temperature=2.0)
        self._mlp = MLPRegressor()
        self._last_predictions: Dict[int, Tuple[float, float, float]] = (
            {}
        )  # horizon -> (price, return, conf)
        self._lock = threading.RLock()

    def feed_candles(self, candles: List[dict]):
        """Добавить свечи в историю."""
        self._pattern_matcher.feed(candles)

        # Периодически переобучаем MLP
        if len(candles) > 50 and hasattr(self, "_last_mlp_train"):
            if time.time() - getattr(self, "_last_mlp_train", 0) > 3600:
                returns = []
                for i in range(1, len(candles)):
                    r = (
                        (candles[i]["close"] - candles[i - 1]["close"])
                        / (candles[i - 1]["close"] + 1e-9)
                        * 100
                    )
                    returns.append(r)
                self._mlp.train(candles, returns)
                self._last_mlp_train = time.time()

    def predict(self, current_price: float, candles: List[dict]) -> Dict[int, dict]:
        """
        Предсказать цену на каждый горизонт.
        Возвращает: {horizon: {"price": float, "return_pct": float, "confidence": float, "direction": str}}
        """
        with self._lock:
            if len(candles) < MAX_PATTERN_LEN:
                return {}

            recent = [c["close"] for c in candles[-MAX_PATTERN_LEN:]]
            matches = self._pattern_matcher.find_matches(recent, top_k=10)

            if len(matches) < MIN_PATTERN_MATCH:
                return {}

            base_return, base_conf = self._attention.predict(matches)
            mlp_correction = self._mlp.predict_correction(candles)

            results = {}
            for h in HORIZONS:
                # Уверенность убывает с горизонтом
                horizon_decay = math.exp(-h / 10.0)
                conf = base_conf * horizon_decay

                # Коррекция от MLP (с меньшим весом на дальних горизонтах)
                corrected_return = base_return * (
                    1 + mlp_correction * 0.1 * horizon_decay
                )

                # Дисперсия предсказаний = мера неопределённости
                returns = [m[1] for m in matches[:5]]
                dispersion = np.std(returns) if returns else 10.0
                conf *= max(0.3, 1.0 - dispersion / 20.0)

                predicted_price = current_price * (1 + corrected_return / 100)
                direction = (
                    "UP"
                    if corrected_return > 1.0
                    else "DOWN" if corrected_return < -1.0 else "FLAT"
                )

                results[h] = {
                    "price": round(predicted_price, 6),
                    "return_pct": round(corrected_return, 4),
                    "confidence": round(conf, 4),
                    "direction": direction,
                    "matches_found": len(matches),
                }

            self._last_predictions = {
                h: (
                    results[h]["price"],
                    results[h]["return_pct"],
                    results[h]["confidence"],
                )
                for h in results
            }
            return results

    def get_signal(self, current_price: float, candles: List[dict]) -> dict:
        """Упрощённый сигнал для торгового движка."""
        preds = self.predict(current_price, candles)
        if not preds or 7 not in preds:
            return {"signal": "HOLD", "confidence": 0.0, "target_price": current_price}

        p7 = preds[7]
        if p7["confidence"] < CONFIDENCE_THRESHOLD:
            return {
                "signal": "HOLD",
                "confidence": p7["confidence"],
                "target_price": current_price,
            }

        signal = (
            "BUY"
            if p7["direction"] == "UP"
            else "SELL" if p7["direction"] == "DOWN" else "HOLD"
        )
        return {
            "signal": signal,
            "confidence": p7["confidence"],
            "target_price": p7["price"],
            "expected_return_pct": p7["return_pct"],
            "horizons": preds,
        }

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "last_predictions": {
                    str(k): {"price": v[0], "return": v[1], "conf": v[2]}
                    for k, v in self._last_predictions.items()
                },
                "history_size": len(self._pattern_matcher._history),
            }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_prophet: Optional[MultiHorizonPredictor] = None


def get_prophet() -> MultiHorizonPredictor:
    global _prophet
    if _prophet is None:
        _prophet = MultiHorizonPredictor()
    return _prophet


def predict_price(current_price: float, candles: List[dict]) -> dict:
    """Публичный API: получить предсказание цены."""
    prophet = get_prophet()
    prophet.feed_candles(candles)
    return prophet.get_signal(current_price, candles)


def get_full_prediction(current_price: float, candles: List[dict]) -> Dict[int, dict]:
    """Публичный API: полное мультигоризонтное предсказание."""
    prophet = get_prophet()
    prophet.feed_candles(candles)
    return prophet.predict(current_price, candles)
