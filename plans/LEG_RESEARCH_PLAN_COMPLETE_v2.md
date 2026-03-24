# Latent Execution Gap (LEG) — Complete Research & Implementation Plan v2

**Date:** 2026-03-23
**Status:** Plan (final, incorporates all refinements + 4 critical fixes)
**Grounded in:** V2 ablation data (51 cases × 3 conditions × 3 models)
**Supersedes:** `LEG_RESEARCH_PLAN.md`, `LEG_RESEARCH_PLAN_refinement.md`

---

## 1. Formal Definition

### LEG Event

A single attempt where:
- **reasoning is correct**: verified by hybrid consensus of 3 independent signals
- **code is incorrect**: fails execution-based invariant tests

Formally:
```
LEG(attempt_k) = reasoning_confidence(k) ∈ {HIGH, MEDIUM} ∧ ¬pass(k)
```

### Empirical Baseline (from V2 ablation)

| Metric | 4o-mini |
|---|---|
| LEG_rate (keyword-only, baseline) | 28/40 = **70%** |
| LEG_rate (keyword-only, retry) | 165/261 = **63%** |
| LEG → success transitions | 12/165 = **7.3%** |
| LEG persistence (max consecutive) | **5** |

---

## 2. Hybrid LEG Detection (3 Signals → Consensus)

### Three Independent Signals

| Signal | Source | Speed | Depth | Exists |
|---|---|---|---|---|
| keyword_signal | `_detect_latent_signal()` | Fast | Shallow | Yes |
| classifier_alignment_signal | Classifier type matches reasoning type (FIX 1) | Fast | Moderate | Needs modification |
| llm_eval_signal | CRIT-lite LLM evaluator (FIX 4) | Slow | Deep | New |

### FIX 1: Classifier Signal — Alignment Check, Not Raw Vote

The classifier's failure type alone is NOT evidence of correct reasoning. It only counts as a vote when the model's reasoning mentions the SAME failure type the classifier detected.

```python
def _classifier_agrees_with_reasoning(classification, reasoning_text):
    """Classifier vote: only counts if reasoning mentions the same failure type.

    This measures alignment between reasoning and actual failure,
    NOT classifier correctness alone.
    """
    if not classification or classification["failure_type_final"] == "UNKNOWN":
        return False

    # Extract what failure type the REASONING talks about
    reasoning_type = _detect_failure_type_from_reasoning(reasoning_text)
    if not reasoning_type:
        return False

    # Vote counts only if classifier and reasoning agree
    return classification["failure_type_final"] == reasoning_type


def _detect_failure_type_from_reasoning(reasoning_text):
    """Detect which failure type the reasoning text describes.

    Uses the same keyword sets as _LATENT_KEYWORDS but maps to
    classifier FAILURE_TYPES for comparison.
    """
    text_lower = reasoning_text.lower()

    # Map latent keywords → classifier types
    mapping = {
        "TEMPORAL_ORDERING": ["order", "before", "after", "sequence", "timing"],
        "HIDDEN_DEPENDENCY": ["dependency", "import", "missing", "undefined", "hidden"],
        "INVARIANT_VIOLATION": ["invariant", "balance", "conservation", "consistent", "atomic"],
        "PARTIAL_STATE_UPDATE": ["partial", "incomplete", "all fields", "both"],
        "RETRY_LOGIC_BUG": ["retry", "duplicate", "idempotent", "once"],
        "EDGE_CASE_MISSED": ["edge", "boundary", "null", "empty", "zero"],
        "LOGGING_INCONSISTENCY": ["log", "side effect", "record"],
    }

    for ftype, keywords in mapping.items():
        if any(kw in text_lower for kw in keywords):
            return ftype
    return None
```

### Consensus Rule (Updated with FIX 1)

```python
def _compute_reasoning_confidence(keyword_signal, classifier_alignment, llm_eval_signal):
    """Compute LEG confidence from 3 independent signals.

    keyword_signal: bool — reasoning text has correct failure-type keywords
    classifier_alignment: bool — classifier type MATCHES reasoning's identified type (FIX 1)
    llm_eval_signal: "YES" | "PARTIAL" | "NO" | None — CRIT-lite semantic probe
    """
    votes = 0
    if keyword_signal:
        votes += 1
    if classifier_alignment:  # FIX 1: only counts if reasoning matches classifier
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

---

## 3. LLM Evaluator — CRIT-Lite (FIX 4: Structured Evaluator)

### Prompt

```python
_CRIT_LITE_PROMPT = """You are evaluating whether a developer's reasoning correctly identifies the ROOT CAUSE of a code failure.

IMPORTANT:
You are NOT evaluating:
- code quality
- whether the fix works
- style or clarity

You are ONLY evaluating:
→ whether the reasoning correctly identifies the failure mechanism

---

# Inputs

## Code (FAILED)
```python
{code}
```

## Test Failure
{test_output}

## Model's Reasoning
{reasoning}

## Detected Failure Type (from system)
{classifier_type}

---

# TASK

Evaluate whether the reasoning correctly identifies the SPECIFIC FAILURE MECHANISM.

# PHASE 1 — DETECTION

1. FAILURE TYPE MATCH
Does the reasoning identify the same type of failure as the detected failure type?

2. MECHANISM IDENTIFICATION
Does the reasoning explain HOW the failure occurs (not just what is wrong)?

3. ERROR CONNECTION
Does the reasoning connect the mechanism to the observed test failure?

# PHASE 2 — CLASSIFICATION

- YES: reasoning correctly identifies failure type AND mechanism AND explains the error
- PARTIAL: reasoning identifies general area but misses specific mechanism OR does not connect to error
- NO: reasoning is incorrect, irrelevant, or identifies wrong mechanism

# RULES

- Be CONSERVATIVE — only answer YES if clearly correct
- Do NOT reward vague reasoning
- Do NOT infer correctness if mechanism is missing
- Prefer PARTIAL over YES if uncertain

# OUTPUT

Return EXACTLY one word:

YES
PARTIAL
NO"""
```

### Function

```python
def _evaluate_reasoning_correctness(model, reasoning_text, code_k, error_obj,
                                     test_output, classifier_type):
    """CRIT-lite semantic probe. ANALYSIS ONLY — never used in retry loop.

    Returns: "YES" | "PARTIAL" | "NO" | None (on failure)
    """
    prompt = _CRIT_LITE_PROMPT.format(
        code=code_k[:800],
        test_output=test_output[:300],
        reasoning=reasoning_text[:500],
        classifier_type=classifier_type or "UNKNOWN",
    )
    try:
        raw = call_model(prompt, model=model, raw=True)
        answer = raw.strip().upper().split()[0] if raw.strip() else "NO"
        if answer not in ("YES", "PARTIAL", "NO"):
            answer = "NO"
        return answer
    except Exception:
        return None
```

### Integration — ANALYSIS ONLY

Called **after the retry loop ends**, gated by `use_llm_eval` flag:

```python
if use_llm_eval:
    for entry in trajectory:
        if not entry["pass"] and entry.get("reasoning"):
            ft = entry.get("classification", {}).get("failure_type_final") if entry.get("classification") else None
            entry["llm_eval"] = _evaluate_reasoning_correctness(
                model, entry["reasoning"], entry["code"],
                entry["error"], _format_test_output(ev), ft
            )
            model_call_count += 1
        else:
            entry["llm_eval"] = None
```

### CRITICAL: Control/Analysis Split

The LLM evaluator is **NEVER** used in:
- Any `if` statement inside the retry loop
- Adaptive hint selection
- Trajectory context escalation
- Stop conditions

It is **ONLY** used in post-hoc summary fields.

---

## 4. Step-Level Alignment Validation (FIX 2 + FIX 3)

### FIX 2: Alignment Requires Action Token

The previous 30% keyword threshold was too permissive. Now requires BOTH keyword coverage AND at least one action token in the code.

```python
_ACTION_TOKENS = frozenset([
    '=', 'copy(', 'if ', 'for ', 'append(', 'return ', 'raise ',
    '.pop(', '.get(', '.update(', '.insert(', 'del ', 'import ',
    'try:', 'except', 'with ', '.clear(', '.add(',
])


def _step_implemented(step_text, code):
    """Check if a plan step is reflected in code.

    FIX 2: Requires BOTH keyword coverage AND action token presence.
    """
    keywords = _extract_action_keywords(step_text)
    if not keywords:
        return True  # can't check

    # Keyword coverage
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3

    # Action token check: code must contain at least one actual code modification
    has_action = any(tok in code for tok in _ACTION_TOKENS)

    return keyword_covered and has_action


def _extract_action_keywords(step_text):
    """Extract semantic action keywords from a plan step."""
    cleaned = re.sub(r'\b(in|the|a|an|to|of|for|and|or|by|with|from)\b', '', step_text.lower())
    words = re.findall(r'[a-zA-Z_]\w{3,}', cleaned)
    generic = {'should', 'must', 'need', 'change', 'update', 'make', 'ensure',
               'function', 'method', 'variable', 'code', 'line', 'file'}
    return [w for w in words if w not in generic]


def _validate_plan_coverage(plan, code):
    """Step-level alignment: check each plan step against code."""
    if not plan or not plan.get("steps"):
        return {"aligned": False, "step_coverage": 0.0,
                "steps_implemented": 0, "steps_total": 0, "per_step": []}

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

### FIX 3: Plan-Failure Match Uses Classifier Type

The previous `_plan_matches_failure` only checked syntax/runtime errors. Now compares the classifier's detected type against the plan's invariant text.

```python
def _plan_matches_failure(plan, error_obj, classification):
    """Does the plan address the actual failure type?

    FIX 3: Compares classifier_type with plan invariant / reasoning.
    If no semantic overlap → plan is wrong → NOT a LEG event.
    """
    if not plan or not plan.get("invariant"):
        return None  # can't check

    invariant_lower = plan["invariant"].lower()
    error_category = error_obj.get("category", "")

    # Hard mismatch: syntax/runtime error but plan talks about logic
    if error_category in ("syntax", "runtime", "load"):
        if error_category == "syntax" and "syntax" not in invariant_lower:
            return False
        if error_category == "runtime":
            err_type = (error_obj.get("message", "").split(":")[0] or "").lower()
            if err_type and err_type not in invariant_lower:
                return False

    # FIX 3: Compare classifier type with plan text
    if classification and classification.get("failure_type_final") != "UNKNOWN":
        classifier_type = classification["failure_type_final"].lower().replace("_", " ")
        # Check if ANY word from classifier type appears in plan invariant
        classifier_words = classifier_type.split()
        overlap = any(w in invariant_lower for w in classifier_words if len(w) > 3)
        if not overlap:
            # Also check plan steps
            steps_text = " ".join(plan.get("steps", [])).lower()
            overlap = any(w in steps_text for w in classifier_words if len(w) > 3)
        if not overlap:
            return False

    return True
```

---

## 5. Hypotheses

### H1: Reasoning is Underspecified

**Claim:** Reasoning identifies correct failure category but lacks executable specificity.

**Test:** Plan-then-code intervention (Experiment 1). If LEG rate drops with explicit plan, H1 supported.

### H2: Code Generation Ignores Reasoning (Loose Coupling)

**Claim:** Reasoning and code generation are loosely coupled internal processes.

**Test:** Reasoning echo intervention (Experiment 2). If echoing reasoning back reduces LEG, H2 supported.

### H3: Instruction Compliance Overrides Reasoning

**Claim:** Adversarial task prompts override correct reasoning.

**Test:** Compare LEG rate Level D (traps) vs Level A-C. **Testable NOW from existing data.**

### H4: Retry Anchors to Initial Mistake

**Claim:** Previous code context anchors subsequent attempts.

**Test:** Fresh retry without previous code (Experiment 4).

### H5: Multi-File Plumbing Failure

**Claim:** Multi-file cases have higher LEG due to coordination difficulty.

**Test:** LEG rate by file count. **Testable NOW from existing data.**

---

## 6. Experiment Designs

### Experiment 1: Plan-Then-Code (tests H1)

**Condition:** `retry_alignment`
**Control:** `retry_no_contract`
**Change:** Force structured PLAN before code, validate plan-code alignment
**Measured:** LEG rate, step_coverage, plan_parse_rate
**Expected if H1 true:** LEG rate drops ~50%

### Experiment 2: Reasoning Echo (tests H2)

**Condition:** `retry_echo`
**Control:** `retry_no_contract`
**Change:** Include model's own reasoning from previous attempt as explicit constraint
**Measured:** LEG rate, reasoning-code consistency
**Expected if H2 true:** LEG rate drops ~20%

### Experiment 3: Task Override (tests H3)

**Condition:** Modify Level D prompts to permit deviation from suggested simplification
**Control:** Original Level D prompts
**Measured:** LEG rate on Level D
**Expected if H3 true:** LEG rate drops dramatically on modified prompts

### Experiment 4: Fresh Retry (tests H4)

**Condition:** `retry_fresh`
**Control:** `retry_no_contract`
**Change:** No previous code in retry prompt, only original code + test feedback
**Measured:** LEG rate, code similarity, convergence
**Expected if H4 true:** More diverse code, possibly higher convergence

### Experiment 5: File Count (tests H5, no new code)

**Post-hoc analysis** of existing ablation data. Group by file count → compare LEG rate.

---

## 7. Alignment Intervention Design (`retry_alignment`)

### Prompt Template (initial attempt)

```
{task_description}

=== Code ===
{original_code}

Before writing code, output your fix plan in this EXACT format:

PLAN:
1. In [function_name]: [change description]
2. In [function_name]: [change description]
INVARIANT: [what must remain true after your changes]

Then output your complete fixed code.
```

### Prompt Template (retry after failure)

```
{task_description}

=== Original Code ===
{original_code}

=== Test Results (FAILED) ===
{test_output}

=== Your Previous Plan ===
{extracted_plan}

Your plan was correct but your code did not implement it.
Specifically: {plan_code_mismatch_description}

Revise your code to match your plan. Output:

PLAN: [updated plan if needed]
CODE: [complete fixed code]
```

### Plan Extraction

```python
def _extract_plan(raw_output):
    """Extract structured plan from model output."""
    plan_match = re.search(r'PLAN:\s*\n((?:\d+\..*\n?)+)', raw_output)
    invariant_match = re.search(r'INVARIANT:\s*(.*)', raw_output)
    if not plan_match:
        return None
    steps = re.findall(r'\d+\.\s*(.*)', plan_match.group(1))
    invariant = invariant_match.group(1).strip() if invariant_match else None
    return {"steps": steps, "invariant": invariant}
```

### Integration — CONTROL Signal (Plan Mismatch Feedback)

```python
# Inside retry loop, alignment condition only:
if use_alignment:
    plan = _extract_plan(raw)
    if plan and code_k:
        alignment = _validate_plan_coverage(plan, code_k)
        plan_match = _plan_matches_failure(plan, error_obj, classification)
        entry["plan"] = plan
        entry["plan_alignment"] = alignment
        entry["plan_matches_failure"] = plan_match

        # CONTROL: if plan exists but code doesn't match → feedback
        if not alignment["aligned"] and k < max_iterations - 1:
            trajectory_context = (
                f"Your plan has {alignment['steps_total']} steps but only "
                f"{alignment['steps_implemented']} are implemented in your code. "
                f"Implement your plan exactly."
            )
```

### Plan Quality Logging

```python
# In summary:
plan_entries = [e for e in trajectory if e.get("plan")]
if plan_entries:
    summary["plan_quality"] = {
        "parse_success_rate": round(len(plan_entries) / len(trajectory), 3),
        "avg_step_count": round(sum(len(e["plan"]["steps"]) for e in plan_entries) / len(plan_entries), 1),
        "avg_step_coverage": round(sum(e.get("plan_alignment", {}).get("step_coverage", 0) for e in plan_entries) / len(plan_entries), 3),
        "plan_matches_failure_rate": round(sum(1 for e in plan_entries if e.get("plan_matches_failure")) / len(plan_entries), 3),
    }

# Warning if plan parse rate is low
if plan_entries and len(plan_entries) / len(trajectory) < 0.5:
    _log.warning("LOW PLAN PARSE RATE for %s: %d/%d (%.0f%%)",
                 case["id"], len(plan_entries), len(trajectory),
                 100 * len(plan_entries) / len(trajectory))
```

---

## 8. Metrics

### LEG_rate (hybrid)
```
LEG_rate_hybrid = |{k : reasoning_confidence(k) ∈ {HIGH,MEDIUM} ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### LEG_rate (high confidence only)
```
LEG_rate_high = |{k : reasoning_confidence(k) = HIGH ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### LEG_rate (keyword-only, backward compat)
```
LEG_rate_keyword = |{k : keyword_signal(k) ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### LEG_resolution_rate
```
LEG_resolution = |{k : LEG_hybrid(k) ∧ pass(k+1)}| / |{k : LEG_hybrid(k)}|
```

### LEG_persistence
```
LEG_persistence = max consecutive hybrid LEG events in trajectory
```

### alignment_score
```
alignment_score = step_coverage (fraction of plan steps reflected in code, with action token check)
```

### llm_eval_agreement
```
agreement_rate = |{k : llm_eval(k) agrees with keyword_signal(k)}| / |{k : both exist}|
```

### LEG_by_level
```
LEG_rate_level_X = LEG_rate_hybrid restricted to Level X cases
```

---

## 9. Logging Schema (New Fields Only)

### Per-iteration — 5 new fields

```json
{
    "llm_eval": "YES",                    // CRIT-lite result (ANALYSIS ONLY)
    "reasoning_confidence": "HIGH",       // 3-signal consensus
    "leg_event": true,                    // hybrid LEG
    "leg_keyword_only": true,             // backward compat
    "classifier_alignment": true          // FIX 1: classifier agrees with reasoning
}
```

### Per-iteration (alignment condition) — 3 new fields

```json
{
    "plan": {"steps": [...], "invariant": "..."},
    "plan_alignment": {"aligned": true, "step_coverage": 0.8, ...},
    "plan_matches_failure": true
}
```

### Per-summary — 6 new fields

```json
{
    "leg_rate_hybrid": 0.63,
    "leg_rate_keyword": 0.70,
    "leg_rate_high_confidence": 0.45,
    "leg_resolution_rate": 0.073,
    "llm_eval_agreement": {
        "keyword_llm_agree": 12,
        "keyword_llm_disagree": 5,
        "classifier_llm_agree": 10,
        "classifier_llm_disagree": 7,
        "agreement_rate": 0.71
    },
    "plan_quality": {
        "parse_success_rate": 0.85,
        "avg_step_count": 2.3,
        "avg_step_coverage": 0.65,
        "plan_matches_failure_rate": 0.90
    }
}
```

---

## 10. Control vs Analysis Split (STRICT)

### CONTROL (inside retry loop, may influence prompts)

| Signal | Used For |
|---|---|
| consecutive_same_failure | Escalation ("try different strategy") |
| similarity_to_previous | Stagnation detection |
| score_improving | Search broadening |
| failure_type | Adaptive hint selection |
| plan_alignment.aligned | Plan mismatch feedback (alignment condition only) |

### ANALYSIS (post-hoc only, NEVER in retry loop)

| Signal | Used For |
|---|---|
| llm_eval | Reasoning quality assessment |
| reasoning_confidence | LEG classification |
| leg_event / leg_keyword_only | LEG rate computation |
| classifier_alignment | Consensus signal |
| llm_eval_agreement | Signal reliability measurement |
| trajectory_dynamics | Regime classification |
| All aggregate metrics | Summary statistics |

---

## 11. Implementation Plan

### File-Level Changes

| File | Change | Lines |
|---|---|---|
| `retry_harness.py` | Add `_detect_failure_type_from_reasoning()`, `_classifier_agrees_with_reasoning()`, `_compute_reasoning_confidence()`, `_evaluate_reasoning_correctness()`, `_extract_plan()`, `_validate_plan_coverage()` (updated), `_plan_matches_failure()` (updated), `_step_implemented()` (updated), `_ACTION_TOKENS`, `use_alignment` flag, `use_llm_eval` flag, new entry/summary fields | ~150 |
| `runner.py` | Add `retry_alignment` condition dispatch | ~5 |
| `scripts/leg_analysis.py` | **NEW**: post-hoc LEG analysis on existing logs | ~80 |
| `tests/test_retry_harness.py` | Tests for new functions | ~30 |
| **Total** | | **~265** |

### Phase Order

```
Phase 1: scripts/leg_analysis.py               [NOW, 0 API calls]
  → H3 test (Level D vs A-C LEG rate)
  → H5 test (file count vs LEG rate)
  → Baseline LEG metrics for all 3 models

Phase 2: Alignment intervention code            [~100 lines]
  → _extract_plan, _validate_plan_coverage (FIX 2), _plan_matches_failure (FIX 3)
  → use_alignment flag in retry harness
  → retry_alignment condition in runner.py

Phase 3: Smoke test                             [~20 API calls]
  → 2 cases × retry_alignment × gpt-4o-mini

Phase 4: Hybrid LEG detection                   [~50 lines]
  → _detect_failure_type_from_reasoning (FIX 1)
  → _classifier_agrees_with_reasoning (FIX 1)
  → _compute_reasoning_confidence
  → New per-entry + summary fields

Phase 5: CRIT-lite evaluator                    [~40 lines]
  → _evaluate_reasoning_correctness (FIX 4)
  → use_llm_eval flag (default False)

Phase 6: Alignment ablation                     [~350 calls per model]
  → 51 cases × retry_alignment × gpt-4o-mini

Phase 7: LLM eval on existing logs              [~300 calls per model]
  → Run CRIT-lite on retry trajectories from V2 ablation
  → Compute hybrid LEG rates
```

---

## 12. Risks and Mitigations

### Risk 1: LEG Detection Noise (REDUCED by hybrid approach)

**Problem:** Keyword-only detection has high false positive rate.
**Mitigation:** Hybrid consensus requires ≥2 signals to agree. HIGH confidence requires LLM evaluator YES. Report LEG rates at all confidence levels. FIX 1 ensures classifier signal measures alignment, not just classifier correctness.

### Risk 2: Alignment Over-Constrains (REDUCED by FIX 2)

**Problem:** Plan requirement may hurt easy cases.
**Mitigation:** FIX 2 requires action tokens (actual code modification), not just keyword overlap. Compare per-level: if Level A degrades, intervention is too heavy.

### Risk 3: Plan Extraction Fails

**Problem:** Models may not follow PLAN/CODE format.
**Mitigation:** Fallback to regular retry if no plan extracted. Log parse rate. Warn if < 50%.

### Risk 4: Wrong Plan Counted as LEG (FIXED by FIX 3)

**Problem:** Model produces plan about "ordering" when the actual error is "NameError."
**Mitigation:** FIX 3 compares classifier type with plan invariant text. No semantic overlap → plan_matches_failure=False → not counted as LEG.

### Risk 5: LLM Evaluator Unreliable

**Problem:** CRIT-lite may disagree with other signals.
**Mitigation:** LLM eval is one of three signals, not ground truth. Agreement rate is explicitly tracked. Disagreements are logged and analyzed.

### Risk 6: Data Plumbing

**Problem:** New fields not logged.
**Mitigation:** Same dict pattern as all existing fields. Verify in smoke test. `use_llm_eval=False` by default.

---

## 13. Expected Outcomes by Hypothesis

| Hypothesis | If TRUE | If FALSE |
|---|---|---|
| H1: Underspecified reasoning | Plan-then-code reduces LEG ~50% | LEG unchanged with explicit plan |
| H2: Loose coupling | Reasoning echo reduces LEG ~20% | Model ignores echoed reasoning |
| H3: Instruction compliance | LEG_rate(D) >> LEG_rate(A-C) by 2x+ | LEG uniform across levels |
| H4: Retry anchoring | Fresh retry: similarity < 0.8, higher convergence | Similar code without previous attempt |
| H5: Multi-file plumbing | LEG_rate(3+ files) >> LEG_rate(1 file) | LEG uniform across file counts |

**Immediately testable (existing data):** H3, H5
**Highest expected impact:** H1 (plan-then-code)
**Most novel finding potential:** H2 (loose coupling → fundamental LLM architecture insight)
