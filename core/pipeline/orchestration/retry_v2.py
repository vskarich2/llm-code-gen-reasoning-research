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

    # Map variant to .j2 component
    variant_to_component = {
        "strict": "critique_strict",
        "moderate": "critique_moderate",
        "aggressive": "critique_aggressive",
        "reasoning_only": "critique_reasoning_only",
    }
    comp_name = variant_to_component.get(variant)
    if not comp_name:
        info["skipped_missing_fields"] = True
        return info, parent_eid

    crit_vars = {"root_cause": root_cause, "fix_strategy": fix_strategy}
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


def run_retry_v2(
    case: dict,
    model: str,
    condition: str,
    logger,
    case_start_eid: int = 0,
) -> tuple[str, str, dict]:
    """Run v2 retry harness. Returns (case_id, condition, ev)."""

    config = get_config()
    cond_retry = config.conditions[condition].retry
    max_iterations = cond_retry.max_attempts
    max_total_seconds = cond_retry.max_total_seconds
    cid = case["id"]
    code_files = case["code_files_contents"]
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

    # Determine retry mode
    use_test_feedback = "no_contract" in condition or "adaptive" in condition
    use_classifier_hint = "adaptive" in condition
    use_bare_retry = "bare_retry" in condition
    critique_variant = _resolve_critique_variant(condition)

    t0 = time.monotonic()
    trajectory = []
    prev_code = ""
    prev_raw = ""
    last_parent_eid = case_start_eid
    best_ev = None
    best_parsed_gen = None
    best_code = ""

    for k in range(max_iterations):
        elapsed = time.monotonic() - t0
        if elapsed > max_total_seconds:
            _log.warning("TIMEOUT %s after %.1fs at attempt %d", cid, elapsed, k)
            break

        # ── Build prompt ──
        if k == 0:
            gen_vars = {
                "task": task,
                "code_files_block": code_block,
                "file_keys_example": file_keys_example,
                "schema_line": schema_line,
            }
            prompt = _compile_prompt(
                ("task_and_code", "output_instruction_v3"), gen_vars
            )

        elif use_bare_retry:
            # Pure control: previous response + same prompt, nothing else
            gen_vars = {
                "task": task,
                "code_files_block": code_block,
                "file_keys_example": file_keys_example,
                "schema_line": schema_line,
            }
            base_prompt = _compile_prompt(
                ("task_and_code", "output_instruction_v3"), gen_vars
            )
            prompt = (
                f"Your previous response:\n{prev_raw}\n\n"
                + base_prompt
            )

        elif critique_variant and critique_info.get("critique"):
            # Critique modes: previous attempt + critique
            prompt = _build_critique_retry_prompt(
                prev_raw, critique_info["critique"], schema_line,
            )

        elif critique_variant and not critique_info.get("critique"):
            # Critique mode but NO_MISMATCH or missing fields: plain retry
            prompt = _build_critique_retry_prompt(prev_raw, "", schema_line)

        elif use_test_feedback:
            # Test feedback modes — compiled via test_feedback_retry.j2
            prompt = _compile_prompt(("test_feedback_retry",), {
                "task": task,
                "code_files_block": code_block,
                "prev_code": prev_code,
                "test_feedback": test_feedback,
                "schema_line": schema_line,
                "classifier_hint": classifier_hint if use_classifier_hint else "",
            })

        else:
            # Fallback
            prompt = _build_critique_retry_prompt(prev_raw, "", schema_line)

        # ── Call model ──
        gen_result = call_model(
            prompt, model=model, raw=True,
            logger=logger, case_id=cid, phase="generation",
            condition=condition,
            parent_event_id=last_parent_eid,
        )
        raw_response = gen_result.response
        assert gen_result.event_id is not None, "call_model must return event_id in execution path"
        last_parent_eid = gen_result.event_id

        # ── Parse ──
        parse_exec = parse_v2_execution(raw_response, "baseline_v2")
        parse_fmt = parse_v2_format(raw_response, "baseline_v2")
        parse_rec = parse_v2_recovery(raw_response, "baseline_v2")
        parsed_gen = parse_exec

        parse_rec.execution_equivalent = (
            parse_exec.parse_valid and parse_rec.parse_valid
            and parse_exec.full_json == parse_rec.full_json
        )

        # ── Extract code ──
        code = ""
        from core.pipeline.reconstructor import ReconstructionResult
        manifest_files = case.get("code_files_contents", {})
        manifest_paths = list(manifest_files.keys())
        recon = ReconstructionResult(status="RECON_MISSING_FILES", files={})
        if parsed_gen.files_dict:
            recon = reconstruct_strict(
                manifest_paths, manifest_files, parsed_gen.files_dict
            )
            if recon.status == "SUCCESS" and recon.changed_files:
                changed = [recon.files[p] for p in manifest_paths
                           if p in recon.changed_files]
                code = "\n\n".join(changed)

        # ── Execute ──
        from core.pipeline.execution.exec_canonical import exec_canonical
        exec_result = exec_canonical(
            case, parsed_gen, recon, config, logger, attempt=k)
        passed = exec_result.get("pass", False)

        # ── Build hints for next iteration ──
        test_feedback = ""
        classifier_hint = ""
        critique_info = {
            "critique": "", "variant": critique_variant,
            "no_mismatch": False, "truncated": False,
            "prescriptive": False, "skipped_missing_fields": False,
        }

        if not passed and k < max_iterations - 1:
            reasons = exec_result.get("reasons", [])
            test_feedback = "\n".join(reasons) if reasons else "Tests failed."

            fj = parsed_gen.full_json or {}
            root_cause = fj.get("root_cause", "")
            fix_strategy = fj.get("fix_strategy", "")

            # Classifier hint (adaptive mode)
            if use_classifier_hint and parsed_gen.parse_status == "success":
                try:
                    cv = {
                        "root_cause": root_cause,
                        "fix_strategy": fix_strategy,
                        "code": (code or ""),
                        "task": task,
                    }
                    cp = _compile_prompt(("critique_mismatch_v2",), cv)
                    hint_result = call_model(
                        cp, model=config.models.evaluator.name, raw=True,
                        logger=logger, case_id=cid, phase="classification",
                        condition=condition, parent_event_id=last_parent_eid,
                    )
                    cr = hint_result.response
                    assert hint_result.event_id is not None, "call_model must return event_id in execution path"
                    last_parent_eid = hint_result.event_id
                    ct = cr.strip()
                    if ct and "NO MISMATCH" not in ct:
                        classifier_hint = f"\n=== Reasoning-Code Mismatch ===\n{ct}"
                except Exception as e:
                    _log.debug("Classifier hint failed: %s", e)

            # Mismatch critique (leg_critique modes)
            if critique_variant:
                critique_info, last_parent_eid = _generate_critique(
                    critique_variant, root_cause, fix_strategy, code,
                    config, logger, cid, condition, last_parent_eid,
                )

        # ── Track trajectory ──
        trajectory.append({
            "attempt": k,
            "pass": passed,
            "score": exec_result.get("score", 0),
            "parse_valid": parsed_gen.parse_valid,
            "code_length": len(code),
            "retry_mode": condition,
            "had_test_feedback": bool(test_feedback) and use_test_feedback,
            "had_classifier_hint": bool(classifier_hint),
            "mismatch_critique": critique_info.get("critique") or None,
            "mismatch_variant": critique_info.get("variant"),
            "mismatch_no_mismatch": critique_info.get("no_mismatch", False),
            "mismatch_truncated": critique_info.get("truncated", False),
            "mismatch_prescriptive": critique_info.get("prescriptive", False),
            "critique_skipped_missing_fields": critique_info.get("skipped_missing_fields", False),
        })

        # Track best
        if passed or best_ev is None:
            best_ev = exec_result
            best_parsed_gen = parsed_gen
            best_code = code
            best_parse_exec = parse_exec
            best_parse_fmt = parse_fmt
            best_parse_rec = parse_rec
            best_raw = raw_response

        prev_code = code
        prev_raw = raw_response

        if passed:
            _log.info("retry_v2 %s: PASS at attempt %d", cid, k)
            break

    # ── Final classification on best result ──
    parsed_gen = best_parsed_gen
    exec_result = best_ev
    code = best_code
    raw_response = best_raw
    parse_exec = best_parse_exec
    parse_fmt = best_parse_fmt
    parse_rec = best_parse_rec

    artifact = normalize_generation_v2(parsed_gen, case, "baseline_v2")

    if parsed_gen.parse_status == "success":
        classifier_result, classify_eid = classify_case(
            artifact, case, code, config, logger, last_parent_eid, condition, cid)
    else:
        classifier_result = ClassifierResultV2()
        classifier_result.parse_error = f"skipped: parse_status={parsed_gen.parse_status}"
        classify_eid = last_parent_eid

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

    ev = assemble_v2_result(
        exec_result=exec_result, artifact=artifact,
        classifier=classifier_result, signals=signals,
        case=case, condition=condition, model=model,
    )

    ev["num_attempts"] = len(trajectory)
    ev["trajectory"] = trajectory
    ev["retry_passed_at"] = next(
        (t["attempt"] for t in trajectory if t["pass"]), None
    )
    ev["retry_mode"] = condition

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
    }

    elapsed = time.monotonic() - t0

    parsed_compat = {
        "code": code,
        "reasoning": f"Root cause: {artifact.normalized_root_cause}\n"
                     f"Fix strategy: {artifact.normalized_fix_strategy}",
        "parse_error": parsed_gen.parse_error,
        "_raw_fallback": False,
        "data_lineage": ["raw_output_received", "parser_v2", "retry_v2"],
    }

    last_eid = classify_eid
    end_eid = logger.end_case(
        cid, condition=condition, raw_ev=ev,
        runtime_ms=round(elapsed * 1000),
        parent_event_id=last_eid,
    )
    logger.log_run(
        cid, condition, prompt, raw_response, parsed_compat,
        canonical_event_id=end_eid,
    )

    return cid, condition, ev
