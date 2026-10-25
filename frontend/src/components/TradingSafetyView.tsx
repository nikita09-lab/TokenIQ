import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Lock,
  Unlock,
  RefreshCw,
  Sliders,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  DollarSign,
  AlertOctagon,
  Sparkles,
  Info,
  Check,
  Send,
  Trash2,
  RotateCcw,
  Ban,
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
} from 'lucide-react';
import {
  getTradingStatus,
  getRiskConfig,
  updateRiskConfig,
  checkSignalRisk,
  engageKillSwitch,
  resetKillSwitch,
  createOrderPreview,
  confirmAndSubmitOrder,
  listOrders,
  cancelOrder,
  reconcileOrder,
} from '../services/api';
import type {
  TradingStatusData,
  RiskConfigData,
  RiskCheckRequestData,
  RiskCheckResultData,
  OrderPreviewRequestData,
  OrderPreviewResponseData,
  OrderExecutionRecordData,
} from '../types/market';
import { AutomatedTradingPanel } from './AutomatedTradingPanel';

interface TradingSafetyViewProps {
  onSelectSymbol?: (symbol: string) => void;
}

type SafetyViewMode = 'safety' | 'execution' | 'automation';

export const TradingSafetyView: React.FC<TradingSafetyViewProps> = ({ onSelectSymbol }) => {
  // Navigation mode
  const [viewMode, setViewMode] = useState<SafetyViewMode>('automation');

  // Status & limits state
  const [status, setStatus] = useState<TradingStatusData | null>(null);
  const [config, setConfig] = useState<RiskConfigData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Editable config state
  const [isEditingConfig, setIsEditingConfig] = useState<boolean>(false);
  const [configForm, setConfigForm] = useState<RiskConfigData>({
    max_order_notional_usd: 500,
    max_position_size: 10,
    max_daily_realized_loss_usd: 100,
    max_orders_per_day: 20,
    max_concurrent_positions: 1,
    min_stop_loss_distance_pct: 0.5,
    max_signal_age_seconds: 300,
  });
  const [savingConfig, setSavingConfig] = useState<boolean>(false);

  // Kill Switch Modals & Action State
  const [showResetModal, setShowResetModal] = useState<boolean>(false);
  const [resetReason, setResetReason] = useState<string>('');
  const [resetConfirmed, setResetConfirmed] = useState<boolean>(false);
  const [killSwitchLoading, setKillSwitchLoading] = useState<boolean>(false);

  // Dry-Run Evaluation Sandbox State
  const [simSymbol, setSimSymbol] = useState<string>('BTCUSD');
  const [simSide, setSimSide] = useState<'BUY' | 'SELL'>('BUY');
  const [simIntent, setSimIntent] = useState<string>('OPEN_LONG');
  const [simQty, setSimQty] = useState<string>('1.0');
  const [simPrice, setSimPrice] = useState<string>('84000');
  const [simStopLoss, setSimStopLoss] = useState<string>('82500');
  const [simSignalId, setSimSignalId] = useState<string>(`sig_manual_${Date.now()}`);
  const [simIsStale, setSimIsStale] = useState<boolean>(false);
  const [evaluating, setEvaluating] = useState<boolean>(false);
  const [evalResult, setEvalResult] = useState<RiskCheckResultData | null>(null);

  // ==========================================================================
  // Phase 7.2: Two-Stage Testnet Order Execution State
  // ==========================================================================
  const [orderSymbol, setOrderSymbol] = useState<string>('BTCUSD');
  const [orderSide, setOrderSide] = useState<'BUY' | 'SELL'>('BUY');
  const [orderType, setOrderType] = useState<'limit_order' | 'market_order'>('limit_order');
  const [orderQty, setOrderQty] = useState<string>('1.0');
  const [orderPrice, setOrderPrice] = useState<string>('84000');
  const [orderStopLoss, setOrderStopLoss] = useState<string>('82500');
  const [generatingPreview, setGeneratingPreview] = useState<boolean>(false);

  // Active Preview & Confirmation Dialog
  const [activePreview, setActivePreview] = useState<OrderPreviewResponseData | null>(null);
  const [previewRemainingSeconds, setPreviewRemainingSeconds] = useState<number>(60);
  const [orderConfirmChecked, setOrderConfirmChecked] = useState<boolean>(false);
  const [submittingOrder, setSubmittingOrder] = useState<boolean>(false);

  // Order Records & Cancellation
  const [orders, setOrders] = useState<OrderExecutionRecordData[]>([]);
  const [loadingOrders, setLoadingOrders] = useState<boolean>(false);
  const [cancellingOrderId, setCancellingOrderId] = useState<string | null>(null);
  const [orderToCancel, setOrderToCancel] = useState<OrderExecutionRecordData | null>(null);
  const [reconcilingOrderId, setReconcilingOrderId] = useState<string | null>(null);

  const isMountedRef = useRef<boolean>(true);

  // Product specification guidelines
  const productSpecs: Record<string, { tick: string; cval: string; defaultPrice: string; defaultSL: string }> = {
    BTCUSD: { tick: '0.1', cval: '0.001 BTC', defaultPrice: '84000', defaultSL: '82500' },
    ETHUSD: { tick: '0.05', cval: '0.01 ETH', defaultPrice: '3200', defaultSL: '3120' },
    SOLUSD: { tick: '0.0001', cval: '1.0 SOL', defaultPrice: '180', defaultSL: '175' },
  };

  // Fetch status, config, and orders
  const fetchData = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true);
    setError(null);
    try {
      const [statusRes, configRes, ordersRes] = await Promise.all([
        getTradingStatus(),
        getRiskConfig(),
        listOrders().catch(() => []),
      ]);
      if (isMountedRef.current) {
        setStatus(statusRes);
        setConfig(configRes);
        setConfigForm(configRes);
        setOrders(ordersRes);
      }
    } catch (err: unknown) {
      if (isMountedRef.current) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Failed to retrieve trading safety status: ${msg}`);
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    fetchData();
    // Poll safety status and orders every 10 seconds
    const interval = setInterval(() => {
      fetchData(false);
    }, 10000);
    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
    };
  }, [fetchData]);

  // Preview countdown timer
  useEffect(() => {
    if (!activePreview) return;
    setPreviewRemainingSeconds(activePreview.ttl_seconds);

    const timer = setInterval(() => {
      setPreviewRemainingSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [activePreview]);

  // Switch symbol presets
  const handleSelectSymbol = (sym: string) => {
    setOrderSymbol(sym);
    const spec = productSpecs[sym];
    if (spec) {
      setOrderPrice(spec.defaultPrice);
      setOrderStopLoss(spec.defaultSL);
    }
  };

  // Handle emergency kill switch engagement
  const handleEngageKillSwitch = async () => {
    setKillSwitchLoading(true);
    setError(null);
    try {
      const updated = await engageKillSwitch('Emergency manual stop triggered from Trading Safety Terminal.');
      setStatus(updated);
      setSuccessMsg('Emergency Kill Switch has been ENGAGED. All trading operations are now halted.');
      setTimeout(() => setSuccessMsg(null), 6000);
    } catch (err: unknown) {
      setError(`Failed to engage kill switch: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setKillSwitchLoading(false);
    }
  };

  // Handle deliberate kill switch reset
  const handleResetKillSwitch = async () => {
    if (!resetConfirmed || resetReason.trim().length < 5) {
      setError('Please provide a valid operator reason (at least 5 characters) and check the confirmation box.');
      return;
    }

    setKillSwitchLoading(true);
    setError(null);
    try {
      const updated = await resetKillSwitch(true, resetReason.trim());
      setStatus(updated);
      setShowResetModal(false);
      setResetReason('');
      setResetConfirmed(false);
      setSuccessMsg('Kill switch successfully reset and trading safeguards authorized.');
      setTimeout(() => setSuccessMsg(null), 6000);
    } catch (err: unknown) {
      setError(`Failed to reset kill switch: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setKillSwitchLoading(false);
    }
  };

  // Handle saving risk limits
  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingConfig(true);
    setError(null);
    try {
      const res = await updateRiskConfig(configForm);
      setConfig(res.config);
      setConfigForm(res.config);
      setIsEditingConfig(false);
      setSuccessMsg('Risk and safety limits updated and persisted safely.');
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchData(false);
    } catch (err: unknown) {
      setError(`Failed to update risk config: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSavingConfig(false);
    }
  };

  // Handle Dry-Run Risk Evaluation Sandbox
  const handleRunEvaluation = async (e: React.FormEvent) => {
    e.preventDefault();
    setEvaluating(true);
    setEvalResult(null);
    setError(null);
    try {
      const payload: RiskCheckRequestData = {
        signal_id: simSignalId,
        symbol: simSymbol,
        side: simSide,
        position_intent: simIntent,
        quantity: parseFloat(simQty),
        price: parseFloat(simPrice),
        stop_loss: parseFloat(simStopLoss),
        timestamp: Math.floor((Date.now() - (simIsStale ? 400000 : 0)) / 1000),
      };
      const res = await checkSignalRisk(payload);
      setEvalResult(res);
    } catch (err: unknown) {
      setError(`Evaluation failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setEvaluating(false);
    }
  };

  // Stage 1: Generate Order Preview
  const handleGeneratePreview = async (e: React.FormEvent) => {
    e.preventDefault();
    setGeneratingPreview(true);
    setError(null);

    const qty = parseFloat(orderQty);
    const price = orderType === 'limit_order' ? parseFloat(orderPrice) : undefined;
    const sl = orderStopLoss ? parseFloat(orderStopLoss) : undefined;

    const req: OrderPreviewRequestData = {
      symbol: orderSymbol,
      side: orderSide,
      order_type: orderType,
      quantity: qty,
      price: price,
      stop_loss: sl,
    };

    try {
      const preview = await createOrderPreview(req);
      setActivePreview(preview);
      setOrderConfirmChecked(false);
    } catch (err: unknown) {
      setError(`Failed to generate order preview: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setGeneratingPreview(false);
    }
  };

  // Stage 2: Confirm & Submit Order to Testnet
  const handleConfirmOrder = async () => {
    if (!activePreview || !orderConfirmChecked) return;

    setSubmittingOrder(true);
    setError(null);

    try {
      const record = await confirmAndSubmitOrder({
        preview_id: activePreview.preview_id,
        confirm: true,
      });

      setActivePreview(null);
      setSuccessMsg(
        `Order ${record.client_order_id} submitted to Delta Testnet! Status: ${record.state} ${
          record.order_id ? `(Exchange ID: ${record.order_id})` : ''
        }`
      );
      setTimeout(() => setSuccessMsg(null), 8000);
      fetchData(false);
    } catch (err: unknown) {
      setError(`Submission failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSubmittingOrder(false);
    }
  };

  // Cancel an open order
  const handleExecuteCancel = async () => {
    if (!orderToCancel) return;
    const targetId = orderToCancel.order_id || orderToCancel.client_order_id;
    setCancellingOrderId(targetId);
    setError(null);

    try {
      await cancelOrder(targetId, 'User requested cancellation from Trading Terminal');
      setOrderToCancel(null);
      setSuccessMsg(`Order ${targetId} cancelled successfully.`);
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchData(false);
    } catch (err: unknown) {
      setError(`Failed to cancel order: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCancellingOrderId(null);
    }
  };

  // Reconcile order state
  const handleReconcile = async (orderId: string) => {
    setReconcilingOrderId(orderId);
    setError(null);
    try {
      const updated = await reconcileOrder(orderId);
      setSuccessMsg(`Order ${orderId} reconciled. Exchange status: ${updated.state}`);
      setTimeout(() => setSuccessMsg(null), 5000);
      fetchData(false);
    } catch (err: unknown) {
      setError(`Reconciliation failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setReconcilingOrderId(null);
    }
  };

  if (loading && !status) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[500px] text-slate-400 gap-3">
        <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
        <span className="font-mono text-sm">Initializing TokenIQ Trading Safety Engine...</span>
      </div>
    );
  }

  const isKillSwitchEngaged = status?.kill_switch_engaged ?? true;
  const isTradingEnabled = status?.trading_enabled ?? false;

  const openOrders = orders.filter((o) =>
    ['OPEN', 'PENDING', 'SUBMITTED'].includes(o.state)
  );
  const historicalOrders = orders.filter(
    (o) => !['OPEN', 'PENDING', 'SUBMITTED'].includes(o.state)
  );

  return (
    <div className="flex flex-col gap-6 p-6 max-w-7xl mx-auto text-slate-100">
      {/* Top Banner: Master Safety & Kill Switch Status */}
      <div
        className={`relative overflow-hidden rounded-2xl border p-6 backdrop-blur-md shadow-2xl transition-all ${
          isKillSwitchEngaged
            ? 'bg-gradient-to-r from-rose-950/40 via-red-950/20 to-slate-900/60 border-rose-500/30'
            : 'bg-gradient-to-r from-emerald-950/40 via-cyan-950/20 to-slate-900/60 border-emerald-500/30'
        }`}
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
          <div className="flex items-start gap-4">
            <div
              className={`p-3.5 rounded-2xl border shadow-lg ${
                isKillSwitchEngaged
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-400 shadow-rose-950/50'
                  : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-emerald-950/50'
              }`}
            >
              {isKillSwitchEngaged ? (
                <ShieldAlert className="w-8 h-8 animate-pulse" />
              ) : (
                <ShieldCheck className="w-8 h-8 text-emerald-400" />
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                  Trading Safety & Order Execution
                </h1>
                <span
                  className={`text-xs px-2.5 py-1 rounded-full font-mono font-bold tracking-wider uppercase border ${
                    isKillSwitchEngaged
                      ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                      : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  }`}
                >
                  {isKillSwitchEngaged ? 'HALT ENGAGED' : 'TRADING AUTHORIZED'}
                </span>
                <span className="text-xs px-2.5 py-1 rounded-full font-mono font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                  DELTA INDIA TESTNET
                </span>
                <span className="text-xs px-2.5 py-1 rounded-full font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  TWO-STAGE CONFIRMATION
                </span>
              </div>

              <p className="text-sm text-slate-300 max-w-2xl leading-relaxed">
                {isKillSwitchEngaged
                  ? status?.kill_switch_reason ||
                    'Trading is currently halted. The kill-switch blocks all new order submissions and strategy approvals.'
                  : 'Testnet execution active. Manual orders require explicit two-stage confirmation and satisfy strict pre-trade risk checks.'}
              </p>

              <div className="text-xs text-slate-400 font-mono mt-1 flex items-center gap-2">
                <Lock className="w-3.5 h-3.5 text-slate-500" />
                <span>
                  Host: <span className="text-cyan-400 font-bold">{status?.base_url || 'cdn-ind.testnet.deltaex.org'}</span> • Verified Testnet Only
                </span>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={() => fetchData(true)}
              disabled={refreshing}
              className="px-3.5 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-slate-300 hover:text-white text-xs font-medium flex items-center gap-2 transition disabled:opacity-50"
              title="Refresh status"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-cyan-400' : ''}`} />
              <span>Refresh</span>
            </button>

            {isKillSwitchEngaged ? (
              <button
                onClick={() => setShowResetModal(true)}
                disabled={killSwitchLoading}
                className="px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/40 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-emerald-950/40 transition disabled:opacity-50"
              >
                <Unlock className="w-4 h-4" />
                <span>Reset Kill Switch</span>
              </button>
            ) : (
              <button
                onClick={handleEngageKillSwitch}
                disabled={killSwitchLoading}
                className="px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 border border-rose-400/40 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-rose-950/40 transition disabled:opacity-50"
              >
                <AlertOctagon className="w-4 h-4" />
                <span>Emergency Kill Switch</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Notifications / Alerts */}
      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 text-rose-400" />
          <div className="flex-1 font-mono text-xs">{error}</div>
          <button onClick={() => setError(null)} className="text-slate-400 hover:text-white text-xs">
            ✕
          </button>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 text-sm">
          <CheckCircle2 className="w-5 h-5 shrink-0 text-emerald-400" />
          <div className="flex-1 font-mono text-xs">{successMsg}</div>
          <button onClick={() => setSuccessMsg(null)} className="text-slate-400 hover:text-white text-xs">
            ✕
          </button>
        </div>
      )}

      {/* Session Telemetry & Daily Metric Counters */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Orders Submitted Today</span>
            <Send className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-white">
              {status?.orders_submitted_today ?? 0}
            </span>
            <span className="text-xs text-slate-500 font-mono">/ {config?.max_orders_per_day ?? 100} max</span>
          </div>
          <span className="text-[11px] text-cyan-400/80 mt-2 font-mono">
            Tracked upon genuine exchange submission
          </span>
        </div>

        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Evaluations Today</span>
            <Sparkles className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {status?.evaluations_today ?? 0}
            </span>
            <span className="text-xs text-slate-500 font-mono">evals</span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 font-mono">
            Dry-run pre-checks (independent counter)
          </span>
        </div>

        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Daily Realized Loss</span>
            <DollarSign className="w-4 h-4 text-amber-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-white">
              ${(status?.daily_realized_loss_usd ?? 0).toFixed(2)}
            </span>
            <span className="text-xs text-slate-500 font-mono">
              / ${(config?.max_daily_realized_loss_usd ?? 100).toFixed(0)} max
            </span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 font-mono">
            Safety halt limit on realized loss
          </span>
        </div>

        <div className="p-4 rounded-xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-medium">Active Positions</span>
            <Layers className="w-4 h-4 text-blue-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-white">
              {status?.active_positions_count ?? 0}
            </span>
            <span className="text-xs text-slate-500 font-mono">
              / {config?.max_concurrent_positions ?? 3} max
            </span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 font-mono">
            Live exchange open positions
          </span>
        </div>
      </div>

      {/* Mode Navigation Tabs */}
      <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setViewMode('automation')}
            className={`px-4 py-2 rounded-xl text-xs font-bold font-mono flex items-center gap-2 transition ${
              viewMode === 'automation'
                ? 'bg-cyan-500 text-slate-950 shadow-lg shadow-cyan-950/50'
                : 'bg-white/5 text-slate-400 hover:text-white hover:bg-white/10'
            }`}
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Automated Trading Engine</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">AUTOPILOT</span>
          </button>

          <button
            onClick={() => setViewMode('execution')}
            className={`px-4 py-2 rounded-xl text-xs font-bold font-mono flex items-center gap-2 transition ${
              viewMode === 'execution'
                ? 'bg-cyan-500 text-slate-950 shadow-lg shadow-cyan-950/50'
                : 'bg-white/5 text-slate-400 hover:text-white hover:bg-white/10'
            }`}
          >
            <Send className="w-3.5 h-3.5" />
            <span>Manual Execution (Two-Stage)</span>
          </button>

          <button
            onClick={() => setViewMode('safety')}
            className={`px-4 py-2 rounded-xl text-xs font-bold font-mono flex items-center gap-2 transition ${
              viewMode === 'safety'
                ? 'bg-cyan-500 text-slate-950 shadow-lg shadow-cyan-950/50'
                : 'bg-white/5 text-slate-400 hover:text-white hover:bg-white/10'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Risk Controls & Sandbox</span>
          </button>
        </div>

        <span className="text-[11px] font-mono text-slate-400 hidden sm:block">
          Production Trading: <span className="text-rose-400 font-bold">STRICTLY DISABLED</span>
        </span>
      </div>

      {/* ====================================================================== */}
      {/* MODE 1: TESTNET ORDER EXECUTION                                        */}
      {/* ====================================================================== */}
      {viewMode === 'execution' && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left: Order Form */}
            <div className="lg:col-span-5 flex flex-col gap-4">
              <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                  <div className="flex items-center gap-2">
                    <Send className="w-4 h-4 text-cyan-400" />
                    <h2 className="text-base font-semibold text-white">Manual Testnet Order Entry</h2>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    STAGE 1: PREVIEW
                  </span>
                </div>

                <form onSubmit={handleGeneratePreview} className="flex flex-col gap-3.5 text-xs">
                  {/* Symbol Quick Selector */}
                  <div>
                    <label className="text-slate-400 mb-1.5 block font-medium">Product / Pair</label>
                    <div className="grid grid-cols-3 gap-2">
                      {['BTCUSD', 'ETHUSD', 'SOLUSD'].map((sym) => (
                        <button
                          key={sym}
                          type="button"
                          onClick={() => handleSelectSymbol(sym)}
                          className={`p-2 rounded-xl text-xs font-mono font-bold border transition flex flex-col items-center gap-0.5 ${
                            orderSymbol === sym
                              ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                              : 'bg-white/[0.02] text-slate-400 border-white/[0.06] hover:bg-white/[0.06]'
                          }`}
                        >
                          <span>{sym}</span>
                          <span className="text-[10px] text-slate-500 font-normal">
                            {productSpecs[sym]?.cval}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Side & Order Type */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-slate-400 mb-1 block">Trade Side</label>
                      <div className="grid grid-cols-2 gap-1.5">
                        <button
                          type="button"
                          onClick={() => setOrderSide('BUY')}
                          className={`py-2 rounded-lg font-mono font-bold text-xs transition ${
                            orderSide === 'BUY'
                              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/50'
                              : 'bg-white/[0.04] text-slate-400 hover:text-white'
                          }`}
                        >
                          BUY / LONG
                        </button>
                        <button
                          type="button"
                          onClick={() => setOrderSide('SELL')}
                          className={`py-2 rounded-lg font-mono font-bold text-xs transition ${
                            orderSide === 'SELL'
                              ? 'bg-rose-600 text-white shadow-lg shadow-rose-950/50'
                              : 'bg-white/[0.04] text-slate-400 hover:text-white'
                          }`}
                        >
                          SELL / SHORT
                        </button>
                      </div>
                    </div>

                    <div>
                      <label className="text-slate-400 mb-1 block">Order Type</label>
                      <select
                        value={orderType}
                        onChange={(e) => setOrderType(e.target.value as 'limit_order' | 'market_order')}
                        className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      >
                        <option value="limit_order">Limit Order</option>
                        <option value="market_order">Market Order</option>
                      </select>
                    </div>
                  </div>

                  {/* Quantity & Price */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-slate-400 mb-1 block">
                        Quantity <span className="text-slate-500">(contracts)</span>
                      </label>
                      <input
                        type="number"
                        step="1"
                        min="1"
                        max="1000"
                        value={orderQty}
                        onChange={(e) => setOrderQty(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                        required
                      />
                    </div>

                    <div>
                      <label className="text-slate-400 mb-1 block">
                        Limit Price <span className="text-slate-500">($ USD)</span>
                      </label>
                      <input
                        type="number"
                        step={productSpecs[orderSymbol]?.tick || '0.1'}
                        min="0.01"
                        value={orderPrice}
                        disabled={orderType === 'market_order'}
                        onChange={(e) => setOrderPrice(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none disabled:opacity-40"
                        required={orderType === 'limit_order'}
                      />
                    </div>
                  </div>

                  {/* Mandatory Protective Stop-Loss */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-slate-400 block font-medium">
                        Protective Stop-Loss Price <span className="text-cyan-400 font-bold">*Mandatory</span>
                      </label>
                      <span className="text-[10px] text-slate-500 font-mono">
                        Min 0.5% distance required
                      </span>
                    </div>
                    <input
                      type="number"
                      step={productSpecs[orderSymbol]?.tick || '0.1'}
                      min="0.01"
                      value={orderStopLoss}
                      onChange={(e) => setOrderStopLoss(e.target.value)}
                      placeholder="e.g. 82500"
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  {/* Estimated Notional Preview Callout */}
                  <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] flex items-center justify-between text-xs font-mono">
                    <span className="text-slate-400">Estimated Notional:</span>
                    <span className="font-bold text-white">
                      ${(
                        (parseFloat(orderQty) || 0) *
                        (orderSymbol === 'BTCUSD' ? 0.001 : orderSymbol === 'ETHUSD' ? 0.01 : 1.0) *
                        (parseFloat(orderPrice) || 0)
                      ).toFixed(2)}{' '}
                      USD
                    </span>
                  </div>

                  <button
                    type="submit"
                    disabled={generatingPreview || isKillSwitchEngaged || !isTradingEnabled}
                    className="mt-1 w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-xs shadow-lg shadow-cyan-950/40 flex items-center justify-center gap-2 transition disabled:opacity-40"
                  >
                    <Play className={`w-4 h-4 ${generatingPreview ? 'animate-spin' : ''}`} />
                    <span>
                      {isKillSwitchEngaged
                        ? 'Trading Halted by Kill Switch'
                        : generatingPreview
                        ? 'Generating Preview...'
                        : 'Preview Order & Validate Risk'}
                    </span>
                  </button>
                </form>
              </div>

              {/* Security info card */}
              <div className="p-4 rounded-xl bg-slate-900/60 border border-white/[0.06] text-xs text-slate-400 flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                  <span>Two-Stage Order Protection</span>
                </div>
                <p className="leading-relaxed text-[11px]">
                  1. <strong className="text-slate-200">Preview:</strong> The backend verifies product contract semantics, calculates exact notional, and checks all 11 pre-trade risk safeguards.
                </p>
                <p className="leading-relaxed text-[11px]">
                  2. <strong className="text-slate-200">Confirmation:</strong> The user explicitly confirms the exact preview. The backend locks the preview, re-checks risk immediately, and dispatches to Delta Testnet.
                </p>
              </div>
            </div>

            {/* Right: Active Order Confirmation Card or Instructions */}
            <div className="lg:col-span-7 flex flex-col gap-4">
              {activePreview ? (
                <div className="p-6 rounded-2xl bg-gradient-to-b from-slate-900/90 to-[#0D131F]/90 border border-cyan-500/40 shadow-2xl backdrop-blur flex flex-col gap-4">
                  <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                    <div className="flex items-center gap-2">
                      <Send className="w-4 h-4 text-cyan-400" />
                      <h3 className="text-base font-bold text-white">Stage 2: Confirm Order Submission</h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <Clock className="w-3.5 h-3.5 text-amber-400" />
                      <span className="font-mono text-xs font-bold text-amber-300">
                        Expires in {previewRemainingSeconds}s
                      </span>
                    </div>
                  </div>

                  {/* Countdown Progress Bar */}
                  <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-1000 ${
                        previewRemainingSeconds > 20 ? 'bg-cyan-400' : 'bg-rose-500 animate-pulse'
                      }`}
                      style={{ width: `${(previewRemainingSeconds / activePreview.ttl_seconds) * 100}%` }}
                    />
                  </div>

                  {/* Parameters Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Symbol</span>
                      <span className="font-bold text-white">{activePreview.symbol}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Side</span>
                      <span
                        className={`font-bold ${
                          activePreview.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {activePreview.side}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Contracts</span>
                      <span className="font-bold text-white">{activePreview.quantity}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Order Price</span>
                      <span className="font-bold text-white">
                        {activePreview.price ? `$${activePreview.price.toLocaleString()}` : 'MARKET'}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Stop Loss</span>
                      <span className="font-bold text-amber-400">
                        ${activePreview.stop_loss?.toLocaleString() || 'N/A'}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Contract Val</span>
                      <span className="font-bold text-slate-300">{activePreview.contract_value}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Tick Size</span>
                      <span className="font-bold text-slate-300">{activePreview.tick_size}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/5">
                      <span className="text-slate-400 text-[10px] block">Est. Notional</span>
                      <span className="font-bold text-cyan-300">
                        ${activePreview.estimated_notional_usd.toLocaleString(undefined, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </span>
                    </div>
                  </div>

                  {/* Pre-trade Risk Result Badge */}
                  <div
                    className={`p-3.5 rounded-xl border flex items-center justify-between ${
                      activePreview.can_submit
                        ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300'
                        : 'bg-rose-950/20 border-rose-500/30 text-rose-300'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      {activePreview.can_submit ? (
                        <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                      ) : (
                        <XCircle className="w-5 h-5 text-rose-400" />
                      )}
                      <div>
                        <div className="text-xs font-bold font-mono">
                          PRE-TRADE RISK DECISION: {activePreview.risk_decision}
                        </div>
                        <div className="text-[11px] text-slate-300">
                          {activePreview.can_submit
                            ? 'All risk safeguards passed. Order is authorized for submission.'
                            : activePreview.risk_reasons.join(' • ') || 'Order violates configured risk limits.'}
                        </div>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-black/40 border border-white/10 uppercase">
                      {activePreview.environment}
                    </span>
                  </div>

                  {/* Confirmation Checkbox */}
                  <div className="flex items-start gap-2.5 p-3 rounded-xl bg-white/[0.03] border border-white/[0.08]">
                    <input
                      type="checkbox"
                      id="confirmOrderSubmit"
                      checked={orderConfirmChecked}
                      disabled={!activePreview.can_submit || previewRemainingSeconds === 0}
                      onChange={(e) => setOrderConfirmChecked(e.target.checked)}
                      className="mt-0.5 rounded border-cyan-500 text-cyan-500 focus:ring-0 cursor-pointer disabled:cursor-not-allowed"
                    />
                    <label
                      htmlFor="confirmOrderSubmit"
                      className="text-xs text-slate-300 cursor-pointer leading-tight select-none"
                    >
                      I explicitly confirm the exact order parameters above and authorize dispatch to{' '}
                      <span className="text-cyan-400 font-bold">{activePreview.verified_testnet_host}</span>.
                    </label>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex items-center justify-end gap-3 pt-2">
                    <button
                      type="button"
                      onClick={() => setActivePreview(null)}
                      className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-xs font-mono transition"
                    >
                      Cancel Preview
                    </button>

                    <button
                      type="button"
                      disabled={
                        !orderConfirmChecked ||
                        !activePreview.can_submit ||
                        previewRemainingSeconds === 0 ||
                        submittingOrder
                      }
                      onClick={handleConfirmOrder}
                      className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-xs shadow-lg shadow-cyan-950/40 flex items-center gap-2 transition disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <Send className={`w-3.5 h-3.5 ${submittingOrder ? 'animate-spin' : ''}`} />
                      <span>{submittingOrder ? 'Submitting to Testnet...' : 'Confirm & Submit to Testnet'}</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="p-8 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col items-center justify-center text-center gap-3 min-h-[340px]">
                  <div className="p-4 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                    <Send className="w-8 h-8" />
                  </div>
                  <h3 className="text-base font-bold text-white">No Order Preview Generated</h3>
                  <p className="text-xs text-slate-400 max-w-sm leading-relaxed">
                    Select a contract, specify quantity and prices in the form on the left, then click{' '}
                    <strong className="text-cyan-400">Preview Order</strong> to calculate notional and validate risk.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Open Orders Table (Live Testnet) */}
          <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-400" />
                <h3 className="text-base font-semibold text-white">Active Testnet Orders ({openOrders.length})</h3>
              </div>
              <button
                onClick={() => fetchData(true)}
                className="text-xs text-cyan-400 hover:text-cyan-300 font-mono flex items-center gap-1"
              >
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
            </div>

            {openOrders.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-500 font-mono">
                No active open orders on Delta Exchange Testnet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-slate-400 text-[11px]">
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2">Type</th>
                      <th className="pb-2">Size</th>
                      <th className="pb-2">Price</th>
                      <th className="pb-2">Stop Loss</th>
                      <th className="pb-2">State</th>
                      <th className="pb-2">Client ID</th>
                      <th className="pb-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {openOrders.map((ord) => (
                      <tr key={ord.client_order_id} className="hover:bg-white/[0.02]">
                        <td className="py-3 font-bold text-white">{ord.symbol}</td>
                        <td className="py-3">
                          <span
                            className={`font-bold px-1.5 py-0.5 rounded text-[10px] ${
                              ord.side === 'BUY'
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : 'bg-rose-500/20 text-rose-400'
                            }`}
                          >
                            {ord.side}
                          </span>
                        </td>
                        <td className="py-3 text-slate-300">{ord.order_type}</td>
                        <td className="py-3 text-white">{ord.size}</td>
                        <td className="py-3 text-white">
                          {ord.limit_price ? `$${ord.limit_price.toLocaleString()}` : 'MARKET'}
                        </td>
                        <td className="py-3 text-amber-400">
                          {ord.stop_loss ? `$${ord.stop_loss.toLocaleString()}` : '—'}
                        </td>
                        <td className="py-3">
                          <span className="px-2 py-0.5 rounded text-[10px] bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                            {ord.state}
                          </span>
                        </td>
                        <td className="py-3 text-slate-400 text-[10px] truncate max-w-[120px]" title={ord.client_order_id}>
                          {ord.client_order_id}
                        </td>
                        <td className="py-3 text-right">
                          <button
                            onClick={() => setOrderToCancel(ord)}
                            className="px-2.5 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-[11px] transition"
                          >
                            Cancel
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Historical & Reconciled Orders */}
          {historicalOrders.length > 0 && (
            <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-slate-400" />
                  <h3 className="text-base font-semibold text-white">Execution History ({historicalOrders.length})</h3>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-slate-400 text-[11px]">
                      <th className="pb-2">Time</th>
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2">Size</th>
                      <th className="pb-2">Notional</th>
                      <th className="pb-2">State</th>
                      <th className="pb-2">Status / Details</th>
                      <th className="pb-2 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {historicalOrders.map((ord) => (
                      <tr key={ord.client_order_id} className="hover:bg-white/[0.02]">
                        <td className="py-3 text-slate-400 text-[11px]">
                          {new Date(ord.created_at * 1000).toLocaleTimeString()}
                        </td>
                        <td className="py-3 font-bold text-white">{ord.symbol}</td>
                        <td className="py-3 font-bold">{ord.side}</td>
                        <td className="py-3 text-white">{ord.size}</td>
                        <td className="py-3 text-slate-300">${ord.notional_usd.toFixed(2)}</td>
                        <td className="py-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              ord.state === 'FILLED'
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : ord.state === 'CANCELLED'
                                ? 'bg-slate-700/50 text-slate-400 border border-slate-600'
                                : ord.state === 'UNKNOWN'
                                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse'
                                : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                            }`}
                          >
                            {ord.state}
                          </span>
                        </td>
                        <td className="py-3 text-[11px] text-slate-400 max-w-[200px] truncate" title={ord.error_message || ord.exchange_state || ''}>
                          {ord.error_message || ord.exchange_state || 'Exchange recorded'}
                        </td>
                        <td className="py-3 text-right">
                          {ord.state === 'UNKNOWN' && (
                            <button
                              onClick={() => handleReconcile(ord.order_id || ord.client_order_id)}
                              disabled={reconcilingOrderId === (ord.order_id || ord.client_order_id)}
                              className="px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-[11px] flex items-center gap-1 font-mono transition"
                            >
                              <RotateCcw className="w-3 h-3" />
                              <span>Reconcile</span>
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ====================================================================== */}
      {/* MODE 2: RISK SAFEGUARDS & DRY-RUN SANDBOX                             */}
      {/* ====================================================================== */}
      {viewMode === 'safety' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Risk Limits */}
          <div className="lg:col-span-5 flex flex-col gap-5">
            <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-cyan-400" />
                  <h2 className="text-base font-semibold text-white">Active Risk Safeguards</h2>
                </div>
                {!isEditingConfig ? (
                  <button
                    onClick={() => setIsEditingConfig(true)}
                    className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-cyan-400 hover:text-cyan-300 text-xs font-mono font-medium border border-cyan-500/20 transition"
                  >
                    Edit Limits
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      if (config) setConfigForm(config);
                      setIsEditingConfig(false);
                    }}
                    className="text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                )}
              </div>

              {isEditingConfig ? (
                <form onSubmit={handleSaveConfig} className="flex flex-col gap-3 text-xs">
                  <div>
                    <label className="text-slate-400 mb-1 block">Max Order Notional (USD)</label>
                    <input
                      type="number"
                      step="50"
                      min="10"
                      value={configForm.max_order_notional_usd}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, max_order_notional_usd: parseFloat(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 mb-1 block">Max Position Size (Contracts)</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      value={configForm.max_position_size}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, max_position_size: parseFloat(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 mb-1 block">Max Daily Realized Loss (USD)</label>
                    <input
                      type="number"
                      step="25"
                      min="10"
                      value={configForm.max_daily_realized_loss_usd}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, max_daily_realized_loss_usd: parseFloat(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 mb-1 block">Max Orders Per Day</label>
                    <input
                      type="number"
                      step="5"
                      min="1"
                      value={configForm.max_orders_per_day}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, max_orders_per_day: parseInt(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 mb-1 block">Max Concurrent Positions</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      max="10"
                      value={configForm.max_concurrent_positions}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, max_concurrent_positions: parseInt(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 mb-1 block">Min Stop-Loss Distance (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="10.0"
                      value={configForm.min_stop_loss_distance_pct}
                      onChange={(e) =>
                        setConfigForm({ ...configForm, min_stop_loss_distance_pct: parseFloat(e.target.value) || 0 })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                      required
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={savingConfig}
                    className="mt-2 w-full py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-2 transition disabled:opacity-50"
                  >
                    <Check className="w-4 h-4" />
                    <span>{savingConfig ? 'Persisting Limits...' : 'Save & Protect Limits'}</span>
                  </button>
                </form>
              ) : (
                <div className="flex flex-col gap-3 text-xs">
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Max Order Notional</span>
                    <span className="font-mono font-bold text-white">
                      ${(config?.max_order_notional_usd ?? 500).toLocaleString()} USD
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Max Position Size</span>
                    <span className="font-mono font-bold text-white">
                      {config?.max_position_size ?? 10} contracts
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Max Daily Realized Loss</span>
                    <span className="font-mono font-bold text-white">
                      ${(config?.max_daily_realized_loss_usd ?? 100).toLocaleString()} USD
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Max Orders Per Day</span>
                    <span className="font-mono font-bold text-white">
                      {config?.max_orders_per_day ?? 20}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Max Concurrent Positions</span>
                    <span className="font-mono font-bold text-white">
                      {config?.max_concurrent_positions ?? 1}
                    </span>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03]">
                    <span className="text-slate-400">Min Stop-Loss Distance</span>
                    <span className="font-mono font-bold text-white">
                      {config?.min_stop_loss_distance_pct ?? 0.5}%
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right: Dry-Run Sandbox */}
          <div className="lg:col-span-7 flex flex-col gap-5">
            <div className="p-5 rounded-2xl bg-[#0D131F]/90 border border-white/[0.08] backdrop-blur flex flex-col gap-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <Play className="w-4 h-4 text-emerald-400" />
                  <h2 className="text-base font-semibold text-white">Dry-Run Risk Evaluation Sandbox</h2>
                </div>
                <span className="text-[11px] text-amber-400/90 font-mono bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                  Zero Exchange Orders
                </span>
              </div>

              {/* Sandbox Form */}
              <form onSubmit={handleRunEvaluation} className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="text-slate-400 mb-1 block">Contract Symbol</label>
                  <select
                    value={simSymbol}
                    onChange={(e) => setSimSymbol(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                  >
                    <option value="BTCUSD">BTCUSD (Delta India Testnet)</option>
                    <option value="ETHUSD">ETHUSD (Delta India Testnet)</option>
                    <option value="SOLUSD">SOLUSD (Delta India Testnet)</option>
                  </select>
                </div>

                <div>
                  <label className="text-slate-400 mb-1 block">Trade Side & Intent</label>
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={simSide}
                      onChange={(e) => setSimSide(e.target.value as 'BUY' | 'SELL')}
                      className="px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                    <select
                      value={simIntent}
                      onChange={(e) => setSimIntent(e.target.value)}
                      className="px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                    >
                      <option value="OPEN_LONG">OPEN_LONG</option>
                      <option value="CLOSE_LONG">CLOSE_LONG</option>
                      <option value="OPEN_SHORT">OPEN_SHORT</option>
                      <option value="CLOSE_SHORT">CLOSE_SHORT</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="text-slate-400 mb-1 block">Order Quantity (Contracts)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.001"
                    value={simQty}
                    onChange={(e) => setSimQty(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                    required
                  />
                </div>

                <div>
                  <label className="text-slate-400 mb-1 block">Entry Price ($)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.01"
                    value={simPrice}
                    onChange={(e) => setSimPrice(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                    required
                  />
                </div>

                <div>
                  <label className="text-slate-400 mb-1 block">Protective Stop-Loss ($)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.01"
                    value={simStopLoss}
                    onChange={(e) => setSimStopLoss(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none"
                    required
                  />
                </div>

                <div>
                  <label className="text-slate-400 mb-1 block">Signal ID</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={simSignalId}
                      onChange={(e) => setSimSignalId(e.target.value)}
                      className="flex-1 px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono focus:border-cyan-400 focus:outline-none text-[11px]"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setSimSignalId(`sig_${Date.now()}`)}
                      className="px-2 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs"
                      title="Generate unique signal ID"
                    >
                      🎲
                    </button>
                  </div>
                </div>

                <div className="sm:col-span-2 pt-2">
                  <button
                    type="submit"
                    disabled={evaluating}
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-sm shadow-lg shadow-cyan-950/40 flex items-center justify-center gap-2 transition disabled:opacity-50"
                  >
                    <Play className={`w-4 h-4 ${evaluating ? 'animate-spin' : ''}`} />
                    <span>{evaluating ? 'Evaluating Risk Criteria...' : 'Evaluate Proposed Order (Dry-Run)'}</span>
                  </button>
                </div>
              </form>

              {/* Evaluation Results */}
              {evalResult && (
                <div className="mt-3 flex flex-col gap-3 pt-4 border-t border-white/[0.08]">
                  <div
                    className={`p-4 rounded-xl border flex items-center justify-between ${
                      evalResult.approved
                        ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-300'
                        : 'bg-rose-950/30 border-rose-500/30 text-rose-300'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {evalResult.approved ? (
                        <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                      ) : (
                        <XCircle className="w-6 h-6 text-rose-400" />
                      )}
                      <div>
                        <div className="font-bold text-base tracking-wide flex items-center gap-2">
                          <span>DECISION: {evalResult.decision}</span>
                          <span className="text-[11px] px-2 py-0.5 rounded font-mono bg-white/10">
                            Notional: ${evalResult.proposed_notional_usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                        </div>
                        <div className="text-xs text-slate-300 font-mono mt-0.5">
                          Signal: {evalResult.signal_id} • Evaluated at {new Date(evalResult.evaluated_at * 1000).toLocaleTimeString()}
                        </div>
                      </div>
                    </div>
                  </div>

                  {evalResult.reasons.length > 0 && (
                    <div className="p-3.5 rounded-xl bg-rose-950/20 border border-rose-500/20 text-xs flex flex-col gap-1.5">
                      <span className="font-semibold text-rose-400 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" /> Rejection Reasons:
                      </span>
                      <ul className="list-disc list-inside space-y-1 text-slate-300 font-mono">
                        {evalResult.reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================== */}
      {/* MODE 3: AUTOMATED TRADING ENGINE                                       */}
      {/* ====================================================================== */}
      {viewMode === 'automation' && (
        <AutomatedTradingPanel
          onSelectSymbol={onSelectSymbol}
          tradingStatus={status}
          onRefreshParent={() => fetchData(false)}
        />
      )}

      {/* Kill Switch Reset Modal */}
      {showResetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-md p-6 rounded-2xl bg-slate-900 border border-emerald-500/30 shadow-2xl flex flex-col gap-4 text-slate-100">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                <Unlock className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Deliberate Kill-Switch Reset</h3>
                <p className="text-xs text-slate-400">Explicit operator authorization required</p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Resetting the kill switch authorizes testnet order evaluation and submission.
            </p>

            <div>
              <label className="text-xs text-slate-300 font-medium mb-1 block">
                Operator Justification / Reason:
              </label>
              <textarea
                rows={3}
                value={resetReason}
                onChange={(e) => setResetReason(e.target.value)}
                placeholder="e.g. Verified testnet credentials and risk limits."
                className="w-full px-3 py-2 rounded-lg bg-black/40 border border-white/10 text-white font-mono text-xs focus:border-emerald-400 focus:outline-none"
                required
              />
            </div>

            <div className="flex items-start gap-2 p-3 rounded-lg bg-emerald-950/20 border border-emerald-500/20">
              <input
                type="checkbox"
                id="confirmReset"
                checked={resetConfirmed}
                onChange={(e) => setResetConfirmed(e.target.checked)}
                className="mt-0.5 rounded border-emerald-500 text-emerald-500 focus:ring-0"
              />
              <label htmlFor="confirmReset" className="text-xs text-emerald-200 cursor-pointer leading-tight">
                I explicitly confirm that risk limits have been validated and I authorize testnet execution.
              </label>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowResetModal(false);
                  setResetReason('');
                  setResetConfirmed(false);
                }}
                className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-xs transition"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!resetConfirmed || resetReason.trim().length < 5 || killSwitchLoading}
                onClick={handleResetKillSwitch}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center gap-2 transition disabled:opacity-40"
              >
                <Unlock className="w-3.5 h-3.5" />
                <span>Confirm & Reset Kill Switch</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cancel Order Confirmation Modal */}
      {orderToCancel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-sm p-6 rounded-2xl bg-slate-900 border border-rose-500/30 shadow-2xl flex flex-col gap-4 text-slate-100">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400">
                <Ban className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Cancel Testnet Order</h3>
                <p className="text-xs text-slate-400 font-mono">
                  {orderToCancel.symbol} • {orderToCancel.side} {orderToCancel.size}
                </p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Are you sure you want to cancel order{' '}
              <span className="font-mono font-bold text-white">
                {orderToCancel.order_id || orderToCancel.client_order_id}
              </span>{' '}
              on Delta Exchange Testnet?
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setOrderToCancel(null)}
                className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-xs transition"
              >
                Keep Order
              </button>
              <button
                type="button"
                disabled={cancellingOrderId !== null}
                onClick={handleExecuteCancel}
                className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs flex items-center gap-2 transition disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Confirm Cancel</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
