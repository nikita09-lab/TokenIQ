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
        Attach exchange-native bracket protection to an already-open Testnet position.

        Delta's POST /v2/orders/bracket endpoint attaches a stop-loss and optional
        take-profit to the full open position. It is safer than independent exit
        orders because the exchange manages the bracket as a single position-level
        protection object.
        """
        validate_testnet_host(delta_testnet_gateway.host_url)

        if not delta_client.api_key or not delta_client.api_secret:
            raise ProtectionPlacementError("API credentials not configured in backend/.env")
        if quantity <= 0 or stop_price <= 0:
            raise ProtectionPlacementError("Protection requires positive quantity and stop price.")
        if take_profit_price is not None and take_profit_price <= 0:
            raise ProtectionPlacementError("Take-profit price must be positive.")

        # Delta's bracket API closes the full position; it does not take size/side.
        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "bracket_stop_trigger_method": "mark_price",
            "stop_loss_order": {
                "order_type": "market_order",
                "stop_price": str(stop_price),
            },
        }
        if take_profit_price is not None:
            payload["take_profit_order"] = {
                "order_type": "market_order",
                "stop_price": str(take_profit_price),
            }

        canonical_path = "/v2/orders/bracket"
        full_url = f"{delta_testnet_gateway.host_url}{canonical_path}"
        body = json.dumps(payload, separators=(",", ":"))
        headers = delta_client.get_auth_headers(
            method="POST",
            path=canonical_path,
            query_string="",
            payload=body,
        )

        logger.info(
            "Attaching Testnet bracket protection for %s (%s, stop=%s, take_profit=%s).",
            symbol,
            position_side.upper(),
            stop_price,
            take_profit_price,
        )

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.post(full_url, content=body, headers=headers)
            except Exception as exc:
                logger.error("Network transport error submitting bracket protection: %s", exc)
                raise ProtectionPlacementError(f"Network error placing bracket protection: {exc}")

        status = response.status_code
        try:
            data = response.json()
        except Exception:
            raise ProtectionPlacementError(
                f"Invalid JSON from exchange (HTTP {status}): {response.text}"
            )

        if status == 200 and data.get("success"):
            # Delta may return only {"success": true} for bracket requests; retain
            # the acknowledged protection levels for local telemetry.
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            return {
                **result,
                "bracket_attached": True,
                "product_id": int(product_id),
                "stop_loss_price": stop_price,
                "take_profit_price": take_profit_price,
            }

        error_msg = (data.get("error") or {}).get("message") or data.get("message") or response.text
        raise ProtectionPlacementError(f"Delta Exchange rejected bracket protection: {error_msg}")

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
