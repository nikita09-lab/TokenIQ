import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from app.automation.models import AutomationConfig

logger = logging.getLogger("automation_config")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "data" / "automation_config.json"


class AutomationConfigManager:
    """
    Manages persistent automated trading configuration with fail-closed safety guarantees.
    
    Safety Invariants:
    1. Automated trading is strictly disabled (enabled=False) by default.
    2. An unexpected restart, application boot, or file corruption NEVER enables automation.
    3. Updating configuration validates all bounds before persisting atomically.
    4. Enabling requires explicit, deliberate confirmation.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._config: AutomationConfig = self._load_initial_config()

    def _load_initial_config(self) -> AutomationConfig:
        """
        Load configuration from disk.
        CRITICAL SAFETY RULE: Regardless of what is in the file, upon process boot,
        enabled is ALWAYS forced to False to prevent unattended order execution on restart!
        """
        if not self.config_path.exists():
            default_cfg = AutomationConfig(enabled=False)
            self._save_to_disk(default_cfg)
            return default_cfg

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = AutomationConfig(**data)
            # Enforce safety invariant: Always start disabled on process startup
            if cfg.enabled:
                logger.warning(
                    "Safety Override: Automation was marked enabled on disk, "
                    "resetting enabled=False on application boot."
                )
                cfg.enabled = False
                self._save_to_disk(cfg)
            return cfg
        except Exception as exc:
            logger.error(
                f"Failed to load automation configuration ({exc}). Failing closed with safe defaults."
            )
            fallback = AutomationConfig(enabled=False)
            self._save_to_disk(fallback)
            return fallback

    def _save_to_disk(self, config: AutomationConfig) -> None:
        """Atomically persist configuration to disk via temp file."""
        temp_file = self.config_path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(config.model_dump(), f, indent=2)
            temp_file.replace(self.config_path)
            logger.info("Automation configuration safely persisted to disk.")
        except Exception as exc:
            logger.error(f"Failed to persist automation config: {exc}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Could not persist automation configuration: {exc}")

    async def get_config(self) -> AutomationConfig:
        """Retrieve current in-memory configuration."""
        async with self._lock:
            return self._config.model_copy()

    async def update_config(self, updates: AutomationConfig) -> AutomationConfig:
        """
        Validate and atomically update configuration.
        Preserves active enabled state unless explicitly toggled through enable/disable methods.
        """
        async with self._lock:
            # Preserve current enabled state during regular config editing
            updates.enabled = self._config.enabled
            self._config = updates
            self._save_to_disk(self._config)
            return self._config.model_copy()

    async def set_enabled(self, enabled: bool) -> AutomationConfig:
        """
        Explicitly toggle master automation state.
        Must only be called after safety validation passes.
        """
        async with self._lock:
            self._config.enabled = enabled
            self._save_to_disk(self._config)
            logger.info(f"Master automated trading enabled state set to: {enabled}")
            return self._config.model_copy()


automation_config_manager = AutomationConfigManager()
