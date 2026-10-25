import React, { useState, useMemo } from 'react';
import {
  FlaskConical,
  Play,
  RotateCcw,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  Sliders,
  Layers,
  ArrowRight,
  ShieldAlert,
  Info,
  Calendar,
  Sparkles,
  ChevronDown,
  ChevronUp,
  BarChart2,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { runEvaluation } from '../services/api';
import type {
  EvaluationRequest,
  EvaluationResultData,
  EvaluatedParameterSetData,
  ParameterSearchSpace,
  EquityPointData,
} from '../types/market';

interface StrategyLabViewProps {
  initialSymbol?: string;
  onSelectSymbol?: (symbol: string) => void;
}

const POPULAR_SYMBOLS = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'XRPUSD', 'DOGEUSD', 'AVAXUSD', 'BNBUSD'];

const RESOLUTIONS = [
  { id: '15m', label: '15m' },
  { id: '30m', label: '30m' },
  { id: '1h', label: '1 Hour' },
  { id: '4h', label: '4 Hours' },
  { id: '1d', label: '1 Day' },
];

const PRESETS = [
  {
    name: 'Quick Grid (9 Sets)',
    desc: 'Fast EMAs [5, 9, 13] vs Slow EMAs [21, 34, 55]',
    space: {
      fast_periods: [5, 9, 13],
      slow_periods: [21, 34, 55],
      rsi_periods: [14],
      rsi_buy_mins: [40.0],
      rsi_sell_maxs: [60.0],
      volume_confirmation: [false],
    },
  },
  {
    name: 'Standard Walk-Forward (36 Sets)',
    desc: 'Moving averages and RSI momentum threshold sensitivity',
    space: {
      fast_periods: [7, 9, 13],
      slow_periods: [21, 34, 50],
      rsi_periods: [14],
      rsi_buy_mins: [35.0, 45.0],
      rsi_sell_maxs: [55.0, 65.0],
      volume_confirmation: [false],
    },
  },
  {
    name: 'Volume & Regime Check (36 Sets)',
    desc: 'Tests trend confirmation with volume filter enabled/disabled',
    space: {
      fast_periods: [5, 9, 13],
      slow_periods: [21, 34, 55],
      rsi_periods: [14, 21],
      rsi_buy_mins: [40.0],
      rsi_sell_maxs: [60.0],
      volume_confirmation: [false, true],
    },
  },
];

export const StrategyLabView: React.FC<StrategyLabViewProps> = ({
  initialSymbol = 'BTCUSD',
  onSelectSymbol,
}) => {
  // Evaluation Job Configuration
  const [symbol, setSymbol] = useState<string>(initialSymbol);
  const [resolution, setResolution] = useState<string>('1h');
  const [rangeDays, setRangeDays] = useState<number>(45);
  const [splitRatio, setSplitRatio] = useState<number>(0.70);
  const [rankingMetric, setRankingMetric] = useState<'net_return_pct' | 'profit_factor' | 'win_rate_pct'>('net_return_pct');
  const [initialCapital, setInitialCapital] = useState<number>(10000);
  const [feePercent, setFeePercent] = useState<number>(0.05);
  const [slippagePercent, setSlippagePercent] = useState<number>(0.05);
  const [executionMode, setExecutionMode] = useState<'next_open' | 'current_close'>('next_open');

  // Discrete parameter search space strings (comma-separated for user convenience)
  const [fastStr, setFastStr] = useState<string>('5, 9, 13');
  const [slowStr, setSlowStr] = useState<string>('21, 34, 55');
  const [rsiStr, setRsiStr] = useState<string>('14');
  const [buyMinStr, setBuyMinStr] = useState<string>('40');
  const [sellMaxStr, setSellMaxStr] = useState<string>('60');
  const [volChoice, setVolChoice] = useState<'false' | 'true' | 'both'>('false');

  // UI States
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EvaluationResultData | null>(null);
  const [selectedRank, setSelectedRank] = useState<number>(1);
  const [sortField, setSortField] = useState<keyof EvaluatedParameterSetData | 'train_ret' | 'test_ret' | 'degradation'>('rank');
  const [sortAsc, setSortAsc] = useState<boolean>(true);
  const [showConfig, setShowConfig] = useState<boolean>(true);

  // Parse comma-separated numbers into arrays
  const parsedSearchSpace = useMemo<ParameterSearchSpace>(() => {
    const parseNums = (str: string) =>
      str
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .map(Number)
        .filter((n) => !isNaN(n));

    const fast = parseNums(fastStr);
    const slow = parseNums(slowStr);
    const rsi = parseNums(rsiStr);
    const buyMin = parseNums(buyMinStr);
    const sellMax = parseNums(sellMaxStr);

    let vols = [false];
    if (volChoice === 'true') vols = [true];
    else if (volChoice === 'both') vols = [false, true];

    return {
      fast_periods: fast.length > 0 ? fast : [9],
      slow_periods: slow.length > 0 ? slow : [21],
      rsi_periods: rsi.length > 0 ? rsi : [14],
      rsi_buy_mins: buyMin.length > 0 ? buyMin : [40.0],
      rsi_sell_maxs: sellMax.length > 0 ? sellMax : [60.0],
      volume_confirmation: vols,
    };
  }, [fastStr, slowStr, rsiStr, buyMinStr, sellMaxStr, volChoice]);

  // Dynamic combination counter and validation
  const combinationStats = useMemo(() => {
    let valid = 0;
    let filtered = 0;
    const { fast_periods, slow_periods, rsi_periods, rsi_buy_mins, rsi_sell_maxs, volume_confirmation } =
      parsedSearchSpace;

    for (const f of fast_periods) {
      for (const s of slow_periods) {
        for (const r of rsi_periods) {
          for (const bm of rsi_buy_mins) {
            for (const sm of rsi_sell_maxs) {
              for (const v of volume_confirmation) {
                if (f >= s || bm > sm) {
                  filtered++;
                } else {
                  valid++;
                }
              }
            }
          }
        }
      }
    }
    return { valid, filtered, total: valid + filtered, isOverLimit: valid > 100 };
  }, [parsedSearchSpace]);

  // Apply a preset configuration
  const handleApplyPreset = (preset: typeof PRESETS[0]) => {
    setFastStr(preset.space.fast_periods.join(', '));
    setSlowStr(preset.space.slow_periods.join(', '));
    setRsiStr(preset.space.rsi_periods.join(', '));
    setBuyMinStr(preset.space.rsi_buy_mins.join(', '));
    setSellMaxStr(preset.space.rsi_sell_maxs.join(', '));
    if (preset.space.volume_confirmation.length === 2) setVolChoice('both');
    else if (preset.space.volume_confirmation[0]) setVolChoice('true');
    else setVolChoice('false');
  };

  // Run the walk-forward evaluation job
  const handleRunEvaluation = async () => {
    if (combinationStats.valid === 0) {
      setError('No valid parameter combinations. Ensure each fast EMA is strictly less than slow EMA.');
      return;
    }
    if (combinationStats.isOverLimit) {
      setError(`Grid size (${combinationStats.valid}) exceeds the 100 combination ceiling. Please narrow your search space.`);
      return;
    }

    setIsRunning(true);
    setError(null);

    const now = Math.floor(Date.now() / 1000);
    const startTime = now - rangeDays * 86400;

    const req: EvaluationRequest = {
      symbol: symbol.trim().toUpperCase(),
      resolution,
      start_time: startTime,
      end_time: now,
      split_ratio: Number(splitRatio),
      initial_capital: Number(initialCapital),
      fee_rate: Number(feePercent) / 100.0,
      slippage_rate: Number(slippagePercent) / 100.0,
      execution_mode: executionMode,
      max_combinations: 100,
      search_space: parsedSearchSpace,
      ranking_metric: rankingMetric,
    };

    try {
      const res = await runEvaluation(req);
      setResult(res);
      setSelectedRank(1);
      // Auto-collapse configuration panel to focus on analytics
      setShowConfig(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRunning(false);
    }
  };

  // Selected parameter set for detailed inspection
  const selectedParamSet = useMemo<EvaluatedParameterSetData | null>(() => {
    if (!result || !result.parameter_sets.length) return null;
    return result.parameter_sets.find((p) => p.rank === selectedRank) || result.parameter_sets[0];
  }, [result, selectedRank]);

  // Sorted parameter comparison table
  const sortedParameterSets = useMemo(() => {
    if (!result) return [];
    const sets = [...result.parameter_sets];

    sets.sort((a, b) => {
      let valA: number = 0;
      let valB: number = 0;

      if (sortField === 'rank') {
        valA = a.rank;
        valB = b.rank;
      } else if (sortField === 'train_ret') {
        valA = a.in_sample.net_return_pct;
        valB = b.in_sample.net_return_pct;
      } else if (sortField === 'test_ret') {
        valA = a.out_of_sample.net_return_pct;
        valB = b.out_of_sample.net_return_pct;
      } else if (sortField === 'degradation') {
        valA = a.return_degradation_pct;
        valB = b.return_degradation_pct;
      }

      return sortAsc ? valA - valB : valB - valA;
    });

    return sets;
  }, [result, sortField, sortAsc]);

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(field === 'rank');
    }
  };

  // Dual Equity Curve SVG Chart Builder
  const chartPoints = useMemo(() => {
    if (!result || !result.winner_train_equity_curve || !result.winner_test_equity_curve) {
      return null;
    }

    const trainCurve = result.winner_train_equity_curve;
    const testCurve = result.winner_test_equity_curve;

    if (!trainCurve.length || !testCurve.length) return null;

    // Combined points for full walk-forward timeline
    // Note: Out-of-sample started fresh with initial capital, so we display both
    const trainMin = Math.min(...trainCurve.map((p) => p.equity));
    const trainMax = Math.max(...trainCurve.map((p) => p.equity));
    const testMin = Math.min(...testCurve.map((p) => p.equity));
    const testMax = Math.max(...testCurve.map((p) => p.equity));

    const overallMin = Math.min(trainMin, testMin) * 0.98;
    const overallMax = Math.max(trainMax, testMax) * 1.02;

    return {
      trainCurve,
      testCurve,
      min: overallMin,
      max: overallMax,
    };
  }, [result]);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500/20 to-cyan-500/20 border border-indigo-500/30 text-indigo-400">
              <FlaskConical className="w-4 h-4 text-cyan-400" />
            </div>
            <h1 className="text-xl font-bold text-white tracking-tight">
              Strategy Lab <span className="text-cyan-400 font-mono text-sm ml-2 font-normal">Robustness & Walk-Forward Optimizer</span>
            </h1>
          </div>
          <p className="text-xs text-slate-400 font-mono mt-1">
            Evaluate parameter stability across chronological In-Sample (Train) and Out-of-Sample (Test) periods to detect overfitting before risking capital.
          </p>
        </div>

        {/* Quick controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-medium bg-[#121824] hover:bg-[#1A2234] border border-white/10 text-slate-300 transition-colors"
          >
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            <span>{showConfig ? 'Collapse Setup' : 'Configure Grid'}</span>
            {showConfig ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Configuration Card */}
      {showConfig && (
        <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-5 space-y-5 shadow-xl">
          {/* Preset Buttons */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                Quick Preset Parameter Grids
              </label>
              <span className="text-[11px] text-slate-500 font-mono">1-Click Population</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  onClick={() => handleApplyPreset(p)}
                  className="flex flex-col text-left p-3 rounded-lg bg-[#121824] hover:bg-[#1A2234] border border-white/[0.08] hover:border-cyan-500/40 transition-all group"
                >
                  <span className="text-xs font-semibold text-white group-hover:text-cyan-400 transition-colors">
                    {p.name}
                  </span>
                  <span className="text-[11px] text-slate-400 font-mono mt-1 leading-tight">{p.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Row 1: Market & Period Setup */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-2 border-t border-white/[0.05]">
            {/* Symbol */}
            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1.5">
                Pair Symbol
              </label>
              <div className="flex items-center gap-1 mb-1.5">
                {POPULAR_SYMBOLS.slice(0, 4).map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setSymbol(s);
                      if (onSelectSymbol) onSelectSymbol(s);
                    }}
                    className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors ${
                      symbol === s
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                        : 'bg-[#121824] text-slate-400 hover:text-white'
                    }`}
                  >
                    {s.replace('USD', '')}
                  </button>
                ))}
              </div>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                className="w-full bg-[#121824] border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-cyan-500"
                placeholder="e.g. BTCUSD"
              />
            </div>

            {/* Resolution */}
            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1.5">
                Candle Interval
              </label>
              <div className="grid grid-cols-5 gap-1 mb-1.5">
                {RESOLUTIONS.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setResolution(r.id)}
                    className={`py-1 rounded text-xs font-mono font-medium transition-colors ${
                      resolution === r.id
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                        : 'bg-[#121824] text-slate-400 hover:text-white'
                    }`}
                  >
                    {r.id}
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-slate-500 font-mono">1h interval recommended for stable swings</span>
            </div>

            {/* History Range */}
            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1.5">
                Historical Sample
              </label>
              <div className="grid grid-cols-4 gap-1 mb-1.5">
                {[30, 45, 60, 90].map((days) => (
                  <button
                    key={days}
                    onClick={() => setRangeDays(days)}
                    className={`py-1 rounded text-xs font-mono font-medium transition-colors ${
                      rangeDays === days
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                        : 'bg-[#121824] text-slate-400 hover:text-white'
                    }`}
                  >
                    {days}D
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-slate-500 font-mono">45D provides ~1080 hourly candles</span>
            </div>

            {/* Chronological Train/Test Split */}
            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1.5">
                Train / Test Split
              </label>
              <div className="grid grid-cols-3 gap-1 mb-1.5">
                {[
                  { ratio: 0.60, label: '60 / 40' },
                  { ratio: 0.70, label: '70 / 30' },
                  { ratio: 0.80, label: '80 / 20' },
                ].map((s) => (
                  <button
                    key={s.ratio}
                    onClick={() => setSplitRatio(s.ratio)}
                    className={`py-1 rounded text-xs font-mono font-medium transition-colors ${
                      splitRatio === s.ratio
                        ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 font-bold'
                        : 'bg-[#121824] text-slate-400 hover:text-white'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-indigo-400/90 font-mono">
                {Math.round(splitRatio * 100)}% In-Sample / {Math.round((1 - splitRatio) * 100)}% Out-of-Sample
              </span>
            </div>
          </div>

          {/* Row 2: Search Grid Configuration */}
          <div className="pt-2 border-t border-white/[0.05]">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                Discrete Parameter Search Space (Comma-Separated Grid)
              </label>
              <span className="text-[11px] text-slate-500 font-mono">
                Auto-validates: Fast EMA must strictly precede Slow EMA
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {/* Fast EMAs */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  Fast EMA Periods
                </label>
                <input
                  type="text"
                  value={fastStr}
                  onChange={(e) => setFastStr(e.target.value)}
                  className="w-full bg-[#080A0F] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                  placeholder="e.g. 5, 9, 13"
                />
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Integers &gt;= 2</span>
              </div>

              {/* Slow EMAs */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  Slow EMA Periods
                </label>
                <input
                  type="text"
                  value={slowStr}
                  onChange={(e) => setSlowStr(e.target.value)}
                  className="w-full bg-[#080A0F] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                  placeholder="e.g. 21, 34, 55"
                />
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Must be &gt; Fast</span>
              </div>

              {/* RSI Periods */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  RSI Lookbacks
                </label>
                <input
                  type="text"
                  value={rsiStr}
                  onChange={(e) => setRsiStr(e.target.value)}
                  className="w-full bg-[#080A0F] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                  placeholder="e.g. 14, 21"
                />
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Default: 14</span>
              </div>

              {/* RSI Buy Min */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  RSI Buy Min (0..100)
                </label>
                <input
                  type="text"
                  value={buyMinStr}
                  onChange={(e) => setBuyMinStr(e.target.value)}
                  className="w-full bg-[#080A0F] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                  placeholder="e.g. 35, 40, 45"
                />
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Momentum floor</span>
              </div>

              {/* RSI Sell Max */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  RSI Sell Max (0..100)
                </label>
                <input
                  type="text"
                  value={sellMaxStr}
                  onChange={(e) => setSellMaxStr(e.target.value)}
                  className="w-full bg-[#080A0F] border border-white/10 rounded px-2.5 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                  placeholder="e.g. 55, 60, 65"
                />
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Momentum ceiling</span>
              </div>

              {/* Volume Filter */}
              <div className="bg-[#121824] p-3 rounded-lg border border-white/[0.05]">
                <label className="block text-[11px] font-mono text-cyan-300 mb-1 font-semibold">
                  Volume Confirmation
                </label>
                <div className="grid grid-cols-3 gap-1">
                  {[
                    { id: 'false', label: 'Off' },
                    { id: 'true', label: 'On' },
                    { id: 'both', label: 'Both' },
                  ].map((v) => (
                    <button
                      key={v.id}
                      onClick={() => setVolChoice(v.id as any)}
                      className={`py-1 rounded text-[11px] font-mono transition-colors ${
                        volChoice === v.id
                          ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                          : 'bg-[#080A0F] text-slate-400 hover:text-white'
                      }`}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>
                <span className="text-[10px] text-slate-500 font-mono block mt-1">Vol &gt; 20-SMA</span>
              </div>
            </div>
          </div>

          {/* Row 3: Live Combination Counter & Execution Actions */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-3 border-t border-white/[0.05]">
            <div className="flex items-center gap-3">
              <div
                className={`px-3 py-1.5 rounded-lg border text-xs font-mono flex items-center gap-2 ${
                  combinationStats.isOverLimit
                    ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                    : combinationStats.valid > 60
                    ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                    : 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                }`}
              >
                <Zap className="w-4 h-4 shrink-0" />
                <span>
                  Valid Grid Size:{' '}
                  <strong>
                    {combinationStats.valid} / 100 max
                  </strong>
                </span>
                {combinationStats.filtered > 0 && (
                  <span className="text-[11px] text-slate-400 border-l border-white/10 pl-2">
                    ({combinationStats.filtered} invalid pruned)
                  </span>
                )}
              </div>

              {/* Ranking Metric selector */}
              <div className="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
                <span>Rank Winner By:</span>
                <select
                  value={rankingMetric}
                  onChange={(e) => setRankingMetric(e.target.value as any)}
                  className="bg-[#121824] border border-white/10 text-white rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-cyan-500"
                >
                  <option value="net_return_pct">Net Return (%)</option>
                  <option value="profit_factor">Profit Factor</option>
                  <option value="win_rate_pct">Win Rate (%)</option>
                </select>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleRunEvaluation}
                disabled={isRunning || combinationStats.valid === 0 || combinationStats.isOverLimit}
                className={`flex items-center gap-2 px-5 py-2 rounded-lg font-mono text-xs font-bold transition-all shadow-lg ${
                  isRunning || combinationStats.valid === 0 || combinationStats.isOverLimit
                    ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-white/5'
                    : 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white shadow-cyan-500/20 active:scale-95'
                }`}
              >
                {isRunning ? (
                  <>
                    <RotateCcw className="w-4 h-4 animate-spin text-white" />
                    <span>Evaluating Grid in Memory...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-white" />
                    <span>Run Walk-Forward Optimization</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>
      )}

      {/* Execution Results View */}
      {result && (
        <div className="space-y-6">
          {/* Overfitting & Robustness Alert Banner */}
          {result.selected_winner_is_overfit ? (
            <div className="p-4 rounded-xl bg-gradient-to-r from-amber-500/15 via-rose-500/10 to-amber-500/15 border border-amber-500/30 text-amber-200 text-xs shadow-lg space-y-1">
              <div className="flex items-center gap-2 font-bold text-sm text-amber-300">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                <span>Overfitting Alert: In-Sample Strategy Degraded On Unseen Data</span>
              </div>
              <p className="font-mono text-slate-300 leading-relaxed pl-6">
                {result.selected_winner_overfit_warning ||
                  'The parameter combination selected using training data performed significantly worse on the separate out-of-sample test period. This strongly indicates curve-fitting to historical noise rather than genuine market edge.'}
              </p>
              <div className="flex items-center gap-4 pl-6 pt-1 text-[11px] font-mono text-amber-400/80">
                <span>In-Sample Win Rate: {result.parameter_sets[0].in_sample.win_rate_pct.toFixed(1)}%</span>
                <span>→</span>
                <span>Out-of-Sample Win Rate: {result.parameter_sets[0].out_of_sample.win_rate_pct.toFixed(1)}%</span>
                <span className="text-slate-400">|</span>
                <span>Return Drop: {result.parameter_sets[0].return_degradation_pct.toFixed(1)}%</span>
              </div>
            </div>
          ) : (
            <div className="p-4 rounded-xl bg-gradient-to-r from-emerald-500/15 via-cyan-500/10 to-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-xs shadow-lg space-y-1">
              <div className="flex items-center gap-2 font-bold text-sm text-emerald-300">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Out-of-Sample Validated: Parameter Set Maintained Robustness</span>
              </div>
              <p className="font-mono text-slate-300 leading-relaxed pl-6">
                The top-ranked training strategy retained stable performance on unseen out-of-sample data without severe degradation or drawdown explosion.
              </p>
            </div>
          )}

          {/* Deep-Dive Card for Selected Strategy */}
          {selectedParamSet && (
            <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl p-5 space-y-5 shadow-xl">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 font-mono text-xs font-bold">
                      Rank #{selectedParamSet.rank}
                    </span>
                    <h2 className="text-base font-bold text-white tracking-tight font-sans">
                      {selectedParamSet.params_label}
                    </h2>
                  </div>
                  <span className="text-[11px] text-slate-400 font-mono mt-0.5 block">
                    Next-Candle-Open Execution • Taker Fee: {(feePercent).toFixed(2)}% • Slippage: {(slippagePercent).toFixed(2)}%
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <span className="text-[10px] text-slate-400 uppercase font-mono block">Robustness Ratio</span>
                    <span
                      className={`text-sm font-bold font-mono ${
                        selectedParamSet.robustness_ratio === null
                          ? 'text-slate-400'
                          : selectedParamSet.robustness_ratio >= 0.7
                          ? 'text-emerald-400'
                          : selectedParamSet.robustness_ratio >= 0.3
                          ? 'text-amber-400'
                          : 'text-rose-400'
                      }`}
                    >
                      {selectedParamSet.robustness_ratio !== null ? `${selectedParamSet.robustness_ratio.toFixed(2)}x` : 'N/A'}
                    </span>
                  </div>

                  <div className="text-right border-l border-white/10 pl-3">
                    <span className="text-[10px] text-slate-400 uppercase font-mono block">Return Degradation</span>
                    <span
                      className={`text-sm font-bold font-mono ${
                        selectedParamSet.return_degradation_pct > 10
                          ? 'text-rose-400'
                          : selectedParamSet.return_degradation_pct > 0
                          ? 'text-amber-400'
                          : 'text-emerald-400'
                      }`}
                    >
                      {selectedParamSet.return_degradation_pct > 0 ? '-' : '+'}
                      {Math.abs(selectedParamSet.return_degradation_pct).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Side-by-Side Comparison: Training vs Out-of-Sample */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* 1. In-Sample (Training) Period */}
                <div className="bg-[#121824] rounded-xl p-4 border border-indigo-500/20 space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-indigo-400 animate-pulse" />
                      <span className="text-xs font-bold text-white font-mono uppercase tracking-wider">
                        In-Sample Training Period
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/30">
                      {selectedParamSet.in_sample.total_bars} Bars ({Math.round(result.split_ratio * 100)}%)
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Net Return</span>
                      <span
                        className={`text-sm font-bold font-mono ${
                          selectedParamSet.in_sample.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {selectedParamSet.in_sample.net_return_pct >= 0 ? '+' : ''}
                        {selectedParamSet.in_sample.net_return_pct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        ${selectedParamSet.in_sample.net_profit.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Max Drawdown</span>
                      <span className="text-sm font-bold font-mono text-rose-400">
                        -{selectedParamSet.in_sample.max_drawdown_pct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        ${selectedParamSet.in_sample.max_drawdown_dollars.toFixed(2)}
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Win Rate</span>
                      <span className="text-sm font-bold font-mono text-white">
                        {selectedParamSet.in_sample.win_rate_pct.toFixed(1)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        {selectedParamSet.in_sample.winning_trades}W / {selectedParamSet.in_sample.losing_trades}L
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Profit Factor</span>
                      <span className="text-sm font-bold font-mono text-white">
                        {selectedParamSet.in_sample.profit_factor !== null
                          ? selectedParamSet.in_sample.profit_factor.toFixed(2)
                          : 'N/A'}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        {selectedParamSet.in_sample.total_trades} trades
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-2 border-t border-white/[0.04]">
                    <span>Buy &amp; Hold: {selectedParamSet.in_sample.buy_and_hold_return_pct.toFixed(2)}%</span>
                    <span>Market Exposure: {selectedParamSet.in_sample.market_exposure_pct.toFixed(1)}%</span>
                    <span>Fees: ${selectedParamSet.in_sample.total_fees_paid.toFixed(2)}</span>
                  </div>
                </div>

                {/* 2. Out-of-Sample (Testing) Period */}
                <div
                  className={`rounded-xl p-4 border space-y-3 transition-colors ${
                    selectedParamSet.is_overfit
                      ? 'bg-rose-500/[0.04] border-rose-500/30'
                      : 'bg-emerald-500/[0.04] border-emerald-500/30'
                  }`}
                >
                  <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-2.5 h-2.5 rounded-full ${
                          selectedParamSet.is_overfit ? 'bg-rose-400' : 'bg-emerald-400'
                        } animate-pulse`}
                      />
                      <span className="text-xs font-bold text-white font-mono uppercase tracking-wider">
                        Out-of-Sample Unseen Testing
                      </span>
                    </div>
                    <span
                      className={`text-[11px] font-mono px-2 py-0.5 rounded border ${
                        selectedParamSet.is_overfit
                          ? 'text-rose-300 bg-rose-500/10 border-rose-500/30'
                          : 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                      }`}
                    >
                      {selectedParamSet.out_of_sample.total_bars} Bars ({Math.round((1 - result.split_ratio) * 100)}%)
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Net Return</span>
                      <span
                        className={`text-sm font-bold font-mono ${
                          selectedParamSet.out_of_sample.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {selectedParamSet.out_of_sample.net_return_pct >= 0 ? '+' : ''}
                        {selectedParamSet.out_of_sample.net_return_pct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        ${selectedParamSet.out_of_sample.net_profit.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Max Drawdown</span>
                      <span className="text-sm font-bold font-mono text-rose-400">
                        -{selectedParamSet.out_of_sample.max_drawdown_pct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        ${selectedParamSet.out_of_sample.max_drawdown_dollars.toFixed(2)}
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Win Rate</span>
                      <span className="text-sm font-bold font-mono text-white">
                        {selectedParamSet.out_of_sample.win_rate_pct.toFixed(1)}%
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        {selectedParamSet.out_of_sample.winning_trades}W / {selectedParamSet.out_of_sample.losing_trades}L
                      </span>
                    </div>

                    <div>
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">Profit Factor</span>
                      <span className="text-sm font-bold font-mono text-white">
                        {selectedParamSet.out_of_sample.profit_factor !== null
                          ? selectedParamSet.out_of_sample.profit_factor.toFixed(2)
                          : 'N/A'}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono block">
                        {selectedParamSet.out_of_sample.total_trades} trades
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-2 border-t border-white/[0.04]">
                    <span>Buy &amp; Hold: {selectedParamSet.out_of_sample.buy_and_hold_return_pct.toFixed(2)}%</span>
                    <span>Market Exposure: {selectedParamSet.out_of_sample.market_exposure_pct.toFixed(1)}%</span>
                    <span>Fees: ${selectedParamSet.out_of_sample.total_fees_paid.toFixed(2)}</span>
                  </div>
                </div>
              </div>

              {/* Dual Walk-Forward Equity Visualization */}
              {chartPoints && (
                <div className="pt-2 border-t border-white/[0.05]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                      <BarChart2 className="w-3.5 h-3.5 text-cyan-400" />
                      Walk-Forward Equity Trajectory (Training vs Out-of-Sample)
                    </span>
                    <div className="flex items-center gap-4 text-[11px] font-mono">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-0.5 bg-indigo-400 rounded-full" />
                        <span className="text-slate-300">In-Sample Equity</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`w-2.5 h-0.5 ${
                            result.selected_winner_is_overfit ? 'bg-rose-400' : 'bg-emerald-400'
                          } rounded-full`}
                        />
                        <span className="text-slate-300">Out-of-Sample Equity</span>
                      </div>
                    </div>
                  </div>

                  {/* SVG Chart */}
                  <div className="w-full h-44 bg-[#080A0F] rounded-lg border border-white/5 relative p-2 overflow-hidden flex items-end">
                    <svg className="w-full h-full overflow-visible" viewBox="0 0 1000 150" preserveAspectRatio="none">
                      {/* Midline / Starting Capital line */}
                      <line
                        x1="0"
                        y1="75"
                        x2="1000"
                        y2="75"
                        stroke="rgba(255,255,255,0.1)"
                        strokeDasharray="4 4"
                      />

                      {/* Partition line: Train / Test split vertical marker */}
                      <line
                        x1={result.split_ratio * 1000}
                        y1="0"
                        x2={result.split_ratio * 1000}
                        y2="150"
                        stroke="rgba(255,255,255,0.3)"
                        strokeWidth="1.5"
                        strokeDasharray="6 3"
                      />

                      {/* In-Sample Equity Polyline */}
                      {(() => {
                        const pts = chartPoints.trainCurve.map((p, i) => {
                          const x = (i / chartPoints.trainCurve.length) * (result.split_ratio * 1000);
                          const yRange = chartPoints.max - chartPoints.min || 1;
                          const y = 150 - ((p.equity - chartPoints.min) / yRange) * 140 - 5;
                          return `${x.toFixed(1)},${y.toFixed(1)}`;
                        });
                        return (
                          <polyline
                            fill="none"
                            stroke="#818CF8"
                            strokeWidth="2"
                            points={pts.join(' ')}
                          />
                        );
                      })()}

                      {/* Out-of-Sample Equity Polyline */}
                      {(() => {
                        const startX = result.split_ratio * 1000;
                        const width = 1000 - startX;
                        const pts = chartPoints.testCurve.map((p, i) => {
                          const x = startX + (i / chartPoints.testCurve.length) * width;
                          const yRange = chartPoints.max - chartPoints.min || 1;
                          const y = 150 - ((p.equity - chartPoints.min) / yRange) * 140 - 5;
                          return `${x.toFixed(1)},${y.toFixed(1)}`;
                        });
                        return (
                          <polyline
                            fill="none"
                            stroke={result.selected_winner_is_overfit ? '#F43F5E' : '#10B981'}
                            strokeWidth="2.5"
                            points={pts.join(' ')}
                          />
                        );
                      })()}
                    </svg>

                    {/* Split boundary label */}
                    <div
                      className="absolute top-2 font-mono text-[10px] text-slate-400 bg-black/60 px-1.5 py-0.5 rounded border border-white/10"
                      style={{ left: `${result.split_ratio * 100}%`, transform: 'translateX(-50%)' }}
                    >
                      Split: {new Date(result.test_start_time * 1000).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Sortable Parameter Sets Comparison Table */}
          <div className="bg-[#0B0F17] border border-white/[0.07] rounded-xl overflow-hidden shadow-xl">
            <div className="p-4 border-b border-white/[0.07] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
                  <Layers className="w-4 h-4 text-cyan-400" />
                  Parameter Comparison Grid ({result.total_combinations_evaluated} Combinations)
                </h3>
                <span className="text-[11px] text-slate-400 font-mono">
                  Ranked strictly by training performance. Click any row to inspect dual walk-forward metrics.
                </span>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="bg-[#121824] text-slate-400 border-b border-white/[0.07] select-none">
                    <th
                      onClick={() => toggleSort('rank')}
                      className="py-3 px-3 cursor-pointer hover:text-white"
                    >
                      Rank {sortField === 'rank' && (sortAsc ? '▲' : '▼')}
                    </th>
                    <th className="py-3 px-3">Parameters (EMA / RSI / Vol)</th>
                    <th
                      onClick={() => toggleSort('train_ret')}
                      className="py-3 px-3 cursor-pointer hover:text-white text-right"
                    >
                      Train Return % {sortField === 'train_ret' && (sortAsc ? '▲' : '▼')}
                    </th>
                    <th
                      onClick={() => toggleSort('test_ret')}
                      className="py-3 px-3 cursor-pointer hover:text-white text-right"
                    >
                      Test Return % {sortField === 'test_ret' && (sortAsc ? '▲' : '▼')}
                    </th>
                    <th
                      onClick={() => toggleSort('degradation')}
                      className="py-3 px-3 cursor-pointer hover:text-white text-right"
                    >
                      Degradation {sortField === 'degradation' && (sortAsc ? '▲' : '▼')}
                    </th>
                    <th className="py-3 px-3 text-right">Train DD</th>
                    <th className="py-3 px-3 text-right">Test DD</th>
                    <th className="py-3 px-3 text-right">Train Win %</th>
                    <th className="py-3 px-3 text-right">Test Win %</th>
                    <th className="py-3 px-3 text-right">Trades (Tr/Te)</th>
                    <th className="py-3 px-3 text-center">Robustness Status</th>
                    <th className="py-3 px-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {sortedParameterSets.map((p) => {
                    const isSelected = p.rank === selectedRank;
                    return (
                      <tr
                        key={p.rank}
                        onClick={() => setSelectedRank(p.rank)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-cyan-500/[0.08] text-white font-semibold'
                            : 'hover:bg-white/[0.02] text-slate-300'
                        }`}
                      >
                        <td className="py-2.5 px-3">
                          <span
                            className={`inline-flex items-center justify-center w-5 h-5 rounded text-[11px] font-bold ${
                              p.rank === 1
                                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                                : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {p.rank}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-slate-200">
                          {p.params_label}
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right font-bold ${
                            p.in_sample.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {p.in_sample.net_return_pct >= 0 ? '+' : ''}
                          {p.in_sample.net_return_pct.toFixed(1)}%
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right font-bold ${
                            p.out_of_sample.net_return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {p.out_of_sample.net_return_pct >= 0 ? '+' : ''}
                          {p.out_of_sample.net_return_pct.toFixed(1)}%
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right ${
                            p.return_degradation_pct > 10
                              ? 'text-rose-400 font-bold'
                              : p.return_degradation_pct > 0
                              ? 'text-amber-400'
                              : 'text-emerald-400'
                          }`}
                        >
                          {p.return_degradation_pct > 0 ? '-' : '+'}
                          {Math.abs(p.return_degradation_pct).toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-rose-400/90">
                          -{p.in_sample.max_drawdown_pct.toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-rose-400/90">
                          -{p.out_of_sample.max_drawdown_pct.toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-slate-300">
                          {p.in_sample.win_rate_pct.toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-slate-300">
                          {p.out_of_sample.win_rate_pct.toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-slate-400">
                          {p.in_sample.total_trades} / {p.out_of_sample.total_trades}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          {p.is_overfit ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-rose-500/10 text-rose-400 border border-rose-500/30">
                              <AlertTriangle className="w-3 h-3" /> Overfit
                            </span>
                          ) : p.out_of_sample.total_trades === 0 ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 border border-white/5">
                              Stagnant
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                              <CheckCircle2 className="w-3 h-3" /> Robust
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRank(p.rank);
                            }}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors ${
                              isSelected
                                ? 'bg-cyan-500 text-black font-bold'
                                : 'bg-[#121824] hover:bg-cyan-500/20 text-cyan-400'
                            }`}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Regulatory & Methodology Disclaimer */}
          <div className="p-4 rounded-xl bg-[#0B0F17] border border-white/[0.05] text-[11px] font-mono text-slate-400 leading-relaxed space-y-1">
            <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
              <span>TokenIQ Evaluation Methodology &amp; Risk Disclosure</span>
            </div>
            <p>
              Walk-forward optimization partitions historical data chronologically into in-sample (training) and out-of-sample (testing) segments.
              Strategy rankings and winner selection are derived exclusively from training period performance.
              Orders simulate next-candle-open fills with exchange taker fees (0.05%) and execution slippage (0.05%) applied on completed candles.
              Past hypothetical performance is not a guarantee of future live trading returns.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
