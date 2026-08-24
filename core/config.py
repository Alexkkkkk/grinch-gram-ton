"""Unified configuration — single source of truth, no duplication."""

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _bool_env(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "")
    if not v:
        return default
    return v.strip().lower() not in ("false", "0", "no", "none", "")


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _str_env(key: str, default: str) -> str:
    return os.getenv(key, default) or default


@dataclass
class FeeConfig:
    pct: float = field(default_factory=lambda: _float_env("FEE_PCT", 1.0))
    slippage: float = field(default_factory=lambda: _float_env("SLIPPAGE_PCT", 5.0))
    gas_reserve_ton: float = field(default_factory=lambda: _float_env("GAS_RESERVE_TON", 0.45))
    sell_gas_ton: float = field(default_factory=lambda: _float_env("SELL_GAS_TON", 0.253))
    buy_gas_ton: float = field(default_factory=lambda: _float_env("BUY_GAS_TON", 0.103))

    @property
    def round_trip(self) -> float:
        return self.pct * 2


@dataclass
class GridConfig:
    enabled: bool = field(default_factory=lambda: _bool_env("GRID_MODE", True))
    symbol: str = field(default_factory=lambda: _str_env("GRID_SYMBOL", "GRINCH/TON"))
    count: int = field(default_factory=lambda: _int_env("GRID_COUNT", 40))
    step_pct: float = field(default_factory=lambda: _float_env("GRID_STEP_PCT", 3.5))
    min_step_pct: float = field(default_factory=lambda: _float_env("GRID_MIN_STEP_PCT", 3.0))
    max_step_pct: float = field(default_factory=lambda: _float_env("GRID_MAX_STEP_PCT", 8.0))
    sell_levels: int = field(default_factory=lambda: _int_env("GRID_SELL_LEVELS", 20))
    buy_levels: int = field(default_factory=lambda: _int_env("GRID_BUY_LEVELS", 20))
    adaptive_step: bool = field(default_factory=lambda: _bool_env("GRID_ADAPTIVE_STEP", True))
    tick_sec: int = field(default_factory=lambda: _int_env("GRID_TICK_SEC", 15))
    tick_interval: int = field(default_factory=lambda: _int_env("GRID_TICK_INTERVAL", 15))
    recenter_threshold: float = field(
        default_factory=lambda: _float_env("GRID_RECENTER_THRESHOLD", 1.8)
    )
    recenter_cooldown: int = field(
        default_factory=lambda: _int_env("GRID_RECENTER_COOLDOWN", 1800)
    )
    min_order_ton: float = 15.0
    gas_reserve_ton: float = 5.0
    db_path: str = field(
        default_factory=lambda: _str_env("GRID_DB_PATH", "/app/data/grid_grinch_gram.db")
    )


@dataclass
class TrailConfig:
    breakeven_at: float = field(default_factory=lambda: _float_env("TRAIL_BREAKEVEN_AT", 6.0))
    stage2_at: float = field(default_factory=lambda: _float_env("TRAIL_STAGE2_AT", 12.0))
    stage2_pct: float = field(default_factory=lambda: _float_env("TRAIL_STAGE2_PCT", 17.0))
    stage3_at: float = field(default_factory=lambda: _float_env("TRAIL_STAGE3_AT", 18.0))
    stage3_pct: float = field(default_factory=lambda: _float_env("TRAIL_STAGE3_PCT", 12.0))
    stage4_at: float = field(default_factory=lambda: _float_env("TRAIL_STAGE4_AT", 26.0))
    stage4_pct: float = field(default_factory=lambda: _float_env("TRAIL_STAGE4_PCT", 6.0))
    base_pct: float = field(default_factory=lambda: _float_env("TRAILING_STOP_PCT", 13.0))
    trend_widen: float = field(default_factory=lambda: _float_env("TRAIL_TREND_WIDEN", 1.5))
    chop_tighten: float = field(default_factory=lambda: _float_env("TRAIL_CHOP_TIGHTEN", 0.8))
    trend_adx: float = field(default_factory=lambda: _float_env("TRAIL_TREND_ADX", 28.0))


@dataclass
class DcaConfig:
    enabled: bool = False
    stake_ton: float = field(default_factory=lambda: _float_env("DCA_STAKE_TON", 100))
    target_profit_pct: float = field(
        default_factory=lambda: _float_env("DCA_TARGET_PROFIT_PCT", 22)
    )
    drop_trigger_pct: float = field(
        default_factory=lambda: _float_env("DCA_DROP_TRIGGER_PCT", 10)
    )
    pullback_wait_pct: float = field(
        default_factory=lambda: _float_env("DCA_PULLBACK_WAIT_PCT", 13)
    )
    max_entries: int = field(default_factory=lambda: _int_env("DCA_MAX_ENTRIES", 10))
    cascade_enabled: bool = field(default_factory=lambda: _bool_env("DCA_CASCADE_ENABLED", True))
    cascade_l1_pct: float = field(
        default_factory=lambda: _float_env("DCA_CASCADE_LEVEL1_PCT", 28)
    )
    cascade_l2_pct: float = field(
        default_factory=lambda: _float_env("DCA_CASCADE_LEVEL2_PCT", 52)
    )
    smart_reentry: bool = field(
        default_factory=lambda: _bool_env("DCA_SMART_REENTRY_ENABLED", True)
    )
    smart_reentry_pullback: float = field(
        default_factory=lambda: _float_env("DCA_SMART_REENTRY_PULLBACK_PCT", 7)
    )
    smart_reentry_min_conf: float = field(
        default_factory=lambda: _float_env("DCA_SMART_REENTRY_MIN_AI_CONF", 50)
    )
    reentry_cooldown_sec: int = field(
        default_factory=lambda: _int_env("DCA_REENTRY_COOLDOWN_SEC", 30)
    )
    compound_enabled: bool = field(
        default_factory=lambda: _bool_env("DCA_COMPOUND_ENABLED", True)
    )
    compound_ratio: float = field(
        default_factory=lambda: _float_env("DCA_COMPOUND_RATIO", 0.45)
    )
    compound_max_ton: float = field(
        default_factory=lambda: _float_env("DCA_COMPOUND_MAX_TON", 500)
    )
    adaptive_trigger: bool = field(
        default_factory=lambda: _bool_env("DCA_ADAPTIVE_TRIGGER_ENABLED", True)
    )
    adaptive_fast_move: float = field(
        default_factory=lambda: _float_env("DCA_ADAPTIVE_FAST_MOVE_PCT", 6)
    )
    adaptive_fast_drop: float = field(
        default_factory=lambda: _float_env("DCA_ADAPTIVE_FAST_DROP_PCT", 4)
    )
    ai_adapt_min_cycles: int = field(
        default_factory=lambda: _int_env("DCA_AI_ADAPT_MIN_CYCLES", 3)
    )
    ai_target_cap: float = field(default_factory=lambda: _float_env("DCA_AI_TARGET_CAP", 60))
    ai_drop_cap: float = field(default_factory=lambda: _float_env("DCA_AI_DROP_CAP", 50))
    ai_pullback_cap: float = field(
        default_factory=lambda: _float_env("DCA_AI_PULLBACK_CAP", 50)
    )
    ai_sell_block_conf: float = field(
        default_factory=lambda: _float_env("DCA_AI_SELL_BLOCK_CONF", 85)
    )


@dataclass
class AiConfig:
    autonomous_mode: bool = True
    full_rights: bool = field(default_factory=lambda: _bool_env("AI_FULL_RIGHTS", False))
    full_rights_min_conf: float = field(
        default_factory=lambda: _float_env("AI_FULL_RIGHTS_MIN_CONF", 52)
    )
    autonomous_min_conf: float = field(
        default_factory=lambda: _float_env("AI_AUTONOMOUS_MIN_CONF", 50)
    )
    min_confidence: float = field(
        default_factory=lambda: _float_env("MIN_AI_CONFIDENCE", 50)
    )
    override_confidence: float = field(
        default_factory=lambda: _float_env("AI_OVERRIDE_CONFIDENCE", 78)
    )
    hard_override_confidence: float = field(
        default_factory=lambda: _float_env("AI_HARD_OVERRIDE_CONFIDENCE", 93)
    )
    atr_feasibility_mult: float = field(
        default_factory=lambda: _float_env("AI_ATR_FEASIBILITY_MULT", 1.2)
    )
    size_mult: float = field(default_factory=lambda: _float_env("AI_SIZE_MULT", 1.5))


@dataclass
class SmartConfig:
    buy_enabled: bool = field(default_factory=lambda: _bool_env("SMART_BUY_ENABLED", True))
    buy_pullback_pct: float = field(
        default_factory=lambda: _float_env("SMART_BUY_PULLBACK_PCT", 0.2)
    )
    buy_max_wait_ticks: int = field(
        default_factory=lambda: _int_env("SMART_BUY_MAX_WAIT_TICKS", 2)
    )
    buy_skip_conf: float = field(
        default_factory=lambda: _float_env("SMART_BUY_SKIP_CONF", 88.0)
    )
    tp_enabled: bool = field(default_factory=lambda: _bool_env("SMART_TP_ENABLED", True))
    tp_min_conf: float = field(default_factory=lambda: _float_env("SMART_TP_MIN_CONF", 70.0))
    tp_tight_trail_pct: float = field(
        default_factory=lambda: _float_env("SMART_TP_TIGHT_TRAIL_PCT", 10.0)
    )


@dataclass
class ProtectionConfig:
    profit_protect_enabled: bool = field(
        default_factory=lambda: _bool_env("PROFIT_PROTECT_ENABLED", True)
    )
    profit_protect_ton: float = field(
        default_factory=lambda: _float_env("PROFIT_PROTECT_TON", 3.0)
    )
    profit_protect_drop_pct: float = field(
        default_factory=lambda: _float_env("PROFIT_PROTECT_DROP_PCT", 9.0)
    )
    profit_protect_ai_sell: bool = field(
        default_factory=lambda: _bool_env("PROFIT_PROTECT_AI_SELL", True)
    )
    circuit_breaker_enabled: bool = field(
        default_factory=lambda: _bool_env("CIRCUIT_BREAKER_ENABLED", True)
    )
    circuit_breaker_daily_loss_pct: float = field(
        default_factory=lambda: _float_env("CIRCUIT_BREAKER_DAILY_LOSS_PCT", 15.0)
    )
    stale_position_enabled: bool = field(
        default_factory=lambda: _bool_env("STALE_POSITION_ENABLED", False)
    )
    stale_position_max_hours: float = field(
        default_factory=lambda: _float_env("STALE_POSITION_MAX_HOURS", 72.0)
    )
    stale_position_min_profit_pct: float = field(
        default_factory=lambda: _float_env("STALE_POSITION_MIN_PROFIT_PCT", 1.0)
    )
    loss_cooldown_sec: int = field(
        default_factory=lambda: _int_env("LOSS_COOLDOWN_SEC", 120)
    )


@dataclass
class ShortConfig:
    enabled: bool = field(default_factory=lambda: _bool_env("SHORT_TRADING_ENABLED", True))
    trail_pct: float = field(default_factory=lambda: _float_env("SHORT_TRAIL_PCT", 10.0))
    reserve: float = field(default_factory=lambda: _float_env("GRINCH_RESERVE", 500))
    min_ai_conf: float = field(default_factory=lambda: _float_env("SHORT_MIN_AI_CONF", 58.0))


@dataclass
class ScalpConfig:
    enabled: bool = field(default_factory=lambda: _bool_env("SCALPING_ENABLED", True))
    target_net_pct: float = field(
        default_factory=lambda: _float_env("SCALP_TARGET_NET_PCT", 3.0)
    )
    tp_pct: float = field(default_factory=lambda: _float_env("SCALP_TP_PCT", 5.0))
    trail_pct: float = field(default_factory=lambda: _float_env("SCALP_TRAIL_PCT", 7.0))
    min_ai_conf: float = field(default_factory=lambda: _float_env("SCALP_MIN_AI_CONF", 52.0))
    max_atr_pct: float = field(default_factory=lambda: _float_env("SCALP_MAX_ATR_PCT", 8.0))


@dataclass
class FusionConfig:
    enabled: bool = field(default_factory=lambda: _bool_env("FUSION_ENABLED", True))
    skip_confirm_conf: float = field(
        default_factory=lambda: _float_env("FUSION_SKIP_CONFIRM_CONF", 68.0)
    )
    pump_boost_max: float = field(
        default_factory=lambda: _float_env("FUSION_PUMP_BOOST_MAX", 1.8)
    )


class _SingletonMeta(type):
    """Metaclass allowing class-style attribute access on singleton instance."""

    def __call__(cls, *args, **kwargs):
        if cls.__dict__.get("_instance") is None:
            cls._instance = super().__call__(*args, **kwargs)
        return cls._instance

    def __getattr__(cls, name):
        inst = cls.__dict__.get("_instance")
        if inst is None:
            inst = cls()
        return getattr(inst, name)

    def __setattr__(cls, name, value):
        if name == "_instance":
            type.__setattr__(cls, name, value)
            return
        inst = cls.__dict__.get("_instance")
        if inst is None:
            inst = cls()
        setattr(inst, name, value)


class Config(metaclass=_SingletonMeta):
    """Unified config namespace — replaces monolithic config.py."""

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # Core
        self.EXCHANGE: str = _str_env("EXCHANGE", "binance")
        self.SYMBOL: str = _str_env("SYMBOL", "GRINCH/TON")
        self.TIMEFRAME: str = _str_env("TIMEFRAME", "15m")
        self.TRADE_MODE: str = _str_env("TRADE_MODE", "dedust")
        self.DEMO_MODE: bool = _bool_env("DEMO_MODE", False)

        # Money management
        self.TRADE_AMOUNT: float = _float_env("TRADE_AMOUNT", 100)
        self.MAX_OPEN_TRADES: int = _int_env("MAX_OPEN_TRADES", 1)
        self.MIN_STAKE_TON: float = _float_env("MIN_STAKE_TON", 5.0)
        self.MIN_PROFIT_TON: float = _float_env("MIN_PROFIT_TON", 5.0)
        self.MIN_PROFIT_TON_ABS: float = _float_env("MIN_PROFIT_TON_ABS", 2.0)

        # Targets
        self.TARGET_NET_PCT: float = _float_env("TARGET_NET_PCT", 13.0)
        self.TAKE_PROFIT_PCT: float = _float_env("TAKE_PROFIT_PCT", 22.0)
        self.STOP_LOSS_PCT: float = _float_env("STOP_LOSS_PCT", 5.0)
        self.USE_DYNAMIC_TARGETS: bool = _bool_env("USE_DYNAMIC_TARGETS", True)
        self.ATR_SL_MULT: float = _float_env("ATR_SL_MULT", 2.5)
        self.ATR_TP_MULT: float = _float_env("ATR_TP_MULT", 3.0)

        # Filters
        self.TREND_FILTER: bool = _bool_env("TREND_FILTER", True)
        self.RSI_OVERBOUGHT: float = _float_env("RSI_OVERBOUGHT", 78)
        self.RSI_OVERSOLD_REVERSAL: float = _float_env("RSI_OVERSOLD_REVERSAL", 25)
        self.REVERSAL_AI_MIN: float = _float_env("REVERSAL_AI_MIN", 70)
        self.CONFLUENCE_ENABLED: bool = _bool_env("CONFLUENCE_ENABLED", True)
        self.CONFLUENCE_RSI_MAX: float = _float_env("CONFLUENCE_RSI_MAX", 78)
        self.CONFLUENCE_VOL_MIN_RATIO: float = _float_env("CONFLUENCE_VOL_MIN_RATIO", 0.6)
        self.EV_THRESHOLD: float = _float_env("EV_THRESHOLD", -1.0)

        # Dead hours
        self.DEAD_HOURS_UTC: List[int] = [
            int(h)
            for h in _str_env("DEAD_HOURS_UTC", "0,3,8,12,14").split(",")
            if h.strip().lstrip("-").isdigit()
        ]
        self.DEAD_HOURS_DROP_MULT: float = _float_env("DEAD_HOURS_DROP_MULT", 1.5)

        # All-in bottom
        self.ALLIN_ON_BOTTOM: bool = _bool_env("ALLIN_ON_BOTTOM", False)
        self.ALLIN_BOTTOM_CONF: float = _float_env("ALLIN_BOTTOM_CONF", 65)
        self.ALLIN_RSI_MAX: float = _float_env("ALLIN_RSI_MAX", 32)
        self.ALLIN_MIN_FREE_TON: float = _float_env("ALLIN_MIN_FREE_TON", 50)

        # Large sell detector
        self.LARGE_SELL_DCA_ENABLED: bool = _bool_env("LARGE_SELL_DCA_ENABLED", True)
        self.LARGE_SELL_DCA_TON: float = _float_env("LARGE_SELL_DCA_TON", 60)
        self.LARGE_SELL_MIN_TON: float = _float_env("LARGE_SELL_MIN_TON", 150)
        self.LARGE_SELL_COOLDOWN_SEC: int = _int_env("LARGE_SELL_COOLDOWN_SEC", 300)

        # Smart money
        self.SMART_MONEY_BLOCK: float = _float_env("SMART_MONEY_BLOCK", -0.6)
        self.SMART_MONEY_BOOST_AT: float = _float_env("SMART_MONEY_BOOST_AT", 0.5)
        self.SMART_MONEY_CONF_BONUS: float = _float_env("SMART_MONEY_CONF_BONUS", 5)
        self.SMART_MONEY_MIN_FLOOR: float = _float_env("SMART_MONEY_MIN_FLOOR", 45)
        self.SMART_EARLY_WINDOW_SEC: int = _int_env("SMART_EARLY_WINDOW_SEC", 600)
        self.SMART_EARLY_MIN_TON: float = _float_env("SMART_EARLY_MIN_TON", 10)

        # Whale analysis
        self.WHALE_BALANCE_POLL_SEC: int = _int_env("WHALE_BALANCE_POLL_SEC", 300)
        self.WHALE_TOP_N: int = _int_env("WHALE_TOP_N", 25)
        self.WHALE_MIN_GRINCH: float = _float_env("WHALE_MIN_GRINCH", 100000)

        # Order flow
        self.ORDER_FLOW_INJECT_ENABLED: bool = _bool_env("ORDER_FLOW_INJECT_ENABLED", True)

        # Fast reentry
        self.FAST_REENTRY_ENABLED: bool = _bool_env("FAST_REENTRY_ENABLED", True)
        self.FAST_REENTRY_PULLBACK_PCT: float = _float_env("FAST_REENTRY_PULLBACK_PCT", 7.0)
        self.FAST_REENTRY_MIN_CONF: float = _float_env("FAST_REENTRY_MIN_CONF", 55.0)

        # Security
        self.SECRET_KEY: str = _str_env("SECRET_KEY", "")
        self.REPORT_ERRORS: bool = _bool_env("REPORT_ERRORS", True)

        # TON / Token addresses
        self.TON_WALLET: str = _str_env(
            "TON_WALLET", "EQDDgb2BTM-KCjntOoUg6uHllvnu3KGqEquKw6IySVP3hGXJ"
        )
        self.TOKEN_ADDRESS: str = _str_env(
            "TOKEN_ADDRESS", "EQA6G0uVERDZTkLNa0drWBna1F5TSbogy7UXEWU5ERHz4uJL"
        )
        self.POOL_ADDRESS: str = _str_env(
            "POOL_ADDRESS", "EQDpVwTQr53cwgaT_VCFsmrleg5fBvStTjMrvyvprF_ROC9Z"
        )
        self.GRINCH_TOKEN_ADDRESS: str = self.TOKEN_ADDRESS
        self.GRINCH_POOL_ADDRESS: str = self.POOL_ADDRESS

        # Binance grid overrides
        self.BINANCE_API_KEY: str = _str_env("BINANCE_API_KEY", "")
        self.BINANCE_API_SECRET: str = _str_env("BINANCE_API_SECRET", "")
        self.USE_BINANCE_TESTNET: bool = _bool_env("USE_BINANCE_TESTNET", True)
        self.GRID_SYMBOL_BINANCE: str = _str_env("GRID_SYMBOL", "AUDIOUSDT")
        self.GRID_INVESTMENT: float = _float_env("GRID_INVESTMENT", 1000)
        self.GRID_UPPER_PRICE: float = _float_env("GRID_UPPER_PRICE", 0)
        self.GRID_LOWER_PRICE: float = _float_env("GRID_LOWER_PRICE", 0)
        self.GRID_FEE_PCT: float = 0.1
        self.GRID_MIN_ORDER_USDT: float = 10.0

        # Safety hardcodes
        self.ONLY_PROFIT_EXIT: bool = True
        self.AI_AUTONOMOUS_MODE: bool = True

        # Sub-configs
        self.FEES: FeeConfig = FeeConfig()
        self.GRID: GridConfig = GridConfig()
        self.TRAIL: TrailConfig = TrailConfig()
        self.DCA: DcaConfig = DcaConfig()
        self.AI: AiConfig = AiConfig()
        self.SMART: SmartConfig = SmartConfig()
        self.PROTECTION: ProtectionConfig = ProtectionConfig()
        self.SHORT: ShortConfig = ShortConfig()
        self.SCALP: ScalpConfig = ScalpConfig()
        self.FUSION: FusionConfig = FusionConfig()

    @classmethod
    def required_gross_pct(cls, stake_ton: float = 0) -> float:
        """Minimum gross % move for net profit after DEX fees + gas."""
        inst = cls()
        fee = inst.FEES.pct / 100.0
        denom = 1.0 - fee
        if denom <= 0:
            return inst.TARGET_NET_PCT + inst.FEES.round_trip
        base = (inst.TARGET_NET_PCT + 2.0 * inst.FEES.pct) / denom
        if stake_ton <= 0:
            return base
        buy_gas = inst.FEES.buy_gas_ton
        sell_gas = inst.FEES.sell_gas_ton
        target = inst.TARGET_NET_PCT / 100.0
        total_cost = stake_ton + buy_gas
        numerator = total_cost * (1.0 + target) + sell_gas
        denominator = stake_ton * (1.0 - fee) ** 2
        if denominator <= 0:
            return base
        gross = (numerator / denominator - 1.0) * 100.0
        return max(gross, base)

    @classmethod
    def required_drop_pct_for_short(cls, grinch_value_ton: float = 0) -> float:
        return cls.required_gross_pct(grinch_value_ton)


# Initialize singleton on import
Config()
