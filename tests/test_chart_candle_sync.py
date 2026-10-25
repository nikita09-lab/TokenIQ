"""
Tests for Chart WebSocket Live Updates, Candle Synchronization, and REST Backfill.
Validates:
1. Normalization of Delta Exchange WebSocket candle schema (full & abbreviated keys).
2. Repeated in-place updates to the same active candle (no duplicate creation).
3. New candle creation upon interval advancement.
4. Out-of-order data and timestamp integrity protection.
5. Reconnection & REST backfill merging without duplicates.
6. Microsecond / millisecond timestamp normalization.
"""

from typing import Any, Dict, List, Literal, Tuple
import pytest


def normalize_ws_candle(msg: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    """
    Python mirror of frontend/src/utils/candleSync.ts normalizeWsCandle().
    """
    msg_type = str(msg.get("type") or "")
    if not msg_type.startswith("candlestick_"):
        raise ValueError("Invalid candlestick message type")

    symbol = str(msg.get("symbol") or msg.get("sy") or "").strip()
    if not symbol:
        raise ValueError("Missing symbol")

    resolution = str(msg.get("resolution") or msg.get("res") or msg_type.replace("candlestick_", "")).strip()

    raw_open = msg.get("open") if msg.get("open") is not None else msg.get("o")
    raw_high = msg.get("high") if msg.get("high") is not None else msg.get("h")
    raw_low = msg.get("low") if msg.get("low") is not None else msg.get("l")
    raw_close = msg.get("close") if msg.get("close") is not None else msg.get("c")
    raw_vol = msg.get("volume") if msg.get("volume") is not None else msg.get("v", 0.0)

    raw_time = (
        msg.get("candle_start_time")
        if msg.get("candle_start_time") is not None
        else msg.get("cst", msg.get("timestamp", msg.get("ts")))
    )

    num_time = float(raw_time)
    if num_time > 1e14:
        time_sec = int(num_time / 1_000_000)
    elif num_time > 1e11:
        time_sec = int(num_time / 1_000)
    else:
        time_sec = int(num_time)

    candle = {
        "time": time_sec,
        "open": float(raw_open),
        "high": float(raw_high),
        "low": float(raw_low),
        "close": float(raw_close),
        "volume": float(raw_vol or 0.0),
    }
    return candle, symbol, resolution


def apply_candle_update(
    current_candles: List[Dict[str, Any]], incoming: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Python mirror of frontend/src/utils/candleSync.ts applyCandleUpdate().
    """
    if not current_candles:
        return [incoming], "appended", incoming

    last_bar = current_candles[-1]

    # Case 1: Same candle interval (in-place update of active candle)
    if incoming["time"] == last_bar["time"]:
        updated_bar = {
            "time": last_bar["time"],
            "open": last_bar["open"],  # Preserve original interval open
            "high": max(last_bar["high"], incoming["high"]),
            "low": min(last_bar["low"], incoming["low"]),
            "close": incoming["close"],
            "volume": incoming["volume"] if incoming["volume"] > 0 else last_bar["volume"],
        }
        res = list(current_candles[:-1]) + [updated_bar]
        return res, "updated", updated_bar

    # Case 2: New interval began (timestamp is forward in time)
    if incoming["time"] > last_bar["time"]:
        res = list(current_candles) + [incoming]
        return res, "appended", incoming

    # Case 3: Out of order / historical timestamp
    for idx, bar in enumerate(current_candles):
        if bar["time"] == incoming["time"]:
            updated_bar = {
                "time": bar["time"],
                "open": bar["open"],
                "high": max(bar["high"], incoming["high"]),
                "low": min(bar["low"], incoming["low"]),
                "close": incoming["close"],
                "volume": incoming["volume"] if incoming["volume"] > 0 else bar["volume"],
            }
            res = list(current_candles)
            res[idx] = updated_bar
            return res, "updated", current_candles[-1]

    # Stale/out-of-order bar that doesn't match: ignore
    return current_candles, "ignored", last_bar


def merge_historical_candles(
    existing: List[Dict[str, Any]], fresh: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Python mirror of frontend/src/utils/candleSync.ts mergeHistoricalCandles().
    """
    candle_map = {c["time"]: c for c in existing}
    for c in fresh:
        candle_map[c["time"]] = c
    return sorted(candle_map.values(), key=lambda x: x["time"])


# ============================================================================
# Unit Tests
# ============================================================================

def test_ws_candle_normalization_full_delta_schema():
    """Verify Delta Exchange's full-name candlestick format is normalized correctly."""
    raw = {
        "type": "candlestick_1m",
        "symbol": "BTCUSD",
        "resolution": "1m",
        "open": 82000.0,
        "high": 82500.0,
        "low": 81950.0,
        "close": 82300.0,
        "volume": 125.5,
        "candle_start_time": 1792504740000000,  # 16-digit microseconds
    }
    candle, symbol, res = normalize_ws_candle(raw)
    assert symbol == "BTCUSD"
    assert res == "1m"
    assert candle["time"] == 1792504740  # Correctly converted to Unix seconds
    assert candle["open"] == 82000.0
    assert candle["high"] == 82500.0
    assert candle["low"] == 81950.0
    assert candle["close"] == 82300.0
    assert candle["volume"] == 125.5


def test_ws_candle_normalization_abbreviated_delta_schema():
    """Verify Delta Exchange's abbreviated candlestick format is normalized correctly."""
    raw = {
        "type": "candlestick_5m",
        "sy": "ETHUSD",
        "res": "5m",
        "o": 3100.0,
        "h": 3120.0,
        "l": 3090.0,
        "c": 3115.0,
        "v": 540.2,
        "cst": 1700000000000000,
    }
    candle, symbol, res = normalize_ws_candle(raw)
    assert symbol == "ETHUSD"
    assert res == "5m"
    assert candle["time"] == 1700000000
    assert candle["close"] == 3115.0


def test_repeated_updates_to_same_candle():
    """
    Verify that repeated price ticks within the same interval update the candle
    in place without creating duplicate bars or changing the candle count.
    """
    candles = [
        {"time": 1700000000, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10.0}
    ]

    tick2 = {"time": 1700000000, "open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0, "volume": 25.0}
    updated_candles, action, latest = apply_candle_update(candles, tick2)

    assert action == "updated"
    assert len(updated_candles) == 1
    assert latest["open"] == 100.0  # Open remains unchanged
    assert latest["high"] == 105.0  # High expanded to 105
    assert latest["low"] == 98.0   # Low expanded to 98
    assert latest["close"] == 104.0
    assert latest["volume"] == 25.0

    # Third tick pulling back
    tick3 = {"time": 1700000000, "open": 100.0, "high": 103.0, "low": 99.0, "close": 103.0, "volume": 30.0}
    updated_candles3, action3, latest3 = apply_candle_update(updated_candles, tick3)

    assert action3 == "updated"
    assert len(updated_candles3) == 1
    assert latest3["high"] == 105.0  # High preserved at highest recorded (105)
    assert latest3["low"] == 98.0    # Low preserved at lowest recorded (98)
    assert latest3["close"] == 103.0 # Close updated to latest price


def test_new_candle_creation_upon_interval_advance():
    """
    Verify that when a candle with a forward timestamp arrives, a new bar is appended.
    """
    candles = [
        {"time": 1700000000, "open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0, "volume": 25.0}
    ]

    new_bar = {"time": 1700000060, "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 12.0}
    updated_candles, action, latest = apply_candle_update(candles, new_bar)

    assert action == "appended"
    assert len(updated_candles) == 2
    assert updated_candles[0]["time"] == 1700000000
    assert updated_candles[1]["time"] == 1700000060
    assert latest["time"] == 1700000060


def test_out_of_order_data_does_not_break_chronological_ordering():
    """
    Verify that an out-of-order candle (time < latest bar) does not append to the end.
    """
    candles = [
        {"time": 1700000000, "open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0, "volume": 25.0},
        {"time": 1700000060, "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.5, "volume": 12.0},
    ]

    # Stale tick arriving from past (timestamp 1699999900)
    stale_tick = {"time": 1699999900, "open": 95.0, "high": 96.0, "low": 94.0, "close": 95.5, "volume": 5.0}
    updated_candles, action, latest = apply_candle_update(candles, stale_tick)

    assert action == "ignored"
    assert len(updated_candles) == 2
    assert updated_candles[-1]["time"] == 1700000060


def test_reconnection_and_rest_backfill_merging():
    """
    Verify that when WebSocket reconnects, historical backfill bars are merged
    without duplicate timestamps and with strictly ascending order.
    """
    existing_candles = [
        {"time": 1700000000, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10.0},
        {"time": 1700000060, "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.5, "volume": 15.0},
    ]

    # REST backfill returned overlapping last bar + 2 newly completed bars
    rest_backfill = [
        {"time": 1700000060, "open": 101.0, "high": 103.5, "low": 100.0, "close": 103.0, "volume": 18.0}, # Overlapping
        {"time": 1700000120, "open": 103.0, "high": 105.0, "low": 102.0, "close": 104.0, "volume": 22.0}, # New
        {"time": 1700000180, "open": 104.0, "high": 106.0, "low": 103.5, "close": 105.0, "volume": 19.0}, # New
    ]

    merged = merge_historical_candles(existing_candles, rest_backfill)

    # Must have exactly 4 bars, no duplicates
    assert len(merged) == 4
    timestamps = [c["time"] for c in merged]
    assert timestamps == [1700000000, 1700000060, 1700000120, 1700000180]
    # Check that overlapping bar 1700000060 was updated with finalized REST close
    assert merged[1]["close"] == 103.0
    assert merged[1]["volume"] == 18.0
