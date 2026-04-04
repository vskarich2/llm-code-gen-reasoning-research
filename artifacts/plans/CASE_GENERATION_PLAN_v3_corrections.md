# Case Generation Plan v3 — Correction Pass

**Date:** 2026-03-23
**Type:** Targeted fixes to v3. No structural changes.
**Rule:** Apply these corrections to v3 before implementation. Each fix references the exact section it modifies.

---

## Fix 1: failure_regime Derived from Mechanism Signals, Not outcome_type

### Problem

§15E defines `failure_regime` from a lookup table keyed on `outcome_type`. This is circular: outcome_type describes WHAT happened (pass/fail trajectory), not WHY. A `flat_fail` could be CSF (model can't simulate the system) or REI (model reasons correctly but produces unparseable code every time). The outcome doesn't distinguish them.

### Replacement for §15E

Delete the existing §15E table. Replace with:

---

#### §15E. Regime Assignment (Mechanism-Based)

Regime is derived from three **mechanism signals**, not from outcome:

```json
"mechanism_signals": {
    "reasoning_consistent": true,
    "error_stable": true,
    "diff_localized": true
}
```

**Signal definitions:**

| Signal | Type | Definition | How to Compute |
|---|---|---|---|
| `reasoning_consistent` | bool | Model's reasoning correctly identifies the bug location and type across iterations | `reasoning_valid == True` on ≥50% of iterations where `pass == False`. Compared against `ground_truth_bug.type` and `ground_truth_bug.location` |
| `error_stable` | bool | The same category of error recurs across iterations (model is stuck, not wandering) | `error_entropy < 0.5` (computed over `error_type` categories, not raw strings — see Fix 3) |
| `diff_localized` | bool | Model's edits are concentrated in/near the actual bug location | `edit_distance_to_bug ≤ 1` where edit_distance_to_bug counts how many functions away the model's edits are from `ground_truth_bug.location` |

**Regime assignment rules:**

| reasoning_consistent | error_stable | diff_localized | Regime | Interpretation |
|---|---|---|---|---|
| True | True | True | **REI** | Knows the bug, targets the right place, but can't produce the fix. Execution is the bottleneck |
| True | True | False | **REI (misdirected)** | Knows the bug, stuck on same error, but edits the wrong place |
| True | False | — | **CSF (unstable)** | Knows the bug, but each attempt produces a different error. Can't converge |
| False | True | True | **Heuristic** | Doesn't identify the bug correctly, but edits are localized. Pattern matching without understanding |
| False | True | False | **Heuristic (scattered)** | Doesn't identify bug, edits are scattered. Applying templates blindly |
| False | False | — | **CSF** | Doesn't identify bug, errors are unstable. No causal model of the system |

**For pass_first_try cases:** Regime is `Heuristic` (succeeded without retry, suggesting pattern matching sufficed) OR `N/A` if the case was too easy (see Fix 9 filtering rule).

**Regime is assigned per (case, model) pair**, not per run. When replications exist, signals are averaged across replications before thresholding.

---

### Corresponding update to §14A log schema

Add `mechanism_signals` block to the per-run log record, inside `mechanism_metrics`:

```json
"mechanism_metrics": {
    "mechanism_signals": {
        "reasoning_consistent": true,
        "error_stable": true,
        "diff_localized": true
    },
    "failure_regime": "REI",
    ...
}
```

`failure_regime` is now DERIVED from `mechanism_signals`, not independently set. Log both so the derivation is auditable.

---

## Fix 2: Ground Truth Bug in Case Schema

### Problem

`critique_accuracy` (§14B) requires comparing error feedback to the actual bug, but the case schema has no machine-readable bug description.

### Addition to §5 Case Schema

Add new required field `ground_truth_bug`:

```json
"ground_truth_bug": {
    "type": "shared_reference_mutation",
    "location": "config.py::create_config",
    "invariant": "create_config() must return a dict that is not reference-equal to DEFAULTS",
    "fix_pattern": "return DEFAULTS.copy()"
}
```

**Field definitions:**

| Subfield | Type | Definition |
|---|---|---|
| `type` | string | Short label for the bug mechanism (free-form but consistent within family). Used by `critique_accuracy` to check if error feedback identifies the correct mechanism |
| `location` | string | `file::function` where the bug lives. Used by `diff_localized` signal |
| `invariant` | string | The invariant that is violated. Used by `critique_accuracy` to check if feedback identifies the correct invariant |
| `fix_pattern` | string | The minimal code pattern of a correct fix. Used by validation pipeline, not shown to model |

### Revised critique_accuracy computation (replaces §14B definition)

```
critique_accuracy = (n_iterations_where_feedback_matches_ground_truth) / (n_failing_iterations)
```

Where "feedback matches ground truth" means the `error_message` or `error_type` from the test:
1. References the correct function (`ground_truth_bug.location`), OR
2. Describes a violation matching `ground_truth_bug.invariant` (substring match on key terms)

This is computable automatically — no human labeling required per run.

---

## Fix 3: error_entropy Computed Over Categories, Not Strings

### Problem

Current definition: Shannon entropy of distinct `error_message` strings. Two messages describing the same bug in different words ("stock leaked: was 10, now 7" vs "stock leaked: was 10, now 4") would be counted as distinct, inflating entropy.

### Revised definition (replaces the error_entropy row in §14B)

| Field | Type | Definition | How to Compute |
|---|---|---|---|
| `error_entropy` | float [0, 1] | How much does the failure MODE change across iterations? | Shannon entropy computed over the **`error_type` category** sequence, NOT raw error_message strings. Normalized to [0, 1] by dividing by log2(n_categories). |

**error_type categories** (closed set):

| Category | Definition |
|---|---|
| `syntax_error` | Code does not parse |
| `import_error` | Module load fails (missing import, circular) |
| `runtime_error` | Uncaught exception during execution |
| `invariant_violation` | Code runs, but test invariant fails |
| `wrong_output` | Code runs, output has wrong shape/value but no invariant check fires |
| `timeout` | Execution exceeds time limit |
| `no_code` | Model returned reasoning but no code block |

**Computation:**

```python
from collections import Counter
import math

def error_entropy(per_iteration: list[dict]) -> float:
    failing = [it["error_type"] for it in per_iteration if not it["pass"] and it["error_type"]]
    if len(failing) <= 1:
        return 0.0
    counts = Counter(failing)
    total = sum(counts.values())
    n_categories = len(counts)
    if n_categories <= 1:
        return 0.0
    H = -sum((c/total) * math.log2(c/total) for c in counts.values())
    max_H = math.log2(n_categories)
    return H / max_H  # normalized to [0, 1]
```

**Interpretation:**
- 0.0 → same error type every iteration (stuck — CSF or stable REI)
- 1.0 → different error type every iteration (wandering — unstable CSF)

---

## Fix 4: edit_dispersion Refined to Function-Level

### Problem

Current definition: `n_files_edited / n_files_in_case`. For a 1-file Level A case, this is always 1.0 regardless of whether the model edited 1 function or 5.

### Revised definition (replaces edit_dispersion row in §14B)

| Field | Type | Definition | How to Compute |
|---|---|---|---|
| `edit_dispersion` | float [0, 1] | How scattered are the model's edits relative to the bug location? | Fraction of functions in the case that were modified, normalized. A perfectly localized fix edits only the function containing the bug (dispersion ≈ 0). Editing every function = 1.0 |

**Computation:**

```python
def edit_dispersion(candidate_code: str, original_code: str, ground_truth_location: str) -> float:
    """
    1. Diff candidate vs original at function granularity
    2. Count functions that differ (n_edited)
    3. Count total functions in case (n_total)
    4. Return (n_edited - 1) / max(n_total - 1, 1)
       Subtract 1 because the bug function SHOULD be edited
    """
```

This works for 1-file and multi-file cases. For Level A cases with 3 functions, editing only the bug function gives `(1-1)/(3-1) = 0.0` (perfectly localized). Editing all 3 gives `(3-1)/(3-1) = 1.0`.

**Per-iteration:** Computed on each iteration's candidate code. The logged value is the **mean across failing iterations** (to measure how scattered the model's failed attempts are).

---

## Fix 5: reasoning_execution_gap Strengthened

### Problem

Current definition: `reasoning_valid=True AND pass=False on any iteration`. This is too weak — a model that reasons correctly on iteration 1 but fixes the bug on iteration 2 would be flagged as having a gap, even though it converged.

### Revised definition (replaces reasoning_execution_gap row in §14B)

| Field | Type | Definition | How to Compute |
|---|---|---|---|
| `reasoning_execution_gap` | bool | Model consistently identifies the correct bug but cannot fix it | ALL THREE conditions must hold: (1) `reasoning_consistent == True` (correct bug identified on ≥50% of failing iterations), (2) `error_stable == True` (same error type persists — not wandering), (3) `final_pass == False` (model never succeeded) |

**Interpretation:** This is the signature of genuine REI — the model "knows" what's wrong but its code generation cannot produce the fix, and this persists across all retries. It is NOT triggered when the model eventually succeeds (that's convergence, not a gap).

---

## Fix 6: bug_pattern_class Mapping Audit

### Problem

`implicit_schema` had 3 families (alias_config, effect_order, temporal_drift). `effect_order` is misclassified — its bug is about a side-effect-to-iteration dependency, not about producer/consumer schema disagreement.

### Corrected Mappings

| Family | v3 Primary | v3-corrected Primary | Reason for Change |
|---|---|---|---|
| `effect_order` | implicit_schema | **hidden_dependency** | The per-item requirement is a dependency between the side effect and the loop iteration that isn't visible from the loop structure. This matches the hidden_dependency definition ("a function depends on behavior of another function that is not visible from the call site") |
| All other families | (unchanged) | (unchanged) | — |

### Corrected Distribution

| bug_pattern_class | Families (primary) | Count |
|---|---|---|
| hidden_dependency | stale_cache, early_return, **effect_order** | **3** (was 2) |
| implicit_schema | alias_config, temporal_drift | **2** (was 3) |
| partial_state_update | partial_update, partial_rollback, index_misalign | 3 |
| edge_case_omission | use_before_set, missing_branch, wrong_condition | 3 |
| retry_state_accumulation | mutable_default, retry_dup | 2 |
| execution_model_mismatch | lazy_init | 1 |
| silent_failure | silent_default | 1 |

No class has more than 3 families. The top three classes (hidden_dependency, partial_state_update, edge_case_omission) each have exactly 3 — balanced coverage of the most important patterns.

---

## Fix 7: Add boundary_group (Derived Field)

### Addition to §5 Case Schema

```json
"boundary_group": "local"
```

**Definition:** Coarsened grouping of `boundary_type` for analysis stratification.

| boundary_type | boundary_group |
|---|---|
| `local` | `local` |
| `cross_function` | `local` |
| `cross_boundary` | `cross_boundary` |

**Rationale:** The key analytical question (§16B) is whether crossing a MODULE boundary (not just a function boundary) causes a regime transition. `cross_function` (same file, different function) is structurally closer to `local` than to `cross_boundary` (different file). Grouping them simplifies the boundary effect analysis to a clean binary comparison.

**Field is derived, not manually set.** Implementation: `boundary_group = "cross_boundary" if boundary_type == "cross_boundary" else "local"`.

---

## Fix 8: Add silent_failure Metric

### Addition to §14A per-iteration schema

Add to each entry in `per_iteration`:

```json
{
    "iteration": 1,
    "pass": false,
    "score": 0.5,
    "error_type": "invariant_violation",
    "silent_failure": true,
    ...
}
```

**Definition:**

| Field | Type | Definition |
|---|---|---|
| `silent_failure` | bool | The candidate code executed without error AND produced plausible-looking output, BUT the invariant was violated |

**Computation:**

```python
silent_failure = (
    code_parseable == True
    and code_runnable == True
    and error_type == "invariant_violation"  # not runtime_error, not syntax_error
    and pass == False
)
```

**Why this matters:** Silent failures are the most dangerous failure mode (from forensic analysis: SILENT-001). They are also the hardest for retry to fix — the error feedback must explain an invariant violation, which is harder than explaining a crash. Cases with high `silent_failure` rates are predicted to be CSF-dominant.

### Addition to §15B Mechanism Metrics table

| Metric | Grain | Purpose |
|---|---|---|
| **silent_failure_rate** | Per case × model | Fraction of failing iterations that are silent failures. High rate → bug is subtle, retry feedback is weak |

---

## Fix 9: Retry Analysis Filtering Rule

### Addition to §16 (applies to ALL analyses in 16A–16E)

**MANDATORY FILTERING RULE:**

> All retry-dynamics analyses (§16E, Converged@K, iterations_to_success, trajectory_type, convergence_slope, error_entropy) **MUST exclude `pass_first_try` cases**.
>
> Cases that pass on the first attempt have no retry trajectory. Including them in retry analyses would:
> 1. Inflate Converged@K by counting cases that didn't need retrying
> 2. Produce meaningless `convergence_slope = 0` entries
> 3. Bias trajectory_type toward "flat" (no iterations to analyze)
>
> **Implementation:** Filter on `outcome_type != "pass_first_try"` before computing any retry metric.

**Regime analyses (§16A, §16B, §16C) may include pass_first_try cases** — they are valid data points for regime classification (labeled as `Heuristic`).

**Pass rate analyses (§15A, §15C) always include pass_first_try** — Pass@1 specifically measures first-attempt performance.

---

## Fix 10: expected_regime Marked as Hypothesis

### Problem

The `expected_regime` field contains per-model probability distributions that look authoritative but are subjective priors.

### Revision to §5 Case Schema

Replace the `expected_regime` field definition:

**Before:**
```json
"expected_regime": {
    "nano":   {"heuristic": 0.3, "REI": 0.5, "CSF": 0.2},
    "4o-mini": {"heuristic": 0.7, "REI": 0.2, "CSF": 0.1},
    "5-mini": {"heuristic": 0.1, "REI": 0.3, "CSF": 0.6}
}
```

**After:**
```json
"expected_regime_hypothesis": {
    "_note": "HYPOTHESIS ONLY — not ground truth. Set at design time based on causal_depth + forensic analysis priors. Will be compared against observed failure_regime after first experimental run.",
    "nano":   "CSF",
    "4o-mini": "Heuristic",
    "5-mini": "CSF"
}
```

**Changes:**
1. Field renamed to `expected_regime_hypothesis` to make the status unambiguous
2. Probability distributions replaced with single most-likely label (probabilities implied false precision)
3. `_note` field added as a schema-level reminder
4. Values derived mechanically from `causal_depth`: L1 → Heuristic for 4o-mini, CSF for nano/5-mini. L2 → REI for 4o-mini, CSF for others. L3 → CSF for all.

This is a **pre-registration** of expected outcomes, not a measurement. The analysis in §16D will compare observed vs expected.

---

## Summary of All Fixes

| # | Section | What Was Fixed | Type |
|---|---|---|---|
| 1 | §15E | failure_regime now derived from 3 mechanism signals, not outcome_type | **Breaking logic fix** |
| 2 | §5, §14B | Added `ground_truth_bug` to schema; critique_accuracy defined against it | **New required field** |
| 3 | §14B | error_entropy computed over error_type categories, not raw strings | **Metric definition fix** |
| 4 | §14B | edit_dispersion measured at function granularity, not file granularity | **Metric definition fix** |
| 5 | §14B | reasoning_execution_gap requires all 3: correct reasoning + stable error + no success | **Strengthened definition** |
| 6 | §2 | effect_order moved from implicit_schema to hidden_dependency | **Classification fix** |
| 7 | §5 | Added `boundary_group` (derived: local vs cross_boundary) | **New derived field** |
| 8 | §14A, §15B | Added `silent_failure` per-iteration flag + aggregate rate metric | **New metric** |
| 9 | §16 | Retry analyses must exclude pass_first_try cases | **Filtering rule** |
| 10 | §5 | expected_regime renamed to expected_regime_hypothesis; probabilities → single labels | **Precision fix** |

### Assumptions Clarified

1. **Regime is NOT outcome.** Outcome (pass/fail/converge) is an observable. Regime (Heuristic/REI/CSF) is a causal explanation of WHY that outcome occurred. The mechanism signals (reasoning_consistent, error_stable, diff_localized) bridge this gap.

2. **ground_truth_bug is per-case, not per-run.** Each case has exactly one bug. The ground truth is set at design time and validated by the validation pipeline (Check 2: test fails on buggy code, Check 3: test passes on reference fix).

3. **error_type is assigned by the test harness, not the model.** The 7 error_type categories are determined by the test execution infrastructure (did it parse? did it run? did the invariant hold?). This makes error_entropy deterministic and reproducible.

4. **edit_dispersion requires function-level diffing.** This means the implementation needs an AST-level differ or at minimum a `def`-header-based chunker. This is feasible for Python code with the `ast` module.

5. **silent_failure is the most dangerous category.** From the forensic analysis, SILENT-001 (CRIT fallback score) was the most damaging bug because it produced valid-looking output. Cases with high silent_failure rates should be prioritized for CGE analysis — contracts are specifically designed to catch this class of error.
