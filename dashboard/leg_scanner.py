"""WAL-driven case_data loader for LEG benchmark dashboard.

Source of truth: merged_events.jsonl (WAL) + per-worker artifact files.
No derived assumptions. No hidden state. Everything reconstructable from logs.

Uses schema.py FIELD_REGISTRY for all field extraction — no hardcoded paths.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from dashboard.schema import (
    FIELD_REGISTRY, get_source_fields, get_case_fields, get_required_fields,
)
from dashboard.derived_fields import apply_derived_fields

log = logging.getLogger(__name__)


def _get(d: dict, path: str, default=None):
    """Nested dict access via dot-separated path."""
    cur = d
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur


def load_wal(log_dir: Path) -> list[dict]:
    """Read ALL events from merged_events.jsonl.

    Returns the full event list. Raises on missing/empty WAL.
    """
    wal = log_dir / "merged_events.jsonl"
    if not wal.exists():
        raise FileNotFoundError(f"WAL not found: {wal}")
    events = []
    with wal.open("r") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Malformed JSON at line {i + 1} in {wal}: {e}"
                ) from e
    if not events:
        raise ValueError(f"WAL is empty: {wal}")
    return events


def _load_cases(cases_path: Path) -> dict[str, dict]:
    """Load case metadata. Returns dict: case_id -> case dict."""
    if not cases_path.exists():
        raise FileNotFoundError(f"Cases file not found: {cases_path}")
    data = json.loads(cases_path.read_text())
    return {c["id"]: c for c in data}


def _extract_event_fields(e: dict) -> dict:
    """Extract all FIELD_REGISTRY source fields from one event.

    Uses the registry — no hardcoded field paths.
    """
    row = {}
    for col_name, source_path in get_source_fields():
        val = _get(e, source_path)
        # Try fallback_source if primary is None
        if val is None:
            spec = FIELD_REGISTRY[col_name]
            fallback = spec.get("fallback_source")
            if fallback:
                val = _get(e, fallback)
        row[col_name] = val
    return row


def _join_case_metadata(row: dict, cases: dict[str, dict]) -> dict:
    """Join case metadata fields onto a row."""
    case_id = row.get("case_id")
    case_meta = cases.get(case_id, {})
    for col_name, case_key in get_case_fields():
        row[col_name] = case_meta.get(case_key)
    return row


def _validate_required(row: dict, idx: int):
    """Validate required fields are non-null. Raises on violation."""
    for field_name in get_required_fields():
        if row.get(field_name) is None:
            raise ValueError(
                f"Event {idx}: missing required field '{field_name}' "
                f"(work_id={row.get('work_id', '?')})"
            )


def _resolve_attempt_paths(
    log_dir: Path, work_id: str, event_attempt: int,
    trajectory_idx: int, n_attempts: int,
) -> dict:
    """Resolve artifact file paths for one attempt within a retry chain.

    Retry workers: all attempts in attempt_001/calls_flat/.
    File ordering varies (oracle/critique calls interleaved),
    so we scan by suffix rather than computing indices.

    Layout for a 2-attempt critique retry:
      000001_generation.txt      ← att 0 gen
      000002_oracle_eval.txt     ← att 0 oracle
      000003_classification.txt  ← att 0 classifier
      000004_classification.txt  ← att 0 critique (between attempts)
      000005_generation.txt      ← att 1 gen
      000006_oracle_eval.txt     ← att 1 oracle
      000007_classification.txt  ← att 1 classifier
    """
    calls_dir = (
        log_dir / "workers" / work_id
        / f"attempt_{event_attempt:03d}" / "calls_flat"
    )

    gen_file = Path("/dev/null")
    cls_file = Path("/dev/null")
    critique_file = Path("/dev/null")

    if calls_dir.exists():
        gen_files = sorted(calls_dir.glob("*_generation.txt"))
        cls_files = sorted(calls_dir.glob("*_classification.txt"))

        if trajectory_idx < len(gen_files):
            gen_file = gen_files[trajectory_idx]

        # Find the upper bound: the next generation file (if any)
        next_gen_num = "999999"
        if trajectory_idx + 1 < len(gen_files):
            next_gen_num = gen_files[trajectory_idx + 1].name.split("_")[0]

        # Classification files between this gen and next gen:
        # first one = classifier, second one = critique
        if gen_file.exists() and cls_files:
            gen_num = gen_file.name.split("_")[0]
            matching_cls = []
            for cf in cls_files:
                cf_num = cf.name.split("_")[0]
                if cf_num > gen_num and cf_num < next_gen_num:
                    matching_cls.append(cf)
            if matching_cls:
                cls_file = matching_cls[0]
            if len(matching_cls) > 1:
                critique_file = matching_cls[1]

    return {
        "worker_dir": str(log_dir / "workers" / work_id),
        "prompt_path": str(gen_file) if gen_file.exists() else None,
        "response_path": str(gen_file) if gen_file.exists() else None,
        "classify_path": str(cls_file) if cls_file.exists() else None,
        "critique_path": str(critique_file) if critique_file.exists() else None,
        "artifact_status": "ok" if gen_file.exists() else "missing",
    }


def _classify_trajectory(attempts: list[dict]) -> str:
    """Classify an attempt chain's trajectory type."""
    if len(attempts) <= 1:
        return "single_shot"
    passes = [a.get("pass", False) for a in attempts]
    if passes[0]:
        return "single_shot" if all(passes) else "divergence"
    if passes[-1]:
        first_pass = next(i for i, p in enumerate(passes) if p)
        return "monotonic_fix" if all(passes[first_pass:]) else "oscillation"
    return "oscillation" if any(passes[1:]) else "stagnation"


def build_attempt_table(
    events: list[dict],
    cases_path: Path,
    log_dir: Path,
) -> pd.DataFrame:
    """Build canonical attempt-level DataFrame from WAL events.

    One row per attempt. Single-shot = 1 row. Retry = N rows from trajectory.
    All fields extracted via FIELD_REGISTRY. Strict validation.
    """
    cases = _load_cases(cases_path)

    # Filter to case.end events
    terminal = [
        (i, e) for i, e in enumerate(events)
        if e.get("event_type") == "case.end"
    ]
    if not terminal:
        raise ValueError("No case.end events found in WAL")

    rows = []

    for event_idx, e in terminal:
        # Extract all registry fields from the event
        base_row = _extract_event_fields(e)
        _join_case_metadata(base_row, cases)
        _validate_required(base_row, event_idx)

        case_id = base_row["case_id"]
        if case_id not in cases:
            raise ValueError(
                f"Unknown case_id '{case_id}' not in {cases_path}"
            )

        work_id = base_row["work_id"]
        event_attempt = base_row["attempt_idx"]

        # Get trajectory (per-attempt results)
        trajectory = _get(e, "payload.trajectory") or _get(
            e, "extra.trajectory"
        )

        if trajectory and len(trajectory) > 1:
            # RETRY CHAIN: one row per trajectory entry
            traj_type = _classify_trajectory(trajectory)
            n_attempts = len(trajectory)

            for t_entry in trajectory:
                t_idx = t_entry["attempt"]
                is_final = (t_idx == len(trajectory) - 1)

                paths = _resolve_attempt_paths(
                    log_dir, work_id, event_attempt, t_idx, n_attempts
                )

                row = dict(base_row)
                # Override with per-attempt values
                t_exec = t_entry.get("execution", {})
                row["attempt_idx"] = t_idx
                row["exec_pass"] = t_exec.get("pass", False)
                row["score"] = t_exec.get("score")
                row["exec_category"] = t_exec.get("execution_category")
                row["tests_passed"] = None
                row["tests_total"] = None
                row["runtime_ms"] = None

                # Per-attempt oracle
                t_oracle = t_entry.get("oracle", {})
                row["oracle_reasoning_truth"] = t_oracle.get("reasoning_truth")
                row["oracle_correct"] = t_oracle.get("oracle_correct")
                row["oracle_status"] = t_oracle.get("status")

                # Per-attempt classifier
                t_cls = t_entry.get("classifier", {})
                row["classifier_mechanism"] = t_cls.get("mechanism_identified")
                row["classifier_commitments_satisfied"] = t_cls.get("commitments_satisfied")
                row["classifier_ric"] = t_cls.get("reasoning_internal_consistency")
                row["classifier_ccc"] = t_cls.get("commitments_code_consistency")

                # Per-attempt AST
                t_ast = t_entry.get("ast", {})
                row["ast_status"] = t_ast.get("status")
                row["ast_correct"] = t_ast.get("ast_correct")

                # Per-attempt disagreement
                t_dis = t_entry.get("reasoning_disagreement", {})
                row["reasoning_disagreement_type"] = t_dis.get("type")

                # Reasoning fields on all attempts (not just final)
                if not is_final:
                    row["reasoning_correct"] = t_oracle.get("oracle_correct")
                    row["mechanism_label"] = None
                    row["confidence"] = None

                # Retry metadata
                row["is_final_attempt"] = is_final
                row["n_attempts"] = n_attempts
                row["trajectory_type"] = traj_type
                row["mismatch_critique"] = t_entry.get("mismatch_critique")
                row["had_test_feedback"] = t_entry.get(
                    "had_test_feedback", False
                )
                row["code_length"] = t_entry.get("code_length")
                row["attempt_status"] = t_entry.get("status", "UNKNOWN")

                row.update(paths)
                rows.append(row)
        else:
            # SINGLE-SHOT: one row from event directly
            paths = _resolve_attempt_paths(
                log_dir, work_id, event_attempt, 0, 1
            )
            row = dict(base_row)
            row["attempt_idx"] = 0
            row["is_final_attempt"] = True
            row["n_attempts"] = 1
            row["trajectory_type"] = "single_shot"
            row["mismatch_critique"] = None
            row["had_test_feedback"] = False
            row["code_length"] = None

            row.update(paths)
            rows.append(row)

    df = pd.DataFrame(rows)

    # Apply derived fields from registry
    df = apply_derived_fields(df)

    # Sort by chain then attempt
    df = df.sort_values(["chain_id", "attempt_idx"]).reset_index(drop=True)

    # Chain integrity validation
    for cid, g in df.groupby("chain_id"):
        actual = g["attempt_idx"].tolist()
        expected = list(range(len(actual)))
        if actual != expected:
            raise ValueError(
                f"Attempt index gap in chain '{cid}': "
                f"expected {expected}, got {actual}"
            )

    # Temporal deltas for retry chains
    df["prev_exec_pass"] = df.groupby("chain_id")["exec_pass"].shift(1)
    mask = df["prev_exec_pass"].notna()
    df["delta_exec"] = None
    df.loc[mask, "delta_exec"] = df.loc[mask].apply(
        lambda r: (
            "fail_to_pass" if not r["prev_exec_pass"] and r["exec_pass"]
            else "pass_to_fail" if r["prev_exec_pass"] and not r["exec_pass"]
            else "fail_to_fail" if not r["prev_exec_pass"]
            else "pass_to_pass"
        ),
        axis=1,
    )

    return df


def read_artifact(path: str | None) -> str | None:
    """Read an artifact file. Returns None if path is None or missing."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def split_prompt_response(artifact_text: str) -> tuple[str, str]:
    """Split a calls_flat generation file into prompt and response."""
    prompt_marker = "--- PROMPT ---"
    response_marker = "--- RESPONSE ---"
    prompt_start = artifact_text.find(prompt_marker)
    response_start = artifact_text.find(response_marker)
    if prompt_start == -1 or response_start == -1:
        return artifact_text, ""
    prompt = artifact_text[
        prompt_start + len(prompt_marker):response_start
    ].strip()
    response = artifact_text[
        response_start + len(response_marker):
    ].strip()
    return prompt, response
