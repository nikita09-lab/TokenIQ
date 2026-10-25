import logging
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, status

from app.evaluation.engine import EvaluationValidationError
from app.evaluation.models import EvaluationRequest, EvaluationResult
from app.evaluation.service import evaluation_service

logger = logging.getLogger("evaluation_routes")

router = APIRouter(prefix="/evaluation", tags=["Strategy Evaluation & Robustness"])


@router.get("/config-options", response_model=Dict[str, Any])
async def get_evaluation_config_options() -> Dict[str, Any]:
    """
    Retrieve parameter grid options, preset configurations, supported intervals,
    split ratios, and evaluation constraints for Strategy Lab.
    """
    return {
        "success": True,
        "config": evaluation_service.get_config_options(),
    }


@router.post("/run", response_model=Dict[str, Any])
async def run_evaluation(request: EvaluationRequest) -> Dict[str, Any]:
    """
    Execute a bounded walk-forward parameter evaluation job.
    Fetches historical candles once from Delta Exchange, splits chronologically into
    in-sample (training) and out-of-sample (testing) periods, ranks parameter combinations
    strictly on training data, and tests for overfitting on unseen data.
    """
    try:
        result = await evaluation_service.run_evaluation(request)
        return {
            "success": True,
            "result": result.model_dump(),
        }
    except EvaluationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error(f"Unexpected error running evaluation: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Strategy evaluation failed: {str(exc)}",
        )


@router.get("/results/{evaluation_id}", response_model=Dict[str, Any])
async def get_evaluation_result(evaluation_id: str) -> Dict[str, Any]:
    """
    Retrieve cached evaluation results by unique evaluation job ID.
    """
    result = evaluation_service.get_result(evaluation_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation result '{evaluation_id}' not found or expired from cache.",
        )
    return {
        "success": True,
        "result": result.model_dump(),
    }
