"""Call-level logging system for T3 benchmark.

PRIMARY INDEX = LLM CALL.

Every call_model() invocation produces exactly one call record:
  - {call_id}.json  in  {run_dir}/calls/
  - one append     to  {run_dir}/calls_flat.txt

This module is the ONLY writer of call logs. No other code touches these files.
All data flows through emit_call() which is invoked from call_model() in llm.py.

No case/attempt directory structure. No hierarchy. One file per LLM call.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("t3.call_logger")

# ============================================================
# GLOBAL STATE (set once per run via init_call_logger)
# ============================================================

_run_dir: Path | None = None
_calls_dir: Path | None = None
_flat_path: Path | None = None
_call_counter: int = 0
_call_counter_start: int = 0
_enabled: bool = False


def init_call_logger(run_dir: Path) -> None:
    """Initialize the call logger for a run. Must be called once before any LLM calls.

    Creates:
        {run_dir}/calls/          directory
        {run_dir}/calls_flat.txt  empty file (append target)
    """
    global _run_dir, _calls_dir, _flat_path, _call_counter, _call_counter_start, _enabled

    _run_dir = Path(run_dir)
    _calls_dir = _run_dir / "calls"
    _calls_dir.mkdir(parents=True, exist_ok=True)
    _flat_path = _run_dir / "calls_flat.txt"
    # Touch flat file
    _flat_path.touch()

    # Resume support: find highest existing call ID to avoid overwriting
    existing = [f.stem for f in _calls_dir.glob("*.json")]
    if existing:
        _call_counter = max(int(s) for s in existing if s.isdigit())
        _log.info("Call logger resuming from call_id=%d (%d existing calls)", _call_counter, len(existing))
    else:
        _call_counter = 0
    _call_counter_start = _call_counter
    _enabled = True
    _log.info("Call logger initialized: %s", _calls_dir)


def close_call_logger() -> int:
    """Close the call logger. Returns number of calls made in this session."""
    global _enabled
    session_count = _call_counter - _call_counter_start
    _enabled = False
    _log.info("Call logger closed: %d calls this session (%d total)", session_count, _call_counter)
    return session_count


def _next_call_id() -> int:
    """Return next monotonic call ID. Global across entire run."""
    global _call_counter
    _call_counter += 1
    return _call_counter


def _sanitize_path(name: str) -> str:
    """Replace non-filesystem-safe characters."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


# ============================================================
# CALL CONTEXT (set by execution code before call_model)
# ============================================================

_call_context: dict = {}
_prompt_provenance: dict | None = None


def set_call_context(**kwargs) -> None:
    """Set metadata context for the next LLM call.

    Called by execution code BEFORE call_model() to attach:
        phase, case_id, condition, attempt_index, step, etc.

    Context is consumed (read and cleared) by emit_call().
    """
    global _call_context
    _call_context = dict(kwargs)


def set_prompt_provenance(rendered_prompt, variables: dict, condition: str | None = None,
                          config_name: str | None = None) -> None:
    """Set prompt assembly provenance for the next LLM call.

    Called AFTER assembly_engine.build() returns, BEFORE call_model().
    Stores enough data to reconstruct the exact prompt from logs alone.
    """
    import hashlib
    global _prompt_provenance
    _prompt_provenance = {
        "component_names": list(rendered_prompt.component_names),
        "component_hashes": list(rendered_prompt.component_hashes),
        "variables": {k: v for k, v in variables.items()},
        "variables_used": list(rendered_prompt.variables_used),
        "plan_hash": rendered_prompt.plan_hash,
        "final_prompt_hash": rendered_prompt.final_prompt_hash,
        "condition": condition,
        "config_name": config_name,
    }


def _consume_context() -> dict:
    """Read and clear the call context. Returns the context dict."""
    global _call_context
    ctx = _call_context
    _call_context = {}
    return ctx


def _consume_provenance() -> dict | None:
    """Read and clear prompt provenance. Returns the provenance dict or None."""
    global _prompt_provenance
    prov = _prompt_provenance
    _prompt_provenance = None
    return prov


# ============================================================
# CORE: emit_call — ONE function, ONE entry point
# ============================================================


def emit_call(
    model: str,
    prompt_raw: str,
    response_raw: str,
    elapsed_seconds: float,
    error: str | None = None,
) -> int | None:
    """Log one LLM call. Returns the call_id, or None if logging is disabled.

    Called from call_model() in llm.py. This is the ONLY entry point.

    Writes:
        {run_dir}/calls/{call_id:06d}.json
        appends to {run_dir}/calls_flat.txt
    """
    if not _enabled or _run_dir is None:
        return None

    call_id = _next_call_id()
    ctx = _consume_context()
    prov = _consume_provenance()
    timestamp = datetime.now().isoformat()

    record = {
        "call_id": call_id,
        "timestamp": timestamp,
        "model": model,
        "phase": ctx.get("phase", "unknown"),
        "case_id": ctx.get("case_id"),
        "condition": ctx.get("condition"),
        "attempt_index": ctx.get("attempt_index", 0),
        "step": ctx.get("step"),
        "prompt_raw": prompt_raw,
        "response_raw": response_raw,
        "prompt_length": len(prompt_raw),
        "response_length": len(response_raw),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "error": error,
        "prompt_assembly": prov,
    }

    # Write JSON file
    json_path = _calls_dir / f"{call_id:06d}.json"
    try:
        fd = os.open(str(json_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, json.dumps(record, indent=2, default=str).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        _log.error("CALL LOG WRITE FAILED for call %d: %s", call_id, e)

    # Append to flat file
    try:
        flat_line = _format_flat_entry(record)
        fd = os.open(str(_flat_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, flat_line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        _log.error("FLAT LOG APPEND FAILED for call %d: %s", call_id, e)

    return call_id


def _format_flat_entry(record: dict) -> str:
    """Format one call record as a human-readable flat log entry."""
    call_id = record["call_id"]
    model = record["model"]
    phase = record["phase"]
    case_id = record.get("case_id") or "?"
    condition = record.get("condition") or "?"
    attempt = record.get("attempt_index", 0)
    step = record.get("step") or ""
    elapsed = record.get("elapsed_seconds", 0)
    error = record.get("error")

    header_parts = [
        f"[{call_id:06d}]",
        f"model={model}",
        f"phase={phase}",
        f"case={case_id}",
        f"condition={condition}",
        f"attempt={attempt}",
    ]
    if step:
        header_parts.append(f"step={step}")
    header_parts.append(f"elapsed={elapsed:.1f}s")
    if error:
        header_parts.append(f"ERROR={error}")

    header = " ".join(header_parts)

    lines = []
    lines.append(header)
    lines.append("")
    lines.append("=== PROMPT ===")
    lines.append(record["prompt_raw"])
    lines.append("")
    lines.append("=== RESPONSE ===")
    lines.append(record["response_raw"])
    lines.append("")
    lines.append("-" * 72)
    lines.append("")

    return "\n".join(lines)


def get_call_count() -> int:
    """Return current call count."""
    return _call_counter
