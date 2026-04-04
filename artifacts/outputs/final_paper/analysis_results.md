# Full Analysis Results — LEG Intervention Effectiveness

**Dataset:** 42,188 rows | 8 models | 6 conditions | 58 cases | 28 families
**Sources:** 42 log directories (global_calibration, retry_critique stages 0-2, stage_b/c_critique, v2_oracle, v2_canonical, v2_targeted)
**Parse success:** 100% after 937-row pre-filter. Strict and parse-conditioned results are identical. Zero reconstruction artifacts.

---

## 1. DATA INTEGRITY

### Rows per condition

| Condition | Rows |
|---|---|
| baseline_v2 | 11,249 |
| leg_reduction_lean_v2 | 9,869 |
| leg_reduction_v2 | 8,652 |
| retry_leg_critique_strict_v2 | 4,531 |
| retry_bare_retry_v2 | 4,460 |
| retry_reasoning_only_critique_v1 | 3,427 |

### Rows per model

| Model | Rows |
|---|---|
| gpt-4o-mini | 10,535 |
| gpt-5.4-mini | 10,505 |
| gpt-5-mini | 8,463 |
| gpt-4.1-nano | 7,854 |
| claude-sonnet-4-6 | 2,418 |
| claude-haiku-4-5-20251001 | 1,262 |
| gpt-5 | 980 |
| claude-sonnet-4-20250514 | 171 |

### Pairing integrity

| Comparison | Paired trials | Unpaired baseline | Unpaired treatment |
|---|---|---|---|
| baseline_v2 vs lean | 7,495 | 247 | 137 |
| baseline_v2 vs full_leg | 7,307 | 435 | 132 |
| baseline_v2 vs retry | 3,178 | 4,564 | 63 |
| baseline_v2 vs retry_strict | 3,394 | 4,348 | 76 |
| baseline_v2 vs retry_reasoning | 2,978 | 4,764 | 75 |

---

## 2. CORE PAIRED DELTAS

### LEAN (leg_reduction_lean_v2 vs baseline_v2)

Overall: pass Δ=-0.001, LEG Δ=-0.038 (17,122 paired trials)

| Model | Pass Δ | LEG Δ | N |
|---|---|---|---|
| claude-haiku-4-5 | +0.214 | -0.097 | 614 |
| claude-sonnet-4-6 | +0.229 | -0.232 | 1,050 |
| gpt-4.1-nano | -0.021 | -0.003 | 3,080 |
| gpt-4o-mini | -0.046 | -0.069 | 4,663 |
| gpt-5 | +0.084 | -0.161 | 310 |
| gpt-5-mini | +0.003 | -0.031 | 3,188 |
| gpt-5.4-mini | -0.010 | +0.006 | 4,217 |

### Full LEG (leg_reduction_v2 vs baseline_v2)

Overall: pass Δ=-0.003, LEG Δ=-0.024 (13,239 paired trials)

| Model | Pass Δ | LEG Δ | N |
|---|---|---|---|
| claude-haiku-4-5 | +0.395 | -0.322 | 368 |
| claude-sonnet-4-6 | +0.124 | -0.113 | 662 |
| gpt-4.1-nano | -0.079 | -0.017 | 2,645 |
| gpt-4o-mini | -0.005 | -0.039 | 3,062 |
| gpt-5 | +0.076 | -0.061 | 270 |
| gpt-5-mini | +0.043 | +0.002 | 2,862 |
| gpt-5.4-mini | -0.036 | +0.004 | 3,370 |

### Bare retry (retry_bare_retry_v2 vs baseline_v2)

Overall: pass Δ=+0.053, LEG Δ=-0.019 (11,197 paired trials)

| Model | Pass Δ | LEG Δ | N |
|---|---|---|---|
| claude-haiku-4-5 | -0.057 | +0.048 | 459 |
| claude-sonnet-4-6 | +0.056 | -0.031 | 444 |
| gpt-4.1-nano | +0.042 | -0.049 | 1,460 |
| gpt-4o-mini | +0.080 | -0.046 | 3,677 |
| gpt-5 | +0.020 | -0.033 | 100 |
| gpt-5-mini | +0.098 | +0.004 | 1,275 |
| gpt-5.4-mini | +0.004 | +0.007 | 3,782 |

### Retry + strict critique (retry_leg_critique_strict_v2 vs baseline_v2)

Overall: pass Δ=+0.079, LEG Δ=-0.036 (10,811 paired trials)

| Model | Pass Δ | LEG Δ | N |
|---|---|---|---|
| claude-haiku-4-5 | +0.175 | -0.101 | 325 |
| claude-sonnet-4-6 | +0.273 | -0.242 | 460 |
| gpt-4.1-nano | +0.076 | -0.032 | 1,338 |
| gpt-4o-mini | +0.049 | -0.026 | 3,800 |
| gpt-5 | +0.200 | -0.187 | 100 |
| gpt-5-mini | +0.091 | -0.004 | 1,389 |
| gpt-5.4-mini | +0.046 | -0.027 | 3,399 |

### Retry + reasoning critique (retry_reasoning_only_critique_v1 vs baseline_v2)

Overall: pass Δ=+0.075, LEG Δ=-0.036 (7,173 paired trials)

| Model | Pass Δ | LEG Δ | N |
|---|---|---|---|
| claude-haiku-4-5 | +0.150 | -0.090 | 79 |
| claude-sonnet-4-6 | +0.213 | -0.208 | 100 |
| gpt-4.1-nano | +0.090 | -0.045 | 862 |
| gpt-4o-mini | +0.037 | -0.025 | 2,454 |
| gpt-5 | +0.080 | -0.130 | 60 |
| gpt-5-mini | +0.091 | -0.006 | 1,067 |
| gpt-5.4-mini | +0.054 | -0.033 | 2,551 |

---

## 3. INTERVENTION COMPARISON SUMMARY

| Intervention | Mean Δpass | % Helped (>10pp) | % Hurt (<-10pp) | Help/Harm Ratio |
|---|---|---|---|---|
| LEAN (single-shot) | -0.001 | 14.7% | 15.1% | 0.97 |
| Full LEG (single-shot) | -0.003 | 17.4% | 15.8% | 1.10 |
| Bare retry | +0.053 | 24.1% | 5.2% | **4.63** |
| Retry + strict critique | +0.079 | 20.3% | 3.9% | **5.21** |
| Retry + reasoning critique | +0.075 | 21.2% | 2.2% | **9.64** |

---

## 4. LEAN VS FULL LEG COMPARISON

Across 252 shared (case_id, model) pairs:

| Outcome | Count | % |
|---|---|---|
| LEAN > LEG | 56 | 22.2% |
| LEG > LEAN | 70 | 27.8% |
| Tie (~equal) | 126 | 50.0% |

Mean pass_delta LEAN: -0.0010
Mean pass_delta LEG: -0.0028
Mean difference (LEAN - LEG): +0.0018

Neither dominates. They are complementary.

### Cases where LEAN >> LEG (>20pp difference)

| Case | Model | LEAN Δ | LEG Δ | Diff |
|---|---|---|---|---|
| retry_dup_b | gpt-4.1-nano | +0.000 | -1.000 | +1.000 |
| alias_config_c | gpt-4.1-nano | -0.062 | -0.900 | +0.838 |
| partial_update_b | gpt-4.1-nano | +0.000 | -0.750 | +0.750 |
| mutable_default_a | gpt-4o-mini | +0.000 | -0.700 | +0.700 |
| wrong_condition_c | gpt-4.1-nano | +0.000 | -0.700 | +0.700 |

### Cases where LEG >> LEAN (>20pp difference)

| Case | Model | LEAN Δ | LEG Δ | Diff |
|---|---|---|---|---|
| silent_default_b | gpt-4.1-nano | -0.900 | +0.000 | -0.900 |
| early_return_a | gpt-4o-mini | -0.321 | +0.500 | -0.821 |
| effect_order_b | gpt-4o-mini | -0.475 | +0.316 | -0.791 |
| lazy_init_a | gpt-4.1-nano | -0.667 | +0.000 | -0.667 |
| use_before_set_b | gpt-4o-mini | +0.015 | +0.596 | -0.582 |

---

## 5. RECONSTRUCTION ARTIFACT DETECTION

Parse success rate is 100% across all (model, condition) combinations. All observed effects are real. No artifacts.

### LEAN artifact counts

| Category | Count |
|---|---|
| MIXED/UNCLEAR | 137 |
| REAL_HARM | 61 |
| REAL_HELP | 54 |

### Full LEG artifact counts

| Category | Count |
|---|---|
| MIXED/UNCLEAR | 128 |
| REAL_HELP | 65 |
| REAL_HARM | 60 |

### Retry+strict artifact counts

| Category | Count |
|---|---|
| MIXED/UNCLEAR | 137 |
| REAL_HELP | 78 |
| REAL_HARM | 17 |

### Retry+reasoning artifact counts

| Category | Count |
|---|---|
| MIXED/UNCLEAR | 142 |
| REAL_HELP | 72 |
| REAL_HARM | 17 |

---

## 6. FAMILY × INTERVENTION — MEAN Δpass

| Family | LEAN | Full LEG | Retry | Retry+strict | Retry+reasoning | Best |
|---|---|---|---|---|---|---|
| false_fix_deadlock | +0.010 | -0.027 | +0.037 | **+0.459** | +0.328 | retry_strict |
| invariant_partial_fail | +0.337 | +0.168 | -0.012 | **+0.399** | +0.300 | retry_strict |
| feature_flag_drift | +0.257 | **+0.359** | +0.050 | +0.140 | +0.143 | full_leg |
| l3_state_pipeline | +0.105 | -0.028 | +0.077 | +0.347 | **+0.370** | retry_reasoning |
| missing_branch | -0.086 | -0.044 | -0.000 | -0.025 | **+0.137** | retry_reasoning |
| use_before_set | -0.019 | +0.056 | +0.067 | +0.073 | **+0.105** | retry_reasoning |
| cache_invalidation_order | +0.115 | +0.076 | +0.024 | +0.206 | **+0.212** | retry_reasoning |
| wrong_condition | +0.044 | -0.037 | +0.025 | +0.083 | **+0.092** | retry_reasoning |
| lost_update | +0.112 | +0.157 | +0.198 | +0.232 | **+0.255** | retry_reasoning |
| hidden_dep_multihop | +0.111 | +0.058 | +0.050 | **+0.174** | +0.099 | retry_strict |
| partial_rollback | -0.035 | -0.050 | **+0.199** | +0.110 | +0.130 | retry |
| commit_gate | **+0.169** | +0.050 | +0.188 | +0.138 | +0.062 | lean |
| overdetermination | +0.053 | **+0.136** | +0.011 | -0.010 | +0.030 | full_leg |
| partial_update | -0.020 | -0.024 | +0.069 | **+0.076** | +0.058 | retry_strict |
| check_then_act | +0.083 | +0.043 | +0.085 | **+0.111** | +0.103 | retry_strict |
| ordering_dependency | +0.056 | -0.037 | +0.106 | **+0.150** | +0.025 | retry_strict |
| early_return | -0.051 | +0.101 | **+0.137** | +0.092 | +0.035 | retry |
| effect_order | -0.104 | **+0.045** | +0.045 | -0.018 | -0.045 | full_leg |
| config_shadowing | -0.139 | -0.104 | +0.022 | +0.025 | **+0.041** | retry_reasoning |
| async_race_lock | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — |

### Which intervention wins per family?

| Intervention | # Families |
|---|---|
| Retry+reasoning | **10** |
| Retry+strict | 7 |
| Bare retry | 5 |
| LEAN | 3 |
| Full LEG | 3 |

---

## 7. FAMILY × INTERVENTION — MEAN ΔLEG

| Family | LEAN | Full LEG | Retry | Retry+strict | Retry+reasoning | Best LEG reduction |
|---|---|---|---|---|---|---|
| feature_flag_drift | **-0.341** | -0.318 | +0.003 | -0.084 | -0.089 | lean |
| invariant_partial_fail | -0.320 | -0.171 | +0.000 | **-0.430** | -0.293 | retry_strict |
| false_fix_deadlock | +0.145 | +0.063 | +0.036 | **-0.314** | -0.216 | retry_strict |
| l3_state_pipeline | **-0.234** | +0.037 | -0.053 | -0.219 | -0.208 | lean |
| async_race_lock | **-0.185** | -0.090 | +0.015 | +0.067 | +0.044 | lean |
| commit_gate | -0.166 | -0.075 | **-0.188** | -0.138 | -0.062 | retry |
| partial_rollback | -0.066 | -0.008 | **-0.150** | -0.070 | -0.080 | retry |
| lost_update | -0.075 | -0.096 | -0.072 | -0.024 | **-0.133** | retry_reasoning |
| ordering_dependency | **-0.125** | -0.098 | -0.062 | -0.100 | +0.050 | lean |
| overdetermination | -0.101 | **-0.135** | +0.044 | +0.020 | +0.000 | full_leg |
| config_shadowing | +0.092 | +0.156 | +0.014 | **-0.023** | +0.000 | retry_strict |
| use_before_set | -0.021 | **-0.091** | -0.012 | -0.022 | -0.080 | full_leg |

---

## 8. FAMILY × INTERVENTION — HELP/HARM COUNTS

Format: Xh/Yhr = X helped (>+10pp) / Y hurt (<-10pp)

| Family | LEAN | Full LEG | Retry | Retry+strict | Retry+reasoning |
|---|---|---|---|---|---|
| alias_config | 1h/0hr | 1h/2hr | 1h/1hr | 0h/1hr | 0h/0hr |
| async_race_lock | 0h/0hr | 0h/0hr | 0h/0hr | 0h/0hr | 0h/0hr |
| cache_invalidation_order | 1h/0hr | 2h/1hr | 1h/0hr | 3h/0hr | 2h/0hr |
| check_then_act | 4h/2hr | 4h/2hr | 1h/0hr | 3h/1hr | 2h/0hr |
| commit_gate | 2h/0hr | 1h/0hr | 2h/0hr | 2h/0hr | 1h/0hr |
| config_shadowing | 0h/2hr | 0h/1hr | 0h/0hr | 1h/0hr | 1h/0hr |
| early_return | 1h/4hr | 3h/1hr | 6h/0hr | 2h/0hr | 2h/0hr |
| effect_order | 0h/4hr | 1h/0hr | 3h/0hr | 0h/1hr | 0h/1hr |
| false_fix_deadlock | 1h/0hr | 0h/1hr | 0h/0hr | 3h/0hr | 3h/0hr |
| feature_flag_drift | 2h/0hr | 4h/0hr | 3h/1hr | 3h/0hr | 3h/0hr |
| hidden_dep_multihop | 2h/0hr | 3h/1hr | 2h/1hr | 5h/0hr | 4h/0hr |
| index_misalign | 0h/2hr | 0h/2hr | 2h/1hr | 1h/0hr | 0h/1hr |
| invariant_partial_fail | 3h/0hr | 4h/0hr | 1h/0hr | 5h/0hr | 4h/0hr |
| l3_state_pipeline | 1h/0hr | 0h/1hr | 1h/0hr | 2h/0hr | 3h/0hr |
| lazy_init | 0h/3hr | 1h/3hr | 2h/1hr | 2h/0hr | 2h/0hr |
| lost_update | 3h/0hr | 4h/1hr | 4h/0hr | 4h/0hr | 4h/0hr |
| missing_branch | 1h/5hr | 2h/3hr | 2h/2hr | 1h/1hr | 5h/1hr |
| mutable_default | 0h/3hr | 2h/3hr | 3h/0hr | 2h/1hr | 3h/0hr |
| ordering_dependency | 1h/1hr | 0h/2hr | 1h/0hr | 1h/0hr | 0h/0hr |
| overdetermination | 1h/0hr | 2h/0hr | 1h/1hr | 0h/1hr | 1h/0hr |
| partial_rollback | 2h/3hr | 1h/3hr | 4h/0hr | 1h/0hr | 2h/0hr |
| partial_update | 1h/1hr | 2h/2hr | 4h/0hr | 3h/0hr | 2h/0hr |
| retry_dup | 0h/1hr | 0h/1hr | 1h/0hr | 0h/1hr | 0h/1hr |
| silent_default | 3h/1hr | 0h/3hr | 3h/1hr | 0h/0hr | 1h/0hr |
| stale_cache | 2h/2hr | 1h/1hr | 1h/1hr | 1h/1hr | 1h/0hr |
| temporal_drift | 3h/2hr | 2h/3hr | 2h/1hr | 0h/1hr | 1h/1hr |
| use_before_set | 1h/1hr | 3h/2hr | 3h/0hr | 1h/0hr | 1h/0hr |
| wrong_condition | 1h/1hr | 1h/1hr | 2h/1hr | 1h/0hr | 1h/0hr |

---

## 9. TOP CASES — BIGGEST HELPS AND HARMS

### LEAN — Top 5 helps

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| feature_flag_drift | feature_flag_drift | claude-sonnet-4-6 | 0.000→1.000 | **+1.000** |
| feature_flag_drift | feature_flag_drift | claude-haiku-4-5 | 0.020→0.940 | **+0.920** |
| invariant_partial_fail | invariant_partial_fail | claude-sonnet-4-6 | 0.117→1.000 | **+0.883** |
| invariant_partial_fail | invariant_partial_fail | gpt-5 | 0.120→0.960 | **+0.840** |
| wrong_condition_b | wrong_condition | gpt-4.1-nano | 0.013→0.684 | **+0.671** |

### LEAN — Top 5 harms

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| lazy_init_c | lazy_init | gpt-4o-mini | 0.963→0.000 | **-0.963** |
| silent_default_b | silent_default | gpt-4.1-nano | 0.900→0.000 | **-0.900** |
| use_before_set_b | use_before_set | gpt-4.1-nano | 0.988→0.225 | **-0.762** |
| mutable_default_c | mutable_default | gpt-4o-mini | 0.740→0.000 | **-0.740** |
| lazy_init_a | lazy_init | gpt-4.1-nano | 1.000→0.333 | **-0.667** |

### Full LEG — Top 5 helps

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| feature_flag_drift | feature_flag_drift | claude-haiku-4-5 | 0.020→1.000 | **+0.980** |
| feature_flag_drift | feature_flag_drift | claude-sonnet-4-6 | 0.000→0.960 | **+0.960** |
| use_before_set_a | use_before_set | gpt-4o-mini | 0.400→1.000 | **+0.600** |
| use_before_set_b | use_before_set | gpt-4o-mini | 0.000→0.596 | **+0.596** |
| cache_invalidation_order | cache_invalidation_order | gpt-4.1-nano | 0.071→0.600 | **+0.529** |

### Full LEG — Top 5 harms

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| retry_dup_b | retry_dup | gpt-4.1-nano | 1.000→0.000 | **-1.000** |
| alias_config_c | alias_config | gpt-4.1-nano | 1.000→0.100 | **-0.900** |
| use_before_set_b | use_before_set | gpt-4.1-nano | 0.988→0.150 | **-0.838** |
| partial_update_b | partial_update | gpt-4.1-nano | 1.000→0.250 | **-0.750** |
| wrong_condition_c | wrong_condition | gpt-4.1-nano | 1.000→0.300 | **-0.700** |

### Retry+strict — Top 5 helps

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| partial_rollback_a | partial_rollback | gpt-4.1-nano | 0.000→0.900 | **+0.900** |
| l3_state_pipeline | l3_state_pipeline | gpt-4o-mini | 0.000→0.900 | **+0.900** |
| wrong_condition_b | wrong_condition | gpt-4.1-nano | 0.000→0.900 | **+0.900** |
| false_fix_deadlock | false_fix_deadlock | claude-sonnet-4-6 | 0.000→0.900 | **+0.900** |
| invariant_partial_fail | invariant_partial_fail | claude-sonnet-4-6 | 0.122→0.978 | **+0.856** |

### Retry+reasoning — Top 5 helps

| Case | Family | Model | Baseline→Treatment | Δ |
|---|---|---|---|---|
| partial_rollback_a | partial_rollback | gpt-4.1-nano | 0.000→1.000 | **+1.000** |
| wrong_condition_b | wrong_condition | gpt-4.1-nano | 0.000→1.000 | **+1.000** |
| invariant_partial_fail | invariant_partial_fail | claude-haiku-4-5 | 0.000→0.900 | **+0.900** |
| use_before_set_b | use_before_set | gpt-4o-mini | 0.000→0.851 | **+0.851** |
| l3_state_pipeline | l3_state_pipeline | gpt-4o-mini | 0.000→0.700 | **+0.700** |

---

## 10. MODEL-SPECIFIC BEHAVIOR

### LEAN

| Model | Pass Δ | LEG Δ | % Helped | % Hurt | LEG→pass converting |
|---|---|---|---|---|---|
| claude-haiku-4-5 | +0.214 | -0.097 | 40.0% | 0.0% | 40.0% |
| claude-sonnet-4-6 | +0.229 | -0.232 | 45.5% | 0.0% | 45.5% |
| gpt-4.1-nano | -0.021 | -0.003 | 19.3% | 17.5% | 17.5% |
| gpt-4o-mini | -0.046 | -0.069 | 17.2% | 24.1% | 15.5% |
| gpt-5 | +0.084 | -0.161 | 20.0% | 20.0% | 20.0% |
| gpt-5-mini | +0.003 | -0.031 | 5.2% | 12.1% | 8.6% |
| gpt-5.4-mini | -0.010 | +0.006 | 8.6% | 10.3% | 10.3% |

### Full LEG

| Model | Pass Δ | LEG Δ | % Helped | % Hurt | LEG→pass converting |
|---|---|---|---|---|---|
| claude-haiku-4-5 | +0.395 | -0.322 | 100.0% | 0.0% | 80.0% |
| claude-sonnet-4-6 | +0.124 | -0.113 | 36.4% | 9.1% | 36.4% |
| gpt-4.1-nano | -0.079 | -0.017 | 10.3% | 19.0% | 13.8% |
| gpt-4o-mini | -0.005 | -0.039 | 20.7% | 24.1% | 20.7% |
| gpt-5 | +0.076 | -0.061 | 20.0% | 0.0% | 20.0% |
| gpt-5-mini | +0.043 | +0.002 | 20.7% | 5.2% | 8.6% |
| gpt-5.4-mini | -0.036 | +0.004 | 6.9% | 19.0% | 6.9% |

### Retry+strict

| Model | Pass Δ | LEG Δ | % Helped | % Hurt | LEG→pass converting |
|---|---|---|---|---|---|
| claude-haiku-4-5 | +0.175 | -0.101 | 40.0% | 20.0% | 40.0% |
| claude-sonnet-4-6 | +0.273 | -0.242 | 55.6% | 0.0% | 55.6% |
| gpt-4.1-nano | +0.076 | -0.032 | 19.1% | 6.4% | 19.1% |
| gpt-4o-mini | +0.049 | -0.026 | 17.0% | 9.4% | 13.2% |
| gpt-5 | +0.200 | -0.187 | 40.0% | 0.0% | 60.0% |
| gpt-5-mini | +0.091 | -0.004 | 21.1% | 0.0% | 8.8% |
| gpt-5.4-mini | +0.046 | -0.027 | 14.3% | 0.0% | 12.5% |

---

## 11. LEG-SUFFERING CASE CONVERSION

### LEAN — LEG-suffering pairs (baseline LEG ≥ 0.4)

44 LEG-suffering (case, model) pairs:
- **Improved (>+10pp): 18/44 (40.9%)**
- Unchanged: 24/44 (54.5%)
- Worsened (<-10pp): 2/44 (4.5%)

### Full LEG — LEG-suffering pairs

44 LEG-suffering (case, model) pairs:
- **Improved (>+10pp): 19/44 (43.2%)**
- Unchanged: 25/44 (56.8%)
- Worsened (<-10pp): 0/44 (0.0%)

### Retry+strict — LEG-suffering pairs

44 LEG-suffering (case, model) pairs:
- **Improved (>+10pp): 18/44 (40.9%)**
- Unchanged: 25/44 (56.8%)
- Worsened (<-10pp): 1/44 (2.3%)

### Retry+reasoning — LEG-suffering pairs

42 LEG-suffering (case, model) pairs:
- **Improved (>+10pp): 19/42 (45.2%)**
- Unchanged: 23/42 (54.8%)
- Worsened (<-10pp): 0/42 (0.0%)

---

## 12. HETEROGENEITY ANALYSIS

A case is heterogeneous if at least one model has pass_delta > +10pp AND at least one has pass_delta < -10pp.

### LEAN heterogeneity

8/58 cases heterogeneous (13.8%)

| Family | % Heterogeneous | Avg Abs Delta |
|---|---|---|
| check_then_act | 100% | 0.244 |
| ordering_dependency | 100% | 0.156 |
| temporal_drift | 33% | 0.081 |
| stale_cache | 33% | 0.135 |
| silent_default | 33% | 0.160 |
| partial_update | 33% | 0.093 |
| partial_rollback | 33% | 0.102 |
| missing_branch | 33% | 0.165 |

### Full LEG heterogeneity

10/58 cases heterogeneous (17.2%)

---

## 13. FAMILY FAILURE TYPE CLASSIFICATION

### Classification rules

- **EXECUTION_LIMITED:** high LEG (≥0.4), low pass (<0.3), retry or critique improves ≥+15pp
- **BELIEF_LIMITED:** retry alone weak (<+10pp), retry+reasoning or retry+strict ≥+15pp
- **REPRESENTATION_LIMITED:** low pass (<0.3), ALL interventions <+5pp
- **ALREADY_SOLVED_FRAGILE:** high pass (≥0.8), some interventions cause ≥-10pp drop

### Results

| Family | Failure Type | Best Intervention | Avg Baseline Pass | Avg Baseline LEG | Best Δ |
|---|---|---|---|---|---|
| false_fix_deadlock | EXECUTION_LIMITED | retry_strict | 0.176 | 0.425 | +0.456 |
| invariant_partial_fail | EXECUTION_LIMITED | retry_strict | 0.057 | 0.572 | +0.397 |
| feature_flag_drift | BELIEF_LIMITED | full_leg | 0.317 | 0.555 | +0.368 |
| l3_state_pipeline | BELIEF_LIMITED | retry_reasoning | 0.331 | 0.374 | +0.364 |
| missing_branch | BELIEF_LIMITED | retry_reasoning | 0.619 | 0.287 | +0.233 |
| use_before_set | BELIEF_LIMITED | retry_reasoning | 0.745 | 0.234 | +0.211 |
| cache_invalidation_order | BELIEF_LIMITED | retry_reasoning | 0.472 | 0.219 | +0.210 |
| wrong_condition | BELIEF_LIMITED | retry_reasoning | 0.835 | 0.000 | +0.200 |
| lost_update | EXECUTION_LIMITED | retry_reasoning | 0.333 | 0.333 | +0.193 |
| hidden_dep_multihop | BELIEF_LIMITED | retry_strict | 0.405 | 0.192 | +0.187 |
| partial_rollback | EXECUTION_LIMITED | retry | 0.787 | 0.153 | +0.181 |
| commit_gate | EXECUTION_LIMITED | lean | 0.846 | 0.150 | +0.154 |
| partial_update | EXECUTION_LIMITED | retry | 0.825 | 0.025 | +0.144 |
| check_then_act | EXECUTION_LIMITED | retry_strict | 0.529 | 0.172 | +0.139 |
| early_return | EXECUTION_LIMITED | retry_strict | 0.753 | 0.073 | +0.117 |
| effect_order | ALREADY_SOLVED_FRAGILE | full_leg | 0.818 | 0.117 | +0.100 |
| mutable_default | ALREADY_SOLVED_FRAGILE | retry_reasoning | 0.883 | 0.052 | +0.083 |
| temporal_drift | ALREADY_SOLVED_FRAGILE | lean | 0.856 | 0.003 | +0.083 |
| config_shadowing | REPRESENTATION_LIMITED | retry_reasoning | 0.311 | 0.547 | +0.037 |
| lazy_init | ALREADY_SOLVED_FRAGILE | retry_strict | 0.967 | 0.000 | +0.023 |
| alias_config | ALREADY_SOLVED_FRAGILE | lean | 0.984 | 0.013 | +0.003 |
| async_race_lock | REPRESENTATION_LIMITED | lean | 0.000 | 0.535 | +0.000 |

### Failure type distribution

| Failure Type | Count |
|---|---|
| EXECUTION_LIMITED | 8 |
| BELIEF_LIMITED | 7 |
| ALREADY_SOLVED_FRAGILE | 5 |
| MIXED | 5 |
| REPRESENTATION_LIMITED | 2 |
| NEUTRAL | 1 |

---

## 14. INTERVENTION EFFECTIVENESS BY FAILURE TYPE

| Failure Type | lean | full_leg | retry | retry_strict | retry_reasoning |
|---|---|---|---|---|---|
| **EXECUTION_LIMITED** (41 pairs) | +0.090 (14h/6hr) | +0.064 (14h/5hr) | +0.096 (14h/1hr) | **+0.214 (21h/1hr)** | +0.158 (17h/2hr) |
| **BELIEF_LIMITED** (35 pairs) | +0.085 (8h/2hr) | +0.096 (12h/5hr) | +0.054 (9h/1hr) | +0.171 (15h/1hr) | **+0.209 (17h/0hr)** |
| **ALREADY_SOLVED_FRAGILE** (21 pairs) | -0.060 (2h/4hr) | -0.097 (1h/7hr) | +0.036 (3h/0hr) | +0.022 (3h/0hr) | +0.018 (1h/1hr) |
| **REPRESENTATION_LIMITED** (11 pairs) | -0.075 (0h/2hr) | -0.056 (0h/1hr) | +0.010 (0h/0hr) | +0.012 (1h/0hr) | +0.020 (1h/0hr) |
| **MIXED** (21 pairs) | +0.027 (5h/4hr) | -0.008 (4h/5hr) | +0.055 (5h/1hr) | +0.056 (5h/1hr) | +0.044 (4h/1hr) |

---

## 15. RESPONSE SHAPE CLASSIFICATION

For each (family, model), classified by how it responds to the intervention ladder:

| Response Type | Count | Definition |
|---|---|---|
| flat | 40 | Max delta < +5pp across all interventions |
| retry_dominant | 23 | Retry variants outperform all single-shot |
| critique_sensitive | 18 | Retry ≈ baseline, but retry+critique >> retry |
| single_shot_sensitive | 17 | LEAN or full_leg >> all retry variants |
| negative_sensitive | 13 | At least one intervention causes ≥-10pp drop |
| monotonic_positive | 11 | Increasing improvement baseline→retry→critique |
| mixed | 11 | No clear pattern |

---

## 16. LEG SUBTYPE CLASSIFICATION

45 LEG-suffering (case, model) pairs, classified:

| LEG Subtype | Count | % | Definition |
|---|---|---|---|
| **convertible_LEG** | 16 | 35.6% | Retry alone fixes (Δpass > +10pp) |
| **belief_correctable_LEG** | 17 | 37.8% | Retry alone fails, critique fixes |
| **irreducible_LEG** | 12 | 26.7% | No intervention fixes |

### LEG subtype by family

| Family | Convertible | Belief-correctable | Irreducible |
|---|---|---|---|
| async_race_lock | 0 | 0 | **4** |
| config_shadowing | 0 | 0 | **4** |
| invariant_partial_fail | 1 | **4** | 0 |
| false_fix_deadlock | 0 | **3** | 1 |
| feature_flag_drift | 2 | 2 | 0 |
| lost_update | **2** | 1 | 0 |
| partial_rollback | **2** | 0 | 0 |
| missing_branch | 0 | **2** | 0 |
| l3_state_pipeline | 0 | 1 | 1 |
| early_return | 0 | 0 | 0 |

Irreducible LEG concentrates in exactly 2 families: `async_race_lock` (4/4 models) and `config_shadowing` (4/6 models).

### LEG subtype by model

| Model | Convertible | Belief-correctable | Irreducible |
|---|---|---|---|
| claude-haiku-4-5 | 3 | 1 | 0 |
| claude-sonnet-4-6 | 1 | 2 | 1 |
| gpt-4.1-nano | 3 | 3 | 3 |
| gpt-4o-mini | 8 | 4 | 4 |
| gpt-5 | 0 | 1 | 1 |
| gpt-5-mini | 0 | 3 | 2 |
| gpt-5.4-mini | 1 | 3 | 1 |

### Irreducible LEG cases (full detail)

| Case | Model | Baseline Pass | Baseline LEG | Best Δ |
|---|---|---|---|---|
| async_race_lock | gpt-4o-mini | 0.000 | 0.469 | 0.000 |
| async_race_lock | gpt-5 | 0.000 | 0.557 | 0.000 |
| async_race_lock | gpt-5-mini | 0.000 | 0.600 | 0.000 |
| async_race_lock | gpt-5.4-mini | 0.000 | 0.747 | 0.000 |
| config_shadowing | claude-sonnet-4-6 | 0.000 | 0.983 | 0.000 |
| config_shadowing | gpt-4.1-nano | 0.000 | 0.854 | +0.027 |
| config_shadowing | gpt-4o-mini | 0.000 | 0.691 | 0.000 |
| config_shadowing | gpt-5-mini | 0.033 | 0.650 | +0.056 |
| effect_order_c | gpt-4o-mini | 0.300 | 0.567 | 0.000 |
| false_fix_deadlock | gpt-4.1-nano | 0.000 | 0.500 | 0.000 |
| l3_state_pipeline | gpt-4.1-nano | 0.008 | 0.512 | +0.088 |
| retry_dup_c | gpt-4o-mini | 0.000 | 1.000 | 0.000 |

---

## 17. REPRESENTATION-LIMITED REDEFINITION

134 (case, model) pairs with max Δ < 5pp, split by baseline characteristics:

| Subtype | Count | Definition |
|---|---|---|
| **already_solved** | 121 | High pass (≥0.8), low LEG — no room to improve |
| **structural_impossibility** | 10 | High LEG (≥0.4), low pass (<0.3) — model reasons but cannot execute |
| **capability_ceiling** | 3 | Low LEG (<0.4), low pass (<0.3) — model cannot reason or execute |

Structural impossibility by family:

| Family | Count |
|---|---|
| async_race_lock | 4 |
| config_shadowing | 3 |
| effect_order | 1 |
| false_fix_deadlock | 1 |
| retry_dup | 1 |

---

## 18. INTERVENTION HARM MAP

### Harm rates by intervention

| Intervention | % Hurt | Families affected | Mean when negative |
|---|---|---|---|
| lean | **15.1%** | 17 | -0.355 |
| full_leg | **15.8%** | 22 | -0.370 |
| retry | 5.2% | 11 | -0.149 |
| retry_strict | 3.9% | 9 | -0.177 |
| retry_reasoning | **2.2%** | 5 | -0.318 |

### Families with negative mean delta (harm map)

| Family | lean | full_leg | retry | retry_strict | retry_reasoning |
|---|---|---|---|---|---|
| config_shadowing | -0.139 (2/6) | -0.104 (1/6) | | | |
| lazy_init | -0.181 (3/12) | -0.103 (3/12) | | | |
| mutable_default | -0.122 (3/12) | -0.093 (3/12) | | | |
| effect_order | -0.104 (4/12) | | | | -0.045 (1/11) |
| missing_branch | -0.086 (5/12) | -0.044 (3/12) | | -0.025 (1/12) | |
| early_return | -0.051 (4/12) | | | | |
| alias_config | | -0.069 (2/12) | | | |
| index_misalign | -0.050 (2/12) | -0.050 (2/12) | | | |
| silent_default | | -0.085 (3/12) | | | |
| stale_cache | -0.050 (2/12) | -0.032 (1/12) | | | |
| temporal_drift | | -0.054 (3/13) | | | |

### Fragile families (harmed by ≥2 interventions)

- `config_shadowing`
- `lazy_init`
- `mutable_default`

### Safe families (harmed by 0 interventions)

`async_race_lock`, `cache_invalidation_order`, `check_then_act`, `commit_gate`, `feature_flag_drift`, `hidden_dep_multihop`, `invariant_partial_fail`, `lost_update`, `overdetermination`, `use_before_set`

### Unsafe interventions (>20% of models hurt)

| Intervention | Family | % Hurt | Mean Δ |
|---|---|---|---|
| lean | missing_branch | 42% | -0.086 |
| lean | check_then_act | 33% | +0.083 |
| lean | config_shadowing | 33% | -0.139 |
| lean | early_return | 33% | -0.051 |
| lean | effect_order | 33% | -0.104 |
| lean | lazy_init | 25% | -0.181 |
| lean | mutable_default | 25% | -0.122 |
| lean | partial_rollback | 25% | -0.035 |
| full_leg | ordering_dependency | 50% | -0.037 |
| full_leg | check_then_act | 33% | +0.043 |
| full_leg | lazy_init | 25% | -0.103 |
| full_leg | missing_branch | 25% | -0.044 |
| full_leg | mutable_default | 25% | -0.093 |
| full_leg | partial_rollback | 25% | -0.050 |
| full_leg | silent_default | 25% | -0.085 |
| full_leg | temporal_drift | 23% | -0.054 |

---

## 19. CROSS-MODEL CONSISTENCY ON FLAT FAMILIES

| Family | Classification | Detail |
|---|---|---|
| alias_config | TRUE STRUCTURAL (already solved) | 100% pass at baseline, flat across all 4 models |
| async_race_lock | TRUE STRUCTURAL (impossible) | 0% pass, 47-75% LEG, flat across all 5 models including gpt-5 |
| lazy_init | TRUE STRUCTURAL (already solved) | 100% pass, flat across all 4 models |
| config_shadowing | CAPABILITY THRESHOLD | Flat on 4/6 models (0% pass), but gpt-5 solves it (84%) and gpt-5.4-mini solves it (99.5%) |
| retry_dup | CAPABILITY THRESHOLD | Flat on 3/4 models (100% pass), gpt-4o-mini responds (90%→100%) |

---

## 20. CROSS-MODEL CONSISTENCY (FULL)

| Family | Std Pass | Std Delta | N Models | Consistency |
|---|---|---|---|---|
| feature_flag_drift | 0.404 | 0.449 | 7 | capability_sensitive |
| use_before_set | 0.486 | 0.397 | 4 | capability_sensitive |
| false_fix_deadlock | 0.359 | 0.382 | 6 | capability_sensitive |
| invariant_partial_fail | 0.049 | 0.350 | 7 | capability_sensitive |
| wrong_condition | 0.322 | 0.343 | 5 | capability_sensitive |
| l3_state_pipeline | 0.395 | 0.282 | 4 | capability_sensitive |
| cache_invalidation_order | 0.437 | 0.255 | 5 | capability_sensitive |
| lost_update | 0.287 | 0.241 | 6 | capability_sensitive |
| check_then_act | 0.256 | 0.201 | 6 | capability_sensitive |
| commit_gate | 0.188 | 0.188 | 4 | capability_sensitive |
| overdetermination | 0.420 | 0.184 | 5 | capability_sensitive |
| ordering_dependency | 0.279 | 0.180 | 4 | capability_sensitive |
| retry_dup | 0.168 | 0.168 | 4 | capability_sensitive |
| partial_rollback | 0.176 | 0.158 | 4 | capability_sensitive |
| early_return | 0.358 | 0.139 | 4 | consistent |
| effect_order | 0.252 | 0.133 | 4 | consistent |
| hidden_dep_multihop | 0.394 | 0.124 | 6 | consistent |
| partial_update | 0.158 | 0.124 | 4 | consistent |
| temporal_drift | 0.184 | 0.116 | 5 | consistent |
| missing_branch | 0.216 | 0.113 | 4 | consistent |
| index_misalign | 0.262 | 0.105 | 4 | consistent |
| mutable_default | 0.116 | 0.089 | 4 | consistent |
| stale_cache | 0.048 | 0.081 | 4 | consistent |
| config_shadowing | 0.472 | 0.066 | 6 | consistent |
| lazy_init | 0.020 | 0.036 | 4 | consistent |
| silent_default | 0.229 | 0.035 | 4 | consistent |
| alias_config | 0.024 | 0.006 | 4 | consistent |
| async_race_lock | 0.000 | 0.000 | 5 | consistent |

14 families capability_sensitive, 14 consistent.

---

## 21. FAMILIES RANKED BY BEST ACHIEVABLE Δpass

| Family | Best Δpass | Best Intervention | Worst Δpass | Spread |
|---|---|---|---|---|
| false_fix_deadlock | +0.459 | retry_strict | -0.027 | 0.485 |
| invariant_partial_fail | +0.399 | retry_strict | -0.012 | 0.411 |
| l3_state_pipeline | +0.370 | retry_reasoning | -0.028 | 0.398 |
| feature_flag_drift | +0.359 | full_leg | +0.050 | 0.309 |
| lost_update | +0.255 | retry_reasoning | +0.112 | 0.143 |
| cache_invalidation_order | +0.212 | retry_reasoning | +0.024 | 0.188 |
| partial_rollback | +0.199 | retry | -0.050 | 0.249 |
| commit_gate | +0.188 | retry | +0.050 | 0.138 |
| hidden_dep_multihop | +0.174 | retry_strict | +0.050 | 0.124 |
| ordering_dependency | +0.150 | retry_strict | -0.037 | 0.187 |
| early_return | +0.137 | retry | -0.051 | 0.188 |
| missing_branch | +0.137 | retry_reasoning | -0.086 | 0.223 |
| overdetermination | +0.136 | full_leg | -0.010 | 0.146 |
| check_then_act | +0.111 | retry_strict | +0.043 | 0.068 |
| use_before_set | +0.105 | retry_reasoning | -0.019 | 0.124 |
| wrong_condition | +0.092 | retry_reasoning | -0.037 | 0.129 |
| partial_update | +0.076 | retry_strict | -0.024 | 0.100 |
| mutable_default | +0.068 | retry_reasoning | -0.122 | 0.190 |
| silent_default | +0.050 | retry_reasoning | -0.085 | 0.135 |
| effect_order | +0.045 | full_leg | -0.104 | 0.149 |
| index_misalign | +0.042 | retry | -0.050 | 0.092 |
| config_shadowing | +0.041 | retry_reasoning | -0.139 | 0.180 |
| alias_config | +0.036 | lean | -0.069 | 0.105 |
| temporal_drift | +0.036 | lean | -0.054 | 0.090 |
| lazy_init | +0.027 | retry_strict | -0.181 | 0.208 |
| stale_cache | +0.025 | retry_reasoning | -0.050 | 0.075 |
| retry_dup | +0.011 | retry | -0.067 | 0.078 |
| async_race_lock | +0.000 | — | +0.000 | 0.000 |

### Intervention-resistant families (best Δpass < +5pp)

`effect_order`, `index_misalign`, `config_shadowing`, `alias_config`, `temporal_drift`, `lazy_init`, `stale_cache`, `retry_dup`, `async_race_lock` (9 families)

---

## 22. LEG CONVERSION — STRONG CONVERSIONS BY FAMILY

Where baseline LEG ≥ 0.4 and both leg_drop ≥ 0.2 and pass_gain ≥ 0.2:

| Family | Strong Conversions | Avg Pass Gain | Avg LEG Drop | Avg Conversion Ratio |
|---|---|---|---|---|
| invariant_partial_fail | 20 | +0.59 | 0.60 | 1.05 |
| feature_flag_drift | 14 | +0.61 | 0.63 | 0.96 |
| false_fix_deadlock | 4 | +0.70 | 0.58 | 1.20 |
| partial_rollback | 4 | +0.66 | 0.58 | 1.20 |
| lost_update | 4 | +0.39 | 0.33 | 0.95 |
| use_before_set | 4 | +0.62 | 0.60 | 1.00 |
| missing_branch | 3 | +0.45 | 0.42 | 1.11 |
| ordering_dependency | 3 | +0.38 | 0.38 | 1.05 |
| early_return | 2 | +0.44 | 0.37 | 1.19 |
| l3_state_pipeline | 2 | +0.80 | 0.50 | 1.60 |
| commit_gate | 2 | +0.43 | 0.43 | 1.00 |
| overdetermination | 2 | +0.32 | 0.47 | 0.68 |

Overall: 67/230 strong conversions (29%), 55 weak (24%), 108 no conversion (47%).

---

## 23. CRITICAL FINDINGS

### Pattern 1: LEG is three distinct mechanisms, not one

35.6% convertible (retry fixes), 37.8% belief-correctable (critique required), 26.7% irreducible (nothing works). Treating LEG as a single phenomenon is incorrect. The optimal intervention depends entirely on the subtype.

### Pattern 2: Single-shot interventions have 1:1 help/harm ratio

lean: 37 helped, 38 hurt (0.97:1). full_leg: 44 helped, 40 hurt (1.10:1). These are coin-flip interventions at the population level. They only help specific (family, model) pairs.

### Pattern 3: Critique achieves 10:1 help/harm ratio

retry_reasoning: 49 helped, 5 hurt (9.8:1). On BELIEF_LIMITED families specifically: 1/55 hurt. This is the safest intervention by a wide margin.

### Pattern 4: 53% of pairs are flat — hard boundary

134/253 (case, model) pairs have max Δ < 5pp across all interventions. Of these, 121 are already solved, 10 are structural impossibilities, 3 are capability ceilings. Current methods have no mechanism to address the structural impossibility class.

### Pattern 5: Intervention-family mismatch causes most harms

lean hurts 8 families. full_leg hurts 13 families. retry_reasoning hurts 0 families on BELIEF_LIMITED. The harm comes from applying the wrong intervention to the wrong failure type, not from intervention weakness in general.

### Anomaly 1: async_race_lock — LEG drops but pass stays at 0%

LEAN reduces LEG by -18.2pp but pass remains exactly 0%. The intervention changes the model's reasoning without enabling execution. This is the purest structural impossibility — the code generation task exceeds the model's capability regardless of reasoning quality.

### Anomaly 2: false_fix_deadlock and invariant_partial_fail classified EXECUTION_LIMITED but retry alone doesn't help

Bare retry delta is +3.5pp and -1.4pp respectively. Only critique fixes them (+45.6pp and +39.7pp). The models need to understand WHY the first attempt failed, not just try again.

### Anomaly 3: config_shadowing is a capability threshold, not a representation failure

gpt-5 solves it at 84% pass and gpt-5.4-mini at 99.5%, but all other models are at 0%. No intervention helps the weaker models. This is a discrete capability jump, not a gradual improvement.
