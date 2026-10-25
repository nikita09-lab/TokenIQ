import pytest
import pandas as pd
import numpy as np

from app.strategies.base import PositionIntent, SignalType
from app.strategies.ema_crossover import (
    EMACrossoverStrategy,
    InsufficientDataError,
    InvalidCandleDataError,
)
from app.strategies.indicators import calculate_ema, calculate_rsi, calculate_sma


# ============================================================================
# 1. Indicator Calculation Tests
# ============================================================================

def test_indicators_ema_calculation():
    series = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0])
    ema_3 = calculate_ema(series, period=3)
    assert len(ema_3) == len(series)
    assert not ema_3.isna().any()
    # In an uptrend, EMA lags price: ema_3[-1] < series[-1]
    assert ema_3.iloc[-1] < series.iloc[-1]
    assert ema_3.iloc[-1] > series.iloc[0]


def test_indicators_ema_invalid_period():
    series = pd.Series([10.0, 11.0, 12.0])
    with pytest.raises(ValueError, match="positive integer"):
        calculate_ema(series, period=0)


def test_indicators_rsi_boundary_conditions():
    # 1. Flat series -> RSI = 50.0
    flat = pd.Series([100.0] * 30)
    rsi_flat = calculate_rsi(flat, period=14)
    assert rsi_flat.iloc[-1] == 50.0

    # 2. Monotonically increasing -> RSI = 100.0
    uptrend = pd.Series([float(i) for i in range(1, 40)])
    rsi_up = calculate_rsi(uptrend, period=14)
    assert rsi_up.iloc[-1] == 100.0

    # 3. Monotonically decreasing -> RSI = 0.0
    downtrend = pd.Series([float(i) for i in range(40, 0, -1)])
    rsi_down = calculate_rsi(downtrend, period=14)
    assert rsi_down.iloc[-1] == 0.0

    # 4. Oscillating series -> strictly in [0, 100]
    oscillating = pd.Series([10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 13.0, 15.0] * 5)
    rsi_osc = calculate_rsi(oscillating, period=14)
    assert (rsi_osc >= 0.0).all() and (rsi_osc <= 100.0).all()


def test_indicators_sma():
    series = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])
    sma_3 = calculate_sma(series, period=3)
    # first 2 should be NaN
    assert pd.isna(sma_3.iloc[0])
    assert pd.isna(sma_3.iloc[1])
    assert sma_3.iloc[2] == 4.0
    assert sma_3.iloc[4] == 8.0


# ============================================================================
# 2. Helper to Build Synthetic Candle Datasets
# ============================================================================

def make_synthetic_candles(prices, volumes=None, base_timestamp=1700000000, step=3600):
    candles = []
    for i, p in enumerate(prices):
        v = volumes[i] if volumes else 1000.0
        t = base_timestamp + (i * step)
        candles.append({
            "time": t,
            "open": p * 0.99,
            "high": p * 1.01,
            "low": p * 0.98,
            "close": float(p),
            "volume": float(v),
        })
    return candles


# ============================================================================
# 3. Signal Generation Tests: BUY, SELL, HOLD & Intent
# ============================================================================

def test_ema_crossover_buy_signal():
    """Golden cross: Fast EMA crosses above Slow EMA with healthy RSI."""
    # Start with downtrend (fast < slow), then cross on final candle
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "rsi_filter_enabled": True,
        "rsi_buy_min": 30.0,
        "rsi_overbought": 85.0,
    })

    signal = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.BUY
    assert signal.position_intent == PositionIntent.OPEN_LONG
    assert signal.fast_ema > signal.slow_ema
    assert "Golden Cross" in signal.explanation
    assert signal.symbol == "BTCUSD"
    assert signal.close == float(prices[-1])


def test_ema_crossover_sell_signal_intent_close_long():
    """Death cross with default sell_intent = 'CLOSE_LONG'."""
    # Start with uptrend (fast > slow), then cross down on final candle
    prices = [50.0 + i * 0.5 for i in range(30)] + [64.0, 61.0]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "rsi_filter_enabled": False,
        "sell_intent": "CLOSE_LONG",
    })

    signal = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.SELL
    assert signal.position_intent == PositionIntent.CLOSE_LONG
    assert signal.fast_ema < signal.slow_ema
    assert "Bearish Death Cross" in signal.explanation
    assert "Closing existing Long position" in signal.explanation


def test_ema_crossover_sell_signal_intent_open_short():
    """Death cross with configured sell_intent = 'OPEN_SHORT'."""
    prices = [50.0 + i * 0.5 for i in range(30)] + [64.0, 61.0]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "rsi_filter_enabled": False,
        "sell_intent": "OPEN_SHORT",
    })

    signal = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.SELL
    assert signal.position_intent == PositionIntent.OPEN_SHORT
    assert "Opening new Short position" in signal.explanation


def test_ema_crossover_hold_no_crossover():
    """When trend continues without crossover, signal is HOLD."""
    prices = [100.0 + i for i in range(40)]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={"fast_period": 5, "slow_period": 10})
    signal = strat.evaluate(candles, symbol="ETHUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.HOLD
    assert signal.position_intent == PositionIntent.NO_ACTION
    assert "No new crossover" in signal.explanation


def test_rsi_filter_rejects_overbought_buy():
    """Golden cross filtered out because RSI is overbought (> 70)."""
    # Cross occurs on final candle with sharp spike (RSI > 80)
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 95.0]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "rsi_filter_enabled": True,
        "rsi_overbought": 70.0,
    })

    signal = strat.evaluate(candles, symbol="SOLUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.HOLD
    assert signal.position_intent == PositionIntent.NO_ACTION
    assert "overbought" in signal.explanation


def test_volume_confirmation_filter():
    """When volume confirmation is enabled, low volume rejects crossover."""
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0]
    # Set volume SMA high (1000) but last bar volume very low (10)
    volumes = [1000.0] * 31 + [10.0]
    candles = make_synthetic_candles(prices, volumes=volumes)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "volume_confirmation_enabled": True,
        "volume_ma_period": 5,
    })

    signal = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)

    assert signal.signal == SignalType.HOLD
    assert "Volume" in signal.explanation and "below" in signal.explanation


# ============================================================================
# 4. Error Handling & Edge Cases
# ============================================================================

def test_insufficient_historical_data_raises_error():
    """Fewer candles than required raises InsufficientDataError."""
    short_candles = make_synthetic_candles([100.0, 101.0, 102.0, 103.0])
    strat = EMACrossoverStrategy(custom_params={"fast_period": 9, "slow_period": 21})

    with pytest.raises(InsufficientDataError, match="Insufficient completed candles"):
        strat.evaluate(short_candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)


def test_empty_candles_raises_error():
    strat = EMACrossoverStrategy()
    with pytest.raises(InsufficientDataError, match="No candle data provided"):
        strat.evaluate([], symbol="BTCUSD", resolution="1h")


def test_missing_or_invalid_candle_values():
    """Candles with NaN, missing close, or negative price are handled or rejected."""
    # Missing required 'close' field
    malformed = [{"time": 1700000000 + i * 3600, "open": 100.0} for i in range(30)]
    strat = EMACrossoverStrategy()
    with pytest.raises(InvalidCandleDataError, match="missing required field 'close'"):
        strat.evaluate(malformed, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)


def test_repeated_signal_idempotency():
    """Evaluating the exact same completed candle twice flags is_repeated=True and returns HOLD."""
    prices = [100.0 - i * 0.5 for i in range(30)] + [86.0, 89.0]
    candles = make_synthetic_candles(prices)

    strat = EMACrossoverStrategy(custom_params={
        "fast_period": 3,
        "slow_period": 7,
        "rsi_period": 5,
        "rsi_filter_enabled": False,
    })

    # First evaluation -> BUY
    sig1 = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)
    assert sig1.signal == SignalType.BUY
    assert sig1.is_repeated is False

    # Second evaluation with the exact same candles -> HOLD (repeated)
    sig2 = strat.evaluate(candles, symbol="BTCUSD", resolution="1h", allow_incomplete_candle=True)
    assert sig2.signal == SignalType.HOLD
    assert sig2.is_repeated is True
    assert "Repeated" in sig2.explanation


def test_parameter_validation_constraints():
    strat = EMACrossoverStrategy()

    # fast_period >= slow_period must fail
    with pytest.raises(ValueError, match="fast_period .* must be strictly less than slow_period"):
        strat.configure({"fast_period": 25, "slow_period": 20})

    # negative rsi bounds must fail
    with pytest.raises(ValueError, match="rsi_buy_min"):
        strat.configure({"rsi_buy_min": -5.0})

    # invalid sell intent must fail
    with pytest.raises(ValueError, match="sell_intent must be one of"):
        strat.configure({"sell_intent": "INVALID_INTENT"})
