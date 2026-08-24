"""Circuit breaker — halt trading on excessive losses."""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Halt trading when daily loss exceeds threshold."""

    def __init__(self, config=None):
        self.config = config
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.last_reset = datetime.utcnow().date()

    def check(self, trade_pnl: float) -> bool:
        """Return True if trading should HALT."""
        today = datetime.utcnow().date()
        if today != self.last_reset:
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.last_reset = today
        self.daily_pnl += trade_pnl
        self.trades_today += 1
        if not self.config:
            return False
        limit = getattr(self.config, "circuit_breaker_daily_loss_pct", 15.0)
        if self.daily_pnl < -limit:
            logger.warning("CIRCUIT BREAKER: daily loss %.2f%% exceeds %.2f%%", abs(self.daily_pnl), limit)
            return True
        return False
