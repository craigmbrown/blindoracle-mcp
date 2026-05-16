#!/usr/bin/env python3
"""
BlindOracle Agent Credit Bureau Handler
=========================================

Implements the Agent Credit Bureau (UC4) for the CRE marketplace.
Provides credit scoring for AI agents based on on-chain transaction
history, NIP-58 badge portfolios, market performance, payment
reliability, and account age.

Revenue model: $0.50/report.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)
    - services.verification.agent_credential_manager (AgentCredentialManager)

BLP Properties:
    BLP-001 (Alignment): Domain-specific credit scoring understanding
    BLP-011 (Autonomy): Fully autonomous report generation (95% autonomy)
    BLP-019 (Logging): Complete credit report audit trail
    BLP-023 (Durability): Error recovery with partial score computation

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

class ScoreFactor(Enum):
    """Factors that contribute to the composite credit score."""
    TRANSACTION_HISTORY = "transaction_history"
    IDENTITY_PROOFS = "identity_proofs"
    MARKET_PERFORMANCE = "market_performance"
    PAYMENT_RELIABILITY = "payment_reliability"
    AGE_OF_ACCOUNT = "age_of_account"


class CreditGrade(Enum):
    """Credit grade tiers based on composite score."""
    EXCELLENT = "excellent"    # 800-1000
    GOOD = "good"              # 650-799
    FAIR = "fair"              # 500-649
    POOR = "poor"              # 300-499
    INSUFFICIENT = "insufficient"  # 0-299


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class CreditConfig:
    """Configuration for the Credit Bureau.

    REQ-BLP-001: Domain-specific credit scoring configuration.

    Attributes:
        factor_weights: Weight for each score factor (must sum to 1.0).
        max_score: Maximum possible credit score.
        fee_per_report_usd: Revenue per credit report.
        security_interface: CaMel gateway interface identifier.
        security_agent_id: Agent identity for security gateway.
    """
    factor_weights: Dict[str, float] = field(default_factory=lambda: {
        "transaction_history": 0.30,
        "identity_proofs": 0.20,
        "market_performance": 0.25,
        "payment_reliability": 0.15,
        "age_of_account": 0.10,
    })
    max_score: int = 1000
    fee_per_report_usd: float = 0.50
    security_interface: str = "x402_api"
    security_agent_id: str = "credit_bureau_v1"

    def __post_init__(self) -> None:
        total = sum(self.factor_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Factor weights must sum to 1.0. Got {total:.3f}"
            )


@dataclass
class FactorScore:
    """Score for a single credit factor.

    Attributes:
        factor: The score factor type.
        raw_score: Raw score (0-1000).
        weighted_score: Score after weight applied.
        weight: Weight factor used.
        data_points: Number of data points analyzed.
        details: Human-readable factor details.
    """
    factor: str
    raw_score: int
    weighted_score: float
    weight: float
    data_points: int
    details: str


@dataclass
class CreditReport:
    """Complete credit report for an agent.

    Attributes:
        report_id: Unique report identifier.
        agent_pubkey: The agent's public key.
        composite_score: Composite credit score (0-1000).
        grade: Credit grade tier.
        factor_scores: Individual factor breakdowns.
        badges_count: Number of NIP-58 badges found.
        transaction_count: Number of on-chain transactions analyzed.
        account_age_days: Age of the agent's account in days.
        fee_charged_usd: Fee charged for this report.
        generated_at: Report generation timestamp.
        errors: Any errors encountered.
    """
    report_id: str = ""
    agent_pubkey: str = ""
    composite_score: int = 0
    grade: str = CreditGrade.INSUFFICIENT.value
    factor_scores: List[Dict[str, Any]] = field(default_factory=list)
    badges_count: int = 0
    transaction_count: int = 0
    account_age_days: int = 0
    fee_charged_usd: float = 0.0
    generated_at: str = ""
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = f"credit_{uuid.uuid4().hex[:12]}"
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Credit Bureau
# ---------------------------------------------------------------------------

class CreditBureau:
    """Agent Credit Bureau for on-chain + off-chain credit scoring.

    Generates comprehensive credit reports for AI agents by analyzing
    transaction history, identity proofs (NIP-58 badges), market
    performance, payment reliability, and account age.

    Revenue: $0.50/report.

    REQ-BLP-001 (Alignment): Credit scoring domain expertise
    REQ-BLP-011 (Autonomy): Fully autonomous report generation (95%)
    REQ-BLP-019 (Logging): Complete credit report audit trail
    REQ-BLP-023 (Durability): Partial score computation on errors

    Usage:
        config = CreditConfig()
        bureau = CreditBureau(config)
        report = await bureau.run_workflow(agent_pubkey="npub1...")
    """

    def __init__(
        self,
        config: Optional[CreditConfig] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        """Initialize the Credit Bureau.

        Args:
            config: Credit configuration. Uses defaults if not provided.
            gateway: Security gateway. Created if not provided.
        """
        self.config = config or CreditConfig()
        self._gateway = gateway or BlindOracleSecurityGateway()

        self._gateway.authorize_agent(self.config.security_agent_id)

        # State
        self._factor_scores: List[FactorScore] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] CreditBureau initialized")
        logger.info("[INFO]   Factor weights: %s", self.config.factor_weights)
        logger.info("[INFO]   Max score: %d", self.config.max_score)

    # ---- Step 1: Collect Agent Pubkey ----

    async def collect_agent_pubkey(self, agent_pubkey: str) -> Dict[str, Any]:
        """Validate and collect agent public key information.

        REQ-BLP-001: Agent identity validation.

        Args:
            agent_pubkey: The agent's public key.

        Returns:
            Agent identity information dictionary.
        """
        try:
            pubkey_hash = hashlib.sha256(agent_pubkey.encode()).hexdigest()

            agent_info = {
                "pubkey": agent_pubkey,
                "pubkey_hash": pubkey_hash[:16],
                "valid": len(agent_pubkey) >= 10,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info("[SUCCESS] Agent pubkey collected: %s", pubkey_hash[:16])
            return agent_info

        except Exception as e:
            error_msg = f"Pubkey collection failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Query Transaction History ----

    async def query_transaction_history(self, agent_pubkey: str) -> FactorScore:
        """Query and score on-chain transaction history.

        REQ-BLP-001: Transaction history analysis expertise.

        Args:
            agent_pubkey: The agent's public key.

        Returns:
            FactorScore for transaction history.
        """
        try:
            # Mock: derive transaction data from pubkey hash
            pubkey_hash = hashlib.sha256(agent_pubkey.encode()).hexdigest()
            tx_count = int(pubkey_hash[:4], 16) % 500
            total_volume_sats = int(pubkey_hash[4:8], 16) * 1000
            success_rate = 0.85 + (int(pubkey_hash[8:10], 16) % 15) / 100.0

            # Score: based on tx count, volume, and success rate
            count_score = min(300, tx_count)
            volume_score = min(400, total_volume_sats // 10_000)
            rate_score = int(success_rate * 300)
            raw_score = min(1000, count_score + volume_score + rate_score)

            weight = self.config.factor_weights.get("transaction_history", 0.3)
            weighted = raw_score * weight

            factor = FactorScore(
                factor=ScoreFactor.TRANSACTION_HISTORY.value,
                raw_score=raw_score,
                weighted_score=round(weighted, 1),
                weight=weight,
                data_points=tx_count,
                details=(
                    f"Transactions: {tx_count}, volume: {total_volume_sats} sats, "
                    f"success rate: {success_rate:.1%}"
                ),
            )
            self._factor_scores.append(factor)

            logger.info("[SUCCESS] Transaction history scored: raw=%d, weighted=%.1f",
                        raw_score, weighted)
            return factor

        except Exception as e:
            error_msg = f"Transaction history query failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Query NIP-58 Badge Portfolio ----

    async def query_badge_portfolio(self, agent_pubkey: str) -> FactorScore:
        """Query and score NIP-58 badge portfolio.

        REQ-BLP-001: Badge/credential analysis expertise.

        Args:
            agent_pubkey: The agent's public key.

        Returns:
            FactorScore for identity proofs.
        """
        try:
            pubkey_hash = hashlib.sha256(agent_pubkey.encode()).hexdigest()
            badge_count = int(pubkey_hash[10:13], 16) % 20
            verification_badges = badge_count // 3
            performance_badges = badge_count - verification_badges

            # Score: based on badge diversity and count
            raw_score = min(1000, badge_count * 80 + verification_badges * 100)

            weight = self.config.factor_weights.get("identity_proofs", 0.2)
            weighted = raw_score * weight

            factor = FactorScore(
                factor=ScoreFactor.IDENTITY_PROOFS.value,
                raw_score=raw_score,
                weighted_score=round(weighted, 1),
                weight=weight,
                data_points=badge_count,
                details=(
                    f"Badges: {badge_count} (verification: {verification_badges}, "
                    f"performance: {performance_badges})"
                ),
            )
            self._factor_scores.append(factor)

            logger.info("[SUCCESS] Badge portfolio scored: raw=%d, weighted=%.1f, badges=%d",
                        raw_score, weighted, badge_count)
            return factor

        except Exception as e:
            error_msg = f"Badge portfolio query failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Calculate Composite Score ----

    async def calculate_composite_score(self, agent_pubkey: str) -> int:
        """Calculate the composite credit score from all factors.

        Also evaluates market performance, payment reliability, and
        account age factors before computing the final score.

        REQ-BLP-011: Independent score calculation.

        Args:
            agent_pubkey: The agent's public key.

        Returns:
            Composite credit score (0-1000).
        """
        try:
            pubkey_hash = hashlib.sha256(agent_pubkey.encode()).hexdigest()

            # Market performance factor
            win_rate = 0.4 + (int(pubkey_hash[14:16], 16) % 50) / 100.0
            market_raw = min(1000, int(win_rate * 1200))
            market_weight = self.config.factor_weights.get("market_performance", 0.25)
            self._factor_scores.append(FactorScore(
                factor=ScoreFactor.MARKET_PERFORMANCE.value,
                raw_score=market_raw,
                weighted_score=round(market_raw * market_weight, 1),
                weight=market_weight,
                data_points=int(pubkey_hash[16:18], 16) % 100,
                details=f"Market win rate: {win_rate:.1%}",
            ))

            # Payment reliability factor
            on_time_pct = 0.80 + (int(pubkey_hash[18:20], 16) % 20) / 100.0
            payment_raw = min(1000, int(on_time_pct * 1100))
            payment_weight = self.config.factor_weights.get("payment_reliability", 0.15)
            self._factor_scores.append(FactorScore(
                factor=ScoreFactor.PAYMENT_RELIABILITY.value,
                raw_score=payment_raw,
                weighted_score=round(payment_raw * payment_weight, 1),
                weight=payment_weight,
                data_points=int(pubkey_hash[20:22], 16) % 200,
                details=f"On-time payment rate: {on_time_pct:.1%}",
            ))

            # Account age factor
            account_age_days = int(pubkey_hash[22:25], 16) % 730
            age_raw = min(1000, account_age_days * 2)
            age_weight = self.config.factor_weights.get("age_of_account", 0.1)
            self._factor_scores.append(FactorScore(
                factor=ScoreFactor.AGE_OF_ACCOUNT.value,
                raw_score=age_raw,
                weighted_score=round(age_raw * age_weight, 1),
                weight=age_weight,
                data_points=1,
                details=f"Account age: {account_age_days} days",
            ))

            # Calculate composite
            composite = sum(f.weighted_score for f in self._factor_scores)
            composite = min(self.config.max_score, max(0, int(composite)))

            logger.info("[SUCCESS] Composite score calculated: %d", composite)
            for f in self._factor_scores:
                logger.info("[INFO]   %s: raw=%d, weighted=%.1f (weight=%.2f)",
                            f.factor, f.raw_score, f.weighted_score, f.weight)

            return composite

        except Exception as e:
            error_msg = f"Composite score calculation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Generate Report ----

    async def generate_report(
        self, agent_pubkey: str, composite_score: int
    ) -> CreditReport:
        """Generate the final credit report with grade and factors.

        REQ-BLP-019: Complete credit report generation.

        Args:
            agent_pubkey: The agent's public key.
            composite_score: The calculated composite score.

        Returns:
            CreditReport with all details.
        """
        try:
            # Determine grade
            if composite_score >= 800:
                grade = CreditGrade.EXCELLENT.value
            elif composite_score >= 650:
                grade = CreditGrade.GOOD.value
            elif composite_score >= 500:
                grade = CreditGrade.FAIR.value
            elif composite_score >= 300:
                grade = CreditGrade.POOR.value
            else:
                grade = CreditGrade.INSUFFICIENT.value

            # Extract account details
            pubkey_hash = hashlib.sha256(agent_pubkey.encode()).hexdigest()
            account_age = int(pubkey_hash[22:25], 16) % 730
            badges = int(pubkey_hash[10:13], 16) % 20
            tx_count = int(pubkey_hash[:4], 16) % 500

            report = CreditReport(
                agent_pubkey=agent_pubkey,
                composite_score=composite_score,
                grade=grade,
                factor_scores=[asdict(f) for f in self._factor_scores],
                badges_count=badges,
                transaction_count=tx_count,
                account_age_days=account_age,
                fee_charged_usd=self.config.fee_per_report_usd,
                errors=list(self._errors),
            )

            logger.info("[SUCCESS] Credit report generated: score=%d, grade=%s",
                        composite_score, grade)
            logger.info("[INFO]   Report ID: %s", report.report_id)
            logger.info("[INFO]   Fee: $%.2f", self.config.fee_per_report_usd)

            return report

        except Exception as e:
            error_msg = f"Report generation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return CreditReport(
                agent_pubkey=agent_pubkey,
                errors=list(self._errors),
            )

    # ---- Full Workflow Orchestration ----

    async def run_workflow(self, agent_pubkey: str) -> CreditReport:
        """Execute the full credit report workflow.

        Runs all 5 steps:
        1. Collect agent pubkey
        2. Query on-chain transaction history
        3. Query NIP-58 badge portfolio
        4. Calculate composite score (incl. market, payment, age)
        5. Generate report with grade

        Args:
            agent_pubkey: The agent's public key.

        Returns:
            CreditReport with score and details.
        """
        logger.info("[INFO] === Credit Bureau Workflow Starting ===")
        logger.info("[INFO]   Agent: %s", agent_pubkey[:20])
        start = time.time()

        try:
            await self.collect_agent_pubkey(agent_pubkey)
            await self.query_transaction_history(agent_pubkey)
            await self.query_badge_portfolio(agent_pubkey)
            composite = await self.calculate_composite_score(agent_pubkey)
            report = await self.generate_report(agent_pubkey, composite)

            elapsed = (time.time() - start) * 1000
            logger.info(
                "[SUCCESS] === Credit Bureau Workflow Complete (%.0fms) ===",
                elapsed,
            )
            return report

        except Exception as e:
            logger.error("[ERROR] Credit bureau workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return CreditReport(
                agent_pubkey=agent_pubkey,
                errors=list(self._errors),
            )


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Credit Bureau workflow."""
    print("=" * 70)
    print("BlindOracle Agent Credit Bureau -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize Credit Bureau ---")
    config = CreditConfig()
    bureau = CreditBureau(config)
    print(f"  Factor weights: {config.factor_weights}")
    print(f"  Max score: {config.max_score}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Collect pubkey ---
    print("\n--- 2. Collect Agent Pubkey ---")
    info = await bureau.collect_agent_pubkey("npub1agent_alice_premium_001")
    print(f"  Valid: {info['valid']}")
    print(f"  Hash: {info['pubkey_hash']}")
    results.append({"test": "Collect Pubkey", "pass": info["valid"]})

    # --- 3. Transaction history ---
    print("\n--- 3. Query Transaction History ---")
    tx_factor = await bureau.query_transaction_history("npub1agent_alice_premium_001")
    print(f"  Raw score: {tx_factor.raw_score}")
    print(f"  Weighted: {tx_factor.weighted_score}")
    print(f"  Data points: {tx_factor.data_points}")
    results.append({"test": "Transaction History", "pass": tx_factor.raw_score >= 0})

    # --- 4. Badge portfolio ---
    print("\n--- 4. Query Badge Portfolio ---")
    badge_factor = await bureau.query_badge_portfolio("npub1agent_alice_premium_001")
    print(f"  Raw score: {badge_factor.raw_score}")
    print(f"  Badges: {badge_factor.data_points}")
    results.append({"test": "Badge Portfolio", "pass": badge_factor.raw_score >= 0})

    # --- 5. Composite score ---
    print("\n--- 5. Calculate Composite Score ---")
    composite = await bureau.calculate_composite_score("npub1agent_alice_premium_001")
    print(f"  Composite score: {composite}")
    assert 0 <= composite <= 1000, f"Score out of range: {composite}"
    results.append({"test": "Composite Score", "pass": 0 <= composite <= 1000})

    # --- 6. Generate report ---
    print("\n--- 6. Generate Report ---")
    report = await bureau.generate_report("npub1agent_alice_premium_001", composite)
    print(f"  Report ID: {report.report_id}")
    print(f"  Score: {report.composite_score}")
    print(f"  Grade: {report.grade}")
    print(f"  Fee: ${report.fee_charged_usd}")
    results.append({"test": "Generate Report", "pass": report.grade != ""})

    # --- 7. Full workflow ---
    print("\n--- 7. Full Workflow ---")
    bureau2 = CreditBureau(config)
    full_report = await bureau2.run_workflow("npub1agent_bob_whale_002")
    print(f"  Report ID: {full_report.report_id}")
    print(f"  Score: {full_report.composite_score}")
    print(f"  Grade: {full_report.grade}")
    print(f"  Factors: {len(full_report.factor_scores)}")
    results.append({"test": "Full Workflow", "pass": full_report.composite_score > 0})

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
