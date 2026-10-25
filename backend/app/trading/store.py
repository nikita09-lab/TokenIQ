import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.trading.models import OrderExecutionRecord, OrderPreviewResponse, OrderState
from app.core.config import get_storage_path

logger = logging.getLogger("execution_store")


class ExecutionStore:
    """
    Durable, thread-safe and coroutine-safe store for order previews, execution records,
    and state transitions. Persisted to execution_records.json.
    """

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = data_file or get_storage_path(
            "execution_records.json",
            Path(__file__).resolve().parent / "execution_records.json",
        )
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._previews: Dict[str, OrderPreviewResponse] = {}
        self._consumed_previews: Dict[str, int] = {}  # preview_id -> consumed_at timestamp
        self._orders: Dict[str, OrderExecutionRecord] = {}  # client_order_id -> record
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load execution state from disk if exists."""
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                consumed = raw.get("consumed_previews") or {}
                self._consumed_previews = {k: int(v) for k, v in consumed.items()}
                orders_raw = raw.get("orders") or []
                loaded_orders: Dict[str, OrderExecutionRecord] = {}
                for o in orders_raw:
                    rec = OrderExecutionRecord(**o)
                    loaded_orders[rec.client_order_id] = rec
                self._orders = loaded_orders
        except Exception as exc:
            logger.error(f"Failed to load execution records from {self.data_file}: {exc}")

    def reload_from_disk(self) -> None:
        """Explicitly synchronize in-memory state with persisted file."""
        self._load_from_disk()

    def _save_to_disk(self) -> None:
        """Atomically persist state to disk."""
        temp_file = self.data_file.with_suffix(".tmp")
        try:
            data = {
                "updated_at": int(time.time()),
                "consumed_previews": self._consumed_previews,
                "orders": [rec.model_dump() for rec in self._orders.values()],
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.data_file)
        except Exception as exc:
            logger.error(f"Failed to persist execution records to {self.data_file}: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    async def save_preview(self, preview: OrderPreviewResponse) -> None:
        """Store an order preview in memory with TTL."""
        async with self._lock:
            self._previews[preview.preview_id] = preview

    async def get_preview(self, preview_id: str) -> Optional[OrderPreviewResponse]:
        """Retrieve an order preview if it exists and has not expired."""
        async with self._lock:
            preview = self._previews.get(preview_id)
            if not preview:
                return None
            now = int(time.time())
            if now > preview.expires_at:
                return None
            return preview

    async def consume_preview(self, preview_id: str) -> Optional[OrderPreviewResponse]:
        """
        Atomically check and consume a preview to prevent replay and double submission.
        Returns the preview if valid and successfully consumed, or None otherwise.
        """
        async with self._lock:
            # 1. Check if already consumed
            if preview_id in self._consumed_previews:
                logger.warning(f"Replay attempt blocked: Preview '{preview_id}' was already consumed.")
                return None

            # 2. Check existence in active previews
            preview = self._previews.get(preview_id)
            if not preview:
                logger.warning(f"Preview '{preview_id}' not found.")
                return None

            # 3. Check expiration
            now = int(time.time())
            if now > preview.expires_at:
                logger.warning(f"Preview '{preview_id}' expired at {preview.expires_at} (now={now}).")
                return None

            # 4. Mark consumed atomically
            self._consumed_previews[preview_id] = now
            del self._previews[preview_id]
            self._save_to_disk()
            return preview

    async def save_order(self, record: OrderExecutionRecord) -> None:
        """Save or update an order execution record atomically."""
        async with self._lock:
            record.updated_at = int(time.time())
            self._orders[record.client_order_id] = record
            self._save_to_disk()

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[OrderExecutionRecord]:
        async with self._lock:
            return self._orders.get(client_order_id)

    async def get_order_by_id(self, order_id_or_client_id: str) -> Optional[OrderExecutionRecord]:
        async with self._lock:
            # Check by client_order_id
            if order_id_or_client_id in self._orders:
                return self._orders[order_id_or_client_id]
            # Check by exchange order_id
            for rec in self._orders.values():
                if rec.order_id == str(order_id_or_client_id):
                    return rec
            return None

    async def get_all_orders(self) -> List[OrderExecutionRecord]:
        async with self._lock:
            # Return sorted chronologically descending
            return sorted(list(self._orders.values()), key=lambda r: r.created_at, reverse=True)

    async def get_active_orders(self) -> List[OrderExecutionRecord]:
        async with self._lock:
            return sorted(
                [
                    rec for rec in self._orders.values()
                    if rec.state in (OrderState.OPEN.value, OrderState.PENDING.value, OrderState.SUBMITTED.value)
                    and not rec.reconciliation_needed
                ],
                key=lambda r: r.created_at,
                reverse=True,
            )

    async def get_unknown_orders(self) -> List[OrderExecutionRecord]:
        async with self._lock:
            return [
                rec for rec in self._orders.values()
                if rec.state == OrderState.UNKNOWN.value or rec.reconciliation_needed
            ]


execution_store = ExecutionStore()
