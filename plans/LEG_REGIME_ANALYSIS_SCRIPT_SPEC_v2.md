# LEG_true × Trajectory Regime Analysis Script Spec (v2)

**Date:** 2026-03-24
**Script:** `scripts/leg_regime_analysis.py`
**Depends on:** LEG Evaluation Module v7, retry_harness.py trajectory logging
**Supersedes:** LEG_REGIME_ANALYSIS_SCRIPT_SPEC.md

---

## 1. Scope and Purpose

### What this script answers

1. Is LEG_true enriched in specific trajectory regimes?
2. When LEG_true occurs, is it predominantly coupling or execution failure?
3. Does this subtype composition vary by regime?
4. Does `retry_alignment` change regime distribution or LEG_true rate within regimes?
5. What are the dominant attempt-to-attempt transitions when LEG_true is present?

### What this script does NOT answer

- Whether LEG_true detection is accurate (evaluator module's job)
- What causes LEG (hypothesis experiments' job)
- How to improve model performance (descriptive, not prescriptive)

### Metric hierarchy

- **Primary:** `LEG_true` as defined in LEG Evaluation Module v7
- **Subtype:** `LEG_coupling`, `LEG_execution` (alignment condition only)
- **Diagnostic only:** `LEG_keyword` (separate column, never mixed into primary tables)
- **Alignment-conditioned analysis** uses `LEG_true`, not keyword LEG

### Three-valued LEG_true

LEG_true has three states in this analysis:
- `True` — evaluator ran, confirmed LEG
- `False` — evaluator ran, not LEG
- `None` — evaluator did not run

`None` is never treated as `False`. Runs with `None` are excluded from all LEG-based analyses and included only in non-LEG analyses (regime distribution, convergence rate).

---

## 2. Input Sources

### Primary source of truth

Per-run metadata JSONL files produced by `retry_harness.py`. Each file contains interleaved per-iteration records and summary records.

Summary records identified by: `record["iteration"] == "summary"`.
Per-iteration records identified by: `record["iteration"]` is an integer.

### File discovery

The script takes one or more JSONL file paths as input via `--input`. No automatic discovery.

### What the script reads

From each summary record:
- Run-level fields (case_id, condition, model, converged, total_iterations_executed)
- Trajectory array (list of per-attempt dicts)
- Trajectory dynamics (`trajectory_dynamics["pattern"]`)
- Failure sequence, failure persistence

From each per-attempt entry within the trajectory:
- pass, score
- leg_true, leg_coupling, leg_execution
- leg_keyword_only
- classifier_failure_type
- llm_eval_blind_verdict, llm_eval_blind_type
- alignment_success, alignment_step_coverage

### Case metadata

The script reads `cases_v2.json` (path via `--cases`) for:
- difficulty (A, B, C, D)
- family
- failure_mode

---

## 3. Required Input Fields

### Summary-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `case_id` | str | required | |
| `condition` | str | required | must be known retry condition |
| `model` | str | required | |
| `converged` | bool | required | |
| `total_iterations_executed` | int | required | |
| `trajectory` | list[dict] | required | len >= 1 |
| `trajectory_dynamics` | dict | required | must contain `pattern` |
| `failure_regime` | str | required | |
| `failure_persistence` | dict | optional | |
| `failure_sequence` | list[str] | optional | |
| `leg_rate_true` | float\|None | optional | None if evaluator not run |
| `leg_rate_keyword` | float | optional | |
| `evaluator_bias` | dict\|None | optional | |

### Per-attempt fields

| Field | Type | Required | Scope |
|---|---|---|---|
| `pass` | bool | required | all |
| `score` | float | required | all |
| `attempt` | int | required | all (0-indexed) |
| `leg_true` | bool\|None | required | None if evaluator did not run for this attempt |
| `leg_keyword_only` | bool | optional | diagnostic |
| `leg_coupling` | bool\|None | alignment-only | None for non-alignment conditions |
| `leg_execution` | bool\|None | alignment-only | None for non-alignment conditions |
| `classifier_failure_type` | str | required | |
| `llm_eval_blind_verdict` | str\|None | required | None if evaluator not run |
| `llm_eval_blind_type` | str\|None | required | None if evaluator not run |
| `alignment_success` | bool\|None | alignment-only | |
| `alignment_step_coverage` | float\|None | alignment-only | |

### Missing field behavior

| Situation | Behavior |
|---|---|
| Summary missing `trajectory` | Skip run, log warning |
| Summary missing `trajectory_dynamics` | Skip run, log warning |
| `leg_true` is None on an attempt | Preserve as None. Do NOT default to False. Exclude from LEG metrics. |
| `leg_true` missing entirely from attempt dict | Treat as None (evaluator not run). Log warning. |
| `leg_coupling`/`leg_execution` None on alignment condition | Log warning, exclude from subtype analysis for that attempt |
| `leg_coupling`/`leg_execution` None on non-alignment condition | Expected, no warning |

---

## 4. Validation Checks Before Analysis

Checks run on all loaded data before any statistics. ERROR = exit. WARNING = log and continue.

| Check | Severity | Rule |
|---|---|---|
| `case_id` non-empty string | ERROR | every summary |
| `condition` in allowed set | ERROR | `{"retry_no_contract", "retry_with_contract", "retry_adaptive", "retry_alignment"}` |
| `model` non-empty string | ERROR | every summary |
| `converged` is bool | ERROR | every summary |
| `total_iterations_executed` == `len(trajectory)` | ERROR | every summary |
| `trajectory` is list with len >= 1 | ERROR | every summary |
| `trajectory_dynamics` is dict with key `pattern` | ERROR | every summary |
| `trajectory_dynamics["pattern"]` in allowed regime set (§7) | WARNING | normalize if not |
| `leg_true` is bool or None for every attempt | WARNING | treat other types as None |
| No summary mixes multiple models within one run | ERROR | per summary |
| Attempt positions contiguous 0..N-1 | WARNING | reindex by position if not |
| `classifier_failure_type` in FAILURE_TYPE_SET | WARNING | treat invalid as UNKNOWN |
| `pass` is bool for every attempt | ERROR | |
| `alignment_success` is bool or None | WARNING | |

---

## 5. Run-Level Derived Metrics

### evaluator_enabled

```
evaluator_enabled = any(
    e.get("llm_eval_blind_verdict") is not None
    for e in trajectory
)
```

Type: bool. True if the LLM evaluator ran on at least one attempt in this trajectory. Runs where `evaluator_enabled == False` are excluded from ALL LEG-based analyses. They are included in regime-only analyses (convergence rate, regime distribution).

### failed_attempt_count

```
failed_attempt_count = sum(1 for e in trajectory if not e["pass"])
```

### evaluated_failed_count

```
evaluated_failed_count = sum(1 for e in trajectory
                             if not e["pass"] and e.get("leg_true") is not None)
```

Count of failed attempts where the evaluator actually ran (leg_true is True or False, not None).

### ever_leg_true

```
ever_leg_true = any(
    e.get("leg_true") is True
    for e in trajectory
    if not e["pass"]
)
```

Type: bool. Only considers failed attempts. Only considers attempts where leg_true is explicitly True (not None).

Defined only when `evaluator_enabled == True`. Set to None otherwise.

### leg_true_count

```
leg_true_count = sum(1 for e in trajectory
                     if not e["pass"] and e.get("leg_true") is True)
```

Type: int. Counts only failed attempts with leg_true == True.

### leg_true_rate_within_run

```
leg_true_rate_within_run = leg_true_count / evaluated_failed_count
    if evaluated_failed_count > 0 else None
```

Type: float or None. Denominator is evaluated failed attempts (not all failed attempts).

### leg_true_persistence

Longest consecutive streak of attempts where `not e["pass"] and e.get("leg_true") is True`:

```
max_streak = 0
current = 0
for e in trajectory:
    if not e["pass"] and e.get("leg_true") is True:
        current += 1
        max_streak = max(max_streak, current)
    else:
        current = 0
leg_true_persistence = max_streak
```

### first_leg_true_attempt

```
first_leg_true_attempt = min(
    e["attempt"] for e in trajectory
    if not e["pass"] and e.get("leg_true") is True
) if ever_leg_true else None
```

### leg_true_to_success

```
leg_true_to_success = any(
    (not trajectory[i]["pass"])
    and trajectory[i].get("leg_true") is True
    and trajectory[i+1]["pass"]
    for i in range(len(trajectory) - 1)
)
```

### leg_coupling_count

```
leg_coupling_count = sum(1 for e in trajectory
                         if not e["pass"] and e.get("leg_coupling") is True)
```

### leg_execution_count

```
leg_execution_count = sum(1 for e in trajectory
                          if not e["pass"] and e.get("leg_execution") is True)
```

### dominant_leg_subtype

Only for alignment conditions where `leg_true_count > 0`:

```
if leg_coupling_count > leg_execution_count:
    "coupling"
elif leg_execution_count > leg_coupling_count:
    "execution"
elif leg_coupling_count == leg_execution_count and leg_coupling_count > 0:
    "mixed"
else:
    "none"
```

For non-alignment conditions: None.

### alignment_score_mean, alignment_score_std, alignment_score_min, alignment_score_max

```
scores = [e["alignment_step_coverage"] for e in trajectory
          if e.get("alignment_step_coverage") is not None]

alignment_score_mean = mean(scores) if scores else None
alignment_score_std = std(scores) if len(scores) >= 2 else None
alignment_score_min = min(scores) if scores else None
alignment_score_max = max(scores) if scores else None
```

### regime

```
regime = _normalize_regime(trajectory_dynamics["pattern"])
```

Consumed from summary, not recomputed. Normalized per §7.

---

## 6. Attempt-Level Derived Metrics

Each attempt produces one row. All attempts included (failed and passing).

### attempt_state

Computed from attempt fields, not from stored `leg_coupling`/`leg_execution` flags. This ensures consistency with the evaluation module definitions.

```
if attempt["pass"]:
    state = "SUCCESS"
elif attempt.get("leg_true") is not True:
    # leg_true is False or None
    state = "FAILURE_NO_LEG"
else:
    # leg_true is True
    if attempt.get("alignment_success") is True:
        state = "LEG_EXECUTION"
    elif attempt.get("alignment_success") is False:
        state = "LEG_COUPLING"
    else:
        # alignment_success is None (non-alignment condition)
        state = "LEG_TRUE_UNTYPED"
```

Note: `attempt_state` is derived from `pass`, `leg_true`, and `alignment_success`. It does NOT read `leg_coupling` or `leg_execution` directly, ensuring it is computed the same way the evaluation module defines those subtypes.

### Fields emitted per attempt row

| Field | Source |
|---|---|
| case_id | summary |
| model | summary |
| condition | summary |
| run_id | f"{case_id}__{model}__{condition}" |
| attempt_index | attempt["attempt"] |
| pass | attempt |
| score | attempt |
| attempt_state | computed (above) |
| leg_true | attempt (True/False/None) |
| leg_keyword_only | attempt |
| classifier_failure_type | attempt |
| alignment_success | attempt (or None) |
| alignment_step_coverage | attempt (or None) |

---

## 7. Regime Definitions

### Regime normalization

The script applies a deterministic normalization mapping before any analysis:

```python
_REGIME_NORMALIZE = {
    "single_shot": "SINGLE_SHOT",
    "MONOTONIC_FIX": "MONOTONIC_FIX",
    "OSCILLATING_FIX": "OSCILLATING_FIX",
    "OSCILLATION": "OSCILLATION",
    "DIVERGENCE": "DIVERGENCE",
    "STAGNATION": "STAGNATION",
    "UNCLASSIFIED": "UNCLASSIFIED",
    # lowercase variants
    "monotonic_fix": "MONOTONIC_FIX",
    "oscillating_fix": "OSCILLATING_FIX",
    "oscillation": "OSCILLATION",
    "divergence": "DIVERGENCE",
    "stagnation": "STAGNATION",
    "unclassified": "UNCLASSIFIED",
    "single_shot_success": "SINGLE_SHOT",
}

def _normalize_regime(raw):
    return _REGIME_NORMALIZE.get(raw, "UNKNOWN")
```

### Allowed normalized regime labels

```
ALLOWED_REGIMES = {
    "SINGLE_SHOT",
    "MONOTONIC_FIX",
    "OSCILLATING_FIX",
    "OSCILLATION",
    "DIVERGENCE",
    "STAGNATION",
    "UNCLASSIFIED",
    "UNKNOWN",
}
```

### Regime grouping for coarse analysis

| Group | Contains |
|---|---|
| converged | SINGLE_SHOT, MONOTONIC_FIX, OSCILLATING_FIX |
| stagnation | STAGNATION |
| divergence | DIVERGENCE |
| oscillation | OSCILLATION |
| other | UNCLASSIFIED, UNKNOWN |

This mapping is a constant, not an argument.

---

## 8. Transition State Definitions

### State space

```
TRANSITION_STATES = (
    "SUCCESS",
    "FAILURE_NO_LEG",
    "LEG_TRUE_UNTYPED",
    "LEG_COUPLING",
    "LEG_EXECUTION",
)
```

### Assignment rule

Each attempt maps to exactly one state using the `attempt_state` formula from §6. The state is derived from `pass`, `leg_true`, and `alignment_success` — not from stored subtype flags.

### Transition counting

A transition is a pair `(state_k, state_{k+1})` for consecutive attempts in the same trajectory.

- Self-transitions count (e.g., `LEG_COUPLING → LEG_COUPLING`)
- The final attempt has no outgoing transition
- Transitions are counted per-run, then aggregated across runs matching a filter

### Transition matrix

A 5×5 matrix where `M[i][j]` = count of transitions from state i to state j.

Row-normalized version: `P[i][j] = M[i][j] / sum(M[i])` if `sum(M[i]) > 0` else 0.

Both raw counts and row-normalized probabilities are written to output.

### Filtering for LEG analyses

Transition analysis involving LEG states uses only `evaluator_enabled` runs. Runs without evaluator data are excluded from the transition matrix.

---

## 9. Core Analyses

### A. Regime × LEG_true Prevalence

For each (model, condition, regime):

| Metric | Definition | Source |
|---|---|---|
| run_count | total runs | all runs |
| evaluator_run_count | runs with evaluator_enabled | evaluator runs only |
| convergence_rate | converged / run_count | all runs |
| ever_leg_true_rate | ever_leg_true / evaluator_run_count | evaluator runs only |
| mean_leg_true_count | mean(leg_true_count) | evaluator runs only |
| mean_leg_true_persistence | mean(leg_true_persistence) | evaluator runs only |
| mean_leg_true_rate_within_run | mean(leg_true_rate_within_run) excluding None | evaluator runs only |

### B. Regime Enrichment

For each (model, regime R):

```
P(ever_leg_true | regime == R) vs P(ever_leg_true | regime != R)
```

Only over evaluator_enabled runs. Report both rates, ratio, and Fisher exact test result.

Flag: enriched (ratio > 1.5), depleted (ratio < 0.67), neutral (between).

### C. Subtype Decomposition Within LEG_true

Among evaluator_enabled runs with `ever_leg_true == True` AND `condition == "retry_alignment"`:

For each regime:
- coupling_fraction = leg_coupling_count / (leg_coupling_count + leg_execution_count) if denominator > 0
- execution_fraction = leg_execution_count / (leg_coupling_count + leg_execution_count)
- mixed_fraction = 1 - coupling_fraction - execution_fraction (if dominant_leg_subtype == "mixed")

### D. Intervention Comparison

Compare conditions (e.g., `retry_no_contract` vs `retry_alignment`):

| Metric | Scope |
|---|---|
| ever_leg_true_rate | evaluator runs |
| mean_leg_true_persistence | evaluator runs |
| dominant_subtype distribution | alignment only |
| regime distribution | all runs |
| convergence_rate | all runs |

Stratified by difficulty level.

### E. Transition Analysis

Build transition matrix for subsets:
1. All evaluator_enabled runs
2. Evaluator_enabled runs where `ever_leg_true == True`
3. Per-regime subsets (if cell sizes allow)

Report:
- Raw count matrix (5×5)
- Row-normalized probability matrix (5×5)
- Most common outgoing transition from each LEG state
- Self-transition rate for each LEG state

---

## 10. Statistical Tests

### A. Regime enrichment: Fisher's exact test

2×2 table: (regime R / not R) × (ever_leg_true / not).
Only over evaluator_enabled runs.
Report: odds ratio, p-value.
If any cell < 5: flag "small_sample", still compute.

### B. Intervention comparison: Proportion z-test

For `ever_leg_true_rate` between two conditions.
Only over evaluator_enabled runs.
Report: z-statistic, p-value, 95% CI for difference.
If either group < 10 runs: flag "underpowered", descriptive only.

### C. Subtype distribution: Chi-square test

Among LEG_true evaluator-enabled runs on alignment condition.
If expected cell < 5: Fisher's exact instead.
Report: test statistic, p-value, Cramér's V.

### D. Transition matrix: No test

Descriptive only. The matrix is the artifact.

### General rules

- Two-sided tests.
- α = 0.05.
- If > 5 tests on same table: Bonferroni correction; report raw and adjusted p-values.
- If total evaluator_enabled runs < 30 for any analysis: warning "insufficient sample size."

---

## 11. Output Tables

### Table 1: `regime_summary.csv`

One row per (model, condition, regime).

| Column | Type | Description |
|---|---|---|
| model | str | |
| condition | str | |
| regime | str | normalized |
| regime_group | str | coarse group |
| run_count | int | all runs |
| evaluator_run_count | int | evaluator_enabled runs |
| convergence_rate | float | all runs |
| ever_leg_true_rate | float\|NA | evaluator runs, NA if evaluator_run_count == 0 |
| mean_leg_true_count | float\|NA | |
| mean_leg_true_persistence | float\|NA | |
| mean_leg_true_rate_within_run | float\|NA | |

### Table 2: `regime_leg_enrichment.csv`

One row per (model, regime).

| Column | Type |
|---|---|
| model | str |
| regime | str |
| leg_true_rate_in_regime | float |
| leg_true_rate_outside_regime | float |
| enrichment_ratio | float\|NA |
| fisher_odds_ratio | float |
| fisher_p_value | float |
| fisher_p_adjusted | float\|NA |
| small_sample_flag | bool |
| evaluator_runs_in_regime | int |
| evaluator_runs_outside | int |

### Table 3: `subtype_by_regime.csv`

One row per (model, regime). Alignment condition only.

| Column | Type |
|---|---|
| model | str |
| regime | str |
| leg_true_runs | int |
| coupling_count | int |
| execution_count | int |
| coupling_fraction | float |
| execution_fraction | float |

### Table 4: `condition_comparison.csv`

One row per (model, difficulty, metric).

| Column | Type |
|---|---|
| model | str |
| difficulty | str |
| metric | str |
| condition_a | str |
| condition_a_value | float |
| condition_b | str |
| condition_b_value | float |
| delta | float |
| p_value | float\|NA |
| underpowered | bool |

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

Both raw counts and row-normalized probabilities in the same table. `probability` = `count / sum(counts for same from_state)`.

---

## 12. Output Figures

The script emits figure-ready CSV files. It does NOT render plots.

### Figure 1: LEG_true rate by regime

- Data: `regime_summary.csv`
- x-axis: regime (categorical)
- y-axis: ever_leg_true_rate
- Grouping: model (color)
- Facet: condition (optional)
- Note: only evaluator-enabled runs

### Figure 2: Coupling vs execution within LEG_true

- Data: `subtype_by_regime.csv`
- x-axis: regime
- y-axis: stacked bar (coupling_fraction, execution_fraction)
- Filter: alignment condition, evaluator-enabled runs with LEG_true

### Figure 3: Transition heatmap

- Data: `transition_matrix.csv`
- x-axis: to_state
- y-axis: from_state
- Cell value: probability
- One heatmap per (model, condition)
- Filter: evaluator-enabled runs

---

## 13. Output Files / Artifacts

All written to `--output-dir`.

| File | Format | Description |
|---|---|---|
| `regime_summary.csv` | CSV | Table 1 |
| `regime_leg_enrichment.csv` | CSV | Table 2 |
| `subtype_by_regime.csv` | CSV | Table 3 |
| `condition_comparison.csv` | CSV | Table 4 |
| `transition_matrix.csv` | CSV | Table 5 |
| `analysis_summary.json` | JSON | Top-level stats: total runs, evaluator-enabled runs, models, conditions, warnings count |
| `warnings.txt` | text | All validation warnings and skipped runs |

---

## 14. Script CLI Interface

```
python scripts/leg_regime_analysis.py \
    --input logs/gpt-4o-mini_*.jsonl logs/gpt-4.1-nano_*.jsonl \
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
| `--cases` | yes | — | Path to cases_v2.json |
| `--output-dir` | yes | — | Directory for outputs (created if not exists) |
| `--models` | no | all found | Comma-separated model filter |
| `--conditions` | no | all retry conditions | Comma-separated condition filter |
| `--difficulty` | no | all | Comma-separated difficulty filter |
| `--min-runs-per-cell` | no | 5 | Minimum runs for statistical tests |
| `--strict` | no | false | Exit on WARNING (not just ERROR) |

---

## 15. Failure Modes / Edge Cases

| Situation | Behavior |
|---|---|
| Summary missing `trajectory` | Skip run, log warning |
| Summary missing `trajectory_dynamics` | Skip run, log warning |
| `leg_true` is None on an attempt | Preserve as None. Exclude from LEG counts and rates. Never treat as False. |
| `leg_true` missing from attempt dict | Treat as None (evaluator not run). Log warning. |
| All attempts in a run have `leg_true == None` | `evaluator_enabled = False`. Run excluded from LEG analyses. Included in regime-only. |
| `leg_coupling`/`leg_execution` None on alignment condition | Log warning. Attempt_state uses `alignment_success` directly (§6), not stored flags. |
| Non-alignment condition, subtype fields None | Expected. No warning. Subtype analysis skipped for this condition. |
| Unknown regime label after normalization | Mapped to "UNKNOWN". Log warning. |
| Run with 0 failed attempts | ever_leg_true = False (trivially), leg_true_count = 0, leg_true_rate_within_run = None |
| Run with all evaluator parse failures | leg_true is None for all attempts → evaluator_enabled may be True (verdict was attempted) but all leg_true are None. ever_leg_true = False (no True values). Log warning. |
| Cell with < `--min-runs-per-cell` evaluator runs | Emit row with values, add `underpowered=True`, skip stat test |
| Inconsistent attempt numbering | Reindex by position, log warning |
| No runs match filter | Exit with error |
| Empty trajectory | Skip run, log warning |
| Transition from attempt with leg_true=None | attempt_state = FAILURE_NO_LEG (None is not True). Transition counted normally. |

---

## 16. Implementation Plan

### Phase 1: Loader + Validator

- Read JSONL files, extract summary records
- Read cases_v2.json, build case metadata lookup
- Apply regime normalization (§7)
- Run all validation checks (§4)
- Classify runs as evaluator_enabled or not
- Output: validated list of summary dicts, warnings log

**Test:** Load one smoke-test log. Verify check count. Verify evaluator_enabled classification. Print run count and evaluator_enabled count.

### Phase 2: Run-Level Table

- Compute all §5 metrics for each summary
- Respect three-valued leg_true: None excluded from all LEG aggregations
- Build `regime_summary.csv` data
- Write `regime_summary.csv`

**Test:** Verify row count = unique (model, condition, regime) tuples. Spot-check one run's derived metrics manually. Verify ever_leg_true_rate denominators use evaluator_run_count, not run_count.

### Phase 3: Attempt-Level Table + Transitions

- Compute §6 attempt_state for each attempt using the formula (not stored flags)
- Build transition counts (§8)
- Write `transition_matrix.csv` with both counts and probabilities

**Test:** Verify total transitions = sum(trajectory_length - 1) across evaluator_enabled runs. Verify row probabilities sum to 1.0 (±rounding). Verify self-transitions are plausible.

### Phase 4: Enrichment + Subtype + Comparison

- Compute §9A-D analyses
- Filter LEG analyses to evaluator_enabled runs
- Run §10 statistical tests (with underpowered flags)
- Write `regime_leg_enrichment.csv`, `subtype_by_regime.csv`, `condition_comparison.csv`

**Test:** Verify enrichment ratios > 0. Verify p-values in [0, 1]. Verify subtype fractions sum to 1.0 within floating point tolerance. Verify condition_comparison uses evaluator_enabled runs for LEG metrics and all runs for regime metrics.

### Phase 5: Summary + Smoke Test

- Write `analysis_summary.json` and `warnings.txt`
- Run on actual ablation logs from the V2 experiment
- Manually verify 3-5 rows in each table against raw log data
- Check: no None values treated as False in any LEG column
- Check: evaluator_run_count <= run_count in every row

**Test:** Full end-to-end on real data. Compare a few values to manual computation from the JSONL.
