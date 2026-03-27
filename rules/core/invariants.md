# HARD INVARIANTS

These constraints are non-negotiable system properties.  
They must hold across all executions, configurations, and code changes.

Violation of any invariant must:
- be surfaced in post-action audit
- include root cause and location
- block approval unless explicitly waived

Each invariant includes:
- definition (what must always hold)
- scope (where it applies)
- enforcement guidance (how to verify)
- audit heuristics (non-exhaustive checks)

---

# INV-01 — Single Canonical Execution Entry

All evaluation attempts must enter through exactly one canonical execution entrypoint.

## Definition
There is one and only one function responsible for orchestrating:
- prompt construction
- model invocation
- parsing
- reconstruction
- execution evaluation
- reasoning evaluation
- logging

## Requirements
- No alternate top-level execution paths
- Retry loops must re-enter through this entrypoint
- All callers must route through this function

## Forbidden
- parallel pipelines (“legacy”, “fast path”, “safe path”)
- direct calls into downstream modules (llm, parse, evaluator) from outside execution layer

## Enforcement
- enumerate all functions capable of initiating evaluation
- verify they route into the canonical execution entry

## Audit Heuristics
- search for multiple “run_*”, “execute_*”, “evaluate_*” entrypoints
- search for direct llm/parse/evaluator calls outside execution layer

---

# INV-02 — Single Canonical Implementation Per Responsibility

Each critical responsibility must have exactly one implementation.

## Applies to
- parsing
- reconstruction
- execution evaluation
- reasoning evaluation
- retry control
- event emission
- metric computation

## Requirements
- one canonical function/module per responsibility
- all callers route through that implementation

## Forbidden
- duplicate implementations across modules
- “v2”, “safe”, “alt”, or shadow variants
- fallback paths that replicate core logic

## Enforcement
- identify canonical owner for each responsibility
- remove or consolidate duplicates

## Audit Heuristics
- search for similar function names or logic across modules
- diff similar code blocks across files

---

# INV-03 — No Silent Failure

The system must never continue execution after an invalid or unknown state without explicit handling.

## Definition
All failures must be:
- explicitly raised (for invariant violations), or
- explicitly handled and logged (for recoverable errors)

## Requirements
- invariant violations → raise immediately
- recoverable errors → structured log + explicit branch

## Forbidden
- `except: pass`
- swallowing exceptions
- implicit fallback behavior
- returning partial or default results for invalid state

## Enforcement
- every exception path must either re-raise or log with context

## Audit Heuristics
- grep for `except` blocks
- verify presence of raise or structured logging

---

# INV-04 — Explicit Contract Boundaries

All module and function boundaries must enforce input/output contracts.

## Requirements
- validate required inputs at entry points
- enforce output shape and invariants
- distinguish:
  - missing
  - invalid
  - empty
  - not applicable

## Forbidden
- implicit assumptions about input structure
- unchecked dict access
- variable output formats without contract

## Enforcement
- presence of validation/assertions at boundaries

## Audit Heuristics
- search for `.get()` on required fields
- identify functions without input validation

---

# INV-05 — No Silent Defaults for Critical Values

Missing required values must cause explicit failure.

## Applies to
- config parameters
- parsed outputs
- evaluation inputs
- identifiers and metadata

## Requirements
- required values must be explicitly validated
- absence must raise an error

## Forbidden
- `config.get("key", default)` for required values
- implicit substitution of missing data

## Enforcement
- verify required fields are validated before use

## Audit Heuristics
- grep for `get(` with defaults
- trace usage of required config fields

---

# INV-06 — Controlled Determinism

Internal system behavior must be deterministic given the same inputs.

## Scope
Applies to:
- parsing
- reconstruction
- execution evaluation
- metric computation
- ordering of operations

Does NOT require strict determinism from external LLM APIs.

## Requirements
- no unseeded randomness
- no time-based branching logic
- deterministic ordering for unordered collections
- full logging of external call parameters

## Forbidden
- reliance on iteration order of dict/set
- time-dependent evaluation logic
- hidden randomness

## Enforcement
- seed all randomness
- normalize ordering where relevant

## Audit Heuristics
- search for `random.` usage
- inspect iteration over unordered structures

---

# INV-07 — Separation of Generation and Evaluation

Generation and evaluation must remain logically and structurally separate.

## Definition
- generation: producing candidate outputs
- evaluation: measuring correctness (behavioral or reasoning)

## Requirements
- evaluation must not mutate original generation artifacts
- generation must not implicitly depend on evaluation state

## Allowed
- explicit, logged feedback loops (e.g., retry, repair, contract-gated)
- feedback must be:
  - condition-scoped
  - explicitly passed as input
  - logged

## Forbidden
- hidden feedback channels
- evaluator mutating generation output
- implicit dependency between evaluation and generation

## Enforcement
- verify data passed between modules is explicit and immutable

## Audit Heuristics
- check for mutation of generation artifacts
- check for implicit global/shared state usage

---

# INV-08 — Complete Terminal Logging

Every evaluation attempt must produce exactly one terminal record.

## Terminal states include
- success
- failure
- timeout
- aborted
- parse_failure
- execution_failure

## Requirements
- every attempt ends in one and only one terminal state
- terminal state must be logged with full context
- crashes and timeouts must still produce a record

## Forbidden
- missing terminal records
- multiple conflicting terminal states
- silent termination

## Enforcement
- trace all execution paths to terminal logging

## Audit Heuristics
- verify all exit paths emit a final log event

---

# INV-09 — No Unbounded External Calls

All external calls must have bounded execution time.

## Applies to
- LLM API calls
- HTTP requests
- Redis or database calls
- subprocess execution

## Requirements
- explicit timeout defined
- failure mode logged
- no indefinite blocking

## Forbidden
- calls without timeout
- reliance on default infinite wait behavior

## Enforcement
- inspect all external call sites

## Audit Heuristics
- search for API/client instantiation
- verify timeout parameters are present

---

# INV-10 — Explicit Resource Lifecycle

All external resources must have defined lifecycle.

## Requirements
- clear owner
- defined creation point
- explicit cleanup or reuse strategy

## Forbidden
- per-call client instantiation without justification
- unclosed resources
- implicit lifecycle

## Enforcement
- verify use of context managers or managed clients

## Audit Heuristics
- search for `open(`, API client creation, subprocess usage

---

# INV-11 — Single Source of Truth for State

Each piece of state must have exactly one owner.

## Applies to
- config
- case data
- execution results
- logs and events
- derived metrics

## Requirements
- compute once, propagate forward
- no independent recomputation

## Forbidden
- shadow copies
- inconsistent representations
- recomputing evaluation outputs in multiple modules

## Enforcement
- trace origin of key state variables

---

# INV-12 — Raw Artifact Preservation

Raw inputs and outputs must be preserved.

## Applies to
- prompts
- model responses
- classifier outputs
- reconstructed code
- execution outputs

## Requirements
- store raw artifacts before transformation
- log transformations separately

## Forbidden
- overwriting raw data
- storing only processed summaries
- losing provenance

## Enforcement
- verify logging includes raw payloads

---

# INV-13 — Metric Provenance Integrity

All metrics must declare their source and trust level.

## Requirements
- distinguish:
  - behavioral (trusted)
  - classifier-derived (untrusted/heuristic)
  - derived metrics

- computation must be centralized

## Forbidden
- mixing trusted and untrusted metrics without labeling
- presenting derived metrics as ground truth

## Enforcement
- audit metric definitions and computation paths

---

# INV-14 — No Duplicate Decision Logic

All policy decisions must have a single owner.

## Applies to
- retry conditions
- parse success criteria
- classification thresholds
- evaluation categories

## Requirements
- one canonical implementation
- shared across all modules

## Forbidden
- duplicated decision rules
- inconsistent thresholds

## Enforcement
- identify decision points and verify centralization

---

# INV-15 — Integration Integrity

All pipeline modifications must preserve end-to-end correctness.

## Requirements
- integration tests must cover:
  - prompt → execution → evaluation → logging
- no partial validation

## Forbidden
- changes validated only at unit level
- untested pipeline wiring changes

## Enforcement
- require integration test coverage for pipeline changes

---

# SUMMARY

The system must always be:

- single-entry, single-path
- non-duplicated in core responsibilities
- explicit in contracts
- fail-loud on invalid states
- deterministic internally
- strictly separated in concerns
- fully logged with terminal completeness
- bounded in all external interactions
- centrally owned in all decisions and state
- fully auditable with preserved provenance

Any violation of these properties is a system-level failure.