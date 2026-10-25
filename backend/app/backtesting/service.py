import logging
import time
from typing import Any, Dict, List, Optional
from collections import OrderedDict

from app.backtesting.engine import BacktestEngine, BacktestValidationError
from app.backtesting.models import BacktestRequest, BacktestResult
from app.exchanges.delta_client import delta_client
from app.strategies.registry import strategy_registry

logger = logging.getLogger("backtest_service")


class BacktestService:
    """
    Coordinates historical candle retrieval, strategy simulation, and result caching.
    """

    def __init__(self, cache_limit: int = 50):
        self._results_cache: OrderedDict[str, BacktestResult] = OrderedDict()
        self._cache_limit = cache_limit

    async def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        """
        Fetch real Delta Exchange historical data, simulate the strategy chronologically,
        and cache the structured result.
        """
        now = int(time.time())
        end_time = request.end_time if request.end_time is not None else now
        if request.start_time is not None:
            start_time = request.start_time
        else:
            # Default to 30 days of historical data
            start_time = end_time - (30 * 86400)

        if start_time >= end_time:
            raise BacktestValidationError(
                f"Start time ({start_time}) must be earlier than end time ({end_time})."
            )

        symbol = request.symbol.strip().upper()
        resolution = request.resolution.strip().lower()

        logger.info(
            f"Fetching historical candles for backtest: symbol={symbol}, resolution={resolution}, "
            f"start={start_time}, end={end_time}"
        )

        try:
            candle_data = await delta_client.get_historical_candles(
                symbol=symbol,
                resolution=resolution,
                start=start_time,
                end=end_time,
            )
        except Exception as exc:
            logger.error(f"Exchange error retrieving backtest candles for {symbol}: {exc}")
            raise BacktestValidationError(f"Delta Exchange market data error: {str(exc)}")

        candles = candle_data.get("candles") or []
        if not candles or len(candles) == 0:
            raise BacktestValidationError(
                f"No candle data available from Delta Exchange for {symbol} at resolution {resolution} in the given date range."
            )

        # Execute the simulation engine
        engine = BacktestEngine(request)
        result = engine.run(candles)

        # Store in LRU cache
        self._results_cache[result.backtest_id] = result
        if len(self._results_cache) > self._cache_limit:
            self._results_cache.popitem(last=False)

        logger.info(
            f"Backtest {result.backtest_id} complete for {symbol}. "
            f"Net PnL: ${result.metrics.net_profit:,.2f} ({result.metrics.net_return_pct:.2f}%), "
            f"Trades: {result.metrics.total_trades}, Win Rate: {result.metrics.win_rate_pct:.1f}%"
        )
        return result

    def get_result(self, backtest_id: str) -> Optional[BacktestResult]:
        """Retrieve a cached backtest result by ID."""
        return self._results_cache.get(backtest_id)

    def get_config_options(self) -> Dict[str, Any]:
        """Return available configuration defaults, allowed intervals, and strategy schemas."""
        strategy = strategy_registry.get_strategy("ema_crossover")
        schema = strategy.get_parameters_schema() if strategy else {}

        return {
            "supported_resolutions": ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"],
            "default_resolution": "1h",
            "default_lookback_days": 90,
            "default_initial_capital": 10000.0,
            "default_fee_rate": 0.0005,  # 0.05%
            "default_slippage_rate": 0.0005,  # 0.05%
            "execution_modes": [
                {
                    "mode": "next_open",
                    "label": "Next Candle Open (Recommended)",
                    "description": "Fills at the open of the candle immediately following the signal (eliminates look-ahead bias).",
                },
                {
                    "mode": "current_close",
                    "label": "Current Candle Close",
                    "description": "Fills at the close of the signal candle with slippage applied.",
                },
            ],
            "default_strategy_params": strategy.parameters if strategy else {},
            "strategy_presets": {
                "9/11/20": {"fast_period": 9, "middle_period": 11, "slow_period": 20, "rsi_filter_enabled": False},
                "8/13/21": {"fast_period": 8, "middle_period": 13, "slow_period": 21, "rsi_filter_enabled": False},
            },
            "strategy_parameters_schema": schema.get("parameters", {}),
            "disclaimer": (
                "DISCLAIMER: TokenIQ backtesting is purely analytical and does not constitute financial advice. "
                "Simulated past performance is not indicative of future market returns."
            ),
        }


# Singleton backtest service instance
backtest_service = BacktestService()
