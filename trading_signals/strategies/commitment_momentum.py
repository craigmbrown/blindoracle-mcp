"""
Strategy 2: Commitment Momentum — Infer smart money direction from
position commitment velocity via BO /v2/positions.

REQ-AUTORESEARCH-007: Commitment Momentum strategy
BLP-031: Self-Improvement through flow analysis

Signal logic:
- Track commitment volume (SHA256 hashes) per time window
- Sudden spike in commitments = "smart money entering"
- Combine velocity with price momentum for direction
- velocity > threshold → BUY (follow smart money)
- velocity drops below fade → SELL (smart money exiting)
"""

import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.bo_api_client import BOApiClient
from trading_signals.indicators import TechnicalIndicators


# Commitment history file for backtesting
HISTORY_FILE = Path(__file__).parent.parent.parent.parent / "data" / "commitment_history.jsonl"


@StrategyRegistry.register
class CommitmentMomentumStrategy(Strategy):
    """Commitment Momentum: smart money flow from position velocity."""

    name = "commitment_momentum"
    description = "Infer smart money direction from commitment velocity spikes"

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = BOApiClient()
        self.indicators = TechnicalIndicators()
        self._commitment_history: List[dict] = []
        self._load_history()

    def _load_history(self):
        """Load persisted commitment history."""
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    self._commitment_history = [
                        json.loads(line) for line in f if line.strip()
                    ]
            except Exception:
                self._commitment_history = []

    def _save_entry(self, entry: dict):
        """Append a commitment entry to history."""
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._commitment_history.append(entry)

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch active forecasts and simulate commitment tracking.

        In production, this would poll /v2/positions for new commitment hashes.
        For backtesting, we generate synthetic commitment counts based on
        price volatility (higher volatility = more commitments).
        """
        data = {
            "asset": asset,
            "commitments_1h": 0,
            "commitments_24h": 0,
            "avg_commitments_24h": 0,
            "velocity": 1.0,
        }

        # Try to get live forecast data for market activity signals
        forecasts = await self.client.get_forecasts(limit=20)
        if forecasts:
            # Count active markets as proxy for commitment activity
            active = len([f for f in forecasts if f.get("status") == "active"])
            data["commitments_1h"] = active
            data["commitments_24h"] = active * 12  # rough estimate
            data["avg_commitments_24h"] = max(active * 10, 1)

        return data

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from commitment velocity + price momentum."""
        cfg = self.get_config_section()
        velocity_threshold = cfg.get("velocity_threshold", 3.0)
        fade_threshold = cfg.get("fade_threshold", 0.3)
        min_commitments = cfg.get("min_commitments", 5)

        if not prices or len(prices) < 30:
            return None

        # Calculate velocity from price data volatility as proxy for commitment flow
        # Higher volatility = more market activity = more commitments
        recent_vol = self._recent_volatility(prices, window=12)
        avg_vol = self._recent_volatility(prices, window=72)

        if avg_vol > 0:
            velocity = recent_vol / avg_vol
        else:
            velocity = 1.0

        # Use API data if available
        api_velocity = 1.0
        if data.get("avg_commitments_24h", 0) > 0:
            api_velocity = data.get("commitments_1h", 0) / max(data["avg_commitments_24h"] / 24, 0.1)

        # Blend velocities (API data gets higher weight when available)
        if data.get("commitments_1h", 0) >= min_commitments:
            velocity = 0.4 * velocity + 0.6 * api_velocity
        # else: stick with price-based velocity

        # Price momentum for direction
        momentum = self._price_momentum(prices)

        # RSI confirmation
        rsi = self.indicators.calculate_rsi(prices)
        rsi_signal = rsi.signal if rsi else "hold"

        # Signal generation
        if velocity > velocity_threshold:
            # High activity — follow smart money direction
            if momentum > 0 and rsi_signal != "sell":
                return "buy"
            elif momentum < 0 and rsi_signal != "buy":
                return "sell"
        elif velocity < fade_threshold:
            # Low activity — mean revert
            if momentum > 0.02:  # extended up, no volume → sell
                return "sell"
            elif momentum < -0.02:  # extended down, no volume → buy
                return "buy"

        return None

    def _recent_volatility(self, prices: List[float], window: int = 12) -> float:
        """Calculate recent price volatility (std of returns)."""
        if len(prices) < window + 1:
            return 0.0
        recent = prices[-window:]
        returns = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    def _price_momentum(self, prices: List[float]) -> float:
        if len(prices) < 10:
            return 0.0
        return (prices[-1] - prices[-10]) / prices[-10]

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "velocity_threshold": 3.0,
            "fade_threshold": 0.3,
            "lookback_hours": 24,
            "min_commitments": 5,
        }
        section = self.config.get("commitment_momentum", {})
        defaults.update(section)
        return defaults
