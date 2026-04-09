"""Strict merge — no overwrites, producer tracking, atomic commit.

Successful node outputs are committed. Failed node outputs are discarded.
Every key in state.values has a corresponding entry in state.producers.
"""

from __future__ import annotations

from typing import Any, Mapping

from side_projects.graph_runner.engine.errors import MergeConflictError
from side_projects.graph_runner.engine.types import ExecutionState, NodeResult


def merge_node_result(
    state: ExecutionState,
    node_name: str,
    result: NodeResult,
) -> ExecutionState:
    """Merge a node's outputs into state. Returns new immutable state.

    Raises MergeConflictError if any output key already exists.
    """
    new_values = dict(state.values)
    new_producers = dict(state.producers)

    for key, value in result.outputs.items():
        if key in new_values:
            raise MergeConflictError(
                key=key,
                existing_producer=new_producers.get(key, "seed"),
                new_producer=node_name,
            )
        new_values[key] = value
        new_producers[key] = node_name

    return ExecutionState(
        values=new_values,
        producers=new_producers,
        completed_nodes=state.completed_nodes | {node_name},
        failed_nodes=state.failed_nodes,
        skipped_nodes=state.skipped_nodes,
        skip_reasons=state.skip_reasons,
        invariant_violations=state.invariant_violations,
    )


def mark_failed(
    state: ExecutionState, node_name: str,
) -> ExecutionState:
    """Mark a node as failed. Does NOT merge outputs."""
    return ExecutionState(
        values=state.values,
        producers=state.producers,
        completed_nodes=state.completed_nodes,
        failed_nodes=state.failed_nodes | {node_name},
        skipped_nodes=state.skipped_nodes,
        skip_reasons=state.skip_reasons,
        invariant_violations=state.invariant_violations,
    )


def mark_skipped(
    state: ExecutionState, node_name: str, reason: str,
) -> ExecutionState:
    """Mark a node as skipped with an explicit reason."""
    new_skip_reasons = dict(state.skip_reasons)
    new_skip_reasons[node_name] = reason
    return ExecutionState(
        values=state.values,
        producers=state.producers,
        completed_nodes=state.completed_nodes,
        failed_nodes=state.failed_nodes,
        skipped_nodes=state.skipped_nodes | {node_name},
        skip_reasons=new_skip_reasons,
        invariant_violations=state.invariant_violations,
    )


def add_invariant_violations(
    state: ExecutionState,
    violations: tuple,
) -> ExecutionState:
    """Append invariant violations to state."""
    if not violations:
        return state
    return ExecutionState(
        values=state.values,
        producers=state.producers,
        completed_nodes=state.completed_nodes,
        failed_nodes=state.failed_nodes,
        skipped_nodes=state.skipped_nodes,
        skip_reasons=state.skip_reasons,
        invariant_violations=state.invariant_violations + violations,
    )
