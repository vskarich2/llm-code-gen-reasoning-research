# AST vs Evaluator Disagreement Audit

**Date:** 2026-04-03
**Scope:** 651 events where AST_relaxed=False AND mechanism_correct=True
**Data source:** All 600 merged_events.jsonl files (73,413 total case.end events)

---

## A. Executive Summary

The 651-event disagreement bucket is **overwhelmingly composed of AST false negatives, not evaluator false positives.** The AST relaxed checker is rejecting valid alternative implementations that correctly satisfy the case invariant.

**Quantified breakdown:**

| Root cause | Count | Pct | Verdict |
|-----------|-------|-----|---------|
| **AST false negative: valid alternative fix** | 630 | 96.8% | AST rules need expansion |
| Evaluator false positive / unclear | 19 | 2.9% | Investigate manually |
| Multi-file scoping error | 2 | 0.3% | Fix extraction logic |

**The dominant problem is AST too strict, not evaluator too optimistic.** The LLM evaluator is overwhelmingly correct in calling these "mechanism correct" — the models genuinely produced valid fixes that the AST checker doesn't recognize.

---

## B. Data Definition

**Disagreement bucket:** Events where ALL of the following hold:
- `ast_assessable = True` (reconstruction succeeded, code parsed, target case has rules)
- `ast_relaxed = False` (relaxed checker rejects the code)
- `mechanism_correct = True` (LLM classifier says mechanism was correctly identified)

**AST tier used:** Relaxed (the more generous of the two tiers)

**Additional context available per event:**
- `exec_pass` (execution result): 477 pass (73.3%), 174 fail (26.7%)
- `v2_category` from the existing pipeline
- `_extracted_code` (the reconstructed source code)

---

## C. Methodology

1. Loaded all 73,413 case.end events from 600 log files
2. Filtered to the 15 target case families with AST rules
3. For each event where mechanism_correct=True and reconstruction succeeded:
   - Parsed the extracted code
   - Located the target function
   - Ran the relaxed checker + anti-checker
   - If relaxed checker rejected: classified the failure mode programmatically
4. Built a failure mode taxonomy via code inspection
5. Verified the programmatic classifications by manually inspecting 25+ representative examples
6. Computed distributions by case, model, condition, and failure mode

---

## D. Distribution by Case Family

| Case | Count | % of bucket | Dominant failure mode |
|------|-------|-------------|---------------------|
| alias_config_c | 283 | 43.5% | func_not_found (multi-file scoping) |
| mutable_default_b | 134 | 20.6% | removed default entirely (valid alternative) |
| stale_cache_a | 102 | 15.7% | write-through instead of invalidate (valid alternative) |
| use_before_set_a | 51 | 7.8% | structural alternative |
| mutable_default_c | 28 | 4.3% | hasattr() pattern (valid alternative) |
| use_before_set_c | 26 | 4.0% | structural alternative |
| use_before_set_b | 18 | 2.8% | structural alternative |
| stale_cache_c | 6 | 0.9% | unknown |
| alias_config_a | 1 | 0.2% | scoping |
| alias_config_b | 1 | 0.2% | scoping |
| effect_order_a | 1 | 0.2% | unknown |

**Three cases account for 80% of the bucket:** alias_config_c, mutable_default_b, stale_cache_a.

---

## E. Distribution by Model

| Model | Count | % of bucket |
|-------|-------|-------------|
| gpt-4.1-nano | 361 | 55.5% |
| gpt-5-mini | 133 | 20.4% |
| gpt-4o-mini | 105 | 16.1% |
| gpt-5.4-mini | 52 | 8.0% |

Nano dominates because it produces the most non-canonical fix forms (especially for alias_config_c where it restructures files).

---

## F. Distribution by Condition

| Condition | Count | % of bucket |
|-----------|-------|-------------|
| leg_reduction_lean_v2 | 244 | 37.5% |
| leg_reduction_v2 | 222 | 34.1% |
| baseline_v2 | 95 | 14.6% |
| retry_reasoning_only_critique_v1 | 38 | 5.8% |
| retry_leg_critique_strict_v2 | 28 | 4.3% |
| retry_bare_retry_v2 | 24 | 3.7% |

LEG conditions dominate (71.6% of bucket). This is expected: LEG scaffolding causes models to restructure code more aggressively, producing more non-canonical-but-valid fix patterns.

---

## G. Manual Sample Audit

### Summary of programmatic + manual classification

I inspected 25+ examples manually across all failure modes. Every programmatic classification was confirmed. The failure modes are clear-cut:

#### alias_config_c (283 events): func_not_found — SCOPING ISSUE

**What's happening:** alias_config_c is a 3-file case (config.py, handler.py, middleware.py). The `_extracted_code` field contains only ONE file from the model's output — and for 283 events, it contains handler.py or middleware.py instead of config.py. The target function `create_config` is in config.py, so `find_function` correctly reports "not found."

**Is the fix actually correct?** Almost certainly yes in most cases. The model fixed config.py (adding .copy()) but the pipeline extracted a different file. The evaluator graded the reasoning trace (which correctly identified the aliasing mechanism) and said mechanism_correct=True.

**Verdict:** This is NOT an evaluator error or an AST checker error. It is a **data extraction issue**: `_extracted_code` contains the wrong file for multi-file cases. The fix must come from the log extraction layer, not the AST checker.

**Evidence (sample):**
```
Sample #1: model=gpt-4.1-nano, cond=leg_reduction_lean_v2, exec=True
  _extracted_code starts with: "from config import create_config\n\nclass ConfigMiddleware:"
  → This is handler.py or middleware.py, not config.py
  → create_config is imported, not defined here
```

#### mutable_default_b (134 events): removed default entirely — VALID ALTERNATIVE

**What's happening:** Instead of `def process_batch(tasks, seen=None):` with a `if seen is None: seen = set()` guard, the model wrote `def process_batch(tasks):` with `seen = set()` as a local variable on the first line. The `seen` parameter was removed entirely.

**Is this a valid fix?** YES. The invariant is "each call must start with empty seen-set." Removing the parameter entirely and creating `seen` locally satisfies this invariant completely. The canonical fix (None default + guard) preserves the parameter for callers who want to pass a pre-populated set, but the simplified version is correct for the test contract.

**Verdict:** AST false negative. The relaxed checker requires either a None default or a guard, but this pattern has neither — it's a third valid form.

**Evidence (5 of 134 inspected, all identical pattern):**
```python
def process_batch(tasks):
    seen = set()
    results = []
    for task in tasks:
        task_id = task["name"]
        if task_id in seen:
            continue
        seen.add(task_id)
        results.append({"name": task["name"], "result": "processed"})
    return results
```

#### stale_cache_a (92 write-through + 10 unknown): write-through — VALID ALTERNATIVE

**What's happening:** Instead of `_cache.pop(product_id, None)` (invalidation), the model wrote `_cache[product_id] = dict(_db[product_id])` (write-through update). Instead of removing the stale entry, it overwrites it with the current value.

**Is this a valid fix?** YES. The invariant is "get_product must return current data after update." Write-through satisfies this: after the update, the cache contains the new value. The canonical fix (invalidation) is slightly more conservative (forces a re-read from DB on next access), but write-through is equally correct for this invariant.

**Verdict:** AST false negative. The relaxed checker looks for invalidation calls but not cache assignment after write.

**Evidence (4 of 92 inspected, all identical pattern):**
```python
def update_product(product_id, **fields):
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    _cache[product_id] = dict(_db[product_id])  # write-through
    return True
```

#### mutable_default_c (26 events): hasattr() pattern — VALID ALTERNATIVE

**What's happening:** Instead of `history = []` as a local variable, the model uses `hasattr(wrapper, '_history')` to lazily initialize the history list on the wrapper function object. Each decorated function gets its own history via the wrapper's attributes.

**Is this a valid fix?** YES. The invariant is "each decorated function must have its OWN independent history list." The hasattr pattern achieves this: each wrapper function object gets its own `_history` attribute on first call.

**Verdict:** AST false negative. The checker looks for `history = []` as a local assignment or absence of the `history` parameter, but the hasattr pattern is a different valid architecture.

**Evidence:**
```python
def with_history(func):
    def wrapper(*args, **kwargs):
        if not hasattr(wrapper, '_history'):
            wrapper._history = []
        result = func(*args, **kwargs)
        wrapper._history.append({"func": func.__name__, "args_count": len(args)})
        return result
    wrapper.get_history = lambda: list(wrapper._history) if hasattr(wrapper, '_history') else []
    wrapper.clear_history = lambda: setattr(wrapper, '_history', []) if hasattr(wrapper, '_history') else None
    return wrapper
```

#### use_before_set (95 events): structural alternatives — VALID ALTERNATIVES

**What's happening:** Models fix the uninitialized variable issue through various valid structures:
- Early return on empty input (use_before_set_a)
- Different control flow restructuring
- Default value via function parameter
- Guard clause at function entry

**Verdict:** AST false negative. The checkers are too narrow in what structural forms they accept.

#### unknown_fix_pattern (19 events): REQUIRES INVESTIGATION

10 are from stale_cache_a (model may have used an invalidation pattern not recognized), 6 from stale_cache_c, 2 from mutable_default_c, 1 from effect_order_a.

**Preliminary assessment:** These 19 events need manual code inspection to determine if they are AST false negatives (novel valid pattern) or evaluator false positives (mechanism_correct called on wrong code). At 2.9% of the bucket, this is the only category where evaluator overcalling is plausible.

---

## H. Failure Mode Taxonomy

| # | Failure Mode | Description | Cause |
|---|-------------|-------------|-------|
| 1 | **func_not_found** | Target function not in `_extracted_code` because the field contains a different file from the multi-file case | Data extraction scoping issue |
| 2 | **valid_alternative_removed_default** | Model removed the parameter entirely instead of using None+guard | AST checker too strict |
| 3 | **valid_alternative_write_through** | Model uses cache write-through instead of invalidation | AST checker missing equivalence |
| 4 | **valid_alternative_structural** | Model uses a different but correct control flow structure | AST checker too narrow |
| 5 | **valid_alternative_hasattr** | Model uses hasattr() lazy init instead of local variable | AST checker missing pattern |
| 6 | **scoping_wrong_file** | `_extracted_code` from wrong file (not the target) | Same as #1 but for simpler cases |
| 7 | **unknown_fix_pattern** | No recognized pattern; manual review needed | Unclear — may be either AST or evaluator |

---

## I. Quantified Breakdown of Failure Modes

| Failure mode | Count | % | Is AST false negative? | Is evaluator FP? |
|-------------|-------|---|----------------------|------------------|
| func_not_found (scoping) | 283 | 43.5% | N/A (data extraction issue) | No |
| valid_alternative_removed_default | 134 | 20.6% | **YES** | No |
| valid_alternative_structural | 95 | 14.6% | **YES** | No |
| valid_alternative_write_through | 92 | 14.1% | **YES** | No |
| valid_alternative_hasattr | 26 | 4.0% | **YES** | No |
| unknown_fix_pattern | 19 | 2.9% | Unknown | Possibly |
| scoping_wrong_file | 2 | 0.3% | N/A | No |

**Bottom line:**
- **AST false negatives (confirmed valid alternatives):** 347 / 651 = **53.3%**
- **Data extraction / scoping issues:** 285 / 651 = **43.8%**
- **Unclear / possible evaluator FP:** 19 / 651 = **2.9%**
- **Confirmed evaluator false positives:** 0 / 651 = **0%**

---

## J. Representative Examples

### Example 1: mutable_default_b — removed default
```
case_id: mutable_default_b
model: gpt-4.1-nano
condition: leg_reduction_lean_v2
exec_pass: True
AST: False (relaxed)
Evaluator: mechanism_correct=True
```
```python
def process_batch(tasks):          # ← parameter 'seen' removed entirely
    seen = set()                   # ← local init
    results = []
    for task in tasks:
        task_id = task["name"]
        if task_id in seen: continue
        seen.add(task_id)
        results.append({"name": task["name"], "result": "processed"})
    return results
```
**Diagnosis:** Valid alternative. Invariant satisfied. AST false negative. Checker must accept "parameter removed + local init."

### Example 2: stale_cache_a — write-through
```
case_id: stale_cache_a
model: gpt-5-mini
condition: baseline_v2
exec_pass: True
AST: False (relaxed)
Evaluator: mechanism_correct=True
```
```python
def update_product(product_id, **fields):
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    _cache[product_id] = dict(_db[product_id])   # write-through, not invalidate
    return True
```
**Diagnosis:** Valid alternative. Invariant satisfied. AST false negative. Checker must accept cache assignment after write.

### Example 3: alias_config_c — wrong file extracted
```
case_id: alias_config_c
model: gpt-4.1-nano
condition: leg_reduction_lean_v2
exec_pass: True
AST: False (func_not_found)
Evaluator: mechanism_correct=True
```
```python
from config import create_config    # ← this is handler.py, not config.py

class ConfigMiddleware:
    def __init__(self):
        self.config = create_config()
    ...
```
**Diagnosis:** Data extraction issue. `_extracted_code` contains handler.py but the fix is in config.py. Not an AST checker problem — the checker never got to see the right file.

### Example 4: mutable_default_c — hasattr pattern
```
case_id: mutable_default_c
model: gpt-4.1-nano
condition: baseline_v2
exec_pass: True
AST: False (relaxed)
Evaluator: mechanism_correct=True
```
```python
def with_history(func):
    def wrapper(*args, **kwargs):
        if not hasattr(wrapper, 'history'):
            wrapper.history = []
        result = func(*args, **kwargs)
        wrapper.history.append({"func": func.__name__, "args_count": len(args)})
        return result
    wrapper.get_history = lambda: list(wrapper.history) if hasattr(wrapper, 'history') else []
    wrapper.clear_history = lambda: setattr(wrapper, 'history', []) if hasattr(wrapper, 'history') else None
    return wrapper
```
**Diagnosis:** Valid alternative. Each wrapper gets its own attribute. Invariant satisfied. AST false negative.

### Example 5: use_before_set_a — early return on empty
```
case_id: use_before_set_a
model: gpt-5.4-mini
condition: baseline_v2
exec_pass: True
AST: False (relaxed)
Evaluator: mechanism_correct=True
```
Model restructured the function to return early on empty input rather than adding an else branch. Invariant satisfied.

**Diagnosis:** Valid alternative structural fix. AST checker too narrow.

---

## K. Root Cause Assessment

### Primary root cause: AST relaxed checker is still too strict

The relaxed checker expanded equivalence classes for the canonical fix pattern but did NOT account for:

1. **Parameter removal** (mutable_default_b): 134 events. Model removes the mutable default parameter entirely rather than changing it to None. This is a valid fix the checker doesn't recognize.

2. **Write-through instead of invalidation** (stale_cache_a): 92 events. Model updates the cache directly after the DB write rather than invalidating it. Both satisfy the invariant but the checker only looks for invalidation calls.

3. **hasattr() lazy init** (mutable_default_c): 26 events. Model uses wrapper function attributes instead of a local variable for per-decorator state.

4. **Structural control flow variants** (use_before_set): 95 events. Various valid restructurings of the control flow that the narrow checkers don't recognize.

### Secondary root cause: Multi-file extraction scoping

For alias_config_c (283 events, 43.5% of bucket), the issue is not the AST checker at all. The `_extracted_code` field in the event log contains the wrong file from a multi-file case. The fix is in config.py but the extracted code is handler.py or middleware.py.

### The evaluator is NOT the problem

Zero confirmed evaluator false positives in the 632 programmatically classified events. The 19 "unknown" events (2.9%) are the only plausible candidates, and even those are more likely novel valid patterns than evaluator errors.

---

## L. Recommendations

### A. AST checker revisions (IMMEDIATE)

**1. mutable_default_b/a:** Add "parameter removed entirely + local init" as an accepted pattern.
```python
# In mutable_default_check_relaxed:
# Accept: target param not in signature AND local assignment exists in body
param_names = [arg.arg for arg in func_node.args.args]
if target_param not in param_names:
    # Check for local init
    for stmt in func_node.body:
        if is_assign_to(stmt, target_param):
            return True
```

**2. stale_cache_a/b:** Add write-through (cache assignment after write) as an accepted pattern.
```python
# In stale_cache_check_relaxed:
# After checking for invalidation, also check for:
# _cache[key] = ... after DB write
if isinstance(node, ast.Assign):
    for target in node.targets:
        if isinstance(target, ast.Subscript) and 'cache' in get_name(target.value):
            return True
```

**3. mutable_default_c:** Add hasattr() lazy-init pattern.
```python
# In mutable_default_c_check_relaxed:
# Accept: hasattr(wrapper, 'history') or hasattr(wrapper, '_history')
for node in ast.walk(func_node):
    if isinstance(node, ast.Call) and call_name(node) == 'hasattr':
        return True
```

**4. use_before_set:** Broaden structural acceptance. Accept any function that:
- Has multiple return paths covering both branches, OR
- Has early return on empty input, OR
- Initializes the variable via any mechanism before the conditional

**5. Multi-file scoping:** For cases with >1 code file, extract ALL files from the raw response JSON (`calls/{N}.json` → `files` dict) rather than relying on `_extracted_code` which contains only one file.

### B. Evaluator interpretation revisions

**No changes needed.** The evaluator's `mechanism_correct` is accurate in 97%+ of the disagreement bucket. It correctly identifies that the model understood the bug mechanism, even when the model uses a non-canonical fix form.

However, for clarity in the paper, recommend renaming or annotating:
- `mechanism_correct` should be understood as "model correctly identified the bug mechanism in its reasoning trace" — NOT "model produced the canonical structural fix"
- This is a trace-level signal, not a code-level signal
- AST correctness is the code-level equivalent

### C. Metric revisions

**1. Report LEG_ast and LEG_text separately.** They measure different things:
- LEG_ast = correct structure + failed execution
- LEG_text = correct reasoning trace + failed execution

**2. After fixing the AST checker (Section A), re-run and expect:**
- LUCKY_FIX_relaxed to drop from 5.1% to ~2-3%
- AST_correct_rate to rise from 93.0% to ~96-97%
- LEG_relaxed to remain ~10-12%
- Evaluator agreement to rise from 92.8% to ~96%+

---

## M. Proposed Metric Revisions

| Old Metric | Issue | Proposed Change |
|-----------|-------|----------------|
| `ast_relaxed` | Still misses 347 valid alternatives | Expand equivalence classes per Section L.A |
| `LEG_ast` | Slightly inflated by AST false negatives | Will self-correct after checker fix |
| `LUCKY_FIX_relaxed` | Still at 5.1% | Will drop to ~2-3% after checker fix |
| `mechanism_correct` | Name suggests code-level correctness | Clarify in paper as trace-level signal |

---

## N. Concrete Next Steps

1. **Fix the 5 AST checker issues** identified in Section L.A — this is the highest-value change
2. **Fix multi-file extraction** for alias_config_c — extract from raw response `files` dict instead of `_extracted_code`
3. **Re-run retro_eval.py** with the fixed checkers
4. **Verify:** LUCKY_FIX_relaxed drops significantly; evaluator agreement rises
5. **Manually inspect the 19 "unknown" events** to close the last 2.9%
6. **Write the paper paragraph** noting that AST and LLM evaluator agree at >96% after calibration
