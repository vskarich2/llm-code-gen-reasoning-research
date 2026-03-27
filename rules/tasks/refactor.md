# TASK TYPE: REFACTOR

Rules specific to restructuring existing code.

## REF-01 — Behavior Preservation

A refactor must not change observable behavior.
Before and after the refactor, the same inputs must produce the same outputs.

Verification: run the existing test suite before and after. All tests must produce identical results.

## REF-02 — No Feature Addition During Refactor

A refactor changes structure, not behavior.
Do not add new capabilities, new parameters, new conditions, or new metrics during a refactor.

If a feature is needed, it is a separate task.

## REF-03 — Incremental Decomposition

Large refactors must be broken into steps where each step:
- Is independently testable
- Does not break the system
- Can be reviewed in isolation

No "big bang" rewrites where everything changes at once.

## REF-04 — Migration Path

If a refactor changes interfaces (function signatures, config format, log schema):
- Document the old interface
- Document the new interface
- Provide a migration path or compatibility shim
- Remove the shim in a separate, later step

## REF-05 — Scope Declaration

Before starting, explicitly list:
- Files that will change
- Files that will NOT change
- Functions that will be renamed, moved, or deleted

Any change outside this declared scope requires re-entering the planning phase.
