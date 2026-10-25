import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from app.automation.models import PositionLifecycleState, PositionStateRecord
from app.exchanges.delta_client import delta_client

logger = logging.getLogger("position_manager")

DEFAULT_POSITIONS_FILE = Path(__file__).resolve().parent / "data" / "position_state.json"


class PositionManager:
    """
    Authoritative position tracker and lifecycle coordinator.
    
    Guarantees:
    1. Synchronized with live exchange state via Delta Exchange REST /v2/positions.
    2. Detects external changes made outside TokenIQ.
    3. Prevents unwanted position reversals and unconfigured pyramiding.
    4. Tracks cooldown period between closed trades.
    5. Durable persistence across restarts.
    """

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = data_file or DEFAULT_POSITIONS_FILE
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._positions: Dict[str, PositionStateRecord] = {}  # symbol -> PositionStateRecord
        self._last_exit_times: Dict[str, int] = {}  # symbol -> timestamp of last close
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load position state from disk."""
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            pos_dict = raw.get("positions") or {}
            for sym, p in pos_dict.items():
                self._positions[sym] = PositionStateRecord(**p)
            self._last_exit_times = {k: int(v) for k, v in (raw.get("last_exit_times") or {}).items()}
            logger.info(f"Loaded position state for {len(self._positions)} symbols from disk.")
        except Exception as exc:
            logger.error(f"Failed to load position state from {self.data_file}: {exc}")

    def _save_to_disk(self) -> None:
        """Atomically persist position records to disk."""
        temp_file = self.data_file.with_suffix(".tmp")
        try:
            data = {
                "updated_at": int(time.time()),
                "positions": {sym: p.model_dump() for sym, p in self._positions.items()},
                "last_exit_times": self._last_exit_times,
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.data_file)
        except Exception as exc:
            logger.error(f"Failed to persist position state: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    async def get_position(self, symbol: str) -> PositionStateRecord:
        """Get or initialize position record for a symbol."""
        symbol_upper = symbol.upper()
        async with self._lock:
            if symbol_upper not in self._positions:
                self._positions[symbol_upper] = PositionStateRecord(
                    symbol=symbol_upper,
                    product_id=0,
                    lifecycle_state=PositionLifecycleState.FLAT,
                )
            return self._positions[symbol_upper].model_copy()

    async def get_all_positions(self) -> List[PositionStateRecord]:
        """Return all tracked position records."""
        async with self._lock:
            return [p.model_copy() for p in self._positions.values()]

    async def update_lifecycle_state(
        self,
        symbol: str,
        new_state: PositionLifecycleState,
        **kwargs: Any,
    ) -> PositionStateRecord:
        """Transition position lifecycle state atomically."""
        symbol_upper = symbol.upper()
        async with self._lock:
            pos = self._positions.get(symbol_upper)
            if not pos:
                pos = PositionStateRecord(
                    symbol=symbol_upper,
                    product_id=kwargs.get("product_id", 0),
                    lifecycle_state=new_state,
                )
                self._positions[symbol_upper] = pos
            else:
                pos.lifecycle_state = new_state

            pos.updated_at = int(time.time())

            # Apply any additional state fields provided in kwargs
            for k, v in kwargs.items():
                if hasattr(pos, k):
                    setattr(pos, k, v)

            if new_state == PositionLifecycleState.FLAT:
                pos.quantity = 0.0
                pos.average_entry_price = 0.0
                pos.current_notional_usd = 0.0
                pos.side = None
                pos.closed_at = int(time.time())
                self._last_exit_times[symbol_upper] = int(time.time())

            self._save_to_disk()
            return pos.model_copy()

    async def check_cooldown(self, symbol: str, cooldown_seconds: int) -> Tuple[bool, int]:
        """
        Check if symbol is currently in trade cooldown.
        Returns:
            (in_cooldown: bool, remaining_seconds: int)
        """
        symbol_upper = symbol.upper()
        async with self._lock:
            last_exit = self._last_exit_times.get(symbol_upper)
            if not last_exit:
                return False, 0
            elapsed = int(time.time()) - last_exit
            if elapsed < cooldown_seconds:
                return True, (cooldown_seconds - elapsed)
            return False, 0

    async def reconcile_with_exchange(
        self, symbol: str, product_id: Optional[int] = None
    ) -> PositionStateRecord:
        """
        Synchronize local position record against live exchange state.
        Authoritative source: GET /v2/positions/margined or /v2/positions.
        """
        symbol_upper = symbol.upper()

        # Resolve authoritative product metadata for product_id and underlying_asset_symbol
        from app.risk.service import risk_service
        products = await risk_service._get_fresh_products()
        meta = next((p for p in products if str(p.get("symbol", "")).upper() == symbol_upper), None)
        target_product_id = product_id or (int(meta.get("id")) if meta and meta.get("id") else None)
        underlying = (meta.get("underlying_asset") or {}).get("symbol") if meta else None
        if not underlying and symbol_upper.startswith("BTC"):
            underlying = "BTC"

        try:
            exchange_positions = await delta_client.get_positions(
                product_id=target_product_id,
                underlying_asset_symbol=underlying,
            )
        except Exception as exc:
            logger.error(f"Failed to fetch exchange positions for reconciliation: {exc}")
            raise RuntimeError(f"Cannot reconcile positions: Exchange connection error ({exc})")

        # Fetch open orders to verify stop-loss and take-profit protection
        open_orders: List[Dict[str, Any]] = []
        try:
            open_orders = await delta_client.get_open_orders(product_id=target_product_id)
        except Exception as exc:
            logger.warning(f"Failed to fetch open orders during position reconciliation: {exc}")

        # Find position for target symbol or product_id
        matched = next(
            (
                p for p in exchange_positions
                if str(p.get("symbol", "")).upper() == symbol_upper
                or (target_product_id and int(p.get("product_id") or 0) == target_product_id)
            ),
            None,
        )

        async with self._lock:
            pos = self._positions.get(symbol_upper)
            if not pos:
                pos = PositionStateRecord(
                    symbol=symbol_upper,
                    product_id=target_product_id or 0,
                )
                self._positions[symbol_upper] = pos

            now = int(time.time())
            pos.updated_at = now
            if target_product_id:
                pos.product_id = target_product_id

            if not matched or float(matched.get("size") or 0.0) == 0:
                # Position is flat on exchange
                if pos.lifecycle_state == PositionLifecycleState.ENTRY_PENDING:
                    order_key = pos.entry_order_id or pos.entry_client_order_id
                    if order_key:
                        from app.trading.service import order_execution_service
                        from app.trading.models import OrderState
                        try:
                            rec = await order_execution_service.reconcile_order(order_key)
                            if rec.state in (OrderState.REJECTED.value, OrderState.CANCELLED.value):
                                logger.info(
                                    f"Reconciliation: Pending entry order {order_key} for {symbol_upper} was {rec.state}. "
                                    "Resolving position lifecycle to FLAT."
                                )
                                pos.lifecycle_state = PositionLifecycleState.FLAT
                                pos.entry_order_id = None
                                pos.entry_client_order_id = None
                                pos.quantity = 0.0
                                pos.average_entry_price = 0.0
                                pos.current_notional_usd = 0.0
                                pos.side = None
                                pos.closed_at = now
                                pos.protection_verified = False
                            elif rec.state == OrderState.FILLED.value:
                                logger.warning(
                                    f"Entry order {order_key} is FILLED but exchange position size is 0. Preserving state."
                                )
                            elif rec.state in (OrderState.OPEN.value, OrderState.PENDING.value, OrderState.SUBMITTED.value):
                                logger.info(
                                    f"Entry order {order_key} is still {rec.state} on exchange. Position remains ENTRY_PENDING."
                                )
                            else:
                                logger.info(
                                    f"Entry order {order_key} state is UNKNOWN. Preserving ENTRY_PENDING."
                                )
                        except ValueError:
                            logger.warning(f"Pending entry order {order_key} not in execution store.")
                        except Exception as exc:
                            logger.warning(f"Could not verify pending entry order {order_key}: {exc}. Preserving ENTRY_PENDING.")
                    else:
                        pos.lifecycle_state = PositionLifecycleState.FLAT
                        pos.quantity = 0.0
                        pos.average_entry_price = 0.0
                        pos.current_notional_usd = 0.0
                        pos.side = None
                        pos.closed_at = now
                        pos.protection_verified = False
                elif pos.lifecycle_state != PositionLifecycleState.FLAT:
                    logger.info(f"Reconciliation: Position for {symbol_upper} is FLAT on exchange.")
                    pos.lifecycle_state = PositionLifecycleState.FLAT
                    pos.quantity = 0.0
                    pos.average_entry_price = 0.0
                    pos.current_notional_usd = 0.0
                    pos.side = None
                    pos.closed_at = now
                    pos.protection_verified = False
                    self._last_exit_times[symbol_upper] = now
            else:
                raw_size = float(matched.get("size") or 0.0)
                entry_px = float(matched.get("entry_price") or 0.0)
                product_id = int(matched.get("product_id") or pos.product_id or target_product_id or 0)
                side_str = "LONG" if raw_size > 0 else "SHORT"

                pos.product_id = product_id
                pos.quantity = abs(raw_size)
                pos.average_entry_price = entry_px
                pos.side = side_str
                pos.realized_pnl_usd = float(matched.get("realized_pnl") or 0.0)

                if pos.lifecycle_state in (
                    PositionLifecycleState.FLAT,
                    PositionLifecycleState.ENTRY_PENDING,
                ):
                    pos.lifecycle_state = PositionLifecycleState.OPEN
                    pos.opened_at = now

                # Verify protective stop-loss against live open orders on exchange
                has_stop = any(
                    (
                        o.get("stop_order_type") == "stop_loss"
                        or str(o.get("order_type", "")).lower() == "stop_market_order"
                        or o.get("stop_price") is not None
                    )
                    and int(o.get("product_id") or 0) == pos.product_id
                    for o in open_orders
                )
                pos.protection_verified = has_stop

            self._save_to_disk()
            return pos.model_copy()


position_manager = PositionManager()
