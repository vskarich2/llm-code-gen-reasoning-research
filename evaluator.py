"""T3 Evaluation dispatcher.

Responsibilities:
  1. Route to execution-based evaluation (THE ONLY behavioral test)
  2. LLM-based classification of reasoning quality (multi-dimensional)
  3. Derived categories via compute_category from reasoning.py
  4. Evidence usage scoring (SCM experiment)

TWO sources of truth:
  - exec_evaluate: runs code, tests invariants → behavioral pass/fail
  - llm_classify: LLM judge → 4 reasoning dimensions + confidence + failure_type

There are NO heuristic keyword-matching classifiers. ALL classification
comes from the LLM evaluator and reasoning.py derivation logic.

Schema version: 2 (structured reasoning, multi-dimensional classifier).
"""

import json
import logging
import re

# HARD IMPORT — if this fails, the system cannot produce valid results.
from exec_eval import exec_evaluate

from llm import call_model

from reasoning import (
    parse_classify_output as _parse_classify_dims,
    compute_reasoning_correct,
    compute_category,
    should_run_grounded,
    VALID_FAILURE_TYPES,
    NULL_CLASSIFIER_RESULT,
    REASONING_SCHEMA_VERSION,
)

_log = logging.getLogger("t3.evaluator")


# ============================================================
# LLM CLASSIFIER — multi-dimensional reasoning evaluation
# ============================================================


def _get_eval_model() -> str:
    """Get evaluator model from config. No hardcoded fallback."""
    from experiment_config import get_config

    return get_config().models.evaluator.name


def llm_classify(
    case: dict,
    code: str,
    reasoning_obj: dict,
    reasoning_validation: dict,
    eval_model: str | None = None,
) -> dict:
    """Run the LLM reasoning classifier on an attempt.

    Evaluates ONLY reasoning correctness via 4 dimensions. Does NOT judge code correctness.
    Code correctness comes from execution tests — never from this classifier.

    REASONING GATE: If reasoning_present is False (from validate_reasoning),
    classification is skipped. Returns NULL_CLASSIFIER_RESULT.

    Args:
        case: benchmark case dict (has "task", "failure_mode", "id")
        code: extracted code from the model's response
        reasoning_obj: structured reasoning {root_cause, failure_mechanism, broken_invariant, fix_strategy}
        reasoning_validation: from validate_reasoning() — has reasoning_attempted, reasoning_present
        eval_model: model to use for classifier. If None, uses default.

    Returns dict with:
        mechanism_identified, invariant_identified, fix_alignment, reasoning_code_alignment: YES/PARTIAL/NO or None
        failure_type, failure_type_raw: str or None
        confidence: HIGH/MEDIUM/LOW or None
        explanation: str or None
        classify_parse_error: str or None
        classify_raw: str or None
        classifier_prompt: str or None
        eval_model_actual: str or None
        classifier_mode: str
        reasoning_correct_mode: str
        reasoning_correct: bool or None
    """
    from experiment_config import get_config

    config = get_config()
    classifier_mode = config.evaluation.classifier_mode
    reasoning_correct_mode = config.evaluation.reasoning_correct_mode

    # REASONING GATE: if reasoning is not present, skip classification entirely
    if not reasoning_validation.get("reasoning_present", False):
        return {
            **NULL_CLASSIFIER_RESULT,
            "classify_raw": None,
            "classifier_prompt": None,
            "eval_model_actual": None,
            "classifier_mode": classifier_mode,
            "reasoning_correct_mode": reasoning_correct_mode,
            "reasoning_correct": None,
        }

    # Build classifier prompt with structured reasoning fields.
    # Empty fields are marked "[COULD NOT EXTRACT]" — never sent as blank strings.
    # Blank strings silently mislead the classifier into thinking reasoning is absent.
    eval_cfg = config.models.evaluator

    def _field_or_missing(val):
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict) and val:
            return str(val)
        return "[COULD NOT EXTRACT]"

    _cls_vars = {
        "failure_types": ", ".join(sorted(VALID_FAILURE_TYPES)),
        "task": case.get("task", "")[: eval_cfg.max_task_chars],
        "code": (code or "")[: eval_cfg.max_code_chars],
        "root_cause": _field_or_missing(reasoning_obj.get("root_cause")),
        "failure_mechanism": _field_or_missing(reasoning_obj.get("failure_mechanism")),
        "broken_invariant": _field_or_missing(reasoning_obj.get("broken_invariant")),
        "fix_strategy": _field_or_missing(reasoning_obj.get("fix_strategy")),
        "self_check": _field_or_missing(reasoning_obj.get("self_check")),
        "risk_check": _field_or_missing(reasoning_obj.get("risk_check")),
        "classifier_mode": classifier_mode,
    }

    # Grounded mode: add ground truth if available
    if classifier_mode == "grounded":
        can_ground, reason = should_run_grounded(case, classifier_mode)
        if can_ground:
            _cls_vars["ground_truth_failure_mode"] = case.get("failure_mode", "")
            _cls_vars["ground_truth_trap"] = case.get("trap_description", "")
            _cls_vars["ground_truth_invariant"] = case.get("ground_truth_invariant", "")
        else:
            # Fall back to blind if ground truth is missing
            _cls_vars["classifier_mode"] = "blind"

    from assembly_engine import build as _assembly_build

    _rendered = _assembly_build(["classify_reasoning"], _cls_vars)
    prompt = _rendered.final_prompt

    model = eval_model or _get_eval_model()

    try:
        from call_logger import set_call_context

        set_call_context(
            phase="classifier",
            case_id=case.get("id", "?"),
            condition=case.get("_condition", "?"),
        )
        raw = call_model(prompt, model=model, raw=True)
        dims = _parse_classify_dims(raw)

        # Derive reasoning_correct from classifier dimensions
        reasoning_correct = None
        if dims.get("parse_error") is None:
            schema_matched = reasoning_validation.get("schema_matched", "baseline")
            reasoning_correct = compute_reasoning_correct(dims, reasoning_correct_mode, schema_matched=schema_matched)

        return {
            "mechanism_identified": dims.get("mechanism_identified"),
            "invariant_identified": dims.get("invariant_identified"),
            "causal_chain_complete": dims.get("causal_chain_complete"),
            "fix_alignment": dims.get("fix_alignment"),
            "reasoning_code_alignment": dims.get("reasoning_code_alignment"),
            "failure_type": dims.get("failure_type"),
            "failure_type_raw": dims.get("failure_type_raw"),
            "confidence": dims.get("confidence"),
            "counterfactual": dims.get("counterfactual"),
            "evidence": dims.get("evidence"),
            "judgment": dims.get("judgment"),
            "explanation": dims.get("explanation"),
            "classify_parse_error": dims.get("parse_error"),
            "classify_raw": raw,
            "classifier_prompt": prompt,
            "eval_model_actual": model,
            "classifier_mode": classifier_mode,
            "reasoning_correct_mode": reasoning_correct_mode,
            "reasoning_correct": reasoning_correct,
        }
    except Exception as e:
        _log.error("LLM classifier call failed: %s", e)
        return {
            **NULL_CLASSIFIER_RESULT,
            "classify_raw": None,
            "classify_parse_error": f"exception:{e}",
            "classifier_prompt": prompt,
            "eval_model_actual": model,
            "classifier_mode": classifier_mode,
            "reasoning_correct_mode": reasoning_correct_mode,
            "reasoning_correct": None,
        }


# ============================================================
# MAIN DISPATCH
# ============================================================


def evaluate_output(case: dict, parsed: dict, eval_model: str | None = None) -> dict:
    """Evaluate model output from a canonical ParsedResponse.

    parsed MUST contain: code, raw_output, parse_error, _raw_fallback,
    reasoning_obj, reasoning_validation.

    Pipeline:
      1. exec_evaluate(case, parsed["code"]) → behavioral pass/fail
      2. llm_classify(structured reasoning) → multi-dimensional classification
      3. compute_category → 8 explicit categories
      4. Evidence metrics on parsed["raw_output"] (SCM cases only)
      5. Propagate parse_error and _raw_fallback into result
    """
    code = parsed["code"]
    raw_output = parsed["raw_output"]
    reasoning_obj = parsed.get("reasoning_obj", {})
    reasoning_validation = parsed.get("reasoning_validation", {})

    # All-UNCHANGED is a legal reconstruction outcome: SUCCESS + empty code.
    if parsed.get("_reconstruction_status") == "SUCCESS" and (not code or not code.strip()):
        _log.info(
            "RECONSTRUCTION SUCCESS with empty code for case %s — "
            "model marked all files UNCHANGED.",
            case.get("id", "?"),
        )

    # Step 1: execution-based behavioral test — SOLE authority for code correctness
    result = exec_evaluate(case, code)
    exec_pass = result["pass"]
    result["code_correct"] = exec_pass

    # Step 2: LLM reasoning classifier — structured, multi-dimensional
    classify = llm_classify(
        case, code, reasoning_obj, reasoning_validation, eval_model=eval_model
    )

    # Merge classifier results into ev
    result["reasoning_correct"] = classify.get("reasoning_correct")
    result["mechanism_identified"] = classify.get("mechanism_identified")
    result["invariant_identified"] = classify.get("invariant_identified")
    result["causal_chain_complete"] = classify.get("causal_chain_complete")
    result["fix_alignment"] = classify.get("fix_alignment")
    result["reasoning_code_alignment"] = classify.get("reasoning_code_alignment")
    result["failure_type"] = classify.get("failure_type")
    result["failure_type_raw"] = classify.get("failure_type_raw")
    result["confidence"] = classify.get("confidence")
    result["counterfactual"] = classify.get("counterfactual")
    result["evidence"] = classify.get("evidence")
    result["judgment"] = classify.get("judgment")
    result["explanation"] = classify.get("explanation")
    result["classify_raw"] = classify.get("classify_raw")
    result["classify_parse_error"] = classify.get("classify_parse_error")
    result["classifier_prompt"] = classify.get("classifier_prompt")
    result["eval_model_intended"] = eval_model
    result["eval_model_actual"] = classify.get("eval_model_actual")
    result["classifier_mode"] = classify.get("classifier_mode")
    result["reasoning_correct_mode"] = classify.get("reasoning_correct_mode")

    # Step 3: Category — 8 explicit categories via reasoning.py
    reasoning_present = reasoning_validation.get("reasoning_present", False)
    parse_failed = bool(parsed.get("_raw_fallback", False))

    category = compute_category(
        code_correct=exec_pass,
        reasoning_correct=classify.get("reasoning_correct"),
        reasoning_present=reasoning_present,
        classifier_parse_error=classify.get("classify_parse_error"),
        parse_failed=parse_failed,
    )
    result["category"] = category

    # alignment dict for backward compatibility
    result["alignment"] = {
        "category": category,
        "code_correct": exec_pass,
        "reasoning_correct": classify.get("reasoning_correct"),
    }

    # Reasoning validation metadata
    result["reasoning_attempted"] = reasoning_validation.get("reasoning_attempted", False)
    result["reasoning_present"] = reasoning_present
    result["reasoning_lengths"] = reasoning_validation.get("reasoning_lengths", {})

    # Schema version
    result["reasoning_schema_version"] = REASONING_SCHEMA_VERSION

    # Backward-compat fields
    result["identified_correct_issue"] = classify.get("reasoning_correct") or False
    result["final_output_correct"] = exec_pass
    result["reasoning_action_gap"] = (classify.get("reasoning_correct") is True) and (
        not exec_pass
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


# ============================================================
# BACKWARD COMPATIBILITY — compute_alignment (DEPRECATED)
# ============================================================
# Used by retry_harness.py. Will be removed when retry_harness is updated.


def compute_alignment(code_correct: bool | None, reasoning_correct: bool | None) -> dict:
    """DEPRECATED: use compute_category from reasoning.py directly.

    Kept for backward compatibility with retry_harness.
    """
    if code_correct is None or reasoning_correct is None:
        cat = "unclassified"
    elif reasoning_correct and code_correct:
        cat = "true_success"
    elif reasoning_correct and not code_correct:
        cat = "leg"
    elif not reasoning_correct and code_correct:
        cat = "lucky_fix"
    else:
        cat = "true_failure"
    return {
        "category": cat,
        "code_correct": code_correct,
        "reasoning_correct": reasoning_correct,
        "leg_true": cat == "leg",
        "lucky_fix": cat == "lucky_fix",
        "true_success": cat == "true_success",
        "true_failure": cat == "true_failure",
    }


# ============================================================
# BACKWARD COMPATIBILITY — heuristic reasoning detection (DEPRECATED)
# ============================================================
# Used by retry_harness.py for heuristic_signal logging only.
# NOT used for any classification decision.

from eval_cases import _has, _low  # noqa: F401

_REASONING_SIGNALS = {
    "HIDDEN_DEPENDENCY": [
        "overwrite", "cache_put_if_absent.*different", "not interchangeable",
        "stale", "live.*write", "always.*overwrite", "won't overwrite",
    ],
    "TEMPORAL_ORDERING": ["order", "before", "after", "sequence", "timing", "first"],
    "TEMPORAL_CAUSAL_ERROR": [
        "original data", "raw data", "before transform", "different keys",
        "different semantic", "not.*replacement",
    ],
    "INVARIANT_VIOLATION": [
        "partial failure", "money.*lost", "rollback", "inconsistent",
        "atomicity", "failure window", "debit.*credit",
    ],
    "STATE_SEMANTIC_VIOLATION": [
        "frozen", "get_committed_total", "preview", "stage.*without.*commit",
        "none.*not.*zero", "returns none",
    ],
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
    """DEPRECATED: heuristic keyword matching. Used ONLY by retry_harness."""
    signals = _REASONING_SIGNALS.get(case.get("failure_mode", ""), [])
    return len(_has(output, signals)) >= 1


# DEPRECATED: kept for test_evaluator_fixes.py backward compat
_VALID_BOOLS = frozenset(["YES", "NO"])

_CLASSIFICATION_DISALLOWED = frozenset(
    {"REASONING_LOST", "CODE_LOST", "STRUCTURE_MISSING"}
)


def classify_parse_category(
    reasoning: str, parse_error: str | None, raw_fallback: bool = False
) -> str:
    """DEPRECATED: replaced by reasoning_validation.reasoning_present."""
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
        return "CLEAN"
    return "CLEAN"


# Re-export FAILURE_TYPE_SET for backward compat (used by test_v2_bridge.py)
from failure_classifier import FAILURE_TYPE_SET  # noqa: F401


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
    for prefix, section in [
        ("F", "functions"),
        ("V", "variables"),
        ("E", "edges"),
        ("I", "invariants"),
    ]:
        for k, v in scm.get(section, {}).items():
            valid_ids.add(k)
            id_definitions[k] = v if isinstance(v, str) else str(v)
    for k in scm.get("constraints", {}):
        valid_ids.add(k)
        id_definitions[k] = scm["constraints"][k].get("text", "")

    found_ids = set(re.findall(r"\b([FVEIC]\d+)\b", output))
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
            code_terms = re.findall(r"[a-z_]+\(\)", defn) + re.findall(r"[a-z_]+\[", defn)
            for term in code_terms[:3]:
                clean = term.rstrip("()[")
                if clean and len(clean) > 2:
                    for m in re.finditer(re.escape(vid), output):
                        window = output[max(0, m.start() - 50) : m.end() + 50]
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
    for m in re.finditer(r"\b" + re.escape(vid) + r"\b", output):
        start = max(0, m.start() - 120)
        end = min(len(output), m.end() + 120)
        window = output[start:end].lower()
        has_claim = any(
            w in window
            for w in [
                "writes", "reads", "sets", "returns", "calls", "checks",
                "overwrites", "always", "never", "must", "not",
            ]
        )
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
