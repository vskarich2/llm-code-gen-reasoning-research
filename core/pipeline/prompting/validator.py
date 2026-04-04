"""Prompt validation: ordering, dependencies, collisions, inputs, structure.

All validation is fail-fast. No warning-only paths in strict mode.
"""

from __future__ import annotations

import heapq
import re
from enum import Enum

from core.pipeline.prompting.contracts import (
    ParsedSection,
    PromptComponent,
    PromptProgram,
)
from core.pipeline.prompting.exceptions import (
    PromptDependencyCycleError,
    PromptDependencyMissingError,
    PromptExtraInputError,
    PromptForbiddenCombinationError,
    PromptInputTypeError,
    PromptMissingInputError,
    PromptOrderingConflictError,
    PromptOutputContractMismatchError,
    PromptProgramStructureError,
    PromptSectionCollisionError,
)
from core.pipeline.prompting.sections import SINGLETON_SECTIONS, Section


class CompilerMode(str, Enum):
    MIGRATION = "migration"
    STRICT = "strict"


def resolve_order(components: list[PromptComponent]) -> list[PromptComponent]:
    """Topological sort with program-order tiebreak.

    Ordering edges from: dependencies, before, after.
    When multiple components are available (no constraint between them),
    the tiebreak preserves the original program component list order.
    This guarantees the caller-specified order is respected when no
    constraints force a different ordering.

    Cycle → PromptDependencyCycleError.
    Conflict → PromptOrderingConflictError.
    """
    names = {c.name for c in components}
    comp_by_name = {c.name: c for c in components}

    # Original position for stable tiebreak
    original_index = {c.name: i for i, c in enumerate(components)}

    # Build adjacency: edge (A, B) means A must come before B
    edges: set[tuple[str, str]] = set()

    for comp in components:
        for dep in comp.dependencies:
            if dep not in names:
                raise PromptDependencyMissingError(
                    f"Component '{comp.name}' depends on '{dep}' which is not "
                    f"in program. Present: {sorted(names)}"
                )
            edges.add((dep, comp.name))

        for after_name in comp.after:
            if after_name in names:
                edges.add((after_name, comp.name))

        for before_name in comp.before:
            if before_name in names:
                edges.add((comp.name, before_name))

    # Check for direct conflicts: A→B and B→A
    for a, b in edges:
        if (b, a) in edges:
            raise PromptOrderingConflictError(
                f"Ordering conflict: '{a}' must come before '{b}' AND "
                f"'{b}' must come before '{a}'"
            )

    # Kahn's algorithm with program-order tiebreak
    in_degree: dict[str, int] = {c.name: 0 for c in components}
    adj: dict[str, list[str]] = {c.name: [] for c in components}
    for a, b in edges:
        adj[a].append(b)
        in_degree[b] += 1

    # Priority queue: (original_index, name) for stable ordering
    queue = [(original_index[n], n) for n, d in in_degree.items() if d == 0]
    heapq.heapify(queue)
    result: list[str] = []

    while queue:
        _, node = heapq.heappop(queue)
        result.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                heapq.heappush(queue, (original_index[neighbor], neighbor))

    if len(result) != len(components):
        remaining = names - set(result)
        raise PromptDependencyCycleError(
            f"Cycle detected among components: {sorted(remaining)}"
        )

    return [comp_by_name[n] for n in result]


def check_forbidden_combinations(components: list[PromptComponent]) -> None:
    """Reject mutually exclusive component pairs."""
    names = {c.name for c in components}
    for comp in components:
        for forbidden in comp.forbidden_with:
            if forbidden in names:
                raise PromptForbiddenCombinationError(
                    f"Components '{comp.name}' and '{forbidden}' are "
                    f"mutually exclusive (forbidden_with)"
                )


def check_section_collisions(
    components: list[PromptComponent],
    program: PromptProgram,
) -> None:
    """Reject duplicate singleton section emissions."""
    allowed_multi = set(program.allow_multi_emit)
    owners: dict[Section, str] = {}

    for comp in components:
        for section in comp.exports:
            if section in owners and section not in allowed_multi:
                if section in SINGLETON_SECTIONS:
                    raise PromptSectionCollisionError(
                        f"Singleton section '{section.value}' emitted by both "
                        f"'{owners[section]}' and '{comp.name}'"
                    )
            owners[section] = comp.name


def validate_inputs(
    components: list[PromptComponent],
    render_vars: dict[str, str],
    program: PromptProgram,
    mode: CompilerMode,
) -> None:
    """Validate provided inputs against component contracts.

    Checks: missing required, extra undeclared, wrong type, conditional groups.
    """
    required_union: set[str] = set()
    optional_union: set[str] = set()
    all_declared: set[str] = set()

    for comp in components:
        required_union |= comp.required_inputs
        optional_union |= comp.optional_inputs
        all_declared |= comp.all_declared_inputs

        # Evaluate conditional groups
        for cg in comp.conditional_groups:
            try:
                active = cg.condition(render_vars)
            except Exception:
                active = False
            if active:
                required_union |= cg.required_inputs
                optional_union |= cg.optional_inputs
                all_declared |= cg.required_inputs | cg.optional_inputs

    # Missing required
    provided = set(render_vars.keys())
    missing = required_union - provided
    if missing:
        raise PromptMissingInputError(
            f"Program '{program.name}': missing required inputs "
            f"{sorted(missing)}"
        )

    # Extra inputs — controlled by program.strict, not compiler mode.
    # Compiler mode controls structural validation; program.strict controls
    # input validation. This allows STRICT structural checks while tolerating
    # extra variables during migration of call sites.
    extra = provided - all_declared
    if extra and program.strict:
        raise PromptExtraInputError(
            f"Program '{program.name}': unexpected inputs "
            f"{sorted(extra)}. Declared: {sorted(all_declared)}"
        )

    # Type validation
    for key, value in render_vars.items():
        if key in required_union:
            if not isinstance(value, str):
                raise PromptInputTypeError(
                    f"Input '{key}' must be str, got {type(value).__name__}"
                )
        elif key in optional_union:
            if value is not None and not isinstance(value, str):
                raise PromptInputTypeError(
                    f"Optional input '{key}' must be str or None, "
                    f"got {type(value).__name__}"
                )


def validate_program_structure(
    program: PromptProgram,
    sections: list[ParsedSection],
    mode: CompilerMode,
) -> None:
    """Validate compiled sections against program structural CLAUDE_RULES."""
    rendered_names = [s.name for s in sections]
    rendered_set = set(rendered_names)

    # Required sections
    for req in program.required_sections:
        if req not in rendered_set:
            if mode == CompilerMode.STRICT:
                raise PromptProgramStructureError(
                    f"Program '{program.name}': required section "
                    f"'{req.value}' not present in rendered output. "
                    f"Rendered: {[s.value for s in rendered_names]}"
                )

    # Disallowed sections
    allowed_set = set(program.allowed_sections)
    for section in rendered_set:
        if section not in allowed_set:
            if mode == CompilerMode.STRICT:
                raise PromptProgramStructureError(
                    f"Program '{program.name}': section '{section.value}' "
                    f"not in allowed_sections. "
                    f"Allowed: {[s.value for s in program.allowed_sections]}"
                )

    # Section order
    if program.section_order:
        order_index = {s: i for i, s in enumerate(program.section_order)}
        prev_idx = -1
        for section in rendered_names:
            if section in order_index:
                idx = order_index[section]
                if idx < prev_idx:
                    if mode == CompilerMode.STRICT:
                        raise PromptProgramStructureError(
                            f"Program '{program.name}': section "
                            f"'{section.value}' appears out of order"
                        )
                prev_idx = idx

    # Section semantics
    for section_enum, checks in program.section_semantics.items():
        matching = [s for s in sections if s.name == section_enum]
        for s in matching:
            for check in checks:
                if check.startswith("re:"):
                    if not re.search(check[3:], s.content):
                        raise PromptProgramStructureError(
                            f"Section '{section_enum.value}' does not match "
                            f"required pattern '{check}'"
                        )
                else:
                    if check not in s.content:
                        raise PromptProgramStructureError(
                            f"Section '{section_enum.value}' does not contain "
                            f"required substring '{check}'"
                        )


def validate_output_contract(
    program: PromptProgram,
    sections: list[ParsedSection],
) -> None:
    """Verify prompt is compatible with declared output contract."""
    if program.output_contract is None:
        return

    from core.contracts.contracts_v2 import SCHEMA_REQUIRED_FIELDS

    if program.output_contract not in SCHEMA_REQUIRED_FIELDS:
        raise PromptOutputContractMismatchError(
            f"Program '{program.name}' declares output_contract "
            f"'{program.output_contract}' not in SCHEMA_REQUIRED_FIELDS. "
            f"Known: {sorted(SCHEMA_REQUIRED_FIELDS.keys())}"
        )

    required_fields = SCHEMA_REQUIRED_FIELDS[program.output_contract]

    # Find OUTPUT_INSTRUCTION section
    oi_sections = [s for s in sections if s.name == Section.OUTPUT_INSTRUCTION]
    if not oi_sections:
        raise PromptOutputContractMismatchError(
            f"Program '{program.name}' declares output_contract "
            f"'{program.output_contract}' but has no OUTPUT_INSTRUCTION section"
        )

    oi_content = oi_sections[0].content
    missing = [f for f in required_fields if f'"{f}"' not in oi_content]
    if missing:
        raise PromptOutputContractMismatchError(
            f"Program '{program.name}' output_contract "
            f"'{program.output_contract}' requires fields "
            f"{sorted(required_fields)} but OUTPUT_INSTRUCTION does not "
            f"mention (quoted): {sorted(missing)}"
        )
