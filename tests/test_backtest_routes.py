import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.exchanges.delta_client import delta_client

client = TestClient(app)


def test_get_backtest_config_options():
    response = client.get("/api/v1/backtesting/config-options")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    config = data["config"]
    assert "supported_resolutions" in config
    assert "default_initial_capital" in config
    assert "execution_modes" in config
    assert "DISCLAIMER" in config["disclaimer"]


@pytest.mark.asyncio
async def test_run_backtest_endpoint_success(monkeypatch):
    """Test running a backtest through FastAPI endpoint with synthetic candles."""
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0, 95.0, 90.0, 82.0]
    opens = [100.0 - i * 0.5 for i in range(30)] + [86.0, 88.0, 90.0, 93.0, 85.0]
    synthetic_candles = [
        {
            "time": 1700000000 + i * 3600,
            "open": float(opens[i]),
            "high": float(max(opens[i], p) * 1.01),
            "low": float(min(opens[i], p) * 0.99),
            "close": float(p),
            "volume": 1500.0,
        }
        for i, p in enumerate(prices)
    ]

    async def mock_candles(*args, **kwargs):
        return {
            "symbol": "BTCUSD",
            "resolution": "1h",
            "candles": synthetic_candles,
        }

    monkeypatch.setattr(delta_client, "get_historical_candles", mock_candles)

    payload = {
        "symbol": "BTCUSD",
        "resolution": "1h",
        "start_time": 1700000000,
        "end_time": 1700000000 + len(prices) * 3600,
        "initial_capital": 10000.0,
        "fee_rate": 0.0005,
        "slippage_rate": 0.0005,
        "execution_mode": "next_open",
        "strategy_params": {
            "fast_period": 3,
            "slow_period": 7,
            "rsi_period": 5,
            "rsi_filter_enabled": False,
        },
    }

    response = client.post("/api/v1/backtesting/run", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    res = data["result"]
    assert res["symbol"] == "BTCUSD"
    assert "metrics" in res
    assert "equity_curve" in res
    assert "trades" in res
    assert res["metrics"]["initial_capital"] == 10000.0
    assert len(res["equity_curve"]) == len(prices)

    # Test retrieving by backtest_id
    backtest_id = res["backtest_id"]
    get_res = client.get(f"/api/v1/backtesting/results/{backtest_id}")
    assert get_res.status_code == 200
    assert get_res.json()["result"]["backtest_id"] == backtest_id


def test_run_backtest_invalid_parameters():
    # 1. Non-positive initial capital
    res1 = client.post(
        "/api/v1/backtesting/run",
        json={"symbol": "BTCUSD", "initial_capital": -100.0},
    )
    assert res1.status_code in [400, 422]

    # 2. start_time >= end_time
    res2 = client.post(
        "/api/v1/backtesting/run",
        json={"symbol": "BTCUSD", "start_time": 1700010000, "end_time": 1700000000},
    )
    assert res2.status_code == 422
    assert "must be earlier" in res2.json()["detail"].lower()


def test_get_backtest_result_not_found():
    response = client.get("/api/v1/backtesting/results/nonexistent_bt_id_123")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
