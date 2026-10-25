import type { CandleData } from '../types/market';

/**
 * Normalizes an incoming raw WebSocket message from Delta Exchange into a standard CandleData object.
 * Supports both full names (symbol, close, open, high, low, volume, candle_start_time)
 * and abbreviated names (sy, c, o, h, l, v, cst).
 */
export function normalizeWsCandle(
  msg: Record<string, any>
): { candle: CandleData; symbol: string; resolution: string } | null {
  if (!msg || typeof msg !== 'object') return null;

  const msgType = String(msg.type || '');
  if (!msgType.startsWith('candlestick_')) return null;

  const symbol = String(msg.symbol || msg.sy || '').trim();
  if (!symbol) return null;

  const resolution = String(msg.resolution || msg.res || msgType.replace('candlestick_', '')).trim();

  // Price & Volume fields
  const rawOpen = msg.open !== undefined ? msg.open : msg.o;
  const rawHigh = msg.high !== undefined ? msg.high : msg.h;
  const rawLow = msg.low !== undefined ? msg.low : msg.l;
  const rawClose = msg.close !== undefined ? msg.close : msg.c;
  const rawVolume = msg.volume !== undefined ? msg.volume : msg.v;

  const open = Number(rawOpen);
  const high = Number(rawHigh);
  const low = Number(rawLow);
  const close = Number(rawClose);
  const volume = Number(rawVolume || 0);

  if (isNaN(open) || isNaN(high) || isNaN(low) || isNaN(close)) {
    return null;
  }

  // Timestamp normalization (handle microseconds 1e14+, milliseconds 1e11+, or seconds)
  const rawTime =
    msg.candle_start_time !== undefined
      ? msg.candle_start_time
      : msg.cst !== undefined
      ? msg.cst
      : msg.timestamp !== undefined
      ? msg.timestamp
      : msg.ts;

  let timeSec: number;
  if (rawTime !== undefined && rawTime !== null) {
    const num = Number(rawTime);
    if (isNaN(num) || num <= 0) {
      timeSec = Math.floor(Date.now() / 1000);
    } else if (num > 1e14) {
      // Microseconds from Delta Exchange (e.g. 1792504740000000)
      timeSec = Math.floor(num / 1000000);
    } else if (num > 1e11) {
      // Milliseconds
      timeSec = Math.floor(num / 1000);
    } else {
      // Seconds
      timeSec = Math.floor(num);
    }
  } else {
    timeSec = Math.floor(Date.now() / 1000);
  }

  return {
    symbol,
    resolution,
    candle: {
      time: timeSec,
      open,
      high,
      low,
      close,
      volume: isNaN(volume) ? 0 : volume,
    },
  };
}

export type CandleUpdateAction = 'appended' | 'updated' | 'ignored';

export interface CandleUpdateResult {
  updatedCandles: CandleData[];
  action: CandleUpdateAction;
  latestBar: CandleData;
}

/**
 * Incrementally applies a live incoming candle to an existing chronological candle list.
 * 
 * Rules:
 * 1. If timestamp matches the latest candle -> updates current bar in place.
 * 2. If timestamp is strictly greater than the latest candle -> starts a new bar (appends).
 * 3. If timestamp is older than the latest candle:
 *    - If it matches an earlier existing candle in the array -> updates that historical bar.
 *    - Otherwise ignored to preserve chronological ordering and prevent back-tracking.
 * 4. Never fabricates prices or volume.
 */
export function applyCandleUpdate(
  currentCandles: CandleData[],
  incoming: CandleData
): CandleUpdateResult {
  if (!currentCandles || currentCandles.length === 0) {
    return {
      updatedCandles: [incoming],
      action: 'appended',
      latestBar: incoming,
    };
  }

  const lastIndex = currentCandles.length - 1;
  const lastBar = currentCandles[lastIndex];

  // Case 1: Same candle interval (in-place update of current active candle)
  if (incoming.time === lastBar.time) {
    const updatedBar: CandleData = {
      time: lastBar.time,
      open: lastBar.open, // Keep original interval open price
      high: Math.max(lastBar.high, incoming.high),
      low: Math.min(lastBar.low, incoming.low),
      close: incoming.close,
      volume: incoming.volume > 0 ? incoming.volume : lastBar.volume,
    };

    const nextCandles = [...currentCandles];
    nextCandles[lastIndex] = updatedBar;

    return {
      updatedCandles: nextCandles,
      action: 'updated',
      latestBar: updatedBar,
    };
  }

  // Case 2: New interval began (timestamp is forward in time)
  if (incoming.time > lastBar.time) {
    const nextCandles = [...currentCandles, incoming];
    return {
      updatedCandles: nextCandles,
      action: 'appended',
      latestBar: incoming,
    };
  }

  // Case 3: Out-of-order / past timestamp
  // Check if it matches an existing historical candle
  const existingIdx = currentCandles.findIndex((c) => c.time === incoming.time);
  if (existingIdx !== -1) {
    const existingBar = currentCandles[existingIdx];
    const updatedHistorical: CandleData = {
      time: existingBar.time,
      open: existingBar.open,
      high: Math.max(existingBar.high, incoming.high),
      low: Math.min(existingBar.low, incoming.low),
      close: incoming.close,
      volume: incoming.volume > 0 ? incoming.volume : existingBar.volume,
    };
    const nextCandles = [...currentCandles];
    nextCandles[existingIdx] = updatedHistorical;
    return {
      updatedCandles: nextCandles,
      action: 'updated',
      latestBar: nextCandles[lastIndex],
    };
  }

  // Out of order and doesn't match an existing bar: ignore to maintain integrity
  return {
    updatedCandles: currentCandles,
    action: 'ignored',
    latestBar: lastBar,
  };
}

/**
 * Merges newly fetched historical or recovery candles into existing candles without duplicates,
 * maintaining strictly ascending chronological order.
 */
export function mergeHistoricalCandles(
  existingCandles: CandleData[],
  freshCandles: CandleData[]
): CandleData[] {
  if (!freshCandles || freshCandles.length === 0) return existingCandles;
  if (!existingCandles || existingCandles.length === 0) return [...freshCandles].sort((a, b) => a.time - b.time);

  const candleMap = new Map<number, CandleData>();

  for (const c of existingCandles) {
    candleMap.set(c.time, c);
  }

  for (const c of freshCandles) {
    candleMap.set(c.time, c);
  }

  return Array.from(candleMap.values()).sort((a, b) => a.time - b.time);
}
