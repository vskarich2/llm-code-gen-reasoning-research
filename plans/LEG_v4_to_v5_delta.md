# LEG Plan — v4 → v5 Delta (Precision Pass)

**Core invariant of this delta:**
> "Even when the model semantically identifies the true failure mechanism, code generation still fails."

Every change below serves this claim. Nothing weakens it.

---

## 1. Exact Changes to Metric Definitions

### 1A. LEG_true — Redefined (FIX 1)

**v4 definition (REMOVED):**
```
LEG_true(k) = llm_eval_blind(k) == "YES"
              ∧ reasoning_matches_truth(k)
              ∧ ¬pass(k)

where reasoning_matches_truth(k) =
    _detect_failure_type_from_reasoning(reasoning_k) == classification(k).failure_type_final
```

**v5 definition (REPLACES):**
```
LEG_true(k) = llm_eval_blind_verdict(k) == "YES"
              ∧ llm_eval_blind_type(k) == classification(k).failure_type_final
              ∧ llm_eval_blind_type(k) != "UNKNOWN"
              ∧ ¬pass(k)
```

What changed: `reasoning_matches_truth` no longer uses the heuristic keyword parser `_detect_failure_type_from_reasoning()`. Instead, the BLIND LLM evaluator itself infers the failure type (`llm_eval_blind_type`). The match is between the evaluator's semantically inferred type and the classifier's structurally detected type. Both are imperfect, but their agreement is strong evidence.

**Why this is stronger:** The heuristic parser matches surface keywords ("order" → TEMPORAL_ORDERING). The LLM evaluator reads the reasoning, the code, and the test failure, then independently infers which failure type the reasoning describes. If the evaluator's semantic inference agrees with the classifier's structural detection, the reasoning genuinely identifies the true mechanism — not just a keyword.

**What the heuristic parser still does:** It remains as `keyword_signal` for LEG_keyword, for `signal_overlap_rate` computation, for cheap pre-filtering, and for backward compatibility. It is NOT part of LEG_true.

### 1B. LEG_coupling and LEG_execution — New Subtypes (FIX 4)

**LEG_coupling:**
```
LEG_coupling(k) = LEG_true(k) ∧ alignment_success(k) == False
```

**LEG_execution:**
```
LEG_execution(k) = LEG_true(k) ∧ alignment_success(k) == True
```

**Where alignment_success is defined as:**
```
alignment_success(k) = plan_matches_failure(k) == True
                       ∧ step_coverage(k) >= 0.5
```

I use the thresholded version (`alignment_success`) rather than raw `alignment_score < threshold` because:
- `plan_matches_failure` guards against wrong-plan cases (the plan must address the actual failure type)
- The threshold (0.5) is already established in `_validate_plan_coverage`
- Using two jointly necessary conditions reduces false classification of alignment

**When alignment data is unavailable** (non-alignment conditions): LEG_coupling and LEG_execution are both `None`. They are only computable for the `retry_alignment` condition. For other conditions, only aggregate LEG_true is reported.

**Interpretation:**
- If LEG_coupling >> LEG_execution: the bottleneck is reasoning→code translation. The model knows what to do but doesn't do it.
- If LEG_execution >> LEG_coupling: the bottleneck is execution fidelity. The model translates its reasoning into code, but the code is still wrong at a level below the plan.
- If both are high: both mechanisms contribute.

### 1C. Alignment Analysis Uses LEG_true (FIX 2)

**v4 `_compute_alignment_leg_split` (REMOVED):**
Used `latent_signal.correct_pattern_in_reasoning` (keyword-based).

**v5 (REPLACES):**

```python
def _compute_alignment_leg_split(trajectory):
    """LEG_true rate conditioned on alignment_success.

    Primary analysis: uses LEG_true (semantic evaluator + classifier match).
    Diagnostic fallback: also computes keyword-based split.
    """
    aligned_true = []     # alignment_success == True, LEG_true events
    unaligned_true = []   # alignment_success == False, LEG_true events
    aligned_kw = []       # same split but keyword LEG (fallback)
    unaligned_kw = []
    raw_scores = []       # all alignment_scores for distribution

    for e in trajectory:
        if e["pass"]:
            continue
        pa = e.get("plan_alignment")
        pmf = e.get("plan_matches_failure")
        if pa is None:
            continue  # not an alignment condition

        score = pa.get("step_coverage", 0)
        raw_scores.append(score)
        is_aligned = pa.get("aligned", False) and pmf is True

        is_leg_true = e.get("leg_true", False)
        is_leg_kw = e.get("leg_keyword_only", False)

        if is_aligned:
            aligned_true.append(is_leg_true)
            aligned_kw.append(is_leg_kw)
        else:
            unaligned_true.append(is_leg_true)
            unaligned_kw.append(is_leg_kw)

    def rate(lst):
        return round(sum(lst) / len(lst), 3) if lst else None

    # Score distribution buckets
    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for s in raw_scores:
        if s < 0.2: buckets["0.0-0.2"] += 1
        elif s < 0.4: buckets["0.2-0.4"] += 1
        elif s < 0.6: buckets["0.4-0.6"] += 1
        elif s < 0.8: buckets["0.6-0.8"] += 1
        else: buckets["0.8-1.0"] += 1

    return {
        # Primary (LEG_true)
        "leg_true_when_aligned": rate(aligned_true),
        "leg_true_when_not_aligned": rate(unaligned_true),
        "aligned_count": len(aligned_true),
        "unaligned_count": len(unaligned_true),
        # Diagnostic fallback (keyword)
        "leg_keyword_when_aligned": rate(aligned_kw),
        "leg_keyword_when_not_aligned": rate(unaligned_kw),
        # Raw distribution
        "alignment_score_distribution": buckets,
        "alignment_score_values": [round(s, 3) for s in raw_scores],
    }
```

**Explicit interpretation rule (written in the plan, not implied):**
- If `leg_true_when_aligned` << `leg_true_when_not_aligned`: alignment is associated with reduced reasoning→code failure. This supports H1 (underspecified reasoning → plan helps).
- If they are similar: alignment may not be the relevant mechanism. The translation gap persists even when the plan is correctly implemented at the step level.

### 1D. Metric Hierarchy — Explicit (MINOR 2)

**Primary metric (all claims rest on this):**
```
LEG_true
```

**Primary robustness check (all-signal consensus, does not require LLM type inference):**
```
LEG_strong_primary (VERY_HIGH confidence)
```

**Secondary / exploratory (reported for completeness, not primary evidence):**
```
LEG_strong_secondary (HIGH confidence)
LEG_weak (MEDIUM confidence)
LEG_keyword (backward compatibility / upper bound)
```

**Subtype decomposition (alignment condition only):**
```
LEG_coupling (LEG_true + not aligned)
LEG_execution (LEG_true + aligned)
```

This hierarchy is fixed. No section of the plan or analysis should present a weaker metric as though it carries equal weight to LEG_true.

### 1E. bias_rate — Redefined (MINOR 1)

**v4 (REMOVED):**
```
bias_rate = (conditioned_yes - blind_yes) / total
```

**v5 (REPLACES):**
```
bias_rate_relative = (conditioned_yes - blind_yes) / blind_yes    [if blind_yes > 0, else None]
bias_rate_absolute = (conditioned_yes - blind_yes) / total        [always computable, diagnostic]
```

`bias_rate_relative` is the primary reported metric. It measures: "how much does seeing the classifier type inflate the evaluator's YES rate, relative to the blind baseline?"

Example: blind_yes=10, conditioned_yes=14, total=20
- bias_rate_relative = (14-10)/10 = 0.40 (40% inflation)
- bias_rate_absolute = (14-10)/20 = 0.20

The relative form is more interpretable: "the conditioned evaluator says YES 40% more often than the blind evaluator."

---

## 2. Exact Changes to Evaluator Prompt and Output Schema

### 2A. BLIND Evaluator Prompt (Updated — FIX 1)

```python
_CRIT_LITE_BLIND_PROMPT = """You are evaluating whether a developer's reasoning correctly identifies the ROOT CAUSE of a code failure.

IMPORTANT: You are ONLY evaluating whether the reasoning correctly identifies the failure mechanism. You are NOT evaluating code quality, style, or whether the fix works.

# Inputs

## Code (FAILED)
```python
{code}
```

## Test Failure (Structured)
Category: {error_category}
Message: {error_message}
Failed assertions:
{test_reasons}

## Developer's Reasoning
{reasoning}

# TASK

## Phase 1: Evaluate reasoning correctness

1. FAILURE TYPE MATCH: Does the reasoning identify the type of failure?
2. MECHANISM IDENTIFICATION: Does the reasoning explain HOW the failure occurs?
3. ERROR CONNECTION: Does the reasoning connect the mechanism to the test failure?

## Phase 2: Classify

- YES: reasoning correctly identifies failure type AND mechanism AND explains the error
- PARTIAL: identifies general area but misses specific mechanism OR does not connect to error
- NO: reasoning is incorrect, irrelevant, or identifies wrong mechanism

## Phase 3: Infer failure type

Based on the code, test failure, and reasoning, what type of failure is occurring?

Choose EXACTLY one from this list:
- TEMPORAL_ORDERING (operations happen in wrong order / stale reads)
- HIDDEN_DEPENDENCY (missing import, undefined reference, implicit coupling)
- INVARIANT_VIOLATION (conservation law, atomicity, consistency broken)
- PARTIAL_STATE_UPDATE (some fields updated, others missed)
- RETRY_LOGIC_BUG (duplication, idempotency failure, retry side effects)
- EDGE_CASE_MISSED (null, empty, boundary, off-by-one)
- LOGGING_INCONSISTENCY (side effects, logging, audit trail ordering)
- UNKNOWN (cannot confidently determine)

# RULES

- Be CONSERVATIVE — only YES if clearly correct
- Do NOT reward vague reasoning
- Do NOT infer correctness if mechanism is missing
- Prefer PARTIAL over YES if uncertain
- For failure type: choose based on the CODE and TEST FAILURE, not only on the reasoning

# OUTPUT

Return EXACTLY in this format (verdict semicolon type):

VERDICT ; FAILURE_TYPE

Examples:
YES ; TEMPORAL_ORDERING
PARTIAL ; HIDDEN_DEPENDENCY
NO ; UNKNOWN"""
```

### 2B. CONDITIONED Evaluator Prompt (adds classifier_type)

Same as blind, with one addition after `## Developer's Reasoning`:
```
## System-Detected Failure Type
{classifier_type}
```

### 2C. Parsing Logic

```python
_VALID_FAILURE_TYPES = frozenset([
    "TEMPORAL_ORDERING", "HIDDEN_DEPENDENCY", "INVARIANT_VIOLATION",
    "PARTIAL_STATE_UPDATE", "RETRY_LOGIC_BUG", "EDGE_CASE_MISSED",
    "LOGGING_INCONSISTENCY", "UNKNOWN",
])

def _parse_evaluator_response(raw):
    """Parse 'VERDICT ; TYPE' response.

    Returns: (verdict, inferred_type) or (None, None) on failure.
    """
    if not raw or not raw.strip():
        return None, None
    # Try parsing "YES ; TEMPORAL_ORDERING"
    parts = raw.strip().split(";")
    if len(parts) >= 2:
        verdict = parts[0].strip().upper()
        inferred_type = parts[1].strip().upper().replace(" ", "_")
    else:
        # Fallback: first word is verdict, try to find type
        words = raw.strip().upper().split()
        verdict = words[0] if words else None
        inferred_type = "UNKNOWN"
        for w in words:
            cleaned = w.strip().replace(" ", "_")
            if cleaned in _VALID_FAILURE_TYPES:
                inferred_type = cleaned
                break

    if verdict not in ("YES", "PARTIAL", "NO"):
        return None, None
    if inferred_type not in _VALID_FAILURE_TYPES:
        inferred_type = "UNKNOWN"

    return verdict, inferred_type
```

### 2D. Updated Evaluator Function

```python
def _evaluate_reasoning_correctness(model, reasoning_text, code_k,
                                     error_obj, classifier_type=None, blind=True):
    """CRIT-lite evaluator. ANALYSIS ONLY.

    Returns: {"verdict": str, "inferred_type": str} or {"verdict": None, "inferred_type": None}
    """
    error_category = error_obj.get("category", "unknown")
    error_message = (error_obj.get("message") or "")[:300]
    test_reasons = "\n".join(f"- {r}" for r in (error_obj.get("reasons") or [])[:5])

    if blind:
        prompt = _CRIT_LITE_BLIND_PROMPT.format(
            code=code_k[:1200],
            error_category=error_category,
            error_message=error_message,
            test_reasons=test_reasons,
            reasoning=reasoning_text[:800],
        )
    else:
        prompt = _CRIT_LITE_CONDITIONED_PROMPT.format(
            code=code_k[:1200],
            error_category=error_category,
            error_message=error_message,
            test_reasons=test_reasons,
            reasoning=reasoning_text[:800],
            classifier_type=classifier_type or "UNKNOWN",
        )

    try:
        raw = call_model(prompt, model=model, raw=True)
        verdict, inferred_type = _parse_evaluator_response(raw)
        return {"verdict": verdict, "inferred_type": inferred_type}
    except Exception:
        return {"verdict": None, "inferred_type": None}
```

---

## 3. Exact Changes to Alignment Analysis

### 3A. alignment_success Definition

```
alignment_success(k) = plan_matches_failure(k) == True
                       ∧ plan_alignment(k).step_coverage >= 0.5
```

Both conditions must hold. This is not new — it was in v4. What is new is that this exact definition is now the gating condition for LEG_coupling vs LEG_execution.

### 3B. LEG_coupling and LEG_execution

```
LEG_coupling(k) = LEG_true(k) ∧ ¬alignment_success(k)
LEG_execution(k) = LEG_true(k) ∧ alignment_success(k)
```

Justification for using `alignment_success` (thresholded) rather than raw `alignment_score < X`:
- `alignment_success` requires `plan_matches_failure == True`, which guards against wrong-topic plans. A plan about "ordering" when the bug is "NameError" should not count as "aligned" regardless of step_coverage.
- The 0.5 threshold on step_coverage is the same one used elsewhere in the system. Changing it later can be explored via the raw score distribution.

### 3C. Raw Score Distribution

`alignment_leg_split` now includes `alignment_score_values` (full list) and `alignment_score_distribution` (bucketed histogram). This allows threshold sensitivity analysis without re-running experiments.

### 3D. Explicit Interpretation

Written in the plan, not implied:

> If `leg_true_when_aligned` is substantially lower than `leg_true_when_not_aligned`, the alignment intervention is associated with reduced LEG. This means that forcing the model to make its plan explicit, and then checking whether the code implements the plan, helps close the reasoning→code gap.
>
> If the rates are similar, the gap persists even when the model's code appears to implement its plan. This points to LEG_execution — the model's plan-level reasoning is correct and translated, but the resulting code still fails at a finer granularity than the plan captures.
>
> The relative magnitude of LEG_coupling vs LEG_execution is the key diagnostic for distinguishing "translation failure" from "execution failure."

---

## 4. Exact Changes to Logging Schema

### 4A. Per-iteration — replace 2 fields, add 4 fields

**REMOVED:**
```json
"llm_eval_blind": "YES",           // old: single string
"llm_eval_conditioned": "PARTIAL"  // old: single string
```

**REPLACED WITH (MINOR 3):**
```json
"llm_eval_blind_verdict": "YES",
"llm_eval_blind_type": "TEMPORAL_ORDERING",
"llm_eval_conditioned_verdict": "PARTIAL",
"llm_eval_conditioned_type": "HIDDEN_DEPENDENCY"
```

**ADDED:**
```json
"reasoning_matches_truth": true,    // llm_eval_blind_type == classifier.failure_type_final
"leg_coupling": true,               // LEG_true ∧ ¬alignment_success (alignment cond only, else null)
"leg_execution": false              // LEG_true ∧ alignment_success (alignment cond only, else null)
```

**UNCHANGED from v4:**
```json
"reasoning_confidence": "VERY_HIGH",
"classifier_alignment": true,
"leg_true": true,
"leg_strong_primary": true,
"leg_weak": false,
"leg_keyword_only": true
```

### 4B. Per-summary — replace 2 fields, add 4 fields

**REMOVED:**
```json
"llm_eval_bias": {
    "blind_yes": 10,
    "conditioned_yes": 14,
    "total": 20,
    "bias_rate": 0.2
}
```

**REPLACED WITH (MINOR 1):**
```json
"llm_eval_bias": {
    "blind_yes": 10,
    "conditioned_yes": 14,
    "total": 20,
    "bias_rate_relative": 0.40,
    "bias_rate_absolute": 0.20
}
```

**ADDED:**
```json
"leg_coupling_rate": 0.25,
"leg_execution_rate": 0.15,
"alignment_leg_split": {
    "leg_true_when_aligned": 0.15,
    "leg_true_when_not_aligned": 0.55,
    "leg_keyword_when_aligned": 0.40,
    "leg_keyword_when_not_aligned": 0.80,
    "aligned_count": 10,
    "unaligned_count": 8,
    "alignment_score_distribution": {"0.0-0.2": 2, "0.2-0.4": 3, "0.4-0.6": 3, "0.6-0.8": 5, "0.8-1.0": 5},
    "alignment_score_values": [0.0, 0.2, 0.3, 0.5, 0.5, 0.6, 0.7, 0.8, 0.8, 0.9, ...]
}
```

**UNCHANGED from v4:**
```json
"leg_rate_true", "leg_rate_strong_primary", "leg_rate_strong_secondary",
"leg_rate_weak", "leg_rate_keyword", "leg_resolution_rate_true",
"signal_overlap_rate", "llm_eval_agreement", "plan_quality"
```

---

## 5. Exact Changes to Terminology and Interpretation

### 5A. "Independent" → "Complementary" (FIX 3)

Every instance of "independent" referring to the 3 signals is replaced:

**v4 (all instances removed):**
- "Three Independent Signals" (section header)
- "3 independent signals" (consensus rule docstring)
- Any prose referring to signal independence

**v5 (replaces with):**
- Section header: "Three Complementary Signals"
- Docstring: "3 complementary signals (partially correlated; see signal_overlap_rate)"

### 5B. Signal Overlap Interpretation — Explicit

Added to the interpretation section (not implied):

> **Signal complementarity and overlap.** The three LEG detection signals — keyword matching, classifier-reasoning alignment, and blind LLM evaluation — are complementary but not fully independent. The keyword signal and classifier-alignment signal share the same failure-type ontology and may fire on the same lexical features. `signal_overlap_rate` quantifies this redundancy.
>
> - If `signal_overlap_rate > 0.9`: the fast signals (keyword + classifier alignment) are measuring essentially the same thing. The consensus adds little information beyond the LLM evaluator. In this regime, LEG_true (which depends on the LLM evaluator's type inference) is the only metric that adds genuine new signal.
> - If `signal_overlap_rate` is moderate (0.4-0.7): the fast signals capture different aspects of reasoning correctness. The consensus is informative.
> - If `signal_overlap_rate < 0.3`: the signals are largely complementary. Agreement between them is meaningful evidence.
>
> Regardless of overlap, the primary claim (LEG_true) depends on the LLM evaluator's semantic type inference matching the classifier's structural detection. This cross-method agreement is the strongest evidence available without human annotation.

### 5C. LEG_true Strength/Weakness Discussion — Updated

> **Strength of LEG_true.** The primary metric is based on two complementary detection methods agreeing on the failure type: (1) a blind LLM evaluator that reads the reasoning, code, and test failure and infers the failure mechanism, and (2) a heuristic classifier that detects the failure type from error structure and critique signals. When both identify the same failure type, AND the LLM evaluator judges the reasoning as correct, the evidence for "model understood the true mechanism" is strong.
>
> **Weakness of LEG_true.** Both the evaluator and the classifier are imperfect. The evaluator is an LLM (subject to its own reasoning failures). The classifier uses keyword heuristics on critique and error signals. Their agreement reduces but does not eliminate false positives. The metric is a proxy for human judgment, not a replacement for it. A small-sample human annotation study would strengthen the claim.
>
> **What the heuristic keyword parser does NOT do.** The keyword parser (`_detect_latent_signal`) is NOT part of LEG_true. It is used only for LEG_keyword (backward compatibility), for signal_overlap_rate (measuring redundancy between fast signals), and for cheap pre-analysis. The primary scientific claim does not rest on keyword matching.

---

## 6. Implementation Caveats

### 6A. LLM Evaluator Now Returns Structured Output

The evaluator prompt asks for `VERDICT ; TYPE` on a single line. Models may not follow this format exactly. The parser `_parse_evaluator_response` handles:
- Correct format: `"YES ; TEMPORAL_ORDERING"` → `("YES", "TEMPORAL_ORDERING")`
- Missing semicolon: `"YES TEMPORAL_ORDERING"` → falls back to word-scanning
- Invalid type: `"YES ; SOMETHING_WRONG"` → type becomes `"UNKNOWN"`
- Garbage output: → `(None, None)`, entry logged as `verdict=None, type=None`, not counted in any LEG metric

**Risk:** If the evaluator frequently returns `UNKNOWN` as the inferred type, `reasoning_matches_truth` will be False even when the verdict is YES (because UNKNOWN ≠ any specific classifier type). This would suppress LEG_true.

**Mitigation:** Track `llm_eval_blind_type == "UNKNOWN"` rate in summary. If > 50%, the evaluator is not confident enough to infer types, and the analysis should fall back to LEG_strong_primary (consensus-based, does not require type inference).

### 6B. LEG_coupling and LEG_execution Only Exist for Alignment Condition

For `retry_no_contract`, `retry_adaptive`, and `baseline`: there is no plan, so `alignment_success` is undefined. The `leg_coupling` and `leg_execution` per-entry fields are `None`. The summary fields `leg_coupling_rate` and `leg_execution_rate` are `None`.

This is by design. The subtype decomposition is only meaningful when we have plan data to compare against.

### 6C. Additional API Cost from Type Inference

The evaluator prompt is slightly longer (adds the failure type vocabulary and Phase 3). Response may also be slightly longer. No meaningful cost increase — still 2 calls per failed attempt (blind + conditioned).

### 6D. _detect_failure_type_from_reasoning Still Exists

It is used for:
- `classifier_alignment` signal (does reasoning mention same type as classifier?)
- `keyword_signal` contribution to consensus
- `signal_overlap_rate` computation
- LEG_keyword backward compat

It is NOT used for LEG_true. This is stated explicitly in the plan and in the code docstring.
