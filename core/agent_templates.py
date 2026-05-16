# REQ-TMPL-001: AgentTemplate pydantic model — parametric agent blueprint
# REQ-TMPL-002: TemplateParam with typed validation
# REQ-TMPL-005: InstantiatedAgent tracking model
# @BLP-001: Alignment — templates validate against known capabilities and trust tiers
# @BLP-041: Self-Replication — templates are the mechanism for parameterized agent cloning

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.marketplace_templates import ChangelogEntry, CREUseCase, PricingTier

# MASSAT Security Hardening (ASI01-ASI10) — auto-injected by security_hardening_rollout.py
try:
    from core.security_guards import validate_agent_input, check_agent_scope, log_agent_action
    from core.tool_allowlist import validate_tool_call, get_allowed_tools
    from core.agent_monitor import AgentSessionMonitor
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False



# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TemplateCategory(str, Enum):
    """REQ-TMPL-001: Categories for agent templates aligned with ecosystem archetypes."""
    SFA = "sfa"              # Single File Agent (TheBaby pattern)
    CRON_AGENT = "cron"      # Scheduled team agent (BlindOracle pattern)
    MCP_SERVER = "mcp"       # MCP server wrapper
    RESEARCH = "research"    # Research / analysis agent
    COMMERCE = "commerce"    # Commerce / trading agent
    CUSTOM = "custom"        # Custom / other


class TemplateStatus(str, Enum):
    """Lifecycle states for a template."""
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class TemplateSourceType(str, Enum):
    """Source types that determine render + validation behaviour."""
    SFA_PYTHON = "sfa_python"
    AGENT_JSON = "agent_json"
    MCP_CONFIG = "mcp_config"


# ---------------------------------------------------------------------------
# TemplateParam
# ---------------------------------------------------------------------------

class TemplateParam(BaseModel):
    """
    REQ-TMPL-002: A configurable parameter for template instantiation.

    Supports typed validation including regex, enum constraints, and secret
    handling.  Secret params are never persisted after instantiation.
    """
    name: str                                   # e.g. "model_name"
    display_name: str                           # e.g. "LLM Model"
    description: str                            # Help text shown in catalog
    param_type: str                             # string | number | boolean | enum | secret
    default: Optional[Any] = None
    required: bool = False
    enum_values: Optional[List[str]] = None     # Valid values when param_type="enum"
    validation_regex: Optional[str] = None      # Regex for param_type="string"

    @field_validator("param_type")
    @classmethod
    def validate_param_type(cls, v: str) -> str:
        allowed = {"string", "number", "boolean", "enum", "secret"}
        if v not in allowed:
            raise ValueError(f"param_type must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def check_enum_values(self) -> "TemplateParam":
        """REQ-TMPL-002: enum params must declare enum_values."""
        if self.param_type == "enum" and not self.enum_values:
            raise ValueError("param_type='enum' requires enum_values to be set")
        if self.validation_regex is not None:
            try:
                re.compile(self.validation_regex)
            except re.error as exc:
                raise ValueError(f"validation_regex is not a valid regex: {exc}") from exc
        return self


# ---------------------------------------------------------------------------
# AgentTemplate
# ---------------------------------------------------------------------------

class AgentTemplate(BaseModel):
    """
    REQ-TMPL-001: Parametric agent template for the BlindOracle marketplace.

    Separates blueprint concerns (AgentTemplate) from catalog listing concerns
    (MarketplaceListing) per Design Decision D1.  Renders via Jinja2 sandboxed
    environment (Design Decision D2).

    template_id pattern: "tmpl-" followed by word chars, dots, or hyphens.
    """
    # Identity
    template_id: str = Field(..., pattern=r"^tmpl-[\w.\-]+$")
    name: str
    description: str
    category: TemplateCategory
    tags: List[str] = []

    # Versioning (reuses ChangelogEntry from marketplace_templates.py)
    version: str = "1.0.0"
    changelog: List[ChangelogEntry] = []

    # Author & Trust (Design Decision D6 — trust tier flows from author)
    author_id: str                              # Agent DID or "system"
    author_name: Optional[str] = None
    trust_tier: int = Field(default=3, ge=1, le=5)
    marketplace_visibility: str = "public"      # private | restricted | public

    # Template Content
    source_type: TemplateSourceType
    source_template: str                        # Jinja2 template body
    parameters: List[TemplateParam] = []
    required_env_vars: List[str] = []           # e.g. ["OPENAI_API_KEY"]
    required_tools: List[str] = []              # MCP tools needed
    required_skills: List[str] = []             # VALID_SKILLS names

    # Pricing (reuses PricingTier from marketplace_templates.py)
    pricing_tier: PricingTier = PricingTier.FREE
    template_price_usd: float = Field(default=0.0, ge=0.0)
    instantiation_price_usd: float = Field(default=0.0, ge=0.0)

    # Marketplace metadata (Design Decision D7 — organic quality via downloads+ratings)
    status: TemplateStatus = TemplateStatus.DRAFT
    published_at: Optional[datetime] = None
    downloads: int = Field(default=0, ge=0)
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    cre_use_cases: List[CREUseCase] = []
    blp_properties: List[str] = []

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("marketplace_visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        allowed = {"private", "restricted", "public"}
        if v not in allowed:
            raise ValueError(f"marketplace_visibility must be one of {allowed}")
        return v

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"version must be semver (X.Y.Z), got '{v}'")
        return v

    @model_validator(mode="after")
    def check_trust_tier_visibility(self) -> "AgentTemplate":
        """
        REQ-TMPL-001 / Design D6: Internal (tier 1) templates cannot be public.
        """
        if self.trust_tier == 1 and self.marketplace_visibility == "public":
            raise ValueError(
                "trust_tier=1 (internal) templates cannot have marketplace_visibility='public'. "
                "Use 'private' or 'restricted'."
            )
        return self

    def bump_version(self, summary: str, breaking_changes: Optional[bool] = None) -> None:
        """
        Bump semver and append a ChangelogEntry.  Mirrors MarketplaceListing.bump_version().

        breaking_changes=None  -> patch bump (bug fix)
        breaking_changes=False -> minor bump (new feature, non-breaking)
        breaking_changes=True  -> major bump (breaking API change)
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
        entry = ChangelogEntry(
            version=self.version,
            summary=summary,
            breaking_changes=bool(breaking_changes),
        )
        self.changelog.append(entry)
        if len(self.changelog) > 50:
            self.changelog = self.changelog[-50:]
        self.updated_at = datetime.now()

    def get_required_params(self) -> List[TemplateParam]:
        """Return only parameters marked required=True."""
        return [p for p in self.parameters if p.required]

    def get_param_by_name(self, name: str) -> Optional[TemplateParam]:
        """Look up a parameter definition by name."""
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def to_catalog_entry(self) -> Dict[str, Any]:
        """
        REQ-TMPL-008: Strip private fields for public catalog display.
        Excludes: source_template (IP), author_id, changelog.
        """
        data = self.model_dump(
            exclude={"source_template", "author_id", "changelog"},
        )
        return data


# ---------------------------------------------------------------------------
# InstantiatedAgent
# ---------------------------------------------------------------------------

class InstantiatedAgent(BaseModel):
    """
    REQ-TMPL-005: Record of a single template instantiation.

    Secret parameters are resolved from environment at instantiation time
    and are NEVER stored in this model.
    """
    instance_id: str = Field(..., pattern=r"^inst-[\w.\-]+$")
    template_id: str
    template_version: str
    parameters_used: Dict[str, Any]             # Resolved non-secret parameter values
    generated_file_path: Optional[str] = None   # Absolute path to generated SFA/config
    capability_id: Optional[str] = None         # If registered in CapabilityRegistry
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str = "operator"                # Agent DID or "operator"

    @field_validator("parameters_used", mode="before")
    @classmethod
    def strip_none_values(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, dict):
            return {k: val for k, val in v.items() if val is not None}
        return v or {}
