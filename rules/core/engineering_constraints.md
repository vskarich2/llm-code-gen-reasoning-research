# ENGINEERING_CONSTRAINTS.md

**Recommended location:** `rules/core/engineering_constraints.md`

**Purpose:**  
This file defines hard engineering constraints for all code changes. It is cross-cutting and applies to refactors, debugging, feature work, parsing, evaluation, logging, retries, and infrastructure. It exists to prevent silent failures, duplicated logic, fragmented code paths, weak contracts, and unverifiable behavior.

**Relationship to existing rule system:**  
- `ENTRYPOINT.md` tells the agent **when** to act.
- `invariants.md` defines system truths that must remain true.
- `code_quality.md` defines quality thresholds.
- `architecture.md` defines ownership and module boundaries.
- `ENGINEERING_CONSTRAINTS.md` defines **how implementation must be performed** at the code level.
- Task-specific files may add stricter rules, but may not weaken this file.

**Precedence:**  
If any task-specific instruction conflicts with this file, follow the stricter rule.

---

# EC-01 — SINGLE CANONICAL CODE PATH

There must be exactly one canonical implementation path for each critical transformation.

## Applies to
- parsing
- response normalization
- prompt construction
- reconstruction
- execution assembly
- evaluation
- classifier invocation
- logging
- metric computation
- retry state transitions

## Requirements
- Do not create parallel implementations of the same core logic.
- Do not introduce “temporary” alternate paths, fallback branches, shadow handlers, or monkey patches.
- If duplicate logic already exists, consolidate into one canonical function before extending behavior.
- All callers must route through the canonical path.

## Forbidden
- multiple parse flows for the same response type
- separate “fast path” and “safe path” unless explicitly approved and audited
- duplicated helper functions with slightly different semantics
- branching on historical legacy behavior unless documented and isolated

## Required proof
For every change affecting critical flow, identify:
1. canonical entrypoint
2. canonical transformation path
3. all callers
4. any old path removed or preserved

---

# EC-02 — EXPLICIT INPUT/OUTPUT CONTRACTS

Every non-trivial function must have a precise contract.

## Required
For each function, the implementation must make clear:
- expected inputs
- allowed input types
- output shape
- possible exceptions
- invariants preserved
- invariants established

## Minimum standard
Use at least one of:
- type hints
- docstring with contract semantics
- explicit runtime assertions
- typed dataclass / typed object boundary

## Forbidden
- undocumented dict-shaped inputs with implicit required keys
- hidden mutation of caller-owned objects
- returning different shapes depending on internal branch without documentation
- “sometimes returns None” unless contract explicitly says so

---

# EC-03 — FAIL LOUDLY AT BOUNDARIES

Unexpected states must fail loudly and specifically.

## Required
- Raise explicit errors on impossible or contract-breaking states.
- Use assertions for invariants that must never fail.
- Include enough context in the error to diagnose the state transition.

## Forbidden
- swallowing exceptions
- broad `except Exception:` without re-raise or structured handling
- silent fallback to default values on malformed state
- returning partial success on structurally invalid input

## Bad patterns
- `dict.get("key", [])` when missing key is a bug
- `return {}`
- `return None`
- `pass`
- log-and-continue on invariant violation

## Good rule
If the system cannot justify the state, it must not proceed.

---

# EC-04 — NO SILENT DEFAULTS FOR CRITICAL DATA

Missing critical data is a bug, not a normal condition.

## Critical data includes
- case identifiers
- condition names
- parsed files
- code payloads
- evaluator verdicts
- run metadata
- event fields
- retry counters
- execution status flags
- classifier outputs

## Required
- Validate presence explicitly.
- Distinguish “missing”, “empty”, “invalid”, and “not applicable”.

## Forbidden
- defaulting missing critical fields to empty string, empty list, empty dict, False, or 0
- auto-coercing malformed values into acceptable shapes
- inferring absent data without explicit provenance

---

# EC-05 — SMALL, SINGLE-PURPOSE FUNCTIONS

Functions must be small enough to audit and specific enough to reason about.

## Hard limits
- Preferred maximum: 30 logical lines
- Soft maximum: 40 logical lines
- Absolute maximum without explicit justification: 60 logical lines

## Requirements
Each function should do one of:
- validate
- transform
- assemble
- route
- persist
- classify
- compute
- render
- orchestrate

Not several at once.

## Forbidden
- parse + validate + mutate + persist in one function
- orchestration mixed with business logic
- helper functions that hide multiple transformations

## Exception
A top-level orchestrator may coordinate multiple steps, but must delegate the steps themselves.

---

# EC-06 — FILE SIZE AND RESPONSIBILITY LIMITS

Files must stay narrow in scope.

## Hard limits
- Preferred maximum: 250 lines
- Soft maximum: 300 lines
- Absolute maximum without explicit justification: 400 lines

## Requirements
- One file should own one coherent responsibility.
- If a file contains multiple unrelated domains, split it.
- If a file mixes orchestration, transformation, persistence, and policy, split it.

## Forbidden
- “utility dumping ground” files
- giant files containing unrelated helpers
- mixing domain logic with debug-only instrumentation

---

# EC-07 — MAXIMUM NESTING AND CONTROL FLOW SIMPLICITY

Code must remain visually auditable.

## Limits
- Preferred maximum nesting depth: 2
- Soft maximum: 3
- Avoid nested conditionals inside loops inside try blocks

## Required
- use guard clauses
- extract branch-specific logic into named helpers
- flatten conditionals where possible

## Forbidden
- deeply nested parse / validation / reconstruction trees
- long if/elif ladders encoding hidden policy
- boolean soup conditions that cannot be inspected quickly

---

# EC-08 — NO HIDDEN SIDE EFFECTS

Mutation must be obvious and localized.

## Required
- Functions that mutate state must make it clear in name or contract.
- Prefer returning new values over mutating shared state.
- If mutating shared state is required, document the ownership boundary.

## Forbidden
- mutating caller-owned dicts/lists without explicit contract
- mutating global/module state during normal evaluation flow
- hidden writes during “read-like” operations
- logging functions that also transform business state

---

# EC-09 — STRUCTURED LOGGING AT EVERY TRANSFORMATION BOUNDARY

Every critical transformation must be inspectable after the fact.

## Required logging boundaries
- input received
- normalization/parsing result
- reconstruction result
- assembly result
- execution start/end
- evaluator request/response
- classifier request/response
- retry decision
- final metric emission

## Requirements
Each boundary log should include:
- operation name
- source of input
- stable identifiers (`run_id`, `case_id`, `condition`, attempt index)
- success/failure
- structural metadata
- reason for branch or rejection

## Forbidden
- “something failed” without structured context
- logs that omit identifiers
- logs that only store summaries when raw payload is what matters
- logging only after completion while omitting intermediate transformations

---

# EC-10 — RAW PAYLOAD PRESERVATION

When a system transforms external input, the raw input must be preserved.

## Applies to
- model prompts
- model responses
- classifier responses
- reconstructed code
- execution artifacts
- parsed JSON payloads
- retry feedback

## Required
- persist raw request/response before normalization when feasible
- preserve exact text for auditability
- log derived metadata separately from raw payload

## Forbidden
- overwriting raw payloads with cleaned versions
- only storing summaries of model output
- mutating canonical artifacts in place after logging them

---

# EC-11 — PARSING MUST BE DETERMINISTIC, TIERED, AND AUDITABLE

Parsing logic must be explicit, ordered, and measurable.

## Required
- Define ordered parse tiers.
- Record which tier succeeded.
- Record why earlier tiers failed.
- Preserve the raw source used for parsing.

## Forbidden
- ad hoc substring slicing without structured attribution
- invisible cleanup logic that changes semantics
- accepting malformed output without marking degraded mode
- parse code duplicated across modules

## Required degraded-mode behavior
If parser accepts a degraded recovery path, mark it explicitly and propagate that status forward.

---

# EC-12 — RECONSTRUCTION MUST BE SEPARATE FROM PARSING

Parsing and reconstruction are different operations and must remain separate.

## Parsing answers
- what did the model emit?

## Reconstruction answers
- how does that map back onto the required program structure?

## Required
- separate functions
- separate logs
- separate status fields
- separate failure reasons

## Forbidden
- parser that secretly fills missing files
- reconstructor that silently repairs parse corruption
- mixed parse/reconstruct code paths that blur root cause

---

# EC-13 — NO “BEST EFFORT” FOR CORE CORRECTNESS PATHS

Core correctness code must not guess.

## Core paths
- execution assembly
- correctness evaluation
- reference fix loading
- retry control
- metric labeling
- event schema construction

## Forbidden
- heuristic guessing without explicit status
- placeholder data in production evaluation
- inferred values pretending to be verified values
- fabricating missing artifacts to keep pipeline moving

## Allowed only if explicit
Heuristics may exist only when:
1. they are declared as heuristics
2. they are logged
3. they are measurable
4. they cannot be confused with ground truth

---

# EC-14 — REUSE EXISTING UTILITIES BEFORE ADDING NEW ONES

New helpers are allowed only after an explicit reuse audit.

## Before creating a new function, the implementer must check
- does a function already exist for this responsibility?
- is there already a canonical module that owns this logic?
- can the existing function be extended safely without adding a new path?

## Required report in plan
For every new helper:
- why existing functions are insufficient
- why extension is safer or unsafe
- where this helper belongs
- why it will not duplicate existing semantics

## Forbidden
- creating near-duplicate helpers with slightly different names
- adding new parser/reconstructor/logger/evaluator helpers without path audit
- creating “v2”, “new”, “safe”, “fixed”, “better” utilities instead of consolidating

---

# EC-15 — NEW FUNCTIONS REQUIRE PLACEMENT JUSTIFICATION

A new function must be placed in the correct owning file.

## Required
Before writing a new function, identify:
- candidate files for ownership
- why the chosen file is correct
- why nearby files are incorrect
- whether the file is already over capacity

## Preferred decision rule
Place code where the dominant responsibility already exists.

## Forbidden
- adding functions wherever the agent is already editing
- placing orchestration helpers in data modules
- placing domain logic in logging modules
- placing one-off helpers in unrelated files for convenience

---

# EC-16 — STATE TRANSITIONS MUST BE EXPLICIT

Retry loops, decision boundaries, and evaluation states must be modeled explicitly.

## Required
- represent states using named enums/constants/typed labels where practical
- log transition reason
- log prior state and next state
- centralize transition rules

## Forbidden
- implicit retry state in loosely coupled booleans
- multiple modules independently deciding retries
- magic integers or string literals scattered through the codebase

---

# EC-17 — DECISION LOGIC MUST BE CENTRALIZED

A policy decision must have one owner.

## Examples
- when to retry
- how to classify failure type
- what counts as parse success
- what counts as reconstruction success
- when to emit a dashboard metric
- when to abort a run

## Required
- one canonical decision function/module per policy
- all callers route through that owner

## Forbidden
- repeating decision rules in CLI, runner, evaluator, and dashboard separately
- local copies of thresholds
- duplicated category mappings

---

# EC-18 — CONSTANTS MUST HAVE A SINGLE SOURCE OF TRUTH

Names, thresholds, categories, and mode labels must not drift.

## Required
Centralize:
- condition names
- failure categories
- event field names
- retry labels
- threshold values
- status enums

## Forbidden
- retyping constants across files
- ad hoc string comparisons for shared labels
- duplicated threshold numbers embedded in logic

---

# EC-19 — EVERY CRITICAL BRANCH MUST BE TESTABLE

A branch that matters operationally must be reachable by a test.

## Required tests for critical logic
- happy path
- invalid input
- impossible state / invariant violation
- degraded parsing / fallback path
- retry trigger
- non-retry terminal path
- logging emission for critical boundaries

## Forbidden
- code that can only be “tested manually”
- critical branches with no deterministic trigger
- safety logic untested because “unlikely”

---

# EC-20 — INTEGRATION TESTS ARE REQUIRED FOR PIPELINE CHANGES

If the change affects wiring, a unit test is not enough.

## Required when changing
- prompt building
- parser
- reconstructor
- execution assembly
- evaluator invocation
- event emission
- retry flow
- configuration loading

## Required proof
At least one integration test must verify the full affected path end-to-end through the modified boundary.

---

# EC-21 — REFERENCE ARTIFACTS MUST BE VERIFIED, NOT TRUSTED

Reference fixes, classifier outputs, metadata fields, and derived metrics must be checked, not assumed.

## Required
- validate reference artifacts before using them in evaluation or reporting
- fail on incompatible metadata
- test that reference fixes actually pass where applicable

## Forbidden
- trusting stale metadata
- assuming labels are correct because they exist
- allowing bad reference artifacts to silently poison evaluation

---

# EC-22 — METRICS MUST TRACK PROVENANCE

Every derived metric must be traceable to trusted or untrusted sources.

## Required
For each metric, declare:
- source fields
- computation owner
- trust level
- assumptions
- whether it depends on heuristic or LLM judgment

## Forbidden
- mixing trusted behavioral metrics with untrusted classifier metrics without labeling
- presenting derived values as hard truth when inputs are weak
- unlabeled composite metrics

---

# EC-23 — DO NOT HIDE HEURISTICS INSIDE “FACT-LIKE” FIELDS

Heuristic judgments must be visibly heuristic.

## Required
Use explicit labels such as:
- `heuristic_*`
- `estimated_*`
- `derived_*`
- `classifier_*`
- `degraded_*`

## Forbidden
- storing guessed values in fields named as facts
- mixing inferred and observed values in the same field
- writing heuristic status into canonical correctness fields

---

# EC-24 — MODIFICATIONS MUST BE MINIMAL, REVERSIBLE, AND LOCAL

Change only what is necessary.

## Required
- smallest coherent fix
- preserve external behavior unless intentionally changed
- keep change set local to owning module where possible
- remove obsolete code introduced by consolidation

## Forbidden
- broad opportunistic rewrites during bug fix
- feature work hidden inside refactors
- leaving dead compatibility shims after migration
- “just in case” scaffolding

---

# EC-25 — DEAD CODE, LEGACY PATHS, AND UNUSED HELPERS MUST BE REMOVED

Unused code is not harmless. It creates false affordances and duplicate paths.

## Required
When a path is superseded:
- remove the old path
- update callers
- delete obsolete helpers
- delete stale comments and stale flags
- update tests accordingly

## Forbidden
- leaving legacy code “for safety”
- commented-out old implementations
- preserving unused wrappers without ownership

---

# EC-26 — COMMENTS MUST EXPLAIN WHY, NOT RESTATE WHAT

Comments are for invariants, rationale, edge cases, and traps.

## Good comments
- why this assertion exists
- why a degraded parse tier is allowed
- why order matters
- why a state is impossible
- why a branch is intentionally strict

## Bad comments
- restating obvious code
- stale TODOs without ownership
- decorative comments without operational value

---

# EC-27 — DOCSTRINGS REQUIRED FOR PUBLIC OR PIPELINE-CRITICAL FUNCTIONS

A public or critical function must have a short operational docstring.

## Must include
- purpose
- key inputs
- key outputs
- raised errors or invariant failures
- any important side effects

---

# EC-28 — CONFIGURATION MUST BE VALIDATED ON LOAD

Configuration is executable policy and must be treated as such.

## Required
- validate schema at load time
- validate allowed values
- fail early on unknown or stale values
- map config values to centralized constants

## Forbidden
- permissive acceptance of unknown config keys
- stringly typed config flowing deep into the system unchecked
- late failure after cost has already been incurred

---

# EC-29 — EVENT SCHEMAS MUST BE STABLE, VERSIONED, AND COMPLETE

Event logs are part of the product, not incidental debug output.

## Required
- stable field names
- explicit schema version when schema evolves
- complete identifiers on every event
- no ambiguous overloaded fields
- raw and derived data separated

## Forbidden
- changing event meanings silently
- partial event writes without status
- omitting fields needed for replay or audit

---

# EC-30 — POST-CHANGE COMPLIANCE REPORT IS MANDATORY

After every non-trivial change, report compliance against this file.

## Minimum report sections
1. Canonical code path affected
2. New/removed functions
3. New/removed files
4. Contracts added/changed
5. Invariants touched
6. Logging boundaries touched
7. Tests added/updated
8. Dead code removed
9. Remaining risks
10. Explicit PASS/FAIL for any waived constraint

---

# REQUIRED IMPLEMENTATION CHECKLIST

Before modifying code, the implementer must answer:

1. What is the canonical code path for this behavior?
2. Which module owns this responsibility?
3. Am I extending the owner or creating duplication?
4. What are the exact input/output contracts?
5. What invariant could silently break here?
6. Where will raw payloads be preserved?
7. What logs will prove the transformation happened correctly?
8. Which branch or failure mode will the new tests exercise?
9. What old code path or helper can now be deleted?
10. What field, threshold, or label must remain single-source-of-truth?

If any answer is vague, implementation is not ready.

---