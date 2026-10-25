import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.automation.models import PositionLifecycleState, PositionStateRecord, AutomationConfig, AutomationState
from app.automation.position_manager import PositionManager
from app.automation.worker import AutomatedTradingWorker
from app.exchanges.delta_client import DeltaExchangeClient
from app.risk.models import RiskConfig, SafetyState, TradingStatus
from app.risk.service import RiskManagementService, risk_service
from app.trading.models import OrderExecutionRecord, OrderState
from app.trading.service import order_execution_service
from app.trading.store import execution_store
from app.trading.gateway import delta_testnet_gateway


# ============================================================================
# 1. Delta Client Request Schema & Parameter Validation
# ============================================================================
@pytest.mark.asyncio
async def test_get_positions_passes_product_id_and_normalizes_dict():
    """Verify get_positions(product_id=84) passes product_id and normalizes single dict."""
    client = DeltaExchangeClient(api_key="dummy_key", api_secret="dummy_secret")

    with patch.object(client, "_get_authenticated", new_callable=AsyncMock) as mock_auth:
        mock_auth.return_value = {
            "success": True,
            "result": {"size": 0, "entry_price": None, "product_id": 84},
        }

        # Size == 0 should normalize to empty list
        res_zero = await client.get_positions(product_id=84)
        assert res_zero == []
        mock_auth.assert_called_with("/v2/positions/margined", params={"product_id": 84})

        # Size > 0 should normalize to list with position
        mock_auth.return_value = {
            "success": True,
            "result": {"size": 2, "entry_price": 85000.0, "product_id": 84},
        }
        res_active = await client.get_positions(product_id=84)
        assert len(res_active) == 1
        assert res_active[0]["size"] == 2
        assert res_active[0]["product_id"] == 84


@pytest.mark.asyncio
async def test_get_positions_passes_underlying_asset_symbol():
    """Verify get_positions(underlying_asset_symbol='BTC') passes query parameter."""
    client = DeltaExchangeClient(api_key="dummy_key", api_secret="dummy_secret")

    with patch.object(client, "_get_authenticated", new_callable=AsyncMock) as mock_auth:
        mock_auth.return_value = {
            "success": True,
            "result": [{"product_id": 84, "size": 1, "symbol": "BTCUSD"}],
        }

        res = await client.get_positions(underlying_asset_symbol="BTC")
        assert len(res) == 1
        assert res[0]["symbol"] == "BTCUSD"
        mock_auth.assert_called_with(
            "/v2/positions/margined", params={"underlying_asset_symbol": "BTC"}
        )


@pytest.mark.asyncio
async def test_get_positions_without_params_never_calls_unfiltered_positions():
    """
    CRITICAL SCHEMA REGRESSION: Calling /v2/positions without product_id or
    underlying_asset_symbol results in Delta API HTTP 400 bad_schema.
    Verify get_positions() with no parameters raises when /v2/positions/margined fails
    and NEVER falls back to /v2/positions without parameters.
    """
    client = DeltaExchangeClient(api_key="dummy_key", api_secret="dummy_secret")

    with patch.object(client, "_get_authenticated", new_callable=AsyncMock) as mock_auth:
        mock_auth.side_effect = RuntimeError("Margined call timeout")

        with pytest.raises(RuntimeError, match="Margined call timeout"):
            await client.get_positions()

        # Must have only called /v2/positions/margined, never /v2/positions
        assert mock_auth.call_count == 1
        call_endpoint = mock_auth.call_args[0][0]
        assert call_endpoint == "/v2/positions/margined"


# ============================================================================
# 2. Clock Drift & Signature Expiry Self-Healing
# ============================================================================
@pytest.mark.asyncio
async def test_server_time_offset_synchronization_on_expired_signature():
    """
    Delta Testnet enforces a strict 5s signature validity window.
    When expired_signature (HTTP 401) is returned with server_time in context,
    the client must calibrate _server_time_offset and retry once.
    """
    client = DeltaExchangeClient(api_key="dummy_key", api_secret="dummy_secret")
    client._server_time_offset = 0

    now = int(time.time())
    delta_server_time = now + 12  # Exchange clock is 12s ahead

    # Simulate 401 expired_signature on first call, 200 on retry
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_resp_401.text = '{"error":{"code":"expired_signature","context":{"server_time":' + str(delta_server_time) + '}}}'
    mock_resp_401.json.return_value = {
        "error": {
            "code": "expired_signature",
            "context": {"server_time": delta_server_time},
        }
    }

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"success": True, "result": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_http:
        mock_http.side_effect = [mock_resp_401, mock_resp_200]

        data = await client._get_authenticated("/v2/positions/margined")
        assert data["success"] is True
        assert mock_http.call_count == 2
        # Offset should be calibrated to delta_server_time - local_time (~12s)
        assert abs(client._server_time_offset - 12) <= 1


# ============================================================================
# 3. Position Reconciliation: ENTRY_PENDING & Safety Verification
# ============================================================================
@pytest.mark.asyncio
async def test_reconcile_with_exchange_resolves_entry_pending_to_flat_when_order_rejected(tmp_path):
    """
    When local state is ENTRY_PENDING but exchange reports flat position and
    reconciled entry order is REJECTED/not found, position lifecycle must resolve to FLAT.
    """
    pm = PositionManager(data_file=tmp_path / "test_pos.json")
    symbol = "BTCUSD"

    # Pre-load ENTRY_PENDING position
    record = PositionStateRecord(
        symbol=symbol,
        product_id=1,
        lifecycle_state=PositionLifecycleState.ENTRY_PENDING,
        entry_client_order_id="tokiq_auto_test_rej_1",
        quantity=0.0,
    )
    pm._positions[symbol] = record

    mock_products = [{"id": 84, "symbol": "BTCUSD", "underlying_asset": {"symbol": "BTC"}}]
    mock_positions = []  # Exchange has no active position
    mock_open_orders = []

    mock_reconciled_order = OrderExecutionRecord(
        preview_id="prev_1",
        client_order_id="tokiq_auto_test_rej_1",
        symbol=symbol,
        product_id=84,
        side="BUY",
        order_type="market_order",
        size=1.0,
        unfilled_size=1.0,
        notional_usd=80.0,
        state=OrderState.REJECTED.value,
        error_message="Reconciliation conclusive: Order not found on Delta Exchange Testnet.",
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    with patch("app.risk.service.risk_service._get_fresh_products", new_callable=AsyncMock) as mock_fp, \
         patch("app.automation.position_manager.delta_client.get_positions", new_callable=AsyncMock) as mock_gp, \
         patch("app.automation.position_manager.delta_client.get_open_orders", new_callable=AsyncMock) as mock_goo, \
         patch("app.trading.service.order_execution_service.reconcile_order", new_callable=AsyncMock) as mock_ro:

        mock_fp.return_value = mock_products
        mock_gp.return_value = mock_positions
        mock_goo.return_value = mock_open_orders
        mock_ro.return_value = mock_reconciled_order

        pos = await pm.reconcile_with_exchange(symbol)

        assert pos.lifecycle_state == PositionLifecycleState.FLAT
        assert pos.product_id == 84  # Updated from outdated 1 to authoritative 84
        assert pos.quantity == 0.0
        assert pos.entry_client_order_id is None
        assert pos.protection_verified is False


@pytest.mark.asyncio
async def test_reconcile_with_exchange_preserves_entry_pending_on_exchange_error(tmp_path):
    """
    If exchange communication fails during reconciliation, ENTRY_PENDING
    state must be preserved. Never guess or prematurely set FLAT.
    """
    pm = PositionManager(data_file=tmp_path / "test_pos.json")
    symbol = "BTCUSD"

    record = PositionStateRecord(
        symbol=symbol,
        product_id=84,
        lifecycle_state=PositionLifecycleState.ENTRY_PENDING,
        entry_client_order_id="tokiq_auto_test_err_1",
        quantity=0.0,
    )
    pm._positions[symbol] = record

    mock_products = [{"id": 84, "symbol": "BTCUSD", "underlying_asset": {"symbol": "BTC"}}]

    with patch("app.risk.service.risk_service._get_fresh_products", new_callable=AsyncMock) as mock_fp, \
         patch("app.automation.position_manager.delta_client.get_positions", new_callable=AsyncMock) as mock_gp:

        mock_fp.return_value = mock_products
        mock_gp.side_effect = RuntimeError("Exchange connection error: timeout")

        with pytest.raises(RuntimeError, match="Cannot reconcile positions"):
            await pm.reconcile_with_exchange(symbol)

        # State in position manager must remain strictly ENTRY_PENDING
        stored_pos = await pm.get_position(symbol)
        assert stored_pos.lifecycle_state == PositionLifecycleState.ENTRY_PENDING
        assert stored_pos.entry_client_order_id == "tokiq_auto_test_err_1"


@pytest.mark.asyncio
async def test_reconcile_with_exchange_preserves_entry_pending_when_order_open(tmp_path):
    """
    If position size is 0 on exchange but entry order is verified OPEN on exchange,
    position lifecycle state must remain ENTRY_PENDING.
    """
    pm = PositionManager(data_file=tmp_path / "test_pos.json")
    symbol = "BTCUSD"

    record = PositionStateRecord(
        symbol=symbol,
        product_id=84,
        lifecycle_state=PositionLifecycleState.ENTRY_PENDING,
        entry_client_order_id="tokiq_auto_test_open_1",
        quantity=0.0,
    )
    pm._positions[symbol] = record

    mock_products = [{"id": 84, "symbol": "BTCUSD", "underlying_asset": {"symbol": "BTC"}}]
    mock_positions = []
    mock_open_orders = []

    mock_reconciled_order = OrderExecutionRecord(
        preview_id="prev_2",
        client_order_id="tokiq_auto_test_open_1",
        order_id="998877",
        symbol=symbol,
        product_id=84,
        side="BUY",
        order_type="market_order",
        size=1.0,
        unfilled_size=1.0,
        notional_usd=80.0,
        state=OrderState.OPEN.value,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    with patch("app.risk.service.risk_service._get_fresh_products", new_callable=AsyncMock) as mock_fp, \
         patch("app.automation.position_manager.delta_client.get_positions", new_callable=AsyncMock) as mock_gp, \
         patch("app.automation.position_manager.delta_client.get_open_orders", new_callable=AsyncMock) as mock_goo, \
         patch("app.trading.service.order_execution_service.reconcile_order", new_callable=AsyncMock) as mock_ro:

        mock_fp.return_value = mock_products
        mock_gp.return_value = mock_positions
        mock_goo.return_value = mock_open_orders
        mock_ro.return_value = mock_reconciled_order

        pos = await pm.reconcile_with_exchange(symbol)

        assert pos.lifecycle_state == PositionLifecycleState.ENTRY_PENDING
        assert pos.entry_client_order_id == "tokiq_auto_test_open_1"


@pytest.mark.asyncio
async def test_protection_verification_against_actual_exchange_state(tmp_path):
    """
    Requirement 7: Stop-loss and take-profit protection must be verified against
    the actual exchange state before considering any position protected.
    """
    pm = PositionManager(data_file=tmp_path / "test_pos.json")
    symbol = "BTCUSD"

    mock_products = [{"id": 84, "symbol": "BTCUSD", "underlying_asset": {"symbol": "BTC"}}]
    mock_positions = [{"product_id": 84, "symbol": "BTCUSD", "size": 1.0, "entry_price": 84000.0}]

    with patch("app.risk.service.risk_service._get_fresh_products", new_callable=AsyncMock) as mock_fp, \
         patch("app.automation.position_manager.delta_client.get_positions", new_callable=AsyncMock) as mock_gp, \
         patch("app.automation.position_manager.delta_client.get_open_orders", new_callable=AsyncMock) as mock_goo:

        mock_fp.return_value = mock_products
        mock_gp.return_value = mock_positions

        # Case A: No open stop-loss order on exchange -> protection_verified must be FALSE
        mock_goo.return_value = []
        pos_unprotected = await pm.reconcile_with_exchange(symbol)
        assert pos_unprotected.lifecycle_state == PositionLifecycleState.OPEN
        assert pos_unprotected.quantity == 1.0
        assert pos_unprotected.protection_verified is False

        # Case B: Open stop-loss order exists on exchange for product 84 -> protection_verified is TRUE
        mock_goo.return_value = [
            {
                "id": 112233,
                "product_id": 84,
                "order_type": "stop_market_order",
                "stop_order_type": "stop_loss",
                "stop_price": 82000.0,
            }
        ]
        pos_protected = await pm.reconcile_with_exchange(symbol)
        assert pos_protected.protection_verified is True


# ============================================================================
# 4. Dry-Run Mode & Execution Policy Consistency
# ============================================================================
@pytest.mark.asyncio
async def test_dry_run_mode_consistency_with_trading_enabled():
    """
    Verify that dry_run_mode is dynamic and consistent:
    - trading_enabled == False -> dry_run_mode: True
    - trading_enabled == True  -> dry_run_mode: False (authorized testnet)
    """
    service = RiskManagementService()

    with patch("app.exchanges.delta_client.delta_client.get_account_overview", new_callable=AsyncMock) as mock_ao:
        mock_ao.return_value = {"positions": []}

        # 1. Trading disabled
        service.engine.state.trading_enabled = False
        status_disabled = await service.get_trading_status()
        assert status_disabled.trading_enabled is False
        assert status_disabled.dry_run_mode is True
        assert "Dry-run simulation mode active" in status_disabled.disclaimer

        # 2. Trading enabled
        service.engine.state.trading_enabled = True
        status_enabled = await service.get_trading_status()
        assert status_enabled.trading_enabled is True
        assert status_enabled.dry_run_mode is False
        assert "Authorized Testnet execution active" in status_enabled.disclaimer


# ============================================================================
# 5. Order Reconciliation, Confirmed Absence & Connectivity Errors
# ============================================================================
@pytest.mark.asyncio
async def test_reconcile_order_confirmed_not_found_on_exchange(tmp_path):
    """
    Regression: When Delta Exchange returns order_not_found (_not_found_on_exchange=True),
    the order record is marked REJECTED with exchange_state='not_found'.
    The historical execution record is PRESERVED, not deleted.
    """
    now = int(time.time())
    order = OrderExecutionRecord(
        preview_id="prev_test_not_found",
        client_order_id="tokiq_test_not_found_1",
        order_id="55443322",
        symbol="BTCUSD",
        product_id=84,
        side="BUY",
        order_type="limit_order",
        size=1.0,
        unfilled_size=1.0,
        limit_price=80000.0,
        state=OrderState.OPEN.value,
        notional_usd=80.0,
        created_at=now,
        updated_at=now,
    )
    await execution_store.save_order(order)

    with patch.object(delta_testnet_gateway, "list_open_orders", new_callable=AsyncMock) as mock_list, \
         patch.object(delta_testnet_gateway, "get_order_by_id", new_callable=AsyncMock) as mock_get:
        mock_list.return_value = []
        mock_get.return_value = {"_not_found_on_exchange": True}

        reconciled = await order_execution_service.reconcile_order("tokiq_test_not_found_1")

        assert reconciled.state == OrderState.REJECTED.value
        assert reconciled.exchange_state == "not_found"
        assert reconciled.reconciliation_needed is False
        assert "Order not found on Delta Exchange Testnet" in reconciled.error_message

        # Assert record still exists in execution_store (never deleted)
        fetched = await execution_store.get_order_by_client_id("tokiq_test_not_found_1")
        assert fetched is not None
        assert fetched.client_order_id == "tokiq_test_not_found_1"
        assert fetched.state == OrderState.REJECTED.value


@pytest.mark.asyncio
async def test_reconcile_order_exchange_connectivity_error_preserves_unknown(tmp_path):
    """
    Regression: When exchange verification fails due to network/connectivity errors,
    the order is transitioned to explicit UNKNOWN with exchange_state='unverified'.
    Fails closed and never falsely claims OPEN or CLOSED.
    """
    now = int(time.time())
    order = OrderExecutionRecord(
        preview_id="prev_test_conn_err",
        client_order_id="tokiq_test_conn_err_1",
        order_id="99887711",
        symbol="BTCUSD",
        product_id=84,
        side="BUY",
        order_type="limit_order",
        size=1.0,
        unfilled_size=1.0,
        limit_price=80000.0,
        state=OrderState.OPEN.value,
        notional_usd=80.0,
        created_at=now,
        updated_at=now,
    )
    await execution_store.save_order(order)

    with patch.object(delta_testnet_gateway, "list_open_orders", new_callable=AsyncMock) as mock_list:
        mock_list.side_effect = RuntimeError("Delta Exchange API connection refused (HTTP 502)")

        with pytest.raises(RuntimeError) as exc_info:
            await order_execution_service.reconcile_order("tokiq_test_conn_err_1")

        assert "Exchange unreachable" in str(exc_info.value)

        # Verify order transitioned to UNKNOWN and not left as OPEN
        fetched = await execution_store.get_order_by_client_id("tokiq_test_conn_err_1")
        assert fetched is not None
        assert fetched.state == OrderState.UNKNOWN.value
        assert fetched.exchange_state == "unverified"
        assert fetched.reconciliation_needed is True
        assert "blocked by exchange communication error" in fetched.error_message


@pytest.mark.asyncio
async def test_worker_recover_pending_orders_clears_stale_latest_order_status(tmp_path):
    """
    Regression: Worker boot recovery reconciles all unverified local OPEN records.
    When exchange reports them absent, active_orders becomes empty and latest_order_status
    reports None rather than falsely claiming OPEN.
    Also verifies last_reconciliation_at is populated and worker_uptime_seconds is 0 when OFF.
    """
    now = int(time.time())
    stale_order = OrderExecutionRecord(
        preview_id="prev_stale_1",
        client_order_id="tokiq_stale_mock_1",
        order_id="12345",
        symbol="BTCUSD",
        product_id=84,
        side="BUY",
        order_type="market_order",
        size=1.0,
        unfilled_size=1.0,
        state=OrderState.OPEN.value,
        notional_usd=80.0,
        created_at=now - 3600,
        updated_at=now - 3600,
    )
    await execution_store.save_order(stale_order)

    # Before recovery: active orders has 1 order, latest_order_status would be OPEN
    active_before = await execution_store.get_active_orders()
    assert any(o.client_order_id == "tokiq_stale_mock_1" for o in active_before)

    worker = AutomatedTradingWorker()

    with patch.object(delta_testnet_gateway, "list_open_orders", new_callable=AsyncMock) as mock_list, \
         patch.object(delta_testnet_gateway, "get_order_by_id", new_callable=AsyncMock) as mock_get, \
         patch.object(risk_service, "_get_fresh_products", new_callable=AsyncMock) as mock_prod, \
         patch("app.automation.position_manager.delta_client.get_positions", new_callable=AsyncMock) as mock_pos, \
         patch("app.automation.position_manager.delta_client.get_open_orders", new_callable=AsyncMock) as mock_open:

        mock_list.return_value = []
        mock_get.return_value = {"_not_found_on_exchange": True}
        mock_prod.return_value = [{"id": 84, "symbol": "BTCUSD", "underlying_asset": {"symbol": "BTC"}}]
        mock_pos.return_value = []
        mock_open.return_value = []

        await worker.start()

        # After startup recovery: active_orders has 0 orders
        active_after = await execution_store.get_active_orders()
        assert not any(o.client_order_id == "tokiq_stale_mock_1" for o in active_after)

        status = await worker.get_status()
        assert status.latest_order_status is None
        assert status.last_reconciliation_at is not None
        assert status.last_reconciliation_at > 0
        assert status.worker_uptime_seconds == 0
        assert status.state == AutomationState.OFF
        assert status.enabled is False


@pytest.mark.asyncio
async def test_historical_order_counter_preserved_during_reconciliation():
    """
    Regression: Reconciling orders does NOT reset or decrement orders_submitted_today.
    The historical submission counter is strictly preserved.
    """
    initial_count = 15
    risk_service.engine.state.orders_submitted_today = initial_count

    with patch.object(delta_testnet_gateway, "list_open_orders", new_callable=AsyncMock) as mock_list, \
         patch.object(delta_testnet_gateway, "get_order_by_id", new_callable=AsyncMock) as mock_get:
        mock_list.return_value = []
        mock_get.return_value = {"_not_found_on_exchange": True}

        # Save and reconcile a test order
        now = int(time.time())
        order = OrderExecutionRecord(
            preview_id="prev_counter_test",
            client_order_id="tokiq_counter_test_1",
            order_id="55443322",
            symbol="BTCUSD",
            product_id=84,
            side="BUY",
            order_type="limit_order",
            size=1.0,
            unfilled_size=1.0,
            state=OrderState.OPEN.value,
            notional_usd=80.0,
            created_at=now,
            updated_at=now,
        )
        await execution_store.save_order(order)
        await order_execution_service.reconcile_order("tokiq_counter_test_1")

        # The historical order counter must strictly remain unchanged
        assert risk_service.engine.state.orders_submitted_today == initial_count
