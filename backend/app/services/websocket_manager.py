import asyncio
import json
import logging
from typing import Any, Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect
import websockets

from app.core.config import settings

logger = logging.getLogger("websocket_manager")


class WebSocketManager:
    """
    Manages client WebSocket connections from the frontend and bridges them
    to the upstream Delta Exchange public WebSocket feed.
    """

    def __init__(self):
        self.active_clients: Set[WebSocket] = set()
        self.subscribed_channels: Dict[str, Set[str]] = {}  # channel_name -> set of symbols
        self.upstream_ws: Any = None
        self.is_running: bool = False
        self._upstream_task: Any = None
        self._lock = asyncio.Lock()
        self.upstream_connected: bool = False

    async def start(self):
        """Start upstream WebSocket bridge."""
        if self.is_running:
            return
        self.is_running = True
        self._upstream_task = asyncio.create_task(self._upstream_loop())
        logger.info("WebSocketManager bridge started.")

    async def stop(self):
        """Stop upstream WebSocket bridge and disconnect all clients."""
        self.is_running = False
        if self._upstream_task:
            self._upstream_task.cancel()
            try:
                await self._upstream_task
            except asyncio.CancelledError:
                pass

        if self.upstream_ws:
            try:
                await self.upstream_ws.close()
            except Exception:
                pass

        for client in list(self.active_clients):
            try:
                await client.close()
            except Exception:
                pass
        self.active_clients.clear()
        logger.info("WebSocketManager stopped.")

    async def connect_client(self, websocket: WebSocket):
        """Accept a new frontend client WebSocket connection."""
        await websocket.accept()
        self.active_clients.add(websocket)
        logger.info(f"Frontend client connected. Total clients: {len(self.active_clients)}")

        # Send initial status handshake
        await self.send_to_client(
            websocket,
            {
                "type": "connection_status",
                "status": "connected" if self.upstream_connected else "connecting",
                "message": "Connected to TokenIQ Backend Market Bridge",
            },
        )

    def disconnect_client(self, websocket: WebSocket):
        """Remove a disconnected frontend client."""
        self.active_clients.discard(websocket)
        logger.info(f"Frontend client disconnected. Remaining clients: {len(self.active_clients)}")

    async def send_to_client(self, websocket: WebSocket, data: Dict[str, Any]):
        """Send JSON message to a specific client safely."""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            self.disconnect_client(websocket)

    async def broadcast_to_clients(self, message_str: str):
        """Broadcast raw or normalized JSON message to all connected clients."""
        if not self.active_clients:
            return

        dead_clients = []
        for client in self.active_clients:
            try:
                await client.send_text(message_str)
            except Exception:
                dead_clients.append(client)

        for client in dead_clients:
            self.disconnect_client(client)

    async def handle_client_message(self, websocket: WebSocket, message_text: str):
        """Handle incoming message from a frontend client (subscribe, unsubscribe, ping)."""
        try:
            msg = json.loads(message_text)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await self.send_to_client(websocket, {"type": "pong"})
                return

            if msg_type in ("subscribe", "unsubscribe"):
                payload = msg.get("payload") or {}
                channels = payload.get("channels") or []

                for ch in channels:
                    ch_name = ch.get("name")
                    symbols = ch.get("symbols") or []
                    if not ch_name or not symbols:
                        continue

                    if msg_type == "subscribe":
                        if ch_name not in self.subscribed_channels:
                            self.subscribed_channels[ch_name] = set()
                        self.subscribed_channels[ch_name].update(symbols)
                    elif msg_type == "unsubscribe":
                        if ch_name in self.subscribed_channels:
                            self.subscribed_channels[ch_name].difference_update(symbols)

                # Forward subscription to upstream Delta Exchange socket if connected
                if self.upstream_ws and self.upstream_connected:
                    try:
                        await self.upstream_ws.send(message_text)
                    except Exception as exc:
                        logger.warning(f"Error forwarding subscription to Delta WS: {exc}")

        except json.JSONDecodeError:
            logger.warning(f"Malformed JSON received from client: {message_text[:100]}")
        except Exception as exc:
            logger.error(f"Error handling client message: {exc}")

    async def _resubscribe_all_upstream(self):
        """Resubscribe all registered channels upon upstream reconnection."""
        if not self.upstream_ws or not self.upstream_connected:
            return

        for ch_name, symbols in self.subscribed_channels.items():
            if not symbols:
                continue
            payload = {
                "type": "subscribe",
                "payload": {
                    "channels": [
                        {
                            "name": ch_name,
                            "symbols": list(symbols),
                        }
                    ]
                },
            }
            try:
                await self.upstream_ws.send(json.dumps(payload))
            except Exception as exc:
                logger.warning(f"Error sending resubscription to Delta WS: {exc}")

    async def _upstream_loop(self):
        """Persistent background worker maintaining connection to Delta Exchange WebSocket."""
        # Yield to allow FastAPI and Uvicorn to finish startup banner first
        await asyncio.sleep(0.3)

        upstream_urls = [
            settings.DELTA_WS_URL,
            "wss://socket.india.delta.exchange",
        ]
        # Deduplicate while preserving order
        upstream_urls = list(dict.fromkeys(upstream_urls))

        reconnect_delay = 1.0
        max_reconnect_delay = 15.0
        url_idx = 0

        while self.is_running:
            target_url = upstream_urls[url_idx % len(upstream_urls)]
            try:
                logger.info(f"Connecting to Delta Exchange WebSocket: {target_url}")
                async with websockets.connect(
                    target_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self.upstream_ws = ws
                    self.upstream_connected = True
                    reconnect_delay = 1.0
                    logger.info("Connected to Delta Exchange WebSocket.")

                    # Notify frontend clients
                    await self.broadcast_to_clients(
                        json.dumps({
                            "type": "connection_status",
                            "status": "connected",
                            "message": "Live feed connected to Delta Exchange",
                        })
                    )

                    # Restore subscriptions
                    await self._resubscribe_all_upstream()

                    # Start application-level heartbeat ping to Delta Exchange
                    async def _send_upstream_pings():
                        while self.is_running and self.upstream_connected and ws:
                            try:
                                await asyncio.sleep(20)
                                if self.upstream_connected and ws:
                                    await ws.send(json.dumps({"type": "ping"}))
                            except Exception:
                                break

                    ping_task = asyncio.create_task(_send_upstream_pings())

                    try:
                        async for message in ws:
                            if not self.is_running:
                                break
                            # Consume upstream heartbeat pong
                            if '"type":"pong"' in message or '"type": "pong"' in message:
                                continue
                            # Broadcast directly to all frontend clients
                            await self.broadcast_to_clients(message)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.upstream_connected = False
                self.upstream_ws = None
                err_str = str(exc)
                if "getaddrinfo" in err_str or "11001" in err_str:
                    reason = "Exchange DNS resolution offline or temporary lookup failure"
                elif "refused" in err_str.lower():
                    reason = "Exchange socket connection refused"
                elif "timed out" in err_str.lower():
                    reason = "Exchange socket connection timed out"
                else:
                    reason = err_str

                logger.warning(
                    f"Upstream exchange WebSocket disconnected ({reason}). "
                    f"Retrying in {int(reconnect_delay)}s. REST API endpoints remain operational."
                )
                await self.broadcast_to_clients(
                    json.dumps({
                        "type": "connection_status",
                        "status": "connecting",
                        "message": f"Reconnecting to exchange in {int(reconnect_delay)}s...",
                    })
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                url_idx += 1


websocket_manager = WebSocketManager()

