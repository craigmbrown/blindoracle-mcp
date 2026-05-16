"""
Shared BlindOracle + Chainlink Marketplace API client.

REQ-AUTORESEARCH-005: Unified API client with rate limiting and cost tracking.
All strategies share this client for BO and Chainlink API access.
"""

import asyncio
import time
from typing import Dict, List, Optional

from trading_signals.backtester import DualAmount


class BOApiClient:
    """Client for BlindOracle API + Chainlink Marketplace with rate limiting."""

    BO_BASE = "https://api.craigmbrown.com"
    CL_BASE = "https://craigmbrown.com/marketplace"
    AGENT_ID = "autoresearch-optimizer"

    # Per-endpoint costs (USD)
    COSTS = {
        "/v2/forecasts": 0.001,
        "/v2/positions": 0.0005,
        "/v2/forecasts/resolve": 0.002,
        "/v2/account/balance": 0.0,
        "/v2/health": 0.0,
        "/v2/verify/credential": 0.0,
        "/v2/transfer/quote": 0.0,
        "/api/v1/prices": 0.0,  # Marketplace free tier
    }

    def __init__(self, max_rpm: int = 90):
        self.max_rpm = max_rpm
        self._call_times: List[float] = []
        self.total_cost_usd = 0.0
        self.call_count = 0

    def _throttle(self):
        """Enforce rate limit by sleeping if needed."""
        now = time.time()
        self._call_times = [t for t in self._call_times if now - t < 60]
        if len(self._call_times) >= self.max_rpm:
            sleep_time = 60 - (now - self._call_times[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._call_times.append(time.time())
        self.call_count += 1

    def _track_cost(self, endpoint: str):
        for path, cost in self.COSTS.items():
            if path in endpoint:
                self.total_cost_usd += cost
                return

    def _headers(self) -> dict:
        return {
            "X-Agent-Id": self.AGENT_ID,
            "Content-Type": "application/json",
        }

    async def _get(self, url: str, params: dict = None, retries: int = 3) -> Optional[dict]:
        self._throttle()
        self._track_cost(url)
        try:
            import aiohttp
            for attempt in range(retries):
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(
                            url, headers=self._headers(), params=params,
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as r:
                            if r.status == 200:
                                return await r.json()
                            if r.status == 429:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            print(f"WARNING [BOApiClient]: {url} returned {r.status}")
                            return None
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        print(f"WARNING [BOApiClient]: {url} failed after {retries} retries: {e}")
            return None
        except ImportError:
            print("WARNING [BOApiClient]: aiohttp not installed")
            return None

    async def _post(self, url: str, data: dict = None, retries: int = 3) -> Optional[dict]:
        self._throttle()
        self._track_cost(url)
        try:
            import aiohttp
            for attempt in range(retries):
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.post(
                            url, headers=self._headers(), json=data or {},
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as r:
                            if r.status in (200, 201):
                                return await r.json()
                            if r.status == 429:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            print(f"WARNING [BOApiClient]: POST {url} returned {r.status}")
                            return None
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        print(f"WARNING [BOApiClient]: POST {url} failed: {e}")
            return None
        except ImportError:
            return None

    # --- BlindOracle Endpoints ---

    async def get_health(self) -> Optional[dict]:
        return await self._get(f"{self.BO_BASE}/v2/health")

    async def get_forecasts(self, limit: int = 50) -> List[dict]:
        data = await self._get(f"{self.BO_BASE}/v2/forecasts", {"limit": str(limit)})
        if data is None:
            return []
        return data if isinstance(data, list) else data.get("forecasts", data.get("data", []))

    async def get_forecast(self, market_id: str) -> Optional[dict]:
        return await self._get(f"{self.BO_BASE}/v2/forecasts/{market_id}")

    async def get_balance(self) -> Optional[dict]:
        return await self._get(f"{self.BO_BASE}/v2/account/balance")

    async def get_transfer_quote(self, from_rail: str, to_rail: str, amount: str) -> Optional[dict]:
        return await self._get(f"{self.BO_BASE}/v2/transfer/quote", {
            "from": from_rail, "to": to_rail, "amount": amount
        })

    async def submit_position(self, market_id: str, side: str, amount: float,
                              commitment_hash: str = "") -> Optional[dict]:
        return await self._post(f"{self.BO_BASE}/v2/positions", {
            "market_id": market_id, "side": side,
            "amount": str(amount), "commitment_hash": commitment_hash,
        })

    # --- Chainlink Marketplace Endpoints ---

    async def get_chainlink_price(self, pair: str, network: str = "ethereum") -> Optional[dict]:
        return await self._get(
            f"{self.CL_BASE}/api/v1/prices/{pair}",
            {"network": network},
        )

    # --- Cost Summary ---

    def get_cost_summary(self, btc_price: float = 85000.0) -> DualAmount:
        return DualAmount.from_usd(self.total_cost_usd, btc_price)
