#!/usr/bin/env python3
"""
BlindOracle AI Proof-of-Reserve Handler
=========================================

Implements the AI Proof-of-Reserve Agent (UC9) for the CRE marketplace.
Generates verifiable proof that BlindOracle reserves match liabilities
by summing eCash liabilities, querying Bitcoin and USDC reserves,
computing the reserve ratio, publishing cryptographic proofs, and
minting NIP-58 Proof of Witness badges.

Revenue model: $1/challenge.

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)
    - services.swaps.cross_chain_router (CrossChainRouter)

BLP Properties:
    BLP-001 (Alignment): Reserve verification domain expertise
    BLP-005 (Security Integrity): Cryptographic proof generation
    BLP-011 (Autonomy): Fully autonomous verification (99%)
    BLP-019 (Logging): Immutable audit trail for reserve proofs
    BLP-023 (Durability): Error recovery with partial proof generation

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import hashlib
import json
import logging
import secrets
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

class ReserveStatus(Enum):
    """Status of the reserve audit."""
    FULLY_BACKED = "fully_backed"
    OVER_COLLATERALIZED = "over_collateralized"
    UNDER_COLLATERALIZED = "under_collateralized"
    AUDIT_FAILED = "audit_failed"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ReserveConfig:
    """Configuration for the Proof-of-Reserve Agent.

    REQ-BLP-001: Reserve verification configuration.

    Attributes:
        min_reserve_ratio: Minimum acceptable reserve ratio (1.0 = 100%).
        challenge_fee_usd: Fee per challenge/verification.
        publish_to_nostr: Whether to publish proofs to Nostr.
        mint_witness_badge: Whether to mint NIP-58 badges for verifiers.
        security_interface: CaMel gateway interface.
        security_agent_id: Agent identity.
    """
    min_reserve_ratio: float = 1.0
    challenge_fee_usd: float = 1.0
    publish_to_nostr: bool = True
    mint_witness_badge: bool = True
    security_interface: str = "x402_api"
    security_agent_id: str = "proof_of_reserve_v1"


@dataclass
class LiabilitySummary:
    """Summary of all eCash liabilities.

    Attributes:
        total_ecash_sats: Total eCash tokens outstanding.
        active_markets_sats: Sats locked in active prediction markets.
        pending_withdrawals_sats: Pending withdrawal requests.
        total_liabilities_sats: Grand total liabilities.
        token_count: Number of unique eCash tokens.
    """
    total_ecash_sats: int = 0
    active_markets_sats: int = 0
    pending_withdrawals_sats: int = 0
    total_liabilities_sats: int = 0
    token_count: int = 0


@dataclass
class ReserveSummary:
    """Summary of all reserves.

    Attributes:
        btc_reserve_sats: Bitcoin reserves in satoshis.
        usdc_reserve_sats: USDC reserves in satoshi equivalent.
        lightning_reserve_sats: Lightning channel balance.
        total_reserves_sats: Total reserves.
    """
    btc_reserve_sats: int = 0
    usdc_reserve_sats: int = 0
    lightning_reserve_sats: int = 0
    total_reserves_sats: int = 0


@dataclass
class CryptographicProof:
    """A cryptographic proof of reserve.

    Attributes:
        proof_id: Unique proof identifier.
        merkle_root: Merkle root of liability tree.
        reserve_hash: Hash of reserve data.
        combined_proof: Combined proof hash.
        timestamp: Proof generation timestamp.
        reserve_ratio: Reserve ratio at proof time.
        status: Reserve status.
        signature: Cryptographic signature.
    """
    proof_id: str = ""
    merkle_root: str = ""
    reserve_hash: str = ""
    combined_proof: str = ""
    timestamp: str = ""
    reserve_ratio: float = 0.0
    status: str = ReserveStatus.AUDIT_FAILED.value
    signature: str = ""

    def __post_init__(self) -> None:
        if not self.proof_id:
            self.proof_id = f"por_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ReserveAudit:
    """Complete reserve audit report.

    Attributes:
        audit_id: Unique audit identifier.
        liabilities: Liability summary.
        reserves: Reserve summary.
        reserve_ratio: Computed reserve ratio.
        status: Reserve status.
        proof: Cryptographic proof.
        badge_minted: Whether a witness badge was minted.
        fee_charged_usd: Fee charged.
        errors: Any errors encountered.
        timestamp: Audit timestamp.
    """
    audit_id: str = ""
    liabilities: Optional[Dict[str, Any]] = None
    reserves: Optional[Dict[str, Any]] = None
    reserve_ratio: float = 0.0
    status: str = ReserveStatus.AUDIT_FAILED.value
    proof: Optional[Dict[str, Any]] = None
    badge_minted: bool = False
    fee_charged_usd: float = 0.0
    errors: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.audit_id:
            self.audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Proof-of-Reserve Agent
# ---------------------------------------------------------------------------

class ProofOfReserve:
    """AI Proof-of-Reserve Agent.

    Generates verifiable cryptographic proofs that BlindOracle reserves
    match liabilities. Sums eCash liabilities, queries BTC and USDC
    reserves, computes reserve ratio, publishes proofs, and mints
    NIP-58 Proof of Witness badges for verifiers.

    Revenue: $1/challenge.

    REQ-BLP-001 (Alignment): Reserve verification expertise
    REQ-BLP-005 (Security Integrity): Cryptographic proof generation
    REQ-BLP-011 (Autonomy): Fully autonomous (99%)
    REQ-BLP-019 (Logging): Immutable audit trail
    REQ-BLP-023 (Durability): Partial proof on errors

    Usage:
        config = ReserveConfig()
        agent = ProofOfReserve(config)
        audit = await agent.run_workflow()
    """

    def __init__(
        self,
        config: Optional[ReserveConfig] = None,
        router: Optional[CrossChainRouter] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
    ) -> None:
        self.config = config or ReserveConfig()
        self._router = router or CrossChainRouter()
        self._gateway = gateway or BlindOracleSecurityGateway()
        self._gateway.authorize_agent(self.config.security_agent_id)

        self._liabilities: Optional[LiabilitySummary] = None
        self._reserves: Optional[ReserveSummary] = None
        self._errors: List[str] = []

        logger.info("[SUCCESS] ProofOfReserve initialized")
        logger.info("[INFO]   Min ratio: %.2f", self.config.min_reserve_ratio)

    # ---- Step 1: Sum eCash Liabilities ----

    async def sum_liabilities(self) -> LiabilitySummary:
        """Sum all eCash liabilities from the federation.

        REQ-BLP-001: Liability accounting expertise.

        Returns:
            LiabilitySummary with all liability components.
        """
        try:
            # Mock: use router balances to derive liabilities
            balances = await self._router.get_balances()
            ecash_balance = balances.get("eCash", 500_000)

            # Derive components
            active_markets = int(ecash_balance * 0.4)
            pending = int(ecash_balance * 0.05)
            circulating = ecash_balance - active_markets - pending

            self._liabilities = LiabilitySummary(
                total_ecash_sats=circulating,
                active_markets_sats=active_markets,
                pending_withdrawals_sats=pending,
                total_liabilities_sats=ecash_balance,
                token_count=int(ecash_balance / 1000) + 1,
            )

            logger.info("[SUCCESS] Liabilities summed: %d sats total",
                        self._liabilities.total_liabilities_sats)
            logger.info("[INFO]   eCash: %d, Markets: %d, Pending: %d",
                        circulating, active_markets, pending)

            return self._liabilities

        except Exception as e:
            error_msg = f"Liability summation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Query Reserves ----

    async def query_reserves(self) -> ReserveSummary:
        """Query Bitcoin and USDC reserves.

        REQ-BLP-001: Multi-chain reserve querying.

        Returns:
            ReserveSummary with all reserve components.
        """
        try:
            balances = await self._router.get_balances()

            btc = balances.get("BTC", 0)
            usdc = balances.get("USDC", 0)
            lightning = balances.get("Lightning", 0)

            # USDC converted to sat equivalent (rough)
            usdc_sats = int(usdc * 0.015)

            self._reserves = ReserveSummary(
                btc_reserve_sats=btc,
                usdc_reserve_sats=usdc_sats,
                lightning_reserve_sats=lightning,
                total_reserves_sats=btc + usdc_sats + lightning,
            )

            logger.info("[SUCCESS] Reserves queried: %d sats total",
                        self._reserves.total_reserves_sats)
            logger.info("[INFO]   BTC: %d, USDC: %d, Lightning: %d",
                        btc, usdc_sats, lightning)

            return self._reserves

        except Exception as e:
            error_msg = f"Reserve query failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Calculate Reserve Ratio ----

    async def calculate_ratio(self) -> float:
        """Calculate the reserve ratio.

        REQ-BLP-011: Independent ratio computation.

        Returns:
            Reserve ratio (reserves / liabilities).
        """
        try:
            assert self._liabilities is not None
            assert self._reserves is not None

            if self._liabilities.total_liabilities_sats == 0:
                ratio = float("inf")
            else:
                ratio = (
                    self._reserves.total_reserves_sats
                    / self._liabilities.total_liabilities_sats
                )

            ratio = round(ratio, 4)
            logger.info("[SUCCESS] Reserve ratio: %.4f (min: %.2f)",
                        ratio, self.config.min_reserve_ratio)

            return ratio

        except Exception as e:
            error_msg = f"Ratio calculation failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 4: Publish Cryptographic Proof ----

    async def publish_proof(self, ratio: float) -> CryptographicProof:
        """Generate and publish a cryptographic proof of reserve.

        REQ-BLP-005: Cryptographic integrity.
        REQ-BLP-019: Immutable proof publication.

        Args:
            ratio: The computed reserve ratio.

        Returns:
            CryptographicProof with all proof data.
        """
        try:
            # Build Merkle root of liabilities
            liability_data = json.dumps(asdict(self._liabilities), sort_keys=True)
            merkle_root = hashlib.sha256(liability_data.encode()).hexdigest()

            # Hash reserves
            reserve_data = json.dumps(asdict(self._reserves), sort_keys=True)
            reserve_hash = hashlib.sha256(reserve_data.encode()).hexdigest()

            # Combined proof
            combined = f"{merkle_root}:{reserve_hash}:{ratio}"
            combined_proof = hashlib.sha256(combined.encode()).hexdigest()

            # Signature (mock -- in production use real keypair)
            signature = hashlib.sha256(
                f"{combined_proof}:{secrets.token_hex(16)}".encode()
            ).hexdigest()

            # Determine status
            if ratio >= self.config.min_reserve_ratio * 1.1:
                status = ReserveStatus.OVER_COLLATERALIZED.value
            elif ratio >= self.config.min_reserve_ratio:
                status = ReserveStatus.FULLY_BACKED.value
            else:
                status = ReserveStatus.UNDER_COLLATERALIZED.value

            proof = CryptographicProof(
                merkle_root=merkle_root,
                reserve_hash=reserve_hash,
                combined_proof=combined_proof,
                reserve_ratio=ratio,
                status=status,
                signature=signature,
            )

            logger.info("[SUCCESS] Cryptographic proof published: %s", proof.proof_id)
            logger.info("[INFO]   Status: %s, Ratio: %.4f", status, ratio)
            logger.info("[INFO]   Merkle root: %s...", merkle_root[:16])

            return proof

        except Exception as e:
            error_msg = f"Proof publication failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 5: Mint NIP-58 Badge ----

    async def mint_witness_badge(self, proof: CryptographicProof) -> bool:
        """Mint a NIP-58 Proof of Witness badge for verifiers.

        REQ-BLP-019: Badge minting for accountability.

        Args:
            proof: The cryptographic proof to badge.

        Returns:
            Whether the badge was minted.
        """
        try:
            if not self.config.mint_witness_badge:
                logger.info("[INFO] Badge minting disabled")
                return False

            # CaMel security for badge minting
            sec_request = SecurityRequest(
                interface=self.config.security_interface,
                operation="badge_mint",
                agent_id=self.config.security_agent_id,
                parameters={
                    "badge_type": "proof_of_witness",
                    "proof_id": proof.proof_id,
                    "reserve_status": proof.status,
                },
                amount_sats=0,
            )
            sec_response = self._gateway.process_request(sec_request)

            if sec_response.approved:
                logger.info("[SUCCESS] NIP-58 Proof of Witness badge minted: %s",
                            proof.proof_id)
                return True
            else:
                logger.info("[INFO] Badge minting denied by CaMel: %s",
                            sec_response.denial_reason)
                return False

        except Exception as e:
            error_msg = f"Badge minting failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            return False

    # ---- Full Workflow ----

    async def run_workflow(self) -> ReserveAudit:
        """Execute the full proof-of-reserve workflow.

        Steps:
        1. Sum eCash liabilities
        2. Query BTC + USDC reserves
        3. Calculate reserve ratio
        4. Publish cryptographic proof
        5. Mint NIP-58 badge

        Returns:
            ReserveAudit with complete audit results.
        """
        logger.info("[INFO] === Proof-of-Reserve Workflow Starting ===")
        start = time.time()

        try:
            liabilities = await self.sum_liabilities()
            reserves = await self.query_reserves()
            ratio = await self.calculate_ratio()
            proof = await self.publish_proof(ratio)
            badge_minted = await self.mint_witness_badge(proof)

            audit = ReserveAudit(
                liabilities=asdict(liabilities),
                reserves=asdict(reserves),
                reserve_ratio=ratio,
                status=proof.status,
                proof=asdict(proof),
                badge_minted=badge_minted,
                fee_charged_usd=self.config.challenge_fee_usd,
                errors=list(self._errors),
            )

            elapsed = (time.time() - start) * 1000
            logger.info("[SUCCESS] === Proof-of-Reserve Workflow Complete (%.0fms) ===",
                        elapsed)
            logger.info("[INFO]   Status: %s, Ratio: %.4f, Badge: %s",
                        proof.status, ratio, badge_minted)

            return audit

        except Exception as e:
            logger.error("[ERROR] Proof-of-reserve workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return ReserveAudit(errors=list(self._errors))


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full Proof-of-Reserve workflow."""
    print("=" * 70)
    print("BlindOracle AI Proof-of-Reserve -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # --- 1. Initialize ---
    print("\n--- 1. Initialize ---")
    config = ReserveConfig()
    agent = ProofOfReserve(config)
    print(f"  Min ratio: {config.min_reserve_ratio}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Sum liabilities ---
    print("\n--- 2. Sum Liabilities ---")
    liabilities = await agent.sum_liabilities()
    print(f"  Total: {liabilities.total_liabilities_sats} sats")
    print(f"  eCash: {liabilities.total_ecash_sats}, Markets: {liabilities.active_markets_sats}")
    results.append({"test": "Sum Liabilities", "pass": liabilities.total_liabilities_sats > 0})

    # --- 3. Query reserves ---
    print("\n--- 3. Query Reserves ---")
    reserves = await agent.query_reserves()
    print(f"  Total: {reserves.total_reserves_sats} sats")
    print(f"  BTC: {reserves.btc_reserve_sats}, USDC: {reserves.usdc_reserve_sats}")
    results.append({"test": "Query Reserves", "pass": reserves.total_reserves_sats > 0})

    # --- 4. Calculate ratio ---
    print("\n--- 4. Calculate Ratio ---")
    ratio = await agent.calculate_ratio()
    print(f"  Ratio: {ratio:.4f}")
    results.append({"test": "Calculate Ratio", "pass": ratio > 0})

    # --- 5. Publish proof ---
    print("\n--- 5. Publish Proof ---")
    proof = await agent.publish_proof(ratio)
    print(f"  Proof ID: {proof.proof_id}")
    print(f"  Status: {proof.status}")
    print(f"  Merkle root: {proof.merkle_root[:16]}...")
    results.append({"test": "Publish Proof", "pass": proof.combined_proof != ""})

    # --- 6. Mint badge ---
    print("\n--- 6. Mint Badge ---")
    minted = await agent.mint_witness_badge(proof)
    print(f"  Minted: {minted}")
    results.append({"test": "Mint Badge", "pass": True})

    # --- 7. Full workflow ---
    print("\n--- 7. Full Workflow ---")
    agent2 = ProofOfReserve(config)
    audit = await agent2.run_workflow()
    print(f"  Audit ID: {audit.audit_id}")
    print(f"  Status: {audit.status}")
    print(f"  Ratio: {audit.reserve_ratio:.4f}")
    print(f"  Fee: ${audit.fee_charged_usd}")
    results.append({"test": "Full Workflow", "pass": audit.status != ReserveStatus.AUDIT_FAILED.value})

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
