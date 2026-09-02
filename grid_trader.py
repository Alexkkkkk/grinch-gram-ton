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
    amount_token: float = 0.0
    amount_ton: float = 0.0
    status: str = "waiting"
    filled_at: Optional[float] = None
    fill_price_ton: float = 0.0
    profit_ton: float = 0.0
    # Total TON cost of the paired buy, including the estimated network fee.
    entry_cost_ton: float = 0.0
    tx_hash: str = ""
    note: str = ""

    def to_base(self) -> BaseGridLevel:
        """Convert to memory-optimized base level."""
        base = BaseGridLevel(
            self.price_ton, self.side, self.amount_token or self.amount_ton
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
    grid_reserved_token: float = 0.0
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
        self._ai_recommended_step = 0.0
        self._ai_recommended_investment_ton = None
        self._ai_recommended_sell_levels = None
        self._ai_recommended_buy_levels = None

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
            # DedustClient exposes the read-only wallet query as get_balance
            # (singular). Normalize it to the tuple expected by the grid.
            if self._dc and hasattr(self._dc, "get_balance"):
                balances = self._dc.get_balance()
                if isinstance(balances, dict):
                    ton = float(balances.get("TON", 0) or 0)
                    token_key = getattr(Config, "TOKEN_SYMBOL", "USDT")
                    token = balances.get(token_key, balances.get("USDT", 0))
                    return ton, float(token or 0)
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
        kimi = state.get("kimi", {})
        try:
            self._ai_recommended_step = (
                float(kimi.get("step_pct", 0) or 0) if kimi.get("ready") else 0.0
            )
        except (TypeError, ValueError):
            self._ai_recommended_step = 0.0
        try:
            self._ai_recommended_investment_ton = (
                float(kimi.get("investment_ton"))
                if kimi.get("ready") and kimi.get("investment_ton") is not None
                else None
            )
            self._ai_recommended_sell_levels = (
                int(kimi.get("sell_levels", 0) or 0) if kimi.get("ready") else 0
            )
            self._ai_recommended_buy_levels = (
                int(kimi.get("buy_levels", 0) or 0) if kimi.get("ready") else 0
            )
        except (TypeError, ValueError):
            self._ai_recommended_investment_ton = None
            self._ai_recommended_sell_levels = None
            self._ai_recommended_buy_levels = None

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
            kimi_blocked = (
                self._ai
                and hasattr(self._ai, "kimi_required_for_auto_grid")
                and self._ai.kimi_required_for_auto_grid()
                and not self._ai.kimi_allows_initial_build()
            )
            if not kimi_blocked:
                self.ai_build_grid(
                    price_ton,
                    step_pct=self._ai_recommended_step or None,
                    investment_ton=self._ai_recommended_investment_ton,
                    sell_levels=self._ai_recommended_sell_levels,
                    buy_levels=self._ai_recommended_buy_levels,
                )

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

            # A persisted grid can predate wallet initialization and contain
            # zero sell inventory. Rebuild it once live token inventory is
            # available, otherwise the UI shows sell levels that can never fill.
            if (
                self._state.active
                and self._state.sell_levels
                and not any(level.amount_token > 0 for level in self._state.sell_levels)
            ):
                _, token_bal = self._get_balances()
                if token_bal is not None and float(token_bal) > 0:
                    self._maybe_build_grid(price_ton)
                    return

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
                            f"SELL L{level.id}: {level.amount_token:.0f} @ {price_ton:.6f} "
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
                                        level.profit_ton
                                        / max(
                                            level.entry_cost_ton or level.amount_ton,
                                            0.001,
                                        )
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
                        self._state.last_action = f"BUY L{level.id}: {level.amount_token:.0f} @ {price_ton:.6f}"
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
        if (
            not self._state.active
            and not self._state.sell_levels
            and not self._state.buy_levels
            and self._ai_enabled
            and self._ai
            and hasattr(self._ai, "kimi_required_for_auto_grid")
            and self._ai.kimi_required_for_auto_grid()
            and not self._ai.kimi_allows_initial_build()
        ):
            return
        ton_bal, token_bal = self._get_balances()
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
        step = self._ai_recommended_step or self._adaptive_step(atr_pct)
        # GRID_INVESTMENT is the working TON budget; build_grid adds the
        # configured gas reserve back when splitting buy levels.
        try:
            configured_investment = float(getattr(Config, "GRID_INVESTMENT", 0) or 0)
        except (TypeError, ValueError):
            configured_investment = 0.0
        gas_reserve = float(GridCfg.gas_reserve_ton or 0.0)
        ton_for_grid = float(ton_bal)
        if configured_investment > 0:
            ton_for_grid = min(ton_for_grid, configured_investment + gas_reserve)
        self.build_grid(
            center_price,
            step_pct=step,
            sell_levels=self._ai_recommended_sell_levels,
            buy_levels=self._ai_recommended_buy_levels,
            token_balance=token_bal,
            ton_balance=(
                min(ton_for_grid, self._ai_recommended_investment_ton)
                if self._ai_recommended_investment_ton is not None
                else ton_for_grid
            ),
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
    @staticmethod
    def _allow_unprofitable_orders():
        return os.getenv("GRID_ALLOW_UNPROFITABLE_ORDERS", "0").strip() == "1"

    @staticmethod
    def _gas_per_tx():
        try:
            return max(0.0, float(os.getenv("GRID_GAS_PER_TX", "0.004")))
        except (TypeError, ValueError):
            return 0.004

    @classmethod
    def _min_profitable_order_ton(cls, step_pct):
        try:
            configured_min = max(0.0, float(os.getenv("GRID_MIN_ORDER_TON", "0.05")))
        except (TypeError, ValueError):
            configured_min = 0.05
        # Explicit opt-in is required because small orders can lose more on
        # gas than they gain from a grid step.
        if cls._allow_unprofitable_orders():
            return configured_min
        fee = Config.FEES.pct / 100.0
        step = float(step_pct) if step_pct else GridCfg.step_pct
        step = max(step, 0.0)
        cycle_factor = (1.0 + step / 100.0) * (1.0 - fee) ** 2 - 1.0
        if cycle_factor <= 0:
            return float("inf")
        # Realistic gas per tx from on-chain data (~0.004 TON)
        gas_min = (cls._gas_per_tx() * 2.0) / cycle_factor
        return max(configured_min, gas_min)

    def build_grid(
        self,
        center_price,
        step_pct=None,
        sell_levels=None,
        buy_levels=None,
        token_balance=None,
        ton_balance=None,
        active=True,
        upper_price=None,
        lower_price=None,
    ):
        with self._lock:
            step = step_pct or GridCfg.step_pct
            step = max(
                GridCfg.min_step_pct or 3.0, min(GridCfg.max_step_pct or 8.0, step)
            )
            n_sell = (
                sell_levels if sell_levels is not None else (GridCfg.sell_levels or 20)
            )
            n_buy = buy_levels if buy_levels is not None else (GridCfg.buy_levels or 20)

            # Never allocate buy levels below the configured break-even size
            # unless the operator explicitly opts into unprofitable orders.
            gas_reserve = float(GridCfg.gas_reserve_ton or 0.0)
            avail_ton = max(0.0, float(ton_balance or 0.0) - gas_reserve)
            min_order = self._min_profitable_order_ton(step)
            if (
                not self._allow_unprofitable_orders()
                and math.isfinite(min_order)
                and min_order > 0
            ):
                affordable_buys = int((avail_ton + 1e-9) / min_order)
                if affordable_buys < n_buy:
                    log.warning(
                        "[Grid] Reducing buy levels from %d to %d: "
                        "%.4f TON per level is below break-even %.4f TON",
                        n_buy,
                        max(0, affordable_buys),
                        (avail_ton / n_buy) if n_buy else 0.0,
                        min_order,
                    )
                    n_buy = max(0, affordable_buys)

            s = GridState()
            s.active = bool(active)
            s.center_price = center_price
            s.last_rebuild = time.time()

            default_factor = 1 + step / 100
            sell_factor = default_factor
            buy_factor = default_factor
            if upper_price is not None and float(upper_price) > center_price:
                sell_factor = (float(upper_price) / center_price) ** (1 / n_sell)
            if lower_price is not None and 0 < float(lower_price) < center_price:
                buy_factor = (center_price / float(lower_price)) ** (1 / n_buy)

            s.upper_price = float(
                (
                    Decimal(str(center_price)) * Decimal(str(sell_factor)) ** n_sell
                ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            )
            s.lower_price = round(center_price / buy_factor**n_buy, 6)
            s.step_pct = max(
                (sell_factor - 1) * 100,
                (buy_factor - 1) * 100,
            )

            avail_token = max(0.0, float(token_balance or 0.0))
            grin_per_sell = avail_token / n_sell if n_sell > 0 else 0

            for i in range(1, n_sell + 1):
                price = center_price * sell_factor**i
                s.sell_levels.append(
                    GridLevel(
                        id=i,
                        side="sell",
                        price_ton=round(price, 6),
                        amount_token=round(grin_per_sell, 2),
                        amount_ton=0,
                    )
                )
            s.grid_reserved_token = avail_token

            ton_per_buy = avail_ton / n_buy if n_buy > 0 else 0

            for i in range(1, n_buy + 1):
                price = center_price / buy_factor**i
                amount_ton = ton_per_buy if ton_per_buy + 1e-9 >= min_order else 0
                s.buy_levels.append(
                    GridLevel(
                        id=-i,
                        side="buy",
                        price_ton=round(price, 6),
                        amount_token=0,
                        amount_ton=round(amount_ton, 2),
                    )
                )

            s.last_action = (
                f"GRID_BUILT: {n_sell + n_buy} levels; "
                f"buy {ton_per_buy:.2f} TON each; sell {grin_per_sell:.2f} token each"
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
                avail_token,
                avail_ton,
            )
            return s

    def ai_build_grid(
        self,
        center_price,
        sell_levels=None,
        buy_levels=None,
        investment_ton=None,
        upper_price=None,
        lower_price=None,
        step_pct=None,
    ):
        """Public API for AI-triggered grid build."""
        ton_bal, token_bal = self._get_balances()
        ton_budget = float(investment_ton) if investment_ton is not None else ton_bal
        if ton_bal is None:
            # Keep the dashboard useful when the wallet is not configured:
            # render a market-based preview, but do not mark it active and
            # never imply that live orders can be placed.
            step = (
                self._adaptive_step(self._calc_atr_pct())
                if step_pct is None
                else float(step_pct)
            )
            return self.build_grid(
                center_price,
                step_pct=step,
                sell_levels=sell_levels,
                buy_levels=buy_levels,
                token_balance=0,
                ton_balance=ton_budget or 0,
                active=False,
                upper_price=upper_price,
                lower_price=lower_price,
            )
        return self.build_grid(
            center_price,
            step_pct=(
                self._adaptive_step(self._calc_atr_pct())
                if step_pct is None
                else float(step_pct)
            ),
            sell_levels=sell_levels,
            buy_levels=buy_levels,
            token_balance=token_bal,
            ton_balance=ton_budget,
            active=True,
            upper_price=upper_price,
            lower_price=lower_price,
        )

    def _execute_sell(self, level, price_ton):
        try:
            if level.amount_token <= 0:
                return {"ok": False, "error": "zero_amount"}
            if self._dc and hasattr(self._dc, "sell"):
                # Keep the AMM-side profitability guard active for grid sells.
                # Without this argument the DEX client can execute a sell
                # below the level's entry cost.
                entry_cost = level.entry_cost_ton or level.amount_ton
                min_net_ton = entry_cost + self._gas_per_tx()
                result = self._dc.sell(
                    level.amount_token,
                    min_net_ton=min_net_ton,
                )
                if result.get("ok"):
                    # DeDust returns expected_ton; older clients used
                    # received_ton. Accept both so a successful sell is not
                    # recorded as a zero-value fill.
                    received_ton = float(
                        result.get("received_ton", result.get("expected_ton", 0)) or 0
                    )
                    if received_ton <= 0:
                        return {"ok": False, "error": "missing_received_ton"}
                    level.status = "filled"
                    level.filled_at = time.time()
                    level.fill_price_ton = price_ton
                    # Include the sell-side network estimate. A paired sell
                    # already carries the buy-side estimate in entry_cost_ton.
                    level.profit_ton = received_ton - entry_cost - self._gas_per_tx()
                    level.tx_hash = result.get("tx_hash", "")
                    self._state.total_profit_ton += level.profit_ton
                    self._state.total_sell_cycles += 1
                    return {
                        "ok": True,
                        "received": received_ton,
                        "profit_ton": level.profit_ton,
                    }
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
                    received_token = float(
                        result.get(
                            "received_usdt",
                            result.get(
                                "usdt_received",
                                result.get("received_grinch", 0),
                            ),
                        )
                        or 0
                    )
                    if received_token <= 0:
                        return {"ok": False, "error": "missing_received_token"}
                    level.status = "filled"
                    level.filled_at = time.time()
                    level.fill_price_ton = price_ton
                    level.amount_token = received_token
                    level.entry_cost_ton = level.amount_ton + self._gas_per_tx()
                    level.tx_hash = result.get("tx_hash", "")
                    return {"ok": True, "received": received_token}
            return {"ok": False, "error": "no_dedust_client"}
        except Exception as e:
            log.error("[Grid] buy error: %s", e)
            return {"ok": False, "error": str(e)}

    def _place_rebuy(self, level):
        """Recreate the buy one grid step below a filled sell."""
        step_factor = 1.0 + (self._state.step_pct or GridCfg.step_pct) / 100.0
        anchor = level.fill_price_ton or level.price_ton
        if anchor <= 0 or step_factor <= 1:
            return
        target_price = round(anchor / step_factor, 6)
        if any(
            item.status == "waiting"
            and item.side == "buy"
            and abs(item.price_ton - target_price) < 1e-9
            for item in self._state.buy_levels
        ):
            return
        amount_ton = level.amount_ton
        if amount_ton <= 0 and level.amount_token > 0:
            amount_ton = level.amount_token / target_price
        min_order = self._min_profitable_order_ton(self._state.step_pct)
        if not self._allow_unprofitable_orders() and (
            not math.isfinite(min_order) or amount_ton + 1e-9 < min_order
        ):
            log.info(
                "[Grid] Skip rebuy at %.6f: %.4f TON is below break-even %.4f TON",
                target_price,
                amount_ton,
                min_order,
            )
            return
        next_id = -(max([abs(item.id) for item in self._state.buy_levels] or [0]) + 1)
        self._state.buy_levels.append(
            GridLevel(
                id=next_id,
                side="buy",
                price_ton=target_price,
                amount_ton=round(amount_ton, 6),
                note=f"rebuy_after_sell:{level.id}",
            )
        )

    def _place_resell(self, level):
        """Create the sell one grid step above a filled buy."""
        step_factor = 1.0 + (self._state.step_pct or GridCfg.step_pct) / 100.0
        anchor = level.fill_price_ton or level.price_ton
        if anchor <= 0 or step_factor <= 1 or level.amount_token <= 0:
            return
        target_price = round(anchor * step_factor, 6)
        if any(
            item.status == "waiting"
            and item.side == "sell"
            and abs(item.price_ton - target_price) < 1e-9
            for item in self._state.sell_levels
        ):
            return
        next_id = max([item.id for item in self._state.sell_levels] or [0]) + 1
        self._state.sell_levels.append(
            GridLevel(
                id=next_id,
                side="sell",
                price_ton=target_price,
                amount_token=round(level.amount_token, 6),
                amount_ton=level.amount_ton,
                entry_cost_ton=level.entry_cost_ton,
                note=f"resell_after_buy:{level.id}",
            )
        )

    def _record_trade(self, side, level, price):
        trade = {
            "side": side,
            "level_id": level.id,
            "price": price,
            "amount_token": level.amount_token,
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
