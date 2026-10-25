import logging
import time
from typing import Any, Dict, List, Optional
from collections import OrderedDict

from app.evaluation.engine import EvaluationEngine, EvaluationValidationError
from app.evaluation.models import EvaluationRequest, EvaluationResult, ParameterSearchSpace
from app.exchanges.delta_client import delta_client

logger = logging.getLogger("evaluation_service")


class EvaluationService:
    """
    Coordinates historical market data retrieval, bounded parameter search space execution,
    and results caching for TokenIQ Strategy Evaluation and Robustness Testing.
    """

    def __init__(self, cache_limit: int = 50):
        self._results_cache: OrderedDict[str, EvaluationResult] = OrderedDict()
        self._cache_limit = cache_limit

    async def run_evaluation(self, request: EvaluationRequest) -> EvaluationResult:
        """
        Fetch historical candles ONCE from Delta Exchange, run in-memory chronological
        train/test parameter comparison, and cache the output.
        """
        now = int(time.time())
        end_time = request.end_time if request.end_time is not None else now
        if request.start_time is not None:
            start_time = request.start_time
        else:
            # Default to 45 days of candles so train/test has sufficient history
            start_time = end_time - (45 * 86400)

        if start_time >= end_time:
            raise EvaluationValidationError(
                f"start_time ({start_time}) must be strictly earlier than end_time ({end_time})."
            )

        symbol = request.symbol.strip().upper()
        resolution = request.resolution.strip().lower()

        logger.info(
            f"Retrieving historical candles for Strategy Lab: symbol={symbol}, "
            f"resolution={resolution}, range=[{start_time}..{end_time}]"
        )

        try:
            candle_data = await delta_client.get_historical_candles(
                symbol=symbol,
                resolution=resolution,
                start=start_time,
                end=end_time,
            )
        except Exception as exc:
            logger.error(f"Delta client error fetching candles for evaluation: {exc}")
            raise EvaluationValidationError(f"Delta Exchange market data error: {str(exc)}")

        candles = candle_data.get("candles") or []
        if not candles or len(candles) == 0:
            raise EvaluationValidationError(
                f"No candle data available from Delta Exchange for {symbol} at interval {resolution} in the selected range."
            )

        # Run chronological walk-forward evaluation engine
        engine = EvaluationEngine(request)
        result = engine.run(candles)

        # Cache result
        self._results_cache[result.evaluation_id] = result
        if len(self._results_cache) > self._cache_limit:
            self._results_cache.popitem(last=False)

        logger.info(
            f"Evaluation {result.evaluation_id} complete for {symbol}. "
            f"Evaluated {result.total_combinations_evaluated} parameter sets. "
            f"Winner: {result.selected_winner_label} "
            f"(Train PnL: {result.parameter_sets[0].in_sample.net_return_pct:.1f}%, "
            f"Test PnL: {result.parameter_sets[0].out_of_sample.net_return_pct:.1f}%, "
            f"Overfit: {result.selected_winner_is_overfit})"
        )
        return result

    def get_result(self, evaluation_id: str) -> Optional[EvaluationResult]:
        """Retrieve cached evaluation result by ID."""
        return self._results_cache.get(evaluation_id)

    def get_config_options(self) -> Dict[str, Any]:
        """
        Return available parameter search grids, recommended presets,
        supported intervals, split options, and constraints.
        """
        return {
            "default_search_space": ParameterSearchSpace().model_dump(),
            "max_combinations_allowed": 100,
            "supported_resolutions": ["15m", "30m", "1h", "2h", "4h", "1d"],
            "default_resolution": "1h",
            "default_split_ratio": 0.70,
            "split_ratio_options": [
                {"ratio": 0.60, "label": "60% Train / 40% Test (Balanced)"},
                {"ratio": 0.70, "label": "70% Train / 30% Test (Recommended Standard)"},
                {"ratio": 0.80, "label": "80% Train / 20% Test (Deep Training)"},
            ],
            "ranking_metrics": [
                {"id": "net_return_pct", "label": "Net Return (%)", "description": "Total net return after fees and slippage"},
                {"id": "profit_factor", "label": "Profit Factor", "description": "Gross profits divided by gross losses"},
                {"id": "win_rate_pct", "label": "Win Rate (%)", "description": "Percentage of winning closed trades"},
            ],
            "preset_grids": [
                {
                    "name": "EMA 9 / 11 / 20",
                    "description": "Triple EMA baseline with RSI filter disabled",
                    "search_space": {
                        "fast_periods": [9],
                        "middle_periods": [11],
                        "slow_periods": [20],
                        "rsi_periods": [14],
                        "rsi_buy_mins": [40.0],
                        "rsi_sell_maxs": [60.0],
                        "volume_confirmation": [False],
                    },
                },
                {
                    "name": "EMA 8 / 13 / 21",
                    "description": "Alternative Triple EMA preset with RSI filter disabled",
                    "search_space": {
                        "fast_periods": [8],
                        "middle_periods": [13],
                        "slow_periods": [21],
                        "rsi_periods": [14],
                        "rsi_buy_mins": [35.0, 45.0],
                        "rsi_sell_maxs": [55.0, 65.0],
                        "volume_confirmation": [False],
                    },
                },
                {
                    "name": "Triple EMA + Volume Check",
                    "description": "Tests the baseline EMA setup with volume confirmation on or off",
                    "search_space": {
                        "fast_periods": [9],
                        "middle_periods": [11],
                        "slow_periods": [20],
                        "rsi_periods": [14],
                        "rsi_buy_mins": [40.0],
                        "rsi_sell_maxs": [60.0],
                        "volume_confirmation": [False, True],
                    },
                },
            ],
            "disclaimer": (
                "DISCLAIMER: TokenIQ Strategy Evaluation and Robustness Testing provides quantitative analysis only. "
                "Optimization on historical data does not guarantee future profitability. Market regimes change dynamically."
            ),
        }


# Global singleton instance
evaluation_service = EvaluationService()
