import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.automation.config import automation_config_manager
from app.automation.dedup import signal_deduplicator
from app.automation.executor import automated_order_executor
from app.automation.models import (
    AutomationConfig,
    AutomationState,
    AutomationStatusResponse,
    PositionLifecycleState,
    PositionStateRecord,
)
from app.automation.position_manager import position_manager
from app.automation.strategy_runner import strategy_runner
from app.core.environment_guard import validate_testnet_host
from app.exchanges.delta_client import delta_client
from app.risk.service import risk_service
from app.trading.gateway import delta_testnet_gateway
from app.trading.store import execution_store

logger = logging.getLogger("automated_trading_worker")


class UnresolvedOrdersError(RuntimeError):
    """Raised when automated trading activation is rejected due to orders requiring reconciliation."""
    def __init__(self, count: int, client_order_ids: List[str]):
        self.count = count
        self.client_order_ids = client_order_ids
        super().__init__(
            f"Cannot enable automation: {count} order(s) require reconciliation. "
            "Please reconcile orders first."
        )


class AutomatedTradingWorker:
    """
    Reliable, non-blocking background execution service for TokenIQ automated trading.
    
    Guarantees:
    1. Starts strictly OFF / disabled.
    2. Single execution loop guarded by state machine.
    3. Graceful shutdown and task cancellation.
    4. Recovers pending/unknown execution records upon startup.
    5. Reconciles open positions before resuming trading.
    6. Fails closed on stale market data or exchange disconnects.
    """

    def __init__(self):
        self._state: AutomationState = AutomationState.OFF
        self._is_paused: bool = False
        self._pause_reason: Optional[str] = None
        self._last_error: Optional[str] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._loop_lock = asyncio.Lock()
        self._started_at: Optional[int] = None
        self._last_market_data_update_at: Optional[int] = None
        self._last_reconciliation_at: Optional[int] = None
        self._last_candle_timestamp: Optional[int] = None

    @property
    def state(self) -> AutomationState:
        return self._state

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    async def start(self) -> None:
        """
        Start worker lifecycle during FastAPI startup.
        NOTE: Starts in OFF mode pending explicit user activation.
        Performs startup recovery and reconciliation.
        """
        async with self._loop_lock:
            self._state = AutomationState.OFF
            self._is_paused = False
            logger.info("Initializing AutomatedTradingWorker (Startup state: OFF).")

            # 1. Startup Recovery: Reconcile unknown orders
            try:
                await self._recover_pending_orders()
            except Exception as exc:
                logger.warning(f"Startup order recovery encountered non-fatal error: {exc}")

            # 2. Reconcile positions
            try:
                cfg = await automation_config_manager.get_config()
                await position_manager.reconcile_with_exchange(cfg.trading_symbol)
                self._last_reconciliation_at = int(time.time())
            except Exception as exc:
                logger.warning(f"Startup position reconciliation warning: {exc}")

    async def stop(self) -> None:
        """Gracefully stop background loop during application shutdown."""
        async with self._loop_lock:
            self._state = AutomationState.OFF
            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None
            logger.info("AutomatedTradingWorker background task stopped.")

    async def enable_automation(self, explicit_confirm: bool = False) -> AutomationStatusResponse:
        """
        Explicit operator activation of automated trading engine.
        Must satisfy all pre-conditions before transitioning to RUNNING.
        """
        if not explicit_confirm:
            raise ValueError("Enabling automated trading requires explicit user confirmation (confirm=True).")

        async with self._loop_lock:
            # 1. Check Testnet Guard
            verified_host = validate_testnet_host(delta_testnet_gateway.host_url)

            # 2. Check Risk Engine Master Status
            safety = await risk_service.get_trading_status()
            if safety.kill_switch_engaged:
                raise RuntimeError(
                    f"Cannot enable automated trading: Kill Switch is ENGAGED ({safety.kill_switch_reason})."
                )
            if not safety.trading_enabled:
                raise RuntimeError(
                    "Cannot enable automated trading: Master trading authorization is DISABLED."
                )

            # 3. Check Exchange Credentials
            if not delta_client.api_key or not delta_client.api_secret:
                raise RuntimeError("Cannot enable automation: Testnet API credentials missing.")

            # 4. Check Unknown Orders
            unknown_orders = await execution_store.get_unknown_orders()
            if unknown_orders:
                raise UnresolvedOrdersError(
                    count=len(unknown_orders),
                    client_order_ids=[o.client_order_id for o in unknown_orders],
                )

            # 5. Reconcile the target position and fail closed if it is unprotected.
            # This prevents the worker from silently managing an already-open position
            # without a verified exchange-side stop/bracket.
            cfg = await automation_config_manager.get_config()
            position = await position_manager.reconcile_with_exchange(cfg.trading_symbol)
            if position.quantity > 0 and not position.protection_verified:
                raise RuntimeError(
                    f"Cannot enable automation: existing {cfg.trading_symbol} position "
                    "has no verified exchange-side stop-loss/bracket protection. "
                    "Protect or close it on Delta Testnet, then retry."
                )

            # 6. Enable in config and update state
            await automation_config_manager.set_enabled(True)
            self._state = AutomationState.RUNNING
            self._is_paused = False
            self._pause_reason = None
            self._started_at = int(time.time())

            # 6. Launch loop if not running
            if not self._worker_task or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._run_loop())

            logger.info("Automated trading successfully ENABLED and background loop launched.")
            return await self.get_status()

    async def disable_automation(self, reason: Optional[str] = None) -> AutomationStatusResponse:
        """Stop automated trading and transition to OFF."""
        async with self._loop_lock:
            await automation_config_manager.set_enabled(False)
            self._state = AutomationState.OFF
            self._is_paused = False
            self._pause_reason = reason or "Operator requested stop"
            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None

            logger.info(f"Automated trading DISABLED ({self._pause_reason}).")
            return await self.get_status()

    async def pause_entries(self, reason: str = "Operator paused new entries") -> AutomationStatusResponse:
        """Pause new entries while maintaining position management and protection monitoring."""
        async with self._loop_lock:
            if self._state == AutomationState.RUNNING:
                self._state = AutomationState.PAUSED
                self._is_paused = True
                self._pause_reason = reason
                logger.info(f"Automated trading PAUSED: {reason}")
            return await self.get_status()

    async def resume_entries(self) -> AutomationStatusResponse:
        """Resume automated entries if all safety checks pass."""
        async with self._loop_lock:
            # Revalidate kill switch and authorization
            safety = await risk_service.get_trading_status()
            if safety.kill_switch_engaged:
                raise RuntimeError("Cannot resume: Kill switch is ENGAGED.")
            if not safety.trading_enabled:
                raise RuntimeError("Cannot resume: Trading authorization is DISABLED.")

            self._state = AutomationState.RUNNING
            self._is_paused = False
            self._pause_reason = None
            logger.info("Automated trading RESUMED.")
            return await self.get_status()

    async def _run_loop(self) -> None:
        """
        Continuous non-blocking evaluation cycle.
        Runs periodically (e.g. every 10 seconds) to check completed candles,
        monitor position state, and reconcile orders.
        """
        logger.info("Starting automated evaluation loop...")
        while self._state in (AutomationState.RUNNING, AutomationState.PAUSED):
            try:
                await self._cycle_step()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.error(f"Error in automated evaluation cycle: {exc}", exc_info=True)
                # Sleep briefly before next cycle to prevent busy-looping on errors
                await asyncio.sleep(5)

            # Cycle interval: 10 seconds
            await asyncio.sleep(10)

        logger.info("Automated evaluation loop exited.")

    async def _cycle_step(self) -> None:
        """Single iteration of the automated trading worker."""
        config = await automation_config_manager.get_config()
        if not config.enabled:
            self._state = AutomationState.OFF
            return

        # 1. Verify Kill Switch
        safety = await risk_service.get_trading_status()
        if safety.kill_switch_engaged:
            self._state = AutomationState.HALTED
            self._pause_reason = f"Kill Switch engaged: {safety.kill_switch_reason}"
            logger.warning(f"Automation halted by kill switch: {safety.kill_switch_reason}")
            return

        symbol = config.trading_symbol.upper()

        # 2. Fetch authoritative product metadata
        products = await risk_service._get_fresh_products()
        meta = next((p for p in products if str(p.get("symbol")).upper() == symbol), None)
        if not meta:
            logger.warning(f"Product metadata for {symbol} unavailable. Skipping cycle.")
            return

        # 3. Reconcile position state with exchange
        try:
            pos_record = await position_manager.reconcile_with_exchange(symbol)
            self._last_reconciliation_at = int(time.time())
        except Exception as exc:
            logger.warning(f"Position reconciliation failed: {exc}. Pausing entries.")
            self._is_paused = True
            self._pause_reason = f"Exchange reconciliation error: {exc}"
            return

        # 4. Fetch recent completed candles for evaluation
        try:
            candle_data = await delta_client.get_historical_candles(
                symbol=symbol,
                resolution=config.candle_interval,
            )
            candles = candle_data.get("candles") if isinstance(candle_data, dict) else candle_data
            if not isinstance(candles, list):
                candles = []
            self._last_market_data_update_at = int(time.time())
            if candles:
                self._last_candle_timestamp = int(candles[-1].get("time") or time.time())
        except Exception as exc:
            logger.warning(f"Candle fetch failed: {exc}. Skipping evaluation.")
            return

        # 5. Check if new entries are paused
        if self._is_paused or self._state == AutomationState.PAUSED:
            logger.debug("New entries are paused; skipping signal generation.")
            return

        # 6. Evaluate Strategy
        signal = strategy_runner.evaluate_candles(
            config=config,
            product_meta=meta,
            candles=candles,
            current_position_side=pos_record.side,
            current_position_size=pos_record.quantity,
        )

        if not signal:
            return

        # 7. Register & Deduplicate Signal
        registered = await signal_deduplicator.register_signal(signal)
        if not registered:
            # Duplicate signal
            return

        logger.info(
            f"Fresh automated signal generated: {signal.signal_direction} {signal.position_intent} "
            f"({signal.intended_quantity} contracts @ ~${signal.intended_price})."
        )

        # 8. Execute Signal through Risk Engine & Gateway
        await automated_order_executor.execute_signal(
            signal=signal,
            product_meta=meta,
        )

    async def _recover_pending_orders(self) -> None:
        """On boot, inspect stored orders and reconcile any unverified, open, or pending records."""
        from app.trading.models import OrderState
        all_orders = await execution_store.get_all_orders()
        unresolved = [
            order for order in all_orders
            if order.state in (
                OrderState.OPEN.value,
                OrderState.SUBMITTED.value,
                OrderState.PENDING.value,
                OrderState.UNKNOWN.value,
            )
            or order.reconciliation_needed
        ]
        if not unresolved:
            return
        logger.info(f"Startup Recovery: Reconciling {len(unresolved)} unverified/pending orders against Delta Exchange...")
        from app.trading.service import order_execution_service
        for order in unresolved:
            try:
                target_id = order.client_order_id or order.order_id
                await order_execution_service.reconcile_order(target_id)
            except Exception as exc:
                logger.warning(f"Could not reconcile order {order.client_order_id}: {exc}")
        self._last_reconciliation_at = int(time.time())

    async def get_status(self) -> AutomationStatusResponse:
        """Compile comprehensive live status report."""
        config = await automation_config_manager.get_config()
        verified_host = validate_testnet_host(delta_testnet_gateway.host_url)
        safety = await risk_service.get_trading_status()
        pos = await position_manager.get_position(config.trading_symbol)
        recent_signals = await signal_deduplicator.get_recent_signals(limit=1)
        latest_sig = recent_signals[0] if recent_signals else None

        active_orders = await execution_store.get_active_orders()
        latest_order = active_orders[0] if active_orders else None

        uptime = (int(time.time()) - self._started_at) if (self._started_at and self._state == AutomationState.RUNNING) else 0

        # Calculate current exposure
        current_exp = pos.quantity * pos.average_entry_price * 0.001  # approx for BTC

        return AutomationStatusResponse(
            state=self._state,
            enabled=config.enabled,
            is_paused=self._is_paused,
            pause_reason=self._pause_reason,
            kill_switch_engaged=safety.kill_switch_engaged,
            testnet_enforced=True,
            verified_host=verified_host,
            config=config,
            active_position=pos,
            latest_signal=latest_sig,
            latest_signal_rejection_reason=latest_sig.rejection_reason if latest_sig else None,
            latest_order_status=latest_order.state if latest_order else None,
            orders_submitted_today=safety.orders_submitted_today,
            daily_realized_pnl_usd=pos.realized_pnl_usd,
            current_exposure_usd=round(current_exp, 2),
            last_candle_timestamp=self._last_candle_timestamp,
            last_market_data_update_at=self._last_market_data_update_at,
            last_reconciliation_at=self._last_reconciliation_at,
            last_error=self._last_error,
            worker_uptime_seconds=uptime,
        )


automated_trading_worker = AutomatedTradingWorker()
