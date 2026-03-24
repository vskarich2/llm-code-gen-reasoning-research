"""Execution logic for T3 benchmark runs.

Single-condition runs, repair loop, prompt building, logging.
Extracted from runner.py for single-responsibility.
"""

import json
import logging
from pathlib import Path

_exec_log = logging.getLogger("t3.execution")

from llm import call_model, get_model_config
from parse import parse_model_response
from evaluator import evaluate_output
from prompts import build_base_prompt
from nudges.router import (
    apply_diagnostic, apply_guardrail, apply_guardrail_strict,
    apply_counterfactual, apply_reason_then_act, apply_self_check,
    apply_counterfactual_check, apply_test_driven,
    get_operator_names,
)

BASE_DIR = Path(__file__).parent


# ============================================================
# PROMPT BUILDING
# ============================================================

def build_prompt(case: dict, condition: str) -> tuple[str, str | None]:
    """Return (prompt, operator_used) for a condition."""
    code_files = case["code_files_contents"]
    base = build_base_prompt(case["task"], code_files)
    case_id = case["id"]
    hard = case.get("hard_constraints", [])
    ops = get_operator_names(case_id)

    if condition == "baseline":
        return base, None
    elif condition == "diagnostic":
        return apply_diagnostic(case_id, base), ops.get("diagnostic")
    elif condition == "guardrail":
        return apply_guardrail(case_id, base), ops.get("guardrail")
    elif condition == "guardrail_strict":
        return apply_guardrail_strict(case_id, base, hard), "STRICT+" + (ops.get("guardrail") or "HARD_ONLY")
    elif condition == "counterfactual":
        return apply_counterfactual(case_id, base), ops.get("counterfactual")
    elif condition == "reason_then_act":
        return apply_reason_then_act(case_id, base), ops.get("reason_then_act")
    elif condition == "self_check":
        return apply_self_check(case_id, base), ops.get("self_check")
    elif condition == "counterfactual_check":
        return apply_counterfactual_check(case_id, base), ops.get("counterfactual_check")
    elif condition == "test_driven":
        return apply_test_driven(case_id, base), ops.get("test_driven")
    elif condition == "repair_loop":
        return apply_diagnostic(case_id, base), "REPAIR_LOOP"
    # SCM conditions
    elif condition == "scm_descriptive":
        from scm_prompts import build_scm_descriptive
        return build_scm_descriptive(base, case_id), "SCM_DESCRIPTIVE"
    elif condition == "scm_constrained":
        from scm_prompts import build_scm_constrained
        return build_scm_constrained(base, case_id), "SCM_CONSTRAINED"
    elif condition == "scm_constrained_evidence":
        from scm_prompts import build_scm_constrained_evidence
        return build_scm_constrained_evidence(base, case_id), "SCM_EVIDENCE"
    elif condition == "scm_constrained_evidence_minimal":
        from scm_prompts import build_scm_constrained_evidence_minimal
        return build_scm_constrained_evidence_minimal(base, case_id), "SCM_EVIDENCE_MIN"
    elif condition == "evidence_only":
        from scm_prompts import build_evidence_only
        return build_evidence_only(base, case_id), "EVIDENCE_ONLY"
    elif condition == "length_matched_control":
        from scm_prompts import build_length_matched_control
        return build_length_matched_control(base, case_id), "LENGTH_CONTROL"
    # Reasoning interface conditions
    elif condition == "structured_reasoning":
        from reasoning_prompts import build_structured_reasoning
        return build_structured_reasoning(base), "STRUCTURED_REASONING"
    elif condition == "free_form_reasoning":
        from reasoning_prompts import build_free_form_reasoning
        return build_free_form_reasoning(base), "FREE_FORM_REASONING"
    elif condition == "branching_reasoning":
        from reasoning_prompts import build_branching_reasoning
        return build_branching_reasoning(base), "BRANCHING_REASONING"
    elif condition == "contract_gated":
        # Contract-gated uses its own multi-step flow — prompt built inside run_contract_gated
        return base, "CONTRACT_GATED"
    elif condition == "leg_reduction":
        # LEG-reduction uses its own prompt — built inside run_leg_reduction
        return base, "LEG_REDUCTION"
    else:
        raise ValueError(f"Unknown condition: {condition}")


# ============================================================
# LIVE METRICS EVENT EMISSION
# ============================================================

_ablation_events_path: Path | None = None
_ablation_trial: int | None = None
_ablation_run_id: str | None = None


def set_ablation_context(events_path: Path | None, trial: int | None, run_id: str | None):
    """Set ablation context for event emission. Called from runner before evaluations."""
    global _ablation_events_path, _ablation_trial, _ablation_run_id
    _ablation_events_path = events_path
    _ablation_trial = trial
    _ablation_run_id = run_id


def _emit_metrics_event(case: dict, model: str, condition: str, ev: dict,
                        elapsed_seconds: float | None = None) -> None:
    """Emit a live metrics event.

    In ablation mode (events_path set): writes to per-run events.jsonl via emit_event().
    In legacy mode: writes to old shared events.jsonl if dashboard is running.
    """
    if _ablation_events_path is not None:
        # Ablation mode: strict event emission with schema validation
        from live_metrics import emit_event
        alignment = ev.get("alignment", {})
        emit_event({
            "case_id": case["id"],
            "model": model,
            "condition": condition,
            "trial": _ablation_trial,
            "run_id": _ablation_run_id,
            "pass": ev.get("pass", False),
            "score": ev.get("score", 0),
            "reasoning_correct": ev.get("reasoning_correct"),
            "code_correct": ev.get("code_correct"),
            "failure_type": ev.get("failure_type"),
            "category": alignment.get("category"),
            "num_attempts": ev.get("num_attempts", 1),
            "elapsed_seconds": elapsed_seconds,
        }, _ablation_events_path)
        return

    # Legacy mode: old emit_event path (for non-ablation runs)
    try:
        from live_metrics import EVENTS_PATH
        events_path = Path(__file__).parent / "logs" / "events.jsonl"
        if events_path.exists() or events_path.parent.exists():
            from live_metrics import emit_event as _legacy_emit
            alignment = ev.get("alignment", {})
            # Legacy events don't have trial/run_id — skip strict validation
            event = {
                "case_id": case["id"],
                "model": model,
                "condition": condition,
                "pass": ev.get("pass", False),
                "score": ev.get("score", 0),
                "reasoning_correct": ev.get("reasoning_correct"),
                "code_correct": ev.get("code_correct"),
                "failure_type": ev.get("failure_type"),
                "category": alignment.get("category"),
                "num_attempts": ev.get("num_attempts", 1),
                "elapsed_seconds": elapsed_seconds,
            }
            # In legacy mode, write without strict schema validation
            import json, os
            from datetime import datetime
            event["timestamp"] = datetime.now().isoformat()
            line = json.dumps(event, default=str) + "\n"
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        _exec_log.warning("_emit_metrics_event failed: %s: %s", type(e).__name__, e)


# ============================================================
# SINGLE RUN
# ============================================================

def _build_parsed_response(parse_result: dict, raw_output: str) -> dict:
    """Attach raw_output and ensure _raw_fallback is always present."""
    parse_result["raw_output"] = raw_output
    parse_result.setdefault("_raw_fallback", False)
    parse_result.setdefault("parse_error", None)
    parse_result.setdefault("reasoning", "")
    parse_result.setdefault("code", "")
    return parse_result


def _attempt_and_evaluate(case: dict, model: str, prompt: str) -> tuple[str, dict, dict]:
    """Single LLM call → parse once → evaluate. Returns (raw_output, parsed, eval)."""
    raw_output = call_model(prompt, model=model)
    parsed = _build_parsed_response(parse_model_response(raw_output), raw_output)
    ev = evaluate_output(case, parsed)
    return raw_output, parsed, ev


def run_single(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    """Run a single (case, condition) pair. Returns (case_id, condition, eval)."""
    t0 = __import__("time").monotonic()
    prompt, op_used = build_prompt(case, condition)
    raw_output, parsed, ev = _attempt_and_evaluate(case, model, prompt)

    ev["operator_used"] = op_used
    ev["condition"] = condition
    ev["_raw_fallback"] = parsed.get("_raw_fallback", False)
    # alignment is computed inside evaluate_output by the LLM classifier

    write_log(case["id"], condition, model, prompt, raw_output, parsed, ev)
    _emit_metrics_event(case, model, condition, ev, elapsed_seconds=round(__import__("time").monotonic() - t0, 2))
    return case["id"], condition, ev


# ============================================================
# REPAIR LOOP
# ============================================================

def run_repair_loop(case: dict, model: str) -> tuple[str, str, dict]:
    """Attempt 1 with diagnostic. If fails, attempt 2 with error feedback."""
    t0 = __import__("time").monotonic()
    attempts = []

    # Attempt 1
    prompt, _ = build_prompt(case, "repair_loop")
    raw_output, parsed, ev = _attempt_and_evaluate(case, model, prompt)
    attempts.append({"attempt": 1, "pass": ev["pass"], "score": ev["score"],
                     "reasons": ev.get("reasons", [])})

    if ev["pass"]:
        ev.update(operator_used="REPAIR_LOOP", condition="repair_loop",
                  attempts=attempts, num_attempts=1, final_pass=True)
        # alignment computed inside evaluate_output
        write_log(case["id"], "repair_loop", model, prompt, raw_output, parsed, ev)
        _emit_metrics_event(case, model, "repair_loop", ev, elapsed_seconds=round(__import__("time").monotonic() - t0, 2))
        return case["id"], "repair_loop", ev

    # Attempt 2: feed errors back
    error_reasons = "; ".join(ev.get("reasons", [])[:3])
    repair_prompt = prompt + f"\n\nYour previous attempt FAILED with:\n{error_reasons}\n\nFix and return corrected code."
    raw_2, parsed_2, ev2 = _attempt_and_evaluate(case, model, repair_prompt)
    attempts.append({"attempt": 2, "pass": ev2["pass"], "score": ev2["score"],
                     "reasons": ev2.get("reasons", [])})

    ev2.update(operator_used="REPAIR_LOOP", condition="repair_loop",
               attempts=attempts, num_attempts=2, final_pass=ev2["pass"])
    # alignment computed inside evaluate_output
    write_log(case["id"], "repair_loop", model, repair_prompt, raw_2, parsed_2, ev2)
    _emit_metrics_event(case, model, "repair_loop", ev2, elapsed_seconds=round(__import__("time").monotonic() - t0, 2))
    return case["id"], "repair_loop", ev2


# ============================================================
# CONTRACT-GATED EXECUTION
# ============================================================

def run_contract_gated(case: dict, model: str) -> tuple[str, str, dict]:
    """Multi-step CGE: elicit contract → generate code → gate → retry → eval."""
    import logging
    from contract import (
        parse_contract, build_contract_prompt,
        build_code_from_contract_prompt, build_retry_prompt,
    )
    from diff_gate import validate as gate_validate

    cid = case["id"]
    code_files = case["code_files_contents"]
    task = case["task"]
    _log = logging.getLogger("t3.cge")

    # Reference code for must_not_change comparison
    ref_code = "\n\n".join(code_files.values())

    # Step 1: Elicit contract (raw=True to avoid JSON output instruction override)
    contract_prompt = build_contract_prompt(task, code_files)
    contract_raw = call_model(contract_prompt, model=model, raw=True)
    contract = parse_contract(contract_raw)

    if contract is None:
        # Fallback: standard code gen, no gate
        _log.warning("Contract parse failed for %s — falling back to standard", cid)
        return _fallback_run(case, model, contract_raw)

    contract_verifiable = contract.get("_verifiable", False)

    # Step 2: Generate code conditioned on contract
    code_prompt = build_code_from_contract_prompt(task, code_files, contract)
    code_raw = call_model(code_prompt, model=model)
    parsed_code = parse_model_response(code_raw)

    # Step 3: Gate validation
    candidate_code = parsed_code["code"] if isinstance(parsed_code["code"], str) else ""
    gate_1 = gate_validate(contract, candidate_code, ref_code)
    gate_results = [gate_1]

    num_attempts = 1
    final_code_raw = code_raw

    if not gate_1["valid"]:
        # Step 4: Retry with violations
        _log.info("Gate failed for %s (%d violations) — retrying", cid, len(gate_1["violations"]))
        retry_prompt = build_retry_prompt(task, code_files, contract, gate_1["violations"])
        retry_raw = call_model(retry_prompt, model=model)
        parsed_retry = parse_model_response(retry_raw)
        retry_code = parsed_retry["code"] if isinstance(parsed_retry["code"], str) else ""

        gate_2 = gate_validate(contract, retry_code, ref_code)
        gate_results.append(gate_2)
        num_attempts = 2
        final_code_raw = retry_raw

    # Step 5: ALWAYS run exec evaluation
    final_parsed = _build_parsed_response(parse_model_response(final_code_raw), final_code_raw)
    ev = evaluate_output(case, final_parsed)

    # Assemble result
    final_gate = gate_results[-1]
    ev["operator_used"] = "CONTRACT_GATED"
    ev["condition"] = "contract_gated"
    ev["cge_executed"] = True
    ev["contract"] = contract
    ev["contract_parse_error"] = contract.get("_parse_error")
    ev["contract_verifiable"] = contract_verifiable
    ev["contract_satisfied"] = final_gate["valid"]
    ev["_unknown_effects"] = contract.get("_unknown_effects", [])
    ev["_unresolvable_orderings"] = contract.get("_unresolvable_orderings", [])
    ev["gate_results"] = gate_results
    ev["num_attempts"] = num_attempts
    # alignment computed inside evaluate_output

    parsed_final = parse_model_response(final_code_raw)
    write_log(cid, "contract_gated", model, code_prompt, final_code_raw, parsed_final, ev)
    _emit_metrics_event(case, model, "contract_gated", ev)
    return cid, "contract_gated", ev


def _fallback_run(case, model, contract_raw):
    """Fallback when contract parsing fails — CGE DID NOT EXECUTE."""
    parsed = _build_parsed_response(parse_model_response(contract_raw), contract_raw)
    ev = evaluate_output(case, parsed)
    ev["operator_used"] = "CONTRACT_GATED"
    ev["condition"] = "contract_gated"
    ev["cge_executed"] = False
    ev["contract"] = None
    ev["contract_parse_error"] = "failed to parse contract"
    ev["contract_verifiable"] = False
    ev["contract_satisfied"] = False
    ev["gate_results"] = []
    ev["num_attempts"] = 1
    write_log(case["id"], "contract_gated", model, "", contract_raw, parsed, ev)
    _emit_metrics_event(case, model, "contract_gated", ev)
    return case["id"], "contract_gated", ev


# ============================================================
# LEG-REDUCTION (intra-call self-correction)
# ============================================================

def run_leg_reduction(case: dict, model: str) -> tuple[str, str, dict]:
    """Run LEG-reduction condition: plan → code → verify → self-correct (one call).

    Uses a specialized prompt that instructs the model to generate a plan,
    write code, verify plan→code consistency, and self-correct — all in a
    single response.

    Returns (case_id, condition, eval_dict).
    """
    from leg_reduction import build_leg_reduction_prompt, parse_leg_reduction_output

    cid = case["id"]
    code_files = case["code_files_contents"]
    task = case["task"]

    # Build prompt and make ONE LLM call (raw=True, prompt has its own schema)
    prompt = build_leg_reduction_prompt(task, code_files)
    raw_output = call_model(prompt, model=model, raw=True)

    # Parse with strict schema validation
    lr_parsed = parse_leg_reduction_output(raw_output)

    # Build canonical ParsedResponse — same structure as baseline path
    parsed = {
        "code": lr_parsed["code"],
        "reasoning": lr_parsed["bug_diagnosis"],
        "raw_output": raw_output,
        "parse_error": lr_parsed["parse_error"],
        "_raw_fallback": False,
    }

    # Evaluate via standard pipeline — no re-parsing
    ev = evaluate_output(case, parsed)

    # Attach LEG-reduction metadata to eval result
    ev["operator_used"] = "LEG_REDUCTION"
    ev["condition"] = "leg_reduction"
    ev["leg_reduction"] = {
        "valid_schema": lr_parsed["valid"],
        "parse_error": lr_parsed["parse_error"],
        "validation_errors": lr_parsed.get("validation_errors", []),
        "bug_diagnosis": lr_parsed["bug_diagnosis"],
        "plan_steps": lr_parsed["plan_steps"],
        "revision_history": lr_parsed.get("revision_history", []),
        "verification": lr_parsed["verification"],
        "internal_revisions": lr_parsed["internal_revisions"],
        "all_steps_verified": lr_parsed["all_steps_verified"],
        "exceeded_max_revisions": lr_parsed["leg_reduction_exceeded_max_revisions"],
        "plan_step_count": len(lr_parsed["plan_steps"]),
        "verified_step_count": sum(
            1 for v in lr_parsed["verification"] if v.get("status") == "PASS"
        ),
        "revision_count": len(lr_parsed.get("revision_history", [])),
    }
    # alignment computed inside evaluate_output

    # Build a parsed dict compatible with write_log
    log_parsed = {
        "reasoning": lr_parsed["bug_diagnosis"],
        "code": lr_parsed["code"],
        "parse_error": lr_parsed["parse_error"],
    }

    write_log(cid, "leg_reduction", model, prompt, raw_output, log_parsed, ev)
    _emit_metrics_event(case, model, "leg_reduction", ev)
    return cid, "leg_reduction", ev


# ============================================================
# LOGGING — RunLogger class (no shared global state)
# ============================================================

class RunLogger:
    """Isolated logger for a single experiment run.

    Owns its file paths, run identity, write counts, and closed state.
    Writing after close, model mismatch, or run_id mismatch raises RuntimeError.

    Thread-safe: writes are serialized via an internal lock.
    """

    def __init__(self, log_path: Path, prompts_path: Path, responses_path: Path,
                 model: str, run_id: str):
        import threading
        self.log_path = log_path
        self.prompts_path = prompts_path
        self.responses_path = responses_path
        self.model = model
        self.run_id = run_id
        self.closed = False
        self.writes_attempted = 0
        self.writes_failed = 0
        self._lock = threading.Lock()

    def _check_invariants(self, case_id: str, condition: str, model: str):
        """Check all write preconditions. Raises on any violation."""
        if self.closed:
            raise RuntimeError(
                f"LOG WRITE AFTER CLOSE: attempted write for {case_id}/{condition} "
                f"to closed logger ({self.log_path}). This is a run isolation bug."
            )
        if model != self.model:
            raise RuntimeError(
                f"LOG MODEL MISMATCH: logger was created for model '{self.model}' "
                f"but write received model '{model}'. This is a cross-run contamination bug."
            )

    def write(self, case_id, condition, model, prompt, raw_output, parsed, ev):
        """Write one call's data to all three log files. Thread-safe."""
        import threading, time as _time
        tid = threading.current_thread().name
        _exec_log.debug("LOG_LOCK_WAIT thread=%s case=%s cond=%s", tid, case_id, condition)
        t0 = _time.monotonic()
        with self._lock:
            waited = _time.monotonic() - t0
            if waited > 0.1:
                _exec_log.warning("LOG_LOCK_CONTENTION thread=%s case=%s waited=%.3fs",
                                   tid, case_id, waited)
            self._write_locked(case_id, condition, model, prompt, raw_output, parsed, ev)

    def _write_locked(self, case_id, condition, model, prompt, raw_output, parsed, ev):
        self._check_invariants(case_id, condition, model)

        parse_error = parsed.get("parse_error")
        if parse_error and "SEVERE" in str(parse_error):
            _exec_log.warning(
                "SEVERE parse issue for %s/%s: %s (response len=%d)",
                case_id, condition, parse_error, len(raw_output)
            )

        reasoning_text = parsed.get("reasoning") or ""
        code_text = parsed.get("code") or ""
        record = {
            "run_id": self.run_id,
            "case_id": case_id, "condition": condition, "model": model,
            "model_config": get_model_config(),
            "prompt_length": len(prompt),
            "raw_response_length": len(raw_output),
            "parsed": {
                "reasoning": reasoning_text[:200] if isinstance(reasoning_text, str) else str(reasoning_text)[:200],
                "code_length": len(code_text) if isinstance(code_text, str) else len(str(code_text)),
                "parse_error": parse_error,
                "_raw_fallback": parsed.get("_raw_fallback", False),
            },
            "execution": ev.get("execution", {}),
            "evaluation": {
                "pass": ev["pass"], "score": ev["score"],
                "reasoning_valid": ev.get("identified_correct_issue", False),
                "alignment": ev.get("alignment", {}),
                "num_attempts": ev.get("num_attempts"),
            },
        }

        prompt_record = {
            "run_id": self.run_id,
            "case_id": case_id, "condition": condition, "model": model,
            "prompt": prompt,
        }

        response_record = {
            "run_id": self.run_id,
            "case_id": case_id, "condition": condition, "model": model,
            "raw_response": raw_output,
        }

        for path, data in [
            (self.log_path, record),
            (self.prompts_path, prompt_record),
            (self.responses_path, response_record),
        ]:
            self.writes_attempted += 1
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, default=str) + "\n")
            except OSError as e:
                self.writes_failed += 1
                _exec_log.error(
                    "LOG WRITE FAILED for %s/%s to %s: %s",
                    case_id, condition, path, e
                )

    def write_summary(self, summary: dict):
        """Write a summary record to the metadata log. Injects run_id. Thread-safe."""
        with self._lock:
            if self.closed:
                raise RuntimeError(
                    f"LOG WRITE AFTER CLOSE: summary write to closed logger ({self.log_path})."
                )
            summary.setdefault("run_id", self.run_id)
            self.writes_attempted += 1
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(summary, default=str) + "\n")
            except OSError as e:
                self.writes_failed += 1
                _exec_log.error("SUMMARY WRITE FAILED to %s: %s", self.log_path, e)

    def get_stats(self) -> dict:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "log_path": str(self.log_path),
            "attempted": self.writes_attempted,
            "failed": self.writes_failed,
            "success_rate": (
                (self.writes_attempted - self.writes_failed) / self.writes_attempted
                if self.writes_attempted > 0 else 1.0
            ),
        }

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify run log integrity. Call at end of run.

        Returns (valid, reason). If valid=False, the run data should be
        discarded or marked INVALID.
        """
        if self.writes_failed > 0:
            return False, (
                f"RUN INVALID: {self.writes_failed}/{self.writes_attempted} log writes failed. "
                f"Data in {self.log_path} is INCOMPLETE."
            )
        if self.writes_attempted == 0:
            return False, (
                f"RUN INVALID: zero writes attempted. Logger was created but never used. "
                f"Log file {self.log_path} is EMPTY."
            )
        return True, f"OK: {self.writes_attempted} writes, 0 failures"

    def close(self):
        if self.closed:
            return  # idempotent
        self.closed = True
        _exec_log.info("RunLogger closed: run_id=%s, %s (%d writes, %d failed)",
                       self.run_id, self.log_path,
                       self.writes_attempted, self.writes_failed)


# Single active logger — enforced singleton with explicit lifecycle
_active_logger: RunLogger | None = None


def init_run_log(model: str, log_dir: Path | None = None) -> Path:
    """Create a RunLogger for this experiment run.

    Args:
        model: Model name for this run.
        log_dir: If provided, write log files to this directory with fixed names
                 (run.jsonl, run_prompts.jsonl, run_responses.jsonl).
                 If None, use legacy timestamped naming in logs/.

    Returns the log path. The logger is accessible via get_run_logger().
    Raises RuntimeError if a previous logger is still active.
    """
    global _active_logger

    if _active_logger is not None and not _active_logger.closed:
        raise RuntimeError(
            f"LOG BLEED PREVENTED: init_run_log('{model}') called while "
            f"previous logger is still active for model '{_active_logger.model}' "
            f"at {_active_logger.log_path}. Call close_run_log() first."
        )

    if log_dir is not None:
        # Ablation mode: fixed filenames in provided directory
        log_dir = Path(log_dir)
        log_path = log_dir / "run.jsonl"
        prompts_path = log_dir / "run_prompts.jsonl"
        responses_path = log_dir / "run_responses.jsonl"

        import uuid
        run_id = str(uuid.uuid4())[:8]
        _active_logger = RunLogger(log_path, prompts_path, responses_path, model, run_id)
        _exec_log.info("RunLogger created (ablation): run_id=%s, model=%s, log_dir=%s",
                       run_id, model, log_dir)
        return log_path

    # Legacy mode: timestamped filenames in logs/
    from datetime import datetime

    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)

    safe_model = model.replace("/", "_").replace("\\", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{safe_model}_{ts}"

    log_path = logs_dir / f"{stem}.jsonl"
    prompts_path = logs_dir / f"{stem}_prompts.jsonl"
    responses_path = logs_dir / f"{stem}_responses.jsonl"

    for p in [log_path, prompts_path, responses_path]:
        if p.exists():
            raise FileExistsError(
                f"Log file already exists: {p}\n"
                "Refusing to overwrite — wait 1 second or use a different model name."
            )

    import uuid
    run_id = str(uuid.uuid4())[:8]  # short unique ID per run
    _active_logger = RunLogger(log_path, prompts_path, responses_path, model, run_id)
    _exec_log.info("RunLogger created: run_id=%s, model=%s, log=%s", run_id, model, log_path)
    return log_path


def close_run_log():
    """Close the active logger. Must be called before init_run_log for a new model."""
    global _active_logger
    if _active_logger is not None:
        _active_logger.close()
    _active_logger = None


def get_run_logger() -> RunLogger:
    """Get the active RunLogger. Raises if none active."""
    if _active_logger is None or _active_logger.closed:
        raise RuntimeError(
            "No active RunLogger. Call init_run_log() before writing logs."
        )
    return _active_logger


def get_current_log_path() -> Path | None:
    """Backward compat — returns active log path or None."""
    if _active_logger and not _active_logger.closed:
        return _active_logger.log_path
    return None


def get_log_write_stats() -> dict:
    """Return log write statistics for the active logger."""
    if _active_logger:
        return _active_logger.get_stats()
    return {"attempted": 0, "failed": 0, "success_rate": 1.0}


def write_log(case_id, condition, model, prompt, raw_output, parsed, ev):
    """Write one call's data via the active RunLogger.

    Raises RuntimeError if no logger is active or if model doesn't match.
    """
    logger = get_run_logger()
    logger.write(case_id, condition, model, prompt, raw_output, parsed, ev)
