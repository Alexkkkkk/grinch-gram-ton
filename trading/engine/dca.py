"""DCA engine — dollar-cost averaging logic."""

import logging
from typing import List

logger = logging.getLogger(__name__)


class DcaEngine:
    """DCA with cascade levels and smart re-entry."""

    def __init__(self, config=None):
        self.config = config
        self.entries: List[dict] = []

    def should_enter(self, drop_pct: float, pullback_pct: float) -> bool:
        """Check if DCA entry conditions are met."""
        if not self.config or not getattr(self.config, "enabled", False):
            return False
        trigger = getattr(self.config, "drop_trigger_pct", 10)
        wait = getattr(self.config, "pullback_wait_pct", 13)
        return drop_pct >= trigger and pullback_pct >= wait

    def add_entry(self, price: float, amount: float) -> dict:
        entry = {"price": price, "amount": amount, "timestamp": None}
        self.entries.append(entry)
        avg = sum(e["price"] * e["amount"] for e in self.entries) / sum(
            e["amount"] for e in self.entries
        )
        logger.info("DCA entry: %.4f x %.2f | avg=%.4f", price, amount, avg)
        return entry
