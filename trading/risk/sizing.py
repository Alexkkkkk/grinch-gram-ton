"""Position sizing — Kelly, risk-based, and fixed sizing."""
import logging

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculate optimal position size based on risk parameters."""

    def __init__(self, config=None):
        self.config = config

    def fixed(self, capital: float, pct: float = 10.0) -> float:
        return capital * pct / 100

    def risk_based(self, capital: float, risk_pct: float, stop_loss_pct: float) -> float:
        """Risk-based sizing: risk $X per trade."""
        if stop_loss_pct <= 0:
            return 0
        risk_amount = capital * risk_pct / 100
        return risk_amount / (stop_loss_pct / 100)

    def kelly(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly criterion fraction."""
        if avg_loss == 0:
            return 0
        q = 1 - win_rate
        k = (win_rate * avg_win - q * avg_loss) / avg_loss
        return max(0, min(k, 0.25))  # Cap at 25%
