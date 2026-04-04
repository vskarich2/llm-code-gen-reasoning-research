# AST + Oracle Cluster Analysis — New Runs

**Date:** 2026-04-03
**Data:** 6262 assessable oracle-labeled events from 4 new runs
**Runs:** retry_critique_stage2 (OpenAI + Anthropic), global_calibration (OpenAI + Anthropic)
**Conditions:** baseline_v2, leg_reduction_lean_v2, retry_bare_retry_v2, retry_leg_critique_strict_v2, retry_reasoning_only_critique_v1
**Models:** 8 (gpt-4.1-nano, gpt-4o-mini, gpt-5-mini, gpt-5.4-mini, gpt-5, claude-haiku-4.5, claude-sonnet-4, claude-sonnet-4.6)

---

## 1. Anchor Table

| Metric | Value |
|--------|-------|
| P(oracle_reasoning_correct) | 85.8% |
| P(ast_structural_correct) | 87.2% |
| P(exec_pass) | 73.2% |
| P(old_mechanism_correct) | 99.7% |
| Assessable events | 6262 |

---

## 2. Three-Way Decomposition

| Oracle | AST | Exec | Count | % | Category |
|--------|-----|------|-------|---|----------|
| T | T | T | 4242 | 67.7% | FULL_SUCCESS |
| T | T | F | 943 | 15.1% | EXECUTION_GAP |
| F | F | F | 551 | 8.8% | FULL_FAILURE |
| F | T | T | 170 | 2.7% | LUCKY_REASONING |
| T | F | T | 108 | 1.7% | LUCKY_FIX |
| F | T | F | 103 | 1.6% | AST_OK_REASONING_WRONG |
| T | F | F | 82 | 1.3% | STRUCTURAL_FAILURE |
| F | F | T | 63 | 1.0% | DOUBLE_LUCKY |

---

## 3. Causal Failure Decomposition

Total failures: 1679

| Stage | Count | % of failures | Description |
|-------|-------|---------------|-------------|
| 1. Reasoning | 654 | 39.0% | Oracle says reasoning wrong |
| 2. Structure | 82 | 4.9% | Reasoning correct, AST says structure wrong |
| 3. Execution | 943 | 56.2% | Reasoning + structure correct, execution fails |

---

## 4. Condition Comparison

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 374 | 61.8% | 68.2% | 8.3% | 52.9% |
| leg_reduction_lean_v2 | 405 | 59.5% | 61.7% | 22.2% | 34.6% |
| retry_bare_retry_v2 | 1806 | 87.0% | 87.8% | 73.8% | 15.2% |
| retry_leg_critique_strict_v2 | 2019 | 88.1% | 89.9% | 80.8% | 10.8% |
| retry_reasoning_only_critique_v1 | 1658 | 93.7% | 93.5% | 90.3% | 6.7% |

---

## 5. Model Comparison

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| claude-haiku-4-5-20251001 | 55 | 90.9% | 98.2% | 49.1% | 43.6% |
| claude-sonnet-4-20250514 | 110 | 100.0% | 100.0% | 100.0% | 0.0% |
| claude-sonnet-4-6 | 289 | 99.7% | 100.0% | 69.9% | 30.1% |
| gpt-4.1-nano | 1362 | 71.1% | 80.3% | 71.8% | 4.1% |
| gpt-4o-mini | 1393 | 91.0% | 88.5% | 60.7% | 28.4% |
| gpt-5 | 41 | 73.2% | 73.2% | 24.4% | 48.8% |
| gpt-5-mini | 1445 | 93.8% | 91.4% | 84.0% | 13.7% |
| gpt-5.4-mini | 1567 | 83.3% | 84.7% | 76.3% | 10.4% |

---

## 6. Case Clusters

### 6A. Execution Gap Cluster
Cases where models understand the bug AND produce correct structure but execution fails.

| Case | N | Oracle% | AST% | Pass% | ExecGap% | Difficulty | Family |
|------|---|---------|------|-------|----------|------------|--------|
| missing_branch_c | 296 | 100% | 95% | 27% | 70% | C | missing_branch |
| use_before_set_b | 286 | 99% | 99% | 37% | 62% | B | use_before_set |
| invariant_partial_fail | 554 | 97% | 91% | 33% | 57% | C | invariant_partial_fail |
| early_return_b | 215 | 100% | 97% | 71% | 26% | B | early_return |
| hidden_dep_multihop | 57 | 93% | 100% | 70% | 25% | C | hidden_dep_multihop |
| silent_default_b | 114 | 100% | 99% | 75% | 24% | B | silent_default |
| early_return_c | 107 | 100% | 99% | 79% | 21% | C | early_return |
| overdetermination | 161 | 100% | 99% | 80% | 20% | C | overdetermination |
| effect_order_c | 82 | 100% | 100% | 83% | 17% | C | effect_order |
| effect_order_b | 112 | 99% | 100% | 83% | 17% | B | effect_order |
| partial_rollback_c | 113 | 100% | 98% | 81% | 17% | C | partial_rollback |
| use_before_set_c | 78 | 87% | 82% | 76% | 15% | C | use_before_set |

#### invariant_partial_fail
- **Invariant:** sender.balance + receiver.balance must be conserved at all times
- **Fix pattern:** try/except around credit with sender.balance += amount in except block
- **N=554, Oracle=97%, AST=91%, Pass=33%, ExecGap=57%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 200 | 96% | 100% | 18% | 80% |
| claude-sonnet-4-6 | 200 | 100% | 100% | 56% | 44% |
| gpt-4o-mini | 57 | 89% | 14% | 0% | 12% |
| gpt-5 | 30 | 100% | 100% | 33% | 67% |
| claude-haiku-4-5-20251001 | 27 | 96% | 96% | 59% | 37% |
| gpt-5-mini | 26 | 92% | 100% | 19% | 81% |
| gpt-4.1-nano | 14 | 100% | 93% | 29% | 71% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 107 | 94% | 93% | 10% | 81% |
| leg_reduction_lean_v2 | 138 | 97% | 75% | 38% | 35% |
| retry_bare_retry_v2 | 136 | 97% | 97% | 12% | 83% |
| retry_leg_critique_strict_v2 | 137 | 98% | 97% | 63% | 34% |
| retry_reasoning_only_critique_v1 | 36 | 97% | 97% | 47% | 53% |

#### missing_branch_c
- **Invariant:** all valid roles must receive correct permissions
- **Fix pattern:** add missing branch/case
- **N=296, Oracle=100%, AST=95%, Pass=27%, ExecGap=70%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 211 | 100% | 93% | 12% | 82% |
| gpt-4o-mini | 29 | 100% | 100% | 76% | 24% |
| gpt-5.4-mini | 29 | 100% | 100% | 86% | 14% |
| gpt-4.1-nano | 27 | 100% | 100% | 22% | 78% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 47 | 100% | 94% | 9% | 85% |
| leg_reduction_lean_v2 | 39 | 100% | 90% | 13% | 77% |
| retry_bare_retry_v2 | 83 | 100% | 98% | 25% | 73% |
| retry_leg_critique_strict_v2 | 88 | 100% | 97% | 22% | 75% |
| retry_reasoning_only_critique_v1 | 39 | 100% | 95% | 77% | 23% |

#### use_before_set_b
- **Invariant:** function must handle empty/edge-case input without NameError
- **Fix pattern:** initialize variable before conditional
- **N=286, Oracle=99%, AST=99%, Pass=37%, ExecGap=62%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 200 | 98% | 100% | 10% | 89% |
| claude-sonnet-4-20250514 | 30 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 28 | 100% | 89% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 50 | 98% | 100% | 0% | 98% |
| leg_reduction_lean_v2 | 50 | 100% | 100% | 0% | 100% |
| retry_bare_retry_v2 | 76 | 100% | 100% | 34% | 66% |
| retry_leg_critique_strict_v2 | 80 | 98% | 96% | 64% | 36% |
| retry_reasoning_only_critique_v1 | 30 | 100% | 100% | 100% | 0% |

#### early_return_b
- **Invariant:** ledger/audit must have entry for every call
- **Fix pattern:** record before early return or in finally
- **N=215, Oracle=100%, AST=97%, Pass=71%, ExecGap=26%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 132 | 100% | 95% | 53% | 42% |
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 27 | 100% | 100% | 100% | 0% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 34 | 100% | 97% | 32% | 65% |
| leg_reduction_lean_v2 | 17 | 100% | 76% | 6% | 71% |
| retry_bare_retry_v2 | 64 | 100% | 98% | 80% | 19% |
| retry_leg_critique_strict_v2 | 66 | 100% | 100% | 89% | 11% |
| retry_reasoning_only_critique_v1 | 34 | 100% | 100% | 91% | 9% |

#### overdetermination
- **Invariant:** store must contain the latest computed value after update
- **Fix pattern:** remove write_cached call from update_product
- **N=161, Oracle=100%, AST=99%, Pass=80%, ExecGap=20%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| claude-sonnet-4-6 | 30 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 29 | 100% | 100% | 79% | 21% |
| gpt-4o-mini | 27 | 100% | 100% | 0% | 100% |
| gpt-5-mini | 26 | 100% | 96% | 100% | 0% |
| claude-sonnet-4-20250514 | 20 | 100% | 100% | 100% | 0% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| retry_bare_retry_v2 | 54 | 100% | 100% | 80% | 20% |
| retry_leg_critique_strict_v2 | 51 | 100% | 100% | 78% | 22% |
| retry_reasoning_only_critique_v1 | 56 | 100% | 98% | 80% | 20% |

#### silent_default_b
- **Invariant:** flag lookup must return the configured value, not silent default
- **Fix pattern:** fix key name to match dict
- **N=114, Oracle=100%, AST=99%, Pass=75%, ExecGap=24%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 29 | 100% | 97% | 97% | 0% |
| gpt-4o-mini | 28 | 100% | 100% | 4% | 96% |
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| retry_bare_retry_v2 | 34 | 100% | 97% | 76% | 21% |
| retry_leg_critique_strict_v2 | 40 | 100% | 100% | 75% | 25% |
| retry_reasoning_only_critique_v1 | 40 | 100% | 100% | 75% | 25% |

#### early_return_c
- **Invariant:** ledger/audit must have entry for every call
- **Fix pattern:** record before early return or in finally
- **N=107, Oracle=100%, AST=99%, Pass=79%, ExecGap=21%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4.1-nano | 29 | 100% | 97% | 90% | 7% |
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 27 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 23 | 100% | 100% | 13% | 87% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| retry_bare_retry_v2 | 34 | 100% | 97% | 82% | 15% |
| retry_leg_critique_strict_v2 | 36 | 100% | 100% | 81% | 19% |
| retry_reasoning_only_critique_v1 | 37 | 100% | 100% | 73% | 27% |

#### hidden_dep_multihop
- **Invariant:** save_user must use cache_put (always overwrite) so get_display_name returns the latest name
- **Fix pattern:** keep sync_user_to_cache (uses cache_put) in save_user, do not replace with refresh_user_snapshot
- **N=57, Oracle=93%, AST=100%, Pass=70%, ExecGap=25%**

By model:
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| claude-sonnet-4-6 | 29 | 100% | 100% | 100% | 0% |
| claude-haiku-4-5-20251001 | 28 | 86% | 100% | 39% | 50% |

By condition:
| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| retry_bare_retry_v2 | 17 | 94% | 100% | 65% | 29% |
| retry_leg_critique_strict_v2 | 20 | 100% | 100% | 80% | 20% |
| retry_reasoning_only_critique_v1 | 20 | 85% | 100% | 65% | 25% |

### 6B. Clean Cases Cluster
Cases where models succeed at all three levels.

| Case | N | Oracle% | AST% | Pass% |
|------|---|---------|------|-------|
| alias_config_a | 113 | 100% | 100% | 100% |
| alias_config_c | 114 | 100% | 100% | 100% |
| stale_cache_a | 111 | 99% | 95% | 100% |
| stale_cache_b | 87 | 100% | 100% | 100% |
| lazy_init_a | 86 | 100% | 100% | 100% |
| lazy_init_b | 115 | 100% | 100% | 100% |
| lazy_init_c | 111 | 100% | 95% | 100% |
| mutable_default_a | 86 | 100% | 100% | 100% |
| mutable_default_b | 139 | 100% | 100% | 100% |
| effect_order_a | 113 | 100% | 100% | 100% |
| retry_dup_a | 108 | 99% | 100% | 100% |
| retry_dup_b | 113 | 100% | 100% | 100% |
| temporal_drift_a | 114 | 100% | 100% | 100% |
| temporal_drift_b | 119 | 100% | 99% | 100% |
| wrong_condition_a | 114 | 100% | 100% | 100% |
| wrong_condition_c | 112 | 100% | 96% | 100% |
| missing_branch_b | 102 | 100% | 100% | 100% |
| retry_dup_c | 56 | 100% | 100% | 100% |
| partial_rollback_b | 57 | 100% | 100% | 100% |
| early_return_a | 115 | 100% | 94% | 100% |
| temporal_drift_c | 28 | 100% | 100% | 100% |
| index_misalign_a | 105 | 100% | 93% | 99% |
| stale_cache_c | 85 | 100% | 100% | 98% |
| mutable_default_c | 95 | 98% | 99% | 97% |
| missing_branch_a | 115 | 97% | 100% | 96% |
| wrong_condition_b | 113 | 100% | 95% | 95% |
| alias_config_b | 108 | 99% | 100% | 94% |
| partial_update_c | 110 | 99% | 99% | 94% |
| commit_gate | 114 | 100% | 97% | 92% |

### 6C. Genuinely Hard Cases
Cases where models fail at the reasoning level.

| Case | N | Oracle% | AST% | Pass% | Difficulty |
|------|---|---------|------|-------|------------|
| async_race_lock | 281 | 1% | 0% | 0% | C |
| cache_invalidation_order | 306 | 7% | 64% | 38% | C |
| l3_state_pipeline | 238 | 13% | 3% | 32% | C |
| use_before_set_a | 75 | 23% | 69% | 100% | A |

### 6D. Extreme Model Stratification
Cases where the best and worst model differ by >40pp on pass rate.

#### invariant_partial_fail (pass range: 59pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| claude-haiku-4-5-20251001 | 27 | 96% | 96% | 59% | 37% |
| claude-sonnet-4-6 | 200 | 100% | 100% | 56% | 44% |
| gpt-5 | 30 | 100% | 100% | 33% | 67% |
| gpt-4.1-nano | 14 | 100% | 93% | 29% | 71% |
| gpt-5-mini | 26 | 92% | 100% | 19% | 81% |
| gpt-5.4-mini | 200 | 96% | 100% | 18% | 80% |
| gpt-4o-mini | 57 | 89% | 14% | 0% | 12% |

#### cache_invalidation_order (pass range: 96pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 25 | 16% | 100% | 100% | 0% |
| gpt-5.4-mini | 28 | 18% | 75% | 79% | 0% |
| gpt-4.1-nano | 225 | 5% | 66% | 31% | 0% |
| gpt-4o-mini | 28 | 0% | 4% | 4% | 0% |

#### missing_branch_c (pass range: 74pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 29 | 100% | 100% | 86% | 14% |
| gpt-4o-mini | 29 | 100% | 100% | 76% | 24% |
| gpt-4.1-nano | 27 | 100% | 100% | 22% | 78% |
| gpt-5-mini | 211 | 100% | 93% | 12% | 82% |

#### use_before_set_b (pass range: 90pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 28 | 100% | 89% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-20250514 | 30 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 200 | 98% | 100% | 10% | 89% |

#### l3_state_pipeline (pass range: 94pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 28 | 36% | 0% | 100% | 0% |
| gpt-5.4-mini | 28 | 29% | 14% | 79% | 0% |
| gpt-4o-mini | 27 | 41% | 4% | 59% | 0% |
| gpt-4.1-nano | 155 | 1% | 2% | 6% | 0% |

#### early_return_b (pass range: 47pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 27 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 132 | 100% | 95% | 53% | 42% |

#### overdetermination (pass range: 100pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 26 | 100% | 96% | 100% | 0% |
| claude-sonnet-4-20250514 | 20 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-6 | 30 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 29 | 100% | 100% | 79% | 21% |
| gpt-4o-mini | 27 | 100% | 100% | 0% | 100% |

#### silent_default_b (pass range: 96pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 29 | 100% | 97% | 97% | 0% |
| gpt-4o-mini | 28 | 100% | 100% | 4% | 96% |

#### partial_rollback_c (pass range: 71pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 28 | 100% | 100% | 96% | 4% |
| gpt-4o-mini | 28 | 100% | 93% | 29% | 64% |

#### effect_order_b (pass range: 63pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 29 | 97% | 100% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 28 | 100% | 100% | 93% | 7% |
| gpt-4o-mini | 27 | 100% | 100% | 37% | 63% |

#### early_return_c (pass range: 87pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 28 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 27 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 29 | 100% | 97% | 90% | 7% |
| gpt-4o-mini | 23 | 100% | 100% | 13% | 87% |

#### effect_order_c (pass range: 58pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 29 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 24 | 100% | 100% | 42% | 58% |

#### use_before_set_c (pass range: 90pp)
| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 29 | 90% | 79% | 100% | 0% |
| gpt-4.1-nano | 28 | 100% | 71% | 100% | 0% |
| gpt-4o-mini | 21 | 67% | 100% | 10% | 57% |


### 6E. Condition Impact Hotspots
Cases where retry/critique conditions make the biggest difference.

#### invariant_partial_fail (baseline→best: +52pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 107 | 94% | 93% | 10% |
| leg_reduction_lean_v2 | 138 | 97% | 75% | 38% |
| retry_bare_retry_v2 | 136 | 97% | 97% | 12% |
| retry_leg_critique_strict_v2 | 137 | 98% | 97% | 63% |
| retry_reasoning_only_critique_v1 | 36 | 97% | 97% | 47% |

#### cache_invalidation_order (baseline→best: +50pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 49 | 0% | 57% | 10% |
| leg_reduction_lean_v2 | 50 | 0% | 98% | 60% |
| retry_bare_retry_v2 | 81 | 2% | 42% | 23% |
| retry_leg_critique_strict_v2 | 89 | 18% | 70% | 46% |
| retry_reasoning_only_critique_v1 | 37 | 8% | 62% | 59% |

#### missing_branch_c (baseline→best: +68pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 47 | 100% | 94% | 9% |
| leg_reduction_lean_v2 | 39 | 100% | 90% | 13% |
| retry_bare_retry_v2 | 83 | 100% | 98% | 25% |
| retry_leg_critique_strict_v2 | 88 | 100% | 97% | 22% |
| retry_reasoning_only_critique_v1 | 39 | 100% | 95% | 77% |

#### use_before_set_b (baseline→best: +100pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 50 | 98% | 100% | 0% |
| leg_reduction_lean_v2 | 50 | 100% | 100% | 0% |
| retry_bare_retry_v2 | 76 | 100% | 100% | 34% |
| retry_leg_critique_strict_v2 | 80 | 98% | 96% | 64% |
| retry_reasoning_only_critique_v1 | 30 | 100% | 100% | 100% |

#### l3_state_pipeline (baseline→best: +74pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 38 | 0% | 0% | 0% |
| leg_reduction_lean_v2 | 19 | 0% | 0% | 5% |
| retry_bare_retry_v2 | 70 | 6% | 3% | 21% |
| retry_leg_critique_strict_v2 | 73 | 18% | 7% | 42% |
| retry_reasoning_only_critique_v1 | 38 | 37% | 3% | 74% |

#### early_return_b (baseline→best: +59pp)
| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 34 | 100% | 97% | 32% |
| leg_reduction_lean_v2 | 17 | 100% | 76% | 6% |
| retry_bare_retry_v2 | 64 | 100% | 98% | 80% |
| retry_leg_critique_strict_v2 | 66 | 100% | 100% | 89% |
| retry_reasoning_only_critique_v1 | 34 | 100% | 100% | 91% |


---

## 7. Key Findings

### 7.1 The execution gap is the dominant bottleneck
- 943 of 1679 failures (56.2%) occur after correct reasoning AND correct structure
- With oracle labels, reasoning failure accounts for 39.0% — substantially more than the old classifier suggested
- The old mechanism_correct (99.7%) massively overestimates reasoning correctness vs oracle (85.8%)

### 7.2 Reasoning-only critique is the most effective intervention
- retry_reasoning_only_critique_v1 achieves 90.3% pass rate with only 6.7% execution gap
- This beats retry_leg_critique_strict_v2 (80.8% pass, 10.8% gap)
- This beats retry_bare_retry_v2 (73.8% pass, 15.2% gap)
- This beats baseline (8.3% pass, 52.9% gap) and lean (22.2% pass, 34.6% gap)
- Critique targeting the reasoning trace is more effective than critique targeting the code

### 7.3 The execution gap is model-stratified
- claude-sonnet-4: 0% execution gap (perfect execution fidelity)
- gpt-5.4-mini: 10.4% gap
- gpt-5-mini: 13.7% gap
- gpt-4o-mini: 28.4% gap
- claude-sonnet-4.6: 30.1% gap
- gpt-5: 48.8% gap (small N)
- claude-haiku-4.5: 43.6% gap

### 7.4 Flagship execution gap cases
- **missing_branch_c**: 70% execution gap (100% oracle, 95% AST, 27% pass)
- **use_before_set_b**: 62% execution gap (99% oracle, 99% AST, 37% pass)
- **invariant_partial_fail**: 57% execution gap (97% oracle, 91% AST, 33% pass)
- These cases prove that correct reasoning + correct structure ≠ correct execution