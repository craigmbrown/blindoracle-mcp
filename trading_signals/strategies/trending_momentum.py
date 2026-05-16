"""
Strategy 11: Trending Momentum — Combine CoinGecko trending coins with
prediction market confirmation for high-conviction momentum trades.

REQ-RQ030-005: CoinGecko trending + prediction market confirmation strategy
BLP-031: Self-Improvement through social-proof + smart-money fusion

Signal logic:
- Fetch CoinGecko /search/trending (verified live 2026-03-16)
- Check if target asset is in top trending coins
- Cross-reference with Polymarket/Manifold prediction market probabilities
- When coin enters trending AND has bullish PM signal = buy
- When coin drops from trending with bearish PM signal = sell
- Filters pump-and-dumps by requiring prediction market confirmation
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.web_data_client import WebDataClient
from trading_signals.strategies.prediction_market_client import PredictionMarketClient
from trading_signals.indicators import TechnicalIndicators


# Map common asset tickers to CoinGecko symbols
ASSET_TO_SYMBOL = {
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "LINK": "LINK",
    "DOGE": "DOGE",
    "ADA": "ADA",
    "AVAX": "AVAX",
    "DOT": "DOT",
    "MATIC": "MATIC",
    "ATOM": "ATOM",
}


@StrategyRegistry.register
class TrendingMomentumStrategy(Strategy):
    """Trade trending coins confirmed by prediction market signals."""

    name = "trending_momentum"
    description = "Trade CoinGecko trending coins with prediction market confirmation"

    def __init__(self, config: dict):
        super().__init__(config)
        self.web_client = WebDataClient()
        self.pm_client = PredictionMarketClient()
        self.indicators = TechnicalIndicators()
        # Track which assets were previously trending
        self._prev_trending: set = set()

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch CoinGecko trending coins + prediction market data."""
        # Get trending coins
        trending = await self.web_client.get_trending_coins()

        # Check if our asset is in trending
        symbol = ASSET_TO_SYMBOL.get(asset.upper(), asset.upper())
        trending_symbols = {c["symbol"].upper() for c in trending}
        is_trending = symbol in trending_symbols

        # Get trending rank (lower = more trending)
        trending_rank = None
        for c in trending:
            if c["symbol"].upper() == symbol:
                trending_rank = c.get("score", 99) + 1  # score is 0-indexed
                break

        # Detect trend transitions
        was_trending = symbol in self._prev_trending
        entered_trending = is_trending and not was_trending
        left_trending = not is_trending and was_trending

        # Update tracking
        self._prev_trending = trending_symbols

        # Get prediction market data for cross-reference
        pm_markets = await self.pm_client.get_polymarket_markets(limit=30, crypto_only=True)
        asset_lower = asset.lower()
        relevant_pm = [m for m in pm_markets if asset_lower in m["question"].lower()]

        # Also check Manifold for additional signal
        manifold_markets = await self.pm_client.get_manifold_markets(term=asset_lower, limit=10)
        relevant_manifold = [
            m for m in manifold_markets
            if asset_lower in m["question"].lower()
        ]

        # Aggregate prediction market sentiment
        all_probs = []
        for m in relevant_pm:
            all_probs.append(m["yes_prob"])
        for m in relevant_manifold:
            all_probs.append(m["yes_prob"])

        avg_pm_prob = sum(all_probs) / len(all_probs) if all_probs else 0.5

        return {
            "asset": asset,
            "is_trending": is_trending,
            "trending_rank": trending_rank,
            "entered_trending": entered_trending,
            "left_trending": left_trending,
            "trending_count": len(trending),
            "avg_pm_probability": avg_pm_prob,
            "pm_markets_count": len(all_probs),
        }

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from trending status + prediction market confirmation."""
        cfg = self.get_config_section()
        min_rank = cfg.get("min_trending_rank", 15)
        min_pm_prob = cfg.get("min_prediction_prob", 0.55)

        if not prices or len(prices) < 30:
            return None

        is_trending = data.get("is_trending", False)
        trending_rank = data.get("trending_rank")
        entered_trending = data.get("entered_trending", False)
        left_trending = data.get("left_trending", False)
        avg_pm_prob = data.get("avg_pm_probability", 0.5)

        # Calculate price momentum
        if len(prices) >= 5:
            short_momentum = (prices[-1] - prices[-5]) / prices[-5]
        else:
            short_momentum = 0.0

        # Signal 1: Newly entered trending + bullish PM = strong buy
        if entered_trending:
            if avg_pm_prob > min_pm_prob and short_momentum > 0:
                return "buy"

        # Signal 2: Currently trending with high rank + PM confirmation
        if is_trending and trending_rank is not None and trending_rank <= min_rank:
            if avg_pm_prob > min_pm_prob:
                # Confirm with price momentum (avoid buying at the top)
                if short_momentum > 0 and short_momentum < 0.10:  # Not already extended
                    return "buy"

        # Signal 3: Left trending + bearish PM = sell
        if left_trending:
            if avg_pm_prob < (1 - min_pm_prob):
                return "sell"

        # Signal 4: Trending but PM says bearish = potential top
        if is_trending and avg_pm_prob < 0.35:
            if short_momentum < 0:
                return "sell"

        # No PM data available, fall back to trending + RSI
        if data.get("pm_markets_count", 0) == 0:
            if is_trending and trending_rank and trending_rank <= 5:
                rsi = self.indicators.calculate_rsi(prices)
                if rsi and rsi.signal == "buy":
                    return "buy"

        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "min_trending_rank": 15,
            "min_prediction_prob": 0.55,
        }
        section = self.config.get("trending_momentum", {})
        defaults.update(section)
        return defaults
