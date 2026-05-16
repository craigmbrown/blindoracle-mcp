#!/usr/bin/env python3
"""
Alert History Store
@requirement: REQ-ALERT-006 - Alert history retrieval
@BLP: BLP-021 (Durability through append-only JSONL storage)
"""

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_detector import MarketEvent


class AlertHistoryStore:
    """
    Append-only JSONL store for alert history.
    Follows project pattern (e.g., delegation_proofs.json).
    @requirement: REQ-ALERT-006 - Alert history retrieval
    @BLP: BLP-021 (Durability)
    """

    _DEFAULT_PATH = str(
        Path(__file__).parent.parent / "data" / "alert_history.jsonl"
    )

    def __init__(self, history_path: Optional[str] = None) -> None:
        self.history_path = Path(history_path or self._DEFAULT_PATH)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"✅ AlertHistoryStore initialized: {self.history_path}")

    def record(self, event: MarketEvent, delivery_report: Optional[Dict[str, Any]] = None) -> None:
        """
        Append an event + optional delivery report to history.
        Failures are logged but do not raise exceptions.
        """
        try:
            record = {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "priority": event.priority.value,
                "timestamp": event.timestamp,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "market_id": event.market_id,
                "market_name": event.market_name,
                "platform": event.platform,
                "confidence": event.confidence,
                "message": event.message,
                "data": event.data,
                "action_url": event.action_url,
                "delivery": delivery_report or {},
            }
            with open(self.history_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"❌ AlertHistoryStore.record failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")

    def get_history(
        self,
        limit: int = 20,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return the N most recent alert history records, newest first.
        Optionally filter by event_type string.
        @requirement: REQ-ALERT-006 - History retrieval with filtering
        """
        try:
            if not self.history_path.exists():
                return []

            records: List[Dict[str, Any]] = []
            with open(self.history_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if event_type is None or record.get("event_type") == event_type:
                            records.append(record)
                    except json.JSONDecodeError:
                        continue

            # Return newest first, up to limit
            return list(reversed(records[-limit * 3:]))[:limit]

        except Exception as e:
            print(f"❌ AlertHistoryStore.get_history failed: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics over all stored records."""
        try:
            if not self.history_path.exists():
                return {"total": 0, "by_type": {}, "by_priority": {}}

            total = 0
            by_type: Dict[str, int] = {}
            by_priority: Dict[str, int] = {}

            with open(self.history_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        total += 1
                        et = record.get("event_type", "unknown")
                        ep = record.get("priority", "unknown")
                        by_type[et] = by_type.get(et, 0) + 1
                        by_priority[ep] = by_priority.get(ep, 0) + 1
                    except json.JSONDecodeError:
                        continue

            return {"total": total, "by_type": by_type, "by_priority": by_priority}

        except Exception as e:
            print(f"❌ AlertHistoryStore.get_stats failed: {e}")
            return {"total": 0, "by_type": {}, "by_priority": {}, "error": str(e)}
