"""Effect wrapper — isolates side effects for graph runner nodes.

Provides:
  1. EffectLog — structured call logging (JSON lines)
  2. NoOpLogger — minimal logger adapter for functions that require
     a non-None logger (e.g., classify_case asserts event_id != None)
  3. wrap_llm_call — wraps call_model with logging + error capture
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from side_projects.graph_runner.runtime.constants import (
    EFFECT_FIELD_CALL_TYPE,
    EFFECT_FIELD_DURATION_MS,
    EFFECT_FIELD_ERROR_TYPE,
    EFFECT_FIELD_METADATA,
    EFFECT_FIELD_NODE,
    EFFECT_FIELD_STATUS,
    EFFECT_STATUS_ERROR,
    EFFECT_STATUS_SUCCESS,
    EFFECT_TYPE_LLM,
    EFFECT_TYPE_SUBPROCESS,
)

log = logging.getLogger("t3.effect_wrapper")


@dataclass(frozen=True)
class EffectRecord:
    """One logged effect call."""
    node: str
    call_type: str      # EFFECT_TYPE_LLM | EFFECT_TYPE_SUBPROCESS | EFFECT_TYPE_FILE_IO
    duration_ms: int
    status: str         # EFFECT_STATUS_SUCCESS | EFFECT_STATUS_ERROR
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class EffectLog:
    """Append-only effect log for one pipeline run.

    Writes JSON lines to disk. Thread-safe via append mode.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.records_list: list[EffectRecord] = []
        self.log_path: Path | None = None
        if output_dir is not None:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = output_dir / "effect_log.jsonl"

    def record(self, rec: EffectRecord) -> None:
        self.records_list.append(rec)
        if self.log_path is not None:
            line = json.dumps({
                EFFECT_FIELD_NODE: rec.node,
                EFFECT_FIELD_CALL_TYPE: rec.call_type,
                EFFECT_FIELD_DURATION_MS: rec.duration_ms,
                EFFECT_FIELD_STATUS: rec.status,
                EFFECT_FIELD_ERROR_TYPE: rec.error_type,
                EFFECT_FIELD_METADATA: rec.metadata,
            }, default=str)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    @property
    def records(self) -> list[EffectRecord]:
        return list(self.records_list)


class NoOpLogger:
    """Minimal logger adapter that satisfies call_model's logger interface.

    call_model calls logger.log_call(...) which returns an event_id.
    classify_case asserts event_id is not None.
    This adapter returns a synthetic event_id without writing to WAL.
    """

    def __init__(self) -> None:
        self.counter = 0

    def log_call(self, **kwargs: Any) -> int:
        self.counter += 1
        return self.counter

    def log_event(self, *args: Any, **kwargs: Any) -> int:
        self.counter += 1
        return self.counter


# Singleton no-op logger — stateless enough for parallel use
# (each run creates its own, but a shared one is fine for ID generation)
noop_logger_instance = NoOpLogger()


def get_noop_logger() -> NoOpLogger:
    """Return a no-op logger for effect nodes."""
    return noop_logger_instance


def wrap_llm_call(
    node_name: str,
    effect_log: EffectLog | None,
    call_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an LLM call with effect logging.

    Args:
        node_name: Name of the calling node.
        effect_log: EffectLog instance (None = skip logging).
        call_fn: The actual function to call (e.g., call_model).
        *args, **kwargs: Forwarded to call_fn.

    Returns:
        The return value of call_fn.

    Raises:
        Whatever call_fn raises — no silent swallowing.
    """
    t0 = time.monotonic()
    try:
        result = call_fn(*args, **kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if effect_log is not None:
            effect_log.record(EffectRecord(
                node=node_name, call_type=EFFECT_TYPE_LLM,
                duration_ms=elapsed_ms, status=EFFECT_STATUS_SUCCESS,
            ))
        return result
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if effect_log is not None:
            effect_log.record(EffectRecord(
                node=node_name, call_type=EFFECT_TYPE_LLM,
                duration_ms=elapsed_ms, status=EFFECT_STATUS_ERROR,
                error_type=type(exc).__name__,
            ))
        raise


def wrap_subprocess_call(
    node_name: str,
    effect_log: EffectLog | None,
    call_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute a subprocess call with effect logging."""
    t0 = time.monotonic()
    try:
        result = call_fn(*args, **kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if effect_log is not None:
            effect_log.record(EffectRecord(
                node=node_name, call_type=EFFECT_TYPE_SUBPROCESS,
                duration_ms=elapsed_ms, status=EFFECT_STATUS_SUCCESS,
            ))
        return result
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if effect_log is not None:
            effect_log.record(EffectRecord(
                node=node_name, call_type=EFFECT_TYPE_SUBPROCESS,
                duration_ms=elapsed_ms, status=EFFECT_STATUS_ERROR,
                error_type=type(exc).__name__,
            ))
        raise
