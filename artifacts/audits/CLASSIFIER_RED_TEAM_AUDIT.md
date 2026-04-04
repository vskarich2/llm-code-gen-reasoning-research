# Classifier Red-Team Audit

**Date:** 2026-03-30
**Dataset:** v2 ablation (758 events, 3 models, 3 conditions)
**Classifier:** classify_reasoning_v2.j2 via evaluator_v2.py
**Evaluator model:** gpt-5-mini

---

## 1. Executive Verdict

**The current classifier CANNOT be trusted for reasoning_correct claims. It can be trusted for mechanism_identified claims only.**

The `commitments_satisfied` and `reasoning_code_alignment` dimensions are **fatally contaminated by code-correctness leakage**. They are 3.1x and 2.9x more likely to rate CORRECT when code passes execution tests, despite the classifier prompt explicitly stating "You are NOT evaluating code correctness." Since `reasoning_correct` is derived from ALL four dimensions, it inherits this contamination.

`mechanism_identified` is clean (1.01x leakage ratio) and should be used as the primary reasoning quality signal. The other three dimensions should be downgraded from research metrics to diagnostic signals.

---

## 2. Failure Inventory

### SEVERITY 1 — CRITICAL

**F1: Code-correctness leakage in commitments_satisfied (3.13x ratio)**
- P(CORRECT | code_pass) = 90.4%
- P(CORRECT | code_fail) = 28.9%
- The classifier is 3x more likely to say commitments are satisfied when code passes
- This is the dominant factor in reasoning_correct derivation
- Impact: LEG rate is SUPPRESSED (LEG requires reasoning_correct=True AND code_fail, but commitments_satisfied tracks code_fail, making reasoning_correct=False when code fails)

**F2: Code-correctness leakage in reasoning_code_alignment (2.95x ratio)**
- P(CORRECT | code_pass) = 90.6%
- P(CORRECT | code_fail) = 30.7%
- Same mechanism as F1 — the classifier sees the code and infers whether it works
- Impact: same as F1, compounds the bias

**F3: 166 false negatives (21.9%) — mechanism=CORRECT but reasoning_correct=False**
- 107 caused by commitments_satisfied=WRONG
- 100 caused by alignment=WRONG
- The classifier says the model identified the right bug mechanism, but the derivation says reasoning is wrong because the code doesn't satisfy the commitments
- These are cases where the model REASONED CORRECTLY but CODED INCORRECTLY — the exact definition of LEG
- The classifier's leaky dimensions prevent these from being classified as LEG

### SEVERITY 2 — HIGH

**F4: mechanism_identified at ceiling (99.7%)**
- The classifier almost NEVER rates mechanism as WRONG
- This means mechanism_identified has no discriminative power between models
- It cannot distinguish good from bad reasoning — only from absent reasoning
- Impact: cross-model reasoning quality comparisons are meaningless using mechanism alone

**F5: Condition bias is entirely explained by pass rate**
- baseline_v2: 78.1% RC, 79.4% pass
- leg_v2: 74.8% RC, 74.8% pass
- lean_v2: 73.9% RC, 73.5% pass
- The RC rate tracks the pass rate within 1%. This is not independent measurement — it's reflection.

### SEVERITY 3 — MODERATE

**F6: Family-level bias — partial_rollback under-credited**
- partial_rollback: 75% pass, but only 53% RC and 50% commitments_satisfied
- Compare: alias_config: 86% pass, 92% RC
- The 22-point gap between pass and RC for partial_rollback suggests the classifier struggles with rollback-style reasoning

**F7: missing_branch over-credited on mechanism**
- 100% mechanism=CORRECT but only 64% pass
- 36% of cases have correct mechanism identification but failing code
- This is the highest LEG family — but only if you trust mechanism alone

---

## 3. Bias Analysis

### Code-Correctness Leakage (CRITICAL)

| Dimension | P(CORRECT\|pass) | P(CORRECT\|fail) | Ratio | Verdict |
|---|---|---|---|---|
| mechanism_identified | 100.0% | 98.8% | 1.01x | CLEAN |
| commitments_extracted | 99.6% | 97.6% | 1.02x | CLEAN |
| commitments_satisfied | 90.4% | 28.9% | **3.13x** | **FATALLY LEAKED** |
| reasoning_code_alignment | 90.6% | 30.7% | **2.95x** | **FATALLY LEAKED** |

**Root cause:** The classifier receives the model's code. `commitments_satisfied` asks "does the code satisfy the reasoning's commitments?" and `reasoning_code_alignment` asks "does the code implement what the reasoning describes?" Both questions INHERENTLY require the classifier to evaluate code correctness. When code is correct, commitments appear satisfied. When code is broken, commitments appear violated. The classifier isn't leaking — the dimensions are definitionally coupled to code correctness.

**This is a design flaw, not a prompt flaw.** No prompt change can fix it while these dimensions exist.

### Model Bias

| Model | mechanism | commitments_sat | alignment | reasoning_correct | pass |
|---|---|---|---|---|---|
| gpt-4.1-nano | 99.7% | 75.4% | 75.7% | 75.4% | 77.7% |
| gpt-4o-mini | 100.0% | 72.7% | 72.7% | 70.9% | 70.3% |
| gpt-5-mini | 99.4% | 78.7% | 80.5% | 80.5% | 77.6% |

Reasoning_correct tracks pass rate within 3 points for every model. The classifier adds no information beyond execution outcome.

### Condition Bias

| Condition | reasoning_correct | pass_rate | Delta (RC - pass) |
|---|---|---|---|
| baseline_v2 | 78.1% | 79.4% | -1.3% |
| leg_v2 | 74.8% | 74.8% | 0.0% |
| lean_v2 | 73.9% | 73.5% | +0.4% |

RC and pass rate are statistically indistinguishable. The classifier is not measuring reasoning quality independently of code quality.

### Prompt Framing / Style Bias

Not detectable from this data because the leakage effect dominates. Any style bias is masked by the 3x code-correctness correlation.

---

## 4. Case Studies

### FALSE POSITIVES (classifier says CORRECT, reasoning is wrong or shallow)

**FP-1: async_race_lock / gpt-4o-mini / leg_v2**
- Actual bug: RACE_CONDITION (locking issue in concurrent code)
- Model root_cause: "process_item and quick_increment both increment the counter, leading to redundant code and potential locking overhead"
- This is a SYMPTOM description, not a mechanism. "Redundant code" is not the bug.
- Classifier: mechanism=CORRECT, HIGH confidence
- **Why accepted:** The model mentions "locking" which is the right family keyword. The classifier anchors on keyword presence, not causal specificity.
- Code fails → commitments_satisfied=WRONG → reasoning_correct=False. So the leakage accidentally produces the right final answer for the wrong reason.

**FP-2: ordering_dependency / gpt-4.1-nano / baseline_v2**
- Actual bug: TEMPORAL_ORDERING (init must happen before process)
- Model root_cause: "process() checks _initialized variable to determine if init() has been called"
- This DESCRIBES the check, not the bug. The bug is that there's no enforcement of ordering.
- Classifier: mechanism=CORRECT
- **Why accepted:** The model mentions the right variable and function names. The classifier rewards grounding in code entities.

**FP-3: cache_invalidation_order (multiple instances across models)**
- Actual bug: cache operations happen in wrong order
- Models consistently describe the operations but misidentify which ordering is correct
- Classifier: mechanism=CORRECT on all instances
- **Why accepted:** Models name the right functions (cache_invalidate, cache_set). The classifier accepts because it sees code grounding.

### FALSE NEGATIVES (classifier says WRONG, reasoning is correct)

**FN-1: mutable_default_a / gpt-4o-mini / leg_v2**
- Model root_cause: "enqueue function uses a mutable default argument (queue=[]) which causes the same list to be shared across multiple calls"
- This is EXACTLY correct. The mutable default is the canonical mechanism for this bug family.
- Classifier: mechanism=CORRECT, but commitments_satisfied=WRONG → reasoning_correct=False
- **Why rejected:** Code fails execution → commitments_satisfied tracks code failure → reasoning rated incorrect despite correct mechanism

**FN-2: stale_cache_a / gpt-5-mini / lean_v2**
- Model root_cause: "update_product updates _db but does not modify _cache"
- This is EXACTLY correct.
- Classifier: mechanism=CORRECT, commitments_satisfied=WRONG → reasoning_correct=False
- **Why rejected:** Same mechanism — code doesn't pass, so commitments appear unsatisfied

**FN-3: feature_flag_drift / gpt-5-mini / baseline_v2**
- Model root_cause: "api.checkout accepts use_new_pricing but does not change the feature flag"
- Correct identification of the drift mechanism
- Classifier: mechanism=CORRECT, but reasoning_correct=False
- **Why rejected:** Code fails execution

**FN-4 through FN-9:** Same pattern across early_return_a, early_return_b, feature_flag_drift (nano), cache_invalidation_order (both models). All have correct mechanism identification, all rejected because code fails.

This is NOT a false negative problem in the classifier. **It's a systematic design flaw in the reasoning_correct derivation.** The derivation requires ALL dimensions to pass, but two of the four dimensions are proxies for code correctness. When code fails, they fail, and reasoning_correct becomes False regardless of actual reasoning quality.

---

## 5. Metric Contamination Analysis

### INVALID metrics (reasoning_correct is contaminated):

| Metric | Status | Why |
|---|---|---|
| `reasoning_correct` | **INVALID** | Derived from 4 dimensions, 2 of which are code-correctness proxies |
| `LEG_v2` (reasoning correct + code fail) | **INVALID** | LEG requires reasoning_correct=True, but the leaky dimensions make this almost impossible when code fails |
| `lucky_fix` (reasoning wrong + code pass) | **INFLATED** | When code passes, commitments_satisfied=CORRECT, making reasoning_correct more likely True → fewer lucky fixes than reality |
| Cross-condition reasoning comparisons | **INVALID** | RC tracks pass rate, not independent reasoning quality |
| Cross-model reasoning comparisons | **INVALID** | Same — RC reflects model code quality, not reasoning quality |

### VALID metrics (execution-based, no classifier involvement):

| Metric | Status | Why |
|---|---|---|
| `pass_rate` | **VALID** | Execution-based, no classifier |
| `delta_pass` (condition effect) | **VALID** | Execution-based |
| `assembly_failure_rate` | **VALID** | Dual execution comparison |

### PARTIALLY VALID metrics:

| Metric | Status | Why |
|---|---|---|
| `mechanism_identified` | **VALID but ceiling-limited** | Clean (1.01x leakage), but 99.7% CORRECT is not discriminative |
| `commitments_extracted` | **VALID but ceiling-limited** | Clean (1.02x leakage), near 100% |
| `failure_type` classification | **LIKELY VALID** | Independent of code correctness |

---

## 6. The Core Problem

The v2 classifier was designed to evaluate reasoning AND code-reasoning alignment in a single pass. This creates an irreconcilable conflict:

1. To evaluate `commitments_satisfied`, the classifier must judge whether the code implements the commitments
2. To judge code implementation, the classifier must evaluate code correctness
3. Code correctness is the execution outcome that the classifier is supposed to be independent of

**The dimension is asking the wrong question.** "Did the code satisfy the commitments?" ≈ "Did the code work?" The classifier cannot avoid this coupling because the question is inherently coupled.

---

## 7. Hard Recommendations

### IMMEDIATE (before next ablation)

1. **Stop using `reasoning_correct` for LEG claims.** It is contaminated. LEG rates computed from it are meaningless.

2. **Use `mechanism_identified` as the sole reasoning quality signal.** It's the only dimension with clean separation from code correctness (1.01x ratio).

3. **Redefine LEG using mechanism_identified only:**
   ```
   LEG_mechanism = P(mechanism_identified == CORRECT AND code_fail)
   ```
   This is trustworthy because mechanism_identified is not leaked.

4. **Remove `commitments_satisfied` and `reasoning_code_alignment` from the reasoning_correct derivation.** They measure code quality, not reasoning quality.

5. **Keep `commitments_satisfied` and `alignment` as DIAGNOSTIC signals only** — they tell you whether the code matches the reasoning, which is useful information but NOT reasoning quality.

### FOR THE PAPER

1. Report `mechanism_identified` rates as the reasoning quality metric
2. Report `LEG_mechanism` (mechanism correct + code fail) as the LEG metric
3. Report `commitments_satisfied` separately as a "code-reasoning consistency" metric, NOT as part of reasoning correctness
4. Acknowledge the leakage finding explicitly — this is actually an interesting methodological contribution

### WHAT IS SAFE TO CLAIM NOW

- Pass rates across models and conditions — SAFE
- Delta_pass (intervention effect) — SAFE
- Mechanism identification rates — SAFE (but ceiling-limited)
- Family-level difficulty rankings by pass rate — SAFE
- That the classifier's `commitments_satisfied` tracks code correctness — SAFE (this is a finding, not a bug, if framed correctly)

### WHAT MUST NOT BE CLAIMED

- "The model's reasoning was correct but code failed" using reasoning_correct — NOT SAFE
- LEG rates computed from reasoning_correct — NOT SAFE
- Lucky fix rates computed from reasoning_correct — NOT SAFE
- "Condition X improves reasoning quality" using reasoning_correct — NOT SAFE
- Any cross-model reasoning quality comparison using reasoning_correct — NOT SAFE

---

## 8. Appendix

### Table 1: Confusion Matrix (automated gold set, 72 cases)

| | Classifier: RC=True | Classifier: RC=False | Classifier: RC=None |
|---|---|---|---|
| Likely Correct (manual) | 26 (TP) | 9 (FN) | 2 |
| Likely Incorrect (manual) | 16 (FP) | 17 (TN) | 2 |

Precision: 26/(26+16) = 61.9%
Recall: 26/(26+9) = 74.3%

**61.9% precision is unacceptable for research claims.** Nearly 4 in 10 "reasoning correct" labels may be wrong.

Note: This is automated pre-screening, not true manual audit. True precision may differ. But the 3.13x leakage ratio is measured directly from data and is not approximate.

### Table 2: Leakage Risk Table

| Signal | Leak Type | Severity | Evidence |
|---|---|---|---|
| commitments_satisfied_dim | Code correctness → reasoning label | CRITICAL | 3.13x ratio |
| reasoning_code_alignment_dim | Code correctness → reasoning label | CRITICAL | 2.95x ratio |
| mechanism_identified_dim | None detected | CLEAN | 1.01x ratio |
| commitments_extracted_dim | None detected | CLEAN | 1.02x ratio |
| Code in classifier prompt | Structural (unavoidable) | MODERATE | Correct code looks different from broken code |
| Ground truth in grounded mode | Direct answer leak | HIGH (if used) | Provides failure_mode and trap |

### Table 3: LEG Sensitivity

| Metric | Value | Interpretation |
|---|---|---|
| LEG using reasoning_correct | ~3-5% | Severely suppressed by leakage |
| LEG using mechanism_identified only | ~20-25% (estimated) | Likely closer to true LEG |
| Delta | +15-20% | The leakage hides real reasoning-execution gap |
| Impact | SEVERE | The paper would undercount LEG by 4-5x |

### Table 4: Per-Family mechanism=CORRECT but code_fail (true LEG candidates)

| Family | N | mechanism=CORRECT + code_fail | LEG_mechanism rate |
|---|---|---|---|
| missing_branch | 36 | ~12 | ~33% |
| partial_rollback | 36 | ~9 | ~25% |
| effect_order | 40 | ~8 | ~20% |
| false_fix_deadlock | 6 | ~6 | ~100% |

These are the families with genuine reasoning-execution gap that the current reasoning_correct metric hides.
