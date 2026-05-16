"""
Strategy 6: Cross-Platform Arbitrage — Detect same events priced differently
across Polymarket (real money) and Manifold (play money) platforms.

REQ-RQ029-003: Cross-platform prediction market arbitrage strategy
BLP-031: Self-Improvement through multi-platform price discovery

Signal logic:
- Fetch markets from Polymarket and Manifold
- Fuzzy-match same questions across platforms
- When probability spread exceeds threshold -> follow the higher-volume platform
- Fall back to RSI when no cross-platform matches found
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.prediction_market_client import PredictionMarketClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class CrossPlatformArbStrategy(Strategy):
    """Detect cross-platform prediction market mispricing."""

    name = "cross_platform_arb"
    description = "Detect cross-platform prediction market mispricing"

    def __init__(self, config: dict):
        super().__init__(config)
        self.pm_client = PredictionMarketClient()
        self.indicators = TechnicalIndicators()

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch markets from Polymarket and Manifold, find matches."""
        # Get markets from multiple platforms
        poly_markets = await self.pm_client.get_polymarket_markets(
            limit=30, crypto_only=True,
        )
        manifold_markets = await self.pm_client.get_manifold_markets(
            term=asset.lower(), limit=30,
        )

        # Find matching markets
        matches = self.pm_client.match_markets(
            poly_markets, manifold_markets, min_similarity=0.3,
        )

        spreads = []
        for poly, mani, similarity in matches:
            spread = poly["yes_prob"] - mani["yes_prob"]
            spreads.append({
                "poly": poly,
                "manifold": mani,
                "spread": spread,
                "abs_spread": abs(spread),
                "similarity": similarity,
                "poly_volume": poly.get("volume", 0),
            })

        spreads.sort(key=lambda x: x["abs_spread"], reverse=True)
        return {"asset": asset, "matches": matches, "spreads": spreads}

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from cross-platform probability spread."""
        cfg = self.get_config_section()
        threshold = cfg.get("arb_threshold", 0.10)

        if not prices or len(prices) < 30:
            return None

        spreads = data.get("spreads", [])
        if not spreads:
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Look at biggest spread
        actionable = [s for s in spreads if s["abs_spread"] > threshold]
        if not actionable:
            return None

        top = actionable[0]
        # Follow the platform with higher volume (more informed)
        if top["poly_volume"] > 0:
            # Polymarket leads - use its probability for direction
            if top["poly"]["yes_prob"] > top["manifold"]["yes_prob"]:
                return "buy"  # Polymarket more bullish
            else:
                return "sell"  # Polymarket more bearish

        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "arb_threshold": 0.10,
            "min_match_similarity": 0.3,
            "platforms": ["polymarket", "manifold"],
        }
        section = self.config.get("cross_platform_arb", {})
        defaults.update(section)
        return defaults
