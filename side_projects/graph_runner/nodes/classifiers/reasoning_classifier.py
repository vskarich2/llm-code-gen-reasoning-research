"""ReasoningClassifierNode — LLM-based reasoning-code consistency evaluation.

Slot node: registered as "classifier.reasoning".
Effect node: makes LLM API call to evaluator model.
Writes to classifier_results[node_id], not a top-level state key.

CRITICAL: Must run BEFORE ExecuteNode (blindness constraint).
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    CASE_FIELD_ID,
    FIELD_CLASSIFY_EVENT_ID,
    FIELD_RESULT,
    KEY_CASE,
    KEY_CLASSIFIER_RESULTS,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_NORMALIZED_REASONING,
    KEY_RECONSTRUCTED_CODE,
    NODE_ID_CLASSIFIER_REASONING,
    NODE_TYPE_EFFECT,
)
from side_projects.graph_runner.effect_wrapper import (
    EffectLog,
    get_noop_logger,
    wrap_llm_call,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class ReasoningClassifierNode(BaseNode):
    NAME = "ReasoningClassifierNode"
    INPUT_KEYS = frozenset({
        KEY_NORMALIZED_REASONING, KEY_RECONSTRUCTED_CODE,
        KEY_CASE, KEY_CONFIG, KEY_CONDITION,
    })
    OUTPUT_KEYS = frozenset({KEY_CLASSIFIER_RESULTS})
    NODE_TYPE = NODE_TYPE_EFFECT

    SLOT = "classifier"
    REGISTRY_ID = NODE_ID_CLASSIFIER_REASONING

    def __init__(self, effect_log: EffectLog | None = None) -> None:
        self.effect_log = effect_log

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        from core.evaluation.evaluator_v2 import classify_case

        artifact = inputs[KEY_NORMALIZED_REASONING]
        code = inputs[KEY_RECONSTRUCTED_CODE]
        case = inputs[KEY_CASE]
        config = inputs[KEY_CONFIG]
        condition = inputs[KEY_CONDITION]
        case_id = case.get(CASE_FIELD_ID, "")

        classifier_result, classify_event_id = wrap_llm_call(
            self.NAME, self.effect_log,
            classify_case,
            artifact, case, code, config,
            get_noop_logger(),  # logger — no-op adapter for event_id assert
            None,               # parent_event_id
            condition, case_id,
        )

        # Slot output: write to namespaced collection
        existing = inputs.get(KEY_CLASSIFIER_RESULTS, {})
        merged = dict(existing)
        merged[self.REGISTRY_ID] = {
            FIELD_RESULT: classifier_result,
            FIELD_CLASSIFY_EVENT_ID: classify_event_id,
        }

        return NodeResult(outputs={KEY_CLASSIFIER_RESULTS: merged})
