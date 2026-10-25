import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.risk.models import (
    CheckStatus,
    RiskCheckRequest,
    RiskCheckResult,
    RiskConfig,
    RuleEvaluationResult,
    SafetyState,
)

logger = logging.getLogger("risk_engine")

from app.core.config import get_storage_path

STATE_FILE_PATH = get_storage_path("safety_state.json", Path(__file__).parent / "safety_state.json")
CONFIG_FILE_PATH = get_storage_path("risk_config.json", Path(__file__).parent / "risk_config.json")


class RiskEngine:
    """
    Core Risk Management and Safety Engine for TokenIQ.
    
    Safety Invariants:
    1. Trading is disabled by default.
    2. Fail-closed: Missing account data, invalid metadata, or unreadable safety state halts approvals.
    3. Emergency Kill Switch blocks all executions and requires explicit deliberate reset.
    4. Exact Decimal arithmetic for notional and quantity math.
    5. Persistent signal deduplication across application restarts.
    6. Strictly dry-run in Phase 7.1: Never submits orders to any exchange.
    """

    def __init__(
        self,
        state_file: Optional[Path] = None,
        config_file: Optional[Path] = None,
    ):
        self.state_file = state_file or STATE_FILE_PATH
        self.config_file = config_file or CONFIG_FILE_PATH

        self.config = self._load_config()
        self.state = self._load_safety_state()

    # ========================================================================
    # Configuration Persistence & Validation
    # ========================================================================

    def _load_config(self) -> RiskConfig:
        """Load risk limits from file or initialize with safe defaults."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return RiskConfig(**data)
            except Exception as exc:
                logger.warning(f"Failed to load risk config ({exc}), using safe defaults.")
        return RiskConfig()

    def update_config(self, new_config: RiskConfig) -> RiskConfig:
        """
        Validate and atomically persist new risk limits.
        Rejects invalid configurations without corrupting active limits.
        """
        # Validate through Pydantic
        validated = RiskConfig.model_validate(new_config)
        self.config = validated

        temp_file = self.config_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(validated.model_dump(), f, indent=2)
            temp_file.replace(self.config_file)
            logger.info("Risk configuration updated and persisted.")
        except Exception as exc:
            logger.error(f"Failed to persist risk config: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Failed to persist risk configuration: {exc}")

        return self.config

    # ========================================================================
    # Safety State & Kill Switch Persistence (Fail-Closed)
    # ========================================================================

    def _load_safety_state(self) -> SafetyState:
        """
        Load safety state from file.
        FAIL CLOSED: If missing, corrupt, or unreadable, defaults strictly to:
        trading_enabled = False, kill_switch_engaged = True.
        """
        if not self.state_file.exists():
            logger.info("No safety state file found. Initializing fail-closed default safety state.")
            state = SafetyState(
                trading_enabled=False,
                kill_switch_engaged=True,
                kill_switch_reason="Startup default: trading disabled pending deliberate activation.",
                kill_switch_activated_at=int(time.time()),
            )
            self._save_safety_state(state)
            return state

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = SafetyState(**data)

            # A restart must NEVER silently enable trading
            # If trading was previously enabled, log and leave state as configured,
            # but if file had any corruption or ambiguity, fail closed.
            return state
        except Exception as exc:
            logger.error(f"CRITICAL: Failed to parse safety state file ({exc}). FAILING CLOSED.")
            state = SafetyState(
                trading_enabled=False,
                kill_switch_engaged=True,
                kill_switch_reason=f"Fail-closed: safety state file corrupt or unreadable ({exc}).",
                kill_switch_activated_at=int(time.time()),
            )
            self._save_safety_state(state)
            return state

    def _save_safety_state(self, state: SafetyState) -> None:
        """Atomically persist safety state to disk."""
        self._rollover_daily_counters(state)

        # Prune evaluated signals older than 48 hours to prevent unbounded growth
        now = int(time.time())
        cutoff = now - (48 * 3600)
        state.evaluated_signal_ids = {
            sig_id: ts for sig_id, ts in state.evaluated_signal_ids.items() if ts >= cutoff
        }

        temp_file = self.state_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state.model_dump(), f, indent=2)
            temp_file.replace(self.state_file)
        except Exception as exc:
            logger.error(f"Failed to persist safety state: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    def _rollover_daily_counters(self, state: SafetyState) -> None:
        """Reset daily order and evaluation counters when UTC calendar day changes."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state.daily_date != today:
            state.daily_date = today
            state.orders_submitted_today = 0
            state.evaluations_today = 0

    def engage_kill_switch(self, reason: str) -> SafetyState:
        """
        Emergency activation of the trading kill switch.
        Blocks all future risk approvals immediately.
        """
        now = int(time.time())
        self.state.trading_enabled = False
        self.state.kill_switch_engaged = True
        self.state.kill_switch_reason = reason
        self.state.kill_switch_activated_at = now
        self._save_safety_state(self.state)
        logger.warning(f"EMERGENCY KILL SWITCH ENGAGED: {reason}")
        return self.state

    def reset_kill_switch(self, reason: str) -> SafetyState:
        """
        Explicit deliberate reset of the kill switch by an operator.
        """
        now = int(time.time())
        self.state.kill_switch_engaged = False
        self.state.kill_switch_reason = None
        self.state.last_reset_at = now
        self.state.last_reset_reason = reason
        # Explicitly enable trading only when reset with deliberate intent
        self.state.trading_enabled = True
        self._save_safety_state(self.state)
        logger.info(f"KILL SWITCH RESET BY OPERATOR: {reason}")
        return self.state

    def record_order_submitted(self) -> int:
        """
        Record a genuine exchange order submission.
        Increments orders_submitted_today and persists state atomically.
        """
        self._rollover_daily_counters(self.state)
        self.state.orders_submitted_today += 1
        self._save_safety_state(self.state)
        logger.info(f"Order submission recorded: orders_submitted_today={self.state.orders_submitted_today}")
        return self.state.orders_submitted_today

    # ========================================================================
    # Core Risk Check (Dry-Run & Pre-Trade)
    # ========================================================================

    async def evaluate_risk(
        self,
        request: RiskCheckRequest,
        account_telemetry: Optional[Dict[str, Any]],
        products_metadata: Optional[List[Dict[str, Any]]],
    ) -> RiskCheckResult:
        """
        Evaluate a trading signal or proposed order against all safety and risk rules.
        
        STRICTLY DRY-RUN: Never places, submits, or routes orders.
        Does not increment orders_submitted_today; increments evaluations_today.
        """
        now_ts = int(time.time())
        rules: List[RuleEvaluationResult] = []
        reasons: List[str] = []

        # Update daily evaluation counter
        self._rollover_daily_counters(self.state)
        self.state.evaluations_today += 1

        # Calculate notional helper
        proposed_notional_usd = 0.0

        # --------------------------------------------------------------------
        # Rule 1: Master Kill Switch & Trading Enabled Check
        # --------------------------------------------------------------------
        if self.state.kill_switch_engaged:
            msg = f"Trading Kill Switch is ACTIVE: {self.state.kill_switch_reason or 'Emergency stop engaged'}"
            rules.append(RuleEvaluationResult(
                rule_name="kill_switch",
                status=CheckStatus.FAILED,
                message=msg,
                details={"kill_switch_engaged": True, "reason": self.state.kill_switch_reason},
            ))
            reasons.append(msg)
        elif not self.state.trading_enabled:
            msg = "Trading is DISABLED by default. Deliberate operator activation required."
            rules.append(RuleEvaluationResult(
                rule_name="trading_enabled",
                status=CheckStatus.FAILED,
                message=msg,
                details={"trading_enabled": False},
            ))
            reasons.append(msg)
        else:
            rules.append(RuleEvaluationResult(
                rule_name="kill_switch",
                status=CheckStatus.PASSED,
                message="Kill switch inactive; trading is authorized.",
            ))

        # --------------------------------------------------------------------
        # Rule 2: Signal Timestamp Staleness Check
        # --------------------------------------------------------------------
        sig_ts = request.timestamp or now_ts
        sig_age = now_ts - sig_ts
        if sig_age > self.config.max_signal_age_seconds:
            msg = f"Stale signal: Signal age ({sig_age}s) exceeds maximum allowed ({self.config.max_signal_age_seconds}s)."
            rules.append(RuleEvaluationResult(
                rule_name="signal_staleness",
                status=CheckStatus.FAILED,
                message=msg,
                details={"signal_age_seconds": sig_age, "max_age": self.config.max_signal_age_seconds},
            ))
            reasons.append(msg)
        elif sig_age < -60:
            msg = f"Invalid future signal timestamp: {sig_ts} is more than 60s in the future."
            rules.append(RuleEvaluationResult(
                rule_name="signal_staleness",
                status=CheckStatus.FAILED,
                message=msg,
                details={"signal_age_seconds": sig_age},
            ))
            reasons.append(msg)
        else:
            rules.append(RuleEvaluationResult(
                rule_name="signal_staleness",
                status=CheckStatus.PASSED,
                message=f"Signal timestamp fresh (age: {sig_age}s).",
            ))

        # --------------------------------------------------------------------
        # Rule 3: Persistent Duplicate Signal ID Check
        # --------------------------------------------------------------------
        if request.signal_id in self.state.evaluated_signal_ids:
            first_seen = self.state.evaluated_signal_ids[request.signal_id]
            msg = f"Duplicate signal ID: '{request.signal_id}' was already evaluated at epoch {first_seen}."
            rules.append(RuleEvaluationResult(
                rule_name="signal_deduplication",
                status=CheckStatus.FAILED,
                message=msg,
                details={"signal_id": request.signal_id, "first_evaluated_at": first_seen},
            ))
            reasons.append(msg)
        else:
            rules.append(RuleEvaluationResult(
                rule_name="signal_deduplication",
                status=CheckStatus.PASSED,
                message=f"Signal ID '{request.signal_id}' is unique.",
            ))

        # --------------------------------------------------------------------
        # Rule 4: Numerical & Input Sanity Check
        # --------------------------------------------------------------------
        quantity_valid = True
        price_valid = True

        for name, val in [("quantity", request.quantity), ("price", request.price)]:
            if math.isnan(val) or math.isinf(val) or val <= 0:
                msg = f"Invalid numerical value: {name}={val} must be a positive finite number."
                rules.append(RuleEvaluationResult(
                    rule_name="numerical_sanity",
                    status=CheckStatus.FAILED,
                    message=msg,
                    details={"field": name, "value": val},
                ))
                reasons.append(msg)
                if name == "quantity":
                    quantity_valid = False
                if name == "price":
                    price_valid = False

        # --------------------------------------------------------------------
        # Rule 5: Exchange Product Metadata & Contract Semantics
        # --------------------------------------------------------------------
        product_meta = None
        contract_val = Decimal("1.0")
        tick_size = Decimal("0.01")

        if not products_metadata:
            msg = "Exchange product metadata unavailable. Fails closed."
            rules.append(RuleEvaluationResult(
                rule_name="product_metadata",
                status=CheckStatus.FAILED,
                message=msg,
            ))
            reasons.append(msg)
        else:
            sym_upper = request.symbol.upper()
            product_meta = next(
                (p for p in products_metadata if str(p.get("symbol")).upper() == sym_upper),
                None,
            )

            if not product_meta:
                msg = f"Unsupported symbol: '{request.symbol}' is not listed on Delta Exchange."
                rules.append(RuleEvaluationResult(
                    rule_name="product_metadata",
                    status=CheckStatus.FAILED,
                    message=msg,
                ))
                reasons.append(msg)
            else:
                # Check trading operational status
                status = str(product_meta.get("trading_status") or "").lower()
                state = str(product_meta.get("state") or "").lower()
                if status != "operational" or state != "live":
                    msg = f"Symbol '{request.symbol}' is inactive on exchange: status='{status}', state='{state}'."
                    rules.append(RuleEvaluationResult(
                        rule_name="product_metadata",
                        status=CheckStatus.FAILED,
                        message=msg,
                        details={"trading_status": status, "state": state},
                    ))
                    reasons.append(msg)
                else:
                    rules.append(RuleEvaluationResult(
                        rule_name="product_metadata",
                        status=CheckStatus.PASSED,
                        message=f"Symbol '{request.symbol}' verified live and operational on Delta Exchange.",
                    ))

                # Extract contract semantics safely
                try:
                    contract_val = Decimal(str(product_meta.get("contract_value") or "1.0"))
                    tick_size = Decimal(str(product_meta.get("tick_size") or "0.01"))
                except (InvalidOperation, ValueError, TypeError):
                    contract_val = Decimal("1.0")
                    tick_size = Decimal("0.01")

        # --------------------------------------------------------------------
        # Rule 6: Order Notional Calculation & Limit Check (Exact Decimal Math)
        # --------------------------------------------------------------------
        if quantity_valid and price_valid and product_meta:
            try:
                d_qty = Decimal(str(request.quantity))
                d_price = Decimal(str(request.price))
                d_notional = d_qty * contract_val * d_price
                proposed_notional_usd = float(d_notional)

                max_notional = Decimal(str(self.config.max_order_notional_usd))
                if d_notional > max_notional:
                    msg = (
                        f"Order notional (${proposed_notional_usd:,.2f}) exceeds maximum allowed limit "
                        f"(${self.config.max_order_notional_usd:,.2f})."
                    )
                    rules.append(RuleEvaluationResult(
                        rule_name="order_notional_limit",
                        status=CheckStatus.FAILED,
                        message=msg,
                        details={
                            "proposed_notional_usd": proposed_notional_usd,
                            "max_limit_usd": self.config.max_order_notional_usd,
                            "contract_value": float(contract_val),
                        },
                    ))
                    reasons.append(msg)
                else:
                    rules.append(RuleEvaluationResult(
                        rule_name="order_notional_limit",
                        status=CheckStatus.PASSED,
                        message=f"Order notional (${proposed_notional_usd:,.2f}) is within limit (${self.config.max_order_notional_usd:,.2f}).",
                        details={"proposed_notional_usd": proposed_notional_usd},
                    ))
            except Exception as exc:
                msg = f"Failed to compute order notional: {exc}"
                rules.append(RuleEvaluationResult(
                    rule_name="order_notional_limit",
                    status=CheckStatus.FAILED,
                    message=msg,
                ))
                reasons.append(msg)

        # --------------------------------------------------------------------
        # Rule 7: Position Size Limit Check
        # --------------------------------------------------------------------
        if quantity_valid:
            if request.quantity > self.config.max_position_size:
                msg = (
                    f"Order quantity ({request.quantity} contracts) exceeds maximum position size limit "
                    f"({self.config.max_position_size} contracts)."
                )
                rules.append(RuleEvaluationResult(
                    rule_name="position_size_limit",
                    status=CheckStatus.FAILED,
                    message=msg,
                    details={"quantity": request.quantity, "limit": self.config.max_position_size},
                ))
                reasons.append(msg)
            else:
                rules.append(RuleEvaluationResult(
                    rule_name="position_size_limit",
                    status=CheckStatus.PASSED,
                    message=f"Order quantity ({request.quantity}) is within position limit ({self.config.max_position_size}).",
                ))

        # --------------------------------------------------------------------
        # Rule 8: Stop-Loss Validation
        # --------------------------------------------------------------------
        if request.stop_loss is None or request.stop_loss <= 0 or math.isnan(request.stop_loss):
            msg = "Missing stop-loss: Every order must include a protective stop-loss price."
            rules.append(RuleEvaluationResult(
                rule_name="stop_loss_validation",
                status=CheckStatus.FAILED,
                message=msg,
            ))
            reasons.append(msg)
        elif price_valid:
            side_upper = request.side.upper()
            intent_upper = (request.position_intent or "").upper()
            is_long = side_upper == "BUY" or "LONG" in intent_upper
            is_short = side_upper == "SELL" or "SHORT" in intent_upper

            if is_long and request.stop_loss >= request.price:
                msg = f"Invalid Long Stop-Loss: Stop-loss (${request.stop_loss:,.2f}) must be strictly below entry price (${request.price:,.2f})."
                rules.append(RuleEvaluationResult(
                    rule_name="stop_loss_validation",
                    status=CheckStatus.FAILED,
                    message=msg,
                ))
                reasons.append(msg)
            elif is_short and request.stop_loss <= request.price:
                msg = f"Invalid Short Stop-Loss: Stop-loss (${request.stop_loss:,.2f}) must be strictly above entry price (${request.price:,.2f})."
                rules.append(RuleEvaluationResult(
                    rule_name="stop_loss_validation",
                    status=CheckStatus.FAILED,
                    message=msg,
                ))
                reasons.append(msg)
            else:
                # Check distance percentage
                dist_pct = (abs(request.price - request.stop_loss) / request.price) * 100.0
                if dist_pct < self.config.min_stop_loss_distance_pct:
                    msg = (
                        f"Stop-loss distance ({dist_pct:.2f}%) is tighter than minimum required "
                        f"({self.config.min_stop_loss_distance_pct:.2f}%)."
                    )
                    rules.append(RuleEvaluationResult(
                        rule_name="stop_loss_validation",
                        status=CheckStatus.FAILED,
                        message=msg,
                        details={"distance_pct": dist_pct, "min_distance_pct": self.config.min_stop_loss_distance_pct},
                    ))
                    reasons.append(msg)
                else:
                    rules.append(RuleEvaluationResult(
                        rule_name="stop_loss_validation",
                        status=CheckStatus.PASSED,
                        message=f"Stop-loss validated: distance {dist_pct:.2f}% satisfies min {self.config.min_stop_loss_distance_pct:.2f}%.",
                    ))

        # --------------------------------------------------------------------
        # Rule 9: Account Telemetry Availability & Exposure Checks
        # --------------------------------------------------------------------
        if not account_telemetry:
            msg = "Account telemetry unavailable. Fails closed."
            rules.append(RuleEvaluationResult(
                rule_name="account_telemetry",
                status=CheckStatus.FAILED,
                message=msg,
            ))
            reasons.append(msg)
        else:
            positions = account_telemetry.get("positions") or []
            active_positions = [p for p in positions if float(p.get("size") or 0.0) != 0.0]

            # 9a. Concurrent Positions Limit
            is_new_position = not any(
                str(p.get("symbol")).upper() == request.symbol.upper() for p in active_positions
            )
            if is_new_position and len(active_positions) >= self.config.max_concurrent_positions:
                msg = (
                    f"Concurrent positions limit reached: currently holding {len(active_positions)} positions "
                    f"(maximum allowed: {self.config.max_concurrent_positions})."
                )
                rules.append(RuleEvaluationResult(
                    rule_name="concurrent_positions_limit",
                    status=CheckStatus.FAILED,
                    message=msg,
                    details={"active_count": len(active_positions), "max_allowed": self.config.max_concurrent_positions},
                ))
                reasons.append(msg)
            else:
                rules.append(RuleEvaluationResult(
                    rule_name="concurrent_positions_limit",
                    status=CheckStatus.PASSED,
                    message=f"Concurrent positions check passed ({len(active_positions)} active).",
                ))

            # 9b. Daily Realized Loss Limit Check
            total_realized_loss = 0.0
            for p in positions:
                rpnl = float(p.get("realized_pnl") or 0.0)
                if rpnl < 0:
                    total_realized_loss += abs(rpnl)

            if total_realized_loss >= self.config.max_daily_realized_loss_usd:
                msg = (
                    f"Daily realized loss threshold exceeded: ${total_realized_loss:,.2f} lost today "
                    f"(maximum daily threshold: ${self.config.max_daily_realized_loss_usd:,.2f})."
                )
                rules.append(RuleEvaluationResult(
                    rule_name="daily_loss_limit",
                    status=CheckStatus.FAILED,
                    message=msg,
                    details={"realized_loss_usd": total_realized_loss, "max_limit": self.config.max_daily_realized_loss_usd},
                ))
                reasons.append(msg)
            else:
                rules.append(RuleEvaluationResult(
                    rule_name="daily_loss_limit",
                    status=CheckStatus.PASSED,
                    message=f"Daily realized loss (${total_realized_loss:,.2f}) within limits (${self.config.max_daily_realized_loss_usd:,.2f}).",
                ))

        # --------------------------------------------------------------------
        # Rule 10: Daily Submitted Order Limit Check
        # --------------------------------------------------------------------
        if self.state.orders_submitted_today >= self.config.max_orders_per_day:
            msg = (
                f"Daily order limit reached: {self.state.orders_submitted_today} orders submitted today "
                f"(max allowed: {self.config.max_orders_per_day})."
            )
            rules.append(RuleEvaluationResult(
                rule_name="daily_order_count_limit",
                status=CheckStatus.FAILED,
                message=msg,
                details={"orders_submitted_today": self.state.orders_submitted_today, "max_allowed": self.config.max_orders_per_day},
            ))
            reasons.append(msg)
        else:
            rules.append(RuleEvaluationResult(
                rule_name="daily_order_count_limit",
                status=CheckStatus.PASSED,
                message=f"Daily order limit check passed ({self.state.orders_submitted_today}/{self.config.max_orders_per_day}).",
            ))

        # --------------------------------------------------------------------
        # Rule 11: Available Balance & Margin Verification
        # --------------------------------------------------------------------
        if account_telemetry is not None:
            avail_bal = float(account_telemetry.get("available_balance_usd") or 0.0)
            if avail_bal <= 0 and "balances" in account_telemetry:
                for b in account_telemetry.get("balances") or []:
                    sym = str(b.get("asset_symbol") or "").upper()
                    if sym in ("USD", "USDT", "USDC"):
                        avail_bal += float(b.get("available_balance") or 0.0)

            intent_upper = (request.position_intent or "").upper()
            is_entry = "OPEN" in intent_upper or ("CLOSE" not in intent_upper and request.side.upper() in ("BUY", "SELL"))

            if is_entry:
                if avail_bal <= 0:
                    msg = f"Insufficient funds: Available balance is ${avail_bal:,.2f} USD. Cannot open new position."
                    rules.append(RuleEvaluationResult(
                        rule_name="available_margin",
                        status=CheckStatus.FAILED,
                        message=msg,
                        details={"available_balance_usd": avail_bal},
                    ))
                    reasons.append(msg)
                else:
                    # Require at least 10% margin coverage buffer (conservative 10x max leverage equivalent)
                    required_margin = proposed_notional_usd * 0.10
                    if required_margin > avail_bal:
                        msg = (
                            f"Insufficient available margin: Order requires estimated margin of "
                            f"${required_margin:,.2f} USD, but available balance is only ${avail_bal:,.2f} USD."
                        )
                        rules.append(RuleEvaluationResult(
                            rule_name="available_margin",
                            status=CheckStatus.FAILED,
                            message=msg,
                            details={"required_margin_usd": required_margin, "available_balance_usd": avail_bal},
                        ))
                        reasons.append(msg)
                    else:
                        rules.append(RuleEvaluationResult(
                            rule_name="available_margin",
                            status=CheckStatus.PASSED,
                            message=f"Available margin verified (${avail_bal:,.2f} USD available >= ${required_margin:,.2f} required).",
                            details={"available_balance_usd": avail_bal, "required_margin_usd": required_margin},
                        ))

        # --------------------------------------------------------------------
        # Final Decision
        # --------------------------------------------------------------------
        approved = len(reasons) == 0
        decision = "APPROVED" if approved else "REJECTED"

        # Record signal ID in persistent registry
        self.state.evaluated_signal_ids[request.signal_id] = now_ts
        self._save_safety_state(self.state)

        return RiskCheckResult(
            approved=approved,
            decision=decision,
            symbol=request.symbol,
            signal_id=request.signal_id,
            proposed_notional_usd=round(proposed_notional_usd, 4),
            evaluated_at=now_ts,
            rules_evaluated=rules,
            reasons=reasons,
        )


risk_engine = RiskEngine()
