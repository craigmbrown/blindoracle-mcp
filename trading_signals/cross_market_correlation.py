# trading_signals/cross_market_correlation.py
# REQ-SIGNALS-008: Cross-market correlation between prediction markets and crypto prices
# BLP-004: Alignment — ground signals in measurable market relationships

"""
Pearson correlation between prediction market probability changes and crypto price returns.

Design decision: 30-day rolling Pearson on daily series. Simple, interpretable,
computationally cheap. ML models are explicitly out of scope (plan exclusion).

Data sources:
- Price returns: CoinGeckoPriceProvider (already used by SignalGenerator)
- Probability changes: ProbabilityMomentumTracker (already used by SignalGenerator)

Returns None when either series has fewer than 10 data points (insufficient for a
meaningful correlation estimate — avoids spurious results on sparse data).
"""

import math
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """
    Calculate Pearson correlation coefficient for two equal-length lists.

    Returns None if the denominator is zero (constant series) or if
    either list has fewer than 2 elements.

    REQ-SIGNALS-008: Core calculation used by CrossMarketCorrelation.
    """
    n = len(x)
    if n < 2 or n != len(y):
        return None

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if denom_x == 0.0 or denom_y == 0.0:
        return None

    return max(-1.0, min(1.0, num / (denom_x * denom_y)))


def _to_returns(prices: List[float]) -> List[float]:
    """
    Convert a price series to a log-return series.

    log(p[t] / p[t-1]) avoids the scale problem when correlating assets
    with very different price magnitudes.
    """
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
        else:
            returns.append(0.0)
    return returns


def _to_changes(probabilities: List[float]) -> List[float]:
    """
    Convert a probability series to a first-difference series.

    p[t] - p[t-1] so the correlation is between *changes* in probability
    and *returns* in price — not levels, which are spuriously correlated.
    """
    return [probabilities[i] - probabilities[i - 1] for i in range(1, len(probabilities))]


class CrossMarketCorrelation:
    """
    REQ-SIGNALS-008: Correlate prediction market probability timeseries with crypto prices.

    Usage:
        cmc = CrossMarketCorrelation()
        corr = await cmc.calculate("BTC", market_id="btc-above-70k-by-dec-2026")
        # Returns float in [-1, 1] or None if insufficient data
    """

    MIN_DATA_POINTS = 10  # Minimum aligned series length to compute correlation

    def __init__(self) -> None:
        # Lazy imports to avoid hard dependency at module load time
        pass

    async def calculate(
        self,
        asset: str,
        market_id: str,
        window_days: int = 30,
    ) -> Optional[float]:
        """
        Calculate Pearson correlation between probability changes and price returns.

        Args:
            asset: Crypto asset ticker, e.g. "BTC".
            market_id: Prediction market identifier (platform-specific).
            window_days: Rolling window in days (default 30).

        Returns:
            Pearson r in [-1.0, 1.0], or None if data is insufficient.

        REQ-SIGNALS-008: Populates TradingSignal.cross_market_correlation field.
        BLP-004: Alignment — ensures signal is grounded in observable correlations.
        """
        prices, probabilities = await self._fetch_aligned_series(asset, market_id, window_days)

        if len(prices) < self.MIN_DATA_POINTS or len(probabilities) < self.MIN_DATA_POINTS:
            print(
                f"[CrossMarketCorrelation] Insufficient data for {asset}/{market_id}: "
                f"prices={len(prices)}, probs={len(probabilities)}"
            )
            return None

        # Align series lengths (take the shorter)
        min_len = min(len(prices), len(probabilities))
        prices = prices[-min_len:]
        probabilities = probabilities[-min_len:]

        returns = _to_returns(prices)
        changes = _to_changes(probabilities)

        # After differencing, series are 1 element shorter — re-align
        min_diff_len = min(len(returns), len(changes))
        if min_diff_len < self.MIN_DATA_POINTS:
            return None

        returns = returns[-min_diff_len:]
        changes = changes[-min_diff_len:]

        corr = _pearson(returns, changes)
        if corr is not None:
            print(
                f"[CrossMarketCorrelation] {asset}/{market_id} "
                f"r={corr:.4f} over {window_days}d window"
            )
        return corr

    async def calculate_from_series(
        self,
        price_series: List[float],
        probability_series: List[float],
    ) -> Optional[float]:
        """
        Calculate correlation from pre-fetched series (used in tests and batch jobs).

        REQ-SIGNALS-008: Exposed so scheduler can pre-fetch data once and reuse.
        """
        if (
            len(price_series) < self.MIN_DATA_POINTS
            or len(probability_series) < self.MIN_DATA_POINTS
        ):
            return None

        min_len = min(len(price_series), len(probability_series))
        prices = price_series[-min_len:]
        probs = probability_series[-min_len:]

        returns = _to_returns(prices)
        changes = _to_changes(probs)

        min_diff_len = min(len(returns), len(changes))
        if min_diff_len < self.MIN_DATA_POINTS:
            return None

        return _pearson(returns[-min_diff_len:], changes[-min_diff_len:])

    async def _fetch_aligned_series(
        self, asset: str, market_id: str, window_days: int
    ) -> Tuple[List[float], List[float]]:
        """
        Fetch price and probability series for the given window.

        Returns (prices, probabilities). Either may be empty on API failure;
        callers check length before computing correlation.
        """
        prices: List[float] = []
        probabilities: List[float] = []

        # --- Fetch prices ---
        try:
            from trading_signals.signal_generator import CoinGeckoPriceProvider

            provider = CoinGeckoPriceProvider()
            prices = await provider.get_price_history(asset, days=window_days)
        except Exception as e:
            print(f"[CrossMarketCorrelation] Price fetch failed for {asset}: {e}")

        # --- Fetch probability history ---
        try:
            from trading_signals.probability_momentum import ProbabilityMomentumTracker

            tracker = ProbabilityMomentumTracker()
            momentum = await tracker.get_momentum(market_id)
            if momentum:
                # ProbabilityMomentumTracker returns a single ProbabilityChange snapshot.
                # Build a synthetic daily probability series from the change deltas
                # so we have a series to correlate with prices.
                probabilities = self._build_prob_series_from_momentum(momentum, window_days)
        except Exception as e:
            print(f"[CrossMarketCorrelation] Probability fetch failed for {market_id}: {e}")

        return prices, probabilities

    @staticmethod
    def _build_prob_series_from_momentum(momentum: object, window_days: int) -> List[float]:
        """
        Construct a minimal probability series from a ProbabilityChange snapshot.

        Since ProbabilityMomentumTracker only returns current + delta values (not a
        full history), we reconstruct a linear approximation:
          - current probability at t=0
          - back-extrapolated using available deltas

        This is a best-effort series; accuracy improves if/when the tracker is
        extended to return full history.
        """
        try:
            current = float(momentum.current_probability)
            change_1h = float(getattr(momentum, "change_1h", 0.0))
            change_24h = float(getattr(momentum, "change_24h", 0.0))
            change_7d = float(getattr(momentum, "change_7d", 0.0))

            if window_days <= 1:
                # Intra-day: use hourly deltas
                n = min(window_days * 24, 24)
                step = change_1h / max(n, 1)
                return [max(0.0, min(1.0, current - step * i)) for i in range(n, -1, -1)]
            elif window_days <= 7:
                # Up to a week: use daily deltas
                n = window_days
                step = change_24h / max(n, 1)
                return [max(0.0, min(1.0, current - step * i)) for i in range(n, -1, -1)]
            else:
                # Longer window: use weekly delta to extrapolate
                n = window_days
                step = change_7d / 7.0  # weekly delta → per-day
                return [max(0.0, min(1.0, current - step * i)) for i in range(n, -1, -1)]
        except Exception as e:
            print(f"[CrossMarketCorrelation] Failed to build prob series: {e}")
            return []
