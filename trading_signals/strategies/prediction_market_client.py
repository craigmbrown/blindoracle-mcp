"""
Unified Prediction Market Client for Polymarket, Kalshi, Manifold.

REQ-RQ029-001: Cross-platform prediction market data aggregation
BLP-031: Self-Improvement through multi-source signal fusion

Fetches live probability data from 3 free, no-auth prediction market APIs
with caching, error handling, and cross-platform fuzzy matching.
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple


class PredictionMarketClient:
    """Fetches live probability data from 3 prediction market platforms."""

    POLYMARKET_BASE = "https://gamma-api.polymarket.com"
    KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
    MANIFOLD_BASE = "https://api.manifold.markets/v0"

    CRYPTO_KEYWORDS = [
        "bitcoin", "btc", "ethereum", "eth", "crypto",
        "solana", "sol", "chainlink", "link",
    ]

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

    async def _fetch_json(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        """Fetch JSON with error handling and timeout."""
        self.total_calls += 1
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        return await r.json()
                    print(f"WARNING [PredictionMarketClient]: {url} returned {r.status}")
                    return None
        except Exception as e:
            print(f"WARNING [PredictionMarketClient]: {url} failed: {e}")
            return None

    # --- Polymarket Gamma API ---

    async def get_polymarket_markets(
        self, limit: int = 50, crypto_only: bool = True,
    ) -> List[dict]:
        """Fetch open markets from Polymarket Gamma API."""
        cache_key = ("polymarket", limit, crypto_only)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        data = await self._fetch_json(
            f"{self.POLYMARKET_BASE}/markets",
            {"closed": "false", "limit": str(limit)},
        )
        if not data or not isinstance(data, list):
            return []

        markets = []
        for m in data:
            prices = m.get("outcomePrices", [])
            # outcomePrices can be strings or floats
            try:
                yes_prob = float(prices[0]) if prices else 0.5
            except (ValueError, TypeError):
                yes_prob = 0.5
            try:
                no_prob = float(prices[1]) if len(prices) > 1 else 1 - yes_prob
            except (ValueError, TypeError):
                no_prob = 1 - yes_prob

            question = m.get("question", "").lower()

            entry = {
                "platform": "polymarket",
                "id": m.get("id", ""),
                "question": m.get("question", ""),
                "yes_prob": yes_prob,
                "no_prob": no_prob,
                "volume": float(m.get("volume", 0) or 0),
                "liquidity": float(m.get("liquidity", 0) or 0),
            }

            if crypto_only:
                if any(kw in question for kw in self.CRYPTO_KEYWORDS):
                    markets.append(entry)
            else:
                markets.append(entry)

        self._set_cache(cache_key, markets)
        return markets

    # --- Kalshi API ---

    async def get_kalshi_markets(self, limit: int = 50) -> List[dict]:
        """Fetch open markets from Kalshi elections API."""
        cache_key = ("kalshi", limit)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        data = await self._fetch_json(
            f"{self.KALSHI_BASE}/markets",
            {"status": "open", "limit": str(limit)},
        )
        if not data:
            return []

        raw_markets = data.get("markets", []) if isinstance(data, dict) else data
        markets = []
        for m in raw_markets:
            yes_bid = float(m.get("yes_bid", 50)) / 100  # Kalshi uses cents
            markets.append({
                "platform": "kalshi",
                "id": m.get("ticker", ""),
                "question": m.get("title", ""),
                "yes_prob": yes_bid,
                "no_prob": 1 - yes_bid,
                "volume": float(m.get("volume", 0) or 0),
            })

        self._set_cache(cache_key, markets)
        return markets

    # --- Manifold API ---

    async def get_manifold_markets(
        self, term: str = "bitcoin", limit: int = 50,
    ) -> List[dict]:
        """Fetch open markets from Manifold Markets API."""
        cache_key = ("manifold", term, limit)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        data = await self._fetch_json(
            f"{self.MANIFOLD_BASE}/search-markets",
            {"term": term, "filter": "open", "sort": "liquidity", "limit": str(limit)},
        )
        if not data or not isinstance(data, list):
            return []

        markets = []
        for m in data:
            prob = float(m.get("probability", 0.5))
            markets.append({
                "platform": "manifold",
                "id": m.get("id", ""),
                "question": m.get("question", ""),
                "yes_prob": prob,
                "no_prob": 1 - prob,
                "volume": float(m.get("volume", 0) or 0),
                "volume_24h": float(m.get("volume24Hours", 0) or 0),
            })

        self._set_cache(cache_key, markets)
        return markets

    # --- Cross-platform matching ---

    def match_markets(
        self,
        markets_a: List[dict],
        markets_b: List[dict],
        min_similarity: float = 0.3,
    ) -> List[Tuple[dict, dict, float]]:
        """Fuzzy match markets across platforms by question text overlap."""
        matches = []
        for a in markets_a:
            qa = set(a["question"].lower().split())
            best_match = None
            best_score = 0.0
            for b in markets_b:
                qb = set(b["question"].lower().split())
                if not qa or not qb:
                    continue
                overlap = len(qa & qb) / max(len(qa | qb), 1)
                if overlap > best_score and overlap >= min_similarity:
                    best_score = overlap
                    best_match = b
            if best_match:
                matches.append((a, best_match, best_score))
        return matches
