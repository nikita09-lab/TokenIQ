"""
TokenIQ Automated Trading Package
Testnet-only quantitative execution engine.
"""

from app.automation.config import automation_config_manager
from app.automation.dedup import signal_deduplicator
from app.automation.executor import automated_order_executor
from app.automation.models import (
    AutomationConfig,
    AutomationState,
    AutomationStatusResponse,
    AutomatedSignal,
    PositionLifecycleState,
    PositionSizingMode,
    PositionStateRecord,
    SignalLifecycleState,
)
from app.automation.position_manager import position_manager
from app.automation.protection import protection_manager
from app.automation.sizer import position_sizer
from app.automation.strategy_runner import strategy_runner
from app.automation.worker import automated_trading_worker

__all__ = [
    "automation_config_manager",
    "signal_deduplicator",
    "automated_order_executor",
    "automated_trading_worker",
    "position_manager",
    "protection_manager",
    "position_sizer",
    "strategy_runner",
    "AutomationConfig",
    "AutomationState",
    "AutomationStatusResponse",
    "AutomatedSignal",
    "PositionLifecycleState",
    "PositionSizingMode",
    "PositionStateRecord",
    "SignalLifecycleState",
]
