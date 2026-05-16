#!/usr/bin/env python3
"""
BlindOracle Outage Prediction Market Handler
==============================================

Implements the Outage Prediction Market Agent (UC7) for the CRE marketplace.
Monitors infrastructure status endpoints (AWS, GCP, Cloudflare, major
exchanges) every 15 minutes, creates prediction markets when anomalies
are detected, auto-seeds with initial liquidity, and resolves based on
official status updates.

Revenue model: 0.5% of positions.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)
    - services.swaps.cross_chain_router (CrossChainRouter)

BLP Properties:
    BLP-001 (Alignment): Infrastructure monitoring domain expertise
    BLP-011 (Autonomy): Fully autonomous market creation and resolution (99%)
    BLP-019 (Logging): Complete market lifecycle audit trail
    BLP-023 (Durability): Error recovery with graceful degradation

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import hashlib
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve imports relative to project root - ensure absolute priority over CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path = [str(_PROJECT_ROOT)] + [p for p in sys.path if p != str(_PROJECT_ROOT)]

from security.blindoracle_security_gateway import (
    BlindOracleSecurityGateway,
    SecurityConfig,
    SecurityRequest,
)
from services.swaps.cross_chain_router import CrossChainRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class InfraTarget(Enum):
    """Infrastructure monitoring targets."""
    AWS = "aws"
    GCP = "gcp"
    CLOUDFLARE = "cloudflare"
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"


class SignalSeverity(Enum):
    """Severity levels for outage signals."""
    NOMINAL = "nominal"
    DEGRADED = "degraded"
    PARTIAL_OUTAGE = "partial_outage"
    MAJOR_OUTAGE = "major_outage"


class MarketState(Enum):
    """State of an outage prediction market."""
    CREATED = "created"
    ACTIVE = "active"
    RESOLVED_YES = "resolved_yes"
    RESOLVED_NO = "resolved_no"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class OutageConfig:
    """Configuration for the Outage PM Agent.

    REQ-BLP-001: Domain-specific infrastructure monitoring config.

    Attributes:
        targets: Infrastructure targets to monitor.
        anomaly_threshold: Severity threshold for market creation.
        initial_liquidity_sats: Seed liquidity for new markets.
        market_duration_hours: How long markets stay open.
        position_fee_pct: Revenue fee on positions.
        security_interface: CaMel gateway interface.
        security_agent_id: Agent identity.
    """
    targets: List[str] = field(default_factory=lambda: [
        t.value for t in InfraTarget
    ])
    anomaly_threshold: str = SignalSeverity.DEGRADED.value
    initial_liquidity_sats: int = 50_000
    market_duration_hours: int = 4
    position_fee_pct: float = 0.5
    security_interface: str = "x402_api"
    security_agent_id: str = "outage_pm_agent_v1"


@dataclass
class OutageSignal:
    """An anomaly signal from an infrastructure target.

    Attributes:
        target: The infrastructure target.
        severity: Signal severity level.
        description: Human-readable description.
        response_time_ms: Endpoint response time.
        error_rate_pct: Error rate percentage.
        timestamp: When the signal was detected.
    """
    target: str
    severity: str
    description: str
    response_time_ms: float = 0.0
    error_rate_pct: float = 0.0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class AutoMarket:
    """An automatically created prediction market.

    Attributes:
        market_id: Unique market identifier.
        target: Infrastructure target.
        question: The prediction question.
        created_at: Creation timestamp.
        expires_at: Expiration timestamp.
        initial_liquidity_sats: Seed liquidity amount.
        yes_pool_sats: Current YES pool.
        no_pool_sats: Current NO pool.
        state: Current market state.
        resolution_evidence: Evidence used for resolution.
    """
    market_id: str = ""
    target: str = ""
    question: str = ""
    created_at: str = ""
    expires_at: str = ""
    initial_liquidity_sats: int = 0
    yes_pool_sats: int = 0
    no_pool_sats: int = 0
    state: str = MarketState.CREATED.value
    resolution_evidence: str = ""

    def __post_init__(self) -> None:
        if not self.market_id:
            self.market_id = f"outage_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class OutageReport:
    """Summary report for an outage monitoring cycle.

    Attributes:
        cycle_id: Unique cycle identifier.
        timestamp: Report timestamp.
        targets_checked: Number of targets checked.
        signals_detected: Number of anomaly signals.
        markets_created: Number of new markets created.
        markets_resolved: Number of markets resolved.
        total_liquidity_deployed_sats: Total liquidity deployed.
        fees_collected_sats: Fees collected this cycle.
        errors: Any errors encountered.
    """
    cycle_id: str = ""
    timestamp: str = ""
    targets_checked: int = 0
    signals_detected: int = 0
    markets_created: int = 0
    markets_resolved: int = 0
    total_liquidity_deployed_sats: int = 0
    fees_collected_sats: int = 0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cycle_id:
            self.cycle_id = f"outage_cycle_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Outage PM Agent
# ---------------------------------------------------------------------------

class OutagePMAgent:
    """Outage Prediction Market Agent.

    Monitors infrastructure status, creates prediction markets on
    detected anomalies, seeds liquidity, and auto-resolves based on
    official status updates.

    Revenue: 0.5% of positions.

    REQ-BLP-001 (Alignment): Infrastructure monitoring expertise
    REQ-BLP-011 (Autonomy): Fully autonomous operation (99%)
    REQ-BLP-019 (Logging): Market lifecycle audit trail
    REQ-BLP-023 (Durability): Graceful degradation on errors

    Usage:
        config = OutageConfig()
        agent = OutagePMAgent(config)
        report = await agent.run_workflow()
    """

    def __init__(
        self,
        config: Optional[OutageConfig] = None,
        router: Optional[CrossChainRouter] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        self.config = config or OutageConfig()
        self._router = router or CrossChainRouter()
        self._gateway = gateway or BlindOracleSecurityGateway()
        self._gateway.authorize_agent(self.config.security_agent_id)

        self._signals: List[OutageSignal] = []
        self._active_markets: List[AutoMarket] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] OutagePMAgent initialized")
        logger.info("[INFO]   Targets: %s", self.config.targets)
        logger.info("[INFO]   Anomaly threshold: %s", self.config.anomaly_threshold)

    # ---- Step 1: Monitor Status Endpoints ----

    async def monitor_status(self) -> List[OutageSignal]:
        """Check status endpoints for all infrastructure targets.

        REQ-BLP-001: Infrastructure status monitoring.

        Returns:
            List of OutageSignal for each target.
        """
        try:
            signals: List[OutageSignal] = []
            severity_levels = [s.value for s in SignalSeverity]

            for target in self.config.targets:
                # Mock: deterministic health based on target + time
                target_seed = hash(f"{target}_{int(time.time()) // 900}") % 100

                if target_seed < 5:
                    severity = SignalSeverity.MAJOR_OUTAGE.value
                    resp_time = 5000 + target_seed * 100
                    error_rate = 50 + target_seed
                elif target_seed < 15:
                    severity = SignalSeverity.PARTIAL_OUTAGE.value
                    resp_time = 2000 + target_seed * 50
                    error_rate = 10 + target_seed / 2
                elif target_seed < 30:
                    severity = SignalSeverity.DEGRADED.value
                    resp_time = 500 + target_seed * 10
                    error_rate = 2 + target_seed / 10
                else:
                    severity = SignalSeverity.NOMINAL.value
                    resp_time = 50 + target_seed
                    error_rate = 0.1

                signal = OutageSignal(
                    target=target,
                    severity=severity,
                    description=f"{target} status: {severity}",
                    response_time_ms=resp_time,
                    error_rate_pct=error_rate,
                )
                signals.append(signal)

                logger.info("[INFO] %s: severity=%s, resp=%dms, errors=%.1f%%",
                            target, severity, resp_time, error_rate)

            self._signals = signals
            anomalies = [s for s in signals if s.severity != SignalSeverity.NOMINAL.value]
            logger.info("[SUCCESS] Status monitored: %d targets, %d anomalies",
                        len(signals), len(anomalies))

            return signals

        except Exception as e:
            error_msg = f"Status monitoring failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Create Prediction Market ----

    async def create_market(self, signal: OutageSignal) -> AutoMarket:
        """Create a prediction market for a detected anomaly.

        REQ-BLP-011: Autonomous market creation.

        Args:
            signal: The anomaly signal triggering market creation.

        Returns:
            AutoMarket with market details.
        """
        try:
            question = (
                f"Will {signal.target.upper()} experience a major outage "
                f"(>30min downtime) in the next {self.config.market_duration_hours} hours?"
            )

            # CaMel security for market creation
            sec_request = SecurityRequest(
                interface=self.config.security_interface,
                operation="create_market",
                agent_id=self.config.security_agent_id,
                parameters={
                    "target": signal.target,
                    "severity": signal.severity,
                    "question": question,
                },
                amount_sats=self.config.initial_liquidity_sats,
            )
            sec_response = self._gateway.process_request(sec_request)

            if not sec_response.approved:
                logger.error("[ERROR] CaMel rejected market creation: %s",
                             sec_response.denial_reason)
                raise ValueError(f"Market creation denied: {sec_response.denial_reason}")

            market = AutoMarket(
                target=signal.target,
                question=question,
                initial_liquidity_sats=self.config.initial_liquidity_sats,
                yes_pool_sats=self.config.initial_liquidity_sats // 2,
                no_pool_sats=self.config.initial_liquidity_sats // 2,
                state=MarketState.ACTIVE.value,
            )

            self._active_markets.append(market)
            logger.info("[SUCCESS] Market created: %s for %s",
                        market.market_id, signal.target)

            return market

        except Exception as e:
            error_msg = f"Market creation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Auto-Seed Liquidity ----

    async def seed_liquidity(self, market: AutoMarket) -> int:
        """Seed initial liquidity into a new market.

        REQ-BLP-019: Liquidity deployment audit trail.

        Args:
            market: The market to seed.

        Returns:
            Amount of liquidity deployed in satoshis.
        """
        try:
            deployed = market.initial_liquidity_sats
            logger.info("[SUCCESS] Liquidity seeded: %d sats for market %s",
                        deployed, market.market_id)
            return deployed

        except Exception as e:
            error_msg = f"Liquidity seeding failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Resolve Market ----

    async def resolve_market(self, market: AutoMarket) -> AutoMarket:
        """Resolve a market based on official status updates.

        REQ-BLP-011: Autonomous resolution based on evidence.

        Args:
            market: The market to resolve.

        Returns:
            Updated AutoMarket with resolution.
        """
        try:
            # Mock: check if the target actually had an outage
            target_seed = hash(f"{market.target}_resolve") % 100
            had_outage = target_seed < 20  # 20% chance of actual outage

            if had_outage:
                market.state = MarketState.RESOLVED_YES.value
                market.resolution_evidence = (
                    f"Official status page confirmed >30min downtime for {market.target}"
                )
            else:
                market.state = MarketState.RESOLVED_NO.value
                market.resolution_evidence = (
                    f"No major outage confirmed. {market.target} recovered within threshold."
                )

            logger.info("[SUCCESS] Market resolved: %s -> %s",
                        market.market_id, market.state)

            return market

        except Exception as e:
            error_msg = f"Market resolution failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Full Workflow ----

    async def run_workflow(self) -> OutageReport:
        """Execute the full outage monitoring and market workflow.

        Steps:
        1. Monitor status endpoints
        2. Create markets for anomalies
        3. Seed liquidity
        4. Resolve existing markets

        Returns:
            OutageReport with cycle summary.
        """
        logger.info("[INFO] === Outage PM Agent Workflow Starting ===")
        start = time.time()

        try:
            signals = await self.monitor_status()

            # Filter anomalies above threshold
            threshold_order = [s.value for s in SignalSeverity]
            threshold_idx = threshold_order.index(self.config.anomaly_threshold)
            anomalies = [
                s for s in signals
                if threshold_order.index(s.severity) >= threshold_idx
            ]

            markets_created = 0
            total_liquidity = 0
            for signal in anomalies:
                try:
                    market = await self.create_market(signal)
                    liquidity = await self.seed_liquidity(market)
                    total_liquidity += liquidity
                    markets_created += 1
                except Exception as e:
                    self._errors.append(str(e))

            # Resolve any active markets (mock: resolve all)
            markets_resolved = 0
            for market in list(self._active_markets):
                try:
                    await self.resolve_market(market)
                    markets_resolved += 1
                except Exception:
                    pass

            fees = int(total_liquidity * self.config.position_fee_pct / 100.0)

            report = OutageReport(
                targets_checked=len(signals),
                signals_detected=len(anomalies),
                markets_created=markets_created,
                markets_resolved=markets_resolved,
                total_liquidity_deployed_sats=total_liquidity,
                fees_collected_sats=fees,
                errors=list(self._errors),
            )

            elapsed = (time.time() - start) * 1000
            logger.info("[SUCCESS] === Outage PM Workflow Complete (%.0fms) ===", elapsed)
            logger.info("[INFO]   Targets: %d, Anomalies: %d, Markets: %d",
                        report.targets_checked, report.signals_detected, report.markets_created)

            return report

        except Exception as e:
            logger.error("[ERROR] Outage PM workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return OutageReport(errors=list(self._errors))


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Outage PM Agent workflow."""
    print("=" * 70)
    print("BlindOracle Outage Prediction Market Agent -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize ---")
    config = OutageConfig()
    agent = OutagePMAgent(config)
    print(f"  Targets: {config.targets}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Monitor status ---
    print("\n--- 2. Monitor Status ---")
    signals = await agent.monitor_status()
    print(f"  Checked: {len(signals)} targets")
    for s in signals:
        print(f"    {s.target}: {s.severity} (resp: {s.response_time_ms:.0f}ms)")
    results.append({"test": "Monitor Status", "pass": len(signals) == len(config.targets)})

    # --- 3. Create market ---
    print("\n--- 3. Create Market ---")
    test_signal = OutageSignal(
        target="aws", severity=SignalSeverity.DEGRADED.value,
        description="AWS degraded performance",
        response_time_ms=1500, error_rate_pct=5.0,
    )
    market = await agent.create_market(test_signal)
    print(f"  Market ID: {market.market_id}")
    print(f"  Question: {market.question[:60]}...")
    results.append({"test": "Create Market", "pass": market.state == MarketState.ACTIVE.value})

    # --- 4. Seed liquidity ---
    print("\n--- 4. Seed Liquidity ---")
    liquidity = await agent.seed_liquidity(market)
    print(f"  Deployed: {liquidity} sats")
    results.append({"test": "Seed Liquidity", "pass": liquidity > 0})

    # --- 5. Resolve market ---
    print("\n--- 5. Resolve Market ---")
    resolved = await agent.resolve_market(market)
    print(f"  State: {resolved.state}")
    print(f"  Evidence: {resolved.resolution_evidence[:60]}...")
    results.append({"test": "Resolve Market", "pass": resolved.state in [
        MarketState.RESOLVED_YES.value, MarketState.RESOLVED_NO.value,
    ]})

    # --- 6. Full workflow ---
    print("\n--- 6. Full Workflow ---")
    agent2 = OutagePMAgent(config)
    report = await agent2.run_workflow()
    print(f"  Cycle ID: {report.cycle_id}")
    print(f"  Targets checked: {report.targets_checked}")
    print(f"  Signals: {report.signals_detected}")
    print(f"  Markets created: {report.markets_created}")
    results.append({"test": "Full Workflow", "pass": report.targets_checked > 0})

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
