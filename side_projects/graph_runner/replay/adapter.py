"""LLM adapter abstraction + replay/recording implementations.

Protocol:
    LLMAdapter.call(request: LLMRequest) -> LLMResponse

Implementations:
    ReplayAdapter — returns recorded responses, no external calls
    RecordingAdapter — wraps a real adapter, records all interactions
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("t3.replay")


# ============================================================
# DATA TYPES
# ============================================================

@dataclass(frozen=True)
class LLMRequest:
    model: str
    prompt: str
    temperature: float = 0.0
    top_p: float = 1.0


@dataclass(frozen=True)
class LLMResponse:
    text: str
    request_id: str = ""


@dataclass
class InteractionRecord:
    id: str
    model: str
    prompt: str
    response: str
    prompt_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# PROTOCOL
# ============================================================

@runtime_checkable
class LLMAdapter(Protocol):
    def call(self, request: LLMRequest) -> LLMResponse: ...


# ============================================================
# REPLAY ADAPTER
# ============================================================

class ReplayAdapter:
    """Returns recorded responses matched by exact prompt string.

    If a prompt is not found in the recording, raises KeyError.
    No external calls. No fallback. No fuzzy matching.
    """

    def __init__(self, records: list[InteractionRecord]) -> None:
        self.by_prompt_hash: dict[str, InteractionRecord] = {}
        self.by_prompt_exact: dict[str, InteractionRecord] = {}
        self.call_count = 0
        self.miss_count = 0

        for rec in records:
            self.by_prompt_hash[rec.prompt_hash] = rec
            self.by_prompt_exact[rec.prompt] = rec

    def call(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        prompt_hash = hashlib.sha256(
            request.prompt.encode(),
        ).hexdigest()

        rec = self.by_prompt_hash.get(prompt_hash)
        if rec is None:
            rec = self.by_prompt_exact.get(request.prompt)
        if rec is None:
            self.miss_count += 1
            raise KeyError(
                f"ReplayAdapter: no recorded response for prompt "
                f"(hash={prompt_hash[:16]}, len={len(request.prompt)}). "
                f"Searched {len(self.by_prompt_hash)} recordings."
            )

        return LLMResponse(text=rec.response, request_id=rec.id)

    @classmethod
    def from_jsonl(cls, path: Path) -> ReplayAdapter:
        """Load recordings from JSONL file."""
        records = load_recordings(path)
        return cls(records)


# ============================================================
# RECORDING ADAPTER
# ============================================================

class RecordingAdapter:
    """Wraps a real call function, records all interactions.

    call_fn signature: (prompt: str, model: str) -> str
    """

    def __init__(
        self, call_fn: Any, output_path: Path | None = None,
    ) -> None:
        self.call_fn = call_fn
        self.output_path = output_path
        self.records: list[InteractionRecord] = []

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)

    def call(self, request: LLMRequest) -> LLMResponse:
        response_text = self.call_fn(request.prompt, request.model)

        prompt_hash = hashlib.sha256(
            request.prompt.encode(),
        ).hexdigest()

        rec = InteractionRecord(
            id=uuid.uuid4().hex[:16],
            model=request.model,
            prompt=request.prompt,
            response=response_text,
            prompt_hash=prompt_hash,
            metadata={
                "temperature": request.temperature,
                "top_p": request.top_p,
            },
        )
        self.records.append(rec)

        if self.output_path is not None:
            line = json.dumps({
                "id": rec.id,
                "model": rec.model,
                "prompt": rec.prompt,
                "response": rec.response,
                "prompt_hash": rec.prompt_hash,
                "metadata": rec.metadata,
            }, default=str)
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

        return LLMResponse(text=response_text, request_id=rec.id)


# ============================================================
# SERIALIZATION
# ============================================================

def save_recordings(
    records: list[InteractionRecord], path: Path,
) -> None:
    """Save recordings to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            line = json.dumps({
                "id": rec.id,
                "model": rec.model,
                "prompt": rec.prompt,
                "response": rec.response,
                "prompt_hash": rec.prompt_hash,
                "metadata": rec.metadata,
            }, default=str)
            f.write(line + "\n")


def load_recordings(path: Path) -> list[InteractionRecord]:
    """Load recordings from JSONL."""
    records: list[InteractionRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(InteractionRecord(
                id=data["id"],
                model=data["model"],
                prompt=data["prompt"],
                response=data["response"],
                prompt_hash=data.get("prompt_hash", ""),
                metadata=data.get("metadata", {}),
            ))
    return records


# ============================================================
# INJECTION HOOK
# ============================================================

# Module-level adapter slot. When set, call_model uses this
# instead of making real API calls.
active_adapter: LLMAdapter | None = None


def install_adapter(adapter: LLMAdapter | None) -> None:
    """Install an adapter globally. Set None to restore real calls."""
    global active_adapter
    active_adapter = adapter


def get_active_adapter() -> LLMAdapter | None:
    """Return the currently installed adapter, or None."""
    return active_adapter


class AdapterContext:
    """Context manager for safe adapter installation.

    Restores the previous adapter on exit, even if an exception occurs.
    Eliminates global state leak risk across tests.
    """

    def __init__(self, adapter: LLMAdapter) -> None:
        self.adapter = adapter
        self.prev: LLMAdapter | None = None

    def __enter__(self) -> LLMAdapter:
        self.prev = get_active_adapter()
        install_adapter(self.adapter)
        return self.adapter

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        install_adapter(self.prev)
