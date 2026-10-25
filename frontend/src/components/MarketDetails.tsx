import React from 'react';
import {
  Star,
  Copy,
  Check,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
} from 'lucide-react';
import type { ChartResolution, MarketTicker } from '../types/market';

interface MarketDetailsProps {
  ticker: MarketTicker | null;
  resolution: ChartResolution;
  isWatchlisted: boolean;
  onToggleWatchlist: (symbol: string) => void;
}

export const MarketDetails: React.FC<MarketDetailsProps> = ({
  ticker,
  resolution,
  isWatchlisted,
  onToggleWatchlist,
}) => {
  const [copied, setCopied] = React.useState(false);

  if (!ticker) {
    return (
      <div className="flex flex-col items-center justify-center p-8 rounded-xl bg-[#0F1422] border border-white/[0.07] text-slate-400 text-center">
        <Activity className="w-8 h-8 text-slate-400 stroke-1 mb-2" />
        <span className="text-sm font-medium text-slate-300">No Pair Selected</span>
        <span className="text-xs text-slate-400 mt-1">Select any row from the market table to view comprehensive metrics.</span>
      </div>
    );
  }

  const handleCopySymbol = () => {
    navigator.clipboard.writeText(ticker.symbol);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isPositive = (ticker.change24h || 0) >= 0;

  const formatPrice = (val: number | null, decimals = 2) => {
    if (val === null || isNaN(val)) return 'N/A';
    if (val < 0.0001) return `$${val.toExponential(4)}`;
    if (val < 0.01) return `$${val.toFixed(6)}`;
    if (val < 1) return `$${val.toFixed(4)}`;
    return `$${val.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}`;
  };

  const formatPercent = (val: number | null) => {
    if (val === null || isNaN(val)) return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${val.toFixed(4)}%`;
  };

  const formatVolume = (val: number | null) => {
    if (val === null || isNaN(val)) return 'N/A';
    if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
    if (val >= 1e3) return `$${(val / 1e3).toFixed(2)}K`;
    return `$${val.toFixed(2)}`;
  };

  // Calculate bid/ask spread
  const spread =
    ticker.bestAsk !== null && ticker.bestBid !== null && ticker.bestAsk > ticker.bestBid
      ? ticker.bestAsk - ticker.bestBid
      : null;
  const spreadPercent =
    spread !== null && ticker.bestAsk !== null && ticker.bestAsk > 0
      ? (spread / ticker.bestAsk) * 100
      : null;

  return (
    <div className="flex flex-col rounded-xl bg-[#0F1422] border border-white/[0.07] overflow-hidden shadow-xl">
      {/* Header with pair info and actions */}
      <div className="p-4 border-b border-white/[0.07] bg-[#0D121F]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-white font-mono">{ticker.symbol}</h3>
            <button
              onClick={handleCopySymbol}
              className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
              title="Copy symbol"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>

          <button
            onClick={() => onToggleWatchlist(ticker.symbol)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-medium border transition-all ${
              isWatchlisted
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-white/[0.04] text-slate-400 border-white/[0.08] hover:text-white hover:bg-white/[0.08]'
            }`}
          >
            <Star className={`w-3.5 h-3.5 ${isWatchlisted ? 'fill-amber-400 text-amber-400' : ''}`} />
            {isWatchlisted ? 'Watchlisted' : 'Watchlist'}
          </button>
        </div>

        <div className="text-xs text-slate-400 mt-1 truncate font-sans">
          {ticker.name} · <span className="uppercase font-mono text-[11px] text-cyan-400">{ticker.contractType.replace('_', ' ')}</span>
        </div>
      </div>

      {/* Primary Price Block */}
      <div className="p-4 bg-[#0A0E17]/40 border-b border-white/[0.06]">
        <div className="text-xs text-slate-400 font-mono mb-1">Last Traded Price</div>
        <div className="flex items-baseline gap-2.5">
          <div className="text-2xl font-bold font-mono tracking-tight text-white tabular-nums">
            {formatPrice(ticker.lastPrice)}
          </div>
          {ticker.change24h !== null && (
            <span
              className={`inline-flex items-center gap-0.5 text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                isPositive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              }`}
            >
              {isPositive ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
              {ticker.change24h > 0 ? '+' : ''}
              {ticker.change24h.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      {/* Key Market Metrics Grid */}
      <div className="p-4 grid grid-cols-2 gap-3 text-xs font-mono border-b border-white/[0.06]">
        {/* Mark Price */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">Mark Price</div>
          <div className="text-slate-200 font-semibold tabular-nums">
            {formatPrice(ticker.markPrice)}
          </div>
        </div>

        {/* Spot Price */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">Index / Spot Price</div>
          <div className="text-slate-200 font-semibold tabular-nums">
            {formatPrice(ticker.spotPrice)}
          </div>
        </div>

        {/* 24h High */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">24h High</div>
          <div className="text-emerald-400 font-semibold tabular-nums">
            {formatPrice(ticker.high24h)}
          </div>
        </div>

        {/* 24h Low */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">24h Low</div>
          <div className="text-rose-400 font-semibold tabular-nums">
            {formatPrice(ticker.low24h)}
          </div>
        </div>

        {/* 24h Turnover USD */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">24h Turnover</div>
          <div className="text-slate-200 font-semibold tabular-nums">
            {formatVolume(ticker.turnover24hUsd)}
          </div>
        </div>

        {/* 24h Volume Coins */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">24h Base Volume</div>
          <div className="text-slate-200 font-semibold tabular-nums truncate">
            {ticker.volume24h !== null
              ? `${ticker.volume24h.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${ticker.baseAsset}`
              : 'N/A'}
          </div>
        </div>

        {/* Funding Rate */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">Funding Rate</div>
          <div className="text-cyan-400 font-semibold tabular-nums">
            {ticker.fundingRate !== null ? formatPercent(ticker.fundingRate * 100) : 'N/A'}
          </div>
        </div>

        {/* Selected Chart Interval */}
        <div className="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1">Chart Interval</div>
          <div className="text-slate-200 font-semibold uppercase">{resolution}</div>
        </div>
      </div>

      {/* Order Book Quotes / Spread */}
      <div className="p-4 bg-[#0A0E17]/60">
        <div className="text-xs font-semibold text-slate-300 font-sans mb-2.5 flex items-center justify-between">
          <span>Best Bid / Ask Quotes</span>
          <span className="text-[10px] text-slate-400 font-mono">Top of Book</span>
        </div>

        <div className="space-y-2 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Best Bid:</span>
            <span className="text-emerald-400 font-semibold tabular-nums">
              {formatPrice(ticker.bestBid)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Best Ask:</span>
            <span className="text-rose-400 font-semibold tabular-nums">
              {formatPrice(ticker.bestAsk)}
            </span>
          </div>
          <div className="flex items-center justify-between pt-1 border-t border-white/[0.05]">
            <span className="text-slate-400">Spread:</span>
            <span className="text-slate-300 tabular-nums">
              {spread !== null ? `${formatPrice(spread)} (${spreadPercent?.toFixed(3)}%)` : 'N/A'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
