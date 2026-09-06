"""Small repository facade over the project's existing database store."""

from __future__ import annotations

from typing import Any, Iterable

import db_store


class TradeRepository:
    """Persistence facade kept stable for callers using the db package."""

    def upsert(self, trade: dict[str, Any]) -> Any:
        return db_store.trades_upsert(trade)

    def create(self, trade: dict[str, Any]) -> Any:
        return self.upsert(trade)

    def get_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        return db_store.trades_get_all(limit or db_store.TRADES_LIMIT)

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.get_all(limit)

    def get_recent(self, limit: int = 30) -> list[dict[str, Any]]:
        return db_store.trades_get_recent(limit)

    def count(self) -> int:
        return db_store.trades_count()

    def bulk_insert(self, trades: Iterable[dict[str, Any]]) -> Any:
        return db_store.trades_bulk_insert(list(trades))

    def save_open(self, trades: list[dict[str, Any]]) -> Any:
        return db_store.open_trades_save(trades)

    def get_open(self) -> list[dict[str, Any]]:
        return db_store.open_trades_get()
