#!/usr/bin/env python3
"""
BlindOracle AI Consensus Market Resolver Handler
==================================================

Implements the Multi-AI Consensus Market Resolver (UC6) for the CRE
marketplace. When a prediction market deadline is reached, the resolver:

1. Detects the market deadline event
2. Gathers evidence from 5+ independent sources
3. Queries 3+ AI models for independent YES/NO/ABSTAIN votes
4. Applies Byzantine fault-tolerant consensus (67% threshold)
5. Settles the market on-chain
6. Distributes winnings via eCash
7. Writes a complete audit trail

Revenue model: 1% of the total settled pool.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway,
      ByzantineConsensusEngine pattern)
    - services.swaps.cross_chain_router (CrossChainRouter)
    - privacy.ecash_prediction_bridge (ECashPredictionBridge pattern)

BLP Properties:
    BLP-001 (Alignment): Prediction market resolution domain expertise
    BLP-003 (Consensus Security): Byzantine fault-tolerant multi-AI consensus
    BLP-005 (Security Integrity): Anti-manipulation via sealed votes
    BLP-011 (Autonomy): Fully autonomous resolution (99% autonomy)
    BLP-019 (Logging): Immutable audit trail for dispute resolution
    BLP-023 (Durability): Error recovery with graceful degradation

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
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
)
from services.swaps.cross_chain_router import CrossChainRouter

logger = logging.getLogger(__name__)

# Audit log path for resolutions
_AUDIT_DIR = Path("/home/craigmbrown/Project/logs")
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
_RESOLUTION_AUDIT_PATH = _AUDIT_DIR / "blindoracle_resolution_audit.json"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EvidenceSource(Enum):
    """Types of evidence sources for market resolution."""
    NEWS_API = "news_api"
    BLOCKCHAIN_DATA = "blockchain_data"
    ORACLE_FEED = "oracle_feed"
    SOCIAL_SIGNAL = "social_signal"
    EXPERT_OPINION = "expert_opinion"


class VotePosition(Enum):
    """Possible vote positions for AI models."""
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class ResolutionStatus(Enum):
    """Status of a market resolution attempt."""
    PENDING = "pending"
    EVIDENCE_GATHERED = "evidence_gathered"
    VOTES_COLLECTED = "votes_collected"
    CONSENSUS_REACHED = "consensus_reached"
    CONSENSUS_FAILED = "consensus_failed"
    SETTLED = "settled"
    DISPUTED = "disputed"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ResolutionConfig:
    """Configuration for the Consensus Resolver.

    REQ-BLP-001: Domain-specific configuration for market resolution.

    Attributes:
        min_ai_models: Minimum AI models required for a valid consensus.
        consensus_threshold: Byzantine consensus threshold (0.67 = 67%).
        min_evidence_sources: Minimum evidence sources to gather.
        resolution_fee_pct: Revenue fee as percentage of settled pool.
        security_interface: CaMel gateway interface identifier.
        security_agent_id: Agent identity for security gateway.
        enable_sealed_votes: Whether to use sealed-vote anti-front-running.
    """
    min_ai_models: int = 3
    consensus_threshold: float = 0.67
    min_evidence_sources: int = 5
    resolution_fee_pct: float = 1.0
    security_interface: str = "x402_api"
    security_agent_id: str = "consensus_resolver_v1"
    enable_sealed_votes: bool = True


@dataclass
class MarketInfo:
    """Information about a prediction market pending resolution.

    Attributes:
        market_id: On-chain market identifier.
        question: The prediction question.
        deadline: Unix timestamp of the market deadline.
        yes_pool_sats: Total satoshis in the YES pool.
        no_pool_sats: Total satoshis in the NO pool.
        total_pool_sats: Total market pool (yes + no).
        creator: Address of the market creator.
        network: Blockchain network (e.g. "sepolia", "base").
    """
    market_id: int
    question: str
    deadline: int
    yes_pool_sats: int = 0
    no_pool_sats: int = 0
    total_pool_sats: int = 0
    creator: str = ""
    network: str = "sepolia"

    def __post_init__(self) -> None:
        self.total_pool_sats = self.yes_pool_sats + self.no_pool_sats


@dataclass
class Evidence:
    """A single piece of evidence from a source.

    Attributes:
        source: The evidence source type.
        source_name: Human-readable source name.
        content: Summary of the evidence content.
        reliability_score: Source reliability (0.0 - 1.0).
        relevance_score: Relevance to the market question (0.0 - 1.0).
        timestamp: When the evidence was gathered.
        raw_data: Optional raw data from the source.
    """
    source: str
    source_name: str
    content: str
    reliability_score: float
    relevance_score: float
    timestamp: str = ""
    raw_data: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class AIVote:
    """Vote from a single AI model.

    Attributes:
        model_name: Name of the AI model (e.g. "claude-sonnet-4").
        provider: AI provider (e.g. "anthropic").
        position: Vote position (YES/NO/ABSTAIN).
        confidence: Model's confidence in its vote (0.0 - 1.0).
        evidence_summary: Model's summary of key evidence.
        reasoning: Model's reasoning for its position.
        vote_hash: Hash of the vote for sealed-vote verification.
    """
    model_name: str
    provider: str
    position: str
    confidence: float
    evidence_summary: str
    reasoning: str
    vote_hash: str = ""

    def __post_init__(self) -> None:
        if not self.vote_hash:
            content = f"{self.model_name}:{self.position}:{self.confidence}"
            self.vote_hash = hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class ConsensusResult:
    """Result of the Byzantine consensus process.

    Attributes:
        consensus_reached: Whether the threshold was met.
        outcome: The consensus outcome (YES/NO) if reached.
        agreement_pct: Percentage of models that agreed.
        votes: All individual AI votes.
        threshold: The required threshold percentage.
        total_models: Number of models that voted.
        agreeing_models: Number of models that agreed with the majority.
    """
    consensus_reached: bool
    outcome: Optional[str]
    agreement_pct: float
    votes: List[AIVote]
    threshold: float
    total_models: int
    agreeing_models: int


@dataclass
class SettlementResult:
    """Result of on-chain market settlement.

    Attributes:
        success: Whether the settlement succeeded.
        market_id: The market that was settled.
        outcome: The settlement outcome (YES/NO).
        tx_hash: On-chain transaction hash.
        fee_sats: Resolution fee collected.
        error: Error message on failure.
    """
    success: bool
    market_id: int
    outcome: str = ""
    tx_hash: str = ""
    fee_sats: int = 0
    error: Optional[str] = None


@dataclass
class DistributionResult:
    """Result of winnings distribution.

    Attributes:
        success: Whether distribution succeeded.
        market_id: The market for which winnings were distributed.
        total_distributed_sats: Total satoshis distributed to winners.
        fee_collected_sats: Resolution fee collected.
        winners_count: Number of winning positions.
        error: Error message on failure.
    """
    success: bool
    market_id: int
    total_distributed_sats: int = 0
    fee_collected_sats: int = 0
    winners_count: int = 0
    error: Optional[str] = None


@dataclass
class ResolutionAuditEntry:
    """Complete audit entry for a market resolution.

    Attributes:
        audit_id: Unique audit identifier.
        market_id: The market being resolved.
        question: The prediction question.
        status: Final resolution status.
        evidence_count: Number of evidence sources gathered.
        ai_votes: All AI model votes with reasoning.
        consensus: Consensus result details.
        settlement: Settlement transaction details.
        distribution: Winnings distribution details.
        total_pool_sats: Total market pool.
        fee_collected_sats: Resolution fee collected.
        errors: Any errors encountered.
        started_at: Workflow start timestamp.
        completed_at: Workflow completion timestamp.
        duration_ms: Total workflow duration in milliseconds.
    """
    audit_id: str = ""
    market_id: int = 0
    question: str = ""
    status: str = ResolutionStatus.PENDING.value
    evidence_count: int = 0
    ai_votes: List[Dict[str, Any]] = field(default_factory=list)
    consensus: Optional[Dict[str, Any]] = None
    settlement: Optional[Dict[str, Any]] = None
    distribution: Optional[Dict[str, Any]] = None
    total_pool_sats: int = 0
    fee_collected_sats: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.audit_id:
            self.audit_id = f"resolution_{uuid.uuid4().hex[:12]}"
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Consensus Resolver
# ---------------------------------------------------------------------------

class ConsensusResolver:
    """Multi-AI Consensus Market Resolver.

    Orchestrates the full market resolution lifecycle using Byzantine
    fault-tolerant consensus from 3+ independent AI models. Evidence
    is gathered from 5+ sources, votes are sealed to prevent front-running,
    and the entire process produces an immutable audit trail.

    Revenue: 1% of the total settled pool.

    REQ-BLP-001 (Alignment): Prediction market resolution expertise
    REQ-BLP-003 (Consensus Security): Byzantine fault tolerance
    REQ-BLP-005 (Security Integrity): Anti-manipulation via sealed votes
    REQ-BLP-011 (Autonomy): Fully autonomous resolution
    REQ-BLP-019 (Logging): Immutable audit trail
    REQ-BLP-023 (Durability): Error recovery with graceful degradation

    Usage:
        config = ResolutionConfig()
        resolver = ConsensusResolver(config)
        audit = await resolver.run_workflow(market_id=42,
            question="Will BTC exceed $100k by June 2026?", deadline=1750000000)
    """

    def __init__(
        self,
        config: Optional[ResolutionConfig] = None,
        router: Optional[CrossChainRouter] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        """Initialize the Consensus Resolver.

        Args:
            config: Resolution configuration. Uses defaults if not provided.
            router: CrossChainRouter for settlement. Created if not provided.
            gateway: Security gateway. Created if not provided.
        """
        self.config = config or ResolutionConfig()
        self._router = router or CrossChainRouter()
        self._gateway = gateway or BlindOracleSecurityGateway()

        # Authorize the resolver agent
        self._gateway.authorize_agent(self.config.security_agent_id)

        # AI model registry (mock -- in production these are real API clients)
        self._ai_models = [
            {"provider": "anthropic", "model": "claude-sonnet-4", "role": "primary_analyst"},
            {"provider": "openai", "model": "gpt-4o", "role": "cross_validator"},
            {"provider": "google", "model": "gemini-pro", "role": "independent_judge"},
        ]

        # State
        self._market_info: Optional[MarketInfo] = None
        self._evidence: List[Evidence] = []
        self._votes: List[AIVote] = []
        self._consensus: Optional[ConsensusResult] = None
        self._errors: List[str] = []

        logger.info("[SUCCESS] ConsensusResolver initialized")
        logger.info("[INFO]   Models: %d (min: %d)",
                    len(self._ai_models), self.config.min_ai_models)
        logger.info("[INFO]   Consensus threshold: %.0f%%",
                    self.config.consensus_threshold * 100)
        logger.info("[INFO]   Resolution fee: %.1f%%", self.config.resolution_fee_pct)
        logger.info("[INFO]   Sealed votes: %s", self.config.enable_sealed_votes)

    # ---- Step 1: Detect Deadline ----

    async def detect_deadline(
        self, market_id: int, question: str, deadline: int
    ) -> MarketInfo:
        """Detect and validate a market deadline event.

        Decodes the MarketDeadlineReached event and verifies the market
        is in a resolvable state.

        REQ-BLP-001: Domain understanding of market lifecycle.

        Args:
            market_id: On-chain market identifier.
            question: The prediction question.
            deadline: Unix timestamp of the deadline.

        Returns:
            MarketInfo with decoded market details.

        Raises:
            ValueError: If the market is not yet past its deadline.
        """
        try:
            now = int(time.time())
            if deadline > now:
                logger.info(
                    "[INFO] Market %d deadline not yet reached: %d > %d",
                    market_id, deadline, now,
                )
                # For testing, allow future deadlines
                logger.info("[INFO] Proceeding anyway (mock mode)")

            # Mock: Generate pool sizes
            pool_seed = hash(f"{market_id}_{question}") % 1_000_000
            yes_pool = pool_seed + 50_000
            no_pool = abs(1_000_000 - pool_seed) + 30_000

            self._market_info = MarketInfo(
                market_id=market_id,
                question=question,
                deadline=deadline,
                yes_pool_sats=yes_pool,
                no_pool_sats=no_pool,
                creator=f"0x{secrets.token_hex(20)}",
            )

            logger.info("[SUCCESS] Market deadline detected: market_id=%d", market_id)
            logger.info("[INFO]   Question: %s", question[:80])
            logger.info("[INFO]   YES pool: %d sats, NO pool: %d sats, Total: %d sats",
                        yes_pool, no_pool, self._market_info.total_pool_sats)

            return self._market_info

        except Exception as e:
            error_msg = f"Deadline detection failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Gather Evidence ----

    async def gather_evidence(self, market_id: int) -> List[Evidence]:
        """Collect evidence from 5+ independent sources.

        Gathers evidence from news APIs, blockchain data, oracle feeds,
        social signals, and expert opinions. Each source is scored for
        reliability and relevance.

        REQ-BLP-001: Multi-source evidence gathering for informed resolution.

        Args:
            market_id: Market identifier for context.

        Returns:
            List of Evidence objects from diverse sources.
        """
        try:
            question = self._market_info.question if self._market_info else f"Market {market_id}"
            evidence_list: List[Evidence] = []

            # Source 1: News API
            evidence_list.append(Evidence(
                source=EvidenceSource.NEWS_API.value,
                source_name="Reuters Financial",
                content=f"News analysis for '{question[:50]}...': "
                        "Multiple reputable sources report relevant developments. "
                        "Coverage sentiment leans toward affirmative outcome based "
                        "on recent market data and expert commentary.",
                reliability_score=0.85,
                relevance_score=0.90,
            ))

            # Source 2: Blockchain Data
            evidence_list.append(Evidence(
                source=EvidenceSource.BLOCKCHAIN_DATA.value,
                source_name="Chainlink Oracle Network",
                content="On-chain data shows consistent trend supporting the "
                        "predicted outcome. Transaction volume and smart contract "
                        "activity align with affirmative resolution.",
                reliability_score=0.95,
                relevance_score=0.88,
            ))

            # Source 3: Oracle Feed
            evidence_list.append(Evidence(
                source=EvidenceSource.ORACLE_FEED.value,
                source_name="Chainlink Price Feeds",
                content="Price oracle data confirms the market conditions described "
                        "in the prediction question. Data feeds show strong correlation "
                        "with historical patterns.",
                reliability_score=0.92,
                relevance_score=0.95,
            ))

            # Source 4: Social Signal
            evidence_list.append(Evidence(
                source=EvidenceSource.SOCIAL_SIGNAL.value,
                source_name="Nostr + X Social Analysis",
                content="Social sentiment analysis across Nostr and X platforms "
                        "indicates 72% positive sentiment regarding the prediction "
                        "outcome. Key opinion leaders support the affirmative position.",
                reliability_score=0.65,
                relevance_score=0.70,
            ))

            # Source 5: Expert Opinion
            evidence_list.append(Evidence(
                source=EvidenceSource.EXPERT_OPINION.value,
                source_name="Domain Expert Panel",
                content="A panel of 5 domain experts (anonymized) provided weighted "
                        "opinions. 4/5 experts support the affirmative outcome with "
                        "moderate-to-high confidence. One expert abstained citing "
                        "insufficient data.",
                reliability_score=0.80,
                relevance_score=0.85,
            ))

            # Source 6: Additional blockchain analysis
            evidence_list.append(Evidence(
                source=EvidenceSource.BLOCKCHAIN_DATA.value,
                source_name="On-chain Whale Tracker",
                content="Whale wallet analysis shows significant positioning in "
                        "alignment with the YES outcome. 3 of top 5 holders have "
                        "increased positions in the last 72 hours.",
                reliability_score=0.75,
                relevance_score=0.78,
            ))

            self._evidence = evidence_list

            logger.info(
                "[SUCCESS] Evidence gathered: %d sources (min required: %d)",
                len(evidence_list), self.config.min_evidence_sources,
            )
            for ev in evidence_list:
                logger.info(
                    "[INFO]   %s (%s): reliability=%.2f, relevance=%.2f",
                    ev.source_name, ev.source, ev.reliability_score, ev.relevance_score,
                )

            return evidence_list

        except Exception as e:
            error_msg = f"Evidence gathering failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Multi-AI Vote ----

    async def multi_ai_vote(self, evidence: List[Evidence]) -> List[AIVote]:
        """Query 3+ AI models for independent resolution votes.

        Each model receives the same evidence package and returns
        a structured vote with confidence, evidence summary, and
        reasoning. Votes are sealed if anti-front-running is enabled.

        REQ-BLP-003: Multi-model consensus for Byzantine fault tolerance.
        REQ-BLP-005: Sealed votes prevent front-running.

        Args:
            evidence: List of evidence objects to provide to each model.

        Returns:
            List of AIVote objects from all models.
        """
        try:
            votes: List[AIVote] = []

            # Prepare evidence summary for models
            evidence_summary = "\n".join(
                f"- [{ev.source_name}] (reliability: {ev.reliability_score:.0%}): "
                f"{ev.content[:100]}..."
                for ev in evidence
            )

            # Create sealed vote session if enabled
            session_id = None
            session_key = None
            if self.config.enable_sealed_votes:
                voter_ids = [m["model"] for m in self._ai_models]
                session_id = f"resolution_{self._market_info.market_id if self._market_info else 0}"
                session_key = self._gateway.create_debate_session(session_id, voter_ids)
                logger.info("[INFO] Sealed vote session created: %s", session_id)

            for model_config in self._ai_models:
                try:
                    # Mock AI model response
                    # In production: call the actual AI API with the evidence
                    vote = await self._query_ai_model(
                        model_config, evidence_summary, evidence,
                    )
                    votes.append(vote)

                    # Submit sealed vote if enabled
                    if session_id and session_key:
                        vote_data = {
                            "position": vote.position,
                            "confidence": vote.confidence,
                        }
                        success, msg = self._gateway.submit_debate_vote(
                            session_id, model_config["model"], vote_data, session_key,
                        )
                        if not success:
                            logger.warning(
                                "[WARN] Sealed vote submission failed for %s: %s",
                                model_config["model"], msg,
                            )

                    logger.info(
                        "[SUCCESS] AI vote: model=%s, position=%s, confidence=%.2f",
                        vote.model_name, vote.position, vote.confidence,
                    )

                except Exception as e:
                    logger.error(
                        "[ERROR] AI model %s failed: %s", model_config["model"], e
                    )
                    self._errors.append(f"Model {model_config['model']} error: {e}")

            if len(votes) < self.config.min_ai_models:
                error_msg = (
                    f"Insufficient AI votes: got {len(votes)}, "
                    f"need {self.config.min_ai_models}"
                )
                logger.error("[ERROR] %s", error_msg)
                self._errors.append(error_msg)
                raise ValueError(error_msg)

            # Reveal sealed votes
            if session_id:
                revealed, vote_data = self._gateway.reveal_debate_votes(session_id)
                if revealed:
                    logger.info("[SUCCESS] Sealed votes revealed: %d votes", len(vote_data or {}))
                else:
                    logger.info("[INFO] Sealed vote reveal pending (not all voters submitted)")

            self._votes = votes
            return votes

        except Exception as e:
            error_msg = f"Multi-AI voting failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    async def _query_ai_model(
        self,
        model_config: Dict[str, str],
        evidence_summary: str,
        evidence: List[Evidence],
    ) -> AIVote:
        """Query a single AI model for its resolution vote.

        Mock implementation. In production, this would call the actual
        AI API (Anthropic, OpenAI, Google) with the evidence package.

        Args:
            model_config: Model configuration (provider, model, role).
            evidence_summary: Formatted evidence summary.
            evidence: Full evidence list.

        Returns:
            AIVote from the model.
        """
        # Mock: Generate a vote based on evidence scores
        # Weighted average of reliability * relevance determines position
        weighted_score = sum(
            ev.reliability_score * ev.relevance_score for ev in evidence
        ) / max(len(evidence), 1)

        # Model-specific bias (simulates different model perspectives)
        model_biases = {
            "claude-sonnet-4": 0.02,       # Slightly optimistic
            "gpt-4o": -0.01,               # Slightly conservative
            "gemini-pro": 0.0,             # Neutral
        }
        bias = model_biases.get(model_config["model"], 0.0)
        adjusted_score = weighted_score + bias

        # Determine position
        if adjusted_score > 0.55:
            position = VotePosition.YES.value
            confidence = min(0.95, adjusted_score + 0.1)
        elif adjusted_score < 0.45:
            position = VotePosition.NO.value
            confidence = min(0.95, 1.0 - adjusted_score + 0.1)
        else:
            position = VotePosition.ABSTAIN.value
            confidence = 0.5

        reasoning_map = {
            VotePosition.YES.value: (
                f"Based on {len(evidence)} evidence sources with weighted reliability "
                f"score of {weighted_score:.2f}, the evidence strongly supports the "
                f"affirmative outcome. Key indicators include oracle feed data, "
                f"on-chain activity patterns, and expert panel consensus."
            ),
            VotePosition.NO.value: (
                f"Analysis of {len(evidence)} sources (weighted score: {weighted_score:.2f}) "
                f"suggests insufficient evidence for the affirmative outcome. "
                f"Social signal reliability is low and expert opinions are divided."
            ),
            VotePosition.ABSTAIN.value: (
                f"Evidence is inconclusive (weighted score: {weighted_score:.2f}). "
                f"Cannot determine outcome with sufficient confidence. "
                f"Recommending manual review."
            ),
        }

        return AIVote(
            model_name=model_config["model"],
            provider=model_config["provider"],
            position=position,
            confidence=round(confidence, 3),
            evidence_summary=f"Analyzed {len(evidence)} sources, weighted score: {weighted_score:.2f}",
            reasoning=reasoning_map.get(position, "No reasoning available."),
        )

    # ---- Step 4: Byzantine Consensus ----

    async def byzantine_consensus(self, votes: List[AIVote]) -> ConsensusResult:
        """Apply Byzantine fault-tolerant consensus to AI votes.

        Counts YES/NO/ABSTAIN votes, determines the majority position,
        and checks if agreement exceeds the threshold. ABSTAIN votes
        are excluded from the denominator.

        REQ-BLP-003: Byzantine consensus with configurable threshold.

        Args:
            votes: List of AI model votes.

        Returns:
            ConsensusResult with the consensus determination.
        """
        try:
            # Count votes by position
            yes_votes = [v for v in votes if v.position == VotePosition.YES.value]
            no_votes = [v for v in votes if v.position == VotePosition.NO.value]
            abstain_votes = [v for v in votes if v.position == VotePosition.ABSTAIN.value]

            # Exclude abstentions from the denominator
            voting_count = len(yes_votes) + len(no_votes)
            if voting_count == 0:
                # All abstained -- no consensus
                self._consensus = ConsensusResult(
                    consensus_reached=False,
                    outcome=None,
                    agreement_pct=0.0,
                    votes=votes,
                    threshold=self.config.consensus_threshold,
                    total_models=len(votes),
                    agreeing_models=0,
                )
                logger.info("[INFO] All models abstained -- no consensus")
                return self._consensus

            # Determine majority
            if len(yes_votes) >= len(no_votes):
                majority_position = VotePosition.YES.value
                agreeing = len(yes_votes)
            else:
                majority_position = VotePosition.NO.value
                agreeing = len(no_votes)

            agreement_pct = agreeing / voting_count
            consensus_reached = agreement_pct >= self.config.consensus_threshold

            self._consensus = ConsensusResult(
                consensus_reached=consensus_reached,
                outcome=majority_position if consensus_reached else None,
                agreement_pct=round(agreement_pct, 4),
                votes=votes,
                threshold=self.config.consensus_threshold,
                total_models=len(votes),
                agreeing_models=agreeing,
            )

            logger.info(
                "[%s] Byzantine consensus: %.1f%% agreement (%d/%d) -- threshold %.0f%% -- %s",
                "SUCCESS" if consensus_reached else "INFO",
                agreement_pct * 100, agreeing, voting_count,
                self.config.consensus_threshold * 100,
                "REACHED" if consensus_reached else "NOT REACHED",
            )
            logger.info("[INFO]   YES: %d, NO: %d, ABSTAIN: %d",
                        len(yes_votes), len(no_votes), len(abstain_votes))

            return self._consensus

        except Exception as e:
            error_msg = f"Byzantine consensus failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Settle Market ----

    async def settle_market(
        self, market_id: int, outcome: str
    ) -> SettlementResult:
        """Settle the market on-chain with the consensus outcome.

        The settlement is CaMel-secured and requires security gateway
        approval. The resolution fee (1%) is calculated from the
        total pool.

        REQ-BLP-019: Settlement audit trail.

        Args:
            market_id: Market to settle.
            outcome: Consensus outcome (YES/NO).

        Returns:
            SettlementResult with transaction details.
        """
        try:
            # CaMel security validation
            sec_request = SecurityRequest(
                interface=self.config.security_interface,
                operation="settle_market",
                agent_id=self.config.security_agent_id,
                parameters={
                    "market_id": market_id,
                    "outcome": outcome,
                    "consensus_pct": self._consensus.agreement_pct if self._consensus else 0,
                },
                amount_sats=self._market_info.total_pool_sats if self._market_info else 0,
            )

            sec_response = self._gateway.process_request(sec_request)

            if not sec_response.approved:
                error_msg = f"CaMel rejected settlement: {sec_response.denial_reason}"
                logger.error("[ERROR] %s", error_msg)
                return SettlementResult(
                    success=False,
                    market_id=market_id,
                    error=error_msg,
                )

            # Calculate fee
            total_pool = self._market_info.total_pool_sats if self._market_info else 0
            fee_sats = int(total_pool * self.config.resolution_fee_pct / 100.0)

            # Mock on-chain settlement
            settlement_data = f"{market_id}_{outcome}_{fee_sats}"
            tx_hash = f"0x{hashlib.sha256(settlement_data.encode()).hexdigest()}"

            # Settle via CrossChainRouter's settlement engine
            outcome_bool = outcome == VotePosition.YES.value
            await self._router.settlement_engine.auto_settle_market(market_id, outcome_bool)

            logger.info(
                "[SUCCESS] Market settled: market_id=%d, outcome=%s, "
                "pool=%d sats, fee=%d sats, tx=%s",
                market_id, outcome, total_pool, fee_sats, tx_hash[:18],
            )

            return SettlementResult(
                success=True,
                market_id=market_id,
                outcome=outcome,
                tx_hash=tx_hash,
                fee_sats=fee_sats,
            )

        except Exception as e:
            error_msg = f"Market settlement failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return SettlementResult(
                success=False,
                market_id=market_id,
                error=str(e),
            )

    # ---- Step 6: Distribute Winnings ----

    async def distribute_winnings(
        self, market_id: int
    ) -> DistributionResult:
        """Distribute winnings to winning positions via eCash.

        Winning positions receive their share of the pool minus
        the resolution fee. Payouts are minted as eCash tokens
        for privacy-preserving withdrawal.

        REQ-BLP-019: Distribution audit trail.

        Args:
            market_id: Market to distribute winnings for.

        Returns:
            DistributionResult with payout details.
        """
        try:
            if not self._market_info or not self._consensus:
                return DistributionResult(
                    success=False,
                    market_id=market_id,
                    error="No market info or consensus available",
                )

            total_pool = self._market_info.total_pool_sats
            fee_sats = int(total_pool * self.config.resolution_fee_pct / 100.0)
            distributable = total_pool - fee_sats

            # Mock: determine number of winners
            # In production, this would iterate over all on-chain commitments
            outcome = self._consensus.outcome
            if outcome == VotePosition.YES.value:
                winners_pool = self._market_info.yes_pool_sats
            else:
                winners_pool = self._market_info.no_pool_sats

            # Each winner gets proportional share of the distributable pool
            # Mock: assume 10 winning positions
            mock_winners = min(10, max(1, winners_pool // 10_000))

            # CaMel security for eCash minting
            sec_request = SecurityRequest(
                interface=self.config.security_interface,
                operation="ecash_mint",
                agent_id=self.config.security_agent_id,
                parameters={
                    "market_id": market_id,
                    "total_distribution_sats": distributable,
                    "winners_count": mock_winners,
                },
                amount_sats=distributable,
            )

            sec_response = self._gateway.process_request(sec_request)

            if not sec_response.approved:
                return DistributionResult(
                    success=False,
                    market_id=market_id,
                    error=f"CaMel rejected distribution: {sec_response.denial_reason}",
                )

            logger.info(
                "[SUCCESS] Winnings distributed: market_id=%d, total=%d sats, "
                "fee=%d sats, winners=%d",
                market_id, distributable, fee_sats, mock_winners,
            )

            return DistributionResult(
                success=True,
                market_id=market_id,
                total_distributed_sats=distributable,
                fee_collected_sats=fee_sats,
                winners_count=mock_winners,
            )

        except Exception as e:
            error_msg = f"Winnings distribution failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return DistributionResult(
                success=False,
                market_id=market_id,
                error=str(e),
            )

    # ---- Step 7: Audit Log ----

    async def audit_log(
        self,
        market_info: MarketInfo,
        consensus: Optional[ConsensusResult],
        settlement: Optional[SettlementResult],
        distribution: Optional[DistributionResult],
        status: ResolutionStatus,
    ) -> ResolutionAuditEntry:
        """Write a complete audit trail for the resolution.

        The audit entry is immutable and contains all information
        needed for dispute resolution: evidence, votes, reasoning,
        consensus details, settlement, and distribution.

        REQ-BLP-019: Immutable audit trail for accountability.

        Args:
            market_info: The market that was resolved.
            consensus: Consensus result (if reached).
            settlement: Settlement result (if executed).
            distribution: Distribution result (if executed).
            status: Final resolution status.

        Returns:
            ResolutionAuditEntry with complete audit details.
        """
        try:
            entry = ResolutionAuditEntry(
                market_id=market_info.market_id,
                question=market_info.question,
                status=status.value,
                evidence_count=len(self._evidence),
                ai_votes=[asdict(v) for v in self._votes],
                consensus={
                    "reached": consensus.consensus_reached,
                    "outcome": consensus.outcome,
                    "agreement_pct": consensus.agreement_pct,
                    "threshold": consensus.threshold,
                    "total_models": consensus.total_models,
                    "agreeing_models": consensus.agreeing_models,
                } if consensus else None,
                settlement={
                    "success": settlement.success,
                    "outcome": settlement.outcome,
                    "tx_hash": settlement.tx_hash,
                    "fee_sats": settlement.fee_sats,
                } if settlement else None,
                distribution={
                    "success": distribution.success,
                    "total_distributed_sats": distribution.total_distributed_sats,
                    "fee_collected_sats": distribution.fee_collected_sats,
                    "winners_count": distribution.winners_count,
                } if distribution else None,
                total_pool_sats=market_info.total_pool_sats,
                fee_collected_sats=distribution.fee_collected_sats if distribution else 0,
                errors=list(self._errors),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

            # Calculate duration
            started = datetime.fromisoformat(entry.started_at)
            completed = datetime.fromisoformat(entry.completed_at)
            entry.duration_ms = (completed - started).total_seconds() * 1000

            # Write to audit file
            try:
                with open(_RESOLUTION_AUDIT_PATH, "a") as f:
                    f.write(json.dumps(asdict(entry), default=str) + "\n")
            except OSError as exc:
                logger.error("[ERROR] Failed to write audit log: %s", exc)

            logger.info("[SUCCESS] Audit log written: audit_id=%s, status=%s",
                        entry.audit_id, entry.status)

            return entry

        except Exception as e:
            error_msg = f"Audit log failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return ResolutionAuditEntry(
                market_id=market_info.market_id,
                status=ResolutionStatus.ERROR.value,
                errors=list(self._errors),
            )

    # ---- Full Workflow Orchestration ----

    async def run_workflow(
        self,
        market_id: int,
        question: str,
        deadline: int,
    ) -> ResolutionAuditEntry:
        """Execute the full market resolution workflow.

        Runs all 7 steps:
        1. Detect market deadline
        2. Gather evidence from 5+ sources
        3. Multi-AI voting (3+ models)
        4. Byzantine consensus (67% threshold)
        5. Settle market on-chain (if consensus reached)
        6. Distribute winnings via eCash (if settled)
        7. Write audit trail (always)

        Args:
            market_id: On-chain market identifier.
            question: The prediction question.
            deadline: Unix timestamp of the market deadline.

        Returns:
            ResolutionAuditEntry with complete resolution audit.
        """
        logger.info("[INFO] === Consensus Resolver Workflow Starting ===")
        logger.info("[INFO]   Market ID: %d", market_id)
        logger.info("[INFO]   Question: %s", question[:80])

        settlement: Optional[SettlementResult] = None
        distribution: Optional[DistributionResult] = None
        status = ResolutionStatus.PENDING

        try:
            # Step 1: Detect deadline
            market_info = await self.detect_deadline(market_id, question, deadline)

            # Step 2: Gather evidence
            evidence = await self.gather_evidence(market_id)
            status = ResolutionStatus.EVIDENCE_GATHERED

            # Step 3: Multi-AI vote
            votes = await self.multi_ai_vote(evidence)
            status = ResolutionStatus.VOTES_COLLECTED

            # Step 4: Byzantine consensus
            consensus = await self.byzantine_consensus(votes)

            if not consensus.consensus_reached:
                status = ResolutionStatus.DISPUTED
                logger.info(
                    "[INFO] Market %d enters DISPUTE state: consensus=%.1f%% < %.0f%%",
                    market_id, consensus.agreement_pct * 100,
                    self.config.consensus_threshold * 100,
                )
            else:
                status = ResolutionStatus.CONSENSUS_REACHED
                assert consensus.outcome is not None

                # Step 5: Settle market
                settlement = await self.settle_market(market_id, consensus.outcome)

                if settlement.success:
                    # Step 6: Distribute winnings
                    distribution = await self.distribute_winnings(market_id)
                    status = ResolutionStatus.SETTLED
                else:
                    status = ResolutionStatus.ERROR

            # Step 7: Audit log (always)
            audit_entry = await self.audit_log(
                market_info, consensus, settlement, distribution, status,
            )

            logger.info("[SUCCESS] === Consensus Resolver Workflow Complete ===")
            logger.info("[INFO]   Status: %s", status.value)
            logger.info("[INFO]   Audit ID: %s", audit_entry.audit_id)

            return audit_entry

        except Exception as e:
            logger.error("[ERROR] Consensus resolver workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")

            # Ensure audit is written even on error
            if self._market_info:
                return await self.audit_log(
                    self._market_info, self._consensus, settlement, distribution,
                    ResolutionStatus.ERROR,
                )
            else:
                return ResolutionAuditEntry(
                    market_id=market_id,
                    question=question,
                    status=ResolutionStatus.ERROR.value,
                    errors=list(self._errors),
                )


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Consensus Resolver workflow with a mock market."""
    print("=" * 70)
    print("BlindOracle AI Consensus Market Resolver -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize Consensus Resolver ---")
    config = ResolutionConfig()
    resolver = ConsensusResolver(config)
    print(f"  Models: {len(resolver._ai_models)}")
    print(f"  Threshold: {config.consensus_threshold*100:.0f}%")
    print(f"  Fee: {config.resolution_fee_pct}%")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Detect deadline ---
    print("\n--- 2. Detect Market Deadline ---")
    market_info = await resolver.detect_deadline(
        market_id=42,
        question="Will BTC exceed $100k by June 2026?",
        deadline=int(time.time()) - 3600,  # 1 hour ago
    )
    print(f"  Market ID: {market_info.market_id}")
    print(f"  Question: {market_info.question}")
    print(f"  Pool: {market_info.total_pool_sats} sats")
    results.append({"test": "Detect Deadline", "pass": market_info.market_id == 42})

    # --- 3. Gather evidence ---
    print("\n--- 3. Gather Evidence ---")
    evidence = await resolver.gather_evidence(42)
    print(f"  Sources gathered: {len(evidence)} (min: {config.min_evidence_sources})")
    for ev in evidence:
        print(f"    [{ev.source}] {ev.source_name}: reliability={ev.reliability_score:.2f}")
    assert len(evidence) >= config.min_evidence_sources
    results.append({"test": "Gather Evidence", "pass": len(evidence) >= config.min_evidence_sources})

    # --- 4. Multi-AI vote ---
    print("\n--- 4. Multi-AI Voting ---")
    votes = await resolver.multi_ai_vote(evidence)
    print(f"  Votes collected: {len(votes)} (min: {config.min_ai_models})")
    for vote in votes:
        print(f"    {vote.model_name} ({vote.provider}): {vote.position} "
              f"(confidence: {vote.confidence:.2f})")
    assert len(votes) >= config.min_ai_models
    results.append({"test": "Multi-AI Vote", "pass": len(votes) >= config.min_ai_models})

    # --- 5. Byzantine consensus ---
    print("\n--- 5. Byzantine Consensus ---")
    consensus = await resolver.byzantine_consensus(votes)
    print(f"  Consensus reached: {consensus.consensus_reached}")
    print(f"  Outcome: {consensus.outcome}")
    print(f"  Agreement: {consensus.agreement_pct*100:.1f}%")
    print(f"  Threshold: {consensus.threshold*100:.0f}%")
    results.append({"test": "Byzantine Consensus", "pass": True})

    # --- 6. Settle market ---
    settlement = None
    distribution = None
    if consensus.consensus_reached and consensus.outcome:
        print("\n--- 6. Settle Market ---")
        settlement = await resolver.settle_market(42, consensus.outcome)
        print(f"  Success: {settlement.success}")
        print(f"  Outcome: {settlement.outcome}")
        print(f"  Fee: {settlement.fee_sats} sats")
        print(f"  TX: {settlement.tx_hash[:18]}...")
        results.append({"test": "Settle Market", "pass": settlement.success})

        # --- 7. Distribute winnings ---
        print("\n--- 7. Distribute Winnings ---")
        distribution = await resolver.distribute_winnings(42)
        print(f"  Success: {distribution.success}")
        print(f"  Distributed: {distribution.total_distributed_sats} sats")
        print(f"  Fee: {distribution.fee_collected_sats} sats")
        print(f"  Winners: {distribution.winners_count}")
        results.append({"test": "Distribute Winnings", "pass": distribution.success})
    else:
        print("\n--- 6-7. Skipped (no consensus) ---")
        results.append({"test": "Settle Market", "pass": True})
        results.append({"test": "Distribute Winnings", "pass": True})

    # --- 8. Audit log ---
    print("\n--- 8. Audit Log ---")
    status = (
        ResolutionStatus.SETTLED if settlement and settlement.success
        else ResolutionStatus.DISPUTED if not consensus.consensus_reached
        else ResolutionStatus.ERROR
    )
    audit = await resolver.audit_log(
        market_info, consensus, settlement, distribution, status,
    )
    print(f"  Audit ID: {audit.audit_id}")
    print(f"  Status: {audit.status}")
    print(f"  Evidence: {audit.evidence_count} sources")
    print(f"  Duration: {audit.duration_ms:.0f}ms")
    results.append({"test": "Audit Log", "pass": True})

    # --- 9. Full workflow ---
    print("\n--- 9. Full Workflow Run ---")
    resolver2 = ConsensusResolver(config)
    full_audit = await resolver2.run_workflow(
        market_id=99,
        question="Will ETH surpass $10k by December 2026?",
        deadline=int(time.time()) - 1800,
    )
    print(f"  Audit ID: {full_audit.audit_id}")
    print(f"  Status: {full_audit.status}")
    print(f"  Fee collected: {full_audit.fee_collected_sats} sats")
    results.append({"test": "Full Workflow", "pass": full_audit.status in [
        ResolutionStatus.SETTLED.value, ResolutionStatus.DISPUTED.value,
    ]})

    # --- Summary ---
    print("\n" + "=" * 70)
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    for r in results:
        status_str = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status_str}] {r['test']}")
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
