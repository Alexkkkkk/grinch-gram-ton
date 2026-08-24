"""Trend analyzer — determine market regime."""

import logging

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Classify market as trending, ranging, or reversing."""

    def __init__(self, config=None):
        self.config = config

    def classify(self, adx: float, price_change_24h: float) -> str:
        """Classify market regime."""
        if adx > 28:
            return "trending_up" if price_change_24h > 0 else "trending_down"
        elif adx < 15:
            return "ranging"
        return "transition"
