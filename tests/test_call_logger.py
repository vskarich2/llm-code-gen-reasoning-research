"""Tests for call-level logging system.

Validates: one file per LLM call, monotonic IDs, raw capture, flat log.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from call_logger import (
    init_call_logger,
    close_call_logger,
    emit_call,
    set_call_context,
    get_call_count,
)


@pytest.fixture
def run_dir(tmp_path):
    """Provide a fresh temp run directory and initialize the logger."""
    init_call_logger(tmp_path)
    yield tmp_path
    close_call_logger()


class TestCallLoggerBasics:

    def test_init_creates_directory(self, run_dir):
        assert (run_dir / "calls").is_dir()
        assert (run_dir / "calls_flat.txt").exists()

    def test_emit_creates_json_file(self, run_dir):
        set_call_context(
            phase="generation", case_id="alias_config_a", condition="baseline", attempt_index=0
        )
        cid = emit_call(
            model="gpt-4o-mini",
            prompt_raw="test prompt",
            response_raw="test response",
            elapsed_seconds=1.5,
        )
        assert cid == 1
        json_path = run_dir / "calls" / "000001.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["call_id"] == 1
        assert data["model"] == "gpt-4o-mini"
        assert data["prompt_raw"] == "test prompt"
        assert data["response_raw"] == "test response"
        assert data["phase"] == "generation"
        assert data["case_id"] == "alias_config_a"
        assert data["condition"] == "baseline"
        assert data["attempt_index"] == 0

    def test_flat_file_appended(self, run_dir):
        set_call_context(phase="generation", case_id="test_case", condition="baseline")
        emit_call(model="gpt-4o-mini", prompt_raw="p1", response_raw="r1", elapsed_seconds=1.0)
        flat = (run_dir / "calls_flat.txt").read_text()
        assert "[000001]" in flat
        assert "model=gpt-4o-mini" in flat
        assert "=== PROMPT ===" in flat
        assert "p1" in flat
        assert "=== RESPONSE ===" in flat
        assert "r1" in flat


class TestMonotonicCallIds:

    def test_sequential_ids(self, run_dir):
        for i in range(5):
            set_call_context(phase="generation", case_id=f"case_{i}")
            cid = emit_call(
                model="m", prompt_raw=f"p{i}", response_raw=f"r{i}", elapsed_seconds=0.1
            )
            assert cid == i + 1

    def test_no_gaps(self, run_dir):
        for i in range(10):
            set_call_context(phase="generation", case_id=f"c{i}")
            emit_call(model="m", prompt_raw=f"p{i}", response_raw=f"r{i}", elapsed_seconds=0.1)
        files = sorted((run_dir / "calls").glob("*.json"))
        assert len(files) == 10
        ids = [json.loads(f.read_text())["call_id"] for f in files]
        assert ids == list(range(1, 11))


class TestRawCapture:

    def test_full_prompt_no_truncation(self, run_dir):
        big_prompt = "X" * 500_000
        set_call_context(phase="generation", case_id="big")
        emit_call(model="m", prompt_raw=big_prompt, response_raw="r", elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert len(data["prompt_raw"]) == 500_000
        assert data["prompt_raw"] == big_prompt

    def test_full_response_no_truncation(self, run_dir):
        big_response = "Y" * 500_000
        set_call_context(phase="generation", case_id="big")
        emit_call(model="m", prompt_raw="p", response_raw=big_response, elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert len(data["response_raw"]) == 500_000

    def test_garbage_response_logged(self, run_dir):
        garbage = '{"broken json\x00\xff with nulls and unicode \U0001f4a9'
        set_call_context(phase="generation", case_id="garbage")
        emit_call(model="m", prompt_raw="p", response_raw=garbage, elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert data["response_raw"] == garbage

    def test_empty_response_logged(self, run_dir):
        set_call_context(phase="generation", case_id="empty")
        emit_call(model="m", prompt_raw="p", response_raw="", elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert data["response_raw"] == ""

    def test_error_logged(self, run_dir):
        set_call_context(phase="generation", case_id="err")
        emit_call(
            model="m",
            prompt_raw="p",
            response_raw="",
            elapsed_seconds=0.5,
            error="Connection timeout",
        )
        data = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert data["error"] == "Connection timeout"


class TestFlatLogCompleteness:

    def test_all_calls_in_flat_log(self, run_dir):
        for i in range(5):
            set_call_context(phase="generation", case_id=f"c{i}")
            emit_call(
                model="m", prompt_raw=f"prompt_{i}", response_raw=f"resp_{i}", elapsed_seconds=0.1
            )
        flat = (run_dir / "calls_flat.txt").read_text()
        for i in range(5):
            assert f"[{i+1:06d}]" in flat
            assert f"prompt_{i}" in flat
            assert f"resp_{i}" in flat

    def test_flat_log_ordering(self, run_dir):
        for i in range(3):
            set_call_context(phase="generation", case_id=f"c{i}")
            emit_call(model="m", prompt_raw=f"p{i}", response_raw=f"r{i}", elapsed_seconds=0.1)
        flat = (run_dir / "calls_flat.txt").read_text()
        pos1 = flat.index("[000001]")
        pos2 = flat.index("[000002]")
        pos3 = flat.index("[000003]")
        assert pos1 < pos2 < pos3


class TestCallContext:

    def test_context_consumed_after_emit(self, run_dir):
        set_call_context(phase="classifier", case_id="c1", condition="baseline")
        emit_call(model="m", prompt_raw="p", response_raw="r", elapsed_seconds=0.1)
        # Second call without context
        cid = emit_call(model="m", prompt_raw="p2", response_raw="r2", elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / f"{cid:06d}.json").read_text())
        assert data["phase"] == "unknown"  # context was consumed
        assert data["case_id"] is None

    def test_phase_types(self, run_dir):
        for phase in ["generation", "classifier", "critique"]:
            set_call_context(phase=phase, case_id="c")
            cid = emit_call(model="m", prompt_raw="p", response_raw="r", elapsed_seconds=0.1)
            data = json.loads((run_dir / "calls" / f"{cid:06d}.json").read_text())
            assert data["phase"] == phase

    def test_step_field(self, run_dir):
        set_call_context(phase="generation", case_id="c", step="contract_elicit")
        cid = emit_call(model="m", prompt_raw="p", response_raw="r", elapsed_seconds=0.1)
        data = json.loads((run_dir / "calls" / f"{cid:06d}.json").read_text())
        assert data["step"] == "contract_elicit"


class TestCallCount:

    def test_count_tracks(self, run_dir):
        assert get_call_count() == 0
        for i in range(7):
            emit_call(model="m", prompt_raw="p", response_raw="r", elapsed_seconds=0.1)
        assert get_call_count() == 7

    def test_close_returns_count(self, tmp_path):
        init_call_logger(tmp_path)
        for i in range(3):
            emit_call(model="m", prompt_raw="p", response_raw="r", elapsed_seconds=0.1)
        count = close_call_logger()
        assert count == 3


class TestIdempotency:

    def test_overwrite_same_call_id(self, run_dir):
        """If we manually write the same file, content is overwritten."""
        set_call_context(phase="generation", case_id="c1")
        emit_call(model="m", prompt_raw="p1", response_raw="r1", elapsed_seconds=0.1)
        data1 = json.loads((run_dir / "calls" / "000001.json").read_text())
        assert data1["prompt_raw"] == "p1"
        # IDs are monotonic so you can't get a collision via normal emit.
        # But the file is deterministically named, so replay would overwrite.


class TestFileCountMatchesCallCount:

    def test_file_count_equals_calls(self, run_dir):
        n = 15
        for i in range(n):
            set_call_context(phase="generation", case_id=f"c{i}")
            emit_call(model="m", prompt_raw=f"p{i}", response_raw=f"r{i}", elapsed_seconds=0.1)
        files = list((run_dir / "calls").glob("*.json"))
        assert len(files) == n
        assert get_call_count() == n
