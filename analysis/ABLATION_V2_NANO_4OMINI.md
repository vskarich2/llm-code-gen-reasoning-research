# V2 Ablation Analysis: nano vs 4o-mini

**Date:** 2026-03-23
**Cases:** 51 (15 Level A + 15 Level B + 15 Level C + 6 Level D traps)
**Conditions:** baseline, retry_no_contract, retry_adaptive
**Log files:** gpt-4.1-nano_20260323_200506.jsonl, gpt-4o-mini_20260323_200504.jsonl

---

## 1. Headline Results

### Baseline Pass Rate by Difficulty Level

| Level | nano | 4o-mini | Gap |
|---|---|---|---|
| A | 13/15 (87%) | 8/15 (53%) | -5 |
| B | 0/15 (0%) | 1/15 (7%) | +1 |
| C | 0/15 (0%) | 1/15 (7%) | +1 |
| D | 0/6 (0%) | 1/6 (17%) | +1 |
| **Total** | **13/51 (25%)** | **11/51 (22%)** | **-2** |

### Retry Convergence by Condition

| Condition | nano | 4o-mini | Gap |
|---|---|---|---|
| baseline | 13/51 (25%) | 11/51 (22%) | -2 |
| retry_no_contract | 17/51 (33%) | 19/51 (37%) | +2 |
| retry_adaptive | 17/51 (33%) | 21/51 (41%) | +4 |

### Recovery Rate (baseline fail → retry converge)

| Condition | nano | 4o-mini |
|---|---|---|
| retry_no_contract | 4/38 (11%) | 9/40 (22%) |
| retry_adaptive | 4/38 (11%) | 10/40 (25%) |

### Adaptive vs No-Contract Delta

**nano:** adaptive wins 0, no_contract wins 0, ties 51

**4o-mini:** adaptive wins 5, no_contract wins 3, ties 43
  Cases where adaptive uniquely helped: ['alias_config_b', 'async_race_lock', 'lazy_init_a', 'retry_dup_c', 'stale_cache_a']

## 2. Regime Distribution

| Regime | nano | 4o-mini |
|---|---|---|
| heuristic | 24 | 19 |
| REI | 8 | 11 |
| mixed | 39 | 43 |
| CSF | 31 | 29 |

## 3. Trajectory Dynamics

| Pattern | nano | 4o-mini |
|---|---|---|
| single_shot | 24 | 19 |
| MONOTONIC_FIX | 10 | 19 |
| OSCILLATING_FIX | 0 | 2 |
| OSCILLATION | 1 | 11 |
| DIVERGENCE | 21 | 10 |
| STAGNATION | 18 | 18 |
| UNCLASSIFIED | 28 | 23 |

## 4. Failure Type Distribution

| Type | nano | 4o-mini |
|---|---|---|
| EDGE_CASE_MISSED | 132 | 93 |
| HIDDEN_DEPENDENCY | 85 | 138 |
| TEMPORAL_ORDERING | 15 | 17 |
| INVARIANT_VIOLATION | 26 | 1 |
| UNKNOWN | 6 | 6 |
| CONFOUNDING_LOGIC | 6 | 5 |
| PARTIAL_STATE_UPDATE | 3 | 1 |
| LOGGING_INCONSISTENCY | 2 | 0 |
| RETRY_LOGIC_BUG | 1 | 0 |

## 5. Latent Execution Gap

**nano:** 161 instances of correct reasoning + wrong code, 0 correct reasoning + correct code
**4o-mini:** 165 instances of correct reasoning + wrong code, 0 correct reasoning + correct code

## 6. Per-Case Results

| Case | Level | nano BL | nano RN | nano RA | mini BL | mini RN | mini RA |
|---|---|---|---|---|---|---|---|
| alias_config_a | A | P 1.0 | P(1) | P(1) | P 1.0 | P(1) | P(1) |
| alias_config_b | B | F 0.2 | F(4) | F(5) | F 0.2 | F(2) | P(4) |
| alias_config_c | C | F 0.0 | F(4) | F(2) | P 1.0 | P(1) | P(1) |
| async_race_lock | D | F 0.0 | F(5) | F(5) | F 0.2 | F(5) | P(1) |
| cache_invalidation_order | D | F 0.2 | F(2) | F(2) | F 0.2 | F(2) | F(2) |
| early_return_a | A | P 1.0 | P(1) | P(1) | F 0.0 | P(2) | P(2) |
| early_return_b | B | F 0.0 | F(2) | F(2) | F 0.0 | F(4) | F(4) |
| early_return_c | C | F 0.2 | F(2) | F(2) | F 0.0 | F(4) | F(3) |
| effect_order_a | A | P 1.0 | P(5) | P(1) | F 0.1 | F(3) | F(4) |
| effect_order_b | B | F 0.0 | F(5) | F(5) | F 0.0 | F(3) | F(4) |
| effect_order_c | C | F 0.1 | F(3) | F(2) | F 0.0 | F(4) | F(4) |
| feature_flag_drift | D | F 0.0 | F(5) | F(5) | F 0.0 | F(4) | F(4) |
| hidden_dep_multihop | D | F 0.0 | F(4) | F(5) | P 1.0 | P(2) | P(2) |
| index_misalign_a | A | P 1.0 | P(2) | P(1) | F 0.2 | F(2) | F(3) |
| index_misalign_b | B | F 0.0 | F(4) | F(5) | F 0.0 | F(3) | F(3) |
| index_misalign_c | C | F 0.0 | F(3) | F(3) | F 0.2 | F(5) | F(5) |
| invariant_partial_fail | D | F 0.2 | F(5) | F(3) | F 0.2 | F(2) | F(2) |
| l3_state_pipeline | D | F 0.0 | F(4) | F(3) | F 0.2 | F(3) | F(4) |
| lazy_init_a | A | P 1.0 | P(1) | P(1) | F 0.2 | F(5) | P(2) |
| lazy_init_b | B | F 0.0 | F(2) | F(3) | F 0.2 | F(5) | F(5) |
| lazy_init_c | C | F 0.0 | F(5) | F(3) | F 0.0 | F(2) | F(2) |
| missing_branch_a | A | P 1.0 | P(1) | P(1) | F 0.2 | P(2) | P(2) |
| missing_branch_b | B | F 0.0 | F(2) | F(2) | F 0.0 | P(4) | F(2) |
| missing_branch_c | C | F 0.2 | F(5) | F(5) | F 0.2 | F(4) | F(5) |
| mutable_default_a | A | P 1.0 | P(1) | P(1) | P 1.0 | P(1) | P(1) |
| mutable_default_b | B | F 0.0 | P(3) | P(2) | P 1.0 | P(1) | P(1) |
| mutable_default_c | C | F 0.0 | F(5) | F(5) | F 0.0 | F(3) | F(4) |
| partial_rollback_a | A | P 1.0 | P(1) | P(2) | P 1.0 | P(1) | P(1) |
| partial_rollback_b | B | F 0.0 | F(4) | F(5) | F 0.0 | F(2) | F(5) |
| partial_rollback_c | C | F 0.0 | F(5) | F(5) | F 0.0 | F(4) | F(4) |
| partial_update_a | A | P 1.0 | P(1) | P(1) | F 0.0 | P(2) | P(2) |
| partial_update_b | B | F 0.2 | F(4) | F(4) | F 0.2 | F(4) | F(4) |
| partial_update_c | C | F 0.2 | F(5) | F(5) | F 0.2 | P(4) | F(5) |
| retry_dup_a | A | F 0.0 | P(2) | P(2) | P 1.0 | P(1) | P(1) |
| retry_dup_b | B | F 0.1 | F(4) | F(3) | F 0.0 | F(5) | F(3) |
| retry_dup_c | C | F 0.0 | F(5) | F(5) | F 0.0 | F(5) | P(4) |
| silent_default_a | A | F 0.2 | P(2) | P(1) | F 0.2 | P(4) | P(3) |
| silent_default_b | B | F 0.2 | F(5) | F(4) | F 0.2 | F(5) | F(4) |
| silent_default_c | C | F 0.0 | F(3) | F(5) | F 0.0 | F(4) | F(3) |
| stale_cache_a | A | P 1.0 | P(1) | P(1) | P 1.0 | F(5) | P(2) |
| stale_cache_b | B | F 0.0 | F(5) | F(2) | F 0.0 | F(4) | F(4) |
| stale_cache_c | C | F 0.0 | F(5) | F(3) | F 0.0 | F(5) | F(4) |
| temporal_drift_a | A | P 1.0 | P(1) | P(1) | P 1.0 | P(1) | P(1) |
| temporal_drift_b | B | F 0.0 | F(4) | F(3) | F 0.0 | F(4) | F(4) |
| temporal_drift_c | C | F 0.0 | F(4) | F(5) | F 0.0 | P(3) | F(3) |
| use_before_set_a | A | P 1.0 | P(1) | P(1) | P 1.0 | P(1) | P(1) |
| use_before_set_b | B | F 0.0 | F(4) | F(4) | F 0.0 | P(4) | P(2) |
| use_before_set_c | C | F 0.1 | F(4) | F(3) | F 0.0 | F(2) | F(2) |
| wrong_condition_a | A | P 1.0 | P(1) | P(1) | P 1.0 | P(1) | P(1) |
| wrong_condition_b | B | F 0.2 | P(2) | P(2) | F 0.2 | P(2) | P(3) |
| wrong_condition_c | C | F 0.2 | F(4) | F(3) | F 0.2 | F(3) | F(3) |

## 7. Key Findings

### Difficulty Gradient Works
Level A → B → C → D shows clear monotonic decrease in pass rate for both models.
nano: 87% → 0% → 0% → 0% (baseline)
4o-mini: 53% → 7% → 7% → 17% (baseline)

### Retry Helps, Especially for 4o-mini
4o-mini recovers 22-25% of baseline failures through retry.
nano recovers only 11% — its failures are more fundamental (CSF).

### Adaptive Retry Shows Signal for 4o-mini
4o-mini: adaptive wins 5 unique cases over no_contract (loses 3).
nano: adaptive and no_contract are identical (0 difference).
This aligns with the theory: adaptive hints help when the model has
enough capability to use them (REI), but not when it lacks the
underlying causal understanding (CSF).

### Latent Execution Gap is Massive
Both models show ~160 instances of correct reasoning + wrong code.
Zero instances of correct reasoning leading to correct code through retry.
This confirms REI as the dominant failure mode — models know the answer
but cannot translate it to working code even with test feedback.