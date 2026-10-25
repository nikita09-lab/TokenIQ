import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

DEFAULT_PRODUCTION_ORIGINS: List[str] = [
    "https://token-iq.vercel.app",
    "https://token-iq-git-main-nikita-santosh-mishras-projects.vercel.app",
    "https://token-rdmzzyx38-nikita-santosh-mishras-projects.vercel.app",
]

DEFAULT_DEVELOPMENT_ORIGINS: List[str] = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]


def clean_origin(origin: str) -> Optional[str]:
    """Clean and normalize a single CORS origin string."""
    cleaned = origin.strip().rstrip("/")
    if not cleaned or cleaned == "/":
        return None
    # Must have a valid web scheme
    lower = cleaned.lower()
    if not (lower.startswith("http://") or lower.startswith("https://") or lower.startswith("ws://") or lower.startswith("wss://")):
        return None
    return cleaned


def is_allowed_websocket_origin(origin: Optional[str], allowed_origins: List[str]) -> bool:
    """Check if a WebSocket origin is permitted against allowed origins."""
    if not origin:
        # Non-browser clients or test clients might omit the Origin header
        return True
    cleaned = clean_origin(origin)
    if not cleaned:
        return False
    if cleaned in allowed_origins:
        return True
    http_equivalent = cleaned.replace("wss://", "https://").replace("ws://", "http://")
    if http_equivalent in allowed_origins:
        return True
    return False


def parse_cors_origins(raw: Optional[str], environment: str, merge_defaults: bool = True) -> List[str]:
    """
    Parse comma-separated CORS origins:
    - Strips whitespace.
    - Strips any trailing slashes ('/' is invalid in CORS origin specs).
    - Ignores empty entries.
    - Preserves ordering while eliminating duplicates.
    - When merge_defaults is True, ensures verified Vercel production origins are permitted.
    """
    parsed: List[str] = []
    if raw is not None and raw.strip():
        items = raw.split(",")
        for item in items:
            cleaned = clean_origin(item)
            if cleaned and cleaned not in parsed:
                parsed.append(cleaned)
    else:
        if environment == "production":
            parsed = list(DEFAULT_PRODUCTION_ORIGINS)
        else:
            parsed = list(DEFAULT_DEVELOPMENT_ORIGINS) + list(DEFAULT_PRODUCTION_ORIGINS)

    if merge_defaults:
        for prod_origin in DEFAULT_PRODUCTION_ORIGINS:
            if prod_origin not in parsed:
                parsed.append(prod_origin)

    return parsed


class Settings:
    PROJECT_NAME: str = "TokenIQ Market API"
    VERSION: str = "1.0.0"

    @property
    def ENVIRONMENT(self) -> str:
        return os.getenv("ENVIRONMENT", "development").lower().strip()

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    @property
    def HOST(self) -> str:
        return os.getenv("HOST", "0.0.0.0").strip()

    @property
    def PORT(self) -> int:
        return int(os.getenv("PORT", "8000"))

    @property
    def FRONTEND_URL(self) -> str:
        return os.getenv("FRONTEND_URL", "https://token-iq.vercel.app").strip().rstrip("/")

    # Delta Exchange Endpoints & Credentials
    @property
    def DELTA_API_URL(self) -> str:
        url = (
            os.getenv("DELTA_API_URL")
            or os.getenv("DELTA_TESTNET_BASE_URL")
            or "https://cdn-ind.testnet.deltaex.org"
        ).strip()
        return url

    @property
    def DELTA_WS_URL(self) -> str:
        return os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange").strip()

    @property
    def DELTA_API_KEY(self) -> str:
        return os.getenv("DELTA_API_KEY", "").strip()

    @property
    def DELTA_API_SECRET(self) -> str:
        return os.getenv("DELTA_API_SECRET", "").strip()

    @property
    def is_authenticated_configured(self) -> bool:
        return bool(self.DELTA_API_KEY and self.DELTA_API_SECRET)

    @property
    def is_testnet(self) -> bool:
        try:
            from app.core.environment_guard import validate_testnet_host
            validate_testnet_host(self.DELTA_API_URL)
            return True
        except Exception:
            return False

    @property
    def masked_api_key(self) -> str:
        if not self.DELTA_API_KEY:
            return ""
        if len(self.DELTA_API_KEY) <= 6:
            return "***"
        return f"{self.DELTA_API_KEY[:3]}...{self.DELTA_API_KEY[-3:]}"

    @property
    def CORS_ORIGINS(self) -> List[str]:
        raw = os.getenv("CORS_ORIGINS")
        return parse_cors_origins(raw, self.ENVIRONMENT)

    def is_origin_allowed(self, origin: Optional[str]) -> bool:
        return is_allowed_websocket_origin(origin, self.CORS_ORIGINS)

    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
    TICKER_CACHE_TTL_SECONDS: float = float(os.getenv("TICKER_CACHE_TTL_SECONDS", "2.0"))


settings = Settings()


def get_storage_path(filename: str, fallback_path):
    """Use persistent storage if TOKENIQ_DATA_DIR is configured."""
    from pathlib import Path
    data_dir = os.getenv("TOKENIQ_DATA_DIR", "").strip()
    if data_dir:
        path = Path(data_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    fallback = Path(fallback_path)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback
