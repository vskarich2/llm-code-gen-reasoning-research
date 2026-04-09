"""DAG construction — builds GraphSpec from node registry + config.

Wires all 16 nodes with explicit edges per dag_spec_v1.md.
Uses the execution engine types (NodeSpec, GraphSpec, EdgeSpec).
"""

from __future__ import annotations

from typing import Any, Mapping

from side_projects.graph_runner.runtime.constants import (
    CASE_FIELD_LOGICAL_FILE_KEYS,
    DDC_FAMILIES,
    DDC_TRAP_SEPARATOR,
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CASE,
    KEY_CLASSIFIER_RESULTS,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CLASSIFY_EVENT_ID,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_DISAGREEMENT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_FINAL_RESULT,
    KEY_FORMAT_PARSE,
    KEY_GEN_EVENT_ID,
    KEY_LOG_STATUS,
    KEY_MODEL,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_RESULTS,
    KEY_ORACLE_SUMMARY,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_PROMPT,
    KEY_PROMPT_META,
    KEY_RAW_RESPONSE,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_RECOVERY_PARSE,
    KEY_RETRY_CONTEXT,
    KEY_RETRY_ELIGIBLE,
    KEY_ROUTING,
    KEY_SIGNALS,
    KEY_SPEC_ORACLE_RESULT,
    KEY_STRICT_PARSE,
    NODE_ID_AST_VERIFY,
    NODE_ID_ASSEMBLE,
    NODE_ID_CLASSIFIER_AGGREGATION,
    NODE_ID_CLASSIFIER_REASONING,
    NODE_ID_EXECUTE,
    NODE_ID_GENERATE,
    NODE_ID_LOG,
    NODE_ID_METRICS,
    NODE_ID_NORMALIZE,
    NODE_ID_ORACLE_AGGREGATION,
    NODE_ID_ORACLE_INLINE,
    NODE_ID_PARSE,
    NODE_ID_PROMPT_BUILD,
    NODE_ID_RECONSTRUCT,
    NODE_ID_ROUTE,
    NODE_ID_SPEC_ORACLE,
    CASE_FIELD_ID,
)
from side_projects.graph_runner.graph.types import (
    EdgeSpec,
    ExecutionContext,
    GraphSpec,
    NodeResult,
    NodeSpec,
)


# ============================================================
# NODE EXECUTOR ADAPTERS
# ============================================================
# Each adapter bridges a BaseNode.execute(inputs) -> NodeResult
# to the engine's executor(context, inputs) -> NodeResult signature.

def make_adapter(node_instance: Any) -> Any:
    """Wrap a BaseNode instance as an engine executor function."""
    def executor(
        context: ExecutionContext, inputs: Mapping[str, Any],
    ) -> NodeResult:
        from side_projects.graph_runner.graph.types import (
            NodeResult as EngineResult,
        )
        old_result = node_instance.execute(dict(inputs))
        return EngineResult(
            outputs=dict(old_result.outputs),
            warnings=(),
        )
    return executor


# ============================================================
# GUARDS
# ============================================================

def guard_spec_oracle(state: Mapping[str, Any]) -> bool:
    """SpecOracleNode runs only for DDC cases."""
    case = state.get(KEY_CASE, {})
    case_id = case.get(CASE_FIELD_ID, "")
    family = (
        case_id.split(DDC_TRAP_SEPARATOR)[0]
        if DDC_TRAP_SEPARATOR in case_id
        else case_id
    )
    return family in DDC_FAMILIES


# ============================================================
# DAG BUILDER
# ============================================================

def build_pipeline_graph(config: Any = None) -> GraphSpec:
    """Build the full 16-node pipeline GraphSpec.

    Instantiates all nodes, wires edges per dag_spec_v1.
    Config is used for node construction parameters (e.g., recovery_execution).
    """
    # Instantiate nodes
    from side_projects.graph_runner.nodes.prompt_build import PromptBuildNode
    from side_projects.graph_runner.nodes.generate import GenerateNode
    from side_projects.graph_runner.nodes.parse import ParseNode
    from side_projects.graph_runner.nodes.route import RouteNode
    from side_projects.graph_runner.nodes.normalize import NormalizeNode
    from side_projects.graph_runner.nodes.reconstruct import ReconstructNode
    from side_projects.graph_runner.nodes.ast_verify import ASTNode
    from side_projects.graph_runner.nodes.oracles.spec_oracle import SpecOracleNode
    from side_projects.graph_runner.nodes.metrics import MetricsNode
    from side_projects.graph_runner.nodes.assemble import AssembleNode
    from side_projects.graph_runner.nodes.log import LogNode
    from side_projects.graph_runner.nodes.generate import GenerateNode
    from side_projects.graph_runner.nodes.execute import ExecuteNode
    from side_projects.graph_runner.nodes.oracles.inline_oracle import InlineOracleNode
    from side_projects.graph_runner.nodes.oracles.oracle_aggregation import OracleAggregationNode
    from side_projects.graph_runner.nodes.classifiers.reasoning_classifier import ReasoningClassifierNode
    from side_projects.graph_runner.nodes.classifiers.classifier_aggregation import ClassifierAggregationNode

    recovery_exec = True
    if config is not None and hasattr(config, "execution"):
        recovery_exec = getattr(config.execution, "recovery_execution", True)

    instances = {
        NODE_ID_PROMPT_BUILD: PromptBuildNode(),
        NODE_ID_GENERATE: GenerateNode(),
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
        NODE_ID_METRICS: MetricsNode(),
        NODE_ID_ASSEMBLE: AssembleNode(),
        NODE_ID_LOG: LogNode(),
    }

    # Build NodeSpec for each
    nodes: list[NodeSpec] = []
    for node_id, inst in instances.items():
        guard = None
        if node_id == NODE_ID_SPEC_ORACLE:
            guard = guard_spec_oracle

        nodes.append(NodeSpec(
            name=node_id,
            input_keys=inst.INPUT_KEYS,
            output_keys=inst.OUTPUT_KEYS,
            executor=make_adapter(inst),
            guard=guard,
            side_effecting=(inst.NODE_TYPE == "effect"),
        ))

    # Edges from dag_spec_v1.md
    edges = (
        EdgeSpec(src=NODE_ID_PROMPT_BUILD, dst=NODE_ID_GENERATE),
        EdgeSpec(src=NODE_ID_GENERATE, dst=NODE_ID_PARSE),
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
        EdgeSpec(src=NODE_ID_ORACLE_AGGREGATION, dst=NODE_ID_METRICS),
        EdgeSpec(src=NODE_ID_CLASSIFIER_AGGREGATION, dst=NODE_ID_METRICS),
        EdgeSpec(src=NODE_ID_EXECUTE, dst=NODE_ID_METRICS),
        EdgeSpec(src=NODE_ID_SPEC_ORACLE, dst=NODE_ID_METRICS),
        EdgeSpec(src=NODE_ID_METRICS, dst=NODE_ID_ASSEMBLE),
        EdgeSpec(src=NODE_ID_ASSEMBLE, dst=NODE_ID_LOG),
    )

    return GraphSpec(nodes=tuple(nodes), edges=edges)


# ============================================================
# SEED KEYS
# ============================================================

SEED_KEYS = frozenset({
    KEY_CASE, KEY_CONDITION, KEY_MODEL, KEY_CONFIG, KEY_RETRY_CONTEXT,
})
