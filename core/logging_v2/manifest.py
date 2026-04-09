"""Run manifest. Immutable fields + enforced status transitions."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.logging_v2.enums import RunStatus

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING:   frozenset({RunStatus.RUNNING}),
    RunStatus.RUNNING:   frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CRASHED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED:    frozenset(),
    RunStatus.CRASHED:   frozenset(),
}


def transition_status(
    current: RunStatus, next_status: RunStatus,
) -> None:
    allowed = ALLOWED_TRANSITIONS[current]
    if next_status not in allowed:
        raise RuntimeError(
            f"Invalid manifest status transition: "
            f"{current.value} → {next_status.value}. "
            f"Allowed: {sorted(s.value for s in allowed)}"
        )


@dataclass
class RunManifest:
    run_id: str
    run_dir_name: str
    experiment_name: str
    experiment_description: str
    experiment_tags: list[str]
    seed: int
    config_path: str
    config_hash: str
    git_commit_sha: str
    git_short_sha: str
    git_branch: str
    git_dirty: bool
    start_timestamp: str
    end_timestamp: str | None
    status: RunStatus
    models: list[dict[str, Any]]
    num_workers: int
    worker_timeout_seconds: int
    logging_schema_version: str
    redis_enabled: bool
    redis_stream_name: str | None
    redis_url: str | None
    wal_path: str
    artifacts_path: str
    materialized_views_path: str
    python_version: str
    hostname: str
    platform: str


def write_manifest(manifest: RunManifest, run_root: Path) -> None:
    path = run_root / "manifest.json"
    data = asdict(manifest)
    data["status"] = manifest.status.value
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(run_root), suffix=".tmp",
    )
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


def update_manifest_status(
    run_root: Path, new_status: RunStatus,
    end_timestamp: str | None = None,
) -> None:
    path = run_root / "manifest.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    current = RunStatus(data["status"])
    transition_status(current, new_status)
    data["status"] = new_status.value
    if end_timestamp is not None:
        data["end_timestamp"] = end_timestamp
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(run_root), suffix=".tmp",
    )
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
