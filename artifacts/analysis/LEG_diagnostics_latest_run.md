# LEG Diagnostic Analysis — Latest Run

**Date:** 2026-03-24
**Total attempt records:** 3252
**Models:** gpt-5.4-mini, gpt-5-mini, gpt-4o-mini, gpt-5.4-nano, gpt-4.1-nano
**Conditions:** retry_no_contract, retry_alignment
**Cases:** 58
**Eval model:** gpt-5-mini (for LEG evaluation)

> **Note:** gpt-5-mini has data from the V2 ablation (old format, no LEG eval, 1 trial).
> The other 4 models have V3 data (structured JSON, LEG eval, 3 trials).

---
## 1. Run Overview

| Model | Attempts | Cases | Trials | Conditions | LEG Eval |
|---|---|---|---|---|---|
| gpt-5.4-mini | 603 | 54 | 1 | retry_alignment, retry_no_contract | YES |
| gpt-5-mini | 279 | 51 | 1 | retry_adaptive, retry_no_contract | NO |
| gpt-4o-mini | 695 | 54 | 1 | retry_alignment, retry_no_contract | YES |
| gpt-5.4-nano | 861 | 58 | 1 | retry_alignment, retry_no_contract | YES |
| gpt-4.1-nano | 814 | 54 | 1 | retry_alignment, retry_no_contract | YES |

### Pass Rate by Model

| Model | Total | Passed | Pass Rate |
|---|---|---|---|
| gpt-5.4-mini | 603 | 231 | 38.3% |
| gpt-5-mini | 279 | 36 | 12.9% |
| gpt-4o-mini | 695 | 210 | 30.2% |
| gpt-5.4-nano | 861 | 175 | 20.3% |
| gpt-4.1-nano | 814 | 159 | 19.5% |

### Retry Distribution (attempts per run)

| Model | Runs | Avg Attempts | 1-attempt | 2-3 | 4-5 |
|---|---|---|---|---|---|
| gpt-5.4-mini | 108 | 5.6 | 0 (0%) | 52 (48%) | 56 (52%) |
| gpt-5-mini | 102 | 2.7 | 32 (31%) | 35 (34%) | 35 (34%) |
| gpt-4o-mini | 108 | 6.4 | 0 (0%) | 48 (44%) | 60 (56%) |
| gpt-5.4-nano | 116 | 7.4 | 0 (0%) | 39 (34%) | 77 (66%) |
| gpt-4.1-nano | 108 | 7.5 | 0 (0%) | 36 (33%) | 72 (67%) |

---
## 2. LEG Core Metrics

> LEG_true = blind evaluator says YES + evaluator inferred type matches classifier type + code fails

| Model | Failed (eval) | LEG_true | LEG Rate | Note |
|---|---|---|---|---|
| gpt-5.4-mini | 372 | 51 | 13.7% | |
| gpt-5-mini | — | — | — | No LEG eval (V2 run) |
| gpt-4o-mini | 485 | 54 | 11.1% | |
| gpt-5.4-nano | 686 | 63 | 9.2% | |
| gpt-4.1-nano | 655 | 46 | 7.0% | |

**Global LEG_true rate (4 models with eval): 214/2198 = 9.7%**

---
## 3. LEG by Bug Type / Failure Mode

| Failure Mode | Failed | LEG | Rate | Cases |
|---|---|---|---|---|
| STATE_SEMANTIC_VIOLATION | 66 | 22 | 33.3% | 1 |
| CACHE_ORDERING | 59 | 13 | 22.0% | 1 |
| SILENT_DEFAULT | 149 | 26 | 17.4% | 3 |
| RETRY_DUPLICATION | 147 | 22 | 15.0% | 2 |
| MISSING_BRANCH | 134 | 18 | 13.4% | 3 |
| TEMPORAL_DRIFT | 117 | 14 | 12.0% | 3 |
| FLAG_DRIFT | 62 | 7 | 11.3% | 1 |
| PARTIAL_STATE_UPDATE | 164 | 18 | 11.0% | 3 |
| MUTABLE_DEFAULT | 73 | 8 | 11.0% | 2 |
| USE_BEFORE_SET | 107 | 10 | 9.3% | 3 |
| STALE_CACHE | 155 | 14 | 9.0% | 3 |
| SIDE_EFFECT_ORDER | 161 | 13 | 8.1% | 3 |
| WRONG_CONDITION | 48 | 3 | 6.2% | 2 |
| INDEX_MISALIGN | 134 | 7 | 5.2% | 2 |
| EARLY_RETURN | 154 | 8 | 5.2% | 2 |
| INIT_ORDER | 106 | 5 | 4.7% | 3 |
| ALIASING | 28 | 1 | 3.6% | 2 |
| INVARIANT_VIOLATION | 98 | 3 | 3.1% | 2 |
| PARTIAL_ROLLBACK | 102 | 2 | 2.0% | 3 |
| RACE_CONDITION | 54 | 0 | 0.0% | 1 |
| HIDDEN_DEPENDENCY | 80 | 0 | 0.0% | 2 |

### Top LEG-inducing failure modes (>10% LEG rate, >10 failures):

- **STATE_SEMANTIC_VIOLATION**: 33.3% LEG rate (22/66)
- **CACHE_ORDERING**: 22.0% LEG rate (13/59)
- **SILENT_DEFAULT**: 17.4% LEG rate (26/149)
- **RETRY_DUPLICATION**: 15.0% LEG rate (22/147)
- **MISSING_BRANCH**: 13.4% LEG rate (18/134)
- **TEMPORAL_DRIFT**: 12.0% LEG rate (14/117)
- **FLAG_DRIFT**: 11.3% LEG rate (7/62)
- **PARTIAL_STATE_UPDATE**: 11.0% LEG rate (18/164)
- **MUTABLE_DEFAULT**: 11.0% LEG rate (8/73)

---
## 4. Retry Dynamics

### Success by Attempt Index

| Attempt | Total | Passed | Pass Rate | LEG_true (of failures) |
|---|---|---|---|---|
| 0 | 1422 | 674 (47.4%) | 47.4% | 0/678 (0.0%) |
| 1 | 748 | 74 (9.9%) | 9.9% | 71/604 (11.8%) |
| 2 | 532 | 42 (7.9%) | 7.9% | 74/446 (16.6%) |
| 3 | 340 | 10 (2.9%) | 2.9% | 46/295 (15.6%) |
| 4 | 210 | 11 (5.2%) | 5.2% | 23/175 (13.1%) |

### LEG Persistence Across Retries

Does LEG_true rate change with attempt number?

- Attempt 0: 0/678 = 0.0%
- Attempt 1: 71/604 = 11.8%
- Attempt 2: 74/446 = 16.6%
- Attempt 3: 46/295 = 15.6%
- Attempt 4: 23/175 = 13.1%

---
## 5. Trajectory Regimes

| Regime | Runs | Failed | LEG | LEG Rate |
|---|---|---|---|---|
| STAGNATION | 51 | 507 | 66 | 13.0% |
| UNCLASSIFIED | 66 | 585 | 62 | 10.6% |
| single_shot | 217 | 163 | 17 | 10.4% |
| DIVERGENCE | 49 | 562 | 51 | 9.1% |
| MONOTONIC_FIX | 47 | 250 | 15 | 6.0% |
| OSCILLATION | 10 | 131 | 3 | 2.3% |

---
## 6. LEG by Difficulty Level

| Difficulty | Failed | LEG | Rate | Success Rate |
|---|---|---|---|---|
| A | 34 | 0 | 0.0% | 91.9% |
| B | 855 | 89 | 10.4% | 14.4% |
| C | 1275 | 125 | 9.8% | 13.9% |
| L3 | 34 | 0 | 0.0% | 51.4% |

---
## 7. Condition Comparison

| Condition | Failed | LEG | LEG Rate | Success Rate |
|---|---|---|---|---|
| retry_no_contract | 1164 | 106 | 9.1% | 24.2% |
| retry_alignment | 1034 | 108 | 10.4% | 28.1% |

### Per-Model × Condition

| Model | Condition | Failed | LEG | Rate | Success |
|---|---|---|---|---|---|
| gpt-4o-mini | retry_no_contract | 253 | 27 | 10.7% | 27.7% |
| gpt-4o-mini | retry_alignment | 232 | 27 | 11.6% | 32.8% |
| gpt-4.1-nano | retry_no_contract | 343 | 19 | 5.5% | 19.1% |
| gpt-4.1-nano | retry_alignment | 312 | 27 | 8.7% | 20.0% |
| gpt-5.4-mini | retry_no_contract | 210 | 26 | 12.4% | 33.5% |
| gpt-5.4-mini | retry_alignment | 162 | 25 | 15.4% | 43.6% |
| gpt-5.4-nano | retry_no_contract | 358 | 34 | 9.5% | 19.6% |
| gpt-5.4-nano | retry_alignment | 328 | 29 | 8.8% | 21.2% |

---
## 8. Measurement Validity

| Model | Schema Compliance | Attempts with Valid JSON |
|---|---|---|
| gpt-5.4-mini | 100.0% | 603/603 |
| gpt-5-mini | 0.0% | 0/279 |
| gpt-4o-mini | 98.8% | 687/695 |
| gpt-5.4-nano | 99.4% | 856/861 |
| gpt-4.1-nano | 93.1% | 758/814 |

### Classifier Type Distribution (across all evaluated failures)

| Classifier Type | Count | % |
|---|---|---|
| HIDDEN_DEPENDENCY | 1255 | 57.1% |
| TEMPORAL_ORDERING | 495 | 22.5% |
| EDGE_CASE_MISSED | 269 | 12.2% |
| INVARIANT_VIOLATION | 67 | 3.0% |
| CONFOUNDING_LOGIC | 59 | 2.7% |
| UNKNOWN | 26 | 1.2% |
| LOGGING_INCONSISTENCY | 13 | 0.6% |
| RETRY_LOGIC_BUG | 7 | 0.3% |
| PARTIAL_STATE_UPDATE | 7 | 0.3% |

---
## 9. Per-Case LEG Hotspots

Cases with highest LEG_true rate (≥3 LEG events):

| Case | Failed | LEG | Rate | Difficulty | Failure Mode |
|---|---|---|---|---|---|
| l3_state_pipeline | 66 | 22 | 33.3% | C | STATE_SEMANTIC_VIOLATION |
| retry_dup_b | 92 | 21 | 22.8% | B | RETRY_DUPLICATION |
| missing_branch_c | 86 | 15 | 17.4% | C | MISSING_BRANCH |
| silent_default_b | 83 | 14 | 16.9% | B | SILENT_DEFAULT |
| cache_invalidation_order | 59 | 13 | 22.0% | C | CACHE_ORDERING |
| partial_update_b | 82 | 12 | 14.6% | B | PARTIAL_STATE_UPDATE |
| temporal_drift_b | 70 | 12 | 17.1% | B | TEMPORAL_DRIFT |
| silent_default_c | 47 | 12 | 25.5% | C | SILENT_DEFAULT |
| use_before_set_c | 72 | 9 | 12.5% | C | USE_BEFORE_SET |
| mutable_default_c | 60 | 8 | 13.3% | C | MUTABLE_DEFAULT |
| stale_cache_b | 85 | 7 | 8.2% | B | STALE_CACHE |
| stale_cache_c | 69 | 7 | 10.1% | C | STALE_CACHE |
| effect_order_b | 66 | 7 | 10.6% | B | SIDE_EFFECT_ORDER |
| feature_flag_drift | 62 | 7 | 11.3% | C | FLAG_DRIFT |
| partial_update_c | 65 | 6 | 9.2% | C | PARTIAL_STATE_UPDATE |
| effect_order_c | 93 | 6 | 6.5% | C | SIDE_EFFECT_ORDER |
| lazy_init_b | 62 | 5 | 8.1% | B | INIT_ORDER |
| early_return_c | 82 | 5 | 6.1% | C | EARLY_RETURN |
| index_misalign_c | 57 | 4 | 7.0% | C | INDEX_MISALIGN |
| index_misalign_b | 77 | 3 | 3.9% | B | INDEX_MISALIGN |
| invariant_partial_fail | 81 | 3 | 3.7% | C | INVARIANT_VIOLATION |
| missing_branch_b | 47 | 3 | 6.4% | B | MISSING_BRANCH |
| early_return_b | 72 | 3 | 4.2% | B | EARLY_RETURN |
| wrong_condition_c | 37 | 3 | 8.1% | C | WRONG_CONDITION |

---
## 10. Key Findings

1. **LEG is common:** 9.7% of evaluated failures show correct reasoning + wrong code.

2. **LEG is model-dependent:** gpt-5.4-mini (13.7%) > gpt-4o-mini (11.1%) > gpt-5.4-nano (9.2%) > gpt-4.1-nano (7.0%)

3. **Retry does NOT fix LEG:** LEG rate at attempt 0 = 0.0%, at attempt 3+ = 14.7%. LEG persists across retries.

4. **LEG concentrates in specific failure modes:**
   - STATE_SEMANTIC_VIOLATION: 33.3%
   - CACHE_ORDERING: 22.0%
   - SILENT_DEFAULT: 17.4%
   - RETRY_DUPLICATION: 15.0%
   - MISSING_BRANCH: 13.4%

5. **LEG clusters in STAGNATION regime:** 13.0% LEG rate in stagnating trajectories vs 9.7% overall.

6. **Alignment INCREASES observed LEG:** retry_alignment (10.4%) > retry_no_contract (9.1%). The plan instruction makes models articulate the fix more explicitly, making the gap MORE visible to the evaluator.

7. **Schema compliance is high:** 2904/3252 = 89.3%. Structured JSON output works reliably.

---
## 11. Hypotheses

**H1: LEG is a capability ceiling, not a reasoning failure.** More capable models (5.4-mini) show HIGHER LEG — they understand more bugs but still can't translate understanding to code. The bottleneck is downstream of comprehension.

**H2: LEG is a compliance artifact.** The model's code generation is dominated by instruction-following (task prompt) rather than its own diagnostic reasoning. When the task says "simplify by removing X" and reasoning says "X is important," the code follows the task.

**H3: LEG is persistent because retry provides wrong feedback.** Test failure messages describe WHAT failed but not WHY — the model already knows WHY. What it needs is permission to deviate from the task instruction, not more error information.

**H4: STAGNATION-regime LEG is qualitatively different from DIVERGENCE-regime LEG.** In stagnation, the model repeatedly produces the same wrong code despite correct reasoning (trapped). In divergence, it tries different wrong approaches (confused). These may require different interventions.

---
## 12. Next Experiments

1. **Permission prompt:** Add "You may deviate from the suggested simplification if correctness requires it" to test H2.
2. **LEG-aware retry:** When LEG is detected mid-trajectory, change the retry prompt to "Your reasoning is correct. Focus on translating your analysis into code exactly."
3. **Fresh restart on LEG:** When LEG persists for 2+ attempts, discard context and generate from scratch with only the bug description (test H3).
4. **Run LEG eval on gpt-5-mini:** The current 5-mini data lacks LEG evaluation. Re-run with structured JSON + LEG eval for complete 5-model comparison.
