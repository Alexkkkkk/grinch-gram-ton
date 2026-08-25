"""Refactored Trader — orchestrates PositionManager + AI + Exchange."""

import logging
import secrets
import time
from datetime import datetime

from core.base_components import BaseWorker
from core.config import Config
from core.events import EVENT_TRADE_CLOSED, EVENT_TRADE_OPENED, emit

logger = logging.getLogger(__name__)


class Trader(BaseWorker):
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
        self.exchange = None  # lazy init
        self._ai = None
        self._positions = None
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
            try:
                import db_store

                if hasattr(db_store, "is_available") and db_store.is_available():
                    for t in db_store.open_trades_get():
                        self._positions.add(t)
            except Exception:
                pass
        return self._positions

    def _get_exchange(self):
        if self.exchange is None:
            try:
                from exchange import ExchangeClient

                self.exchange = ExchangeClient()
            except Exception as exc:
                logger.warning("Exchange init failed: %s", exc)
        return self.exchange

    def _tick(self) -> None:
        if not self._trading_enabled:
            now = time.time()
            if now - self._last_disabled_log_ts >= 300:
                logger.info("Trading disabled (manual switch)")
                self._last_disabled_log_ts = now
            return

        ex = self._get_exchange()
        if ex is None:
            return

        try:
            price = ex.get_live_price()
            ohlcv = ex.get_ohlcv(limit=30)
            if not ohlcv:
                return

            signal = self.ai.analyze(ohlcv)
            conf = signal.get("confidence", 0)
            action = signal.get("ai_signal", "HOLD")

            if Config.GRID.enabled:
                self._grid_tick(price)
                return

            if action == "BUY" and conf >= Config.AI.min_confidence:
                self._maybe_buy(price, signal)
            elif action == "SELL":
                self._maybe_sell(price, signal)

        except Exception as exc:
            logger.warning("Tick error: %s", exc)

    def _grid_tick(self, price: float) -> None:
        try:
            from grid_trader import get_grid_trader

            grid = get_grid_trader()
            grid.tick(price)
        except Exception as exc:
            logger.debug("Grid tick: %s", exc)

    def _maybe_buy(self, price: float, signal: dict) -> None:
        bal = self._get_balance()
        free_ton = bal.get("TON", 0)
        if free_ton < Config.TRADE_AMOUNT + Config.FEES.gas_reserve_ton:
            return
        stake = min(Config.TRADE_AMOUNT, free_ton - Config.FEES.gas_reserve_ton)
        amount = stake / price if price > 0 else 0
        trade = {
            "id": f"t{secrets.token_hex(8)}",
            "entry_price": price,
            "amount": amount,
            "stake_ton": stake,
            "trade_type": "long",
            "opened_at": datetime.utcnow().isoformat(),
            "signal": signal,
        }
        self.positions.add(trade)
        emit(EVENT_TRADE_OPENED, trade)
        logger.info("BUY %.4f TON @ %.8f", stake, price)

    def _maybe_sell(self, price: float, signal: dict) -> None:
        for t in self.positions.open_trades:
            entry = t.get("entry_price", 0)
            if entry <= 0:
                continue
            gross_pct = (price - entry) / entry * 100
            if gross_pct < Config.FEES.round_trip:
                continue
            pnl = t.get("amount", 0) * (price - entry)
            if pnl < Config.MIN_PROFIT_TON_ABS:
                continue
            self.positions.close(t, pnl)
            emit(EVENT_TRADE_CLOSED, {"trade": t, "pnl": pnl, "price": price})
            logger.info("SELL pnl=%.4f TON @ %.8f", pnl, price)

    def _get_balance(self) -> dict:
        now = time.time()
        if now - self._balance_cache_ts < 30 and self._balance_cache:
            return self._balance_cache
        try:
            ex = self._get_exchange()
            if ex:
                self._balance_cache = ex.get_balance()
                self._balance_cache_ts = now
        except Exception:
            pass
        return self._balance_cache

    def enable_trading(self) -> None:
        self._trading_enabled = True
        logger.info("Trading ENABLED")

    def disable_trading(self) -> None:
        self._trading_enabled = False
        logger.info("Trading DISABLED")

    def get_status(self) -> dict:
        stats = self.positions.get_stats()
        return {
            "running": self._running,
            "trading_enabled": self._trading_enabled,
            "positions": stats,
        }
