# New file: trading_signals/indicators.py
# REQ-SIGNALS-001: Technical indicator calculations
# BLP-031: Self-Improvement through pattern learning

from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import pandas as pd
from datetime import datetime


@dataclass
class IndicatorResult:
    """Result of technical indicator calculation"""

    name: str
    value: float
    signal: str  # "buy", "sell", "hold"
    confidence: float  # 0-100
    timestamp: str


class TechnicalIndicators:
    """Calculate technical indicators from price data"""

    def calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[IndicatorResult]:
        """Calculate Relative Strength Index"""
        if len(prices) < period:
            return None

        series = pd.Series(prices)
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        rsi_value = rsi.iloc[-1]
        signal = "hold"
        confidence = 50
        if rsi_value > 70:
            signal = "sell"
            confidence = (rsi_value - 70) / 30 * 50 + 50
        elif rsi_value < 30:
            signal = "buy"
            confidence = (30 - rsi_value) / 30 * 50 + 50

        return IndicatorResult(
            name="RSI",
            value=rsi_value,
            signal=signal,
            confidence=min(100, confidence),
            timestamp=datetime.utcnow().isoformat(),
        )

    def calculate_macd(
        self,
        prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Optional[IndicatorResult]:
        """Calculate MACD with signal line"""
        if len(prices) < slow_period:
            return None

        series = pd.Series(prices)
        ema_fast = series.ewm(span=fast_period, adjust=False).mean()
        ema_slow = series.ewm(span=slow_period, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal_period, adjust=False).mean()

        macd_value = macd.iloc[-1]
        signal_value = signal_line.iloc[-1]

        signal = "hold"
        confidence = 50
        if macd_value > signal_value:
            signal = "buy"
            # Normalize the difference to get a confidence score
            diff = macd_value - signal_value
            confidence = min(100, 50 + (diff / series.std()) * 25)
        elif macd_value < signal_value:
            signal = "sell"
            diff = signal_value - macd_value
            confidence = min(100, 50 + (diff / series.std()) * 25)

        return IndicatorResult(
            name="MACD",
            value=macd_value,
            signal=signal,
            confidence=confidence,
            timestamp=datetime.utcnow().isoformat(),
        )

    def calculate_bollinger_bands(
        self, prices: List[float], period: int = 20, std_dev: int = 2
    ) -> Optional[IndicatorResult]:
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            return None

        series = pd.Series(prices)
        middle_band = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)

        current_price = prices[-1]
        upper = upper_band.iloc[-1]
        lower = lower_band.iloc[-1]

        signal = "hold"
        confidence = 50
        if current_price > upper:
            signal = "sell"
            confidence = min(100, 50 + ((current_price - upper) / (upper - lower)) * 50)
        elif current_price < lower:
            signal = "buy"
            confidence = min(100, 50 + ((lower - current_price) / (upper - lower)) * 50)

        return IndicatorResult(
            name="BollingerBands",
            value=current_price,
            signal=signal,
            confidence=confidence,
            timestamp=datetime.utcnow().isoformat(),
        )

    def calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return None
        return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

    def calculate_momentum(
        self, prices: List[float], period: int = 10
    ) -> Optional[IndicatorResult]:
        """Calculate price momentum"""
        if len(prices) < period + 1:
            return None

        momentum = prices[-1] - prices[-1 - period]
        signal = "hold"
        confidence = 50
        if momentum > 0:
            signal = "buy"
        elif momentum < 0:
            signal = "sell"

        # Confidence based on magnitude of change relative to price
        if prices[-1 - period] > 0:
            confidence = min(100, 50 + (abs(momentum) / prices[-1 - period]) * 100)

        return IndicatorResult(
            name="Momentum",
            value=momentum,
            signal=signal,
            confidence=confidence,
            timestamp=datetime.utcnow().isoformat(),
        )
