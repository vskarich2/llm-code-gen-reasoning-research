"""Pipeline stage functions operating on AttemptState.

Each stage reads from and writes to AttemptState fields.
Called by both run_v2 (single-shot) and run_retry_v2 (retry).
No stage owns the loop or the event assembly — that's the caller's job.
"""

from __future__ import annotations

import logging
import time

from core.pipeline.orchestration.attempt_state import AttemptState

_log = logging.getLogger("t3.stages")


def stage_generate(state: AttemptState, case: dict, config, logger,
                   parent_eid=0) -> None:
    """Stage 1: Render prompt and call generation model."""
    from core.pipeline.orchestration.execution_v2 import (
        _render_generation_prompt, _call_generation_model,
    )
    state.prompt, state.prompt_meta = _render_generation_prompt(
        case, state.condition, config)
    state.raw_response, state.gen_event_id = _call_generation_model(
        state.prompt, state.model, state.case_id, state.condition,
        state.prompt_meta, logger, parent_eid)


def stage_parse(state: AttemptState, case: dict) -> None:
    """Stage 2: Parse raw response, route, assign canonical semantics."""
    from core.pipeline.orchestration.execution_v2 import (
        _parse_outputs, _select_artifact, _validate_structure,
    )
    state.strict_parse, state.recovery_parse, state.format_parse = (
        _parse_outputs(state.raw_response, state.condition))
    state.routing = _select_artifact(
        state.strict_parse, state.recovery_parse, case)
    state.parsed_gen = (
        state.recovery_parse
        if state.routing.selected_source == "recovery"
        else state.strict_parse)

    # ── Canonical parsing semantics (explicit, independent) ──
    # parse_mode is a derived summary; analysis should use both booleans.
    state.strict_parse_valid = (
        state.strict_parse.parse_valid
        and _validate_structure(state.strict_parse, case).structurally_valid
    )
    state.recovery_parse_valid = (
        state.recovery_parse.parse_valid
        and _validate_structure(state.recovery_parse, case).structurally_valid
    )

    if state.strict_parse_valid:
        state.parse_mode = "strict"
    elif state.recovery_parse_valid:
        state.parse_mode = "recovered"
    else:
        state.parse_mode = "failed"

    state.recovery_used = (state.routing.selected_source == "recovery")
    state.execution_source = state.routing.selected_source
    state.retry_eligible = (
        state.strict_parse_valid or state.recovery_parse_valid
    )
    state.retry_triggered = (state.attempt_idx > 0)


def stage_oracle(state: AttemptState, case: dict, config, logger) -> None:
    """Stage 3: Oracle evaluation on raw reasoning fields."""
    from core.evaluation.oracle_inline import run_oracle_evaluation
    fj = state.parsed_gen.full_json or {}
    state.oracle_result = run_oracle_evaluation(
        fj.get("root_cause"), fj.get("fix_strategy"), case, config,
        logger=logger, case_id=state.case_id, condition=state.condition,
        parent_event_id=state.gen_event_id)


def stage_normalize(state: AttemptState, case: dict) -> None:
    """Stage 4: Normalize generation artifact."""
    from core.evaluation.reasoning_v2 import normalize_generation_v2
    state.artifact = normalize_generation_v2(
        state.parsed_gen, case, state.condition)


def stage_reconstruct(state: AttemptState, case: dict, config) -> None:
    """Stage 5: Reconstruct code files from parsed output."""
    from core.pipeline.orchestration.execution_v2 import (
        _reconstruct, _compute_artifact_id,
    )
    state.recon, state.code = _reconstruct(
        state.parsed_gen, case, config)
    state.artifact_id = _compute_artifact_id(state.recon)


def stage_classify(state: AttemptState, case: dict, config,
                   logger) -> None:
    """Stage 6: Run classifier (before execution — blindness)."""
    from core.pipeline.orchestration.execution_v2 import (
        _classify_reasoning,
    )
    state.classifier_result, state.classify_event_id = (
        _classify_reasoning(
            state.artifact, case, state.code, config, logger,
            state.case_id, state.condition, state.parsed_gen,
            state.gen_event_id))


def stage_ast(state: AttemptState, case: dict) -> None:
    """Stage 7: AST structural verification (before execution)."""
    from core.pipeline.orchestration.execution_v2 import (
        _run_ast_verification,
    )
    state.ast_result = _run_ast_verification(
        state.recon, case, state.artifact_id)


def _swebench_exec_result(case: dict) -> dict:
    """Build exec_result from pre-computed SWE-bench Docker results."""
    swe = case.get("_swebench", {})
    resolved = swe.get("resolved_v5", False)
    fail_cat = swe.get("failure_category_v5", "UNKNOWN")

    if resolved:
        category = "EXECUTION_SUCCESS"
    elif fail_cat == "EMPTY_PATCH":
        category = "STRUCTURAL_FAILURE"
    elif fail_cat in ("SYNTAX_ERROR", "IMPORT_ERROR"):
        category = "SYNTAX_FAILURE"
    else:
        category = "INVARIANT_FAILURE"

    return {
        "pass": resolved,
        "score": 1.0 if resolved else 0.0,
        "reasons": [] if resolved else [f"SWE-bench Docker: {fail_cat}"],
        "failure_modes": [] if resolved else [fail_cat],
        "execution": {
            "status": "passed" if resolved else "failed",
            "ran": True,
            "passed_tests": 1 if resolved else 0,
            "total_tests": 1,
            "runtime_error": None,
            "invariant_pass": resolved,
            "mutation_pass": None,
        },
        "execution_category": category,
        "execution_subtype": None if resolved else fail_cat,
        "modules_loaded": [],
        "functions_detected": [],
        "functions_called": [],
        "merge_conflicts": [],
        "execution_trace": [],
        "reconstruction_status": None,
        "semantic_diagnostics": {
            "missing_required_definitions": False,
            "missing_definition_names": [],
        },
        "_extracted_code": "",
        "_assembled_code": "swebench_docker",
    }


def stage_execute(state: AttemptState, case: dict, config,
                  logger) -> None:
    """Stage 8: Execute code against test suite.

    For SWE-bench cases (template == 'swebench_real_world'), injects
    pre-computed Docker evaluation results instead of running subprocess.
    """
    if case.get("template") == "swebench_real_world":
        state.exec_result = _swebench_exec_result(case)
    else:
        from core.pipeline.orchestration.execution_v2 import _execute
        state.exec_result = _execute(
            case, state.parsed_gen, state.recon, config, logger,
            attempt=state.attempt_idx)
    state.passed = state.exec_result.get("pass", False)


def stage_spec_oracle(state: AttemptState, case: dict) -> None:
    """Stage 8b: Spec oracle for DDC cases (after execution)."""
    from core.evaluation.spec_oracle import run_spec_oracle
    state.spec_oracle_result = run_spec_oracle(case, state.exec_result)


def stage_derive_metrics(state: AttemptState, config) -> None:
    """Stage 9: Compute disagreement, signals, evaluation."""
    from core.evaluation.oracle_inline import compute_disagreement
    from core.pipeline.orchestration.execution_v2 import (
        _derive_metrics, _compute_evaluation,
    )
    state.disagreement = compute_disagreement(
        state.classifier_result, state.oracle_result, config)
    state.signals = _derive_metrics(
        state.classifier_result, state.artifact,
        state.exec_result, state.parsed_gen)
    state.evaluation = _compute_evaluation(
        state.routing, state.recon, state.exec_result,
        state.classifier_result, state.oracle_result,
        state.artifact_id)


def run_stages_2_through_9(state: AttemptState, case: dict, config,
                           logger) -> None:
    """Run all stages after generation. Convenience for retry loop."""
    stage_parse(state, case)
    stage_oracle(state, case, config, logger)
    stage_normalize(state, case)
    stage_reconstruct(state, case, config)
    stage_classify(state, case, config, logger)
    stage_ast(state, case)
    stage_execute(state, case, config, logger)
    stage_spec_oracle(state, case)
    stage_derive_metrics(state, config)
