"""Centralized logging system for T3 benchmark experiments.

ONE module for ALL logging. No other code writes log files.
No other module constructs event dictionaries.

Two planes:
  - Control plane: OrchestratorLogger → experiment-level events.jsonl
  - Execution plane: RunLogger → per-run events.jsonl + calls/ + calls_flat/

Canonical event schema v7:
  - event_type: legacy value (for aggregate.py backward compat)
  - event_type_canonical: authoritative classification
  - 14 structured sections always present
  - Field membership defined solely by _build_canonical_and_extra()
  - Schema structure defined solely by emit_event()

IDs:
  - run_id: str — groups one (model, condition, trial)
  - trace_id: str (UUID hex) — groups one case execution
  - trajectory_id: str (UUID hex) — groups one linear execution segment
  - event_id: int (monotonic per file) — strict ordering within one events.jsonl
  - call_id: int (monotonic per run) — links to calls/{id}.json
"""

import hashlib
import json
import os
import tempfile
import uuid
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# CANONICAL EVENT TYPES
# ============================================================

VALID_CANONICAL_TYPES = frozenset({
    "llm_call",
    "execution_eval",
    "reasoning_eval",
    "pipeline_state",
    "error",
})

# Canonical types that REQUIRE parent_event_id to be non-null
PARENT_REQUIRED = frozenset({
    "llm_call",
    "execution_eval",
    "reasoning_eval",
    "error",
})

# Canonical types that REQUIRE an active trace_id
TRACE_REQUIRED = frozenset({
    "llm_call",
    "execution_eval",
    "reasoning_eval",
    "error",
})

# ============================================================
# PHASE ENUM (closed set)
# ============================================================

VALID_PHASES = frozenset({
    "generation",
    "classification",
    "evaluation",
    "case",
    "pipeline",
})

# ============================================================
# LEGACY COMPAT — event types aggregate.py reads
# ============================================================

VALID_LEGACY_EVENT_TYPES = frozenset({
    "orchestrator.start", "orchestrator.schedule", "orchestrator.worker_start",
    "orchestrator.worker_end", "orchestrator.worker_failed", "orchestrator.abort",
    "orchestrator.complete", "orchestrator.preflight_pass", "orchestrator.preflight_fail",
    "run.start", "run.end", "run.failed",
    "case.start", "case.end", "case.failed",
    "call.generate", "call.classify", "call.other",
    "parse.result", "execution.result",
    "metric.record",
    "validation.pass", "validation.fail",
    "pipeline_state",
})

CALL_EVENT_TYPES = frozenset({"call.generate", "call.classify", "call.other"})

_FSYNC_LEGACY_TYPES = frozenset({
    "run.start", "run.end", "run.failed",
    "case.failed", "case.end",
    "orchestrator.start", "orchestrator.complete", "orchestrator.abort",
    "orchestrator.worker_failed",
})

# ============================================================
# CASE HANDLE
# ============================================================

CaseHandle = namedtuple("CaseHandle", ["trace_id", "event_id"])


# ============================================================
# COMPATIBILITY MAPPING
# ============================================================

def resolve_legacy_event_type(
    event_type_canonical: str, phase: str | None, step: str | None
) -> str:
    """Map canonical event type to legacy event type string.

    Total function — returns a string for every input. Never returns null.
    phase is guaranteed valid by emit_event() validation before this is called.
    """
    if event_type_canonical == "llm_call":
        if phase == "classification":
            return "call.classify"
        if phase == "generation":
            return "call.generate"
        return "call.other"
    if event_type_canonical == "execution_eval":
        return "case.end"
    if event_type_canonical == "reasoning_eval":
        return "case.end"
    if event_type_canonical == "error":
        return "case.failed"
    if event_type_canonical == "pipeline_state":
        if step == "case_start":
            return "case.start"
        if step == "run_start":
            return "run.start"
        if step == "run_end":
            return "run.end"
        if step == "run_failed":
            return "run.failed"
        if step == "metric":
            return "metric.record"
        if step == "parse":
            return "parse.result"
        return "pipeline_state"
    return event_type_canonical


# ============================================================
# FILE WRITE HELPERS
# ============================================================

def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically: temp → flush → fsync → rename."""
    path = Path(path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_text_atomic(path: Path, text: str) -> None:
    """Write text atomically: temp → flush → fsync → rename."""
    path = Path(path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_events(events_path: Path) -> list[dict]:
    """Read all events from a JSONL file. Skip malformed lines."""
    events = []
    if not events_path.exists():
        return events
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


# ============================================================
# FLAT CALL RENDERER
# ============================================================

def render_call_flat(record: dict) -> str:
    """Render a call record as human-readable flat text."""
    call_id = record.get("call_id", 0)
    lines = [
        f"=== CALL {call_id:06d} ===",
        f"MODEL: {record.get('model', '?')}",
        f"PHASE: {record.get('phase', '?')}",
        f"CASE_ID: {record.get('case_id', '?')}",
        f"CONDITION: {record.get('condition', '?')}",
        f"TRIAL: {record.get('trial', '?')}",
        f"RUN_ID: {record.get('run_id', '?')}",
        f"TRACE_ID: {record.get('trace_id', '?')}",
        f"TIMESTAMP: {record.get('timestamp', '?')}",
        f"LATENCY_MS: {round(record.get('elapsed_seconds', 0) * 1000)}",
    ]
    if record.get("error"):
        lines.append(f"ERROR: {record['error']}")
    lines.append("")
    lines.append("--- PROMPT ---")
    lines.append(record.get("prompt_raw", ""))
    lines.append("")
    lines.append("--- RESPONSE ---")
    lines.append(record.get("response_raw", ""))
    lines.append("")
    return "\n".join(lines)


# ============================================================
# BASE LOGGER
# ============================================================

class BaseLogger:
    """Shared event-writing logic. Both planes inherit this."""

    def __init__(self, events_path: Path):
        self._events_path = Path(events_path)
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._events_file = open(self._events_path, "a", encoding="utf-8")
        self._event_counter = 0
        self._closed = False

    def _write_event(self, event: dict) -> int:
        """Assign event_id, write line, flush. Returns event_id.

        Validates legacy event_type is in VALID_LEGACY_EVENT_TYPES.
        """
        if self._closed:
            raise RuntimeError("Logger is closed")

        legacy_type = event.get("event_type")
        if legacy_type not in VALID_LEGACY_EVENT_TYPES:
            raise ValueError(f"Invalid legacy event_type: {legacy_type!r}")

        self._event_counter += 1
        event["event_id"] = self._event_counter

        line = json.dumps(event, default=str) + "\n"
        self._events_file.write(line)
        self._events_file.flush()

        if legacy_type in _FSYNC_LEGACY_TYPES:
            os.fsync(self._events_file.fileno())

        return self._event_counter

    def close(self) -> None:
        if not self._closed:
            self._events_file.close()
            self._closed = True


# ============================================================
# ORCHESTRATOR LOGGER (control plane)
# ============================================================

class OrchestratorLogger(BaseLogger):
    """Control plane logger. Created in orchestrator main process only."""

    def __init__(self, experiment_dir: Path):
        experiment_dir = Path(experiment_dir)
        experiment_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(experiment_dir / "events.jsonl")

    def log_event(self, event_type: str, payload: dict) -> int:
        return self._write_event({
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "run_id": None,
            "trace_id": None,
            "trial": None,
            "model": None,
            "condition": None,
            "case_id": None,
            "phase": "orchestrator",
            "payload": payload,
        })


# ============================================================
# RUN LOGGER (execution plane)
# ============================================================

class RunLogger(BaseLogger):
    """Execution plane logger with canonical event schema.

    Created LOCALLY inside each worker process.
    NEVER pickled. NEVER passed through ProcessPoolExecutor.

    All event emission goes through emit_event(). All other methods
    (log_call, end_case, start_case, fail_case, log_event, log_metric)
    are thin wrappers around emit_event().
    """

    def __init__(self, run_dir: Path, run_id: str,
                 model: str, condition: str | None, trial: int,
                 experiment_name: str | None = None):
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "calls").mkdir(exist_ok=True)
        (run_dir / "calls_flat").mkdir(exist_ok=True)

        super().__init__(run_dir / "events.jsonl")

        self._run_dir = run_dir
        self._run_id = run_id
        self._model = model
        self._condition = condition
        self._trial = trial
        self._experiment_name = experiment_name
        self._call_counter = 0

        # Trace state
        self._current_trace_id: str | None = None
        self._current_trajectory_id: str | None = None
        self._current_case_start_event_id: int | None = None
        self._trace_event_counter = 0

        write_json_atomic(run_dir / "metadata.json", {
            "run_id": run_id,
            "model": model,
            "condition": condition,
            "trial": trial,
            "experiment_name": experiment_name,
            "start_time": datetime.now().isoformat(),
        })

    # ============================================================
    # CANONICAL EVENT EMISSION — THE SINGLE ENTRY POINT
    # ============================================================

    def emit_event(
        self,
        event_type_canonical: str,
        *,
        # Context
        case_id: str | None = None,
        condition: str | None = None,
        attempt_idx: int | None = None,
        step: str | None = None,
        phase: str | None = None,
        node: str | None = None,
        edge: str | None = None,
        # Causal chain
        parent_event_id: int | None = None,
        # LLM call data
        call_id: int | None = None,
        llm_model: str | None = None,
        tokens_input_estimate: int | None = None,
        tokens_output_estimate: int | None = None,
        latency_ms: int | None = None,
        call_status: str | None = None,
        error_type: str | None = None,
        request_path: str | None = None,
        response_path: str | None = None,
        flat_path: str | None = None,
        # Prompt provenance
        prompt_assembly: dict | None = None,
        # Execution results (from raw_ev extraction)
        raw_ev: dict | None = None,
        runtime_ms: float | None = None,
        # Direct execution/reasoning (for events without raw_ev)
        exec_error: str | None = None,
        # Artifacts
        code_path: str | None = None,
        # Metrics
        cumulative_cost: float | None = None,
        # Escape hatch
        extra: dict | None = None,
    ) -> int:
        """Emit one canonical event to events.jsonl. Returns event_id.

        This is the ONLY function that calls _write_event().
        All other methods are thin wrappers.

        Field membership for execution/reasoning/extra sections is defined
        solely by _build_canonical_and_extra() when raw_ev is provided.
        emit_event() inserts those returned dicts by reference — it does NOT
        read raw_ev directly for any field in those sections.
        """
        if self._closed:
            raise RuntimeError("Logger is closed")

        # Validate canonical type
        if event_type_canonical not in VALID_CANONICAL_TYPES:
            raise RuntimeError(
                f"Invalid canonical event type: {event_type_canonical!r}. "
                f"Must be one of {sorted(VALID_CANONICAL_TYPES)}."
            )

        # Validate phase (closed enum)
        if phase is not None and phase not in VALID_PHASES:
            raise RuntimeError(
                f"Invalid phase: {phase!r}. Must be one of {sorted(VALID_PHASES)}."
            )

        # Enforce parent_event_id requirement
        if event_type_canonical in PARENT_REQUIRED and parent_event_id is None:
            raise RuntimeError(
                f"parent_event_id is required for event_type_canonical={event_type_canonical!r} "
                f"but was None. case_id={case_id}, condition={condition}. "
                f"Caller MUST pass the event_id of the causal predecessor."
            )

        # Enforce trace_id requirement
        if event_type_canonical in TRACE_REQUIRED and self._current_trace_id is None:
            raise RuntimeError(
                f"trace_id is None but event_type_canonical={event_type_canonical!r} "
                f"requires an active trace. Call start_case() first."
            )

        # Increment trace event counter
        if self._current_trace_id is not None:
            self._trace_event_counter += 1

        effective_condition = condition if condition is not None else self._condition

        # --- Extract execution/reasoning/extra from raw_ev if provided ---
        if raw_ev is not None:
            exec_sec, reas_sec, extra_sec, consumed = self._build_canonical_and_extra(
                raw_ev, runtime_ms
            )
            self._enforce_no_overlap(consumed, extra_sec)
        else:
            exec_sec = {
                "ran": None, "passed": None, "score": None,
                "tests_run": None, "tests_passed": None,
                "runtime_ms": runtime_ms, "error": exec_error,
            }
            reas_sec = {
                "evaluated": False, "reasoning_correct": None,
                "failure_type": None, "confidence": None,
            }
            extra_sec = extra or {}

        # --- Build prompt section ---
        pa = prompt_assembly or {}
        prompt_sec = {
            "prompt_family": pa.get("prompt_family"),
            "prompt_name": pa.get("prompt_name"),
            "prompt_version": pa.get("prompt_version"),
            "prompt_hash": pa.get("prompt_hash"),
            "template_id": pa.get("template_id"),
            "variables_hash": pa.get("variables_hash"),
            "tokens_input_estimate": tokens_input_estimate,
        }

        # --- Build llm_call section ---
        llm_sec = {
            "call_id": call_id,
            "provider": "openai",
            "model": llm_model,
            "temperature": self._get_model_temperature(llm_model),
            "max_tokens": self._get_model_max_tokens(llm_model),
            "tokens_output_estimate": tokens_output_estimate,
            "latency_ms": latency_ms,
            "status": call_status,
            "error_type": error_type,
            "request_path": request_path,
            "response_path": response_path,
            "flat_path": flat_path,
        }

        # --- Compute legacy event type ---
        legacy_type = resolve_legacy_event_type(event_type_canonical, phase, step)

        # --- Build compat payload for aggregate.py ---
        compat_payload = self._build_compat_payload(
            event_type_canonical, exec_sec, reas_sec, llm_sec, extra_sec
        )

        # --- Assemble full record ---
        record = {
            # Legacy flat keys (aggregate.py reads these)
            "event_type": legacy_type,
            "event_type_canonical": event_type_canonical,
            "model": self._model,
            "condition": effective_condition,
            "case_id": case_id,
            "trace_id": self._current_trace_id,
            "trial": self._trial,
            "phase": phase,
            "payload": compat_payload,
            # Canonical structured sections
            "schema_version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "run": {
                "run_id": self._run_id,
                "experiment_name": self._experiment_name,
                "trial": self._trial,
                "model": self._model,
            },
            "trace": {
                "trace_id": self._current_trace_id,
                "parent_event_id": parent_event_id,
                "trajectory_id": self._current_trajectory_id,
                "event_index_within_trace": (
                    self._trace_event_counter if self._current_trace_id else None
                ),
            },
            "context": {
                "case_id": case_id,
                "condition": effective_condition,
                "attempt_idx": attempt_idx,
                "step": step,
                "phase": phase,
                "node": node,
                "edge": edge,
            },
            "prompt": prompt_sec,
            "llm_call": llm_sec,
            "execution": exec_sec,
            "reasoning": reas_sec,
            "artifacts": {
                "code_path": code_path,
                "diff_path": None,
                "stdout_path": None,
                "stderr_path": None,
            },
            "metrics": {
                "cumulative_calls": self._call_counter,
                "cumulative_cost": cumulative_cost,
            },
            "extra": extra_sec,
        }

        return self._write_event(record)

    # ============================================================
    # EXTRACTION — FIELD MEMBERSHIP DEFINITION
    # ============================================================

    def _build_canonical_and_extra(
        self, raw_ev: dict, runtime_ms: float | None
    ) -> tuple[dict, dict, dict, set]:
        """Extract canonical sections from raw_ev.

        Returns (execution_section, reasoning_section, extra_section, consumed_keys).

        consumed_keys: set of top-level raw_ev keys that were read.
        Each canonical field reads from exactly one top-level key (atomic source).
        extra = all top-level keys NOT in consumed_keys, with their values.
        """
        consumed_keys: set[str] = set()

        # --- execution section ---
        # Source top-level keys: "execution", "pass", "score"
        exec_data = raw_ev.get("execution", {})
        consumed_keys.add("execution")
        execution_section = {
            "ran": exec_data.get("ran"),               # from "execution"
            "passed": raw_ev.get("pass"),              # from "pass"
            "score": raw_ev.get("score"),              # from "score"
            "tests_run": exec_data.get("total_tests"), # from "execution"
            "tests_passed": exec_data.get("tests_passed"),  # from "execution"
            "runtime_ms": runtime_ms,                  # from caller parameter
            "error": exec_data.get("error"),           # from "execution"
        }
        consumed_keys.update({"pass", "score"})

        # --- reasoning section ---
        # Source top-level keys: "reasoning_correct", "failure_type", "confidence"
        reasoning_section = {
            "evaluated": raw_ev.get("reasoning_correct") is not None,  # from "reasoning_correct"
            "reasoning_correct": raw_ev.get("reasoning_correct"),       # from "reasoning_correct"
            "failure_type": raw_ev.get("failure_type"),                 # from "failure_type"
            "confidence": raw_ev.get("confidence"),                     # from "confidence"
        }
        consumed_keys.update({"reasoning_correct", "failure_type", "confidence"})

        # --- keys consumed for context (used by emit_event, not in execution/reasoning) ---
        consumed_keys.update({"condition", "operator_used", "num_attempts", "alignment"})

        # --- extra: every top-level key NOT consumed ---
        extra_section = {k: v for k, v in raw_ev.items() if k not in consumed_keys}

        return execution_section, reasoning_section, extra_section, consumed_keys

    def _enforce_no_overlap(self, consumed_keys: set, extra_section: dict) -> None:
        """Raise RuntimeError if any key appears in both consumed and extra.

        Runs BEFORE event emission. Violation halts the process.
        """
        overlap = consumed_keys & set(extra_section.keys())
        if overlap:
            raise RuntimeError(
                f"SCHEMA INVARIANT VIOLATION: top-level keys {overlap} appear in both "
                f"consumed_keys and extra_section. Fix _build_canonical_and_extra()."
            )

    # ============================================================
    # COMPAT PAYLOAD BUILDER
    # ============================================================

    def _build_compat_payload(
        self, canonical_type: str,
        exec_sec: dict, reas_sec: dict, llm_sec: dict, extra_sec: dict,
    ) -> dict:
        """Build legacy payload dict for aggregate.py backward compatibility."""
        if canonical_type == "llm_call":
            return {
                "call_id": llm_sec.get("call_id"),
                "latency_ms": llm_sec.get("latency_ms"),
                "prompt_length": llm_sec.get("tokens_input_estimate"),
                "response_length": llm_sec.get("tokens_output_estimate"),
                "error": llm_sec.get("error_type"),
            }
        if canonical_type in ("execution_eval", "reasoning_eval"):
            return {
                "pass": exec_sec.get("passed"),
                "score": exec_sec.get("score"),
                "failure_type": reas_sec.get("failure_type"),
                **extra_sec,
            }
        if canonical_type == "error":
            return {"error": exec_sec.get("error")}
        return {}

    # ============================================================
    # CONFIG HELPERS
    # ============================================================

    def _get_model_temperature(self, model_name: str | None) -> float | None:
        if model_name is None:
            return None
        try:
            from experiment_config import get_config
            spec = get_config().get_generation_model(model_name)
            return spec.temperature
        except Exception:
            try:
                from experiment_config import get_config
                config = get_config()
                if model_name == config.models.evaluator.name:
                    return config.models.evaluator.temperature
            except Exception:
                pass
        return None

    def _get_model_max_tokens(self, model_name: str | None) -> int | None:
        if model_name is None:
            return None
        try:
            from experiment_config import get_config
            spec = get_config().get_generation_model(model_name)
            return spec.max_tokens
        except Exception:
            try:
                from experiment_config import get_config
                config = get_config()
                if model_name == config.models.evaluator.name:
                    return config.models.evaluator.max_tokens
            except Exception:
                pass
        return None

    # ============================================================
    # CASE LIFECYCLE (thin wrappers around emit_event)
    # ============================================================

    def start_case(self, case_id: str) -> CaseHandle:
        """Begin case execution. Creates trace_id + trajectory_id.

        Returns CaseHandle(trace_id, event_id). Position [0] is trace_id
        for backward compat with unpacking.
        """
        self._current_trace_id = uuid.uuid4().hex
        self._current_trajectory_id = uuid.uuid4().hex
        self._current_case_start_event_id = None
        self._trace_event_counter = 0

        event_id = self.emit_event(
            "pipeline_state",
            case_id=case_id,
            phase="case",
            step="case_start",
        )
        self._current_case_start_event_id = event_id
        return CaseHandle(trace_id=self._current_trace_id, event_id=event_id)

    def end_case(self, case_id: str, *,
                 condition: str | None = None,
                 raw_ev: dict | None = None,
                 runtime_ms: float | None = None,
                 parent_event_id: int | None = None,
                 extra: dict | None = None) -> int:
        """End case. Emits execution_eval event. Clears trace state.

        Callers pass raw_ev (the full evaluation dict). Field extraction
        happens inside emit_event() via _build_canonical_and_extra().
        """
        event_id = self.emit_event(
            "execution_eval",
            case_id=case_id,
            condition=condition,
            phase="case",
            step="case_end",
            parent_event_id=parent_event_id,
            raw_ev=raw_ev,
            runtime_ms=runtime_ms,
            extra=extra,
        )
        self._current_trace_id = None
        self._current_trajectory_id = None
        self._current_case_start_event_id = None
        return event_id

    def fail_case(self, case_id: str, error: str, *,
                  condition: str | None = None,
                  parent_event_id: int | None = None) -> int:
        """Record case failure. Emits error event. Clears trace state."""
        event_id = self.emit_event(
            "error",
            case_id=case_id,
            condition=condition,
            phase="case",
            step="case_failed",
            parent_event_id=parent_event_id,
            exec_error=error,
        )
        self._current_trace_id = None
        self._current_trajectory_id = None
        self._current_case_start_event_id = None
        return event_id

    def new_trajectory(self) -> str:
        """Create a new trajectory within the current trace.

        Called at control-flow boundaries: before retry generation,
        before fallback paths, before loop iterations k>0.
        Returns the new trajectory_id.
        """
        if self._current_trace_id is None:
            raise RuntimeError("new_trajectory() requires an active trace")
        self._current_trajectory_id = uuid.uuid4().hex
        return self._current_trajectory_id

    # ============================================================
    # LLM CALL LOGGING (thin wrapper)
    # ============================================================

    def log_call(self, model: str, prompt: str, response: str,
                 elapsed_seconds: float, case_id: str, phase: str,
                 parent_event_id: int,
                 condition: str | None = None,
                 error: str | None = None,
                 prompt_assembly: dict | None = None) -> int:
        """Log one LLM call. Returns event_id (NOT call_id).

        Writes three outputs:
        1. calls/{call_id:06d}.json (full prompt/response)
        2. calls_flat/{call_id:06d}_{phase}.txt (human-readable)
        3. events.jsonl canonical event (via emit_event)
        """
        self._call_counter += 1
        call_id = self._call_counter
        effective_condition = condition if condition is not None else self._condition

        # Build call file record
        record = {
            "call_id": call_id,
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "phase": phase,
            "case_id": case_id,
            "condition": effective_condition,
            "trial": self._trial,
            "run_id": self._run_id,
            "trace_id": self._current_trace_id,
            "prompt_raw": prompt,
            "response_raw": response,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "error": error,
            "prompt_assembly": prompt_assembly,
        }

        # 1. Canonical JSON (atomic)
        json_path = self._run_dir / "calls" / f"{call_id:06d}.json"
        write_json_atomic(json_path, record)

        # 2. Derived flat text (atomic)
        flat_path = self._run_dir / "calls_flat" / f"{call_id:06d}_{phase}.txt"
        write_text_atomic(flat_path, render_call_flat(record))

        # 3. Canonical event via emit_event
        return self.emit_event(
            "llm_call",
            case_id=case_id,
            condition=condition,
            phase=phase,
            parent_event_id=parent_event_id,
            call_id=call_id,
            llm_model=model,
            tokens_input_estimate=len(prompt),
            tokens_output_estimate=len(response),
            latency_ms=round(elapsed_seconds * 1000),
            call_status="error" if error else "success",
            error_type=error,
            request_path=f"calls/{call_id:06d}.json",
            response_path=f"calls/{call_id:06d}.json",
            flat_path=f"calls_flat/{call_id:06d}_{phase}.txt",
            prompt_assembly=prompt_assembly,
        )

    # ============================================================
    # LEGACY WRAPPERS (for run.start, run.end, metrics)
    # ============================================================

    def log_event(self, event_type: str, payload: dict,
                  case_id: str | None = None,
                  phase: str | None = None,
                  condition: str | None = None) -> int:
        """Legacy wrapper. Routes through emit_event("pipeline_state", ...).

        For backward compat with runner.py run.start/run.end calls.
        """
        # Map legacy event types to step values
        step_map = {
            "run.start": "run_start",
            "run.end": "run_end",
            "run.failed": "run_failed",
            "case.start": "case_start",
            "metric.record": "metric",
            "parse.result": "parse",
        }
        step = step_map.get(event_type, event_type)

        # Map legacy phase values to VALID_PHASES
        _PHASE_MAP = {"run": "pipeline", "orchestrator": "pipeline",
                      "parsing": "evaluation", "reconstruction": "evaluation",
                      "validation": "evaluation"}
        if phase is not None:
            phase = _PHASE_MAP.get(phase, phase)
        elif event_type.startswith("run."):
            phase = "pipeline"
        elif event_type.startswith("case."):
            phase = "case"
        else:
            phase = "evaluation"

        return self.emit_event(
            "pipeline_state",
            case_id=case_id,
            condition=condition,
            phase=phase,
            step=step,
            extra={"legacy_payload": payload},
        )

    def log_metric(self, name: str, value: Any,
                   context: dict | None = None) -> int:
        return self.emit_event(
            "pipeline_state",
            phase="evaluation",
            step="metric",
            extra={"metric_name": name, "metric_value": value,
                   "metric_context": context or {}},
        )

    # ============================================================
    # DEBUG RECORD (run.jsonl — allowed fields only)
    # ============================================================

    def log_run(self, case_id: str, condition: str, prompt: str,
                raw_output: str, parsed: dict, canonical_event_id: int) -> None:
        """Write debug record to run.jsonl. References canonical event.

        Contains ONLY debug-specific fields. No canonical schema fields.
        Forbidden: pass, score, ran, tests_run, reasoning_correct, etc.
        """
        if self._closed:
            raise RuntimeError("Logger is closed — cannot write run record")

        record = {
            "canonical_event_id": canonical_event_id,
            "run_id": self._run_id,
            "trace_id": self._current_trace_id,
            "case_id": case_id,
            "condition": condition,
            "timestamp": datetime.now().isoformat(),
            "prompt_length": len(prompt),
            "raw_response_length": len(raw_output),
            "parsed_reasoning": str(parsed.get("reasoning", ""))[:2000],
            "parsed_code_length": len(parsed.get("code") or ""),
            "parse_error": parsed.get("parse_error"),
            "response_format": parsed.get("response_format"),
            "data_lineage": parsed.get("data_lineage"),
        }

        run_path = self._run_dir / "run.jsonl"
        line = json.dumps(record, default=str) + "\n"
        fd = os.open(str(run_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    # ============================================================
    # FINALIZE
    # ============================================================

    def finalize(self) -> dict:
        """Close logger. Derive metrics.json from events.jsonl. Validate. Return stats."""
        events = read_events(self._run_dir / "events.jsonl")

        # Derive metrics — use legacy event_type for backward compat
        case_ends = [e for e in events if e["event_type"] == "case.end"]
        total = len(case_ends)
        passes = sum(1 for e in case_ends if e["payload"].get("pass"))
        stats = {
            "pass_rate": round(passes / total, 4) if total else 0,
            "total_cases": total,
            "total_pass": passes,
        }
        write_json_atomic(self._run_dir / "metrics.json", stats)

        # Derive calls_index.json
        calls_index = []
        for e in events:
            if e["event_type"] in CALL_EVENT_TYPES:
                cid = e["payload"].get("call_id")
                if cid is not None:
                    calls_index.append({
                        "call_id": cid,
                        "case_id": e["case_id"],
                        "trace_id": e["trace_id"],
                        "phase": e["phase"],
                        "json": f"calls/{cid:06d}.json",
                        "flat": f"calls_flat/{cid:06d}_{e['phase']}.txt",
                    })
        write_json_atomic(self._run_dir / "calls_index.json", calls_index)

        # Validate
        ok, errors = self.validate()
        if not ok:
            raise RuntimeError(f"Run validation failed: {errors}")

        self.close()
        return stats

    # ============================================================
    # VALIDATION
    # ============================================================

    def validate(self) -> tuple[bool, list[str]]:
        """Assert internal consistency. Returns (ok, errors)."""
        errors = []
        events = read_events(self._run_dir / "events.jsonl")

        if not events:
            errors.append("events.jsonl is empty")
            return (False, errors)

        # Call file 1:1 correspondence
        json_count = len(list((self._run_dir / "calls").glob("*.json")))
        flat_count = len(list((self._run_dir / "calls_flat").glob("*.txt")))
        if json_count != flat_count:
            errors.append(f"calls mismatch: {json_count} JSON vs {flat_count} flat")

        # Call events have matching files
        for e in events:
            if e["event_type"] in CALL_EVENT_TYPES:
                cid = e["payload"].get("call_id")
                if cid is not None:
                    jp = self._run_dir / "calls" / f"{cid:06d}.json"
                    if not jp.exists():
                        errors.append(f"call_id={cid} has no file at {jp}")

        # Case lifecycle: every start has exactly one end/failed
        open_traces: dict[str, str] = {}
        for e in events:
            if e["event_type"] == "case.start":
                tid = e["trace_id"]
                if tid in open_traces:
                    errors.append(f"duplicate case.start for trace_id {tid}")
                open_traces[tid] = e["case_id"]
            elif e["event_type"] in ("case.end", "case.failed"):
                tid = e["trace_id"]
                if tid not in open_traces:
                    errors.append(f"case.end/failed without case.start for trace {tid}")
                else:
                    del open_traces[tid]
        if open_traces:
            errors.append(f"unclosed cases: {list(open_traces.values())}")

        # First event is run.start
        if events[0]["event_type"] != "run.start":
            errors.append(f"first event is {events[0]['event_type']}, expected run.start")

        # Last event is run.end or run.failed
        if events[-1]["event_type"] not in ("run.end", "run.failed"):
            errors.append(f"last event is {events[-1]['event_type']}, expected run.end or run.failed")

        # event_ids strictly monotonic from 1
        ids = [e["event_id"] for e in events]
        if ids != list(range(1, len(ids) + 1)):
            errors.append("event_ids not strictly monotonic from 1")

        # All events have schema_version
        for e in events:
            if e.get("schema_version") is None and e.get("event_type_canonical") is not None:
                errors.append(f"event_id={e['event_id']} missing schema_version")

        return (len(errors) == 0, errors)
