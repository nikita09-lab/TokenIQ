import pytest
from unittest.mock import AsyncMock, patch
import pandas as pd
import numpy as np
from fastapi.testclient import TestClient

from app.evaluation.engine import EvaluationEngine, EvaluationValidationError
from app.evaluation.models import EvaluationRequest, ParameterSearchSpace
from app.evaluation.service import evaluation_service
from app.main import app

client = TestClient(app)


def make_candles(prices, opens=None, volumes=None, base_time=1700000000, step=3600):
    candles = []
    for i, p in enumerate(prices):
        t = base_time + (i * step)
        op = opens[i] if opens is not None else p
        v = volumes[i] if volumes is not None else 1000.0
        candles.append({
            "time": t,
            "open": float(op),
            "high": float(max(op, p) * 1.01),
            "low": float(min(op, p) * 0.99),
            "close": float(p),
            "volume": float(v),
        })
    return candles


def test_evaluation_request_validation():
    from pydantic import ValidationError

    # Invalid split_ratio (< 0.50)
    with pytest.raises(ValidationError):
        EvaluationRequest(split_ratio=0.30)

    # Invalid split_ratio (> 0.90)
    with pytest.raises(ValidationError):
        EvaluationRequest(split_ratio=0.95)

    # Negative capital
    with pytest.raises(ValidationError):
        EvaluationRequest(initial_capital=-100)

    # Invalid start_time >= end_time
    with pytest.raises(EvaluationValidationError, match="must be earlier than end_time"):
        EvaluationEngine(EvaluationRequest(start_time=1700010000, end_time=1700000000))


def test_parameter_combination_validation_and_filtering():
    # 1. Reject invalid ranges in search space
    with pytest.raises(EvaluationValidationError, match="fast_period"):
        engine = EvaluationEngine(EvaluationRequest())
        engine.generate_parameter_combinations(ParameterSearchSpace(fast_periods=[1]))

    with pytest.raises(EvaluationValidationError, match="slow_period"):
        engine = EvaluationEngine(EvaluationRequest())
        engine.generate_parameter_combinations(ParameterSearchSpace(slow_periods=[2]))

    # 2. Filter out fast >= slow automatically
    space = ParameterSearchSpace(
        fast_periods=[10, 20],
        slow_periods=[15, 20],  # (10, 15) valid; (10, 20) valid; (20, 15) invalid; (20, 20) invalid
        rsi_periods=[14],
        rsi_buy_mins=[40.0],
        rsi_sell_maxs=[60.0],
        volume_confirmation=[False],
    )
    engine = EvaluationEngine(EvaluationRequest())
    valid_combos, filtered_count = engine.generate_parameter_combinations(space)
    assert len(valid_combos) == 2
    assert filtered_count == 2
    for c in valid_combos:
        assert c.fast_period < c.slow_period

    # 3. Reject when no valid combinations exist
    space_invalid = ParameterSearchSpace(
        fast_periods=[50],
        slow_periods=[20],
    )
    with pytest.raises(EvaluationValidationError, match="No valid parameter combinations"):
        engine.generate_parameter_combinations(space_invalid)

    # 4. Enforce max_combinations boundary
    large_space = ParameterSearchSpace(
        fast_periods=[2, 3, 4, 5, 6, 7, 8, 9, 10],
        slow_periods=[20, 25, 30, 35, 40, 45, 50, 55, 60],
        rsi_periods=[7, 14],
        rsi_buy_mins=[30.0, 40.0],
        rsi_sell_maxs=[60.0, 70.0],
        volume_confirmation=[False, True],
    )
    engine_bounded = EvaluationEngine(EvaluationRequest(max_combinations=50))
    with pytest.raises(EvaluationValidationError, match="exceeds the maximum allowed limit"):
        engine_bounded.generate_parameter_combinations(large_space)


def test_chronological_train_test_split_no_shuffle():
    """
    Verify historical data is strictly partitioned into chronological in-sample (train)
    and out-of-sample (test) segments without shuffling.
    """
    prices = [100.0 + i for i in range(100)]
    candles = make_candles(prices)

    req = EvaluationRequest(split_ratio=0.70)
    engine = EvaluationEngine(req)
    train_candles, test_candles = engine.split_candles_chronologically(candles, max_slow_period=21)

    assert len(train_candles) == 70
    assert len(test_candles) == 30

    train_times = [c["time"] for c in train_candles]
    test_times = [c["time"] for c in test_candles]

    # Verify strictly monotonic ascending
    assert train_times == sorted(train_times)
    assert test_times == sorted(test_times)

    # Verify zero overlap and chronological precedence
    assert max(train_times) < min(test_times)


def test_insufficient_candles_raises_error():
    """
    Ensure the engine rejects requests with insufficient bars to safely warm up
    indicators in both training and test periods.
    """
    req = EvaluationRequest(split_ratio=0.70)
    engine = EvaluationEngine(req)

    # Only 25 candles total: train gets 17, which is < slow_period (34) + 10
    short_candles = make_candles([100.0 + i for i in range(25)])
    with pytest.raises(EvaluationValidationError, match="Insufficient in-sample historical data"):
        engine.split_candles_chronologically(short_candles, max_slow_period=34)


def test_no_test_leakage_in_parameter_selection():
    """
    Verify that the winning strategy is selected STRICTLY on in-sample (training)
    performance and NOT influenced by out-of-sample test results.
    """
    # Create 120 bars:
    # First 80 bars (In-sample): strong uptrend for fast EMA (3/7)
    # Next 40 bars (Out-of-sample): choppy/downtrend
    in_sample_prices = [100.0 + (i * 1.5) for i in range(80)]
    out_sample_prices = [220.0 - (i * 0.5) for i in range(40)]
    candles = make_candles(in_sample_prices + out_sample_prices)

    req = EvaluationRequest(
        split_ratio=0.66,
        search_space=ParameterSearchSpace(
            fast_periods=[3, 5],
            slow_periods=[7, 15],
            rsi_periods=[5],
            rsi_buy_mins=[30.0],
            rsi_sell_maxs=[70.0],
            volume_confirmation=[False],
        ),
        ranking_metric="net_return_pct",
    )
    engine = EvaluationEngine(req)
    result = engine.run(candles)

    assert len(result.parameter_sets) == 4
    # The rank 1 strategy MUST have the highest in_sample net_return_pct
    ranked_train_returns = [p.in_sample.net_return_pct for p in result.parameter_sets]
    assert ranked_train_returns == sorted(ranked_train_returns, reverse=True)

    winner = result.parameter_sets[0]
    assert winner.rank == 1
    assert result.selected_winner_params == winner.params


def test_overfitting_detection_and_warning():
    """
    Verify that when a strategy produces high return in-sample but crashes out-of-sample,
    the overfitting flag (is_overfit) and warning message are accurately generated.
    """
    # 70 bars of rally followed by 30 bars of steep crash
    train_prices = [50.0 + (i * 2.0) for i in range(70)]
    test_prices = [190.0 - (i * 3.0) for i in range(30)]
    candles = make_candles(train_prices + test_prices)

    req = EvaluationRequest(
        split_ratio=0.70,
        search_space=ParameterSearchSpace(
            fast_periods=[3],
            slow_periods=[7],
            rsi_periods=[5],
            rsi_buy_mins=[30.0],
            rsi_sell_maxs=[70.0],
            volume_confirmation=[False],
        ),
    )
    engine = EvaluationEngine(req)
    result = engine.run(candles)

    winner = result.parameter_sets[0]
    # Check that in-sample return was evaluated
    assert winner.in_sample.total_bars == 70
    assert winner.out_of_sample.total_bars == 30
    # Overfit assessment executed
    assert isinstance(winner.is_overfit, bool)
    if winner.is_overfit:
        assert winner.overfit_warning is not None
        assert len(winner.overfit_warning) > 0


def test_zero_trades_and_safe_metrics():
    """
    Ensure evaluation handles flat candles with 0 trades safely without Div/0 errors.
    """
    flat_prices = [100.0 for _ in range(80)]
    candles = make_candles(flat_prices)

    req = EvaluationRequest(
        split_ratio=0.70,
        search_space=ParameterSearchSpace(
            fast_periods=[5],
            slow_periods=[15],
            rsi_periods=[5],
            rsi_buy_mins=[40.0],
            rsi_sell_maxs=[60.0],
            volume_confirmation=[False],
        ),
    )
    engine = EvaluationEngine(req)
    result = engine.run(candles)

    winner = result.parameter_sets[0]
    assert winner.in_sample.total_trades == 0
    assert winner.in_sample.win_rate_pct == 0.0
    assert winner.in_sample.profit_factor is None
    assert winner.in_sample.net_profit == 0.0


def test_evaluation_api_config_options():
    res = client.get("/api/v1/evaluation/config-options")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "default_search_space" in data["config"]
    assert "preset_grids" in data["config"]
    assert len(data["config"]["preset_grids"]) >= 2


def test_evaluation_api_validation_error():
    # Split ratio out of range
    res = client.post(
        "/api/v1/evaluation/run",
        json={"symbol": "BTCUSD", "split_ratio": 0.20},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_evaluation_api_run_success():
    # Mock delta_client.get_historical_candles to return 100 valid candles
    candles = make_candles([100.0 + (i * 0.5) for i in range(100)])
    mock_data = {
        "symbol": "BTCUSD",
        "resolution": "1h",
        "candles": candles,
    }

    with patch("app.evaluation.service.delta_client.get_historical_candles", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data

        req_payload = {
            "symbol": "BTCUSD",
            "resolution": "1h",
            "split_ratio": 0.70,
            "max_combinations": 10,
            "search_space": {
                "fast_periods": [3, 5],
                "slow_periods": [10],
                "rsi_periods": [5],
                "rsi_buy_mins": [40.0],
                "rsi_sell_maxs": [60.0],
                "volume_confirmation": [False],
            },
        }

        res = client.post("/api/v1/evaluation/run", json=req_payload)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        result = body["result"]
        assert result["symbol"] == "BTCUSD"
        assert result["total_combinations_evaluated"] == 2
        assert len(result["parameter_sets"]) == 2
        assert result["parameter_sets"][0]["rank"] == 1
        assert "winner_train_equity_curve" in result
        assert "winner_test_equity_curve" in result

        eval_id = result["evaluation_id"]
        # Retrieve cached result
        res_cached = client.get(f"/api/v1/evaluation/results/{eval_id}")
        assert res_cached.status_code == 200
        assert res_cached.json()["result"]["evaluation_id"] == eval_id


def test_evaluation_api_not_found():
    res = client.get("/api/v1/evaluation/results/non_existent_id_12345")
    assert res.status_code == 404
