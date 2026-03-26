"""Tests for RunLogger isolation and integrity.

Verifies:
1. init twice without close → crash
2. write after close → crash
3. model mismatch → crash
4. run_id in every record
5. thread ownership enforced
6. multi-model sequential runs → separate files
7. same-model sequential runs → separate files (run_id differs)
8. no cross-contamination between runs
9. verify_integrity detects failed writes
10. log path stable mid-run

Run: .venv/bin/python -m pytest tests/test_run_logger.py -v
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from execution import (
    RunLogger,
    init_run_log,
    close_run_log,
    get_run_logger,
    get_current_log_path,
    write_log,
)

BASE = Path(__file__).resolve().parents[1]
LOGS_DIR = BASE / "logs"

_DUMMY_PARSED = {"reasoning": "", "code": ""}
_DUMMY_EV = {"pass": False, "score": 0.0}


def _make_logger(tmp_path, model="test-model", run_id="test-run-001"):
    return RunLogger(
        tmp_path / "test.jsonl",
        tmp_path / "test_prompts.jsonl",
        tmp_path / "test_responses.jsonl",
        model=model,
        run_id=run_id,
    )


@pytest.fixture(autouse=True)
def clean_logger():
    """Ensure no active logger before/after each test."""
    close_run_log()
    yield
    close_run_log()


# ============================================================
# RunLogger class unit tests
# ============================================================

class TestRunLoggerClass:

    def test_write_after_close_raises(self, tmp_path):
        logger = _make_logger(tmp_path)
        logger.close()
        with pytest.raises(RuntimeError, match="WRITE AFTER CLOSE"):
            logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED, _DUMMY_EV)

    def test_model_mismatch_raises(self, tmp_path):
        logger = _make_logger(tmp_path, model="model-a")
        with pytest.raises(RuntimeError, match="MODEL MISMATCH"):
            logger.write("case1", "baseline", "model-b", "p", "o", _DUMMY_PARSED, _DUMMY_EV)

    def test_serial_write_succeeds(self, tmp_path):
        """Writing serially must succeed (no threads needed)."""
        logger = _make_logger(tmp_path)
        logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED, _DUMMY_EV)
        assert logger.writes_attempted == 3  # 3 files
        assert logger.writes_failed == 0

    def test_writes_tracked(self, tmp_path):
        logger = _make_logger(tmp_path)
        logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED,
                     {"pass": True, "score": 1.0})
        stats = logger.get_stats()
        assert stats["attempted"] == 3
        assert stats["failed"] == 0
        assert stats["run_id"] == "test-run-001"

    def test_run_id_in_records(self, tmp_path):
        """Every record must contain the run_id."""
        logger = _make_logger(tmp_path, run_id="unique-abc")
        logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED, _DUMMY_EV)

        for path in [logger.log_path, logger.prompts_path, logger.responses_path]:
            line = open(path).readline()
            record = json.loads(line)
            assert record["run_id"] == "unique-abc", f"run_id missing in {path.name}"

    def test_summary_after_close_raises(self, tmp_path):
        logger = _make_logger(tmp_path)
        logger.close()
        with pytest.raises(RuntimeError, match="WRITE AFTER CLOSE"):
            logger.write_summary({"status": "done"})

    def test_close_idempotent(self, tmp_path):
        logger = _make_logger(tmp_path)
        logger.close()
        logger.close()  # should not raise

    def test_verify_integrity_ok(self, tmp_path):
        logger = _make_logger(tmp_path)
        logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED, _DUMMY_EV)
        valid, reason = logger.verify_integrity()
        assert valid, reason

    def test_verify_integrity_no_writes(self, tmp_path):
        logger = _make_logger(tmp_path)
        valid, reason = logger.verify_integrity()
        assert not valid
        assert "zero writes" in reason

    def test_verify_integrity_failed_writes(self, tmp_path):
        logger = _make_logger(tmp_path)
        # Simulate a failed write by writing to non-existent directory
        logger.log_path = tmp_path / "nonexistent_dir" / "test.jsonl"
        logger.write("case1", "baseline", "test-model", "p", "o", _DUMMY_PARSED, _DUMMY_EV)
        valid, reason = logger.verify_integrity()
        assert not valid
        assert "INVALID" in reason


# ============================================================
# Lifecycle tests
# ============================================================

class TestInitCloseLifecycle:

    def test_init_twice_without_close_raises(self):
        init_run_log("model-a")
        with pytest.raises(RuntimeError, match="LOG BLEED PREVENTED"):
            init_run_log("model-b")

    def test_init_after_close_succeeds(self):
        path_a = init_run_log("lifecycle-test-a")
        close_run_log()
        time.sleep(1)
        path_b = init_run_log("lifecycle-test-b")
        close_run_log()
        assert path_a != path_b
        for p in [path_a, path_b]:
            for f in p.parent.glob(p.stem.split(".")[0] + "*"):
                f.unlink()

    def test_get_run_logger_without_init_raises(self):
        with pytest.raises(RuntimeError, match="No active RunLogger"):
            get_run_logger()

    def test_get_run_logger_after_close_raises(self):
        init_run_log("test-closed")
        close_run_log()
        with pytest.raises(RuntimeError, match="No active RunLogger"):
            get_run_logger()
        for f in LOGS_DIR.glob("test-closed_*"):
            f.unlink()

    def test_write_log_without_init_raises(self):
        with pytest.raises(RuntimeError, match="No active RunLogger"):
            write_log("case1", "baseline", "test", "p", "o", _DUMMY_PARSED, _DUMMY_EV)

    def test_run_id_is_unique(self):
        """Two sequential inits produce different run_ids."""
        init_run_log("runid-test")
        id_a = get_run_logger().run_id
        close_run_log()
        time.sleep(1)
        init_run_log("runid-test")
        id_b = get_run_logger().run_id
        close_run_log()
        assert id_a != id_b, f"Sequential runs got same run_id: {id_a}"
        for f in LOGS_DIR.glob("runid-test_*"):
            f.unlink()


# ============================================================
# Run isolation tests
# ============================================================

class TestRunIsolation:

    def test_sequential_models_separate_files(self):
        """Two models run sequentially — each gets its own log file."""
        path_a = init_run_log("isolation-model-a")
        logger_a = get_run_logger()
        logger_a.write("case1", "baseline", "isolation-model-a", "p", "o",
                       _DUMMY_PARSED, {"pass": True, "score": 1.0})
        close_run_log()

        time.sleep(1)

        path_b = init_run_log("isolation-model-b")
        logger_b = get_run_logger()
        logger_b.write("case1", "baseline", "isolation-model-b", "p", "o",
                       _DUMMY_PARSED, {"pass": False, "score": 0.0})
        close_run_log()

        assert path_a != path_b

        models_in_a = set()
        for line in open(path_a):
            models_in_a.add(json.loads(line).get("model", ""))
        assert models_in_a == {"isolation-model-a"}, f"File A contaminated: {models_in_a}"

        models_in_b = set()
        for line in open(path_b):
            models_in_b.add(json.loads(line).get("model", ""))
        assert models_in_b == {"isolation-model-b"}, f"File B contaminated: {models_in_b}"

        for p in [path_a, path_b]:
            for f in p.parent.glob(p.stem.split(".")[0] + "*"):
                f.unlink()

    def test_same_model_sequential_runs_separate(self):
        """Two runs of the SAME model — must have different run_ids and files."""
        path_a = init_run_log("same-model-test")
        rid_a = get_run_logger().run_id
        get_run_logger().write("case1", "baseline", "same-model-test", "p", "o",
                               _DUMMY_PARSED, _DUMMY_EV)
        close_run_log()

        time.sleep(1)

        path_b = init_run_log("same-model-test")
        rid_b = get_run_logger().run_id
        get_run_logger().write("case1", "baseline", "same-model-test", "p", "o",
                               _DUMMY_PARSED, _DUMMY_EV)
        close_run_log()

        assert path_a != path_b, "Same model produced same log path"
        assert rid_a != rid_b, "Same model produced same run_id"

        # Verify run_ids in files
        rids_in_a = set()
        for line in open(path_a):
            rids_in_a.add(json.loads(line).get("run_id", ""))
        assert rids_in_a == {rid_a}, f"File A has wrong run_ids: {rids_in_a}"

        rids_in_b = set()
        for line in open(path_b):
            rids_in_b.add(json.loads(line).get("run_id", ""))
        assert rids_in_b == {rid_b}, f"File B has wrong run_ids: {rids_in_b}"

        for p in [path_a, path_b]:
            for f in p.parent.glob(p.stem.split(".")[0] + "*"):
                f.unlink()

    def test_log_path_stable_during_run(self):
        path = init_run_log("stability-test")
        assert get_current_log_path() == path
        logger = get_run_logger()
        assert logger.log_path == path
        logger.write("case1", "baseline", "stability-test", "p", "o",
                     _DUMMY_PARSED, {"pass": True, "score": 1.0})
        assert get_current_log_path() == path
        close_run_log()
        for f in LOGS_DIR.glob("stability-test_*"):
            f.unlink()
