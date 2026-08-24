"""Grid engine — spot grid trading logic."""

import logging
from typing import List

logger = logging.getLogger(__name__)


class GridEngine:
    """Spot grid trading with adaptive step sizing."""

    def __init__(self, config=None):
        self.config = config
        self.levels: List[dict] = []

    def build_levels(self, center: float, count: int, step_pct: float) -> List[dict]:
        """Build grid levels around center price."""
        self.levels = []
        for i in range(-count // 2, count // 2 + 1):
            price = center * (1 + i * step_pct / 100)
            self.levels.append(
                {
                    "index": i,
                    "price": round(price, 6),
                    "side": "buy" if i < 0 else "sell" if i > 0 else "neutral",
                    "active": True,
                }
            )
        logger.info("Grid built: %d levels around %.4f", len(self.levels), center)
        return self.levels

    def recenter(self, new_center: float) -> List[dict]:
        """Recalculate grid levels around new center."""
        if not self.levels:
            return []
        step = (
            (self.levels[1]["price"] - self.levels[0]["price"])
            / self.levels[0]["price"]
            * 100
        )
        return self.build_levels(new_center, len(self.levels), step)
