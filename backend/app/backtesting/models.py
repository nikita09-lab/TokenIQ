import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    """
    Configuration parameters for running a historical strategy backtest.
    """
    symbol: str = Field(..., description="Cryptocurrency trading pair symbol (e.g. 'BTCUSD')")
    resolution: str = Field(default="1h", description="Candle interval (e.g. '15m', '1h', '4h', '1d')")
    start_time: Optional[int] = Field(
        default=None,
        description="Start timestamp in Unix seconds (e.g. 30 days ago). If omitted, defaults to 30 days ago.",
    )
    end_time: Optional[int] = Field(
        default=None,
        description="End timestamp in Unix seconds. Defaults to current time.",
    )
    initial_capital: float = Field(
        default=10000.0,
        gt=0,
        description="Starting cash capital in USD",
    )
    fee_rate: float = Field(
        default=0.0005,
        ge=0.0,
        le=0.05,
        description="Exchange trading fee per transaction (e.g. 0.0005 = 0.05% taker fee)",
    )
    slippage_rate: float = Field(
        default=0.0005,
        ge=0.0,
        le=0.05,
        description="Expected execution slippage per transaction (e.g. 0.0005 = 0.05%)",
    )
    execution_mode: Literal["next_open", "current_close"] = Field(
        default="next_open",
        description=(
            "Order execution assumption. 'next_open' executes at the open of the candle immediately "
            "following the signal candle (strictly preventing look-ahead bias). 'current_close' models "
            "execution at the signal candle's close price."
        ),
    )
    strategy_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional overrides for EMA Crossover strategy (fast_period, slow_period, rsi_period, etc.)",
    )


class Trade(BaseModel):
    """
    Detailed audit record of an individual simulated round-trip trade.
    """
    trade_id: int = Field(..., description="Sequential trade identifier")
    symbol: str = Field(..., description="Trading pair symbol")
    side: str = Field(default="LONG", description="Position side ('LONG')")
    entry_time: int = Field(..., description="Entry fill timestamp in Unix seconds")
    entry_price: float = Field(..., description="Effective execution price after slippage")
    entry_fee: float = Field(..., description="Fee paid upon entering position")
    exit_time: int = Field(..., description="Exit fill timestamp in Unix seconds")
    exit_price: float = Field(..., description="Effective execution price after slippage")
    exit_fee: float = Field(..., description="Fee paid upon exiting position")
    total_fees: float = Field(..., description="Total fees paid for the round-trip")
    quantity: float = Field(..., description="Quantity of base asset traded")
    cost_basis: float = Field(..., description="Total USD cost to enter the position")
    proceeds: float = Field(..., description="Total USD proceeds received upon exit")
    gross_pnl: float = Field(..., description="Gross profit/loss before fees")
    net_pnl: float = Field(..., description="Net profit/loss after fees")
    return_pct: float = Field(..., description="Percentage return on the trade")
    exit_reason: str = Field(..., description="Reason for trade exit ('SELL_SIGNAL' or 'END_OF_DATA')")
    duration_seconds: int = Field(..., description="Holding duration in seconds")


class EquityPoint(BaseModel):
    """
    Time-series snapshot of account equity, cash, and drawdown at a specific candle.
    """
    time: int = Field(..., description="Unix timestamp of the candle")
    close: float = Field(..., description="Market close price at this timestamp")
    cash: float = Field(..., description="Available cash balance in USD")
    position_qty: float = Field(..., description="Current quantity of crypto held")
    position_value: float = Field(..., description="Current market value of position in USD")
    equity: float = Field(..., description="Total portfolio value (cash + position_value)")
    drawdown_dollars: float = Field(..., description="Dollar drawdown from all-time portfolio peak")
    drawdown_pct: float = Field(..., description="Percentage drawdown from all-time portfolio peak")
    in_position: bool = Field(..., description="Whether a position was held at this bar")


class BacktestMetrics(BaseModel):
    """
    Quantitative performance metrics summarizing backtest execution.
    """
    initial_capital: float
    final_equity: float
    net_profit: float
    net_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate_pct: float
    loss_rate_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: Optional[float]
    max_drawdown_dollars: float
    max_drawdown_pct: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    total_fees_paid: float
    buy_and_hold_return_pct: float
    total_bars_analyzed: int
    market_exposure_pct: float


class BacktestResult(BaseModel):
    """
    Complete backtest payload containing parameters, summary metrics, equity time-series, and trade history.
    """
    backtest_id: str
    symbol: str
    resolution: str
    start_time: int
    end_time: int
    execution_mode: str
    assumptions_note: str
    strategy_id: str
    strategy_params: Dict[str, Any]
    metrics: BacktestMetrics
    equity_curve: List[EquityPoint]
    trades: List[Trade]
    disclaimer: str = Field(
        default=(
            "DISCLAIMER: Historical backtesting results are hypothetical and modeled for educational and research "
            "purposes. Past performance does not guarantee future results or profitability. Model assumes ideal "
            "liquidity and does not account for exchange outages, market impact, or funding rates."
        ),
        description="Regulatory and risk disclaimer",
    )
