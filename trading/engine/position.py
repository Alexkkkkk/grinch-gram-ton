"""Position engine — open/close/monitor positions."""

import logging

logger = logging.getLogger(__name__)


class PositionEngine:
    """Manages position lifecycle: open, track, close."""

    def __init__(self, config=None):
        self.config = config
        self.positions: dict[str, dict] = {}

    def open(self, symbol: str, side: str, amount: float, price: float) -> dict:
        """Open a new position."""
        pos = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "entry_price": price,
            "status": "open",
        }
        self.positions[symbol] = pos
        logger.info("Position opened: %s %s @ %.4f", side, symbol, price)
        return pos

    def close(self, symbol: str, price: float) -> dict | None:
        """Close an existing position."""
        pos = self.positions.pop(symbol, None)
        if pos:
            pos["exit_price"] = price
            pos["status"] = "closed"
            profit = (price - pos["entry_price"]) * pos["amount"]
            logger.info("Position closed: %s PnL=%.4f", symbol, profit)
        return pos

    def get(self, symbol: str) -> dict | None:
        return self.positions.get(symbol)

    def list_open(self) -> list[dict]:
        return [p for p in self.positions.values() if p["status"] == "open"]
