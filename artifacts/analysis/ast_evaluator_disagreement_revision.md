# AST Evaluator Disagreement — Revision Report

**Date:** 2026-04-03
**Supersedes:** ast_mechanism_disagreement_audit.md
**Data:** 14,272 events from all log files, 9,027 assessable after extraction fix

---

## 1. Executive Summary

The prior audit had two major contaminations: (1) multi-file extraction scoping errors inflated the disagreement bucket by 43%, and (2) the relaxed checker missed three common valid alternative fix patterns. After fixing both:

| Metric | Before revision | After revision | Change |
|--------|----------------|---------------|--------|
| Assessable events | 9,311 | 9,027 | -284 (extraction errors separated) |
| **LUCKY_FIX_relaxed** | **5.1%** | **1.2%** | **-3.9pp** |
| **AST_CORRECT_FAILURE** | **12.2%** | **12.7%** | **+0.5pp** |
| **Evaluator agreement** | **92.8%** | **98.5%** | **+5.7pp** |
| Remaining disagreement | 651 | 116 | **-82%** |

The AST metric is now clean. LUCKY_FIX dropped from 5.1% to 1.2%. Evaluator agreement rose to 98.5%. The LEG signal (AST_CORRECT_FAILURE = 12.7%) is confirmed and slightly strengthened.

---

## 2. What Was Wrong With The Prior Audit

**Problem 1: Extraction contamination.** 283 events from alias_config_c were classified as "AST disagreements" when in fact `_extracted_code` contained the wrong file (handler.py or middleware.py instead of config.py). The AST checker never saw the target file. These were NOT AST checker errors or evaluator errors — they were data pipeline scoping issues.

**Problem 2: Missing valid alternatives.** Three common model fix patterns were not in the relaxed equivalence classes:
- **Parameter removal + local init** (134 events, mutable_default_b): model removes the mutable-default parameter entirely and creates the variable locally
- **Write-through cache update** (92 events, stale_cache_a): model updates the cache entry directly instead of invalidating it
- **hasattr() lazy initialization** (26 events, mutable_default_c): model uses hasattr() on the wrapper function instead of a local variable

**Problem 3: False binary.** Without an `ast_partial` category, events where the model showed structural understanding but incomplete implementation were forced into either "correct" or "wrong."

---

## 3. Extraction / Scoping Fix

**What changed:** Multi-file cases where `_extracted_code` does not contain the target function (`def {func_name}` not in code) are now classified as `extraction_error` and removed from the assessable pool.

**Impact:** 284 events moved from assessable to extraction_error:
- alias_config_c: 283 (model said "UNCHANGED" for config.py in 125 verified cases; the model fixed it via middleware instead, which is a valid alternative fix location for the test_c test)
- alias_config_b: 1

**Note on alias_config_c "UNCHANGED":** In 125 verified cases, the model marked config.py as UNCHANGED and instead modified middleware.py to copy defensively. The test_c test exercises the system through `handle_request()` which goes through middleware — so the test passes. This is a genuinely valid alternative fix at a different architectural layer. The evaluator correctly said `mechanism_correct=True` (the model identified the aliasing mechanism). The model just chose to fix it in middleware instead of config. These events are now `extraction_error` because our AST checker targets config.py — but the model's fix is valid.

---

## 4. Revised AST Taxonomy

Every event now receives one of these labels:

| Label | Definition | Count | % |
|-------|-----------|-------|---|
| `strict_correct` | Matches canonical fix pattern exactly | 6,652 | 73.7% |
| `relaxed_correct` | Satisfies invariant via accepted alternative form | 2,259 | 25.0% |
| `partial` | Shows structural understanding but incomplete implementation | 3 | 0.03% |
| `wrong` | Does not satisfy invariant structurally | 113 | 1.3% |
| `extraction_error` | Target file/function not available for analysis | 284 | — |
| `unassessable` | Reconstruction failed, syntax error, or empty code | 4,961 | — |

---

## 5. Invariant-Based Rule Revisions

### mutable_default: "each call must start with empty container"

**Structural condition:** The mutable state must not persist across calls.

**Accepted forms (invariant-justified):**
1. `param=None` + `if is None: param = X()` — canonical
2. Parameter removed entirely + local assignment — **valid because** removing the parameter eliminates the persistence mechanism entirely. No shared state can exist if the parameter doesn't exist. **Counterexample that would NOT be accepted:** Model removes parameter but reads from a module-level variable instead — this would fail the invariant. Our checker verifies a LOCAL assignment exists.
3. `hasattr(wrapper, '_history')` lazy init (mutable_default_c) — **valid because** each wrapper function object gets its own attribute, so state is per-decorator, not shared. **Counterexample:** `hasattr(module, 'history')` at module level — would be shared. Our checker accepts hasattr() only within the decorator function body.

### stale_cache: "get must return current data after update"

**Structural condition:** After a DB write, the cache must not serve stale data.

**Accepted forms:**
1. Cache invalidation after write (`pop`, `invalidate`, `delete`) — canonical
2. Cache write-through after write (`_cache[key] = new_value`) — **valid because** the cache is overwritten with the current value, so subsequent reads return fresh data. **Counterexample:** `_cache[key] = old_value` (writing stale data). Our checker verifies the assignment happens AFTER the DB write, but does NOT verify the assigned value is fresh — this is a known limitation where execution testing catches semantic errors.

### use_before_set: "handle all inputs without NameError"

The relaxed checkers for this family were already broad (accepting else branches, early returns, multiple return paths, pre-initialization). No new patterns were needed — the 95 "structural alternative" events from the prior audit were already captured by the existing relaxed checkers when the extraction scoping was correct.

---

## 6. Partial-Fix Definition

`ast_partial` = True when:
- The relaxed check passes BUT the anti-pattern is also still present
- This means the model added the fix but didn't remove the bug

Only 3 events in the entire dataset qualify as partial (all in stale_cache_a). This category is real but very rare — models that understand the mechanism well enough to add the fix almost always also remove the bug pattern.

---

## 7. Revised Disagreement Breakdown

The original 651-event disagreement bucket (AST_relaxed=False, mechanism_correct=True) now decomposes as:

| Category | Count | Pct of original 651 |
|----------|-------|-------------------|
| **Extraction error** (now separated, not in assessable) | 284 | 43.6% |
| **Valid alternative — now accepted by relaxed** | 251 | 38.6% |
| **Remaining disagreement** (AST=wrong, eval=correct) | 116 | 17.8% |

The 116 remaining disagreements are concentrated in use_before_set_a (51), use_before_set_c (26), use_before_set_b (18), stale_cache_a (10), and a scatter of others. These are cases where the model used structural alternatives the checker still doesn't recognize — primarily in the use_before_set family which has the most diverse valid fix space.

---

## 8. Revised Metrics

### Relaxed 2×2 Matrix (N=9,027 assessable)

```
                     Exec Pass    Exec Fail
AST Correct             7,761       1,150     (98.7%)
AST Incorrect             110           6     (1.3%)
```

- **AST_CORRECT_FAILURE (LEG_ast) = 12.7%** — 1,150 events where the model produced the correct structural fix but execution still fails
- **LUCKY_FIX = 1.2%** — 110 events where execution passes without the recognized structural fix
- **Evaluator agreement = 98.5%** (vs 92.8% before)

### LEG rates

| Metric | Rate |
|--------|------|
| LEG_ast (relaxed) | 12.7% |
| LEG_ast (strict) | 11.5% |
| LEG_text (evaluator-based) | 0.5% |

LEG_ast is dramatically higher than LEG_text because it measures **structural** correctness-without-execution, while LEG_text measures only cases where the evaluator flagged mechanism_correct + alignment_wrong — a much narrower condition.

---

## 9. Family-Level Impacts

| Case | N | AST_correct% | ACF% | LF% | Notes |
|------|---|-------------|------|-----|-------|
| alias_config_c | 929 | 100.0% | 0.0% | 0.0% | Clean after extraction fix |
| mutable_default_b | 1,087 | 99.8% | 0.2% | 0.0% | Clean after param-removal fix |
| stale_cache_a | 941 | 98.9% | 0.0% | 1.1% | 10 lucky fixes remain |
| mutable_default_c | 680 | 97.9% | 12.1% | 0.3% | High ACF — models fix structure but exec fails |
| **use_before_set_b** | **2,082** | **99.1%** | **38.8%** | **0.9%** | **Highest ACF — massive LEG case** |
| use_before_set_c | 217 | 88.0% | 17.1% | 12.0% | Still has 12% lucky — checker needs work |
| use_before_set_a | 227 | 77.5% | 0.0% | 22.5% | Highest lucky — checker still too strict |
| effect_order_c | 590 | 100.0% | 19.5% | 0.0% | Clean, high LEG |

**use_before_set_a** (22.5% lucky) and **use_before_set_c** (12.0% lucky) still have significant lucky-fix rates, indicating the relaxed checkers for these cases need further expansion. These are the main remaining AST false negative sources.

---

## 10. Model-Level Impacts

| Model | N | ACF% | LF% | AST_correct% |
|-------|---|------|-----|-------------|
| gpt-4o-mini | 2,612 | **39.9%** | 0.4% | 99.6% |
| gpt-4.1-nano | 1,590 | 5.8% | 0.8% | 93.4% |
| gpt-5.4-mini | 2,494 | 0.4% | 1.8% | 97.7% |
| gpt-5-mini | 1,943 | 0.3% | 2.1% | 97.7% |
| claude-sonnet-4 | 362 | 0.0% | 0.0% | 100.0% |

**gpt-4o-mini has the largest structural-correct-but-execution-fails gap at 39.9%.** This is the model with the most severe LEG phenomenon — it consistently produces the right structural transformation but something in its code generation (likely imports, argument handling, or test-contract compliance) causes execution to fail.

---

## 11. Condition-Level Impacts

The condition breakdown is stable — LEG scaffolding conditions still show slightly different patterns but no dramatic shifts from the prior analysis.

---

## 12. What The Evaluator Is Actually Measuring

The 98.5% agreement between AST_relaxed and mechanism_correct confirms that these two signals are measuring closely related but not identical things:

- **mechanism_correct (evaluator):** "Did the model correctly identify the bug mechanism in its reasoning trace?" — this is a **trace-level** judgment about the model's verbal understanding
- **ast_relaxed:** "Does the model's code contain a structural transformation that satisfies the case invariant?" — this is a **code-level** judgment about the actual output

They agree 98.5% of the time because models that understand the mechanism almost always also produce the correct structural fix. The 1.5% disagreement breaks down as:
- 0.1% AST=correct, eval=wrong — evaluator missed the mechanism in prose (evaluator false negative)
- 1.3% AST=wrong, eval=correct — correct mechanism in prose, but code doesn't implement it (genuine trace/code gap) OR AST checker still too strict for some alternatives

**This is a major finding:** The evaluator and AST are measuring almost the same thing from different angles. The evaluator looks at the reasoning trace; AST looks at the code output. When they agree, the signal is very strong. When they disagree, the disagreement is informative about whether the gap is in understanding (trace) or implementation (code).

---

## 13. Recommendations

### A. Further AST checker work
1. **use_before_set_a:** Expand relaxed checker to accept more control-flow restructurings (22.5% lucky fix rate is too high)
2. **use_before_set_c:** Same issue (12.0% lucky)
3. **stale_cache_a:** Investigate the 10 remaining lucky fixes — likely minor pattern gaps

### B. Do NOT further expand alias_config, mutable_default, or effect_order
These families now have ~0% lucky fix rates. The checkers are calibrated.

### C. Report three evaluation axes in the paper
- Execution (behavioral ground truth)
- AST (structural correctness — deterministic, non-LLM)
- Evaluator mechanism_correct (trace-level reasoning — LLM-based)
The paper should present all three, showing their agreement (98.5%) and using their disagreement to decompose the failure space.

### D. LEG_ast is the paper's strongest new metric
12.7% of assessable events show correct structural fix + failed execution. This is an objective, reproducible, non-LLM measurement of the reasoning-execution gap. It should feature prominently.

---

## 14. Remaining Open Issues

1. **use_before_set_a/c lucky fix rates** need further checker expansion — ~95 events still misclassified
2. **Extraction error for multi-file cases** only fully fixable when raw response files are available (workers/ directory). Logs without workers/ still have the old scoping issue.
3. **ast_partial is essentially empty** (3 events). Either the category is too narrowly defined or models genuinely don't produce partial fixes — they either get it right or completely wrong. This is an interesting finding in itself.
4. **The 116 remaining disagreements** should be manually audited to close the last 1.3% of the assessable pool. Expected to be ~70% further AST false negatives (use_before_set alternatives) and ~30% genuine evaluator false positives.
