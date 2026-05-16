from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta

from prediction_markets.base_market import MarketHistoryPoint
from prediction_markets.kalshi_client import KalshiMarketClient
from prediction_markets.polymarket_client import PolymarketCLOBClient


@dataclass
class ProbabilityChange:
    """Track probability changes over time"""

    market_id: str
    market_name: str
    current_probability: float
    previous_probability: float
    change_1h: float
    change_24h: float
    change_7d: float
    momentum_score: float  # -100 to +100


class ProbabilityMomentumTracker:
    """Track and analyze prediction market probability momentum"""

    def __init__(self, platform: str):
        self.client = self._get_client(platform)

    def _get_client(self, platform: str):
        if platform == "kalshi":
            return KalshiMarketClient()
        elif platform == "polymarket":
            return PolymarketCLOBClient()
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    async def get_momentum(self, market_id: str) -> Optional[ProbabilityChange]:
        """Get momentum data for a specific market"""
        market_details = await self.client.get_market_details(market_id)
        if not market_details:
            return None

        history = await self.client.get_market_history(market_id, resolution="1H")
        if not history:
            return None

        history = sorted(history, key=lambda x: x.timestamp)

        now = datetime.utcnow()

        current_prob = history[-1].price

        prob_1h_ago = self._get_prob_at(history, now - timedelta(hours=1))
        prob_24h_ago = self._get_prob_at(history, now - timedelta(days=1))
        prob_7d_ago = self._get_prob_at(history, now - timedelta(days=7))

        change_1h = (current_prob - prob_1h_ago) * 100 if prob_1h_ago is not None else 0
        change_24h = (current_prob - prob_24h_ago) * 100 if prob_24h_ago is not None else 0
        change_7d = (current_prob - prob_7d_ago) * 100 if prob_7d_ago is not None else 0

        # Simple momentum score: weighted average of changes
        momentum_score = (change_1h * 0.5) + (change_24h * 0.3) + (change_7d * 0.2)
        momentum_score = max(-100, min(100, momentum_score))

        return ProbabilityChange(
            market_id=market_id,
            market_name=market_details.title,
            current_probability=current_prob,
            previous_probability=history[-2].price if len(history) > 1 else current_prob,
            change_1h=change_1h,
            change_24h=change_24h,
            change_7d=change_7d,
            momentum_score=momentum_score,
        )

    def _get_prob_at(
        self, history: List[MarketHistoryPoint], time_point: datetime
    ) -> Optional[float]:
        """Finds the probability at or just before a given time_point."""
        relevant_points = [p for p in history if p.timestamp <= time_point]
        if not relevant_points:
            # If no data is old enough, check if the first data point is soon after
            if history and history[0].timestamp < time_point + timedelta(hours=1):
                return history[0].price
            return None
        return relevant_points[-1].price

    async def get_top_movers(self, limit: int = 10) -> List[ProbabilityChange]:
        """Get markets with largest probability changes"""
        all_markets = await self.client.get_markets(
            limit=100
        )  # Limit to 100 markets to avoid too many calls
        all_momentum = []
        for market in all_markets:
            momentum = await self.get_momentum(market.id)
            if momentum:
                all_momentum.append(momentum)

        # Sort by the absolute value of momentum score
        sorted_momentum = sorted(all_momentum, key=lambda x: abs(x.momentum_score), reverse=True)
        return sorted_momentum[:limit]

    async def detect_breakouts(self, threshold: float = 0.05) -> List[ProbabilityChange]:
        """Detect sudden probability movements"""
        all_markets = await self.client.get_markets(limit=100)
        breakouts = []
        for market in all_markets:
            momentum = await self.get_momentum(market.id)
            if momentum and abs(momentum.change_1h) > (threshold * 100):
                breakouts.append(momentum)
        return breakouts
