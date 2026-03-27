"""Template registry, Jinja2 renderer, validation, and hashing for T3 benchmark.

Provides:
  - TemplateSpec / TEMPLATE_REGISTRY: central template definitions
  - render() / render_with_metadata(): strict rendering with variable validation
  - init_template_hashes(): one-shot immutable hashing via Jinja2 loader source
  - preflight_validate_templates(): startup validation
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_tpl_log = logging.getLogger("t3.templates")
BASE_DIR = Path(__file__).parent


# ============================================================
# EXCEPTIONS
# ============================================================


class TemplateError(Exception):
    """Base class for all template system errors."""

    pass


class TemplateNotFoundError(TemplateError):
    pass


class TemplateMissingVarError(TemplateError):
    pass


class TemplateExtraVarError(TemplateError):
    pass


# ============================================================
# TEMPLATE SPEC + REGISTRY
# ============================================================


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    path: str  # relative to project root (e.g., "templates/base.jinja2")
    required_vars: frozenset[str]  # SOLE source of truth for variable requirements


# Central registry -- every template the system uses MUST be registered here.
TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {}


def register(spec: TemplateSpec) -> None:
    if spec.name in TEMPLATE_REGISTRY:
        raise RuntimeError(f"Duplicate template registration: {spec.name}")
    TEMPLATE_REGISTRY[spec.name] = spec


# ============================================================
# REGISTERED TEMPLATES
# ============================================================

register(
    TemplateSpec(
        name="base",
        path="templates/base.jinja2",
        required_vars=frozenset({"task", "code_files_block"}),
    )
)

register(
    TemplateSpec(
        name="retry",
        path="templates/retry.jinja2",
        required_vars=frozenset(
            {
                "task",
                "code_files_block",
                "previous_code",
                "test_output",
                "failure_reason",
                "step_number",
            }
        ),
    )
)

register(
    TemplateSpec(
        name="repair_feedback",
        path="templates/repair_feedback.jinja2",
        required_vars=frozenset(
            {
                "task",
                "code_files_block",
                "error_reasons",
            }
        ),
    )
)

register(
    TemplateSpec(
        name="contract_elicit",
        path="templates/contract_elicit.jinja2",
        required_vars=frozenset(
            {
                "task",
                "code_files_block",
                "contract_schema",
            }
        ),
    )
)

register(
    TemplateSpec(
        name="contract_code",
        path="templates/contract_code.jinja2",
        required_vars=frozenset(
            {
                "task",
                "code_files_block",
                "contract_json",
            }
        ),
    )
)

register(
    TemplateSpec(
        name="contract_retry",
        path="templates/contract_retry.jinja2",
        required_vars=frozenset(
            {
                "task",
                "code_files_block",
                "contract_json",
                "violations_text",
            }
        ),
    )
)

register(
    TemplateSpec(
        name="classify",
        path="templates/classify.jinja2",
        required_vars=frozenset(
            {
                "failure_types",
                "task",
                "code",
                "reasoning",
            }
        ),
    )
)


# ============================================================
# JINJA2 ENVIRONMENT
# ============================================================

_env: Environment | None = None


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(BASE_DIR / "templates")),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
    return _env


def _reset_env() -> None:
    """Reset the Jinja2 environment. For testing only."""
    global _env
    _env = None


# ============================================================
# TEMPLATE HASHING (computed once at startup, immutable)
# ============================================================

_template_hashes: dict[str, str] | None = None


def init_template_hashes() -> dict[str, str]:
    """Compute SHA-256 hashes for ALL registered templates. Called ONCE at startup.

    Uses env.loader.get_source() to hash the exact source Jinja2 will render.
    Returns a copy of the hash dict and stores the original as immutable module state.

    Raises:
        RuntimeError: if called more than once (double-init is a bug)
        TemplateNotFoundError: if any registered template cannot be loaded by Jinja2
    """
    global _template_hashes
    if _template_hashes is not None:
        raise RuntimeError(
            "init_template_hashes() called twice. " "Template hashes are immutable after startup."
        )

    env = _get_env()
    hashes = {}
    for name, spec in TEMPLATE_REGISTRY.items():
        jinja_name = spec.path.replace("templates/", "")
        try:
            source, _, _ = env.loader.get_source(env, jinja_name)
        except Exception as e:
            raise TemplateNotFoundError(
                f"Cannot load template '{name}' ({jinja_name}) via Jinja2 loader: {e}"
            ) from e
        hashes[name] = hashlib.sha256(source.encode("utf-8")).hexdigest()

    _template_hashes = hashes
    return dict(hashes)


def get_template_hash(template_name: str) -> str:
    """Get the precomputed hash for a template. Must call init_template_hashes() first."""
    if _template_hashes is None:
        raise RuntimeError(
            "get_template_hash() called before init_template_hashes(). "
            "Template hashes must be initialized at startup."
        )
    if template_name not in _template_hashes:
        raise TemplateNotFoundError(
            f"No hash for template '{template_name}'. " f"Known: {sorted(_template_hashes.keys())}"
        )
    return _template_hashes[template_name]


def _reset_template_hashes() -> None:
    """Reset hash state. For testing only."""
    global _template_hashes
    _template_hashes = None


# ============================================================
# RENDER
# ============================================================


def render(template_name: str, variables: dict[str, str]) -> str:
    """Render a registered template with strict validation.

    Raises:
        TemplateNotFoundError: template_name not in TEMPLATE_REGISTRY
        TemplateMissingVarError: required var not in variables
        TemplateExtraVarError: variables contains keys not in required_vars
        jinja2.UndefinedError: Jinja2 StrictUndefined caught a missing var at render time
    """
    spec = TEMPLATE_REGISTRY.get(template_name)
    if spec is None:
        raise TemplateNotFoundError(
            f"Template '{template_name}' is not registered. "
            f"Known templates: {sorted(TEMPLATE_REGISTRY.keys())}"
        )

    provided = frozenset(variables.keys())
    missing = spec.required_vars - provided
    if missing:
        raise TemplateMissingVarError(
            f"Template '{template_name}' requires variables {sorted(missing)} "
            f"but they were not provided. "
            f"Required: {sorted(spec.required_vars)}, Provided: {sorted(provided)}"
        )
    extra = provided - spec.required_vars
    if extra:
        raise TemplateExtraVarError(
            f"Template '{template_name}' received unexpected variables {sorted(extra)}. "
            f"Required: {sorted(spec.required_vars)}, Provided: {sorted(provided)}"
        )

    template_hash = get_template_hash(template_name)

    _tpl_log.info(
        "TEMPLATE LOADED: %s (hash=%s)\n  REQUIRED VARS: %s\n  PROVIDED VARS: %s",
        spec.path,
        template_hash[:12],
        sorted(spec.required_vars),
        sorted(provided),
    )

    env = _get_env()
    template = env.get_template(spec.path.replace("templates/", ""))
    rendered = template.render(**variables)

    return rendered


def render_with_metadata(template_name: str, variables: dict[str, str]) -> tuple[str, dict]:
    """Render and return (rendered_text, metadata_dict).

    metadata_dict contains template_name, template_hash, variables -- everything
    needed for prompt logging.
    """
    rendered = render(template_name, variables)
    template_hash = get_template_hash(template_name)
    metadata = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": dict(variables),
        "rendered_length": len(rendered),
    }
    return rendered, metadata


# ============================================================
# PROMPT LOGGING
# ============================================================


def log_rendered_prompt(
    template_name: str, template_hash: str, variables: dict, rendered: str
) -> dict:
    """Build a prompt log record with full provenance.

    Returns the record dict. Caller writes it via RunLogger.
    """
    record = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": variables,
        "rendered_prompt": rendered,
        "rendered_length": len(rendered),
    }
    _tpl_log.info(
        "PROMPT RENDERED: template=%s hash=%s vars=%s len=%d",
        template_name,
        template_hash[:12],
        sorted(variables.keys()),
        len(rendered),
    )
    return record


# ============================================================
# TEMPLATE VALIDATION
# ============================================================

FORBIDDEN_TEMPLATE_TAGS = frozenset(
    {
        "for",
        "endfor",
        "macro",
        "endmacro",
        "call",
        "endcall",
        "filter",
        "endfilter",
        "set",
        "block",
        "endblock",
        "extends",
        "import",
        "from",
    }
)


def validate_template_allowed_logic(template_path: Path) -> None:
    """Check that template uses only allowed Jinja2 tags.

    Allowed: if, elif, else, endif
    Forbidden: for, macro, set, block, extends, import, etc.
    """
    content = template_path.read_text()
    tags = re.findall(r"\{%-?\s*(\w+)", content)
    for tag in tags:
        if tag in FORBIDDEN_TEMPLATE_TAGS:
            raise TemplateError(
                f"Template {template_path} uses forbidden tag '{{% {tag} %}}'. "
                f"Only if/elif/else/endif are allowed. "
                f"Forbidden: {sorted(FORBIDDEN_TEMPLATE_TAGS)}"
            )


def preflight_validate_templates(config) -> None:
    """Validate all templates. Raises on ANY issue. Called once at startup.

    Args:
        config: ExperimentConfig (imported type avoided to prevent circular import)
    """
    # 1. Check every registered template file exists
    for name, spec in TEMPLATE_REGISTRY.items():
        full_path = BASE_DIR / spec.path
        if not full_path.exists():
            raise TemplateNotFoundError(
                f"Registered template '{name}' points to {full_path} which does not exist"
            )

    # 2. Check no unregistered templates exist
    template_dir = BASE_DIR / "templates"
    if template_dir.exists():
        on_disk = {p.name for p in template_dir.glob("*.jinja2")}
        registered_files = {Path(spec.path).name for spec in TEMPLATE_REGISTRY.values()}
        unregistered = on_disk - registered_files
        if unregistered:
            raise TemplateError(
                f"Unregistered template files found: {unregistered}. "
                f"Every .jinja2 file must be registered in TEMPLATE_REGISTRY."
            )

    # 3. Validate template logic rules
    for name, spec in TEMPLATE_REGISTRY.items():
        validate_template_allowed_logic(BASE_DIR / spec.path)

    # 4. Validate every condition's template references exist in registry
    for cond_name, cond_cfg in config.conditions.items():
        for field in ("template", "retry_template", "next_template"):
            tpl_name = getattr(cond_cfg, field)
            if tpl_name is not None and tpl_name not in TEMPLATE_REGISTRY:
                raise TemplateError(
                    f"Condition '{cond_name}'.{field} = '{tpl_name}' " f"not in TEMPLATE_REGISTRY"
                )

    # 5. Dry-render all templates with placeholder values to verify Jinja2 syntax
    env = _get_env()
    for name, spec in TEMPLATE_REGISTRY.items():
        try:
            template = env.get_template(spec.path.replace("templates/", ""))
            placeholders = {var: f"__PLACEHOLDER_{var}__" for var in spec.required_vars}
            template.render(**placeholders)
        except Exception as e:
            raise TemplateError(f"Template '{name}' failed dry-render validation: {e}") from e

    # 6. Compute and store all template hashes (once, immutable)
    hashes = init_template_hashes()
    _tpl_log.info(
        "PREFLIGHT: All %d templates validated OK. Hashes: %s",
        len(TEMPLATE_REGISTRY),
        {k: v[:12] for k, v in hashes.items()},
    )
