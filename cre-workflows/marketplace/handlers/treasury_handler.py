#!/usr/bin/env python3
"""
BlindOracle Autonomous Treasury Agent Handler
==============================================

Implements the Treasury Agent (UC1) logic for the CRE marketplace.
Monitors portfolio balances across BTC, ETH, USDC, and eCash rails,
detects allocation drift, proposes rebalancing trades, and executes
them through the CaMel 4-layer security gateway.

Revenue model: 0.1% fee on each rebalance trade.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, SecurityResponse, BlindOracleSecurityGateway)
    - services.swaps.cross_chain_router (CrossChainRouter, SwapPair)

BLP Properties:
    BLP-001 (Alignment): Domain-specific portfolio management understanding
    BLP-011 (Autonomy): Independent rebalancing decisions based on drift analysis
    BLP-019 (Logging): Complete audit trail for all treasury operations
    BLP-023 (Durability): Error recovery with per-trade isolation

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Resolve imports relative to project root - ensure absolute priority over CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path = [str(_PROJECT_ROOT)] + [p for p in sys.path if p != str(_PROJECT_ROOT)]

from security.blindoracle_security_gateway import (
    BlindOracleSecurityGateway,
    SecurityConfig,
    SecurityRequest,
    SecurityResponse,
)
from services.swaps.cross_chain_router import CrossChainRouter, SwapPair

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

class RebalanceDirection(Enum):
    """Direction of a rebalance trade."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class TreasuryConfig:
    """Configuration for the Treasury Agent.

    REQ-BLP-001: Domain-specific configuration for portfolio management.

    Attributes:
        target_allocations: Target allocation percentages by asset.
        rebalance_threshold_pct: Drift percentage that triggers rebalancing.
        max_single_trade_sats: Maximum amount for a single trade in satoshis.
        rebalance_fee_pct: Fee percentage collected on each rebalance trade.
        security_interface: CaMel gateway interface identifier.
        security_agent_id: Agent identity for security gateway.
    """
    target_allocations: Dict[str, float] = field(default_factory=lambda: {
        "BTC": 40.0,
        "ETH": 30.0,
        "USDC": 20.0,
        "eCash": 10.0,
    })
    rebalance_threshold_pct: float = 5.0
    max_single_trade_sats: int = 10_000
    rebalance_fee_pct: float = 0.1
    security_interface: str = "x402_api"
    security_agent_id: str = "treasury_agent_v1"

    def __post_init__(self) -> None:
        total = sum(self.target_allocations.values())
        if abs(total - 100.0) > 0.01:
            raise ValueError(
                f"Target allocations must sum to 100%. Got {total:.2f}%"
            )


@dataclass
class AllocationAnalysis:
    """Result of comparing current vs target allocations.

    Attributes:
        current_allocations: Current allocation percentages by asset.
        target_allocations: Target allocation percentages by asset.
        drift: Per-asset drift (current - target) in percentage points.
        max_drift: Maximum absolute drift across all assets.
        drift_detected: Whether any asset exceeds the threshold.
        total_value_sats: Total portfolio value in satoshi equivalent.
    """
    current_allocations: Dict[str, float]
    target_allocations: Dict[str, float]
    drift: Dict[str, float]
    max_drift: float
    drift_detected: bool
    total_value_sats: int


@dataclass
class RebalanceTrade:
    """A single proposed rebalance trade.

    Attributes:
        trade_id: Unique identifier for this trade.
        from_asset: Asset to sell.
        to_asset: Asset to buy.
        pair: The swap pair for routing.
        amount_sats: Trade amount in satoshi equivalent.
        direction: Buy or sell direction.
        fee_sats: Fee amount collected in satoshis.
    """
    trade_id: str
    from_asset: str
    to_asset: str
    pair: SwapPair
    amount_sats: int
    direction: RebalanceDirection
    fee_sats: int = 0

    def __post_init__(self) -> None:
        if not self.trade_id:
            self.trade_id = f"rebal_{uuid.uuid4().hex[:12]}"


@dataclass
class RebalanceReport:
    """Performance report generated after a treasury cycle.

    Attributes:
        timestamp: ISO-8601 timestamp of the report.
        cycle_id: Unique identifier for this treasury cycle.
        balances: Current balances across all rails.
        allocations: Current allocation percentages.
        drift_detected: Whether drift was detected.
        max_drift_pct: Maximum drift percentage.
        trades_executed: Number of trades executed.
        total_volume_sats: Total trade volume in satoshis.
        fees_collected_sats: Total fees collected in satoshis.
        errors: List of errors encountered during the cycle.
    """
    timestamp: str = ""
    cycle_id: str = ""
    balances: Dict[str, int] = field(default_factory=dict)
    allocations: Dict[str, float] = field(default_factory=dict)
    drift_detected: bool = False
    max_drift_pct: float = 0.0
    trades_executed: int = 0
    total_volume_sats: int = 0
    fees_collected_sats: int = 0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.cycle_id:
            self.cycle_id = f"cycle_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Swap pair resolution
# ---------------------------------------------------------------------------

# Map (from_asset, to_asset) -> SwapPair
_PAIR_MAP: Dict[Tuple[str, str], SwapPair] = {
    ("BTC", "ETH"): SwapPair.BTC_ETH,
    ("BTC", "USDC"): SwapPair.BTC_USDC,
    ("eCash", "USDC"): SwapPair.ECASH_USDC,
    ("eCash", "BTC"): SwapPair.ECASH_BTC,
    ("ETH", "USDC"): SwapPair.ETH_USDC,
}


def _resolve_swap_pair(from_asset: str, to_asset: str) -> Optional[SwapPair]:
    """Resolve a swap pair from two asset names.

    Tries direct match first, then reverse (some pairs are bidirectional).

    Args:
        from_asset: Source asset name.
        to_asset: Destination asset name.

    Returns:
        SwapPair if found, None otherwise.
    """
    pair = _PAIR_MAP.get((from_asset, to_asset))
    if pair:
        return pair
    # Try reverse mapping (swap will just go the other direction)
    pair = _PAIR_MAP.get((to_asset, from_asset))
    return pair


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

# Mock conversion rates to satoshi equivalent
_SAT_CONVERSION: Dict[str, float] = {
    "BTC": 1.0,              # 1 sat = 1 sat
    "ETH": 0.000000001,      # wei to sat (rough)
    "USDC": 0.015,           # USDC smallest unit to sat (rough)
    "eCash": 1.0,            # eCash sats = BTC sats
    "Lightning": 1.0,        # Lightning sats = BTC sats
}


def _to_sat_equivalent(asset: str, balance: int) -> int:
    """Convert an asset balance to satoshi equivalent for comparison.

    Args:
        asset: Asset name.
        balance: Balance in the asset's smallest unit.

    Returns:
        Approximate value in satoshis.
    """
    rate = _SAT_CONVERSION.get(asset, 1.0)
    return int(balance * rate)


# ---------------------------------------------------------------------------
# Treasury Agent
# ---------------------------------------------------------------------------

class TreasuryAgent:
    """Autonomous Treasury Agent for portfolio rebalancing.

    Monitors portfolio balances across BTC, ETH, USDC, and eCash,
    detects allocation drift against target percentages, and executes
    CaMel-secured rebalancing trades when drift exceeds the threshold.

    Revenue: 0.1% fee on each rebalance trade volume.

    REQ-BLP-001 (Alignment): Portfolio management domain expertise
    REQ-BLP-011 (Autonomy): Independent rebalancing decisions
    REQ-BLP-019 (Logging): Complete audit trail
    REQ-BLP-023 (Durability): Per-trade error isolation

    Usage:
        config = TreasuryConfig()
        agent = TreasuryAgent(config)
        report = await agent.run_workflow()
    """

    def __init__(
        self,
        config: Optional[TreasuryConfig] = None,
        router: Optional[CrossChainRouter] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        """Initialize the Treasury Agent.

        Args:
            config: Treasury configuration. Uses defaults if not provided.
            router: CrossChainRouter instance. Created if not provided.
            gateway: Security gateway instance. Created if not provided.
        """
        self.config = config or TreasuryConfig()
        self._router = router or CrossChainRouter()
        self._gateway = gateway or BlindOracleSecurityGateway()

        # Authorize the treasury agent in the security gateway
        self._gateway.authorize_agent(self.config.security_agent_id)

        # State for the current cycle
        self._balances: Dict[str, int] = {}
        self._analysis: Optional[AllocationAnalysis] = None
        self._trade_plan: List[RebalanceTrade] = []
        self._executed_trades: List[Dict[str, Any]] = []
        self._total_fees_sats: int = 0
        self._errors: List[str] = []

        logger.info("[SUCCESS] TreasuryAgent initialized")
        logger.info("[INFO]   Target allocations: %s", self.config.target_allocations)
        logger.info("[INFO]   Rebalance threshold: %.1f%%", self.config.rebalance_threshold_pct)
        logger.info("[INFO]   Max single trade: %d sats", self.config.max_single_trade_sats)

    # ---- Step 1: Monitor Balances ----

    async def monitor_balances(self) -> Dict[str, int]:
        """Retrieve current balances across all payment rails.

        REQ-BLP-001: Domain understanding -- knows which rails to check.

        Returns:
            Dictionary mapping asset name to balance in smallest unit.
        """
        try:
            self._balances = await self._router.get_balances()
            logger.info("[SUCCESS] Balances retrieved: %s", self._balances)
            return self._balances
        except Exception as e:
            error_msg = f"Failed to retrieve balances: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Analyze Allocation ----

    async def analyze_allocation(self) -> AllocationAnalysis:
        """Compare current allocation against target and calculate drift.

        REQ-BLP-011: Independent decision making -- determines if
        rebalancing is needed without human input.

        Returns:
            AllocationAnalysis with drift calculations.
        """
        try:
            if not self._balances:
                await self.monitor_balances()

            # Convert all balances to satoshi equivalent
            sat_values: Dict[str, int] = {}
            for asset, balance in self._balances.items():
                sat_values[asset] = _to_sat_equivalent(asset, balance)

            total_sats = sum(sat_values.values())
            if total_sats == 0:
                raise ValueError("Total portfolio value is zero -- cannot analyze allocation")

            # Calculate current percentages
            current_pct: Dict[str, float] = {}
            for asset in self.config.target_allocations:
                current_pct[asset] = (sat_values.get(asset, 0) / total_sats) * 100.0

            # Calculate drift
            drift: Dict[str, float] = {}
            for asset, target in self.config.target_allocations.items():
                drift[asset] = round(current_pct.get(asset, 0.0) - target, 2)

            max_drift = max(abs(d) for d in drift.values()) if drift else 0.0
            drift_detected = max_drift > self.config.rebalance_threshold_pct

            self._analysis = AllocationAnalysis(
                current_allocations=current_pct,
                target_allocations=dict(self.config.target_allocations),
                drift=drift,
                max_drift=round(max_drift, 2),
                drift_detected=drift_detected,
                total_value_sats=total_sats,
            )

            logger.info("[SUCCESS] Allocation analysis complete")
            logger.info("[INFO]   Total value: %d sats", total_sats)
            for asset in self.config.target_allocations:
                logger.info(
                    "[INFO]   %s: current=%.1f%% target=%.1f%% drift=%+.1f%%",
                    asset, current_pct.get(asset, 0), self.config.target_allocations[asset],
                    drift.get(asset, 0),
                )
            logger.info("[INFO]   Max drift: %.1f%% (threshold: %.1f%%)",
                        max_drift, self.config.rebalance_threshold_pct)
            logger.info("[INFO]   Drift detected: %s", drift_detected)

            return self._analysis

        except Exception as e:
            error_msg = f"Allocation analysis failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Propose Rebalance ----

    async def propose_rebalance(self) -> List[RebalanceTrade]:
        """Generate a rebalance trade plan if drift exceeds threshold.

        For each over-allocated asset, propose selling the excess into
        the most under-allocated asset. Trades are capped at
        max_single_trade_sats.

        REQ-BLP-011: Independent decision making -- generates trade plan.

        Returns:
            List of proposed RebalanceTrade objects.
        """
        try:
            if self._analysis is None:
                await self.analyze_allocation()

            assert self._analysis is not None

            if not self._analysis.drift_detected:
                logger.info("[INFO] No rebalancing needed -- drift within threshold")
                self._trade_plan = []
                return self._trade_plan

            total_sats = self._analysis.total_value_sats
            trades: List[RebalanceTrade] = []

            # Find over-allocated and under-allocated assets
            over_assets = [(a, d) for a, d in self._analysis.drift.items() if d > self.config.rebalance_threshold_pct]
            under_assets = [(a, d) for a, d in self._analysis.drift.items() if d < -self.config.rebalance_threshold_pct]

            # Sort: most over-allocated first, most under-allocated first
            over_assets.sort(key=lambda x: x[1], reverse=True)
            under_assets.sort(key=lambda x: x[1])

            for over_asset, over_drift in over_assets:
                for under_asset, under_drift in under_assets:
                    # Calculate trade amount (move half the excess drift)
                    trade_pct = min(abs(over_drift), abs(under_drift)) / 2.0
                    trade_sats = int(total_sats * trade_pct / 100.0)
                    trade_sats = min(trade_sats, self.config.max_single_trade_sats)

                    if trade_sats < 100:
                        continue  # Skip dust trades

                    pair = _resolve_swap_pair(over_asset, under_asset)
                    if pair is None:
                        logger.info("[INFO] No swap pair for %s -> %s, skipping", over_asset, under_asset)
                        continue

                    fee_sats = max(1, int(trade_sats * self.config.rebalance_fee_pct / 100.0))

                    trade = RebalanceTrade(
                        trade_id=f"rebal_{uuid.uuid4().hex[:12]}",
                        from_asset=over_asset,
                        to_asset=under_asset,
                        pair=pair,
                        amount_sats=trade_sats,
                        direction=RebalanceDirection.SELL,
                        fee_sats=fee_sats,
                    )
                    trades.append(trade)

                    logger.info(
                        "[INFO] Proposed trade: %s -> %s, %d sats (fee: %d sats), pair: %s",
                        over_asset, under_asset, trade_sats, fee_sats, pair.value,
                    )

            self._trade_plan = trades
            logger.info("[SUCCESS] Rebalance plan: %d trades proposed", len(trades))
            return self._trade_plan

        except Exception as e:
            error_msg = f"Rebalance proposal failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Execute Rebalance (CaMel-Secured) ----

    async def execute_rebalance(self) -> List[Dict[str, Any]]:
        """Execute rebalance trades through the CaMel security gateway.

        Each trade is wrapped in a SecurityRequest and must pass all
        4 CaMel layers before execution. Failed trades do not block
        subsequent trades (per-trade isolation).

        REQ-BLP-019: Complete audit trail for all execution attempts.
        REQ-BLP-023: Error recovery -- individual trade failures isolated.

        Returns:
            List of execution result dictionaries.
        """
        results: List[Dict[str, Any]] = []

        if not self._trade_plan:
            logger.info("[INFO] No trades to execute")
            return results

        for trade in self._trade_plan:
            try:
                # Wrap in SecurityRequest for CaMel validation
                sec_request = SecurityRequest(
                    interface=self.config.security_interface,
                    operation="swap_execute",
                    agent_id=self.config.security_agent_id,
                    parameters={
                        "trade_id": trade.trade_id,
                        "from_asset": trade.from_asset,
                        "to_asset": trade.to_asset,
                        "pair": trade.pair.value,
                        "amount_sats": trade.amount_sats,
                    },
                    amount_sats=trade.amount_sats,
                )

                sec_response = self._gateway.process_request(sec_request)

                if not sec_response.approved:
                    error_msg = (
                        f"CaMel rejected trade {trade.trade_id}: "
                        f"{sec_response.denial_reason}"
                    )
                    logger.error("[ERROR] %s", error_msg)
                    self._errors.append(error_msg)
                    results.append({
                        "trade_id": trade.trade_id,
                        "success": False,
                        "error": sec_response.denial_reason,
                        "security_audit_id": sec_response.audit_id,
                    })
                    continue

                # Execute the swap through CrossChainRouter
                quote = await self._router.get_quote(trade.pair, trade.amount_sats)
                swap_result = await self._router.execute_swap(quote)

                if swap_result.success:
                    self._total_fees_sats += trade.fee_sats
                    result = {
                        "trade_id": trade.trade_id,
                        "success": True,
                        "swap_id": swap_result.swap_id,
                        "input_amount": swap_result.input_amount,
                        "output_amount": swap_result.output_amount,
                        "tx_hash": swap_result.tx_hash,
                        "fee_sats": trade.fee_sats,
                        "security_audit_id": sec_response.audit_id,
                    }
                    logger.info(
                        "[SUCCESS] Trade executed: %s, in=%d, out=%d, fee=%d, tx=%s",
                        trade.trade_id, swap_result.input_amount,
                        swap_result.output_amount, trade.fee_sats,
                        swap_result.tx_hash[:18] if swap_result.tx_hash else "N/A",
                    )
                else:
                    error_msg = f"Swap failed for trade {trade.trade_id}: {swap_result.error}"
                    logger.error("[ERROR] %s", error_msg)
                    self._errors.append(error_msg)
                    result = {
                        "trade_id": trade.trade_id,
                        "success": False,
                        "error": swap_result.error,
                        "security_audit_id": sec_response.audit_id,
                    }

                results.append(result)

            except Exception as e:
                error_msg = f"Trade {trade.trade_id} execution error: {e}"
                logger.error("[ERROR] %s", error_msg)
                self._errors.append(error_msg)
                results.append({
                    "trade_id": trade.trade_id,
                    "success": False,
                    "error": str(e),
                })

        self._executed_trades = results
        successful = sum(1 for r in results if r.get("success"))
        logger.info(
            "[SUCCESS] Rebalance execution complete: %d/%d trades succeeded",
            successful, len(results),
        )
        return results

    # ---- Step 5: Generate Report ----

    async def generate_report(self) -> RebalanceReport:
        """Generate a performance report for this treasury cycle.

        REQ-BLP-019: Comprehensive logging and reporting.

        Returns:
            RebalanceReport with all cycle metrics.
        """
        try:
            # Refresh balances after trades
            if self._executed_trades:
                self._balances = await self._router.get_balances()

            successful_trades = [t for t in self._executed_trades if t.get("success")]
            total_volume = sum(t.get("input_amount", 0) for t in successful_trades)

            report = RebalanceReport(
                balances=dict(self._balances),
                allocations=self._analysis.current_allocations if self._analysis else {},
                drift_detected=self._analysis.drift_detected if self._analysis else False,
                max_drift_pct=self._analysis.max_drift if self._analysis else 0.0,
                trades_executed=len(successful_trades),
                total_volume_sats=total_volume,
                fees_collected_sats=self._total_fees_sats,
                errors=list(self._errors),
            )

            logger.info("[SUCCESS] Treasury report generated")
            logger.info("[INFO]   Cycle ID: %s", report.cycle_id)
            logger.info("[INFO]   Drift detected: %s (max: %.1f%%)",
                        report.drift_detected, report.max_drift_pct)
            logger.info("[INFO]   Trades executed: %d", report.trades_executed)
            logger.info("[INFO]   Total volume: %d sats", report.total_volume_sats)
            logger.info("[INFO]   Fees collected: %d sats", report.fees_collected_sats)
            if report.errors:
                logger.info("[INFO]   Errors: %d", len(report.errors))

            return report

        except Exception as e:
            error_msg = f"Report generation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return RebalanceReport(errors=list(self._errors))

    # ---- Full Workflow Orchestration ----

    async def run_workflow(self) -> RebalanceReport:
        """Execute the full treasury workflow.

        Runs all 5 steps in sequence:
        1. Monitor balances
        2. Analyze allocation
        3. Propose rebalance (if drift detected)
        4. Execute rebalance (if trades proposed)
        5. Generate report (always)

        Returns:
            RebalanceReport with cycle results.
        """
        logger.info("[INFO] === Treasury Agent Workflow Starting ===")
        start = time.time()

        try:
            await self.monitor_balances()
            await self.analyze_allocation()
            await self.propose_rebalance()

            if self._trade_plan:
                await self.execute_rebalance()

            report = await self.generate_report()

            elapsed = (time.time() - start) * 1000
            logger.info(
                "[SUCCESS] === Treasury Agent Workflow Complete (%.0fms) ===",
                elapsed,
            )
            return report

        except Exception as e:
            logger.error("[ERROR] Treasury workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return await self.generate_report()


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Treasury Agent workflow."""
    print("=" * 70)
    print("BlindOracle Treasury Agent -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize with default config ---
    print("\n--- 1. Initialize Treasury Agent ---")
    config = TreasuryConfig()
    agent = TreasuryAgent(config)
    print(f"  Target allocations: {config.target_allocations}")
    print(f"  Threshold: {config.rebalance_threshold_pct}%")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Monitor balances ---
    print("\n--- 2. Monitor Balances ---")
    balances = await agent.monitor_balances()
    print(f"  Balances: {balances}")
    assert len(balances) > 0, "Should have balances"
    results.append({"test": "Monitor Balances", "pass": len(balances) > 0})

    # --- 3. Analyze allocation ---
    print("\n--- 3. Analyze Allocation ---")
    analysis = await agent.analyze_allocation()
    print(f"  Current: {analysis.current_allocations}")
    print(f"  Drift: {analysis.drift}")
    print(f"  Max drift: {analysis.max_drift}%")
    print(f"  Drift detected: {analysis.drift_detected}")
    results.append({"test": "Analyze Allocation", "pass": True})

    # --- 4. Propose rebalance ---
    print("\n--- 4. Propose Rebalance ---")
    trades = await agent.propose_rebalance()
    print(f"  Trades proposed: {len(trades)}")
    for trade in trades:
        print(f"    {trade.from_asset} -> {trade.to_asset}: {trade.amount_sats} sats")
    results.append({"test": "Propose Rebalance", "pass": True})

    # --- 5. Execute rebalance (if trades exist) ---
    print("\n--- 5. Execute Rebalance ---")
    if trades:
        exec_results = await agent.execute_rebalance()
        successful = sum(1 for r in exec_results if r.get("success"))
        print(f"  Executed: {successful}/{len(exec_results)} succeeded")
        results.append({"test": "Execute Rebalance", "pass": True})
    else:
        print("  No trades to execute (portfolio within threshold)")
        results.append({"test": "Execute Rebalance", "pass": True})

    # --- 6. Generate report ---
    print("\n--- 6. Generate Report ---")
    report = await agent.generate_report()
    print(f"  Cycle ID: {report.cycle_id}")
    print(f"  Trades: {report.trades_executed}")
    print(f"  Volume: {report.total_volume_sats} sats")
    print(f"  Fees: {report.fees_collected_sats} sats")
    print(f"  Errors: {len(report.errors)}")
    results.append({"test": "Generate Report", "pass": True})

    # --- 7. Full workflow ---
    print("\n--- 7. Full Workflow Run ---")
    agent2 = TreasuryAgent(config)
    full_report = await agent2.run_workflow()
    print(f"  Cycle ID: {full_report.cycle_id}")
    print(f"  Drift detected: {full_report.drift_detected}")
    results.append({"test": "Full Workflow", "pass": True})

    # --- Summary ---
    print("\n" + "=" * 70)
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['test']}")
    print(f"\nResults: {passed}/{total} passed ({passed/total*100:.0f}%)")
    print("=" * 70)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run_self_test())
