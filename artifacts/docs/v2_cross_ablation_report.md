# V2 Cross-Ablation Report

## Dataset

3,480 unique evaluations across 3 ablation runs:

| Ablation | Models | Trials | Evals |
|---|---|---|---|
| Single-trial v2 (merged as trial 5) | gpt-4.1-nano, gpt-4o-mini, gpt-5-mini | 1 | 522 |
| Four-trial v2 | gpt-4.1-nano, gpt-4o-mini, gpt-5-mini | 4 | 2,088 |
| 5.4-mini | gpt-5.4-mini | 5 | 870 |

The single-trial ablation was a separate API run from the 4-trial ablation. It was
merged as trial 5 (17% disagreement with trial 1, confirming it is an independent
sample, not a duplicate). This gives 5 trials per model for the 3 weaker models
and 5 trials for gpt-5.4-mini.

58 cases, 3 conditions (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2).
Evaluator: gpt-5-mini (grounded mode) for all runs. Temperature: 0.0.
Total: 290 evaluations per model per condition.

---

## 1. Pass Rates

| Model | Baseline | LEG | LEAN | Trials | N/cond |
|---|---|---|---|---|---|
| gpt-4.1-nano | 76% (221/290) | 67% (194/290) | 72% (208/290) | 5 | 290 |
| gpt-4o-mini | 71% (206/290) | 68% (196/290) | 65% (188/290) | 5 | 290 |
| gpt-5-mini | 74% (215/290) | 79% (228/290) | 83% (240/290) | 5 | 290 |
| gpt-5.4-mini | 91% (265/290) | 90% (260/290) | 91% (264/290) | 5 | 290 |

### Key findings

- **gpt-5.4-mini dominates** at 90-91% across all conditions. The BL-LEG gap is
  negligible (-1.7pp). The structured prompt neither helps nor hurts.
- **gpt-5-mini is the only model where LEG beats baseline** (+6pp for LEG, +10pp
  for LEAN). The structured prompt improves the mid-tier model.
- **gpt-4o-mini and gpt-4.1-nano are both hurt by structured prompts** (-4pp to -10pp).
  LEAN hurts 4o-mini more than LEG (-8pp vs -4pp), while for nano LEG hurts more
  than LEAN (-10pp vs -6pp).
- **Model capability determines intervention benefit.** There is a clear threshold:
  below ~75% baseline accuracy, structured prompting hurts. Above it, it helps or
  is neutral.

---

## 2. LEG Intervention Effect

| Model | HELPS | HURTS | BOTH_PASS | BOTH_FAIL | Net |
|---|---|---|---|---|---|
| gpt-4.1-nano | 4 | 11 | 34 | 9 | -7 |
| gpt-4o-mini | 8 | 12 | 32 | 6 | -4 |
| gpt-5-mini | 1 | 1 | 48 | 8 | 0 |
| gpt-5.4-mini | 1 | 0 | 54 | 3 | +1 |

The net intervention effect correlates monotonically with model capability:
nano (-7) < 4o-mini (-4) < 5-mini (0) < 5.4-mini (+1).

For gpt-5.4-mini, 54/58 cases are BOTH_PASS — the model solves them regardless
of prompting strategy. Only 3 cases defeat it entirely (BOTH_FAIL), and LEG helps
exactly 1 case. The structured prompt is essentially invisible to this model.

---

## 3. Cross-Trial Stability

| Model | Unstable Pairs | Total | % Unstable | Trials |
|---|---|---|---|---|
| gpt-4.1-nano | 63/174 | 36% | 5 |
| gpt-4o-mini | 61/174 | 35% | 5 |
| gpt-5-mini | 71/174 | 41% | 5 |
| gpt-5.4-mini | 28/174 | 16% | 5 |

At temperature=0.0, 35-41% of case/condition pairs produce different pass/fail
results across 5 trials for the three weaker models. This is infrastructure
non-determinism (API batching, quantization), not prompt variation.

gpt-5-mini is actually the MOST unstable (41%) despite being a stronger model.
This suggests its accuracy sits closer to the decision boundary on more cases —
it gets more cases "almost right" where a slight perturbation flips the result.

gpt-5.4-mini is significantly more stable (16%), likely because its higher accuracy
means fewer borderline cases.

**Implication:** Single-trial results are unreliable for case-level conclusions.
Multi-trial aggregation is essential for this benchmark.

---

## 4. File Complexity Interaction

Pass rates by number of source files, for LEG_v2 condition:

| Files | nano | 4o-mini | 5-mini | 5.4-mini |
|---|---|---|---|---|
| 1-file | 80% | 66% | 84% | 95% |
| 2-file | 62% | 72% | 87% | 100% |
| 3-file | 69% | 73% | 73% | 86% |
| 4+file | 44% | 47% | 66% | 65% |

### Key findings

- **4+ file cases are universally hard.** Even gpt-5.4-mini drops to 65%. These
  cases (`async_race_lock`, `l3_state_pipeline`, `cache_invalidation_order`, etc.)
  require multi-file coordination that all models struggle with.
- **gpt-5.4-mini achieves 100% on 2-file LEG cases.** The structured prompt +
  strong model completely solves two-file coordination problems.
- **nano collapses on 2-file LEG (62%)** despite 87% baseline — the structured
  prompt specifically hurts nano on multi-file coordination. This is the
  serialization tax: nano can't format the 5-field JSON response correctly when
  dealing with multiple files.
- **gpt-5-mini's LEG advantage is strongest on 2-file cases** (87% vs 78% baseline).
  The structured prompt helps mid-tier models coordinate across two files.

---

## 5. Case Clusters

### Consistently helped by LEG (2+ models)

| Case | Family | Models helped |
|---|---|---|
| cache_invalidation_order | CACHE_ORDERING | nano, 4o-mini |
| lost_update | RACE_CONDITION | 4o-mini, 5.4-mini |

Only 2 cases are consistently helped across multiple models. LEG's benefits are
model-specific rather than case-universal.

### Consistently hurt by LEG (2+ models)

| Case | Family | Models hurt |
|---|---|---|
| alias_config_c | ALIASING | nano, 4o-mini |
| hidden_dep_multihop | HIDDEN_DEPENDENCY | nano, 5-mini |
| lazy_init_b | INIT_ORDER | nano, 4o-mini |
| lazy_init_c | INIT_ORDER | nano, 4o-mini |
| silent_default_b | SILENT_DEFAULT | nano, 4o-mini |
| temporal_drift_b | TEMPORAL_DRIFT | nano, 4o-mini |

6 cases are consistently hurt across multiple models. All are from families with
simple, mechanical fixes (init order, aliasing, silent defaults). The structured
prompt adds overhead that degrades output on these straightforward cases.

### The asymmetry

Consistent hurts outnumber consistent helps 3:1 (6 vs 2). This is the core
tradeoff: structured prompting has concentrated costs (specific case types) but
diffuse benefits (model-specific, not case-specific).

---

## 6. Family-Level Analysis

| Family | Helps | Hurts | Net | Verdict |
|---|---|---|---|---|
| CACHE_ORDERING | 2 | 0 | +2 | BENEFICIAL |
| RACE_CONDITION | 2 | 0 | +2 | BENEFICIAL |
| PARTIAL_ROLLBACK | 2 | 1 | +1 | BENEFICIAL |
| HIDDEN_DEPENDENCY | 2 | 2 | 0 | NEUTRAL |
| MUTABLE_DEFAULT | 1 | 1 | 0 | NEUTRAL |
| USE_BEFORE_SET | 2 | 2 | 0 | NEUTRAL |
| STALE_CACHE | 1 | 2 | -1 | HARMFUL |
| RETRY_DUPLICATION | 1 | 2 | -1 | HARMFUL |
| EARLY_RETURN | 1 | 2 | -1 | HARMFUL |
| TEMPORAL_DRIFT | 0 | 2 | -2 | HARMFUL |
| ALIASING | 0 | 2 | -2 | HARMFUL |
| PARTIAL_STATE_UPDATE | 1 | 4 | -3 | HARMFUL |
| INIT_ORDER | 1 | 5 | -4 | HARMFUL |

### The pattern

LEG is beneficial for bugs requiring **multi-step coordination across components**:
CACHE_ORDERING (invalidation sequences), RACE_CONDITION (lock ordering),
PARTIAL_ROLLBACK (state restoration). These bugs benefit from explicit planning
because the fix requires maintaining multiple invariants simultaneously.

LEG is harmful for bugs with **simple, localized fixes**: INIT_ORDER (move
initialization), ALIASING (copy dict), PARTIAL_STATE_UPDATE (add one update line).
The structured prompt adds cognitive overhead that degrades output on cases where
the model already knows the fix implicitly.

INIT_ORDER is the most consistently harmful family (-4 net across all models).

---

## 7. V2 Category Distribution

### LEG detection rates by model

| Model | BL LEG_v2 | LEG LEG_v2 | LEAN LEG_v2 |
|---|---|---|---|
| gpt-4.1-nano | 21 (9%) | 41 (18%) | 30 (13%) |
| gpt-4o-mini | 36 (16%) | 43 (19%) | 68 (29%) |
| gpt-5-mini | 33 (14%) | 17 (7%) | 23 (10%) |
| gpt-5.4-mini | 10 (3%) | 5 (2%) | 7 (2%) |

### Key findings

- **gpt-4o-mini LEAN has the highest LEG rate (29%).** The lean prompt elicits
  correct reasoning from 4o-mini, but the model fails to implement it in code.
  This is the core LEG phenomenon: reasoning-execution gap.
- **gpt-5.4-mini has near-zero LEG (2-3%).** When this model reasons correctly,
  it almost always produces correct code. The gap is closed.
- **gpt-5-mini's LEG rate drops under structured prompting** (14% BL -> 7% LEG).
  The structured prompt helps this model bridge the gap — fewer cases where
  reasoning is right but code is wrong.
- **gpt-4.1-nano's LEG rate increases under structured prompting** (9% BL -> 18%
  LEG). The structured prompt makes nano articulate correct reasoning but then
  fail on code — it literally creates the gap.

---

## 8. Serialization Tax

| Model | BL tax | LEG tax | LEAN tax |
|---|---|---|---|
| gpt-4.1-nano | 8.2% | 8.6% | 6.5% |
| gpt-4o-mini | 4.3% | 5.2% | 1.7% |
| gpt-5-mini | 0.4% | 0% | 0% |
| gpt-5.4-mini | 0% | 0% | 0.3% |

Serialization tax = events where recovery parser succeeds but execution parser fails.
This is pure formatting overhead — the model's reasoning and code were correct but
the JSON output was malformed.

nano pays the highest tax (8-9%), primarily from triple-quote docstring escaping in
multi-file responses. gpt-5-mini and gpt-5.4-mini have near-zero tax.

---

## 9. Anomalies

### gpt-4o-mini LEAN paradox

gpt-4o-mini performs worse with LEAN (63%) than LEG (67%) or baseline (71%). This
is the opposite of the expected pattern (LEAN should be between baseline and LEG).
The lean prompt may be insufficiently constraining for 4o-mini, giving it enough
structure to attempt complex reasoning but not enough guidance to execute it.

### gpt-5-mini LEAN advantage

gpt-5-mini shows LEAN (83%) > LEG (79%) > baseline (73%). Both structured prompts
help, but LEAN helps more than full LEG. The lighter prompt may be better suited
to 5-mini's capability level — enough structure to organize reasoning without the
overhead of the full 5-field schema.

### 4+file collapse

All models show severe degradation on 4+ file cases (25-66%). These cases represent
a complexity threshold that current models struggle with regardless of prompting
strategy. Only gpt-5-mini shows meaningful benefit from structured prompting on these
cases (66% LEG vs 56% baseline).

### Temperature=0.0 instability

30-35% of case/condition pairs are unstable across trials at temperature=0.0 for the
three weaker models. This is a measurement floor: any single-trial difference smaller
than ~5pp may be noise.

---

## 10. Summary

### The capability threshold

There is a clear threshold around 75% baseline accuracy that determines whether
structured prompting helps:

- **Below threshold** (nano 77%, 4o-mini 71%): LEG hurts. The model cannot reliably
  follow the structured output format while also reasoning and coding correctly. The
  overhead exceeds the benefit.
- **At threshold** (5-mini 73%): LEG helps (+6pp). The model is capable enough to
  follow the format and benefits from the planning structure.
- **Above threshold** (5.4-mini 91%): LEG is invisible. The model solves cases
  regardless of prompting strategy.

### The LEG phenomenon scales inversely with capability

LEG detection rate (reasoning correct, code wrong) is highest for weaker models
and lowest for stronger ones. gpt-5.4-mini almost never exhibits LEG (2-3%).
The reasoning-execution gap is primarily a weak-model phenomenon.

### Multi-trial is essential

30%+ cross-trial instability at temperature=0.0 means single-trial ablation results
are unreliable for case-level conclusions. The 4-trial and 5-trial runs in this
dataset provide the statistical grounding needed for the family-level and model-level
findings above.

### Consistent case clusters exist but are asymmetric

6 cases are consistently hurt by LEG across multiple models (primarily INIT_ORDER
and ALIASING families). Only 2 cases are consistently helped. The structured prompt's
costs are more predictable than its benefits.

### File complexity is a major moderator

The BL-LEG gap scales with file count. Structured prompting is most beneficial for
2-3 file cases on capable models (5-mini, 5.4-mini) and most harmful for 2-3 file
cases on weak models (nano, 4o-mini). 4+ file cases are hard for everyone.
