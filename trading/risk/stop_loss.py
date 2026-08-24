"""Stop-loss engine — fixed and ATR-based stops."""
import logging

logger = logging.getLogger(__name__)


class StopLossEngine:
    """Calculate and track stop-loss levels."""

    def __init__(self, config=None):
        self.config = config

    def calculate(self, entry_price: float, atr: float = 0, side: str = "long") -> float:
        """Calculate stop-loss price."""
        if not self.config:
            return entry_price * 0.95
        sl_pct = getattr(self.config, "stop_loss_pct", 5.0)
        atr_mult = getattr(self.config, "atr_sl_mult", 2.5)
        if atr > 0:
            sl_pct = max(sl_pct, atr * atr_mult / entry_price * 100)
        if side == "long":
            return entry_price * (1 - sl_pct / 100)
        return entry_price * (1 + sl_pct / 100)
