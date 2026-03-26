# Run Diagnostics: gpt-5.4-mini — Full Analysis

**Date:** 2026-03-25
**Run start:** 21:08 UTC
**Pipeline version:** Post-reconstruction-wiring fix + v2 test interface revert

---

## Glossary of Terms and Abbreviations

| Term | Full Name | Definition |
|------|-----------|------------|
| **BL** | Baseline | The control condition — model receives a plain prompt with no intervention |
| **LR** | LEG-Reduction | The experimental condition — model receives a structured prompt that asks it to plan, verify, and self-correct before producing code |
| **Pass** | Full Pass | Both reasoning AND code are correct. The model understood the bug AND produced a working fix. `pass = reasoning_correct AND code_correct` |
| **LEG** | Looks-good Error Gap | The model's reasoning correctly identifies the bug, but the code it produces is wrong. `LEG = reasoning_correct AND NOT code_correct`. This measures the gap between understanding and execution. |
| **Lucky Fix** | Lucky Fix | The model's reasoning is wrong (misidentifies the bug or gives vague reasoning), but the code it produces happens to be correct anyway. `lucky = NOT reasoning_correct AND code_correct` |
| **True Failure** | True Failure | Both reasoning and code are wrong. The model neither understood the bug nor fixed it. `true_failure = NOT reasoning_correct AND NOT code_correct` |
| **True Success** | True Success | Both reasoning and code are correct. Same as Pass. `true_success = reasoning_correct AND code_correct` |
| **Exec\|Reason** | Execution given Reasoning | Of the cases where the model reasoned correctly, what fraction also produced correct code? `P(code_correct \| reasoning_correct)`. Measures how well correct understanding translates to correct code. |
| **reasoning_correct** | Reasoning Correct | An independent LLM classifier judged whether the model's reasoning correctly identified the root cause of the bug. This is evaluated WITHOUT seeing execution results to prevent bias. |
| **code_correct** | Code Correct | The model's generated code was executed against test invariants and passed. This comes from `exec_evaluate` — actual code execution, not LLM judgment. Identical to `pass` in this pipeline. |
| **ran** | Code Executed | The generated code was successfully loaded and executed (no syntax errors, no assembly failures). `ran=True` does not mean the code is correct — just that it ran. |
| **Difficulty A** | Easy | Single-file cases with straightforward bugs |
| **Difficulty B** | Medium | May involve multiple files or more subtle bug patterns |
| **Difficulty C** | Hard | Complex multi-file cases, subtle interactions, harder to diagnose |
| **Difficulty L3** | Level 3 | Special high-complexity cases involving deep state reasoning |
| **Delta (Δ)** | Difference | The change from baseline to leg_reduction. E.g., `Δ pass = LR_pass - BL_pass`. Negative delta on pass rate means the intervention made things worse. Negative delta on LEG means the intervention reduced the error gap (intended effect). |
| **pp** | Percentage Points | Absolute difference between two percentages. E.g., 93% - 81% = 12pp |
| **n** | Sample Size | Number of evaluation events for that group |

---

## 1. Run Summary

| Property | Value |
|----------|-------|
| Model | gpt-5.4-mini |
| Cases file | cases_v2.json |
| Total cases | 58 |
| Conditions | baseline, leg_reduction |
| Trials launched | 8 (2 fully completed, 6 partially completed before run was stopped) |
| Total events | 790 |
| Baseline events | 395 |
| LEG-reduction events | 395 |
| Total passes | 690 / 790 (87.3%) |
| Total fails | 100 / 790 (12.7%) |
| Retries | Not applicable — both conditions are single-shot (1 LLM call per eval) |

**Note on sample sizes:** 12 of the 58 cases have fewer than 8 events per condition because they come from families with only 2-3 trials completed. These are flagged in the per-case table. All Level A/B cases with the `_a`, `_b`, `_c` suffix have the full 8 events per condition.

---

## 2. Core Metrics

### Definitions (repeated for clarity)

- **Pass rate** = fraction of evals where the model both understood the bug and produced a working fix
- **Reasoning accuracy** = fraction of evals where the LLM classifier judged the model's reasoning as correct
- **Code accuracy** = fraction of evals where the generated code passed execution tests (identical to pass rate in this pipeline because `pass = code_correct AND reasoning_correct` but `code_correct` is computed independently)
- **LEG rate** = fraction of evals where reasoning was correct but code was wrong — the "looks good but isn't" gap
- **Lucky fix rate** = fraction of evals where reasoning was wrong but code was correct — accidental fixes
- **True failure rate** = fraction of evals where both reasoning and code were wrong
- **Exec|Reason** = P(code_correct | reasoning_correct) — how often correct reasoning leads to correct code

### Results

| Metric | Baseline (BL) | LEG-Reduction (LR) | Delta (LR - BL) |
|--------|---------------|---------------------|------------------|
| **Pass rate** | 93.7% (370/395) | 81.0% (320/395) | **-12.7pp** |
| **Reasoning accuracy** | 90.4% (357/395) | 47.3% (187/395) | **-43.1pp** |
| **Code accuracy** | 93.7% (370/395) | 81.0% (320/395) | **-12.7pp** |
| **LEG rate** | 5.1% (20/395) | 6.8% (27/395) | +1.7pp |
| **Lucky fix rate** | 8.4% (33/395) | 40.5% (160/395) | **+32.1pp** |
| **True success** | 85.3% (337/395) | 40.5% (160/395) | -44.8pp |
| **True failure** | 1.3% (5/395) | 12.2% (48/395) | +10.9pp |
| **Exec\|Reason** | 94.4% (337/357) | 85.6% (160/187) | -8.8pp |

### Interpretation

The LEG-reduction intervention **did not improve pass rate** — it made it worse by 12.7pp. However, the story is more nuanced:

1. **Reasoning accuracy collapsed under LR** (90.4% → 47.3%). The structured prompt appears to make the LLM classifier judge reasoning as "incorrect" far more often. This could be a real effect (the structured format exposes weaker reasoning) or an artifact (the classifier is confused by the different response format).

2. **Lucky fix rate exploded** (8.4% → 40.5%). Under LR, 40% of correct code came with "wrong" reasoning. This is suspicious — see Section 8.

3. **LEG rate barely changed** (5.1% → 6.8%). The intervention did not meaningfully reduce the execution gap.

4. **Exec|Reason dropped** (94.4% → 85.6%). When reasoning IS correct under LR, code is less likely to be correct too.

> **⚠️ SUSPICIOUS: The massive drop in reasoning_correct under LR (90% → 47%) combined with the massive spike in lucky fixes (8% → 40%) suggests the LLM reasoning classifier may be miscalibrating on the leg_reduction response format. The model may be reasoning correctly but in a format the classifier doesn't recognize as correct. This is a measurement artifact, not necessarily a real effect.**

---

## 3. Metrics by Difficulty

### Definitions
- **A** = Easy (single-file, straightforward bugs) — 15 cases, 120 events per condition
- **B** = Medium (may involve multiple files, subtler patterns) — 15 cases, 120 events per condition
- **C** = Hard (complex interactions, multi-file, subtle) — 19 cases, 151 events per condition (some with <8 trials)
- **L3** = Level 3 (deep state reasoning) — 2 cases, 4 events per condition

### Baseline (BL)

| Difficulty | n | Pass Rate | LEG Rate | Lucky Rate | Interpretation |
|------------|---|-----------|----------|------------|----------------|
| **A** | 120 | **100.0%** | 0.0% | 1.7% | Model solves ALL easy cases perfectly |
| **B** | 120 | **94.2%** | 5.8% | 6.7% | Near-perfect; small LEG and lucky rates |
| **C** | 151 | **88.1%** | 8.6% | 14.6% | Harder; more LEG and more lucky fixes |
| **L3** | 4 | **100.0%** | 0.0% | 25.0% | Small sample; 1 of 4 was a lucky fix |

### LEG-Reduction (LR)

| Difficulty | n | Pass Rate | LEG Rate | Lucky Rate | Interpretation |
|------------|---|-----------|----------|------------|----------------|
| **A** | 120 | **91.7%** | 3.3% | 18.3% | Drop from 100% baseline; lucky fixes appearing |
| **B** | 120 | **86.7%** | 6.7% | 45.0% | Major lucky fix spike — nearly half of passes |
| **C** | 151 | **67.5%** | 9.9% | 53.6% | Significant drop; majority of passes are lucky |
| **L3** | 4 | **100.0%** | 0.0% | 75.0% | Small sample; 3 of 4 are lucky fixes |

### Key Finding

Under LR, lucky fix rate scales dramatically with difficulty: A=18%, B=45%, C=54%, L3=75%. This means harder cases are being "solved" with wrong reasoning far more often under the intervention.

> **⚠️ SUSPICIOUS: Lucky fix rates of 45-75% under LR strongly suggest the reasoning classifier is systematically misjudging the structured LR response format as "incorrect reasoning." The code quality only drops modestly (A: 100→92%, B: 94→87%, C: 88→68%) while reasoning_correct drops catastrophically. This asymmetry is not consistent with a real reasoning quality decline.**

---

## 4. Metrics by Failure Type

### Definitions
Each case has a `failure_mode` describing the class of bug. These are the bug patterns the model must identify and fix.

### Baseline (BL) — by failure type

| Failure Type | n | Pass Rate | LEG Rate | Notes |
|-------------|---|-----------|----------|-------|
| ALIASING | 24 | 100.0% | 0.0% | Perfect — model handles shared reference bugs easily |
| EARLY_RETURN | 24 | 100.0% | 0.0% | Perfect |
| INDEX_MISALIGN | 24 | 100.0% | 0.0% | Perfect |
| MISSING_BRANCH | 24 | 100.0% | 0.0% | Perfect |
| PARTIAL_ROLLBACK | 24 | 100.0% | 0.0% | Perfect |
| PARTIAL_STATE_UPDATE | 26 | 100.0% | 0.0% | Perfect |
| SIDE_EFFECT_ORDER | 24 | 100.0% | 0.0% | Perfect |
| SILENT_DEFAULT | 24 | 100.0% | 0.0% | Perfect |
| STALE_CACHE | 24 | 100.0% | 0.0% | Perfect |
| TEMPORAL_DRIFT | 24 | 100.0% | 0.0% | Perfect |
| USE_BEFORE_SET | 24 | 100.0% | 0.0% | Perfect |
| WRONG_CONDITION | 24 | 100.0% | 0.0% | Perfect |
| TEMPORAL_ORDERING | 2 | 100.0% | 0.0% | Small sample |
| FLAG_DRIFT | 3 | 100.0% | 0.0% | Small sample |
| RETRY_DUPLICATION | 24 | 95.8% | 0.0% | Near-perfect |
| INIT_ORDER | 24 | 95.8% | 4.2% | Minor LEG |
| HIDDEN_DEPENDENCY | 4 | 75.0% | 0.0% | Small sample, 1 fail |
| MUTABLE_DEFAULT | 24 | **70.8%** | **29.2%** | Significant LEG — model understands but can't fix |
| RACE_CONDITION | 8 | **50.0%** | **50.0%** | Half are LEG — model understands races but can't code fixes |
| INVARIANT_VIOLATION | 5 | **40.0%** | **60.0%** | Highest LEG — 3 of 5 are reasoning-correct but code-wrong |
| STATE_SEMANTIC_VIOLATION | 8 | **37.5%** | **50.0%** | Complex state bugs; high LEG |
| CACHE_ORDERING | 3 | **0.0%** | **33.3%** | Hardest — 0 passes |

### LEG-Reduction (LR) — by failure type

| Failure Type | n | Pass Rate | LEG Rate | Δ Pass (vs BL) |
|-------------|---|-----------|----------|-----------------|
| SIDE_EFFECT_ORDER | 24 | 95.8% | 0.0% | -4.2pp |
| USE_BEFORE_SET | 24 | 95.8% | 0.0% | -4.2pp |
| EARLY_RETURN | 24 | 91.7% | 0.0% | -8.3pp |
| RETRY_DUPLICATION | 24 | 91.7% | 0.0% | -4.1pp |
| PARTIAL_ROLLBACK | 24 | 91.7% | 0.0% | -8.3pp |
| TEMPORAL_DRIFT | 24 | 91.7% | 0.0% | -8.3pp |
| INDEX_MISALIGN | 24 | 87.5% | 0.0% | -12.5pp |
| PARTIAL_STATE_UPDATE | 26 | 84.6% | 0.0% | -15.4pp |
| ALIASING | 24 | 83.3% | 0.0% | -16.7pp |
| STALE_CACHE | 24 | 83.3% | 8.3% | -16.7pp |
| SILENT_DEFAULT | 24 | 83.3% | 4.2% | -16.7pp |
| INIT_ORDER | 24 | 75.0% | 12.5% | -20.8pp |
| MISSING_BRANCH | 24 | 75.0% | 25.0% | -25.0pp |
| WRONG_CONDITION | 24 | 70.8% | 4.2% | -29.2pp |
| FLAG_DRIFT | 3 | 66.7% | 0.0% | -33.3pp |
| MUTABLE_DEFAULT | 24 | 58.3% | 25.0% | -12.5pp |
| RACE_CONDITION | 8 | 50.0% | 25.0% | 0.0pp |
| HIDDEN_DEPENDENCY | 4 | 100.0% | 0.0% | **+25.0pp** |
| TEMPORAL_ORDERING | 2 | 100.0% | 0.0% | 0.0pp |
| INVARIANT_VIOLATION | 5 | 40.0% | 60.0% | 0.0pp |
| STATE_SEMANTIC_VIOLATION | 8 | 25.0% | 12.5% | -12.5pp |
| CACHE_ORDERING | 3 | 0.0% | 66.7% | 0.0pp |

### Key Findings

- **LEG-reduction hurts pass rate on every failure type** except HIDDEN_DEPENDENCY (+25pp, small sample) and ties on RACE_CONDITION, INVARIANT_VIOLATION, TEMPORAL_ORDERING, CACHE_ORDERING.
- The **hardest failure types under both conditions**: CACHE_ORDERING (0% both), INVARIANT_VIOLATION (40% both), STATE_SEMANTIC_VIOLATION (38%→25%).
- **LEG is concentrated in**: CACHE_ORDERING, INVARIANT_VIOLATION, RACE_CONDITION, STATE_SEMANTIC_VIOLATION, MUTABLE_DEFAULT — all involve complex state or concurrency reasoning.

---

## 5. Per-Case Table

### How to read this table

Each row is one case. Values are rates across all trials (n=2-8 per condition).

- **bl_pass** = fraction of baseline evals that passed (both reasoning + code correct)
- **bl_rc** = fraction of baseline evals where reasoning was judged correct
- **bl_cc** = fraction of baseline evals where code passed execution tests
- **bl_leg** = fraction of baseline evals with correct reasoning but wrong code
- **bl_lucky** = fraction of baseline evals with wrong reasoning but correct code
- Same for **lr_*** (leg_reduction condition)
- **n** = number of evals per condition

| case_id | diff | failure_mode | bl_pass | bl_rc | bl_cc | bl_leg | bl_lucky | lr_pass | lr_rc | lr_cc | lr_leg | lr_lucky | n |
|---------|------|-------------|---------|-------|-------|--------|----------|---------|-------|-------|--------|----------|---|
| alias_config_a | A | ALIASING | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 8 |
| alias_config_b | B | ALIASING | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.62 | 0.38 | 0.62 | 0.00 | 0.25 | 8 |
| alias_config_c | C | ALIASING | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.38 | 0.88 | 0.00 | 0.50 | 8 |
| async_race_lock | C | RACE_CONDITION | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 2 |
| cache_invalidation_order | C | CACHE_ORDERING | 0.00 | 0.33 | 0.00 | 0.33 | 0.00 | 0.00 | 0.67 | 0.00 | 0.67 | 0.00 | 3 |
| check_then_act | C | RACE_CONDITION | 1.00 | 0.50 | 1.00 | 0.00 | 0.50 | 1.00 | 0.50 | 1.00 | 0.00 | 0.50 | 2 |
| commit_gate | L3 | INVARIANT_VIOLATION | 1.00 | 0.50 | 1.00 | 0.00 | 0.50 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 2 |
| config_shadowing | L3 | PARTIAL_STATE_UPDATE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.50 | 1.00 | 0.00 | 0.50 | 2 |
| early_return_a | A | EARLY_RETURN | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.88 | 0.88 | 0.00 | 0.00 | 8 |
| early_return_b | B | EARLY_RETURN | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 0.88 | 0.12 | 0.88 | 0.00 | 0.75 | 8 |
| early_return_c | C | EARLY_RETURN | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 8 |
| effect_order_a | A | SIDE_EFFECT_ORDER | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 8 |
| effect_order_b | B | SIDE_EFFECT_ORDER | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 8 |
| effect_order_c | C | SIDE_EFFECT_ORDER | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 0.88 | 0.12 | 0.88 | 0.00 | 0.75 | 8 |
| false_fix_deadlock | C | RACE_CONDITION | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 2 |
| feature_flag_drift | C | FLAG_DRIFT | 1.00 | 0.33 | 1.00 | 0.00 | 0.67 | 0.67 | 0.00 | 0.67 | 0.00 | 0.67 | 3 |
| hidden_dep_multihop | C | HIDDEN_DEPENDENCY | 0.50 | 0.50 | 0.50 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 2 |
| index_misalign_a | A | INDEX_MISALIGN | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 8 |
| index_misalign_b | B | INDEX_MISALIGN | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 8 |
| index_misalign_c | C | INDEX_MISALIGN | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 0.62 | 0.00 | 0.62 | 0.00 | 0.62 | 8 |
| invariant_partial_fail | C | INVARIANT_VIOLATION | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 3 |
| l3_state_pipeline | C | STATE_SEMANTIC_VIOLATION | 0.38 | 0.88 | 0.38 | 0.50 | 0.00 | 0.25 | 0.12 | 0.25 | 0.12 | 0.25 | 8 |
| lazy_init_a | A | INIT_ORDER | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.75 | 0.62 | 0.75 | 0.00 | 0.12 | 8 |
| lazy_init_b | B | INIT_ORDER | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.12 | 1.00 | 0.00 | 0.88 | 8 |
| lazy_init_c | C | INIT_ORDER | 0.88 | 0.88 | 0.88 | 0.12 | 0.12 | 0.50 | 0.62 | 0.50 | 0.38 | 0.25 | 8 |
| lost_update | C | RACE_CONDITION | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 2 |
| missing_branch_a | A | MISSING_BRANCH | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.62 | 0.75 | 0.62 | 0.38 | 0.25 | 8 |
| missing_branch_b | B | MISSING_BRANCH | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 8 |
| missing_branch_c | C | MISSING_BRANCH | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.62 | 0.75 | 0.62 | 0.38 | 0.25 | 8 |
| mutable_default_a | A | MUTABLE_DEFAULT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 8 |
| mutable_default_b | B | MUTABLE_DEFAULT | 0.12 | 1.00 | 0.12 | 0.88 | 0.00 | 0.38 | 0.88 | 0.38 | 0.62 | 0.12 | 8 |
| mutable_default_c | C | MUTABLE_DEFAULT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.38 | 0.38 | 0.38 | 0.12 | 0.12 | 8 |
| ordering_dependency | C | TEMPORAL_ORDERING | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.50 | 1.00 | 0.00 | 0.50 | 2 |
| overdetermination | C | HIDDEN_DEPENDENCY | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 2 |
| partial_rollback_a | A | PARTIAL_ROLLBACK | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 8 |
| partial_rollback_b | B | PARTIAL_ROLLBACK | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.50 | 0.88 | 0.00 | 0.38 | 8 |
| partial_rollback_c | C | PARTIAL_ROLLBACK | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.50 | 0.88 | 0.00 | 0.38 | 8 |
| partial_update_a | A | PARTIAL_STATE_UPDATE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.62 | 0.50 | 0.62 | 0.00 | 0.12 | 8 |
| partial_update_b | B | PARTIAL_STATE_UPDATE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.38 | 1.00 | 0.00 | 0.62 | 8 |
| partial_update_c | C | PARTIAL_STATE_UPDATE | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 0.88 | 0.25 | 0.88 | 0.00 | 0.62 | 8 |
| retry_dup_a | A | RETRY_DUPLICATION | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 1.00 | 0.38 | 1.00 | 0.00 | 0.62 | 8 |
| retry_dup_b | B | RETRY_DUPLICATION | 1.00 | 0.12 | 1.00 | 0.00 | 0.88 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 8 |
| retry_dup_c | C | RETRY_DUPLICATION | 0.88 | 0.50 | 0.88 | 0.00 | 0.38 | 0.75 | 0.00 | 0.75 | 0.00 | 0.75 | 8 |
| silent_default_a | A | SILENT_DEFAULT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 1.00 | 0.88 | 0.12 | 0.00 | 8 |
| silent_default_b | B | SILENT_DEFAULT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.00 | 0.88 | 0.00 | 0.88 | 8 |
| silent_default_c | C | SILENT_DEFAULT | 1.00 | 0.62 | 1.00 | 0.00 | 0.38 | 0.75 | 0.00 | 0.75 | 0.00 | 0.75 | 8 |
| stale_cache_a | A | STALE_CACHE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 8 |
| stale_cache_b | B | STALE_CACHE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.75 | 1.00 | 0.75 | 0.25 | 0.00 | 8 |
| stale_cache_c | C | STALE_CACHE | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.75 | 0.12 | 0.75 | 0.00 | 0.62 | 8 |
| temporal_drift_a | A | TEMPORAL_DRIFT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.75 | 1.00 | 0.00 | 0.25 | 8 |
| temporal_drift_b | B | TEMPORAL_DRIFT | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.88 | 0.00 | 0.88 | 0.00 | 0.88 | 8 |
| temporal_drift_c | C | TEMPORAL_DRIFT | 1.00 | 0.75 | 1.00 | 0.00 | 0.25 | 0.88 | 0.00 | 0.88 | 0.00 | 0.88 | 8 |
| use_before_set_a | A | USE_BEFORE_SET | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 1.00 | 0.12 | 1.00 | 0.00 | 0.88 | 8 |
| use_before_set_b | B | USE_BEFORE_SET | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.12 | 1.00 | 0.00 | 0.88 | 8 |
| use_before_set_c | C | USE_BEFORE_SET | 1.00 | 0.25 | 1.00 | 0.00 | 0.75 | 0.88 | 0.00 | 0.88 | 0.00 | 0.88 | 8 |
| wrong_condition_a | A | WRONG_CONDITION | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 8 |
| wrong_condition_b | B | WRONG_CONDITION | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.75 | 0.88 | 0.75 | 0.12 | 0.00 | 8 |
| wrong_condition_c | C | WRONG_CONDITION | 1.00 | 0.88 | 1.00 | 0.00 | 0.12 | 0.38 | 0.12 | 0.38 | 0.00 | 0.25 | 8 |

---

## 6. Trajectory Analysis

Not applicable — both conditions are single-shot (1 LLM call, no retries). There are no retry, repair loop, or multi-attempt conditions in this ablation.

---

## 7. LEG Analysis (Deep Dive)

### Definition reminder
LEG = model's reasoning correctly identifies the bug, but the code it produces is wrong. This is the "looks-good error gap" — the model understands the problem but can't translate that understanding into a working fix.

### Which cases exhibit LEG?

**Persistent LEG** (LEG > 0 in BOTH conditions — these are structurally hard):

| Case | BL LEG | LR LEG | Failure Type | Why |
|------|--------|--------|-------------|-----|
| invariant_partial_fail | 3/3 (100%) | 3/3 (100%) | INVARIANT_VIOLATION | Requires atomic rollback logic — model understands but can't implement |
| false_fix_deadlock | 2/2 (100%) | 2/2 (100%) | RACE_CONDITION | Model correctly identifies race but produces a fix that deadlocks |
| mutable_default_b | 7/8 (88%) | 5/8 (62%) | MUTABLE_DEFAULT | Multi-file case; model fixes wrong function (known reference_fix metadata issue) |
| cache_invalidation_order | 1/3 (33%) | 2/3 (67%) | CACHE_ORDERING | Ordering-sensitive cache logic — model understands but misordering persists |
| l3_state_pipeline | 4/8 (50%) | 1/8 (12%) | STATE_SEMANTIC_VIOLATION | Complex state machine; reasoning helps but code is often wrong |

**LEG only under LR** (intervention introduced new LEG):

| Case | LR LEG | Failure Type |
|------|--------|-------------|
| missing_branch_a | 3/8 (38%) | MISSING_BRANCH |
| missing_branch_c | 3/8 (38%) | MISSING_BRANCH |
| lazy_init_c | 3/8 (38%) | INIT_ORDER |
| stale_cache_b | 2/8 (25%) | STALE_CACHE |

### Which failure types dominate LEG?

Under baseline: INVARIANT_VIOLATION (60%), RACE_CONDITION (50%), STATE_SEMANTIC_VIOLATION (50%), CACHE_ORDERING (33%), MUTABLE_DEFAULT (29%)

Under LR: CACHE_ORDERING (67%), INVARIANT_VIOLATION (60%), MUTABLE_DEFAULT (25%), MISSING_BRANCH (25%), RACE_CONDITION (25%)

### Is execution the bottleneck?

**For baseline: NO.** Exec|Reason = 94.4%. When the model reasons correctly, it produces correct code 94% of the time. The bottleneck is NOT execution — it's the 10% of cases where reasoning fails.

**For LR: Partially.** Exec|Reason = 85.6%. A meaningful drop, suggesting the structured prompt format occasionally degrades code quality even when reasoning is correct.

**For the persistent LEG cases (invariant_partial_fail, false_fix_deadlock, async_race_lock): YES.** These are 100% LEG — perfect reasoning, zero correct code. Execution IS the bottleneck for these specific cases.

---

## 8. Lucky Fix Analysis

### Definition reminder
Lucky fix = model's reasoning is wrong (doesn't correctly identify the bug mechanism) but the code is correct anyway. This can happen when fixes are simple enough to stumble into.

### Scale of the problem

| Condition | Lucky Fix Rate | Lucky Fix Count |
|-----------|---------------|-----------------|
| Baseline | 8.4% (33/395) | Modest — occasional |
| LEG-Reduction | **40.5% (160/395)** | Massive — nearly half of all passes |

### Top lucky fix cases under LR

| Case | LR Lucky Rate | BL Lucky Rate | Code Quality Same? |
|------|--------------|---------------|-------------------|
| retry_dup_b | 100% (8/8) | 88% (7/8) | Yes — always passes, reasoning always "wrong" |
| early_return_c | 100% (8/8) | 0% (0/8) | Yes — code always correct, but LR reasoning flagged wrong |
| lost_update | 100% (2/2) | 0% (0/2) | Same code quality, different reasoning classification |
| commit_gate | 100% (2/2) | 50% (1/2) | Same pattern |
| overdetermination | 100% (2/2) | 0% (0/2) | Same pattern |
| lazy_init_b | 88% (7/8) | 0% (0/8) | Code passes equally, reasoning classified differently |
| use_before_set_a | 88% (7/8) | 12% (1/8) | Same code quality |
| use_before_set_b | 88% (7/8) | 0% (0/8) | Same code quality |
| temporal_drift_b | 88% (7/8) | 0% (0/8) | Same code quality |
| silent_default_b | 88% (7/8) | 0% (0/8) | Same code quality |

### Pattern analysis

Look at `early_return_c`:
- Baseline: 100% pass, 100% reasoning_correct → 0% lucky
- LR: 100% pass, 0% reasoning_correct → 100% lucky

The CODE QUALITY IS IDENTICAL (100% pass both conditions). The only thing that changed is the reasoning classifier's judgment. Under baseline, the classifier says reasoning is correct. Under LR, the classifier says reasoning is wrong. But the model is producing the same quality fixes.

> **⚠️ SUSPICIOUS: This is strong evidence of classifier miscalibration on the LR response format. The LR prompt asks for structured output (plan steps, verification, revision history). The reasoning classifier appears to systematically rate this format as "incorrect reasoning" even when the actual bug analysis is correct. This inflates lucky fix counts and deflates true success counts under LR.**

### Did the intervention increase lucky fixes?

Yes, dramatically: +32.1pp. But this is almost certainly a measurement artifact, not a real change in model behavior. The evidence:
1. Code quality dropped only 12.7pp (93.7% → 81.0%) while reasoning_correct dropped 43.1pp
2. Cases with 100% lucky under LR often have 0% lucky under BL with identical code pass rates
3. The pattern is systematic across many unrelated cases

---

## 9. Intervention Effect (LEG Reduction)

### Summary

| Metric | Baseline | LEG-Reduction | Delta | Direction |
|--------|----------|---------------|-------|-----------|
| Pass rate | 93.7% | 81.0% | -12.7pp | Worse |
| LEG rate | 5.1% | 6.8% | +1.7pp | Slightly worse |
| Lucky rate | 8.4% | 40.5% | +32.1pp | Much worse (but likely artifact) |
| Reasoning acc. | 90.4% | 47.3% | -43.1pp | Much worse (likely artifact) |
| Exec\|Reason | 94.4% | 85.6% | -8.8pp | Worse |

### Interpretation

The LEG-reduction intervention **failed its intended purpose**:
- It did NOT reduce the LEG rate (5.1% → 6.8%, slightly worse)
- It REDUCED overall pass rate by 12.7pp
- The massive reasoning_correct drop is likely a classifier artifact (see Section 8)

**If we correct for the classifier artifact** (treat cases where code is correct as "true success" regardless of reasoning classification), the adjusted metrics would be:
- BL code_correct: 93.7%
- LR code_correct: 81.0%
- The real effect of the intervention is a ~12.7pp drop in code quality

The intervention appears to make models worse at code generation — possibly because the structured plan-verify-correct format consumes output tokens that could be used for code, or because the self-correction step sometimes introduces errors.

---

## 10. Sanity Checks

### Pipeline integrity checks — ALL PASSED

| Check | Result | Status |
|-------|--------|--------|
| pass=True but code_correct=False | 0 cases | PASS |
| code_correct=True but pass=False | 0 cases | PASS |
| Missing reasoning_correct field | 0 events | PASS |
| Missing code_correct field | 0 events | PASS |
| Missing failure_type field | 0 events | PASS |
| Duplicate events | 0 duplicates | PASS |
| Events per condition balanced | 395 BL, 395 LR | PASS |

### Sample size concerns

12 cases have fewer than 8 events per condition (only 2-3 trials completed before run was stopped). These are primarily the L3 and single-family cases (async_race_lock, cache_invalidation_order, false_fix_deadlock, etc.). Results for these cases should be treated as preliminary.

### No pipeline bugs detected

> The post-fix pipeline is functioning correctly. Code is being executed, test results are being recorded, and all fields are populated. The 0% pass rate bug from the previous run is fully resolved.

---

## 11. Anomaly Detection

### Anomaly 1: Reasoning classifier miscalibration on LR format

**Evidence:** reasoning_correct drops from 90.4% to 47.3% under LR, while code_correct drops only from 93.7% to 81.0%. This asymmetry is too large to be explained by the intervention actually degrading reasoning quality.

**Impact:** All LR reasoning-based metrics (LEG, lucky fix, true success, true failure) are unreliable. Code-based metrics (pass rate, code_correct) are reliable.

> **⚠️ SUSPICIOUS: The reasoning classifier needs to be validated on LR-format responses before reasoning metrics under LR can be trusted.**

### Anomaly 2: mutable_default_b has 12% BL pass rate

All other Level A and B cases have ≥88% baseline pass rate. `mutable_default_b` at 12% is a dramatic outlier. This is caused by a known metadata issue: `reference_fix.function` says `enqueue` but the reference fix file modifies `process_batch`/`summarize`. The assembly rename detection flags this as a model error.

> **⚠️ KNOWN ISSUE: mutable_default_b has incorrect reference_fix.function metadata. This causes rename detection to fail, producing artificially low pass rates. This case should be excluded from aggregate metrics or the metadata should be fixed.**

### Anomaly 3: retry_dup_b has 88% lucky fix under baseline

This case has 12% reasoning_correct under baseline but 100% code pass rate. The reasoning classifier consistently rates the model's reasoning as incorrect for this case, even though the code is always correct. This suggests the classifier has difficulty with this specific bug pattern (RETRY_DUPLICATION).

### Anomaly 4: No anomalous pass rate jumps

The before/after comparison shows a clean jump from 0% (broken pipeline) to 93.7% (working pipeline). There are no unexplained partial improvements or intermediate states. This confirms the fix was clean.

---

## 12. Top 10 Hardest Cases

Ranked by baseline pass rate (lower = harder), then by persistence across trials.

| Rank | Case | Diff | Failure Mode | BL Pass | LR Pass | n | Why Hard |
|------|------|------|-------------|---------|---------|---|----------|
| 1 | async_race_lock | C | RACE_CONDITION | 0% | 0% | 2 | Requires thread-safe lock implementation; model reasons correctly but can't produce correct concurrent code |
| 2 | cache_invalidation_order | C | CACHE_ORDERING | 0% | 0% | 3 | Ordering-sensitive cache operations; model must get the exact sequence right |
| 3 | invariant_partial_fail | C | INVARIANT_VIOLATION | 0% | 0% | 3 | Requires atomic rollback on partial failure; 100% LEG in both conditions |
| 4 | false_fix_deadlock | C | RACE_CONDITION | 0% | 0% | 2 | Model's "fix" introduces a deadlock; 100% LEG — perfect reasoning, always broken code |
| 5 | mutable_default_b | B | MUTABLE_DEFAULT | 12% | 38% | 8 | Multi-file case with reference_fix metadata issue; assembly rename detection fails |
| 6 | l3_state_pipeline | C | STATE_SEMANTIC_VIOLATION | 38% | 25% | 8 | Complex state machine with semantic constraints; highest trial-to-trial variance |
| 7 | hidden_dep_multihop | C | HIDDEN_DEPENDENCY | 50% | 100% | 2 | Multi-hop dependency chain; small sample but inconsistent |
| 8 | lazy_init_c | C | INIT_ORDER | 88% | 50% | 8 | Initialization ordering with reset semantics; LR makes it significantly harder |
| 9 | wrong_condition_c | C | WRONG_CONDITION | 100% | 38% | 8 | Biggest LR drop (-62pp); structured reasoning degrades performance on condition logic |
| 10 | mutable_default_c | C | MUTABLE_DEFAULT | 100% | 38% | 8 | Second biggest LR drop (-62pp); multi-file mutable default handling |

---

## 13. Top 10 Most Important Failures

### 1. invariant_partial_fail — Pure LEG (100% both conditions)

The model perfectly identifies that a partial failure must trigger rollback, but every code implementation has subtle bugs in the rollback logic. This is the purest example of the LEG phenomenon in the benchmark.

### 2. false_fix_deadlock — Model creates worse bugs

The model identifies the race condition correctly but produces a "fix" that introduces a deadlock. This is worse than the original bug — the model's intervention makes the system less reliable.

### 3. async_race_lock — Concurrency is fundamentally hard

100% reasoning correct, 0% code correct under baseline. The model understands threading but cannot produce correct lock acquisition patterns. This validates that concurrency bugs are in a different difficulty class.

### 4. mutable_default_b — Infrastructure failure masking model performance

The reference_fix metadata points to the wrong function, causing the assembly system to reject correct code. This is NOT a model failure — it's a benchmark infrastructure issue.

### 5. l3_state_pipeline — High variance, low pass rate

38% baseline pass with 50% LEG. The model sometimes produces correct state machine code but is inconsistent. This case exercises deep state reasoning that is at the frontier of model capability.

### 6. wrong_condition_c — LR catastrophically hurts

100% baseline → 38% LR (-62pp). The structured reasoning format appears to cause the model to overthink a simple condition fix, introducing errors that wouldn't exist in the baseline single-shot approach.

### 7. mutable_default_c — Same pattern as wrong_condition_c

100% → 38% under LR. The intervention is counterproductive for cases where the fix is conceptually simple but the structured format adds cognitive overhead.

### 8. cache_invalidation_order — Nobody can solve this

0% across both conditions. The cache invalidation ordering problem requires precise temporal reasoning that exceeds current model capabilities.

### 9. alias_config_b — Multi-file degrades under LR

100% → 62% under LR. The multi-file reconstruction + LR structured format creates compounding complexity.

### 10. early_return_c — Perfect example of classifier artifact

100% pass both conditions, but 100% reasoning_correct under BL and 0% under LR. The code is identical in quality; only the reasoning classification differs. This failure is in the measurement system, not the model.

---

## 14. Final Diagnosis

### 1. Is the system behaving correctly?

**The execution pipeline: YES.** Code is running, tests are executing, results are being recorded. The reconstruction wiring fix resolved the 0% pass rate bug completely. All sanity checks pass.

**The reasoning classifier: NO (under LR).** There is strong evidence of systematic miscalibration on the LEG-reduction response format. Reasoning-based metrics under LR are unreliable.

### 2. What is the dominant failure mode?

**For baseline:** The model solves 93.7% of cases. The remaining 6.3% are concentrated in concurrency (RACE_CONDITION), complex state (STATE_SEMANTIC_VIOLATION, INVARIANT_VIOLATION), and cache ordering (CACHE_ORDERING). These are structurally hard problems.

**For LR:** The dominant failure mode is the intervention itself making things worse. Pass rate drops 12.7pp across the board.

### 3. Is LEG still present or reduced?

**LEG is low and NOT reduced by the intervention.** Baseline LEG is 5.1%, LR LEG is 6.8%. The intervention failed to reduce the execution gap. LEG is concentrated in a small number of structurally hard cases (invariant_partial_fail, false_fix_deadlock, async_race_lock).

### 4. Did the intervention help or hurt?

**Hurt.** The LEG-reduction intervention:
- Reduced pass rate by 12.7pp
- Did not reduce LEG rate
- Reduced Exec|Reason by 8.8pp
- Dramatically increased apparent lucky fixes (likely a classifier artifact)

### 5. Are results trustworthy?

**Code-based metrics (pass rate, code_correct): YES.** These come from actual code execution and are reliable.

**Reasoning-based metrics under baseline: MOSTLY YES.** Some cases (retry_dup_b, feature_flag_drift) show unusual reasoning classification, but the overall 90.4% reasoning accuracy under baseline is plausible.

**Reasoning-based metrics under LR: NO.** The 47.3% reasoning accuracy is almost certainly deflated by classifier miscalibration. All derived metrics (LEG, lucky fix, true success) are unreliable under LR.

---

## 15. Actionable Next Steps

### Debugging actions

1. **Validate the reasoning classifier on LR-format responses.** Manually review 20 LR responses where the code is correct but reasoning is classified as "wrong." Determine if the classifier is misjudging the structured format. If confirmed, retrain or adjust the classifier prompt for LR-format responses.

2. **Fix mutable_default_b metadata.** The `reference_fix.function` field should point to `process_batch` (the function actually fixed), not `enqueue`. This will unblock correct evaluation of this case.

3. **Increase trial count for low-n cases.** 12 cases have only 2-3 trials. Run targeted trials for these cases to get stable estimates.

### Experiment ideas

1. **Run a classifier ablation.** Use the SAME responses but have the classifier evaluate reasoning in two modes: (a) raw response format, (b) extracted reasoning only. If results differ, the classifier is format-sensitive.

2. **Test a lighter intervention.** The full plan-verify-correct structure may be too heavy. Try a minimal intervention: just ask the model to verify its code matches its reasoning before submitting. This might capture the benefit without the overhead.

3. **Run gpt-5-mini and gpt-4o-mini** with the fixed pipeline. The cross-model comparison will reveal whether the intervention effect is model-specific or universal.

### Refactor suggestions

1. **Decouple reasoning classification from response format.** Extract the reasoning text before passing it to the classifier, stripping any structural formatting. This prevents format-dependent bias.

2. **Add a code-only evaluation path.** For cases where we only care about code correctness (not reasoning), bypass the LLM classifier entirely. This gives us a clean, unbiased code quality metric.

3. **Separate reconstruction metrics.** Track reconstruction success/failure rates, assembly errors, and rename errors as first-class metrics on the dashboard. These are infrastructure signals that shouldn't be mixed with model performance.
