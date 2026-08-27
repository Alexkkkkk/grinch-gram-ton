"""
xai_explainer.py v1 — QuantumXAI: Объяснимый ИИ для торговых решений.

Возможности:
  1. FeatureAttribution  — permutation importance для признаков
  2. DecisionExplainer   — человекочитаемое объяснение решения
  3. Counterfactuals     — "что если" сценарии
  4. TrustScore          — оценка надёжности предсказания
  5. ExplanationLogger   — история объяснений для аудита

Всё без внешних зависимостей (кроме numpy).
"""

import logging
import os
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("xai_explainer")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
EXPLANATION_LOG_FILE = os.path.join(DATA_DIR, "xai_explanations.json")

# ── Константы ────────────────────────────────────────────────────────────────
MAX_EXPLANATIONS = 200
FEATURE_NAMES = [
    "rsi",
    "macd",
    "macd_hist",
    "bb_width",
    "bb_pct",
    "atr_pct",
    "vol_ratio",
    "stoch_rsi",
    "obv_trend",
    "adx",
    "di_plus",
    "di_minus",
    "willr",
    "cci",
    "ichi_gap",
    "above_cloud",
    "ha_trend",
    "vwap_dev",
    "ema_trend",
    "momentum",
    "vol_trend",
    "price_vs_ema50",
    "range_ratio",
    "pump_score",
    "drawdown_pct",
    "profit_momentum",
    "fill_density",
    "regime_encoded",
    "time_of_day",
    "day_of_week",
]


class FeatureAttribution:
    """
    Permutation Importance: меряем, насколько предсказание деградирует
    при случайном перемешивании признака.
    """

    def __init__(self, n_features: int = len(FEATURE_NAMES)):
        self._n = n_features
        self._baseline_predictions: deque = deque(maxlen=100)
        self._feature_impacts: Dict[int, deque] = {
            i: deque(maxlen=50) for i in range(n_features)
        }
        self._lock = threading.Lock()

    def record_baseline(self, prediction: float):
        """Записать базовое предсказание."""
        with self._lock:
            self._baseline_predictions.append(prediction)

    def record_feature_impact(self, feature_idx: int, prediction_with_noise: float):
        """Записать предсказание с зашумлённым признаком."""
        with self._lock:
            if self._baseline_predictions:
                baseline = self._baseline_predictions[-1]
                impact = abs(prediction_with_noise - baseline)
                self._feature_impacts[feature_idx].append(impact)

    def get_importance(self) -> List[Tuple[str, float]]:
        """Вернуть признаки, отсортированные по важности."""
        with self._lock:
            results = []
            for i in range(self._n):
                impacts = list(self._feature_impacts.get(i, []))
                avg_impact = np.mean(impacts) if impacts else 0.0
                name = FEATURE_NAMES[i] if i < len(FEATURE_NAMES) else f"feat_{i}"
                results.append((name, float(avg_impact)))
            results.sort(key=lambda x: x[1], reverse=True)
            return results

    def get_top_features(self, n: int = 5) -> List[Tuple[str, float]]:
        return self.get_importance()[:n]


class DecisionExplainer:
    """Генерирует человекочитаемое объяснение торгового решения."""

    @staticmethod
    def explain(
        signal: str,
        confidence: float,
        features: Dict[str, float],
        top_features: List[Tuple[str, float]],
        regime: str = "UNKNOWN",
        sentiment: Dict = None,
        swarm_consensus: str = None,
        prophet_signal: str = None,
    ) -> str:
        """Сгенерировать объяснение решения."""
        parts = []

        # Основное решение
        if signal == "BUY":
            parts.append(f"🟢 СИГНАЛ ПОКУПКИ (уверенность {confidence:.1f}%)")
        elif signal == "SELL":
            parts.append(f"🔴 СИГНАЛ ПРОДАЖИ (уверенность {confidence:.1f}%)")
        else:
            parts.append(f"⚪ УДЕРЖАНИЕ ПОЗИЦИИ (уверенность {confidence:.1f}%)")

        # Режим рынка
        parts.append(f"📊 Режим рынка: {regime}")

        # Ключевые факторы
        if top_features:
            parts.append("🔑 Ключевые факторы:")
            for name, impact in top_features[:5]:
                if impact > 0.01:
                    emoji = "⚡" if impact > 0.1 else "•"
                    parts.append(f"  {emoji} {name}: влияние {impact:.3f}")

        # Контекст из features
        if features:
            rsi = features.get("rsi", 50)
            if rsi < 30:
                parts.append(f"  • RSI перепродан ({rsi:.1f}) — возможен отскок")
            elif rsi > 70:
                parts.append(f"  • RSI перекуплен ({rsi:.1f}) — возможна коррекция")

            bb_pct = features.get("bb_pct", 50)
            if bb_pct < 10:
                parts.append(
                    f"  • Цена у нижней границы BB ({bb_pct:.1f}%) — поддержка"
                )
            elif bb_pct > 90:
                parts.append(
                    f"  • Цена у верхней границы BB ({bb_pct:.1f}%) — сопротивление"
                )

            adx = features.get("adx", 0)
            if adx > 25:
                parts.append(f"  • Сильный тренд (ADX={adx:.1f})")
            else:
                parts.append(f"  • Слабый тренд/флэт (ADX={adx:.1f})")

        # Сентимент
        if sentiment:
            s_score = sentiment.get("sentiment_score", 0)
            fg_label = sentiment.get("fear_greed", {}).get("label", "Neutral")
            parts.append(f"😰😀 Fear&Greed: {fg_label} (score={s_score:+.2f})")

        # Swarm
        if swarm_consensus:
            parts.append(f"🐝 Консенсус роя: {swarm_consensus}")

        # Prophet
        if prophet_signal:
            parts.append(f"🔮 Нейропророк: {prophet_signal}")

        return "\n".join(parts)


class CounterfactualGenerator:
    """
    Генерирует "что если" сценарии: что изменится, если бы
    ключевой признак был другим.
    """

    @staticmethod
    def generate(
        current_features: Dict[str, float],
        top_features: List[Tuple[str, float]],
        current_signal: str,
    ) -> List[dict]:
        """Сгенерировать контрфактуальные сценарии."""
        scenarios = []

        for name, _ in top_features[:3]:
            if name not in current_features:
                continue

            val = current_features[name]
            modified = dict(current_features)

            # Инвертируем ключевые признаки
            if name == "rsi":
                modified[name] = 100 - val  # инвертируем RSI
                alt_signal = (
                    "SELL"
                    if current_signal == "BUY"
                    else "BUY" if current_signal == "SELL" else "HOLD"
                )
                scenarios.append(
                    {
                        "changed_feature": name,
                        "from": round(val, 2),
                        "to": round(modified[name], 2),
                        "scenario": f"RSI инвертирован: {val:.1f} → {modified[name]:.1f}",
                        "hypothetical_signal": alt_signal,
                    }
                )

            elif name == "bb_pct":
                modified[name] = 100 - val
                alt_signal = (
                    "SELL"
                    if current_signal == "BUY"
                    else "BUY" if current_signal == "SELL" else "HOLD"
                )
                scenarios.append(
                    {
                        "changed_feature": name,
                        "from": round(val, 2),
                        "to": round(modified[name], 2),
                        "scenario": f"BB позиция инвертирована: {val:.1f}% → {modified[name]:.1f}%",
                        "hypothetical_signal": alt_signal,
                    }
                )

            elif name == "adx":
                modified[name] = max(0, val - 15) if val > 20 else min(50, val + 15)
                alt_signal = (
                    "HOLD" if current_signal in ("BUY", "SELL") else current_signal
                )
                scenarios.append(
                    {
                        "changed_feature": name,
                        "from": round(val, 2),
                        "to": round(modified[name], 2),
                        "scenario": f"ADX изменён: {val:.1f} → {modified[name]:.1f} (слабый тренд)",
                        "hypothetical_signal": alt_signal,
                    }
                )

        return scenarios


class TrustScore:
    """
    Оценка надёжности предсказания на основе:
    - Согласованности источников
    - Уверенности модели
    - Качества данных
    - Волатильности рынка
    """

    def __init__(self):
        self._history: deque = deque(maxlen=50)

    def compute(
        self,
        ai_confidence: float,
        ta_confidence: float,
        sentiment_confidence: float,
        swarm_confidence: float,
        prophet_confidence: float,
        data_quality: float = 1.0,
        market_volatility: float = 0.0,
    ) -> Tuple[float, str]:
        """
        Вернуть (trust_score_0_1, label).
        """
        # Согласованность источников
        confs = [
            c
            for c in [
                ai_confidence,
                ta_confidence,
                sentiment_confidence,
                swarm_confidence,
                prophet_confidence,
            ]
            if c > 0
        ]
        if not confs:
            return 0.0, "Нет данных"

        avg_conf = np.mean(confs)
        std_conf = np.std(confs) if len(confs) > 1 else 0
        agreement = 1.0 - min(
            1.0, std_conf / 30.0
        )  # чем меньше разброс → тем выше согласие

        # Штраф за волатильность
        vol_penalty = min(0.3, market_volatility / 50.0)

        # Штраф за низкое качество данных
        data_penalty = (1.0 - data_quality) * 0.2

        trust = avg_conf / 100.0 * agreement * (1 - vol_penalty) * (1 - data_penalty)
        trust = max(0.0, min(1.0, trust))

        self._history.append(trust)

        if trust >= 0.8:
            label = "Высокая надёжность"
        elif trust >= 0.6:
            label = "Хорошая надёжность"
        elif trust >= 0.4:
            label = "Средняя надёжность"
        elif trust >= 0.2:
            label = "Низкая надёжность"
        else:
            label = "Критически низкая"

        return round(trust, 4), label

    def get_trend(self) -> str:
        """Тренд надёжности."""
        if len(self._history) < 10:
            return "insufficient_data"
        recent = list(self._history)[-10:]
        earlier = list(self._history)[:10]
        if np.mean(recent) > np.mean(earlier) * 1.1:
            return "improving"
        elif np.mean(recent) < np.mean(earlier) * 0.9:
            return "degrading"
        return "stable"


class ExplanationLogger:
    """Логгер объяснений для аудита."""

    def __init__(self):
        self._explanations: deque = deque(maxlen=MAX_EXPLANATIONS)
        self._lock = threading.Lock()

    def log(self, explanation: dict):
        with self._lock:
            explanation["timestamp"] = time.time()
            self._explanations.append(explanation)

    def get_recent(self, n: int = 10) -> List[dict]:
        with self._lock:
            return list(self._explanations)[-n:]

    def get_stats(self) -> dict:
        with self._lock:
            if not self._explanations:
                return {}
            signals = [e.get("signal", "HOLD") for e in self._explanations]
            trusts = [e.get("trust_score", 0) for e in self._explanations]
            return {
                "total": len(self._explanations),
                "buy_count": signals.count("BUY"),
                "sell_count": signals.count("SELL"),
                "hold_count": signals.count("HOLD"),
                "avg_trust": round(np.mean(trusts), 4) if trusts else 0,
                "min_trust": round(min(trusts), 4) if trusts else 0,
                "max_trust": round(max(trusts), 4) if trusts else 0,
            }


class QuantumXAI:
    """Единый движок объяснимого ИИ."""

    def __init__(self):
        self._attribution = FeatureAttribution()
        self._explainer = DecisionExplainer()
        self._counterfactual = CounterfactualGenerator()
        self._trust = TrustScore()
        self._logger = ExplanationLogger()

    def explain_decision(
        self,
        signal: str,
        confidence: float,
        features: Dict[str, float],
        regime: str = "UNKNOWN",
        sentiment: Dict = None,
        swarm: Dict = None,
        prophet: Dict = None,
        ai_conf: float = 0,
        ta_conf: float = 0,
        sentiment_conf: float = 0,
        swarm_conf: float = 0,
        prophet_conf: float = 0,
        volatility: float = 0,
    ) -> dict:
        """Полное объяснение торгового решения."""
        # Top features
        top_features = self._attribution.get_top_features(5)

        # Объяснение
        explanation_text = self._explainer.explain(
            signal=signal,
            confidence=confidence,
            features=features,
            top_features=top_features,
            regime=regime,
            sentiment=sentiment,
            swarm_consensus=swarm.get("consensus", None) if swarm else None,
            prophet_signal=prophet.get("signal", None) if prophet else None,
        )

        # Контрфактуалы
        counterfactuals = self._counterfactual.generate(features, top_features, signal)

        # Trust score
        trust_score, trust_label = self._trust.compute(
            ai_confidence=ai_conf,
            ta_confidence=ta_conf,
            sentiment_confidence=sentiment_conf,
            swarm_confidence=swarm_conf,
            prophet_confidence=prophet_conf,
            market_volatility=volatility,
        )

        result = {
            "signal": signal,
            "confidence": round(confidence, 2),
            "explanation": explanation_text,
            "top_features": [(name, round(impact, 4)) for name, impact in top_features],
            "counterfactuals": counterfactuals,
            "trust_score": trust_score,
            "trust_label": trust_label,
            "trust_trend": self._trust.get_trend(),
            "regime": regime,
            "timestamp": time.time(),
        }

        self._logger.log(result)
        return result

    def record_prediction(self, prediction: float, features: Dict[str, float]):
        """Записать предсказание для attribution."""
        self._attribution.record_baseline(prediction)

    def get_feature_importance(self) -> List[Tuple[str, float]]:
        return self._attribution.get_importance()

    def get_explanation_stats(self) -> dict:
        return self._logger.get_stats()

    def get_recent_explanations(self, n: int = 10) -> List[dict]:
        return self._logger.get_recent(n)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_xai: Optional[QuantumXAI] = None


def get_xai() -> QuantumXAI:
    global _xai
    if _xai is None:
        _xai = QuantumXAI()
    return _xai


def explain(
    signal: str,
    confidence: float,
    features: Dict[str, float],
    **kwargs,
) -> dict:
    """Публичный API: объяснить решение."""
    xai = get_xai()
    return xai.explain_decision(signal, confidence, features, **kwargs)
