"""Logging / WAL equivalence tests.

Run: .venv/bin/python -m pytest core/tests/integration/test_logging_equivalence.py -v
"""

from __future__ import annotations

import pytest

from core.constants.pipeline_constants import (
    BACKEND_GRAPH_V1,
    BACKEND_LEGACY_V2,
    BACKEND_SHADOW,
)
from core.tests.fixtures.pipeline_fixtures import (
    PromptClassifyingAdapter,
    RecordingLogger,
    build_fixed_response,
    get_first_ddc_case_id,
    get_first_generation_model,
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


class TestSingleAttemptLogEquivalence:

    def test_legacy_and_graph_same_call_counts(self, config):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        model = get_first_generation_model(config)
        condition = get_first_single_attempt_condition(config)
        adapter = PromptClassifyingAdapter(gen_resp)

        legacy_log = RecordingLogger()
        graph_log = RecordingLogger()

        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_LEGACY_V2
                _dispatch_single_attempt(
                    case, model, condition, legacy_log, 0,
                )

            adapter2 = PromptClassifyingAdapter(gen_resp)
            with AdapterContext(adapter2):
                config.execution.single_attempt_backend = BACKEND_GRAPH_V1
                _dispatch_single_attempt(
                    case, model, condition, graph_log, 0,
                )
        finally:
            config.execution.single_attempt_backend = original

        assert len(legacy_log.end_case_calls) == 1
        assert len(graph_log.end_case_calls) == 1
        assert len(legacy_log.log_run_calls) == 1
        assert len(graph_log.log_run_calls) == 1


class TestShadowLoggingSafety:

    def test_shadow_emits_only_legacy_events(self, config):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, all_cases = load_case_by_id(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        model = get_first_generation_model(config)
        condition = get_first_single_attempt_condition(config)
        adapter = PromptClassifyingAdapter(gen_resp)
        logger = RecordingLogger()

        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_SHADOW
                _dispatch_single_attempt(
                    case, model, condition, logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original

        assert len(logger.end_case_calls) == 1
