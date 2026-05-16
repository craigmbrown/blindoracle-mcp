#!/usr/bin/env python3
"""
Cost Monitor Integration
Tracks API usage, compute costs, and budget management
@requirement: Real-time cost tracking
@requirement: Budget enforcement
@requirement: Cost optimization
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import aiofiles

logger = logging.getLogger(__name__)


class CostCategory(Enum):
    """Cost categories for tracking"""

    LLM_API = "llm_api"
    BLOCKCHAIN = "blockchain"
    IPFS = "ipfs"
    COMPUTE = "compute"
    STORAGE = "storage"
    NETWORK = "network"
    OTHER = "other"


@dataclass
class CostEntry:
    """Individual cost entry"""

    timestamp: datetime
    category: CostCategory
    service: str
    amount: float
    units: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BudgetLimit:
    """Budget limits and thresholds"""

    daily_limit: float
    monthly_limit: float
    per_job_limit: float
    warning_threshold: float = 0.8  # Warn at 80% of limit
    critical_threshold: float = 0.95  # Critical at 95% of limit


class CostMonitor:
    """
    Monitors and controls spending across all services
    @requirement: Track actual costs, not estimates
    @requirement: Enforce budget limits
    """

    # LLM Pricing (USD per 1M tokens)
    LLM_PRICING = {
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "gemini-pro": {"input": 0.5, "output": 1.5},
        "llama-3-70b": {"input": 0.7, "output": 0.9},
        "mistral-large": {"input": 4.0, "output": 12.0},
    }

    # Blockchain costs (USD)
    BLOCKCHAIN_COSTS = {
        "ethereum": {"gas_price": 0.002, "base_fee": 5.0},
        "polygon": {"gas_price": 0.00001, "base_fee": 0.01},
        "arbitrum": {"gas_price": 0.0001, "base_fee": 0.1},
        "base": {"gas_price": 0.00005, "base_fee": 0.05},
    }

    def __init__(self, config: Dict[str, Any]):
        """Initialize cost monitor"""
        self.config = config

        # Budget limits
        self.budget = BudgetLimit(
            daily_limit=config.get("daily_limit", 10.0),
            monthly_limit=config.get("monthly_limit", 200.0),
            per_job_limit=config.get("per_job_limit", 2.0),
            warning_threshold=config.get("warning_threshold", 0.8),
            critical_threshold=config.get("critical_threshold", 0.95),
        )

        # Cost tracking
        self.current_costs: List[CostEntry] = []
        self.cost_log_file = config.get("cost_log", "logs/costs.json")
        self.daily_totals: Dict[str, float] = {}
        self.job_costs: Dict[str, float] = {}

        # WhatsApp notifier (will be injected)
        self.whatsapp = None

        # Alert tracking
        self.last_alert_time: Dict[str, datetime] = {}
        self.alert_cooldown = timedelta(minutes=30)

        logger.info(f"Cost monitor initialized with daily limit: ${self.budget.daily_limit}")

    def set_whatsapp_notifier(self, notifier):
        """Inject WhatsApp notifier"""
        self.whatsapp = notifier

    async def track_llm_usage(
        self, model: str, input_tokens: int, output_tokens: int, job_id: Optional[str] = None
    ) -> float:
        """
        Track LLM API usage and costs
        @requirement: Accurate LLM cost tracking
        """
        try:
            # Get pricing for model
            pricing = self.LLM_PRICING.get(model, self.LLM_PRICING["gpt-3.5-turbo"])

            # Calculate cost (convert from per million to actual tokens)
            input_cost = (input_tokens / 1_000_000) * pricing["input"]
            output_cost = (output_tokens / 1_000_000) * pricing["output"]
            total_cost = input_cost + output_cost

            # Create cost entry
            entry = CostEntry(
                timestamp=datetime.now(),
                category=CostCategory.LLM_API,
                service=model,
                amount=total_cost,
                units=f"{input_tokens + output_tokens} tokens",
                metadata={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "job_id": job_id,
                },
            )

            # Track cost
            await self._record_cost(entry)

            # Check budget
            await self._check_budget(entry)

            logger.info(
                f"LLM cost tracked: ${total_cost:.4f} for {model} "
                f"({input_tokens} in, {output_tokens} out)"
            )

            return total_cost

        except Exception as e:
            logger.error(f"Failed to track LLM usage: {e}")
            return 0.0

    async def track_blockchain_tx(
        self, chain: str, gas_used: int, tx_type: str = "standard", job_id: Optional[str] = None
    ) -> float:
        """
        Track blockchain transaction costs
        @requirement: Blockchain cost tracking
        """
        try:
            # Get chain costs
            chain_costs = self.BLOCKCHAIN_COSTS.get(chain, self.BLOCKCHAIN_COSTS["polygon"])

            # Calculate cost
            gas_cost = gas_used * chain_costs["gas_price"]
            total_cost = gas_cost + chain_costs["base_fee"]

            # Create cost entry
            entry = CostEntry(
                timestamp=datetime.now(),
                category=CostCategory.BLOCKCHAIN,
                service=f"{chain}_{tx_type}",
                amount=total_cost,
                units=f"{gas_used} gas",
                metadata={
                    "chain": chain,
                    "gas_used": gas_used,
                    "tx_type": tx_type,
                    "job_id": job_id,
                },
            )

            # Track cost
            await self._record_cost(entry)

            logger.info(f"Blockchain cost tracked: ${total_cost:.4f} on {chain}")

            return total_cost

        except Exception as e:
            logger.error(f"Failed to track blockchain tx: {e}")
            return 0.0

    async def track_storage(
        self,
        size_bytes: int,
        duration_hours: float = 24,
        service: str = "ipfs",
        job_id: Optional[str] = None,
    ) -> float:
        """
        Track storage costs (IPFS, S3, etc.)
        @requirement: Storage cost tracking
        """
        try:
            # Storage pricing per GB per month
            storage_pricing = {
                "ipfs": 0.01,  # Pinning service cost
                "s3": 0.023,
                "gcs": 0.020,
                "azure": 0.0184,
            }

            price_per_gb_month = storage_pricing.get(service, 0.01)

            # Calculate cost
            size_gb = size_bytes / (1024**3)
            hours_in_month = 730
            cost_per_hour = (price_per_gb_month / hours_in_month) * size_gb
            total_cost = cost_per_hour * duration_hours

            # Create cost entry
            entry = CostEntry(
                timestamp=datetime.now(),
                category=CostCategory.STORAGE,
                service=service,
                amount=total_cost,
                units=f"{size_gb:.3f} GB for {duration_hours} hours",
                metadata={
                    "size_bytes": size_bytes,
                    "duration_hours": duration_hours,
                    "job_id": job_id,
                },
            )

            # Track cost
            await self._record_cost(entry)

            logger.info(f"Storage cost tracked: ${total_cost:.6f} for {size_gb:.3f} GB")

            return total_cost

        except Exception as e:
            logger.error(f"Failed to track storage: {e}")
            return 0.0

    async def track_compute(
        self,
        cpu_hours: float,
        memory_gb_hours: float,
        gpu_hours: float = 0,
        job_id: Optional[str] = None,
    ) -> float:
        """
        Track compute resource costs
        @requirement: Compute cost tracking
        """
        try:
            # Compute pricing (USD per hour)
            compute_pricing = {
                "cpu_hour": 0.05,
                "memory_gb_hour": 0.01,
                "gpu_hour": 0.50,  # GPU is much more expensive
            }

            # Calculate costs
            cpu_cost = cpu_hours * compute_pricing["cpu_hour"]
            memory_cost = memory_gb_hours * compute_pricing["memory_gb_hour"]
            gpu_cost = gpu_hours * compute_pricing["gpu_hour"]
            total_cost = cpu_cost + memory_cost + gpu_cost

            # Create cost entry
            entry = CostEntry(
                timestamp=datetime.now(),
                category=CostCategory.COMPUTE,
                service="compute_resources",
                amount=total_cost,
                units=f"CPU: {cpu_hours}h, RAM: {memory_gb_hours}GB·h, GPU: {gpu_hours}h",
                metadata={
                    "cpu_hours": cpu_hours,
                    "memory_gb_hours": memory_gb_hours,
                    "gpu_hours": gpu_hours,
                    "job_id": job_id,
                },
            )

            # Track cost
            await self._record_cost(entry)

            logger.info(f"Compute cost tracked: ${total_cost:.4f}")

            return total_cost

        except Exception as e:
            logger.error(f"Failed to track compute: {e}")
            return 0.0

    async def get_current_spend(self, period: str = "daily") -> Tuple[float, Dict[str, float]]:
        """
        Get current spending for a period
        @requirement: Real-time cost visibility
        """
        try:
            now = datetime.now()

            if period == "daily":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == "monthly":
                start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == "hourly":
                start_time = now.replace(minute=0, second=0, microsecond=0)
            else:
                start_time = now - timedelta(hours=24)

            # Calculate totals by category
            total = 0.0
            by_category = {}

            for entry in self.current_costs:
                if entry.timestamp >= start_time:
                    total += entry.amount
                    category = entry.category.value
                    by_category[category] = by_category.get(category, 0.0) + entry.amount

            return total, by_category

        except Exception as e:
            logger.error(f"Failed to get current spend: {e}")
            return 0.0, {}

    async def get_job_cost(self, job_id: str) -> float:
        """
        Get total cost for a specific job
        @requirement: Per-job cost tracking
        """
        try:
            total = 0.0
            for entry in self.current_costs:
                if entry.metadata.get("job_id") == job_id:
                    total += entry.amount
            return total
        except Exception as e:
            logger.error(f"Failed to get job cost: {e}")
            return 0.0

    async def optimize_costs(self) -> Dict[str, Any]:
        """
        Analyze costs and suggest optimizations
        @requirement: Cost optimization
        """
        try:
            daily_total, by_category = await self.get_current_spend("daily")

            suggestions = []

            # Check LLM usage
            llm_cost = by_category.get(CostCategory.LLM_API.value, 0)
            if llm_cost > daily_total * 0.5:  # LLM is >50% of costs
                suggestions.append(
                    {
                        "category": "LLM",
                        "issue": f"High LLM costs (${llm_cost:.2f}, {llm_cost/daily_total*100:.1f}% of total)",
                        "suggestion": "Consider using cheaper models for non-critical tasks",
                    }
                )

            # Check blockchain costs
            blockchain_cost = by_category.get(CostCategory.BLOCKCHAIN.value, 0)
            if blockchain_cost > 1.0:  # More than $1 in blockchain fees
                suggestions.append(
                    {
                        "category": "Blockchain",
                        "issue": f"High blockchain fees (${blockchain_cost:.2f})",
                        "suggestion": "Consider batching transactions or using L2 solutions",
                    }
                )

            # Check storage patterns
            storage_cost = by_category.get(CostCategory.STORAGE.value, 0)
            if storage_cost > 0.5:
                suggestions.append(
                    {
                        "category": "Storage",
                        "issue": f"Storage costs accumulating (${storage_cost:.2f})",
                        "suggestion": "Review data retention policies and clean up old data",
                    }
                )

            return {
                "daily_total": daily_total,
                "by_category": by_category,
                "suggestions": suggestions,
                "budget_usage": daily_total / self.budget.daily_limit,
            }

        except Exception as e:
            logger.error(f"Failed to optimize costs: {e}")
            return {}

    async def _record_cost(self, entry: CostEntry):
        """Record cost entry and update totals"""
        try:
            # Add to current costs
            self.current_costs.append(entry)

            # Update daily total
            date_key = entry.timestamp.strftime("%Y-%m-%d")
            self.daily_totals[date_key] = self.daily_totals.get(date_key, 0.0) + entry.amount

            # Update job cost if applicable
            job_id = entry.metadata.get("job_id")
            if job_id:
                self.job_costs[job_id] = self.job_costs.get(job_id, 0.0) + entry.amount

            # Persist to log
            await self._save_cost_log(entry)

        except Exception as e:
            logger.error(f"Failed to record cost: {e}")

    async def _check_budget(self, entry: CostEntry):
        """Check budget limits and send alerts"""
        try:
            # Get current daily spend
            daily_total, _ = await self.get_current_spend("daily")

            # Check daily limit
            daily_usage = daily_total / self.budget.daily_limit

            if daily_usage >= self.budget.critical_threshold:
                await self._send_budget_alert("critical", daily_total, self.budget.daily_limit)
            elif daily_usage >= self.budget.warning_threshold:
                await self._send_budget_alert("warning", daily_total, self.budget.daily_limit)

            # Check per-job limit
            job_id = entry.metadata.get("job_id")
            if job_id:
                job_cost = self.job_costs.get(job_id, 0.0)
                if job_cost > self.budget.per_job_limit:
                    logger.warning(f"Job {job_id} exceeded budget: ${job_cost:.2f}")
                    if self.whatsapp:
                        await self.whatsapp.notify_critical(
                            f"⚠️ Job Budget Exceeded\n"
                            f"Job: {job_id}\n"
                            f"Cost: ${job_cost:.2f}\n"
                            f"Limit: ${self.budget.per_job_limit:.2f}"
                        )

        except Exception as e:
            logger.error(f"Failed to check budget: {e}")

    async def _send_budget_alert(self, level: str, current: float, limit: float):
        """Send budget alert with cooldown"""
        try:
            # Check cooldown
            last_alert = self.last_alert_time.get(level)
            if last_alert:
                if datetime.now() - last_alert < self.alert_cooldown:
                    return  # Skip alert due to cooldown

            # Send alert
            usage_pct = (current / limit) * 100

            if level == "critical":
                message = (
                    f"🚨 CRITICAL: Daily Budget Alert\n"
                    f"Current: ${current:.2f}\n"
                    f"Limit: ${limit:.2f}\n"
                    f"Usage: {usage_pct:.1f}%\n"
                    f"Action: Costs may be throttled!"
                )
            else:
                message = (
                    f"⚠️ WARNING: Daily Budget Alert\n"
                    f"Current: ${current:.2f}\n"
                    f"Limit: ${limit:.2f}\n"
                    f"Usage: {usage_pct:.1f}%"
                )

            if self.whatsapp:
                await self.whatsapp.notify_critical(message)

            logger.warning(f"Budget {level}: ${current:.2f} of ${limit:.2f} ({usage_pct:.1f}%)")

            # Update last alert time
            self.last_alert_time[level] = datetime.now()

        except Exception as e:
            logger.error(f"Failed to send budget alert: {e}")

    async def _save_cost_log(self, entry: CostEntry):
        """Save cost entry to persistent log"""
        try:
            # Prepare entry for JSON
            entry_dict = {
                "timestamp": entry.timestamp.isoformat(),
                "category": entry.category.value,
                "service": entry.service,
                "amount": entry.amount,
                "units": entry.units,
                "metadata": entry.metadata,
            }

            # Append to log file
            os.makedirs(os.path.dirname(self.cost_log_file), exist_ok=True)

            async with aiofiles.open(self.cost_log_file, "a") as f:
                await f.write(json.dumps(entry_dict) + "\n")

        except Exception as e:
            logger.error(f"Failed to save cost log: {e}")

    async def load_historical_costs(self, days: int = 7):
        """Load historical costs from log"""
        try:
            if not os.path.exists(self.cost_log_file):
                return

            cutoff = datetime.now() - timedelta(days=days)

            async with aiofiles.open(self.cost_log_file, "r") as f:
                async for line in f:
                    try:
                        entry_dict = json.loads(line)
                        timestamp = datetime.fromisoformat(entry_dict["timestamp"])

                        if timestamp >= cutoff:
                            entry = CostEntry(
                                timestamp=timestamp,
                                category=CostCategory(entry_dict["category"]),
                                service=entry_dict["service"],
                                amount=entry_dict["amount"],
                                units=entry_dict["units"],
                                metadata=entry_dict.get("metadata", {}),
                            )
                            self.current_costs.append(entry)

                    except Exception as e:
                        logger.warning(f"Failed to parse cost entry: {e}")

            logger.info(f"Loaded {len(self.current_costs)} historical cost entries")

        except Exception as e:
            logger.error(f"Failed to load historical costs: {e}")


async def main():
    """Test cost monitor"""
    logging.basicConfig(level=logging.INFO)

    # Configuration
    config = {
        "daily_limit": 10.0,
        "monthly_limit": 200.0,
        "per_job_limit": 2.0,
        "cost_log": "logs/costs.json",
    }

    # Initialize monitor
    monitor = CostMonitor(config)

    # Test LLM tracking
    await monitor.track_llm_usage("gpt-4", 1000, 500, job_id="test-001")
    await monitor.track_llm_usage("claude-3-sonnet", 2000, 1000, job_id="test-001")

    # Test blockchain tracking
    await monitor.track_blockchain_tx("ethereum", 21000, "standard", job_id="test-001")

    # Test storage tracking
    await monitor.track_storage(1024 * 1024 * 100, 24, "ipfs", job_id="test-001")  # 100MB for 24h

    # Test compute tracking
    await monitor.track_compute(2.5, 4.0, 0.5, job_id="test-001")

    # Get current spend
    daily_total, by_category = await monitor.get_current_spend("daily")
    print(f"\nDaily Total: ${daily_total:.2f}")
    print("By Category:")
    for cat, amount in by_category.items():
        print(f"  {cat}: ${amount:.2f}")

    # Get job cost
    job_cost = await monitor.get_job_cost("test-001")
    print(f"\nJob test-001 cost: ${job_cost:.2f}")

    # Get optimization suggestions
    optimization = await monitor.optimize_costs()
    print(f"\nOptimization Analysis:")
    print(f"Budget Usage: {optimization['budget_usage']*100:.1f}%")
    if optimization["suggestions"]:
        print("Suggestions:")
        for suggestion in optimization["suggestions"]:
            print(f"  - {suggestion['category']}: {suggestion['suggestion']}")


if __name__ == "__main__":
    asyncio.run(main())
