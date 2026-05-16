"""
Strategy 7: Consensus Divergence — Follow money markets when they diverge
from crowd forecasts.

REQ-RQ029-004: Money-vs-crowd consensus divergence strategy
BLP-031: Self-Improvement through smart-money tracking

Signal logic:
- Polymarket = real money (informed traders, skin in the game)
- Manifold = play money (crowd wisdom, no financial stake)
- When money market diverges from crowd by >threshold -> follow the money
- Positive divergence (money > crowd) -> bullish signal
- Negative divergence (money < crowd) -> bearish signal
- Fall back to RSI when no cross-platform matches found
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.prediction_market_client import PredictionMarketClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class ConsensusDivergenceStrategy(Strategy):
    """Follow money markets when they diverge from crowd forecasts."""

    name = "consensus_divergence"
    description = "Follow money markets when they diverge from crowd forecasts"

    def __init__(self, config: dict):
        super().__init__(config)
        self.pm_client = PredictionMarketClient()
        self.indicators = TechnicalIndicators()

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch money market (Polymarket) and crowd market (Manifold) data."""
        # Money market (real money)
        money_markets = await self.pm_client.get_polymarket_markets(
            limit=30, crypto_only=True,
        )
        # Crowd market (play money)
        crowd_markets = await self.pm_client.get_manifold_markets(
            term=asset.lower(), limit=30,
        )

        # Match and compute divergence
        matches = self.pm_client.match_markets(
            money_markets, crowd_markets, min_similarity=0.3,
        )

        divergences = []
        for money, crowd, sim in matches:
            div = money["yes_prob"] - crowd["yes_prob"]
            divergences.append({
                "money": money,
                "crowd": crowd,
                "divergence": div,
                "abs_divergence": abs(div),
                "similarity": sim,
            })

        divergences.sort(key=lambda x: x["abs_divergence"], reverse=True)
        return {"asset": asset, "divergences": divergences}

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from money-vs-crowd divergence."""
        cfg = self.get_config_section()
        threshold = cfg.get("divergence_threshold", 0.15)

        if not prices or len(prices) < 30:
            return None

        divergences = data.get("divergences", [])
        if not divergences:
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Find actionable divergences
        actionable = [d for d in divergences if d["abs_divergence"] > threshold]
        if not actionable:
            return None

        # Follow the money
        top = actionable[0]
        if top["divergence"] > 0:
            # Money more bullish than crowd -> buy
            return "buy"
        else:
            # Money more bearish than crowd -> sell
            return "sell"

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "divergence_threshold": 0.15,
            "money_platform": "polymarket",
            "crowd_platform": "manifold",
        }
        section = self.config.get("consensus_divergence", {})
        defaults.update(section)
        return defaults
