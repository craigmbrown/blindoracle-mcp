#!/usr/bin/env python3
"""
Real Market Data Fetcher for Production Prediction Markets
Phase 3: Real API Integration for Kalshi and Polymarket

This module fetches REAL market data from:
- Kalshi Elections API (no auth needed for market data)
- Polymarket Gamma API (public read access)

Created: 2025-12-09
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict


@dataclass
class RealMarket:
    """Normalized market data from real APIs"""

    id: str
    platform: str  # "kalshi" or "polymarket"
    title: str
    description: str = ""
    yes_price: float = 0.5  # 0.0 to 1.0
    no_price: float = 0.5
    volume: float = 0.0
    liquidity: float = 0.0
    status: str = "active"
    closes_at: Optional[datetime] = None
    category: str = "General"
    ticker: str = ""  # Kalshi ticker or Polymarket condition_id
    raw_data: Dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    is_real: bool = True
    source: str = ""  # "kalshi_api" or "polymarket_gamma_api"
    # REQ-RQ166-012: Topological resolver fields
    resolver_confidence: float = 0.5   # 0.0–1.0, updated by propagation
    correlation_ids: List[str] = field(default_factory=list)  # Correlated market IDs

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        result["closes_at"] = self.closes_at.isoformat() if self.closes_at else None
        result["fetched_at"] = self.fetched_at.isoformat()
        return result


@dataclass
class ArbitrageOpportunity:
    """Cross-platform arbitrage opportunity"""

    buy_market: RealMarket
    sell_market: RealMarket
    side: str  # "YES" or "NO"
    buy_price: float
    sell_price: float
    spread: float
    expected_profit_pct: float
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "buy_platform": self.buy_market.platform,
            "buy_market_id": self.buy_market.id,
            "buy_title": self.buy_market.title[:60],
            "sell_platform": self.sell_market.platform,
            "sell_market_id": self.sell_market.id,
            "sell_title": self.sell_market.title[:60],
            "side": self.side,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "spread": self.spread,
            "expected_profit_pct": self.expected_profit_pct,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "is_real": True,
        }


class RealMarketDataFetcher:
    """
    Fetches REAL market data from Kalshi and Polymarket APIs.
    No authentication needed for read-only market data.
    """

    # API Endpoints
    KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, List[RealMarket]] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds = 60  # Cache for 60 seconds
        print("[REAL_MARKET_DATA] Initialized - fetching from Kalshi & Polymarket APIs")

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

    # =====================
    # KALSHI API Methods
    # =====================

    async def fetch_kalshi_markets(self, limit: int = 50) -> List[RealMarket]:
        """
        Fetch markets from Kalshi Elections API

        API Docs: https://docs.kalshi.com
        Endpoint: GET /trade-api/v2/markets
        """
        markets = []
        session = await self._ensure_session()

        try:
            url = f"{self.KALSHI_BASE_URL}/markets"
            params = {"limit": min(limit, 100)}  # Max 100 per request

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    kalshi_markets = data.get("markets", [])

                    for m in kalshi_markets:
                        try:
                            # Parse Kalshi response
                            yes_price = (
                                float(m.get("yes_price", 50)) / 100.0
                            )  # Convert cents to decimal

                            # Parse close time
                            close_time = m.get("close_time", "")
                            closes_at = None
                            if close_time:
                                try:
                                    closes_at = datetime.fromisoformat(
                                        close_time.replace("Z", "+00:00")
                                    )
                                except:
                                    closes_at = datetime.utcnow() + timedelta(days=30)

                            market = RealMarket(
                                id=m.get("ticker", m.get("id", "")),
                                platform="kalshi",
                                title=m.get("title", "Unknown Market"),
                                description=m.get("subtitle", ""),
                                yes_price=yes_price,
                                no_price=1.0 - yes_price,
                                volume=float(m.get("volume", 0) or 0),
                                liquidity=float(m.get("open_interest", 0) or 0),
                                status=m.get("status", "active"),
                                closes_at=closes_at,
                                category=m.get("category", "General"),
                                ticker=m.get("ticker", ""),
                                raw_data={
                                    "event_ticker": m.get("event_ticker", ""),
                                    "series_ticker": m.get("series_ticker", ""),
                                },
                                source="kalshi_api",
                            )
                            markets.append(market)
                        except Exception as parse_err:
                            print(f"[KALSHI] Parse error: {parse_err}")
                            continue

                    print(f"[KALSHI_API] Fetched {len(markets)} REAL markets")
                else:
                    print(f"[KALSHI] API returned {response.status}")

        except Exception as e:
            print(f"[KALSHI] Error: {e}")

        return markets

    # =====================
    # POLYMARKET API Methods
    # =====================

    async def fetch_polymarket_markets(self, limit: int = 50) -> List[RealMarket]:
        """
        Fetch markets from Polymarket Gamma API

        API Docs: https://docs.polymarket.com
        Endpoint: GET /events (recommended) or /markets
        """
        markets = []
        session = await self._ensure_session()

        try:
            # Use events endpoint with volume ordering for active markets
            url = f"{self.POLYMARKET_GAMMA_URL}/events"
            params = {
                "limit": min(limit, 100),
                "order": "volume24hr",
                "ascending": "false",
                "closed": "false",
            }

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    events = await response.json()

                    for event in events:
                        event_markets = event.get("markets", [])

                        for m in event_markets:
                            try:
                                # Parse outcome prices
                                outcome_prices = m.get("outcomePrices", [])
                                if isinstance(outcome_prices, str):
                                    # Sometimes it's a JSON string
                                    try:
                                        outcome_prices = json.loads(outcome_prices)
                                    except:
                                        outcome_prices = [0.5, 0.5]

                                if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                                    try:
                                        yes_price = float(outcome_prices[0])
                                    except (ValueError, TypeError):
                                        yes_price = 0.5
                                else:
                                    yes_price = 0.5

                                # Parse end date
                                end_date = m.get("endDate", "")
                                closes_at = None
                                if end_date:
                                    try:
                                        closes_at = datetime.fromisoformat(
                                            end_date.replace("Z", "+00:00")
                                        )
                                    except:
                                        closes_at = datetime.utcnow() + timedelta(days=30)

                                market = RealMarket(
                                    id=m.get("conditionId", m.get("id", "")),
                                    platform="polymarket",
                                    title=m.get("question", event.get("title", "Unknown")),
                                    description=m.get("description", ""),
                                    yes_price=yes_price,
                                    no_price=1.0 - yes_price,
                                    volume=float(m.get("volume", 0) or 0),
                                    liquidity=float(m.get("liquidity", 0) or 0),
                                    status="active" if m.get("active", True) else "closed",
                                    closes_at=closes_at,
                                    category=event.get("category", m.get("category", "General")),
                                    ticker=m.get("conditionId", ""),
                                    raw_data={
                                        "event_slug": event.get("slug", ""),
                                        "question_id": m.get("questionId", ""),
                                        "ctf_address": "0x4D953115678b15CE0B0396bCF95Db68003f86FB5",
                                    },
                                    source="polymarket_gamma_api",
                                )
                                markets.append(market)
                            except Exception as parse_err:
                                print(f"[POLYMARKET] Parse error: {parse_err}")
                                continue

                    print(f"[POLYMARKET_GAMMA_API] Fetched {len(markets)} REAL markets")
                else:
                    print(f"[POLYMARKET] API returned {response.status}")

        except Exception as e:
            print(f"[POLYMARKET] Error: {e}")

        return markets

    # =====================
    # Combined Methods
    # =====================

    async def fetch_all_markets(self, limit_per_platform: int = 30) -> Dict[str, List[RealMarket]]:
        """
        Fetch markets from all platforms concurrently

        Returns:
            Dict with "kalshi" and "polymarket" keys containing market lists
        """
        # Check cache
        if (
            self._cache_timestamp
            and (datetime.utcnow() - self._cache_timestamp).seconds < self._cache_ttl_seconds
        ):
            print("[CACHE] Returning cached market data")
            return self._cache

        # Fetch from both platforms concurrently
        kalshi_task = asyncio.create_task(self.fetch_kalshi_markets(limit_per_platform))
        polymarket_task = asyncio.create_task(self.fetch_polymarket_markets(limit_per_platform))

        kalshi_markets, polymarket_markets = await asyncio.gather(
            kalshi_task, polymarket_task, return_exceptions=True
        )

        # Handle exceptions
        if isinstance(kalshi_markets, Exception):
            print(f"[KALSHI] Fetch failed: {kalshi_markets}")
            kalshi_markets = []
        if isinstance(polymarket_markets, Exception):
            print(f"[POLYMARKET] Fetch failed: {polymarket_markets}")
            polymarket_markets = []

        result = {"kalshi": kalshi_markets, "polymarket": polymarket_markets}

        # Update cache
        self._cache = result
        self._cache_timestamp = datetime.utcnow()

        total = len(kalshi_markets) + len(polymarket_markets)
        print(
            f"[REAL_MARKET_DATA] Total: {total} markets ({len(kalshi_markets)} Kalshi, {len(polymarket_markets)} Polymarket)"
        )

        return result

    # =====================
    # Arbitrage Detection
    # =====================

    def find_arbitrage_opportunities(
        self,
        kalshi_markets: List[RealMarket],
        polymarket_markets: List[RealMarket],
        min_spread: float = 0.03,  # 3% minimum spread
    ) -> List[ArbitrageOpportunity]:
        """
        Find cross-platform arbitrage opportunities by matching similar markets

        This is a simple implementation using keyword matching.
        Production would use more sophisticated NLP/embedding similarity.
        """
        opportunities = []

        def calculate_similarity(title1: str, title2: str) -> float:
            """Simple word overlap similarity"""
            words1 = set(title1.lower().split())
            words2 = set(title2.lower().split())

            # Remove common words
            stopwords = {"will", "the", "a", "an", "in", "on", "at", "by", "be", "to", "of", "?"}
            words1 = words1 - stopwords
            words2 = words2 - stopwords

            if not words1 or not words2:
                return 0.0

            intersection = words1.intersection(words2)
            union = words1.union(words2)

            return len(intersection) / len(union) if union else 0.0

        # Compare markets across platforms
        for k_market in kalshi_markets:
            for p_market in polymarket_markets:
                similarity = calculate_similarity(k_market.title, p_market.title)

                if similarity > 0.5:  # 50% similarity threshold
                    # Check YES price spread
                    yes_spread = abs(k_market.yes_price - p_market.yes_price)

                    if yes_spread >= min_spread:
                        # Determine buy/sell direction
                        if k_market.yes_price < p_market.yes_price:
                            buy_market, sell_market = k_market, p_market
                            buy_price, sell_price = k_market.yes_price, p_market.yes_price
                        else:
                            buy_market, sell_market = p_market, k_market
                            buy_price, sell_price = p_market.yes_price, k_market.yes_price

                        opp = ArbitrageOpportunity(
                            buy_market=buy_market,
                            sell_market=sell_market,
                            side="YES",
                            buy_price=buy_price,
                            sell_price=sell_price,
                            spread=yes_spread,
                            expected_profit_pct=(
                                (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
                            ),
                            confidence=similarity,
                        )
                        opportunities.append(opp)

                    # Also check NO price spread
                    no_spread = abs(k_market.no_price - p_market.no_price)

                    if no_spread >= min_spread:
                        if k_market.no_price < p_market.no_price:
                            buy_market, sell_market = k_market, p_market
                            buy_price, sell_price = k_market.no_price, p_market.no_price
                        else:
                            buy_market, sell_market = p_market, k_market
                            buy_price, sell_price = p_market.no_price, k_market.no_price

                        opp = ArbitrageOpportunity(
                            buy_market=buy_market,
                            sell_market=sell_market,
                            side="NO",
                            buy_price=buy_price,
                            sell_price=sell_price,
                            spread=no_spread,
                            expected_profit_pct=(
                                (sell_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
                            ),
                            confidence=similarity,
                        )
                        opportunities.append(opp)

        # Sort by expected profit
        opportunities.sort(key=lambda x: x.expected_profit_pct, reverse=True)

        print(
            f"[ARBITRAGE] Found {len(opportunities)} opportunities with spread >= {min_spread:.1%}"
        )

        return opportunities

    # =====================
    # Job Integration
    # =====================

    async def get_market_analysis_for_job(self) -> Dict[str, Any]:
        """
        Get comprehensive market analysis for job runner integration.
        Returns data in format expected by multi_strategy_runner.py
        """
        all_markets = await self.fetch_all_markets()

        kalshi_markets = all_markets.get("kalshi", [])
        polymarket_markets = all_markets.get("polymarket", [])

        # Find arbitrage opportunities
        opportunities = self.find_arbitrage_opportunities(kalshi_markets, polymarket_markets)

        # Calculate platform statistics
        kalshi_volume = sum(m.volume for m in kalshi_markets)
        poly_volume = sum(m.volume for m in polymarket_markets)

        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "is_real": True,
            "source": "real_market_apis",
            "platforms": {
                "kalshi": {
                    "market_count": len(kalshi_markets),
                    "total_volume": kalshi_volume,
                    "markets": [m.to_dict() for m in kalshi_markets[:10]],  # Top 10
                },
                "polymarket": {
                    "market_count": len(polymarket_markets),
                    "total_volume": poly_volume,
                    "markets": [m.to_dict() for m in polymarket_markets[:10]],  # Top 10
                },
            },
            "arbitrage_opportunities": [o.to_dict() for o in opportunities[:5]],  # Top 5
            "summary": {
                "total_markets": len(kalshi_markets) + len(polymarket_markets),
                "total_volume": kalshi_volume + poly_volume,
                "arbitrage_count": len(opportunities),
                "best_spread": opportunities[0].spread if opportunities else 0,
            },
        }

        return analysis


# Synchronous wrapper for job runner
def get_real_market_data_sync() -> Dict[str, Any]:
    """
    Synchronous wrapper for use in job runner.
    Creates event loop and runs async fetch.
    """
    fetcher = RealMarketDataFetcher()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(fetcher.get_market_analysis_for_job())
    finally:
        loop.run_until_complete(fetcher.close())
        loop.close()

    return result


# Test function
if __name__ == "__main__":

    async def test():
        print("=" * 60)
        print("Testing Real Market Data Fetcher")
        print("=" * 60)

        fetcher = RealMarketDataFetcher()

        try:
            # Fetch all markets
            all_markets = await fetcher.fetch_all_markets(limit_per_platform=10)

            print("\n--- KALSHI MARKETS ---")
            for m in all_markets["kalshi"][:3]:
                print(f"  {m.title[:60]}...")
                print(f"    YES: {m.yes_price:.1%} | Volume: ${m.volume:,.0f}")

            print("\n--- POLYMARKET MARKETS ---")
            for m in all_markets["polymarket"][:3]:
                print(f"  {m.title[:60]}...")
                print(f"    YES: {m.yes_price:.1%} | Volume: ${m.volume:,.0f}")

            # Find arbitrage
            print("\n--- ARBITRAGE OPPORTUNITIES ---")
            opportunities = fetcher.find_arbitrage_opportunities(
                all_markets["kalshi"], all_markets["polymarket"], min_spread=0.02
            )

            for opp in opportunities[:3]:
                print(f"  {opp.side}: Buy on {opp.buy_market.platform} @ {opp.buy_price:.1%}")
                print(f"       Sell on {opp.sell_market.platform} @ {opp.sell_price:.1%}")
                print(f"       Spread: {opp.spread:.1%} | Profit: {opp.expected_profit_pct:.1f}%")

            # Get job analysis
            print("\n--- JOB ANALYSIS ---")
            analysis = await fetcher.get_market_analysis_for_job()
            print(f"  Total Markets: {analysis['summary']['total_markets']}")
            print(f"  Total Volume: ${analysis['summary']['total_volume']:,.0f}")
            print(f"  Arbitrage Opportunities: {analysis['summary']['arbitrage_count']}")
            print(f"  Is Real Data: {analysis['is_real']}")

        finally:
            await fetcher.close()

        print("\n" + "=" * 60)
        print("Test Complete")
        print("=" * 60)

    asyncio.run(test())
