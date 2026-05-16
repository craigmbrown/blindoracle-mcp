# REQ-TMPL-008: TemplateCatalog — public catalog generation + stats
# REQ-TMPL-009: Bridge to MarketplaceService — sync templates as listings
# @BLP-051: Self-Organization — catalog auto-organizes by category/use-case; featured emerge from usage
# @BLP-052: Self-Organization — A2A manifest export for agent discovery

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.agent_templates import AgentTemplate, TemplateCategory, TemplateStatus
from core.marketplace_templates import CREUseCase, ListingStatus, PricingTier
from core.template_registry import TemplateRegistry

logger = logging.getLogger(__name__)

# Number of featured templates to surface (Design Decision D7)
_FEATURED_COUNT = 10


class TemplateCatalog:
    """
    REQ-TMPL-008: Public catalog of published, non-private agent templates.

    REQ-TMPL-009: Bridges to MarketplaceService by creating MarketplaceListing
    records for each published template (one listing per template, idempotent).

    Design Decision D7: Featured templates are computed (by downloads + rating),
    not manually curated.
    """

    def __init__(
        self,
        registry: TemplateRegistry,
        marketplace_service: Optional[Any] = None,
    ) -> None:
        self.registry = registry
        self.marketplace_service = marketplace_service

    # ------------------------------------------------------------------
    # Public catalog (REQ-TMPL-008)
    # ------------------------------------------------------------------

    def generate_public_catalog(self) -> List[Dict[str, Any]]:
        """
        REQ-TMPL-008: Return a list of catalog entries for all published,
        non-private templates.

        Each entry is the result of AgentTemplate.to_catalog_entry() with
        source_template and author_id stripped (IP + privacy protection).
        """
        catalog: List[Dict[str, Any]] = []
        for tmpl in self.registry.list_all():
            if tmpl.status != TemplateStatus.PUBLISHED:
                continue
            if tmpl.marketplace_visibility == "private":
                continue
            entry = tmpl.to_catalog_entry()
            catalog.append(entry)

        # Sort by composite score descending (downloads, rating, recency)
        def _score(entry: Dict[str, Any]) -> float:
            published_at_raw = entry.get("published_at") or entry.get("created_at")
            try:
                if isinstance(published_at_raw, str):
                    pub_dt = datetime.fromisoformat(published_at_raw)
                elif isinstance(published_at_raw, datetime):
                    pub_dt = published_at_raw
                else:
                    pub_dt = datetime.now()
            except Exception:
                pub_dt = datetime.now()

            age_days = max(0, (datetime.now() - pub_dt).days)
            if age_days < 7:
                recency = 1.0
            elif age_days < 30:
                recency = 0.6
            elif age_days < 90:
                recency = 0.3
            else:
                recency = 0.1

            downloads = entry.get("downloads", 0) or 0
            rating = entry.get("rating") or 0.0
            return downloads * 0.4 + rating * 0.3 + recency * 0.3

        catalog.sort(key=_score, reverse=True)
        return catalog

    def get_featured(self) -> List[AgentTemplate]:
        """
        Design D7: Return top N templates by (downloads * 0.4 + rating * 0.3 + recency * 0.3).
        Only published, non-private templates qualify.
        """
        published = [
            t
            for t in self.registry.list_all()
            if t.status == TemplateStatus.PUBLISHED
            and t.marketplace_visibility != "private"
        ]

        def _score(t: AgentTemplate) -> float:
            pub_dt = t.published_at or t.created_at
            age_days = max(0, (datetime.now() - pub_dt).days)
            if age_days < 7:
                recency = 1.0
            elif age_days < 30:
                recency = 0.6
            elif age_days < 90:
                recency = 0.3
            else:
                recency = 0.1
            return t.downloads * 0.4 + (t.rating or 0.0) * 0.3 + recency * 0.3

        published.sort(key=_score, reverse=True)
        return published[:_FEATURED_COUNT]

    def get_by_use_case(self, use_case: CREUseCase) -> List[AgentTemplate]:
        """
        REQ-TMPL-008: Return published templates filtered by CRE use case.
        Results are sorted by composite score.
        """
        return self.registry.search(
            cre_use_case=use_case.value,
            status=TemplateStatus.PUBLISHED,
        )

    def get_by_category(self, category: TemplateCategory) -> List[AgentTemplate]:
        """Return published templates in a specific category."""
        return self.registry.search(
            category=category,
            status=TemplateStatus.PUBLISHED,
        )

    def catalog_stats(self) -> Dict[str, Any]:
        """Aggregate stats for the public catalog."""
        reg_stats = self.registry.stats()
        featured = self.get_featured()
        by_use_case: Dict[str, int] = {}
        for tmpl in self.registry.list_all():
            if tmpl.status != TemplateStatus.PUBLISHED:
                continue
            for uc in tmpl.cre_use_cases:
                by_use_case[uc.value] = by_use_case.get(uc.value, 0) + 1

        return {
            **reg_stats,
            "featured_count": len(featured),
            "by_use_case": by_use_case,
            "marketplace_bridge": self.marketplace_service is not None,
        }

    # ------------------------------------------------------------------
    # MarketplaceService bridge (REQ-TMPL-009)
    # ------------------------------------------------------------------

    def sync_to_marketplace(self) -> List[str]:
        """
        REQ-TMPL-009: Create a MarketplaceListing in MarketplaceService for each
        published template that doesn't already have one.

        Returns a list of listing_ids that were created.

        Mapping:
            capability_id = f"template.{template.template_id}"
            tags          = ["template", f"category:{category}"] + template.tags
            base_price_usd = template.template_price_usd
        """
        if self.marketplace_service is None:
            logger.warning("No MarketplaceService configured; skipping sync_to_marketplace().")
            return []

        created_listing_ids: List[str] = []

        # Build index of existing capability_ids to avoid duplicates
        try:
            existing_cap_ids = {
                listing.capability_id
                for listing in self.marketplace_service.list_all_listings(include_archived=True)
            }
        except Exception as exc:
            logger.error("Could not retrieve existing listings: %s", exc)
            return []

        for tmpl in self.registry.list_all():
            if tmpl.status != TemplateStatus.PUBLISHED:
                continue
            if tmpl.marketplace_visibility == "private":
                continue

            cap_id = f"template.{tmpl.template_id}"
            if cap_id in existing_cap_ids:
                logger.debug("Listing already exists for template capability: %s", cap_id)
                continue

            # Determine pricing tier from template price
            price = tmpl.template_price_usd
            if price == 0.0:
                tier = PricingTier.FREE
            elif price <= 0.004:
                tier = PricingTier.MICRO
                price = max(0.001, price)
            elif price <= 0.010:
                tier = PricingTier.STANDARD
                price = max(0.005, price)
            else:
                tier = PricingTier.PREMIUM
                price = max(0.011, price)

            tags = ["template", f"category:{tmpl.category.value}"] + list(tmpl.tags)
            if tmpl.trust_tier == 1:
                tags.append("sensitive")
            if tmpl.marketplace_visibility == "restricted":
                tags.append("restricted")

            try:
                listing = self.marketplace_service.create_listing(
                    capability_id=cap_id,
                    name=tmpl.name,
                    description=tmpl.description,
                    base_price_usd=price,
                    pricing_tier=tier,
                    cre_use_cases=tmpl.cre_use_cases or [],
                    tags=tags,
                    author_id=tmpl.author_id,
                )
                # Immediately publish so it appears in catalog
                try:
                    self.marketplace_service.publish_listing(listing.listing_id)
                except Exception as pub_exc:
                    logger.warning(
                        "Could not auto-publish listing %s: %s",
                        listing.listing_id,
                        pub_exc,
                    )
                created_listing_ids.append(listing.listing_id)
                logger.info(
                    "Created marketplace listing %s for template %s",
                    listing.listing_id,
                    tmpl.template_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create marketplace listing for template %s: %s",
                    tmpl.template_id,
                    exc,
                )

        return created_listing_ids

    # ------------------------------------------------------------------
    # A2A manifest (REQ per Design D7 / BLP-052)
    # ------------------------------------------------------------------

    def export_a2a_manifest_section(self) -> Dict[str, Any]:
        """
        Export the template catalog as a section for .well-known/agent-services.json.

        Returns a dict compatible with the A2A directory broadcast format used by
        CapabilityRegistry.broadcast_a2a_directory().
        """
        templates_section: List[Dict[str, Any]] = []
        for tmpl in self.get_featured():
            templates_section.append({
                "template_id": tmpl.template_id,
                "name": tmpl.name,
                "description": tmpl.description,
                "category": tmpl.category.value,
                "version": tmpl.version,
                "pricing_tier": tmpl.pricing_tier.value,
                "template_price_usd": tmpl.template_price_usd,
                "downloads": tmpl.downloads,
                "rating": tmpl.rating,
                "tags": tmpl.tags,
                "cre_use_cases": [uc.value for uc in tmpl.cre_use_cases],
                "blp_properties": tmpl.blp_properties,
                "source_type": tmpl.source_type.value,
            })

        return {
            "template_marketplace": {
                "total_templates": self.registry.stats()["published"],
                "featured": templates_section,
                "endpoint": "/api/templates",
            }
        }
