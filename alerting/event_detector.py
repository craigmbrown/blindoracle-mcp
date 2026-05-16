#!/usr/bin/env python3
"""
Event Detection Engine for Prediction Market Alerting
@requirement: REQ-ALERT-001 - Event detection from market data
@requirement: REQ-ALERT-002 - Arbitrage detection
@requirement: REQ-ALERT-003 - Probability shift detection
@BLP: BLP-021 (Durability through continuous monitoring)
"""

import asyncio
import difflib
import hashlib
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .config import AlertConfig


class EventPriority(Enum):
    """Priority levels for market events."""

    CRITICAL = "critical"  # Immediate action required (WhatsApp + NOSTR)
    HIGH = "high"          # Time-sensitive (NOSTR)
    MEDIUM = "medium"      # Important but not urgent (NOSTR)
    LOW = "low"            # Informational (batched/silent)


class EventType(Enum):
    """Types of detectable market events."""

    ARBITRAGE_OPPORTUNITY = "arbitrage_opportunity"
    PROBABILITY_SHIFT = "probability_shift"
    VOLUME_SPIKE = "volume_spike"
    MARKET_RESOLUTION = "market_resolution"
    PRICE_ALERT = "price_alert"
    NEW_MARKET = "new_market"
    NEWS_TRIGGER = "news_trigger"  # Signal fusion: belief velocity exceeds threshold


@dataclass
class MarketEvent:
    """
    Detected market event ready for routing.
    @requirement: REQ-ALERT-001 - MarketEvent data model
    """

    event_id: str
    event_type: EventType
    priority: EventPriority
    timestamp: str

    # Market context
    market_id: str
    market_name: str
    platform: str  # "kalshi" or "polymarket"

    # Event-specific payload
    data: Dict[str, Any]

    # Metadata
    confidence: float  # 0-100
    message: str
    action_url: Optional[str] = None

    def dedup_key(self) -> str:
        """Deterministic key for deduplication within a time window."""
        raw = f"{self.event_type.value}:{self.market_id}:{self.platform}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class EventDetector:
    """
    Polls prediction markets and emits MarketEvent objects via registered handlers.
    @requirement: REQ-ALERT-001 - Continuous market monitoring
    @requirement: REQ-ALERT-002 - Arbitrage detection
    @requirement: REQ-ALERT-003 - Probability shift detection
    @BLP: BLP-021 (Durability - auto-restarts on error)
    """

    def __init__(self, config: AlertConfig, aggregator: Any = None) -> None:
        self.config = config
        self._aggregator = aggregator
        self._handlers: List[Callable] = []
        # Market state snapshots keyed by market_id
        self._prev_state: Dict[str, Dict[str, Any]] = {}
        self._running = False
        print("✅ EventDetector initialized")

    async def add_handler(self, handler: Callable) -> None:
        """Register an async callback to receive MarketEvent objects."""
        self._handlers.append(handler)
        print(f"✅ EventDetector: handler registered ({len(self._handlers)} total)")

    async def start_monitoring(self) -> None:
        """
        Main monitoring loop. Runs indefinitely with error back-off.
        @requirement: REQ-ALERT-001 - Continuous monitoring loop
        @BLP: BLP-021 (Durability - survives transient failures)
        """
        self._running = True
        print(f"🔍 EventDetector: monitoring started (poll every {self.config.poll_interval_seconds}s)")

        while self._running:
            try:
                events = await self._check_all_markets()
                for event in events:
                    await self._emit_event(event)
                await asyncio.sleep(self.config.poll_interval_seconds)
            except asyncio.CancelledError:
                print("ℹ️ EventDetector: monitoring cancelled")
                self._running = False
                break
            except Exception as e:
                print(f"❌ EventDetector: error in monitoring loop: {e}")
                print(f"   Traceback: {traceback.format_exc()}")
                await asyncio.sleep(60)  # Back off on error

    def stop_monitoring(self) -> None:
        """Signal the monitoring loop to stop."""
        self._running = False

    async def _emit_event(self, event: MarketEvent) -> None:
        """Dispatch event to all registered handlers."""
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception as e:
                print(f"❌ EventDetector: handler error: {e}")
                print(f"   Traceback: {traceback.format_exc()}")

    async def _check_all_markets(self) -> List[MarketEvent]:
        """
        Fetch market data and run all detectors.
        @requirement: REQ-ALERT-001 - Unified event detection
        """
        events: List[MarketEvent] = []

        try:
            # Fetch current market data
            markets_by_platform = await self._fetch_markets()

            events.extend(await self._detect_arbitrage(markets_by_platform))
            events.extend(await self._detect_probability_shifts(markets_by_platform))
            events.extend(await self._detect_volume_spikes(markets_by_platform))
            events.extend(await self._detect_resolutions(markets_by_platform))
            events.extend(await self._detect_price_alerts(markets_by_platform))
            events.extend(await self._detect_new_markets(markets_by_platform))

            # Update state snapshot
            for platform, markets in markets_by_platform.items():
                for market in markets:
                    market_id = market.get("id", "")
                    self._prev_state[market_id] = {
                        "yes_price": market.get("yes_price", 0.0),
                        "no_price": market.get("no_price", 0.0),
                        "volume": market.get("volume", 0.0),
                        "status": market.get("status", "active"),
                        "platform": platform,
                        "title": market.get("title", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

        except Exception as e:
            print(f"❌ EventDetector._check_all_markets failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")

        return events

    async def _fetch_markets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch all markets from the aggregator."""
        result: Dict[str, List[Dict[str, Any]]] = {}
        try:
            if self._aggregator is None:
                return result

            # Kalshi
            try:
                kalshi_markets = await self._aggregator.get_kalshi_markets()
                result["kalshi"] = [
                    self._normalize_market(m, "kalshi") for m in (kalshi_markets or [])
                ]
            except Exception as e:
                print(f"⚠️ EventDetector: Kalshi fetch failed: {e}")
                result["kalshi"] = []

            # Polymarket
            try:
                poly_markets = await self._aggregator.get_polymarket_markets()
                result["polymarket"] = [
                    self._normalize_market(m, "polymarket") for m in (poly_markets or [])
                ]
            except Exception as e:
                print(f"⚠️ EventDetector: Polymarket fetch failed: {e}")
                result["polymarket"] = []

        except Exception as e:
            print(f"❌ EventDetector._fetch_markets failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")

        return result

    def _normalize_market(self, market: Any, platform: str) -> Dict[str, Any]:
        """Normalize a market object or dict to a flat dict."""
        if isinstance(market, dict):
            return {
                "id": market.get("id", ""),
                "title": market.get("title", ""),
                "yes_price": float(market.get("yes_price", 0.0)),
                "no_price": float(market.get("no_price", 0.0)),
                "volume": float(market.get("volume", 0.0)),
                "status": str(market.get("status", "active")),
                "platform": platform,
            }
        # NormalizedMarket dataclass
        return {
            "id": getattr(market, "id", ""),
            "title": getattr(market, "title", ""),
            "yes_price": float(getattr(market, "yes_price", 0.0)),
            "no_price": float(getattr(market, "no_price", 0.0)),
            "volume": float(getattr(market, "volume", 0.0)),
            "status": str(getattr(market, "status", "active")),
            "platform": platform,
        }

    async def _detect_arbitrage(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """
        Detect cross-platform arbitrage opportunities.
        @requirement: REQ-ALERT-002 - Arbitrage detection
        """
        events: List[MarketEvent] = []
        threshold = self.config.arbitrage_threshold_percent / 100.0

        kalshi = markets_by_platform.get("kalshi", [])
        poly = markets_by_platform.get("polymarket", [])

        # Build title index for cross-market matching (fuzzy, G4 fix)
        _FUZZY_THRESHOLD = 0.90  # SequenceMatcher ratio threshold (strict: prevent false positives)

        kalshi_titles: List[str] = []
        kalshi_by_norm_title: Dict[str, Dict] = {}
        for m in kalshi:
            norm = m.get("title", "").lower().strip()
            if norm:
                kalshi_titles.append(norm)
                kalshi_by_norm_title[norm] = m

        def _best_kalshi_match(poly_title: str) -> Optional[Dict]:
            """Return best-matching Kalshi market via fuzzy title comparison."""
            norm_poly = poly_title.lower().strip()
            if not norm_poly or not kalshi_titles:
                return None
            # Fast exact check first
            if norm_poly in kalshi_by_norm_title:
                return kalshi_by_norm_title[norm_poly]
            # Fuzzy fallback
            matches = difflib.get_close_matches(
                norm_poly, kalshi_titles, n=1, cutoff=_FUZZY_THRESHOLD
            )
            if matches:
                return kalshi_by_norm_title[matches[0]]
            return None

        for poly_market in poly:
            kalshi_market = _best_kalshi_match(poly_market.get("title", ""))
            if not kalshi_market:
                continue

            # Check YES arbitrage: buy YES on cheaper, sell on expensive
            yes_diff = abs(poly_market["yes_price"] - kalshi_market["yes_price"])
            if yes_diff >= threshold and yes_diff > 0:
                buy_platform = "polymarket" if poly_market["yes_price"] < kalshi_market["yes_price"] else "kalshi"
                sell_platform = "kalshi" if buy_platform == "polymarket" else "polymarket"
                buy_price = min(poly_market["yes_price"], kalshi_market["yes_price"])
                sell_price = max(poly_market["yes_price"], kalshi_market["yes_price"])
                spread_pct = yes_diff * 100

                events.append(
                    MarketEvent(
                        event_id=str(uuid.uuid4()),
                        event_type=EventType.ARBITRAGE_OPPORTUNITY,
                        priority=EventPriority.CRITICAL,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        market_id=f"{kalshi_market['id']}-{poly_market['id']}",
                        market_name=poly_market.get("title", "Unknown"),
                        platform=f"{buy_platform}↔{sell_platform}",
                        data={
                            "buy_platform": buy_platform,
                            "sell_platform": sell_platform,
                            "buy_price": buy_price,
                            "sell_price": sell_price,
                            "spread_percent": round(spread_pct, 2),
                            "side": "YES",
                        },
                        confidence=min(95.0, 70.0 + spread_pct * 5),
                        message=(
                            f"Arbitrage: {spread_pct:.1f}% spread on YES\n"
                            f"Buy on {buy_platform} @ {buy_price:.3f}\n"
                            f"Sell on {sell_platform} @ {sell_price:.3f}"
                        ),
                    )
                )

        return events

    async def _detect_probability_shifts(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """
        Detect significant probability changes since last poll.
        @requirement: REQ-ALERT-003 - Probability shift detection
        """
        events: List[MarketEvent] = []
        threshold_1h = self.config.probability_shift_threshold_1h

        for platform, markets in markets_by_platform.items():
            for market in markets:
                market_id = market.get("id", "")
                prev = self._prev_state.get(market_id)
                if not prev:
                    continue

                current_yes = market.get("yes_price", 0.0)
                prev_yes = prev.get("yes_price", current_yes)
                shift = abs(current_yes - prev_yes)

                if shift >= threshold_1h:
                    direction = "up" if current_yes > prev_yes else "down"
                    priority = EventPriority.HIGH if shift >= threshold_1h * 2 else EventPriority.MEDIUM

                    events.append(
                        MarketEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.PROBABILITY_SHIFT,
                            priority=priority,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            market_id=market_id,
                            market_name=market.get("title", "Unknown"),
                            platform=platform,
                            data={
                                "prev_yes_price": round(prev_yes, 4),
                                "current_yes_price": round(current_yes, 4),
                                "shift": round(shift, 4),
                                "direction": direction,
                            },
                            confidence=80.0,
                            message=(
                                f"Probability {direction} {shift * 100:.1f}%: "
                                f"{prev_yes:.3f} → {current_yes:.3f}"
                            ),
                        )
                    )

        return events

    async def _detect_volume_spikes(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """Detect abnormal volume spikes."""
        events: List[MarketEvent] = []
        multiplier = self.config.volume_spike_multiplier

        for platform, markets in markets_by_platform.items():
            for market in markets:
                market_id = market.get("id", "")
                prev = self._prev_state.get(market_id)
                if not prev:
                    continue

                current_vol = market.get("volume", 0.0)
                prev_vol = prev.get("volume", 0.0)

                if prev_vol > 0 and current_vol >= prev_vol * multiplier:
                    ratio = current_vol / prev_vol

                    events.append(
                        MarketEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.VOLUME_SPIKE,
                            priority=EventPriority.MEDIUM,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            market_id=market_id,
                            market_name=market.get("title", "Unknown"),
                            platform=platform,
                            data={
                                "prev_volume": round(prev_vol, 2),
                                "current_volume": round(current_vol, 2),
                                "ratio": round(ratio, 2),
                            },
                            confidence=75.0,
                            message=(
                                f"Volume spike {ratio:.1f}x: "
                                f"${prev_vol:,.0f} → ${current_vol:,.0f}"
                            ),
                        )
                    )

        return events

    async def _detect_resolutions(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """Detect markets that have resolved/settled."""
        events: List[MarketEvent] = []

        for platform, markets in markets_by_platform.items():
            for market in markets:
                market_id = market.get("id", "")
                prev = self._prev_state.get(market_id)
                if not prev:
                    continue

                current_status = str(market.get("status", "")).lower()
                prev_status = str(prev.get("status", "active")).lower()

                if prev_status == "active" and current_status in ("settled", "resolved", "closed"):
                    events.append(
                        MarketEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.MARKET_RESOLUTION,
                            priority=EventPriority.HIGH,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            market_id=market_id,
                            market_name=market.get("title", "Unknown"),
                            platform=platform,
                            data={
                                "prev_status": prev_status,
                                "current_status": current_status,
                                "final_yes_price": market.get("yes_price", 0.0),
                            },
                            confidence=99.0,
                            message=f"Market resolved: {current_status}",
                        )
                    )

        return events

    async def _detect_price_alerts(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """
        Check user-configured price alert rules against current market data.
        @requirement: REQ-ALERT-004 - Price alert rules
        """
        events: List[MarketEvent] = []

        for rule in self.config.price_alerts:
            if not rule.get("active", True):
                continue

            asset = rule.get("asset", "").upper()
            target = float(rule.get("target_price", 0))
            direction = rule.get("direction", "above")

            for platform, markets in markets_by_platform.items():
                for market in markets:
                    title = market.get("title", "").upper()
                    if asset not in title:
                        continue

                    current_price = market.get("yes_price", 0.0)
                    triggered = (
                        (direction == "above" and current_price >= target)
                        or (direction == "below" and current_price <= target)
                    )

                    if triggered:
                        events.append(
                            MarketEvent(
                                event_id=str(uuid.uuid4()),
                                event_type=EventType.PRICE_ALERT,
                                priority=EventPriority.MEDIUM,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                market_id=market.get("id", ""),
                                market_name=market.get("title", "Unknown"),
                                platform=platform,
                                data={
                                    "alert_id": rule.get("alert_id"),
                                    "asset": asset,
                                    "target_price": target,
                                    "current_price": current_price,
                                    "direction": direction,
                                },
                                confidence=99.0,
                                message=(
                                    f"Price alert: {asset} is {direction} {target:.3f} "
                                    f"(current: {current_price:.3f})"
                                ),
                            )
                        )

        return events

    async def _detect_new_markets(
        self, markets_by_platform: Dict[str, List[Dict[str, Any]]]
    ) -> List[MarketEvent]:
        """Detect newly created markets not seen in previous state."""
        events: List[MarketEvent] = []

        for platform, markets in markets_by_platform.items():
            for market in markets:
                market_id = market.get("id", "")
                if market_id and market_id not in self._prev_state:
                    events.append(
                        MarketEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.NEW_MARKET,
                            priority=EventPriority.LOW,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            market_id=market_id,
                            market_name=market.get("title", "Unknown"),
                            platform=platform,
                            data={
                                "yes_price": market.get("yes_price", 0.0),
                                "volume": market.get("volume", 0.0),
                            },
                            confidence=99.0,
                            message=f"New market detected: {market.get('title', 'Unknown')}",
                        )
                    )

        return events
