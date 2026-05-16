"""
Unified Web Data Client for RQ-030 strategies.

REQ-RQ030-001: Real-time data enrichment from WebSearch, RPC, CoinGecko, Kalshi
BLP-031: Self-Improvement through multi-source signal fusion

Provides cached access to:
- WebSearch (news headlines via subprocess)
- Ethereum/Base RPC (gas prices, block fullness)
- CoinGecko trending coins
- Kalshi rate-cut prediction markets

All data sources verified live on 2026-03-16.
"""

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
ETH_RPC = "https://eth.llamarpc.com"
BASE_RPC = "https://mainnet.base.org"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class WebDataClient:
    """Unified client for WebSearch + RPC + CoinGecko + Kalshi data."""

    # Class-level cache: {key: (data, timestamp)}
    _cache: Dict = {}
    _CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self.total_calls = 0

    def _get_cached(self, key) -> Optional[object]:
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._CACHE_TTL:
                return data
        return None

    def _set_cache(self, key, data) -> None:
        self._cache[key] = (data, time.time())

    async def _fetch_json(self, url: str, params: Optional[dict] = None,
                          headers: Optional[dict] = None,
                          method: str = "GET",
                          json_body: Optional[dict] = None) -> Optional[dict]:
        """Fetch JSON with error handling and timeout."""
        self.total_calls += 1
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                kwargs = {
                    "timeout": aiohttp.ClientTimeout(total=15),
                }
                if params:
                    kwargs["params"] = params
                if headers:
                    kwargs["headers"] = headers
                if json_body:
                    kwargs["json"] = json_body

                if method == "POST":
                    async with s.post(url, **kwargs) as r:
                        if r.status == 200:
                            return await r.json()
                        print(f"WARNING [WebDataClient]: POST {url} returned {r.status}")
                        return None
                else:
                    async with s.get(url, **kwargs) as r:
                        if r.status == 200:
                            return await r.json()
                        print(f"WARNING [WebDataClient]: {url} returned {r.status}")
                        return None
        except Exception as e:
            print(f"WARNING [WebDataClient]: {url} failed: {e}")
            return None

    # --- News Search (WebSearch via subprocess) ---

    async def search_news(self, query: str, max_results: int = 10) -> List[dict]:
        """Search for news headlines using claude --print subprocess.

        Returns list of {title, snippet, url} dicts.
        Falls back to empty list on failure.
        """
        cache_key = ("news", query)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        self.total_calls += 1
        results = []

        try:
            # Use claude --print with a focused news extraction prompt
            prompt = (
                f'Search the web for: "{query}". '
                f"Return ONLY a JSON array of the top {max_results} results, each with "
                f'"title", "snippet", and "url" keys. No other text.'
            )
            proc = await asyncio.create_subprocess_exec(
                "claude", "--print", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**__import__("os").environ},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            text = stdout.decode("utf-8", errors="replace").strip()

            # Extract JSON array from response
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    results = [
                        {
                            "title": item.get("title", ""),
                            "snippet": item.get("snippet", ""),
                            "url": item.get("url", ""),
                        }
                        for item in parsed[:max_results]
                    ]
        except asyncio.TimeoutError:
            print(f"WARNING [WebDataClient]: News search timed out for '{query}'")
        except Exception as e:
            print(f"WARNING [WebDataClient]: News search failed: {e}")

        self._set_cache(cache_key, results)
        return results

    # --- Ethereum RPC ---

    async def get_eth_gas_price(self) -> Optional[int]:
        """Get current Ethereum gas price in gwei via eth_gasPrice RPC.

        Returns gas price in gwei, or None on failure.
        """
        cache_key = "eth_gas_price"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._fetch_json(
            ETH_RPC,
            method="POST",
            headers={"Content-Type": "application/json"},
            json_body={
                "jsonrpc": "2.0",
                "method": "eth_gasPrice",
                "params": [],
                "id": 1,
            },
        )
        if data and "result" in data:
            gas_wei = int(data["result"], 16)
            gas_gwei = gas_wei // 10**9
            self._set_cache(cache_key, gas_gwei)
            return gas_gwei
        return None

    async def get_eth_block_fullness(self) -> Optional[float]:
        """Get latest Ethereum block fullness (gasUsed / gasLimit).

        Returns ratio 0.0-1.0, or None on failure.
        """
        cache_key = "eth_block_fullness"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._fetch_json(
            ETH_RPC,
            method="POST",
            headers={"Content-Type": "application/json"},
            json_body={
                "jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": ["latest", False],
                "id": 1,
            },
        )
        if data and "result" in data:
            block = data["result"]
            gas_used = int(block.get("gasUsed", "0x0"), 16)
            gas_limit = int(block.get("gasLimit", "0x1"), 16)
            if gas_limit > 0:
                fullness = gas_used / gas_limit
                self._set_cache(cache_key, fullness)
                return fullness
        return None

    async def get_base_block_fullness(self) -> Optional[float]:
        """Get latest Base L2 block fullness (gasUsed / gasLimit).

        Returns ratio 0.0-1.0, or None on failure.
        """
        cache_key = "base_block_fullness"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._fetch_json(
            BASE_RPC,
            method="POST",
            headers={"Content-Type": "application/json"},
            json_body={
                "jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": ["latest", False],
                "id": 1,
            },
        )
        if data and "result" in data:
            block = data["result"]
            gas_used = int(block.get("gasUsed", "0x0"), 16)
            gas_limit = int(block.get("gasLimit", "0x1"), 16)
            if gas_limit > 0:
                fullness = gas_used / gas_limit
                self._set_cache(cache_key, fullness)
                return fullness
        return None

    # --- CoinGecko Trending ---

    async def get_trending_coins(self) -> List[dict]:
        """Get CoinGecko trending coins (top 15 by search activity).

        Returns list of {id, name, symbol, market_cap_rank, score} dicts.
        """
        cache_key = "coingecko_trending"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._fetch_json(f"{COINGECKO_BASE}/search/trending")
        if not data or "coins" not in data:
            return []

        coins = []
        for item in data.get("coins", []):
            c = item.get("item", {})
            coins.append({
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "symbol": c.get("symbol", "").upper(),
                "market_cap_rank": c.get("market_cap_rank", 999),
                "score": c.get("score", 0),
                "price_btc": c.get("price_btc", 0),
            })

        self._set_cache(cache_key, coins)
        return coins

    # --- Kalshi Rate-Cut Markets ---

    async def get_kalshi_rate_markets(self) -> List[dict]:
        """Get Kalshi markets related to Fed rate decisions.

        Returns list of {ticker, title, yes_prob, volume} dicts.
        """
        cache_key = "kalshi_rate_markets"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        data = await self._fetch_json(
            f"{KALSHI_BASE}/markets",
            params={"status": "open", "limit": "100"},
        )
        if not data:
            return []

        raw_markets = data.get("markets", []) if isinstance(data, dict) else data
        rate_keywords = ["rate", "fed", "fomc", "interest", "cut", "hike", "federal reserve"]

        markets = []
        for m in raw_markets:
            title = m.get("title", "").lower()
            if any(kw in title for kw in rate_keywords):
                yes_bid = float(m.get("yes_bid", 50)) / 100  # Kalshi uses cents
                markets.append({
                    "ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "yes_prob": yes_bid,
                    "no_prob": 1 - yes_bid,
                    "volume": float(m.get("volume", 0) or 0),
                })

        self._set_cache(cache_key, markets)
        return markets
