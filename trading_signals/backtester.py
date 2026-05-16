# trading_signals/backtester.py
# REQ-SIGNALS-005: Strategy backtesting
# REQ-AUTORESEARCH-002: Real price provider for backtesting
# BLP-031: Self-Improvement through historical validation

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from .signal_generator import SignalGenerator, TradingSignal, CoinGeckoPriceProvider


# --- Dual Currency Tracking ---

@dataclass
class DualAmount:
    """USD + sats dual-currency amount for Lightning/Fedimint readiness."""
    usd: float
    sats: int  # always integer satoshis
    btc_price_at_conversion: float  # audit trail
    timestamp: str

    @staticmethod
    def from_usd(usd: float, btc_price: float) -> "DualAmount":
        sats = int((usd / btc_price) * 100_000_000) if btc_price > 0 else 0
        return DualAmount(
            usd=usd, sats=sats,
            btc_price_at_conversion=btc_price,
            timestamp=datetime.utcnow().isoformat(),
        )

    def to_dict(self) -> dict:
        return {
            "usd": round(self.usd, 2),
            "sats": self.sats,
            "btc_price": round(self.btc_price_at_conversion, 2),
        }


def usd_to_sats(usd: float, btc_price: float) -> int:
    """Convert USD to satoshis. 1 BTC = 100,000,000 sats."""
    if btc_price <= 0:
        return 0
    return int((usd / btc_price) * 100_000_000)


def sats_to_usd(sats: int, btc_price: float) -> float:
    return (sats / 100_000_000) * btc_price


async def get_current_btc_price() -> float:
    """Via CoinGeckoPriceProvider — already exists."""
    provider = CoinGeckoPriceProvider()
    prices = await provider.get_price_history("BTC", days=1)
    return prices[-1] if prices else 0.0


# --- Price Providers ---

class MockPriceProvider:
    """Legacy mock provider — kept for backwards compatibility."""
    async def get_price_history_for_period(
        self, asset: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        dates = pd.date_range(start, end, freq="h")

        if asset == "BTC":
            price = 60000
            prices = []
            for _ in range(len(dates)):
                price += np.random.normal(0, 300)
                prices.append(price)
            return pd.DataFrame({"timestamp": dates, "price": prices}).set_index("timestamp")
        return pd.DataFrame()


class RealPriceProvider:
    """Combines CoinGecko + BO API for backtesting with real market data.

    REQ-AUTORESEARCH-002: Replace random walk with real historical prices.
    Caches per-asset price data to avoid CoinGecko 429 rate limits.
    """

    # Class-level cache: {(asset, days): (prices_list, fetch_timestamp)}
    _price_cache: dict = {}
    _CACHE_TTL = 3600  # 1 hour cache

    def __init__(self):
        self.coingecko = CoinGeckoPriceProvider()
        self.bo_base_url = "https://api.craigmbrown.com"

    async def get_price_history_for_period(
        self, asset: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Fetch real CoinGecko data with caching to avoid rate limits."""
        import time as _time
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        days = max(1, (end - start).days + 1)

        # Check cache first
        cache_key = (asset.upper(), days)
        now = _time.time()
        if cache_key in self._price_cache:
            cached_prices, cached_at = self._price_cache[cache_key]
            if now - cached_at < self._CACHE_TTL and cached_prices:
                prices = cached_prices
                n = len(prices)
                timestamps = pd.date_range(start, end, periods=n)
                return pd.DataFrame({"timestamp": timestamps, "price": prices}).set_index("timestamp")

        # Fetch from CoinGecko with retry + backoff
        prices = []
        for attempt in range(3):
            prices = await self.coingecko.get_price_history(asset, days=days)
            if prices:
                break
            # Backoff on rate limit
            import asyncio
            await asyncio.sleep(2 ** attempt * 5)  # 5s, 10s, 20s

        if not prices:
            print(f"WARNING [RealPriceProvider]: No price data for {asset} after 3 retries")
            return pd.DataFrame()

        # Cache the result
        self._price_cache[cache_key] = (prices, now)

        n = len(prices)
        timestamps = pd.date_range(start, end, periods=n)
        df = pd.DataFrame({"timestamp": timestamps, "price": prices}).set_index("timestamp")
        return df

    async def get_market_resolutions(self) -> List[dict]:
        """GET /v2/accuracy — free endpoint, no auth needed."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.bo_base_url}/v2/accuracy",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data if isinstance(data, list) else data.get("results", [])
                    print(f"WARNING [RealPriceProvider]: BO /v2/accuracy returned {r.status}")
                    return []
        except Exception as e:
            print(f"WARNING [RealPriceProvider]: BO /v2/accuracy failed: {e}")
            return []

    async def get_forecast_history(self, market_id: str) -> Optional[dict]:
        """GET /v2/forecasts/{id} — historical probability curve."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.bo_base_url}/v2/forecasts/{market_id}",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        return await r.json()
                    return None
        except Exception as e:
            print(f"WARNING [RealPriceProvider]: BO forecast fetch failed: {e}")
            return None

    async def get_active_forecasts(self, limit: int = 50) -> List[dict]:
        """GET /v2/forecasts — active market forecasts."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.bo_base_url}/v2/forecasts",
                    params={"limit": str(limit)},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data if isinstance(data, list) else data.get("forecasts", [])
                    return []
        except Exception as e:
            print(f"WARNING [RealPriceProvider]: BO /v2/forecasts failed: {e}")
            return []


# --- Backtest Results ---

@dataclass
class BacktestResult:
    """Result of strategy backtest — dual currency tracking."""

    strategy_name: str
    period_start: str
    period_end: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    # Dual currency fields
    total_return_dual: Optional[DualAmount] = None
    max_drawdown_dual: Optional[DualAmount] = None
    per_trade_pnl: List[DualAmount] = field(default_factory=list)
    config_used: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "strategy_name": self.strategy_name,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_return_usd": round(self.total_return, 2),
            "max_drawdown_usd": round(self.max_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
        }
        if self.total_return_dual:
            d["total_return_sats"] = self.total_return_dual.sats
        if self.max_drawdown_dual:
            d["max_drawdown_sats"] = self.max_drawdown_dual.sats
        return d


# --- Backtester ---

class Backtester:
    """Backtest trading signals against historical data.

    Supports both MockPriceProvider (legacy) and RealPriceProvider (autoresearch).
    """

    def __init__(self, use_real_data: bool = False):
        self.price_provider = RealPriceProvider() if use_real_data else MockPriceProvider()

    async def run_backtest(
        self,
        strategy: SignalGenerator,
        asset: str,
        start_date: str,
        end_date: str,
        config: Optional[dict] = None,
    ) -> BacktestResult:
        """Run backtest for a strategy over a historical period."""

        historical_data = await self.price_provider.get_price_history_for_period(
            asset, start_date, end_date
        )
        if historical_data.empty:
            raise ValueError(f"Could not fetch historical data for {asset} backtest")

        # Get stops from config if available
        stops = (config or {}).get("stops", {})
        trailing_stop_pct = stops.get("trailing_stop_pct", 0.05)
        max_loss_pct = stops.get("max_loss_pct", 0.08)

        trades = []
        position = 0  # -1 for short, 1 for long, 0 for neutral
        entry_price = 0.0
        peak_price = 0.0  # for trailing stop

        # Use price history directly for signal generation (avoid API calls per tick)
        all_prices = historical_data["price"].tolist()

        for i in range(30, len(historical_data)):  # need min 30 bars for indicators
            prices_so_far = all_prices[:i]
            current_price = all_prices[i]

            # Generate signal from price history slice (no API call)
            signal = strategy.generate_signal_from_prices(prices_so_far)

            # Apply trailing stop
            if position == 1 and current_price > peak_price:
                peak_price = current_price
            elif position == -1 and (peak_price == 0 or current_price < peak_price):
                peak_price = current_price

            # Check stop losses
            if position == 1:
                # Trailing stop for long
                if peak_price > 0 and (peak_price - current_price) / peak_price > trailing_stop_pct:
                    trades.append(current_price - entry_price)
                    position = 0
                    entry_price = 0
                    peak_price = 0
                    continue
                # Max loss stop
                if entry_price > 0 and (entry_price - current_price) / entry_price > max_loss_pct:
                    trades.append(current_price - entry_price)
                    position = 0
                    entry_price = 0
                    peak_price = 0
                    continue
            elif position == -1:
                # Trailing stop for short
                if peak_price > 0 and (current_price - peak_price) / peak_price > trailing_stop_pct:
                    trades.append(entry_price - current_price)
                    position = 0
                    entry_price = 0
                    peak_price = 0
                    continue
                # Max loss stop
                if entry_price > 0 and (current_price - entry_price) / entry_price > max_loss_pct:
                    trades.append(entry_price - current_price)
                    position = 0
                    entry_price = 0
                    peak_price = 0
                    continue

            if not signal:
                continue

            if position == 0:
                if signal == "buy":
                    position = 1
                    entry_price = current_price
                    peak_price = current_price
                elif signal == "sell":
                    position = -1
                    entry_price = current_price
                    peak_price = current_price
            elif position == 1 and signal == "sell":
                trades.append(current_price - entry_price)
                position = -1
                entry_price = current_price
                peak_price = current_price
            elif position == -1 and signal == "buy":
                trades.append(entry_price - current_price)
                position = 1
                entry_price = current_price
                peak_price = current_price

        # Calculate results
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t > 0])
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        returns = pd.Series(trades).cumsum() if trades else pd.Series(dtype=float)
        total_return = float(returns.iloc[-1]) if not returns.empty else 0.0
        max_drawdown = float((returns.cummax() - returns).max()) if not returns.empty else 0.0

        sharpe_ratio = 0.0
        if not returns.empty and len(returns) > 1:
            std = returns.std()
            if std > 0:
                sharpe_ratio = float(returns.mean() / std)

        # Build dual-currency amounts
        btc_price = all_prices[-1] if all_prices else 0.0  # use latest price as proxy
        total_return_dual = DualAmount.from_usd(total_return, btc_price)
        max_drawdown_dual = DualAmount.from_usd(max_drawdown, btc_price)
        per_trade_pnl = [DualAmount.from_usd(t, btc_price) for t in trades]

        return BacktestResult(
            strategy_name=strategy.__class__.__name__,
            period_start=start_date,
            period_end=end_date,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            total_return_dual=total_return_dual,
            max_drawdown_dual=max_drawdown_dual,
            per_trade_pnl=per_trade_pnl,
            config_used=config,
        )

    async def compare_strategies(
        self, strategies: List[SignalGenerator], asset: str, start_date: str, end_date: str
    ) -> List[BacktestResult]:
        """Compare multiple strategies."""
        results = []
        for strategy in strategies:
            result = await self.run_backtest(strategy, asset, start_date, end_date)
            results.append(result)
        return results
