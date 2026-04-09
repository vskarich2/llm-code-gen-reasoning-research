"""Full pipeline replay tests.

Runs the entire system (graph engine + retry controller + prompt system)
using RECORDED LLM responses. No API calls. Deterministic.

Run: .venv/bin/python -m pytest core/tests/integration/test_full_replay.py -v
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, ".")

import pytest

from side_projects.graph_runner.replay.adapter import (
    AdapterContext,
    InteractionRecord,
    LLMRequest,
    LLMResponse,
    ReplayAdapter,
    install_adapter,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASE_DATA = PROJECT_ROOT / "case_data"


# ============================================================
# FIXTURES: build deterministic recordings from case data
# ============================================================

def make_recording(prompt_text: str, response_text: str,
                   model: str = "gpt-4o-mini") -> InteractionRecord:
    return InteractionRecord(
        id=hashlib.sha256(prompt_text.encode()).hexdigest()[:16],
        model=model,
        prompt=prompt_text,
        response=response_text,
        prompt_hash=hashlib.sha256(prompt_text.encode()).hexdigest(),
    )


def build_oracle_response() -> str:
    return "CORRECT\nThe reasoning correctly identifies the root cause."


def build_classifier_response() -> str:
    return json.dumps({
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
    })


def build_generation_response(case: dict, all_cases: list) -> str:
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]
    files = {}
    for fp in case["code_files"]:
        filename = fp.rsplit("/", 1)[-1]
        files[filename] = ref_code if filename == bug_file else "UNCHANGED"
    return json.dumps({
        "root_cause": f"Bug in {bug_file}: incorrect logic",
        "fix_strategy": "Fix the root cause directly",
        "code_commitments": ["Must fix the identified bug"],
        "files": files,
    })


def load_case(case_id: str) -> tuple[dict, list]:
    with open(CASE_DATA / "cases_v2.json") as f:
        all_cases = json.load(f)
    case = next(c for c in all_cases if c["id"] == case_id)
    case = dict(case)
    contents = {}
    for fp in case["code_files"]:
        contents[fp] = (CASE_DATA / fp).read_text()
    case["code_files_contents"] = contents
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: content for fp, content in contents.items()
    }
    return case, all_cases


class CaptureAdapter:
    """Adapter that returns pre-built responses keyed by prompt content.

    Matches by checking if prompt contains specific keywords to determine
    if it's a generation, oracle, or classifier call.
    """

    def __init__(self, gen_response: str) -> None:
        self.gen_response = gen_response
        self.oracle_response = build_oracle_response()
        self.classifier_response = build_classifier_response()
        self.calls: list[dict] = []
        self.call_count = 0

    def call(self, request: Any) -> Any:
        from side_projects.graph_runner.replay.adapter import LLMResponse
        self.call_count += 1
        prompt_lower = request.prompt.lower()
        call_type = self.classify_call(prompt_lower)

        self.calls.append({
            "n": self.call_count,
            "model": request.model,
            "prompt_len": len(request.prompt),
            "type": call_type,
        })

        if call_type == "oracle":
            return LLMResponse(text=self.oracle_response)

        if call_type == "classifier":
            return LLMResponse(text=self.classifier_response)

        if call_type == "critique":
            return LLMResponse(
                text="The fix targets the wrong location.",
            )

        return LLMResponse(text=self.gen_response)

    def classify_call(self, prompt_lower: str) -> str:
        # Oracle: has ground truth bug spec markers
        if "ground truth bug specification" in prompt_lower:
            return "oracle"
        if "bug_type:" in prompt_lower and "bug_location:" in prompt_lower:
            return "oracle"
        if "true mechanism" in prompt_lower:
            return "oracle"
        # Classifier: has evaluation instruction markers
        if ("internal consistency" in prompt_lower
                and "commitments" in prompt_lower
                and "reasoning_internal_consistency" in prompt_lower):
            return "classifier"
        # Critique: mismatch analysis
        if "mismatch" in prompt_lower and "root cause:" in prompt_lower:
            return "critique"
        if "auditing consistency" in prompt_lower:
            return "critique"
        return "generation"


from typing import Any


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
    """Ensure adapter is uninstalled after each test."""
    yield
    install_adapter(None)


# NOTE: New tests should use AdapterContext instead of adapter_cleanup.
# Legacy tests below use adapter_cleanup for backward compat.


# ============================================================
# TEST 1 — Single attempt via graph engine (no API calls)
# ============================================================

class TestSingleAttemptReplay:

    def test_graph_single_attempt_no_api(
        self, config, adapter_cleanup,
    ):
        """Full graph pipeline with adapter — no mock.patch, no API calls.
        Adapter intercepts ALL call_model calls (generation, oracle, classifier).
        """
        case, all_cases = load_case("logging_pipeline_chain")
        gen_resp = build_generation_response(case, all_cases)
        adapter = CaptureAdapter(gen_resp)
        install_adapter(adapter)

        from side_projects.graph_runner.run_single_attempt import (
            run_graph_v1,
        )
        logger = MagicMock()
        cid, cond, ev = run_graph_v1(
            case, "gpt-4o-mini", "baseline_v3", logger, 0,
        )

        assert adapter.call_count >= 3, (
            f"Expected >= 3 adapter calls (gen + oracle + classifier), "
            f"got {adapter.call_count}"
        )
        gen_calls = [c for c in adapter.calls if c["type"] == "generation"]
        oracle_calls = [c for c in adapter.calls if c["type"] == "oracle"]
        assert len(gen_calls) >= 1, "Generation not called via adapter"
        assert len(oracle_calls) >= 1, "Oracle not called via adapter"
        assert ev.get("pass") is True

    def test_deterministic_output(self, config, adapter_cleanup):
        """Running twice produces identical results."""
        case, all_cases = load_case("logging_pipeline_chain")
        gen_resp = build_generation_response(case, all_cases)

        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )

        adapter1 = CaptureAdapter(gen_resp)
        install_adapter(adapter1)
        result1 = run_graph_pipeline(case, gen_resp, config)

        adapter2 = CaptureAdapter(gen_resp)
        install_adapter(adapter2)
        result2 = run_graph_pipeline(case, gen_resp, config)

        for key in ("exec_pass", "passed", "recon_status",
                     "artifact_id", "spec_oracle_depth", "parse_mode"):
            assert result1[key] == result2[key], (
                f"Non-deterministic: {key} "
                f"run1={result1[key]!r} run2={result2[key]!r}"
            )


# ============================================================
# TEST 2 — Retry path replay
# ============================================================

class TestRetryReplay:

    def test_retry_with_adapter(self, config, adapter_cleanup):
        case, all_cases = load_case("logging_pipeline_chain")
        gen_resp = build_generation_response(case, all_cases)
        adapter = CaptureAdapter(gen_resp)
        install_adapter(adapter)

        from core.pipeline.orchestration.retry_v2 import run_retry_v2
        logger = MagicMock()
        cid, cond, ev = run_retry_v2(
            case, "gpt-4o-mini", "critique_strict_v3", logger, 0,
        )

        assert ev.get("num_attempts", 0) >= 1
        assert ev.get("pass") is True
        assert adapter.call_count >= 1

    def test_retry_graph_with_adapter(
        self, config, adapter_cleanup,
    ):
        case, all_cases = load_case("logging_pipeline_chain")
        gen_resp = build_generation_response(case, all_cases)
        adapter = CaptureAdapter(gen_resp)
        install_adapter(adapter)

        from side_projects.graph_runner.retry_controller import (
            run_retry_graph,
        )
        logger = MagicMock()
        cid, cond, ev = run_retry_graph(
            case, "gpt-4o-mini", "critique_strict_v3", logger, 0,
        )

        assert ev.get("num_attempts", 0) >= 1
        assert ev.get("pass") is True


# ============================================================
# TEST 3 — Failure replay
# ============================================================

class TestFailureReplay:

    def test_buggy_case_fails(self, config, adapter_cleanup):
        """UNCHANGED response produces failure, not crash."""
        case, _ = load_case("logging_pipeline_chain")
        buggy = json.dumps({
            "root_cause": "No issue found",
            "fix_strategy": "No change",
            "code_commitments": ["None"],
            "files": {
                fp.rsplit("/", 1)[-1]: "UNCHANGED"
                for fp in case["code_files"]
            },
        })
        adapter = CaptureAdapter(buggy)
        install_adapter(adapter)

        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )
        result = run_graph_pipeline(case, buggy, config)
        assert result["exec_pass"] is False
        assert result["passed"] is False

    def test_parse_failure_no_crash(self, config, adapter_cleanup):
        """Malformed JSON response doesn't crash the pipeline."""
        case, _ = load_case("logging_pipeline_chain")
        adapter = CaptureAdapter("THIS IS NOT JSON")
        install_adapter(adapter)

        from side_projects.graph_runner.validation.equivalence import (
            run_graph_pipeline,
        )
        result = run_graph_pipeline(case, "THIS IS NOT JSON", config)
        assert result["parsed_generation_valid"] is False


# ============================================================
# TEST 4 — Adapter isolation
# ============================================================

class TestAdapterIsolation:

    def test_adapter_uninstall(self, adapter_cleanup):
        """After uninstall, no adapter is active."""
        from side_projects.graph_runner.replay.adapter import (
            get_active_adapter,
        )
        install_adapter(None)
        assert get_active_adapter() is None

    def test_replay_adapter_hard_fail_on_miss(self):
        """ReplayAdapter raises KeyError on unknown prompt."""
        adapter = ReplayAdapter([])
        from side_projects.graph_runner.replay.adapter import LLMRequest
        with pytest.raises(KeyError):
            adapter.call(LLMRequest(model="m", prompt="unknown"))

    def test_replay_adapter_exact_match(self):
        """ReplayAdapter returns exact recorded response."""
        rec = make_recording("hello", "world")
        adapter = ReplayAdapter([rec])
        from side_projects.graph_runner.replay.adapter import LLMRequest
        resp = adapter.call(LLMRequest(model="m", prompt="hello"))
        assert resp.text == "world"
