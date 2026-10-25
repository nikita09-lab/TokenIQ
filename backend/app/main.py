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

# Configure CORS for frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {
        "status": "healthy",
        "upstream_ws_connected": websocket_manager.upstream_connected,
        "active_clients": len(websocket_manager.active_clients),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
