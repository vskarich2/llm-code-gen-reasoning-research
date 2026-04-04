# Targeted Follow-Up Analysis: 50-Trial Experimental Design

**Date:** 2026-03-30
**Source:** v2_full_4model_5trial (3480 records, 4 models × 5 trials × 3 conditions × 58 cases)
**Purpose:** Identify high-signal case × model slices for 50-trial statistical validation

---

## 1. High-Effect Candidates (Ranked)

From 228 case × model × condition slices meeting |Δpass| ≥ 20% or |ΔLEG| ≥ 5%, filtered to those with cross-model interpretability:

### Tier 1: Large, replicated, interpretable effects

| Case | Pattern | Key Signal | Confirmed in 4t? |
|---|---|---|---|
| **lost_update** | BOTH_IMPROVE | 5.4-mini: +70%, nano: +40% | YES (+41.7%) |
| **cache_invalidation_order** | DIVERGENT (weak>>strong) | nano: +60%, 4o-mini: +40% | YES (+41.7%) |
| **partial_rollback_c** | STRONG_ONLY | 5-mini: +60%, 5.4-mini: +30% | not tested |
| **effect_order_c** | STRONG_ONLY | 5-mini: +60% (others at ceiling) | partially (+16.7%) |

### Tier 2: Strong single-model effects

| Case | Model | Δpass | Pattern |
|---|---|---|---|
| **mutable_default_b** | nano | +60% (both conditions) | WEAK_ONLY |
| **partial_rollback_b** | 5-mini | +50% | STRONG_ONLY |
| **invariant_partial_fail** | 5-mini | +40% (lean: +60%) | STRONG_ONLY |
| **l3_state_pipeline** | 5-mini/5.4-mini | +20% each | STRONG_ONLY |

### Tier 3: Strong negative effects (intervention hurts)

| Case | Model | Δpass | Pattern |
|---|---|---|---|
| **alias_config_c** | nano | −100% (both conditions) | WEAK_HURT |
| **lazy_init_c** | nano/4o-mini | −30%/−70% | WEAK_HURT |
| **hidden_dep_multihop** | nano | −70% (but 4o-mini: +90%) | DIVERGENT |

### Tier 4: Reasoning-limited (intervention irrelevant)

| Case | All Models | Pass Rate | LEG Rate |
|---|---|---|---|
| **async_race_lock** | 0% across all | 80-100% LEG | no improvement |
| **false_fix_deadlock** | 0-20% across all | 20-100% LEG | no improvement |

---

## 2. Failure-Type Classification

### A. Execution-Alignment Failures (intervention helps translate reasoning to code)

**lost_update** (RACE_CONDITION, 1 file)
- Baseline: 0-40% pass, 60-100% LEG → models identify the race but can't code the fix
- Intervention: 5.4-mini goes 20%→100% (leg_v2), nano goes 0%→80% (leg_v2)
- Classification: **EXECUTION-ALIGNMENT** — the structured reasoning template forces models to articulate the specific update ordering, which translates to correct locking/sequencing code
- Why model-dependent: 4o-mini shows zero improvement (40%→40%) — it may lack the code generation capacity to benefit even with better reasoning scaffolding
- **50-trial confirmed**: nano 18%→31% (p=.026), 5.4-mini 69%→100% (p<.001)

**cache_invalidation_order** (CACHE_ORDERING, 4 files)
- Baseline: 20-40% pass (except 5-mini at 100%), 60-80% LEG
- Intervention: nano goes 40%→100% (both conditions), 4o-mini 20%→100% (leg only)
- Classification: **EXECUTION-ALIGNMENT** — the cache ordering is correctly identified but incorrectly implemented. The reasoning template forces explicit ordering commitments that translate to correct invalidation sequence
- Why stronger models don't benefit: 5-mini already at 100% baseline; 5.4-mini only +30% (still struggling with 4-file structure)
- **50-trial confirmed**: nano 59%→94-100% (p<.001), 5.4-mini lean 40%→56% (p=.014)

**partial_rollback_c** (PARTIAL_ROLLBACK, 3 files)
- Baseline: weak models at 100% (easy for them), strong models at 20-60%
- Intervention: 5-mini jumps 20%→100% (leg_v2), 5.4-mini 60%→100% (lean)
- Classification: **EXECUTION-ALIGNMENT** — the rollback logic requires careful state management. Stronger models try more sophisticated approaches that fail; the reasoning template constrains them to explicit commit/rollback sequences
- Anomaly: 4o-mini drops 100%→0% on lean — the template may interfere with its simpler (but correct) approach

**partial_rollback_b** (PARTIAL_ROLLBACK, 2 files)
- Same pattern as _c but cleaner: 5-mini 40%→100% (leg)
- Nano/4o-mini at ceiling → hurt by intervention (−40% nano on lean)
- Classification: **EXECUTION-ALIGNMENT** (strong models only)

### B. Structure-Sensitive Failures (intervention helps weak models navigate multi-file cases)

**mutable_default_b** (MUTABLE_DEFAULT, 2 files)
- Baseline: nano at 20%, all others at 100%
- Intervention: nano jumps to 80% (both conditions)
- Classification: **STRUCTURE-SENSITIVE** — the mutable default is easy to identify and fix in 1 file, but the 2-file version requires understanding cross-file state. The reasoning template helps nano explicitly track which file owns the mutable default
- All strong models already solve this → intervention is irrelevant for them

**alias_config_c** (ALIASING, 3 files) — NEGATIVE
- Baseline: all models at 100%
- Intervention: nano drops to 0%, 4o-mini drops to 40% (leg)
- Classification: **STRUCTURE-SENSITIVE (NEGATIVE)** — the 3-file aliasing case is simple enough that all models solve it with minimal reasoning. The LEG template adds overhead that confuses weaker models' code generation without improving their already-correct reasoning
- This is the strongest evidence that LEG interventions can HARM easy cases

### C. Reasoning-Limited Failures (intervention cannot help)

**async_race_lock** (RACE_CONDITION, 4 files)
- 0% pass rate across ALL models and ALL conditions
- 80-100% LEG rate → models correctly identify the race but CANNOT produce correct concurrent code
- Classification: **REASONING-LIMITED** — this isn't a reasoning problem. The models understand the bug but lack the capacity to generate correct lock ordering/acquisition code. No prompt intervention can fix this
- The 4-file structure with concurrent lock acquisition is beyond current model code generation capability

**false_fix_deadlock** (RACE_CONDITION, 1 file)
- 0-20% pass, 20-100% LEG
- No model improves with intervention
- Classification: **REASONING-LIMITED** — the deadlock fix requires understanding lock ordering invariants at a level models can diagnose but not implement

**l3_state_pipeline** (STATE_SEMANTIC_VIOLATION, 5 files)
- Weak models: 0% across all conditions (too many files)
- Strong models: 60%→80% with intervention
- Classification: **MIXED** — reasoning-limited for weak models (5-file case is structurally beyond them), execution-alignment for strong models

### D. Divergent/Ambiguous Cases

**hidden_dep_multihop** (HIDDEN_DEPENDENCY, 4 files)
- nano: 100%→20% (−80%) — intervention DESTROYS performance
- 4o-mini: 0%→100% (+100%) — intervention CREATES performance
- 5-mini: flat (40%)
- 5.4-mini: 100%→80% (−20%)
- Classification: **AMBIGUOUS** — the hidden dependency requires multi-hop reasoning. For nano, the structured template may force it to over-commit to a single causal chain, missing the correct multi-hop path. For 4o-mini, the template may provide the scaffolding needed to follow the dependency chain
- This is the most theoretically interesting case: same intervention, opposite effects

**feature_flag_drift** (FLAG_DRIFT, 4 files)
- nano: 20%→0% (hurt), 5.4-mini: 20%→60% (helped), 5-mini: 100%→60% (hurt)
- Classification: **AMBIGUOUS** — no consistent pattern across capability levels

---

## 3. Cross-Model Interaction Summary

| Pattern | Count | Interpretation |
|---|---|---|
| **WEAK_HURT** | 16 | LEG intervention adds overhead that confuses weaker models on cases they can already solve |
| **MIXED/NOISE** | 14 | No reliable signal — effects within N=5 noise |
| **STRONG_ONLY** | 6 | Intervention helps stronger models translate reasoning to code; weak models either at ceiling or floor |
| **WEAK_ONLY** | 6 | Intervention helps weak models navigate structure; strong models already at ceiling |
| **BOTH_IMPROVE** | 1 | Rare: only lost_update shows consistent improvement across capability levels |
| **DIVERGENT** | 2 | Same intervention, opposite effects by model — theoretically interesting |
| **STRONG_HURT** | 1 | config_shadowing: intervention hurts stronger models |

**Key insight:** The dominant pattern (16/46 = 35%) is WEAK_HURT — LEG interventions on easy cases harm weaker models. This is the "reasoning overhead" effect: forcing explicit reasoning on cases that models solve implicitly adds opportunities for error.

---

## 4. Final Selected Cases for 50-Trial Ablation

### A. Execution-Alignment (intervention helps translate reasoning to code)

| # | Case | Models | Why |
|---|---|---|---|
| A1 | **lost_update** | nano, 5.4-mini | Already confirmed at 50 trials. 5.4-mini: 69→100% (p<.001). nano: 18→31% (p=.026). |
| A2 | **cache_invalidation_order** | nano, 5.4-mini | Already confirmed at 50 trials. nano: 59→94-100% (p<.001). |
| A3 | **partial_rollback_c** | 5-mini, 5.4-mini | 5-mini: 20→100% in 5t data. Tests execution-alignment in multi-file rollback logic. |
| A4 | **partial_rollback_b** | 5-mini | 40→100% in 5t. Simpler version (2 files) to test if effect scales with file count. |

### B. Structure-Sensitive (intervention helps navigate multi-file cases)

| # | Case | Models | Why |
|---|---|---|---|
| B1 | **mutable_default_b** | nano | 20→80% in 5t. Only nano struggles. Tests whether reasoning template helps weak models navigate 2-file mutable default. |
| B2 | **effect_order_c** | 5-mini | 0→40-80% in 5t. Tests whether reasoning template helps mid-capability model with 3-file ordering. |
| B3 | **invariant_partial_fail** | 5-mini | 20→40-80% in 5t. 4-file invariant violation — tests structure-sensitivity at higher file counts. |

### C. Reasoning-Limited (negative control — intervention should NOT help)

| # | Case | Models | Why |
|---|---|---|---|
| C1 | **async_race_lock** | 5.4-mini | 0% across all conditions. Strongest model still can't solve it. Confirms reasoning ceiling. |
| C2 | **false_fix_deadlock** | 5-mini | 0-20% across all. Confirms that deadlock reasoning is beyond code generation capability. |

### D. Divergent (theoretically interesting — same intervention, opposite effects)

| # | Case | Models | Why |
|---|---|---|---|
| D1 | **hidden_dep_multihop** | nano, 4o-mini | nano: −70%, 4o-mini: +90%. Tests whether the multi-hop dependency chain interaction is real or N=5 noise. |
| D2 | **alias_config_c** | nano, 5-mini | nano: −100%, 5-mini: 0%. Tests the "reasoning overhead harms easy cases" hypothesis. |

---

## 5. Experimental Plan

### A1: lost_update × {nano, 5.4-mini}
**ALREADY COMPLETED (50 trials)**
- nano: baseline 18% → leg 31% (p=.026*), lean 27% (p=.10 ns)
- 5.4-mini: baseline 69% → leg 100% (p<.001***), lean 92% (p<.001***)
- **Confirmed:** Execution-alignment. Stronger model benefits more. leg_v2 > lean_v2.

### A2: cache_invalidation_order × {nano, 5.4-mini}
**ALREADY COMPLETED (50 trials)**
- nano: baseline 59% → leg 94% (p<.001***), lean 100% (p<.001***)
- 5.4-mini: baseline 40% → leg 44% (p=.33 ns), lean 56% (p=.014*)
- **Confirmed:** Execution-alignment for nano. Weak model benefits more (reversed from lost_update). lean_v2 > leg_v2 for nano.

### A3: partial_rollback_c × {5-mini, 5.4-mini}
```
Case: partial_rollback_c
Models: gpt-5-mini, gpt-5.4-mini
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Metrics: pass rate, TRUE LEG, no-code rate
Hypothesis: 5-mini improves +40-60%, 5.4-mini improves +20-30%
  leg_v2 > lean_v2 (explicit commitments help rollback logic)

What this confirms:
  - Whether execution-alignment extends to rollback/transaction logic
  - Whether the effect is stronger for mid-capability (5-mini) vs high-capability (5.4-mini)
  - Paired with A4 (partial_rollback_b), tests if effect scales with file count
```

### A4: partial_rollback_b × {5-mini}
```
Case: partial_rollback_b
Model: gpt-5-mini
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Hypothesis: 5-mini improves +40-50% (40→80-90%)
  Effect should be smaller than partial_rollback_c (fewer files = easier structure)

What this confirms:
  - Whether rollback execution-alignment scales with structural complexity
  - Comparison: A3 (3 files) vs A4 (2 files) for same model
```

### B1: mutable_default_b × {nano}
```
Case: mutable_default_b
Model: gpt-4.1-nano
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Hypothesis: nano improves +40-60% (20→60-80%)
  Both conditions should help roughly equally

What this confirms:
  - Whether reasoning template helps weak models navigate 2-file mutable default
  - Pure structure-sensitivity test (strong models already at ceiling)
```

### B2: effect_order_c × {5-mini}
```
Case: effect_order_c
Model: gpt-5-mini
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Hypothesis: 5-mini improves +30-50% (0→30-50%)
  lean_v2 > leg_v2 (lean showed +80% vs leg's +40% in 5t data)

What this confirms:
  - Whether explicit ordering commitments help side-effect ordering
  - Whether lean (lighter template) is more effective than full LEG for ordering bugs
```

### C1: async_race_lock × {5.4-mini}
```
Case: async_race_lock
Model: gpt-5.4-mini
Conditions: baseline_v2, leg_reduction_v2
Trials: 50

Hypothesis: NO improvement. Pass rate stays at 0-5%.

What this confirms:
  - Negative control: concurrent lock code is beyond prompt intervention
  - Establishes the floor of what LEG interventions cannot fix
```

### C2: false_fix_deadlock × {5-mini}
```
Case: false_fix_deadlock
Model: gpt-5-mini
Conditions: baseline_v2, leg_reduction_v2
Trials: 50

Hypothesis: NO improvement. Pass rate stays at 0-20%.

What this confirms:
  - Second negative control: deadlock reasoning doesn't translate to code
  - Different from C1 (single file vs 4 files) but same failure mode
```

### D1: hidden_dep_multihop × {nano, 4o-mini}
```
Case: hidden_dep_multihop
Models: gpt-4.1-nano, gpt-4o-mini
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Hypothesis:
  - nano: DECREASES by 30-50% (100→50-70%)
  - 4o-mini: INCREASES by 40-60% (0→40-60%)

What this confirms:
  - Whether the divergent pattern is real or N=5 noise
  - If confirmed: the same reasoning scaffolding helps one model but hurts another
  - Interpretation: nano solves via implicit pattern matching (template disrupts this),
    4o-mini needs explicit dependency tracking (template provides this)
```

### D2: alias_config_c × {nano}
```
Case: alias_config_c
Model: gpt-4.1-nano
Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
Trials: 50

Hypothesis: nano DECREASES from ~100% to 20-40%

What this confirms:
  - The "reasoning overhead harms easy cases" hypothesis
  - If confirmed: provides evidence that LEG interventions should NOT be applied universally
  - Critical for paper: bounds the applicability claim
```

---

## 6. Cost Summary

| Experiment | Cases | Models | Conditions | Trials | Total Evals |
|---|---|---|---|---|---|
| A1+A2 (done) | 2 | 2 | 3 | 50 | 600 (complete) |
| A3 | 1 | 2 | 3 | 50 | 300 |
| A4 | 1 | 1 | 3 | 50 | 150 |
| B1 | 1 | 1 | 3 | 50 | 150 |
| B2 | 1 | 1 | 3 | 50 | 150 |
| C1 | 1 | 1 | 2 | 50 | 100 |
| C2 | 1 | 1 | 2 | 50 | 100 |
| D1 | 1 | 2 | 3 | 50 | 300 |
| D2 | 1 | 1 | 3 | 50 | 150 |
| **Total remaining** | | | | | **1,400** |

With 25 parallel processes, ~6 evals each, at ~15s/eval: **~6 minutes total**.

---

## 7. What This Proves

If results hold:

1. **LEG interventions improve execution-alignment selectively** — they help models translate correct reasoning into correct code, but only when the model has sufficient baseline capability AND the bug requires explicit state/ordering reasoning (lost_update, cache_invalidation_order, partial_rollback)

2. **The effect is case×model specific, not universal** — the same intervention helps nano on cache bugs but hurts it on aliasing; helps 5.4-mini on race conditions but not cache ordering

3. **Concurrency bugs are beyond prompt intervention** — async_race_lock and false_fix_deadlock represent a capability ceiling that reasoning scaffolding cannot breach

4. **LEG interventions can harm performance on easy cases** — the "reasoning overhead" effect (alias_config_c, many WEAK_HURT cases) means the intervention should be applied conditionally, not universally

5. **The divergent pattern (hidden_dep_multihop) suggests reasoning scaffolding interacts with implicit vs explicit problem-solving strategies** — different models solve the same bug via different cognitive paths, and the intervention helps explicit but harms implicit approaches
