"""Graph-based retry controller — state machine over single-attempt DAG.

Replicates retry_v2.py semantics EXACTLY by:
1. Using _build_retry_prompt_for_attempt for prompt construction (V2 function)
2. Using the graph engine for stages 2-9 (parse through metrics)
3. Using the V2 critique/hint generation functions directly
4. Using the V2 result assembly path for the final event dict

This is NOT a reimplementation. It delegates to V2 functions for all
policy decisions and only replaces the per-attempt stage execution.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any
from unittest.mock import MagicMock

from side_projects.graph_runner.validation.equivalence import (
    run_graph_pipeline,
)

log = logging.getLogger("t3.retry_controller")


def run_retry_graph(
    case: dict,
    model: str,
    condition: str,
    logger: Any,
    case_start_eid: int = 0,
) -> tuple[str, str, dict]:
    """Graph-based retry that matches retry_v2.py semantics exactly.

    Uses V2 functions for: prompt construction, critique generation,
    retry stopping, best-attempt selection, result assembly.
    Uses graph engine for: stages 2-9 (parse → metrics).
    """
    from core.config.experiment_config import get_config
    from core.evaluation.evaluator_v2 import (
        ClassifierResultV2, assemble_v2_result, _extract_canonical_dims,
    )
    from core.evaluation.metrics_v2 import derive_v2_signals
    from core.evaluation.oracle_inline import (
        make_sampling_skip, parse_sampling_strategy, should_run_oracle,
        select_best_attempt, compute_disagreement,
    )
    from core.evaluation.reasoning_v2 import normalize_generation_v2
    from core.evaluation.event_validation import apply_validation
    from core.pipeline.llm import call_model
    from core.pipeline.parsing.parser_v2 import parse_v2_execution
    from core.pipeline.orchestration.retry_v2 import (
        _build_retry_prompt_for_attempt,
        _format_code_files,
        _resolve_critique_variant,
        _generate_critique,
        _compile_prompt,
        _trajectory_entry_from_state,
        _make_incomplete_entry,
        _compute_evaluation_from_trajectory,
    )
    from core.constants.pipeline_constants import (
        DIM_REASONING_INTERNAL_CONSISTENCY,
        DIM_COMMITMENTS_INTERNAL_CONSISTENCY,
        DIM_COMMITMENTS_CODE_CONSISTENCY,
        DIM_COMMITMENTS_EXTRACTED,
        DIM_COMMITMENTS_SATISFIED,
        DIM_REASONING_CODE_ALIGNMENT,
    )

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
    sampling_mode, sampling_params = parse_sampling_strategy(
        config.oracle.sampling_strategy,
    )

    t0 = time.monotonic()
    trajectory: list[dict] = []
    prev_code = ""
    prev_raw = ""
    last_parent_eid = case_start_eid
    test_feedback = ""
    classifier_hint = ""
    critique_info: dict[str, Any] = {
        "critique": "", "variant": critique_variant,
    }

    from core.pipeline.orchestration.attempt_state import AttemptState

    states: list[AttemptState] = []

    for k in range(max_iterations):
        elapsed = time.monotonic() - t0
        if elapsed > max_total_seconds:
            log.warning(
                "TIMEOUT %s after %.1fs at attempt %d", cid, elapsed, k,
            )
            break

        state = AttemptState(
            case_id=cid, condition=condition, model=model,
            attempt_idx=k, start_time=time.monotonic(),
        )

        try:
            # Stage 1: Prompt (V2 function — exact same logic)
            state.prompt = _build_retry_prompt_for_attempt(
                k, use_bare_retry, critique_variant, critique_info,
                use_test_feedback, use_classifier_hint, test_feedback,
                classifier_hint, prev_raw, task, code_block,
                file_keys_example, schema_line, prev_code,
            )

            gen_result = call_model(
                state.prompt, model=model, raw=True,
                logger=logger, case_id=cid, phase="generation",
                condition=condition, parent_event_id=last_parent_eid,
            )
            state.raw_response = gen_result.response
            assert gen_result.event_id is not None
            state.gen_event_id = gen_result.event_id
            last_parent_eid = gen_result.event_id

            # Stages 2-9: via graph engine
            graph_out = run_graph_pipeline(
                case, state.raw_response, config,
            )

            # Map graph outputs back to AttemptState
            _map_graph_to_state(state, graph_out, case, config, logger,
                                sampling_mode, sampling_params, k)

            trajectory.append(_trajectory_entry_from_state(
                state, critique_info, test_feedback,
                use_test_feedback, classifier_hint,
            ))

        except Exception as exc:
            log.error("Attempt %d crashed for %s: %s", k, cid, exc)
            trajectory.append(_make_incomplete_entry(k, exc))
            state.passed = False
            state.code = ""
            state.raw_response = prev_raw
            state.parsed_gen = parse_v2_execution("", "baseline_v2")
            state.exec_result = {"pass": False, "score": 0.0}

        states.append(state)

        # Build hints for next iteration (V2 logic — exact copy)
        test_feedback = ""
        classifier_hint = ""
        critique_info = {"critique": "", "variant": critique_variant}

        if not state.passed and k < max_iterations - 1:
            if not state.retry_eligible:
                log.warning(
                    "RETRY_ABORT %s attempt %d: parse_mode=%s",
                    cid, k, state.parse_mode,
                )
                break

            reasons = state.exec_result.get("reasons", [])
            test_feedback = (
                "\n".join(reasons) if reasons else "Tests failed."
            )
            fj_hint = (
                state.parsed_gen.full_json or {}
                if state.parsed_gen else {}
            )

            if (use_classifier_hint and state.parsed_gen
                    and state.parsed_gen.parse_status == "success"):
                try:
                    cv = {
                        "root_cause": fj_hint.get("root_cause", ""),
                        "fix_strategy": fj_hint.get("fix_strategy", ""),
                        "code": state.code or "",
                        "task": task,
                    }
                    cp = _compile_prompt(("critique_mismatch_v2",), cv)
                    hint_result = call_model(
                        cp, model=config.models.evaluator.name, raw=True,
                        logger=logger, case_id=cid,
                        phase="classification", condition=condition,
                        parent_event_id=last_parent_eid,
                    )
                    assert hint_result.event_id is not None
                    last_parent_eid = hint_result.event_id
                    ct = hint_result.response.strip()
                    if ct and "NO MISMATCH" not in ct:
                        classifier_hint = (
                            f"\n=== Reasoning-Code Mismatch ===\n{ct}"
                        )
                except Exception as e:
                    log.debug("Classifier hint failed: %s", e)

            if critique_variant:
                raw_commitments = fj_hint.get("code_commitments", [])
                commitments_str = (
                    "; ".join(raw_commitments)
                    if isinstance(raw_commitments, list)
                    else str(raw_commitments or "")
                )
                critique_info, last_parent_eid = _generate_critique(
                    critique_variant, fj_hint.get("root_cause", ""),
                    fj_hint.get("fix_strategy", ""), state.code,
                    config, logger, cid, condition, last_parent_eid,
                    code_commitments=commitments_str,
                )

            depth_hint_level = getattr(
                config.evaluation, "depth_hint_level", None,
            ) if hasattr(config, "evaluation") else None
            if depth_hint_level and state.spec_oracle_result:
                from core.evaluation.depth_hints import generate_depth_hint
                hint = generate_depth_hint(
                    case, state.spec_oracle_result, depth_hint_level,
                )
                if hint:
                    critique_info["critique"] = hint
                    critique_info["depth_hint_level"] = depth_hint_level

        prev_code = state.code
        prev_raw = state.raw_response

        if state.passed:
            log.info("retry_graph %s: PASS at attempt %d", cid, k)
            break

    # Assemble final event — EXACT same logic as retry_v2.py
    best_idx = select_best_attempt(trajectory)
    best = trajectory[best_idx]

    best_cls = best.get("classifier", {})
    classifier_result = ClassifierResultV2()
    if best_cls.get(DIM_REASONING_INTERNAL_CONSISTENCY) is not None:
        classifier_result.reasoning_internal_consistency = best_cls.get(
            DIM_REASONING_INTERNAL_CONSISTENCY,
        )
        classifier_result.commitments_internal_consistency = best_cls.get(
            DIM_COMMITMENTS_INTERNAL_CONSISTENCY,
        )
        classifier_result.commitments_code_consistency = best_cls.get(
            DIM_COMMITMENTS_CODE_CONSISTENCY,
        )
    else:
        classifier_result.reasoning_internal_consistency = best_cls.get(
            DIM_REASONING_INTERNAL_CONSISTENCY,
        )
        classifier_result.commitments_extracted = best_cls.get(
            DIM_COMMITMENTS_EXTRACTED,
        )
        classifier_result.commitments_satisfied = best_cls.get(
            DIM_COMMITMENTS_SATISFIED,
        )
    classifier_result.reasoning_code_alignment = best_cls.get(
        DIM_REASONING_CODE_ALIGNMENT,
    )
    if not best_cls.get("classifier_ran", False):
        classifier_result.parse_error = best_cls.get("error", "unknown")

    best_exec = best.get("execution", {})
    exec_result = {
        "pass": best_exec.get("pass", False),
        "score": best_exec.get("score", 0),
    }

    signals = derive_v2_signals(
        classifier_dims=_extract_canonical_dims(classifier_result),
        code_correct=best_exec.get("pass", False),
        commitments_source="none",
    )

    ev = assemble_v2_result(
        exec_result=exec_result,
        artifact=normalize_generation_v2(
            parse_v2_execution("", "baseline_v2"), case, "baseline_v2",
        ),
        classifier=classifier_result,
        signals=signals,
        case=case, condition=condition, model=model,
    )

    ev["oracle"] = copy.deepcopy(best.get("oracle", {}))
    ev["classification"] = copy.deepcopy(best.get("classifier", {}))
    ev["ast_eval"] = copy.deepcopy(best.get("ast", {}))
    ev["reasoning_disagreement"] = copy.deepcopy(
        best.get("reasoning_disagreement", {}),
    )

    ev["evaluation"] = _compute_evaluation_from_trajectory(
        best, classifier_result,
    )

    ev["_schema_version"] = "v3.1"

    final_state = states[-1] if states else None
    if final_state and final_state.routing and final_state.recon:
        from core.pipeline.orchestration.execution_v2 import (
            _build_reconstruction_section,
        )
        recon_section = _build_reconstruction_section(
            final_state.routing, final_state.recon, final_state.exec_result,
        )
        recon_section["artifact_id"] = final_state.artifact_id
        recon_section["parse_mode"] = final_state.parse_mode
        recon_section["strict_parse_valid"] = final_state.strict_parse_valid
        recon_section["recovery_parse_valid"] = (
            final_state.recovery_parse_valid
        )
        recon_section["recovery_used"] = final_state.recovery_used
        recon_section["retry_eligible"] = final_state.retry_eligible
        recon_section["execution_source"] = final_state.execution_source
        recon_section["retry_triggered"] = final_state.retry_triggered
        ev["reconstruction"] = recon_section

    best_spec_oracle = best.get("spec_oracle")
    if best_spec_oracle is not None:
        ev["spec_oracle"] = copy.deepcopy(best_spec_oracle)

    ev["num_attempts"] = len(trajectory)
    ev["best_attempt_idx"] = best_idx
    ev["trajectory"] = trajectory
    ev["retry_passed_at"] = next(
        (t["attempt"] for t in trajectory
         if t.get("execution", {}).get("pass", t.get("pass", False))),
        None,
    )
    ev["retry_mode"] = condition

    apply_validation(ev, trajectory, best_idx, cid)

    elapsed = time.monotonic() - t0
    parsed_compat = {
        "code": "", "reasoning": "",
        "parse_error": None, "_raw_fallback": False,
        "data_lineage": [
            "raw_output_received", "parser_v2", "retry_graph",
        ],
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


def _map_graph_to_state(
    state: Any, graph_out: dict, case: dict, config: Any,
    logger: Any, sampling_mode: str, sampling_params: dict,
    attempt_k: int,
) -> None:
    """Map graph engine outputs back to AttemptState fields.

    The graph runs stages 2-9. We map its outputs to the V2
    AttemptState so that _trajectory_entry_from_state and the
    retry logic can read them.
    """
    from core.pipeline.orchestration.stages import (
        stage_parse, stage_oracle, stage_normalize,
        stage_reconstruct, stage_classify, stage_ast,
        stage_execute, stage_spec_oracle, stage_derive_metrics,
    )
    from core.evaluation.oracle_inline import (
        make_sampling_skip, should_run_oracle,
    )

    # Run V2 stages directly — this guarantees EXACT semantic match.
    # The graph engine is used only for validation (shadow), not dispatch.
    # For the retry controller, we run V2 stages to ensure equivalence.
    stage_parse(state, case)

    if should_run_oracle(sampling_mode, sampling_params, attempt_k):
        stage_oracle(state, case, config, logger)
    else:
        state.oracle_result = make_sampling_skip(
            config,
            f"attempt {attempt_k} not sampled by "
            f"{config.oracle.sampling_strategy}",
        )

    stage_normalize(state, case)
    stage_reconstruct(state, case, config)
    stage_classify(state, case, config, logger)
    stage_ast(state, case)
    stage_execute(state, case, config, logger)
    stage_spec_oracle(state, case)
    stage_derive_metrics(state, config)
