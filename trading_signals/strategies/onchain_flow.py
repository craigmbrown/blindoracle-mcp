"""
Strategy 9: On-Chain Flow — Monitor blockchain gas prices and block fullness
as a proxy for network demand and activity.

REQ-RQ030-003: Blockchain flow analysis strategy
BLP-031: Self-Improvement through on-chain signal integration

Signal logic:
- Fetch Ethereum gas price + block fullness via free public RPCs (verified live)
- Also fetch Base L2 block fullness for L2 activity signal
- High gas = high demand = bullish. Compare with price momentum.
- Block fullness >95% = network congestion = potential volatility
- Fall back to RSI when RPC data unavailable
"""

from typing import List, Optional

from trading_signals.strategies import Strategy, StrategyRegistry
from trading_signals.strategies.web_data_client import WebDataClient
from trading_signals.indicators import TechnicalIndicators


@StrategyRegistry.register
class OnchainFlowStrategy(Strategy):
    """Trade based on Ethereum/Base on-chain activity signals."""

    name = "onchain_flow"
    description = "Trade on Ethereum gas and block fullness as demand proxy"

    def __init__(self, config: dict):
        super().__init__(config)
        self.web_client = WebDataClient()
        self.indicators = TechnicalIndicators()
        # Track gas price history for spike detection
        self._gas_history: List[int] = []

    async def fetch_data(self, asset: str, **kwargs) -> dict:
        """Fetch on-chain metrics from Ethereum and Base RPCs."""
        gas_price = await self.web_client.get_eth_gas_price()
        eth_fullness = await self.web_client.get_eth_block_fullness()
        base_fullness = await self.web_client.get_base_block_fullness()

        # Track gas history for moving average
        if gas_price is not None:
            self._gas_history.append(gas_price)
            # Keep last 24 readings (~2h at 5-min intervals)
            self._gas_history = self._gas_history[-24:]

        # Calculate gas spike ratio vs recent average
        gas_spike_ratio = 1.0
        if gas_price and len(self._gas_history) >= 2:
            avg_gas = sum(self._gas_history[:-1]) / len(self._gas_history[:-1])
            if avg_gas > 0:
                gas_spike_ratio = gas_price / avg_gas

        return {
            "asset": asset,
            "gas_price_gwei": gas_price,
            "eth_block_fullness": eth_fullness,
            "base_block_fullness": base_fullness,
            "gas_spike_ratio": gas_spike_ratio,
            "gas_history_length": len(self._gas_history),
        }

    def generate_signal(self, data: dict, prices: List[float]) -> Optional[str]:
        """Generate signal from on-chain flow metrics."""
        cfg = self.get_config_section()
        gas_spike_threshold = cfg.get("gas_spike_threshold", 2.0)
        fullness_threshold = cfg.get("block_fullness_threshold", 0.95)

        if not prices or len(prices) < 30:
            return None

        gas_price = data.get("gas_price_gwei")
        eth_fullness = data.get("eth_block_fullness")
        gas_spike = data.get("gas_spike_ratio", 1.0)

        # No on-chain data available, fall back to RSI
        if gas_price is None and eth_fullness is None:
            rsi = self.indicators.calculate_rsi(prices)
            return rsi.signal if rsi and rsi.signal in ("buy", "sell") else None

        # Calculate price momentum for confirmation
        if len(prices) >= 10:
            momentum = (prices[-1] - prices[-10]) / prices[-10]
        else:
            momentum = 0.0

        # Signal 1: Gas spike (high demand burst)
        if gas_spike > gas_spike_threshold:
            # High gas spike = sudden demand increase
            if momentum > 0:
                # Network demand rising + price rising = bullish
                return "buy"
            elif momentum < -0.02:
                # High gas during selloff could mean panic liquidations
                return "sell"

        # Signal 2: Block fullness (sustained congestion)
        if eth_fullness is not None and eth_fullness > fullness_threshold:
            # Blocks nearly full = high network utilization
            if momentum > 0.01:
                return "buy"

        # Signal 3: Low activity divergence
        if gas_spike < 0.5 and gas_price is not None:
            # Abnormally low gas = quiet period
            # If price is still rising during quiet period, might be manipulation
            if momentum > 0.03:
                rsi = self.indicators.calculate_rsi(prices)
                if rsi and rsi.signal == "sell":
                    return "sell"  # Divergence: low activity but rising price

        # No strong signal from on-chain data
        return None

    def get_config_section(self) -> dict:
        defaults = {
            "enabled": True,
            "gas_spike_threshold": 2.0,
            "block_fullness_threshold": 0.95,
        }
        section = self.config.get("onchain_flow", {})
        defaults.update(section)
        return defaults
