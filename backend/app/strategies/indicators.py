import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).
    Formula: EMA_t = alpha * Price_t + (1 - alpha) * EMA_{t-1}
    where alpha = 2 / (period + 1)
    """
    if len(series) == 0:
        return pd.Series(dtype=float)
    if period <= 0:
        raise ValueError(f"EMA period must be a positive integer, got {period}")

    # Clean and ensure numeric float type
    s = pd.to_numeric(series, errors="coerce")
    return s.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI) using Wilder's exponential smoothing.
    Handles flat prices (RSI=50), zero loss (RSI=100), and zero gain (RSI=0) safely.
    """
    if len(series) == 0:
        return pd.Series(dtype=float)
    if period <= 0:
        raise ValueError(f"RSI period must be a positive integer, got {period}")

    s = pd.to_numeric(series, errors="coerce")
    delta = s.diff()

    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Wilder's smoothing corresponds to ewm with alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    # Safe division avoiding 0/0 and divide-by-zero warnings
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = np.where(
            avg_loss == 0.0,
            np.where(avg_gain == 0.0, 50.0, 100.0),
            100.0 - (100.0 / (1.0 + rs)),
        )

    # First value has no diff; initialize neutral 50.0
    res = pd.Series(rsi, index=s.index, dtype=float)
    if len(res) > 0 and pd.isna(res.iloc[0]):
        res.iloc[0] = 50.0
    return res


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average (SMA) over a rolling window."""
    if len(series) == 0:
        return pd.Series(dtype=float)
    if period <= 0:
        raise ValueError(f"SMA period must be a positive integer, got {period}")

    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window=period, min_periods=period).mean()
