"""Graph validation — runs BEFORE execution.

Rejects invalid graphs: cycles, missing nodes, duplicate names,
impossible dependencies (input_keys never produced by any node or seed).
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.engine.errors import GraphValidationError
from side_projects.graph_runner.engine.types import GraphSpec


def validate_graph(
    graph: GraphSpec, seed_keys: frozenset[str],
) -> None:
    """Validate graph structure. Raises GraphValidationError on failure."""
    check_duplicate_names(graph)
    check_edges_reference_valid_nodes(graph)
    check_acyclic(graph)
    check_satisfiable_inputs(graph, seed_keys)


def check_duplicate_names(graph: GraphSpec) -> None:
    names = [n.name for n in graph.nodes]
    seen: set[str] = set()
    dupes: list[str] = []
    for name in names:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    if dupes:
        raise GraphValidationError(
            f"Duplicate node names: {sorted(dupes)}"
        )


def check_edges_reference_valid_nodes(graph: GraphSpec) -> None:
    valid_names = {n.name for n in graph.nodes}
    for edge in graph.edges:
        if edge.src not in valid_names:
            raise GraphValidationError(
                f"Edge references unknown source node: "
                f"{edge.src!r}"
            )
        if edge.dst not in valid_names:
            raise GraphValidationError(
                f"Edge references unknown destination node: "
                f"{edge.dst!r}"
            )


def check_acyclic(graph: GraphSpec) -> None:
    """Detect cycles via topological sort (Kahn's algorithm)."""
    adj: dict[str, list[str]] = {n.name: [] for n in graph.nodes}
    in_degree: dict[str, int] = {n.name: 0 for n in graph.nodes}

    for edge in graph.edges:
        adj[edge.src].append(edge.dst)
        in_degree[edge.dst] += 1

    queue = [n for n, d in in_degree.items() if d == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(graph.nodes):
        remaining = {
            n for n, d in in_degree.items() if d > 0
        }
        raise GraphValidationError(
            f"Graph contains cycle(s) involving nodes: "
            f"{sorted(remaining)}"
        )


def check_satisfiable_inputs(
    graph: GraphSpec, seed_keys: frozenset[str],
) -> None:
    """Verify every node's input_keys can be satisfied."""
    all_produced: set[str] = set(seed_keys)
    for node in graph.nodes:
        all_produced |= node.output_keys

    for node in graph.nodes:
        unsatisfiable = node.input_keys - all_produced
        if unsatisfiable:
            raise GraphValidationError(
                f"Node {node.name!r} requires keys "
                f"{sorted(unsatisfiable)} that are never produced "
                f"by any node or seed"
            )


def compute_topological_order(graph: GraphSpec) -> list[str]:
    """Return deterministic topological order: rank then lexical."""
    adj: dict[str, list[str]] = {n.name: [] for n in graph.nodes}
    in_degree: dict[str, int] = {n.name: 0 for n in graph.nodes}

    for edge in graph.edges:
        adj[edge.src].append(edge.dst)
        in_degree[edge.dst] += 1

    result: list[str] = []
    queue = sorted(n for n, d in in_degree.items() if d == 0)

    while queue:
        node = queue.pop(0)
        result.append(node)
        neighbors = sorted(adj[node])
        for neighbor in neighbors:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()

    return result
