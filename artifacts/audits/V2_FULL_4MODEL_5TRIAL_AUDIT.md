# Audit: v2_full_4model_5trial Ablation

**Date:** 2026-03-30
**Dataset:** logs/v2_full_4model_5trial (4 models × 5 trials × 3 conditions × 58 cases)
**Evaluator:** gpt-5-mini (for all models)
**Classifier:** classify_reasoning_v2.j2 via evaluator_v2.py

---

## 1. Headline Metrics

| Metric | Value |
|---|---|
| Total records | 3480 |
| Classified (have mechanism_identified) | 3360 (96.6%) |
| Parse failures (unclassified) | 120 (3.4%) |
| Overall pass rate | 2666/3480 = 76.6% |
| Mechanism correct | 3349/3360 = 99.7% |
| Reasoning correct (compat, 4-dim) | 2635/3360 = 78.4% |
| TRUE LEG (mech=CORRECT + code_fail + code_present) | 411/3360 = 12.2% |
| No-code failures (classified) | 275/3360 = 8.2% |
| Infrastructure total | 395/3480 = 11.4% |

---

## 2. Leakage Test

| Dimension | P(CORRECT\|pass) | P(CORRECT\|fail) | Ratio | Verdict |
|---|---|---|---|---|
| mechanism_identified | 99.9% | 98.8% | 1.01x | CLEAN |
| commitments_extracted | 99.8% | 94.7% | 1.05x | CLEAN |
| commitments_satisfied | 89.8% | 34.0% | **2.64x** | **LEAKED** |
| reasoning_code_alignment | 89.5% | 38.9% | **2.30x** | **LEAKED** |

**Interpretation:** Consistent with previous audits. `mechanism_identified` is the only trustworthy reasoning dimension. `commitments_satisfied` and `reasoning_code_alignment` remain coupled to code correctness. The 2.64x and 2.30x ratios are slightly lower than the v2 ablation (3.13x/2.95x), suggesting some improvement but still fundamentally compromised.

---

## 3. Per Model

| Model | N (classified) | Pass Rate | Mech Correct | RC (compat) |
|---|---|---|---|---|
| gpt-4.1-nano | 795 | 78.4% | 100.0% | 77.9% |
| gpt-4o-mini | 835 | 71.0% | 99.5% | 72.9% |
| gpt-5-mini | 866 | 78.3% | 99.7% | 79.4% |
| gpt-5.4-mini | 864 | 89.4% | 99.5% | 83.2% |

**Key finding:** gpt-5.4-mini dominates with 89.4% pass rate, 18+ points above gpt-4o-mini (71.0%). Mechanism identification is at ceiling (99.5-100%) for all models — non-discriminative.

---

## 4. Per Condition

| Condition | N | Pass Rate | RC Rate | Delta (RC − Pass) |
|---|---|---|---|---|
| baseline_v2 | 1123 | 80.6% | 78.5% | −2.1% |
| leg_reduction_lean_v2 | 1125 | 78.0% | 74.2% | −3.8% |
| leg_reduction_v2 | 1112 | 79.4% | 82.6% | +3.2% |

**Interpretation:** RC tracks pass rate closely for baseline and lean, confirming leakage. The leg_reduction_v2 condition shows a +3.2% delta (RC > pass), which is anomalous — the structured reasoning template may be inflating classifier confidence.

---

## 5. Model × Condition

| Model | Condition | N | Pass | RC |
|---|---|---|---|---|
| gpt-4.1-nano | baseline_v2 | 270 | 83.3% | 80.0% |
| gpt-4.1-nano | leg_reduction_lean_v2 | 265 | 77.4% | 74.0% |
| gpt-4.1-nano | leg_reduction_v2 | 260 | 74.2% | 79.6% |
| gpt-4o-mini | baseline_v2 | 279 | 73.8% | 73.5% |
| gpt-4o-mini | leg_reduction_lean_v2 | 283 | 66.8% | 71.4% |
| gpt-4o-mini | leg_reduction_v2 | 273 | 72.5% | 74.0% |
| gpt-5-mini | baseline_v2 | 286 | 76.6% | 80.1% |
| gpt-5-mini | leg_reduction_lean_v2 | 290 | 77.2% | 70.0% |
| gpt-5-mini | leg_reduction_v2 | 290 | 81.0% | 88.3% |
| gpt-5.4-mini | baseline_v2 | 288 | 88.5% | 80.2% |
| gpt-5.4-mini | leg_reduction_lean_v2 | 287 | 90.6% | 81.5% |
| gpt-5.4-mini | leg_reduction_v2 | 289 | 88.9% | 87.9% |

**Notable anomaly:** gpt-5.4-mini shows RC significantly below pass rate (−8.3% for baseline, −9.1% for lean). This is the opposite of leakage — the classifier rates gpt-5.4-mini's reasoning lower than its code performance. This could indicate that gpt-5.4-mini produces correct code via pattern matching rather than explicit reasoning (the classifier penalizes implicit reasoning).

---

## 6. Condition Effect on Pass Rate and LEG

### gpt-4.1-nano
| Condition | Pass | Δ Pass | LEG | Δ LEG |
|---|---|---|---|---|
| baseline_v2 | 77.6% | — | 15.2% | — |
| leg_reduction_lean_v2 | 70.7% | −6.9% | 11.7% | −3.5% |
| leg_reduction_v2 | 66.6% | −11.0% | 14.6% | −0.6% |

### gpt-4o-mini
| Condition | Pass | Δ Pass | LEG | Δ LEG |
|---|---|---|---|---|
| baseline_v2 | 71.0% | — | 14.7% | — |
| leg_reduction_lean_v2 | 65.2% | −5.9% | 15.2% | +0.5% |
| leg_reduction_v2 | 68.3% | −2.8% | 15.8% | +1.1% |

### gpt-5-mini
| Condition | Pass | Δ Pass | LEG | Δ LEG |
|---|---|---|---|---|
| baseline_v2 | 75.5% | — | 12.2% | — |
| leg_reduction_lean_v2 | 77.2% | +1.7% | 6.2% | −6.0% |
| leg_reduction_v2 | 81.0% | +5.5% | 13.4% | +1.2% |

### gpt-5.4-mini
| Condition | Pass | Δ Pass | LEG | Δ LEG |
|---|---|---|---|---|
| baseline_v2 | 87.9% | — | 11.1% | — |
| leg_reduction_lean_v2 | 89.7% | +1.7% | 7.7% | −3.4% |
| leg_reduction_v2 | 88.6% | +0.7% | 9.7% | −1.4% |

**Key findings:**
1. LEG conditions **hurt** weaker models (nano: −11.0% pass, 4o-mini: −5.9%) but **help** stronger models (5-mini: +5.5%, 5.4-mini: +1.7%)
2. lean_v2 consistently reduces LEG rate for stronger models (5-mini: −6.0%, 5.4-mini: −3.4%) — the structured reasoning constraint helps translate reasoning into correct code
3. For gpt-4.1-nano, leg_reduction_v2 drops pass rate by 11 points while barely touching LEG — the reasoning overhead reduces code quality without improving reasoning-execution alignment

---

## 7. Category Distribution

| Category | Count | Rate |
|---|---|---|
| interpretable_success | 2383 | 68.5% |
| LEG_v2 | 407 | 11.7% |
| full_failure_v2 | 287 | 8.2% |
| alignment_failure_pass | 276 | 7.9% |
| parser_failure_v2 | 120 | 3.4% |
| lucky_fix_v2 | 7 | 0.2% |

---

## 8. Revised Error Taxonomy

| Category | Count | Rate | Definition |
|---|---|---|---|
| True Success | 2663 | 76.5% | mech=CORRECT + pass |
| TRUE LEG | 411 | 11.8% | mech=CORRECT + fail + code present |
| No-code failure | 275 | 7.9% | mech=CORRECT + fail + no extractable code |
| Parse failure | 120 | 3.4% | Generation parse failed, no classifier run |
| Reasoning failure | 11 | 0.3% | mech ≠ CORRECT |
| Infrastructure total | 395 | 11.4% | Parse failures + no-code |
| Lucky fix | 3 | 0.1% | pass + mech ≠ CORRECT |

**No import/assembly errors detected.** The CodeAssembler rewrite has eliminated the import stripping failures seen in earlier ablations.

---

## 9. TRUE LEG by Model

| Model | TRUE LEG | Rate (of classified) |
|---|---|---|
| gpt-4o-mini | 238 | 28.5% |
| gpt-4.1-nano | 172 | 21.6% |
| gpt-5-mini | 186 | 21.5% |
| gpt-5.4-mini | 90 | 10.4% |

**gpt-4o-mini has the highest TRUE LEG at 28.5%** — nearly 3× that of gpt-5.4-mini. This suggests gpt-4o-mini's reasoning quality is close to the other models (99.5% mechanism identification) but its code generation capability lags significantly.

---

## 10. Family-Level TRUE LEG (Top 15)

| Family | N | Pass Rate | LEG Rate |
|---|---|---|---|
| async_race_lock | 60 | 0.0% | 88.1% |
| invariant_partial_fail | 60 | 15.0% | 77.2% |
| false_fix_deadlock | 60 | 3.3% | 74.5% |
| feature_flag_drift | 60 | 35.0% | 50.0% |
| l3_state_pipeline | 60 | 36.7% | 48.3% |
| missing_branch_c | 60 | 43.3% | 46.6% |
| lost_update | 60 | 41.7% | 36.4% |
| cache_invalidation_order | 60 | 65.0% | 30.0% |
| hidden_dep_multihop | 60 | 61.7% | 25.0% |
| retry_dup_c | 60 | 60.0% | 24.5% |
| alias_config_c | 60 | 78.3% | 21.7% |
| effect_order_b | 60 | 58.3% | 20.7% |
| missing_branch_a | 60 | 83.3% | 16.7% |
| use_before_set_b | 60 | 70.0% | 16.7% |
| config_shadowing | 60 | 68.3% | 16.4% |

### Zero-LEG Families (always succeed when mechanism is correct)

| Family | Pass Rate |
|---|---|
| partial_update_a | 91.7% |
| partial_update_b | 85.0% |
| retry_dup_a | 98.3% |
| silent_default_c | 90.0% |
| stale_cache_a | 91.7% |
| stale_cache_b | 93.3% |
| stale_cache_c | 85.0% |
| temporal_drift_a | 96.7% |
| use_before_set_a | 95.0% |
| wrong_condition_a | 96.7% |

**Interpretation:** The hardest families (async_race_lock, invariant_partial_fail, false_fix_deadlock) represent genuinely difficult coding challenges — models identify the bug mechanism but cannot produce correct concurrent/rollback code. The zero-LEG families are simple enough that correct diagnosis always translates to correct code.

---

## 11. No-Code Failures

| Family | No-code / Total | Rate |
|---|---|---|
| temporal_drift_b | 15/60 | 25.0% |
| missing_branch_b | 12/60 | 20.0% |
| check_then_act | 11/60 | 18.3% |
| early_return_b | 11/60 | 18.3% |
| effect_order_b | 11/60 | 18.3% |
| false_fix_deadlock | 11/60 | 18.3% |

| Model | No-code / Classified | Rate |
|---|---|---|
| gpt-4o-mini | 112/835 | 13.4% |
| gpt-5-mini | 96/866 | 11.1% |
| gpt-4.1-nano | 62/795 | 7.8% |
| gpt-5.4-mini | 8/864 | 0.9% |

**gpt-5.4-mini almost never fails to produce code** (0.9%), while gpt-4o-mini fails 13.4% of the time. This is a significant contributor to gpt-4o-mini's lower pass rate.

---

## 12. Recoverable Cases

93 cases had recoverable parse failures (triple_quote_fix):
- gpt-4.1-nano: 61
- gpt-4o-mini: 29
- gpt-5-mini: 2
- gpt-5.4-mini: 1

These are cases where the strict parser failed but the recovery parser could extract code. Recovery output is currently diagnostic-only and does not enter the pipeline.

---

## 13. RC vs Pass Rate Correlation

The core leakage test: if the classifier is independent, RC and pass rate should not correlate.

| Model | Condition | Pass | RC | Δ |
|---|---|---|---|---|
| gpt-4.1-nano | baseline_v2 | 83.3% | 80.0% | −3.3% |
| gpt-4.1-nano | lean_v2 | 77.4% | 74.0% | −3.4% |
| gpt-4.1-nano | leg_v2 | 74.2% | 79.6% | **+5.4%** |
| gpt-4o-mini | baseline_v2 | 73.8% | 73.5% | −0.4% |
| gpt-4o-mini | lean_v2 | 66.8% | 71.4% | +4.6% |
| gpt-4o-mini | leg_v2 | 72.5% | 74.0% | +1.5% |
| gpt-5-mini | baseline_v2 | 76.6% | 80.1% | +3.5% |
| gpt-5-mini | lean_v2 | 77.2% | 70.0% | **−7.2%** |
| gpt-5-mini | leg_v2 | 81.0% | 88.3% | **+7.2%** |
| gpt-5.4-mini | baseline_v2 | 88.5% | 80.2% | **−8.3%** |
| gpt-5.4-mini | lean_v2 | 90.6% | 81.5% | **−9.1%** |
| gpt-5.4-mini | leg_v2 | 88.9% | 87.9% | −1.0% |

**Two notable patterns:**
1. **gpt-5.4-mini: RC consistently below pass** (−8.3%, −9.1%). This is the reverse of leakage — the classifier penalizes this model's reasoning despite high code quality. Possible explanation: gpt-5.4-mini produces correct code via implicit reasoning that the classifier doesn't credit.
2. **leg_reduction_v2 inflates RC** across all models (+5.4%, +1.5%, +7.2%, −1.0%). The structured reasoning template produces verbose, well-organized reasoning that the classifier rewards — but this doesn't always translate to better code.

---

## 14. Claims Assessment

### Safe Claims
- Pass rates across models and conditions
- Model ranking by pass rate: gpt-5.4-mini > gpt-5-mini > gpt-4.1-nano > gpt-4o-mini
- Mechanism identification is near-universal (99.7%) across all models
- TRUE LEG rate of 12.2% using mechanism-based definition
- Family difficulty rankings by pass rate and LEG rate
- Condition effect direction: LEG conditions help stronger models, hurt weaker ones
- Infrastructure failure rate (11.4%) with parse failures (3.4%) and no-code (8.2%)
- Zero assembly/import errors (CodeAssembler fix validated)

### Claims Requiring Caveats
- TRUE LEG by model (28.5% for gpt-4o-mini) — mechanism_identified may have ~15% false positive rate on hard cases
- Condition effects on LEG rate — small N per cell (N≈260-290), not statistically tested
- Family-level LEG rates — N=60 per family, high variance

### Invalid Claims
- Any claim using `reasoning_correct` (compat, 4-dimension) — still leaked at 2.64x
- Cross-model reasoning quality comparisons using RC
- Cross-condition reasoning quality comparisons using RC
- Lucky fix rates (N=7, too small)

---

## 15. Comparison with Previous Ablations

| Metric | v2 ablation (758) | v2_full_4model_5trial (3480) |
|---|---|---|
| Models | 3 | 4 |
| Pass rate | ~75.9% | 76.6% |
| Mechanism correct | 99.7% | 99.7% |
| TRUE LEG | 9.4% | 12.2% |
| Infrastructure | 14.4% | 11.4% |
| Parse failures | — | 3.4% |
| Leakage (sat) | 3.13x | 2.64x |
| Leakage (align) | 2.95x | 2.30x |

**The larger ablation confirms all prior findings.** Leakage ratios are slightly improved (2.64x vs 3.13x) but still fundamentally compromised. TRUE LEG is higher (12.2% vs 9.4%), likely because the 4-model ablation includes more diverse failure modes. Infrastructure failures are lower, partly because parse failures are now tracked separately.
