"""Manifest reader for live run monitoring.

Reads manifest.json and heartbeat files from an active or completed
experiment run directory. Pure data loading — no Streamlit imports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ManifestSnapshot:
    """Parsed manifest.json state at one point in time."""
    status: str = "unknown"
    total: int = 0
    pending: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    work_items: list[dict[str, Any]] = field(default_factory=list)
    failed_items: list[dict[str, Any]] = field(default_factory=list)
    running_items: list[dict[str, Any]] = field(default_factory=list)
    config_text: str = ""
    error: str | None = None


def load_manifest(run_dir: Path) -> ManifestSnapshot:
    """Load and parse manifest.json from a run directory."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return ManifestSnapshot(error="manifest.json not found")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return ManifestSnapshot(error=f"Failed to read manifest: {e}")

    items = data.get("work_items", {})
    snap = ManifestSnapshot(
        status=data.get("status", "unknown"),
        total=len(items),
    )

    for wid, state in items.items():
        s = state.get("state", "UNKNOWN")
        entry = {
            "work_id": wid,
            "state": s,
            "model": state.get("model", ""),
            "condition": state.get("condition", ""),
            "trial": state.get("trial", 0),
            "case_id": state.get("case_id", ""),
            "attempt": state.get("attempt", 1),
            "exit_code": state.get("exit_code"),
            "error": state.get("error", ""),
            "started_at": state.get("started_at", ""),
            "completed_at": state.get("completed_at", ""),
        }
        snap.work_items.append(entry)

        if s == "PENDING":
            snap.pending += 1
        elif s == "RUNNING":
            snap.running += 1
            snap.running_items.append(entry)
        elif s == "SUCCEEDED":
            snap.succeeded += 1
        elif s in ("FAILED", "FATAL"):
            snap.failed += 1
            snap.failed_items.append(entry)

    # Load config snapshot
    config_path = run_dir / "config.snapshot.yaml"
    if config_path.exists():
        try:
            snap.config_text = config_path.read_text(encoding="utf-8")
        except OSError:
            pass

    return snap


def load_heartbeat(run_dir: Path, work_id: str) -> dict[str, Any] | None:
    """Load heartbeat.json for a specific worker."""
    # Workers are in run_dir/workers/{work_id}/attempt_NNN/
    workers_dir = run_dir / "workers"
    if not workers_dir.exists():
        return None

    # Find the latest attempt dir for this work_id
    worker_dir = workers_dir / work_id
    if not worker_dir.exists():
        return None

    attempt_dirs = sorted(worker_dir.glob("attempt_*"), reverse=True)
    if not attempt_dirs:
        return None

    hb_path = attempt_dirs[0] / "heartbeat.json"
    if not hb_path.exists():
        return None

    try:
        return json.loads(hb_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_live_runs() -> list[str]:
    """Find run directories that have manifest.json."""
    logs_root = Path("logs")
    if not logs_root.exists():
        return []
    runs: list[str] = []
    for entry in sorted(logs_root.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "manifest.json").exists():
            runs.append(str(entry))
    # Sort by manifest mtime (most recent first)
    runs.sort(
        key=lambda p: (Path(p) / "manifest.json").stat().st_mtime,
        reverse=True,
    )
    return runs
