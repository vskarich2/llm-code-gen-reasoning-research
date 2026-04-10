"""Structured warning logger for pipeline nodes.

Emits structured warning records via the stdlib logging module.
Does NOT raise exceptions. Does NOT write to WAL.
Intended for validation warnings that must be visible but not fatal.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("t3.node_validation")


def log_node_warning(
    *,
    node: str,
    message: str,
    state: dict[str, Any] | None = None,
) -> None:
    """Log a structured validation warning for a pipeline node.

    Args:
        node: Name of the node that detected the violation.
        message: Human-readable description of the violation.
        state: Current pipeline state dict (used to extract case_id
               and condition for context). May be None.
    """
    case_id = ""
    condition = ""
    if state is not None:
        case_id = _safe_extract_case_id(state)
        condition = state.get("condition", "")

    _log.warning(
        "[NODE_VALIDATION] node=%s case=%s condition=%s | %s",
        node,
        case_id,
        condition,
        message,
    )


def _safe_extract_case_id(state: dict[str, Any]) -> str:
    """Extract case_id from state without crashing."""
    case = state.get("case")
    if isinstance(case, dict):
        return case.get("id", "")
    return ""
