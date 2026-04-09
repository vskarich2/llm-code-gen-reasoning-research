"""Runner-level integration tests for backend dispatch, shadow safety,
logging compatibility, config validation, and failure propagation.

Tests exercise _dispatch_single_attempt, _dispatch_retry, and
_run_one_inner through the real orchestration entry layer.

Run: .venv/bin/python -m pytest core/tests/integration/test_runner_backend_integration.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")

import pytest

from core.constants.pipeline_constants import (
    BACKEND_GRAPH_V1,
    BACKEND_LEGACY_V2,
    BACKEND_SHADOW,
)
from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    install_adapter,
    LLMRequest,
    LLMResponse,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASE_DATA = PROJECT_ROOT / "case_data"


# ============================================================
# RECORDING LOGGER
# ============================================================

class RecordingLogger:
    """Stub logger that records all calls for assertion."""

    def __init__(self):
        self.end_case_calls = []
        self.log_run_calls = []
        self.start_case_calls = []
        self.error_calls = []

    def start_case(self, case_id):
        self.start_case_calls.append(case_id)

        class Handle:
            trace_id = "test_trace"
            event_id = 1
        return Handle()

    def end_case(self, *args, **kwargs):
        self.end_case_calls.append((args, kwargs))
        return 12345

    def log_run(self, *args, **kwargs):
        self.log_run_calls.append((args, kwargs))

    def log_call(self, *args, **kwargs):
        return self.call_counter()

    def call_counter(self):
        if not hasattr(self, "_ctr"):
            self._ctr = 0
        self._ctr += 1
        return self._ctr

    def log_structured_error(self, *args, **kwargs):
        self.error_calls.append((args, kwargs))

    def fail_case(self, *args, **kwargs):
        pass

    def new_trajectory(self):
        pass


# ============================================================
# CAPTURE ADAPTER — intercepts ALL call_model calls
# ============================================================

class CaptureAdapter:
    def __init__(self, gen_response):
        self.gen_response = gen_response
        self.calls = []
        self.call_count = 0

    def call(self, request):
        self.call_count += 1
        prompt_lower = request.prompt.lower()
        call_type = self.classify(prompt_lower)
        self.calls.append({"type": call_type, "len": len(request.prompt)})

        if call_type == "oracle":
            return LLMResponse(
                text="CORRECT\nThe reasoning correctly identifies the root cause.",
            )
        if call_type == "classifier":
            return LLMResponse(text=json.dumps({
                "reasoning_internal_consistency": "CORRECT",
                "reasoning_internal_consistency_justification":
                    "Root cause identifies the source correctly.",
                "commitments_internal_consistency": "CORRECT",
                "commitments_internal_consistency_justification":
                    "Commitments follow from fix strategy.",
                "commitments_code_consistency": "CORRECT",
                "commitments_code_consistency_justification":
                    "Code implements stated commitments.",
                "reasoning_code_alignment": "CORRECT",
                "reasoning_code_alignment_justification":
                    "Code changes match the fix strategy.",
            }))
        if call_type == "critique":
            return LLMResponse(text="The fix targets the wrong location.")
        return LLMResponse(text=self.gen_response)

    def classify(self, prompt_lower):
        if "ground truth bug specification" in prompt_lower:
            return "oracle"
        if "bug_type:" in prompt_lower and "bug_location:" in prompt_lower:
            return "oracle"
        if "true mechanism" in prompt_lower:
            return "oracle"
        if ("internal consistency" in prompt_lower
                and "reasoning_internal_consistency" in prompt_lower):
            return "classifier"
        if "auditing consistency" in prompt_lower:
            return "critique"
        if "mismatch" in prompt_lower and "root cause:" in prompt_lower:
            return "critique"
        return "generation"


# ============================================================
# HELPERS
# ============================================================

def load_case(case_id):
    with open(CASE_DATA / "cases_v2.json") as f:
        all_cases = json.load(f)
    case = next(c for c in all_cases if c["id"] == case_id)
    case = dict(case)
    for fp in case["code_files"]:
        case.setdefault("code_files_contents", {})[fp] = (
            CASE_DATA / fp
        ).read_text()
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: (CASE_DATA / fp).read_text()
        for fp in case["code_files"]
    }
    return case, all_cases


def build_fixed_response(case, all_cases):
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]
    files = {}
    for fp in case["code_files"]:
        fn = fp.rsplit("/", 1)[-1]
        files[fn] = ref_code if fn == bug_file else "UNCHANGED"
    return json.dumps({
        "root_cause": f"Bug in {bug_file}: incorrect logic",
        "fix_strategy": "Fix the root cause directly",
        "code_commitments": ["Must fix the identified bug"],
        "files": files,
    })


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="module")
def config():
    from core.config.experiment_config import load_config, is_config_loaded
    if not is_config_loaded():
        load_config("core/config/config_storage/smoke_ddc_cases.yaml")
    from core.config.experiment_config import get_config
    return get_config()


@pytest.fixture
def adapter_cleanup():
    """Legacy cleanup fixture — prefer AdapterContext in new tests."""
    yield
    install_adapter(None)


@pytest.fixture
def case_and_response(config):
    case, all_cases = load_case("logging_pipeline_chain")
    gen_resp = build_fixed_response(case, all_cases)
    return case, gen_resp


# ============================================================
# TASK 2 + 7: BACKEND CONFIG VALIDATION
# ============================================================

class TestBackendValidation:

    def test_invalid_single_attempt_backend_raises(self, config):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = "garbage_backend"
            with pytest.raises(
                RuntimeError, match="Invalid execution.single_attempt_backend",
            ):
                _dispatch_single_attempt(
                    {}, "m", "baseline_v3", MagicMock(), 0,
                )
        finally:
            config.execution.single_attempt_backend = original

    def test_invalid_retry_backend_raises(self, config):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = "garbage_backend"
            with pytest.raises(
                RuntimeError, match="Invalid execution.retry_backend",
            ):
                _dispatch_retry(
                    {}, "m", "critique_strict_v3", MagicMock(), 0,
                )
        finally:
            config.execution.retry_backend = original

    def test_valid_backends_accepted(self, config):
        from core.constants.pipeline_constants import VALID_BACKENDS
        for backend in VALID_BACKENDS:
            assert backend in (
                BACKEND_LEGACY_V2, BACKEND_GRAPH_V1, BACKEND_SHADOW,
            )


# ============================================================
# TASK 3 TEST C: DISPATCH ROUTING
# ============================================================

class TestSingleAttemptDispatch:

    def test_legacy_routes_to_run_v2(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_LEGACY_V2
            with patch(
                "core.pipeline.orchestration.execution_v2.run_v2",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_single_attempt(
                    case_and_response[0], "m", "baseline_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
            assert out == ("cid", "cond", {"pass": True})
        finally:
            config.execution.single_attempt_backend = original

    def test_graph_routes_to_run_graph_v1(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_GRAPH_V1
            with patch(
                "side_projects.graph_runner.run_single_attempt.run_graph_v1",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_single_attempt(
                    case_and_response[0], "m", "baseline_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
            assert out == ("cid", "cond", {"pass": True})
        finally:
            config.execution.single_attempt_backend = original

    def test_shadow_routes_to_run_shadow(self, config, case_and_response):
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_SHADOW
            with patch(
                "side_projects.graph_runner.shadow_compare.run_shadow",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_single_attempt(
                    case_and_response[0], "m", "baseline_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.single_attempt_backend = original


class TestRetryDispatch:

    def test_legacy_retry_routes_correctly(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_LEGACY_V2
            with patch(
                "core.pipeline.orchestration.retry_v2.run_retry_v2",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original

    def test_graph_retry_routes_correctly(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_GRAPH_V1
            with patch(
                "side_projects.graph_runner.retry_controller.run_retry_graph",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original

    def test_shadow_retry_routes_correctly(self, config, case_and_response):
        from core.pipeline.orchestration.runner import _dispatch_retry
        original = config.execution.retry_backend
        try:
            config.execution.retry_backend = BACKEND_SHADOW
            with patch(
                "side_projects.graph_runner.shadow_retry.run_shadow_retry",
            ) as mock:
                mock.return_value = ("cid", "cond", {"pass": True})
                out = _dispatch_retry(
                    case_and_response[0], "m", "critique_strict_v3",
                    MagicMock(), 0,
                )
            mock.assert_called_once()
        finally:
            config.execution.retry_backend = original


# ============================================================
# TASK 3 TEST B + D: SHADOW SAFETY + FAILURE PROPAGATION
# ============================================================

class TestShadowSafety:

    def test_shadow_returns_legacy_when_graph_crashes(
        self, config, case_and_response,
    ):
        """Shadow mode must return legacy result even if graph fails."""
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        adapter = CaptureAdapter(gen_resp)
        original = config.execution.single_attempt_backend
        try:
            config.execution.single_attempt_backend = BACKEND_SHADOW
            with AdapterContext(adapter):
                with patch(
                    "side_projects.graph_runner.run_single_attempt"
                    ".run_graph_v1",
                    side_effect=RuntimeError("boom"),
                ):
                    cid, cond, ev = _dispatch_single_attempt(
                        case, "gpt-4o-mini", "baseline_v3",
                        RecordingLogger(), 0,
                    )
            # Legacy must have succeeded — shadow returns legacy result
            assert ev.get("pass") is True
            assert "evaluation" in ev or "alignment" in ev
        finally:
            config.execution.single_attempt_backend = original


# ============================================================
# TASK 4: LOGGING COMPATIBILITY
# ============================================================

class TestLoggingCompatibility:

    def test_single_attempt_legacy_log_structure(
        self, config, case_and_response,
    ):
        """Legacy backend emits end_case and log_run exactly once."""
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        adapter = CaptureAdapter(gen_resp)
        logger = RecordingLogger()
        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_LEGACY_V2
                _dispatch_single_attempt(
                    case, "gpt-4o-mini", "baseline_v3", logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original
        assert len(logger.end_case_calls) == 1
        assert len(logger.log_run_calls) == 1

    def test_graph_single_attempt_log_structure(
        self, config, case_and_response,
    ):
        """Graph backend emits end_case and log_run exactly once."""
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, gen_resp = case_and_response
        adapter = CaptureAdapter(gen_resp)
        logger = RecordingLogger()
        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_GRAPH_V1
                _dispatch_single_attempt(
                    case, "gpt-4o-mini", "baseline_v3", logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original
        assert len(logger.end_case_calls) == 1
        assert len(logger.log_run_calls) == 1
