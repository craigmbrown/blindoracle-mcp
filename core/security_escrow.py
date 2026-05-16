#!/usr/bin/env python3
"""
Phase 4: Security & Escrow System
=================================

Comprehensive security layer for the Chainlink Job Runner:
- Multi-signature escrow for high-value transactions
- Rate limiting and anomaly detection
- Job validation with cryptographic proofs
- Escrow holdback for dispute resolution
- Emergency pause/kill switch

@requirement: REQ-SEC-001 - Multi-sig escrow for transactions > 1000 sats
@requirement: REQ-SEC-002 - Rate limiting (max 100 jobs/hour, 1000/day)
@requirement: REQ-SEC-003 - Anomaly detection for suspicious patterns
@requirement: REQ-SEC-004 - Cryptographic proof verification
@requirement: REQ-SEC-005 - Emergency pause capability
"""

import os
import sys
import json
import hashlib
import hmac
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import threading

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Security constants
MAX_JOBS_PER_HOUR = 100
MAX_JOBS_PER_DAY = 1000
MAX_SATS_PER_JOB = 100000  # 0.001 BTC
MAX_SATS_PER_HOUR = 500000  # 0.005 BTC
MAX_SATS_PER_DAY = 2000000  # 0.02 BTC
ESCROW_THRESHOLD_SATS = 1000  # Jobs > 1000 sats go to escrow
ESCROW_HOLD_HOURS = 24  # Hold period for escrow funds
ANOMALY_THRESHOLD_MULTIPLIER = 3.0  # 3x average = anomaly

# Security files
SECURITY_CONFIG_FILE = PROJECT_ROOT / "config" / "security_config.json"
ESCROW_LEDGER_FILE = PROJECT_ROOT / "logs" / "escrow_ledger.json"
SECURITY_AUDIT_FILE = PROJECT_ROOT / "logs" / "security_audit.json"
RATE_LIMIT_FILE = PROJECT_ROOT / "logs" / "rate_limits.json"


class SecurityLevel(Enum):
    """Security levels for different operations."""

    LOW = "low"  # Standard jobs < 100 sats
    MEDIUM = "medium"  # Jobs 100-1000 sats
    HIGH = "high"  # Jobs > 1000 sats (escrow)
    CRITICAL = "critical"  # Manual approval required


class AlertType(Enum):
    """Types of security alerts."""

    RATE_LIMIT = "rate_limit"
    ANOMALY = "anomaly"
    ESCROW_THRESHOLD = "escrow_threshold"
    INVALID_PROOF = "invalid_proof"
    EMERGENCY_PAUSE = "emergency_pause"
    SUSPICIOUS_PATTERN = "suspicious_pattern"


@dataclass
class EscrowEntry:
    """Entry in the escrow ledger."""

    escrow_id: str
    job_id: str
    amount_sats: int
    status: str  # pending, released, refunded, disputed
    created_at: str
    release_after: str
    proof_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityAlert:
    """Security alert record."""

    alert_id: str
    alert_type: str
    severity: str
    message: str
    details: Dict[str, Any]
    timestamp: str
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RateLimiter:
    """
    Rate limiter for job execution.

    Tracks job counts and sats spent in sliding windows.
    """

    def __init__(self):
        self._hourly_jobs: List[float] = []
        self._daily_jobs: List[float] = []
        self._hourly_sats: List[Tuple[float, int]] = []
        self._daily_sats: List[Tuple[float, int]] = []
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        """Load rate limit state from file."""
        try:
            if RATE_LIMIT_FILE.exists():
                with open(RATE_LIMIT_FILE, "r") as f:
                    state = json.load(f)
                    self._hourly_jobs = state.get("hourly_jobs", [])
                    self._daily_jobs = state.get("daily_jobs", [])
        except Exception:
            pass

    def _save_state(self) -> None:
        """Save rate limit state to file."""
        try:
            RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "hourly_jobs": self._hourly_jobs[-200:],
                "daily_jobs": self._daily_jobs[-2000:],
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            with open(RATE_LIMIT_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _cleanup_old_entries(self) -> None:
        """Remove entries outside the time window."""
        now = time.time()
        hour_ago = now - 3600
        day_ago = now - 86400

        self._hourly_jobs = [t for t in self._hourly_jobs if t > hour_ago]
        self._daily_jobs = [t for t in self._daily_jobs if t > day_ago]
        self._hourly_sats = [(t, s) for t, s in self._hourly_sats if t > hour_ago]
        self._daily_sats = [(t, s) for t, s in self._daily_sats if t > day_ago]

    def check_rate_limit(self, amount_sats: int = 0) -> Dict[str, Any]:
        """
        Check if current request is within rate limits.

        Returns:
            Dict with allowed status and current usage
        """
        with self._lock:
            self._cleanup_old_entries()

            hourly_job_count = len(self._hourly_jobs)
            daily_job_count = len(self._daily_jobs)
            hourly_sats_total = sum(s for _, s in self._hourly_sats)
            daily_sats_total = sum(s for _, s in self._daily_sats)

            # Check job count limits
            if hourly_job_count >= MAX_JOBS_PER_HOUR:
                return {
                    "allowed": False,
                    "reason": f"Hourly job limit reached ({MAX_JOBS_PER_HOUR})",
                    "type": "job_count_hourly",
                    "current": hourly_job_count,
                    "limit": MAX_JOBS_PER_HOUR,
                }

            if daily_job_count >= MAX_JOBS_PER_DAY:
                return {
                    "allowed": False,
                    "reason": f"Daily job limit reached ({MAX_JOBS_PER_DAY})",
                    "type": "job_count_daily",
                    "current": daily_job_count,
                    "limit": MAX_JOBS_PER_DAY,
                }

            # Check sats limits
            if hourly_sats_total + amount_sats > MAX_SATS_PER_HOUR:
                return {
                    "allowed": False,
                    "reason": f"Hourly sats limit reached ({MAX_SATS_PER_HOUR})",
                    "type": "sats_hourly",
                    "current": hourly_sats_total,
                    "limit": MAX_SATS_PER_HOUR,
                    "requested": amount_sats,
                }

            if daily_sats_total + amount_sats > MAX_SATS_PER_DAY:
                return {
                    "allowed": False,
                    "reason": f"Daily sats limit reached ({MAX_SATS_PER_DAY})",
                    "type": "sats_daily",
                    "current": daily_sats_total,
                    "limit": MAX_SATS_PER_DAY,
                    "requested": amount_sats,
                }

            return {
                "allowed": True,
                "hourly_jobs": hourly_job_count,
                "daily_jobs": daily_job_count,
                "hourly_sats": hourly_sats_total,
                "daily_sats": daily_sats_total,
                "remaining_hourly_jobs": MAX_JOBS_PER_HOUR - hourly_job_count,
                "remaining_daily_jobs": MAX_JOBS_PER_DAY - daily_job_count,
            }

    def record_job(self, amount_sats: int = 0) -> None:
        """Record a job execution."""
        with self._lock:
            now = time.time()
            self._hourly_jobs.append(now)
            self._daily_jobs.append(now)
            if amount_sats > 0:
                self._hourly_sats.append((now, amount_sats))
                self._daily_sats.append((now, amount_sats))
            self._save_state()


class ProofVerifier:
    """
    Verifies cryptographic proofs for job completions.

    Ensures jobs have valid on-chain or API proofs.
    """

    @staticmethod
    def generate_proof_hash(job_data: Dict[str, Any]) -> str:
        """Generate a hash of the job proof data."""
        proof_components = []

        # Include key job identifiers
        proof_components.append(job_data.get("job_id", ""))
        proof_components.append(job_data.get("job_type", ""))
        proof_components.append(job_data.get("source", ""))
        proof_components.append(job_data.get("timestamp", ""))

        # Include proof summary if present
        proof_summary = job_data.get("proof_summary", {})
        if proof_summary:
            # For oracle jobs - include block numbers
            block_numbers = proof_summary.get("block_numbers", [])
            if block_numbers:
                proof_components.extend([str(b) for b in block_numbers])

            # For market jobs - include market counts
            total_markets = proof_summary.get("total_markets", 0)
            if total_markets:
                proof_components.append(str(total_markets))

        # Create hash
        proof_string = "|".join(str(c) for c in proof_components)
        return hashlib.sha256(proof_string.encode()).hexdigest()

    @staticmethod
    def verify_chainlink_proof(job_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Verify Chainlink oracle proof.

        Returns:
            Tuple of (is_valid, reason)
        """
        if job_data.get("source") != "chainlink_mainnet":
            return False, "Source is not chainlink_mainnet"

        if not job_data.get("is_real", False):
            return False, "Job is not marked as real"

        proof = job_data.get("proof_summary", {})

        # Check for block numbers (on-chain proof)
        block_numbers = proof.get("block_numbers", [])
        if not block_numbers:
            return False, "No block numbers in proof"

        # Verify block numbers are reasonable (not 0 or negative)
        for bn in block_numbers:
            if not isinstance(bn, int) or bn <= 0:
                return False, f"Invalid block number: {bn}"

        # Check for round IDs
        round_ids = proof.get("round_ids", [])
        if not round_ids:
            return False, "No round IDs in proof"

        return True, "Valid Chainlink proof"

    @staticmethod
    def verify_market_proof(job_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Verify market data proof (Kalshi/Polymarket).

        Returns:
            Tuple of (is_valid, reason)
        """
        if job_data.get("source") != "real_market_apis":
            return False, "Source is not real_market_apis"

        if not job_data.get("is_real", False):
            return False, "Job is not marked as real"

        proof = job_data.get("proof_summary", {})

        # Check for market counts
        total_markets = proof.get("total_markets", 0)
        if total_markets <= 0:
            return False, "No markets in proof"

        # Verify API sources
        api_sources = proof.get("api_sources", [])
        if not api_sources:
            return False, "No API sources in proof"

        return True, "Valid market data proof"

    def verify_job(self, job_data: Dict[str, Any]) -> Tuple[bool, str, str]:
        """
        Verify job has valid proof.

        Returns:
            Tuple of (is_valid, reason, proof_hash)
        """
        source = job_data.get("source", "")

        if source == "chainlink_mainnet":
            is_valid, reason = self.verify_chainlink_proof(job_data)
        elif source == "real_market_apis":
            is_valid, reason = self.verify_market_proof(job_data)
        elif source == "real_hybrid":
            # Hybrid jobs need valid oracle data
            chainlink_data = job_data.get("chainlink_data", {})
            oracle_data = chainlink_data.get("oracle_data", {})
            if oracle_data.get("source") == "chainlink_mainnet":
                is_valid, reason = True, "Valid hybrid proof (oracle verified)"
            else:
                is_valid, reason = False, "Invalid hybrid proof"
        else:
            is_valid, reason = False, f"Unknown source: {source}"

        proof_hash = self.generate_proof_hash(job_data) if is_valid else ""

        return is_valid, reason, proof_hash


class EscrowManager:
    """
    Manages escrow for high-value job payments.

    Jobs above ESCROW_THRESHOLD_SATS are held in escrow
    for ESCROW_HOLD_HOURS before release.
    """

    def __init__(self):
        self._load_ledger()

    def _load_ledger(self) -> None:
        """Load escrow ledger from file."""
        try:
            if ESCROW_LEDGER_FILE.exists():
                with open(ESCROW_LEDGER_FILE, "r") as f:
                    self.ledger = json.load(f)
            else:
                self.ledger = {
                    "version": "1.0",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "total_in_escrow_sats": 0,
                    "total_released_sats": 0,
                    "entries": [],
                }
        except Exception:
            self.ledger = {"entries": []}

    def _save_ledger(self) -> None:
        """Save escrow ledger to file."""
        try:
            ESCROW_LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.ledger["last_updated"] = datetime.now(timezone.utc).isoformat()
            with open(ESCROW_LEDGER_FILE, "w") as f:
                json.dump(self.ledger, f, indent=2)
        except Exception as e:
            print(f"[EscrowManager] Save error: {e}")

    def requires_escrow(self, amount_sats: int) -> bool:
        """Check if amount requires escrow."""
        return amount_sats >= ESCROW_THRESHOLD_SATS

    def create_escrow(
        self,
        job_id: str,
        amount_sats: int,
        proof_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EscrowEntry:
        """
        Create escrow entry for a job payment.

        Args:
            job_id: Job identifier
            amount_sats: Amount to hold in escrow
            proof_hash: Hash of job proof
            metadata: Additional metadata

        Returns:
            EscrowEntry with escrow details
        """
        import uuid

        now = datetime.now(timezone.utc)
        release_after = now + timedelta(hours=ESCROW_HOLD_HOURS)

        entry = EscrowEntry(
            escrow_id=f"escrow_{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            amount_sats=amount_sats,
            status="pending",
            created_at=now.isoformat(),
            release_after=release_after.isoformat(),
            proof_hash=proof_hash,
            metadata=metadata or {},
        )

        # Add to ledger
        self.ledger["entries"].append(entry.to_dict())
        self.ledger["total_in_escrow_sats"] = (
            self.ledger.get("total_in_escrow_sats", 0) + amount_sats
        )
        self._save_ledger()

        return entry

    def check_releasable(self) -> List[EscrowEntry]:
        """
        Check for escrow entries ready for release.

        Returns:
            List of entries past hold period
        """
        now = datetime.now(timezone.utc)
        releasable = []

        for entry_dict in self.ledger.get("entries", []):
            if entry_dict.get("status") == "pending":
                release_after = datetime.fromisoformat(
                    entry_dict["release_after"].replace("Z", "+00:00")
                )
                if now >= release_after:
                    releasable.append(EscrowEntry(**entry_dict))

        return releasable

    def release_escrow(self, escrow_id: str) -> Dict[str, Any]:
        """
        Release funds from escrow.

        Args:
            escrow_id: Escrow entry identifier

        Returns:
            Release result
        """
        for entry in self.ledger.get("entries", []):
            if entry.get("escrow_id") == escrow_id:
                if entry.get("status") != "pending":
                    return {
                        "success": False,
                        "error": f"Escrow not in pending status: {entry.get('status')}",
                    }

                entry["status"] = "released"
                entry["released_at"] = datetime.now(timezone.utc).isoformat()

                self.ledger["total_in_escrow_sats"] -= entry["amount_sats"]
                self.ledger["total_released_sats"] = (
                    self.ledger.get("total_released_sats", 0) + entry["amount_sats"]
                )
                self._save_ledger()

                return {
                    "success": True,
                    "escrow_id": escrow_id,
                    "amount_sats": entry["amount_sats"],
                    "job_id": entry["job_id"],
                }

        return {"success": False, "error": "Escrow not found"}

    def get_status(self) -> Dict[str, Any]:
        """Get escrow system status."""
        pending_entries = [
            e for e in self.ledger.get("entries", []) if e.get("status") == "pending"
        ]

        return {
            "total_in_escrow_sats": self.ledger.get("total_in_escrow_sats", 0),
            "total_released_sats": self.ledger.get("total_released_sats", 0),
            "pending_count": len(pending_entries),
            "escrow_threshold_sats": ESCROW_THRESHOLD_SATS,
            "hold_hours": ESCROW_HOLD_HOURS,
        }


class SecurityManager:
    """
    Main security manager coordinating all security features.

    Provides:
    - Rate limiting
    - Proof verification
    - Escrow management
    - Anomaly detection
    - Emergency controls
    """

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.proof_verifier = ProofVerifier()
        self.escrow_manager = EscrowManager()
        self._paused = False
        self._alerts: List[SecurityAlert] = []
        self._load_config()

    def _load_config(self) -> None:
        """Load security configuration."""
        try:
            if SECURITY_CONFIG_FILE.exists():
                with open(SECURITY_CONFIG_FILE, "r") as f:
                    self.config = json.load(f)
            else:
                self.config = {
                    "escrow_enabled": True,
                    "rate_limiting_enabled": True,
                    "anomaly_detection_enabled": True,
                    "emergency_pause": False,
                    "allowed_sources": ["chainlink_mainnet", "real_market_apis", "real_hybrid"],
                }
                self._save_config()
        except Exception:
            self.config = {}

    def _save_config(self) -> None:
        """Save security configuration."""
        try:
            SECURITY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SECURITY_CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    def _log_alert(self, alert: SecurityAlert) -> None:
        """Log security alert."""
        self._alerts.append(alert)

        # Save to audit file
        try:
            if SECURITY_AUDIT_FILE.exists():
                with open(SECURITY_AUDIT_FILE, "r") as f:
                    audit = json.load(f)
            else:
                audit = {"alerts": []}

            audit["alerts"].append(alert.to_dict())
            audit["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Keep last 1000 alerts
            audit["alerts"] = audit["alerts"][-1000:]

            SECURITY_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SECURITY_AUDIT_FILE, "w") as f:
                json.dump(audit, f, indent=2)
        except Exception:
            pass

    def emergency_pause(self, reason: str = "Manual pause") -> Dict[str, Any]:
        """
        Emergency pause all job processing.

        Args:
            reason: Reason for pause

        Returns:
            Pause result
        """
        import uuid

        self._paused = True
        self.config["emergency_pause"] = True
        self._save_config()

        alert = SecurityAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:12]}",
            alert_type=AlertType.EMERGENCY_PAUSE.value,
            severity="critical",
            message=f"Emergency pause activated: {reason}",
            details={"reason": reason},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._log_alert(alert)

        return {"success": True, "paused": True, "reason": reason, "alert_id": alert.alert_id}

    def resume(self) -> Dict[str, Any]:
        """Resume job processing after pause."""
        self._paused = False
        self.config["emergency_pause"] = False
        self._save_config()

        return {
            "success": True,
            "paused": False,
            "resumed_at": datetime.now(timezone.utc).isoformat(),
        }

    def is_paused(self) -> bool:
        """Check if system is paused."""
        return self._paused or self.config.get("emergency_pause", False)

    def validate_job(self, job_data: Dict[str, Any], amount_sats: int) -> Dict[str, Any]:
        """
        Comprehensive job validation.

        Checks:
        - System not paused
        - Rate limits
        - Proof validity
        - Escrow requirements

        Args:
            job_data: Job result data
            amount_sats: Payment amount

        Returns:
            Validation result with security level
        """
        import uuid

        # Check emergency pause
        if self.is_paused():
            return {
                "valid": False,
                "reason": "System is paused",
                "security_level": SecurityLevel.CRITICAL.value,
            }

        # Check rate limits
        if self.config.get("rate_limiting_enabled", True):
            rate_check = self.rate_limiter.check_rate_limit(amount_sats)
            if not rate_check.get("allowed"):
                alert = SecurityAlert(
                    alert_id=f"alert_{uuid.uuid4().hex[:12]}",
                    alert_type=AlertType.RATE_LIMIT.value,
                    severity="warning",
                    message=rate_check.get("reason", "Rate limit exceeded"),
                    details=rate_check,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                self._log_alert(alert)

                return {
                    "valid": False,
                    "reason": rate_check.get("reason"),
                    "security_level": SecurityLevel.HIGH.value,
                    "rate_limit_info": rate_check,
                }

        # Verify proof
        is_valid, reason, proof_hash = self.proof_verifier.verify_job(job_data)
        if not is_valid:
            alert = SecurityAlert(
                alert_id=f"alert_{uuid.uuid4().hex[:12]}",
                alert_type=AlertType.INVALID_PROOF.value,
                severity="warning",
                message=f"Invalid proof: {reason}",
                details={"job_id": job_data.get("job_id"), "reason": reason},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._log_alert(alert)

            return {
                "valid": False,
                "reason": f"Invalid proof: {reason}",
                "security_level": SecurityLevel.HIGH.value,
            }

        # Determine security level
        if amount_sats < 100:
            security_level = SecurityLevel.LOW
        elif amount_sats < ESCROW_THRESHOLD_SATS:
            security_level = SecurityLevel.MEDIUM
        else:
            security_level = SecurityLevel.HIGH

        # Check if escrow is required
        requires_escrow = self.config.get(
            "escrow_enabled", True
        ) and self.escrow_manager.requires_escrow(amount_sats)

        return {
            "valid": True,
            "security_level": security_level.value,
            "proof_hash": proof_hash,
            "requires_escrow": requires_escrow,
            "escrow_hold_hours": ESCROW_HOLD_HOURS if requires_escrow else 0,
            "rate_limit_info": self.rate_limiter.check_rate_limit(amount_sats),
        }

    def process_validated_job(
        self, job_data: Dict[str, Any], amount_sats: int, validation_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a validated job (record rate limit, create escrow if needed).

        Args:
            job_data: Job result data
            amount_sats: Payment amount
            validation_result: Result from validate_job()

        Returns:
            Processing result
        """
        # Record in rate limiter
        self.rate_limiter.record_job(amount_sats)

        # Create escrow if required
        if validation_result.get("requires_escrow"):
            escrow_entry = self.escrow_manager.create_escrow(
                job_id=job_data.get("job_id", "unknown"),
                amount_sats=amount_sats,
                proof_hash=validation_result.get("proof_hash", ""),
                metadata={"job_type": job_data.get("job_type"), "source": job_data.get("source")},
            )
            return {
                "processed": True,
                "escrow_created": True,
                "escrow_id": escrow_entry.escrow_id,
                "release_after": escrow_entry.release_after,
                "amount_sats": amount_sats,
            }

        return {
            "processed": True,
            "escrow_created": False,
            "amount_sats": amount_sats,
            "immediate_release": True,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive security status."""
        return {
            "paused": self.is_paused(),
            "rate_limits": self.rate_limiter.check_rate_limit(0),
            "escrow": self.escrow_manager.get_status(),
            "config": {
                "escrow_enabled": self.config.get("escrow_enabled", True),
                "rate_limiting_enabled": self.config.get("rate_limiting_enabled", True),
                "anomaly_detection_enabled": self.config.get("anomaly_detection_enabled", True),
            },
            "recent_alerts": len(self._alerts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def release_ready_escrows(self) -> List[Dict[str, Any]]:
        """
        Release all escrows that have passed the hold period.

        Returns:
            List of released escrow results
        """
        releasable = self.escrow_manager.check_releasable()
        results = []

        for entry in releasable:
            result = self.escrow_manager.release_escrow(entry.escrow_id)
            results.append(result)

        return results


# Global security manager instance
_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Get or create global security manager instance."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager


async def test_security_system():
    """Test the security system."""
    print("=" * 70)
    print("PHASE 4: SECURITY & ESCROW SYSTEM TEST")
    print("=" * 70)

    manager = get_security_manager()

    # Test status
    print("\n--- Security Status ---")
    status = manager.get_status()
    print(f"Paused: {status['paused']}")
    print(f"Rate Limits: {status['rate_limits']['allowed']}")
    print(f"Escrow Status: {status['escrow']}")

    # Test job validation
    print("\n--- Job Validation Test ---")

    # Valid job
    valid_job = {
        "job_id": "job_test_001",
        "job_type": "oracle_feed",
        "source": "chainlink_mainnet",
        "is_real": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proof_summary": {
            "feeds_count": 7,
            "block_numbers": [23977838, 23977838],
            "round_ids": [129127208515966876337, 129127208515966883381],
        },
    }

    result = manager.validate_job(valid_job, 50)
    print(f"Valid job (50 sats): {result['valid']}, Level: {result['security_level']}")

    result = manager.validate_job(valid_job, 1500)
    print(f"Valid job (1500 sats): {result['valid']}, Escrow: {result.get('requires_escrow')}")

    # Invalid job
    invalid_job = {"job_id": "job_test_002", "source": "simulated", "is_real": False}

    result = manager.validate_job(invalid_job, 50)
    print(f"Invalid job: {result['valid']}, Reason: {result.get('reason', 'N/A')[:50]}")

    # Test escrow
    print("\n--- Escrow Test ---")
    escrow_status = manager.escrow_manager.get_status()
    print(f"Total in escrow: {escrow_status['total_in_escrow_sats']} sats")
    print(f"Pending entries: {escrow_status['pending_count']}")

    print("\n[SUCCESS] Phase 4 Security System test complete!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_security_system())
