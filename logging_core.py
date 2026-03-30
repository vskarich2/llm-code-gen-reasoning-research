"""Centralized logging system for T3 benchmark experiments.

ONE module for ALL logging. No other code writes log files.

Two planes:
  - Control plane: OrchestratorLogger → experiment-level events.jsonl
  - Execution plane: RunLogger → per-run events.jsonl + calls/ + calls_flat/

Both use identical event schema. Both enforce VALID_EVENT_TYPES, VALID_PHASES,
and REQUIRES_TRACE invariants.

IDs:
  - run_id: str — groups one (model, condition, trial)
  - trace_id: str (UUID hex) — groups one case execution
  - event_id: int (monotonic per file) — strict ordering within one events.jsonl
  - call_id: int (monotonic per run) — links to calls/{id}.json
"""

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# ENUMS
# ============================================================

VALID_EVENT_TYPES = frozenset({
    # Orchestrator (control plane)
    "orchestrator.start",
    "orchestrator.schedule",
    "orchestrator.worker_start",
    "orchestrator.worker_end",
    "orchestrator.worker_failed",
    "orchestrator.abort",
    "orchestrator.complete",
    "orchestrator.preflight_pass",
    "orchestrator.preflight_fail",

    # Run (execution plane)
    "run.start",
    "run.end",
    "run.failed",

    # Case
    "case.start",
    "case.end",
    "case.failed",

    # LLM calls
    "call.generate",
    "call.classify",
    "call.other",

    # Pipeline stages
    "parse.result",
    "execution.result",

    # Metrics
    "metric.record",

    # Validation
    "validation.pass",
    "validation.fail",
})

VALID_PHASES = frozenset({
    "orchestrator",
    "run",
    "case",
    "generation",
    "classification",
    "parsing",
    "reconstruction",
    "evaluation",
    "validation",
})

REQUIRES_TRACE = frozenset({
    "case.start",
    "case.end",
    "case.failed",
    "call.generate",
    "call.classify",
    "call.other",
    "parse.result",
    "execution.result",
})

CALL_EVENT_TYPES = frozenset({"call.generate", "call.classify", "call.other"})

PHASE_TO_CALL_EVENT_TYPE = {
    "generation": "call.generate",
    "classification": "call.classify",
}

_FSYNC_EVENT_TYPES = frozenset({
    "run.start", "run.end", "run.failed",
    "case.failed",
    "orchestrator.start", "orchestrator.complete", "orchestrator.abort",
    "orchestrator.worker_failed",
})

_PHASE_INFERENCE = {
    "orchestrator.": "orchestrator",
    "run.": "run",
    "case.": "case",
    "call.generate": "generation",
    "call.classify": "classification",
    "call.other": "generation",
    "parse.": "parsing",
    "execution.": "evaluation",
    "metric.": "evaluation",
    "validation.": "validation",
}


def _infer_phase(event_type: str) -> str:
    for prefix, phase in _PHASE_INFERENCE.items():
        if event_type.startswith(prefix):
            return phase
    raise ValueError(f"Cannot infer phase for event_type: {event_type}")


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
    """Render a call record as human-readable flat text.

    This is the ONLY function that defines the flat text format.
    """
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
        """Validate schema, assign event_id, write line, flush. Returns event_id."""
        if self._closed:
            raise RuntimeError("Logger is closed")

        event_type = event.get("event_type")
        phase = event.get("phase")

        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event_type!r}")
        if phase not in VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase!r}")

        self._event_counter += 1
        event["event_id"] = self._event_counter

        line = json.dumps(event, default=str) + "\n"
        self._events_file.write(line)
        self._events_file.flush()

        if event_type in _FSYNC_EVENT_TYPES:
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
    """Execution plane logger. Created LOCALLY inside each worker process.

    NEVER pickled. NEVER passed through ProcessPoolExecutor.
    """

    def __init__(self, run_dir: Path, run_id: str,
                 model: str, condition: str, trial: int):
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
        self._call_counter = 0
        self._current_trace_id: str | None = None

        write_json_atomic(run_dir / "metadata.json", {
            "run_id": run_id,
            "model": model,
            "condition": condition,
            "trial": trial,
            "start_time": datetime.now().isoformat(),
        })

    # --- Case lifecycle ---

    def start_case(self, case_id: str) -> str:
        """Begin case execution. Creates trace_id. Logs case.start. Returns trace_id."""
        self._current_trace_id = uuid.uuid4().hex
        self.log_event("case.start", {}, case_id=case_id, phase="case")
        return self._current_trace_id

    def end_case(self, case_id: str, payload: dict) -> int:
        """End case. Logs case.end. Clears trace_id."""
        event_id = self.log_event("case.end", payload, case_id=case_id, phase="case")
        self._current_trace_id = None
        return event_id

    def fail_case(self, case_id: str, payload: dict) -> int:
        """Record case failure. Logs case.failed. Clears trace_id."""
        event_id = self.log_event("case.failed", payload, case_id=case_id, phase="case")
        self._current_trace_id = None
        return event_id

    # --- Core event logging ---

    def log_event(self, event_type: str, payload: dict,
                  case_id: str | None = None,
                  phase: str | None = None) -> int:
        """Write structured event. Injects run identity and current trace_id.

        Raises RuntimeError if event_type requires trace_id but none is active.
        """
        if event_type in REQUIRES_TRACE and self._current_trace_id is None:
            raise RuntimeError(
                f"trace_id is None but event_type '{event_type}' requires an active trace. "
                f"Call start_case() before emitting case-level events."
            )
        if phase is None:
            phase = _infer_phase(event_type)
        return self._write_event({
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "run_id": self._run_id,
            "trace_id": self._current_trace_id,
            "trial": self._trial,
            "model": self._model,
            "condition": self._condition,
            "case_id": case_id,
            "phase": phase,
            "payload": payload,
        })

    # --- LLM call logging ---

    def log_call(self, model: str, prompt: str, response: str,
                 elapsed_seconds: float, case_id: str, phase: str,
                 error: str | None = None,
                 prompt_assembly: dict | None = None) -> int:
        """Log one LLM call. Returns call_id.

        Writes three outputs from ONE in-memory record:
        1. calls/{call_id:06d}.json (canonical)
        2. calls_flat/{call_id:06d}_{phase}.txt (derived)
        3. events.jsonl entry (timeline, references call_id, NOT full prompt)

        Raises RuntimeError if any write fails.
        """
        self._call_counter += 1
        call_id = self._call_counter

        event_type = PHASE_TO_CALL_EVENT_TYPE.get(phase, "call.other")

        record = {
            "call_id": call_id,
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "phase": phase,
            "case_id": case_id,
            "condition": self._condition,
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

        # 2. Derived flat text (atomic, same record)
        flat_path = self._run_dir / "calls_flat" / f"{call_id:06d}_{phase}.txt"
        write_text_atomic(flat_path, render_call_flat(record))

        # 3. Event entry (references call_id, does NOT embed prompt/response)
        self.log_event(event_type, {
            "call_id": call_id,
            "latency_ms": round(elapsed_seconds * 1000),
            "prompt_length": len(prompt),
            "response_length": len(response),
            "error": error,
        }, case_id=case_id, phase=phase)

        return call_id

    # --- Metrics ---

    def log_metric(self, name: str, value: Any,
                   context: dict | None = None) -> int:
        return self.log_event("metric.record", {
            "name": name, "value": value, "context": context or {},
        }, phase="evaluation")

    # --- Finalize ---

    def finalize(self) -> dict:
        """Close logger. Derive metrics.json from events.jsonl. Validate. Return stats."""
        events = read_events(self._run_dir / "events.jsonl")

        # Derive metrics from events
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
                cid = e["payload"]["call_id"]
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

    # --- Validation ---

    def validate(self) -> tuple[bool, list[str]]:
        """Assert internal consistency. Returns (ok, errors)."""
        errors = []
        events = read_events(self._run_dir / "events.jsonl")

        # 1. Non-empty
        if not events:
            errors.append("events.jsonl is empty")
            return (False, errors)

        # 2. Call file 1:1 correspondence
        json_count = len(list((self._run_dir / "calls").glob("*.json")))
        flat_count = len(list((self._run_dir / "calls_flat").glob("*.txt")))
        if json_count != flat_count:
            errors.append(f"calls mismatch: {json_count} JSON vs {flat_count} flat")

        # 3. Call events have matching files
        for e in events:
            if e["event_type"] in CALL_EVENT_TYPES:
                cid = e["payload"].get("call_id")
                if cid is not None:
                    json_path = self._run_dir / "calls" / f"{cid:06d}.json"
                    if not json_path.exists():
                        errors.append(f"call_id={cid} referenced in event but no file at {json_path}")

        # 4. Case lifecycle: every start has exactly one end/failed
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
                    errors.append(f"case.end/failed without case.start for trace_id {tid}")
                else:
                    del open_traces[tid]
        if open_traces:
            errors.append(f"unclosed cases: {list(open_traces.values())}")

        # 5. Events between case.start and case.end share trace_id
        active_trace: str | None = None
        for e in events:
            if e["event_type"] == "case.start":
                active_trace = e["trace_id"]
            elif e["event_type"] in ("case.end", "case.failed"):
                active_trace = None
            elif active_trace is not None and e["trace_id"] is not None:
                if e["trace_id"] != active_trace:
                    errors.append(
                        f"event_id={e['event_id']} has trace_id={e['trace_id']} "
                        f"but active trace is {active_trace}"
                    )

        # 6. REQUIRES_TRACE invariant
        for e in events:
            if e["event_type"] in REQUIRES_TRACE and e.get("trace_id") is None:
                errors.append(
                    f"event_id={e['event_id']} type={e['event_type']} has trace_id=None "
                    f"(case_id={e.get('case_id')})"
                )

        # 7. First event is run.start
        if events[0]["event_type"] != "run.start":
            errors.append(f"first event is {events[0]['event_type']}, expected run.start")

        # 8. Last event is run.end or run.failed
        if events[-1]["event_type"] not in ("run.end", "run.failed"):
            errors.append(f"last event is {events[-1]['event_type']}, expected run.end or run.failed")

        # 9. event_ids strictly monotonic from 1
        ids = [e["event_id"] for e in events]
        if ids != list(range(1, len(ids) + 1)):
            errors.append("event_ids not strictly monotonic from 1")

        # 10. No legacy calls_flat.txt
        if (self._run_dir / "calls_flat.txt").exists():
            errors.append("legacy calls_flat.txt still exists")

        return (len(errors) == 0, errors)
