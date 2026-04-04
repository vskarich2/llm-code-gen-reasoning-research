# Forensic Audit of LEG Effect Report

**Date**: 2026-03-31
**Target**: `analysis/leg_effect_canonical_report.md`
**Data**: 28,637 evals across 13 ablation runs, 8 models, 58 cases
**Auditor**: Claude (adversarial mode)

---

## 1. TRUST ASSESSMENT

**Medium-High confidence.** The core numerical claims are verified. The statistical methods are sound. But three systemic issues reduce confidence in specific interpretive claims.

**% of results likely valid**: ~75-80% of factual claims hold exactly. ~15% are inflated by LEG rate inflation (see below). ~5-10% are unsupported by the invariant tests they claim to validate.

---

## 2. CLAIM VALIDITY TABLE

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | LEG helps on high-LEG-rate cross-boundary cases | **SUPPORTED** | Recomputed pass rates match within 3pp. Fisher exact tests verified. All 10 strongest results survive global Bonferroni (p < 0.00012). |
| 2 | Lean outperforms full LEG for strong models | **SUPPORTED** | Consistent across S4.6, GPT-5, 5-mini. Exception: Haiku 4.5 where LEG > lean. |
| 3 | Full LEG outperforms lean for weak models | **SUPPORTED** | Haiku 4.5 data shows LEG p=0.002 vs lean p=0.142. |
| 4 | Reconstruction artifacts inflate/deflate apparent LEG effects | **SUPPORTED** | Reconstruction rate: baseline 88.8%, LEG 86.3%, lean 83.1%. LEG makes parsing HARDER, not easier. Multiple cases verified where strict delta ≠ recon-only delta. |
| 5 | LEG never harms models with high baseline LEG rate | **SUPPORTED** | 0/17 high-LEG pairs show significant harm. Verified from raw logs. |
| 6 | feature_flag_drift 0%→100% is genuine reasoning improvement | **PARTIALLY SUPPORTED** | The pass rate improvement is real and verified. BUT the test has a weakness: hardcoded `base*qty*0.9` passes without flag propagation. The test validates behavior, not mechanism. The 100% LEG rate at baseline IS genuine (behavioral failure). But the 100% pass under lean doesn't conclusively prove the model learned flag propagation — it may have learned to hardcode the formula. |
| 7 | invariant_partial_fail lean converts LEGs to passes via strategy selection | **SUPPORTED** | Log analysis verified. Baseline uses debit-then-fail (no rollback). Lean uses fail-before-mutate (no mutation before check). Both strategies are valid; lean causes the model to select the working one. |
| 8 | LEG rate = 98.8% of failures have mc=True | **SUPPORTED BUT MISLEADING** | See Section 3.1 below. The classifier assigns mc=True 99.5% of the time across ALL evals. This is not "models almost always reason correctly" — it's "the classifier almost never says False." |
| 9 | Lucky fixes are negligible (0.1%) | **SUPPORTED as consequence of #8** | Lucky fix = mc=False AND pass=True. Since mc=False is only 0.5% of all evals, lucky fixes are mechanically bounded at ~0.5%. This is a ceiling effect, not a benchmark property. |
| 10 | 6.1% soft lucky rate is meaningful | **SUPPORTED** | PARTIAL dimensions on passing samples are a genuine signal. Verified stable across strict/recon-only. |
| 11 | Config_shadowing trap fix detection works | **SUPPORTED** | Anti-hardcoding probe verified: mutates DEFAULTS to 99, checks propagation. Trap fix correctly fails. |
| 12 | GPT-5 solves false_fix_deadlock at 90% | **SUPPORTED** | Verified from raw logs: 45/50 pass. |
| 13 | Pooled GEE results are unbiased | **PARTIALLY REFUTED** | 324 (case, model, condition) keys appear in 2 sources (10-trial full + 50-trial targeted). Targeted cases have 6x the data, biasing the GEE toward LEG-sensitive cases. |

---

## 3. ROOT CAUSES OF CONCERN (ranked)

### 3.1 CRITICAL: The Classifier Says mc=True 99.5% of the Time

**Finding**: mechanism_correct is True for 16,105 out of 16,182 classified evals (99.5%). Only 77 evals get mc=False across the entire dataset.

**Breakdown by quadrant**:
- Recon success + exec pass: mc=True 99.9% (expected — correct code, correct reasoning)
- Recon success + exec fail: mc=True 98.7% (the LEG phenomenon)
- Recon fail + exec fail: mc=True 99.0% (classifier can't see code, still says True)

**The problem**: mc=True on reconstruction failures (99.0%) proves the classifier is rating reasoning INDEPENDENTLY of code quality — which is good for independence, but also means the classifier is almost never saying the reasoning is wrong. The 99.5% True rate means mechanism_correct has almost no discriminative power. It's essentially a constant.

**Impact on LEG definition**: LEG = mc=True AND pass=False. If mc=True is a near-constant (99.5%), then LEG rate ≈ failure rate. The "reasoning-execution gap" may just be "failure rate rebranded."

**Mitigation**: The report already computes LEG rates and pass rates separately. The LEG conversion analysis (LEG rate drops AND pass rate rises) is valid regardless of the classifier's baseline rate, because it measures CHANGE. The absolute LEG rates are less meaningful than the deltas.

**Severity**: HIGH for interpretive claims about "models that understand but can't code." MEDIUM for LEG conversion claims (deltas are valid). LOW for pass rate claims (unaffected).

### 3.2 HIGH: LEG Rate Inflation from Reconstruction Failures

**Finding**: Strict LEG rates are inflated compared to genuine LEG rates (recon-only failures) on several cases:

| Case | Strict LEG | Genuine LEG | Inflation |
|---|---|---|---|
| check_then_act | 41% | 17% | +24pp |
| temporal_drift_b | 22% | 0% | +22pp |
| missing_branch_b | 16% | 1% | +16pp |
| early_return_a | 10% | 0% | +10pp |
| partial_update_c | 21% | 10% | +11pp |

When reconstruction fails, the code can't execute, so pass=False. But the classifier still sees the reasoning (root_cause, fix_strategy) and rates it as mc=True. This creates phantom LEG: the model may have produced correct code that couldn't be parsed, but it's counted as "reasoning correct, execution failed."

**Impact**: Strict LEG rates overstate the reasoning-execution gap. The report addresses this with recon-only analysis but some narrative claims use strict LEG rates without qualification.

**Cases unaffected** (strict ≈ genuine within 5pp): invariant_partial_fail, config_shadowing, cache_invalidation_order, lost_update, hidden_dep_multihop, wrong_condition_b. These are the cases where the LEG finding is most robust.

### 3.3 HIGH: feature_flag_drift Test Does Not Validate Mechanism

**Finding**: A hardcoded implementation that bypasses the flag system entirely passes the test:
```python
def checkout(customer, items, use_new_pricing=False):
    total = sum(item["base"] * item["qty"] * (0.9 if use_new_pricing and item["qty"]>=10 else 1) for item in items)
    return {"total": total}
```

The test checks `total == 900` (behavior) but not that the flag was propagated through `compute_price` → `_v2_price` → `is_enabled("new_pricing")` (mechanism).

**Impact**: The feature_flag_drift results (S4.6 0%→100% lean, H4.5 2%→100% LEG) cannot be interpreted as "models learned flag propagation." They can only be interpreted as "models learned to produce correct output values." The behavioral improvement is real; the mechanism claim is unsupported by the test.

**Severity**: HIGH for the specific claim that LEG teaches flag propagation. LOW for the general claim that LEG improves pass rates.

### 3.4 MEDIUM: Cross-Source Data Overlap Biases Pooled GEE

**Finding**: 324 (case, model, condition) keys appear in both the 10-trial full run and the 50-trial targeted runs. The 13 targeted cases have 60 trials each vs 10 for the other 45 cases. The GEE clusters by case_id, so targeted cases get 6x the weight.

**Impact**: The pooled GEE in Section 15.10 (21,360 evals) is biased toward LEG-sensitive cases. The LEG × 5-mini interaction (+0.860, p=0.001) may be inflated because the cases where 5-mini benefits from LEG are over-represented.

**Severity**: MEDIUM. The per-ablation analyses (which don't pool) are unaffected. The pooled GEE should be interpreted with this caveat.

### 3.5 MEDIUM: Trial Independence at Temperature 0

**Finding**: 40-74% of (case, model, condition) keys show variance across 50 trials despite temperature=0. This means trials are NOT deterministic — there IS randomness — but it comes from provider-side noise, not the experimental design.

**Impact**: Fisher exact tests treat each trial as independent. If there's autocorrelation (e.g., batched API calls producing correlated outputs), p-values may be too small. With 50 trials and variance confirming non-determinism, the independence assumption is approximately valid but not guaranteed.

**Severity**: MEDIUM. The strongest results (p < 0.000001) have enough margin that moderate autocorrelation wouldn't change significance. Marginal results (p = 0.01-0.05) could be affected.

---

## 4. WHAT SURVIVES

After the audit, the following findings remain robust:

1. **LEG/lean improves pass rates on invariant_partial_fail** across GPT-5, Sonnet 4.6, and 5-mini. The effect is Bonferroni-significant, recon-verified, and the mechanism (strategy selection) is confirmed by log analysis. This is the strongest single finding.

2. **LEG/lean improves pass rates on cache_invalidation_order × nano** (+56pp, recon-verified, Bonferroni). Strict and genuine LEG rates match (66% vs 64%). Real effect.

3. **LEG harms alias_config_c × nano** (-92pp, recon-verified, Bonferroni). Models that solve the case at baseline are destroyed by LEG format overhead.

4. **LEG harms config_shadowing × 5.4-mini** (-44pp, recon-verified). The strongest model on this case is degraded by scaffolding.

5. **Lean is generally safer than full LEG** for strong models. Full LEG is better for weak models (Haiku 4.5). This pattern is consistent across all data.

6. **Reconstruction artifacts account for 40% of failures** in the GPT pipeline. 5-mini has the highest reconstruction failure rate among capable models (56% of its failures).

7. **The LEG conversion mechanism** (LEG rate drops proportionally as pass rate rises) is genuine and not a statistical artifact. The 1:1 conversion on cases like commit_gate, invariant_partial_fail, and feature_flag_drift is too consistent to be noise.

8. **Lucky fixes are negligible** — but this is partly because the classifier almost never says mc=False, not because models never produce lucky fixes. The 0.1% rate is a ceiling imposed by classifier leniency.

---

## 5. WHAT IS COMPROMISED

1. **Absolute LEG rates** (e.g., "96% LEG rate at baseline") should not be interpreted as "96% of the time the model reasons correctly." The classifier assigns mc=True 99.5% of the time. The LEG rate is better understood as "failure rate × 0.995."

2. **feature_flag_drift mechanism claims** — the test doesn't validate flag propagation. The 0%→100% improvement is behaviorally real but mechanistically unverified.

3. **Pooled GEE significance values** — biased by cross-source overlap toward LEG-sensitive cases. Per-ablation results are reliable.

4. **Strict LEG rates on check_then_act, temporal_drift_b, missing_branch_b** — inflated by 10-24pp due to reconstruction failures being counted as LEG. Use genuine (recon-only) LEG rates for these cases.

5. **Haiku 3 LEG rates** — based on only ~10% of samples (90% have mc=None due to parse failures). Unreliable.

---

## 6. ACTIONABLE FIXES

### Immediate (before publication)

1. **Add caveat to all mc=True interpretations**: State that the classifier assigns mc=True 99.5% of the time, limiting its discriminative power. LEG rates should be presented alongside this baseline rate.

2. **Report genuine LEG rates alongside strict LEG rates**: Add a column showing LEG rate computed only on reconstruction-successful samples.

3. **Flag feature_flag_drift test weakness**: Note that the test validates behavior, not mechanism. Add a mechanism check (verify `_flags` dict was modified during execution) or caveat the claim.

4. **Separate pooled GEE from per-ablation GEE**: Note the cross-source overlap and its bias direction. Report per-ablation results as primary.

### Before next ablation

5. **Recalibrate the classifier**: The 99.5% mc=True rate suggests the classifier's threshold for "mechanism correct" is too low. Consider adding adversarial probes where the reasoning is deliberately wrong to verify the classifier can detect it.

6. **Add mechanism-specific test checks**: For feature_flag_drift, add a check that the flag system was actually used (e.g., verify `_flags["new_pricing"]` was set and unset during execution).

7. **Deduplicate cross-source data before pooling**: When running pooled analyses, use only the highest-trial-count source per (case, model, condition) key.

### Longer term

8. **Develop a "classifier sensitivity" metric**: What % of deliberately-wrong reasoning does the classifier catch? This establishes the classifier's false negative rate and bounds the interpretability of mc=True.

9. **Run the classifier on adversarial inputs**: Feed the classifier reasoning that describes the wrong bug mechanism and verify it returns mc=False. If it still returns mc=True, the classifier needs fundamental recalibration.
