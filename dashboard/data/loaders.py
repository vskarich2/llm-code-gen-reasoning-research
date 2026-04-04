"""Data loading: experiments, oracle labels, cases, experiment discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.leg_scanner import build_attempt_table, load_wal

LOGS_ROOT = Path("logs")
CASES_PATH = Path("case_data/cases_v2.json")


def _is_v2_wal(wal_path: Path) -> bool:
    try:
        with wal_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("event_type") == "case.end":
                    return event.get("work_id") is not None
        return False
    except (json.JSONDecodeError, OSError):
        return False


def _log_mtime(exp_path: str) -> float:
    wal = Path(exp_path) / "merged_events.jsonl"
    try:
        return wal.stat().st_mtime if wal.exists() else 0.0
    except OSError:
        return 0.0


def find_experiments() -> list[str]:
    if not LOGS_ROOT.exists():
        return []
    experiments: list[str] = []
    for entry in sorted(LOGS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        wal = entry / "merged_events.jsonl"
        if wal.exists() and _is_v2_wal(wal):
            experiments.append(str(entry))
            continue
        for sub in sorted(entry.iterdir()):
            if not sub.is_dir():
                continue
            sub_wal = sub / "merged_events.jsonl"
            if sub_wal.exists() and _is_v2_wal(sub_wal):
                experiments.append(str(sub))
    experiments.sort(key=_log_mtime, reverse=True)
    return experiments


@st.cache_data(ttl=30)
def load_experiment(log_dir: str) -> pd.DataFrame:
    path = Path(log_dir)
    events = load_wal(path)
    df = build_attempt_table(events, CASES_PATH, path)
    df["_experiment"] = path.name
    return df


@st.cache_data(ttl=60)
def load_cases() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if isinstance(raw, dict):
        items = raw.get("cases", [])
    else:
        items = raw
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        case_id = item.get("id")
        if case_id:
            result[case_id] = item
    return result


def load_oracle_labels(selected_oracle: list[tuple[str, Path]]) -> pd.DataFrame | None:
    rows: list[dict[str, Any]] = []
    for name, path in selected_oracle:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                row["_oracle_source"] = name
                rows.append(row)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return df.rename(
        columns={
            "trial": "trial_idx",
            "reasoning_truth": "oracle_verdict",
        }
    )


def merge_oracle(df: pd.DataFrame, oracle_df: pd.DataFrame | None) -> pd.DataFrame:
    if oracle_df is None or df.empty:
        return df
    join_cols = ["case_id", "model", "condition", "trial_idx"]
    keep_cols = join_cols + ["oracle_verdict", "justification", "_oracle_source"]
    slim = oracle_df[keep_cols].drop_duplicates(subset=join_cols)
    return df.merge(slim, on=join_cols, how="left")
