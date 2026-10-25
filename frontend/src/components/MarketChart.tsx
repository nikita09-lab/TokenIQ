import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import {
  RefreshCw,
  Layers,
  AlertTriangle,
  Radio,
  Calendar,
  X,
  Check,
  Info,
} from 'lucide-react';
import { getHistoricalCandles } from '../services/api';
import { marketSocket } from '../services/marketSocket';
import { applyCandleUpdate, mergeHistoricalCandles } from '../utils/candleSync';
import type {
  CandleData,
  ChartResolution,
  ConnectionStatusType,
  HistoryRangeConfig,
  HistoryRangePreset,
  MarketTicker,
} from '../types/market';

interface MarketChartProps {
  selectedTicker: MarketTicker | null;
  resolution: ChartResolution;
  onResolutionChange: (res: ChartResolution) => void;
  latestWsCandle?: CandleData | null;
  connectionStatus: ConnectionStatusType;
  historyRange: HistoryRangeConfig;
  onHistoryRangeChange: (range: HistoryRangeConfig) => void;
}

// Global in-memory cache to preserve loaded candles across navigation without refetching
const candleDataCache = new Map<string, CandleData[]>();

export const MarketChart: React.FC<MarketChartProps> = ({
  selectedTicker,
  resolution,
  onResolutionChange,
  connectionStatus,
  historyRange,
  onHistoryRangeChange,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // In-memory chronological candle store for the current active chart
  const candlesRef = useRef<CandleData[]>([]);
  const lastCandleTimeRef = useRef<number>(0);
  const isFetchingRef = useRef<boolean>(false);

  // UI state
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [candlesCount, setCandlesCount] = useState<number>(0);
  const [lastLiveUpdate, setLastLiveUpdate] = useState<Date | null>(null);
  const [limitationNotice, setLimitationNotice] = useState<string | null>(null);

  // Custom date picker state
  const [isCustomPickerOpen, setIsCustomPickerOpen] = useState<boolean>(false);
  const todayStr = useMemo(() => new Date().toISOString().split('T')[0], []);
  const [customStart, setCustomStart] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().split('T')[0];
  });
  const [customEnd, setCustomEnd] = useState<string>(todayStr);
  const [customError, setCustomError] = useState<string | null>(null);

  const selectedSymbol = selectedTicker?.symbol || '';

  // Resolution definitions
  const resolutions: { id: ChartResolution; label: string }[] = [
    { id: '1m', label: '1m' },
    { id: '5m', label: '5m' },
    { id: '15m', label: '15m' },
    { id: '1h', label: '1H' },
    { id: '1d', label: '1D' },
  ];

  // Range preset definitions
  const historyPresets: { id: HistoryRangePreset; label: string }[] = [
    { id: '1D', label: '1D' },
    { id: '7D', label: '7D' },
    { id: '1M', label: '1M' },
    { id: '3M', label: '3M' },
    { id: 'custom', label: 'Custom' },
  ];

  // Cache key generator
  const getCacheKey = useCallback(
    (sym: string, res: string, range: HistoryRangeConfig) => {
      if (range.type === 'custom') {
        return `${sym}_${res}_custom_${range.startDateStr}_${range.endDateStr}`;
      }
      return `${sym}_${res}_${range.type}`;
    },
    []
  );

  // Check if current range ends in the past (live updates should be paused)
  const isHistoricalOnlyRange = useMemo(() => {
    if (historyRange.type === 'custom' && historyRange.end) {
      const nowSec = Math.floor(Date.now() / 1000);
      return historyRange.end < nowSec - 300;
    }
    return false;
  }, [historyRange]);

  // ============================================================================
  // 1. CHART INITIALIZATION & RESIZE: Run ONCE on container mount
  // Stable chart reference preserved across updates, zero recreation/remove() on data ticks!
  // ============================================================================
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) return;

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 460;

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#0B0F17' },
        textColor: '#94A3B8',
        fontFamily: "'JetBrains Mono', 'Inter', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(0, 240, 255, 0.35)',
          width: 1,
          style: 3,
        },
        horzLine: {
          color: 'rgba(0, 240, 255, 0.35)',
          width: 1,
          style: 3,
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        textColor: '#94A3B8',
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10B981',
      downColor: '#F43F5E',
      borderUpColor: '#10B981',
      borderDownColor: '#F43F5E',
      wickUpColor: '#10B981',
      wickDownColor: '#F43F5E',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(56, 189, 248, 0.3)',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '', // overlay
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;

    // ResizeObserver: Only updates dimensions via applyOptions, NEVER removes chart!
    let animationFrameId: number | null = null;
    const ro = new ResizeObserver((entries) => {
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      animationFrameId = requestAnimationFrame(() => {
        for (const entry of entries) {
          const { width: w, height: h } = entry.contentRect;
          if (w > 0 && h > 0 && chartRef.current) {
            chartRef.current.applyOptions({ width: w, height: h });
          }
        }
      });
    });

    ro.observe(container);

    return () => {
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      ro.disconnect();
      if (chartRef.current) {
        try {
          chartRef.current.remove();
        } catch {
          // ignore
        }
        chartRef.current = null;
        candlestickSeriesRef.current = null;
        volumeSeriesRef.current = null;
      }
    };
  }, []); // Strictly empty dependency array: create chart ONCE on mount!

  // ============================================================================
  // 2. HISTORICAL DATA LOADING: Triggered ONLY when symbol, resolution, or range changes
  // ============================================================================
  const loadHistoricalCandles = useCallback(
    async (sym: string, res: ChartResolution, range: HistoryRangeConfig) => {
      if (!sym) return;

      const cacheKey = getCacheKey(sym, res, range);
      const cached = candleDataCache.get(cacheKey);

      // If cached data exists, load immediately to prevent blank screen
      if (cached && cached.length > 0 && candlestickSeriesRef.current && volumeSeriesRef.current && chartRef.current) {
        candlesRef.current = [...cached];
        lastCandleTimeRef.current = cached[cached.length - 1].time;
        setCandlesCount(cached.length);

        candlestickSeriesRef.current.setData(
          cached.map((c) => ({
            time: c.time as Time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }))
        );
        volumeSeriesRef.current.setData(
          cached.map((c) => ({
            time: c.time as Time,
            value: c.volume,
            color: c.close >= c.open ? 'rgba(16, 185, 129, 0.35)' : 'rgba(244, 63, 94, 0.35)',
          }))
        );
        chartRef.current.timeScale().fitContent();
      } else {
        setIsLoading(true);
      }

      setError(null);
      isFetchingRef.current = true;

      try {
        const result = await getHistoricalCandles(sym, res, range);
        const { candles, limitationNotice: notice } = result;

        setLimitationNotice(notice || null);

        if (!candles || candles.length === 0) {
          if (!cached) {
            setError(`No historical candle data returned for ${sym} (${res}, ${range.label})`);
          }
          setIsLoading(false);
          isFetchingRef.current = false;
          return;
        }

        // Update in-memory state & cache
        candleDataCache.set(cacheKey, candles);
        candlesRef.current = [...candles];
        lastCandleTimeRef.current = candles[candles.length - 1].time;
        setCandlesCount(candles.length);

        if (candlestickSeriesRef.current && volumeSeriesRef.current && chartRef.current) {
          candlestickSeriesRef.current.setData(
            candles.map((c) => ({
              time: c.time as Time,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
            }))
          );
          volumeSeriesRef.current.setData(
            candles.map((c) => ({
              time: c.time as Time,
              value: c.volume,
              color: c.close >= c.open ? 'rgba(16, 185, 129, 0.35)' : 'rgba(244, 63, 94, 0.35)',
            }))
          );
          chartRef.current.timeScale().fitContent();
        }
      } catch (err) {
        console.error('Failed to load historical candles:', err);
        if (!cached) {
          setError(err instanceof Error ? err.message : 'Error retrieving candle data');
        }
      } finally {
        setIsLoading(false);
        isFetchingRef.current = false;
      }
    },
    [getCacheKey]
  );

  // Trigger historical reload on symbol / resolution / range change
  useEffect(() => {
    if (!selectedSymbol) return;

    loadHistoricalCandles(selectedSymbol, resolution, historyRange);

    // Subscribe WebSocket for live candle stream on this symbol & resolution
    marketSocket.subscribeCandles(selectedSymbol, resolution);

    return () => {
      marketSocket.unsubscribeCandles(selectedSymbol);
    };
  }, [selectedSymbol, resolution, historyRange, loadHistoricalCandles]);

  // ============================================================================
  // 3. LIVE WEBSOCKET INCREMENTAL UPDATES (Zero Canvas Rebuilding, Zero Full Re-renders)
  // Uses series.update() in place, preserving zoom, scroll, and crosshairs!
  // ============================================================================
  useEffect(() => {
    if (!selectedSymbol || isHistoricalOnlyRange) return;

    const unsub = marketSocket.addCandleListener((candle, sym, res) => {
      // Ensure packet matches active symbol and resolution
      if (sym !== selectedSymbol || res !== resolution) return;

      const candleSeries = candlestickSeriesRef.current;
      const volSeries = volumeSeriesRef.current;
      if (!candleSeries || !volSeries) return;

      const result = applyCandleUpdate(candlesRef.current, candle);
      if (result.action === 'ignored') return;

      // Update in-memory candle array
      candlesRef.current = result.updatedCandles;
      lastCandleTimeRef.current = result.latestBar.time;

      // Incremental series update: updates active bar or appends new bar without tearing down chart!
      candleSeries.update({
        time: result.latestBar.time as Time,
        open: result.latestBar.open,
        high: result.latestBar.high,
        low: result.latestBar.low,
        close: result.latestBar.close,
      });

      volSeries.update({
        time: result.latestBar.time as Time,
        value: result.latestBar.volume,
        color:
          result.latestBar.close >= result.latestBar.open
            ? 'rgba(16, 185, 129, 0.4)'
            : 'rgba(244, 63, 94, 0.4)',
      });

      if (result.action === 'appended') {
        setCandlesCount(result.updatedCandles.length);
      }

      setLastLiveUpdate(new Date());
    });

    return () => {
      unsub();
    };
  }, [selectedSymbol, resolution, isHistoricalOnlyRange]);

  // ============================================================================
  // 4. RECONNECTION BACKFILL (Recover missed bars after network disconnect)
  // ============================================================================
  useEffect(() => {
    if (!selectedSymbol || isHistoricalOnlyRange) return;

    const unsubReconnect = marketSocket.addReconnectListener(async () => {
      if (isFetchingRef.current) return;
      const lastTime = lastCandleTimeRef.current;
      if (!lastTime) return;

      try {
        const nowSec = Math.floor(Date.now() / 1000);
        // Backfill candles between last known timestamp and now
        const backfillRange: HistoryRangeConfig = {
          type: 'custom',
          start: Math.max(lastTime - 3600, 0),
          end: nowSec,
          label: 'reconnect_backfill',
        };

        const result = await getHistoricalCandles(selectedSymbol, resolution, backfillRange);
        if (result.candles && result.candles.length > 0) {
          const merged = mergeHistoricalCandles(candlesRef.current, result.candles);
          candlesRef.current = merged;
          lastCandleTimeRef.current = merged[merged.length - 1].time;
          setCandlesCount(merged.length);

          // Update latest bars to catch up
          if (candlestickSeriesRef.current && volumeSeriesRef.current) {
            for (const bar of result.candles) {
              candlestickSeriesRef.current.update({
                time: bar.time as Time,
                open: bar.open,
                high: bar.high,
                low: bar.low,
                close: bar.close,
              });
              volumeSeriesRef.current.update({
                time: bar.time as Time,
                value: bar.volume,
                color: bar.close >= bar.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)',
              });
            }
          }
        }
      } catch (err) {
        console.warn('Reconnection candle backfill failed:', err);
      }
    });

    return () => {
      unsubReconnect();
    };
  }, [selectedSymbol, resolution, isHistoricalOnlyRange]);

  // Manual reload trigger
  const handleManualReload = () => {
    if (!selectedSymbol) return;
    loadHistoricalCandles(selectedSymbol, resolution, historyRange);
  };

  // Custom date range application
  const handleApplyCustomRange = () => {
    setCustomError(null);

    if (!customStart || !customEnd) {
      setCustomError('Please select both start and end dates.');
      return;
    }

    if (customEnd < customStart) {
      setCustomError('End date cannot be earlier than start date.');
      return;
    }

    if (customEnd > todayStr) {
      setCustomError('End date cannot be in the future.');
      return;
    }

    const startDateObj = new Date(`${customStart}T00:00:00Z`);
    const endDateObj = new Date(`${customEnd}T23:59:59Z`);

    const startSec = Math.floor(startDateObj.getTime() / 1000);
    const endSec = Math.min(Math.floor(endDateObj.getTime() / 1000), Math.floor(Date.now() / 1000));

    if (startSec >= endSec) {
      setCustomError('Invalid range span.');
      return;
    }

    onHistoryRangeChange({
      type: 'custom',
      start: startSec,
      end: endSec,
      label: `${customStart} to ${customEnd}`,
      startDateStr: customStart,
      endDateStr: customEnd,
    });

    setIsCustomPickerOpen(false);
  };

  const handleCustomPreset = (daysBack: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - daysBack);

    setCustomStart(start.toISOString().split('T')[0]);
    setCustomEnd(end.toISOString().split('T')[0]);
    setCustomError(null);
  };

  const isPositive = (selectedTicker?.change24h || 0) >= 0;

  return (
    <div className="flex flex-col rounded-xl bg-[#0F1422] border border-white/[0.07] overflow-hidden shadow-xl select-none">
      {/* Chart Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-white/[0.07] bg-[#0D121F]">
        {/* Left: Pair Info & Live Price */}
        <div className="flex flex-wrap items-center gap-3">
          {selectedTicker ? (
            <>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-white font-mono tracking-tight">{selectedTicker.symbol}</h2>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-mono uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                  {selectedTicker.contractType.replace('_', ' ')}
                </span>
              </div>

              <div className="flex items-baseline gap-2 pl-2 border-l border-white/[0.08]">
                <span className="text-xl font-bold text-white font-mono tabular-nums tracking-tight">
                  ${selectedTicker.lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                </span>
                {selectedTicker.change24h !== null && (
                  <span
                    className={`text-xs font-mono font-semibold tabular-nums px-2 py-0.5 rounded ${
                      isPositive
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                    }`}
                  >
                    {isPositive ? '+' : ''}
                    {selectedTicker.change24h.toFixed(2)}%
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-sm font-semibold text-slate-300 font-mono">Select a Trading Pair</div>
          )}
        </div>

        {/* Right Toolbar: History Range & Interval Selectors */}
        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
          {/* 1. History Range Controls */}
          <div className="relative flex items-center gap-1 p-1 rounded-lg bg-[#080B12] border border-white/[0.06]">
            <span className="text-[10px] font-mono text-slate-400 uppercase px-1 hidden sm:inline">Range:</span>
            {historyPresets.map((hp) => {
              const isSelected = historyRange.type === hp.id;
              return (
                <button
                  key={hp.id}
                  onClick={() => {
                    if (hp.id === 'custom') {
                      setIsCustomPickerOpen((prev) => !prev);
                    } else {
                      setIsCustomPickerOpen(false);
                      onHistoryRangeChange({
                        type: hp.id,
                        label: hp.id === '1M' ? '1M (30D)' : hp.id === '3M' ? '3M (90D)' : hp.id,
                      });
                    }
                  }}
                  className={`px-2 py-0.5 rounded text-xs font-mono font-semibold transition-all ${
                    isSelected
                      ? 'bg-blue-500/25 text-blue-300 border border-blue-500/40 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title={hp.id === 'custom' ? 'Select custom date range' : `Load ${hp.label} of historical data`}
                >
                  {hp.label}
                </button>
              );
            })}

            {/* Custom Date Picker Popover Panel */}
            {isCustomPickerOpen && (
              <div className="absolute right-0 top-full mt-2 w-72 p-4 bg-[#121826] border border-white/[0.12] rounded-xl shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150">
                <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/[0.08]">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-white font-sans">
                    <Calendar className="w-4 h-4 text-cyan-400" />
                    <span>Custom Date Range</span>
                  </div>
                  <button
                    onClick={() => setIsCustomPickerOpen(false)}
                    className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/[0.06]"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="flex items-center gap-1.5 mb-3">
                  <button
                    onClick={() => handleCustomPreset(3)}
                    className="px-2 py-0.5 rounded bg-white/[0.05] hover:bg-white/[0.1] text-[10px] font-mono text-slate-300"
                  >
                    3 Days
                  </button>
                  <button
                    onClick={() => handleCustomPreset(14)}
                    className="px-2 py-0.5 rounded bg-white/[0.05] hover:bg-white/[0.1] text-[10px] font-mono text-slate-300"
                  >
                    14 Days
                  </button>
                  <button
                    onClick={() => handleCustomPreset(30)}
                    className="px-2 py-0.5 rounded bg-white/[0.05] hover:bg-white/[0.1] text-[10px] font-mono text-slate-300"
                  >
                    30 Days
                  </button>
                </div>

                <div className="space-y-2.5 text-xs font-mono">
                  <div>
                    <label className="block text-[10px] text-slate-400 uppercase mb-1">Start Date (UTC)</label>
                    <input
                      type="date"
                      value={customStart}
                      max={customEnd || todayStr}
                      onChange={(e) => {
                        setCustomStart(e.target.value);
                        setCustomError(null);
                      }}
                      className="w-full px-2.5 py-1.5 rounded-lg bg-[#0A0E17] border border-white/[0.1] text-slate-200 text-xs focus:outline-none focus:border-cyan-400"
                    />
                  </div>

                  <div>
                    <label className="block text-[10px] text-slate-400 uppercase mb-1">End Date (UTC)</label>
                    <input
                      type="date"
                      value={customEnd}
                      min={customStart}
                      max={todayStr}
                      onChange={(e) => {
                        setCustomEnd(e.target.value);
                        setCustomError(null);
                      }}
                      className="w-full px-2.5 py-1.5 rounded-lg bg-[#0A0E17] border border-white/[0.1] text-slate-200 text-xs focus:outline-none focus:border-cyan-400"
                    />
                  </div>
                </div>

                {customError && (
                  <div className="mt-2.5 p-2 rounded bg-rose-500/10 border border-rose-500/20 text-rose-300 text-[11px] leading-tight">
                    {customError}
                  </div>
                )}

                <div className="flex items-center justify-end gap-2 mt-4 pt-2 border-t border-white/[0.08]">
                  <button
                    onClick={() => setIsCustomPickerOpen(false)}
                    className="px-3 py-1 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-white/[0.05] transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleApplyCustomRange}
                    className="px-3.5 py-1 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-semibold font-mono flex items-center gap-1 transition-colors"
                  >
                    <Check className="w-3.5 h-3.5" />
                    Apply Range
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 2. Candle Granularity Interval Selector */}
          <div className="flex items-center gap-1 p-1 rounded-lg bg-[#080B12] border border-white/[0.06]">
            <span className="text-[10px] font-mono text-slate-400 uppercase px-1 hidden sm:inline">Interval:</span>
            {resolutions.map((r) => (
              <button
                key={r.id}
                onClick={() => onResolutionChange(r.id)}
                className={`px-2.5 py-0.5 rounded text-xs font-mono font-semibold transition-all ${
                  resolution === r.id
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-glow-cyan/20'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title={`Set candle interval to ${r.label}`}
              >
                {r.label}
              </button>
            ))}
          </div>

          {/* 3. Live Stream / Historical indicator */}
          <div className="hidden lg:flex items-center gap-1.5 text-[11px] font-mono text-slate-400 bg-white/[0.04] px-2.5 py-1 rounded-lg border border-white/[0.06]">
            {isHistoricalOnlyRange ? (
              <span className="text-amber-400 flex items-center gap-1">
                <Calendar className="w-3.5 h-3.5" />
                <span>Closed History</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <Radio
                  className={`w-3.5 h-3.5 ${
                    connectionStatus === 'connected' ? 'text-emerald-400 animate-pulse' : 'text-slate-400'
                  }`}
                />
                <span>
                  {lastLiveUpdate
                    ? `Live ${lastLiveUpdate.toLocaleTimeString([], { hour12: false })}`
                    : connectionStatus === 'connected'
                    ? 'Streaming Live'
                    : 'Connecting'}
                </span>
              </span>
            )}
          </div>

          {/* Reload / Refresh Button */}
          <button
            onClick={handleManualReload}
            disabled={isLoading}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-white/[0.06] transition-colors"
            title="Reload historical candles"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Limitation Notice Pill if range is large */}
      {limitationNotice && (
        <div className="px-4 py-1.5 bg-blue-500/10 border-b border-blue-500/20 text-blue-300 text-xs font-mono flex items-center gap-2">
          <Info className="w-3.5 h-3.5 shrink-0 text-cyan-400" />
          <span>{limitationNotice}</span>
        </div>
      )}

      {/* Chart Canvas Area */}
      <div className="relative w-full h-[460px] bg-[#0B0F17]">
        {/* Subtle Loading Spinner over chart (keeping previous candles visible) */}
        {isLoading && (
          <div className="absolute top-3 right-3 z-20 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#0B0F17]/90 border border-cyan-500/30 text-cyan-300 text-xs font-mono shadow-xl backdrop-blur-md">
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-cyan-400" />
            <span>Updating history...</span>
          </div>
        )}

        {/* Error Overlay with Retry */}
        {error && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-[#0B0F17]/90 p-6 text-center">
            <AlertTriangle className="w-8 h-8 text-amber-400 mb-2" />
            <span className="text-sm font-semibold text-slate-200 mb-1">Failed to load chart</span>
            <p className="text-xs text-slate-400 max-w-md mb-4">{error}</p>
            <button
              onClick={handleManualReload}
              className="px-4 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-mono font-semibold hover:bg-cyan-500/30 transition-all"
            >
              Retry Loading Candles
            </button>
          </div>
        )}

        {/* Empty state when no ticker is selected */}
        {!selectedSymbol && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#0B0F17] text-slate-400">
            <Layers className="w-10 h-10 stroke-1 text-slate-400 mb-2" />
            <span className="text-sm font-medium text-slate-300">Select a Trading Pair</span>
            <span className="text-xs text-slate-400">Choose a pair from the market table to view live candlestick charts</span>
          </div>
        )}

        {/* Lightweight Charts mounting element: ALWAYS preserved in DOM */}
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* Chart Footer Info Bar */}
      <div className="flex flex-wrap items-center justify-between px-4 py-2 bg-[#0A0E17]/80 border-t border-white/[0.06] text-[11px] font-mono text-slate-400 gap-2">
        <div className="flex flex-wrap items-center gap-4">
          <span>
            Bars: <span className="text-slate-200 font-semibold">{candlesCount}</span>
          </span>
          <span>
            Interval: <span className="text-cyan-400 font-semibold">{resolution}</span>
          </span>
          <span>
            Range:{' '}
            <span className="text-blue-300 font-semibold">
              {historyRange.type === 'custom'
                ? `${historyRange.startDateStr} → ${historyRange.endDateStr}`
                : historyRange.label || historyRange.type}
            </span>
          </span>
        </div>
        <div className="flex items-center gap-2 text-slate-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
          <span>Delta Exchange Public WebSocket Feed · Zero-Flicker Streaming</span>
        </div>
      </div>
    </div>
  );
};
