export type ConnectionStatusType = 'connected' | 'connecting' | 'disconnected';

export type ChartResolution = '1m' | '5m' | '15m' | '1h' | '1d';

export type HistoryRangePreset = '1D' | '7D' | '1M' | '3M' | 'custom';

export interface HistoryRangeConfig {
  type: HistoryRangePreset;
  start?: number; // Unix seconds
  end?: number;   // Unix seconds
  label: string;
  startDateStr?: string; // YYYY-MM-DD
  endDateStr?: string;   // YYYY-MM-DD
}

export type ActiveTab = 'overview' | 'charts' | 'watchlist' | 'backtesting' | 'evaluation' | 'wallet' | 'safety' | 'about';

export interface DeltaRawTicker {
  symbol: string;
  product_id?: number;
  close?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  turnover?: number;
  turnover_usd?: number;
  ltp_change_24h?: string | number;
  mark_change_24h?: string | number;
  mark_price?: string | number;
  spot_price?: string | number;
  funding_rate?: string | number;
  contract_type?: string;
  underlying_asset_symbol?: string;
  description?: string;
  tick_size?: string | number;
  time?: string;
  timestamp?: number;
  product_trading_status?: string;
  leverage?: number;
  quotes?: {
    best_bid?: string | number | null;
    best_ask?: string | number | null;
    bid_size?: string | number | null;
    ask_size?: string | number | null;
  };
}

export interface MarketTicker {
  symbol: string;
  productId: number;
  name: string;
  baseAsset: string;
  quoteAsset: string;
  contractType: string;
  lastPrice: number;
  prevPrice?: number;
  change24h: number | null;
  high24h: number | null;
  low24h: number | null;
  volume24h: number | null;
  turnover24hUsd: number | null;
  markPrice: number | null;
  spotPrice: number | null;
  fundingRate: number | null;
  bestBid: number | null;
  bestAsk: number | null;
  timestamp: number;
  lastUpdatedStr: string;
  priceDirection?: 'up' | 'down' | 'same';
}

export interface CandleData {
  time: number; // Unix seconds (UTC)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesFetchResult {
  candles: CandleData[];
  limitationNotice?: string;
  actualRange: {
    start: number;
    end: number;
  };
}

export interface MarketStats {
  btcPrice: number | null;
  btcChange24h: number | null;
  btcVolume: number | null;
  ethPrice: number | null;
  ethChange24h: number | null;
  ethVolume: number | null;
  totalTradingPairs: number;
  activePerpetuals: number;
  totalVolumeUsd24h: number | null;
  gainersCount: number;
  losersCount: number;
}

export type SortField = 'symbol' | 'lastPrice' | 'change24h' | 'high24h' | 'low24h' | 'volume24h' | 'turnover24hUsd';
export type SortDirection = 'asc' | 'desc';

export interface BacktestRequest {
  symbol: string;
  resolution: string;
  start_time?: number;
  end_time?: number;
  initial_capital: number;
  fee_rate: number;
  slippage_rate: number;
  execution_mode: 'next_open' | 'current_close';
  strategy_params?: Record<string, any>;
}

export interface TradeRecord {
  trade_id: number;
  symbol: string;
  side: string;
  entry_time: number;
  entry_price: number;
  entry_fee: number;
  exit_time: number;
  exit_price: number;
  exit_fee: number;
  total_fees: number;
  quantity: number;
  cost_basis: number;
  proceeds: number;
  gross_pnl: number;
  net_pnl: number;
  return_pct: number;
  exit_reason: string;
  duration_seconds: number;
}

export interface EquityPointData {
  time: number;
  close: number;
  cash: number;
  position_qty: number;
  position_value: number;
  equity: number;
  drawdown_dollars: number;
  drawdown_pct: number;
  in_position: boolean;
}

export interface BacktestMetricsData {
  initial_capital: number;
  final_equity: number;
  net_profit: number;
  net_return_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  break_even_trades: number;
  win_rate_pct: number;
  loss_rate_pct: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  max_drawdown_dollars: number;
  max_drawdown_pct: number;
  avg_trade_pnl: number;
  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  total_fees_paid: number;
  buy_and_hold_return_pct: number;
  total_bars_analyzed: number;
  market_exposure_pct: number;
}

export interface BacktestResultData {
  backtest_id: string;
  symbol: string;
  resolution: string;
  start_time: number;
  end_time: number;
  execution_mode: string;
  assumptions_note: string;
  strategy_id: string;
  strategy_params: Record<string, any>;
  metrics: BacktestMetricsData;
  equity_curve: EquityPointData[];
  trades: TradeRecord[];
  disclaimer: string;
}

// ============================================================================
// Phase 4: Strategy Evaluation and Robustness Testing Types
// ============================================================================

export interface ParameterSearchSpace {
  fast_periods: number[];
  slow_periods: number[];
  rsi_periods: number[];
  rsi_buy_mins: number[];
  rsi_sell_maxs: number[];
  volume_confirmation: boolean[];
}

export interface EvaluationRequest {
  symbol: string;
  resolution: string;
  start_time?: number;
  end_time?: number;
  split_ratio: number;
  initial_capital: number;
  fee_rate: number;
  slippage_rate: number;
  execution_mode: 'next_open' | 'current_close';
  max_combinations: number;
  search_space: ParameterSearchSpace;
  ranking_metric: 'net_return_pct' | 'profit_factor' | 'win_rate_pct';
}

export interface PeriodMetricsData {
  period_type: 'in_sample' | 'out_of_sample';
  start_time: number;
  end_time: number;
  total_bars: number;
  initial_capital: number;
  final_equity: number;
  net_profit: number;
  net_return_pct: number;
  max_drawdown_dollars: number;
  max_drawdown_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  break_even_trades: number;
  win_rate_pct: number;
  loss_rate_pct: number;
  profit_factor: number | null;
  gross_profit: number;
  gross_loss: number;
  avg_trade_pnl: number;
  total_fees_paid: number;
  market_exposure_pct: number;
  buy_and_hold_return_pct: number;
}

export interface StrategyParamCombinationData {
  fast_period: number;
  slow_period: number;
  rsi_period: number;
  rsi_buy_min: number;
  rsi_sell_max: number;
  volume_confirmation_enabled: boolean;
  rsi_filter_enabled: boolean;
  rsi_overbought: number;
  rsi_oversold: number;
  volume_ma_period: number;
  sell_intent: string;
}

export interface EvaluatedParameterSetData {
  rank: number;
  params: StrategyParamCombinationData;
  params_label: string;
  in_sample: PeriodMetricsData;
  out_of_sample: PeriodMetricsData;
  robustness_ratio: number | null;
  return_degradation_pct: number;
  drawdown_increase_ratio: number | null;
  is_overfit: boolean;
  overfit_warning: string | null;
}

export interface EvaluationResultData {
  evaluation_id: string;
  symbol: string;
  resolution: string;
  execution_mode: string;
  total_bars: number;
  split_ratio: number;
  train_bars: number;
  test_bars: number;
  train_start_time: number;
  train_end_time: number;
  test_start_time: number;
  test_end_time: number;
  total_combinations_requested: number;
  total_combinations_evaluated: number;
  invalid_combinations_filtered: number;
  ranking_metric: string;
  selected_winner_params: StrategyParamCombinationData;
  selected_winner_label: string;
  selected_winner_is_overfit: boolean;
  selected_winner_overfit_warning: string | null;
  parameter_sets: EvaluatedParameterSetData[];
  winner_train_equity_curve: EquityPointData[];
  winner_test_equity_curve: EquityPointData[];
  winner_train_trades: TradeRecord[];
  winner_test_trades: TradeRecord[];
  created_at: number;
  disclaimer: string;
}

// ============================================================================
// Phase 6: Testnet Wallet & Account Dashboard Types
// ============================================================================

export interface WalletBalanceItemData {
  asset_id: number;
  asset_symbol: string;
  balance: number;
  available_balance: number;
  blocked_margin: number;
  order_margin?: number;
  position_margin?: number;
  usd_value?: number | null;
}

export interface PositionItemData {
  product_id: number;
  symbol: string;
  side: 'LONG' | 'SHORT';
  size: number;
  entry_price: number;
  mark_price: number;
  margin: number;
  unrealized_pnl: number;
  realized_pnl: number;
  liquidation_price?: number | null;
  bankruptcy_price?: number | null;
  leverage?: number | null;
  updated_at?: number | null;
}

export interface OrderItemData {
  order_id: string;
  product_id: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  order_type: string;
  size: number;
  unfilled_size: number;
  limit_price?: number | null;
  stop_price?: number | null;
  average_fill_price?: number | null;
  state: string;
  created_at: number;
  updated_at?: number | null;
}

export interface AccountOverviewData {
  authenticated: boolean;
  is_testnet: boolean;
  environment: string;
  base_url: string;
  masked_api_key: string;
  client_ip?: string | null;
  total_balance_usd: number;
  available_balance_usd: number;
  total_margin_used_usd: number;
  order_margin_usd?: number;
  position_margin_usd?: number;
  account_equity_usd?: number;
  account_currency?: string;
  total_unrealized_pnl_usd: number;
  balances: WalletBalanceItemData[];
  positions: PositionItemData[];
  open_orders: OrderItemData[];
  recent_orders: OrderItemData[];
  last_updated_at: number;
  last_balance_update_timestamp?: number;
  diagnostic?: string | null;
  warning?: string | null;
  disclaimer: string;
}

export interface AccountAuthStatusData {
  authenticated: boolean;
  is_testnet: boolean;
  environment: string;
  base_url: string;
  masked_api_key: string;
  client_ip?: string | null;
  diagnostic?: string | null;
  warning?: string | null;
}

export interface RiskConfigData {
  max_order_notional_usd: number;
  max_position_size: number;
  max_daily_realized_loss_usd: number;
  max_orders_per_day: number;
  max_concurrent_positions: number;
  min_stop_loss_distance_pct: number;
  max_signal_age_seconds: number;
}

export interface TradingStatusData {
  trading_enabled: boolean;
  kill_switch_engaged: boolean;
  kill_switch_reason?: string | null;
  kill_switch_activated_at?: number | null;
  last_reset_at?: number | null;
  dry_run_mode: boolean;
  testnet_enforced: boolean;
  base_url: string;
  active_risk_limits: RiskConfigData;
  orders_submitted_today: number;
  evaluations_today: number;
  daily_realized_loss_usd: number;
  active_positions_count: number;
  disclaimer: string;
}

export interface RuleEvaluationResultData {
  rule_name: string;
  status: 'PASSED' | 'FAILED' | 'SKIPPED';
  message: string;
  details?: Record<string, any>;
}

export interface RiskCheckRequestData {
  symbol: string;
  side: 'BUY' | 'SELL';
  position_intent?: string;
  quantity: number;
  price: number;
  stop_loss?: number;
  signal_id: string;
  timestamp?: number;
  strategy_id?: string;
}

export interface RiskCheckResultData {
  approved: boolean;
  decision: 'APPROVED' | 'REJECTED';
  symbol: string;
  signal_id: string;
  proposed_notional_usd: number;
  evaluated_at: number;
  rules_evaluated: RuleEvaluationResultData[];
  reasons: string[];
  disclaimer: string;
}

// ============================================================================
// Phase 7.2: Secure Delta Exchange Testnet Order Execution Types
// ============================================================================

export interface OrderPreviewRequestData {
  symbol: string;
  side: 'BUY' | 'SELL';
  order_type: 'limit_order' | 'market_order';
  quantity: number;
  price?: number;
  stop_loss?: number;
  position_intent?: 'OPEN_LONG' | 'CLOSE_LONG' | 'OPEN_SHORT' | 'CLOSE_SHORT';
  client_order_id?: string;
}

export interface OrderPreviewResponseData {
  preview_id: string;
  symbol: string;
  product_id: number;
  side: 'BUY' | 'SELL';
  order_type: string;
  quantity: number;
  price?: number;
  stop_loss?: number;
  contract_value: number;
  tick_size: number;
  estimated_notional_usd: number;
  environment: string;
  verified_testnet_host: string;
  created_at: number;
  expires_at: number;
  ttl_seconds: number;
  can_submit: boolean;
  risk_decision: string;
  risk_reasons: string[];
  rules_evaluated: RuleEvaluationResultData[];
  disclaimer: string;
}

export interface OrderConfirmRequestData {
  preview_id: string;
  confirm: boolean;
  notes?: string;
}

export interface OrderExecutionRecordData {
  preview_id: string;
  client_order_id: string;
  order_id?: string | null;
  symbol: string;
  product_id: number;
  side: 'BUY' | 'SELL';
  order_type: string;
  size: number;
  unfilled_size: number;
  limit_price?: number | null;
  stop_loss?: number | null;
  average_fill_price?: number | null;
  state: 'PREVIEWED' | 'CONFIRMING' | 'SUBMITTED' | 'OPEN' | 'PENDING' | 'FILLED' | 'CANCELLED' | 'REJECTED' | 'UNKNOWN' | 'EXPIRED';
  notional_usd: number;
  created_at: number;
  updated_at: number;
  confirmed_at?: number | null;
  submitted_at?: number | null;
  error_message?: string | null;
  reconciliation_needed: boolean;
  reconciliation_attempts: number;
  reconciliation_last_at?: number | null;
  exchange_state?: string | null;
  exchange_response?: Record<string, any> | null;
}

export interface ExecutionStatusResponseData {
  service_ready: boolean;
  testnet_enforced: boolean;
  verified_host: string;
  trading_enabled: boolean;
  kill_switch_engaged: boolean;
  kill_switch_reason?: string | null;
  orders_submitted_today: number;
  active_local_orders_count: number;
  unknown_orders_count: number;
  disclaimer: string;
}

// ============================================================================
// TokenIQ Full Automated Trading Types
// ============================================================================

export type AutomationStateType = 'OFF' | 'STARTING' | 'RUNNING' | 'PAUSED' | 'HALTED';
export type PositionSizingModeType = 'fixed_contracts' | 'fixed_notional' | 'risk_budget';
export type PositionLifecycleStateType =
  | 'FLAT'
  | 'ENTRY_SIGNAL'
  | 'RISK_CHECK'
  | 'ENTRY_PENDING'
  | 'OPEN'
  | 'PROTECTION_VERIFIED'
  | 'EXIT_TRIGGERED'
  | 'EXIT_PENDING';

export interface AutomationConfigData {
  enabled: boolean;
  selected_strategy: string;
  trading_symbol: string;
  candle_interval: string;
  strategy_parameters: Record<string, any>;
  position_sizing_mode: PositionSizingModeType;
  fixed_contract_quantity: number;
  fixed_notional_usd: number;
  risk_budget_usd: number;
  maximum_order_notional: number;
  maximum_position_size: number;
  maximum_concurrent_positions: number;
  maximum_daily_realized_loss: number;
  maximum_orders_per_day: number;
  maximum_trades_per_day: number;
  protective_stop_loss_percentage: number;
  take_profit_percentage?: number | null;
  maximum_allowed_slippage: number;
  cooldown_period_seconds: number;
  allow_long: boolean;
  allow_short: boolean;
  allow_reentry: boolean;
  allow_pyramiding: boolean;
  require_confirmed_candle: boolean;
}

export interface AutomatedSignalData {
  signal_id: string;
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  timeframe: string;
  candle_timestamp: number;
  signal_direction: 'BUY' | 'SELL' | 'EXIT_LONG' | 'EXIT_SHORT' | 'NO_SIGNAL';
  position_intent: string;
  entry_rationale: string;
  intended_price: number;
  intended_quantity: number;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  created_at: number;
  idempotency_key: string;
  lifecycle_state: string;
  rejection_reason?: string | null;
  client_order_id?: string | null;
  exchange_order_id?: string | null;
}

export interface PositionStateRecordData {
  symbol: string;
  product_id: number;
  lifecycle_state: PositionLifecycleStateType;
  side?: 'LONG' | 'SHORT' | null;
  quantity: number;
  average_entry_price: number;
  current_notional_usd: number;
  entry_order_id?: string | null;
  entry_client_order_id?: string | null;
  stop_loss_order_id?: string | null;
  stop_loss_price?: number | null;
  take_profit_order_id?: string | null;
  take_profit_price?: number | null;
  protection_verified: boolean;
  opened_at?: number | null;
  updated_at: number;
  closed_at?: number | null;
  realized_pnl_usd: number;
  last_exit_reason?: string | null;
}

export interface AutomationStatusResponseData {
  state: AutomationStateType;
  enabled: boolean;
  is_paused: boolean;
  pause_reason?: string | null;
  kill_switch_engaged: boolean;
  testnet_enforced: boolean;
  verified_host: string;
  config: AutomationConfigData;
  active_position?: PositionStateRecordData | null;
  latest_signal?: AutomatedSignalData | null;
  latest_signal_rejection_reason?: string | null;
  latest_order_status?: string | null;
  orders_submitted_today: number;
  trades_completed_today: number;
  daily_realized_pnl_usd: number;
  current_exposure_usd: number;
  last_candle_timestamp?: number | null;
  last_market_data_update_at?: number | null;
  last_reconciliation_at?: number | null;
  last_reconciliation_result?: string | null;
  last_error?: string | null;
  worker_uptime_seconds: number;
  wallet_balance_usd?: number | null;
  available_margin_usd?: number | null;
  account_equity_usd?: number | null;
  daily_loss_limit_usd?: number | null;
  worker_heartbeat_at?: number | null;
  disclaimer: string;
}


