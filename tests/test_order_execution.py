import asyncio
import time
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# pyrefly: ignore[missing-import]
from app.main import app
# pyrefly: ignore[missing-import]
from app.core.environment_guard import (
    validate_testnet_host,
    EnvironmentSafetyViolation,
    VERIFIED_TESTNET_HOSTS,
)
# pyrefly: ignore[missing-import]
from app.exchanges.delta_client import delta_client
# pyrefly: ignore[missing-import]
from app.risk.service import risk_service
# pyrefly: ignore[missing-import]
from app.trading.gateway import (
    delta_testnet_gateway,
    ExchangeOrderRejectedError,
    OrderSubmissionTimeoutError,
)
# pyrefly: ignore[missing-import]
from app.trading.models import (
    OrderConfirmRequest,
    OrderExecutionRecord,
    OrderPreviewRequest,
    OrderState,
)
# pyrefly: ignore[missing-import]
from app.trading.service import order_execution_service
# pyrefly: ignore[missing-import]
from app.trading.store import execution_store

client = TestClient(app)

SAMPLE_PRODUCTS = [
    {
        "id": 27,
        "symbol": "BTCUSD",
        "tick_size": "0.1",
        "contract_value": "0.001",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
        "position_size_limit": 5000,
    },
    {
        "id": 28,
        "symbol": "ETHUSD",
        "tick_size": "0.05",
        "contract_value": "0.01",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
        "position_size_limit": 4000,
    },
    {
        "id": 29,
        "symbol": "SOLUSD",
        "tick_size": "0.0001",
        "contract_value": "1.0",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
        "position_size_limit": 550,
    },
]

SAMPLE_ACCOUNT_OK = {
    "authenticated": True,
    "positions": [
        {
            "product_id": 27,
            "symbol": "BTCUSD",
            "size": 0.0,
            "realized_pnl": 0.0,
        }
    ],
    "balances": [{"asset_symbol": "USDT", "balance": 10000.0, "available_balance": 8000.0}],
    "orders": [],
}


# Setup fixture to reset kill switch and mock telemetry for deterministic tests
@pytest.fixture(autouse=True)
def setup_safety_environment():
    # Reset kill switch and enable trading for test baseline
    risk_service.engine.reset_kill_switch("Automated test suite initialization")
    orig_notional = risk_service.engine.config.max_order_notional_usd
    risk_service.engine.config.max_order_notional_usd = 500.0
    with patch.object(delta_client, "get_products", new_callable=AsyncMock) as mock_prod, \
         patch.object(delta_client, "get_account_overview", new_callable=AsyncMock) as mock_acc:
        mock_prod.return_value = SAMPLE_PRODUCTS
        mock_acc.return_value = SAMPLE_ACCOUNT_OK
        # Pre-seed cache in risk_service
        risk_service._cached_products = SAMPLE_PRODUCTS
        risk_service._products_cached_time = time.time()
        yield
    risk_service.engine.config.max_order_notional_usd = orig_notional


# ============================================================================
# 1 & 2: Environment Guard & Host Allowlist Tests
# ============================================================================

def test_environment_guard_valid_testnet_hosts():
    """Requirement 1: Valid testnet configuration passes environment guard."""
    for host in VERIFIED_TESTNET_HOSTS:
        url = f"https://{host}"
        assert validate_testnet_host(url) == host
        assert validate_testnet_host(f"https://{host}/v2") == host


def test_environment_guard_rejects_production_urls():
    """Requirement 2: Production URLs are strictly rejected."""
    production_urls = [
        "https://cdn.deltaex.org",
        "https://api.delta.exchange",
        "https://cdn.india.delta.exchange",
        "https://api.india.delta.exchange",
        "https://india.delta.exchange",
        "https://delta.exchange",
    ]
    for prod_url in production_urls:
        with pytest.raises(EnvironmentSafetyViolation) as exc_info:
            validate_testnet_host(prod_url)
        assert "Production host" in str(exc_info.value) or "SAFETY VIOLATION" in str(exc_info.value)


def test_environment_guard_rejects_lookalike_and_malicious_domains():
    """Requirement 2: Lookalike, spoofed, and arbitrary domains are rejected."""
    bad_urls = [
        "https://cdn-ind.testnet.deltaex.org.attacker.com",
        "https://faketestnet.deltaex.org",
        "https://testnet.deltaex.org.fake",
        "https://evil-phishing.com",
        "http://cdn-ind.testnet.deltaex.org",  # Insecure HTTP
        "https://cdn-ind.testnet.deltaex.org:8443",  # Non-standard port
        "https://user:pass@cdn-ind.testnet.deltaex.org",  # Embedded credentials
        "",
        None,
    ]
    for bad_url in bad_urls:
        with pytest.raises(EnvironmentSafetyViolation):
            validate_testnet_host(bad_url)


# ============================================================================
# 3 & 4: Kill Switch & Trading Authorization Guard Tests
# ============================================================================

def test_kill_switch_engaged_blocks_order_confirmation():
    """Requirement 3: Kill switch engaged blocks order confirmation and submission."""
    # 1. Create a valid preview
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    # 2. Engage Emergency Kill Switch
    client.post("/api/v1/trading/kill-switch", json={"reason": "Emergency halt test"})

    # 3. Attempt confirmation - must be rejected with 403
    res_conf = client.post(
        "/api/v1/trading/orders/confirm",
        json={"preview_id": preview_id, "confirm": True},
    )
    assert res_conf.status_code == 403
    assert "Kill Switch is ENGAGED" in res_conf.json()["detail"]


def test_trading_authorization_disabled_blocks_submission():
    """Requirement 4: Trading authorization disabled blocks order confirmation."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    # Disable trading authorization directly in engine state
    risk_service.engine.state.trading_enabled = False

    res_conf = client.post(
        "/api/v1/trading/orders/confirm",
        json={"preview_id": preview_id, "confirm": True},
    )
    assert res_conf.status_code == 403
    assert "trading authorization is DISABLED" in res_conf.json()["detail"]


# ============================================================================
# 5, 6, 7 & 8: Data Validation & Pre-trade Risk Limits
# ============================================================================

def test_invalid_price_tick_size_rejected():
    """Requirement 7: Invalid price conforming to tick size is rejected."""
    # BTCUSD tick size is 0.1 on Delta Exchange. Price with 0.05 must be rejected
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.05,  # Invalid tick alignment
        "stop_loss": 79000.0,
    }
    res = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res.status_code == 422
    assert "tick size" in res.json()["detail"]


def test_missing_stop_loss_preview_marked_not_submittable():
    """Requirement 7 & 8: Missing stop-loss fails risk assessment and can_submit is False."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": None,
    }
    res = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res.status_code == 200
    data = res.json()
    assert data["can_submit"] is False
    assert data["risk_decision"] == "REJECTED"
    assert any("stop-loss" in r.lower() for r in data["risk_reasons"])


def test_oversized_notional_rejected_in_preview():
    """Requirement 8: Order exceeding max notional is rejected by pre-trade risk check."""
    # 40 BTC contracts @ $200,000 with 0.001 contract_value = $8,000 notional (exceeds $5,000 limit, while 40 < 50 position size limit)
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 40.0,
        "price": 200000.0,
        "stop_loss": 195000.0,
    }
    res = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res.status_code == 200
    data = res.json()
    assert data["can_submit"] is False
    assert data["risk_decision"] == "REJECTED"
    assert any("notional" in r.lower() for r in data["risk_reasons"])


# ============================================================================
# 9, 10 & 11: Two-Stage Manual Confirmation, Expiration & Replay Protection
# ============================================================================

def test_expired_preview_cannot_be_confirmed():
    """Requirement 9: Expired previews (> 60s) cannot be confirmed."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    # Artificially expire the preview in store
    preview_obj = asyncio.run(execution_store.get_preview(preview_id))
    assert preview_obj is not None
    preview_obj.expires_at = int(time.time()) - 10

    res_conf = client.post(
        "/api/v1/trading/orders/confirm",
        json={"preview_id": preview_id, "confirm": True},
    )
    assert res_conf.status_code == 400
    assert "expired" in res_conf.json()["detail"].lower()


def test_replayed_confirmation_blocked():
    """Requirement 10 & 11: Replaying an already confirmed preview is strictly blocked."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    mock_exchange_resp = {
        "id": 99887711,
        "product_id": 27,
        "size": 1,
        "side": "buy",
        "order_type": "limit_order",
        "state": "open",
        "unfilled_size": 1,
    }

    with patch.object(delta_testnet_gateway, "submit_order", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = mock_exchange_resp

        # First confirmation succeeds
        res_conf1 = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf1.status_code == 200
        assert res_conf1.json()["state"] == "OPEN"
        assert mock_submit.call_count == 1

        # Second confirmation of the same preview must be rejected
        res_conf2 = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf2.status_code == 400
        assert "already consumed" in res_conf2.json()["detail"].lower()
        # Ensure exchange was NOT called a second time
        assert mock_submit.call_count == 1


# ============================================================================
# 12 & 13: Exchange Rejection & Timeout Handling
# ============================================================================

def test_exchange_rejection_handled_cleanly():
    """Requirement 12: Exchange rejection is captured, marked REJECTED, and does not increment order count."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    initial_orders_today = risk_service.engine.state.orders_submitted_today

    with patch.object(delta_testnet_gateway, "submit_order", side_effect=ExchangeOrderRejectedError("Insufficient margin")):
        res_conf = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf.status_code == 422
        assert "Insufficient margin" in res_conf.json()["detail"]
        # Order counter must NOT have incremented
        assert risk_service.engine.state.orders_submitted_today == initial_orders_today


def test_network_timeout_produces_unknown_state_never_retries():
    """Requirement 13: Network timeout creates UNKNOWN state pending reconciliation, not blind retry."""
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    with patch.object(
        delta_testnet_gateway,
        "submit_order",
        side_effect=OrderSubmissionTimeoutError("tokiq_timeout_test", "Request timed out"),
    ) as mock_submit:
        res_conf = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf.status_code == 200
        data = res_conf.json()
        assert data["state"] == "UNKNOWN"
        assert data["reconciliation_needed"] is True
        # Gateway submit_order was called exactly once, NEVER retried blindly
        assert mock_submit.call_count == 1


# ============================================================================
# 14: Order Cancellation Validation
# ============================================================================

def test_cancel_ineligible_order_rejected():
    """Requirement 14: Cancelling an order that is not open (e.g. FILLED or CANCELLED) is rejected."""
    filled_rec = OrderExecutionRecord(
        preview_id="prev_filled_test",
        client_order_id="tokiq_filled_test_1",
        order_id="990011",
        symbol="BTCUSD",
        product_id=27,
        side="BUY",
        order_type="limit_order",
        size=1.0,
        unfilled_size=0.0,
        state=OrderState.FILLED.value,
        notional_usd=80.0,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    asyncio.run(execution_store.save_order(filled_rec))

    res_cancel = client.post(
        f"/api/v1/trading/orders/{filled_rec.order_id}/cancel",
        json={"reason": "Test cancel"},
    )
    assert res_cancel.status_code == 400
    assert "cannot be cancelled" in res_cancel.json()["detail"].lower()


# ============================================================================
# 15 & 16: Automated Trading Disabled & No Route to Production
# ============================================================================

def test_strategy_signals_never_automatically_submit_orders():
    """Requirement 15: Strategy signal generation must never place orders."""
    initial_orders = risk_service.engine.state.orders_submitted_today

    with patch.object(delta_testnet_gateway, "submit_order", new_callable=AsyncMock) as mock_submit:
        res = client.post("/api/v1/strategies/ema_crossover/signal", json={"symbol": "BTCUSD", "resolution": "1h"})
        # Signal endpoint generates signals or handles data
        assert res.status_code in (200, 422, 400)
        # Order gateway was NEVER called
        assert mock_submit.call_count == 0
        # Orders today remained unchanged
        assert risk_service.engine.state.orders_submitted_today == initial_orders


def test_production_url_in_execution_service_rejected():
    """Requirement 16: Execution service strictly rejects any attempt to route to production."""
    from unittest.mock import PropertyMock
    # pyrefly: ignore[missing-import]
    from app.trading.gateway import DeltaTestnetOrderGateway
    with patch.object(DeltaTestnetOrderGateway, "host_url", new_callable=PropertyMock, return_value="https://api.delta.exchange"):
        with pytest.raises(EnvironmentSafetyViolation):
            asyncio.run(order_execution_service.get_execution_status())


def test_execution_status_api_endpoint():
    """Verify GET /api/v1/trading/execution/status returns correct posture."""
    res = client.get("/api/v1/trading/execution/status")
    assert res.status_code == 200
    data = res.json()
    assert data["service_ready"] is True
    assert data["testnet_enforced"] is True
    assert "cdn-ind.testnet.deltaex.org" in data["verified_host"] or "testnet" in data["verified_host"]
    assert "TESTNET ORDER EXECUTION" in data["disclaimer"]


@pytest.mark.asyncio
async def test_concurrent_confirmation_attempts_only_one_succeeds():
    """Requirement 11: Concurrent confirmation attempts - atomic consumption ensures exactly one succeeds."""
    prev_req = OrderPreviewRequest(
        symbol="BTCUSD",
        side="BUY",
        order_type="limit_order",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
    )
    preview = await order_execution_service.create_order_preview(prev_req)
    preview_id = preview.preview_id

    mock_exchange_resp = {
        "id": 55443322,
        "product_id": 27,
        "size": 1,
        "side": "buy",
        "order_type": "limit_order",
        "state": "open",
        "unfilled_size": 1,
    }

    with patch.object(delta_testnet_gateway, "submit_order", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = mock_exchange_resp

        req = OrderConfirmRequest(preview_id=preview_id, confirm=True)
        # Dispatch two concurrent confirmation coroutines
        results = await asyncio.gather(
            order_execution_service.confirm_and_submit_order(req),
            order_execution_service.confirm_and_submit_order(req),
            return_exceptions=True,
        )

        successes = [r for r in results if isinstance(r, OrderExecutionRecord)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1
        assert len(failures) == 1
        assert "already consumed" in str(failures[0]).lower() or "invalid" in str(failures[0]).lower()
        # Gateway was submitted to exchange exactly once
        assert mock_submit.call_count == 1


def test_kill_switch_activated_during_pending_workflow_prevents_submission():
    """Requirement 18: Kill switch activated during a pending workflow prevents submission."""
    # Step A: User creates preview while system is healthy
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    # Step B: Emergency occurs right before confirmation!
    client.post(
        "/api/v1/trading/kill-switch",
        json={"reason": "Sudden exchange maintenance detected during user workflow"},
    )

    # Step C: User attempts to confirm pending preview
    with patch.object(delta_testnet_gateway, "submit_order", new_callable=AsyncMock) as mock_submit:
        res_conf = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf.status_code == 403
        assert "Kill Switch is ENGAGED" in res_conf.json()["detail"]
        assert mock_submit.call_count == 0


@pytest.mark.asyncio
async def test_reconciliation_exchange_error_preserves_unknown_state():
    """Regression Test: If exchange query fails (401/network), order state remains UNKNOWN and reconciliation_needed is True."""
    order_record = OrderExecutionRecord(
        preview_id="prev_recon_test_1",
        client_order_id="tokiq_recon_test_1",
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
        reconciliation_attempts=0,
    )
    await execution_store.save_order(order_record)

    with patch.object(
        delta_testnet_gateway,
        "list_open_orders",
        side_effect=RuntimeError("Delta API HTTP 401: IP not whitelisted"),
    ), patch.object(delta_testnet_gateway, "submit_order", new_callable=AsyncMock) as mock_submit:
        with pytest.raises(RuntimeError) as exc_info:
            await order_execution_service.reconcile_order("tokiq_recon_test_1")

        assert "Exchange unreachable" in str(exc_info.value)
        # Order submission was NEVER called or blindly retried
        assert mock_submit.call_count == 0

    reloaded = await execution_store.get_order_by_id("tokiq_recon_test_1")
    assert reloaded is not None
    # State MUST remain UNKNOWN
    assert reloaded.state == OrderState.UNKNOWN.value
    assert reloaded.reconciliation_needed is True
    # Verification attempts must NOT increment towards false expiry when exchange failed
    assert reloaded.reconciliation_attempts == 0
    assert "Reconciliation blocked by exchange communication error" in (reloaded.error_message or "")


def test_runtime_storage_unpolluted_by_timeout_test():
    """Regression Test: Running tests that simulate timeouts does NOT write to runtime execution_records.json."""
    from pathlib import Path
    import json

    runtime_file = Path(__file__).resolve().parent.parent / "backend" / "app" / "trading" / "execution_records.json"
    assert runtime_file.exists()

    with open(runtime_file, "r", encoding="utf-8") as f:
        before_data = json.load(f)
    before_count = len(before_data.get("orders", []))

    # Run order preview and timed-out confirmation
    prev_req = {
        "symbol": "BTCUSD",
        "side": "BUY",
        "order_type": "limit_order",
        "quantity": 1.0,
        "price": 80000.0,
        "stop_loss": 79000.0,
    }
    res_prev = client.post("/api/v1/trading/orders/preview", json=prev_req)
    assert res_prev.status_code == 200
    preview_id = res_prev.json()["preview_id"]

    with patch.object(
        delta_testnet_gateway,
        "submit_order",
        side_effect=OrderSubmissionTimeoutError("tokiq_storage_test", "Request timed out"),
    ):
        res_conf = client.post(
            "/api/v1/trading/orders/confirm",
            json={"preview_id": preview_id, "confirm": True},
        )
        assert res_conf.status_code == 200
        assert res_conf.json()["state"] == "UNKNOWN"

    # Verify that the runtime file was completely untouched
    with open(runtime_file, "r", encoding="utf-8") as f:
        after_data = json.load(f)
    after_count = len(after_data.get("orders", []))

    assert before_count == after_count
    # Ensure the newly created test order client_order_id does NOT exist in runtime file
    assert not any(o.get("client_order_id") == res_conf.json()["client_order_id"] for o in after_data.get("orders", []))

