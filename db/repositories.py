"""Repository pattern for database access."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TradeRepository:
    """Unified trade storage — replaces scattered db_store calls."""

    def __init__(self, session=None):
        self._session = session

    def save(self, trade: Dict[str, Any]) -> None:
        try:
            import db_store

            if db_store.is_available():
                db_store.trade_save(trade)
        except Exception as exc:
            logger.warning("[TradeRepo] save failed: %s", exc)

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            import db_store

            if db_store.is_available():
                return db_store.trades_get_recent(limit)
        except Exception as exc:
            logger.warning("[TradeRepo] get_recent failed: %s", exc)
        return []

    def get_open(self) -> List[Dict[str, Any]]:
        try:
            import db_store

            if db_store.is_available():
                return db_store.open_trades_get()
        except Exception as exc:
            logger.warning("[TradeRepo] get_open failed: %s", exc)
        return []
