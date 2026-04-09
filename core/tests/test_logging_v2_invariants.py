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

    def test_rejects_string(self) -> None:
        with pytest.raises(ValueError):
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


class TestLoadCallArtifacts:

    def test_rejects_missing_call_id(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import (
            load_call_artifacts,
        )
        calls_dir = tmp_path / "artifacts" / "calls" / "cond" / "mdl" / "case" / "trial_0" / "path_0" / "node"
        calls_dir.mkdir(parents=True)
        bad = {"event_id": "e", "timestamp": "t"}
        (calls_dir / "call_001.json").write_text(json.dumps(bad))
        with pytest.raises(RuntimeError, match="missing required"):
            load_call_artifacts(tmp_path)

    def test_rejects_hash_mismatch(self, tmp_path: Path) -> None:
        from core.logging_v2.views.intermediate import (
            load_call_artifacts,
        )
        calls_dir = tmp_path / "artifacts" / "calls" / "c" / "m" / "case" / "trial_0" / "path_0" / "n"
        calls_dir.mkdir(parents=True)
        prompt = "hello"
        response = "world"
        data = {
            "call_id": "00000001",
            "event_id": "e",
            "timestamp": "t",
            "model": "m",
            "node": "n",
            "phase": "generation",
            "run_id": "r",
            "case_id": "case",
            "condition": "c",
            "trial": 0,
            "path": 0,
            "prompt": prompt,
            "prompt_hash": "WRONG_HASH",
            "prompt_length": len(prompt),
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": None,
            "response": response,
            "response_hash": hashlib.sha256(
                response.encode(),
            ).hexdigest(),
            "response_length": len(response),
            "latency_ms": 100,
            "status": "success",
            "error": None,
        }
        (calls_dir / "call_001.json").write_text(json.dumps(data))
        with pytest.raises(RuntimeError, match="Prompt hash mismatch"):
            load_call_artifacts(tmp_path)
