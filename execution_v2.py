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
from parser_v2 import parse_generation_v2
from reasoning_v2 import normalize_generation_v2
from evaluator_v2 import (
    build_classifier_v2_vars, parse_classifier_v2_output,
    assemble_v2_result, ClassifierResultV2,
)
from metrics_v2 import derive_v2_signals

_log = logging.getLogger("t3.execution_v2")


def run_v2(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    """Run a v2 condition. Single entry point called from runner.py.

    Handles: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2.
    Returns (case_id, condition, ev) — same signature as v1 run functions.
    """
    if condition not in V2_CONDITIONS:
        raise ValueError(f"run_v2 called with non-v2 condition: {condition}")

    from assembly_engine import build as _assembly_build, resolve_condition
    from prompts import _format_code_files
    from llm import call_model
    from exec_eval import exec_evaluate
    from experiment_config import get_config
    from call_logger import set_call_context, set_prompt_provenance

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

    # Build schema_line for output_instruction_v3 (baseline_v2 only)
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

    set_prompt_provenance(rendered, variables, condition=condition)
    set_call_context(phase="generation", case_id=cid, condition=condition, attempt_index=0)

    # ── STAGE 2: Call model ──
    raw_response = call_model(prompt, model=model, raw=True)

    # ── STAGE 3: Parse (parser_v2 — sole authority) ──
    parsed_gen = parse_generation_v2(raw_response, condition)

    # ── STAGE 4: Normalize ──
    artifact = normalize_generation_v2(parsed_gen, case, condition)

    # ── STAGE 5: Extract code + execute ──
    code = ""
    if parsed_gen.files_dict:
        # Reconstruct code from files dict
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
    if parsed_gen.parse_status == "success":
        classifier_vars, source_for_classifier = build_classifier_v2_vars(
            artifact, case, code, config
        )
        classifier_result.commitment_source_for_classifier = source_for_classifier

        set_call_context(phase="classifier", case_id=cid, condition=condition, attempt_index=0)
        classify_raw = call_model(
            _assembly_build(["classify_reasoning_v2"], classifier_vars).final_prompt,
            model=config.models.evaluator.name,
            raw=True,
        )
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

    # Handle parse/classifier failures for category
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

    elapsed = time.monotonic() - t0

    # ── STAGE 9: Log ──
    # Reuse existing logging infrastructure
    from execution import write_log, _emit_metrics_event

    # Build a parsed dict compatible with write_log signature
    parsed_compat = {
        "code": code,
        "reasoning": f"Root cause: {artifact.normalized_root_cause}\nFix strategy: {artifact.normalized_fix_strategy}",
        "parse_error": parsed_gen.parse_error,
        "_raw_fallback": False,
        "data_lineage": ["raw_output_received", "parser_v2"],
    }

    write_log(cid, condition, model, prompt, raw_response, parsed_compat, ev)
    _emit_metrics_event(case, model, condition, ev, elapsed_seconds=round(elapsed, 2))

    return cid, condition, ev
