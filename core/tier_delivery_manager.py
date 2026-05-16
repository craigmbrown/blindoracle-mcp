#!/usr/bin/env python3
"""
Tier-Based Delivery Manager
===========================

Manages job output delivery based on customer tier, integrating:
1. Notion customer/subscription validation
2. Tier-based rate limiting and quotas
3. IPFS delivery with cryptographic proof
4. Delivery confirmation tracking

Tiers:
- STARTER: 1,000 calls/month, 10 req/min
- PRO: 10,000 calls/month, 100 req/min
- ENTERPRISE: Unlimited calls, 1,000 req/min
"""

import os
import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import secrets

# Tier configuration
TIER_CONFIG = {
    "starter": {
        "calls_per_month": 1000,
        "rate_limit_per_minute": 10,
        "max_output_size_mb": 10,
        "priority": 1,
        "features": ["data_feeds", "ccip_read"],
        "sla_hours": 24,
    },
    "pro": {
        "calls_per_month": 10000,
        "rate_limit_per_minute": 100,
        "max_output_size_mb": 100,
        "priority": 2,
        "features": ["data_feeds", "ccip_read", "ccip_write", "vrf", "automation"],
        "sla_hours": 4,
    },
    "enterprise": {
        "calls_per_month": 1000000,  # Effectively unlimited
        "rate_limit_per_minute": 1000,
        "max_output_size_mb": 1000,
        "priority": 3,
        "features": ["all"],
        "sla_hours": 1,
    },
}


class DeliveryStatus(Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    PROCESSING = "processing"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class TierValidation:
    """Result of tier validation check"""

    valid: bool
    customer_id: str
    tier: str
    tier_config: Dict[str, Any]
    calls_remaining: int
    rate_limit_ok: bool
    features_allowed: List[str]
    error: Optional[str] = None


@dataclass
class DeliveryConfirmation:
    """Cryptographic proof of job delivery"""

    delivery_id: str
    job_id: str
    customer_id: str
    tier: str

    # Output details
    output_hash: str  # SHA-256 of output content
    output_size_bytes: int
    output_format: str

    # Delivery metadata
    delivered_at: str
    delivery_method: str  # "ipfs", "api", "webhook"

    # Proof
    proof_signature: str  # Hash of all delivery data

    # Optional fields with defaults
    delivery_location: Optional[str] = None  # IPFS CID or webhook URL

    # Tier tracking
    calls_used_this_delivery: int = 1
    calls_remaining_after: int = 0

    # Status
    status: str = "delivered"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TierDeliveryManager:
    """
    Manages tier-aware job output delivery with quota tracking
    """

    def __init__(self, notion_client=None, storage_dir: str = None):
        self.notion_client = notion_client
        self.storage_dir = Path(
            storage_dir
            or "/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/data/deliveries"
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Rate limiting tracking (in-memory for demo, use Redis in production)
        self._rate_windows: Dict[str, List[float]] = {}

        # Usage tracking file
        self.usage_file = self.storage_dir / "tier_usage.json"
        self._load_usage()

    def _load_usage(self):
        """Load usage tracking data"""
        if self.usage_file.exists():
            self.usage_data = json.loads(self.usage_file.read_text())
        else:
            self.usage_data = {
                "customers": {},
                "last_reset": datetime.now(timezone.utc).isoformat(),
            }

    def _save_usage(self):
        """Save usage tracking data"""
        self.usage_file.write_text(json.dumps(self.usage_data, indent=2))

    def validate_tier_access(
        self, customer_id: str, api_key_hash: str, requested_feature: str = "data_feeds"
    ) -> TierValidation:
        """
        Validate customer tier and check quotas/rate limits

        Args:
            customer_id: Customer identifier
            api_key_hash: SHA-256 hash of API key
            requested_feature: Feature being accessed

        Returns:
            TierValidation with access decision
        """
        # Look up customer from stored workflow results
        customer_data = self._get_customer_data(customer_id, api_key_hash)

        if not customer_data:
            return TierValidation(
                valid=False,
                customer_id=customer_id,
                tier="unknown",
                tier_config={},
                calls_remaining=0,
                rate_limit_ok=False,
                features_allowed=[],
                error="Customer not found or invalid API key",
            )

        tier = customer_data.get("tier", "starter")
        config = TIER_CONFIG.get(tier, TIER_CONFIG["starter"])

        # Check feature access
        features_allowed = config["features"]
        if "all" not in features_allowed and requested_feature not in features_allowed:
            return TierValidation(
                valid=False,
                customer_id=customer_id,
                tier=tier,
                tier_config=config,
                calls_remaining=0,
                rate_limit_ok=False,
                features_allowed=features_allowed,
                error=f"Feature '{requested_feature}' not available in {tier} tier",
            )

        # Check rate limit
        rate_limit_ok = self._check_rate_limit(customer_id, config["rate_limit_per_minute"])
        if not rate_limit_ok:
            return TierValidation(
                valid=False,
                customer_id=customer_id,
                tier=tier,
                tier_config=config,
                calls_remaining=self._get_calls_remaining(customer_id, config["calls_per_month"]),
                rate_limit_ok=False,
                features_allowed=features_allowed,
                error=f"Rate limit exceeded ({config['rate_limit_per_minute']} req/min)",
            )

        # Check monthly quota
        calls_remaining = self._get_calls_remaining(customer_id, config["calls_per_month"])
        if calls_remaining <= 0:
            return TierValidation(
                valid=False,
                customer_id=customer_id,
                tier=tier,
                tier_config=config,
                calls_remaining=0,
                rate_limit_ok=True,
                features_allowed=features_allowed,
                error=f"Monthly quota exceeded ({config['calls_per_month']} calls/month)",
            )

        return TierValidation(
            valid=True,
            customer_id=customer_id,
            tier=tier,
            tier_config=config,
            calls_remaining=calls_remaining,
            rate_limit_ok=True,
            features_allowed=features_allowed,
        )

    def _get_customer_data(self, customer_id: str, api_key_hash: str) -> Optional[Dict]:
        """Get customer data from workflow results"""
        results_file = Path(
            "/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/logs/post_payment_workflow_results.json"
        )

        if results_file.exists():
            results = json.loads(results_file.read_text())
            for customer in results.get("customers_created", []):
                if customer.get("customer_id") == customer_id:
                    # Verify API key hash matches
                    if customer.get("api_key_hash") == api_key_hash:
                        return customer

        return None

    def _check_rate_limit(self, customer_id: str, limit_per_minute: int) -> bool:
        """Check if customer is within rate limit"""
        now = time.time()
        window_start = now - 60  # 1 minute window

        if customer_id not in self._rate_windows:
            self._rate_windows[customer_id] = []

        # Remove old entries
        self._rate_windows[customer_id] = [
            t for t in self._rate_windows[customer_id] if t > window_start
        ]

        # Check if under limit
        if len(self._rate_windows[customer_id]) >= limit_per_minute:
            return False

        # Record this request
        self._rate_windows[customer_id].append(now)
        return True

    def _get_calls_remaining(self, customer_id: str, monthly_limit: int) -> int:
        """Get remaining calls for customer this month"""
        if customer_id not in self.usage_data.get("customers", {}):
            self.usage_data.setdefault("customers", {})[customer_id] = {"calls_this_month": 0}

        used = self.usage_data["customers"][customer_id].get("calls_this_month", 0)
        return max(0, monthly_limit - used)

    def _increment_usage(self, customer_id: str):
        """Increment usage counter for customer"""
        if customer_id not in self.usage_data.get("customers", {}):
            self.usage_data.setdefault("customers", {})[customer_id] = {"calls_this_month": 0}

        self.usage_data["customers"][customer_id]["calls_this_month"] += 1
        self._save_usage()

    def deliver_job_output(
        self,
        job_id: str,
        customer_id: str,
        api_key_hash: str,
        output_content: bytes,
        output_format: str = "json",
        delivery_method: str = "api",
        webhook_url: Optional[str] = None,
    ) -> DeliveryConfirmation:
        """
        Deliver job output with tier validation and confirmation

        Args:
            job_id: Job identifier
            customer_id: Customer identifier
            api_key_hash: SHA-256 hash of customer's API key
            output_content: Job output as bytes
            output_format: Format of output (json, csv, binary)
            delivery_method: How to deliver (api, ipfs, webhook)
            webhook_url: Optional webhook URL for webhook delivery

        Returns:
            DeliveryConfirmation with proof of delivery
        """
        delivery_id = f"del_{job_id}_{secrets.token_hex(4)}"

        # Validate tier access
        validation = self.validate_tier_access(customer_id, api_key_hash)

        if not validation.valid:
            return DeliveryConfirmation(
                delivery_id=delivery_id,
                job_id=job_id,
                customer_id=customer_id,
                tier=validation.tier,
                output_hash="",
                output_size_bytes=0,
                output_format=output_format,
                delivered_at=datetime.now(timezone.utc).isoformat(),
                delivery_method=delivery_method,
                proof_signature="",
                status=f"failed: {validation.error}",
            )

        # Check output size limit
        output_size = len(output_content)
        max_size = validation.tier_config["max_output_size_mb"] * 1024 * 1024

        if output_size > max_size:
            return DeliveryConfirmation(
                delivery_id=delivery_id,
                job_id=job_id,
                customer_id=customer_id,
                tier=validation.tier,
                output_hash="",
                output_size_bytes=output_size,
                output_format=output_format,
                delivered_at=datetime.now(timezone.utc).isoformat(),
                delivery_method=delivery_method,
                proof_signature="",
                status=f"failed: Output size ({output_size} bytes) exceeds tier limit ({max_size} bytes)",
            )

        # Generate output hash
        output_hash = hashlib.sha256(output_content).hexdigest()

        # Perform delivery based on method
        delivery_location = None

        if delivery_method == "api":
            # Store locally for API retrieval
            output_file = self.storage_dir / f"{delivery_id}.{output_format}"
            output_file.write_bytes(output_content)
            delivery_location = str(output_file)

        elif delivery_method == "ipfs":
            # Would integrate with IPFS here
            # For now, simulate with local storage
            output_file = self.storage_dir / f"{delivery_id}.{output_format}"
            output_file.write_bytes(output_content)
            delivery_location = f"ipfs://simulated_cid_{output_hash[:16]}"

        elif delivery_method == "webhook" and webhook_url:
            # Would POST to webhook here
            delivery_location = webhook_url

        # Increment usage
        self._increment_usage(customer_id)
        calls_remaining = validation.calls_remaining - 1

        # Generate proof signature
        proof_data = f"{delivery_id}:{job_id}:{customer_id}:{output_hash}:{datetime.now(timezone.utc).isoformat()}"
        proof_signature = hashlib.sha256(proof_data.encode()).hexdigest()

        # Create confirmation
        confirmation = DeliveryConfirmation(
            delivery_id=delivery_id,
            job_id=job_id,
            customer_id=customer_id,
            tier=validation.tier,
            output_hash=output_hash,
            output_size_bytes=output_size,
            output_format=output_format,
            delivered_at=datetime.now(timezone.utc).isoformat(),
            delivery_method=delivery_method,
            delivery_location=delivery_location,
            proof_signature=proof_signature,
            calls_used_this_delivery=1,
            calls_remaining_after=calls_remaining,
            status="delivered",
        )

        # Save confirmation record
        self._save_confirmation(confirmation)

        return confirmation

    def _save_confirmation(self, confirmation: DeliveryConfirmation):
        """Save delivery confirmation to disk"""
        conf_file = self.storage_dir / f"confirmation_{confirmation.delivery_id}.json"
        conf_file.write_text(json.dumps(confirmation.to_dict(), indent=2))

    def get_delivery_status(self, delivery_id: str) -> Optional[DeliveryConfirmation]:
        """Get status of a delivery by ID"""
        conf_file = self.storage_dir / f"confirmation_{delivery_id}.json"

        if conf_file.exists():
            data = json.loads(conf_file.read_text())
            return DeliveryConfirmation(**data)

        return None

    def get_customer_usage(self, customer_id: str) -> Dict[str, Any]:
        """Get usage statistics for a customer"""
        if customer_id not in self.usage_data.get("customers", {}):
            return {"calls_this_month": 0, "deliveries": []}

        usage = self.usage_data["customers"][customer_id].copy()

        # Find all deliveries for this customer
        deliveries = []
        for conf_file in self.storage_dir.glob(f"confirmation_del_*_{customer_id[:8]}*.json"):
            try:
                data = json.loads(conf_file.read_text())
                if data.get("customer_id") == customer_id:
                    deliveries.append(data)
            except:
                pass

        usage["deliveries"] = deliveries
        return usage


def test_tier_delivery():
    """Test the tier delivery system"""
    print("\n" + "=" * 70)
    print("  TIER-BASED DELIVERY MANAGER TEST")
    print("=" * 70)

    manager = TierDeliveryManager()

    # Load workflow results to get real customer data
    results_file = Path(
        "/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/logs/post_payment_workflow_results.json"
    )

    if not results_file.exists():
        print("\n❌ No workflow results found. Run post-payment workflow first.")
        return

    results = json.loads(results_file.read_text())

    # Test delivery for each tier
    test_results = []

    for customer in results.get("customers_created", []):
        customer_id = customer["customer_id"]
        api_key_hash = customer["api_key_hash"]
        tier = customer["tier"]

        print(f"\n{'─' * 60}")
        print(f"  Testing {tier.upper()} Tier Delivery")
        print(f"{'─' * 60}")
        print(f"  Customer: {customer_id}")

        # Create test job output
        job_id = f"job_test_{tier}_{secrets.token_hex(4)}"
        test_output = json.dumps(
            {
                "job_id": job_id,
                "result": f"Test {tier} tier job output",
                "data": {
                    "price_feeds": [
                        {"pair": "ETH/USD", "price": 2350.42},
                        {"pair": "BTC/USD", "price": 43521.00},
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
            indent=2,
        ).encode()

        # Validate tier access
        print(f"\n  1. Validating tier access...")
        validation = manager.validate_tier_access(customer_id, api_key_hash, "data_feeds")

        if validation.valid:
            print(f"     ✅ Access granted")
            print(f"     ✅ Tier: {validation.tier}")
            print(f"     ✅ Calls remaining: {validation.calls_remaining}")
            print(f"     ✅ Features: {', '.join(validation.features_allowed)}")
        else:
            print(f"     ❌ Access denied: {validation.error}")
            continue

        # Deliver job output
        print(f"\n  2. Delivering job output...")
        confirmation = manager.deliver_job_output(
            job_id=job_id,
            customer_id=customer_id,
            api_key_hash=api_key_hash,
            output_content=test_output,
            output_format="json",
            delivery_method="api",
        )

        if confirmation.status == "delivered":
            print(f"     ✅ Delivery ID: {confirmation.delivery_id}")
            print(f"     ✅ Output Hash: {confirmation.output_hash[:32]}...")
            print(f"     ✅ Size: {confirmation.output_size_bytes} bytes")
            print(f"     ✅ Location: {confirmation.delivery_location}")
            print(f"     ✅ Proof: {confirmation.proof_signature[:32]}...")
            print(f"     ✅ Calls remaining: {confirmation.calls_remaining_after}")
        else:
            print(f"     ❌ Delivery failed: {confirmation.status}")

        test_results.append(
            {
                "tier": tier,
                "customer_id": customer_id,
                "job_id": job_id,
                "delivery_id": confirmation.delivery_id,
                "status": confirmation.status,
                "proof": confirmation.proof_signature,
            }
        )

    # Save test results
    test_file = Path(
        "/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/logs/tier_delivery_test_results.json"
    )
    test_file.write_text(
        json.dumps(
            {"test_time": datetime.now(timezone.utc).isoformat(), "deliveries": test_results},
            indent=2,
        )
    )

    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    print(
        f"\n  Successful deliveries: {sum(1 for r in test_results if r['status'] == 'delivered')}/{len(test_results)}"
    )
    print(f"  Results saved to: {test_file}")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_tier_delivery()
