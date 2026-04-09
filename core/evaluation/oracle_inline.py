"""Inline oracle evaluation and per-attempt measurement utilities.

Provides:
- _run_oracle_evaluation(): inline oracle with no-leakage contract
- _compute_per_attempt_disagreement(): classifier-oracle disagreement
- _make_sampling_skip(): sampling skip result factory
- select_best_attempt(): best attempt selection for retry chains
- parse_sampling_strategy(): config string parser
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path

_log = logging.getLogger("t3.oracle_inline")

_SCHEMA_VERSION = "v3.1"
_ORACLE_VERSION = "inline_v1"

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# Cache the template hash (computed once per process)
_TEMPLATE_HASH: str | None = None


def _get_template_hash(template_name: str = "oracle_reasoning_truth") -> str:
    global _TEMPLATE_HASH
    if _TEMPLATE_HASH is None:
        tmpl_path = Path(__file__).parent.parent.parent / "core" / "prompts" / "components" / f"{template_name}.j2"
        if not tmpl_path.exists():
            # Try from project root
            tmpl_path = Path("core/prompts/components") / f"{template_name}.j2"
        if tmpl_path.exists():
            _TEMPLATE_HASH = hashlib.sha256(
                tmpl_path.read_text().encode()
            ).hexdigest()[:16]
        else:
            _TEMPLATE_HASH = "template_not_found"
    return _TEMPLATE_HASH


def _oracle_base(config) -> dict:
    """Build the common oracle result fields from config."""
    return {
        "version": _ORACLE_VERSION,
        "prompt_template_hash": _get_template_hash(),
        "partial_mode": config.oracle.partial_mode,
        "sampling_strategy": config.oracle.sampling_strategy,
        "sampling_reason": None,
    }


def _derive_oracle_correct(label: str, partial_mode: str) -> bool | None:
    """Derive oracle_correct boolean from label and mode."""
    if label in ("UNASSESSED", "UNJUDGABLE"):
        return None
    if partial_mode == "strict":
        return label == "CORRECT"
    return label in ("CORRECT", "PARTIAL")


def run_oracle_evaluation(
    raw_root_cause: str,
    raw_fix_strategy: str,
    case: dict,
    config,
    logger=None,
    case_id: str = "",
    condition: str = "",
    parent_event_id=None,
) -> dict:
    """Run oracle reasoning evaluation inline.

    NO LEAKAGE CONTRACT: This function must NEVER receive or access:
    - execution results (exec_result, passed, score)
    - classifier results (reasoning_internal_consistency, etc.)
    - reconstructed/generated code
    - AST evaluation results
    - normalized reasoning text
    It evaluates ONLY the model's RAW stated reasoning against ground truth.
    Logger is passed for call recording only — not for data access.
    """
    from core.evaluation.oracle_eval.reasoning_truth import (
        build_oracle_spec, load_buggy_code, render_prompt,
        parse_response, is_unjudgable,
    )
    from core.pipeline.llm import call_model

    base = _oracle_base(config)

    if not config.oracle.inline_enabled:
        return {**base, "status": "DISABLED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "", "error": None,
                "latency_ms": 0, "prompt_instance_hash": None}

    # Distinguish missing inputs from short reasoning
    rc_missing = raw_root_cause is None
    fs_missing = raw_fix_strategy is None
    if rc_missing and fs_missing:
        return {**base, "status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "",
                "error": "missing_root_cause_and_fix_strategy", "latency_ms": 0,
                "prompt_instance_hash": None}
    if rc_missing:
        return {**base, "status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "",
                "error": "missing_root_cause", "latency_ms": 0,
                "prompt_instance_hash": None}
    if fs_missing:
        return {**base, "status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "",
                "error": "missing_fix_strategy", "latency_ms": 0,
                "prompt_instance_hash": None}
    if is_unjudgable(raw_root_cause, raw_fix_strategy):
        return {**base, "status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "",
                "error": "reasoning_too_short", "latency_ms": 0,
                "prompt_instance_hash": None}

    oracle_spec = build_oracle_spec(case)
    buggy_code = load_buggy_code(case, _PROJECT_ROOT)
    template_name = getattr(config.oracle, "prompt_template", "oracle_reasoning_truth")
    # Strip .j2 suffix if present — compiler adds it
    if template_name.endswith(".j2"):
        template_name = template_name[:-3]
    prompt = render_prompt(oracle_spec, raw_root_cause, raw_fix_strategy,
                           buggy_code, template_name=template_name)
    instance_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]

    t0 = time.monotonic()
    try:
        cr = call_model(
            prompt,
            model=config.oracle.model,
            raw=True,
            logger=logger,
            case_id=case_id,
            phase="oracle_eval",
            condition=condition,
            parent_event_id=parent_event_id,
        )
        raw_resp = cr.response
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {**base, "status": "FAILURE", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "",
                "error": str(e)[:200], "latency_ms": elapsed,
                "prompt_instance_hash": instance_hash}

    elapsed = int((time.monotonic() - t0) * 1000)
    label, justification, err = parse_response(raw_resp)

    if err is not None:
        return {**base, "status": "PARSE_ERROR", "reasoning_truth": label,
                "oracle_correct": None, "justification": justification,
                "error": err, "latency_ms": elapsed,
                "prompt_instance_hash": instance_hash}

    oracle_correct = _derive_oracle_correct(label, config.oracle.partial_mode)
    return {**base, "status": "SUCCESS", "reasoning_truth": label,
            "oracle_correct": oracle_correct, "justification": justification,
            "error": None, "latency_ms": elapsed,
            "prompt_instance_hash": instance_hash}


def make_sampling_skip(config, reason: str) -> dict:
    """Create an oracle result for a sampling-skipped attempt."""
    base = _oracle_base(config)
    return {**base, "status": "SAMPLING_SKIP", "reasoning_truth": "UNASSESSED",
            "oracle_correct": None, "justification": "", "error": None,
            "latency_ms": 0, "prompt_instance_hash": None,
            "sampling_reason": reason}


def compute_disagreement(classifier_result, oracle_result: dict, config) -> dict:
    """Compute relationship between classifier consistency and oracle correctness.

    classifier_result:
        - v3 schema: reasoning_internal_consistency
        - v2 schema: reasoning_internal_consistency (legacy: reasoning_internal_consistency)

    oracle_result:
        - oracle_correct: bool (ground truth correctness)

    This function no longer treats classifier output as correctness.
    Instead, it tracks a 2x2 grid:
        - coherent_correct
        - coherent_incorrect
        - incoherent_correct
        - incoherent_incorrect
    """

    # --- Extract classifier signal (CONSISTENCY, not correctness) ---
    if isinstance(classifier_result, dict):
        mech = classifier_result.get("reasoning_internal_consistency")

        # fallback for legacy v2
        if mech is None:
            mech = classifier_result.get("reasoning_internal_consistency")

        cls_ran = classifier_result.get("classifier_ran", mech is not None)

    else:
        mech = getattr(classifier_result, "reasoning_internal_consistency", None)

        if mech is None:
            mech = getattr(classifier_result, "reasoning_internal_consistency", None)

        # safer check than previous version
        parse_error = getattr(classifier_result, "parse_error", None)
        cls_ran = (parse_error is None) and (mech is not None)

    # --- Extract oracle signal (TRUE correctness) ---
    oracle_correct = oracle_result.get("oracle_correct")

    # --- Handle missing classifier ---
    if not cls_ran or mech is None:
        return {
            "type": "classifier_not_available",
            "classifier_consistent": None,
            "oracle_correct": oracle_correct,
            "disagreement": None,
        }

    # --- Classifier consistency ---
    cls_consistent = (mech == "CORRECT")

    # --- Handle missing oracle ---
    if oracle_correct is None:
        return {
            "type": "oracle_not_available",
            "classifier_consistent": cls_consistent,
            "oracle_correct": None,
            "disagreement": None,
        }

    # --- 2x2 classification ---
    if cls_consistent and oracle_correct:
        dtype = "coherent_correct"
    elif cls_consistent and not oracle_correct:
        dtype = "coherent_incorrect"
    elif not cls_consistent and oracle_correct:
        dtype = "incoherent_correct"
    else:
        dtype = "incoherent_incorrect"

    # --- Disagreement = axes differ ---
    disagreement = (cls_consistent != oracle_correct)

    return {
        "type": dtype,
        "classifier_consistent": cls_consistent,
        "oracle_correct": oracle_correct,
        "disagreement": disagreement,
    }


def select_best_attempt(trajectory: list[dict]) -> int:
    """Select the best attempt index.

    Returns the index of the FIRST passing attempt.
    If no attempt passes, returns the index of the LAST attempt.
    """
    for i, entry in enumerate(trajectory):
        ex = entry.get("execution", {})
        if ex.get("pass", False):
            return i
    return max(0, len(trajectory) - 1)


def parse_sampling_strategy(strategy_str: str) -> tuple[str, dict]:
    """Parse sampling strategy config string.

    Returns (mode, params) tuple.
    """
    s = strategy_str.strip().upper()
    if s == "ALWAYS":
        return ("ALWAYS", {})
    if s == "FINAL_ONLY":
        raise ValueError(
            "FINAL_ONLY sampling is not supported. "
            "Use ALWAYS, FIRST_K(n), or RANDOM_SAMPLE(p)."
        )
    if s.startswith("FIRST_K(") and s.endswith(")"):
        n = int(s[8:-1])
        return ("FIRST_K", {"n": n})
    if s.startswith("RANDOM_SAMPLE(") and s.endswith(")"):
        p = float(s[14:-1])
        if not (0 < p <= 1):
            raise ValueError(f"RANDOM_SAMPLE probability must be in (0, 1], got {p}")
        return ("RANDOM_SAMPLE", {"p": p})
    raise ValueError(f"Unknown oracle sampling strategy: {strategy_str}")


def should_run_oracle(mode: str, params: dict, attempt_k: int) -> bool:
    """Decide whether oracle should run for this attempt given strategy."""
    if mode == "ALWAYS":
        return True
    if mode == "FINAL_ONLY":
        raise ValueError("FINAL_ONLY is not supported")
    if mode == "FIRST_K":
        return attempt_k < params["n"]
    if mode == "RANDOM_SAMPLE":
        return random.random() < params["p"]
    return True
