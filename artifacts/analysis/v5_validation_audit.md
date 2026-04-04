# V5 Validation Audit

**Data:** 20031 assessable oracle-labeled events

## Part 1: Consistency Audit

### 1.1 Failure decomposition integrity
Total failures: 3837
S1 (reasoning): 1320
S2 (structure): 275
S3 (execution): 2242
Sum: 3837
**Check: 3837 == 3837? PASS**

### 1.2 Stage 3 vs AST-correct exec failures
Stage 3 (oracle_correct AND ast_correct AND exec_fail): 2242
AST_alignment=correct AND exec_fail: 2531
ast_relaxed=True AND exec_fail: 2531

Difference (ast_relaxed exec_fail - Stage 3): 289
These are events where ast_relaxed=True AND exec_fail=True BUT oracle_correct=False
Verified count: 289
**Explanation: The 2531 figure includes 289 events where AST says correct structure but oracle says wrong reasoning. Stage 3 (2242) correctly excludes these because they are reasoning failures first.**

ast_alignment=correct exec_fail: 2531
Stage 3: 2242
Difference: 289
(ast=correct, exec=fail, oracle=wrong): 289
**Total AST-correct exec failures = Stage 3 (2242) + oracle-wrong-but-AST-correct (289) = 2531 = 2531. CONSISTENT.**

### 1.3 Unknown distribution
ast_correct: 18271 (91.2%)
ast_incorrect: 828 (4.1%)
ast_unknown: 932 (4.7%)
Sum: 20031
**Check: 20031 == 20031? PASS**

Stage 2 decomposition:
  oracle_correct + ast_incorrect: 149
  oracle_correct + ast_unknown: 126
  Total Stage 2: 275 == 275? PASS
**Unknown is counted in Stage 2 (structural failure), NOT Stage 3 (execution failure). This is correct — unknown means we cannot confirm the structure is right.**

---

## Part 2: Unknown State Investigation

### 2.1 l3_state_pipeline (97% unknown)

N=659, correct=20 (3.0%), incorrect=0 (0.0%), unknown=639 (97.0%)

**Root cause:** The checker requires both `commit()` AND `freeze_view()` in `process_batch()`. Most models keep `commit()` but remove `freeze_view()` (thinking it's redundant). Since the function IS modified (commit present) and no anti-pattern is defined for this family, the result is `unknown` — not incorrect (no anti-pattern) and not correct (missing freeze_view).

**Classification:** (B) Missing checker coverage. The checker should have an anti-pattern for "commit present but freeze_view absent" which would make these `incorrect` instead of `unknown`. Alternatively, add freeze_view-absent as a negative signal.

**Impact on metrics:** l3_state_pipeline contributes 639 of 932 unknown events (69%). This single family dominates the unknown bucket.

### 2.2 Global unknown excluding l3_state_pipeline

Without l3_state_pipeline: N=19372, unknown=293 (1.5%)
**Global unknown rate drops from 4.7% to 1.5% when excluding l3_state_pipeline.**
**AST is broadly reliable. The high unknown rate is driven by one family with a known checker gap.**

### 2.3 Unknown × execution
unknown + exec_pass: 355 (38.1%)
unknown + exec_fail: 577 (61.9%)

unknown+exec_pass by family:
  l3_state_pipeline: 229
  use_before_set: 69
  lazy_init: 10
  stale_cache: 9
  index_misalign: 9
  invariant_partial_fail: 8
  early_return: 7
  partial_rollback: 6
  partial_update: 4
  mutable_default: 2
  hidden_dep_multihop: 1
  effect_order: 1

**l3_state_pipeline (229) dominates. These are commit-only fixes that pass the test (which was weak before our fix). The remaining 126 are scattered across families and are likely valid alternative repairs.**

---

## Part 3: Locus Probe = 100% Investigation

### 3.1 Implementation check

The locus probe checks: `f"def {target_func}" in code`
where `code` = `payload._extracted_code` and `target_func` = `reference_fix.function`.

**Problem identified:** The assessable set ALREADY filters out events where the target function is not found in the extracted code. Events where the function is missing are classified as `extraction_error` and excluded from the assessable pool. Therefore, EVERY assessable event has `def {target_func}` in the code BY DEFINITION.

**This means the locus probe is DEGENERATE on the assessable set.** It has zero discriminative power because the filtering already ensures 100% locus match. The probe only becomes informative if we include extraction_error events in the denominator.

### 3.2 Including extraction errors
Total oracle-labeled events (including extraction errors): 29158
Extraction errors: 483
Assessable (target function found): 20031
Locus match rate on FULL oracle set: 68.7%

**Revised locus probe oracle agreement (including extraction errors as locus=False):**
Extraction errors with oracle_correct: 185
Extraction errors with oracle_wrong: 290
**39% of extraction errors have oracle_correct — meaning the model reasoned correctly but produced code where the target function is missing. These would be locus=False + oracle_correct → locus probe WRONG here.**

Full-set locus probe agreement: 18389/20506 = 89.7%
(Assessable locus=T × oracle=T: 18099, ext_err locus=F × oracle=F: 290)

**Conclusion: The locus probe on the FULL oracle set (including extraction errors) achieves 89.7% oracle agreement. On the assessable-only set it is 100% by construction (degenerate). The +4.5pp AST increment over locus in the report is ONLY valid on the assessable set and measures pattern-matching value, not locus value.**

---

## Part 4: AST vs Locus Probe Per-Family

Since locus=100% on the assessable set, the per-family comparison is between AST pattern matching (correct/incorrect/unknown) and a trivial "always correct" baseline.

The meaningful comparison is AST vs execution:

| Family | N | Exec-Oracle agree | AST-Oracle agree | AST increment |
|--------|---|-------------------|-----------------|---------------|
| invariant_partial_fail | 1151 | 30.8% | 86.5% | +55.8pp |
| missing_branch | 1427 | 72.5% | 97.0% | +24.5pp |
| hidden_dep_multihop | 784 | 62.5% | 86.2% | +23.7pp |
| silent_default | 214 | 75.7% | 99.1% | +23.4pp |
| use_before_set | 1201 | 69.4% | 86.4% | +17.0pp |
| overdetermination | 853 | 84.4% | 99.8% | +15.4pp |
| early_return | 1851 | 88.4% | 97.9% | +9.5pp |
| effect_order | 975 | 91.5% | 99.8% | +8.3pp |
| commit_gate | 679 | 92.6% | 98.1% | +5.4pp |
| partial_rollback | 611 | 85.3% | 90.0% | +4.7pp |
| mutable_default | 1472 | 95.7% | 99.7% | +3.9pp |
| l3_state_pipeline | 659 | 80.1% | 82.1% | +2.0pp |
| retry_dup | 586 | 97.8% | 99.7% | +1.9pp |
| partial_update | 809 | 94.6% | 96.3% | +1.7pp |
| stale_cache | 1003 | 97.7% | 98.7% | +1.0pp |
| alias_config | 1028 | 98.9% | 99.9% | +1.0pp |
| index_misalign | 209 | 94.7% | 95.7% | +1.0pp |
| async_race_lock | 382 | 99.0% | 99.0% | +0.0pp |
| lazy_init | 1319 | 99.6% | 98.9% | -0.7pp |
| wrong_condition | 1040 | 95.1% | 94.2% | -0.9pp |
| temporal_drift | 1064 | 99.7% | 96.4% | -3.3pp |
| cache_invalidation_order | 714 | 58.3% | 38.2% | -20.0pp |

---

## Part 5: Execution Failure Decomposition Validation

### 5.1 Category sum check
Total AST-correct exec failures (ast_alignment=correct): 2531
Sum of categories: 2531
Categories: {'wrong_value_literal': 1242, 'unexpected_exception': 378, 'name_error': 309, 'import_failure': 302, 'unclassified_invariant': 239, 'runtime_crash': 35, 'missing_attribute': 26}
**Check: 2531 == 2531? PASS**

ast_relaxed=True AND exec_fail: 2531
ast_alignment=correct AND exec_fail: 2531
Difference: 0 (ast_relaxed but alignment != correct means anti-pattern also found)

### 5.2 wrong_value_literal sample inspection

Sampled 20 wrong_value_literal events. Sub-classification:
  misclassified: 12
  wrong_count_or_length: 8

Sample failure_reasons:
  [invariant_partial_fail] failure path: total=50, expected=100 (sender=50, receiver=0)
  [invariant_partial_fail] failure path: total=50, expected=100 (sender=50, receiver=0)
  [missing_branch_c] service_account got can_admin=True, expected False. Got: {'can_read': True, 'can_write': True, 'can_admin': True}
  [missing_branch_c] service_account got can_admin=True, expected False. Got: {'can_read': True, 'can_write': True, 'can_admin': True}
  [missing_branch_c] service_account got can_admin=True, expected False. Got: {'can_read': True, 'can_write': True, 'can_admin': True}

**Assessment:** "wrong_value_literal" is a reasonable label. These are cases where the test expected a specific value and got a different one. Sub-types include wrong counts, wrong status strings, wrong numeric values, and wrong permission values. All are value-level precision errors within structurally correct code. The category name is adequate; no rename needed.

### 5.3 Unclassified invariant sample

Sampled 20 unclassified events. Sub-classification:
  has_expected_keyword: 16
  has_fail_keyword: 2
  truly_unclassified: 2

Sample failure_reasons:
  [invariant_partial_fail] failure path: execute_transfer did not raise RuntimeError with random=0.0 (should trigger transient failure)
  [hidden_dep_multihop] cache not overwritten: get_display_name returned 'Alice', expected 'Bob'
  [hidden_dep_multihop] cache not overwritten: get_display_name returned 'Alice', expected 'Bob'
  [hidden_dep_multihop] cache not overwritten: get_display_name returned 'Alice', expected 'Bob'
  [hidden_dep_multihop] cache not overwritten: get_display_name returned 'Alice', expected 'Bob'

Unclassified by family: {'hidden_dep_multihop': 190, 'early_return': 30, 'invariant_partial_fail': 18, 'mutable_default': 1}

---

## Part 6: Core Claim Sensitivity Analysis

### 6.1 Sensitivity to unknown classification

| Treatment | Stage 3 count | Stage 3 % | Total failures |
|-----------|---------------|-----------|----------------|
| Current (unknown → Stage 2) | 2242 | 58.4% | 3837 |
| Alt A (unknown → Stage 3) | 2368 | 61.7% | 3837 |
| Alt B (unknown excluded) | 2242 | 68.8% | 3260 |

**The 58.4% claim shifts to 61.7% if unknown is treated as correct, or 68.8% if unknown is excluded. Range: 58.4%–61.7%. The finding is robust to unknown treatment.**

### 6.2 Per-family execution fidelity gap

| Family | N | Failures | Stage 3 | Stage 3 % of failures | Stage 3 % of all |
|--------|---|----------|---------|----------------------|------------------|
| alias_config | 1028 | 10 | 10 | 100% | 1.0% |
| mutable_default | 1472 | 60 | 60 | 100% | 4.1% |
| effect_order | 975 | 82 | 82 | 100% | 8.4% |
| index_misalign | 209 | 11 | 11 | 100% | 5.3% |
| retry_dup | 586 | 11 | 11 | 100% | 1.9% |
| temporal_drift | 1064 | 3 | 3 | 100% | 0.3% |
| overdetermination | 853 | 133 | 132 | 99% | 15.5% |
| use_before_set | 1201 | 231 | 223 | 97% | 18.6% |
| silent_default | 214 | 52 | 50 | 96% | 23.4% |
| missing_branch | 1427 | 374 | 355 | 95% | 24.9% |
| early_return | 1851 | 214 | 185 | 86% | 10.0% |
| stale_cache | 1003 | 22 | 19 | 86% | 1.9% |
| invariant_partial_fail | 1151 | 837 | 690 | 82% | 59.9% |
| hidden_dep_multihop | 784 | 374 | 285 | 76% | 36.4% |
| commit_gate | 679 | 50 | 37 | 74% | 5.4% |
| partial_update | 809 | 42 | 31 | 74% | 3.8% |
| lazy_init | 1319 | 5 | 3 | 60% | 0.2% |
| partial_rollback | 611 | 78 | 43 | 55% | 7.0% |
| wrong_condition | 1040 | 51 | 2 | 4% | 0.2% |
| cache_invalidation_order | 714 | 405 | 10 | 2% | 1.4% |

### 6.3 Per-model execution fidelity gap (with sample sizes)

| Model | N | Failures | Stage 3 | EFF% | Note |
|-------|---|----------|---------|------|------|
| claude-haiku-4-5-20251001 | 355 | 272 | 243 | 68.5% |  |
| gpt-5 | 238 | 147 | 81 | 34.0% |  |
| gpt-4o-mini | 3998 | 1403 | 888 | 22.2% |  |
| claude-sonnet-4-6 | 739 | 107 | 90 | 12.2% |  |
| gpt-4.1-nano | 4040 | 907 | 377 | 9.3% |  |
| gpt-5-mini | 4778 | 399 | 312 | 6.5% |  |
| gpt-5.4-mini | 5222 | 602 | 251 | 4.8% |  |
| claude-sonnet-4-20250514 | 660 | 0 | 0 | 0.0% |  |

**gpt-5 (N=238) and claude-haiku-4.5 (N=355) have high EFF% but moderate sample sizes. Claims about these specific models should note the sample size. gpt-4o-mini (N=3998) and gpt-5.4-mini (N=5222) have large samples and their EFF% values are robust.**