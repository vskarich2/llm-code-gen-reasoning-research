"""Stable intermediate representation built from WAL + call artifacts.

All views derive from RunIR. Never from runtime state.
Ordering uses WAL seq exclusively. No filename or timestamp sorting.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logging_v2.call_artifacts import CallArtifact
from core.logging_v2.enums import CallPhase, CallStatus, EventType
from core.logging_v2.events import WALEvent
from core.logging_v2.enums import Emitter
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


def load_call_artifacts(run_root: Path) -> list[CallArtifact]:
    calls_dir = run_root / "artifacts" / "calls"
    results: list[CallArtifact] = []
    if not calls_dir.exists():
        return results
    paths = list(calls_dir.rglob("*.json"))
    records = []

    for json_path in paths:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        records.append(data)

    records.sort(key=lambda d: d["call_id"])

    for data in records:
        data["phase"] = CallPhase(data["phase"])
        data["status"] = CallStatus(data["status"])
        results.append(CallArtifact(**data))
    return results
