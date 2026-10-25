from app.backtesting.service import BacktestService
from app.strategies.ema_crossover import EMACrossoverStrategy


def test_primary_strategy_defaults_to_triple_ema_without_rsi_filter():
    strategy = EMACrossoverStrategy()
    assert strategy.parameters["fast_period"] == 9
    assert strategy.parameters["middle_period"] == 11
    assert strategy.parameters["slow_period"] == 20
    assert strategy.parameters["rsi_filter_enabled"] is False


def test_both_recommended_triple_ema_presets_are_valid_without_rsi_filter():
    for fast, middle, slow in ((9, 11, 20), (8, 13, 21)):
        strategy = EMACrossoverStrategy(custom_params={
            "fast_period": fast,
            "middle_period": middle,
            "slow_period": slow,
            "rsi_filter_enabled": False,
        })
        assert strategy.parameters["fast_period"] < strategy.parameters["middle_period"] < strategy.parameters["slow_period"]
        assert strategy.parameters["rsi_filter_enabled"] is False


def test_backtest_options_expose_both_ema_presets():
    options = BacktestService().get_config_options()
    assert options["strategy_presets"]["9/11/20"] == {
        "fast_period": 9, "middle_period": 11, "slow_period": 20, "rsi_filter_enabled": False
    }
    assert options["strategy_presets"]["8/13/21"] == {
        "fast_period": 8, "middle_period": 13, "slow_period": 21, "rsi_filter_enabled": False
    }
