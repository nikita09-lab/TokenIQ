import logging
import math
import uuid
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from app.backtesting.models import (
    BacktestMetrics,
    BacktestRequest,
    BacktestResult,
    EquityPoint,
    Trade,
)
from app.strategies.ema_crossover import EMACrossoverStrategy, InsufficientDataError
from app.strategies.indicators import calculate_ema, calculate_rsi, calculate_sma

logger = logging.getLogger("backtest_engine")


class BacktestValidationError(ValueError):
    """Raised when request parameters, date ranges, or candles fail validation."""
    pass


class BacktestEngine:
    """
    Chronological, event-driven backtesting simulation engine for TokenIQ.
    Prevents look-ahead bias by executing trade signals on the open of the subsequent candle.
    Models long-only positions, configurable fees, and execution slippage.
    """

    def __init__(self, request: BacktestRequest):
        self.request = request
        self._validate_request()
        self.strategy = EMACrossoverStrategy(custom_params=request.strategy_params)

    def _validate_request(self) -> None:
        if self.request.initial_capital <= 0:
            raise BacktestValidationError("Initial capital must be strictly greater than 0.")
        if self.request.fee_rate < 0 or self.request.fee_rate > 0.05:
            raise BacktestValidationError("Fee rate must be between 0.0 and 0.05 (5%).")
        if self.request.slippage_rate < 0 or self.request.slippage_rate > 0.05:
            raise BacktestValidationError("Slippage rate must be between 0.0 and 0.05 (5%).")
        if (
            self.request.start_time is not None
            and self.request.end_time is not None
            and self.request.start_time >= self.request.end_time
        ):
            raise BacktestValidationError(
                f"start_time ({self.request.start_time}) must be strictly earlier than end_time ({self.request.end_time})."
            )

    def _prepare_dataframe(self, candles: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Clean, deduplicate, validate, and compute technical indicators over historical candles.
        """
        if not candles or len(candles) == 0:
            raise BacktestValidationError(f"No candle data provided for {self.request.symbol}.")

        df = pd.DataFrame(candles)
        required_cols = ["time", "open", "high", "low", "close"]
        for col in required_cols:
            if col not in df.columns:
                raise BacktestValidationError(f"Candle data missing required column '{col}'.")

        # Convert to numeric float/int types
        for col in ["time", "open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        else:
            df["volume"] = 0.0

        # Drop corrupted rows & non-positive prices
        df = df.dropna(subset=["time", "open", "close"]).copy()
        df = df[(df["close"] > 0) & (df["open"] > 0)]

        # Deduplicate duplicate timestamps, keeping first
        df = df.drop_duplicates(subset=["time"], keep="first")

        # Sort ascending chronologically
        df = df.sort_values(by="time", ascending=True).reset_index(drop=True)

        min_required = max(
            self.strategy.parameters["slow_period"],
            self.strategy.parameters["rsi_period"],
            self.strategy.parameters["volume_ma_period"] if self.strategy.parameters["volume_confirmation_enabled"] else 0,
        ) + 5

        if len(df) < min_required:
            raise BacktestValidationError(
                f"Insufficient historical data: received {len(df)} valid candles, but strategy requires "
                f"at least {min_required} bars for {self.strategy.parameters['slow_period']}-EMA warmup."
            )

        # Compute technical indicators
        fast_p = self.strategy.parameters["fast_period"]
        slow_p = self.strategy.parameters["slow_period"]
        rsi_p = self.strategy.parameters["rsi_period"]
        vol_p = self.strategy.parameters["volume_ma_period"]

        df["fast_ema"] = calculate_ema(df["close"], fast_p)
        df["slow_ema"] = calculate_ema(df["close"], slow_p)
        df["rsi"] = calculate_rsi(df["close"], rsi_p)

        if self.strategy.parameters["volume_confirmation_enabled"]:
            df["volume_ma"] = calculate_sma(df["volume"], vol_p)
        else:
            df["volume_ma"] = np.nan

        return df

    def run(self, candles: List[Dict[str, Any]]) -> BacktestResult:
        """
        Execute the chronological simulation over completed bars.
        """
        df = self._prepare_dataframe(candles)
        n_bars = len(df)

        fee_rate = self.request.fee_rate
        slippage_rate = self.request.slippage_rate
        exec_mode = self.request.execution_mode

        # Strategy parameters
        rsi_filter = self.strategy.parameters["rsi_filter_enabled"]
        rsi_buy_min = self.strategy.parameters["rsi_buy_min"]
        rsi_overbought = self.strategy.parameters["rsi_overbought"]
        rsi_sell_max = self.strategy.parameters["rsi_sell_max"]
        rsi_oversold = self.strategy.parameters["rsi_oversold"]
        vol_filter = self.strategy.parameters["volume_confirmation_enabled"]
        warmup_idx = max(
            self.strategy.parameters["slow_period"],
            self.strategy.parameters["rsi_period"],
        ) + 1

        # State tracking
        cash = float(self.request.initial_capital)
        position_qty = 0.0
        entry_price = 0.0
        entry_time = 0
        entry_fee = 0.0
        cost_basis = 0.0

        pending_signal: Optional[str] = None  # "BUY" or "SELL"
        trades: List[Trade] = []
        equity_curve: List[EquityPoint] = []
        trade_id = 1
        peak_equity = cash
        bars_in_position = 0

        for i in range(n_bars):
            curr_bar = df.iloc[i]
            bar_time = int(curr_bar["time"])
            open_price = float(curr_bar["open"])
            close_price = float(curr_bar["close"])

            # -------------------------------------------------------------
            # 1. Execute any pending order from previous candle (Look-ahead prevention)
            # -------------------------------------------------------------
            if exec_mode == "next_open" and pending_signal is not None:
                if pending_signal == "BUY" and position_qty == 0.0 and cash > 0.0:
                    fill_price = open_price * (1.0 + slippage_rate)
                    cost_per_unit = fill_price * (1.0 + fee_rate)
                    qty = cash / cost_per_unit
                    trade_cost = qty * fill_price
                    fee = trade_cost * fee_rate

                    cash -= (trade_cost + fee)
                    position_qty = qty
                    entry_price = fill_price
                    entry_time = bar_time
                    entry_fee = fee
                    cost_basis = trade_cost

                elif pending_signal == "SELL" and position_qty > 0.0:
                    fill_price = open_price * (1.0 - slippage_rate)
                    gross_proceeds = position_qty * fill_price
                    exit_fee = gross_proceeds * fee_rate
                    net_proceeds = gross_proceeds - exit_fee
                    gross_pnl = gross_proceeds - cost_basis
                    net_pnl = gross_pnl - (entry_fee + exit_fee)
                    total_fees = entry_fee + exit_fee
                    return_pct = (net_pnl / (cost_basis + entry_fee)) * 100.0 if (cost_basis + entry_fee) > 0 else 0.0

                    cash += net_proceeds

                    trades.append(
                        Trade(
                            trade_id=trade_id,
                            symbol=self.request.symbol.upper(),
                            side="LONG",
                            entry_time=entry_time,
                            entry_price=round(entry_price, 4),
                            entry_fee=round(entry_fee, 4),
                            exit_time=bar_time,
                            exit_price=round(fill_price, 4),
                            exit_fee=round(exit_fee, 4),
                            total_fees=round(total_fees, 4),
                            quantity=round(position_qty, 6),
                            cost_basis=round(cost_basis, 2),
                            proceeds=round(net_proceeds, 2),
                            gross_pnl=round(gross_pnl, 2),
                            net_pnl=round(net_pnl, 2),
                            return_pct=round(return_pct, 2),
                            exit_reason="SELL_SIGNAL",
                            duration_seconds=bar_time - entry_time,
                        )
                    )
                    trade_id += 1
                    position_qty = 0.0
                    entry_price = 0.0
                    entry_fee = 0.0
                    cost_basis = 0.0

                pending_signal = None

            # -------------------------------------------------------------
            # 2. Evaluate strategy signal on completed bar i
            # -------------------------------------------------------------
            generated_signal: Optional[str] = None
            if i >= warmup_idx:
                prev_bar = df.iloc[i - 1]

                prev_fast = float(prev_bar["fast_ema"])
                prev_slow = float(prev_bar["slow_ema"])
                curr_fast = float(curr_bar["fast_ema"])
                curr_slow = float(curr_bar["slow_ema"])

                bullish_crossover = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
                bearish_crossover = (prev_fast >= prev_slow) and (curr_fast < curr_slow)

                curr_rsi = float(curr_bar["rsi"]) if not np.isnan(curr_bar["rsi"]) else None
                curr_vol = float(curr_bar["volume"]) if not np.isnan(curr_bar["volume"]) else None
                curr_vol_ma = float(curr_bar["volume_ma"]) if not np.isnan(curr_bar["volume_ma"]) else None

                if bullish_crossover:
                    rsi_ok = True
                    if rsi_filter and curr_rsi is not None:
                        if curr_rsi > rsi_overbought or curr_rsi < rsi_buy_min:
                            rsi_ok = False

                    vol_ok = True
                    if vol_filter and curr_vol is not None and curr_vol_ma is not None:
                        if curr_vol <= curr_vol_ma:
                            vol_ok = False

                    if rsi_ok and vol_ok:
                        generated_signal = "BUY"

                elif bearish_crossover:
                    rsi_ok = True
                    if rsi_filter and curr_rsi is not None:
                        if curr_rsi < rsi_oversold or curr_rsi > rsi_sell_max:
                            rsi_ok = False

                    vol_ok = True
                    if vol_filter and curr_vol is not None and curr_vol_ma is not None:
                        if curr_vol <= curr_vol_ma:
                            vol_ok = False

                    if rsi_ok and vol_ok:
                        generated_signal = "SELL"

            # -------------------------------------------------------------
            # 3. Handle generated signal according to execution mode
            # -------------------------------------------------------------
            if generated_signal == "BUY" and position_qty == 0.0:
                if exec_mode == "next_open":
                    pending_signal = "BUY"
                else:  # current_close
                    fill_price = close_price * (1.0 + slippage_rate)
                    cost_per_unit = fill_price * (1.0 + fee_rate)
                    qty = cash / cost_per_unit
                    trade_cost = qty * fill_price
                    fee = trade_cost * fee_rate

                    cash -= (trade_cost + fee)
                    position_qty = qty
                    entry_price = fill_price
                    entry_time = bar_time
                    entry_fee = fee
                    cost_basis = trade_cost

            elif generated_signal == "SELL" and position_qty > 0.0:
                if exec_mode == "next_open":
                    pending_signal = "SELL"
                else:  # current_close
                    fill_price = close_price * (1.0 - slippage_rate)
                    gross_proceeds = position_qty * fill_price
                    exit_fee = gross_proceeds * fee_rate
                    net_proceeds = gross_proceeds - exit_fee
                    gross_pnl = gross_proceeds - cost_basis
                    net_pnl = gross_pnl - (entry_fee + exit_fee)
                    total_fees = entry_fee + exit_fee
                    return_pct = (net_pnl / (cost_basis + entry_fee)) * 100.0 if (cost_basis + entry_fee) > 0 else 0.0

                    cash += net_proceeds
                    trades.append(
                        Trade(
                            trade_id=trade_id,
                            symbol=self.request.symbol.upper(),
                            side="LONG",
                            entry_time=entry_time,
                            entry_price=round(entry_price, 4),
                            entry_fee=round(entry_fee, 4),
                            exit_time=bar_time,
                            exit_price=round(fill_price, 4),
                            exit_fee=round(exit_fee, 4),
                            total_fees=round(total_fees, 4),
                            quantity=round(position_qty, 6),
                            cost_basis=round(cost_basis, 2),
                            proceeds=round(net_proceeds, 2),
                            gross_pnl=round(gross_pnl, 2),
                            net_pnl=round(net_pnl, 2),
                            return_pct=round(return_pct, 2),
                            exit_reason="SELL_SIGNAL",
                            duration_seconds=bar_time - entry_time,
                        )
                    )
                    trade_id += 1
                    position_qty = 0.0
                    entry_price = 0.0
                    entry_fee = 0.0
                    cost_basis = 0.0

            # -------------------------------------------------------------
            # 4. Record bar-by-bar Equity Point
            # -------------------------------------------------------------
            in_pos = position_qty > 0.0
            if in_pos:
                bars_in_position += 1

            pos_val = position_qty * close_price
            equity = cash + pos_val
            peak_equity = max(peak_equity, equity)
            dd_dollars = max(0.0, peak_equity - equity)
            dd_pct = (dd_dollars / peak_equity * 100.0) if peak_equity > 0.0 else 0.0

            equity_curve.append(
                EquityPoint(
                    time=bar_time,
                    close=round(close_price, 4),
                    cash=round(cash, 2),
                    position_qty=round(position_qty, 6),
                    position_value=round(pos_val, 2),
                    equity=round(equity, 2),
                    drawdown_dollars=round(dd_dollars, 2),
                    drawdown_pct=round(dd_pct, 2),
                    in_position=in_pos,
                )
            )

        # -------------------------------------------------------------
        # 5. End of Data: Liquidate any remaining open position
        # -------------------------------------------------------------
        if position_qty > 0.0 and len(df) > 0:
            final_bar = df.iloc[-1]
            final_time = int(final_bar["time"])
            final_close = float(final_bar["close"])
            fill_price = final_close * (1.0 - slippage_rate)
            gross_proceeds = position_qty * fill_price
            exit_fee = gross_proceeds * fee_rate
            net_proceeds = gross_proceeds - exit_fee
            gross_pnl = gross_proceeds - cost_basis
            net_pnl = gross_pnl - (entry_fee + exit_fee)
            total_fees = entry_fee + exit_fee
            return_pct = (net_pnl / (cost_basis + entry_fee)) * 100.0 if (cost_basis + entry_fee) > 0 else 0.0

            cash += net_proceeds
            trades.append(
                Trade(
                    trade_id=trade_id,
                    symbol=self.request.symbol.upper(),
                    side="LONG",
                    entry_time=entry_time,
                    entry_price=round(entry_price, 4),
                    entry_fee=round(entry_fee, 4),
                    exit_time=final_time,
                    exit_price=round(fill_price, 4),
                    exit_fee=round(exit_fee, 4),
                    total_fees=round(total_fees, 4),
                    quantity=round(position_qty, 6),
                    cost_basis=round(cost_basis, 2),
                    proceeds=round(net_proceeds, 2),
                    gross_pnl=round(gross_pnl, 2),
                    net_pnl=round(net_pnl, 2),
                    return_pct=round(return_pct, 2),
                    exit_reason="END_OF_DATA",
                    duration_seconds=final_time - entry_time,
                )
            )
            position_qty = 0.0
            # Update the very last equity point to reflect liquidated cash
            if equity_curve:
                equity_curve[-1].cash = round(cash, 2)
                equity_curve[-1].position_qty = 0.0
                equity_curve[-1].position_value = 0.0
                equity_curve[-1].equity = round(cash, 2)
                equity_curve[-1].in_position = False

        # -------------------------------------------------------------
        # 6. Compute Comprehensive Summary Metrics
        # -------------------------------------------------------------
        initial_cap = self.request.initial_capital
        final_eq = cash
        net_profit = final_eq - initial_cap
        net_return_pct = (net_profit / initial_cap) * 100.0

        total_trades = len(trades)
        winning_trades = [t for t in trades if t.net_pnl > 0]
        losing_trades = [t for t in trades if t.net_pnl < 0]
        break_even_trades = [t for t in trades if t.net_pnl == 0]

        win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0
        loss_rate = (len(losing_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
        gross_loss = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))

        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0 and gross_loss == 0:
            profit_factor = None  # Infinite profit factor with zero loss
        else:
            profit_factor = None

        max_dd_dollars = max((p.drawdown_dollars for p in equity_curve), default=0.0)
        max_dd_pct = max((p.drawdown_pct for p in equity_curve), default=0.0)

        avg_trade_pnl = (sum(t.net_pnl for t in trades) / total_trades) if total_trades > 0 else 0.0
        avg_win = (sum(t.net_pnl for t in winning_trades) / len(winning_trades)) if winning_trades else 0.0
        avg_loss = (sum(t.net_pnl for t in losing_trades) / len(losing_trades)) if losing_trades else 0.0
        largest_win = max((t.net_pnl for t in winning_trades), default=0.0)
        largest_loss = min((t.net_pnl for t in losing_trades), default=0.0)

        # Consecutive win/loss streaks
        consec_wins = 0
        max_consec_wins = 0
        consec_losses = 0
        max_consec_losses = 0
        for t in trades:
            if t.net_pnl > 0:
                consec_wins += 1
                consec_losses = 0
                max_consec_wins = max(max_consec_wins, consec_wins)
            elif t.net_pnl < 0:
                consec_losses += 1
                consec_wins = 0
                max_consec_losses = max(max_consec_losses, consec_losses)
            else:
                consec_wins = 0
                consec_losses = 0

        total_fees = sum(t.total_fees for t in trades)

        # Buy & Hold benchmark
        first_close = float(df.iloc[0]["close"])
        last_close = float(df.iloc[-1]["close"])
        buy_and_hold_return_pct = ((last_close - first_close) / first_close * 100.0) if first_close > 0 else 0.0

        market_exposure_pct = (bars_in_position / n_bars * 100.0) if n_bars > 0 else 0.0

        metrics = BacktestMetrics(
            initial_capital=round(initial_cap, 2),
            final_equity=round(final_eq, 2),
            net_profit=round(net_profit, 2),
            net_return_pct=round(net_return_pct, 2),
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            break_even_trades=len(break_even_trades),
            win_rate_pct=round(win_rate, 2),
            loss_rate_pct=round(loss_rate, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=profit_factor,
            max_drawdown_dollars=round(max_dd_dollars, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            avg_trade_pnl=round(avg_trade_pnl, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            total_fees_paid=round(total_fees, 2),
            buy_and_hold_return_pct=round(buy_and_hold_return_pct, 2),
            total_bars_analyzed=n_bars,
            market_exposure_pct=round(market_exposure_pct, 2),
        )

        assumptions_note = (
            f"Execution: {exec_mode}. Orders triggered by completed candle i execute at "
            f"{'next candle open' if exec_mode == 'next_open' else 'current candle close'} with "
            f"{slippage_rate * 100:.3f}% slippage and {fee_rate * 100:.3f}% transaction fees. "
            f"Position model: 100% equity long-only."
        )

        backtest_id = f"bt_{uuid.uuid4().hex[:12]}"
        start_ts = int(df.iloc[0]["time"])
        end_ts = int(df.iloc[-1]["time"])

        return BacktestResult(
            backtest_id=backtest_id,
            symbol=self.request.symbol.upper(),
            resolution=self.request.resolution.lower(),
            start_time=start_ts,
            end_time=end_ts,
            execution_mode=exec_mode,
            assumptions_note=assumptions_note,
            strategy_id="ema_crossover",
            strategy_params=self.strategy.parameters,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
        )
