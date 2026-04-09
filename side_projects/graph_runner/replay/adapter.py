"""LLM adapter abstraction + replay/recording implementations.

Protocol:
    LLMAdapter.call(request: LLMRequest) -> LLMResponse

Implementations:
    ReplayAdapter — returns recorded responses, no external calls
    RecordingAdapter — wraps a real adapter, records all interactions

Injection uses contextvars (no global mutable state).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("t3.replay")

COMPOSITE_KEY_SEPARATOR = "|"


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
    composite_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# PROTOCOL
# ============================================================

@runtime_checkable
class LLMAdapter(Protocol):
    def call(self, request: LLMRequest) -> LLMResponse: ...


# ============================================================
# KEY COMPUTATION
# ============================================================

def compute_composite_key(request: LLMRequest) -> str:
    """Composite key: hash(model | temperature | top_p | prompt).

    Prevents collisions across different models or sampling parameters.
    """
    raw = COMPOSITE_KEY_SEPARATOR.join([
        request.model,
        str(request.temperature),
        str(request.top_p),
        request.prompt,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_composite_key_from_parts(
    model: str, prompt: str,
    temperature: float = 0.0, top_p: float = 1.0,
) -> str:
    raw = COMPOSITE_KEY_SEPARATOR.join([
        model, str(temperature), str(top_p), prompt,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


# ============================================================
# REPLAY ADAPTER
# ============================================================

class ReplayAdapter:
    """Returns recorded responses matched by composite key.

    Composite key = hash(model | temperature | top_p | prompt).
    If key not found, raises KeyError. No fallback. No fuzzy matching.
    Validates uniqueness at load time.
    """

    def __init__(self, records: list[InteractionRecord]) -> None:
        self.by_key: dict[str, InteractionRecord] = {}
        self.call_count = 0
        self.miss_count = 0

        for rec in records:
            if rec.composite_key in self.by_key:
                raise ValueError(
                    f"Duplicate composite key in recordings: "
                    f"{rec.composite_key[:16]} "
                    f"(model={rec.model})"
                )
            self.by_key[rec.composite_key] = rec

    def call(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        key = compute_composite_key(request)

        rec = self.by_key.get(key)
        if rec is None:
            self.miss_count += 1
            raise KeyError(
                f"ReplayAdapter: no recorded response for "
                f"composite key (key={key[:16]}, "
                f"model={request.model}, "
                f"prompt_len={len(request.prompt)}). "
                f"Searched {len(self.by_key)} recordings."
            )

        return LLMResponse(text=rec.response, request_id=rec.id)

    @classmethod
    def from_jsonl(cls, path: Path) -> ReplayAdapter:
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

        key = compute_composite_key(request)

        rec = InteractionRecord(
            id=uuid.uuid4().hex[:16],
            model=request.model,
            prompt=request.prompt,
            response=response_text,
            composite_key=key,
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
                "composite_key": rec.composite_key,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            line = json.dumps({
                "id": rec.id,
                "model": rec.model,
                "prompt": rec.prompt,
                "response": rec.response,
                "composite_key": rec.composite_key,
                "metadata": rec.metadata,
            }, default=str)
            f.write(line + "\n")


def load_recordings(path: Path) -> list[InteractionRecord]:
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
                composite_key=data.get(
                    "composite_key",
                    data.get("prompt_hash", ""),
                ),
                metadata=data.get("metadata", {}),
            ))
    return records


# ============================================================
# INJECTION VIA CONTEXTVARS (NO GLOBAL MUTABLE STATE)
# ============================================================

_adapter_var: ContextVar[LLMAdapter | None] = ContextVar(
    "llm_adapter", default=None,
)


def install_adapter(adapter: LLMAdapter | None) -> Token:
    """Install adapter into context. Returns token for reset."""
    return _adapter_var.set(adapter)


def get_active_adapter() -> LLMAdapter | None:
    return _adapter_var.get()


def reset_adapter(token: Token) -> None:
    _adapter_var.reset(token)


class AdapterContext:
    """Context manager for safe adapter installation via contextvars.

    Restores previous value on exit. No global mutable state.
    """

    def __init__(self, adapter: LLMAdapter) -> None:
        self.adapter = adapter
        self.token: Token | None = None

    def __enter__(self) -> LLMAdapter:
        self.token = install_adapter(self.adapter)
        return self.adapter

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.token is not None:
            reset_adapter(self.token)
