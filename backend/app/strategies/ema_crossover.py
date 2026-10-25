import logging
import time
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from app.strategies.base import BaseStrategy, PositionIntent, SignalType, StrategySignal
from app.strategies.indicators import calculate_ema, calculate_rsi, calculate_sma

logger = logging.getLogger("ema_crossover_strategy")


class InsufficientDataError(ValueError):
    """Raised when the candle history has fewer bars than required by the strategy indicators."""
    pass


class InvalidCandleDataError(ValueError):
    """Raised when candle data is malformed, missing, or non-numeric."""
    pass


class EMACrossoverStrategy(BaseStrategy):
    """
    Triple Exponential Moving Average (EMA) crossover strategy with optional volume confirmation.

    Default trend stack is EMA 9 / EMA 11 / EMA 20. RSI filtering is disabled by default.
    Signals are evaluated strictly on completed candles.
        * For BUY: momentum must be present (RSI >= rsi_buy_min) and not overbought (RSI <= rsi_overbought).
        * For SELL: downward momentum (RSI <= rsi_sell_max) and not oversold (RSI >= rsi_oversold).
    - Volume Filter (optional):
        * Current candle volume must exceed the volume SMA.
    - Evaluated strictly on COMPLETED candles to avoid look-ahead bias.
    """

    DEFAULT_PARAMETERS = {
        "fast_period": 9,
        "middle_period": 11,
        "slow_period": 20,
        "rsi_period": 14,
        "rsi_filter_enabled": False,
        "rsi_buy_min": 40.0,
        "rsi_overbought": 70.0,
        "rsi_sell_max": 60.0,
        "rsi_oversold": 30.0,
        "volume_confirmation_enabled": False,
        "volume_ma_period": 20,
        "sell_intent": "CLOSE_LONG",  # Options: "CLOSE_LONG", "OPEN_SHORT", "CLOSE_LONG_OR_OPEN_SHORT"
    }

    def __init__(
        self,
        strategy_id: str = "ema_crossover",
        name: str = "Triple EMA Crossover (9/11/20)",
        description: str = (
            "Triple EMA trend-following strategy using 9/11/20 defaults; RSI filter is off by default."
        ),
        custom_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(strategy_id, name, description)
        self.parameters = dict(self.DEFAULT_PARAMETERS)
        # Preserve the previous two-EMA behavior for older API clients that do not send middle_period.
        self._legacy_two_ema = bool(custom_params and "middle_period" not in custom_params)
        if custom_params:
            self.configure(custom_params)

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return parameter metadata, types, constraints, and current values."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "parameters": {
                "fast_period": {
                    "type": "integer",
                    "default": 9,
                    "min": 2,
                    "max": 200,
                    "description": "Period for Fast Exponential Moving Average",
                    "current": self.parameters["fast_period"],
                },
                "middle_period": {
                    "type": "integer",
                    "default": 11,
                    "min": 3,
                    "max": 300,
                    "description": "Period for Middle Exponential Moving Average (must be between fast and slow)",
                    "current": self.parameters["middle_period"],
                },
                "slow_period": {
                    "type": "integer",
                    "default": 20,
                    "min": 4,
                    "max": 500,
                    "description": "Period for Slow Exponential Moving Average (must be > middle_period)",
                    "current": self.parameters["slow_period"],
                },
                "rsi_period": {
                    "type": "integer",
                    "default": 14,
                    "min": 2,
                    "max": 100,
                    "description": "Period for Relative Strength Index",
                    "current": self.parameters["rsi_period"],
                },
                "rsi_filter_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": "Optional RSI filter; disabled by default for the triple-EMA strategy",
                    "current": self.parameters["rsi_filter_enabled"],
                },
                "rsi_buy_min": {
                    "type": "number",
                    "default": 40.0,
                    "min": 0.0,
                    "max": 100.0,
                    "description": "Minimum RSI required to confirm BUY signal",
                    "current": self.parameters["rsi_buy_min"],
                },
                "rsi_overbought": {
                    "type": "number",
                    "default": 70.0,
                    "min": 50.0,
                    "max": 100.0,
                    "description": "Upper RSI boundary above which BUY signals are rejected (overbought)",
                    "current": self.parameters["rsi_overbought"],
                },
                "rsi_sell_max": {
                    "type": "number",
                    "default": 60.0,
                    "min": 0.0,
                    "max": 100.0,
                    "description": "Maximum RSI required to confirm SELL signal",
                    "current": self.parameters["rsi_sell_max"],
                },
                "rsi_oversold": {
                    "type": "number",
                    "default": 30.0,
                    "min": 0.0,
                    "max": 50.0,
                    "description": "Lower RSI boundary below which SELL signals are rejected (oversold)",
                    "current": self.parameters["rsi_oversold"],
                },
                "volume_confirmation_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to require candle volume > volume SMA",
                    "current": self.parameters["volume_confirmation_enabled"],
                },
                "volume_ma_period": {
                    "type": "integer",
                    "default": 20,
                    "min": 2,
                    "max": 200,
                    "description": "Period for volume Simple Moving Average",
                    "current": self.parameters["volume_ma_period"],
                },
                "sell_intent": {
                    "type": "string",
                    "enum": ["CLOSE_LONG", "OPEN_SHORT", "CLOSE_LONG_OR_OPEN_SHORT"],
                    "default": "CLOSE_LONG",
                    "description": (
                        "Defines whether SELL means closing an existing long position ('CLOSE_LONG') "
                        "or entering a short position ('OPEN_SHORT')."
                    ),
                    "current": self.parameters["sell_intent"],
                },
            },
        }

    def configure(self, params: Dict[str, Any]) -> None:
        """Validate and apply updated strategy parameters."""
        validated = dict(self.parameters)

        if "fast_period" in params:
            val = int(params["fast_period"])
            if val < 2:
                raise ValueError("fast_period must be >= 2")
            validated["fast_period"] = val

        if "middle_period" in params:
            val = int(params["middle_period"])
            if val < 3:
                raise ValueError("middle_period must be >= 3")
            validated["middle_period"] = val

        if "slow_period" in params:
            val = int(params["slow_period"])
            if val < 4:
                raise ValueError("slow_period must be >= 4")
            validated["slow_period"] = val

        if validated["fast_period"] >= validated["slow_period"]:
            raise ValueError(
                f"fast_period ({validated['fast_period']}) must be strictly less than slow_period ({validated['slow_period']})"
            )
        # Backwards-compatible customizations that only set fast/slow still get a valid middle EMA.
        if "middle_period" not in params and not (validated["fast_period"] < validated["middle_period"] < validated["slow_period"]):
            if validated["slow_period"] - validated["fast_period"] < 2:
                raise ValueError("EMA periods must leave room for a middle_period between fast and slow")
            validated["middle_period"] = (validated["fast_period"] + validated["slow_period"]) // 2
        if not (validated["fast_period"] < validated["middle_period"] < validated["slow_period"]):
            raise ValueError("EMA periods must satisfy fast_period < middle_period < slow_period")

        if "rsi_period" in params:
            val = int(params["rsi_period"])
            if val < 2:
                raise ValueError("rsi_period must be >= 2")
            validated["rsi_period"] = val

        if "rsi_filter_enabled" in params:
            validated["rsi_filter_enabled"] = bool(params["rsi_filter_enabled"])

        if "rsi_buy_min" in params:
            val = float(params["rsi_buy_min"])
            if not 0.0 <= val <= 100.0:
                raise ValueError("rsi_buy_min must be between 0.0 and 100.0")
            validated["rsi_buy_min"] = val

        if "rsi_overbought" in params:
            val = float(params["rsi_overbought"])
            if not 0.0 <= val <= 100.0:
                raise ValueError("rsi_overbought must be between 0.0 and 100.0")
            validated["rsi_overbought"] = val

        if "rsi_sell_max" in params:
            val = float(params["rsi_sell_max"])
            if not 0.0 <= val <= 100.0:
                raise ValueError("rsi_sell_max must be between 0.0 and 100.0")
            validated["rsi_sell_max"] = val

        if "rsi_oversold" in params:
            val = float(params["rsi_oversold"])
            if not 0.0 <= val <= 100.0:
                raise ValueError("rsi_oversold must be between 0.0 and 100.0")
            validated["rsi_oversold"] = val

        if "volume_confirmation_enabled" in params:
            validated["volume_confirmation_enabled"] = bool(params["volume_confirmation_enabled"])

        if "volume_ma_period" in params:
            val = int(params["volume_ma_period"])
            if val < 2:
                raise ValueError("volume_ma_period must be >= 2")
            validated["volume_ma_period"] = val

        if "sell_intent" in params:
            intent_val = str(params["sell_intent"]).upper()
            valid_intents = ["CLOSE_LONG", "OPEN_SHORT", "CLOSE_LONG_OR_OPEN_SHORT"]
            if intent_val not in valid_intents:
                raise ValueError(f"sell_intent must be one of {valid_intents}, got {intent_val}")
            validated["sell_intent"] = intent_val

        self.parameters = validated

    @staticmethod
    def _get_resolution_seconds(resolution: str) -> int:
        mapping = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "6h": 21600,
            "1d": 86400,
        }
        return mapping.get(resolution.lower(), 3600)

    def _filter_completed_candles(
        self,
        candles: List[Dict[str, Any]],
        resolution: str,
        reference_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ensure only completed candles are included in calculations.
        If the newest candle is still forming (its period hasn't ended), exclude it.
        """
        if not candles:
            return []

        # Sort ascending by time
        sorted_candles = sorted(candles, key=lambda c: int(c.get("time", 0)))
        now = reference_time if reference_time is not None else int(time.time())
        res_seconds = self._get_resolution_seconds(resolution)

        # Check if the last candle is still forming
        last_candle = sorted_candles[-1]
        candle_open_time = int(last_candle.get("time", 0))

        # A candle is complete when current time >= candle_open_time + res_seconds
        if now < (candle_open_time + res_seconds):
            # Still in progress -> exclude last candle
            completed = sorted_candles[:-1]
        else:
            completed = sorted_candles

        return completed

    def evaluate(
        self,
        candles: List[Dict[str, Any]],
        symbol: str,
        resolution: str = "1h",
        reference_time: Optional[int] = None,
        allow_incomplete_candle: bool = False,
    ) -> StrategySignal:
        """
        Evaluate candle data and generate a structured signal for completed candles.
        """
        sym = symbol.upper()
        if not candles or len(candles) == 0:
            raise InsufficientDataError(f"No candle data provided for {sym}.")

        # Filter completed candles
        if allow_incomplete_candle:
            eval_candles = sorted(candles, key=lambda c: int(c.get("time", 0)))
        else:
            eval_candles = self._filter_completed_candles(candles, resolution, reference_time)

        min_required = max(
            self.parameters["slow_period"],
            self.parameters["rsi_period"] if self.parameters["rsi_filter_enabled"] else 0,
            self.parameters["volume_ma_period"] if self.parameters["volume_confirmation_enabled"] else 0,
        ) + 2

        if len(eval_candles) < min_required:
            raise InsufficientDataError(
                f"Insufficient completed candles for {sym}. Received {len(eval_candles)} completed bars, "
                f"but strategy requires at least {min_required} bars for the EMA stack "
                f"({self.parameters['fast_period']}/{self.parameters['middle_period']}/{self.parameters['slow_period']})."
            )

        # Convert to DataFrame
        try:
            df = pd.DataFrame(eval_candles)
            required_cols = ["time", "close"]
            for col in required_cols:
                if col not in df.columns:
                    raise InvalidCandleDataError(f"Candle data missing required field '{col}'")

            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["time"] = pd.to_numeric(df["time"], errors="coerce")

            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
            else:
                df["volume"] = 0.0

            # Drop any corrupted rows with NaN time or close
            df = df.dropna(subset=["time", "close"]).copy()
            df = df[df["close"] > 0]  # Valid positive price

            if len(df) < min_required:
                raise InsufficientDataError(
                    f"Only {len(df)} valid non-null candle rows remain after cleaning; requires {min_required}."
                )

        except Exception as exc:
            if isinstance(exc, (InsufficientDataError, InvalidCandleDataError)):
                raise
            raise InvalidCandleDataError(f"Failed to process candle data: {exc}")

        # Compute technical indicators
        fast_p = self.parameters["fast_period"]
        middle_p = self.parameters["middle_period"]
        slow_p = self.parameters["slow_period"]
        rsi_p = self.parameters["rsi_period"]
        vol_p = self.parameters["volume_ma_period"]

        df["fast_ema"] = calculate_ema(df["close"], fast_p)
        df["middle_ema"] = calculate_ema(df["close"], middle_p)
        df["slow_ema"] = calculate_ema(df["close"], slow_p)
        df["rsi"] = calculate_rsi(df["close"], rsi_p)

        if self.parameters["volume_confirmation_enabled"]:
            df["volume_ma"] = calculate_sma(df["volume"], vol_p)
        else:
            df["volume_ma"] = np.nan

        # Current completed candle (last row) and previous completed candle (second to last)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        curr_time = int(curr["time"])
        curr_close = float(curr["close"])
        curr_fast = float(curr["fast_ema"])
        curr_middle = float(curr["middle_ema"])
        curr_slow = float(curr["slow_ema"])
        curr_rsi = float(curr["rsi"]) if not np.isnan(curr["rsi"]) else None
        curr_vol = float(curr["volume"]) if not np.isnan(curr["volume"]) else None
        curr_vol_ma = float(curr["volume_ma"]) if not np.isnan(curr["volume_ma"]) else None

        prev_fast = float(prev["fast_ema"])
        prev_middle = float(prev["middle_ema"])
        prev_slow = float(prev["slow_ema"])

        # Check for repeated evaluation on the exact same completed candle
        last_eval_time = self._last_evaluated_candle.get(sym)
        is_repeated = (last_eval_time is not None and last_eval_time == curr_time)

        # Triple-EMA confirmation: fast crosses middle while the middle/slow trend stack agrees.
        if self._legacy_two_ema:
            bullish_crossover = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
            bearish_crossover = (prev_fast >= prev_slow) and (curr_fast < curr_slow)
        else:
            bullish_crossover = (prev_fast <= prev_middle) and (curr_fast > curr_middle) and (curr_middle > curr_slow)
            bearish_crossover = (prev_fast >= prev_middle) and (curr_fast < curr_middle) and (curr_middle < curr_slow)

        signal_type = SignalType.HOLD
        position_intent = PositionIntent.NO_ACTION
        explanation_parts = []

        # RSI filter checks
        rsi_filter = self.parameters["rsi_filter_enabled"]
        rsi_buy_min = self.parameters["rsi_buy_min"]
        rsi_overbought = self.parameters["rsi_overbought"]
        rsi_sell_max = self.parameters["rsi_sell_max"]
        rsi_oversold = self.parameters["rsi_oversold"]

        # Volume filter checks
        vol_filter = self.parameters["volume_confirmation_enabled"]

        configured_sell_intent = PositionIntent(self.parameters["sell_intent"])

        if is_repeated:
            signal_type = SignalType.HOLD
            position_intent = PositionIntent.NO_ACTION
            explanation = (
                f"HOLD (Repeated): Completed candle at timestamp {curr_time} was already evaluated. "
                f"No new completed {resolution} bar has closed yet. "
                f"Triple EMA stack: fast {curr_fast:.2f}, middle {curr_middle:.2f}, slow {curr_slow:.2f}."
            )
        elif bullish_crossover:
            # Check RSI filter for BUY
            rsi_ok = True
            rsi_reason = ""
            if rsi_filter and curr_rsi is not None:
                if curr_rsi > rsi_overbought:
                    rsi_ok = False
                    rsi_reason = f"RSI ({curr_rsi:.1f}) is in overbought territory (> {rsi_overbought:.1f})"
                elif curr_rsi < rsi_buy_min:
                    rsi_ok = False
                    rsi_reason = f"RSI ({curr_rsi:.1f}) lacks bullish momentum (< {rsi_buy_min:.1f})"

            # Check Volume filter
            vol_ok = True
            vol_reason = ""
            if vol_filter and curr_vol is not None and curr_vol_ma is not None:
                if curr_vol <= curr_vol_ma:
                    vol_ok = False
                    vol_reason = f"Volume ({curr_vol:.1f}) is below {vol_p}-period SMA ({curr_vol_ma:.1f})"

            if rsi_ok and vol_ok:
                signal_type = SignalType.BUY
                position_intent = PositionIntent.OPEN_LONG
                explanation = (
                    f"BUY (OPEN_LONG): Bullish Golden Cross detected on completed candle. "
                    f"Fast EMA {fast_p} crossed above Middle EMA {self.parameters['middle_period']} with the Middle EMA above Slow EMA {slow_p}. "
                    + (f"RSI confirmation: {curr_rsi:.1f}." if rsi_filter and curr_rsi is not None else "RSI filter is off.")
                )
                if vol_filter and curr_vol_ma:
                    explanation += f" Volume confirmed at {curr_vol:.1f} (> {vol_p}-SMA {curr_vol_ma:.1f})."
            else:
                signal_type = SignalType.HOLD
                position_intent = PositionIntent.NO_ACTION
                filtered_reasons = []
                if not rsi_ok:
                    filtered_reasons.append(rsi_reason)
                if not vol_ok:
                    filtered_reasons.append(vol_reason)
                explanation = (
                    f"HOLD: Bullish EMA crossover occurred, but signal was filtered out: "
                    f"{'; '.join(filtered_reasons)}."
                )

        elif bearish_crossover:
            # Check RSI filter for SELL
            rsi_ok = True
            rsi_reason = ""
            if rsi_filter and curr_rsi is not None:
                if curr_rsi < rsi_oversold:
                    rsi_ok = False
                    rsi_reason = f"RSI ({curr_rsi:.1f}) is in oversold territory (< {rsi_oversold:.1f})"
                elif curr_rsi > rsi_sell_max:
                    rsi_ok = False
                    rsi_reason = f"RSI ({curr_rsi:.1f}) still shows bullish bias (> {rsi_sell_max:.1f})"

            # Check Volume filter
            vol_ok = True
            vol_reason = ""
            if vol_filter and curr_vol is not None and curr_vol_ma is not None:
                if curr_vol <= curr_vol_ma:
                    vol_ok = False
                    vol_reason = f"Volume ({curr_vol:.1f}) is below {vol_p}-period SMA ({curr_vol_ma:.1f})"

            if rsi_ok and vol_ok:
                signal_type = SignalType.SELL
                position_intent = configured_sell_intent
                intent_desc = (
                    "Closing existing Long position"
                    if configured_sell_intent == PositionIntent.CLOSE_LONG
                    else "Opening new Short position"
                    if configured_sell_intent == PositionIntent.OPEN_SHORT
                    else "Closing Long or Opening Short"
                )
                explanation = (
                    f"SELL ({configured_sell_intent.value} - {intent_desc}): "
                    f"Bearish Death Cross detected on completed candle. "
                    f"Fast EMA {fast_p} crossed below Middle EMA {self.parameters['middle_period']} with the Middle EMA below Slow EMA {slow_p}. "
                    + (f"RSI confirmation: {curr_rsi:.1f}." if rsi_filter and curr_rsi is not None else "RSI filter is off.")
                )
                if vol_filter and curr_vol_ma:
                    explanation += f" Volume confirmed at {curr_vol:.1f} (> {vol_p}-SMA {curr_vol_ma:.1f})."
            else:
                signal_type = SignalType.HOLD
                position_intent = PositionIntent.NO_ACTION
                filtered_reasons = []
                if not rsi_ok:
                    filtered_reasons.append(rsi_reason)
                if not vol_ok:
                    filtered_reasons.append(vol_reason)
                explanation = (
                    f"HOLD: Bearish EMA crossover occurred, but signal was filtered out: "
                    f"{'; '.join(filtered_reasons)}."
                )

        else:
            signal_type = SignalType.HOLD
            position_intent = PositionIntent.NO_ACTION
            trend = "Bullish" if curr_fast >= curr_slow else "Bearish"
            diff = abs(curr_fast - curr_slow)
            rsi_str = f"{curr_rsi:.1f}" if curr_rsi is not None else "N/A"
            explanation = (
                f"HOLD: No new crossover on completed candle. "
                f"EMA stack is Fast {curr_fast:.2f}, Middle {curr_middle:.2f}, Slow {curr_slow:.2f} "
                f"(trend: {trend}). "
                f"RSI={rsi_str}."
            )

        # Update last evaluated timestamp to prevent repeated signals on the exact same bar
        self._last_evaluated_candle[sym] = curr_time

        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            symbol=sym,
            resolution=resolution,
            signal=signal_type,
            position_intent=position_intent,
            timestamp=curr_time,
            candle_time=curr_time,
            close=curr_close,
            fast_ema=round(curr_fast, 4),
            slow_ema=round(curr_slow, 4),
            rsi=round(curr_rsi, 2) if curr_rsi is not None else None,
            volume=round(curr_vol, 2) if curr_vol is not None else None,
            volume_ma=round(curr_vol_ma, 2) if curr_vol_ma is not None else None,
            explanation=explanation,
            is_repeated=is_repeated,
            metrics={
                "prev_fast_ema": round(prev_fast, 4),
                "prev_slow_ema": round(prev_slow, 4),
                "bullish_crossover": bool(bullish_crossover),
                "bearish_crossover": bool(bearish_crossover),
                "fast_period": fast_p,
                "slow_period": slow_p,
                "rsi_period": rsi_p,
                "volume_ma_period": vol_p,
                "volume_confirmation_enabled": vol_filter,
                "rsi_filter_enabled": rsi_filter,
                "sell_intent_configured": self.parameters["sell_intent"],
                "total_completed_candles_analyzed": len(df),
            },
        )

        self._latest_signals[sym] = signal
        return signal
