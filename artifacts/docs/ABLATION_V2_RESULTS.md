# V2 Ablation Results — Full Analysis
Generated: 2026-03-24T10:32:06

## 1. Experiment Summary

- **Total eval calls**: 695/696 (1 timeout: gpt-5.4-mini/lost_update/baseline trial 2)
- **Cases**: 58
- **Conditions**: baseline, leg_reduction
- **Models**: gpt-4o-mini, gpt-5-mini, gpt-5.4-mini
- **Trials per cell**: 2
- **Wall-clock time**: 42.7 minutes
- **Throughput**: 0.27 eval calls/sec

## 2. Overall Metrics

| Metric | Value |
|--------|-------|
| Pass rate | 66.9% (465/695) |
| Fail rate | 33.1% (230/695) |
| Reasoning correct | 75.5% (525/695) |
| Code correct | 66.9% (465/695) |

### 2×2 Reasoning × Code Matrix

|  | Code correct | Code wrong | Total |
|--|-------------|-----------|-------|
| **Reasoning correct** | 388 true success | 137 **LEG** | 525 |
| **Reasoning wrong** | 77 lucky fix | 93 true failure | 170 |
| **Total** | 465 | 230 | 695 |

- **LEG rate**: 19.7% — model understood the bug but wrote broken code
- **Lucky fix rate**: 11.1% — model got code right for wrong reasons
- **Alignment rate**: 55.8% — reasoning and code both correct
- **Misalignment rate**: 30.8% — reasoning and code disagree

## 3. Condition Comparison (Key Result)

| Condition | N | Pass% | LEG% | Lucky% | True Success% | True Failure% |
|-----------|---|-------|------|--------|--------------|---------------|
| baseline | 347 | 68.6% | 25.1% | 3.2% | 65.4% | 6.3% |
| leg_reduction | 348 | 65.2% | 14.4% | 19.0% | 46.3% | 20.4% |

### Intervention Effect

- **Pass rate delta**: -3.4pp (intervention hurts)
- **LEG rate delta**: -10.7pp (fewer gaps — intervention closes LEG)
- **Lucky fix delta**: +15.8pp (more lucky fixes)

**Interpretation**: Leg reduction reduces the Latent Execution Gap by 10.7pp — when the model reasons correctly, the plan→verify→revise cycle helps translate that understanding into working code. The pass rate cost of 3.4pp suggests the structured format disrupts some heuristic/pattern-matching successes (lucky fixes rise by 15.8pp).

## 4. Model Breakdown

| Model | N | Pass% | LEG% | Lucky% | Align% |
|-------|---|-------|------|--------|--------|
| gpt-4o-mini | 232 | 64.7% | 19.8% | 8.6% | 56.0% |
| gpt-5-mini | 232 | 60.8% | 28.4% | 9.9% | 50.9% |
| gpt-5.4-mini | 231 | 75.3% | 10.8% | 14.7% | 60.6% |

### Model × Condition Interaction

| Model | Condition | N | Pass% | LEG% |
|-------|-----------|---|-------|------|
| gpt-4o-mini | baseline | 116 | 73.3% | 21.6% |
| gpt-4o-mini | leg_reduction | 116 | 56.0% | 18.1% |
| gpt-5-mini | baseline | 116 | 52.6% | 40.5% |
| gpt-5-mini | leg_reduction | 116 | 69.0% | 16.4% |
| gpt-5.4-mini | baseline | 115 | 80.0% | 13.0% |
| gpt-5.4-mini | leg_reduction | 116 | 70.7% | 8.6% |

### Per-Model Intervention Effect

| Model | Baseline Pass% | LegRed Pass% | Δ Pass | Baseline LEG% | LegRed LEG% | Δ LEG |
|-------|---------------|-------------|--------|--------------|------------|-------|
| gpt-4o-mini | 73.3% | 56.0% | -17.2pp | 21.6% | 18.1% | -3.4pp |
| gpt-5-mini | 52.6% | 69.0% | +16.4pp | 40.5% | 16.4% | -24.1pp |
| gpt-5.4-mini | 80.0% | 70.7% | -9.3pp | 13.0% | 8.6% | -4.4pp |

## 5. Failure Type Breakdown

| Failure Type | Count | % of Failures |
|-------------|-------|---------------|
| CONFOUNDING_LOGIC | 101 | 43.9% |
| PARTIAL_STATE_UPDATE | 76 | 33.0% |
| INVARIANT_VIOLATION | 29 | 12.6% |
| UNKNOWN | 10 | 4.3% |
| TEMPORAL_ORDERING | 6 | 2.6% |
| RETRY_LOGIC_BUG | 5 | 2.2% |
| LOGGING_INCONSISTENCY | 2 | 0.9% |
| HIDDEN_DEPENDENCY | 1 | 0.4% |

## 6. Case-Level Analysis

### Hardest Cases (lowest pass rate)

| Case | N | Pass% | LEG% | Lucky% | Failure Mode |
|------|---|-------|------|--------|-------------|
| async_race_lock | 12 | 0.0% | 50.0% | 0.0% | RACE_CONDITION |
| l3_state_pipeline | 12 | 0.0% | 50.0% | 0.0% | STATE_SEMANTIC_VIOLATION |
| false_fix_deadlock | 12 | 8.3% | 58.3% | 0.0% | RACE_CONDITION |
| hidden_dep_multihop | 12 | 8.3% | 25.0% | 0.0% | HIDDEN_DEPENDENCY |
| invariant_partial_fail | 12 | 8.3% | 75.0% | 8.3% | INVARIANT_VIOLATION |
| mutable_default_b | 12 | 16.7% | 58.3% | 0.0% | MUTABLE_DEFAULT |
| use_before_set_b | 12 | 25.0% | 50.0% | 8.3% | USE_BEFORE_SET |
| cache_invalidation_order | 12 | 33.3% | 25.0% | 0.0% | CACHE_ORDERING |
| commit_gate | 12 | 33.3% | 33.3% | 33.3% | INVARIANT_VIOLATION |
| feature_flag_drift | 12 | 33.3% | 41.7% | 16.7% | FLAG_DRIFT |
| retry_dup_c | 12 | 33.3% | 16.7% | 33.3% | RETRY_DUPLICATION |
| early_return_c | 12 | 50.0% | 16.7% | 8.3% | EARLY_RETURN |
| lazy_init_c | 12 | 50.0% | 41.7% | 8.3% | INIT_ORDER |
| use_before_set_c | 12 | 50.0% | 16.7% | 25.0% | USE_BEFORE_SET |
| effect_order_b | 12 | 58.3% | 25.0% | 8.3% | SIDE_EFFECT_ORDER |

### Highest LEG Rate Cases

| Case | N | Pass% | LEG% | Failure Mode |
|------|---|-------|------|-------------|
| invariant_partial_fail | 12 | 8.3% | 75.0% | INVARIANT_VIOLATION |
| false_fix_deadlock | 12 | 8.3% | 58.3% | RACE_CONDITION |
| mutable_default_b | 12 | 16.7% | 58.3% | MUTABLE_DEFAULT |
| async_race_lock | 12 | 0.0% | 50.0% | RACE_CONDITION |
| l3_state_pipeline | 12 | 0.0% | 50.0% | STATE_SEMANTIC_VIOLATION |
| use_before_set_b | 12 | 25.0% | 50.0% | USE_BEFORE_SET |
| feature_flag_drift | 12 | 33.3% | 41.7% | FLAG_DRIFT |
| lazy_init_c | 12 | 50.0% | 41.7% | INIT_ORDER |
| missing_branch_a | 12 | 58.3% | 41.7% | MISSING_BRANCH |
| missing_branch_c | 12 | 58.3% | 41.7% | MISSING_BRANCH |
| commit_gate | 12 | 33.3% | 33.3% | INVARIANT_VIOLATION |
| wrong_condition_b | 12 | 66.7% | 33.3% | WRONG_CONDITION |
| lost_update | 11 | 63.6% | 27.3% | RACE_CONDITION |
| alias_config_c | 12 | 75.0% | 25.0% | ALIASING |
| cache_invalidation_order | 12 | 33.3% | 25.0% | CACHE_ORDERING |

### Highest Lucky Fix Rate Cases

| Case | N | Pass% | Lucky% | Failure Mode |
|------|---|-------|--------|-------------|
| retry_dup_b | 12 | 83.3% | 50.0% | RETRY_DUPLICATION |
| silent_default_c | 12 | 75.0% | 50.0% | SILENT_DEFAULT |
| early_return_b | 12 | 75.0% | 41.7% | EARLY_RETURN |
| partial_rollback_c | 12 | 83.3% | 41.7% | PARTIAL_ROLLBACK |
| commit_gate | 12 | 33.3% | 33.3% | INVARIANT_VIOLATION |
| retry_dup_c | 12 | 33.3% | 33.3% | RETRY_DUPLICATION |
| lost_update | 11 | 63.6% | 27.3% | RACE_CONDITION |
| overdetermination | 12 | 83.3% | 25.0% | HIDDEN_DEPENDENCY |
| partial_update_b | 12 | 91.7% | 25.0% | PARTIAL_STATE_UPDATE |
| retry_dup_a | 12 | 100.0% | 25.0% | RETRY_DUPLICATION |

## 7. Stability Across Trials

- **Total (case, condition, model) cells with 2 trials**: 347
- **Cells where trials disagreed (pass in one, fail in other)**: 56
- **Disagreement rate**: 16.1%

### Unstable Cases (trials disagreed)

| Case | Condition | Model | Trial Results |
|------|-----------|-------|---------------|
| alias_config_b | leg_reduction | gpt-5.4-mini | [1, 0] |
| alias_config_c | baseline | gpt-4o-mini | [1, 0] |
| alias_config_c | baseline | gpt-5-mini | [0, 1] |
| alias_config_c | baseline | gpt-5.4-mini | [1, 0] |
| config_shadowing | leg_reduction | gpt-5-mini | [0, 1] |
| config_shadowing | leg_reduction | gpt-5.4-mini | [0, 1] |
| early_return_a | leg_reduction | gpt-5-mini | [1, 0] |
| early_return_b | leg_reduction | gpt-5.4-mini | [1, 0] |
| early_return_c | baseline | gpt-5-mini | [1, 0] |
| early_return_c | leg_reduction | gpt-5.4-mini | [0, 1] |
| effect_order_b | leg_reduction | gpt-5.4-mini | [1, 0] |
| false_fix_deadlock | baseline | gpt-5-mini | [1, 0] |
| feature_flag_drift | baseline | gpt-5-mini | [1, 0] |
| feature_flag_drift | leg_reduction | gpt-5-mini | [0, 1] |
| hidden_dep_multihop | baseline | gpt-5.4-mini | [1, 0] |
| index_misalign_a | baseline | gpt-4o-mini | [1, 0] |
| index_misalign_b | leg_reduction | gpt-5.4-mini | [0, 1] |
| index_misalign_c | leg_reduction | gpt-5.4-mini | [1, 0] |
| invariant_partial_fail | leg_reduction | gpt-4o-mini | [1, 0] |
| lazy_init_a | baseline | gpt-4o-mini | [0, 1] |
| lazy_init_a | leg_reduction | gpt-5.4-mini | [0, 1] |
| lazy_init_b | leg_reduction | gpt-5-mini | [1, 0] |
| lazy_init_c | baseline | gpt-5-mini | [0, 1] |
| lazy_init_c | leg_reduction | gpt-5-mini | [1, 0] |
| missing_branch_a | leg_reduction | gpt-5-mini | [1, 0] |
| missing_branch_b | baseline | gpt-4o-mini | [1, 0] |
| missing_branch_c | baseline | gpt-4o-mini | [0, 1] |
| missing_branch_c | baseline | gpt-5-mini | [0, 1] |
| missing_branch_c | leg_reduction | gpt-4o-mini | [0, 1] |
| mutable_default_b | baseline | gpt-5-mini | [1, 0] |
| mutable_default_b | leg_reduction | gpt-5-mini | [0, 1] |
| mutable_default_c | baseline | gpt-5-mini | [1, 0] |
| mutable_default_c | leg_reduction | gpt-5-mini | [1, 0] |
| partial_rollback_a | leg_reduction | gpt-5-mini | [0, 1] |
| partial_rollback_b | baseline | gpt-4o-mini | [0, 1] |
| partial_rollback_b | baseline | gpt-5-mini | [1, 0] |
| partial_rollback_b | leg_reduction | gpt-5-mini | [1, 0] |
| partial_update_a | leg_reduction | gpt-5-mini | [1, 0] |
| partial_update_a | leg_reduction | gpt-5.4-mini | [0, 1] |
| partial_update_b | leg_reduction | gpt-4o-mini | [1, 0] |
| silent_default_a | leg_reduction | gpt-5-mini | [0, 1] |
| silent_default_c | baseline | gpt-5-mini | [0, 1] |
| stale_cache_b | baseline | gpt-5-mini | [1, 0] |
| stale_cache_c | leg_reduction | gpt-5-mini | [1, 0] |
| stale_cache_c | leg_reduction | gpt-5.4-mini | [1, 0] |
| temporal_drift_b | baseline | gpt-5-mini | [1, 0] |
| temporal_drift_c | leg_reduction | gpt-4o-mini | [0, 1] |
| temporal_drift_c | leg_reduction | gpt-5.4-mini | [1, 0] |
| use_before_set_b | baseline | gpt-4o-mini | [1, 0] |
| use_before_set_c | baseline | gpt-5.4-mini | [1, 0] |
| use_before_set_c | leg_reduction | gpt-5.4-mini | [1, 0] |
| wrong_condition_a | leg_reduction | gpt-4o-mini | [0, 1] |
| wrong_condition_a | leg_reduction | gpt-5.4-mini | [0, 1] |
| wrong_condition_b | leg_reduction | gpt-5-mini | [0, 1] |
| wrong_condition_b | leg_reduction | gpt-5.4-mini | [0, 1] |
| wrong_condition_c | baseline | gpt-5-mini | [0, 1] |

## 8. Performance by Failure Mode

| Failure Mode | N | Pass% | LEG% | Lucky% |
|-------------|---|-------|------|--------|
| STATE_SEMANTIC_VIOLATION | 12 | 0.0% | 50.0% | 0.0% |
| INVARIANT_VIOLATION | 24 | 20.8% | 54.2% | 20.8% |
| CACHE_ORDERING | 12 | 33.3% | 25.0% | 0.0% |
| FLAG_DRIFT | 12 | 33.3% | 41.7% | 16.7% |
| RACE_CONDITION | 47 | 38.3% | 38.3% | 6.4% |
| HIDDEN_DEPENDENCY | 24 | 45.8% | 20.8% | 12.5% |
| USE_BEFORE_SET | 36 | 52.8% | 22.2% | 16.7% |
| MUTABLE_DEFAULT | 36 | 61.1% | 25.0% | 0.0% |
| MISSING_BRANCH | 36 | 63.9% | 36.1% | 0.0% |
| EARLY_RETURN | 36 | 66.7% | 16.7% | 16.7% |
| INIT_ORDER | 36 | 69.4% | 19.4% | 5.6% |
| SIDE_EFFECT_ORDER | 36 | 69.4% | 22.2% | 5.6% |
| RETRY_DUPLICATION | 36 | 72.2% | 11.1% | 36.1% |
| WRONG_CONDITION | 36 | 75.0% | 16.7% | 2.8% |
| SILENT_DEFAULT | 36 | 77.8% | 2.8% | 25.0% |
| PARTIAL_STATE_UPDATE | 48 | 81.2% | 12.5% | 16.7% |
| PARTIAL_ROLLBACK | 36 | 83.3% | 13.9% | 16.7% |
| TEMPORAL_ORDERING | 12 | 83.3% | 0.0% | 8.3% |
| STALE_CACHE | 36 | 86.1% | 11.1% | 5.6% |
| TEMPORAL_DRIFT | 36 | 86.1% | 8.3% | 11.1% |
| INDEX_MISALIGN | 36 | 86.1% | 11.1% | 2.8% |
| ALIASING | 36 | 88.9% | 8.3% | 8.3% |

## 9. Performance

- **Avg time per eval**: 12.7s
- **Median time per eval**: 9.4s
- **Min/Max**: 2.2s / 100.4s
- **baseline avg**: 12.7s

## 10. Full Case × Condition Pass Rate Table

| Case | gpt-4o-mini BL | gpt-4o-mini LR | gpt-5-mini BL | gpt-5-mini LR | gpt-5.4-mini BL | gpt-5.4-mini LR |
|------|------|------|------|------|------|------|
| alias_config_a | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| alias_config_b | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| alias_config_c | 1/2 | 2/2 | 1/2 | 2/2 | 1/2 | 2/2 |
| async_race_lock | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| cache_invalidation_order | 0/2 | 2/2 | 0/2 | 2/2 | 0/2 | 0/2 |
| check_then_act | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| commit_gate | 0/2 | 2/2 | 0/2 | 2/2 | 0/2 | 0/2 |
| config_shadowing | 2/2 | 2/2 | 0/2 | 1/2 | 2/2 | 1/2 |
| early_return_a | 2/2 | 0/2 | 2/2 | 1/2 | 2/2 | 2/2 |
| early_return_b | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 1/2 |
| early_return_c | 2/2 | 0/2 | 1/2 | 0/2 | 2/2 | 1/2 |
| effect_order_a | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| effect_order_b | 2/2 | 2/2 | 0/2 | 0/2 | 2/2 | 1/2 |
| effect_order_c | 2/2 | 2/2 | 0/2 | 0/2 | 2/2 | 2/2 |
| false_fix_deadlock | 0/2 | 0/2 | 1/2 | 0/2 | 0/2 | 0/2 |
| feature_flag_drift | 0/2 | 0/2 | 1/2 | 1/2 | 0/2 | 2/2 |
| hidden_dep_multihop | 0/2 | 0/2 | 0/2 | 0/2 | 1/2 | 0/2 |
| index_misalign_a | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| index_misalign_b | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 1/2 |
| index_misalign_c | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| invariant_partial_fail | 0/2 | 1/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| l3_state_pipeline | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| lazy_init_a | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| lazy_init_b | 2/2 | 2/2 | 0/2 | 1/2 | 2/2 | 2/2 |
| lazy_init_c | 2/2 | 0/2 | 1/2 | 1/2 | 2/2 | 0/2 |
| lost_update | 0/2 | 0/2 | 2/2 | 2/2 | 1/1 | 2/2 |
| missing_branch_a | 0/2 | 0/2 | 2/2 | 1/2 | 2/2 | 2/2 |
| missing_branch_b | 1/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| missing_branch_c | 1/2 | 1/2 | 1/2 | 0/2 | 2/2 | 2/2 |
| mutable_default_a | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| mutable_default_b | 0/2 | 0/2 | 1/2 | 1/2 | 0/2 | 0/2 |
| mutable_default_c | 2/2 | 0/2 | 1/2 | 1/2 | 2/2 | 2/2 |
| ordering_dependency | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| overdetermination | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 |
| partial_rollback_a | 2/2 | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 |
| partial_rollback_b | 1/2 | 2/2 | 1/2 | 1/2 | 2/2 | 2/2 |
| partial_rollback_c | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 |
| partial_update_a | 2/2 | 2/2 | 2/2 | 1/2 | 2/2 | 1/2 |
| partial_update_b | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| partial_update_c | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 |
| retry_dup_a | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| retry_dup_b | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 |
| retry_dup_c | 2/2 | 2/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| silent_default_a | 0/2 | 0/2 | 2/2 | 1/2 | 2/2 | 2/2 |
| silent_default_b | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| silent_default_c | 2/2 | 0/2 | 1/2 | 2/2 | 2/2 | 2/2 |
| stale_cache_a | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| stale_cache_b | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 |
| stale_cache_c | 2/2 | 2/2 | 0/2 | 1/2 | 2/2 | 1/2 |
| temporal_drift_a | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| temporal_drift_b | 2/2 | 0/2 | 1/2 | 2/2 | 2/2 | 2/2 |
| temporal_drift_c | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| use_before_set_a | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| use_before_set_b | 1/2 | 0/2 | 0/2 | 0/2 | 0/2 | 2/2 |
| use_before_set_c | 2/2 | 0/2 | 0/2 | 2/2 | 1/2 | 1/2 |
| wrong_condition_a | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 1/2 |
| wrong_condition_b | 2/2 | 2/2 | 0/2 | 1/2 | 2/2 | 1/2 |
| wrong_condition_c | 2/2 | 0/2 | 1/2 | 2/2 | 2/2 | 2/2 |
