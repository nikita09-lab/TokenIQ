"""
Tests for TokenIQ Production Deployment and CORS Configuration.

Validates:
1. Exact Vercel origins permitted with credentials.
2. Unapproved origins rejected (no Access-Control-Allow-Origin returned).
3. CORS preflight OPTIONS requests handled properly.
4. Parsing logic for CORS_ORIGINS (comma separation, trailing slashes stripped, whitespace ignored).
5. WebSocket origin validation (approved vs unapproved origins).
6. Health-check endpoints (/health and /api/v1/health).
7. Trading safety invariants (automation remains OFF on startup).
8. Delta Exchange testnet enforcement remains active.
"""

import pytest
from starlette.testclient import TestClient

from app.core.config import clean_origin, parse_cors_origins, settings
from app.core.environment_guard import EnvironmentSafetyViolation, validate_testnet_host
from app.main import app

VERCEL_ORIGINS = [
    "https://token-iq.vercel.app",
    "https://token-iq-git-main-nikita-santosh-mishras-projects.vercel.app",
    "https://token-rdmzzyx38-nikita-santosh-mishras-projects.vercel.app",
]

UNAPPROVED_ORIGIN = "https://unauthorized-malicious-site.com"


@pytest.fixture
def client():
    return TestClient(app)


def test_cors_origins_parsing_sanitization():
    """Verify comma-separated origins are trimmed, slashes stripped, and empty entries dropped."""
    raw = " https://token-iq.vercel.app/ , , https://token-iq-git-main-nikita-santosh-mishras-projects.vercel.app/ , https://token-rdmzzyx38-nikita-santosh-mishras-projects.vercel.app "
    parsed = parse_cors_origins(raw, "production", merge_defaults=False)

    assert parsed == [
        "https://token-iq.vercel.app",
        "https://token-iq-git-main-nikita-santosh-mishras-projects.vercel.app",
        "https://token-rdmzzyx38-nikita-santosh-mishras-projects.vercel.app",
    ]
    # No trailing slashes
    for origin in parsed:
        assert not origin.endswith("/")


def test_cors_origins_parsing_production_fallback():
    """Verify that when raw is None or empty in production, it falls back to the 3 exact Vercel domains."""
    parsed = parse_cors_origins(None, "production", merge_defaults=False)
    assert parsed == VERCEL_ORIGINS

    parsed_empty = parse_cors_origins("   ", "production", merge_defaults=False)
    assert parsed_empty == VERCEL_ORIGINS


def test_clean_origin_rejects_invalid():
    """Verify clean_origin rejects non-web schemes and root slashes."""
    assert clean_origin("javascript:alert(1)") is None
    assert clean_origin("/") is None
    assert clean_origin("   ") is None
    assert clean_origin("https://valid-domain.com/") == "https://valid-domain.com"


@pytest.mark.parametrize("origin", VERCEL_ORIGINS)
def test_each_vercel_origin_allowed(client, origin):
    """Verify each configured Vercel origin receives CORS approval with credentials."""
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_unapproved_origin_rejected(client):
    """Verify unapproved origins do NOT receive access-control-allow-origin header."""
    response = client.get("/health", headers={"Origin": UNAPPROVED_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("origin", VERCEL_ORIGINS)
def test_cors_preflight_options_request(client, origin):
    """Verify preflight OPTIONS requests return 200 and required CORS headers."""
    response = client.options(
        "/api/v1/market/status",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"
    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "POST" in allowed_methods
    assert "OPTIONS" in allowed_methods


def test_cors_preflight_unapproved_origin(client):
    """Verify preflight OPTIONS requests from unapproved origins do not get allowed."""
    response = client.options(
        "/api/v1/market/status",
        headers={
            "Origin": UNAPPROVED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_health_check_endpoints(client):
    """Verify root /health and /api/v1/health endpoints return healthy status."""
    res_root = client.get("/health")
    assert res_root.status_code == 200
    data_root = res_root.json()
    assert data_root["status"] in ("healthy", "ok")
    assert data_root["testnet_enforced"] is True

    res_api = client.get("/api/v1/health")
    assert res_api.status_code == 200
    data_api = res_api.json()
    assert data_api["status"] in ("healthy", "ok")


def test_websocket_origin_allowed(client):
    """Verify WebSocket connection succeeds when origin is an approved Vercel domain."""
    with client.websocket_connect(
        "/api/v1/market/ws",
        headers={"Origin": "https://token-iq.vercel.app"},
    ) as ws:
        # Connected successfully
        assert ws is not None


def test_websocket_origin_unapproved_rejected(client):
    """Verify WebSocket connection is closed/rejected when origin is unauthorized."""
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/api/v1/market/ws",
            headers={"Origin": UNAPPROVED_ORIGIN},
        ):
            pass


def test_trading_safety_automation_off_by_default(client):
    """Safety check: automation must remain OFF and disabled on startup."""
    response = client.get("/api/v1/automation/status")
    assert response.status_code == 200
    data = response.json()
    assert data.get("enabled") is False
    assert data.get("state") in ("OFF", "STOPPED")


def test_testnet_enforcement_intact():
    """Safety check: Delta Exchange host must be testnet, and production host must be blocked."""
    assert settings.is_testnet is True
    # Validating current configured host does not raise
    validate_testnet_host(settings.DELTA_API_URL)

    # Attempting to validate a production exchange host MUST raise violation error
    with pytest.raises(EnvironmentSafetyViolation):
        validate_testnet_host("https://api.india.delta.exchange")
