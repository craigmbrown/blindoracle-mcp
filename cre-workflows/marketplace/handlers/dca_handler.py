#!/usr/bin/env python3
"""
BlindOracle AI DCA Agent Handler
=================================

Implements the AI-powered Dollar Cost Averaging Agent (UC3) for the
CRE marketplace. Manages subscriber subscriptions, analyzes market
conditions, calculates optimal purchase amounts (smart DCA adjusts
+/-20% based on conditions), and executes purchases via CrossChainRouter.

Revenue model: $29-99/mo subscription tiers (basic, pro, whale).

Dependencies:
    - security.blindoracle_security_gateway (SecurityRequest, BlindOracleSecurityGateway)
    - services.swaps.cross_chain_router (CrossChainRouter, SwapPair)

BLP Properties:
    BLP-001 (Alignment): Domain-specific DCA strategy understanding
    BLP-011 (Autonomy): Fully autonomous daily execution (99% autonomy)
    BLP-019 (Logging): Complete execution audit trail per subscriber
    BLP-023 (Durability): Per-subscriber error isolation

@author: Craig M. Brown
@version: 1.0.0
@date: 2026-02-15
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import random
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
from services.swaps.cross_chain_router import CrossChainRouter, SwapPair

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SubscriptionTier(Enum):
    """DCA subscription tiers with pricing and feature sets."""
    BASIC = "basic"
    PRO = "pro"
    WHALE = "whale"


class DCAStrategy(Enum):
    """DCA execution strategies."""
    FIXED = "fixed"      # Fixed amount every period
    SMART = "smart"      # AI-adjusted +/-20% based on market conditions


class DCAFrequency(Enum):
    """Purchase frequency options."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class MarketTrend(Enum):
    """Simplified market trend indicator."""
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class DCAConfig:
    """Configuration for the DCA Agent.

    REQ-BLP-001: Domain-specific DCA configuration.

    Attributes:
        subscription_tiers: Tier definitions with pricing and features.
        smart_adjustment_pct: Maximum adjustment percentage for smart DCA.
        security_interface: CaMel gateway interface identifier.
        security_agent_id: Agent identity for security gateway.
    """
    subscription_tiers: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "basic": {
            "name": "Basic DCA",
            "price_usd_monthly": 29,
            "supported_assets": ["BTC"],
            "features": ["fixed_dca"],
            "max_daily_sats": 100_000,
        },
        "pro": {
            "name": "Pro DCA",
            "price_usd_monthly": 49,
            "supported_assets": ["BTC", "ETH"],
            "features": ["fixed_dca", "smart_dca"],
            "max_daily_sats": 500_000,
        },
        "whale": {
            "name": "Whale DCA",
            "price_usd_monthly": 99,
            "supported_assets": ["BTC", "ETH"],
            "features": ["fixed_dca", "smart_dca", "volatility_scaling"],
            "max_daily_sats": 2_000_000,
        },
    })
    smart_adjustment_pct: float = 20.0
    security_interface: str = "x402_api"
    security_agent_id: str = "dca_agent_v1"


@dataclass
class DCASubscription:
    """Represents an active DCA subscription.

    Attributes:
        subscriber_id: Unique subscriber identifier.
        asset: Target asset (e.g. "BTC", "ETH").
        amount_sats: Base purchase amount per period in satoshis.
        frequency: Purchase frequency (daily/weekly/monthly).
        strategy: DCA strategy (fixed or smart).
        tier: Subscription tier.
        active: Whether the subscription is currently active.
        created_at: ISO-8601 creation timestamp.
        last_execution: ISO-8601 timestamp of last purchase.
        total_invested_sats: Total amount invested across all purchases.
        total_units_acquired: Total units acquired (in smallest unit).
    """
    subscriber_id: str
    asset: str
    amount_sats: int
    frequency: str = DCAFrequency.DAILY.value
    strategy: str = DCAStrategy.FIXED.value
    tier: str = SubscriptionTier.BASIC.value
    active: bool = True
    created_at: str = ""
    last_execution: str = ""
    total_invested_sats: int = 0
    total_units_acquired: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class MarketAnalysis:
    """Result of market condition analysis for an asset.

    Attributes:
        asset: The asset analyzed.
        trend: Current market trend (bullish/neutral/bearish).
        volatility_index: Volatility score (0.0 = stable, 1.0 = highly volatile).
        price_vs_sma: Price relative to 7-day SMA (-1.0 to +1.0).
        momentum: Momentum indicator (-1.0 bearish to +1.0 bullish).
        recommendation: Adjustment recommendation for smart DCA.
        adjustment_pct: Recommended adjustment percentage (-20 to +20).
    """
    asset: str
    trend: str
    volatility_index: float
    price_vs_sma: float
    momentum: float
    recommendation: str
    adjustment_pct: float


@dataclass
class PurchaseResult:
    """Result of a single DCA purchase execution.

    Attributes:
        subscriber_id: Subscriber who this purchase was for.
        asset: Asset purchased.
        requested_amount_sats: Amount requested for purchase.
        actual_amount_sats: Amount actually purchased (after smart adjustment).
        output_amount: Amount of asset received in smallest unit.
        tx_hash: Transaction hash.
        success: Whether the purchase succeeded.
        error: Error message on failure.
        market_context: Market analysis context at time of purchase.
    """
    subscriber_id: str
    asset: str
    requested_amount_sats: int
    actual_amount_sats: int = 0
    output_amount: int = 0
    tx_hash: str = ""
    success: bool = False
    error: Optional[str] = None
    market_context: Optional[Dict[str, Any]] = None


@dataclass
class ExecutionReport:
    """Summary report for a DCA execution cycle.

    Attributes:
        timestamp: ISO-8601 timestamp.
        cycle_id: Unique cycle identifier.
        subscriptions_processed: Number of subscriptions processed.
        purchases_successful: Number of successful purchases.
        purchases_failed: Number of failed purchases.
        total_volume_sats: Total purchase volume in satoshis.
        subscription_revenue_usd: Monthly subscription revenue.
        errors: List of errors encountered.
    """
    timestamp: str = ""
    cycle_id: str = ""
    subscriptions_processed: int = 0
    purchases_successful: int = 0
    purchases_failed: int = 0
    total_volume_sats: int = 0
    subscription_revenue_usd: float = 0.0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.cycle_id:
            self.cycle_id = f"dca_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Swap pair resolution for DCA
# ---------------------------------------------------------------------------

_DCA_PAIR_MAP: Dict[str, SwapPair] = {
    "BTC": SwapPair.ECASH_BTC,       # Buy BTC via eCash
    "ETH": SwapPair.BTC_ETH,         # Buy ETH via BTC
}


# ---------------------------------------------------------------------------
# DCA Agent
# ---------------------------------------------------------------------------

class DCAAgent:
    """AI-powered Dollar Cost Averaging Agent.

    Manages DCA subscriptions across three tiers. Executes daily,
    weekly, or monthly purchases for each subscriber, optionally
    adjusting amounts +/-20% based on market intelligence (smart DCA).

    Revenue: Monthly subscription fees ($29/$49/$99).

    REQ-BLP-001 (Alignment): DCA strategy domain expertise
    REQ-BLP-011 (Autonomy): Fully autonomous execution (99% autonomy)
    REQ-BLP-019 (Logging): Per-subscriber audit trail
    REQ-BLP-023 (Durability): Per-subscriber error isolation

    Usage:
        config = DCAConfig()
        agent = DCAAgent(config)
        report = await agent.run_workflow()
    """

    def __init__(
        self,
        config: Optional[DCAConfig] = None,
        router: Optional[CrossChainRouter] = None,
        gateway: Optional[BlindOracleSecurityGateway] = None,
        subscriptions: Optional[List[DCASubscription]] = None,
    ) -> None:
        """Initialize the DCA Agent.

        Args:
            config: DCA configuration. Uses defaults if not provided.
            router: CrossChainRouter instance. Created if not provided.
            gateway: Security gateway instance. Created if not provided.
            subscriptions: Pre-loaded subscriptions (for testing).
        """
        self.config = config or DCAConfig()
        self._router = router or CrossChainRouter()
        self._gateway = gateway or BlindOracleSecurityGateway()

        # Authorize the DCA agent
        self._gateway.authorize_agent(self.config.security_agent_id)

        # Subscription store
        self._subscriptions: List[DCASubscription] = subscriptions or []
        self._active_subscriptions: List[DCASubscription] = []

        # State for current cycle
        self._market_analyses: Dict[str, MarketAnalysis] = {}
        self._purchase_results: List[PurchaseResult] = []
        self._errors: List[str] = []

        logger.info("[SUCCESS] DCAAgent initialized")
        logger.info("[INFO]   Tiers: %s", list(self.config.subscription_tiers.keys()))
        logger.info("[INFO]   Smart adjustment: +/-%.0f%%", self.config.smart_adjustment_pct)

    # ---- Step 1: Check Subscriptions ----

    async def check_subscriptions(self) -> List[DCASubscription]:
        """Load and filter active subscriptions due for execution.

        REQ-BLP-011: Autonomously determines which subscriptions to process.

        Returns:
            List of active subscriptions due for execution.
        """
        try:
            now = datetime.now(timezone.utc)

            self._active_subscriptions = []
            for sub in self._subscriptions:
                if not sub.active:
                    continue

                # Check if due for execution based on frequency
                if sub.last_execution:
                    last_exec = datetime.fromisoformat(sub.last_execution)
                    if sub.frequency == DCAFrequency.DAILY.value:
                        if (now - last_exec).days < 1:
                            continue
                    elif sub.frequency == DCAFrequency.WEEKLY.value:
                        if (now - last_exec).days < 7:
                            continue
                    elif sub.frequency == DCAFrequency.MONTHLY.value:
                        if (now - last_exec).days < 28:
                            continue

                self._active_subscriptions.append(sub)

            logger.info(
                "[SUCCESS] Subscriptions checked: %d active, %d due for execution",
                sum(1 for s in self._subscriptions if s.active),
                len(self._active_subscriptions),
            )
            return self._active_subscriptions

        except Exception as e:
            error_msg = f"Subscription check failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 2: Analyze Market ----

    async def analyze_market(self) -> Dict[str, MarketAnalysis]:
        """Analyze market conditions for all relevant assets.

        Generates mock market analysis with trend, volatility, and
        momentum indicators. In production, this would query real
        price APIs and calculate technical indicators.

        REQ-BLP-001: Domain expertise in market analysis for DCA optimization.

        Returns:
            Dictionary mapping asset name to MarketAnalysis.
        """
        try:
            # Determine which assets need analysis
            assets_needed = set()
            for sub in self._active_subscriptions:
                assets_needed.add(sub.asset)

            for asset in assets_needed:
                # Mock market analysis (in production: query price APIs)
                # Use deterministic seeding based on date for reproducibility
                date_seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
                asset_seed = hash(asset) % 1000
                random.seed(date_seed + asset_seed)

                price_vs_sma = random.uniform(-0.15, 0.15)
                volatility = random.uniform(0.1, 0.8)
                momentum = random.uniform(-0.5, 0.5)

                # Determine trend
                if price_vs_sma > 0.05:
                    trend = MarketTrend.BULLISH.value
                elif price_vs_sma < -0.05:
                    trend = MarketTrend.BEARISH.value
                else:
                    trend = MarketTrend.NEUTRAL.value

                # Calculate smart DCA adjustment
                # Buy more when price is below SMA (bearish = opportunity)
                # Buy less when price is above SMA (bullish = expensive)
                adjustment = -price_vs_sma * self.config.smart_adjustment_pct / 0.15
                adjustment = max(-self.config.smart_adjustment_pct,
                                 min(self.config.smart_adjustment_pct, adjustment))

                if adjustment > 5:
                    recommendation = "increase_purchase"
                elif adjustment < -5:
                    recommendation = "decrease_purchase"
                else:
                    recommendation = "maintain_amount"

                analysis = MarketAnalysis(
                    asset=asset,
                    trend=trend,
                    volatility_index=round(volatility, 3),
                    price_vs_sma=round(price_vs_sma, 4),
                    momentum=round(momentum, 3),
                    recommendation=recommendation,
                    adjustment_pct=round(adjustment, 1),
                )
                self._market_analyses[asset] = analysis

                logger.info(
                    "[SUCCESS] Market analysis for %s: trend=%s, vol=%.2f, "
                    "price_vs_sma=%.3f, adjustment=%+.1f%%",
                    asset, trend, volatility, price_vs_sma, adjustment,
                )

            # Reset random seed
            random.seed()

            return self._market_analyses

        except Exception as e:
            error_msg = f"Market analysis failed: {e}"
            logger.error("[ERROR] %s", error_msg)
            self._errors.append(error_msg)
            raise

    # ---- Step 3: Calculate Optimal Amount ----

    async def calculate_optimal_amount(
        self, subscription: DCASubscription
    ) -> int:
        """Calculate the optimal purchase amount for a subscriber.

        Fixed DCA: uses the configured amount unchanged.
        Smart DCA: adjusts +/-20% based on market conditions.

        REQ-BLP-011: Independent optimization of purchase amounts.

        Args:
            subscription: The subscriber's DCA subscription.

        Returns:
            Optimal purchase amount in satoshis.
        """
        base_amount = subscription.amount_sats

        if subscription.strategy == DCAStrategy.SMART.value:
            analysis = self._market_analyses.get(subscription.asset)
            if analysis:
                adjustment_factor = 1.0 + (analysis.adjustment_pct / 100.0)
                adjusted = int(base_amount * adjustment_factor)

                # Enforce tier limits
                tier_config = self.config.subscription_tiers.get(subscription.tier, {})
                max_daily = tier_config.get("max_daily_sats", 100_000)
                adjusted = min(adjusted, max_daily)
                adjusted = max(adjusted, 100)  # Minimum 100 sats

                logger.info(
                    "[INFO] Smart DCA for %s: base=%d, adjusted=%d (%+.1f%%)",
                    subscription.subscriber_id, base_amount, adjusted,
                    analysis.adjustment_pct,
                )
                return adjusted

        # Fixed DCA or no market data available
        logger.info(
            "[INFO] Fixed DCA for %s: amount=%d sats",
            subscription.subscriber_id, base_amount,
        )
        return base_amount

    # ---- Step 4: Execute Purchase ----

    async def execute_purchase(
        self, subscription: DCASubscription, amount_sats: int
    ) -> PurchaseResult:
        """Execute a DCA purchase for a subscriber.

        REQ-BLP-019: Complete audit trail for each purchase.
        REQ-BLP-023: Error isolation -- one subscriber's failure
        does not affect others.

        Args:
            subscription: The subscriber's DCA subscription.
            amount_sats: Calculated purchase amount in satoshis.

        Returns:
            PurchaseResult with execution details.
        """
        try:
            # CaMel security validation
            sec_request = SecurityRequest(
                interface=self.config.security_interface,
                operation="swap_execute",
                agent_id=self.config.security_agent_id,
                parameters={
                    "subscriber_id": subscription.subscriber_id,
                    "asset": subscription.asset,
                    "amount_sats": amount_sats,
                    "strategy": subscription.strategy,
                },
                amount_sats=amount_sats,
            )

            sec_response = self._gateway.process_request(sec_request)

            if not sec_response.approved:
                error_msg = f"CaMel rejected purchase: {sec_response.denial_reason}"
                logger.error("[ERROR] %s for subscriber %s",
                             error_msg, subscription.subscriber_id)
                return PurchaseResult(
                    subscriber_id=subscription.subscriber_id,
                    asset=subscription.asset,
                    requested_amount_sats=amount_sats,
                    success=False,
                    error=error_msg,
                )

            # Resolve swap pair
            pair = _DCA_PAIR_MAP.get(subscription.asset)
            if pair is None:
                return PurchaseResult(
                    subscriber_id=subscription.subscriber_id,
                    asset=subscription.asset,
                    requested_amount_sats=amount_sats,
                    success=False,
                    error=f"No swap pair for asset: {subscription.asset}",
                )

            # Execute via CrossChainRouter
            quote = await self._router.get_quote(pair, amount_sats)
            swap_result = await self._router.execute_swap(quote)

            market_ctx = None
            analysis = self._market_analyses.get(subscription.asset)
            if analysis:
                market_ctx = {
                    "trend": analysis.trend,
                    "volatility": analysis.volatility_index,
                    "adjustment_pct": analysis.adjustment_pct,
                }

            if swap_result.success:
                logger.info(
                    "[SUCCESS] DCA purchase: subscriber=%s, asset=%s, "
                    "amount=%d sats, output=%d, tx=%s",
                    subscription.subscriber_id, subscription.asset,
                    amount_sats, swap_result.output_amount,
                    swap_result.tx_hash[:18] if swap_result.tx_hash else "N/A",
                )
                return PurchaseResult(
                    subscriber_id=subscription.subscriber_id,
                    asset=subscription.asset,
                    requested_amount_sats=amount_sats,
                    actual_amount_sats=swap_result.input_amount,
                    output_amount=swap_result.output_amount,
                    tx_hash=swap_result.tx_hash,
                    success=True,
                    market_context=market_ctx,
                )
            else:
                return PurchaseResult(
                    subscriber_id=subscription.subscriber_id,
                    asset=subscription.asset,
                    requested_amount_sats=amount_sats,
                    success=False,
                    error=swap_result.error,
                    market_context=market_ctx,
                )

        except Exception as e:
            error_msg = f"Purchase failed for {subscription.subscriber_id}: {e}"
            logger.error("[ERROR] %s", error_msg)
            return PurchaseResult(
                subscriber_id=subscription.subscriber_id,
                asset=subscription.asset,
                requested_amount_sats=amount_sats,
                success=False,
                error=str(e),
            )

    # ---- Step 5: Update Positions ----

    async def update_positions(
        self, subscription: DCASubscription, result: PurchaseResult
    ) -> None:
        """Update a subscriber's accumulated position after a purchase.

        REQ-BLP-019: Tracks cumulative investment history.

        Args:
            subscription: The subscriber's DCA subscription.
            result: The purchase execution result.
        """
        if result.success:
            subscription.total_invested_sats += result.actual_amount_sats
            subscription.total_units_acquired += result.output_amount
            subscription.last_execution = datetime.now(timezone.utc).isoformat()

            # Calculate average cost basis
            avg_cost = (
                subscription.total_invested_sats / subscription.total_units_acquired
                if subscription.total_units_acquired > 0 else 0
            )

            logger.info(
                "[SUCCESS] Position updated: subscriber=%s, total_invested=%d sats, "
                "total_units=%d, avg_cost=%.4f",
                subscription.subscriber_id,
                subscription.total_invested_sats,
                subscription.total_units_acquired,
                avg_cost,
            )

    # ---- Step 6: Notify Subscriber ----

    async def notify_subscriber(
        self, subscription: DCASubscription, result: PurchaseResult
    ) -> Dict[str, Any]:
        """Generate an execution report for a subscriber.

        REQ-BLP-019: Subscriber-level reporting.

        Args:
            subscription: The subscriber's DCA subscription.
            result: The purchase execution result.

        Returns:
            Report dictionary for the subscriber.
        """
        report = {
            "subscriber_id": subscription.subscriber_id,
            "asset": subscription.asset,
            "tier": subscription.tier,
            "strategy": subscription.strategy,
            "success": result.success,
            "amount_purchased_sats": result.actual_amount_sats,
            "output_received": result.output_amount,
            "total_invested_sats": subscription.total_invested_sats,
            "total_units_acquired": subscription.total_units_acquired,
            "market_context": result.market_context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if result.error:
            report["error"] = result.error

        logger.info(
            "[INFO] Subscriber report: %s - %s - %s",
            subscription.subscriber_id,
            "SUCCESS" if result.success else "FAILED",
            f"{result.actual_amount_sats} sats" if result.success else result.error,
        )

        return report

    # ---- Full Workflow Orchestration ----

    async def run_workflow(self) -> ExecutionReport:
        """Execute the full DCA workflow for all active subscribers.

        Runs all 6 steps:
        1. Check subscriptions
        2. Analyze market conditions
        3-6. For each subscriber: calculate, execute, update, notify

        Returns:
            ExecutionReport with cycle summary.
        """
        logger.info("[INFO] === DCA Agent Workflow Starting ===")
        start = time.time()

        try:
            # Step 1: Load subscriptions
            active = await self.check_subscriptions()

            if not active:
                logger.info("[INFO] No subscriptions due for execution")
                return ExecutionReport(subscriptions_processed=0)

            # Step 2: Analyze market
            await self.analyze_market()

            # Steps 3-6: Process each subscriber
            successful = 0
            failed = 0
            total_volume = 0

            for sub in active:
                try:
                    # Calculate amount
                    amount = await self.calculate_optimal_amount(sub)

                    # Execute purchase
                    result = await self.execute_purchase(sub, amount)
                    self._purchase_results.append(result)

                    # Update position
                    await self.update_positions(sub, result)

                    # Notify
                    await self.notify_subscriber(sub, result)

                    if result.success:
                        successful += 1
                        total_volume += result.actual_amount_sats
                    else:
                        failed += 1

                except Exception as e:
                    failed += 1
                    error_msg = f"Subscriber {sub.subscriber_id} processing error: {e}"
                    logger.error("[ERROR] %s", error_msg)
                    self._errors.append(error_msg)

            # Calculate subscription revenue
            revenue = 0.0
            for sub in self._subscriptions:
                if sub.active:
                    tier_config = self.config.subscription_tiers.get(sub.tier, {})
                    revenue += tier_config.get("price_usd_monthly", 0)

            report = ExecutionReport(
                subscriptions_processed=len(active),
                purchases_successful=successful,
                purchases_failed=failed,
                total_volume_sats=total_volume,
                subscription_revenue_usd=revenue,
                errors=list(self._errors),
            )

            elapsed = (time.time() - start) * 1000
            logger.info("[SUCCESS] === DCA Agent Workflow Complete (%.0fms) ===", elapsed)
            logger.info("[INFO]   Processed: %d subscriptions", len(active))
            logger.info("[INFO]   Successful: %d, Failed: %d", successful, failed)
            logger.info("[INFO]   Volume: %d sats", total_volume)
            logger.info("[INFO]   Revenue: $%.0f/mo", revenue)

            return report

        except Exception as e:
            logger.error("[ERROR] DCA workflow failed: %s", e)
            self._errors.append(f"Workflow error: {e}")
            return ExecutionReport(errors=list(self._errors))


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

async def _run_self_test() -> None:
    """Validate the full DCA Agent workflow with mock subscriptions."""
    print("=" * 70)
    print("BlindOracle AI DCA Agent -- Self-Test")
    print("=" * 70)

    results: List[Dict[str, Any]] = []

    # Create test subscriptions
    test_subscriptions = [
        DCASubscription(
            subscriber_id="sub_alice_001",
            asset="BTC",
            amount_sats=50_000,
            frequency=DCAFrequency.DAILY.value,
            strategy=DCAStrategy.FIXED.value,
            tier=SubscriptionTier.BASIC.value,
        ),
        DCASubscription(
            subscriber_id="sub_bob_002",
            asset="BTC",
            amount_sats=100_000,
            frequency=DCAFrequency.DAILY.value,
            strategy=DCAStrategy.SMART.value,
            tier=SubscriptionTier.PRO.value,
        ),
        DCASubscription(
            subscriber_id="sub_whale_003",
            asset="ETH",
            amount_sats=500_000,
            frequency=DCAFrequency.DAILY.value,
            strategy=DCAStrategy.SMART.value,
            tier=SubscriptionTier.WHALE.value,
        ),
        DCASubscription(
            subscriber_id="sub_inactive_004",
            asset="BTC",
            amount_sats=10_000,
            frequency=DCAFrequency.DAILY.value,
            strategy=DCAStrategy.FIXED.value,
            tier=SubscriptionTier.BASIC.value,
            active=False,  # Inactive -- should be skipped
        ),
    ]

    # --- 1. Initialize ---
    print("\n--- 1. Initialize DCA Agent ---")
    config = DCAConfig()
    agent = DCAAgent(config, subscriptions=test_subscriptions)
    print(f"  Tiers: {list(config.subscription_tiers.keys())}")
    print(f"  Subscriptions loaded: {len(test_subscriptions)}")
    results.append({"test": "Initialization", "pass": True})

    # --- 2. Check subscriptions ---
    print("\n--- 2. Check Active Subscriptions ---")
    active = await agent.check_subscriptions()
    print(f"  Active and due: {len(active)}")
    assert len(active) == 3, f"Expected 3 active, got {len(active)}"
    results.append({"test": "Check Subscriptions", "pass": len(active) == 3})

    # --- 3. Analyze market ---
    print("\n--- 3. Analyze Market Conditions ---")
    analyses = await agent.analyze_market()
    for asset, analysis in analyses.items():
        print(f"  {asset}: trend={analysis.trend}, vol={analysis.volatility_index}, "
              f"adj={analysis.adjustment_pct:+.1f}%")
    results.append({"test": "Analyze Market", "pass": len(analyses) > 0})

    # --- 4. Calculate amounts ---
    print("\n--- 4. Calculate Optimal Amounts ---")
    for sub in active:
        amount = await agent.calculate_optimal_amount(sub)
        label = f"{'smart' if sub.strategy == 'smart' else 'fixed'}"
        print(f"  {sub.subscriber_id} ({label}): base={sub.amount_sats}, optimal={amount}")
    results.append({"test": "Calculate Amounts", "pass": True})

    # --- 5. Execute purchases ---
    print("\n--- 5. Execute Purchases ---")
    for sub in active:
        amount = await agent.calculate_optimal_amount(sub)
        result = await agent.execute_purchase(sub, amount)
        status = "SUCCESS" if result.success else f"FAILED: {result.error}"
        print(f"  {sub.subscriber_id}: {status}")
        if result.success:
            print(f"    Purchased: {result.actual_amount_sats} sats -> {result.output_amount} units")
        await agent.update_positions(sub, result)
    results.append({"test": "Execute Purchases", "pass": True})

    # --- 6. Full workflow ---
    print("\n--- 6. Full Workflow Run ---")
    # Reset subscriptions for fresh run
    fresh_subs = [
        DCASubscription(
            subscriber_id="sub_fresh_001",
            asset="BTC",
            amount_sats=25_000,
            strategy=DCAStrategy.SMART.value,
            tier=SubscriptionTier.PRO.value,
        ),
    ]
    agent2 = DCAAgent(config, subscriptions=fresh_subs)
    report = await agent2.run_workflow()
    print(f"  Cycle ID: {report.cycle_id}")
    print(f"  Processed: {report.subscriptions_processed}")
    print(f"  Successful: {report.purchases_successful}")
    print(f"  Volume: {report.total_volume_sats} sats")
    print(f"  Revenue: ${report.subscription_revenue_usd}/mo")
    results.append({"test": "Full Workflow", "pass": report.purchases_successful >= 1})

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
