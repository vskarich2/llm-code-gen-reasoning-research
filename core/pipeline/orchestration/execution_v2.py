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
    _extract_canonical_dims,
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
    """Canonical critical path. Returns (case_id, condition, ev).

    Pipeline order (v3.1):
      parse → oracle(raw) → normalize → reconstruct → classifier → AST → execute
    Classifier and AST run BEFORE execution to enforce blindness.
    """
    if logger is None:
        raise RuntimeError("run_v2 requires an explicit logger")
    if condition not in V2_CONDITIONS:
        raise ValueError(f"run_v2 called with non-v2 condition: {condition}")
    from core.config.experiment_config import get_config
    from core.evaluation.oracle_inline import run_oracle_evaluation, compute_disagreement
    from core.evaluation.event_validation import apply_validation
    t0 = time.monotonic()
    config = get_config()
    cid = case["id"]

    prompt, prompt_meta = _render_generation_prompt(case, condition, config)
    raw_response, gen_eid = _call_generation_model(
        prompt, model, cid, condition, prompt_meta, logger, case_start_eid)

    strict_parse, recovery_parse, fmt_parse = _parse_outputs(raw_response, condition)
    routing = _select_artifact(strict_parse, recovery_parse, case)
    _check_parse_invariant(strict_parse, recovery_parse, cid, condition, logger)

    parsed_gen = recovery_parse if routing.selected_source == "recovery" else strict_parse

    # Oracle: uses RAW fields, before normalize. None preserved (not coerced to "").
    fj = parsed_gen.full_json or {}
    oracle_result = run_oracle_evaluation(
        fj.get("root_cause"), fj.get("fix_strategy"), case, config,
        logger=logger, case_id=cid, condition=condition, parent_event_id=gen_eid)

    artifact = normalize_generation_v2(parsed_gen, case, condition)
    recon, code = _reconstruct(parsed_gen, case, config)
    artifact_id = _compute_artifact_id(recon)

    # Log classifier visibility surface
    n_total = len(recon.files) if recon.files else 0
    n_modified = len(recon.changed_files) if recon.changed_files else 0
    _log.debug("CLASSIFIER_SURFACE case=%s files_total=%d files_modified=%d",
               cid, n_total, n_modified)

    # Classifier + AST: before execution (blindness enforcement)
    classifier_result, classify_eid = _classify_reasoning(
        artifact, case, code, config, logger, cid, condition, parsed_gen, gen_eid)
    ast_result = _run_ast_verification(recon, case, artifact_id)

    # Execute: after classifier + AST
    exec_result = _execute(case, parsed_gen, recon, config, logger)

    disagreement = compute_disagreement(classifier_result, oracle_result, config)
    signals = _derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
    evaluation = _compute_evaluation(routing, recon, exec_result, classifier_result, oracle_result, artifact_id)

    ev = _assemble_result(exec_result, artifact, classifier_result, signals,
                          case, condition, model, strict_parse, fmt_parse,
                          recovery_parse, routing, recon, evaluation, artifact_id,
                          ast_result, oracle_result, disagreement,
                          prompt_meta=prompt_meta)

    apply_validation(ev, None, -1, cid)

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

    if "logical_file_keys" not in case:
        raise RuntimeError(
            "case missing 'logical_file_keys'. "
            "load_cases() must be called before execution."
        )
    code_files = case["logical_file_keys"]
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
# HELPER: Reconstruct (code assembly only)
# ============================================================

def _reconstruct(parsed_gen, case, config):
    """Reconstruct code from parsed output. No execution.

    Returns (recon, code_string).
    """
    from core.pipeline.reconstructor import reconstruct_strict, ReconstructionResult

    # Generation output contract assertion
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
            recon = ReconstructionResult(
                status="GENERATION_CONTRACT_VIOLATION", files={})
            return recon, ""

    # Use logical file keys (bare filenames) for reconstruction matching.
    # The model sees bare filenames in the prompt and returns bare filenames.
    # The reconstructor matches model output keys against these.
    if "logical_file_keys" not in case:
        raise RuntimeError(
            "case missing 'logical_file_keys'. "
            "load_cases() must be called before reconstruction."
        )
    logical_files = case["logical_file_keys"]
    logical_paths = list(logical_files.keys())

    recon = ReconstructionResult(status="RECON_MISSING_FILES", files={})
    if parsed_gen.files_dict:
        recon = reconstruct_strict(logical_paths, logical_files, parsed_gen.files_dict)

    # Build full materialized code for classifier (ALL files, not just changed).
    # This matches what execution sees — the full reconstructed package.
    full_code_parts = []
    if recon.status == "SUCCESS" and recon.files:
        for path in logical_paths:
            if path in recon.files:
                is_modified = path in recon.changed_files
                marker = "MODIFIED" if is_modified else "UNCHANGED"
                full_code_parts.append(
                    f"# [{marker}] {path}\n{recon.files[path]}")
    full_code = "\n\n".join(full_code_parts)

    return recon, full_code


# ============================================================
# HELPER: Execute
# ============================================================

def _execute(case, parsed_gen, recon, config, logger, attempt=0):
    """Execute tests on reconstructed code. Returns exec_result dict."""
    from core.pipeline.execution.exec_canonical import exec_canonical

    if recon.status == "GENERATION_CONTRACT_VIOLATION":
        return {
            "pass": False, "score": 0.0,
            "reasons": ["Generation contract violation"],
            "execution_category": "STRUCTURAL_FAILURE",
            "failure_type": "GENERATION_CONTRACT_VIOLATION",
            "execution": {"status": "not_executed", "ran": False},
        }

    return exec_canonical(case, parsed_gen, recon, config, logger, attempt=attempt)


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
        classifier_dims=_extract_canonical_dims(classifier_result),
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


def _compute_evaluation(
    routing,
    recon,
    exec_result,
    classification,
    oracle_result,
    artifact_id,
):
    """
    Full-granularity evaluation with preserved signals + derived projections.

    Raw signals (preserved):
      - Oracle: reasoning_truth ∈ {CORRECT, PARTIAL, WRONG, UNJUDGABLE}
      - Classifier: 4 dims (RIC, CIC, CCC, RCA)
      - Execution: execution_category (string)

    Derived axes (projections, NOT replacements):
      - R_bool: reasoning correctness (oracle)
      - T_bool: translation consistency (classifier aggregate)
      - E_bool: execution success

    Provides:
      - fine-grained outcome_class
      - LEG detection + subtype
      - quadrant labels
      - raw + projected signals side-by-side
    """

    # ==================================================
    # THREE INDEPENDENT SIGNALS (computed once, reused)
    # ==================================================

    # E = execution success (ground truth, from test harness)
    execution_category = exec_result.get("execution_category")
    assert execution_category is not None, "execution_category must be set"
    execution_pass = (execution_category == "EXECUTION_SUCCESS")

    # R_recon = reconstruction success (serialization validity)
    reconstruction_success = (recon.status == "SUCCESS")

    # U = routing validity (source selection)
    routing_valid = (routing.selected_source != "none")

    # Serialization failure type (independent of execution)
    s_fail_type = None
    if not routing_valid:
        s_fail_type = _derive_serialization_failure_type(routing, recon)
    elif not reconstruction_success:
        s_fail_type = _derive_serialization_failure_type(routing, recon)

    # ==================================================
    # SERIALIZATION-AWARE LAYER (E × R_recon × U)
    # ==================================================

    if not routing_valid:
        serialization_outcome = "routing_failure"
    elif execution_pass and reconstruction_success:
        serialization_outcome = "clean_success"
    elif execution_pass and not reconstruction_success:
        serialization_outcome = "lucky_success_serialization_failure"
    elif not execution_pass and reconstruction_success:
        serialization_outcome = "valid_output_wrong_code"
    else:
        serialization_outcome = "total_failure"

    # ==================================================
    # Axis R — Oracle reasoning (FULL label + projection)
    # ==================================================
    oracle_label = oracle_result.get("reasoning_truth")
    oracle_correct = oracle_result.get("oracle_correct")
    R_bool = oracle_correct

    # ==================================================
    # Axis T — Classifier translation (FULL dims + projection)
    # ==================================================
    classifier_ran = classification.parse_error is None

    if classifier_ran:
        canonical = _extract_canonical_dims(classification)
        RIC = canonical.get("mechanism_identified")
        CIC = canonical.get("commitments_extracted")
        CCC = canonical.get("commitments_satisfied")
        RCA = canonical.get("reasoning_code_alignment")

        classifier_dims = {"RIC": RIC, "CIC": CIC, "CCC": CCC, "RCA": RCA}
        T_bool = (RIC == "CORRECT") and (CCC == "CORRECT")
    else:
        classifier_dims = {"RIC": None, "CIC": None, "CCC": None, "RCA": None}
        T_bool = None

    # ==================================================
    # OUTCOME CLASSIFICATION (reasoning × execution layer)
    # Uses routing_valid as prerequisite, NOT reconstruction_success.
    # Execution is the ground truth for whether code ran.
    # ==================================================

    if not routing_valid:
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

    # ==================================================
    # LEG subtyping
    # ==================================================
    leg_subtype = None
    if outcome == "LEG":
        if T_bool is True:
            leg_subtype = "execution_failure"
        elif T_bool is False:
            leg_subtype = "translation_failure"
        else:
            leg_subtype = "unknown"

    # ==================================================
    # Quadrant views
    # ==================================================
    quadrant_RT = None
    if isinstance(R_bool, bool) and isinstance(T_bool, bool):
        if R_bool and T_bool:
            quadrant_RT = "R1_T1"
        elif R_bool and not T_bool:
            quadrant_RT = "R1_T0"
        elif not R_bool and T_bool:
            quadrant_RT = "R0_T1"
        else:
            quadrant_RT = "R0_T0"

    quadrant_RE = None
    if isinstance(R_bool, bool):
        if R_bool and execution_pass:
            quadrant_RE = "R1_E1"
        elif R_bool and not execution_pass:
            quadrant_RE = "R1_E0"
        elif not R_bool and execution_pass:
            quadrant_RE = "R0_E1"
        else:
            quadrant_RE = "R0_E0"

    # ==================================================
    # Return EVERYTHING (no information loss)
    # ==================================================

    return {
        # --- Three independent signals ---
        "execution_pass": execution_pass,
        "reconstruction_success": reconstruction_success,
        "routing_valid": routing_valid,
        "serialization_success": reconstruction_success,  # backward compat alias

        # --- Serialization-aware layer (E × R_recon × U) ---
        "serialization_outcome": serialization_outcome,
        "serialization_failure_type": s_fail_type,
        "lucky_success_serialization_failure": (
            execution_pass and not reconstruction_success
        ),

        # --- Execution ---
        "execution_success": execution_pass,
        "execution_category": execution_category,

        # --- Oracle (full + projected) ---
        "oracle_label": oracle_label,
        "oracle_correct": oracle_correct,
        "reasoning_correct": R_bool,

        # --- Classifier (full + projected) ---
        "classifier_ran": classifier_ran,
        "classifier_dims": classifier_dims,
        "translation_consistent": T_bool,

        # --- Outcomes (reasoning × execution layer) ---
        "outcome_class": outcome,
        "LEG": (outcome == "LEG"),
        "LEG_subtype": leg_subtype,

        # --- Quadrants ---
        "quadrant_RT": quadrant_RT,
        "quadrant_RE": quadrant_RE,

        # --- ID ---
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
                     routing, recon, evaluation, artifact_id, ast_result,
                     oracle_result=None, disagreement=None,
                     prompt_meta=None):
    if prompt_meta is None:
        raise RuntimeError(
            "prompt_meta is required in _assemble_result. "
            "Caller must pass the prompt provenance dict from _render_generation_prompt()."
        )
    """Build the final event dict with all v3.1 sections."""
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
    _cls_canonical = _extract_canonical_dims(classifier_result)
    ev["classification"] = {
        # Canonical dimension signals (via mapping layer)
        "mechanism_identified": _cls_canonical["mechanism_identified"],
        "commitments_extracted": _cls_canonical["commitments_extracted"],
        "commitments_satisfied": _cls_canonical["commitments_satisfied"],
        "reasoning_code_alignment": _cls_canonical["reasoning_code_alignment"],
        # V3 raw dimensions (None if v2 parser used)
        "reasoning_internal_consistency": classifier_result.reasoning_internal_consistency,
        "commitments_internal_consistency": classifier_result.commitments_internal_consistency,
        "commitments_code_consistency": classifier_result.commitments_code_consistency,
        # Justifications (debug only — never affects metrics)
        "reasoning_internal_consistency_justification": classifier_result.reasoning_internal_consistency_justification,
        "commitments_internal_consistency_justification": classifier_result.commitments_internal_consistency_justification,
        "commitments_code_consistency_justification": classifier_result.commitments_code_consistency_justification,
        "reasoning_code_alignment_justification": classifier_result.reasoning_code_alignment_justification,
        # Metadata
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

    # Oracle section (v3.1) — always present on new events
    if oracle_result is not None:
        ev["oracle"] = oracle_result
    if disagreement is not None:
        ev["reasoning_disagreement"] = disagreement

    # Schema version
    ev["_schema_version"] = "v3.1"

    # Reproducibility: config hash and model spec
    ev["config"] = {
        "config_hash": _cfg._config_sha256,
        "config_path": _cfg._config_path,
    }
    ev["model_spec"] = {
        "name": model,
    }

    # Prompt provenance
    ev["prompt_meta"] = prompt_meta

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
