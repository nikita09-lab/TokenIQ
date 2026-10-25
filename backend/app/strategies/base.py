from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class PositionIntent(str, Enum):
    OPEN_LONG = "OPEN_LONG"
    CLOSE_LONG = "CLOSE_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG_OR_OPEN_SHORT = "CLOSE_LONG_OR_OPEN_SHORT"
    NO_ACTION = "NO_ACTION"


class StrategySignal(BaseModel):
    """
    Structured quantitative trading signal generated from completed candle data.
    """
    strategy_id: str = Field(..., description="Unique strategy identifier (e.g. 'ema_crossover')")
    strategy_name: str = Field(..., description="Human-readable strategy name")
    symbol: str = Field(..., description="Trading pair symbol (e.g. 'BTCUSD')")
    resolution: str = Field(..., description="Candle interval (e.g. '1h')")
    signal: SignalType = Field(..., description="Signal directive: BUY, SELL, or HOLD")
    position_intent: PositionIntent = Field(
        ...,
        description=(
            "Explicit definition of the signal action. For SELL signals, distinguishes "
            "between closing a long position ('CLOSE_LONG') vs opening a short position ('OPEN_SHORT')."
        ),
    )
    timestamp: int = Field(..., description="Unix timestamp of the completed candle (seconds)")
    candle_time: int = Field(..., description="Completed candle open/bar timestamp (seconds)")
    close: float = Field(..., description="Closing price of the completed candle")
    fast_ema: Optional[float] = Field(None, description="Fast Exponential Moving Average value")
    slow_ema: Optional[float] = Field(None, description="Slow Exponential Moving Average value")
    rsi: Optional[float] = Field(None, description="Relative Strength Index value")
    volume: Optional[float] = Field(None, description="Volume of the completed candle")
    volume_ma: Optional[float] = Field(None, description="Volume moving average value if enabled")
    explanation: str = Field(..., description="Detailed analytical justification for the signal")
    is_repeated: bool = Field(
        False,
        description="True if this exact completed candle was already evaluated previously",
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional technical metrics and indicator states",
    )
    disclaimer: str = Field(
        default=(
            "DISCLAIMER: TokenIQ signals are research indicators based on past technical data. "
            "They do not guarantee profit, should not be construed as investment advice, "
            "and are not connected to automated order execution."
        ),
        description="Regulatory and risk disclaimer",
    )


class BaseStrategy(ABC):
    """
    Abstract Base Class for TokenIQ trading strategies.
    Ensures decoupled, testable, and configurable indicator and signal generation.
    """

    def __init__(self, strategy_id: str, name: str, description: str):
        self.strategy_id = strategy_id
        self.name = name
        self.description = description
        self.parameters: Dict[str, Any] = {}
        # Tracks last evaluated completed candle timestamp per symbol to prevent repeated signals
        self._last_evaluated_candle: Dict[str, int] = {}
        # Stores the latest generated signal per symbol
        self._latest_signals: Dict[str, StrategySignal] = {}

    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return the schema and metadata of configurable strategy parameters."""
        pass

    @abstractmethod
    def configure(self, params: Dict[str, Any]) -> None:
        """Validate and apply updated strategy parameters."""
        pass

    @abstractmethod
    def evaluate(
        self,
        candles: List[Dict[str, Any]],
        symbol: str,
        resolution: str = "1h",
    ) -> StrategySignal:
        """
        Evaluate market candles and produce a structured StrategySignal.
        Must operate exclusively on completed candles.
        """
        pass

    def get_latest_signal(self, symbol: str) -> Optional[StrategySignal]:
        """Retrieve the most recently generated signal for a symbol."""
        return self._latest_signals.get(symbol.upper())

    def get_all_latest_signals(self) -> Dict[str, StrategySignal]:
        """Retrieve all cached latest signals across symbols."""
        return dict(self._latest_signals)
