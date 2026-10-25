import pytest
import pandas as pd
import numpy as np

from app.backtesting.engine import BacktestEngine, BacktestValidationError
from app.backtesting.models import BacktestRequest


def make_candles(prices, opens=None, volumes=None, base_time=1700000000, step=3600):
    candles = []
    for i, p in enumerate(prices):
        t = base_time + (i * step)
        op = opens[i] if opens is not None else p
        v = volumes[i] if volumes is not None else 1000.0
        candles.append({
            "time": t,
            "open": float(op),
            "high": float(max(op, p) * 1.01),
            "low": float(min(op, p) * 0.99),
            "close": float(p),
            "volume": float(v),
        })
    return candles


def test_backtest_validation_errors():
    from pydantic import ValidationError

    # 1. Non-positive capital raises Pydantic validation error
    with pytest.raises(ValidationError):
        BacktestRequest(symbol="BTCUSD", initial_capital=0)

    # 2. Negative fee raises Pydantic validation error
    with pytest.raises(ValidationError):
        BacktestRequest(symbol="BTCUSD", fee_rate=-0.01)

    # 3. Invalid date order (start >= end) raises BacktestValidationError in Engine
    with pytest.raises(BacktestValidationError, match="must be strictly earlier"):
        BacktestEngine(BacktestRequest(symbol="BTCUSD", start_time=1700010000, end_time=1700000000))


def test_backtest_insufficient_data():
    req = BacktestRequest(
        symbol="BTCUSD",
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5},
    )
    engine = BacktestEngine(req)
    short_candles = make_candles([100.0, 101.0, 102.0])
    with pytest.raises(BacktestValidationError, match="Insufficient historical data"):
        engine.run(short_candles)


def test_lookahead_prevention_next_open_execution():
    """
    Verify that when execution_mode is 'next_open', a signal on candle i
    fills strictly on candle i+1's open, preventing look-ahead bias.
    """
    # 30 downtrend candles, then Golden cross on bar 31
    # Bar 31: close=89.0 (crossover occurred)
    # Bar 32: open=92.0, close=95.0
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0, 95.0, 100.0]
    opens = [100.0 - i * 0.5 for i in range(30)] + [86.0, 88.0, 92.0, 97.0]
    base_t = 1700000000
    candles = make_candles(prices, opens=opens, base_time=base_t, step=3600)

    # 1. Run with next_open
    req_next_open = BacktestRequest(
        symbol="BTCUSD",
        execution_mode="next_open",
        fee_rate=0.0,
        slippage_rate=0.0,
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5, "rsi_filter_enabled": False},
    )
    result_next = BacktestEngine(req_next_open).run(candles)
    assert len(result_next.trades) >= 1
    first_trade = result_next.trades[0]

    # Signal triggered at index 31 (timestamp = base_t + 31 * 3600)
    # But fill must occur on bar 32 (timestamp = base_t + 32 * 3600) at its OPEN (92.0)
    expected_fill_time = base_t + 32 * 3600
    expected_fill_price = 92.0
    assert first_trade.entry_time == expected_fill_time
    assert first_trade.entry_price == expected_fill_price

    # 2. Run with current_close
    req_curr_close = BacktestRequest(
        symbol="BTCUSD",
        execution_mode="current_close",
        fee_rate=0.0,
        slippage_rate=0.0,
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5, "rsi_filter_enabled": False},
    )
    result_curr = BacktestEngine(req_curr_close).run(candles)
    assert len(result_curr.trades) >= 1
    # Under current_close, fill occurs at bar 31's CLOSE (89.0)
    assert result_curr.trades[0].entry_time == base_t + 31 * 3600
    assert result_curr.trades[0].entry_price == 89.0


def test_backtest_fees_and_slippage():
    """Verify that fees and slippage are correctly deducted on entry and exit."""
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0, 95.0, 92.0, 85.0]
    opens = [100.0 - i * 0.5 for i in range(30)] + [86.0, 88.0, 90.0, 93.0, 88.0]
    candles = make_candles(prices, opens=opens)

    fee = 0.001  # 0.1%
    slip = 0.001  # 0.1%
    req = BacktestRequest(
        symbol="BTCUSD",
        initial_capital=10000.0,
        fee_rate=fee,
        slippage_rate=slip,
        execution_mode="next_open",
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5, "rsi_filter_enabled": False},
    )
    res = BacktestEngine(req).run(candles)
    assert len(res.trades) >= 1
    trade = res.trades[0]

    # Entry price with slippage: open * (1 + slippage)
    expected_entry_base = opens[32]  # bar 32 open
    assert trade.entry_price == pytest.approx(expected_entry_base * (1.0 + slip), rel=1e-4)

    # Fees must be non-zero and tracked
    assert trade.entry_fee > 0.0
    assert trade.exit_fee > 0.0
    assert trade.total_fees == pytest.approx(trade.entry_fee + trade.exit_fee, rel=1e-4)
    assert res.metrics.total_fees_paid > 0.0


def test_backtest_no_trades_handling():
    """Flat prices produce 0 trades without division by zero or crashing."""
    flat_prices = [100.0] * 40
    candles = make_candles(flat_prices)

    req = BacktestRequest(symbol="BTCUSD", initial_capital=10000.0)
    res = BacktestEngine(req).run(candles)

    assert res.metrics.total_trades == 0
    assert res.metrics.winning_trades == 0
    assert res.metrics.losing_trades == 0
    assert res.metrics.win_rate_pct == 0.0
    assert res.metrics.profit_factor is None
    assert res.metrics.net_profit == 0.0
    assert res.metrics.final_equity == 10000.0
    assert len(res.trades) == 0
    assert len(res.equity_curve) == len(candles)


def test_backtest_max_drawdown_calculation():
    """Verify maximum drawdown dollar and percentage calculations."""
    # Start high (10000 capital in position), drop 20%, then recover
    # 30 bars warmup, buy at bar 31 open (100), drop to 80 (20% drawdown), recover to 110
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0, 80.0, 75.0, 95.0, 110.0]
    opens = [100.0 - i * 0.5 for i in range(30)] + [86.0, 88.0, 90.0, 80.0, 75.0, 95.0]
    candles = make_candles(prices, opens=opens)

    req = BacktestRequest(
        symbol="BTCUSD",
        initial_capital=10000.0,
        fee_rate=0.0,
        slippage_rate=0.0,
        execution_mode="next_open",
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5, "rsi_filter_enabled": False},
    )
    res = BacktestEngine(req).run(candles)

    # Maximum drawdown must be greater than 10%
    assert res.metrics.max_drawdown_pct > 10.0
    assert res.metrics.max_drawdown_dollars > 1000.0
    for pt in res.equity_curve:
        assert pt.drawdown_pct >= 0.0


def test_backtest_duplicate_and_missing_timestamps():
    """Engine cleans duplicate timestamps and non-numeric bars cleanly."""
    base_t = 1700000000
    dirty_candles = [
        {"time": base_t + i * 3600, "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 100}
        for i in range(35)
    ]
    # Add duplicate timestamp
    dirty_candles.append({"time": base_t + 10 * 3600, "open": 99.0, "high": 101.0, "low": 98.0, "close": 99.0, "volume": 50})
    # Add candle with negative close
    dirty_candles.append({"time": base_t + 36 * 3600, "open": 100.0, "high": 105.0, "low": 95.0, "close": -1.0, "volume": 100})

    req = BacktestRequest(
        symbol="BTCUSD",
        strategy_params={"fast_period": 3, "slow_period": 7, "rsi_period": 5},
    )
    res = BacktestEngine(req).run(dirty_candles)
    # Total bars analyzed should be 35 (duplicates & negative filtered)
    assert res.metrics.total_bars_analyzed == 35
