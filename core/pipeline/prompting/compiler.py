"""Prompt compiler — the SINGLE prompt construction path.

compile(program, inputs, mode) → CompiledPrompt

Six stages, each fail-fast:
1. Input normalization
2. Component resolution
3. Static validation (dependencies, ordering, collisions)
4. Input validation (required, extra, types, conditional groups)
5. Render with runtime access tracking
6. Post-compile validation (sections, structure, output contract, placeholders)

Compilation is atomic: returns CompiledPrompt or raises. No partial state.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import jinja2

from core.pipeline.prompting.contracts import CompiledPrompt, PromptProgram
from core.pipeline.prompting.exceptions import (
    PromptCompilationError,
    PromptRenderedSectionMismatchError,
    PromptSectionParseError,
    PromptUnresolvedPlaceholderError,
)
from core.pipeline.prompting.section_parser import parse_sections, strip_markers
from core.pipeline.prompting.tracking import TrackingContext, enter_compilation, exit_compilation
from core.pipeline.prompting.validator import (
    CompilerMode,
    check_forbidden_combinations,
    check_section_collisions,
    resolve_order,
    validate_inputs,
    validate_output_contract,
    validate_program_structure,
)

_log = logging.getLogger("t3.prompt_compiler")

# Marker escaping for input sanitization
_MARKER_START = "<<SECTION:"
_MARKER_END = "<<END_SECTION:"


def _sanitize_render_vars(variables: dict[str, str]) -> dict[str, str]:
    """Escape section marker syntax in all input values.

    Prevents marker injection: a variable value containing
    <<SECTION:task_context>> would corrupt the section parser.
    """
    sanitized = {}
    for key, value in variables.items():
        if _MARKER_START in value or _MARKER_END in value:
            value = value.replace(_MARKER_START, "\\<<SECTION:")
            value = value.replace(_MARKER_END, "\\<<END_SECTION:")
        sanitized[key] = value
    return sanitized


def compile(
    program: PromptProgram,
    inputs: dict[str, str],
    mode: CompilerMode = CompilerMode.STRICT,
    registry: Any = None,
) -> CompiledPrompt:
    """Compile a prompt program into a final prompt artifact.

    Args:
        program: Typed composition spec.
        inputs: Render-ready string dict (from normalizer or direct).
        mode: STRICT (production) or MIGRATION (transitional).
        registry: Component registry. If None, uses module-level default.

    Returns:
        CompiledPrompt — frozen, auditable artifact.

    Raises:
        PromptError subclass on any validation, compilation, or structural failure.
    """
    enter_compilation()
    try:
        return _compile_inner(program, inputs, mode, registry)
    except Exception:
        raise
    finally:
        exit_compilation()


def _compile_inner(
    program: PromptProgram,
    inputs: dict[str, str],
    mode: CompilerMode,
    registry: Any,
) -> CompiledPrompt:
    """Inner compilation logic. All six stages."""
    if registry is None:
        raise PromptCompilationError(
            "No registry provided. Pass registry= or set module default."
        )

    # ── Stage 1: Input normalization ──
    render_vars = {k: (v if v is not None else "") for k, v in inputs.items()}

    # ── Stage 2: Component resolution ──
    components = []
    for name in program.components:
        comp = registry.get(name)
        components.append(comp)

    # ── Stage 3: Static validation ──
    ordered = resolve_order(components)
    check_forbidden_combinations(ordered)
    check_section_collisions(ordered, program)

    # ── Stage 4: Input validation ──
    validate_inputs(ordered, render_vars, program, mode)

    # ── Stage 5: Render with tracking ──
    safe_vars = _sanitize_render_vars(render_vars)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)

    all_parts: list[str] = []
    component_accessed: dict[str, tuple[str, ...]] = {}

    for comp in ordered:
        with TrackingContext() as ctx:
            template = env.from_string(comp.raw_template)
            rendered = template.render(**safe_vars)
        all_parts.append(rendered)
        component_accessed[comp.name] = tuple(sorted(ctx.accessed))

    raw_rendered = "".join(all_parts)
    all_accessed = frozenset().union(
        *(set(v) for v in component_accessed.values())
    )

    # ── Stage 6: Post-compile validation ──
    sections, parse_errors = parse_sections(raw_rendered)

    if parse_errors:
        if mode == CompilerMode.STRICT:
            raise PromptSectionParseError(
                f"Section parse errors in '{program.name}': {parse_errors}"
            )
        else:
            _log.warning(
                "Section parse errors (migration mode, non-fatal): %s",
                parse_errors,
            )

    # Structural validation: declared vs rendered sections
    sections_declared: list[str] = []
    for comp in ordered:
        sections_declared.extend(s.value for s in comp.exports)
    sections_declared_tuple = tuple(sections_declared)

    sections_rendered_tuple = tuple(s.name.value for s in sections)
    structural_valid = (sections_declared_tuple == sections_rendered_tuple)

    if not structural_valid and mode == CompilerMode.STRICT and sections_declared_tuple:
        raise PromptRenderedSectionMismatchError(
            f"Declared sections {sections_declared_tuple} != "
            f"rendered sections {sections_rendered_tuple}"
        )

    # Program structure checks
    validate_program_structure(program, sections, mode)

    # Output contract
    if mode == CompilerMode.STRICT:
        validate_output_contract(program, sections)

    # Final prompt: strip markers from raw render.
    # Sections are used for structural validation, not reconstruction.
    # strip_markers preserves all non-marker content including whitespace,
    # ensuring byte equivalence with the pre-marker template output.
    # reconstruct_from_sections is available for future use when programs
    # need explicit re-ordering, but is not used by default.
    final_prompt = strip_markers(raw_rendered)

    # Unresolved placeholder check
    if re.search(r"\{\{.*?\}\}", final_prompt):
        raise PromptUnresolvedPlaceholderError(
            f"Unresolved placeholders in compiled prompt for '{program.name}'"
        )

    # Hashes
    final_prompt_hash = hashlib.sha256(final_prompt.encode()).hexdigest()

    composition_parts = "|".join([
        program.name,
        ",".join(c.name for c in ordered),
        ",".join(c.content_hash for c in ordered),
        ",".join(s.value for s in program.section_order),
        program.output_contract or "",
    ])
    composition_hash = hashlib.sha256(composition_parts.encode()).hexdigest()

    provided = tuple(sorted(render_vars.keys()))
    accessed = tuple(sorted(all_accessed))
    unused = tuple(sorted(set(render_vars.keys()) - all_accessed))

    # Provenance
    provenance = _build_provenance(
        program, ordered, render_vars, all_accessed, sections,
        final_prompt_hash, composition_hash,
    )

    return CompiledPrompt(
        program_name=program.name,
        condition=program.condition,
        output_contract=program.output_contract,
        compiler_mode=mode.value,
        component_order=tuple(c.name for c in ordered),
        component_versions=tuple(c.version for c in ordered),
        component_hashes=tuple(c.content_hash for c in ordered),
        sections_declared=sections_declared_tuple,
        sections_rendered=sections_rendered_tuple,
        structural_valid=structural_valid,
        required_inputs_union=frozenset().union(
            *(c.required_inputs for c in ordered)
        ),
        optional_inputs_union=frozenset().union(
            *(c.optional_inputs for c in ordered)
        ),
        provided_inputs=provided,
        accessed_inputs=accessed,
        unused_inputs=unused,
        component_accessed_inputs=component_accessed,
        final_prompt=final_prompt,
        final_prompt_hash=final_prompt_hash,
        composition_hash=composition_hash,
        provenance=provenance,
    )


def _build_provenance(
    program: PromptProgram,
    ordered: list,
    render_vars: dict[str, str],
    accessed: frozenset[str],
    sections: list,
    final_hash: str,
    comp_hash: str,
) -> dict[str, Any]:
    """Build serializable provenance record."""
    return {
        "program_name": program.name,
        "condition": program.condition,
        "output_contract": program.output_contract,
        "components": [
            {
                "name": c.name,
                "version": c.version,
                "content_hash": c.content_hash,
                "required_inputs": sorted(c.required_inputs),
                "exports": [s.value for s in c.exports],
            }
            for c in ordered
        ],
        "inputs_provided": sorted(render_vars.keys()),
        "inputs_accessed": sorted(accessed),
        "inputs_unused": sorted(set(render_vars.keys()) - accessed),
        "sections_declared": [s.value for s in sum(
            (list(c.exports) for c in ordered), []
        )],
        "sections_rendered": [s.name.value for s in sections],
        "final_prompt_hash": final_hash,
        "composition_hash": comp_hash,
    }
