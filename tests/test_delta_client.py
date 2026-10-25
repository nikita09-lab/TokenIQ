import pytest
from app.exchanges.delta_client import DeltaExchangeClient


def test_parse_ticker_valid():
    client = DeltaExchangeClient()
    raw = {
        "symbol": "BTCUSD",
        "close": 82000.5,
        "high": 83000.0,
        "low": 81000.0,
        "volume": 15000.0,
        "ltp_change_24h": "2.5",
        "mark_price": "82010.0",
        "spot_price": "82005.0",
        "funding_rate": "0.01",
        "quotes": {
            "best_bid": "82000.0",
            "best_ask": "82001.0",
        },
        "contract_type": "perpetual_futures",
    }
    parsed = client.parse_ticker(raw)
    assert parsed is not None
    assert parsed["symbol"] == "BTCUSD"
    assert parsed["last_price"] == 82000.5
    assert parsed["change_24h"] == 2.5
    assert parsed["high_24h"] == 83000.0
    assert parsed["low_24h"] == 81000.0
    assert parsed["best_bid"] == 82000.0
    assert parsed["best_ask"] == 82001.0
    assert parsed["base_asset"] == "BTC"
    assert parsed["quote_asset"] == "USD"


def test_parse_ticker_invalid_missing_symbol():
    client = DeltaExchangeClient()
    raw = {"close": 100.0}
    assert client.parse_ticker(raw) is None


def test_parse_ticker_invalid_missing_close():
    client = DeltaExchangeClient()
    raw = {"symbol": "BTCUSD", "close": None}
    assert client.parse_ticker(raw) is None


def test_get_resolution_seconds():
    client = DeltaExchangeClient()
    assert client.get_resolution_seconds("1m") == 60
    assert client.get_resolution_seconds("5m") == 300
    assert client.get_resolution_seconds("15m") == 900
    assert client.get_resolution_seconds("1h") == 3600
    assert client.get_resolution_seconds("1d") == 86400
