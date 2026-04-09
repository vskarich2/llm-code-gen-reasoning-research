"""WAL event types and validation.

EmittableEvent: caller builds this (no event_id, no seq).
WALEvent: writer produces this (immutable, has event_id + seq).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.logging_v2.enums import Emitter, EventType
from core.logging_v2.event_types import EVENT_TYPE_SPECS, PAYLOAD_SCHEMAS

LLM_CALL_TYPES = frozenset({
    EventType.LLM_CALL_STARTED,
    EventType.LLM_CALL_COMPLETED,
    EventType.LLM_CALL_FAILED,
})


@dataclass(frozen=True)
class EmittableEvent:
    """Caller-built event. No event_id or seq — those are set by WALWriter."""
    event_type: EventType
    timestamp: str
    run_id: str
    emitter: Emitter
    payload: dict[str, Any]
    case_id: str | None = None
    condition: str | None = None
    model: str | None = None
    trial: int | None = None
    path: int | None = None
    node: str | None = None
    parent_event_id: str | None = None
    trace_id: str | None = None
    call_id: str | None = None
    artifact_ref: str | None = None


@dataclass(frozen=True)
class WALEvent:
    """Finalized immutable event with writer-assigned event_id and seq."""
    event_id: str
    seq: int
    event_type: EventType
    schema_version: str
    timestamp: str
    run_id: str
    emitter: Emitter
    payload: dict[str, Any]
    case_id: str | None
    condition: str | None
    model: str | None
    trial: int | None
    path: int | None
    node: str | None
    parent_event_id: str | None
    trace_id: str | None
    call_id: str | None
    artifact_ref: str | None


def validate_emittable(event: EmittableEvent) -> None:
    """Validate an EmittableEvent before finalization."""
    if not isinstance(event.event_type, EventType):
        raise TypeError(
            f"event_type must be EventType, got {type(event.event_type)}"
        )
    if not isinstance(event.emitter, Emitter):
        raise TypeError(
            f"emitter must be Emitter, got {type(event.emitter)}"
        )

    spec = EVENT_TYPE_SPECS.get(event.event_type)
    if spec is None:
        raise RuntimeError(
            f"Unknown event type: {event.event_type.value}"
        )

    if spec.emitter != event.emitter:
        raise RuntimeError(
            f"Event {event.event_type.value} requires emitter "
            f"{spec.emitter.value}, got {event.emitter.value}"
        )

    if spec.requires_case and event.case_id is None:
        raise RuntimeError(
            f"Event {event.event_type.value} requires case_id"
        )

    if spec.requires_call_id and event.call_id is None:
        raise RuntimeError(
            f"Event {event.event_type.value} requires call_id"
        )

    if event.trial is not None and event.trial < 0:
        raise ValueError(
            f"trial must be >= 0, got {event.trial}"
        )

    if event.path is not None and event.path < 0:
        raise ValueError(
            f"path must be >= 0, got {event.path}"
        )

    if (event.artifact_ref is not None
            and event.artifact_ref.startswith("/")):
        raise ValueError(
            f"artifact_ref must be relative, got {event.artifact_ref!r}"
        )

    validate_payload(event)
    validate_axis_consistency(event)


def validate_payload(event: EmittableEvent) -> None:
    """Validate payload matches the schema for this event type."""
    schema = PAYLOAD_SCHEMAS.get(event.event_type)
    if schema is None:
        raise RuntimeError(
            f"No payload schema for {event.event_type.value}"
        )
    for key, expected_type in schema.items():
        if key not in event.payload:
            raise RuntimeError(
                f"Missing payload key {key!r} for "
                f"{event.event_type.value}"
            )
        if not isinstance(event.payload[key], expected_type):
            raise RuntimeError(
                f"Payload key {key!r} for {event.event_type.value}: "
                f"expected {expected_type.__name__}, "
                f"got {type(event.payload[key]).__name__}"
            )


def validate_axis_consistency(event: EmittableEvent) -> None:
    """If node is present, trial and path must be present.
    If LLM call event, all axes must be present.
    """
    if event.node is not None:
        if event.trial is None:
            raise ValueError(
                f"node={event.node!r} requires trial to be set"
            )
        if event.path is None:
            raise ValueError(
                f"node={event.node!r} requires path to be set"
            )

    if event.event_type in LLM_CALL_TYPES:
        for field_name in (
            "case_id", "condition", "model", "trial", "path", "node",
        ):
            if getattr(event, field_name) is None:
                raise ValueError(
                    f"LLM call event {event.event_type.value} "
                    f"requires {field_name} to be set"
                )
