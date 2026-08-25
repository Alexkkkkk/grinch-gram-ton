"""Scalping engine — quick in-and-out trades."""

import logging

logger = logging.getLogger(__name__)


class ScalpEngine:
    """High-frequency scalp trades with tight stops."""

    def __init__(self, config=None):
        self.config = config

    def evaluate(self, spread_pct: float, volatility: float) -> dict:
        """Evaluate scalp opportunity."""
        if not self.config or not getattr(self.config, "enabled", False):
            return {"signal": "hold", "confidence": 0}
        target = getattr(self.config, "target_net_pct", 3.0)
        max_atr = getattr(self.config, "max_atr_pct", 8.0)
        if volatility > max_atr:
            return {"signal": "hold", "confidence": 0, "reason": "volatility_too_high"}
        if spread_pct < target * 0.5:
            return {"signal": "hold", "confidence": 0, "reason": "spread_too_low"}
        return {
            "signal": "scalp",
            "confidence": min(100, spread_pct / target * 50),
            "target": target,
        }
