"""Prompt compilation error hierarchy.

Every error type corresponds to a specific failure mode.
No generic catch-alls. No warning-only paths in strict mode.
"""


class PromptError(Exception):
    """Base class for all prompt compilation errors."""


# ── Registry / load errors ──


class PromptRegistryError(PromptError):
    """Registry load or lookup failure."""


class UnknownPromptComponentError(PromptRegistryError):
    """Component name not found in registry."""


class DuplicatePromptComponentError(PromptRegistryError):
    """Two components registered with the same name."""


class PromptForbiddenConstructError(PromptRegistryError):
    """Component uses a banned Jinja2 tag (for, macro, set, etc.)."""


class PromptMetadataDriftError(PromptRegistryError):
    """Metadata declares variable not referenced in template (and not control),
    or template references variable not declared in metadata."""


class PromptUndeclaredVariableError(PromptRegistryError):
    """Template references a variable not declared in metadata."""


class PromptVersionDriftError(PromptRegistryError):
    """Content hash changed but version was not bumped."""


# ── Validation errors ──


class PromptValidationError(PromptError):
    """Input or composition validation failure."""


class PromptMissingInputError(PromptValidationError):
    """Required input not provided."""


class PromptExtraInputError(PromptValidationError):
    """Input provided that no component requires or accepts."""


class PromptInputTypeError(PromptValidationError):
    """Input value has wrong type."""


class PromptOrderingConflictError(PromptValidationError):
    """Component ordering constraints are contradictory."""


class PromptDependencyCycleError(PromptValidationError):
    """Circular dependency detected among components."""


class PromptDependencyMissingError(PromptValidationError):
    """Component declares dependency on an absent component."""


class PromptSectionCollisionError(PromptValidationError):
    """Two components emit the same singleton section."""


class PromptForbiddenCombinationError(PromptValidationError):
    """Two components declared as mutually exclusive are both present."""


class PromptProgramStructureError(PromptValidationError):
    """Compiled prompt violates program-level section CLAUDE_RULES."""


class PromptOutputContractMismatchError(PromptValidationError):
    """Program output_contract references unknown schema or prompt
    instruction text is incompatible with schema fields."""


# ── Compilation errors ──


class PromptCompilationError(PromptError):
    """Render-time or post-render failure."""


class PromptUnresolvedPlaceholderError(PromptCompilationError):
    """Final prompt contains unresolved {{ }} placeholders."""


class PromptRenderedSectionMismatchError(PromptCompilationError):
    """Rendered section markers do not match component declared exports."""


class PromptSectionParseError(PromptCompilationError):
    """Section marker parsing failed — malformed, nested, or unpaired markers."""
