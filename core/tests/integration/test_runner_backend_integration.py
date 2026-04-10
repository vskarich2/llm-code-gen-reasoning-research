"""Runner-level integration tests for backend dispatch, shadow safety,
logging compatibility, and config validation.

All tests use fixtures from core.tests.fixtures.pipeline_fixtures.
No hardcoded strings. No sys.path hacks. No raw install_adapter.

Run: .venv/bin/python -m pytest core/tests/integration/test_runner_backend_integration.py -v
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

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


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="module")
def config():
    return load_test_config()


@pytest.fixture(scope="module")
def case_id():
    return get_first_ddc_case_id()


@pytest.fixture
def case_and_response(case_id):
    case, all_cases = load_case_by_id(case_id)
    gen_resp = build_fixed_response(case, all_cases)
    return case, gen_resp


@pytest.fixture(autouse=True)
def enforce_no_adapter_leak():
    assert get_active_adapter() is None
    yield
    assert get_active_adapter() is None


# ============================================================
# BACKEND VALIDATION
# ============================================================

class TestBackendValidation:

    def test_invalid_single_attempt_backend_raises(self, config):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = "garbage"
            with pytest.raises(
                RuntimeError,
                match="Invalid execution.single_attempt_backend",
            ):
                _dispatch_single_attempt(
                    {}, "m", "bl", MagicMock(), 0,
                )
        finally:
            config.execution.single_attempt_backend = original

    def test_invalid_retry_backend_raises(self, config):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = "garbage"
            with pytest.raises(
                RuntimeError,
                match="Invalid execution.retry_backend",
            ):
                _dispatch_retry(
                    {}, "m", "crit", MagicMock(), 0,
                )
        finally:
            config.execution.retry_backend = original


# ============================================================
# DISPATCH ROUTING
# ============================================================

class TestSingleAttemptDispatch:

    def test_legacy_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        condition = get_first_single_attempt_condition(config)
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_LEGACY_V2
            with patch(
                "core.pipeline.orchestration.execution_v2.run_v2",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_single_attempt(
                    case_and_response[0], "m", condition, MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.single_attempt_backend = original

    def test_graph_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        condition = get_first_single_attempt_condition(config)
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_GRAPH_V1
            with patch(
                "side_projects.graph_runner.control.run_single_attempt"
                ".run_graph_v1",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_single_attempt(
                    case_and_response[0], "m", condition, MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.single_attempt_backend = original

    def test_shadow_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        condition = get_first_single_attempt_condition(config)
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_SHADOW
            with patch(
                "side_projects.graph_runner.control.shadow_compare.run_shadow",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_single_attempt(
                    case_and_response[0], "m", condition, MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.single_attempt_backend = original


class TestRetryDispatch:

    def test_legacy_retry_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_LEGACY_V2
            with patch(
                "core.pipeline.orchestration.retry_v2.run_retry_v2",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original

    def test_graph_retry_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_GRAPH_V1
            with patch(
                "side_projects.graph_runner.control.retry_controller"
                ".run_retry_graph",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original

    def test_shadow_retry_routes(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_SHADOW
            with patch(
                "side_projects.graph_runner.control.shadow_retry"
                ".run_shadow_retry",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original


# ============================================================
# SHADOW SAFETY
# ============================================================

class TestShadowSafety:

    def test_shadow_returns_legacy_when_graph_crashes(
        self, config, case_and_response,
    ):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        model = get_first_generation_model(config)
        condition = get_first_single_attempt_condition(config)
        adapter = PromptClassifyingAdapter(gen_resp)
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_SHADOW
            with AdapterContext(adapter):
                with patch(
                    "side_projects.graph_runner.control.run_single_attempt"
                    ".run_graph_v1",
                    side_effect=RuntimeError("boom"),
                ):
                    cid, cond, ev = _dispatch_single_attempt(
                        case, model, condition, RecordingLogger(), 0,
                    )
            assert ev.get("pass") is True
        finally:
            config.execution.single_attempt_backend = original


# ============================================================
# LOGGING COMPATIBILITY
# ============================================================

class TestLoggingCompatibility:

    def test_legacy_log_structure(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        model = get_first_generation_model(config)
        condition = get_first_single_attempt_condition(config)
        adapter = PromptClassifyingAdapter(gen_resp)
        logger = RecordingLogger()
        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_LEGACY_V2
                _dispatch_single_attempt(
                    case, model, condition, logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original
        assert len(logger.end_case_calls) == 1
        assert len(logger.log_run_calls) == 1

    def test_graph_log_structure(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        model = get_first_generation_model(config)
        condition = get_first_single_attempt_condition(config)
        adapter = PromptClassifyingAdapter(gen_resp)
        logger = RecordingLogger()
        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_GRAPH_V1
                _dispatch_single_attempt(
                    case, model, condition, logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original
        assert len(logger.end_case_calls) == 1
        assert len(logger.log_run_calls) == 1
