# Buggy Variant Generation Report

**Total cases:** 58
**Total variants:** 290 (5 per case)
**Correctly rejected by oracle:** 256 (88.3%)
**Incorrectly passed:** 34

## Per-Case Results

| Case | Valid/5 | Issues |
|------|---------|--------|
| alias_config_a | 4/5 | 1 variants pass (mutator mismatch) |
| alias_config_b | 4/5 | 1 variants pass (mutator mismatch) |
| alias_config_c | 3/5 | 2 variants pass (mutator mismatch) |
| async_race_lock | 5/5 | None |
| cache_invalidation_order | 5/5 | None |
| check_then_act | 5/5 | None |
| commit_gate | 5/5 | None |
| config_shadowing | 5/5 | None |
| early_return_a | 5/5 | None |
| early_return_b | 1/5 | 4 variants pass (mutator mismatch) |
| early_return_c | 1/5 | 4 variants pass (mutator mismatch) |
| effect_order_a | 5/5 | None |
| effect_order_b | 5/5 | None |
| effect_order_c | 5/5 | None |
| false_fix_deadlock | 5/5 | None |
| feature_flag_drift | 5/5 | None |
| hidden_dep_multihop | 5/5 | None |
| index_misalign_a | 5/5 | None |
| index_misalign_b | 5/5 | None |
| index_misalign_c | 5/5 | None |
| invariant_partial_fail | 5/5 | None |
| l3_state_pipeline | 5/5 | None |
| lazy_init_a | 5/5 | None |
| lazy_init_b | 5/5 | None |
| lazy_init_c | 5/5 | None |
| lost_update | 5/5 | None |
| missing_branch_a | 5/5 | None |
| missing_branch_b | 5/5 | None |
| missing_branch_c | 5/5 | None |
| mutable_default_a | 5/5 | None |
| mutable_default_b | 5/5 | None |
| mutable_default_c | 1/5 | 4 variants pass (mutator mismatch) |
| ordering_dependency | 5/5 | None |
| overdetermination | 5/5 | None |
| partial_rollback_a | 5/5 | None |
| partial_rollback_b | 5/5 | None |
| partial_rollback_c | 5/5 | None |
| partial_update_a | 4/5 | 1 variants pass (mutator mismatch) |
| partial_update_b | 1/5 | 4 variants pass (mutator mismatch) |
| partial_update_c | 1/5 | 4 variants pass (mutator mismatch) |
| retry_dup_a | 5/5 | None |
| retry_dup_b | 5/5 | None |
| retry_dup_c | 5/5 | None |
| silent_default_a | 5/5 | None |
| silent_default_b | 5/5 | None |
| silent_default_c | 5/5 | None |
| stale_cache_a | 4/5 | 1 variants pass (mutator mismatch) |
| stale_cache_b | 1/5 | 4 variants pass (mutator mismatch) |
| stale_cache_c | 1/5 | 4 variants pass (mutator mismatch) |
| temporal_drift_a | 5/5 | None |
| temporal_drift_b | 5/5 | None |
| temporal_drift_c | 5/5 | None |
| use_before_set_a | 5/5 | None |
| use_before_set_b | 5/5 | None |
| use_before_set_c | 5/5 | None |
| wrong_condition_a | 5/5 | None |
| wrong_condition_b | 5/5 | None |
| wrong_condition_c | 5/5 | None |

## Key Findings

1. **46/58 cases (79%) have perfect 5/5 variant coverage** — all buggy variants correctly fail
2. **12 cases have partial coverage** — custom mutators produce accidentally-correct code for B/C difficulty variants
3. **The oracle (tests_v2) is robust** — when a variant is genuinely buggy, the test catches it
4. **The mutator engineering is the bottleneck**, not the oracle

## Root Cause of Failures

All 34 "invalid" variants are cases where:
- The string replacement in the mutator did not match the target code
- The mutator silently returned the reference fix (correct code)
- The oracle correctly passed it (because it IS correct)

**Zero cases of oracle weakness detected** — no genuinely buggy code passes the tests.