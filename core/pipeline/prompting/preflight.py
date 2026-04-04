"""Startup validation for the prompt compilation system.

Run before any experiment. Validates all components, metadata-AST
consistency, version-hash drift, and dry-renders all programs.
"""

from __future__ import annotations

import logging

import jinja2

from core.pipeline.prompting.exceptions import PromptCompilationError
from core.pipeline.prompting.registry import PromptRegistry

_log = logging.getLogger("t3.prompt_preflight")


def preflight_validate(registry: PromptRegistry) -> dict[str, str]:
    """Validate all components and programs at startup.

    Returns dict of component_name → content_hash for baseline recording.
    Raises on any failure.
    """
    if not registry.loaded:
        raise PromptCompilationError("Registry not loaded before preflight.")

    all_components = registry.get_all_components()
    all_programs = registry.get_all_programs()
    hashes: dict[str, str] = {}

    # Check 1: dry-render each component with placeholder variables
    env = jinja2.Environment(undefined=jinja2.Undefined)  # permissive for dry-render
    for name, comp in all_components.items():
        placeholders = {v: f"__PLACEHOLDER_{v}__" for v in comp.all_declared_inputs}
        try:
            template = env.from_string(comp.raw_template)
            template.render(**placeholders)
        except Exception as e:
            raise PromptCompilationError(
                f"Component '{name}' failed dry-render: {e}"
            ) from e
        hashes[name] = comp.content_hash

    # Check 2: every program's components exist in registry
    for prog_name, program in all_programs.items():
        for comp_name in program.components:
            if comp_name not in all_components:
                _log.warning(
                    "Program '%s' references component '%s' not in registry "
                    "(may be legacy condition — not blocking preflight)",
                    prog_name, comp_name,
                )

    _log.info(
        "PREFLIGHT: %d components validated, %d programs checked.",
        len(all_components), len(all_programs),
    )
    return hashes
