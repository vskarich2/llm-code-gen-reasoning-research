"""Logging / WAL equivalence tests — prove legacy and graph emit compatible events.

Run: .venv/bin/python -m pytest core/tests/integration/test_logging_equivalence.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")

import pytest

from core.constants.pipeline_constants import (
    BACKEND_GRAPH_V1,
    BACKEND_LEGACY_V2,
    BACKEND_SHADOW,
)
from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    LLMRequest,
    LLMResponse,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASE_DATA = PROJECT_ROOT / "case_data"


# ============================================================
# RECORDING LOGGER
# ============================================================

class RecordingLogger:
    def __init__(self) -> None:
        self.end_case_calls: list[tuple] = []
        self.log_run_calls: list[tuple] = []
        self.start_case_calls: list[str] = []
        self.ctr = 0

    def start_case(self, case_id: str) -> Any:
        self.start_case_calls.append(case_id)

        class Handle:
            trace_id = "test_trace"
            event_id = 1
        return Handle()

    def end_case(self, *args: Any, **kwargs: Any) -> int:
        self.end_case_calls.append((args, kwargs))
        self.ctr += 1
        return self.ctr

    def log_run(self, *args: Any, **kwargs: Any) -> None:
        self.log_run_calls.append((args, kwargs))

    def log_call(self, **kwargs: Any) -> int:
        self.ctr += 1
        return self.ctr

    def log_structured_error(self, *a: Any, **kw: Any) -> None:
        pass

    def fail_case(self, *a: Any, **kw: Any) -> None:
        pass

    def new_trajectory(self) -> None:
        pass


# ============================================================
# ADAPTER
# ============================================================

class FixedAdapter:
    def __init__(self, gen_response: str) -> None:
        self.gen_response = gen_response

    def call(self, request: LLMRequest) -> LLMResponse:
        lower = request.prompt.lower()
        if "ground truth bug specification" in lower or "true mechanism" in lower:
            return LLMResponse(text="CORRECT\nOK.")
        if "bug_type:" in lower and "bug_location:" in lower:
            return LLMResponse(text="CORRECT\nOK.")
        if ("internal consistency" in lower
                and "reasoning_internal_consistency" in lower):
            return LLMResponse(text=json.dumps({
                "reasoning_internal_consistency": "CORRECT",
                "reasoning_internal_consistency_justification": "t",
                "commitments_internal_consistency": "CORRECT",
                "commitments_internal_consistency_justification": "t",
                "commitments_code_consistency": "CORRECT",
                "commitments_code_consistency_justification": "t",
                "reasoning_code_alignment": "CORRECT",
                "reasoning_code_alignment_justification": "t",
            }))
        return LLMResponse(text=self.gen_response)


# ============================================================
# HELPERS
# ============================================================

def load_case(case_id: str) -> tuple[dict, list]:
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


def build_fixed_response(case: dict, all_cases: list) -> str:
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    bug_file = case["reference_fix"]["file"]
    files = {}
    for fp in case["code_files"]:
        fn = fp.rsplit("/", 1)[-1]
        files[fn] = (
            ref_path.read_text() if fn == bug_file else "UNCHANGED"
        )
    return json.dumps({
        "root_cause": f"Bug in {bug_file}",
        "fix_strategy": "Fix directly",
        "code_commitments": ["Fix bug"],
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


# ============================================================
# TESTS
# ============================================================

CASE_ID = "logging_pipeline_chain"


class TestSingleAttemptLogEquivalence:

    def test_legacy_and_graph_same_log_call_counts(self, config):
        """Both backends emit end_case + log_run exactly once."""
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, all_cases = load_case(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        adapter = FixedAdapter(gen_resp)

        legacy_logger = RecordingLogger()
        graph_logger = RecordingLogger()

        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_LEGACY_V2
                _dispatch_single_attempt(
                    case, "gpt-4o-mini", "baseline_v3",
                    legacy_logger, 0,
                )

                config.execution.single_attempt_backend = BACKEND_GRAPH_V1
                _dispatch_single_attempt(
                    case, "gpt-4o-mini", "baseline_v3",
                    graph_logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original

        assert len(legacy_logger.end_case_calls) == 1, (
            f"Legacy: {len(legacy_logger.end_case_calls)} end_case calls"
        )
        assert len(graph_logger.end_case_calls) == 1, (
            f"Graph: {len(graph_logger.end_case_calls)} end_case calls"
        )
        assert len(legacy_logger.log_run_calls) == 1
        assert len(graph_logger.log_run_calls) == 1


class TestShadowLoggingSafety:

    def test_shadow_emits_canonical_legacy_events(self, config):
        """Shadow mode must emit ONLY legacy events as canonical."""
        from core.pipeline.orchestration.runner import (
            _dispatch_single_attempt,
        )
        case, all_cases = load_case(CASE_ID)
        gen_resp = build_fixed_response(case, all_cases)
        adapter = FixedAdapter(gen_resp)
        logger = RecordingLogger()

        original = config.execution.single_attempt_backend
        try:
            with AdapterContext(adapter):
                config.execution.single_attempt_backend = BACKEND_SHADOW
                _dispatch_single_attempt(
                    case, "gpt-4o-mini", "baseline_v3", logger, 0,
                )
        finally:
            config.execution.single_attempt_backend = original

        # Shadow must emit exactly 1 end_case (from legacy path)
        assert len(logger.end_case_calls) == 1
