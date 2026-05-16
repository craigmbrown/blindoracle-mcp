# REQ-MKT-003: MarketplaceService CRUD + catalog generation (atomic JSON persistence)
# REQ-MKT-004: Service CRUD (create/get/update/delete/publish)
# REQ-MKT-006: Enrich listings with real reputation scores from ReputationEngine
# REQ-MKT-007: Enrich listings with real proof counts from ProofDB
# REQ-MKT-009: Public catalog excludes private + draft listings
# REQ-MKT-011: Bootstrap from real CapabilityRegistry (28 agents)
# REQ-MKT-012: Bridge listing layer to commerce engine (importlib wiring)
# REQ-MKT-013: Production stats with real data sources

import importlib.util as _iu
import json
import logging
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.marketplace_templates import (
    CREUseCase,
    ListingStatus,
    ListingValidator,
    MarketplaceListing,
    PricingTier,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real dependency loading via importlib (same pattern as services/marketplace/engine.py:50-67)
# Falls back to inline stubs if services are not importable (test/CI environments).
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, rel_path: str):
    """Dynamically load a module by relative path from project root."""
    full_path = _PROJECT_ROOT / rel_path
    try:
        spec = _iu.spec_from_file_location(name, full_path)
        if spec is None or spec.loader is None:
            return None
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.debug("Could not load %s from %s: %s", name, full_path, exc)
        return None


# --- CapabilityRegistry ---
_cap_registry_mod = _load_module(
    "capability_registry",
    "services/capability_registry/registry.py",
)
if _cap_registry_mod is not None:
    _RealCapabilityRegistry = getattr(_cap_registry_mod, "CapabilityRegistry", None)
    _HAS_REAL_REGISTRY = _RealCapabilityRegistry is not None
else:
    _RealCapabilityRegistry = None
    _HAS_REAL_REGISTRY = False

# --- ReputationEngine ---
_rep_engine_mod = _load_module(
    "reputation_engine",
    "services/reputation/engine.py",
)
if _rep_engine_mod is not None:
    _RealReputationEngine = getattr(_rep_engine_mod, "ReputationEngine", None)
    _HAS_REAL_REPUTATION = _RealReputationEngine is not None
else:
    _RealReputationEngine = None
    _HAS_REAL_REPUTATION = False

# --- ProofDB ---
_proof_db_mod = _load_module(
    "proof_db",
    "services/proof/proof_db.py",
)
if _proof_db_mod is not None:
    _RealProofDB = getattr(_proof_db_mod, "ProofDB", None)
    _HAS_REAL_PROOFDB = _RealProofDB is not None
else:
    _RealProofDB = None
    _HAS_REAL_PROOFDB = False


# ---------------------------------------------------------------------------
# Fallback stubs (used only when real services are unavailable)
# ---------------------------------------------------------------------------

class _StubCapabilityRegistry:
    """Minimal stub used when real CapabilityRegistry is unavailable."""
    def get(self, capability_id: str) -> Optional[Any]:
        return None

    def list_all(self) -> List[Any]:
        return []


class _StubReputationEngine:
    def get(self, agent_name: str) -> Optional[Any]:
        return None


class _StubProofDB:
    def get_proof_count(self, agent_name: str) -> int:
        return 0


# ---------------------------------------------------------------------------
# MarketplaceService
# ---------------------------------------------------------------------------

class MarketplaceService:
    """
    REQ-MKT-003, REQ-MKT-004: Central service for managing BlindOracle marketplace listings.

    Wires to real production services (CapabilityRegistry, ReputationEngine, ProofDB)
    via importlib.util pattern. Gracefully falls back to stubs if services are unavailable.

    Handles CRUD operations, registry synchronization, enrichment, and catalog generation.
    """

    DATA_FILE = _PROJECT_ROOT / "data" / "marketplace_listings.json"

    # Class-level sentinels — allow test monkeypatching before instance creation
    reputation_engine: Any = None
    proof_db: Any = None

    def __init__(self, data_file: Optional[Path] = None) -> None:
        self.data_file = data_file or self.DATA_FILE
        self._listings: Dict[str, MarketplaceListing] = {}
        self._load_listings()
        self.capability_registry = self._load_capability_registry()
        self.listing_validator = ListingValidator(self.capability_registry)
        # Only load if not already set by monkeypatch (class-level sentinel is None)
        if type(self).reputation_engine is None:
            self.reputation_engine = self._load_reputation_engine()
        if type(self).proof_db is None:
            self.proof_db = self._load_proof_db()

    # ------------------------------------------------------------------
    # Dependency loading
    # ------------------------------------------------------------------

    def _load_capability_registry(self) -> Any:
        """
        REQ-MKT-011: Load real CapabilityRegistry or fall back to stub.
        Uses importlib pattern matching services/marketplace/engine.py lines 50-67.
        """
        if _HAS_REAL_REGISTRY:
            try:
                reg = _RealCapabilityRegistry()
                count = len(reg.list_all())
                logger.info("Real CapabilityRegistry loaded: %d agents", count)
                return reg
            except Exception as exc:
                logger.warning("Real CapabilityRegistry init failed: %s — using stub", exc)
        return _StubCapabilityRegistry()

    def _load_reputation_engine(self) -> Any:
        """REQ-MKT-006: Load real ReputationEngine or stub."""
        if _HAS_REAL_REPUTATION:
            try:
                engine = _RealReputationEngine()
                logger.info("Real ReputationEngine loaded")
                return engine
            except Exception as exc:
                logger.warning("Real ReputationEngine init failed: %s — using stub", exc)
        return _StubReputationEngine()

    def _load_proof_db(self) -> Any:
        """REQ-MKT-007: Load real ProofDB or stub."""
        if _HAS_REAL_PROOFDB:
            try:
                db = _RealProofDB()
                logger.info("Real ProofDB loaded at %s", db.db_path)
                return db
            except Exception as exc:
                logger.warning("Real ProofDB init failed: %s — using stub", exc)
        return _StubProofDB()

    # ------------------------------------------------------------------
    # ProofDB helpers
    # ------------------------------------------------------------------

    def _get_proof_count_for_agent(self, agent_name: str, capability_id: Optional[str] = None) -> int:
        """
        REQ-MKT-007: Count proofs for an agent by name from ProofDB.
        Supports both the real ProofDB (SQLite query) and stubs with get_proof_count().
        Falls back to capability_id lookup for stubs that index by capability_id.
        """
        # Real ProofDB: query directly via db_path (read-only)
        if _HAS_REAL_PROOFDB and hasattr(self.proof_db, "db_path"):
            try:
                conn = sqlite3.connect(self.proof_db.db_path, timeout=5.0)
                row = conn.execute(
                    "SELECT COUNT(*) FROM proofs WHERE agent_name = ?",
                    (agent_name,),
                ).fetchone()
                conn.close()
                return int(row[0]) if row else 0
            except Exception as exc:
                logger.debug("ProofDB count query failed for %s: %s", agent_name, exc)
                return 0
        # Stub or mock with get_proof_count() interface — try capability_id first, then agent_name
        if hasattr(self.proof_db, "get_proof_count"):
            if capability_id is not None:
                count = self.proof_db.get_proof_count(capability_id)
                if count:
                    return count
            return self.proof_db.get_proof_count(agent_name)
        return 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_listings(self) -> None:
        if self.data_file.exists():
            try:
                content = self.data_file.read_text()
                raw_listings = json.loads(content)
                for listing_data in raw_listings:
                    listing = MarketplaceListing(**listing_data)
                    self._listings[listing.listing_id] = listing
            except Exception as exc:
                logger.error("Error loading marketplace listings from %s: %s", self.data_file, exc)
                self._listings = {}
        else:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_listings()

    def _save_listings(self) -> None:
        """REQ-MKT-003: Atomic JSON persistence via tmp-rename."""
        temp_file = self.data_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w") as f:
                json.dump(
                    [listing.model_dump() for listing in self._listings.values()],
                    f,
                    indent=4,
                    default=str,
                )
            shutil.move(str(temp_file), str(self.data_file))
        except Exception as exc:
            logger.error("Error saving marketplace listings: %s", exc)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_listing(
        self,
        capability_id: str,
        name: str,
        description: str,
        base_price_usd: float,
        pricing_tier: PricingTier = PricingTier.MICRO,
        cre_use_cases: Optional[List[CREUseCase]] = None,
        tags: Optional[List[str]] = None,
        author_id: Optional[str] = None,
        status: Optional[Any] = None,
    ) -> MarketplaceListing:
        """REQ-MKT-004: Creates a new marketplace listing."""
        # Resolve name from registry if capability is known (registry is authoritative)
        cap = self.capability_registry.get(capability_id)
        if cap is not None:
            resolved_name = getattr(cap, "name", None) or getattr(cap, "display_name", None) or name
        else:
            logger.warning("Capability '%s' not in registry; creating listing anyway.", capability_id)
            resolved_name = name

        listing_id = f"mkt-{str(uuid.uuid4())}"
        listing = MarketplaceListing(
            listing_id=listing_id,
            capability_id=capability_id,
            name=resolved_name,
            description=description,
            base_price_usd=base_price_usd,
            pricing_tier=pricing_tier,
            cre_use_cases=cre_use_cases or [],
            tags=list(tags or []),
            author_id=author_id,
            status=status if status is not None else ListingStatus.DRAFT,
        )
        if cap is not None:
            self.listing_validator.validate_listing(listing)  # REQ-MKT-002
        self._listings[listing_id] = listing
        self._save_listings()
        return listing

    def get_listing(self, listing_id: str) -> Optional[MarketplaceListing]:
        """REQ-MKT-004: Retrieves a marketplace listing by ID."""
        return self._listings.get(listing_id)

    def update_listing(self, listing_id: str, **kwargs: Any) -> MarketplaceListing:
        """REQ-MKT-004: Updates an existing marketplace listing."""
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing with ID '{listing_id}' not found.")

        updated_data = listing.model_dump()
        updated_data.update(kwargs)

        if "status" in kwargs:
            updated_data["status"] = ListingStatus(kwargs["status"])
        if "pricing_tier" in kwargs:
            updated_data["pricing_tier"] = PricingTier(kwargs["pricing_tier"])
        if "cre_use_cases" in kwargs:
            updated_data["cre_use_cases"] = [CREUseCase(uc) for uc in kwargs["cre_use_cases"]]

        updated_listing = MarketplaceListing(**updated_data)
        self.listing_validator.validate_listing(updated_listing)  # REQ-MKT-002
        updated_listing.last_updated_at = datetime.now()
        self._listings[listing_id] = updated_listing
        self._save_listings()
        return updated_listing

    def delete_listing(self, listing_id: str) -> None:
        """REQ-MKT-004: Soft deletes (archives) a marketplace listing."""
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing with ID '{listing_id}' not found.")
        listing.status = ListingStatus.ARCHIVED
        listing.last_updated_at = datetime.now()
        self._save_listings()

    def list_all_listings(self, include_archived: bool = False) -> List[MarketplaceListing]:
        """Lists all listings, optionally including archived ones."""
        if include_archived:
            return list(self._listings.values())
        return [l for l in self._listings.values() if l.status != ListingStatus.ARCHIVED]

    def publish_listing(self, listing_id: str) -> MarketplaceListing:
        """REQ-MKT-004: Publishes a draft or deprecated listing."""
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing with ID '{listing_id}' not found.")
        if listing.status not in [ListingStatus.DRAFT, ListingStatus.DEPRECATED]:
            raise ValueError(
                f"Listing '{listing_id}' cannot be published from status '{listing.status}'."
            )
        # REQ-MKT-009 / Design D7: Tier 1 (sensitive) agents must not auto-publish
        if "sensitive" in listing.tags:
            raise ValueError(
                f"Sensitive agent '{listing.name}' cannot be auto-published. Manual review required."
            )
        listing.status = ListingStatus.PUBLISHED
        listing.published_at = datetime.now()
        listing.last_updated_at = datetime.now()
        self._save_listings()
        return listing

    # ------------------------------------------------------------------
    # Registry Sync (REQ-MKT-011)
    # ------------------------------------------------------------------

    def sync_from_registry(self) -> List[MarketplaceListing]:
        """
        REQ-MKT-011: Bootstrap DRAFT listings from the real CapabilityRegistry.

        Maps AgentCapability fields to MarketplaceListing fields using attribute
        access (works for both the real dataclass and pydantic mock):
          - capability_id → capability_id
          - display_name / name → name
          - description → description
          - price_per_call_usd → base_price_usd (+ PricingTier inference)
          - trust_tier / marketplace_visibility → listing visibility + tags
          - category → CREUseCase mapping
        """
        synced: List[MarketplaceListing] = []
        all_caps = self.capability_registry.list_all()
        existing_cap_ids = {l.capability_id for l in self._listings.values()}

        for cap in all_caps:
            cap_id = cap.capability_id
            if cap_id in existing_cap_ids:
                continue

            # Attribute access — works for real dataclass and pydantic mock
            display_name = (
                getattr(cap, "display_name", None)
                or getattr(cap, "name", None)
                or f"Agent {cap_id}"
            )
            description = getattr(cap, "description", "No description provided.")

            # Pricing: map real price_per_call_usd to PricingTier
            raw_price: float = getattr(cap, "price_per_call_usd", 0.001)
            if raw_price == 0.0:
                tier = PricingTier.FREE
                price = 0.0
            elif raw_price <= 0.004:
                tier = PricingTier.MICRO
                price = max(0.001, min(raw_price, 0.004))
            elif raw_price <= 0.010:
                tier = PricingTier.STANDARD
                price = max(0.005, min(raw_price, 0.010))
            else:
                tier = PricingTier.PREMIUM
                price = max(0.011, raw_price)

            # Tags: include team, category, trust tier metadata
            tags: List[str] = ["synced_from_registry"]
            team = getattr(cap, "team", "")
            category = getattr(cap, "category", "")
            trust_tier = getattr(cap, "trust_tier", 3)
            marketplace_visibility = getattr(cap, "marketplace_visibility", "public")

            if team:
                tags.append(f"team:{team}")
            if category:
                tags.append(f"category:{category}")
            if trust_tier == 1:
                tags.append("sensitive")
            if marketplace_visibility == "private":
                tags.append("private")

            # CRE use case: map category string to CREUseCase
            cre_use_case = _CATEGORY_TO_CRE_USE_CASE.get(category, CREUseCase.CUSTOM)

            listing_id = f"mkt-{str(uuid.uuid4())}"
            try:
                listing = MarketplaceListing(
                    listing_id=listing_id,
                    capability_id=cap_id,
                    name=display_name,
                    description=description,
                    base_price_usd=price,
                    pricing_tier=tier,
                    cre_use_cases=[cre_use_case],
                    tags=tags,
                    author_id="system",
                )
            except Exception as exc:
                logger.warning("Skipping capability %s during sync: %s", cap_id, exc)
                continue

            listing.status = ListingStatus.DRAFT
            self._listings[listing_id] = listing
            synced.append(listing)
            logger.info("Created DRAFT listing for capability: %s (%s)", cap_id, display_name)

        if synced:
            self._save_listings()
        return synced

    # ------------------------------------------------------------------
    # Enrichment (REQ-MKT-006, REQ-MKT-007)
    # ------------------------------------------------------------------

    def enrich_listing(self, listing_id: str) -> MarketplaceListing:
        """
        REQ-MKT-006, REQ-MKT-007: Enrich a listing with reputation score and proof count.

        - ReputationEngine.get(agent_name) returns AgentReputation (score attr) or None.
        - ProofDB: count proofs by agent_name from the proofs table.
        """
        listing = self._listings.get(listing_id)
        if not listing:
            raise ValueError(f"Listing with ID '{listing_id}' not found.")

        # REQ-MKT-006: Reputation score
        rep = self.reputation_engine.get(listing.name)
        if rep is not None:
            # Real engine returns AgentReputation(score=float); mock may return float directly
            score = rep.score if hasattr(rep, "score") else float(rep)
            listing.reputation_score = round(score, 4)
            logger.info("Enriched '%s' with reputation score: %.2f", listing.name, score)
            # Add reputation tag (deduplicated)
            rep_tag = f"reputation:{score:.2f}"
            listing.tags = [t for t in listing.tags if not t.startswith("reputation:")] + [rep_tag]

        # REQ-MKT-007: Proof count — try agent_name first, then capability_id for stubs
        agent_name = getattr(
            self.capability_registry.get(listing.capability_id),
            "agent_name",
            listing.name,
        )
        proof_count = self._get_proof_count_for_agent(agent_name, listing.capability_id)
        listing.proof_count = proof_count
        if proof_count > 0:
            logger.info("Enriched '%s' with proof count: %d", listing.name, proof_count)
        # Add proof_count tag (deduplicated)
        pc_tag = f"proof_count:{proof_count}"
        listing.tags = [t for t in listing.tags if not t.startswith("proof_count:")] + [pc_tag]

        self._save_listings()
        return listing

    # ------------------------------------------------------------------
    # Catalog (REQ-MKT-009)
    # ------------------------------------------------------------------

    def generate_catalog(self) -> List[Dict[str, Any]]:
        """
        REQ-MKT-009: Generate public catalog excluding draft, private, and archived listings.
        """
        catalog = []
        for listing in self._listings.values():
            if listing.status != ListingStatus.PUBLISHED:
                continue
            if "private" in listing.tags:
                continue
            catalog.append(listing.to_catalog_entry())
        return catalog

    # ------------------------------------------------------------------
    # Deployable Config Bridge (REQ-MKT-012)
    # ------------------------------------------------------------------

    def export_deployable_config(self, listing_id: str) -> Dict[str, Any]:
        """
        REQ-MKT-012: Export listing as deployable agent config for the commerce engine.
        """
        listing = self.get_listing(listing_id)
        if not listing:
            raise ValueError(f"Listing with ID '{listing_id}' not found.")

        return {
            "agent_id": listing.capability_id,
            "agent_name": listing.name,
            "description": listing.description,
            "pricing": {
                "tier": listing.pricing_tier.value,
                "base_price_usd": listing.base_price_usd,
            },
            "metadata": {
                "cre_use_cases": [uc.value for uc in listing.cre_use_cases],
                "tags": listing.tags,
                "version": listing.version,
                "reputation_score": listing.reputation_score,
                "proof_count": listing.proof_count,
            },
        }

    # ------------------------------------------------------------------
    # Template Bridge (REQ-TMPL-009)
    # ------------------------------------------------------------------

    def sync_from_templates(self) -> List[MarketplaceListing]:
        """
        REQ-TMPL-009: Create DRAFT marketplace listings for published AgentTemplates
        that don't already have a corresponding listing.

        This is the pull-side complement to TemplateCatalog.sync_to_marketplace().
        Useful when called from a cron agent or admin CLI.

        capability_id format: "template.<template_id>"
        Tags: ["template", "category:<cat>"] + template tags
        """
        try:
            import importlib.util as _iu_inner
            _tmpl_spec = _iu_inner.spec_from_file_location(
                "template_registry",
                _PROJECT_ROOT / "core" / "template_registry.py",
            )
            if _tmpl_spec is None:
                logger.warning("template_registry module not found; skipping sync_from_templates.")
                return []
            _tmpl_mod = _iu_inner.module_from_spec(_tmpl_spec)
            _tmpl_spec.loader.exec_module(_tmpl_mod)  # type: ignore[union-attr]
            _TemplateRegistry = getattr(_tmpl_mod, "TemplateRegistry", None)
            if _TemplateRegistry is None:
                return []
            registry = _TemplateRegistry()
        except Exception as exc:
            logger.warning("Could not load TemplateRegistry for sync: %s", exc)
            return []

        existing_cap_ids = {l.capability_id for l in self._listings.values()}
        synced: List[MarketplaceListing] = []

        for tmpl in registry.list_all():
            if getattr(tmpl, "status", None) is None:
                continue
            if tmpl.status.value != "published":
                continue
            cap_id = f"template.{tmpl.template_id}"
            if cap_id in existing_cap_ids:
                continue

            raw_price: float = getattr(tmpl, "template_price_usd", 0.0)
            if raw_price == 0.0:
                tier = PricingTier.FREE
                price = 0.0
            elif raw_price <= 0.004:
                tier = PricingTier.MICRO
                price = max(0.001, min(raw_price, 0.004))
            elif raw_price <= 0.010:
                tier = PricingTier.STANDARD
                price = max(0.005, min(raw_price, 0.010))
            else:
                tier = PricingTier.PREMIUM
                price = max(0.011, raw_price)

            category = getattr(tmpl.category, "value", str(tmpl.category))
            tags: List[str] = ["template", f"category:{category}"] + list(tmpl.tags or [])
            if getattr(tmpl, "trust_tier", 3) == 1:
                tags.append("sensitive")

            try:
                listing = self.create_listing(
                    capability_id=cap_id,
                    name=tmpl.name,
                    description=tmpl.description,
                    base_price_usd=price,
                    pricing_tier=tier,
                    cre_use_cases=list(tmpl.cre_use_cases or []),
                    tags=tags,
                    author_id=getattr(tmpl, "author_id", "system"),
                )
                synced.append(listing)
                logger.info("Created DRAFT listing for template: %s", tmpl.template_id)
            except Exception as exc:
                logger.warning(
                    "Failed to create listing for template %s: %s",
                    tmpl.template_id,
                    exc,
                )

        return synced

    # ------------------------------------------------------------------
    # Stats (REQ-MKT-013)
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """
        REQ-MKT-013: Return production stats aggregated from real data sources.
        """
        all_listings = list(self._listings.values())
        published = [l for l in all_listings if l.status == ListingStatus.PUBLISHED]
        draft = [l for l in all_listings if l.status == ListingStatus.DRAFT]
        archived = [l for l in all_listings if l.status == ListingStatus.ARCHIVED]
        deprecated = [l for l in all_listings if l.status == ListingStatus.DEPRECATED]

        enriched = [l for l in all_listings if l.reputation_score is not None]
        avg_rep = (
            round(sum(l.reputation_score for l in enriched) / len(enriched), 2)
            if enriched else None
        )
        total_proofs = sum(l.proof_count for l in all_listings)

        tier_counts: Dict[str, int] = {}
        for l in all_listings:
            tier_counts[l.pricing_tier.value] = tier_counts.get(l.pricing_tier.value, 0) + 1

        return {
            "total": len(all_listings),
            "published": len(published),
            "draft": len(draft),
            "archived": len(archived),
            "deprecated": len(deprecated),
            "enriched": len(enriched),
            "avg_reputation_score": avg_rep,
            "total_proof_count": total_proofs,
            "by_pricing_tier": tier_counts,
            "registry_backend": "real" if _HAS_REAL_REGISTRY else "stub",
            "reputation_backend": "real" if _HAS_REAL_REPUTATION else "stub",
            "proofdb_backend": "real" if _HAS_REAL_PROOFDB else "stub",
        }


# ---------------------------------------------------------------------------
# Category → CREUseCase mapping
# ---------------------------------------------------------------------------

_CATEGORY_TO_CRE_USE_CASE: Dict[str, CREUseCase] = {
    "analysis": CREUseCase.DATA_ANALYSIS,
    "security": CREUseCase.SECURITY_AUDIT,
    "benchmarking": CREUseCase.DATA_ANALYSIS,
    "strategy": CREUseCase.RESEARCH_ASSISTANT,
    "operations": CREUseCase.SYSTEM_MONITORING,
    "commercial": CREUseCase.FINANCIAL_MODELING,
    "trading": CREUseCase.PREDICTION_MARKET,
    "research": CREUseCase.RESEARCH_ASSISTANT,
    "optimization": CREUseCase.OPTIMIZATION,
}
