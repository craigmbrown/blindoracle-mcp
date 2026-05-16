"""
Strategy 5: Probability Momentum — Track probability shifts on Polymarket
crypto markets and trade the underlying asset when probabilities move suddenly.

REQ-RQ029-002: Prediction market probability momentum strategy
BLP-031: Self-Improvement through probability-price correlation

Signal logic:
- Fetch Polymarket crypto markets and track yes_prob over time
- When average probability delta exceeds threshold -> directional signal
- Confirm with price momentum before acting
- Fall back to RSI when no prediction market data available
"""

from typing import Dict, List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.prediction_market_client import PredictionMarketClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class ProbMomentumStrategy(Strategy):
    """Trade underlying when prediction market probabilities shift suddenly."""

    name = "prob_momentum"
    description = "Trade underlying when prediction market probabilities shift suddenly"

    def __init__(self, config: dict):
        super().__init__(config)
        self.pm_client = PredictionMarketClient()
        self.indicators = TechnicalIndicators()
        self._prev_probs: Dict[str, float] = {}  # market_id -> last_prob

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch Polymarket crypto markets and compute probability deltas."""
        markets = await self.pm_client.get_polymarket_markets(limit=30, crypto_only=True)
        # Filter to markets mentioning this asset
        asset_lower = asset.lower()
        relevant = [m for m in markets if asset_lower in m["question"].lower()]

        # Calculate probability deltas vs cached values
        deltas = []
        for m in relevant:
            mid = m["id"]
            current = m["yes_prob"]
            prev = self._prev_probs.get(mid, current)
            delta = current - prev
            self._prev_probs[mid] = current
            deltas.append({
                "market": m,
                "delta": delta,
                "current": current,
                "prev": prev,
            })

        return {"asset": asset, "markets": relevant, "deltas": deltas}

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from probability momentum + price confirmation."""
        cfg = self.get_config_section()
        threshold = cfg.get("delta_threshold", 0.05)

        if not prices or len(prices) < 30:
            return None

        deltas = data.get("deltas", [])
        if not deltas:
            # No prediction market data, fall back to RSI
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Aggregate probability momentum across all relevant markets
        total_delta = sum(d["delta"] for d in deltas) / max(len(deltas), 1)

        # Strong bullish probability shift
        if total_delta > threshold:
            # Confirm with price momentum
            if len(prices) >= 5 and prices[-1] >= prices[-5]:
                return "buy"
        # Strong bearish probability shift
        elif total_delta < -threshold:
            if len(prices) >= 5 and prices[-1] <= prices[-5]:
                return "sell"

        # Moderate signal: use absolute probability level
        avg_prob = sum(d["current"] for d in deltas) / max(len(deltas), 1)
        if avg_prob > 0.7:  # Markets think bullish
            rsi = self.indicators.calculate_rsi(prices)
            if rsi and rsi.signal == "buy":
                return "buy"
        elif avg_prob < 0.3:  # Markets think bearish
            rsi = self.indicators.calculate_rsi(prices)
            if rsi and rsi.signal == "sell":
                return "sell"

        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "delta_threshold": 0.05,
            "min_volume_usd": 50000,
            "platforms": ["polymarket"],
        }
        section = self.config.get("prob_momentum", {})
        defaults.update(section)
        return defaults
