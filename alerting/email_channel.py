#!/usr/bin/env python3
"""
Email Digest Alert Channel
@requirement: REQ-ALERT-005 - Multi-channel routing (email implementation)
@BLP: BLP-011 (Autonomy through automated delivery)

Gap G2 fix: implements email digest for LOW/MEDIUM priority alerts.
Uses scripts/unified_email_responder.py + email_templates/dynamic_email_composer.py
per project email standards.

Policy:
- Only LOW and MEDIUM priority events are batched and sent via email.
- CRITICAL / HIGH events go to WhatsApp / NOSTR respectively (see router.py).
- When batch_low_priority=True, events are accumulated and flushed on
  send_digest() call (intended to be called on a schedule, e.g. daily).
- When batch_low_priority=False, each event is sent immediately.
"""

import json
import os
import subprocess
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on path for email utilities
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from .config import AlertConfig
from .event_detector import EventPriority, EventType, MarketEvent
from .router import AlertChannel


class EmailChannel(AlertChannel):
    """
    Email alert channel using the project's dynamic email composer.

    Accepts LOW and MEDIUM events only (CRITICAL/HIGH go to WhatsApp/NOSTR).
    Supports immediate send or batched digest mode (controlled by
    config.batch_low_priority).

    @requirement: REQ-ALERT-005 - Email channel routing
    @BLP: BLP-011 (Autonomy)
    """

    # Priorities that this channel handles
    _HANDLED_PRIORITIES = {EventPriority.LOW, EventPriority.MEDIUM}

    def __init__(self, config: AlertConfig) -> None:
        self.config = config
        self._batch: List[MarketEvent] = []
        self._recipient_email = os.getenv(
            "ALERT_EMAIL_RECIPIENT", os.environ.get("BLINDORACLE_OPERATOR_EMAIL", "operator@example.com")
        )
        self._composer_path = str(
            _PROJECT_ROOT / "email_templates" / "dynamic_email_composer.py"
        )
        self._responder_path = str(
            _PROJECT_ROOT / "scripts" / "unified_email_responder.py"
        )
        print(f"✅ EmailChannel initialized (recipient={self._recipient_email})")

    async def send(self, event: MarketEvent) -> bool:
        """
        Send or batch-queue an alert event.

        CRITICAL and HIGH events are silently ignored (handled by other channels).
        LOW/MEDIUM events are batched when batch_low_priority=True, else sent immediately.
        """
        if event.priority not in self._HANDLED_PRIORITIES:
            # Not this channel's responsibility
            return True

        if self.config.batch_low_priority:
            self._batch.append(event)
            print(
                f"ℹ️ EmailChannel: event batched ({len(self._batch)} pending)"
                f" [{event.event_type.value}]"
            )
            return True
        else:
            return await self._send_single(event)

    async def send_digest(self) -> bool:
        """
        Flush the current batch as a single digest email.
        Call this on a schedule (e.g., daily at 08:00).

        Returns True if digest was sent (or batch was empty), False on error.
        """
        if not self._batch:
            print("ℹ️ EmailChannel: digest called with empty batch, skipping")
            return True

        events = list(self._batch)
        self._batch.clear()

        subject = self._make_digest_subject(events)
        body_html = self._make_digest_html(events)

        success = self._send_email(subject, body_html)
        if success:
            print(f"✅ EmailChannel: digest sent ({len(events)} events)")
        else:
            print(f"❌ EmailChannel: digest send failed, {len(events)} events dropped")
        return success

    async def _send_single(self, event: MarketEvent) -> bool:
        """Send a single event immediately as an email."""
        subject = self._make_single_subject(event)
        body_html = self._make_single_html(event)
        success = self._send_email(subject, body_html)
        if success:
            print(f"✅ EmailChannel: immediate email sent [{event.event_type.value}]")
        return success

    def _send_email(self, subject: str, body_html: str) -> bool:
        """
        Invoke the unified_email_responder to send the email.
        Falls back gracefully on error.
        """
        try:
            python_bin = sys.executable
            cmd = [
                python_bin,
                self._responder_path,
                "send",
                "--to", self._recipient_email,
                "--subject", subject,
                "--body", body_html,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(_PROJECT_ROOT),
            )
            if result.returncode == 0:
                return True
            print(
                f"⚠️ EmailChannel: responder exited {result.returncode}: "
                f"{result.stderr[:200]}"
            )
            return False
        except FileNotFoundError:
            # Responder script not present — log and degrade gracefully
            print(
                f"⚠️ EmailChannel: unified_email_responder.py not found at "
                f"{self._responder_path}; email dropped"
            )
            return False
        except subprocess.TimeoutExpired:
            print("⚠️ EmailChannel: email send timed out after 30s")
            return False
        except Exception as e:
            print(f"⚠️ EmailChannel: unexpected error: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return False

    # -------------------------------------------------------------------------
    # HTML formatting helpers
    # -------------------------------------------------------------------------

    _PRIORITY_EMOJI: Dict[EventPriority, str] = {
        EventPriority.CRITICAL: "🚨",
        EventPriority.HIGH: "⚠️",
        EventPriority.MEDIUM: "ℹ️",
        EventPriority.LOW: "📝",
    }

    _TYPE_EMOJI: Dict[EventType, str] = {
        EventType.ARBITRAGE_OPPORTUNITY: "💰",
        EventType.PROBABILITY_SHIFT: "📊",
        EventType.VOLUME_SPIKE: "📈",
        EventType.MARKET_RESOLUTION: "✅",
        EventType.PRICE_ALERT: "🎯",
        EventType.NEW_MARKET: "🆕",
    }

    def _make_single_subject(self, event: MarketEvent) -> str:
        emoji = self._TYPE_EMOJI.get(event.event_type, "📌")
        label = event.event_type.value.replace("_", " ").title()
        return f"{emoji} BlindOracle Alert: {label} — {event.market_name[:50]}"

    def _make_digest_subject(self, events: List[MarketEvent]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"📊 BlindOracle Daily Digest ({len(events)} alerts) — {ts}"

    def _make_single_html(self, event: MarketEvent) -> str:
        """Green-on-black HTML for a single event (project email theme)."""
        p_emoji = self._PRIORITY_EMOJI.get(event.priority, "📌")
        t_emoji = self._TYPE_EMOJI.get(event.event_type, "📌")
        label = event.event_type.value.replace("_", " ").upper()
        data_rows = "".join(
            f"<tr><td style='padding:4px 8px;color:#808080'>{k}</td>"
            f"<td style='padding:4px 8px;color:#00ff41'>{v}</td></tr>"
            for k, v in event.data.items()
        )
        action = (
            f"<p style='margin-top:16px'>"
            f"<a href='{event.action_url}' style='color:#00ff41'>{event.action_url}</a></p>"
            if event.action_url else ""
        )
        return f"""
<html><body style="background:#0a0a0a;color:#00ff41;font-family:monospace;font-size:18px;padding:24px">
  <h2 style="color:#00ff41;border-bottom:1px solid #00ff41;padding-bottom:8px">
    {p_emoji} {t_emoji} {label}
  </h2>
  <p style="font-size:16px;color:#b0b0b0">{event.message}</p>
  <table style="border-collapse:collapse;margin-top:12px">
    <tr><td style="padding:4px 8px;color:#808080">Market</td>
        <td style="padding:4px 8px;color:#00ff41">{event.market_name}</td></tr>
    <tr><td style="padding:4px 8px;color:#808080">Platform</td>
        <td style="padding:4px 8px;color:#00ff41">{event.platform}</td></tr>
    <tr><td style="padding:4px 8px;color:#808080">Confidence</td>
        <td style="padding:4px 8px;color:#00ff41">{event.confidence:.0f}%</td></tr>
    <tr><td style="padding:4px 8px;color:#808080">Time</td>
        <td style="padding:4px 8px;color:#00ff41">{event.timestamp[:19]} UTC</td></tr>
    {data_rows}
  </table>
  {action}
  <p style="margin-top:24px;font-size:14px;color:#404040">BlindOracle Prediction Markets — auto-generated</p>
</body></html>
""".strip()

    def _make_digest_html(self, events: List[MarketEvent]) -> str:
        """Green-on-black HTML digest of multiple events."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Group by event type for clarity
        by_type: Dict[str, List[MarketEvent]] = defaultdict(list)
        for ev in events:
            by_type[ev.event_type.value].append(ev)

        sections = []
        for etype, evs in sorted(by_type.items()):
            t_emoji = self._TYPE_EMOJI.get(
                EventType(etype), "📌"
            ) if etype in [e.value for e in EventType] else "📌"
            label = etype.replace("_", " ").title()
            rows = ""
            for ev in evs:
                p_emoji = self._PRIORITY_EMOJI.get(ev.priority, "📌")
                rows += (
                    f"<tr>"
                    f"<td style='padding:6px 10px;color:#808080'>{ev.timestamp[:16]}</td>"
                    f"<td style='padding:6px 10px;color:#00ff41'>{p_emoji} {ev.market_name[:60]}</td>"
                    f"<td style='padding:6px 10px;color:#b0b0b0'>{ev.platform}</td>"
                    f"<td style='padding:6px 10px;color:#b0b0b0'>{ev.confidence:.0f}%</td>"
                    f"<td style='padding:6px 10px;color:#e0e0e0'>{ev.message[:80]}</td>"
                    f"</tr>"
                )
            sections.append(f"""
  <h3 style="color:#00ff41;margin-top:24px">{t_emoji} {label} ({len(evs)})</h3>
  <table style="border-collapse:collapse;width:100%">
    <tr style="border-bottom:1px solid #404040">
      <th style="padding:6px 10px;text-align:left;color:#808080">Time</th>
      <th style="padding:6px 10px;text-align:left;color:#808080">Market</th>
      <th style="padding:6px 10px;text-align:left;color:#808080">Platform</th>
      <th style="padding:6px 10px;text-align:left;color:#808080">Conf</th>
      <th style="padding:6px 10px;text-align:left;color:#808080">Message</th>
    </tr>
    {rows}
  </table>""")

        body = "\n".join(sections)
        return f"""
<html><body style="background:#0a0a0a;color:#00ff41;font-family:monospace;font-size:16px;padding:24px">
  <h2 style="color:#00ff41;border-bottom:1px solid #00ff41;padding-bottom:8px">
    📊 BlindOracle Daily Alert Digest
  </h2>
  <p style="color:#808080">{ts} — {len(events)} alert(s)</p>
  {body}
  <p style="margin-top:32px;font-size:14px;color:#404040">BlindOracle Prediction Markets — auto-generated digest</p>
</body></html>
""".strip()
