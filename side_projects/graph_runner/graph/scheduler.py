"""Sequential execution engine — v1.

Deterministic: same graph + same inputs = identical execution order + state.
No threads. No retry. No experiment policy. Pure execution.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from side_projects.graph_runner.graph.errors import (
    DeadGraphError,
    GuardEvaluationError,
    NodeContractError,
    NodeExecutionError,
)
from side_projects.graph_runner.graph.merge import (
    mark_failed,
    mark_skipped,
    merge_node_result,
)
from side_projects.graph_runner.graph.types import (
    ExecutionContext,
    ExecutionState,
    ExecutionSummary,
    GraphSpec,
    NodeResult,
    NodeSpec,
    SKIP_GUARD_FALSE,
    SKIP_UNSATISFIABLE_INPUTS,
    SKIP_UPSTREAM_FAILED,
)
from side_projects.graph_runner.graph.graph_validation import (
    compute_topological_order,
    validate_graph,
)

log = logging.getLogger("t3.engine")


# ============================================================
# READINESS
# ============================================================

def is_resolved(node: NodeSpec, state: ExecutionState) -> bool:
    """A node is resolved if completed, failed, or skipped."""
    return (
        node.name in state.completed_nodes
        or node.name in state.failed_nodes
        or node.name in state.skipped_nodes
    )


def is_ready(node: NodeSpec, state: ExecutionState) -> bool:
    """A node is ready iff:
    1. NOT resolved
    2. ALL input_keys exist in state.values
    3. guard is None OR guard(state.values) == True
    """
    if is_resolved(node, state):
        return False
    if not node.input_keys.issubset(state.values.keys()):
        return False
    if node.guard is not None:
        try:
            return node.guard(state.values)
        except Exception:
            return False
    return True


def get_downstream_nodes(
    node_name: str, graph: GraphSpec,
) -> frozenset[str]:
    """Return all nodes transitively downstream of node_name."""
    adj: dict[str, list[str]] = {n.name: [] for n in graph.nodes}
    for edge in graph.edges:
        adj[edge.src].append(edge.dst)

    visited: set[str] = set()
    stack = list(adj.get(node_name, []))
    while stack:
        n = stack.pop()
        if n not in visited:
            visited.add(n)
            stack.extend(adj.get(n, []))
    return frozenset(visited)


# ============================================================
# CONTRACT VALIDATION
# ============================================================

def validate_node_contract(
    node: NodeSpec, result: NodeResult,
) -> None:
    """Validate that result matches node's declared contract."""
    produced = frozenset(result.outputs.keys())
    missing = node.output_keys - produced
    extra = produced - node.output_keys
    if missing:
        raise NodeContractError(
            node.name,
            f"missing declared outputs: {sorted(missing)}",
        )
    if extra:
        raise NodeContractError(
            node.name,
            f"undeclared outputs: {sorted(extra)}",
        )


# ============================================================
# NODE EXECUTION
# ============================================================

def execute_node(
    node: NodeSpec,
    state: ExecutionState,
    context: ExecutionContext,
) -> NodeResult:
    """Execute a single node. Raises on failure (no swallowing)."""
    inputs = {
        k: state.values[k] for k in node.input_keys
    }
    try:
        result = node.executor(context, inputs)
    except Exception as exc:
        raise NodeExecutionError(node.name, exc) from exc

    validate_node_contract(node, result)
    return result


# ============================================================
# ENGINE
# ============================================================

def run_graph(
    graph: GraphSpec,
    seed: Mapping[str, Any],
    context: ExecutionContext,
) -> ExecutionSummary:
    """Execute graph sequentially. Returns ExecutionSummary.

    1. Validate graph
    2. Compute topological order
    3. Execute nodes in order
    4. Return summary
    """
    seed_keys = frozenset(seed.keys())
    validate_graph(graph, seed_keys)
    order = compute_topological_order(graph)

    node_map = {n.name: n for n in graph.nodes}
    state = ExecutionState(
        values=dict(seed),
        producers={k: "seed" for k in seed},
    )

    log.info("graph.start nodes=%d seed_keys=%s",
             len(graph.nodes), sorted(seed_keys))

    for node_name in order:
        node = node_map[node_name]

        if is_resolved(node, state):
            continue

        # Check if upstream failed → skip
        if not node.input_keys.issubset(state.values.keys()):
            log.info("node.skipped name=%s reason=%s",
                      node_name, SKIP_UNSATISFIABLE_INPUTS)
            state = mark_skipped(
                state, node_name, SKIP_UNSATISFIABLE_INPUTS,
            )
            # Skip downstream nodes too
            downstream = get_downstream_nodes(node_name, graph)
            for dn in downstream:
                if not is_resolved(node_map[dn], state):
                    state = mark_skipped(
                        state, dn, SKIP_UPSTREAM_FAILED,
                    )
            continue

        # Evaluate guard
        if node.guard is not None:
            try:
                guard_result = node.guard(state.values)
            except Exception as exc:
                log.warning("node.guard_error name=%s error=%s",
                            node_name, exc)
                state = mark_failed(state, node_name)
                continue
            if not guard_result:
                log.info("node.skipped name=%s reason=%s",
                          node_name, SKIP_GUARD_FALSE)
                state = mark_skipped(
                    state, node_name, SKIP_GUARD_FALSE,
                )
                continue

        # Execute
        log.info("node.start name=%s", node_name)
        t0 = time.monotonic()
        try:
            result = execute_node(node, state, context)
        except (NodeExecutionError, NodeContractError) as exc:
            elapsed = time.monotonic() - t0
            log.warning("node.failure name=%s elapsed=%.3fs error=%s",
                         node_name, elapsed, exc)
            state = mark_failed(state, node_name)
            # Skip dependents (continue_independent mode)
            downstream = get_downstream_nodes(node_name, graph)
            for dn in downstream:
                if not is_resolved(node_map[dn], state):
                    state = mark_skipped(
                        state, dn, SKIP_UPSTREAM_FAILED,
                    )
            continue

        elapsed = time.monotonic() - t0
        log.info("node.success name=%s elapsed=%.3fs outputs=%s",
                  node_name, elapsed, sorted(result.outputs.keys()))

        # Merge
        state = merge_node_result(state, node_name, result)

    success = (
        len(state.failed_nodes) == 0
        and len(state.skipped_nodes) == 0
    )

    log.info("graph.end completed=%d failed=%d skipped=%d success=%s",
             len(state.completed_nodes), len(state.failed_nodes),
             len(state.skipped_nodes), success)

    return ExecutionSummary(
        final_state=state,
        completed_nodes=tuple(sorted(state.completed_nodes)),
        failed_nodes=tuple(sorted(state.failed_nodes)),
        skipped_nodes=tuple(sorted(state.skipped_nodes)),
        success=success,
    )
