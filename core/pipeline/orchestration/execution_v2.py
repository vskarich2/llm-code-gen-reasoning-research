"""V2 execution path — canonical critical-path orchestration.

This module owns the full v2 evaluation pipeline:
  prompt build → call_model → parse → validate → reconstruct → execute → classify → metrics → log

The top-level function `run_v2()` is the single readable entrypoint.
All stage logic is delegated to helper functions below it.
"""

import hashlib as _hl
import json as _j
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.contracts.contracts_v2 import CONDITION_TO_SCHEMA, V2_CONDITIONS
from core.pipeline.parsing.parser_v2 import parse_v2_execution, parse_v2_format, parse_v2_recovery
from core.evaluation.reasoning_v2 import normalize_generation_v2
from core.evaluation.evaluator_v2 import (
    build_classifier_v2_vars, parse_classifier_v2_output,
    parse_classifier_v3_output, assemble_v2_result, ClassifierResultV2,
)
from core.evaluation.metrics_v2 import derive_v2_signals
from core.pipeline.prompting.compiler import compile as _prompt_compile
from core.pipeline.prompting.contracts import PromptProgram
from core.pipeline.prompting.sections import Section
from core.pipeline.prompting.validator import CompilerMode

_log = logging.getLogger("t3.execution_v2")

_compiler_registry = None

# ── Pipeline stage contracts ──
GENERATION_OUTPUT_CONTRACT = frozenset({
    "root_cause",
    "fix_strategy",
    "files",
})


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class StructuralValidationResult:
    """Result of validating a parsed output's structure against case expectations."""
    structurally_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    observed_files: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    """Which parsed artifact was selected for execution and why."""
    selected_source: str              # "strict" | "recovery" | "none"
    strict_parse_valid: bool = False
    recovery_parse_valid: bool = False
    strict_structurally_valid: bool = False
    recovery_structurally_valid: bool = False
    recovery_used: bool = False
    divergence_detected: bool = False
    structural_errors: list[str] = field(default_factory=list)


# ============================================================
# COMPILER REGISTRY (singleton)
# ============================================================

def _get_compiler_registry():
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


def _compile_prompt_from_components(components, variables):
    """Compile a prompt from component names and template variables."""
    program = PromptProgram(
        name="execution_v2",
        condition="execution_v2",
        components=components,
        required_sections=(),
        allowed_sections=tuple(Section),
        section_order=(),
        strict=False,
    )
    return _prompt_compile(
        program, variables, CompilerMode.MIGRATION, _get_compiler_registry()
    )


# ============================================================
# TOP-LEVEL CRITICAL PATH (≤60 lines)
# ============================================================

def run_v2(case: dict, model: str, condition: str, logger,
           case_start_eid: int | str = 0) -> tuple[str, str, dict]:
    """Canonical critical path. Returns (case_id, condition, ev)."""
    if logger is None:
        raise RuntimeError("run_v2 requires an explicit logger")
    if condition not in V2_CONDITIONS:
        raise ValueError(f"run_v2 called with non-v2 condition: {condition}")
    from core.config.experiment_config import get_config
    t0 = time.monotonic()
    config = get_config()
    cid = case["id"]

    prompt, prompt_meta = _render_generation_prompt(case, condition, config)
    raw_response, gen_eid = _call_generation_model(
        prompt, model, cid, condition, prompt_meta, logger, case_start_eid)

    strict_parse, recovery_parse, fmt_parse = _parse_outputs(raw_response, condition)
    routing = _select_artifact(strict_parse, recovery_parse, case)
    _check_parse_invariant(strict_parse, recovery_parse, cid, condition, logger)

    if routing.selected_source == "recovery":
        parsed_gen = recovery_parse
    else:
        parsed_gen = strict_parse
    artifact = normalize_generation_v2(parsed_gen, case, condition)
    recon, code, exec_result = _reconstruct_and_execute(parsed_gen, case, config, logger)
    artifact_id = _compute_artifact_id(recon)

    classifier_result, classify_eid = _classify_reasoning(
        artifact, case, code, config, logger, cid, condition, parsed_gen, gen_eid)
    signals = _derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
    evaluation = _compute_evaluation(routing, recon, exec_result, classifier_result, artifact_id)
    ast_result = _run_ast_verification(recon, case, artifact_id)

    ev = _assemble_result(exec_result, artifact, classifier_result, signals,
                          case, condition, model, strict_parse, fmt_parse,
                          recovery_parse, routing, recon, evaluation, artifact_id,
                          ast_result)

    elapsed = time.monotonic() - t0
    _log_result(logger, cid, condition, ev, prompt, raw_response,
                artifact, parsed_gen, gen_eid, classify_eid, elapsed)
    return cid, condition, ev


# ============================================================
# HELPER: Structural validation
# ============================================================

def _validate_structure(parsed, case) -> StructuralValidationResult:
    """Validate a parsed output against case structural expectations.

    Checks:
    1. Required file coverage
    2. No duplicate file keys
    3. No empty changed-file payloads
    4. Valid changed/unchanged semantics (not all UNCHANGED)
    5. File basename consistency
    """
    if not parsed.parse_valid or not parsed.files_dict:
        return StructuralValidationResult(
            structurally_valid=False,
            errors=["parse invalid or no files_dict"],
        )

    expected = list(case.get("code_files", []))
    expected_basenames = {Path(f).name for f in expected}
    observed = list(parsed.files_dict.keys())
    observed_basenames = {Path(f).name for f in observed}

    errors = []

    # 1. Required file coverage
    missing = set(expected) - set(observed)
    # Allow if model uses basenames instead of full paths
    missing_basenames = expected_basenames - observed_basenames
    if missing and missing_basenames:
        errors.append(f"missing files: {sorted(missing)}")

    # 2. Duplicate file keys
    if len(observed) != len(set(observed)):
        seen = set()
        dupes = [f for f in observed if f in seen or seen.add(f)]
        errors.append(f"duplicate file keys: {dupes}")

    # 3. Empty changed-file payloads
    for fname, content in parsed.files_dict.items():
        if content is not None and not isinstance(content, str):
            errors.append(f"non-string content for {fname}")
        elif content is not None and content.strip() == "":
            errors.append(f"empty content for {fname}")

    # 4. All UNCHANGED = no actual change
    unchanged_sentinel = "UNCHANGED"
    all_unchanged = all(
        v == unchanged_sentinel or v is None
        for v in parsed.files_dict.values()
    )
    if all_unchanged and parsed.files_dict:
        errors.append("all files marked UNCHANGED (no change)")

    return StructuralValidationResult(
        structurally_valid=len(errors) == 0,
        errors=errors,
        expected_files=expected,
        observed_files=observed,
    )


# ============================================================
# HELPER: Select artifact (routing)
# ============================================================

def _select_artifact(strict_parse, recovery_parse, case) -> RoutingDecision:
    """Validate structure of both parse results and select the execution artifact.

    Routing policy:
    1. Prefer strict if strict is parse-valid AND structurally valid.
    2. Use recovery only if strict is unusable AND recovery is parse-valid
       AND structurally valid AND config recovery_execution is True.
    3. If both unusable (or recovery disabled when strict fails), select none.
    """
    from core.config.experiment_config import get_config

    _invalid = StructuralValidationResult(structurally_valid=False, errors=["parse invalid"])
    strict_sv = _validate_structure(strict_parse, case) if strict_parse.parse_valid else _invalid
    recovery_sv = _validate_structure(recovery_parse, case) if recovery_parse.parse_valid else _invalid

    divergence = (
        strict_parse.parse_valid and recovery_parse.parse_valid
        and strict_sv.structurally_valid and recovery_sv.structurally_valid
        and not getattr(recovery_parse, 'execution_equivalent', True)
    )

    if strict_parse.parse_valid and strict_sv.structurally_valid:
        selected = "strict"
        recovery_used = False
    elif (get_config().execution.recovery_execution
          and recovery_parse.parse_valid
          and recovery_sv.structurally_valid):
        selected = "recovery"
        recovery_used = True
    else:
        selected = "none"
        recovery_used = False

    return RoutingDecision(
        selected_source=selected,
        strict_parse_valid=strict_parse.parse_valid,
        recovery_parse_valid=recovery_parse.parse_valid,
        strict_structurally_valid=strict_sv.structurally_valid,
        recovery_structurally_valid=recovery_sv.structurally_valid,
        recovery_used=recovery_used,
        divergence_detected=divergence,
        structural_errors=strict_sv.errors + recovery_sv.errors,
    )


# ============================================================
# HELPER: Render generation prompt
# ============================================================

def _render_generation_prompt(case, condition, config):
    """Build the generation prompt from condition components and case data."""
    from core.pipeline import _format_code_files

    code_files = case.get("logical_file_keys") or case["code_files_contents"]
    task = case["task"]
    file_paths = list(code_files.keys())

    code_block = _format_code_files(code_files)
    file_keys_example = ", ".join(
        f'"{p}": "<complete file contents or UNCHANGED>"' for p in file_paths
    )

    schema_line = ""
    if condition in ("baseline_v2", "baseline_v3"):
        schema_line = (
            '{"root_cause": "<...>", "fix_strategy": "<...>", '
            '"code_commitments": ["<scope> must <action>", ...], '
            '"files": {' + file_keys_example + '}}'
        )

    variables = {
        "task": task,
        "code_files_block": code_block,
        "file_keys_example": file_keys_example,
        "schema_line": schema_line,
    }

    reg = _get_compiler_registry()
    prog = reg.get_program(condition)
    components = tuple(prog.components)

    compiled = _prompt_compile(
        PromptProgram(
            name=f"{condition}_generation",
            condition=condition,
            components=components,
            required_sections=(),
            allowed_sections=tuple(Section),
            section_order=(),
            strict=False,
        ),
        variables,
        CompilerMode.MIGRATION,
        _get_compiler_registry(),
    )

    try:
        config_name = config.experiment.name
    except Exception:
        config_name = None

    prompt_meta = {
        "prompt_family": condition,
        "prompt_name": compiled.composition_hash,
        "prompt_version": config_name,
        "prompt_hash": compiled.final_prompt_hash,
        "template_id": compiled.composition_hash,
        "variables_hash": _hl.sha256(
            _j.dumps(variables, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "template_stack": list(components),
        "logical_file_keys": list(code_files.keys()),
    }

    return compiled.final_prompt, prompt_meta


# ============================================================
# HELPER: Call generation model
# ============================================================

def _call_generation_model(prompt, model, cid, condition, prompt_meta,
                           logger, case_start_eid):
    """Call the LLM for code generation. Returns (raw_response, gen_event_id)."""
    from core.pipeline.llm import call_model

    gen_result = call_model(
        prompt, model=model, raw=True,
        logger=logger, case_id=cid, phase="generation",
        condition=condition, prompt_assembly=prompt_meta,
        parent_event_id=case_start_eid,
    )
    raw_response = gen_result.response
    assert gen_result.event_id is not None, \
        "call_model must return event_id in execution path"
    return raw_response, gen_result.event_id


# ============================================================
# HELPER: Parse outputs
# ============================================================

def _parse_outputs(raw_response, condition):
    """Run strict, format, and recovery parsers. Returns three parse results."""
    strict = parse_v2_execution(raw_response, condition)
    fmt = parse_v2_format(raw_response, condition)
    recovery = parse_v2_recovery(raw_response, condition)

    recovery.execution_equivalent = (
        strict.parse_valid
        and recovery.parse_valid
        and strict.full_json == recovery.full_json
    )

    return strict, recovery, fmt


def _check_parse_invariant(strict, recovery, cid, condition, logger):
    """Log invariant violation if strict parsed but recovery did not."""
    if strict.parse_valid and not recovery.parse_valid:
        _log.error(
            "INVARIANT VIOLATION: execution parsed but recovery failed. "
            "case=%s condition=%s", cid, condition,
        )
        logger.log_structured_error("case.error.parse", cid, {
            "parse_stage": "v2_invariant",
            "error": (
                f"execution parsed but recovery failed: "
                f"exec_valid={strict.parse_valid}, "
                f"recovery_valid={recovery.parse_valid}"
            ),
        })


# ============================================================
# HELPER: Reconstruct + execute
# ============================================================

def _reconstruct_and_execute(parsed_gen, case, config, logger):
    """Reconstruct code from parsed output and execute canonically.

    Returns (recon, code_string, exec_result).
    """
    # ── Generation output contract assertion ──
    if parsed_gen.parse_valid and parsed_gen.full_json:
        fj = parsed_gen.full_json
        missing = GENERATION_OUTPUT_CONTRACT - set(fj.keys())
        if missing:
            cid = case["id"]
            _log.error(
                "GENERATION CONTRACT VIOLATION: case=%s missing fields=%s "
                "observed=%s. Marking as structural pipeline failure.",
                cid, sorted(missing), sorted(fj.keys()),
            )
            from core.pipeline.reconstructor import ReconstructionResult
            recon = ReconstructionResult(
                status="GENERATION_CONTRACT_VIOLATION",
                files={},
            )
            exec_result = {
                "pass": False,
                "score": 0.0,
                "reasons": [f"Generation output missing: {sorted(missing)}"],
                "execution_category": "STRUCTURAL_FAILURE",
                "failure_type": "GENERATION_CONTRACT_VIOLATION",
                "execution": {"status": "not_executed", "ran": False},
            }
            return recon, "", exec_result

    from core.pipeline.reconstructor import reconstruct_strict, ReconstructionResult
    from core.pipeline.execution.exec_canonical import exec_canonical

    manifest_files = case.get("code_files_contents", {})
    manifest_paths = list(manifest_files.keys())

    code = ""
    recon = ReconstructionResult(status="RECON_MISSING_FILES", files={})
    if parsed_gen.files_dict:
        recon = reconstruct_strict(manifest_paths, manifest_files, parsed_gen.files_dict)
        if recon.status == "SUCCESS" and recon.changed_files:
            changed_parts = [recon.files[p] for p in manifest_paths
                             if p in recon.changed_files]
            code = "\n\n".join(changed_parts)

    exec_result = exec_canonical(case, parsed_gen, recon, config, logger, attempt=0)

    return recon, code, exec_result


# ============================================================
# HELPER: Classify reasoning
# ============================================================

def _classify_reasoning(artifact, case, code, config, logger,
                        cid, condition, parsed_gen, gen_eid):
    """Run the reasoning classifier if parse succeeded.

    Delegates to the canonical classify_case() in evaluator_v2.
    Returns (ClassifierResultV2, classify_event_id).
    """
    from core.evaluation.evaluator_v2 import classify_case

    if parsed_gen.parse_status == "success":
        return classify_case(
            artifact, case, code, config, logger, gen_eid, condition, cid)
    else:
        result = ClassifierResultV2()
        result.parse_error = f"skipped: generation parse_status={parsed_gen.parse_status}"
        return result, gen_eid


# ============================================================
# HELPER: Derive metrics
# ============================================================

def _derive_metrics(classifier_result, artifact, exec_result, parsed_gen):
    """Compute v2 signals from classifier and execution results."""
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

    return signals


# ============================================================
# HELPER: Artifact ID
# ============================================================

def _compute_artifact_id(recon) -> str:
    """Deterministic hash of reconstructed code. Uses json.dumps for stability."""
    import hashlib, json as _json
    if recon.status != "SUCCESS" or not recon.files:
        return "no_artifact"
    content = _json.dumps(dict(recon.files), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ============================================================
# HELPER: Formal evaluation model (3-axis + outcome class)
# ============================================================

def _compute_evaluation(routing, recon, exec_result, classification, artifact_id):
    """Compute the 3-axis evaluation model and outcome class.

    Axes:
      S (serialization) — from routing + recon, NOT exec_result
      E (execution)     — from execution_category only
      R (reasoning)     — from classifier dimensions, None-safe

    Outcome classes form a complete partition. Assertion enforced.
    """
    # Axis 1: Serialization
    S = (routing.selected_source != "none") and (recon.status == "SUCCESS")

    # Axis 2: Execution — execution_category must always be set
    execution_category = exec_result.get("execution_category")
    assert execution_category is not None, \
        "execution_category must be set before evaluation"
    E = (execution_category == "EXECUTION_SUCCESS")

    # Axis 3: Reasoning — from classifier, None-safe
    classifier_ran = classification.parse_error is None
    if classifier_ran:
        M = (classification.mechanism_identified == "CORRECT")
        C = (classification.commitments_satisfied == "CORRECT")
        A = (classification.reasoning_code_alignment == "CORRECT")
        R = M and C
    else:
        M = None
        C = None
        A = None
        R = None

    # Outcome classification
    # R can be None when classifier didn't run (e.g., missing reasoning fields).
    # This is a valid state — the model produced code but no reasoning.
    if not S:
        outcome = "serialization_failure"
        s_fail_type = _derive_serialization_failure_type(routing, recon)
    elif R is None:
        # Serialization succeeded but classifier didn't run.
        # Classify based on execution alone — reasoning is unknown.
        outcome = "classifier_not_run"
        s_fail_type = None
    elif E and R:
        outcome = "interpretable_success"
        s_fail_type = None
    elif E and not R:
        outcome = "unsupported_success"
        s_fail_type = None
    elif not E and R:
        outcome = "LEG"
        s_fail_type = None
    else:  # not E and not R
        outcome = "reasoning_failure"
        s_fail_type = None

    # Partition assertion (when R is a bool, not None)
    if S and isinstance(R, bool):
        classes = [
            S and E and R,
            S and E and (not R),
            S and (not E) and R,
            S and (not E) and (not R),
        ]
        assert sum(classes) == 1, f"Partition violated: S={S} E={E} R={R}"

    # LEG subtyping
    leg_subtype = None
    if outcome == "LEG":
        leg_subtype = "congruent" if A else "incongruent"

    return {
        "serialization_success": S,
        "serialization_failure_type": s_fail_type,
        "execution_success": E,
        "execution_category": execution_category,
        "mechanism_correct": M,
        "commitments_valid": C,
        "alignment_positive": A,
        "reasoning_sufficient": R,
        "LEG": (outcome == "LEG"),
        "LEG_subtype": leg_subtype,
        "outcome_class": outcome,
        "artifact_id": artifact_id,
    }


def _derive_serialization_failure_type(routing, recon):
    """Classify the specific serialization failure mode.

    Distinct failure modes are never collapsed.
    """
    if routing.selected_source == "none":
        if not routing.strict_parse_valid and not routing.recovery_parse_valid:
            return "parser_failure"
        if routing.strict_parse_valid and not routing.strict_structurally_valid:
            if not routing.recovery_parse_valid:
                return "strict_structural_invalid"
            if routing.recovery_parse_valid and not routing.recovery_structurally_valid:
                return "both_structural_invalid"
            return "unknown"
        if not routing.strict_parse_valid and routing.recovery_parse_valid:
            if not routing.recovery_structurally_valid:
                return "recovery_structural_invalid"
            return "unknown"
        return "unknown"
    # Artifact was selected but recon failed
    status = recon.status
    if status == "RECON_INVALID_CODE":
        return "syntax_error"
    if status == "RECON_MISSING_FILES":
        return "missing_file"
    if status == "RECON_EMPTY_FILE":
        return "empty_file"
    if status == "RECON_SENTINEL_MISMATCH":
        return "invalid_structure"
    return "recon_failure"


# ============================================================
# HELPER: AST verification
# ============================================================

def _run_ast_verification(recon, case, artifact_id):
    """Run AST structural verification if spec exists.

    Must run on the same reconstructed artifact used for execution.
    Must not run on failed reconstruction.
    Every evaluation emits an explicit status — never silently omitted.
    """
    from core.evaluation.ast_eval import check_ast_patterns

    if recon.status == "SUCCESS" and recon.files:
        return check_ast_patterns(
            reconstructed_files=dict(recon.files),
            case_id=case["id"],
            artifact_id=artifact_id,
        )
    else:
        from core.evaluation.ast_eval import ASTResult
        return ASTResult(
            status="not_measurable",
            reason="reconstruction_failed",
            artifact_id=artifact_id,
        )


# ============================================================
# HELPER: Build reconstruction section
# ============================================================

def _build_reconstruction_section(routing, recon, exec_result):
    """Build the first-class reconstruction event section."""
    executed = exec_result.get("pass") is not None  # execution was attempted

    return {
        # Parse routing
        "parsing_mode": routing.selected_source if routing.selected_source != "none" else "failed",
        "strict_parse_valid": routing.strict_parse_valid,
        "recovery_parse_valid": routing.recovery_parse_valid,
        "strict_structurally_valid": routing.strict_structurally_valid,
        "recovery_structurally_valid": routing.recovery_structurally_valid,
        "structural_errors": routing.structural_errors,
        "recovery_used": routing.recovery_used,
        "divergence_detected": routing.divergence_detected,
        "execution_eligible": routing.selected_source != "none" and recon.status == "SUCCESS",
        "executed": executed,
        # Reconstruction result (ALL fields from ReconstructionResult)
        "recon_status": recon.status,
        "reconstruction_mode": recon.reconstruction_mode,
        "files_changed": sorted(recon.changed_files) if recon.changed_files else [],
        "files_missing": sorted(recon.missing_files) if recon.missing_files else [],
        "files_extra": sorted(recon.extra_files) if recon.extra_files else [],
        "files_total": len(recon.files) if recon.files else 0,
        "syntax_errors": recon.syntax_errors if recon.syntax_errors else {},
        "format_violation": recon.format_violation,
        # Recovery tracking
        "content_normalized": recon.content_normalized,
        "normalization_log": recon.normalization_log,
        "recovery_applied": recon.recovery_applied,
        "recovery_types": recon.recovery_types,
        # Semantic diagnostics
        "semantic_diagnostics": recon.semantic_diagnostics,
    }


# ============================================================
# HELPER: Assemble result
# ============================================================

def _assemble_result(exec_result, artifact, classifier_result, signals,
                     case, condition, model,
                     strict_parse, fmt_parse, recovery_parse,
                     routing, recon, evaluation, artifact_id, ast_result):
    """Build the final event dict with reconstruction, classification, evaluation, AST."""
    from core.config.experiment_config import get_config
    _cfg = get_config()

    ev = assemble_v2_result(
        exec_result=exec_result,
        artifact=artifact,
        classifier=classifier_result,
        signals=signals,
        case=case,
        condition=condition,
        model=model,
    )

    # First-class reconstruction section (PR4a)
    recon_section = _build_reconstruction_section(routing, recon, exec_result)
    recon_section["artifact_id"] = artifact_id
    recon_section["recovery_execution_enabled"] = _cfg.execution.recovery_execution
    ev["reconstruction"] = recon_section

    # First-class classification section (PR5)
    ev["classification"] = {
        "mechanism_identified": classifier_result.mechanism_identified,
        "commitments_extracted": classifier_result.commitments_extracted,
        "commitments_satisfied": classifier_result.commitments_satisfied,
        "reasoning_code_alignment": classifier_result.reasoning_code_alignment,
        "classifier_ran": classifier_result.parse_error is None,
        "classifier_skipped_reason": classifier_result.parse_error,
        "classifier_mode": _cfg.evaluation.classifier_mode,
        "classifier_template": _cfg.evaluation.classifier_template,
        "classifier_schema_variant": _cfg.evaluation.classifier_schema_variant,
        "commitment_state": artifact.commitment_quality_state if hasattr(artifact, 'commitment_quality_state') else (classifier_result.commitment_source_for_classifier or "none"),
        "artifact_id": artifact_id,
    }

    # First-class evaluation section (PR6)
    ev["evaluation"] = evaluation

    # AST verification section (PR7) — always present on new events
    ev["ast_eval"] = ast_result.to_dict()

    # Reproducibility: config hash and model spec
    ev["config"] = {
        "config_hash": _cfg._config_sha256,
        "config_path": _cfg._config_path,
    }
    ev["model_spec"] = {
        "name": model,
    }

    # Legacy parse tier diagnostics (retained for backward compat)
    ev["v2_parse_tiers"] = {
        "exec_parse_valid": strict_parse.parse_valid,
        "exec_schema_valid": strict_parse.schema_valid,
        "exec_parse_error": strict_parse.parse_error,
        "format_valid": fmt_parse.format_valid,
        "format_error": fmt_parse.format_error,
        "recovery_parse_valid": recovery_parse.parse_valid,
        "recovery_schema_valid": recovery_parse.schema_valid,
        "recovery_type": recovery_parse.recovery_type,
        "recovery_steps": recovery_parse.recovery_steps,
        "execution_equivalent": recovery_parse.execution_equivalent,
        "recoverable": not strict_parse.parse_valid and recovery_parse.parse_valid,
        "possible_mis_extraction": strict_parse.possible_mis_extraction,
        "schema_normalization": recovery_parse.schema_normalization_applied,
        "invariant_violation": strict_parse.parse_valid and not recovery_parse.parse_valid,
    }

    return ev


# ============================================================
# HELPER: Log result
# ============================================================

def _log_result(logger, cid, condition, ev, prompt, raw_response,
                artifact, parsed_gen, gen_eid, classify_eid, elapsed):
    """Emit the case-end event and log the run record."""
    parsed_compat = {
        "code": ev.get("_extracted_code", ""),
        "reasoning": (
            f"Root cause: {artifact.normalized_root_cause}\n"
            f"Fix strategy: {artifact.normalized_fix_strategy}"
        ),
        "parse_error": parsed_gen.parse_error,
        "_raw_fallback": False,
        "data_lineage": ["raw_output_received", "parser_v2"],
    }

    last_eid = classify_eid if parsed_gen.parse_status == "success" else gen_eid
    end_eid = logger.end_case(
        cid, condition=condition, raw_ev=ev,
        runtime_ms=round(elapsed * 1000),
        parent_event_id=last_eid,
    )
    logger.log_run(
        cid, condition, prompt, raw_response, parsed_compat,
        canonical_event_id=end_eid,
    )
