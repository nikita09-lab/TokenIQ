import React, { useState, useEffect, useMemo } from 'react';
import { Sidebar } from '../components/Sidebar';
import { Topbar } from '../components/Topbar';
import { MarketSummary } from '../components/MarketSummary';
import { MarketTable } from '../components/MarketTable';
import { MarketChart } from '../components/MarketChart';
import { MarketDetails } from '../components/MarketDetails';
import { AboutView } from '../components/AboutView';
import { BacktestingView } from '../components/BacktestingView';
import { StrategyLabView } from '../components/StrategyLabView';
import { AccountWalletView } from '../components/AccountWalletView';
import { TradingSafetyView } from '../components/TradingSafetyView';
import { useMarketData } from '../hooks/useMarketData';
import { useMarketWebSocket } from '../hooks/useMarketWebSocket';
import type { ActiveTab, ChartResolution, HistoryRangeConfig } from '../types/market';
import { WifiOff } from 'lucide-react';

export const DashboardPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSD');
  const [chartResolution, setChartResolution] = useState<ChartResolution>('1h');
  const [historyRange, setHistoryRange] = useState<HistoryRangeConfig>({
    type: '7D',
    label: '7D',
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Watchlist stored locally in browser
  const [watchlist, setWatchlist] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('tokeniq_watchlist');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      // ignore
    }
    return ['BTCUSD', 'ETHUSD', 'SOLUSD'];
  });

  // Save watchlist to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('tokeniq_watchlist', JSON.stringify(watchlist));
    } catch {
      // ignore
    }
  }, [watchlist]);

  const handleToggleWatchlist = (symbol: string) => {
    setWatchlist((prev) =>
      prev.includes(symbol) ? prev.filter((s) => s !== symbol) : [...prev, symbol]
    );
  };

  // Live market REST data & statistics from FastAPI backend
  const { tickers, tickersMap, marketStats, isLoading, error, lastRefreshed, refresh } =
    useMarketData();

  // Real-time WebSocket connection & candlestick streaming from FastAPI WebSocket bridge
  const { connectionStatus, latestCandle, lastMessageTime, reconnect } = useMarketWebSocket(
    selectedSymbol,
    chartResolution
  );

  // Selected ticker object
  const selectedTicker = useMemo(() => {
    return tickersMap.get(selectedSymbol) || tickers.find((t) => t.symbol === selectedSymbol) || null;
  }, [tickersMap, tickers, selectedSymbol]);

  // When a user selects a pair
  const handleSelectPair = (symbol: string) => {
    setSelectedSymbol(symbol);
    setSearchQuery('');
  };

  return (
    <div className="flex h-screen w-full bg-[#080A0F] text-slate-100 overflow-hidden font-sans">
      {/* Sidebar for Desktop */}
      <div className="hidden md:flex">
        <Sidebar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
          watchlistCount={watchlist.length}
        />
      </div>

      {/* Mobile Drawer Overlay */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileMenuOpen(false)}
          />
          <div className="relative z-10 w-64 bg-[#0B0F17] h-full shadow-2xl">
            <Sidebar
              activeTab={activeTab}
              onTabChange={(tab) => {
                setActiveTab(tab);
                setMobileMenuOpen(false);
              }}
              collapsed={false}
              onToggleCollapse={() => setMobileMenuOpen(false)}
              watchlistCount={watchlist.length}
            />
          </div>
        </div>
      )}

      {/* Main App Content Area */}
      <div className="flex flex-col flex-1 min-w-0 h-screen overflow-hidden">
        {/* Topbar */}
        <Topbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          connectionStatus={connectionStatus}
          lastMessageTime={lastMessageTime}
          lastRefreshed={lastRefreshed}
          onRefresh={refresh}
          isRefreshing={isLoading}
          onToggleMobileMenu={() => setMobileMenuOpen(!mobileMenuOpen)}
          tickers={tickers}
          onSelectPair={handleSelectPair}
        />

        {/* Warning Banner if disconnected */}
        {connectionStatus === 'disconnected' && (
          <div className="px-4 py-2 bg-rose-500/10 border-b border-rose-500/20 text-rose-300 text-xs flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <WifiOff className="w-4 h-4 text-rose-400 shrink-0" />
              <span>
                <strong>Live Feed Disconnected:</strong> Real-time WebSocket bridge to backend is down. Attempting auto-reconnection with exponential backoff.
              </span>
            </div>
            <button
              onClick={reconnect}
              className="px-2.5 py-0.5 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 font-mono text-[11px] font-semibold transition-colors"
            >
              Reconnect Now
            </button>
          </div>
        )}

        {/* Scrollable Dashboard Viewport */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {/* Main Chart & Trading Views (Preserved during navigation to prevent chart unmounting) */}
          <div className={['overview', 'charts', 'watchlist'].includes(activeTab) ? 'space-y-6' : 'hidden'}>
            {/* 1. Header based on active tab */}
            {activeTab === 'overview' && (
              <MarketSummary
                stats={marketStats}
                connectionStatus={connectionStatus}
                isLoading={isLoading}
                onSelectPair={handleSelectPair}
              />
            )}

            {activeTab === 'charts' && (
              <div className="flex items-center justify-between pb-1">
                <div>
                  <h1 className="text-xl font-bold text-white tracking-tight">Interactive Trading Chart (PRO)</h1>
                  <p className="text-xs text-slate-400 font-mono">
                    Institutional-grade candlestick terminal with volume histogram and historical date-range controls
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'watchlist' && (
              <div className="flex items-center justify-between pb-1">
                <div>
                  <h1 className="text-xl font-bold text-white tracking-tight">Market Watchlist</h1>
                  <p className="text-xs text-slate-400 font-mono">
                    {watchlist.length} saved trading pairs monitored in local browser storage
                  </p>
                </div>
              </div>
            )}

            {/* 2. Persistent Chart & Details Row */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              <div className="xl:col-span-2 min-w-0">
                <MarketChart
                  selectedTicker={selectedTicker}
                  resolution={chartResolution}
                  onResolutionChange={setChartResolution}
                  latestWsCandle={latestCandle}
                  connectionStatus={connectionStatus}
                  historyRange={historyRange}
                  onHistoryRangeChange={setHistoryRange}
                />
              </div>
              <div className="xl:col-span-1 min-w-0">
                <MarketDetails
                  ticker={selectedTicker}
                  resolution={chartResolution}
                  isWatchlisted={watchlist.includes(selectedSymbol)}
                  onToggleWatchlist={handleToggleWatchlist}
                />
              </div>
            </div>

            {/* 3. Table below chart customized per active tab */}
            {activeTab === 'overview' && (
              <MarketTable
                tickers={tickers}
                selectedSymbol={selectedSymbol}
                onSelectPair={handleSelectPair}
                watchlist={watchlist}
                onToggleWatchlist={handleToggleWatchlist}
                isLoading={isLoading}
                error={error}
                onRetry={refresh}
                searchFilter={searchQuery}
              />
            )}

            {activeTab === 'charts' && (
              <MarketTable
                tickers={tickers}
                selectedSymbol={selectedSymbol}
                onSelectPair={handleSelectPair}
                watchlist={watchlist}
                onToggleWatchlist={handleToggleWatchlist}
                isLoading={isLoading}
                error={error}
                onRetry={refresh}
                searchFilter={searchQuery}
              />
            )}

            {activeTab === 'watchlist' && (
              <MarketTable
                tickers={tickers.filter((t) => watchlist.includes(t.symbol))}
                selectedSymbol={selectedSymbol}
                onSelectPair={handleSelectPair}
                watchlist={watchlist}
                onToggleWatchlist={handleToggleWatchlist}
                isLoading={isLoading}
                error={error}
                onRetry={refresh}
                searchFilter={searchQuery}
              />
            )}
          </div>

          {/* Strategy Backtesting View */}
          {activeTab === 'backtesting' && (
            <BacktestingView
              initialSymbol={selectedSymbol}
              onSelectSymbol={handleSelectPair}
            />
          )}

          {/* Phase 4: Strategy Lab (Evaluation and Robustness Testing) */}
          {activeTab === 'evaluation' && (
            <StrategyLabView
              initialSymbol={selectedSymbol}
              onSelectSymbol={handleSelectPair}
            />
          )}

          {/* Phase 6: Testnet Wallet & Account View */}
          {activeTab === 'wallet' && (
            <AccountWalletView
              onSelectSymbol={handleSelectPair}
            />
          )}

          {/* Phase 7.1: Risk & Safety Engine View */}
          {activeTab === 'safety' && (
            <TradingSafetyView
              onSelectSymbol={handleSelectPair}
            />
          )}

          {/* About View */}
          {activeTab === 'about' && <AboutView />}
        </main>
      </div>
    </div>
  );
};
