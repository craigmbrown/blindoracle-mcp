# REQ-TMPL-003: TemplateRegistry — CRUD + atomic JSON persistence
# REQ-TMPL-004: Template search with relevance scoring
# @BLP-021: Durability — atomic JSON persistence with version history preserved
# @BLP-051: Self-Organization — catalog auto-organizes; featured templates emerge from usage

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.agent_templates import AgentTemplate, TemplateCategory, TemplateStatus

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TemplateRegistry:
    """
    REQ-TMPL-003: Central CRUD store for AgentTemplate objects.

    Persists to data/agent_templates.json using the same atomic tmp-rename
    pattern as MarketplaceService._save_listings() for crash-safe writes.

    REQ-TMPL-004: Search results are scored by:
        score = downloads * 0.4 + (rating or 0) * 0.3 + recency * 0.3
    where recency decays from 1.0 (< 7 days) to 0.1 (> 90 days).
    """

    DEFAULT_DATA_FILE = _PROJECT_ROOT / "data" / "agent_templates.json"

    def __init__(self, data_file: Optional[Path] = None) -> None:
        self.data_file = data_file or self.DEFAULT_DATA_FILE
        self._templates: Dict[str, AgentTemplate] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """REQ-TMPL-003: Load templates from JSON file, or create empty file."""
        if self.data_file.exists():
            try:
                raw = json.loads(self.data_file.read_text())
                for item in raw:
                    try:
                        tmpl = AgentTemplate(**item)
                        self._templates[tmpl.template_id] = tmpl
                    except Exception as exc:
                        logger.warning("Skipping corrupt template entry: %s", exc)
                logger.info(
                    "TemplateRegistry loaded %d templates from %s",
                    len(self._templates),
                    self.data_file,
                )
            except Exception as exc:
                logger.error("Failed to load templates from %s: %s", self.data_file, exc)
                self._templates = {}
        else:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self._save()

    def _save(self) -> None:
        """REQ-TMPL-003: Atomic write via tmp-rename (crash-safe)."""
        tmp = self.data_file.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(
                    [t.model_dump() for t in self._templates.values()],
                    f,
                    indent=4,
                    default=str,
                )
            shutil.move(str(tmp), str(self.data_file))
        except Exception as exc:
            logger.error("Failed to save templates: %s", exc)
        finally:
            if tmp.exists():
                tmp.unlink()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, template: AgentTemplate) -> AgentTemplate:
        """
        REQ-TMPL-003: Persist a new template.

        Raises ValueError if template_id already exists to prevent silent overwrites.
        """
        if template.template_id in self._templates:
            raise ValueError(
                f"Template '{template.template_id}' already exists. "
                "Use update() to modify existing templates."
            )
        self._templates[template.template_id] = template
        self._save()
        logger.info("Created template: %s (%s)", template.template_id, template.name)
        return template

    def get(self, template_id: str) -> Optional[AgentTemplate]:
        """REQ-TMPL-003: Retrieve a template by ID. Returns None if not found."""
        return self._templates.get(template_id)

    def update(self, template_id: str, **kwargs: Any) -> AgentTemplate:
        """
        REQ-TMPL-003: Partial update of an existing template.

        Always sets updated_at to now.  Raises ValueError if template not found.
        """
        tmpl = self._templates.get(template_id)
        if tmpl is None:
            raise ValueError(f"Template '{template_id}' not found.")

        data = tmpl.model_dump()
        data.update(kwargs)
        data["updated_at"] = datetime.now()

        updated = AgentTemplate(**data)
        self._templates[template_id] = updated
        self._save()
        logger.info("Updated template: %s", template_id)
        return updated

    def delete(self, template_id: str) -> None:
        """
        REQ-TMPL-003: Soft-delete by archiving (matches MarketplaceListing pattern).

        Does not remove the record so historical instances remain traceable.
        """
        tmpl = self._templates.get(template_id)
        if tmpl is None:
            raise ValueError(f"Template '{template_id}' not found.")
        tmpl.status = TemplateStatus.ARCHIVED
        tmpl.updated_at = datetime.now()
        self._save()
        logger.info("Archived template: %s", template_id)

    def publish(self, template_id: str) -> AgentTemplate:
        """
        REQ-TMPL-003: Transition a DRAFT or DEPRECATED template to PUBLISHED.

        Enforces trust tier visibility rules (Design D6):
        - trust_tier=1 templates cannot be published publicly.
        """
        tmpl = self._templates.get(template_id)
        if tmpl is None:
            raise ValueError(f"Template '{template_id}' not found.")
        if tmpl.status not in (TemplateStatus.DRAFT, TemplateStatus.DEPRECATED):
            raise ValueError(
                f"Template '{template_id}' cannot be published from status '{tmpl.status}'."
            )
        if tmpl.trust_tier == 1 and tmpl.marketplace_visibility == "public":
            raise ValueError(
                f"Internal (trust_tier=1) template '{template_id}' cannot be published to public catalog."
            )
        tmpl.status = TemplateStatus.PUBLISHED
        tmpl.published_at = datetime.now()
        tmpl.updated_at = datetime.now()
        self._save()
        logger.info("Published template: %s", template_id)
        return tmpl

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_all(self, include_archived: bool = False) -> List[AgentTemplate]:
        """Return all templates, optionally including archived ones."""
        if include_archived:
            return list(self._templates.values())
        return [t for t in self._templates.values() if t.status != TemplateStatus.ARCHIVED]

    # ------------------------------------------------------------------
    # Search (REQ-TMPL-004)
    # ------------------------------------------------------------------

    def search(
        self,
        *,
        category: Optional[TemplateCategory] = None,
        tags: Optional[List[str]] = None,
        max_price: Optional[float] = None,
        visibility: Optional[str] = None,
        cre_use_case: Optional[str] = None,
        author_id: Optional[str] = None,
        status: Optional[TemplateStatus] = None,
        query: Optional[str] = None,
    ) -> List[AgentTemplate]:
        """
        REQ-TMPL-004: Multi-filter search with relevance scoring.

        Scoring formula:
            score = downloads * 0.4 + (rating or 0) * 0.3 + recency * 0.3

        recency:
            < 7 days old  -> 1.0
            < 30 days old -> 0.6
            < 90 days old -> 0.3
            >= 90 days    -> 0.1
        """
        candidates = list(self._templates.values())

        # Filter: skip archived unless explicitly requested
        if status is None:
            candidates = [t for t in candidates if t.status != TemplateStatus.ARCHIVED]
        else:
            candidates = [t for t in candidates if t.status == status]

        if category is not None:
            candidates = [t for t in candidates if t.category == category]

        if tags:
            tag_set = set(tags)
            candidates = [t for t in candidates if tag_set.issubset(set(t.tags))]

        if max_price is not None:
            candidates = [t for t in candidates if t.template_price_usd <= max_price]

        if visibility is not None:
            candidates = [t for t in candidates if t.marketplace_visibility == visibility]

        if cre_use_case is not None:
            candidates = [
                t for t in candidates
                if any(uc.value == cre_use_case for uc in t.cre_use_cases)
            ]

        if author_id is not None:
            candidates = [t for t in candidates if t.author_id == author_id]

        if query:
            q_lower = query.lower()
            candidates = [
                t for t in candidates
                if q_lower in t.name.lower() or q_lower in t.description.lower()
            ]

        # Score and sort
        now = datetime.now()
        scored: List[tuple[float, AgentTemplate]] = []
        for tmpl in candidates:
            age_days = (now - (tmpl.published_at or tmpl.created_at)).days
            if age_days < 7:
                recency = 1.0
            elif age_days < 30:
                recency = 0.6
            elif age_days < 90:
                recency = 0.3
            else:
                recency = 0.1

            score = (
                tmpl.downloads * 0.4
                + (tmpl.rating or 0.0) * 0.3
                + recency * 0.3
            )
            scored.append((score, tmpl))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [tmpl for _, tmpl in scored]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Aggregate metrics for dashboard / monitoring."""
        all_t = list(self._templates.values())
        published = [t for t in all_t if t.status == TemplateStatus.PUBLISHED]
        draft = [t for t in all_t if t.status == TemplateStatus.DRAFT]
        archived = [t for t in all_t if t.status == TemplateStatus.ARCHIVED]
        deprecated = [t for t in all_t if t.status == TemplateStatus.DEPRECATED]

        total_downloads = sum(t.downloads for t in all_t)
        rated = [t for t in all_t if t.rating is not None]
        avg_rating = (
            round(sum(t.rating for t in rated) / len(rated), 2) if rated else None  # type: ignore[arg-type]
        )

        by_category: Dict[str, int] = {}
        for t in all_t:
            by_category[t.category.value] = by_category.get(t.category.value, 0) + 1

        return {
            "total": len(all_t),
            "published": len(published),
            "draft": len(draft),
            "archived": len(archived),
            "deprecated": len(deprecated),
            "total_downloads": total_downloads,
            "avg_rating": avg_rating,
            "by_category": by_category,
            "data_file": str(self.data_file),
        }
