"""FULL equivalence tests: all 38 DDC cases.

Run: .venv/bin/python -m pytest core/tests/test_graph_equivalence_full.py -v
"""

import sys
sys.path.insert(0, ".")

import pytest

from side_projects.graph_runner.validation.equivalence import (
    build_buggy_response,
    build_fixed_response,
    compare_outputs,
    load_case,
    run_graph_pipeline,
    run_v2_pipeline,
)

ALL_DDC = [
    "auth_context_chain",
    "billing_aggregation_chain",
    "config_derivation_chain",
    "event_etl_chain",
    "logging_pipeline_chain",
    "ml_feature_chain",
    "search_index_chain",
    "serialization_pipeline_chain",
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


@pytest.fixture(scope="module")
def config():
    from core.config.experiment_config import load_config, is_config_loaded
    if not is_config_loaded():
        load_config("core/config/config_storage/smoke_ddc_cases.yaml")
    from core.config.experiment_config import get_config
    return get_config()


class TestFullDDCFixed:
    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_fixed(self, case_id, config):
        case, all_cases = load_case(case_id)
        raw_response = build_fixed_response(case, all_cases)
        v2 = run_v2_pipeline(case, raw_response, config)
        graph = run_graph_pipeline(case, raw_response, config)
        result = compare_outputs(case_id, "fixed", v2, graph)
        if not result.all_match:
            lines = [f"MISMATCH {case_id} fixed:"]
            for k, (a, b) in result.mismatches.items():
                lines.append(f"  {k}: V2={a!r} GRAPH={b!r}")
            pytest.fail("\n".join(lines))


class TestFullDDCBuggy:
    @pytest.mark.parametrize("case_id", ALL_DDC)
    def test_buggy(self, case_id, config):
        case, all_cases = load_case(case_id)
        raw_response = build_buggy_response(case)
        v2 = run_v2_pipeline(case, raw_response, config)
        graph = run_graph_pipeline(case, raw_response, config)
        result = compare_outputs(case_id, "buggy", v2, graph)
        if not result.all_match:
            lines = [f"MISMATCH {case_id} buggy:"]
            for k, (a, b) in result.mismatches.items():
                lines.append(f"  {k}: V2={a!r} GRAPH={b!r}")
            pytest.fail("\n".join(lines))
