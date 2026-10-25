import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.backtesting.models import EquityPoint, Trade


class ParameterSearchSpace(BaseModel):
    """
    Defines the discrete parameter grid to evaluate for the EMA Crossover + RSI strategy.
    """
    fast_periods: List[int] = Field(
        default=[5, 9, 13],
        description="Fast EMA periods to test (must be strictly less than slow EMA periods)",
    )
    slow_periods: List[int] = Field(
        default=[21, 34, 55],
        description="Slow EMA periods to test",
    )
    rsi_periods: List[int] = Field(
        default=[14],
        description="RSI lookback periods to test",
    )
    rsi_buy_mins: List[float] = Field(
        default=[40.0],
        description="Minimum RSI momentum thresholds for BUY entry confirmation",
    )
    rsi_sell_maxs: List[float] = Field(
        default=[60.0],
        description="Maximum RSI momentum thresholds for SELL exit confirmation",
    )
    volume_confirmation: List[bool] = Field(
        default=[False],
        description="Whether to require candle volume > 20-period volume SMA",
    )


class EvaluationRequest(BaseModel):
    """
    Configuration for a bounded chronological walk-forward parameter evaluation job.
    """
    symbol: str = Field(default="BTCUSD", description="Cryptocurrency trading pair symbol")
    resolution: str = Field(default="1h", description="Candle interval (e.g. '15m', '1h', '4h', '1d')")
    start_time: Optional[int] = Field(
        default=None,
        description="Start timestamp in Unix seconds. Defaults to 45 days ago if omitted.",
    )
    end_time: Optional[int] = Field(
        default=None,
        description="End timestamp in Unix seconds. Defaults to current time.",
    )
    split_ratio: float = Field(
        default=0.70,
        ge=0.50,
        le=0.90,
        description="Chronological train/test split ratio (e.g. 0.70 = 70% in-sample training, 30% out-of-sample testing)",
    )
    initial_capital: float = Field(
        default=10000.0,
        gt=0,
        description="Starting cash capital in USD for each evaluation period",
    )
    fee_rate: float = Field(
        default=0.0005,
        ge=0.0,
        le=0.05,
        description="Exchange trading fee per transaction (e.g. 0.0005 = 0.05%)",
    )
    slippage_rate: float = Field(
        default=0.0005,
        ge=0.0,
        le=0.05,
        description="Expected execution slippage per transaction (e.g. 0.0005 = 0.05%)",
    )
    execution_mode: Literal["next_open", "current_close"] = Field(
        default="next_open",
        description="Order fill assumption: 'next_open' eliminates look-ahead bias.",
    )
    max_combinations: int = Field(
        default=100,
        ge=1,
        le=200,
        description="Hard boundary on parameter grid size to prevent server resource exhaustion.",
    )
    search_space: ParameterSearchSpace = Field(
        default_factory=ParameterSearchSpace,
        description="Configurable grid parameters to test.",
    )
    ranking_metric: Literal["net_return_pct", "profit_factor", "win_rate_pct"] = Field(
        default="net_return_pct",
        description="Performance metric used to select top strategies using training data only.",
    )


class PeriodMetrics(BaseModel):
    """
    Performance summary metrics for a specific chronological window (In-Sample or Out-of-Sample).
    """
    period_type: Literal["in_sample", "out_of_sample"]
    start_time: int
    end_time: int
    total_bars: int
    initial_capital: float
    final_equity: float
    net_profit: float
    net_return_pct: float
    max_drawdown_dollars: float
    max_drawdown_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate_pct: float
    loss_rate_pct: float
    profit_factor: Optional[float] = None
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_trade_pnl: float = 0.0
    total_fees_paid: float
    market_exposure_pct: float
    buy_and_hold_return_pct: float


class StrategyParamCombination(BaseModel):
    """
    Specific validated parameter assignment for one backtest run.
    """
    fast_period: int
    slow_period: int
    rsi_period: int
    rsi_buy_min: float
    rsi_sell_max: float
    volume_confirmation_enabled: bool
    rsi_filter_enabled: bool = True
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    volume_ma_period: int = 20
    sell_intent: str = "CLOSE_LONG"


class EvaluatedParameterSet(BaseModel):
    """
    Complete comparative record for a single parameter set across both In-Sample and Out-of-Sample periods.
    """
    rank: int = Field(..., description="Rank based strictly on In-Sample (Training) performance")
    params: StrategyParamCombination
    params_label: str
    in_sample: PeriodMetrics
    out_of_sample: PeriodMetrics
    robustness_ratio: Optional[float] = Field(
        default=None,
        description="Ratio of out-of-sample return to in-sample return (1.0 = equal, <0 = broke down)",
    )
    return_degradation_pct: float = Field(
        default=0.0,
        description="Percentage point difference between in-sample and out-of-sample return (positive = degradation)",
    )
    drawdown_increase_ratio: Optional[float] = Field(
        default=None,
        description="Ratio of out-of-sample max drawdown to in-sample max drawdown (>1.0 = worse drawdown)",
    )
    is_overfit: bool = Field(
        default=False,
        description="Flagged true if in-sample performance was positive but out-of-sample performance degraded severely",
    )
    overfit_warning: Optional[str] = Field(
        default=None,
        description="Human-readable warning explaining why this parameter set is suspected of overfitting",
    )


class EvaluationResult(BaseModel):
    """
    Top-level payload returned by the Strategy Evaluation and Robustness Testing engine.
    """
    evaluation_id: str
    symbol: str
    resolution: str
    execution_mode: str
    total_bars: int
    split_ratio: float
    train_bars: int
    test_bars: int
    train_start_time: int
    train_end_time: int
    test_start_time: int
    test_end_time: int
    total_combinations_requested: int
    total_combinations_evaluated: int
    invalid_combinations_filtered: int
    ranking_metric: str
    selected_winner_params: StrategyParamCombination
    selected_winner_label: str
    selected_winner_is_overfit: bool
    selected_winner_overfit_warning: Optional[str] = None
    parameter_sets: List[EvaluatedParameterSet]
    winner_train_equity_curve: List[EquityPoint] = []
    winner_test_equity_curve: List[EquityPoint] = []
    winner_train_trades: List[Trade] = []
    winner_test_trades: List[Trade] = []
    created_at: int = Field(default_factory=lambda: int(time.time()))
    disclaimer: str = Field(
        default=(
            "DISCLAIMER: TokenIQ Strategy Evaluation and Robustness Testing provides quantitative historical simulation. "
            "In-sample performance is subject to data-mining and curve-fitting bias. Out-of-sample testing models unseen "
            "historical data to evaluate robustness, but does not guarantee live profitability. Real execution may "
            "experience exchange outages, latency, liquidation, and unanticipated slippage."
        ),
        description="Regulatory and risk disclaimer",
    )
