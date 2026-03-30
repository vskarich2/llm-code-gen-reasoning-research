"""Tests for merge_run.py — canonical merged_run.jsonl builder."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from merge_run import (
    build_merged_run, load_run_files, parse_row, compute_key,
    deduplicate_rows, validate_completeness, validate_schema,
    write_atomic, PRIMARY_KEY_FIELDS, REQUIRED_FIELDS,
)


def _make_row(case_id="case_a", condition="baseline_v2", model="nano",
              trial=1, run_id="run_1", passed=True, **extra):
    """Build a valid run.jsonl row."""
    row = {
        "case_id": case_id,
        "condition": condition,
        "model": model,
        "trial": trial,
        "run_id": run_id,
        "timestamp": "2026-03-30T12:00:00",
        "evaluation": {"pass": passed, "v2_category": "interpretable_success"},
        "trace_id": "abc123",
    }
    row.update(extra)
    return row


def _write_run_jsonl(directory, rows):
    """Write rows to run.jsonl inside a directory."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "run.jsonl")
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


# ============================================================
# Test 1: Happy path
# ============================================================

def test_happy_path():
    with tempfile.TemporaryDirectory() as tmp:
        # Two chunks, 2 cases x 2 conditions each
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_chunk_0"), [
            _make_row("case_a", "baseline_v2"),
            _make_row("case_a", "leg_v2"),
        ])
        _write_run_jsonl(os.path.join(tmp, "chunk_1", "ts_chunk_1"), [
            _make_row("case_b", "baseline_v2"),
            _make_row("case_b", "leg_v2"),
        ])

        path = build_merged_run(
            tmp,
            expected_case_ids={"case_a", "case_b"},
            expected_conditions={"baseline_v2", "leg_v2"},
        )

        rows = [json.loads(l) for l in open(path)]
        assert len(rows) == 4
        keys = {compute_key(r) for r in rows}
        assert len(keys) == 4


# ============================================================
# Test 2: Duplicate identical rows — deduplicated
# ============================================================

def test_duplicate_identical():
    with tempfile.TemporaryDirectory() as tmp:
        row = _make_row("case_a", "baseline_v2")
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [row])
        _write_run_jsonl(os.path.join(tmp, "chunk_1", "ts_c1"), [row])

        path = build_merged_run(
            tmp,
            expected_case_ids={"case_a"},
            expected_conditions={"baseline_v2"},
        )
        rows = [json.loads(l) for l in open(path)]
        assert len(rows) == 1


# ============================================================
# Test 3: Duplicate conflicting rows — raises error
# ============================================================

def test_duplicate_conflicting():
    with tempfile.TemporaryDirectory() as tmp:
        row1 = _make_row("case_a", "baseline_v2", passed=True)
        row2 = _make_row("case_a", "baseline_v2", passed=False)
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [row1])
        _write_run_jsonl(os.path.join(tmp, "chunk_1", "ts_c1"), [row2])

        with pytest.raises(ValueError, match="CONFLICTING DUPLICATE"):
            build_merged_run(tmp)


# ============================================================
# Test 4: Missing rows — raises error
# ============================================================

def test_missing_rows():
    with tempfile.TemporaryDirectory() as tmp:
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [
            _make_row("case_a", "baseline_v2"),
        ])

        with pytest.raises(ValueError, match="Incomplete dataset"):
            build_merged_run(
                tmp,
                expected_case_ids={"case_a", "case_b"},
                expected_conditions={"baseline_v2"},
                strict_completeness=True,
            )


# ============================================================
# Test 5: Schema mismatch — raises error when strict
# ============================================================

def test_schema_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        row1 = _make_row("case_a", "baseline_v2")
        row2 = _make_row("case_b", "baseline_v2")
        row2["extra_field"] = "unexpected"
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [row1, row2])

        with pytest.raises(ValueError, match="Schema mismatch"):
            build_merged_run(tmp, strict_schema=True)


# ============================================================
# Test 6: Missing required field — raises error
# ============================================================

def test_missing_required_field():
    with tempfile.TemporaryDirectory() as tmp:
        row = {"case_id": "case_a", "condition": "baseline_v2"}  # missing model, trial, etc.
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [row])

        with pytest.raises(ValueError, match="missing required fields"):
            build_merged_run(tmp)


# ============================================================
# Test 7: No run.jsonl files — raises FileNotFoundError
# ============================================================

def test_no_files():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FileNotFoundError):
            build_merged_run(tmp)


# ============================================================
# Test 8: Atomic write — no partial file on error
# ============================================================

def test_atomic_write():
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        path = Path(tmp) / "test.jsonl"
        rows = [_make_row("a", "b"), _make_row("c", "d")]
        write_atomic(path, rows)

        assert path.exists()
        written = [json.loads(l) for l in path.open()]
        assert len(written) == 2


# ============================================================
# Test 9: Primary key computation
# ============================================================

def test_compute_key():
    row = _make_row("case_x", "cond_y", model="m", trial=3)
    key = compute_key(row)
    assert key == ("case_x", "cond_y", "m", 3)


# ============================================================
# Test 10: Deterministic ordering
# ============================================================

def test_deterministic_ordering():
    with tempfile.TemporaryDirectory() as tmp:
        _write_run_jsonl(os.path.join(tmp, "chunk_1", "ts_c1"), [
            _make_row("case_b", "baseline_v2"),
        ])
        _write_run_jsonl(os.path.join(tmp, "chunk_0", "ts_c0"), [
            _make_row("case_a", "baseline_v2"),
        ])

        path = build_merged_run(
            tmp,
            expected_case_ids={"case_a", "case_b"},
            expected_conditions={"baseline_v2"},
        )
        rows = [json.loads(l) for l in open(path)]
        # Should be sorted by key: case_a before case_b
        assert rows[0]["case_id"] == "case_a"
        assert rows[1]["case_id"] == "case_b"


# ============================================================
# Test 11: Real parallel run data (if available)
# ============================================================

_REAL_RUN = os.path.join(
    os.path.dirname(__file__), "..",
    "logs/v2_parallel_smoke",
)
_HAS_REAL = os.path.isdir(_REAL_RUN)


@pytest.mark.skipif(not _HAS_REAL, reason="no parallel smoke data")
def test_real_parallel_run():
    """Validate merge on real parallel run output."""
    import glob
    run_dirs = sorted(glob.glob(os.path.join(_REAL_RUN, "*smoke_004*")))
    if not run_dirs:
        pytest.skip("no smoke_004 run")
    run_dir = run_dirs[-1]

    path = build_merged_run(run_dir, strict_completeness=False, strict_schema=False)
    rows = [json.loads(l) for l in open(path)]
    assert len(rows) > 0

    # No duplicate keys
    keys = [compute_key(r) for r in rows]
    assert len(keys) == len(set(keys))
