"""InlineOracleNode — LLM-based reasoning truth evaluation.

Slot node: registered as "oracle.inline".
Effect node: makes LLM API call to evaluator model.
Writes to oracle_results[node_id], not a top-level state key.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.runtime.constants import (
    ATTR_RAW_FIX_STRATEGY,
    ATTR_RAW_ROOT_CAUSE,
    CASE_FIELD_ID,
    KEY_CASE,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_RESULTS,
    NODE_ID_ORACLE_INLINE,
    NODE_TYPE_EFFECT,
)
from side_projects.graph_runner.runtime.effect_wrapper import (
    EffectLog,
    wrap_llm_call,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


class InlineOracleNode(BaseNode):
    NAME = "InlineOracleNode"
    INPUT_KEYS = frozenset({
        KEY_NORMALIZED_REASONING, KEY_CASE, KEY_CONFIG, KEY_CONDITION,
    })
    OUTPUT_KEYS = frozenset({KEY_ORACLE_RESULTS})
    NODE_TYPE = NODE_TYPE_EFFECT

    SLOT = "oracle"
    REGISTRY_ID = NODE_ID_ORACLE_INLINE

    def __init__(self, effect_log: EffectLog | None = None) -> None:
        self.effect_log = effect_log

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        from core.evaluation.oracle_inline import run_oracle_evaluation

        artifact = inputs[KEY_NORMALIZED_REASONING]
        case = inputs[KEY_CASE]
        config = inputs[KEY_CONFIG]
        condition = inputs[KEY_CONDITION]
        case_id = case.get(CASE_FIELD_ID, "")

        raw_root_cause = getattr(artifact, ATTR_RAW_ROOT_CAUSE, "") or ""
        raw_fix_strategy = getattr(artifact, ATTR_RAW_FIX_STRATEGY, "") or ""

        oracle_result = wrap_llm_call(
            self.NAME, self.effect_log,
            run_oracle_evaluation,
            raw_root_cause, raw_fix_strategy, case, config,
            logger=None,
            case_id=case_id,
            condition=condition,
        )

        # Slot output: write to namespaced collection
        existing = inputs.get(KEY_ORACLE_RESULTS, {})
        merged = dict(existing)
        merged[self.REGISTRY_ID] = oracle_result

        return NodeResult(outputs={KEY_ORACLE_RESULTS: merged})
