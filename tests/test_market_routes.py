import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "TokenIQ"


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_market_status():
    response = client.get("/api/v1/market/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"


def test_get_tickers_structure():
    response = client.get("/api/v1/market/tickers")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["result"], list)
    if data["result"]:
        first = data["result"][0]
        assert "symbol" in first
        assert "last_price" in first


def test_get_stats_structure():
    response = client.get("/api/v1/market/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    res = data["result"]
    assert "total_trading_pairs" in res
    assert "active_perpetuals" in res
