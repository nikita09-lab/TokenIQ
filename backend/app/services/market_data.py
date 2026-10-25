import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.exchanges.delta_client import delta_client

logger = logging.getLogger("market_data_service")


class MarketDataService:
    """Service layer for aggregated cryptocurrency market data."""

    def __init__(self):
        self._client = delta_client
        self._tickers_cache: List[Dict[str, Any]] = []
        self._tickers_cache_time: float = 0.0

    async def get_tickers(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Retrieve tickers with TTL caching."""
        now = time.time()
        if (
            not force_refresh
            and self._tickers_cache
            and (now - self._tickers_cache_time) < settings.TICKER_CACHE_TTL_SECONDS
        ):
            return self._tickers_cache

        try:
            tickers = await self._client.get_tickers()
            self._tickers_cache = tickers
            self._tickers_cache_time = now
            return tickers
        except Exception as exc:
            # If cache is available on network failure, return stale cache as fallback
            if self._tickers_cache:
                logger.warning(f"Error fetching fresh tickers, returning cached: {exc}")
                return self._tickers_cache
            raise exc

    async def get_ticker_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Find a single ticker by symbol."""
        tickers = await self.get_tickers()
        sym_upper = symbol.upper()
        for t in tickers:
            if t["symbol"].upper() == sym_upper:
                return t
        return None

    async def get_market_stats(self) -> Dict[str, Any]:
        """Compute live exchange statistics and market breadth."""
        tickers = await self.get_tickers()

        btc_ticker = next((t for t in tickers if t["symbol"] == "BTCUSD" or "BTCUSD" in t["symbol"]), None)
        eth_ticker = next((t for t in tickers if t["symbol"] == "ETHUSD" or "ETHUSD" in t["symbol"]), None)

        total_turnover_usd = 0.0
        gainers = 0
        losers = 0
        perpetuals = 0

        for t in tickers:
            if t.get("contract_type") == "perpetual_futures":
                perpetuals += 1

            turnover = t.get("turnover_24h_usd")
            if turnover is not None and not (isinstance(turnover, float) and turnover != turnover):
                total_turnover_usd += turnover

            change = t.get("change_24h")
            if change is not None:
                if change > 0:
                    gainers += 1
                elif change < 0:
                    losers += 1

        return {
            "btc_price": btc_ticker["last_price"] if btc_ticker else None,
            "btc_change_24h": btc_ticker["change_24h"] if btc_ticker else None,
            "btc_volume": btc_ticker["volume_24h"] if btc_ticker else None,
            "eth_price": eth_ticker["last_price"] if eth_ticker else None,
            "eth_change_24h": eth_ticker["change_24h"] if eth_ticker else None,
            "eth_volume": eth_ticker["volume_24h"] if eth_ticker else None,
            "total_trading_pairs": len(tickers),
            "active_perpetuals": perpetuals,
            "total_volume_usd_24h": total_turnover_usd if total_turnover_usd > 0 else None,
            "gainers_count": gainers,
            "losers_count": losers,
            "timestamp": int(time.time() * 1000),
        }

    async def get_candles(
        self,
        symbol: str,
        resolution: str = "1h",
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch historical candlestick bars."""
        return await self._client.get_historical_candles(
            symbol=symbol,
            resolution=resolution,
            start=start,
            end=end,
        )

    async def get_products(self) -> List[Dict[str, Any]]:
        """Fetch available product contracts."""
        return await self._client.get_products()


market_service = MarketDataService()
