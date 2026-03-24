# Evaluation Module — Final Plan (v7)

**Date:** 2026-03-24
**Status:** Implementation-ready

---

## 1. Overview

This module measures:

> Given a failed code generation attempt, did the model's reasoning correctly identify the specific failure mechanism?

If yes AND code still fails → LEG event.

Components:
1. A heuristic classifier that deterministically assigns a failure type from structured error signals
2. A blind LLM evaluator that returns a structured verdict + inferred failure type
3. A conditioned LLM evaluator (same, but given the classifier type) for bias measurement
4. A strict parser that accepts exact format or rejects
5. Alignment metrics for the plan-then-code intervention
6. LEG subtype decomposition into coupling vs execution failures

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

### LEG_keyword (Diagnostic Only)

```
LEG_keyword(k) = keyword_signal(k) == True AND pass(k) == False
```

Keyword-based LEG is NOT used for any primary analysis, any primary claim, or any primary figure.

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

This enum is used identically by the classifier and the evaluator. Both output values from this set. No other values are accepted anywhere.

---

## 4. Classifier Contract

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
    "failure_type_final": str,          # always a member of FAILURE_TYPE_SET
    "critique_failure_type": str|None,
    "error_category": str,
    "matched_keywords": list[str],
    "classifier_rule_path": str,
    "classifier_confidence": float,
}
```

### Priority Rules

Applied in order. First match wins. No fuzzy matching.

**Rule 1 (confidence 0.8):** Critique keyword match.
- Requires: `critique` is not None, `critique["_valid"]` is not False
- Scans: `critique["root_cause"]` + `critique["invariant_violated"]` (lowercased, substring containment)
- Keywords per type:
  - TEMPORAL_ORDERING: "order", "before", "after", "timing", "sequence", "stale"
  - HIDDEN_DEPENDENCY: "depend", "import", "hidden", "missing", "undefined", "not defined"
  - INVARIANT_VIOLATION: "invariant", "conserv", "balance", "consistent", "atomic", "rollback"
  - PARTIAL_STATE_UPDATE: "partial", "incomplete", "subset", "some but not all"
  - RETRY_LOGIC_BUG: "retry", "duplic", "idempot", "repeat", "twice", "already"
  - LOGGING_INCONSISTENCY: "log", "side effect", "record", "audit"
  - EDGE_CASE_MISSED: "edge", "boundary", "null", "empty", "zero", "none"

**Rule 2 (confidence 0.5):** Error category mapping.
- "syntax" → EDGE_CASE_MISSED
- "load" → HIDDEN_DEPENDENCY
- "runtime" + "NameError" in message → HIDDEN_DEPENDENCY
- "runtime" + "ImportError" in message → HIDDEN_DEPENDENCY
- "runtime" + "AttributeError" in message → HIDDEN_DEPENDENCY
- "runtime" + "KeyError" in message → PARTIAL_STATE_UPDATE
- "runtime" + "IndexError" in message → EDGE_CASE_MISSED
- "runtime" + "TypeError" in message → EDGE_CASE_MISSED
- "runtime" + other → EDGE_CASE_MISSED

**Rule 3 (confidence 0.3):** Keyword scan on `error_obj.reasons` (concatenated, lowercased). Same keyword sets as Rule 1.

**Rule 4 (confidence 0.0):** `failure_type_final = "UNKNOWN"`.

### UNKNOWN Handling

If no rule matches: output UNKNOWN. Never suppressed.

### Determinism Guarantee

Given identical inputs, output is identical. No randomness, no sampling, no external state.

### Classifier Tests

```python
def test_classifier_temporal():
    c = {"root_cause": "state read before write", "invariant_violated": "ordering", "_valid": True}
    e = {"category": "logic", "message": "", "reasons": []}
    assert classify_failure(e, c)["failure_type_final"] == "TEMPORAL_ORDERING"

def test_classifier_hidden_dep_runtime():
    e = {"category": "runtime", "message": "NameError: 'foo' not defined", "reasons": []}
    assert classify_failure(e, None)["failure_type_final"] == "HIDDEN_DEPENDENCY"

def test_classifier_unknown():
    e = {"category": "logic", "message": "test failed", "reasons": ["test failed"]}
    assert classify_failure(e, None)["failure_type_final"] == "UNKNOWN"

def test_classifier_conflicting():
    c = {"root_cause": "operations in wrong order", "invariant_violated": "", "_valid": True}
    e = {"category": "runtime", "message": "NameError: x", "reasons": []}
    assert classify_failure(e, c)["failure_type_final"] == "TEMPORAL_ORDERING"

def test_classifier_enum():
    for e in [{"category": "", "message": "", "reasons": []},
              {"category": "logic", "message": "xyz", "reasons": ["abc"]}]:
        assert classify_failure(e, None)["failure_type_final"] in FAILURE_TYPE_SET

def test_classifier_deterministic():
    e = {"category": "logic", "message": "stale state", "reasons": ["stale"]}
    assert classify_failure(e, None) == classify_failure(e, None)
```

---

## 5. Evaluator Contract

### Verdict Space

Binary: YES or NO. No PARTIAL.

**Justification:** LEG_true requires a clean boolean. "The model identified the true mechanism" is either true or false. PARTIAL introduces thresholding ambiguity. Conservative undercounting (uncertain → NO) is preferable.

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
NO ; UNKNOWN

Return ONLY this one line. No explanation. No commentary."""
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
    """CRIT-lite evaluator. ANALYSIS ONLY.

    Returns: {
        "verdict": str|None,
        "inferred_type": str|None,
        "raw": str|None,
        "parse_error": str|None
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

### Parser

```python
_VALID_VERDICTS = frozenset(["YES", "NO"])

def _parse_evaluator_output(raw):
    """Parse evaluator output. Strict contract:
    - Exactly one non-empty line
    - That line contains exactly one semicolon
    - Left of semicolon is a valid verdict
    - Right of semicolon is a valid failure type
    - Any deviation → parse failure

    Blank lines (whitespace-only) are stripped before counting.
    """
    result = {"verdict": None, "inferred_type": None, "raw": raw, "parse_error": None}

    if not raw or not raw.strip():
        result["parse_error"] = "empty_response"
        return result

    nonempty_lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]

    if len(nonempty_lines) == 0:
        result["parse_error"] = "no_nonempty_lines"
        return result

    if len(nonempty_lines) > 1:
        result["parse_error"] = f"extra_nonempty_lines:got_{len(nonempty_lines)}"
        return result

    line = nonempty_lines[0]

    parts = line.split(";")
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

**Forbidden:** keyword matching, regex extraction, closest-match lookup, embedding similarity, ontology mapping, auto-correction, retry, partial parsing, recovery.

---

## 6. Primary Metric Path (LEG_true)

### Inputs

| Field | Source | Type |
|---|---|---|
| `llm_eval_blind_verdict` | Blind evaluator → parser | "YES", "NO", or None |
| `llm_eval_blind_type` | Blind evaluator → parser | member of FAILURE_TYPE_SET, or None |
| `classifier_failure_type` | `classify_failure()["failure_type_final"]` | member of FAILURE_TYPE_SET |
| `pass` | `exec_evaluate()` | bool |

### Computation

```python
def _compute_leg_true(entry):
    if entry["pass"]:
        return False
    verdict = entry.get("llm_eval_blind_verdict")
    blind_type = entry.get("llm_eval_blind_type")
    classifier_type = entry.get("classifier_failure_type")
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
- `_detect_failure_type_from_reasoning()`
- `classifier_alignment` or `_classifier_agrees_with_reasoning()`
- Any regex-based inference
- Any embedding similarity
- Any fuzzy matching
- Any ontology mapping
- Any alignment fields
- Any conditioned evaluator fields (`llm_eval_conditioned_verdict`, `llm_eval_conditioned_type`)

### reasoning_matches_truth

```python
def _compute_reasoning_matches_truth(entry):
    blind_type = entry.get("llm_eval_blind_type")
    classifier_type = entry.get("classifier_failure_type")
    if blind_type is None or classifier_type is None:
        return False
    if blind_type == "UNKNOWN":
        return False
    return blind_type == classifier_type
```

---

## 7. Alignment Metric

### _compute_alignment

```python
ALIGNMENT_THRESHOLD = 0.5

def _compute_alignment(plan, code, error_obj, classification):
    """Compute all alignment fields.

    Args:
        plan: dict with "steps" and "invariant", or None
        code: str, the generated code
        error_obj: dict with "category", "message", "reasons"
        classification: dict with "failure_type_final"

    Returns:
        dict with step_coverage, per_step, plan_matches_failure, alignment_success
        OR None if plan is None
    """
    if plan is None:
        return None

    step_coverage, per_step = _compute_step_coverage(plan, code)
    plan_matches = _plan_matches_failure(plan, error_obj, classification)
    alignment_success = (plan_matches is True) and (step_coverage >= ALIGNMENT_THRESHOLD)

    return {
        "step_coverage": step_coverage,
        "per_step": per_step,
        "plan_matches_failure": plan_matches,
        "alignment_success": alignment_success,
    }
```

### Plan Extraction

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

### Step Coverage

```python
def _compute_step_coverage(plan, code):
    if not plan or not plan.get("steps"):
        return 0.0, []
    per_step = []
    for step in plan["steps"]:
        impl = _step_implemented(step, code)
        per_step.append({"step": step[:80], "implemented": impl})
    implemented = sum(1 for s in per_step if s["implemented"])
    coverage = implemented / len(plan["steps"])
    return round(coverage, 3), per_step

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
        return True
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3
    has_action = any(tok in code for tok in _ACTION_TOKENS)
    return keyword_covered and has_action
```

### plan_matches_failure

```python
def _plan_matches_failure(plan, error_obj, classification):
    if not plan or not plan.get("invariant"):
        return None
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

### Threshold Justification

`ALIGNMENT_THRESHOLD = 0.5`. At least half the plan steps must be reflected in the code. Raw `step_coverage` is always logged for post-hoc threshold sensitivity.

---

## 8. Metric Hierarchy

**Primary metric:** `LEG_true`. All primary claims rest on this.

**Primary robustness check:** `LEG_strong_primary`. Adds keyword heuristic as third confirmation.

**Diagnostic only:** `LEG_keyword`. NOT used for any primary analysis.

**Subtype decomposition (alignment condition only):** `LEG_coupling`, `LEG_execution`.

---

## 9. Subtype Decomposition

### LEG_coupling

```
LEG_coupling(k) = LEG_true(k) == True AND alignment_success(k) == False
```

Reasoning→code translation failure.

### LEG_execution

```
LEG_execution(k) = LEG_true(k) == True AND alignment_success(k) == True
```

Execution fidelity failure.

### Guarantees

- LEG_true is computed BEFORE subtypes.
- `_compute_leg_true` does NOT reference alignment fields.
- `_compute_alignment` does NOT reference LEG fields.
- Subtypes are `None` for non-alignment conditions.

---

## 10. Bias Metric

```python
def _compute_evaluator_bias(trajectory):
    blind_yes = sum(1 for e in trajectory
                    if e.get("llm_eval_blind_verdict") == "YES")
    conditioned_yes = sum(1 for e in trajectory
                          if e.get("llm_eval_conditioned_verdict") == "YES")
    total = sum(1 for e in trajectory
                if e.get("llm_eval_blind_verdict") is not None
                and e.get("llm_eval_conditioned_verdict") is not None)

    bias_rate_relative = (
        round((conditioned_yes - blind_yes) / blind_yes, 3)
        if blind_yes > 0 else None
    )
    bias_rate_absolute = (
        round((conditioned_yes - blind_yes) / total, 3)
        if total > 0 else None
    )

    return {
        "blind_yes": blind_yes,
        "conditioned_yes": conditioned_yes,
        "total_evaluated": total,
        "bias_rate_relative": bias_rate_relative,
        "bias_rate_absolute": bias_rate_absolute,
    }
```

---

## 11. Invalid Evaluator Output Policy

When the evaluator produces invalid output for a specific attempt:

1. That attempt's `llm_eval_blind_verdict` and `llm_eval_blind_type` are `None`.
2. That attempt's `leg_true` is `False`.
3. The attempt remains in the trajectory. The run is NOT invalidated.
4. The parse error is logged in `llm_eval_blind_parse_error`.
5. The attempt is excluded from LEG metrics (not counted in numerator or denominator of LEG rates that require a valid evaluator result).
6. The attempt IS counted in `evaluator_parse_failure_rate_blind`.
7. No retry of the evaluator call.
8. No repair of the output.
9. No auto-correction.

The same policy applies independently to the conditioned evaluator and its fields.

---

## 12. Parse Failure Rate

```
evaluator_parse_failure_rate_blind =
    (# blind evaluator calls where llm_eval_blind_parse_error is not None)
    /
    (# blind evaluator calls attempted)

evaluator_parse_failure_rate_conditioned =
    (# conditioned evaluator calls where llm_eval_conditioned_parse_error is not None)
    /
    (# conditioned evaluator calls attempted)
```

"Calls attempted" = all failed attempts where reasoning was non-empty and the evaluator function was invoked. This includes successful parses, format failures, and exceptions.

Exceptions produce `parse_error="exception:..."` and count as parse failures.

Skipped calls (passing attempts, empty reasoning, `use_llm_eval=False`) are NOT in the denominator.

Blind and conditioned rates are reported separately.

---

## 13. Central Schema Table

### Per-Attempt Fields

| Field | Type | Allowed Values | Nullable | Scope |
|---|---|---|---|---|
| `llm_eval_blind_verdict` | str | "YES", "NO" | Yes (parse failure) | per-attempt |
| `llm_eval_blind_type` | str | members of FAILURE_TYPE_SET | Yes (parse failure) | per-attempt |
| `llm_eval_blind_raw` | str | any | Yes (exception) | per-attempt |
| `llm_eval_blind_parse_error` | str | any | Yes (no error) | per-attempt |
| `llm_eval_conditioned_verdict` | str | "YES", "NO" | Yes (parse failure) | per-attempt |
| `llm_eval_conditioned_type` | str | members of FAILURE_TYPE_SET | Yes (parse failure) | per-attempt |
| `llm_eval_conditioned_raw` | str | any | Yes (exception) | per-attempt |
| `llm_eval_conditioned_parse_error` | str | any | Yes (no error) | per-attempt |
| `classifier_failure_type` | str | members of FAILURE_TYPE_SET | No | per-attempt |
| `reasoning_matches_truth` | bool | True, False | No | per-attempt |
| `leg_true` | bool | True, False | No | per-attempt |
| `leg_strong_primary` | bool | True, False | No | per-attempt |
| `leg_keyword_only` | bool | True, False | No | per-attempt |
| `leg_coupling` | bool | True, False | Yes (non-alignment) | per-attempt |
| `leg_execution` | bool | True, False | Yes (non-alignment) | per-attempt |
| `alignment_step_coverage` | float | [0.0, 1.0] | Yes (non-alignment) | per-attempt |
| `alignment_success` | bool | True, False | Yes (non-alignment) | per-attempt |
| `alignment_plan_matches` | bool | True, False | Yes (non-alignment / no invariant) | per-attempt |
| `alignment_per_step` | list[dict] | [{"step": str, "implemented": bool}] | Yes (non-alignment) | per-attempt |

### Per-Summary Fields

| Field | Type | Nullable | Scope |
|---|---|---|---|
| `leg_rate_true` | float | No | per-summary |
| `leg_rate_strong_primary` | float | No | per-summary |
| `leg_rate_keyword` | float | No | per-summary |
| `leg_resolution_rate_true` | float | Yes (no LEG events) | per-summary |
| `leg_coupling_rate` | float | Yes (non-alignment) | per-summary |
| `leg_execution_rate` | float | Yes (non-alignment) | per-summary |
| `evaluator_parse_failure_rate_blind` | float | No | per-summary |
| `evaluator_parse_failure_rate_conditioned` | float | No | per-summary |
| `evaluator_unknown_type_rate` | float | No | per-summary |
| `evaluator_bias` | dict | No | per-summary |
| `evaluator_bias.blind_yes` | int | No | nested |
| `evaluator_bias.conditioned_yes` | int | No | nested |
| `evaluator_bias.total_evaluated` | int | No | nested |
| `evaluator_bias.bias_rate_relative` | float | Yes (blind_yes=0) | nested |
| `evaluator_bias.bias_rate_absolute` | float | Yes (total=0) | nested |
| `alignment_leg_split` | dict | Yes (non-alignment) | per-summary |

### Storage Format

All fields are JSON-serializable. Written to existing 3-file JSONL system. Per-attempt fields in trajectory entry dict. Per-summary fields in summary record.

---

## 14. Pipeline

```
1. CASE INPUT
   case dict

2. MODEL GENERATION (inside retry loop)
   for k in range(max_iterations):
       raw = call_model(prompt, model)
       code_k, reasoning_k = parse(raw)

3. EXECUTION (inside loop)
       ev = _safe_evaluate(case, raw)

4. CLASSIFICATION (inside loop)
       classification = classify_failure(error_obj, critique)
       entry["classifier_failure_type"] = classification["failure_type_final"]

5. ALIGNMENT (inside loop, alignment condition only)
       plan = _extract_plan(raw)
       alignment = _compute_alignment(plan, code_k, error_obj, classification)
       if alignment is not None:
           entry["alignment_step_coverage"] = alignment["step_coverage"]
           entry["alignment_success"] = alignment["alignment_success"]
           entry["alignment_plan_matches"] = alignment["plan_matches_failure"]
           entry["alignment_per_step"] = alignment["per_step"]

6. KEYWORD SIGNAL (inside loop, diagnostic)
       latent = _detect_latent_signal(reasoning_k, ev["pass"])
       entry["leg_keyword_only"] = latent["correct_pattern_in_reasoning"] and not ev["pass"]

7. STOP CONDITIONS (unchanged)

--- LOOP ENDS ---

8. LLM EVALUATION (post-hoc, gated by use_llm_eval)
   for entry in trajectory:
       if not entry["pass"] and entry.get("reasoning"):
           ft = entry.get("classifier_failure_type")

           blind = _evaluate_reasoning(model, entry["reasoning"], entry["code"],
                                        entry["error"], blind=True)
           entry["llm_eval_blind_verdict"] = blind["verdict"]
           entry["llm_eval_blind_type"] = blind["inferred_type"]
           entry["llm_eval_blind_raw"] = blind["raw"]
           entry["llm_eval_blind_parse_error"] = blind["parse_error"]

           conditioned = _evaluate_reasoning(model, entry["reasoning"], entry["code"],
                                              entry["error"], classifier_type=ft, blind=False)
           entry["llm_eval_conditioned_verdict"] = conditioned["verdict"]
           entry["llm_eval_conditioned_type"] = conditioned["inferred_type"]
           entry["llm_eval_conditioned_raw"] = conditioned["raw"]
           entry["llm_eval_conditioned_parse_error"] = conditioned["parse_error"]

           model_call_count += 2

9. LEG COMPUTATION (post-hoc)
   for entry in trajectory:
       entry["reasoning_matches_truth"] = _compute_reasoning_matches_truth(entry)
       entry["leg_true"] = _compute_leg_true(entry)
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

10. SUMMARY + LOGGING
```

---

## 15. Failure Modes

### Malformed evaluator output

Parse failure. `verdict=None, inferred_type=None`. Attempt excluded from LEG metrics. Counted in parse failure rate. Run continues.

### UNKNOWN inferred type

`reasoning_matches_truth = False`. `leg_true = False`. Counted in `evaluator_unknown_type_rate`.

### UNKNOWN classifier type

`reasoning_matches_truth = False`. `leg_true = False`.

### Extra non-empty lines

Parse failure: `"extra_nonempty_lines:got_N"`.

### Multiple semicolons

`len(parts) != 2`. Parse failure.

### Invalid enum value

Parse failure.

### Missing fields

All default to `None`. `_compute_leg_true` returns `False` on any `None`.

### Both wrong but agreeing

Residual false positive. Mitigated by conservative prompt and `LEG_strong_primary`.

---

## 16. Signal Relationship

The three LEG signals — keyword, classifier-alignment, blind LLM evaluator — are **complementary but partially correlated**.

- Keyword and classifier-alignment share the same ontology. They are correlated.
- The LLM evaluator provides semantic grounding. It is the least correlated with fast signals.

Agreement is corroboration, not independence proof.

`signal_overlap_rate = |{k : keyword ∧ classifier_alignment}| / |{k : keyword ∨ classifier_alignment}|` measures redundancy.

---

## 17. Implementation Invariants

1. LEG_true uses ONLY: `llm_eval_blind_verdict`, `llm_eval_blind_type`, `classifier_failure_type`, `pass`.
2. LEG_true uses NONE of: keyword heuristics, regex, embedding similarity, fuzzy matching, ontology mapping, alignment fields, conditioned evaluator fields.
3. Alignment is computed independently of LEG_true.
4. The conditioned evaluator is NEVER used in primary LEG metrics.
5. The parser NEVER auto-corrects malformed output.
6. The classifier is deterministic.
7. All inputs to `_compute_leg_true` are logged. LEG metrics are replayable from logs alone.

---

## 18. Testing Plan

### Parser Tests

```python
def test_parse_valid_yes():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "TEMPORAL_ORDERING"
    assert r["parse_error"] is None

def test_parse_valid_no():
    r = _parse_evaluator_output("NO ; UNKNOWN")
    assert r["verdict"] == "NO"
    assert r["inferred_type"] == "UNKNOWN"

def test_parse_rejects_partial():
    assert _parse_evaluator_output("PARTIAL ; HIDDEN_DEPENDENCY")["verdict"] is None

def test_parse_rejects_bad_type():
    assert _parse_evaluator_output("YES ; WRONG")["verdict"] is None

def test_parse_rejects_no_semicolon():
    assert _parse_evaluator_output("YES TEMPORAL_ORDERING")["verdict"] is None

def test_parse_rejects_empty():
    assert _parse_evaluator_output("")["verdict"] is None

def test_parse_rejects_prose():
    assert _parse_evaluator_output("The reasoning is correct")["verdict"] is None

def test_parse_strips_whitespace():
    r = _parse_evaluator_output("  YES  ;  HIDDEN_DEPENDENCY  ")
    assert r["verdict"] == "YES"

def test_parse_rejects_trailing_prose():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING\nThis is because...")
    assert r["verdict"] is None
    assert "extra_nonempty_lines" in r["parse_error"]

def test_parse_rejects_two_valid_lines():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING\nNO ; HIDDEN_DEPENDENCY")
    assert r["verdict"] is None

def test_parse_allows_surrounding_blank_lines():
    r = _parse_evaluator_output("\n  YES ; TEMPORAL_ORDERING  \n\n")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "TEMPORAL_ORDERING"
```

### LEG_true Tests

```python
def test_leg_true_match():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classifier_failure_type": "TEMPORAL_ORDERING"}
    assert _compute_leg_true(e) is True

def test_leg_true_type_mismatch():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classifier_failure_type": "HIDDEN_DEPENDENCY"}
    assert _compute_leg_true(e) is False

def test_leg_true_unknown():
    e = {"pass": False, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "UNKNOWN",
         "classifier_failure_type": "UNKNOWN"}
    assert _compute_leg_true(e) is False

def test_leg_true_verdict_no():
    e = {"pass": False, "llm_eval_blind_verdict": "NO",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classifier_failure_type": "TEMPORAL_ORDERING"}
    assert _compute_leg_true(e) is False

def test_leg_true_pass():
    e = {"pass": True, "llm_eval_blind_verdict": "YES",
         "llm_eval_blind_type": "TEMPORAL_ORDERING",
         "classifier_failure_type": "TEMPORAL_ORDERING"}
    assert _compute_leg_true(e) is False

def test_leg_true_none():
    e = {"pass": False, "llm_eval_blind_verdict": None,
         "llm_eval_blind_type": None,
         "classifier_failure_type": "TEMPORAL_ORDERING"}
    assert _compute_leg_true(e) is False
```

### Invariant Tests

```python
def test_no_heuristic_in_leg_true():
    import inspect
    source = inspect.getsource(_compute_leg_true)
    for word in ["keyword", "latent_signal", "detect_failure_type_from_reasoning",
                 "regex", "fuzzy", "embedding", "similarity", "ontology", "alignment",
                 "conditioned"]:
        assert word not in source.lower()

def test_no_circularity():
    import inspect
    assert "alignment" not in inspect.getsource(_compute_leg_true)
    assert "leg_true" not in inspect.getsource(_compute_alignment)

def test_enum_complete():
    assert len(FAILURE_TYPES) == 8
    assert "UNKNOWN" in FAILURE_TYPE_SET

def test_classifier_deterministic():
    e = {"category": "logic", "message": "stale", "reasons": ["stale"]}
    assert classify_failure(e, None) == classify_failure(e, None)
```

### Integration Tests

```python
def test_pipeline_all_fields(monkeypatch):
    for entry in summary["trajectory"]:
        for field in ["llm_eval_blind_verdict", "llm_eval_blind_type",
                      "llm_eval_blind_raw", "llm_eval_blind_parse_error",
                      "llm_eval_conditioned_verdict", "llm_eval_conditioned_type",
                      "llm_eval_conditioned_raw", "llm_eval_conditioned_parse_error",
                      "classifier_failure_type", "reasoning_matches_truth",
                      "leg_true", "leg_strong_primary", "leg_keyword_only"]:
            assert field in entry

def test_replay():
    for entry in trajectory:
        assert _compute_leg_true(entry) == entry["leg_true"]
```
