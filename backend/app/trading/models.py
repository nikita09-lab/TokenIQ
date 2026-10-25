import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "limit_order"
    MARKET = "market_order"


class OrderState(str, Enum):
    PREVIEWED = "PREVIEWED"
    CONFIRMING = "CONFIRMING"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"


class OrderPreviewRequest(BaseModel):
    """
    Request to validate and preview a proposed testnet order.
    Does NOT submit any order to the exchange.
    """
    symbol: str = Field(..., description="Target contract symbol (e.g. BTCUSD, ETHUSD, SOLUSD)")
    side: Literal["BUY", "SELL"] = Field(..., description="Trade side")
    order_type: Literal["limit_order", "market_order"] = Field(
        default="limit_order",
        description="Order type: 'limit_order' or 'market_order'",
    )
    quantity: float = Field(..., gt=0, description="Order quantity in contracts")
    price: Optional[float] = Field(
        default=None,
        gt=0,
        description="Limit price in USD (required for limit_order)",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        gt=0,
        description="Protective stop-loss price in USD (mandatory for risk check approval)",
    )
    position_intent: Optional[Literal["OPEN_LONG", "CLOSE_LONG", "OPEN_SHORT", "CLOSE_SHORT"]] = Field(
        default=None,
        description="Trading intent (e.g. OPEN_LONG, CLOSE_LONG)",
    )
    client_order_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional custom client order identifier",
    )

    @field_validator("quantity", "price", "stop_loss")
    @classmethod
    def validate_finite(cls, v: Optional[float], info) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v) or v <= 0:
                raise ValueError(f"{info.field_name} must be a positive finite number")
        return v


class OrderPreviewResponse(BaseModel):
    """
    Pre-validated preview of a proposed testnet order with TTL and pre-trade risk evaluation.
    """
    preview_id: str = Field(..., description="Unique preview identifier")
    symbol: str
    product_id: int
    side: Literal["BUY", "SELL"]
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    contract_value: float
    tick_size: float
    estimated_notional_usd: float
    environment: str = "TESTNET"
    verified_testnet_host: str
    created_at: int
    expires_at: int
    ttl_seconds: int
    can_submit: bool
    risk_decision: str
    risk_reasons: List[str] = Field(default_factory=list)
    rules_evaluated: List[Dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = (
        "PREVIEW ONLY: No exchange order has been placed. "
        "Explicit user confirmation is required within the TTL window to submit."
    )


class OrderConfirmRequest(BaseModel):
    """
    Explicit user confirmation to submit a previously previewed testnet order.
    """
    preview_id: str = Field(..., min_length=1, description="Preview ID to confirm")
    confirm: bool = Field(..., description="Must explicitly be True to confirm")
    notes: Optional[str] = Field(default=None, max_length=256, description="Optional operator note")


class OrderCancelRequest(BaseModel):
    """
    Request to cancel an open testnet order.
    """
    reason: Optional[str] = Field(default="Manual user cancellation", max_length=256)


class OrderExecutionRecord(BaseModel):
    """
    Durable record of an order's lifecycle, state transitions, and exchange reconciliation.
    """
    preview_id: str
    client_order_id: str
    order_id: Optional[str] = None
    symbol: str
    product_id: int
    side: Literal["BUY", "SELL"]
    order_type: str
    size: float
    unfilled_size: float
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    average_fill_price: Optional[float] = None
    state: str = "PREVIEWED"
    notional_usd: float
    created_at: int
    updated_at: int
    confirmed_at: Optional[int] = None
    submitted_at: Optional[int] = None
    error_message: Optional[str] = None
    reconciliation_needed: bool = False
    reconciliation_attempts: int = 0
    reconciliation_last_at: Optional[int] = None
    exchange_state: Optional[str] = None
    exchange_response: Optional[Dict[str, Any]] = None


class ExecutionStatusResponse(BaseModel):
    """
    Consolidated readiness and status of the order execution service.
    """
    service_ready: bool
    testnet_enforced: bool
    verified_host: str
    trading_enabled: bool
    kill_switch_engaged: bool
    kill_switch_reason: Optional[str] = None
    orders_submitted_today: int
    active_local_orders_count: int
    unknown_orders_count: int
    disclaimer: str = (
        "TESTNET ORDER EXECUTION: Live trading on Delta Exchange India Testnet only. "
        "Production real-money trading is strictly blocked."
    )
