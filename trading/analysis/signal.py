"""Signal generator — entry/exit signals from multiple sources."""

import logging

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Combine price action, indicators, and AI for signals."""

    def __init__(self, config=None):
        self.config = config

    def generate(self, price: float, indicators: dict) -> dict:
        """Generate trading signal."""
        rsi = indicators.get("rsi", 50)
        adx = indicators.get("adx", 0)
        score = 0
        reasons = []
        if rsi < 30:
            score += 30
            reasons.append("rsi_oversold")
        elif rsi > 70:
            score -= 30
            reasons.append("rsi_overbought")
        if adx > 25:
            score += 20
            reasons.append("trending")
        signal = "buy" if score > 20 else "sell" if score < -20 else "hold"
        return {
            "signal": signal,
            "score": score,
            "confidence": abs(score),
            "reasons": reasons,
        }
