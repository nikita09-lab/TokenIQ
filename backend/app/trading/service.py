import asyncio
from decimal import Decimal
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.environment_guard import validate_testnet_host
from app.risk.models import RiskCheckRequest
from app.risk.service import risk_service
from app.trading.gateway import (
    delta_testnet_gateway,
    ExchangeOrderRejectedError,
    OrderSubmissionTimeoutError,
)
from app.trading.models import (
    ExecutionStatusResponse,
    OrderCancelRequest,
    OrderConfirmRequest,
    OrderExecutionRecord,
    OrderPreviewRequest,
    OrderPreviewResponse,
    OrderState,
)
from app.trading.store import execution_store

logger = logging.getLogger("order_execution_service")


class OrderExecutionService:
    """
    Dedicated Order Execution Service for TokenIQ Phase 7.2.
    Enforces two-stage manual confirmation, mandatory pre-trade risk evaluation,
    exact testnet allowlist guardrails, and persistent reconciliation.
    """

    def __init__(self):
        self._submission_lock = asyncio.Lock()

    async def get_execution_status(self) -> ExecutionStatusResponse:
        """Retrieve consolidated status and safety posture of the execution engine."""
        verified_host = validate_testnet_host(delta_testnet_gateway.host_url)
        safety_status = await risk_service.get_trading_status()
        active_orders = await execution_store.get_active_orders()
        unknown_orders = await execution_store.get_unknown_orders()

        return ExecutionStatusResponse(
            service_ready=True,
            testnet_enforced=True,
            verified_host=verified_host,
            trading_enabled=safety_status.trading_enabled,
            kill_switch_engaged=safety_status.kill_switch_engaged,
            kill_switch_reason=safety_status.kill_switch_reason,
            orders_submitted_today=safety_status.orders_submitted_today,
            active_local_orders_count=len(active_orders),
            unknown_orders_count=len(unknown_orders),
        )

    async def create_order_preview(self, request: OrderPreviewRequest) -> OrderPreviewResponse:
        """
        Stage 1: Validate proposed order, check product specs, calculate exact notional,
        evaluate risk rules in dry-run mode, and generate an expiring preview with TTL.
        STRICTLY PREVIEW: Never places an order on the exchange.
        """
        # 1. Environment Guard Check
        verified_host = validate_testnet_host(delta_testnet_gateway.host_url)

        # 2. Check Product Metadata
        symbol_upper = request.symbol.upper()
        products_list = await risk_service._get_fresh_products()
        meta = next(
            (p for p in products_list if str(p.get("symbol")).upper() == symbol_upper),
            None,
        )
        if not meta:
            raise ValueError(f"Product metadata for symbol '{symbol_upper}' is unavailable from Delta Exchange.")

        product_id = int(meta.get("id") or meta.get("product_id") or 0)
        contract_val = float(meta.get("contract_value") or 1.0)
        tick_size = float(meta.get("tick_size") or 0.1)

        # 3. Validate Tick Size & Decimals
        price_for_eval = request.price
        if request.order_type == "limit_order":
            if price_for_eval is None or price_for_eval <= 0:
                raise ValueError("Limit orders must include a valid positive price.")
            # Verify price conforms to tick size
            tick_dec = Decimal(str(tick_size))
            price_dec = Decimal(str(price_for_eval))
            remainder = price_dec % tick_dec
            if remainder != Decimal("0") and abs(remainder - tick_dec) > Decimal("0.000001"):
                raise ValueError(
                    f"Price {price_for_eval} does not conform to product tick size {tick_size}."
                )
        else:
            # For market order evaluation, use a nominal price estimate if provided or placeholder
            price_for_eval = request.price or 100.0

        # 4. Calculate Exact Notional
        d_qty = Decimal(str(request.quantity))
        d_cval = Decimal(str(contract_val))
        d_price = Decimal(str(price_for_eval))
        estimated_notional_usd = float(d_qty * d_cval * d_price)

        # 5. Pre-trade Risk Check (Dry-Run Evaluation)
        now_ts = int(time.time())
        signal_id = request.client_order_id or f"preview_sig_{symbol_upper}_{now_ts}_{uuid.uuid4().hex[:4]}"
        risk_req = RiskCheckRequest(
            symbol=symbol_upper,
            side=request.side,
            position_intent=request.position_intent,
            quantity=request.quantity,
            price=price_for_eval,
            stop_loss=request.stop_loss,
            signal_id=signal_id,
            timestamp=now_ts,
            strategy_id="manual_order_preview",
        )

        risk_res = await risk_service.check_signal_risk(risk_req)

        # Check if kill switch is engaged
        safety_status = await risk_service.get_trading_status()
        can_submit = (
            risk_res.approved
            and not safety_status.kill_switch_engaged
            and safety_status.trading_enabled
        )

        preview_id = f"prev_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        ttl_seconds = 60
        expires_at = now_ts + ttl_seconds

        preview = OrderPreviewResponse(
            preview_id=preview_id,
            symbol=symbol_upper,
            product_id=product_id,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            stop_loss=request.stop_loss,
            contract_value=contract_val,
            tick_size=tick_size,
            estimated_notional_usd=estimated_notional_usd,
            environment="TESTNET",
            verified_testnet_host=verified_host,
            created_at=now_ts,
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
            can_submit=can_submit,
            risk_decision=risk_res.decision,
            risk_reasons=risk_res.reasons,
            rules_evaluated=[r.model_dump() for r in risk_res.rules_evaluated],
        )

        await execution_store.save_preview(preview)
        return preview

    async def confirm_and_submit_order(self, request: OrderConfirmRequest) -> OrderExecutionRecord:
        """
        Stage 2: Explicit confirmation and submission.
        - Verifies preview is active, unexpired, and not replayed.
        - Atomically consumes preview under concurrency lock.
        - Reruns mandatory live pre-submission risk check.
        - Dispatches order to Delta Exchange Testnet.
        - Increments order count only upon genuine exchange submission.
        - Handles timeout as UNKNOWN state for reconciliation.
        """
        if not request.confirm:
            raise ValueError("Order confirmation must explicitly set 'confirm': true.")

        async with self._submission_lock:
            # 1. Atomically consume preview (prevents replay / concurrent double execution)
            preview = await execution_store.consume_preview(request.preview_id)
            if not preview:
                raise ValueError(
                    f"Order preview '{request.preview_id}' is invalid, expired, or was already consumed. "
                    "Please generate a fresh preview before confirming."
                )

            # 2. Strict Kill Switch & Trading Authorization Check
            safety_status = await risk_service.get_trading_status()
            if safety_status.kill_switch_engaged:
                raise RuntimeError(
                    f"Order submission blocked: Emergency Kill Switch is ENGAGED. "
                    f"Reason: {safety_status.kill_switch_reason or 'Halt active'}."
                )
            if not safety_status.trading_enabled:
                raise RuntimeError(
                    "Order submission blocked: Master trading authorization is DISABLED."
                )

            # 3. Mandatory Pre-Submission Risk Check
            now_ts = int(time.time())
            fresh_signal_id = f"ord_exec_{preview.symbol}_{now_ts}_{uuid.uuid4().hex[:4]}"
            risk_req = RiskCheckRequest(
                symbol=preview.symbol,
                side=preview.side,
                quantity=preview.quantity,
                price=preview.price or 100.0,
                stop_loss=preview.stop_loss,
                signal_id=fresh_signal_id,
                timestamp=now_ts,
                strategy_id="manual_order_confirm",
            )

            risk_res = await risk_service.check_signal_risk(risk_req)
            if not risk_res.approved:
                # Create rejected record
                record = OrderExecutionRecord(
                    preview_id=preview.preview_id,
                    client_order_id=f"tokiq_rej_{now_ts}",
                    symbol=preview.symbol,
                    product_id=preview.product_id,
                    side=preview.side,
                    order_type=preview.order_type,
                    size=preview.quantity,
                    unfilled_size=preview.quantity,
                    limit_price=preview.price,
                    stop_loss=preview.stop_loss,
                    state=OrderState.REJECTED.value,
                    notional_usd=preview.estimated_notional_usd,
                    created_at=now_ts,
                    updated_at=now_ts,
                    error_message=f"Risk check failed: {'; '.join(risk_res.reasons)}",
                )
                await execution_store.save_order(record)
                raise RuntimeError(f"Order submission failed pre-trade risk check: {'; '.join(risk_res.reasons)}")

            # 4. Generate unique client order ID
            client_order_id = f"tokiq_{now_ts}_{uuid.uuid4().hex[:6]}"

            # Create initial submission record
            record = OrderExecutionRecord(
                preview_id=preview.preview_id,
                client_order_id=client_order_id,
                symbol=preview.symbol,
                product_id=preview.product_id,
                side=preview.side,
                order_type=preview.order_type,
                size=preview.quantity,
                unfilled_size=preview.quantity,
                limit_price=preview.price,
                stop_loss=preview.stop_loss,
                state=OrderState.SUBMITTED.value,
                notional_usd=preview.estimated_notional_usd,
                created_at=now_ts,
                updated_at=now_ts,
                confirmed_at=now_ts,
            )
            await execution_store.save_order(record)

            # 5. Dispatch to Delta Testnet Gateway
            try:
                exchange_res = await delta_testnet_gateway.submit_order(
                    product_id=preview.product_id,
                    size=preview.quantity,
                    side=preview.side,
                    order_type=preview.order_type,
                    limit_price=preview.price,
                    client_order_id=client_order_id,
                    stop_loss_price=preview.stop_loss,
                )

                # Genuine submission succeeded! Increment order counter in safety state.
                risk_service.record_order_submitted()

                # Update record with exchange details
                record.order_id = str(exchange_res.get("id"))
                record.state = OrderState.OPEN.value
                record.unfilled_size = float(exchange_res.get("unfilled_size") or preview.quantity)
                record.submitted_at = int(time.time())
                record.exchange_response = exchange_res
                record.exchange_state = str(exchange_res.get("state") or "open")
                await execution_store.save_order(record)
                return record

            except OrderSubmissionTimeoutError as timeout_exc:
                # Crucial Safety Rule: Network timeout produces UNKNOWN state; NEVER automatically retry!
                logger.error(
                    f"Order submission timeout for {client_order_id}. Setting state to UNKNOWN."
                )
                record.state = OrderState.UNKNOWN.value
                record.reconciliation_needed = True
                record.error_message = str(timeout_exc)
                await execution_store.save_order(record)
                return record

            except ExchangeOrderRejectedError as rej_exc:
                logger.warning(f"Exchange rejected order {client_order_id}: {rej_exc}")
                record.state = OrderState.REJECTED.value
                record.error_message = str(rej_exc)
                await execution_store.save_order(record)
                raise rej_exc

            except Exception as exc:
                logger.error(f"Unexpected error submitting order {client_order_id}: {exc}")
                record.state = OrderState.REJECTED.value
                record.error_message = str(exc)
                await execution_store.save_order(record)
                raise exc

    async def reconcile_order(self, order_id_or_client_id: str) -> OrderExecutionRecord:
        """
        Reconcile local execution record against live exchange state.
        Resolves UNKNOWN states safely without re-submitting orders.
        """
        record = await execution_store.get_order_by_id(order_id_or_client_id)
        if not record:
            raise ValueError(f"Order '{order_id_or_client_id}' not found in execution store.")

        record.reconciliation_last_at = int(time.time())

        # 1. Query open orders on exchange with explicit communication error handling
        try:
            open_orders = await delta_testnet_gateway.list_open_orders(product_id=record.product_id)
        except Exception as exc:
            # Preserve or transition to explicit UNKNOWN state when exchange status cannot be verified
            logger.warning(
                f"Exchange query failed during reconciliation of order {record.client_order_id}: {exc}"
            )
            record.state = OrderState.UNKNOWN.value
            record.exchange_state = "unverified"
            record.reconciliation_needed = True
            record.error_message = f"Reconciliation blocked by exchange communication error: {exc}"
            await execution_store.save_order(record)
            raise RuntimeError(
                f"Cannot reconcile order '{record.client_order_id}': Exchange unreachable ({exc}). "
                "Order status remains UNKNOWN pending verified exchange connectivity."
            )

        # Increment verified reconciliation attempts only after a successful exchange query
        record.reconciliation_attempts += 1

        matched_open = next(
            (
                o for o in open_orders
                if str(o.get("id")) == str(record.order_id)
                or str(o.get("client_order_id")) == str(record.client_order_id)
            ),
            None,
        )

        if matched_open:
            record.order_id = str(matched_open.get("id"))
            record.state = OrderState.OPEN.value
            record.exchange_state = str(matched_open.get("state") or "open")
            record.unfilled_size = float(matched_open.get("unfilled_size") or 0.0)
            record.reconciliation_needed = False
            record.error_message = None
            await execution_store.save_order(record)
            return record

        # 2. Check single order status if we have order_id
        is_conclusively_not_found = False
        if record.order_id:
            try:
                order_detail = await delta_testnet_gateway.get_order_by_id(record.order_id)
                if order_detail:
                    if order_detail.get("_not_found_on_exchange"):
                        is_conclusively_not_found = True
                    else:
                        state_raw = str(order_detail.get("state") or "").lower()
                        if "fill" in state_raw:
                            record.state = OrderState.FILLED.value
                        elif "cancel" in state_raw:
                            record.state = OrderState.CANCELLED.value
                        elif "open" in state_raw or "pending" in state_raw:
                            record.state = OrderState.OPEN.value
                        record.exchange_state = state_raw
                        record.reconciliation_needed = False
                        record.error_message = None
                        await execution_store.save_order(record)
                        return record
            except Exception as exc:
                logger.warning(f"Failed to fetch order detail for {record.order_id}: {exc}")
                record.state = OrderState.UNKNOWN.value
                record.exchange_state = "unverified"
                record.reconciliation_needed = True
                record.error_message = f"Reconciliation blocked by exchange communication error: {exc}"
                await execution_store.save_order(record)
                raise RuntimeError(
                    f"Cannot reconcile order '{record.client_order_id}': Exchange detail query failed ({exc}). "
                    "Order status remains UNKNOWN pending verified exchange connectivity."
                )

        # 3. Conclusively mark as REJECTED if exchange proved order does not exist.
        # If missing from open orders and not conclusively verified on exchange, mark UNKNOWN.
        if is_conclusively_not_found:
            record.state = OrderState.REJECTED.value
            record.exchange_state = "not_found"
            record.reconciliation_needed = False
            record.error_message = "Reconciliation conclusive: Order not found on Delta Exchange Testnet."
            await execution_store.save_order(record)
        elif record.state in (OrderState.OPEN.value, OrderState.SUBMITTED.value, OrderState.PENDING.value):
            record.state = OrderState.UNKNOWN.value
            record.exchange_state = "unverified"
            record.reconciliation_needed = True
            record.error_message = "Order absent from open orders but exchange status inconclusive. Marked UNKNOWN pending verification."
            await execution_store.save_order(record)
        else:
            await execution_store.save_order(record)

        return record

    async def cancel_order(self, order_id: str, reason: Optional[str] = None) -> OrderExecutionRecord:
        """
        Cancel an open order on Delta Exchange Testnet.
        Validates order eligibility before dispatching cancellation request.
        """
        record = await execution_store.get_order_by_id(order_id)
        if not record:
            raise ValueError(f"Order '{order_id}' was not found.")

        # Validate order is in an open/cancellable state
        if record.state not in (OrderState.OPEN.value, OrderState.PENDING.value, OrderState.SUBMITTED.value):
            raise ValueError(
                f"Order '{order_id}' cannot be cancelled because its current state is '{record.state}'."
            )

        # Dispatch cancellation
        exchange_order_id = record.order_id or order_id
        await delta_testnet_gateway.cancel_order(
            product_id=record.product_id,
            order_id=exchange_order_id,
        )

        record.state = OrderState.CANCELLED.value
        record.exchange_state = "cancelled"
        record.error_message = reason or "Manually cancelled by user"
        await execution_store.save_order(record)
        return record

    async def list_orders(self) -> List[OrderExecutionRecord]:
        """List all tracked local order records sorted chronologically."""
        return await execution_store.get_all_orders()

    async def get_order(self, order_id: str) -> OrderExecutionRecord:
        """Retrieve a specific order execution record."""
        record = await execution_store.get_order_by_id(order_id)
        if not record:
            raise ValueError(f"Order '{order_id}' not found.")
        return record


order_execution_service = OrderExecutionService()
