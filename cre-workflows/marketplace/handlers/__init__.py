# Copyright (c) 2025 Craig M. Brown. All rights reserved.
"""
BlindOracle CRE Marketplace Workflow Handlers
==============================================

Python handler implementations for CRE marketplace workflows.

Handlers:
    treasury_handler           - UC1: Autonomous treasury management and rebalancing
    compliance_handler         - UC2: RWA compliance screening (4-agent debate)
    dca_handler                - UC3: AI-powered dollar cost averaging
    credit_bureau_handler      - UC4: On-chain agent credit scoring
    arbitrage_handler          - UC5: Cross-chain arbitrage detection/execution
    consensus_resolver_handler - UC6: Multi-AI consensus for market resolution
    outage_pm_handler          - UC7: Outage prediction market creation
    health_monitor_handler     - UC8: Platform-wide health monitoring
    proof_of_reserve_handler   - UC9: Cryptographic proof-of-reserve auditing
    customer_success_handler   - UC10: Proactive customer success management
    ccip_conditional_handler   - UC12: Cross-chain conditional markets (CCIP)
"""

from .treasury_handler import TreasuryAgent, TreasuryConfig
from .compliance_handler import ComplianceSwarm, ComplianceConfig
from .dca_handler import DCAAgent, DCAConfig, DCASubscription
from .credit_bureau_handler import CreditBureau, CreditConfig
from .arbitrage_handler import ArbitrageBreaker, ArbitrageConfig
from .consensus_resolver_handler import ConsensusResolver, ResolutionConfig
from .outage_pm_handler import OutagePMAgent, OutageConfig
from .health_monitor_handler import HealthMonitor, HealthConfig
from .proof_of_reserve_handler import ProofOfReserve, ReserveConfig
from .customer_success_handler import CustomerSuccessAgent, SuccessConfig
# UC11 — RQ-166: Topological Market Resolver
from .topological_resolver_handler import TopologicalResolverHandler
# UC12 — RQ-172: Cross-Chain Conditional Markets (CCIP)
from .ccip_conditional_handler import CCIPConditionalHandler

__all__ = [
    # UC1: Treasury
    "TreasuryAgent",
    "TreasuryConfig",
    # UC2: Compliance
    "ComplianceSwarm",
    "ComplianceConfig",
    # UC3: DCA
    "DCAAgent",
    "DCAConfig",
    "DCASubscription",
    # UC4: Credit Bureau
    "CreditBureau",
    "CreditConfig",
    # UC5: Arbitrage
    "ArbitrageBreaker",
    "ArbitrageConfig",
    # UC6: Consensus Resolver
    "ConsensusResolver",
    "ResolutionConfig",
    # UC7: Outage PM
    "OutagePMAgent",
    "OutageConfig",
    # UC8: Health Monitor
    "HealthMonitor",
    "HealthConfig",
    # UC9: Proof of Reserve
    "ProofOfReserve",
    "ReserveConfig",
    # UC10: Customer Success
    "CustomerSuccessAgent",
    "SuccessConfig",
    # UC12: CCIP Conditional
    "CCIPConditionalHandler",
]
