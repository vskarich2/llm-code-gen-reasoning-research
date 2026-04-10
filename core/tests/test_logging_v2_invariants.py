"""Unit tests for logging_v2 invariants. Direct, focused, one per fix."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from core.logging_v2.axes import validate_call_index
from core.logging_v2.enums import (
    CallPhase,
    CallStatus,
    Emitter,
    EventType,
)
from core.logging_v2.events import EmittableEvent, validate_payload
from core.logging_v2.validation import normalize_model_name
from core.logging_v2.wal_writer import WALWriter


class TestValidateCallIndex:

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError):
            validate_call_index(0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            validate_call_index(-1)

    def test_accepts_one(self) -> None:
        validate_call_index(1)

    def test_accepts_large(self) -> None:
        validate_call_index(999)

    def test_rejects_string_with_typeerror(self) -> None:
        with pytest.raises(TypeError):
            validate_call_index("1")


class TestValidatePayload:

    def test_rejects_extra_keys(self) -> None:
        e = EmittableEvent(
            event_type=EventType.RUN_STARTED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={
                "experiment_name": "x", "seed": 42, "BOGUS": True,
            },
        )
        with pytest.raises(RuntimeError, match="Unexpected payload"):
            validate_payload(e)

    def test_rejects_none_for_required_field(self) -> None:
        e = EmittableEvent(
            event_type=EventType.RUN_COMPLETED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"total_cases": None, "total_pass": 0},
        )
        with pytest.raises(RuntimeError):
            validate_payload(e)

    def test_rejects_bool_for_int(self) -> None:
        e = EmittableEvent(
            event_type=EventType.RUN_COMPLETED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"total_cases": True, "total_pass": 0},
        )
        with pytest.raises(RuntimeError, match="exact type"):
            validate_payload(e)

    def test_accepts_valid_payload(self) -> None:
        e = EmittableEvent(
            event_type=EventType.RUN_STARTED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"experiment_name": "test", "seed": 42},
        )
        validate_payload(e)

    def test_accepts_valid_completed_payload(self) -> None:
        e = EmittableEvent(
            event_type=EventType.RUN_COMPLETED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"total_cases": 10, "total_pass": 7},
        )
        validate_payload(e)


class TestWALWriterRunIdMismatch:

    def test_rejects_mismatched_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w = WALWriter(Path(td) / "wal.jsonl", "run_A")
            e = EmittableEvent(
                event_type=EventType.RUN_STARTED,
                timestamp="t", run_id="run_B",
                emitter=Emitter.RUNNER,
                payload={"experiment_name": "x", "seed": 0},
            )
            with pytest.raises(RuntimeError, match="run_id mismatch"):
                w.emit(e)
            w.close()

    def test_rejects_invalid_event_type(self) -> None:
        """validate_emittable enforces event_type membership via EVENT_TYPE_SPECS."""
        with tempfile.TemporaryDirectory() as td:
            w = WALWriter(Path(td) / "wal.jsonl", "r")
            e = EmittableEvent(
                event_type=EventType.RUN_STARTED,
                timestamp="t", run_id="r",
                emitter=Emitter.ENGINE,
                payload={"experiment_name": "x", "seed": 0},
            )
            with pytest.raises(RuntimeError, match="requires emitter"):
                w.emit(e)
            w.close()


class TestNormalizeModelName:

    def test_exact_member_returns_unchanged(self) -> None:
        result = normalize_model_name(
            "gpt-4o-mini", {"gpt-4o-mini", "gpt-5-mini"},
        )
        assert result == "gpt-4o-mini"

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Unknown model"):
            normalize_model_name("bogus", {"gpt-4o-mini"})


def _make_valid_call_data(
    call_id: str = "00000001",
    prompt: str = "hello",
    response: str = "world",
) -> dict:
    return {
        "call_id": call_id,
        "event_id": "e001",
        "timestamp": "2026-01-01T00:00:00Z",
        "model": "gpt-4o-mini",
        "node": "generate",
        "phase": "generation",
        "run_id": "r001",
        "case_id": "alias_config_c",
        "condition": "baseline_v3",
        "trial": 0,
        "path": 0,
        "prompt": prompt,
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_length": len(prompt),
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": None,
        "response": response,
        "response_hash": hashlib.sha256(response.encode()).hexdigest(),
        "response_length": len(response),
        "latency_ms": 100,
        "status": "success",
        "error": None,
    }


def _write_call_artifact(
    tmp_path: Path, data: dict, subdir: str = "c/m/case/trial_0/path_0/n",
) -> Path:
    calls_dir = tmp_path / "artifacts" / "calls" / subdir
    calls_dir.mkdir(parents=True, exist_ok=True)
    path = calls_dir / f"call_{data['call_id'][-3:]}.json"
    path.write_text(json.dumps(data))
    return path


class TestLoadCallArtifacts:

    def test_rejects_missing_required_fields(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        calls_dir = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n"
        calls_dir.mkdir(parents=True)
        (calls_dir / "call_001.json").write_text(
            json.dumps({"event_id": "e", "timestamp": "t"}),
        )
        with pytest.raises(RuntimeError, match="missing required"):
            load_call_artifacts(tmp_path)

    def test_rejects_prompt_hash_mismatch(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["prompt_hash"] = "WRONG"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Prompt hash mismatch"):
            load_call_artifacts(tmp_path)

    def test_rejects_response_hash_mismatch(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["response_hash"] = "WRONG"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Response hash mismatch"):
            load_call_artifacts(tmp_path)

    def test_rejects_malformed_call_id(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data(call_id="bad")
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid call_id format"):
            load_call_artifacts(tmp_path)

    def test_rejects_duplicate_call_id(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        d1 = _make_valid_call_data(call_id="00000001", prompt="a", response="b")
        d2 = _make_valid_call_data(call_id="00000001", prompt="c", response="d")
        dir1 = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n1"
        dir1.mkdir(parents=True)
        (dir1 / "call_001.json").write_text(json.dumps(d1))
        dir2 = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n2"
        dir2.mkdir(parents=True)
        (dir2 / "call_001.json").write_text(json.dumps(d2))
        with pytest.raises(RuntimeError, match="Duplicate call_id"):
            load_call_artifacts(tmp_path)

    def test_accepts_valid_artifact(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        _write_call_artifact(tmp_path, data)
        results = load_call_artifacts(tmp_path)
        assert len(results) == 1
        assert results[0].call_id == "00000001"

    def test_rejects_invalid_temperature_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["temperature"] = "bad"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid temperature"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_top_p_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["top_p"] = "bad"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid top_p"):
            load_call_artifacts(tmp_path)

    def test_rejects_negative_max_tokens(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["max_tokens"] = -1
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid max_tokens"):
            load_call_artifacts(tmp_path)

    def test_rejects_json_list(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        calls_dir = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n"
        calls_dir.mkdir(parents=True)
        (calls_dir / "call_001.json").write_text(json.dumps([1, 2, 3]))
        with pytest.raises(RuntimeError, match="must be JSON object"):
            load_call_artifacts(tmp_path)

    def test_rejects_empty_string_error(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["error"] = ""
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid error field"):
            load_call_artifacts(tmp_path)

    def test_enum_error_includes_path(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["phase"] = "not_a_real_phase"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid phase in call artifact"):
            load_call_artifacts(tmp_path)
