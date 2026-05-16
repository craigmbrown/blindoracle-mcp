"""
Strategy 1: Forecast Arbitrage — Detect mispricing between BO forecast
probabilities and Chainlink oracle spot prices.

REQ-AUTORESEARCH-006: Forecast Arbitrage strategy
BLP-031: Self-Improvement through probability-price divergence detection

Signal logic:
- For crypto forecast markets, extract the implied price target
- Compare BO probability vs Chainlink spot price distance to target
- If probability is low but price is close to target → underpriced → BUY
- If probability is high but price is far from target → overpriced → SELL
"""

from typing import Dict, List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.bo_api_client import BOApiClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class ForecastArbStrategy(Strategy):
    """Forecast Arbitrage: BO probability vs Chainlink spot price."""

    name = "forecast_arb"
    description = "Detect mispricing between forecast probabilities and oracle spot prices"

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = BOApiClient()
        self.indicators = TechnicalIndicators()
        self._cached_forecasts: List[dict] = []
        self._cached_prices: Dict[str, float] = {}

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch BO forecasts + Chainlink spot price for the asset."""
        data = {"forecasts": [], "spot_price": None, "asset": asset}

        # Get forecasts
        forecasts = await self.client.get_forecasts(limit=30)
        if forecasts:
            # Filter to crypto-related forecasts
            crypto_keywords = [asset.lower(), asset.upper()]
            data["forecasts"] = [
                f for f in forecasts
                if any(kw in str(f.get("question", "")).lower() for kw in [asset.lower()])
            ]
            self._cached_forecasts = data["forecasts"]

        # Get Chainlink spot price
        pair = f"{asset}-USD"
        price_data = await self.client.get_chainlink_price(pair)
        if price_data and "price" in price_data:
            data["spot_price"] = float(price_data["price"])
            self._cached_prices[asset] = data["spot_price"]

        return data

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from forecast-vs-spot divergence + technical confirmation."""
        cfg = self.get_config_section()
        arb_threshold = cfg.get("arb_threshold", 0.05)

        forecasts = data.get("forecasts", [])
        spot_price = data.get("spot_price")

        # If no API data, fall back to pure technical analysis
        if not spot_price or not prices or len(prices) < 30:
            return self._technical_fallback(prices)

        # Check each forecast for mispricing
        buy_signals = 0
        sell_signals = 0

        for forecast in forecasts:
            prob = forecast.get("probability", {})
            yes_prob = prob.get("yes", 0.5) if isinstance(prob, dict) else 0.5
            question = str(forecast.get("question", "")).lower()

            # Try to extract price target from question (e.g., "BTC > $90K")
            target_price = self._extract_price_target(question)
            if not target_price:
                continue

            # Distance from spot to target as fraction
            distance = abs(target_price - spot_price) / spot_price

            # Mispricing detection
            if distance < arb_threshold and yes_prob < 0.4:
                # Price is close to target but market says unlikely → underpriced
                buy_signals += 1
            elif distance > arb_threshold * 3 and yes_prob > 0.7:
                # Price is far from target but market says likely → overpriced
                sell_signals += 1

        # Combine with momentum for direction confirmation
        momentum = self._price_momentum(prices)

        if buy_signals > sell_signals and momentum >= 0:
            return "buy"
        elif sell_signals > buy_signals and momentum <= 0:
            return "sell"

        return self._technical_fallback(prices)

    def _extract_price_target(self, question: str) -> Optional[float]:
        """Extract a dollar price target from a forecast question string."""
        import re
        # Match patterns like "$90K", "$90,000", "$90000", "90k"
        patterns = [
            r'\$(\d+(?:,\d{3})*(?:\.\d+)?)\s*[kK]',  # $90K
            r'\$(\d+(?:,\d{3})*(?:\.\d+)?)',  # $90,000
            r'(\d+(?:,\d{3})*)\s*[kK]',  # 90K
        ]
        for pattern in patterns:
            match = re.search(pattern, question)
            if match:
                val = float(match.group(1).replace(",", ""))
                if question.lower().endswith("k") or "k" in match.group(0).lower():
                    val *= 1000
                return val
        return None

    def _price_momentum(self, prices: List[float]) -> float:
        """Simple momentum: positive = bullish, negative = bearish."""
        if len(prices) < 10:
            return 0.0
        return (prices[-1] - prices[-10]) / prices[-10]

    def _technical_fallback(self, prices: List[float]) -> Optional[str]:
        """Fall back to RSI when no forecast data available."""
        if not prices or len(prices) < 30:
            return None
        rsi = self.indicators.calculate_rsi(prices)
        if rsi and rsi.signal in ("buy", "sell"):
            return rsi.signal
        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "arb_threshold": 0.05,
            "min_liquidity_usd": 100,
            "max_position_usd": 50,
            "pairs": ["BTC-USD", "ETH-USD", "LINK-USD"],
        }
        section = self.config.get("forecast_arb", {})
        defaults.update(section)
        return defaults
