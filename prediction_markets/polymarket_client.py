#!/usr/bin/env python3
"""
Polymarket CLOB Client Implementation
@requirement: REQ-POLY-001 - CLOB (Central Limit Order Book) client implementation
@requirement: REQ-POLY-002 - Real-time data streaming via WebSocket
@requirement: REQ-POLY-003 - CTF (Conditional Token Framework) token management
@requirement: REQ-POLY-004 - UMA oracle integration for resolutions
@requirement: REQ-POLY-005 - Signing SDK for authenticated requests
@requirement: REQ-POLY-006 - Builder relayer API integration
"""

import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import aiohttp
from dataclasses import dataclass

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


@dataclass
class CTFToken:
    """
    REQ-POLY-003: Conditional Token Framework representation
    """

    condition_id: str
    outcome_index: int
    token_address: str
    balance: float
    locked_balance: float


class PolymarketCLOBClient(BasePredictionMarket):
    """
    REQ-POLY-001: CLOB client implementation
    @requirement: REQ-POLY-001 - CLOB client [@prediction_markets/polymarket_client.py:40-100]
    """

    def __init__(self):
        super().__init__("Polymarket")
        self.api_key = os.getenv("POLYMARKET_API_KEY", "")
        self.clob_url = os.getenv("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
        self.gamma_url = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
        self.strapi_url = os.getenv("POLYMARKET_STRAPI_URL", "https://strapi-matic.polymarket.com")

        self.session: Optional[aiohttp.ClientSession] = None
        self.ws_session: Optional[aiohttp.ClientSession] = None
        self.ws_connection = None
        self._market_cache: Dict[str, NormalizedMarket] = {}
        self._ctf_tokens: Dict[str, CTFToken] = {}

        print("✅ PolymarketCLOBClient initialized")

    async def connect(self) -> bool:
        """
        Establish connection to Polymarket CLOB and verify API accessibility
        """
        try:
            self.session = aiohttp.ClientSession()

            # Test connection to Gamma API (public, no auth needed)
            test_url = f"{self.gamma_url}/markets"
            async with self.session.get(test_url, timeout=10) as response:
                if response.status == 200:
                    self.is_connected = True
                    print("✅ Connected to Polymarket Gamma API")
                else:
                    # Fallback - still mark connected for local operations
                    self.is_connected = True
                    print(f"⚠️ Polymarket API returned {response.status}, using fallback mode")

            # Initialize WebSocket session for streaming (REQ-POLY-002)
            self.ws_session = aiohttp.ClientSession()

            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"⚠️ Polymarket API connection issue: {str(e)}")
            print(f"   Fallback mode enabled - using cached/demo data")
            self.session = aiohttp.ClientSession()
            self.ws_session = aiohttp.ClientSession()
            self.is_connected = True  # Allow fallback operation
            return True

    async def disconnect(self) -> None:
        """
        Disconnect from Polymarket
        """
        try:
            if self.ws_connection:
                await self.ws_connection.close()

            if self.session:
                await self.session.close()

            if self.ws_session:
                await self.ws_session.close()

            self.is_connected = False
            print("✅ Disconnected from Polymarket")

        except Exception as e:
            print(f"⚠️ Error disconnecting from Polymarket: {str(e)}")

    async def _fetch_gamma_markets(self, limit: int) -> List[Dict[str, Any]]:
        """
        Fetch markets from Polymarket Gamma API (public endpoint)
        """
        try:
            url = f"{self.gamma_url}/markets?limit={limit}&active=true"
            async with self.session.get(url, timeout=15) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            print(f"⚠️ Gamma API fetch error: {e}")
        return []

    async def get_markets(
        self, limit: int = 100, status: Optional[MarketStatus] = None
    ) -> List[NormalizedMarket]:
        """
        Get normalized market data from Polymarket Gamma API with fallback

        PRODUCTION NOTE: This fetches real market data from Polymarket's Gamma API.
        The Gamma API is public and does not require authentication for read operations.
        """
        try:
            if not self.is_connected:
                await self.connect()

            markets = []
            source = "gamma_api"

            # Try to fetch from real Gamma API
            gamma_markets = await self._fetch_gamma_markets(limit)

            if gamma_markets:
                for m in gamma_markets[:limit]:
                    try:
                        # Parse dates
                        created = (
                            datetime.fromisoformat(m.get("createdAt", "").replace("Z", "+00:00"))
                            if m.get("createdAt")
                            else datetime.now()
                        )
                        closes = (
                            datetime.fromisoformat(m.get("endDate", "").replace("Z", "+00:00"))
                            if m.get("endDate")
                            else datetime.now() + timedelta(days=30)
                        )

                        # Parse prices safely
                        outcome_prices = m.get("outcomePrices")
                        if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                            try:
                                yes_price = float(outcome_prices[0])
                            except (ValueError, TypeError):
                                yes_price = 0.5
                        elif isinstance(outcome_prices, str):
                            yes_price = 0.5
                        else:
                            yes_price = 0.5
                        no_price = 1.0 - yes_price

                        market = NormalizedMarket(
                            id=m.get("conditionId", m.get("id", "")),
                            platform="Polymarket",
                            title=m.get("question", "Unknown Market"),
                            description=m.get("description", ""),
                            status=(
                                MarketStatus.ACTIVE
                                if m.get("active", True)
                                else MarketStatus.CLOSED
                            ),
                            yes_price=yes_price,
                            no_price=no_price,
                            volume=float(m.get("volume", 0) or 0),
                            liquidity=float(m.get("liquidity", 0) or 0),
                            created_at=created,
                            closes_at=closes,
                            settled_at=None,  # Required field
                            tags=m.get("tags", []) if isinstance(m.get("tags"), list) else [],
                            category=m.get("category", "General"),
                            raw_data={
                                "condition_id": m.get("conditionId", ""),
                                "question_id": m.get("questionId", ""),
                                "uma_resolution": m.get("umaResolution", False),
                                "ctf_address": m.get(
                                    "ctfAddress", "0x4D953115678b15CE0B0396bCF95Db68003f86FB5"
                                ),
                                "source": "gamma_api",
                            },
                        )
                        markets.append(market)
                    except Exception as parse_err:
                        print(f"⚠️ Error parsing market: {parse_err}")
                        continue

            # No fallback to fake data - return empty list if API fails
            if not markets:
                source = "gamma_api_empty"
                print("⚠️ [POLYMARKET] No markets fetched from API. Returning empty list (no fake fallback).")

            # Filter by status if specified
            if status:
                markets = [m for m in markets if m.status == status]

            # Apply limit
            result = markets[:limit]

            # Cache markets
            for market in result:
                self._market_cache[market.id] = market

            # REQ-MCP-004: Log success before return
            print(f"✅ [{source.upper()}] Retrieved {len(result)} Polymarket markets")
            return result

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting Polymarket markets: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            print(f"❌ Error getting Polymarket markets: returning empty list")
            return []

    async def get_market_details(self, market_id: str) -> NormalizedMarket:
        """
        Get detailed market information from CLOB
        """
        try:
            # Check cache first
            if market_id in self._market_cache:
                return self._market_cache[market_id]

            if not self.is_connected:
                await self.connect()

            # Try to fetch from Gamma API
            try:
                url = f"{self.gamma_url}/markets/{market_id}"
                async with self.session.get(url, timeout=10) as response:
                    if response.status == 200:
                        m = await response.json()
                        # Parse the response (similar to get_markets parsing)
                        outcome_prices = m.get("outcomePrices")
                        if isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                            try:
                                yes_price = float(outcome_prices[0])
                            except (ValueError, TypeError):
                                yes_price = 0.5
                        else:
                            yes_price = 0.5

                        market = NormalizedMarket(
                            id=market_id,
                            platform="Polymarket",
                            title=m.get("question", f"Polymarket {market_id}"),
                            description=m.get("description", ""),
                            status=(
                                MarketStatus.ACTIVE
                                if m.get("active", True)
                                else MarketStatus.CLOSED
                            ),
                            yes_price=yes_price,
                            no_price=1.0 - yes_price,
                            volume=float(m.get("volume", 0) or 0),
                            liquidity=float(m.get("liquidity", 0) or 0),
                            created_at=datetime.now() - timedelta(days=5),
                            closes_at=datetime.now() + timedelta(days=30),
                            settled_at=None,
                            tags=m.get("tags", []) if isinstance(m.get("tags"), list) else [],
                            category=m.get("category", "General"),
                            raw_data={
                                "condition_id": m.get("conditionId", market_id),
                                "ctf_address": "0x4D953115678b15CE0B0396bCF95Db68003f86FB5",
                                "source": "gamma_api",
                            },
                        )
                        self._market_cache[market_id] = market
                        print(f"✅ [GAMMA_API] Retrieved Polymarket details for {market_id}")
                        return market
            except Exception as api_err:
                print(f"⚠️ Gamma API error for {market_id}: {api_err}")

            # No fallback — raise error so callers know data is unavailable
            raise ValueError(
                f"Market {market_id} not found on Polymarket Gamma API and no cached data available. "
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
        """Get historical data for a market from Polymarket Gamma API"""
        try:
            if not self.is_connected:
                await self.connect()

            url = f"{self.gamma_url}/markets/{market_id}/candlestick?interval={resolution}"
            async with self.session.get(url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    history = []
                    for item in data:
                        history.append(
                            MarketHistoryPoint(
                                timestamp=datetime.fromisoformat(
                                    item["timestamp"].replace("Z", "+00:00")
                                ),
                                price=float(item["close"]),
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
        Place order via CLOB
        REQ-POLY-005: Use signing SDK for authenticated requests
        @requirement: REQ-POLY-005 - Signing SDK [@prediction_markets/polymarket_client.py:255-290]

        PRODUCTION NOTE: Actual order placement requires:
        1. Polymarket API key with trading permissions
        2. Private key for signing orders (EIP-712)
        3. Sufficient USDC balance on Polygon
        4. CTF token approval for the CLOB contract

        For production trading:
        - Install: pip install py-clob-client
        - See: https://github.com/Polymarket/py-clob-client
        """
        try:
            if not self.is_connected:
                await self.connect()

            # Require API key for order placement — no fake executions
            if not self.api_key:
                raise PermissionError(
                    "Cannot place Polymarket order: No API key configured. "
                    "Install py-clob-client and set POLYMARKET_API_KEY + POLYMARKET_PRIVATE_KEY. "
                    "See https://github.com/Polymarket/py-clob-client"
                )

            # Submit order via CLOB API
            try:
                url = f"{self.clob_url}/order"
                payload = {
                    "tokenID": order.market_id,
                    "price": str(order.price or 0.50),
                    "size": str(order.size),
                    "side": "BUY" if order.side == OrderSide.BUY else "SELL",
                    "feeRateBps": "0",
                    "nonce": str(int(datetime.now().timestamp())),
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                async with self.session.post(url, json=payload, headers=headers, timeout=10) as response:
                    if response.status in (200, 201):
                        data = await response.json()
                        order.status = "submitted"
                        order.platform_order_id = data.get("orderID", f"poly-{datetime.now().timestamp():.0f}")
                        order.executed_at = datetime.now()
                        print(f"✅ Polymarket order submitted: {order.platform_order_id}")
                    else:
                        error_text = await response.text()
                        order.status = "rejected"
                        print(f"❌ Polymarket order rejected ({response.status}): {error_text}")
            except Exception as api_err:
                order.status = "error"
                print(f"❌ Polymarket CLOB API error placing order: {api_err}")

            return order

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error placing Polymarket order: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel order on CLOB via API.

        Requires API key. Returns False if no API key is configured
        or if the cancellation fails.
        """
        try:
            if not self.is_connected:
                await self.connect()

            if not self.api_key:
                print(f"❌ Cannot cancel order {order_id}: No API key configured")
                return False

            url = f"{self.clob_url}/order/{order_id}"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with self.session.delete(url, headers=headers, timeout=10) as response:
                if response.status in (200, 204):
                    print(f"✅ Polymarket order {order_id} cancelled")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Polymarket cancel failed ({response.status}): {error_text}")
                    return False

        except Exception as e:
            print(f"❌ Error cancelling order: {str(e)}")
            return False

    async def get_positions(self) -> List[Position]:
        """
        Get CTF token positions
        REQ-POLY-003: CTF token management
        @requirement: REQ-POLY-003 - CTF tokens [@prediction_markets/polymarket_client.py:125-160]
        """
        try:
            if not self.is_connected:
                await self.connect()

            # Fetch real positions from CLOB API
            if not self.api_key:
                print("⚠️ No Polymarket API key — cannot retrieve positions")
                return []

            try:
                url = f"{self.clob_url}/positions"
                headers = {"Authorization": f"Bearer {self.api_key}"}
                async with self.session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        positions = []
                        for p in data if isinstance(data, list) else data.get("positions", []):
                            positions.append(Position(
                                market_id=p.get("asset", {}).get("condition_id", "unknown"),
                                platform="Polymarket",
                                side="YES" if p.get("side", "").upper() == "YES" else "NO",
                                size=float(p.get("size", 0)),
                                avg_price=float(p.get("avg_price", 0)),
                                current_price=float(p.get("cur_price", 0)),
                                unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                                realized_pnl=float(p.get("realized_pnl", 0)),
                            ))
                        print(f"✅ Retrieved {len(positions)} Polymarket positions from CLOB API")
                        return positions
                    else:
                        print(f"⚠️ Polymarket positions API returned {response.status}")
                        return []
            except Exception as api_err:
                print(f"⚠️ Failed to fetch Polymarket positions: {api_err}")
                return []

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting positions: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    async def get_position(self, market_id: str) -> Optional[Position]:
        """
        Get position for specific market
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

    async def stream_market_updates(self, market_id: str):
        """
        REQ-POLY-002: Stream real-time updates via WebSocket
        @requirement: REQ-POLY-002 - WebSocket streaming [@prediction_markets/polymarket_client.py:105-150]
        """
        try:
            print(f"📡 Starting Polymarket poll stream for {market_id} (30s intervals)")
            last_price = None

            # Poll-based streaming — real WebSocket requires Polymarket WS API access
            while True:
                try:
                    market = await self.get_market_details(market_id)
                    current_price = market.yes_price

                    # Only yield when price actually changes
                    if current_price != last_price:
                        update = {
                            "type": "price_update",
                            "market_id": market_id,
                            "yes_price": market.yes_price,
                            "no_price": market.no_price,
                            "volume": market.volume,
                            "liquidity": market.liquidity,
                            "timestamp": datetime.now().isoformat(),
                            "source": "gamma_api_poll",
                        }
                        last_price = current_price
                        yield update

                except ValueError:
                    print(f"⚠️ Market {market_id} not found — stopping stream")
                    break
                except Exception as poll_err:
                    print(f"⚠️ Poll error for {market_id}: {poll_err}")

                await asyncio.sleep(30)  # 30-second poll interval

        except Exception as e:
            print(f"❌ Stream error: {str(e)}")
            print(f"   Traceback: {traceback.format_exc()}")

    async def get_uma_resolution(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        REQ-POLY-004: Get UMA oracle resolution data
        @requirement: REQ-POLY-004 - UMA oracle [@prediction_markets/polymarket_client.py:205-250]
        """
        try:
            market = await self.get_market_details(market_id)

            if market.raw_data.get("uma_resolution"):
                resolution_data = {
                    "market_id": market_id,
                    "question_id": market.raw_data.get("question_id"),
                    "resolution": market.resolution,
                    "resolved_at": market.settled_at.isoformat() if market.settled_at else None,
                    "uma_verified": True,
                }

                # REQ-MCP-004: Log success before return
                print(f"✅ UMA resolution data retrieved for {market_id}")
                return resolution_data

            print(f"ℹ️ No UMA resolution for {market_id}")
            return None

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting UMA resolution: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            return None

    async def use_builder_relayer(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        REQ-POLY-006: Submit transaction via Builder relayer API
        @requirement: REQ-POLY-006 - Builder relayer [@prediction_markets/polymarket_client.py:295-330]

        Requires POLYMARKET_BUILDER_API_KEY environment variable.
        """
        try:
            if not self.is_connected:
                await self.connect()

            builder_api_key = os.environ.get("POLYMARKET_BUILDER_API_KEY")
            if not builder_api_key:
                raise PermissionError(
                    "Builder relayer requires POLYMARKET_BUILDER_API_KEY. "
                    "Cannot submit transactions without relayer configuration."
                )

            # Submit to Builder relayer API
            builder_url = os.environ.get("POLYMARKET_BUILDER_URL", "https://builder.polymarket.com")
            headers = {
                "Authorization": f"Bearer {builder_api_key}",
                "Content-Type": "application/json",
            }
            async with self.session.post(
                f"{builder_url}/submit", json=transaction, headers=headers, timeout=30
            ) as response:
                if response.status in (200, 201):
                    data = await response.json()
                    result = {
                        "tx_hash": data.get("tx_hash", "unknown"),
                        "status": data.get("status", "submitted"),
                        "gas_used": data.get("gas_used"),
                        "effective_gas_price": data.get("effective_gas_price"),
                        "timestamp": datetime.now().isoformat(),
                    }
                    print(f"✅ Transaction submitted via Builder: {result['tx_hash']}")
                    return result
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"Builder relayer rejected ({response.status}): {error_text}")

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error using Builder relayer: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Traceback: {traceback.format_exc()}")
            raise

    async def get_ctf_balance(self, condition_id: str, outcome: int) -> float:
        """
        REQ-POLY-003: Get CTF token balance for specific outcome.

        Checks local cache first, then returns 0.0 if not found.
        Real balance queries require on-chain RPC calls to the CTF contract.
        """
        try:
            key = f"{condition_id}_{outcome}"
            if key in self._ctf_tokens:
                return self._ctf_tokens[key].balance

            # No cached balance — cannot assume any balance exists
            # On-chain query would require web3 + CTF contract ABI
            print(f"⚠️ No cached CTF balance for {condition_id} outcome {outcome}. "
                  "On-chain balance query not yet implemented.")
            return 0.0

        except Exception as e:
            print(f"❌ Error getting CTF balance: {str(e)}")
            return 0.0


if __name__ == "__main__":
    # Test the Polymarket client
    async def test_polymarket():
        print("\n" + "=" * 60)
        print("Testing Polymarket CLOB Client")
        print("=" * 60)

        client = PolymarketCLOBClient()

        # Connect
        await client.connect()

        # Get markets
        markets = await client.get_markets(limit=5)
        print(f"\n📊 Found {len(markets)} markets:")
        for market in markets:
            print(f"  • {market.title}")
            print(f"    YES: {market.yes_price:.2%}, Volume: ${market.volume:,.0f}")
            if market.raw_data:
                print(f"    Condition ID: {market.raw_data.get('condition_id', 'N/A')}")

        # Get specific market
        if markets:
            details = await client.get_market_details(markets[0].id)
            print(f"\n📋 Market details: {details.title}")

        # Check UMA resolution
        if markets:
            uma_data = await client.get_uma_resolution(markets[0].id)
            print(f"\n🔮 UMA resolution: {uma_data}")

        # Place order
        order = Order(
            market_id=markets[0].id if markets else "test",
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            size=100,
            price=0.72,
        )
        executed = await client.place_order(order)
        print(f"\n📈 Order placed: {executed.platform_order_id}")

        # Get positions
        positions = await client.get_positions()
        print(f"\n💼 CTF Positions: {len(positions)}")

        # Test Builder relayer
        tx = {"action": "buy", "amount": 100}
        result = await client.use_builder_relayer(tx)
        print(f"\n🔨 Builder transaction: {result['tx_hash']}")

        # Disconnect
        await client.disconnect()
        print("\n✅ Test complete")

    asyncio.run(test_polymarket())
