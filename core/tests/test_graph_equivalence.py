"""Equivalence tests: graph engine vs V2 pipeline.

Run: .venv/bin/python -m pytest core/tests/test_graph_equivalence.py -v
"""

from __future__ import annotations

import pytest

from core.tests.fixtures.pipeline_fixtures import (
    build_buggy_response,
    build_fixed_response,
    get_first_ddc_case_id,
    load_case_by_id,
    load_test_config,
)
from side_projects.graph_runner.validation.equivalence import (
    compare_outputs,
    run_graph_pipeline,
    run_v2_pipeline,
    COMPARE_FIELDS,
)

from core.constants.pipeline_constants import DDC_FAMILIES

DDC_BASELINES = sorted(DDC_FAMILIES)[:3]
DDC_VARIANTS = [f"{b}_trap_1" for b in DDC_BASELINES]
ALL_DDC = DDC_BASELINES + DDC_VARIANTS


@pytest.fixture(scope="module")
def config():
    return load_test_config()


class TestFixedPathEquivalence:

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed(self, case_id, config):
        case, all_cases = load_case_by_id(case_id)
        raw = build_fixed_response(case, all_cases)
        v2 = run_v2_pipeline(case, raw, config)
        graph = run_graph_pipeline(case, raw, config)
        result = compare_outputs(case_id, "fixed", v2, graph)
        if not result.all_match:
            lines = [f"MISMATCH {case_id} fixed:"]
            for k, (a, b) in result.mismatches.items():
                lines.append(f"  {k}: V2={a!r} GRAPH={b!r}")
            pytest.fail("\n".join(lines))


class TestBuggyPathEquivalence:

    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy(self, case_id, config):
        case, all_cases = load_case_by_id(case_id)
        raw = build_buggy_response(case)
        v2 = run_v2_pipeline(case, raw, config)
        graph = run_graph_pipeline(case, raw, config)
        result = compare_outputs(case_id, "buggy", v2, graph)
        if not result.all_match:
            lines = [f"MISMATCH {case_id} buggy:"]
            for k, (a, b) in result.mismatches.items():
                lines.append(f"  {k}: V2={a!r} GRAPH={b!r}")
            pytest.fail("\n".join(lines))


class TestGraphStructure:

    def test_fixed_no_failures(self, config):
        case_id = get_first_ddc_case_id()
        case, all_cases = load_case_by_id(case_id)
        raw = build_fixed_response(case, all_cases)
        out = run_graph_pipeline(case, raw, config)
        assert len(out["failed_nodes"]) == 0

    def test_fixed_passes(self, config):
        case_id = get_first_ddc_case_id()
        case, all_cases = load_case_by_id(case_id)
        raw = build_fixed_response(case, all_cases)
        out = run_graph_pipeline(case, raw, config)
        assert out["exec_pass"] is True
        assert out["passed"] is True

    def test_buggy_fails(self, config):
        case_id = get_first_ddc_case_id()
        case, _ = load_case_by_id(case_id)
        raw = build_buggy_response(case)
        out = run_graph_pipeline(case, raw, config)
        assert out["exec_pass"] is False

    def test_spec_oracle_ddc(self, config):
        case_id = get_first_ddc_case_id()
        case, all_cases = load_case_by_id(case_id)
        raw = build_fixed_response(case, all_cases)
        out = run_graph_pipeline(case, raw, config)
        assert out["spec_oracle_status"] == "evaluated"
        assert out["spec_oracle_depth"] == "A"
