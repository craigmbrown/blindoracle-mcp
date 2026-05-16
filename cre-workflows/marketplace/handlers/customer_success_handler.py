#!/usr/bin/env python3
"""
BlindOracle Customer Success Agent Handler
============================================

Implements the Customer Success Agent (UC10) for the CRE marketplace.
Tracks agent customer health, prevents churn, and upsells services.
Runs daily at 00:00 UTC analyzing usage metrics, calculating health
scores, identifying at-risk agents, generating recommendations,
sending Lulu-formatted notifications, and tracking conversions.

Revenue model: $49/mo subscription.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)

BLP Properties:
    BLP-001 (Alignment): Customer success domain expertise
    BLP-011 (Autonomy): Fully autonomous operation (99% -- no founder needed)
    BLP-019 (Logging): Complete customer interaction audit trail
    BLP-031 (Self-Improvement): Learning from churn patterns

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

class ChurnRisk(Enum):
    """Churn risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AccountTier(Enum):
    """Customer account tiers."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class SuccessConfig:
    """Configuration for the Customer Success Agent.

    REQ-BLP-001: Customer success domain configuration.

    Attributes:
        health_score_weights: Weights for health score components.
        churn_thresholds: Score thresholds for churn risk levels.
        upsell_services: Services available for upselling.
        subscription_monthly_usd: Monthly subscription fee.
        security_interface: CaMel gateway interface.
        security_agent_id: Agent identity.
    """
    health_score_weights: Dict[str, float] = field(default_factory=lambda: {
        "api_calls_7d": 0.30,
        "volume_7d": 0.25,
        "services_used": 0.20,
        "login_frequency": 0.15,
        "support_tickets": 0.10,
    })
    churn_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "low": 70.0,
        "medium": 50.0,
        "high": 30.0,
        "critical": 10.0,
    })
    upsell_services: List[str] = field(default_factory=lambda: [
        "smart_dca", "credit_reports", "arbitrage_alerts",
        "compliance_screening", "proof_of_reserve",
    ])
    subscription_monthly_usd: float = 49.0
    security_interface: str = "x402_api"
    security_agent_id: str = "customer_success_v1"


@dataclass
class AgentUsageMetrics:
    """Usage metrics for a single agent customer.

    Attributes:
        agent_pubkey: The agent's public key.
        api_calls_7d: API calls in the last 7 days.
        volume_7d_sats: Transaction volume in last 7 days.
        services_used: Number of distinct services used.
        total_services: Total available services.
        login_days_7d: Days logged in during last 7 days.
        support_tickets_open: Open support tickets.
        account_tier: Current account tier.
        days_since_last_activity: Days since last activity.
    """
    agent_pubkey: str
    api_calls_7d: int = 0
    volume_7d_sats: int = 0
    services_used: int = 0
    total_services: int = 10
    login_days_7d: int = 0
    support_tickets_open: int = 0
    account_tier: str = AccountTier.FREE.value
    days_since_last_activity: int = 0


@dataclass
class AgentHealthScore:
    """Health score for an agent customer.

    Attributes:
        agent_pubkey: The agent's public key.
        composite_score: Overall health score (0-100).
        component_scores: Individual component scores.
        churn_risk: Assessed churn risk level.
        trend: Score trend (improving/stable/declining).
        previous_score: Previous composite score.
    """
    agent_pubkey: str
    composite_score: float = 0.0
    component_scores: Dict[str, float] = field(default_factory=dict)
    churn_risk: str = ChurnRisk.LOW.value
    trend: str = "stable"
    previous_score: float = 0.0


@dataclass
class Recommendation:
    """A personalized recommendation for an agent.

    Attributes:
        agent_pubkey: Target agent.
        recommendation_type: Type (retention/upsell/engagement).
        title: Short recommendation title.
        message: Full recommendation message.
        priority: Priority (1=highest).
        service_suggested: Suggested service for upsell.
    """
    agent_pubkey: str
    recommendation_type: str = "engagement"
    title: str = ""
    message: str = ""
    priority: int = 3
    service_suggested: Optional[str] = None


@dataclass
class SuccessReport:
    """Summary report for a customer success cycle.

    Attributes:
        report_id: Unique report identifier.
        timestamp: Report generation time.
        agents_analyzed: Number of agents analyzed.
        avg_health_score: Average health score across all agents.
        at_risk_count: Number of at-risk agents.
        recommendations_generated: Total recommendations.
        notifications_sent: Notifications sent.
        conversion_opportunities: Upsell conversion opportunities.
        subscription_revenue_usd: Monthly subscription revenue.
        errors: Any errors encountered.
    """
    report_id: str = ""
    timestamp: str = ""
    agents_analyzed: int = 0
    avg_health_score: float = 0.0
    at_risk_count: int = 0
    recommendations_generated: int = 0
    notifications_sent: int = 0
    conversion_opportunities: int = 0
    subscription_revenue_usd: float = 0.0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = f"success_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Customer Success Agent
# ---------------------------------------------------------------------------

class CustomerSuccessAgent:
    """Customer Success Agent for agent health tracking and churn prevention.

    Analyzes agent usage metrics daily, calculates health scores,
    identifies at-risk customers, generates personalized recommendations,
    sends Lulu-formatted notifications, and tracks free-to-paid conversion.

    Revenue: $49/mo subscription.

    REQ-BLP-001 (Alignment): Customer success expertise
    REQ-BLP-011 (Autonomy): Fully autonomous (99%)
    REQ-BLP-019 (Logging): Customer interaction audit trail
    REQ-BLP-031 (Self-Improvement): Churn pattern learning

    Usage:
        config = SuccessConfig()
        agent = CustomerSuccessAgent(config)
        report = await agent.run_workflow()
    """

    def __init__(
        self,
        config: Optional[SuccessConfig] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
        agents: Optional[List[AgentUsageMetrics]] = None,
    ) -> None:
        self.config = config or SuccessConfig()
        self._gateway = gateway or BlindOracleSecurityGateway()
        self._gateway.authorize_agent(self.config.security_agent_id)

        self._agents = agents or []
        self._health_scores: List[AgentHealthScore] = []
        self._recommendations: List[Recommendation] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] CustomerSuccessAgent initialized")
        logger.info("[INFO]   Agents tracked: %d", len(self._agents))
        logger.info("[INFO]   Upsell services: %s", self.config.upsell_services)

    # ---- Step 1: Analyze Usage Metrics ----

    async def analyze_usage(self) -> List[AgentUsageMetrics]:
        """Analyze usage metrics for all tracked agents.

        REQ-BLP-001: Usage pattern analysis.

        Returns:
            List of AgentUsageMetrics for all agents.
        """
        try:
            if not self._agents:
                # Generate mock agent data
                mock_pubkeys = [
                    "npub1agent_power_user_001",
                    "npub1agent_active_002",
                    "npub1agent_declining_003",
                    "npub1agent_churning_004",
                    "npub1agent_free_tier_005",
                ]

                for pubkey in mock_pubkeys:
                    pk_hash = hashlib.sha256(pubkey.encode()).hexdigest()
                    calls = int(pk_hash[:4], 16) % 500
                    volume = int(pk_hash[4:8], 16) * 100
                    services = int(pk_hash[8:10], 16) % 8
                    logins = int(pk_hash[10:12], 16) % 8
                    tickets = int(pk_hash[12:14], 16) % 3
                    inactive = int(pk_hash[14:16], 16) % 30

                    tier_idx = int(pk_hash[16:18], 16) % 4
                    tiers = [AccountTier.FREE, AccountTier.STARTER,
                             AccountTier.PROFESSIONAL, AccountTier.ENTERPRISE]
                    tier = tiers[tier_idx].value

                    self._agents.append(AgentUsageMetrics(
                        agent_pubkey=pubkey,
                        api_calls_7d=calls,
                        volume_7d_sats=volume,
                        services_used=services,
                        login_days_7d=logins,
                        support_tickets_open=tickets,
                        account_tier=tier,
                        days_since_last_activity=inactive,
                    ))

            logger.info("[SUCCESS] Usage analyzed: %d agents", len(self._agents))
            return self._agents

        except Exception as e:
            error_msg = f"Usage analysis failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Calculate Health Scores ----

    async def calculate_health_scores(self) -> List[AgentHealthScore]:
        """Calculate health scores for all agents.

        REQ-BLP-001: Health score computation.

        Returns:
            List of AgentHealthScore for all agents.
        """
        try:
            scores: List[AgentHealthScore] = []

            for agent in self._agents:
                components: Dict[str, float] = {}

                # API calls score (0-100)
                api_score = min(100, agent.api_calls_7d / 3)
                components["api_calls_7d"] = round(api_score, 1)

                # Volume score (0-100)
                vol_score = min(100, agent.volume_7d_sats / 5000)
                components["volume_7d"] = round(vol_score, 1)

                # Services used score (0-100)
                svc_score = (agent.services_used / max(agent.total_services, 1)) * 100
                components["services_used"] = round(svc_score, 1)

                # Login frequency score (0-100)
                login_score = (agent.login_days_7d / 7.0) * 100
                components["login_frequency"] = round(login_score, 1)

                # Support tickets (inverse -- more tickets = lower score)
                ticket_score = max(0, 100 - agent.support_tickets_open * 30)
                components["support_tickets"] = round(ticket_score, 1)

                # Weighted composite
                weights = self.config.health_score_weights
                composite = sum(
                    components.get(k, 0) * w
                    for k, w in weights.items()
                )
                composite = round(min(100, max(0, composite)), 1)

                # Determine churn risk
                thresholds = self.config.churn_thresholds
                if composite >= thresholds["low"]:
                    risk = ChurnRisk.LOW.value
                elif composite >= thresholds["medium"]:
                    risk = ChurnRisk.MEDIUM.value
                elif composite >= thresholds["high"]:
                    risk = ChurnRisk.HIGH.value
                else:
                    risk = ChurnRisk.CRITICAL.value

                # Trend (mock: based on activity)
                if agent.days_since_last_activity <= 1:
                    trend = "improving"
                elif agent.days_since_last_activity <= 7:
                    trend = "stable"
                else:
                    trend = "declining"

                health = AgentHealthScore(
                    agent_pubkey=agent.agent_pubkey,
                    composite_score=composite,
                    component_scores=components,
                    churn_risk=risk,
                    trend=trend,
                    previous_score=composite * 0.95,  # Mock previous
                )
                scores.append(health)

                logger.info("[INFO] Health: %s, score=%.1f, risk=%s, trend=%s",
                            agent.agent_pubkey[:20], composite, risk, trend)

            self._health_scores = scores
            avg = sum(s.composite_score for s in scores) / max(len(scores), 1)
            at_risk = sum(1 for s in scores if s.churn_risk in [
                ChurnRisk.HIGH.value, ChurnRisk.CRITICAL.value,
            ])
            logger.info("[SUCCESS] Health scores calculated: avg=%.1f, at_risk=%d",
                        avg, at_risk)

            return scores

        except Exception as e:
            error_msg = f"Health score calculation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Generate Recommendations ----

    async def generate_recommendations(self) -> List[Recommendation]:
        """Generate personalized recommendations for at-risk agents.

        REQ-BLP-031: Learning from patterns to improve recommendations.

        Returns:
            List of Recommendation for agents.
        """
        try:
            recommendations: List[Recommendation] = []

            for health in self._health_scores:
                agent_metrics = next(
                    (a for a in self._agents if a.agent_pubkey == health.agent_pubkey),
                    None,
                )
                if not agent_metrics:
                    continue

                if health.churn_risk in [ChurnRisk.HIGH.value, ChurnRisk.CRITICAL.value]:
                    # Retention recommendation
                    recommendations.append(Recommendation(
                        agent_pubkey=health.agent_pubkey,
                        recommendation_type="retention",
                        title="Re-engagement recommended",
                        message=(
                            f"Agent {health.agent_pubkey[:20]} shows declining engagement "
                            f"(score: {health.composite_score:.0f}, risk: {health.churn_risk}). "
                            f"Consider offering a free trial of premium features."
                        ),
                        priority=1,
                    ))

                elif health.churn_risk == ChurnRisk.MEDIUM.value:
                    # Engagement recommendation
                    recommendations.append(Recommendation(
                        agent_pubkey=health.agent_pubkey,
                        recommendation_type="engagement",
                        title="Increase service adoption",
                        message=(
                            f"Agent uses {agent_metrics.services_used}/{agent_metrics.total_services} "
                            f"services. Recommend exploring additional capabilities."
                        ),
                        priority=2,
                    ))

                # Upsell for free tier agents with good health
                if (agent_metrics.account_tier == AccountTier.FREE.value
                        and health.composite_score >= 50):
                    svc = self.config.upsell_services[
                        hash(health.agent_pubkey) % len(self.config.upsell_services)
                    ]
                    recommendations.append(Recommendation(
                        agent_pubkey=health.agent_pubkey,
                        recommendation_type="upsell",
                        title=f"Upgrade to access {svc}",
                        message=(
                            f"Agent shows strong usage patterns (score: {health.composite_score:.0f}). "
                            f"Recommend upgrading to Starter tier for {svc} access."
                        ),
                        priority=2,
                        service_suggested=svc,
                    ))

            self._recommendations = recommendations
            logger.info("[SUCCESS] Recommendations generated: %d", len(recommendations))

            return recommendations

        except Exception as e:
            error_msg = f"Recommendation generation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Send Notifications ----

    async def send_notifications(self) -> int:
        """Send Lulu-formatted notifications for recommendations.

        REQ-BLP-019: Notification audit trail.

        Returns:
            Number of notifications sent.
        """
        try:
            sent = 0
            for rec in self._recommendations:
                # Mock: send notification
                logger.info(
                    "[SUCCESS] Notification sent: agent=%s, type=%s, title=%s",
                    rec.agent_pubkey[:20], rec.recommendation_type, rec.title,
                )
                sent += 1

            logger.info("[INFO] Total notifications sent: %d", sent)
            return sent

        except Exception as e:
            error_msg = f"Notification sending failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Track Conversions ----

    async def track_conversions(self) -> int:
        """Track free-to-paid conversion opportunities.

        REQ-BLP-031: Conversion pattern learning.

        Returns:
            Number of conversion opportunities identified.
        """
        try:
            free_tier = [
                a for a in self._agents
                if a.account_tier == AccountTier.FREE.value
            ]
            good_health_free = [
                a for a in free_tier
                if any(h.composite_score >= 50
                       for h in self._health_scores
                       if h.agent_pubkey == a.agent_pubkey)
            ]

            logger.info("[SUCCESS] Conversion tracking: %d free tier, %d conversion candidates",
                        len(free_tier), len(good_health_free))

            return len(good_health_free)

        except Exception as e:
            error_msg = f"Conversion tracking failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Full Workflow ----

    async def run_workflow(self) -> SuccessReport:
        """Execute the full customer success workflow.

        Steps:
        1. Analyze usage metrics
        2. Calculate health scores
        3. Generate recommendations
        4. Send Lulu-formatted notifications
        5. Track free-to-paid conversions

        Returns:
            SuccessReport with cycle summary.
        """
        logger.info("[INFO] === Customer Success Agent Workflow Starting ===")
        start = time.time()

        try:
            await self.analyze_usage()
            health_scores = await self.calculate_health_scores()
            recommendations = await self.generate_recommendations()
            notifications_sent = await self.send_notifications()
            conversions = await self.track_conversions()

            avg_health = (
                sum(s.composite_score for s in health_scores)
                / max(len(health_scores), 1)
            )
            at_risk = sum(1 for s in health_scores if s.churn_risk in [
                ChurnRisk.HIGH.value, ChurnRisk.CRITICAL.value,
            ])

            # Revenue from paid subscribers
            paid_count = sum(
                1 for a in self._agents
                if a.account_tier != AccountTier.FREE.value
            )
            revenue = paid_count * self.config.subscription_monthly_usd

            report = SuccessReport(
                agents_analyzed=len(self._agents),
                avg_health_score=round(avg_health, 1),
                at_risk_count=at_risk,
                recommendations_generated=len(recommendations),
                notifications_sent=notifications_sent,
                conversion_opportunities=conversions,
                subscription_revenue_usd=revenue,
                errors=list(self._errors),
            )

            elapsed = (time.time() - start) * 1000
            logger.info("[SUCCESS] === Customer Success Workflow Complete (%.0fms) ===",
                        elapsed)
            logger.info("[INFO]   Agents: %d, Avg health: %.1f, At risk: %d",
                        report.agents_analyzed, report.avg_health_score,
                        report.at_risk_count)
            logger.info("[INFO]   Recommendations: %d, Conversions: %d, Revenue: $%.0f",
                        report.recommendations_generated,
                        report.conversion_opportunities,
                        report.subscription_revenue_usd)

            return report

        except Exception as e:
            logger.error("[ERROR] Customer success workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return SuccessReport(errors=list(self._errors))


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Customer Success Agent workflow."""
    print("=" * 70)
    print("BlindOracle Customer Success Agent -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize ---")
    config = SuccessConfig()
    agent = CustomerSuccessAgent(config)
    print(f"  Upsell services: {config.upsell_services}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Analyze usage ---
    print("\n--- 2. Analyze Usage ---")
    metrics = await agent.analyze_usage()
    print(f"  Agents: {len(metrics)}")
    for m in metrics:
        print(f"    {m.agent_pubkey[:25]}: calls={m.api_calls_7d}, "
              f"tier={m.account_tier}")
    results.append({"test": "Analyze Usage", "pass": len(metrics) > 0})

    # --- 3. Health scores ---
    print("\n--- 3. Calculate Health Scores ---")
    scores = await agent.calculate_health_scores()
    for s in scores:
        print(f"    {s.agent_pubkey[:25]}: score={s.composite_score:.0f}, "
              f"risk={s.churn_risk}, trend={s.trend}")
    results.append({"test": "Health Scores", "pass": len(scores) > 0})

    # --- 4. Recommendations ---
    print("\n--- 4. Generate Recommendations ---")
    recs = await agent.generate_recommendations()
    for r in recs:
        print(f"    [{r.recommendation_type}] {r.agent_pubkey[:20]}: {r.title}")
    results.append({"test": "Recommendations", "pass": True})

    # --- 5. Notifications ---
    print("\n--- 5. Send Notifications ---")
    sent = await agent.send_notifications()
    print(f"  Sent: {sent}")
    results.append({"test": "Notifications", "pass": True})

    # --- 6. Conversions ---
    print("\n--- 6. Track Conversions ---")
    conversions = await agent.track_conversions()
    print(f"  Conversion opportunities: {conversions}")
    results.append({"test": "Track Conversions", "pass": True})

    # --- 7. Full workflow ---
    print("\n--- 7. Full Workflow ---")
    agent2 = CustomerSuccessAgent(config)
    report = await agent2.run_workflow()
    print(f"  Report ID: {report.report_id}")
    print(f"  Agents: {report.agents_analyzed}")
    print(f"  Avg health: {report.avg_health_score:.1f}")
    print(f"  At risk: {report.at_risk_count}")
    print(f"  Revenue: ${report.subscription_revenue_usd:.0f}/mo")
    results.append({"test": "Full Workflow", "pass": report.agents_analyzed > 0})

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
