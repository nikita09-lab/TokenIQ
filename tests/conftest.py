import os
import sys
from pathlib import Path
import pytest

# Add backend directory to sys.path so app imports resolve everywhere across runners
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# pyrefly: ignore[missing-import]
from app.trading.store import execution_store
# pyrefly: ignore[missing-import]
from app.automation.position_manager import position_manager
# pyrefly: ignore[missing-import]
from app.automation.config import automation_config_manager
# pyrefly: ignore[missing-import]
from app.automation.dedup import signal_deduplicator
# pyrefly: ignore[missing-import]
from app.risk.engine import risk_engine


@pytest.fixture(autouse=True)
def isolate_runtime_storage(tmp_path):
    """
    Ensure all test runs use isolated temporary storage through pytest tmp_path.
    Guarantees that test execution never writes synthetic or mock orders, positions,
    configs, or safety states to real runtime files in backend/app/.
    """
    # 1. Isolate ExecutionStore
    real_exec_file = execution_store.data_file
    real_orders = dict(execution_store._orders)
    real_previews = dict(execution_store._previews)
    real_consumed = dict(execution_store._consumed_previews)

    test_exec_file = tmp_path / "test_execution_records.json"
    execution_store.data_file = test_exec_file
    execution_store._orders = {}
    execution_store._previews = {}
    execution_store._consumed_previews = {}

    # 2. Isolate PositionManager
    real_pos_file = position_manager.data_file
    real_positions = dict(position_manager._positions)
    real_exit_times = dict(position_manager._last_exit_times)

    test_pos_file = tmp_path / "test_positions.json"
    position_manager.data_file = test_pos_file
    position_manager._positions = {}
    position_manager._last_exit_times = {}

    # 3. Isolate SignalDeduplicator
    real_dedup_file = signal_deduplicator.data_file
    real_signals = dict(signal_deduplicator._signals)

    test_dedup_file = tmp_path / "test_signals.json"
    signal_deduplicator.data_file = test_dedup_file
    signal_deduplicator._signals = {}

    # 4. Isolate AutomationConfigManager
    real_config_path = automation_config_manager.config_path
    real_config = automation_config_manager._config.model_copy()

    test_cfg_path = tmp_path / "test_automation_config.json"
    automation_config_manager.config_path = test_cfg_path
    automation_config_manager._config = real_config.model_copy()

    # 5. Isolate RiskEngine safety state & risk config
    real_risk_state_file = risk_engine.state_file
    real_risk_state = risk_engine.state.model_copy()
    real_risk_config_file = risk_engine.config_file
    real_risk_config = risk_engine.config.model_copy()

    test_risk_state_file = tmp_path / "test_safety_state.json"
    test_risk_config_file = tmp_path / "test_risk_config.json"
    risk_engine.state_file = test_risk_state_file
    risk_engine.state = real_risk_state.model_copy()
    risk_engine.config_file = test_risk_config_file
    risk_engine.config = real_risk_config.model_copy()

    yield

    # Restore runtime data files and in-memory caches
    execution_store.data_file = real_exec_file
    execution_store._orders = real_orders
    execution_store._previews = real_previews
    execution_store._consumed_previews = real_consumed

    position_manager.data_file = real_pos_file
    position_manager._positions = real_positions
    position_manager._last_exit_times = real_exit_times

    signal_deduplicator.data_file = real_dedup_file
    signal_deduplicator._signals = real_signals

    automation_config_manager.config_path = real_config_path
    automation_config_manager._config = real_config

    risk_engine.state_file = real_risk_state_file
    risk_engine.state = real_risk_state
    risk_engine.config_file = real_risk_config_file
    risk_engine.config = real_risk_config
