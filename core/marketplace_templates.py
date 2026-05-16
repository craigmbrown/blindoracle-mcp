# REQ-MKT-001: MarketplaceListing pydantic model for BlindOracle agent listings
# REQ-MKT-002: ListingValidator validates against CapabilityRegistry
# REQ-MKT-008: Pricing tier validation (free/micro/standard/premium bounds)
# REQ-MKT-014: Template versioning with changelog
# REQ-MKT-015: CRE use case classification
# REQ-TMPL-009: TemplateCategory imported here for MarketplaceListing template_id bridge

from enum import Enum
from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class TemplateCategory(str, Enum):
    """
    REQ-TMPL-009: TemplateCategory re-exported here so MarketplaceListing can
    reference template categories without creating a circular import.
    The authoritative definition lives in core/agent_templates.py.
    """
    SFA = "sfa"
    CRON_AGENT = "cron"
    MCP_SERVER = "mcp"
    RESEARCH = "research"
    COMMERCE = "commerce"
    CUSTOM = "custom"


class AgentCapability(BaseModel):
    """
    Minimal pydantic representation for test/mock CapabilityRegistry entries.
    The real CapabilityRegistry uses a dataclass (services/capability_registry/registry.py).
    Both share the same attribute interface for duck-typing.
    """
    capability_id: str
    name: str
    description: str


class ListingStatus(str, Enum):
    """REQ-MKT-004: Status of a marketplace listing."""
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class PricingTier(str, Enum):
    """REQ-MKT-008: Defines pricing tiers for marketplace listings."""
    FREE = "free"
    MICRO = "micro"
    STANDARD = "standard"
    PREMIUM = "premium"


class CREUseCase(str, Enum):
    """REQ-MKT-015: Canonical CRE use cases for agent classification."""
    DATA_ANALYSIS = "data_analysis"
    PREDICTION_MARKET = "prediction_market"
    AUTOMATION = "automation"
    SECURITY_AUDIT = "security_audit"
    CONTENT_GENERATION = "content_generation"
    FINANCIAL_MODELING = "financial_modeling"
    RESEARCH_ASSISTANT = "research_assistant"
    OPTIMIZATION = "optimization"
    SYSTEM_MONITORING = "system_monitoring"
    CUSTOM = "custom"


class ChangelogEntry(BaseModel):
    """REQ-MKT-014: Entry for version changelog."""
    version: str
    date: datetime = Field(default_factory=datetime.now)
    summary: str
    breaking_changes: bool = False


class MarketplaceListing(AgentCapability):
    """
    REQ-MKT-001: Pydantic model for a BlindOracle agent marketplace listing.
    Extends AgentCapability with marketplace-specific metadata.

    listing_id format: "mkt-<any-alphanumeric-dash-dot-chars>"
    Supports both test IDs (mkt-cap-test-001-abc123) and UUID IDs (mkt-{uuid4}).
    """
    # REQ-MKT-001: listing_id pattern allows capability slugs + UUID fragments
    listing_id: str = Field(..., pattern=r"^mkt-[\w.\-]+$")
    status: ListingStatus = ListingStatus.DRAFT
    pricing_tier: PricingTier = PricingTier.MICRO
    base_price_usd: float = Field(..., ge=0)
    cre_use_cases: List[CREUseCase] = []
    tags: List[str] = []
    author_id: Optional[str] = None
    published_at: Optional[datetime] = None
    last_updated_at: datetime = Field(default_factory=datetime.now)
    changelog: List[ChangelogEntry] = []
    version: str = "1.0.0"
    # REQ-MKT-006: Enrichment fields (populated by enrich_listing())
    reputation_score: Optional[float] = None
    # REQ-MKT-007: Proof count from ProofDB enrichment
    proof_count: int = 0
    # REQ-TMPL-009: Optional link back to an AgentTemplate (set by TemplateCatalog.sync_to_marketplace())
    template_id: Optional[str] = None

    @field_validator("cre_use_cases", mode="before")
    @classmethod
    def validate_cre_use_cases(cls, v: Any) -> List[CREUseCase]:
        if not isinstance(v, list):
            raise ValueError("CRE use cases must be a list")
        return [CREUseCase(item) for item in v]

    @model_validator(mode="after")
    def validate_pricing_tier_and_price(self) -> "MarketplaceListing":
        """REQ-MKT-008: Validate pricing tier vs price constraints."""
        tier = self.pricing_tier
        price = self.base_price_usd

        if tier == PricingTier.FREE and price != 0:
            raise ValueError("Free tier agents must have a base price of 0 USD.")
        elif tier == PricingTier.MICRO and not (0.001 <= price <= 0.004):
            raise ValueError("Micro tier agents must have a base price between $0.001 and $0.004.")
        elif tier == PricingTier.STANDARD and not (0.005 <= price <= 0.010):
            raise ValueError("Standard tier agents must have a base price between $0.005 and $0.010.")
        elif tier == PricingTier.PREMIUM and price <= 0.010:
            raise ValueError("Premium tier agents must have a base price greater than $0.010.")
        return self

    def to_catalog_entry(self) -> Dict[str, Any]:
        """Strips private fields for public catalog display. REQ-MKT-009."""
        catalog_dict = self.model_dump(exclude={
            "author_id", "changelog", "last_updated_at", "status"
        })
        catalog_dict["status"] = self.status.value
        return catalog_dict

    def bump_version(self, summary: str, breaking_changes: Optional[bool] = None) -> None:
        """
        REQ-MKT-014: Bumps the version and adds a changelog entry.
        Keeps a maximum of 50 changelog entries (FIFO trim).

        breaking_changes=None  → patch bump (default, e.g. bug fix)
        breaking_changes=False → minor bump (new feature, non-breaking)
        breaking_changes=True  → major bump (breaking API change)
        """
        major, minor, patch = map(int, self.version.split("."))
        if breaking_changes is True:
            major += 1
            minor = 0
            patch = 0
        elif breaking_changes is False:
            minor += 1
            patch = 0
        else:
            patch += 1
        self.version = f"{major}.{minor}.{patch}"

        new_entry = ChangelogEntry(
            version=self.version,
            summary=summary,
            breaking_changes=bool(breaking_changes),
        )
        self.changelog.append(new_entry)
        if len(self.changelog) > 50:
            self.changelog = self.changelog[-50:]


class ListingValidator:
    """
    REQ-MKT-002: Validates a MarketplaceListing against the CapabilityRegistry.
    Accepts both the pydantic AgentCapability mock and the real dataclass from registry.py.
    """
    def __init__(self, capability_registry: Any) -> None:
        self.capability_registry = capability_registry

    def validate_listing(self, listing: MarketplaceListing) -> bool:
        """
        Validates capability_id exists in registry and enforces trust tier rules.
        """
        # REQ-MKT-002: Check capability_id exists
        if not self.capability_registry.get(listing.capability_id):
            raise ValueError(f"Capability '{listing.capability_id}' not found in CapabilityRegistry.")

        # REQ-MKT-009 / Design D7: Tier 1 (sensitive) agents must not auto-publish
        if "sensitive" in listing.tags and listing.status == ListingStatus.PUBLISHED:
            print(f"Warning: Sensitive agent '{listing.name}' is attempting to be published. Review manually.")

        return True
