#!/usr/bin/env python3
"""
Base Prediction Market Interface
@requirement: REQ-MARKET-001 - Abstract market interface for multi-platform
@requirement: REQ-MARKET-002 - Market data normalization
@requirement: REQ-MARKET-003 - Order placement abstraction
@requirement: REQ-MARKET-004 - Position management
@requirement: REQ-MARKET-005 - Event streaming support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, AsyncIterator
from enum import Enum
import traceback


class MarketStatus(Enum):
    """Market status enumeration"""

    ACTIVE = "active"
    CLOSED = "closed"
    SETTLED = "settled"
    SUSPENDED = "suspended"


class OrderSide(Enum):
    """Order side for trading"""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration"""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class NormalizedMarket:
    """
    REQ-MARKET-002: Normalized market data structure
    @requirement: REQ-MARKET-002 - Market data normalization [@prediction_markets/base_market.py:85-120]
    """

    # Common fields across all platforms
    id: str
    platform: str
    title: str
    description: str
    status: MarketStatus

    # Trading data
    yes_price: float  # Probability of YES outcome (0.0 to 1.0)
    no_price: float  # Probability of NO outcome (0.0 to 1.0)
    volume: float  # Total volume in USD
    liquidity: float  # Available liquidity in USD

    # Timing
    created_at: datetime
    closes_at: Optional[datetime]
    settled_at: Optional[datetime]

    # Resolution
    resolution: Optional[str] = None  # YES, NO, or None
    resolution_source: Optional[str] = None

    # Platform-specific data
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None

    def get_implied_probability(self) -> float:
        """Get the implied probability from YES price"""
        return self.yes_price

    def get_spread(self) -> float:
        """Get the bid-ask spread"""
        return abs((self.yes_price + self.no_price) - 1.0)


@dataclass
class MarketHistoryPoint:
    """Represents one point in a market's history"""

    timestamp: datetime
    price: float
    volume: float


@dataclass
class Order:
    """
    REQ-MARKET-003: Order structure for trading
    """

    market_id: str
    side: OrderSide
    type: OrderType
    size: float  # Number of shares/contracts
    price: Optional[float] = None  # For limit orders

    # Execution details
    executed_size: float = 0.0
    executed_price: float = 0.0
    status: str = "pending"

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    platform_order_id: Optional[str] = None


@dataclass
class Position:
    """
    REQ-MARKET-004: Position tracking structure
    """

    market_id: str
    platform: str
    side: str  # YES or NO
    size: float  # Number of contracts
    avg_price: float  # Average entry price
    current_price: float

    # P&L calculation
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    # Metadata
    opened_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    def calculate_pnl(self, current_price: float) -> float:
        """Calculate current P&L"""
        self.current_price = current_price
        self.unrealized_pnl = (current_price - self.avg_price) * self.size
        return self.unrealized_pnl


class BasePredictionMarket(ABC):
    """
    REQ-MARKET-001: Abstract base class for prediction market platforms
    @requirement: REQ-MARKET-001 - Base interface [@prediction_markets/base_market.py:20-80]
    """

    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self.is_connected = False
        print(f"✅ {platform_name} market interface initialized")

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the platform"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the platform"""
        pass

    @abstractmethod
    async def get_markets(
        self, limit: int = 100, status: Optional[MarketStatus] = None
    ) -> List[NormalizedMarket]:
        """
        REQ-MARKET-002: Get normalized market data
        @requirement: REQ-MARKET-002 - Data normalization
        """
        pass

    @abstractmethod
    async def get_market_details(self, market_id: str) -> NormalizedMarket:
        """Get detailed information for a specific market"""
        pass

    @abstractmethod
    async def get_market_history(
        self, market_id: str, resolution: Optional[str] = "1D"
    ) -> List[MarketHistoryPoint]:
        """Get historical data for a market"""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """
        REQ-MARKET-003: Place an order
        @requirement: REQ-MARKET-003 - Order placement [@prediction_markets/base_market.py:125-160]
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """
        REQ-MARKET-004: Get current positions
        @requirement: REQ-MARKET-004 - Position management [@prediction_markets/base_market.py:165-200]
        """
        pass

    @abstractmethod
    async def get_position(self, market_id: str) -> Optional[Position]:
        """Get position for a specific market"""
        pass

    async def stream_market_updates(self, market_id: str) -> AsyncIterator[Dict[str, Any]]:
        """
        REQ-MARKET-005: Stream real-time market updates
        @requirement: REQ-MARKET-005 - Event streaming [@prediction_markets/base_market.py:205-240]
        """
        # Default implementation - platforms can override
        print(f"⚠️ {self.platform_name} doesn't support streaming")
        yield {}

    def normalize_market_data(self, raw_data: Dict[str, Any]) -> NormalizedMarket:
        """
        Convert platform-specific data to normalized format
        Platform implementations must override this
        """
        raise NotImplementedError(f"{self.platform_name} must implement normalize_market_data")

    async def get_order_book(self, market_id: str) -> Dict[str, Any]:
        """Get order book data for a market (if supported)"""
        return {"bids": [], "asks": [], "timestamp": datetime.now().isoformat()}

    async def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for a market"""
        return []

    def calculate_arbitrage_opportunity(
        self, market1: NormalizedMarket, market2: NormalizedMarket
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate potential arbitrage between two markets
        Returns opportunity details if profitable
        """
        try:
            # Check if markets are comparable
            if market1.status != MarketStatus.ACTIVE or market2.status != MarketStatus.ACTIVE:
                return None

            # Calculate price differences
            yes_diff = abs(market1.yes_price - market2.yes_price)
            no_diff = abs(market1.no_price - market2.no_price)

            # Need significant difference for profitable arbitrage
            min_diff_threshold = 0.05  # 5% minimum difference

            if yes_diff > min_diff_threshold or no_diff > min_diff_threshold:
                # Determine which market to buy/sell
                if market1.yes_price < market2.yes_price:
                    buy_market = market1
                    sell_market = market2
                    side = "YES"
                    price_diff = yes_diff
                elif market1.no_price < market2.no_price:
                    buy_market = market1
                    sell_market = market2
                    side = "NO"
                    price_diff = no_diff
                else:
                    return None

                # Calculate potential profit (simplified)
                size = (
                    min(buy_market.liquidity, sell_market.liquidity) * 0.1
                )  # Use 10% of liquidity
                gross_profit = size * price_diff

                # Estimate fees (platform specific)
                estimated_fees = size * 0.02  # 2% total fees estimate
                net_profit = gross_profit - estimated_fees

                if net_profit > 10:  # Minimum $10 profit
                    return {
                        "buy_market": buy_market.id,
                        "buy_platform": buy_market.platform,
                        "sell_market": sell_market.id,
                        "sell_platform": sell_market.platform,
                        "side": side,
                        "price_difference": price_diff,
                        "suggested_size": size,
                        "expected_profit": net_profit,
                        "description": f"Buy {side} on {buy_market.platform} at {buy_market.yes_price if side == 'YES' else buy_market.no_price:.3f}, "
                        f"sell on {sell_market.platform} at {sell_market.yes_price if side == 'YES' else sell_market.no_price:.3f}",
                    }

            return None

        except Exception as e:
            print(f"❌ Error calculating arbitrage: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
            return None

    async def health_check(self) -> Dict[str, Any]:
        """Check platform health and connectivity"""
        try:
            # Try to get a few markets
            markets = await self.get_markets(limit=5)

            return {
                "platform": self.platform_name,
                "status": "healthy" if len(markets) > 0 else "degraded",
                "connected": self.is_connected,
                "markets_available": len(markets),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "platform": self.platform_name,
                "status": "error",
                "connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }


class MockPredictionMarket(BasePredictionMarket):
    """
    Mock implementation for testing
    """

    def __init__(self):
        super().__init__("Mock")
        self.mock_markets = []
        self._create_mock_data()

    def _create_mock_data(self):
        """Create mock market data"""
        self.mock_markets = [
            NormalizedMarket(
                id="mock-1",
                platform="Mock",
                title="Will BTC reach $100k by end of 2025?",
                description="Resolution based on CoinGecko price",
                status=MarketStatus.ACTIVE,
                yes_price=0.65,
                no_price=0.35,
                volume=50000,
                liquidity=10000,
                created_at=datetime.now(),
                closes_at=datetime(2025, 12, 31),
                tags=["crypto", "bitcoin"],
                category="Cryptocurrency",
            ),
            NormalizedMarket(
                id="mock-2",
                platform="Mock",
                title="Will ETH merge successfully?",
                description="Already settled market",
                status=MarketStatus.SETTLED,
                yes_price=0.99,
                no_price=0.01,
                volume=100000,
                liquidity=0,
                created_at=datetime(2022, 1, 1),
                closes_at=datetime(2022, 9, 15),
                settled_at=datetime(2022, 9, 15),
                resolution="YES",
                tags=["crypto", "ethereum"],
                category="Cryptocurrency",
            ),
        ]

    async def connect(self) -> bool:
        self.is_connected = True
        return True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def get_markets(
        self, limit: int = 100, status: Optional[MarketStatus] = None
    ) -> List[NormalizedMarket]:
        markets = self.mock_markets
        if status:
            markets = [m for m in markets if m.status == status]
        return markets[:limit]

    async def get_market_details(self, market_id: str) -> NormalizedMarket:
        for market in self.mock_markets:
            if market.id == market_id:
                return market
        raise ValueError(f"Market {market_id} not found")

    async def place_order(self, order: Order) -> Order:
        order.status = "executed"
        order.executed_size = order.size
        order.executed_price = order.price or 0.5
        order.executed_at = datetime.now()
        order.platform_order_id = f"mock-order-{datetime.now().timestamp()}"
        return order

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_positions(self) -> List[Position]:
        return []

    async def get_position(self, market_id: str) -> Optional[Position]:
        return None


if __name__ == "__main__":
    # Test the base market interface
    import asyncio

    async def test_mock_market():
        print("\n" + "=" * 60)
        print("Testing Base Market Interface")
        print("=" * 60)

        market = MockPredictionMarket()

        # Connect
        await market.connect()
        print(f"Connected: {market.is_connected}")

        # Get markets
        markets = await market.get_markets(limit=10)
        print(f"\n📊 Found {len(markets)} markets:")
        for m in markets:
            print(f"  • {m.title}")
            print(f"    YES: {m.yes_price:.2%}, Volume: ${m.volume:,.0f}")

        # Test order placement
        order = Order(
            market_id="mock-1", side=OrderSide.BUY, type=OrderType.LIMIT, size=100, price=0.65
        )

        executed = await market.place_order(order)
        print(f"\n📈 Order executed: {executed.platform_order_id}")

        # Health check
        health = await market.health_check()
        print(f"\n🏥 Health: {health}")

        print("\n✅ Test complete")

    asyncio.run(test_mock_market())
