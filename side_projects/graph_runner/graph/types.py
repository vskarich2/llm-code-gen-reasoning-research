"""Core type definitions for the execution engine.

All types are frozen dataclasses — immutable after construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


# ============================================================
# SKIP REASONS — closed enum
# ============================================================

SKIP_UNSATISFIABLE_INPUTS = "SKIP_UNSATISFIABLE_INPUTS"
SKIP_GUARD_FALSE = "SKIP_GUARD_FALSE"
SKIP_FAIL_FAST = "SKIP_FAIL_FAST"
SKIP_UPSTREAM_FAILED = "SKIP_UPSTREAM_FAILED"


# ============================================================
# INVARIANT RECORD
# ============================================================

@dataclass(frozen=True)
class InvariantRecord:
    stage: str
    inv_type: str
    severity: str
    message: str


# ============================================================
# NODE RESULT
# ============================================================

@dataclass(frozen=True)
class NodeResult:
    outputs: Mapping[str, Any]
    warnings: tuple[str, ...] = ()


# ============================================================
# EXECUTION CONTEXT
# ============================================================

@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    case_id: str
    model: str
    condition: str
    config: Any
    logger: Any


# ============================================================
# EDGE SPEC
# ============================================================

@dataclass(frozen=True)
class EdgeSpec:
    src: str
    dst: str


# ============================================================
# NODE SPEC
# ============================================================

@dataclass(frozen=True)
class NodeSpec:
    name: str
    input_keys: frozenset[str]
    output_keys: frozenset[str]
    executor: Callable[[ExecutionContext, Mapping[str, Any]], NodeResult]
    guard: Callable[[Mapping[str, Any]], bool] | None = None
    timeout_s: float | None = None
    side_effecting: bool = False


# ============================================================
# GRAPH SPEC
# ============================================================

@dataclass(frozen=True)
class GraphSpec:
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]


# ============================================================
# EXECUTION STATE
# ============================================================

@dataclass(frozen=True)
class ExecutionState:
    values: Mapping[str, Any] = field(default_factory=dict)
    producers: Mapping[str, str] = field(default_factory=dict)
    completed_nodes: frozenset[str] = frozenset()
    failed_nodes: frozenset[str] = frozenset()
    skipped_nodes: frozenset[str] = frozenset()
    skip_reasons: Mapping[str, str] = field(default_factory=dict)
    invariant_violations: tuple[InvariantRecord, ...] = ()


# ============================================================
# EXECUTION SUMMARY
# ============================================================

@dataclass(frozen=True)
class ExecutionSummary:
    final_state: ExecutionState
    completed_nodes: tuple[str, ...]
    failed_nodes: tuple[str, ...]
    skipped_nodes: tuple[str, ...]
    success: bool
