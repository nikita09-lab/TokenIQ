import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes.market import router as market_router
from app.api.routes.strategies import router as strategies_router
from app.api.routes.backtesting import router as backtesting_router
from app.api.routes.evaluation import router as evaluation_router
from app.api.routes.account import router as account_router
from app.api.routes.trading import router as trading_router
from app.api.routes.automation import router as automation_router
from app.services.websocket_manager import websocket_manager
from app.automation.worker import automated_trading_worker

logging.basicConfig(
    level=logging.INFO if settings.LOG_LEVEL.lower() == "info" else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tokeniq_main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Launch upstream WebSocket stream bridge and automation worker
    logger.info("Initializing TokenIQ FastAPI backend...")
    await websocket_manager.start()
    await automated_trading_worker.start()
    display_host = "127.0.0.1" if settings.HOST in ("0.0.0.0", "::") else settings.HOST
    logger.info(f"TokenIQ REST API ready at http://{display_host}:{settings.PORT}/api/v1/market")
    logger.info(f"Interactive Swagger documentation at http://{display_host}:{settings.PORT}/docs")
    yield
    # Shutdown: Cleanly stop background tasks and sockets
    logger.info("Shutting down TokenIQ FastAPI backend...")
    await automated_trading_worker.stop()
    await websocket_manager.stop()



app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="High-performance backend API and WebSocket bridge for TokenIQ crypto market dashboard.",
    lifespan=lifespan,
)

class DynamicCORSMiddleware(CORSMiddleware):
    """
    Dynamic CORS middleware that evaluates allowed origins at request time.
    Guarantees strict adherence to settings.CORS_ORIGINS without wildcard with credentials.
    """

    def is_allowed_origin(self, origin: str) -> bool:
        return origin in settings.CORS_ORIGINS

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origins = settings.CORS_ORIGINS
            self.allow_origins = origins
            self.allow_all_origins = False
        await super().__call__(scope, receive, send)


# Configure CORS for frontend origins
app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# Mount API routes
app.include_router(market_router, prefix="/api/v1")
app.include_router(strategies_router, prefix="/api/v1")
app.include_router(backtesting_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(account_router, prefix="/api/v1")
app.include_router(trading_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "project": "TokenIQ",
        "description": "Live Crypto Market Dashboard API",
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/health",
        "market_routes": "/api/v1/market",
        "strategy_routes": "/api/v1/strategies",
        "backtesting_routes": "/api/v1/backtesting",
    }


@app.get("/health")
async def health_check():
    import time
    worker_uptime = (
        (int(time.time()) - automated_trading_worker._started_at)
        if (automated_trading_worker._started_at and automated_trading_worker.state.value == "RUNNING")
        else 0
    )
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "testnet_enforced": settings.is_testnet,
        "upstream_ws_connected": websocket_manager.upstream_connected,
        "active_clients": len(websocket_manager.active_clients),
        "worker_health": {
            "state": automated_trading_worker.state.value,
            "is_paused": automated_trading_worker.is_paused,
            "uptime_seconds": worker_uptime,
            "last_market_data_update_at": automated_trading_worker._last_market_data_update_at,
            "last_reconciliation_at": automated_trading_worker._last_reconciliation_at,
            "heartbeat_at": automated_trading_worker._heartbeat_at or int(time.time()),
        },
    }


@app.get("/api/v1/health")
async def api_health_check():
    return await health_check()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
