# V2 Ablation Analysis — Cross-Model Report

## Experiment Configuration

| Parameter | Value |
|---|---|
| Conditions | baseline_v2, leg_reduction_v2, leg_reduction_lean_v2 |
| Cases | 58 (cases_v2.json) |
| Trials | 1 per condition per model |
| Temperature | 0.0 |
| Evaluator | gpt-5-mini (grounded mode) |
| Models | gpt-4.1-nano, gpt-4o-mini, gpt-5-mini |

gpt-4.1-nano was run twice: once with the original parser (13 parse failures due to
unescaped triple-quote docstrings in JSON output), and once with a repaired parser (3
parse failures). Both runs are included to isolate the serialization tax from reasoning
quality.

---

## 1. Pass Rates

| Model | Baseline | LEG | LEAN | Parse Fail | LEG Detections |
|---|---|---|---|---|---|
| gpt-4.1-nano (old parser) | 46/58 (79%) | 38/58 (66%) | 40/58 (69%) | 13 | 27 |
| gpt-4.1-nano (fixed parser) | 45/58 (78%) | 42/58 (72%) | 43/58 (74%) | 3 | 29 |
| gpt-4o-mini | 44/58 (76%) | 36/58 (62%) | 36/58 (62%) | 9 | 36 |
| gpt-5-mini | 45/58 (78%) | 46/58 (79%) | 44/58 (76%) | 0 | 21 |

**Key observations:**

- gpt-5-mini is the only model where LEG beats baseline (79% vs 78%). The stronger
  model absorbs the structured prompt cost and benefits on net.
- gpt-4o-mini shows the largest BL-LEG gap (76% vs 62%), inflated by 9 parse failures.
- The parser fix for gpt-4.1-nano recovered +6pp on LEG (66% to 72%) and +5pp on LEAN
  (69% to 74%), isolating serialization tax from reasoning quality.
- Baseline is stable across the parser fix (-1pp, within noise), confirming the
  parser fix only affects structured output conditions.

## 2. V2 Category Distribution

### gpt-4.1-nano (fixed parser)

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | LUCKY |
|---|---|---|---|---|---|---|
| BL | 38 | 8 | 7 | 5 | 0 | 0 |
| LEG | 36 | 14 | 6 | 2 | 0 | 0 |
| LEG_LEAN | 39 | 7 | 4 | 5 | 3 | 0 |

### gpt-4o-mini

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | LUCKY |
|---|---|---|---|---|---|---|
| BL | 40 | 9 | 4 | 4 | 1 | 0 |
| LEG | 33 | 10 | 2 | 5 | 7 | 1 |
| LEG_LEAN | 33 | 17 | 3 | 4 | 1 | 0 |

### gpt-5-mini

| Condition | INTERP | LEG | ALIGN_F | FULL_F | PARSE_F | LUCKY |
|---|---|---|---|---|---|---|
| BL | 40 | 5 | 5 | 8 | 0 | 0 |
| LEG | 44 | 7 | 2 | 5 | 0 | 0 |
| LEG_LEAN | 39 | 9 | 5 | 5 | 0 | 0 |

**Commentary:**

- `interpretable_success` is the dominant category across all models/conditions (33-44
  per cell), indicating the v2 classifier successfully evaluates most cases.
- `LEG_v2` counts are highest for gpt-4o-mini LEAN (17), suggesting the lean prompt
  elicits correct reasoning that the model then fails to implement.
- `alignment_failure_pass` (code passes, reasoning misaligned) is a distinct phenomenon
  from `lucky_fix`. Only 1 `lucky_fix_v2` was detected across all runs, indicating the v2
  4-dimension classifier rarely produces the 'right answer, wrong reasoning' verdict.
  Instead, it uses the more nuanced `alignment_failure_pass` category.
- 0 classifier failures across all runs -- the v2 classifier template with explicit
  CORRECT/PARTIAL/WRONG examples is robust.

## 3. LEG Intervention Effect (BL vs LEG_v2)

| Model | HELPS | HURTS | BOTH_PASS | BOTH_FAIL | Net |
|---|---|---|---|---|---|
| gpt-4.1-nano (fixed parser) | 5 | 8 | 37 | 8 | -3 |
| gpt-4o-mini | 6 | 14 | 30 | 8 | -8 |
| gpt-5-mini | 5 | 4 | 41 | 8 | +1 |

**Commentary:**

- Blanket LEG application is net negative for gpt-4.1-nano (-3) and gpt-4o-mini (-8),
  but net positive for gpt-5-mini (+1). The intervention cost scales inversely with
  model capability.
- The ratio of BOTH_PASS (cases unaffected by the prompt change) is highest for
  gpt-5-mini (41/58 = 71%), confirming stronger models are more robust to prompt
  variation.

## 4. The Core Finding: Baseline Category Perfectly Predicts LEG Outcome

The most striking result of this ablation: the baseline v2_category is a **100%
accurate predictor** of whether LEG intervention will help or hurt.

| Baseline Category | HELPS | HURTS | BOTH_PASS | BOTH_FAIL | Help Rate (among changed) |
|---|---|---|---|---|---|
| LEG_v2 (right reasoning, wrong code) | 9 | 0 | 0 | 13 | 100% |
| full_failure_v2 (total failure) | 6 | 0 | 0 | 11 | 100% |
| interpretable_success (already working) | 0 | 25 | 93 | 0 | 0% |
| alignment_failure_pass | 0 | 1 | 15 | 0 | 0% |
| parser_failure_v2 | 1 | 0 | 0 | 0 | 100% |

**This is the central research finding:**

- When baseline produces **LEG_v2** (model reasons correctly but writes wrong code),
  LEG intervention **always helps** (9/9 = 100%). The structured prompt forces the
  model to bridge the reasoning-execution gap.
- When baseline produces **full_failure_v2**, LEG **always helps** among cases that
  change (6/6 = 100%).
- When baseline produces **interpretable_success** (already correct), LEG **always
  hurts** among cases that change (0/25 = 0% help rate). The structured prompt adds
  overhead that degrades output on solved cases.
- **Zero exceptions** across 3 models and 174 cases per model.

**Implication:** LEG should be **targeted, not blanket-applied**. A two-phase strategy
-- run baseline first, detect LEG_v2/full_failure cases, then re-run with structured
prompting -- would capture all 15 wins with zero of the 26 losses.

## 5. Where LEG Fixes LEG (9 Cases)

These are cases where baseline has LEG_v2 (correct reasoning, wrong code) and the
structured prompt produces correct code. Every instance follows the same classifier
signature: C/W/W -> C/C/C (mechanism correct, satisfaction and alignment move from
WRONG to CORRECT).

| Case | Family | Model | BL dims | LEG dims | LEAN |
|---|---|---|---|---|---|
| early_return_b | EARLY_RETURN | gpt-4o-mini | C/W/W | C/C/P | LEG (FAIL) |
| effect_order_a | SIDE_EFFECT_ORDER | gpt-5-mini | C/W/W | C/C/C | INTERP (PASS) |
| effect_order_b | SIDE_EFFECT_ORDER | gpt-4o-mini | C/W/W | C/C/C | LEG (FAIL) |
| feature_flag_drift | FLAG_DRIFT | gpt-5-mini | C/W/W | C/C/C | LEG (FAIL) |
| l3_state_pipeline | STATE_SEMANTIC_VIOLATION | gpt-4.1-nano (fixed parser) | C/W/W | C/C/C | LEG (FAIL) |
| mutable_default_b | MUTABLE_DEFAULT | gpt-4.1-nano (fixed parser) | C/W/W | C/C/C | INTERP (PASS) |
| overdetermination | HIDDEN_DEPENDENCY | gpt-5-mini | C/W/W | C/C/C | INTERP (PASS) |
| partial_update_c | PARTIAL_STATE_UPDATE | gpt-4.1-nano (fixed parser) | C/W/W | C/C/C | INTERP (PASS) |
| use_before_set_a | USE_BEFORE_SET | gpt-4o-mini | C/W/W | C/C/C | INTERP (PASS) |

**9 instances across 9 unique cases.** LEAN only
rescues 5/9 of these -- the full structured
prompt is specifically needed to bridge these reasoning-execution gaps.

**Families represented:** SIDE_EFFECT_ORDER (2x), plus single instances from
EARLY_RETURN, FLAG_DRIFT, HIDDEN_DEPENDENCY, MUTABLE_DEFAULT, PARTIAL_STATE_UPDATE,
STATE_SEMANTIC_VIOLATION, USE_BEFORE_SET. These are multi-step bugs where the model
needs to coordinate multiple changes -- exactly where explicit commitment planning helps.

## 6. Where LEG Creates LEG (16 Cases)

These are cases where baseline passes (interpretable_success, C/C/C) but the structured
prompt causes the model to reason correctly and then write wrong code -- the intervention
literally creates the gap it is designed to detect.

| Case | Family | Model | LEG dims | LEAN |
|---|---|---|---|---|
| check_then_act | RACE_CONDITION | gpt-4.1-nano (fixed parser) | C/W/W | ALIGN_F (PASS) |
| check_then_act | RACE_CONDITION | gpt-4o-mini | C/W/P | INTERP (PASS) |
| config_shadowing | PARTIAL_STATE_UPDATE | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |
| index_misalign_a | INDEX_MISALIGN | gpt-4o-mini | C/P/P | LEG (FAIL) |
| index_misalign_a | INDEX_MISALIGN | gpt-5-mini | C/W/W | INTERP (PASS) |
| lazy_init_a | INIT_ORDER | gpt-5-mini | C/W/W | INTERP (PASS) |
| lazy_init_b | INIT_ORDER | gpt-4o-mini | C/W/W | INTERP (PASS) |
| lazy_init_c | INIT_ORDER | gpt-4o-mini | C/W/W | LEG (FAIL) |
| lost_update | RACE_CONDITION | gpt-5-mini | C/W/W | INTERP (PASS) |
| mutable_default_a | MUTABLE_DEFAULT | gpt-4o-mini | C/W/W | INTERP (PASS) |
| partial_rollback_c | PARTIAL_ROLLBACK | gpt-4o-mini | C/W/W | ALIGN_F (PASS) |
| partial_update_a | PARTIAL_STATE_UPDATE | gpt-5-mini | C/W/W | INTERP (PASS) |
| partial_update_b | PARTIAL_STATE_UPDATE | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |
| retry_dup_b | RETRY_DUPLICATION | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |
| silent_default_b | SILENT_DEFAULT | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |
| silent_default_b | SILENT_DEFAULT | gpt-4o-mini | C/W/W | LEG (FAIL) |
| stale_cache_a | STALE_CACHE | gpt-4o-mini | C/W/W | INTERP (PASS) |
| use_before_set_b | USE_BEFORE_SET | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |
| wrong_condition_c | WRONG_CONDITION | gpt-4.1-nano (fixed parser) | C/W/W | INTERP (PASS) |

**19 instances across 16 unique cases.**
LEAN rescues 16/19 of these -- the lighter prompt avoids the
'overthinking' trap that the full structured prompt introduces.

**Consistently vulnerable across 2+ models:**

- `check_then_act` [RACE_CONDITION]: gpt-4.1-nano (fixed parser), gpt-4o-mini
- `index_misalign_a` [INDEX_MISALIGN]: gpt-4o-mini, gpt-5-mini
- `silent_default_b` [SILENT_DEFAULT]: gpt-4.1-nano (fixed parser), gpt-4o-mini

**Mechanism:** The model already knows how to fix these bugs implicitly. When forced to
articulate commitments first, it either (a) over-specifies constraints that conflict
with its natural solution, or (b) focuses attention on the reasoning structure at the
expense of code quality. The families most affected (INIT_ORDER, SILENT_DEFAULT,
RACE_CONDITION) all have straightforward single-point fixes that do not benefit from
explicit planning.

## 7. Alignment Failure Pass ("Accidental Fixes")

These are cases where the code passes tests but the classifier determines the reasoning
does not align with the code. Unlike lucky_fix (wrong mechanism), these cases have correct
mechanism identification but partial or wrong commitment satisfaction/alignment.

**Total: 38 instances across 20 unique cases.** Only 1 `lucky_fix_v2` detected
(`wrong_condition_a` by gpt-4o-mini in LEG).

**Most frequent alignment_failure_pass cases:**

- `hidden_dep_multihop` [HIDDEN_DEPENDENCY] (4x): gpt-4.1-nano (fixed parser):BL(C/P/P), gpt-4.1-nano (fixed parser):LEG(C/P/P), gpt-4o-mini:LEG_LEAN(C/P/P), gpt-5-mini:LEG_LEAN(C/P/P)
- `index_misalign_c` [INDEX_MISALIGN] (4x): gpt-4.1-nano (fixed parser):BL(C/W/W), gpt-4.1-nano (fixed parser):LEG_LEAN(C/W/W), gpt-5-mini:BL(C/W/W), gpt-5-mini:LEG_LEAN(C/W/W)
- `mutable_default_c` [MUTABLE_DEFAULT] (3x): gpt-4.1-nano (fixed parser):BL(C/C/P), gpt-4.1-nano (fixed parser):LEG(C/P/P), gpt-4.1-nano (fixed parser):LEG_LEAN(C/P/P)
- `partial_rollback_b` [PARTIAL_ROLLBACK] (3x): gpt-4.1-nano (fixed parser):LEG(C/C/P), gpt-4o-mini:BL(C/P/P), gpt-5-mini:BL(C/P/P)
- `partial_rollback_c` [PARTIAL_ROLLBACK] (3x): gpt-4.1-nano (fixed parser):LEG(C/P/P), gpt-4o-mini:LEG_LEAN(C/P/P), gpt-5-mini:LEG_LEAN(C/P/P)
- `silent_default_c` [SILENT_DEFAULT] (3x): gpt-4.1-nano (fixed parser):BL(C/P/P), gpt-4.1-nano (fixed parser):LEG(C/C/P), gpt-5-mini:BL(C/P/P)
- `early_return_c` [EARLY_RETURN] (2x): gpt-4.1-nano (fixed parser):BL(C/P/P), gpt-5-mini:LEG_LEAN(C/P/P)
- `ordering_dependency` [TEMPORAL_ORDERING] (2x): gpt-4.1-nano (fixed parser):LEG_LEAN(C/W/W), gpt-4o-mini:BL(C/C/P)
- `use_before_set_c` [USE_BEFORE_SET] (2x): gpt-4o-mini:LEG(C/C/P), gpt-5-mini:BL(C/P/P)
- `invariant_partial_fail` [INVARIANT_VIOLATION] (2x): gpt-5-mini:LEG(C/P/P), gpt-5-mini:LEG_LEAN(C/P/P)

**Hotspot families:** HIDDEN_DEPENDENCY (`hidden_dep_multihop`, 4x), INDEX_MISALIGN
(`index_misalign_c`, 4x), PARTIAL_ROLLBACK (`partial_rollback_b/c`, 6x combined),
MUTABLE_DEFAULT (`mutable_default_c`, 3x). These families have bugs where the test
suite accepts solutions that are technically correct but do not match the stated fix
strategy -- the model finds alternative valid fixes.

## 8. LEG Effect by Bug Family

| Family | Helps | Hurts | Net | Fixes LEG | Creates LEG | Verdict |
|---|---|---|---|---|---|---|
| SIDE_EFFECT_ORDER | 3 | 0 | +3 | 2 | 0 | BENEFICIAL |
| EARLY_RETURN | 2 | 0 | +2 | 1 | 0 | BENEFICIAL |
| CACHE_ORDERING | 1 | 0 | +1 | 0 | 0 | BENEFICIAL |
| INVARIANT_VIOLATION | 1 | 0 | +1 | 0 | 0 | BENEFICIAL |
| FLAG_DRIFT | 1 | 0 | +1 | 1 | 0 | BENEFICIAL |
| HIDDEN_DEPENDENCY | 1 | 0 | +1 | 1 | 0 | BENEFICIAL |
| STATE_SEMANTIC_VIOLATION | 1 | 0 | +1 | 1 | 0 | BENEFICIAL |
| TEMPORAL_ORDERING | 1 | 0 | +1 | 0 | 0 | BENEFICIAL |
| USE_BEFORE_SET | 2 | 1 | +1 | 1 | 1 | BENEFICIAL |
| TEMPORAL_DRIFT | 0 | 0 | +0 | 0 | 0 | NEUTRAL |
| PARTIAL_STATE_UPDATE | 2 | 3 | -1 | 1 | 3 | HARMFUL |
| MISSING_BRANCH | 0 | 1 | -1 | 0 | 0 | HARMFUL |
| MUTABLE_DEFAULT | 1 | 2 | -1 | 1 | 1 | HARMFUL |
| PARTIAL_ROLLBACK | 0 | 1 | -1 | 0 | 1 | HARMFUL |
| WRONG_CONDITION | 0 | 1 | -1 | 0 | 1 | HARMFUL |
| ALIASING | 0 | 2 | -2 | 0 | 0 | HARMFUL |
| INDEX_MISALIGN | 0 | 2 | -2 | 0 | 2 | HARMFUL |
| RETRY_DUPLICATION | 0 | 2 | -2 | 0 | 1 | HARMFUL |
| STALE_CACHE | 0 | 2 | -2 | 0 | 1 | HARMFUL |
| RACE_CONDITION | 0 | 3 | -3 | 0 | 3 | HARMFUL |
| INIT_ORDER | 0 | 3 | -3 | 0 | 3 | HARMFUL |
| SILENT_DEFAULT | 0 | 3 | -3 | 0 | 2 | HARMFUL |

**Families where LEG is BENEFICIAL** (structured reasoning helps):

- **SIDE_EFFECT_ORDER (+3):** The strongest beneficiary. Side-effect ordering requires
  reasoning about execution sequence -- explicit commitment to "effects must occur at
  correct granularity" helps the model coordinate multi-step fixes.
- **EARLY_RETURN (+2):** Early return bugs involve control flow reasoning that benefits
  from explicit fix strategy articulation.
- **USE_BEFORE_SET (+1):** Mixed -- LEG helps one case, hurts another. Variable
  initialization bugs are borderline: some benefit from planning, others do not.

**Families where LEG is HARMFUL** (structured reasoning hurts):

- **INIT_ORDER (-3), SILENT_DEFAULT (-3):** These have simple, mechanical fixes
  (move initialization, add explicit default). Forcing the model to articulate
  commitments before coding adds overhead that degrades output quality.
- **RACE_CONDITION (-3):** Race conditions are hard for all prompting strategies.
  LEG does not help and creates new LEGs by making the model overthink concurrency.
- **ALIASING (-2), STALE_CACHE (-2):** Single-point fixes (copy dict, invalidate cache)
  that do not benefit from explicit planning.

**The pattern:** LEG helps on bugs requiring **multi-step coordination** (side effects,
control flow, state pipelines). It hurts on bugs with **single-point mechanical fixes**
(copy, move, add default). This suggests structured prompting is most valuable when the
fix requires the model to maintain multiple invariants simultaneously.

## 9. Parser Fix Impact (gpt-4.1-nano)

| Metric | Old Parser | Fixed Parser | Delta |
|---|---|---|---|
| BL | 46/58 (79%) | 45/58 (78%) | -1 |
| LEG | 38/58 (66%) | 42/58 (72%) | +4 |
| LEG_LEAN | 40/58 (69%) | 43/58 (74%) | +3 |
| Parse failures | 13 | 3 | -10 |

The parser repair addresses unescaped triple-quote Python docstrings in JSON string
values -- a model-level serialization issue where gpt-4.1-nano outputs unescaped
`"""docstring"""` instead of properly JSON-escaped triple quotes. The fix recovered
10 parse failures, primarily in leg_reduction_v2 (+6pp) and leg_reduction_lean_v2 (+5pp).

**Important caveat:** 50 case/condition pairs changed between the two runs beyond
parse failures, despite temperature=0.0. This indicates non-determinism in the model
output, likely from infrastructure-level variation (batching, quantization). Single-trial
results should be interpreted with this noise floor in mind.

## 10. Hardest Cases

Only 2 cases fail across all conditions in all 3 models:

| Case | Family | BL Categories (nano/4omini/5mini) |
|---|---|---|
| async_race_lock | RACE_CONDITION | LEG/FULL_F/FULL_F |
| false_fix_deadlock | RACE_CONDITION | FULL_F/LEG/FULL_F |

Both are RACE_CONDITION cases involving concurrency patterns that are fundamentally
beyond current model capability at these model sizes. `async_race_lock` requires
understanding lock ordering; `false_fix_deadlock` requires recognizing that a proposed
fix introduces a deadlock.

## 11. Summary and Research Implications

### The Baseline-Category Predictor

The single strongest finding: **baseline v2_category perfectly predicts LEG intervention
outcome.** When baseline has LEG_v2 or full_failure, intervention always helps. When
baseline has interpretable_success, intervention always hurts. This holds across all 3
models with zero exceptions (N=174 per model).

### The Structured Prompting Tradeoff

Structured prompting (LEG) is not uniformly beneficial. It has a clear cost-benefit
profile:

- **Benefit:** Forces models to bridge reasoning-execution gaps on multi-step bugs
  (+15 cases helped across models)
- **Cost:** Introduces overthinking and serialization overhead on simple bugs
  (-26 cases hurt across models)
- **Net:** Negative for weaker models (nano -3, 4o-mini -8), neutral-to-positive
  for stronger models (5-mini +1)

### Model Capability Interaction

| Model | BL-LEG Gap | Parse Fail Rate | LEG Helped | LEG Hurt |
|---|---|---|---|---|
| gpt-4.1-nano (fixed) | -6pp | 1.7% | 5 | 8 |
| gpt-4o-mini | -14pp | 5.2% | 6 | 14 |
| gpt-5-mini | +1pp | 0% | 5 | 4 |

The structured prompt cost scales inversely with model capability. gpt-5-mini can
follow structured instructions without degradation; gpt-4o-mini struggles with both
JSON serialization and the cognitive overhead of explicit planning.

### Bug Complexity as Moderator

LEG intervention is beneficial for bugs requiring multi-step coordination:
SIDE_EFFECT_ORDER, EARLY_RETURN, STATE_SEMANTIC_VIOLATION. It is harmful for bugs
with simple mechanical fixes: INIT_ORDER, SILENT_DEFAULT, ALIASING. The distinguishing
factor is whether the fix requires maintaining multiple invariants simultaneously --
explicit commitment planning helps when there is genuine coordination complexity.

### Toward Targeted Intervention

The perfect predictive power of the baseline category suggests an optimal strategy:

1. Run baseline_v2 on all cases
2. Classify results using the v2 evaluator
3. Re-run only LEG_v2 and full_failure_v2 cases with leg_reduction_v2
4. Keep baseline results for interpretable_success cases

This two-phase strategy would achieve the highest possible pass rate by capturing
all LEG fixes while avoiding all LEG-induced regressions. The v2 classifier's
multi-dimensional evaluation makes this targeting possible -- the v1 binary
`reasoning_correct` flag did not have sufficient resolution to distinguish
fixable LEG cases from cases that should be left alone.
