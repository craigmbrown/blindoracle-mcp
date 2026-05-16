# REQ-TMPL-006: TemplateInstantiator — renders Jinja2 templates with validated params
# REQ-TMPL-007: Parameter validation pipeline (type, enum, regex, required, env vars)
# @BLP-041: Self-Replication — templates are the mechanism for parameterised agent cloning
# @BLP-001: Alignment — all params validated before any code is written to disk

from __future__ import annotations

import json
import logging
import os
import py_compile
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from jinja2.sandbox import SandboxedEnvironment
    from jinja2 import Undefined, TemplateSyntaxError
    _HAS_JINJA2 = True
except ImportError:  # pragma: no cover
    _HAS_JINJA2 = False
    SandboxedEnvironment = None  # type: ignore[assignment,misc]

from core.agent_templates import (
    AgentTemplate,
    InstantiatedAgent,
    TemplateParam,
    TemplateSourceType,
    TemplateStatus,
)
from core.template_registry import TemplateRegistry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "generated_agents"
_INSTANCES_FILE = _PROJECT_ROOT / "data" / "template_instances.json"


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------

def _filter_snake_case(value: str) -> str:
    """Convert a string to snake_case."""
    s = re.sub(r"[\s\-]+", "_", str(value))
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _filter_upper_snake(value: str) -> str:
    """Convert a string to UPPER_SNAKE_CASE (suitable for env var names)."""
    return _filter_snake_case(value).upper()


def _filter_safe_string(value: str) -> str:
    """Escape a string for safe embedding in Python source code."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


# ---------------------------------------------------------------------------
# TemplateInstantiator
# ---------------------------------------------------------------------------

class TemplateInstantiator:
    """
    REQ-TMPL-006: Renders agent templates into runnable SFA files or JSON configs.

    REQ-TMPL-007 validation pipeline (in order):
        1. Check all required params present
        2. Validate types (string/number/boolean/enum/secret)
        3. Apply validation_regex for string params
        4. Check enum values against enum_values list
        5. Warn (not error) if required_env_vars are absent from environment
        6. Render template to string via Jinja2 SandboxedEnvironment
        7. For sfa_python: run py_compile on rendered output
        8. For agent_json: validate JSON schema (parse check)

    Secret params (param_type="secret") are resolved from environment variables
    at render time and are NEVER stored in the InstantiatedAgent record.
    """

    def __init__(
        self,
        registry: TemplateRegistry,
        output_dir: Optional[Path] = None,
        instances_file: Optional[Path] = None,
    ) -> None:
        self.registry = registry
        self.output_dir = output_dir or _DEFAULT_OUTPUT_DIR
        self.instances_file = instances_file or _INSTANCES_FILE
        self._instances: Dict[str, InstantiatedAgent] = {}
        self._load_instances()
        self._env = self._build_jinja_env()

    # ------------------------------------------------------------------
    # Jinja2 environment
    # ------------------------------------------------------------------

    def _build_jinja_env(self) -> Any:
        """Build a Jinja2 SandboxedEnvironment with custom filters."""
        if not _HAS_JINJA2:
            logger.warning("jinja2 not installed; template rendering will be unavailable.")
            return None
        env = SandboxedEnvironment(undefined=Undefined)
        env.filters["snake_case"] = _filter_snake_case
        env.filters["upper_snake"] = _filter_upper_snake
        env.filters["safe_string"] = _filter_safe_string
        return env

    # ------------------------------------------------------------------
    # Instance persistence
    # ------------------------------------------------------------------

    def _load_instances(self) -> None:
        if self.instances_file.exists():
            try:
                raw = json.loads(self.instances_file.read_text())
                for item in raw:
                    try:
                        inst = InstantiatedAgent(**item)
                        self._instances[inst.instance_id] = inst
                    except Exception as exc:
                        logger.warning("Skipping corrupt instance: %s", exc)
            except Exception as exc:
                logger.error("Failed to load instances: %s", exc)
        else:
            self.instances_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_instances()

    def _save_instances(self) -> None:
        """Atomic write via tmp-rename."""
        tmp = self.instances_file.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(
                    [i.model_dump() for i in self._instances.values()],
                    f,
                    indent=4,
                    default=str,
                )
            shutil.move(str(tmp), str(self.instances_file))
        except Exception as exc:
            logger.error("Failed to save instances: %s", exc)
        finally:
            if tmp.exists():
                tmp.unlink()

    # ------------------------------------------------------------------
    # Validation (REQ-TMPL-007)
    # ------------------------------------------------------------------

    def validate_params(
        self,
        template_id: str,
        params: Dict[str, Any],
    ) -> List[str]:
        """
        REQ-TMPL-007: Validate params against template parameter definitions.

        Returns a list of error strings (empty list = valid).
        Warnings for missing env vars are logged but not returned as errors.
        """
        tmpl = self.registry.get(template_id)
        if tmpl is None:
            return [f"Template '{template_id}' not found."]

        errors: List[str] = []

        for param in tmpl.parameters:
            value = params.get(param.name)

            # 1. Required check
            if param.required and (value is None or value == ""):
                errors.append(f"Required parameter '{param.name}' is missing.")
                continue

            # Skip remaining checks if not provided and not required
            if value is None:
                continue

            # 2. Type validation
            type_errors = self._validate_type(param, value)
            errors.extend(type_errors)
            if type_errors:
                continue

            # 3. Regex validation (string types only)
            if param.param_type == "string" and param.validation_regex:
                if not re.fullmatch(param.validation_regex, str(value)):
                    errors.append(
                        f"Parameter '{param.name}' value '{value}' does not match "
                        f"required pattern '{param.validation_regex}'."
                    )

            # 4. Enum value check
            if param.param_type == "enum" and param.enum_values:
                if str(value) not in param.enum_values:
                    errors.append(
                        f"Parameter '{param.name}' value '{value}' is not in "
                        f"allowed values: {param.enum_values}."
                    )

        # 5. Env var presence warnings (non-fatal)
        for env_var in tmpl.required_env_vars:
            if not os.environ.get(env_var):
                logger.warning(
                    "Template '%s' requires env var '%s' which is not set.",
                    template_id,
                    env_var,
                )

        return errors

    def _validate_type(self, param: TemplateParam, value: Any) -> List[str]:
        """Type validation for a single parameter."""
        errors: List[str] = []
        ptype = param.param_type

        if ptype == "number":
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(
                    f"Parameter '{param.name}' expects a number, got '{value}'."
                )
        elif ptype == "boolean":
            if not isinstance(value, bool) and str(value).lower() not in {"true", "false", "1", "0"}:
                errors.append(
                    f"Parameter '{param.name}' expects a boolean, got '{value}'."
                )
        elif ptype in ("string", "secret", "enum"):
            if not isinstance(value, (str, int, float)):
                errors.append(
                    f"Parameter '{param.name}' expects a string-like value, got type '{type(value).__name__}'."
                )
        return errors

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def preview(self, template_id: str, params: Dict[str, Any]) -> str:
        """
        REQ-TMPL-006: Dry-run render — returns rendered source as a string without
        writing any files.  Validation errors raise ValueError.
        """
        tmpl = self._get_published_template(template_id)
        errors = self.validate_params(template_id, params)
        if errors:
            raise ValueError(f"Parameter validation failed: {'; '.join(errors)}")
        resolved = self._resolve_params(tmpl, params)
        return self._render(tmpl, resolved)

    def instantiate(
        self,
        template_id: str,
        params: Dict[str, Any],
        output_dir: Optional[Path] = None,
        created_by: str = "operator",
    ) -> InstantiatedAgent:
        """
        REQ-TMPL-006: Full instantiation pipeline.

            1. Validate params
            2. Resolve defaults + secrets from env
            3. Render Jinja2 template
            4. Post-render validation (py_compile / JSON parse)
            5. Write to output_dir
            6. Increment template download counter
            7. Persist InstantiatedAgent record

        Returns the InstantiatedAgent record.
        """
        tmpl = self._get_published_template(template_id)

        # Validate
        errors = self.validate_params(template_id, params)
        if errors:
            raise ValueError(f"Parameter validation failed: {'; '.join(errors)}")

        # Resolve
        resolved = self._resolve_params(tmpl, params)

        # Render
        rendered = self._render(tmpl, resolved)

        # Post-render validation
        self._post_render_validate(tmpl, rendered)

        # Write file
        dest_dir = output_dir or self.output_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._write_output(tmpl, rendered, dest_dir)

        # Increment downloads (best-effort)
        try:
            self.registry.update(template_id, downloads=tmpl.downloads + 1)
        except Exception as exc:
            logger.warning("Failed to increment download count for %s: %s", template_id, exc)

        # Strip secret values from persisted record (REQ security)
        safe_params = {
            k: v
            for k, v in params.items()
            if not self._is_secret_param(tmpl, k)
        }

        instance_id = f"inst-{uuid.uuid4()}"
        instance = InstantiatedAgent(
            instance_id=instance_id,
            template_id=template_id,
            template_version=tmpl.version,
            parameters_used=safe_params,
            generated_file_path=str(file_path),
            created_by=created_by,
        )
        self.register_instance(instance)
        logger.info(
            "Instantiated template '%s' -> %s (instance %s)",
            template_id,
            file_path,
            instance_id,
        )
        return instance

    # ------------------------------------------------------------------
    # Instance management
    # ------------------------------------------------------------------

    def register_instance(self, instance: InstantiatedAgent) -> None:
        """Persist an InstantiatedAgent record."""
        self._instances[instance.instance_id] = instance
        self._save_instances()

    def list_instances(self, template_id: Optional[str] = None) -> List[InstantiatedAgent]:
        """Return all instances, optionally filtered to a specific template."""
        all_inst = list(self._instances.values())
        if template_id is not None:
            return [i for i in all_inst if i.template_id == template_id]
        return all_inst

    def get_instance(self, instance_id: str) -> Optional[InstantiatedAgent]:
        """Return an instance by ID."""
        return self._instances.get(instance_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_published_template(self, template_id: str) -> AgentTemplate:
        """Retrieve template and ensure it is published (or draft for preview)."""
        tmpl = self.registry.get(template_id)
        if tmpl is None:
            raise ValueError(f"Template '{template_id}' not found.")
        if tmpl.status not in (TemplateStatus.PUBLISHED, TemplateStatus.DRAFT):
            raise ValueError(
                f"Template '{template_id}' is not available for instantiation "
                f"(status: {tmpl.status.value})."
            )
        return tmpl

    def _resolve_params(
        self,
        tmpl: AgentTemplate,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge user-supplied params with defaults.  Resolve secret params
        from environment variables (never from user input).
        """
        resolved: Dict[str, Any] = {}

        for param in tmpl.parameters:
            if param.param_type == "secret":
                # Secrets MUST come from env, never from user-supplied dict
                env_key = _filter_upper_snake(param.name)
                resolved[param.name] = os.environ.get(env_key, "")
            elif param.name in params:
                resolved[param.name] = params[param.name]
            elif param.default is not None:
                resolved[param.name] = param.default

        # Also pass through any extra params not formally declared (loose templates)
        for k, v in params.items():
            if k not in resolved:
                resolved[k] = v

        # Standard template metadata always available
        resolved.setdefault("template_id", tmpl.template_id)
        resolved.setdefault("template_version", tmpl.version)
        resolved.setdefault("category", tmpl.category.value)
        resolved.setdefault("blp_properties", tmpl.blp_properties)
        resolved.setdefault("required_env_vars", tmpl.required_env_vars)

        return resolved

    def _render(self, tmpl: AgentTemplate, resolved: Dict[str, Any]) -> str:
        """Render the Jinja2 template body with resolved parameters."""
        if not _HAS_JINJA2 or self._env is None:
            raise RuntimeError(
                "jinja2 is not installed. Install it with: pip install jinja2"
            )
        try:
            j2_tmpl = self._env.from_string(tmpl.source_template)
            return j2_tmpl.render(**resolved)
        except TemplateSyntaxError as exc:
            raise ValueError(f"Template syntax error in '{tmpl.template_id}': {exc}") from exc
        except Exception as exc:
            raise ValueError(f"Template rendering failed for '{tmpl.template_id}': {exc}") from exc

    def _post_render_validate(self, tmpl: AgentTemplate, rendered: str) -> None:
        """
        REQ-TMPL-007 step 7-8: Post-render validation.
        - sfa_python: syntax-check with py_compile
        - agent_json / mcp_config: JSON parse check
        """
        if tmpl.source_type == TemplateSourceType.SFA_PYTHON:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as tmp_f:
                tmp_f.write(rendered)
                tmp_path = tmp_f.name
            try:
                py_compile.compile(tmp_path, doraise=True)
            except py_compile.PyCompileError as exc:
                raise ValueError(
                    f"Generated Python source has syntax errors: {exc}"
                ) from exc
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        elif tmpl.source_type in (TemplateSourceType.AGENT_JSON, TemplateSourceType.MCP_CONFIG):
            try:
                json.loads(rendered)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Generated JSON is not valid: {exc}"
                ) from exc

    def _write_output(
        self,
        tmpl: AgentTemplate,
        rendered: str,
        dest_dir: Path,
    ) -> Path:
        """Determine output filename and write rendered content."""
        ext_map = {
            TemplateSourceType.SFA_PYTHON: ".py",
            TemplateSourceType.AGENT_JSON: ".json",
            TemplateSourceType.MCP_CONFIG: ".json",
        }
        ext = ext_map.get(tmpl.source_type, ".txt")
        safe_name = _filter_snake_case(tmpl.template_id.replace("tmpl-", ""))
        filename = f"{safe_name}_{uuid.uuid4().hex[:8]}{ext}"
        out_path = dest_dir / filename
        out_path.write_text(rendered, encoding="utf-8")
        logger.info("Wrote generated agent to: %s", out_path)
        return out_path

    def _is_secret_param(self, tmpl: AgentTemplate, param_name: str) -> bool:
        """Return True if the named param is a secret type."""
        param = tmpl.get_param_by_name(param_name)
        return param is not None and param.param_type == "secret"
