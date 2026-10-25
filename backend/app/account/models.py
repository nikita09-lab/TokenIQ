import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class WalletBalanceItem(BaseModel):
    """
    Normalized wallet asset balance representation.
    """
    asset_id: int = Field(default=0, description="Asset numeric identifier")
    asset_symbol: str = Field(..., description="Asset symbol (e.g. USDT, BTC, USD)")
    balance: float = Field(default=0.0, description="Total balance")
    available_balance: float = Field(default=0.0, description="Balance available for margin and trading")
    blocked_margin: float = Field(default=0.0, description="Margin blocked in active positions/orders")
    order_margin: float = Field(default=0.0, description="Margin blocked in pending orders")
    position_margin: float = Field(default=0.0, description="Margin locked in active positions")
    usd_value: Optional[float] = Field(default=None, description="Estimated USD value of this balance")


class PositionItem(BaseModel):
    """
    Normalized open futures/perpetual position item.
    """
    product_id: int
    symbol: str = Field(..., description="Contract symbol (e.g. BTCUSD)")
    side: Literal["LONG", "SHORT"]
    size: float = Field(..., description="Position quantity in contracts")
    entry_price: float = Field(..., description="Average entry fill price")
    mark_price: float = Field(..., description="Current mark price")
    margin: float = Field(default=0.0, description="Initial margin locked in USD")
    unrealized_pnl: float = Field(default=0.0, description="Floating unrealized PnL in USD")
    realized_pnl: float = Field(default=0.0, description="Realized PnL in USD")
    liquidation_price: Optional[float] = Field(default=None, description="Estimated liquidation price")
    bankruptcy_price: Optional[float] = Field(default=None, description="Bankruptcy price")
    leverage: Optional[float] = Field(default=None, description="Position effective leverage")
    updated_at: Optional[int] = Field(default=None, description="Timestamp in milliseconds")


class OrderItem(BaseModel):
    """
    Normalized order representation (open or historical).
    """
    order_id: str
    product_id: int
    symbol: str = Field(..., description="Contract symbol (e.g. BTCUSD)")
    side: Literal["BUY", "SELL"]
    order_type: str = Field(..., description="Order type (e.g. limit_order, market_order)")
    size: float = Field(..., description="Total order size in contracts")
    unfilled_size: float = Field(default=0.0, description="Remaining unfilled contracts")
    limit_price: Optional[float] = Field(default=None, description="Limit order price")
    stop_price: Optional[float] = Field(default=None, description="Stop trigger price if applicable")
    average_fill_price: Optional[float] = Field(default=None, description="Average execution fill price")
    state: str = Field(..., description="Order state: open, pending, closed, cancelled, filled")
    created_at: int = Field(..., description="Creation epoch timestamp in seconds")
    updated_at: Optional[int] = Field(default=None, description="Last update epoch timestamp")


class AccountOverviewData(BaseModel):
    """
    Complete consolidated read-only account dashboard payload.
    """
    authenticated: bool = Field(..., description="Whether API credentials successfully authenticated")
    is_testnet: bool = Field(default=True, description="Strictly true: testnet safety flag")
    environment: str = Field(default="testnet", description="Environment identifier")
    base_url: str = Field(..., description="Connected exchange endpoint")
    masked_api_key: str = Field(default="", description="Masked API key preview (e.g. q72...det)")
    client_ip: Optional[str] = Field(default=None, description="Detected outbound backend egress IP")
    total_balance_usd: float = Field(default=0.0, description="Total portfolio value in USD")
    account_equity_usd: float = Field(default=0.0, description="Total account equity = total_balance_usd + total_unrealized_pnl_usd")
    available_balance_usd: float = Field(default=0.0, description="Total trading margin available in USD")
    total_margin_used_usd: float = Field(default=0.0, description="Total margin locked in positions and orders in USD")
    order_margin_usd: float = Field(default=0.0, description="Total margin locked in pending orders in USD")
    position_margin_usd: float = Field(default=0.0, description="Total margin locked in open positions in USD")
    total_unrealized_pnl_usd: float = Field(default=0.0, description="Total floating unrealized PnL in USD")
    account_currency: str = Field(default="USD", description="Settlement asset currency")
    balances: List[WalletBalanceItem] = Field(default_factory=list)
    positions: List[PositionItem] = Field(default_factory=list)
    open_orders: List[OrderItem] = Field(default_factory=list)
    recent_orders: List[OrderItem] = Field(default_factory=list)
    last_updated_at: int = Field(default_factory=lambda: int(time.time()))
    last_balance_update_timestamp: int = Field(default_factory=lambda: int(time.time()), description="Timestamp of last successful balance sync")
    diagnostic: Optional[str] = Field(default=None, description="Diagnostic error or status guidance")
    warning: Optional[str] = Field(default=None, description="Operational warning if applicable")
    disclaimer: str = Field(
        default=(
            "TESTNET NOTICE: All balances, positions, and orders displayed are simulated demo funds on "
            "Delta Exchange India Testnet. Real money is not involved. Automated strategy execution is disabled."
        ),
        description="Testnet risk disclaimer",
    )
