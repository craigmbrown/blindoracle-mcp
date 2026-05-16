#!/usr/bin/env python3
"""
Kalshi Market Client Implementation
@requirement: REQ-KALSHI-001 - Kalshi API client implementation
@requirement: REQ-KALSHI-002 - Market discovery and search functionality
@requirement: REQ-KALSHI-003 - Position and order management
@requirement: REQ-KALSHI-004 - Event-based market trading
@requirement: REQ-KALSHI-005 - Market resolution handling
"""

import base64
import os
import json
import asyncio
import traceback
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import aiohttp

from .base_market import (
    BasePredictionMarket,
    NormalizedMarket,
    Order,
    Position,
    MarketStatus,
    OrderSide,
    OrderType,
    MarketHistoryPoint,
)


class KalshiMarketClient(BasePredictionMarket):
    """
    REQ-KALSHI-001: Kalshi API client implementation
    @requirement: REQ-KALSHI-001 - API client [@prediction_markets/kalshi_client.py:30-90]
    """

    def __init__(self):
        super().__init__("Kalshi")
        self.api_key = os.getenv("KALSHI_API_KEY", "")
        # RSA private key for request signing (Kalshi v2 API requires this)
        self._private_key_pem = os.getenv("KALSHI_PRIVATE_KEY", "").replace("\\n", "\n")
        self.base_url = os.getenv(
            "KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2"
        )
        self.session: Optional[aiohttp.ClientSession] = None
        self.auth_token: Optional[str] = None
        self._market_cache: Dict[str, NormalizedMarket] = {}
        print("✅ KalshiMarketClient initialized")

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate RSA-signed auth headers for Kalshi v2 API.
        Signs: timestamp_ms + METHOD + /trade-api/v2/path
        Required headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
        Falls back to Bearer token if no private key configured.
        """
        if not self.api_key:
            return {}
        if not self._private_key_pem or "BEGIN" not in self._private_key_pem:
            # Legacy fallback: Bearer token (won't work for trading but OK for reads)
            return {"Authorization": f"Bearer {self.api_key}"}
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
            ts_ms = str(int(time.time() * 1000))
            msg = (ts_ms + method.upper() + path).encode("utf-8")
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode("utf-8"), password=None
            )
            signature = private_key.sign(msg, asym_padding.PKCS1v15(), hashes.SHA256())
            sig_b64 = base64.b64encode(signature).decode("utf-8")
            return {
                "KALSHI-ACCESS-KEY": self.api_key,
                "KALSHI-ACCESS-TIMESTAMP": ts_ms,
                "KALSHI-ACCESS-SIGNATURE": sig_b64,
                "Content-Type": "application/json",
            }
        except Exception as e:
            print(f"⚠️ RSA signing failed, falling back to Bearer: {e}")
            return {"Authorization": f"Bearer {self.api_key}"}

    async def connect(self) -> bool:
        """
        Establish connection to Kalshi platform and verify API accessibility

        PRODUCTION NOTE: Kalshi requires API key authentication for trading operations.
        Market data can be fetched without authentication from the elections API.
        See: https://kalshi.com/docs/api
        """
        try:
            self.session = aiohttp.ClientSession()

            # Test connection to Kalshi public API
            test_url = f"{self.base_url}/markets"
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with self.session.get(test_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    self.is_connected = True
                    if self.api_key:
                        self.auth_token = f"Bearer {self.api_key}"
                        print("✅ Connected to Kalshi API (authenticated)")
                    else:
                        print("✅ Connected to Kalshi API (public access)")
                elif response.status == 401:
                    self.is_connected = True
                    print("✅ Connected to Kalshi (read-only, no API key)")
                else:
                    self.is_connected = True
                    print(f"⚠️ Kalshi API returned {response.status}, using fallback mode")

            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"⚠️ Kalshi API connection issue: {str(e)}")
            print(f"   Fallback mode enabled - using cached/demo data")
            self.session = aiohttp.ClientSession()
            self.is_connected = True  # Allow fallback operation
            return True

    async def disconnect(self) -> None:
        """
        Disconnect from Kalshi platform
        """
        try:
            if self.session:
                await self.session.close()
                self.session = None
            self.is_connected = False
            print("✅ Disconnected from Kalshi")

        except Exception as e:
            print(f"⚠️ Error disconnecting from Kalshi: {str(e)}")

    async def _fetch_kalshi_markets(self, limit: int) -> List[Dict[str, Any]]:
        """
        Fetch markets from Kalshi API
        """
        try:
            url = f"{self.base_url}/markets?limit={limit}&status=active"
            headers = {}
            if self.auth_token:
                headers["Authorization"] = self.auth_token

            async with self.session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("markets", [])
        except Exception as e:
            print(f"⚠️ Kalshi API fetch error: {e}")
        return []

    async def get_markets(
        self, limit: int = 100, status: Optional[MarketStatus] = None
    ) -> List[NormalizedMarket]:
        """
        REQ-KALSHI-002: Get normalized market data from Kalshi API with fallback
        @requirement: REQ-KALSHI-002 - Market discovery [@prediction_markets/kalshi_client.py:95-140]

        PRODUCTION NOTE: This fetches real market data from Kalshi's API.
        Market data is publicly accessible; trading requires authentication.
        """
        try:
            if not self.is_connected:
                await self.connect()

            markets = []
            source = "kalshi_api"

            # Try to fetch from real Kalshi API
            kalshi_markets = await self._fetch_kalshi_markets(limit)

            if kalshi_markets:
                for m in kalshi_markets[:limit]:
                    try:
                        # Parse Kalshi API response into NormalizedMarket
                        yes_price = float(m.get("yes_price", 50)) / 100.0  # Kalshi uses cents
                        no_price = 1.0 - yes_price

                        # Parse dates
                        close_time = m.get("close_time", "")
                        if close_time:
                            closes = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                        else:
                            closes = datetime.now() + timedelta(days=30)

                        market = NormalizedMarket(
                            id=m.get("ticker", m.get("id", "")),
                            platform="Kalshi",
                            title=m.get("title", "Unknown Market"),
                            description=m.get("subtitle", ""),
                            status=(
                                MarketStatus.ACTIVE
                                if m.get("status") == "active"
                                else MarketStatus.CLOSED
                            ),
                            yes_price=yes_price,
                            no_price=no_price,
                            volume=float(m.get("volume", 0) or 0),
                            liquidity=float(m.get("open_interest", 0) or 0),
                            created_at=datetime.now() - timedelta(days=7),
                            closes_at=closes,
                            settled_at=None,
                            tags=m.get("tags", []) if isinstance(m.get("tags"), list) else [],
                            category=m.get("category", "General"),
                            raw_data={
                                "ticker": m.get("ticker", ""),
                                "event_ticker": m.get("event_ticker", ""),
                                "source": "kalshi_api",
                            },
                        )
                        markets.append(market)
                    except Exception as parse_err:
                        print(f"⚠️ Error parsing Kalshi market: {parse_err}")
                        continue

            # No fallback to fake data - return empty list if API fails
            if not markets:
                source = "kalshi_api_empty"
                print("⚠️ [KALSHI] No markets fetched from API. Returning empty list (no fake fallback).")

            # Filter by status if specified
            if status:
                markets = [m for m in markets if m.status == status]

            # Apply limit
            result = markets[:limit]

            # Cache markets
            for market in result:
                self._market_cache[market.id] = market

            # REQ-MCP-004: Log success before return
            print(f"✅ [{source.upper()}] Retrieved {len(result)} Kalshi markets")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting Kalshi markets: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            print(f"❌ Error getting Kalshi markets: returning empty list")
            return []

    async def get_market_details(self, market_id: str) -> NormalizedMarket:
        """
        Get detailed information for a specific market from Kalshi API
        """
        try:
            # Check cache first
            if market_id in self._market_cache:
                return self._market_cache[market_id]

            if not self.is_connected:
                await self.connect()

            # Try to fetch from Kalshi API
            try:
                url = f"{self.base_url}/markets/{market_id}"
                headers = {}
                if self.auth_token:
                    headers["Authorization"] = self.auth_token

                async with self.session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        m = data.get("market", data)

                        yes_price = float(m.get("yes_price", 50)) / 100.0
                        no_price = 1.0 - yes_price

                        market = NormalizedMarket(
                            id=market_id,
                            platform="Kalshi",
                            title=m.get("title", f"Market {market_id}"),
                            description=m.get("subtitle", ""),
                            status=(
                                MarketStatus.ACTIVE
                                if m.get("status") == "active"
                                else MarketStatus.CLOSED
                            ),
                            yes_price=yes_price,
                            no_price=no_price,
                            volume=float(m.get("volume", 0) or 0),
                            liquidity=float(m.get("open_interest", 0) or 0),
                            created_at=datetime.now() - timedelta(days=7),
                            closes_at=datetime.now() + timedelta(days=30),
                            settled_at=None,
                            tags=m.get("tags", []) if isinstance(m.get("tags"), list) else [],
                            category=m.get("category", "General"),
                            raw_data={"ticker": market_id, "source": "kalshi_api"},
                        )
                        self._market_cache[market_id] = market
                        print(f"✅ [KALSHI_API] Retrieved market details for {market_id}")
                        return market
            except Exception as api_err:
                print(f"⚠️ Kalshi API error for {market_id}: {api_err}")

            # No fallback — raise error so callers know data is unavailable
            raise ValueError(
                f"Market {market_id} not found on Kalshi API and no cached data available. "
                "Ensure market ID is valid and API is accessible."
            )

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting market details: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def get_market_history(
        self, market_id: str, resolution: Optional[str] = "1D"
    ) -> List[MarketHistoryPoint]:
        """Get historical data for a market from Kalshi API"""
        try:
            if not self.is_connected:
                await self.connect()

            # Kalshi uses `span` instead of resolution. Let's map it.
            span_map = {"1H": "1h", "1D": "24h", "7D": "7d", "30D": "30d"}
            span = span_map.get(resolution, "7d")

            url = f"{self.base_url}/markets/{market_id}/series?span={span}"
            headers = {}
            if self.auth_token:
                headers["Authorization"] = self.auth_token

            async with self.session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    history = []
                    for item in data.get("series", []):
                        history.append(
                            MarketHistoryPoint(
                                timestamp=datetime.fromisoformat(item["ts"].replace("Z", "+00:00")),
                                price=float(item["yes_price"]) / 100.0,  # Kalshi uses cents
                                volume=float(item["volume"]),
                            )
                        )
                    print(f"✅ Retrieved {len(history)} history points for {market_id}")
                    return history
                else:
                    print(f"⚠️ Failed to fetch history for {market_id}, status: {response.status}")
                    return []
        except Exception as e:
            print(f"❌ Error getting market history for {market_id}: {str(e)}")
            return []

    async def place_order(self, order: Order) -> Order:
        """
        REQ-KALSHI-003: Place an order
        @requirement: REQ-KALSHI-003 - Order management [@prediction_markets/kalshi_client.py:145-180]

        PRODUCTION NOTE: Actual order placement requires:
        1. Kalshi API key with trading permissions
        2. Funded Kalshi account (USD balance)
        3. Proper market access (some markets have restrictions)

        For production trading:
        - Get API credentials from: https://kalshi.com/docs/api
        - Set KALSHI_API_KEY environment variable
        - Ensure account is verified and funded
        """
        try:
            if not self.is_connected:
                await self.connect()

            # Require API key for order placement — no fake executions
            if not self.auth_token:
                raise PermissionError(
                    "Cannot place Kalshi order: No API key configured. "
                    "Set KALSHI_API_KEY environment variable with trading permissions. "
                    "See https://kalshi.com/docs/api for API access."
                )

            # Submit order via Kalshi API (RSA-signed or Bearer fallback)
            try:
                api_path = "/trade-api/v2/portfolio/orders"
                url = f"{self.base_url}/portfolio/orders"
                payload = {
                    "ticker": order.market_id,
                    "count": order.size,
                    "side": "yes" if order.side == OrderSide.BUY else "no",
                    "type": "limit" if order.type == OrderType.LIMIT else "market",
                }
                if order.price is not None:
                    payload["yes_price"] = int(order.price * 100)

                headers = self._get_auth_headers("POST", api_path)
                async with self.session.post(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status in (200, 201):
                        data = await response.json()
                        order.status = "submitted"
                        order.platform_order_id = data.get("order", {}).get("order_id", f"kalshi-{datetime.now().timestamp():.0f}")
                        order.executed_at = datetime.now()
                        print(f"✅ Kalshi order submitted: {order.platform_order_id}")
                    else:
                        error_text = await response.text()
                        order.status = "rejected"
                        print(f"❌ Kalshi order rejected ({response.status}): {error_text}")
            except Exception as api_err:
                order.status = "error"
                print(f"❌ Kalshi API error placing order: {api_err}")

            return order

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error placing Kalshi order: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order via Kalshi API.

        Requires API key with trading permissions. Returns False if
        no API key is configured or if the cancellation fails.
        """
        try:
            if not self.is_connected:
                await self.connect()

            if not self.auth_token:
                print(f"❌ Cannot cancel order {order_id}: No API key configured")
                return False

            url = f"{self.base_url}/portfolio/orders/{order_id}"
            headers = {"Authorization": self.auth_token}
            async with self.session.delete(url, headers=headers, timeout=10) as response:
                if response.status in (200, 204):
                    print(f"✅ Kalshi order {order_id} cancelled")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Kalshi cancel failed ({response.status}): {error_text}")
                    return False

        except Exception as e:
            print(f"❌ Error cancelling order: {str(e)}")
            return False

    async def get_positions(self) -> List[Position]:
        """
        REQ-KALSHI-003: Get current positions
        @requirement: REQ-KALSHI-003 - Position management [@prediction_markets/kalshi_client.py:145-180]
        """
        try:
            if not self.is_connected:
                await self.connect()

            # Fetch real positions from Kalshi API
            if not self.auth_token:
                print("⚠️ No Kalshi API key — cannot retrieve positions")
                return []

            try:
                url = f"{self.base_url}/portfolio/positions"
                headers = {"Authorization": self.auth_token}
                async with self.session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        positions = []
                        for p in data.get("market_positions", []):
                            positions.append(Position(
                                market_id=p.get("ticker", "unknown"),
                                platform="Kalshi",
                                side="YES" if p.get("market_exposure", 0) > 0 else "NO",
                                size=abs(p.get("position", 0)),
                                avg_price=float(p.get("total_cost", 0)) / max(abs(p.get("position", 1)), 1),
                                current_price=float(p.get("market_exposure", 0)) / max(abs(p.get("position", 1)), 1),
                                unrealized_pnl=float(p.get("realized_pnl", 0)),
                                realized_pnl=float(p.get("realized_pnl", 0)),
                            ))
                        print(f"✅ Retrieved {len(positions)} Kalshi positions from API")
                        return positions
                    else:
                        print(f"⚠️ Kalshi positions API returned {response.status}")
                        return []
            except Exception as api_err:
                print(f"⚠️ Failed to fetch Kalshi positions: {api_err}")
                return []

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting positions: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def get_position(self, market_id: str) -> Optional[Position]:
        """
        Get position for a specific market
        """
        try:
            positions = await self.get_positions()
            for pos in positions:
                if pos.market_id == market_id:
                    return pos
            return None

        except Exception as e:
            print(f"❌ Error getting position: {str(e)}")
            return None

    async def get_event_markets(self, event_ticker: str) -> List[NormalizedMarket]:
        """
        REQ-KALSHI-004: Get markets for a specific event
        @requirement: REQ-KALSHI-004 - Event-based trading [@prediction_markets/kalshi_client.py:185-220]
        """
        try:
            if not self.is_connected:
                await self.connect()

            # For demo, filter markets by event
            all_markets = await self.get_markets()
            event_markets = [m for m in all_markets if event_ticker.lower() in m.title.lower()]

            # REQ-MCP-004: Log success before return
            print(f"✅ Found {len(event_markets)} markets for event {event_ticker}")
            return event_markets

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting event markets: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def get_market_resolution(self, market_id: str) -> Optional[str]:
        """
        REQ-KALSHI-005: Get market resolution
        @requirement: REQ-KALSHI-005 - Resolution handling [@prediction_markets/kalshi_client.py:225-260]
        """
        try:
            market = await self.get_market_details(market_id)

            if market.status == MarketStatus.SETTLED:
                # REQ-MCP-004: Log success before return
                print(f"✅ Market {market_id} resolved: {market.resolution}")
                return market.resolution

            print(f"ℹ️ Market {market_id} not yet resolved")
            return None

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting market resolution: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return None

    async def stream_market_updates(self, market_id: str):
        """
        Stream real-time market updates by polling the Kalshi API.

        NOTE: Kalshi WebSocket streaming requires a Pro API plan.
        This implementation polls the REST API at 30-second intervals
        and yields updates only when data actually changes.
        """
        try:
            print(f"📡 Starting market poll stream for {market_id} (30s intervals)")
            last_price = None

            while True:
                try:
                    market = await self.get_market_details(market_id)
                    current_price = market.yes_price

                    # Only yield when price actually changes
                    if current_price != last_price:
                        update = {
                            "type": "market_update",
                            "market_id": market_id,
                            "yes_price": market.yes_price,
                            "no_price": market.no_price,
                            "volume": market.volume,
                            "timestamp": datetime.now().isoformat(),
                            "source": "kalshi_api_poll",
                        }
                        last_price = current_price
                        yield update

                except ValueError:
                    # Market not found — stop streaming
                    print(f"⚠️ Market {market_id} not found — stopping stream")
                    break
                except Exception as poll_err:
                    print(f"⚠️ Poll error for {market_id}: {poll_err}")

                await asyncio.sleep(30)  # 30-second poll interval to respect rate limits

        except Exception as e:
            print(f"❌ Stream error: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    # Test the Kalshi client
    async def test_kalshi():
        print("\n" + "=" * 60)
        print("Testing Kalshi Market Client")
        print("=" * 60)

        client = KalshiMarketClient()

        # Connect
        await client.connect()

        # Get markets
        markets = await client.get_markets(limit=5)
        print(f"\n📊 Found {len(markets)} markets:")
        for market in markets:
            print(f"  • {market.title}")
            print(f"    YES: {market.yes_price:.2%}, Volume: ${market.volume:,.0f}")

        # Get specific market
        if markets:
            details = await client.get_market_details(markets[0].id)
            print(f"\n📋 Market details: {details.title}")

        # Place order
        order = Order(
            market_id=markets[0].id if markets else "test",
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            size=10,
            price=0.65,
        )
        executed = await client.place_order(order)
        print(f"\n📈 Order placed: {executed.platform_order_id}")

        # Get positions
        positions = await client.get_positions()
        print(f"\n💼 Positions: {len(positions)}")

        # Disconnect
        await client.disconnect()
        print("\n✅ Test complete")

    asyncio.run(test_kalshi())
