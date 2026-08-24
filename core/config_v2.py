"""Pydantic-based configuration — type-safe, validated, secure."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class FeeConfig(BaseSettings):
    pct: float = Field(default=0.25, ge=0, le=10)
    slippage: float = Field(default=5.0, ge=0, le=50)
    gas_reserve_ton: float = Field(default=0.45, ge=0)
    sell_gas_ton: float = Field(default=0.253, ge=0)
    buy_gas_ton: float = Field(default=0.103, ge=0)

    @property
    def round_trip(self) -> float:
        return self.pct * 2


class GridConfig(BaseSettings):
    enabled: bool = True
    symbol: str = "GRINCH/TON"
    count: int = Field(default=40, ge=2, le=200)
    step_pct: float = Field(default=3.5, ge=0.1, le=50)
    min_step_pct: float = Field(default=3.0, ge=0.1, le=50)
    max_step_pct: float = Field(default=8.0, ge=0.1, le=50)
    sell_levels: int = Field(default=20, ge=1, le=100)
    buy_levels: int = Field(default=20, ge=1, le=100)
    adaptive_step: bool = True
    tick_sec: int = Field(default=15, ge=1, le=3600)
    tick_interval: int = Field(default=15, ge=1, le=3600)
    recenter_threshold: float = Field(default=1.8, ge=0.1, le=10)
    recenter_cooldown: int = Field(default=1800, ge=0)
    min_order_ton: float = Field(default=15.0, ge=0)
    gas_reserve_ton: float = Field(default=5.0, ge=0)
    db_path: str = "/app/data/grid_grinch_gram.db"


class TrailConfig(BaseSettings):
    breakeven_at: float = Field(default=6.0, ge=0)
    stage2_at: float = Field(default=12.0, ge=0)
    stage2_pct: float = Field(default=17.0, ge=0)
    stage3_at: float = Field(default=18.0, ge=0)
    stage3_pct: float = Field(default=12.0, ge=0)
    stage4_at: float = Field(default=26.0, ge=0)
    stage4_pct: float = Field(default=6.0, ge=0)
    base_pct: float = Field(default=13.0, ge=0)
    trend_widen: float = Field(default=1.5, ge=0)
    chop_tighten: float = Field(default=0.8, ge=0)
    trend_adx: float = Field(default=28.0, ge=0)


class DcaConfig(BaseSettings):
    enabled: bool = False
    stake_ton: float = Field(default=100.0, ge=0)
    target_profit_pct: float = Field(default=22.0, ge=0)
    drop_trigger_pct: float = Field(default=10.0, ge=0)
    pullback_wait_pct: float = Field(default=13.0, ge=0)
    max_entries: int = Field(default=10, ge=1, le=100)
    cascade_enabled: bool = True
    cascade_l1_pct: float = Field(default=28.0, ge=0)
    cascade_l2_pct: float = Field(default=52.0, ge=0)
    smart_reentry: bool = True
    smart_reentry_pullback: float = Field(default=7.0, ge=0)
    smart_reentry_min_conf: float = Field(default=50.0, ge=0, le=100)
    reentry_cooldown_sec: int = Field(default=30, ge=0)
    compound_enabled: bool = True
    compound_ratio: float = Field(default=0.45, ge=0, le=1)
    compound_max_ton: float = Field(default=500.0, ge=0)
    adaptive_trigger: bool = True
    adaptive_fast_move: float = Field(default=6.0, ge=0)
    adaptive_fast_drop: float = Field(default=4.0, ge=0)
    ai_adapt_min_cycles: int = Field(default=3, ge=1)
    ai_target_cap: float = Field(default=60.0, ge=0)
    ai_drop_cap: float = Field(default=50.0, ge=0)
    ai_pullback_cap: float = Field(default=50.0, ge=0)
    ai_sell_block_conf: float = Field(default=85.0, ge=0, le=100)


class AiConfig(BaseSettings):
    autonomous_mode: bool = True
    full_rights: bool = False
    full_rights_min_conf: float = Field(default=52.0, ge=0, le=100)
    autonomous_min_conf: float = Field(default=50.0, ge=0, le=100)
    min_confidence: float = Field(default=50.0, ge=0, le=100)
    override_confidence: float = Field(default=78.0, ge=0, le=100)
    hard_override_confidence: float = Field(default=93.0, ge=0, le=100)
    atr_feasibility_mult: float = Field(default=1.2, ge=0)
    size_mult: float = Field(default=1.5, ge=0)


class ProtectionConfig(BaseSettings):
    profit_protect_enabled: bool = True
    profit_protect_ton: float = Field(default=3.0, ge=0)
    profit_protect_drop_pct: float = Field(default=9.0, ge=0)
    profit_protect_ai_sell: bool = True
    circuit_breaker_enabled: bool = True
    circuit_breaker_daily_loss_pct: float = Field(default=15.0, ge=0)
    stale_position_enabled: bool = False
    stale_position_max_hours: float = Field(default=72.0, ge=0)
    stale_position_min_profit_pct: float = Field(default=1.0, ge=0)
    loss_cooldown_sec: int = Field(default=120, ge=0)


class AppConfig(BaseSettings):
    """Main application configuration — all env vars validated."""

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}

    # Exchange
    exchange: str = Field(default="binance", alias="EXCHANGE")
    symbol: str = Field(default="GRINCH/TON", alias="SYMBOL")
    timeframe: str = Field(default="15m", alias="TIMEFRAME")
    trade_mode: str = Field(default="dedust", alias="TRADE_MODE")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")

    # Capital
    trade_amount: float = Field(default=100.0, ge=0, alias="TRADE_AMOUNT")
    max_open_trades: int = Field(default=1, ge=1, alias="MAX_OPEN_TRADES")
    min_stake_ton: float = Field(default=5.0, ge=0, alias="MIN_STAKE_TON")
    min_profit_ton: float = Field(default=5.0, ge=0, alias="MIN_PROFIT_TON")
    target_net_pct: float = Field(default=13.0, ge=0, alias="TARGET_NET_PCT")
    take_profit_pct: float = Field(default=22.0, ge=0, alias="TAKE_PROFIT_PCT")
    stop_loss_pct: float = Field(default=5.0, ge=0, alias="STOP_LOSS_PCT")

    # Security
    secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), alias="SECRET_KEY"
    )
    report_errors: bool = Field(default=True, alias="REPORT_ERRORS")

    # TON Blockchain
    ton_wallet: str = Field(default="", alias="TON_WALLET")
    token_address: str = Field(default="", alias="TOKEN_ADDRESS")
    pool_address: str = Field(default="", alias="POOL_ADDRESS")
    ton_mnemonic: SecretStr = Field(
        default_factory=lambda: SecretStr(""), alias="TON_MNEMONIC"
    )

    # Binance
    binance_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), alias="BINANCE_API_KEY"
    )
    binance_api_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(""), alias="BINANCE_API_SECRET"
    )
    use_binance_testnet: bool = Field(default=True, alias="USE_BINANCE_TESTNET")

    # Sub-configs
    fees: FeeConfig = Field(default_factory=FeeConfig)
    grid: GridConfig = Field(default_factory=GridConfig)
    trail: TrailConfig = Field(default_factory=TrailConfig)
    dca: DcaConfig = Field(default_factory=DcaConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    protection: ProtectionConfig = Field(default_factory=ProtectionConfig)

    @field_validator("ton_mnemonic", mode="before")
    @classmethod
    def validate_mnemonic(cls, v):
        if not v or str(v).strip() == "":
            return v
        words = str(v).strip().split()
        if len(words) != 24:
            raise ValueError(f"TON mnemonic must be exactly 24 words, got {len(words)}")
        return v

    @property
    def required_gross_pct(self) -> float:
        fee = self.fees.pct / 100.0
        denom = 1.0 - fee
        if denom <= 0:
            return self.target_net_pct + self.fees.round_trip
        return (self.target_net_pct + 2.0 * self.fees.pct) / denom
