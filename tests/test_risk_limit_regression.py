import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

# pyrefly: ignore[missing-import]
from app.automation.executor import AutomatedOrderExecutor
# pyrefly: ignore[missing-import]
from app.automation.models import (
    AutomatedSignal,
    AutomationConfig,
    SignalLifecycleState,
)
# pyrefly: ignore[missing-import]
from app.exchanges.delta_client import delta_client
# pyrefly: ignore[missing-import]
from app.risk.models import (
    CheckStatus,
    RiskCheckRequest,
    RiskConfig,
    TradingStatus,
)
# pyrefly: ignore[missing-import]
from app.risk.service import risk_service
# pyrefly: ignore[missing-import]
from app.trading.gateway import delta_testnet_gateway
# pyrefly: ignore[missing-import]
from app.trading.models import (
    OrderConfirmRequest,
    OrderPreviewResponse,
    OrderState,
)
# pyrefly: ignore[missing-import]
from app.trading.service import order_execution_service
# pyrefly: ignore[missing-import]
from app.trading.store import execution_store

SAMPLE_PRODUCTS = [
    {
        "id": 84,
        "product_id": 84,
        "symbol": "BTCUSD",
        "tick_size": "0.1",
        "contract_value": "0.001",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
    },
    {
        "id": 85,
        "product_id": 85,
        "symbol": "ETHUSD",
        "tick_size": "0.05",
        "contract_value": "0.01",
        "contract_type": "perpetual_futures",
        "trading_status": "operational",
        "state": "live",
    },
]

BASE_ACCOUNT = {
    "authenticated": True,
    "positions": [],
    "balances": [{"asset_symbol": "USDT", "balance": 10000.0, "available_balance": 8000.0}],
    "orders": [],
}


@pytest.fixture(autouse=True)
def setup_risk_limits_environment():
    """Ensure baseline active risk limits match the stricter harmonized settings."""
    risk_service.engine.reset_kill_switch("Automated test suite initialization")
    # Verify effective limits on the isolated engine
    risk_service.engine.config = RiskConfig(
        max_order_notional_usd=500.0,
        max_position_size=10.0,
        max_daily_realized_loss_usd=100.0,
        max_orders_per_day=20,
        max_concurrent_positions=1,
        min_stop_loss_distance_pct=0.5,
        max_signal_age_seconds=300,
    )
    risk_service.engine.state.orders_submitted_today = 0
    risk_service._cached_products = SAMPLE_PRODUCTS
    risk_service._products_cached_time = time.time()

    with patch.object(delta_client, "get_products", new_callable=AsyncMock) as mock_p, \
         patch.object(delta_client, "get_account_overview", new_callable=AsyncMock) as mock_a:
        mock_p.return_value = SAMPLE_PRODUCTS
        mock_a.return_value = BASE_ACCOUNT
        yield


# ============================================================================
# 1. Max Order Notional Limit ($500.0)
# ============================================================================
@pytest.mark.asyncio
async def test_order_exceeding_notional_limit_rejected_before_exchange():
    """
    Regression: An order with notional > $500 is rejected by risk check
    and NEVER reaches delta_testnet_gateway.submit_order.
    8 BTC contracts @ $70,000 * 0.001 = $560.0 notional (> $500.0).
    """
    submit_mock = AsyncMock()
    with patch.object(delta_testnet_gateway, "submit_order", submit_mock):
        req = RiskCheckRequest(
            symbol="BTCUSD",
            side="BUY",
            quantity=8.0,
            price=70000.0,
            stop_loss=69000.0,
            signal_id=f"sig_notional_reg_{int(time.time())}",
            timestamp=int(time.time()),
        )
        res = await risk_service.check_signal_risk(req)
        assert res.approved is False
        assert any("order notional" in r.lower() and "exceeds maximum allowed limit" in r.lower() for r in res.reasons)

        # Confirm via executor
        executor = AutomatedOrderExecutor()
        sig = AutomatedSignal(
            signal_id=f"sig_notional_exec_{int(time.time())}",
            strategy_id="ema_crossover",
            symbol="BTCUSD",
            timeframe="1h",
            candle_timestamp=int(time.time()),
            signal_direction="BUY",
            position_intent="OPEN_LONG",
            entry_rationale="Test notional breach",
            intended_price=70000.0,
            intended_quantity=8.0,
            stop_loss_price=69000.0,
            idempotency_key=f"idemp_notional_{int(time.time())}",
        )
        with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = AutomationConfig(enabled=True)
            exec_res = await executor.execute_signal(sig, SAMPLE_PRODUCTS[0])
            assert exec_res is None

        # Absolute guarantee: submit_order on gateway was NEVER invoked
        assert submit_mock.call_count == 0


# ============================================================================
# 2. Max Position Size Limit (10.0 contracts)
# ============================================================================
@pytest.mark.asyncio
async def test_order_exceeding_position_size_limit_rejected_before_exchange():
    """
    Regression: An order with quantity > 10.0 contracts is rejected
    and NEVER reaches delta_testnet_gateway.submit_order.
    12 contracts @ $30,000 * 0.001 = $360.0 notional (within $500 notional, but 12 > 10 contracts).
    """
    submit_mock = AsyncMock()
    with patch.object(delta_testnet_gateway, "submit_order", submit_mock):
        req = RiskCheckRequest(
            symbol="BTCUSD",
            side="BUY",
            quantity=12.0,  # Exceeds max_position_size (10.0)
            price=30000.0,
            stop_loss=29500.0,
            signal_id=f"sig_pos_size_reg_{int(time.time())}",
            timestamp=int(time.time()),
        )
        res = await risk_service.check_signal_risk(req)
        assert res.approved is False
        assert any("position size limit" in r.lower() for r in res.reasons)

        executor = AutomatedOrderExecutor()
        sig = AutomatedSignal(
            signal_id=f"sig_pos_exec_{int(time.time())}",
            strategy_id="ema_crossover",
            symbol="BTCUSD",
            timeframe="1h",
            candle_timestamp=int(time.time()),
            signal_direction="BUY",
            position_intent="OPEN_LONG",
            entry_rationale="Test pos size breach",
            intended_price=30000.0,
            intended_quantity=12.0,
            stop_loss_price=29500.0,
            idempotency_key=f"idemp_pos_{int(time.time())}",
        )
        with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = AutomationConfig(enabled=True)
            exec_res = await executor.execute_signal(sig, SAMPLE_PRODUCTS[0])
            assert exec_res is None

        assert submit_mock.call_count == 0


# ============================================================================
# 3. Max Daily Realized Loss Limit ($100.0)
# ============================================================================
@pytest.mark.asyncio
async def test_order_exceeding_daily_loss_limit_rejected_before_exchange():
    """
    Regression: When daily realized loss >= $100.0, any order is rejected
    and NEVER reaches delta_testnet_gateway.submit_order.
    """
    loss_account = {
        "authenticated": True,
        "positions": [
            {"product_id": 84, "symbol": "BTCUSD", "size": 0.0, "realized_pnl": -125.0}
        ],
        "balances": [{"asset_symbol": "USDT", "balance": 10000.0, "available_balance": 8000.0}],
    }

    submit_mock = AsyncMock()
    with patch.object(delta_client, "get_account_overview", AsyncMock(return_value=loss_account)), \
         patch.object(delta_testnet_gateway, "submit_order", submit_mock):
        req = RiskCheckRequest(
            symbol="BTCUSD",
            side="BUY",
            quantity=1.0,
            price=70000.0,
            stop_loss=69000.0,
            signal_id=f"sig_loss_reg_{int(time.time())}",
            timestamp=int(time.time()),
        )
        res = await risk_service.check_signal_risk(req)
        assert res.approved is False
        assert any("daily realized loss" in r.lower() for r in res.reasons)

        executor = AutomatedOrderExecutor()
        sig = AutomatedSignal(
            signal_id=f"sig_loss_exec_{int(time.time())}",
            strategy_id="ema_crossover",
            symbol="BTCUSD",
            timeframe="1h",
            candle_timestamp=int(time.time()),
            signal_direction="BUY",
            position_intent="OPEN_LONG",
            entry_rationale="Test loss breach",
            intended_price=70000.0,
            intended_quantity=1.0,
            stop_loss_price=69000.0,
            idempotency_key=f"idemp_loss_{int(time.time())}",
        )
        with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = AutomationConfig(enabled=True)
            exec_res = await executor.execute_signal(sig, SAMPLE_PRODUCTS[0])
            assert exec_res is None

        assert submit_mock.call_count == 0


# ============================================================================
# 4. Max Orders Per Day Limit (20 orders)
# ============================================================================
@pytest.mark.asyncio
async def test_order_exceeding_daily_order_count_rejected_before_exchange():
    """
    Regression: When orders_submitted_today >= 20, any order is rejected
    and NEVER reaches delta_testnet_gateway.submit_order.
    """
    risk_service.engine.state.orders_submitted_today = 20

    submit_mock = AsyncMock()
    with patch.object(delta_testnet_gateway, "submit_order", submit_mock):
        req = RiskCheckRequest(
            symbol="BTCUSD",
            side="BUY",
            quantity=1.0,
            price=70000.0,
            stop_loss=69000.0,
            signal_id=f"sig_order_count_reg_{int(time.time())}",
            timestamp=int(time.time()),
        )
        res = await risk_service.check_signal_risk(req)
        assert res.approved is False
        assert any("daily order limit" in r.lower() for r in res.reasons)

        executor = AutomatedOrderExecutor()
        sig = AutomatedSignal(
            signal_id=f"sig_ord_count_exec_{int(time.time())}",
            strategy_id="ema_crossover",
            symbol="BTCUSD",
            timeframe="1h",
            candle_timestamp=int(time.time()),
            signal_direction="BUY",
            position_intent="OPEN_LONG",
            entry_rationale="Test order count breach",
            intended_price=70000.0,
            intended_quantity=1.0,
            stop_loss_price=69000.0,
            idempotency_key=f"idemp_cnt_{int(time.time())}",
        )
        with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = AutomationConfig(enabled=True)
            exec_res = await executor.execute_signal(sig, SAMPLE_PRODUCTS[0])
            assert exec_res is None

        assert submit_mock.call_count == 0


# ============================================================================
# 5. Max Concurrent Positions Limit (1 position)
# ============================================================================
@pytest.mark.asyncio
async def test_order_exceeding_concurrent_positions_rejected_before_exchange():
    """
    Regression: When holding 1 active position in ETHUSD, opening a new position
    in BTCUSD is rejected because max_concurrent_positions = 1.
    NEVER reaches delta_testnet_gateway.submit_order.
    """
    account_with_position = {
        "authenticated": True,
        "positions": [
            {
                "product_id": 85,
                "symbol": "ETHUSD",
                "size": 2.0,  # Active open position
                "realized_pnl": 0.0,
            }
        ],
        "balances": [{"asset_symbol": "USDT", "balance": 10000.0, "available_balance": 8000.0}],
    }

    submit_mock = AsyncMock()
    with patch.object(delta_client, "get_account_overview", AsyncMock(return_value=account_with_position)), \
         patch.object(delta_testnet_gateway, "submit_order", submit_mock):
        req = RiskCheckRequest(
            symbol="BTCUSD",
            side="BUY",
            quantity=1.0,
            price=70000.0,
            stop_loss=69000.0,
            signal_id=f"sig_concurrent_reg_{int(time.time())}",
            timestamp=int(time.time()),
        )
        res = await risk_service.check_signal_risk(req)
        assert res.approved is False
        assert any("concurrent positions limit" in r.lower() for r in res.reasons)

        executor = AutomatedOrderExecutor()
        sig = AutomatedSignal(
            signal_id=f"sig_concurrent_exec_{int(time.time())}",
            strategy_id="ema_crossover",
            symbol="BTCUSD",
            timeframe="1h",
            candle_timestamp=int(time.time()),
            signal_direction="BUY",
            position_intent="OPEN_LONG",
            entry_rationale="Test concurrent breach",
            intended_price=70000.0,
            intended_quantity=1.0,
            stop_loss_price=69000.0,
            idempotency_key=f"idemp_conc_{int(time.time())}",
        )
        with patch("app.automation.executor.automation_config_manager.get_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = AutomationConfig(enabled=True)
            exec_res = await executor.execute_signal(sig, SAMPLE_PRODUCTS[0])
            assert exec_res is None

        assert submit_mock.call_count == 0


# ============================================================================
# 6. Valid Order Passing All Stricter Limits
# ============================================================================
@pytest.mark.asyncio
async def test_order_within_stricter_limits_approved():
    """
    Verification: 1 BTC contract @ $70,000 * 0.001 = $70.0 notional (< $500),
    quantity 1 (< 10), daily loss 0 (< $100), orders 0 (< 20), positions 0 (< 1).
    Passes all risk checks.
    """
    req = RiskCheckRequest(
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        price=70000.0,
        stop_loss=69000.0,
        signal_id=f"sig_valid_reg_{int(time.time())}",
        timestamp=int(time.time()),
    )
    res = await risk_service.check_signal_risk(req)
    assert res.approved is True
    assert res.reasons == []
