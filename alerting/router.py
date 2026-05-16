#!/usr/bin/env python3
"""
Multi-Channel Alert Router
@requirement: REQ-ALERT-005 - Multi-channel alert routing
@BLP: BLP-011 (Autonomy through automated delivery)

Project policy enforcement:
- WhatsApp is CRITICAL-only (feedback_whatsapp_p0_only)
- Uses existing WhatsAppNotifier and NostrPublisher
"""

import asyncio
import hashlib
import os
import sys
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure parent dir on path for sibling imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from .config import AlertConfig
from .event_detector import EventPriority, EventType, MarketEvent


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Sliding-window rate limiter.
    Allows up to config.max_alerts_per_hour events per rolling hour.
    Also enforces quiet hours.
    """

    def __init__(self, config: AlertConfig) -> None:
        self.config = config
        self._timestamps: deque = deque()

    def allow(self, event: MarketEvent) -> bool:
        """Return True if the event should be allowed through."""
        # CRITICAL events bypass quiet hours but still respect rate limit
        now = datetime.now(timezone.utc)

        # Quiet hours check (non-critical only)
        if event.priority != EventPriority.CRITICAL:
            local_hour = datetime.now().hour
            start = self.config.quiet_hours_start
            end = self.config.quiet_hours_end
            if start > end:
                # Spans midnight: e.g., 22 -> 7
                in_quiet = local_hour >= start or local_hour < end
            else:
                in_quiet = start <= local_hour < end
            if in_quiet:
                return False

        # Sliding window rate limit
        cutoff = now - timedelta(hours=1)
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) >= self.config.max_alerts_per_hour:
            return False

        self._timestamps.append(now)
        return True


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------

class Deduplicator:
    """
    Hash-based deduplication within a configurable time window.
    Prevents the same event from being re-sent within dedup_window_minutes.
    """

    def __init__(self, config: AlertConfig) -> None:
        self.config = config
        # key -> last seen timestamp
        self._seen: Dict[str, datetime] = {}

    def is_duplicate(self, event: MarketEvent) -> bool:
        """Return True if this event is a duplicate within the window."""
        key = event.dedup_key()
        now = datetime.now(timezone.utc)
        window = timedelta(minutes=self.config.dedup_window_minutes)

        if key in self._seen:
            if now - self._seen[key] < window:
                return True

        self._seen[key] = now
        # Prune stale entries periodically
        if len(self._seen) > 1000:
            cutoff = now - window
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        return False


# ---------------------------------------------------------------------------
# Alert Channel Abstractions
# ---------------------------------------------------------------------------

class AlertChannel(ABC):
    """Base class for alert delivery channels."""

    @abstractmethod
    async def send(self, event: MarketEvent) -> bool:
        """Deliver an alert. Returns True on success."""


class WhatsAppChannel(AlertChannel):
    """
    Delivers CRITICAL alerts only via WhatsApp.
    Per project policy (feedback_whatsapp_p0_only), only CRITICAL events
    go to WhatsApp regardless of user config.
    """

    def __init__(self) -> None:
        self._endpoint = os.getenv("WHATSAPP_ENDPOINT", "http://localhost:8083/api/send")
        self._recipient = os.getenv("WHATSAPP_RECIPIENT", os.environ.get("BLINDORACLE_OPERATOR_WHATSAPP", ""))

    async def send(self, event: MarketEvent) -> bool:
        """Send event to WhatsApp. Silently drops non-CRITICAL events."""
        if event.priority != EventPriority.CRITICAL:
            # P0-only policy enforced here
            return True

        message = self._format_message(event)
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                payload = {"to": self._recipient, "message": message}
                async with session.post(self._endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        print(f"✅ WhatsApp alert sent: {event.event_type.value}")
                        return True
                    body = await resp.text()
                    print(f"⚠️ WhatsApp API error {resp.status}: {body[:200]}")
                    return False
        except Exception as e:
            print(f"⚠️ WhatsApp channel failed (non-fatal): {e}")
            # Graceful degradation — alerts should never crash the monitoring loop
            return False

    def _format_message(self, event: MarketEvent) -> str:
        emoji_type = {
            EventType.ARBITRAGE_OPPORTUNITY: "💰",
            EventType.PROBABILITY_SHIFT: "📊",
            EventType.VOLUME_SPIKE: "📈",
            EventType.MARKET_RESOLUTION: "✅",
            EventType.PRICE_ALERT: "🎯",
            EventType.NEW_MARKET: "🆕",
        }.get(event.event_type, "📌")

        priority_emoji = {
            EventPriority.CRITICAL: "🚨",
            EventPriority.HIGH: "⚠️",
            EventPriority.MEDIUM: "ℹ️",
            EventPriority.LOW: "📝",
        }.get(event.priority, "📌")

        lines = [
            f"{priority_emoji} {emoji_type} {event.event_type.value.upper().replace('_', ' ')}",
            "",
            event.message,
            "",
            f"Market: {event.market_name}",
            f"Platform: {event.platform}",
            f"Confidence: {event.confidence:.0f}%",
            f"Time: {event.timestamp[:19]}",
        ]
        if event.action_url:
            lines.append(f"\n{event.action_url}")
        return "\n".join(lines)


class NOSTRChannel(AlertChannel):
    """
    Publishes events to NOSTR relays using existing NostrPublisher.
    Used for HIGH and MEDIUM priority alerts.
    """

    async def send(self, event: MarketEvent) -> bool:
        try:
            from core.nostr_integration import NostrPublisher

            publisher = NostrPublisher()

            if event.event_type == EventType.ARBITRAGE_OPPORTUNITY:
                result = await publisher.publish_arbitrage_opportunity({
                    "asset": event.market_name,
                    "profit_percentage": event.data.get("spread_percent", 0),
                    "markets": [event.data.get("buy_platform", ""), event.data.get("sell_platform", "")],
                    "window_minutes": 30,
                })
            else:
                result = await publisher.publish_research_analysis({
                    "title": f"Market Alert: {event.event_type.value.replace('_', ' ').title()}",
                    "executive_summary": event.message,
                    "markets_analyzed": {event.market_name: event.data},
                    "oracle_insights": [],
                    "predictions": [],
                    "risk_analysis": f"Confidence: {event.confidence:.0f}%",
                    "recommendations": [],
                })

            success = result.get("success", False)
            if success:
                print(f"✅ NOSTR alert published: {event.event_type.value}")
            else:
                print(f"⚠️ NOSTR publish partial failure: {result}")
            return success

        except Exception as e:
            print(f"⚠️ NOSTR channel failed (non-fatal): {e}")
            return False


class NullChannel(AlertChannel):
    """No-op channel for disabled or unimplemented channels."""

    async def send(self, event: MarketEvent) -> bool:
        return True


# ---------------------------------------------------------------------------
# Alert Router
# ---------------------------------------------------------------------------

class AlertRouter:
    """
    Routes MarketEvent objects to the correct channels based on priority,
    enforcing rate limiting and deduplication.

    @requirement: REQ-ALERT-005 - Multi-channel routing
    @BLP: BLP-011 (Autonomy)
    """

    def __init__(self, config: AlertConfig) -> None:
        self.config = config
        self._rate_limiter = RateLimiter(config)
        self._deduplicator = Deduplicator(config)
        self._channels: Dict[str, AlertChannel] = {
            "whatsapp": WhatsAppChannel(),
            "nostr": NOSTRChannel(),
            "email": NullChannel(),
            "slack": NullChannel(),
        }
        print("✅ AlertRouter initialized")

    def update_config(self, config: AlertConfig) -> None:
        """Hot-reload configuration without restarting."""
        self.config = config
        self._rate_limiter.config = config
        self._deduplicator.config = config
        print("✅ AlertRouter config updated")

    async def route(self, event: MarketEvent) -> Dict[str, Any]:
        """
        Route an event to appropriate channels.
        Returns a delivery report dict.
        @requirement: REQ-ALERT-005 - Priority-based routing
        """
        try:
            # Rate limit check
            if not self._rate_limiter.allow(event):
                print(f"ℹ️ AlertRouter: rate limited {event.event_type.value}")
                return {"status": "rate_limited", "event_id": event.event_id}

            # Deduplication check
            if self._deduplicator.is_duplicate(event):
                print(f"ℹ️ AlertRouter: duplicate suppressed {event.event_type.value}")
                return {"status": "duplicate", "event_id": event.event_id}

            # Determine target channels from priority config
            # WhatsApp is always CRITICAL-only regardless of config
            priority_key = event.priority.value
            configured_channels = self.config.priority_channels.get(priority_key, [])

            results: Dict[str, bool] = {}
            tasks = []

            for channel_name in configured_channels:
                # Enforce WhatsApp P0-only policy
                if channel_name == "whatsapp" and event.priority != EventPriority.CRITICAL:
                    continue

                channel = self._channels.get(channel_name)
                if channel and self.config.channels.get(channel_name, False):
                    tasks.append((channel_name, channel.send(event)))

            if tasks:
                channel_results = await asyncio.gather(
                    *[t[1] for t in tasks], return_exceptions=True
                )
                for (ch_name, _), result in zip(tasks, channel_results):
                    if isinstance(result, Exception):
                        results[ch_name] = False
                        print(f"❌ AlertRouter: {ch_name} raised exception: {result}")
                    else:
                        results[ch_name] = bool(result)

            report = {
                "status": "delivered",
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "priority": event.priority.value,
                "channels": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(f"✅ AlertRouter: {event.event_type.value} ({event.priority.value}) -> {results}")
            return report

        except Exception as e:
            print(f"❌ AlertRouter.route failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return {"status": "error", "error": str(e), "event_id": event.event_id}
