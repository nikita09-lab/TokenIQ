import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Wallet,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Check,
  ExternalLink,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  Lock,
  Coins,
  Activity,
  FileText,
  AlertCircle,
  HelpCircle,
} from 'lucide-react';
import { getAccountOverview } from '../services/api';
import type {
  AccountOverviewData,
  WalletBalanceItemData,
  PositionItemData,
  OrderItemData,
} from '../types/market';

interface AccountWalletViewProps {
  onSelectSymbol?: (symbol: string) => void;
}

type WalletTab = 'balances' | 'positions' | 'orders' | 'history';
type RefreshInterval = 0 | 10000 | 30000 | 60000;

export const AccountWalletView: React.FC<AccountWalletViewProps> = ({ onSelectSymbol }) => {
  const [data, setData] = useState<AccountOverviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<WalletTab>('balances');
  const [autoRefreshInterval, setAutoRefreshInterval] = useState<RefreshInterval>(30000);
  const [copiedIp, setCopiedIp] = useState<boolean>(false);
  const [copiedOrderId, setCopiedOrderId] = useState<string | null>(null);

  const isMountedRef = useRef<boolean>(true);

  // Fetch account overview from backend
  const fetchOverview = useCallback(async (isManual = false) => {
    if (isManual) {
      setRefreshing(true);
    }
    setError(null);

    try {
      const overview = await getAccountOverview();
      if (isMountedRef.current) {
        setData(overview);
        setLoading(false);
        setRefreshing(false);
      }
    } catch (err: unknown) {
      if (isMountedRef.current) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  // Initial load
  useEffect(() => {
    isMountedRef.current = true;
    fetchOverview();

    return () => {
      isMountedRef.current = false;
    };
  }, [fetchOverview]);

  // Configurable auto-refresh interval
  useEffect(() => {
    if (autoRefreshInterval === 0) return;

    const interval = setInterval(() => {
      fetchOverview(false);
    }, autoRefreshInterval);

    return () => clearInterval(interval);
  }, [autoRefreshInterval, fetchOverview]);

  // Copy IP handler
  const handleCopyIp = (ip: string) => {
    navigator.clipboard.writeText(ip);
    setCopiedIp(true);
    setTimeout(() => setCopiedIp(false), 2000);
  };

  // Copy Order ID handler
  const handleCopyOrderId = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopiedOrderId(id);
    setTimeout(() => setCopiedOrderId(null), 2000);
  };

  // Formatter helpers
  const formatUsd = (val?: number | null) => {
    if (val === undefined || val === null || isNaN(val)) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(val);
  };

  const formatCrypto = (val?: number | null, maxDec = 6) => {
    if (val === undefined || val === null || isNaN(val)) return '0.00';
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: maxDec,
    }).format(val);
  };

  const formatTime = (epochSeconds?: number | null) => {
    if (!epochSeconds) return '—';
    const date = new Date(epochSeconds * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const formatDateTime = (epochSeconds?: number | null) => {
    if (!epochSeconds) return '—';
    const date = new Date(epochSeconds * 1000);
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  // Balances summary
  const balancesList = data?.balances || [];
  const positionsList = data?.positions || [];
  const openOrdersList = data?.open_orders || [];
  const recentOrdersList = data?.recent_orders || [];

  return (
    <div className="space-y-6 select-none">
      {/* 1. Header Bar with prominent TESTNET Badge & Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 p-5 rounded-xl bg-gradient-to-r from-[#0C1019] via-[#0E1524] to-[#0A0E18] border border-white/[0.08] shadow-lg">
        <div className="flex items-start md:items-center gap-3.5">
          <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500/20 via-orange-500/10 to-amber-600/20 border border-amber-500/30 text-amber-400 shadow-glow-amber/20 shrink-0">
            <Wallet className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-white tracking-tight">Testnet Wallet & Account</h1>
              
              {/* Prominent TESTNET BADGE */}
              <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 font-mono text-xs font-bold tracking-wide animate-pulse">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                TESTNET DEMO ONLY
              </div>

              <div className="hidden sm:flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 font-mono text-[11px] font-semibold">
                <ShieldCheck className="w-3 h-3" />
                READ-ONLY
              </div>
            </div>

            <p className="text-xs text-slate-400 mt-1 font-sans">
              Real-time portfolio telemetry from Delta Exchange India Testnet. Live demo funds only; automated execution disabled.
            </p>
          </div>
        </div>

        {/* Action Controls: Refresh & Interval */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Auto Refresh Interval Selector */}
          <div className="flex items-center gap-1.5 text-xs text-slate-400 bg-white/[0.03] border border-white/[0.08] px-2.5 py-1.5 rounded-lg">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-mono">Auto:</span>
            <select
              value={autoRefreshInterval}
              onChange={(e) => setAutoRefreshInterval(Number(e.target.value) as RefreshInterval)}
              className="bg-transparent text-slate-200 text-xs font-mono outline-none cursor-pointer focus:text-cyan-400"
            >
              <option value={0} className="bg-[#0B0F17] text-slate-300">Off</option>
              <option value={10000} className="bg-[#0B0F17] text-slate-300">10s</option>
              <option value={30000} className="bg-[#0B0F17] text-slate-300">30s</option>
              <option value={60000} className="bg-[#0B0F17] text-slate-300">60s</option>
            </select>
          </div>

          {/* Manual Refresh Button */}
          <button
            onClick={() => fetchOverview(true)}
            disabled={refreshing || loading}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
              refreshing || loading
                ? 'bg-cyan-500/10 text-cyan-400/60 border border-cyan-500/20 cursor-wait'
                : 'bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 hover:border-cyan-400/50 shadow-glow-cyan/10'
            }`}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing || loading ? 'animate-spin' : ''}`} />
            <span>{refreshing ? 'Updating...' : 'Refresh'}</span>
          </button>

          {/* Last refreshed time */}
          {data?.last_updated_at && (
            <div className="text-[11px] text-slate-400 font-mono hidden md:block">
              {formatTime(data.last_updated_at)}
            </div>
          )}
        </div>
      </div>

      {/* 2. Security & Environment Banner */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 px-4 py-2.5 rounded-lg bg-white/[0.02] border border-white/[0.06] text-xs text-slate-400 font-mono">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Lock className="w-3.5 h-3.5 text-cyan-400" />
            <span className="text-slate-400">Endpoint:</span>
            <span className="text-slate-200">{data?.base_url || 'https://cdn-ind.testnet.deltaex.org'}</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">API Key:</span>
            <span className="text-slate-200">
              {data?.masked_api_key ? data.masked_api_key : 'Not Configured in .env'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {data?.authenticated ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[11px]">
              <CheckCircle2 className="w-3 h-3" />
              Authenticated & Synced
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[11px]">
              <AlertTriangle className="w-3 h-3" />
              Authentication Inactive
            </span>
          )}
        </div>
      </div>

      {/* 3. Diagnostic / IP Whitelist Guide (If Authentication Failed) */}
      {!loading && data && !data.authenticated && (
        <div className="p-4 rounded-xl bg-amber-500/[0.08] border border-amber-500/30 text-amber-200 text-xs space-y-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-2">
              <div className="font-semibold text-sm text-amber-300">
                Delta Testnet Authentication Notice
              </div>
              <p className="text-amber-200/90 leading-relaxed font-sans">
                {data.diagnostic || 'API credentials could not be verified on Delta Testnet.'}
              </p>

              {/* IP Whitelist Specific Helper */}
              {data.client_ip && (
                <div className="mt-3 p-3 rounded-lg bg-black/40 border border-amber-500/20 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-amber-300 font-semibold">
                      Detected Backend Outbound IP:
                    </span>
                    <button
                      onClick={() => handleCopyIp(data.client_ip!)}
                      className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 font-mono text-[11px] transition-colors"
                    >
                      {copiedIp ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>{copiedIp ? 'Copied IP' : 'Copy IP'}</span>
                    </button>
                  </div>

                  <div className="font-mono text-sm text-white bg-black/60 px-3 py-1.5 rounded border border-white/10 select-all">
                    {data.client_ip}
                  </div>

                  <div className="text-[11px] text-slate-300 leading-normal font-sans pt-1">
                    <strong>Resolution Steps:</strong>
                    <ol className="list-decimal list-inside space-y-1 mt-1 text-slate-300">
                      <li>Log in to <a href="https://demo.delta.exchange" target="_blank" rel="noreferrer" className="text-cyan-400 underline inline-flex items-center gap-0.5">demo.delta.exchange <ExternalLink className="w-2.5 h-2.5" /></a></li>
                      <li>Navigate to <strong>Account &rarr; API Management &rarr; Edit API Key</strong></li>
                      <li>Add <span className="font-mono text-amber-300 font-semibold">{data.client_ip}</span> to the IP Whitelist (or leave the whitelist empty for demo testing)</li>
                      <li>Save and click <strong>Refresh</strong> above.</li>
                    </ol>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 4. Top Metric Cards: Balances, Margin, and Unrealized PnL */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Balance */}
        <div className="p-4 rounded-xl bg-[#0B0F17] border border-white/[0.07] hover:border-white/[0.12] transition-colors shadow-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span className="font-medium">Total Wallet Balance</span>
            <Coins className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white tracking-tight">
            {loading ? (
              <div className="h-8 w-28 bg-white/[0.05] animate-pulse rounded" />
            ) : (
              formatUsd(data?.total_balance_usd)
            )}
          </div>
          <div className="text-[11px] text-slate-400 font-mono mt-1.5 flex items-center gap-1">
            <span>Simulated Testnet Assets</span>
          </div>
        </div>

        {/* Card 2: Available Balance */}
        <div className="p-4 rounded-xl bg-[#0B0F17] border border-white/[0.07] hover:border-white/[0.12] transition-colors shadow-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span className="font-medium">Available Margin</span>
            <Wallet className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white tracking-tight">
            {loading ? (
              <div className="h-8 w-28 bg-white/[0.05] animate-pulse rounded" />
            ) : (
              formatUsd(data?.available_balance_usd)
            )}
          </div>
          <div className="text-[11px] text-emerald-400/90 font-mono mt-1.5 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            <span>Ready for Margin</span>
          </div>
        </div>

        {/* Card 3: Margin Used */}
        <div className="p-4 rounded-xl bg-[#0B0F17] border border-white/[0.07] hover:border-white/[0.12] transition-colors shadow-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span className="font-medium">Margin Locked</span>
            <Layers className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white tracking-tight">
            {loading ? (
              <div className="h-8 w-28 bg-white/[0.05] animate-pulse rounded" />
            ) : (
              formatUsd(data?.total_margin_used_usd)
            )}
          </div>
          <div className="text-[11px] text-slate-400 font-mono mt-1.5">
            <span>Locked in Positions & Orders</span>
          </div>
        </div>

        {/* Card 4: Total Unrealized PnL */}
        <div className="p-4 rounded-xl bg-[#0B0F17] border border-white/[0.07] hover:border-white/[0.12] transition-colors shadow-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span className="font-medium">Floating Unrealized P&L</span>
            <Activity className="w-4 h-4 text-purple-400" />
          </div>
          <div className="flex items-center gap-2">
            <div
              className={`text-2xl font-bold font-mono tracking-tight ${
                (data?.total_unrealized_pnl_usd || 0) > 0
                  ? 'text-emerald-400'
                  : (data?.total_unrealized_pnl_usd || 0) < 0
                  ? 'text-rose-400'
                  : 'text-slate-300'
              }`}
            >
              {loading ? (
                <div className="h-8 w-28 bg-white/[0.05] animate-pulse rounded" />
              ) : (
                <>
                  {(data?.total_unrealized_pnl_usd || 0) > 0 ? '+' : ''}
                  {formatUsd(data?.total_unrealized_pnl_usd)}
                </>
              )}
            </div>
          </div>
          <div className="text-[11px] font-mono mt-1.5 flex items-center gap-1 text-slate-400">
            {(data?.total_unrealized_pnl_usd || 0) > 0 ? (
              <span className="text-emerald-400 flex items-center gap-0.5">
                <ArrowUpRight className="w-3 h-3" /> In Profit
              </span>
            ) : (data?.total_unrealized_pnl_usd || 0) < 0 ? (
              <span className="text-rose-400 flex items-center gap-0.5">
                <ArrowDownRight className="w-3 h-3" /> In Drawdown
              </span>
            ) : (
              <span>No Open P&L</span>
            )}
          </div>
        </div>
      </div>

      {/* 5. Sub-Tabs Bar: Balances | Positions | Active Orders | Order History */}
      <div className="bg-[#0B0F17] rounded-xl border border-white/[0.08] overflow-hidden">
        <div className="flex items-center border-b border-white/[0.08] px-4 pt-2 gap-2 overflow-x-auto">
          <button
            onClick={() => setActiveTab('balances')}
            className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'balances'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Coins className="w-3.5 h-3.5" />
            <span>Wallet Balances</span>
            <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-white/[0.06] text-slate-300">
              {balancesList.length}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('positions')}
            className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'positions'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            <span>Open Positions</span>
            <span
              className={`ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                positionsList.length > 0
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                  : 'bg-white/[0.06] text-slate-300'
              }`}
            >
              {positionsList.length}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('orders')}
            className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'orders'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Active Orders</span>
            <span
              className={`ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                openOrdersList.length > 0
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  : 'bg-white/[0.06] text-slate-300'
              }`}
            >
              {openOrdersList.length}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'history'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Order History</span>
            <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-white/[0.06] text-slate-300">
              {recentOrdersList.length}
            </span>
          </button>
        </div>

        {/* Tab 1: Wallet Balances Table */}
        {activeTab === 'balances' && (
          <div className="overflow-x-auto">
            {balancesList.length > 0 ? (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-white/[0.02] text-slate-400 border-b border-white/[0.06] uppercase text-[11px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Asset</th>
                    <th className="py-3 px-4 text-right">Total Balance</th>
                    <th className="py-3 px-4 text-right">Available for Trading</th>
                    <th className="py-3 px-4 text-right">Margin Blocked</th>
                    <th className="py-3 px-4 text-right">Estimated USD Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {balancesList.map((b) => (
                    <tr key={b.asset_id || b.asset_symbol} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-white flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 font-bold text-xs">
                          {b.asset_symbol.slice(0, 3)}
                        </div>
                        <div>
                          <div>{b.asset_symbol}</div>
                          <span className="text-[10px] text-slate-400 font-normal">ID: {b.asset_id}</span>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 text-right text-slate-200 font-medium">
                        {formatCrypto(b.balance)}
                      </td>
                      <td className="py-3.5 px-4 text-right text-emerald-400 font-medium">
                        {formatCrypto(b.available_balance)}
                      </td>
                      <td className="py-3.5 px-4 text-right text-amber-400/90 font-medium">
                        {formatCrypto(b.blocked_margin)}
                      </td>
                      <td className="py-3.5 px-4 text-right text-white font-bold">
                        {formatUsd(b.usd_value ?? b.balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="py-12 px-4 text-center">
                <Coins className="w-10 h-10 text-slate-400 mx-auto mb-2 opacity-40" />
                <p className="text-sm text-slate-300 font-medium">No Wallet Balances Reported</p>
                <p className="text-xs text-slate-400 max-w-md mx-auto mt-1 font-sans">
                  {data?.authenticated
                    ? 'No demo assets currently held in this testnet account. Request testnet funds on demo.delta.exchange faucet if available.'
                    : 'Configure your Delta Testnet API Key and Secret in backend/.env to view authenticated wallet balances.'}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Open Positions Table */}
        {activeTab === 'positions' && (
          <div className="overflow-x-auto">
            {positionsList.length > 0 ? (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-white/[0.02] text-slate-400 border-b border-white/[0.06] uppercase text-[11px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Symbol</th>
                    <th className="py-3 px-4">Side</th>
                    <th className="py-3 px-4 text-right">Size (Contracts)</th>
                    <th className="py-3 px-4 text-right">Entry Price</th>
                    <th className="py-3 px-4 text-right">Mark Price</th>
                    <th className="py-3 px-4 text-right">Liq. Price</th>
                    <th className="py-3 px-4 text-right">Margin</th>
                    <th className="py-3 px-4 text-right">Leverage</th>
                    <th className="py-3 px-4 text-right">Unrealized P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {positionsList.map((pos) => {
                    const isLong = pos.side === 'LONG';
                    const isProfitable = pos.unrealized_pnl >= 0;
                    return (
                      <tr
                        key={`${pos.product_id}-${pos.symbol}`}
                        className="hover:bg-white/[0.02] transition-colors cursor-pointer"
                        onClick={() => onSelectSymbol && onSelectSymbol(pos.symbol)}
                        title="Click to view chart for this symbol"
                      >
                        <td className="py-3.5 px-4 font-semibold text-white flex items-center gap-1.5">
                          <span>{pos.symbol}</span>
                          <span className="text-[10px] text-slate-400 font-normal">#{pos.product_id}</span>
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                              isLong
                                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                            }`}
                          >
                            {pos.side}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-200">
                          {formatCrypto(pos.size, 4)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-300">
                          {formatUsd(pos.entry_price)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-cyan-300 font-semibold">
                          {formatUsd(pos.mark_price)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-amber-400/90">
                          {pos.liquidation_price ? formatUsd(pos.liquidation_price) : '—'}
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-300">
                          {formatUsd(pos.margin)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-400">
                          {pos.leverage ? `${pos.leverage}x` : '—'}
                        </td>
                        <td className="py-3.5 px-4 text-right font-bold">
                          <span
                            className={
                              isProfitable
                                ? 'text-emerald-400'
                                : 'text-rose-400'
                            }
                          >
                            {isProfitable ? '+' : ''}
                            {formatUsd(pos.unrealized_pnl)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-12 px-4 text-center">
                <Activity className="w-10 h-10 text-slate-400 mx-auto mb-2 opacity-40" />
                <p className="text-sm text-slate-300 font-medium">No Active Open Positions</p>
                <p className="text-xs text-slate-400 max-w-md mx-auto mt-1 font-sans">
                  There are currently no open positions on Delta Testnet.
                  Automated strategy order execution remains disabled for testing safety.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Active Orders Table */}
        {activeTab === 'orders' && (
          <div className="overflow-x-auto">
            {openOrdersList.length > 0 ? (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-white/[0.02] text-slate-400 border-b border-white/[0.06] uppercase text-[11px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Order ID</th>
                    <th className="py-3 px-4">Symbol</th>
                    <th className="py-3 px-4">Side</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4 text-right">Size</th>
                    <th className="py-3 px-4 text-right">Unfilled</th>
                    <th className="py-3 px-4 text-right">Price</th>
                    <th className="py-3 px-4">State</th>
                    <th className="py-3 px-4 text-right">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {openOrdersList.map((ord) => {
                    const isBuy = ord.side === 'BUY';
                    return (
                      <tr key={ord.order_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3.5 px-4 font-mono text-slate-400 flex items-center gap-1.5">
                          <span>{ord.order_id.slice(0, 8)}...</span>
                          <button
                            onClick={() => handleCopyOrderId(ord.order_id)}
                            className="text-slate-400 hover:text-white"
                            title="Copy Order ID"
                          >
                            {copiedOrderId === ord.order_id ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                          </button>
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-white">
                          {ord.symbol}
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                              isBuy
                                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                            }`}
                          >
                            {ord.side}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-slate-300">
                          {ord.order_type.replace(/_/g, ' ')}
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-200">
                          {formatCrypto(ord.size)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-amber-400/90">
                          {formatCrypto(ord.unfilled_size)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-cyan-300 font-semibold">
                          {ord.limit_price ? formatUsd(ord.limit_price) : 'Market'}
                        </td>
                        <td className="py-3.5 px-4">
                          <span className="px-2 py-0.5 rounded text-[10px] bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold uppercase">
                            {ord.state}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-400">
                          {formatDateTime(ord.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-12 px-4 text-center">
                <Clock className="w-10 h-10 text-slate-400 mx-auto mb-2 opacity-40" />
                <p className="text-sm text-slate-300 font-medium">No Active Orders Pending</p>
                <p className="text-xs text-slate-400 max-w-md mx-auto mt-1 font-sans">
                  The testnet order book has no pending limit or stop orders for your account.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Order History Table */}
        {activeTab === 'history' && (
          <div className="overflow-x-auto">
            {recentOrdersList.length > 0 ? (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-white/[0.02] text-slate-400 border-b border-white/[0.06] uppercase text-[11px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Order ID</th>
                    <th className="py-3 px-4">Symbol</th>
                    <th className="py-3 px-4">Side</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4 text-right">Size</th>
                    <th className="py-3 px-4 text-right">Avg Fill Price</th>
                    <th className="py-3 px-4">Final State</th>
                    <th className="py-3 px-4 text-right">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {recentOrdersList.map((ord) => {
                    const isBuy = ord.side === 'BUY';
                    const isFilled = ord.state === 'filled' || ord.state === 'closed';
                    const isCancelled = ord.state === 'cancelled';
                    return (
                      <tr key={ord.order_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3.5 px-4 font-mono text-slate-400 flex items-center gap-1.5">
                          <span>{ord.order_id.slice(0, 8)}...</span>
                          <button
                            onClick={() => handleCopyOrderId(ord.order_id)}
                            className="text-slate-400 hover:text-white"
                            title="Copy Order ID"
                          >
                            {copiedOrderId === ord.order_id ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                          </button>
                        </td>
                        <td className="py-3.5 px-4 font-semibold text-white">
                          {ord.symbol}
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                              isBuy
                                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                            }`}
                          >
                            {ord.side}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-slate-300">
                          {ord.order_type.replace(/_/g, ' ')}
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-200">
                          {formatCrypto(ord.size)}
                        </td>
                        <td className="py-3.5 px-4 text-right text-cyan-300 font-semibold">
                          {ord.average_fill_price ? formatUsd(ord.average_fill_price) : '—'}
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isFilled
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : isCancelled
                                ? 'bg-slate-500/20 text-slate-400 border border-slate-500/30'
                                : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                            }`}
                          >
                            {ord.state}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-right text-slate-400">
                          {formatDateTime(ord.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-12 px-4 text-center">
                <FileText className="w-10 h-10 text-slate-400 mx-auto mb-2 opacity-40" />
                <p className="text-sm text-slate-300 font-medium">No Recent Order History</p>
                <p className="text-xs text-slate-400 max-w-md mx-auto mt-1 font-sans">
                  No past trades or closed orders have been recorded in the recent testnet history.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 6. Execution Safety & Compliance Callout */}
      <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] text-xs text-slate-400 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 font-sans">
        <div className="flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-semibold text-slate-200">
              Execution Safety Guardrails Active
            </div>
            <p className="text-slate-400 leading-relaxed">
              {data?.disclaimer ||
                'TESTNET NOTICE: All balances, positions, and orders displayed are simulated demo funds on Delta Exchange India Testnet. Real money is not involved. Automated strategy execution is disabled.'}
            </p>
          </div>
        </div>

        <a
          href="https://demo.delta.exchange"
          target="_blank"
          rel="noreferrer"
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 hover:text-white border border-white/[0.08] font-mono text-[11px] transition-colors"
        >
          <span>Delta Testnet Portal</span>
          <ExternalLink className="w-3.5 h-3.5 text-cyan-400" />
        </a>
      </div>
    </div>
  );
};
