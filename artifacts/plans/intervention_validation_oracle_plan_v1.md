# Intervention Validation Under Oracle Labels — Plan v1

**Date**: 2026-04-01
**Goal**: Determine whether intervention effects (baseline → LEG → lean) are real execution improvements or artifacts, using oracle reasoning_truth labels.

## Data

**Oracle labels**: audits/oracle_eval_stage1/results.json — 500 samples, 467 judgable, 19 cases, 9 models, 3 conditions.

**Supplementary (for metrics not requiring oracle)**: merged_events.jsonl from all 12 ablation runs (27,956 events). Execution pass/fail and reconstruction status are already available here without oracle labels.

**Approach**: Use Stage 1 oracle data for all oracle-dependent analyses (reasoning shift, conditional execution, LEG decomposition). Use full logs for execution-only and reconstruction-only analyses that don't need oracle labels.

---

## 1. ANALYSIS PLAN

### Step 1: Recompute Metrics Under Oracle Labels (Stage 1 data)

For each condition (pooled across models and cases):
- A. Reasoning correctness: P(reasoning_truth == CORRECT)
- B. Execution success: P(execution_pass)
- C. Conditional execution: P(pass | reasoning_truth == CORRECT)
- D. Strict LEG: P(fail AND CORRECT)
- E. Soft LEG: P(fail AND CORRECT∪PARTIAL)

For the 2-3 cases with sufficient cell sizes (config_shadowing N≥30, early_return_a N≥16):
- Same metrics per condition

### Step 2: Intervention Effect Decomposition (Stage 1 data)

For each intervention pair (baseline→LEG, baseline→lean):

**Total effect** = Δ P(pass)

Decompose into:
- **Reasoning shift** = Δ P(CORRECT)
- **Execution improvement** = Δ P(pass | CORRECT) — the conditional change
- **Composition shift** = change in mix of CORRECT/PARTIAL/WRONG

The key identity:
```
P(pass) = P(pass|CORRECT)·P(CORRECT) + P(pass|PARTIAL)·P(PARTIAL) + P(pass|WRONG)·P(WRONG)
```

So:
```
Δ P(pass) = Δ[P(pass|CORRECT)·P(CORRECT)] + Δ[P(pass|PARTIAL)·P(PARTIAL)] + Δ[P(pass|WRONG)·P(WRONG)]
```

### Step 3: Core Validation — Restrict to CORRECT-Only (Stage 1 data)

**The decisive test**: Among ONLY rows where reasoning_truth == CORRECT:

P(pass | CORRECT, baseline) vs P(pass | CORRECT, lean) vs P(pass | CORRECT, LEG)

If improvement persists → TRUE execution improvement (the intervention helps models translate correct understanding into working code).

If improvement vanishes → effect was reasoning shift or artifact.

### Step 4: Lucky Fix Analysis (Stage 1 data)

P(pass AND WRONG) per condition.

Are interventions increasing or decreasing lucky fixes?

### Step 5: Model Regime Classification (Stage 1 data)

For each model, compute:
- P(CORRECT) — reasoning capability
- P(pass | CORRECT) — execution capability given correct reasoning

Classify:
- **Reasoning-limited**: P(CORRECT) < 0.5
- **Execution-limited**: P(CORRECT) ≥ 0.5 AND P(pass|CORRECT) < 0.7
- **Capable**: P(CORRECT) ≥ 0.5 AND P(pass|CORRECT) ≥ 0.7

Test whether interventions differentially help each regime.

### Step 6: Reconstruction Control (full logs, no oracle needed)

From merged_events.jsonl (27,956 events), compute:
- P(pass) strict vs P(pass) recon-only, per condition
- If strict ≠ recon-only by >5pp, reconstruction is a confound

This does NOT require oracle labels — it uses execution_pass and reconstruction_status from existing logs.

### Step 7: Case-Level Deep Dives (Stage 1 where feasible, full logs for execution)

For the strong-claim cases from the prior report:
- **invariant_partial_fail**: Stage 1 has 34 samples — compute reasoning_truth distribution per condition. Supplement with execution rates from full logs.
- **feature_flag_drift**: Stage 1 sample size. Same approach.
- **alias_config_c**: Same.
- **config_shadowing**: Stage 1 has 30+ samples — sufficient for per-condition analysis.

For cases with <10 samples in Stage 1: report oracle label distribution but flag as underpowered for intervention comparison.

---

## 2. METRIC DEFINITIONS

| Metric | Formula | Data Source |
|--------|---------|-------------|
| Reasoning correct rate | count(CORRECT) / count(judgable) | Stage 1 |
| Execution pass rate | count(pass) / count(all) | Stage 1 or full logs |
| Conditional pass rate | count(pass AND CORRECT) / count(CORRECT) | Stage 1 |
| Strict LEG rate | count(fail AND CORRECT) / count(judgable) | Stage 1 |
| Soft LEG rate | count(fail AND (CORRECT∪PARTIAL)) / count(judgable) | Stage 1 |
| Lucky fix rate | count(pass AND WRONG) / count(judgable) | Stage 1 |
| Reasoning shift | CORRECT_rate(treat) - CORRECT_rate(baseline) | Stage 1 |
| Execution improvement | cond_pass(treat) - cond_pass(baseline) | Stage 1 |
| Recon inflation | pass_rate(strict) - pass_rate(recon_only) | Full logs |

---

## 3. TABLE SCHEMAS

### Table 1: Pooled Intervention Effects

| Condition | N | CORRECT% | Pass% | Pass\|CORRECT | StrictLEG | SoftLEG | Lucky |
|-----------|---|----------|-------|---------------|-----------|---------|-------|

### Table 2: Decomposition

| Comparison | Δ Pass | Δ CORRECT | Δ Pass\|CORRECT | Reasoning Shift | Execution Shift |
|------------|--------|-----------|-----------------|-----------------|-----------------|
| base→LEG | | | | | |
| base→lean | | | | | |

### Table 3: Core Validation (CORRECT-only)

| Condition | N_correct | Pass\|CORRECT | 95% CI |
|-----------|-----------|---------------|--------|

### Table 4: Per-Model Regime

| Model | N | P(CORRECT) | P(Pass\|CORRECT) | Regime | Δ Pass(lean) | Δ CORRECT(lean) |
|-------|---|-----------|------------------|--------|-------------|-----------------|

### Table 5: Case Deep Dives

| Case | Condition | N | CORRECT | PARTIAL | WRONG | Pass | Pass\|CORRECT | LEG |
|------|-----------|---|---------|---------|-------|------|---------------|-----|

---

## 4. CASE-LEVEL VALIDATION STRATEGY

For each strong claim from the prior report, test TWO things:

### A. Does the pass rate improvement survive?
Compare P(pass) across conditions using Stage 1 data. If Stage 1 cell size <10, report full-log pass rates alongside with caveat.

### B. Does the improvement survive conditioning on CORRECT?
Among CORRECT-only samples, does P(pass|CORRECT) still improve? This is the definitive test.

**Possible outcomes per case:**

| Pass improves? | Pass\|CORRECT improves? | Interpretation |
|---------------|------------------------|----------------|
| YES | YES | TRUE execution improvement — intervention helps correct reasoners code better |
| YES | NO | Reasoning shift — intervention helps models reason better, not code better |
| YES | N/A (too few CORRECT) | Underpowered — report with caveat |
| NO | NO | No real effect — prior finding was classifier artifact |

---

## 5. STATISTICAL TESTING PLAN

### For pooled comparisons (N≥100 per condition):
- **Fisher exact test** on 2×2 tables (pass/fail × baseline/treatment)
- **Bootstrap 95% CIs** for rate differences (10,000 resamples)
- Report both p-value and CI width

### For per-case comparisons (N<30):
- Fisher exact test only (bootstrap unreliable at small N)
- Flag as "exploratory" if N<10

### For conditional comparisons (P(pass|CORRECT)):
- Fisher exact on the CORRECT-only subset
- Report effective N (number of CORRECT samples per condition)
- If effective N < 5 per condition: mark as UNDERPOWERED, do not claim significance

### Multiple comparison correction:
- Bonferroni across the number of (case, comparison) pairs tested
- Report both uncorrected and corrected p-values

---

## 6. EXPECTED FAILURE MODES

### 6.1 Small Cell Sizes
Stage 1 has ~2-9 samples per (case, model, condition) cell. Most per-case comparisons will be underpowered.

**Mitigation**: Pool across models for case-level analysis. Pool across cases for model-level analysis. Flag all comparisons with effective N < 10.

### 6.2 Oracle Evaluator Errors
The oracle evaluator itself may misclassify. Stage 1 validation showed reasonable label distribution but inter-rater reliability is untested.

**Mitigation**: Report results for both "strict" (CORRECT only) and "soft" (CORRECT + PARTIAL) to assess sensitivity to label boundary.

### 6.3 Stratified Sample Bias
The 500-sample stratified sample may not be representative of the full dataset.

**Mitigation**: Compare execution pass rates in Stage 1 sample vs full logs. If they diverge by >5pp, the sample is biased and results should be caveated.

### 6.4 Confounding by Case Difficulty
Interventions may help on easy cases and hurt on hard cases. Pooling across cases masks this.

**Mitigation**: Report case-level results alongside pooled results. Use the case difficulty field (A/B/C) as a stratification variable.

### 6.5 UNJUDGABLE Concentration
33/500 UNJUDGABLE samples are all from claude-3-haiku (parse failures). This model's intervention effects are unmeasurable.

**Mitigation**: Exclude claude-3-haiku from intervention analysis entirely. Report this exclusion.

---

## 7. IMPLEMENTATION PLAN

### Single script: scripts/run_intervention_validation.py

**Inputs**:
- audits/oracle_eval_stage1/results.json (oracle labels)
- All merged_events.jsonl files (for reconstruction control)

**Outputs**:
- audits/intervention_validation/analysis.md (formatted report with all tables)
- audits/intervention_validation/tables.json (machine-readable results)

**Functions** (~250 lines total):
- `load_oracle_results()` — load Stage 1 results
- `load_full_execution_data()` — load pass/recon from merged_events for recon control
- `compute_pooled_table()` — Table 1
- `compute_decomposition()` — Table 2
- `compute_correct_only()` — Table 3 (the decisive test)
- `compute_model_regimes()` — Table 4
- `compute_case_dives()` — Table 5
- `compute_recon_control()` — reconstruction filtering from full logs
- `fisher_exact()` — statistical tests
- `bootstrap_ci()` — confidence intervals
- `format_report()` — markdown output
- `main()`

**No oracle evaluator calls** — this script only analyzes existing results.

**No new dependencies** — uses scipy.stats.fisher_exact (already available).
