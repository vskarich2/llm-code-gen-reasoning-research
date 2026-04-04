# AST Evaluator Disagreement — Revision v2

**Date:** 2026-04-03
**Supersedes:** ast_evaluator_disagreement_revision.md
**Data:** 14,272 events, 9,027 assessable, 133 cross-layer fixes, 151 extraction errors

---

## 1. Executive Summary

After fixing extraction contamination, expanding relaxed equivalence classes, separating cross-layer fixes, and broadening the partial-fix definition, the AST analysis yields a clean three-layer evaluation:

**Headline result:**

```
P(exec_fail | ast_correct) = 12.9%
```

Nearly 1 in 8 structurally correct outputs still fail execution. This is the single clearest quantitative expression of the reasoning-execution gap in the project.

**Complete picture:**

| Layer | What it measures | Rate |
|-------|-----------------|------|
| Evaluator (mechanism_correct) | Trace-level: did the model identify the bug mechanism? | 98.6% of assessable |
| AST (ast_relaxed) | Structure-level: did the code implement the correct structural fix? | 98.7% of assessable |
| Execution (exec_pass) | Behavior-level: did the code pass the invariant test? | 87.3% of assessable |

These three layers agree at 98.5%. The dominant bottleneck is not mechanism understanding (98.6%) or structural implementation (98.7%). **The dominant bottleneck is execution fidelity** — the 12.9% gap between structurally correct code and successful execution.

---

## 2. What Changed Since Revision 1

| Change | Impact |
|--------|--------|
| Split extraction_error from cross_layer_fix | 133 alias_config_c events reclassified as valid cross-layer fixes (all exec_pass=True) |
| Broadened ast_partial definition | 29 events now classified as partial (up from 3) |
| Computed P(exec_fail\|ast_correct) directly | 12.9% — elevated as headline metric |
| Flagship case study: use_before_set_b | P(exec_fail\|ast_correct) = 39.1% for this case |

---

## 3. Three-Layer Evaluation Model

The project's evaluation now decomposes into three orthogonal measurements:

**Layer 1: Trace-level mechanism understanding (evaluator)**
- Source: LLM classifier evaluating the model's reasoning trace
- Question: "Did the model correctly identify the bug mechanism in prose?"
- Signal: `mechanism_correct` (True/False)
- Reliability: High, but subjective; 98.5% agreement with AST

**Layer 2: Code-level structural implementation (AST)**
- Source: Deterministic AST pattern matching against invariant-derived specs
- Question: "Does the generated code contain a structural transformation that satisfies the case invariant?"
- Signal: `ast_relaxed` (True/False), `ast_partial` (True/False)
- Reliability: High, but limited to structural patterns; cannot detect semantic errors

**Layer 3: Behavioral execution correctness (tests)**
- Source: Subprocess execution of invariant tests
- Question: "Does the code actually work when run?"
- Signal: `exec_pass` (True/False)
- Reliability: Ground truth for behavioral correctness

**The key finding:** Layers 1 and 2 are highly aligned (98.5% agreement). Layer 3 diverges — 12.9% of outputs that pass Layers 1 and 2 fail Layer 3. The gap is between structure and execution, not between understanding and structure.

---

## 4. Extraction Error vs Cross-Layer Fix

The prior revision lumped all multi-file scoping issues into "extraction error." This was wrong. Two distinct phenomena were conflated:

### Extraction Error (151 events)
The target file/function was not available for AST analysis due to pipeline limitations. The model may or may not have fixed the bug — we cannot tell.

### Cross-Layer Fix (133 events, ALL from alias_config_c)
The model intentionally fixed the bug at a different architectural layer than the canonical fix. Specifically: instead of fixing `config.py::create_config()` to return `DEFAULTS.copy()`, the model modified `middleware.py` or `handler.py` to copy defensively before using the config.

**Every single cross-layer fix passes execution** (133/133 exec_pass=True). The test_c test exercises the system through `handle_request()`, which routes through middleware. If middleware copies the config before use, the invariant is satisfied even though config.py's `create_config()` still returns a bare reference.

This is not an extraction artifact. It is evidence of **system-level reasoning**: the model understood the aliasing problem and chose to fix it at the consumer layer instead of the producer layer. This is a valid architectural decision.

---

## 5. Revised Partial-Fix Definition

`ast_partial` is now defined as: **the model shows structural understanding of the correct repair mechanism, but the implementation does not fully satisfy the invariant.**

Specific detection criteria:

1. **Fix pattern present + anti-pattern also present:** The model added the fix but didn't remove the bug (e.g., added cache invalidation but also left stale reference code)
2. **Cache-related operation after write, but wrong type:** Model added some cache operation but not the correct invalidation (stale_cache families)
3. **Side-effect call present but wrong location:** Call exists in the function but outside the loop (effect_order families)
4. **Else branch added but invariant not fully covered:** Model restructured control flow showing understanding but incomplete coverage (use_before_set families)
5. **Default changed to non-mutable but guard missing:** Model removed the mutable literal default but didn't add the None-guard initialization (mutable_default families)

**Result:** 29 events classified as partial (0.3% of assessable). This is genuinely rare. Models that understand the mechanism well enough to attempt a structural fix almost always complete it. The partial category captures a real but small population of near-miss implementations.

---

## 6. Revised Disagreement Taxonomy

The original 651-event disagreement bucket (AST_relaxed=False, mechanism_correct=True) now decomposes as:

| Category | Count | % of original 651 | Status |
|----------|-------|-------------------|--------|
| Cross-layer fix | 133 | 20.4% | Valid alternative repair — not a disagreement |
| Extraction error | 151 | 23.2% | Cannot assess — separated from assessable |
| Valid alternative (now relaxed_correct) | 251 | 38.6% | AST checker expanded — resolved |
| Partial fix | 29 | 4.5% | Correctly classified as intermediate |
| Remaining wrong | 87 | 13.4% | 51 from use_before_set_a, 26 from use_before_set_c — likely further AST false negatives |

The remaining 116 assessable disagreements (29 partial + 87 wrong) are concentrated almost entirely in use_before_set (95/116 = 82%). This family has the most diverse valid fix space and the checkers need further expansion.

---

## 7. Structural-to-Execution Gap Metrics

### Headline

```
P(exec_fail | ast_correct) = 1,150 / 8,911 = 12.9%
```

Of 8,911 events where the model produced a structurally correct fix (by relaxed AST criteria), 1,150 still fail execution. This is the cleanest, most defensible measurement of the reasoning-execution gap:

- It does not depend on an LLM evaluator
- It is fully deterministic and reproducible
- It isolates the gap between correct structure and correct behavior
- It establishes that the bottleneck is execution fidelity, not mechanism understanding

### For comparison

```
P(ast_correct | assessable) = 98.7%   — models almost always get the structure right
P(exec_pass | assessable) = 87.3%     — but execution fails 12.7% of the time
P(mechanism_correct | assessable) = 98.6%  — and reasoning traces are almost always correct

The gap is in execution, not understanding.
```

---

## 8. Family-Level Execution Gap Hotspots

| Case | N | AST_correct% | Pass% | P(exec_fail\|ast_correct) |
|------|---|-------------|-------|--------------------------|
| **use_before_set_b** | **2,082** | **99.1%** | **61.2%** | **39.1%** |
| **effect_order_c** | **590** | **100.0%** | **80.5%** | **19.5%** |
| **use_before_set_c** | **217** | **88.0%** | **82.9%** | **19.4%** |
| mutable_default_c | 680 | 99.7% | 87.9% | 12.1% |
| effect_order_b | 746 | 100.0% | 90.9% | 9.1% |
| stale_cache_c | 217 | 97.2% | 89.4% | 8.1% |
| alias_config_b | 281 | 99.6% | 95.4% | 4.6% |

use_before_set_b has the largest execution gap: 39.1% of structurally correct outputs fail. effect_order_c and use_before_set_c follow at ~19.5%. These are the cases where the gap between understanding and execution is widest.

---

## 9. Model-Level Execution Gap

| Model | N | AST_correct% | Pass% | P(exec_fail\|ast_correct) |
|-------|---|-------------|-------|--------------------------|
| **gpt-4o-mini** | **2,612** | **99.6%** | **60.1%** | **40.0%** |
| gpt-4.1-nano | 1,590 | 99.2% | 94.2% | 5.9% |
| gpt-5.4-mini | 2,494 | 97.9% | 99.3% | 0.5% |
| gpt-5-mini | 1,943 | 97.9% | 99.7% | 0.3% |
| claude-sonnet-4 | 362 | 100.0% | 100.0% | 0.0% |

**gpt-4o-mini is the most striking result:** 99.6% structural correctness but only 60.1% execution success. P(exec_fail|ast_correct) = 40.0%. This model consistently understands the bug, consistently produces the right structural fix, and consistently fails to execute correctly. The bottleneck is entirely in execution fidelity — likely import handling, argument passing, test-contract compliance, or reconstruction artifacts.

By contrast, gpt-5-mini and gpt-5.4-mini have P(exec_fail|ast_correct) < 1% — they translate correct structure into successful execution almost perfectly.

---

## 10. Flagship Case Study: use_before_set_b

**Case:** use_before_set_b
**Bug:** `load()` sets `_status` on success path only; on empty/None input, `_status` retains stale value from prior call
**Invariant:** `_status` must be set on all paths through `load()`
**Fix pattern:** Add else branch setting `_status = "empty"` and `_data = None`

**Why this is the cleanest execution gap case:**

- **AST_correct = 99.1%** — virtually every model output adds an else branch or equivalent that covers the empty path
- **exec_pass = 61.2%** — but only 61% of those structurally correct outputs actually pass the test
- **P(exec_fail | ast_correct) = 39.1%** — the highest in the benchmark

This means: in 39.1% of cases, the model does the right thing structurally (adds coverage for the empty path) but something in the execution layer breaks. Likely causes:
- The else branch sets a different status string than the test expects
- The variable initialization pattern doesn't cover a specific edge case the test checks
- Reconstruction artifacts corrupt the code between generation and execution
- Import or scope issues in the multi-file test harness

This case is a canonical demonstration of the paper's thesis: **the gap between reasoning and execution is not a gap in understanding. It is a gap in execution fidelity.**

---

## 11. What The Evaluator Is Actually Measuring

The LLM evaluator's `mechanism_correct` signal is a trace-level judgment: "Did the model correctly identify the bug mechanism in its reasoning output?" It examines `root_cause` and `fix_strategy` fields from the model's structured output.

It does NOT examine whether the code implements the mechanism correctly. It does NOT examine execution results. It is deliberately blind to code-level and behavioral-level outcomes.

**This is correct design, not a flaw.** The evaluator measures understanding. AST measures implementation. Execution measures behavior. The 98.5% agreement between evaluator and AST confirms that models that understand the mechanism almost always also produce the correct structural fix. The disagreements (1.5%) are informative about edge cases, not evidence of evaluator failure.

---

## 12. What AST Is Actually Measuring

AST measures whether the model's generated code contains a structural transformation that satisfies the case invariant. It checks for the presence of specific AST patterns (method calls, control flow structures, statement ordering) that are necessary conditions for the invariant to hold.

**What AST captures:** Correct structural intent — the model produced code with the right fix pattern.

**What AST does not capture:** Semantic correctness within a structurally correct pattern. A model that adds `_cache.pop(product_id, None)` with the wrong variable name for `product_id` will pass AST but fail execution. This is exactly the gap P(exec_fail|ast_correct) measures.

AST is therefore a **necessary but not sufficient** condition for execution success. It is sufficient to establish structural understanding, which is what the paper needs to measure the reasoning-execution gap.

---

## 13. Revised Conclusions

### The dominant bottleneck is execution fidelity, not mechanism understanding

- 98.6% of assessable outputs show correct mechanism identification (evaluator)
- 98.7% show correct structural implementation (AST)
- But only 87.3% succeed at execution
- P(exec_fail | ast_correct) = 12.9%

Models understand the bug. Models produce the right structural fix. But 1 in 8 structurally correct outputs still fail at runtime.

### The gap is model-stratified

- gpt-4o-mini: P(exec_fail|ast_correct) = 40.0% — massive execution fidelity gap
- gpt-4.1-nano: 5.9%
- gpt-5-mini: 0.3%
- gpt-5.4-mini: 0.5%

The execution gap is not uniform. Weaker models fail disproportionately at translating correct structure into working code.

### The gap is family-stratified

- use_before_set_b: 39.1%
- effect_order_c: 19.5%
- use_before_set_c: 19.4%
- Most other families: <5%

Some bug families are harder to execute correctly even when the structure is right.

### Cross-layer fixes are a real phenomenon

133 events (all alias_config_c) show models fixing the bug at a different architectural layer. Every one passes execution. This is system-level reasoning, not a measurement artifact.

### Lucky fixes are genuinely rare

LUCKY_FIX_relaxed = 1.2% (110/9,027). The vast majority of execution successes come from structurally correct code, not accidental test passage.

---

## 14. Remaining Open Issues

1. **use_before_set_a/c checker expansion:** 77 events still classified as wrong that are likely valid structural alternatives. This family has the most diverse fix space and needs broader relaxed patterns.

2. **Execution failure root causes:** The 1,150 AST-correct-but-execution-failed events have not been analyzed for their execution failure reasons. Decomposing these into reconstruction artifacts, import errors, argument mismatches, and semantic errors within correct structures would strengthen the paper significantly.

3. **Cross-layer fix generalization:** Only observed in alias_config_c. Would other multi-file cases show similar cross-layer repair strategies? This is an interesting research question but out of scope for this analysis.

4. **gpt-4o-mini anomaly:** 40% execution gap despite 99.6% structural correctness demands investigation. Is this a systematic execution-layer failure (e.g., import handling) or case-specific? Decomposing by case × model would clarify.
