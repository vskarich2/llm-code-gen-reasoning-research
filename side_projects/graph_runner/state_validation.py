"""Runtime validation for typed state values.

Each function validates that a value belongs to its closed enum set.
Called by BaseNode.run() after execute() returns.
Raises ValueError on invalid values — fail fast, no silent corruption.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    KEY_EXECUTION_RESULT,
    KEY_PARSE_MODE,
    KEY_ROUTING,
    VALID_EXEC_CATEGORIES,
    VALID_PARSE_MODES,
    VALID_ROUTE_SOURCES,
    FIELD_SELECTED_SOURCE,
    EXEC_KEY_EXECUTION_CATEGORY,
)


def validate_parse_mode(value: str) -> None:
    """Validate parse_mode is a member of VALID_PARSE_MODES."""
    if value not in VALID_PARSE_MODES:
        raise ValueError(
            f"Invalid parse mode: {value!r}. "
            f"Must be one of {sorted(VALID_PARSE_MODES)}"
        )


def validate_routing_source(value: str) -> None:
    """Validate routing selected_source is a member of VALID_ROUTE_SOURCES."""
    if value not in VALID_ROUTE_SOURCES:
        raise ValueError(
            f"Invalid routing source: {value!r}. "
            f"Must be one of {sorted(VALID_ROUTE_SOURCES)}"
        )


def validate_routing(routing: dict[str, Any]) -> None:
    """Validate a routing decision dict."""
    source = routing.get(FIELD_SELECTED_SOURCE)
    if source is None:
        raise ValueError(
            f"Routing dict missing {FIELD_SELECTED_SOURCE!r}"
        )
    validate_routing_source(source)


def validate_execution_category(value: str) -> None:
    """Validate execution category is a member of VALID_EXEC_CATEGORIES."""
    if value not in VALID_EXEC_CATEGORIES:
        raise ValueError(
            f"Invalid execution category: {value!r}. "
            f"Must be one of {sorted(VALID_EXEC_CATEGORIES)}"
        )


def validate_execution_result(result: dict[str, Any]) -> None:
    """Validate an execution result dict."""
    category = result.get(EXEC_KEY_EXECUTION_CATEGORY)
    if category is not None:
        validate_execution_category(category)


def validate_node_outputs(outputs: dict[str, Any]) -> None:
    """Validate all typed enum fields in node outputs.

    Called by BaseNode.run() after execute() completes.
    Checks every output key that has a closed enum constraint.
    """
    if KEY_PARSE_MODE in outputs:
        validate_parse_mode(outputs[KEY_PARSE_MODE])

    if KEY_ROUTING in outputs:
        routing = outputs[KEY_ROUTING]
        if hasattr(routing, FIELD_SELECTED_SOURCE):
            validate_routing_source(
                getattr(routing, FIELD_SELECTED_SOURCE),
            )
        elif isinstance(routing, dict):
            validate_routing(routing)

    if KEY_EXECUTION_RESULT in outputs:
        result = outputs[KEY_EXECUTION_RESULT]
        if isinstance(result, dict):
            validate_execution_result(result)
