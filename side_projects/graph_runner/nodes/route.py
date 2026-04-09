"""RouteNode — select the best parse result for downstream processing.

Reimplements routing logic from execution_v2.py.
Cannot import execution_v2.py per migration plan constraints.

Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    ATTR_EXECUTION_EQUIVALENT,
    ATTR_FILES_DICT,
    ATTR_PARSE_VALID,
    CASE_FIELD_LOGICAL_FILE_KEYS,
    FIELD_DIVERGENCE_DETECTED,
    FIELD_RECOVERY_PARSE_VALID,
    FIELD_RECOVERY_STRUCTURALLY_VALID,
    FIELD_RECOVERY_USED,
    FIELD_SELECTED_SOURCE,
    FIELD_STRICT_PARSE_VALID,
    FIELD_STRICT_STRUCTURALLY_VALID,
    FIELD_STRUCTURAL_ERRORS,
    FILE_MARKER_UNCHANGED,
    KEY_CASE,
    KEY_FORMAT_PARSE,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_RECOVERY_PARSE,
    KEY_RETRY_ELIGIBLE,
    KEY_ROUTING,
    KEY_STRICT_PARSE,
    NODE_TYPE_PURE,
    PARSE_MODE_FAILED,
    PARSE_MODE_RECOVERED,
    PARSE_MODE_STRICT,
    ROUTE_SOURCE_NONE,
    ROUTE_SOURCE_RECOVERY,
    ROUTE_SOURCE_STRICT,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class RoutingDecision:
    """Lightweight routing decision record."""

    __slots__ = (
        FIELD_SELECTED_SOURCE, FIELD_STRICT_PARSE_VALID,
        FIELD_RECOVERY_PARSE_VALID, FIELD_STRICT_STRUCTURALLY_VALID,
        FIELD_RECOVERY_STRUCTURALLY_VALID, FIELD_RECOVERY_USED,
        FIELD_DIVERGENCE_DETECTED, FIELD_STRUCTURAL_ERRORS,
    )

    def __init__(
        self,
        selected_source: str,
        strict_parse_valid: bool,
        recovery_parse_valid: bool,
        strict_structurally_valid: bool,
        recovery_structurally_valid: bool,
        recovery_used: bool,
        divergence_detected: bool,
        structural_errors: list[str],
    ) -> None:
        self.selected_source = selected_source
        self.strict_parse_valid = strict_parse_valid
        self.recovery_parse_valid = recovery_parse_valid
        self.strict_structurally_valid = strict_structurally_valid
        self.recovery_structurally_valid = recovery_structurally_valid
        self.recovery_used = recovery_used
        self.divergence_detected = divergence_detected
        self.structural_errors = structural_errors


def validate_structure(parsed: Any, case: dict) -> tuple[bool, list[str]]:
    """Check structural validity of a parsed generation.

    Returns (structurally_valid, errors).
    """
    if not getattr(parsed, ATTR_PARSE_VALID, False):
        return False, ["parse invalid"]

    files_dict = getattr(parsed, ATTR_FILES_DICT, None) or {}
    expected = list((case.get(CASE_FIELD_LOGICAL_FILE_KEYS) or {}).keys())
    observed = list(files_dict.keys())
    errors: list[str] = []

    expected_basenames = {p.split("/")[-1] for p in expected}
    observed_basenames = {p.split("/")[-1] for p in observed}

    missing = set(expected) - set(observed)
    missing_basenames = expected_basenames - observed_basenames
    if missing and missing_basenames:
        errors.append(f"missing files: {sorted(missing)}")

    if len(observed) != len(set(observed)):
        seen: set[str] = set()
        dupes = [f for f in observed if f in seen or seen.add(f)]  # type: ignore[func-returns-value]
        errors.append(f"duplicate file keys: {dupes}")

    for fname, content in files_dict.items():
        if content is not None and not isinstance(content, str):
            errors.append(f"non-string content for {fname}")
        elif content is not None and content.strip() == "":
            errors.append(f"empty content for {fname}")

    all_unchanged = all(
        v == FILE_MARKER_UNCHANGED or v is None
        for v in files_dict.values()
    )
    if all_unchanged and files_dict:
        errors.append("all files marked UNCHANGED (no change)")

    return len(errors) == 0, errors


class RouteNode(BaseNode):
    NAME = "RouteNode"
    INPUT_KEYS = frozenset({
        KEY_STRICT_PARSE, KEY_RECOVERY_PARSE,
        KEY_FORMAT_PARSE, KEY_CASE,
    })
    OUTPUT_KEYS = frozenset({
        KEY_PARSED_GENERATION, KEY_ROUTING,
        KEY_PARSE_MODE, KEY_RETRY_ELIGIBLE,
    })
    NODE_TYPE = NODE_TYPE_PURE

    def __init__(self, recovery_execution: bool = True) -> None:
        self.recovery_execution = recovery_execution

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        strict = inputs[KEY_STRICT_PARSE]
        recovery = inputs[KEY_RECOVERY_PARSE]
        case = inputs[KEY_CASE]

        strict_valid, strict_errs = validate_structure(strict, case)
        recovery_valid, recovery_errs = validate_structure(
            recovery, case,
        )

        divergence = (
            getattr(strict, ATTR_PARSE_VALID, False)
            and getattr(recovery, ATTR_PARSE_VALID, False)
            and strict_valid and recovery_valid
            and not getattr(recovery, ATTR_EXECUTION_EQUIVALENT, True)
        )

        if (
            getattr(strict, ATTR_PARSE_VALID, False)
            and strict_valid
        ):
            selected = ROUTE_SOURCE_STRICT
            recovery_used = False
        elif (
            self.recovery_execution
            and getattr(recovery, ATTR_PARSE_VALID, False)
            and recovery_valid
        ):
            selected = ROUTE_SOURCE_RECOVERY
            recovery_used = True
        else:
            selected = ROUTE_SOURCE_NONE
            recovery_used = False

        routing = RoutingDecision(
            selected_source=selected,
            strict_parse_valid=getattr(strict, ATTR_PARSE_VALID, False),
            recovery_parse_valid=getattr(recovery, ATTR_PARSE_VALID, False),
            strict_structurally_valid=strict_valid,
            recovery_structurally_valid=recovery_valid,
            recovery_used=recovery_used,
            divergence_detected=divergence,
            structural_errors=strict_errs + recovery_errs,
        )

        parsed_gen = (
            recovery if selected == ROUTE_SOURCE_RECOVERY else strict
        )

        if selected == ROUTE_SOURCE_NONE:
            parse_mode = PARSE_MODE_FAILED
        elif selected == ROUTE_SOURCE_RECOVERY:
            parse_mode = PARSE_MODE_RECOVERED
        else:
            parse_mode = PARSE_MODE_STRICT

        retry_eligible = strict_valid or recovery_valid

        return NodeResult(outputs={
            KEY_PARSED_GENERATION: parsed_gen,
            KEY_ROUTING: routing,
            KEY_PARSE_MODE: parse_mode,
            KEY_RETRY_ELIGIBLE: retry_eligible,
        })
