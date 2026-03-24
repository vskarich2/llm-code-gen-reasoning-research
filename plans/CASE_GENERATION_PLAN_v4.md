# T3 Benchmark — Case Generation Plan v4 (Consolidated Authoritative Plan)

**Date:** 2026-03-23
**Scope:** Phase 1 — 15 families × 3 difficulty levels = 45 cases
**Status:** PLAN ONLY — no cases generated yet
**Prerequisite:** Retry harness (see Targeted Retry Ablation Plan v3)

This is the single authoritative document. It supersedes v2, v3, v3-corrections, and v3-final-validation. All corrections and refinements are applied inline.

---

## 0. Design Constraints (from Forensic Analysis)

| Problem | Root Cause | Design Response |
|---|---|---|
| Evaluation bugs (alias_trivial, retry_ack_trivial) | Test reused across incompatible variants | Each case gets its own test function |
| 0.20 score floor on CSF cases | Text-matching gives partial credit for keywords | Execution-based evaluation is primary; text matching is secondary signal |
| 5/18 hard cases scored 0.00 across ALL models | Difficulty not calibrated — cases were impossible | Level A solvable by nano; Level C challenges 4o-mini |
| Partial code returns | Models return only the changed function | Tests use patching: inject candidate code into original module |
| Regime is model-dependent | Same case is REI for 4o-mini, CSF for nano | Difficulty levels create controlled gradient through regime boundary |

---

## 1. Generation Pipeline

```
Step 1: For each of 15 templates, define a FAMILY
        ├── shared domain + context
        ├── the single underlying bug pattern
        └── three difficulty levels (A, B, C)

Step 2: For each level, produce:
        ├── code files (1–4 files depending on level)
        ├── task prompt (the refactoring/fix instruction)
        ├── test function (execution-based invariant check)
        ├── reference fix (known-good minimal patch)
        └── metadata (contract, signals, trap description, ground_truth_bug)

Step 3: Self-validate each case (6 checks — see §7)

Step 4: Integration check:
        ├── runner.py can load and execute the case
        ├── retry_harness.py can run retry loops with classification
        ├── CGE contract can be elicited for it
        └── failure_classifier.py can classify its errors
```

---

## 2. Template → Family Mapping

Each family has a **primary** `bug_pattern_class` from the taxonomy in §13, plus optional secondary labels.

### STATE & MUTATION

| # | Template | Family | bug_pattern_class | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 1 | shared_reference_aliasing | `alias_config` | **implicit_schema** | — | App config | `DEFAULTS` dict returned by reference; mutation corrupts global state | Indirection depth |
| 2 | partial_state_update | `partial_update` | **partial_state_update** | hidden_dependency | User profile | Multi-field update where one dependent field is not written | Coupled fields |
| 3 | stale_cache | `stale_cache` | **hidden_dependency** | silent_failure | Product catalog | Cache read returns outdated value after write-through broken | Cache indirection |
| 4 | lazy_initialization | `lazy_init` | **execution_model_mismatch** | implicit_schema | Service bootstrap | Eager init breaks reset/override lifecycle | Lifecycle complexity |
| 5 | mutable_default_argument | `mutable_default` | **retry_state_accumulation** | implicit_schema | Task queue | `def f(items=[])` accumulates across calls | Visibility |

### TEMPORAL / ORDERING

| # | Template | Family | bug_pattern_class | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 6 | side_effect_ordering | `effect_order` | **hidden_dependency** | edge_case_omission | Event processing | Side effect must happen per-item, not batch end | Coupled effects |
| 7 | use_before_set | `use_before_set` | **edge_case_omission** | — | Data pipeline | Variable read before assignment on conditional path | Conditional complexity |
| 8 | retry_duplication | `retry_dup` | **retry_state_accumulation** | hidden_dependency | Message processing | Retry wraps non-idempotent op, doubling side effects | Idempotency surface |
| 9 | partial_rollback | `partial_rollback` | **partial_state_update** | — | Order fulfillment | Multi-step commit fails mid-sequence without compensation | Steps |
| 10 | temporal_drift | `temporal_drift` | **implicit_schema** | migration_compatibility | Metrics pipeline | Computation must run on raw data, gets moved to post-transform | Pipeline length |

### CONTROL FLOW

| # | Template | Family | bug_pattern_class | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 11 | missing_branch | `missing_branch` | **edge_case_omission** | — | Access control | Conditional doesn't handle a valid case | Branch visibility |
| 12 | incorrect_condition | `wrong_condition` | **edge_case_omission** | — | Rate limiter | Comparison operator wrong (< vs <=, and vs or) | Semantic distance |
| 13 | early_return_skip | `early_return` | **hidden_dependency** | partial_state_update | Payment processing | Early return skips critical cleanup step | Code after return |

### DATA STRUCTURE / SILENT FAILURE

| # | Template | Family | bug_pattern_class | Secondary | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|---|---|
| 14 | index_misalignment | `index_misalign` | **partial_state_update** | — | Report generation | Parallel arrays get out of sync after insert/delete | Structure complexity |
| 15 | silent_default_fallback | `silent_default` | **silent_failure** | distributed_configuration | Feature flags | `.get(key, default)` silently returns wrong value | Fallback chain |

### Distribution

| bug_pattern_class | Families | Count |
|---|---|---|
| hidden_dependency | stale_cache, early_return, effect_order | 3 |
| partial_state_update | partial_update, partial_rollback, index_misalign | 3 |
| edge_case_omission | use_before_set, missing_branch, wrong_condition | 3 |
| implicit_schema | alias_config, temporal_drift | 2 |
| retry_state_accumulation | mutable_default, retry_dup | 2 |
| execution_model_mismatch | lazy_init | 1 |
| silent_failure | silent_default | 1 |

---

## 3. Difficulty Ladder

| Dimension | Level A (Easy) | Level B (Medium) | Level C (Hard) |
|---|---|---|---|
| **Files** | 1, ≤40 lines | 2, ≤80 lines | 3–4, ≤150 lines |
| **Bug location** | Same function | 1-hop: called helper | 2-hop: crosses files |
| **Distractors** | 0 | 1–2 | 3–4 |
| **Trap** | None | Mild | Strong (obvious fix IS the bug) |
| **Fix size** | 1–3 lines | 3–6 lines | 5–10 lines, may touch 2 files |
| **`boundary_type`** | `local` | `cross_function` | `cross_boundary` |
| **`boundary_group`** | `local` | `local` | `cross_boundary` |
| **`temporal_depth`** | `single_step` | `single_step` or `multi_step` | `multi_step` |
| **`statefulness`** | `stateless` | `stateless` or `stateful` | `stateful` |
| **`causal_depth`** | `L1` | `L2` | `L3` |

### Causal Depth

| Level | Definition | Reasoning Required |
|---|---|---|
| **L1** | Bug and effect in same function | Single-step deduction |
| **L2** | Bug in function A, manifests in function B | Trace one call boundary |
| **L3** | Bug requires tracing state through 2+ files | Model state flow across modules |

### Calibration Targets

| Level | nano | 4o-mini | 5-mini |
|---|---|---|---|
| A | 30–50% | 70–90% | 20–40% |
| B | 5–15% | 40–60% | 5–20% |
| C | 0–5% | 15–30% | 0–5% |

---

## 4. Test Design

### 4A. Test Signature

```python
def test(mod: ModuleType) -> tuple[bool, list[str]]:
```

Properties: **pure** (no globals), **deterministic**, **idempotent**, **self-contained**.

### 4B. State Isolation

```python
def test(mod):
    # 1. SETUP — fresh state
    if hasattr(mod, '_store'): mod._store.clear()
    if hasattr(mod, 'DEFAULTS'): mod.DEFAULTS = {"timeout": 30, "retries": 3}
    # 2. EXECUTE
    try:
        result = mod.function_under_test(state)
    except Exception as e:
        return False, [f"raised: {e}"]
    # 3. ASSERT
    if not invariant_holds(result, state):
        return False, [f"invariant violated: {describe(result)}"]
    return True, ["pass"]
```

No `random` patching. Explicit error injection via stubs:
```python
class FailOnSecondCall:
    def __init__(self): self.calls = 0
    def __call__(self, *a):
        self.calls += 1
        if self.calls == 2: raise RuntimeError("injected")
        return "ok"
```

### 4C. Test Contract

```json
{
    "setup": "Creates two Account objects with balances [100, 0]",
    "execution": "Calls execute_transfer(a, b, 50) with injected failure",
    "assertions": ["a.balance + b.balance == 100", "a.balance == 100 on failure"],
    "state_reset": ["No module-level state"],
    "retry_notes": "Safe — fresh objects each call",
    "failure_surface": "local",
    "retry_failure_modes": []
}
```

### 4D. Failure Surface and Retry Modes

| Surface | Definition |
|---|---|
| `local` | Bug and invariant in same function |
| `cross_boundary` | Invariant crosses module boundary |
| `temporal` | Invariant depends on execution order |
| `stateful` | Invariant depends on accumulated state |

| Retry Mode | Definition |
|---|---|
| `duplicate_side_effects` | Effect fires twice under retry |
| `state_leakage` | Module-level state survives between attempts |
| `ordering_violation` | Retry changes operation order |
| `accumulation` | State grows monotonically |

### 4E. Scoring

| Outcome | Score | Criteria |
|---|---|---|
| Pass | 1.0 | Test returns (True, ...) |
| Silent fail | 0.5 | Code runs, invariant fails |
| Reasoning only | 0.2 | Code errors but reasoning identifies issue |
| Fail | 0.0 | Code fails, no correct reasoning |

---

## 5. Case Schema

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
    "boundary_group": "local",
    "temporal_depth": "single_step",
    "statefulness": "stateless",
    "causal_depth": "L2",

    "description": "create_config() returns DEFAULTS by reference. get_settings() caches and mutates it.",
    "task": "get_settings() returns stale data after config changes. Simplify the config loading. Return updated code.",
    "trap": "Routing through merge_overrides() changes the return format",

    "code_files": ["code_snippets/alias_config_b/config.py", "code_snippets/alias_config_b/app.py"],

    "hard_constraints": [
        "create_config() must return a fresh dict on every call",
        "Mutating one config must not affect future calls"
    ],
    "positive_signals": ["copy", "dict(", ".copy()", "fresh", "new dict"],
    "negative_signals": ["merge_overrides", "global config"],

    "ground_truth_bug": {
        "type": "shared_reference_mutation",
        "location": "config.py::create_config",
        "invariant": "create_config() must return a dict that is not reference-equal to DEFAULTS",
        "fix_pattern": "return DEFAULTS.copy()"
    },

    "reference_fix": {
        "file": "code_snippets/alias_config_b/config.py",
        "function": "create_config",
        "diff_summary": "Change `return DEFAULTS` to `return DEFAULTS.copy()`",
        "lines_changed": 1
    },

    "test_contract": {
        "setup": "Reset DEFAULTS to known values",
        "execution": "Call create_config() twice, mutate first result",
        "assertions": ["Second call returns original values", "DEFAULTS unchanged"],
        "state_reset": ["mod.DEFAULTS = {'timeout': 30, 'retries': 3}"],
        "retry_notes": "Safe — resets DEFAULTS before each run",
        "failure_surface": "cross_boundary",
        "retry_failure_modes": ["state_leakage"]
    },

    "expected_regime_hypothesis": {
        "_note": "HYPOTHESIS ONLY. Derived from causal_depth. Validated after first run.",
        "nano": "CSF",
        "4o-mini": "Heuristic",
        "5-mini": "CSF"
    }
}
```

### Field Reference

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | string | yes | `{family}_{level}` |
| `family` | string | yes | Shared across A/B/C |
| `template` | string | yes | One of 15 template names |
| `difficulty` | string | yes | A, B, or C |
| `failure_mode` | string | yes | Evaluator dispatch key |
| `bug_pattern_class` | string | yes | Primary from §13 taxonomy |
| `bug_pattern_secondary` | string | no | Secondary if applicable |
| `boundary_type` | enum | yes | `local` / `cross_function` / `cross_boundary` |
| `boundary_group` | enum | yes | Derived: `local` if boundary_type != cross_boundary, else `cross_boundary` |
| `temporal_depth` | enum | yes | `single_step` / `multi_step` |
| `statefulness` | enum | yes | `stateless` / `stateful` |
| `causal_depth` | enum | yes | `L1` / `L2` / `L3` |
| `ground_truth_bug` | object | yes | `.type`, `.location` (file::func), `.invariant`, `.fix_pattern` |
| `reference_fix` | object | yes | Known-good fix for validation |
| `test_contract` | object | yes | Includes `.failure_surface`, `.retry_failure_modes` |
| `expected_regime_hypothesis` | object | yes | Per-model single label. Pre-registration, not measurement |

---

## 6. File Structure

```
T3_code_generation_MVP/
  cases_v2.json
  code_snippets_v2/{family}_{level}/*.py
  tests_v2/test_{family}.py          # test_a(), test_b(), test_c()
  reference_fixes/{family}_{level}.py  # fixed version of main file
```

Conventions: no external deps, no async, no randomness, exactly one bug per case, bug is silent (runs without crash).

---

## 7. Validation Pipeline

```
CHECK 1: Buggy code loads without error
CHECK 2: Test FAILS on buggy code
CHECK 3: Test PASSES on reference fix
CHECK 4: Fix is minimal (≤ lines_changed + 2)
CHECK 5: Test is idempotent (3 runs, identical results)
CHECK 6: Cross-case isolation (no namespace collision)
```

No case ships until all 6 pass.

---

## 8. Difficulty Calibration

- **Too easy:** ALL models pass baseline → add distractors
- **Too hard:** NO model passes ANY condition → reduce indirection
- **Goldilocks:** After first run, verify ~15 cases per band (>60% / 20–60% / <20% for 4o-mini)

---

## 9. Diversity Guarantees

Covered: 7 domain clusters, 7 bug surfaces, 3 abstraction levels. See §2 distribution table.

---

## 10. Example: `partial_rollback` Family

*Level A:* 1 file. `place_order()` calls `reserve()` then `charge()`. No rollback on charge failure. Fix: try/except + release.

*Level B:* 2 files. Charge is `self.gateway.process()` — one hop. Trap: notification ordering looks like the issue.

*Level C:* 3 files. Two resources to compensate (inventory + audit_log). Trap: retry instead of rollback; forget audit cleanup.

---

## 11. Generation Execution Plan

1. Create directory structure
2. For each family: write Level A → validate → Level B → validate → Level C → validate
3. Build `cases_v2.json`
4. Run `validate_cases.py`
5. Baseline experiment (nano + 4o-mini)
6. Calibrate
7. Ship for full ablation

---

## 12. Bug Pattern Taxonomy

| # | Class | Definition | Forensic Grounding |
|---|---|---|---|
| 1 | **implicit_schema** | Producer/consumer disagree on data shape without shared schema | CRIT-001: field renamed, bundle reshaped |
| 2 | **partial_state_update** | Multi-field update where dependent parts not updated atomically | STRUCT-001: new fields, consumers not updated |
| 3 | **hidden_dependency** | Function depends on another's behavior, invisible from call site | CRIT-001: scorer depends on bundle shape |
| 4 | **silent_failure** | Error path produces valid-looking but incorrect output | SILENT-001: fallback score 0.25 |
| 5 | **retry_state_accumulation** | Retry causes state growth or side effect duplication | RETRY-001: LangGraph append-only reducer |
| 6 | **execution_model_mismatch** | Code for one execution model deployed under another | RACE-001: parallel workers |
| 7 | **edge_case_omission** | Valid input not handled by conditional/guard | STRUCT-001: bracket access on missing key |

---

## 13. Mechanism Signals and Regime Assignment

### Mechanism Signals

```json
"mechanism_signals": {
    "reasoning_consistent": true,
    "error_stable": true,
    "diff_localized": true,
    "progress_made": false
}
```

#### reasoning_consistent

TRUE if EITHER:

**Condition A:** `critique_accuracy >= 0.5 AND error_stable == True`

**Condition B:** `reasoning_valid == True on ≥50% of failing iterations AND model's reasoning contains at least one term from ground_truth_bug.type`

```python
def reasoning_consistent(per_iteration, ground_truth_bug, critique_accuracy, error_stable):
    if critique_accuracy >= 0.5 and error_stable:
        return True
    failing = [it for it in per_iteration if not it["pass"]]
    if not failing:
        return False
    n_valid = sum(1 for it in failing if it["reasoning_valid"])
    if n_valid / len(failing) < 0.5:
        return False
    bug_terms = ground_truth_bug["type"].lower().replace("_", " ").split()
    for it in failing:
        text = (it.get("reasoning_text") or "").lower()
        if any(t in text for t in bug_terms):
            return True
    return False
```

#### error_stable

TRUE if errors are consistent across iterations.

**For ≥3 failing iterations:** `error_entropy < 0.5`

**For <3 failing iterations:** TRUE if all failing iterations have the same `error_type` (majority rule — insufficient data for entropy).

```python
def error_stable(per_iteration):
    failing = [it["error_type"] for it in per_iteration if not it["pass"] and it["error_type"]]
    if len(failing) <= 1:
        return True  # single error = stable by convention
    if len(failing) < 3:
        return len(set(failing)) == 1  # all same type
    return error_entropy(failing) < 0.5
```

#### diff_localized

TRUE if model's edits are in or near the bug function.

**Edit distance:** 0 = same function, 1 = same file/different function, 2 = different file.

```python
def diff_localized(edited_functions, ground_truth_location):
    gt_file, gt_func = ground_truth_location.split("::")
    min_dist = 2
    for edit in edited_functions:
        ed_file, ed_func = edit.split("::")
        if ed_file == gt_file and ed_func == gt_func:
            return True  # distance 0
        elif ed_file == gt_file:
            min_dist = min(min_dist, 1)
    return min_dist <= 1
```

Also TRUE if edited function is directly called by the bug function (captures legitimate cross-function fixes).

#### progress_made

TRUE if score improved in any iteration vs the first failing iteration.

```python
def progress_made(per_iteration):
    failing = [it["score"] for it in per_iteration if not it["pass"]]
    if len(failing) <= 1:
        return False
    return any(s > failing[0] for s in failing[1:])
```

Used for sub-labels only, NOT primary regime assignment (to avoid outcome circularity).

### Regime Assignment (Deterministic Priority Logic)

```python
def assign_regime(signals, outcome):
    if outcome["initial_pass"]:
        return "heuristic"

    rc = signals["reasoning_consistent"]
    es = signals["error_stable"]
    dl = signals["diff_localized"]

    if rc and es:
        return "REI"
    elif (not rc) and es and dl:
        return "heuristic"
    elif (not rc) and es and (not dl):
        return "heuristic_weak"
    else:  # not es
        return "CSF"
```

**Sub-labels** (for detailed analysis):
- `REI` + not dl → `REI_misdirected`
- `REI` + progress_made → `REI_improving`
- `CSF` + rc → `CSF_unstable`

**Replications:** Majority vote. No majority → `"mixed"`.

### Signal Validation Invariant

If any signal is uncomputable (e.g., all iterations unparseable), the record gets `failure_regime = "unclassifiable"` and `regime_degraded = True`. These records are included in pass-rate analyses but excluded from regime-stratified analyses.

---

## 14. Logging Requirements

### Per-Run Log Record

```json
{
    "run_id": "uuid",
    "timestamp": "ISO-8601",
    "case_metadata": {
        "case_id": "alias_config_b",
        "family": "alias_config",
        "bug_pattern_class": "implicit_schema",
        "boundary_type": "cross_function",
        "boundary_group": "local",
        "temporal_depth": "single_step",
        "statefulness": "stateless",
        "causal_depth": "L2",
        "difficulty": "B"
    },
    "run_config": {
        "model": "gpt-4o-mini",
        "condition": "retry_adaptive",
        "contract_used": false,
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
            "silent_failure": true,
            "output_structurally_valid": true,
            "reasoning_valid": true,
            "code_parseable": true,
            "code_runnable": true,
            "classification": {"...from failure_classifier..."},
            "intervention": {"...from adaptive retry..."}
        }
    ],
    "mechanism_metrics": {
        "mechanism_signals": {
            "reasoning_consistent": true,
            "error_stable": true,
            "diff_localized": true,
            "progress_made": false
        },
        "failure_regime": "REI",
        "failure_regime_sub": "REI",
        "regime_degraded": false,
        "critique_accuracy": 1.0,
        "convergence_slope": 0.25,
        "repair_efficiency": 0.25,
        "error_entropy": 0.0,
        "edit_dispersion": 0.0,
        "reasoning_execution_gap": false,
        "silent_failure_rate": 1.0
    },
    "contract_metrics": {
        "contract_elicited": false,
        "contract_verifiable": false,
        "contract_satisfied": false,
        "degraded": false
    }
}
```

### Key Metric Definitions

**error_entropy:** Shannon entropy over `error_type` categories (7-value closed set: syntax_error, import_error, runtime_error, invariant_violation, wrong_output, timeout, no_code). Normalized to [0,1]. Computed only over failing iterations.

**edit_dispersion:** `(n_functions_edited - 1) / max(n_functions_total - 1, 1)`. Measured at function granularity via AST diff. Mean across failing iterations.

**critique_accuracy:** `n_matching / n_failing` where matching = error_message contains `ground_truth_bug.location` function name OR contains ≥2 substantive terms from `ground_truth_bug.invariant`.

**reasoning_execution_gap:** TRUE only if ALL THREE: `reasoning_consistent == True`, `error_stable == True`, `final_pass == False`.

**silent_failure:** `code_parseable AND code_runnable AND error_type == "invariant_violation" AND output_structurally_valid AND score >= 0.3 AND NOT pass`.

**repair_efficiency:** `(final_score - initial_score) / total_iterations`. Normalized rate of improvement.

**All trajectory metrics (entropy, dispersion, progress) are normalized by number of failing iterations**, not total iterations.

### outcome_type values

| Value | Definition |
|---|---|
| `pass_first_try` | Pass on iteration 1 |
| `converged_pass` | Fail initially, pass on iteration K>1 |
| `improved_no_pass` | Score increased but never passed |
| `flat_fail` | Score constant across iterations, never passed |
| `degraded` | Score decreased |
| `oscillating` | Score goes up and down |

### Mandatory Filtering Rule

> **Retry analyses (convergence, trajectory, entropy, slope) MUST exclude `pass_first_try` cases.** Regime and pass-rate analyses may include them.

> **`regime_degraded = True` records** are included in pass-rate analyses but excluded from regime-stratified analyses.

---

## 15. Metrics & Ablation Plan

### Primary Outcomes

| Metric | Aggregation |
|---|---|
| **Pass@1** | Per model × condition × bug_pattern × difficulty |
| **Converged@K** | Per model × condition. K ∈ {1, 2, 3} |
| **Iterations-to-success** | Mean/median per model × condition (excluding pass_first_try) |

### Ablation Conditions

| Condition | Label | What it Tests | Source |
|---|---|---|---|
| Baseline | `BL` | Raw model capability | runner.py |
| Diagnostic nudge | `DX` | Does pointing out issue help? | runner.py |
| Guardrail strict | `GS` | Does constraining actions help? | runner.py |
| Contract-Gated Execution | `CG` | Does contract + gate help? | runner.py |
| Retry no contract | `retry_no` | Does retry help without contract? | retry_harness.py |
| Retry with contract | `retry_wc` | Does retry + contract help? | retry_harness.py |
| Retry adaptive | `retry_adapt` | Does classifier-guided retry help? | retry_harness.py |

**Minimum ablation:** BL + retry_no + retry_adapt = 3 × 45 × 2 models = 270 calls.

**Full ablation:** 7 conditions × 45 × 3 models × 3 replications = 2,835 calls.

---

## 16. Required Analyses

### 16A. Regime × Bug Pattern

For each `bug_pattern_class`, compute distribution of `failure_regime`. Output: heatmap.

### 16B. Boundary Effect

Compare `failure_regime` across A→B→C within each family. Output: sankey/grouped bar.

### 16C. Contract/CGE Effect by Bug Pattern

`delta = pass_rate(retry_wc) - pass_rate(retry_no)` stratified by bug_pattern. Output: grouped bar.

### 16D. Difficulty Gradient Validation

Pass rate and regime distribution by `causal_depth`. Output: stacked bar.

### 16E. Retry Dynamics by Trajectory

Cluster by `trajectory_type`, correlate with `failure_regime`. Output: scatter (error_entropy × convergence_slope, colored by regime).

### 16F. Adaptive Retry Effectiveness (NEW — from ablation plan)

`delta = pass_rate(retry_adapt) - pass_rate(retry_no)` stratified by ablation plan's `failure_type_final`. Cross-reference with `bug_pattern_class` to validate classifier accuracy. Output: comparison table.

---

## 17. Required Figures

| Fig | Data | Type | Shows |
|---|---|---|---|
| 1 | §16A | Heatmap | Regime distribution by bug pattern |
| 2 | §16D | Stacked bar | Pass rate by causal depth |
| 3 | §16C | Grouped bar | Contract effect by pattern |
| 4 | §16B | Sankey | Boundary effect across levels |
| 5 | per_iteration | Line plots | Convergence curves by outcome_type |
| 6 | §16E | Scatter | Error entropy × slope, colored by regime |
| 7 | mechanism_metrics | Bar chart | Reasoning-execution gap rate by pattern |
| 8 | §16F | Table | Adaptive vs non-adaptive by failure type |

---

## 18. Integration with Ablation Design Plan

The case generation plan and the Targeted Retry Ablation Plan v3 are **complementary systems** that share infrastructure. This section maps their integration points.

### 18A. What Each System Owns

| Component | Owner | Consumed By |
|---|---|---|
| 45 case definitions (`cases_v2.json`) | **Case plan** | Both systems |
| Code snippets + tests | **Case plan** | Both systems |
| `ground_truth_bug` per case | **Case plan** | Ablation (for critique_accuracy, regime signals) |
| `failure_classifier.py` | **Ablation plan** | Case plan logging (classification per iteration) |
| `retry_harness.py` | **Ablation plan** | Case plan conditions (retry_no, retry_wc, retry_adapt) |
| Adaptive hints | **Ablation plan** | N/A (internal to retry harness) |
| Mechanism signals + regime | **Case plan** | Post-hoc analysis of ablation data |
| Shadow analysis | **Ablation plan** | Paper figures |

### 18B. Taxonomy Alignment

The two plans use different failure type vocabularies. They are related but serve different purposes:

| Case Plan: `bug_pattern_class` | Ablation Plan: `failure_type_final` | Relationship |
|---|---|---|
| implicit_schema | — (no direct match) | bug_pattern_class is a design-time label; failure_type_final is a runtime classifier output |
| hidden_dependency | HIDDEN_DEPENDENCY | Direct match |
| partial_state_update | PARTIAL_STATE_UPDATE | Direct match |
| edge_case_omission | EDGE_CASE_MISSED | Same concept, different name |
| retry_state_accumulation | RETRY_LOGIC_BUG | Same concept, different name |
| silent_failure | — | Not classified at runtime (silent failures look like invariant_violation) |
| execution_model_mismatch | — | Rare; may map to CONFOUNDING_LOGIC |

**Rule:** `bug_pattern_class` is ground truth (set at case design time). `failure_type_final` is the classifier's best guess from runtime signals. The gap between them is a measure of classifier accuracy — **not** an inconsistency.

### 18C. Logging Schema Compatibility

The ablation plan's trajectory entry schema and the case plan's per_iteration schema must merge. The unified per-iteration record is:

```json
{
    "iteration": 1,
    "pass": false,
    "score": 0.5,
    "error_type": "invariant_violation",
    "error_message": "stock leaked",
    "silent_failure": true,
    "output_structurally_valid": true,
    "reasoning_valid": true,
    "code_parseable": true,
    "code_runnable": true,
    "attempt_similarity": 0.97,

    "classification": {
        "failure_type_final": "PARTIAL_STATE_UPDATE",
        "critique_failure_type": "logic_error",
        "error_category": "logic",
        "matched_keywords": ["partial", "incomplete"],
        "classifier_rule_path": "rule1_critique_keyword",
        "classifier_confidence": 0.8
    },
    "intervention": {
        "type": "PARTIAL_STATE_UPDATE",
        "confidence": 0.8,
        "applied": true,
        "hint_text": "Ensure all related state variables are updated consistently..."
    }
}
```

Fields from the **case plan:** `error_type`, `silent_failure`, `output_structurally_valid`, `reasoning_valid`, `code_parseable`, `code_runnable`.

Fields from the **ablation plan:** `attempt_similarity`, `classification`, `intervention`.

Both systems write to the same JSONL file per run.

### 18D. Condition Mapping

| Condition | runner.py | retry_harness.py | Notes |
|---|---|---|---|
| BL (baseline) | `run_single(case, model, "baseline")` | — | No retry |
| DX, GS | `run_single(case, model, condition)` | — | Single-shot with prompt modification |
| CG | `run_contract_gated(case, model)` | — | CGE with up to 1 retry on gate failure |
| retry_no | — | `run_retry(case, model, use_contract=False, use_adaptive=False)` | K attempts, error feedback only |
| retry_wc | — | `run_retry(case, model, use_contract=True, use_adaptive=False)` | K attempts + contract |
| retry_adapt | — | `run_retry(case, model, use_contract=False, use_adaptive=True)` | K attempts + classifier hints |

The runner dispatches to the appropriate system based on condition.

### 18E. What the Case Plan Provides to the Ablation

1. **45 cases with ground_truth_bug** — enables the ablation's shadow analysis to compare `failure_type_final` against the known `bug_pattern_class`
2. **Mechanism signals computed post-hoc** — the ablation logs the raw data; the case plan's analysis scripts compute `reasoning_consistent`, `error_stable`, `diff_localized`, `progress_made` and assign `failure_regime`
3. **Structural metadata** (`boundary_group`, `causal_depth`, `statefulness`) — enables stratified analysis that the ablation plan alone cannot do

### 18F. What the Ablation Provides to the Case Plan

1. **`failure_classifier.py`** — classifies errors at runtime, producing `classification` entries in logs
2. **Adaptive hints** — a concrete intervention mechanism whose effectiveness can be measured per `bug_pattern_class`
3. **`attempt_similarity`** — stagnation detection that enriches trajectory analysis
4. **Shadow analysis scripts** — compute cross-condition deltas that feed into §16 analyses

---

## 19. Open Questions

1. **Task prompt style:** "Refactor" vs "Fix the bug" framing
2. **Reference fix format:** Full fixed Python file (recommended) vs `.patch`
3. **Integration:** New `cases_v2.json` (recommended) with `--cases` flag on runner.py
4. **Failure mode naming:** New taxonomy (`bug_pattern_class`) for case metadata; existing names for evaluator dispatch
5. **Distractors at Level C:** Vary per family (2–4), not standardized
6. **Ablation scope:** Start with minimum (270 calls), scale to full after smoke test
7. **Per-iteration responses:** Log full responses to separate `_responses.jsonl` (already implemented)
8. **Regime assignment:** Automatic per §13 rules, with human review of `mixed` and `unclassifiable` cases
