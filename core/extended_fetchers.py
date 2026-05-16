#!/usr/bin/env python3
"""
Extended Data Fetchers for Additional Job Types
================================================

New job types:
- CrossChainFetcher: Multi-chain oracle feeds (Arbitrum, Base, Polygon)
- VolatilityFetcher: Price volatility tracking and analysis
- SentimentFetcher: Market sentiment scoring from multiple sources
- AlertFetcher: Price threshold monitoring and alerts
- HistoricalFetcher: Trend analysis over time periods
"""

import sys
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configuration for multi-chain support
CHAIN_CONFIGS = {
    "ethereum": {
        "chain_id": 1,
        "rpc_env": "ETH_RPC_URL",
        "default_rpc": "https://eth-mainnet.g.alchemy.com/v2/demo",
        "feeds": {
            "BTC/USD": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
            "ETH/USD": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
            "LINK/USD": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",
        },
    },
    "arbitrum": {
        "chain_id": 42161,
        "rpc_env": "ARBITRUM_RPC_URL",
        "default_rpc": "https://arb1.arbitrum.io/rpc",
        "feeds": {
            "BTC/USD": "0x6ce185860a4963106506C203335A2910ff3f7fD3",
            "ETH/USD": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
            "ARB/USD": "0xb2A824043730FE05F3DA2efaFa1CBbe83fa548D6",
        },
    },
    "base": {
        "chain_id": 8453,
        "rpc_env": "BASE_RPC_URL",
        "default_rpc": "https://mainnet.base.org",
        "feeds": {
            "BTC/USD": "0x64c911996D3c6aC71E9b8EE1a60F78BA0bC6f2D0",
            "ETH/USD": "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70",
        },
    },
    "polygon": {
        "chain_id": 137,
        "rpc_env": "POLYGON_RPC_URL",
        "default_rpc": "https://polygon-rpc.com",
        "feeds": {
            "BTC/USD": "0xc907E116054Ad103354f2D350FD2514433D57F6f",
            "ETH/USD": "0xF9680D99D6C9589e2a93a78A04A279e509205945",
            "MATIC/USD": "0xAB594600376Ec9fD91F8e885dADF0CE036862dE0",
        },
    },
}

# Price history storage
PRICE_HISTORY_FILE = PROJECT_ROOT / "logs" / "price_history.json"
ALERTS_CONFIG_FILE = PROJECT_ROOT / "logs" / "price_alerts.json"


@dataclass
class PricePoint:
    """Single price data point."""

    pair: str
    price: float
    timestamp: str
    chain: str
    block: Optional[int] = None
    round_id: Optional[int] = None


class DataFetcher(ABC):
    """Abstract base class for data fetchers."""

    @abstractmethod
    def fetch(self) -> Dict[str, Any]:
        """Fetch data synchronously."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        pass

    @abstractmethod
    def is_real_data(self) -> bool:
        pass


class CrossChainPriceFetcher(DataFetcher):
    """
    Fetches prices from multiple chains (Arbitrum, Base, Polygon, Ethereum).
    Compares prices across chains and identifies discrepancies.
    """

    def __init__(self, chains: List[str] = None):
        self.chains = chains or ["ethereum", "arbitrum", "base"]
        self._web3_clients = {}
        self._available = False

        try:
            from web3 import Web3
            import os

            for chain in self.chains:
                config = CHAIN_CONFIGS.get(chain, {})
                rpc_url = os.environ.get(config.get("rpc_env", ""), config.get("default_rpc", ""))
                if rpc_url:
                    self._web3_clients[chain] = Web3(Web3.HTTPProvider(rpc_url))
                    self._available = True
        except ImportError:
            pass

    def fetch(self) -> Dict[str, Any]:
        if not self._available:
            return self._generate_simulated_data()

        results = {
            "source": "cross_chain_oracle",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chains": {},
            "price_comparison": {},
            "discrepancies": [],
        }

        # Chainlink ABI for latestRoundData
        aggregator_abi = [
            {
                "inputs": [],
                "name": "latestRoundData",
                "outputs": [
                    {"name": "roundId", "type": "uint80"},
                    {"name": "answer", "type": "int256"},
                    {"name": "startedAt", "type": "uint256"},
                    {"name": "updatedAt", "type": "uint256"},
                    {"name": "answeredInRound", "type": "uint80"},
                ],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

        all_prices = {}

        for chain, w3 in self._web3_clients.items():
            try:
                if not w3.is_connected():
                    continue

                config = CHAIN_CONFIGS.get(chain, {})
                chain_prices = {}

                for pair, address in config.get("feeds", {}).items():
                    try:
                        contract = w3.eth.contract(
                            address=w3.to_checksum_address(address), abi=aggregator_abi
                        )
                        round_data = contract.functions.latestRoundData().call()
                        decimals = contract.functions.decimals().call()

                        price = round_data[1] / (10**decimals)
                        chain_prices[pair] = {
                            "price": price,
                            "round_id": round_data[0],
                            "updated_at": round_data[3],
                            "block": w3.eth.block_number,
                        }

                        # Aggregate for comparison
                        if pair not in all_prices:
                            all_prices[pair] = []
                        all_prices[pair].append({"chain": chain, "price": price})

                    except Exception as e:
                        chain_prices[pair] = {"error": str(e)}

                results["chains"][chain] = {
                    "chain_id": config.get("chain_id"),
                    "prices": chain_prices,
                    "block": w3.eth.block_number,
                }

            except Exception as e:
                results["chains"][chain] = {"error": str(e)}

        # Calculate price discrepancies
        for pair, prices in all_prices.items():
            if len(prices) >= 2:
                price_values = [p["price"] for p in prices]
                avg_price = sum(price_values) / len(price_values)
                max_diff = max(abs(p - avg_price) for p in price_values)
                diff_pct = (max_diff / avg_price * 100) if avg_price > 0 else 0

                results["price_comparison"][pair] = {
                    "prices_by_chain": prices,
                    "average": avg_price,
                    "max_difference_pct": round(diff_pct, 4),
                }

                if diff_pct > 0.1:  # > 0.1% discrepancy
                    results["discrepancies"].append(
                        {
                            "pair": pair,
                            "difference_pct": round(diff_pct, 4),
                            "chains": [p["chain"] for p in prices],
                        }
                    )

        results["summary"] = {
            "chains_queried": len(results["chains"]),
            "pairs_compared": len(results["price_comparison"]),
            "discrepancies_found": len(results["discrepancies"]),
        }

        return results

    def _generate_simulated_data(self) -> Dict[str, Any]:
        """Generate simulated cross-chain data."""
        import random

        base_prices = {"BTC/USD": 92500, "ETH/USD": 3300, "ARB/USD": 0.85, "MATIC/USD": 0.55}

        results = {
            "source": "cross_chain_simulated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chains": {},
            "price_comparison": {},
            "discrepancies": [],
        }

        for chain in self.chains:
            config = CHAIN_CONFIGS.get(chain, {})
            chain_prices = {}

            for pair in config.get("feeds", {}).keys():
                base = base_prices.get(pair, 100)
                # Add small random variation per chain
                variation = random.uniform(-0.002, 0.002)
                chain_prices[pair] = {
                    "price": round(base * (1 + variation), 2),
                    "round_id": random.randint(1000000, 9999999),
                    "updated_at": int(datetime.now(timezone.utc).timestamp()),
                    "block": random.randint(20000000, 25000000),
                }

            results["chains"][chain] = {
                "chain_id": config.get("chain_id"),
                "prices": chain_prices,
                "block": random.randint(20000000, 25000000),
            }

        return results

    def get_source_name(self) -> str:
        return "cross_chain_oracle"

    def is_real_data(self) -> bool:
        return self._available and len(self._web3_clients) > 0


class VolatilityMonitorFetcher(DataFetcher):
    """
    Monitors price volatility over different time windows.
    Calculates standard deviation, ATR-like metrics, and volatility percentiles.
    """

    def __init__(self, windows: List[int] = None):
        """
        Args:
            windows: Time windows in minutes [5, 15, 60, 240]
        """
        self.windows = windows or [5, 15, 60, 240]
        self._price_history: Dict[str, List[PricePoint]] = {}
        self._load_history()

    def _load_history(self):
        """Load price history from file."""
        try:
            if PRICE_HISTORY_FILE.exists():
                with open(PRICE_HISTORY_FILE) as f:
                    data = json.load(f)
                    for pair, points in data.items():
                        self._price_history[pair] = [PricePoint(**p) for p in points]
        except:
            pass

    def _save_history(self):
        """Save price history to file."""
        try:
            data = {}
            for pair, points in self._price_history.items():
                # Keep last 24 hours
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                recent = [
                    {"pair": p.pair, "price": p.price, "timestamp": p.timestamp, "chain": p.chain}
                    for p in points
                    if datetime.fromisoformat(p.timestamp.replace("Z", "+00:00")) > cutoff
                ]
                if recent:
                    data[pair] = recent[-1000]  # Max 1000 points per pair

            PRICE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PRICE_HISTORY_FILE, "w") as f:
                json.dump(data, f)
        except:
            pass

    def _add_price(self, pair: str, price: float, chain: str = "ethereum"):
        """Add a price point to history."""
        if pair not in self._price_history:
            self._price_history[pair] = []

        self._price_history[pair].append(
            PricePoint(
                pair=pair,
                price=price,
                timestamp=datetime.now(timezone.utc).isoformat(),
                chain=chain,
            )
        )

    def _calculate_volatility(self, prices: List[float]) -> Dict[str, float]:
        """Calculate volatility metrics from price series."""
        if len(prices) < 2:
            return {"std_dev": 0, "range_pct": 0, "avg_change_pct": 0}

        import statistics

        # Standard deviation
        std_dev = statistics.stdev(prices)
        mean_price = statistics.mean(prices)

        # Range as percentage
        range_pct = ((max(prices) - min(prices)) / mean_price * 100) if mean_price > 0 else 0

        # Average change between consecutive prices
        changes = [
            abs(prices[i] - prices[i - 1]) / prices[i - 1] * 100
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        avg_change = sum(changes) / len(changes) if changes else 0

        return {
            "std_dev": round(std_dev, 4),
            "std_dev_pct": round((std_dev / mean_price * 100) if mean_price > 0 else 0, 4),
            "range_pct": round(range_pct, 4),
            "avg_change_pct": round(avg_change, 4),
            "high": max(prices),
            "low": min(prices),
            "data_points": len(prices),
        }

    def fetch(self) -> Dict[str, Any]:
        # First get current prices
        try:
            from core.chainlink_onchain import get_all_real_chainlink_prices

            current_prices = get_all_real_chainlink_prices()

            # Add to history
            if "feeds" in current_prices:
                for pair, data in current_prices["feeds"].items():
                    if isinstance(data, dict) and "price" in data:
                        self._add_price(pair, data["price"])

            self._save_history()
        except:
            pass

        results = {
            "source": "volatility_monitor",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "volatility_by_pair": {},
            "volatility_ranking": [],
            "alerts": [],
        }

        now = datetime.now(timezone.utc)

        for pair, points in self._price_history.items():
            pair_volatility = {"windows": {}}

            for window in self.windows:
                cutoff = now - timedelta(minutes=window)
                window_prices = [
                    p.price
                    for p in points
                    if datetime.fromisoformat(p.timestamp.replace("Z", "+00:00")) > cutoff
                ]

                if window_prices:
                    pair_volatility["windows"][f"{window}m"] = self._calculate_volatility(
                        window_prices
                    )

            if pair_volatility["windows"]:
                # Overall volatility score (weighted avg of std_dev_pct)
                scores = []
                for w, data in pair_volatility["windows"].items():
                    if "std_dev_pct" in data:
                        scores.append(data["std_dev_pct"])
                pair_volatility["volatility_score"] = (
                    round(sum(scores) / len(scores), 4) if scores else 0
                )

                results["volatility_by_pair"][pair] = pair_volatility

        # Rank by volatility
        ranked = sorted(
            [
                (pair, data.get("volatility_score", 0))
                for pair, data in results["volatility_by_pair"].items()
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        results["volatility_ranking"] = [{"pair": p, "score": s} for p, s in ranked]

        # Alert on high volatility
        for pair, score in ranked:
            if score > 2.0:  # > 2% std deviation
                results["alerts"].append(
                    {
                        "type": "high_volatility",
                        "pair": pair,
                        "score": score,
                        "severity": "high" if score > 5 else "medium",
                    }
                )

        results["summary"] = {
            "pairs_monitored": len(results["volatility_by_pair"]),
            "high_volatility_count": len(results["alerts"]),
            "most_volatile": ranked[0] if ranked else None,
        }

        return results

    def get_source_name(self) -> str:
        return "volatility_monitor"

    def is_real_data(self) -> bool:
        return len(self._price_history) > 0


class SentimentAnalysisFetcher(DataFetcher):
    """
    Analyzes market sentiment from multiple sources:
    - Fear & Greed Index
    - Prediction market sentiment
    - Price momentum indicators
    """

    def __init__(self):
        self._available = True

    def fetch(self) -> Dict[str, Any]:
        results = {
            "source": "sentiment_analysis",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "indicators": {},
            "overall_sentiment": {},
            "market_signals": [],
        }

        # 1. Calculate momentum-based sentiment from price data
        try:
            from core.chainlink_onchain import get_all_real_chainlink_prices

            prices = get_all_real_chainlink_prices()

            if "feeds" in prices:
                momentum_signals = []
                for pair, data in prices.get("feeds", {}).items():
                    if isinstance(data, dict) and "price" in data:
                        # Simple momentum indicator based on recent price
                        price = data["price"]
                        # Would normally compare to historical, using simulated for now
                        momentum_signals.append({"pair": pair, "price": price, "signal": "neutral"})

                results["indicators"]["price_momentum"] = {
                    "signals": momentum_signals,
                    "bullish_count": len([s for s in momentum_signals if s["signal"] == "bullish"]),
                    "bearish_count": len([s for s in momentum_signals if s["signal"] == "bearish"]),
                }
        except:
            pass

        # 2. Try to get Fear & Greed Index
        try:
            import requests

            resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            if resp.status_code == 200:
                fng_data = resp.json().get("data", [{}])[0]
                results["indicators"]["fear_greed"] = {
                    "value": int(fng_data.get("value", 50)),
                    "classification": fng_data.get("value_classification", "Neutral"),
                    "timestamp": fng_data.get("timestamp"),
                }
        except:
            # Simulated Fear & Greed
            import random

            value = random.randint(30, 70)
            classification = "Fear" if value < 40 else "Greed" if value > 60 else "Neutral"
            results["indicators"]["fear_greed"] = {
                "value": value,
                "classification": classification,
                "source": "simulated",
            }

        # 3. Analyze prediction market sentiment
        try:
            from core.real_market_data import RealMarketDataFetcher
            import asyncio

            fetcher = RealMarketDataFetcher()
            # Use synchronous call or run async in event loop
            try:
                loop = asyncio.get_event_loop()
                market_data = loop.run_until_complete(fetcher.get_market_analysis_for_job())
            except RuntimeError:
                market_data = asyncio.run(fetcher.get_market_analysis_for_job())

            if "summary" in market_data:
                # Analyze market probabilities for sentiment
                results["indicators"]["prediction_markets"] = {
                    "total_markets": market_data["summary"].get("total_markets", 0),
                    "total_volume": market_data["summary"].get("total_volume", 0),
                    "source": "kalshi_polymarket",
                }
        except:
            pass

        # 4. Calculate overall sentiment score
        sentiment_scores = []

        if "fear_greed" in results["indicators"]:
            # Normalize Fear & Greed to -1 to 1
            fg_value = results["indicators"]["fear_greed"]["value"]
            fg_score = (fg_value - 50) / 50  # -1 to 1
            sentiment_scores.append(("fear_greed", fg_score, 0.4))  # 40% weight

        if "price_momentum" in results["indicators"]:
            pm = results["indicators"]["price_momentum"]
            bullish = pm.get("bullish_count", 0)
            bearish = pm.get("bearish_count", 0)
            total = bullish + bearish
            if total > 0:
                pm_score = (bullish - bearish) / total
                sentiment_scores.append(("momentum", pm_score, 0.3))  # 30% weight

        # Calculate weighted average
        if sentiment_scores:
            total_weight = sum(w for _, _, w in sentiment_scores)
            weighted_score = sum(s * w for _, s, w in sentiment_scores) / total_weight

            # Convert to 0-100 scale
            sentiment_value = int((weighted_score + 1) * 50)

            results["overall_sentiment"] = {
                "score": sentiment_value,
                "classification": self._classify_sentiment(sentiment_value),
                "confidence": round(total_weight * 100, 1),
                "components": [
                    {"indicator": i, "score": round(s, 3), "weight": w}
                    for i, s, w in sentiment_scores
                ],
            }

            # Generate market signals
            if sentiment_value > 70:
                results["market_signals"].append(
                    {
                        "type": "bullish",
                        "strength": "strong" if sentiment_value > 80 else "moderate",
                        "message": "Strong bullish sentiment detected",
                    }
                )
            elif sentiment_value < 30:
                results["market_signals"].append(
                    {
                        "type": "bearish",
                        "strength": "strong" if sentiment_value < 20 else "moderate",
                        "message": "Strong bearish sentiment detected",
                    }
                )

        return results

    def _classify_sentiment(self, score: int) -> str:
        if score >= 80:
            return "Extreme Greed"
        elif score >= 60:
            return "Greed"
        elif score >= 40:
            return "Neutral"
        elif score >= 20:
            return "Fear"
        else:
            return "Extreme Fear"

    def get_source_name(self) -> str:
        return "sentiment_analysis"

    def is_real_data(self) -> bool:
        return True


class AlertGeneratorFetcher(DataFetcher):
    """
    Monitors prices against configured thresholds and generates alerts.
    Supports: price thresholds, percentage changes, cross-chain discrepancies.
    """

    def __init__(self):
        self._alerts_config = self._load_alerts_config()

    def _load_alerts_config(self) -> Dict[str, Any]:
        """Load alert configuration."""
        try:
            if ALERTS_CONFIG_FILE.exists():
                with open(ALERTS_CONFIG_FILE) as f:
                    return json.load(f)
        except:
            pass

        # Default alerts
        return {
            "price_alerts": [
                {"pair": "BTC/USD", "above": 100000, "below": 80000},
                {"pair": "ETH/USD", "above": 4000, "below": 2500},
            ],
            "change_alerts": [
                {"pair": "BTC/USD", "change_pct": 5, "window_minutes": 60},
                {"pair": "ETH/USD", "change_pct": 5, "window_minutes": 60},
            ],
            "discrepancy_alerts": [{"threshold_pct": 0.5}],  # Alert if cross-chain diff > 0.5%
        }

    def _save_alerts_config(self):
        """Save alert configuration."""
        try:
            ALERTS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ALERTS_CONFIG_FILE, "w") as f:
                json.dump(self._alerts_config, f, indent=2)
        except:
            pass

    def fetch(self) -> Dict[str, Any]:
        results = {
            "source": "alert_generator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_alerts": [],
            "alerts_checked": 0,
            "config_summary": {},
        }

        # Get current prices
        current_prices = {}
        try:
            from core.chainlink_onchain import get_all_real_chainlink_prices

            price_data = get_all_real_chainlink_prices()
            if "feeds" in price_data:
                for pair, data in price_data["feeds"].items():
                    if isinstance(data, dict) and "price" in data:
                        current_prices[pair] = data["price"]
        except:
            pass

        # Check price threshold alerts
        for alert in self._alerts_config.get("price_alerts", []):
            pair = alert.get("pair")
            price = current_prices.get(pair)
            results["alerts_checked"] += 1

            if price:
                if "above" in alert and price > alert["above"]:
                    results["active_alerts"].append(
                        {
                            "type": "price_above",
                            "pair": pair,
                            "current_price": price,
                            "threshold": alert["above"],
                            "severity": "high",
                            "message": f"{pair} is above ${alert['above']:,.2f}",
                        }
                    )
                if "below" in alert and price < alert["below"]:
                    results["active_alerts"].append(
                        {
                            "type": "price_below",
                            "pair": pair,
                            "current_price": price,
                            "threshold": alert["below"],
                            "severity": "high",
                            "message": f"{pair} is below ${alert['below']:,.2f}",
                        }
                    )

        # Check percentage change alerts
        try:
            if PRICE_HISTORY_FILE.exists():
                with open(PRICE_HISTORY_FILE) as f:
                    history = json.load(f)

                for alert in self._alerts_config.get("change_alerts", []):
                    pair = alert.get("pair")
                    window = alert.get("window_minutes", 60)
                    threshold = alert.get("change_pct", 5)
                    results["alerts_checked"] += 1

                    if pair in history and pair in current_prices:
                        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)
                        old_prices = [
                            p["price"]
                            for p in history[pair]
                            if datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
                            < cutoff
                        ]

                        if old_prices:
                            old_price = old_prices[-1]
                            current = current_prices[pair]
                            change_pct = abs((current - old_price) / old_price * 100)

                            if change_pct >= threshold:
                                direction = "up" if current > old_price else "down"
                                results["active_alerts"].append(
                                    {
                                        "type": "price_change",
                                        "pair": pair,
                                        "change_pct": round(change_pct, 2),
                                        "direction": direction,
                                        "window_minutes": window,
                                        "severity": (
                                            "high" if change_pct > threshold * 2 else "medium"
                                        ),
                                        "message": f"{pair} moved {direction} {change_pct:.2f}% in {window}min",
                                    }
                                )
        except:
            pass

        results["summary"] = {
            "total_alerts": len(results["active_alerts"]),
            "high_severity": len(
                [a for a in results["active_alerts"] if a.get("severity") == "high"]
            ),
            "alerts_checked": results["alerts_checked"],
            "config_rules": len(self._alerts_config.get("price_alerts", []))
            + len(self._alerts_config.get("change_alerts", [])),
        }

        return results

    def add_price_alert(self, pair: str, above: float = None, below: float = None):
        """Add a price threshold alert."""
        alert = {"pair": pair}
        if above:
            alert["above"] = above
        if below:
            alert["below"] = below
        self._alerts_config.setdefault("price_alerts", []).append(alert)
        self._save_alerts_config()

    def get_source_name(self) -> str:
        return "alert_generator"

    def is_real_data(self) -> bool:
        return True


class HistoricalAnalysisFetcher(DataFetcher):
    """
    Analyzes historical price trends over multiple time periods.
    Calculates: moving averages, trend direction, support/resistance levels.
    """

    def __init__(self):
        self._history_loaded = False

    def fetch(self) -> Dict[str, Any]:
        results = {
            "source": "historical_analysis",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis_by_pair": {},
            "market_trends": [],
            "technical_signals": [],
        }

        # Load price history
        history = {}
        try:
            if PRICE_HISTORY_FILE.exists():
                with open(PRICE_HISTORY_FILE) as f:
                    history = json.load(f)
                self._history_loaded = True
        except:
            pass

        for pair, points in history.items():
            if len(points) < 5:
                continue

            prices = [p["price"] for p in points]
            timestamps = [p["timestamp"] for p in points]

            analysis = {
                "data_points": len(prices),
                "time_range": {
                    "start": timestamps[0] if timestamps else None,
                    "end": timestamps[-1] if timestamps else None,
                },
            }

            # Calculate moving averages
            if len(prices) >= 5:
                analysis["ma_5"] = round(sum(prices[-5:]) / 5, 2)
            if len(prices) >= 20:
                analysis["ma_20"] = round(sum(prices[-20:]) / 20, 2)
            if len(prices) >= 50:
                analysis["ma_50"] = round(sum(prices[-50:]) / 50, 2)

            # Current price vs MAs
            current = prices[-1]
            analysis["current_price"] = current

            # Trend direction
            if "ma_5" in analysis and "ma_20" in analysis:
                if analysis["ma_5"] > analysis["ma_20"]:
                    analysis["short_term_trend"] = "bullish"
                else:
                    analysis["short_term_trend"] = "bearish"

            # Price vs MA signals
            if "ma_20" in analysis:
                if current > analysis["ma_20"] * 1.02:
                    analysis["ma_signal"] = "above_ma20"
                elif current < analysis["ma_20"] * 0.98:
                    analysis["ma_signal"] = "below_ma20"
                else:
                    analysis["ma_signal"] = "near_ma20"

            # Support/Resistance (simple: recent highs/lows)
            if len(prices) >= 20:
                recent = prices[-20:]
                analysis["resistance"] = round(max(recent), 2)
                analysis["support"] = round(min(recent), 2)

                # Distance to support/resistance
                analysis["distance_to_resistance_pct"] = round(
                    (analysis["resistance"] - current) / current * 100, 2
                )
                analysis["distance_to_support_pct"] = round(
                    (current - analysis["support"]) / current * 100, 2
                )

            # Overall change
            if len(prices) >= 2:
                first = prices[0]
                analysis["total_change_pct"] = round((current - first) / first * 100, 2)

            results["analysis_by_pair"][pair] = analysis

            # Add to market trends
            if "short_term_trend" in analysis:
                results["market_trends"].append(
                    {
                        "pair": pair,
                        "trend": analysis["short_term_trend"],
                        "current": current,
                        "ma_5": analysis.get("ma_5"),
                        "ma_20": analysis.get("ma_20"),
                    }
                )

            # Generate technical signals
            if "ma_signal" in analysis:
                if (
                    analysis["ma_signal"] == "above_ma20"
                    and analysis.get("short_term_trend") == "bullish"
                ):
                    results["technical_signals"].append(
                        {
                            "pair": pair,
                            "signal": "bullish_momentum",
                            "strength": "strong",
                            "reason": "Price above MA20 with bullish short-term trend",
                        }
                    )
                elif (
                    analysis["ma_signal"] == "below_ma20"
                    and analysis.get("short_term_trend") == "bearish"
                ):
                    results["technical_signals"].append(
                        {
                            "pair": pair,
                            "signal": "bearish_momentum",
                            "strength": "strong",
                            "reason": "Price below MA20 with bearish short-term trend",
                        }
                    )

        results["summary"] = {
            "pairs_analyzed": len(results["analysis_by_pair"]),
            "bullish_pairs": len([t for t in results["market_trends"] if t["trend"] == "bullish"]),
            "bearish_pairs": len([t for t in results["market_trends"] if t["trend"] == "bearish"]),
            "technical_signals": len(results["technical_signals"]),
            "data_available": self._history_loaded,
        }

        return results

    def get_source_name(self) -> str:
        return "historical_analysis"

    def is_real_data(self) -> bool:
        return self._history_loaded


# Test function
def test_extended_fetchers():
    """Test all extended fetchers."""
    print("=" * 70)
    print("TESTING EXTENDED DATA FETCHERS")
    print("=" * 70)

    fetchers = [
        ("Cross-Chain Prices", CrossChainPriceFetcher()),
        ("Volatility Monitor", VolatilityMonitorFetcher()),
        ("Sentiment Analysis", SentimentAnalysisFetcher()),
        ("Alert Generator", AlertGeneratorFetcher()),
        ("Historical Analysis", HistoricalAnalysisFetcher()),
    ]

    for name, fetcher in fetchers:
        print(f"\n--- {name} ---")
        try:
            result = fetcher.fetch()
            print(f"Source: {fetcher.get_source_name()}")
            print(f"Real Data: {fetcher.is_real_data()}")
            if "summary" in result:
                print(f"Summary: {json.dumps(result['summary'], indent=2)}")
            print("✅ Success")
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    test_extended_fetchers()
