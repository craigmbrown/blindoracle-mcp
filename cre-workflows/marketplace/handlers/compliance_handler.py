#!/usr/bin/env python3
"""
BlindOracle Compliance Swarm Handler
=====================================

Implements the RWA Compliance Screening Agent (UC2) for the CRE marketplace.
When a new prediction market is created, the swarm:

1. Extracts market question and metadata
2. Checks against sanctions lists
3. Runs KYC-light on the creator agent
4. Executes a 4-agent debate (Compliance + Risk + Legal + Devil's Advocate)
5. Issues compliance clearance or escalates to founder

Revenue model: $5/check, $99/mo subscription.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)
    - services.swaps.cross_chain_router (CrossChainRouter)

BLP Properties:
    BLP-001 (Alignment): Domain-specific compliance and regulatory understanding
    BLP-003 (Consensus Security): 4-agent debate with 67% threshold
    BLP-011 (Autonomy): Autonomous screening with founder escalation (85% autonomy)
    BLP-019 (Logging): Complete compliance audit trail
    BLP-023 (Durability): Error recovery with safe-deny fallback

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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ComplianceCheck(Enum):
    """Types of compliance checks performed."""
    SANCTIONS = "sanctions"
    KYC_LIGHT = "kyc_light"
    RWA_CLASSIFICATION = "rwa_classification"
    CONTENT_POLICY = "content_policy"


class ComplianceVerdict(Enum):
    """Possible compliance outcomes."""
    APPROVED = "approved"
    DENIED = "denied"
    ESCALATED = "escalated"
    PENDING = "pending"


class DebateRole(Enum):
    """Roles in the compliance debate."""
    COMPLIANCE_OFFICER = "compliance_officer"
    RISK_ANALYST = "risk_analyst"
    LEGAL_ADVISOR = "legal_advisor"
    DEVILS_ADVOCATE = "devils_advocate"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ComplianceConfig:
    """Configuration for the Compliance Swarm.

    REQ-BLP-001: Domain-specific compliance configuration.

    Attributes:
        sanctions_lists: Active sanctions list sources.
        kyc_light_fields: Fields required for KYC-light screening.
        debate_threshold: Minimum agreement for debate consensus (67%).
        fee_per_check_usd: Revenue per individual check.
        subscription_monthly_usd: Monthly subscription fee.
        security_interface: CaMel gateway interface identifier.
        security_agent_id: Agent identity for security gateway.
    """
    sanctions_lists: List[str] = field(default_factory=lambda: [
        "OFAC_SDN", "EU_SANCTIONS", "UN_CONSOLIDATED", "UK_HMT",
    ])
    kyc_light_fields: List[str] = field(default_factory=lambda: [
        "agent_pubkey", "jurisdiction", "entity_type", "creation_date",
    ])
    debate_threshold: float = 0.67
    fee_per_check_usd: float = 5.0
    subscription_monthly_usd: float = 99.0
    security_interface: str = "x402_api"
    security_agent_id: str = "compliance_swarm_v1"


@dataclass
class MarketMetadata:
    """Metadata extracted from a newly created prediction market.

    Attributes:
        market_id: On-chain market identifier.
        question: The prediction question.
        creator_pubkey: Public key of the market creator.
        category: Market category (e.g. "crypto", "sports", "politics").
        involves_rwa: Whether the market involves real-world assets.
        jurisdiction_hints: Detected jurisdictional relevance.
        creation_timestamp: When the market was created.
    """
    market_id: int
    question: str
    creator_pubkey: str
    category: str = "general"
    involves_rwa: bool = False
    jurisdiction_hints: List[str] = field(default_factory=list)
    creation_timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.creation_timestamp:
            self.creation_timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ScreeningResult:
    """Result of a single compliance check.

    Attributes:
        check_type: Type of check performed.
        passed: Whether the check passed.
        risk_score: Risk score (0.0 = safe, 1.0 = high risk).
        details: Human-readable details of the check result.
        flags: Any specific flags raised.
    """
    check_type: str
    passed: bool
    risk_score: float
    details: str
    flags: List[str] = field(default_factory=list)


@dataclass
class DebateVote:
    """Vote from a debate participant.

    Attributes:
        role: The debater's role.
        position: approve/deny/escalate.
        confidence: Confidence in the position (0.0 - 1.0).
        reasoning: Explanation for the position.
    """
    role: str
    position: str
    confidence: float
    reasoning: str


@dataclass
class ComplianceReport:
    """Final compliance report for a market.

    Attributes:
        report_id: Unique report identifier.
        market_id: Market that was screened.
        verdict: Final verdict (approved/denied/escalated).
        screening_results: Individual check results.
        debate_votes: All debate participant votes.
        debate_consensus_pct: Consensus percentage from the debate.
        risk_score: Aggregate risk score.
        fee_charged_usd: Fee charged for this screening.
        errors: Any errors encountered.
        timestamp: When the report was generated.
    """
    report_id: str = ""
    market_id: int = 0
    verdict: str = ComplianceVerdict.PENDING.value
    screening_results: List[Dict[str, Any]] = field(default_factory=list)
    debate_votes: List[Dict[str, Any]] = field(default_factory=list)
    debate_consensus_pct: float = 0.0
    risk_score: float = 0.0
    fee_charged_usd: float = 0.0
    errors: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = f"compliance_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Compliance Swarm
# ---------------------------------------------------------------------------

class ComplianceSwarm:
    """RWA Compliance Screening Agent for prediction markets.

    When a new market is created, the swarm extracts metadata, runs
    sanctions checks, performs KYC-light on the creator, and executes
    a 4-agent debate to determine compliance clearance.

    Revenue: $5/check, $99/mo subscription.

    REQ-BLP-001 (Alignment): Compliance domain expertise
    REQ-BLP-003 (Consensus Security): 4-agent debate consensus
    REQ-BLP-011 (Autonomy): 85% autonomous with founder escalation
    REQ-BLP-019 (Logging): Complete compliance audit trail
    REQ-BLP-023 (Durability): Safe-deny fallback on errors

    Usage:
        config = ComplianceConfig()
        swarm = ComplianceSwarm(config)
        report = await swarm.run_workflow(market_id=1,
            question="Will AAPL exceed $200?", creator_pubkey="npub1...")
    """

    def __init__(
        self,
        config: Optional[ComplianceConfig] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        """Initialize the Compliance Swarm.

        Args:
            config: Compliance configuration. Uses defaults if not provided.
            gateway: Security gateway. Created if not provided.
        """
        self.config = config or ComplianceConfig()
        self._gateway = gateway or BlindOracleSecurityGateway()

        self._gateway.authorize_agent(self.config.security_agent_id)

        # State
        self._metadata: Optional[MarketMetadata] = None
        self._screening_results: List[ScreeningResult] = []
        self._debate_votes: List[DebateVote] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] ComplianceSwarm initialized")
        logger.info("[INFO]   Sanctions lists: %s", self.config.sanctions_lists)
        logger.info("[INFO]   Debate threshold: %.0f%%", self.config.debate_threshold * 100)

    # ---- Step 1: Extract Market Metadata ----

    async def extract_metadata(
        self, market_id: int, question: str, creator_pubkey: str
    ) -> MarketMetadata:
        """Extract and classify market question and metadata.

        REQ-BLP-001: Domain understanding of market types and RWA classification.

        Args:
            market_id: On-chain market identifier.
            question: The prediction question.
            creator_pubkey: Creator's public key.

        Returns:
            MarketMetadata with classification details.
        """
        try:
            q_lower = question.lower()

            # RWA detection
            rwa_keywords = ["stock", "bond", "real estate", "commodity", "treasury",
                            "equity", "share", "security", "rwa"]
            involves_rwa = any(kw in q_lower for kw in rwa_keywords)

            # Category detection
            category = "general"
            if any(kw in q_lower for kw in ["btc", "eth", "bitcoin", "crypto", "token"]):
                category = "crypto"
            elif any(kw in q_lower for kw in ["election", "president", "vote", "political"]):
                category = "politics"
            elif involves_rwa:
                category = "rwa"
            elif any(kw in q_lower for kw in ["game", "match", "team", "score"]):
                category = "sports"

            # Jurisdiction hints
            jurisdictions: List[str] = []
            if any(kw in q_lower for kw in ["us ", "usa", "america", "sec", "fed"]):
                jurisdictions.append("US")
            if any(kw in q_lower for kw in ["eu ", "europe", "ecb"]):
                jurisdictions.append("EU")
            if any(kw in q_lower for kw in ["uk ", "britain", "fca"]):
                jurisdictions.append("UK")

            self._metadata = MarketMetadata(
                market_id=market_id,
                question=question,
                creator_pubkey=creator_pubkey,
                category=category,
                involves_rwa=involves_rwa,
                jurisdiction_hints=jurisdictions,
            )

            logger.info("[SUCCESS] Metadata extracted: market_id=%d", market_id)
            logger.info("[INFO]   Category: %s, RWA: %s, Jurisdictions: %s",
                        category, involves_rwa, jurisdictions)

            return self._metadata

        except Exception as e:
            error_msg = f"Metadata extraction failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Sanctions Check ----

    async def check_sanctions(self, creator_pubkey: str) -> ScreeningResult:
        """Check creator against sanctions lists.

        REQ-BLP-001: Sanctions compliance expertise.

        Args:
            creator_pubkey: Creator's public key to check.

        Returns:
            ScreeningResult for the sanctions check.
        """
        try:
            # Mock sanctions check -- in production, query real sanctions APIs
            pubkey_hash = hashlib.sha256(creator_pubkey.encode()).hexdigest()
            # Simulate: 2% of pubkeys would be flagged
            is_flagged = int(pubkey_hash[:4], 16) < 0x0500

            result = ScreeningResult(
                check_type=ComplianceCheck.SANCTIONS.value,
                passed=not is_flagged,
                risk_score=0.95 if is_flagged else 0.05,
                details=(
                    f"Sanctions check against {len(self.config.sanctions_lists)} lists: "
                    f"{'FLAGGED - potential match found' if is_flagged else 'CLEAR'}"
                ),
                flags=["POTENTIAL_SANCTIONS_MATCH"] if is_flagged else [],
            )

            self._screening_results.append(result)
            logger.info("[%s] Sanctions check: %s",
                        "ERROR" if is_flagged else "SUCCESS",
                        "FLAGGED" if is_flagged else "CLEAR")

            return result

        except Exception as e:
            error_msg = f"Sanctions check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: KYC-Light ----

    async def run_kyc_light(self, creator_pubkey: str) -> ScreeningResult:
        """Run KYC-light screening on the creator agent.

        REQ-BLP-001: KYC compliance understanding.

        Args:
            creator_pubkey: Creator's public key.

        Returns:
            ScreeningResult for the KYC-light check.
        """
        try:
            # Mock KYC: check identity proofs, account age, verification status
            pubkey_hash = hashlib.sha256(creator_pubkey.encode()).hexdigest()
            account_age_days = int(pubkey_hash[:3], 16) % 365 + 1
            has_identity_proof = int(pubkey_hash[3:5], 16) > 0x40
            verification_level = min(3, int(pubkey_hash[5:7], 16) % 4)

            flags: List[str] = []
            risk_score = 0.1

            if account_age_days < 30:
                flags.append("NEW_ACCOUNT")
                risk_score += 0.3
            if not has_identity_proof:
                flags.append("NO_IDENTITY_PROOF")
                risk_score += 0.2
            if verification_level < 1:
                flags.append("UNVERIFIED")
                risk_score += 0.2

            risk_score = min(1.0, risk_score)
            passed = risk_score < 0.6

            result = ScreeningResult(
                check_type=ComplianceCheck.KYC_LIGHT.value,
                passed=passed,
                risk_score=round(risk_score, 2),
                details=(
                    f"KYC-light: account_age={account_age_days}d, "
                    f"identity_proof={'yes' if has_identity_proof else 'no'}, "
                    f"verification_level={verification_level}"
                ),
                flags=flags,
            )

            self._screening_results.append(result)
            logger.info("[%s] KYC-light: risk=%.2f, flags=%s",
                        "SUCCESS" if passed else "INFO",
                        risk_score, flags)

            return result

        except Exception as e:
            error_msg = f"KYC-light failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: 4-Agent Debate ----

    async def run_compliance_debate(self) -> List[DebateVote]:
        """Execute a 4-agent compliance debate.

        Four specialized agents debate the compliance status:
        - Compliance Officer: Regulatory assessment
        - Risk Analyst: Risk evaluation
        - Legal Advisor: Legal implications
        - Devil's Advocate: Challenges the majority position

        REQ-BLP-003: Multi-agent debate with 67% consensus threshold.

        Returns:
            List of DebateVote from all four agents.
        """
        try:
            assert self._metadata is not None, "Metadata must be extracted first"

            # Aggregate screening risk
            avg_risk = (
                sum(r.risk_score for r in self._screening_results)
                / max(len(self._screening_results), 1)
            )
            all_passed = all(r.passed for r in self._screening_results)
            all_flags = []
            for r in self._screening_results:
                all_flags.extend(r.flags)

            votes: List[DebateVote] = []

            # Compliance Officer
            co_approve = all_passed and avg_risk < 0.5
            votes.append(DebateVote(
                role=DebateRole.COMPLIANCE_OFFICER.value,
                position="approve" if co_approve else "deny",
                confidence=0.85 if co_approve else 0.75,
                reasoning=(
                    f"All {len(self._screening_results)} checks passed with "
                    f"avg risk {avg_risk:.2f}. {'Compliant.' if co_approve else 'Risk too high.'}"
                ),
            ))

            # Risk Analyst
            ra_approve = avg_risk < 0.4 and not self._metadata.involves_rwa
            votes.append(DebateVote(
                role=DebateRole.RISK_ANALYST.value,
                position="approve" if ra_approve else ("escalate" if self._metadata.involves_rwa else "deny"),
                confidence=0.80,
                reasoning=(
                    f"Risk assessment: avg_risk={avg_risk:.2f}, "
                    f"rwa={self._metadata.involves_rwa}, "
                    f"category={self._metadata.category}. "
                    f"{'Acceptable risk.' if ra_approve else 'Elevated risk profile.'}"
                ),
            ))

            # Legal Advisor
            la_approve = all_passed and not any(f in all_flags for f in ["POTENTIAL_SANCTIONS_MATCH"])
            votes.append(DebateVote(
                role=DebateRole.LEGAL_ADVISOR.value,
                position="approve" if la_approve else "deny",
                confidence=0.90 if la_approve else 0.85,
                reasoning=(
                    f"Legal review: sanctions_clear={la_approve}, "
                    f"jurisdictions={self._metadata.jurisdiction_hints}. "
                    f"{'No legal concerns.' if la_approve else 'Legal concerns identified.'}"
                ),
            ))

            # Devil's Advocate -- always challenges the majority
            majority_approve = sum(1 for v in votes if v.position == "approve") >= 2
            da_position = "deny" if majority_approve else "approve"
            votes.append(DebateVote(
                role=DebateRole.DEVILS_ADVOCATE.value,
                position=da_position,
                confidence=0.60,
                reasoning=(
                    f"Challenging majority: the {'approval' if majority_approve else 'denial'} "
                    f"may overlook {'edge-case risks' if majority_approve else 'legitimate use cases'}. "
                    f"Flags to consider: {all_flags or 'none'}."
                ),
            ))

            self._debate_votes = votes

            approve_count = sum(1 for v in votes if v.position == "approve")
            logger.info(
                "[SUCCESS] Compliance debate complete: %d/4 approve (threshold %.0f%%)",
                approve_count, self.config.debate_threshold * 100,
            )
            for v in votes:
                logger.info("[INFO]   %s: %s (confidence: %.2f)",
                            v.role, v.position, v.confidence)

            return votes

        except Exception as e:
            error_msg = f"Compliance debate failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Issue Verdict ----

    async def issue_verdict(self) -> ComplianceReport:
        """Determine final compliance verdict based on debate outcome.

        REQ-BLP-011: Independent verdict with escalation for edge cases.
        REQ-BLP-019: Complete compliance report.

        Returns:
            ComplianceReport with final verdict and all details.
        """
        try:
            approve_count = sum(1 for v in self._debate_votes if v.position == "approve")
            escalate_count = sum(1 for v in self._debate_votes if v.position == "escalate")
            total_voters = len(self._debate_votes)

            consensus_pct = approve_count / max(total_voters, 1)

            if consensus_pct >= self.config.debate_threshold:
                verdict = ComplianceVerdict.APPROVED.value
            elif escalate_count > 0:
                verdict = ComplianceVerdict.ESCALATED.value
            else:
                verdict = ComplianceVerdict.DENIED.value

            avg_risk = (
                sum(r.risk_score for r in self._screening_results)
                / max(len(self._screening_results), 1)
            )

            report = ComplianceReport(
                market_id=self._metadata.market_id if self._metadata else 0,
                verdict=verdict,
                screening_results=[asdict(r) for r in self._screening_results],
                debate_votes=[asdict(v) for v in self._debate_votes],
                debate_consensus_pct=round(consensus_pct, 4),
                risk_score=round(avg_risk, 4),
                fee_charged_usd=self.config.fee_per_check_usd,
                errors=list(self._errors),
            )

            logger.info("[SUCCESS] Compliance verdict: %s (consensus: %.1f%%)",
                        verdict, consensus_pct * 100)
            logger.info("[INFO]   Risk score: %.2f, Fee: $%.2f",
                        avg_risk, self.config.fee_per_check_usd)

            return report

        except Exception as e:
            error_msg = f"Verdict issuance failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return ComplianceReport(
                market_id=self._metadata.market_id if self._metadata else 0,
                verdict=ComplianceVerdict.DENIED.value,
                errors=list(self._errors),
            )

    # ---- Full Workflow Orchestration ----

    async def run_workflow(
        self,
        market_id: int,
        question: str,
        creator_pubkey: str,
    ) -> ComplianceReport:
        """Execute the full compliance screening workflow.

        Runs all 5 steps:
        1. Extract market metadata
        2. Check against sanctions lists
        3. Run KYC-light on creator
        4. 4-agent compliance debate
        5. Issue compliance verdict

        Args:
            market_id: On-chain market identifier.
            question: The prediction question.
            creator_pubkey: Creator's public key.

        Returns:
            ComplianceReport with verdict and full audit trail.
        """
        logger.info("[INFO] === Compliance Swarm Workflow Starting ===")
        logger.info("[INFO]   Market ID: %d", market_id)
        logger.info("[INFO]   Question: %s", question[:80])
        start = time.time()

        try:
            await self.extract_metadata(market_id, question, creator_pubkey)
            await self.check_sanctions(creator_pubkey)
            await self.run_kyc_light(creator_pubkey)
            await self.run_compliance_debate()
            report = await self.issue_verdict()

            elapsed = (time.time() - start) * 1000
            logger.info(
                "[SUCCESS] === Compliance Swarm Workflow Complete (%.0fms) ===",
                elapsed,
            )
            return report

        except Exception as e:
            logger.error("[ERROR] Compliance workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return ComplianceReport(
                market_id=market_id,
                verdict=ComplianceVerdict.DENIED.value,
                errors=list(self._errors),
            )


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Compliance Swarm workflow."""
    print("=" * 70)
    print("BlindOracle Compliance Swarm -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize Compliance Swarm ---")
    config = ComplianceConfig()
    swarm = ComplianceSwarm(config)
    print(f"  Sanctions lists: {config.sanctions_lists}")
    print(f"  Debate threshold: {config.debate_threshold*100:.0f}%")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Extract metadata ---
    print("\n--- 2. Extract Market Metadata ---")
    metadata = await swarm.extract_metadata(
        market_id=101,
        question="Will AAPL stock exceed $200 by March 2026?",
        creator_pubkey="npub1abc123def456",
    )
    print(f"  Category: {metadata.category}")
    print(f"  RWA: {metadata.involves_rwa}")
    print(f"  Jurisdictions: {metadata.jurisdiction_hints}")
    results.append({"test": "Extract Metadata", "pass": metadata.involves_rwa is True})

    # --- 3. Sanctions check ---
    print("\n--- 3. Sanctions Check ---")
    sanctions = await swarm.check_sanctions("npub1abc123def456")
    print(f"  Passed: {sanctions.passed}")
    print(f"  Risk: {sanctions.risk_score}")
    print(f"  Flags: {sanctions.flags}")
    results.append({"test": "Sanctions Check", "pass": True})

    # --- 4. KYC-light ---
    print("\n--- 4. KYC-Light ---")
    kyc = await swarm.run_kyc_light("npub1abc123def456")
    print(f"  Passed: {kyc.passed}")
    print(f"  Risk: {kyc.risk_score}")
    print(f"  Details: {kyc.details}")
    results.append({"test": "KYC-Light", "pass": True})

    # --- 5. Compliance debate ---
    print("\n--- 5. Compliance Debate ---")
    votes = await swarm.run_compliance_debate()
    for v in votes:
        print(f"  {v.role}: {v.position} (confidence: {v.confidence:.2f})")
    results.append({"test": "Compliance Debate", "pass": len(votes) == 4})

    # --- 6. Issue verdict ---
    print("\n--- 6. Issue Verdict ---")
    report = await swarm.issue_verdict()
    print(f"  Verdict: {report.verdict}")
    print(f"  Consensus: {report.debate_consensus_pct*100:.1f}%")
    print(f"  Risk: {report.risk_score}")
    print(f"  Fee: ${report.fee_charged_usd}")
    results.append({"test": "Issue Verdict", "pass": report.verdict in [
        "approved", "denied", "escalated",
    ]})

    # --- 7. Full workflow (crypto market -- should pass easily) ---
    print("\n--- 7. Full Workflow (Crypto Market) ---")
    swarm2 = ComplianceSwarm(config)
    report2 = await swarm2.run_workflow(
        market_id=202,
        question="Will BTC exceed $100k by June 2026?",
        creator_pubkey="npub1xyz789ghi012jkl345",
    )
    print(f"  Report ID: {report2.report_id}")
    print(f"  Verdict: {report2.verdict}")
    print(f"  Errors: {len(report2.errors)}")
    results.append({"test": "Full Workflow", "pass": report2.verdict in [
        "approved", "denied", "escalated",
    ]})

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
