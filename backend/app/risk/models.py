from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RuleEvaluationResult(BaseModel):
    rule_name: str
    status: CheckStatus
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class RiskConfig(BaseModel):
    """
    Configurable risk limits for TokenIQ automated trading safeguards.
    All monetary and quantity calculations use decimal-safe representations.
    """
    max_order_notional_usd: float = Field(
        default=500.0,
        gt=0,
        description="Maximum allowed notional value for a single order in USD",
    )
    max_position_size: float = Field(
        default=10.0,
        gt=0,
        description="Maximum contract quantity allowed for a single position",
    )
    max_daily_realized_loss_usd: float = Field(
        default=100.0,
        gt=0,
        description="Maximum daily realized loss before trading is halted (USD)",
    )
    max_orders_per_day: int = Field(
        default=20,
        gt=0,
        description="Maximum number of submitted orders allowed per calendar day",
    )
    max_concurrent_positions: int = Field(
        default=1,
        gt=0,
        le=20,
        description="Maximum number of simultaneous open positions allowed",
    )
    min_stop_loss_distance_pct: float = Field(
        default=0.5,
        ge=0.1,
        le=50.0,
        description="Minimum required distance from entry price to stop-loss in percent (e.g. 0.5%)",
    )
    max_signal_age_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Maximum acceptable age of a trading signal in seconds before rejection",
    )

    @field_validator(
        "max_order_notional_usd",
        "max_position_size",
        "max_daily_realized_loss_usd",
        "min_stop_loss_distance_pct",
    )
    @classmethod
    def validate_positive_finite(cls, v: float, info) -> float:
        import math
        if math.isnan(v) or math.isinf(v) or v <= 0:
            raise ValueError(f"{info.field_name} must be a positive finite number")
        return v


class SafetyState(BaseModel):
    """
    Persistent safety and kill-switch state.
    Trading must be disabled by default. If the file cannot be read, the engine fails closed.
    """
    trading_enabled: bool = Field(
        default=False,
        description="Master trading permission. Strictly False by default.",
    )
    kill_switch_engaged: bool = Field(
        default=True,
        description="Emergency kill-switch. Strictly True by default.",
    )
    kill_switch_reason: Optional[str] = Field(
        default="Default startup state: trading disabled pending deliberate user activation.",
        description="Reason for kill-switch engagement",
    )
    kill_switch_activated_at: Optional[int] = Field(
        default=None,
        description="Timestamp in seconds when kill switch was engaged",
    )
    last_reset_at: Optional[int] = Field(
        default=None,
        description="Timestamp in seconds of last explicit reset",
    )
    last_reset_reason: Optional[str] = Field(
        default=None,
        description="Deliberate user justification for resetting kill switch",
    )
    daily_date: str = Field(
        default="",
        description="UTC calendar date for daily counter tracking (YYYY-MM-DD)",
    )
    orders_submitted_today: int = Field(
        default=0,
        ge=0,
        description="Count of actual orders submitted to the exchange today",
    )
    evaluations_today: int = Field(
        default=0,
        ge=0,
        description="Count of dry-run risk evaluations performed today",
    )
    evaluated_signal_ids: Dict[str, int] = Field(
        default_factory=dict,
        description="Persistent registry of evaluated signal IDs mapping signal_id -> timestamp",
    )


class TradingStatus(BaseModel):
    """
    Consolidated trading safety status response.
    """
    trading_enabled: bool
    kill_switch_engaged: bool
    kill_switch_reason: Optional[str] = None
    kill_switch_activated_at: Optional[int] = None
    last_reset_at: Optional[int] = None
    dry_run_mode: bool = True
    testnet_enforced: bool = True
    base_url: str
    active_risk_limits: RiskConfig
    orders_submitted_today: int
    evaluations_today: int
    daily_realized_loss_usd: float
    active_positions_count: int
    disclaimer: str = (
        "Operational safety status. Dry-run when trading is disabled; Testnet-only when enabled."
    )


class RiskCheckRequest(BaseModel):
    """
    Request payload for dry-run signal risk evaluation.
    """
    symbol: str = Field(..., description="Target contract symbol (e.g. BTCUSD)")
    side: str = Field(..., description="Proposed trade side: 'BUY' or 'SELL'")
    position_intent: Optional[str] = Field(
        default=None,
        description="Intent: OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT",
    )
    quantity: float = Field(..., gt=0, description="Proposed order contract quantity")
    price: float = Field(..., gt=0, description="Proposed execution or current market price")
    stop_loss: Optional[float] = Field(
        default=None,
        gt=0,
        description="Proposed protective stop-loss price",
    )
    signal_id: str = Field(..., min_length=1, description="Unique strategy signal identifier")
    timestamp: Optional[int] = Field(
        default=None,
        description="Signal generation epoch timestamp in seconds",
    )
    strategy_id: Optional[str] = Field(default="manual", description="Originating strategy identifier")


class RiskCheckResult(BaseModel):
    """
    Comprehensive dry-run risk check decision.
    """
    approved: bool = Field(..., description="Whether the proposed order passed all risk checks")
    decision: str = Field(..., description="'APPROVED' or 'REJECTED'")
    symbol: str
    signal_id: str
    proposed_notional_usd: float
    evaluated_at: int
    rules_evaluated: List[RuleEvaluationResult]
    reasons: List[str]
    disclaimer: str = (
        "DRY-RUN RESULT: This risk evaluation did not place any order on the exchange. "
        "Automated order submission remains disabled."
    )


class KillSwitchRequest(BaseModel):
    reason: str = Field(
        default="Emergency manual kill switch triggered by user.",
        min_length=3,
        description="User justification for engaging the kill switch",
    )


class KillSwitchResetRequest(BaseModel):
    confirm: bool = Field(
        ...,
        description="Deliberate confirmation: must be explicitly True to disengage kill switch",
    )
    reason: str = Field(
        ...,
        min_length=5,
        description="Deliberate operational justification for resetting the kill switch",
    )
