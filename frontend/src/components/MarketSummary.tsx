import React from 'react';
import {
  Layers,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
} from 'lucide-react';
import type { ConnectionStatusType, MarketStats } from '../types/market';

interface MarketSummaryProps {
  stats: MarketStats;
  connectionStatus: ConnectionStatusType;
  isLoading: boolean;
  onSelectPair: (symbol: string) => void;
}

export const MarketSummary: React.FC<MarketSummaryProps> = ({
  stats,
  connectionStatus,
  isLoading,
  onSelectPair,
}) => {
  const formatUsd = (val: number | null, decimals = 2) => {
    if (val === null || isNaN(val)) return 'N/A';
    return `$${val.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}`;
  };

  const formatPercent = (val: number | null) => {
    if (val === null || isNaN(val)) return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${val.toFixed(2)}%`;
  };

  const formatVolume = (val: number | null) => {
    if (val === null || isNaN(val)) return 'N/A';
    if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
    if (val >= 1e3) return `$${(val / 1e3).toFixed(2)}K`;
    return `$${val.toFixed(2)}`;
  };

  const isBtcPositive = (stats.btcChange24h || 0) >= 0;
  const isEthPositive = (stats.ethChange24h || 0) >= 0;

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" aria-label="Market Summary Cards">
      {/* 1. BTC Market Price Card */}
      <div
        onClick={() => onSelectPair('BTCUSD')}
        className="group relative p-4 rounded-xl bg-[#0F1422] border border-white/[0.07] hover:border-cyan-400/30 hover:bg-[#121929] transition-all cursor-pointer shadow-lg overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-24 h-24 bg-amber-500/5 rounded-full blur-2xl group-hover:bg-amber-500/10 transition-all pointer-events-none" />

        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center font-bold text-amber-400 text-xs font-mono">
              ₿
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-300">Bitcoin</h3>
              <span className="text-[10px] font-mono text-slate-400">BTCUSD · Perp</span>
            </div>
          </div>
          {stats.btcChange24h !== null && (
            <span
              className={`inline-flex items-center gap-0.5 text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                isBtcPositive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              }`}
            >
              {isBtcPositive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
              {formatPercent(stats.btcChange24h)}
            </span>
          )}
        </div>

        <div className="mt-2">
          <div className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-white tabular-nums">
            {isLoading && !stats.btcPrice ? (
              <div className="h-7 w-28 bg-white/[0.06] rounded animate-pulse" />
            ) : (
              formatUsd(stats.btcPrice, 2)
            )}
          </div>

          <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.05] text-[11px] text-slate-400 font-mono">
            <span>24h Vol</span>
            <span className="text-slate-300 font-medium">
              {stats.btcVolume ? `${stats.btcVolume.toLocaleString(undefined, { maximumFractionDigits: 1 })} BTC` : 'N/A'}
            </span>
          </div>
        </div>
      </div>

      {/* 2. ETH Market Price Card */}
      <div
        onClick={() => onSelectPair('ETHUSD')}
        className="group relative p-4 rounded-xl bg-[#0F1422] border border-white/[0.07] hover:border-cyan-400/30 hover:bg-[#121929] transition-all cursor-pointer shadow-lg overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-2xl group-hover:bg-blue-500/10 transition-all pointer-events-none" />

        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center font-bold text-blue-400 text-xs font-mono">
              Ξ
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-300">Ethereum</h3>
              <span className="text-[10px] font-mono text-slate-400">ETHUSD · Perp</span>
            </div>
          </div>
          {stats.ethChange24h !== null && (
            <span
              className={`inline-flex items-center gap-0.5 text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                isEthPositive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              }`}
            >
              {isEthPositive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
              {formatPercent(stats.ethChange24h)}
            </span>
          )}
        </div>

        <div className="mt-2">
          <div className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-white tabular-nums">
            {isLoading && !stats.ethPrice ? (
              <div className="h-7 w-28 bg-white/[0.06] rounded animate-pulse" />
            ) : (
              formatUsd(stats.ethPrice, 2)
            )}
          </div>

          <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.05] text-[11px] text-slate-400 font-mono">
            <span>24h Vol</span>
            <span className="text-slate-300 font-medium">
              {stats.ethVolume ? `${stats.ethVolume.toLocaleString(undefined, { maximumFractionDigits: 1 })} ETH` : 'N/A'}
            </span>
          </div>
        </div>
      </div>

      {/* 3. Available Trading Pairs Card */}
      <div className="p-4 rounded-xl bg-[#0F1422] border border-white/[0.07] shadow-lg">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-300">Trading Products</h3>
              <span className="text-[10px] font-mono text-slate-400">Delta Exchange Ecosystem</span>
            </div>
          </div>
          <span className="text-[10px] font-mono text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded">
            Live
          </span>
        </div>

        <div className="mt-2">
          <div className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-white tabular-nums">
            {isLoading ? (
              <div className="h-7 w-20 bg-white/[0.06] rounded animate-pulse" />
            ) : (
              stats.totalTradingPairs.toLocaleString()
            )}
          </div>

          <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.05] text-[11px] text-slate-400 font-mono">
            <span>Active Perpetuals</span>
            <span className="text-slate-300 font-medium">
              {stats.activePerpetuals > 0 ? `${stats.activePerpetuals} Contracts` : 'N/A'}
            </span>
          </div>
        </div>
      </div>

      {/* 4. Overall Market Status Card */}
      <div className="p-4 rounded-xl bg-[#0F1422] border border-white/[0.07] shadow-lg">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-300">Market Breadth</h3>
              <span className="text-[10px] font-mono text-slate-400">Gainers / Losers</span>
            </div>
          </div>
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded uppercase font-bold ${
              connectionStatus === 'connected'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
            }`}
          >
            {connectionStatus}
          </span>
        </div>

        <div className="mt-2">
          <div className="flex items-baseline gap-2 font-mono">
            <span className="text-xl sm:text-2xl font-bold text-emerald-400 tabular-nums">
              {stats.gainersCount}
            </span>
            <span className="text-xs text-slate-400">Up</span>
            <span className="text-slate-400">/</span>
            <span className="text-xl sm:text-2xl font-bold text-rose-400 tabular-nums">
              {stats.losersCount}
            </span>
            <span className="text-xs text-slate-400">Down</span>
          </div>

          <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.05] text-[11px] text-slate-400 font-mono">
            <span>Est. 24h Turnover</span>
            <span className="text-slate-300 font-medium">{formatVolume(stats.totalVolumeUsd24h)}</span>
          </div>
        </div>
      </div>
    </section>
  );
};
