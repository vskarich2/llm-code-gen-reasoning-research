"""V2 retry harness — multi-attempt execution with v2 parsing and evaluation.

Retry modes (determined by condition name):
  retry_no_contract_v2              — test feedback only
  retry_adaptive_v2                 — test feedback + mismatch critique
  retry_leg_critique_v2             — mismatch critique only (moderate, legacy)
  retry_leg_critique_strict_v2      — mismatch critique (strict: minimal specificity)
  retry_leg_critique_moderate_v2    — mismatch critique (moderate: balanced)
  retry_leg_critique_aggressive_v2  — mismatch critique (aggressive: max specificity)
  retry_bare_retry_v2               — pure control (previous response + same prompt)
"""

import logging
import re
import time

from core.pipeline.prompting.compiler import compile as _prompt_compile
from core.pipeline.prompting.contracts import PromptProgram
from core.pipeline.prompting.sections import Section
from core.pipeline.prompting.validator import CompilerMode
from core.evaluation.evaluator_v2 import (
    classify_case, assemble_v2_result, ClassifierResultV2,
    _extract_canonical_dims,
)
from core.config.experiment_config import get_config
from core.pipeline.llm import call_model
from core.evaluation.metrics_v2 import derive_v2_signals
from core.pipeline.parsing.parser_v2 import parse_v2_execution, parse_v2_format, parse_v2_recovery
from core.pipeline import _format_code_files
from core.evaluation.reasoning_v2 import normalize_generation_v2
from core.pipeline.reconstructor import reconstruct_strict

_log = logging.getLogger("t3.retry_v2")

_compiler_registry = None


def _get_compiler_registry():
    """Lazy-load the prompt compiler registry."""
    global _compiler_registry
    if _compiler_registry is None:
        from core.pipeline.prompting.registry import PromptRegistry
        from core.config.paths import COMPONENTS_DIR, COMPONENT_META, PROMPT_MANIFEST
        from core.config.experiment_config import get_config
        _compiler_registry = PromptRegistry()
        _compiler_registry.load(
            components_dir=COMPONENTS_DIR,
            metadata_path=COMPONENT_META,
            manifest_path=PROMPT_MANIFEST,
            validate=get_config().execution.validate_prompts,
        )
    return _compiler_registry


def _compile_prompt(components: tuple[str, ...], variables: dict[str, str]) -> str:
    """Compile a prompt via the new compiler. Returns final prompt string."""
    program = PromptProgram(
        name="retry_v2",
        condition="retry_v2",
        components=components,
        required_sections=(),
        allowed_sections=tuple(Section),
        section_order=(),
        strict=False,
    )
    result = _prompt_compile(
        program, variables, CompilerMode.MIGRATION, _get_compiler_registry()
    )
    return result.final_prompt


# ============================================================
# MISMATCH CRITIQUE PROMPTS (three specificity levels)
# ============================================================

_CRITIQUE_PROMPTS = {
    "strict": """You are auditing consistency between a developer's stated reasoning and their generated code.

You are given:

ROOT CAUSE:
{root_cause}

FIX STRATEGY:
{fix_strategy}

CODE:
{code}

Task:
Write exactly ONE sentence describing the most specific mismatch between the developer's stated reasoning and their code.

Strict CLAUDE_RULES:
- Describe a mismatch, NOT a fix
- Do NOT suggest edits or provide code
- Do NOT mention tests, execution, or correctness
- Do NOT introduce any information not explicitly stated in the reasoning or directly visible in the code
- Do NOT name specific functions, variables, files, or lines unless they are already explicitly mentioned in the root_cause or fix_strategy
- Prefer behavioral language over implementation-detail language
- If there is no clear mismatch, output exactly: NO_MISMATCH

Output:
One sentence only.""",

    "moderate": """You are auditing consistency between a developer's stated reasoning and their generated code.

You are given:

ROOT CAUSE:
{root_cause}

FIX STRATEGY:
{fix_strategy}

CODE:
{code}

Task:
Write exactly ONE sentence describing the most specific mismatch between the developer's stated reasoning and their code.

Rules:
- Describe a mismatch, NOT a fix
- Do NOT suggest edits or provide code
- Do NOT mention tests, execution, or correctness
- Do NOT introduce any information not already implied by the reasoning and code
- You MAY mention the specific behavior, action, or omitted step that is inconsistent
- You MAY mention code entities only if needed to identify the mismatch clearly
- If there is no clear mismatch, output exactly: NO_MISMATCH

Output:
One sentence only.""",

    "aggressive": """You are auditing consistency between a developer's stated reasoning and their generated code.

You are given:

ROOT CAUSE:
{root_cause}

FIX STRATEGY:
{fix_strategy}

CODE:
{code}

Task:
Write exactly ONE sentence describing the most specific mismatch between the developer's stated reasoning and their code.

Rules:
- Describe a mismatch, NOT a fix
- Do NOT provide code
- Do NOT mention tests, execution, or correctness
- Use only information available from the reasoning and code
- You MAY name specific functions, variables, or omitted actions if they are directly supported by the reasoning and code
- Do NOT say what to change; only say what is inconsistent or missing
- If there is no clear mismatch, output exactly: NO_MISMATCH

Output:
One sentence only.""",

    "reasoning_only": """You are auditing a developer's stated reasoning about a software bug.

You are given ONLY the developer's reasoning. You do NOT see their code.

ROOT CAUSE:
{root_cause}

FIX STRATEGY:
{fix_strategy}

Task:
Write exactly ONE sentence identifying the weakest, most unsupported, or most internally inconsistent claim in the developer's reasoning.

Strict CLAUDE_RULES:
- Do NOT mention code, functions, variables, files, or implementation details
- Do NOT suggest fixes or edits
- Do NOT reference any code the developer may have produced
- Only identify reasoning weaknesses: vagueness, internal contradictions, unsupported causal claims, or missing logical steps
- If the reasoning is fully coherent and specific, output exactly: NO_WEAKNESS

Output:
One sentence only.""",
}

_PRESCRIPTIVE_WORDS = frozenset({
    "should", "must", "need to", "add", "change", "replace", "update", "fix",
})


# ============================================================
# CRITIQUE HELPERS
# ============================================================


def _resolve_critique_variant(condition: str) -> str | None:
    """Map condition name to critique variant. Returns None if not a critique mode."""
    if "reasoning_only" in condition:
        return "reasoning_only"
    if "critique_strict" in condition:
        return "strict"
    if "critique_moderate" in condition:
        return "moderate"
    if "critique_aggressive" in condition:
        return "aggressive"
    if "leg_critique" in condition and "strict" not in condition and "moderate" not in condition and "aggressive" not in condition:
        return "moderate"  # legacy retry_leg_critique_v2 uses moderate
    return None


def _truncate_to_one_sentence(text: str) -> tuple[str, bool]:
    """Keep only the first sentence. Returns (text, was_truncated)."""
    # Split on sentence boundaries
    match = re.match(r'^(.+?[.!?])\s', text)
    if match:
        return match.group(1).strip(), True
    return text.strip(), False


def _check_prescriptive(text: str) -> bool:
    """Check if critique contains prescriptive language."""
    lower = text.lower()
    return any(w in lower for w in _PRESCRIPTIVE_WORDS)


def _generate_critique(
    variant: str, root_cause: str, fix_strategy: str, code: str,
    config, logger, cid: str, condition: str, parent_eid: int,
    code_commitments: str = "",
) -> tuple[dict, int]:
    """Generate a one-sentence mismatch critique.

    Returns (critique_info_dict, new_parent_eid).
    critique_info_dict contains: critique, no_mismatch, truncated, prescriptive, variant.
    """
    info = {
        "critique": "",
        "variant": variant,
        "no_mismatch": False,
        "truncated": False,
        "prescriptive": False,
        "skipped_missing_fields": False,
    }

    # reasoning_only variant does not need code
    if variant == "reasoning_only":
        if not root_cause or not fix_strategy:
            info["skipped_missing_fields"] = True
            return info, parent_eid
    elif not root_cause or not fix_strategy or not code:
        info["skipped_missing_fields"] = True
        return info, parent_eid

    # Map variant to .j2 component — use v3 templates when commitments available
    is_v3 = bool(code_commitments)
    variant_to_component = {
        "strict": "critique_strict_v3" if is_v3 else "critique_strict",
        "moderate": "critique_moderate",
        "aggressive": "critique_aggressive",
        "reasoning_only": "critique_reasoning_only_v3" if is_v3 else "critique_reasoning_only",
    }
    comp_name = variant_to_component.get(variant)
    if not comp_name:
        info["skipped_missing_fields"] = True
        return info, parent_eid

    crit_vars = {"root_cause": root_cause, "fix_strategy": fix_strategy}
    if code_commitments:
        crit_vars["code_commitments"] = code_commitments
    if variant != "reasoning_only":
        crit_vars["code"] = code
    prompt = _compile_prompt((comp_name,), crit_vars)

    try:
        crit_result = call_model(
            prompt,
            model=config.models.evaluator.name,
            raw=True,
            logger=logger, case_id=cid, phase="classification",
            condition=condition,
            parent_event_id=parent_eid,
        )
        raw = crit_result.response
        assert crit_result.event_id is not None, "call_model must return event_id in execution path"
        new_eid = crit_result.event_id
    except Exception as e:
        _log.debug("Critique failed for %s: %s", cid, e)
        return info, parent_eid

    text = raw.strip()

    if not text or "NO_MISMATCH" in text or "NO MISMATCH" in text or "NO_WEAKNESS" in text or "NO WEAKNESS" in text:
        info["no_mismatch"] = True
        return info, new_eid

    # Truncate to one sentence if needed
    text, was_truncated = _truncate_to_one_sentence(text)
    info["truncated"] = was_truncated
    info["prescriptive"] = _check_prescriptive(text)
    info["critique"] = text

    return info, new_eid


def _build_critique_retry_prompt(
    prev_raw: str, mismatch_critique: str, schema_line: str,
) -> str:
    """Build retry prompt with or without critique via compiler."""
    return _compile_prompt(("critique_retry",), {
        "prev_raw": prev_raw,
        "mismatch_critique": mismatch_critique,
        "schema_line": schema_line,
    })


# ============================================================
# MAIN RETRY FUNCTION
# ============================================================


def _build_retry_prompt_for_attempt(
    k, use_bare_retry, critique_variant, critique_info,
    use_test_feedback, use_classifier_hint, test_feedback,
    classifier_hint, prev_raw, task, code_block,
    file_keys_example, schema_line, prev_code,
):
    """Build the prompt for attempt k."""
    if k == 0:
        return _compile_prompt(("task_and_code", "output_instruction_v4"), {
            "task": task, "code_files_block": code_block,
            "file_keys_example": file_keys_example, "schema_line": schema_line,
        })
    if use_bare_retry:
        base = _compile_prompt(("task_and_code", "output_instruction_v4"), {
            "task": task, "code_files_block": code_block,
            "file_keys_example": file_keys_example, "schema_line": schema_line,
        })
        return f"Your previous response:\n{prev_raw}\n\n" + base
    if critique_variant and critique_info.get("critique"):
        return _build_critique_retry_prompt(prev_raw, critique_info["critique"], schema_line)
    if critique_variant:
        return _build_critique_retry_prompt(prev_raw, "", schema_line)
    if use_test_feedback:
        return _compile_prompt(("test_feedback_retry",), {
            "task": task, "code_files_block": code_block,
            "prev_code": prev_code, "test_feedback": test_feedback,
            "schema_line": schema_line,
            "classifier_hint": classifier_hint if use_classifier_hint else "",
        })
    return _build_critique_retry_prompt(prev_raw, "", schema_line)


def _classify_outcome(R_bool, T_bool, execution_pass, routing_valid,
                      reconstruction_success, oracle_label, classifier_ran):
    """Derive outcome_class and LEG_subtype from axis booleans."""
    if not routing_valid or not reconstruction_success:
        outcome = "serialization_failure"
    elif oracle_label is None:
        outcome = "oracle_not_available"
    elif not classifier_ran:
        outcome = "classifier_not_run"
    elif R_bool is True and execution_pass is True:
        outcome = "interpretable_success"
    elif R_bool is False and execution_pass is True:
        outcome = "lucky_fix"
    elif R_bool is True and execution_pass is False:
        outcome = "LEG"
    elif R_bool is False and execution_pass is False:
        if T_bool is True:
            outcome = "coherent_incorrect"
        elif T_bool is False:
            outcome = "incoherent_incorrect"
        else:
            outcome = "reasoning_failure_unknown"
    else:
        outcome = "unclassified"

    leg_subtype = None
    if outcome == "LEG":
        if T_bool is True:
            leg_subtype = "execution_failure"
        elif T_bool is False:
            leg_subtype = "translation_failure"
        else:
            leg_subtype = "unknown"
    return outcome, leg_subtype


def _compute_quadrants(R_bool, T_bool, execution_pass):
    """Derive R×T and R×E quadrant labels."""
    quadrant_RT = None
    if isinstance(R_bool, bool) and isinstance(T_bool, bool):
        quadrant_RT = f"R{int(R_bool)}_T{int(T_bool)}"
    quadrant_RE = None
    if isinstance(R_bool, bool):
        quadrant_RE = f"R{int(R_bool)}_E{int(execution_pass)}"
    return quadrant_RT, quadrant_RE


def _compute_evaluation_from_trajectory(best, classifier_result):
    """Build evaluation dict from a trajectory entry's signals.

    Mirrors _compute_evaluation() in execution_v2.py but works from
    already-computed per-attempt data stored in the trajectory.
    """
    best_exec = best.get("execution", {})
    best_oracle = best.get("oracle", {})
    best_cls = best.get("classifier", {})

    execution_pass = best_exec.get("pass", False)
    execution_category = best_exec.get("execution_category", "UNKNOWN")
    routing_valid = best.get("parse_valid", False)
    reconstruction_success = routing_valid and best.get("code_length", 0) > 0

    s_fail_type = None
    if not routing_valid:
        s_fail_type = "parser_failure"
    elif not reconstruction_success:
        s_fail_type = "reconstruction_failure"

    if not routing_valid:
        s_outcome = "routing_failure"
    elif execution_pass and reconstruction_success:
        s_outcome = "clean_success"
    elif execution_pass and not reconstruction_success:
        s_outcome = "lucky_success_serialization_failure"
    elif not execution_pass and reconstruction_success:
        s_outcome = "valid_output_wrong_code"
    else:
        s_outcome = "total_failure"

    oracle_label = best_oracle.get("reasoning_truth")
    R_bool = best_oracle.get("oracle_correct")

    classifier_ran = best_cls.get("classifier_ran", False)
    canonical = _extract_canonical_dims(classifier_result)
    if classifier_ran:
        RIC = canonical.get("reasoning_internal_consistency")
        CCC = canonical.get("commitments_satisfied")
        cls_dims = {"RIC": RIC, "CIC": canonical.get("commitments_extracted"),
                    "CCC": CCC, "RCA": canonical.get("reasoning_code_alignment")}
        T_bool = (RIC == "CORRECT") and (CCC == "CORRECT")
    else:
        cls_dims = {"RIC": None, "CIC": None, "CCC": None, "RCA": None}
        T_bool = None

    outcome, leg_subtype = _classify_outcome(
        R_bool, T_bool, execution_pass, routing_valid,
        reconstruction_success, oracle_label, classifier_ran)
    quadrant_RT, quadrant_RE = _compute_quadrants(R_bool, T_bool, execution_pass)

    return {
        "execution_pass": execution_pass, "reconstruction_success": reconstruction_success,
        "routing_valid": routing_valid, "serialization_success": reconstruction_success,
        "serialization_outcome": s_outcome, "serialization_failure_type": s_fail_type,
        "lucky_success_serialization_failure": execution_pass and not reconstruction_success,
        "execution_success": execution_pass, "execution_category": execution_category,
        "oracle_label": oracle_label, "oracle_correct": R_bool, "reasoning_correct": R_bool,
        "classifier_ran": classifier_ran, "classifier_dims": cls_dims,
        "translation_consistent": T_bool,
        "outcome_class": outcome, "LEG": (outcome == "LEG"), "LEG_subtype": leg_subtype,
        "quadrant_RT": quadrant_RT, "quadrant_RE": quadrant_RE, "artifact_id": "retry_best",
    }


def _trajectory_entry_from_state(state, critique_info, test_feedback,
                                 use_test_feedback, classifier_hint):
    """Build a backward-compatible trajectory entry from AttemptState."""
    _cls_canon = _extract_canonical_dims(state.classifier_result)
    return {
        "attempt": state.attempt_idx, "status": "COMPLETED",
        "execution": {
            "pass": state.passed,
            "score": state.exec_result.get("score", 0),
            "execution_category": state.exec_result.get("execution_category"),
        },
        "oracle": state.oracle_result,
        "classifier": {
            "reasoning_internal_consistency": _cls_canon["reasoning_internal_consistency"],
            "commitments_extracted": _cls_canon["commitments_extracted"],
            "commitments_satisfied": _cls_canon["commitments_satisfied"],
            "reasoning_code_alignment": _cls_canon["reasoning_code_alignment"],
            "reasoning_internal_consistency": state.classifier_result.reasoning_internal_consistency,
            "commitments_internal_consistency": state.classifier_result.commitments_internal_consistency,
            "commitments_code_consistency": state.classifier_result.commitments_code_consistency,
            "classifier_ran": state.classifier_result.parse_error is None,
            "error": state.classifier_result.parse_error,
        },
        "ast": state.ast_result.to_dict() if hasattr(state.ast_result, "to_dict") else state.ast_result,
        "reasoning_disagreement": state.disagreement,
        # Canonical parsing semantics (v4 plan — preserved per attempt)
        "parse_valid": state.parsed_gen.parse_valid if state.parsed_gen else False,
        "parse_mode": state.parse_mode,
        "strict_parse_valid": state.strict_parse_valid,
        "recovery_parse_valid": state.recovery_parse_valid,
        "recovery_used": state.recovery_used,
        "execution_source": state.execution_source,
        "retry_eligible": state.retry_eligible,
        "retry_triggered": state.retry_triggered,
        "recon_status": state.recon.status if state.recon else "MISSING",
        "code_length": len(state.code),
        "retry_mode": state.condition,
        "had_test_feedback": bool(test_feedback) and use_test_feedback,
        "had_classifier_hint": bool(classifier_hint),
        "mismatch_critique": critique_info.get("critique") or None,
        "mismatch_variant": critique_info.get("variant"),
        "depth_hint_level": critique_info.get("depth_hint_level"),
        "spec_oracle": state.spec_oracle_result,
    }


def _make_incomplete_entry(k, error_msg):
    """Build an INCOMPLETE trajectory entry for a crashed attempt."""
    return {
        "attempt": k, "status": "INCOMPLETE_ATTEMPT",
        "execution": {"pass": False, "score": 0.0, "execution_category": "ATTEMPT_INCOMPLETE"},
        "oracle": {"status": "FAILURE", "reasoning_truth": "UNASSESSED", "oracle_correct": None,
                    "error": "attempt_incomplete", "latency_ms": 0, "version": "inline_v1",
                    "partial_mode": "lenient", "sampling_strategy": "ALWAYS",
                    "sampling_reason": None, "prompt_template_hash": None, "prompt_instance_hash": None},
        "classifier": {"reasoning_internal_consistency": None, "commitments_satisfied": None,
                       "reasoning_code_alignment": None, "classifier_ran": False, "error": "attempt_incomplete"},
        "ast": {"status": "not_measurable", "ast_correct": None, "ast_score": None,
                "reason": "attempt_incomplete"},
        "reasoning_disagreement": {"disagreement": None, "type": "attempt_incomplete",
                                   "classifier_consistent": None, "oracle_correct": None},
        "parse_valid": False, "code_length": 0, "error": str(error_msg)[:500],
    }


def run_retry_v2(
    case: dict,
    model: str,
    condition: str,
    logger,
    case_start_eid: int = 0,
) -> tuple[str, str, dict]:
    """Run v2 retry harness with per-attempt 4-axis measurement.

    Pipeline order per attempt (v3.1):
      parse → oracle(raw) → normalize → reconstruct → classifier → AST → execute
    """
    from core.evaluation.oracle_inline import (
        run_oracle_evaluation, compute_disagreement, make_sampling_skip,
        select_best_attempt, parse_sampling_strategy, should_run_oracle,
    )
    from core.evaluation.event_validation import apply_validation
    from core.pipeline.execution.exec_canonical import exec_canonical
    from core.evaluation.ast_eval import check_ast_patterns

    config = get_config()
    cond_retry = config.conditions[condition].retry
    max_iterations = cond_retry.max_attempts
    max_total_seconds = cond_retry.max_total_seconds
    cid = case["id"]
    if "logical_file_keys" not in case:
        raise RuntimeError(
            "case missing 'logical_file_keys'. "
            "load_cases() must be called before retry execution."
        )
    code_files = case["logical_file_keys"]
    task = case["task"]
    file_paths = list(code_files.keys())
    code_block = _format_code_files(code_files)
    file_keys_example = ", ".join(
        f'"{p}": "<complete file contents or UNCHANGED>"' for p in file_paths
    )
    schema_line = (
        '{"root_cause": "<...>", "fix_strategy": "<...>", "files": {'
        + file_keys_example + '}}'
    )

    use_test_feedback = "no_contract" in condition or "adaptive" in condition
    use_classifier_hint = "adaptive" in condition
    use_bare_retry = "bare_retry" in condition
    critique_variant = _resolve_critique_variant(condition)
    sampling_mode, sampling_params = parse_sampling_strategy(config.oracle.sampling_strategy)

    t0 = time.monotonic()
    trajectory = []
    prev_code = ""
    prev_raw = ""
    last_parent_eid = case_start_eid
    test_feedback = ""
    classifier_hint = ""
    critique_info = {"critique": "", "variant": critique_variant}

    from core.pipeline.orchestration.attempt_state import AttemptState
    from core.pipeline.orchestration.stages import (
        stage_parse, stage_oracle, stage_normalize,
        stage_reconstruct, stage_classify, stage_ast,
        stage_execute, stage_spec_oracle, stage_derive_metrics,
    )

    states: list[AttemptState] = []

    for k in range(max_iterations):
        elapsed = time.monotonic() - t0
        if elapsed > max_total_seconds:
            _log.warning("TIMEOUT %s after %.1fs at attempt %d", cid, elapsed, k)
            break

        state = AttemptState(
            case_id=cid, condition=condition, model=model, attempt_idx=k,
            start_time=time.monotonic(),
        )

        try:
            # Stage 1: Generate (retry builds its own prompt)
            state.prompt = _build_retry_prompt_for_attempt(
                k, use_bare_retry, critique_variant, critique_info,
                use_test_feedback, use_classifier_hint, test_feedback,
                classifier_hint, prev_raw, task, code_block, file_keys_example,
                schema_line, prev_code)

            gen_result = call_model(
                state.prompt, model=model, raw=True,
                logger=logger, case_id=cid, phase="generation",
                condition=condition, parent_event_id=last_parent_eid)
            state.raw_response = gen_result.response
            assert gen_result.event_id is not None
            state.gen_event_id = gen_result.event_id
            last_parent_eid = gen_result.event_id

            # Stages 2-9: identical to single-shot
            stage_parse(state, case)

            # Oracle: respect sampling strategy
            if should_run_oracle(sampling_mode, sampling_params, k):
                stage_oracle(state, case, config, logger)
            else:
                state.oracle_result = make_sampling_skip(
                    config, f"attempt {k} not sampled by {config.oracle.sampling_strategy}")

            stage_normalize(state, case)
            stage_reconstruct(state, case, config)
            stage_classify(state, case, config, logger)
            if state.classify_event_id:
                last_parent_eid = state.classify_event_id
            stage_ast(state, case)
            stage_execute(state, case, config, logger)
            stage_spec_oracle(state, case)
            stage_derive_metrics(state, config)

            # Build backward-compat trajectory entry from state
            trajectory.append(_trajectory_entry_from_state(
                state, critique_info, test_feedback, use_test_feedback,
                classifier_hint))

        except Exception as exc:
            _log.error("Attempt %d crashed for %s: %s", k, cid, exc)
            trajectory.append(_make_incomplete_entry(k, exc))
            state.passed = False
            state.code = ""
            state.raw_response = prev_raw
            state.parsed_gen = parse_v2_execution("", "baseline_v2")
            state.exec_result = {"pass": False, "score": 0.0}

        states.append(state)

        # Build hints for next iteration
        test_feedback = ""
        classifier_hint = ""
        critique_info = {"critique": "", "variant": critique_variant}

        if not state.passed and k < max_iterations - 1:
            # ── Retry eligibility gate ──
            if not state.retry_eligible:
                _log.warning(
                    "RETRY_ABORT %s attempt %d: parse_mode=%s — "
                    "not retryable (no executable artifact)",
                    cid, k, state.parse_mode)
                break

            reasons = state.exec_result.get("reasons", [])
            test_feedback = "\n".join(reasons) if reasons else "Tests failed."
            fj_hint = state.parsed_gen.full_json or {} if state.parsed_gen else {}

            if use_classifier_hint and state.parsed_gen and state.parsed_gen.parse_status == "success":
                try:
                    cv = {"root_cause": fj_hint.get("root_cause", ""),
                          "fix_strategy": fj_hint.get("fix_strategy", ""),
                          "code": state.code or "", "task": task}
                    cp = _compile_prompt(("critique_mismatch_v2",), cv)
                    hint_result = call_model(
                        cp, model=config.models.evaluator.name, raw=True,
                        logger=logger, case_id=cid, phase="classification",
                        condition=condition, parent_event_id=last_parent_eid)
                    assert hint_result.event_id is not None
                    last_parent_eid = hint_result.event_id
                    ct = hint_result.response.strip()
                    if ct and "NO MISMATCH" not in ct:
                        classifier_hint = f"\n=== Reasoning-Code Mismatch ===\n{ct}"
                except Exception as e:
                    _log.debug("Classifier hint failed: %s", e)

            if critique_variant:
                raw_commitments = fj_hint.get("code_commitments", [])
                commitments_str = "; ".join(raw_commitments) if isinstance(raw_commitments, list) else str(raw_commitments or "")
                critique_info, last_parent_eid = _generate_critique(
                    critique_variant, fj_hint.get("root_cause", ""),
                    fj_hint.get("fix_strategy", ""), state.code,
                    config, logger, cid, condition, last_parent_eid,
                    code_commitments=commitments_str)

            # Depth hint override: if spec oracle detected wrong-depth fix,
            # replace or augment the critique with a depth-direction hint.
            depth_hint_level = getattr(
                config.evaluation, "depth_hint_level", None
            ) if hasattr(config, "evaluation") else None
            if depth_hint_level and state.spec_oracle_result:
                from core.evaluation.depth_hints import generate_depth_hint
                hint = generate_depth_hint(case, state.spec_oracle_result, depth_hint_level)
                if hint:
                    critique_info["critique"] = hint
                    critique_info["depth_hint_level"] = depth_hint_level

        prev_code = state.code
        prev_raw = state.raw_response

        if state.passed:
            _log.info("retry_v2 %s: PASS at attempt %d", cid, k)
            break

    # Assemble final event from trajectory
    import copy
    best_idx = select_best_attempt(trajectory)
    best = trajectory[best_idx]

    # Reconstruct top-level from best attempt (canonical source = trajectory)
    best_cls = best.get("classifier", {})
    classifier_result = ClassifierResultV2()
    # Populate v3 fields if present, else v2 fields
    if best_cls.get("reasoning_internal_consistency") is not None:
        classifier_result.reasoning_internal_consistency = best_cls.get("reasoning_internal_consistency")
        classifier_result.commitments_internal_consistency = best_cls.get("commitments_internal_consistency")
        classifier_result.commitments_code_consistency = best_cls.get("commitments_code_consistency")
    else:
        classifier_result.reasoning_internal_consistency = best_cls.get("reasoning_internal_consistency")
        classifier_result.commitments_extracted = best_cls.get("commitments_extracted")
        classifier_result.commitments_satisfied = best_cls.get("commitments_satisfied")
    classifier_result.reasoning_code_alignment = best_cls.get("reasoning_code_alignment")
    if not best_cls.get("classifier_ran", False):
        classifier_result.parse_error = best_cls.get("error", "unknown")

    best_exec = best.get("execution", {})
    exec_result = {"pass": best_exec.get("pass", False), "score": best_exec.get("score", 0)}

    signals = derive_v2_signals(
        classifier_dims=_extract_canonical_dims(classifier_result),
        code_correct=best_exec.get("pass", False),
        commitments_source="none",
    )

    ev = assemble_v2_result(
        exec_result=exec_result, artifact=normalize_generation_v2(
            parse_v2_execution("", "baseline_v2"), case, "baseline_v2"),
        classifier=classifier_result, signals=signals,
        case=case, condition=condition, model=model,
    )

    # Canonical source: top-level derived from trajectory[best_idx]
    ev["oracle"] = copy.deepcopy(best.get("oracle", {}))
    ev["classification"] = copy.deepcopy(best.get("classifier", {}))
    ev["ast_eval"] = copy.deepcopy(best.get("ast", {}))
    ev["reasoning_disagreement"] = copy.deepcopy(best.get("reasoning_disagreement", {}))

    # CRITICAL: evaluation section (outcome_class, LEG, quadrants, etc.)
    ev["evaluation"] = _compute_evaluation_from_trajectory(best, classifier_result)

    ev["_schema_version"] = "v3.1"

    # Reconstruction section from final attempt state (v4 plan)
    # Uses states list (AttemptState objects) for full metadata.
    final_state = states[-1] if states else None
    if final_state and final_state.routing and final_state.recon:
        from core.pipeline.orchestration.execution_v2 import (
            _build_reconstruction_section,
        )
        recon_section = _build_reconstruction_section(
            final_state.routing, final_state.recon, final_state.exec_result)
        recon_section["artifact_id"] = final_state.artifact_id
        # Add canonical parsing semantics
        recon_section["parse_mode"] = final_state.parse_mode
        recon_section["strict_parse_valid"] = final_state.strict_parse_valid
        recon_section["recovery_parse_valid"] = final_state.recovery_parse_valid
        recon_section["recovery_used"] = final_state.recovery_used
        recon_section["retry_eligible"] = final_state.retry_eligible
        recon_section["execution_source"] = final_state.execution_source
        recon_section["retry_triggered"] = final_state.retry_triggered
        ev["reconstruction"] = recon_section

    # Spec oracle (DDC cases only) — from best attempt in trajectory
    best_spec_oracle = best.get("spec_oracle")
    if best_spec_oracle is not None:
        ev["spec_oracle"] = copy.deepcopy(best_spec_oracle)

    ev["num_attempts"] = len(trajectory)
    ev["best_attempt_idx"] = best_idx
    ev["trajectory"] = trajectory
    ev["retry_passed_at"] = next(
        (t["attempt"] for t in trajectory
         if t.get("execution", {}).get("pass", t.get("pass", False))), None)
    ev["retry_mode"] = condition

    apply_validation(ev, trajectory, best_idx, cid)

    elapsed = time.monotonic() - t0
    parsed_compat = {
        "code": "", "reasoning": "",
        "parse_error": None, "_raw_fallback": False,
        "data_lineage": ["raw_output_received", "parser_v2", "retry_v2"],
    }

    end_eid = logger.end_case(
        cid, condition=condition, raw_ev=ev,
        runtime_ms=round(elapsed * 1000),
        parent_event_id=last_parent_eid,
    )
    logger.log_run(
        cid, condition, "", prev_raw, parsed_compat,
        canonical_event_id=end_eid,
    )

    return cid, condition, ev
