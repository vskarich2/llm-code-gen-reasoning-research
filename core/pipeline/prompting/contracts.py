"""Core case_data contracts for the prompt compilation system.

All frozen dataclasses. No mutation after construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from core.pipeline.prompting.sections import Section


@dataclass(frozen=True)
class ConditionalGroup:
    """A group of inputs that become required under a condition.

    The condition is a callable compiled from condition_expr via the
    restricted expression engine. It takes the full input dict and
    returns bool.
    """

    name: str
    condition: Callable[[dict[str, Any]], bool]
    condition_expr: str
    required_inputs: frozenset[str]
    optional_inputs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PromptComponent:
    """Full contract for a single prompt template.

    ALL contract fields come from component_metadata.yaml.
    AST is used only for drift detection, never as authoritative source.
    """

    name: str
    version: str
    path: Path
    content_hash: str
    raw_template: str

    # Input contract (from metadata)
    required_inputs: frozenset[str]
    optional_inputs: frozenset[str]
    control_inputs: frozenset[str]
    input_types: dict[str, str]
    conditional_groups: tuple[ConditionalGroup, ...]

    # Structural contract (from metadata)
    exports: tuple[Section, ...]
    dependencies: tuple[str, ...]
    before: tuple[str, ...]
    after: tuple[str, ...]
    forbidden_with: tuple[str, ...]

    # Metadata
    description: str
    tags: tuple[str, ...]

    @property
    def all_declared_inputs(self) -> frozenset[str]:
        """All inputs this component knows about."""
        base = self.required_inputs | self.optional_inputs | self.control_inputs
        for cg in self.conditional_groups:
            base = base | cg.required_inputs | cg.optional_inputs
        return base


@dataclass(frozen=True)
class ParsedSection:
    """A section extracted from rendered output by the section parser."""

    name: Section
    content: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class PromptProgram:
    """Typed composition spec declaring what a prompt consists of."""

    name: str
    condition: str
    components: tuple[str, ...]

    # Structural CLAUDE_RULES
    required_sections: tuple[Section, ...]
    allowed_sections: tuple[Section, ...]
    section_order: tuple[Section, ...]
    allow_multi_emit: tuple[Section, ...] = ()

    # Section content checks: Section → list of required substrings/patterns.
    # Strings prefixed with "re:" are regex; otherwise substring match.
    section_semantics: dict[Section, list[str]] = field(default_factory=dict)

    # Downstream linkage
    output_contract: str | None = None

    strict: bool = True


@dataclass(frozen=True)
class CompiledPrompt:
    """Immutable artifact from prompt compilation.

    Every field name reflects an actual guarantee:
    - accessed_inputs: runtime observation from TrackingContext
    - sections_rendered: actual markers found by parser
    - structural_valid: real comparison, not echoed declaration
    - component_versions: human-managed semantic versions
    - component_hashes: SHA-256 content integrity fingerprints
    """

    # Identity
    program_name: str
    condition: str
    output_contract: str | None
    compiler_mode: str

    # Composition
    component_order: tuple[str, ...]
    component_versions: tuple[str, ...]
    component_hashes: tuple[str, ...]

    # Structural validation
    sections_declared: tuple[str, ...]
    sections_rendered: tuple[str, ...]
    structural_valid: bool

    # Input tracking
    required_inputs_union: frozenset[str]
    optional_inputs_union: frozenset[str]
    provided_inputs: tuple[str, ...]
    accessed_inputs: tuple[str, ...]
    unused_inputs: tuple[str, ...]

    # Per-component runtime access
    component_accessed_inputs: Mapping[str, tuple[str, ...]]

    # Output
    final_prompt: str
    final_prompt_hash: str
    composition_hash: str

    # Provenance
    provenance: dict[str, Any]
