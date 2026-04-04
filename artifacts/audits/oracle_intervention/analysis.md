# Oracle Intervention Ablation — Full Results

**Date**: 2026-04-01
**Total matched events**: 22323

## 0. Oracle Reliability

- A vs A2 (stochasticity): 98.0%
- A vs B (prompt sensitivity): 88.0%
- Cohen's kappa (A vs B): 0.555

## 1. Pooled Intervention Summary (Table 1)

| Cond | N | CORRECT | PARTIAL | WRONG | UNJDG | Pass | P\|C | P\|P | P\|W | StrictLEG | SoftLEG | Lucky |
|------|---|---------|---------|-------|-------|------|------|------|------|-----------|---------|-------|
| base | 7441 | 81.1% | 10.2% | 8.6% | 4.4% | 63.5% | 77.3% | 14.1% | 25.7% | 18.4% | 27.2% | 2.2% |
| LEG | 7441 | 81.7% | 10.5% | 7.7% | 5.8% | 64.8% | 80.0% | 14.7% | 23.6% | 16.3% | 25.3% | 1.8% |
| lean | 7441 | 81.0% | 10.9% | 8.0% | 4.7% | 65.2% | 77.7% | 27.4% | 29.6% | 18.1% | 26.0% | 2.4% |

## 2. Intervention Deltas (Table 2)

| Comparison | Δ Pass | Δ CORRECT | Δ P\|C | Δ P\|P | Δ SoftLEG | Δ Lucky |
|------------|--------|-----------|--------|--------|-----------|---------|
| base→LEG | +1.2% | +0.6% | +2.7% | +0.5% | -1.9% | -0.4% |
| base→lean | +1.6% | -0.1% | +0.4% | +13.3% | -1.2% | +0.1% |
| LEG→lean | +0.4% | -0.7% | -2.3% | +12.8% | +0.7% | +0.5% |

## 3. Core Tests A–D (Table 3)

### base→LEG

| Test | N_eff | Δ Pass | McNemar p | 95% CI |
|------|-------|--------|-----------|--------|
| A concordant-C | 5432 | +2.5% | 7.0e-05 | [+1.3%, +3.7%] |
| B baseline-C | 5775 | -0.7% | 0.2589 | [-1.9%, +0.5%] |
| C concordant-CP | 6263 | +2.2% | 2.3e-04 | [+1.0%, +3.3%] |
| D baseline-CP | 6503 | +0.6% | 0.3046 | [-0.6%, +1.7%] |

### base→lean

| Test | N_eff | Δ Pass | McNemar p | 95% CI |
|------|-------|--------|-----------|--------|
| A concordant-C | 5399 | +0.9% | 0.1228 | [-0.3%, +2.1%] |
| B baseline-C | 5775 | -1.4% | 0.0209 | [-2.5%, -0.2%] |
| C concordant-CP | 6287 | +1.9% | 9.0e-04 | [+0.8%, +3.0%] |
| D baseline-CP | 6503 | +0.6% | 0.3239 | [-0.6%, +1.7%] |

### LEG→lean

| Test | N_eff | Δ Pass | McNemar p | 95% CI |
|------|-------|--------|-----------|--------|
| A concordant-C | 5392 | -2.1% | 4.9e-04 | [-3.2%, -0.9%] |
| B baseline-C | 5728 | -3.9% | 9.6e-11 | [-5.1%, -2.8%] |
| C concordant-CP | 6254 | -0.7% | 0.2259 | [-1.8%, +0.4%] |
| D baseline-CP | 6465 | -1.8% | 0.0014 | [-2.9%, -0.7%] |

## 4. Reasoning Stability

| Comparison | N | Stay CORRECT | → PARTIAL | → WRONG | → UNJDG |
|------------|---|-------------|-----------|---------|---------|
| base→LEG | 5775 | 94.1% | 2.9% | 0.5% | 2.5% |
| base→lean | 5775 | 93.5% | 3.7% | 0.9% | 1.9% |
| LEG→lean | 5728 | 94.1% | 3.3% | 0.9% | 1.7% |

## 5. UNJUDGABLE Shift

- baseline_v2: 4.4%
- leg_reduction_v2: 5.8%
- leg_reduction_lean_v2: 4.7%
- Δ base→LEG: +1.5%
- Δ base→lean: +0.3%

## 6. Reconstruction Control (Table 5)

| Comp | Strict Δ Pass | Recon Δ Pass | Strict Δ P\|C | Recon Δ P\|C | \|S−R\| | Sensitive? |
|------|--------------|-------------|-------------|------------|--------|-----------|
| base→LEG | +1.2% | +4.3% | +2.7% | +5.8% | 3.0% |  |
| base→lean | +1.6% | +5.3% | +0.4% | +5.2% | 3.7% |  |
| LEG→lean | +0.4% | +1.1% | -2.3% | -0.7% | 0.7% |  |

## 7. Per-Model Regime (Table 4)

| Model | N | P(C) | P(P\|C) | Regime | Δ Pass(lean) | Δ C(lean) | UNJDG% | Excl? |
|-------|---|------|---------|--------|-------------|----------|--------|-------|
| claude-3-haiku-20240307 | 756 | 0.0% | — | reasoning-limited | -50.0% | +50.0% | 91.1% | YES |
| claude-haiku-4-5-20251001 | 750 | 66.4% | 15.1% | execution-limited | +20.8% | -7.6% | 0.0% |  |
| claude-sonnet-4-20250514 | 900 | 63.7% | 78.5% | capable | +16.7% | +3.0% | 0.0% |  |
| claude-sonnet-4-6 | 1200 | 87.0% | 63.2% | execution-limited | +20.5% | -1.7% | 0.0% |  |
| gpt-4.1-nano | 4233 | 81.9% | 74.4% | capable | +2.0% | -6.5% | 5.3% |  |
| gpt-4o-mini | 4533 | 77.4% | 61.4% | execution-limited | -7.7% | +3.1% | 4.0% |  |
| gpt-5 | 750 | 59.2% | 95.9% | capable | +8.4% | -0.8% | 0.0% |  |
| gpt-5-mini | 4533 | 84.6% | 86.0% | capable | +1.7% | +3.5% | 0.1% |  |
| gpt-5.4-mini | 4668 | 90.2% | 93.2% | capable | +1.0% | -1.2% | 0.1% |  |

## 8. Exclusion Sensitivity

Excluded models: ['claude-3-haiku-20240307']

## 9. LEG Conversion Matrix (Table 6)

| Condition | P(pass\|C) | P(pass\|P) | P(pass\|W) | N_C | N_P | N_W |
|-----------|-----------|-----------|-----------|-----|-----|-----|
| base | 77.3% | 14.1% | 25.7% | 5775 | 728 | 614 |
| LEG | 80.0% | 14.7% | 23.6% | 5728 | 737 | 543 |
| lean | 77.7% | 27.4% | 29.6% | 5748 | 776 | 568 |