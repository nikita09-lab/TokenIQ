import itertools
import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from app.backtesting.engine import BacktestEngine, BacktestValidationError
from app.backtesting.models import BacktestMetrics, BacktestRequest, BacktestResult, EquityPoint, Trade
from app.evaluation.models import (
    EvaluatedParameterSet,
    EvaluationRequest,
    EvaluationResult,
    ParameterSearchSpace,
    PeriodMetrics,
    StrategyParamCombination,
)

logger = logging.getLogger("evaluation_engine")


class EvaluationValidationError(ValueError):
    """Raised when evaluation search space, split ratio, or candle data fail validation."""
    pass


class EvaluationEngine:
    """
    Chronological walk-forward strategy evaluation and robustness testing engine.
    
    Principles:
    1. Reuses a single historical dataset in-memory across all parameter sets.
    2. Strictly splits historical data chronologically into in-sample (train) and out-of-sample (test).
    3. Never randomly shuffles time series candles.
    4. Selects optimal parameters strictly using training performance (zero test leakage).
    5. Evaluates the selected parameters on unseen out-of-sample data with fees and slippage.
    6. Formulates quantitative overfitting alerts when strategies degrade on unseen data.
    """

    def __init__(self, request: EvaluationRequest):
        self.request = request
        self._validate_request()

    def _validate_request(self) -> None:
        if self.request.initial_capital <= 0:
            raise EvaluationValidationError("Initial capital must be strictly greater than 0.")
        if self.request.split_ratio < 0.50 or self.request.split_ratio > 0.90:
            raise EvaluationValidationError("split_ratio must be between 0.50 (50%) and 0.90 (90%).")
        if self.request.fee_rate < 0 or self.request.fee_rate > 0.05:
            raise EvaluationValidationError("Fee rate must be between 0.0 and 0.05 (5%).")
        if self.request.slippage_rate < 0 or self.request.slippage_rate > 0.05:
            raise EvaluationValidationError("Slippage rate must be between 0.0 and 0.05 (5%).")
        if (
            self.request.start_time is not None
            and self.request.end_time is not None
            and self.request.start_time >= self.request.end_time
        ):
            raise EvaluationValidationError(
                f"start_time ({self.request.start_time}) must be earlier than end_time ({self.request.end_time})."
            )
        if self.request.max_combinations < 1 or self.request.max_combinations > 200:
            raise EvaluationValidationError("max_combinations must be between 1 and 200.")

    def generate_parameter_combinations(
        self, search_space: ParameterSearchSpace
    ) -> Tuple[List[StrategyParamCombination], int]:
        """
        Generate and validate all discrete combinations in the search space.
        Rejects invalid configurations (e.g. fast_period >= slow_period).
        Enforces max_combinations boundary to prevent server resource exhaustion.
        
        Returns:
            (valid_combinations, filtered_invalid_count)
        """
        fast_list = search_space.fast_periods or [9]
        middle_list = search_space.middle_periods or [0]  # legacy callers derive a midpoint per fast/slow pair
        slow_list = search_space.slow_periods or [20]
        vol_list = search_space.volume_confirmation or [False]

        for f in fast_list:
            if not isinstance(f, int) or f < 2:
                raise EvaluationValidationError(f"Invalid fast_period {f}: must be an integer >= 2.")
        for m in middle_list:
            if m != 0 and (not isinstance(m, int) or m < 3):
                raise EvaluationValidationError(f"Invalid middle_period {m}: must be an integer >= 3.")
        for s in slow_list:
            if not isinstance(s, int) or s < 4:
                raise EvaluationValidationError(f"Invalid slow_period {s}: must be an integer >= 4.")

        total_cartesian = len(fast_list) * len(middle_list) * len(slow_list) * len(vol_list)
        valid_combinations: List[StrategyParamCombination] = []
        filtered_count = 0
        for fast, middle, slow, vol in itertools.product(fast_list, middle_list, slow_list, vol_list):
            if middle == 0:
                middle = (fast + slow) // 2
            if not (fast < middle < slow):
                filtered_count += 1
                continue
            valid_combinations.append(
                StrategyParamCombination(
                    fast_period=fast,
                    middle_period=middle,
                    slow_period=slow,
                    rsi_period=14,
                    rsi_buy_min=40.0,
                    rsi_sell_max=60.0,
                    volume_confirmation_enabled=bool(vol),
                    rsi_filter_enabled=False,
                    rsi_overbought=70.0,
                    rsi_oversold=30.0,
                    volume_ma_period=20,
                    sell_intent="CLOSE_LONG",
                )
            )

        if not valid_combinations:
            raise EvaluationValidationError(
                "No valid parameter combinations found. Ensure fast_period < middle_period < slow_period."
            )

        if len(valid_combinations) > self.request.max_combinations:
            raise EvaluationValidationError(
                f"Generated {len(valid_combinations)} valid combinations ({total_cartesian} total), which exceeds "
                f"the maximum allowed limit of {self.request.max_combinations}. Please narrow your parameter search space."
            )

        return valid_combinations, filtered_count

    def split_candles_chronologically(
        self, candles: List[Dict[str, Any]], max_slow_period: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Clean, sort, deduplicate, and chronologically split historical candles.
        Guarantees that train timestamps are strictly earlier than test timestamps.
        Never randomly shuffles data.
        """
        if not candles or len(candles) == 0:
            raise EvaluationValidationError(f"No candle data provided for {self.request.symbol}.")

        df = pd.DataFrame(candles)
        required_cols = ["time", "open", "high", "low", "close"]
        for col in required_cols:
            if col not in df.columns:
                raise EvaluationValidationError(f"Candle data missing required column '{col}'.")

        for col in ["time", "open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        else:
            df["volume"] = 0.0

        # Drop corrupted rows
        df = df.dropna(subset=["time", "open", "close"]).copy()
        df = df[(df["close"] > 0) & (df["open"] > 0)]
        df = df.drop_duplicates(subset=["time"], keep="first")
        # Strict chronological ascending sort
        df = df.sort_values(by="time", ascending=True).reset_index(drop=True)

        total_bars = len(df)
        split_ratio = self.request.split_ratio
        split_idx = int(total_bars * split_ratio)

        train_df = df.iloc[:split_idx].copy().reset_index(drop=True)
        test_df = df.iloc[split_idx:].copy().reset_index(drop=True)

        min_train_required = max_slow_period + 10
        min_test_required = max(15, min(max_slow_period + 5, 40))

        if len(train_df) < min_train_required:
            raise EvaluationValidationError(
                f"Insufficient in-sample historical data: training slice contains {len(train_df)} candles, "
                f"but at least {min_train_required} candles are required for the largest slow EMA ({max_slow_period}) warmup. "
                f"Please select a broader date range or lower resolution."
            )

        if len(test_df) < min_test_required:
            raise EvaluationValidationError(
                f"Insufficient out-of-sample historical data: testing slice contains {len(test_df)} candles, "
                f"which is less than the required minimum of {min_test_required} bars. "
                f"Adjust your train/test split ratio or select a broader date range."
            )

        # Strict chronological separation assertion
        train_max_time = train_df["time"].max()
        test_min_time = test_df["time"].min()
        if train_max_time >= test_min_time:
            raise EvaluationValidationError(
                f"Chronological split failed: train end time ({train_max_time}) >= test start time ({test_min_time})."
            )

        train_candles = train_df.to_dict(orient="records")
        test_candles = test_df.to_dict(orient="records")

        return train_candles, test_candles

    def _convert_metrics_to_period(
        self,
        b_metrics: BacktestMetrics,
        period_type: str,
        start_time: int,
        end_time: int,
        total_bars: int,
    ) -> PeriodMetrics:
        """Helper to convert standard BacktestMetrics to PeriodMetrics."""
        return PeriodMetrics(
            period_type="in_sample" if period_type == "in_sample" else "out_of_sample",
            start_time=start_time,
            end_time=end_time,
            total_bars=total_bars,
            initial_capital=b_metrics.initial_capital,
            final_equity=b_metrics.final_equity,
            net_profit=b_metrics.net_profit,
            net_return_pct=b_metrics.net_return_pct,
            max_drawdown_dollars=b_metrics.max_drawdown_dollars,
            max_drawdown_pct=b_metrics.max_drawdown_pct,
            total_trades=b_metrics.total_trades,
            winning_trades=b_metrics.winning_trades,
            losing_trades=b_metrics.losing_trades,
            break_even_trades=b_metrics.break_even_trades,
            win_rate_pct=b_metrics.win_rate_pct,
            loss_rate_pct=b_metrics.loss_rate_pct,
            profit_factor=b_metrics.profit_factor,
            gross_profit=b_metrics.gross_profit,
            gross_loss=b_metrics.gross_loss,
            avg_trade_pnl=b_metrics.avg_trade_pnl,
            total_fees_paid=b_metrics.total_fees_paid,
            market_exposure_pct=b_metrics.market_exposure_pct,
            buy_and_hold_return_pct=b_metrics.buy_and_hold_return_pct,
        )

    def _evaluate_overfitting(
        self, in_sample: PeriodMetrics, out_of_sample: PeriodMetrics
    ) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
        """
        Mathematically assess out-of-sample degradation and overfitting risk.
        
        Returns:
            (is_overfit, overfit_warning, robustness_ratio, return_degradation_pct, drawdown_increase_ratio)
        """
        train_ret = in_sample.net_return_pct
        test_ret = out_of_sample.net_return_pct
        train_dd = in_sample.max_drawdown_pct
        test_dd = out_of_sample.max_drawdown_pct

        return_degradation = round(train_ret - test_ret, 2)

        robustness_ratio: Optional[float] = None
        if train_ret > 0:
            robustness_ratio = round(test_ret / train_ret, 2)
        elif train_ret < 0 and test_ret > 0:
            robustness_ratio = 1.0  # Actually improved out of sample

        drawdown_increase_ratio: Optional[float] = None
        if train_dd > 0:
            drawdown_increase_ratio = round(test_dd / train_dd, 2)

        is_overfit = False
        warning: Optional[str] = None

        # Condition 1: Positive in-sample, negative out-of-sample (Inversion)
        if train_ret >= 3.0 and test_ret < -1.0:
            is_overfit = True
            warning = (
                f"Severe Return Inversion: Strategy generated +{train_ret:.1f}% in-sample, "
                f"but lost {test_ret:.1f}% out-of-sample on unseen data. High curve-fitting risk."
            )
        # Condition 2: High in-sample return, severe collapse (>70% drop)
        elif train_ret >= 5.0 and test_ret < (train_ret * 0.30):
            is_overfit = True
            warning = (
                f"Severe Return Degradation: Return dropped from +{train_ret:.1f}% in-sample "
                f"to +{test_ret:.1f}% out-of-sample (>70% degradation)."
            )
        # Condition 3: Drawdown surge (>2.5x increase in drawdown)
        elif test_dd > (2.5 * train_dd) and test_dd >= 5.0:
            is_overfit = True
            warning = (
                f"Drawdown Explosion: Out-of-sample max drawdown ({test_dd:.1f}%) is "
                f"{(test_dd / train_dd):.1f}x higher than in-sample ({train_dd:.1f}%)."
            )
        # Condition 4: Trade stagnation / regime freeze
        elif in_sample.total_trades >= 5 and out_of_sample.total_trades == 0:
            is_overfit = True
            warning = (
                f"Regime Stagnation: Triggered {in_sample.total_trades} trades during training, "
                f"but zero trades during out-of-sample testing."
            )
        # Condition 5: Win rate collapse
        elif (
            in_sample.total_trades >= 4
            and in_sample.win_rate_pct >= 60.0
            and out_of_sample.total_trades >= 3
            and out_of_sample.win_rate_pct < 35.0
        ):
            is_overfit = True
            warning = (
                f"Win Rate Collapse: Win rate plunged from {in_sample.win_rate_pct:.1f}% in-sample "
                f"to {out_of_sample.win_rate_pct:.1f}% out-of-sample."
            )

        return is_overfit, warning, robustness_ratio, return_degradation, drawdown_increase_ratio

    def run(self, candles: List[Dict[str, Any]]) -> EvaluationResult:
        """
        Execute bounded parameter optimization over in-sample training candles,
        and evaluate performance on separate out-of-sample testing candles.
        
        The winning strategy is chosen STRICTLY from in-sample performance.
        Candles are reused in memory without repeated network requests.
        """
        # 1. Generate & validate discrete parameter grid
        combinations, filtered_count = self.generate_parameter_combinations(self.request.search_space)
        max_slow = max(c.slow_period for c in combinations)

        # 2. Chronologically split candle dataset
        train_candles, test_candles = self.split_candles_chronologically(candles, max_slow)

        train_start = int(train_candles[0]["time"])
        train_end = int(train_candles[-1]["time"])
        test_start = int(test_candles[0]["time"])
        test_end = int(test_candles[-1]["time"])

        total_bars = len(train_candles) + len(test_candles)

        logger.info(
            f"Evaluating {len(combinations)} parameter sets on {self.request.symbol}: "
            f"Train={len(train_candles)} bars ({train_start}..{train_end}), "
            f"Test={len(test_candles)} bars ({test_start}..{test_end})"
        )

        evaluated_sets: List[Dict[str, Any]] = []

        # 3. Simulate each combination across Train and Test slices
        for combo in combinations:
            # Build parameter dict for strategy configuration
            strategy_params = combo.model_dump()

            # In-Sample Backtest Request
            train_req = BacktestRequest(
                symbol=self.request.symbol,
                resolution=self.request.resolution,
                start_time=train_start,
                end_time=train_end,
                initial_capital=self.request.initial_capital,
                fee_rate=self.request.fee_rate,
                slippage_rate=self.request.slippage_rate,
                execution_mode=self.request.execution_mode,
                strategy_params=strategy_params,
            )

            # Out-of-Sample Backtest Request
            test_req = BacktestRequest(
                symbol=self.request.symbol,
                resolution=self.request.resolution,
                start_time=test_start,
                end_time=test_end,
                initial_capital=self.request.initial_capital,
                fee_rate=self.request.fee_rate,
                slippage_rate=self.request.slippage_rate,
                execution_mode=self.request.execution_mode,
                strategy_params=strategy_params,
            )

            # Run in-sample backtest
            train_engine = BacktestEngine(train_req)
            train_result = train_engine.run(train_candles)

            # Run out-of-sample backtest
            test_engine = BacktestEngine(test_req)
            test_result = test_engine.run(test_candles)

            in_sample_metrics = self._convert_metrics_to_period(
                train_result.metrics, "in_sample", train_start, train_end, len(train_candles)
            )
            out_of_sample_metrics = self._convert_metrics_to_period(
                test_result.metrics, "out_of_sample", test_start, test_end, len(test_candles)
            )

            is_overfit, warning, rob_ratio, ret_deg, dd_ratio = self._evaluate_overfitting(
                in_sample_metrics, out_of_sample_metrics
            )

            vol_label = "Vol: On" if combo.volume_confirmation_enabled else "Vol: Off"
            label = f"Triple EMA {combo.fast_period}/{combo.middle_period}/{combo.slow_period} | {vol_label} | RSI off"

            evaluated_sets.append({
                "combo": combo,
                "label": label,
                "in_sample": in_sample_metrics,
                "out_of_sample": out_of_sample_metrics,
                "robustness_ratio": rob_ratio,
                "return_degradation_pct": ret_deg,
                "drawdown_increase_ratio": dd_ratio,
                "is_overfit": is_overfit,
                "overfit_warning": warning,
                "train_equity_curve": train_result.equity_curve,
                "test_equity_curve": test_result.equity_curve,
                "train_trades": train_result.trades,
                "test_trades": test_result.trades,
            })

        # 4. RANK STRICTLY BY IN-SAMPLE (TRAINING) PERFORMANCE
        # Critical anti-overfitting requirement: winning strategy selected using training data only!
        metric = self.request.ranking_metric

        def ranking_key(item: Dict[str, Any]) -> Tuple[float, float, float]:
            ins = item["in_sample"]
            if metric == "profit_factor":
                pf = ins.profit_factor if ins.profit_factor is not None else -1.0
                return (pf, ins.net_return_pct, -ins.max_drawdown_pct)
            elif metric == "win_rate_pct":
                return (ins.win_rate_pct, ins.net_return_pct, -ins.max_drawdown_pct)
            else:  # net_return_pct (default)
                pf = ins.profit_factor if ins.profit_factor is not None else 0.0
                return (ins.net_return_pct, pf, -ins.max_drawdown_pct)

        evaluated_sets.sort(key=ranking_key, reverse=True)

        # 5. Format results and assign ranks
        final_param_sets: List[EvaluatedParameterSet] = []
        for idx, item in enumerate(evaluated_sets, start=1):
            final_param_sets.append(
                EvaluatedParameterSet(
                    rank=idx,
                    params=item["combo"],
                    params_label=item["label"],
                    in_sample=item["in_sample"],
                    out_of_sample=item["out_of_sample"],
                    robustness_ratio=item["robustness_ratio"],
                    return_degradation_pct=item["return_degradation_pct"],
                    drawdown_increase_ratio=item["drawdown_increase_ratio"],
                    is_overfit=item["is_overfit"],
                    overfit_warning=item["overfit_warning"],
                )
            )

        winner = evaluated_sets[0]

        evaluation_id = f"eval_{uuid.uuid4().hex[:12]}"

        return EvaluationResult(
            evaluation_id=evaluation_id,
            symbol=self.request.symbol.upper(),
            resolution=self.request.resolution.lower(),
            execution_mode=self.request.execution_mode,
            total_bars=total_bars,
            split_ratio=self.request.split_ratio,
            train_bars=len(train_candles),
            test_bars=len(test_candles),
            train_start_time=train_start,
            train_end_time=train_end,
            test_start_time=test_start,
            test_end_time=test_end,
            total_combinations_requested=len(combinations) + filtered_count,
            total_combinations_evaluated=len(combinations),
            invalid_combinations_filtered=filtered_count,
            ranking_metric=self.request.ranking_metric,
            selected_winner_params=winner["combo"],
            selected_winner_label=winner["label"],
            selected_winner_is_overfit=winner["is_overfit"],
            selected_winner_overfit_warning=winner["overfit_warning"],
            parameter_sets=final_param_sets,
            winner_train_equity_curve=winner["train_equity_curve"],
            winner_test_equity_curve=winner["test_equity_curve"],
            winner_train_trades=winner["train_trades"],
            winner_test_trades=winner["test_trades"],
        )
