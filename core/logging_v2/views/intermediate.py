"""Stable intermediate representation built from WAL + call artifacts.

All views derive from RunIR. Never from runtime state.
Ordering uses WAL seq exclusively. No filename or timestamp sorting.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging_v2.call_artifacts import (
    CallArtifact,
    compute_prompt_hash,
    compute_response_hash,
)
from core.logging_v2.enums import CallPhase, CallStatus, Emitter, EventType
from core.logging_v2.events import WALEvent
from core.logging_v2.manifest import RunManifest, RunStatus


@dataclass
class RunIR:
    manifest: RunManifest
    events: list[WALEvent]
    calls: list[CallArtifact]
    events_by_case: dict[str, list[WALEvent]] = field(
        default_factory=lambda: defaultdict(list),
    )
    events_by_type: dict[EventType, list[WALEvent]] = field(
        default_factory=lambda: defaultdict(list),
    )
    calls_by_case: dict[str, list[CallArtifact]] = field(
        default_factory=lambda: defaultdict(list),
    )
    calls_by_node: dict[str, list[CallArtifact]] = field(
        default_factory=lambda: defaultdict(list),
    )


def build_ir(run_root: Path) -> RunIR:
    """Build RunIR from WAL + call artifacts on disk.

    Events sorted by seq (WAL append order). No other sorting allowed.
    """
    manifest = load_manifest(run_root)
    events = load_wal_events(run_root)
    calls = load_call_artifacts(run_root)

    ir = RunIR(manifest=manifest, events=events, calls=calls)

    for event in events:
        if event.case_id is not None:
            ir.events_by_case[event.case_id].append(event)
        ir.events_by_type[event.event_type].append(event)

    for call in calls:
        ir.calls_by_case[call.case_id].append(call)
        ir.calls_by_node[call.node].append(call)

    return ir


def load_manifest(run_root: Path) -> RunManifest:
    path = run_root / "manifest.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = RunStatus(data["status"])
    return RunManifest(**data)


def load_wal_events(run_root: Path) -> list[WALEvent]:
    path = run_root / "wal.jsonl"
    events: list[WALEvent] = []
    if not path.exists():
        return events
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            data["event_type"] = EventType(data["event_type"])
            data["emitter"] = Emitter(data["emitter"])
            events.append(WALEvent(**data))
    events.sort(key=lambda e: e.seq)
    return events


REQUIRED_CALL_FIELDS = frozenset({
    "call_id", "event_id", "timestamp", "model", "node", "phase",
    "run_id", "case_id", "condition", "trial", "path", "prompt",
    "prompt_hash", "prompt_length", "temperature", "top_p", "max_tokens",
    "response", "response_hash", "response_length", "latency_ms",
    "status", "error",
})

CALL_ID_PATTERN = re.compile(r"^[0-9]{8}$")

NON_EMPTY_STRING_FIELDS = frozenset({
    "event_id", "model", "node", "case_id", "condition", "run_id",
    "timestamp", "phase", "status",
})


def load_call_artifacts(run_root: Path) -> list[CallArtifact]:
    calls_dir = run_root / "artifacts" / "calls"
    results: list[CallArtifact] = []
    if not calls_dir.exists():
        return results
    json_paths = list(calls_dir.rglob("*.json"))
    validated: list[tuple[dict, Path]] = []
    seen_call_ids: dict[str, Path] = {}

    for json_path in json_paths:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise RuntimeError(
                f"Call artifact must be JSON object: {json_path}"
            )

        missing = REQUIRED_CALL_FIELDS - set(data.keys())
        if missing:
            raise RuntimeError(
                f"Call artifact missing required fields "
                f"{sorted(missing)}: {json_path}"
            )

        if not isinstance(data["call_id"], str) or not data["call_id"]:
            raise RuntimeError(
                f"Invalid call_id in artifact: {json_path}"
            )
        if not CALL_ID_PATTERN.fullmatch(data["call_id"]):
            raise RuntimeError(
                f"Invalid call_id format in artifact {json_path}: "
                f"{data['call_id']!r}"
            )
        if data["call_id"] in seen_call_ids:
            raise RuntimeError(
                f"Duplicate call_id {data['call_id']} in {json_path} "
                f"(already seen in {seen_call_ids[data['call_id']]})"
            )
        seen_call_ids[data["call_id"]] = json_path

        actual_prompt_hash = compute_prompt_hash(data["prompt"])
        if actual_prompt_hash != data["prompt_hash"]:
            raise RuntimeError(
                f"Prompt hash mismatch in {json_path}: "
                f"expected {data['prompt_hash'][:16]}, "
                f"got {actual_prompt_hash[:16]}"
            )

        actual_response_hash = compute_response_hash(data["response"])
        if actual_response_hash != data["response_hash"]:
            raise RuntimeError(
                f"Response hash mismatch in {json_path}: "
                f"expected {data['response_hash'][:16]}, "
                f"got {actual_response_hash[:16]}"
            )

        if data["prompt_length"] != len(data["prompt"]):
            raise RuntimeError(
                f"prompt_length mismatch in {json_path}: "
                f"declared {data['prompt_length']}, actual {len(data['prompt'])}"
            )
        if data["response_length"] != len(data["response"]):
            raise RuntimeError(
                f"response_length mismatch in {json_path}: "
                f"declared {data['response_length']}, actual {len(data['response'])}"
            )

        if not isinstance(data["trial"], int) or data["trial"] < 0:
            raise RuntimeError(f"Invalid trial in {json_path}: {data['trial']!r}")
        if not isinstance(data["path"], int) or data["path"] < 0:
            raise RuntimeError(f"Invalid path in {json_path}: {data['path']!r}")
        if not isinstance(data["latency_ms"], int) or data["latency_ms"] < 0:
            raise RuntimeError(f"Invalid latency_ms in {json_path}: {data['latency_ms']!r}")

        if not isinstance(data["temperature"], float):
            raise RuntimeError(f"Invalid temperature in {json_path}: {data['temperature']!r}")
        if not isinstance(data["top_p"], float):
            raise RuntimeError(f"Invalid top_p in {json_path}: {data['top_p']!r}")

        if data["max_tokens"] is not None:
            if not isinstance(data["max_tokens"], int) or data["max_tokens"] < 0:
                raise RuntimeError(
                    f"Invalid max_tokens in {json_path}: {data['max_tokens']!r}"
                )

        if data["error"] is not None:
            if not isinstance(data["error"], str) or not data["error"]:
                raise RuntimeError(
                    f"Invalid error field in {json_path}: {data['error']!r}"
                )

        for field_name in NON_EMPTY_STRING_FIELDS:
            if not isinstance(data[field_name], str) or not data[field_name]:
                raise RuntimeError(
                    f"Field {field_name!r} must be non-empty string in {json_path}"
                )

        validated.append((data, json_path))

    validated.sort(key=lambda pair: pair[0]["call_id"])

    for data, json_path in validated:
        try:
            data["phase"] = CallPhase(data["phase"])
        except Exception as exc:
            raise RuntimeError(
                f"Invalid phase in call artifact {json_path}: {data['phase']!r}"
            ) from exc
        try:
            data["status"] = CallStatus(data["status"])
        except Exception as exc:
            raise RuntimeError(
                f"Invalid status in call artifact {json_path}: {data['status']!r}"
            ) from exc
        results.append(CallArtifact(**data))
    return results
