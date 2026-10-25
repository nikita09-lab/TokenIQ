import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROJECT_NAME: str = "TokenIQ Market API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Delta Exchange Endpoints & Credentials
    DELTA_API_URL: str = os.getenv("DELTA_API_URL", "https://cdn-ind.testnet.deltaex.org")
    DELTA_WS_URL: str = os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange")
    DELTA_API_KEY: str = os.getenv("DELTA_API_KEY", "").strip()
    DELTA_API_SECRET: str = os.getenv("DELTA_API_SECRET", "").strip()

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

    # CORS Origins
    _raw_cors = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
    )
    CORS_ORIGINS: List[str] = [origin.strip() for origin in _raw_cors.split(",") if origin.strip()]

    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15.0"))
    TICKER_CACHE_TTL_SECONDS: float = float(os.getenv("TICKER_CACHE_TTL_SECONDS", "2.0"))


settings = Settings()
