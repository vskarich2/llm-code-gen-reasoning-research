# LEG_true × Trajectory Regime Analysis Script Spec

**Date:** 2026-03-24
**Script:** `scripts/leg_regime_analysis.py`
**Depends on:** LEG Evaluation Module v7, retry_harness.py trajectory logging

---

## 1. Scope and Purpose

### What this script answers

1. Is LEG_true enriched in specific trajectory regimes? (e.g., do stagnating runs show more LEG_true than diverging runs?)
2. When LEG_true occurs, is it predominantly coupling failure or execution failure?
3. Does this subtype composition vary by regime?
4. Does the `retry_alignment` intervention change the regime distribution or the LEG_true rate within regimes?
5. What are the dominant attempt-to-attempt transitions when LEG_true is present?

### What this script does NOT answer

- Whether LEG_true is "real" (that is the evaluator module's job, not analysis)
- What causes LEG (that is the hypothesis-testing experiments' job)
- How to improve model performance (this is descriptive, not prescriptive)

### Metric hierarchy

- **Primary analysis metric:** `LEG_true` as defined in LEG Evaluation Module v7
- **Subtype decomposition:** `LEG_coupling`, `LEG_execution` (alignment condition only)
- **Diagnostic / fallback:** `LEG_keyword` (reported in a separate column, never mixed into primary tables)
- **Alignment-conditioned analysis** uses `LEG_true`, not keyword LEG

---

## 2. Input Sources

### Primary source of truth

The script reads **per-run metadata JSONL files** produced by `retry_harness.py`. Each file contains interleaved per-iteration records and summary records.

The script identifies summary records by: `record["iteration"] == "summary"`.

The script identifies per-iteration records by: `record["iteration"]` is an integer.

### File discovery

The script takes one or more JSONL file paths as input. It does NOT discover files automatically.

### What the script reads

For each summary record:
- Run-level fields (case_id, condition, model, converged, total_iterations_executed, etc.)
- Trajectory array (list of per-attempt dicts, code field stripped)
- LEG summary fields (leg_rate_true, evaluator_bias, etc.)
- Trajectory dynamics (trajectory_dynamics.pattern)
- Failure sequence, failure persistence

For each per-attempt entry within the trajectory:
- pass, score
- leg_true, leg_coupling, leg_execution
- leg_keyword_only
- classifier_failure_type
- llm_eval_blind_verdict, llm_eval_blind_type
- alignment_success, alignment_step_coverage (if present)
- attempt index (position in trajectory array)

### Case metadata

The script also reads `cases_v2.json` to obtain per-case metadata:
- difficulty (A, B, C, D)
- family
- failure_mode
- bug_pattern_class (if present)

The path to cases_v2.json is provided via CLI argument.

---

## 3. Required Input Fields

### Summary-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `case_id` | str | required | |
| `condition` | str | required | must be a known retry condition |
| `model` | str | required | |
| `converged` | bool | required | |
| `total_iterations_executed` | int | required | |
| `trajectory` | list[dict] | required | |
| `trajectory_dynamics` | dict | required | must contain `pattern` |
| `failure_regime` | str | required | |
| `failure_persistence` | dict | optional | |
| `failure_sequence` | list[str] | optional | |
| `leg_rate_true` | float | optional | present if use_llm_eval was True |
| `leg_rate_keyword` | float | optional | |
| `evaluator_bias` | dict | optional | |

### Per-attempt fields (within trajectory array)

| Field | Type | Required | Notes |
|---|---|---|---|
| `pass` | bool | required | |
| `score` | float | required | |
| `attempt` | int | required | 0-indexed |
| `leg_true` | bool | required if evaluator ran | False if evaluator did not run |
| `leg_keyword_only` | bool | optional | diagnostic |
| `leg_coupling` | bool\|None | alignment-only | None for non-alignment |
| `leg_execution` | bool\|None | alignment-only | None for non-alignment |
| `classifier_failure_type` | str | required | |
| `llm_eval_blind_verdict` | str\|None | required if evaluator ran | |
| `llm_eval_blind_type` | str\|None | required if evaluator ran | |
| `alignment_success` | bool\|None | alignment-only | |
| `alignment_step_coverage` | float\|None | alignment-only | |

### Missing field behavior

| Situation | Behavior |
|---|---|
| Summary missing `trajectory` | Skip run, log warning |
| Summary missing `trajectory_dynamics` | Skip run, log warning |
| Summary missing `leg_rate_true` (evaluator not run) | Include in regime analysis but exclude from LEG cross-tabs |
| Attempt missing `leg_true` | Treat as `leg_true = False` with warning |
| Attempt missing `leg_coupling`/`leg_execution` on alignment condition | Log warning, exclude from subtype analysis |
| Attempt missing `leg_coupling`/`leg_execution` on non-alignment condition | Expected, no warning |

---

## 4. Validation Checks Before Analysis

The script runs these checks on all loaded data before computing any statistics. If any check fails with severity ERROR, the script exits. WARNING checks log and continue.

| Check | Severity | Rule |
|---|---|---|
| `case_id` is non-empty string | ERROR | every summary |
| `condition` is in `{"retry_no_contract", "retry_with_contract", "retry_adaptive", "retry_alignment"}` | ERROR | every summary |
| `model` is non-empty string | ERROR | every summary |
| `converged` is bool | ERROR | every summary |
| `total_iterations_executed` == `len(trajectory)` | ERROR | every summary |
| `trajectory` is list with len >= 1 | ERROR | every summary |
| `trajectory_dynamics` is dict with key `pattern` | ERROR | every summary |
| `trajectory_dynamics["pattern"]` is in allowed regime set (§7) | WARNING | reclassify as UNKNOWN if not |
| `leg_true` is bool for every failed attempt where evaluator ran | WARNING | treat None as False |
| No summary mixes multiple models | ERROR | within each file |
| Attempt indices are contiguous 0..N-1 | WARNING | reindex if not |
| `classifier_failure_type` is in FAILURE_TYPE_SET for every attempt | WARNING | treat invalid as UNKNOWN |

---

## 5. Run-Level Derived Metrics

Each summary record produces one row in the run-level table. Formulas below.

### ever_leg_true

```
ever_leg_true = any(e["leg_true"] for e in trajectory if not e["pass"])
```

Type: bool. True if at least one failed attempt in the trajectory is a LEG_true event.

### leg_true_count

```
leg_true_count = sum(1 for e in trajectory if e.get("leg_true"))
```

Type: int. Count of LEG_true events in the trajectory.

### failed_attempt_count

```
failed_attempt_count = sum(1 for e in trajectory if not e["pass"])
```

### leg_true_rate_within_run

```
leg_true_rate_within_run = leg_true_count / failed_attempt_count
    if failed_attempt_count > 0 else None
```

Type: float or None.

### leg_true_persistence

```
leg_true_persistence = max length of consecutive leg_true==True in trajectory
```

Computed by scanning the trajectory for the longest run of consecutive entries where `leg_true == True` and `pass == False`. If no LEG_true events, value is 0.

### first_leg_true_attempt

```
first_leg_true_attempt = min(e["attempt"] for e in trajectory if e.get("leg_true"))
    if ever_leg_true else None
```

Type: int or None.

### leg_true_to_success

```
leg_true_to_success = any(
    trajectory[i]["leg_true"] and trajectory[i+1]["pass"]
    for i in range(len(trajectory) - 1)
)
```

Type: bool. True if any LEG_true event is immediately followed by a passing attempt.

### leg_coupling_count

```
leg_coupling_count = sum(1 for e in trajectory if e.get("leg_coupling"))
```

Type: int. 0 for non-alignment conditions (all entries have `leg_coupling = None`).

### leg_execution_count

```
leg_execution_count = sum(1 for e in trajectory if e.get("leg_execution"))
```

### dominant_leg_subtype

Only computed for alignment conditions where `leg_true_count > 0`:

```
if leg_coupling_count > leg_execution_count:
    dominant_leg_subtype = "coupling"
elif leg_execution_count > leg_coupling_count:
    dominant_leg_subtype = "execution"
elif leg_coupling_count == leg_execution_count and leg_coupling_count > 0:
    dominant_leg_subtype = "mixed"
else:
    dominant_leg_subtype = "none"
```

For non-alignment conditions: `dominant_leg_subtype = None`.

### alignment_score_mean

```
alignment_score_mean = mean(e["alignment_step_coverage"]
    for e in trajectory if e.get("alignment_step_coverage") is not None)
```

None if no alignment data present.

### regime

```
regime = trajectory_dynamics["pattern"]
```

Consumed from summary, not recomputed.

---

## 6. Attempt-Level Derived Metrics

Each attempt in the trajectory produces one row in the attempt-level table.

### attempt_state

Each attempt is assigned exactly one state label from the set defined in §8.

Computed as:
```
if attempt["pass"]:
    state = "SUCCESS"
elif attempt.get("leg_true") and attempt.get("leg_coupling"):
    state = "LEG_COUPLING"
elif attempt.get("leg_true") and attempt.get("leg_execution"):
    state = "LEG_EXECUTION"
elif attempt.get("leg_true"):
    state = "LEG_TRUE_UNTYPED"  # non-alignment condition, no subtype info
elif not attempt["pass"]:
    state = "FAILURE_NO_LEG"
```

### Fields emitted per attempt row

- case_id, model, condition, run_id (derived from case_id + model + condition)
- attempt_index
- pass
- score
- attempt_state
- leg_true
- leg_coupling (or None)
- leg_execution (or None)
- classifier_failure_type
- alignment_success (or None)
- alignment_step_coverage (or None)

All attempts are included (both failed and passing).

---

## 7. Regime Definitions

The script consumes regime labels from the `trajectory_dynamics["pattern"]` field. It does NOT recompute regimes.

### Allowed regime labels

```
ALLOWED_REGIMES = {
    "single_shot",
    "MONOTONIC_FIX",
    "OSCILLATING_FIX",
    "OSCILLATION",
    "DIVERGENCE",
    "STAGNATION",
    "UNCLASSIFIED",
}
```

If a summary has a regime label not in this set, the script logs a WARNING and maps it to `"UNKNOWN"`.

### Regime grouping for analysis

For analyses that require coarser grouping (e.g., small cell sizes), the script uses:

| Group | Contains |
|---|---|
| success | single_shot, MONOTONIC_FIX, OSCILLATING_FIX |
| stagnation | STAGNATION |
| divergence | DIVERGENCE |
| oscillation | OSCILLATION |
| other | UNCLASSIFIED, UNKNOWN |

This mapping is a constant in the script, not an argument.

---

## 8. Transition State Definitions

### State space

```
TRANSITION_STATES = {
    "SUCCESS",
    "FAILURE_NO_LEG",
    "LEG_TRUE_UNTYPED",    # LEG_true on non-alignment condition
    "LEG_COUPLING",        # LEG_true + not aligned (alignment condition only)
    "LEG_EXECUTION",       # LEG_true + aligned (alignment condition only)
}
```

### Assignment rule

Each attempt maps to exactly one state (defined in §6 `attempt_state`).

### Transition counting

A transition is a pair `(state_k, state_{k+1})` for consecutive attempts in the same trajectory.

- Self-transitions count (e.g., `LEG_COUPLING → LEG_COUPLING`).
- The final attempt has no outgoing transition.
- Transitions are counted per-run, then aggregated across runs.

### Transition matrix

A 5×5 matrix where `M[i][j]` = count of transitions from state i to state j, aggregated across all runs matching a filter (model, condition, regime, etc.).

Row-normalized version: `P[i][j] = M[i][j] / sum(M[i])` gives transition probabilities.

---

## 9. Core Analyses

### A. Regime × LEG_true Prevalence

For each regime (or regime group):

| Metric | Definition |
|---|---|
| run_count | number of runs with this regime |
| ever_leg_true_rate | fraction of runs where ever_leg_true == True |
| mean_leg_true_count | mean of leg_true_count across runs |
| mean_leg_true_persistence | mean of leg_true_persistence across runs |
| convergence_rate | fraction of runs where converged == True |

Stratified by: model, condition, difficulty (optional).

### B. Regime Enrichment

For each regime R:

```
P(ever_leg_true | regime == R) vs P(ever_leg_true | regime != R)
```

Report both rates and the ratio. Flag regimes where the ratio > 1.5 or < 0.67 as "enriched" or "depleted."

### C. Subtype Decomposition Within LEG_true

Among runs with `ever_leg_true == True` AND `condition == "retry_alignment"`:

For each regime:
- fraction where `dominant_leg_subtype == "coupling"`
- fraction where `dominant_leg_subtype == "execution"`
- fraction where `dominant_leg_subtype == "mixed"`

### D. Intervention Comparison

Compare `retry_no_contract` vs `retry_alignment` (or any pair of conditions):

| Metric | Definition |
|---|---|
| ever_leg_true_rate | per condition |
| mean_leg_true_persistence | per condition |
| dominant_subtype distribution | alignment only |
| regime distribution | per condition |
| convergence_rate | per condition |

Stratified by difficulty level.

### E. Transition Analysis

Build transition matrix for:
1. All runs
2. Runs where `ever_leg_true == True`
3. Per-regime subsets (if cell sizes allow)

Report:
- Raw count matrix
- Row-normalized probability matrix
- Most common transition from each LEG state
- Self-transition rate for each LEG state (persistence signal)

---

## 10. Statistical Tests

### A. Regime enrichment: Fisher's exact test

For each regime R:
- 2×2 table: (regime R / not R) × (ever_leg_true / not)
- Fisher's exact test, two-sided
- Report: odds ratio, p-value
- If any cell < 5: report "small sample" flag, still compute but do not claim significance

### B. Intervention comparison: Proportion z-test

For `ever_leg_true_rate` between two conditions:
- Two-proportion z-test
- Report: z-statistic, p-value, 95% CI for difference
- If either group has < 10 runs: flag "underpowered", report descriptive stats only

### C. Subtype distribution: Chi-square test

Among LEG_true runs on alignment condition:
- Chi-square test of (coupling / execution / mixed) distribution across regimes
- If expected cell count < 5: use Fisher's exact test instead
- Report: test statistic, p-value, Cramér's V

### D. Transition matrix: No test

Transition matrices are reported descriptively. No statistical test applied. The matrix is the analysis artifact itself.

### General rules

- All tests are two-sided.
- Significance level: α = 0.05.
- Multiple comparisons: if more than 5 tests on the same table, apply Bonferroni correction and report both raw and adjusted p-values.
- If total runs < 30 for any analysis, print a warning: "insufficient sample size for reliable inference."

---

## 11. Output Tables

### Table 1: `regime_summary.csv`

One row per (model, condition, regime).

| Column | Type |
|---|---|
| model | str |
| condition | str |
| regime | str |
| regime_group | str |
| run_count | int |
| convergence_rate | float |
| ever_leg_true_rate | float |
| mean_leg_true_count | float |
| mean_leg_true_persistence | float |
| mean_leg_true_rate_within_run | float |

### Table 2: `regime_leg_enrichment.csv`

One row per (model, regime).

| Column | Type |
|---|---|
| model | str |
| regime | str |
| leg_true_rate_in_regime | float |
| leg_true_rate_outside_regime | float |
| enrichment_ratio | float |
| fisher_odds_ratio | float |
| fisher_p_value | float |
| small_sample_flag | bool |

### Table 3: `subtype_by_regime.csv`

One row per (model, regime). Alignment condition only.

| Column | Type |
|---|---|
| model | str |
| regime | str |
| leg_true_runs | int |
| coupling_fraction | float |
| execution_fraction | float |
| mixed_fraction | float |

### Table 4: `condition_comparison.csv`

One row per (model, difficulty, metric).

| Column | Type |
|---|---|
| model | str |
| difficulty | str |
| metric | str |
| retry_no_contract_value | float |
| retry_alignment_value | float |
| delta | float |
| p_value | float\|None |

### Table 5: `transition_matrix.csv`

One row per (model, condition, from_state, to_state).

| Column | Type |
|---|---|
| model | str |
| condition | str |
| from_state | str |
| to_state | str |
| count | int |
| probability | float |

---

## 12. Output Figures

The script emits figure-ready CSV files. It does NOT render plots.

### Figure 1 spec: LEG_true rate by regime

- Data file: `regime_summary.csv`
- x-axis: regime (categorical)
- y-axis: ever_leg_true_rate
- Grouping: model (color/hue)
- Facet: condition (optional)

### Figure 2 spec: Coupling vs execution within LEG_true

- Data file: `subtype_by_regime.csv`
- x-axis: regime
- y-axis: stacked bar (coupling_fraction, execution_fraction, mixed_fraction)
- Filter: alignment condition only

### Figure 3 spec: Transition heatmap

- Data file: `transition_matrix.csv`
- x-axis: to_state
- y-axis: from_state
- Cell value: probability
- One heatmap per (model, condition)

---

## 13. Output Files / Artifacts

All outputs written to `--output-dir`.

| File | Format | Description |
|---|---|---|
| `regime_summary.csv` | CSV | Table 1 |
| `regime_leg_enrichment.csv` | CSV | Table 2 |
| `subtype_by_regime.csv` | CSV | Table 3 |
| `condition_comparison.csv` | CSV | Table 4 |
| `transition_matrix.csv` | CSV | Table 5 |
| `analysis_summary.json` | JSON | Top-level stats: total runs, models, conditions, warnings |
| `warnings.txt` | text | All validation warnings and skipped runs |

---

## 14. Script CLI Interface

```
python scripts/leg_regime_analysis.py \
    --input logs/gpt-4o-mini_20260324_*.jsonl logs/gpt-4.1-nano_20260324_*.jsonl \
    --cases cases_v2.json \
    --output-dir analysis/leg_regime/ \
    [--models gpt-4o-mini,gpt-4.1-nano] \
    [--conditions retry_no_contract,retry_alignment] \
    [--difficulty A,B,C,D] \
    [--min-runs-per-cell 5] \
    [--strict]
```

| Argument | Required | Default | Description |
|---|---|---|---|
| `--input` | yes | — | One or more JSONL log file paths (glob supported) |
| `--cases` | yes | — | Path to cases_v2.json for case metadata |
| `--output-dir` | yes | — | Directory for all output files (created if not exists) |
| `--models` | no | all found | Comma-separated model filter |
| `--conditions` | no | all retry conditions | Comma-separated condition filter |
| `--difficulty` | no | all | Comma-separated difficulty filter (A,B,C,D) |
| `--min-runs-per-cell` | no | 5 | Minimum runs per cell for statistical tests |
| `--strict` | no | false | If set, exit on any WARNING (not just ERROR) |

---

## 15. Failure Modes / Edge Cases

| Situation | Behavior |
|---|---|
| Summary missing `trajectory` key | Skip run, log warning, count in `warnings.txt` |
| Summary missing `trajectory_dynamics` | Skip run, log warning |
| Summary has `leg_rate_true == None` (evaluator not run) | Include in regime analysis, exclude from LEG cross-tabs, log note |
| Attempt missing `leg_true` | Treat as False, log warning |
| Attempt `leg_coupling` is None on alignment condition | Log warning, exclude from subtype analysis for that attempt |
| Non-alignment condition missing `leg_coupling`/`leg_execution` | Expected, no warning, subtype columns = None |
| Unknown regime label | Map to "UNKNOWN", log warning |
| Run with 0 failed attempts | ever_leg_true = False, leg_true_count = 0, leg_true_rate_within_run = None |
| Run with all evaluator parse failures | ever_leg_true = False (all leg_true = False), log warning |
| Cell with < `--min-runs-per-cell` runs | Emit row with values but add `underpowered=True` column, skip stat test |
| Inconsistent attempt numbering | Reindex by position, log warning |
| Mixed models in one file | Script handles multiple models per file (groups by model field) |
| No runs match filter | Exit with error "no matching runs found" |
| Empty trajectory array | Skip run, log warning |

---

## 16. Implementation Plan

### Phase 1: Loader + Validator

- Read JSONL files, extract summary records
- Read cases_v2.json, build case metadata lookup
- Run all validation checks from §4
- Output: validated list of summary dicts, warnings log

Test: load one smoke-test log file, verify all checks pass, print run count.

### Phase 2: Run-Level Table

- Compute all §5 metrics for each summary
- Build `regime_summary.csv` data
- Write `regime_summary.csv`

Test: verify row count = number of summaries. Spot-check one run's derived metrics manually against the log.

### Phase 3: Attempt-Level Table + Transitions

- Compute §6 attempt_state for each attempt
- Build transition counts (§8)
- Write `transition_matrix.csv`

Test: verify total transitions = sum of (trajectory_length - 1) across all runs. Verify self-transition counts are plausible.

### Phase 4: Enrichment + Subtype + Comparison

- Compute §9A-D analyses
- Run §10 statistical tests
- Write `regime_leg_enrichment.csv`, `subtype_by_regime.csv`, `condition_comparison.csv`

Test: verify enrichment ratios are > 0. Verify p-values are in [0, 1]. Verify subtype fractions sum to ≤ 1.0.

### Phase 5: Summary + Smoke Test

- Write `analysis_summary.json` and `warnings.txt`
- Run on actual ablation logs
- Manually verify 3-5 rows against raw log data
- Verify all output files are non-empty and well-formed

Test: full end-to-end on real data. Compare a few values to manual computation.
