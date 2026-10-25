import React, { useState, useMemo } from 'react';
import {
  Play,
  RotateCcw,
  TrendingUp,
  TrendingDown,
  Target,
  Percent,
  DollarSign,
  AlertTriangle,
  Clock,
  Layers,
  ChevronDown,
  ChevronUp,
  Info,
  Calendar,
  Sparkles,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import { runBacktest } from '../services/api';
import type { BacktestRequest, BacktestResultData, TradeRecord, EquityPointData } from '../types/market';

interface BacktestingViewProps {
  initialSymbol?: string;
  onSelectSymbol?: (symbol: string) => void;
}

const POPULAR_SYMBOLS = [
  'BTCUSD',
  'ETHUSD',
  'SOLUSD',
  'XRPUSD',
  'DOGEUSD',
  'AVAXUSD',
  'BNBUSD',
  'ADAUSD',
  'LINKUSD',
  'NEARUSD',
];

const RESOLUTIONS = [
  { id: '15m', label: '15m' },
  { id: '1h', label: '1 Hour' },
  { id: '4h', label: '4 Hours' },
  { id: '1d', label: '1 Day' },
];

const COMPARISON_PRESETS = [
  { id: '9-11-20', label: 'EMA 9 / 11 / 20', fast: 9, middle: 11, slow: 20 },
  { id: '8-13-21', label: 'EMA 8 / 13 / 21', fast: 8, middle: 13, slow: 21 },
  { id: '5-9-21', label: 'EMA 5 / 9 / 21', fast: 5, middle: 9, slow: 21 },
  { id: '5-13-34', label: 'EMA 5 / 13 / 34', fast: 5, middle: 13, slow: 34 },
  { id: '8-13-34', label: 'EMA 8 / 13 / 34', fast: 8, middle: 13, slow: 34 },
  { id: '10-20-50', label: 'EMA 10 / 20 / 50', fast: 10, middle: 20, slow: 50 },
];

export const BacktestingView: React.FC<BacktestingViewProps> = ({
  initialSymbol = 'BTCUSD',
  onSelectSymbol,
}) => {
  // Form parameters
  const [symbol, setSymbol] = useState<string>(initialSymbol);
  const [resolution, setResolution] = useState<string>('1h');
  const [rangeDays, setRangeDays] = useState<number>(90);
  const [initialCapital, setInitialCapital] = useState<number>(10000);
  const [feePercent, setFeePercent] = useState<number>(0.05); // 0.05%
  const [slippagePercent, setSlippagePercent] = useState<number>(0.05); // 0.05%
  const [executionMode, setExecutionMode] = useState<'next_open' | 'current_close'>('next_open');

  // Strategy Parameters
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [fastPeriod, setFastPeriod] = useState<number>(9);
  const [middlePeriod, setMiddlePeriod] = useState<number>(11);
  const [slowPeriod, setSlowPeriod] = useState<number>(20);
  const [rsiPeriod] = useState<number>(14);
  const rsiFilterEnabled = false;
  const [rsiBuyMin, setRsiBuyMin] = useState<number>(40.0);
  const [rsiOverbought, setRsiOverbought] = useState<number>(70.0);
  const [rsiSellMax, setRsiSellMax] = useState<number>(60.0);
  const [rsiOversold, setRsiOversold] = useState<number>(30.0);
  const [volumeFilterEnabled, setVolumeFilterEnabled] = useState<boolean>(false);
  const [volumeMaPeriod, setVolumeMaPeriod] = useState<number>(20);

  // Execution states
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResultData | null>(null);
  const [comparisonResults, setComparisonResults] = useState<BacktestResultData[]>([]);
  const [selectedComparisonPresets, setSelectedComparisonPresets] = useState<string[]>(['9-11-20', '8-13-21']);
  const [showComparisonOptions, setShowComparisonOptions] = useState<boolean>(false);
  const [isComparing, setIsComparing] = useState<boolean>(false);

  // Selected trade filter in history table
  const [tradeFilter, setTradeFilter] = useState<'ALL' | 'WIN' | 'LOSS'>('ALL');

  const handleRunBacktest = async () => {
    setIsRunning(true);
    setError(null);

    const now = Math.floor(Date.now() / 1000);
    const startTime = now - rangeDays * 86400;

    const payload: BacktestRequest = {
      symbol: symbol.trim().toUpperCase(),
      resolution,
      start_time: startTime,
      end_time: now,
      initial_capital: Number(initialCapital),
      fee_rate: Number(feePercent) / 100.0,
      slippage_rate: Number(slippagePercent) / 100.0,
      execution_mode: executionMode,
      strategy_params: {
        fast_period: Number(fastPeriod),
        middle_period: Number(middlePeriod),
        slow_period: Number(slowPeriod),
        rsi_period: Number(rsiPeriod),
        rsi_filter_enabled: false,
        rsi_buy_min: Number(rsiBuyMin),
        rsi_overbought: Number(rsiOverbought),
        rsi_sell_max: Number(rsiSellMax),
        rsi_oversold: Number(rsiOversold),
        volume_confirmation_enabled: Boolean(volumeFilterEnabled),
        volume_ma_period: Number(volumeMaPeriod),
        sell_intent: 'CLOSE_LONG',
      },
    };

    try {
      const data = await runBacktest(payload);
      setResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || 'Backtest failed to execute.');
    } finally {
      setIsRunning(false);
    }
  };

  const handleComparePresets = async () => {
    const selected = COMPARISON_PRESETS.filter((preset) => selectedComparisonPresets.includes(preset.id));
    if (selected.length < 2) {
      setError('Select at least 2 EMA presets to compare.');
      return;
    }
    if (selected.length > 6) {
      setError('Compare up to 6 presets at a time to keep the run manageable.');
      return;
    }

    setIsComparing(true);
    setError(null);
    setComparisonResults([]);
    const now = Math.floor(Date.now() / 1000);
    const common = {
      symbol: symbol.trim().toUpperCase(),
      resolution,
      start_time: now - rangeDays * 86400,
      end_time: now,
      initial_capital: Number(initialCapital),
      fee_rate: Number(feePercent) / 100.0,
      slippage_rate: Number(slippagePercent) / 100.0,
      execution_mode: executionMode,
      strategy_params: { rsi_filter_enabled: false, sell_intent: 'CLOSE_LONG' },
    } as const;
    try {
      const results: BacktestResultData[] = [];
      for (const preset of selected) {
        const data = await runBacktest({
          ...common,
          strategy_params: {
            ...common.strategy_params,
            fast_period: preset.fast,
            middle_period: preset.middle,
            slow_period: preset.slow,
          },
        });
        results.push(data);
        setComparisonResults([...results]);
      }
      setComparisonResults(results);
      if (results.length) setResult(results[0]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || 'Preset comparison failed.');
    } finally {
      setIsComparing(false);
    }
  };

  const filteredTrades = useMemo(() => {
    if (!result?.trades) return [];
    if (tradeFilter === 'WIN') return result.trades.filter((t) => t.net_pnl > 0);
    if (tradeFilter === 'LOSS') return result.trades.filter((t) => t.net_pnl < 0);
    return result.trades;
  }, [result, tradeFilter]);

  // Format Unix timestamp to readable date/time
  const formatTs = (ts: number): string => {
    return new Date(ts * 1000).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  };

  // SVG Chart Dimensions & Computations for Equity Curve
  const chartData = useMemo(() => {
    if (!result?.equity_curve || result.equity_curve.length === 0) return null;
    const curve = result.equity_curve;
    const equities = curve.map((p) => p.equity);
    const minEq = Math.min(...equities, result.metrics.initial_capital * 0.95);
    const maxEq = Math.max(...equities, result.metrics.initial_capital * 1.05);
    const range = maxEq - minEq || 1;

    const width = 800;
    const height = 240;
    const padding = 20;

    const points = curve.map((p, idx) => {
      const x = padding + (idx / (curve.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((p.equity - minEq) / range) * (height - 2 * padding);
      return { x, y, point: p };
    });

    const pathD = points.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`, '');
    const areaD = `${pathD} L ${(width - padding).toFixed(1)} ${(height - padding).toFixed(1)} L ${padding} ${(height - padding).toFixed(1)} Z`;

    const baselineY = height - padding - ((result.metrics.initial_capital - minEq) / range) * (height - 2 * padding);

    // Drawdown curve
    const maxDdPct = Math.max(...curve.map((p) => p.drawdown_pct), 5);
    const ddHeight = 80;
    const ddPoints = curve.map((p, idx) => {
      const x = padding + (idx / (curve.length - 1)) * (width - 2 * padding);
      const y = (p.drawdown_pct / maxDdPct) * (ddHeight - 20) + 10;
      return { x, y };
    });
    const ddPathD = ddPoints.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`, '');
    const ddAreaD = `${ddPathD} L ${(width - padding).toFixed(1)} 0 L ${padding} 0 Z`;

    return {
      width,
      height,
      points,
      pathD,
      areaD,
      baselineY,
      minEq,
      maxEq,
      ddHeight,
      ddPoints,
      ddPathD,
      ddAreaD,
      maxDdPct,
    };
  }, [result]);

  return (
    <div className="flex-1 overflow-y-auto bg-[#080A0F] p-4 lg:p-6 space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
              <span className="text-cyan-400">⚡</span> Strategy Backtesting Engine
            </h1>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-semibold">
              PHASE 3 • EVENT-DRIVEN
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Simulate one Triple EMA strategy (9/11/20 or 8/13/21) on historical Delta Exchange candles. RSI filtering is off.
            Next-candle execution strictly prevents look-ahead bias.
          </p>
        </div>

        <button
          onClick={handleRunBacktest}
          disabled={isRunning}
          className={`flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-xs transition-all shadow-lg select-none ${
            isRunning
              ? 'bg-cyan-500/30 text-cyan-300 cursor-not-allowed border border-cyan-500/30'
              : 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 hover:shadow-cyan-500/20 active:scale-[0.98]'
          }`}
        >
          {isRunning ? (
            <>
              <RotateCcw className="w-3.5 h-3.5 animate-spin text-cyan-300" />
              <span>Simulating Market...</span>
            </>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Run Backtest</span>
            </>
          )}
        </button>
        <button
          onClick={() => setShowComparisonOptions((open) => !open)}
          disabled={isRunning || isComparing}
          className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-semibold text-xs border border-violet-400/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20 disabled:opacity-50"
        >
          {showComparisonOptions ? 'Hide comparison options' : `Compare strategies (${selectedComparisonPresets.length} selected)`}
        </button>
      </div>

      {showComparisonOptions && (
        <section className="rounded-xl border border-violet-400/20 bg-[#0B0F17] p-4 space-y-3">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-white">Choose EMA strategies to compare</h3>
              <p className="text-xs text-slate-400 mt-1">Select 2–6 presets. All runs use the same pair, timeframe, date range, capital, fees and slippage.</p>
            </div>
            <span className="text-xs font-mono text-violet-200">{selectedComparisonPresets.length}/6 selected</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {COMPARISON_PRESETS.map((preset) => {
              const checked = selectedComparisonPresets.includes(preset.id);
              return (
                <label key={preset.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-3 text-sm transition-colors ${checked ? 'border-violet-400/40 bg-violet-500/10 text-white' : 'border-white/[0.08] bg-black/10 text-slate-300 hover:border-white/20'}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!checked && selectedComparisonPresets.length >= 6}
                    onChange={(event) => {
                      setSelectedComparisonPresets((current) => event.target.checked ? [...current, preset.id] : current.filter((id) => id !== preset.id));
                      setComparisonResults([]);
                    }}
                    className="h-4 w-4 accent-violet-400"
                  />
                  <span>{preset.label}</span>
                </label>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setSelectedComparisonPresets(COMPARISON_PRESETS.map((p) => p.id))} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5">Select all (6)</button>
            <button type="button" onClick={() => setSelectedComparisonPresets(['9-11-20', '8-13-21'])} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5">Reset to 2 defaults</button>
            <button type="button" onClick={handleComparePresets} disabled={isRunning || isComparing || selectedComparisonPresets.length < 2} className="ml-auto flex items-center gap-2 rounded-lg bg-violet-400 px-4 py-2.5 text-xs font-semibold text-slate-950 hover:bg-violet-300 disabled:cursor-not-allowed disabled:opacity-50">
              {isComparing ? <><RotateCcw className="h-3.5 w-3.5 animate-spin" /> Running {comparisonResults.length + 1} of {selectedComparisonPresets.length}…</> : `Run ${selectedComparisonPresets.length} comparisons`}
            </button>
          </div>
        </section>
      )}

      {/* Control Panel Card */}
      <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-5 shadow-sm space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Symbol Selector */}
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5 uppercase tracking-wider">
              Trading Pair
            </label>
            <select
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                if (onSelectSymbol) onSelectSymbol(e.target.value);
              }}
              className="w-full bg-[#121824] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/60 font-mono"
            >
              {POPULAR_SYMBOLS.map((s) => (
                <option key={s} value={s}>
                  {s} (Delta Perp)
                </option>
              ))}
            </select>
          </div>

          {/* Candle Resolution */}
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5 uppercase tracking-wider">
              Candle Resolution
            </label>
            <div className="grid grid-cols-4 gap-1 bg-[#121824] p-1 border border-white/[0.1] rounded-lg">
              {RESOLUTIONS.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setResolution(r.id)}
                  type="button"
                  className={`py-1 text-center text-[11px] font-mono rounded transition-colors ${
                    resolution === r.id
                      ? 'bg-cyan-500/20 text-cyan-400 font-semibold border border-cyan-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* Historical Range Presets */}
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5 uppercase tracking-wider">
              Lookback Range
            </label>
            <div className="grid grid-cols-6 gap-1 bg-[#121824] p-1 border border-white/[0.1] rounded-lg">
              {[
                { days: 7, label: '7D' },
                { days: 30, label: '30D' },
                { days: 60, label: '60D' },
                { days: 90, label: '90D' },
                { days: 180, label: '180D' },
                { days: 365, label: '1Y' },
              ].map((preset) => (
                <button
                  key={preset.days}
                  onClick={() => setRangeDays(preset.days)}
                  type="button"
                  className={`py-1 text-center text-[11px] font-mono rounded transition-colors ${
                    rangeDays === preset.days
                      ? 'bg-cyan-500/20 text-cyan-400 font-semibold border border-cyan-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Initial Capital */}
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5 uppercase tracking-wider">
              Starting Capital ($)
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-slate-500 text-xs">$</span>
              <input
                type="number"
                min="100"
                step="500"
                value={initialCapital}
                onChange={(e) => setInitialCapital(Math.max(1, Number(e.target.value)))}
                className="w-full bg-[#121824] border border-white/[0.1] rounded-lg pl-7 pr-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/60 font-mono"
              />
            </div>
          </div>
        </div>

        {/* Execution Model & Assumptions Strip */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 border-t border-white/[0.05]">
          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5">
              Execution Timing (Look-Ahead Bias)
            </label>
            <select
              value={executionMode}
              onChange={(e) => setExecutionMode(e.target.value as any)}
              className="w-full bg-[#121824] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/60 font-mono"
            >
              <option value="next_open">Next Candle Open (Look-Ahead Free)</option>
              <option value="current_close">Current Candle Close (Idealized)</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5">
              Trading Fee per Order (%)
            </label>
            <div className="relative">
              <input
                type="number"
                min="0"
                max="2"
                step="0.01"
                value={feePercent}
                onChange={(e) => setFeePercent(Math.max(0, Number(e.target.value)))}
                className="w-full bg-[#121824] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/60 font-mono pr-8"
              />
              <span className="absolute right-3 top-2 text-slate-500 text-xs font-mono">%</span>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-slate-400 mb-1.5">
              Execution Slippage (%)
            </label>
            <div className="relative">
              <input
                type="number"
                min="0"
                max="2"
                step="0.01"
                value={slippagePercent}
                onChange={(e) => setSlippagePercent(Math.max(0, Number(e.target.value)))}
                className="w-full bg-[#121824] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500/60 font-mono pr-8"
              />
              <span className="absolute right-3 top-2 text-slate-500 text-xs font-mono">%</span>
            </div>
          </div>
        </div>

        {/* Collapsible Strategy Parameters Accordion */}
        <div className="pt-2">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 font-mono transition-colors"
          >
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            <span>{showAdvanced ? 'Hide Strategy Parameters' : 'Triple EMA Presets (RSI filter off)'}</span>
          </button>

          {showAdvanced && (
            <div className="mt-4 p-4 rounded-lg bg-[#0E131E] border border-white/[0.06] space-y-4 animate-in fade-in duration-200">
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => { setFastPeriod(9); setMiddlePeriod(11); setSlowPeriod(20); }} className={`px-3 py-1.5 rounded text-xs font-mono border ${fastPeriod === 9 && middlePeriod === 11 && slowPeriod === 20 ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' : 'bg-slate-800 text-slate-300 border-white/10'}`}>EMA 9 / 11 / 20</button>
                <button type="button" onClick={() => { setFastPeriod(8); setMiddlePeriod(13); setSlowPeriod(21); }} className={`px-3 py-1.5 rounded text-xs font-mono border ${fastPeriod === 8 && middlePeriod === 13 && slowPeriod === 21 ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' : 'bg-slate-800 text-slate-300 border-white/10'}`}>EMA 8 / 13 / 21</button>
                <span className="px-3 py-1.5 rounded text-xs font-mono text-slate-400 bg-slate-900 border border-white/10">RSI filter OFF</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-[10px] font-mono text-slate-400 mb-1">Fast EMA Period</label>
                <input type="number" min="2" max="100" value={fastPeriod} onChange={(e) => setFastPeriod(Number(e.target.value))} className="w-full bg-[#161D2B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white font-mono" />
              </div>
              <div>
                <label className="block text-[10px] font-mono text-slate-400 mb-1">Middle EMA Period</label>
                <input type="number" min="3" max="200" value={middlePeriod} onChange={(e) => setMiddlePeriod(Number(e.target.value))} className="w-full bg-[#161D2B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white font-mono" />
              </div>
              <div>
                <label className="block text-[10px] font-mono text-slate-400 mb-1">Slow EMA Period</label>
                <input type="number" min="4" max="300" value={slowPeriod} onChange={(e) => setSlowPeriod(Number(e.target.value))} className="w-full bg-[#161D2B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white font-mono" />
              </div>
              <div>
                <label className="block text-[10px] font-mono text-slate-400 mb-1">Volume Confirmation</label>
                <button
                  type="button"
                  onClick={() => setVolumeFilterEnabled(!volumeFilterEnabled)}
                  className={`w-full py-1.5 px-3 rounded text-xs font-mono font-semibold transition-colors border ${
                    volumeFilterEnabled
                      ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
                      : 'bg-slate-800 text-slate-400 border-white/[0.1]'
                  }`}
                >
                  {volumeFilterEnabled ? 'Active (SMA)' : 'Off'}
                </button>
              </div>

              <div>
                <label className="block text-[10px] font-mono text-slate-400 mb-1">Volume SMA Period</label>
                <input
                  type="number"
                  min="2"
                  max="100"
                  value={volumeMaPeriod}
                  onChange={(e) => setVolumeMaPeriod(Number(e.target.value))}
                  className="w-full bg-[#161D2B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white font-mono"
                />
              </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {comparisonResults.length >= 2 && (
        <div className="bg-[#0B0F17] border border-violet-400/20 rounded-xl p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-white">Triple EMA Strategy Comparison ({comparisonResults.length} presets)</h3>
            <p className="text-xs text-slate-400 mt-1">Same symbol, candle interval, dates, starting capital, fees and slippage. These are historical simulations, not profit guarantees.</p>
          </div>
          <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-[#0F1420] text-slate-400"><tr><th className="p-3">Preset</th><th className="p-3 text-right">Net P&L</th><th className="p-3 text-right">Return</th><th className="p-3 text-right">Trades</th><th className="p-3 text-right">Win Rate</th><th className="p-3 text-right">Max Drawdown</th><th className="p-3 text-right">Profit Factor</th></tr></thead>
              <tbody>{comparisonResults.map((item, index) => { const preset = COMPARISON_PRESETS.filter((p) => selectedComparisonPresets.includes(p.id))[index]; return <tr key={item.backtest_id} className="border-t border-white/[0.06]"><td className="p-3 text-white">{preset?.label ?? `EMA preset ${index + 1}`}</td><td className={`p-3 text-right ${item.metrics.net_profit >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{item.metrics.net_profit >= 0 ? '+' : ''}${item.metrics.net_profit.toFixed(2)}</td><td className={`p-3 text-right ${item.metrics.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{item.metrics.net_return_pct.toFixed(2)}%</td><td className="p-3 text-right text-slate-200">{item.metrics.total_trades}</td><td className="p-3 text-right text-slate-200">{item.metrics.win_rate_pct.toFixed(1)}%</td><td className="p-3 text-right text-rose-300">-{item.metrics.max_drawdown_pct.toFixed(2)}%</td><td className="p-3 text-right text-slate-200">{item.metrics.profit_factor == null ? 'N/A' : item.metrics.profit_factor.toFixed(2)}</td></tr>; })}</tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500">The equity chart below shows the first selected preset. Compare the table metrics first, then run an individual backtest for any preset whose full equity curve you want to inspect.</p>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start gap-3 text-rose-300 text-xs">
          <AlertTriangle className="w-5 h-5 shrink-0 text-rose-400 mt-0.5" />
          <div className="space-y-1">
            <span className="font-semibold font-mono">Backtest Execution Error:</span>
            <p className="text-rose-200/90 leading-relaxed">{error}</p>
          </div>
        </div>
      )}

      {/* Empty State before running */}
      {!result && !isRunning && !error && (
        <div className="border border-white/[0.07] border-dashed rounded-xl p-12 text-center bg-[#0B0F17]/40 space-y-3">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 mb-2">
            <Layers className="w-6 h-6" />
          </div>
          <h3 className="text-sm font-semibold text-white">No Simulation Results Yet</h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
            Select your cryptocurrency symbol, interval, lookback period, and click{' '}
            <strong className="text-cyan-400 font-medium">"Run Backtest"</strong> to fetch real Delta Exchange
            historical candles and execute the chronological simulation.
          </p>
        </div>
      )}

      {/* Simulation Running Progress Skeleton */}
      {isRunning && (
        <div className="border border-white/[0.07] rounded-xl p-12 text-center bg-[#0B0F17] space-y-4">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 animate-pulse">
            <RotateCcw className="w-6 h-6 animate-spin text-cyan-400" />
          </div>
          <div className="space-y-1.5">
            <h3 className="text-sm font-semibold text-white">Fetching Delta Exchange Historical Candles</h3>
            <p className="text-xs text-slate-400 font-mono">
              Evaluating completed {resolution} bars for {symbol} with {feePercent}% fees & {slippagePercent}% slippage...
            </p>
          </div>
        </div>
      )}

      {/* Results View */}
      {result && !isRunning && (
        <div className="space-y-6 animate-in fade-in duration-300">
          {/* Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {/* 1. Net Profit */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Net P&L ($)
              </span>
              <div
                className={`text-lg font-bold font-mono tracking-tight ${
                  result.metrics.net_profit >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {result.metrics.net_profit >= 0 ? '+' : ''}${result.metrics.net_profit.toLocaleString()}
              </div>
              <span
                className={`text-[11px] font-mono font-medium ${
                  result.metrics.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {result.metrics.net_return_pct >= 0 ? '+' : ''}
                {result.metrics.net_return_pct.toFixed(2)}%
              </span>
            </div>

            {/* 2. Win Rate */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Win Rate
              </span>
              <div className="text-lg font-bold font-mono text-white tracking-tight">
                {result.metrics.win_rate_pct.toFixed(1)}%
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                {result.metrics.winning_trades}W / {result.metrics.losing_trades}L ({result.metrics.total_trades} total)
              </span>
            </div>

            {/* 3. Profit Factor */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Profit Factor
              </span>
              <div className="text-lg font-bold font-mono text-white tracking-tight">
                {result.metrics.profit_factor !== null ? result.metrics.profit_factor.toFixed(2) : 'N/A'}
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                Gross: ${result.metrics.gross_profit.toFixed(0)} / ${result.metrics.gross_loss.toFixed(0)}
              </span>
            </div>

            {/* 4. Max Drawdown */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Max Drawdown
              </span>
              <div className="text-lg font-bold font-mono text-rose-400 tracking-tight">
                -{result.metrics.max_drawdown_pct.toFixed(2)}%
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                -${result.metrics.max_drawdown_dollars.toLocaleString()}
              </span>
            </div>

            {/* 5. Final Equity */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Final Equity
              </span>
              <div className="text-lg font-bold font-mono text-white tracking-tight">
                ${result.metrics.final_equity.toLocaleString()}
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                From ${result.metrics.initial_capital.toLocaleString()}
              </span>
            </div>

            {/* 6. Benchmark Comparison */}
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-4">
              <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Buy & Hold Return
              </span>
              <div
                className={`text-lg font-bold font-mono tracking-tight ${
                  result.metrics.buy_and_hold_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {result.metrics.buy_and_hold_return_pct >= 0 ? '+' : ''}
                {result.metrics.buy_and_hold_return_pct.toFixed(2)}%
              </div>
              <span className="text-[11px] font-mono text-slate-400">
                Fees: ${result.metrics.total_fees_paid.toFixed(2)}
              </span>
            </div>
          </div>

          {/* Assumptions Notice */}
          <div className="p-3.5 rounded-lg bg-[#0E131E] border border-white/[0.07] flex items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-2 text-slate-300">
              <Info className="w-4 h-4 shrink-0 text-cyan-400" />
              <span>
                <strong className="text-white font-mono">Assumptions: </strong>
                {result.assumptions_note}
              </span>
            </div>
            <span className="text-[11px] font-mono text-slate-400 shrink-0">
              Bars: {result.metrics.total_bars_analyzed.toLocaleString()} | Exposure: {result.metrics.market_exposure_pct}%
            </span>
          </div>

          {/* Equity Curve & Underwater Chart Card */}
          {chartData && (
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-5 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider font-mono">
                    Portfolio Equity Curve ($)
                  </h3>
                  <span className="text-[11px] text-slate-400">
                    Chronological progression of capital (Initial: ${result.metrics.initial_capital.toLocaleString()} ➔ Final: ${result.metrics.final_equity.toLocaleString()})
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-mono text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-0.5 bg-cyan-400 inline-block" />
                    <span>Portfolio Equity</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-0.5 bg-slate-600 border-b border-dashed border-slate-400 inline-block" />
                    <span>Initial Capital</span>
                  </div>
                </div>
              </div>

              {/* Equity Chart SVG */}
              <div className="w-full overflow-hidden bg-[#070A0F] rounded-lg border border-white/[0.05] p-2">
                <svg
                  viewBox={`0 0 ${chartData.width} ${chartData.height}`}
                  className="w-full h-56 overflow-visible"
                  preserveAspectRatio="none"
                >
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={result.metrics.net_return_pct >= 0 ? '#10b981' : '#f43f5e'} stopOpacity="0.25" />
                      <stop offset="100%" stopColor={result.metrics.net_return_pct >= 0 ? '#10b981' : '#f43f5e'} stopOpacity="0.0" />
                    </linearGradient>
                  </defs>

                  {/* Horizontal Baseline (Initial Capital) */}
                  <line
                    x1="20"
                    y1={chartData.baselineY}
                    x2={chartData.width - 20}
                    y2={chartData.baselineY}
                    stroke="#475569"
                    strokeDasharray="4 4"
                    strokeWidth="1"
                  />

                  {/* Gradient Area Fill */}
                  <path d={chartData.areaD} fill="url(#equityGradient)" />

                  {/* Line Stroke */}
                  <path
                    d={chartData.pathD}
                    fill="none"
                    stroke={result.metrics.net_return_pct >= 0 ? '#34d399' : '#fb7185'}
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* Drawdown Percentage Underwater Chart */}
              <div className="pt-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">
                    Drawdown (% Underwater)
                  </span>
                  <span className="text-[10px] font-mono text-rose-400">
                    Max: -{result.metrics.max_drawdown_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="w-full overflow-hidden bg-[#070A0F] rounded border border-white/[0.05] p-1">
                  <svg
                    viewBox={`0 0 ${chartData.width} ${chartData.ddHeight}`}
                    className="w-full h-16 overflow-visible"
                    preserveAspectRatio="none"
                  >
                    <defs>
                      <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.0" />
                        <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.3" />
                      </linearGradient>
                    </defs>
                    <path d={chartData.ddAreaD} fill="url(#ddGradient)" />
                    <path
                      d={chartData.ddPathD}
                      fill="none"
                      stroke="#f43f5e"
                      strokeWidth="1.2"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
              </div>
            </div>
          )}

          {/* Trade History Table Card */}
          <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <h3 className="text-xs font-semibold text-white uppercase tracking-wider font-mono">
                  Closed Trade Log ({result.trades.length} Trades)
                </h3>
                <span className="text-[11px] text-slate-400">
                  Detailed chronological audit of simulated positions, execution prices, and fees.
                </span>
              </div>

              {/* Trade Filter Pills */}
              <div className="flex items-center gap-1 bg-[#121824] p-1 rounded-lg border border-white/[0.08]">
                {[
                  { id: 'ALL', label: `All (${result.trades.length})` },
                  { id: 'WIN', label: `Wins (${result.metrics.winning_trades})` },
                  { id: 'LOSS', label: `Losses (${result.metrics.losing_trades})` },
                ].map((f) => (
                  <button
                    key={f.id}
                    onClick={() => setTradeFilter(f.id as any)}
                    className={`px-2.5 py-1 text-[11px] font-mono rounded transition-colors ${
                      tradeFilter === f.id
                        ? 'bg-cyan-500/20 text-cyan-400 font-semibold border border-cyan-500/30'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Table */}
            {filteredTrades.length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500 font-mono">
                No trades match the selected filter.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-[#0F1420] text-slate-400 border-b border-white/[0.08] text-[10px] uppercase tracking-wider">
                    <tr>
                      <th className="py-2.5 px-3">#</th>
                      <th className="py-2.5 px-3">Side</th>
                      <th className="py-2.5 px-3">Entry Time</th>
                      <th className="py-2.5 px-3 text-right">Entry Price</th>
                      <th className="py-2.5 px-3">Exit Time</th>
                      <th className="py-2.5 px-3 text-right">Exit Price</th>
                      <th className="py-2.5 px-3 text-right">Duration</th>
                      <th className="py-2.5 px-3 text-right">Fees</th>
                      <th className="py-2.5 px-3 text-right">Net P&L ($)</th>
                      <th className="py-2.5 px-3 text-right">Return %</th>
                      <th className="py-2.5 px-3 text-center">Exit Reason</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {filteredTrades.map((t) => {
                      const isProfit = t.net_pnl > 0;
                      const durationHours = (t.duration_seconds / 3600).toFixed(1);

                      return (
                        <tr key={t.trade_id} className="hover:bg-white/[0.02] transition-colors">
                          <td className="py-2.5 px-3 text-slate-400">{t.trade_id}</td>
                          <td className="py-2.5 px-3">
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
                              {t.side}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-300">{formatTs(t.entry_time)}</td>
                          <td className="py-2.5 px-3 text-right text-white">${t.entry_price.toLocaleString()}</td>
                          <td className="py-2.5 px-3 text-slate-300">{formatTs(t.exit_time)}</td>
                          <td className="py-2.5 px-3 text-right text-white">${t.exit_price.toLocaleString()}</td>
                          <td className="py-2.5 px-3 text-right text-slate-400">{durationHours}h</td>
                          <td className="py-2.5 px-3 text-right text-slate-400">${t.total_fees.toFixed(2)}</td>
                          <td
                            className={`py-2.5 px-3 text-right font-semibold ${
                              isProfit ? 'text-emerald-400' : 'text-rose-400'
                            }`}
                          >
                            {isProfit ? '+' : ''}${t.net_pnl.toFixed(2)}
                          </td>
                          <td
                            className={`py-2.5 px-3 text-right font-semibold ${
                              isProfit ? 'text-emerald-400' : 'text-rose-400'
                            }`}
                          >
                            {isProfit ? '+' : ''}{t.return_pct.toFixed(2)}%
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[9px] uppercase font-mono ${
                                t.exit_reason === 'SELL_SIGNAL'
                                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                  : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                              }`}
                            >
                              {t.exit_reason}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Legal Disclaimer Box */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-white/[0.05] text-[11px] text-slate-500 space-y-1">
            <span className="font-semibold text-slate-400 block font-mono">Regulatory & Analytical Disclaimer</span>
            <p className="leading-relaxed">{result.disclaimer}</p>
          </div>
        </div>
      )}
    </div>
  );
};
