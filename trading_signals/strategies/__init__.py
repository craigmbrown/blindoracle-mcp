"""
Strategy ABC + Registry for the Autoresearch Trade Optimizer.

REQ-AUTORESEARCH-004: Pluggable strategy architecture
BLP-031: Self-Improvement through strategy comparison

Each strategy implements fetch_data() and generate_signal() and registers
itself via @StrategyRegistry.register decorator.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from trading_signals.backtester import DualAmount


@dataclass
class StrategySignal:
    """Signal produced by a strategy."""
    direction: str  # "buy", "sell", or "hold"
    confidence: float  # 0-100
    reasoning: str
    metadata: Dict = None

    def __post_init__(self):
        self.metadata = self.metadata or {}


class Strategy(ABC):
    """Base class for all trading strategies."""

    name: str = "base"
    description: str = ""

    def __init__(self, config: dict):
        self.config = config
        self.api_costs = DualAmount.from_usd(0.0, 85000.0)

    @abstractmethod
    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch strategy-specific data from APIs."""
        ...

    @abstractmethod
    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate buy/sell/None signal from data + price history."""
        ...

    def get_config_section(self) -> dict:
        """Return this strategy's config subsection."""
        return self.config.get(self.name, {})

    def add_api_cost(self, usd: float, btc_price: float = 85000.0):
        """Track cumulative API costs."""
        self.api_costs = DualAmount.from_usd(
            self.api_costs.usd + usd, btc_price
        )


class StrategyRegistry:
    """Registry for pluggable strategies."""

    _strategies: Dict[str, Type[Strategy]] = {}

    @classmethod
    def register(cls, strategy_cls: Type[Strategy]) -> Type[Strategy]:
        """Decorator to register a strategy class."""
        cls._strategies[strategy_cls.name] = strategy_cls
        return strategy_cls

    @classmethod
    def get(cls, name: str, config: dict) -> Strategy:
        """Instantiate a registered strategy by name."""
        if name not in cls._strategies:
            available = ", ".join(cls._strategies.keys())
            raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
        return cls._strategies[name](config)

    @classmethod
    def list_all(cls) -> List[str]:
        """List all registered strategy names."""
        return list(cls._strategies.keys())


# Auto-import strategy modules to trigger @register decorators
def _auto_register():
    try:
        from trading_signals.strategies import forecast_arb  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import commitment_momentum  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import market_maker  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import prob_momentum  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import cross_platform_arb  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import consensus_divergence  # noqa: F401
    except ImportError:
        pass
    # RQ-030: Data-enriched strategies
    try:
        from trading_signals.strategies import news_catalyst  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import onchain_flow  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import macro_divergence  # noqa: F401
    except ImportError:
        pass
    try:
        from trading_signals.strategies import trending_momentum  # noqa: F401
    except ImportError:
        pass


_auto_register()
