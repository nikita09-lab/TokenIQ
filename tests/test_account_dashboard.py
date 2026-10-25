import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.exchanges.delta_client import DeltaExchangeClient
from app.main import app

client = TestClient(app)


def test_testnet_security_guardrail_prevents_production_account_calls():
    """
    Ensure the backend fails closed and refuses to execute private authenticated
    endpoints if configured with a production URL.
    """
    prod_client = DeltaExchangeClient(
        base_url="https://api.india.delta.exchange",
        api_key="key",
        api_secret="secret",
    )
    with pytest.raises(RuntimeError, match="Security Violation"):
        prod_client._assert_testnet_safe()


@pytest.mark.asyncio
async def test_wallet_balances_normalized_mocked():
    """
    Verify /v2/wallet/balances is correctly normalized into typed models.
    """
    delta = DeltaExchangeClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    mock_resp = {
        "success": True,
        "result": [
            {
                "asset_id": 14,
                "asset_symbol": "USDT",
                "balance": "10000.500000",
                "available_balance": "8500.000000",
                "blocked_margin": "1500.500000",
            },
            {
                "asset_id": 2,
                "asset_symbol": "BTC",
                "balance": "0.500000",
                "available_balance": "0.500000",
                "blocked_margin": "0.000000",
            },
        ],
    }

    with patch.object(delta, "_get_authenticated", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        balances = await delta.get_wallet_balances()
        assert len(balances) == 2
        assert balances[0]["asset_symbol"] == "USDT"
        assert balances[0]["balance"] == "10000.500000"


@pytest.mark.asyncio
async def test_positions_normalized_mocked():
    """
    Verify /v2/positions/margined is normalized with sides and pricing.
    """
    delta = DeltaExchangeClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="test_key",
        api_secret="test_secret",
    )

    mock_resp = {
        "success": True,
        "result": [
            {
                "product_id": 27,
                "product_symbol": "BTCUSD",
                "size": 100,
                "entry_price": "65000.0",
                "mark_price": "66000.0",
                "margin": "650.0",
                "unrealized_pnl": "100.0",
                "realized_pnl": "0.0",
                "liquidation_price": "55000.0",
                "leverage": 10.0,
            },
            {
                "product_id": 12,
                "product_symbol": "ETHUSD",
                "size": -50,
                "entry_price": "3500.0",
                "mark_price": "3550.0",
                "margin": "175.0",
                "unrealized_pnl": "-25.0",
                "realized_pnl": "0.0",
                "liquidation_price": "4000.0",
                "leverage": 10.0,
            },
        ],
    }

    with patch.object(delta, "_get_authenticated", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        positions = await delta.get_positions()
        assert len(positions) == 2
        assert positions[0]["product_symbol"] == "BTCUSD"


@pytest.mark.asyncio
async def test_ip_whitelist_diagnostic_extraction():
    """
    Verify that when Delta returns ip_not_whitelisted_for_api_key, the client IP
    is extracted and reported in the diagnostic without leaking credentials.
    """
    delta = DeltaExchangeClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key="key",
        api_secret="secret",
    )

    fake_err = RuntimeError('Delta API HTTP 401: {"error":{"code":"ip_not_whitelisted_for_api_key","context":{"client_ip":"223.228.40.93"}},"success":false}')
    setattr(fake_err, "status_code", 401)
    setattr(fake_err, "response_body", '{"error":{"code":"ip_not_whitelisted_for_api_key","context":{"client_ip":"223.228.40.93"}},"success":false}')

    diag, client_ip = delta._diagnose_auth_error(fake_err)
    assert client_ip == "223.228.40.93"
    assert "IP Whitelist Restriction" in diag
    assert "223.228.40.93" in diag
    assert "secret" not in diag


@pytest.mark.asyncio
async def test_get_account_overview_unconfigured():
    """
    Verify that when credentials are not present, get_account_overview returns
    safe empty arrays without crashing or inventing balances.
    """
    delta = DeltaExchangeClient(base_url="https://cdn-ind.testnet.deltaex.org", api_key="", api_secret="")
    overview = await delta.get_account_overview()

    assert overview["authenticated"] is False
    assert overview["is_testnet"] is True
    assert overview["total_balance_usd"] == 0.0
    assert overview["balances"] == []
    assert overview["positions"] == []
    assert overview["open_orders"] == []
    assert overview["recent_orders"] == []
    assert "missing" in overview["diagnostic"]


def test_api_account_overview_endpoint():
    """
    Test GET /api/v1/account/overview endpoint.
    """
    with patch("app.exchanges.delta_client.delta_client.get_account_overview", new_callable=AsyncMock) as mock_overview:
        mock_overview.return_value = {
            "authenticated": True,
            "is_testnet": True,
            "environment": "testnet",
            "base_url": "https://cdn-ind.testnet.deltaex.org",
            "masked_api_key": "q72...det",
            "client_ip": "223.228.40.93",
            "total_balance_usd": 10000.0,
            "available_balance_usd": 8500.0,
            "total_margin_used_usd": 1500.0,
            "total_unrealized_pnl_usd": 150.0,
            "balances": [
                {
                    "asset_id": 14,
                    "asset_symbol": "USDT",
                    "balance": 10000.0,
                    "available_balance": 8500.0,
                    "blocked_margin": 1500.0,
                    "usd_value": 10000.0,
                }
            ],
            "positions": [],
            "open_orders": [],
            "recent_orders": [],
            "last_updated_at": 1700000000,
            "diagnostic": None,
            "warning": None,
            "disclaimer": "TESTNET DEMO ONLY",
        }

        res = client.get("/api/v1/account/overview")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        overview = data["overview"]
        assert overview["authenticated"] is True
        assert overview["total_balance_usd"] == 10000.0
        assert len(overview["balances"]) == 1


def test_api_account_positions_endpoint():
    """
    Test GET /api/v1/account/positions endpoint.
    """
    with patch("app.exchanges.delta_client.delta_client.get_account_overview", new_callable=AsyncMock) as mock_overview:
        mock_overview.return_value = {
            "authenticated": True,
            "positions": [
                {
                    "product_id": 27,
                    "symbol": "BTCUSD",
                    "side": "LONG",
                    "size": 100.0,
                    "entry_price": 65000.0,
                    "mark_price": 66000.0,
                    "margin": 650.0,
                    "unrealized_pnl": 100.0,
                    "realized_pnl": 0.0,
                    "liquidation_price": 55000.0,
                    "bankruptcy_price": 54000.0,
                    "leverage": 10.0,
                    "updated_at": 1700000000000,
                }
            ],
            "total_unrealized_pnl_usd": 100.0,
            "diagnostic": None,
        }

        res = client.get("/api/v1/account/positions")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "BTCUSD"
        assert data["positions"][0]["side"] == "LONG"
