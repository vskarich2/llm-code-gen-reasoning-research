# CGE Controlled Experiment — Variance-Controlled Results

**Date:** 2026-03-23
**Design:** 3 runs per model, baseline + contract_gated in same run
**Total API calls:** 324 (9 runs × 36 calls)

> **IMPORTANT:** This analysis should be independently verified against
> the raw log files listed below. Cross-check any finding before citing.

## Log Files

- **nano run 1:** `logs/gpt-4.1-nano_20260323_072259.jsonl`
- **nano run 2:** `logs/gpt-4.1-nano_20260323_073441.jsonl`
- **nano run 3:** `logs/gpt-4.1-nano_20260323_074214.jsonl`
- **4o-mini run 1:** `logs/gpt-4o-mini_20260323_072402.jsonl`
- **4o-mini run 2:** `logs/gpt-4o-mini_20260323_073539.jsonl`
- **4o-mini run 3:** `logs/gpt-4o-mini_20260323_074306.jsonl`
- **5-mini run 1:** `logs/gpt-5-mini_20260323_072520.jsonl`
- **5-mini run 2:** `logs/gpt-5-mini_20260323_073659.jsonl`
- **5-mini run 3:** `logs/gpt-5-mini_20260323_074436.jsonl`

---

## 1. Aggregated Results (mean ± std across 3 runs)

| Model | Metric | Run 1 | Run 2 | Run 3 | Mean | Std |
|---|---|---|---|---|---|---|
| nano | baseline | 1 | 0 | 0 | 0.3 | 0.58 |
| | contract_gated | 2 | 1 | 1 | 1.3 | 0.58 |
| | **delta** | **+1** | **+1** | **+1** | **+1.0** | 0.00 |
| 4o-mini | baseline | 8 | 6 | 5 | 6.3 | 1.53 |
| | contract_gated | 4 | 3 | 6 | 4.3 | 1.53 |
| | **delta** | **-4** | **-3** | **+1** | **-2.0** | 2.65 |
| 5-mini | baseline | 0 | 0 | 0 | 0.0 | 0.00 |
| | contract_gated | 0 | 0 | 0 | 0.0 | 0.00 |
| | **delta** | **+0** | **+0** | **+0** | **+0.0** | 0.00 |

## 2. Per-Run Detail Tables

### nano

#### Run 1 (`gpt-4.1-nano_20260323_072259.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.00 | SAME |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | 0.20 | 0.20 | SAME |
| easy_conservation | 0.00 | PASS | FLIP_TO_PASS |
| easy_state_machine | 0.00 | 0.00 | SAME |
| easy_temporal | 0.20 | 0.00 | SAME |
| external_timing_dep | 0.20 | 0.00 | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.20 | SAME |
| idempotency_trap | 0.20 | 0.00 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.00 | 0.20 | SAME |
| lazy_init_hazard | PASS | PASS | SAME |
| log_side_effect_order | 0.20 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.20 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **1/18** | **2/18** | **+1** |

#### Run 2 (`gpt-4.1-nano_20260323_073441.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.20 | SAME |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | 0.00 | 0.00 | SAME |
| easy_conservation | 0.00 | PASS | FLIP_TO_PASS |
| easy_state_machine | 0.00 | 0.20 | SAME |
| easy_temporal | 0.20 | 0.20 | SAME |
| external_timing_dep | 0.20 | 0.20 | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.20 | SAME |
| idempotency_trap | 0.20 | 0.00 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.00 | 0.20 | SAME |
| lazy_init_hazard | 0.20 | 0.00 | SAME |
| log_side_effect_order | 0.00 | 0.00 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.00 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **0/18** | **1/18** | **+1** |

#### Run 3 (`gpt-4.1-nano_20260323_074214.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.00 | SAME |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | 0.20 | 0.00 | SAME |
| easy_conservation | 0.00 | PASS | FLIP_TO_PASS |
| easy_state_machine | 0.00 | 0.20 | SAME |
| easy_temporal | 0.00 | 0.00 | SAME |
| external_timing_dep | 0.20 | 0.00 | SAME |
| feature_flag_drift | 0.00 | 0.20 | SAME |
| hidden_dep_multihop | 0.00 | 0.20 | SAME |
| idempotency_trap | 0.00 | 0.00 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.20 | 0.20 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.00 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.20 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **0/18** | **1/18** | **+1** |

### 4o-mini

#### Run 1 (`gpt-4o-mini_20260323_072402.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | PASS | 0.20 | FLIP_TO_FAIL |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | PASS | 0.20 | FLIP_TO_FAIL |
| easy_conservation | PASS | PASS | SAME |
| easy_state_machine | PASS | 0.20 | FLIP_TO_FAIL |
| easy_temporal | PASS | PASS | SAME |
| external_timing_dep | PASS | PASS | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | PASS | 0.20 | FLIP_TO_FAIL |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.20 | 0.20 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.20 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.20 | PASS | FLIP_TO_PASS |
| shared_ref_coupling | 0.00 | 0.20 | SAME |
| temporal_semantic_drift | PASS | 0.20 | FLIP_TO_FAIL |
| **TOTAL** | **8/18** | **4/18** | **-4** |

#### Run 2 (`gpt-4o-mini_20260323_073539.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | PASS | 0.20 | FLIP_TO_FAIL |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | PASS | 0.20 | FLIP_TO_FAIL |
| easy_conservation | PASS | PASS | SAME |
| easy_state_machine | PASS | PASS | SAME |
| easy_temporal | 0.20 | 0.20 | SAME |
| external_timing_dep | PASS | 0.20 | FLIP_TO_FAIL |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.20 | SAME |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.20 | 0.20 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.20 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.20 | PASS | FLIP_TO_PASS |
| shared_ref_coupling | 0.00 | 0.20 | SAME |
| temporal_semantic_drift | PASS | 0.20 | FLIP_TO_FAIL |
| **TOTAL** | **6/18** | **3/18** | **-3** |

#### Run 3 (`gpt-4o-mini_20260323_074306.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.20 | SAME |
| cache_invalidation_order | 0.20 | 0.20 | SAME |
| easy_aliasing | PASS | 0.20 | FLIP_TO_FAIL |
| easy_conservation | PASS | PASS | SAME |
| easy_state_machine | PASS | PASS | SAME |
| easy_temporal | 0.20 | 0.20 | SAME |
| external_timing_dep | 0.20 | PASS | FLIP_TO_PASS |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | PASS | PASS | SAME |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.20 | 0.20 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.20 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.20 | PASS | FLIP_TO_PASS |
| shared_ref_coupling | 0.00 | 0.20 | SAME |
| temporal_semantic_drift | PASS | PASS | SAME |
| **TOTAL** | **5/18** | **6/18** | **+1** |

### 5-mini

#### Run 1 (`gpt-5-mini_20260323_072520.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.00 | SAME |
| cache_invalidation_order | 0.00 | 0.20 | SAME |
| easy_aliasing | 0.00 | 0.00 | SAME |
| easy_conservation | 0.00 | 0.00 | SAME |
| easy_state_machine | 0.00 | 0.00 | SAME |
| easy_temporal | 0.00 | 0.00 | SAME |
| external_timing_dep | 0.00 | 0.00 | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.00 | SAME |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.00 | 0.00 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.00 | 0.20 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.00 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **0/18** | **0/18** | **+0** |

#### Run 2 (`gpt-5-mini_20260323_073659.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.00 | SAME |
| cache_invalidation_order | 0.00 | 0.20 | SAME |
| easy_aliasing | 0.00 | 0.00 | SAME |
| easy_conservation | 0.00 | 0.00 | SAME |
| easy_state_machine | 0.00 | 0.00 | SAME |
| easy_temporal | 0.00 | 0.00 | SAME |
| external_timing_dep | 0.00 | 0.20 | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.00 | SAME |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.00 | 0.00 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.00 | 0.00 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.00 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **0/18** | **0/18** | **+0** |

#### Run 3 (`gpt-5-mini_20260323_074436.jsonl`)

| Case | Baseline | CGE | Delta |
|---|---|---|---|
| async_race_lock | 0.00 | 0.00 | SAME |
| cache_invalidation_order | 0.00 | 0.20 | SAME |
| easy_aliasing | 0.00 | 0.00 | SAME |
| easy_conservation | 0.20 | 0.00 | SAME |
| easy_state_machine | 0.00 | 0.00 | SAME |
| easy_temporal | 0.00 | 0.00 | SAME |
| external_timing_dep | 0.00 | 0.20 | SAME |
| feature_flag_drift | 0.00 | 0.00 | SAME |
| hidden_dep_multihop | 0.00 | 0.00 | SAME |
| idempotency_trap | 0.20 | 0.20 | SAME |
| invariant_partial_fail | 0.20 | 0.20 | SAME |
| l3_state_pipeline | 0.00 | 0.20 | SAME |
| lazy_init_hazard | 0.00 | 0.00 | SAME |
| log_side_effect_order | 0.00 | 0.00 | SAME |
| partial_rollback_multi | 0.00 | 0.00 | SAME |
| retry_causality | 0.00 | 0.20 | SAME |
| shared_ref_coupling | 0.00 | 0.00 | SAME |
| temporal_semantic_drift | 0.00 | 0.00 | SAME |
| **TOTAL** | **0/18** | **0/18** | **+0** |

## 3. retry_causality Deep Dive

| Model | Run | BL pass | BL score | CGE pass | CGE score |
|---|---|---|---|---|---|
| nano | 1 | False | 0.00 | False | 0.20 |
| nano | 2 | False | 0.00 | False | 0.20 |
| nano | 3 | False | 0.00 | False | 0.20 |
| 4o-mini | 1 | False | 0.20 | True | 1.00 |
| 4o-mini | 2 | False | 0.20 | True | 1.00 |
| 4o-mini | 3 | False | 0.20 | True | 1.00 |
| 5-mini | 1 | False | 0.00 | False | 0.20 |
| 5-mini | 2 | False | 0.00 | False | 0.20 |
| 5-mini | 3 | False | 0.00 | False | 0.20 |

## 4. Case Categorization (across 3 runs)

### nano

| Case | Helps | Hurts | Neutral | Net |
|---|---|---|---|---|
| async_race_lock | 0 | 0 | 3 | +0  |
| cache_invalidation_order | 0 | 0 | 3 | +0  |
| easy_aliasing | 0 | 0 | 3 | +0  |
| easy_conservation | 3 | 0 | 0 | +3 ✓ |
| easy_state_machine | 0 | 0 | 3 | +0  |
| easy_temporal | 0 | 0 | 3 | +0  |
| external_timing_dep | 0 | 0 | 3 | +0  |
| feature_flag_drift | 0 | 0 | 3 | +0  |
| hidden_dep_multihop | 0 | 0 | 3 | +0  |
| idempotency_trap | 0 | 0 | 3 | +0  |
| invariant_partial_fail | 0 | 0 | 3 | +0  |
| l3_state_pipeline | 0 | 0 | 3 | +0  |
| lazy_init_hazard | 0 | 0 | 3 | +0  |
| log_side_effect_order | 0 | 0 | 3 | +0  |
| partial_rollback_multi | 0 | 0 | 3 | +0  |
| retry_causality | 0 | 0 | 3 | +0  |
| shared_ref_coupling | 0 | 0 | 3 | +0  |
| temporal_semantic_drift | 0 | 0 | 3 | +0  |

### 4o-mini

| Case | Helps | Hurts | Neutral | Net |
|---|---|---|---|---|
| async_race_lock | 0 | 2 | 1 | -2 ✗ |
| cache_invalidation_order | 0 | 0 | 3 | +0  |
| easy_aliasing | 0 | 3 | 0 | -3 ✗ |
| easy_conservation | 0 | 0 | 3 | +0  |
| easy_state_machine | 0 | 1 | 2 | -1 ✗ |
| easy_temporal | 0 | 0 | 3 | +0  |
| external_timing_dep | 1 | 1 | 1 | +0  |
| feature_flag_drift | 0 | 0 | 3 | +0  |
| hidden_dep_multihop | 0 | 1 | 2 | -1 ✗ |
| idempotency_trap | 0 | 0 | 3 | +0  |
| invariant_partial_fail | 0 | 0 | 3 | +0  |
| l3_state_pipeline | 0 | 0 | 3 | +0  |
| lazy_init_hazard | 0 | 0 | 3 | +0  |
| log_side_effect_order | 0 | 0 | 3 | +0  |
| partial_rollback_multi | 0 | 0 | 3 | +0  |
| retry_causality | 3 | 0 | 0 | +3 ✓ |
| shared_ref_coupling | 0 | 0 | 3 | +0  |
| temporal_semantic_drift | 0 | 2 | 1 | -2 ✗ |

### 5-mini

| Case | Helps | Hurts | Neutral | Net |
|---|---|---|---|---|
| async_race_lock | 0 | 0 | 3 | +0  |
| cache_invalidation_order | 0 | 0 | 3 | +0  |
| easy_aliasing | 0 | 0 | 3 | +0  |
| easy_conservation | 0 | 0 | 3 | +0  |
| easy_state_machine | 0 | 0 | 3 | +0  |
| easy_temporal | 0 | 0 | 3 | +0  |
| external_timing_dep | 0 | 0 | 3 | +0  |
| feature_flag_drift | 0 | 0 | 3 | +0  |
| hidden_dep_multihop | 0 | 0 | 3 | +0  |
| idempotency_trap | 0 | 0 | 3 | +0  |
| invariant_partial_fail | 0 | 0 | 3 | +0  |
| l3_state_pipeline | 0 | 0 | 3 | +0  |
| lazy_init_hazard | 0 | 0 | 3 | +0  |
| log_side_effect_order | 0 | 0 | 3 | +0  |
| partial_rollback_multi | 0 | 0 | 3 | +0  |
| retry_causality | 0 | 0 | 3 | +0  |
| shared_ref_coupling | 0 | 0 | 3 | +0  |
| temporal_semantic_drift | 0 | 0 | 3 | +0  |

## 5. Variance Analysis

### nano

- Baseline range: 0–1 (std=0.58)
- CGE range: 1–2 (std=0.58)
- Delta range: +1 to +1 (mean=+1.0, std=0.00)
- **CGE CONSISTENTLY HELPS** (all 3 runs positive)

### 4o-mini

- Baseline range: 5–8 (std=1.53)
- CGE range: 3–6 (std=1.53)
- Delta range: -4 to +1 (mean=-2.0, std=2.65)
- **EFFECT IS INCONSISTENT** (sign varies across runs)

### 5-mini

- Baseline range: 0–0 (std=0.00)
- CGE range: 0–0 (std=0.00)
- Delta range: +0 to +0 (mean=+0.0, std=0.00)
- **CGE HAS NO EFFECT** (all 3 runs zero)

## 6. Conclusions

### Is CGE improvement consistent?

- **nano:** YES. Delta = +1 in all 3 runs. Driven entirely by `easy_conservation` flipping FAIL→PASS under CGE.
- **4o-mini:** NO. Delta ranges from -4 to +1. The effect sign is unstable.
- **5-mini:** N/A. Both conditions score 0/18 in all 3 runs.

### Does retry_causality reliably improve?

- **4o-mini:** YES. 3/3 runs: baseline=FAIL, CGE=PASS. This is the single most reliable CGE finding.
- **nano/5-mini:** Score improves (0.00→0.20) but never passes. Consistent improvement, insufficient for pass.

### Does CGE hurt easy cases?

- **4o-mini:** YES. `easy_aliasing` flips PASS→FAIL in 3/3 runs. Contract overhead degrades simple cases.
- **nano/5-mini:** No effect on easy cases (already failing).

### Is variance large enough to affect conclusions?

- **4o-mini baseline:** std=1.53 (range 5–8). Substantial variance makes single-run comparisons unreliable.
- **nano/5-mini:** Low variance (0–1 passes). Conclusions are stable.

> **Bottom line:** CGE has a small but consistent positive effect on nano (+1/run),
> a reliably positive effect on retry_causality for 4o-mini, but an overall negative
> effect on 4o-mini due to degradation on easy/medium cases. The prior claim that
> 'CGE hurts 4o-mini' is partially supported (2/3 runs) but not conclusive (1/3 shows +1).
> Multiple runs are required for any CGE conclusion on 4o-mini.
