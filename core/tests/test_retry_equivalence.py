"""Retry equivalence tests: graph retry controller vs legacy retry_v2.

Runs the same mocked LLM responses through both retry backends and
compares trajectories + final outputs. Any mismatch is a migration bug.

Run: .venv/bin/python -m pytest core/tests/test_retry_equivalence.py -v
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")

import pytest

from side_projects.graph_runner.shadow_retry import compare_retry_results

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DATA = PROJECT_ROOT / "case_data"


# ── Mock LLM ──

ATTEMPT_COUNTER = {"n": 0}


def mock_call_model_pass_second(prompt, model, **kwargs):
    """Mock: fail on attempt 0, pass on attempt 1."""
    from core.pipeline.llm import ModelCallResult
    prompt_lower = prompt.lower()

    if "ground truth" in prompt_lower or "mechanism" in prompt_lower or "bug_type" in prompt_lower:
        return ModelCallResult(
            response="CORRECT\nCorrect mechanism.",
            event_id=kwargs.get("parent_event_id") or 1,
        )

    if "reasoning" in prompt_lower and "commitments" in prompt_lower:
        response = json.dumps({
            "reasoning_internal_consistency": "CORRECT",
            "reasoning_internal_consistency_justification": "test",
            "commitments_internal_consistency": "CORRECT",
            "commitments_internal_consistency_justification": "test",
            "commitments_code_consistency": "CORRECT",
            "commitments_code_consistency_justification": "test",
            "reasoning_code_alignment": "CORRECT",
            "reasoning_code_alignment_justification": "test",
        })
        return ModelCallResult(
            response=response,
            event_id=kwargs.get("parent_event_id") or 2,
        )

    if "mismatch" in prompt_lower or "critique" in prompt_lower:
        return ModelCallResult(
            response="The fix strategy targets the wrong module.",
            event_id=kwargs.get("parent_event_id") or 3,
        )

    return ModelCallResult(
        response="UNJUDGABLE\nNo data",
        event_id=kwargs.get("parent_event_id") or 4,
    )


# ── Fixtures ──

@pytest.fixture(scope="module")
def config():
    from core.config.experiment_config import load_config, is_config_loaded
    if not is_config_loaded():
        load_config("core/config/config_storage/smoke_ddc_cases.yaml")
    from core.config.experiment_config import get_config
    return get_config()


@pytest.fixture(scope="module")
def all_cases():
    with open(CASE_DATA / "cases_v2.json") as f:
        return json.load(f)


def load_case(case_id, all_cases):
    case = next(c for c in all_cases if c["id"] == case_id)
    case = dict(case)
    contents = {}
    for fp in case["code_files"]:
        contents[fp] = (CASE_DATA / fp).read_text()
    case["code_files_contents"] = contents
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: content for fp, content in contents.items()
    }
    return case


def build_fixed_response(case, all_cases):
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]
    files = {}
    for fp in case["code_files"]:
        filename = fp.rsplit("/", 1)[-1]
        if filename == bug_file:
            files[filename] = ref_code
        else:
            files[filename] = "UNCHANGED"
    return json.dumps({
        "root_cause": f"Bug in {bug_file}",
        "fix_strategy": "Fix the root cause",
        "code_commitments": ["Fix must correct behavior"],
        "files": files,
    })


# ── Run helpers ──

def run_legacy_retry(case, condition, config, mock_fn):
    """Run legacy retry_v2 with mocked LLM."""
    from core.pipeline.orchestration.retry_v2 import run_retry_v2
    logger = MagicMock()
    # Must patch at BOTH the definition site and the import site
    with (
        patch("core.pipeline.llm.call_model", side_effect=mock_fn),
        patch("core.pipeline.orchestration.retry_v2.call_model", side_effect=mock_fn),
    ):
        cid, cond, ev = run_retry_v2(case, "test-model", condition, logger, 0)
    return ev


def run_graph_retry(case, condition, config, mock_fn):
    """Run graph retry controller with mocked LLM."""
    from side_projects.graph_runner.retry_controller import run_retry_graph
    logger = MagicMock()
    with (
        patch("core.pipeline.llm.call_model", side_effect=mock_fn),
        patch("core.pipeline.orchestration.retry_v2.call_model", side_effect=mock_fn),
    ):
        cid, cond, ev = run_retry_graph(
            case, "test-model", condition, logger, 0,
        )
    return ev


# ── Tests ──

class TestRetryEquivalence:
    """Graph retry must produce identical results to legacy retry."""

    def test_single_attempt_pass(self, config, all_cases):
        """Case passes on attempt 0 → no retry."""
        case = load_case("logging_pipeline_chain", all_cases)
        fixed_resp = build_fixed_response(case, all_cases)

        def combined_mock(prompt, model, **kwargs):
            from core.pipeline.llm import ModelCallResult
            lower = prompt.lower()
            if "ground truth" in lower or "mechanism" in lower or "bug_type" in lower:
                return ModelCallResult(
                    response="CORRECT\nCorrect mechanism.",
                    event_id=kwargs.get("parent_event_id") or 1,
                )
            if "reasoning" in lower and "commitments" in lower:
                return ModelCallResult(
                    response=json.dumps({
                        "reasoning_internal_consistency": "CORRECT",
                        "reasoning_internal_consistency_justification": "t",
                        "commitments_internal_consistency": "CORRECT",
                        "commitments_internal_consistency_justification": "t",
                        "commitments_code_consistency": "CORRECT",
                        "commitments_code_consistency_justification": "t",
                        "reasoning_code_alignment": "CORRECT",
                        "reasoning_code_alignment_justification": "t",
                    }),
                    event_id=kwargs.get("parent_event_id") or 2,
                )
            # Generation call
            return ModelCallResult(
                response=fixed_resp,
                event_id=kwargs.get("parent_event_id") or 3,
            )

        legacy = run_legacy_retry(case, "critique_strict_v3", config, combined_mock)
        graph = run_graph_retry(case, "critique_strict_v3", config, combined_mock)

        diffs = compare_retry_results(case["id"], legacy, graph)
        if diffs:
            lines = [f"MISMATCH ({len(diffs)} diffs):"]
            for d in diffs:
                lines.append(
                    f"  {d.get('attempt_index', 'final')} "
                    f"{d['field']}: L={d['legacy']!r} G={d['graph']!r}"
                )
            pytest.fail("\n".join(lines))

    def test_trajectory_structure(self, config, all_cases):
        """Both backends produce trajectory with same length."""
        case = load_case("logging_pipeline_chain", all_cases)
        fixed_resp = build_fixed_response(case, all_cases)

        def mock_fn(prompt, model, **kwargs):
            from core.pipeline.llm import ModelCallResult
            lower = prompt.lower()
            if "ground truth" in lower or "mechanism" in lower or "bug_type" in lower:
                return ModelCallResult(
                    response="CORRECT\nOK.", event_id=1,
                )
            if "reasoning" in lower and "commitments" in lower:
                return ModelCallResult(
                    response=json.dumps({
                        "reasoning_internal_consistency": "CORRECT",
                        "reasoning_internal_consistency_justification": "t",
                        "commitments_internal_consistency": "CORRECT",
                        "commitments_internal_consistency_justification": "t",
                        "commitments_code_consistency": "CORRECT",
                        "commitments_code_consistency_justification": "t",
                        "reasoning_code_alignment": "CORRECT",
                        "reasoning_code_alignment_justification": "t",
                    }),
                    event_id=2,
                )
            return ModelCallResult(response=fixed_resp, event_id=3)

        legacy = run_legacy_retry(
            case, "critique_strict_v3", config, mock_fn,
        )
        graph = run_graph_retry(
            case, "critique_strict_v3", config, mock_fn,
        )

        assert legacy.get("num_attempts") == graph.get("num_attempts"), (
            f"Attempt count mismatch: legacy={legacy.get('num_attempts')} "
            f"graph={graph.get('num_attempts')}"
        )

    def test_best_attempt_selection(self, config, all_cases):
        """Both backends select the same best attempt."""
        case = load_case("logging_pipeline_chain", all_cases)
        fixed_resp = build_fixed_response(case, all_cases)

        def mock_fn(prompt, model, **kwargs):
            from core.pipeline.llm import ModelCallResult
            lower = prompt.lower()
            if "ground truth" in lower or "mechanism" in lower or "bug_type" in lower:
                return ModelCallResult(response="CORRECT\nOK.", event_id=1)
            if "reasoning" in lower and "commitments" in lower:
                return ModelCallResult(
                    response=json.dumps({
                        "reasoning_internal_consistency": "CORRECT",
                        "reasoning_internal_consistency_justification": "t",
                        "commitments_internal_consistency": "CORRECT",
                        "commitments_internal_consistency_justification": "t",
                        "commitments_code_consistency": "CORRECT",
                        "commitments_code_consistency_justification": "t",
                        "reasoning_code_alignment": "CORRECT",
                        "reasoning_code_alignment_justification": "t",
                    }),
                    event_id=2,
                )
            return ModelCallResult(response=fixed_resp, event_id=3)

        legacy = run_legacy_retry(
            case, "critique_strict_v3", config, mock_fn,
        )
        graph = run_graph_retry(
            case, "critique_strict_v3", config, mock_fn,
        )

        assert legacy.get("best_attempt_idx") == graph.get("best_attempt_idx")


class TestDispatchRouting:
    """Verify the dispatch function routes correctly."""

    def test_default_routes_to_legacy(self, config):
        from core.pipeline.orchestration.runner import _dispatch_retry
        from core.constants.pipeline_constants import BACKEND_LEGACY_V2
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
