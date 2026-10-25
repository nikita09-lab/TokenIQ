import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.automation.config import automation_config_manager
from app.automation.dedup import signal_deduplicator
from app.automation.models import (
    AutomatedSignal,
    AutomationConfig,
    AutomationStatusResponse,
    PositionStateRecord,
)
from app.automation.position_manager import position_manager
from app.automation.worker import automated_trading_worker, UnresolvedOrdersError
from app.risk.service import risk_service
from app.trading.gateway import delta_testnet_gateway
from app.trading.store import execution_store

logger = logging.getLogger("automation_routes")

router = APIRouter(prefix="/automation", tags=["Automated Trading"])


class EnableAutomationRequest(BaseModel):
    confirm: bool = Field(..., description="Must explicitly be True to confirm enabling automation")
    acknowledgement: Optional[str] = Field(
        default=None,
        description="Optional operator statement acknowledging testnet-only risk limits",
    )


class PauseAutomationRequest(BaseModel):
    reason: Optional[str] = Field(
        default="Operator paused new entries",
        max_length=256,
        description="Reason for pausing new automated entries",
    )


class ConfigValidationResponse(BaseModel):
    valid: bool
    reasons: List[str] = Field(default_factory=list)
    normalized_config: Optional[AutomationConfig] = None


@router.get("/status", response_model=AutomationStatusResponse)
async def get_automation_status():
    """
    Retrieve comprehensive live status of the automated trading engine,
    including state, limits, active position, latest signal, and safety postures.
    """
    try:
        return await automated_trading_worker.get_status()
    except Exception as exc:
        logger.error(f"Failed to compile automation status: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve automation status: {exc}",
        )


@router.get("/config", response_model=AutomationConfig)
async def get_automation_config():
    """Retrieve current persistent automated trading configuration."""
    return await automation_config_manager.get_config()


@router.put("/config", response_model=AutomationConfig)
async def update_automation_config(config: AutomationConfig):
    """
    Update persistent automated trading configuration.
    Validates all numeric bounds and product specifications.
    """
    try:
        updated = await automation_config_manager.update_config(config)
        return updated
    except Exception as exc:
        logger.error(f"Error updating automation config: {exc}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid configuration parameters: {exc}",
        )


@router.post("/config/validate", response_model=ConfigValidationResponse)
async def validate_automation_config(config: AutomationConfig):
    """
    Validate proposed automated trading configuration against risk limits,
    exchange specifications, and environment safeguards without saving.
    """
    reasons = []

    # 1. Check Product exists on Delta Exchange
    try:
        products = await risk_service._get_fresh_products()
        sym = config.trading_symbol.upper()
        meta = next((p for p in products if str(p.get("symbol")).upper() == sym), None)
        if not meta:
            reasons.append(f"Target symbol '{sym}' is not a supported contract on Delta Exchange.")
    except Exception as exc:
        reasons.append(f"Could not fetch product metadata: {exc}")

    # 2. Check risk limit bounds
    if config.maximum_order_notional <= 0:
        reasons.append("Maximum order notional must be positive.")
    if config.protective_stop_loss_percentage < 0.5:
        reasons.append("Protective stop-loss must be at least 0.5%.")
    if config.strategy_parameters.get("fast_period", 0) >= config.strategy_parameters.get("slow_period", 0):
        reasons.append("Fast EMA period must be strictly less than Slow EMA period.")

    is_valid = len(reasons) == 0
    return ConfigValidationResponse(
        valid=is_valid,
        reasons=reasons,
        normalized_config=config if is_valid else None,
    )


@router.post("/enable", response_model=AutomationStatusResponse)
async def enable_automation(request: EnableAutomationRequest):
    """
    Explicitly enable automated testnet order execution.
    Fails closed if the kill switch is engaged, trading authorization is disabled,
    or required credentials/telemetry are missing.
    """
    try:
        return await automated_trading_worker.enable_automation(explicit_confirm=request.confirm)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except UnresolvedOrdersError as unres_err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "UNRESOLVED_ORDERS",
                "message": str(unres_err),
                "unresolved_order_count": unres_err.count,
                "client_order_ids": unres_err.client_order_ids,
                "actionable_guidance": "Check Delta Exchange IP whitelist and verify orders under Trading Safety before enabling automation.",
            },
        )
    except RuntimeError as run_err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTIVATION_SAFETY_VIOLATION",
                "message": str(run_err),
                "actionable_guidance": "Resolve the safety condition before enabling automated trading.",
            },
        )
    except Exception as exc:
        logger.error(f"Failed to enable automation: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate automation: {exc}",
        )


@router.post("/stop", response_model=AutomationStatusResponse)
async def stop_automation():
    """
    Disables automated order execution and stops the evaluation loop.
    Leaves open positions intact.
    """
    try:
        return await automated_trading_worker.disable_automation(reason="Manual operator stop request")
    except Exception as exc:
        logger.error(f"Failed to stop automation: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable automation: {exc}",
        )


@router.post("/pause", response_model=AutomationStatusResponse)
async def pause_automation(request: PauseAutomationRequest):
    """
    Pauses new automated trade entries while preserving active position
    management and protective stop monitoring.
    """
    try:
        return await automated_trading_worker.pause_entries(reason=request.reason or "Paused by user")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause automation: {exc}",
        )


@router.post("/resume", response_model=AutomationStatusResponse)
async def resume_automation():
    """
    Resumes new automated trade entries after verifying that all safety
    and risk limits pass.
    """
    try:
        return await automated_trading_worker.resume_entries()
    except RuntimeError as run_err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTIVATION_SAFETY_VIOLATION",
                "message": str(run_err),
                "actionable_guidance": "Resolve the safety condition before resuming automated trading.",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume automation: {exc}",
        )


@router.get("/signals", response_model=List[AutomatedSignal])
async def list_signals(limit: int = Query(default=50, ge=1, le=200)):
    """Retrieve chronologically descending history of generated automated signals."""
    return await signal_deduplicator.get_recent_signals(limit=limit)


@router.get("/positions", response_model=List[PositionStateRecord])
async def list_positions():
    """Retrieve tracked positions and their synchronized lifecycle states."""
    return await position_manager.get_all_positions()


@router.post("/reconcile", response_model=PositionStateRecord)
async def reconcile_position(symbol: str = Query(..., description="Symbol to reconcile with exchange")):
    """
    Force manual reconciliation of a symbol's position against live exchange state.
    """
    try:
        import time
        res = await position_manager.reconcile_with_exchange(symbol.upper())
        automated_trading_worker._last_reconciliation_at = int(time.time())
        return res
    except Exception as exc:
        logger.error(f"Reconciliation error for {symbol}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange position reconciliation failed: {exc}",
        )
