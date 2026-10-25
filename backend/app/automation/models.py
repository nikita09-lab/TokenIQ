import math
import time
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class AutomationState(str, Enum):
    OFF = "OFF"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class PositionSizingMode(str, Enum):
    FIXED_CONTRACTS = "fixed_contracts"
    FIXED_NOTIONAL = "fixed_notional"
    RISK_BUDGET = "risk_budget"


class SignalLifecycleState(str, Enum):
    GENERATED = "GENERATED"
    REJECTED = "REJECTED"
    RISK_APPROVED = "RISK_APPROVED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class PositionLifecycleState(str, Enum):
    FLAT = "FLAT"
    ENTRY_SIGNAL = "ENTRY_SIGNAL"
    RISK_CHECK = "RISK_CHECK"
    ENTRY_PENDING = "ENTRY_PENDING"
    OPEN = "OPEN"
    PROTECTION_VERIFIED = "PROTECTION_VERIFIED"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    EXIT_PENDING = "EXIT_PENDING"


class AutomationConfig(BaseModel):
    """
    Persistent automated trading configuration for TokenIQ.
    Starts strictly disabled (enabled=False).
    """
    enabled: bool = Field(
        default=False,
        description="Master automated trading switch. Strictly False by default.",
    )
    selected_strategy: str = Field(
        default="ema_crossover",
        description="Identifier of configured strategy in registry",
    )
    trading_symbol: str = Field(
        default="BTCUSD",
        description="Target contract symbol for automated trading (e.g. BTCUSD, ETHUSD)",
    )
    candle_interval: str = Field(
        default="1h",
        description="Candle interval (e.g. 1m, 5m, 15m, 1h, 1d)",
    )
    strategy_parameters: Dict[str, Any] = Field(
        default_factory=lambda: {
            "fast_period": 9,
            "middle_period": 11,
            "slow_period": 20,
            "rsi_period": 14,
            "rsi_filter_enabled": False,
            "rsi_buy_min": 40.0,
            "rsi_overbought": 70.0,
            "rsi_sell_max": 60.0,
            "rsi_oversold": 30.0,
            "volume_confirmation_enabled": False,
            "volume_ma_period": 20,
            "sell_intent": "CLOSE_LONG",
        },
        description="Strategy indicator parameters",
    )
    position_sizing_mode: PositionSizingMode = Field(
        default=PositionSizingMode.FIXED_CONTRACTS,
        description="Position sizing calculation methodology",
    )
    fixed_contract_quantity: float = Field(
        default=1.0,
        gt=0,
        description="Fixed contract quantity when using fixed_contracts mode",
    )
    fixed_notional_usd: float = Field(
        default=100.0,
        gt=0,
        description="Target notional value in USD when using fixed_notional mode",
    )
    risk_budget_usd: float = Field(
        default=25.0,
        gt=0,
        description="Maximum risk amount in USD per trade for risk_budget sizing",
    )
    maximum_order_notional: float = Field(
        default=500.0,
        gt=0,
        description="Maximum allowed notional exposure per order in USD",
    )
    maximum_position_size: float = Field(
        default=10.0,
        gt=0,
        description="Maximum allowed position size in contracts",
    )
    maximum_concurrent_positions: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Maximum simultaneous open positions allowed in automation",
    )
    maximum_daily_realized_loss: float = Field(
        default=100.0,
        gt=0,
        description="Daily realized loss limit in USD triggering automated pause",
    )
    maximum_orders_per_day: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Maximum automated orders per calendar day",
    )
    maximum_trades_per_day: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Maximum round-trip trades allowed per day",
    )
    protective_stop_loss_percentage: float = Field(
        default=1.5,
        ge=0.5,
        le=20.0,
        description="Mandatory protective stop loss distance in percent (e.g. 1.5%)",
    )
    take_profit_percentage: Optional[float] = Field(
        default=4.0,
        ge=0.5,
        le=50.0,
        description="Optional take profit target in percent",
    )
    maximum_allowed_slippage: float = Field(
        default=0.5,
        ge=0.01,
        le=5.0,
        description="Maximum allowed execution slippage in percent",
    )
    cooldown_period_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Mandatory cooldown between automated trades in seconds",
    )
    allow_long: bool = Field(
        default=True,
        description="Allow automated long entries",
    )
    allow_short: bool = Field(
        default=False,
        description="Allow automated short entries (requires verified margin & strategy)",
    )
    allow_reentry: bool = Field(
        default=False,
        description="Allow re-entry on new signal after exit (subject to cooldown)",
    )
    allow_pyramiding: bool = Field(
        default=False,
        description="Allow adding to an existing position (strictly False by default)",
    )
    require_confirmed_candle: bool = Field(
        default=True,
        description="Require candle close confirmation before signal evaluation",
    )

    @field_validator(
        "fixed_contract_quantity",
        "fixed_notional_usd",
        "risk_budget_usd",
        "maximum_order_notional",
        "maximum_position_size",
        "maximum_daily_realized_loss",
        "protective_stop_loss_percentage",
        "maximum_allowed_slippage",
    )
    @classmethod
    def validate_finite_positive(cls, v: float, info) -> float:
        if math.isnan(v) or math.isinf(v) or v <= 0:
            raise ValueError(f"{info.field_name} must be a positive finite number")
        return v


class AutomatedSignal(BaseModel):
    """
    Durable structured trading signal generated by the automated strategy runner.
    """
    signal_id: str = Field(..., description="Unique deterministic signal identifier")
    strategy_id: str
    strategy_version: str = "1.0.0"
    symbol: str
    timeframe: str
    candle_timestamp: int = Field(..., description="Candle bar open epoch timestamp")
    signal_direction: Literal["BUY", "SELL", "EXIT_LONG", "EXIT_SHORT", "NO_SIGNAL"]
    position_intent: str = Field(..., description="OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, NO_ACTION")
    entry_rationale: str
    intended_price: float
    intended_quantity: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    created_at: int = Field(default_factory=lambda: int(time.time()))
    idempotency_key: str = Field(..., description="Durable idempotency hash")
    lifecycle_state: SignalLifecycleState = SignalLifecycleState.GENERATED
    rejection_reason: Optional[str] = None
    client_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None


class PositionStateRecord(BaseModel):
    """
    Managed position tracking record synchronized with authoritative exchange state.
    """
    symbol: str
    product_id: int
    lifecycle_state: PositionLifecycleState = PositionLifecycleState.FLAT
    side: Optional[Literal["LONG", "SHORT"]] = None
    quantity: float = 0.0
    average_entry_price: float = 0.0
    current_notional_usd: float = 0.0
    entry_order_id: Optional[str] = None
    entry_client_order_id: Optional[str] = None
    stop_loss_order_id: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_order_id: Optional[str] = None
    take_profit_price: Optional[float] = None
    protection_verified: bool = False
    opened_at: Optional[int] = None
    updated_at: int = Field(default_factory=lambda: int(time.time()))
    closed_at: Optional[int] = None
    realized_pnl_usd: float = 0.0
    last_exit_reason: Optional[str] = None


class AutomationStatusResponse(BaseModel):
    """
    Live status payload for frontend automation dashboard.
    """
    state: AutomationState
    enabled: bool
    is_paused: bool
    pause_reason: Optional[str] = None
    kill_switch_engaged: bool
    testnet_enforced: bool = True
    verified_host: str
    config: AutomationConfig
    active_position: Optional[PositionStateRecord] = None
    latest_signal: Optional[AutomatedSignal] = None
    latest_signal_rejection_reason: Optional[str] = None
    latest_order_status: Optional[str] = None
    orders_submitted_today: int = 0
    trades_completed_today: int = 0
    daily_realized_pnl_usd: float = 0.0
    current_exposure_usd: float = 0.0
    last_candle_timestamp: Optional[int] = None
    last_market_data_update_at: Optional[int] = None
    last_reconciliation_at: Optional[int] = None
    last_error: Optional[str] = None
    worker_uptime_seconds: int = 0
    disclaimer: str = (
        "AUTOMATED TESTNET TRADING: Operates strictly on Delta Exchange India Testnet. "
        "Production real-money trading is technically impossible. "
        "Requires explicit user activation and passes all pre-trade risk safeguards."
    )
