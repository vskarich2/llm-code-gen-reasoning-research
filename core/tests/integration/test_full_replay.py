"""Full pipeline replay tests via adapter injection. No API calls.

Run: .venv/bin/python -m pytest core/tests/integration/test_full_replay.py -v
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.tests.fixtures.pipeline_fixtures import (
    PromptClassifyingAdapter,
    RecordingLogger,
    build_buggy_response,
    build_fixed_response,
    get_first_ddc_case_id,
    get_first_generation_model,
    get_first_retry_condition,
    get_first_single_attempt_condition,
    load_case_by_id,
    load_test_config,
)
from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    get_active_adapter,
)

CASE_ID = get_first_ddc_case_id()


@pytest.fixture(scope="module")
def config():
    return load_test_config()


@pytest.fixture(autouse=True)
def enforce_no_leak():
    assert get_active_adapter() is None
    yield
    assert get_active_adapter() is None


class TestSingleAttemptReplay:

    def test_graph_via_adapter(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        model = get_first_generation_model(config)
        adapter = PromptClassifyingAdapter(gen_resp)

        condition = get_first_single_attempt_condition(config)
        with AdapterContext(adapter):
            from side_projects.graph_runner.control.run_single_attempt import (
                run_graph_v1,
            )
            cid, cond, ev = run_graph_v1(
                case, model, condition, RecordingLogger(), 0,
            )

        assert adapter.call_count >= 3
        gen_calls = [c for c in adapter.calls if c["type"] == "generation"]
        assert len(gen_calls) >= 1

    def test_deterministic(self, config):
        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)

        r1 = run_graph_pipeline(case, gen_resp, config)
        r2 = run_graph_pipeline(case, gen_resp, config)

        for key in ("exec_pass", "passed", "recon_status", "artifact_id"):
            assert r1[key] == r2[key], (
                f"Non-deterministic: {key} "
                f"run1={r1[key]!r} run2={r2[key]!r}"
            )


class TestRetryReplay:

    def test_retry_legacy_via_adapter(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        model = get_first_generation_model(config)
        adapter = PromptClassifyingAdapter(gen_resp)

        with AdapterContext(adapter):
            from core.pipeline.orchestration.retry_v2 import run_retry_v2
            cid, cond, ev = run_retry_v2(
                case, model, get_first_retry_condition(config),
                RecordingLogger(), 0,
            )

        assert ev.get("num_attempts", 0) >= 1
        assert adapter.call_count >= 1

    def test_retry_graph_via_adapter(self, config):
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        model = get_first_generation_model(config)
        adapter = PromptClassifyingAdapter(gen_resp)

        with AdapterContext(adapter):
            from side_projects.graph_runner.control.retry_controller import (
                run_retry_graph,
            )
            cid, cond, ev = run_retry_graph(
                case, model, get_first_retry_condition(config),
                RecordingLogger(), 0,
            )

        assert ev.get("num_attempts", 0) >= 1


class TestFailureReplay:

    def test_buggy_case_fails(self, config):
        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )
        case, _ = load_case_by_id(CASE_ID)
        buggy = build_buggy_response(case)
        result = run_graph_pipeline(case, buggy, config)
        assert result["exec_pass"] is False
        assert result["passed"] is False

    def test_parse_failure_no_crash(self, config):
        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )
        case, _ = load_case_by_id(CASE_ID)
        result = run_graph_pipeline(case, "NOT JSON", config)
        assert result["parsed_generation_valid"] is False
