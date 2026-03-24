# T3 Benchmark — Case Generation Plan v3 (Mechanism-Aware Revision)

**Date:** 2026-03-23
**Scope:** Phase 1 — 15 families × 3 difficulty levels = 45 cases
**Status:** PLAN ONLY — no cases generated yet
**Prerequisite:** Retry harness assumed to exist
**Revision:** Targeted upgrade of v2 — adds mechanism taxonomy, structural metadata, logging spec, analysis plan. All v2 content preserved.

---

## Revision Log (v2 → v3)

| Section | Change Type | What Changed |
|---|---|---|
| §2 Template → Family Mapping | **EXTENDED** | Added `bug_pattern_class` (primary + secondary) column |
| §3 Difficulty Ladder | **EXTENDED** | Added `causal_depth` (L1/L2/L3) and structural metadata dimensions |
| §4 Test Design | **EXTENDED** | Added `failure_surface` and `retry_failure_modes` per test |
| §5 Case Schema | **EXTENDED** | 8 new required fields added |
| §13 | **NEW** | Bug Pattern Taxonomy (grounded in forensic audit) |
| §14 | **NEW** | Logging Requirements for Analysis |
| §15 | **NEW** | Metrics & Ablation Plan |
| §16 | **NEW** | Required Analyses |
| §17 | **NEW** | Required Figures |
| §0–§1, §6–§12 | UNCHANGED | All v2 content preserved verbatim |

---

## 0–1. [UNCHANGED from v2]

*(Lessons from Forensic Analysis + Overall Generation Pipeline — no modifications)*

---

## 2. Template → Family Mapping [EXTENDED]

Each family now has a **primary** `bug_pattern_class` drawn from the taxonomy defined in §13, plus optional secondary labels. The mapping is grounded in the real bug audit (CODEBASE_FORENSIC_ANALYSIS.md).

### STATE & MUTATION

| # | Template | Family | bug_pattern_class (primary) | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 1 | shared_reference_aliasing | `alias_config` | **implicit_schema** | — | App config | `DEFAULTS` dict returned by reference; caller mutation corrupts global state | Indirection depth |
| 2 | partial_state_update | `partial_update` | **partial_state_update** | hidden_dependency | User profile | Multi-field update where one dependent field is not written | Number of coupled fields |
| 3 | stale_cache | `stale_cache` | **hidden_dependency** | silent_failure | Product catalog | Cache read returns outdated value after write-through path is broken | Cache indirection |
| 4 | lazy_initialization | `lazy_init` | **execution_model_mismatch** | implicit_schema | Service bootstrap | Eager init at import time breaks reset/override lifecycle | Lifecycle complexity |
| 5 | mutable_default_argument | `mutable_default` | **retry_state_accumulation** | implicit_schema | Task queue | `def f(items=[])` accumulates across calls | Visibility of accumulation |

### TEMPORAL / ORDERING

| # | Template | Family | bug_pattern_class (primary) | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 6 | side_effect_ordering | `effect_order` | **implicit_schema** | edge_case_omission | Event processing | Side effect must happen per-item, not once at batch end | Number of coupled effects |
| 7 | use_before_set | `use_before_set` | **edge_case_omission** | — | Data pipeline | Variable read before assignment on a conditional path | Conditional complexity |
| 8 | retry_duplication | `retry_dup` | **retry_state_accumulation** | hidden_dependency | Message processing | Retry wraps a non-idempotent operation, doubling side effects | Idempotency surface |
| 9 | partial_rollback | `partial_rollback` | **partial_state_update** | — | Order fulfillment | Multi-step commit fails mid-sequence without compensation | Number of steps |
| 10 | temporal_drift | `temporal_drift` | **implicit_schema** | migration_compatibility | Metrics pipeline | Computation that must run on raw data gets moved to post-transform | Pipeline length |

### CONTROL FLOW

| # | Template | Family | bug_pattern_class (primary) | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 11 | missing_branch | `missing_branch` | **edge_case_omission** | — | Access control | A conditional doesn't handle a valid case | Branch visibility |
| 12 | incorrect_condition | `wrong_condition` | **edge_case_omission** | — | Rate limiter | Comparison operator is wrong (< vs <=, and vs or) | Semantic distance |
| 13 | early_return_skip | `early_return` | **hidden_dependency** | partial_state_update | Payment processing | Early return skips a critical cleanup/finalization step | Code after return |

### DATA STRUCTURE

| # | Template | Family | bug_pattern_class (primary) | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 14 | index_misalignment | `index_misalign` | **partial_state_update** | — | Report generation | Two parallel arrays/dicts get out of sync | Data structure complexity |

### SILENT FAILURE

| # | Template | Family | bug_pattern_class (primary) | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 15 | silent_default_fallback | `silent_default` | **silent_failure** | distributed_configuration | Feature flags | `.get(key, default)` silently returns wrong value | Fallback chain length |

### Bug Pattern Class Distribution

| bug_pattern_class | Families (primary) | Count |
|---|---|---|
| implicit_schema | alias_config, effect_order, temporal_drift | 3 |
| partial_state_update | partial_update, partial_rollback, index_misalign | 3 |
| edge_case_omission | use_before_set, missing_branch, wrong_condition | 3 |
| hidden_dependency | stale_cache, early_return | 2 |
| retry_state_accumulation | mutable_default, retry_dup | 2 |
| execution_model_mismatch | lazy_init | 1 |
| silent_failure | silent_default | 1 |

This distribution covers 7 of 10 taxonomy classes at primary level. The remaining 3 (distributed_configuration, migration_compatibility, test_drift) appear as secondary labels. This is intentional — those 3 are meta-level patterns (they describe how bugs propagate across a codebase, not a single-case bug type).

---

## 3. Difficulty Ladder Design [EXTENDED]

### Universal Rules [EXTENDED with structural metadata + causal depth]

| Dimension | Level A (Easy) | Level B (Medium) | Level C (Hard) |
|---|---|---|---|
| **Files** | 1 file, ≤40 lines | 2 files, ≤80 lines total | 3–4 files, ≤150 lines total |
| **Bug location** | Same function as the entry point | 1-hop: bug in called helper | 2-hop: bug effect crosses files |
| **Distractor functions** | 0 | 1–2 (named similarly to the bug) | 3–4 (including attractive-but-wrong alternatives) |
| **Trap strength** | No trap | Mild trap | Strong trap: the "obvious" fix introduces the bug |
| **Fix size** | 1–3 lines changed | 3–6 lines changed | 5–10 lines changed, may touch 2 files |
| **Expected regime** | Heuristic (pattern matching) | REI (reasoning correct, execution needs structure) | CSF boundary (requires causal simulation) |
| | | | |
| **`boundary_type`** | `local` | `cross_function` | `cross_boundary` |
| **`temporal_depth`** | `single_step` | `single_step` or `multi_step` | `multi_step` |
| **`statefulness`** | `stateless` | `stateless` or `stateful` | `stateful` |
| **`causal_depth`** | `L1` — direct, local causation | `L2` — cross-function dependency | `L3` — multi-step, cross-module state evolution |

### Causal Depth Definition (NEW)

Causal depth is the primary analytical dimension. It measures how many reasoning hops are required to identify the bug:

| Level | Code | Definition | Reasoning Required |
|---|---|---|---|
| **L1** | Direct | Bug and its effect are in the same function. The broken invariant is visible in the local code. | "This function returns a reference instead of a copy" — single-step deduction |
| **L2** | Cross-function | Bug is in function A but the invariant violation manifests in function B (called by A or calling A). | "Function A's return value is mutated by function B because A doesn't copy" — requires tracing one call boundary |
| **L3** | Cross-module | Bug requires tracing state through 2+ files. The effect may only manifest under specific execution sequences. | "Module X writes to cache, Module Y reads stale data because Module Z broke the write-through path" — requires modeling state flow across modules |

**Connection to regimes (from regime analysis):**
- L1 cases are predicted to be Heuristic for 4o-mini (pattern matchable)
- L2 cases are predicted to be REI for 4o-mini (reasoning correct but execution needs scaffolding)
- L3 cases are predicted to be at the CSF boundary (causal simulation required)

This mapping is a HYPOTHESIS, not ground truth. The first experimental run will validate or falsify it.

### Calibration Targets [UNCHANGED from v2]

*(Same table as v2 — nano/4o-mini/5-mini pass rate bands)*

---

## 4. Retry-Aware Test Design [EXTENDED]

### 4A–4C. [UNCHANGED from v2]

*(Test architecture, state isolation protocol, test contract schema — all preserved)*

### 4D. Failure Modes Under Retry [EXTENDED with mechanism labels]

Each test now explicitly documents two mechanism-aware metadata fields:

#### `failure_surface` — WHERE the bug manifests

| Surface Type | Definition | Example |
|---|---|---|
| `local` | Bug and invariant violation are in the same function/scope | `alias_config_a`: mutate return value, same function sees corruption |
| `cross_boundary` | Invariant violation crosses a function or module boundary | `stale_cache_b`: write in service.py, stale read in api.py |
| `temporal` | Invariant depends on execution order / sequence | `effect_order_b`: snapshot must happen before increment |
| `stateful` | Invariant depends on accumulated state across calls | `mutable_default_a`: list grows across invocations |

#### `retry_failure_modes` — WHAT can go wrong under retry

| Mode | Definition | Which families are susceptible |
|---|---|---|
| `duplicate_side_effects` | Retry causes an effect to fire twice | retry_dup (all levels), effect_order_b/c |
| `state_leakage` | Module-level state survives between attempts | mutable_default (all), stale_cache (all), alias_config_b/c |
| `ordering_violation` | Retry changes the order of operations | effect_order (all), temporal_drift_b/c |
| `accumulation` | State grows monotonically across retries | mutable_default (all), retry_dup (all), index_misalign_b/c |

#### Per-Family Test Mechanism Mapping

| Family | Level A | Level B | Level C |
|---|---|---|---|
| alias_config | local / state_leakage | cross_boundary / state_leakage | cross_boundary / state_leakage |
| partial_update | local / — | cross_boundary / — | cross_boundary / ordering_violation |
| stale_cache | local / state_leakage | cross_boundary / state_leakage | cross_boundary / state_leakage |
| lazy_init | local / state_leakage | cross_boundary / state_leakage | cross_boundary / state_leakage, ordering_violation |
| mutable_default | stateful / accumulation | stateful / accumulation | stateful / accumulation |
| effect_order | temporal / ordering_violation | temporal / ordering_violation, duplicate | temporal / ordering_violation, duplicate |
| use_before_set | local / — | local / — | cross_boundary / — |
| retry_dup | stateful / duplicate_side_effects | stateful / duplicate, accumulation | stateful / duplicate, accumulation |
| partial_rollback | local / — | cross_boundary / — | cross_boundary / ordering_violation |
| temporal_drift | local / — | cross_boundary / — | cross_boundary / ordering_violation |
| missing_branch | local / — | cross_boundary / — | cross_boundary / — |
| wrong_condition | local / — | local / — | cross_boundary / — |
| early_return | local / — | cross_boundary / — | cross_boundary / ordering_violation |
| index_misalign | stateful / accumulation | stateful / accumulation | cross_boundary / accumulation |
| silent_default | local / — | cross_boundary / — | cross_boundary / state_leakage |

### 4E. Scoring Rubric [UNCHANGED from v2]

---

## 5. Case Schema [EXTENDED]

```json
{
    "id": "alias_config_b",
    "family": "alias_config",
    "template": "shared_reference_aliasing",
    "difficulty": "B",
    "failure_mode": "ALIASING",

    "bug_pattern_class": "implicit_schema",
    "bug_pattern_secondary": null,

    "boundary_type": "cross_function",
    "temporal_depth": "single_step",
    "statefulness": "stateless",
    "causal_depth": "L2",

    "description": "create_config() returns DEFAULTS by reference. get_settings() caches and mutates it.",
    "task": "get_settings() returns stale data after config changes. Simplify the config loading to fix this. Return the updated code.",
    "trap": "Routing through merge_overrides() changes the return format",

    "code_files": [
        "code_snippets/alias_config_b/config.py",
        "code_snippets/alias_config_b/app.py"
    ],

    "hard_constraints": [
        "create_config() must return a fresh dict on every call",
        "Mutating one config must not affect future calls"
    ],

    "positive_signals": ["copy", "dict(", ".copy()", "fresh", "new dict"],
    "negative_signals": ["merge_overrides", "global config"],

    "reference_fix": {
        "file": "code_snippets/alias_config_b/config.py",
        "function": "create_config",
        "diff_summary": "Change `return DEFAULTS` to `return DEFAULTS.copy()`",
        "lines_changed": 1
    },

    "test_contract": {
        "setup": "Reset DEFAULTS to known values",
        "execution": "Call create_config() twice, mutate first result",
        "assertions": [
            "Second call returns original values (not mutated)",
            "DEFAULTS dict is unchanged"
        ],
        "state_reset": ["mod.DEFAULTS = {'timeout': 30, 'retries': 3}"],
        "retry_notes": "Safe — test resets DEFAULTS before each run",
        "failure_surface": "cross_boundary",
        "retry_failure_modes": ["state_leakage"]
    },

    "expected_regime": {
        "nano":   {"heuristic": 0.3, "REI": 0.5, "CSF": 0.2},
        "4o-mini": {"heuristic": 0.7, "REI": 0.2, "CSF": 0.1},
        "5-mini": {"heuristic": 0.1, "REI": 0.3, "CSF": 0.6}
    }
}
```

### New Fields (v3 additions)

| Field | Type | Required | Description |
|---|---|---|---|
| `bug_pattern_class` | string | yes | Primary class from §13 taxonomy |
| `bug_pattern_secondary` | string | no | Secondary class if applicable |
| `boundary_type` | enum | yes | `"local"` \| `"cross_function"` \| `"cross_boundary"` |
| `temporal_depth` | enum | yes | `"single_step"` \| `"multi_step"` |
| `statefulness` | enum | yes | `"stateless"` \| `"stateful"` |
| `causal_depth` | enum | yes | `"L1"` \| `"L2"` \| `"L3"` |
| `test_contract.failure_surface` | string | yes | `"local"` \| `"cross_boundary"` \| `"temporal"` \| `"stateful"` |
| `test_contract.retry_failure_modes` | list[string] | yes | Subset of: `duplicate_side_effects`, `state_leakage`, `ordering_violation`, `accumulation` (empty list if no retry risk) |
| `expected_regime` | object | yes | Per-model probability distribution over {heuristic, REI, CSF}. Hypothesis — filled at design time, validated after first run |

### v2 Fields [ALL PRESERVED]

*(id, family, template, difficulty, failure_mode, description, task, trap, code_files, hard_constraints, positive_signals, negative_signals, reference_fix, test_contract.setup/execution/assertions/state_reset/retry_notes)*

---

## 6–12. [UNCHANGED from v2]

*(File structure, validation pipeline, difficulty calibration, diversity guarantees, example family sketch, generation execution plan, open questions — all preserved verbatim)*

---

## 13. Bug Pattern Taxonomy [NEW]

Grounded in the codebase forensic audit (CODEBASE_FORENSIC_ANALYSIS.md), which identified 8 bug cycles across 30 commits. Each taxonomy class maps to at least one real bug cycle.

| # | Class | Definition | Forensic Grounding | How LLMs Fail on This |
|---|---|---|---|---|
| 1 | **implicit_schema** | Producer and consumer disagree on data shape, field names, or field locations — without a shared schema | CRIT-001: thesis field moved from top-level to reasoning dict; field renamed supported_by_claims→supporting_claims | Model produces code that assumes a dict shape not matching the actual contract. Reasoning says "preserve the interface" but code changes the interface |
| 2 | **partial_state_update** | Multi-field or multi-resource update where not all dependent parts are updated atomically | STRUCT-001: new required fields added to data model but mocks/consumers not updated | Model fixes one field but misses a coupled field. Classic REI: reasoning identifies both fields, code only changes one |
| 3 | **hidden_dependency** | A function depends on behavior of another function that is not visible from the call site | CRIT-001: scorer depends on bundle shape produced by runner, but dependency is through shared dict | Model refactors function A without checking function B that silently depends on A's output shape |
| 4 | **silent_failure** | Error path produces valid-looking but incorrect output (fallback scores, empty dicts, default values) | SILENT-001: CRIT fallback score of 0.25 masked all evaluation errors | Model adds .get(key, default) where the default is wrong, or catches exceptions too broadly |
| 5 | **retry_state_accumulation** | Retry/re-execution causes state to grow or side effects to duplicate because container is append-only | RETRY-001: LangGraph reducer appended stale retries to state["revisions"] | Model adds retry logic without checking if the underlying container accumulates. Mutable defaults are the single-function version |
| 6 | **distributed_configuration** | Same default/constant defined independently in N files — changing one without the others creates inconsistency | CONFIG-001: crit_user_template default in 4 files | Model changes a default in one file but doesn't propagate. Only applicable at Level C (cross-module) |
| 7 | **migration_compatibility** | Old and new data formats coexist; consumer code must handle both | TELEM-001: new telemetry format deployed before dashboard updated | Model writes code for new format but breaks old-format consumers. Temporal_drift family at Level C |
| 8 | **execution_model_mismatch** | Code written for one execution model (serial) deployed under another (parallel, lazy, deferred) | RACE-001: .json.tmp shared by parallel workers | Model assumes sequential execution (e.g., eager init when lazy is required). Lazy_init family |
| 9 | **edge_case_omission** | A valid input case is not handled by a conditional, dispatch, or guard | STRUCT-001 (partial): bracket access doesn't handle missing key | Model generates code that works for the tested path but not the edge path |
| 10 | **test_drift** | Tests check the wrong thing after code refactoring | TEST-001: tests checked inline HTML after JS extraction | Not directly testable as a code bug — this is a meta-pattern about test infrastructure. Included for completeness but not mapped to any case family as primary |

---

## 14. Logging Requirements for Analysis [NEW]

The retry harness MUST emit structured JSONL logs that support the analyses in §16. Each run (one model × one condition × one case) produces one log record.

### 14A. Per-Run Log Record Schema

```json
{
    "run_id": "uuid",
    "timestamp": "ISO-8601",

    "case_metadata": {
        "case_id": "alias_config_b",
        "family": "alias_config",
        "bug_pattern_class": "implicit_schema",
        "boundary_type": "cross_function",
        "temporal_depth": "single_step",
        "statefulness": "stateless",
        "causal_depth": "L2",
        "difficulty": "B"
    },

    "run_config": {
        "model": "gpt-4o-mini",
        "condition": "contract_gated",
        "contract_used": true,
        "max_iterations": 3,
        "temperature": 0.0
    },

    "outcome": {
        "initial_pass": false,
        "final_pass": true,
        "converged": true,
        "iterations_to_success": 2,
        "total_iterations": 2,
        "final_score": 1.0,
        "outcome_type": "converged_pass"
    },

    "per_iteration": [
        {
            "iteration": 1,
            "pass": false,
            "score": 0.5,
            "error_type": "invariant_violation",
            "error_message": "stock leaked: was 10, now 7",
            "reasoning_valid": true,
            "code_parseable": true,
            "code_runnable": true
        },
        {
            "iteration": 2,
            "pass": true,
            "score": 1.0,
            "error_type": null,
            "error_message": null,
            "reasoning_valid": true,
            "code_parseable": true,
            "code_runnable": true
        }
    ],

    "mechanism_metrics": {
        "failure_regime": "REI",
        "trajectory_type": "monotonic_improvement",
        "critique_accuracy": 1.0,
        "convergence_slope": 0.5,
        "error_entropy": 0.0,
        "edit_dispersion": 0.1,
        "reasoning_execution_gap": true
    },

    "contract_metrics": {
        "contract_elicited": true,
        "contract_verifiable": true,
        "contract_satisfied": true,
        "gate_violations_attempt1": 2,
        "gate_violations_attempt2": 0,
        "degraded": false
    }
}
```

### 14B. Field Definitions

#### Case Metadata (copied from case definition — enables filtering/grouping)

| Field | Source | Use |
|---|---|---|
| case_id, family, difficulty | cases_v2.json | Grouping, per-family analysis |
| bug_pattern_class | cases_v2.json | §16A analysis (regime × pattern) |
| boundary_type, temporal_depth, statefulness | cases_v2.json | §16B analysis (boundary effects) |
| causal_depth | cases_v2.json | §16D analysis (difficulty gradient) |

#### Outcome Fields

| Field | Type | Definition |
|---|---|---|
| `initial_pass` | bool | Did the first attempt pass? |
| `final_pass` | bool | Did the last attempt pass? |
| `converged` | bool | Did the model eventually pass? (= `final_pass`) |
| `iterations_to_success` | int \| null | Number of iterations before first pass. null if never passed |
| `total_iterations` | int | Total iterations run (may exceed iterations_to_success if we always run all K) |
| `final_score` | float | Score of the final iteration (0.0, 0.2, 0.5, 1.0) |
| `outcome_type` | enum | One of: `pass_first_try`, `converged_pass`, `improved_no_pass`, `flat_fail`, `degraded`, `oscillating` |

#### Outcome Type Definitions

| outcome_type | Definition | Regime Signal |
|---|---|---|
| `pass_first_try` | Pass on iteration 1 | Heuristic (if no scaffolding) or over-easy case |
| `converged_pass` | Fail initially, pass on iteration K>1 | REI — the gap was bridgeable |
| `improved_no_pass` | Score increased but never passed | REI borderline — close but not enough iterations |
| `flat_fail` | Score stays at 0.0 or 0.5 across all iterations | CSF — model cannot make progress |
| `degraded` | Score decreased from iteration 1 to final | Heuristic disrupted — scaffolding/retry hurt |
| `oscillating` | Score goes up and down across iterations | Unstable reasoning — model changes approach each time |

#### Mechanism Metrics

| Field | Type | Definition | How to Compute |
|---|---|---|---|
| `failure_regime` | enum | Post-hoc regime label: `"heuristic"`, `"REI"`, `"CSF"` | Assigned based on outcome_type + score trajectory (see §15) |
| `trajectory_type` | enum | Shape of score trajectory across iterations | `"monotonic_improvement"`, `"flat"`, `"degraded"`, `"oscillating"` |
| `critique_accuracy` | float [0,1] | Did the retry feedback correctly identify the bug? | Fraction of iterations where error_message pointed to the actual bug (vs. a symptom or wrong issue) |
| `convergence_slope` | float | Rate of score improvement per iteration | `(final_score - initial_score) / total_iterations` |
| `error_entropy` | float [0,1] | How much do errors change across iterations? | Shannon entropy of the set of distinct error_messages across iterations. 0 = same error every time (stuck). 1 = different error every time (wandering) |
| `edit_dispersion` | float [0,1] | How scattered are edits across files? | `n_files_edited / n_files_in_case`. 0 = edits concentrated. 1 = edits everywhere |
| `reasoning_execution_gap` | bool | Did the model identify the correct issue but fail to fix it? | reasoning_valid=True AND pass=False on any iteration |

#### Contract Metrics (for CGE runs only)

| Field | Type | Definition |
|---|---|---|
| `contract_elicited` | bool | Did the model produce a parseable contract? |
| `contract_verifiable` | bool | Did the contract use only ALLOWED_EFFECTS? |
| `contract_satisfied` | bool | Did the final code pass the contract gate? |
| `gate_violations_attempt1` | int | Number of gate violations on first code generation |
| `gate_violations_attempt2` | int | Number after retry (0 = gate passed) |
| `degraded` | bool | Did CGE produce worse results than baseline for this case? |

### 14C. Log Storage

```
logs/
  {model}_{timestamp}.jsonl          # one line per run (case × condition)
  {model}_{timestamp}_prompts.jsonl  # full prompts (separate for size)
  {model}_{timestamp}_responses.jsonl # full LLM responses (separate)
```

Compatible with existing logging in `execution.py`. The new fields are additive — no existing fields are removed.

---

## 15. Metrics & Ablation Plan [NEW]

### 15A. Primary Outcomes

| Metric | Definition | Aggregation |
|---|---|---|
| **Pass@1** | Fraction of cases that pass on first attempt (baseline, no retry) | Per model, per condition, per bug_pattern_class, per difficulty |
| **Converged@K** | Fraction of cases that eventually pass within K iterations | Per model, per condition. K ∈ {1, 2, 3} |
| **Iterations-to-success** | Mean/median iterations before first pass (among cases that converge) | Per model, per condition |

### 15B. Mechanism Metrics (computed from log records)

| Metric | Grain | Purpose |
|---|---|---|
| **failure_regime distribution** | Per model × condition | What fraction of failures are Heuristic / REI / CSF? |
| **trajectory_type distribution** | Per model × condition | What fraction are monotonic / flat / degraded / oscillating? |
| **error_entropy** | Per case × model | Is the model stuck on the same error (entropy=0) or wandering (entropy=1)? |
| **edit_dispersion** | Per case × model | Does the model correctly localize the fix, or scatter edits? |
| **convergence_slope** | Per model × condition | Is retry improving scores, or flat? |
| **reasoning_execution_gap rate** | Per model × bug_pattern_class | Which patterns exhibit the most REI-style failures? |

### 15C. Structural Metrics

| Metric | Stratification | Purpose |
|---|---|---|
| **Pass rate by bug_pattern_class** | model × condition × class | Which bug patterns are hardest? |
| **Pass rate by boundary_type** | model × condition × boundary | Does cross-boundary kill performance? |
| **Pass rate by temporal_depth** | model × condition × depth | Does multi-step reasoning fail? |
| **Pass rate by causal_depth** | model × condition × L1/L2/L3 | Is the difficulty ladder working? |
| **Pass rate by statefulness** | model × condition × stateless/stateful | Does statefulness predict failure? |

### 15D. Ablation Conditions

The experiment runs each case under these conditions (where applicable):

| Condition | Label | What it tests |
|---|---|---|
| Baseline (no scaffolding) | `BL` | Raw model capability |
| Diagnostic nudge | `DX` | Does pointing out the issue help? |
| Guardrail strict | `GS` | Does constraining actions help? |
| Contract-Gated Execution | `CG` | Does contract + gate help? |
| Repair loop (K=2) | `RL` | Does retry with error feedback help? |
| CGE + Repair loop | `CG+RL` | Does contract + retry help? |

Minimum viable ablation: `BL, CG, RL` (3 conditions × 45 cases × 3 models = 405 LLM calls).

Full ablation: all 6 conditions × 45 cases × 3 models × 3 replications = 2,430 LLM calls.

### 15E. Regime Assignment Rules

After collecting data, each (case, model, condition) triple gets a regime label:

| outcome_type | convergence_slope | reasoning_execution_gap | Regime |
|---|---|---|---|
| pass_first_try | — | — | **Heuristic** |
| converged_pass | > 0 | True | **REI** (gap was bridgeable) |
| converged_pass | > 0 | False | **REI** (but reasoning was also fixed) |
| improved_no_pass | > 0 | True | **REI (borderline)** |
| flat_fail | 0 | any | **CSF** |
| degraded | < 0 | — | **Heuristic disrupted** |
| oscillating | — | — | **CSF (unstable)** |

---

## 16. Required Analyses [NEW]

### 16A. Regime × Bug Pattern

**Question:** Do certain bug patterns reliably produce REI vs CSF failures?

**Method:** For each `bug_pattern_class`, compute the distribution of `failure_regime` across all models and conditions.

**Expected finding (hypothesis):**
- `implicit_schema` → mostly REI (model can identify the schema issue but misexecutes)
- `edge_case_omission` → mostly Heuristic at L1, CSF at L3 (pattern-matchable when obvious)
- `partial_state_update` → mostly CSF (requires simulating multi-step state)
- `retry_state_accumulation` → REI for capable models (CGE helps), CSF for weaker ones

**Output:** Heatmap (bug_pattern_class × regime, colored by proportion).

### 16B. Boundary Effect

**Question:** Does crossing a code boundary (function → module) cause a regime transition?

**Method:** For each family, compare `failure_regime` across levels A (local) → B (cross_function) → C (cross_boundary).

**Expected finding:**
- A→B: Heuristic→REI transition (model needs help crossing the boundary)
- B→C: REI→CSF transition (model cannot trace the full dependency chain)

**Output:** Sankey diagram showing regime flow across difficulty levels.

### 16C. Contract/CGE Effect by Bug Pattern

**Question:** Does CGE selectively help REI cases and not CSF cases, as predicted by the regime framework?

**Method:** For each `bug_pattern_class`, compute:
- `delta_pass_rate = pass_rate(CG) - pass_rate(BL)`
- `delta_pass_rate_retry = pass_rate(CG+RL) - pass_rate(RL)`

Stratify by bug pattern to identify which patterns benefit most from contracts.

**Expected finding (from regime analysis):**
- CGE helps `implicit_schema` and `retry_state_accumulation` (REI-dominant patterns)
- CGE hurts `edge_case_omission` at Level A (Heuristic-dominant, contract adds overhead)
- CGE has no effect on `partial_state_update` at Level C (CSF-dominant)

**Output:** Grouped bar chart (bug_pattern_class × delta, colored by condition).

### 16D. Difficulty Gradient Validation

**Question:** Does the L1→L2→L3 causal depth ladder produce the expected regime transitions?

**Method:** For each model, plot `pass_rate` and `failure_regime` distribution by `causal_depth`.

**Expected finding:**
- L1: mostly Heuristic (>60% pass for 4o-mini)
- L2: mostly REI (30-50% pass for 4o-mini)
- L3: mostly CSF (<20% pass for 4o-mini)

**Output:** Stacked bar chart (causal_depth × regime proportion × model).

### 16E. Retry Dynamics by Trajectory Type

**Question:** How do error trajectories differ by regime?

**Method:** Cluster cases by `trajectory_type` and correlate with `failure_regime`.

**Expected finding:**
- `monotonic_improvement` → REI cases
- `flat` → CSF cases
- `degraded` → Heuristic cases where retry hurts
- `oscillating` → borderline REI/CSF cases

**Output:** Scatter plot (error_entropy × convergence_slope, colored by regime).

---

## 17. Required Figures [NEW]

For the research paper, the following figures must be producible from the logged data:

| Figure | Data Source | Type | What It Shows |
|---|---|---|---|
| **Fig 1: Regime distribution by bug pattern** | §16A | Heatmap | Which patterns cause which failure modes |
| **Fig 2: Pass rate by causal depth** | §16D | Stacked bar | L1→L2→L3 difficulty gradient validation |
| **Fig 3: CGE effect by bug pattern** | §16C | Grouped bar | Where contracts help vs hurt, stratified by pattern |
| **Fig 4: Boundary effect (local vs cross)** | §16B | Sankey / grouped bar | How crossing boundaries changes the regime |
| **Fig 5: Convergence curves** | per_iteration data | Line plots (one per case cluster) | Score vs iteration number, colored by outcome_type |
| **Fig 6: Error entropy vs convergence slope** | §16E | Scatter | Regime separation in trajectory space |
| **Fig 7: Reasoning-execution gap rate** | mechanism_metrics | Bar chart by bug_pattern_class | Which patterns exhibit the most "knows but can't do" |
| **Fig 8: Model comparison radar** | all metrics | Radar chart per model | nano vs 4o-mini vs 5-mini across all mechanism dimensions |

---

## 18. Open Questions [EXTENDED from v2]

### From v2 (still open)

1. **Task prompt style**: "Refactor" vs "Fix the bug" framing
2. **Reference fix format**: `.patch` files vs full fixed Python files
3. **Integration**: extend `cases.json` or new `cases_v2.json`
4. **Failure mode naming**: reuse existing taxonomy or new
5. **Distractor count at Level C**: standardize or vary

### New for v3

6. **Regime probability calibration**: The `expected_regime` field uses probabilities (e.g., `{"heuristic": 0.7, "REI": 0.2, "CSF": 0.1}`). Should these be set by hand based on intuition, or left as uniform priors and updated after the first run?

7. **Critique accuracy measurement**: `critique_accuracy` requires comparing the error feedback to the "actual bug." This needs a ground-truth bug description per case. Should this be a new field in the case schema (e.g., `ground_truth_bug_description`)?

8. **Ablation scope**: The minimum viable ablation is 405 calls (3 conditions × 45 cases × 3 models). The full ablation is 2,430 calls. Which should be the initial target?

9. **Per-iteration logging granularity**: Should we log full LLM responses for every iteration, or only metadata? Full responses are needed for post-hoc analysis but increase storage 10×.

10. **Regime assignment timing**: Should `failure_regime` be assigned per-run (automatic, based on §15E rules) or post-hoc by a human analyst reviewing the data?
