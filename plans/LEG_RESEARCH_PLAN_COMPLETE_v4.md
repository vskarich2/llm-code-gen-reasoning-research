# Latent Execution Gap (LEG) — Complete Research & Implementation Plan v4

**Date:** 2026-03-23
**Status:** Plan (final)
**Grounded in:** V2 ablation data (51 cases × 3 conditions × 3 models)
**Supersedes:** All previous LEG plan documents

**Changes v3 → v4:**
- FIX 8: VERY_HIGH confidence tier (all 3 signals unanimous)
- FIX 9: LEG_true metric (reasoning matches actual failure type)
- FIX 10: Alignment causal metric (LEG rate when aligned vs not)
- Minor: directional bias_rate, structured failure context in evaluator

---

## 1. Formal Definition

### LEG Event

A single attempt where reasoning is correct but code is incorrect.

### Four Tiers

**LEG_true** (cleanest, strongest — FIX 9):
```
LEG_true(k) = llm_eval_blind(k) == "YES"
              ∧ reasoning_matches_truth(k)
              ∧ ¬pass(k)

where reasoning_matches_truth(k) =
    _detect_failure_type_from_reasoning(reasoning_k) == classification(k).failure_type_final
```
This is the most defensible claim: the model's reasoning identifies the SAME failure mechanism as the classifier detects, AND the blind LLM evaluator confirms the reasoning is correct, AND the code still fails.

**LEG_strong_primary** (all signals unanimous — FIX 8):
```
LEG_strong_primary(k) = reasoning_confidence(k) == VERY_HIGH ∧ ¬pass(k)

where VERY_HIGH = keyword_signal ∧ classifier_alignment ∧ llm_eval_blind == "YES"
```

**LEG_strong_secondary** (2+ signals agree + LLM YES):
```
LEG_strong_secondary(k) = reasoning_confidence(k) == HIGH ∧ ¬pass(k)
```

**LEG_weak** (exploratory):
```
LEG_weak(k) = reasoning_confidence(k) == MEDIUM ∧ ¬pass(k)
```

**LEG_keyword** (backward compat):
```
LEG_keyword(k) = keyword_signal(k) ∧ ¬pass(k)
```

All five are logged. `LEG_true` is the primary publishable claim. `LEG_strong_primary` is the secondary. Others are supporting evidence.

### Empirical Baseline (from V2 ablation, keyword-only)

| Metric | 4o-mini |
|---|---|
| LEG_rate (keyword-only, baseline) | 28/40 = **70%** |
| LEG_rate (keyword-only, retry) | 165/261 = **63%** |
| LEG → success transitions | 12/165 = **7.3%** |
| LEG persistence (max) | **5** |

---

## 2. Hybrid LEG Detection (3 Signals → Consensus)

### Three Independent Signals

| Signal | Source | Depth | Exists |
|---|---|---|---|
| keyword_signal | `_detect_latent_signal()` | Shallow | Yes |
| classifier_alignment_signal | Classifier type matches reasoning type | Moderate | Needs mod |
| llm_eval_blind_signal | CRIT-lite evaluator, blind mode | Deep | New |

### Signal 1: Keyword Detection (existing, unchanged)

```python
# _detect_latent_signal(reasoning_k, code_passed)
# → {correct_pattern_in_reasoning: bool, latent_reasoning_type: str}
```

### Signal 2: Classifier-Reasoning Alignment (unchanged from v2)

```python
def _classifier_agrees_with_reasoning(classification, reasoning_text):
    """Only counts if reasoning mentions the SAME failure type the classifier detected."""
    if not classification or classification["failure_type_final"] == "UNKNOWN":
        return False
    reasoning_type = _detect_failure_type_from_reasoning(reasoning_text)
    if not reasoning_type:
        return False
    return classification["failure_type_final"] == reasoning_type


def _detect_failure_type_from_reasoning(reasoning_text):
    """Detect which failure type the reasoning text describes."""
    text_lower = reasoning_text.lower()
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

### Signal 3: CRIT-Lite LLM Evaluator — Dual Mode

#### Mode A — BLIND (primary)

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

1. FAILURE TYPE MATCH: Does the reasoning identify the type of failure?
2. MECHANISM IDENTIFICATION: Does the reasoning explain HOW the failure occurs?
3. ERROR CONNECTION: Does the reasoning connect the mechanism to the test failure?

# CLASSIFICATION

- YES: reasoning correctly identifies failure type AND mechanism AND explains the error
- PARTIAL: identifies general area but misses specific mechanism OR does not connect to error
- NO: reasoning is incorrect, irrelevant, or identifies wrong mechanism

# RULES

- Be CONSERVATIVE — only YES if clearly correct
- Do NOT reward vague reasoning
- Do NOT infer correctness if mechanism is missing
- Prefer PARTIAL over YES if uncertain

Return EXACTLY one word: YES, PARTIAL, or NO"""
```

Note (minor improvement): Test failure now uses structured fields (category, message, reasons) instead of raw truncated test output. This reduces truncation bias and gives the evaluator clearer signal.

#### Mode B — CONDITIONED (secondary, adds classifier_type)

```python
_CRIT_LITE_CONDITIONED_PROMPT = _CRIT_LITE_BLIND_PROMPT.replace(
    "## Developer's Reasoning\n{reasoning}",
    "## Developer's Reasoning\n{reasoning}\n\n## System-Detected Failure Type\n{classifier_type}"
)
```

#### Function

```python
def _evaluate_reasoning_correctness(model, reasoning_text, code_k,
                                     error_obj, classifier_type=None, blind=True):
    """CRIT-lite evaluator. ANALYSIS ONLY — never in retry loop."""
    # Build structured failure context (minor improvement: no raw truncation)
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
        answer = raw.strip().upper().split()[0] if raw.strip() else "NO"
        if answer not in ("YES", "PARTIAL", "NO"):
            answer = "NO"
        return answer
    except Exception:
        return None
```

#### Integration — Post-Hoc, Both Modes

```python
if use_llm_eval:
    for entry in trajectory:
        if not entry["pass"] and entry.get("reasoning"):
            ft = (entry.get("classification", {}) or {}).get("failure_type_final")
            entry["llm_eval_blind"] = _evaluate_reasoning_correctness(
                model, entry["reasoning"], entry["code"],
                entry["error"], blind=True)
            entry["llm_eval_conditioned"] = _evaluate_reasoning_correctness(
                model, entry["reasoning"], entry["code"],
                entry["error"], classifier_type=ft, blind=False)
            model_call_count += 2
        else:
            entry["llm_eval_blind"] = None
            entry["llm_eval_conditioned"] = None
```

### Consensus Rule (FIX 8: adds VERY_HIGH)

```python
def _compute_reasoning_confidence(keyword_signal, classifier_alignment, llm_eval_blind):
    """Consensus from 3 independent signals. Uses BLIND evaluator only.

    VERY_HIGH: all 3 unanimous (FIX 8)
    HIGH: ≥2 agree + LLM=YES
    MEDIUM: ≥2 agree
    LOW: 1 signal
    NONE: 0 signals
    """
    votes = 0
    if keyword_signal:
        votes += 1
    if classifier_alignment:
        votes += 1
    if llm_eval_blind == "YES":
        votes += 1
    elif llm_eval_blind == "PARTIAL":
        votes += 0.5

    # FIX 8: all three unanimous
    if keyword_signal and classifier_alignment and llm_eval_blind == "YES":
        return "VERY_HIGH"
    elif votes >= 2 and llm_eval_blind == "YES":
        return "HIGH"
    elif votes >= 2:
        return "MEDIUM"
    elif votes >= 1:
        return "LOW"
    else:
        return "NONE"
```

### Reasoning-Truth Match (FIX 9)

```python
def _reasoning_matches_truth(reasoning_text, classification):
    """Does the reasoning identify the SAME failure type as the classifier?

    This is the foundation of LEG_true — the strongest LEG metric.
    """
    if not classification or classification["failure_type_final"] == "UNKNOWN":
        return False
    reasoning_type = _detect_failure_type_from_reasoning(reasoning_text)
    if not reasoning_type:
        return False
    return reasoning_type == classification["failure_type_final"]
```

Note: This is the same logic as `_classifier_agrees_with_reasoning`, extracted as a named concept for clarity. `LEG_true` uses both this AND `llm_eval_blind == "YES"`.

---

## 3. Step-Level Alignment Validation (unchanged from v2/v3)

### Action Token Requirement, Plan Extraction, Plan-Failure Match

All as previously defined. `_ACTION_TOKENS`, `_step_implemented()`, `_extract_plan()`, `_validate_plan_coverage()`, `_plan_matches_failure()` — unchanged.

### Structured Alignment Feedback (FIX 7 from v3, unchanged)

```python
if use_alignment and plan and not alignment["aligned"] and k < max_iterations - 1:
    missing_steps = [s["step"] for s in alignment["per_step"] if not s["implemented"]]
    trajectory_context = (
        f"Your plan has {alignment['steps_total']} steps, "
        f"but only {alignment['steps_implemented']} are implemented.\n\n"
        f"Missing steps:\n" +
        "\n".join(f"- {s}" for s in missing_steps[:3]) +
        "\n\nImplement ALL steps in your code."
    )
```

### Alignment Causal Metric (FIX 10)

```python
def _compute_alignment_leg_split(trajectory):
    """Compare LEG rate when plan is aligned vs not aligned.

    This isolates whether alignment reduces LEG.
    Returns None if not an alignment condition or insufficient data.
    """
    aligned_attempts = []
    unaligned_attempts = []

    for e in trajectory:
        if not e["pass"] and e.get("plan_alignment") is not None:
            pa = e["plan_alignment"]
            pmf = e.get("plan_matches_failure")
            is_aligned = pa.get("step_coverage", 0) >= 0.5 and pmf is True

            if is_aligned:
                aligned_attempts.append(e)
            else:
                unaligned_attempts.append(e)

    if not aligned_attempts and not unaligned_attempts:
        return None

    # LEG rate for each group (using keyword for now; hybrid computed post-hoc)
    def leg_rate(attempts):
        if not attempts:
            return None
        leg = sum(1 for a in attempts
                  if a.get("latent_signal", {}).get("correct_pattern_in_reasoning"))
        return round(leg / len(attempts), 3)

    return {
        "leg_rate_when_aligned": leg_rate(aligned_attempts),
        "leg_rate_when_not_aligned": leg_rate(unaligned_attempts),
        "aligned_count": len(aligned_attempts),
        "unaligned_count": len(unaligned_attempts),
    }
```

Logged in summary as `"alignment_leg_split"`. This directly tests whether plan-code alignment reduces the reasoning→code translation failure.

---

## 4. Hypotheses (unchanged)

| # | Hypothesis | Test | Testable Now? |
|---|---|---|---|
| H1 | Reasoning underspecified | Plan-then-code | Needs retry_alignment |
| H2 | Loose coupling | Reasoning echo + mapping | Needs retry_echo |
| H3 | Instruction compliance overrides | LEG by level | **YES** |
| H4 | Retry anchors | Fresh retry | Needs retry_fresh |
| H5 | Multi-file plumbing | LEG by file count | **YES** |

---

## 5. Experiment Designs (unchanged from v2/v3)

Experiments 1-5 as previously defined.

---

## 6. Alignment Intervention (`retry_alignment`) (unchanged except FIX 7, FIX 10)

Prompt templates, plan extraction, validation from v2. FIX 7 structured feedback from v3. FIX 10 alignment causal metric added to summary.

---

## 7. Metrics

### LEG Tiers (ordered by strength)

| Metric | Definition | Purpose |
|---|---|---|
| **LEG_true** | `llm_eval_blind == YES ∧ reasoning_matches_truth ∧ ¬pass` | Cleanest claim: model demonstrably understood the specific bug and still failed |
| **LEG_strong_primary** | `VERY_HIGH confidence ∧ ¬pass` | All 3 signals unanimous |
| **LEG_strong_secondary** | `HIGH confidence ∧ ¬pass` | 2+ signals + LLM YES |
| **LEG_weak** | `MEDIUM confidence ∧ ¬pass` | Exploratory |
| **LEG_keyword** | `keyword_signal ∧ ¬pass` | Backward compat / upper bound |

### Resolution Rates

```
LEG_resolution_true = |{k : LEG_true(k) ∧ pass(k+1)}| / |{k : LEG_true(k)}|
LEG_resolution_keyword = |{k : LEG_keyword(k) ∧ pass(k+1)}| / |{k : LEG_keyword(k)}|
```

### Persistence

```
LEG_persistence_true = max consecutive LEG_true events in trajectory
```

### Alignment (step-level)

```
alignment_score = step_coverage with action token check [0, 1]
```

### Alignment Causal (FIX 10)

```
LEG_rate_when_aligned = LEG rate restricted to attempts where step_coverage ≥ 0.5 ∧ plan_matches_failure
LEG_rate_when_not_aligned = LEG rate restricted to attempts where not aligned
```

If `LEG_rate_when_aligned << LEG_rate_when_not_aligned`, alignment reduces the translation gap.

### Evaluator Bias (minor improvement: directional)

```
bias_rate = (conditioned_yes_count - blind_yes_count) / total_evaluated
```

Positive = conditioned inflates YES (confirmation bias). Negative = conditioned suppresses YES. Near zero = no bias.

### Signal Overlap

```
signal_overlap_rate = |{k : keyword(k) ∧ classifier_alignment(k)}| / |{k : keyword(k) ∨ classifier_alignment(k)}|
```

### LEG by Level

```
LEG_true_level_X = LEG_true rate restricted to Level X cases
```

---

## 8. Logging Schema (All New Fields)

### Per-iteration — 9 new fields

```json
{
    "llm_eval_blind": "YES",
    "llm_eval_conditioned": "PARTIAL",
    "reasoning_confidence": "VERY_HIGH",
    "classifier_alignment": true,
    "reasoning_matches_truth": true,
    "leg_true": true,
    "leg_strong_primary": true,
    "leg_weak": false,
    "leg_keyword_only": true
}
```

### Per-iteration (alignment condition) — 3 fields (unchanged)

```json
{
    "plan": {"steps": [...], "invariant": "..."},
    "plan_alignment": {"aligned": true, "step_coverage": 0.8, "per_step": [...]},
    "plan_matches_failure": true
}
```

### Per-summary — 10 new fields

```json
{
    "leg_rate_true": 0.40,
    "leg_rate_strong_primary": 0.42,
    "leg_rate_strong_secondary": 0.50,
    "leg_rate_weak": 0.18,
    "leg_rate_keyword": 0.70,
    "leg_resolution_rate_true": 0.03,
    "signal_overlap_rate": 0.65,
    "llm_eval_bias": {
        "blind_yes": 10,
        "conditioned_yes": 14,
        "total": 20,
        "bias_rate": 0.2
    },
    "llm_eval_agreement": {
        "keyword_blind_agree": 12,
        "keyword_blind_disagree": 5,
        "classifier_blind_agree": 10,
        "classifier_blind_disagree": 7
    },
    "alignment_leg_split": {
        "leg_rate_when_aligned": 0.30,
        "leg_rate_when_not_aligned": 0.75,
        "aligned_count": 10,
        "unaligned_count": 8
    }
}
```

---

## 9. Control vs Analysis Split (STRICT, unchanged)

**CONTROL (retry loop):** consecutive_same_failure, similarity_to_previous, score_improving, failure_type, plan_alignment.aligned + missing steps feedback.

**ANALYSIS (post-hoc):** All LEG tiers, all evaluator outputs, confidence, alignment_leg_split, bias metrics. NEVER in retry loop `if` statements.

---

## 10. Implementation Plan

### File-Level Changes

| File | Change | Lines |
|---|---|---|
| `retry_harness.py` | `_detect_failure_type_from_reasoning()`, `_classifier_agrees_with_reasoning()`, `_reasoning_matches_truth()`, `_compute_reasoning_confidence()` (VERY_HIGH), `_evaluate_reasoning_correctness()` (dual mode, structured failure context), `_extract_plan()`, `_validate_plan_coverage()`, `_plan_matches_failure()`, `_compute_alignment_leg_split()`, `_ACTION_TOKENS`, flags, 9 per-entry fields, 10 summary fields, FIX 7 feedback | ~180 |
| `runner.py` | `retry_alignment` dispatch | ~5 |
| `scripts/leg_analysis.py` | **NEW**: post-hoc LEG analysis | ~80 |
| `tests/test_retry_harness.py` | Tests for new functions + LEG tiers | ~35 |
| **Total** | | **~300** |

### Phase Order

```
Phase 1: scripts/leg_analysis.py                    [NOW, 0 API calls]
  → H3: LEG_keyword by level (D vs A-C)
  → H5: LEG_keyword by file count
  → Baseline keyword LEG metrics for all 3 models

Phase 2: Alignment code                             [~90 lines]
  → Plan extraction, step-level validation, plan-failure match
  → FIX 7 structured feedback, FIX 10 alignment_leg_split
  → retry_alignment in runner.py

Phase 3: Smoke test alignment                       [~20 API calls]

Phase 4: Hybrid LEG detection + dual evaluator      [~90 lines]
  → Reasoning-truth match (FIX 9)
  → VERY_HIGH confidence (FIX 8)
  → Dual evaluator with structured failure context
  → All per-entry + summary fields

Phase 5: Alignment ablation                         [~350 calls per model]
  → 51 cases × retry_alignment × gpt-4o-mini

Phase 6: LLM eval on existing retry logs            [~600 calls per model]
  → Dual CRIT-lite on V2 ablation trajectories
  → Compute all LEG tier rates + bias + alignment split

Phase 7: Full analysis                              [0 API calls]
  → LEG_true rates across conditions and models
  → Alignment causal effect (FIX 10)
  → Evaluator bias measurement
  → H3 + H5 with hybrid confidence
```

---

## 11. Risks and Mitigations

### Risk 1: LEG_true Too Strict

**Problem:** Requiring BOTH `llm_eval_blind == YES` AND `reasoning_matches_truth` may produce very few LEG_true events.
**Mitigation:** Report all 5 tiers. If LEG_true count < 10, use LEG_strong_primary for analysis. The tier hierarchy ensures there's always a usable metric.

### Risk 2: Evaluator Confirmation Bias

**Problem:** Conditioned evaluator may inflate YES.
**Mitigation:** Primary analysis uses blind mode ONLY. `bias_rate` is directional (conditioned_yes - blind_yes) / total. If bias_rate > 0.2, conditioned results are flagged.

### Risk 3: Alignment Overconstrain

**Problem:** Plan requirement may hurt easy cases.
**Mitigation:** FIX 10 `alignment_leg_split` directly measures whether alignment helps or hurts. If `leg_rate_when_aligned ≈ leg_rate_when_not_aligned`, alignment is not the mechanism.

### Risk 4: Signal Redundancy

**Problem:** If `signal_overlap_rate > 0.9`, keyword and classifier signals are measuring the same thing — consensus adds no value.
**Mitigation:** Report overlap rate. If redundant, simplify to keyword + LLM eval only.

### Risks 5-7: Plan extraction, data plumbing, dual eval cost (unchanged from v3)

---

## 12. Expected Outcomes

| Hypothesis | If TRUE | If FALSE |
|---|---|---|
| H1: Underspecified | Plan-then-code reduces LEG_true ~50% | LEG_true unchanged |
| H2: Loose coupling | Reasoning echo reduces LEG_true ~20% | Model ignores own reasoning |
| H3: Instruction compliance | LEG_true(D) >> LEG_true(A-C) 2x+ | Uniform |
| H4: Retry anchoring | Fresh retry: similarity < 0.8 | Similar code regardless |
| H5: Multi-file plumbing | LEG_true(3+ files) >> LEG_true(1 file) | Uniform |

### Key Predictions

1. **LEG_true will be lower than LEG_keyword** — the keyword detector has high false positive rate. Expect LEG_true ≈ 30-40% vs LEG_keyword ≈ 63%.

2. **Evaluator bias_rate will be positive** — conditioned evaluator will say YES more often than blind, because it anchors on the classifier_type. Expect bias_rate ≈ 10-25%.

3. **alignment_leg_split will show signal** — `leg_rate_when_aligned < leg_rate_when_not_aligned`, confirming that when the model's plan matches its code, the translation gap is smaller.

4. **LEG_true on Level D (traps) will be very high** — the model's reasoning is correct (it identifies the trap) but its code complies with the adversarial instruction anyway. This is the purest form of LEG.
