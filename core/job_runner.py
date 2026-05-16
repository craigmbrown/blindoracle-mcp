#!/usr/bin/env python3
"""
Phase 5: Refactored Job Runner
==============================

Clean, modular job runner architecture with:
- Pluggable data fetchers (oracle, market, hybrid)
- Unified job execution pipeline
- Clean separation of concerns
- Event-driven job lifecycle
- Comprehensive job result handling

@requirement: REQ-JOB-001 - Modular data fetcher architecture
@requirement: REQ-JOB-002 - Unified execution pipeline
@requirement: REQ-JOB-003 - Event hooks for observability
@requirement: REQ-JOB-004 - Clean error handling and recovery
"""

import sys
import json
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Protocol
from dataclasses import dataclass, asdict, field
from enum import Enum
from abc import ABC, abstractmethod

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Paths
LOG_DIR = PROJECT_ROOT / "logs"
JOBS_LOG = LOG_DIR / "jobs_v2.json"


class JobStatus(Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # Security blocked
    ESCROWED = "escrowed"  # In escrow hold


class JobType(Enum):
    """Available job types."""

    # Original job types
    ORACLE_FEED = "oracle_feed"
    MARKET_ARBITRAGE = "market_arbitrage"
    PREDICTION_ANALYSIS = "prediction_analysis"
    COMPREHENSIVE_REPORT = "comprehensive_report"
    # Extended job types
    CROSS_CHAIN_PRICES = "cross_chain_prices"
    VOLATILITY_MONITOR = "volatility_monitor"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    ALERT_GENERATOR = "alert_generator"
    HISTORICAL_ANALYSIS = "historical_analysis"


@dataclass
class JobConfig:
    """Configuration for a job type."""

    job_type: JobType
    name: str
    description: str
    cost_sats: int  # Execution cost
    value_sats: int  # Value earned
    interval_minutes: int
    enabled: bool = True


@dataclass
class JobResult:
    """Result of a job execution."""

    job_id: str
    job_type: str
    status: JobStatus
    timestamp: str
    duration_ms: int
    data: Dict[str, Any]
    source: str
    is_real: bool
    reward_sats: int
    proof_summary: Optional[Dict[str, Any]] = None
    security_info: Optional[Dict[str, Any]] = None
    payment_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


class DataFetcher(ABC):
    """Abstract base class for data fetchers."""

    @abstractmethod
    async def fetch(self) -> Dict[str, Any]:
        """Fetch data from source."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Get the source identifier."""
        pass

    @abstractmethod
    def is_real_data(self) -> bool:
        """Check if this returns real data."""
        pass


class ChainlinkFetcher(DataFetcher):
    """Fetches real Chainlink oracle data."""

    def __init__(self):
        self._connector = None
        try:
            from core.chainlink_onchain import ChainlinkOnChainConnector

            self._connector = ChainlinkOnChainConnector()
        except ImportError:
            pass

    async def fetch(self) -> Dict[str, Any]:
        if not self._connector:
            return {"error": "Chainlink connector not available", "source": "simulated"}

        try:
            from core.chainlink_onchain import get_all_real_chainlink_prices

            return get_all_real_chainlink_prices()
        except Exception as e:
            return {"error": str(e), "source": "error"}

    def get_source_name(self) -> str:
        return "chainlink_mainnet"

    def is_real_data(self) -> bool:
        return self._connector is not None


class MarketDataFetcher(DataFetcher):
    """Fetches real market data from Kalshi/Polymarket."""

    def __init__(self):
        self._available = False
        try:
            from core.real_market_data import RealMarketDataFetcher

            self._fetcher = RealMarketDataFetcher()
            self._available = True
        except ImportError:
            self._fetcher = None

    async def fetch(self) -> Dict[str, Any]:
        if not self._available:
            return {"error": "Market data fetcher not available", "source": "simulated"}

        try:
            return await self._fetcher.get_market_analysis_for_job()
        except Exception as e:
            return {"error": str(e), "source": "error"}

    def get_source_name(self) -> str:
        return "real_market_apis"

    def is_real_data(self) -> bool:
        return self._available


class JobEventHandler(Protocol):
    """Protocol for job event handlers."""

    def on_job_start(self, job_id: str, job_type: str) -> None: ...
    def on_job_complete(self, result: JobResult) -> None: ...
    def on_job_error(self, job_id: str, error: str) -> None: ...


class DefaultEventHandler:
    """Default event handler with logging."""

    def on_job_start(self, job_id: str, job_type: str) -> None:
        print(f"[JOB] Starting {job_type}: {job_id}")

    def on_job_complete(self, result: JobResult) -> None:
        status = "REAL" if result.is_real else "SIM"
        print(
            f"[JOB] Complete {result.job_type}: {result.job_id} [{status}] +{result.reward_sats} sats"
        )

    def on_job_error(self, job_id: str, error: str) -> None:
        print(f"[JOB] Error {job_id}: {error}")


class JobRunner:
    """
    Refactored job runner with clean architecture.

    Features:
    - Pluggable data fetchers
    - Security integration
    - Payment processing
    - Event-driven lifecycle
    """

    # Default job configurations
    DEFAULT_CONFIGS: Dict[JobType, JobConfig] = {
        # Original job types
        JobType.ORACLE_FEED: JobConfig(
            job_type=JobType.ORACLE_FEED,
            name="Oracle Feed",
            description="Fetch Chainlink price feeds",
            cost_sats=5,
            value_sats=10,
            interval_minutes=15,
        ),
        JobType.MARKET_ARBITRAGE: JobConfig(
            job_type=JobType.MARKET_ARBITRAGE,
            name="Market Arbitrage",
            description="Analyze cross-platform arbitrage",
            cost_sats=10,
            value_sats=25,
            interval_minutes=30,
        ),
        JobType.PREDICTION_ANALYSIS: JobConfig(
            job_type=JobType.PREDICTION_ANALYSIS,
            name="Prediction Analysis",
            description="Analyze prediction markets",
            cost_sats=8,
            value_sats=20,
            interval_minutes=60,
        ),
        JobType.COMPREHENSIVE_REPORT: JobConfig(
            job_type=JobType.COMPREHENSIVE_REPORT,
            name="Comprehensive Report",
            description="Full market analysis report",
            cost_sats=15,
            value_sats=75,
            interval_minutes=240,
        ),
        # Extended job types
        JobType.CROSS_CHAIN_PRICES: JobConfig(
            job_type=JobType.CROSS_CHAIN_PRICES,
            name="Cross-Chain Prices",
            description="Multi-chain oracle feeds (Arbitrum, Base, Polygon)",
            cost_sats=12,
            value_sats=30,
            interval_minutes=20,
        ),
        JobType.VOLATILITY_MONITOR: JobConfig(
            job_type=JobType.VOLATILITY_MONITOR,
            name="Volatility Monitor",
            description="Price volatility tracking and analysis",
            cost_sats=8,
            value_sats=20,
            interval_minutes=10,
        ),
        JobType.SENTIMENT_ANALYSIS: JobConfig(
            job_type=JobType.SENTIMENT_ANALYSIS,
            name="Sentiment Analysis",
            description="Market sentiment scoring from multiple sources",
            cost_sats=15,
            value_sats=35,
            interval_minutes=30,
        ),
        JobType.ALERT_GENERATOR: JobConfig(
            job_type=JobType.ALERT_GENERATOR,
            name="Alert Generator",
            description="Price threshold monitoring and alerts",
            cost_sats=5,
            value_sats=15,
            interval_minutes=5,
        ),
        JobType.HISTORICAL_ANALYSIS: JobConfig(
            job_type=JobType.HISTORICAL_ANALYSIS,
            name="Historical Analysis",
            description="Trend analysis and technical indicators",
            cost_sats=10,
            value_sats=25,
            interval_minutes=60,
        ),
    }

    def __init__(
        self,
        event_handler: Optional[JobEventHandler] = None,
        enable_security: bool = True,
        enable_payments: bool = True,
    ):
        """
        Initialize job runner.

        Args:
            event_handler: Handler for job lifecycle events
            enable_security: Enable security validation
            enable_payments: Enable payment processing
        """
        self.event_handler = event_handler or DefaultEventHandler()
        self.enable_security = enable_security
        self.enable_payments = enable_payments

        # Initialize fetchers
        self.fetchers: Dict[JobType, DataFetcher] = {
            JobType.ORACLE_FEED: ChainlinkFetcher(),
            JobType.MARKET_ARBITRAGE: MarketDataFetcher(),
            JobType.PREDICTION_ANALYSIS: MarketDataFetcher(),
        }

        # Initialize extended fetchers
        try:
            from core.extended_fetchers import (
                CrossChainPriceFetcher,
                VolatilityMonitorFetcher,
                SentimentAnalysisFetcher,
                AlertGeneratorFetcher,
                HistoricalAnalysisFetcher,
            )

            self.fetchers[JobType.CROSS_CHAIN_PRICES] = CrossChainPriceFetcher()
            self.fetchers[JobType.VOLATILITY_MONITOR] = VolatilityMonitorFetcher()
            self.fetchers[JobType.SENTIMENT_ANALYSIS] = SentimentAnalysisFetcher()
            self.fetchers[JobType.ALERT_GENERATOR] = AlertGeneratorFetcher()
            self.fetchers[JobType.HISTORICAL_ANALYSIS] = HistoricalAnalysisFetcher()
        except ImportError as e:
            print(f"[JobRunner] Extended fetchers not available: {e}")

        # Initialize optional components
        self._security_manager = None
        self._payment_system = None

        if enable_security:
            try:
                from core.security_escrow import get_security_manager

                self._security_manager = get_security_manager()
            except ImportError:
                print("[JobRunner] Security system not available")

        if enable_payments:
            try:
                from core.production_payment import ProductionPaymentSystem

                self._payment_system = ProductionPaymentSystem()
            except ImportError:
                print("[JobRunner] Payment system not available")

        # Ensure log directory exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _generate_job_id(self) -> str:
        """Generate unique job ID."""
        return f"job_{uuid.uuid4().hex[:8]}"

    async def _fetch_data(self, job_type: JobType) -> Dict[str, Any]:
        """Fetch data for job type."""
        fetcher = self.fetchers.get(job_type)
        if fetcher:
            return await fetcher.fetch()

        # Comprehensive report combines multiple fetchers
        if job_type == JobType.COMPREHENSIVE_REPORT:
            oracle_data = await self.fetchers[JobType.ORACLE_FEED].fetch()
            market_data = await self.fetchers[JobType.MARKET_ARBITRAGE].fetch()

            return {
                "oracle_data": oracle_data,
                "market_data": market_data,
                "source": (
                    "real_hybrid"
                    if oracle_data.get("source") == "chainlink_mainnet"
                    else "simulated"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return {"error": "No fetcher available", "source": "simulated"}

    def _create_proof_summary(
        self, job_type: JobType, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Create proof summary from job data."""
        source = data.get("source", "")

        if source == "chainlink_mainnet" and "feeds" in data:
            feeds = data.get("feeds", {})
            return {
                "feeds_count": len(feeds),
                "block_numbers": [
                    f.get("block_number")
                    for f in feeds.values()
                    if isinstance(f, dict) and f.get("block_number")
                ],
                "round_ids": [
                    f.get("round_id")
                    for f in feeds.values()
                    if isinstance(f, dict) and f.get("round_id")
                ],
            }

        if source == "real_market_apis":
            summary = data.get("summary", {})
            platforms = data.get("platforms", {})
            return {
                "total_markets": summary.get("total_markets", 0),
                "kalshi_markets": platforms.get("kalshi", {}).get("market_count", 0),
                "polymarket_markets": platforms.get("polymarket", {}).get("market_count", 0),
                "total_volume_usd": summary.get("total_volume", 0),
                "api_sources": ["kalshi_api", "polymarket_gamma_api"],
            }

        if source == "real_hybrid":
            oracle = data.get("oracle_data", {})
            if oracle.get("source") == "chainlink_mainnet":
                return self._create_proof_summary(JobType.ORACLE_FEED, oracle)

        return None

    async def _validate_security(self, job_result: JobResult, config: JobConfig) -> Dict[str, Any]:
        """Validate job through security system."""
        if not self._security_manager:
            return {"valid": True, "reason": "Security disabled"}

        if self._security_manager.is_paused():
            return {"valid": False, "reason": "System paused"}

        validation = self._security_manager.validate_job(job_result.to_dict(), config.value_sats)

        if validation.get("valid"):
            # Process through security (rate limiting, escrow)
            process_result = self._security_manager.process_validated_job(
                job_result.to_dict(), config.value_sats, validation
            )
            validation["security_processed"] = process_result

        return validation

    async def _process_payment(
        self, job_result: JobResult, config: JobConfig
    ) -> Optional[Dict[str, Any]]:
        """Process payment for completed job."""
        if not self._payment_system or not job_result.is_real:
            return None

        try:
            if not self._payment_system.verify_job_completion(job_result.to_dict()):
                return {"status": "verification_failed"}

            receipt = await self._payment_system.execute_payout(
                job_id=job_result.job_id, amount_sats=config.value_sats, payment_type="treasury"
            )

            return {
                "payment_id": receipt.payment_id,
                "status": receipt.status,
                "amount_sats": receipt.amount_sats,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def execute(self, job_type: JobType) -> JobResult:
        """
        Execute a single job.

        Args:
            job_type: Type of job to execute

        Returns:
            JobResult with execution details
        """
        job_id = self._generate_job_id()
        config = self.DEFAULT_CONFIGS[job_type]
        start_time = datetime.now(timezone.utc)

        # Notify start
        self.event_handler.on_job_start(job_id, job_type.value)

        try:
            # Fetch data
            data = await self._fetch_data(job_type)

            # Calculate duration
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            # Determine if real
            source = data.get("source", "simulated")
            is_real = source in ["chainlink_mainnet", "real_market_apis", "real_hybrid"]

            # Create result
            result = JobResult(
                job_id=job_id,
                job_type=job_type.value,
                status=JobStatus.COMPLETED if is_real else JobStatus.COMPLETED,
                timestamp=start_time.isoformat(),
                duration_ms=duration_ms,
                data=data,
                source=source,
                is_real=is_real,
                reward_sats=config.value_sats if is_real else 0,
                proof_summary=self._create_proof_summary(job_type, data),
            )

            # Security validation
            if is_real and self.enable_security:
                security_result = await self._validate_security(result, config)
                result.security_info = security_result

                if not security_result.get("valid"):
                    result.status = JobStatus.BLOCKED
                    result.is_real = False
                    result.reward_sats = 0
                elif security_result.get("security_processed", {}).get("escrow_created"):
                    result.status = JobStatus.ESCROWED

            # Payment processing
            if result.is_real and self.enable_payments and result.status == JobStatus.COMPLETED:
                payment_result = await self._process_payment(result, config)
                result.payment_info = payment_result

            # Log result
            self._log_result(result)

            # Notify completion
            self.event_handler.on_job_complete(result)

            return result

        except Exception as e:
            # Handle errors
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            result = JobResult(
                job_id=job_id,
                job_type=job_type.value,
                status=JobStatus.FAILED,
                timestamp=start_time.isoformat(),
                duration_ms=duration_ms,
                data={},
                source="error",
                is_real=False,
                reward_sats=0,
                error=str(e),
            )

            self.event_handler.on_job_error(job_id, str(e))
            self._log_result(result)

            return result

    async def execute_all(self, job_types: Optional[List[JobType]] = None) -> List[JobResult]:
        """
        Execute multiple jobs concurrently.

        Args:
            job_types: List of job types to execute (default: all)

        Returns:
            List of job results
        """
        types_to_run = job_types or list(JobType)

        # Execute concurrently
        tasks = [self.execute(jt) for jt in types_to_run]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                job_type = types_to_run[i]
                error_result = JobResult(
                    job_id=self._generate_job_id(),
                    job_type=job_type.value,
                    status=JobStatus.FAILED,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    duration_ms=0,
                    data={},
                    source="error",
                    is_real=False,
                    reward_sats=0,
                    error=str(result),
                )
                processed_results.append(error_result)
            else:
                processed_results.append(result)

        return processed_results

    def _log_result(self, result: JobResult) -> None:
        """Log job result to file."""
        try:
            if JOBS_LOG.exists():
                with open(JOBS_LOG, "r") as f:
                    jobs = json.load(f)
            else:
                jobs = []

            jobs.append(result.to_dict())

            # Keep last 1000 jobs
            jobs = jobs[-1000:]

            with open(JOBS_LOG, "w") as f:
                json.dump(jobs, f, indent=2)
        except Exception as e:
            print(f"[JobRunner] Log error: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get runner status."""
        return {
            "security_enabled": self._security_manager is not None,
            "payments_enabled": self._payment_system is not None,
            "fetchers": {jt.value: f.is_real_data() for jt, f in self.fetchers.items()},
            "configs": {
                jt.value: {
                    "name": c.name,
                    "cost_sats": c.cost_sats,
                    "value_sats": c.value_sats,
                    "interval_minutes": c.interval_minutes,
                }
                for jt, c in self.DEFAULT_CONFIGS.items()
            },
        }


async def test_job_runner():
    """Test the refactored job runner."""
    print("=" * 70)
    print("PHASE 5: REFACTORED JOB RUNNER TEST")
    print("=" * 70)

    runner = JobRunner()

    # Test status
    print("\n--- Runner Status ---")
    status = runner.get_status()
    print(f"Security: {status['security_enabled']}")
    print(f"Payments: {status['payments_enabled']}")
    print(f"Fetchers: {status['fetchers']}")

    # Test single job
    print("\n--- Single Job Execution ---")
    result = await runner.execute(JobType.ORACLE_FEED)
    print(f"Job ID: {result.job_id}")
    print(f"Status: {result.status.value}")
    print(f"Source: {result.source}")
    print(f"Is Real: {result.is_real}")
    print(f"Reward: {result.reward_sats} sats")
    print(f"Duration: {result.duration_ms}ms")

    # Test all jobs
    print("\n--- All Jobs Execution ---")
    results = await runner.execute_all()
    for r in results:
        status_emoji = "✅" if r.is_real else "📋"
        print(f"{status_emoji} {r.job_type}: {r.status.value} ({r.reward_sats} sats)")

    print("\n[SUCCESS] Phase 5 Job Runner test complete!")


if __name__ == "__main__":
    asyncio.run(test_job_runner())
