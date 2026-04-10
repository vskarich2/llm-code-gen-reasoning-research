"""Call artifact writer. Produces .json (canonical) and .txt (derived).

Write ordering (non-negotiable):
1. Write call_NNN.json atomically
2. Emit LLM_CALL_COMPLETED WAL event referencing the .json path
3. Write call_NNN.txt atomically (non-canonical, secondary)

Call index is presentation-only, not semantic. Never used in logic.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.logging_v2.config import LoggingV2Config
from core.logging_v2.enums import ArtifactGroup, Axis, CallPhase, CallStatus
from core.logging_v2.axes import validate_call_index
from core.logging_v2.paths import build_artifact_path


@dataclass
class CallArtifact:
    call_id: str
    event_id: str
    timestamp: str
    model: str
    node: str
    phase: CallPhase
    run_id: str
    case_id: str
    condition: str
    trial: int
    path: int
    prompt: str
    prompt_hash: str
    prompt_length: int
    temperature: float
    top_p: float
    max_tokens: int | None
    response: str
    response_hash: str
    response_length: int
    latency_ms: int
    status: CallStatus
    error: str | None


def compute_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def compute_response_hash(response: str) -> str:
    return hashlib.sha256(response.encode()).hexdigest()


def write_call_json(
    run_root: Path,
    call: CallArtifact,
    call_index: int,
) -> str:
    """Write call JSON artifact. Returns relative path from run_root."""
    validate_call_index(call_index)
    dir_path = build_artifact_path(
        run_root,
        ArtifactGroup.CALLS,
        {
            Axis.CONDITION: call.condition,
            Axis.MODEL: call.model,
            Axis.CASE: call.case_id,
            Axis.TRIAL: call.trial,
            Axis.PATH: call.path,
            Axis.NODE: call.node,
        },
    )
    dir_path.mkdir(parents=True, exist_ok=True)
    filename = f"call_{call_index:03d}.json"
    file_path = dir_path / filename

    data = asdict(call)
    data["phase"] = call.phase.value
    data["status"] = call.status.value

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(dir_path), suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    rel = file_path.relative_to(run_root)
    return str(rel)


def render_call_txt(
    call: CallArtifact, config: LoggingV2Config,
) -> str:
    """Render human-readable call text. Pure function.

    Fixed section ordering: METADATA → REQUEST → RESPONSE.
    No conditional sections. No dynamic headers.
    """
    sep = config.call_txt_separator
    meta_name, req_name, resp_name = config.call_txt_section_names

    def section_header(name: str) -> str:
        return f"{sep}\n {name}\n{sep}"

    metadata_lines = [
        f"model:     {call.model}",
        f"node:      {call.node}",
        f"phase:     {call.phase.value}",
        f"case:      {call.case_id}",
        f"condition: {call.condition}",
        f"trial:     {call.trial}",
        f"path:      {call.path}",
        f"latency:   {call.latency_ms}ms",
        f"status:    {call.status.value}",
    ]
    if call.error is not None:
        metadata_lines.append(f"error:     {call.error}")

    parts = [
        section_header(meta_name),
        "\n".join(metadata_lines),
        "",
        section_header(req_name),
        call.prompt,
        "",
        section_header(resp_name),
        call.response,
    ]
    return "\n".join(parts)


def write_call_txt(
    run_root: Path,
    call: CallArtifact,
    call_index: int,
    config: LoggingV2Config,
) -> None:
    """Write human-readable call text. Secondary, non-canonical."""
    validate_call_index(call_index)
    dir_path = build_artifact_path(
        run_root,
        ArtifactGroup.CALLS,
        {
            Axis.CONDITION: call.condition,
            Axis.MODEL: call.model,
            Axis.CASE: call.case_id,
            Axis.TRIAL: call.trial,
            Axis.PATH: call.path,
            Axis.NODE: call.node,
        },
    )
    dir_path.mkdir(parents=True, exist_ok=True)
    filename = f"call_{call_index:03d}.txt"
    file_path = dir_path / filename

    content = render_call_txt(call, config)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(dir_path), suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
