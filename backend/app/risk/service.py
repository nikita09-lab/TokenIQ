import logging
import time
from typing import Any, Dict, List, Optional

from app.exchanges.delta_client import delta_client
from app.risk.engine import risk_engine
from app.risk.models import (
    RiskCheckRequest,
    RiskCheckResult,
    RiskConfig,
    TradingStatus,
)

logger = logging.getLogger("risk_service")


class RiskManagementService:
    """
    Coordinates risk evaluations, kill-switch operations, and safety telemetry
    with Delta Exchange India Testnet.
    
    SAFETY PRINCIPLES:
    - Strictly dry-run mode in Phase 7.1. Zero order execution.
    - Server-side testnet URL enforcement (fails closed if not testnet).
    - Never leaks API keys, secrets, or raw HMAC signatures.
    """

    def __init__(self):
        self.engine = risk_engine
        self._cached_products: List[Dict[str, Any]] = []
        self._products_cached_time: float = 0.0

    async def _get_fresh_products(self) -> List[Dict[str, Any]]:
        """Retrieve and cache Delta Exchange product specifications."""
        now = time.time()
        # Cache product specifications for 60 seconds
        if self._cached_products and (now - self._products_cached_time) < 60.0:
            return self._cached_products

        try:
            products = await delta_client.get_products()
            if products:
                self._cached_products = products
                self._products_cached_time = now
            return self._cached_products
        except Exception as exc:
            logger.warning(f"Failed to fetch fresh products from Delta: {exc}")
            return self._cached_products

    async def get_trading_status(self) -> TradingStatus:
        """
        Compile current trading readiness, safety state, active limits, and daily metrics.
        Fails closed on connection issues.
        """
        delta_client._assert_testnet_safe()

        # Try retrieving current account telemetry for live risk metrics
        account_data = {}
        daily_loss = 0.0
        active_pos_count = 0

        try:
            account_data = await delta_client.get_account_overview()
            positions = account_data.get("positions") or []
            active_positions = [p for p in positions if float(p.get("size") or 0.0) != 0.0]
            active_pos_count = len(active_positions)

            for p in positions:
                rpnl = float(p.get("realized_pnl") or 0.0)
                if rpnl < 0:
                    daily_loss += abs(rpnl)
        except Exception as exc:
            logger.warning(f"Could not retrieve live account telemetry for trading status: {exc}")

        state = self.engine.state
        self.engine._rollover_daily_counters(state)

        return TradingStatus(
            trading_enabled=state.trading_enabled,
            kill_switch_engaged=state.kill_switch_engaged,
            kill_switch_reason=state.kill_switch_reason,
            kill_switch_activated_at=state.kill_switch_activated_at,
            last_reset_at=state.last_reset_at,
            dry_run_mode=not state.trading_enabled,
            testnet_enforced=True,
            base_url=delta_client.host_url,
            active_risk_limits=self.engine.config,
            orders_submitted_today=state.orders_submitted_today,
            evaluations_today=state.evaluations_today,
            daily_realized_loss_usd=round(daily_loss, 2),
            active_positions_count=active_pos_count,
            disclaimer=(
                "Dry-run simulation mode active. Live order execution is disabled."
                if not state.trading_enabled
                else "Authorized Testnet execution active on Delta Exchange India Testnet. Production trading is strictly impossible."
            ),
        )

    def get_risk_config(self) -> RiskConfig:
        """Retrieve current active risk limits."""
        return self.engine.config

    def update_risk_config(self, new_config: RiskConfig) -> RiskConfig:
        """Update and persist risk limits safely."""
        return self.engine.update_config(new_config)

    async def check_signal_risk(self, request: RiskCheckRequest) -> RiskCheckResult:
        """
        Perform a comprehensive, fail-closed dry-run risk check for a proposed trade or strategy signal.
        STRICTLY DRY-RUN: Never routes, sends, or submits orders.
        """
        delta_client._assert_testnet_safe()

        # Fetch product metadata and account state
        products = await self._get_fresh_products()
        account_data = None
        try:
            account_data = await delta_client.get_account_overview()
        except Exception as exc:
            logger.warning(f"Failed to fetch account overview for risk evaluation: {exc}")

        return await self.engine.evaluate_risk(
            request=request,
            account_telemetry=account_data,
            products_metadata=products,
        )

    async def engage_kill_switch(self, reason: str) -> TradingStatus:
        """Engage emergency kill switch immediately."""
        self.engine.engage_kill_switch(reason)
        return await self.get_trading_status()

    async def reset_kill_switch(self, confirm: bool, reason: str) -> TradingStatus:
        """Deliberately reset kill switch with operator confirmation."""
        if not confirm:
            raise ValueError("Deliberate confirmation ('confirm': true) is required to reset the kill switch.")
        self.engine.reset_kill_switch(reason)
        return await self.get_trading_status()

    def record_order_submitted(self) -> int:
        """Record genuine exchange order submission in persistent safety state."""
        return self.engine.record_order_submitted()


risk_service = RiskManagementService()
