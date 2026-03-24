# T3 Benchmark — Full Ablation Results

**Date:** 2026-03-23
**Models:** gpt-4.1-nano, gpt-4o-mini, gpt-5-mini
**Cases:** 18 (14 hard L3 + 4 easy calibration)
**Conditions:** 20 (19 intervention types + contract_gated)

> **IMPORTANT:** This analysis was generated automatically and should be
> independently verified. Scores, pass rates, and interpretations may
> contain errors. The raw logs in `logs/` are the ground truth —
> cross-check any finding against the log files before citing.

---

## 1. Full Ablation Summary (19 conditions, 3 models)

### 1.1 Pass Rate by Condition

| Condition | nano (18) | 4o-mini (18) | 5-mini (18) |
|---|---|---|---|
| baseline | 0 (0%) | 5 (28%) | 1 (6%) |
| diagnostic | 1 (6%) | 5 (28%) | 3 (17%) |
| guardrail | 1 (6%) | 6 (33%) | 0 (0%) |
| guardrail_strict | 1 (6%) | 6 (33%) | 0 (0%) |
| counterfactual | 0 (0%) | 5 (28%) | 0 (0%) |
| reason_then_act | 1 (6%) | 7 (39%) | 1 (6%) |
| self_check | 0 (0%) | 8 (44%) | 0 (0%) |
| counterfactual_check | 1 (6%) | 5 (28%) | 0 (0%) |
| test_driven | 3 (17%) | 6 (33%) | 0 (0%) |
| repair_loop | 0 (0%) | 7 (39%) | 1 (6%) |
| scm_descriptive | 2 (11%) | 8 (44%) | 0 (0%) |
| scm_constrained | 1 (6%) | 6 (33%) | 0 (0%) |
| scm_constrained_evidence | 1 (6%) | 5 (28%) | 0 (0%) |
| scm_evidence_minimal | 1 (6%) | 7 (39%) | 1 (6%) |
| evidence_only | 1 (6%) | 7 (39%) | 1 (6%) |
| length_matched_control | 0 (0%) | 8 (44%) | 0 (0%) |
| structured_reasoning | 1 (6%) | 7 (39%) | 0 (0%) |
| free_form_reasoning | 0 (0%) | 7 (39%) | 0 (0%) |
| branching_reasoning | 1 (6%) | 4 (22%) | 0 (0%) |

### 1.2 Reasoning-Action Gaps by Condition

| Condition | nano | 4o-mini | 5-mini |
|---|---|---|---|
| baseline | 12 | 8 | 12 |
| diagnostic | 14 | 10 | 14 |
| guardrail | 12 | 9 | 15 |
| Total (all conditions) | 236 | 151 | 279 |

---

## 2. Per-Case Solve Rate (grouped by difficulty)

### 2.1 Easy Calibration Cases

| Case | Failure Mode | nano | 4o-mini | 5-mini |
|---|---|---|---|---|
| easy_aliasing | EASY_ALIASING | 3/19 (16%) | 18/19 (95%) | 0/19 (0%) |
| easy_conservation | EASY_CONSERVATION | 10/19 (53%) | 19/19 (100%) | 4/19 (21%) |
| easy_state_machine | EASY_STATE_MACHINE | 1/19 (5%) | 16/19 (84%) | 2/19 (11%) |
| easy_temporal | EASY_TEMPORAL | 1/19 (5%) | 8/19 (42%) | 1/19 (5%) |
| **Easy subtotal** | | **15/76 (20%)** | **61/76 (80%)** | **7/76 (9%)** |

### 2.2 Hard L3 Cases

| Case | Failure Mode | nano | 4o-mini | 5-mini |
|---|---|---|---|---|
| async_race_lock | RACE_CONDITION | 0/19 (0%) | 4/19 (21%) | 0/19 (0%) |
| cache_invalidation_order | CACHE_ORDERING | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| external_timing_dep | TIMING_DEPENDENCY | 0/19 (0%) | 18/19 (95%) | 0/19 (0%) |
| feature_flag_drift | FLAG_DRIFT | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| hidden_dep_multihop | HIDDEN_DEPENDENCY | 0/19 (0%) | 8/19 (42%) | 0/19 (0%) |
| idempotency_trap | IDEMPOTENCY_VIOLATION | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| invariant_partial_fail | INVARIANT_VIOLATION | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| l3_state_pipeline | STATE_SEMANTIC_VIOLATION | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| lazy_init_hazard | INIT_ORDER | 1/19 (5%) | 1/19 (5%) | 0/19 (0%) |
| log_side_effect_order | SIDE_EFFECT_ORDER | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| partial_rollback_multi | PARTIAL_ROLLBACK | 0/19 (0%) | 0/19 (0%) | 0/19 (0%) |
| retry_causality | RETRY_DUPLICATION | 0/19 (0%) | 0/19 (0%) | 1/19 (5%) |
| shared_ref_coupling | SHARED_REFERENCE | 0/19 (0%) | 12/19 (63%) | 0/19 (0%) |
| temporal_semantic_drift | TEMPORAL_CAUSAL_ERROR | 0/19 (0%) | 15/19 (79%) | 0/19 (0%) |
| **Hard subtotal** | | **1/266 (0.4%)** | **58/266 (22%)** | **1/266 (0.4%)** |

### 2.3 Grand Total

| | nano | 4o-mini | 5-mini |
|---|---|---|---|
| **All cases** | **16/342 (5%)** | **119/342 (35%)** | **8/342 (2%)** |

---

## 3. Fully Resistant Cases

These cases scored 0% across ALL 3 models and ALL 19 conditions (57 total attempts each):

| Case | Failure Mode |
|---|---|
| cache_invalidation_order | CACHE_ORDERING |
| feature_flag_drift | FLAG_DRIFT |
| idempotency_trap | IDEMPOTENCY_VIOLATION |
| invariant_partial_fail | INVARIANT_VIOLATION |
| l3_state_pipeline | STATE_SEMANTIC_VIOLATION |
| log_side_effect_order | SIDE_EFFECT_ORDER |
| partial_rollback_multi | PARTIAL_ROLLBACK |

---

## 4. Contract-Gated Execution (CGE) Results

### 4.1 CGE vs Baseline

| Case | nano BL | nano CG | 4o-mini BL | 4o-mini CG | 5-mini BL | 5-mini CG |
|---|---|---|---|---|---|---|
| hidden_dep_multihop | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 | 0.00 |
| temporal_semantic_drift | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 | 0.00 |
| invariant_partial_fail | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| l3_state_pipeline | 0.20 | 0.20 | 0.20 | 0.20 | 0.00 | 0.00 |
| easy_conservation | 0.00 | **1.00** | 1.00 | 0.00 | 0.20 | **1.00** |
| easy_state_machine | 0.00 | 0.20 | 1.00 | 1.00 | 0.00 | 0.00 |
| easy_aliasing | 0.20 | 0.00 | 1.00 | 0.20 | 0.00 | 0.00 |
| **Total pass** | **0/18** | **2/18** | **7/18** | **4/18** | **1/18** | **1/18** |

### 4.2 CGE Analysis

- **nano:** CGE helps (+2 passes vs 0 baseline). Contract elicitation forces structured thinking.
- **4o-mini:** CGE HURTS (-3 passes vs baseline). The extra contract step adds complexity that degrades the model's ability on cases it already solves. Notably, easy_conservation goes from PASS to FAIL.
- **5-mini:** CGE neutral (1 pass each, different cases). Contract doesn't help this model.

### 4.3 Contract Quality

| Model | Contracts parsed | Parse errors | Avg response length |
|---|---|---|---|
| nano | 17/18 | 1 | 1,635 bytes |
| 4o-mini | 18/18 | 0 | 1,303 bytes |
| 5-mini | 18/18 | 0 | 2,959 bytes |

---

## 5. Key Findings

### 5.1 Model Capability Hierarchy

gpt-4o-mini >> gpt-4.1-nano > gpt-5-mini

4o-mini is the only model that meaningfully responds to interventions.
5-mini is the weakest despite being the largest model name — it produces longer but less correct code.

### 5.2 No Single Intervention Dominates

Best condition varies by model:
- nano: test_driven (3/18), scm_descriptive (2/18)
- 4o-mini: self_check, scm_descriptive, length_matched_control (all 8/18)
- 5-mini: diagnostic (3/18)

### 5.3 Length-Matched Control Confound

For 4o-mini, `length_matched_control` (no causal content, just filler text) scores 8/18 — tied with the best real interventions. This suggests prompt length, not causal structure, drives much of the improvement for this model.

### 5.4 Reasoning-Action Gap is Pervasive

Across all models and conditions: models identify the correct issue ~60-80% of the time but produce wrong code anyway. More reasoning scaffolding (diagnostic, SCM) increases gap count because the model articulates more correct reasoning without translating it to code.

### 5.5 7 Cases are Fully Resistant

These cases resist ALL intervention types across ALL models. They represent genuine L3 failures that current prompt-based interventions cannot address.

### 5.6 Easy Cases Validate Difficulty Gradient

4o-mini solves 80% of easy cases but only 22% of hard cases. This confirms the benchmark measures genuine causal reasoning difficulty, not just prompt sensitivity.

---

## 6. Log Files

All raw data is in `logs/`:

### Full 19-condition ablation (342 calls each):
- `gpt-4.1-nano_20260323_060304.jsonl` + `_prompts.jsonl` + `_responses.jsonl`
- `gpt-4o-mini_20260323_060546.jsonl` + `_prompts.jsonl` + `_responses.jsonl`
- `gpt-5-mini_20260323_062448.jsonl` + `_prompts.jsonl` + `_responses.jsonl`

### CGE ablation (36 calls each):
- `gpt-4.1-nano_20260323_065831.jsonl` + `_prompts.jsonl` + `_responses.jsonl`
- `gpt-4o-mini_20260323_065949.jsonl` + `_prompts.jsonl` + `_responses.jsonl`
- `gpt-5-mini_20260323_070127.jsonl` + `_prompts.jsonl` + `_responses.jsonl`

---

## 7. Caveats

> **This analysis should be independently verified.**
>
> - Pass rates are based on execution-based evaluation (code is actually run).
>   The evaluator uses heuristic invariant checks that may have false positives
>   or false negatives. Check `exec_eval.py` invariant functions for each case.
>
> - Scores are non-deterministic across runs due to model sampling (temperature=0
>   but not fully deterministic for all model families). Results may vary ±1-2
>   passes per condition on re-run.
>
> - The "fully resistant" classification is based on this specific set of runs.
>   A different prompt formulation or model version could change results.
>
> - CGE results are from a single run per model. The contract elicitation step
>   adds variance — the model may generate different contracts on re-run.
>
> - The length-matched control finding (prompt length ≈ causal structure for
>   4o-mini) needs confirmation with more runs and different filler texts.
>
> - gpt-5-mini's poor performance may be partly due to the `temperature`
>   parameter not being supported (it uses default sampling), making it
>   less deterministic than the other models.

---

## 8. System Info

- Evaluation: execution-based (code is compiled and run against invariant tests)
- 166 unit/integration tests passing
- Per-run logs: metadata + full prompts + full responses (3 files per run)
- No log overwriting (timestamp-based filenames)
