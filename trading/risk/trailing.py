"""Trailing stop engine — multi-stage trailing."""
import logging

logger = logging.getLogger(__name__)


class TrailingStopEngine:
    """Multi-stage trailing stop with breakeven and profit locks."""

    STAGES = [
        (0, "base"),
        (6, "breakeven"),
        (12, "stage2"),
        (18, "stage3"),
        (26, "stage4"),
    ]

    def __init__(self, config=None):
        self.config = config

    def update(self, entry_price: float, current_price: float, side: str = "long") -> dict:
        """Update trailing stop level."""
        profit_pct = abs(current_price - entry_price) / entry_price * 100
        stage = "base"
        for threshold, name in self.STAGES:
            if profit_pct >= threshold:
                stage = name
        trail_pct = getattr(self.config, f"{stage}_pct", 13.0) if self.config else 13.0
        if side == "long":
            stop = current_price * (1 - trail_pct / 100)
        else:
            stop = current_price * (1 + trail_pct / 100)
        return {"stage": stage, "stop_price": stop, "trail_pct": trail_pct, "profit_pct": profit_pct}
