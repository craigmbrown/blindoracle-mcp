#!/usr/bin/env python3
"""
NOSTR Integration for Chainlink Prediction Markets
@requirement: REQ-NOSTR-001 through REQ-NOSTR-012 - NOSTR protocol integration
@requirement: REQ-CRYPTO-001 through REQ-CRYPTO-005 - Crypto analysis posting

This module integrates NOSTR protocol for decentralized social publishing of:
1. Prediction market analysis
2. Chainlink oracle data
3. Arbitrage opportunities
4. Performance metrics
5. Research insights
"""

import json
import asyncio
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import websockets
import coincurve
import requests


@dataclass
class NostrEvent:
    """NOSTR event structure following NIP-01"""

    id: str = ""
    pubkey: str = ""
    created_at: int = 0
    kind: int = 1
    tags: List[List[str]] = None
    content: str = ""
    sig: str = ""

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at == 0:
            self.created_at = int(datetime.now(timezone.utc).timestamp())


@dataclass
class PredictionMarketPost:
    """Structured prediction market analysis for NOSTR"""

    title: str
    market_data: Dict[str, Any]
    chainlink_data: Dict[str, Any]
    arbitrage_opportunities: List[Dict[str, Any]]
    analysis: str
    confidence_score: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class NostrPublisher:
    """
    NOSTR publisher for prediction market analysis
    @requirement: REQ-NOSTR-001 - Self-hosted relay integration
    @requirement: REQ-NOSTR-003 - DID document schema
    """

    def __init__(self, private_key_hex: str = None, relay_urls: List[str] = None):
        """
        Initialize NOSTR publisher

        Args:
            private_key_hex: Hex-encoded private key for signing
            relay_urls: List of NOSTR relay URLs
        """
        try:
            # Generate or use provided private key
            if private_key_hex:
                self.private_key_hex = private_key_hex
            else:
                self.private_key_hex = secrets.token_hex(32)

            # Generate public key from private key using coincurve (BIP-340)
            private_key_bytes = bytes.fromhex(self.private_key_hex)
            pk = coincurve.PrivateKey(private_key_bytes)
            # X-only public key (32 bytes) for Nostr/BIP-340
            public_key_bytes = pk.public_key.format(compressed=True)
            # Compressed pubkey is 33 bytes (prefix + x-coord), take x-only (skip prefix byte)
            self.public_key_hex = public_key_bytes[1:].hex()

            # Default relay URLs
            self.relay_urls = relay_urls or [
                "wss://relay.damus.io",
                "wss://nos.lol",
                "wss://relay.nostr.band",
            ]

            self.agent_id = f"chainlink-prediction-agent-{self.public_key_hex[:16]}"

            print(f"✅ NostrPublisher initialized")
            print(f"   Agent ID: {self.agent_id}")
            print(f"   Public key: {self.public_key_hex[:16]}...")
            print(f"   Relays: {len(self.relay_urls)}")

        except Exception as e:
            print(f"❌ NostrPublisher initialization failed: {e}")
            raise

    def _sign_event(self, event: NostrEvent) -> str:
        """
        Sign NOSTR event following NIP-01
        @requirement: REQ-NOSTR-003 - DID document schema
        """
        try:
            # Create serialized event for signing
            event_data = [
                0,  # Reserved for future use
                event.pubkey,
                event.created_at,
                event.kind,
                event.tags,
                event.content,
            ]

            serialized = json.dumps(event_data, separators=(",", ":"), ensure_ascii=False)
            event_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            event.id = event_id

            # BIP-340 Schnorr signature using coincurve
            import coincurve

            pk = coincurve.PrivateKey(bytes.fromhex(self.private_key_hex))
            sig = pk.sign_schnorr(bytes.fromhex(event_id))
            signature_hex = sig.hex()

            print(f"✅ Event signed: {event_id[:16]}...")
            return signature_hex

        except Exception as e:
            print(f"❌ Event signing failed: {e}")
            raise

    async def publish_prediction_analysis(self, analysis: PredictionMarketPost) -> Dict[str, Any]:
        """
        Publish prediction market analysis to NOSTR
        @requirement: REQ-CRYPTO-001 - Crypto analysis posting
        @requirement: REQ-NOSTR-002 - Lightning integration for zaps
        """
        try:
            print(f"📊 Publishing prediction analysis: {analysis.title}")

            # Create structured content
            content = self._format_prediction_content(analysis)

            # Create NOSTR event
            event = NostrEvent(
                pubkey=self.public_key_hex,
                kind=1,  # Text note
                content=content,
                tags=[
                    ["t", "chainlink"],
                    ["t", "prediction-markets"],
                    ["t", "crypto-analysis"],
                    ["p", self.public_key_hex, "", "author"],
                    ["e", "", "", "root"],
                ],
            )

            # Sign the event
            event.sig = self._sign_event(event)

            # Publish to relays
            results = await self._publish_to_relays(event)

            # Prepare response
            response = {
                "event_id": event.id,
                "public_key": self.public_key_hex,
                "relay_results": results,
                "content_summary": analysis.title,
                "timestamp": analysis.timestamp,
                "success": len([r for r in results.values() if r.get("success")]) > 0,
            }

            print(f"✅ Prediction analysis published to {len(results)} relays")
            return response

        except Exception as e:
            print(f"❌ Publishing prediction analysis failed: {e}")
            import traceback

            traceback.print_exc()
            return {"error": str(e), "success": False}

    async def publish_chainlink_oracle_update(self, oracle_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish Chainlink oracle data update to NOSTR
        @requirement: REQ-CHAINLINK-001 - Oracle data publishing
        """
        try:
            print(f"🔗 Publishing Chainlink oracle update")

            # Format oracle update content
            content = self._format_oracle_content(oracle_data)

            # Create NOSTR event
            event = NostrEvent(
                pubkey=self.public_key_hex,
                kind=1,
                content=content,
                tags=[
                    ["t", "chainlink"],
                    ["t", "oracle"],
                    ["t", "price-feed"],
                    ["p", self.public_key_hex, "", "author"],
                ],
            )

            # Sign and publish
            event.sig = self._sign_event(event)
            results = await self._publish_to_relays(event)

            response = {
                "event_id": event.id,
                "oracle_pair": oracle_data.get("pair", "Unknown"),
                "price": oracle_data.get("price", 0),
                "relay_results": results,
                "success": len([r for r in results.values() if r.get("success")]) > 0,
            }

            print(
                f"✅ Oracle update published: {oracle_data.get('pair')} = ${oracle_data.get('price', 0):,.2f}"
            )
            return response

        except Exception as e:
            print(f"❌ Publishing oracle update failed: {e}")
            return {"error": str(e), "success": False}

    async def publish_arbitrage_opportunity(self, arbitrage_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish arbitrage opportunity to NOSTR
        @requirement: REQ-ARBITRAGE-001 - Arbitrage opportunity sharing
        """
        try:
            print(f"⚡ Publishing arbitrage opportunity")

            # Format arbitrage content
            content = self._format_arbitrage_content(arbitrage_data)

            # Create NOSTR event
            event = NostrEvent(
                pubkey=self.public_key_hex,
                kind=1,
                content=content,
                tags=[
                    ["t", "arbitrage"],
                    ["t", "trading-opportunity"],
                    ["t", "defi"],
                    ["p", self.public_key_hex, "", "author"],
                ],
            )

            # Sign and publish
            event.sig = self._sign_event(event)
            results = await self._publish_to_relays(event)

            response = {
                "event_id": event.id,
                "profit_percentage": arbitrage_data.get("profit_percentage", 0),
                "markets": arbitrage_data.get("markets", []),
                "relay_results": results,
                "success": len([r for r in results.values() if r.get("success")]) > 0,
            }

            print(
                f"✅ Arbitrage opportunity published: {arbitrage_data.get('profit_percentage', 0):.2f}% profit"
            )
            return response

        except Exception as e:
            print(f"❌ Publishing arbitrage opportunity failed: {e}")
            return {"error": str(e), "success": False}

    def _format_prediction_content(self, analysis: PredictionMarketPost) -> str:
        """Format prediction market analysis for NOSTR post"""
        content = f"""🔮 Prediction Market Analysis - {analysis.title}

📊 Market Data:
"""

        # Add market data summary
        for market, data in analysis.market_data.items():
            if isinstance(data, dict):
                content += (
                    f"• {market}: {data.get('price', 'N/A')} ({data.get('volume', 'N/A')} volume)\n"
                )
            else:
                content += f"• {market}: {data}\n"

        content += f"""
🔗 Chainlink Oracle Data:
"""

        # Add oracle data
        for pair, data in analysis.chainlink_data.items():
            if isinstance(data, dict):
                content += f"• {pair}: ${data.get('price', 0):,.2f} (Updated: {data.get('timestamp', 'N/A')})\n"
            else:
                content += f"• {pair}: {data}\n"

        # Add arbitrage opportunities
        if analysis.arbitrage_opportunities:
            content += f"\n⚡ Arbitrage Opportunities:\n"
            for opp in analysis.arbitrage_opportunities:
                profit = opp.get("profit_percentage", 0)
                content += (
                    f"• {profit:.2f}% profit between {opp.get('markets', 'Unknown markets')}\n"
                )

        content += f"""
📈 Analysis:
{analysis.analysis}

🎯 Confidence Score: {analysis.confidence_score:.2f}/1.0
⏰ Generated: {analysis.timestamp}

#ChainlinkPredictionMarkets #CryptoAnalysis #DeFi #PredictionMarkets #Arbitrage
"""

        return content

    def _format_oracle_content(self, oracle_data: Dict[str, Any]) -> str:
        """Format Chainlink oracle data for NOSTR post"""
        pair = oracle_data.get("pair", "Unknown")
        price = oracle_data.get("price", 0)
        timestamp = oracle_data.get("timestamp", "Unknown")
        network = oracle_data.get("network", "Unknown")

        content = f"""🔗 Chainlink Oracle Update

📊 {pair}: ${price:,.2f}
🌐 Network: {network}
⏰ Updated: {timestamp}

#Chainlink #Oracle #PriceFeed #DeFi
"""
        return content

    def _format_arbitrage_content(self, arbitrage_data: Dict[str, Any]) -> str:
        """Format arbitrage opportunity for NOSTR post"""
        profit = arbitrage_data.get("profit_percentage", 0)
        markets = arbitrage_data.get("markets", [])
        asset = arbitrage_data.get("asset", "Unknown")

        content = f"""⚡ Arbitrage Opportunity Detected!

💰 Asset: {asset}
📈 Profit: {profit:.2f}%
🏪 Markets: {' ↔ '.join(markets)}
⏱ Opportunity Window: {arbitrage_data.get('window_minutes', 'Unknown')} minutes

⚠️ This is not financial advice. DYOR!

#Arbitrage #TradingOpportunity #DeFi #CryptoTrading
"""
        return content

    async def _publish_to_relays(self, event: NostrEvent) -> Dict[str, Dict[str, Any]]:
        """
        Publish event to all configured NOSTR relays
        @requirement: REQ-NOSTR-001 - Relay communication
        """
        results = {}

        for relay_url in self.relay_urls:
            try:
                result = await self._publish_to_relay(event, relay_url)
                results[relay_url] = result

            except Exception as e:
                results[relay_url] = {"success": False, "error": str(e)}
                print(f"❌ Failed to publish to {relay_url}: {e}")

        return results

    async def _publish_to_relay(self, event: NostrEvent, relay_url: str) -> Dict[str, Any]:
        """
        Publish event to a single NOSTR relay
        @requirement: REQ-NOSTR-001 - Relay communication protocol
        """
        try:
            # Convert event to JSON message
            event_dict = asdict(event)
            message = json.dumps(["EVENT", event_dict])

            # For WebSocket relays
            if relay_url.startswith("ws"):
                # websockets 15.x API: open_timeout instead of timeout
                async with websockets.connect(
                    relay_url,
                    open_timeout=10,
                    close_timeout=5,
                ) as websocket:
                    await websocket.send(message)

                    # Wait for response
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=5)
                        response_data = json.loads(response)

                        if response_data[0] == "OK" and response_data[2]:
                            return {"success": True, "message": "Event accepted"}
                        else:
                            return {
                                "success": False,
                                "error": (
                                    response_data[3] if len(response_data) > 3 else "Unknown error"
                                ),
                            }

                    except asyncio.TimeoutError:
                        return {"success": True, "message": "Event sent, no response received"}

            # For HTTP relays (fallback)
            else:
                response = requests.post(relay_url, json=event_dict, timeout=10)
                if response.status_code == 200:
                    return {"success": True, "message": "Event accepted"}
                else:
                    return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_agent_profile(self) -> Dict[str, Any]:
        """
        Get NOSTR profile information for the agent
        @requirement: REQ-NOSTR-003 - DID document schema
        """
        try:
            profile = {
                "agent_id": self.agent_id,
                "public_key": self.public_key_hex,
                "did": f"did:nostr:{self.public_key_hex}",
                "capabilities": [
                    "chainlink_oracle_monitoring",
                    "prediction_market_analysis",
                    "arbitrage_detection",
                    "crypto_research",
                    "real_time_alerts",
                ],
                "relay_urls": self.relay_urls,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            print(f"✅ Agent profile generated: {self.agent_id}")
            return profile

        except Exception as e:
            print(f"❌ Failed to get agent profile: {e}")
            return {"error": str(e)}

    async def publish_research_analysis(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publish comprehensive prediction research analysis
        @requirement: REQ-CRYPTO-005 - Research publication
        """
        try:
            print(f"📚 Publishing research analysis")

            # Create comprehensive research content
            content = self._format_research_content(research_data)

            # Create NOSTR event
            event = NostrEvent(
                pubkey=self.public_key_hex,
                kind=30023,  # Long-form content
                content=content,
                tags=[
                    ["t", "research"],
                    ["t", "prediction-markets"],
                    ["t", "crypto-analysis"],
                    ["t", "defi"],
                    ["title", research_data.get("title", "Prediction Market Research")],
                    ["published_at", str(int(datetime.now(timezone.utc).timestamp()))],
                    ["p", self.public_key_hex, "", "author"],
                ],
            )

            # Sign and publish
            event.sig = self._sign_event(event)
            results = await self._publish_to_relays(event)

            response = {
                "event_id": event.id,
                "research_title": research_data.get("title", "Unknown"),
                "relay_results": results,
                "success": len([r for r in results.values() if r.get("success")]) > 0,
            }

            print(f"✅ Research analysis published")
            return response

        except Exception as e:
            print(f"❌ Publishing research analysis failed: {e}")
            return {"error": str(e), "success": False}

    def _format_research_content(self, research_data: Dict[str, Any]) -> str:
        """Format comprehensive research analysis for NOSTR"""
        title = research_data.get("title", "Prediction Market Research Analysis")

        content = f"""# {title}

## Executive Summary
{research_data.get("executive_summary", "Comprehensive analysis of prediction market trends and opportunities.")}

## Market Overview
"""

        # Add market data
        markets = research_data.get("markets_analyzed", {})
        for market_name, data in markets.items():
            content += f"\n### {market_name}\n"
            if isinstance(data, dict):
                for key, value in data.items():
                    content += f"- **{key.replace('_', ' ').title()}:** {value}\n"
            else:
                content += f"- {data}\n"

        # Add oracle insights
        if research_data.get("oracle_insights"):
            content += "\n## Chainlink Oracle Insights\n"
            for insight in research_data["oracle_insights"]:
                content += f"- {insight}\n"

        # Add predictions
        if research_data.get("predictions"):
            content += "\n## Key Predictions\n"
            for prediction in research_data["predictions"]:
                content += f"- **{prediction.get('market', 'Unknown')}:** {prediction.get('prediction', 'N/A')} (Confidence: {prediction.get('confidence', 0)}%)\n"

        # Add risk analysis
        if research_data.get("risk_analysis"):
            content += f"\n## Risk Analysis\n{research_data['risk_analysis']}\n"

        # Add recommendations
        if research_data.get("recommendations"):
            content += "\n## Recommendations\n"
            for rec in research_data["recommendations"]:
                content += f"- {rec}\n"

        content += f"""
## Methodology
This analysis was generated using autonomous AI agents with access to:
- Real-time Chainlink oracle data
- Multiple prediction market platforms
- Advanced statistical models
- Historical trend analysis

## Disclaimer
This research is for informational purposes only and does not constitute financial advice. 
Always conduct your own research before making investment decisions.

---
*Generated by Chainlink Prediction Markets AI Agent*
*Timestamp: {datetime.now(timezone.utc).isoformat()}*

#PredictionMarkets #Chainlink #DeFi #CryptoResearch #AIAnalysis
"""

        return content


# Utility functions for integration
def create_nostr_publisher(config: Dict[str, Any] = None) -> NostrPublisher:
    """
    Create and configure NOSTR publisher
    @requirement: REQ-NOSTR-001 - Publisher initialization
    """
    try:
        if not config:
            config = {}

        private_key = config.get("private_key")
        relay_urls = config.get(
            "relay_urls", ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.nostr.info"]
        )

        publisher = NostrPublisher(private_key, relay_urls)
        print(f"✅ NOSTR publisher created successfully")
        return publisher

    except Exception as e:
        print(f"❌ Failed to create NOSTR publisher: {e}")
        raise


async def publish_market_analysis_to_nostr(
    analysis_data: Dict[str, Any], publisher: NostrPublisher = None
) -> Dict[str, Any]:
    """
    Publish market analysis to NOSTR with proper formatting
    @requirement: REQ-CRYPTO-001 - Market analysis publishing
    """
    try:
        if not publisher:
            publisher = create_nostr_publisher()

        # Create prediction market post
        post = PredictionMarketPost(
            title=analysis_data.get("title", "Market Analysis"),
            market_data=analysis_data.get("market_data", {}),
            chainlink_data=analysis_data.get("chainlink_data", {}),
            arbitrage_opportunities=analysis_data.get("arbitrage_opportunities", []),
            analysis=analysis_data.get("analysis", ""),
            confidence_score=analysis_data.get("confidence_score", 0.0),
        )

        # Publish to NOSTR
        result = await publisher.publish_prediction_analysis(post)
        print(f"✅ Market analysis published to NOSTR")
        return result

    except Exception as e:
        print(f"❌ Failed to publish market analysis to NOSTR: {e}")
        return {"error": str(e), "success": False}


if __name__ == "__main__":
    # Test the NOSTR integration
    async def test_nostr_integration():
        """Test NOSTR integration functionality"""
        try:
            print("🧪 Testing NOSTR Integration")

            # Create publisher
            publisher = create_nostr_publisher()

            # Test prediction analysis
            test_analysis = PredictionMarketPost(
                title="Test Prediction Market Analysis",
                market_data={
                    "kalshi": {"price": 0.65, "volume": "10K"},
                    "polymarket": {"price": 0.62, "volume": "25K"},
                },
                chainlink_data={
                    "BTC-USD": {"price": 65432.50, "timestamp": "2025-11-15T19:30:00Z"}
                },
                arbitrage_opportunities=[
                    {"profit_percentage": 4.8, "markets": ["Kalshi", "Polymarket"]}
                ],
                analysis="Strong arbitrage opportunity detected with 4.8% profit potential.",
                confidence_score=0.85,
            )

            result = await publisher.publish_prediction_analysis(test_analysis)
            print(f"📊 Test result: {result}")

            # Test oracle update
            oracle_data = {
                "pair": "BTC-USD",
                "price": 65432.50,
                "network": "ethereum",
                "timestamp": "2025-11-15T19:30:00Z",
            }

            oracle_result = await publisher.publish_chainlink_oracle_update(oracle_data)
            print(f"🔗 Oracle result: {oracle_result}")

            print("✅ NOSTR integration test completed successfully")

        except Exception as e:
            print(f"❌ NOSTR integration test failed: {e}")
            import traceback

            traceback.print_exc()

    # Run test
    asyncio.run(test_nostr_integration())
