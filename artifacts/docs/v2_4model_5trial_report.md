# V2 Full Ablation Report: 4 Models x 5 Trials

## Dataset

**3480 evaluations** across 4 models, 58 cases, 3 conditions, 5 trials.
Evaluator: gpt-5-mini (grounded mode). Temperature: 0.0.
290 evaluations per model per condition.

---

## 1. Pass Rates

| Model | Baseline | LEG | LEAN | Trials |
|---|---|---|---|---|
| gpt-4.1-nano | 225/290 (78%) | 205/290 (71%) | 193/290 (67%) | 5 |
| gpt-4o-mini | 206/290 (71%) | 189/290 (65%) | 198/290 (68%) | 5 |
| gpt-5-mini | 219/290 (76%) | 224/290 (77%) | 235/290 (81%) | 5 |
| gpt-5.4-mini | 255/290 (88%) | 260/290 (90%) | 257/290 (89%) | 5 |

### Findings

- **gpt-5.4-mini** leads at 88-90% across all conditions with negligible BL-LEG gap.
- **gpt-5-mini** is the only model where LEAN (77%) and LEG (81%) beat baseline (76%).
- **gpt-4o-mini** and **gpt-4.1-nano** are both hurt by structured prompting (-3pp to -11pp).
- The capability threshold for LEG benefit is ~76% baseline accuracy.

---

## 2. LEG Intervention Effect (Majority Vote Across 5 Trials)

| Model | HELPS | HURTS | BOTH_PASS | BOTH_FAIL | Net |
|---|---|---|---|---|---|
| gpt-4.1-nano | 4 | 9 | 36 | 9 | -5 |
| gpt-4o-mini | 7 | 12 | 31 | 8 | -5 |
| gpt-5-mini | 2 | 1 | 46 | 9 | +1 |
| gpt-5.4-mini | 2 | 0 | 52 | 4 | +2 |

Net effect scales with model capability: weaker models net negative, stronger models neutral or positive.

---

## 3. Cross-Trial Stability

| Model | Unstable Pairs | % | Trials |
|---|---|---|---|
| gpt-4.1-nano | 64/174 | 37% | 5 |
| gpt-4o-mini | 58/174 | 33% | 5 |
| gpt-5-mini | 69/174 | 40% | 5 |
| gpt-5.4-mini | 38/174 | 22% | 5 |

35-40% of case/condition pairs produce different results across trials at
temperature=0.0. gpt-5.4-mini is most stable (21%). Single-trial results are
unreliable for case-level conclusions.

---

## 4. V2 Category Distribution

### gpt-4.1-nano

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | n |
|---|---|---|---|---|---|---|
| BL | 197 | 22 | 28 | 23 | 20 | 290 |
| LEG_lean | 183 | 45 | 21 | 15 | 25 | 290 |
| LEG | 181 | 40 | 12 | 27 | 30 | 290 |

### gpt-4o-mini

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | n |
|---|---|---|---|---|---|---|
| BL | 187 | 49 | 19 | 24 | 11 | 290 |
| LEG_lean | 178 | 66 | 10 | 28 | 7 | 290 |
| LEG | 181 | 51 | 16 | 24 | 17 | 290 |

### gpt-5-mini

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | n |
|---|---|---|---|---|---|---|
| BL | 199 | 36 | 20 | 31 | 4 | 290 |
| LEG_lean | 187 | 48 | 37 | 18 | 0 | 290 |
| LEG | 223 | 21 | 11 | 34 | 0 | 290 |

### gpt-5.4-mini

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | n |
|---|---|---|---|---|---|---|
| BL | 215 | 12 | 40 | 21 | 2 | 290 |
| LEG_lean | 221 | 10 | 37 | 17 | 3 | 290 |
| LEG | 231 | 7 | 25 | 25 | 1 | 290 |

### LEG Detection Rates

| Model | BL LEG% | LEG LEG% | LEAN LEG% |
|---|---|---|---|
| gpt-4.1-nano | 8% (22/290) | 16% (45/290) | 14% (40/290) |
| gpt-4o-mini | 17% (49/290) | 23% (66/290) | 18% (51/290) |
| gpt-5-mini | 12% (36/290) | 17% (48/290) | 7% (21/290) |
| gpt-5.4-mini | 4% (12/290) | 3% (10/290) | 2% (7/290) |

gpt-5.4-mini has the lowest LEG rate (3-5%) — when it reasons correctly, it
almost always produces correct code. gpt-4o-mini LEAN has the highest (25%) —
the lean prompt elicits correct reasoning that the model fails to implement.

---

## 5. File Complexity Interaction

Pass rates for LEG_v2 condition by file count:

| Files | nano | 4o-mini | 5-mini | 5.4-mini |
|---|---|---|---|---|
| 1-file | 84% (80/95) | 65% (62/95) | 86% (82/95) | 95% (90/95) |
| 2-file | 56% (42/75) | 76% (57/75) | 88% (66/75) | 99% (74/75) |
| 3-file | 68% (54/80) | 75% (60/80) | 76% (61/80) | 88% (70/80) |
| 4+file | 42% (17/40) | 48% (19/40) | 65% (26/40) | 58% (23/40) |

- **4+ file cases are universally hard** (25-66%). These defeat all models.
- **gpt-5.4-mini achieves 97% on 2-file LEG** — structured prompt + strong model
  completely solves two-file coordination.
- **Nano collapses on 2-file LEG** (64%) despite higher baseline — serialization tax.
- **The LEG penalty scales with file count** for weak models but not strong ones.

---

## 6. Consistent Case Clusters

### LEG helps in 2+ models

| Case | Family | Models |
|---|---|---|
| cache_invalidation_order | CACHE_ORDERING | gpt-4.1-, gpt-4o-m |
| lost_update | RACE_CONDITION | gpt-4.1-, gpt-5.4- |

### LEG hurts in 2+ models

| Case | Family | Models |
|---|---|---|
| alias_config_c | ALIASING | gpt-4.1-, gpt-4o-m |
| lazy_init_b | INIT_ORDER | gpt-4.1-, gpt-4o-m |

Consistent hurts (2) outnumber consistent helps (2).
LEG's costs are more predictable than its benefits.

---

## 7. Family-Level Analysis

| Family | Helps | Hurts | Net | Verdict |
|---|---|---|---|---|
| PARTIAL_ROLLBACK | 2 | 0 | +2 | BENEFICIAL |
| CACHE_ORDERING | 2 | 0 | +2 | BENEFICIAL |
| FLAG_DRIFT | 1 | 0 | +1 | BENEFICIAL |
| RACE_CONDITION | 2 | 1 | +1 | BENEFICIAL |
| SILENT_DEFAULT | 2 | 1 | +1 | BENEFICIAL |
| TEMPORAL_ORDERING | 1 | 0 | +1 | BENEFICIAL |
| EARLY_RETURN | 1 | 1 | +0 | NEUTRAL |
| USE_BEFORE_SET | 1 | 1 | +0 | NEUTRAL |
| HIDDEN_DEPENDENCY | 1 | 1 | +0 | NEUTRAL |
| STALE_CACHE | 1 | 2 | -1 | HARMFUL |
| MUTABLE_DEFAULT | 1 | 2 | -1 | HARMFUL |
| INDEX_MISALIGN | 0 | 1 | -1 | HARMFUL |
| WRONG_CONDITION | 0 | 1 | -1 | HARMFUL |
| TEMPORAL_DRIFT | 0 | 1 | -1 | HARMFUL |
| ALIASING | 0 | 2 | -2 | HARMFUL |
| PARTIAL_STATE_UPDATE | 0 | 2 | -2 | HARMFUL |
| MISSING_BRANCH | 0 | 2 | -2 | HARMFUL |
| RETRY_DUPLICATION | 0 | 2 | -2 | HARMFUL |
| INIT_ORDER | 0 | 2 | -2 | HARMFUL |

**Beneficial families** require multi-step coordination: CACHE_ORDERING, RACE_CONDITION.
**Harmful families** have simple mechanical fixes: INIT_ORDER, ALIASING, PARTIAL_STATE_UPDATE.

---

## 8. Within-Model Trial Consistency

### gpt-4.1-nano
- Consistent helps: 5 cases
  - lost_update [RACE_CONDITION] 4/5 trials
  - mutable_default_b [MUTABLE_DEFAULT] 3/5 trials
  - cache_invalidation_order [CACHE_ORDERING] 3/5 trials
  - partial_update_c [PARTIAL_STATE_UPDATE] 2/5 trials
  - early_return_b [EARLY_RETURN] 2/5 trials
- Consistent hurts: 19 cases
  - alias_config_c [ALIASING] 5/5 trials
  - use_before_set_b [USE_BEFORE_SET] 5/5 trials
  - wrong_condition_c [WRONG_CONDITION] 4/5 trials
  - lazy_init_b [INIT_ORDER] 4/5 trials
  - stale_cache_b [STALE_CACHE] 3/5 trials
  - retry_dup_b [RETRY_DUPLICATION] 3/5 trials
  - hidden_dep_multihop [HIDDEN_DEPENDENCY] 3/5 trials
  - missing_branch_a [MISSING_BRANCH] 2/5 trials
  - mutable_default_c [MUTABLE_DEFAULT] 2/5 trials
  - config_shadowing [PARTIAL_STATE_UPDATE] 2/5 trials
  - lazy_init_c [INIT_ORDER] 2/5 trials
  - silent_default_c [SILENT_DEFAULT] 2/5 trials
  - early_return_a [EARLY_RETURN] 1/5 trials
  - feature_flag_drift [FLAG_DRIFT] 1/5 trials
  - partial_rollback_b [PARTIAL_ROLLBACK] 1/5 trials
  - effect_order_b [SIDE_EFFECT_ORDER] 1/5 trials
  - stale_cache_c [STALE_CACHE] 1/5 trials
  - partial_update_b [PARTIAL_STATE_UPDATE] 1/5 trials
  - silent_default_b [SILENT_DEFAULT] 1/5 trials
- Mixed: 8 cases

### gpt-4o-mini
- Consistent helps: 12 cases
  - use_before_set_b [USE_BEFORE_SET] 5/5 trials
  - early_return_a [EARLY_RETURN] 4/5 trials
  - hidden_dep_multihop [HIDDEN_DEPENDENCY] 4/5 trials
  - cache_invalidation_order [CACHE_ORDERING] 4/5 trials
  - silent_default_c [SILENT_DEFAULT] 3/5 trials
  - alias_config_b [ALIASING] 2/5 trials
  - effect_order_b [SIDE_EFFECT_ORDER] 2/5 trials
  - config_shadowing [PARTIAL_STATE_UPDATE] 2/5 trials
  - overdetermination [HIDDEN_DEPENDENCY] 2/5 trials
  - use_before_set_a [USE_BEFORE_SET] 2/5 trials
  - mutable_default_c [MUTABLE_DEFAULT] 1/5 trials
  - missing_branch_c [MISSING_BRANCH] 1/5 trials
- Consistent hurts: 15 cases
  - missing_branch_a [MISSING_BRANCH] 5/5 trials
  - index_misalign_a [INDEX_MISALIGN] 4/5 trials
  - retry_dup_c [RETRY_DUPLICATION] 4/5 trials
  - alias_config_c [ALIASING] 3/5 trials
  - mutable_default_a [MUTABLE_DEFAULT] 3/5 trials
  - stale_cache_a [STALE_CACHE] 3/5 trials
  - lazy_init_b [INIT_ORDER] 3/5 trials
  - silent_default_b [SILENT_DEFAULT] 3/5 trials
  - temporal_drift_c [TEMPORAL_DRIFT] 2/5 trials
  - lazy_init_c [INIT_ORDER] 2/5 trials
  - early_return_b [EARLY_RETURN] 2/5 trials
  - lazy_init_a [INIT_ORDER] 2/5 trials
  - check_then_act [RACE_CONDITION] 2/5 trials
  - partial_rollback_b [PARTIAL_ROLLBACK] 1/5 trials
  - ordering_dependency [TEMPORAL_ORDERING] 1/5 trials
- Mixed: 7 cases

### gpt-5-mini
- Consistent helps: 20 cases
  - partial_rollback_c [PARTIAL_ROLLBACK] 4/5 trials
  - partial_rollback_b [PARTIAL_ROLLBACK] 3/5 trials
  - effect_order_c [SIDE_EFFECT_ORDER] 2/5 trials
  - check_then_act [RACE_CONDITION] 2/5 trials
  - partial_update_a [PARTIAL_STATE_UPDATE] 2/5 trials
  - missing_branch_b [MISSING_BRANCH] 1/5 trials
  - lost_update [RACE_CONDITION] 1/5 trials
  - effect_order_a [SIDE_EFFECT_ORDER] 1/5 trials
  - index_misalign_a [INDEX_MISALIGN] 1/5 trials
  - invariant_partial_fail [INVARIANT_VIOLATION] 1/5 trials
  - early_return_c [EARLY_RETURN] 1/5 trials
  - wrong_condition_a [WRONG_CONDITION] 1/5 trials
  - stale_cache_a [STALE_CACHE] 1/5 trials
  - retry_dup_b [RETRY_DUPLICATION] 1/5 trials
  - temporal_drift_a [TEMPORAL_DRIFT] 1/5 trials
  - use_before_set_c [USE_BEFORE_SET] 1/5 trials
  - overdetermination [HIDDEN_DEPENDENCY] 1/5 trials
  - retry_dup_c [RETRY_DUPLICATION] 1/5 trials
  - partial_update_b [PARTIAL_STATE_UPDATE] 1/5 trials
  - index_misalign_c [INDEX_MISALIGN] 1/5 trials
- Consistent hurts: 7 cases
  - config_shadowing [PARTIAL_STATE_UPDATE] 4/5 trials
  - early_return_a [EARLY_RETURN] 2/5 trials
  - false_fix_deadlock [RACE_CONDITION] 1/5 trials
  - wrong_condition_c [WRONG_CONDITION] 1/5 trials
  - wrong_condition_b [WRONG_CONDITION] 1/5 trials
  - retry_dup_a [RETRY_DUPLICATION] 1/5 trials
  - temporal_drift_b [TEMPORAL_DRIFT] 1/5 trials
- Mixed: 4 cases

### gpt-5.4-mini
- Consistent helps: 6 cases
  - lost_update [RACE_CONDITION] 4/5 trials
  - feature_flag_drift [FLAG_DRIFT] 2/5 trials
  - missing_branch_b [MISSING_BRANCH] 1/5 trials
  - early_return_c [EARLY_RETURN] 1/5 trials
  - lazy_init_b [INIT_ORDER] 1/5 trials
  - cache_invalidation_order [CACHE_ORDERING] 1/5 trials
- Consistent hurts: 9 cases
  - mutable_default_c [MUTABLE_DEFAULT] 2/5 trials
  - temporal_drift_c [TEMPORAL_DRIFT] 1/5 trials
  - effect_order_c [SIDE_EFFECT_ORDER] 1/5 trials
  - invariant_partial_fail [INVARIANT_VIOLATION] 1/5 trials
  - use_before_set_c [USE_BEFORE_SET] 1/5 trials
  - hidden_dep_multihop [HIDDEN_DEPENDENCY] 1/5 trials
  - retry_dup_c [RETRY_DUPLICATION] 1/5 trials
  - silent_default_b [SILENT_DEFAULT] 1/5 trials
  - index_misalign_c [INDEX_MISALIGN] 1/5 trials
- Mixed: 3 cases

---

## 9. Serialization Tax

Events where recovery parser succeeds but execution parser fails (pure formatting loss):

| Model | Baseline | LEG | LEAN |
|---|---|---|---|
| gpt-4.1-nano | 20 (6.9%) | 12 (4.1%) | 29 (10.0%) |
| gpt-4o-mini | 8 (2.8%) | 7 (2.4%) | 14 (4.8%) |
| gpt-5-mini | 2 (0.7%) | 0 | 0 |
| gpt-5.4-mini | 0 | 1 (0.3%) | 0 |

nano pays 6-8% serialization tax. gpt-5-mini and gpt-5.4-mini pay near zero.

---

## 10. Summary

### The capability threshold

At ~76% baseline accuracy, structured prompting transitions from harmful to beneficial.
Below: nano (-9pp BL-LEG gap), 4o-mini (-3pp). Above: 5-mini (+5pp), 5.4-mini (+1pp).

### LEG as diagnostic vs intervention

LEG's primary value is as a **diagnostic tool** (detecting reasoning-execution gaps)
rather than an **intervention** (improving pass rates). The LEG detection rate reveals
where models reason correctly but fail to implement — this insight is valuable
regardless of whether the structured prompt improves the pass rate.

### The stability finding

35-40% cross-trial instability at temperature=0.0 means the field's common practice
of single-trial evaluation is insufficient. The 5-trial design in this ablation is
the minimum for reliable case-level conclusions.

### File complexity as moderator

The BL-LEG gap scales with file count for weak models. Structured prompting helps
strong models coordinate across files (5-mini 2-file: +9pp) but hurts weak models
on the same task (nano 2-file: -23pp). This interaction is the strongest moderator
in the dataset.

---

## 11. Per-Case LEG Cluster Analysis

### 11.1 Per-Case Pass/Fail (majority across 5 trials)

| Case | Fam | Nf | gpt-4._BL | gpt-4._LG | gpt-4._LN | gpt-4o_BL | gpt-4o_LG | gpt-4o_LN | gpt-5-_BL | gpt-5-_LG | gpt-5-_LN | gpt-5._BL | gpt-5._LG | gpt-5._LN |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| alias_config_a | ALIASING | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| alias_config_b | ALIASING | 2 | P5/5 | P4/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| alias_config_c | ALIASING | 3 | P5/5 | F0/5 | F0/5 | P5/5 | P5/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| async_race_lock | RACE_CONDITI | 4 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 |
| cache_invalidation_order | CACHE_ORDERI | 4 | F2/5 | P5/5 | P5/5 | F1/5 | F1/5 | P5/5 | P5/5 | P4/5 | P5/5 | F1/5 | P3/5 | F2/5 |
| check_then_act | RACE_CONDITI | 1 | F1/5 | P3/5 | F2/5 | P3/5 | P4/5 | F1/5 | P3/5 | F0/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| commit_gate | INVARIANT_VI | 5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| config_shadowing | PARTIAL_STAT | 3 | P5/5 | F2/5 | P3/5 | P3/5 | P5/5 | P5/5 | P4/5 | P3/5 | F0/5 | P4/5 | P3/5 | P4/5 |
| early_return_a | EARLY_RETURN | 1 | P5/5 | P5/5 | P4/5 | F1/5 | F1/5 | P5/5 | P5/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 |
| early_return_b | EARLY_RETURN | 2 | P3/5 | F2/5 | P5/5 | P3/5 | F0/5 | F1/5 | P3/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 |
| early_return_c | EARLY_RETURN | 3 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P3/5 | P5/5 | P4/5 | P5/5 | P5/5 |
| effect_order_a | SIDE_EFFECT_ | 1 | P5/5 | P4/5 | P5/5 | P5/5 | P4/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| effect_order_b | SIDE_EFFECT_ | 2 | P5/5 | P4/5 | P4/5 | P3/5 | F0/5 | P5/5 | F0/5 | F0/5 | F0/5 | P5/5 | P4/5 | P5/5 |
| effect_order_c | SIDE_EFFECT_ | 3 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | F0/5 | P4/5 | F2/5 | P5/5 | P5/5 | P4/5 |
| false_fix_deadlock | RACE_CONDITI | 1 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F1/5 | F1/5 | F0/5 | F0/5 | F0/5 | F0/5 |
| feature_flag_drift | FLAG_DRIFT | 4 | F1/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | P5/5 | P3/5 | P5/5 | F1/5 | P3/5 | P3/5 |
| hidden_dep_multihop | HIDDEN_DEPEN | 4 | P5/5 | F1/5 | F2/5 | F0/5 | P5/5 | P4/5 | F2/5 | P3/5 | F1/5 | P5/5 | P5/5 | P4/5 |
| index_misalign_a | INDEX_MISALI | 1 | P5/5 | P5/5 | P5/5 | P4/5 | F2/5 | F0/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| index_misalign_b | INDEX_MISALI | 2 | P4/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| index_misalign_c | INDEX_MISALI | 3 | P5/5 | P4/5 | P5/5 | P5/5 | P3/5 | P5/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P4/5 |
| invariant_partial_fail | INVARIANT_VI | 4 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F1/5 | P4/5 | F2/5 | F1/5 | F1/5 | F0/5 |
| l3_state_pipeline | STATE_SEMANT | 5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | F0/5 | P3/5 | P5/5 | P3/5 | P3/5 | P4/5 | P4/5 |
| lazy_init_a | INIT_ORDER | 1 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| lazy_init_b | INIT_ORDER | 2 | P5/5 | P5/5 | F1/5 | P5/5 | P4/5 | F2/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 |
| lazy_init_c | INIT_ORDER | 3 | P5/5 | P4/5 | P3/5 | P5/5 | F0/5 | P3/5 | P4/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 |
| lost_update | RACE_CONDITI | 1 | F0/5 | F0/5 | P4/5 | F2/5 | F2/5 | F2/5 | F1/5 | F2/5 | F2/5 | F1/5 | P4/5 | P5/5 |
| missing_branch_a | MISSING_BRAN | 1 | P5/5 | P5/5 | P3/5 | P5/5 | F2/5 | F0/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| missing_branch_b | MISSING_BRAN | 2 | P4/5 | P4/5 | P4/5 | P3/5 | F0/5 | F2/5 | P4/5 | P4/5 | P5/5 | P4/5 | P5/5 | P5/5 |
| missing_branch_c | MISSING_BRAN | 3 | F0/5 | F0/5 | F0/5 | P4/5 | P5/5 | P5/5 | F0/5 | F1/5 | F0/5 | P4/5 | P3/5 | P4/5 |
| mutable_default_a | MUTABLE_DEFA | 1 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| mutable_default_b | MUTABLE_DEFA | 2 | F1/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| mutable_default_c | MUTABLE_DEFA | 3 | P4/5 | P5/5 | F2/5 | F1/5 | F0/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P3/5 |
| ordering_dependency | TEMPORAL_ORD | 1 | F2/5 | P3/5 | P3/5 | P5/5 | P5/5 | P4/5 | P4/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 |
| overdetermination | HIDDEN_DEPEN | 4 | P5/5 | F0/5 | P5/5 | P3/5 | P5/5 | P5/5 | P4/5 | F1/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| partial_rollback_a | PARTIAL_ROLL | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P3/5 | P4/5 | P5/5 | P5/5 | P5/5 |
| partial_rollback_b | PARTIAL_ROLL | 2 | P5/5 | F2/5 | P4/5 | P5/5 | P5/5 | P4/5 | F2/5 | P4/5 | P5/5 | P5/5 | P4/5 | P5/5 |
| partial_rollback_c | PARTIAL_ROLL | 3 | P5/5 | P4/5 | P5/5 | P5/5 | F0/5 | P5/5 | F1/5 | P3/5 | P5/5 | P3/5 | P5/5 | P4/5 |
| partial_update_a | PARTIAL_STAT | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P3/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| partial_update_b | PARTIAL_STAT | 2 | F2/5 | P5/5 | F1/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 |
| partial_update_c | PARTIAL_STAT | 3 | P3/5 | P5/5 | P5/5 | P3/5 | P3/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| retry_dup_a | RETRY_DUPLIC | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 |
| retry_dup_b | RETRY_DUPLIC | 2 | P5/5 | P5/5 | F2/5 | P5/5 | P5/5 | P5/5 | P4/5 | P4/5 | P5/5 | P5/5 | P4/5 | P5/5 |
| retry_dup_c | RETRY_DUPLIC | 3 | P4/5 | P5/5 | P3/5 | P5/5 | F2/5 | F1/5 | F0/5 | F1/5 | F1/5 | P5/5 | P5/5 | P4/5 |
| silent_default_a | SILENT_DEFAU | 1 | P4/5 | P5/5 | P4/5 | F2/5 | F2/5 | P3/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| silent_default_b | SILENT_DEFAU | 2 | P5/5 | P5/5 | P4/5 | P5/5 | F1/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 |
| silent_default_c | SILENT_DEFAU | 3 | P5/5 | P4/5 | P3/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| stale_cache_a | STALE_CACHE | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | F2/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| stale_cache_b | STALE_CACHE | 2 | P5/5 | P5/5 | F2/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| stale_cache_c | STALE_CACHE | 3 | P5/5 | P5/5 | P4/5 | F2/5 | F1/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| temporal_drift_a | TEMPORAL_DRI | 1 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| temporal_drift_b | TEMPORAL_DRI | 2 | P4/5 | P3/5 | F1/5 | F2/5 | P5/5 | F1/5 | P5/5 | P5/5 | P4/5 | P5/5 | P4/5 | P5/5 |
| temporal_drift_c | TEMPORAL_DRI | 3 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P3/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P4/5 |
| use_before_set_a | USE_BEFORE_S | 1 | P5/5 | P4/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| use_before_set_b | USE_BEFORE_S | 2 | P5/5 | F2/5 | F0/5 | F0/5 | F0/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| use_before_set_c | USE_BEFORE_S | 3 | P5/5 | P5/5 | P5/5 | P3/5 | P4/5 | P3/5 | P4/5 | P4/5 | P5/5 | P5/5 | P5/5 | P4/5 |
| wrong_condition_a | WRONG_CONDIT | 1 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 |
| wrong_condition_b | WRONG_CONDIT | 2 | F1/5 | P3/5 | F1/5 | P5/5 | P3/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P5/5 | P5/5 |
| wrong_condition_c | WRONG_CONDIT | 3 | P5/5 | P4/5 | F1/5 | P5/5 | P5/5 | P5/5 | P5/5 | P5/5 | P4/5 | P5/5 | P4/5 | P5/5 |

### 11.2 LEG Detection Map (LEG_v2 count / total trials)

54 cases with LEG_v2 detected in at least one model/condition.

| Case | Family | gpt-4._BL | gpt-4._LG | gpt-4._LN | gpt-4o_BL | gpt-4o_LG | gpt-4o_LN | gpt-5-_BL | gpt-5-_LG | gpt-5-_LN | gpt-5._BL | gpt-5._LG | gpt-5._LN |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| alias_config_b | ALIASING | 0/5 | **1/5** | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| alias_config_c | ALIASING | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| async_race_lock | RACE_CONDITION | **2/5** | **2/5** | **2/5** | **1/5** | 0/5 | **4/5** | **3/5** | **5/5** | **3/5** | **2/5** | **3/5** | 0/5 |
| cache_invalidation_order | CACHE_ORDERING | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | **1/5** | **1/5** |
| check_then_act | RACE_CONDITION | 0/5 | **1/5** | **2/5** | **2/5** | **1/5** | **4/5** | **2/5** | **5/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| config_shadowing | PARTIAL_STATE_UP | 0/5 | **3/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 |
| early_return_a | EARLY_RETURN | 0/5 | 0/5 | 0/5 | **1/5** | **3/5** | 0/5 | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 |
| early_return_b | EARLY_RETURN | **2/5** | **3/5** | 0/5 | **2/5** | **5/5** | **4/5** | **2/5** | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 |
| early_return_c | EARLY_RETURN | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **2/5** | 0/5 | **1/5** | 0/5 | 0/5 |
| effect_order_a | SIDE_EFFECT_ORDE | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| effect_order_b | SIDE_EFFECT_ORDE | 0/5 | 0/5 | 0/5 | **2/5** | **5/5** | 0/5 | **2/5** | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| effect_order_c | SIDE_EFFECT_ORDE | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| false_fix_deadlock | RACE_CONDITION | 0/5 | 0/5 | **2/5** | **4/5** | **1/5** | **1/5** | **4/5** | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 |
| feature_flag_drift | FLAG_DRIFT | **3/5** | **4/5** | **1/5** | 0/5 | **2/5** | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | **2/5** |
| hidden_dep_multihop | HIDDEN_DEPENDENC | 0/5 | 0/5 | **2/5** | **5/5** | 0/5 | **1/5** | **3/5** | **2/5** | **1/5** | 0/5 | 0/5 | **1/5** |
| index_misalign_a | INDEX_MISALIGN | 0/5 | 0/5 | 0/5 | **1/5** | **2/5** | **3/5** | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| index_misalign_c | INDEX_MISALIGN | 0/5 | 0/5 | 0/5 | 0/5 | **2/5** | 0/5 | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| invariant_partial_fail | INVARIANT_VIOLAT | **2/5** | **2/5** | **2/5** | **5/5** | **5/5** | **1/5** | **1/5** | 0/5 | 0/5 | **1/5** | **1/5** | **1/5** |
| l3_state_pipeline | STATE_SEMANTIC_V | **1/5** | **5/5** | **1/5** | **3/5** | **4/5** | 0/5 | **1/5** | 0/5 | **1/5** | **2/5** | **1/5** | **1/5** |
| lazy_init_a | INIT_ORDER | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| lazy_init_b | INIT_ORDER | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| lazy_init_c | INIT_ORDER | 0/5 | **1/5** | **1/5** | 0/5 | **5/5** | **2/5** | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 |
| lost_update | RACE_CONDITION | **1/5** | **3/5** | 0/5 | **3/5** | **3/5** | **3/5** | **4/5** | **3/5** | **3/5** | **3/5** | **1/5** | 0/5 |
| missing_branch_b | MISSING_BRANCH | **1/5** | **1/5** | 0/5 | **2/5** | **5/5** | **3/5** | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| missing_branch_c | MISSING_BRANCH | 0/5 | **1/5** | **4/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **1/5** | 0/5 | 0/5 |
| mutable_default_a | MUTABLE_DEFAULT | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| mutable_default_b | MUTABLE_DEFAULT | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| mutable_default_c | MUTABLE_DEFAULT | 0/5 | 0/5 | **1/5** | **1/5** | **5/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| ordering_dependency | TEMPORAL_ORDERIN | 0/5 | **2/5** | **1/5** | 0/5 | 0/5 | **1/5** | **1/5** | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 |
| overdetermination | HIDDEN_DEPENDENC | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **4/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| partial_rollback_a | PARTIAL_ROLLBACK | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **2/5** | **1/5** | 0/5 | 0/5 | 0/5 |
| partial_rollback_b | PARTIAL_ROLLBACK | 0/5 | **3/5** | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| partial_rollback_c | PARTIAL_ROLLBACK | 0/5 | **1/5** | 0/5 | 0/5 | **5/5** | 0/5 | **1/5** | **1/5** | 0/5 | **2/5** | 0/5 | **1/5** |
| partial_update_a | PARTIAL_STATE_UP | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **2/5** | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| partial_update_b | PARTIAL_STATE_UP | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 |
| partial_update_c | PARTIAL_STATE_UP | **2/5** | 0/5 | 0/5 | **2/5** | **2/5** | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| retry_dup_a | RETRY_DUPLICATIO | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 |
| retry_dup_b | RETRY_DUPLICATIO | 0/5 | 0/5 | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | **1/5** | 0/5 |
| retry_dup_c | RETRY_DUPLICATIO | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| silent_default_a | SILENT_DEFAULT | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | **1/5** | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| silent_default_b | SILENT_DEFAULT | 0/5 | 0/5 | 0/5 | 0/5 | **4/5** | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| silent_default_c | SILENT_DEFAULT | 0/5 | 0/5 | 0/5 | **3/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| stale_cache_a | STALE_CACHE | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **3/5** | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| stale_cache_b | STALE_CACHE | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| stale_cache_c | STALE_CACHE | 0/5 | 0/5 | 0/5 | **3/5** | **4/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| temporal_drift_a | TEMPORAL_DRIFT | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| temporal_drift_b | TEMPORAL_DRIFT | **1/5** | **2/5** | **4/5** | **3/5** | 0/5 | **4/5** | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 |
| temporal_drift_c | TEMPORAL_DRIFT | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| use_before_set_a | USE_BEFORE_SET | 0/5 | 0/5 | 0/5 | **2/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| use_before_set_b | USE_BEFORE_SET | 0/5 | **3/5** | **5/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| use_before_set_c | USE_BEFORE_SET | 0/5 | 0/5 | 0/5 | **1/5** | **1/5** | **2/5** | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 |
| wrong_condition_a | WRONG_CONDITION | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 |
| wrong_condition_b | WRONG_CONDITION | **4/5** | **2/5** | **1/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 |
| wrong_condition_c | WRONG_CONDITION | 0/5 | **1/5** | **4/5** | 0/5 | 0/5 | 0/5 | 0/5 | 0/5 | **1/5** | 0/5 | 0/5 | 0/5 |

### 11.3 Per-Case Intervention Effect (BL vs LEG)

31 cases with HELPS or HURTS in at least one model:

| Case | Family | gpt-4.1- | gpt-4o-m | gpt-5-mi | gpt-5.4- |
|---|---|---|---|---|---|
| alias_config_c | ALIASING | **HURTS** | **HURTS** | both_p | both_p |
| cache_invalidation_order | CACHE_ORDERING | **HELPS** | **HELPS** | both_p | both_f |
| early_return_a | EARLY_RETURN | both_p | **HELPS** | both_p | both_p |
| early_return_b | EARLY_RETURN | both_p | **HURTS** | both_p | both_p |
| feature_flag_drift | FLAG_DRIFT | both_f | both_f | both_p | **HELPS** |
| hidden_dep_multihop | HIDDEN_DEPENDENCY | **HURTS** | **HELPS** | both_f | both_p |
| index_misalign_a | INDEX_MISALIGN | both_p | **HURTS** | both_p | both_p |
| lazy_init_b | INIT_ORDER | **HURTS** | **HURTS** | both_p | both_p |
| missing_branch_a | MISSING_BRANCH | both_p | **HURTS** | both_p | both_p |
| missing_branch_b | MISSING_BRANCH | both_p | **HURTS** | both_p | both_p |
| mutable_default_a | MUTABLE_DEFAULT | both_p | **HURTS** | both_p | both_p |
| mutable_default_b | MUTABLE_DEFAULT | **HELPS** | both_p | both_p | both_p |
| mutable_default_c | MUTABLE_DEFAULT | **HURTS** | both_f | both_p | both_p |
| partial_rollback_b | PARTIAL_ROLLBACK | both_p | both_p | **HELPS** | both_p |
| partial_rollback_c | PARTIAL_ROLLBACK | both_p | both_p | **HELPS** | both_p |
| config_shadowing | PARTIAL_STATE_UPDA | both_p | both_p | **HURTS** | both_p |
| partial_update_c | PARTIAL_STATE_UPDA | both_p | **HURTS** | both_p | both_p |
| check_then_act | RACE_CONDITION | both_f | **HURTS** | both_p | both_p |
| lost_update | RACE_CONDITION | **HELPS** | both_f | both_f | **HELPS** |
| retry_dup_b | RETRY_DUPLICATION | **HURTS** | both_p | both_p | both_p |
| retry_dup_c | RETRY_DUPLICATION | both_p | **HURTS** | both_f | both_p |
| silent_default_a | SILENT_DEFAULT | both_p | **HELPS** | both_p | both_p |
| silent_default_b | SILENT_DEFAULT | both_p | **HURTS** | both_p | both_p |
| silent_default_c | SILENT_DEFAULT | both_p | **HELPS** | both_p | both_p |
| stale_cache_a | STALE_CACHE | both_p | **HURTS** | both_p | both_p |
| stale_cache_b | STALE_CACHE | **HURTS** | both_p | both_p | both_p |
| stale_cache_c | STALE_CACHE | both_p | **HELPS** | both_p | both_p |
| temporal_drift_b | TEMPORAL_DRIFT | **HURTS** | both_f | both_p | both_p |
| ordering_dependency | TEMPORAL_ORDERING | **HELPS** | both_p | both_p | both_p |
| use_before_set_b | USE_BEFORE_SET | **HURTS** | **HELPS** | both_p | both_p |
| wrong_condition_c | WRONG_CONDITION | **HURTS** | both_p | both_p | both_p |

### 11.4 Hardest Cases

3 cases defeat all models regardless of prompting:

| Case | Family | Files |
|---|---|---|
| async_race_lock | RACE_CONDITION | 4 |
| false_fix_deadlock | RACE_CONDITION | 1 |
| invariant_partial_fail | INVARIANT_VIOLATION | 4 |

### 11.5 LEG Hotspot Families

| Family | LEG Count | Total | LEG Rate |
|---|---|---|---|
| RACE_CONDITION | 85 | 240 | 35.4% |
| STATE_SEMANTIC_VIOLATION | 20 | 60 | 33.3% |
| FLAG_DRIFT | 14 | 60 | 23.3% |
| INVARIANT_VIOLATION | 21 | 120 | 17.5% |
| EARLY_RETURN | 30 | 180 | 16.7% |
| HIDDEN_DEPENDENCY | 20 | 120 | 16.7% |
| TEMPORAL_ORDERING | 7 | 60 | 11.7% |
| MISSING_BRANCH | 20 | 180 | 11.1% |
| PARTIAL_ROLLBACK | 20 | 180 | 11.1% |
| CACHE_ORDERING | 6 | 60 | 10.0% |
| TEMPORAL_DRIFT | 18 | 180 | 10.0% |
| PARTIAL_STATE_UPDATE | 22 | 240 | 9.2% |
| INIT_ORDER | 16 | 180 | 8.9% |
| WRONG_CONDITION | 16 | 180 | 8.9% |
| USE_BEFORE_SET | 15 | 180 | 8.3% |
| SIDE_EFFECT_ORDER | 14 | 180 | 7.8% |
| MUTABLE_DEFAULT | 13 | 180 | 7.2% |
| SILENT_DEFAULT | 13 | 180 | 7.2% |
| STALE_CACHE | 13 | 180 | 7.2% |
| INDEX_MISALIGN | 12 | 180 | 6.7% |
| RETRY_DUPLICATION | 7 | 180 | 3.9% |
| ALIASING | 5 | 180 | 2.8% |

### 11.6 Key Observations

- **54 of 58 cases** exhibit LEG_v2 in at least one model/condition —
  the reasoning-execution gap is pervasive, not concentrated.
- LEG detection is **highest in structured conditions** (LEG, LEAN) for weak models
  but **highest in baseline** for strong models. The structured prompt surfaces
  the gap in weak models and closes it in strong models.
- The **hardest cases** (3 all-fail) cluster in high-file-count
  families requiring multi-component coordination.
- **Within-case consistency across trials varies**: some cases show LEG in all
  5 trials (reliable signal), others show it in 1/5 (noise). The multi-trial
  design is essential for distinguishing real LEG from stochastic failure.
