from typing import Any, Dict, List, Optional
from app.strategies.base import BaseStrategy, StrategySignal
from app.strategies.ema_crossover import EMACrossoverStrategy


class StrategyRegistry:
    """
    Central registry and lifecycle manager for TokenIQ quantitative strategies.
    Decouples strategy execution and state from HTTP endpoints.
    """

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}
        # Register default baseline strategies
        self.register_strategy(EMACrossoverStrategy())

    def register_strategy(self, strategy: BaseStrategy) -> None:
        """Register a new strategy instance."""
        self._strategies[strategy.strategy_id] = strategy

    def get_strategy(self, strategy_id: str) -> Optional[BaseStrategy]:
        """Lookup strategy by identifier."""
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> List[Dict[str, Any]]:
        """List all available strategies with their metadata and current configuration."""
        result = []
        for strat in self._strategies.values():
            schema = strat.get_parameters_schema()
            result.append({
                "strategy_id": strat.strategy_id,
                "name": strat.name,
                "description": strat.description,
                "parameters_schema": schema.get("parameters", {}),
                "current_parameters": strat.parameters,
                "disclaimer": (
                    "DISCLAIMER: TokenIQ strategies are mathematical models for research and "
                    "analysis. They do not claim profitability, do not constitute investment advice, "
                    "and are not connected to automated order execution."
                ),
            })
        return result

    def get_latest_signal(
        self,
        strategy_id: str,
        symbol: str,
    ) -> Optional[StrategySignal]:
        """Retrieve the most recent signal produced by a specific strategy and symbol."""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return None
        return strategy.get_latest_signal(symbol)

    def get_all_latest_signals(self) -> List[StrategySignal]:
        """Retrieve all latest signals across all registered strategies."""
        signals: List[StrategySignal] = []
        for strat in self._strategies.values():
            signals.extend(strat.get_all_latest_signals().values())
        return signals


# Singleton strategy registry
strategy_registry = StrategyRegistry()
