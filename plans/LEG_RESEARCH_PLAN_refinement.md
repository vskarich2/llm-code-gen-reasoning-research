# LEG Research Plan — Final Refinement

**Date:** 2026-03-23
**Type:** Delta to `LEG_RESEARCH_PLAN.md`
**Scope:** 6 targeted changes, <200 lines new code

---

## 1. Updated LEG Definition (Hybrid Detection)

### Three Independent Signals

| Signal | Source | Speed | Depth | Already Exists |
|---|---|---|---|---|
| keyword_signal | `_detect_latent_signal()` in retry_harness.py | Fast | Shallow | Yes |
| classifier_signal | `classify_failure()` in failure_classifier.py | Fast | Moderate | Yes |
| llm_eval_signal | NEW: `_evaluate_reasoning_correctness()` | Slow (1 LLM call) | Deep | No |

### Consensus Rule

```python
def _compute_reasoning_confidence(keyword_signal, classifier_signal, llm_eval_signal):
    """Compute LEG confidence from 3 independent signals.

    keyword_signal: bool (from _detect_latent_signal)
    classifier_signal: str failure_type that matches the actual error pattern
    llm_eval_signal: "YES" | "PARTIAL" | "NO" | None (from LLM evaluator)
    """
    votes = 0
    if keyword_signal:
        votes += 1
    if classifier_signal:  # classifier identified a specific (non-UNKNOWN) type
        votes += 1
    if llm_eval_signal == "YES":
        votes += 1
    elif llm_eval_signal == "PARTIAL":
        votes += 0.5

    if votes >= 2 and llm_eval_signal == "YES":
        return "HIGH"
    elif votes >= 2:
        return "MEDIUM"
    elif votes >= 1:
        return "LOW"
    else:
        return "NONE"
```

### Updated LEG Event

```
LEG(attempt_k) = reasoning_confidence(k) ∈ {HIGH, MEDIUM} ∧ ¬pass(k)
```

The old definition (keyword-only) is preserved as `LEG_keyword` for backward compatibility. The new hybrid definition is `LEG_hybrid`. Both are logged. Analysis can filter by either.

---

## 2. LLM Evaluator Design

### Function

```python
def _evaluate_reasoning_correctness(model, reasoning_text, code_k, error_obj, test_output):
    """Semantic probe: does the reasoning correctly identify the root cause?

    ANALYSIS ONLY — never used in retry loop control.
    Returns: "YES" | "PARTIAL" | "NO"
    """
    prompt = f"""You are evaluating whether a developer's reasoning correctly identifies the root cause of a code failure.

=== Developer's Reasoning ===
{reasoning_text[:500]}

=== Their Code (which FAILED tests) ===
```python
{code_k[:800]}
```

=== Test Failure ===
{test_output[:300]}

Does the reasoning correctly identify WHY the code fails?

Answer EXACTLY one word:
- YES: reasoning correctly identifies the specific root cause
- PARTIAL: reasoning identifies the general area but misses the specific mechanism
- NO: reasoning is wrong or irrelevant to the actual failure

Answer:"""

    try:
        raw = call_model(prompt, model=model, raw=True)
        answer = raw.strip().upper().split()[0] if raw.strip() else "NO"
        if answer not in ("YES", "PARTIAL", "NO"):
            answer = "NO"
        return answer
    except Exception:
        return None  # evaluator failed, don't count
```

### Integration Point

Called **post-hoc in summary construction**, NOT inside the retry loop:

```python
# After the retry loop ends, before building summary:
# Only evaluate LEG on failed attempts (saves API calls)
for entry in trajectory:
    if not entry["pass"] and entry.get("reasoning"):
        entry["llm_eval"] = _evaluate_reasoning_correctness(
            model, entry["reasoning"], entry["code"],
            entry["error"], _format_test_output_from_entry(entry)
        )
        model_call_count += 1
    else:
        entry["llm_eval"] = None
```

### Cost

One LLM call per failed attempt. For 51 cases × 2 retry conditions × ~3 avg failed attempts = ~306 additional calls per model. This is significant — can be gated by a `use_llm_eval=True` flag.

### CRITICAL: Control/Analysis Split

The LLM evaluator is **ANALYSIS ONLY**. It is:
- NOT used in any `if` statement inside the retry loop
- NOT used to select adaptive hints
- NOT used to determine retry behavior
- ONLY computed after all iterations complete
- ONLY logged for post-hoc analysis

---

## 3. Step-Level Alignment Validation

### Replacing Lexical Matching

The current `_validate_plan_coverage` matches function names. The upgrade extracts action keywords from each plan step.

```python
def _extract_action_keywords(step_text):
    """Extract semantic action keywords from a plan step.

    'In create_config: add .copy() to prevent aliasing'
    → ['copy', 'prevent', 'aliasing', 'create_config']
    """
    # Remove filler
    cleaned = re.sub(r'\b(in|the|a|an|to|of|for|and|or|by|with|from)\b', '', step_text.lower())
    # Extract words > 3 chars that aren't generic
    words = re.findall(r'[a-zA-Z_]\w{3,}', cleaned)
    generic = {'should', 'must', 'need', 'change', 'update', 'make', 'ensure',
               'function', 'method', 'variable', 'code', 'line', 'file'}
    return [w for w in words if w not in generic]


def _step_implemented(step_text, code):
    """Check if a plan step's action keywords appear in the code."""
    keywords = _extract_action_keywords(step_text)
    if not keywords:
        return True  # can't check, assume implemented
    hits = sum(1 for kw in keywords if kw in code.lower())
    return hits / len(keywords) >= 0.3  # at least 30% of keywords present


def _validate_plan_coverage(plan, code):
    """Step-level alignment: check each plan step against code."""
    if not plan or not plan.get("steps"):
        return {"aligned": False, "step_coverage": 0.0,
                "steps_implemented": 0, "steps_total": 0,
                "per_step": []}

    per_step = []
    implemented = 0
    for step in plan["steps"]:
        is_impl = _step_implemented(step, code)
        per_step.append({"step": step[:80], "implemented": is_impl})
        if is_impl:
            implemented += 1

    coverage = implemented / len(plan["steps"])
    return {
        "aligned": coverage >= 0.5,
        "step_coverage": round(coverage, 3),
        "steps_implemented": implemented,
        "steps_total": len(plan["steps"]),
        "per_step": per_step,
    }
```

### Plan Correctness Check

```python
def _plan_matches_failure(plan, error_obj, critique):
    """Does the plan address the actual failure type?

    If the plan talks about 'ordering' but the error is 'NameError',
    the plan is wrong — this is NOT a LEG event.
    """
    if not plan or not plan.get("invariant"):
        return None  # can't check

    invariant_lower = plan["invariant"].lower()
    error_category = error_obj.get("category", "")

    # If error is syntax/runtime but plan talks about logic → mismatch
    if error_category in ("syntax", "runtime", "load"):
        # Check if plan mentions the actual error type
        if error_category == "syntax" and "syntax" not in invariant_lower:
            return False
        if error_category == "runtime":
            err_type = error_obj.get("message", "").split(":")[0] if error_obj.get("message") else ""
            if err_type and err_type.lower() not in invariant_lower:
                return False

    return True  # plan at least addresses a logic-level concern
```

---

## 4. Updated Logging Schema (Additions Only)

### Per-iteration entry — 4 new fields

```json
{
    "llm_eval": "YES",                    // LLM evaluator result (ANALYSIS ONLY)
    "reasoning_confidence": "HIGH",       // consensus of 3 signals
    "leg_event": true,                    // hybrid LEG: confidence ∈ {HIGH,MEDIUM} ∧ ¬pass
    "leg_keyword_only": true              // old definition for backward compat
}
```

### Per-iteration (alignment condition only) — 3 new fields

```json
{
    "plan": {"steps": ["..."], "invariant": "..."},
    "plan_alignment": {"aligned": true, "step_coverage": 0.8, "per_step": [...]},
    "plan_matches_failure": true
}
```

### Per-summary — 6 new fields

```json
{
    "leg_rate_hybrid": 0.63,              // LEG events / failed attempts (hybrid)
    "leg_rate_keyword": 0.70,             // LEG events / failed attempts (keyword-only)
    "leg_rate_high_confidence": 0.45,     // HIGH confidence LEG / failed attempts
    "leg_resolution_rate": 0.073,         // LEG → pass transitions / LEG events
    "llm_eval_agreement": {
        "keyword_llm_agree": 12,
        "keyword_llm_disagree": 5,
        "classifier_llm_agree": 10,
        "classifier_llm_disagree": 7,
        "agreement_rate": 0.71
    },
    "plan_quality": {                     // alignment condition only
        "parse_success_rate": 0.85,
        "avg_step_count": 2.3,
        "avg_step_coverage": 0.65,
        "plan_matches_failure_rate": 0.90
    }
}
```

---

## 5. Updated Metrics

### LEG_rate (hybrid)

```
LEG_rate_hybrid = |{k : reasoning_confidence(k) ∈ {HIGH,MEDIUM} ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### LEG_rate (high confidence only)

```
LEG_rate_high = |{k : reasoning_confidence(k) = HIGH ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### LEG_resolution_rate

```
LEG_resolution = |{k : LEG(k) ∧ pass(k+1)}| / |{k : LEG(k)}|
```

### alignment_score (step-level)

```
alignment_score = step_coverage (fraction of plan steps reflected in code)
```

### llm_eval_agreement

```
agreement_rate = |{k : llm_eval(k) agrees with keyword_signal(k)}| / |{k : both signals exist}|
```

### LEG_persistence (unchanged from v1)

```
LEG_persistence = max consecutive LEG events in trajectory
```

---

## 6. Implementation Plan

### File-Level Changes

| File | Change | Lines |
|---|---|---|
| `retry_harness.py` | Add `_evaluate_reasoning_correctness()`, `_compute_reasoning_confidence()`, `use_llm_eval` flag, `use_alignment` flag, plan extraction/validation, 6 new per-entry fields, 6 new summary fields | ~100 |
| `runner.py` | Add `retry_alignment` condition dispatch | ~5 |
| `scripts/leg_analysis.py` | **NEW**: post-hoc LEG analysis on existing logs | ~80 |
| `tests/test_retry_harness.py` | Tests for new functions | ~30 |
| **Total** | | **~215** |

Note: Slightly over the 200-line budget due to the LLM evaluator. If strict, the LLM evaluator can be deferred to a separate `scripts/leg_eval.py` post-hoc script (~40 lines out of the critical path).

### Phase Order

```
1. scripts/leg_analysis.py                    [post-hoc, no API, runs NOW]
   → H3 test (Level D vs A-C)
   → H5 test (file count)
   → Baseline LEG metrics for all 3 models

2. retry_harness.py: add use_alignment        [~60 lines]
   → plan extraction
   → step-level validation
   → plan quality logging

3. runner.py: retry_alignment condition        [~5 lines]

4. Smoke test: 2 cases × retry_alignment      [~20 API calls]

5. retry_harness.py: add use_llm_eval         [~40 lines]
   → LLM evaluator
   → reasoning_confidence
   → hybrid LEG fields

6. Full ablation: 51 cases × retry_alignment  [~350 calls per model]
   + LLM eval on existing retry logs          [~300 calls per model]
```

### What Is NOT Implemented

- LLM evaluator is NOT used for control (strict separation)
- Plan validation does NOT abort the retry loop (only logs)
- Alignment rejection only triggers trajectory context feedback (same mechanism as adaptive hints — CONTROL signals only)
- No new pipelines, no architectural changes

### Backward Compatibility

- `leg_keyword_only` preserves the old LEG definition
- All existing summary fields unchanged
- New fields are additive — old logs remain valid
- `use_llm_eval=False` by default — no extra API calls unless opted in
