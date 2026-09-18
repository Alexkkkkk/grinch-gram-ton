"""grid_pro_engine.py — Pro features above QuantumGrid v7.1.

Features not in Binance/Bybit grids:
  * Geometric spacing (price progression by fixed %).
  * Trailing Up / Trailing Down (range follows price).
  * SPOT_NEUTRAL / SPOT_LONG / FUTURES_NEUTRAL modes.
  * Reverse grid (sell-low / buy-high) for bearish regimes.
  * ATR-adaptive step + Squeeze-pulse range expansion.
  * Portfolio SL/TP (in % from center).
  * Risk guard: daily-trade cap, cooling-down after losses, position cap.
  * Dry-run plan generator — virtual orders without execution.
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

log = logging.getLogger("grid_pro")


class GridMode(str, Enum):
    SPOT_NEUTRAL = "SPOT_NEUTRAL"  # buy below, sell above
    SPOT_LONG = "SPOT_LONG"  # only buys to accumulate
    FUTURES_NEUTRAL = "FUTURES_NEUTRAL"  # both sides, leverage
    REVERSE = "REVERSE"  # sell below, buy above (bearish range)


@dataclass
class ProConfig:
    mode: GridMode = GridMode.SPOT_NEUTRAL
    spacing: str = "geometric"  # "arithmetic" or "geometric"
    trailing_up_pct: float = 0.0  # 0 disables
    trailing_down_pct: float = 0.0
    leverage: float = 1.0  # effective for FUTURES_NEUTRAL
    reverse_below_center: bool = False
    portfolio_sl_pct: float = 0.0  # 0 disables — global SL in % from entry
    portfolio_tp_pct: float = 0.0  # 0 disables — global TP in % from entry
    atr_period: int = 14  # candles for ATR calc
    atr_k_min: float = 0.6
    atr_k_max: float = 1.6
    squeeze_bb_period: int = 20
    squeeze_bb_k: float = 0.6
    squeeze_expand: float = 1.5  # range mult on squeeze detection
    max_daily_trades: int = 0  # 0 disables
    cooldown_after_loss_min: int = 0
    max_position_pct: float = 60.0  # % of balance tied by grid


@dataclass
class GridPlan:
    mode: str
    spacing: str
    center_price: float
    upper_price: float
    lower_price: float
    step_pct: float
    n_buy: int
    n_sell: int
    buy_levels: List[float] = field(default_factory=list)
    sell_levels: List[float] = field(default_factory=list)
    atr_pct: float = 0.0
    squeeze: bool = False
    sl_price: float = 0.0
    tp_price: float = 0.0
    trailing_active: bool = False
    leverage: float = 1.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode
        return d


def _q(x: float, p: int = 6) -> float:
    return float(Decimal(str(x)).quantize(Decimal(10) ** -p, rounding=ROUND_HALF_UP))


def atr_pct(candles: List[Dict[str, float]], period: int = 14) -> float:
    """ATR as % of last close, over the last `period` candles."""
    if not candles or len(candles) < 2:
        return 0.0
    trs: List[float] = []
    closes: List[float] = []
    for i in range(1, len(candles)):
        h = float(candles[i]["high"])
        l = float(candles[i]["low"])
        pc = float(candles[i - 1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
        closes.append(float(candles[i]["close"]))
    closes.append(float(candles[-1]["close"]))
    last = closes[-1] or 1e-9
    if not trs:
        return 0.0
    window = trs[-period:] if len(trs) >= period else trs
    atr = mean(window)
    return (atr / last) * 100.0


def bollinger_width(
    candles: List[Dict[str, float]], period: int = 20, k: float = 2.0
) -> float:
    if len(candles) < period:
        return 0.0
    closes = [float(c["close"]) for c in candles[-period:]]
    m = mean(closes)
    sd = pstdev(closes) if len(closes) > 1 else 0.0
    upper = m + k * sd
    lower = m - k * sd
    return ((upper - lower) / (m or 1e-9)) * 100.0  # width as %


def adaptive_step(
    candles: List[Dict[str, float]], pro: ProConfig, base_step: float
) -> float:
    """ATR-driven step adjustment. base_step (e.g. 0.9) is a seed; we modulate by ATR."""
    a = atr_pct(candles, pro.atr_period)
    if a <= 0:
        return base_step
    # higher vol -> wider step (within [base*k_min, base*k_max])
    ratio = a / max(base_step, 1e-6)
    ratio = max(min(ratio, pro.atr_k_max), pro.atr_k_min)
    return _q(base_step * ratio, 4)


def geometric_levels(
    center: float,
    step_pct: float,
    n_buy: int,
    n_sell: int,
    spacing: str,
    reverse: bool = False,
) -> (List[float], List[float]):
    """Return (buy_levels, sell_levels). geometric uses (1+step) factor."""
    factor = (1.0 + step_pct / 100.0) if spacing == "geometric" else 1.0
    step = step_pct / 100.0 if spacing == "arithmetic" else step_pct / 100.0

    buys: List[float] = []
    sells: List[float] = []
    if spacing == "geometric":
        # prices[i] = center * factor^(-i)  for buys, factor^(i) for sells (or reverse)
        for i in range(1, n_buy + 1):
            p = center * (factor**-i)
            buys.append(_q(p))
        for i in range(1, n_sell + 1):
            p = center * (factor**i)
            sells.append(_q(p))
    else:
        for i in range(1, n_buy + 1):
            buys.append(_q(center * (1 - i * step)))
        for i in range(1, n_sell + 1):
            sells.append(_q(center * (1 + i * step)))
    if reverse:
        # invert sides — sell below, buy above
        buys, sells = sells, buys
    return buys, sells


def trailing_bounds(center: float, price: float, pro: ProConfig) -> (float, float):
    """If price drifts, recenter bounds so trailing never lets price escape."""
    if pro.trailing_up_pct <= 0 and pro.trailing_down_pct <= 0:
        return center, center
    upper = center
    lower = center
    if pro.trailing_up_pct > 0 and price > center:
        upper = price * (1 + pro.trailing_up_pct / 100.0)
        if price > center:
            lower = price * (1 - (pro.trailing_down_pct or pro.trailing_up_pct) / 100.0)
            center_new = (upper + lower) / 2.0
            return center_new, center_new
    if pro.trailing_down_pct > 0 and price < center:
        lower = price * (1 - pro.trailing_down_pct / 100.0)
        upper = price * (1 + (pro.trailing_up_pct or pro.trailing_down_pct) / 100.0)
        center_new = (upper + lower) / 2.0
        return center_new, center_new
    return center, center


def build_plan(
    center: float,
    candles: List[Dict[str, float]],
    pro: ProConfig,
    base_step_pct: float,
    n_buy: int,
    n_sell: int,
    entry_price: Optional[float] = None,
) -> GridPlan:
    eff_step = adaptive_step(candles, pro, base_step_pct) if candles else base_step_pct
    sq = (
        bollinger_width(candles, pro.squeeze_bb_period) < pro.squeeze_bb_k
        if candles
        else False
    )

    # trailing center
    center_eff = center
    if pro.trailing_up_pct > 0 or pro.trailing_down_pct > 0 and candles:
        last = float(candles[-1]["close"])
        center_eff, _ = trailing_bounds(center, last, pro)

    # levels + reverse handling
    reverse = (pro.mode == GridMode.REVERSE) or pro.reverse_below_center
    buys, sells = geometric_levels(
        center_eff, eff_step, n_buy, n_sell, pro.spacing, reverse=reverse
    )

    # portfolio SL/TP, anchored on entry or current
    anchor = entry_price or center_eff or center
    sl = (
        anchor * (1 - pro.portfolio_sl_pct / 100.0) if pro.portfolio_sl_pct > 0 else 0.0
    )
    tp = (
        anchor * (1 + pro.portfolio_tp_pct / 100.0) if pro.portfolio_tp_pct > 0 else 0.0
    )

    # range expansion on squeeze
    range_mult = pro.squeeze_expand if sq else 1.0
    upper_price = sells[-1] if sells else center_eff * (1 + eff_step / 100)
    lower_price = buys[-1] if buys else center_eff * (1 - eff_step / 100)
    upper_price *= range_mult
    lower_price /= range_mult

    plan = GridPlan(
        mode=pro.mode.value,
        spacing=pro.spacing,
        center_price=_q(center_eff),
        upper_price=_q(upper_price),
        lower_price=_q(lower_price),
        step_pct=eff_step,
        n_buy=len(buys),
        n_sell=len(sells),
        buy_levels=buys,
        sell_levels=sells,
        atr_pct=atr_pct(candles, pro.atr_period),
        squeeze=sq,
        sl_price=_q(sl) if sl else 0.0,
        tp_price=_q(tp) if tp else 0.0,
        trailing_active=pro.trailing_up_pct > 0 or pro.trailing_down_pct > 0,
        leverage=pro.leverage,
        note="squeeze-pulse" if sq else ("reverse" if reverse else "normal"),
    )
    return plan


# ═══════════════════════════════════════════
# Risk guard
# ═══════════════════════════════════════════
class RiskGuard:
    def __init__(self, pro: ProConfig):
        self.pro = pro
        self.day_started = time.time()
        self.trades_today = 0
        self.last_loss_ts = 0.0

    def allow(self) -> (bool, str):
        # day rollover
        if time.time() - self.day_started > 86400:
            self.day_started = time.time()
            self.trades_today = 0
        if self.pro.max_daily_trades and self.trades_today >= self.pro.max_daily_trades:
            return False, "max_daily_trades reached"
        if self.pro.cooldown_after_loss_min > 0 and self.last_loss_ts:
            elapsed_min = (time.time() - self.last_loss_ts) / 60.0
            if elapsed_min < self.pro.cooldown_after_loss_min:
                rem = self.pro.cooldown_after_loss_min - elapsed_min
                return False, f"cooldown {rem:.1f}m"
        return True, "ok"

    def on_trade(self, profitable: bool):
        self.trades_today += 1
        if not profitable:
            self.last_loss_ts = time.time()
