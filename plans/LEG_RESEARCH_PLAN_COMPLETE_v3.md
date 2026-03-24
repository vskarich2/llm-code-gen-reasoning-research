# Latent Execution Gap (LEG) — Complete Research & Implementation Plan v3

**Date:** 2026-03-23
**Status:** Plan (final)
**Grounded in:** V2 ablation data (51 cases × 3 conditions × 3 models)
**Supersedes:** All previous LEG plan documents

**Changes v2 → v3:**
- FIX 5: Blind vs conditioned evaluator modes (removes confirmation bias)
- FIX 6: Strong vs Weak LEG split (reduces permissiveness)
- FIX 7: Structured alignment feedback with explicit missing steps

---

## 1. Formal Definition

### LEG Event

A single attempt where reasoning is correct but code is incorrect.

### Two Tiers (FIX 6)

**STRONG LEG** (primary result, publishable):
```
LEG_strong(k) = reasoning_confidence(k) == HIGH
                ∧ llm_eval_blind(k) == "YES"
                ∧ ¬pass(k)
```

**WEAK LEG** (exploratory, reported separately):
```
LEG_weak(k) = reasoning_confidence(k) == MEDIUM
              ∧ ¬pass(k)
```

**Keyword-only LEG** (backward compatibility):
```
LEG_keyword(k) = keyword_signal(k) ∧ ¬pass(k)
```

All three are logged. Strong LEG is the main analytical claim. Weak and keyword are supporting evidence.

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
# _detect_latent_signal(reasoning_k, code_passed) → {correct_pattern_in_reasoning, latent_reasoning_type}
# Uses _LATENT_KEYWORDS dict
```

### Signal 2: Classifier-Reasoning Alignment (from v2, unchanged)

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

### Signal 3: CRIT-Lite LLM Evaluator — Dual Mode (FIX 5)

Two modes to detect and measure confirmation bias:

#### Mode A — BLIND (primary, no classifier_type in prompt)

```python
_CRIT_LITE_BLIND_PROMPT = """You are evaluating whether a developer's reasoning correctly identifies the ROOT CAUSE of a code failure.

IMPORTANT: You are ONLY evaluating whether the reasoning correctly identifies the failure mechanism. You are NOT evaluating code quality, style, or whether the fix works.

# Inputs

## Code (FAILED)
```python
{code}
```

## Test Failure
{test_output}

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

#### Mode B — CONDITIONED (secondary, includes classifier_type)

```python
_CRIT_LITE_CONDITIONED_PROMPT = _CRIT_LITE_BLIND_PROMPT.replace(
    "## Developer's Reasoning\n{reasoning}",
    "## Developer's Reasoning\n{reasoning}\n\n## System-Detected Failure Type\n{classifier_type}"
)
```

#### Evaluator Function

```python
def _evaluate_reasoning_correctness(model, reasoning_text, code_k,
                                     test_output, classifier_type=None, blind=True):
    """CRIT-lite evaluator. ANALYSIS ONLY — never in retry loop.

    blind=True: Mode A (no classifier_type) — primary
    blind=False: Mode B (with classifier_type) — secondary
    """
    if blind:
        prompt = _CRIT_LITE_BLIND_PROMPT.format(
            code=code_k[:1200],
            test_output=test_output[:500],
            reasoning=reasoning_text[:800],
        )
    else:
        prompt = _CRIT_LITE_CONDITIONED_PROMPT.format(
            code=code_k[:1200],
            test_output=test_output[:500],
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

Note on truncation (minor improvement): Code capped at 1200 chars (was 800), test_output at 500 (was 300), reasoning at 800 (was 500). Reduces truncation bias on longer outputs.

#### Integration — Post-Hoc, Both Modes

```python
if use_llm_eval:
    for entry in trajectory:
        if not entry["pass"] and entry.get("reasoning"):
            test_out = _format_test_output(ev)
            ft = entry.get("classification", {}).get("failure_type_final") if entry.get("classification") else None

            # Mode A: blind (primary)
            entry["llm_eval_blind"] = _evaluate_reasoning_correctness(
                model, entry["reasoning"], entry["code"], test_out, blind=True)
            model_call_count += 1

            # Mode B: conditioned (secondary)
            entry["llm_eval_conditioned"] = _evaluate_reasoning_correctness(
                model, entry["reasoning"], entry["code"], test_out,
                classifier_type=ft, blind=False)
            model_call_count += 1
        else:
            entry["llm_eval_blind"] = None
            entry["llm_eval_conditioned"] = None
```

Cost: 2 LLM calls per failed attempt (was 1). ~600 calls per model for full eval. Gated by `use_llm_eval=True`.

#### Bias Metric

```python
# In summary:
blind_results = [e["llm_eval_blind"] for e in trajectory if e.get("llm_eval_blind")]
cond_results = [e["llm_eval_conditioned"] for e in trajectory if e.get("llm_eval_conditioned")]
agree = sum(1 for b, c in zip(blind_results, cond_results) if b == c)
total_both = min(len(blind_results), len(cond_results))
summary["llm_eval_bias"] = {
    "blind_yes": sum(1 for r in blind_results if r == "YES"),
    "conditioned_yes": sum(1 for r in cond_results if r == "YES"),
    "agreement": agree,
    "total": total_both,
    "bias_rate": round(1 - agree / total_both, 3) if total_both else 0.0,
}
```

### Consensus Rule (uses blind mode only)

```python
def _compute_reasoning_confidence(keyword_signal, classifier_alignment, llm_eval_blind):
    """Consensus from 3 independent signals. Uses BLIND evaluator only."""
    votes = 0
    if keyword_signal:
        votes += 1
    if classifier_alignment:
        votes += 1
    if llm_eval_blind == "YES":
        votes += 1
    elif llm_eval_blind == "PARTIAL":
        votes += 0.5

    if votes >= 2 and llm_eval_blind == "YES":
        return "HIGH"
    elif votes >= 2:
        return "MEDIUM"
    elif votes >= 1:
        return "LOW"
    else:
        return "NONE"
```

---

## 3. Step-Level Alignment Validation (from v2, unchanged)

### Action Token Requirement

```python
_ACTION_TOKENS = frozenset([
    '=', 'copy(', 'if ', 'for ', 'append(', 'return ', 'raise ',
    '.pop(', '.get(', '.update(', '.insert(', 'del ', 'import ',
    'try:', 'except', 'with ', '.clear(', '.add(',
])

def _step_implemented(step_text, code):
    keywords = _extract_action_keywords(step_text)
    if not keywords:
        return True
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3
    has_action = any(tok in code for tok in _ACTION_TOKENS)
    return keyword_covered and has_action
```

### Plan Validation (from v2, unchanged)

`_extract_plan()`, `_validate_plan_coverage()`, `_plan_matches_failure()` — all as defined in v2.

### Structured Alignment Feedback (FIX 7)

```python
# Inside retry loop, alignment condition, when plan exists but code doesn't match:
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

This replaces the generic "implement your plan exactly" with explicit enumeration of which steps are missing. Capped at 3 missing steps to avoid prompt bloat.

---

## 4. Hypotheses (unchanged from v2)

| # | Hypothesis | Test Method | Testable Now? |
|---|---|---|---|
| H1 | Reasoning is underspecified | Plan-then-code intervention | Needs retry_alignment |
| H2 | Loose coupling (reasoning ignored) | Reasoning echo intervention | Needs retry_echo |
| H3 | Instruction compliance overrides | LEG rate Level D vs A-C | **YES** |
| H4 | Retry anchors to initial mistake | Fresh retry (no prev code) | Needs retry_fresh |
| H5 | Multi-file plumbing failure | LEG rate by file count | **YES** |

### H2 Strengthening (minor improvement)

For the reasoning echo experiment, add explicit reasoning→code mapping requirement:

```
=== Your Own Analysis ===
You previously stated: "{reasoning_k-1}"

For EACH claim in your analysis, identify the SPECIFIC code change that implements it:
- Claim: [from your reasoning] → Code change: [line/function]

Your code did not implement your analysis. Fix it.
```

This forces the model to make the mapping explicit, testing whether the coupling failure is about implicit vs explicit translation.

---

## 5. Experiment Designs (unchanged from v2)

Experiments 1-5 as previously defined. Experiment 2 uses the strengthened H2 prompt above.

---

## 6. Alignment Intervention (`retry_alignment`) (unchanged except FIX 7)

Prompt templates, plan extraction, and validation logic from v2. The only change is the trajectory context feedback (FIX 7) which now lists specific missing steps.

---

## 7. Metrics

### Primary (Strong LEG)

```
LEG_rate_strong = |{k : LEG_strong(k)}| / |{k : ¬pass(k)}|
```

### Secondary (Weak LEG)

```
LEG_rate_weak = |{k : LEG_weak(k)}| / |{k : ¬pass(k)}|
```

### Backward Compatibility

```
LEG_rate_keyword = |{k : keyword_signal(k) ∧ ¬pass(k)}| / |{k : ¬pass(k)}|
```

### Resolution

```
LEG_resolution_strong = |{k : LEG_strong(k) ∧ pass(k+1)}| / |{k : LEG_strong(k)}|
```

### Persistence

```
LEG_persistence = max consecutive LEG_strong events in trajectory
```

### Alignment

```
alignment_score = step_coverage with action token check
```

### Evaluator Bias

```
llm_eval_bias_rate = |{k : blind(k) ≠ conditioned(k)}| / |{k : both exist}|
```

### Signal Overlap (minor improvement)

```
signal_overlap_rate = |{k : keyword(k) ∧ classifier_alignment(k)}| / |{k : either is True}|
```

Measures how correlated the fast signals are. If > 0.9, they're redundant. If < 0.5, they capture different aspects.

### LEG by Level

```
LEG_rate_strong_level_X = LEG_rate_strong restricted to Level X cases
```

---

## 8. Logging Schema (All New Fields)

### Per-iteration — 7 new fields

```json
{
    "llm_eval_blind": "YES",              // Mode A (no classifier_type)
    "llm_eval_conditioned": "PARTIAL",    // Mode B (with classifier_type)
    "reasoning_confidence": "HIGH",       // 3-signal consensus (uses blind only)
    "classifier_alignment": true,         // classifier agrees with reasoning
    "leg_strong": true,                   // HIGH confidence + blind=YES + failed
    "leg_weak": false,                    // MEDIUM confidence + failed
    "leg_keyword_only": true              // backward compat
}
```

### Per-iteration (alignment condition) — 3 fields (unchanged from v2)

```json
{
    "plan": {"steps": [...], "invariant": "..."},
    "plan_alignment": {"aligned": true, "step_coverage": 0.8, "per_step": [...]},
    "plan_matches_failure": true
}
```

### Per-summary — 8 new fields

```json
{
    "leg_rate_strong": 0.45,
    "leg_rate_weak": 0.18,
    "leg_rate_keyword": 0.70,
    "leg_resolution_rate_strong": 0.05,
    "signal_overlap_rate": 0.65,
    "llm_eval_bias": {
        "blind_yes": 10,
        "conditioned_yes": 14,
        "agreement": 15,
        "total": 20,
        "bias_rate": 0.25
    },
    "llm_eval_agreement": {
        "keyword_blind_agree": 12,
        "keyword_blind_disagree": 5,
        "classifier_blind_agree": 10,
        "classifier_blind_disagree": 7
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

## 9. Control vs Analysis Split (STRICT, unchanged)

**CONTROL (retry loop):** consecutive_same_failure, similarity_to_previous, score_improving, failure_type (for adaptive hints), plan_alignment.aligned (for alignment feedback only).

**ANALYSIS (post-hoc only):** llm_eval_blind, llm_eval_conditioned, reasoning_confidence, leg_strong, leg_weak, classifier_alignment, all aggregate metrics, trajectory_dynamics.

Nothing from the ANALYSIS column appears in any `if` statement inside the retry loop.

---

## 10. Implementation Plan

### File-Level Changes

| File | Change | Lines |
|---|---|---|
| `retry_harness.py` | `_detect_failure_type_from_reasoning()`, `_classifier_agrees_with_reasoning()`, `_compute_reasoning_confidence()`, `_evaluate_reasoning_correctness()` (dual mode), `_extract_plan()`, `_validate_plan_coverage()`, `_plan_matches_failure()`, `_ACTION_TOKENS`, `use_alignment` + `use_llm_eval` flags, FIX 7 structured feedback, 7 new per-entry fields, 8 new summary fields, bias metric | ~170 |
| `runner.py` | `retry_alignment` condition dispatch | ~5 |
| `scripts/leg_analysis.py` | **NEW**: post-hoc LEG analysis on existing logs | ~80 |
| `tests/test_retry_harness.py` | Tests for new functions + LEG tiers | ~30 |
| **Total** | | **~285** |

### Phase Order

```
Phase 1: scripts/leg_analysis.py                    [NOW, 0 API calls]
  → H3 test (Level D vs A-C LEG rate, keyword-only)
  → H5 test (file count vs LEG rate)
  → Baseline LEG metrics for all 3 models

Phase 2: Alignment code                             [~80 lines]
  → _extract_plan, _validate_plan_coverage, _plan_matches_failure
  → use_alignment flag, FIX 7 structured feedback
  → retry_alignment in runner.py

Phase 3: Smoke test alignment                       [~20 API calls]
  → 2 cases × retry_alignment × gpt-4o-mini

Phase 4: Hybrid LEG detection + dual evaluator      [~90 lines]
  → _detect_failure_type_from_reasoning, _classifier_agrees_with_reasoning
  → _compute_reasoning_confidence
  → _evaluate_reasoning_correctness (blind + conditioned modes)
  → use_llm_eval flag, bias metric
  → 7 per-entry fields, 8 summary fields

Phase 5: Alignment ablation                         [~350 calls per model]
  → 51 cases × retry_alignment × gpt-4o-mini

Phase 6: LLM eval on existing retry logs            [~600 calls per model]
  → Dual-mode CRIT-lite on V2 ablation trajectories
  → Compute strong/weak LEG rates + bias metric

Phase 7: Full analysis                              [0 API calls]
  → Compare LEG_strong across conditions
  → Test H3 and H5 with hybrid confidence
  → Measure evaluator bias rate
  → Publish-ready figures
```

---

## 11. Risks and Mitigations

### Risk 1: Evaluator Bias (ADDRESSED by FIX 5)

**Problem:** Conditioned evaluator may inflate YES rate by anchoring on classifier_type.
**Mitigation:** Blind mode is primary. Bias rate is explicitly measured. If bias_rate > 30%, report blind results only.

### Risk 2: LEG Definition Too Strict (ADDRESSED by FIX 6)

**Problem:** Strong LEG requires HIGH confidence + blind YES. May undercount.
**Mitigation:** Weak LEG captures borderline cases. Keyword LEG provides upper bound. Three tiers let analysis explore the sensitivity.

### Risk 3: Alignment Feedback Too Specific (ADDRESSED by FIX 7)

**Problem:** Listing missing steps may confuse the model or cause it to focus on form over substance.
**Mitigation:** Cap at 3 missing steps. Compare alignment with and without structured feedback (if needed, add a `retry_alignment_generic` condition that uses the old generic message).

### Risk 4: Dual Evaluator Cost

**Problem:** 2 LLM calls per failed attempt doubles eval cost.
**Mitigation:** `use_llm_eval=False` by default. Only run on targeted subsets. Can run Mode A only if budget is tight (Mode B is supplementary).

### Risks 5-6: Plan extraction, data plumbing (unchanged from v2)

---

## 12. Expected Outcomes

| Hypothesis | If TRUE | If FALSE |
|---|---|---|
| H1: Underspecified | Plan-then-code reduces LEG_strong ~50% | LEG_strong unchanged |
| H2: Loose coupling | Reasoning echo + mapping reduces LEG_strong ~20% | Model ignores echoed reasoning |
| H3: Instruction compliance | LEG_strong(D) >> LEG_strong(A-C) by 2x+ | Uniform |
| H4: Retry anchoring | Fresh retry: similarity < 0.8 | Similar code regardless |
| H5: Multi-file plumbing | LEG_strong(3+ files) >> LEG_strong(1 file) | Uniform |

### Key Prediction

If evaluator bias_rate > 20%: the conditioned evaluator is not trustworthy for LEG claims. All publishable LEG rates should use blind mode only. The conditioned mode becomes a calibration signal, not a primary measurement.
