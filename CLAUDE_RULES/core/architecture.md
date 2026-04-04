# ARCHITECTURE CONSTRAINTS

Rules governing module boundaries, data flow, ownership, and system structure.  
These constraints ensure a single, auditable, and non-duplicated execution pipeline.

---

# ARCH-01 — Module Responsibility (Single Ownership)

Each module has exactly one responsibility and is the canonical owner of that responsibility.

| Module | Responsibility | May call | Must not call |
|--------|---------------|----------|---------------|
| `runner.py` | Orchestration: load config, load cases, iterate (case × condition), aggregate results | execution, experiment_config | llm, parse, evaluator, exec_eval |
| `execution.py` | Canonical evaluation pipeline entrypoint | llm, parse, reconstructor, exec_eval, evaluator, logging | runner |
| `llm.py` | LLM API calls | SDK, experiment_config | execution, evaluator, parse |
| `parse.py` | Response parsing (raw → structured) | (pure computation) | llm, execution, evaluator |
| `reconstructor.py` | Structured → program reconstruction | (pure computation) | llm, execution |
| `exec_eval.py` | Behavioral execution + test validation | (in-process or subprocess) | llm, evaluator |
| `evaluator.py` | Reasoning classification + alignment | llm, exec_eval | execution, runner |
| `prompts.py` | Prompt construction | (pure computation) | llm, execution |
| `experiment_config.py` | Config loading + validation | stdlib only | all runtime modules |
| `call_logger.py` | Raw LLM call logging | stdlib only | execution logic |
| `logging / metrics layer` | Structured logging + event emission | stdlib only | execution logic |

## Requirements
- Each responsibility must have exactly one canonical implementation.
- All callers must route through the owning module.
- No duplicate implementations across modules.

## Forbidden
- multiple parsing implementations
- multiple evaluation pipelines
- shadow helpers implementing the same logic
- adding logic to a module that does not own that responsibility

---

# ARCH-02 — Canonical Execution Pipeline

All evaluations must follow a single canonical flow:
config
→ runner
→ execution (entrypoint)
→ build_prompt
→ llm_call
→ parse
→ reconstruct
→ exec_eval (behavioral correctness)
→ evaluator (reasoning correctness)
→ logging/metrics


## Requirements
- All evaluation must enter through `execution.py`
- All steps must occur in this order
- Each step must be explicitly represented in code

## Controlled Loops
Retry is allowed but must re-enter ONLY through the execution entrypoint.

## Forbidden
- skipping steps (e.g., parse → exec without reconstruction)
- calling downstream modules directly (bypassing execution)
- embedding pipeline logic across multiple modules

---

# ARCH-03 — No Pipeline Bypass

No module may bypass the canonical pipeline.

## Forbidden examples
- `runner.py` calling `llm.py` directly
- `evaluator.py` calling `parse.py`
- logging reconstructing state independently
- metrics recomputing evaluation results

## Rule
All flow must go through `execution.py` unless explicitly defined as a controlled exception.

---

# ARCH-04 — Single Source of Truth for State

Each piece of state has exactly one owner.

| State | Owner | Others may |
|-------|-------|-----------|
| Experiment config | `experiment_config.py` | Read only |
| Case data | `runner.py` | Read only |
| Execution result | `execution.py` | Read only |
| Run log | logging layer | Append only |
| Event stream | logging layer | Append only |
| LLM call log | `call_logger.py` | Append only |

## Requirements
- Derived values must be computed once and propagated.
- No recomputation of core state across modules.

## Forbidden
- shadow copies of state
- recomputing evaluation results independently
- inconsistent representations of the same data

---

# ARCH-05 — Separation of Core Concerns

The following responsibilities must remain strictly separated:

- parsing (what the model produced)
- reconstruction (mapping to program structure)
- execution (behavioral correctness)
- reasoning evaluation (semantic correctness)

## Forbidden
- parser repairing code
- reconstructor fixing parse errors silently
- evaluator executing code
- execution layer performing reasoning classification

---

# ARCH-06 — No Global Mutable State in Hot Path

Module-level mutable state is forbidden in the evaluation pipeline.

## Allowed
- constants
- immutable config
- explicitly managed singletons

## Forbidden
- module-level lists/dicts accumulating results
- hidden state across evaluations
- implicit caching without reset

## Check
Search for:
- `= {}`
- `= []`
- `= set()`

---

# ARCH-07 — Explicit Resource Lifecycle

All external resources must have defined lifecycle.

## Required
- defined creation point
- clear owner
- explicit cleanup

## Applies to
- API clients
- file handles
- subprocesses
- network connections

## Rules
- prefer context managers
- reuse clients when safe
- do not instantiate clients per call without justification

## Forbidden
- leaking connections
- unclosed resources
- implicit resource creation

---

# ARCH-08 — No Cross-Module Side Effects

Modules must not mutate each other’s state implicitly.

## Allowed
- function arguments and return values
- explicit shared objects (e.g., config)

## Forbidden
- importing and mutating module-level variables
- hidden mutation through shared references

---

# ARCH-09 — File Placement Discipline

Before adding a function:

1. Identify the owning module (ARCH-01)
2. Check for existing implementation
3. Extend existing logic if possible
4. Only create new function if no canonical implementation exists

Before creating a file:

1. Prove no existing module can own the responsibility
2. Define single responsibility
3. update module map

## Forbidden
- adding functions “where convenient”
- creating parallel helper utilities
- scattering logic across unrelated modules

---

# ARCH-10 — Centralized Decision Logic

Policy decisions must have a single owner.

## Examples
- retry conditions
- parse success criteria
- evaluation thresholds
- classification categories

## Requirements
- one canonical implementation per decision
- all callers use the same function

## Forbidden
- duplicated decision logic across modules
- hardcoded thresholds in multiple places

---

# ARCH-11 — Logging as a First-Class Layer

Logging is a dedicated system layer.

## Requirements
- all modules emit logs via logging system
- logs must include identifiers (`run_id`, `case_id`, etc.)
- raw inputs and outputs must be preserved

## Forbidden
- ad hoc logging (`print`)
- reconstructing state inside logging
- logging derived summaries without raw data

---

# ARCH-12 — Retry and Control Flow Centralization

Retry logic must be centralized.

## Requirements
- retries routed through execution entrypoint
- retry decisions made in one location

## Forbidden
- modules implementing independent retry loops
- hidden retry logic inside helpers

---

# ARCH-13 — Canonical Implementation Enforcement

Each responsibility must have exactly one implementation.

## Required
- identify canonical function for:
  - parsing
  - reconstruction
  - evaluation
  - logging
- remove duplicates

## Forbidden
- multiple implementations of same responsibility
- versioned helpers (`parse_v2`, `safe_parse`, etc.)
- fallback paths that duplicate logic

---

# ARCH-14 — Data Provenance Preservation

Data must not lose origin information.

## Required
- track source of each transformation
- preserve raw inputs
- log transformation steps

## Forbidden
- overwriting raw data
- mixing derived and original data
- losing attribution of transformations

---

# ARCH-15 — Integration Integrity

All pipeline modifications must preserve end-to-end integrity.

## Required
- integration tests for any pipeline change
- validation of full flow (prompt → execution → evaluation)

## Forbidden
- changes that only pass unit tests
- partial pipeline validation

---

# SUMMARY

The system must be:

- single-path (no duplication)
- explicitly layered (no mixing concerns)
- forward-flowing with controlled loops
- contract-driven
- centrally owned (no shadow logic)
- observable at every stage
- non-silent on failure

Any architecture that introduces:
- duplicate implementations
- pipeline bypasses
- hidden state
- unclear ownership
- implicit behavior

is non-compliant.