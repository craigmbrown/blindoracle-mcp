"""
Strategy 3: Market Making — Provide two-sided liquidity to BO markets,
earning spread from the AMM.

REQ-AUTORESEARCH-008: Market Making strategy
BLP-031: Self-Improvement through spread optimization

Signal logic:
- Identify markets with sufficient volume but wide spread
- Place simulated bid/ask around midpoint
- Track inventory: if skewed, adjust quotes
- Exit when spread compresses or market approaches close
- P&L = earned spread - adverse selection losses
"""

from typing import Dict, List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.bo_api_client import BOApiClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class MarketMakerStrategy(Strategy):
    """Market Making: earn spread by providing two-sided AMM liquidity."""

    name = "market_maker"
    description = "Provide liquidity to BO markets, earning spread from AMM"

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = BOApiClient()
        self.indicators = TechnicalIndicators()
        # Simulated inventory tracking
        self._inventory: float = 0.0  # positive = long, negative = short
        self._trade_count: int = 0
        self._spread_earned: float = 0.0

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch market state for spread analysis."""
        data = {
            "asset": asset,
            "markets": [],
            "avg_spread": 0.0,
            "widest_spread": 0.0,
        }

        forecasts = await self.client.get_forecasts(limit=30)
        if forecasts:
            for f in forecasts:
                prob = f.get("probability", {})
                if isinstance(prob, dict):
                    yes = prob.get("yes", 0.5)
                    no = prob.get("no", 0.5)
                else:
                    yes, no = 0.5, 0.5

                # Spread = 1 - (yes + no), or use bid/ask gap
                spread = abs(1.0 - (yes + no))
                if spread < 0.001:
                    # If perfectly balanced, infer spread from liquidity
                    spread = 0.02  # default 2%

                data["markets"].append({
                    "id": f.get("market_id", f.get("id", "")),
                    "question": f.get("question", ""),
                    "yes_prob": yes,
                    "no_prob": no,
                    "spread": spread,
                    "volume": f.get("volume", 0),
                })

            if data["markets"]:
                spreads = [m["spread"] for m in data["markets"]]
                data["avg_spread"] = sum(spreads) / len(spreads)
                data["widest_spread"] = max(spreads)

        return data

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate market-making signal based on spread and inventory.

        For backtesting with price data, we simulate market making by:
        - Buying when price dips (filling our bid)
        - Selling when price rises (filling our ask)
        - Managing inventory to stay balanced
        """
        cfg = self.get_config_section()
        target_spread = cfg.get("target_spread", 0.04)
        max_skew = cfg.get("max_inventory_skew", 0.70)

        if not prices or len(prices) < 20:
            return None

        current = prices[-1]
        prev = prices[-2] if len(prices) > 1 else current

        # Calculate short-term mean (our "fair value")
        window = min(20, len(prices))
        fair_value = sum(prices[-window:]) / window

        # Our simulated bid/ask
        half_spread = target_spread / 2
        bid = fair_value * (1 - half_spread)
        ask = fair_value * (1 + half_spread)

        # Check if price moved into our bid or ask
        price_return = (current - prev) / prev if prev > 0 else 0

        # Inventory management
        inventory_ratio = self._inventory / max(abs(self._inventory) + 1, 1)

        if current <= bid and inventory_ratio < max_skew:
            # Price hit our bid — we buy
            self._inventory += 1
            self._trade_count += 1
            self._spread_earned += half_spread * current
            return "buy"

        elif current >= ask and inventory_ratio > -max_skew:
            # Price hit our ask — we sell
            self._inventory -= 1
            self._trade_count += 1
            self._spread_earned += half_spread * current
            return "sell"

        # Inventory reduction: if skewed, lean into reducing
        if abs(inventory_ratio) > max_skew:
            if self._inventory > 0:
                self._inventory -= 0.5
                return "sell"  # reduce long inventory
            else:
                self._inventory += 0.5
                return "buy"  # reduce short inventory

        # Volatility check: widen spread in high vol (don't trade)
        vol = self._recent_volatility(prices)
        if vol > target_spread * 2:
            return None  # too volatile, step back

        return None

    def _recent_volatility(self, prices: List[float], window: int = 10) -> float:
        if len(prices) < window + 1:
            return 0.0
        recent = prices[-window:]
        returns = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "target_spread": 0.04,
            "min_spread": 0.01,
            "max_inventory_skew": 0.70,
            "max_markets": 5,
            "min_volume_usd": 500,
        }
        section = self.config.get("market_maker", {})
        defaults.update(section)
        return defaults
