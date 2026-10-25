import React, { useState, useMemo } from 'react';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Star,
  Search,
  AlertCircle,
} from 'lucide-react';
import type { MarketTicker, SortDirection, SortField } from '../types/market';

interface MarketTableProps {
  tickers: MarketTicker[];
  selectedSymbol: string;
  onSelectPair: (symbol: string) => void;
  watchlist: string[];
  onToggleWatchlist: (symbol: string) => void;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  searchFilter?: string;
}

export const MarketTable: React.FC<MarketTableProps> = ({
  tickers,
  selectedSymbol,
  onSelectPair,
  watchlist,
  onToggleWatchlist,
  isLoading,
  error,
  onRetry,
  searchFilter = '',
}) => {
  const [filterType, setFilterType] = useState<'all' | 'perpetual' | 'spot' | 'watchlist'>('perpetual');
  const [sortField, setSortField] = useState<SortField>('turnover24hUsd');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const pageSize = 20;

  // Handle column header sort toggle
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  // Filter tickers
  const filteredTickers = useMemo(() => {
    return tickers.filter((t) => {
      // Type filter
      if (filterType === 'perpetual' && t.contractType !== 'perpetual_futures') {
        return false;
      }
      if (filterType === 'spot' && t.contractType !== 'spot') {
        return false;
      }
      if (filterType === 'watchlist' && !watchlist.includes(t.symbol)) {
        return false;
      }

      // Search filter
      if (searchFilter.trim()) {
        const query = searchFilter.toLowerCase();
        const matchesSym = t.symbol.toLowerCase().includes(query);
        const matchesName = t.name.toLowerCase().includes(query);
        const matchesBase = t.baseAsset.toLowerCase().includes(query);
        if (!matchesSym && !matchesName && !matchesBase) return false;
      }

      return true;
    });
  }, [tickers, filterType, watchlist, searchFilter]);

  // Sort tickers
  const sortedTickers = useMemo(() => {
    const list = [...filteredTickers];
    list.sort((a, b) => {
      let valA: number | string | null = null;
      let valB: number | string | null = null;

      switch (sortField) {
        case 'symbol':
          valA = a.symbol;
          valB = b.symbol;
          break;
        case 'lastPrice':
          valA = a.lastPrice;
          valB = b.lastPrice;
          break;
        case 'change24h':
          valA = a.change24h ?? -Infinity;
          valB = b.change24h ?? -Infinity;
          break;
        case 'high24h':
          valA = a.high24h ?? -Infinity;
          valB = b.high24h ?? -Infinity;
          break;
        case 'low24h':
          valA = a.low24h ?? -Infinity;
          valB = b.low24h ?? -Infinity;
          break;
        case 'volume24h':
          valA = a.volume24h ?? -Infinity;
          valB = b.volume24h ?? -Infinity;
          break;
        case 'turnover24hUsd':
        default:
          valA = a.turnover24hUsd ?? -Infinity;
          valB = b.turnover24hUsd ?? -Infinity;
          break;
      }

      if (valA === null) return 1;
      if (valB === null) return -1;

      if (typeof valA === 'string' && typeof valB === 'string') {
        return sortDirection === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }

      return sortDirection === 'asc' ? (valA as number) - (valB as number) : (valB as number) - (valA as number);
    });
    return list;
  }, [filteredTickers, sortField, sortDirection]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sortedTickers.length / pageSize));
  const paginatedTickers = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedTickers.slice(start, start + pageSize);
  }, [sortedTickers, currentPage, pageSize]);

  // Reset page when filter or search changes
  React.useEffect(() => {
    setCurrentPage(1);
  }, [filterType, searchFilter]);

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ArrowUpDown className="w-3 h-3 text-slate-400 opacity-50 group-hover:opacity-100" />;
    }
    return sortDirection === 'asc' ? (
      <ArrowUp className="w-3 h-3 text-cyan-400" />
    ) : (
      <ArrowDown className="w-3 h-3 text-cyan-400" />
    );
  };

  const formatPrice = (price: number) => {
    if (price === 0) return '0.00';
    if (price < 0.0001) return price.toExponential(4);
    if (price < 0.01) return price.toFixed(6);
    if (price < 1) return price.toFixed(4);
    if (price < 1000) return price.toFixed(2);
    return price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const formatVolume = (val: number | null) => {
    if (val === null || isNaN(val)) return 'N/A';
    if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
    if (val >= 1e3) return `$${(val / 1e3).toFixed(2)}K`;
    return `$${val.toFixed(2)}`;
  };

  return (
    <div className="flex flex-col rounded-xl bg-[#0F1422] border border-white/[0.07] overflow-hidden shadow-xl">
      {/* Table Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-white/[0.07] bg-[#0D121F]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white font-sans tracking-tight">Market Markets</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-400 font-mono">
            {filteredTickers.length} Pairs
          </span>
        </div>

        {/* Market Filter Tabs */}
        <div className="flex items-center gap-1 p-1 rounded-lg bg-[#080B12] border border-white/[0.06]">
          <button
            onClick={() => setFilterType('perpetual')}
            className={`px-3 py-1 rounded text-xs font-medium transition-all ${
              filterType === 'perpetual'
                ? 'bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/30 shadow-glow-cyan/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Perpetuals
          </button>
          <button
            onClick={() => setFilterType('spot')}
            className={`px-3 py-1 rounded text-xs font-medium transition-all ${
              filterType === 'spot'
                ? 'bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Spot
          </button>
          <button
            onClick={() => setFilterType('all')}
            className={`px-3 py-1 rounded text-xs font-medium transition-all ${
              filterType === 'all'
                ? 'bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            All Products
          </button>
          <button
            onClick={() => setFilterType('watchlist')}
            className={`px-3 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-all ${
              filterType === 'watchlist'
                ? 'bg-amber-500/20 text-amber-300 font-semibold border border-amber-500/30'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Star className={`w-3 h-3 ${watchlist.length > 0 ? 'fill-amber-400 text-amber-400' : ''}`} />
            Watchlist ({watchlist.length})
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="m-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={onRetry}
            className="px-2.5 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 font-medium font-mono text-[11px] transition-colors"
          >
            Retry Fetch
          </button>
        </div>
      )}

      {/* Table Container */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-white/[0.06] bg-[#0A0E17]/60 text-[11px] font-mono uppercase tracking-wider text-slate-400">
              <th className="py-3 px-3 w-10 text-center">★</th>
              <th
                onClick={() => handleSort('symbol')}
                className="py-3 px-4 cursor-pointer hover:text-slate-200 transition-colors group select-none"
              >
                <div className="flex items-center gap-1.5">
                  <span>Trading Pair</span>
                  {renderSortIcon('symbol')}
                </div>
              </th>
              <th
                onClick={() => handleSort('lastPrice')}
                className="py-3 px-4 text-right cursor-pointer hover:text-slate-200 transition-colors group select-none"
              >
                <div className="flex items-center justify-end gap-1.5">
                  <span>Last Price</span>
                  {renderSortIcon('lastPrice')}
                </div>
              </th>
              <th
                onClick={() => handleSort('change24h')}
                className="py-3 px-4 text-right cursor-pointer hover:text-slate-200 transition-colors group select-none"
              >
                <div className="flex items-center justify-end gap-1.5">
                  <span>24h Change</span>
                  {renderSortIcon('change24h')}
                </div>
              </th>
              <th
                onClick={() => handleSort('high24h')}
                className="py-3 px-4 text-right cursor-pointer hover:text-slate-200 transition-colors group select-none hidden md:table-cell"
              >
                <div className="flex items-center justify-end gap-1.5">
                  <span>24h High</span>
                  {renderSortIcon('high24h')}
                </div>
              </th>
              <th
                onClick={() => handleSort('low24h')}
                className="py-3 px-4 text-right cursor-pointer hover:text-slate-200 transition-colors group select-none hidden md:table-cell"
              >
                <div className="flex items-center justify-end gap-1.5">
                  <span>24h Low</span>
                  {renderSortIcon('low24h')}
                </div>
              </th>
              <th
                onClick={() => handleSort('turnover24hUsd')}
                className="py-3 px-4 text-right cursor-pointer hover:text-slate-200 transition-colors group select-none hidden sm:table-cell"
              >
                <div className="flex items-center justify-end gap-1.5">
                  <span>24h Turnover</span>
                  {renderSortIcon('turnover24hUsd')}
                </div>
              </th>
              <th className="py-3 px-4 text-right hidden lg:table-cell">Last Updated</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-white/[0.04] text-xs font-mono">
            {isLoading && tickers.length === 0 ? (
              // Loading skeletons
              Array.from({ length: 10 }).map((_, i) => (
                <tr key={i} className="animate-pulse">
                  <td className="py-3.5 px-3 text-center">
                    <div className="w-4 h-4 bg-white/[0.06] rounded mx-auto" />
                  </td>
                  <td className="py-3.5 px-4">
                    <div className="w-24 h-4 bg-white/[0.06] rounded mb-1" />
                    <div className="w-16 h-3 bg-white/[0.04] rounded" />
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <div className="w-20 h-4 bg-white/[0.06] rounded ml-auto" />
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <div className="w-16 h-4 bg-white/[0.06] rounded ml-auto" />
                  </td>
                  <td className="py-3.5 px-4 text-right hidden md:table-cell">
                    <div className="w-16 h-4 bg-white/[0.06] rounded ml-auto" />
                  </td>
                  <td className="py-3.5 px-4 text-right hidden md:table-cell">
                    <div className="w-16 h-4 bg-white/[0.06] rounded ml-auto" />
                  </td>
                  <td className="py-3.5 px-4 text-right hidden sm:table-cell">
                    <div className="w-20 h-4 bg-white/[0.06] rounded ml-auto" />
                  </td>
                  <td className="py-3.5 px-4 text-right hidden lg:table-cell">
                    <div className="w-14 h-3 bg-white/[0.04] rounded ml-auto" />
                  </td>
                </tr>
              ))
            ) : paginatedTickers.length === 0 ? (
              // Empty state
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-400 font-sans">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <Search className="w-8 h-8 text-slate-400 stroke-1" />
                    <span className="text-sm font-medium text-slate-300">No trading pairs found</span>
                    <span className="text-xs text-slate-400">
                      {filterType === 'watchlist'
                        ? 'Your watchlist is currently empty. Star pairs from the table to save them.'
                        : 'Try adjusting your search query or product filters.'}
                    </span>
                  </div>
                </td>
              </tr>
            ) : (
              paginatedTickers.map((ticker) => {
                const isSelected = ticker.symbol === selectedSymbol;
                const isWatchlisted = watchlist.includes(ticker.symbol);
                const isPositive = (ticker.change24h || 0) >= 0;

                // Flash class on real-time price change
                const flashClass =
                  ticker.priceDirection === 'up'
                    ? 'price-flash-up'
                    : ticker.priceDirection === 'down'
                    ? 'price-flash-down'
                    : '';

                return (
                  <tr
                    key={ticker.symbol}
                    onClick={() => onSelectPair(ticker.symbol)}
                    className={`cursor-pointer transition-colors hover:bg-white/[0.04] ${
                      isSelected ? 'bg-cyan-500/[0.07] border-l-2 border-l-cyan-400' : ''
                    } ${flashClass}`}
                  >
                    {/* Watchlist Star */}
                    <td
                      className="py-3.5 px-3 text-center"
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleWatchlist(ticker.symbol);
                      }}
                    >
                      <button
                        className="p-1 rounded hover:bg-white/[0.08] text-slate-400 transition-colors"
                        title={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                        aria-label={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                      >
                        <Star
                          className={`w-4 h-4 transition-transform hover:scale-110 ${
                            isWatchlisted ? 'fill-amber-400 text-amber-400' : 'text-slate-400 hover:text-slate-300'
                          }`}
                        />
                      </button>
                    </td>

                    {/* Pair Symbol & Tag */}
                    <td className="py-3.5 px-4 font-sans">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white font-mono text-sm tracking-tight">{ticker.symbol}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded font-mono uppercase bg-white/[0.06] text-slate-400">
                          {ticker.contractType === 'perpetual_futures'
                            ? 'PERP'
                            : ticker.contractType === 'spot'
                            ? 'SPOT'
                            : 'OPT'}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono truncate max-w-[180px]">
                        {ticker.name}
                      </div>
                    </td>

                    {/* Last Price */}
                    <td className="py-3.5 px-4 text-right">
                      <span className="font-bold text-white text-sm tabular-nums tracking-tight">
                        ${formatPrice(ticker.lastPrice)}
                      </span>
                    </td>

                    {/* 24h Change */}
                    <td className="py-3.5 px-4 text-right">
                      {ticker.change24h !== null ? (
                        <span
                          className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded font-mono font-semibold text-xs tabular-nums ${
                            isPositive
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                          }`}
                        >
                          {isPositive ? '+' : ''}
                          {ticker.change24h.toFixed(2)}%
                        </span>
                      ) : (
                        <span className="text-slate-400">N/A</span>
                      )}
                    </td>

                    {/* 24h High */}
                    <td className="py-3.5 px-4 text-right text-slate-300 tabular-nums hidden md:table-cell">
                      {ticker.high24h !== null ? `$${formatPrice(ticker.high24h)}` : 'N/A'}
                    </td>

                    {/* 24h Low */}
                    <td className="py-3.5 px-4 text-right text-slate-300 tabular-nums hidden md:table-cell">
                      {ticker.low24h !== null ? `$${formatPrice(ticker.low24h)}` : 'N/A'}
                    </td>

                    {/* 24h Turnover USD */}
                    <td className="py-3.5 px-4 text-right text-slate-200 font-semibold tabular-nums hidden sm:table-cell">
                      {formatVolume(ticker.turnover24hUsd)}
                    </td>

                    {/* Last Updated Timestamp */}
                    <td className="py-3.5 px-4 text-right text-slate-400 text-[11px] tabular-nums hidden lg:table-cell">
                      {ticker.lastUpdatedStr}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Bar */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.06] bg-[#0A0E17]/60 text-xs font-mono text-slate-400">
          <div>
            Showing {(currentPage - 1) * pageSize + 1} -{' '}
            {Math.min(currentPage * pageSize, sortedTickers.length)} of {sortedTickers.length} pairs
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="px-2.5 py-1 rounded bg-white/[0.04] border border-white/[0.07] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white/[0.08] transition-colors"
            >
              Previous
            </button>
            <span className="px-2 font-semibold text-slate-200">
              {currentPage} / {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="px-2.5 py-1 rounded bg-white/[0.04] border border-white/[0.07] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white/[0.08] transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
