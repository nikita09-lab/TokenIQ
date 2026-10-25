import asyncio
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock
import pytest
from fastapi.testclient import TestClient

from app.automation.config import AutomationConfigManager
from app.automation.dedup import SignalDeduplicator
from app.automation.executor import AutomatedOrderExecutor
from app.automation.models import (
    AutomatedSignal,
    AutomationConfig,
    AutomationState,
    PositionLifecycleState,
    PositionSizingMode,
    SignalLifecycleState,
)
from app.automation.position_manager import PositionManager
from app.automation.protection import ProtectionManager, ProtectionPlacementError
from app.automation.sizer import PositionSizer, PositionSizingError
from app.automation.strategy_runner import AutomatedStrategyRunner
from app.automation.worker import AutomatedTradingWorker
from app.core.environment_guard import EnvironmentSafetyViolation
from app.main import app
from app.risk.models import CheckStatus, RiskCheckResult, RiskConfig, RuleEvaluationResult, TradingStatus
from app.trading.gateway import DeltaTestnetOrderGateway, OrderSubmissionTimeoutError, ExchangeOrderRejectedError


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def btc_meta():
    return {
        "id": 1,
        "product_id": 1,
        "symbol": "BTCUSD",
        "contract_value": 0.001,
        "tick_size": 0.1,
    }


# ============================================================================
# 1. Automation Disabled by Default & Safety Boot Invariant
# ============================================================================
def test_automation_disabled_by_default(tmp_path):
    cfg_file = tmp_path / "auto_cfg.json"
    manager = AutomationConfigManager(config_path=cfg_file)
    # When initialized, enabled must strictly be False
    loop = asyncio.new_event_loop()
    try:
        cfg = loop.run_until_complete(manager.get_config())
        assert cfg.enabled is False
    finally:
        loop.close()


def test_automation_restart_never_enables_itself(tmp_path):
    """Even if enabled=True was written to disk, reboot must force enabled=False."""
    cfg_file = tmp_path / "auto_cfg.json"
    with open(cfg_file, "w") as f:
        json.dump({"enabled": True, "trading_symbol": "BTCUSD"}, f)

    manager = AutomationConfigManager(config_path=cfg_file)
    loop = asyncio.new_event_loop()
    try:
        cfg = loop.run_until_complete(manager.get_config())
        assert cfg.enabled is False
    finally:
        loop.close()


# ============================================================================
# 2. Production Endpoint Rejection
# ============================================================================
def test_production_endpoint_rejection():
    gateway = DeltaTestnetOrderGateway()
    with patch.object(DeltaTestnetOrderGateway, "host_url", new_callable=PropertyMock) as mock_host:
        mock_host.return_value = "https://api.delta.exchange"
        with pytest.raises(EnvironmentSafetyViolation) as exc_info:
            gateway._assert_testnet_safe()
        assert "Production host" in str(exc_info.value) or "Security Violation" in str(exc_info.value)


# ============================================================================
# 3. Kill Switch Blocks Automated Submission
# ============================================================================
@pytest.mark.asyncio
async def test_kill_switch_blocks_automated_submission(tmp_path, btc_meta):
    executor = AutomatedOrderExecutor()
    signal = AutomatedSignal(
        signal_id="sig_test_ks_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=int(time.time()),
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Golden cross",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        idempotency_key="hash_ks_1",
    )

    with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg, \
         patch("app.automation.executor.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status:
        mock_cfg.return_value = AutomationConfig(enabled=True)
        # Kill switch is engaged
        mock_status.return_value = TradingStatus(
            trading_enabled=True,
            kill_switch_engaged=True,
            kill_switch_reason="Emergency halt active",
            base_url="https://cdn-ind.testnet.deltaex.org",
            active_risk_limits=RiskConfig(),
            orders_submitted_today=0,
            evaluations_today=0,
            daily_realized_loss_usd=0.0,
            active_positions_count=0,
        )

        res = await executor.execute_signal(signal, btc_meta)
        assert res is None


# ============================================================================
# 4. Signal Deduplication & Idempotency
# ============================================================================
@pytest.mark.asyncio
async def test_signal_deduplication_prevents_duplicate_processing(tmp_path):
    dedup_file = tmp_path / "signals.json"
    dedup = SignalDeduplicator(data_file=dedup_file)

    sig1 = AutomatedSignal(
        signal_id="sig_101",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=1700000000,
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="RSI confirmation",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        idempotency_key="key_abc_123",
    )

    sig2 = AutomatedSignal(
        signal_id="sig_102",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=1700000000,
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="RSI confirmation duplicate",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        idempotency_key="key_abc_123",  # Identical key
    )

    registered1 = await dedup.register_signal(sig1)
    assert registered1 is True

    registered2 = await dedup.register_signal(sig2)
    assert registered2 is False


# ============================================================================
# 5. Stale Signal Rejection
# ============================================================================
@pytest.mark.asyncio
async def test_stale_signal_rejection(btc_meta):
    executor = AutomatedOrderExecutor()
    stale_time = int(time.time()) - 500  # 500s ago (> 300s max)
    signal = AutomatedSignal(
        signal_id="sig_stale_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=stale_time,
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Old signal",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        created_at=stale_time,
        idempotency_key="key_stale_1",
    )

    with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg, \
         patch("app.automation.executor.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status:
        mock_cfg.return_value = AutomationConfig(enabled=True)
        mock_status.return_value = TradingStatus(
            trading_enabled=True,
            kill_switch_engaged=False,
            base_url="https://cdn-ind.testnet.deltaex.org",
            active_risk_limits=RiskConfig(),
            orders_submitted_today=0,
            evaluations_today=0,
            daily_realized_loss_usd=0.0,
            active_positions_count=0,
        )

        res = await executor.execute_signal(signal, btc_meta)
        assert res is None


# ============================================================================
# 6. Position Sizing Arithmetic & Limits
# ============================================================================
def test_position_sizing_fixed_contracts(btc_meta):
    config = AutomationConfig(
        position_sizing_mode=PositionSizingMode.FIXED_CONTRACTS,
        fixed_contract_quantity=2.0,
        maximum_order_notional=500.0,
        maximum_position_size=10.0,
    )
    # 1 BTCUSD contract = 0.001 BTC. At $80,000, 1 contract = $80.
    # 2 contracts = $160 notional.
    qty, notional = PositionSizer.calculate_order_quantity(
        config=config,
        product_meta=btc_meta,
        entry_price=80000.0,
        stop_loss_price=78000.0,
    )
    assert qty == 2.0
    assert notional == 160.0


def test_position_sizing_caps_by_max_notional(btc_meta):
    config = AutomationConfig(
        position_sizing_mode=PositionSizingMode.FIXED_CONTRACTS,
        fixed_contract_quantity=10.0,  # 10 contracts = $800
        maximum_order_notional=250.0,  # Cap at $250 -> max 3 contracts ($240)
        maximum_position_size=20.0,
    )
    qty, notional = PositionSizer.calculate_order_quantity(
        config=config,
        product_meta=btc_meta,
        entry_price=80000.0,
    )
    assert qty == 3.0
    assert notional <= 250.0


def test_position_sizing_rejects_zero_capacity(btc_meta):
    config = AutomationConfig(
        maximum_position_size=5.0,
    )
    with pytest.raises(PositionSizingError):
        PositionSizer.calculate_order_quantity(
            config=config,
            product_meta=btc_meta,
            entry_price=80000.0,
            current_position_size=5.0,  # Already at limit
        )


# ============================================================================
# 7. Cooldown Period Enforcement
# ============================================================================
@pytest.mark.asyncio
async def test_cooldown_period_enforcement(tmp_path):
    pos_file = tmp_path / "pos.json"
    pos_mgr = PositionManager(data_file=pos_file)

    # Transition to FLAT (sets exit time)
    await pos_mgr.update_lifecycle_state("BTCUSD", PositionLifecycleState.FLAT)

    # Checking cooldown with 300s
    in_cooldown, remaining = await pos_mgr.check_cooldown("BTCUSD", 300)
    assert in_cooldown is True
    assert remaining > 0


# ============================================================================
# 8. Timeout Produces UNKNOWN State, Never Blind Retries
# ============================================================================
@pytest.mark.asyncio
async def test_order_submission_timeout_sets_unknown_state(btc_meta):
    executor = AutomatedOrderExecutor()
    signal = AutomatedSignal(
        signal_id="sig_timeout_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=int(time.time()),
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Breakout",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        idempotency_key="key_timeout_1",
    )

    with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg, \
         patch("app.automation.executor.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status, \
         patch("app.automation.executor.risk_service.check_signal_risk", new_callable=AsyncMock) as mock_risk, \
         patch("app.automation.executor.delta_testnet_gateway.submit_order", new_callable=AsyncMock) as mock_submit:

        mock_cfg.return_value = AutomationConfig(enabled=True)
        mock_status.return_value = TradingStatus(
            trading_enabled=True,
            kill_switch_engaged=False,
            base_url="https://cdn-ind.testnet.deltaex.org",
            active_risk_limits=RiskConfig(),
            orders_submitted_today=0,
            evaluations_today=0,
            daily_realized_loss_usd=0.0,
            active_positions_count=0,
        )
        mock_risk.return_value = RiskCheckResult(
            approved=True,
            decision="APPROVED",
            symbol="BTCUSD",
            signal_id=signal.signal_id,
            proposed_notional_usd=80.0,
            evaluated_at=int(time.time()),
            rules_evaluated=[],
            reasons=[],
        )
        # Gateway times out
        mock_submit.side_effect = OrderSubmissionTimeoutError("tokiq_client_1", "Timed out")

        record = await executor.execute_signal(signal, btc_meta)
        assert record is not None
        assert record.state == "UNKNOWN"
        assert record.reconciliation_needed is True


# ============================================================================
# 9. Protective Stop Placement Failure Triggers Emergency Liquidation
# ============================================================================
@pytest.mark.asyncio
async def test_protection_failure_triggers_emergency_close(btc_meta):
    executor = AutomatedOrderExecutor()
    signal = AutomatedSignal(
        signal_id="sig_prot_fail_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=int(time.time()),
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Signal test",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78000.0,
        idempotency_key="key_prot_fail_1",
    )

    with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg, \
         patch("app.automation.executor.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status, \
         patch("app.automation.executor.risk_service.check_signal_risk", new_callable=AsyncMock) as mock_risk, \
         patch("app.automation.executor.delta_testnet_gateway.submit_order", new_callable=AsyncMock) as mock_submit, \
         patch("app.automation.executor.protection_manager.place_protective_stop", new_callable=AsyncMock) as mock_stop, \
         patch("app.automation.executor.protection_manager.execute_emergency_position_close", new_callable=AsyncMock) as mock_emg:

        mock_cfg.return_value = AutomationConfig(enabled=True)
        mock_status.return_value = TradingStatus(
            trading_enabled=True,
            kill_switch_engaged=False,
            base_url="https://cdn-ind.testnet.deltaex.org",
            active_risk_limits=RiskConfig(),
            orders_submitted_today=0,
            evaluations_today=0,
            daily_realized_loss_usd=0.0,
            active_positions_count=0,
        )
        mock_risk.return_value = RiskCheckResult(
            approved=True,
            decision="APPROVED",
            symbol="BTCUSD",
            signal_id=signal.signal_id,
            proposed_notional_usd=80.0,
            evaluated_at=int(time.time()),
            rules_evaluated=[],
            reasons=[],
        )
        mock_submit.return_value = {"id": "12345", "state": "filled", "unfilled_size": 0}
        mock_stop.side_effect = ProtectionPlacementError("Exchange rejected stop loss")
        mock_emg.return_value = {"id": "99999", "state": "filled"}

        # Simulate position manager returning open position
        with patch("app.automation.executor.position_manager.reconcile_with_exchange", new_callable=AsyncMock) as mock_reconcile:
            mock_reconcile.return_value = MagicMock(
                lifecycle_state=PositionLifecycleState.OPEN,
                product_id=1,
                quantity=1.0,
                side="LONG",
            )
            record = await executor.execute_signal(signal, btc_meta)
            assert record is not None
            # Emergency close must have been invoked
            mock_emg.assert_called_once()


# ============================================================================
# 10. Separation of Manual vs Automated Orders
# ============================================================================
@pytest.mark.asyncio
async def test_manual_execution_does_not_enable_automation():
    from app.automation.config import automation_config_manager
    cfg = await automation_config_manager.get_config()
    assert cfg.enabled is False


# ============================================================================
# 11. REST API Endpoints Testing
# ============================================================================
def test_api_automation_status(test_client):
    res = test_client.get("/api/v1/automation/status")
    assert res.status_code == 200
    data = res.json()
    assert data["testnet_enforced"] is True
    assert "disclaimer" in data


def test_api_automation_config_get_and_validate(test_client):
    res = test_client.get("/api/v1/automation/config")
    assert res.status_code == 200
    cfg = res.json()
    assert cfg["enabled"] is False

    # Validate config
    val_res = test_client.post("/api/v1/automation/config/validate", json=cfg)
    assert val_res.status_code == 200
    assert "valid" in val_res.json()


def test_api_automation_enable_requires_explicit_confirm(test_client):
    # Missing explicit confirm
    res = test_client.post("/api/v1/automation/enable", json={"confirm": False})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_api_automation_enable_rejected_with_structured_409_when_unresolved_orders_exist(test_client):
    """Regression Test: Unresolved orders trigger structured HTTP 409 with UNRESOLVED_ORDERS code and guidance."""
    from app.trading.store import execution_store
    from app.trading.models import OrderExecutionRecord, OrderState
    import time

    # Save an order requiring reconciliation in the isolated store
    rec = OrderExecutionRecord(
        preview_id="prev_unres_1",
        client_order_id="tokiq_unres_1",
        symbol="BTCUSD",
        product_id=27,
        side="BUY",
        order_type="limit_order",
        size=1.0,
        unfilled_size=1.0,
        state=OrderState.UNKNOWN.value,
        notional_usd=80.0,
        created_at=int(time.time()),
        updated_at=int(time.time()),
        reconciliation_needed=True,
    )
    await execution_store.save_order(rec)

    with patch("app.automation.worker.delta_client") as mock_delta:
        mock_delta.api_key = "test_key"
        mock_delta.api_secret = "test_secret"
        mock_delta.host_url = "https://cdn-ind.testnet.deltaex.org"

        res = test_client.post("/api/v1/automation/enable", json={"confirm": True})
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["code"] == "UNRESOLVED_ORDERS"
        assert detail["unresolved_order_count"] == 1
        assert "tokiq_unres_1" in detail["client_order_ids"]
        assert "actionable_guidance" in detail
        assert "IP whitelist" in detail["actionable_guidance"]


def test_api_automation_enable_rejected_when_kill_switch_engaged(test_client):
    """Regression Test: Kill switch engaged triggers structured HTTP 409 with ACTIVATION_SAFETY_VIOLATION."""
    with patch("app.automation.worker.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = MagicMock(
            kill_switch_engaged=True,
            kill_switch_reason="Emergency operator trigger",
            trading_enabled=True,
        )
        res = test_client.post("/api/v1/automation/enable", json={"confirm": True})
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["code"] == "ACTIVATION_SAFETY_VIOLATION"
        assert "Kill Switch is ENGAGED" in detail["message"]
        assert "actionable_guidance" in detail



# ============================================================================
# 12. Pyramiding Blocked When Disabled
# ============================================================================
def test_pyramiding_blocked_when_disabled(btc_meta):
    runner = AutomatedStrategyRunner()
    config = AutomationConfig(allow_pyramiding=False, allow_long=True)

    # Mock raw signal as BUY
    raw_sig = MagicMock(
        signal="BUY",
        candle_time=1700000000,
        timestamp=1700000000,
        close=80000.0,
        explanation="Golden cross",
    )
    with patch.object(runner._strategy, "evaluate", return_value=raw_sig):
        # We already have an open long position of 1 contract
        res = runner.evaluate_candles(
            config=config,
            product_meta=btc_meta,
            candles=[{"time": 1, "close": 100}, {"time": 2, "close": 105}],
            current_position_side="LONG",
            current_position_size=1.0,
        )
        # Should be None because pyramiding is disabled
        assert res is None


# ============================================================================
# 13. Strategy Runner Emits Fresh Signal on Completed Candle
# ============================================================================
def test_strategy_runner_emits_fresh_signal(btc_meta):
    runner = AutomatedStrategyRunner()
    config = AutomationConfig(allow_long=True, allow_short=False)

    raw_sig = MagicMock(
        signal="BUY",
        candle_time=1700000500,
        timestamp=1700000500,
        close=82000.0,
        explanation="Golden cross entry",
    )
    with patch.object(runner._strategy, "evaluate", return_value=raw_sig):
        # Flat position
        res = runner.evaluate_candles(
            config=config,
            product_meta=btc_meta,
            candles=[{"time": 1, "close": 100}, {"time": 2, "close": 105}],
            current_position_side=None,
            current_position_size=0.0,
        )
        assert res is not None
        assert res.signal_direction == "BUY"
        assert res.position_intent == "OPEN_LONG"
        assert res.intended_price == 82000.0
        assert res.stop_loss_price is not None
        assert res.stop_loss_price < 82000.0


# ============================================================================
# 14. Worker Pause and Resume Lifecycle
# ============================================================================
@pytest.mark.asyncio
async def test_worker_pause_and_resume():
    worker = AutomatedTradingWorker()
    worker._state = AutomationState.RUNNING

    # Pause
    res = await worker.pause_entries("Manual safety pause")
    assert worker.state == AutomationState.PAUSED
    assert worker.is_paused is True

    # Resume with passing safety checks
    with patch("app.automation.worker.risk_service.get_trading_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = TradingStatus(
            trading_enabled=True,
            kill_switch_engaged=False,
            base_url="https://cdn-ind.testnet.deltaex.org",
            active_risk_limits=RiskConfig(),
            orders_submitted_today=0,
            evaluations_today=0,
            daily_realized_loss_usd=0.0,
            active_positions_count=0,
        )
        await worker.resume_entries()
        assert worker.state == AutomationState.RUNNING
        assert worker.is_paused is False


# ============================================================================
# 15. API Positions and Signals List
# ============================================================================
def test_api_list_signals_and_positions(test_client):
    sig_res = test_client.get("/api/v1/automation/signals")
    assert sig_res.status_code == 200
    assert isinstance(sig_res.json(), list)

    pos_res = test_client.get("/api/v1/automation/positions")
    assert pos_res.status_code == 200
    assert isinstance(pos_res.json(), list)

