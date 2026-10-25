import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.services.market_data import market_service
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger("market_routes")

router = APIRouter(prefix="/market", tags=["Market Data"])


@router.get("/status")
async def get_market_status() -> Dict[str, Any]:
    """Get backend and upstream market-data connection status."""
    return {
        "status": "operational",
        "upstream_connected": websocket_manager.upstream_connected,
        "active_clients": len(websocket_manager.active_clients),
        "service": "TokenIQ Market API",
    }


@router.get("/tickers")
async def get_tickers(refresh: bool = False) -> Dict[str, Any]:
    """
    Fetch all available cryptocurrency trading pairs from Delta Exchange.
    Results are normalized and cached with a short TTL to protect against rate limits.
    """
    try:
        tickers = await market_service.get_tickers(force_refresh=refresh)
        return {
            "success": True,
            "count": len(tickers),
            "result": tickers,
        }
    except Exception as exc:
        logger.error(f"Failed to fetch tickers: {exc}")
        raise HTTPException(status_code=502, detail=f"Exchange API error: {str(exc)}")


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str) -> Dict[str, Any]:
    """Fetch real-time metrics for a specific symbol (e.g. BTCUSD, ETHUSD)."""
    try:
        ticker = await market_service.get_ticker_by_symbol(symbol)
        if not ticker:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found on exchange")
        return {
            "success": True,
            "result": ticker,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to fetch ticker {symbol}: {exc}")
        raise HTTPException(status_code=502, detail=f"Exchange API error: {str(exc)}")


@router.get("/products")
async def get_products() -> Dict[str, Any]:
    """Fetch raw product metadata and contracts from Delta Exchange."""
    try:
        products = await market_service.get_products()
        return {
            "success": True,
            "count": len(products),
            "result": products,
        }
    except Exception as exc:
        logger.error(f"Failed to fetch products: {exc}")
        raise HTTPException(status_code=502, detail=f"Exchange API error: {str(exc)}")


@router.get("/stats")
async def get_market_stats() -> Dict[str, Any]:
    """Calculate aggregated market breadth, BTC/ETH benchmarks, and turnover statistics."""
    try:
        stats = await market_service.get_market_stats()
        return {
            "success": True,
            "result": stats,
        }
    except Exception as exc:
        logger.error(f"Failed to calculate market stats: {exc}")
        raise HTTPException(status_code=502, detail=f"Failed to compute stats: {str(exc)}")


@router.get("/candles")
async def get_candles(
    symbol: str = Query(..., description="Trading pair symbol (e.g. BTCUSD)"),
    resolution: str = Query("1h", description="Candle interval (1m, 5m, 15m, 1h, 1d)"),
    start: Optional[int] = Query(None, description="Start timestamp in Unix seconds"),
    end: Optional[int] = Query(None, description="End timestamp in Unix seconds"),
) -> Dict[str, Any]:
    """
    Retrieve historical OHLCV candles from Delta Exchange with multi-chunk paging.
    Lightweight Charts ready (ascending chronological order).
    """
    try:
        data = await market_service.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start,
            end=end,
        )
        return data
    except Exception as exc:
        logger.error(f"Failed to fetch candles for {symbol}: {exc}")
        raise HTTPException(status_code=502, detail=f"Exchange candle error: {str(exc)}")


@router.websocket("/ws")
async def market_websocket_endpoint(websocket: WebSocket):
    """
    Real-time market streaming WebSocket endpoint.
    Frontend connects here to subscribe to ticker and candlestick feeds.
    """
    await websocket_manager.connect_client(websocket)
    try:
        while True:
            data_text = await websocket.receive_text()
            await websocket_manager.handle_client_message(websocket, data_text)
    except WebSocketDisconnect:
        websocket_manager.disconnect_client(websocket)
    except Exception as exc:
        logger.warning(f"Client websocket error: {exc}")
        websocket_manager.disconnect_client(websocket)
