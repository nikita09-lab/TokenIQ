import hashlib
import hmac
import logging
import math
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import httpx

from app.core.config import settings

logger = logging.getLogger("delta_client")


class DeltaExchangeClient:
    """
    Client for Delta Exchange (India exchange API & Testnet).
    Supports public market data and HMAC-SHA256 signed authenticated read-only account requests.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        raw_url = (base_url or settings.DELTA_API_URL).rstrip("/")
        # Normalize host URL (strip trailing /v2 if present for clean canonical path resolution)
        if raw_url.endswith("/v2"):
            self.host_url = raw_url[:-3]
        else:
            self.host_url = raw_url

        self.base_url = f"{self.host_url}/v2"
        self.timeout = timeout or settings.REQUEST_TIMEOUT_SECONDS
        self.api_key = api_key if api_key is not None else settings.DELTA_API_KEY
        self.api_secret = api_secret if api_secret is not None else settings.DELTA_API_SECRET

        self._server_time_offset: int = 0
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "TokenIQ-Dashboard/1.0 (+https://github.com/tokeniq)",
        }
        self._account_overview_cache: Optional[Tuple[Dict[str, Any], float]] = None

    def _resolve_url(self, endpoint: str) -> Tuple[str, str]:
        """
        Resolve (canonical_path, full_url) ensuring /v2 prefix is consistently present.
        Example: '/tickers' -> ('/v2/tickers', 'https://cdn-ind.testnet.deltaex.org/v2/tickers')
                 '/v2/profile' -> ('/v2/profile', 'https://cdn-ind.testnet.deltaex.org/v2/profile')
        """
        cleaned = endpoint.strip()
        if not cleaned.startswith("/"):
            cleaned = "/" + cleaned
        if not cleaned.startswith("/v2/"):
            canonical_path = f"/v2{cleaned}"
        else:
            canonical_path = cleaned
        full_url = f"{self.host_url}{canonical_path}"
        return canonical_path, full_url

    def generate_signature(
        self,
        method: str,
        path: str,
        query_string: str = "",
        payload: str = "",
        timestamp: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generate HMAC-SHA256 signature for Delta Exchange API authentication.
        
        Formula:
            Signature Data = Method + Timestamp + RequestPath + QueryString + Body
        
        Args:
            method: Uppercase HTTP method (e.g. 'GET', 'POST')
            path: Canonical request path starting with '/v2/' (excluding domain)
            query_string: Query string with leading '?' if params exist, else ''
            payload: Compact JSON payload or '' if empty
            timestamp: Epoch seconds as string (generated if omitted)
            
        Returns:
            (signature_hex, timestamp_seconds)
        """
        if not self.api_secret:
            raise ValueError("Delta API Secret is not configured.")

        # Delta requires timestamp in integer seconds
        ts = timestamp or str(int(time.time()) + self._server_time_offset)

        # Canonical path must start with /v2/
        if not path.startswith("/"):
            path = "/" + path
        if not path.startswith("/v2/"):
            path = f"/v2{path}"

        # Query string must include leading ? if non-empty
        qs = query_string or ""
        if qs and not qs.startswith("?"):
            qs = f"?{qs}"

        body = payload or ""

        # Concatenate in documented order: METHOD + TIMESTAMP + PATH + QUERY_STRING + BODY
        signature_data = method.upper() + ts + path + qs + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return signature, ts

    def get_auth_headers(
        self,
        method: str,
        path: str,
        query_string: str = "",
        payload: str = "",
        timestamp: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Build authenticated request headers containing api-key, signature, and timestamp.
        """
        if not self.api_key:
            raise ValueError("Delta API Key is not configured.")
        if not self.api_secret:
            raise ValueError("Delta API Secret is not configured.")

        sig, ts = self.generate_signature(
            method=method,
            path=path,
            query_string=query_string,
            payload=payload,
            timestamp=timestamp,
        )

        headers = dict(self._headers)
        headers.update({
            "api-key": self.api_key,
            "signature": sig,
            "timestamp": ts,
            "Content-Type": "application/json",
        })
        return headers

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Public unauthenticated GET request."""
        canonical_path, full_url = self._resolve_url(endpoint)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(full_url, params=params, headers=self._headers)
                response.raise_for_status()
                data = response.json()
                return data
            except httpx.TimeoutException as exc:
                logger.error(f"Timeout connecting to Delta API ({full_url}): {exc}")
                raise RuntimeError(f"Delta API timeout ({canonical_path}): Exchange response took longer than {self.timeout}s")
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTP error from Delta API ({full_url}): {exc.response.status_code}")
                raise RuntimeError(f"Delta API error: HTTP {exc.response.status_code}")
            except Exception as exc:
                logger.error(f"Unexpected connection error ({full_url}): {exc}")
                raise RuntimeError(f"Failed to connect to Delta Exchange: {str(exc)}")

    def _assert_testnet_safe(self) -> None:
        """
        Enforce testnet-only execution for authenticated private account endpoints.
        Fails closed with EnvironmentSafetyViolation if the configured base URL is not
        in the verified Delta Testnet allowlist.
        """
        from app.core.environment_guard import validate_testnet_host
        validate_testnet_host(self.host_url)

    async def _get_authenticated(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        _is_retry: bool = False,
    ) -> Dict[str, Any]:
        """
        Authenticated GET request using HMAC-SHA256 signature.
        Strictly read-only; never submits, cancels, or alters orders.
        """
        # Security Guardrail: Enforce testnet URL
        self._assert_testnet_safe()

        canonical_path, full_url = self._resolve_url(endpoint)

        query_string = ""
        if params:
            query_string = "?" + urllib.parse.urlencode(params)

        headers = self.get_auth_headers(
            method="GET",
            path=canonical_path,
            query_string=query_string,
            payload="",
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(full_url, params=params, headers=headers)
                if response.status_code != 200:
                    logger.warning(
                        f"Delta authenticated request returned HTTP {response.status_code} for {canonical_path}"
                    )
                    error_text = response.text
                    try:
                        err_json = response.json()
                        err_code = (err_json.get("error") or {}).get("code")
                        if err_code == "expired_signature" and not _is_retry:
                            server_time = (err_json.get("error") or {}).get("context", {}).get("server_time")
                            if server_time:
                                self._server_time_offset = int(server_time) - int(time.time())
                                logger.info(
                                    f"Adjusted Delta server time offset to {self._server_time_offset}s after expired signature. Retrying request once..."
                                )
                                return await self._get_authenticated(endpoint, params=params, _is_retry=True)
                    except Exception:
                        pass
                    err = RuntimeError(f"Delta API HTTP {response.status_code}: {error_text}")
                    setattr(err, "status_code", response.status_code)
                    setattr(err, "response_body", error_text)
                    raise err

                return response.json()
            except httpx.TimeoutException as exc:
                logger.error(f"Timeout during authenticated request ({canonical_path}): {exc}")
                err = RuntimeError(f"Delta API timeout ({canonical_path}): response exceeded {self.timeout}s")
                setattr(err, "status_code", 408)
                raise err
            except httpx.HTTPStatusError as exc:
                err = RuntimeError(f"Delta API error: HTTP {exc.response.status_code}")
                setattr(err, "status_code", exc.response.status_code)
                raise err
            except Exception as exc:
                if not hasattr(exc, "status_code"):
                    setattr(exc, "status_code", None)
                raise exc

    async def get_profile(self) -> Dict[str, Any]:
        """
        Retrieve read-only user profile information from Delta Exchange.
        Endpoint: GET /v2/profile
        """
        return await self._get_authenticated("/v2/profile")

    async def get_wallet_balances(self) -> List[Dict[str, Any]]:
        """
        Retrieve read-only wallet balances from Delta Exchange.
        Endpoint: GET /v2/wallet/balances
        """
        data = await self._get_authenticated("/v2/wallet/balances")
        return data.get("result") or []

    async def get_positions(
        self,
        product_id: Optional[int] = None,
        underlying_asset_symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve read-only open positions from Delta Exchange.
        Endpoint: GET /v2/positions/margined (with fallback to /v2/positions)

        Note: Delta Exchange's /v2/positions strictly requires either product_id
        or underlying_asset_symbol. Calling /v2/positions without either parameter
        causes HTTP 400 bad_schema.
        """
        params: Dict[str, Any] = {}
        if product_id is not None:
            params["product_id"] = product_id
        elif underlying_asset_symbol is not None:
            params["underlying_asset_symbol"] = underlying_asset_symbol

        try:
            data = await self._get_authenticated("/v2/positions/margined", params=params if params else None)
            res = data.get("result")
            if isinstance(res, list):
                return res
            elif isinstance(res, dict):
                return [res] if float(res.get("size") or 0.0) != 0.0 else []
            return []
        except Exception as exc:
            # If no product filter was provided, we cannot fall back to /v2/positions
            # because /v2/positions requires product_id or underlying_asset_symbol.
            if not params:
                logger.warning(f"Failed /v2/positions/margined without product filter: {exc}")
                raise exc

            logger.warning(f"Failed /v2/positions/margined, falling back to /v2/positions: {exc}")
            data = await self._get_authenticated("/v2/positions", params=params)
            res = data.get("result")
            if isinstance(res, list):
                return res
            elif isinstance(res, dict):
                if product_id is not None and "product_id" not in res:
                    res["product_id"] = product_id
                return [res] if float(res.get("size") or 0.0) != 0.0 else []
            return []

    async def get_open_orders(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve read-only active/open orders from Delta Exchange.
        Endpoint: GET /v2/orders?states=open,pending
        """
        params: Dict[str, Any] = {"states": "open,pending"}
        if product_id is not None:
            params["product_id"] = product_id
        data = await self._get_authenticated("/v2/orders", params=params)
        return data.get("result") or []

    async def get_order_history(self, page_size: int = 20) -> List[Dict[str, Any]]:
        """
        Retrieve read-only past order history from Delta Exchange.
        Endpoint: GET /v2/orders/history?page_size={page_size}
        """
        params = {"page_size": min(page_size, 50)}
        try:
            data = await self._get_authenticated("/v2/orders/history", params=params)
            return data.get("result") or []
        except Exception as exc:
            logger.warning(f"Failed /v2/orders/history: {exc}")
            return []

    def _diagnose_auth_error(self, exc: Exception) -> Tuple[str, Optional[str]]:
        """
        Translate authentication failures into actionable, safe diagnostic messages
        and extract the client IP when available, without exposing API secrets or raw signatures.
        
        Returns:
            (diagnostic_message, client_ip)
        """
        import json
        import re

        err_msg = str(exc)
        status_code = getattr(exc, "status_code", None)
        response_body = getattr(exc, "response_body", "")

        client_ip: Optional[str] = None
        error_code: Optional[str] = None

        if response_body:
            try:
                body_data = json.loads(response_body)
                error_obj = body_data.get("error") or {}
                error_code = error_obj.get("code")
                context = error_obj.get("context") or {}
                client_ip = context.get("client_ip")
            except Exception:
                pass

        if not client_ip:
            m = re.search(r'["\']client_ip["\']\s*:\s*["\']([^"\']+)["\']', err_msg)
            if m:
                client_ip = m.group(1)

        # 1. IP Whitelist Failure
        if error_code == "ip_not_whitelisted_for_api_key" or "ip_not_whitelisted" in err_msg:
            ip_display = f" ({client_ip})" if client_ip else ""
            return (
                f"IP Whitelist Restriction: Your backend server's public IP{ip_display} is not on your API key's whitelist "
                f"on demo.delta.exchange. To resolve: (1) Log in to demo.delta.exchange -> API Keys -> Edit Key; "
                f"(2) Add '{client_ip or 'your current server IP'}' to the IP Whitelist (or leave the whitelist empty for demo testing). "
                f"Note: Your local web browser's public IP may differ from your backend server's outbound egress IP.",
                client_ip,
            )

        # 2. Invalid Key
        if error_code == "invalid_api_key" or "invalid_api_key" in err_msg:
            return (
                "Invalid API Key: The configured API key was not recognized by demo.delta.exchange. "
                "Ensure your key was generated on Delta Testnet (demo.delta.exchange) and not on production.",
                client_ip,
            )

        # 3. Signature Mismatch
        if error_code == "signature_mismatch" or "signature_mismatch" in err_msg:
            return (
                "Signature Mismatch (HTTP 401 Unauthorized): The HMAC-SHA256 signature did not match Delta's calculation. "
                "Verify that DELTA_API_SECRET in backend/.env has no extra whitespace, quotes, or line breaks.",
                client_ip,
            )

        # 4. Expired Signature / Time Drift
        if error_code == "expired_signature" or "expired_signature" in err_msg:
            return (
                "Signature Expired: Request timestamp exceeded Delta's 5-second validity window. "
                "Ensure your computer's system clock is synchronized with internet time (NTP).",
                client_ip,
            )

        # Generic HTTP Codes
        if status_code == 401 or "401" in err_msg:
            return (
                "Authentication failed (HTTP 401 Unauthorized): API credentials or signature rejected by Delta Testnet. "
                "Verify API Key and Secret on demo.delta.exchange.",
                client_ip,
            )
        elif status_code == 403 or "403" in err_msg:
            return (
                "Access forbidden (HTTP 403 Forbidden): Check IP Whitelist restrictions and verify the API key has 'Read' permissions.",
                client_ip,
            )
        elif status_code == 404 or "404" in err_msg:
            return (
                f"Endpoint not found (HTTP 404): Could not reach the endpoint at {self.host_url}. "
                "Verify that DELTA_API_URL is configured to the India testnet endpoint 'https://cdn-ind.testnet.deltaex.org'.",
                client_ip,
            )
        elif status_code == 429 or "429" in err_msg:
            return (
                "Rate limit exceeded (HTTP 429): Delta Exchange testnet request quota reached. "
                "Wait a few moments before retrying.",
                client_ip,
            )
        else:
            return f"Delta Exchange connection error: {err_msg}", client_ip

    async def verify_authentication(self) -> Dict[str, Any]:
        """
        Verify that configured API credentials authenticate properly using a read-only endpoint.
        Never modifies, submits, or cancels orders.
        Returns a sanitized status dictionary safe for display and logging.
        """
        masked = (
            f"{self.api_key[:3]}...{self.api_key[-3:]}"
            if self.api_key and len(self.api_key) > 6
            else "***"
        )
        endpoint = "/v2/profile"

        if not self.api_key or not self.api_secret:
            return {
                "success": False,
                "authenticated": False,
                "endpoint_tested": endpoint,
                "http_status": None,
                "environment": "testnet" if settings.is_testnet else "production",
                "base_url": self.host_url,
                "key_configured": False,
                "masked_key": "",
                "diagnostic": "DELTA_API_KEY or DELTA_API_SECRET is missing from backend/.env. Configure credentials to authenticate.",
            }

        try:
            profile_data = await self.get_profile()
            result = profile_data.get("result") or {}

            # Sanitize profile - expose only safe high-level status fields without PII
            account_info = {
                "user_id": result.get("id") or result.get("user_id"),
                "country": result.get("country"),
                "maker_commission_rate": result.get("maker_commission_rate"),
                "taker_commission_rate": result.get("taker_commission_rate"),
                "is_kyc_done": result.get("is_kyc_done"),
                "status": "active" if profile_data.get("success") else "unknown",
            }

            return {
                "success": True,
                "authenticated": True,
                "endpoint_tested": endpoint,
                "http_status": 200,
                "environment": "testnet" if settings.is_testnet else "production",
                "base_url": self.host_url,
                "key_configured": True,
                "masked_key": masked,
                "diagnostic": "Authentication successful: Delta Exchange testnet HMAC-SHA256 signature verified.",
                "account_info": account_info,
            }
        except Exception as exc:
            diagnostic, client_ip = self._diagnose_auth_error(exc)
            status_code = getattr(exc, "status_code", None)
            return {
                "success": False,
                "authenticated": False,
                "endpoint_tested": endpoint,
                "http_status": status_code,
                "environment": "testnet" if settings.is_testnet else "production",
                "base_url": self.host_url,
                "key_configured": True,
                "masked_key": masked,
                "client_ip": client_ip,
                "diagnostic": diagnostic,
            }

    async def get_account_overview(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Consolidate complete read-only testnet account overview:
        balances, positions, open orders, and recent order history.
        Never fabricates balances; accurately reports exchange state or diagnostics.
        Uses a short 2.5-second in-memory cache to prevent redundant exchange hammering
        during parallel status polling from dashboard components.
        """
        now = time.time()
        if not force_refresh and self._account_overview_cache:
            cache_data, cache_time = self._account_overview_cache
            if (now - cache_time) < 2.5:
                return cache_data

        masked = (
            f"{self.api_key[:3]}...{self.api_key[-3:]}"
            if self.api_key and len(self.api_key) > 6
            else "***"
        )

        if not self.api_key or not self.api_secret:
            return {
                "authenticated": False,
                "is_testnet": True,
                "environment": "testnet",
                "base_url": self.host_url,
                "masked_api_key": "",
                "client_ip": None,
                "total_balance_usd": 0.0,
                "available_balance_usd": 0.0,
                "total_margin_used_usd": 0.0,
                "total_unrealized_pnl_usd": 0.0,
                "balances": [],
                "positions": [],
                "open_orders": [],
                "recent_orders": [],
                "last_updated_at": int(time.time()),
                "diagnostic": "DELTA_API_KEY or DELTA_API_SECRET is missing from backend/.env. Configure demo testnet credentials to view live testnet wallet balances.",
                "warning": "Demo credentials not configured.",
                "disclaimer": "TESTNET NOTICE: Demo funds only. Real money execution is strictly disabled.",
            }

        # 1. Fetch Balances
        balances_raw: List[Dict[str, Any]] = []
        positions_raw: List[Dict[str, Any]] = []
        open_orders_raw: List[Dict[str, Any]] = []
        history_raw: List[Dict[str, Any]] = []
        diagnostic: Optional[str] = None
        client_ip: Optional[str] = None
        is_auth = False

        try:
            balances_raw = await self.get_wallet_balances()
            is_auth = True
        except Exception as exc:
            diag, ip = self._diagnose_auth_error(exc)
            diagnostic = diag
            client_ip = ip
            logger.warning(f"Account balances query failed: {diag}")

        if is_auth:
            # 2. Fetch Positions
            try:
                positions_raw = await self.get_positions()
            except Exception as exc:
                logger.warning(f"Account positions query failed: {exc}")

            # 3. Fetch Open Orders
            try:
                open_orders_raw = await self.get_open_orders()
            except Exception as exc:
                logger.warning(f"Account open orders query failed: {exc}")

            # 4. Fetch Order History
            try:
                history_raw = await self.get_order_history(page_size=20)
            except Exception as exc:
                logger.warning(f"Account order history query failed: {exc}")

        # Normalize balances
        normalized_balances = []
        total_bal_usd = 0.0
        avail_bal_usd = 0.0
        margin_used_usd = 0.0

        for b in balances_raw:
            try:
                sym = str(b.get("asset_symbol") or "USD").upper()
                bal = float(b.get("balance") or 0.0)
                avail = float(b.get("available_balance") or 0.0)
                blocked = float(b.get("blocked_margin") or 0.0)
                # For USDT or USD, assume 1:1 USD valuation
                usd_val = bal if sym in ("USDT", "USD", "USDC") else None

                if sym in ("USDT", "USD", "USDC"):
                    total_bal_usd += bal
                    avail_bal_usd += avail
                    margin_used_usd += blocked

                normalized_balances.append({
                    "asset_id": int(b.get("asset_id") or 0),
                    "asset_symbol": sym,
                    "balance": round(bal, 6),
                    "available_balance": round(avail, 6),
                    "blocked_margin": round(blocked, 6),
                    "usd_value": round(usd_val, 2) if usd_val is not None else None,
                })
            except Exception:
                continue

        # Normalize positions
        normalized_positions = []
        total_upnl_usd = 0.0

        for p in positions_raw:
            try:
                raw_size = float(p.get("size") or 0.0)
                if raw_size == 0.0:
                    continue  # closed position

                side = "LONG" if raw_size > 0 else "SHORT"
                upnl = float(p.get("unrealized_pnl") or 0.0)
                total_upnl_usd += upnl

                def _safe_float(v: Any) -> Optional[float]:
                    if v is None or v == "":
                        return None
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return None

                normalized_positions.append({
                    "product_id": int(p.get("product_id") or 0),
                    "symbol": str(p.get("product_symbol") or p.get("symbol") or "CONTRACT"),
                    "side": side,
                    "size": abs(raw_size),
                    "entry_price": float(p.get("entry_price") or 0.0),
                    "mark_price": float(p.get("mark_price") or 0.0),
                    "margin": float(p.get("margin") or 0.0),
                    "unrealized_pnl": round(upnl, 4),
                    "realized_pnl": float(p.get("realized_pnl") or 0.0),
                    "liquidation_price": _safe_float(p.get("liquidation_price")),
                    "bankruptcy_price": _safe_float(p.get("bankruptcy_price")),
                    "leverage": _safe_float(p.get("leverage")),
                    "updated_at": p.get("updated_at"),
                })
            except Exception:
                continue

        # Normalize open orders
        normalized_open_orders = []
        for o in open_orders_raw:
            try:
                side_str = str(o.get("side") or "buy").upper()
                normalized_open_orders.append({
                    "order_id": str(o.get("id") or o.get("order_id")),
                    "product_id": int(o.get("product_id") or 0),
                    "symbol": str(o.get("product_symbol") or o.get("symbol") or "CONTRACT"),
                    "side": "BUY" if "BUY" in side_str else "SELL",
                    "order_type": str(o.get("order_type") or "limit_order"),
                    "size": float(o.get("size") or 0.0),
                    "unfilled_size": float(o.get("unfilled_size") or 0.0),
                    "limit_price": float(o["limit_price"]) if o.get("limit_price") else None,
                    "stop_price": float(o["stop_price"]) if o.get("stop_price") else None,
                    "average_fill_price": float(o["average_fill_price"]) if o.get("average_fill_price") else None,
                    "state": str(o.get("state") or "open"),
                    "created_at": int(o.get("created_at") or time.time()),
                    "updated_at": int(o.get("updated_at")) if o.get("updated_at") else None,
                })
            except Exception:
                continue

        # Normalize recent orders
        normalized_recent_orders = []
        for o in history_raw:
            try:
                side_str = str(o.get("side") or "buy").upper()
                normalized_recent_orders.append({
                    "order_id": str(o.get("id") or o.get("order_id")),
                    "product_id": int(o.get("product_id") or 0),
                    "symbol": str(o.get("product_symbol") or o.get("symbol") or "CONTRACT"),
                    "side": "BUY" if "BUY" in side_str else "SELL",
                    "order_type": str(o.get("order_type") or "limit_order"),
                    "size": float(o.get("size") or 0.0),
                    "unfilled_size": float(o.get("unfilled_size") or 0.0),
                    "limit_price": float(o["limit_price"]) if o.get("limit_price") else None,
                    "stop_price": float(o["stop_price"]) if o.get("stop_price") else None,
                    "average_fill_price": float(o["average_fill_price"]) if o.get("average_fill_price") else None,
                    "state": str(o.get("state") or "closed"),
                    "created_at": int(o.get("created_at") or time.time()),
                    "updated_at": int(o.get("updated_at")) if o.get("updated_at") else None,
                })
            except Exception:
                continue

        result = {
            "authenticated": is_auth,
            "is_testnet": True,
            "environment": "testnet",
            "base_url": self.host_url,
            "masked_api_key": masked,
            "client_ip": client_ip,
            "total_balance_usd": round(total_bal_usd, 2),
            "available_balance_usd": round(avail_bal_usd, 2),
            "total_margin_used_usd": round(margin_used_usd, 2),
            "total_unrealized_pnl_usd": round(total_upnl_usd, 4),
            "balances": normalized_balances,
            "positions": normalized_positions,
            "open_orders": normalized_open_orders,
            "recent_orders": normalized_recent_orders,
            "last_updated_at": int(time.time()),
            "diagnostic": diagnostic,
            "warning": "IP Whitelist or Auth Issue: verify demo credentials" if not is_auth else None,
            "disclaimer": "TESTNET DEMO ONLY: All balances, positions, and orders represent simulated testnet funds. Live automated trading is disabled.",
        }
        self._account_overview_cache = (result, now)
        return result

    def parse_ticker(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse raw Delta Exchange ticker object safely into normalized format."""
        if not raw or not raw.get("symbol"):
            return None

        close_raw = raw.get("close")
        if close_raw is None:
            return None

        try:
            close_price = float(close_raw)
        except (ValueError, TypeError):
            return None

        def to_float(val: Any) -> Optional[float]:
            if val is None or val == "":
                return None
            try:
                v = float(val)
                return None if math.isnan(v) else v
            except (ValueError, TypeError):
                return None

        change_24h = to_float(raw.get("ltp_change_24h"))
        if change_24h is None:
            change_24h = to_float(raw.get("mark_change_24h"))

        high_24h = to_float(raw.get("high"))
        low_24h = to_float(raw.get("low"))
        volume_24h = to_float(raw.get("volume"))

        turnover_usd = to_float(raw.get("turnover_usd"))
        if turnover_usd is None:
            turnover_usd = to_float(raw.get("turnover"))

        mark_price = to_float(raw.get("mark_price"))
        spot_price = to_float(raw.get("spot_price"))
        funding_rate = to_float(raw.get("funding_rate"))

        quotes = raw.get("quotes") or {}
        best_bid = to_float(quotes.get("best_bid"))
        best_ask = to_float(quotes.get("best_ask"))

        # Normalized timestamp (milliseconds)
        ts = raw.get("timestamp")
        if ts:
            ts_ms = int(ts) // 1000
        else:
            time_str = raw.get("time")
            if time_str:
                try:
                    dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    ts_ms = int(dt.timestamp() * 1000)
                except Exception:
                    ts_ms = int(time.time() * 1000)
            else:
                ts_ms = int(time.time() * 1000)

        date_obj = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        last_updated_str = date_obj.strftime("%H:%M:%S UTC")

        symbol = str(raw["symbol"])
        base_asset = raw.get("underlying_asset_symbol") or ""
        quote_asset = "USD"
        if not base_asset:
            if symbol.endswith("USD"):
                base_asset = symbol[:-3]
                quote_asset = "USD"
            elif symbol.endswith("USDT"):
                base_asset = symbol[:-4]
                quote_asset = "USDT"
            else:
                base_asset = symbol

        return {
            "symbol": symbol,
            "product_id": raw.get("product_id") or 0,
            "name": raw.get("description") or symbol,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "contract_type": raw.get("contract_type") or "perpetual_futures",
            "last_price": close_price,
            "change_24h": change_24h,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "volume_24h": volume_24h,
            "turnover_24h_usd": turnover_usd,
            "mark_price": mark_price,
            "spot_price": spot_price,
            "funding_rate": funding_rate,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "timestamp": ts_ms,
            "last_updated_str": last_updated_str,
            "price_direction": "same",
        }

    async def get_tickers(self) -> List[Dict[str, Any]]:
        """Fetch all public tickers from Delta Exchange and parse them."""
        data = await self._get("/tickers")
        raw_list = data.get("result") or []
        parsed_tickers: List[Dict[str, Any]] = []

        for item in raw_list:
            parsed = self.parse_ticker(item)
            if parsed:
                parsed_tickers.append(parsed)

        return parsed_tickers

    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch all available products from Delta Exchange."""
        data = await self._get("/products")
        return data.get("result") or []

    @staticmethod
    def get_resolution_seconds(resolution: str) -> int:
        mapping = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "1d": 86400,
        }
        return mapping.get(resolution.lower(), 3600)

    async def get_historical_candles(
        self,
        symbol: str,
        resolution: str = "1h",
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch historical OHLCV candles from Delta Exchange with multi-chunk backward retrieval.
        Delta Exchange caps a single response to 4,000 candles.
        """
        now = int(time.time())
        res_seconds = self.get_resolution_seconds(resolution)

        if end is None:
            end = now
        if start is None:
            start = end - (7 * 86400)  # default 7 days

        if start >= end:
            start = end - 86400

        total_seconds = end - start
        estimated_candles = math.ceil(total_seconds / res_seconds)

        seen_times = set()
        candles: List[Dict[str, Any]] = []
        current_end = end
        max_chunks = 10
        chunks_fetched = 0

        while current_end > start and chunks_fetched < max_chunks:
            chunks_fetched += 1
            params = {
                "symbol": symbol,
                "resolution": resolution,
                "start": start,
                "end": current_end,
            }

            try:
                data = await self._get("/history/candles", params=params)
            except Exception as exc:
                if chunks_fetched == 1:
                    raise exc
                # If subsequent chunk fails, return whatever we have already retrieved
                break

            result = data.get("result") or []
            if not result:
                break

            new_in_chunk = 0
            for item in result:
                t = item.get("time")
                if t is not None and t not in seen_times:
                    try:
                        seen_times.add(t)
                        candles.append({
                            "time": int(t),
                            "open": float(item["open"]),
                            "high": float(item["high"]),
                            "low": float(item["low"]),
                            "close": float(item["close"]),
                            "volume": float(item.get("volume") or 0.0),
                        })
                        new_in_chunk += 1
                    except (ValueError, KeyError, TypeError):
                        continue

            oldest_in_chunk = result[-1].get("time")
            if oldest_in_chunk is None or oldest_in_chunk <= start or new_in_chunk == 0:
                break

            current_end = oldest_in_chunk - res_seconds

        # Sort chronologically ascending for Lightweight Charts
        candles.sort(key=lambda c: c["time"])

        limitation_notice = None
        if estimated_candles > 10000 and len(candles) < estimated_candles * 0.8:
            limitation_notice = (
                f"Loaded the latest {len(candles):,} candles for this period (Delta Exchange query limit). "
                f"For full historical coverage of large date spans, select a higher interval (e.g. 15m, 1H, or 1D)."
            )

        return {
            "success": True,
            "symbol": symbol,
            "resolution": resolution,
            "candles": candles,
            "count": len(candles),
            "limitation_notice": limitation_notice,
            "range": {
                "start": candles[0]["time"] if candles else start,
                "end": candles[-1]["time"] if candles else end,
            },
        }


delta_client = DeltaExchangeClient()
