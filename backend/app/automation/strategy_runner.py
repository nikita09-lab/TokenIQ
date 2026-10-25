import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.automation.dedup import signal_deduplicator
from app.automation.models import AutomatedSignal, AutomationConfig, SignalLifecycleState
from app.automation.sizer import position_sizer, PositionSizingError
from app.strategies.base import PositionIntent, SignalType, StrategySignal
from app.strategies.ema_crossover import EMACrossoverStrategy

logger = logging.getLogger("automated_strategy_runner")


class AutomatedStrategyRunner:
    """
    Evaluates validated technical strategies against finalized market candles,
    calculates protective stops and sizing, and emits deduplicated AutomatedSignals.
    """

    def __init__(self):
        # We instantiate the validated repository strategy
        self._strategy = EMACrossoverStrategy()
        # Track last evaluated completed candle timestamp per (strategy, symbol, timeframe)
        self._last_evaluated_candles: Dict[str, int] = {}

    def configure_strategy(self, strategy_id: str, params: Dict[str, Any]) -> None:
        """Apply parameter updates to the active strategy."""
        if strategy_id != "ema_crossover":
            raise ValueError(f"Strategy '{strategy_id}' is not supported. Supported: 'ema_crossover'.")
        self._strategy.configure(params)
        logger.info(f"Strategy runner configured with parameters: {params}")

    def evaluate_candles(
        self,
        config: AutomationConfig,
        product_meta: Dict[str, Any],
        candles: List[Dict[str, Any]],
        current_position_side: Optional[str] = None,
        current_position_size: float = 0.0,
        available_margin_usd: Optional[float] = None,
    ) -> Optional[AutomatedSignal]:
        """
        Evaluate completed candles, determine trade intent and sizing, and produce an AutomatedSignal.
        
        Returns:
            AutomatedSignal if a fresh signal is produced, or None if no action / duplicate.
        """
        if not candles or len(candles) < 2:
            logger.debug("Insufficient candle history for evaluation.")
            return None

        symbol = config.trading_symbol.upper()
        timeframe = config.candle_interval

        # Ensure strategy parameters align with config
        self.configure_strategy(config.selected_strategy, config.strategy_parameters)

        # 1. Run core strategy evaluation on completed candles
        # Note: The strategy evaluate method evaluates candles chronologically
        try:
            raw_signal: StrategySignal = self._strategy.evaluate(
                candles=candles,
                symbol=symbol,
                resolution=timeframe,
            )
        except Exception as exc:
            logger.warning(f"Strategy evaluation error for {symbol} ({timeframe}): {exc}")
            return None

        candle_ts = int(raw_signal.candle_time or raw_signal.timestamp)
        cache_key = f"{config.selected_strategy}:{symbol}:{timeframe}"

        # 2. Check completed candle freshness
        # If require_confirmed_candle is True, do not re-evaluate the same completed candle
        if config.require_confirmed_candle:
            last_ts = self._last_evaluated_candles.get(cache_key)
            if last_ts is not None and candle_ts <= last_ts:
                # Candle already processed
                return None
            self._last_evaluated_candles[cache_key] = candle_ts

        close_price = float(raw_signal.close)
        if close_price <= 0:
            logger.warning(f"Invalid non-positive candle close price: {close_price}")
            return None

        # 3. Determine signal direction and position intent based on active position state
        signal_dir, resolved_intent = self._resolve_intent_and_direction(
            raw_signal=raw_signal,
            config=config,
            current_position_side=current_position_side,
            current_position_size=current_position_size,
        )

        if signal_dir == "NO_SIGNAL" or resolved_intent == "NO_ACTION":
            return None

        # 4. Calculate protective Stop-Loss and Take-Profit prices
        sl_price, tp_price = self._calculate_protection_levels(
            direction=signal_dir,
            intent=resolved_intent,
            entry_price=close_price,
            config=config,
            product_meta=product_meta,
        )

        # 5. Position Sizing
        # For exit signals (closing existing position), quantity is exactly current position size
        if resolved_intent in ("CLOSE_LONG", "CLOSE_SHORT"):
            intended_quantity = abs(current_position_size)
            if intended_quantity <= 0:
                logger.info(f"Exit signal generated but current position size is {current_position_size}.")
                return None
        else:
            # Entry sizing
            try:
                intended_quantity, _ = position_sizer.calculate_order_quantity(
                    config=config,
                    product_meta=product_meta,
                    entry_price=close_price,
                    stop_loss_price=sl_price,
                    available_margin_usd=available_margin_usd,
                    current_position_size=current_position_size,
                )
            except PositionSizingError as sizer_err:
                logger.warning(f"Position sizing rejected order: {sizer_err}")
                idempotency_key = signal_deduplicator.generate_idempotency_key(
                    strategy_id=config.selected_strategy,
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_timestamp=candle_ts,
                    signal_direction=signal_dir,
                    position_intent=resolved_intent,
                )
                signal_id = f"sig_{symbol}_{candle_ts}_{uuid.uuid4().hex[:6]}"
                return AutomatedSignal(
                    signal_id=signal_id,
                    strategy_id=config.selected_strategy,
                    strategy_version="1.0.0",
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_timestamp=candle_ts,
                    signal_direction=signal_dir,
                    position_intent=resolved_intent,
                    entry_rationale=raw_signal.explanation,
                    intended_price=close_price,
                    intended_quantity=0.0,
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price,
                    idempotency_key=idempotency_key,
                    lifecycle_state=SignalLifecycleState.REJECTED,
                    rejection_reason=f"Position sizing rejected: {sizer_err}",
                )

        # 6. Generate Idempotency Key & Construct AutomatedSignal
        idempotency_key = signal_deduplicator.generate_idempotency_key(
            strategy_id=config.selected_strategy,
            symbol=symbol,
            timeframe=timeframe,
            candle_timestamp=candle_ts,
            signal_direction=signal_dir,
            position_intent=resolved_intent,
        )

        signal_id = f"sig_{symbol}_{candle_ts}_{uuid.uuid4().hex[:6]}"

        automated_signal = AutomatedSignal(
            signal_id=signal_id,
            strategy_id=config.selected_strategy,
            strategy_version="1.0.0",
            symbol=symbol,
            timeframe=timeframe,
            candle_timestamp=candle_ts,
            signal_direction=signal_dir,
            position_intent=resolved_intent,
            entry_rationale=raw_signal.explanation,
            intended_price=close_price,
            intended_quantity=intended_quantity,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            idempotency_key=idempotency_key,
            lifecycle_state=SignalLifecycleState.GENERATED,
        )

        return automated_signal

    def _resolve_intent_and_direction(
        self,
        raw_signal: StrategySignal,
        config: AutomationConfig,
        current_position_side: Optional[str],
        current_position_size: float,
    ) -> Tuple[str, str]:
        """
        Translates raw indicator signal into actionable trading directive,
        distinguishing entry vs exit and respecting allow_long / allow_short.
        """
        has_long = current_position_side == "LONG" and current_position_size > 0
        has_short = current_position_side == "SHORT" and current_position_size > 0
        is_flat = not has_long and not has_short

        if raw_signal.signal == SignalType.BUY:
            if has_short:
                # Exit short
                return "EXIT_SHORT", "CLOSE_SHORT"
            elif is_flat:
                if not config.allow_long:
                    logger.debug("BUY signal ignored: allow_long is disabled.")
                    return "NO_SIGNAL", "NO_ACTION"
                return "BUY", "OPEN_LONG"
            elif has_long:
                if config.allow_pyramiding:
                    return "BUY", "OPEN_LONG"
                else:
                    return "NO_SIGNAL", "NO_ACTION"

        elif raw_signal.signal == SignalType.SELL:
            if has_long:
                # Closing existing long
                return "EXIT_LONG", "CLOSE_LONG"
            elif is_flat:
                if not config.allow_short:
                    logger.debug("SELL signal ignored for entry: allow_short is disabled.")
                    return "NO_SIGNAL", "NO_ACTION"
                return "SELL", "OPEN_SHORT"
            elif has_short:
                if config.allow_pyramiding:
                    return "SELL", "OPEN_SHORT"
                else:
                    return "NO_SIGNAL", "NO_ACTION"

        return "NO_SIGNAL", "NO_ACTION"

    def _calculate_protection_levels(
        self,
        direction: str,
        intent: str,
        entry_price: float,
        config: AutomationConfig,
        product_meta: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate price-aligned stop-loss and take-profit levels.
        For exits, protection is not required (returns None, None).
        """
        if intent in ("CLOSE_LONG", "CLOSE_SHORT"):
            return None, None

        tick_size = float(product_meta.get("tick_size") or 0.1)
        sl_pct = config.protective_stop_loss_percentage / 100.0
        tp_pct = (config.take_profit_percentage / 100.0) if config.take_profit_percentage else None

        if direction == "BUY":  # Long position
            raw_sl = entry_price * (1.0 - sl_pct)
            sl_price = round(round(raw_sl / tick_size) * tick_size, 4)
            tp_price = None
            if tp_pct:
                raw_tp = entry_price * (1.0 + tp_pct)
                tp_price = round(round(raw_tp / tick_size) * tick_size, 4)

        elif direction == "SELL":  # Short position
            raw_sl = entry_price * (1.0 + sl_pct)
            sl_price = round(round(raw_sl / tick_size) * tick_size, 4)
            tp_price = None
            if tp_pct:
                raw_tp = entry_price * (1.0 - tp_pct)
                tp_price = round(round(raw_tp / tick_size) * tick_size, 4)

        else:
            return None, None

        return sl_price, tp_price


strategy_runner = AutomatedStrategyRunner()
