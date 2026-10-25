import pytest
from app.services.websocket_manager import WebSocketManager


def test_websocket_manager_initialization():
    manager = WebSocketManager()
    assert len(manager.active_clients) == 0
    assert manager.is_running is False
    assert manager.upstream_connected is False


@pytest.mark.asyncio
async def test_websocket_manager_subscribe_tracking():
    manager = WebSocketManager()
    # Mock message
    msg = '{"type": "subscribe", "payload": {"channels": [{"name": "ticker", "symbols": ["BTCUSD", "ETHUSD"]}]}}'

    class DummyWS:
        pass

    dummy = DummyWS()
    await manager.handle_client_message(dummy, msg)

    assert "ticker" in manager.subscribed_channels
    assert "BTCUSD" in manager.subscribed_channels["ticker"]
    assert "ETHUSD" in manager.subscribed_channels["ticker"]


@pytest.mark.asyncio
async def test_websocket_manager_ping_pong():
    """Verify that client ping receives pong."""
    manager = WebSocketManager()
    sent_messages = []

    class MockClientWS:
        async def send_text(self, text: str):
            sent_messages.append(text)

    client = MockClientWS()
    await manager.handle_client_message(client, '{"type": "ping"}')
    assert len(sent_messages) == 1
    assert '"type": "pong"' in sent_messages[0]


@pytest.mark.asyncio
async def test_websocket_manager_unsubscribe():
    """Verify unsubscription removes symbols from registry."""
    manager = WebSocketManager()
    manager.subscribed_channels = {"candlestick_1m": {"BTCUSD", "ETHUSD"}}

    class MockClientWS:
        pass

    unsub_msg = '{"type": "unsubscribe", "payload": {"channels": [{"name": "candlestick_1m", "symbols": ["ETHUSD"]}]}}'
    await manager.handle_client_message(MockClientWS(), unsub_msg)

    assert "ETHUSD" not in manager.subscribed_channels["candlestick_1m"]
    assert "BTCUSD" in manager.subscribed_channels["candlestick_1m"]


@pytest.mark.asyncio
async def test_websocket_manager_broadcast_to_clients():
    """Verify broadcast sends message to all active clients."""
    manager = WebSocketManager()
    received = []

    class MockClientWS:
        async def send_text(self, text: str):
            received.append(text)

    c1 = MockClientWS()
    c2 = MockClientWS()
    manager.active_clients.add(c1)
    manager.active_clients.add(c2)

    await manager.broadcast_to_clients('{"type": "candlestick_1m", "close": 82000.0}')
    assert len(received) == 2
    assert "82000.0" in received[0]
    assert "82000.0" in received[1]

