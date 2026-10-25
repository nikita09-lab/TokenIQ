import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient

from app.exchanges.delta_client import DeltaExchangeClient
from app.main import app

client = TestClient(app)


def test_signature_generation_matches_specification():
    """
    Verify that HMAC-SHA256 signature matches Delta Exchange documented formula:
    Signature Data = Method + Timestamp + Path + QueryString + Body
    """
    api_key = "test_api_key_12345"
    api_secret = "test_api_secret_secret_abc"
    delta = DeltaExchangeClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key=api_key,
        api_secret=api_secret,
    )

    fixed_timestamp = "1700000000"
    method = "GET"
    path = "/v2/profile"
    query_string = ""
    payload = ""

    # Expected raw string: GET1700000000/v2/profile
    expected_data = "GET1700000000/v2/profile"
    expected_signature = hmac.new(
        api_secret.encode("utf-8"),
        expected_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    sig, ts = delta.generate_signature(
        method=method,
        path=path,
        query_string=query_string,
        payload=payload,
        timestamp=fixed_timestamp,
    )

    assert ts == fixed_timestamp
    assert sig == expected_signature
    assert len(sig) == 64  # SHA-256 produces 64 hex characters


def test_signature_with_query_string():
    """
    Verify that query parameters are properly incorporated with a leading '?' in signature.
    """
    api_secret = "secret123"
    delta = DeltaExchangeClient(api_key="key123", api_secret=api_secret)

    sig, ts = delta.generate_signature(
        method="GET",
        path="/v2/orders",
        query_string="states=open",
        timestamp="1700000000",
    )

    expected_data = "GET1700000000/v2/orders?states=open"
    expected_sig = hmac.new(
        api_secret.encode("utf-8"),
        expected_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert sig == expected_sig


def test_signature_timestamp_is_integer_seconds():
    """
    Ensure default timestamp is Unix epoch in seconds (not float and not milliseconds).
    """
    delta = DeltaExchangeClient(api_key="k", api_secret="s")
    _, ts = delta.generate_signature("GET", "/v2/profile")

    # ts must be all digits
    assert ts.isdigit()
    # Must be in reasonable epoch seconds range (approx 10 digits for years 2020-2030)
    assert 9 <= len(ts) <= 11
    val = int(ts)
    assert val > 1600000000
    assert val < 2500000000


def test_signature_missing_credentials_raises_error():
    delta_no_secret = DeltaExchangeClient(api_key="k", api_secret="")
    with pytest.raises(ValueError, match="API Secret is not configured"):
        delta_no_secret.generate_signature("GET", "/v2/profile")

    delta_no_key = DeltaExchangeClient(api_key="", api_secret="s")
    with pytest.raises(ValueError, match="API Key is not configured"):
        delta_no_key.get_auth_headers("GET", "/v2/profile")


def test_auth_headers_construction():
    api_key = "delta_key_999"
    api_secret = "delta_secret_888"
    delta = DeltaExchangeClient(api_key=api_key, api_secret=api_secret)

    headers = delta.get_auth_headers("GET", "/v2/wallet/balances", timestamp="1700000000")

    assert headers["api-key"] == api_key
    assert "signature" in headers
    assert len(headers["signature"]) == 64
    assert headers["timestamp"] == "1700000000"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_authenticated_get_profile_success_mocked():
    """
    Verify authenticated read-only GET /v2/profile with mocked 200 response.
    """
    api_key = "test_key"
    api_secret = "test_secret"
    delta = DeltaExchangeClient(
        base_url="https://cdn-ind.testnet.deltaex.org",
        api_key=api_key,
        api_secret=api_secret,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {
            "id": 123456,
            "email": "trader@example.com",
            "country": "IND",
            "maker_commission_rate": "0.0002",
            "taker_commission_rate": "0.0005",
            "is_kyc_done": True,
        },
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        profile = await delta.get_profile()
        assert profile["success"] is True
        assert profile["result"]["id"] == 123456

        # Check call arguments
        call_args, call_kwargs = mock_get.call_args
        assert call_args[0] == "https://cdn-ind.testnet.deltaex.org/v2/profile"
        headers_sent = call_kwargs["headers"]
        assert headers_sent["api-key"] == api_key
        assert "signature" in headers_sent
        assert "timestamp" in headers_sent


@pytest.mark.asyncio
async def test_verify_authentication_401_unauthorized_safe_diagnostic():
    """
    Verify that on 401 Unauthorized, verify_authentication returns safe diagnostic
    guidance without exposing secrets.
    """
    delta = DeltaExchangeClient(api_key="bad_key", api_secret="bad_secret")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = '{"error": {"code": "signature_mismatch", "message": "Invalid signature"}}'

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        result = await delta.verify_authentication()
        assert result["success"] is False
        assert result["authenticated"] is False
        assert result["http_status"] == 401
        assert "401 Unauthorized" in result["diagnostic"]
        # Ensure secret is NOT in diagnostic
        assert "bad_secret" not in result["diagnostic"]


@pytest.mark.asyncio
async def test_verify_authentication_403_forbidden_ip_whitelist_diagnostic():
    """
    Verify that on 403 Forbidden, diagnostic explicitly notes IP Whitelist and permissions.
    """
    delta = DeltaExchangeClient(api_key="whitelisted_key", api_secret="secret")

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"error": {"code": "ip_restricted", "message": "IP not whitelisted"}}'

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        result = await delta.verify_authentication()
        assert result["success"] is False
        assert result["authenticated"] is False
        assert result["http_status"] == 403
        assert "IP Whitelist" in result["diagnostic"]
        assert "403 Forbidden" in result["diagnostic"]
        assert "secret" not in result["diagnostic"]


@pytest.mark.asyncio
async def test_verify_authentication_unconfigured_credentials():
    """
    Verify that when API key/secret are missing, it returns safe unconfigured status.
    """
    delta = DeltaExchangeClient(api_key="", api_secret="")
    result = await delta.verify_authentication()
    assert result["authenticated"] is False
    assert result["key_configured"] is False
    assert "missing" in result["diagnostic"]


def test_api_auth_status_endpoint():
    """
    Test GET /api/v1/account/auth-status endpoint.
    """
    with patch("app.exchanges.delta_client.delta_client.verify_authentication", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = {
            "success": True,
            "authenticated": True,
            "endpoint_tested": "/v2/profile",
            "http_status": 200,
            "environment": "testnet",
            "base_url": "https://cdn-ind.testnet.deltaex.org",
            "key_configured": True,
            "masked_key": "dem...999",
            "diagnostic": "Authentication successful",
            "account_info": {"user_id": 999, "status": "active"},
        }

        res = client.get("/api/v1/account/auth-status")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["auth"]["authenticated"] is True
        assert body["auth"]["masked_key"] == "dem...999"
