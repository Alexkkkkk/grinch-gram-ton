"""Refactored Trader — orchestrates PositionManager + AI + Exchange."""
import json
import logging
import os
import threading
import time
from datetime import datetime

from core.base_components import BaseWorker
from core.config import Config
from core.events import emit, EVENT_TRADE_CLOSED, EVENT_TRADE_OPENED
from exchange import ExchangeClient

logger = logging.getLogger(__name__)


class Trader(BaseWorker):
    """Simplified trader using BaseWorker lifecycle."""

    __slots__ = (
        "exchange",
        "_ai",
        "_positions",
        "_trading_enabled",
        "_last_disabled_log_ts",
        "_balance_cache",
        "_balance_cache_ts",
    )

    def __init__(self):
        super().__init__(name="trader", interval_sec=Config.GRID.tick_sec)
        self.exchange = ExchangeClient()
        self._ai = None  # lazy
        self._positions = None  # lazy
        self._trading_enabled = True
        self._last_disabled_log_ts = 0.0
        self._balance_cache: dict = {}
        self._balance_cache_ts = 0.0

    @property
    def ai(self):
        if self._ai is None:
            from ai import get_ai_engine
            self._ai = get_ai_engine()
        return self._ai

    @property
    def positions(self):
        if self._positions is None:
            from trading.position_manager import PositionManager
            self._positions = PositionManager()
            # Restore from DB
            try:
                import db_store
                if db_store.is_available():
                    saved = db_store.open_trades_get()
                    for t in saved:
                        self._positions.add(t)
            except Exception:
                pass
        return self._positions

    def _tick(self) -> None:
        if not self._trading_enabled:
            now = time.time()
            if now - self._last_disabled_log_ts >= 300:
                logger.info("Trading disabled (manual switch)")
                self._last_disabled_log_ts = now
            return

        try:
            price = self.exchange.get_live_price()
            ohlcv = self.exchange.get_ohlcv(limit=30)
            if not ohlcv:
                return

            signal = self.ai.analyze(ohlcv)
            conf = signal.get("confidence", 0)
            action = signal.get("ai_signal", "HOLD")

            # Grid logic takes precedence if enabled
            if Config.GRID.enabled:
                self._grid_tick(price)
                return

            # Simple AI-driven spot logic
            if action == "BUY" and conf >= Config.AI.min_confidence:
                self._maybe_buy(price, signal)
            elif action == "SELL":
                self._maybe_sell(price, signal)

        except Exception as exc:
            logger.warning("[Trader] tick error: %s", exc)

    def _grid_tick(self, price: float) -> None:
        """Delegate to grid trader if available."""
        try:
            from grid_trader import get_grid_trader
            grid = get_grid_trader()
            grid.tick(price)
        except Exception as exc:
            logger.debug("[Trader] grid tick: %s", exc)

    def _maybe_buy(self, price: float, signal: dict) -> None:
        bal = self._get_balance()
        free_ton = bal.get("TON", 0)
        if free_ton < Config.TRADE_AMOUNT + Config.FEES.gas_reserve_ton:
            return
        stake = min(Config.TRADE_AMOUNT, free_ton - Config.FEES.gas_reserve_ton)
        amount = stake / price if price > 0 else 0
        trade = {
            "id": f"t{int(time.time()*1000)}",
            "entry_price": price,
            "amount": amount,
            "stake_ton": stake,
            "trade_type": "long",
            "opened_at": datetime.utcnow().isoformat(),
            "signal": signal,
        }
        self.positions.add(trade)
        emit(EVENT_TRADE_OPENED, trade)
        logger.info("[Trader] BUY %.4f TON @ %.8f", stake, price)

    def _maybe_sell(self, price: float, signal: dict) -> None:
        for t in self.positions.open_trades:
            entry = t.get("entry_price", 0)
            if entry <= 0:
                continue
            gross_pct = (price - entry) / entry * 100
            # Only profit exit
            if gross_pct < Config.FEES.round_trip:
                continue
            pnl = t.get("amount", 0) * (price - entry)
            if pnl < Config.MIN_PROFIT_TON_ABS:
                continue
            self.positions.close(t, pnl)
            emit(EVENT_TRADE_CLOSED, {"trade": t, "pnl": pnl, "price": price})
            logger.info("[Trader] SELL pnl=%.4f TON @ %.8f", pnl, price)

    def _get_balance(self) -> dict:
        now = time.time()
        if now - self._balance_cache_ts < 30 and self._balance_cache:
            return self._balance_cache
        try:
            self._balance_cache = self.exchange.get_balance()
            self._balance_cache_ts = now
        except Exception:
            pass
        return self._balance_cache

    def enable_trading(self) -> None:
        self._trading_enabled = True
        logger.info("[Trader] Trading ENABLED")

    def disable_trading(self) -> None:
        self._trading_enabled = False
        logger.info("[Trader] Trading DISABLED")

    def get_status(self) -> dict:
        stats = self.positions.get_stats()
        return {
            "running": self._running,
            "trading_enabled": self._trading_enabled,
            "positions": stats,
            "ai_signal": "HOLD",  # cached
        }
