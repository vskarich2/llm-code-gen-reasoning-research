"""Adapter isolation tests — prove replay state does not leak.

Run: .venv/bin/python -m pytest core/tests/integration/test_adapter_isolation.py -v
"""

from __future__ import annotations

import pytest

from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    LLMRequest,
    LLMResponse,
    ReplayAdapter,
    InteractionRecord,
    compute_composite_key,
    get_active_adapter,
)


class StubAdapter:
    def __init__(self) -> None:
        self.call_count = 0

    def call(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(text="stub")


class TestAdapterContextManager:

    def test_installs_and_restores(self) -> None:
        assert get_active_adapter() is None
        stub = StubAdapter()
        with AdapterContext(stub):
            assert get_active_adapter() is stub
        assert get_active_adapter() is None

    def test_restores_on_exception(self) -> None:
        assert get_active_adapter() is None
        with pytest.raises(ValueError):
            with AdapterContext(StubAdapter()):
                raise ValueError("boom")
        assert get_active_adapter() is None

    def test_nested_contexts(self) -> None:
        s1, s2 = StubAdapter(), StubAdapter()
        with AdapterContext(s1):
            assert get_active_adapter() is s1
            with AdapterContext(s2):
                assert get_active_adapter() is s2
            assert get_active_adapter() is s1
        assert get_active_adapter() is None


class TestAdapterIsolationAcrossTests:

    def test_none_at_start(self) -> None:
        assert get_active_adapter() is None

    def test_does_not_leak(self) -> None:
        with AdapterContext(StubAdapter()):
            pass
        assert get_active_adapter() is None

    def test_still_none(self) -> None:
        assert get_active_adapter() is None


class TestReplayAdapterFailFast:

    def test_missing_prompt_raises(self) -> None:
        adapter = ReplayAdapter([])
        with pytest.raises(KeyError, match="no recorded response"):
            adapter.call(LLMRequest(model="m", prompt="unknown"))

    def test_exact_match(self) -> None:
        prompt = "exact prompt"
        req = LLMRequest(model="m", prompt=prompt)
        key = compute_composite_key(req)
        rec = InteractionRecord(
            id="r1", model="m", prompt=prompt,
            response="recorded", composite_key=key,
        )
        adapter = ReplayAdapter([rec])
        resp = adapter.call(req)
        assert resp.text == "recorded"

    def test_wrong_prompt_raises(self) -> None:
        req_correct = LLMRequest(model="m", prompt="correct")
        rec = InteractionRecord(
            id="r1", model="m", prompt="correct",
            response="resp",
            composite_key=compute_composite_key(req_correct),
        )
        adapter = ReplayAdapter([rec])
        with pytest.raises(KeyError):
            adapter.call(LLMRequest(model="m", prompt="wrong"))

    def test_different_model_no_match(self) -> None:
        """Same prompt but different model must not match."""
        prompt = "shared prompt"
        req_a = LLMRequest(model="model_a", prompt=prompt)
        rec = InteractionRecord(
            id="r1", model="model_a", prompt=prompt,
            response="resp",
            composite_key=compute_composite_key(req_a),
        )
        adapter = ReplayAdapter([rec])
        with pytest.raises(KeyError):
            adapter.call(LLMRequest(model="model_b", prompt=prompt))

    def test_duplicate_key_rejected_at_load(self) -> None:
        req = LLMRequest(model="m", prompt="p")
        key = compute_composite_key(req)
        recs = [
            InteractionRecord(
                id="r1", model="m", prompt="p",
                response="a", composite_key=key,
            ),
            InteractionRecord(
                id="r2", model="m", prompt="p",
                response="b", composite_key=key,
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate composite key"):
            ReplayAdapter(recs)


@pytest.fixture(autouse=True)
def enforce_no_leak():
    """Prove adapter never leaks across tests."""
    assert get_active_adapter() is None
    yield
    assert get_active_adapter() is None
