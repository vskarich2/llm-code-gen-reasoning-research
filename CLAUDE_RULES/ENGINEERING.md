# ============================================================
# ENGINEERING.md — ELITE IMPLEMENTATION CONSTRAINTS
# ============================================================

Purpose:
This file defines how code must be written and modified at the local level.

All system correctness is defined in:
→ INVARIANTS.md

This file MUST NOT redefine system invariants.
It enforces implementation discipline only.

---

# EC-01 — EXPLICIT INPUT/OUTPUT CONTRACTS

Every non-trivial function must define a clear contract.

Required:
- explicit input types
- explicit output shape
- defined failure modes
- validation at boundaries

Allowed mechanisms:
- type hints
- assertions
- validation functions
- structured objects (dataclasses / typed dicts)

Forbidden:
- implicit dict contracts
- undocumented return shapes
- hidden mutation of inputs

---

# EC-02 — FAIL FAST AT BOUNDARIES

Invalid or unexpected states must fail immediately.

Required:
- explicit errors for invalid inputs
- assertions for impossible states

Forbidden:
- partial returns on invalid state
- continuing execution after contract violation

---

# EC-03 — SMALL, SINGLE-PURPOSE FUNCTIONS

Functions must be easy to reason about.

Limits:
- preferred ≤ 30 logical lines
- hard limit ≤ 60 (requires justification)

Each function must do ONE thing:
- validate
- transform
- assemble
- route
- compute

Forbidden:
- mixing multiple responsibilities
- hidden multi-step transformations

---

# EC-04 — FILE SCOPE DISCIPLINE

Files must have a single coherent responsibility.

Limits:
- preferred ≤ 250 lines
- hard limit ≤ 400

Required:
- group related logic only
- split files when responsibilities diverge

Forbidden:
- “utility dumping ground” files
- mixing orchestration with low-level logic

---

# EC-05 — CONTROL FLOW SIMPLICITY

Code must be visually auditable.

Limits:
- preferred nesting depth ≤ 2
- soft limit ≤ 3

Required:
- guard clauses
- extracted helper functions

Forbidden:
- deep nesting
- long if/elif ladders encoding policy

---

# EC-06 — NO HIDDEN SIDE EFFECTS

Mutation must be explicit and local.

Required:
- clearly signal mutating functions
- prefer returning new values

Forbidden:
- mutating caller-owned data silently
- global state mutation
- side effects inside “read-like” functions

---

# EC-07 — REUSE BEFORE ADDING NEW CODE

Do not introduce new logic without checking existing ownership.

Before adding a function:
- identify existing owner module
- verify reuse is not possible
- justify why extension is insufficient

Forbidden:
- duplicate helpers
- “v2”, “new”, or shadow implementations

---

# EC-08 — CORRECT PLACEMENT OF NEW CODE

All new code must live in the correct module.

Required:
- identify owning module before writing code
- place logic where responsibility already exists

Forbidden:
- placing code where you are already editing for convenience
- mixing domains across modules

---

# EC-09 — TESTABILITY OF CRITICAL LOGIC

All important branches must be testable.

Required coverage:
- valid path
- invalid input
- failure path

Forbidden:
- untestable branches
- logic only verifiable manually

---

# EC-10 — MINIMAL, LOCAL, REVERSIBLE CHANGES

All modifications must be tightly scoped.

Required:
- smallest possible change
- local to owning module
- remove obsolete code after consolidation

Forbidden:
- opportunistic refactors
- scope creep
- leaving dead or duplicate code behind

---

# EC-11 — DESCRIPTIVE NAMING

Names must encode intent clearly.

Required:
- verb + object (+ context if needed)

Examples:
- `build_evaluation_prompt`
- `parse_model_response_json`
- `compute_pass_rate`

Forbidden:
- vague names (`process`, `handle`, `do_work`, `helper`)
- names that hide multiple responsibilities

Rule:
If a name requires explanation, the function is either misnamed or doing too much.

---

# EC-12 — IMPORT HYGIENE

Imports must be explicit and clean.

Required:
- no unused imports
- explicit imports only

Forbidden:
- wildcard imports (`from x import *`)
- circular dependencies between modules

---

# EC-13 — DOCSTRINGS FOR PUBLIC OR CRITICAL FUNCTIONS

Functions used across modules or critical to pipeline behavior must have docstrings.

Must include:
- purpose
- key inputs
- key outputs
- failure conditions
- side effects (if any)

Forbidden:
- undocumented public functions
- docstrings that restate obvious code without explaining behavior

---

# EC-14 — NO MAGIC NUMBERS

Numeric literals must have semantic meaning.

Required:
- use named constants or config values

Examples:
- `PASS_THRESHOLD`
- `config.max_tokens`

Forbidden:
- embedded thresholds (`0.95`, `600`, `800`)
- repeated numeric literals across files

Allowed:
- trivial values (0, 1, -1)

---

## FUNCTIONAL DISCIPLINE

### Functional Core, Imperative Shell

- Prefer pure functions for:
  - parsing
  - transformation
  - validation
  - computation

- Side effects are allowed ONLY at boundaries:
  - API calls
  - logging
  - file I/O
  - orchestration

---

### No Hidden State

- No global mutable state
- No implicit shared mutation
- No hidden caches

All state must flow through:
→ function arguments
→ return values

---

### Explicit Data Flow

- No implicit dependencies
- No reading hidden module state
- Inputs and outputs must fully define behavior

---

### Controlled Mutation

- Local mutation is allowed
- Mutation of inputs must be explicit and documented
- No cross-function mutation

---

### Composition

- Prefer small, single-purpose functions
- Prefer chaining transformations over monolithic logic

---

### Error Handling

- No silent fallback
- No hidden control flow changes
- Fail explicitly on invalid state

---

### Practical Rule

Do NOT force functional style when it harms clarity.

→ clarity > purity

# SUMMARY

- invariants define truth
- this file defines implementation discipline
- keep code small, explicit, and auditable
- avoid duplication and hidden behavior
- enforce correctness at boundaries
- minimize and localize all changes

Primary rule:
→ Write code that cannot silently violate INVARIANTS.md