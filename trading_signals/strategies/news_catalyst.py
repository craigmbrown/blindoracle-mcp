"""
Strategy 8: News Catalyst — Detect breaking crypto news events and trade on sentiment.

REQ-RQ030-002: News event detection strategy
BLP-031: Self-Improvement through real-time news signal fusion

Signal logic:
- Search for breaking crypto news via WebSearch (verified live 2026-03-16)
- Score headlines using bullish/bearish keyword counting
- Trade when net sentiment score exceeds threshold with 3+ news items
- Fall back to RSI when no news data available
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.web_data_client import WebDataClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class NewsCatalystStrategy(Strategy):
    """Detect breaking crypto news events and trade on sentiment magnitude."""

    name = "news_catalyst"
    description = "Trade on breaking crypto news sentiment detection"

    DEFAULT_BULLISH = [
        "etf", "adoption", "institutional", "rally", "breakout", "surge",
        "bullish", "approval", "partnership", "upgrade", "record", "inflow",
    ]
    DEFAULT_BEARISH = [
        "hack", "ban", "crash", "sec", "fraud", "liquidation",
        "bearish", "exploit", "lawsuit", "fine", "outflow", "dump",
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self.web_client = WebDataClient()
        self.indicators = TechnicalIndicators()

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Search for recent crypto news about this asset."""
        cfg = self.get_config_section()
        query = f"{asset} cryptocurrency news today"

        news = await self.web_client.search_news(query, max_results=10)

        # Score each headline
        bullish_kw = cfg.get("bullish_keywords", self.DEFAULT_BULLISH)
        bearish_kw = cfg.get("bearish_keywords", self.DEFAULT_BEARISH)

        scored = []
        for item in news:
            text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            bull_count = sum(1 for kw in bullish_kw if kw.lower() in text)
            bear_count = sum(1 for kw in bearish_kw if kw.lower() in text)

            # Normalize to -1..+1 range
            total = bull_count + bear_count
            if total > 0:
                score = (bull_count - bear_count) / total
            else:
                score = 0.0

            scored.append({
                "title": item.get("title", ""),
                "score": score,
                "bullish_hits": bull_count,
                "bearish_hits": bear_count,
            })

        return {
            "asset": asset,
            "news_count": len(scored),
            "scored_news": scored,
        }

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from news sentiment magnitude."""
        cfg = self.get_config_section()
        threshold = cfg.get("sentiment_threshold", 0.6)
        min_count = cfg.get("min_news_count", 3)

        if not prices or len(prices) < 30:
            return None

        scored = data.get("scored_news", [])
        if len(scored) < min_count:
            # Not enough news, fall back to RSI
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Aggregate sentiment across all headlines
        scores = [s["score"] for s in scored if s["score"] != 0]
        if not scores:
            return None

        avg_sentiment = sum(scores) / len(scores)

        # Strong bullish news cluster
        if avg_sentiment > threshold:
            # Confirm: price not already extended (avoid buying tops)
            if len(prices) >= 5 and prices[-1] <= max(prices[-5:]) * 1.05:
                return "buy"

        # Strong bearish news cluster
        elif avg_sentiment < -threshold:
            # Confirm: price not already crashed
            if len(prices) >= 5 and prices[-1] >= min(prices[-5:]) * 0.95:
                return "sell"

        # Moderate sentiment with RSI confirmation
        if abs(avg_sentiment) > threshold * 0.5:
            rsi = self.indicators.calculate_rsi(prices)
            if rsi:
                if avg_sentiment > 0 and rsi.signal == "buy":
                    return "buy"
                elif avg_sentiment < 0 and rsi.signal == "sell":
                    return "sell"

        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "sentiment_threshold": 0.6,
            "min_news_count": 3,
            "bullish_keywords": self.DEFAULT_BULLISH,
            "bearish_keywords": self.DEFAULT_BEARISH,
        }
        section = self.config.get("news_catalyst", {})
        defaults.update(section)
        return defaults
