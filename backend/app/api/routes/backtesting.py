import logging
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status

from app.backtesting.engine import BacktestValidationError
from app.backtesting.models import BacktestRequest
from app.backtesting.service import backtest_service

logger = logging.getLogger("backtesting_routes")

router = APIRouter(prefix="/backtesting", tags=["Strategy Backtesting"])


@router.get("/config-options", response_model=Dict[str, Any])
async def get_backtest_config_options() -> Dict[str, Any]:
    """
    Retrieve backtest configuration options, supported resolutions, execution modes, and defaults.
    """
    return {
        "success": True,
        "config": backtest_service.get_config_options(),
    }


@router.post("/run", response_model=Dict[str, Any])
async def run_backtest(request: BacktestRequest) -> Dict[str, Any]:
    """
    Execute a historical backtest of the EMA Crossover (9/21) + RSI strategy against
    real Delta Exchange India historical market data.
    """
    try:
        result = await backtest_service.run_backtest(request)
        return {
            "success": True,
            "result": result.model_dump(),
        }
    except BacktestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Unexpected error running backtest: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest execution failed: {str(exc)}",
        )


@router.get("/results/{backtest_id}", response_model=Dict[str, Any])
async def get_backtest_result(backtest_id: str) -> Dict[str, Any]:
    """
    Retrieve previously calculated backtest results by unique backtest ID.
    """
    result = backtest_service.get_result(backtest_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backtest result '{backtest_id}' not found or expired from cache.",
        )
    return {
        "success": True,
        "result": result.model_dump(),
    }
