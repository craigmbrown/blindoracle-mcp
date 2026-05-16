#!/usr/bin/env python3
"""
Research Agent Marketplace Integration
=======================================

Integrates Enhanced Research Agent Negotiation System with Job Marketplace
for automated fact-checking research jobs with Byzantine consensus.

@requirement: REQ-RESEARCH-001 - Multi-agent research with fact-checking debates
@requirement: REQ-RESEARCH-002 - Byzantine consensus (67% threshold)
@requirement: REQ-RESEARCH-003 - V4 Memory integration for pattern learning
@requirement: REQ-JOB-001 - Job marketplace integration
@requirement: REQ-MCP-003 - All exceptions print full details
@requirement: REQ-MCP-004 - Success responses logged before return
"""

import os
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.whatsapp_notifier import WhatsAppNotifier
from core.job_marketplace import JobMarketplace, Job
from core.base_level_properties import PropertyTracker

# Import BTC integration modules
try:
    sys.path.append(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    )
    from btc_integration import FedimintManager, FedimintBTCBridge

    FEDIMINT_AVAILABLE = True
except ImportError:
    FEDIMINT_AVAILABLE = False
    print("⚠️ Fedimint module not available")


@dataclass
class ResearchAgent:
    """Specialized research agent with role and expertise"""

    id: str
    name: str
    role: str
    expertise: List[str]
    confidence_threshold: float = 0.7
    challenges_issued: int = 0
    challenges_won: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "expertise": self.expertise,
            "confidence_threshold": self.confidence_threshold,
            "challenges_issued": self.challenges_issued,
            "challenges_won": self.challenges_won,
        }


@dataclass
class ResearchFinding:
    """Research finding with consensus tracking"""

    claim: str
    source: str
    confidence: float
    agent_id: str
    votes: Dict[str, str] = field(default_factory=dict)  # agent_id -> ACCEPT/REJECT/ABSTAIN
    consensus_score: float = 0.0
    validated: bool = False
    challenges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "source": self.source,
            "confidence": self.confidence,
            "agent_id": self.agent_id,
            "votes": self.votes,
            "consensus_score": self.consensus_score,
            "validated": self.validated,
            "challenges": self.challenges,
        }


@dataclass
class ResearchJob(Job):
    """Extended job type for research with debate requirements"""

    topic: str = ""
    debate_rounds: int = 3
    consensus_threshold: float = 0.67
    findings: List[ResearchFinding] = field(default_factory=list)
    final_consensus: Dict[str, Any] = field(default_factory=dict)


class ResearchAgentMarketplace:
    """
    Research Agent Marketplace with Byzantine Consensus

    Manages 6 specialized research agents that challenge each other's
    findings to produce validated, consensus-based research outputs.

    @requirement: REQ-RESEARCH-001 - Multi-agent debates [@core/research_agent_marketplace.py:75-500]
    @requirement: REQ-RESEARCH-002 - Byzantine consensus [@core/research_agent_marketplace.py:200-300]
    """

    # Byzantine consensus threshold
    CONSENSUS_THRESHOLD = 0.67

    def __init__(self, notifier: Optional[WhatsAppNotifier] = None):
        """Initialize research agent marketplace"""
        self.notifier = notifier or WhatsAppNotifier()
        self.property_tracker = PropertyTracker()
        self.job_marketplace = JobMarketplace(self.notifier)

        # Initialize Fedimint for eCash payments
        if FEDIMINT_AVAILABLE:
            self.fedimint = FedimintManager()
            print("✅ Fedimint integration enabled for eCash payments")
        else:
            self.fedimint = None

        # Initialize 6 specialized research agents
        self.agents = self._init_agents()

        # Research job tracking
        self.active_research: Dict[str, ResearchJob] = {}
        self.completed_research: List[ResearchJob] = []

        # Statistics
        self.stats = {
            "research_jobs_completed": 0,
            "total_findings_validated": 0,
            "avg_consensus_score": 0.0,
            "challenges_issued": 0,
            "challenges_resolved": 0,
            "ecash_payments_processed": 0,
        }

        print(f"✅ ResearchAgentMarketplace initialized with {len(self.agents)} agents")

    def _init_agents(self) -> Dict[str, ResearchAgent]:
        """Initialize 6 specialized research agents"""
        agents = {
            "evidence_gatherer": ResearchAgent(
                id="evidence_gatherer",
                name="Evidence Gatherer",
                role="Collects initial research from multiple sources",
                expertise=["web_search", "data_collection", "source_identification"],
            ),
            "fact_checker": ResearchAgent(
                id="fact_checker",
                name="Fact Checker",
                role="Validates claims against authoritative sources",
                expertise=["source_verification", "cross_referencing", "accuracy_assessment"],
            ),
            "devils_advocate": ResearchAgent(
                id="devils_advocate",
                name="Devil's Advocate",
                role="Challenges assumptions and identifies weaknesses",
                expertise=["critical_analysis", "assumption_testing", "counterargument"],
            ),
            "domain_expert": ResearchAgent(
                id="domain_expert",
                name="Domain Expert",
                role="Provides specialized industry context",
                expertise=["market_analysis", "technical_context", "industry_trends"],
            ),
            "bias_detector": ResearchAgent(
                id="bias_detector",
                name="Bias Detector",
                role="Identifies confirmation bias and logical fallacies",
                expertise=["bias_analysis", "fallacy_detection", "objectivity_assessment"],
            ),
            "synthesis_coordinator": ResearchAgent(
                id="synthesis_coordinator",
                name="Synthesis Coordinator",
                role="Builds consensus from validated findings",
                expertise=["consensus_building", "synthesis", "report_generation"],
            ),
        }
        return agents

    async def create_research_job(
        self,
        topic: str,
        payment: float,
        debate_rounds: int = 3,
        client_address: Optional[str] = None,
    ) -> ResearchJob:
        """
        Create a new research job with debate requirements.

        @requirement: REQ-JOB-001 - Job creation [@core/research_agent_marketplace.py:150-200]
        """
        try:
            job_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            job = ResearchJob(
                id=job_id,
                type="research_debate",
                topic=topic,
                payment=payment,
                debate_rounds=debate_rounds,
                consensus_threshold=self.CONSENSUS_THRESHOLD,
                requirements={
                    "agents_required": 6,
                    "min_consensus": 0.67,
                    "debate_rounds": debate_rounds,
                },
                client_address=client_address,
            )

            self.active_research[job_id] = job

            # Notify via WhatsApp
            await self.notifier.send_notification(
                f"📋 New Research Job Created\n"
                f"Topic: {topic}\n"
                f"Payment: ${payment:.2f}\n"
                f"Debate Rounds: {debate_rounds}\n"
                f"Job ID: {job_id}"
            )

            print(f"✅ Research job created: {job_id}")
            return job

        except Exception as e:
            print(f"❌ Error creating research job: {e}")
            traceback.print_exc()
            raise

    async def execute_research_job(self, job_id: str) -> Dict[str, Any]:
        """
        Execute complete research job with fact-checking debates.

        Phases:
        1. Independent Research - Each agent gathers findings
        2. Fact Challenge Round - Agents challenge each other
        3. Evidence Negotiation - Vote on disputed claims
        4. Consensus Building - Build final validated output

        @requirement: REQ-RESEARCH-001 - Multi-agent debates [@core/research_agent_marketplace.py:200-350]
        @requirement: REQ-RESEARCH-002 - Byzantine consensus [@core/research_agent_marketplace.py:300-350]
        """
        try:
            if job_id not in self.active_research:
                return {"error": f"Job {job_id} not found"}

            job = self.active_research[job_id]
            job.status = "in_progress"
            job.accepted_at = datetime.now()

            print(f"\n🔬 Executing Research Job: {job.topic}")
            print("=" * 50)

            # Phase 1: Independent Research
            print("\n📚 Phase 1: Independent Research")
            findings = await self._phase_independent_research(job)
            job.findings = findings
            print(f"   Gathered {len(findings)} initial findings")

            # Phase 2: Fact Challenge Round
            print("\n⚔️ Phase 2: Fact Challenge Round")
            challenged_findings = await self._phase_fact_challenge(job, findings)
            print(f"   {len([f for f in challenged_findings if f.challenges])} findings challenged")

            # Phase 3: Evidence Negotiation (Byzantine Voting)
            print("\n🗳️ Phase 3: Evidence Negotiation (Byzantine Consensus)")
            voted_findings = await self._phase_evidence_negotiation(job, challenged_findings)
            validated = [f for f in voted_findings if f.validated]
            disputed = [f for f in voted_findings if not f.validated]
            print(f"   Validated: {len(validated)} | Disputed: {len(disputed)}")

            # Phase 4: Consensus Building
            print("\n🤝 Phase 4: Consensus Building")
            final_consensus = await self._phase_consensus_building(job, validated, disputed)
            job.final_consensus = final_consensus

            # Complete job
            job.status = "completed"
            job.completed_at = datetime.now()

            # Process payment (eCash if available)
            payment_result = await self._process_payment(job)

            # Update statistics
            self.stats["research_jobs_completed"] += 1
            self.stats["total_findings_validated"] += len(validated)

            # Move to completed
            self.completed_research.append(job)
            del self.active_research[job_id]

            # Notify completion
            await self.notifier.send_notification(
                f"✅ Research Job Complete\n"
                f"Topic: {job.topic}\n"
                f"Validated: {len(validated)} findings\n"
                f"Disputed: {len(disputed)} findings\n"
                f"Consensus Score: {final_consensus.get('avg_consensus', 0):.1%}\n"
                f"Payment: ${job.payment:.2f}"
            )

            result = {
                "job_id": job_id,
                "topic": job.topic,
                "status": "completed",
                "validated_findings": [f.to_dict() for f in validated],
                "disputed_findings": [f.to_dict() for f in disputed],
                "consensus": final_consensus,
                "payment": payment_result,
                "execution_time": (job.completed_at - job.accepted_at).total_seconds(),
            }

            print(f"\n✅ Research job completed: {job_id}")
            return result

        except Exception as e:
            print(f"❌ Error executing research job: {e}")
            traceback.print_exc()
            if job_id in self.active_research:
                self.active_research[job_id].status = "failed"
            return {"error": str(e)}

    async def _phase_independent_research(self, job: ResearchJob) -> List[ResearchFinding]:
        """Phase 1: Each agent conducts independent research"""
        findings = []

        # Simulate each agent gathering findings
        for agent_id, agent in self.agents.items():
            if agent.role == "Synthesis Coordinator":
                continue  # Coordinator doesn't gather initial findings

            # In production, this would call actual research tools
            finding = ResearchFinding(
                claim=f"[{agent.name}] Finding about {job.topic}",
                source=f"Research by {agent.name}",
                confidence=0.75 + (hash(agent_id) % 25) / 100,  # 0.75-1.0
                agent_id=agent_id,
            )
            findings.append(finding)

        return findings

    async def _phase_fact_challenge(
        self, job: ResearchJob, findings: List[ResearchFinding]
    ) -> List[ResearchFinding]:
        """Phase 2: Agents challenge each other's findings"""

        for finding in findings:
            # Each agent (except the original) can challenge
            for agent_id, agent in self.agents.items():
                if agent_id == finding.agent_id:
                    continue

                # Devil's Advocate always challenges
                # Others challenge if confidence < threshold
                should_challenge = (
                    agent_id == "devils_advocate" or finding.confidence < agent.confidence_threshold
                )

                if should_challenge:
                    challenge = {
                        "challenger_id": agent_id,
                        "challenger_name": agent.name,
                        "reason": f"Challenge from {agent.name}: confidence below threshold",
                        "timestamp": datetime.now().isoformat(),
                    }
                    finding.challenges.append(challenge)
                    agent.challenges_issued += 1
                    self.stats["challenges_issued"] += 1

        return findings

    async def _phase_evidence_negotiation(
        self, job: ResearchJob, findings: List[ResearchFinding]
    ) -> List[ResearchFinding]:
        """
        Phase 3: Byzantine consensus voting on findings.

        @requirement: REQ-RESEARCH-002 - Byzantine consensus (67% threshold)
        """

        for finding in findings:
            # Each agent votes
            accept_votes = 0
            total_votes = 0

            for agent_id, agent in self.agents.items():
                # Synthesis coordinator abstains from voting
                if agent_id == "synthesis_coordinator":
                    finding.votes[agent_id] = "ABSTAIN"
                    continue

                # Vote based on confidence and challenges
                if finding.confidence >= 0.8 and len(finding.challenges) == 0:
                    vote = "ACCEPT"
                elif finding.confidence < 0.6 or len(finding.challenges) > 2:
                    vote = "REJECT"
                else:
                    # Consider challenges
                    if any(c["challenger_id"] == "bias_detector" for c in finding.challenges):
                        vote = "REJECT"
                    else:
                        vote = "ACCEPT"

                finding.votes[agent_id] = vote
                total_votes += 1
                if vote == "ACCEPT":
                    accept_votes += 1

            # Calculate consensus score
            finding.consensus_score = accept_votes / total_votes if total_votes > 0 else 0
            finding.validated = finding.consensus_score >= self.CONSENSUS_THRESHOLD

            self.stats["challenges_resolved"] += len(finding.challenges)

        return findings

    async def _phase_consensus_building(
        self, job: ResearchJob, validated: List[ResearchFinding], disputed: List[ResearchFinding]
    ) -> Dict[str, Any]:
        """Phase 4: Build final consensus output"""

        # Calculate average consensus
        all_scores = [f.consensus_score for f in validated + disputed]
        avg_consensus = sum(all_scores) / len(all_scores) if all_scores else 0

        consensus = {
            "topic": job.topic,
            "total_findings": len(validated) + len(disputed),
            "validated_count": len(validated),
            "disputed_count": len(disputed),
            "avg_consensus": avg_consensus,
            "threshold_used": self.CONSENSUS_THRESHOLD,
            "agents_participated": len(self.agents),
            "summary": {
                "validated": [f.claim for f in validated],
                "disputed": [
                    {
                        "claim": f.claim,
                        "consensus": f.consensus_score,
                        "challenges": len(f.challenges),
                    }
                    for f in disputed
                ],
            },
            "timestamp": datetime.now().isoformat(),
        }

        # Update average consensus in stats
        total_jobs = self.stats["research_jobs_completed"] + 1
        self.stats["avg_consensus_score"] = (
            self.stats["avg_consensus_score"] * (total_jobs - 1) + avg_consensus
        ) / total_jobs

        return consensus

    async def _process_payment(self, job: ResearchJob) -> Dict[str, Any]:
        """Process payment via Fedimint eCash or standard payment"""

        if self.fedimint and job.client_address:
            try:
                # Create eCash invoice
                invoice = await self.fedimint.create_invoice(
                    amount_msats=int(job.payment * 100_000),  # Convert USD to approx msats
                    description=f"Research: {job.topic}",
                )
                self.stats["ecash_payments_processed"] += 1

                return {
                    "method": "fedimint_ecash",
                    "invoice": invoice,
                    "amount_usd": job.payment,
                    "status": "invoice_created",
                }
            except Exception as e:
                print(f"⚠️ eCash payment error, falling back: {e}")

        # Standard payment tracking
        return {"method": "standard", "amount_usd": job.payment, "status": "pending_verification"}

    def get_status(self) -> Dict[str, Any]:
        """Get marketplace status and statistics"""
        return {
            "agents": {aid: a.to_dict() for aid, a in self.agents.items()},
            "active_jobs": len(self.active_research),
            "completed_jobs": len(self.completed_research),
            "stats": self.stats,
            "fedimint_enabled": FEDIMINT_AVAILABLE,
            "consensus_threshold": self.CONSENSUS_THRESHOLD,
        }


# Command-line interface
async def main():
    """Test the research agent marketplace"""
    print("\n" + "=" * 60)
    print("🔬 Research Agent Marketplace Test")
    print("=" * 60)

    marketplace = ResearchAgentMarketplace()

    # Create a test research job
    job = await marketplace.create_research_job(
        topic="Bitcoin Lightning Network adoption trends 2025", payment=50.0, debate_rounds=3
    )

    # Execute the research
    result = await marketplace.execute_research_job(job.id)

    # Print results
    print("\n" + "=" * 60)
    print("📊 Research Results")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))

    # Print status
    print("\n" + "=" * 60)
    print("📈 Marketplace Status")
    print("=" * 60)
    status = marketplace.get_status()
    print(f"Research Jobs Completed: {status['stats']['research_jobs_completed']}")
    print(f"Findings Validated: {status['stats']['total_findings_validated']}")
    print(f"Avg Consensus Score: {status['stats']['avg_consensus_score']:.1%}")
    print(f"Challenges Issued: {status['stats']['challenges_issued']}")
    print(f"Fedimint Enabled: {status['fedimint_enabled']}")


if __name__ == "__main__":
    asyncio.run(main())
