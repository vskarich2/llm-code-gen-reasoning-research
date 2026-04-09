"""Integration test: full pipeline stages on ALL 38 DDC cases × both paths.

Constructs realistic LLM responses from reference fixes (fixed path) and
UNCHANGED files (buggy path), runs them through ACTUAL pipeline stages
(parse → oracle → normalize → reconstruct → classify → ast → execute →
spec_oracle → derive_metrics), and verifies the event dict.

Mocks only the LLM call layer (call_model) with realistic oracle/classifier
responses. Everything else runs real.

Run: .venv/bin/python -m pytest core/tests/test_ddc_pipeline_integration.py -v
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DATA = PROJECT_ROOT / "case_data"

DDC_BASELINES = [
    "auth_context_chain",
    "billing_aggregation_chain",
    "config_derivation_chain",
    "event_etl_chain",
    "logging_pipeline_chain",
    "ml_feature_chain",
    "search_index_chain",
    "serialization_pipeline_chain",
]

DDC_VARIANTS = [
    "auth_context_chain_trap_1",
    "auth_context_chain_trap_3",
    "auth_context_chain_trap_4",
    "auth_context_chain_trap_5",
    "billing_aggregation_chain_trap_1",
    "billing_aggregation_chain_trap_3",
    "billing_aggregation_chain_trap_4",
    "billing_aggregation_chain_trap_5",
    "config_derivation_chain_trap_1",
    "config_derivation_chain_trap_3",
    "config_derivation_chain_trap_4",
    "config_derivation_chain_trap_5",
    "event_etl_chain_trap_1",
    "event_etl_chain_trap_3",
    "event_etl_chain_trap_4",
    "event_etl_chain_trap_5",
    "logging_pipeline_chain_trap_1",
    "logging_pipeline_chain_trap_3",
    "logging_pipeline_chain_trap_4",
    "logging_pipeline_chain_trap_5",
    "ml_feature_chain_trap_1",
    "ml_feature_chain_trap_3",
    "ml_feature_chain_trap_4",
    "ml_feature_chain_trap_5",
    "search_index_chain_trap_3",
    "search_index_chain_trap_5",
    "serialization_pipeline_chain_trap_1",
    "serialization_pipeline_chain_trap_3",
    "serialization_pipeline_chain_trap_4",
    "serialization_pipeline_chain_trap_5",
]

ALL_DDC = DDC_BASELINES + DDC_VARIANTS


# ── Mock LLM ─────────────────────────────────────────────────


def _mock_call_model(prompt, model, **kwargs):
    """Mock LLM that returns realistic oracle/classifier responses."""
    from core.pipeline.llm import ModelCallResult
    prompt_lower = prompt.lower()

    if "ground truth" in prompt_lower or "mechanism" in prompt_lower or "bug_type" in prompt_lower:
        return ModelCallResult(
            response="CORRECT\nThe reasoning correctly identifies the root cause mechanism.",
            event_id=kwargs.get("parent_event_id"),
        )

    if "reasoning" in prompt_lower and ("commitments" in prompt_lower or "classifier" in prompt_lower):
        response = json.dumps({
            "reasoning_internal_consistency": "CONSISTENT",
            "reasoning_internal_consistency_justification": "test mock",
            "commitments_internal_consistency": "CONSISTENT",
            "commitments_internal_consistency_justification": "test mock",
            "commitments_code_consistency": "CONSISTENT",
            "commitments_code_consistency_justification": "test mock",
            "reasoning_code_alignment": "ALIGNED",
            "reasoning_code_alignment_justification": "test mock",
        })
        return ModelCallResult(response=response, event_id=kwargs.get("parent_event_id"))

    return ModelCallResult(response="UNJUDGABLE\nNo data", event_id=None)


# ── Fixtures ─────────────────────────────────────────────────


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


# ── Helpers ──────────────────────────────────────────────────


def _build_fixed_response(case: dict, all_cases: list) -> str:
    """Build LLM JSON response with root fix + reverted trap compensation.

    For baselines: replaces the buggy file with the reference fix.
    For trap variants: also reverts any files that differ from baseline
    (undoing trap compensation that would conflict with the root fix).
    """
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]

    baseline_contents = {}
    if "_trap_" in case["id"]:
        baseline_id = case["family"]
        baseline_case = next((c for c in all_cases if c["id"] == baseline_id), None)
        if baseline_case:
            for fp in baseline_case["code_files"]:
                filename = fp.rsplit("/", 1)[-1]
                baseline_contents[filename] = (CASE_DATA / fp).read_text()

    files = {}
    for fp in case["code_files"]:
        filename = fp.rsplit("/", 1)[-1]
        if filename == bug_file:
            files[filename] = ref_code
        elif baseline_contents:
            variant_content = (CASE_DATA / fp).read_text()
            baseline_content = baseline_contents.get(filename, "")
            if variant_content != baseline_content:
                files[filename] = baseline_content
            else:
                files[filename] = "UNCHANGED"
        else:
            files[filename] = "UNCHANGED"

    return json.dumps({
        "root_cause": f"Bug in {bug_file}: {case['ground_truth_bug']['invariant']}",
        "fix_strategy": case["ground_truth_bug"]["fix_pattern"],
        "code_commitments": [
            f"{case['reference_fix']['function']} must {case['ground_truth_bug']['invariant']}"
        ],
        "files": files,
    })


def _build_buggy_response(case: dict) -> str:
    """Build LLM response with all files UNCHANGED (no fix applied)."""
    files = {fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]}
    return json.dumps({
        "root_cause": "The issue appears to be in downstream consumers",
        "fix_strategy": "No changes needed to the pipeline code",
        "code_commitments": ["pipeline must pass data through correctly"],
        "files": files,
    })


def _load_case_with_contents(case: dict) -> dict:
    """Populate code_files_contents and logical_file_keys on a case dict."""
    case = dict(case)
    contents = {}
    for fp in case["code_files"]:
        full = CASE_DATA / fp
        contents[fp] = full.read_text()
    case["code_files_contents"] = contents
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: content
        for fp, content in contents.items()
    }
    return case


def _run_pipeline(case_id, raw_response, config, all_cases):
    """Run stages 2-9 with mocked LLM. Returns (AttemptState, case_dict)."""
    from core.pipeline.orchestration.attempt_state import AttemptState
    from core.pipeline.orchestration.stages import run_stages_2_through_9

    case = next(c for c in all_cases if c["id"] == case_id)
    case = _load_case_with_contents(case)
    logger = MagicMock()

    state = AttemptState(
        case_id=case_id,
        condition="baseline_v3",
        model="test-model",
        attempt_idx=0,
        start_time=time.monotonic(),
        raw_response=raw_response,
        prompt="<test prompt>",
        prompt_meta={"template": "test", "components": []},
        gen_event_id="test_gen_001",
    )

    with patch("core.pipeline.llm.call_model", side_effect=_mock_call_model):
        run_stages_2_through_9(state, case, config, logger)

    return state, case


# ── Fixed path: all 38 cases ────────────────────────────────


class TestFixedPath:
    """Reference fix response → test passes, depth A, event serializable."""

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed_passes_execution(self, case_id, config, all_cases):
        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_fixed_response(case, all_cases)
        state, _ = _run_pipeline(case_id, raw_response, config, all_cases)

        assert state.parsed_gen.parse_valid, f"parse failed: {state.parsed_gen.parse_error}"
        assert state.recon.status == "SUCCESS", f"recon failed: {state.recon.status}"
        assert state.exec_result.get("pass") is True, (
            f"reference fix failed: {state.exec_result.get('failure_reasons', [])}"
        )

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed_spec_oracle_depth_a(self, case_id, config, all_cases):
        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_fixed_response(case, all_cases)
        state, _ = _run_pipeline(case_id, raw_response, config, all_cases)

        assert state.spec_oracle_result is not None
        assert state.spec_oracle_result["status"] == "evaluated"
        assert state.spec_oracle_result["llm_depth"]["depth"] == "A"

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed_event_serializable(self, case_id, config, all_cases):
        from core.pipeline.orchestration.execution_v2 import _assemble_result_from_state

        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_fixed_response(case, all_cases)
        state, case_full = _run_pipeline(case_id, raw_response, config, all_cases)

        ev = _assemble_result_from_state(state, case_full, config)

        for section in ["reconstruction", "classification", "evaluation",
                        "ast_eval", "oracle", "spec_oracle"]:
            assert section in ev, f"missing {section}"

        serialized = json.dumps(ev)
        assert len(serialized) > 100


# ── Buggy path: all 38 cases ────────────────────────────────


class TestBuggyPath:
    """UNCHANGED response → test fails, pipeline doesn't crash, event serializable."""

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy_fails_execution(self, case_id, config, all_cases):
        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_buggy_response(case)
        state, _ = _run_pipeline(case_id, raw_response, config, all_cases)

        assert state.parsed_gen is not None
        assert state.recon is not None
        assert state.exec_result is not None
        assert state.exec_result.get("pass") is False, (
            f"buggy code should fail but passed for {case_id}"
        )

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy_spec_oracle_runs(self, case_id, config, all_cases):
        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_buggy_response(case)
        state, _ = _run_pipeline(case_id, raw_response, config, all_cases)

        assert state.spec_oracle_result is not None
        assert state.spec_oracle_result["status"] == "evaluated"

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy_event_serializable(self, case_id, config, all_cases):
        from core.pipeline.orchestration.execution_v2 import _assemble_result_from_state

        case = next(c for c in all_cases if c["id"] == case_id)
        raw_response = _build_buggy_response(case)
        state, case_full = _run_pipeline(case_id, raw_response, config, all_cases)

        ev = _assemble_result_from_state(state, case_full, config)
        serialized = json.dumps(ev)
        assert len(serialized) > 100


# ── Non-DDC cases ────────────────────────────────────────────


class TestNonDDC:
    """Non-DDC cases must not have spec_oracle in the event."""

    def test_non_ddc_no_spec_oracle(self, config, all_cases):
        case = next(c for c in all_cases if c["id"] == "alias_config_a")
        case = _load_case_with_contents(case)

        files = {fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]}
        raw_response = json.dumps({
            "root_cause": "shared reference",
            "fix_strategy": "copy defaults",
            "code_commitments": ["create_config must return a copy"],
            "files": files,
        })

        logger = MagicMock()
        from core.pipeline.orchestration.attempt_state import AttemptState
        from core.pipeline.orchestration.stages import run_stages_2_through_9

        state = AttemptState(
            case_id="alias_config_a",
            condition="baseline_v3",
            model="test-model",
            start_time=time.monotonic(),
            raw_response=raw_response,
            prompt="<test>",
            prompt_meta={"template": "test", "components": []},
            gen_event_id="test_gen",
        )

        with patch("core.pipeline.llm.call_model", side_effect=_mock_call_model):
            run_stages_2_through_9(state, case, config, logger)

        assert state.spec_oracle_result is None

        from core.pipeline.orchestration.execution_v2 import _assemble_result_from_state
        ev = _assemble_result_from_state(state, case, config)
        assert "spec_oracle" not in ev


# ============================================================
# RETRY PATH
# ============================================================


class TestRetryPath:
    """Verify retry path includes spec_oracle in trajectory and final event."""

    def test_retry_trajectory_has_spec_oracle(self, config, all_cases):
        """Run retry with 2 attempts on a DDC case. Each attempt's trajectory
        entry and the final event must include spec_oracle."""
        from core.pipeline.orchestration.retry_v2 import run_retry_v2
        from unittest.mock import MagicMock

        case_id = "serialization_pipeline_chain"
        case = next(c for c in all_cases if c["id"] == case_id)
        case = _load_case_with_contents(case)

        # Mock LLM: first attempt returns buggy (UNCHANGED), second returns fix
        call_count = {"n": 0}
        def mock_call(prompt, model, **kwargs):
            from core.pipeline.llm import ModelCallResult
            call_count["n"] += 1
            prompt_lower = prompt.lower()

            # Oracle/classifier calls
            if "ground truth" in prompt_lower or "mechanism" in prompt_lower:
                return ModelCallResult(response="CORRECT\nIdentified root cause.", event_id=kwargs.get("parent_event_id"))
            if "reasoning" in prompt_lower and "commitments" in prompt_lower:
                return ModelCallResult(response=json.dumps({
                    "reasoning_internal_consistency": "CONSISTENT",
                    "reasoning_internal_consistency_justification": "mock",
                    "commitments_internal_consistency": "CONSISTENT",
                    "commitments_internal_consistency_justification": "mock",
                    "commitments_code_consistency": "CONSISTENT",
                    "commitments_code_consistency_justification": "mock",
                    "reasoning_code_alignment": "ALIGNED",
                    "reasoning_code_alignment_justification": "mock",
                }), event_id=kwargs.get("parent_event_id"))
            # Critique call
            if "previous" in prompt_lower or "critique" in prompt_lower or "mismatch" in prompt_lower:
                return ModelCallResult(response="The fix modifies the wrong file.", event_id=kwargs.get("parent_event_id"))

            # Generation calls — first buggy, second fixed
            gen_calls = call_count["n"]
            if gen_calls <= 1:
                files = {fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]}
                resp = json.dumps({
                    "root_cause": "serializer converts to epoch",
                    "fix_strategy": "no change needed",
                    "code_commitments": ["pipeline must work"],
                    "files": files,
                })
            else:
                ref_code = (CASE_DATA / "reference_fixes" / f"{case_id}.py").read_text()
                bug_file = case["reference_fix"]["file"]
                files = {fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]}
                files[bug_file] = ref_code
                resp = json.dumps({
                    "root_cause": "serializer converts created_at to epoch via EPOCH_TABLE",
                    "fix_strategy": "preserve created_at as ISO string",
                    "code_commitments": ["serialize must preserve ISO strings"],
                    "files": files,
                })
            return ModelCallResult(response=resp, event_id=1)

        logger = MagicMock()
        logger.log_structured_event = MagicMock(return_value=1)
        logger.log_structured_error = MagicMock()
        logger.end_case = MagicMock()

        with patch("core.pipeline.llm.call_model", side_effect=mock_call):
            result = run_retry_v2(
                case=case,
                condition="critique_strict_v3",
                model=config.models.generation[0].name,
                logger=logger,
            )

        cid, condition, ev = result

        # Final event must have spec_oracle
        assert "spec_oracle" in ev, (
            f"spec_oracle missing from retry final event. Keys: {sorted(ev.keys())}"
        )
        assert ev["spec_oracle"]["status"] == "evaluated"

        # Trajectory entries must have spec_oracle
        trajectory = ev.get("trajectory", [])
        assert len(trajectory) >= 1
        for i, entry in enumerate(trajectory):
            assert "spec_oracle" in entry, (
                f"trajectory[{i}] missing spec_oracle. Keys: {sorted(entry.keys())}"
            )
