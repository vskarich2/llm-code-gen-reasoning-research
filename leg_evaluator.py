"""LEG (Latent Execution Gap) evaluator module.

Measures whether a model's reasoning correctly identifies the failure mechanism
even when its code fails. ANALYSIS ONLY — never used in retry loop control.

Components:
  - Strict parser: accepts exactly "VERDICT ; FAILURE_TYPE" or rejects
  - Blind evaluator: infers failure type without seeing classifier output
  - Conditioned evaluator: given classifier type (for bias measurement)
  - LEG_true computation: blind verdict + blind type == classifier type
"""

from llm import call_model
from failure_classifier import FAILURE_TYPES, FAILURE_TYPE_SET

# ============================================================
# VERDICT ENUM
# ============================================================

_VALID_VERDICTS = frozenset(["YES", "NO"])


# ============================================================
# EVALUATOR PROMPTS
# ============================================================

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

_CRIT_LITE_CONDITIONED_PROMPT = _CRIT_LITE_BLIND_PROMPT.replace(
    "## Developer's Reasoning\n{reasoning}",
    "## Developer's Reasoning\n{reasoning}\n\n## System-Detected Failure Type\n{classifier_type}",
)


# ============================================================
# STRICT PARSER
# ============================================================


def parse_evaluator_output(raw):
    """Parse evaluator output. Strict contract:
    - Exactly one non-empty line
    - That line contains exactly one semicolon
    - Left of semicolon is a valid verdict
    - Right of semicolon is a valid failure type
    - Any deviation -> parse failure

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


# ============================================================
# EVALUATOR FUNCTION
# ============================================================


def evaluate_reasoning(
    model, reasoning_text, code_k, error_obj, classifier_type=None, blind=True, eval_model=None
):
    """CRIT-lite evaluator. ANALYSIS ONLY — never in retry loop.

    Args:
        model: the model being evaluated (used as fallback if eval_model not set)
        eval_model: override model for the evaluator LLM call. If None, uses `model`.
        blind: if True, classifier_type is NOT included in prompt.

    Returns: {
        "verdict": str|None,       "YES" or "NO" or None
        "inferred_type": str|None, member of FAILURE_TYPE_SET or None
        "raw": str|None,           raw LLM output
        "parse_error": str|None    reason for failure or None
    }
    """
    error_category = error_obj.get("category", "unknown")
    error_message = (error_obj.get("message") or "")[:300]
    test_reasons = "\n".join(f"- {r}" for r in (error_obj.get("reasons") or [])[:5])

    _eval_vars = {
        "code": code_k[:1200],
        "error_category": error_category,
        "error_message": error_message,
        "test_reasons": test_reasons,
        "reasoning": reasoning_text[:800],
    }
    if blind:
        from assembly_engine import build as _assembly_build
        _rendered = _assembly_build(["evaluate_reasoning_blind"], _eval_vars)
        prompt = _rendered.final_prompt
    else:
        _eval_vars["classifier_type"] = classifier_type or "UNKNOWN"
        from assembly_engine import build as _assembly_build
        _rendered = _assembly_build(["evaluate_reasoning_conditioned"], _eval_vars)
        prompt = _rendered.final_prompt

    try:
        use_model = eval_model or model
        raw = call_model(prompt, model=use_model, raw=True)
        return parse_evaluator_output(raw)
    except Exception as e:
        return {
            "verdict": None,
            "inferred_type": None,
            "raw": None,
            "parse_error": f"exception:{e}",
        }


# ============================================================
# LEG COMPUTATION (pure functions, no LLM calls)
# ============================================================


def compute_leg_true(entry):
    """Primary LEG metric. Uses ONLY 4 fields:
    llm_eval_blind_verdict, llm_eval_blind_type, classifier_failure_type, pass.
    """
    if entry.get("pass", True):
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


def compute_reasoning_matches_truth(entry):
    """Does the evaluator's inferred type match the classifier's detected type?"""
    blind_type = entry.get("llm_eval_blind_type")
    classifier_type = entry.get("classifier_failure_type")
    if blind_type is None or classifier_type is None:
        return False
    if blind_type == "UNKNOWN":
        return False
    return blind_type == classifier_type


def compute_evaluator_bias(trajectory):
    """Measure confirmation bias between blind and conditioned evaluators."""
    blind_yes = sum(1 for e in trajectory if e.get("llm_eval_blind_verdict") == "YES")
    conditioned_yes = sum(1 for e in trajectory if e.get("llm_eval_conditioned_verdict") == "YES")
    total = sum(
        1
        for e in trajectory
        if e.get("llm_eval_blind_verdict") is not None
        and e.get("llm_eval_conditioned_verdict") is not None
    )

    bias_rate_relative = (
        round((conditioned_yes - blind_yes) / blind_yes, 3) if blind_yes > 0 else None
    )
    bias_rate_absolute = round((conditioned_yes - blind_yes) / total, 3) if total > 0 else None

    return {
        "blind_yes": blind_yes,
        "conditioned_yes": conditioned_yes,
        "total_evaluated": total,
        "bias_rate_relative": bias_rate_relative,
        "bias_rate_absolute": bias_rate_absolute,
    }
