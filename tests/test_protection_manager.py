import json
from unittest.mock import patch

import pytest

from app.automation.protection import ProtectionManager


class FakeResponse:
    status_code = 200
    text = '{"success": true}'

    def json(self):
        return {"success": True}


class FakeAsyncClient:
    last_request = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, content, headers):
        FakeAsyncClient.last_request = {
            "url": url,
            "body": json.loads(content),
            "headers": headers,
        }
        return FakeResponse()


@pytest.mark.asyncio
async def test_protection_uses_delta_bracket_with_stop_and_take_profit(monkeypatch):
    from app.automation import protection

    monkeypatch.setattr(protection.delta_client, "api_key", "test-key")
    monkeypatch.setattr(protection.delta_client, "api_secret", "test-secret")
    monkeypatch.setattr(
        protection.delta_client, "get_auth_headers", lambda **kwargs: {"signature": "test"}
    )
    monkeypatch.setattr(protection.httpx, "AsyncClient", FakeAsyncClient)

    manager = ProtectionManager()
    result = await manager.place_protective_stop(
        product_id=27,
        symbol="BTCUSD",
        position_side="LONG",
        quantity=1,
        stop_price=98000,
        take_profit_price=104000,
    )

    request = FakeAsyncClient.last_request
    assert request["url"].endswith("/v2/orders/bracket")
    assert request["body"]["product_id"] == 27
    assert request["body"]["bracket_stop_trigger_method"] == "mark_price"
    assert request["body"]["stop_loss_order"] == {
        "order_type": "market_order",
        "stop_price": "98000",
    }
    assert request["body"]["take_profit_order"] == {
        "order_type": "market_order",
        "stop_price": "104000",
    }
    assert result["bracket_attached"] is True
    assert result["take_profit_price"] == 104000


@pytest.mark.asyncio
async def test_protection_can_attach_stop_without_take_profit(monkeypatch):
    from app.automation import protection

    monkeypatch.setattr(protection.delta_client, "api_key", "test-key")
    monkeypatch.setattr(protection.delta_client, "api_secret", "test-secret")
    monkeypatch.setattr(
        protection.delta_client, "get_auth_headers", lambda **kwargs: {"signature": "test"}
    )
    monkeypatch.setattr(protection.httpx, "AsyncClient", FakeAsyncClient)

    manager = ProtectionManager()
    await manager.place_protective_stop(
        product_id=27,
        symbol="BTCUSD",
        position_side="LONG",
        quantity=1,
        stop_price=98000,
        take_profit_price=None,
    )
    request = FakeAsyncClient.last_request
    assert "stop_loss_order" in request["body"]
    assert "take_profit_order" not in request["body"]
