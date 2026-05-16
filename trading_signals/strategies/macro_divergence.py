"""
Strategy 10: Macro Divergence — Detect divergence between macro sentiment
(Fed rate predictions on Kalshi) and crypto price direction.

REQ-RQ030-004: Macro-crypto correlation divergence strategy
BLP-031: Self-Improvement through cross-asset signal fusion

Signal logic:
- Fetch Kalshi Fed rate-cut market probabilities (verified live 2026-03-16)
- Search for macro headlines via WebSearch
- When Kalshi says rate cuts likely (>60%) but BTC falling = buy divergence
- When Kalshi says rate hikes likely but BTC rising = sell divergence
- Combines CFTC-regulated prediction market data with real-time macro news
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.web_data_client import WebDataClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class MacroDivergenceStrategy(Strategy):
    """Trade macro-crypto divergences using Kalshi rate markets + news."""

    name = "macro_divergence"
    description = "Trade when Fed rate predictions diverge from crypto direction"

    DOVISH_KEYWORDS = [
        "rate cut", "dovish", "easing", "pivot", "lower rates",
        "soft landing", "stimulus", "accommodative",
    ]
    HAWKISH_KEYWORDS = [
        "rate hike", "hawkish", "tightening", "higher rates",
        "inflation", "restrictive", "no cut",
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self.web_client = WebDataClient()
        self.indicators = TechnicalIndicators()

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch Kalshi rate markets + macro news headlines."""
        # Get Kalshi rate-cut prediction markets
        rate_markets = await self.web_client.get_kalshi_rate_markets()

        # Search for macro news
        news = await self.web_client.search_news(
            "Federal Reserve interest rate decision crypto impact", max_results=5
        )

        # Calculate aggregate rate-cut probability from Kalshi
        cut_probs = []
        for m in rate_markets:
            title = m.get("title", "").lower()
            # Markets about rate cuts: yes_prob = probability of cut happening
            if "cut" in title or "lower" in title or "decrease" in title:
                cut_probs.append(m["yes_prob"])
            # Markets about rate staying same or hiking: invert
            elif "hike" in title or "increase" in title or "raise" in title:
                cut_probs.append(1 - m["yes_prob"])  # invert: high hike prob = low cut prob

        avg_cut_prob = sum(cut_probs) / len(cut_probs) if cut_probs else 0.5

        # Score macro news sentiment
        dovish_count = 0
        hawkish_count = 0
        for item in news:
            text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            dovish_count += sum(1 for kw in self.DOVISH_KEYWORDS if kw in text)
            hawkish_count += sum(1 for kw in self.HAWKISH_KEYWORDS if kw in text)

        total_kw = dovish_count + hawkish_count
        if total_kw > 0:
            news_sentiment = (dovish_count - hawkish_count) / total_kw  # -1 to +1
        else:
            news_sentiment = 0.0

        return {
            "asset": asset,
            "rate_markets_count": len(rate_markets),
            "avg_cut_probability": avg_cut_prob,
            "news_macro_sentiment": news_sentiment,
            "dovish_count": dovish_count,
            "hawkish_count": hawkish_count,
            "kalshi_markets": rate_markets[:5],  # top 5 for logging
        }

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from macro-crypto divergence."""
        cfg = self.get_config_section()
        cut_threshold = cfg.get("rate_cut_threshold", 0.60)

        if not prices or len(prices) < 30:
            return None

        avg_cut_prob = data.get("avg_cut_probability", 0.5)
        news_sentiment = data.get("news_macro_sentiment", 0.0)

        # No Kalshi data, fall back to RSI
        if data.get("rate_markets_count", 0) == 0:
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Calculate crypto price direction over window
        window = min(len(prices), 24)  # ~24h if hourly
        if window < 5:
            return None
        crypto_return = (prices[-1] - prices[-window]) / prices[-window]

        # Combine Kalshi + news into macro score
        # Kalshi weight 70%, news weight 30%
        macro_score = avg_cut_prob * 0.7 + ((news_sentiment + 1) / 2) * 0.3

        # Divergence detection
        # Case 1: Dovish macro (rate cuts likely) + crypto falling = BUY divergence
        if macro_score > cut_threshold and crypto_return < -0.02:
            # Macro says bullish, crypto hasn't caught up yet
            rsi = self.indicators.calculate_rsi(prices)
            if not rsi or rsi.signal != "sell":  # Don't fight extreme oversold
                return "buy"

        # Case 2: Hawkish macro + crypto rising = SELL divergence
        if macro_score < (1 - cut_threshold) and crypto_return > 0.02:
            # Macro says bearish, crypto hasn't caught down yet
            rsi = self.indicators.calculate_rsi(prices)
            if not rsi or rsi.signal != "buy":  # Don't fight extreme overbought
                return "sell"

        # Case 3: Strong agreement (no divergence) — weaker signal
        if macro_score > 0.7 and crypto_return > 0.01:
            # Both say bullish, follow the trend
            rsi = self.indicators.calculate_rsi(prices)
            if rsi and rsi.signal == "buy":
                return "buy"

        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "rate_cut_threshold": 0.60,
            "divergence_window_hours": 24,
        }
        section = self.config.get("macro_divergence", {})
        defaults.update(section)
        return defaults
