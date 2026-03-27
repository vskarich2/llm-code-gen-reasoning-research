"""Assembly engine — the SINGLE prompt construction path.

ENFORCEMENT INVARIANT:

All prompts MUST be constructed via build() in this module.
This module defines the ONLY valid prompt construction path.

Forbidden outside this module and prompt_registry.py:
  - direct registry access (get_component, get_nudge_text, registry["..."])
  - raw template usage (component.raw_text)
  - string-based prompt construction (.format(), f-strings for prompts)

Any violation must be caught by tests in:
  tests/test_assembly_engine.py::TestEnforcement

Phase 2: Build + render. Components come from the prompt registry.
"""

import hashlib
import logging
from dataclasses import dataclass, field

from jinja2 import Environment, StrictUndefined

from prompt_registry import get_component, get_nudge_text, get_cge_instruction, is_loaded

_log = logging.getLogger("t3.assembly")

# Single Jinja2 environment — StrictUndefined ensures missing variables are fatal
_env = Environment(undefined=StrictUndefined)


@dataclass(frozen=True)
class RenderedPrompt:
    """Immutable artifact representing one fully assembled prompt."""

    final_prompt: str
    component_names: tuple[str, ...]
    component_hashes: tuple[str, ...]
    variables_used: tuple[str, ...]
    plan_hash: str
    final_prompt_hash: str


def resolve_nudge(key: str) -> str:
    """Resolve a nudge text entry from the registry. Called by execution code
    to get nudge text without importing prompt_registry directly."""
    return get_nudge_text(key)


def resolve_cge_instruction(key: str) -> str:
    """Resolve a CGE instruction from the registry."""
    return get_cge_instruction(key)


def build(components: list[str], variables: dict[str, str]) -> RenderedPrompt:
    """Build a prompt from named components and variables.

    This is the ONE function that constructs prompts. No exceptions.

    Args:
        components: Ordered list of component names from the registry.
        variables: Dict of variable_name -> value for rendering.

    Returns:
        RenderedPrompt with the final string and full provenance.

    Raises:
        RuntimeError: If registry is not loaded.
        KeyError: If a component name is not found.
        jinja2.UndefinedError: If a required variable is missing.
    """
    if not is_loaded():
        raise RuntimeError(
            "Prompt registry not loaded. Call load_prompt_registry() before building prompts."
        )

    if not components:
        raise ValueError("ASSEMBLY ERROR: components list is empty.")

    rendered_parts = []
    comp_names = []
    comp_hashes = []
    all_vars_used = set()

    for comp_name in components:
        comp = get_component(comp_name)
        comp_names.append(comp.name)
        comp_hashes.append(comp.content_hash)
        for var in comp.required_variables:
            if var in variables:
                all_vars_used.add(var)

        # Render with StrictUndefined — missing variable = fatal error
        template = _env.from_string(comp.raw_text)
        rendered = template.render(**variables)
        rendered_parts.append(rendered)

    # Direct concatenation — components own their own whitespace/separators.
    # This matches the old system's behavior where base + nudge are concatenated directly.
    final_prompt = "".join(rendered_parts)

    # Compute hashes
    plan_hash = hashlib.sha256(
        "|".join(f"{n}:{h}" for n, h in zip(comp_names, comp_hashes)).encode()
    ).hexdigest()[:16]

    final_prompt_hash = hashlib.sha256(final_prompt.encode("utf-8")).hexdigest()[:16]

    return RenderedPrompt(
        final_prompt=final_prompt,
        component_names=tuple(comp_names),
        component_hashes=tuple(comp_hashes),
        variables_used=tuple(sorted(all_vars_used)),
        plan_hash=plan_hash,
        final_prompt_hash=final_prompt_hash,
    )
