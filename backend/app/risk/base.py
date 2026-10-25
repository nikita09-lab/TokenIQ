from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseRiskManager(ABC):
    """
    Abstract Risk Management Interface for TokenIQ.
    NOTE: Risk validation is inactive in this market-data phase.
    """

    def __init__(self, max_drawdown_pct: float = 5.0, max_leverage: int = 20):
        self.max_drawdown_pct = max_drawdown_pct
        self.max_leverage = max_leverage
        self.is_active: bool = False

    @abstractmethod
    def validate_order(self, order_payload: Dict[str, Any]) -> bool:
        """Validate an order against exposure and balance limits before submission."""
        return False

    @abstractmethod
    def check_position_limits(self, symbol: str, size: float) -> bool:
        """Verify that proposed position does not exceed symbol limits."""
        return False
