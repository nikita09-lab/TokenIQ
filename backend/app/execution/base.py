from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseExecutionEngine(ABC):
    """
    Abstract Order Execution Engine for TokenIQ.
    NOTE: Execution engine is strictly inactive / read-only in this market-data phase.
    """

    def __init__(self, mode: str = "read_only"):
        self.mode = mode
        self.is_active: bool = False

    @abstractmethod
    async def place_order(self, order_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Submit order to exchange."""
        raise NotImplementedError("Live order placement is disabled in read-only phase.")

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        raise NotImplementedError("Order cancellation is disabled in read-only phase.")

    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Retrieve current open positions."""
        return []
