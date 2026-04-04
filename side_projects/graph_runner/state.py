# graph_runner/state.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import uuid

"""
This file defines the core runtime case_data model for the graph execution system.
It is responsible for representing and storing all case_data ("artifacts") produced
during execution, and for providing a consistent interface through which stages
(StageSpec objects) read and write that case_data.

--------------------------------------------------------------------------------
HIGH-LEVEL ROLE

This module implements the "state layer" of the system.

Conceptually:
    - StageSpec (from elsewhere) defines *what should happen*
    - Executors define *how computation happens*
    - ExecutionState (this file) defines *where case_data lives*

Together, they form a dataflow system:
    stages read from state → compute → write back to state → next stages run

--------------------------------------------------------------------------------
CORE CONCEPT: ARTIFACT

An Artifact represents a single piece of case_data produced during execution.

Instead of storing raw values directly (e.g., strings, dicts), everything is
wrapped in an Artifact object:

    Artifact(
        id=UUID,
        type="string label",
        value=actual case_data,
        metadata={...}
    )

Key properties:
    - id: globally unique identifier (used for tracking and referencing)
    - type: semantic label (e.g., "prompt", "response", "parsed")
    - value: the actual payload (can be any Python object)
    - metadata: optional auxiliary case_data (timestamps, provenance, etc.)

Artifacts are:
    - immutable (frozen dataclass)
    - uniquely identifiable
    - suitable for logging, replay, and debugging

This abstraction allows the system to:
    - track case_data lineage
    - attach metadata to intermediate results
    - support reproducibility and auditability

--------------------------------------------------------------------------------
ARTIFACT REFERENCES

ArtifactRef is a lightweight pointer to an Artifact by ID.

    ArtifactRef(id="...")

This exists to:
    - avoid copying large values
    - allow passing references between components
    - decouple identity from storage

However, in the current design:
    - ArtifactRef is a thin wrapper and does not enforce safety
    - it relies on ExecutionState to resolve IDs

--------------------------------------------------------------------------------
CORE CONCEPT: EXECUTION STATE

ExecutionState is the central storage for all artifacts produced during a run.

It maintains two mappings:

    artifacts: Dict[artifact_id → Artifact]
        - stores all artifacts ever created in this execution

    index: Dict[logical_name → artifact_id]
        - maps human-readable names (e.g., "prompt") to the *latest* artifact

Together, this creates a two-layer lookup system:

    name → artifact_id → Artifact

--------------------------------------------------------------------------------
HOW STAGES INTERACT WITH STATE

Stages (defined elsewhere via StageSpec) interact with ExecutionState using
string keys.

Example StageSpec:
    input_keys = ["prompt"]
    output_keys = ["raw_response"]

Execution flow:

    1. Read inputs:
        artifact = state.get("prompt")
        value = artifact.value

    2. Compute:
        result = executor(value)

    3. Write outputs:
        state.add_artifact("raw_response", new_artifact)

This means:
    - ExecutionState is the single source of truth for all case_data
    - StageSpec only names case_data; it does not store it

--------------------------------------------------------------------------------
IMPORTANT SEMANTICS

1. INCREMENTAL STATE BUILDUP

State is NOT fully populated at the start.

It grows over time as stages execute:

    Step 0: {"case": ...}
    Step 1: {"case": ..., "prompt": ...}
    Step 2: {"case": ..., "prompt": ..., "raw_response": ...}

At any moment:
    - state contains all outputs from previously executed stages
    - missing keys indicate stages that have not run yet

--------------------------------------------------------------------------------
2. LATEST-VALUE SEMANTICS (NO VERSIONING)

The index enforces:

    one logical name → one current artifact

When a new artifact is added:

    index[name] = new_artifact.id

This overwrites the previous mapping.

Implications:
    - only the latest value for each key is accessible via name
    - previous versions are still stored in `artifacts` but are not indexed
    - history is not easily accessible without additional mechanisms

This is a limitation for:
    - retries
    - trajectory analysis
    - debugging multi-step evolution

--------------------------------------------------------------------------------
3. NAME-BASED DATAFLOW

All communication between stages happens via string keys:

    "prompt", "raw_response", "parsed_response", etc.

There is:
    - no type enforcement
    - no schema validation
    - no compile-time checking

This makes the system:
    - flexible and easy to extend
    - but fragile to typos and inconsistencies

--------------------------------------------------------------------------------
4. FAIL-FAST LOOKUPS

    get(name):
        - returns the Artifact for the given name
        - raises KeyError if missing

    has(name):
        - checks whether a key exists in state

This supports:
    - guard-based execution (stages only run if inputs exist)
    - explicit failure when required case_data is missing

--------------------------------------------------------------------------------
RELATIONSHIP TO STAGE SPEC

StageSpec (defined elsewhere) describes:
    - which keys to read (input_keys)
    - which keys to write (output_keys)

ExecutionState provides:
    - storage for those keys
    - lookup and mutation APIs

The connection is purely via shared string names.

In other words:
    StageSpec defines the dataflow graph implicitly,
    ExecutionState makes that graph concrete at runtime.

--------------------------------------------------------------------------------
DESIGN STRENGTHS

- Clear separation between computation (executors) and case_data (state)
- Artifact abstraction supports logging, replay, and provenance
- Incremental state enables flexible execution and partial runs
- Decoupled stages communicate only via state

--------------------------------------------------------------------------------
CURRENT LIMITATIONS / RISKS

- No enforcement that executors produce declared output_keys
- No validation that input_keys fully capture dependencies
- Hidden dependencies may exist outside input_keys (e.g., in guards)
- No type safety for artifact values or types
- Overwrite semantics lose visibility into intermediate history
- String-based keys are error-prone and not centrally defined

--------------------------------------------------------------------------------
MENTAL MODEL

Think of ExecutionState as:

    "A versioned (but currently only latest-visible) key-value store of artifacts,
     representing the accumulated outputs of all executed stages in a pipeline."

And the system as a whole:

    state + StageSpecs + executors = a dataflow execution engine

--------------------------------------------------------------------------------
"""

# =========================
# Artifact
# =========================

@dataclass(frozen=True)
class Artifact:
    id: str
    type: str
    value: Any
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(type: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> "Artifact":
        return Artifact(
            id=str(uuid.uuid4()),
            type=type,
            value=value,
            metadata=metadata or {},
        )


# =========================
# ArtifactRef
# =========================

@dataclass(frozen=True)
class ArtifactRef:
    id: str


# =========================
# ExecutionState
# =========================

@dataclass
class ExecutionState:
    artifacts: Dict[str, Artifact] = field(default_factory=dict)
    index: Dict[str, str] = field(default_factory=dict)  # logical_name → artifact_id

    def add_artifact(self, name: str, artifact: Artifact) -> ArtifactRef:
        self.artifacts[artifact.id] = artifact
        self.index[name] = artifact.id
        return ArtifactRef(id=artifact.id)

    def get(self, name: str) -> Artifact:
        artifact_id = self.index.get(name)
        if artifact_id is None:
            raise KeyError(f"Artifact '{name}' not found in state")
        return self.artifacts[artifact_id]

    def get_ref(self, name: str) -> ArtifactRef:
        artifact_id = self.index.get(name)
        if artifact_id is None:
            raise KeyError(f"Artifact '{name}' not found in state")
        return ArtifactRef(id=artifact_id)

    def has(self, name: str) -> bool:
        return name in self.index