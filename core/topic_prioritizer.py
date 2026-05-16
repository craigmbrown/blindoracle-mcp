"""
Topic Prioritizer — ranks research topics using lifelog insights + V5 memory.

Scoring formula:
    score = log_frequency * (1 / max(days_since_mention, 0.5)) * (1 - memory_confidence)

Topics with high lifelog frequency, recent mentions, and low memory confidence
(not yet well-understood) surface first.

Usage:
    from core.topic_prioritizer import TopicPrioritizer
    tp = TopicPrioritizer()
    topics = tp.get_top_topics(n=5)
    # [{"topic": "ETH regulation", "score": 8.4, "lifelog_count": 3,
    #   "days_since": 0.2, "memory_context": "Prior fade +6pp"}]
"""

import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

LIFELOG_DIR = Path("/home/craigmbrown/Project/Limitless-Lifelog-Manager/research_outputs")
MEMORY_CLAIMS_DIR = Path("/home/craigmbrown/Project/v5_memory/knowledge/claims")
MEMORY_DECISIONS_DIR = Path("/home/craigmbrown/Project/v5_memory/knowledge/decisions")
STATE_FILE = Path("/home/craigmbrown/Project/chainlink-prediction-markets-mcp-enhanced/data/topic_scores.json")

# Known market-relevant topics to seed entity matching
SEED_TOPICS = [
    "ETH", "BTC", "SEC", "ETF", "Chainlink", "DeFi", "crypto regulation",
    "Polymarket", "Kalshi", "prediction market", "stablecoin", "CFTC",
    "Federal Reserve", "interest rates", "inflation", "elections",
    "XRP", "SOL", "LINK", "AVAX", "MATIC",
]


class TopicPrioritizer:
    """
    Reads lifelog daily insight files + V5 memory decisions to score and rank
    research topics for the AutoResearch belief velocity system.
    """

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days
        self._router = None  # lazy init

    def _get_router(self):
        if self._router is None:
            from core.llm_router_client import get_router
            self._router = get_router()
        return self._router

    def _read_lifelog_files(self) -> List[Dict[str, Any]]:
        """Read last N days of lifelog insight files."""
        entries = []
        if not LIFELOG_DIR.exists():
            logger.warning(f"Lifelog dir not found: {LIFELOG_DIR}")
            return entries

        for fpath in sorted(LIFELOG_DIR.glob("daily_insight_full_*.md"), reverse=True):
            # Extract date from filename: daily_insight_full_YYYY-MM-DD.md
            match = re.search(r"(\d{4}-\d{2}-\d{2})", fpath.name)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            age_days = (datetime.now(timezone.utc) - file_date).total_seconds() / 86400
            if age_days > self.lookback_days:
                break

            content = fpath.read_text(errors="replace")
            entries.append({
                "date": match.group(1),
                "age_days": age_days,
                "content": content[:8000],  # cap to avoid huge payloads
                "path": str(fpath),
            })

        logger.info(f"[topic_prioritizer] Loaded {len(entries)} lifelog files")
        return entries

    def _extract_topics_from_lifelog(self, entries: List[Dict]) -> Dict[str, Dict]:
        """
        Use regex seed matching for fast entity detection.
        Falls back to router topic_scoring for richer extraction.
        """
        topic_counts: Dict[str, Dict] = {}

        for entry in entries:
            content_lower = entry["content"].lower()
            age = entry["age_days"]

            # Seed-based fast matching (no LLM cost for common terms)
            for seed in SEED_TOPICS:
                if seed.lower() in content_lower:
                    occurrences = content_lower.count(seed.lower())
                    if seed not in topic_counts:
                        topic_counts[seed] = {"count": 0, "min_age_days": age, "mentions": []}
                    topic_counts[seed]["count"] += occurrences
                    topic_counts[seed]["min_age_days"] = min(topic_counts[seed]["min_age_days"], age)
                    topic_counts[seed]["mentions"].append(entry["date"])

            # Use router for richer topic extraction on recent files (age < 2 days)
            if age < 2.0 and len(entries) > 0:
                try:
                    router = self._get_router()
                    result = router.route(
                        task_type="topic_scoring",
                        prompt=(
                            f"From this daily insight excerpt, extract all market-relevant topics "
                            f"(assets, regulations, events, people, organizations). "
                            f"Return JSON array of strings only.\n\nEXCERPT:\n{entry['content'][:2000]}"
                        ),
                    )
                    # Try to parse JSON from response
                    content = result.get("content", "")
                    json_match = re.search(r'\[.*?\]', content, re.DOTALL)
                    if json_match:
                        extracted = json.loads(json_match.group())
                        for topic in extracted:
                            topic = str(topic).strip()
                            if len(topic) > 1:
                                if topic not in topic_counts:
                                    topic_counts[topic] = {"count": 0, "min_age_days": age, "mentions": []}
                                topic_counts[topic]["count"] += 1
                                topic_counts[topic]["min_age_days"] = min(
                                    topic_counts[topic]["min_age_days"], age)
                except Exception as e:
                    logger.warning(f"[topic_prioritizer] Router topic_scoring failed: {e}")

        return topic_counts

    def _read_memory_decisions(self) -> Dict[str, Dict]:
        """Read V5 memory decisions to get confidence scores per topic."""
        decisions: Dict[str, Dict] = {}

        for dir_path in [MEMORY_DECISIONS_DIR, MEMORY_CLAIMS_DIR]:
            if not dir_path.exists():
                continue
            for fpath in dir_path.glob("*.json"):
                try:
                    data = json.loads(fpath.read_text())
                    topic = data.get("topic") or data.get("entity") or data.get("subject", "")
                    confidence = float(data.get("confidence", 0.5))
                    outcome = data.get("outcome", "")
                    if topic:
                        decisions[topic.lower()] = {
                            "confidence": confidence,
                            "outcome": outcome,
                            "file": fpath.name,
                        }
                except Exception:
                    pass
            # Also check markdown files for memory entries
            for fpath in dir_path.glob("*.md"):
                try:
                    content = fpath.read_text()
                    confidence_match = re.search(r'confidence[:\s]+([0-9.]+)', content, re.I)
                    topic_match = re.search(r'topic[:\s]+(.+)', content, re.I)
                    if topic_match:
                        topic = topic_match.group(1).strip().lower()
                        conf = float(confidence_match.group(1)) if confidence_match else 0.5
                        decisions[topic] = {"confidence": conf, "outcome": "", "file": fpath.name}
                except Exception:
                    pass

        logger.info(f"[topic_prioritizer] Loaded {len(decisions)} memory decisions")
        return decisions

    def _score_topics(
        self,
        topic_counts: Dict[str, Dict],
        memory_decisions: Dict[str, Dict],
    ) -> List[Dict[str, Any]]:
        """Score and sort topics. Returns ranked list."""
        scored = []
        for topic, data in topic_counts.items():
            count = data["count"]
            age = max(data["min_age_days"], 0.1)

            # Memory confidence: high confidence = less need to research (lower priority)
            mem = memory_decisions.get(topic.lower(), {})
            memory_confidence = mem.get("confidence", 0.3)  # default low = worth researching
            memory_context = mem.get("outcome", "") or mem.get("file", "")

            # score = log_frequency × (1 / days_since) × (1 - memory_confidence)
            import math
            score = math.log1p(count) * (1.0 / age) * (1.0 - memory_confidence)

            scored.append({
                "topic": topic,
                "score": round(score, 3),
                "lifelog_count": count,
                "days_since_mention": round(age, 2),
                "memory_confidence": memory_confidence,
                "memory_context": memory_context,
                "recent_dates": data.get("mentions", [])[:3],
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def get_top_topics(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Main entry point. Returns top N topics ranked by score.
        Also persists to STATE_FILE for dashboard consumption.
        """
        entries = self._read_lifelog_files()
        if not entries:
            logger.warning("[topic_prioritizer] No lifelog files found, returning seed topics")
            return [{"topic": t, "score": 1.0, "lifelog_count": 0,
                     "days_since_mention": 999, "memory_confidence": 0.3,
                     "memory_context": "", "recent_dates": []}
                    for t in SEED_TOPICS[:n]]

        topic_counts = self._extract_topics_from_lifelog(entries)
        memory_decisions = self._read_memory_decisions()
        ranked = self._score_topics(topic_counts, memory_decisions)

        top = ranked[:n]

        # Persist for dashboard
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": self.lookback_days,
            "topics": top,
        }, indent=2))

        logger.info(f"[topic_prioritizer] Top topics: {[t['topic'] for t in top[:5]]}")
        return top


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Topic Prioritizer")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    tp = TopicPrioritizer(lookback_days=args.days)
    topics = tp.get_top_topics(n=args.top)
    print(f"\nTop {args.top} topics (lookback={args.days}d):")
    for i, t in enumerate(topics, 1):
        print(f"  {i:2}. [{t['score']:.3f}] {t['topic']:30s} "
              f"mentions={t['lifelog_count']} age={t['days_since_mention']:.1f}d "
              f"mem_conf={t['memory_confidence']:.2f}")
