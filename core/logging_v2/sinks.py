"""Sink protocol. WALWriter dispatches to sinks after WAL write."""

from __future__ import annotations

from typing import Protocol

from core.logging_v2.events import WALEvent


class Sink(Protocol):
    def emit(self, event: WALEvent) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
