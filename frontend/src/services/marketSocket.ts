import type { CandleData, ConnectionStatusType } from '../types/market';
import { normalizeWsCandle } from '../utils/candleSync';

export interface WebSocketTickerUpdate {
  symbol: string;
  close: number;
  open?: number;
  high?: number;
  low?: number;
  markPrice?: number;
  spotPrice?: number;
  change24h?: number;
  bestBid?: number;
  bestAsk?: number;
  timestamp: number;
}

export type TickerListener = (update: WebSocketTickerUpdate) => void;
export type CandleListener = (candle: CandleData, symbol: string, resolution: string) => void;
export type StatusListener = (status: ConnectionStatusType) => void;
export type ReconnectListener = () => void;

class MarketSocketService {
  private ws: WebSocket | null = null;
  private status: ConnectionStatusType = 'disconnected';
  private reconnectAttempts = 0;
  private maxReconnectDelay = 15000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingInterval: ReturnType<typeof setInterval> | null = null;

  // Subscriptions registry
  private subscribedTickerSymbols = new Set<string>();
  private activeCandleSubscriptions = new Map<string, string>(); // symbol -> resolution

  // Listeners
  private tickerListeners = new Set<TickerListener>();
  private candleListeners = new Set<CandleListener>();
  private statusListeners = new Set<StatusListener>();
  private reconnectListeners = new Set<ReconnectListener>();

  private getSocketUrl(): string {
    const envObj = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;

    // 1. Explicit WebSocket URL override if configured
    const explicitWs = (envObj?.VITE_WS_URL || (import.meta as any).env?.VITE_WS_URL)?.trim();
    if (explicitWs) {
      return explicitWs.replace(/\/+$/, '');
    }

    // 2. Derive WebSocket URL from VITE_API_BASE_URL if configured
    const apiBase = (envObj?.VITE_API_BASE_URL || (import.meta as any).env?.VITE_API_BASE_URL)?.trim().replace(/\/+$/, '');
    if (apiBase) {
      try {
        const backendUrl = new URL(apiBase);
        backendUrl.protocol = backendUrl.protocol === 'https:' ? 'wss:' : 'ws:';
        backendUrl.pathname = '/api/v1/market/ws';
        backendUrl.search = '';
        backendUrl.hash = '';
        return backendUrl.toString();
      } catch {
        const wsProtocol = apiBase.startsWith('https:') ? 'wss:' : 'ws:';
        const hostPath = apiBase.replace(/^https?:\/\//, '').replace(/\/api(\/v1)?$/, '');
        return `${wsProtocol}//${hostPath}/api/v1/market/ws`;
      }
    }

    // 3. Fallback for local development using Vite proxy
    if (typeof window !== 'undefined') {
      const isSecure = window.location.protocol === 'https:';
      const wsProtocol = isSecure ? 'wss:' : 'ws:';
      return `${wsProtocol}//${window.location.host}/api/v1/market/ws`;
    }
    return 'ws://localhost:8000/api/v1/market/ws';
  }

  public getStatus(): ConnectionStatusType {
    return this.status;
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.setStatus('connecting');

    try {
      const url = this.getSocketUrl();
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        const wasReconnecting = this.reconnectAttempts > 0;
        this.setStatus('connected');
        this.reconnectAttempts = 0;
        this.startHeartbeat();
        this.resubscribeAll();

        // Notify reconnect listeners to backfill any candles missed during disconnection
        if (wasReconnecting) {
          this.reconnectListeners.forEach((l) => {
            try {
              l();
            } catch (e) {
              console.error('Reconnect listener error:', e);
            }
          });
        }
      };

      this.ws.onmessage = (event: MessageEvent) => {
        this.handleMessage(event.data);
      };

      this.ws.onerror = (err) => {
        console.warn('Backend MarketSocket error:', err);
      };

      this.ws.onclose = () => {
        this.cleanupSocket();
        this.setStatus('disconnected');
        this.scheduleReconnect();
      };
    } catch (err) {
      console.error('Failed to initialize WebSocket:', err);
      this.setStatus('disconnected');
      this.scheduleReconnect();
    }
  }

  private setStatus(newStatus: ConnectionStatusType): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusListeners.forEach((listener) => {
        try {
          listener(newStatus);
        } catch (e) {
          console.error('Status listener error:', e);
        }
      });
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          // ignore
        }
      }
    }, 25000);
  }

  private stopHeartbeat(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;

    // Exponential backoff: 1s, 2s, 4s, 8s, up to 15s
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private cleanupSocket(): void {
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }

  private resubscribeAll(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    // Resubscribe tickers
    if (this.subscribedTickerSymbols.size > 0) {
      const symbols = Array.from(this.subscribedTickerSymbols);
      this.sendSubscription('ticker', symbols);
    }

    // Resubscribe candles
    this.activeCandleSubscriptions.forEach((resolution, symbol) => {
      this.sendSubscription(`candlestick_${resolution}`, [symbol]);
    });
  }

  private sendSubscription(channelName: string, symbols: string[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || symbols.length === 0) return;

    const payload = {
      type: 'subscribe',
      payload: {
        channels: [
          {
            name: channelName,
            symbols,
          },
        ],
      },
    };

    try {
      this.ws.send(JSON.stringify(payload));
    } catch (err) {
      console.warn('Failed to send subscription:', err);
    }
  }

  private sendUnsubscription(channelName: string, symbols: string[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || symbols.length === 0) return;

    const payload = {
      type: 'unsubscribe',
      payload: {
        channels: [
          {
            name: channelName,
            symbols,
          },
        ],
      },
    };

    try {
      this.ws.send(JSON.stringify(payload));
    } catch (err) {
      console.warn('Failed to send unsubscription:', err);
    }
  }

  public subscribeTickers(symbols: string[]): void {
    const toAdd: string[] = [];
    symbols.forEach((s) => {
      if (!this.subscribedTickerSymbols.has(s)) {
        this.subscribedTickerSymbols.add(s);
        toAdd.push(s);
      }
    });

    if (toAdd.length > 0) {
      this.connect();
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.sendSubscription('ticker', toAdd);
      }
    }
  }

  private candleSubscriberCount = new Map<string, number>();

  public subscribeCandles(symbol: string, resolution: string): void {
    const key = `${symbol}_${resolution}`;
    const prevCount = this.candleSubscriberCount.get(key) || 0;
    this.candleSubscriberCount.set(key, prevCount + 1);

    if (prevCount === 0) {
      this.activeCandleSubscriptions.set(symbol, resolution);
      this.connect();
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.sendSubscription(`candlestick_${resolution}`, [symbol]);
      }
    }
  }

  public unsubscribeCandles(symbol: string, resolution?: string): void {
    const res = resolution || this.activeCandleSubscriptions.get(symbol);
    if (!res) return;

    const key = `${symbol}_${res}`;
    const currentCount = this.candleSubscriberCount.get(key) || 1;
    const nextCount = Math.max(0, currentCount - 1);
    this.candleSubscriberCount.set(key, nextCount);

    if (nextCount === 0) {
      this.candleSubscriberCount.delete(key);
      this.sendUnsubscription(`candlestick_${res}`, [symbol]);
      if (this.activeCandleSubscriptions.get(symbol) === res) {
        this.activeCandleSubscriptions.delete(symbol);
      }
    }
  }

  public addTickerListener(fn: TickerListener): () => void {
    this.tickerListeners.add(fn);
    return () => this.tickerListeners.delete(fn);
  }

  public addCandleListener(fn: CandleListener): () => void {
    this.candleListeners.add(fn);
    return () => this.candleListeners.delete(fn);
  }

  public addStatusListener(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => this.statusListeners.delete(fn);
  }

  public addReconnectListener(fn: ReconnectListener): () => void {
    this.reconnectListeners.add(fn);
    return () => this.reconnectListeners.delete(fn);
  }

  private handleMessage(raw: string): void {
    try {
      const msg = JSON.parse(raw);

      // Connection status notice from backend
      if (msg.type === 'connection_status') {
        if (msg.status === 'connected') {
          this.setStatus('connected');
        } else if (msg.status === 'connecting') {
          this.setStatus('connecting');
        } else if (msg.status === 'disconnected') {
          this.setStatus('disconnected');
        }
        return;
      }

      // 1. Ticker updates
      if (msg.type === 'ticker') {
        const spotPrice = msg.sp ? parseFloat(msg.sp) : undefined;
        const symbol = msg.sy || msg.symbol;

        if (Array.isArray(msg.d)) {
          for (const item of msg.d) {
            const sym = item.s || symbol;
            const ohlc = item.ohlc || [];
            const close = ohlc[3] !== undefined ? Number(ohlc[3]) : undefined;
            if (!sym || close === undefined || isNaN(close)) continue;

            const update: WebSocketTickerUpdate = {
              symbol: sym,
              close,
              open: ohlc[0] !== undefined ? Number(ohlc[0]) : undefined,
              high: ohlc[1] !== undefined ? Number(ohlc[1]) : undefined,
              low: ohlc[2] !== undefined ? Number(ohlc[2]) : undefined,
              markPrice: item.m ? parseFloat(item.m) : undefined,
              spotPrice,
              change24h: item.m24hc ? parseFloat(item.m24hc) : undefined,
              bestAsk: item.q && item.q[0] ? parseFloat(item.q[0]) : undefined,
              bestBid: item.q && item.q[2] ? parseFloat(item.q[2]) : undefined,
              timestamp: msg.ts ? Math.floor(msg.ts / 1000) : Date.now(),
            };

            this.tickerListeners.forEach((l) => {
              try {
                l(update);
              } catch (e) {
                console.error('Ticker listener error:', e);
              }
            });
          }
        }
      }

      // 2. Candlestick updates (using robust normalizer supporting both full & short schema)
      if (typeof msg.type === 'string' && msg.type.startsWith('candlestick_')) {
        const parsed = normalizeWsCandle(msg);
        if (parsed) {
          this.candleListeners.forEach((l) => {
            try {
              l(parsed.candle, parsed.symbol, parsed.resolution);
            } catch (e) {
              console.error('Candle listener error:', e);
            }
          });
        }
      }
    } catch {
      // ignore json parse error
    }
  }

  public disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.cleanupSocket();
    this.setStatus('disconnected');
  }
}

// Singleton instance
export const marketSocket = new MarketSocketService();
