import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getTickers } from '../services/api';
import { marketSocket } from '../services/marketSocket';
import type { WebSocketTickerUpdate } from '../services/marketSocket';
import type { MarketStats, MarketTicker } from '../types/market';

export function useMarketData() {
  const [tickersMap, setTickersMap] = useState<Map<string, MarketTicker>>(new Map());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  // Keep a ref to the latest tickersMap for high-frequency updates without stale closures
  const tickersMapRef = useRef<Map<string, MarketTicker>>(tickersMap);
  tickersMapRef.current = tickersMap;

  // Pending updates buffer to avoid React re-rendering on every single WS packet
  const pendingUpdatesRef = useRef<Map<string, WebSocketTickerUpdate>>(new Map());
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchInitialData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getTickers();
      const map = new Map<string, MarketTicker>();
      for (const t of data) {
        map.set(t.symbol, t);
      }
      tickersMapRef.current = map;
      setTickersMap(map);
      setLastRefreshed(new Date());

      // Auto-subscribe top active perpetuals to WebSocket ticker channel
      const topSymbols = data
        .filter((t) => t.contractType === 'perpetual_futures' || t.symbol === 'BTCUSD' || t.symbol === 'ETHUSD')
        .slice(0, 30)
        .map((t) => t.symbol);

      if (topSymbols.length > 0) {
        marketSocket.subscribeTickers(topSymbols);
      }
    } catch (err) {
      console.error('Failed to fetch tickers:', err);
      setError(err instanceof Error ? err.message : 'Unable to connect to Delta Exchange market API');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Flush buffered WebSocket ticker updates every 250ms
  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current) return;

    flushTimerRef.current = setTimeout(() => {
      flushTimerRef.current = null;
      if (pendingUpdatesRef.current.size === 0) return;

      const currentMap = new Map(tickersMapRef.current);
      let changed = false;

      pendingUpdatesRef.current.forEach((update, symbol) => {
        const existing = currentMap.get(symbol);
        if (existing) {
          const prevPrice = existing.lastPrice;
          const newPrice = update.close;
          const direction = newPrice > prevPrice ? 'up' : newPrice < prevPrice ? 'down' : 'same';

          currentMap.set(symbol, {
            ...existing,
            prevPrice,
            lastPrice: newPrice,
            priceDirection: direction,
            high24h: update.high !== undefined ? update.high : existing.high24h,
            low24h: update.low !== undefined ? update.low : existing.low24h,
            markPrice: update.markPrice !== undefined ? update.markPrice : existing.markPrice,
            spotPrice: update.spotPrice !== undefined ? update.spotPrice : existing.spotPrice,
            change24h: update.change24h !== undefined ? update.change24h : existing.change24h,
            bestBid: update.bestBid !== undefined ? update.bestBid : existing.bestBid,
            bestAsk: update.bestAsk !== undefined ? update.bestAsk : existing.bestAsk,
            timestamp: update.timestamp,
            lastUpdatedStr: new Date(update.timestamp).toLocaleTimeString(),
          });
          changed = true;
        }
      });

      pendingUpdatesRef.current.clear();

      if (changed) {
        tickersMapRef.current = currentMap;
        setTickersMap(currentMap);
      }
    }, 250);
  }, []);

  // Listen for real-time WebSocket ticker updates
  useEffect(() => {
    const unsubTicker = marketSocket.addTickerListener((update) => {
      pendingUpdatesRef.current.set(update.symbol, update);
      scheduleFlush();
    });

    return () => {
      unsubTicker();
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [scheduleFlush]);

  // Initial fetch on mount
  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  // Convert map to array for consumers
  const tickers = useMemo(() => {
    return Array.from(tickersMap.values());
  }, [tickersMap]);

  // Calculate market stats from real data
  const marketStats = useMemo<MarketStats>(() => {
    const btcTicker = tickersMap.get('BTCUSD') || tickers.find((t) => t.symbol.includes('BTCUSD'));
    const ethTicker = tickersMap.get('ETHUSD') || tickers.find((t) => t.symbol.includes('ETHUSD'));

    let totalVolumeUsd = 0;
    let gainers = 0;
    let losers = 0;
    let perpetualsCount = 0;

    tickers.forEach((t) => {
      if (t.contractType === 'perpetual_futures') {
        perpetualsCount++;
      }
      if (t.turnover24hUsd && !isNaN(t.turnover24hUsd)) {
        totalVolumeUsd += t.turnover24hUsd;
      }
      if (t.change24h !== null && !isNaN(t.change24h)) {
        if (t.change24h > 0) gainers++;
        else if (t.change24h < 0) losers++;
      }
    });

    return {
      btcPrice: btcTicker ? btcTicker.lastPrice : null,
      btcChange24h: btcTicker ? btcTicker.change24h : null,
      btcVolume: btcTicker ? btcTicker.volume24h : null,
      ethPrice: ethTicker ? ethTicker.lastPrice : null,
      ethChange24h: ethTicker ? ethTicker.change24h : null,
      ethVolume: ethTicker ? ethTicker.volume24h : null,
      totalTradingPairs: tickers.length,
      activePerpetuals: perpetualsCount,
      totalVolumeUsd24h: totalVolumeUsd > 0 ? totalVolumeUsd : null,
      gainersCount: gainers,
      losersCount: losers,
    };
  }, [tickersMap, tickers]);

  return {
    tickers,
    tickersMap,
    marketStats,
    isLoading,
    error,
    lastRefreshed,
    refresh: fetchInitialData,
  };
}
