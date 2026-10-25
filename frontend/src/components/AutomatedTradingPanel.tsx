import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Play,
  Pause,
  Square,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  Sliders,
  DollarSign,
  Activity,
  Zap,
  Lock,
  Layers,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Info,
  Check,
  AlertCircle,
} from 'lucide-react';
import {
  getAutomationStatus,
  getAutomationConfig,
  updateAutomationConfig,
  validateAutomationConfig,
  enableAutomation,
  stopAutomation,
  pauseAutomation,
  resumeAutomation,
  listAutomationSignals,
  reconcileAutomationPosition,
  engageKillSwitch,
} from '../services/api';
import type {
  AutomationConfigData,
  AutomationStatusResponseData,
  AutomatedSignalData,
  PositionStateRecordData,
  TradingStatusData,
} from '../types/market';

interface AutomatedTradingPanelProps {
  onSelectSymbol?: (symbol: string) => void;
  tradingStatus?: TradingStatusData | null;
  onRefreshParent?: () => void;
}

export const AutomatedTradingPanel: React.FC<AutomatedTradingPanelProps> = ({
  onSelectSymbol,
  tradingStatus,
  onRefreshParent,
}) => {
  const [status, setStatus] = useState<AutomationStatusResponseData | null>(null);
  const [config, setConfig] = useState<AutomationConfigData | null>(null);
  const [signals, setSignals] = useState<AutomatedSignalData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Lifecycle & concurrency guards
  const isMountedRef = useRef<boolean>(true);
  const inFlightRef = useRef<boolean>(false);
  const activeAbortControllerRef = useRef<AbortController | null>(null);

  // Enable Confirmation Modal State
  const [showEnableModal, setShowEnableModal] = useState<boolean>(false);
  const [enableConfirmed, setEnableConfirmed] = useState<boolean>(false);
  const [enabling, setEnabling] = useState<boolean>(false);

  // Config Editing State
  const [isEditingConfig, setIsEditingConfig] = useState<boolean>(false);
  const [configForm, setConfigForm] = useState<AutomationConfigData | null>(null);
  const [validatingConfig, setValidatingConfig] = useState<boolean>(false);
  const [savingConfig, setSavingConfig] = useState<boolean>(false);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; reasons: string[] } | null>(null);

  // Action states
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [reconciling, setReconciling] = useState<boolean>(false);

  const fetchAutomationData = useCallback(async (isManual: boolean = false) => {
    // Prevent overlapping background polls
    if (inFlightRef.current && !isManual) {
      return;
    }

    // When manual refresh is explicitly requested, abort any in-flight request and re-query
    if (inFlightRef.current && isManual && activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort('New manual refresh requested');
    }

    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    inFlightRef.current = true;

    if (isManual) setRefreshing(true);

    try {
      const [statusRes, configRes, signalsRes] = await Promise.all([
        getAutomationStatus({ signal: abortController.signal }),
        getAutomationConfig({ signal: abortController.signal }),
        listAutomationSignals(20, { signal: abortController.signal }).catch((err: unknown) => {
          if (
            (err instanceof DOMException && (err.name === 'AbortError' || err.code === 20)) ||
            (err instanceof Error && (err.name === 'AbortError' || err.message.toLowerCase().includes('abort')))
          ) {
            throw err;
          }
          return [];
        }),
      ]);

      if (!isMountedRef.current) return;

      setStatus(statusRes);
      setConfig(configRes);
      if (!isEditingConfig) {
        setConfigForm(configRes);
      }
      setSignals(signalsRes);
      setError(null);
    } catch (err: unknown) {
      if (!isMountedRef.current) return;

      const isAbort =
        (err instanceof DOMException && (err.name === 'AbortError' || err.code === 20)) ||
        (err instanceof Error && (err.name === 'AbortError' || err.message.toLowerCase().includes('abort')));

      // Ignore expected cancellations (unmount, new poll replacement)
      if (isAbort) {
        return;
      }

      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to retrieve automation telemetry: ${msg}`);
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
      inFlightRef.current = false;
    }
  }, [isEditingConfig]);

  useEffect(() => {
    isMountedRef.current = true;
    fetchAutomationData();
    const interval = setInterval(() => {
      fetchAutomationData(false);
    }, 10000);
    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
      if (activeAbortControllerRef.current) {
        activeAbortControllerRef.current.abort('Component unmounted');
      }
    };
  }, [fetchAutomationData]);

  // Handle explicit enable
  const handleEnableAutomation = async () => {
    if (!enableConfirmed) {
      setError('Please check the confirmation box before enabling automation.');
      return;
    }
    setEnabling(true);
    setError(null);
    try {
      const updated = await enableAutomation(
        true,
        'Explicit operator confirmation via Automated Trading Panel'
      );
      setStatus(updated);
      setShowEnableModal(false);
      setEnableConfirmed(false);
      setSuccessMsg('Automated trading ENABLED on Delta Exchange Testnet.');
      setTimeout(() => setSuccessMsg(null), 6000);
      fetchAutomationData(false);
      if (onRefreshParent) onRefreshParent();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Activation failed: ${msg}`);
    } finally {
      setEnabling(false);
    }
  };

  // Handle stop
  const handleStopAutomation = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const updated = await stopAutomation();
      setStatus(updated);
      setSuccessMsg('Automated trading engine STOPPED.');
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchAutomationData(false);
      if (onRefreshParent) onRefreshParent();
    } catch (err: unknown) {
      setError(`Stop failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Handle pause
  const handlePauseAutomation = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const updated = await pauseAutomation('Manual pause from dashboard');
      setStatus(updated);
      setSuccessMsg('New automated entries PAUSED. Active positions remain protected.');
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchAutomationData(false);
    } catch (err: unknown) {
      setError(`Pause failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Handle resume
  const handleResumeAutomation = async () => {
    setActionLoading(true);
    setError(null);
    try {
      const updated = await resumeAutomation();
      setStatus(updated);
      setSuccessMsg('Automated trading engine RESUMED.');
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchAutomationData(false);
    } catch (err: unknown) {
      setError(`Resume failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Handle manual position reconciliation
  const handleReconcile = async () => {
    if (!config?.trading_symbol) return;
    setReconciling(true);
    setError(null);
    try {
      await reconcileAutomationPosition(config.trading_symbol);
      setSuccessMsg(`Position for ${config.trading_symbol} reconciled with exchange.`);
      setTimeout(() => setSuccessMsg(null), 4000);
      fetchAutomationData(false);
    } catch (err: unknown) {
      setError(`Reconciliation failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setReconciling(false);
    }
  };

  // Handle validate config
  const handleValidateConfig = async () => {
    if (!configForm) return;
    setValidatingConfig(true);
    setError(null);
    try {
      const res = await validateAutomationConfig(configForm);
      setValidationResult(res);
      if (res.valid) {
        setSuccessMsg('Configuration is VALID according to risk and exchange parameters.');
        setTimeout(() => setSuccessMsg(null), 4000);
      }
    } catch (err: unknown) {
      setError(`Validation failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setValidatingConfig(false);
    }
  };

  // Handle save config
  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!configForm) return;
    setSavingConfig(true);
    setError(null);
    try {
      const updated = await updateAutomationConfig(configForm);
      setConfig(updated);
      setConfigForm(updated);
      setIsEditingConfig(false);
      setSuccessMsg('Automation configuration updated and safely persisted.');
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchAutomationData(false);
    } catch (err: unknown) {
      setError(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSavingConfig(false);
    }
  };

  if (loading && !status) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[350px] text-slate-400 gap-3">
        <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
        <span className="font-mono text-sm">Loading Automated Trading Engine Telemetry...</span>
      </div>
    );
  }

  const isRunning = status?.state === 'RUNNING';
  const isPaused = status?.state === 'PAUSED' || status?.is_paused;
  const isHalted = status?.state === 'HALTED' || status?.kill_switch_engaged;
  const isOff = status?.state === 'OFF' || !status?.enabled;

  const activePos = status?.active_position;
  const isPositionOpen = Boolean(activePos && activePos.lifecycle_state !== 'FLAT' && activePos.quantity > 0);

  // Field mappings with strict fallback resolution (never fabricate or substitute production host)
  const displayHost = status?.verified_host || (tradingStatus?.base_url ? new URL(tradingStatus.base_url).hostname : 'cdn-ind.testnet.deltaex.org');
  const displayStrategy = config?.selected_strategy || status?.config?.selected_strategy || 'ema_crossover';
  const displaySymbol = config?.trading_symbol || status?.config?.trading_symbol || 'BTCUSD';
  const displayInterval = config?.candle_interval || status?.config?.candle_interval || '1h';
  const ordersSubmittedToday = status?.orders_submitted_today ?? tradingStatus?.orders_submitted_today ?? 0;
  const maxOrdersPerDay = config?.maximum_orders_per_day ?? status?.config?.maximum_orders_per_day ?? 20;

  return (
    <div className="flex flex-col gap-6">
      {/* Alert Notifications */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between gap-3 animate-fadeIn">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchAutomationData(true)}
              disabled={refreshing}
              className="px-2.5 py-1 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs font-mono font-medium transition"
            >
              Retry
            </button>
            <button onClick={() => setError(null)} className="text-slate-400 hover:text-white text-base">
              ×
            </button>
          </div>
        </div>
      )}

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between gap-3 animate-fadeIn">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-slate-400 hover:text-white text-base">
            ×
          </button>
        </div>
      )}

      {/* Main Automation Engine Master Card */}
      <div
        className={`relative overflow-hidden rounded-2xl border p-6 backdrop-blur-md shadow-2xl transition-all ${isRunning
            ? 'bg-gradient-to-r from-emerald-950/40 via-cyan-950/20 to-slate-900/70 border-emerald-500/40'
            : isPaused
              ? 'bg-gradient-to-r from-amber-950/40 via-yellow-950/20 to-slate-900/70 border-amber-500/40'
              : isHalted
                ? 'bg-gradient-to-r from-rose-950/40 via-red-950/20 to-slate-900/70 border-rose-500/40'
                : 'bg-gradient-to-r from-slate-900/80 via-slate-900/40 to-slate-950/80 border-white/[0.08]'
          }`}
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
          <div className="flex items-start gap-4">
            <div
              className={`p-3.5 rounded-2xl border shadow-lg ${isRunning
                  ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-emerald-950/50'
                  : isPaused
                    ? 'bg-amber-500/10 border-amber-500/40 text-amber-400 shadow-amber-950/50'
                    : isHalted
                      ? 'bg-rose-500/10 border-rose-500/40 text-rose-400 shadow-rose-950/50'
                      : 'bg-slate-800/50 border-white/10 text-slate-400'
                }`}
            >
              <Zap className={`w-8 h-8 ${isRunning ? 'animate-pulse' : ''}`} />
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-3 flex-wrap">
                <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                  Automated Trading Engine
                </h2>
                <span
                  className={`text-xs px-2.5 py-1 rounded-full font-mono font-bold tracking-wider uppercase border ${isRunning
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                      : isPaused
                        ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                        : isHalted
                          ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                          : 'bg-slate-700/50 text-slate-300 border-slate-600'
                    }`}
                >
                  {status?.state || 'OFF'}
                </span>
                <span className="text-xs px-2.5 py-1 rounded-full font-mono font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                  TESTNET ONLY
                </span>
                <span className="text-xs px-2.5 py-1 rounded-full font-mono text-slate-300 bg-white/5 border border-white/10">
                  {displaySymbol} • {displayInterval}
                </span>
              </div>

              <p className="text-sm text-slate-300 max-w-2xl leading-relaxed">
                {isRunning
                  ? 'Active background strategy evaluation running. Evaluates finalized candles, runs mandatory risk checks, and submits verified testnet orders.'
                  : isPaused
                    ? `New automated entries are PAUSED: ${status?.pause_reason || 'Manual operator pause'}. Active positions and protective stops remain continuously monitored.`
                    : isHalted
                      ? `AUTOMATION HALTED: ${status?.pause_reason || 'Kill switch engaged or safety violation'}.`
                      : 'Automation is currently OFF. Starts disabled by default. Requires explicit operator activation.'}
              </p>

              <div className="text-xs text-slate-400 font-mono mt-1 flex items-center gap-3 flex-wrap">
                <span className="flex items-center gap-1">
                  <Lock className="w-3 h-3 text-cyan-400" /> Host:{' '}
                  <span className="text-cyan-300 font-bold">{displayHost}</span>
                </span>
                <span>• Strategy: <span className="text-white font-bold">{displayStrategy}</span></span>
                <span>• Wallet: <span className="text-cyan-300 font-bold">${(status?.wallet_balance_usd ?? 200).toFixed(2)}</span></span>
                {status?.worker_heartbeat_at ? (
                  <span>• Heartbeat: <span className="text-emerald-400 font-bold">{new Date(status.worker_heartbeat_at * 1000).toLocaleTimeString()}</span></span>
                ) : null}
                {status?.worker_uptime_seconds ? (
                  <span>• Uptime: <span className="text-emerald-400 font-bold">{Math.floor(status.worker_uptime_seconds / 60)}m {status.worker_uptime_seconds % 60}s</span></span>
                ) : null}
              </div>
            </div>
          </div>

          {/* Engine Controls */}
          <div className="flex items-center gap-3 shrink-0 flex-wrap">
            <button
              onClick={() => fetchAutomationData(true)}
              disabled={refreshing}
              className="p-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-slate-300 text-xs font-medium transition"
              title="Refresh telemetry"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-cyan-400' : ''}`} />
            </button>

            {isOff && (
              <button
                onClick={() => setShowEnableModal(true)}
                disabled={actionLoading || isHalted}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 text-xs font-bold font-mono tracking-wider flex items-center gap-2 shadow-lg shadow-emerald-950/40 transition disabled:opacity-50"
              >
                <Play className="w-4 h-4 fill-slate-950" />
                <span>ENABLE AUTOMATION</span>
              </button>
            )}

            {isRunning && (
              <>
                <button
                  onClick={handlePauseAutomation}
                  disabled={actionLoading}
                  className="px-4 py-2.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 text-xs font-bold font-mono flex items-center gap-2 transition"
                >
                  <Pause className="w-4 h-4" />
                  <span>PAUSE ENTRIES</span>
                </button>
                <button
                  onClick={handleStopAutomation}
                  disabled={actionLoading}
                  className="px-4 py-2.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-rose-300 text-xs font-bold font-mono flex items-center gap-2 transition"
                >
                  <Square className="w-4 h-4" />
                  <span>STOP</span>
                </button>
              </>
            )}

            {isPaused && (
              <>
                <button
                  onClick={handleResumeAutomation}
                  disabled={actionLoading || isHalted}
                  className="px-4 py-2.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 text-xs font-bold font-mono flex items-center gap-2 transition disabled:opacity-50"
                >
                  <Play className="w-4 h-4" />
                  <span>RESUME</span>
                </button>
                <button
                  onClick={handleStopAutomation}
                  disabled={actionLoading}
                  className="px-4 py-2.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-rose-300 text-xs font-bold font-mono flex items-center gap-2 transition"
                >
                  <Square className="w-4 h-4" />
                  <span>STOP</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Grid: Position Status, Protective Orders, and Realized Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Metric 0: Testnet Wallet Balance & Margin */}
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Testnet Wallet</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
              USD
            </span>
          </div>
          <span className="text-xl font-bold font-mono text-white">
            ${(status?.wallet_balance_usd ?? 200).toFixed(2)} USD
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            Avail Margin: ${(status?.available_margin_usd ?? 200).toFixed(2)} • Equity: ${(status?.account_equity_usd ?? status?.wallet_balance_usd ?? 200).toFixed(2)}
          </span>
        </div>

        {/* Metric 1: Current Position */}
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Managed Position</span>
            <button
              onClick={handleReconcile}
              disabled={reconciling}
              className="text-[10px] text-cyan-400 hover:underline flex items-center gap-1"
              title="Reconcile with exchange"
            >
              <RefreshCw className={`w-3 h-3 ${reconciling ? 'animate-spin' : ''}`} />
              Reconcile
            </button>
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-xl font-bold font-mono ${isPositionOpen
                  ? activePos?.side === 'LONG'
                    ? 'text-emerald-400'
                    : 'text-rose-400'
                  : 'text-slate-400'
                }`}
            >
              {isPositionOpen ? `${activePos?.side} ${activePos?.quantity} contracts` : 'FLAT'}
            </span>
          </div>
          <span className="text-[11px] text-slate-400 font-mono">
            {isPositionOpen
              ? `Avg Entry: $${activePos?.average_entry_price.toLocaleString()} • Notional: ~$${(
                (activePos?.quantity || 0) * (activePos?.average_entry_price || 0) * 0.001
              ).toFixed(2)}`
              : 'No open automated exposure'}
          </span>
        </div>

        {/* Metric 2: Protective Orders */}
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-2">
          <div className="flex items-center justify-between text-slate-400 text-xs">
            <span>Protective Stop-Loss</span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ${
                !isPositionOpen
                  ? 'bg-slate-800 text-slate-400 border border-slate-700/60'
                  : activePos?.protection_verified
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              }`}
            >
              {!isPositionOpen ? 'FLAT (N/A)' : activePos?.protection_verified ? 'VERIFIED' : 'UNVERIFIED'}
            </span>
          </div>
          <span className="text-xl font-bold font-mono text-white">
            {!isPositionOpen ? '—' : activePos?.stop_loss_price ? `$${activePos.stop_loss_price.toLocaleString()}` : '—'}
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            {!isPositionOpen
              ? 'No active position. Protective stop attaches automatically upon entry fill.'
              : activePos?.stop_loss_order_id
              ? `Order ID: ${activePos.stop_loss_order_id}`
              : activePos?.protection_verified
              ? 'Active exchange protection'
              : 'Stop-loss order pending verification'}
          </span>
        </div>

        {/* Metric 3: Orders & Trades Today */}
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-2">
          <div className="text-slate-400 text-xs">Daily Execution Counter</div>
          <span className="text-xl font-bold font-mono text-cyan-400">
            {ordersSubmittedToday} / {maxOrdersPerDay} orders
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            Max trades per day: {config?.maximum_trades_per_day ?? status?.config?.maximum_trades_per_day ?? 20}
          </span>
        </div>

        {/* Metric 4: Realized P&L */}
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-2">
          <div className="text-slate-400 text-xs">Daily Realized Loss</div>
          <span
            className={`text-xl font-bold font-mono ${(status?.daily_realized_pnl_usd ?? 0) < 0 ? 'text-rose-400' : 'text-emerald-400'
              }`}
          >
            ${(status?.daily_realized_pnl_usd ?? 0).toFixed(2)} USD
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            Daily loss cap: ${(config?.maximum_daily_realized_loss ?? 4).toLocaleString()} USD
          </span>
        </div>
      </div>

      {/* Contract Specification & Conservative Sizing Notice */}
      {Number(config?.maximum_order_notional ?? 20) < 85 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-3">
          <AlertCircle className="w-5 h-5 shrink-0 text-amber-400 mt-0.5" />
          <div className="flex flex-col gap-1">
            <span className="font-bold font-mono text-amber-300">
              Conservative Sizing Guard: 1 BTCUSD Contract (~$80 USD) exceeds $20 Max Notional Limit
            </span>
            <p className="text-slate-300 leading-relaxed">
              Delta Exchange India Testnet enforces a minimum trade size of <strong>1 contract</strong> (0.001 BTC = ~$80.24 USD notional at current price).
              With your conservative limit of <strong>${Number(config?.maximum_order_notional ?? 20).toFixed(2)} USD</strong>, new entry signals will be rejected by the Risk Engine and Position Sizer as exceeding notional bounds.
              To allow 1 contract to be traded automatically, update Maximum Order Notional to at least <strong>$85.00 USD</strong>.
            </p>
          </div>
        </div>
      )}

      {/* Main Section: Left = Strategy & Position Sizing Configuration, Right = Latest Signal & Audit Log */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Configuration Form */}
        <div className="lg:col-span-5 flex flex-col gap-4">
          <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <div className="flex items-center gap-2">
                <Sliders className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-semibold text-white">Automation Strategy & Sizing Config</h3>
              </div>
              <button
                onClick={() => setIsEditingConfig(!isEditingConfig)}
                className="text-xs text-cyan-400 hover:text-cyan-300 font-mono"
              >
                {isEditingConfig ? 'Cancel' : 'Edit Config'}
              </button>
            </div>

            {configForm && (
              <form onSubmit={handleSaveConfig} className="flex flex-col gap-3 text-xs">
                <div>
                  <label className="text-slate-400 block mb-1">Trading Contract Symbol</label>
                  <select
                    disabled={!isEditingConfig}
                    value={configForm.trading_symbol}
                    onChange={(e) => setConfigForm({ ...configForm, trading_symbol: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                  >
                    <option value="BTCUSD">BTCUSD (Delta India Testnet)</option>
                    <option value="ETHUSD">ETHUSD (Delta India Testnet)</option>
                    <option value="SOLUSD">SOLUSD (Delta India Testnet)</option>
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Candle Interval</label>
                    <select
                      disabled={!isEditingConfig}
                      value={configForm.candle_interval}
                      onChange={(e) => setConfigForm({ ...configForm, candle_interval: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    >
                      <option value="1m">1m</option>
                      <option value="5m">5m</option>
                      <option value="15m">15m</option>
                      <option value="1h">1h</option>
                      <option value="1d">1d</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-slate-400 block mb-1">Position Sizing Mode</label>
                    <select
                      disabled={!isEditingConfig}
                      value={configForm.position_sizing_mode}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, position_sizing_mode: e.target.value as any })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    >
                      <option value="fixed_contracts">Fixed Contracts</option>
                      <option value="fixed_notional">Fixed Notional ($)</option>
                      <option value="risk_budget">Risk Budget ($)</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Order Quantity / Target</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      disabled={!isEditingConfig}
                      value={configForm.fixed_contract_quantity}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          fixed_contract_quantity: parseFloat(e.target.value) || 1,
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 block mb-1">Max Order Notional ($)</label>
                    <input
                      type="number"
                      step="50"
                      min="10"
                      disabled={!isEditingConfig}
                      value={configForm.maximum_order_notional}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          maximum_order_notional: parseFloat(e.target.value) || 500,
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Stop-Loss (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.5"
                      max="20"
                      disabled={!isEditingConfig}
                      value={configForm.protective_stop_loss_percentage}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          protective_stop_loss_percentage: parseFloat(e.target.value) || 1.5,
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 block mb-1">Take-Profit (%)</label>
                    <input
                      type="number"
                      step="0.5"
                      min="0.5"
                      disabled={!isEditingConfig}
                      value={configForm.take_profit_percentage || ''}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          take_profit_percentage: e.target.value ? parseFloat(e.target.value) : null,
                        })
                      }
                      placeholder="Optional"
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Max Position (contracts)</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      disabled={!isEditingConfig}
                      value={configForm.maximum_position_size}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          maximum_position_size: parseFloat(e.target.value) || 10,
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 block mb-1">Trade Cooldown (sec)</label>
                    <input
                      type="number"
                      step="30"
                      min="10"
                      disabled={!isEditingConfig}
                      value={configForm.cooldown_period_seconds}
                      onChange={(e) =>
                        setConfigForm({
                          ...configForm,
                          cooldown_period_seconds: parseInt(e.target.value, 10) || 300,
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-60"
                    />
                  </div>
                </div>

                <div className="pt-2 flex flex-col gap-1.5 border-t border-white/[0.06]">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      disabled={!isEditingConfig}
                      checked={configForm.allow_long}
                      onChange={(e) => setConfigForm({ ...configForm, allow_long: e.target.checked })}
                      className="rounded bg-black/40 border-white/20 text-cyan-500 focus:ring-0"
                    />
                    <span className="text-slate-300">Allow Long Entries (BUY)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      disabled={!isEditingConfig}
                      checked={configForm.allow_short}
                      onChange={(e) => setConfigForm({ ...configForm, allow_short: e.target.checked })}
                      className="rounded bg-black/40 border-white/20 text-cyan-500 focus:ring-0"
                    />
                    <span className="text-slate-300">Allow Short Entries (SELL)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      disabled={!isEditingConfig}
                      checked={configForm.require_confirmed_candle}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, require_confirmed_candle: e.target.checked })
                      }
                      className="rounded bg-black/40 border-white/20 text-cyan-500 focus:ring-0"
                    />
                    <span className="text-slate-300">Require Confirmed Candle Close</span>
                  </label>
                </div>

                {isEditingConfig && (
                  <div className="flex items-center gap-2 pt-3">
                    <button
                      type="button"
                      onClick={handleValidateConfig}
                      disabled={validatingConfig}
                      className="flex-1 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-mono font-medium transition"
                    >
                      {validatingConfig ? 'Validating...' : 'Validate'}
                    </button>
                    <button
                      type="submit"
                      disabled={savingConfig}
                      className="flex-1 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold font-mono transition"
                    >
                      {savingConfig ? 'Saving...' : 'Save Configuration'}
                    </button>
                  </div>
                )}
              </form>
            )}
          </div>
        </div>

        {/* Right: Latest Signal & Signal History Audit Log */}
        <div className="lg:col-span-7 flex flex-col gap-4">
          {/* Latest Signal Card */}
          <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-3">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-semibold text-white">Latest Quantitative Strategy Signal</h3>
              </div>
              <span className="text-[11px] text-slate-400 font-mono">
                Strategy: {config?.selected_strategy}
              </span>
            </div>

            {status?.latest_signal ? (
              <div className="flex flex-col gap-3 text-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2.5 py-1 rounded font-bold font-mono ${status.latest_signal.signal_direction.includes('BUY')
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                        }`}
                    >
                      {status.latest_signal.signal_direction}
                    </span>
                    <span className="font-mono text-slate-300">{status.latest_signal.position_intent}</span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded font-mono text-[10px] ${status.latest_signal.lifecycle_state === 'FILLED'
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : status.latest_signal.lifecycle_state === 'REJECTED'
                          ? 'bg-rose-500/20 text-rose-300'
                          : 'bg-cyan-500/20 text-cyan-300'
                      }`}
                  >
                    {status.latest_signal.lifecycle_state}
                  </span>
                </div>

                <p className="text-slate-300 leading-relaxed bg-white/[0.02] p-2.5 rounded-lg border border-white/[0.04]">
                  {status.latest_signal.entry_rationale}
                </p>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono text-[11px] text-slate-400">
                  <div>
                    Price: <span className="text-white">${status.latest_signal.intended_price.toLocaleString()}</span>
                  </div>
                  <div>
                    Qty: <span className="text-white">{status.latest_signal.intended_quantity} contracts</span>
                  </div>
                  <div>
                    Stop: <span className="text-rose-400">${status.latest_signal.stop_loss_price || '—'}</span>
                  </div>
                  <div>
                    Time: <span className="text-white">{new Date(status.latest_signal.created_at * 1000).toLocaleTimeString()}</span>
                  </div>
                </div>

                {status.latest_signal.rejection_reason && (
                  <div className="text-[11px] text-rose-400 bg-rose-500/10 p-2 rounded border border-rose-500/20">
                    Rejection: {status.latest_signal.rejection_reason}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-slate-400 text-xs py-4 text-center font-mono">
                No signal evaluated in current session yet. Evaluates on completed candle close.
              </div>
            )}
          </div>

          {/* Signal Audit Log Table */}
          <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-3">
            <h3 className="text-sm font-semibold text-white">Signal Lifecycle Audit Log</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="text-[11px] text-slate-400 border-b border-white/[0.06]">
                  <tr>
                    <th className="pb-2">Time</th>
                    <th className="pb-2">Direction</th>
                    <th className="pb-2">Intent</th>
                    <th className="pb-2">Price</th>
                    <th className="pb-2">Qty</th>
                    <th className="pb-2">Lifecycle State</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04] text-slate-300">
                  {signals.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-4 text-center text-slate-500">
                        No automated signals recorded yet.
                      </td>
                    </tr>
                  ) : (
                    signals.map((sig) => (
                      <tr key={sig.signal_id} className="hover:bg-white/[0.02]">
                        <td className="py-2 text-slate-400">
                          {new Date(sig.created_at * 1000).toLocaleTimeString()}
                        </td>
                        <td
                          className={`py-2 font-bold ${sig.signal_direction.includes('BUY') ? 'text-emerald-400' : 'text-rose-400'
                            }`}
                        >
                          {sig.signal_direction}
                        </td>
                        <td className="py-2 text-slate-400">{sig.position_intent}</td>
                        <td className="py-2">${sig.intended_price.toLocaleString()}</td>
                        <td className="py-2">{sig.intended_quantity}</td>
                        <td className="py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] ${sig.lifecycle_state === 'FILLED'
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : sig.lifecycle_state === 'REJECTED'
                                  ? 'bg-rose-500/20 text-rose-300'
                                  : 'bg-cyan-500/20 text-cyan-300'
                              }`}
                          >
                            {sig.lifecycle_state}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {/* Explicit Enable Confirmation Dialog Modal */}
      {showEnableModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
          <div className="bg-[#0B0F17] border border-cyan-500/30 rounded-2xl max-w-lg w-full p-6 shadow-2xl flex flex-col gap-4">
            <div className="flex items-center gap-3 pb-3 border-b border-white/[0.08]">
              <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Enable Automated Testnet Trading</h3>
                <span className="text-[11px] font-mono text-cyan-400">Delta Exchange India Testnet Only</span>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              You are about to activate live automated order execution. The background runner will continuously
              evaluate completed candles, apply pre-trade risk checks, and submit orders directly to Delta Exchange Testnet.
            </p>

            <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.06] flex flex-col gap-2 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-slate-400">Selected Strategy:</span>
                <span className="text-white font-bold">{displayStrategy}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Contract & Resolution:</span>
                <span className="text-white font-bold">{displaySymbol} ({displayInterval})</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Max Order Notional:</span>
                <span className="text-cyan-400 font-bold">${config?.maximum_order_notional ?? status?.config?.maximum_order_notional ?? 500} USD</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Max Position Size:</span>
                <span className="text-cyan-400 font-bold">{config?.maximum_position_size} contracts</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Max Daily Realized Loss:</span>
                <span className="text-rose-400 font-bold">${config?.maximum_daily_realized_loss} USD</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Protective Stop-Loss:</span>
                <span className="text-amber-400 font-bold">{config?.protective_stop_loss_percentage}% mandatory</span>
              </div>
            </div>

            <label className="flex items-start gap-2.5 cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={enableConfirmed}
                onChange={(e) => setEnableConfirmed(e.target.checked)}
                className="mt-0.5 rounded bg-black/60 border-cyan-500/40 text-cyan-500 focus:ring-0"
              />
              <span className="text-xs text-slate-300 leading-relaxed">
                I explicitly confirm and authorize automated testnet order execution under the strict risk limits configured above.
              </span>
            </label>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/[0.08]">
              <button
                type="button"
                onClick={() => {
                  setShowEnableModal(false);
                  setEnableConfirmed(false);
                }}
                disabled={enabling}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleEnableAutomation}
                disabled={!enableConfirmed || enabling}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 text-xs font-bold font-mono transition disabled:opacity-50 flex items-center gap-2"
              >
                {enabling ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-slate-950" />}
                <span>{enabling ? 'Activating...' : 'Confirm & Enable'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
