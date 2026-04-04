"""Runtime variable access tracking for Jinja2.

Instruments jinja2.runtime.Context.resolve_or_missing to record
which variables are actually resolved (non-missing) during render.

CONSTRAINT: This system assumes exclusive control of the Jinja2
runtime. Any concurrent or external use of Jinja2 Template.render()
during prompt compilation is unsupported. This is acceptable because
the project enforces single-process serial execution.
"""

from __future__ import annotations

import jinja2.runtime

from core.pipeline.prompting.exceptions import PromptCompilationError


class TrackingContext:
    """Context manager that records Jinja2 variable resolutions.

    Usage:
        with TrackingContext() as ctx:
            rendered = template.render(**variables)
        actually_accessed = ctx.accessed
    """

    def __init__(self) -> None:
        self._accessed: set[str] = set()
        self._original_resolve = None

    def __enter__(self) -> TrackingContext:
        self._original_resolve = jinja2.runtime.Context.resolve_or_missing
        accessed = self._accessed
        original = self._original_resolve

        def tracking_resolve(ctx_self, key):  # type: ignore[no-untyped-def]
            result = original(ctx_self, key)
            if result is not jinja2.runtime.missing:
                accessed.add(key)
            return result

        jinja2.runtime.Context.resolve_or_missing = tracking_resolve  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> bool:
        jinja2.runtime.Context.resolve_or_missing = self._original_resolve  # type: ignore[assignment]
        assert jinja2.runtime.Context.resolve_or_missing is self._original_resolve, (
            "TrackingContext: restore failed — Jinja2 runtime may be corrupted"
        )
        return False

    @property
    def accessed(self) -> frozenset[str]:
        """Variables that Jinja2 resolved to a non-missing value."""
        return frozenset(self._accessed)


# Module-level re-entrancy guard
_compiling = False


def enter_compilation() -> None:
    """Mark compilation as in progress. Raises on nested call."""
    global _compiling
    if _compiling:
        raise PromptCompilationError("Nested compilation detected")
    _compiling = True


def exit_compilation() -> None:
    """Mark compilation as complete."""
    global _compiling
    _compiling = False
