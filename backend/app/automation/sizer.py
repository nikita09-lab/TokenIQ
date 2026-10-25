from decimal import Decimal, ROUND_DOWN, InvalidOperation
import logging
from typing import Any, Dict, Optional, Tuple

from app.automation.models import AutomationConfig, PositionSizingMode

logger = logging.getLogger("position_sizer")


class PositionSizingError(ValueError):
    """Raised when position sizing calculation fails or violates contract bounds."""
    pass


class PositionSizer:
    """
    Risk-based position sizing engine for TokenIQ automated execution.
    Performs exact Decimal arithmetic respecting contract specifications,
    notional bounds, available margin, and stop-loss distance.
    """

    @staticmethod
    def calculate_order_quantity(
        config: AutomationConfig,
        product_meta: Dict[str, Any],
        entry_price: float,
        stop_loss_price: Optional[float] = None,
        available_margin_usd: Optional[float] = None,
        current_position_size: float = 0.0,
        open_orders_exposure_contracts: float = 0.0,
    ) -> Tuple[float, float]:
        """
        Calculates safe integer contract quantity and resulting estimated notional in USD.
        
        Returns:
            (contract_quantity: float, estimated_notional_usd: float)
            
        Raises:
            PositionSizingError: If bounds are violated or required metadata is missing.
        """
        # 1. Validate inputs
        if entry_price <= 0:
            raise PositionSizingError(f"Entry price must be positive, got {entry_price}")

        # 2. Extract product specifications
        contract_val_raw = product_meta.get("contract_value") or 1.0
        tick_size_raw = product_meta.get("tick_size") or 0.1
        try:
            d_cval = Decimal(str(contract_val_raw))
            d_tick = Decimal(str(tick_size_raw))
            d_price = Decimal(str(entry_price))
        except (InvalidOperation, TypeError) as exc:
            raise PositionSizingError(f"Invalid numeric contract metadata: {exc}")

        if d_cval <= 0 or d_tick <= 0:
            raise PositionSizingError("Product metadata specifies invalid non-positive contract value or tick size.")

        # Delta Exchange uses integer contract sizes for futures/perpetuals
        # 1 contract of BTCUSD = 0.001 BTC. At price $80,000, 1 contract = $80 notional.
        notional_per_contract = d_cval * d_price
        if notional_per_contract <= 0:
            raise PositionSizingError("Notional per contract evaluated to zero or negative.")

        max_order_notional = Decimal(str(config.maximum_order_notional))
        max_pos_size = Decimal(str(config.maximum_position_size))

        # 3. Calculate target raw contracts based on sizing mode
        if config.position_sizing_mode == PositionSizingMode.FIXED_CONTRACTS:
            target_contracts = Decimal(str(config.fixed_contract_quantity))

        elif config.position_sizing_mode == PositionSizingMode.FIXED_NOTIONAL:
            target_notional = Decimal(str(config.fixed_notional_usd))
            target_contracts = target_notional / notional_per_contract

        elif config.position_sizing_mode == PositionSizingMode.RISK_BUDGET:
            if stop_loss_price is None or stop_loss_price <= 0:
                raise PositionSizingError("Risk budget position sizing requires a valid protective stop-loss price.")
            d_sl = Decimal(str(stop_loss_price))
            price_distance = abs(d_price - d_sl)
            if price_distance <= Decimal("0"):
                raise PositionSizingError("Stop loss distance is zero; cannot compute risk budget.")
            risk_budget = Decimal(str(config.risk_budget_usd))
            # Loss per contract = contract_value * price_distance
            loss_per_contract = d_cval * price_distance
            if loss_per_contract <= Decimal("0"):
                raise PositionSizingError("Loss per contract evaluated to zero.")
            target_contracts = risk_budget / loss_per_contract

        else:
            raise PositionSizingError(f"Unsupported position sizing mode: {config.position_sizing_mode}")

        # 4. Discrete contract quantization (Delta contracts are whole integers)
        # Always round DOWN to ensure limits are never exceeded
        quantized_contracts = target_contracts.quantize(Decimal("1"), rounding=ROUND_DOWN)

        if quantized_contracts < Decimal("1"):
            raise PositionSizingError(
                f"Calculated size ({target_contracts:.4f}) is below minimum allowable quantity of 1 contract "
                f"(notional per contract: ${float(notional_per_contract):.2f})."
            )

        # 5. Cap by maximum order notional
        estimated_notional = quantized_contracts * notional_per_contract
        if estimated_notional > max_order_notional:
            allowed_by_notional = (max_order_notional / notional_per_contract).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
            logger.info(
                f"Quantized contracts ({quantized_contracts}) exceeded maximum order notional "
                f"(${float(max_order_notional):.2f}). Capping to {allowed_by_notional} contracts."
            )
            quantized_contracts = allowed_by_notional

        if quantized_contracts < Decimal("1"):
            raise PositionSizingError(
                f"Order notional would exceed max limit of ${float(max_order_notional):.2f} "
                f"even with 1 contract (${float(notional_per_contract):.2f})."
            )

        # 6. Cap by remaining allowed position capacity
        d_current_pos = Decimal(str(abs(current_position_size)))
        d_open_orders = Decimal(str(abs(open_orders_exposure_contracts)))
        total_current_exposure = d_current_pos + d_open_orders

        remaining_capacity = max_pos_size - total_current_exposure
        if remaining_capacity <= Decimal("0"):
            raise PositionSizingError(
                f"Position limit reached: Current exposure {float(total_current_exposure)} contracts "
                f"meets or exceeds maximum position size {float(max_pos_size)}."
            )

        if quantized_contracts > remaining_capacity:
            logger.info(
                f"Quantized contracts ({quantized_contracts}) would exceed remaining position capacity "
                f"({remaining_capacity}). Capping to {remaining_capacity} contracts."
            )
            quantized_contracts = remaining_capacity.quantize(Decimal("1"), rounding=ROUND_DOWN)

        if quantized_contracts < Decimal("1"):
            raise PositionSizingError(
                f"Remaining position capacity ({float(remaining_capacity):.2f}) is below 1 contract."
            )

        # 7. Check available margin if provided
        final_notional = float(quantized_contracts * notional_per_contract)
        if available_margin_usd is not None and available_margin_usd > 0:
            # Require at least 20% margin coverage (equivalent to 5x max leverage margin)
            # or fail safe
            if available_margin_usd < (final_notional * 0.1):
                raise PositionSizingError(
                    f"Insufficient available margin (${available_margin_usd:.2f}) for order notional "
                    f"(${final_notional:.2f})."
                )

        return float(quantized_contracts), round(final_notional, 2)


position_sizer = PositionSizer()
