# Global Calibration Ablation — Plan v1

**Date**: 2026-04-01
**Goal**: Map the distribution of intervention regimes across the full benchmark at low cost.

This stage estimates WHERE LEG resolution mechanisms matter, not just HOW they work.

---

## 1. Scope Definition

| Dimension | Count |
|-----------|-------|
| Cases | 58 |
| Models | 8 (excluding claude-3-haiku, >80% UNJUDGABLE) |
| Valid case × model pairs (≥10 baseline trials) | 236 |
| Pairs already tested with critique/r-only | 27 |
| **NEW pairs to test** | **211** |

### Models

claude-haiku-4-5, claude-sonnet-4, claude-sonnet-4-6, gpt-4.1-nano, gpt-4o-mini, gpt-5, gpt-5-mini, gpt-5.4-mini

### Runs Required

New events: 211 pairs × 3 new arms × 10 trials = **6,330 events**

Baseline data already exists for all 236 pairs from the main oracle intervention dataset (22K events). We do NOT rerun baseline. We reuse existing baseline pass rates from oracle-labeled data.

Total new generation calls: 6,330
Total new classifier calls: 6,330
**Total new API calls: ~12,660**

### Cost

~$190 generation + classification. ~2-3 minutes wall time at 200 workers per model.

---

## 2. Experimental Design

### Arms

| Arm | Condition | Source |
|-----|-----------|--------|
| Baseline | baseline_v2 | EXISTING DATA (oracle-labeled, 22K events) |
| Bare retry | retry_bare_retry_v2 | NEW (10 trials) |
| Critique | retry_leg_critique_strict_v2 | NEW (10 trials), or EXISTING for 27 pairs |
| Reasoning-only | retry_reasoning_only_critique_v1 | NEW (10 trials), or EXISTING for 18 pairs |

### Trial Count: 10

**Why 10 is sufficient for regime classification:**
- At 10 trials, a pass rate of 0% vs 30% is detectable (0/10 vs 3/10). The regime classification threshold is 2/10 (20pp), which requires a minimum detectable effect that 10 trials can distinguish from zero.
- The classification bins are coarse (5 regimes). We are not computing p-values per pair. We are binning into broad categories where ±15pp noise is acceptable.
- At 10 trials with p=0.5, the 95% CI is ±31pp. This means individual pair classifications have substantial uncertainty. But when aggregated across 236 pairs, the regime distribution estimate is much tighter (±3-5pp by CLT).

**Why 10 is NOT sufficient for per-pair statistical claims:**
- Cannot distinguish 20% from 40% pass rate reliably (2/10 vs 4/10, Fisher p=0.63).
- Individual pair classifications are noisy. Any specific pair's regime label has ~30% misclassification probability at borderline effects.
- Per-pair claims require N≥40 (from Stage B power rules).

### Randomization

- Trials 1-10 with fixed seed=42 (same as all prior ablations).
- Temperature=0 for all generation models. Provider-side variance is the only randomization source (verified: 40-74% of pairs show trial variance at temp=0).

### Integration with Existing Data

For the 27 pairs already tested (from Stage B/C):
- Use existing critique and reasoning-only data (50-90 trials).
- Compute pass rates from existing data. Do NOT rerun.
- These pairs serve as internal calibration: their regime classification at N=10 (subsampled) vs N=50+ tests the classifier's noise level.

---

## 3. Metrics per Case × Model Pair

For each of the 236 pairs, compute:

| Metric | Definition |
|--------|-----------|
| pass_base | P(pass \| baseline) from oracle intervention data |
| pass_retry | P(pass \| bare_retry) from new 10-trial data |
| pass_crit | P(pass \| critique) from new 10-trial data |
| pass_ro | P(pass \| reasoning_only) from new 10-trial data |
| Δ_retry | pass_retry - pass_base |
| Δ_crit | pass_crit - pass_base |
| Δ_ro | pass_ro - pass_base |
| best_arm | argmax(pass_base, pass_retry, pass_crit, pass_ro) |
| regime | Classification per Section 4 |

Also carry forward from oracle data:
| Metric | Source |
|--------|-------|
| P(CORRECT) | Oracle intervention labels |
| P(pass \| CORRECT) | Oracle intervention labels |
| LEG_rate | Oracle intervention labels |
| cluster | From case regime taxonomy (Section 5.C) |

---

## 4. Regime Classification Rules

**Threshold: T = 2/10 = 20pp**

At 10 trials, a 20pp difference means ≥2 additional passes. This is the minimum meaningful signal at this sample size.

### Classification Logic (applied in order)

**1. No Effect**
```
max(Δ_retry, Δ_crit, Δ_ro) < T
```
No arm improves over baseline by ≥20pp.

**2. Retry-Dominant (exploration)**
```
Δ_retry ≥ T
AND Δ_crit < Δ_retry + T
AND Δ_ro < Δ_retry + T
```
Retry improves, and neither critique nor reasoning-only substantially exceeds retry.

**3. Critique-Dominant (execution alignment)**
```
Δ_crit ≥ T
AND Δ_crit ≥ Δ_ro + T
```
Critique improves AND beats reasoning-only by ≥20pp.

**4. Reasoning-Only Dominant (interference)**
```
Δ_ro ≥ T
AND Δ_ro ≥ Δ_crit + T
```
Reasoning-only improves AND beats critique by ≥20pp.

**5. Intervention-Equivalent (critique ≈ reasoning-only)**
```
Δ_crit ≥ T AND Δ_ro ≥ T
AND |Δ_crit - Δ_ro| < T
```
Both critique and reasoning-only help, and they are within 20pp of each other.

**6. Ceiling**
```
pass_base ≥ 0.9
```
Baseline already near-perfect. No room for improvement. Classified separately.

These rules are mutually exclusive when applied in order. If a pair falls through all rules (should not happen), classify as "unclassifiable."

---

## 5. Aggregations

### A. Global Distribution

| Regime | Count | % of pairs |
|--------|-------|-----------|
| No effect | | |
| Ceiling | | |
| Retry-dominant | | |
| Critique-dominant | | |
| Reasoning-only dominant | | |
| Intervention-equivalent | | |

### B. By Model

| Model | No effect | Ceiling | Retry | Critique | R-only | Equivalent |
|-------|-----------|---------|-------|----------|--------|------------|

One row per model. Shows whether intervention sensitivity is model-specific.

### C. By Case Cluster

Using the existing taxonomy from the case breakdown:
- **Severe LEG** (2 cases): feature_flag_drift, false_fix_deadlock
- **Moderate LEG** (10 cases): check_then_act, overdetermination, missing_branch_c, etc.
- **Partial-dominated** (2 cases): invariant_partial_fail, config_shadowing
- **Reasoning-limited** (2 cases): l3_state_pipeline, async_race_lock
- **Lucky fix** (4 cases): cache_invalidation_order, use_before_set_a, etc.
- **Capable** (38 cases): the majority

These cluster labels are derived from the oracle-labeled baseline data (P(CORRECT), P(pass|CORRECT), P(pass|WRONG)).

| Cluster | N_pairs | No effect | Ceiling | Retry | Critique | R-only | Equivalent |
|---------|---------|-----------|---------|-------|----------|--------|------------|

---

## 6. Connection to LEG

This ablation connects intervention regimes to LEG prevalence:

For each pair, we have BOTH:
- LEG rate from oracle labels (P(CORRECT AND fail))
- Intervention regime from this ablation

This allows:

**Cross-tabulation: LEG severity × intervention regime**

| | LEG > 30% | LEG 10-30% | LEG < 10% | LEG ≈ 0% |
|---|---|---|---|---|
| No effect | | | | |
| Retry-dominant | | | | |
| Critique-dominant | | | | |
| R-only dominant | | | | |
| Equivalent | | | | |

This answers: **When LEG is present, which resolution mechanism works?**

If critique-dominant is concentrated in high-LEG pairs → critique specifically resolves LEG.
If critique-dominant appears in low-LEG pairs → critique helps for other reasons (e.g., code quality improvement unrelated to reasoning).

---

## 7. Interpretation Plan

| Outcome | Conclusion |
|---------|-----------|
| >50% of pairs are "no effect" or "ceiling" | Interventions matter only for a minority of the benchmark. Focus resources on that minority. |
| >30% are retry-dominant | A second attempt alone is the primary intervention. Critique overhead is unjustified for most cases. |
| >20% are critique-dominant | Execution alignment via code-mismatch feedback is a broadly useful mechanism. Worth productizing. |
| >20% are reasoning-only dominant | Constraint interference from code-mismatch feedback is widespread. The full critique is actively harmful in many cases. |
| Critique-dominant concentrates in severe/moderate LEG | Critique is a targeted LEG resolution tool. Should be deployed selectively, not universally. |
| Regimes distribute evenly across clusters | No single intervention strategy is optimal. Adaptive selection is needed. |
| Strong model-dependence | Intervention effectiveness is a property of the model, not the case. Route by model capability. |

---

## 8. Risks / Failure Modes

### 8.1 Low-N Variance
At 10 trials, individual pair classifications have ~30% error rate at borderline effects. A pair with true pass rate 25% (critique) could appear as 0/10 or 5/10.

**Mitigation**: Aggregated regime distributions are stable (236 pairs × 10 trials = 2,360 observations per arm). Individual pair labels are noisy; the distribution is not.

### 8.2 Threshold Sensitivity
The 20pp threshold (T=2/10) is coarse. A 15pp true effect will often be classified as "no effect."

**Mitigation**: Report regime distributions at T=10pp (1/10) and T=30pp (3/10) as sensitivity analysis. If conclusions change substantially, the threshold is driving results.

### 8.3 Uneven Case Difficulty
Easy cases (38 "capable" cases) dominate the benchmark. If most are ceiling, the regime distribution will be dominated by "no effect / ceiling" regardless of intervention power.

**Mitigation**: Report regime distributions BOTH globally AND within each cluster. The cluster-level distribution is more informative than the global one.

### 8.4 Model Instability
Some models (4o-mini, nano) show high variance across trials even at temp=0. At N=10, this produces noisy pass rate estimates.

**Mitigation**: The regime classification uses coarse bins (20pp). Model instability of ±10pp is within the noise band and will not systematically bias regime distribution.

### 8.5 Misclassification of Ties
When multiple arms perform similarly (within 20pp), the regime classification defaults to "no effect" or "equivalent." True differences may be masked.

**Mitigation**: Report the number of pairs within 10pp of a threshold boundary. If >30% of pairs are borderline, the classification is too coarse and the threshold should be tightened (requiring more trials).

### 8.6 Baseline Reference Mismatch
Baseline pass rates come from existing oracle data (50 trials). New intervention arms have 10 trials. The precision asymmetry means Δ estimates are dominated by treatment-arm noise.

**Mitigation**: This is acceptable for regime classification (coarse bins). Not acceptable for effect size estimation.

---

## 9. Follow-Up Plan

After this calibration ablation:

### Step 1: Review Regime Distribution
Identify which regimes contain the most pairs. Determine whether the Stage B findings (17% critique-dominant, 28% retry-dominant, 33% no-effect) generalize.

### Step 2: Select Representative Pairs
From each regime, select 3-5 representative pairs that span different cases and models.

### Step 3: Confirmatory Experiments (N=50)
Run 50-trial ablations ONLY on the selected representative pairs. This provides statistical power for per-pair claims.

**Do NOT rerun the full 236 pairs at N=50.** That is wasteful. The calibration ablation identifies WHERE to invest; the confirmatory experiments invest there.

### Step 4: Final Analysis
Combine:
- Global regime distribution (from calibration, N=10)
- Per-pair effect sizes (from confirmatory, N=50)
- LEG decomposition (from Stage A transition matrix)

This produces the final dataset for the paper.
