#!/usr/bin/env python3
"""
Job Marketplace Integration for Chainlink AI Monetization System
@requirement: REQ-JOB-001 - Job marketplace integration
@requirement: REQ-JOB-002 - Automated job acceptance based on criteria
@requirement: REQ-JOB-003 - Payment escrow verification
@requirement: REQ-MCP-003 - All exceptions print full details
@requirement: REQ-MCP-004 - Success responses logged before return
"""

import os
import json
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from queue import PriorityQueue
from pathlib import Path
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.whatsapp_notifier import WhatsAppNotifier
from core.base_level_properties import PropertyTracker


@dataclass
class Job:
    """
    Job data structure with priority and requirements
    @requirement: REQ-JOB-001 - Job structure [@core/job_marketplace.py:30-60]
    """

    id: str
    type: str  # oracle_feed, prediction_analysis, market_arbitrage
    payment: float
    requirements: Dict[str, Any]
    deadline: Optional[datetime] = None
    priority: int = 5  # 1-10, higher is more urgent
    status: str = "pending"
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    payment_verified: bool = False
    escrow_address: Optional[str] = None
    client_address: Optional[str] = None

    def __lt__(self, other):
        """For priority queue comparison"""
        return self.priority > other.priority

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payment": self.payment,
            "requirements": self.requirements,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "priority": self.priority,
            "status": self.status,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "payment_verified": self.payment_verified,
        }


class JobMarketplace:
    """
    Job marketplace for accepting and managing prediction market jobs
    @requirement: REQ-JOB-001 - Marketplace integration [@core/job_marketplace.py:65-500]
    @requirement: REQ-JOB-002 - Automated acceptance [@core/job_marketplace.py:150-200]
    @requirement: REQ-JOB-003 - Payment verification [@core/job_marketplace.py:205-250]
    """

    def __init__(self, notifier: Optional[WhatsAppNotifier] = None):
        """Initialize job marketplace"""
        self.notifier = notifier or WhatsAppNotifier()
        self.property_tracker = PropertyTracker()

        # Job management
        self.job_queue = PriorityQueue()
        self.active_jobs: Dict[str, Job] = {}
        self.completed_jobs: List[Job] = []

        # Job acceptance criteria
        self.min_payment = float(os.getenv("MIN_JOB_PAYMENT", "10.0"))
        self.max_concurrent_jobs = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))

        # Supported job types and their base costs
        self.job_types = {
            "oracle_feed": {"base_cost": 5.0, "time_estimate": 60},
            "prediction_analysis": {"base_cost": 15.0, "time_estimate": 300},
            "market_arbitrage": {"base_cost": 10.0, "time_estimate": 120},
            "comprehensive_report": {"base_cost": 25.0, "time_estimate": 600},
        }

        # Statistics
        self.stats = {
            "jobs_accepted": 0,
            "jobs_completed": 0,
            "jobs_rejected": 0,
            "total_revenue": 0.0,
        }

        # Real system integrations (will be injected)
        self.payment_system = None
        self.delivery_system = None
        self.cost_monitor = None

        # Storage for persistence
        self.storage_path = Path("/home/craigmbrown/Project/logs/job_marketplace.json")
        self.load_state()

        print(f"✅ JobMarketplace initialized (min payment: ${self.min_payment})")

    def set_payment_system(self, payment_system):
        """Inject payment system for real payment verification"""
        self.payment_system = payment_system
        print("✅ Payment system integrated with job marketplace")

    def set_delivery_system(self, delivery_system):
        """Inject delivery system for IPFS content delivery"""
        self.delivery_system = delivery_system
        print("✅ Delivery system integrated with job marketplace")

    def set_cost_monitor(self, cost_monitor):
        """Inject cost monitor for tracking expenses"""
        self.cost_monitor = cost_monitor
        print("✅ Cost monitor integrated with job marketplace")

    async def scan_for_jobs(self) -> None:
        """
        Continuously scan for new jobs from various sources
        @requirement: REQ-JOB-001 - Job discovery [@core/job_marketplace.py:110-145]
        """
        print("🔍 Starting job marketplace scanner")

        while True:
            try:
                # Check multiple job sources
                jobs = []

                # 1. Check Chainlink oracle network for data requests
                oracle_jobs = await self._check_chainlink_oracle_jobs()
                jobs.extend(oracle_jobs)

                # 2. Check prediction market platforms
                market_jobs = await self._check_prediction_market_jobs()
                jobs.extend(market_jobs)

                # 3. Check direct API requests (simulated for now)
                api_jobs = await self._check_api_job_requests()
                jobs.extend(api_jobs)

                # Process discovered jobs
                for job in jobs:
                    if await self.evaluate_job(job):
                        await self.accept_job(job)
                    else:
                        self.stats["jobs_rejected"] += 1
                        print(f"❌ Job {job.id} rejected - doesn't meet criteria")

                # Save state periodically
                self.save_state()

                # REQ-MCP-004: Log success before continuing
                active_count = len(self.active_jobs)
                print(f"✅ Job scan complete - {len(jobs)} found, {active_count} active")

            except Exception as e:
                # REQ-MCP-003: Print full exception details
                print(f"❌ Job scan error: {str(e)}")
                print(f"   Exception type: {type(e).__name__}")
                print(f"   Full traceback: {traceback.format_exc()}")
                await self.notifier.notify_error("job_scanner", str(e))

            # Wait before next scan
            await asyncio.sleep(30)

    async def evaluate_job(self, job: Job) -> bool:
        """
        Evaluate if job meets acceptance criteria
        @requirement: REQ-JOB-002 - Criteria evaluation [@core/job_marketplace.py:150-200]
        """
        try:
            # Check payment amount
            if job.payment < self.min_payment:
                print(f"⚠️ Job {job.id} payment too low: ${job.payment} < ${self.min_payment}")
                return False

            # Check if we have capacity
            if len(self.active_jobs) >= self.max_concurrent_jobs:
                print(f"⚠️ At capacity: {len(self.active_jobs)}/{self.max_concurrent_jobs} jobs")
                return False

            # Check job type is supported
            if job.type not in self.job_types:
                print(f"⚠️ Unsupported job type: {job.type}")
                return False

            # Check profitability (payment vs estimated cost)
            estimated_cost = self.job_types[job.type]["base_cost"]
            profit_margin = (job.payment - estimated_cost) / job.payment

            if profit_margin < 0.3:  # Require at least 30% profit margin
                print(f"⚠️ Job {job.id} profit margin too low: {profit_margin:.1%}")
                return False

            # Check deadline is achievable
            if job.deadline:
                time_available = (job.deadline - datetime.now()).total_seconds()
                time_required = self.job_types[job.type]["time_estimate"]

                if time_available < time_required * 1.5:  # Need 50% buffer
                    print(
                        f"⚠️ Job {job.id} deadline too tight: {time_available}s < {time_required * 1.5}s"
                    )
                    return False

            # REQ-MCP-004: Log success evaluation
            print(f"✅ Job {job.id} meets all criteria (margin: {profit_margin:.1%})")
            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Job evaluation error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    async def accept_job(self, job: Job) -> bool:
        """
        Accept job and add to processing queue
        @requirement: REQ-JOB-002 - Job acceptance [@core/job_marketplace.py:205-250]
        @requirement: REQ-JOB-003 - Payment verification
        """
        try:
            # Verify payment is in escrow
            if not await self.verify_payment_escrow(job):
                print(f"❌ Job {job.id} payment not verified")
                return False

            # Mark job as accepted
            job.status = "accepted"
            job.accepted_at = datetime.now()
            job.payment_verified = True

            # Add to queue and active jobs
            self.job_queue.put(job)
            self.active_jobs[job.id] = job

            # Update statistics
            self.stats["jobs_accepted"] += 1

            # Notify acceptance
            await self.notifier.notify_job_accepted(
                job_id=job.id, payment=job.payment, requirements=job.requirements
            )

            # Update BLP metrics - improved alignment with market
            self.property_tracker.update_property("alignment", 0.05)

            # REQ-MCP-004: Log success before return
            print(f"✅ Job {job.id} accepted - payment ${job.payment} verified")
            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Job acceptance error: {str(e)}")
            print(f"   Exception type: {type(e).__name__}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    async def verify_payment_escrow(self, job: Job) -> bool:
        """
        Verify payment is in escrow using real payment system
        @requirement: REQ-JOB-003 - Payment verification [@core/job_marketplace.py:255-290]
        """
        try:
            # Use real payment system if available
            if hasattr(self, "payment_system") and self.payment_system:
                # Real payment verification
                is_verified = await self.payment_system.verify_escrow(
                    job_id=job.id, expected_amount=job.payment
                )

                if is_verified:
                    job.payment_verified = True
                    # Get escrow address from payment system
                    if hasattr(self.payment_system, "get_escrow_address"):
                        job.escrow_address = await self.payment_system.get_escrow_address(job.id)
                    else:
                        job.escrow_address = "0x" + "0" * 40  # Placeholder

                    print(f"✅ Payment verified for job {job.id}: ${job.payment} in escrow")
                    return True
                else:
                    print(f"❌ No payment found for job {job.id}")
                    return False
            else:
                # No payment system configured - cannot verify real payments
                # NOTE: Production requires a payment system integration
                # Options: Chainlink CCIP, Fedimint, Lightning Network, or EVM escrow contract
                print(f"⚠️ [NO PAYMENT SYSTEM] Cannot verify payment for job {job.id}")
                print(f"   PRODUCTION: Configure payment_system via set_payment_system()")
                print(
                    f"   Supported: ChainlinkPaymentSystem, FedimintPaymentSystem, LightningPaymentSystem"
                )

                # Return False - no verified payment without real system
                # For testing, jobs must be submitted with pre-verified payments
                if os.getenv("ALLOW_UNVERIFIED_JOBS", "").lower() == "true":
                    print(
                        f"   ⚠️ ALLOW_UNVERIFIED_JOBS=true - accepting without verification (testing only)"
                    )
                    job.payment_verified = False
                    job.escrow_address = None
                    return True

                return False

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Payment verification error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    async def get_next_job(self) -> Optional[Job]:
        """
        Get highest priority job from queue
        @requirement: REQ-JOB-002 - Priority processing
        """
        try:
            if not self.job_queue.empty():
                job = self.job_queue.get()
                job.status = "processing"

                # REQ-MCP-004: Log job retrieval
                print(f"✅ Retrieved job {job.id} for processing (priority: {job.priority})")
                return job

            return None

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Error getting next job: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return None

    async def complete_job(self, job_id: str, output: Dict[str, Any]) -> bool:
        """
        Mark job as completed
        @requirement: REQ-DEL-001 - Job completion tracking
        """
        try:
            if job_id not in self.active_jobs:
                print(f"⚠️ Job {job_id} not found in active jobs")
                return False

            job = self.active_jobs[job_id]
            job.status = "completed"
            job.completed_at = datetime.now()

            # Move to completed list
            self.completed_jobs.append(job)
            del self.active_jobs[job_id]

            # Update statistics
            self.stats["jobs_completed"] += 1
            self.stats["total_revenue"] += job.payment

            # Calculate execution time
            execution_time = (job.completed_at - job.accepted_at).total_seconds()

            # Notify completion
            await self.notifier.notify_job_completed(
                job_id=job_id,
                execution_time=execution_time,
                output_hash=output.get("ipfs_hash", "N/A"),
            )

            # Update BLP metrics
            self.property_tracker.update_property("self_improvement", 0.02)

            # REQ-MCP-004: Log success
            print(f"✅ Job {job_id} completed in {execution_time:.1f}s")
            return True

        except Exception as e:
            # REQ-MCP-003: Print full exception details
            print(f"❌ Job completion error: {str(e)}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return False

    # Private helper methods

    async def _check_chainlink_oracle_jobs(self) -> List[Job]:
        """
        Check Chainlink network for oracle data requests

        PRODUCTION: This method should query:
        1. Chainlink Automation Registry for upkeeps needing execution
        2. Chainlink Any API for pending data requests
        3. Custom Chainlink nodes for operator-specific jobs

        For now, returns empty - jobs should be submitted via API endpoint
        """
        jobs = []

        # Check if Chainlink integration is configured
        chainlink_api = os.getenv("CHAINLINK_OPERATOR_API")
        if chainlink_api:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    # Query Chainlink operator API for pending jobs
                    async with session.get(f"{chainlink_api}/pending-jobs", timeout=10) as response:
                        if response.status == 200:
                            pending = await response.json()
                            for job_data in pending.get("jobs", []):
                                job = Job(
                                    id=job_data.get("id"),
                                    type="oracle_feed",
                                    payment=float(job_data.get("payment", 0)),
                                    requirements=job_data.get("requirements", {}),
                                    deadline=(
                                        datetime.fromisoformat(job_data["deadline"])
                                        if job_data.get("deadline")
                                        else None
                                    ),
                                    priority=job_data.get("priority", 5),
                                )
                                jobs.append(job)
                            if jobs:
                                print(f"🔍 [LIVE] Found {len(jobs)} Chainlink oracle jobs")
            except Exception as e:
                print(f"⚠️ Chainlink API query failed: {e}")

        # NOTE: No simulated jobs - production requires real Chainlink integration
        # Set CHAINLINK_OPERATOR_API environment variable to enable

        return jobs

    async def _check_prediction_market_jobs(self) -> List[Job]:
        """
        Check prediction markets for analysis job requests

        PRODUCTION: This method should query:
        1. Internal job queue API for submitted requests
        2. Partner platform APIs for analysis needs
        3. Market monitoring alerts for arbitrage opportunities

        Jobs should be submitted via the submit_job() method or API endpoint
        """
        jobs = []

        # Check internal job submission queue
        job_queue_file = Path("/home/craigmbrown/Project/logs/pending_jobs.json")
        if job_queue_file.exists():
            try:
                with open(job_queue_file, "r") as f:
                    pending = json.load(f)

                for job_data in pending.get("jobs", []):
                    if job_data.get("status") == "pending":
                        job = Job(
                            id=job_data.get("id"),
                            type=job_data.get("type", "prediction_analysis"),
                            payment=float(job_data.get("payment", 0)),
                            requirements=job_data.get("requirements", {}),
                            deadline=(
                                datetime.fromisoformat(job_data["deadline"])
                                if job_data.get("deadline")
                                else None
                            ),
                            priority=job_data.get("priority", 5),
                            client_address=job_data.get("client_address"),
                        )
                        jobs.append(job)

                if jobs:
                    print(f"🔍 [QUEUE] Found {len(jobs)} pending prediction market jobs")

            except Exception as e:
                print(f"⚠️ Job queue read error: {e}")

        # NOTE: No simulated jobs - production requires real job submissions
        return jobs

    async def _check_api_job_requests(self) -> List[Job]:
        """
        Check for direct API job requests

        PRODUCTION: Implement REST API endpoint at /api/v1/jobs
        POST /api/v1/jobs - Submit new job
        GET /api/v1/jobs - List active jobs

        For now, checks a webhook queue file for submitted jobs
        """
        jobs = []

        # Check webhook queue file (jobs submitted via external API)
        webhook_queue = Path("/home/craigmbrown/Project/logs/api_jobs_queue.json")
        if webhook_queue.exists():
            try:
                with open(webhook_queue, "r") as f:
                    queue_data = json.load(f)

                for job_data in queue_data.get("jobs", []):
                    if job_data.get("status") == "pending":
                        job = Job(
                            id=job_data.get("id"),
                            type=job_data.get("type", "comprehensive_report"),
                            payment=float(job_data.get("payment", 0)),
                            requirements=job_data.get("requirements", {}),
                            deadline=(
                                datetime.fromisoformat(job_data["deadline"])
                                if job_data.get("deadline")
                                else None
                            ),
                            priority=job_data.get("priority", 5),
                            client_address=job_data.get("client_address"),
                        )
                        jobs.append(job)

                if jobs:
                    print(f"🔍 [API] Found {len(jobs)} API job requests")

            except Exception as e:
                print(f"⚠️ API queue read error: {e}")

        # NOTE: No simulated jobs - production requires real API submissions
        # Implement FastAPI/Flask endpoint for production job submission
        return jobs

    async def submit_job(self, job_data: Dict[str, Any]) -> Optional[str]:
        """
        Submit a new job to the marketplace

        This is the production method for job submission.
        Returns job_id if successful, None if rejected.
        """
        try:
            job = Job(
                id=job_data.get("id", f"job_{datetime.now().timestamp():.0f}"),
                type=job_data.get("type", "prediction_analysis"),
                payment=float(job_data.get("payment", 0)),
                requirements=job_data.get("requirements", {}),
                deadline=(
                    datetime.fromisoformat(job_data["deadline"])
                    if job_data.get("deadline")
                    else None
                ),
                priority=job_data.get("priority", 5),
                client_address=job_data.get("client_address"),
            )

            if await self.evaluate_job(job):
                if await self.accept_job(job):
                    print(f"✅ Job {job.id} submitted and accepted")
                    return job.id

            print(f"❌ Job submission rejected")
            return None

        except Exception as e:
            print(f"❌ Job submission error: {e}")
            print(f"   Full traceback: {traceback.format_exc()}")
            return None

    def save_state(self) -> None:
        """Save marketplace state to disk"""
        try:
            state = {
                "stats": self.stats,
                "active_jobs": [job.to_dict() for job in self.active_jobs.values()],
                "completed_count": len(self.completed_jobs),
                "timestamp": datetime.now().isoformat(),
            }

            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w") as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            print(f"⚠️ Failed to save state: {str(e)}")

    def load_state(self) -> None:
        """Load marketplace state from disk"""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, "r") as f:
                    state = json.load(f)
                    self.stats = state.get("stats", self.stats)
                    print(f"✅ Loaded state: {self.stats['jobs_completed']} jobs completed")
        except Exception as e:
            print(f"⚠️ Failed to load state: {str(e)}")

    async def get_statistics(self) -> Dict[str, Any]:
        """Get marketplace statistics"""
        return {
            **self.stats,
            "active_jobs": len(self.active_jobs),
            "queued_jobs": self.job_queue.qsize(),
            "avg_payment": self.stats["total_revenue"] / max(1, self.stats["jobs_completed"]),
            "acceptance_rate": self.stats["jobs_accepted"]
            / max(1, self.stats["jobs_accepted"] + self.stats["jobs_rejected"]),
        }


# Test function
if __name__ == "__main__":

    async def test_marketplace():
        print("\n" + "=" * 60)
        print("Testing Job Marketplace")
        print("=" * 60)

        notifier = WhatsAppNotifier()
        marketplace = JobMarketplace(notifier)

        # Create test job
        test_job = Job(
            id="test_001",
            type="oracle_feed",
            payment=25.00,
            requirements={"data_type": "price_feed", "asset": "BTC-USD", "markets": ["Kalshi"]},
            priority=7,
        )

        # Test job evaluation
        if await marketplace.evaluate_job(test_job):
            print("✅ Test job meets criteria")

            # Test job acceptance
            if await marketplace.accept_job(test_job):
                print("✅ Test job accepted")

                # Get next job
                next_job = await marketplace.get_next_job()
                if next_job:
                    print(f"✅ Retrieved job: {next_job.id}")

                    # Complete job
                    await marketplace.complete_job(next_job.id, {"ipfs_hash": "QmTestHash123"})

        # Get statistics
        stats = await marketplace.get_statistics()
        print(f"\n📊 Statistics: {json.dumps(stats, indent=2)}")

        print("\n✅ Job Marketplace test complete")

    asyncio.run(test_marketplace())
