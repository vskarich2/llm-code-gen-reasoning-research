"""Type definitions for deep_dependency_chain_cases case specs per v7 spec."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class CanonicalRepresentation:
    field_names: list[str]
    schema_description: str
    storage_location: str
    access_paths: list[str]


@dataclass
class NodeDeclarations:
    source_of_truth_node: str
    corruption_introduced_at_node: str
    first_observable_symptom_node: str
    required_fix_node: str


@dataclass
class ChainNode:
    name: str
    module: str
    function: str
    transform_description: str


@dataclass
class TrapSpec:
    trap_id: str               # "trap_1", "trap_2", etc., or "near_root_incorrect"
    trap_type: str             # "endpoint_compensation", "intermediate_recomputation",
                               # "validation_masking", "downstream_override",
                               # "partial_upstream_fix", "near_root_incorrect"
    depth: str                 # "D", "C", "B", "A-wrong"
    description: str
    patch_description: str     # what the patch does
    why_attractive: str
    why_fails: str
    primary_invariant: str     # one of the 5 invariant names
    primary_test_instance: str | None  # for generalization: which test input


@dataclass
class InvariantSpec:
    name: str                  # "trap_catching", "generalization", "causal_location",
                               # "cross_path", "chain_integrity"
    falsification_condition: str
    test_inputs: list[dict]    # concrete test inputs for this invariant


@dataclass
class CaseSpec:
    case_id: str
    difficulty: str            # "B" or "C"
    domain: str
    scenario: str
    nodes: NodeDeclarations
    canonical: CanonicalRepresentation
    chain: list[ChainNode]
    bypass_consumer: str       # function name
    bypass_description: str
    bug_description: str
    root_fix_description: str
    traps: list[TrapSpec]
    invariants: list[InvariantSpec]

    # Executable components (callables)
    build_buggy_state: Callable | None = None
    apply_root_fix: Callable | None = None
    apply_trap: dict[str, Callable] = field(default_factory=dict)
    run_primary_test: Callable | None = None
    run_invariant: dict[str, Callable] = field(default_factory=dict)
    classify_patch_depth: Callable | None = None


@dataclass
class InvariantResult:
    name: str
    passed: bool
    test_instance: str | None = None
    detail: str = ""


@dataclass
class PatchResult:
    patch_id: str
    primary_test_passed: bool
    invariant_results: list[InvariantResult] = field(default_factory=list)
    primary_failure: str | None = None
    depth: str = "unrelated"
    detail: str = ""
