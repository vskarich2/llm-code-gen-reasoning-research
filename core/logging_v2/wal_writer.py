"""WAL writer. Stateless except for seq counter and file handle.

Caller builds EmittableEvent. Writer finalizes to WALEvent (assigns
event_id + seq). WALEvent is fully immutable.

Sink failures are logged but NEVER block WAL writes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.logging_v2.events import (
    EmittableEvent,
    WALEvent,
    validate_emittable,
)
from core.logging_v2.sinks import Sink

log = logging.getLogger("t3.wal_writer")

SCHEMA_VERSION = "2.0"


class WALWriter:
    def __init__(
        self,
        wal_path: Path,
        run_id: str,
        sinks: list[Sink] | None = None,
    ) -> None:
        self.wal_path = Path(wal_path)
        self.run_id = run_id
        self.sinks: list[Sink] = sinks or []
        self.seq = 0
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.wal_path, "a", encoding="utf-8")

    def emit(self, event: EmittableEvent) -> str:
        """Validate, finalize, write to WAL, dispatch to sinks.

        Returns event_id. Caller never sets event_id or seq.
        """
        if event.run_id != self.run_id:
            raise RuntimeError(
                f"run_id mismatch: event has {event.run_id!r}, "
                f"writer has {self.run_id!r}"
            )

        validate_emittable(event)

        self.seq += 1
        event_id = f"{self.seq:08d}"

        wal_event = WALEvent(
            event_id=event_id,
            seq=self.seq,
            event_type=event.event_type,
            schema_version=SCHEMA_VERSION,
            timestamp=event.timestamp,
            run_id=event.run_id,
            emitter=event.emitter,
            payload=event.payload,
            case_id=event.case_id,
            condition=event.condition,
            model=event.model,
            trial=event.trial,
            path=event.path,
            node=event.node,
            parent_event_id=event.parent_event_id,
            trace_id=event.trace_id,
            call_id=event.call_id,
            artifact_ref=event.artifact_ref,
        )

        record = asdict(wal_event)
        line = json.dumps(record, default=str) + "\n"
        self.file.write(line)
        self.file.flush()
        os.fsync(self.file.fileno())

        for sink in self.sinks:
            try:
                sink.emit(wal_event)
            except Exception as exc:
                log.warning(
                    "Sink %s failure for event %s: %s",
                    type(sink).__name__, event_id, exc,
                    exc_info=exc,
                )

        return event_id

    def close(self) -> None:
        self.file.close()
        for sink in self.sinks:
            try:
                sink.close()
            except Exception as exc:
                log.warning(
                    "Sink %s close failure: %s",
                    type(sink).__name__, exc,
                    exc_info=exc,
                )
