import React, { useRef, useState, useEffect } from 'react';
import {
  Search,
  RefreshCw,
  Menu,
  Clock,
  Sparkles,
  X,
} from 'lucide-react';
import { ConnectionStatus } from './ConnectionStatus';
import type { ConnectionStatusType, MarketTicker } from '../types/market';

interface TopbarProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  connectionStatus: ConnectionStatusType;
  lastMessageTime?: Date | null;
  lastRefreshed: Date | null;
  onRefresh: () => void;
  isRefreshing: boolean;
  onToggleMobileMenu: () => void;
  tickers: MarketTicker[];
  onSelectPair: (symbol: string) => void;
}

export const Topbar: React.FC<TopbarProps> = ({
  searchQuery,
  onSearchChange,
  connectionStatus,
  lastMessageTime,
  lastRefreshed,
  onRefresh,
  isRefreshing,
  onToggleMobileMenu,
  tickers,
  onSelectPair,
}) => {
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const searchContainerRef = useRef<HTMLDivElement>(null);

  // Close search dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setIsSearchFocused(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Quick matches for search dropdown
  const filteredQuickMatches = searchQuery.trim()
    ? tickers
        .filter(
          (t) =>
            t.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
            t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            t.baseAsset.toLowerCase().includes(searchQuery.toLowerCase())
        )
        .slice(0, 6)
    : [];

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between h-16 px-4 md:px-6 bg-[#0E131F]/90 backdrop-blur-md border-b border-white/[0.07] gap-4">
      {/* Left: Mobile hamburger & Search bar */}
      <div className="flex items-center gap-3 flex-1 max-w-lg">
        <button
          onClick={onToggleMobileMenu}
          className="md:hidden p-2 text-slate-400 hover:text-white hover:bg-white/[0.05] rounded-lg transition-colors"
          aria-label="Toggle navigation menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Search input with drop-down results */}
        <div ref={searchContainerRef} className="relative w-full max-w-sm">
          <div className="relative flex items-center">
            <Search className="absolute left-3 w-4 h-4 text-slate-400 pointer-events-none" />
            <input
              type="text"
              placeholder="Search pairs (e.g. BTC, ETH, SOL)..."
              value={searchQuery}
              onChange={(e) => {
                onSearchChange(e.target.value);
                setIsSearchFocused(true);
              }}
              onFocus={() => setIsSearchFocused(true)}
              className="w-full h-9 pl-9 pr-8 text-xs sm:text-sm bg-[#131929] border border-white/[0.1] rounded-lg text-slate-200 placeholder-slate-400 focus:outline-none focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/30 transition-all font-mono"
            />
            {searchQuery && (
              <button
                onClick={() => {
                  onSearchChange('');
                  setIsSearchFocused(false);
                }}
                className="absolute right-2.5 p-0.5 text-slate-400 hover:text-white rounded"
                title="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Quick search dropdown */}
          {isSearchFocused && filteredQuickMatches.length > 0 && (
            <div className="absolute left-0 right-0 mt-1.5 py-1.5 bg-[#121826] border border-white/[0.1] rounded-lg shadow-2xl z-50 overflow-hidden">
              <div className="px-3 py-1 text-[10px] uppercase font-mono tracking-wider text-slate-400">
                Matching Trading Pairs ({filteredQuickMatches.length})
              </div>
              {filteredQuickMatches.map((ticker) => {
                const isPositive = (ticker.change24h || 0) >= 0;
                return (
                  <button
                    key={ticker.symbol}
                    onClick={() => {
                      onSelectPair(ticker.symbol);
                      setIsSearchFocused(false);
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 text-xs hover:bg-white/[0.06] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-bold font-mono text-slate-200">{ticker.symbol}</span>
                      <span className="text-[10px] text-slate-400 font-sans">{ticker.contractType.replace('_', ' ')}</span>
                    </div>
                    <div className="flex items-center gap-2.5">
                      <span className="font-mono text-slate-100">
                        ${ticker.lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                      </span>
                      {ticker.change24h !== null && (
                        <span
                          className={`font-mono text-[11px] font-semibold flex items-center ${
                            isPositive ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {isPositive ? '+' : ''}
                          {ticker.change24h.toFixed(2)}%
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Right controls: Exchange label, Connection status, Last refreshed, Refresh button */}
      <div className="flex items-center gap-2.5 sm:gap-4 shrink-0">
        {/* Exchange Tag */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#131929] border border-white/[0.08] text-xs font-medium text-slate-300">
          <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-mono text-slate-400 text-[11px]">Exchange:</span>
          <span className="text-white font-semibold">Delta Exchange</span>
        </div>

        {/* Real Live WebSocket Connection Status */}
        <ConnectionStatus status={connectionStatus} lastMessageTime={lastMessageTime} />

        {/* Last updated timestamp */}
        <div className="hidden lg:flex items-center gap-1.5 text-slate-400 text-xs font-mono">
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span>
            {lastRefreshed
              ? lastRefreshed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
              : 'Syncing...'}
          </span>
        </div>

        {/* Refresh button */}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className={`flex items-center justify-center w-8 h-8 rounded-lg bg-[#131929] border border-white/[0.08] text-slate-300 hover:text-white hover:border-cyan-400/40 transition-all ${
            isRefreshing ? 'opacity-60 cursor-not-allowed' : 'active:scale-95'
          }`}
          title="Refresh market data"
          aria-label="Refresh market data"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-cyan-400' : ''}`} />
        </button>
      </div>
    </header>
  );
};
