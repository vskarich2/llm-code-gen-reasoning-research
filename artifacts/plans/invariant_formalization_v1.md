# Invariant Formalization Plan v1

**Date:** 2026-03-30
**Scope:** Complete redesign of the invariant specification layer for the T3 code generation benchmark
**Status:** PLAN ONLY — no implementation

---

## Table of Contents

1. [Diagnosis: Why the Current Invariants Fail](#1-diagnosis)
2. [Target Invariant Model](#2-target-invariant-model)
3. [Invariant Schema](#3-invariant-schema)
4. [Invariant Strength Criteria](#4-invariant-strength-criteria)
5. [Family-by-Family Invariant Redesign](#5-family-by-family-invariant-redesign)
6. [Degenerate Pass Catalog](#6-degenerate-pass-catalog)
7. [Mechanism vs Outcome Policy](#7-mechanism-vs-outcome-policy)
8. [Invariant to Test Derivation Rules](#8-invariant-to-test-derivation-rules)
9. [Meta-Validation of Invariants](#9-meta-validation-of-invariants)
10. [Migration Plan](#10-migration-plan)

---

## 1. DIAGNOSIS: WHY THE CURRENT INVARIANTS FAIL

### 1.1 The Root Problem

The benchmark's invariants are **labels masquerading as specifications**. The current system stores invariants in three disconnected representations — natural language in `cases_v2.json` (`ground_truth_bug.invariant`), prose in `CASE_DOC.md`, and executable assertions in `tests_v2/test_*.py` — but none of these representations is a formal invariant. They are outcome descriptions.

The `ground_truth_bug.invariant` field for `retry_dup_a` reads: *"retry_send must send exactly once on first success."* This is not an invariant. It is one observable consequence of a correct implementation under one specific execution condition (success on first attempt). It says nothing about what must happen under failure-then-success, what state must exist before the call, what state is forbidden after the call, or what mechanisms must be preserved.

### 1.2 Taxonomy of Invariant Failures

The current invariant layer fails in the following structurally distinct ways:

#### F1: Invariants Phrased as Outcome Snapshots, Not State-Transition Rules

Every current invariant describes a point-in-time output check: "after X, Y must equal Z." None describes the required transition: "system must move from state S0 to state S1 via mechanism M, and state S2 must be forbidden."

**Examples:**
- `stale_cache`: "get_product() must return current data after update_product()" — says nothing about what "current" means if there are multiple cache layers, or what must be invalidated vs. what must be rewritten
- `partial_rollback`: "if a multi-step operation fails mid-sequence, all prior steps must be compensated" — says nothing about what constitutes compensation (reversal? no-op? state wipe?)
- `invariant_partial_fail`: "sender.balance + receiver.balance must be conserved after a failed transfer" — conservation is an output property, not a mechanism property; a no-op transfer trivially conserves balance

#### F2: Missing Complement Conditions

No invariant specifies both the positive and negative obligation. Tests check that a specific output value is correct after the fix, but never check that the system also works correctly on the happy path, or that the fixed behavior doesn't break adjacent functionality.

**Examples:**
- `wrong_condition_a`: Tests `is_rate_limited(5, 5) == True` (at-limit blocks). Never tests `is_rate_limited(4, 5) == False` (below-limit allows). A model returning `def is_rate_limited(count, limit): return True` passes.
- `missing_branch_a`: Tests `get_permissions("moderator")` returns non-empty set with "read" and "delete". Never tests that `get_permissions("admin")` still works. A model that replaces the entire permissions system with a moderator-only stub passes.
- `partial_rollback_a`: Tests that inventory is released after failed payment. Never tests that inventory is correctly reserved after successful payment. A model that makes `place_order` a no-op (always raises ValueError without reserving) passes.

#### F3: No Explicit Forbidden Behaviors

No invariant states what the system must NOT do. The current system only checks for the presence of correct outputs, never the absence of incorrect side effects.

**Examples:**
- `effect_order`: Tests that 3 snapshots exist with correct values. Does not forbid: (a) additional spurious snapshots, (b) snapshots at batch-end rather than per-item, (c) snapshots with correct values but wrong ordering relative to counter mutations.
- `hidden_dep_multihop`: Tests that `get_display_name("u1")` returns "Bob" after second save. Does not forbid: (a) the cache being bypassed entirely (direct DB read on every call), (b) the `_store` being wiped and rebuilt on every save.
- `alias_config`: Tests that `cfg2["timeout"] == 30`. Does not forbid: (a) `create_config` ignoring its overrides argument entirely, (b) `create_config` always returning a hardcoded dict.

#### F4: No Temporal Scope

No invariant specifies when it applies. "Cache should stay fresh" — fresh after how many operations? Across how many calls? After reset? After failure? The temporal scope is entirely implicit in the test code and differs silently between families.

**Examples:**
- `stale_cache`: The invariant applies across a write-then-read pair. But what about read-write-read-write-read? What about concurrent reads? The temporal scope is "one update cycle" but this is unstated.
- `mutable_default`: The invariant applies across consecutive calls. But the test only makes two calls. Is the invariant supposed to hold across N calls? After a module reload? This is unstated.
- `use_before_set`: The invariant applies "across repeated calls." But the test only checks call 1 → call 2. Does the invariant hold for call N → call N+1 for arbitrary N?

#### F5: No Mechanism Constraints

The most damaging failure. For families where the bug is about HOW something works (cache invalidation, retry loops, lock ordering, rollback compensation), the invariant only checks WHAT the output is. This allows mechanism-violating fixes that produce correct outputs by accident or by bypassing the intended subsystem.

**Examples:**
- `stale_cache`: A model that removes the cache entirely and reads directly from `_db` on every `get_product()` call passes all tests. The cache subsystem is never required to exist.
- `retry_dup`: A model that removes the retry loop entirely passes all tests because `fail_first=False` means success on the first attempt. The retry mechanism is never exercised.
- `false_fix_deadlock`: A model that returns `{"A": 100, "B": 100}` directly from both functions passes. The step-based transfer simulation is never required to execute.
- `invariant_partial_fail`: A model where `execute_transfer` is a no-op (catches exception, does nothing) conserves balance because nothing happened. The transfer mechanism is not required to attempt anything.

#### F6: No Distinction Between Observational and Implementation Equivalence

The benchmark treats two implementations as equivalent if they produce the same test outputs. For a research benchmark measuring reasoning about code mechanisms, this is fundamentally wrong. A model that "fixes" a stale cache bug by removing the cache has demonstrated a different reasoning capability than one that adds cache invalidation. The invariant system provides no way to distinguish these.

#### F7: No Cross-Boundary Semantics

For multi-file cases (retry_dup_b/c, config_shadowing, overdetermination, hidden_dep_multihop), the invariant says nothing about which module boundaries must be preserved. The harness flattens all files into one namespace via `CodeAssembler`. A model that collapses a 3-file system into a single flat implementation passes if the output is correct. The invariant does not require that `sender.py`, `store.py`, and `pipeline.py` remain as separate logical units with defined interfaces.

#### F8: No Formal Representation of the Failure Surface

No invariant defines the space of inputs or conditions under which the bug manifests. The "failure surface" is implicit in the single test case. This means:
- The test might exercise a path that the bug doesn't affect
- The test might not exercise the path that the bug does affect
- There is no way to know whether the invariant covers the full failure surface without reading both the invariant and the buggy code and manually reasoning about coverage

#### F9: No Treatment of Degenerate Fixes

No invariant explicitly excludes trivially-satisfying implementations. The `test_contract.assertions` in `cases_v2.json` are outcome assertions, not mechanism assertions. For every current invariant, there exists at least one degenerate implementation that satisfies it:
- `lost_update`: `def sequential_double_increment(): return 2`
- `config_shadowing`: `def run_system_check(): return {"request": {"timeout": 30}, "background": {"timeout": 30}}`
- `overdetermination`: `def serve_request(id): return {"value": 99}`
- `invariant_partial_fail`: `def execute_transfer(s, r, amt): raise RuntimeError("fail")` (no-op, conserves balance)
- `partial_rollback_a`: `def place_order(inv, wallet, qty, price): raise ValueError("fail")` (no-op, inventory never touched)

#### F10: No Way to Express Compound Constraints

Some invariants require expressing: "X must change AND Y must remain unchanged AND the change to X must happen via mechanism M." The current system can only express: "After calling F, check that output == expected." There is no compositional structure for:
- "Update field A without corrupting field B" (partial_update)
- "Invalidate cache layer 1 AND cache layer 2" (stale_cache_c)
- "Rollback reservation AND rollback audit log AND raise exception" (partial_rollback_c)
- "Transfer amount from sender AND to receiver, atomically" (invariant_partial_fail)

### 1.3 Summary Diagnosis

| Failure Mode | Frequency | Impact |
|---|---|---|
| F1: Outcome snapshots, not transitions | Universal | All invariants under-constrain |
| F2: Missing complements | ~70% of families | False positives from always-block/always-allow |
| F3: No forbidden behaviors | Universal | No-op and bypass fixes pass |
| F4: No temporal scope | ~80% of families | Unclear what "across calls" means |
| F5: No mechanism constraints | ~50% of families | Cache bypass, retry removal pass |
| F6: No obs. vs. impl. distinction | Universal | Cannot classify fix quality |
| F7: No cross-boundary semantics | ~30% of families | Namespace flattening undetected |
| F8: No failure surface | Universal | Test coverage unknown |
| F9: No degenerate exclusion | Universal | Trivial passes undetected |
| F10: No compound constraints | ~40% of families | Can't express "change X, preserve Y" |

---

## 2. TARGET INVARIANT MODEL

### 2.1 Overview

A strong invariant is a **state-transition specification** with five components:

```
INVARIANT := (PRE, ACTION, POST_REQUIRED, POST_FORBIDDEN, META)
```

Where:
- **PRE**: The required system state before the action. Includes all observable state variables, their allowed values, and any setup actions that must have occurred.
- **ACTION**: The trigger — the function call, sequence of calls, or interleaving that exercises the invariant.
- **POST_REQUIRED**: The required system state after the action. Includes all observable state variables that must hold specific values or satisfy specific predicates.
- **POST_FORBIDDEN**: The system state that must NOT exist after the action. Explicitly excludes degenerate outcomes.
- **META**: Constraints on HOW the transition happened — mechanism requirements, temporal ordering, boundary preservation, repeatability.

### 2.2 State Model

Every invariant operates on a **state space** consisting of:

```
STATE := {
  primary_entities:    [explicitly named state variables],
  derived_entities:    [state computed from primary entities],
  side_effect_traces:  [observable effects: logs, notifications, audit entries],
  structural_entities: [functions, classes, modules that must exist],
  mechanism_traces:    [evidence that a specific mechanism was used]
}
```

### 2.3 Invariant Components in Detail

#### 2.3.1 Preconditions

Preconditions define the required starting state. They must be:
- **Concrete**: Specific values, not "some valid state"
- **Minimal**: Only the state relevant to the invariant, not the entire system
- **Reproducible**: A test can establish the precondition deterministically

Types of preconditions:
- **Value preconditions**: `_value == 0`, `balance == 100`
- **Structural preconditions**: `get()` exists, `_set()` exists, `Account` class exists
- **State-history preconditions**: `reset()` was called, `no prior calls to F()`
- **Configuration preconditions**: `fail_first == True`, `max_retries == 3`

#### 2.3.2 Actions

Actions define what triggers the invariant check. They must specify:
- **Single-call**: `retry_send("hello", max_retries=2)`
- **Multi-call sequence**: `save_user(Alice); save_user(Bob); get_display_name()`
- **Interleaving**: `run_steps([(read_a, ()), (read_b, ()), (write_a, ()), (write_b, ())])`
- **Failure injection**: `_random_mod.random = lambda: 0.0` before `execute_transfer()`

#### 2.3.3 Required Postconditions

Required postconditions define what MUST be true after the action. Multiple types:
- **Value postconditions**: `get() == 2`, `balance == 50`
- **Predicate postconditions**: `balance >= 0`, `len(sent) == 1`
- **Relational postconditions**: `sender.balance + receiver.balance == initial_total`
- **Temporal postconditions**: `snapshots[0]` was recorded before `snapshots[1]`
- **Identity postconditions**: `cfg1 is not cfg2` (not just equality, but distinct objects)
- **Trace postconditions**: `_sent` contains exactly `["hello"]`

#### 2.3.4 Forbidden Postconditions

Forbidden postconditions define what MUST NOT be true. This is the anti-degenerate layer:
- **No-op exclusion**: `execute_transfer must have attempted debit` (not just conserved balance)
- **Bypass exclusion**: `_cache must have been consulted` (not bypassed by direct DB read)
- **Hardcoding exclusion**: `function must produce different output for different input` (via second test with different values)
- **Collapse exclusion**: `module must define both send() and store_message()` (not collapsed into one function)

#### 2.3.5 Meta-Constraints

Meta-constraints govern the HOW:
- **Mechanism requirements**: "Must use cache_put, not cache_put_if_absent"
- **Boundary requirements**: "Fix must reside in file X, not file Y"
- **Repeatability requirements**: "Must pass on N consecutive calls with state reset between each"
- **Temporal ordering**: "snapshot() must be called after each item's counter increment, not at batch end"
- **Idempotency requirements**: "Calling test twice on the same module state must produce the same result"

### 2.4 Invariant Taxonomy by Semantic Domain

| Domain | What It Constrains | Key Properties |
|---|---|---|
| **Identity/Aliasing** | Object identity, reference sharing | `is` vs `==`, mutation isolation, copy semantics |
| **Field Synchronization** | Derived state consistency | Change field A → derived field B updates |
| **Cache Coherence** | Staleness prevention | Write-through, invalidation, freshness after update |
| **Lifecycle/Reset** | State management across phases | Configure → use → reset → reconfigure |
| **Default Isolation** | Mutable argument independence | Per-call fresh state, no accumulation |
| **Side-Effect Timing** | When effects occur | Per-item vs per-batch, ordering relative to mutations |
| **Edge-Case Safety** | Boundary correctness | Off-by-one, empty input, zero-amount |
| **Retry/Idempotency** | Duplicate prevention under retry | Exactly-once delivery, failure-then-success behavior |
| **Rollback/Compensation** | Failure recovery | Full compensation, partial success handling |
| **Condition Correctness** | Boolean logic | Operator precedence, threshold direction, AND vs OR |
| **Branch Completeness** | Exhaustive dispatch | All valid inputs have handlers, no silent fallthrough |
| **Temporal Consistency** | Pre-transformation data preservation | Raw stats on original data, not transformed |
| **Structure Synchronization** | Parallel data alignment | Insert/delete in one structure mirrors in others |
| **Configuration Propagation** | Flag/setting flow | Propagation through call chain, cleanup after use |
| **Pipeline Integrity** | Multi-stage state evolution | Commit gates, freeze semantics, preview vs. ingest |
| **Cross-Module Dependency** | Hidden coupling | Write-through across module boundaries |
| **Atomicity/Locking** | Concurrent correctness | Mutual exclusion, deadlock freedom, conservation |

### 2.5 What the Model Must Distinguish

The invariant system must support classification of model outputs into:

| Classification | Definition | Invariant Support Required |
|---|---|---|
| **True Fix** | Correct output via correct mechanism | POST_REQUIRED + META mechanism check |
| **Partial Fix** | Some postconditions met, others not | Per-postcondition pass/fail reporting |
| **Lucky Fix** | Correct output on tested inputs, wrong on others | Multiple input sets in ACTION |
| **Behaviorally Correct, Mechanism-Violating** | Right output, wrong mechanism | META mechanism check fails |
| **Degenerate Pass** | Trivially satisfies output checks | POST_FORBIDDEN catches it |
| **Reasoning-Correct, Execution-Failed** | Right intent, syntax/runtime error | Separate from invariant (harness level) |
| **Cross-Boundary Misunderstanding** | Wrong file/function targeted | META boundary check |
| **State Contamination** | Prior call state leaks into current | Repeated-call invariant with reset |

---

## 3. INVARIANT SCHEMA

### 3.1 Schema Definition

Each invariant is a structured record with the following fields:

```yaml
invariant:
  # --- IDENTITY ---
  invariant_id: string          # Unique identifier, e.g., "INV-retry_dup_a-001"
  family: string                # Bug family, e.g., "retry_dup"
  case_id: string               # Case this invariant belongs to
  bug_pattern: string           # Bug mechanism, e.g., "retry_state_accumulation"
  semantic_domain: string       # From taxonomy: "retry_idempotency", "cache_coherence", etc.

  # --- SCOPE ---
  scope: enum                   # "single_call" | "multi_call_sequence" | "interleaved" | "failure_injection"
  boundary_type: enum           # "local" | "cross_function" | "cross_module" | "cross_layer"
  temporal_scope: string        # When invariant applies: "per_call", "across_calls", "after_reset",
                                # "after_failure", "across_retries", "across_modules"
  statefulness: enum            # "stateless" | "stateful_within_call" | "stateful_across_calls"

  # --- ENTITIES ---
  target_entities:
    primary: list[string]       # State variables the invariant constrains, e.g., ["_sent", "_counter"]
    derived: list[string]       # Computed state, e.g., ["display_name", "full_name"]
    structural: list[string]    # Functions/classes that must exist, e.g., ["retry_send", "get_sent"]
    side_effects: list[string]  # Observable traces, e.g., ["_audit_log", "_notifications"]

  # --- STATE TRANSITION ---
  pre_state:
    description: string         # Human-readable precondition
    concrete: list[string]      # Machine-checkable preconditions as Python expressions
                                # e.g., ["len(mod._sent) == 0", "mod._counter == 0"]
    setup_actions: list[string] # Actions to establish precondition
                                # e.g., ["mod.reset()", "mod._sent = []"]

  trigger:
    description: string         # Human-readable action description
    primary_action: string      # The main action, e.g., "mod.retry_send('hello', max_retries=2)"
    action_sequence: list[dict] # Ordered list of actions with parameters
                                # Each: {call: string, args: dict, expect: string}
    failure_injection: dict     # Optional: {target: string, mock: string, restore: string}

  required_post_state:
    description: string         # Human-readable postcondition
    assertions: list[dict]      # Each: {expr: string, message: string, category: string}
                                # Categories: "value", "predicate", "relational", "identity", "trace"
    happy_path_obligations: list[dict]  # Complement assertions that must also hold
                                        # Each: {expr: string, message: string}

  forbidden_post_state:
    description: string         # What must NOT happen
    exclusions: list[dict]      # Each: {pattern: string, detection: string, message: string}
                                # pattern: "no_op", "always_block", "always_allow", "hardcoded",
                                #          "bypass_cache", "bypass_retry", "collapse_modules", etc.
                                # detection: Python expression or structural check

  # --- MECHANISM ---
  mechanism_requirements:
    required: boolean           # Whether mechanism constraints apply
    constraints: list[dict]     # Each: {description: string, check: string, severity: string}
                                # check: how to verify (structural, behavioral, or trace-based)
    preserved_subsystems: list[string]  # Subsystems that must exist in the fix
                                        # e.g., ["cache layer", "retry loop", "lock acquisition"]
    forbidden_bypasses: list[string]    # Mechanisms that must NOT be used
                                        # e.g., ["remove cache entirely", "remove retry loop"]

  # --- ANTI-DEGENERATE ---
  degenerate_pass_patterns: list[dict]
    # Each: {name: string, implementation: string, why_it_passes: string, detection: string}
    # implementation: pseudocode of the degenerate fix
    # detection: how the invariant system prevents this from passing

  # --- OBSERVABILITY ---
  observability_requirements:
    required_traces: list[string]       # State that must be observable
    mechanism_evidence: list[string]    # Evidence that mechanism was used
                                        # e.g., ["results contain 'before'/'after' keys"]

  # --- TESTING DERIVATION ---
  complement_conditions: list[dict]     # Each: {description: string, test: string}
                                        # Tests for the OTHER side of the invariant
  minimal_happy_path: dict              # {action: string, expected: string}
                                        # The simplest test that the system works at all
  minimal_failure_path: dict            # {action: string, expected: string}
                                        # The simplest test that the failure mode is handled
  mutation_sensitivity: list[string]    # Dimensions the fix must be tested across
                                        # e.g., ["different input values", "different initial state",
                                        #         "repeated calls", "failure then success"]

  # --- RESET ---
  reset_requirements:
    has_reset: boolean                  # Whether the system has reset semantics
    reset_actions: list[string]         # How to reset, e.g., ["mod.reset()", "mod._sent = []"]
    post_reset_state: list[string]      # Required state after reset

  # --- ADVERSARIAL ---
  adversarial_dimensions: list[string]  # What an adversarial model would try
                                        # e.g., ["hardcode return value", "remove retry loop",
                                        #         "bypass cache", "always raise exception"]

  # --- CLASSIFICATION ---
  semantic_strength_level: enum         # "INVALID" | "WEAK" | "USABLE" | "STRONG" | "RESEARCH_GRADE"
  current_strength_assessment: string   # Assessment of the invariant as currently implemented
  strength_gaps: list[string]           # What would need to change to reach RESEARCH_GRADE
```

### 3.2 Schema Constraints

1. Every invariant MUST have at least one entry in `degenerate_pass_patterns`.
2. Every invariant with `statefulness != "stateless"` MUST define `reset_requirements`.
3. Every invariant with `scope == "failure_injection"` MUST define both `minimal_happy_path` and `minimal_failure_path`.
4. Every invariant with `mechanism_requirements.required == true` MUST define at least one entry in `mechanism_requirements.constraints`.
5. Every invariant MUST have at least one entry in `complement_conditions`.
6. `required_post_state.assertions` MUST contain at least two assertions (prevents single-check invariants).
7. `forbidden_post_state.exclusions` MUST contain at least one entry.

---

## 4. INVARIANT STRENGTH CRITERIA

### 4.1 Strength Levels

#### INVALID

An invariant is INVALID if ANY of the following are true:
- It can be satisfied by a no-op implementation (function that does nothing or always raises)
- It can be satisfied by a constant-returning function
- It has zero assertions
- It has no defined precondition
- It contradicts the stated bug pattern

#### WEAK

An invariant is WEAK if ANY of the following are true:
- It can be satisfied by `always True` or `always False`
- It checks only one side of a threshold/condition (e.g., "blocks at limit" but not "allows below limit")
- It does not constrain the happy path when a happy path exists
- It does not constrain repeated-call behavior when stateful
- It does not define pre/post state explicitly
- It does not exclude any degenerate implementation
- It checks count but not content of side effects
- It checks content but not ordering of side effects when ordering matters
- It has only one assertion

#### USABLE WITH CAVEATS

An invariant is USABLE if:
- It has two or more assertions targeting different state dimensions
- It cannot be satisfied by constant return values (tested with at least two different inputs)
- It defines both a failure path and a happy path when applicable
- It has at least one explicit degenerate exclusion

But at least one of these gaps remains:
- No mechanism constraint when the family is mechanism-sensitive
- No temporal ordering check when side-effect timing matters
- No cross-boundary check when the case is multi-file
- No repeated-call test when the system is stateful

#### STRONG

An invariant is STRONG if:
- All USABLE criteria are met
- Mechanism constraints are defined when the family requires them
- At least two input scenarios prevent hardcoding
- Both happy path and failure path are tested when applicable
- Repeated-call behavior is tested when the system is stateful
- Reset semantics are tested when the system supports reset
- At least one structural check validates the fix preserves required functions/state

#### RESEARCH-GRADE

An invariant is RESEARCH-GRADE if:
- All STRONG criteria are met
- Degenerate pass patterns are explicitly enumerated and tested against
- Mechanism traces provide evidence of HOW the fix works, not just WHAT it outputs
- Cross-boundary semantics are validated when applicable
- The invariant supports classification into: true fix, partial fix, lucky fix, mechanism-violating fix
- Mutation sensitivity dimensions are defined and tested
- The invariant has been validated against at least 3 known degenerate implementations

### 4.2 Review Rubric

| Criterion | Points | How to Check |
|---|---|---|
| Has >=2 assertions on different state dimensions | 1 | Count unique state variables in assertions |
| Cannot be satisfied by constant return | 2 | Verify with two input sets |
| Tests happy path when one exists | 1 | Check `happy_path_obligations` is non-empty |
| Tests failure path when failure semantics exist | 1 | Check `minimal_failure_path` is defined |
| Excludes at least one degenerate pattern | 2 | Check `forbidden_post_state.exclusions` |
| Has mechanism constraint when family is mechanism-sensitive | 2 | Check `mechanism_requirements` |
| Tests repeated-call behavior when stateful | 1 | Check for multi-call test pattern |
| Tests with multiple input values | 1 | Check `mutation_sensitivity` |
| Has structural preservation check | 1 | Check for `hasattr` or function existence checks |
| Has cross-boundary validation when multi-file | 1 | Check boundary semantics |

**Scoring:**
- 0-2: INVALID
- 3-5: WEAK
- 6-8: USABLE
- 9-11: STRONG
- 12-13: RESEARCH-GRADE

### 4.3 Automatic Disqualifiers

An invariant MUST fail review if:
1. `def f(): return <constant>` satisfies all assertions
2. `def f(): raise Exception()` satisfies all assertions
3. `def f(): pass` satisfies all assertions
4. A function that ignores all arguments satisfies all assertions
5. Removing the target subsystem (cache, retry loop, lock) satisfies all assertions
6. Flattening multi-file logic into one function satisfies all assertions

---

## 5. FAMILY-BY-FAMILY INVARIANT REDESIGN

### 5.1 alias_config

**A. Current implicit invariant:** "create_config() must return a fresh dict; mutating one config must not affect future calls or DEFAULTS."

**B. Why insufficient:**
- Tests only one contamination scenario (timeout override). Doesn't check deep nesting.
- No complement: never checks that overrides actually work (happy path for the override mechanism itself).
- No forbidden behavior: doesn't exclude `create_config` ignoring its argument entirely.

**C. Degenerate implementations that satisfy it:**
1. `def create_config(overrides=None): return {"timeout": 30, "retries": 3, "debug": False}` — ignores overrides, always returns defaults. Passes because test only checks that cfg2 (called with no overrides) has default values.
2. `def create_config(overrides=None): return dict(DEFAULTS)` where DEFAULTS is recreated as a literal each time — correct but doesn't demonstrate understanding of the aliasing bug.

**D. Strong invariant:**
- PRE: DEFAULTS has known values {timeout: 30, retries: 3, debug: False}
- ACTION 1 (override): `cfg1 = create_config({"timeout": 5})`
- POST_REQUIRED (override applied): `cfg1["timeout"] == 5`
- ACTION 2 (clean call): `cfg2 = create_config()`
- POST_REQUIRED (isolation): `cfg2["timeout"] == 30`
- POST_REQUIRED (DEFAULTS unmodified): `DEFAULTS["timeout"] == 30`
- POST_REQUIRED (identity): `cfg1 is not cfg2`
- POST_FORBIDDEN: `cfg1 is DEFAULTS`, `cfg2 is DEFAULTS` (must not return the DEFAULTS object itself)
- ACTION 3 (mutation test): `cfg1["debug"] = True`
- POST_REQUIRED (mutation isolation): `cfg2.get("debug") == False`, `DEFAULTS.get("debug") == False`

**E. Complement conditions:**
- Override must actually take effect: `create_config({"timeout": 5})["timeout"] == 5`
- Multiple overrides: `create_config({"timeout": 5, "debug": True})` has both

**F. State to observe:** `DEFAULTS` (must be unmodified), return values of create_config (must be independent)

**G. Mechanism-sensitive:** Yes — the fix must involve copying or constructing a new dict, not removing the override mechanism.

**H. Minimum obligations:**
- Happy path: override applied correctly
- Failure path: mutation of one config doesn't leak to another or to DEFAULTS

---

### 5.2 partial_update

**A. Current implicit invariant:** "Derived/dependent fields must stay in sync after updates."

**B. Why insufficient:**
- Only checks the derived field that should change. Doesn't check that unrelated fields are preserved.
- No complement: doesn't test that update works for the non-derived primary field.
- Level C tests `verified` reset on email change but doesn't verify that name change does NOT reset `verified`.

**C. Degenerate implementations:**
1. `def update_profile(user, changes): user.update(changes); user["display_name"] = changes.get("name", user.get("name"))` — always sets display_name from changes dict, even when name isn't being changed (would overwrite display_name with None if only email is changed)
2. `def update_profile(user, changes): user.update(changes); user["display_name"] = user["name"]; user["full_name"] = user.get("first_name", "") + " " + user.get("last_name", ""); user["verified"] = False` — always resets verified, even on non-email changes

**D. Strong invariant:**
- PRE: User created with known values
- ACTION: `update_profile(user, {"name": "Bob"})`
- POST_REQUIRED: `user["name"] == "Bob"`, `user["display_name"] == "Bob"`
- POST_REQUIRED (preservation): `user["email"] == "alice@example.com"` (unchanged)
- COMPLEMENT ACTION: `update_profile(user, {"email": "new@example.com"})`
- POST_REQUIRED: `user["email"] == "new@example.com"`
- POST_REQUIRED: `user["display_name"] == "Bob"` (display_name unchanged because name wasn't changed)
- Level C specific:
  - POST_REQUIRED: After email change, `verified == False`
  - COMPLEMENT: After name change (not email), `verified` remains True

**E. Complement conditions:**
- Changing field A updates derived A' but does NOT change unrelated derived B'
- Changing field B updates derived B' but does NOT change unrelated derived A'

**F. State to observe:** All user fields, not just the changed one

**G. Mechanism-sensitive:** No — output equivalence is sufficient here.

**H. Minimum obligations:**
- Happy path: update works and syncs derived field
- Preservation path: update does not corrupt unrelated fields
- Selective path: different updates trigger different derived field updates

---

### 5.3 stale_cache

**A. Current implicit invariant:** "get_product() must return current data after update_product()."

**B. Why insufficient:**
- Only tests one key. Model that invalidates only for "p1" passes.
- No mechanism constraint: model that removes cache entirely passes.
- Only tests price field. Model that updates price but leaves other fields stale passes.
- No complement: doesn't verify that cache actually provides value (i.e., that cached reads are faster or that the cache exists).

**C. Degenerate implementations:**
1. Remove cache entirely: `def get_product(pid): return _db[pid]` — always reads from DB, cache never consulted.
2. Special-case "p1": `def get_product(pid): if pid == "p1": return _db[pid]; return _cache.get(pid, _db[pid])` — cache bypassed only for tested key.
3. Rebuild cache on every read: `def get_product(pid): _cache[pid] = _db[pid]; return _cache[pid]` — cache is meaningless, rebuilt every time.

**D. Strong invariant:**
- PRE: Empty DB and cache
- ACTION 1: `add_product("p1", "Widget", 10.0)`
- ACTION 2: `get_product("p1")` — primes cache
- ACTION 3: `update_product("p1", price=25.0)`
- ACTION 4: `result = get_product("p1")`
- POST_REQUIRED: `result["price"] == 25.0`
- ANTI-HARDCODING ACTION: Same sequence with "p2" and different prices
- POST_REQUIRED: `result2["price"] == <different_expected_value>`
- MECHANISM (when required): `_cache` dict must exist and be consulted (not bypassed). Evidence: `"p1" in mod._cache` after a read.
- POST_FORBIDDEN: Cache bypass (removing `_cache` entirely). Detection: `hasattr(mod, "_cache")` or structural AST check.

**E. Complement conditions:**
- Cache hit: After add + get (prime), second get returns same value (cache working)
- Cache miss: get on non-existent key returns None or raises appropriately

**F. State to observe:** `_db`, `_cache`, return values

**G. Mechanism-sensitive:** YES for levels B and C (cross-file cache invalidation is the point). Level A is borderline.

**H. Minimum obligations:**
- Happy path: add + get returns correct value
- Stale path: add + get + update + get returns updated value
- Multi-key: at least two different keys tested

---

### 5.4 lazy_init

**A. Current implicit invariant:** "After reset + reconfigure, all getters must reflect the new config."

**B. Why insufficient:**
- Tests only one getter per level. Model that fixes one getter but leaves others stale passes.
- No complement: doesn't test that DEFAULT values are returned before configure().
- Doesn't test that a second reconfigure also works (multi-cycle lifecycle).

**C. Degenerate implementations:**
1. `def get_host(): return "prod.example.com"` — hardcoded to test value
2. `def get_host(): return _settings.get("host", "localhost")` — reads from dict but doesn't prove lazy evaluation was fixed

**D. Strong invariant:**
- PRE: Settings at defaults
- ACTION 1: `configure(host="prod.example.com")`
- POST_REQUIRED: `get_host() == "prod.example.com"`
- COMPLEMENT: Before configure, `get_host() == "localhost"` (default)
- ANTI-HARDCODING: `configure(host="staging.example.com")`, `get_host() == "staging.example.com"`
- LIFECYCLE: reset, configure to new value, verify

**E. Complement conditions:** Default values returned before any configure call

**F. State to observe:** `_settings` dict, getter return values

**G. Mechanism-sensitive:** Yes — the bug is about lazy initialization capturing stale values. The fix must ensure getters re-read from the config source, not from a captured snapshot.

**H. Minimum obligations:**
- Happy path: configure works
- Default path: before configure, defaults are returned
- Multi-cycle: configure → get → reset → configure(different) → get

---

### 5.5 mutable_default

**A. Current implicit invariant:** "Mutable default arguments must not leak state across calls."

**B. Why insufficient:**
- Only tests two calls. Doesn't verify three or more (accumulation pattern).
- No complement: doesn't verify that the function works correctly on the first call.

**C. Degenerate implementations:**
1. `def enqueue(task, queue=None): return [task]` — always returns new single-element list, ignoring queue parameter. Passes because test only checks second call has length 1.

**D. Strong invariant:**
- PRE: No prior calls
- ACTION 1: `q1 = enqueue(task1)`
- POST_REQUIRED: `len(q1) == 1`, `q1[0] == task1`
- ACTION 2: `q2 = enqueue(task2)`
- POST_REQUIRED: `len(q2) == 1`, `q2[0] == task2` (not task1)
- POST_FORBIDDEN: `q2` contains task1 (state leaked)
- POST_REQUIRED (identity): `q1 is not q2`
- ANTI-ACCUMULATION: Third call `q3 = enqueue(task3)`, `len(q3) == 1`

**E. Complement conditions:**
- When explicit queue is passed, it should be used: `enqueue(task, existing_queue)` appends to existing_queue

**F. State to observe:** Return values, default argument state

**G. Mechanism-sensitive:** Partially — the fix must change how the default is handled (None sentinel + new list), but the exact implementation doesn't matter as long as isolation holds.

**H. Minimum obligations:**
- Happy path: single call returns correct result
- Isolation: second call is independent
- Accumulation: third call is still independent

---

### 5.6 effect_order

**A. Current implicit invariant:** "Side effects (snapshot/emit/audit) must happen per-item, not once at batch end."

**B. Why insufficient:**
- Level A: now checks both count AND values (`snapshots == [10, 30, 60]`), which is good.
- But: doesn't verify that snapshots are taken AFTER counter increment (timing). A model that calls `snapshot()` three times at batch start with pre-computed values would pass.
- No complement: doesn't verify that batch-level behavior still works (e.g., the batch still returns the correct aggregate).

**C. Degenerate implementations:**
1. `def process_batch(items): _snapshots.extend([10, 30, 60])` — hardcoded snapshot values without processing items.
2. Process all items into counter, then snapshot three times with counter value: `for item in items: _counter += item` then `for _ in items: _snapshots.append(_counter)` — snapshots all equal 60.

**D. Strong invariant:**
- PRE: `_counter == 0`, `_snapshots == []`
- ACTION: `process_batch([10, 20, 30])`
- POST_REQUIRED: `snapshots == [10, 30, 60]` (running totals prove per-item timing)
- ANTI-HARDCODING ACTION: `process_batch([5, 15, 25])`, `snapshots == [5, 20, 45]`
- POST_REQUIRED: `_counter == 60` after first batch (or 45 after second)
- POST_FORBIDDEN: All snapshots have the same value (proves batch-end not per-item)

**E. Complement conditions:**
- Batch return value (if any) is still correct
- Counter is incremented correctly regardless of snapshot timing

**F. State to observe:** `_counter`, `_snapshots`, return value of `process_batch`

**G. Mechanism-sensitive:** YES — the invariant is about WHEN snapshots happen relative to counter mutations. This is a timing/ordering constraint.

**H. Minimum obligations:**
- Per-item values: snapshots are running totals, not final totals
- Anti-hardcoding: different input produces different snapshot values
- Counter correctness: final counter matches sum of items

---

### 5.7 use_before_set

**A. Current implicit invariant:** "Variables must reflect current call's state, not prior state."

**B. Why insufficient:**
- Only tests with empty second input. Doesn't test with different non-empty second input to distinguish "returns empty" from "returns fresh for current input."
- No complement: doesn't verify first call was actually correct.

**C. Degenerate implementations:**
1. `def transform(data): return list(data)` — always returns copy of input, correct but doesn't prove understanding of the use-before-set bug.
2. `def transform(data): return [] if not data else [x*2 for x in data]` — handles empty case specially, might not handle non-empty-but-different correctly.

**D. Strong invariant:**
- PRE: No prior calls (or after reset)
- ACTION 1: `r1 = transform([1, 2, 3])`
- POST_REQUIRED: `r1 == [2, 4, 6]` (or whatever the correct transform is)
- ACTION 2: `r2 = transform([])`
- POST_REQUIRED: `r2 == []`
- POST_FORBIDDEN: `r2 == r1` or `r2 == [2, 4, 6]`
- ANTI-HARDCODING ACTION 3: `r3 = transform([10])`
- POST_REQUIRED: `r3 == [20]` (proves current call's data is used)
- POST_FORBIDDEN: `r3` contains any element from r1

**E. Complement conditions:**
- First call with real data produces correct result
- Third call with different data produces result from third call's data, not first or second

**F. State to observe:** Return values, any module-level state (`_last_result`, etc.)

**G. Mechanism-sensitive:** No — output correctness is sufficient.

**H. Minimum obligations:**
- Happy path: non-empty input → correct output
- Stale prevention: empty input after non-empty → empty output
- Fresh data: non-empty input after empty → output from current input

---

### 5.8 retry_dup

**A. Current implicit invariant:** "Each message should appear exactly once in the store after a successful send, regardless of retry logic."

**B. Why insufficient:**
- **Critical flaw:** All three levels call with `fail_first=False`. The retry path is NEVER exercised. A model that removes the retry loop entirely passes.
- No complement: doesn't verify that retry actually works (message delivered after failure-then-success).
- No mechanism constraint: doesn't require the retry loop to exist.

**C. Degenerate implementations:**
1. `def retry_send(msg, max_retries=2): _sent.append(msg)` — no retry loop, just direct send. Passes because first attempt always succeeds.
2. `def retry_send(msg, max_retries=2): send(msg); return` — calls send once, no retry logic. Passes.

**D. Strong invariant:**
- PRE: `_sent == []`
- ACTION 1 (success path): `retry_send("hello", max_retries=2)` with `fail_first=False`
- POST_REQUIRED: `len(_sent) == 1`, `_sent[0] == "hello"`
- ACTION 2 (failure-then-success path): Reset, then `retry_send("world", max_retries=3, fail_first=True)`
- POST_REQUIRED: `len(_sent) == 1`, `_sent[0] == "world"` (exactly once despite retry)
- POST_FORBIDDEN: `len(_sent) == 0` (message not delivered), `len(_sent) > 1` (duplicated)
- MECHANISM: retry loop must exist. Structural check: function body contains loop or recursive call with decrementing counter.
- ANTI-DEGENERATE: If `fail_first=True`, the function MUST have attempted at least once before succeeding. Evidence: `_attempt_count >= 2` when `fail_first=True`.

**E. Complement conditions:**
- Success-on-first: exactly one message
- Failure-then-success: exactly one message (retry worked, no duplication)
- All-failures: no message delivered, appropriate error/return (if applicable)

**F. State to observe:** `_sent`, `_attempt_count`, return value

**G. Mechanism-sensitive:** YES — the retry loop is the entire point. Removing it is not a fix.

**H. Minimum obligations:**
- Happy path: success delivers exactly once
- Retry path: failure-then-success delivers exactly once
- Mechanism: retry loop exists and executes

---

### 5.9 partial_rollback

**A. Current implicit invariant:** "If a multi-step operation fails mid-sequence, all prior steps must be compensated (rolled back)."

**B. Why insufficient:**
- **Critical flaw:** Only tests the failure path. Never tests the success path. A model where `place_order` is a no-op (always raises without doing anything) passes because inventory is never touched.
- No complement: doesn't verify that successful orders actually work.
- Doesn't verify that the failure mechanism is correct (payment fails, not some other error).

**C. Degenerate implementations:**
1. `def place_order(inv, wallet, qty, price): raise ValueError("fail")` — no-op, always fails, inventory never reserved. Passes because inventory check sees original values.
2. `def place_order(inv, wallet, qty, price): pass` — no-op, doesn't raise. Inventory never touched. Would fail because test expects ValueError, but a model that raises ValueError without doing anything passes.

**D. Strong invariant:**
- PRE: `inv.available() == 10`, `wallet.balance == <known>`
- ACTION 1 (happy path): Create wallet with sufficient funds, call `place_order(inv, wallet, 3, 10.0)`
- POST_REQUIRED (happy path): `inv.available() == 7` (3 items reserved/sold), wallet balance decreased
- ACTION 2 (failure path): Create wallet with zero funds, call `place_order(inv, wallet_empty, 3, 10.0)`
- POST_REQUIRED (failure path): ValueError raised, `inv.available() == 10` (rolled back), `inv.reserved == 0`
- POST_FORBIDDEN: No-op (inventory must have been temporarily reserved before failure). Detection: if `inv.available()` was never modified during the call, the function didn't attempt the transaction.

**E. Complement conditions:**
- Successful order reserves inventory correctly
- Failed order restores inventory completely
- Multiple successful orders accumulate correctly

**F. State to observe:** `inv.available()`, `inv.reserved`, `wallet.balance`, audit log, exception type

**G. Mechanism-sensitive:** YES — the fix must implement try/except with compensation, not avoid the transaction entirely.

**H. Minimum obligations:**
- Happy path: successful order works
- Failure path: failed order fully compensates
- No-op exclusion: function must attempt the transaction

---

### 5.10 temporal_drift

**A. Current implicit invariant:** "raw_stats must reflect the ORIGINAL data, not any transformed/normalized version."

**B. Why insufficient:**
- Uses fixed test data, so hardcoded returns pass.
- Each difficulty level uses different data, but each only tests one input.
- No complement: doesn't verify that the transformed data is also correct.

**C. Degenerate implementations:**
1. `def pipeline(data): return {"raw_stats": {"raw_max": max(data), "raw_min": min(data), "raw_sum": sum(data)}}` — computes raw stats correctly but skips the entire transformation pipeline. Passes, but doesn't prove the model understood the temporal drift issue.

**D. Strong invariant:**
- PRE: No prior state
- ACTION 1: `result = pipeline([10, 50, 30, 80, 20])`
- POST_REQUIRED: `raw_stats == {"raw_max": 80, "raw_min": 10, "raw_sum": 190}`
- ANTI-HARDCODING ACTION 2: `result2 = pipeline([5, 15, 25])`
- POST_REQUIRED: `raw_stats == {"raw_max": 25, "raw_min": 5, "raw_sum": 45}`
- POST_REQUIRED (transformation occurred): `result["transformed"]` exists and differs from `result["raw_stats"]`
- POST_FORBIDDEN: `result["transformed"]` is identical to raw data (transformation didn't happen)

**E. Complement conditions:**
- Transformation pipeline still produces correct transformed output
- Raw stats are computed from original data, transformed stats from transformed data

**F. State to observe:** `raw_stats`, `transformed` output, intermediate pipeline state

**G. Mechanism-sensitive:** Partially — must preserve both the raw stats computation and the transformation pipeline.

**H. Minimum obligations:**
- Correct raw stats
- Different input produces different raw stats
- Transformation still occurs (pipeline not gutted)

---

### 5.11 missing_branch

**A. Current implicit invariant:** "All documented roles must receive their correct permissions."

**B. Why insufficient:**
- Only tests the MISSING role. Doesn't verify existing roles still work.
- A model that replaces the entire permission system with a stub for the tested role passes.

**C. Degenerate implementations:**
1. `def get_permissions(role): return {"read", "delete"}` — always returns moderator's permissions regardless of role.
2. `def get_permissions(role): if role == "moderator": return {"read", "delete"}; return set()` — adds moderator but breaks all other roles.

**D. Strong invariant:**
- PRE: Permission system with known roles (admin, user)
- ACTION 1 (missing role): `get_permissions("moderator")`
- POST_REQUIRED: Contains "read" and "delete"
- ACTION 2 (existing role regression): `get_permissions("admin")`
- POST_REQUIRED: Contains admin's expected permissions (not moderator's)
- ACTION 3 (another existing role): `get_permissions("user")`
- POST_REQUIRED: Contains user's expected permissions
- POST_FORBIDDEN: All roles return the same permissions (always-same degenerate)

**E. Complement conditions:**
- Existing roles still work correctly (regression test)
- Unknown role is handled gracefully (not tested currently but should be)

**F. State to observe:** Return values for each role

**G. Mechanism-sensitive:** No — output correctness is sufficient for permission dispatch.

**H. Minimum obligations:**
- Missing role added correctly
- At least one existing role verified as regression test
- Not all roles return identical permissions

---

### 5.12 wrong_condition

**A. Current implicit invariant:** "Rate limiting conditions must use correct operators."

**B. Why insufficient:**
- **Critical flaw at level A:** Only tests `is_rate_limited(5, 5) == True`. Never tests `is_rate_limited(4, 5) == False`. A model returning `True` always passes.
- Level B: Only tests the "should block" case. Never tests "should allow."
- Level C: Only tests "should block." Never tests "should allow."

**C. Degenerate implementations:**
1. `def is_rate_limited(count, limit): return True` — always blocks. Passes level A.
2. `def is_allowed(**kwargs): return False` — always blocks. Passes level B.
3. `def should_allow(**kwargs): return False` — always blocks. Passes level C.

**D. Strong invariant:**
- Level A:
  - ACTION 1: `is_rate_limited(5, 5)` → `True` (at limit, block)
  - ACTION 2: `is_rate_limited(4, 5)` → `False` (below limit, allow)
  - ACTION 3: `is_rate_limited(6, 5)` → `True` (above limit, block)
  - POST_FORBIDDEN: Function returns same value for all inputs
- Level B:
  - ACTION 1: `is_allowed(rpm=50, rate_limit=100, daily=10001, quota=10000)` → `False` (quota exceeded)
  - ACTION 2: `is_allowed(rpm=50, rate_limit=100, daily=9000, quota=10000)` → `True` (both OK)
  - ACTION 3: `is_allowed(rpm=150, rate_limit=100, daily=5000, quota=10000)` → `False` (rate exceeded)
- Level C:
  - ACTION 1: `should_allow(expired=True, exempt=True, over_limit=True)` → `False` (expired blocks)
  - ACTION 2: `should_allow(expired=False, exempt=False, over_limit=False)` → `True` (all clear)
  - ACTION 3: `should_allow(expired=False, exempt=True, over_limit=True)` → `True` (not expired, exempt)

**E. Complement conditions:**
- Both sides of every threshold: at-limit AND below-limit
- Both allow and deny outcomes tested

**F. State to observe:** Boolean return values

**G. Mechanism-sensitive:** No — output correctness is sufficient.

**H. Minimum obligations:**
- At-threshold blocks
- Below-threshold allows
- Both true and false outcomes observed

---

### 5.13 early_return

**A. Current implicit invariant:** "Every payment call must produce a corresponding audit/ledger entry, even on early-return paths."

**B. Why insufficient:**
- Tests only the positive case (all entries present). Doesn't verify entry content.
- `verify_ledger(2)` is a count check — doesn't verify that both entries correspond to the correct payments.

**C. Degenerate implementations:**
1. `def process_payment(amount, tag): _ledger.append({"amount": 0, "tag": "dummy"})` — always appends a dummy entry. Count check passes.

**D. Strong invariant:**
- PRE: `_ledger == []`
- ACTION: `process_payment(100, "normal"); process_payment(0, "zero-amount")`
- POST_REQUIRED: `len(_ledger) == 2`
- POST_REQUIRED (content): Ledger entries contain correct amounts and tags
- POST_REQUIRED (early-return specific): The zero-amount entry exists with `amount == 0`
- COMPLEMENT: Normal payment still processes correctly (not just logged)

**E. Complement conditions:**
- Normal payment works end-to-end
- Early-return path still creates ledger entry with correct content

**F. State to observe:** `_ledger` contents (not just length), payment processing outcome

**G. Mechanism-sensitive:** Partially — the fix must preserve the early-return optimization while adding the audit call.

**H. Minimum obligations:**
- Normal payment logged with correct content
- Early-return payment logged with correct content
- Ledger entry content matches payment parameters

---

### 5.14 index_misalign

**A. Current implicit invariant:** "Parallel data structures must stay synchronized after mutations."

**B. Why insufficient:**
- Well-tested with position-specific assertions. Adequate.
- Could be stronger with: (a) delete operations, (b) boundary positions (first, last, middle).

**C. Degenerate implementations:**
- Hard to fake this one — the multi-step mutation sequence with position checks is good.

**D. Strong invariant:**
- Current tests are already close to STRONG. Main addition: verify that size of both structures matches after every mutation.
- POST_REQUIRED: `len(labels) == len(values)` after every add/remove operation.

**E. Complement conditions:** Delete operation maintains alignment. Already partially covered in level B.

**F. State to observe:** `_labels`, `_values`, `_widths` lengths and contents

**G. Mechanism-sensitive:** No — output correctness is sufficient.

**H. Minimum obligations:** Insert, delete, and verify alignment after each.

---

### 5.15 silent_default

**A. Current implicit invariant:** "Feature flag lookups must return the actual configured value, not silently fall back to a default."

**B. Why insufficient:**
- Only tests the case where the flag IS configured (should return True). Doesn't test what happens when a flag is genuinely not configured (should return default False).
- No complement: doesn't verify that correctly-named flags work without the camelCase → snake_case conversion.

**C. Degenerate implementations:**
1. `def is_enabled(flag): return True` — always returns True. Passes level A.

**D. Strong invariant:**
- ACTION 1: `is_enabled("darkMode")` → `True` (camelCase resolves to dark_mode=True)
- ACTION 2: `is_enabled("dark_mode")` → `True` (exact match also works)
- ACTION 3: `is_enabled("nonExistentFlag")` → `False` (genuinely missing flag returns default)
- POST_FORBIDDEN: Same return value for all inputs

**E. Complement conditions:**
- Exact-match lookup works
- Missing flag returns False (not True)
- Both True and False flag values are tested

**F. State to observe:** Return values, FLAGS dict

**G. Mechanism-sensitive:** Yes for level C — the fix must correct the key translation, not bypass the lookup chain.

**H. Minimum obligations:**
- Translated key works
- Direct key works
- Missing key returns default
- Both True and False configured values tested

---

### 5.16 l3_state_pipeline

**A. Current implicit invariant:** "After process_batch, meta.frozen must be True, stable must contain data, and get_committed_total must return the correct sum."

**B. Why insufficient:**
- Good composite check (frozen, stable, total). Hard to fake because three independent properties must hold.
- But: doesn't test what happens when commit() is removed (should fail with frozen=False). This is actually tested by the buggy code validation, not by the invariant itself.
- No complement: doesn't test that preview mode does NOT freeze.

**C. Degenerate implementations:**
- Harder to fake than most — three independent properties provide good coverage.

**D. Strong invariant:**
- Current tests are ADEQUATE. Main addition: test with different entry values for anti-hardcoding.
- Already done in commit_gate which tests preview must not freeze.

**E. Complement conditions:** Preview does not commit. Already tested in commit_gate.

**F. State to observe:** meta.frozen, stable contents, committed total

**G. Mechanism-sensitive:** YES — commit() and freeze_view() must both exist as separate operations.

**H. Minimum obligations:** Frozen gate set, stable populated, total correct, preview doesn't freeze.

---

### 5.17 cache_invalidation_order

**A. Current implicit invariant:** "After update_record, read_record must return the latest value."

**B. Why insufficient:**
- Structurally identical to stale_cache. Same weaknesses: single key, no mechanism constraint.
- Only tests one key with one update cycle.

**C. Degenerate implementations:** Same as stale_cache — remove cache, bypass cache for tested key.

**D. Strong invariant:**
- Same strengthening as stale_cache: multiple keys, anti-hardcoding with different values.
- POST_REQUIRED: After update("k1", "v1") + read + update("k1", "v2") + read: returns "v2"
- ANTI-HARDCODING: update("k2", "x1") + read + update("k2", "x2") + read: returns "x2"

**E-H:** Mirror stale_cache family.

---

### 5.18 feature_flag_drift

**A. Current implicit invariant:** "checkout with use_new_pricing=True must apply v2 pricing (10% discount)."

**B. Why insufficient:**
- Single test with one item. Hardcoded `total=900` is trivially satisfiable.
- Good that it checks flag cleanup (`flags["new_pricing"] == False` after call).
- No complement: doesn't test that `use_new_pricing=False` gives v1 pricing (total=1000).

**C. Degenerate implementations:**
1. `def checkout(cust, items, use_new_pricing=False): return {"total": 900}` — always returns 900.

**D. Strong invariant:**
- ACTION 1: `checkout(cust, items, use_new_pricing=True)` → total=900
- ACTION 2: `checkout(cust, items, use_new_pricing=False)` → total=1000 (v1 pricing)
- POST_REQUIRED: Flag cleanup after both calls
- ANTI-HARDCODING: Different items give different totals

**E. Complement conditions:** v1 pricing (flag=False) must also work.

**F. State to observe:** Invoice total, _flags state

**G. Mechanism-sensitive:** YES — the flag must propagate through the call chain to `compute_price`.

**H. Minimum obligations:** Flag=True gives discount, Flag=False gives no discount, flag cleaned up.

---

### 5.19 invariant_partial_fail

**A. Current implicit invariant:** "sender.balance + receiver.balance must be conserved after a failed transfer."

**B. Why insufficient:**
- **Critical flaw:** Only tests the failure path. Never tests the success path. A no-op `execute_transfer` that always raises RuntimeError without touching balances conserves balance trivially.
- The conservation check is an output property that doesn't distinguish "nothing happened" from "debit was rolled back."

**C. Degenerate implementations:**
1. `def execute_transfer(s, r, amt): raise RuntimeError("fail")` — no-op, always fails, balance trivially conserved.
2. `def execute_transfer(s, r, amt): pass` — no-op, doesn't transfer, doesn't raise. Would fail because test expects RuntimeError. But variant: `def execute_transfer(s, r, amt): if random.random() < 0.3: raise RuntimeError("fail")` with mocked random → always raises, never transfers.

**D. Strong invariant:**
- PRE: `sender.balance == 100`, `receiver.balance == 0`
- ACTION 1 (happy path, random not mocked): `execute_transfer(sender, receiver, 50)` with `random.random = lambda: 1.0` (above threshold, succeeds)
- POST_REQUIRED (happy path): `sender.balance == 50`, `receiver.balance == 50`, total conserved
- ACTION 2 (failure path, random mocked to trigger failure): `execute_transfer(sender2, receiver2, 50)` with `random.random = lambda: 0.0`
- POST_REQUIRED (failure path): RuntimeError raised, `sender2.balance + receiver2.balance == 100`
- POST_REQUIRED (rollback evidence): `sender2.balance == 100` (debit was rolled back, not "debit never happened")
- POST_FORBIDDEN: No-op detection — in the happy path, balance MUST have changed. `sender.balance != 100` after successful transfer.

**E. Complement conditions:**
- Successful transfer works correctly (money moves)
- Failed transfer rolls back correctly (money conserved)
- The transfer function actually attempts the transfer (not a no-op)

**F. State to observe:** sender.balance, receiver.balance, total, exception type

**G. Mechanism-sensitive:** YES — the fix must implement rollback/compensation, not avoid the transfer.

**H. Minimum obligations:**
- Happy path: transfer succeeds, balances change correctly
- Failure path: transfer fails, balances conserved
- No-op exclusion: successful transfer must change balances

---

### 5.20 async_race_lock

**A. Current implicit invariant:** "run_verified must use process_item (with locking) not quick_increment."

**B. Why insufficient:**
- Actually one of the better tests — checks for `before`/`after` keys as mechanism evidence.
- But: doesn't verify that before < after (monotonic increment evidence).
- Doesn't verify that results are in expected order or that values are correct.

**C. Degenerate implementations:**
- Harder to fake — must produce dicts with `before` and `after` keys with correct count.
- Possible: `def run_verified(items): return {"total": 5, "results": [{"before": 0, "after": 1} for _ in items]}` — hardcoded but has correct structure.

**D. Strong invariant:**
- POST_REQUIRED: `total == 5`, `len(results) == 5`
- POST_REQUIRED (mechanism): Each result has `before` and `after` keys
- POST_REQUIRED (monotonic): `results[i]["after"] == results[i]["before"] + 1`
- POST_REQUIRED (sequential): `results[i]["before"] == results[i-1]["after"]` for i > 0
- ANTI-HARDCODING: Different item count → different total and results count

**E. Complement conditions:** Different input size produces proportionally different results.

**F. State to observe:** results list with before/after values, total

**G. Mechanism-sensitive:** YES — locking is the point.

**H. Minimum obligations:** Correct total, mechanism evidence, monotonic values, anti-hardcoding.

---

### 5.21 hidden_dep_multihop

**A. Current implicit invariant:** "Write-through cache must overwrite on save_user."

**B. Why insufficient:**
- Good test — checks intermediate state (Alice) then final state (Bob).
- Could be stronger: doesn't verify that the cache layer is being used (vs. bypassed).
- Only tests one user ID.

**C. Degenerate implementations:**
1. Remove cache: `def get_display_name(uid): return db._rows[uid]["name"]` — bypasses cache, always reads from DB.

**D. Strong invariant:**
- Current test is close to STRONG. Main addition:
- ANTI-HARDCODING: Second user ID with different sequence
- MECHANISM: `_store` dict should contain the cached value after save

**E. Complement conditions:** Cache is actually populated after save (not just bypassed).

**F. State to observe:** `_store`, `db._rows`, return values

**G. Mechanism-sensitive:** YES — the cache must exist and use write-through (put, not put-if-absent).

**H. Minimum obligations:** Intermediate state correct, final state correct, cache populated, second user tested.

---

### 5.22 config_shadowing

**A. Current implicit invariant:** "Both request and background paths must use timeout=30."

**B. Why insufficient:**
- **Trivially satisfiable.** `def run_system_check(): return {"request": {"timeout": 30}, "background": {"timeout": 30}}` passes.
- Single call, single return value, no state involved.
- No complement: doesn't test what happens with different config values.
- The L3 (counterfactual) nature of this case is completely lost — the test doesn't require reasoning about WHY the timeout is 30.

**C. Degenerate implementations:**
1. Hardcode the return dict.
2. Set both timeouts to 30 without understanding which config layer provides the value.

**D. Strong invariant:**
- ACTION 1: `run_system_check()` → both timeouts == 30
- ANTI-HARDCODING ACTION 2: Modify the config source (if possible) and re-check
- MECHANISM: The fix must be in the correct config layer (defaults.py, not service.py). This is hard to test without structural analysis.
- STRUCTURAL: Functions from all config layers must still exist (`get_defaults`, `get_config`, etc.)
- COMPLEMENT: If config is changed to timeout=60, `run_system_check()` should reflect 60.

**E. Complement conditions:** Different config value produces different output.

**F. State to observe:** Return dict, config layer state

**G. Mechanism-sensitive:** YES — this is an L3 case. The fix must target the structural cause (wrong default in config layer), not just make the output correct.

**H. Minimum obligations:**
- Default value correct
- Structural check: all config layer functions exist
- Anti-hardcoding: different config produces different output

---

### 5.23 Summary: Current vs. Target Strength

| Family | Current Strength | Target Strength | Key Gap |
|---|---|---|---|
| alias_config | STRONG | RESEARCH-GRADE | Add override effectiveness check |
| partial_update | USABLE | STRONG | Add preservation check for unrelated fields |
| stale_cache | STRONG | RESEARCH-GRADE | Add mechanism check, multi-key test |
| lazy_init | USABLE | STRONG | Add default value check, multi-cycle lifecycle |
| mutable_default | STRONG | RESEARCH-GRADE | Add third-call accumulation test, complement for explicit queue |
| effect_order | USABLE | STRONG | Anti-hardcoding with different input values |
| use_before_set | STRONG | RESEARCH-GRADE | Add third call with non-empty different data |
| retry_dup | **WEAK** | RESEARCH-GRADE | Add failure-then-success path, mechanism check |
| partial_rollback | **WEAK** | RESEARCH-GRADE | Add happy path, no-op exclusion |
| temporal_drift | USABLE | STRONG | Anti-hardcoding with second input set |
| missing_branch | USABLE | STRONG | Regression test on existing roles |
| wrong_condition | **WEAK** | STRONG | Add complement (below-threshold allows) |
| early_return | USABLE | STRONG | Verify ledger entry content, not just count |
| index_misalign | STRONG | RESEARCH-GRADE | Size consistency check after each mutation |
| silent_default | USABLE | STRONG | Add missing-flag default, both True/False values |
| l3_state_pipeline | USABLE | STRONG | Anti-hardcoding with different entries |
| cache_invalidation_order | USABLE | STRONG | Multi-key, mechanism check |
| feature_flag_drift | USABLE | STRONG | Test flag=False gives v1 pricing |
| invariant_partial_fail | **WEAK** | RESEARCH-GRADE | Add happy path, no-op exclusion |
| async_race_lock | STRONG | RESEARCH-GRADE | Monotonic value check, anti-hardcoding |
| hidden_dep_multihop | STRONG | RESEARCH-GRADE | Second user ID, cache population check |
| config_shadowing | **WEAK** | STRONG | Anti-hardcoding, structural check |

---

## 6. DEGENERATE PASS CATALOG

### 6.1 No-Op Pass

**Definition:** The model's function does nothing or does nothing relevant. The invariant is satisfied because no state changed from its initial (correct) value.

**Why naive invariants miss it:** Invariants check post-state == expected, but the expected state might equal the pre-state (e.g., balance conserved because nothing was transferred).

**Invariant fields that must rule it out:**
- `forbidden_post_state`: Must require evidence that the action was attempted (state changed and then restored, not state never changed)
- `happy_path_obligations`: Must include a test where the function is expected to produce a state change
- `mechanism_requirements`: Must require the function to execute its core logic

**Affected families:** partial_rollback, invariant_partial_fail, partial_update

### 6.2 Always-Block / Always-Allow

**Definition:** The model's boolean-returning function returns a constant (always True or always False).

**Why naive invariants miss it:** Invariant only tests one branch of the boolean, so a constant that matches that branch passes.

**Invariant fields that must rule it out:**
- `complement_conditions`: Must test both True and False outcomes
- `forbidden_post_state`: "Function must not return same value for all inputs"
- `mutation_sensitivity`: Must include inputs that produce different expected outputs

**Affected families:** wrong_condition, silent_default, missing_branch

### 6.3 Hardcoded Return Value

**Definition:** The model returns a constant matching the expected test output, ignoring all inputs.

**Why naive invariants miss it:** Single-input tests have a single expected output, which a constant matches.

**Invariant fields that must rule it out:**
- `mutation_sensitivity`: Must test with at least two different inputs that produce different expected outputs
- `forbidden_post_state`: "Output must vary with input"

**Affected families:** lost_update, check_then_act, false_fix_deadlock, overdetermination, config_shadowing, feature_flag_drift, temporal_drift

### 6.4 Bypass Cache Entirely

**Definition:** The model removes or ignores the cache layer and reads directly from the source of truth on every call.

**Why naive invariants miss it:** The output is correct (fresh data) regardless of cache state.

**Invariant fields that must rule it out:**
- `mechanism_requirements`: "Cache layer must be consulted during reads"
- `observability_requirements`: "Cache dict must contain entries after reads"
- `preserved_subsystems`: ["cache layer"]

**Affected families:** stale_cache, cache_invalidation_order, hidden_dep_multihop, overdetermination

### 6.5 Bypass Retry Loop Entirely

**Definition:** The model removes the retry loop and performs a single direct call.

**Why naive invariants miss it:** When `fail_first=False`, the first call succeeds, so retry is unnecessary. The test only exercises the success path.

**Invariant fields that must rule it out:**
- `mechanism_requirements`: "Retry loop must exist and execute on failure"
- `trigger`: Must include a failure-then-success action sequence
- `observability_requirements`: "Attempt count must be >= 2 when first attempt fails"

**Affected families:** retry_dup

### 6.6 Wipe-and-Rebuild

**Definition:** The model clears all state and reconstructs it from scratch, rather than surgically fixing the invariant violation.

**Why naive invariants miss it:** The rebuilt state may be correct at the point the test checks.

**Invariant fields that must rule it out:**
- `mechanism_requirements`: "State must be preserved across operations, not rebuilt"
- `forbidden_post_state`: "State prior to the current operation must not be lost"

**Affected families:** stale_cache (clear and re-add), alias_config (recreate DEFAULTS)

### 6.7 Flatten Cross-File Logic

**Definition:** The model collapses a multi-file system into a single flat implementation, eliminating module boundaries.

**Why naive invariants miss it:** The harness assembles all files into one namespace, so flattening is invisible to output-based tests.

**Invariant fields that must rule it out:**
- `mechanism_requirements.boundary_preservation`: Specific functions from specific modules must exist
- `target_entities.structural`: Required function/class names from each original module

**Affected families:** retry_dup_b/c, config_shadowing, overdetermination, hidden_dep_multihop

### 6.8 Satisfy Count but Not Content

**Definition:** The model produces the right number of entries in a collection but with wrong values.

**Why naive invariants miss it:** Tests that only check `len(collection)` miss content errors.

**Invariant fields that must rule it out:**
- `required_post_state.assertions`: Must include content-level checks, not just count checks
- `observability_requirements`: "Collection entries must match expected values"

**Affected families:** effect_order (count without values — now partially fixed), early_return (count-based verify)

### 6.9 Preserve Sum but Skip Transfer

**Definition:** For balance conservation invariants, the model doesn't perform the transfer at all, which trivially conserves the sum.

**Why naive invariants miss it:** `sender + receiver == total` is true if neither balance changed.

**Invariant fields that must rule it out:**
- `happy_path_obligations`: "Successful transfer must change individual balances"
- `forbidden_post_state`: "sender.balance must differ from initial after successful transfer"

**Affected families:** invariant_partial_fail, false_fix_deadlock

### 6.10 Raise Exception Without Semantics

**Definition:** The model raises the expected exception type without performing the operations that should precede it.

**Why naive invariants miss it:** Tests that catch expected exceptions and then check state see the initial state, which may be the "correct" post-failure state.

**Invariant fields that must rule it out:**
- `happy_path_obligations`: Must verify the non-exception path works
- `mechanism_requirements`: "Function must attempt the operation before failing"

**Affected families:** partial_rollback, invariant_partial_fail

### 6.11 Fake Lock Metadata

**Definition:** The model produces data structures that look like locked-execution evidence without actual locking.

**Why naive invariants miss it:** Tests check for structural evidence (e.g., `before`/`after` keys) that can be fabricated.

**Invariant fields that must rule it out:**
- `required_post_state.assertions`: Must check value consistency (monotonic, sequential)
- `mutation_sensitivity`: Different input sizes produce proportionally different results

**Affected families:** async_race_lock

### 6.12 Special-Case Tested Key

**Definition:** The model adds special handling for the exact key used in tests but leaves the general case broken.

**Why naive invariants miss it:** Tests use one or two specific keys, and the special case matches.

**Invariant fields that must rule it out:**
- `mutation_sensitivity`: Must test with keys not present in the buggy code
- `required_post_state`: Must include assertions with at least two different keys

**Affected families:** stale_cache, cache_invalidation_order

### 6.13 Summary Table

| Degenerate Class | Key Detection | Minimum Invariant Field |
|---|---|---|
| No-op | Happy path requires state change | `happy_path_obligations` |
| Always-block/allow | Both outcomes tested | `complement_conditions` |
| Hardcoded return | Multiple inputs, different outputs | `mutation_sensitivity` |
| Bypass cache | Cache state observed | `mechanism_requirements` |
| Bypass retry | Failure-then-success tested | `trigger.action_sequence` |
| Wipe-and-rebuild | Intermediate state preserved | `mechanism_requirements` |
| Flatten modules | Required functions from each module | `target_entities.structural` |
| Count-not-content | Content-level assertions | `required_post_state.assertions` |
| Sum-not-transfer | Individual balances change on success | `happy_path_obligations` |
| Exception-no-semantics | Non-exception path tested | `happy_path_obligations` |
| Fake metadata | Value consistency (monotonic) | `required_post_state.assertions` |
| Special-case key | Multiple keys tested | `mutation_sensitivity` |

---

## 7. MECHANISM VS OUTCOME POLICY

### 7.1 The Core Distinction

**Outcome equivalence:** Two implementations are equivalent if they produce the same outputs for all tested inputs, regardless of internal mechanism.

**Mechanism equivalence:** Two implementations are equivalent only if they use the same subsystems, preserve the same module boundaries, and produce the same intermediate states.

### 7.2 Decision Framework

#### Rule 1: When outcome equivalence is sufficient

Outcome equivalence is sufficient when ALL of the following hold:
- The function is **pure or nearly pure** (no significant side effects beyond the return value)
- The bug is about **logic correctness** (wrong operator, missing branch, incorrect computation)
- No **subsystem preservation** is required (no cache, no retry loop, no lock)
- The function is **single-file, local scope**
- The benchmark claim is about **"can the model produce correct output"**, not "can the model reason about the intended mechanism"

**Families where outcome equivalence is sufficient:**
- `wrong_condition` (a/b/c) — the bug is a boolean logic error
- `missing_branch` (a/b/c) — the bug is a missing dispatch case
- `partial_update` (a/b/c) — the bug is about field synchronization output
- `use_before_set` (a/b/c) — the bug is about stale variable usage
- `index_misalign` (a/b/c) — the bug is about data structure alignment

#### Rule 2: When mechanism constraints are required

Mechanism constraints are required when ANY of the following hold:
- The bug is about **HOW a subsystem operates** (cache invalidation, retry semantics, lock ordering)
- Removing the subsystem would produce correct outputs but would be a **fundamentally different system**
- The benchmark claim is about the model's ability to reason about **the intended mechanism**, not just produce correct outputs
- The case involves **cross-module interaction** where the interaction pattern is part of the specification
- The case involves **temporal ordering** of side effects
- The case involves **failure recovery** where the recovery mechanism matters

**Families where mechanism constraints are required:**
- `stale_cache` (b/c) — cache invalidation mechanism is the point
- `retry_dup` (a/b/c) — retry loop existence and behavior is the point
- `partial_rollback` (a/b/c) — compensation/rollback mechanism is the point
- `invariant_partial_fail` — rollback after partial failure is the point
- `effect_order` (a/b/c) — per-item side-effect timing is the point
- `hidden_dep_multihop` — write-through cache mechanism is the point
- `async_race_lock` — locking mechanism is the point
- `false_fix_deadlock` — lock ordering mechanism is the point
- `config_shadowing` — config layer propagation is the point
- `feature_flag_drift` — flag propagation through call chain is the point
- `lazy_init` — lazy vs. eager initialization mechanism is the point

#### Rule 3: When "works but via different mechanism" should be classified separately

When the invariant is mechanism-sensitive, a model output that produces correct final outputs but uses a different mechanism should be classified as:

**"Behaviorally Correct, Mechanism-Violating" (BCMV)**

This is NOT a pass and NOT a fail. It is a distinct classification that the benchmark must support. It means:
- The model understood WHAT was wrong (output was incorrect)
- The model did NOT understand WHY it was wrong (the intended mechanism)
- The model found a correct solution via a different path

**BCMV examples:**
- Fixing stale cache by removing the cache entirely
- Fixing retry duplication by removing the retry loop
- Fixing rollback by making the function a no-op that raises immediately
- Fixing lock ordering by removing locks and making everything sequential
- Fixing config shadowing by hardcoding the correct values

#### Rule 4: When module boundaries are part of the invariant

Module boundaries are part of the invariant when:
- The case has multiple `code_files` in its definition
- The bug specifically involves cross-module interaction
- The CASE_DOC.md describes the bug in terms of how modules interact

For these cases, the invariant must specify: "Functions X, Y, Z must exist in the fix. The fix must modify function W in module M, not replace the entire system."

**Families where boundaries matter:**
- `retry_dup_b/c` — sender.py / store.py interaction
- `config_shadowing` — defaults.py / env_config.py / service.py interaction
- `overdetermination` — store.py / writer_a.py / writer_b.py interaction
- `hidden_dep_multihop` — db.py / cache.py / service.py interaction

#### Rule 5: Hard policy table

| Family | Outcome Sufficient? | Mechanism Required? | Boundary Required? | BCMV Classification? |
|---|---|---|---|---|
| alias_config | Yes (L1) | No | No | N/A |
| partial_update | Yes | No | No | N/A |
| stale_cache_a | Yes | Borderline | No | Optional |
| stale_cache_b/c | No | Yes | Yes (b/c) | Yes |
| lazy_init | No | Yes | No | Yes |
| mutable_default | Yes | No | No | N/A |
| effect_order | No | Yes (timing) | No | Yes |
| use_before_set | Yes | No | No | N/A |
| retry_dup | No | Yes | Yes (b/c) | Yes |
| partial_rollback | No | Yes (compensation) | No | Yes |
| temporal_drift | Mostly | Partial | No | Optional |
| missing_branch | Yes | No | No | N/A |
| wrong_condition | Yes | No | No | N/A |
| early_return | Mostly | Partial | No | Optional |
| index_misalign | Yes | No | No | N/A |
| silent_default | Mostly | Yes (c) | No | Yes (c) |
| l3_state_pipeline | No | Yes (pipeline) | No | Yes |
| cache_invalidation_order | No | Yes | No | Yes |
| feature_flag_drift | No | Yes (propagation) | No | Yes |
| invariant_partial_fail | No | Yes (rollback) | No | Yes |
| async_race_lock | No | Yes (locking) | No | Yes |
| hidden_dep_multihop | No | Yes (write-through) | Yes | Yes |
| config_shadowing | No | Yes (config layer) | Yes | Yes |
| false_fix_deadlock | No | Yes (lock ordering) | No | Yes |
| overdetermination | No | Yes (cache) | Yes | Yes |
| commit_gate | No | Yes (pipeline) | No | Yes |

---

## 8. INVARIANT TO TEST DERIVATION RULES

### 8.1 Derivation Principles

Tests are **derived from invariants**, not invented independently. Each invariant field maps to specific test obligations:

### 8.2 Mandatory Derivation Rules

#### Rule D1: Happy-Path Test Generation
**If** `minimal_happy_path` is defined, **then** the test MUST include an assertion sequence that exercises the non-error path and verifies the system produces a correct positive result.

*Rationale:* Without happy-path testing, no-op implementations pass.

#### Rule D2: Failure-Path Test Generation
**If** `minimal_failure_path` is defined, **then** the test MUST include an assertion sequence that injects a failure and verifies the system handles it correctly (rollback, compensation, error propagation).

*Rationale:* Without failure-path testing, the recovery mechanism is unvalidated.

#### Rule D3: Complement Condition Generation
**For each** entry in `complement_conditions`, the test MUST include an assertion that verifies the complementary behavior.

*Rationale:* Without complements, always-True/always-False implementations pass.

#### Rule D4: Threshold Bidirectionality
**If** the invariant involves a threshold, boundary, or condition, **then** the test MUST include assertions on BOTH sides of the threshold: one that should pass the condition, one that should fail it.

*Rationale:* Unidirectional threshold tests are trivially satisfiable by constant returns.

#### Rule D5: Multi-Input Anti-Hardcoding
**For each** entry in `mutation_sensitivity`, the test MUST include at least one additional action sequence with different input values that produce different expected outputs.

*Rationale:* Single-input tests are satisfiable by hardcoded returns.

#### Rule D6: Stateful Repeated-Call Test
**If** `statefulness != "stateless"`, **then** the test MUST include a sequence of at least two calls (or call-reset-call) that verifies state isolation or correct state accumulation.

*Rationale:* Single-call tests on stateful systems miss state leakage bugs.

#### Rule D7: Reset-Then-Use Test
**If** `reset_requirements.has_reset == true`, **then** the test MUST include a reset-then-use sequence that verifies the system returns to a known clean state.

*Rationale:* Without reset testing, state contamination between test runs is undetected.

#### Rule D8: Mechanism Evidence Test
**If** `mechanism_requirements.required == true`, **then** the test MUST include at least one assertion that checks for evidence of the mechanism being used (structural existence check, trace data, intermediate state).

*Rationale:* Without mechanism evidence, bypass implementations pass.

#### Rule D9: Forbidden Behavior Test
**For each** entry in `forbidden_post_state.exclusions`, the test SHOULD include a detection check. At minimum, the most critical exclusion must be checked.

*Rationale:* Without forbidden-behavior checks, degenerate implementations pass.

#### Rule D10: Side-Effect Content Test
**If** the invariant involves side effects (logs, notifications, audit entries), **then** the test MUST check both the COUNT and the CONTENT of the side effects. Count-only checks miss content errors.

*Rationale:* Satisfy-count-but-not-content is a documented degenerate pattern.

#### Rule D11: Side-Effect Ordering Test
**If** the invariant involves side-effect timing (per-item vs. per-batch), **then** the test MUST check the VALUES of side effects (not just count), where the values encode timing information (e.g., running totals).

*Rationale:* Count-correct but value-wrong implies wrong timing.

#### Rule D12: Cross-Boundary Test
**If** `boundary_type != "local"` AND the mechanism policy requires boundary preservation, **then** the test MUST include a structural check that key functions from the expected modules exist in the loaded module.

*Rationale:* Without boundary checks, namespace flattening is invisible.

#### Rule D13: Synchronization Preservation Test
**If** the invariant involves updating field A, **then** the test MUST verify that unrelated field B is NOT corrupted by the update.

*Rationale:* Without preservation checks, over-aggressive updates pass.

#### Rule D14: Cache Cycle Test
**If** the invariant involves cache coherence, **then** the test MUST include at least one complete read-write-read cycle that verifies the read after write returns fresh data.

*Rationale:* This is the minimal test for cache staleness.

#### Rule D15: Retry Cycle Test
**If** the invariant involves retry behavior, **then** the test MUST include at least one failure-then-success retry cycle that verifies: (a) the retry happened, (b) the final result is correct, (c) no duplication occurred.

*Rationale:* Success-only retry tests are vacuous.

### 8.3 Derivation Flow

```
Invariant Schema
    │
    ├─ pre_state              → Test setup code (reset, initialize)
    ├─ trigger.action_sequence → Test action sequence
    ├─ required_post_state     → Primary assertions
    ├─ happy_path_obligations  → Happy-path assertions (Rule D1)
    ├─ minimal_failure_path    → Failure-path assertions (Rule D2)
    ├─ complement_conditions   → Complement assertions (Rule D3)
    ├─ forbidden_post_state    → Anti-degenerate assertions (Rule D9)
    ├─ mechanism_requirements  → Structural/trace assertions (Rule D8)
    ├─ mutation_sensitivity    → Additional input scenarios (Rule D5)
    ├─ reset_requirements      → Reset-then-use assertions (Rule D7)
    └─ observability_requirements → Mechanism evidence assertions
```

### 8.4 Test Structure Template

Every derived test function follows this structure:

```
def test_{difficulty}(mod):
    # 1. SETUP (from pre_state.setup_actions)
    # 2. PRE-CHECK (from pre_state.concrete) [optional]
    # 3. PRIMARY ACTION (from trigger.primary_action)
    # 4. PRIMARY ASSERTIONS (from required_post_state.assertions)
    # 5. HAPPY PATH (from happy_path_obligations) [if applicable]
    # 6. COMPLEMENT ACTIONS (from complement_conditions)
    # 7. COMPLEMENT ASSERTIONS
    # 8. ANTI-HARDCODING ACTION (from mutation_sensitivity)
    # 9. ANTI-HARDCODING ASSERTIONS
    # 10. MECHANISM CHECK (from mechanism_requirements) [if applicable]
    # 11. ANTI-DEGENERATE CHECK (from forbidden_post_state) [if applicable]
    # 12. RETURN (pass, reasons)
```

---

## 9. META-VALIDATION OF INVARIANTS

### 9.1 Purpose

Before an invariant is accepted into the benchmark, it must be validated to ensure it is strong enough to serve its purpose. Meta-validation proves that the invariant itself is correct, complete, and resistant to gaming.

### 9.2 Validation Checklist

Every invariant must pass ALL of the following checks:

#### Check M1: Degenerate Candidate Review
For each entry in `degenerate_pass_patterns`:
- Manually (or programmatically) verify that the degenerate implementation WOULD pass the current test
- Verify that the strengthened invariant DOES block the degenerate implementation
- If any degenerate still passes, the invariant is not ready

#### Check M2: Adversarial Counterexample Review
Construct at least one adversarial implementation that:
- Is structurally different from the reference fix
- Satisfies all `required_post_state` assertions
- Attempt to verify that `forbidden_post_state` catches it
- If it slips through, add a new exclusion

#### Check M3: Happy-Path Completeness Review
- If the system has a non-error execution path, verify the invariant tests it
- If the happy-path test is missing, the invariant allows no-op/always-error implementations
- Mark as FAIL if `happy_path_obligations` is empty when a happy path exists

#### Check M4: Complement-Condition Review
- For every boolean/threshold in the invariant, verify both sides are tested
- For every "should block" assertion, verify there is a "should allow" assertion
- Mark as FAIL if any threshold is tested from only one side

#### Check M5: Repeated-Call/State Review
- If `statefulness != "stateless"`, verify the test exercises at least two calls
- Verify that state is properly reset between independent test sequences
- Verify that the mutation test (running test twice) is meaningful

#### Check M6: Cross-Boundary Review
- If `boundary_type != "local"`, verify the test checks for functions from expected modules
- Verify that flattening the modules into one namespace does not silently pass
- This is only required for families flagged as boundary-sensitive in the mechanism policy

#### Check M7: Mechanism-Sensitivity Review
- If the mechanism policy says this family requires mechanism constraints, verify `mechanism_requirements.required == true` and at least one constraint is defined
- If mechanism constraints are absent when required, mark as FAIL

#### Check M8: False-Pass Simulation
- Run the invariant test against at least 3 degenerate implementations:
  1. No-op (function does nothing)
  2. Constant return (function returns hardcoded expected value)
  3. Bypass (function removes the relevant subsystem)
- All 3 must FAIL the test. If any passes, the invariant is too weak.

#### Check M9: Partial-Fix Discrimination Review
- Construct a partial fix that fixes one assertion but not another
- Verify the invariant correctly reports partial pass (some assertions pass, others fail)
- The invariant must support per-assertion reporting, not just all-or-nothing

### 9.3 Validation Severity

| Check | If Failed | Consequence |
|---|---|---|
| M1 (degenerate) | BLOCKING | Invariant cannot be accepted |
| M2 (adversarial) | BLOCKING | Add exclusion, re-validate |
| M3 (happy path) | BLOCKING | Add happy-path obligation |
| M4 (complement) | BLOCKING | Add complement condition |
| M5 (state) | WARNING | Add if stateful, skip if stateless |
| M6 (boundary) | WARNING | Add if multi-file, skip if single-file |
| M7 (mechanism) | BLOCKING for mechanism-sensitive families | Add mechanism constraint |
| M8 (false-pass simulation) | BLOCKING | Strengthen until all 3 degenerates fail |
| M9 (partial-fix) | WARNING | Improve per-assertion reporting |

### 9.4 Automation

The false-pass simulation (M8) should be automated:

```
For each invariant I:
  For each degenerate template D in [no_op, constant_return, bypass]:
    Generate degenerate code for I's case
    Load as module
    Run I's test function against module
    Assert test FAILS
    If test PASSES: flag invariant as WEAK, report which degenerate passed
```

This can be run as part of the validation pipeline (`validate_cases_v2.py`) as a new check: `check_anti_degenerate`.

---

## 10. MIGRATION PLAN

### Phase 0: Foundation (Prerequisites)
**Goal:** Establish the invariant schema and tooling without changing any existing tests.

1. Create `invariant_schema.py` — the dataclass or TypedDict that implements Section 3's schema
2. Create `invariant_registry.py` — a registry that maps `case_id → Invariant` records
3. Create `invariant_validator.py` — implements the meta-validation checklist from Section 9
4. Create `degenerate_templates.py` — a library of degenerate code generators (no-op, constant, bypass) for each family
5. Write unit tests for the schema, registry, and validator

**Files touched:** New files only. No existing file changes.
**Verification:** Schema can represent all 22 families. Validator runs on empty registry without error.

### Phase 1: Audit and Classify
**Goal:** Assign a strength rating to every existing invariant.

1. For each of the 22 families, fill in the invariant schema from the current test code and `cases_v2.json`
2. Run the strength rubric (Section 4) on each invariant
3. Produce a strength report: family → current strength level → gaps
4. Run the false-pass simulation (M8) against all families with the existing tests
5. Record which families have degenerate passes

**Files touched:** New invariant records in registry. No test changes.
**Verification:** Strength report matches the assessment in Section 5.23. False-pass simulation confirms known weak families.

### Phase 2: Fix WEAK Families (Critical)
**Goal:** Bring WEAK families to at least USABLE.

Priority order (by impact on benchmark validity):
1. **retry_dup** — Add `fail_first=True` test path
2. **wrong_condition** — Add complement conditions (below-threshold allows)
3. **invariant_partial_fail** — Add happy-path test (successful transfer)
4. **partial_rollback** — Add happy-path test (successful order)
5. **config_shadowing** — Add anti-hardcoding with different config values
6. **overdetermination** — Add second update with different values

For each:
- Write the new invariant record in the schema
- Derive the new test assertions from the invariant
- Add assertions to the existing test function
- Run false-pass simulation to verify degenerates now fail
- Run the existing test suite to verify no regressions

**Files touched:** `tests_v2/test_retry_dup.py`, `tests_v2/test_wrong_condition.py`, `tests_v2/test_invariant_partial_fail.py`, `tests_v2/test_partial_rollback.py`, `tests_v2/test_config_shadowing.py`, `tests_v2/test_overdetermination.py`
**Verification:** All 6 families pass false-pass simulation. Existing reference fixes still pass. Existing validation pipeline (`validate_cases_v2.py`) still passes.

### Phase 3: Strengthen USABLE Families
**Goal:** Bring USABLE families to STRONG.

For each USABLE family (see Section 5.23):
- Add anti-hardcoding inputs where missing
- Add complement conditions where missing
- Add mechanism evidence checks where policy requires
- Update invariant records

**Files touched:** Most `tests_v2/test_*.py` files.
**Verification:** Strength rubric scores increase. False-pass simulation passes.

### Phase 4: Mechanism Policy Implementation
**Goal:** Implement the mechanism vs. outcome policy from Section 7.

1. Add `mechanism_policy` field to case metadata in `cases_v2.json`
2. For mechanism-sensitive families, add structural/trace checks to tests
3. Add BCMV classification to the evaluation result schema in `exec_eval.py`
4. When a test passes output assertions but fails mechanism assertions, classify as BCMV instead of PASS

**Files touched:** `cases_v2.json`, `exec_eval.py`, mechanism-sensitive test files.
**Verification:** A bypass implementation (cache removed) is classified as BCMV, not PASS.

### Phase 5: Anti-Degenerate Automation
**Goal:** Automate the false-pass simulation as a CI check.

1. Integrate `degenerate_templates.py` with `validate_cases_v2.py`
2. Add a 7th validation check: `check_anti_degenerate`
3. For each case, generate no-op, constant, and bypass degenerates
4. Verify all three fail the test
5. Fail validation if any degenerate passes

**Files touched:** `validate_cases_v2.py`, `degenerate_templates.py`
**Verification:** `python validate_cases_v2.py` now includes anti-degenerate check. Known-weak families from Phase 1 now pass.

### Phase 6: Research-Grade Upgrades
**Goal:** Bring STRONG families to RESEARCH-GRADE where feasible.

- Add per-assertion result reporting (not just boolean pass/fail)
- Add partial-fix detection (some assertions pass, others fail)
- Add monotonic value checks for locking/counter families
- Add cross-boundary structural validation for multi-file families
- Document all invariant decisions in case metadata

**Files touched:** `exec_eval.py` (result schema), select test files.
**Verification:** Evaluation results now include per-assertion breakdown. Partial fixes are classified correctly.

### Phase 7: Documentation and Regression Prevention
**Goal:** Lock down the invariant system against regression.

1. Write invariant specifications into `cases_v2.json` (new `invariant_spec` field)
2. Add invariant strength to case metadata
3. Create a pre-merge check that validates new/modified invariants against the strength rubric
4. Document the mechanism policy in a project-level doc
5. Add the invariant schema to the project's type system

**Files touched:** `cases_v2.json`, new documentation file.
**Verification:** Any test change that weakens an invariant (removes assertions, removes anti-hardcoding) fails pre-merge validation.

### Phase Summary

| Phase | Goal | Risk | Duration Estimate |
|---|---|---|---|
| 0 | Foundation | None (new files only) | Small |
| 1 | Audit | None (read-only analysis) | Small |
| 2 | Fix WEAK | Low (add assertions to existing tests) | Medium |
| 3 | Strengthen USABLE | Low (add assertions) | Medium |
| 4 | Mechanism policy | Medium (changes eval schema) | Medium |
| 5 | Anti-degenerate automation | Low (new validation check) | Small |
| 6 | Research-grade | Medium (changes result schema) | Large |
| 7 | Documentation | None | Small |

### Regression Prevention

After each phase:
1. Run full validation pipeline: `python validate_cases_v2.py`
2. Run full test suite: all reference fixes must still pass
3. Run false-pass simulation: all degenerates must fail
4. Verify strength ratings have not decreased

---

## Appendix A: Files to Create

| File | Purpose | Phase |
|---|---|---|
| `invariant_schema.py` | Dataclass for invariant records | 0 |
| `invariant_registry.py` | Maps case_id → invariant spec | 0 |
| `invariant_validator.py` | Meta-validation checklist | 0 |
| `degenerate_templates.py` | Degenerate code generators per family | 0 |

## Appendix B: Files to Modify

| File | Modification | Phase |
|---|---|---|
| `tests_v2/test_retry_dup.py` | Add fail_first=True test, mechanism check | 2 |
| `tests_v2/test_wrong_condition.py` | Add complement conditions | 2 |
| `tests_v2/test_invariant_partial_fail.py` | Add happy-path test | 2 |
| `tests_v2/test_partial_rollback.py` | Add happy-path test | 2 |
| `tests_v2/test_config_shadowing.py` | Add anti-hardcoding | 2 |
| `tests_v2/test_overdetermination.py` | Add second value test | 2 |
| `tests_v2/test_missing_branch.py` | Add regression on existing roles | 3 |
| `tests_v2/test_feature_flag_drift.py` | Add flag=False test | 3 |
| `tests_v2/test_silent_default.py` | Add missing-flag default test | 3 |
| `tests_v2/test_temporal_drift.py` | Add second input set | 3 |
| `tests_v2/test_early_return.py` | Add content checks to verify() | 3 |
| `tests_v2/test_lazy_init.py` | Add default value check, multi-cycle | 3 |
| `tests_v2/test_async_race_lock.py` | Add monotonic value checks | 3 |
| `tests_v2/test_hidden_dep_multihop.py` | Add second user, cache check | 3 |
| `cases_v2.json` | Add invariant_spec, mechanism_policy | 4, 7 |
| `exec_eval.py` | Add BCMV classification, per-assertion results | 4, 6 |
| `validate_cases_v2.py` | Add anti-degenerate check | 5 |

## Appendix C: Invariant Schema as Flat YAML (Reference)

```yaml
# Example: retry_dup_a strong invariant
invariant_id: "INV-retry_dup_a-001"
family: "retry_dup"
case_id: "retry_dup_a"
bug_pattern: "retry_state_accumulation"
semantic_domain: "retry_idempotency"
scope: "multi_call_sequence"
boundary_type: "local"
temporal_scope: "across_retries"
statefulness: "stateful_across_calls"

target_entities:
  primary: ["_sent"]
  derived: []
  structural: ["retry_send", "get_sent", "send", "reset"]
  side_effects: ["_attempt_count"]

pre_state:
  description: "Empty sent list, zero attempt count"
  concrete: ["len(mod._sent) == 0"]
  setup_actions: ["mod.reset() if hasattr(mod, 'reset') else None", "mod._sent = []"]

trigger:
  description: "Send message with retry on both success and failure-then-success paths"
  action_sequence:
    - call: "mod.retry_send('hello', max_retries=2)"
      args: {fail_first: false}
      expect: "success on first attempt"
    - call: "mod.reset(); mod.retry_send('world', max_retries=3, fail_first=True)"
      args: {fail_first: true}
      expect: "failure on first attempt, success on retry"

required_post_state:
  description: "Exactly one message in _sent after each send"
  assertions:
    - expr: "len(mod.get_sent()) == 1"
      message: "expected 1 message after successful send"
      category: "predicate"
    - expr: "mod.get_sent()[0] == 'hello'"
      message: "wrong message content"
      category: "value"

  happy_path_obligations:
    - expr: "len(mod.get_sent()) == 1 after fail_first=True send"
      message: "retry path must also deliver exactly once"

forbidden_post_state:
  description: "No duplicate messages, no missing messages"
  exclusions:
    - pattern: "bypass_retry"
      detection: "retry loop must exist in function body"
      message: "retry mechanism removed"
    - pattern: "no_op"
      detection: "len(mod.get_sent()) > 0 after any send call"
      message: "send produced no messages"

mechanism_requirements:
  required: true
  constraints:
    - description: "Retry loop must exist and execute on failure"
      check: "mod._attempt_count >= 2 when fail_first=True"
      severity: "mechanism_violation"
  preserved_subsystems: ["retry loop", "send function"]
  forbidden_bypasses: ["remove retry loop entirely"]

degenerate_pass_patterns:
  - name: "no_retry"
    implementation: "def retry_send(msg, max_retries=2): _sent.append(msg)"
    why_it_passes: "fail_first=False means first attempt succeeds"
    detection: "fail_first=True test catches this"

complement_conditions:
  - description: "fail_first=True must still deliver exactly once"
    test: "retry_send('world', max_retries=3, fail_first=True); assert len(get_sent()) == 1"
  - description: "all-failures must not deliver"
    test: "retry_send('fail', max_retries=1, fail_first=True, always_fail=True); assert len(get_sent()) == 0"

minimal_happy_path:
  action: "retry_send('hello', max_retries=2)"
  expected: "len(get_sent()) == 1 and get_sent()[0] == 'hello'"

minimal_failure_path:
  action: "retry_send('world', max_retries=3, fail_first=True)"
  expected: "len(get_sent()) == 1 and get_sent()[0] == 'world'"

mutation_sensitivity:
  - "different message content"
  - "different max_retries"
  - "fail_first=True vs fail_first=False"

reset_requirements:
  has_reset: true
  reset_actions: ["mod.reset()", "mod._sent = []"]
  post_reset_state: ["len(mod._sent) == 0"]

adversarial_dimensions:
  - "remove retry loop"
  - "hardcode return value"
  - "always succeed on first try regardless of fail_first"

semantic_strength_level: "RESEARCH_GRADE"
current_strength_assessment: "WEAK — only tests success path"
strength_gaps:
  - "No failure-then-success test"
  - "No mechanism evidence check"
  - "No anti-bypass structural check"
```
