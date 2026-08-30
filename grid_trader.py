"""
grid_trader.py — AI-Powered Spot Grid (QuantumGrid v7.1)
Synchronized with core.config.GridConfig and core.base_components.GridLevel
"""

import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from core.base_components import GridLevel as BaseGridLevel
from core.config import Config

log = logging.getLogger("grid")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
STATE_FILE = os.path.join(DATA_DIR, "grid_state.json")
TRADE_HISTORY_FILE = os.path.join(DATA_DIR, "grid_trade_history.json")

# Use unified GridConfig from core.config
GridCfg = Config.GRID


@dataclass
class GridLevel:
    """Grid level compatible with BaseGridLevel but extended for trading."""

    id: int
    side: str
    price_ton: float
    amount_grinch: float = 0.0
    amount_ton: float = 0.0
    status: str = "waiting"
    filled_at: Optional[float] = None
    fill_price_ton: float = 0.0
    profit_ton: float = 0.0
    tx_hash: str = ""
    note: str = ""

    def to_base(self) -> BaseGridLevel:
        """Convert to memory-optimized base level."""
        base = BaseGridLevel(
            self.price_ton, self.side, self.amount_grinch or self.amount_ton
        )
        base.filled = self.status == "filled"
        return base


@dataclass
class GridState:
    active: bool = False
    center_price: float = 0.0
    step_pct: float = 0.0
    upper_price: float = 0.0
    lower_price: float = 0.0
    sell_levels: List[GridLevel] = field(default_factory=list)
    buy_levels: List[GridLevel] = field(default_factory=list)
    completed_fills: List[GridLevel] = field(default_factory=list)
    total_profit_ton: float = 0.0
    total_sell_cycles: int = 0
    grid_reserved_grinch: float = 0.0
    last_action: str = ""
    last_rebuild: float = 0.0
    last_tick: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0

    def to_dict(self):
        d = asdict(self)
        d["sell_levels"] = [asdict(l) for l in self.sell_levels]
        d["buy_levels"] = [asdict(l) for l in self.buy_levels]
        d["completed_fills"] = [asdict(l) for l in self.completed_fills]
        return d

    @classmethod
    def from_dict(cls, d):
        s = cls()
        for k, v in d.items():
            if k in ("sell_levels", "buy_levels", "completed_fills"):
                setattr(s, k, [GridLevel(**l) for l in (v or [])])
            elif hasattr(s, k):
                setattr(s, k, v)
        return s


class GridTrader:
    # AI Control settings from unified config
    AI_ENABLED = True
    AI_AUTO_START = True
    AI_AUTO_STOP = True
    AI_MIN_CONFIDENCE = 60.0
    AI_PAUSE_ON_TRAP = True
    AI_DYNAMIC_STEP = True
    AI_MAX_DRAWDOWN_PCT = 35.0

    def __init__(self):
        self._dc = None
        self._ai = None
        self._trader = None
        self._price_feed = None
        self._state = GridState()
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._load_state()
        self._trade_history: List[dict] = []
        self._load_trade_history()
        self._price_history: List[float] = []
        self._candles: List[dict] = []

        # AI state
        self._ai_enabled = self.AI_ENABLED
        self._ai_last_signal = "HOLD"
        self._ai_last_confidence = 0.0
        self._ai_trap_detected = False
        self._ai_pause_reason = ""
        self._ai_recommendation = {}

    def inject(
        self, dedust_client=None, ai_engine=None, trader_ref=None, price_feed=None
    ):
        self._dc = dedust_client
        self._ai = ai_engine
        self._trader = trader_ref
        self._price_feed = price_feed

    @property
    def is_active(self) -> bool:
        # The poller keeps the lock while talking to external services.  A
        # read-only status request must never wait on that network I/O.
        return bool(self._state.active)

    def start_poller(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="grid-poller"
        )
        self._thread.start()
        log.info("[Grid] Poller started (AI=%s)", self._ai_enabled)

    def stop(self):
        self._stop.set()

    def stop_grid(self):
        with self._lock:
            self._state.active = False
            self._save_state()
        log.info("[Grid] Grid stopped")

    def start_grid(self) -> dict:
        """Resume an already-built grid without silently creating a new one."""
        with self._lock:
            if not self._state.sell_levels and not self._state.buy_levels:
                return {"ok": False, "error": "Grid is not built"}
            self._state.active = True
            self._save_state()
        log.info("[Grid] Grid started")
        return {"ok": True}

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log.error("[Grid] tick error: %s", e)
            self._stop.wait(GridCfg.tick_sec or 15)

    def _get_price(self):
        try:
            if self._dc and hasattr(self._dc, "get_grinch_ton_price"):
                return self._dc.get_grinch_ton_price()
            if self._trader and hasattr(self._trader, "get_price"):
                return self._trader.get_price()
            if self._price_feed:
                price = self._price_feed()
                if price and price > 0:
                    return price
        except Exception as e:
            log.debug("[Grid] price error: %s", e)
        return 0.0

    def _get_balances(self):
        try:
            if self._trader and hasattr(self._trader, "get_balances"):
                return self._trader.get_balances()
            if self._dc and hasattr(self._dc, "get_balances"):
                return self._dc.get_balances()
        except Exception as e:
            log.debug("[Grid] balance error: %s", e)
        return None, None

    def _calc_atr_pct(self):
        if len(self._price_history) < 5:
            return GridCfg.step_pct
        recent = self._price_history[-20:]
        if len(recent) < 2:
            return GridCfg.step_pct
        trs = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
        atr = sum(trs) / len(trs)
        current = recent[-1]
        return (atr / current * 100) if current > 0 else GridCfg.step_pct

    def _detect_regime(self):
        if len(self._price_history) < 14:
            return "SIDEWAYS"
        prices = self._price_history[-30:]
        sma7 = sum(prices[-7:]) / 7
        sma14 = sum(prices[-14:]) / 14
        current = prices[-1]
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))
        ]
        vol = sum(r**2 for r in returns) / len(returns) ** 0.5 if returns else 0

        if vol > 0.03:
            if current > sma7 > sma14:
                return "TREND_UP"
            elif current < sma7 < sma14:
                return "TREND_DOWN"
            return "VOLATILE"
        if current > sma7 * 1.02:
            return "TREND_UP"
        elif current < sma7 * 0.98:
            return "TREND_DOWN"
        return "SIDEWAYS"

    def _update_ai(self, price_ton):
        from quantum_brain import get_brain

        brain = get_brain()
        brain.state.price = price_ton
        brain.state.price_history.append(price_ton)
        state = brain.get_state()

        self._ai_last_signal = state["unified"]["signal"]
        self._ai_last_confidence = state["unified"]["confidence"]
        self._ai_trap_detected = state["grid_ai"]["trap_detected"]
        self._ai_pause_reason = (
            "Pause buying" if state["grid_ai"]["pause_buying"] else ""
        )
        self._ai_recommendation = state

        if state["unified"]["action"] == "STOP" and self._state.active:
            log.warning("[QuantumBrain] Auto-stop: unified action = STOP")
            self._state.active = False
            self._ai_pause_reason = "AI: Unified STOP"
            return
        if state["unified"]["action"] == "PAUSE_BUY":
            self._ai_pause_reason = "AI: Unified PAUSE_BUY"
            return
        if state["unified"]["action"] in ("BUILD", "START") and not self._state.active:
            log.info("[QuantumBrain] Auto-start: action=%s", state["unified"]["action"])
            self.ai_build_grid(price_ton)

    def _calc_drawdown(self, current_price):
        if not self._state.center_price or self._state.center_price <= 0:
            return 0.0
        return abs(
            (current_price - self._state.center_price) / self._state.center_price * 100
        )

    def _tick(self):
        with self._lock:
            price_ton = self._get_price()
            if not price_ton:
                return
            self._state.last_tick = time.time()
            self._price_history.append(price_ton)
            if len(self._price_history) > 100:
                self._price_history = self._price_history[-100:]

            self._update_ai(price_ton)

            if not self._state.active or not self._state.sell_levels:
                self._maybe_build_grid(price_ton)
                return

            if self._should_recenter(price_ton):
                log.info("[Grid] Recenter triggered @ %.6f", price_ton)
                self._maybe_build_grid(price_ton)
                return

            # SELL
            for level in self._state.sell_levels:
                if level.status == "waiting" and price_ton >= level.price_ton:
                    res = self._execute_sell(level, price_ton)
                    if res.get("ok"):
                        self._record_trade("SELL", level, price_ton)
                        self._state.last_action = (
                            f"SELL L{level.id}: {level.amount_grinch:.0f} @ {price_ton:.6f} "
                            f"| profit {level.profit_ton:+.3f} TON"
                        )
                        log.info("[Grid] %s", self._state.last_action)
                        self._place_rebuy(level)
                        if self._ai:
                            try:
                                self._ai.record_fill(
                                    side="sell",
                                    step_used=self._state.step_pct,
                                    atr_pct=self._calc_atr_pct(),
                                    regime=self._detect_regime(),
                                    profit_ton=level.profit_ton,
                                    profit_pct=(
                                        level.profit_ton / max(level.amount_ton, 0.001)
                                    )
                                    * 100,
                                )
                            except Exception:
                                pass
                    self._save_state()
                    return

            # BUY
            for level in self._state.buy_levels:
                if level.status == "waiting" and price_ton <= level.price_ton:
                    if (
                        self._ai_pause_reason
                        and "Pause buying" in self._ai_pause_reason
                    ):
                        log.info("[Grid AI] Skipping BUY: %s", self._ai_pause_reason)
                        return
                    res = self._execute_buy(level, price_ton)
                    if res.get("ok"):
                        self._record_trade("BUY", level, price_ton)
                        self._state.last_action = f"BUY L{level.id}: {level.amount_grinch:.0f} @ {price_ton:.6f}"
                        log.info("[Grid] %s", self._state.last_action)
                        self._place_resell(level)
                        if self._ai:
                            try:
                                self._ai.record_fill(
                                    side="buy",
                                    step_used=self._state.step_pct,
                                    atr_pct=self._calc_atr_pct(),
                                    regime=self._detect_regime(),
                                    profit_ton=0,
                                    profit_pct=0,
                                )
                            except Exception:
                                pass
                    self._save_state()
                    return

    def _should_recenter(self, price_ton):
        if not self._state.center_price or not self._state.step_pct:
            return False
        steps_away = abs(math.log(price_ton / self._state.center_price)) / math.log(
            1 + self._state.step_pct / 100
        )
        if steps_away >= GridCfg.recenter_threshold:
            if time.time() - self._state.last_rebuild >= GridCfg.recenter_cooldown:
                return True
        return False

    def _maybe_build_grid(self, center_price):
        ton_bal, grin_bal = self._get_balances()
        if ton_bal is None:
            # Rate-limit warning: log only once per minute to avoid spam
            now = time.time()
            if (
                not hasattr(self, "_last_balance_warn")
                or now - self._last_balance_warn > 60
            ):
                log.warning(
                    "[Grid] No balances available (TON_MNEMONIC not set?), skipping grid build"
                )
                self._last_balance_warn = now
            return
        atr_pct = self._calc_atr_pct()
        step = self._adaptive_step(atr_pct)
        self.build_grid(
            center_price, step_pct=step, grinch_balance=grin_bal, ton_balance=ton_bal
        )

    @staticmethod
    def _adaptive_step(atr_pct):
        if not GridCfg.adaptive_step:
            return GridCfg.step_pct
        if atr_pct >= 8.0:
            return min(GridCfg.max_step_pct or 8.0, 7.0)
        elif atr_pct >= 5.0:
            return min(GridCfg.max_step_pct or 8.0, 5.0)
        elif atr_pct >= 3.0:
            return 4.0
        return max(GridCfg.min_step_pct or 3.0, 3.0)

    @staticmethod
    def _min_profitable_order_ton(step_pct):
        fee = Config.FEES.pct / 100.0
        step = float(step_pct) if step_pct else GridCfg.step_pct
        step = max(step, 0.0)
        cycle_factor = (1.0 + step / 100.0) * (1.0 - fee) ** 2 - 1.0
        if cycle_factor <= 0:
            return float("inf")
        gas_min = (0.30 * 2.0) / cycle_factor
        return max(15.0, math.ceil(gas_min * 10.0) / 10.0)

    def build_grid(
        self,
        center_price,
        step_pct=None,
        sell_levels=None,
        buy_levels=None,
        grinch_balance=None,
        ton_balance=None,
    ):
        with self._lock:
            step = step_pct or GridCfg.step_pct
            step = max(
                GridCfg.min_step_pct or 3.0, min(GridCfg.max_step_pct or 8.0, step)
            )
            n_sell = sell_levels or GridCfg.sell_levels or 20
            n_buy = buy_levels or GridCfg.buy_levels or 20

            s = GridState()
            s.active = True
            s.center_price = center_price
            s.step_pct = step
            s.last_rebuild = time.time()

            s.upper_price = float(
                (
                    Decimal(str(center_price))
                    * (Decimal("1") + Decimal(str(step)) / Decimal("100")) ** n_sell
                ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            )
            s.lower_price = round(center_price / (1 + step / 100) ** n_buy, 6)

            avail_grinch = max(0.0, float(grinch_balance or 0.0))
            grin_per_sell = avail_grinch / n_sell if n_sell > 0 else 0

            for i in range(1, n_sell + 1):
                price = center_price * (1 + step / 100) ** i
                s.sell_levels.append(
                    GridLevel(
                        id=i,
                        side="sell",
                        price_ton=round(price, 6),
                        amount_grinch=round(grin_per_sell, 2),
                        amount_ton=0,
                    )
                )
            s.grid_reserved_grinch = avail_grinch

            avail_ton = max(
                0.0, float(ton_balance or 0.0) - (GridCfg.gas_reserve_ton or 5.0)
            )
            ton_per_buy = avail_ton / n_buy if n_buy > 0 else 0
            min_order = self._min_profitable_order_ton(step)

            for i in range(1, n_buy + 1):
                price = center_price / (1 + step / 100) ** i
                amount_ton = ton_per_buy if ton_per_buy >= min_order else 0
                s.buy_levels.append(
                    GridLevel(
                        id=-i,
                        side="buy",
                        price_ton=round(price, 6),
                        amount_grinch=0,
                        amount_ton=round(amount_ton, 2),
                    )
                )

            self._state = s
            self._save_state()
            log.info(
                "[Grid] Built: center=%.6f step=%.1f%% sell=%d buy=%d "
                "upper=%.6f lower=%.6f grin=%.0f ton=%.1f",
                center_price,
                step,
                n_sell,
                n_buy,
                s.upper_price,
                s.lower_price,
                avail_grinch,
                avail_ton,
            )
            return s

    def ai_build_grid(self, center_price):
        """Public API for AI-triggered grid build."""
        self._maybe_build_grid(center_price)

    def _execute_sell(self, level, price_ton):
        try:
            if level.amount_grinch <= 0:
                return {"ok": False, "error": "zero_amount"}
            if self._dc and hasattr(self._dc, "sell"):
                result = self._dc.sell(level.amount_grinch)
                if result.get("ok"):
                    received_ton = result.get("received_ton", 0)
                    level.status = "filled"
                    level.filled_at = time.time()
                    level.fill_price_ton = price_ton
                    level.profit_ton = received_ton - level.amount_ton
                    level.tx_hash = result.get("tx_hash", "")
                    self._state.total_profit_ton += level.profit_ton
                    self._state.total_sell_cycles += 1
                    return {"ok": True, "received": received_ton}
            return {"ok": False, "error": "no_dedust_client"}
        except Exception as e:
            log.error("[Grid] sell error: %s", e)
            return {"ok": False, "error": str(e)}

    def _execute_buy(self, level, price_ton):
        try:
            if level.amount_ton <= 0:
                return {"ok": False, "error": "zero_amount"}
            if self._dc and hasattr(self._dc, "buy"):
                result = self._dc.buy(level.amount_ton)
                if result.get("ok"):
                    received_grinch = result.get("received_grinch", 0)
                    level.status = "filled"
                    level.filled_at = time.time()
                    level.fill_price_ton = price_ton
                    level.amount_grinch = received_grinch
                    level.tx_hash = result.get("tx_hash", "")
                    return {"ok": True, "received": received_grinch}
            return {"ok": False, "error": "no_dedust_client"}
        except Exception as e:
            log.error("[Grid] buy error: %s", e)
            return {"ok": False, "error": str(e)}

    def _place_rebuy(self, level):
        """Place a new buy level after sell fill."""
        pass  # Implement if needed

    def _place_resell(self, level):
        """Place a new sell level after buy fill."""
        pass  # Implement if needed

    def _record_trade(self, side, level, price):
        trade = {
            "side": side,
            "level_id": level.id,
            "price": price,
            "amount_grinch": level.amount_grinch,
            "amount_ton": level.amount_ton,
            "profit_ton": level.profit_ton,
            "timestamp": time.time(),
        }
        self._trade_history.append(trade)
        if len(self._trade_history) > 1000:
            self._trade_history = self._trade_history[-800:]
        self._save_trade_history()

    def get_trade_history(self):
        with self._lock:
            return list(self._trade_history)

    def get_state_dict(self):
        with self._lock:
            return self._state.to_dict()

    def _save_state(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self._state.to_dict(), f)
        except Exception as e:
            log.warning("[Grid] save state error: %s", e)

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    self._state = GridState.from_dict(json.load(f))
        except Exception as e:
            log.warning("[Grid] load state error: %s", e)

    def _save_trade_history(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(TRADE_HISTORY_FILE, "w") as f:
                json.dump(self._trade_history, f)
        except Exception as e:
            log.warning("[Grid] save history error: %s", e)

    def _load_trade_history(self):
        try:
            if os.path.exists(TRADE_HISTORY_FILE):
                with open(TRADE_HISTORY_FILE, "r") as f:
                    self._trade_history = json.load(f)
        except Exception as e:
            log.warning("[Grid] load history error: %s", e)
