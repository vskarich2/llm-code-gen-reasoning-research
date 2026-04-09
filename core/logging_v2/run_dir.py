"""Run directory creation. Unique naming with epoch-ms + git SHA."""

from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def get_git_sha() -> tuple[str, str]:
    """Return (full_sha, short_sha). Returns ('nogit', 'nogit') if not a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            full = result.stdout.strip()
            return full, full[:6]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "nogit", "nogit"


def get_git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def get_git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def sanitize_experiment_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def create_run_directory(
    base_dir: Path, experiment_name: str,
) -> tuple[Path, str, str]:
    """Create a uniquely-named run directory under base_dir.

    Returns (run_dir_path, full_git_sha, short_git_sha).

    Naming: {YYYY-MM-DD}_{HH-MM-SS}-{epoch_ms}-{git_sha_prefix}_{experiment_name}
    UTC wall clock. Epoch-ms ensures uniqueness.
    os.mkdir (no exist_ok) — collision raises immediately.
    On collision: sleep 2ms, retry once. Second collision: RuntimeError.
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    full_sha, short_sha = get_git_sha()
    safe_name = sanitize_experiment_name(experiment_name)

    for attempt in range(2):
        now = datetime.now(timezone.utc)
        epoch_ms = int(time.time() * 1000)
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        dir_name = (
            f"{timestamp}-{epoch_ms}-{short_sha}_{safe_name}"
        )
        target = base_dir / dir_name
        try:
            os.mkdir(target)
            return target, full_sha, short_sha
        except FileExistsError:
            if attempt == 0:
                time.sleep(0.002)
            else:
                raise RuntimeError(
                    f"Run directory collision after retry: {target}"
                )

    raise RuntimeError("Unreachable")
