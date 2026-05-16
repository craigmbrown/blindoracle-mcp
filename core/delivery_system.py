#!/usr/bin/env python3
"""
Delivery System with IPFS Integration
Handles secure and verifiable delivery of completed work
@requirement: Delivery mechanism for agent output
@requirement: Proof of work completion
@requirement: Content addressing and immutability
"""

import asyncio
import hashlib
import json
import logging
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import aiohttp
from dataclasses import dataclass
from enum import Enum

# Optional IPFS client import
try:
    import ipfshttpclient

    IPFS_CLIENT_AVAILABLE = True
except ImportError:
    IPFS_CLIENT_AVAILABLE = False
    ipfshttpclient = None

logger = logging.getLogger(__name__)


class DeliveryStatus(Enum):
    """Delivery status tracking"""

    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    VERIFIED = "verified"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class DeliveryReceipt:
    """Receipt for delivered content"""

    job_id: str
    ipfs_hash: str
    content_hash: str
    timestamp: datetime
    status: DeliveryStatus
    metadata: Dict[str, Any]
    verification_proof: Optional[str] = None
    tx_hash: Optional[str] = None


class DeliverySystem:
    """
    Handles delivery of completed work through IPFS
    @requirement: Secure content delivery
    @requirement: Verifiable proof of completion
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize delivery system"""
        self.config = config

        # Production-first: default to real mode, fallback to demo only if needed
        self.demo_mode = config.get("demo_mode", False)

        # IPFS configuration - try multiple endpoints
        self.ipfs_api = config.get("ipfs_api", os.getenv("IPFS_API", "/ip4/127.0.0.1/tcp/5001"))
        self.ipfs_gateway = config.get(
            "ipfs_gateway", os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs/")
        )

        # Alternative IPFS services (for production without local node)
        self.pinata_api_key = os.getenv("PINATA_API_KEY")
        self.pinata_secret = os.getenv("PINATA_SECRET_API_KEY")
        self.web3_storage_token = os.getenv("WEB3_STORAGE_TOKEN")

        # Storage paths
        self.delivery_log = config.get("delivery_log", "logs/deliveries.json")
        self.pending_deliveries: Dict[str, DeliveryReceipt] = {}

        # Initialize IPFS client - try multiple methods
        self.ipfs_client = None
        self.ipfs_method = None

        if not self.demo_mode:
            # Method 1: Local IPFS node (requires ipfshttpclient)
            if IPFS_CLIENT_AVAILABLE:
                try:
                    self.ipfs_client = ipfshttpclient.connect(self.ipfs_api, timeout=10)
                    self.ipfs_method = "local_node"
                    logger.info(f"✅ Connected to local IPFS at {self.ipfs_api}")
                except Exception as e:
                    logger.warning(f"Local IPFS unavailable: {e}")
            else:
                logger.warning("ipfshttpclient not installed - local IPFS node unavailable")

            # If no local node, try cloud services
            if not self.ipfs_method:
                # Method 2: Pinata pinning service
                if self.pinata_api_key and self.pinata_secret:
                    self.ipfs_method = "pinata"
                    logger.info(f"✅ Using Pinata IPFS pinning service")

                # Method 3: Web3.Storage
                elif self.web3_storage_token:
                    self.ipfs_method = "web3_storage"
                    logger.info(f"✅ Using Web3.Storage IPFS service")

                # No IPFS method available
                else:
                    logger.warning("⚠️ No IPFS service available")
                    logger.warning(
                        "   Configure: IPFS_API (local), PINATA_API_KEY, or WEB3_STORAGE_TOKEN"
                    )
                    self.demo_mode = True

        # WhatsApp notifier (will be injected)
        self.whatsapp = None

        mode_info = f"mode={self.ipfs_method}" if self.ipfs_method else "demo_mode"
        logger.info(f"Delivery system initialized ({mode_info})")

    def set_whatsapp_notifier(self, notifier):
        """Inject WhatsApp notifier"""
        self.whatsapp = notifier

    async def prepare_delivery(
        self, job_id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None
    ) -> DeliveryReceipt:
        """
        Prepare content for delivery
        @requirement: Package agent output for delivery
        """
        try:
            logger.info(f"Preparing delivery for job {job_id}")

            # Create delivery package
            package = {
                "job_id": job_id,
                "timestamp": datetime.now().isoformat(),
                "content": content,
                "metadata": metadata or {},
                "system_info": {
                    "agent_version": self.config.get("agent_version", "1.0.0"),
                    "pipeline": "DITD+O",
                    "compute_advantage": self._calculate_compute_advantage(content),
                },
            }

            # Calculate content hash
            content_json = json.dumps(package, sort_keys=True)
            content_hash = hashlib.sha256(content_json.encode()).hexdigest()

            # Create receipt
            receipt = DeliveryReceipt(
                job_id=job_id,
                ipfs_hash="",  # Will be set after upload
                content_hash=content_hash,
                timestamp=datetime.now(),
                status=DeliveryStatus.PENDING,
                metadata=metadata or {},
            )

            # Store pending delivery
            self.pending_deliveries[job_id] = receipt

            # Store package for upload
            receipt.package = package  # Attach for upload phase

            logger.info(f"Delivery prepared: {content_hash[:16]}...")
            return receipt

        except Exception as e:
            logger.error(f"Failed to prepare delivery: {e}")
            raise

    async def upload_to_ipfs(self, receipt: DeliveryReceipt) -> str:
        """
        Upload content to IPFS using available method
        @requirement: Distributed storage for immutability
        """
        try:
            receipt.status = DeliveryStatus.UPLOADING
            logger.info(f"Uploading job {receipt.job_id} to IPFS via {self.ipfs_method or 'demo'}")

            # Get package from receipt
            package = getattr(receipt, "package", None)
            if not package:
                raise Exception("No package attached to receipt")

            content_json = json.dumps(package, sort_keys=True)

            if self.demo_mode:
                # Demo mode: generate deterministic hash based on content
                # NOTE: Production requires real IPFS - configure IPFS_API, PINATA_API_KEY, or WEB3_STORAGE_TOKEN
                content_hash = hashlib.sha256(content_json.encode()).hexdigest()[:32]
                ipfs_hash = f"Qm{content_hash}DEMO"
                logger.warning(f"[DEMO] No IPFS service configured - using local hash: {ipfs_hash}")
                logger.warning(
                    f"   PRODUCTION: Set IPFS_API, PINATA_API_KEY, or WEB3_STORAGE_TOKEN"
                )

            elif self.ipfs_method == "local_node" and self.ipfs_client:
                # Local IPFS node upload
                result = self.ipfs_client.add_json(package)
                ipfs_hash = result["Hash"]
                self.ipfs_client.pin.add(ipfs_hash)
                logger.info(f"✅ [LOCAL] Content uploaded and pinned: {ipfs_hash}")

            elif self.ipfs_method == "pinata":
                # Pinata IPFS pinning service
                ipfs_hash = await self._upload_to_pinata(content_json, receipt.job_id)
                logger.info(f"✅ [PINATA] Content pinned: {ipfs_hash}")

            elif self.ipfs_method == "web3_storage":
                # Web3.Storage upload
                ipfs_hash = await self._upload_to_web3_storage(content_json, receipt.job_id)
                logger.info(f"✅ [WEB3.STORAGE] Content uploaded: {ipfs_hash}")

            else:
                raise Exception(f"No IPFS upload method available (method={self.ipfs_method})")

            # Update receipt
            receipt.ipfs_hash = ipfs_hash
            receipt.status = DeliveryStatus.UPLOADED

            # Notify via WhatsApp
            if self.whatsapp:
                await self.whatsapp.notify_critical(
                    f"📤 Content Uploaded to IPFS\n"
                    f"Job: {receipt.job_id}\n"
                    f"IPFS: {ipfs_hash[:16]}...\n"
                    f"Gateway: {self.ipfs_gateway}{ipfs_hash}"
                )

            return ipfs_hash

        except Exception as e:
            logger.error(f"Failed to upload to IPFS: {e}")
            receipt.status = DeliveryStatus.FAILED
            raise

    async def verify_upload(self, ipfs_hash: str) -> bool:
        """
        Verify content is accessible via IPFS
        @requirement: Ensure content availability
        """
        try:
            logger.info(f"Verifying IPFS content: {ipfs_hash}")

            if self.demo_mode:
                # Demo mode: cannot verify without real IPFS
                logger.warning(f"[DEMO] Cannot verify content - no IPFS service configured")
                return False  # Explicit false in demo mode

            # Try to fetch from gateway
            async with aiohttp.ClientSession() as session:
                url = f"{self.ipfs_gateway}{ipfs_hash}"
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        logger.info(f"Content verified at: {url}")
                        return True
                    else:
                        logger.warning(f"Failed to verify content: HTTP {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    async def create_delivery_proof(self, receipt: DeliveryReceipt) -> Dict[str, Any]:
        """
        Create cryptographic proof of delivery
        @requirement: Proof of work completion
        """
        try:
            logger.info(f"Creating delivery proof for job {receipt.job_id}")

            # Create proof structure
            proof = {
                "job_id": receipt.job_id,
                "ipfs_hash": receipt.ipfs_hash,
                "content_hash": receipt.content_hash,
                "timestamp": receipt.timestamp.isoformat(),
                "metadata": receipt.metadata,
                "verification": {
                    "method": "sha256",
                    "content_hash": receipt.content_hash,
                    "ipfs_verified": await self.verify_upload(receipt.ipfs_hash),
                },
            }

            # Generate proof hash
            proof_json = json.dumps(proof, sort_keys=True)
            proof_hash = hashlib.sha256(proof_json.encode()).hexdigest()

            proof["proof_hash"] = proof_hash
            receipt.verification_proof = proof_hash

            logger.info(f"Delivery proof created: {proof_hash[:16]}...")
            return proof

        except Exception as e:
            logger.error(f"Failed to create delivery proof: {e}")
            raise

    async def deliver(
        self, job_id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Complete delivery pipeline
        @requirement: Full delivery workflow with verification
        """
        try:
            logger.info(f"Starting delivery for job {job_id}")

            # Prepare delivery
            receipt = await self.prepare_delivery(job_id, content, metadata)

            # Upload to IPFS
            ipfs_hash = await self.upload_to_ipfs(receipt)

            # Verify upload
            verified = await self.verify_upload(ipfs_hash)
            if verified:
                receipt.status = DeliveryStatus.VERIFIED
            else:
                logger.warning(f"Content verification failed for {ipfs_hash}")

            # Create delivery proof
            proof = await self.create_delivery_proof(receipt)

            # Mark as delivered
            receipt.status = DeliveryStatus.DELIVERED

            # Log delivery
            await self._log_delivery(receipt, proof)

            # Notify completion
            if self.whatsapp:
                await self.whatsapp.notify_critical(
                    f"✅ Delivery Complete\n"
                    f"Job: {job_id}\n"
                    f"IPFS: {ipfs_hash[:16]}...\n"
                    f"Proof: {proof['proof_hash'][:16]}...\n"
                    f"Status: {receipt.status.value}"
                )

            logger.info(f"Delivery complete: {ipfs_hash}")
            return ipfs_hash, proof

        except Exception as e:
            logger.error(f"Delivery failed for job {job_id}: {e}")
            if self.whatsapp:
                await self.whatsapp.notify_error(
                    f"❌ Delivery Failed\n" f"Job: {job_id}\n" f"Error: {str(e)}"
                )
            raise

    async def retrieve_content(self, ipfs_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve content from IPFS
        @requirement: Content retrieval for verification
        """
        try:
            logger.info(f"Retrieving content: {ipfs_hash}")

            if self.demo_mode:
                # Demo mode: cannot retrieve without real IPFS
                logger.warning(f"[DEMO] Cannot retrieve content - no IPFS service configured")
                logger.warning(
                    f"   PRODUCTION: Configure IPFS_API, PINATA_API_KEY, or WEB3_STORAGE_TOKEN"
                )
                return None

            if not self.ipfs_client:
                # Try gateway retrieval
                async with aiohttp.ClientSession() as session:
                    url = f"{self.ipfs_gateway}{ipfs_hash}"
                    async with session.get(url, timeout=30) as response:
                        if response.status == 200:
                            content = await response.json()
                            logger.info(f"Content retrieved from gateway")
                            return content
            else:
                # Direct IPFS retrieval
                content = self.ipfs_client.get_json(ipfs_hash)
                logger.info(f"Content retrieved from IPFS node")
                return content

        except Exception as e:
            logger.error(f"Failed to retrieve content: {e}")
            return None

    async def get_delivery_status(self, job_id: str) -> Optional[DeliveryReceipt]:
        """
        Get delivery status for a job
        @requirement: Status tracking
        """
        # Check pending deliveries
        if job_id in self.pending_deliveries:
            return self.pending_deliveries[job_id]

        # Check logged deliveries
        deliveries = await self._load_delivery_log()
        return deliveries.get(job_id)

    def _calculate_compute_advantage(self, content: Dict[str, Any]) -> float:
        """
        Calculate compute advantage for delivered content
        @requirement: Base Level Properties tracking
        """
        # Simple heuristic based on content complexity
        complexity = len(json.dumps(content))
        autonomy = 0.95  # Target 95% autonomy
        time_saved = complexity / 1000  # Rough estimate

        # Compute Advantage = (Compute × Autonomy) / (Time + Effort + Cost)
        compute_advantage = (complexity * autonomy) / (time_saved + 1 + 0.01)

        return round(compute_advantage, 2)

    async def _log_delivery(self, receipt: DeliveryReceipt, proof: Dict[str, Any]):
        """Log delivery to persistent storage"""
        try:
            # Load existing log
            deliveries = await self._load_delivery_log()

            # Add new delivery
            deliveries[receipt.job_id] = {
                "receipt": {
                    "job_id": receipt.job_id,
                    "ipfs_hash": receipt.ipfs_hash,
                    "content_hash": receipt.content_hash,
                    "timestamp": receipt.timestamp.isoformat(),
                    "status": receipt.status.value,
                    "metadata": receipt.metadata,
                    "verification_proof": receipt.verification_proof,
                },
                "proof": proof,
            }

            # Save log
            os.makedirs(os.path.dirname(self.delivery_log), exist_ok=True)
            with open(self.delivery_log, "w") as f:
                json.dump(deliveries, f, indent=2)

            logger.info(f"Delivery logged: {receipt.job_id}")

        except Exception as e:
            logger.error(f"Failed to log delivery: {e}")

    async def _load_delivery_log(self) -> Dict[str, Any]:
        """Load delivery log from storage"""
        try:
            if os.path.exists(self.delivery_log):
                with open(self.delivery_log, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load delivery log: {e}")
        return {}

    async def cleanup_pending(self, max_age_hours: int = 24):
        """Clean up old pending deliveries"""
        try:
            now = datetime.now()
            to_remove = []

            for job_id, receipt in self.pending_deliveries.items():
                age = (now - receipt.timestamp).total_seconds() / 3600
                if age > max_age_hours:
                    logger.warning(f"Removing stale delivery: {job_id} (age: {age:.1f} hours)")
                    to_remove.append(job_id)

            for job_id in to_remove:
                del self.pending_deliveries[job_id]

            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} stale deliveries")

        except Exception as e:
            logger.error(f"Failed to cleanup pending deliveries: {e}")

    async def _upload_to_pinata(self, content_json: str, job_id: str) -> str:
        """
        Upload content to Pinata IPFS pinning service
        https://docs.pinata.cloud/api-reference/endpoint/pin-json-to-ipfs
        """
        url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"

        headers = {
            "Content-Type": "application/json",
            "pinata_api_key": self.pinata_api_key,
            "pinata_secret_api_key": self.pinata_secret,
        }

        payload = {
            "pinataContent": json.loads(content_json),
            "pinataMetadata": {
                "name": f"job-{job_id}",
                "keyvalues": {"job_id": job_id, "system": "chainlink-prediction-markets"},
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["IpfsHash"]
                else:
                    error = await response.text()
                    raise Exception(f"Pinata upload failed: {response.status} - {error}")

    async def _upload_to_web3_storage(self, content_json: str, job_id: str) -> str:
        """
        Upload content to Web3.Storage
        https://web3.storage/docs/reference/http-api/
        """
        url = "https://api.web3.storage/upload"

        headers = {
            "Authorization": f"Bearer {self.web3_storage_token}",
            "Content-Type": "application/json",
            "X-Name": f"job-{job_id}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=content_json, headers=headers, timeout=60
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["cid"]
                else:
                    error = await response.text()
                    raise Exception(f"Web3.Storage upload failed: {response.status} - {error}")


async def main():
    """Test delivery system"""
    logging.basicConfig(level=logging.INFO)

    # Demo configuration
    config = {
        "demo_mode": True,
        "ipfs_api": "/ip4/127.0.0.1/tcp/5001",
        "ipfs_gateway": "https://ipfs.io/ipfs/",
        "delivery_log": "logs/deliveries.json",
    }

    # Initialize delivery system
    delivery = DeliverySystem(config)

    # Test content
    test_content = {
        "result": "Completed analysis of market trends",
        "predictions": [
            {"market": "BTC", "direction": "up", "confidence": 0.75},
            {"market": "ETH", "direction": "up", "confidence": 0.82},
        ],
        "compute_metrics": {
            "tokens_processed": 150000,
            "inference_time_ms": 2341,
            "model": "gpt-4",
        },
    }

    # Test delivery
    ipfs_hash, proof = await delivery.deliver(
        job_id="test-job-001", content=test_content, metadata={"client": "test", "priority": "high"}
    )

    print(f"Delivered to IPFS: {ipfs_hash}")
    print(f"Proof hash: {proof['proof_hash']}")

    # Test retrieval
    retrieved = await delivery.retrieve_content(ipfs_hash)
    if retrieved:
        print(f"Retrieved content: {retrieved.get('job_id')}")

    # Check status
    status = await delivery.get_delivery_status("test-job-001")
    if status:
        print(f"Delivery status: {status.status.value}")


if __name__ == "__main__":
    asyncio.run(main())
