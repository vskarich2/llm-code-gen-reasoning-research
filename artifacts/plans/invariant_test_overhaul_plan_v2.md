# Invariant Test System Overhaul -- Plan v2

**Task type**: FEATURE (measurement architecture redesign)
**Date**: 2026-03-30
**Status**: AWAITING APPROVAL
**Revision**: v2 -- complete rewrite addressing v1 rejection feedback + integration of invariant formalization audit

---

## Changes from v1

- **Added** Section 1: What This Benchmark Is Actually Measuring
- **Added** Section 3: Mechanism vs Outcome Equivalence Policy (full major section)
- **Added** Section 5: Isolation Model and Its Limits
- **Added** Section 10: Benchmark Versioning Policy
- **Rewritten** Section 2 as "Target Measurement Architecture" (not "test architecture")
- **Rewritten** Section 4: Invariant specification schema massively expanded with semantic fields from invariant formalization audit
- **Rewritten** Section 6: Candidate Evaluation and Benchmark Meta-Validation explicitly separated into two layers
- **Rewritten** Section 8: StructuredVerdict expanded for richer classification
- **Added** ROOT CAUSE 7 to diagnosis
- **Added** 5 new risks to risk section
- **Integrated** the invariant formalization audit's schema (PRE/ACTION/POST_REQUIRED/POST_FORBIDDEN/META model), degenerate pass catalog, family-level strength assessments, and derivation rules throughout

---

## Table of Contents

1. What This Benchmark Is Actually Measuring
2. Diagnosis: Root Causes of Current System Failure
3. Mechanism vs Outcome Equivalence Policy
4. Invariant Specification System
5. Isolation Model and Its Limits
6. Target Measurement Architecture
7. Candidate Evaluation Layer (Layer 1)
8. Benchmark Meta-Validation Layer (Layer 2)
9. Family-Level Policy Assignments
10. Benchmark Versioning Policy
11. Migration Plan
12. Risks

---

## 1. WHAT THIS BENCHMARK IS ACTUALLY MEASURING

### 1.1 This Is Not Software QA

This benchmark is a **measurement system for reasoning-execution behavior** in code-generating language models. It is NOT a software test suite, a regression harness, or a CI gate.

The fundamental question is not "does the code work?" but rather:

> Given a buggy codebase and a task description, can the model (a) identify the correct failure mechanism, (b) produce a fix that addresses that mechanism, (c) preserve the surrounding system's integrity, and (d) distinguish between symptom suppression and root-cause repair?

This distinction matters because ordinary software QA accepts any implementation that produces correct outputs. A benchmark measuring **reasoning about code mechanisms** must additionally measure:

- Whether the fix addresses the stated failure mechanism or a different one
- Whether the fix preserves subsystem boundaries and interfaces
- Whether the fix would generalize beyond the tested inputs
- Whether the fix demonstrates understanding of the causal chain, or merely masks the symptom

### 1.2 What the Invariant Layer Must Support

Because this is a reasoning-execution benchmark, the invariant layer must produce classification signals richer than pass/fail:

| Classification | Definition | What It Reveals About the Model |
|---|---|---|
| **True Fix** | Correct output via correct mechanism | Model understood both what and why |
| **Partial Fix** | Some postconditions met, others not | Model understood part of the problem |
| **Lucky Fix** | Correct output for tested inputs, wrong mechanism | Model got lucky or pattern-matched |
| **Behaviorally Correct, Mechanism-Violating (BCMV)** | Right output, wrong subsystem pathway | Model found a workaround, didn't reason about the mechanism |
| **Degenerate Pass** | Trivially satisfies output checks (no-op, constant, bypass) | Model produced garbage that happens to satisfy weak tests |
| **Reasoning-Correct, Execution-Failed** | Correct reasoning in output, code doesn't compile/run | Model understood the problem but failed at code generation |
| **Cross-Boundary Misunderstanding** | Fix targets wrong file/function | Model misidentified the fault location |
| **State Contamination** | Prior call state leaks into current result | Model introduced a new bug |
| **Trap Fix** | Fix matches the documented "trap" -- addresses symptom, not root cause | Model fell for the misdirection in the task |

The invariant layer must make these distinctions **mechanically derivable** from the test results, not requiring human judgment post-hoc.

### 1.3 What an Invariant Is in This Benchmark

An invariant in this benchmark is a **state-transition specification** with five components:

```
INVARIANT := (PRE, ACTION, POST_REQUIRED, POST_FORBIDDEN, META)
```

This is derived from the invariant formalization audit. Specifically:

- **PRE**: Required system state before the action. Concrete, minimal, reproducible.
- **ACTION**: The trigger -- function call(s), sequence, interleaving, or failure injection.
- **POST_REQUIRED**: Required state after the action. Includes value, predicate, relational, identity, and trace postconditions.
- **POST_FORBIDDEN**: State that MUST NOT exist after the action. This is the anti-degenerate layer.
- **META**: Constraints on HOW the transition happened -- mechanism requirements, boundary preservation, temporal ordering, repeatability.

### 1.4 What an Invariant Is NOT

- It is NOT an expected output for a specific input (that is an outcome check)
- It is NOT a code pattern to match (that is structural coupling)
- It is NOT a single assertion (that is a point check, trivially satisfiable)
- It is NOT a prose description in `cases_v2.json` (that is a label, not a specification)
- It is NOT implicit in the test code (that makes the test the specification, which prevents independent validation)

### 1.5 Semantic Obligations Before Any Test Can Exist

Before a test function can be written for a case, the following must be explicitly specified:

1. **Equivalence policy**: Is behavioral equivalence sufficient, or are mechanism constraints required? (Section 3)
2. **State surface**: What observable state constitutes the system's "before" and "after"? What hidden state (caches, closures, module globals) must be tracked?
3. **Failure surface**: Under what conditions does the bug manifest? What inputs, orderings, or state histories trigger it?
4. **Degenerate exclusions**: What trivially-satisfying implementations must be rejected? (At minimum: no-op, constant return, subsystem bypass)
5. **Complement obligations**: What complementary behavior must also hold? (If the test checks "blocks at limit," it must also check "allows below limit.")
6. **Happy-path obligation**: Does the function need to demonstrably work in the non-buggy case before we test the buggy case?
7. **Mechanism evidence**: If the equivalence policy requires mechanism preservation, what observable evidence proves the mechanism was used?

These are not optional enhancements. They are prerequisites. A test written without them is an outcome check masquerading as an invariant test.

---

## 2. DIAGNOSIS: ROOT CAUSES OF CURRENT SYSTEM FAILURE

### ROOT CAUSE 1: Tests encode expected outputs, not invariants

Current tests follow: `call function -> check return value -> pass/fail`. This is outcome testing. An invariant is a property that must hold across ALL valid states, not a specific output for a specific input.

**Evidence**: `test_wrong_condition.py:test_a` checks `is_rate_limited(5, 5) == True` but never `is_rate_limited(4, 5) == False`. Result: `return True` passes. `test_partial_rollback.py:test_a` checks `inv.available() == 10` after failure but never that a successful order reduces inventory. Result: no-op `place_order` passes.

### ROOT CAUSE 2: No state transition verification

Tests check final state but never verify what state was BEFORE, that state CHANGED correctly, that intermediate states were valid, or that hidden state was properly affected.

**Evidence**: `test_invariant_partial_fail.py` checks `sender.balance + receiver.balance == 100` after forced failure. Initial state (100, 0) trivially satisfies this. Cannot distinguish "rolled back" from "never started."

### ROOT CAUSE 3: No adversarial coverage

Tests use single inputs, call functions once or twice, and check one assertion. Only `lost_update` and `check_then_act` have anti-hardcoding. No family tests repeated calls with accumulation detection, input permutations, or cross-call contamination probes.

### ROOT CAUSE 4: Execution model erases cross-file semantics

Both execution paths flatten multi-file code into a merged namespace. `from cache import cache_get` is never tested -- all names are in the flat namespace. 38 of 51 cases are multi-file, but cross-file invariants are not tested as cross-file interactions.

### ROOT CAUSE 5: No mechanism to detect partial fixes or lucky fixes

Binary pass/fail. No way to detect: fixes that satisfy assertions but violate the stated invariant, fixes that work for tested inputs but fail for others, fixes that work by accident, or partial fixes addressing one of two required changes.

### ROOT CAUSE 6: No state isolation enforcement

Ad-hoc state reset via `if hasattr(mod, "_counter"): mod._counter = 0`. If model renames variable, reset silently fails. If model adds new state, test doesn't know to reset it.

### ROOT CAUSE 7: No explicit semantic equivalence policy

The benchmark cannot distinguish between: intended fix, acceptable alternative implementation, and behaviorally-passing but mechanism-violating workaround. There is no family-level policy for when behavioral equivalence is sufficient versus when mechanism preservation is required. This makes every pass/fail signal ambiguous for research interpretation.

**Evidence**: `stale_cache` -- removing the cache entirely produces correct outputs. `config_shadowing` -- hardcoding 30 in both consumers produces correct outputs. `feature_flag_drift` -- computing the discount directly from the parameter bypasses the flag system but gives the right total. Without a policy, these are indistinguishable from true fixes in the benchmark results.

---

## 3. MECHANISM VS OUTCOME EQUIVALENCE POLICY

### 3.1 The Core Distinction

**Outcome equivalence**: Two implementations are equivalent if they produce the same outputs for all tested inputs, regardless of internal mechanism.

**Mechanism equivalence**: Two implementations are equivalent only if they use the same subsystems, preserve the same module boundaries, and produce the same intermediate states.

For ordinary software: outcome equivalence is sufficient.
For this benchmark: mechanism equivalence is required for families where the bug is ABOUT the mechanism, not just the output.

### 3.2 Equivalence Policy Taxonomy

| Policy | Definition | When to Apply |
|---|---|---|
| `behavior_only` | Any code producing correct outputs passes | Pure logic bugs: wrong operator, missing branch, incorrect computation |
| `behavior_plus_side_effect_preservation` | Correct outputs AND required side effects (audit logs, ledger entries) must be present with correct content | Bugs where side effects are contractual obligations |
| `behavior_plus_side_effect_timing` | Correct outputs AND side effects must occur at the right granularity (per-item, not per-batch) and in the right order | Effect ordering bugs |
| `behavior_plus_lifecycle_preservation` | Correct outputs AND state management lifecycle (reset, configure, get) must work across multiple phases | Lifecycle/init bugs |
| `behavior_plus_subsystem_preservation` | Correct outputs AND the specific subsystem (cache, retry loop, lock) must exist and be exercised | Bugs where the subsystem's behavior IS the point |
| `behavior_plus_compensation_semantics` | Correct outputs AND failure recovery must involve actual compensation (rollback of prior steps), not avoidance of the operation | Rollback/atomicity bugs |
| `behavior_plus_propagation_semantics` | Correct outputs AND a value/flag must flow through the intended call chain, not be hardcoded at the consumer | Configuration/flag propagation bugs |
| `behavior_plus_boundary_preservation` | Correct outputs AND module boundaries must be maintained -- fix must reside in the correct file/function | Cross-module bugs where the interaction pattern is part of the specification |

### 3.3 Decision Procedure

To assign a policy to a family:

1. Read `ground_truth_bug.type` and `bug_pattern_class` from `cases_v2.json`
2. Ask: "Is the bug about WHAT the code produces, or HOW it produces it?"
   - If WHAT: `behavior_only`
   - If HOW: proceed to step 3
3. Ask: "What subsystem/mechanism is broken?"
   - Cache invalidation -> `behavior_plus_subsystem_preservation`
   - Retry loop -> `behavior_plus_subsystem_preservation`
   - Lock ordering -> `behavior_plus_subsystem_preservation`
   - Rollback/compensation -> `behavior_plus_compensation_semantics`
   - Flag/config propagation -> `behavior_plus_propagation_semantics`
   - Side effect timing -> `behavior_plus_side_effect_timing`
   - Lifecycle management -> `behavior_plus_lifecycle_preservation`
4. Ask: "Is the bug specifically about cross-module interaction?"
   - If yes: add `_plus_boundary_preservation` modifier
5. Ask: "Does the fix require side effects (audit, ledger) with specific content?"
   - If yes: add `behavior_plus_side_effect_preservation`

### 3.4 Classification Rules

When the equivalence policy is `behavior_only`:
- Output correct -> PASS
- Output incorrect -> FAIL
- No mechanism judgment needed

When the equivalence policy requires mechanism preservation:
- Output correct AND mechanism preserved -> **TRUE_FIX** (PASS)
- Output correct BUT mechanism violated -> **BCMV** (scored separately, NOT counted as PASS for the benchmark's primary metric)
- Output incorrect -> **FAIL** (regardless of mechanism)
- Output correct on tested inputs but mechanism removed -> **DEGENERATE_PASS** (FAIL)

BCMV is a distinct, trackable classification. It is reported in results. It is NOT silently collapsed into PASS. Researchers decide how to weight it for their specific claims.

### 3.5 Concrete Examples

**Case: `retry_dup_a`**
Policy: `behavior_plus_subsystem_preservation`
- A fix that adds `break` after successful send -> TRUE_FIX
- A fix that removes the retry loop entirely (just `_sent.append(msg)`) -> BCMV (behavior correct on success path because `fail_first=False`, but retry mechanism destroyed)
- A fix that suppresses all sends -> FAIL (behavior incorrect)

**Case: `stale_cache_b`**
Policy: `behavior_plus_subsystem_preservation + boundary_preservation`
- A fix that adds `cache.invalidate(pid)` in `update_product()` -> TRUE_FIX
- A fix that removes the cache module and reads directly from DB -> BCMV (read-after-write correct, but cache subsystem destroyed)
- A fix that only invalidates for key "p1" -> LUCKY_FIX (passes tested input, fails others)

**Case: `config_shadowing`**
Policy: `behavior_plus_propagation_semantics + boundary_preservation`
- A fix that changes `DEFAULTS["timeout"]` from 5 to 30 in `defaults.py` -> TRUE_FIX
- A fix that changes `run_background_job()` to call `get_config()` instead of `get_defaults()` -> TRAP_FIX (passes the test but doesn't fix the structural cause -- the metadata explicitly identifies this as the trap)
- A fix that hardcodes `return {"timeout": 30, "source": "background"}` in `run_background_job()` -> BCMV (output correct but propagation destroyed)

**Case: `wrong_condition_a`**
Policy: `behavior_only`
- A fix that changes `>` to `>=` -> TRUE_FIX
- A fix that rewrites the function with different logic but same behavior -> TRUE_FIX (mechanism doesn't matter for logic bugs)
- `return True` -> DEGENERATE_PASS (FAIL, caught by complement condition)

**Case: `invariant_partial_fail`**
Policy: `behavior_plus_compensation_semantics`
- A fix that wraps the debit in try/except and rolls back on credit failure -> TRUE_FIX
- A fix where `execute_transfer` is a no-op that always raises -> DEGENERATE_PASS (balance trivially conserved because nothing happened)
- A fix that catches the exception and does `sender.balance += amount` to restore -> TRUE_FIX (compensation mechanism present)

**Case: `partial_rollback_c`**
Policy: `behavior_plus_compensation_semantics + side_effect_preservation`
- A fix that adds `release()` and `remove_audit_entry()` in the except block -> TRUE_FIX
- A fix where `place_order` immediately raises without reserving -> DEGENERATE_PASS (inventory never touched, audit never written)
- A fix that releases inventory but forgets audit cleanup -> PARTIAL_FIX

### 3.6 How Mechanism Constraints Are Enforced

Mechanism constraints are not enforced by reading the model's source code (AST analysis). They are enforced by **observable evidence**:

1. **Subsystem existence**: `hasattr(mod, '_cache')` or `hasattr(mod, 'retry_send')` -- structural check that the subsystem's state/functions exist
2. **Subsystem exercise**: After a cache-dependent read, `mod._cache` contains entries (the cache was consulted, not bypassed)
3. **Mechanism traces**: `mod._attempt_count >= 2` when `fail_first=True` (retry loop executed more than once)
4. **Side-effect ordering**: Snapshot values are running totals `[10, 30, 60]` not final totals `[60, 60, 60]` (proves per-item timing)
5. **Happy-path state change**: `sender.balance != initial_balance` after successful transfer (proves the function actually did something)
6. **Anti-hardcoding**: Different inputs produce different outputs (proves the function processes its arguments)

These are all behavioral observations, not code inspection. They work within the existing execution harness.

---

## 4. INVARIANT SPECIFICATION SYSTEM

### 4.1 Full Schema

This schema integrates the invariant formalization audit's `(PRE, ACTION, POST_REQUIRED, POST_FORBIDDEN, META)` model with the equivalence policy from Section 3 and the semantic fields identified as missing in the v1 rejection.

```yaml
invariant:
  # --- IDENTITY ---
  invariant_id: string              # "INV-{case_id}-{seq}"
  family: string
  case_id: string
  bug_pattern: string               # From cases_v2.json ground_truth_bug.type
  semantic_domain: string           # From taxonomy: identity_aliasing, cache_coherence, etc.

  # --- EQUIVALENCE POLICY ---
  equivalence_policy: enum          # From Section 3.2 taxonomy
  acceptable_mechanisms: list[str]  # Mechanisms that count as TRUE_FIX
                                    # e.g., ["cache invalidation via invalidate()",
                                    #        "cache invalidation via delete+re-set"]
  forbidden_mechanisms: list[str]   # Mechanisms that produce BCMV classification
                                    # e.g., ["remove cache entirely", "bypass cache on read"]
  classification_if_behavior_passes_but_mechanism_fails: enum
                                    # "BCMV" | "TRAP_FIX" | "LUCKY_FIX"

  # --- SCOPE ---
  scope: enum                       # single_call | multi_call_sequence | interleaved | failure_injection
  boundary_type: enum               # local | cross_function | cross_module | cross_layer
  temporal_scope: string            # per_call | across_calls | after_reset | across_retries
  statefulness: enum                # stateless | stateful_within_call | stateful_across_calls

  # --- STATE SURFACES ---
  observational_surface: list[str]  # State visible through the public API
                                    # e.g., ["get_product() return value", "available() return value"]
  hidden_state_surface: list[str]   # Internal state that must be tracked for mechanism evidence
                                    # e.g., ["_cache dict contents", "_attempt_count value"]
  required_unchanged_state: list[str]  # State that MUST NOT change during the action
                                       # e.g., ["DEFAULTS dict", "unrelated profile fields"]

  # --- STATE TRANSITION (from invariant formalization audit) ---
  pre_state:
    description: string
    concrete: list[str]             # Python expressions: ["len(mod._sent) == 0"]
    setup_actions: list[str]        # ["mod.reset()", "mod._sent = []"]

  trigger:
    description: string
    primary_action: string
    action_sequence: list[dict]     # [{call: str, args: dict, expect: str}]
    failure_injection: dict|null    # {target: str, mock: str, restore: str}

  required_post_state:
    description: string
    assertions: list[dict]          # [{expr: str, message: str, category: str}]
                                    # category: value | predicate | relational | identity | trace
    happy_path_obligations: list[dict]  # [{expr: str, message: str}]

  forbidden_post_state:
    description: string
    exclusions: list[dict]          # [{pattern: str, detection: str, message: str}]
                                    # pattern: no_op | always_block | always_allow | hardcoded |
                                    #          bypass_cache | bypass_retry | collapse_modules | etc.

  # --- MECHANISM (from invariant formalization audit) ---
  mechanism_requirements:
    required: boolean
    constraints: list[dict]         # [{description: str, check: str, severity: str}]
    preserved_subsystems: list[str]
    forbidden_bypasses: list[str]

  mechanism_evidence_requirements: list[str]
                                    # Observable evidence that mechanism was used
                                    # e.g., ["_cache contains entry after read",
                                    #        "_attempt_count >= 2 when fail_first=True"]

  # --- PARTIAL / LUCKY FIX CRITERIA ---
  partial_fix_criteria: list[dict]  # [{description: str, condition: str}]
                                    # e.g., [{desc: "fixes commit but not freeze_view",
                                    #         condition: "frozen==True but consistent==False"}]
  lucky_fix_criteria: list[str]     # Conditions that suggest luck rather than understanding
                                    # e.g., ["passes with test input but fails with different values"]

  # --- ANTI-DEGENERATE (from invariant formalization audit) ---
  degenerate_pass_patterns: list[dict]
                                    # [{name: str, implementation: str,
                                    #   why_it_passes: str, detection: str}]

  # --- COMPLEMENT, MUTATION, ADVERSARIAL ---
  complement_conditions: list[dict] # [{description: str, test: str}]
  minimal_happy_path: dict          # {action: str, expected: str}
  minimal_failure_path: dict|null   # {action: str, expected: str}
  mutation_sensitivity: list[str]   # ["different input values", "repeated calls", etc.]
  adversarial_dimensions: list[str] # ["hardcode return", "remove retry", "bypass cache"]

  # --- ENVIRONMENT ---
  environment_assumptions: list[str]  # ["random.random is patchable", "no filesystem deps"]
  nondeterminism_controls: list[dict] # [{source: str, control: str}]
                                      # e.g., [{source: "random.random", control: "mock to lambda: 0.0"}]

  # --- RESET ---
  reset_requirements:
    has_reset: boolean
    reset_actions: list[str]
    post_reset_state: list[str]

  # --- STRENGTH ---
  semantic_strength_level: enum     # INVALID | WEAK | USABLE | STRONG | RESEARCH_GRADE
  current_strength_assessment: string
  strength_gaps: list[str]
```

### 4.2 Schema Constraints (Hard Rules)

These constraints are derived from the invariant formalization audit's Section 3.2:

1. Every invariant MUST have at least one entry in `degenerate_pass_patterns`
2. Every stateful invariant MUST define `reset_requirements`
3. Every failure-injection invariant MUST define both `minimal_happy_path` and `minimal_failure_path`
4. Every mechanism-sensitive invariant MUST have `mechanism_requirements.required == true` with at least one constraint
5. Every invariant MUST have at least one `complement_condition`
6. `required_post_state.assertions` MUST contain at least two assertions on different state dimensions
7. `forbidden_post_state.exclusions` MUST contain at least one entry
8. `equivalence_policy` MUST be set (no default)
9. If `equivalence_policy` is not `behavior_only`, then `acceptable_mechanisms` and `forbidden_mechanisms` MUST be non-empty

### 4.3 Invariant Strength Criteria

The strength rubric from the invariant formalization audit applies:

| Level | Criteria |
|---|---|
| **INVALID** | Can be satisfied by no-op, constant return, or exception-only implementation |
| **WEAK** | Can be satisfied by always-True/False; checks only one side of a threshold; no happy-path test; no degenerate exclusion |
| **USABLE** | 2+ assertions, cannot be satisfied by constants, has happy/failure paths and one degenerate exclusion; BUT missing mechanism constraint when needed, or missing temporal check when timing matters |
| **STRONG** | All USABLE criteria plus mechanism constraints where required, 2+ input scenarios, repeated-call test when stateful, structural preservation check |
| **RESEARCH_GRADE** | All STRONG criteria plus explicit degenerate catalog tested against, mechanism traces for HOW, cross-boundary validation, supports TRUE_FIX/PARTIAL/LUCKY/BCMV classification |

### 4.4 Automatic Disqualifiers

An invariant MUST fail review if ANY of these are true (from invariant formalization audit Section 4.3):

1. `def f(): return <constant>` satisfies all assertions
2. `def f(): raise Exception()` satisfies all assertions
3. `def f(): pass` satisfies all assertions
4. A function ignoring all arguments satisfies all assertions
5. Removing the target subsystem satisfies all assertions
6. Flattening multi-file logic into one function satisfies all assertions

---

## 5. ISOLATION MODEL AND ITS LIMITS

### 5.1 What Fresh-Module Isolation Provides

The IsolationEngine (creating a fresh module per test invocation) provides:

**Module-state isolation**: Each test starts with module-level variables at their initialization values. No leakage of `_counter`, `_cache`, `_sent` between test invocations. This eliminates ROOT CAUSE 6 (ad-hoc state reset).

**Name collision avoidance**: Each loaded module gets a unique `sys.modules` key. Prior test runs' modules do not shadow current ones.

**Import-time re-execution**: Module-level code (variable initialization, class definitions) runs fresh each time. Eagerly-captured closures, import-time side effects, and singleton patterns are re-initialized.

### 5.2 What Fresh-Module Isolation Does NOT Provide

**Randomness control**: `random.random()`, `random.choice()`, etc. are process-global. A test that patches `random.random` in one invocation must restore it afterward. Fresh module loading does not reset the global RNG state.
- **Control strategy**: Every invariant that uses randomness MUST declare it in `nondeterminism_controls` with explicit mock/restore actions. The test harness enforces mock restoration in a `finally` block. This is already done correctly for `invariant_partial_fail` (patches `random.random`).

**Clock/time control**: `time.time()`, `time.monotonic()`, `datetime.now()` are process-global. Fresh imports do not reset the clock.
- **Control strategy**: No current cases depend on wall-clock time. If future cases do, they must declare `nondeterminism_controls` with mock strategies. For now: **out of scope**.

**Environment variable isolation**: `os.environ` is process-global. Fresh imports do not sandbox environment variables.
- **Control strategy**: No current cases read environment variables at test time (the `silent_default_c` case has `_ENV` as a module-level dict, not `os.environ`). For now: **out of scope**. If future cases use `os.environ`, they must be subprocess-isolated.

**Filesystem isolation**: Temporary files created by one test persist for subsequent tests in the same process.
- **Control strategy**: The disk-backed execution path (`exec_canonical.py`) already creates temp directories and cleans them up. All test execution should go through this path. Module-level execution via `exec()` should be deprecated for production scoring.

**Subprocess state**: If model code spawns subprocesses, their state is not controlled.
- **Control strategy**: No current cases spawn subprocesses. The harness itself spawns subprocesses for disk-backed execution, but these are fresh per invocation. **Out of scope** for model-generated code.

**Import-time hidden side effects**: If module A's import triggers a side effect in module B (e.g., registering a handler), and module B is imported in a different order, behavior may differ.
- **Control strategy**: The merged-namespace approach eliminates cross-module imports but also eliminates cross-module import testing. The isolated execution mode (Section 6) preserves import order. This is a known limitation of the merged-namespace path.

**Global singletons outside the module**: If model code uses `logging.getLogger()` or other process-wide singletons, fresh module loading does not reset them.
- **Control strategy**: No current test invariants depend on logger state. **Out of scope**.

**OS-level nondeterminism**: Thread scheduling, file descriptor ordering, network timing.
- **Control strategy**: The benchmark runs single-process, single-threaded, no network. **Not applicable**.

### 5.3 Summary: Isolation Guarantees

| Isolation Type | Provided? | Notes |
|---|---|---|
| Module-level variable reset | **YES** | Fresh import per invocation |
| sys.modules namespace | **YES** | Unique module names |
| Import-time code re-execution | **YES** | Module-level code runs fresh |
| RNG state | **NO** | Must mock/restore explicitly per invariant |
| Clock/time | **NO** | Out of scope (no current cases) |
| Environment variables | **NO** | Out of scope (no current cases) |
| Filesystem | **PARTIAL** | Disk-backed path cleans up; exec() path does not |
| Subprocess state | **NO** | Out of scope (no current cases) |
| Cross-module import order | **PARTIAL** | Merged namespace: no. Isolated mode: yes |
| Process-wide singletons | **NO** | Out of scope (no current cases) |

The plan does NOT claim that fresh-module isolation solves all state problems. It solves the most impactful one (module-level variable contamination, ROOT CAUSE 6) and explicitly documents what it does not solve.

---

## 6. TARGET MEASUREMENT ARCHITECTURE

### 6.1 Two-Layer Separation

The architecture is split into two strictly separated layers:

**Layer 1: Candidate Evaluation** -- Runs at benchmark time against model-generated code. Produces a `MeasurementVerdict` for each case. This is the scoring path.

**Layer 2: Benchmark Meta-Validation** -- Runs during benchmark development against known inputs (reference fixes, buggy originals, synthetic degenerates, trap fixes). Proves that the benchmark itself is correct. This is the calibration path.

These layers share invariant specifications but have different execution contexts, different inputs, and different success criteria. They must NEVER be mixed.

### 6.2 Layer 1: Candidate Evaluation Components

```
cases_v2.json + INVARIANT_SPECS/*.yaml
    |
    v
IsolationEngine                     (fresh module per invocation)
    |
    v
CandidateEvaluator
    |
    +-- Phase A: PRECONDITION       (verify initial state)
    +-- Phase B: HAPPY_PATH         (verify function works correctly)
    +-- Phase C: INVARIANT          (verify the specific invariant holds)
    +-- Phase D: ADVERSARIAL        (boundary, contamination, anti-hardcoding)
    +-- Phase E: MECHANISM          (mechanism evidence, when policy requires)
    |
    v
MeasurementVerdict                  (structured classification, not just bool)
```

### 6.3 Layer 2: Benchmark Meta-Validation Components

```
INVARIANT_SPECS/*.yaml + reference_fixes/ + code_snippets_v2/ + degenerate_templates/
    |
    v
BenchmarkValidator
    |
    +-- META-1: Reference fixes pass all phases
    +-- META-2: Buggy originals fail invariant phase
    +-- META-3: Degenerate implementations fail (no-op, constant, bypass)
    +-- META-4: Trap fixes are classified correctly (not TRUE_FIX)
    +-- META-5: Spec completeness (all schema constraints satisfied)
    +-- META-6: Anti-cheat coverage (2+ input sets per case)
    +-- META-7: Strength rubric (every invariant >= USABLE)
    +-- META-8: Equivalence policy consistency
    |
    v
ValidationReport                    (per-invariant pass/fail with evidence)
```

### 6.4 Data Flow: Candidate Evaluation (Layer 1)

```
1. Load case from cases_v2.json
2. Load invariant spec from INVARIANT_SPECS/{family}.yaml
3. Load equivalence policy from spec
4. IsolationEngine creates FRESH module from model code
5. StateTracker snapshots initial state
6. CandidateEvaluator executes phases A-E:
   Phase A: PRECONDITION -- verify initial state per spec.pre_state.concrete
   Phase B: HAPPY_PATH -- execute spec.minimal_happy_path, verify
   Phase C: INVARIANT -- execute spec.trigger, verify spec.required_post_state
   Phase D: ADVERSARIAL -- execute complement_conditions + mutation_sensitivity inputs
   Phase E: MECHANISM -- if equivalence_policy requires, check mechanism_evidence_requirements
7. StateTracker snapshots final state, verifies required_unchanged_state
8. Classify result:
   - All phases pass + mechanism pass (or not required) -> TRUE_FIX
   - All behavior phases pass but mechanism fails -> BCMV
   - Some behavior phases pass, others fail -> PARTIAL_FIX
   - Behavior passes only for standard inputs, fails for anti-hardcoding -> LUCKY_FIX
   - Degenerate pattern detected (forbidden_post_state triggered) -> DEGENERATE_PASS (FAIL)
   - Behavior fails -> FAIL
9. Assemble MeasurementVerdict
```

### 6.5 Data Flow: Benchmark Meta-Validation (Layer 2)

```
1. For each case:
   a. Load reference fix -> run Layer 1 evaluation -> assert TRUE_FIX
   b. Load buggy original -> run Layer 1 evaluation -> assert FAIL at Phase C
   c. For each degenerate template (no-op, constant, bypass):
      Generate degenerate code -> run Layer 1 evaluation -> assert FAIL or DEGENERATE_PASS
   d. If case has declared trap fix:
      Generate trap fix code -> run Layer 1 evaluation -> assert TRAP_FIX or BCMV (not TRUE_FIX)
   e. Validate invariant spec against schema constraints (Section 4.2)
   f. Validate invariant strength >= USABLE (Section 4.3)
   g. Validate equivalence policy is assigned and consistent (Section 3)
```

---

## 7. CANDIDATE EVALUATION LAYER (Layer 1) -- Detail

### 7.1 MeasurementVerdict Schema

```python
@dataclass
class PhaseResult:
    phase: str                    # "precondition" | "happy_path" | "invariant" | "adversarial" | "mechanism"
    invariant_id: str             # which invariant this checks
    passed: bool
    assertions_total: int
    assertions_passed: int
    failure_details: list[str]    # specific assertion failures with evidence
    state_diff: dict | None       # what state changed during this phase

@dataclass
class MeasurementVerdict:
    case_id: str
    variant: str

    # --- Primary classification ---
    classification: str           # TRUE_FIX | PARTIAL_FIX | LUCKY_FIX | BCMV |
                                  # DEGENERATE_PASS | TRAP_FIX | FAIL |
                                  # CRASH | PARSE_FAILURE

    # --- Behavioral dimension ---
    behavior_pass: bool           # Did all output-level assertions pass?

    # --- Mechanism dimension ---
    mechanism_pass: bool | None   # Did mechanism evidence checks pass? None if not required.
    mechanism_evidence: list[str] # What evidence was found/missing

    # --- Phase detail ---
    phases: list[PhaseResult]     # Per-phase results

    # --- Degenerate detection ---
    degenerate_pattern_detected: str | None  # Which pattern, if any

    # --- State ---
    state_isolation_verified: bool
    unchanged_state_violations: list[str]  # required_unchanged_state that was modified

    # --- Anti-cheat ---
    anti_hardcoding_passed: bool  # Did varying inputs produce correct varying outputs?

    # --- Partial fix detail ---
    invariants_satisfied: list[str]   # Which invariant IDs passed
    invariants_violated: list[str]    # Which invariant IDs failed

    # --- Metadata ---
    equivalence_policy: str       # Which policy was applied
    execution_model: str          # "merged" | "isolated" | "subprocess"
```

### 7.2 Classification Decision Procedure

```
1. Did the code parse/compile/load?
   NO -> CRASH or PARSE_FAILURE

2. Did Phase B (HAPPY_PATH) pass?
   NO -> Check if it's a no-op/constant -> DEGENERATE_PASS (if detected) or FAIL

3. Did Phase C (INVARIANT) pass?
   NO -> Check which assertions failed -> PARTIAL_FIX (if some passed) or FAIL

4. Did Phase D (ADVERSARIAL) pass?
   NO -> Check if standard input passed but variant failed -> LUCKY_FIX
   NO -> Check if complement failed -> FAIL (one-sided implementation)

5. Is mechanism required by equivalence_policy?
   YES -> Did Phase E (MECHANISM) pass?
          NO -> BCMV
          YES -> proceed
   NO -> proceed

6. Was a forbidden_post_state pattern detected?
   YES -> DEGENERATE_PASS

7. Does the fix match a declared trap_fix_detection pattern?
   YES -> TRAP_FIX

8. All checks pass -> TRUE_FIX
```

### 7.3 Phase Specifications

**Phase A: PRECONDITION**
- Source: `invariant.pre_state.concrete`
- Purpose: Verify the module loaded correctly and initial state matches expectations
- On failure: CRASH (module didn't load correctly) -- do not proceed to subsequent phases

**Phase B: HAPPY_PATH**
- Source: `invariant.minimal_happy_path` + `invariant.required_post_state.happy_path_obligations`
- Purpose: Verify the function works correctly for normal, non-edge-case inputs
- On failure: No-op and constant implementations fail here. This is the primary defense against degenerate passes.

**Phase C: INVARIANT**
- Source: `invariant.trigger` + `invariant.required_post_state.assertions`
- Purpose: Verify the specific invariant that the bug violates
- On failure: The model's fix does not address the bug

**Phase D: ADVERSARIAL**
- Source: `invariant.complement_conditions` + `invariant.mutation_sensitivity`
- Purpose: Verify the fix is not one-sided, hardcoded, or input-specific
- On failure: Lucky fix, one-sided implementation, or hardcoded output

**Phase E: MECHANISM** (conditional on equivalence_policy)
- Source: `invariant.mechanism_requirements` + `invariant.mechanism_evidence_requirements`
- Purpose: Verify the fix uses the intended mechanism, not a bypass
- On failure: BCMV -- behavior correct but mechanism wrong

---

## 8. BENCHMARK META-VALIDATION LAYER (Layer 2) -- Detail

### 8.1 META-1: Reference Fix Validation

```
For each case in cases_v2.json:
    Load reference fix from reference_fixes/{case_id}.py
    Run Layer 1 evaluation
    Assert: classification == TRUE_FIX
    Assert: ALL phases pass
    If reference fix fails: THE INVARIANT IS WRONG, not the reference fix
```

### 8.2 META-2: Buggy Code Validation

```
For each case in cases_v2.json:
    Load buggy code from code_snippets_v2/{family}/
    Run Layer 1 evaluation
    Assert: Phase C (INVARIANT) fails
    Assert: Phase B (HAPPY_PATH) MAY pass (buggy code can work for normal inputs)
    If buggy code passes Phase C: THE INVARIANT IS TOO WEAK
```

### 8.3 META-3: Degenerate Pass Validation

```
For each case:
    For each degenerate_pass_pattern in the invariant spec:
        Generate degenerate code from pattern
        Run Layer 1 evaluation
        Assert: classification != TRUE_FIX
        Assert: at least one of Phase B, C, D, or E fails
        If degenerate passes all phases: THE INVARIANT IS TOO WEAK, add exclusion
```

Three mandatory degenerate templates for every case:
1. **No-op**: Function body is `pass` or `raise <expected_exception>`
2. **Constant return**: Function returns hardcoded expected value from the standard test
3. **Subsystem bypass**: If mechanism-sensitive, remove the target subsystem

### 8.4 META-4: Trap Fix Validation

```
For each case with a declared "trap" in cases_v2.json:
    Construct the trap fix
    Run Layer 1 evaluation
    Assert: classification is TRAP_FIX or BCMV or PARTIAL_FIX (NOT TRUE_FIX)
    If trap fix classifies as TRUE_FIX: THE INVARIANT DOES NOT DETECT THE TRAP
```

### 8.5 META-5: Spec Completeness

```
For each invariant spec:
    Assert: all schema constraints from Section 4.2 are satisfied
    Assert: equivalence_policy is set
    Assert: degenerate_pass_patterns is non-empty
    Assert: complement_conditions is non-empty
    Assert: required_post_state.assertions has >= 2 entries
    Assert: forbidden_post_state.exclusions has >= 1 entry
    If mechanism_requirements.required and equivalence_policy != behavior_only:
        Assert: mechanism_evidence_requirements is non-empty
        Assert: acceptable_mechanisms is non-empty
        Assert: forbidden_mechanisms is non-empty
```

### 8.6 META-6: Anti-Cheat Coverage

```
For each case:
    Assert: mutation_sensitivity has >= 1 entry
    Assert: the test exercises at least 2 distinct input sets that produce different expected outputs
```

### 8.7 META-7: Strength Validation

```
For each invariant spec:
    Compute strength score per rubric (Section 4.3)
    Assert: strength >= USABLE
    If WEAK or INVALID: BLOCKING -- invariant must be strengthened before benchmark results are trusted
```

### 8.8 META-8: Equivalence Policy Consistency

```
For each family:
    Assert: equivalence_policy matches the assignment in Section 9
    If mechanism_requirements.required == true:
        Assert: equivalence_policy is not "behavior_only"
    If equivalence_policy is "behavior_only":
        Assert: mechanism_requirements.required == false
```

---

## 9. FAMILY-LEVEL POLICY ASSIGNMENTS

### 9.1 Complete Assignment Table

| Family | Equivalence Policy | Mechanism Sensitive? | Boundary Sensitive? | Current Strength | Target Strength | Critical Gap |
|---|---|---|---|---|---|---|
| alias_config | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Add override effectiveness check |
| partial_update | `behavior_only` | No | No | USABLE | STRONG | Add preservation check for unrelated fields; test_c must check cached_greeting |
| stale_cache (a) | `behavior_only` | Borderline | No | STRONG | RESEARCH_GRADE | Add anti-hardcoding with second key |
| stale_cache (b,c) | `behavior_plus_subsystem_preservation` | Yes | Yes | STRONG | RESEARCH_GRADE | Add mechanism check (cache consulted), multi-key |
| lazy_init | `behavior_plus_lifecycle_preservation` | Yes | No | USABLE | STRONG | Add default-before-configure, multi-cycle lifecycle |
| mutable_default | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Add 3rd-call accumulation, complement for explicit queue |
| effect_order | `behavior_plus_side_effect_timing` | Yes (timing) | No | USABLE | STRONG | Add anti-hardcoding with different input values |
| use_before_set | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Add 3rd call with non-empty different data |
| retry_dup | `behavior_plus_subsystem_preservation` | Yes | Yes (b,c) | **WEAK** | RESEARCH_GRADE | Add fail_first=True test, mechanism check |
| partial_rollback | `behavior_plus_compensation_semantics` | Yes | No | **WEAK** | RESEARCH_GRADE | Add happy path, no-op exclusion |
| temporal_drift | `behavior_plus_side_effect_preservation` | Partial | No | USABLE | STRONG | Add anti-hardcoding, verify normalization preserved |
| missing_branch | `behavior_only` | No | No | USABLE | STRONG | Add regression test on existing roles |
| wrong_condition | `behavior_only` | No | No | **WEAK** | STRONG | Add complement (below-threshold allows) |
| early_return | `behavior_plus_side_effect_preservation` | Partial | No | USABLE | STRONG | Verify ledger content, not just count |
| index_misalign | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Size consistency check after each mutation |
| silent_default | `behavior_only` (a,b); `behavior_plus_propagation_semantics` (c) | Yes (c) | No | USABLE | STRONG | Add missing-flag default, both True/False values |
| l3_state_pipeline | `behavior_plus_subsystem_preservation` | Yes | No | USABLE | STRONG | Anti-hardcoding with different entries |
| cache_invalidation_order | `behavior_plus_subsystem_preservation` | Yes | No | USABLE | STRONG | Multi-key, test safe_update path |
| feature_flag_drift | `behavior_plus_propagation_semantics` | Yes | No | USABLE | STRONG | Test flag=False (v1 pricing), vary inputs |
| invariant_partial_fail | `behavior_plus_compensation_semantics` | Yes | No | **WEAK** | RESEARCH_GRADE | Add happy path, no-op exclusion |
| async_race_lock | `behavior_plus_subsystem_preservation` | Yes | No | STRONG | RESEARCH_GRADE | Monotonic value checks, anti-hardcoding |
| hidden_dep_multihop | `behavior_plus_subsystem_preservation` | Yes | Yes | STRONG | RESEARCH_GRADE | Second user, cache population check |
| config_shadowing | `behavior_plus_propagation_semantics` | Yes | Yes | **WEAK** | STRONG | Anti-hardcoding, structural layer check |
| commit_gate | `behavior_plus_subsystem_preservation` | Yes | No | USABLE | STRONG | Anti-hardcoding with different entries |
| overdetermination | `behavior_plus_subsystem_preservation` | Yes | Yes | USABLE | STRONG | Third update, version check |
| lost_update | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Third anti-hardcoding input |
| check_then_act | `behavior_only` | No | No | STRONG | RESEARCH_GRADE | Third anti-hardcoding input |
| ordering_dependency | `behavior_only` | No | No | USABLE | STRONG | Multi-item before-init test |
| false_fix_deadlock | `behavior_plus_subsystem_preservation` | Yes | No | STRONG | RESEARCH_GRADE | Verify specific account values after transfer |

### 9.2 Policy Justifications for Non-Obvious Assignments

**alias_config = behavior_only**: The bug is about Python copy semantics. Any implementation that returns independent dicts is correct. The mechanism (`.copy()` vs `dict()` vs `{**DEFAULTS}`) doesn't matter.

**stale_cache_a = behavior_only but stale_cache_b/c = subsystem_preservation**: Level A is a single-file case where the cache is internal. Bypassing it is equivalent to fixing it. Levels B/C are cross-file cases where the cache is a separate module with defined interfaces. Removing it destroys the architecture.

**effect_order = side_effect_timing**: The invariant is not just "3 snapshots exist" but "snapshots happened after each item's counter increment." Timing is the mechanism. A batch-level snapshot at the end with pre-computed values violates the invariant even if values match.

**retry_dup = subsystem_preservation**: The retry loop IS the point of the case. Removing it is not a fix, it's a bypass. The benchmark needs to distinguish "fixed the break-on-success bug in the retry loop" from "removed the retry loop."

**wrong_condition = behavior_only**: The bug is a boolean logic error (`>` vs `>=`, `or` vs `and`). Any implementation that produces correct boolean outputs for all inputs is correct. There is no subsystem to preserve.

**config_shadowing = propagation_semantics + boundary_preservation**: The bug is specifically about which config layer contains the wrong default. A fix that hardcodes values in the service layer masks the structural cause. The metadata explicitly identifies this as the trap fix. The benchmark must distinguish structural fixes from symptomatic fixes.

---

## 10. BENCHMARK VERSIONING POLICY

### 10.1 Why Versioning Matters

This overhaul changes benchmark semantics. Specifically:
- Cases previously scored as PASS may now score as BCMV, PARTIAL_FIX, or DEGENERATE_PASS
- Cases previously scored as PASS may now FAIL because happy-path or complement tests are added
- New classifications (BCMV, TRAP_FIX, PARTIAL_FIX) did not exist before

This means: **pass rates before and after this overhaul are not directly comparable.**

### 10.2 Version Boundaries

| Version | Definition | Breaking Change? |
|---|---|---|
| V2.0 | Current system (outcome-only tests, binary pass/fail) | Baseline |
| V2.1 | WEAK families fixed (wrong_condition, partial_rollback, invariant_partial_fail, config_shadowing, retry_dup) with happy-path and complement tests added | **YES** -- pass rates will decrease for these families |
| V2.2 | USABLE families strengthened (anti-hardcoding, mechanism checks, side-effect content) | **YES** -- pass rates may decrease, BCMV classification introduced |
| V2.3 | Full measurement architecture (MeasurementVerdict, all families at STRONG+) | **YES** -- classification system replaces binary pass/fail |

### 10.3 Comparability Rules

1. **Within a version**: Pass rates are comparable across models, conditions, and trials.
2. **Across versions**: Pass rates are NOT comparable. V2.1 pass rate < V2.0 pass rate does not mean the models got worse.
3. **Reporting requirement**: All results must state which benchmark version produced them.
4. **Dual-reporting period**: During V2.1 rollout, both V2.0 and V2.1 results should be computed and reported for the same model outputs, to establish the version-transition delta.
5. **New classifications**: BCMV, PARTIAL_FIX, LUCKY_FIX are new signals. They should be reported separately from the primary pass rate, not collapsed into PASS or FAIL.

### 10.4 What Counts as a Semantically Breaking Change

A change is semantically breaking if it can change the classification of a model output without changing the model output itself:
- Adding a new assertion that was not previously checked
- Adding a mechanism constraint to a previously behavior-only family
- Adding an anti-hardcoding input that causes a formerly-passing hardcoded output to fail
- Introducing a new classification category (BCMV, TRAP_FIX)
- Changing the equivalence policy for a family

All of these require a version bump.

A change is NOT semantically breaking if it only affects infrastructure:
- Improving state isolation without changing assertions
- Restructuring test code without changing test logic
- Adding meta-validation checks
- Improving error messages

### 10.5 Historical Data Treatment

Existing run logs (`logs/v2_*`) were produced under V2.0 semantics. They remain valid for V2.0 claims. They should NOT be retroactively re-scored under V2.1+ semantics unless the raw model outputs are re-evaluated.

---

## 11. MIGRATION PLAN

### Phase 0: Foundation (no behavior change, no version bump)

**Goal**: Establish invariant specification infrastructure.

1. Create `invariant_schema.py` -- dataclass implementing Section 4.1 schema
2. Create `invariant_registry.py` -- maps case_id to invariant spec
3. Create `invariant_validator.py` -- implements meta-validation checklist (Section 8)
4. Create `degenerate_templates.py` -- no-op, constant, bypass generators per family
5. Unit tests for schema, registry, validator

**Files**: New files only. No existing changes.
**Verification**: Schema can represent all 28 families. Validator runs without error.

### Phase 1: Audit and Classify (no behavior change, no version bump)

**Goal**: Rate every existing invariant, identify gaps.

1. Fill invariant specs from current test code + cases_v2.json for all 28 families
2. Run strength rubric on each
3. Run false-pass simulation (META-3) against all families with existing tests
4. Produce audit report: family -> strength -> gaps -> degenerate pass results

**Files**: New invariant records. No test changes.
**Verification**: Audit report matches Section 9.1 assessments. Confirms WEAK families.

### Phase 2: Fix WEAK Families -- triggers version bump to V2.1

**Goal**: Bring 5 WEAK families to USABLE. This is the minimum-viable benchmark fix.

Priority order:
1. `wrong_condition` (a,b,c) -- add complement conditions (below-threshold allows)
2. `partial_rollback` (a,b,c) -- add happy-path test (successful order)
3. `invariant_partial_fail` -- add happy-path test (successful transfer) + no-op exclusion
4. `config_shadowing` -- add anti-hardcoding with different config values
5. `retry_dup` (a,b,c) -- add fail_first=True test path + mechanism check

For each family:
- Write formal invariant spec
- Derive new assertions from spec using derivation rules (Section 4)
- Add assertions to existing test function
- Run META-3 (degenerate simulation) to verify degenerates now fail
- Run META-1 (reference fix) to verify no regression
- Compute dual scores (V2.0 and V2.1) on existing model outputs

**Files**: `tests_v2/test_wrong_condition.py`, `tests_v2/test_partial_rollback.py`, `tests_v2/test_invariant_partial_fail.py`, `tests_v2/test_config_shadowing.py`, `tests_v2/test_retry_dup.py`
**Verification**: All 5 families pass META-1, META-2, META-3. Strength >= USABLE.

### Phase 3: Strengthen USABLE Families -- version V2.2

**Goal**: Bring all USABLE families to STRONG. Introduce mechanism checks and BCMV classification.

For each USABLE family (per Section 9.1):
- Add anti-hardcoding inputs
- Add complement conditions
- Add mechanism evidence checks where equivalence policy requires
- Add side-effect content checks (not just count)
- Introduce BCMV classification in eval results

Order: temporal_drift, missing_branch, feature_flag_drift, partial_update, cache_invalidation_order, use_before_set, lazy_init, silent_default, early_return, effect_order, l3_state_pipeline, commit_gate, overdetermination, ordering_dependency

**Files**: Most `tests_v2/test_*.py` files. `exec_eval.py` (add BCMV classification field).
**Verification**: All families pass META-1 through META-8. Strength >= STRONG.

### Phase 4: Full Measurement Architecture -- version V2.3

**Goal**: Implement MeasurementVerdict, full classification pipeline.

1. Implement `MeasurementVerdict` dataclass (Section 7.1)
2. Implement classification decision procedure (Section 7.2)
3. Wire CandidateEvaluator to produce MeasurementVerdict
4. Bring STRONG families to RESEARCH_GRADE where feasible
5. Add per-assertion reporting (partial fix detection)
6. Integrate IsolationEngine as the sole execution path for canonical scoring
7. Deprecate concat-path scoring for research results

**Files**: `exec_eval.py`, `evaluator.py`, `harness/` modules, select test files
**Verification**: Full meta-validation suite passes. Classification produces expected results for all known inputs.

### Phase 5: Anti-Degenerate Automation (no version bump)

**Goal**: Automate META-3 as a CI check.

1. Integrate `degenerate_templates.py` with validation pipeline
2. For each case: generate no-op, constant, bypass -> verify all fail
3. Add to pre-merge checks

**Files**: `validate_cases_v2.py`, `degenerate_templates.py`
**Verification**: `python validate_cases_v2.py` includes anti-degenerate check.

### Phase 6: Documentation Lock-Down (no version bump)

**Goal**: Prevent regression.

1. Write invariant specs into `cases_v2.json` (new `invariant_spec` field)
2. Add strength level to case metadata
3. Create pre-merge check: any test change that reduces strength is blocked
4. Document mechanism policy
5. Write benchmark version history

**Files**: `cases_v2.json`, documentation
**Verification**: Any assertion removal fails pre-merge validation.

---

## 12. RISKS

### 12.1 Backward Compatibility / Pass Rate Disruption

Strengthened invariants will reduce pass rates for previously-collected data. A model that scored 0.6 under V2.0 may score 0.4 under V2.1 because degenerate passes are now caught.

**Mitigation**: Dual-reporting period (Section 10.3). Compute both V2.0 and V2.1 scores during transition. Report the version-transition delta explicitly.

### 12.2 Over-Constraining Legitimate Alternative Fixes

Mechanism constraints may reject valid fixes that use a different (but correct) mechanism. Example: a fix that replaces `cache_put_if_absent` with `cache_put` is mechanistically different from the reference fix but equally valid.

**Mitigation**: `acceptable_mechanisms` in the invariant spec lists ALL acceptable mechanisms, not just the reference fix's mechanism. The mechanism check verifies the subsystem exists and is exercised, not that it uses the exact same function.

### 12.3 Cross-Version Comparability Loss

Researchers may incorrectly compare V2.0 and V2.1 pass rates and conclude models regressed.

**Mitigation**: Version stamp on all results. Documentation requiring version-matched comparisons. Dual-reporting period.

### 12.4 Semantic Drift in Invariant Specs

Over time, invariant specs may drift from test code if maintained separately.

**Mitigation**: META-5 (spec completeness) runs as CI. Test assertions must reference invariant IDs. Orphaned specs or orphaned assertions are flagged.

### 12.5 Hidden Nondeterminism Causing False Signals

If `random.random` is not properly mocked/restored, a test may pass or fail nondeterministically.

**Mitigation**: Every invariant with `nondeterminism_controls` entries must have mock/restore wrapped in `finally`. The harness verifies restoration. Currently only `invariant_partial_fail` and `retry_dup` use randomness -- both already mock it.

### 12.6 Benchmark Meta-Validation Incompleteness

META-3 (degenerate simulation) uses predefined templates. A novel degenerate not in the template library would slip through.

**Mitigation**: Three mandatory templates (no-op, constant, bypass) cover the most common degenerate classes. The degenerate catalog (integrated from invariant formalization audit, Section 6) identifies 13 distinct degenerate classes. Templates should be expanded to cover all 13 over time. META-7 (strength rubric) provides an additional check independent of templates.

### 12.7 BCMV Classification Overreach

Marking mechanism-violating fixes as BCMV (not PASS) makes a strong claim about what constitutes "understanding." A model that bypasses the cache but explains why in its reasoning may have demonstrated understanding despite the mechanism violation.

**Mitigation**: BCMV is a classification signal, not a judgment. It is reported alongside the reasoning classifier's output. Researchers can cross-reference BCMV with reasoning_correct to distinguish "understood but chose different approach" from "didn't understand the mechanism." The benchmark does not claim BCMV is always wrong -- it claims the distinction should be visible.

### 12.8 Invariant Spec Maintenance Burden

28 YAML files + 28 test files + schema validation + meta-tests is a significant maintenance surface.

**Mitigation**: The spec IS the test. Tests are derived from specs mechanically. Changing the spec changes the test. META-5 enforces consistency. The upfront cost is high but the ongoing cost is lower than maintaining ad-hoc tests that silently degrade.
