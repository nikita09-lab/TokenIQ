import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.automation.worker import automated_trading_worker, AutomationState
from app.automation.config import automation_config_manager
from app.automation.position_manager import position_manager
from app.exchanges.delta_client import delta_client
from app.risk.service import risk_service
from app.risk.models import TradingStatus, RiskConfig, SafetyState


@pytest.fixture
def test_client():
    return TestClient(app)


def test_automation_status_telemetry_fields(test_client):
    """
    Verify that /api/v1/automation/status delivers complete telemetry
    including verified_host, config.selected_strategy, and orders_submitted_today.
    """
    response = test_client.get("/api/v1/automation/status")
    assert response.status_code == 200
    data = response.json()

    # Telemetry fields required by the dashboard
    assert "verified_host" in data
    assert data["verified_host"] == "cdn-ind.testnet.deltaex.org"
    assert "config" in data
    assert "selected_strategy" in data["config"]
    assert data["config"]["selected_strategy"] == "ema_crossover"
    assert "orders_submitted_today" in data
    assert isinstance(data["orders_submitted_today"], int)
    assert "active_position" in data
    assert "testnet_enforced" in data
    assert data["testnet_enforced"] is True


def test_order_counter_consistency(test_client):
    """
    Verify that /api/v1/automation/status and /api/v1/trading/status
    report consistent orders_submitted_today counters from the Risk Engine.
    """
    # Set risk state orders_submitted_today to 15
    from app.risk.engine import risk_engine
    risk_engine.state.orders_submitted_today = 15

    trading_res = test_client.get("/api/v1/trading/status")
    assert trading_res.status_code == 200
    trading_data = trading_res.json()
    assert trading_data["orders_submitted_today"] == 15

    auto_res = test_client.get("/api/v1/automation/status")
    assert auto_res.status_code == 200
    auto_data = auto_res.json()
    assert auto_data["orders_submitted_today"] == 15


def test_protective_stop_flat_position_semantics(test_client):
    """
    When managed position is FLAT (quantity == 0.0), protection_verified must be False
    and stop_loss_order_id must be None. The frontend should display FLAT (N/A) rather
    than suggesting a missing or unverified stop on an open trade.
    """
    response = test_client.get("/api/v1/automation/status")
    assert response.status_code == 200
    data = response.json()

    active_pos = data.get("active_position")
    assert active_pos is not None
    assert active_pos["lifecycle_state"] == "FLAT"
    assert active_pos["quantity"] == 0.0
    assert active_pos["protection_verified"] is False
    assert active_pos["stop_loss_order_id"] is None


@pytest.mark.asyncio
async def test_account_overview_cache_short_ttl(monkeypatch):
    """
    Verify that delta_client.get_account_overview caches responses within 2.5s
    to avoid hammering the exchange when multiple dashboard components query status concurrently.
    """
    mock_payload = {
        "authenticated": True,
        "is_testnet": True,
        "total_balance_usd": 1000.0,
        "positions": [],
        "open_orders": [],
        "recent_orders": [],
    }

    # Provide test credentials so the method exercises the authenticated cache path.
    monkeypatch.setattr(delta_client, "api_key", "test-api-key")
    monkeypatch.setattr(delta_client, "api_secret", "test-api-secret")

    # Clear any previous cache
    delta_client._account_overview_cache = None

    with patch.object(delta_client, "get_wallet_balances", new_callable=AsyncMock) as mock_wallets, \
         patch.object(delta_client, "get_positions", new_callable=AsyncMock) as mock_pos, \
         patch.object(delta_client, "get_open_orders", new_callable=AsyncMock) as mock_orders, \
         patch.object(delta_client, "get_order_history", new_callable=AsyncMock) as mock_hist:

        mock_wallets.return_value = [{"asset_symbol": "USDT", "balance": 1000.0, "available_balance": 1000.0, "blocked_margin": 0.0}]
        mock_pos.return_value = []
        mock_orders.return_value = []
        mock_hist.return_value = []

        # Call 1: should invoke network methods
        res1 = await delta_client.get_account_overview()
        assert mock_wallets.call_count == 1

        # Call 2 (immediate): should return cached result without calling network again
        res2 = await delta_client.get_account_overview()
        assert mock_wallets.call_count == 1
        assert res2["total_balance_usd"] == res1["total_balance_usd"]

        # Call 3 (forced refresh): should bypass cache
        res3 = await delta_client.get_account_overview(force_refresh=True)
        assert mock_wallets.call_count == 2


def test_automation_remains_off_invariant(test_client):
    """Safety check: automated trading must remain strictly OFF."""
    res = test_client.get("/api/v1/automation/status")
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "OFF"
    assert data["enabled"] is False
