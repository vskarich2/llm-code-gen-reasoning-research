"""Equivalence tests: graph engine vs V2 pipeline.

Runs the same deterministic mock LLM response through both the V2 pipeline
stages and the graph engine, then compares every deterministic output field.

Any mismatch is a migration bug, not a test failure.

Run: .venv/bin/python -m pytest core/tests/test_graph_equivalence.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

import pytest

from side_projects.graph_runner.validation.equivalence import (
    build_buggy_response,
    build_fixed_response,
    compare_outputs,
    load_case,
    mock_call_model,
    run_graph_pipeline,
    run_v2_pipeline,
    COMPARE_FIELDS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── Test cases ──

DDC_BASELINES = [
    "logging_pipeline_chain",
    "ml_feature_chain",
    "auth_context_chain",
]

DDC_VARIANTS = [
    "logging_pipeline_chain_trap_1",
    "ml_feature_chain_trap_1",
    "auth_context_chain_trap_1",
]

ALL_DDC = DDC_BASELINES + DDC_VARIANTS


# ── Fixtures ──

@pytest.fixture(scope="module")
def config():
    from core.config.experiment_config import load_config, is_config_loaded
    if not is_config_loaded():
        load_config("core/config/config_storage/smoke_ddc_cases.yaml")
    from core.config.experiment_config import get_config
    return get_config()


# ── Fixed path equivalence ──

class TestFixedPathEquivalence:
    """Reference fix response: V2 and graph must produce identical outputs."""

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed_equivalence(self, case_id, config):
        case, all_cases = load_case(case_id)
        raw_response = build_fixed_response(case, all_cases)

        v2_out = run_v2_pipeline(case, raw_response, config)
        graph_out = run_graph_pipeline(case, raw_response, config)

        result = compare_outputs(case_id, "fixed", v2_out, graph_out)

        if not result.all_match:
            lines = [f"MISMATCH for {case_id} (fixed):"]
            for field_name, (v2_val, graph_val) in result.mismatches.items():
                lines.append(
                    f"  {field_name}: V2={v2_val!r} GRAPH={graph_val!r}"
                )
            pytest.fail("\n".join(lines))


# ── Buggy path equivalence ──

class TestBuggyPathEquivalence:
    """UNCHANGED response: V2 and graph must produce identical outputs."""

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy_equivalence(self, case_id, config):
        case, all_cases = load_case(case_id)
        raw_response = build_buggy_response(case)

        v2_out = run_v2_pipeline(case, raw_response, config)
        graph_out = run_graph_pipeline(case, raw_response, config)

        result = compare_outputs(case_id, "buggy", v2_out, graph_out)

        if not result.all_match:
            lines = [f"MISMATCH for {case_id} (buggy):"]
            for field_name, (v2_val, graph_val) in result.mismatches.items():
                lines.append(
                    f"  {field_name}: V2={v2_val!r} GRAPH={graph_val!r}"
                )
            pytest.fail("\n".join(lines))


# ── Structural tests ──

class TestGraphStructure:
    """Verify graph engine mechanics independent of comparison."""

    def test_graph_completes_all_nodes_fixed(self, config):
        case, all_cases = load_case("logging_pipeline_chain")
        raw_response = build_fixed_response(case, all_cases)
        graph_out = run_graph_pipeline(case, raw_response, config)

        assert len(graph_out["failed_nodes"]) == 0, (
            f"Graph had failures: {graph_out['failed_nodes']}"
        )

    def test_graph_completes_all_nodes_buggy(self, config):
        case, all_cases = load_case("logging_pipeline_chain")
        raw_response = build_buggy_response(case)
        graph_out = run_graph_pipeline(case, raw_response, config)

        assert len(graph_out["failed_nodes"]) == 0, (
            f"Graph had failures: {graph_out['failed_nodes']}"
        )

    def test_fixed_case_passes(self, config):
        case, all_cases = load_case("logging_pipeline_chain")
        raw_response = build_fixed_response(case, all_cases)
        graph_out = run_graph_pipeline(case, raw_response, config)
        assert graph_out["exec_pass"] is True
        assert graph_out["passed"] is True

    def test_buggy_case_fails(self, config):
        case, all_cases = load_case("logging_pipeline_chain")
        raw_response = build_buggy_response(case)
        graph_out = run_graph_pipeline(case, raw_response, config)
        assert graph_out["exec_pass"] is False
        assert graph_out["passed"] is False

    def test_spec_oracle_runs_for_ddc(self, config):
        case, all_cases = load_case("logging_pipeline_chain")
        raw_response = build_fixed_response(case, all_cases)
        graph_out = run_graph_pipeline(case, raw_response, config)
        assert graph_out["spec_oracle_status"] == "evaluated"
        assert graph_out["spec_oracle_depth"] == "A"
