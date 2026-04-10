"""Typed error classes for the execution engine.

Every failure mode has a dedicated exception type.
No generic exceptions. No silent downgrades.
"""

from __future__ import annotations


class GraphValidationError(Exception):
    """Graph structure is invalid (cycles, missing nodes, impossible deps)."""


class DeadGraphError(Exception):
    """No nodes are runnable but unresolved nodes remain."""


class NodeExecutionError(Exception):
    """A node's executor raised during execution."""

    def __init__(self, node_name: str, cause: Exception) -> None:
        self.node_name = node_name
        self.cause = cause
        super().__init__(f"Node {node_name!r} failed: {cause}")


class NodeContractError(Exception):
    """A node produced outputs that violate its contract."""

    def __init__(self, node_name: str, detail: str) -> None:
        self.node_name = node_name
        self.detail = detail
        super().__init__(f"Node {node_name!r} contract: {detail}")


class MergeConflictError(Exception):
    """A merge would overwrite an existing state key."""

    def __init__(
        self, key: str, existing_producer: str, new_producer: str,
    ) -> None:
        self.key = key
        self.existing_producer = existing_producer
        self.new_producer = new_producer
        super().__init__(
            f"Key {key!r} already produced by "
            f"{existing_producer!r}, cannot be written by "
            f"{new_producer!r}"
        )


class GuardEvaluationError(Exception):
    """A node's guard function raised during evaluation."""

    def __init__(self, node_name: str, cause: Exception) -> None:
        self.node_name = node_name
        self.cause = cause
        super().__init__(f"Guard for {node_name!r} failed: {cause}")


class NodeTimeoutError(Exception):
    """A node exceeded its configured timeout."""

    def __init__(self, node_name: str, timeout_s: float) -> None:
        self.node_name = node_name
        self.timeout_s = timeout_s
        super().__init__(
            f"Node {node_name!r} exceeded timeout of {timeout_s}s"
        )
