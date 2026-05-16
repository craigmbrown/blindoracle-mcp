# New file: trading_signals/signal_generator.py
# REQ-SIGNALS-003: Combined signal generation
# BLP-031: Self-Improvement through accuracy tracking

import os
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
from datetime import datetime
import uuid

from .indicators import TechnicalIndicators, IndicatorResult
from .probability_momentum import ProbabilityMomentumTracker, ProbabilityChange
from .signal_store import SignalStore
from .cross_market_correlation import CrossMarketCorrelation


# Price provider that fetches real data from CoinGecko API
class CoinGeckoPriceProvider:
    """Fetches real historical price data from CoinGecko's free API.

    Falls back to returning an empty list (not fake data) if the API is
    unavailable, ensuring signal generation only runs on real data.
    """

    COINGECKO_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "LINK": "chainlink",
        "SOL": "solana",
        "AVAX": "avalanche-2",
        "MATIC": "matic-network",
        "DOT": "polkadot",
        "ADA": "cardano",
    }

    async def get_price_history(self, asset: str, days: int = 90) -> List[float]:
        """Fetch real hourly/daily price history from CoinGecko.

        Returns empty list if asset is unsupported or API fails.
        No synthetic/random data is ever generated.
        """
        coin_id = self.COINGECKO_IDS.get(asset.upper())
        if not coin_id:
            print(f"WARNING [CoinGeckoPriceProvider]: Unknown asset '{asset}' — no price history available")
            return []

        try:
            import aiohttp
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            params = {"vs_currency": "usd", "days": str(days)}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        prices = [point[1] for point in data.get("prices", [])]
                        if prices:
                            print(f"SUCCESS [CoinGeckoPriceProvider]: Got {len(prices)} price points for {asset}")
                            return prices
                        print(f"WARNING [CoinGeckoPriceProvider]: Empty price data for {asset}")
                        return []
                    else:
                        print(f"WARNING [CoinGeckoPriceProvider]: CoinGecko returned {resp.status} for {asset}")
                        return []
        except ImportError:
            print("WARNING [CoinGeckoPriceProvider]: aiohttp not installed — cannot fetch real prices")
            return []
        except Exception as e:
            print(f"WARNING [CoinGeckoPriceProvider]: Failed to fetch {asset} prices: {e}")
            return []


@dataclass
class TradingSignal:
    """Generated trading signal"""

    signal_id: str
    timestamp: str
    asset: str
    signal_type: str  # "buy", "sell", "hold"
    confidence: float  # 0-100

    # Supporting data
    technical_signals: Dict[str, IndicatorResult]
    probability_momentum: Optional[ProbabilityChange]
    cross_market_correlation: Optional[float]

    # Metadata
    reasoning: str
    risk_level: str  # "low", "medium", "high"
    suggested_position_size: float  # 0-1 (percentage of portfolio)


def load_strategy_config(config_path: Optional[str] = None) -> dict:
    """Load strategy config from YAML file, with sensible defaults."""
    defaults = {
        "signal_weights": {"RSI": 1.0, "MACD": 1.0, "BollingerBands": 0.8, "momentum": 1.2},
        "thresholds": {
            "buy_threshold": 0.3, "sell_threshold": -0.3,
            "rsi_overbought": 70, "rsi_oversold": 30, "momentum_trigger": 20,
        },
        "position_sizing": {"high_risk_max": 0.10, "medium_risk_max": 0.05, "low_risk_max": 0.02},
        "stops": {"trailing_stop_pct": 0.05, "max_loss_pct": 0.08},
    }
    if not config_path:
        return defaults
    try:
        import yaml
        with open(config_path, "r") as f:
            loaded = yaml.safe_load(f) or {}
        # Merge loaded over defaults
        for key in defaults:
            if key in loaded:
                if isinstance(defaults[key], dict):
                    defaults[key].update(loaded[key])
                else:
                    defaults[key] = loaded[key]
        return defaults
    except Exception as e:
        print(f"WARNING [load_strategy_config]: Failed to load {config_path}: {e}")
        return defaults


class SignalGenerator:
    """Generate trading signals from multiple data sources.

    REQ-AUTORESEARCH-003: Accepts config_path to load weights/thresholds from YAML.
    """

    def __init__(self, platform: str = "polymarket", config_path: Optional[str] = None,
                 config_dict: Optional[dict] = None,
                 signal_store: Optional[SignalStore] = None,
                 auto_save: bool = True):
        self.indicators = TechnicalIndicators()
        self.momentum_tracker = ProbabilityMomentumTracker(platform=platform)
        self.price_provider = CoinGeckoPriceProvider()
        self.correlation_calc = CrossMarketCorrelation()
        self.signal_history: List[TradingSignal] = []
        # REQ-SIGNALS-005b: Persistent store for accuracy tracking
        self._store = signal_store  # None = lazy-init on first signal
        self._auto_save = auto_save  # Set False for dry-run / test modes
        # Load config: explicit dict > file path > defaults
        if config_dict:
            self.config = config_dict
        else:
            # Auto-detect default strategy_config.yaml adjacent to this file
            if config_path is None:
                _default_cfg = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "strategy_config.yaml"
                )
                if os.path.exists(_default_cfg):
                    config_path = _default_cfg
            self.config = load_strategy_config(config_path)

    def _get_store(self) -> SignalStore:
        """Lazy-initialize SignalStore on first use (avoids DB creation in tests that don't need it)."""
        if self._store is None:
            self._store = SignalStore()
        return self._store

    def generate_signal_from_prices(self, prices: List[float]) -> Optional[str]:
        """Generate signal direction from a price array (no API call).

        Used by the backtester to avoid CoinGecko calls per tick.
        Returns "buy", "sell", or None (hold).
        """
        if len(prices) < 30:
            return None

        tech_signals = {}
        rsi = self.indicators.calculate_rsi(prices)
        if rsi:
            tech_signals["RSI"] = rsi
        macd = self.indicators.calculate_macd(prices)
        if macd:
            tech_signals["MACD"] = macd
        bollinger = self.indicators.calculate_bollinger_bands(prices)
        if bollinger:
            tech_signals["BollingerBands"] = bollinger

        signal_type, _, _ = self.combine_signals(tech_signals, None)
        return signal_type if signal_type in ("buy", "sell") else None

    async def generate_signal(
        self, asset: str, prediction_market_id: Optional[str] = None
    ) -> Optional[TradingSignal]:
        """Generate combined trading signal"""

        price_history = await self.price_provider.get_price_history(asset)
        if not price_history:
            return None

        # 1. Calculate Technical Indicators
        tech_signals = {}
        rsi = self.indicators.calculate_rsi(price_history)
        if rsi:
            tech_signals["RSI"] = rsi

        macd = self.indicators.calculate_macd(price_history)
        if macd:
            tech_signals["MACD"] = macd

        bollinger = self.indicators.calculate_bollinger_bands(price_history)
        if bollinger:
            tech_signals["BollingerBands"] = bollinger

        # 2. Get Probability Momentum
        momentum = None
        if prediction_market_id:
            momentum = await self.momentum_tracker.get_momentum(prediction_market_id)

        # 3. Calculate cross-market correlation (REQ-SIGNALS-008)
        correlation = None
        if prediction_market_id and price_history:
            try:
                correlation = await self.correlation_calc.calculate_from_series(
                    price_series=price_history,
                    probability_series=self.correlation_calc._build_prob_series_from_momentum(
                        momentum, window_days=30
                    ) if momentum else [],
                )
            except Exception as e:
                print(f"WARNING [SignalGenerator]: Cross-market correlation failed for {asset}: {e}")

        # 4. Combine signals and calculate confidence
        final_signal, confidence, reasoning = self.combine_signals(tech_signals, momentum)

        # 5. Determine risk and position size
        risk_level = self._determine_risk(confidence)
        position_size = self._suggest_position_size(confidence, risk_level)

        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            asset=asset,
            signal_type=final_signal,
            confidence=confidence,
            technical_signals=tech_signals,
            probability_momentum=momentum,
            cross_market_correlation=correlation,  # REQ-SIGNALS-008: now populated
            reasoning=reasoning,
            risk_level=risk_level,
            suggested_position_size=position_size,
        )

        self.signal_history.append(signal)

        # REQ-SIGNALS-005b: Persist every signal to SQLite for accuracy tracking
        if self._auto_save:
            try:
                self._get_store().save_signal(signal)
            except Exception as e:
                print(f"WARNING [SignalGenerator]: Failed to save signal to store: {e}")

        return signal

    def combine_signals(
        self, technical_signals: Dict[str, IndicatorResult], momentum: Optional[ProbabilityChange]
    ) -> (str, float, str):
        """Combine various signals into a single recommendation.

        Uses configurable weights and thresholds from strategy_config.yaml.
        """

        signals = list(technical_signals.values())
        if not signals:
            return "hold", 50.0, "No technical indicators available."

        weights = self.config.get("signal_weights", {})
        thresholds = self.config.get("thresholds", {})
        buy_thresh = thresholds.get("buy_threshold", 0.3)
        sell_thresh = thresholds.get("sell_threshold", -0.3)
        momentum_trigger = thresholds.get("momentum_trigger", 20)

        # Weighted average of signals
        total_confidence = 0
        weighted_signal_sum = 0

        for s in signals:
            signal_value = 1 if s.signal == "buy" else -1 if s.signal == "sell" else 0
            # Base weight from confidence deviation, scaled by config weight
            indicator_weight = weights.get(s.name, 1.0)
            base_weight = abs(s.confidence - 50) * indicator_weight
            weighted_signal_sum += signal_value * base_weight
            total_confidence += base_weight

        if momentum:
            momentum_weight_config = weights.get("momentum", 1.2)
            momentum_signal = (
                1 if momentum.momentum_score > momentum_trigger
                else -1 if momentum.momentum_score < -momentum_trigger
                else 0
            )
            momentum_weight = abs(momentum.momentum_score) / 2 * momentum_weight_config
            weighted_signal_sum += momentum_signal * momentum_weight
            total_confidence += momentum_weight

        if total_confidence == 0:
            return "hold", 50.0, "Indicators are neutral."

        avg_signal = weighted_signal_sum / total_confidence

        if avg_signal > buy_thresh:
            final_signal = "buy"
        elif avg_signal < sell_thresh:
            final_signal = "sell"
        else:
            final_signal = "hold"

        overall_confidence = 50.0 + (avg_signal * 50.0)

        reasoning = "Combined signal based on: " + ", ".join(technical_signals.keys())
        if momentum:
            reasoning += " and prediction market momentum."

        return final_signal, min(100, max(0, overall_confidence)), reasoning

    def _determine_risk(self, confidence: float) -> str:
        if confidence > 80 or confidence < 20:
            return "high"
        elif confidence > 65 or confidence < 35:
            return "medium"
        else:
            return "low"

    def _suggest_position_size(self, confidence: float, risk_level: str) -> float:
        sizing = self.config.get("position_sizing", {})
        base_size = abs(confidence - 50) / 50  # 0 to 1
        if risk_level == "high":
            return base_size * sizing.get("high_risk_max", 0.10)
        elif risk_level == "medium":
            return base_size * sizing.get("medium_risk_max", 0.05)
        else:
            return base_size * sizing.get("low_risk_max", 0.02)

    async def generate_batch_signals(self, assets: List[str]) -> List[TradingSignal]:
        """Generate signals for multiple assets"""
        import asyncio
        tasks = [self.generate_signal(asset) for asset in assets]
        signals = await asyncio.gather(*tasks)
        return [s for s in signals if s is not None]

    def track_accuracy(self, signal_id: str, actual_outcome: str) -> None:
        """
        Track signal accuracy for self-improvement.

        REQ-SIGNALS-005b: Persists outcome to SQLite via SignalStore so
        get_signal_accuracy() MCP tool can return real metrics.
        BLP-031: Self-Improvement through historical performance measurement.
        """
        # Log to in-memory history (backward compat)
        for signal in self.signal_history:
            if signal.signal_id == signal_id:
                print(f"Signal {signal_id} ({signal.signal_type}) outcome was {actual_outcome}")
                break

        # Persist to SQLite
        try:
            self._get_store().record_outcome(signal_id, actual_outcome)
        except Exception as e:
            print(f"WARNING [SignalGenerator]: Failed to record outcome: {e}")
