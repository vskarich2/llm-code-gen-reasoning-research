# Combined Oracle + AST Analysis — All Oracle-Evaluated Data

**Date:** 2026-04-03
**Events:** 20031 (oracle-labeled + AST-assessable)
**Oracle sources:** Original 12-log oracle intervention (22,323 labels) + retry_critique_stage2 (3,000) + global_calibration (6,244)
**Models:** 9
**Cases:** 47
**Conditions:** baseline_v2, leg_reduction_v2, leg_reduction_lean_v2, retry_bare_retry_v2, retry_leg_critique_strict_v2, retry_reasoning_only_critique_v1

---

## Anchor Table

| Metric | Value |
|--------|-------|
| **N (events)** | **20031** |
| P(oracle_reasoning_correct) | 90.4% |
| P(ast_structural_correct) | 91.2% |
| P(exec_pass) | 80.8% |
| P(old_mechanism_correct) | 99.7% |
| **P(exec_fail \| ast_correct)** | **13.9%** |

---

## Three-Way Decomposition

| Oracle | AST | Exec | Count | % | Category |
|--------|-----|------|-------|---|----------|
| T | T | T | 15282 | 76.3% | FULL_SUCCESS |
| T | T | F | 2242 | 11.2% | EXECUTION_GAP |
| F | F | F | 1031 | 5.1% | FULL_FAILURE |
| F | T | T | 458 | 2.3% | LUCKY_REASONING |
| T | F | T | 300 | 1.5% | LUCKY_FIX |
| F | T | F | 289 | 1.4% | AST_OK_REASONING_WRONG |
| T | F | F | 275 | 1.4% | STRUCTURAL_FAILURE |
| F | F | T | 154 | 0.8% | DOUBLE_LUCKY |

---

## Causal Failure Decomposition

Total failures: 3837

| Stage | Count | % | Description |
|-------|-------|---|-------------|
| 1. Reasoning | 1320 | 34.4% | Oracle says reasoning wrong |
| 2. Structure | 275 | 7.2% | Reasoning correct, structure wrong |
| **3. Execution** | **2242** | **58.4%** | **Reasoning + structure correct, execution fails** |

---

## By Condition

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 5071 | 90.7% | 91.1% | 77.3% | 14.2% |
| leg_reduction_lean_v2 | 4805 | 89.9% | 91.5% | 81.9% | 9.8% |
| leg_reduction_v2 | 4735 | 91.1% | 91.8% | 82.3% | 9.8% |
| retry_bare_retry_v2 | 1779 | 87.6% | 88.2% | 74.5% | 15.1% |
| retry_leg_critique_strict_v2 | 1983 | 88.6% | 90.2% | 81.5% | 10.6% |
| retry_reasoning_only_critique_v1 | 1658 | 93.7% | 93.5% | 90.3% | 6.7% |

---

## By Model

| Model | N | Oracle% | AST% | Pass% | P(F\|A) | ExecGap% |
|-------|---|---------|------|-------|---------|----------|
| claude-haiku-4-5-20251001 | 355 | 90.7% | 99.2% | 23.4% | 77.3% | 68.5% |
| claude-sonnet-4-20250514 | 660 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| claude-sonnet-4-6 | 739 | 97.0% | 100.0% | 85.5% | 14.5% | 12.2% |
| gpt-4.1-nano | 4040 | 87.1% | 88.9% | 77.5% | 13.8% | 9.3% |
| gpt-4o-mini | 3998 | 88.0% | 89.2% | 64.9% | 27.7% | 22.2% |
| gpt-5 | 238 | 73.1% | 74.4% | 38.2% | 48.6% | 34.0% |
| gpt-5-mini | 4778 | 93.8% | 92.7% | 91.6% | 7.2% | 6.5% |
| gpt-5.4-mini | 5222 | 90.1% | 91.0% | 88.5% | 5.4% | 4.8% |

---

## By Family (top 20 by execution gap)

| Family | N | Oracle% | AST% | Pass% | ExecGap% |
|--------|---|---------|------|-------|----------|
| invariant_partial_fail | 1151 | 95% | 90% | 27% | 59.9% |
| hidden_dep_multihop | 784 | 88% | 98% | 52% | 36.4% |
| missing_branch | 1427 | 99% | 98% | 74% | 24.9% |
| silent_default | 214 | 100% | 99% | 76% | 23.4% |
| use_before_set | 1201 | 87% | 94% | 81% | 18.6% |
| overdetermination | 853 | 100% | 100% | 84% | 15.5% |
| early_return | 1851 | 100% | 98% | 88% | 10.0% |
| effect_order | 975 | 100% | 100% | 92% | 8.4% |
| partial_rollback | 611 | 98% | 92% | 87% | 7.0% |
| commit_gate | 679 | 100% | 98% | 93% | 5.4% |
| index_misalign | 209 | 100% | 96% | 95% | 5.3% |
| mutable_default | 1472 | 100% | 100% | 96% | 4.1% |
| partial_update | 809 | 100% | 97% | 95% | 3.8% |
| stale_cache | 1003 | 100% | 99% | 98% | 1.9% |
| retry_dup | 586 | 100% | 100% | 98% | 1.9% |
| cache_invalidation_order | 714 | 4% | 65% | 43% | 1.4% |
| alias_config | 1028 | 100% | 100% | 99% | 1.0% |
| temporal_drift | 1064 | 100% | 96% | 100% | 0.3% |
| lazy_init | 1319 | 100% | 99% | 100% | 0.2% |
| wrong_condition | 1040 | 100% | 94% | 95% | 0.2% |

---

## Key Findings

1. **20,031 events** with all three measurements — the largest oracle+AST+execution dataset in the project.
2. **Execution fidelity is the dominant bottleneck:** 58% of failures occur after correct reasoning AND correct structure.
3. **P(exec_fail | ast_correct) = 13.9%** — 1 in 7 structurally correct outputs fail execution.
4. **Reasoning-only critique is the most effective intervention:** 94% oracle correct, 94% AST correct, 90% pass, 6.7% execution gap.
5. **The old mechanism_correct classifier overestimates by 9pp** compared to the oracle.
6. **The causal decomposition is robust:** corrections for oracle FP (~0.3%) and AST FP (~1-2%) shift <2% of failures between stages.
---

## Case Family Clusters

### Cluster A: Execution Gap
Models understand the bug AND produce the correct structural fix, but execution fails.

| Case | N | Oracle% | AST% | Pass% | ExecGap% | Difficulty |
|------|---|---------|------|-------|----------|------------|
| invariant_partial_fail | 1151 | 95% | 90% | 27% | 59.9% | C |
| missing_branch_c | 673 | 100% | 96% | 47% | 50.4% | C |
| hidden_dep_multihop | 784 | 88% | 98% | 52% | 36.4% | C |
| silent_default_b | 214 | 100% | 99% | 76% | 23.4% | B |
| use_before_set_b | 838 | 100% | 99% | 77% | 23.3% | B |
| partial_rollback_c | 214 | 100% | 99% | 81% | 18.2% | C |
| early_return_c | 628 | 100% | 99% | 81% | 17.8% | C |
| effect_order_c | 193 | 100% | 100% | 83% | 17.1% | C |
| overdetermination | 853 | 100% | 100% | 84% | 15.5% | C |
| use_before_set_c | 182 | 92% | 86% | 81% | 15.4% | C |
| early_return_b | 596 | 100% | 96% | 84% | 12.2% | B |
| mutable_default_c | 518 | 100% | 100% | 89% | 10.8% | C |
| effect_order_b | 555 | 100% | 100% | 91% | 8.8% | B |
| stale_cache_c | 182 | 100% | 98% | 90% | 8.8% | C |
| retry_dup_c | 141 | 100% | 100% | 92% | 7.8% | C |
| missing_branch_a | 232 | 99% | 100% | 93% | 6.9% | A |
| commit_gate | 679 | 100% | 98% | 93% | 5.4% | L3 |
| partial_update_c | 580 | 100% | 98% | 93% | 5.3% | C |
| index_misalign_a | 209 | 100% | 96% | 95% | 5.3% | A |

#### invariant_partial_fail
- **Invariant:** sender.balance + receiver.balance must be conserved at all times
- **Fix pattern:** try/except around credit with sender.balance += amount in except block
- **N=1151, Oracle=95%, AST=90%, Pass=27%, ExecGap=60%**

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 247 | 96% | 98% | 14% | 81% |
| claude-haiku-4-5-20251001 | 177 | 92% | 98% | 14% | 80% |
| gpt-4.1-nano | 116 | 88% | 82% | 4% | 67% |
| gpt-5-mini | 144 | 98% | 97% | 32% | 65% |
| gpt-5 | 180 | 97% | 98% | 51% | 45% |
| claude-sonnet-4-6 | 200 | 100% | 100% | 56% | 44% |
| gpt-4o-mini | 87 | 91% | 14% | 0% | 11% |

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 279 | 93% | 96% | 7% | 83% |
| leg_reduction_lean_v2 | 302 | 96% | 86% | 43% | 41% |
| leg_reduction_v2 | 261 | 93% | 80% | 18% | 60% |
| retry_bare_retry_v2 | 136 | 97% | 97% | 12% | 83% |
| retry_leg_critique_strict_v2 | 137 | 98% | 97% | 63% | 34% |
| retry_reasoning_only_critique_v1 | 36 | 97% | 97% | 47% | 53% |

#### missing_branch_c
- **Invariant:** all valid roles must receive correct permissions
- **Fix pattern:** add missing branch/case
- **N=673, Oracle=100%, AST=96%, Pass=47%, ExecGap=50%**

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4.1-nano | 119 | 100% | 99% | 7% | 92% |
| gpt-5-mini | 239 | 100% | 92% | 18% | 75% |
| gpt-5.4-mini | 160 | 100% | 98% | 80% | 19% |
| gpt-4o-mini | 155 | 100% | 100% | 88% | 12% |

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 178 | 100% | 98% | 42% | 57% |
| leg_reduction_lean_v2 | 171 | 100% | 99% | 53% | 46% |
| leg_reduction_v2 | 132 | 100% | 91% | 63% | 30% |
| retry_bare_retry_v2 | 75 | 100% | 97% | 27% | 72% |
| retry_leg_critique_strict_v2 | 78 | 100% | 96% | 23% | 73% |
| retry_reasoning_only_critique_v1 | 39 | 100% | 95% | 77% | 23% |

#### hidden_dep_multihop
- **Invariant:** save_user must use cache_put (always overwrite) so get_display_name returns the latest name
- **Fix pattern:** keep sync_user_to_cache (uses cache_put) in save_user, do not replace with refresh_user_snapshot
- **N=784, Oracle=88%, AST=98%, Pass=52%, ExecGap=36%**

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 145 | 76% | 100% | 1% | 75% |
| gpt-4.1-nano | 63 | 83% | 100% | 22% | 62% |
| claude-haiku-4-5-20251001 | 178 | 90% | 100% | 33% | 57% |
| gpt-5-mini | 92 | 91% | 97% | 63% | 26% |
| gpt-5.4-mini | 127 | 99% | 91% | 94% | 6% |
| claude-sonnet-4-6 | 179 | 88% | 100% | 89% | 2% |

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 241 | 92% | 100% | 48% | 43% |
| leg_reduction_lean_v2 | 232 | 86% | 100% | 57% | 31% |
| leg_reduction_v2 | 254 | 85% | 95% | 48% | 37% |
| retry_bare_retry_v2 | 17 | 94% | 100% | 65% | 29% |
| retry_leg_critique_strict_v2 | 20 | 100% | 100% | 80% | 20% |
| retry_reasoning_only_critique_v1 | 20 | 85% | 100% | 65% | 25% |

#### silent_default_b
- **Invariant:** flag lookup must return the configured value, not silent default
- **Fix pattern:** fix key name to match dict
- **N=214, Oracle=100%, AST=99%, Pass=76%, ExecGap=23%**

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 44 | 100% | 100% | 9% | 91% |
| gpt-4.1-nano | 56 | 100% | 96% | 79% | 18% |
| gpt-5-mini | 58 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 56 | 100% | 100% | 100% | 0% |

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 39 | 100% | 97% | 72% | 26% |
| leg_reduction_lean_v2 | 32 | 100% | 100% | 69% | 31% |
| leg_reduction_v2 | 29 | 100% | 100% | 90% | 10% |
| retry_bare_retry_v2 | 34 | 100% | 97% | 76% | 21% |
| retry_leg_critique_strict_v2 | 40 | 100% | 100% | 75% | 25% |
| retry_reasoning_only_critique_v1 | 40 | 100% | 100% | 75% | 25% |

#### use_before_set_b
- **Invariant:** function must handle empty/edge-case input without NameError
- **Fix pattern:** initialize variable before conditional
- **N=838, Oracle=100%, AST=99%, Pass=77%, ExecGap=23%**

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 245 | 99% | 100% | 21% | 79% |
| gpt-5.4-mini | 143 | 100% | 100% | 99% | 1% |
| gpt-5-mini | 176 | 100% | 95% | 99% | 1% |
| gpt-4.1-nano | 93 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-20250514 | 180 | 100% | 100% | 100% | 0% |

| Condition | N | Oracle% | AST% | Pass% | ExecGap% |
|-----------|---|---------|------|-------|----------|
| baseline_v2 | 243 | 100% | 99% | 79% | 21% |
| leg_reduction_lean_v2 | 208 | 100% | 100% | 76% | 24% |
| leg_reduction_v2 | 201 | 100% | 99% | 92% | 8% |
| retry_bare_retry_v2 | 76 | 100% | 100% | 34% | 66% |
| retry_leg_critique_strict_v2 | 80 | 98% | 96% | 64% | 36% |
| retry_reasoning_only_critique_v1 | 30 | 100% | 100% | 100% | 0% |

### Cluster B: Clean Cases
Models succeed at all three levels (>90% on each).

| Case | N | Oracle% | AST% | Pass% |
|------|---|---------|------|-------|
| stale_cache_a | 627 | 100% | 99% | 100% |
| early_return_a | 627 | 100% | 99% | 100% |
| alias_config_c | 568 | 100% | 100% | 100% |
| alias_config_a | 233 | 100% | 100% | 100% |
| partial_update_a | 229 | 100% | 93% | 100% |
| lazy_init_a | 191 | 100% | 99% | 100% |
| effect_order_a | 227 | 100% | 100% | 100% |
| retry_dup_a | 226 | 99% | 100% | 100% |
| wrong_condition_c | 222 | 100% | 95% | 100% |
| retry_dup_b | 219 | 100% | 100% | 100% |
| temporal_drift_a | 231 | 100% | 97% | 100% |
| wrong_condition_a | 232 | 100% | 100% | 100% |
| temporal_drift_b | 695 | 100% | 96% | 100% |
| mutable_default_b | 770 | 100% | 100% | 100% |
| missing_branch_b | 522 | 97% | 100% | 100% |
| lazy_init_c | 567 | 100% | 98% | 100% |
| lazy_init_b | 561 | 100% | 100% | 99% |
| stale_cache_b | 194 | 100% | 99% | 98% |
| mutable_default_a | 184 | 100% | 100% | 98% |
| temporal_drift_c | 138 | 100% | 99% | 98% |
| partial_rollback_b | 166 | 100% | 95% | 97% |
| alias_config_b | 227 | 100% | 100% | 96% |
| index_misalign_a | 209 | 100% | 96% | 95% |
| missing_branch_a | 232 | 99% | 100% | 93% |
| partial_update_c | 580 | 100% | 98% | 93% |
| commit_gate | 679 | 100% | 98% | 93% |
| retry_dup_c | 141 | 100% | 100% | 92% |
| wrong_condition_b | 586 | 100% | 92% | 91% |
| effect_order_b | 555 | 100% | 100% | 91% |

### Cluster C: Genuinely Hard Cases
Models fail at the reasoning level (<50% oracle correct).

| Case | N | Oracle% | AST% | Pass% | Difficulty |
|------|---|---------|------|-------|------------|
| async_race_lock | 382 | 1% | 0% | 0% | C |
| cache_invalidation_order | 714 | 4% | 65% | 43% | C |
| l3_state_pipeline | 659 | 20% | 3% | 38% | C |
| use_before_set_a | 181 | 25% | 81% | 100% | A |

#### async_race_lock
- **Invariant:** run_verified requires atomic read-increment-read via locking
- **Why hard:** Oracle=1% — models fail to identify the mechanism

| Model | N | Oracle% | AST% | Pass% |
|-------|---|---------|------|-------|
| gpt-4.1-nano | 28 | 7% | 0% | 0% |
| gpt-4o-mini | 54 | 0% | 0% | 0% |
| gpt-5-mini | 43 | 0% | 0% | 0% |
| gpt-5.4-mini | 199 | 1% | 0% | 0% |
| gpt-5 | 58 | 0% | 0% | 0% |

#### cache_invalidation_order
- **Invariant:** read_record must return the latest value after update_record
- **Why hard:** Oracle=4% — models fail to identify the mechanism

| Model | N | Oracle% | AST% | Pass% |
|-------|---|---------|------|-------|
| gpt-5-mini | 143 | 4% | 100% | 100% |
| gpt-5.4-mini | 147 | 4% | 50% | 51% |
| gpt-4.1-nano | 248 | 4% | 71% | 34% |
| gpt-4o-mini | 176 | 6% | 41% | 3% |

#### l3_state_pipeline
- **Invariant:** commit sets frozen=True for get_committed_total; freeze_view rebuilds view from stable
- **Why hard:** Oracle=20% — models fail to identify the mechanism

| Model | N | Oracle% | AST% | Pass% |
|-------|---|---------|------|-------|
| gpt-5-mini | 142 | 61% | 0% | 90% |
| gpt-5.4-mini | 157 | 20% | 10% | 61% |
| gpt-4o-mini | 176 | 6% | 1% | 9% |
| gpt-4.1-nano | 184 | 1% | 2% | 5% |

#### use_before_set_a
- **Invariant:** function must handle empty/edge-case input without NameError
- **Why hard:** Oracle=25% — models fail to identify the mechanism

| Model | N | Oracle% | AST% | Pass% |
|-------|---|---------|------|-------|
| gpt-4.1-nano | 23 | 35% | 100% | 100% |
| gpt-4o-mini | 41 | 7% | 98% | 100% |
| gpt-5-mini | 58 | 33% | 90% | 100% |
| gpt-5.4-mini | 59 | 27% | 53% | 100% |

### Cluster D: Extreme Model Stratification
Cases where best-to-worst model pass rate differs by >40pp.

#### invariant_partial_fail (pass range: 56pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| claude-sonnet-4-6 | 200 | 100% | 100% | 56% | 44% |
| gpt-5 | 180 | 97% | 98% | 51% | 45% |
| gpt-5-mini | 144 | 98% | 97% | 32% | 65% |
| gpt-5.4-mini | 247 | 96% | 98% | 14% | 81% |
| claude-haiku-4-5-20251001 | 177 | 92% | 98% | 14% | 80% |
| gpt-4.1-nano | 116 | 88% | 82% | 4% | 67% |
| gpt-4o-mini | 87 | 91% | 14% | 0% | 11% |

#### overdetermination (pass range: 82pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 163 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-20250514 | 120 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-6 | 180 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 136 | 100% | 99% | 93% | 7% |
| gpt-4.1-nano | 117 | 100% | 100% | 90% | 10% |
| gpt-4o-mini | 137 | 100% | 99% | 18% | 81% |

#### use_before_set_b (pass range: 79pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4.1-nano | 93 | 100% | 100% | 100% | 0% |
| claude-sonnet-4-20250514 | 180 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 176 | 100% | 95% | 99% | 1% |
| gpt-5.4-mini | 143 | 100% | 100% | 99% | 1% |
| gpt-4o-mini | 245 | 99% | 100% | 21% | 79% |

#### hidden_dep_multihop (pass range: 93pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 127 | 99% | 91% | 94% | 6% |
| claude-sonnet-4-6 | 179 | 88% | 100% | 89% | 2% |
| gpt-5-mini | 92 | 91% | 97% | 63% | 26% |
| claude-haiku-4-5-20251001 | 178 | 90% | 100% | 33% | 57% |
| gpt-4.1-nano | 63 | 83% | 100% | 22% | 62% |
| gpt-4o-mini | 145 | 76% | 100% | 1% | 75% |

#### cache_invalidation_order (pass range: 97pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 143 | 4% | 100% | 100% | 0% |
| gpt-5.4-mini | 147 | 4% | 50% | 51% | 0% |
| gpt-4.1-nano | 248 | 4% | 71% | 34% | 0% |
| gpt-4o-mini | 176 | 6% | 41% | 3% | 6% |

#### missing_branch_c (pass range: 81pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 155 | 100% | 100% | 88% | 12% |
| gpt-5.4-mini | 160 | 100% | 98% | 80% | 19% |
| gpt-5-mini | 239 | 100% | 92% | 18% | 75% |
| gpt-4.1-nano | 119 | 100% | 99% | 7% | 92% |

#### l3_state_pipeline (pass range: 85pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 142 | 61% | 0% | 90% | 0% |
| gpt-5.4-mini | 157 | 20% | 10% | 61% | 0% |
| gpt-4o-mini | 176 | 6% | 1% | 9% | 0% |
| gpt-4.1-nano | 184 | 1% | 2% | 5% | 0% |

#### early_return_c (pass range: 77pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 161 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 168 | 100% | 100% | 99% | 1% |
| gpt-4.1-nano | 161 | 100% | 96% | 93% | 3% |
| gpt-4o-mini | 138 | 100% | 100% | 23% | 77% |

#### early_return_b (pass range: 49pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 157 | 100% | 100% | 99% | 1% |
| gpt-5.4-mini | 153 | 100% | 100% | 99% | 1% |
| gpt-4.1-nano | 148 | 100% | 89% | 83% | 5% |
| gpt-4o-mini | 138 | 100% | 96% | 51% | 46% |

#### wrong_condition_b (pass range: 45pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 144 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 160 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 176 | 100% | 99% | 98% | 1% |
| gpt-4.1-nano | 106 | 100% | 55% | 55% | 0% |

#### partial_rollback_a (pass range: 55pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4o-mini | 59 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 55 | 98% | 95% | 100% | 0% |
| gpt-5.4-mini | 59 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 58 | 81% | 34% | 45% | 0% |

#### silent_default_b (pass range: 91pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5-mini | 58 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 56 | 100% | 100% | 100% | 0% |
| gpt-4.1-nano | 56 | 100% | 96% | 79% | 18% |
| gpt-4o-mini | 44 | 100% | 100% | 9% | 91% |

#### partial_rollback_c (pass range: 83pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-5.4-mini | 59 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 55 | 100% | 100% | 98% | 2% |
| gpt-4.1-nano | 53 | 100% | 100% | 98% | 2% |
| gpt-4o-mini | 47 | 100% | 96% | 17% | 79% |

#### effect_order_c (pass range: 69pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4.1-nano | 29 | 100% | 100% | 100% | 0% |
| gpt-5-mini | 57 | 100% | 100% | 100% | 0% |
| gpt-5.4-mini | 59 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 48 | 100% | 100% | 31% | 69% |

#### use_before_set_c (pass range: 83pp)

| Model | N | Oracle% | AST% | Pass% | ExecGap% |
|-------|---|---------|------|-------|----------|
| gpt-4.1-nano | 57 | 96% | 79% | 100% | 0% |
| gpt-5-mini | 59 | 92% | 78% | 100% | 0% |
| gpt-5.4-mini | 24 | 100% | 100% | 100% | 0% |
| gpt-4o-mini | 42 | 83% | 100% | 17% | 67% |


### Cluster E: Condition Impact Hotspots
Cases where the best intervention improves pass rate by >25pp over baseline.

#### invariant_partial_fail (baseline 7% → retry_leg_critique_strict_v2 63%, +56pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 279 | 93% | 96% | 7% |
| leg_reduction_lean_v2 | 302 | 96% | 86% | 43% |
| leg_reduction_v2 | 261 | 93% | 80% | 18% |
| retry_bare_retry_v2 | 136 | 97% | 97% | 12% |
| retry_leg_critique_strict_v2 | 137 | 98% | 97% | 63% |
| retry_reasoning_only_critique_v1 | 36 | 97% | 97% | 47% |

#### hidden_dep_multihop (baseline 48% → retry_leg_critique_strict_v2 80%, +32pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 241 | 92% | 100% | 48% |
| leg_reduction_lean_v2 | 232 | 86% | 100% | 57% |
| leg_reduction_v2 | 254 | 85% | 95% | 48% |
| retry_bare_retry_v2 | 17 | 94% | 100% | 65% |
| retry_leg_critique_strict_v2 | 20 | 100% | 100% | 80% |
| retry_reasoning_only_critique_v1 | 20 | 85% | 100% | 65% |

#### cache_invalidation_order (baseline 34% → retry_reasoning_only_critique_v1 59%, +26pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 174 | 0% | 50% | 34% |
| leg_reduction_lean_v2 | 180 | 1% | 75% | 53% |
| leg_reduction_v2 | 171 | 7% | 81% | 46% |
| retry_bare_retry_v2 | 73 | 3% | 41% | 23% |
| retry_leg_critique_strict_v2 | 79 | 16% | 67% | 46% |
| retry_reasoning_only_critique_v1 | 37 | 8% | 62% | 59% |

#### missing_branch_c (baseline 42% → retry_reasoning_only_critique_v1 77%, +35pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 178 | 100% | 98% | 42% |
| leg_reduction_lean_v2 | 171 | 100% | 99% | 53% |
| leg_reduction_v2 | 132 | 100% | 91% | 63% |
| retry_bare_retry_v2 | 75 | 100% | 97% | 27% |
| retry_leg_critique_strict_v2 | 78 | 100% | 96% | 23% |
| retry_reasoning_only_critique_v1 | 39 | 100% | 95% | 77% |

#### l3_state_pipeline (baseline 33% → retry_reasoning_only_critique_v1 74%, +41pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 172 | 12% | 2% | 33% |
| leg_reduction_lean_v2 | 145 | 31% | 1% | 47% |
| leg_reduction_v2 | 174 | 19% | 4% | 29% |
| retry_bare_retry_v2 | 65 | 6% | 3% | 23% |
| retry_leg_critique_strict_v2 | 65 | 20% | 8% | 48% |
| retry_reasoning_only_critique_v1 | 38 | 37% | 3% | 74% |

#### partial_rollback_a (baseline 74% → retry_reasoning_only_critique_v1 100%, +26pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 39 | 100% | 74% | 74% |
| leg_reduction_lean_v2 | 39 | 100% | 77% | 79% |
| leg_reduction_v2 | 38 | 100% | 74% | 74% |
| retry_bare_retry_v2 | 35 | 89% | 83% | 91% |
| retry_leg_critique_strict_v2 | 40 | 85% | 90% | 98% |
| retry_reasoning_only_critique_v1 | 40 | 95% | 95% | 100% |

#### partial_rollback_c (baseline 74% → retry_bare_retry_v2 100%, +26pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 38 | 100% | 100% | 74% |
| leg_reduction_lean_v2 | 29 | 100% | 100% | 90% |
| leg_reduction_v2 | 34 | 100% | 100% | 79% |
| retry_bare_retry_v2 | 33 | 100% | 100% | 100% |
| retry_leg_critique_strict_v2 | 40 | 100% | 95% | 72% |
| retry_reasoning_only_critique_v1 | 40 | 100% | 100% | 75% |

#### retry_dup_c (baseline 73% → retry_bare_retry_v2 100%, +27pp)

| Condition | N | Oracle% | AST% | Pass% |
|-----------|---|---------|------|-------|
| baseline_v2 | 33 | 100% | 100% | 73% |
| leg_reduction_lean_v2 | 28 | 100% | 100% | 96% |
| leg_reduction_v2 | 24 | 100% | 100% | 96% |
| retry_bare_retry_v2 | 17 | 100% | 100% | 100% |
| retry_leg_critique_strict_v2 | 19 | 100% | 100% | 100% |
| retry_reasoning_only_critique_v1 | 20 | 100% | 100% | 100% |


### Cluster F: Oracle-AST Disagreement
Cases where oracle and AST substantially disagree (>15pp difference).

| Case | N | Oracle% | AST% | Diff | Interpretation |
|------|---|---------|------|------|----------------|
| cache_invalidation_order | 714 | 4% | 65% | +61pp | AST > Oracle: models fix structurally without articulating full mechanism |
| use_before_set_a | 181 | 25% | 81% | +55pp | AST > Oracle: models fix structurally without articulating full mechanism |
| l3_state_pipeline | 659 | 20% | 3% | -17pp | Oracle > AST: models reason correctly but AST checker may be too strict |