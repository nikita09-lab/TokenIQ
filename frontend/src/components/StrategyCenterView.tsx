import React, { useState } from 'react';
import { Activity, FlaskConical, LineChart, ShieldCheck } from 'lucide-react';
import { BacktestingView } from './BacktestingView';
import { StrategyLabView } from './StrategyLabView';

interface StrategyCenterViewProps {
  initialSymbol?: string;
  onSelectSymbol?: (symbol: string) => void;
}

type Mode = 'backtest' | 'validate';

export const StrategyCenterView: React.FC<StrategyCenterViewProps> = ({
  initialSymbol = 'BTCUSD',
  onSelectSymbol,
}) => {
  const [mode, setMode] = useState<Mode>('backtest');

  return (
    <div className="flex-1 min-w-0 overflow-y-auto bg-[#080A0F] p-4 lg:p-6 space-y-5">
      <header className="rounded-2xl border border-white/[0.08] bg-gradient-to-br from-[#101927] via-[#0B0F17] to-[#0B1220] p-5 lg:p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-cyan-400/25 bg-cyan-400/10 text-cyan-300">
            <Activity className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.2em] text-cyan-300/80">TokenIQ · Strategy workspace</p>
            <h1 className="mt-1 text-xl font-bold tracking-tight text-white lg:text-2xl">Strategy Center</h1>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">
              Test the Triple EMA strategy, compare 9/11/20 with 8/13/21, and validate results on unseen historical candles before enabling Testnet automation.
            </p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setMode('backtest')}
            className={`flex items-start gap-3 rounded-xl border p-4 text-left transition-colors ${mode === 'backtest' ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-white/[0.08] bg-black/10 hover:border-white/20'}`}
          >
            <LineChart className={`mt-0.5 h-5 w-5 shrink-0 ${mode === 'backtest' ? 'text-cyan-300' : 'text-slate-400'}`} />
            <span>
              <span className="block text-sm font-semibold text-white">1. Backtest</span>
              <span className="mt-1 block text-xs leading-5 text-slate-400">Run one setup and inspect equity, P&L, trades and drawdown.</span>
            </span>
          </button>
          <button
            type="button"
            onClick={() => setMode('validate')}
            className={`flex items-start gap-3 rounded-xl border p-4 text-left transition-colors ${mode === 'validate' ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-white/[0.08] bg-black/10 hover:border-white/20'}`}
          >
            <FlaskConical className={`mt-0.5 h-5 w-5 shrink-0 ${mode === 'validate' ? 'text-cyan-300' : 'text-slate-400'}`} />
            <span>
              <span className="block text-sm font-semibold text-white">2. Optimize &amp; validate</span>
              <span className="mt-1 block text-xs leading-5 text-slate-400">Compare EMA parameter sets and test the winner on a later, unseen period.</span>
            </span>
          </button>
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2.5 text-xs leading-5 text-amber-100/80">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          Historical performance is not a profit guarantee. Check out-of-sample return, drawdown, fees and trade count; this page does not itself turn automation on.
        </div>
      </header>

      {mode === 'backtest' ? (
        <BacktestingView initialSymbol={initialSymbol} onSelectSymbol={onSelectSymbol} />
      ) : (
        <StrategyLabView initialSymbol={initialSymbol} onSelectSymbol={onSelectSymbol} />
      )}
    </div>
  );
};
