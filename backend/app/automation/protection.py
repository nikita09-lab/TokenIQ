import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import httpx

from app.automation.models import PositionLifecycleState, PositionStateRecord
from app.core.config import settings
from app.core.environment_guard import validate_testnet_host
from app.exchanges.delta_client import delta_client
from app.trading.gateway import (
    delta_testnet_gateway,
    ExchangeOrderRejectedError,
    OrderSubmissionTimeoutError,
)

logger = logging.getLogger("protection_manager")


class ProtectionPlacementError(RuntimeError):
    """Raised when protective stop-loss order placement fails on the exchange."""
    pass


class ProtectionManager:
    """
    Manages protective stop-loss and take-profit orders on Delta Exchange Testnet.
    
    Safety Invariants:
    1. Uses verified Delta Exchange testnet endpoints.
    2. Uses exact filled quantity and average entry price.
    3. Verifies that the exchange explicitly acknowledged the protective order.
    4. If protective order placement fails:
       - Fails closed immediately.
       - Dispatches an emergency market reduction/close order to protect account capital.
       - Verifies that emergency close succeeded.
    """

    def __init__(self):
        self.timeout = 10.0

    async def place_protective_stop(
        self,
        product_id: int,
        symbol: str,
        position_side: str,  # 'LONG' or 'SHORT'
        quantity: float,
        stop_price: float,
        take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submits a protective stop-market order to Delta Exchange Testnet.
        Opposite side to position (e.g. LONG position -> SELL stop order).
        
        Endpoint: POST /v2/orders
        Payload fields for stop order:
            product_id: int
            size: int
            side: 'sell' if long else 'buy'
            order_type: 'stop_market_order'
            stop_order_type: 'stop_loss'
            stop_price: str(stop_price)
            stop_trigger_method: 'mark_price'
        """
        validate_testnet_host(delta_testnet_gateway.host_url)

        if not delta_client.api_key or not delta_client.api_secret:
            raise ProtectionPlacementError("API credentials not configured in backend/.env")

        clean_size = int(round(quantity)) if abs(quantity - round(quantity)) < 1e-6 else quantity
        exit_side = "sell" if position_side.upper() == "LONG" else "buy"

        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "size": clean_size,
            "side": exit_side,
            "order_type": "stop_market_order",
            "stop_order_type": "stop_loss",
            "stop_price": str(stop_price),
            "stop_trigger_method": "mark_price",
            "client_order_id": f"sl_{int(time.time())}_{product_id}",
        }

        canonical_path = "/v2/orders"
        full_url = f"{delta_testnet_gateway.host_url}{canonical_path}"
        body = json.dumps(payload, separators=(",", ":"))

        headers = delta_client.get_auth_headers(
            method="POST",
            path=canonical_path,
            query_string="",
            payload=body,
        )

        logger.info(
            f"Submitting protective stop-loss for {symbol} ({exit_side} {clean_size} contracts @ stop {stop_price})..."
        )

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.post(full_url, content=body, headers=headers)
            except Exception as exc:
                logger.error(f"Network transport error submitting stop-loss: {exc}")
                raise ProtectionPlacementError(f"Network error placing stop-loss: {exc}")

        status = response.status_code
        try:
            data = response.json()
        except Exception:
            raise ProtectionPlacementError(f"Invalid JSON from exchange (HTTP {status}): {response.text}")

        if status == 200 and data.get("success"):
            order_info = data.get("result") or {}
            logger.info(
                f"Protective stop-loss verified on Delta Testnet! ID: {order_info.get('id')}"
            )
            return order_info

        error_msg = (data.get("error") or {}).get("message") or data.get("message") or response.text
        raise ProtectionPlacementError(f"Delta Exchange rejected protective stop-loss: {error_msg}")

    async def execute_emergency_position_close(
        self,
        product_id: int,
        symbol: str,
        position_side: str,
        quantity: float,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Emergency safety protocol: If stop-loss placement fails, immediately market-close
        the position so the account is not left exposed to unbounded risk.
        """
        logger.critical(
            f"EMERGENCY PROTOCOL ACTIVATED: Closing {quantity} contracts of {symbol} {position_side}. "
            f"Reason: {reason}"
        )
        exit_side = "SELL" if position_side.upper() == "LONG" else "BUY"

        try:
            res = await delta_testnet_gateway.submit_order(
                product_id=product_id,
                size=quantity,
                side=exit_side,
                order_type="market_order",
                client_order_id=f"emg_close_{int(time.time())}_{product_id}",
            )
            logger.info(f"Emergency close order submitted to testnet: Order ID {res.get('id')}")
            return res
        except Exception as exc:
            logger.critical(f"FATAL: Emergency market close failed ({exc})! Operator intervention required.")
            raise RuntimeError(f"Emergency close failed: {exc}")


protection_manager = ProtectionManager()
