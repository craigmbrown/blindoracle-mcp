# trading_signals/nostr_publisher.py
# REQ-SIGNALS-007: Publish high-confidence trading signals to NOSTR
# BLP-011: Autonomy — signals self-publish without operator intervention

"""
Thin adapter that wraps core/nostr_integration.NostrPublisher to publish
TradingSignal objects as NIP-01 kind-1 text notes.

Design decisions:
- Gate: only publish when signal.confidence >= min_confidence (default 75)
- Fire-and-forget: failures are logged but never raise (signals saved to SQLite regardless)
- Event kind 1 (short text note) with #t tags for asset ticker and signal type
- Reuses existing core/nostr_integration.py — no duplicate relay/key management
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional


# Confidence threshold below which signals are NOT published to NOSTR
_DEFAULT_MIN_CONFIDENCE = 75.0

# NOSTR private key env var (optional — generates ephemeral key if absent)
_NOSTR_PRIVATE_KEY_ENV = "NOSTR_PRIVATE_KEY_HEX"


def _format_signal_note(signal: Any) -> str:
    """
    Format a TradingSignal as a human-readable NOSTR note.

    REQ-SIGNALS-007: Content must be informative but not financial advice.
    """
    asset = getattr(signal, "asset", "UNKNOWN")
    signal_type = getattr(signal, "signal_type", "hold").upper()
    confidence = getattr(signal, "confidence", 0.0)
    risk_level = getattr(signal, "risk_level", "medium")
    reasoning = getattr(signal, "reasoning", "")
    timestamp = getattr(signal, "timestamp", datetime.now(timezone.utc).isoformat())
    signal_id = getattr(signal, "signal_id", "")

    # Emoji mapping
    type_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal_type, "⚪")
    risk_emoji = {"low": "🔵", "medium": "🟠", "high": "🔴"}.get(risk_level, "⚪")

    return (
        f"{type_emoji} Trading Signal: {signal_type} {asset}\n\n"
        f"Confidence: {confidence:.1f}%\n"
        f"Risk Level: {risk_emoji} {risk_level.upper()}\n"
        f"Reasoning: {reasoning}\n\n"
        f"Signal ID: {signal_id[:8]}...\n"
        f"Generated: {timestamp}\n\n"
        f"⚠️ Not financial advice. DYOR.\n\n"
        f"#TradingSignals #{asset} #{'PredictionMarkets'} #BlindOracle"
    )


class TradingSignalNostrPublisher:
    """
    REQ-SIGNALS-007: Publish high-confidence TradingSignals to NOSTR relays.

    Wraps core.nostr_integration.NostrPublisher. If the NOSTR dependencies
    (coincurve, websockets) are not installed, publish() degrades gracefully
    and logs a warning — signals are always saved to SQLite regardless.

    Usage:
        publisher = TradingSignalNostrPublisher(min_confidence=75.0)
        event_id = await publisher.publish_signal(signal)
    """

    def __init__(
        self,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        relay_urls: Optional[list] = None,
        private_key_hex: Optional[str] = None,
    ) -> None:
        self.min_confidence = min_confidence
        self.relay_urls = relay_urls
        self.private_key_hex = private_key_hex or os.environ.get(_NOSTR_PRIVATE_KEY_ENV)
        self._publisher = None  # Lazy-initialized on first publish

    def _get_publisher(self) -> Optional[Any]:
        """Lazy-initialize the underlying NostrPublisher. Returns None on import failure."""
        if self._publisher is not None:
            return self._publisher
        try:
            import sys
            import os as _os
            # Ensure the MCP package root is on sys.path
            pkg_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if pkg_root not in sys.path:
                sys.path.insert(0, pkg_root)

            from core.nostr_integration import NostrPublisher

            self._publisher = NostrPublisher(
                private_key_hex=self.private_key_hex,
                relay_urls=self.relay_urls,
            )
            return self._publisher
        except ImportError as e:
            print(f"[TradingSignalNostrPublisher] NOSTR dependencies not available: {e}")
            return None
        except Exception as e:
            print(f"[TradingSignalNostrPublisher] Failed to initialize NostrPublisher: {e}")
            return None

    async def publish_signal(self, signal: Any) -> Optional[str]:
        """
        Publish a TradingSignal to NOSTR if confidence >= min_confidence.

        Args:
            signal: TradingSignal dataclass instance.

        Returns:
            NOSTR event_id string if published, None if below threshold or on failure.

        REQ-SIGNALS-007: Gate on confidence, fire-and-forget on relay errors.
        BLP-011: Autonomy — no operator action required to distribute signals.
        """
        confidence = getattr(signal, "confidence", 0.0)
        asset = getattr(signal, "asset", "UNKNOWN")
        signal_type = getattr(signal, "signal_type", "hold")

        if confidence < self.min_confidence:
            print(
                f"[TradingSignalNostrPublisher] Skipping {asset} {signal_type} "
                f"({confidence:.1f}% < {self.min_confidence}% threshold)"
            )
            return None

        publisher = self._get_publisher()
        if publisher is None:
            print(
                f"[TradingSignalNostrPublisher] NOSTR unavailable — "
                f"signal {getattr(signal, 'signal_id', '')[:8]} not published"
            )
            return None

        try:
            content = _format_signal_note(signal)
            tags = [
                ["t", asset.lower()],
                ["t", signal_type.lower()],
                ["t", "trading-signals"],
                ["t", "blindoracle"],
            ]

            # Use the core publisher's low-level event construction
            from core.nostr_integration import NostrEvent

            event = NostrEvent(
                pubkey=publisher.public_key_hex,
                kind=1,
                content=content,
                tags=tags,
            )
            event.sig = publisher._sign_event(event)
            results = await publisher._publish_to_relays(event)

            successes = sum(1 for r in results.values() if r.get("success"))
            if successes > 0:
                print(
                    f"[TradingSignalNostrPublisher] Published {asset} {signal_type} "
                    f"to {successes}/{len(results)} relays — event {event.id[:16]}..."
                )
                return event.id
            else:
                print(
                    f"[TradingSignalNostrPublisher] All relays rejected signal "
                    f"{asset} {signal_type}: {results}"
                )
                return None

        except Exception as e:
            # Fire-and-forget: log but never raise so scheduler continues
            print(f"[TradingSignalNostrPublisher] Publish error for {asset}: {e}")
            return None
