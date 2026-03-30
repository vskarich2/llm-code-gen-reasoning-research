"""V2 execution path — dedicated dispatcher for v2 ablation conditions.

This module owns the full v2 evaluation pipeline:
  prompt build → call_model → parser_v2 → normalize → exec_eval → classify_v2 → metrics → log

It imports FROM legacy modules (llm, exec_eval, assembly_engine, execution logging)
but legacy modules do NOT import from here. One-directional dependency.
"""

import logging
import time
from pathlib import Path

from contracts_v2 import CONDITION_TO_SCHEMA, V2_CONDITIONS
from parser_v2 import parse_v2_execution, parse_v2_format, parse_v2_recovery
from reasoning_v2 import normalize_generation_v2
from evaluator_v2 import (
    build_classifier_v2_vars, parse_classifier_v2_output,
    assemble_v2_result, ClassifierResultV2,
)
from metrics_v2 import derive_v2_signals

_log = logging.getLogger("t3.execution_v2")


def run_v2(case: dict, model: str, condition: str, logger,
           case_start_eid: int = 0) -> tuple[str, str, dict]:
    """Run a v2 condition. Single entry point called from runner.py.

    Handles: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2.
    Returns (case_id, condition, ev) — same signature as v1 run functions.

    Args:
        logger: RunLogger instance. Required. Passed explicitly through call stack.
    """
    if logger is None:
        raise RuntimeError("run_v2 requires an explicit logger")
    if condition not in V2_CONDITIONS:
        raise ValueError(f"run_v2 called with non-v2 condition: {condition}")

    from assembly_engine import build as _assembly_build, resolve_condition
    from prompts import _format_code_files
    from llm import call_model
    from exec_eval import exec_evaluate
    from experiment_config import get_config
    from execution import _capture_prompt_assembly

    t0 = time.monotonic()
    config = get_config()
    cid = case["id"]
    code_files = case["code_files_contents"]
    task = case["task"]
    file_paths = list(code_files.keys())

    # ── STAGE 1: Build prompt ──
    code_block = _format_code_files(code_files)
    file_keys_example = ", ".join(f'"{p}": "<complete file contents or UNCHANGED>"' for p in file_paths)

    schema_variant = CONDITION_TO_SCHEMA[condition]

    schema_line = ""
    if condition == "baseline_v2":
        schema_line = (
            '{"root_cause": "<...>", "fix_strategy": "<...>", "files": {'
            + file_keys_example + '}}'
        )

    variables = {
        "task": task,
        "code_files_block": code_block,
        "file_keys_example": file_keys_example,
        "schema_line": schema_line,
    }

    spec = resolve_condition(condition)
    components = list(spec["components"])
    rendered = _assembly_build(components, variables)
    prompt = rendered.final_prompt
    prompt_asm = _capture_prompt_assembly(rendered, variables, condition, prompt)

    # ── STAGE 2: Call model ──
    raw_response = call_model(
        prompt, model=model, raw=True,
        logger=logger, case_id=cid, phase="generation",
        condition=condition, prompt_assembly=prompt_asm,
        parent_event_id=case_start_eid,
    )
    gen_eid = logger._event_counter

    # ── STAGE 3: Parse (three-tier: execution drives, format+recovery diagnostic) ──
    parse_exec = parse_v2_execution(raw_response, condition)
    parse_fmt = parse_v2_format(raw_response, condition)
    parse_rec = parse_v2_recovery(raw_response, condition)

    parsed_gen = parse_exec  # ONLY execution enters pipeline

    # Compute execution-recovery equivalence
    parse_rec.execution_equivalent = (
        parse_exec.parse_valid
        and parse_rec.parse_valid
        and parse_exec.full_json == parse_rec.full_json
    )

    # Invariant check: execution subset of recovery
    if parse_exec.parse_valid and not parse_rec.parse_valid:
        _log.error(
            "INVARIANT VIOLATION: execution parsed but recovery failed. case=%s condition=%s",
            cid, condition,
        )

    # ── STAGE 4: Normalize ──
    artifact = normalize_generation_v2(parsed_gen, case, condition)

    # ── STAGE 5: Extract code + execute ──
    code = ""
    if parsed_gen.files_dict:
        from reconstructor import reconstruct_strict
        manifest_files = case.get("code_files_contents", {})
        manifest_paths = list(manifest_files.keys())
        recon = reconstruct_strict(manifest_paths, manifest_files, parsed_gen.files_dict)
        if recon.status == "SUCCESS" and recon.changed_files:
            changed_parts = [recon.files[p] for p in manifest_paths if p in recon.changed_files]
            code = "\n\n".join(changed_parts)

    exec_result = exec_evaluate(case, code)

    # ── STAGE 6: Classify (only if parse succeeded) ──
    classifier_result = ClassifierResultV2()
    classify_eid = gen_eid  # default parent if classifier doesn't run
    if parsed_gen.parse_status == "success":
        classifier_vars, source_for_classifier = build_classifier_v2_vars(
            artifact, case, code, config
        )
        classifier_result.commitment_source_for_classifier = source_for_classifier

        classify_prompt = _assembly_build(["classify_reasoning_v2"], classifier_vars).final_prompt
        classify_raw = call_model(
            classify_prompt,
            model=config.models.evaluator.name,
            raw=True,
            logger=logger, case_id=cid, phase="classification",
            condition=condition,
            parent_event_id=gen_eid,
        )
        classify_eid = logger._event_counter
        classifier_result = parse_classifier_v2_output(classify_raw)
        classifier_result.commitment_source_for_classifier = source_for_classifier
    else:
        classifier_result.parse_error = f"skipped: generation parse_status={parsed_gen.parse_status}"

    # ── STAGE 7: Derive metrics ──
    code_correct = exec_result.get("pass", False)
    signals = derive_v2_signals(
        classifier_dims={
            "mechanism_identified": classifier_result.mechanism_identified,
            "commitments_extracted": classifier_result.commitments_extracted,
            "commitments_satisfied": classifier_result.commitments_satisfied,
            "reasoning_code_alignment": classifier_result.reasoning_code_alignment,
        },
        code_correct=code_correct,
        commitments_source=artifact.commitments_source,
    )

    if parsed_gen.parse_status != "success":
        signals.v2_category = "parser_failure_v2"
        signals.legacy_compat_category = "parse_failed"

    # ── STAGE 8: Assemble result ──
    ev = assemble_v2_result(
        exec_result=exec_result,
        artifact=artifact,
        classifier=classifier_result,
        signals=signals,
        case=case,
        condition=condition,
        model=model,
    )

    # Parse tier diagnostics (never consumed by pipeline)
    ev["v2_parse_tiers"] = {
        "exec_parse_valid": parse_exec.parse_valid,
        "exec_schema_valid": parse_exec.schema_valid,
        "exec_parse_error": parse_exec.parse_error,
        "format_valid": parse_fmt.format_valid,
        "format_error": parse_fmt.format_error,
        "recovery_parse_valid": parse_rec.parse_valid,
        "recovery_schema_valid": parse_rec.schema_valid,
        "recovery_type": parse_rec.recovery_type,
        "recovery_steps": parse_rec.recovery_steps,
        "execution_equivalent": parse_rec.execution_equivalent,
        "recoverable": not parse_exec.parse_valid and parse_rec.parse_valid,
        "possible_mis_extraction": parse_exec.possible_mis_extraction,
        "schema_normalization": parse_rec.schema_normalization_applied,
        "invariant_violation": parse_exec.parse_valid and not parse_rec.parse_valid,
    }

    elapsed = time.monotonic() - t0

    # ── STAGE 9: Log via explicit logger ──
    parsed_compat = {
        "code": code,
        "reasoning": f"Root cause: {artifact.normalized_root_cause}\nFix strategy: {artifact.normalized_fix_strategy}",
        "parse_error": parsed_gen.parse_error,
        "_raw_fallback": False,
        "data_lineage": ["raw_output_received", "parser_v2"],
    }

    # Determine parent: classify_eid if classifier ran, else gen_eid
    last_eid = classify_eid if parsed_gen.parse_status == "success" else gen_eid
    end_eid = logger.end_case(cid, condition=condition, raw_ev=ev,
                              runtime_ms=round(elapsed * 1000),
                              parent_event_id=last_eid)
    logger.log_run(cid, condition, prompt, raw_response, parsed_compat,
                   canonical_event_id=end_eid)

    return cid, condition, ev
