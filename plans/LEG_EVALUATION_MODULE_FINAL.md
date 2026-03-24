# Evaluation Module — Final Revised Plan

**Date:** 2026-03-23
**Status:** Implementation-ready
**Purpose:** Measure the Latent Execution Gap (LEG) — cases where a model semantically identifies the true failure mechanism but code generation still fails.

---

## 1. Overview

This module measures one thing:

> Given a failed code generation attempt, did the model's reasoning correctly identify the specific failure mechanism?

If yes AND code still fails → LEG event.

The module consists of:
- A blind LLM evaluator that returns a structured verdict + failure type
- A conditioned LLM evaluator (same, but given the system-detected failure type) for bias measurement
- A strict parser that accepts exact format or rejects
- Alignment metrics for the plan-then-code intervention
- LEG subtype decomposition (coupling vs execution)

The module does NOT:
- Use keyword matching for any primary metric
- Use fuzzy matching, regex fallback, embedding similarity, or ontology mapping
- Participate in retry loop control decisions

---

## 2. Definitions

### LEG_true

```
LEG_true(k) =
    llm_eval_blind_verdict(k) == "YES"
    AND llm_eval_blind_type(k) == classifier_failure_type(k)
    AND llm_eval_blind_type(k) != "UNKNOWN"
    AND pass(k) == False
```

`llm_eval_blind_verdict`: the blind evaluator's judgment of reasoning correctness.
`llm_eval_blind_type`: the blind evaluator's inferred failure type from a closed enum.
`classifier_failure_type`: the heuristic classifier's detected failure type from the same closed enum.

LEG_true fires when two methods — one semantic (LLM), one structural (classifier) — independently agree on the failure type, AND the semantic method confirms the reasoning is correct, AND the code fails.

### LEG_coupling

```
LEG_coupling(k) =
    LEG_true(k) == True
    AND alignment_success(k) == False
```

The model understood the bug but the code does not implement its reasoning. Available only for the `retry_alignment` condition.

### LEG_execution

```
LEG_execution(k) =
    LEG_true(k) == True
    AND alignment_success(k) == True
```

The model understood the bug AND the code appears to implement the plan, but tests still fail. Available only for the `retry_alignment` condition.

### No circularity

`LEG_true` is computed from evaluator verdict + evaluator type + classifier type + test pass/fail. It does NOT reference alignment.

`alignment_success` is computed from plan extraction + step coverage + plan-failure match. It does NOT reference LEG_true.

`LEG_coupling` and `LEG_execution` combine these two computations. Neither input depends on the other.

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

**8 types. No hierarchy. No subtypes. No synonyms.**

| Type | What it covers |
|---|---|
| TEMPORAL_ORDERING | Operations in wrong order, stale reads, race conditions |
| HIDDEN_DEPENDENCY | Missing import, undefined reference, implicit coupling between modules |
| INVARIANT_VIOLATION | Conservation law broken, atomicity failure, rollback missing |
| PARTIAL_STATE_UPDATE | Some fields updated but not others, incomplete mutation |
| RETRY_LOGIC_BUG | Duplicate operations on retry, idempotency failure |
| EDGE_CASE_MISSED | Null, empty, zero, boundary, off-by-one |
| LOGGING_INCONSISTENCY | Side effects in wrong order, audit trail broken |
| UNKNOWN | Cannot confidently determine |

### How classifier_failure_type is assigned

`failure_classifier.classify_failure(error_obj, critique)` returns `failure_type_final` from this same enum. It uses critique keywords → error category → error message keywords → UNKNOWN. This is the structural signal.

### How evaluator_type is assigned

The blind LLM evaluator infers the type from code + test failure + reasoning. It outputs a string from the same enum. Parsing is strict (see §4).

### Category boundaries

Categories do not overlap by definition. A failure is classified into exactly one type. If a failure could plausibly fit two categories, the evaluator and classifier will each pick one. Their agreement (or disagreement) is the signal. The system does not resolve ambiguity — it measures it.

---

## 4. Evaluator Contract

### 4A. Blind Evaluator Prompt

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

**Design decisions:**
- PARTIAL is removed. The verdict is binary: YES or NO. This eliminates a category that invites disagreement and weakens the claim. If reasoning is only partially correct, it is NO for the purpose of LEG_true.
- The prompt says "If uncertain, answer NO." This is conservative by design. LEG_true should undercount, not overcount.
- The failure type vocabulary is listed verbatim in the prompt. The evaluator cannot invent types.

### 4B. Conditioned Evaluator Prompt

Identical to blind, with one addition after `## Developer's Reasoning`:

```
## System-Detected Failure Type
{classifier_type}
```

Everything else is the same.

### 4C. Evaluator Function

```python
def _evaluate_reasoning(model, reasoning_text, code_k, error_obj,
                        classifier_type=None, blind=True):
    """CRIT-lite evaluator. ANALYSIS ONLY.

    Returns dict with verdict and inferred_type. Both are parsed strings
    from closed enums, or None on parse failure.
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
    except Exception:
        return {"verdict": None, "inferred_type": None, "raw": None, "parse_error": "exception"}
```

### 4D. Parser — Strict, No Fallback

```python
_VALID_VERDICTS = frozenset(["YES", "NO"])

def _parse_evaluator_output(raw):
    """Parse 'VERDICT ; FAILURE_TYPE' output. Strict: no repair, no fuzzy match.

    Returns:
        {"verdict": str|None, "inferred_type": str|None, "raw": str, "parse_error": str|None}
    """
    result = {"verdict": None, "inferred_type": None, "raw": raw, "parse_error": None}

    if not raw or not raw.strip():
        result["parse_error"] = "empty_response"
        return result

    # Take the first non-empty line only
    first_line = None
    for line in raw.strip().splitlines():
        line = line.strip()
        if line:
            first_line = line
            break

    if not first_line:
        result["parse_error"] = "no_content_line"
        return result

    # Split on semicolon
    parts = first_line.split(";")
    if len(parts) != 2:
        result["parse_error"] = f"expected_2_parts_got_{len(parts)}"
        return result

    verdict_raw = parts[0].strip().upper()
    type_raw = parts[1].strip().upper().replace(" ", "_")

    # Strict enum check — no synonyms, no fuzzy match
    if verdict_raw not in _VALID_VERDICTS:
        result["parse_error"] = f"invalid_verdict_{verdict_raw}"
        return result

    if type_raw not in FAILURE_TYPE_SET:
        result["parse_error"] = f"invalid_type_{type_raw}"
        return result

    result["verdict"] = verdict_raw
    result["inferred_type"] = type_raw
    return result
```

**Forbidden behaviors (explicitly stated):**
- No keyword matching on the raw output
- No regex extraction of partial matches
- No "closest enum value" lookup
- No embedding similarity
- No ontology mapping (e.g., "ordering" → TEMPORAL_ORDERING)
- No auto-correction of typos
- No retry on parse failure

If the output does not match `VERDICT ; FAILURE_TYPE` with both values in their respective enums, the result is `verdict=None, inferred_type=None, parse_error=<reason>`. The attempt is NOT counted in any LEG metric. It is counted in the parse failure rate.

---

## 5. Alignment Metric

### 5A. Plan Extraction

```python
def _extract_plan(raw_output):
    """Extract structured plan from model output.

    Returns {"steps": list[str], "invariant": str|None} or None.
    """
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

A "step" is a numbered line (e.g., "1. In create_config: add .copy()") extracted from the PLAN block. Steps are the unit of coverage measurement.

### 5B. Step Coverage

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
        return True
    code_lower = code.lower()
    hits = sum(1 for kw in keywords if kw in code_lower)
    keyword_covered = hits / len(keywords) >= 0.3
    has_action = any(tok in code for tok in _ACTION_TOKENS)
    return keyword_covered and has_action

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
```

`step_coverage` is a float in [0, 1]. It is the fraction of plan steps whose action keywords appear in the code AND the code contains at least one action token. This is a heuristic — it is used for alignment analysis, NOT for LEG_true.

### 5C. Plan-Failure Match

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

### 5D. Alignment Score and Alignment Success

```python
ALIGNMENT_THRESHOLD = 0.5

def _compute_alignment(plan, code, error_obj, classification):
    step_coverage, per_step = _compute_step_coverage(plan, code)
    pmf = _plan_matches_failure(plan, error_obj, classification)

    alignment_success = (pmf is True) and (step_coverage >= ALIGNMENT_THRESHOLD)

    return {
        "step_coverage": step_coverage,
        "per_step": per_step,
        "plan_matches_failure": pmf,
        "alignment_success": alignment_success,
    }
```

`alignment_score` = `step_coverage` (continuous).
`alignment_success` = `plan_matches_failure == True AND step_coverage >= 0.5` (binary).

The threshold 0.5 means at least half the plan steps are reflected in the code. This is permissive by design — we want to distinguish "plan totally ignored" from "plan partially implemented." Threshold sensitivity can be explored post-hoc using the raw `step_coverage` values.

Both continuous and binary are logged.

---

## 6. Metric Hierarchy

### Primary metric (all claims rest on this):

```
LEG_true
```

LEG_true is the publishable number. It measures: "the fraction of failed attempts where the model semantically identified the true failure mechanism." No keyword heuristic participates.

### Primary robustness check:

```
LEG_strong_primary (VERY_HIGH confidence: keyword + classifier_alignment + evaluator YES, all agree)
```

This adds the keyword signal as a third confirmation. It is stricter than LEG_true (requires all three signals) but includes a heuristic component. It validates that LEG_true is not an artifact of evaluator-classifier collusion.

### Diagnostic / exploratory (not used for primary claims):

```
LEG_keyword (keyword signal only — backward compatibility, upper bound)
```

### Subtype decomposition (alignment condition only):

```
LEG_coupling (LEG_true + not aligned)
LEG_execution (LEG_true + aligned)
```

**Explicit statement:** Keyword-based LEG is NOT used for any primary analysis. It is retained for backward compatibility with prior ablation logs and as a cheap diagnostic signal.

---

## 7. Subtype Decomposition

### LEG_coupling

```
LEG_coupling(k) = LEG_true(k) AND alignment_success(k) == False
```

**Interpretation:** The model's reasoning correctly identifies the failure mechanism (confirmed by blind evaluator + classifier agreement), but the model's code does not implement its own reasoning (low step coverage or wrong-topic plan). This is a **reasoning→code translation failure**.

**Mapped failure mode:** The bottleneck is between understanding and implementation. Interventions that force explicit plan-code mapping (structured alignment prompts) should reduce LEG_coupling.

### LEG_execution

```
LEG_execution(k) = LEG_true(k) AND alignment_success(k) == True
```

**Interpretation:** The model's reasoning is correct AND the code appears to implement the plan at the step level, but tests still fail. This is an **execution fidelity failure** — the code is wrong at a granularity finer than the plan captures.

**Mapped failure mode:** The bottleneck is in code-level correctness even when the plan is right. This is harder to fix with prompting — it may require stronger code generation capabilities.

### Availability

LEG_coupling and LEG_execution are `None` for non-alignment conditions (no plan data). They are computed only for `retry_alignment`.

### No circularity

LEG_true does not reference alignment. Alignment does not reference LEG_true. They are combined only in the subtype definitions.

---

## 8. Bias Metric

### Definition

```python
def _compute_evaluator_bias(trajectory):
    blind_yes = sum(1 for e in trajectory
                    if e.get("llm_eval_blind_verdict") == "YES")
    cond_yes = sum(1 for e in trajectory
                   if e.get("llm_eval_conditioned_verdict") == "YES")
    total = sum(1 for e in trajectory
                if e.get("llm_eval_blind_verdict") is not None
                and e.get("llm_eval_conditioned_verdict") is not None)

    if blind_yes == 0:
        bias_rate_relative = None  # undefined when denominator is 0
    else:
        bias_rate_relative = round((cond_yes - blind_yes) / blind_yes, 3)

    bias_rate_absolute = round((cond_yes - blind_yes) / total, 3) if total > 0 else None

    return {
        "blind_yes": blind_yes,
        "conditioned_yes": cond_yes,
        "total_evaluated": total,
        "bias_rate_relative": bias_rate_relative,
        "bias_rate_absolute": bias_rate_absolute,
    }
```

`bias_rate_relative` measures: "how much does seeing the classifier type inflate the evaluator's YES rate, relative to the blind baseline?" A value of 0.40 means 40% inflation.

`bias_rate_absolute` is diagnostic only.

If `bias_rate_relative > 0.30`: the conditioned evaluator is materially biased. All primary analysis uses blind evaluator only. The conditioned mode becomes calibration data.

---

## 9. Logging Schema

### Per-iteration fields (all new fields from this module)

```
llm_eval_blind_verdict     : str | None     "YES", "NO", or None on parse failure
llm_eval_blind_type        : str | None     enum value or None on parse failure
llm_eval_blind_parse_error : str | None     parse error reason or None
llm_eval_cond_verdict      : str | None     same for conditioned mode
llm_eval_cond_type         : str | None
llm_eval_cond_parse_error  : str | None
reasoning_matches_truth    : bool | None    llm_eval_blind_type == classifier_failure_type (and neither is UNKNOWN/None)
leg_true                   : bool           LEG_true(k) as defined in §2
leg_coupling               : bool | None    None if not alignment condition
leg_execution              : bool | None    None if not alignment condition
leg_keyword_only           : bool           keyword_signal AND not pass (backward compat)
```

### Per-iteration fields (alignment condition only)

```
plan                       : dict | None    {"steps": [...], "invariant": "..."}
alignment_step_coverage    : float | None   [0, 1]
alignment_per_step         : list | None    [{"step": "...", "implemented": bool}, ...]
alignment_plan_matches     : bool | None
alignment_success          : bool | None
```

### Per-summary fields

```
leg_rate_true              : float          LEG_true events / failed attempts
leg_rate_keyword           : float          keyword LEG / failed attempts (diagnostic)
leg_resolution_rate_true   : float | None   LEG_true(k) ∧ pass(k+1) / LEG_true(k)
leg_coupling_rate          : float | None   LEG_coupling / failed attempts (alignment only)
leg_execution_rate         : float | None   LEG_execution / failed attempts (alignment only)
evaluator_parse_failure_rate : float        parse failures / total eval calls
evaluator_unknown_type_rate  : float        UNKNOWN type / successful parses
evaluator_bias             : dict           see §8
alignment_leg_split        : dict | None    see §5, includes raw score values + distribution
```

### Storage format

All fields are JSON-serializable. Appended to existing 3-file JSONL system. Per-iteration fields are in the trajectory entry dict. Per-summary fields are in the summary record.

### Replay compatibility

Given the same log files, all LEG metrics can be recomputed by:
1. Reading `llm_eval_blind_verdict`, `llm_eval_blind_type`, `classifier_failure_type` from each entry
2. Applying the LEG_true formula
3. Reading `alignment_success` for subtype decomposition

No external state is needed. All inputs are logged.

---

## 10. Pipeline

### End-to-end flow for one case

```
1. CASE INPUT
   case dict with id, task, code_files, failure_mode

2. MODEL GENERATION (inside retry loop)
   for k in range(max_iterations):
       prompt = build_prompt(case, condition, prev_code, test_output, ...)
       raw = call_model(prompt, model)
       parsed = parse_model_response(raw)
       code_k = parsed["code"]
       reasoning_k = parsed["reasoning"]

3. EXECUTION
       ev = _safe_evaluate(case, raw)

4. CLASSIFICATION (heuristic, inside loop)
       classification = classify_failure(error_obj, critique)
       → classifier_failure_type = classification["failure_type_final"]

5. ALIGNMENT (alignment condition only, inside loop)
       plan = _extract_plan(raw)
       alignment = _compute_alignment(plan, code_k, error_obj, classification)

6. TRAJECTORY ENTRY (inside loop, before stop conditions)
       entry = {all existing fields + new fields with None defaults}
       trajectory.append(entry)

7. STOP CONDITIONS (unchanged — uses control signals only)

--- LOOP ENDS ---

8. LLM EVALUATION (post-hoc, outside loop, gated by use_llm_eval)
   for entry in trajectory:
       if not entry["pass"] and entry["reasoning"]:
           blind_result = _evaluate_reasoning(model, ..., blind=True)
           cond_result = _evaluate_reasoning(model, ..., blind=False)
           entry["llm_eval_blind_verdict"] = blind_result["verdict"]
           entry["llm_eval_blind_type"] = blind_result["inferred_type"]
           entry["llm_eval_blind_parse_error"] = blind_result["parse_error"]
           entry["llm_eval_cond_verdict"] = cond_result["verdict"]
           entry["llm_eval_cond_type"] = cond_result["inferred_type"]
           entry["llm_eval_cond_parse_error"] = cond_result["parse_error"]

9. LEG COMPUTATION (post-hoc, after evaluator)
   for entry in trajectory:
       if not entry["pass"]:
           classifier_type = (entry.get("classification") or {}).get("failure_type_final")
           blind_type = entry.get("llm_eval_blind_type")
           blind_verdict = entry.get("llm_eval_blind_verdict")

           entry["reasoning_matches_truth"] = (
               blind_type is not None
               and classifier_type is not None
               and blind_type == classifier_type
               and blind_type != "UNKNOWN"
           )

           entry["leg_true"] = (
               blind_verdict == "YES"
               and entry["reasoning_matches_truth"]
           )

           if entry.get("alignment_success") is not None:
               entry["leg_coupling"] = entry["leg_true"] and not entry["alignment_success"]
               entry["leg_execution"] = entry["leg_true"] and entry["alignment_success"]

10. SUMMARY CONSTRUCTION
    Compute aggregate metrics from trajectory entries.
    Write summary record to log.

11. LOGGING
    All fields written to 3-file JSONL system (metadata + prompts + responses).
```

---

## 11. Failure Modes and Edge Cases

### Malformed LLM evaluator output

**Behavior:** `_parse_evaluator_output` returns `verdict=None, inferred_type=None, parse_error=<reason>`.
**Effect:** The attempt is NOT counted in any LEG metric. It IS counted in `evaluator_parse_failure_rate`.
**No retry.** No auto-correction. No fallback.

### UNKNOWN inferred type

**Behavior:** Parser returns `verdict="YES", inferred_type="UNKNOWN"`.
**Effect:** `reasoning_matches_truth = False` (because UNKNOWN != any classifier type). `leg_true = False`. The attempt is NOT a LEG event.
**Tracked in:** `evaluator_unknown_type_rate`.

### Multiple types in output

**Behavior:** Parser takes the first non-empty line. If that line has exactly 2 semicolon-separated parts, both valid, it succeeds. Otherwise parse failure.
**No multi-type handling.** One type per evaluation.

### Invalid enum value

**Behavior:** Parser returns `parse_error="invalid_type_<value>"`. `verdict=None, inferred_type=None`.
**No closest-match lookup.** Exact string match against `FAILURE_TYPE_SET` only.

### Missing fields in trajectory entry

**Behavior:** All new fields default to `None` at entry creation. LEG computation checks for `None` before comparison. A `None` verdict or type results in `leg_true = False` for that entry.

### Classifier returns UNKNOWN

**Behavior:** `classifier_failure_type = "UNKNOWN"`. `reasoning_matches_truth = False` (because UNKNOWN on either side blocks the match). `leg_true = False`.

### Both evaluator and classifier return the same wrong type

**Risk:** If both independently agree on the WRONG type, and the evaluator says YES, `leg_true` fires. This is a false positive.
**Mitigation:** This is the residual false positive rate. It is inherent in any system without human annotation. The conservative evaluator prompt ("only YES if clearly correct") reduces but does not eliminate this. Reporting `LEG_strong_primary` (adds keyword signal as third check) helps bound the issue.

---

## 12. Testing Plan

### Unit Tests: Parser

```python
def test_parse_valid():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "TEMPORAL_ORDERING"
    assert r["parse_error"] is None

def test_parse_valid_no():
    r = _parse_evaluator_output("NO ; UNKNOWN")
    assert r["verdict"] == "NO"
    assert r["inferred_type"] == "UNKNOWN"

def test_parse_rejects_partial():
    """PARTIAL is not a valid verdict in v5."""
    r = _parse_evaluator_output("PARTIAL ; HIDDEN_DEPENDENCY")
    assert r["verdict"] is None
    assert r["parse_error"] is not None

def test_parse_rejects_invalid_type():
    r = _parse_evaluator_output("YES ; WRONG_TYPE")
    assert r["verdict"] is None
    assert r["inferred_type"] is None

def test_parse_rejects_missing_semicolon():
    r = _parse_evaluator_output("YES TEMPORAL_ORDERING")
    assert r["verdict"] is None

def test_parse_rejects_empty():
    r = _parse_evaluator_output("")
    assert r["verdict"] is None

def test_parse_rejects_garbage():
    r = _parse_evaluator_output("The reasoning appears to be correct because...")
    assert r["verdict"] is None

def test_parse_strips_whitespace():
    r = _parse_evaluator_output("  YES  ;  HIDDEN_DEPENDENCY  ")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "HIDDEN_DEPENDENCY"

def test_parse_takes_first_line():
    r = _parse_evaluator_output("YES ; TEMPORAL_ORDERING\nsome extra text")
    assert r["verdict"] == "YES"
    assert r["inferred_type"] == "TEMPORAL_ORDERING"
```

### Unit Tests: Enum Validation

```python
def test_all_failure_types_in_set():
    assert len(FAILURE_TYPES) == 8
    assert "UNKNOWN" in FAILURE_TYPE_SET
    for ft in FAILURE_TYPES:
        assert ft == ft.upper()
        assert " " not in ft

def test_no_synonyms():
    """No two types should be semantically equivalent."""
    assert "ORDERING_BUG" not in FAILURE_TYPE_SET
    assert "RACE_CONDITION" not in FAILURE_TYPE_SET
    assert "OFF_BY_ONE" not in FAILURE_TYPE_SET
```

### Unit Tests: LEG_true Correctness

```python
def test_leg_true_basic():
    entry = {"pass": False, "llm_eval_blind_verdict": "YES",
             "llm_eval_blind_type": "TEMPORAL_ORDERING",
             "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(entry) is True

def test_leg_true_type_mismatch():
    entry = {"pass": False, "llm_eval_blind_verdict": "YES",
             "llm_eval_blind_type": "TEMPORAL_ORDERING",
             "classification": {"failure_type_final": "HIDDEN_DEPENDENCY"}}
    assert _compute_leg_true(entry) is False

def test_leg_true_unknown_blocks():
    entry = {"pass": False, "llm_eval_blind_verdict": "YES",
             "llm_eval_blind_type": "UNKNOWN",
             "classification": {"failure_type_final": "UNKNOWN"}}
    assert _compute_leg_true(entry) is False

def test_leg_true_no_verdict():
    entry = {"pass": False, "llm_eval_blind_verdict": "NO",
             "llm_eval_blind_type": "TEMPORAL_ORDERING",
             "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(entry) is False

def test_leg_true_pass_blocks():
    entry = {"pass": True, "llm_eval_blind_verdict": "YES",
             "llm_eval_blind_type": "TEMPORAL_ORDERING",
             "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(entry) is False

def test_leg_true_none_verdict():
    entry = {"pass": False, "llm_eval_blind_verdict": None,
             "llm_eval_blind_type": None,
             "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(entry) is False
```

### Integration Tests: Pipeline Consistency

```python
def test_full_pipeline_produces_all_fields(monkeypatch):
    """Run one case through entire pipeline, verify all LEG fields present."""
    # Mock LLM to return deterministic evaluator output
    ...
    for entry in summary["trajectory"]:
        assert "llm_eval_blind_verdict" in entry
        assert "llm_eval_blind_type" in entry
        assert "leg_true" in entry
        assert isinstance(entry["leg_true"], bool)

def test_replay_determinism():
    """Recompute LEG metrics from logged fields. Must match original."""
    for entry in trajectory:
        recomputed = _compute_leg_true(entry)
        assert recomputed == entry["leg_true"]
```

### Invariant Tests

```python
def test_no_heuristic_in_leg_true():
    """LEG_true must NOT reference keyword_signal or _detect_latent_signal."""
    import inspect
    source = inspect.getsource(_compute_leg_true)
    assert "keyword" not in source.lower()
    assert "latent_signal" not in source
    assert "detect_failure_type_from_reasoning" not in source

def test_leg_true_uses_exact_match():
    """Type comparison must be == not 'in' or fuzzy."""
    # Verify that "TEMPORAL" does not match "TEMPORAL_ORDERING"
    entry = {"pass": False, "llm_eval_blind_verdict": "YES",
             "llm_eval_blind_type": "TEMPORAL",
             "classification": {"failure_type_final": "TEMPORAL_ORDERING"}}
    assert _compute_leg_true(entry) is False  # parse should have rejected "TEMPORAL"

def test_no_circularity():
    """LEG_true does not reference alignment. Alignment does not reference LEG_true."""
    import inspect
    leg_src = inspect.getsource(_compute_leg_true)
    assert "alignment" not in leg_src
    align_src = inspect.getsource(_compute_alignment)
    assert "leg_true" not in align_src
```
