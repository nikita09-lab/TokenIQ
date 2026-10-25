import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.exchanges.delta_client import delta_client

client = TestClient(app)


def test_list_strategies_endpoint():
    response = client.get("/api/v1/strategies")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["count"] >= 1
    ids = [s["strategy_id"] for s in data["strategies"]]
    assert "ema_crossover" in ids
    # Verify disclaimer is present
    assert "DISCLAIMER" in data["strategies"][0]["disclaimer"]


def test_get_strategy_details_endpoint():
    response = client.get("/api/v1/strategies/ema_crossover")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["strategy_id"] == "ema_crossover"
    assert "schema" in data
    assert "current_parameters" in data


def test_get_strategy_not_found():
    response = client.get("/api/v1/strategies/unknown_strategy_xyz")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_configure_strategy_valid():
    response = client.post(
        "/api/v1/strategies/ema_crossover/configure",
        json={"parameters": {"fast_period": 8, "slow_period": 24, "rsi_period": 14}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["updated_parameters"]["fast_period"] == 8
    assert data["updated_parameters"]["slow_period"] == 24


def test_configure_strategy_invalid_fast_greater_than_slow():
    response = client.post(
        "/api/v1/strategies/ema_crossover/configure",
        json={"parameters": {"fast_period": 30, "slow_period": 20}},
    )
    assert response.status_code == 422
    assert "strictly less than" in response.json()["detail"]


def test_signal_endpoint_validation_errors():
    # 1. Invalid short symbol
    res1 = client.post(
        "/api/v1/strategies/ema_crossover/signal",
        json={"symbol": "B", "resolution": "1h"},
    )
    assert res1.status_code == 400

    # 2. Invalid resolution
    res2 = client.post(
        "/api/v1/strategies/ema_crossover/signal",
        json={"symbol": "BTCUSD", "resolution": "99min"},
    )
    assert res2.status_code == 400

    # 3. Unknown strategy
    res3 = client.post(
        "/api/v1/strategies/phantom_strategy/signal",
        json={"symbol": "BTCUSD", "resolution": "1h"},
    )
    assert res3.status_code == 404


@pytest.mark.asyncio
async def test_signal_generation_with_synthetic_candles(monkeypatch):
    """Mock delta_client with synthetic candles to test full endpoint execution cleanly."""
    prices = [100.0 + i for i in range(50)]
    synthetic_candles = [
        {
            "time": 1700000000 + i * 3600,
            "open": p * 0.99,
            "high": p * 1.01,
            "low": p * 0.98,
            "close": float(p),
            "volume": 1200.0,
        }
        for i, p in enumerate(prices)
    ]

    async def mock_candles(symbol, resolution="1h", start=None, end=None):
        return {
            "symbol": symbol,
            "resolution": resolution,
            "candles": synthetic_candles,
        }

    monkeypatch.setattr(delta_client, "get_historical_candles", mock_candles)

    # Test POST endpoint
    res_post = client.post(
        "/api/v1/strategies/ema_crossover/signal",
        json={"symbol": "BTCUSD", "resolution": "1h"},
    )
    assert res_post.status_code == 200
    data = res_post.json()
    assert data["success"] is True
    sig = data["signal"]
    assert sig["symbol"] == "BTCUSD"
    assert sig["signal"] in ["BUY", "SELL", "HOLD"]
    assert sig["position_intent"] in [
        "OPEN_LONG",
        "CLOSE_LONG",
        "OPEN_SHORT",
        "CLOSE_LONG_OR_OPEN_SHORT",
        "NO_ACTION",
    ]
    assert "disclaimer" in sig
    assert sig["fast_ema"] is not None
    assert sig["slow_ema"] is not None

    # Test GET convenience endpoint
    res_get = client.get("/api/v1/strategies/ema_crossover/signal?symbol=BTCUSD&resolution=1h")
    assert res_get.status_code == 200
    assert res_get.json()["success"] is True

    # Test latest-signal retrieval endpoint
    res_latest = client.get("/api/v1/strategies/ema_crossover/latest-signal?symbol=BTCUSD")
    assert res_latest.status_code == 200
    assert res_latest.json()["signal"]["symbol"] == "BTCUSD"


@pytest.mark.asyncio
async def test_signal_generation_insufficient_exchange_candles(monkeypatch):
    """When exchange returns too few candles, API returns 422 Unprocessable Entity."""
    async def mock_short_candles(symbol, resolution="1h", start=None, end=None):
        return {
            "symbol": symbol,
            "resolution": resolution,
            "candles": [
                {"time": 1700000000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}
            ],
        }

    monkeypatch.setattr(delta_client, "get_historical_candles", mock_short_candles)

    response = client.post(
        "/api/v1/strategies/ema_crossover/signal",
        json={"symbol": "BTCUSD", "resolution": "1h"},
    )
    assert response.status_code == 422
    assert "insufficient" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signal_generation_exchange_downtime_error(monkeypatch):
    """When exchange client fails, API returns 502 Bad Gateway."""
    async def mock_error(*args, **kwargs):
        raise ConnectionError("Exchange network timeout")

    monkeypatch.setattr(delta_client, "get_historical_candles", mock_error)

    response = client.post(
        "/api/v1/strategies/ema_crossover/signal",
        json={"symbol": "BTCUSD", "resolution": "1h"},
    )
    assert response.status_code == 502
    assert "Delta Exchange market data error" in response.json()["detail"]
