"""Canonical merged_run.jsonl builder for T3 parallel runs.

Validates, deduplicates, and merges per-chunk run.jsonl files into a single
canonical dataset. This is the single source of truth for all evaluation analysis.

Primary key: (case_id, condition, model, trial)

Usage:
    from orchestration.merge_run import build_merged_run
    path = build_merged_run("logs/.../run_dir")
"""

import json
import os
import tempfile
from pathlib import Path


# Primary key fields — must be present in every row
PRIMARY_KEY_FIELDS = ("case_id", "condition", "model", "trial")

# All required top-level fields
REQUIRED_FIELDS = frozenset({
    "case_id", "condition", "model", "trial", "run_id",
    "timestamp", "evaluation",
})


def load_run_files(run_dir: str | Path) -> list[Path]:
    """Recursively find all events.jsonl files under run_dir.

    We read case.end events from events.jsonl (the new logging system puts
    full eval case_data there, not in run.jsonl).
    """
    run_dir = Path(run_dir)
    files = sorted(run_dir.rglob("events.jsonl"))
    if not files:
        raise FileNotFoundError(
            f"No events.jsonl files found under {run_dir}"
        )
    return files


def _extract_case_end_rows(events_path: Path, source: str) -> list[dict]:
    """Extract case.end events from events.jsonl and normalize to row format.

    Each case.end event becomes one row with the primary key fields at top level
    and the payload flattened into an 'evaluation' dict.
    """
    rows = []
    for line_num, line in enumerate(events_path.open(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # skip corrupt lines in events (WAL may have trailing partial)

        if event.get("event_type") != "case.end":
            continue

        # Build a normalized row from the case.end event
        payload = event.get("payload", {})
        row = {
            "case_id": event.get("case_id"),
            "condition": event.get("condition"),
            "model": event.get("model"),
            "trial": event.get("trial"),
            "run_id": event.get("run", {}).get("run_id") if isinstance(event.get("run"), dict) else event.get("run_id"),
            "timestamp": event.get("timestamp"),
            "evaluation": payload,
            "execution": event.get("execution", {}),
            "trace_id": event.get("trace_id"),
        }

        # Validate required fields
        missing = REQUIRED_FIELDS - set(k for k, v in row.items() if v is not None)
        if missing:
            continue  # skip malformed case.end events

        rows.append(row)
    return rows


def parse_row(line: str, source_file: str, line_num: int) -> dict:
    """Parse and validate a single JSONL row (for reading merged_run.jsonl)."""
    row = json.loads(line)
    if not isinstance(row, dict):
        raise ValueError(
            f"{source_file}:{line_num}: row is {type(row).__name__}, not dict"
        )
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise ValueError(
            f"{source_file}:{line_num}: missing required fields: {sorted(missing)}"
        )
    return row


def compute_key(row: dict) -> tuple:
    """Extract the primary key from a row."""
    return tuple(row[f] for f in PRIMARY_KEY_FIELDS)


def validate_schema(rows: list[dict]) -> None:
    """Enforce consistent schema across all rows."""
    if not rows:
        return
    reference_keys = set(rows[0].keys())
    for i, row in enumerate(rows[1:], 2):
        row_keys = set(row.keys())
        if row_keys != reference_keys:
            extra = row_keys - reference_keys
            missing = reference_keys - row_keys
            raise ValueError(
                f"Schema mismatch at row {i}: "
                f"extra={sorted(extra)}, missing={sorted(missing)}"
            )


def validate_completeness(
    rows: list[dict],
    expected_case_ids: set | None = None,
    expected_conditions: set | None = None,
    expected_trials: set | None = None,
) -> None:
    """Verify the dataset is complete (all key combinations present)."""
    actual_keys = {compute_key(r) for r in rows}
    actual_case_ids = {r["case_id"] for r in rows}
    actual_conditions = {r["condition"] for r in rows}
    actual_trials = {r["trial"] for r in rows}

    case_ids = expected_case_ids or actual_case_ids
    conditions = expected_conditions or actual_conditions
    trials = expected_trials or actual_trials

    expected_keys = {
        (cid, cond, rows[0]["model"], trial)
        for cid in case_ids
        for cond in conditions
        for trial in trials
    }

    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys

    if missing:
        missing_list = sorted(missing)
        raise ValueError(
            f"Incomplete dataset: {len(missing)} missing keys "
            f"(expected {len(expected_keys)}, got {len(actual_keys)}). "
            f"First missing: {missing_list}"
        )
    if extra:
        extra_list = sorted(extra)
        raise ValueError(
            f"Unexpected extra keys: {len(extra)}. First extra: {extra_list}"
        )


def deduplicate_rows(rows: list[dict]) -> list[dict]:
    """Enforce primary key uniqueness. Identical dups are collapsed.
    Conflicting dups raise."""
    seen = {}
    result = []
    for row in rows:
        key = compute_key(row)
        if key in seen:
            existing = seen[key]
            # Compare evaluation dicts (the meaningful content)
            ev_existing = existing.get("evaluation", {})
            ev_new = row.get("evaluation", {})
            if ev_existing == ev_new:
                continue  # identical duplicate, skip
            # Conflicting duplicate — find differences
            diff_keys = []
            all_ev_keys = set(ev_existing.keys()) | set(ev_new.keys())
            for k in sorted(all_ev_keys):
                v1 = ev_existing.get(k)
                v2 = ev_new.get(k)
                if v1 != v2:
                    diff_keys.append(k)
            raise ValueError(
                f"CONFLICTING DUPLICATE for key {key}: "
                f"evaluation differs on {diff_keys}"
            )
        seen[key] = row
        result.append(row)
    return result


def write_atomic(path: Path, rows: list[dict]) -> None:
    """Write rows to JSONL atomically (temp + fsync + rename)."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def build_merged_run(
    run_dir: str | Path,
    expected_case_ids: set | None = None,
    expected_conditions: set | None = None,
    expected_trials: set | None = None,
    strict_completeness: bool = True,
    strict_schema: bool = False,
) -> str:
    """Build canonical merged_run.jsonl from per-chunk run.jsonl files.

    Args:
        run_dir: parent run directory containing chunk subdirectories
        expected_*: optional sets for completeness validation.
            If None, inferred from the case_data.
        strict_completeness: if True, raise on incomplete case_data.
            If False, log warning but continue.
        strict_schema: if True, require identical schemas across rows.
            If False, allow schema variation (common with mixed conditions).

    Returns:
        Path to the written merged_run.jsonl.

    Raises:
        FileNotFoundError: no run.jsonl files found
        ValueError: validation failure (missing fields, duplicates, etc.)
    """
    run_dir = Path(run_dir)

    # Step 1: find all events.jsonl files
    run_files = load_run_files(run_dir)
    print(f"  merge_run: found {len(run_files)} events.jsonl files")

    # Step 2: extract case.end rows from events
    all_rows = []
    for events_file in run_files:
        source = str(events_file.relative_to(run_dir))
        rows = _extract_case_end_rows(events_file, source)
        for row in rows:
            row["_chunk_source"] = events_file.parent.name
        all_rows.extend(rows)

    print(f"  merge_run: extracted {len(all_rows)} case.end rows")

    if not all_rows:
        raise ValueError(f"No rows found in {len(run_files)} run.jsonl files")

    # Step 3: deduplicate
    deduped = deduplicate_rows(all_rows)
    n_dupes = len(all_rows) - len(deduped)
    if n_dupes:
        print(f"  merge_run: removed {n_dupes} identical duplicates")
    print(f"  merge_run: {len(deduped)} unique rows after dedup")

    # Step 4: schema validation
    if strict_schema:
        validate_schema(deduped)

    # Step 5: completeness validation
    if strict_completeness:
        try:
            validate_completeness(
                deduped, expected_case_ids, expected_conditions,
                expected_trials,
            )
        except ValueError as e:
            print(f"  merge_run: WARNING completeness check failed: {e}")
            if strict_completeness:
                raise

    # Step 6: sort by primary key for deterministic output
    deduped.sort(key=lambda r: compute_key(r))

    # Step 7: atomic write
    output_path = run_dir / "merged_run.jsonl"
    write_atomic(output_path, deduped)

    print(f"  merge_run: wrote {len(deduped)} rows to {output_path}")
    return str(output_path)
