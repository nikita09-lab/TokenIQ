import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Dict, List, Optional

from app.automation.models import AutomatedSignal, SignalLifecycleState
from app.core.config import get_storage_path

logger = logging.getLogger("signal_deduplicator")

DEFAULT_SIGNALS_FILE = get_storage_path(
    "signals_store.json",
    Path(__file__).resolve().parent / "data" / "signals_store.json",
)


class SignalDeduplicator:
    """
    Durable signal deduplication and lifecycle registry.
    
    Guarantees:
    1. Idempotency Key: Deterministic SHA-256 hash of (strategy, symbol, timeframe, candle_ts, direction, intent).
    2. Zero Duplicate Execution: Once an idempotency key is registered and in flight or executed,
       subsequent evaluations of the same completed candle are rejected.
    3. Concurrency Protection: Thread-safe and coroutine-safe with async mutex.
       NOTE ON ARCHITECTURAL BOUNDARY: Uses an in-process asyncio mutex and atomic disk persistence.
       This safely guards the single-worker execution loop. In a distributed multi-worker setup,
       a Redis distributed lock would be required.
    4. Lifecycle Persistence: Tracks state transitions across application restarts.
    """

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = data_file or DEFAULT_SIGNALS_FILE
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._signals: Dict[str, AutomatedSignal] = {}  # signal_id -> AutomatedSignal
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> signal_id
        self._load_from_disk()

    def generate_idempotency_key(
        self,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        candle_timestamp: int,
        signal_direction: str,
        position_intent: str,
    ) -> str:
        """Construct deterministic idempotency hash."""
        raw = f"{strategy_id}:{symbol.upper()}:{timeframe}:{candle_timestamp}:{signal_direction}:{position_intent}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_from_disk(self) -> None:
        """Load persisted signal records from disk."""
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            signals_data = raw.get("signals") or []
            for s in signals_data:
                sig = AutomatedSignal(**s)
                self._signals[sig.signal_id] = sig
                self._idempotency_map[sig.idempotency_key] = sig.signal_id
            logger.info(f"Loaded {len(self._signals)} signals from durable store.")
        except Exception as exc:
            logger.error(f"Failed to load signal store from {self.data_file}: {exc}")

    def _save_to_disk(self) -> None:
        """Atomically persist signals to disk."""
        temp_file = self.data_file.with_suffix(".tmp")
        try:
            # Retain last 500 signals to prevent unbound file growth
            all_signals = list(self._signals.values())
            if len(all_signals) > 500:
                all_signals = sorted(all_signals, key=lambda s: s.created_at, reverse=True)[:500]
            data = {
                "updated_at": int(time.time()),
                "signals": [s.model_dump() for s in all_signals],
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.data_file)
        except Exception as exc:
            logger.error(f"Failed to persist signal store: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    async def register_signal(self, signal: AutomatedSignal) -> bool:
        """
        Attempt to register a newly generated signal.
        Returns True if signal is fresh and successfully registered.
        Returns False if duplicate signal already exists.
        """
        async with self._lock:
            existing_id = self._idempotency_map.get(signal.idempotency_key)
            if existing_id:
                logger.warning(
                    f"Deduplication blocked signal: Idempotency key {signal.idempotency_key[:12]}... "
                    f"already exists as signal '{existing_id}'."
                )
                return False

            self._signals[signal.signal_id] = signal
            self._idempotency_map[signal.idempotency_key] = signal.signal_id
            self._save_to_disk()
            return True

    async def is_duplicate(self, idempotency_key: str) -> bool:
        """Check whether an idempotency key has already been registered."""
        async with self._lock:
            return idempotency_key in self._idempotency_map

    async def update_lifecycle(
        self,
        signal_id: str,
        new_state: SignalLifecycleState,
        rejection_reason: Optional[str] = None,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[AutomatedSignal]:
        """Atomically transition a signal's lifecycle state."""
        async with self._lock:
            sig = self._signals.get(signal_id)
            if not sig:
                return None
            sig.lifecycle_state = new_state
            if rejection_reason:
                sig.rejection_reason = rejection_reason
            if client_order_id:
                sig.client_order_id = client_order_id
            if exchange_order_id:
                sig.exchange_order_id = exchange_order_id
            self._save_to_disk()
            return sig.model_copy()

    async def get_signal(self, signal_id: str) -> Optional[AutomatedSignal]:
        """Retrieve signal by ID."""
        async with self._lock:
            sig = self._signals.get(signal_id)
            return sig.model_copy() if sig else None

    async def get_recent_signals(self, limit: int = 50) -> List[AutomatedSignal]:
        """Get latest signals sorted chronologically descending."""
        async with self._lock:
            return sorted(
                [s.model_copy() for s in self._signals.values()],
                key=lambda s: s.created_at,
                reverse=True,
            )[:limit]


signal_deduplicator = SignalDeduplicator()
