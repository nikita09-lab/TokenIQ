import asyncio
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import httpx
import pytest

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
from app.core.environment_guard import EnvironmentSafetyViolation, validate_testnet_host
from app.exchanges.delta_client import DeltaExchangeClient
from app.risk.engine import RiskEngine
from app.risk.models import CheckStatus, RiskCheckRequest, RiskCheckResult, RiskConfig, SafetyState
from app.strategies.base import SignalType
from app.trading.gateway import (
    DeltaTestnetOrderGateway,
    ExchangeOrderRejectedError,
    OrderSubmissionTimeoutError,
)
from app.trading.models import OrderExecutionRecord, OrderState
from app.trading.store import ExecutionStore


@pytest.fixture
def btc_meta():
    return {
        "id": 84,
        "product_id": 84,
        "symbol": "BTCUSD",
        "contract_value": 0.001,
        "tick_size": 0.1,
        "trading_status": "operational",
        "state": "live",
    }


# ============================================================================
# 1. Testnet Endpoint Enforcement & Production Rejection
# ============================================================================
def test_testnet_endpoint_enforcement():
    """Verify that verified Delta Testnet hosts pass, and production endpoints raise EnvironmentSafetyViolation."""
    # Verified Testnet host must pass
    verified = validate_testnet_host("https://cdn-ind.testnet.deltaex.org")
    assert "cdn-ind.testnet.deltaex.org" in verified

    # Production endpoints must fail-closed
    for prod_url in [
        "https://api.delta.exchange",
        "https://api.india.delta.exchange",
        "https://cdn.deltaex.org",
        "wss://socket.india.delta.exchange",
    ]:
        with pytest.raises(EnvironmentSafetyViolation):
            validate_testnet_host(prod_url)


# ============================================================================
# 2. Missing and Invalid Credentials Handling
# ============================================================================
@pytest.mark.asyncio
async def test_missing_and_invalid_credentials():
    """Verify that missing credentials disable order execution and report diagnostic safely without leaking secrets."""
    client = DeltaExchangeClient(base_url="https://cdn-ind.testnet.deltaex.org")
    client.api_key = ""
    client.api_secret = ""

    overview = await client.get_account_overview()
    assert overview["authenticated"] is False
    assert overview["masked_api_key"] == ""
    assert "missing" in overview["diagnostic"].lower()

    # Worker activation must fail closed if credentials missing
    worker = AutomatedTradingWorker()
    with patch("app.automation.worker.delta_client", client):
        with pytest.raises(RuntimeError) as exc_info:
            await worker.enable_automation(explicit_confirm=True)
        assert "credentials missing" in str(exc_info.value).lower()


# ============================================================================
# 3. Wallet Balance Retrieval and Safe Failure Reporting
# ============================================================================
@pytest.mark.asyncio
async def test_wallet_balance_retrieval_and_failure_reporting():
    """Verify wallet balance distinguishes total, available, margins, and reports failures without fabricating balances."""
    client = DeltaExchangeClient(base_url="https://cdn-ind.testnet.deltaex.org")
    client.api_key = "test_key_abc"
    client.api_secret = "test_secret_xyz"

    mock_balances = [
        {
            "asset_id": 3,
            "asset_symbol": "USD",
            "balance": "200.00",
            "available_balance": "195.50",
            "blocked_margin": "4.50",
            "order_margin": "2.00",
            "position_margin": "2.50",
        }
    ]

    with patch.object(client, "get_wallet_balances", AsyncMock(return_value=mock_balances)):
        with patch.object(client, "get_positions", AsyncMock(return_value=[])):
            with patch.object(client, "get_open_orders", AsyncMock(return_value=[])):
                with patch.object(client, "get_order_history", AsyncMock(return_value=[])):
                    overview = await client.get_account_overview(force_refresh=True)
                    assert overview["authenticated"] is True
                    assert overview["total_balance_usd"] == 200.0
                    assert overview["available_balance_usd"] == 195.50
                    assert overview["total_margin_used_usd"] == 4.50
                    assert overview["order_margin_usd"] == 2.00
                    assert overview["position_margin_usd"] == 2.50
                    assert overview["account_currency"] == "USD"
                    assert overview["last_balance_update_timestamp"] is not None

    # Failure case: Exchange returns error
    with patch.object(client, "get_wallet_balances", AsyncMock(side_effect=RuntimeError("Delta API 401: Unauthorized"))):
        overview_fail = await client.get_account_overview(force_refresh=True)
        assert overview_fail["authenticated"] is False
        assert overview_fail["total_balance_usd"] == 0.0
        assert "unauthorized" in (overview_fail["diagnostic"] or "").lower()


# ============================================================================
# 4. Market Data Failures, Stale Candles, and Completed Candle Deduplication
# ============================================================================
def test_completed_candle_deduplication_and_stale_rejection(btc_meta):
    """Verify that strategy runner only processes fresh completed candles and ignores duplicates."""
    runner = AutomatedStrategyRunner()
    config = AutomationConfig(
        selected_strategy="ema_crossover",
        trading_symbol="BTCUSD",
        candle_interval="1h",
        require_confirmed_candle=True,
    )

    t0 = 1700000000
    candles = [
        {"time": t0, "open": 80000, "high": 80500, "low": 79800, "close": 80200, "volume": 10},
        {"time": t0 + 3600, "open": 80200, "high": 80800, "low": 80100, "close": 80600, "volume": 15},
    ]

    # Mock raw strategy returning a signal on the completed candle
    mock_raw = MagicMock()
    mock_raw.candle_time = t0 + 3600
    mock_raw.timestamp = t0 + 3600
    mock_raw.close = 80600
    mock_raw.signal = SignalType.BUY
    mock_raw.signal_type.value = "BUY"
    mock_raw.explanation = "EMA 9 crossed above EMA 21"

    with patch.object(runner._strategy, "evaluate", return_value=mock_raw):
        # First evaluation produces signal
        sig1 = runner.evaluate_candles(
            config=config,
            product_meta=btc_meta,
            candles=candles,
            available_margin_usd=200.0,
        )
        assert sig1 is not None

        # Immediate re-evaluation of same completed candle returns None
        sig2 = runner.evaluate_candles(
            config=config,
            product_meta=btc_meta,
            candles=candles,
            available_margin_usd=200.0,
        )
        assert sig2 is None


# ============================================================================
# 5. Duplicate Signal Prevention (Idempotency Key & Mutex)
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_signal_prevention(tmp_path):
    """Verify that identical signals cannot be registered twice in deduplicator."""
    dedup = SignalDeduplicator(data_file=tmp_path / "signals.json")
    signal = AutomatedSignal(
        signal_id="sig_test_dedup_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=1700000000,
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="EMA cross",
        intended_price=80000.0,
        intended_quantity=1.0,
        idempotency_key="idemp_key_hash_12345",
    )

    # First registration passes
    reg1 = await dedup.register_signal(signal)
    assert reg1 is True

    # Duplicate registration fails
    reg2 = await dedup.register_signal(signal)
    assert reg2 is False


# ============================================================================
# 6. Insufficient Balance & Margin Rejection (Rule 11)
# ============================================================================
@pytest.mark.asyncio
async def test_insufficient_balance_and_margin_rejection(btc_meta):
    """Verify Rule 11: entry orders fail when available margin is zero or insufficient."""
    engine = RiskEngine()
    engine.config = RiskConfig()
    engine.state.trading_enabled = True
    engine.state.kill_switch_engaged = False

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        position_intent="OPEN_LONG",
        quantity=1.0,
        price=80000.0,
        stop_loss=78800.0,
        signal_id="sig_margin_test",
        timestamp=int(time.time()),
    )

    # 1. Zero available balance
    res_zero = await engine.evaluate_risk(
        request=req,
        account_telemetry={"available_balance_usd": 0.0, "positions": []},
        products_metadata=[btc_meta],
    )
    assert res_zero.approved is False
    assert any("insufficient funds" in r.lower() for r in res_zero.reasons)

    # 2. Balance less than 10% notional margin buffer ($80 notional -> $8 required)
    res_insuf = await engine.evaluate_risk(
        request=req,
        account_telemetry={"available_balance_usd": 5.0, "positions": []},
        products_metadata=[btc_meta],
    )
    assert res_insuf.approved is False
    assert any("insufficient available margin" in r.lower() for r in res_insuf.reasons)


# ============================================================================
# 7. Conservative Notional ($20) vs BTCUSD Contract Sizing ($80.24) Rejection
# ============================================================================
def test_maximum_notional_rejection_at_conservative_limits(btc_meta):
    """
    Verify that with proposed initial conservative limit ($20.00 max notional),
    1 BTCUSD contract (~$80.24) is rejected by PositionSizer as exceeding limit,
    and strategy runner creates a REJECTED signal with the clear explanation.
    """
    config = AutomationConfig(
        selected_strategy="ema_crossover",
        trading_symbol="BTCUSD",
        candle_interval="1h",
        maximum_order_notional=20.0,  # Proposed $20 limit
        maximum_position_size=1.0,
    )

    # Direct Sizer calculation must raise PositionSizingError
    with pytest.raises(PositionSizingError) as exc_info:
        PositionSizer.calculate_order_quantity(
            config=config,
            product_meta=btc_meta,
            entry_price=80240.0,
            stop_loss_price=79036.0,
            available_margin_usd=200.0,
        )
    assert "exceed max limit of $20.00" in str(exc_info.value)

    # Strategy runner converts this into a REJECTED AutomatedSignal
    runner = AutomatedStrategyRunner()
    candles = [
        {"time": 1700000000, "open": 80000, "high": 80500, "low": 79800, "close": 80200, "volume": 10},
        {"time": 1700003600, "open": 80200, "high": 80800, "low": 80100, "close": 80240, "volume": 15},
    ]
    mock_raw = MagicMock()
    mock_raw.candle_time = 1700003600
    mock_raw.timestamp = 1700003600
    mock_raw.close = 80240.0
    mock_raw.signal = SignalType.BUY
    mock_raw.signal_type.value = "BUY"
    mock_raw.explanation = "EMA cross entry"

    with patch.object(runner._strategy, "evaluate", return_value=mock_raw):
        sig = runner.evaluate_candles(
            config=config,
            product_meta=btc_meta,
            candles=candles,
            available_margin_usd=200.0,
        )
        assert sig is not None
        assert sig.lifecycle_state == SignalLifecycleState.REJECTED
        assert "exceed max limit of $20.00" in (sig.rejection_reason or "")


# ============================================================================
# 8. Daily Realized Loss Limit Enforcement ($4.00 Cap)
# ============================================================================
@pytest.mark.asyncio
async def test_daily_loss_limit_enforcement(btc_meta):
    """Verify that when daily realized loss reaches the $4.00 cap, orders are blocked."""
    engine = RiskEngine()
    engine.config = RiskConfig(max_daily_realized_loss_usd=4.0)
    engine.state.trading_enabled = True
    engine.state.kill_switch_engaged = False

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        position_intent="OPEN_LONG",
        quantity=1.0,
        price=80000.0,
        stop_loss=78800.0,
        signal_id="sig_daily_loss_test",
        timestamp=int(time.time()),
    )

    # Realized loss = -$4.50 (exceeds $4.00 cap)
    account_with_loss = {
        "available_balance_usd": 195.50,
        "positions": [
            {"symbol": "BTCUSD", "size": 0, "realized_pnl": -4.50}
        ],
    }

    res = await engine.evaluate_risk(
        request=req,
        account_telemetry=account_with_loss,
        products_metadata=[btc_meta],
    )
    assert res.approved is False
    assert any("daily realized loss" in r.lower() for r in res.reasons)


# ============================================================================
# 9. Order Submission Timeout & Safe Recovery (No Duplicate Orders)
# ============================================================================
@pytest.mark.asyncio
async def test_order_submission_timeout_safe_recovery(btc_meta, tmp_path):
    """Verify that HTTP timeout transitions order to UNKNOWN for reconciliation, never duplicate retry."""
    executor = AutomatedOrderExecutor()
    store = ExecutionStore(data_file=tmp_path / "orders.json")

    signal = AutomatedSignal(
        signal_id="sig_timeout_1",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=int(time.time()),
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Test timeout",
        intended_price=80000.0,
        intended_quantity=1.0,
        stop_loss_price=78800.0,
        idempotency_key="idemp_timeout_1",
    )

    mock_safety = MagicMock()
    mock_safety.kill_switch_engaged = False
    mock_safety.trading_enabled = True

    mock_risk = MagicMock()
    mock_risk.approved = True

    with patch("app.automation.executor.execution_store", store):
        with patch("app.automation.executor.automation_config_manager.get_config", AsyncMock(return_value=AutomationConfig(enabled=True))):
            with patch("app.automation.executor.risk_service.get_trading_status", AsyncMock(return_value=mock_safety)):
                with patch("app.automation.executor.risk_service.check_signal_risk", AsyncMock(return_value=mock_risk)):
                    with patch("app.automation.executor.delta_testnet_gateway.submit_order", AsyncMock(side_effect=OrderSubmissionTimeoutError("tokiq_timeout_order_1", "Request timed out"))):
                        record = await executor.execute_signal(signal, btc_meta)
                        assert record is not None
                        assert record.state == OrderState.UNKNOWN.value
                        assert record.reconciliation_needed is True

                        # Inspect store: Order must be persisted as UNKNOWN
                        saved = await store.get_order_by_client_id(record.client_order_id)
                        assert saved is not None
                        assert saved.state == OrderState.UNKNOWN.value


# ============================================================================
# 10. Protective Stop-Loss Verification and Mandatory Attachment
# ============================================================================
@pytest.mark.asyncio
async def test_protective_stop_loss_verification():
    """Verify that positions require confirmed exchange-side stop loss."""
    prot_mgr = ProtectionManager()

    # If stop-loss placement fails, ProtectionPlacementError is raised
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": {"code": "invalid_order"}}
    mock_resp.text = '{"error": {"code": "invalid_order"}}'

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)):
        with patch("app.automation.protection.delta_client.api_key", "test_key"):
            with patch("app.automation.protection.delta_client.api_secret", "test_secret"):
                with pytest.raises(ProtectionPlacementError):
                    await prot_mgr.place_protective_stop(
                        product_id=84,
                        symbol="BTCUSD",
                        position_side="LONG",
                        quantity=1.0,
                        stop_price=78800.0,
                    )


# ============================================================================
# 11. Kill-Switch Behavior Halts Trading Immediately
# ============================================================================
@pytest.mark.asyncio
async def test_kill_switch_halts_automation():
    """Verify that an active kill switch prevents order execution."""
    executor = AutomatedOrderExecutor()
    signal = AutomatedSignal(
        signal_id="sig_ks_halt",
        strategy_id="ema_crossover",
        symbol="BTCUSD",
        timeframe="1h",
        candle_timestamp=int(time.time()),
        signal_direction="BUY",
        position_intent="OPEN_LONG",
        entry_rationale="Test KS halt",
        intended_price=80000.0,
        intended_quantity=1.0,
        idempotency_key="idemp_ks_halt",
    )

    mock_safety = MagicMock()
    mock_safety.kill_switch_engaged = True
    mock_safety.kill_switch_reason = "Manual emergency stop engaged"

    with patch("app.automation.executor.risk_service.get_trading_status", AsyncMock(return_value=mock_safety)):
        with patch("app.automation.executor.automation_config_manager.get_config", AsyncMock(return_value=AutomationConfig(enabled=True))):
            rec = await executor.execute_signal(signal, {"id": 84, "product_id": 84, "symbol": "BTCUSD", "contract_value": 0.001, "tick_size": 0.1})
            assert rec is None


# ============================================================================
# 12. Automation Starts Strictly OFF and Survives Reboot Safely
# ============================================================================
@pytest.mark.asyncio
async def test_automation_starts_strictly_off_on_boot():
    """Verify that AutomatedTradingWorker starts in OFF state on application boot."""
    worker = AutomatedTradingWorker()
    await worker.start()
    assert worker.state == AutomationState.OFF
    assert worker.is_paused is False

    status = await worker.get_status()
    assert status.state == AutomationState.OFF
    assert status.enabled is False
    assert status.testnet_enforced is True
    assert status.active_position.lifecycle_state == PositionLifecycleState.FLAT
