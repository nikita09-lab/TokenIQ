import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status

from app.risk.models import (
    KillSwitchRequest,
    KillSwitchResetRequest,
    RiskCheckRequest,
    RiskCheckResult,
    RiskConfig,
    TradingStatus,
)
from app.risk.service import risk_service

logger = logging.getLogger("trading_routes")

router = APIRouter(prefix="/trading", tags=["Trading Safety & Risk Engine"])


@router.get("/status", response_model=TradingStatus)
async def get_trading_safety_status() -> TradingStatus:
    """
    Retrieve current trading safety status, kill-switch state, active risk limits,
    and daily counters.
    """
    try:
        return await risk_service.get_trading_status()
    except Exception as exc:
        logger.error(f"Error fetching trading safety status: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/risk-config", response_model=RiskConfig)
async def get_risk_configuration() -> RiskConfig:
    """
    Retrieve current active risk limits and parameters.
    """
    return risk_service.get_risk_config()


@router.put("/risk-config", response_model=RiskConfig)
async def update_risk_configuration(new_config: RiskConfig) -> RiskConfig:
    """
    Update and atomically persist new risk limits.
    Strictly validates all limits to ensure positive finite values.
    """
    try:
        return risk_service.update_risk_config(new_config)
    except Exception as exc:
        logger.error(f"Failed to update risk config: {exc}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post("/risk-check", response_model=RiskCheckResult)
async def evaluate_signal_risk(request: RiskCheckRequest) -> RiskCheckResult:
    """
    Evaluate a proposed trade or strategy signal against all safety and risk rules.
    
    STRICTLY DRY-RUN: Never routes, sends, or submits orders to any exchange.
    Does not count as an actual submitted order.
    """
    try:
        return await risk_service.check_signal_risk(request)
    except Exception as exc:
        logger.error(f"Risk evaluation error for {request.symbol}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/kill-switch", response_model=TradingStatus)
async def engage_kill_switch(payload: KillSwitchRequest) -> TradingStatus:
    """
    Emergency activation of the trading kill switch.
    Immediately halts all future trade approvals.
    Note: Does not cancel open orders or close existing positions (not implemented in this phase).
    """
    try:
        return await risk_service.engage_kill_switch(payload.reason)
    except Exception as exc:
        logger.error(f"Failed to engage kill switch: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/kill-switch/reset", response_model=TradingStatus)
async def reset_kill_switch(payload: KillSwitchResetRequest) -> TradingStatus:
    """
    Deliberately reset the trading kill switch.
    Requires explicit operator confirmation ('confirm': true) and justification.
    """
    try:
        return await risk_service.reset_kill_switch(confirm=payload.confirm, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Failed to reset kill switch: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ============================================================================
# Phase 7.2: Secure Delta Exchange Testnet Order Execution Endpoints
# ============================================================================

from app.trading.models import (
    ExecutionStatusResponse,
    OrderCancelRequest,
    OrderConfirmRequest,
    OrderExecutionRecord,
    OrderPreviewRequest,
    OrderPreviewResponse,
)
from app.trading.service import order_execution_service
from app.core.environment_guard import EnvironmentSafetyViolation
from app.trading.gateway import ExchangeOrderRejectedError


@router.get("/execution/status", response_model=ExecutionStatusResponse)
async def get_execution_status() -> ExecutionStatusResponse:
    """
    Retrieve readiness and safety posture of the testnet order execution service.
    """
    try:
        return await order_execution_service.get_execution_status()
    except EnvironmentSafetyViolation as env_exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(env_exc))
    except Exception as exc:
        logger.error(f"Error fetching execution status: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/orders/preview", response_model=OrderPreviewResponse)
async def create_order_preview(payload: OrderPreviewRequest) -> OrderPreviewResponse:
    """
    Stage 1: Generate an expiring order preview with pre-trade risk evaluation.
    STRICTLY PREVIEW: Never places an exchange order.
    """
    try:
        return await order_execution_service.create_order_preview(payload)
    except ValueError as val_exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(val_exc))
    except EnvironmentSafetyViolation as env_exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(env_exc))
    except Exception as exc:
        logger.error(f"Failed to create order preview for {payload.symbol}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/orders/confirm", response_model=OrderExecutionRecord)
async def confirm_and_submit_order(payload: OrderConfirmRequest) -> OrderExecutionRecord:
    """
    Stage 2: Confirm and submit a previewed order strictly to Delta Testnet.
    Reruns live risk checks immediately before submission.
    """
    try:
        return await order_execution_service.confirm_and_submit_order(payload)
    except ValueError as val_exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_exc))
    except EnvironmentSafetyViolation as env_exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(env_exc))
    except ExchangeOrderRejectedError as rej_exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(rej_exc))
    except RuntimeError as r_exc:
        # Risk check or authorization failure
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(r_exc))
    except Exception as exc:
        logger.error(f"Failed to submit order for preview {payload.preview_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/orders", response_model=List[OrderExecutionRecord])
async def list_orders() -> List[OrderExecutionRecord]:
    """
    List all local testnet order execution records sorted chronologically.
    """
    try:
        return await order_execution_service.list_orders()
    except Exception as exc:
        logger.error(f"Failed to list orders: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/orders/{order_id}", response_model=OrderExecutionRecord)
async def get_order_detail(order_id: str) -> OrderExecutionRecord:
    """
    Retrieve specific order execution record by client_order_id or exchange order_id.
    """
    try:
        return await order_execution_service.get_order(order_id)
    except ValueError as val_exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_exc))
    except Exception as exc:
        logger.error(f"Failed to get order {order_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/orders/{order_id}/cancel", response_model=OrderExecutionRecord)
async def cancel_order(order_id: str, payload: Optional[OrderCancelRequest] = None) -> OrderExecutionRecord:
    """
    Cancel an eligible open order on Delta Exchange Testnet.
    """
    reason = payload.reason if payload else "Manual cancellation"
    try:
        return await order_execution_service.cancel_order(order_id, reason=reason)
    except ValueError as val_exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_exc))
    except EnvironmentSafetyViolation as env_exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(env_exc))
    except Exception as exc:
        logger.error(f"Failed to cancel order {order_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/orders/{order_id}/reconcile", response_model=OrderExecutionRecord)
async def reconcile_order(order_id: str) -> OrderExecutionRecord:
    """
    Reconcile local execution record against live Delta Testnet exchange state.
    """
    try:
        return await order_execution_service.reconcile_order(order_id)
    except ValueError as val_exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_exc))
    except Exception as exc:
        logger.error(f"Failed to reconcile order {order_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

