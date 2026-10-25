import asyncio
from decimal import Decimal
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from app.automation.config import automation_config_manager
from app.automation.dedup import signal_deduplicator
from app.automation.models import (
    AutomatedSignal,
    PositionLifecycleState,
    PositionStateRecord,
    SignalLifecycleState,
)
from app.automation.position_manager import position_manager
from app.automation.protection import protection_manager, ProtectionPlacementError
from app.core.environment_guard import validate_testnet_host
from app.risk.models import RiskCheckRequest
from app.risk.service import risk_service
from app.trading.gateway import (
    delta_testnet_gateway,
    ExchangeOrderRejectedError,
    OrderSubmissionTimeoutError,
)
from app.trading.models import OrderExecutionRecord, OrderState
from app.trading.store import execution_store

logger = logging.getLogger("automated_order_executor")


class OrderExecutionBlockedError(RuntimeError):
    """Raised when risk check, kill switch, or environment guard blocks execution."""
    pass


class AutomatedOrderExecutor:
    """
    Executes automated trading signals safely against Delta Exchange Testnet.
    
    Guarantees:
    1. Zero orders without Risk & Safety Engine approval.
    2. Zero production execution (strict environment guard).
    3. Replay & Duplicate Prevention (durable idempotency + mutex).
    4. Execution intent persisted BEFORE exchange HTTP call.
    5. Network timeouts result in UNKNOWN state, NEVER automatic retry.
    6. Stop-loss protection verification upon fill; emergency close on protection failure.
    """

    def __init__(self):
        self._execution_lock = asyncio.Lock()

    async def execute_signal(
        self,
        signal: AutomatedSignal,
        product_meta: Dict[str, Any],
    ) -> Optional[OrderExecutionRecord]:
        """
        Executes a validated automated trading signal through the full risk and exchange pipeline.
        """
        async with self._execution_lock:
            # 1. Environment Guard Check
            validate_testnet_host(delta_testnet_gateway.host_url)

            # 2. Check Automation Master State & Kill Switch
            config = await automation_config_manager.get_config()
            if not config.enabled:
                rejection = "Automated execution blocked: Master automation is disabled."
                logger.warning(rejection)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            safety_status = await risk_service.get_trading_status()
            if safety_status.kill_switch_engaged:
                rejection = f"Automated execution blocked: Kill Switch is ENGAGED ({safety_status.kill_switch_reason})."
                logger.warning(rejection)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            if not safety_status.trading_enabled:
                rejection = "Automated execution blocked: Master trading authorization is DISABLED."
                logger.warning(rejection)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            # 3. Check Signal Freshness
            now = int(time.time())
            signal_age = now - signal.created_at
            if signal_age > config.strategy_parameters.get("max_signal_age_seconds", 300):
                rejection = f"Signal is stale ({signal_age}s old > max allowed)."
                logger.warning(rejection)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            # 4. Check Cooldown
            in_cooldown, remaining = await position_manager.check_cooldown(
                signal.symbol, config.cooldown_period_seconds
            )
            if in_cooldown:
                rejection = f"Trading cooldown active for {signal.symbol} ({remaining}s remaining)."
                logger.info(rejection)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            # 5. Extract Product Specifications & Sizing
            product_id = int(product_meta.get("id") or product_meta.get("product_id") or 0)
            contract_val = float(product_meta.get("contract_value") or 1.0)
            tick_size = float(product_meta.get("tick_size") or 0.1)

            order_side = "BUY" if signal.signal_direction in ("BUY", "EXIT_SHORT") else "SELL"
            notional_usd = float(
                Decimal(str(signal.intended_quantity))
                * Decimal(str(contract_val))
                * Decimal(str(signal.intended_price))
            )

            # 6. Pre-trade Risk & Safety Engine Evaluation
            risk_req = RiskCheckRequest(
                symbol=signal.symbol,
                side=order_side,
                position_intent=signal.position_intent,
                quantity=signal.intended_quantity,
                price=signal.intended_price,
                stop_loss=signal.stop_loss_price,
                signal_id=signal.signal_id,
                timestamp=signal.created_at,
                strategy_id=signal.strategy_id,
            )

            risk_res = await risk_service.check_signal_risk(risk_req)
            if not risk_res.approved:
                rejection = f"Risk check failed: {'; '.join(risk_res.reasons)}"
                logger.warning(f"Order rejected by risk engine: {rejection}")
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=rejection
                )
                return None

            await signal_deduplicator.update_lifecycle(
                signal.signal_id, SignalLifecycleState.RISK_APPROVED
            )

            # 7. Generate Client Order ID & Persist Execution Intent BEFORE exchange dispatch
            client_order_id = f"tokiq_auto_{now}_{uuid.uuid4().hex[:6]}"
            order_record = OrderExecutionRecord(
                preview_id=f"auto_prev_{signal.signal_id}",
                client_order_id=client_order_id,
                symbol=signal.symbol,
                product_id=product_id,
                side=order_side,
                order_type="market_order",  # Automated strategies use market entry on candle close
                size=signal.intended_quantity,
                unfilled_size=signal.intended_quantity,
                limit_price=None,
                stop_loss=signal.stop_loss_price,
                state=OrderState.SUBMITTED.value,
                notional_usd=notional_usd,
                created_at=now,
                updated_at=now,
                confirmed_at=now,
            )
            await execution_store.save_order(order_record)
            await signal_deduplicator.update_lifecycle(
                signal.signal_id,
                SignalLifecycleState.SUBMITTED,
                client_order_id=client_order_id,
            )

            # Update position lifecycle to pending
            if signal.position_intent in ("OPEN_LONG", "OPEN_SHORT"):
                await position_manager.update_lifecycle_state(
                    signal.symbol,
                    PositionLifecycleState.ENTRY_PENDING,
                    product_id=product_id,
                    entry_client_order_id=client_order_id,
                )
            else:
                await position_manager.update_lifecycle_state(
                    signal.symbol,
                    PositionLifecycleState.EXIT_PENDING,
                )

            # 8. Dispatch Order to Delta Exchange Testnet
            try:
                exchange_res = await delta_testnet_gateway.submit_order(
                    product_id=product_id,
                    size=signal.intended_quantity,
                    side=order_side,
                    order_type="market_order",
                    client_order_id=client_order_id,
                )

                # Genuine submission succeeded! Increment daily submitted orders
                risk_service.record_order_submitted()

                exchange_order_id = str(exchange_res.get("id"))
                order_record.order_id = exchange_order_id
                order_record.submitted_at = int(time.time())
                order_record.state = OrderState.OPEN.value
                order_record.exchange_response = exchange_res
                order_record.exchange_state = str(exchange_res.get("state") or "open")
                await execution_store.save_order(order_record)

                await signal_deduplicator.update_lifecycle(
                    signal.signal_id,
                    SignalLifecycleState.SUBMITTED,
                    exchange_order_id=exchange_order_id,
                )

                # 9. Handle Post-Fill Position & Protective Stop Placement
                await self._handle_post_order_execution(
                    signal=signal,
                    order_record=order_record,
                    exchange_res=exchange_res,
                    product_meta=product_meta,
                )

                return order_record

            except OrderSubmissionTimeoutError as timeout_err:
                logger.error(
                    f"Submission timeout for {client_order_id}. Setting UNKNOWN state for reconciliation."
                )
                order_record.state = OrderState.UNKNOWN.value
                order_record.reconciliation_needed = True
                order_record.error_message = str(timeout_err)
                await execution_store.save_order(order_record)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.UNKNOWN, rejection_reason=str(timeout_err)
                )
                return order_record

            except ExchangeOrderRejectedError as rej_err:
                logger.warning(f"Exchange rejected automated order {client_order_id}: {rej_err}")
                order_record.state = OrderState.REJECTED.value
                order_record.error_message = str(rej_err)
                await execution_store.save_order(order_record)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.REJECTED, rejection_reason=str(rej_err)
                )
                # Reconcile position state back to flat/open
                await position_manager.reconcile_with_exchange(signal.symbol)
                return order_record

            except Exception as exc:
                logger.error(f"Unexpected error executing automated order: {exc}")
                order_record.state = OrderState.REJECTED.value
                order_record.error_message = str(exc)
                await execution_store.save_order(order_record)
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.FAILED, rejection_reason=str(exc)
                )
                await position_manager.reconcile_with_exchange(signal.symbol)
                return order_record

    async def _handle_post_order_execution(
        self,
        signal: AutomatedSignal,
        order_record: OrderExecutionRecord,
        exchange_res: Dict[str, Any],
        product_meta: Dict[str, Any],
    ) -> None:
        """
        Processes fills, updates position state, and verifies stop-loss protection.
        """
        # Reconcile authoritative position with exchange
        pos = await position_manager.reconcile_with_exchange(signal.symbol)

        if signal.position_intent in ("CLOSE_LONG", "CLOSE_SHORT"):
            if pos.lifecycle_state == PositionLifecycleState.FLAT:
                await signal_deduplicator.update_lifecycle(
                    signal.signal_id, SignalLifecycleState.FILLED
                )
                logger.info(f"Position exit confirmed for {signal.symbol}. Position is now FLAT.")
            return

        # For Entry orders: If position is open, verify or place protective stop-loss
        if pos.lifecycle_state in (PositionLifecycleState.OPEN, PositionLifecycleState.ENTRY_PENDING):
            if signal.stop_loss_price and pos.quantity > 0:
                pos_side = pos.side or ("LONG" if signal.signal_direction == "BUY" else "SHORT")
                try:
                    stop_order = await protection_manager.place_protective_stop(
                        product_id=pos.product_id,
                        symbol=signal.symbol,
                        position_side=pos_side,
                        quantity=pos.quantity,
                        stop_price=signal.stop_loss_price,
                        take_profit_price=signal.take_profit_price,
                    )
                    await position_manager.update_lifecycle_state(
                        signal.symbol,
                        PositionLifecycleState.PROTECTION_VERIFIED,
                        stop_loss_order_id=str(stop_order.get("id")),
                        stop_loss_price=signal.stop_loss_price,
                        protection_verified=True,
                    )
                    await signal_deduplicator.update_lifecycle(
                        signal.signal_id, SignalLifecycleState.FILLED
                    )
                    logger.info(f"Protection verified for {signal.symbol} at stop {signal.stop_loss_price}.")
                except ProtectionPlacementError as prot_err:
                    logger.critical(
                        f"CRITICAL SAFETY TRIGGER: Stop-loss placement failed for {signal.symbol} ({prot_err}). "
                        "Executing emergency liquidation to prevent unprotected exposure!"
                    )
                    # Emergency protocol
                    try:
                        await protection_manager.execute_emergency_position_close(
                            product_id=pos.product_id,
                            symbol=signal.symbol,
                            position_side=pos_side,
                            quantity=pos.quantity,
                            reason=f"Protection placement failed: {prot_err}",
                        )
                    finally:
                        await position_manager.reconcile_with_exchange(signal.symbol)


automated_order_executor = AutomatedOrderExecutor()
