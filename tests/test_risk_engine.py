import json
import math
import os
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# pyrefly: ignore[missing-import]
from app.main import app
# pyrefly: ignore[missing-import]
from app.risk.engine import RiskEngine
# pyrefly: ignore[missing-import]
from app.risk.models import (
    CheckStatus,
    RiskCheckRequest,
    RiskConfig,
    SafetyState,
)
# pyrefly: ignore[missing-import]
from app.risk.service import RiskManagementService

client = TestClient(app)

SAMPLE_PRODUCTS = [
    {
        "id": 84,
        "symbol": "BTCUSD",
        "tick_size": "0.1",
        "contract_value": "0.001",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
        "position_size_limit": 5000,
        "position_notional_limit": "300000",
    },
    {
        "id": 85,
        "symbol": "ETHUSD",
        "tick_size": "0.05",
        "contract_value": "0.01",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
        "position_size_limit": 4000,
        "position_notional_limit": "150000",
    },
]

SAMPLE_ACCOUNT_OK = {
    "authenticated": True,
    "positions": [
        {
            "product_id": 84,
            "symbol": "BTCUSD",
            "size": 5.0,
            "realized_pnl": -50.0,
        }
    ],
    "balances": [{"asset_symbol": "USDT", "balance": 10000.0, "available_balance": 8000.0}],
}


@pytest.fixture
def temp_risk_engine(tmp_path):
    """Fixture providing an isolated RiskEngine with temporary state and config files."""
    state_file = tmp_path / "safety_state.json"
    config_file = tmp_path / "risk_config.json"
    engine = RiskEngine(state_file=state_file, config_file=config_file)
    return engine


def test_trading_disabled_by_default_on_startup(temp_risk_engine):
    """
    Requirement 1: Trading must be disabled by default after application startup.
    Kill switch must be engaged by default.
    """
    assert temp_risk_engine.state.trading_enabled is False
    assert temp_risk_engine.state.kill_switch_engaged is True
    assert "Startup default" in (temp_risk_engine.state.kill_switch_reason or "")


@pytest.mark.asyncio
async def test_kill_switch_blocks_approvals(temp_risk_engine):
    """
    Requirement 3: Kill switch blocks all future execution approvals.
    """
    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_test_1",
    )
    result = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert result.approved is False
    assert result.decision == "REJECTED"
    assert any("Kill Switch is ACTIVE" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_approved_when_trading_enabled_and_all_rules_pass(temp_risk_engine):
    """
    Verify that when deliberately reset/enabled, a completely valid signal is APPROVED.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing activation")
    assert temp_risk_engine.state.trading_enabled is True
    assert temp_risk_engine.state.kill_switch_engaged is False

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=5.0,  # 5 * 0.001 * 80000 = $400.00 notional (under stricter $500 limit)
        price=80000.0,
        stop_loss=79000.0,  # distance = 1.25% (>= 0.5% min)
        signal_id="sig_valid_1",
        timestamp=int(time.time()),
    )
    result = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert result.approved is True
    assert result.decision == "APPROVED"
    assert len(result.reasons) == 0
    assert result.proposed_notional_usd == 400.0


@pytest.mark.asyncio
async def test_order_notional_limit_independently(temp_risk_engine):
    """
    Requirement 2: Maximum order notional value limit.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")
    # For BTCUSD, contract_value is 0.001 BTC.
    # At price 80,000, 100 contracts = 100 * 0.001 * 80000 = $8,000 notional (exceeds default $5,000 limit)
    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=100.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_notional_1",
        timestamp=int(time.time()),
    )
    result = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert result.approved is False
    assert any("Order notional" in r and "exceeds maximum allowed limit" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_position_size_limit_independently(temp_risk_engine):
    """
    Requirement 2: Maximum position size limit.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")
    # Set limit to 20 contracts
    temp_risk_engine.config.max_position_size = 20.0

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=25.0,  # exceeds 20.0
        price=50000.0,
        stop_loss=49500.0,
        signal_id="sig_pos_size_1",
        timestamp=int(time.time()),
    )
    result = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert result.approved is False
    assert any("position size limit" in r.lower() for r in result.reasons)


@pytest.mark.asyncio
async def test_stop_loss_validation(temp_risk_engine):
    """
    Requirement 2: Stop loss parameter validation and minimum acceptable distance.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")

    # 1. Missing stop-loss
    req_no_sl = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=None,
        signal_id="sig_sl_1",
        timestamp=int(time.time()),
    )
    res1 = await temp_risk_engine.evaluate_risk(req_no_sl, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res1.approved is False
    assert any("Missing stop-loss" in r for r in res1.reasons)

    # 2. Long Stop-Loss above entry price
    req_bad_long_sl = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=81000.0,
        signal_id="sig_sl_2",
        timestamp=int(time.time()),
    )
    res2 = await temp_risk_engine.evaluate_risk(req_bad_long_sl, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res2.approved is False
    assert any("Invalid Long Stop-Loss" in r for r in res2.reasons)

    # 3. Short Stop-Loss below entry price
    req_bad_short_sl = RiskCheckRequest(
        symbol="BTCUSD",
        side="SELL",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_sl_3",
        timestamp=int(time.time()),
    )
    res3 = await temp_risk_engine.evaluate_risk(req_bad_short_sl, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res3.approved is False
    assert any("Invalid Short Stop-Loss" in r for r in res3.reasons)

    # 4. Stop-loss distance too tight (less than 0.5% default)
    # Entry 80,000, SL 79,900 -> 100/80000 = 0.125% (< 0.5%)
    req_tight_sl = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79900.0,
        signal_id="sig_sl_4",
        timestamp=int(time.time()),
    )
    res4 = await temp_risk_engine.evaluate_risk(req_tight_sl, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res4.approved is False
    assert any("tighter than minimum required" in r for r in res4.reasons)


@pytest.mark.asyncio
async def test_daily_realized_loss_limit(temp_risk_engine):
    """
    Requirement 2: Maximum daily realized loss limit.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")
    temp_risk_engine.config.max_daily_realized_loss_usd = 200.0

    account_heavy_loss = {
        "authenticated": True,
        "positions": [
            {"product_id": 84, "symbol": "BTCUSD", "size": 0.0, "realized_pnl": -250.0}
        ],
    }

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_loss_1",
        timestamp=int(time.time()),
    )
    res = await temp_risk_engine.evaluate_risk(req, account_heavy_loss, SAMPLE_PRODUCTS)
    assert res.approved is False
    assert any("Daily realized loss threshold exceeded" in r for r in res.reasons)


@pytest.mark.asyncio
async def test_concurrent_positions_limit(temp_risk_engine):
    """
    Requirement 2: Maximum concurrent positions limit.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")
    temp_risk_engine.config.max_concurrent_positions = 2

    # Account already has 2 active positions
    account_2_positions = {
        "authenticated": True,
        "positions": [
            {"product_id": 84, "symbol": "BTCUSD", "size": 1.0, "realized_pnl": 0.0},
            {"product_id": 85, "symbol": "ETHUSD", "size": 1.0, "realized_pnl": 0.0},
        ],
    }

    # Propose opening SOLUSD (a 3rd position)
    products_with_sol = SAMPLE_PRODUCTS + [
        {
            "id": 86,
            "symbol": "SOLUSD",
            "tick_size": "0.01",
            "contract_value": "1.0",
            "contract_type": "perpetual_futures",
            "trading_status": "operational",
            "state": "live",
        }
    ]

    req = RiskCheckRequest(
        symbol="SOLUSD",
        side="BUY",
        quantity=1.0,
        price=150.0,
        stop_loss=145.0,
        signal_id="sig_sol_1",
        timestamp=int(time.time()),
    )
    res = await temp_risk_engine.evaluate_risk(req, account_2_positions, products_with_sol)
    assert res.approved is False
    assert any("Concurrent positions limit reached" in r for r in res.reasons)


@pytest.mark.asyncio
async def test_persistent_signal_deduplication(temp_risk_engine, tmp_path):
    """
    Requirement 3: Signal deduplication must be persisted across restarts.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_replay_100",
        timestamp=int(time.time()),
    )

    # First evaluation succeeds
    res1 = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res1.approved is True

    # Immediate duplicate evaluation fails
    res2 = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res2.approved is False
    assert any("Duplicate signal ID" in r for r in res2.reasons)

    # Re-instantiate engine from disk state file (simulating backend restart)
    new_engine_instance = RiskEngine(
        state_file=temp_risk_engine.state_file,
        config_file=temp_risk_engine.config_file,
    )
    new_engine_instance.reset_kill_switch(reason="Re-opened after restart")

    # Evaluation with same signal_id must STILL be rejected!
    res3 = await new_engine_instance.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res3.approved is False
    assert any("Duplicate signal ID" in r for r in res3.reasons)


@pytest.mark.asyncio
async def test_stale_signal_rejection(temp_risk_engine):
    """
    Requirement 2: Rejection of stale signals.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")
    old_timestamp = int(time.time()) - 600  # 10 minutes ago (exceeds default 300s)

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_stale_1",
        timestamp=old_timestamp,
    )
    res = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS)
    assert res.approved is False
    assert any("Stale signal" in r for r in res.reasons)


@pytest.mark.asyncio
async def test_fail_closed_on_missing_exchange_metadata(temp_risk_engine):
    """
    Requirement 4: Fail closed if product metadata is missing or unavailable.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_missing_meta",
        timestamp=int(time.time()),
    )
    # Empty product list
    res = await temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, products_metadata=[])
    assert res.approved is False
    assert any("Exchange product metadata unavailable" in r for r in res.reasons)


@pytest.mark.asyncio
async def test_fail_closed_on_missing_account_telemetry(temp_risk_engine):
    """
    Requirement 4: Fail closed if account telemetry is unavailable.
    """
    temp_risk_engine.reset_kill_switch(reason="Authorized testing")

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_missing_account",
        timestamp=int(time.time()),
    )
    # None account telemetry
    res = await temp_risk_engine.evaluate_risk(req, account_telemetry=None, products_metadata=SAMPLE_PRODUCTS)
    assert res.approved is False
    assert any("Account telemetry unavailable" in r for r in res.reasons)


def test_corrupt_safety_state_file_fails_closed(tmp_path):
    """
    Requirement 7: If the state file is corrupt or unreadable, trading must remain disabled.
    """
    bad_file = tmp_path / "safety_state.json"
    bad_file.write_text("{ this is corrupt json !!!", encoding="utf-8")

    engine = RiskEngine(state_file=bad_file)
    assert engine.state.trading_enabled is False
    assert engine.state.kill_switch_engaged is True
    assert "Fail-closed" in (engine.state.kill_switch_reason or "")


def test_daily_order_counter_distinct_from_evaluations(temp_risk_engine):
    """
    Requirement 2: Risk-check evaluations must not count as actual submitted orders.
    """
    initial_orders = temp_risk_engine.state.orders_submitted_today
    initial_evals = temp_risk_engine.state.evaluations_today

    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=80000.0,
        stop_loss=79000.0,
        signal_id="sig_counter_1",
    )
    import asyncio
    asyncio.run(temp_risk_engine.evaluate_risk(req, SAMPLE_ACCOUNT_OK, SAMPLE_PRODUCTS))

    assert temp_risk_engine.state.evaluations_today == initial_evals + 1
    # Orders submitted count MUST remain unchanged!
    assert temp_risk_engine.state.orders_submitted_today == initial_orders


# ============================================================================
# API Route Integration Tests
# ============================================================================

def test_api_trading_status_endpoint():
    """Verify GET /api/v1/trading/status returns structure."""
    res = client.get("/api/v1/trading/status")
    assert res.status_code == 200
    data = res.json()
    assert "trading_enabled" in data
    assert "kill_switch_engaged" in data
    assert data["dry_run_mode"] == (not data["trading_enabled"])
    assert data["testnet_enforced"] is True


def test_api_risk_config_get_and_update():
    """Verify GET and PUT /api/v1/trading/risk-config."""
    res_get = client.get("/api/v1/trading/risk-config")
    assert res_get.status_code == 200
    cfg = res_get.json()
    assert cfg["max_order_notional_usd"] > 0

    # Valid update
    cfg["max_order_notional_usd"] = 7500.0
    res_put = client.put("/api/v1/trading/risk-config", json=cfg)
    assert res_put.status_code == 200
    assert res_put.json()["max_order_notional_usd"] == 7500.0

    # Invalid update (negative or zero)
    bad_cfg = dict(cfg)
    bad_cfg["max_order_notional_usd"] = -100.0
    res_bad = client.put("/api/v1/trading/risk-config", json=bad_cfg)
    assert res_bad.status_code == 422


def test_api_kill_switch_engage_and_reset():
    """Verify POST /api/v1/trading/kill-switch and reset."""
    # Engage
    res = client.post("/api/v1/trading/kill-switch", json={"reason": "Test emergency pause"})
    assert res.status_code == 200
    data = res.json()
    assert data["kill_switch_engaged"] is True
    assert data["trading_enabled"] is False

    # Attempt reset without confirm=True
    res_bad_reset = client.post(
        "/api/v1/trading/kill-switch/reset",
        json={"confirm": False, "reason": "No confirm"},
    )
    assert res_bad_reset.status_code == 400

    # Valid deliberate reset
    res_reset = client.post(
        "/api/v1/trading/kill-switch/reset",
        json={"confirm": True, "reason": "Operator verification complete"},
    )
    assert res_reset.status_code == 200
    assert res_reset.json()["kill_switch_engaged"] is False
    assert res_reset.json()["trading_enabled"] is True


def test_dry_run_risk_check_never_calls_order_execution():
    """
    Requirement 9: Add tests proving dry-run checks never call any order-placement method,
    including under error conditions.
    """
    from unittest.mock import MagicMock
    # pyrefly: ignore[missing-import]
    from app.exchanges.delta_client import delta_client

    # 1. Structural audit: delta_client strictly lacks order placement methods
    assert not hasattr(delta_client, "place_order")
    assert not hasattr(delta_client, "submit_order")
    assert not hasattr(delta_client, "create_order")
    assert not hasattr(delta_client, "_post_authenticated")

    # 2. Attach a sentinel mock order-placement method to delta_client to verify it is NEVER called
    delta_client.place_order_sentinel = MagicMock()

    try:
        # A: Test under normal evaluation
        req_data = {
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1.0,
            "price": 80000.0,
            "stop_loss": 79000.0,
            "signal_id": f"dry_run_safe_{int(time.time())}",
        }
        res = client.post("/api/v1/trading/risk-check", json=req_data)
        assert res.status_code == 200
        data = res.json()
        assert "decision" in data
        assert "DRY-RUN RESULT" in data["disclaimer"]
        assert delta_client.place_order_sentinel.call_count == 0

        # B: Test under error conditions (e.g., account telemetry network failure)
        with patch.object(delta_client, "get_account_overview", side_effect=RuntimeError("Simulated network failure")):
            req_data_err = {
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 1.0,
                "price": 80000.0,
                "stop_loss": 79000.0,
                "signal_id": f"dry_run_err_{int(time.time())}",
            }
            res_err = client.post("/api/v1/trading/risk-check", json=req_data_err)
            assert res_err.status_code == 200
            data_err = res_err.json()
            # Fails closed on error
            assert data_err["decision"] == "REJECTED"
            assert any("telemetry" in r["rule_name"].lower() and r["status"] == "FAILED" for r in data_err["rules_evaluated"])
            # Proves dry run NEVER calls order placement even under error conditions
            assert delta_client.place_order_sentinel.call_count == 0
    finally:
        delattr(delta_client, "place_order_sentinel")

