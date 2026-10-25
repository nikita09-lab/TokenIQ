import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query, status

from app.account.models import (
    AccountOverviewData,
    OrderItem,
    PositionItem,
    WalletBalanceItem,
)
from app.exchanges.delta_client import delta_client

logger = logging.getLogger("account_routes")

router = APIRouter(prefix="/account", tags=["Account & Testnet Wallet"])


@router.get("/overview", response_model=Dict[str, Any])
async def get_testnet_account_overview() -> Dict[str, Any]:
    """
    Retrieve consolidated testnet account overview:
    wallet balances, open positions, open orders, and recent order history.
    Strictly read-only; never places, modifies, or cancels orders.
    Enforces testnet endpoint safety server-side.
    """
    overview = await delta_client.get_account_overview()
    return {
        "success": True,
        "overview": overview,
    }


@router.get("/auth-status", response_model=Dict[str, Any])
async def check_authentication_status() -> Dict[str, Any]:
    """
    Verify Delta Exchange testnet API credentials using a signed read-only request.
    Strictly read-only. Returns safe diagnostic information without leaking API secrets.
    """
    auth_result = await delta_client.verify_authentication()
    return {
        "success": True,
        "auth": auth_result,
    }


@router.get("/balances", response_model=Dict[str, Any])
async def get_wallet_balances() -> Dict[str, Any]:
    """
    Retrieve read-only wallet asset balances from Delta Exchange Testnet.
    """
    try:
        overview = await delta_client.get_account_overview()
        return {
            "success": True,
            "authenticated": overview["authenticated"],
            "balances": overview["balances"],
            "total_balance_usd": overview["total_balance_usd"],
            "available_balance_usd": overview["available_balance_usd"],
            "total_margin_used_usd": overview["total_margin_used_usd"],
            "diagnostic": overview.get("diagnostic"),
        }
    except Exception as exc:
        diag, client_ip = delta_client._diagnose_auth_error(exc)
        status_code = getattr(exc, "status_code", None) or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(
            status_code=status_code,
            detail=diag,
        )


@router.get("/positions", response_model=Dict[str, Any])
async def get_open_positions() -> Dict[str, Any]:
    """
    Retrieve read-only open futures/perpetual positions from Delta Exchange Testnet.
    """
    try:
        overview = await delta_client.get_account_overview()
        return {
            "success": True,
            "authenticated": overview["authenticated"],
            "positions": overview["positions"],
            "total_unrealized_pnl_usd": overview["total_unrealized_pnl_usd"],
            "diagnostic": overview.get("diagnostic"),
        }
    except Exception as exc:
        diag, client_ip = delta_client._diagnose_auth_error(exc)
        status_code = getattr(exc, "status_code", None) or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(
            status_code=status_code,
            detail=diag,
        )


@router.get("/orders", response_model=Dict[str, Any])
async def get_open_orders() -> Dict[str, Any]:
    """
    Retrieve read-only active/pending orders from Delta Exchange Testnet.
    """
    try:
        overview = await delta_client.get_account_overview()
        return {
            "success": True,
            "authenticated": overview["authenticated"],
            "open_orders": overview["open_orders"],
            "diagnostic": overview.get("diagnostic"),
        }
    except Exception as exc:
        diag, client_ip = delta_client._diagnose_auth_error(exc)
        status_code = getattr(exc, "status_code", None) or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(
            status_code=status_code,
            detail=diag,
        )


@router.get("/history", response_model=Dict[str, Any])
async def get_order_history(
    page_size: int = Query(default=20, ge=1, le=50, description="Max orders to retrieve")
) -> Dict[str, Any]:
    """
    Retrieve read-only historical orders from Delta Exchange Testnet.
    """
    try:
        overview = await delta_client.get_account_overview()
        return {
            "success": True,
            "authenticated": overview["authenticated"],
            "recent_orders": overview["recent_orders"][:page_size],
            "diagnostic": overview.get("diagnostic"),
        }
    except Exception as exc:
        diag, client_ip = delta_client._diagnose_auth_error(exc)
        status_code = getattr(exc, "status_code", None) or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(
            status_code=status_code,
            detail=diag,
        )
