import { useEffect, useState } from 'react';
import { marketSocket } from '../services/marketSocket';
import type { CandleData, ConnectionStatusType } from '../types/market';

export function useMarketWebSocket(selectedSymbol?: string, resolution?: string) {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatusType>(marketSocket.getStatus());
  const [latestCandle, setLatestCandle] = useState<CandleData | null>(null);
  const [lastMessageTime, setLastMessageTime] = useState<Date | null>(null);

  useEffect(() => {
    // Listen to connection status changes
    const unsubStatus = marketSocket.addStatusListener((status) => {
      setConnectionStatus(status);
    });

    // Ensure connection is active
    marketSocket.connect();

    return () => {
      unsubStatus();
    };
  }, []);

  // Subscribe to candlestick updates for selectedSymbol + resolution
  useEffect(() => {
    if (!selectedSymbol || !resolution) return;

    marketSocket.subscribeCandles(selectedSymbol, resolution);

    const unsubCandle = marketSocket.addCandleListener((candle, sym, res) => {
      if (sym === selectedSymbol && res === resolution) {
        setLatestCandle(candle);
        setLastMessageTime(new Date());
      }
    });

    return () => {
      unsubCandle();
      marketSocket.unsubscribeCandles(selectedSymbol);
    };
  }, [selectedSymbol, resolution]);

  return {
    connectionStatus,
    latestCandle,
    lastMessageTime,
    reconnect: () => {
      marketSocket.disconnect();
      marketSocket.connect();
    },
  };
}
