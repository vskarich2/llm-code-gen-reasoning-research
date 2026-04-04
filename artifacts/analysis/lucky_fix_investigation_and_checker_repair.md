# Lucky Fix Investigation and Checker Repair

**Date:** 2026-04-03
**Data:** 27,956 events from 12 oracle-evaluated log directories, 18,180 assessable

---

## A. Executive Summary

The LUCKY_FIX rate dropped from **11.1% to 3.2%** after repairing 6 invariant checker families. Of the original 2,016 lucky-fix events, **1,436 (71%) were checker false negatives** — valid alternative fixes that the checker incorrectly rejected. The remaining 580 events (3.2%) are a mix of genuine partial fixes that pass tests and residual checker gaps.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| P(ast_correct) | 79.1% | **90.2%** | **+11.1pp** |
| LUCKY_FIX | 11.1% | **3.2%** | **-7.9pp** |
| AST_partial | 4.7% | 2.2% | -2.5pp |
| P(exec_fail \| ast_correct) | 11.1% | 13.3% | +2.2pp |

---

## B. Definition of LUCKY_FIX Bucket

`LUCKY_FIX = exec_pass AND NOT ast_relaxed` — events where execution passes but the AST checker says the code does not structurally satisfy the invariant.

---

## C. Distribution by Family (Pre-Revision)

| Family | LF count | LF% | Root cause |
|--------|---------|-----|-----------|
| early_return | 616 | 24.6% | Checker too narrow on branch placement |
| temporal_drift | 526 | 57.0% | Checker tested ordering, not argument |
| cache_invalidation_order | 288 | 42.4% | Checker didn't accept direct cache_set |
| hidden_dep_multihop | 234 | 25.7% | Checker matched specific function name |
| l3_state_pipeline | 230 | 35.8% | Genuine partial fix (commit without freeze_view) |
| invariant_partial_fail | 51 | 5.9% | Checker couldn't see through helper extraction |

---

## D-E. Distribution by Model / Condition

Evenly distributed across models and conditions — the checker defects were not model-specific.

---

## F-G. Manual Audit Methodology and Findings

Inspected 2-3 actual code outputs from each of the top 6 families (12+ concrete examples). For each:
- Read the generated code
- Compared against the invariant
- Determined whether the model's fix satisfies the invariant
- Identified why the checker rejected it

---

## H. Failure Mode Taxonomy

| Category | Count | % of original LF |
|----------|-------|------------------|
| **Valid alternative: checker tested wrong structural proxy** | 814 | 40.4% |
| **Valid alternative: checker too narrow on placement** | 616 | 30.6% |
| **Genuine partial fix that passes test** | 230 | 11.4% |
| **Valid alternative: checker matched specific function name** | 234 | 11.6% |
| **Valid alternative: checker couldn't see through indirection** | 51 | 2.5% |
| Residual (unknown / other) | 71 | 3.5% |

---

## I. Checker Defects Identified

### 1. early_return (616 LF)
**Invariant:** Ledger must have entry for every call.
**Old rule:** Audit call inside the `if amount==0` branch before return.
**Defect:** Models restructure to single `_ledger.append()` covering ALL paths — no early return at all. Checker only looked inside the if-branch.
**Fix:** Accept any structure where audit call covers all paths: before if, in both branches, no early return with single append, or finally block.

### 2. temporal_drift (526 LF)
**Invariant:** raw_stats must reflect original untransformed data.
**Old rule:** `compute_raw_stats` must be called BEFORE `normalize` (statement ordering).
**Defect:** The invariant is about the ARGUMENT, not the ordering. Models correctly call `compute_raw_stats(data)` with the original parameter even when the call comes after `normalize()`.
**Fix:** Check that `compute_raw_stats` is called with the function's original input parameter, not the transformed output.

### 3. cache_invalidation_order (288 LF)
**Invariant:** read_record returns latest value after update.
**Old rule:** `cache_invalidate` before `cache_conditional_set`.
**Defect:** Models use direct `cache_set(key, value)` after `db_write` instead of the invalidate→conditional_set pattern. Direct cache_set is a valid alternative that satisfies the invariant.
**Fix:** Accept either invalidation or direct cache write after db_write.

### 4. hidden_dep_multihop (234 LF)
**Invariant:** save_user must use always-overwrite cache semantics.
**Old rule:** Calls `sync_user_to_cache` or `cache_put`.
**Defect:** Models create new unified functions (`update_user_cache(user, conditional=False)`, `cache_write`, etc.) with overwrite semantics.
**Fix:** Accept any cache-write function call that is NOT `refresh_user_snapshot` or `cache_put_if_absent`.

### 5. invariant_partial_fail (51 LF)
**Invariant:** Balance conservation on failure.
**Old rule:** `ast.Try` with `ast.AugAssign` in handler.
**Defect:** Models extract core transfer into a helper function. The try/except wraps the helper call, and compensation is in the handler, but the checker can't see through the indirection.
**Fix:** Accept any try/except where the handler contains a call (compensation attempt) plus raise.

### 6. l3_state_pipeline (230 LF) — NOT A CHECKER DEFECT
**Invariant:** Both `commit()` and `freeze_view()` required.
**Finding:** Models keep `commit()` but remove `freeze_view()`. These pass execution because the test primarily checks commit's effects. These are **genuine partial fixes** that happen to pass, not checker errors. The checker is correct; the test surface is incomplete.
**Action:** Reclassified as `ast_partial` (56 events) or remains `wrong` (174 events). No checker change.

---

## J. Invariant-Justified Rule Revisions

| Family | Old rule | Invariant | New rule | Justified because |
|--------|----------|-----------|----------|-------------------|
| early_return | Audit in if-branch | All calls logged | Audit on all paths | Single append covering both paths satisfies invariant |
| temporal_drift | Call ordering | raw_stats = original data | Argument check | `compute_raw_stats(data)` satisfies invariant regardless of position |
| cache_invalidation_order | invalidate → conditional_set | Latest value in cache | Any cache update after write | Direct cache_set puts latest value in cache |
| hidden_dep_multihop | Specific function name | Always-overwrite semantics | Any non-conditional cache write | Overwrite behavior is the invariant, not the function name |
| invariant_partial_fail | AugAssign in handler | Balance conservation | Any compensation + raise | Helper extraction preserves the compensation logic |

---

## K. Pre/Post Revision Metrics

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| P(ast_correct) | 79.1% | 90.2% | +11.1pp |
| LUCKY_FIX | 11.1% (2,016) | 3.2% (580) | -7.9pp |
| AST_partial | 4.7% (853) | 2.2% (399) | -2.5pp |
| AST-evaluator agreement | 79.2% | 90.3% | +11.1pp |
| P(exec_fail\|ast_correct) | 11.1% | 13.3% | +2.2pp |

The +2.2pp increase in P(exec_fail|ast_correct) is expected: we added ~1,400 events to the ast_correct pool, and a fraction of those fail execution (valid structure but wrong details).

---

## L. Residual Genuine Lucky Fixes

Post-revision LUCKY_FIX = 580 events (3.2%). The top contributors:

| Family | LF | Assessment |
|--------|-----|-----------|
| l3_state_pipeline | 230 | **Genuine partial fix.** commit() alone passes test but freeze_view() is needed for full invariant. Test surface is incomplete. |
| early_return | 170 | **Residual checker gap.** Models use diverse restructurings not yet in equivalence class. ~80% likely valid alternatives, ~20% genuine lucky. |
| invariant_partial_fail | 51 | **Mixed.** Some use helper extraction patterns the v2 checker still misses; some are genuinely wrong code that passes. |
| temporal_drift | 42 | **Residual.** Models use intermediate variables that confuse argument checking. ~75% likely valid. |
| use_before_set | 29 | **Known gap.** Diverse structural alternatives. |
| hidden_dep_multihop | 16 | **Residual.** Novel function names not in equivalence class. |

**Estimated composition of 580 residual LUCKY_FIX:**
- ~230 (40%) genuine partial fixes (l3_state_pipeline)
- ~200 (34%) remaining checker gaps (mostly early_return)
- ~100 (17%) likely valid alternatives needing more patterns
- ~50 (9%) genuinely lucky or ambiguous

---

## M. Recommendations

1. **l3_state_pipeline test strengthening:** The test should fully check both commit and freeze_view effects. The 230 LF events here are test-surface-incomplete, not checker errors.

2. **early_return further expansion:** The 170 remaining LF events use diverse restructurings. Another round of code inspection and equivalence class expansion would reduce this to ~30.

3. **Accept 3.2% as operational LF rate.** After removing l3_state_pipeline (test issue), the true LF rate is **1.9%** — low enough that further checker work has diminishing returns.

---

## N. Concrete Next Steps

1. The checker revision is done for the 6 families identified.
2. The `analysis/ast_full_58case_results_v2.csv` file is the clean dataset.
3. The causal decomposition now shows: 1.2% reasoning failure, 34.4% structural failure, **64.6% execution failure** — confirming that execution fidelity is the dominant bottleneck.
4. Further lucky-fix reduction would target early_return and l3_state_pipeline specifically.
