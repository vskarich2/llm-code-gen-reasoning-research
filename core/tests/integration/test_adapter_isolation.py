"""Adapter isolation tests — prove replay state does not leak.

Run: .venv/bin/python -m pytest core/tests/integration/test_adapter_isolation.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import pytest

from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    LLMRequest,
    LLMResponse,
    ReplayAdapter,
    get_active_adapter,
    install_adapter,
    InteractionRecord,
)


class StubAdapter:
    """Minimal adapter for isolation testing."""

    def __init__(self) -> None:
        self.call_count = 0

    def call(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(text="stub")


class TestAdapterContextManager:

    def test_context_installs_and_restores(self) -> None:
        assert get_active_adapter() is None
        stub = StubAdapter()
        with AdapterContext(stub):
            assert get_active_adapter() is stub
        assert get_active_adapter() is None

    def test_context_restores_on_exception(self) -> None:
        assert get_active_adapter() is None
        stub = StubAdapter()
        with pytest.raises(ValueError):
            with AdapterContext(stub):
                assert get_active_adapter() is stub
                raise ValueError("boom")
        assert get_active_adapter() is None

    def test_nested_contexts(self) -> None:
        stub1 = StubAdapter()
        stub2 = StubAdapter()
        with AdapterContext(stub1):
            assert get_active_adapter() is stub1
            with AdapterContext(stub2):
                assert get_active_adapter() is stub2
            assert get_active_adapter() is stub1
        assert get_active_adapter() is None


class TestAdapterIsolationAcrossTests:

    def test_no_adapter_at_start(self) -> None:
        """Adapter must be None at test start."""
        assert get_active_adapter() is None

    def test_adapter_does_not_leak(self) -> None:
        """After context exits, adapter is None."""
        stub = StubAdapter()
        with AdapterContext(stub):
            resp = stub.call(LLMRequest(model="m", prompt="p"))
            assert resp.text == "stub"
        assert get_active_adapter() is None

    def test_still_none_after_previous_test(self) -> None:
        """Prove previous test did not leak state."""
        assert get_active_adapter() is None


class TestReplayAdapterFailFast:

    def test_missing_prompt_raises_keyerror(self) -> None:
        adapter = ReplayAdapter([])
        with pytest.raises(KeyError, match="no recorded response"):
            adapter.call(LLMRequest(model="m", prompt="unknown"))

    def test_exact_match_returns_recorded(self) -> None:
        import hashlib
        prompt = "exact prompt text"
        rec = InteractionRecord(
            id="rec1",
            model="m",
            prompt=prompt,
            response="recorded response",
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
        )
        adapter = ReplayAdapter([rec])
        resp = adapter.call(LLMRequest(model="m", prompt=prompt))
        assert resp.text == "recorded response"

    def test_wrong_prompt_raises_even_with_records(self) -> None:
        import hashlib
        rec = InteractionRecord(
            id="rec1",
            model="m",
            prompt="correct prompt",
            response="response",
            prompt_hash=hashlib.sha256(b"correct prompt").hexdigest(),
        )
        adapter = ReplayAdapter([rec])
        with pytest.raises(KeyError):
            adapter.call(LLMRequest(model="m", prompt="wrong prompt"))
