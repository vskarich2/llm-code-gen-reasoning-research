"""Equivalence testing: V2 pipeline vs graph engine.

Runs the same mocked LLM response through both systems and compares
every deterministic output field. Any mismatch is a migration bug.

Pure-stage comparison only (no LLM calls compared — those are non-deterministic).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

from side_projects.graph_runner.constants import (
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CASE,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_EXECUTION_RESULT,
    KEY_MODEL,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_RETRY_CONTEXT,
    KEY_ROUTING,
    KEY_SPEC_ORACLE_RESULT,
)

from core.utils.paths import get_case_data_dir, get_reference_fixes_dir

CASE_DATA = get_case_data_dir()


# ============================================================
# MOCK LLM (shared by both pipelines)
# ============================================================

def mock_call_model(prompt, model, **kwargs):
    """Deterministic mock LLM for equivalence testing."""
    from core.pipeline.llm import ModelCallResult
    prompt_lower = prompt.lower()

    if "ground truth" in prompt_lower or "mechanism" in prompt_lower or "bug_type" in prompt_lower:
        return ModelCallResult(
            response="CORRECT\nThe reasoning correctly identifies the root cause mechanism.",
            event_id=kwargs.get("parent_event_id") or 1,
        )

    if "reasoning" in prompt_lower and ("commitments" in prompt_lower or "classifier" in prompt_lower):
        response = json.dumps({
            "reasoning_internal_consistency": "CORRECT",
            "reasoning_internal_consistency_justification": "Root cause identifies the source correctly.",
            "commitments_internal_consistency": "CORRECT",
            "commitments_internal_consistency_justification": "Commitments follow from fix strategy.",
            "commitments_code_consistency": "CORRECT",
            "commitments_code_consistency_justification": "Code implements stated commitments.",
            "reasoning_code_alignment": "CORRECT",
            "reasoning_code_alignment_justification": "Code changes match the fix strategy.",
        })
        return ModelCallResult(response=response, event_id=kwargs.get("parent_event_id") or 2)

    return ModelCallResult(response="UNJUDGABLE\nNo data", event_id=3)


# ============================================================
# CASE LOADING
# ============================================================

def load_case(case_id: str) -> dict:
    """Load a case from cases_v2.json with file contents populated."""
    with open(CASE_DATA / "cases_v2.json") as f:
        all_cases = json.load(f)
    case = next(c for c in all_cases if c["id"] == case_id)
    case = dict(case)
    contents = {}
    for fp in case["code_files"]:
        contents[fp] = (CASE_DATA / fp).read_text()
    case["code_files_contents"] = contents
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: content
        for fp, content in contents.items()
    }
    return case, all_cases


def build_fixed_response(case: dict, all_cases: list) -> str:
    """Build LLM JSON with the reference fix applied."""
    ref_path = CASE_DATA / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]

    baseline_contents = {}
    if "_trap_" in case["id"]:
        baseline_id = case["family"]
        baseline_case = next(
            (c for c in all_cases if c["id"] == baseline_id), None,
        )
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
            f"{case['reference_fix']['function']} must "
            f"{case['ground_truth_bug']['invariant']}"
        ],
        "files": files,
    })


def build_buggy_response(case: dict) -> str:
    """Build LLM response with all files UNCHANGED."""
    files = {
        fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]
    }
    return json.dumps({
        "root_cause": "The issue appears to be in downstream consumers",
        "fix_strategy": "No changes needed to the pipeline code",
        "code_commitments": ["pipeline must pass data through correctly"],
        "files": files,
    })


# ============================================================
# V2 PIPELINE RUNNER
# ============================================================

def run_v2_pipeline(
    case: dict, raw_response: str, config: Any,
) -> dict:
    """Run V2 pipeline stages 2-9 with mocked LLM. Returns state dict."""
    from core.pipeline.orchestration.attempt_state import AttemptState
    from core.pipeline.orchestration.stages import run_stages_2_through_9

    state = AttemptState(
        case_id=case["id"],
        condition="baseline_v3",
        model="test-model",
        attempt_idx=0,
        start_time=time.monotonic(),
        raw_response=raw_response,
        prompt="<test prompt>",
        prompt_meta={"template": "test"},
        gen_event_id="test_gen_001",
    )

    logger = MagicMock()
    with patch("core.pipeline.llm.call_model", side_effect=mock_call_model):
        run_stages_2_through_9(state, case, config, logger)

    return {
        "parse_mode": state.parse_mode,
        "parsed_generation_valid": (
            state.parsed_gen.parse_valid if state.parsed_gen else False
        ),
        "parsed_generation_files": (
            sorted(state.parsed_gen.files_dict.keys())
            if state.parsed_gen and state.parsed_gen.files_dict
            else []
        ),
        "routing_source": (
            state.routing.selected_source if state.routing else None
        ),
        "recon_status": state.recon.status if state.recon else None,
        "recon_files": (
            sorted(state.recon.files.keys())
            if state.recon and state.recon.files else []
        ),
        "reconstructed_code_len": len(state.code),
        "artifact_id": state.artifact_id,
        "exec_pass": state.exec_result.get("pass"),
        "exec_category": state.exec_result.get("execution_category"),
        "passed": state.passed,
        "spec_oracle_status": (
            state.spec_oracle_result.get("status")
            if state.spec_oracle_result else None
        ),
        "spec_oracle_depth": (
            state.spec_oracle_result.get("llm_depth", {}).get("depth")
            if state.spec_oracle_result else None
        ),
    }


# ============================================================
# GRAPH ENGINE RUNNER
# ============================================================

def run_graph_pipeline(
    case: dict, raw_response: str, config: Any,
) -> dict:
    """Run graph engine on stages 2+ with mocked LLM. Returns comparable dict.

    Skips PromptBuild and Generate (we inject raw_response directly).
    Runs: Parse → Route → Normalize → Reconstruct → AST → Oracle → Classify
          → OracleAgg → ClassifierAgg → Execute → SpecOracle
    """
    from side_projects.graph_runner.nodes.parse import ParseNode
    from side_projects.graph_runner.nodes.route import RouteNode
    from side_projects.graph_runner.nodes.normalize import NormalizeNode
    from side_projects.graph_runner.nodes.reconstruct import ReconstructNode
    from side_projects.graph_runner.nodes.ast_verify import ASTNode
    from side_projects.graph_runner.nodes.spec_oracle import SpecOracleNode
    from side_projects.graph_runner.nodes.execute import ExecuteNode
    from side_projects.graph_runner.nodes.oracles.inline_oracle import InlineOracleNode
    from side_projects.graph_runner.nodes.oracles.oracle_aggregation import OracleAggregationNode
    from side_projects.graph_runner.nodes.classifiers.reasoning_classifier import ReasoningClassifierNode
    from side_projects.graph_runner.nodes.classifiers.classifier_aggregation import ClassifierAggregationNode
    from side_projects.graph_runner.engine.types import (
        NodeSpec, GraphSpec, EdgeSpec, ExecutionContext, NodeResult,
    )
    from side_projects.graph_runner.engine.scheduler import run_graph
    from side_projects.graph_runner.dag import make_adapter
    from side_projects.graph_runner.constants import (
        NODE_ID_PARSE, NODE_ID_ROUTE, NODE_ID_NORMALIZE,
        NODE_ID_RECONSTRUCT, NODE_ID_AST_VERIFY, NODE_ID_SPEC_ORACLE,
        NODE_ID_EXECUTE, NODE_ID_ORACLE_INLINE, NODE_ID_ORACLE_AGGREGATION,
        NODE_ID_CLASSIFIER_REASONING, NODE_ID_CLASSIFIER_AGGREGATION,
    )
    from side_projects.graph_runner.dag import guard_spec_oracle

    recovery_exec = True
    if config is not None and hasattr(config, "execution"):
        recovery_exec = getattr(config.execution, "recovery_execution", True)

    instances = {
        NODE_ID_PARSE: ParseNode(),
        NODE_ID_ROUTE: RouteNode(recovery_execution=recovery_exec),
        NODE_ID_NORMALIZE: NormalizeNode(),
        NODE_ID_RECONSTRUCT: ReconstructNode(),
        NODE_ID_AST_VERIFY: ASTNode(),
        NODE_ID_ORACLE_INLINE: InlineOracleNode(),
        NODE_ID_ORACLE_AGGREGATION: OracleAggregationNode(
            oracle_order=[NODE_ID_ORACLE_INLINE],
        ),
        NODE_ID_CLASSIFIER_REASONING: ReasoningClassifierNode(),
        NODE_ID_CLASSIFIER_AGGREGATION: ClassifierAggregationNode(
            classifier_order=[NODE_ID_CLASSIFIER_REASONING],
        ),
        NODE_ID_EXECUTE: ExecuteNode(),
        NODE_ID_SPEC_ORACLE: SpecOracleNode(),
    }

    nodes = []
    for nid, inst in instances.items():
        guard = guard_spec_oracle if nid == NODE_ID_SPEC_ORACLE else None
        nodes.append(NodeSpec(
            name=nid,
            input_keys=inst.INPUT_KEYS,
            output_keys=inst.OUTPUT_KEYS,
            executor=make_adapter(inst),
            guard=guard,
            side_effecting=(inst.NODE_TYPE == "effect"),
        ))

    edges = (
        EdgeSpec(src=NODE_ID_PARSE, dst=NODE_ID_ROUTE),
        EdgeSpec(src=NODE_ID_ROUTE, dst=NODE_ID_NORMALIZE),
        EdgeSpec(src=NODE_ID_NORMALIZE, dst=NODE_ID_RECONSTRUCT),
        EdgeSpec(src=NODE_ID_NORMALIZE, dst=NODE_ID_ORACLE_INLINE),
        EdgeSpec(src=NODE_ID_RECONSTRUCT, dst=NODE_ID_CLASSIFIER_REASONING),
        EdgeSpec(src=NODE_ID_RECONSTRUCT, dst=NODE_ID_AST_VERIFY),
        EdgeSpec(src=NODE_ID_ORACLE_INLINE, dst=NODE_ID_ORACLE_AGGREGATION),
        EdgeSpec(src=NODE_ID_CLASSIFIER_REASONING, dst=NODE_ID_CLASSIFIER_AGGREGATION),
        EdgeSpec(src=NODE_ID_CLASSIFIER_AGGREGATION, dst=NODE_ID_EXECUTE),
        EdgeSpec(src=NODE_ID_AST_VERIFY, dst=NODE_ID_EXECUTE),
        EdgeSpec(src=NODE_ID_EXECUTE, dst=NODE_ID_SPEC_ORACLE),
    )

    graph = GraphSpec(nodes=tuple(nodes), edges=edges)

    seed = {
        "case": case,
        "condition": "baseline_v3",
        "model": "test-model",
        "config": config,
        "raw_response": raw_response,
    }

    context = ExecutionContext(
        run_id="equiv_test",
        case_id=case["id"],
        model="test-model",
        condition="baseline_v3",
        config=config,
        logger=None,
    )

    with patch("core.pipeline.llm.call_model", side_effect=mock_call_model):
        summary = run_graph(graph, seed=seed, context=context)

    vals = summary.final_state.values

    parsed_gen = vals.get("parsed_generation")
    routing = vals.get("routing")
    recon = vals.get("recon")
    spec_oracle = vals.get("spec_oracle_result")

    return {
        "parse_mode": vals.get("parse_mode"),
        "parsed_generation_valid": (
            parsed_gen.parse_valid if parsed_gen else False
        ),
        "parsed_generation_files": (
            sorted(parsed_gen.files_dict.keys())
            if parsed_gen and parsed_gen.files_dict else []
        ),
        "routing_source": (
            getattr(routing, "selected_source", None)
            if routing else None
        ),
        "recon_status": recon.status if recon else None,
        "recon_files": (
            sorted(recon.files.keys())
            if recon and recon.files else []
        ),
        "reconstructed_code_len": len(vals.get("reconstructed_code", "")),
        "artifact_id": vals.get("artifact_id"),
        "exec_pass": vals.get("execution_result", {}).get("pass"),
        "exec_category": vals.get("execution_result", {}).get(
            "execution_category",
        ),
        "passed": vals.get("passed"),
        "spec_oracle_status": (
            spec_oracle.get("status") if spec_oracle else None
        ),
        "spec_oracle_depth": (
            spec_oracle.get("llm_depth", {}).get("depth")
            if spec_oracle else None
        ),
        "completed_nodes": summary.completed_nodes,
        "failed_nodes": summary.failed_nodes,
    }


# ============================================================
# COMPARISON
# ============================================================

@dataclass
class ComparisonResult:
    case_id: str
    response_type: str
    matches: dict[str, bool] = field(default_factory=dict)
    mismatches: dict[str, tuple] = field(default_factory=dict)
    v2_error: str | None = None
    graph_error: str | None = None

    @property
    def all_match(self) -> bool:
        return (
            not self.v2_error
            and not self.graph_error
            and all(self.matches.values())
        )


COMPARE_FIELDS = [
    "parsed_generation_valid",
    "parsed_generation_files",
    "recon_status",
    "recon_files",
    "reconstructed_code_len",
    "artifact_id",
    "exec_pass",
    "passed",
    "spec_oracle_status",
    "spec_oracle_depth",
]


def compare_outputs(
    case_id: str, response_type: str,
    v2: dict, graph: dict,
) -> ComparisonResult:
    """Compare V2 and graph outputs field by field."""
    result = ComparisonResult(
        case_id=case_id, response_type=response_type,
    )

    for field_name in COMPARE_FIELDS:
        v2_val = v2.get(field_name)
        graph_val = graph.get(field_name)
        if v2_val == graph_val:
            result.matches[field_name] = True
        else:
            result.matches[field_name] = False
            result.mismatches[field_name] = (v2_val, graph_val)

    return result
