import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings
from app.core.environment_guard import validate_testnet_host, EnvironmentSafetyViolation
from app.exchanges.delta_client import delta_client

logger = logging.getLogger("delta_testnet_gateway")


class OrderSubmissionTimeoutError(RuntimeError):
    """
    Raised when an order submission times out or disconnects mid-flight.
    This creates an UNKNOWN state that requires reconciliation before retry.
    """
    def __init__(self, client_order_id: str, message: str):
        super().__init__(message)
        self.client_order_id = client_order_id


class ExchangeOrderRejectedError(RuntimeError):
    """Raised when Delta Exchange explicitly rejects an order (e.g. margin, bounds)."""
    def __init__(self, message: str, code: Optional[str] = None, http_status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class DeltaTestnetOrderGateway:
    """
    Secure gateway for placing, checking, and cancelling orders strictly on Delta Exchange Testnet.
    Enforces testnet validation on every single HTTP request.
    """

    def __init__(self):
        self.timeout = 10.0

    @property
    def host_url(self) -> str:
        return delta_client.host_url

    def _assert_testnet_safe(self) -> str:
        """Enforce verified testnet host before any exchange interaction."""
        return validate_testnet_host(self.host_url)

    def _sanitize_error_text(self, text: str) -> str:
        """Sanitize error messages to ensure API keys/secrets are never exposed."""
        if not text:
            return "Unknown exchange error"
        sanitized = text
        if settings.DELTA_API_SECRET and len(settings.DELTA_API_SECRET) > 4:
            sanitized = sanitized.replace(settings.DELTA_API_SECRET, "[REDACTED_SECRET]")
        if settings.DELTA_API_KEY and len(settings.DELTA_API_KEY) > 4:
            sanitized = sanitized.replace(settings.DELTA_API_KEY, "[REDACTED_KEY]")
        return sanitized

    async def submit_order(
        self,
        product_id: int,
        size: float,
        side: str,
        order_type: str,
        limit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        stop_loss_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit a new order to Delta Exchange Testnet.
        Endpoint: POST /v2/orders
        
        Raises:
            OrderSubmissionTimeoutError: if request timed out (resulting in UNKNOWN state).
            ExchangeOrderRejectedError: if exchange responded with error or rejection.
            EnvironmentSafetyViolation: if configured URL is not verified testnet.
        """
        # 1. Enforce Testnet Guardrail
        self._assert_testnet_safe()

        if not delta_client.api_key or not delta_client.api_secret:
            raise RuntimeError("Exchange API credentials are not configured in backend/.env")

        # 2. Build official Delta payload
        # On Delta Exchange, contract size is integer count for futures
        clean_size = int(round(size)) if abs(size - round(size)) < 1e-6 else size
        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "size": clean_size,
            "side": side.lower(),
            "order_type": order_type,
        }

        if order_type == "limit_order":
            if limit_price is None or limit_price <= 0:
                raise ValueError("Limit orders require a valid positive limit_price.")
            payload["limit_price"] = str(limit_price)

        if client_order_id:
            payload["client_order_id"] = str(client_order_id)

        canonical_path = "/v2/orders"
        full_url = f"{self.host_url}{canonical_path}"
        body = json.dumps(payload, separators=(",", ":"))

        # 3. Build authenticated headers
        headers = delta_client.get_auth_headers(
            method="POST",
            path=canonical_path,
            query_string="",
            payload=body,
        )

        # 4. Dispatch request with strict no-redirect and timeout handling
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.post(full_url, content=body, headers=headers)
            except httpx.TimeoutException as exc:
                logger.error(
                    f"Timeout submitting order client_order_id={client_order_id} to testnet: {exc}"
                )
                raise OrderSubmissionTimeoutError(
                    client_order_id=client_order_id or "unknown",
                    message=f"Exchange order submission timed out after {self.timeout}s. State is UNKNOWN pending reconciliation.",
                )
            except httpx.RequestError as exc:
                logger.error(f"Network transport error submitting order to testnet: {exc}")
                raise OrderSubmissionTimeoutError(
                    client_order_id=client_order_id or "unknown",
                    message=f"Network error during order submission: {exc}. State is UNKNOWN pending reconciliation.",
                )

        # 5. Process exchange response
        status = response.status_code
        try:
            data = response.json()
        except Exception:
            raw_text = self._sanitize_error_text(response.text)
            raise ExchangeOrderRejectedError(
                message=f"Invalid JSON received from Delta Exchange (HTTP {status}): {raw_text}",
                http_status=status,
            )

        if status == 200 and data.get("success"):
            logger.info(
                f"Order successfully submitted to Delta Testnet! Exchange Order ID: {data.get('result', {}).get('id')}"
            )
            return data.get("result") or {}

        # Handle rejection
        error_info = data.get("error") or {}
        err_msg = self._sanitize_error_text(error_info.get("message") or data.get("message") or response.text)
        err_code = error_info.get("code")
        logger.warning(f"Delta Testnet rejected order submission (HTTP {status}): {err_msg} (code={err_code})")
        raise ExchangeOrderRejectedError(
            message=f"Delta Exchange rejected order: {err_msg}",
            code=err_code,
            http_status=status,
        )

    async def cancel_order(self, product_id: int, order_id: str) -> Dict[str, Any]:
        """
        Cancel an open order on Delta Exchange Testnet.
        Endpoint: DELETE /v2/orders
        """
        self._assert_testnet_safe()

        try:
            numeric_order_id = int(order_id)
        except ValueError:
            numeric_order_id = order_id

        payload = {
            "product_id": int(product_id),
            "id": numeric_order_id,
        }

        canonical_path = "/v2/orders"
        full_url = f"{self.host_url}{canonical_path}"
        body = json.dumps(payload, separators=(",", ":"))

        headers = delta_client.get_auth_headers(
            method="DELETE",
            path=canonical_path,
            query_string="",
            payload=body,
        )

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.request("DELETE", full_url, content=body, headers=headers)
            except Exception as exc:
                raise RuntimeError(f"Network error while cancelling order {order_id}: {exc}")

        status = response.status_code
        try:
            data = response.json()
        except Exception:
            raise RuntimeError(f"Failed to cancel order (HTTP {status}): {self._sanitize_error_text(response.text)}")

        if status == 200 and data.get("success"):
            logger.info(f"Order {order_id} successfully cancelled on Delta Testnet.")
            return data.get("result") or {}

        error_info = data.get("error") or {}
        err_msg = self._sanitize_error_text(error_info.get("message") or data.get("message") or response.text)
        raise RuntimeError(f"Failed to cancel order {order_id} on Delta Testnet: {err_msg}")

    async def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve order status directly from Delta Exchange.
        Endpoint: GET /v2/orders/{order_id}
        """
        self._assert_testnet_safe()

        canonical_path = f"/v2/orders/{order_id}"
        full_url = f"{self.host_url}{canonical_path}"

        headers = delta_client.get_auth_headers(
            method="GET",
            path=canonical_path,
            query_string="",
            payload="",
        )

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.get(full_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("result")
                try:
                    err_json = response.json()
                    err_code = (err_json.get("error") or {}).get("code")
                    if err_code == "order_not_found":
                        logger.info(f"Order {order_id} conclusively reported not found by exchange.")
                        return {"_not_found_on_exchange": True}
                except Exception:
                    pass
                return None
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.error(f"Network transport error querying order {order_id}: {exc}")
                raise exc
            except Exception as exc:
                logger.warning(f"Failed to fetch order {order_id} from exchange: {exc}")
                raise exc

    async def list_open_orders(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all active/open orders from Delta Exchange Testnet.
        Endpoint: GET /v2/orders?states=open,pending
        """
        self._assert_testnet_safe()
        return await delta_client.get_open_orders(product_id=product_id)


delta_testnet_gateway = DeltaTestnetOrderGateway()
