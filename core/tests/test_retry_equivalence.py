"""Retry equivalence tests: transitional retry controller vs legacy retry_v2.

Run: .venv/bin/python -m pytest core/tests/test_retry_equivalence.py -v
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from core.constants.pipeline_constants import (
    BACKEND_GRAPH_V1,
    BACKEND_LEGACY_V2,
)
from core.tests.fixtures.pipeline_fixtures import (
    build_fixed_response,
    get_first_ddc_case_id,
    get_first_generation_model,
    get_first_retry_condition,
    load_case_by_id,
    load_test_config,
    build_classifier_response,
    RecordingLogger,
)
from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    LLMRequest,
    LLMResponse,
    get_active_adapter,
)
from side_projects.graph_runner.shadow_retry import compare_retry_results

CASE_ID = get_first_ddc_case_id()


@pytest.fixture(scope="module")
def config():
    return load_test_config()


@pytest.fixture(autouse=True)
def enforce_no_leak():
    assert get_active_adapter() is None
    yield
    assert get_active_adapter() is None


def make_combined_adapter(gen_resp: str) -> object:
    """Adapter returning fixed gen + oracle + classifier responses."""
    class Adapter:
        def call(self, request: LLMRequest) -> LLMResponse:
            lower = request.prompt.lower()
            if ("ground truth" in lower
                    or "true mechanism" in lower
                    or "bug_type:" in lower):
                return LLMResponse(text="CORRECT\nOK.", request_id="o")
            if ("internal consistency" in lower
                    and "reasoning_internal_consistency" in lower):
                return LLMResponse(
                    text=build_classifier_response(), request_id="c",
                )
            if "mismatch" in lower or "auditing" in lower:
                return LLMResponse(text="Fix is wrong.", request_id="cr")
            return LLMResponse(text=gen_resp, request_id="g")
    return Adapter()


def run_legacy(case, condition, config, adapter):
    from core.pipeline.orchestration.retry_v2 import run_retry_v2
    model = get_first_generation_model(config)
    logger = RecordingLogger()
    with AdapterContext(adapter):
        _, _, ev = run_retry_v2(case, model, condition, logger, 0)
    return ev


def run_graph(case, condition, config, adapter):
    from side_projects.graph_runner.retry_controller import run_retry_graph
    model = get_first_generation_model(config)
    logger = RecordingLogger()
    with AdapterContext(adapter):
        _, _, ev = run_retry_graph(case, model, condition, logger, 0)
    return ev


class TestRetryEquivalence:

    def test_single_attempt_pass(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        condition = get_first_retry_condition(config)

        adapter = make_combined_adapter(gen_resp)
        legacy = run_legacy(case, condition, config, adapter)

        adapter2 = make_combined_adapter(gen_resp)
        graph = run_graph(case, condition, config, adapter2)

        diffs = compare_retry_results(CASE_ID, legacy, graph)
        if diffs:
            lines = [f"MISMATCH ({len(diffs)} diffs):"]
            for d in diffs:
                lines.append(
                    f"  {d.get('attempt_index', 'final')} "
                    f"{d['field']}: L={d['legacy']!r} G={d['graph']!r}"
                )
            pytest.fail("\n".join(lines))

    def test_trajectory_length(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        condition = get_first_retry_condition(config)

        legacy = run_legacy(
            case, condition, config, make_combined_adapter(gen_resp),
        )
        graph = run_graph(
            case, condition, config, make_combined_adapter(gen_resp),
        )

        assert legacy.get("num_attempts") == graph.get("num_attempts")

    def test_best_attempt_selection(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        condition = get_first_retry_condition(config)

        legacy = run_legacy(
            case, condition, config, make_combined_adapter(gen_resp),
        )
        graph = run_graph(
            case, condition, config, make_combined_adapter(gen_resp),
        )

        assert (
            legacy.get("best_attempt_idx")
            == graph.get("best_attempt_idx")
        )


class TestDispatchRouting:

    def test_default_is_legacy(self, config):
        backend = getattr(
            config.execution, "retry_backend", BACKEND_LEGACY_V2,
        )
        assert backend == BACKEND_LEGACY_V2

    def test_dispatch_importable(self):
        from core.pipeline.orchestration.runner import _dispatch_retry
        assert callable(_dispatch_retry)

    def test_retry_controller_importable(self):
        from side_projects.graph_runner.retry_controller import (
            run_retry_graph,
        )
        assert callable(run_retry_graph)

    def test_shadow_retry_importable(self):
        from side_projects.graph_runner.shadow_retry import (
            run_shadow_retry,
        )
        assert callable(run_shadow_retry)
