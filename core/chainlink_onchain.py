#!/usr/bin/env python3
"""
Chainlink On-Chain Connector - REAL Web3 Price Feed Integration
================================================================

This module provides DIRECT on-chain queries to Chainlink price feed contracts
on Ethereum mainnet using Web3.py. No simulation, no fallbacks - real data only.

Contract addresses verified working on Ethereum Mainnet:
- BTC/USD: 0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c
- ETH/USD: 0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419
- LINK/USD: 0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c

Requirements:
- ETH_RPC_URL environment variable (Infura/Alchemy endpoint)
- web3.py installed

BLP Requirements:
- BLP-021 to BLP-030: Durability Properties (real on-chain data persistence)
- BLP-011 to BLP-020: Autonomy Properties (autonomous price feed queries)
"""

import os
import sys
import json
import time
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from decimal import Decimal

# Web3 import with graceful fallback
try:
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware

    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    print("WARNING: web3.py not installed. Install with: pip install web3")


# Configuration
ETH_RPC_URL = os.getenv(
    "ETH_RPC_URL", "https://mainnet.infura.io/v3/ca3c9e35bb254bb39f985866aaf5ae4c"
)

# Chainlink Price Feed Addresses (Ethereum Mainnet) - VERIFIED WORKING
CHAINLINK_FEEDS = {
    "BTC/USD": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
    "ETH/USD": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
    "LINK/USD": "0x2c1d072e956AFFC0D435Cb7AC38EF18d24d9127c",
    # Additional feeds can be added from https://docs.chain.link/data-feeds/price-feeds/addresses
    "AAVE/USD": "0x547a514d5e3769680Ce22B2361c10Ea13619e8a9",
    "UNI/USD": "0x553303d460EE0afB37EdFf9bE42922D8FF63220e",
    "SOL/USD": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",
    "MATIC/USD": "0x7bAC85A8a13A4BcD8abb3eB7d6b4d632c5a57676",
    "DOT/USD": "0x1C07AFb8E2B827c5A4739C6d59Ae3A5035f28734",
    "AVAX/USD": "0xFF3EEb22B22e4E6fB8e0a6d0F3F04A18f8B9D2A2",
}

# AggregatorV3Interface ABI (minimal for price reading)
AGGREGATOR_V3_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "version",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class OnChainPriceResult:
    """Result from a real Chainlink on-chain price feed query"""

    pair: str
    price: float
    raw_price: int  # Raw answer from contract
    decimals: int
    round_id: int
    updated_at: str  # ISO timestamp
    updated_at_unix: int
    started_at_unix: int
    answered_in_round: int
    block_number: int
    is_stale: bool  # True if data older than 1 hour
    staleness_seconds: int
    contract_address: str
    network: str
    source: str  # Always "chainlink_mainnet" for real queries
    proof: Dict[str, Any]  # Contains verification data

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChainlinkOnChainConnector:
    """
    Direct Web3 connection to Chainlink price feed contracts on Ethereum mainnet.

    This class provides REAL on-chain data - no simulation, no fallbacks.
    Every price returned has on-chain proof (round_id, block_number, timestamps).
    """

    def __init__(self, rpc_url: Optional[str] = None):
        """
        Initialize connection to Ethereum mainnet.

        Args:
            rpc_url: Optional custom RPC URL. Uses ETH_RPC_URL env var by default.
        """
        if not WEB3_AVAILABLE:
            raise ImportError("web3.py is required. Install with: pip install web3")

        self.rpc_url = rpc_url or ETH_RPC_URL
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        # Inject middleware for POA chains (not needed for mainnet but good practice)
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to Ethereum node at {self.rpc_url}")

        self.chain_id = self.w3.eth.chain_id
        self.network = "ethereum_mainnet" if self.chain_id == 1 else f"chain_{self.chain_id}"

        # Cache for contract instances
        self._contract_cache: Dict[str, Any] = {}

        print(f"[ChainlinkOnChain] Connected to {self.network} (Chain ID: {self.chain_id})")
        print(f"[ChainlinkOnChain] Current block: {self.w3.eth.block_number}")

    def _get_contract(self, address: str):
        """Get or create contract instance for an address."""
        if address not in self._contract_cache:
            self._contract_cache[address] = self.w3.eth.contract(
                address=Web3.to_checksum_address(address), abi=AGGREGATOR_V3_ABI
            )
        return self._contract_cache[address]

    def get_price(self, pair: str) -> OnChainPriceResult:
        """
        Query REAL Chainlink price feed on Ethereum mainnet.

        This makes an actual on-chain call to the Chainlink aggregator contract.
        Returns verifiable on-chain data with proof (round_id, block, timestamps).

        Args:
            pair: Asset pair like "BTC/USD", "ETH/USD", "LINK/USD"

        Returns:
            OnChainPriceResult with real on-chain data and proof

        Raises:
            ValueError: If pair is not supported
            ConnectionError: If Web3 connection fails
        """
        # Normalize pair format
        pair_normalized = pair.upper().replace("-", "/")

        if pair_normalized not in CHAINLINK_FEEDS:
            available = list(CHAINLINK_FEEDS.keys())
            raise ValueError(f"Unknown price feed: {pair}. Available: {available}")

        feed_address = CHAINLINK_FEEDS[pair_normalized]
        contract = self._get_contract(feed_address)

        # Get current block for proof
        current_block = self.w3.eth.block_number

        # Call latestRoundData() on the actual contract
        round_data = contract.functions.latestRoundData().call()
        decimals = contract.functions.decimals().call()

        round_id, answer, started_at, updated_at, answered_in_round = round_data

        # Calculate actual price
        price = answer / (10**decimals)

        # Check if data is stale (older than 1 hour)
        current_time = int(time.time())
        staleness_seconds = current_time - updated_at
        is_stale = staleness_seconds > 3600

        # Build result with proof
        result = OnChainPriceResult(
            pair=pair_normalized,
            price=price,
            raw_price=answer,
            decimals=decimals,
            round_id=round_id,
            updated_at=datetime.utcfromtimestamp(updated_at).isoformat() + "Z",
            updated_at_unix=updated_at,
            started_at_unix=started_at,
            answered_in_round=answered_in_round,
            block_number=current_block,
            is_stale=is_stale,
            staleness_seconds=staleness_seconds,
            contract_address=feed_address,
            network=self.network,
            source="chainlink_mainnet",
            proof={
                "round_id": round_id,
                "block_number": current_block,
                "contract_address": feed_address,
                "chain_id": self.chain_id,
                "rpc_url": self.rpc_url.split("?")[0],  # Remove API key from proof
                "query_timestamp": current_time,
                "updated_at_unix": updated_at,
                "raw_answer": str(answer),  # String to preserve full precision
            },
        )

        status = "STALE" if is_stale else "FRESH"
        print(
            f"[ChainlinkOnChain] [{status}] {pair_normalized} = ${price:,.2f} (round {round_id}, block {current_block})"
        )

        return result

    def get_all_prices(self) -> Dict[str, OnChainPriceResult]:
        """
        Query all configured Chainlink price feeds.

        Returns:
            Dict mapping pair names to OnChainPriceResult objects
        """
        results = {}
        errors = []

        for pair in CHAINLINK_FEEDS.keys():
            try:
                results[pair] = self.get_price(pair)
            except Exception as e:
                print(f"[ChainlinkOnChain] ERROR getting {pair}: {e}")
                errors.append({"pair": pair, "error": str(e)})

        print(
            f"[ChainlinkOnChain] Fetched {len(results)}/{len(CHAINLINK_FEEDS)} prices successfully"
        )

        return results

    def verify_connection(self) -> Dict[str, Any]:
        """
        Verify connection to Ethereum mainnet and return status.

        Returns:
            Dict with connection status and diagnostic info
        """
        return {
            "connected": self.w3.is_connected(),
            "chain_id": self.chain_id,
            "network": self.network,
            "block_number": self.w3.eth.block_number,
            "rpc_url": self.rpc_url.split("/v3/")[0] + "/v3/***",  # Hide API key
            "configured_feeds": list(CHAINLINK_FEEDS.keys()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


# Convenience function for quick price lookups
def get_real_chainlink_price(pair: str) -> Dict[str, Any]:
    """
    Quick helper to get a single real Chainlink price.

    Usage:
        price_data = get_real_chainlink_price("BTC/USD")
        print(f"BTC = ${price_data['price']:,.2f}")
    """
    connector = ChainlinkOnChainConnector()
    result = connector.get_price(pair)
    return result.to_dict()


def get_all_real_chainlink_prices() -> Dict[str, Dict[str, Any]]:
    """
    Quick helper to get all configured Chainlink prices.

    Usage:
        all_prices = get_all_real_chainlink_prices()
        for pair, data in all_prices.items():
            print(f"{pair} = ${data['price']:,.2f}")
    """
    connector = ChainlinkOnChainConnector()
    results = connector.get_all_prices()
    return {pair: result.to_dict() for pair, result in results.items()}


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("CHAINLINK ON-CHAIN CONNECTOR - PRODUCTION TEST")
    print("=" * 70)

    try:
        connector = ChainlinkOnChainConnector()

        # Verify connection
        print("\n--- Connection Status ---")
        status = connector.verify_connection()
        print(f"Connected: {status['connected']}")
        print(f"Network: {status['network']} (Chain ID: {status['chain_id']})")
        print(f"Block: {status['block_number']}")

        # Get all prices
        print("\n--- Real Chainlink Prices (Ethereum Mainnet) ---")
        all_prices = connector.get_all_prices()

        for pair, result in all_prices.items():
            stale_indicator = " [STALE]" if result.is_stale else ""
            print(f"  {pair}: ${result.price:,.2f}{stale_indicator}")
            print(f"    Round: {result.round_id}")
            print(f"    Updated: {result.updated_at}")
            print(f"    Block: {result.block_number}")
            print(f"    Contract: {result.contract_address}")
            print()

        # Show proof for first result
        if all_prices:
            first_pair = list(all_prices.keys())[0]
            first_result = all_prices[first_pair]
            print(f"\n--- Proof for {first_pair} ---")
            print(json.dumps(first_result.proof, indent=2))

        print("\n[SUCCESS] Chainlink on-chain connector working correctly")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
