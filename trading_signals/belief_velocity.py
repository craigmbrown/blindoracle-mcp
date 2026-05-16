"""
Belief Velocity Correlator — pure math, no LLM.

On each SignalEvent, takes a T0 probability snapshot for matched markets,
then re-polls at T+15, T+30, T+60 minutes to compute velocity.

velocity = (prob_T60 - prob_T0) / 60  (% per minute)

Fires NEWS_TRIGGER event when |velocity| > VELOCITY_THRESHOLD.

Writes to data/belief_changes.jsonl (append-only).

Usage:
    from trading_signals.belief_velocity import BeliefVelocityTracker
    tracker = BeliefVelocityTracker()
    # On signal event:
    tracker.start_tracking(signal_event, matched_markets)
    # Later (run in loop):
    completed = await tracker.process_pending()
"""

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)

DATA_DIR = Path("/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/data")
BELIEF_LOG = DATA_DIR / "belief_changes.jsonl"
PENDING_FILE = DATA_DIR / "belief_pending.json"

VELOCITY_THRESHOLD = 1.5  # %/min — triggers NEWS_TRIGGER event
SNAPSHOT_WINDOWS = [0, 15, 30, 60]  # minutes after signal


@dataclass
class ProbSnapshot:
    window_min: int
    prob: float
    polled_at: str


@dataclass
class BeliefChange:
    tracking_id: str
    signal_id: str
    signal_headline: str
    platform: str
    market_id: str
    market_title: str
    prob_T0: float
    prob_T15: Optional[float]
    prob_T30: Optional[float]
    prob_T60: Optional[float]
    velocity_pct_per_min: Optional[float]    # (T60 - T0) / 60
    velocity_pct_per_min_T30: Optional[float]  # early read: (T30 - T0) / 30
    triggered_alert: bool = False
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    snapshots: List[Dict] = field(default_factory=list)


@dataclass
class PendingTrack:
    tracking_id: str
    signal_id: str
    signal_headline: str
    platform: str
    market_id: str
    market_title: str
    prob_T0: float
    started_at_ts: float      # unix timestamp
    snapshots: List[Dict] = field(default_factory=list)
    next_window_idx: int = 1  # index into SNAPSHOT_WINDOWS (0 = T0 already taken)


class BeliefVelocityTracker:

    def __init__(self, on_velocity_alert: Optional[Callable] = None):
        """
        on_velocity_alert: callback(belief_change: BeliefChange) called when
                           |velocity| > VELOCITY_THRESHOLD.
        """
        self.on_velocity_alert = on_velocity_alert
        self._pending: List[PendingTrack] = []
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_pending()

    def _load_pending(self):
        if PENDING_FILE.exists():
            try:
                data = json.loads(PENDING_FILE.read_text())
                self._pending = [PendingTrack(**p) for p in data.get("pending", [])]
                logger.info(f"[belief_velocity] Loaded {len(self._pending)} pending tracks")
            except Exception as e:
                logger.warning(f"[belief_velocity] Could not load pending: {e}")

    def _save_pending(self):
        PENDING_FILE.write_text(json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pending": [asdict(p) for p in self._pending],
        }, indent=2))

    def _get_current_prob(self, platform: str, market_id: str) -> Optional[float]:
        """Fetch current probability from Kalshi or Polymarket."""
        import sys
        sys.path.insert(0, "/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced")
        try:
            loop = asyncio.get_event_loop()

            if platform.lower() == "kalshi":
                from prediction_markets.kalshi_client import KalshiClient
                client = KalshiClient()
                markets = loop.run_until_complete(client.get_markets(limit=200))
                for m in markets:
                    if m.market_id == market_id:
                        return m.probability
            elif platform.lower() == "polymarket":
                from prediction_markets.polymarket_client import PolymarketClient
                client = PolymarketClient()
                markets = loop.run_until_complete(client.get_markets(limit=200))
                for m in markets:
                    if m.market_id == market_id:
                        return m.probability
        except Exception as e:
            logger.warning(f"[belief_velocity] Could not fetch prob for {platform}/{market_id}: {e}")
        return None

    def start_tracking(self, signal_id: str, signal_headline: str,
                       platform: str, market_id: str, market_title: str,
                       prob_T0: float) -> str:
        """
        Begin tracking a market after a signal event.
        Returns tracking_id.
        """
        import hashlib
        tracking_id = hashlib.sha256(
            f"{signal_id}:{platform}:{market_id}".encode()
        ).hexdigest()[:12]

        track = PendingTrack(
            tracking_id=tracking_id,
            signal_id=signal_id,
            signal_headline=signal_headline,
            platform=platform,
            market_id=market_id,
            market_title=market_title,
            prob_T0=prob_T0,
            started_at_ts=time.time(),
            snapshots=[{"window_min": 0, "prob": prob_T0,
                        "polled_at": datetime.now(timezone.utc).isoformat()}],
            next_window_idx=1,
        )
        self._pending.append(track)
        self._save_pending()
        logger.info(f"[belief_velocity] Tracking started: {market_title[:50]} "
                    f"T0={prob_T0:.3f} signal={signal_id}")
        return tracking_id

    def start_tracking_from_signal(self, signal_event, markets: List[Dict]):
        """
        Convenience: start tracking all matched markets from a SignalEvent.
        Fetches T0 probability and starts tracking each matched market.
        """
        ids = []
        for m in markets[:5]:  # limit to 5 markets per signal
            prob_t0 = m.get("current_prob", 0.5)
            # Try to get fresher prob from live API
            live_prob = self._get_current_prob(m.get("platform", ""), m.get("market_id", ""))
            prob_t0 = live_prob if live_prob is not None else prob_t0

            tid = self.start_tracking(
                signal_id=signal_event.signal_id,
                signal_headline=signal_event.headline,
                platform=m.get("platform", "unknown"),
                market_id=m.get("market_id", m.get("id", "")),
                market_title=m.get("market", m.get("title", "")),
                prob_T0=prob_t0,
            )
            ids.append(tid)
        return ids

    def process_pending(self) -> List[BeliefChange]:
        """
        Check all pending tracks. For any that have reached a snapshot window,
        poll the market and record the snapshot. Complete tracks at T+60.
        Returns list of completed BeliefChange objects.
        """
        now = time.time()
        completed: List[BeliefChange] = []
        still_pending: List[PendingTrack] = []

        for track in self._pending:
            age_min = (now - track.started_at_ts) / 60.0
            modified = False

            # Take snapshots for windows that are due
            while track.next_window_idx < len(SNAPSHOT_WINDOWS):
                target_min = SNAPSHOT_WINDOWS[track.next_window_idx]
                if age_min < target_min:
                    break  # not yet time for this snapshot

                prob = self._get_current_prob(track.platform, track.market_id)
                if prob is not None:
                    track.snapshots.append({
                        "window_min": target_min,
                        "prob": prob,
                        "polled_at": datetime.now(timezone.utc).isoformat(),
                    })
                    logger.info(f"[belief_velocity] T+{target_min}m snapshot: "
                                f"{track.market_title[:40]} prob={prob:.3f}")

                track.next_window_idx += 1
                modified = True

            # Complete if T+60 snapshot has been taken
            if track.next_window_idx >= len(SNAPSHOT_WINDOWS):
                snap_map = {s["window_min"]: s["prob"] for s in track.snapshots}
                p0 = snap_map.get(0, track.prob_T0)
                p15 = snap_map.get(15)
                p30 = snap_map.get(30)
                p60 = snap_map.get(60)

                vel = ((p60 - p0) / 60.0 * 100) if p60 is not None else None
                vel30 = ((p30 - p0) / 30.0 * 100) if p30 is not None else None

                bc = BeliefChange(
                    tracking_id=track.tracking_id,
                    signal_id=track.signal_id,
                    signal_headline=track.signal_headline,
                    platform=track.platform,
                    market_id=track.market_id,
                    market_title=track.market_title,
                    prob_T0=p0,
                    prob_T15=p15,
                    prob_T30=p30,
                    prob_T60=p60,
                    velocity_pct_per_min=round(vel, 4) if vel is not None else None,
                    velocity_pct_per_min_T30=round(vel30, 4) if vel30 is not None else None,
                    triggered_alert=abs(vel) > VELOCITY_THRESHOLD if vel is not None else False,
                    started_at=datetime.fromtimestamp(track.started_at_ts, tz=timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    snapshots=track.snapshots,
                )

                # Persist to log
                with open(BELIEF_LOG, "a") as f:
                    f.write(json.dumps(asdict(bc)) + "\n")

                # Fire alert callback
                if bc.triggered_alert and self.on_velocity_alert:
                    try:
                        self.on_velocity_alert(bc)
                    except Exception as e:
                        logger.error(f"[belief_velocity] Alert callback failed: {e}")

                completed.append(bc)
                logger.info(f"[belief_velocity] COMPLETE: {bc.market_title[:40]} "
                            f"vel={bc.velocity_pct_per_min} alert={bc.triggered_alert}")
            else:
                still_pending.append(track)
                if modified:
                    pass  # will save below

        self._pending = still_pending
        self._save_pending()
        return completed

    def get_recent_velocities(self, limit: int = 20) -> List[Dict]:
        """Read last N completed belief changes from log."""
        if not BELIEF_LOG.exists():
            return []
        lines = BELIEF_LOG.read_text().strip().splitlines()
        results = []
        for line in reversed(lines[-limit * 2:]):
            try:
                results.append(json.loads(line))
            except Exception:
                pass
            if len(results) >= limit:
                break
        return results

    def get_top_movers(self, lookback_hours: int = 2) -> List[Dict]:
        """Return markets with highest |velocity| in last N hours."""
        cutoff_ts = time.time() - lookback_hours * 3600
        records = self.get_recent_velocities(limit=200)
        movers = []
        for r in records:
            vel = r.get("velocity_pct_per_min")
            if vel is None:
                continue
            # Filter by recency
            try:
                started = datetime.fromisoformat(r["started_at"]).timestamp()
                if started < cutoff_ts:
                    continue
            except Exception:
                pass
            movers.append(r)
        movers.sort(key=lambda x: abs(x.get("velocity_pct_per_min", 0)), reverse=True)
        return movers[:10]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", action="store_true", help="Process pending tracks")
    parser.add_argument("--movers", action="store_true", help="Show top movers")
    parser.add_argument("--status", action="store_true", help="Show pending count")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    tracker = BeliefVelocityTracker()

    if args.status:
        print(f"Pending tracks: {len(tracker._pending)}")

    if args.process:
        completed = tracker.process_pending()
        print(f"Completed: {len(completed)} tracks")
        for bc in completed:
            print(f"  {bc.market_title[:50]} vel={bc.velocity_pct_per_min} alert={bc.triggered_alert}")

    if args.movers:
        movers = tracker.get_top_movers()
        print(f"\nTop movers ({len(movers)}):")
        for m in movers:
            vel = m.get("velocity_pct_per_min", 0)
            arrow = "🔴" if vel < -VELOCITY_THRESHOLD else ("🟢" if vel > VELOCITY_THRESHOLD else "⚪")
            print(f"  {arrow} {m['market_title'][:50]:50s} vel={vel:+.3f}%/min")
