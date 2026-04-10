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
            payload={"experiment_name": "x", "seed": 42, "BOGUS": True},
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
        validate_payload(EmittableEvent(
            event_type=EventType.RUN_STARTED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"experiment_name": "test", "seed": 42},
        ))

    def test_accepts_valid_completed_payload(self) -> None:
        validate_payload(EmittableEvent(
            event_type=EventType.RUN_COMPLETED,
            timestamp="t", run_id="r", emitter=Emitter.RUNNER,
            payload={"total_cases": 10, "total_pass": 7},
        ))


class TestWALWriter:

    def test_rejects_mismatched_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w = WALWriter(Path(td) / "wal.jsonl", "run_A")
            with pytest.raises(RuntimeError, match="run_id mismatch"):
                w.emit(EmittableEvent(
                    event_type=EventType.RUN_STARTED, timestamp="t",
                    run_id="run_B", emitter=Emitter.RUNNER,
                    payload={"experiment_name": "x", "seed": 0},
                ))
            w.close()

    def test_rejects_invalid_emitter_for_event_type(self) -> None:
        """RUN_STARTED requires Emitter.RUNNER; ENGINE is wrong."""
        with tempfile.TemporaryDirectory() as td:
            w = WALWriter(Path(td) / "wal.jsonl", "r")
            with pytest.raises(RuntimeError, match="requires emitter"):
                w.emit(EmittableEvent(
                    event_type=EventType.RUN_STARTED, timestamp="t",
                    run_id="r", emitter=Emitter.ENGINE,
                    payload={"experiment_name": "x", "seed": 0},
                ))
            w.close()


class TestNormalizeModelName:

    def test_exact_member_returns_unchanged(self) -> None:
        assert normalize_model_name("gpt-4o-mini", {"gpt-4o-mini"}) == "gpt-4o-mini"

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
        d = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n"
        d.mkdir(parents=True)
        (d / "call_001.json").write_text(json.dumps({"event_id": "e"}))
        with pytest.raises(RuntimeError, match="missing required"):
            load_call_artifacts(tmp_path)

    def test_rejects_prompt_hash_mismatch(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["prompt_hash"] = "a" * 64
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Prompt hash mismatch"):
            load_call_artifacts(tmp_path)

    def test_rejects_response_hash_mismatch(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["response_hash"] = "b" * 64
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Response hash mismatch"):
            load_call_artifacts(tmp_path)

    def test_rejects_malformed_call_id(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data(call_id="bad")
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid call_id format"):
            load_call_artifacts(tmp_path)

    def test_rejects_duplicate_call_id_with_both_paths(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        d1 = _make_valid_call_data(call_id="00000001", prompt="a", response="b")
        d2 = _make_valid_call_data(call_id="00000001", prompt="c", response="d")
        dir1 = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n1"
        dir1.mkdir(parents=True)
        p1 = dir1 / "call_001.json"
        p1.write_text(json.dumps(d1))
        dir2 = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n2"
        dir2.mkdir(parents=True)
        p2 = dir2 / "call_001.json"
        p2.write_text(json.dumps(d2))
        with pytest.raises(RuntimeError) as exc_info:
            load_call_artifacts(tmp_path)
        msg = str(exc_info.value)
        assert "Duplicate call_id" in msg
        assert "00000001" in msg
        assert "already seen in" in msg

    def test_accepts_valid_artifact(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        _write_call_artifact(tmp_path, data)
        results = load_call_artifacts(tmp_path)
        assert len(results) == 1
        assert results[0].call_id == "00000001"

    def test_accepts_max_tokens_none(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["max_tokens"] = None
        _write_call_artifact(tmp_path, data)
        results = load_call_artifacts(tmp_path)
        assert results[0].max_tokens is None

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

    def test_rejects_json_list_with_path(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        d = tmp_path / "artifacts" / "calls" / "c/m/case/trial_0/path_0/n"
        d.mkdir(parents=True)
        p = d / "call_001.json"
        p.write_text(json.dumps([1, 2, 3]))
        with pytest.raises(RuntimeError) as exc_info:
            load_call_artifacts(tmp_path)
        msg = str(exc_info.value)
        assert "Call artifact must be JSON object" in msg
        assert str(p) in msg

    def test_rejects_empty_string_error(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["error"] = ""
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid error field"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_phase_enum_with_path(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["phase"] = "not_a_real_phase"
        p = _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError) as exc_info:
            load_call_artifacts(tmp_path)
        msg = str(exc_info.value)
        assert "Invalid phase in call artifact" in msg
        assert str(p.parent) in msg or "path_0" in msg

    def test_rejects_invalid_status_enum_with_path(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["status"] = "not_a_real_status"
        p = _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError) as exc_info:
            load_call_artifacts(tmp_path)
        msg = str(exc_info.value)
        assert "Invalid status in call artifact" in msg
        assert str(p.parent) in msg or "path_0" in msg

    def test_rejects_empty_phase_string(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["phase"] = ""
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Field 'phase' must be non-empty string"):
            load_call_artifacts(tmp_path)

    def test_rejects_empty_status_string(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["status"] = ""
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Field 'status' must be non-empty string"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_prompt_hash_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["prompt_hash"] = 12345
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid prompt_hash"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_response_hash_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["response_hash"] = 12345
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid response_hash"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_prompt_length_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["prompt_length"] = "five"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid prompt_length"):
            load_call_artifacts(tmp_path)

    def test_rejects_invalid_response_length_type(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["response_length"] = "five"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid response_length"):
            load_call_artifacts(tmp_path)

    def test_rejects_short_prompt_hash(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import load_call_artifacts
        data = _make_valid_call_data()
        data["prompt_hash"] = "abc"
        _write_call_artifact(tmp_path, data)
        with pytest.raises(RuntimeError, match="Invalid prompt_hash"):
            load_call_artifacts(tmp_path)
