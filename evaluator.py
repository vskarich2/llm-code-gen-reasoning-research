"""T3 Evaluation dispatcher.

Responsibilities:
  1. Route to execution-based evaluation (THE ONLY behavioral test)
  2. LLM-based classification of code_correct + reasoning_correct
  3. Derived categories: true_success, leg_true, lucky_fix, true_failure
  4. Evidence usage scoring (SCM experiment)

TWO sources of truth:
  - exec_evaluate: runs code, tests invariants → behavioral pass/fail
  - llm_classify: LLM judge → code_correct, reasoning_correct, failure_type

There are NO heuristic keyword-matching classifiers. ALL classification
comes from the LLM evaluator. This is a core measurement decision.
"""

import json
import logging
import re

# HARD IMPORT — if this fails, the system cannot produce valid results.
from exec_eval import exec_evaluate

from llm import call_model
from failure_classifier import FAILURE_TYPE_SET

_log = logging.getLogger("t3.evaluator")


# ============================================================
# LLM CLASSIFIER — replaces all heuristic reasoning detection
# ============================================================

_CLASSIFY_PROMPT = """You are evaluating whether a developer's REASONING correctly identifies the root cause of a software bug.

You are ONLY evaluating reasoning quality. You are NOT judging whether the code is correct.
The code may be correct or incorrect — that is NOT your task.

Do NOT assume the code is correct or incorrect based on appearance.
Do NOT infer correctness from likely execution success.
Focus ONLY on whether the reasoning correctly identifies the bug mechanism and proposes a fix consistent with that mechanism.

# Your Task

Determine TWO things:

1. **reasoning_correct**: Does the reasoning correctly identify the TRUE failure mechanism?
   - TRUE if the reasoning identifies the correct root cause AND explains how the bug manifests
   - FALSE if the reasoning is wrong, vague, irrelevant, or identifies the wrong mechanism

2. **failure_type**: What type of failure mechanism does this bug involve?
   Choose EXACTLY one from:
   {failure_types}

# Inputs

## Task Description
{task}

## Developer's Reasoning
{reasoning}

## Code Produced by Developer
```python
{code}
```

# Rules
- Evaluate ONLY reasoning quality — whether the developer understood the bug
- Do NOT judge whether the code would pass or fail tests
- A developer can have perfect reasoning but write broken code, or vice versa
- Be conservative: only YES if the reasoning clearly identifies the correct mechanism
- Vague reasoning ("I fixed the bug") is NOT correct reasoning
- If uncertain, answer NO

# Output
Return EXACTLY one line:
<REASONING_CORRECT> ; <FAILURE_TYPE>

Where REASONING_CORRECT is YES or NO.

Examples:
YES ; HIDDEN_DEPENDENCY
NO ; INVARIANT_VIOLATION
YES ; TEMPORAL_ORDERING
NO ; UNKNOWN

Return ONLY this one line. No explanation."""

_VALID_BOOLS = frozenset(["YES", "NO"])


def parse_classify_output(raw: str) -> dict:
    """Parse LLM reasoning classifier output. Strict contract.

    Expected format: REASONING_CORRECT ; FAILURE_TYPE
    Any deviation → parse_error, fields set to None.
    NEVER silently defaults.
    """
    result = {
        "reasoning_correct": None,
        "failure_type": None,
        "raw": raw,
        "parse_error": None,
    }

    if not raw or not raw.strip():
        result["parse_error"] = "empty_response"
        return result

    nonempty_lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]

    if len(nonempty_lines) == 0:
        result["parse_error"] = "no_nonempty_lines"
        return result

    if len(nonempty_lines) > 1:
        result["parse_error"] = f"extra_lines:got_{len(nonempty_lines)}"
        return result

    parts = nonempty_lines[0].split(";")
    if len(parts) != 2:
        result["parse_error"] = f"expected_2_parts_got_{len(parts)}"
        return result

    reasoning_raw = parts[0].strip().upper()
    type_raw = parts[1].strip().upper().replace(" ", "_")

    if reasoning_raw not in _VALID_BOOLS:
        result["parse_error"] = f"invalid_reasoning_correct:{reasoning_raw}"
        return result

    if type_raw not in FAILURE_TYPE_SET:
        result["parse_error"] = f"invalid_failure_type:{type_raw}"
        return result

    result["reasoning_correct"] = reasoning_raw == "YES"
    result["failure_type"] = type_raw
    return result


def _get_eval_model() -> str:
    """Get evaluator model from config. No hardcoded fallback."""
    from experiment_config import get_config
    return get_config().models.evaluator.name


def classify_parse_category(reasoning: str, parse_error: str | None,
                             raw_fallback: bool = False) -> str:
    """Determine parse category for reasoning input.

    Returns one of: CLEAN, REASONING_LOST, CODE_LOST, PARTIAL_JSON_RECOVERED,
    MALFORMED_BUT_RECOVERED, STRUCTURE_MISSING.
    """
    if not parse_error and reasoning and reasoning.strip():
        return "CLEAN"
    if parse_error and (not reasoning or not reasoning.strip()):
        if "STRUCTURE_MISSING" in str(parse_error) or "schema" in str(parse_error).lower():
            return "STRUCTURE_MISSING"
        if raw_fallback:
            return "CODE_LOST"
        return "REASONING_LOST"
    if parse_error and reasoning and reasoning.strip():
        if "lenient" in str(parse_error):
            return "PARTIAL_JSON_RECOVERED"
        return "MALFORMED_BUT_RECOVERED"
    if not parse_error and (not reasoning or not reasoning.strip()):
        # No parse error but empty reasoning: this is genuine empty reasoning
        # (model chose not to explain), NOT a parse failure. Classify normally.
        return "CLEAN"
    return "CLEAN"


# Categories where classification is disallowed (reasoning is unrecoverable)
_CLASSIFICATION_DISALLOWED = frozenset({
    "REASONING_LOST", "CODE_LOST", "STRUCTURE_MISSING",
})


def llm_classify(case: dict, code: str, reasoning: str,
                 eval_model: str | None = None,
                 parse_error: str | None = None,
                 raw_fallback: bool = False) -> dict:
    """Run the LLM reasoning classifier on an attempt.

    Evaluates ONLY reasoning correctness. Does NOT judge code correctness.
    Code correctness comes from execution tests — never from this classifier.

    The prompt deliberately excludes execution results to prevent bias.

    PARSE GATE (Fix D): If reasoning is empty/missing due to a parse failure,
    classification is skipped and reasoning_correct=None is returned. Parse
    failures MUST NOT produce reasoning_correct=False.

    Args:
        case: benchmark case dict (has "task", "failure_mode", "id")
        code: extracted code from the model's response
        reasoning: extracted reasoning from the model's response
        eval_model: model to use for classifier. If None, uses default.
        parse_error: parse error from upstream parsing, if any.
        raw_fallback: True if the response hit the raw_fallback parser tier.

    Returns dict with:
        reasoning_correct: bool or None (None on parse failure OR reasoning lost)
        failure_type: str or None
        classify_raw: str or None
        classify_parse_error: str or None
        eval_model_actual: str — the model actually used for classification
        parse_category: str — the parse category of the reasoning input
    """
    # Determine parse category
    parse_cat = classify_parse_category(reasoning, parse_error, raw_fallback)

    # PARSE GATE: if reasoning is unrecoverable, do NOT classify.
    # Return None instead of False. This is a correctness fix.
    if parse_cat in _CLASSIFICATION_DISALLOWED:
        _log.warning(
            "PARSE GATE: skipping classification for case %s — "
            "parse_category=%s, parse_error=%s, reasoning empty=%s",
            case.get("id", "?"), parse_cat, parse_error,
            not (reasoning and reasoning.strip()),
        )
        return {
            "reasoning_correct": None,
            "failure_type": None,
            "classify_raw": None,
            "classify_parse_error": f"GATED:{parse_cat}",
            "classifier_prompt": None,
            "eval_model_actual": None,
            "parse_category": parse_cat,
        }

    # Truncation limits from config
    from experiment_config import get_config
    eval_cfg = get_config().models.evaluator
    prompt = _CLASSIFY_PROMPT.format(
        failure_types=", ".join(sorted(FAILURE_TYPE_SET)),
        task=case.get("task", "")[:eval_cfg.max_task_chars],
        code=(code or "")[:eval_cfg.max_code_chars],
        reasoning=(reasoning or "")[:eval_cfg.max_reasoning_chars],
    )

    # Evaluator model from config — no hardcoded fallback
    model = eval_model or _get_eval_model()

    try:
        raw = call_model(prompt, model=model, raw=True)
        parsed = parse_classify_output(raw)
        return {
            "reasoning_correct": parsed["reasoning_correct"],
            "failure_type": parsed["failure_type"],
            "classify_raw": raw,
            "classify_parse_error": parsed["parse_error"],
            "classifier_prompt": prompt,
            "eval_model_actual": model,
            "parse_category": parse_cat,
        }
    except Exception as e:
        _log.error("LLM classifier call failed: %s", e)
        return {
            "reasoning_correct": None,
            "failure_type": None,
            "classify_raw": None,
            "classify_parse_error": f"exception:{e}",
            "classifier_prompt": prompt,
            "eval_model_actual": model,
            "parse_category": parse_cat,
        }


# ============================================================
# DERIVED CATEGORIES (pure computation — no LLM, no heuristics)
# ============================================================

def compute_category(code_correct: bool | None, reasoning_correct: bool | None) -> str:
    """Compute the alignment category.

    code_correct comes from execution tests (ground truth).
    reasoning_correct comes from LLM classifier.

    Returns one of: true_success, leg, lucky_fix, true_failure, unclassified.
    "unclassified" ONLY if reasoning classifier failed (None).
    """
    if code_correct is None or reasoning_correct is None:
        return "unclassified"
    if reasoning_correct and code_correct:
        return "true_success"
    if reasoning_correct and not code_correct:
        return "leg"
    if not reasoning_correct and code_correct:
        return "lucky_fix"
    return "true_failure"


def compute_alignment(code_correct: bool | None, reasoning_correct: bool | None) -> dict:
    """Compute alignment dict.

    code_correct: from execution tests (ground truth).
    reasoning_correct: from LLM reasoning classifier.
    """
    category = compute_category(code_correct, reasoning_correct)
    return {
        "category": category,
        "code_correct": code_correct,
        "reasoning_correct": reasoning_correct,
        "leg_true": category == "leg",
        "lucky_fix": category == "lucky_fix",
        "true_success": category == "true_success",
        "true_failure": category == "true_failure",
    }


# ============================================================
# BACKWARD COMPATIBILITY — heuristic reasoning detection (DEPRECATED)
# ============================================================

# _has and _low are still importable for any code that needs them,
# but they are NOT used for classification decisions.
from eval_cases import _has, _low  # noqa: F401

# _REASONING_SIGNALS is retained ONLY for the retry_harness heuristic_signal
# (which is logged but NOT used for classification decisions).
# This will be removed in a future cleanup.
_REASONING_SIGNALS = {
    "HIDDEN_DEPENDENCY": ["overwrite", "cache_put_if_absent.*different",
                          "not interchangeable", "stale", "live.*write",
                          "always.*overwrite", "won't overwrite"],
    "TEMPORAL_ORDERING": ["order", "before", "after", "sequence", "timing", "first"],
    "TEMPORAL_CAUSAL_ERROR": ["original data", "raw data", "before transform",
                              "different keys", "different semantic", "not.*replacement"],
    "INVARIANT_VIOLATION": ["partial failure", "money.*lost", "rollback",
                            "inconsistent", "atomicity", "failure window", "debit.*credit"],
    "STATE_SEMANTIC_VIOLATION": ["frozen", "get_committed_total", "preview",
                                 "stage.*without.*commit", "none.*not.*zero", "returns none"],
    "RACE_CONDITION": ["race", "lock", "concurren", "thread.*safe"],
    "IDEMPOTENCY_VIOLATION": ["idempoten", "accumulate", "double", "not.*safe.*retry"],
    "CACHE_ORDERING": ["version", "invalidat.*order", "conditional_set"],
    "PARTIAL_ROLLBACK": ["rollback", "release", "partial.*fail", "inconsisten"],
    "INIT_ORDER": ["lazy", "reset", "singleton", "init.*order"],
    "TIMING_DEPENDENCY": ["stale", "ttl", "timing", "fresh"],
    "SHARED_REFERENCE": ["shared.*ref", "mutable", "live.*dict", "copy.*break"],
    "SIDE_EFFECT_ORDER": ["snapshot.*order", "per.record", "verify_consistency"],
    "RETRY_DUPLICATION": ["double.*retry", "already.*retry", "seq.*increment"],
    "FLAG_DRIFT": ["global.*flag", "is_enabled", "compute_price.*global"],
    "EASY_TEMPORAL": ["log", "update", "order"],
    "EASY_CONSERVATION": ["balance", "total", "conserv"],
    "EASY_STATE_MACHINE": ["transition", "valid", "invalid"],
    "EASY_ALIASING": ["reference", "live", "mutati"],
    "CONSERVATION_VIOLATION": ["net", "amount.*fee", "mismatch", "conserv", "both sides"],
    "ALIASING": ["reference", "shared", "mutate.*default", "copy", "alias"],
    "EARLY_RETURN": ["return", "early", "exit", "skip", "short.circuit"],
    "INDEX_MISALIGN": ["index", "off.by.one", "offset", "boundary", "range"],
    "MISSING_BRANCH": ["branch", "case", "condition", "else", "fallthrough"],
    "MUTABLE_DEFAULT": ["mutable", "default", "shared", "argument", "parameter"],
    "PARTIAL_STATE_UPDATE": ["partial", "incomplete", "update", "all fields"],
    "SILENT_DEFAULT": ["default", "silent", "None", "fallback", "missing"],
    "STALE_CACHE": ["stale", "cache", "invalidat", "fresh", "ttl"],
    "TEMPORAL_DRIFT": ["timing", "order", "drift", "before", "after"],
    "USE_BEFORE_SET": ["uninitial", "before set", "None", "not yet", "undefined"],
    "WRONG_CONDITION": ["condition", "wrong", "inverted", "negat", "opposite"],
}


def _detected_correct_reasoning(case: dict, output: str) -> bool:
    """DEPRECATED: heuristic keyword matching for reasoning detection.

    Retained ONLY for backward compatibility with retry_harness heuristic_signal.
    This is NOT used for any classification decision in evaluate_output.
    The LLM classifier (llm_classify) is the sole source of truth.
    """
    signals = _REASONING_SIGNALS.get(case.get("failure_mode", ""), [])
    return len(_has(output, signals)) >= 1


# ============================================================
# EVIDENCE USAGE SCORING (SCM experiment)
# ============================================================

def compute_evidence_metrics(case: dict, output: str) -> dict:
    """Compute evidence_usage_score, incorrect/uncertain/hallucinated counts.

    Returns None values for non-SCM cases. NEVER returns 0 as a substitute
    for "not applicable" — that corrupts averages.
    """
    from scm_data import get_scm
    scm = get_scm(case.get("id", ""))
    if not scm:
        return {
            "has_scm": False,
            "evidence_usage_score": None,
            "incorrect_evidence_usage_count": None,
            "uncertain_evidence_usage_count": None,
            "hallucinated_evidence_count": None,
            "evidence_action_gap": None,
            "delta_gap": None,
        }

    valid_ids = set()
    id_definitions = {}
    for prefix, section in [("F", "functions"), ("V", "variables"),
                            ("E", "edges"), ("I", "invariants")]:
        for k, v in scm.get(section, {}).items():
            valid_ids.add(k)
            id_definitions[k] = v if isinstance(v, str) else str(v)
    for k in scm.get("constraints", {}):
        valid_ids.add(k)
        id_definitions[k] = scm["constraints"][k].get("text", "")

    found_ids = set(re.findall(r'\b([FVEIC]\d+)\b', output))
    valid_found = found_ids & valid_ids
    hallucinated = found_ids - valid_ids

    if not valid_found:
        return {
            "has_scm": True,
            "evidence_usage_score": 0,
            "incorrect_evidence_usage_count": 0,
            "uncertain_evidence_usage_count": 0,
            "hallucinated_evidence_count": len(hallucinated),
            "evidence_action_gap": False,
            "delta_gap": 0,
        }

    incorrect = 0
    uncertain = 0
    for vid in valid_found:
        classification = _classify_id_usage(vid, id_definitions.get(vid, ""), output)
        if classification == "incorrect":
            incorrect += 1
        elif classification == "uncertain":
            uncertain += 1

    score = 1 if len(valid_found) >= 3 else 0

    if score >= 1:
        for vid in valid_found:
            defn = id_definitions.get(vid, "")
            code_terms = re.findall(r'[a-z_]+\(\)', defn) + re.findall(r"[a-z_]+\[", defn)
            for term in code_terms[:3]:
                clean = term.rstrip("()[")
                if clean and len(clean) > 2:
                    for m in re.finditer(re.escape(vid), output):
                        window = output[max(0, m.start()-50):m.end()+50]
                        if clean in window.lower():
                            score = 2
                            break
                if score == 2:
                    break
            if score == 2:
                break

    if score >= 2 and incorrect == 0:
        c_ids = {v for v in valid_found if v.startswith("C")}
        e_ids = {v for v in valid_found if v.startswith("E")}
        f_ids = {v for v in valid_found if v.startswith("F")}
        i_ids = {v for v in valid_found if v.startswith("I")}
        if c_ids and e_ids and f_ids and i_ids:
            paragraphs = output.split("\n\n")
            for para in paragraphs:
                has_c = any(c in para for c in c_ids)
                has_e = any(e in para for e in e_ids)
                has_f = any(f in para for f in f_ids)
                has_i = any(i in para for i in i_ids)
                if has_c and has_e and has_f and has_i:
                    score = 3
                    break

    return {
        "has_scm": True,
        "evidence_usage_score": score,
        "incorrect_evidence_usage_count": incorrect,
        "uncertain_evidence_usage_count": uncertain,
        "hallucinated_evidence_count": len(hallucinated),
        "evidence_action_gap": False,
        "delta_gap": 0,
    }


def _classify_id_usage(vid: str, definition: str, output: str) -> str:
    """Classify a single SCM ID usage as correct/incorrect/uncertain."""
    defn_lower = definition.lower()
    for m in re.finditer(r'\b' + re.escape(vid) + r'\b', output):
        start = max(0, m.start() - 120)
        end = min(len(output), m.end() + 120)
        window = output[start:end].lower()
        has_claim = any(w in window for w in [
            "writes", "reads", "sets", "returns", "calls", "checks",
            "overwrites", "always", "never", "must", "not",
        ])
        if not has_claim:
            return "uncertain"
        if "cache_put_if_absent" in defn_lower or "not overwrite" in defn_lower:
            if "always overwrite" in window or "always sets" in window:
                return "incorrect"
        if "cache_put" in defn_lower and "cache_put_if_absent" not in defn_lower:
            if "does not overwrite" in window or "skip" in window:
                return "incorrect"
        if "frozen" in defn_lower and "true" in defn_lower:
            if "false" in window and "frozen" in window and "sets" in window:
                return "incorrect"
        return "correct"
    return "uncertain"


# ============================================================
# MAIN DISPATCH
# ============================================================

def evaluate_output(case: dict, parsed: dict, eval_model: str | None = None) -> dict:
    """Evaluate model output from a canonical ParsedResponse.

    parsed MUST contain: code, reasoning, raw_output, parse_error, _raw_fallback.
    This function does NOT parse raw output. Parsing happens once at the boundary.

    Pipeline:
      1. exec_evaluate(case, parsed["code"]) → behavioral pass/fail
      2. llm_classify(... parsed["code"], parsed["reasoning"]) → classification
      3. Derive categories: true_success, leg, lucky_fix, true_failure
      4. Evidence metrics on parsed["raw_output"] (SCM cases only)
      5. Propagate parse_error and _raw_fallback into result
    """
    code = parsed["code"]
    reasoning = parsed["reasoning"]
    raw_output = parsed["raw_output"]

    # All-UNCHANGED is a legal reconstruction outcome: SUCCESS + empty code.
    # The model believes original code is correct. exec_evaluate will handle it
    # (empty code → "no extractable code" → pass=False).
    if parsed.get("_reconstruction_status") == "SUCCESS" and (not code or not code.strip()):
        _log.info(
            "RECONSTRUCTION SUCCESS with empty code for case %s — "
            "model marked all files UNCHANGED.",
            case.get("id", "?"),
        )

    # Step 1: execution-based behavioral test — SOLE authority for code correctness
    result = exec_evaluate(case, code)
    exec_pass = result["pass"]

    # Step 2: LLM reasoning classifier — ONLY judges reasoning, NOT code
    # Pass parse_error and _raw_fallback for the parse gate (Fix D)
    classify = llm_classify(
        case, code, reasoning, eval_model=eval_model,
        parse_error=parsed.get("parse_error"),
        raw_fallback=parsed.get("_raw_fallback", False),
    )

    # code_correct comes from EXECUTION, never from classifier
    result["code_correct"] = exec_pass
    result["reasoning_correct"] = classify["reasoning_correct"]
    result["failure_type"] = classify["failure_type"]
    result["classify_raw"] = classify["classify_raw"]
    result["classify_parse_error"] = classify["classify_parse_error"]
    result["classifier_prompt"] = classify.get("classifier_prompt")
    result["eval_model_intended"] = eval_model
    result["eval_model_actual"] = classify.get("eval_model_actual")
    result["parse_category"] = classify.get("parse_category")

    # Classifier's code opinion — logged for diagnostics only, NEVER used in metrics
    classifier_code_correct = classify.get("classifier_code_correct")  # None (no longer produced)
    result["classifier_code_correct"] = classifier_code_correct

    # Disagreement detection (for analysis — classifier no longer judges code,
    # so this will always be None in the new system)
    result["classifier_disagreement"] = None
    result["classifier_disagreement_type"] = None

    # Step 3: Derive categories — uses exec_pass for code, classifier for reasoning
    result["alignment"] = compute_alignment(exec_pass, classify["reasoning_correct"])

    # Backward-compat fields
    result["identified_correct_issue"] = classify["reasoning_correct"] or False
    result["final_output_correct"] = exec_pass
    result["reasoning_action_gap"] = (
        (classify["reasoning_correct"] is True) and (not exec_pass)
    )

    # Step 4: Evidence metrics
    ev_metrics = compute_evidence_metrics(case, raw_output)
    result.update(ev_metrics)

    if ev_metrics["evidence_usage_score"] is not None:
        result["evidence_action_gap"] = (
            ev_metrics["evidence_usage_score"] >= 2 and not result["pass"]
        )
        r_gap = 1 if result["reasoning_action_gap"] else 0
        e_gap = 1 if result["evidence_action_gap"] else 0
        result["delta_gap"] = r_gap - e_gap

    # Step 5: Propagate parse metadata
    result["parse_error"] = parsed["parse_error"]
    result["_raw_fallback"] = parsed["_raw_fallback"]

    return result
