# Evaluation Module — Final Revised Plan (v5)

**Date:** 2026-03-23
**Status:** Implementation-ready
**Purpose:** Measure the Latent Execution Gap (LEG) — cases where a model semantically identifies the true failure mechanism but code generation still fails.

---

## 1. Overview

This module measures one thing:

> Given a failed code generation attempt, did the model's reasoning correctly identify the specific failure mechanism?

If yes AND code still fails → LEG event.

Components:
1. A **heuristic classifier** that deterministically assigns a failure type from structured error signals
2. A **blind LLM evaluator** that independently returns a verdict + inferred failure type
3. A **conditioned LLM evaluator** (same, but given the classifier type) for bias measurement
4. A **strict parser** that accepts exact format or rejects — no fallback
5. **Alignment metrics** for the plan-then-code intervention
6. **LEG subtype decomposition** into coupling vs execution failures

The module does NOT:
- Use keyword matching, regex fallback, embedding similarity, fuzzy matching, or ontology mapping in any primary metric
- Participate in retry loop control decisions
- Attempt to repair malformed evaluator output

---

## 2. Definitions

### LEG_true (Primary Metric)

```
LEG_true(k) =
    llm_eval_blind_verdict(k) == "YES"
    AND llm_eval_blind_type(k) == classifier_failure_type(k)
    AND llm_eval_blind_type(k) != "UNKNOWN"
    AND pass(k) == False
```

### LEG_strong_primary (Robustness Check)

```
LEG_strong_primary(k) =
    keyword_signal(k) == True
    AND classifier_alignment(k) == True
    AND llm_eval_blind_verdict(k) == "YES"
    AND pass(k) == False
```

Where `keyword_signal` is from the existing `_detect_latent_signal()` heuristic and `classifier_alignment` is from `_classifier_agrees_with_reasoning()`. This metric adds a third heuristic confirmation. It is NOT the primary metric — it is a robustness check to validate that LEG_true is not an artifact of evaluator-classifier collusion.

### LEG_keyword (Diagnostic Only)

```
LEG_keyword(k) = keyword_signal(k) == True AND pass(k) == False
```

Backward compatibility. NOT used for any primary analysis.

### LEG_coupling (Alignment Condition Only)

```
LEG_coupling(k) = LEG_true(k) == True AND alignment_success(k) == False
```

### LEG_execution (Alignment Condition Only)

```
LEG_execution(k) = LEG_true(k) == True AND alignment_success(k) == True
```

---

## 3. Failure Type Ontology

### Closed Enum

```python
FAILURE_TYPES = (
    "TEMPORAL_ORDERING",
    "HIDDEN_DEPENDENCY",
    "INVARIANT_VIOLATION",
    "PARTIAL_STATE_UPDATE",
    "RETRY_LOGIC_BUG",
    "EDGE_CASE_MISSED",
    "LOGGING_INCONSISTENCY",
    "UNKNOWN",
)

FAILURE_TYPE_SET = frozenset(FAILURE_TYPES)
```

8 types. Flat. No hierarchy. No synonyms. No overlap.

| Type | Covers |
|---|---|
| TEMPORAL_ORDERING | Operations in wrong order, stale reads, sequence violations |
| HIDDEN_DEPENDENCY | Missing import, undefined reference, implicit coupling |
| INVARIANT_VIOLATION | Conservation broken, atomicity failure, rollback missing |
| PARTIAL_STATE_UPDATE | Some fields updated but not all, incomplete mutation |
| RETRY_LOGIC_BUG | Duplicate operations on retry, idempotency failure |
| EDGE_CASE_MISSED | Null, empty, zero, boundary, off-by-one |
| LOGGING_INCONSISTENCY | Side effects in wrong order, audit trail broken |
| UNKNOWN | Cannot determine with confidence |

This enum is used identically by the classifier and the evaluator. Both output values from this set. No other values are accepted.

---

## 4. Classifier Contract

The classifier is a deterministic function. Given identical inputs, it produces identical output.

### Signature

```python
def classify_failure(error_obj: dict, critique: dict | None) -> dict
```

### Inputs

- `error_obj`: dict with keys `category` (str), `message` (str), `reasons` (list[str])
- `critique`: dict with keys `failure_type` (str), `root_cause` (str), `invariant_violated` (str), `_valid` (bool) — or None

No case metadata. No case_id. No failure_mode. No ground truth.

### Output

```python
{
    "failure_type_final": str,          # from FAILURE_TYPE_SET, always present
    "critique_failure_type": str|None,  # raw from critique, for logging
    "error_category": str,              # raw from error_obj
    "matched_keywords": list[str],      # which keywords triggered the rule
    "classifier_rule_path": str,        # which rule fired
    "classifier_confidence": float,     # 0.0 - 1.0
}
```

`failure_type_final` is always a member of `FAILURE_TYPE_SET`. Never null. Never free text.

### Priority Rules (Deterministic, Applied in Order)

**Rule 1: Critique keyword match (confidence 0.8)**
- Condition: `critique` is not None, `critique["_valid"]` is not False
- Action: scan `critique["root_cause"]` + `critique["invariant_violated"]` for keywords
- Mapping (exact keyword sets defined in `failure_classifier.py:_CRITIQUE_KEYWORDS`):
  - "order", "before", "after", "timing", "sequence", "stale" → TEMPORAL_ORDERING
  - "depend", "import", "hidden", "missing", "undefined", "not defined" → HIDDEN_DEPENDENCY
  - "invariant", "conserv", "balance", "consistent", "atomic", "rollback" → INVARIANT_VIOLATION
  - "partial", "incomplete", "subset", "some but not all" → PARTIAL_STATE_UPDATE
  - "retry", "duplic", "idempot", "repeat", "twice", "already" → RETRY_LOGIC_BUG
  - "log", "side effect", "record", "audit" → LOGGING_INCONSISTENCY
  - "edge", "boundary", "null", "empty", "zero", "none" → EDGE_CASE_MISSED
- First match wins. No fuzzy matching. Substring containment only.

**Rule 2: Error category (confidence 0.5)**
- `"syntax"` → EDGE_CASE_MISSED
- `"load"` → HIDDEN_DEPENDENCY
- `"runtime"` + "NameError" in message → HIDDEN_DEPENDENCY
- `"runtime"` + "ImportError" in message → HIDDEN_DEPENDENCY
- `"runtime"` + "AttributeError" in message → HIDDEN_DEPENDENCY
- `"runtime"` + "KeyError" in message → PARTIAL_STATE_UPDATE
- `"runtime"` + "IndexError" in message → EDGE_CASE_MISSED
- `"runtime"` + "TypeError" in message → EDGE_CASE_MISSED
- `"runtime"` + other → EDGE_CASE_MISSED

**Rule 3: Keyword scan on error_obj.reasons (confidence 0.3)**
- Concatenate all reasons into one string
- Apply same keyword sets as Rule 1
- First match wins

**Rule 4: Fallback (confidence 0.0)**
- Output: UNKNOWN

No probabilistic scoring. No embedding similarity. No LLM calls. Each input maps to exactly one output deterministically.

### UNKNOWN Handling

If no rule matches before Rule 4: `failure_type_final = "UNKNOWN"`. This is never suppressed. It propagates to LEG_true computation where it blocks the match (`UNKNOWN != any non-UNKNOWN type`).

### Determinism Guarantee

> Given identical `error_obj` and `critique` inputs, `classify_failure` produces identical output. There is no randomness, no sampling, no external state.

### Unit Tests

```python
def test_classifier_temporal_from_critique():
    critique = {"root_cause": "state read before write", "invariant_violated": "ordering", "_valid": True}
    error = {"category": "logic", "message": "", "reasons": []}
    r = classify_failure(error, critique)
    assert r["failure_type_final"] == "TEMPORAL_ORDERING"
    assert r["failure_type_final"] in FAILURE_TYPE_SET

def test_classifier_hidden_dep_from_runtime():
    error = {"category": "runtime", "message": "NameError: 'foo' not defined", "reasons": []}
    r = classify_failure(error, None)
    assert r["failure_type_final"] == "HIDDEN_DEPENDENCY"

def test_classifier_unknown_fallback():
    error = {"category": "logic", "message": "test failed", "reasons": ["test failed"]}
    r = classify_failure(error, None)
    assert r["failure_type_final"] == "UNKNOWN"
    assert r["classifier_confidence"] == 0.0

def test_classifier_conflicting_signals():
    """Critique says ordering, error says NameError. Rule 1 wins (higher priority)."""
    critique = {"root_cause": "operations in wrong order", "invariant_violated": "", "_valid": True}
    error = {"category": "runtime", "message": "NameError: x", "reasons": []}
    r = classify_failure(error, critique)
    assert r["failure_type_final"] == "TEMPORAL_ORDERING"  # Rule 1 fires first

def test_classifier_always_returns_enum():
    for error in [{"category": "", "message": "", "reasons": []},
                  {"category": "logic", "message": "xyz", "reasons": ["abc"]}]:
        for critique in [None, {"_valid": False}]:
            r = classify_failure(error, critique)
            assert r["failure_type_final"] in FAILURE_TYPE_SET

def test_classifier_deterministic():
    error = {"category": "logic", "message": "stale state", "reasons": ["stale"]}
    r1 = classify_failure(error, None)
    r2 = classify_failure(error, None)
    assert r1 == r2
```

---

## 5. Evaluator Contract

### Verdict Space: YES / NO (Binary)

**Decision:** The verdict is binary. PARTIAL is excluded.

**Justification:**
1. **LEG_true requires a clean boolean.** The central claim is "the model identified the true mechanism AND code still failed." There is no "partially identified" version of this claim. Either the reasoning matches the mechanism or it doesn't.
2. **PARTIAL introduces measurement noise.** Reviewers would ask: "When you report 63% LEG rate, how many of those are PARTIAL?" This forces a secondary threshold (does PARTIAL count?) which weakens the metric.
3. **Conservative bias is intentional.** The evaluator prompt says "if uncertain, answer NO." This means LEG_true undercounts rather than overcounts. An undercount is defensible; an overcount is not.
4. **Bias measurement is cleaner.** `bias_rate = (cond_yes - blind_yes) / blind_yes` is well-defined with a binary verdict. With three values, the analysis requires additional decisions about how to count PARTIAL.

**Propagation:** The binary verdict is used consistently in:
- Evaluator prompt (`YES` or `NO` only)
- Parser (`_VALID_VERDICTS = frozenset(["YES", "NO"])`)
- LEG_true formula (`verdict == "YES"`)
- Bias metric (counts YES only)

### Blind Evaluator Prompt

```python
_CRIT_LITE_BLIND_PROMPT = """You are evaluating whether a developer's reasoning correctly identifies the ROOT CAUSE of a code failure.

You are ONLY evaluating whether the reasoning correctly identifies the failure mechanism. You are NOT evaluating code quality, style, or whether the fix works.

# Inputs

## Code (FAILED)
```python
{code}
```

## Test Failure
Category: {error_category}
Message: {error_message}
Failed assertions:
{test_reasons}

## Developer's Reasoning
{reasoning}

# Task

## Phase 1: Evaluate reasoning correctness
1. Does the reasoning identify the type of failure?
2. Does the reasoning explain HOW the failure occurs (the mechanism)?
3. Does the reasoning connect the mechanism to the observed test failure?

## Phase 2: Infer failure type
Based on the code, test failure, and reasoning, classify the failure.

Choose EXACTLY one:
- TEMPORAL_ORDERING
- HIDDEN_DEPENDENCY
- INVARIANT_VIOLATION
- PARTIAL_STATE_UPDATE
- RETRY_LOGIC_BUG
- EDGE_CASE_MISSED
- LOGGING_INCONSISTENCY
- UNKNOWN

## Phase 3: Verdict
- YES: reasoning correctly identifies the failure type AND mechanism AND connects to the error
- NO: reasoning is incorrect, vague, irrelevant, or identifies the wrong mechanism

Rules:
- Be conservative. Only YES if clearly correct.
- Do NOT reward vague reasoning.
- Do NOT infer correctness if the mechanism is missing.
- If uncertain, answer NO.

# Output

Return EXACTLY one line in this format:

VERDICT ; FAILURE_TYPE

Examples:
YES ; TEMPORAL_ORDERING
NO ; HIDDEN_DEPENDENCY
NO ; UNKNOWN"""
```

### Conditioned Evaluator Prompt

Identical to blind, with one section added after `## Developer's Reasoning`:

```
## System-Detected Failure Type
{classifier_type}
```

### Evaluator Function

```python
def _evaluate_reasoning(model, reasoning_text, code_k, error_obj,
                        classifier_type=None, blind=True):
    """CRIT-lite evaluator. ANALYSIS ONLY — never in retry loop.

    Returns: {
        "verdict": str|None,       # "YES" or "NO" or None
        "inferred_type": str|None, # from FAILURE_TYPE_SET or None
        "raw": str|None,           # raw LLM output
        "parse_error": str|None    # reason for parse failure or None
    }
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
        return _parse_evaluator_output(raw)
    except Exception as e:
        return {"verdict": None, "inferred_type": None, "raw": None,
                "parse_error": f"exception:{e}"}
```

### Parser — Strict, No Fallback

```python
_VALID_VERDICTS = frozenset(["YES", "NO"])

def _parse_evaluator_output(raw):
    """Parse 'VERDICT ; FAILURE_TYPE'. Strict: no repair, no fuzzy match.

    On ANY format violation: verdict=None, inferred_type=None, parse_error=<reason>.
    """
    result = {"verdict": None, "inferred_type": None, "raw": raw, "parse_error": None}

    if not raw or not raw.strip():
        result["parse_error"] = "empty_response"
        return result

    first_line = None
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break

    if not first_line:
        result["parse_error"] = "no_content_line"
        return result

    parts = first_line.split(";")
    if len(parts) != 2:
        result["parse_error"] = f"expected_2_semicolon_parts_got_{len(parts)}"
        return result

    verdict_raw = parts[0].strip().upper()
    type_raw = parts[1].strip().upper().replace(" ", "_")

    if verdict_raw not in _VALID_VERDICTS:
        result["parse_error"] = f"invalid_verdict:{verdict_raw}"
        return result

    if type_raw not in FAILURE_TYPE_SET:
        result["parse_error"] = f"invalid_type:{type_raw}"
        return result

    result["verdict"] = verdict_raw
    result["inferred_type"] = type_raw
    return result
```

**Forbidden behaviors (explicit):**
- No keyword matching on raw output
- No regex extraction of partial matches
- No "closest enum value" lookup
- No embedding similarity
- No ontology mapping
- No auto-correction of typos
- No retry on parse failure
- No accepting PARTIAL as a verdict

If output ≠ `VERDICT ; FAILURE_TYPE` with both values in their enums → `verdict=None, inferred_type=None`. The attempt is excluded from LEG metrics and counted in `evaluator_parse_failure_rate`.

---

## 6. Primary Metric Path (LEG_true)

### Inputs

| Field | Source | Type |
|---|---|---|
| `llm_eval_blind_verdict` | Blind evaluator → parser | str: "YES", "NO", or None |
| `llm_eval_blind_type` | Blind evaluator → parser | str: member of FAILURE_TYPE_SET, or None |
| `classifier_failure_type` | `classify_failure()` → `failure_type_final` | str: member of FAILURE_TYPE_SET |
| `pass` | `exec_evaluate()` → `pass` | bool |

### Computation

```python
def _compute_leg_true(entry):
    if entry["pass"]:
        return False
    verdict = entry.get("llm_eval_blind_verdict")
    blind_type = entry.get("llm_eval_blind_type")
    classifier_type = (entry.get("classification") or {}).get("failure_type_final")
    if verdict != "YES":
        return False
    if blind_type is None or classifier_type is None:
        return False
    if blind_type == "UNKNOWN":
        return False
    return blind_type == classifier_type
```

### Exclusion Guarantee

The following are NOT used in `_compute_leg_true`:
- `keyword_signal` or `_detect_latent_signal()`
- `_detect_failure_type_from_reasoning()` (heuristic keyword parser)
- `classifier_alignment` or `_classifier_agrees_with_reasoning()`
- Any regex-based inference
- Any embedding similarity
- Any fuzzy matching
- Any ontology mapping

LEG_true depends on exactly 4 fields: blind verdict, blind type, classifier type, and pass/fail.

### reasoning_matches_truth

```
reasoning_matches_truth(k) =
    llm_eval_blind_type(k) is not None
    AND classifier_failure_type(k) is not None
    AND llm_eval_blind_type(k) == classifier_failure_type(k)
    AND llm_eval_blind_type(k) != "UNKNOWN"
```

This is a derived boolean stored for clarity. It is NOT an independent signal — it is a component of LEG_true.

---

## 7. Alignment Metric

### Step Extraction

A "step" is a numbered line inside a `PLAN:` block:

```
PLAN:
1. In create_config: replace DEFAULTS with DEFAULTS.copy()
2. In get_base_config: return fresh dict instead of reference
INVARIANT: DEFAULTS must not be mutated by callers
```

Extraction rule:
```python
def _extract_plan(raw_output):
    plan_match = re.search(r'PLAN:\s*\n((?:\d+\..*\n?)+)', raw_output)
    invariant_match = re.search(r'INVARIANT:\s*(.*)', raw_output)
    if not plan_match:
        return None
    steps = re.findall(r'\d+\.\s*(.*)', plan_match.group(1))
    if not steps:
        return None
    invariant = invariant_match.group(1).strip() if invariant_match else None
    return {"steps": steps, "invariant": invariant}
```

Each step is a free-text string. Steps are extracted by matching `\d+\.\s*(.*)`. If no `PLAN:` block exists, plan is `None`.

### Step Coverage

```
step_coverage = implemented_steps / total_steps
```

Where `implemented_steps` = number of plan steps for which `_step_implemented(step, code)` returns True.

```python
_ACTION_TOKENS = frozenset([
    '=', 'copy(', 'if ', 'for ', 'append(', 'return ', 'raise ',
    '.pop(', '.get(', '.update(', '.insert(', 'del ', 'import ',
    'try:', 'except', 'with ', '.clear(', '.add(',
])

def _extract_action_keywords(step_text):
    cleaned = re.sub(r'\b(in|the|a|an|to|of|for|and|or|by|with|from)\b', '', step_text.lower())
    words = re.findall(r'[a-zA-Z_]\w{3,}', cleaned)
    generic = {'should', 'must', 'need', 'change', 'update', 'make', 'ensure',
               'function', 'method', 'variable', 'code', 'line', 'file'}
    return [w for w in words if w not in generic]

def _step_implemented(step_text, code):
    keywords = _extract_action_keywords(step_text)
    if not keywords:
        return True  # no keywords extractable → cannot check → assume True
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3
    has_action = any(tok in code for tok in _ACTION_TOKENS)
    return keyword_covered and has_action
```

Example: step "In create_config: add .copy() to prevent aliasing" → keywords `['copy', 'prevent', 'aliasing', 'create_config']` → code must contain ≥30% of these AND at least one action token.

### Threshold

```python
ALIGNMENT_THRESHOLD = 0.5
```

Justification: 0.5 means at least half the plan steps are reflected in the code. This is deliberately permissive — it separates "plan totally ignored" from "plan partially implemented." The raw `step_coverage` float is always logged for post-hoc threshold sensitivity analysis.

### plan_matches_failure

```python
def _plan_matches_failure(plan, error_obj, classification):
    if not plan or not plan.get("invariant"):
        return None  # no invariant to check
    invariant_lower = plan["invariant"].lower()
    error_category = error_obj.get("category", "")
    if error_category in ("syntax", "runtime", "load"):
        if error_category == "syntax" and "syntax" not in invariant_lower:
            return False
        if error_category == "runtime":
            err_type = (error_obj.get("message", "").split(":")[0] or "").lower()
            if err_type and err_type not in invariant_lower:
                return False
    if classification and classification.get("failure_type_final") != "UNKNOWN":
        classifier_words = classification["failure_type_final"].lower().replace("_", " ").split()
        overlap = any(w in invariant_lower for w in classifier_words if len(w) > 3)
        if not overlap:
            steps_text = " ".join(plan.get("steps", [])).lower()
            overlap = any(w in steps_text for w in classifier_words if len(w) > 3)
        if not overlap:
            return False
    return True
```

### alignment_success

```
alignment_success =
    plan_matches_failure == True
    AND step_coverage >= 0.5
```

### Logging

Both continuous and binary are logged:
- `alignment_step_coverage`: float [0, 1] (continuous)
- `alignment_success`: bool (binary, thresholded)
- `alignment_plan_matches`: bool | None
- `alignment_per_step`: list[dict] (per-step detail)
- `alignment_score_values`: list[float] in summary (full distribution for sensitivity analysis)

---

## 8. Metric Hierarchy

### Primary Metric:
```
LEG_true
```
All primary claims rest on this. It uses the blind evaluator's semantic type inference matched against the classifier's structural detection. No heuristic keyword matching.

### Primary Robustness Check:
```
LEG_strong_primary
```
```
LEG_strong_primary(k) =
    keyword_signal(k) == True
    AND classifier_alignment(k) == True
    AND llm_eval_blind_verdict(k) == "YES"
    AND pass(k) == False
```
Adds the keyword heuristic as a third confirmation signal. If LEG_true and LEG_strong_primary diverge significantly, it suggests evaluator-classifier collusion or keyword detector failure.

### Diagnostic Only:
```
LEG_keyword
```
Keyword-based. NOT used for any primary analysis. Retained for backward compatibility with prior ablation logs and as a cheap screening signal.

**Explicit statement:** Keyword-based LEG is NOT used for any primary analysis, any primary claim, or any primary figure. It appears only in diagnostic/robustness sections.

---

## 9. Subtype Decomposition

### LEG_coupling

```
LEG_coupling(k) = LEG_true(k) == True AND alignment_success(k) == False
```

The model's reasoning correctly identifies the failure mechanism (blind evaluator + classifier agree), but the code does not implement the reasoning (low step coverage or wrong-topic plan).

Interpretation: reasoning→code translation failure. The bottleneck is between understanding and implementation.

### LEG_execution

```
LEG_execution(k) = LEG_true(k) == True AND alignment_success(k) == True
```

The model's reasoning is correct AND the code appears to implement the plan, but tests still fail.

Interpretation: execution fidelity failure. The code is wrong at a granularity finer than the plan captures.

### Guarantees

- LEG_true is computed BEFORE alignment.
- Alignment does NOT affect LEG_true.
- `_compute_leg_true()` does not reference alignment fields.
- `_compute_alignment()` does not reference LEG fields.
- LEG_coupling and LEG_execution combine these two independent computations.

### Availability

LEG_coupling and LEG_execution are `None` for non-alignment conditions (no plan data). They are computed only for `retry_alignment`.

---

## 10. Bias Metric

```python
def _compute_evaluator_bias(trajectory):
    blind_yes = sum(1 for e in trajectory
                    if e.get("llm_eval_blind_verdict") == "YES")
    cond_yes = sum(1 for e in trajectory
                   if e.get("llm_eval_cond_verdict") == "YES")
    total = sum(1 for e in trajectory
                if e.get("llm_eval_blind_verdict") is not None
                and e.get("llm_eval_cond_verdict") is not None)

    bias_rate_relative = (
        round((cond_yes - blind_yes) / blind_yes, 3)
        if blind_yes > 0 else None
    )
    bias_rate_absolute = (
        round((cond_yes - blind_yes) / total, 3)
        if total > 0 else None
    )

    return {
        "blind_yes": blind_yes,
        "conditioned_yes": cond_yes,
        "total_evaluated": total,
        "bias_rate_relative": bias_rate_relative,
        "bias_rate_absolute": bias_rate_absolute,
    }
```

`bias_rate_relative`: primary. Measures inflation relative to blind baseline. 0.40 = conditioned says YES 40% more often.

`bias_rate_absolute`: diagnostic. Measures absolute difference as fraction of total.

If `bias_rate_relative > 0.30`: conditioned evaluator is materially biased. All primary analysis uses blind only.

---

## 11. Logging Schema

### Per-iteration fields

| Field | Type | Description |
|---|---|---|
| `llm_eval_blind_verdict` | str \| None | "YES", "NO", or None (parse failure) |
| `llm_eval_blind_type` | str \| None | Member of FAILURE_TYPE_SET, or None |
| `llm_eval_blind_raw` | str \| None | Raw LLM output string |
| `llm_eval_blind_parse_error` | str \| None | Parse error reason or None |
| `llm_eval_cond_verdict` | str \| None | Same for conditioned mode |
| `llm_eval_cond_type` | str \| None | |
| `llm_eval_cond_raw` | str \| None | |
| `llm_eval_cond_parse_error` | str \| None | |
| `classifier_failure_type` | str | From classification dict, always in FAILURE_TYPE_SET |
| `reasoning_matches_truth` | bool \| None | blind_type == classifier_type (neither UNKNOWN/None) |
| `leg_true` | bool | LEG_true formula result |
| `leg_strong_primary` | bool | All 3 signals agree |
| `leg_keyword_only` | bool | Keyword signal only (diagnostic) |
| `leg_coupling` | bool \| None | LEG_true ∧ ¬alignment_success (alignment cond only) |
| `leg_execution` | bool \| None | LEG_true ∧ alignment_success (alignment cond only) |
| `alignment_step_coverage` | float \| None | [0, 1] continuous (alignment cond only) |
| `alignment_success` | bool \| None | Thresholded binary (alignment cond only) |
| `alignment_plan_matches` | bool \| None | Does plan address actual failure? |
| `alignment_per_step` | list \| None | Per-step implementation detail |

### Per-summary fields

| Field | Type | Description |
|---|---|---|
| `leg_rate_true` | float | LEG_true count / failed attempts |
| `leg_rate_strong_primary` | float | LEG_strong_primary / failed attempts |
| `leg_rate_keyword` | float | LEG_keyword / failed attempts (diagnostic) |
| `leg_resolution_rate_true` | float \| None | LEG_true(k) ∧ pass(k+1) / LEG_true(k) |
| `leg_coupling_rate` | float \| None | LEG_coupling / failed attempts (alignment only) |
| `leg_execution_rate` | float \| None | LEG_execution / failed attempts (alignment only) |
| `evaluator_parse_failure_rate` | float | Parse failures / total eval calls |
| `evaluator_unknown_type_rate` | float | UNKNOWN type / successful parses |
| `evaluator_bias` | dict | See §10 |
| `alignment_leg_split` | dict \| None | See §7, includes raw score values + distribution |

### Storage Format

All fields are JSON-serializable. Written to the existing 3-file JSONL system (metadata + prompts + responses). Per-iteration fields are in the trajectory entry dict. Per-summary fields are in the summary record.

### Replay Invariant

Given the same log files, all LEG metrics can be recomputed by reading: `llm_eval_blind_verdict`, `llm_eval_blind_type`, `classifier_failure_type`, `pass`, `alignment_success`. No external state is needed. All inputs are logged. `_compute_leg_true(entry)` applied to logged entries must produce the same `leg_true` value that was originally logged.

---

## 12. Pipeline

```
1. CASE INPUT
   case dict with id, task, code_files, failure_mode

2. MODEL GENERATION (inside retry loop, unchanged)
   for k in range(max_iterations):
       raw = call_model(prompt, model)
       code_k, reasoning_k = parse(raw)

3. EXECUTION (inside loop, unchanged)
       ev = _safe_evaluate(case, raw)

4. CLASSIFICATION (inside loop, deterministic)
       classification = classify_failure(error_obj, critique)
       entry["classifier_failure_type"] = classification["failure_type_final"]

5. ALIGNMENT (inside loop, alignment condition only)
       plan = _extract_plan(raw)
       alignment = _compute_alignment(plan, code_k, error_obj, classification)
       entry["alignment_step_coverage"] = alignment["step_coverage"]
       entry["alignment_success"] = alignment["alignment_success"]

6. KEYWORD SIGNAL (inside loop, for diagnostic LEG_keyword)
       latent = _detect_latent_signal(reasoning_k, ev["pass"])
       entry["leg_keyword_only"] = latent["correct_pattern_in_reasoning"] and not ev["pass"]

7. STOP CONDITIONS (unchanged, control signals only)

--- LOOP ENDS ---

8. LLM EVALUATION (post-hoc, gated by use_llm_eval flag)
   for entry in trajectory:
       if not entry["pass"] and entry["reasoning"]:
           blind = _evaluate_reasoning(model, ..., blind=True)
           cond = _evaluate_reasoning(model, ..., classifier_type=..., blind=False)
           entry["llm_eval_blind_verdict"] = blind["verdict"]
           entry["llm_eval_blind_type"] = blind["inferred_type"]
           entry["llm_eval_blind_raw"] = blind["raw"]
           entry["llm_eval_blind_parse_error"] = blind["parse_error"]
           entry["llm_eval_cond_verdict"] = cond["verdict"]
           entry["llm_eval_cond_type"] = cond["inferred_type"]
           entry["llm_eval_cond_raw"] = cond["raw"]
           entry["llm_eval_cond_parse_error"] = cond["parse_error"]

9. LEG COMPUTATION (post-hoc, after evaluator)
   for entry in trajectory:
       entry["reasoning_matches_truth"] = (
           entry.get("llm_eval_blind_type") is not None
           and entry.get("classifier_failure_type") is not None
           and entry["llm_eval_blind_type"] == entry["classifier_failure_type"]
           and entry["llm_eval_blind_type"] != "UNKNOWN"
       )
       entry["leg_true"] = (
           entry.get("llm_eval_blind_verdict") == "YES"
           and entry["reasoning_matches_truth"]
           and not entry["pass"]
       )
       entry["leg_strong_primary"] = (
           entry.get("leg_keyword_only", False)
           and entry.get("classifier_alignment", False)
           and entry.get("llm_eval_blind_verdict") == "YES"
           and not entry["pass"]
       )
       if entry.get("alignment_success") is not None:
           entry["leg_coupling"] = entry["leg_true"] and not entry["alignment_success"]
           entry["leg_execution"] = entry["leg_true"] and entry["alignment_success"]
       else:
           entry["leg_coupling"] = None
           entry["leg_execution"] = None

10. SUMMARY CONSTRUCTION
    Aggregate metrics from trajectory. Write to log.

11. LOGGING
    All fields written to JSONL.
```

---

## 13. Failure Modes

### Malformed evaluator output

**Trigger:** Output does not match `VERDICT ; FAILURE_TYPE` with both in their enums.
**Behavior:** `verdict=None, inferred_type=None, parse_error=<reason>`.
**Effect:** Attempt excluded from all LEG metrics. Counted in `evaluator_parse_failure_rate`.
**No retry. No repair. No fallback.**

### UNKNOWN inferred type (evaluator)

**Trigger:** Evaluator returns `"YES ; UNKNOWN"`.
**Behavior:** `reasoning_matches_truth = False` (UNKNOWN ≠ any classifier type).
**Effect:** `leg_true = False`. Counted in `evaluator_unknown_type_rate`.

### UNKNOWN classifier type

**Trigger:** Classifier returns `failure_type_final = "UNKNOWN"`.
**Behavior:** `reasoning_matches_truth = False`.
**Effect:** `leg_true = False`.

### Multiple types in evaluator output

**Trigger:** Evaluator outputs multiple lines or multiple semicolons.
**Behavior:** Parser takes first non-empty line. If that line has ≠ 2 semicolon parts → parse failure.

### Invalid enum value

**Trigger:** Type string not in `FAILURE_TYPE_SET`.
**Behavior:** Parse failure. `verdict=None, inferred_type=None`.
**No closest match. No synonym lookup. Exact string match only.**

### Missing fields in trajectory entry

**Behavior:** All new fields default to `None` at entry creation. `_compute_leg_true` checks for `None` before comparison. `None` anywhere → `leg_true = False`.

### Both evaluator and classifier wrong but agreeing

**Risk:** False positive LEG_true.
**Mitigation:** `LEG_strong_primary` adds keyword signal as third check. Residual false positive rate is inherent without human annotation. The conservative evaluator prompt reduces it.

---

## 14. Testing Plan

### Parser Tests

```python
def test_parse_yes_temporal():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "TEMPORAL_ORDERING"
    assert r["parse_error"] is None

def test_parse_no_unknown():
    r = _parse_evaluator_output("NO ; UNKNOWN")
    assert r["verdict"] == "NO"
    assert r["inferred_type"] == "UNKNOWN"

def test_parse_rejects_partial():
    r = _parse_evaluator_output("PARTIAL ; HIDDEN_DEPENDENCY")
    assert r["verdict"] is None

def test_parse_rejects_bad_type():
    r = _parse_evaluator_output("YES ; WRONG")
    assert r["verdict"] is None

def test_parse_rejects_no_semicolon():
    r = _parse_evaluator_output("YES TEMPORAL_ORDERING")
    assert r["verdict"] is None

def test_parse_rejects_empty():
    r = _parse_evaluator_output("")
    assert r["verdict"] is None

def test_parse_rejects_prose():
    r = _parse_evaluator_output("The reasoning is correct because...")
    assert r["verdict"] is None

def test_parse_strips_whitespace():
    r = _parse_evaluator_output("  YES  ;  HIDDEN_DEPENDENCY  ")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "HIDDEN_DEPENDENCY"

def test_parse_first_line_only():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING\nextra text")
    assert r["verdict"] == "YES"
```

### LEG_true Tests

```python
def test_leg_true_match():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(e) is True

def test_leg_true_type_mismatch():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classification": {"failure_type_final": "HIDDEN_DEPENDENCY"}}
    assert _compute_leg_true(e) is False

def test_leg_true_unknown_blocks():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "UNKNOWN",
         "classification": {"failure_type_final": "UNKNOWN"}}
    assert _compute_leg_true(e) is False

def test_leg_true_no_blocks():
    e = {"pass": False, "llm_eval_blind_verdict": "NO",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(e) is False

def test_leg_true_pass_blocks():
    e = {"pass": True, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(e) is False

def test_leg_true_none_blocks():
    e = {"pass": False, "llm_eval_blind_verdict": None,
         "llm_eval_blind_type": None,
         "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(e) is False
```

### Invariant Tests

```python
def test_no_heuristic_in_leg_true():
    import inspect
    source = inspect.getsource(_compute_leg_true)
    forbidden = ["keyword", "latent_signal", "detect_failure_type_from_reasoning",
                 "regex", "fuzzy", "embedding", "similarity", "ontology"]
    for word in forbidden:
        assert word not in source.lower(), f"forbidden: {word} found in _compute_leg_true"

def test_leg_true_exact_match_only():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL",  # not in enum, should have been rejected by parser
         "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(e) is False

def test_no_circularity():
    import inspect
    leg_src = inspect.getsource(_compute_leg_true)
    assert "alignment" not in leg_src
    align_src = inspect.getsource(_compute_alignment)
    assert "leg_true" not in align_src

def test_enum_completeness():
    assert len(FAILURE_TYPES) == 8
    assert "UNKNOWN" in FAILURE_TYPE_SET
    for ft in FAILURE_TYPES:
        assert ft == ft.upper()
        assert " " not in ft
```

### Integration Tests

```python
def test_full_pipeline_fields(monkeypatch):
    """All LEG fields present after full pipeline run."""
    # mock evaluator to return valid structured output
    ...
    for entry in summary["trajectory"]:
        assert "llm_eval_blind_verdict" in entry
        assert "llm_eval_blind_type" in entry
        assert "llm_eval_blind_raw" in entry
        assert "leg_true" in entry
        assert isinstance(entry["leg_true"], bool)

def test_replay_determinism():
    """Recomputing LEG from logged fields matches original."""
    for entry in trajectory:
        assert _compute_leg_true(entry) == entry["leg_true"]

def test_classifier_determinism():
    """Same inputs → same classifier output."""
    e = {"category": "logic", "message": "stale", "reasons": ["stale state"]}
    r1 = classify_failure(e, None)
    r2 = classify_failure(e, None)
    assert r1 == r2
```

---

## 15. Signal Relationship

### Signals Are Complementary, Not Independent

The three LEG detection signals — keyword matching, classifier-reasoning alignment, and blind LLM evaluation — are **complementary but partially correlated**.

Specifically:
- **Keyword signal and classifier-alignment** share the same failure-type ontology. Both detect failure categories from text. The keyword signal scans the model's reasoning; the classifier-alignment signal checks whether the model's reasoning mentions the same type the classifier detected from error structure. These signals may fire on overlapping lexical features. They are correlated.
- **The LLM evaluator** provides semantic grounding. It reads the full reasoning, code, and test failure, and makes a judgment that goes beyond keyword presence. It is the most expensive and the least correlated with the fast signals.

### Agreement Is Corroboration, Not Independence Proof

When two signals agree, this is evidence of corroboration — not proof of statistical independence. The distinction matters for interpreting consensus confidence levels:

- `VERY_HIGH` (all 3 agree): strong corroboration across complementary methods
- `HIGH` (2+ agree + evaluator YES): moderate corroboration with semantic backing
- `MEDIUM` (2+ agree): fast-signal agreement only

### signal_overlap_rate

```
signal_overlap_rate = |{k : keyword(k) ∧ classifier_alignment(k)}| / |{k : keyword(k) ∨ classifier_alignment(k)}|
```

This quantifies redundancy between the two fast signals:
- If > 0.9: the fast signals measure essentially the same thing. Consensus adds little beyond the LLM evaluator.
- If 0.4-0.7: the fast signals capture different aspects. Consensus is informative.
- If < 0.3: the signals are largely complementary.

Regardless of overlap, LEG_true depends on the LLM evaluator's semantic type inference matching the classifier's structural detection. This cross-method agreement is the strongest evidence available without human annotation.
