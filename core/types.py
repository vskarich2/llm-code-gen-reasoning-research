"""Shared foundational types for the T3 benchmark.

Contains only dataclass definitions — no logic, no side effects.
"""

from dataclasses import dataclass, field


@dataclass
class ParsedGenerationV2:
    """Canonical parsed v2 generation output."""

    # Core fields (unchanged interface)
    parse_status: str               # "success" | "partial" | "invalid" | "failed"
    schema_variant: str             # "baseline_v2" | "leg_v2" | "lean_v2"
    full_json: dict | None
    files_dict: dict | None
    parse_error: str | None
    raw_response_text: str
    parser_variant: str = "parser_v2_generation"
    validation_status: str = ""
    validation_errors: list[str] = field(default_factory=list)

    # Decomposed validity
    parse_valid: bool = False
    schema_valid: bool = False

    # Parser identity
    parser_tier: str = "execution"  # "execution" | "format" | "recovery"

    # Format diagnostic (format parser only)
    format_valid: bool = False
    format_error: str | None = None

    # Recovery diagnostic (recovery parser only)
    recovery_type: str | None = None
    recovery_steps: list[str] = field(default_factory=list)
    execution_equivalent: bool = True

    # Hardening signals
    possible_mis_extraction: bool = False
    schema_normalization_applied: bool = False


@dataclass
class AssemblyResult:
    code: str
    status: str  # SUCCESS | SYNTAX_ERROR | REWRITE_ERROR | ASSEMBLY_ERROR
    files_used: dict = field(default_factory=dict)  # path → "model" | "original" | "extra"
    rewrites_applied: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    # Compatibility fields (used by exec_eval)
    assembly_used: bool = False
    assembly_risky: bool = False
    rename_error: bool = False
    expected_func: str = ""
    duplicate_defs: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    # Qualified import resolution
    qualified_imports_resolved: list = field(default_factory=list)
    qualified_imports_failed: list = field(default_factory=list)
    qualified_import_warnings: list = field(default_factory=list)

    def __getitem__(self, key):
        """Dict-style access for backward compat with old tests."""
        return getattr(self, key)

    def get(self, key, default=None):
        """Dict-style .get() for backward compat."""
        return getattr(self, key, default)
