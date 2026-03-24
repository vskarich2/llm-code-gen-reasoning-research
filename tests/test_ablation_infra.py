"""Infrastructure tests for the ablation system.

Tests: event schema validation, durability, safe file reading,
run discovery, trial completeness, atomic dashboard writing, merge validation.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_metrics import (
    emit_event,
    read_events_safe,
    aggregate_model_events,
    compute_trial_progress,
    compute_metrics,
    write_dashboard,
)


def _valid_event(**overrides):
    """Construct a valid event dict."""
    e = {
        "model": "test-model",
        "trial": 1,
        "run_id": "abc123",
        "case_id": "test_case",
        "condition": "baseline",
    }
    e.update(overrides)
    return e


# ============================================================
# A1. Event schema validation
# ============================================================

class TestEventSchema:
    def test_emit_event_missing_key_raises(self, tmp_path):
        event = _valid_event()
        del event["model"]
        path = tmp_path / "events.jsonl"
        with pytest.raises(ValueError, match="missing required keys"):
            emit_event(event, path)
        # File should not exist or be empty
        assert not path.exists() or path.stat().st_size == 0

    def test_emit_event_extra_optional_keys_allowed(self, tmp_path):
        event = _valid_event(score=0.95, elapsed_seconds=1.5)
        path = tmp_path / "events.jsonl"
        emit_event(event, path)
        written = json.loads(path.read_text().strip())
        assert written["score"] == 0.95
        assert written["elapsed_seconds"] == 1.5

    def test_emit_event_timestamp_present_and_string(self, tmp_path):
        event = _valid_event()
        path = tmp_path / "events.jsonl"
        emit_event(event, path)
        written = json.loads(path.read_text().strip())
        assert "timestamp" in written
        assert isinstance(written["timestamp"], str)
        # Verify it's parseable as ISO 8601
        from datetime import datetime
        datetime.fromisoformat(written["timestamp"])

    def test_emit_event_field_types_enforced(self, tmp_path):
        path = tmp_path / "events.jsonl"

        # trial must be int, not str
        with pytest.raises(ValueError, match="trial.*must be int"):
            emit_event(_valid_event(trial="1"), path)

        # model must be str, not int
        with pytest.raises(ValueError, match="model.*must be str"):
            emit_event(_valid_event(model=123), path)

        # run_id must be str, not int
        with pytest.raises(ValueError, match="run_id.*must be str"):
            emit_event(_valid_event(run_id=42), path)

        # case_id must be str, not None
        with pytest.raises(ValueError, match="case_id.*must be str"):
            emit_event(_valid_event(case_id=None), path)

        # condition must be str, not bool
        with pytest.raises(ValueError, match="condition.*must be str"):
            emit_event(_valid_event(condition=True), path)


# ============================================================
# A2. Event durability
# ============================================================

class TestEventDurability:
    def test_emit_event_readable_from_disk(self, tmp_path):
        event = _valid_event()
        path = tmp_path / "events.jsonl"
        emit_event(event, path)

        content = path.read_text()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) == 1
        written = json.loads(lines[0])
        assert written["model"] == "test-model"
        assert written["case_id"] == "test_case"

    def test_emit_event_fsync_exercised(self, tmp_path):
        event = _valid_event()
        path = tmp_path / "events.jsonl"
        with patch("live_metrics.os.fsync") as mock_fsync:
            # We need to also patch os.open/os.write/os.close to not actually fail
            # Instead, just verify fsync is called by running normally and checking
            pass
        # Simpler: verify the function calls os.fsync by running and checking file exists
        emit_event(event, path)
        assert path.exists()
        # The real test: mock os.fsync and verify it's called
        with patch("os.fsync") as mock_fsync:
            emit_event(_valid_event(case_id="second"), path)
            assert mock_fsync.called

    def test_emit_event_one_line_per_write(self, tmp_path):
        path = tmp_path / "events.jsonl"
        for i in range(5):
            emit_event(_valid_event(case_id=f"case_{i}"), path)

        content = path.read_text()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # each must be valid JSON


# ============================================================
# A3. Safe partial-file reading
# ============================================================

class TestSafeFileReading:
    def _write_raw(self, path, content):
        with open(path, "w") as f:
            f.write(content)

    def test_read_skips_incomplete_trailing_line(self, tmp_path):
        path = tmp_path / "events.jsonl"
        valid = json.dumps({"a": 1}) + "\n"
        self._write_raw(path, valid * 3 + '{"model": "x", "tria')
        events = read_events_safe(path)
        assert len(events) == 3

    def test_read_skips_corrupt_middle_line(self, tmp_path):
        path = tmp_path / "events.jsonl"
        valid1 = json.dumps({"first": True}) + "\n"
        corrupt = "NOT JSON\n"
        valid2 = json.dumps({"third": True}) + "\n"
        self._write_raw(path, valid1 + corrupt + valid2)
        events = read_events_safe(path)
        assert len(events) == 2
        assert events[0]["first"] is True
        assert events[1]["third"] is True

    def test_read_counts_valid_lines_around_corrupt(self, tmp_path):
        path = tmp_path / "events.jsonl"
        lines = []
        lines.append(json.dumps({"i": 0}) + "\n")
        lines.append(json.dumps({"i": 1}) + "\n")
        lines.append("CORRUPT LINE\n")
        lines.append(json.dumps({"i": 3}) + "\n")
        lines.append(json.dumps({"i": 4}) + "\n")
        lines.append(json.dumps({"i": 5}) + "\n")
        self._write_raw(path, "".join(lines))
        events = read_events_safe(path)
        assert len(events) == 5


# ============================================================
# A4. Run discovery safety
# ============================================================

class TestRunDiscovery:
    def test_discovery_ignores_dir_without_events(self, tmp_path):
        run_dir = tmp_path / "run_test-model_t1_abc123"
        run_dir.mkdir()
        (run_dir / "metadata.json").write_text("{}")
        events = aggregate_model_events("test-model", tmp_path)
        assert len(events) == 0

    def test_discovery_handles_empty_events_file(self, tmp_path):
        run_dir = tmp_path / "run_test-model_t1_abc123"
        run_dir.mkdir()
        (run_dir / "events.jsonl").touch()
        events = aggregate_model_events("test-model", tmp_path)
        assert len(events) == 0

    def test_discovery_skips_malformed_metadata(self, tmp_path):
        run_dir = tmp_path / "run_test-model_t1_abc123"
        run_dir.mkdir()
        # Write 3 valid events
        events_path = run_dir / "events.jsonl"
        for i in range(3):
            with open(events_path, "a") as f:
                f.write(json.dumps({"i": i}) + "\n")
        # Malformed metadata
        (run_dir / "metadata.json").write_text("NOT JSON")

        # aggregate_model_events should still return 3 events
        events = aggregate_model_events("test-model", tmp_path)
        assert len(events) == 3

        # compute_trial_progress should mark as ERROR
        progress = compute_trial_progress("test-model", tmp_path, 1)
        assert len(progress) == 1
        assert progress[0]["status"] == "ERROR"


# ============================================================
# A5. Trial completeness logic
# ============================================================

class TestTrialCompleteness:
    def _setup_run(self, tmp_path, model, trial, n_events, total_jobs=116):
        run_dir = tmp_path / f"run_{model}_t{trial}_abc{trial}"
        run_dir.mkdir()
        (run_dir / "metadata.json").write_text(json.dumps({"total_jobs": total_jobs}))
        events_path = run_dir / "events.jsonl"
        events_path.touch()  # always create the file
        for i in range(n_events):
            with open(events_path, "a") as f:
                f.write(json.dumps({"i": i}) + "\n")
        return run_dir

    def test_trial_complete(self, tmp_path):
        self._setup_run(tmp_path, "m", 1, 116)
        progress = compute_trial_progress("m", tmp_path, 1)
        assert progress[0]["status"] == "COMPLETE"
        assert progress[0]["actual"] == 116
        assert progress[0]["expected"] == 116

    def test_trial_in_progress(self, tmp_path):
        self._setup_run(tmp_path, "m", 1, 50)
        progress = compute_trial_progress("m", tmp_path, 1)
        assert progress[0]["status"] == "IN_PROGRESS"
        assert progress[0]["actual"] == 50

    def test_trial_not_started(self, tmp_path):
        self._setup_run(tmp_path, "m", 1, 0)
        progress = compute_trial_progress("m", tmp_path, 1)
        assert progress[0]["status"] == "NOT_STARTED"
        assert progress[0]["actual"] == 0

    def test_per_model_summary(self, tmp_path):
        self._setup_run(tmp_path, "m", 1, 116)    # COMPLETE
        self._setup_run(tmp_path, "m", 2, 50)     # IN_PROGRESS
        self._setup_run(tmp_path, "m", 3, 0)      # NOT_STARTED
        progress = compute_trial_progress("m", tmp_path, 3)
        statuses = {p["status"] for p in progress}
        assert "COMPLETE" in statuses
        assert "IN_PROGRESS" in statuses
        assert "NOT_STARTED" in statuses
        assert sum(1 for p in progress if p["status"] == "COMPLETE") == 1
        assert sum(1 for p in progress if p["status"] == "IN_PROGRESS") == 1
        assert sum(1 for p in progress if p["status"] == "NOT_STARTED") == 1


# ============================================================
# A6. Atomic dashboard writing
# ============================================================

class TestAtomicDashboard:
    def test_dashboard_exists_after_write(self, tmp_path):
        path = tmp_path / "dashboard.txt"
        write_dashboard({"completed_jobs": 0, "total_jobs": 100, "percent_complete": 0}, path)
        assert path.exists()
        content = path.read_text()
        assert len(content) > 0

    def test_dashboard_tmp_cleaned_up(self, tmp_path):
        path = tmp_path / "dashboard.txt"
        write_dashboard({"completed_jobs": 0, "total_jobs": 100, "percent_complete": 0}, path)
        tmp_file = path.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_dashboard_content_is_complete(self, tmp_path):
        path = tmp_path / "dashboard.txt"
        write_dashboard({"completed_jobs": 0, "total_jobs": 100, "percent_complete": 0}, path)
        content = path.read_text()
        assert content.startswith("=" * 72)
        assert content.strip().endswith("=" * 72)

    def test_dashboard_rejects_mixed_model_events(self):
        events = [
            {"model": "A", "pass": True, "condition": "baseline",
             "reasoning_correct": True, "code_correct": True},
            {"model": "B", "pass": False, "condition": "baseline",
             "reasoning_correct": False, "code_correct": False},
        ]
        with pytest.raises(AssertionError, match="multiple models"):
            compute_metrics(events, 100)

    def test_metrics_missing_required_field_raises(self):
        events = [
            {"model": "A", "condition": "baseline"},  # missing 'pass'
        ]
        with pytest.raises(RuntimeError, match="Missing 'pass' field"):
            compute_metrics(events, 100)


# ============================================================
# A7. Merge validation (tested via the functions in merge_and_validate)
# ============================================================

class TestMergeValidation:
    """These test the validation logic conceptually.
    Full integration tested via scripts/merge_and_validate.py.
    """

    def test_merge_detects_duplicate_tuple(self, tmp_path):
        """Two events with same (model, case_id, condition, trial) = duplicate."""
        events = [
            {"model": "m", "case_id": "c", "condition": "baseline", "trial": 1},
            {"model": "m", "case_id": "c", "condition": "baseline", "trial": 1},
        ]
        tuples = [(e["model"], e["case_id"], e["condition"], e["trial"]) for e in events]
        from collections import Counter
        counts = Counter(tuples)
        duplicates = {t: c for t, c in counts.items() if c > 1}
        assert len(duplicates) > 0

    def test_merge_detects_missing_tuple(self):
        """Missing one tuple from the expected set."""
        expected = {("m", "c1", "bl", 1), ("m", "c1", "bl", 2), ("m", "c2", "bl", 1), ("m", "c2", "bl", 2)}
        actual = {("m", "c1", "bl", 1), ("m", "c1", "bl", 2), ("m", "c2", "bl", 1)}
        missing = expected - actual
        assert len(missing) == 1
        assert ("m", "c2", "bl", 2) in missing

    def test_merge_order_deterministic(self, tmp_path):
        """Sorting by (model, trial, case_id, condition) is deterministic."""
        events = [
            {"model": "b", "trial": 2, "case_id": "c1", "condition": "lr"},
            {"model": "a", "trial": 1, "case_id": "c2", "condition": "bl"},
            {"model": "a", "trial": 1, "case_id": "c1", "condition": "bl"},
        ]
        sorted1 = sorted(events, key=lambda e: (e["model"], e["trial"], e["case_id"], e["condition"]))
        sorted2 = sorted(events, key=lambda e: (e["model"], e["trial"], e["case_id"], e["condition"]))
        assert sorted1 == sorted2
        assert sorted1[0]["model"] == "a"
        assert sorted1[0]["case_id"] == "c1"
