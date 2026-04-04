"""Live WAL loader — supports streaming updates from growing log files.

Tracks file offset to append new events without full reload.
Thread-safe for use with Streamlit's rerun model.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from dashboard.leg_scanner import build_attempt_table


@dataclass
class LiveState:
    """Tracks WAL read position for incremental loading."""
    log_dir: Path
    cases_path: Path
    file_offset: int = 0
    events: list[dict] = field(default_factory=list)
    df: pd.DataFrame | None = None
    last_update: float = 0.0
    total_lines: int = 0
    error: str | None = None


def create_live_state(log_dir: Path, cases_path: Path) -> LiveState:
    """Create a fresh LiveState for a log directory."""
    return LiveState(log_dir=log_dir, cases_path=cases_path)


def poll_wal(state: LiveState) -> bool:
    """Read new events from WAL since last offset.

    Returns True if new events were found, False otherwise.
    Sets state.error on failure (does not raise).
    """
    wal = state.log_dir / "merged_events.jsonl"
    if not wal.exists():
        state.error = f"WAL not found: {wal}"
        return False

    try:
        with wal.open("r") as f:
            f.seek(state.file_offset)
            new_lines = f.readlines()
            new_offset = f.tell()
    except OSError as e:
        state.error = f"WAL read error: {e}"
        return False

    if not new_lines:
        return False

    new_events = []
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            new_events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip malformed lines in live mode (may be partial write)

    if not new_events:
        state.file_offset = new_offset
        return False

    state.events.extend(new_events)
    state.file_offset = new_offset
    state.total_lines += len(new_events)
    state.last_update = time.time()
    state.error = None

    # Rebuild DataFrame from all events
    try:
        state.df = build_attempt_table(
            state.events, state.cases_path, state.log_dir
        )
    except (ValueError, KeyError) as e:
        # In live mode, incomplete case_data may cause transient errors
        state.error = f"Table build error (transient): {e}"
        return True  # events were added even if table build failed

    return True


def full_reload(state: LiveState) -> None:
    """Force full reload from disk. Resets offset."""
    state.file_offset = 0
    state.events = []
    state.df = None
    state.total_lines = 0
    state.error = None
    poll_wal(state)
