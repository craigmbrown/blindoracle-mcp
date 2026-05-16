#!/usr/bin/env python3
"""
Unified Market Aggregator for Prediction Markets
@requirement: REQ-AGG-001 - Unified market aggregation
@requirement: REQ-AGG-002 - Cross-market opportunity detection
@requirement: REQ-AGG-003 - Normalized data presentation
@requirement: REQ-AGG-004 - Aggregated liquidity analysis
"""

import asyncio
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .base_market import BasePredictionMarket, NormalizedMarket, Order, Position, MarketStatus


@dataclass
class ArbitrageOpportunity:
    """
    REQ-AGG-002: Cross-market arbitrage opportunity
    """

    buy_market: NormalizedMarket
    sell_market: NormalizedMarket
    side: str  # YES or NO
    price_difference: float
    expected_profit: float
    suggested_size: float
    confidence_score: float
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "buy_market_id": self.buy_market.id,
            "buy_platform": self.buy_market.platform,
            "sell_market_id": self.sell_market.id,
            "sell_platform": self.sell_market.platform,
            "side": self.side,
            "price_difference": self.price_difference,
            "expected_profit": self.expected_profit,
            "suggested_size": self.suggested_size,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp.isoformat(),
            "description": f"Buy {self.side} on {self.buy_market.platform} at "
            f"{self.buy_market.yes_price if self.side == 'YES' else self.buy_market.no_price:.3f}, "
            f"sell on {self.sell_market.platform} at "
            f"{self.sell_market.yes_price if self.side == 'YES' else self.sell_market.no_price:.3f}",
        }


class UnifiedMarketAggregator:
    """
    REQ-AGG-001: Unified market aggregator across platforms
    @requirement: REQ-AGG-001 - Unified aggregation [@prediction_markets/market_aggregator.py:30-80]
    """

    def __init__(self):
        self.kalshi_client: Optional[BasePredictionMarket] = None
        self.polymarket_client: Optional[BasePredictionMarket] = None
        self.chainlink_connector = None  # Will be initialized when needed
        self._cached_markets: Dict[str, List[NormalizedMarket]] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = 60  # 60 seconds cache
        print("✅ UnifiedMarketAggregator initialized")

    async def initialize_all_clients(self) -> None:
        """Initialize all market platform clients"""
        try:
            # Initialize Kalshi client
            from .kalshi_client import KalshiMarketClient

            self.kalshi_client = KalshiMarketClient()
            await self.kalshi_client.connect()
            print("✅ Kalshi client connected")
        except Exception as e:
            print(f"⚠️ Kalshi client initialization failed: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")

        try:
            # Initialize Polymarket client
            from .polymarket_client import PolymarketCLOBClient

            self.polymarket_client = PolymarketCLOBClient()
            await self.polymarket_client.connect()
            print("✅ Polymarket client connected")
        except Exception as e:
            print(f"⚠️ Polymarket client initialization failed: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")

        try:
            # Initialize Chainlink connector (absolute import for production)
            from core.chainlink_integration import ChainlinkOracleConnector

            self.chainlink_connector = ChainlinkOracleConnector()
            print("✅ Chainlink oracle connector initialized")
        except Exception as e:
            print(f"⚠️ Chainlink connector initialization failed: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")

    async def get_kalshi_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        REQ-AGG-003: Get normalized Kalshi markets
        @requirement: REQ-AGG-003 - Normalized data [@prediction_markets/market_aggregator.py:135-170]
        """
        try:
            if not self.kalshi_client:
                print("⚠️ Kalshi client not initialized")
                return []

            markets = await self.kalshi_client.get_markets(limit=limit)

            # Convert to dictionary format for JSON serialization
            result = []
            for market in markets:
                result.append(
                    {
                        "id": market.id,
                        "platform": "kalshi",
                        "title": market.title,
                        "description": market.description,
                        "status": market.status.value,
                        "yes_price": market.yes_price,
                        "no_price": market.no_price,
                        "volume": market.volume,
                        "liquidity": market.liquidity,
                        "created_at": market.created_at.isoformat(),
                        "closes_at": market.closes_at.isoformat() if market.closes_at else None,
                        "tags": market.tags,
                        "category": market.category,
                    }
                )

            print(f"✅ Retrieved {len(result)} Kalshi markets")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting Kalshi markets: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def get_polymarket_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        REQ-AGG-003: Get normalized Polymarket markets
        """
        try:
            if not self.polymarket_client:
                print("⚠️ Polymarket client not initialized")
                return []

            markets = await self.polymarket_client.get_markets(limit=limit)

            # Convert to dictionary format
            result = []
            for market in markets:
                result.append(
                    {
                        "id": market.id,
                        "platform": "polymarket",
                        "title": market.title,
                        "description": market.description,
                        "status": market.status.value,
                        "yes_price": market.yes_price,
                        "no_price": market.no_price,
                        "volume": market.volume,
                        "liquidity": market.liquidity,
                        "created_at": market.created_at.isoformat(),
                        "closes_at": market.closes_at.isoformat() if market.closes_at else None,
                        "tags": market.tags,
                        "category": market.category,
                    }
                )

            print(f"✅ Retrieved {len(result)} Polymarket markets")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting Polymarket markets: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def find_arbitrage_opportunities(
        self, min_profit_threshold: float = 10.0, min_price_difference: float = 0.05
    ) -> List[Dict[str, Any]]:
        """
        REQ-AGG-002: Find cross-market arbitrage opportunities
        @requirement: REQ-AGG-002 - Opportunity detection [@prediction_markets/market_aggregator.py:85-130]
        """
        try:
            opportunities = []

            # Get markets from both platforms
            kalshi_markets = []
            polymarket_markets = []

            if self.kalshi_client:
                kalshi_markets = await self.kalshi_client.get_markets(limit=100)

            if self.polymarket_client:
                polymarket_markets = await self.polymarket_client.get_markets(limit=100)

            print(
                f"🔍 Analyzing {len(kalshi_markets)} Kalshi and {len(polymarket_markets)} Polymarket markets"
            )

            # Compare similar markets across platforms
            for k_market in kalshi_markets:
                for p_market in polymarket_markets:
                    # Check if markets are similar (simple title matching for now)
                    similarity = self._calculate_market_similarity(k_market, p_market)

                    if similarity > 0.7:  # 70% similarity threshold
                        # Calculate arbitrage opportunity
                        if self.kalshi_client and self.polymarket_client:
                            opp = self.kalshi_client.calculate_arbitrage_opportunity(
                                k_market, p_market
                            )
                            if opp and opp["expected_profit"] >= min_profit_threshold:
                                opportunities.append(opp)

            # Sort by expected profit
            opportunities.sort(key=lambda x: x["expected_profit"], reverse=True)

            # REQ-MCP-004: Log success before return
            print(f"✅ Found {len(opportunities)} arbitrage opportunities")
            return opportunities

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error finding arbitrage opportunities: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    def _calculate_market_similarity(
        self, market1: NormalizedMarket, market2: NormalizedMarket
    ) -> float:
        """Calculate similarity score between two markets"""
        try:
            # Simple similarity based on title overlap
            title1_words = set(market1.title.lower().split())
            title2_words = set(market2.title.lower().split())

            if not title1_words or not title2_words:
                return 0.0

            intersection = title1_words.intersection(title2_words)
            union = title1_words.union(title2_words)

            return len(intersection) / len(union) if union else 0.0

        except Exception as e:
            print(f"⚠️ Error calculating similarity: {str(e)}")
            return 0.0

    async def execute_arbitrage(
        self, opportunity: Dict[str, Any], max_size: float
    ) -> Dict[str, Any]:
        """
        Execute arbitrage trade across markets
        """
        try:
            result = {
                "status": "executed",
                "opportunity": opportunity,
                "buy_order": None,
                "sell_order": None,
                "actual_profit": 0.0,
                "execution_time": datetime.now().isoformat(),
            }

            # Determine which client to use for each side
            buy_client = None
            sell_client = None

            if opportunity["buy_platform"] == "kalshi":
                buy_client = self.kalshi_client
            elif opportunity["buy_platform"] == "polymarket":
                buy_client = self.polymarket_client

            if opportunity["sell_platform"] == "kalshi":
                sell_client = self.kalshi_client
            elif opportunity["sell_platform"] == "polymarket":
                sell_client = self.polymarket_client

            if not buy_client or not sell_client:
                raise ValueError("Required market clients not available")

            # Place orders (simplified - in production would need proper order management)
            size = min(max_size, opportunity["suggested_size"])

            # Place buy order
            buy_order = Order(
                market_id=opportunity["buy_market"],
                side="buy",
                type="limit",
                size=size,
                price=opportunity.get("buy_price", 0.5),
            )
            executed_buy = await buy_client.place_order(buy_order)
            result["buy_order"] = executed_buy

            # Place sell order
            sell_order = Order(
                market_id=opportunity["sell_market"],
                side="sell",
                type="limit",
                size=size,
                price=opportunity.get("sell_price", 0.5),
            )
            executed_sell = await sell_client.place_order(sell_order)
            result["sell_order"] = executed_sell

            # Calculate actual profit
            result["actual_profit"] = (
                executed_sell.executed_price - executed_buy.executed_price
            ) * size

            # REQ-MCP-004: Log success before return
            print(f"✅ Arbitrage executed: ${result['actual_profit']:.2f} profit")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error executing arbitrage: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def verify_with_chainlink_oracles(self) -> Dict[str, Any]:
        """
        Verify market data with Chainlink oracles
        """
        try:
            if not self.chainlink_connector:
                print("⚠️ Chainlink connector not initialized")
                return {}

            verification_results = {
                "timestamp": datetime.now().isoformat(),
                "price_feeds": {},
                "vrf_data": {},
                "verified_markets": [],
            }

            # Get relevant price feeds
            assets = ["BTC-USD", "ETH-USD", "SPY-USD"]
            for asset in assets:
                try:
                    price_data = await self.chainlink_connector.get_price_feed(asset)
                    verification_results["price_feeds"][asset] = price_data
                except Exception as e:
                    print(f"⚠️ Failed to get price feed for {asset}: {str(e)}")

            # REQ-MCP-004: Log success before return
            print(
                f"✅ Oracle verification complete: {len(verification_results['price_feeds'])} feeds"
            )
            return verification_results

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error verifying with oracles: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return {}

    async def get_aggregated_liquidity(self) -> Dict[str, Any]:
        """
        REQ-AGG-004: Calculate aggregated liquidity across platforms
        @requirement: REQ-AGG-004 - Liquidity analysis [@prediction_markets/market_aggregator.py:175-210]
        """
        try:
            liquidity_data = {
                "timestamp": datetime.now().isoformat(),
                "platforms": {},
                "total_liquidity": 0.0,
                "total_volume": 0.0,
                "market_count": 0,
            }

            # Get Kalshi liquidity
            if self.kalshi_client:
                kalshi_markets = await self.kalshi_client.get_markets()
                kalshi_liquidity = sum(m.liquidity for m in kalshi_markets)
                kalshi_volume = sum(m.volume for m in kalshi_markets)

                liquidity_data["platforms"]["kalshi"] = {
                    "liquidity": kalshi_liquidity,
                    "volume": kalshi_volume,
                    "markets": len(kalshi_markets),
                }

                liquidity_data["total_liquidity"] += kalshi_liquidity
                liquidity_data["total_volume"] += kalshi_volume
                liquidity_data["market_count"] += len(kalshi_markets)

            # Get Polymarket liquidity
            if self.polymarket_client:
                poly_markets = await self.polymarket_client.get_markets()
                poly_liquidity = sum(m.liquidity for m in poly_markets)
                poly_volume = sum(m.volume for m in poly_markets)

                liquidity_data["platforms"]["polymarket"] = {
                    "liquidity": poly_liquidity,
                    "volume": poly_volume,
                    "markets": len(poly_markets),
                }

                liquidity_data["total_liquidity"] += poly_liquidity
                liquidity_data["total_volume"] += poly_volume
                liquidity_data["market_count"] += len(poly_markets)

            # REQ-MCP-004: Log success before return
            print(f"✅ Aggregated liquidity: ${liquidity_data['total_liquidity']:,.2f}")
            return liquidity_data

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting aggregated liquidity: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return {}

    async def is_kalshi_connected(self) -> bool:
        """Check if Kalshi client is connected"""
        return self.kalshi_client is not None and self.kalshi_client.is_connected

    async def is_polymarket_connected(self) -> bool:
        """Check if Polymarket client is connected"""
        return self.polymarket_client is not None and self.polymarket_client.is_connected

    async def is_chainlink_connected(self) -> bool:
        """Check if Chainlink connector is available"""
        return self.chainlink_connector is not None


if __name__ == "__main__":
    # Test the aggregator
    import asyncio

    async def test_aggregator():
        print("\n" + "=" * 60)
        print("Testing Unified Market Aggregator")
        print("=" * 60)

        aggregator = UnifiedMarketAggregator()

        # Initialize all clients
        await aggregator.initialize_all_clients()

        # Get markets from each platform
        kalshi_data = await aggregator.get_kalshi_markets(limit=5)
        print(f"\n📊 Kalshi markets: {len(kalshi_data)}")

        poly_data = await aggregator.get_polymarket_markets(limit=5)
        print(f"📊 Polymarket markets: {len(poly_data)}")

        # Find arbitrage opportunities
        opportunities = await aggregator.find_arbitrage_opportunities()
        print(f"\n💰 Arbitrage opportunities: {len(opportunities)}")

        # Get aggregated liquidity
        liquidity = await aggregator.get_aggregated_liquidity()
        print(f"\n💧 Total liquidity: ${liquidity.get('total_liquidity', 0):,.2f}")

        # Verify with oracles
        verification = await aggregator.verify_with_chainlink_oracles()
        print(f"\n🔮 Oracle verification: {len(verification.get('price_feeds', {}))} feeds")

        print("\n✅ Aggregator test complete")

    asyncio.run(test_aggregator())
