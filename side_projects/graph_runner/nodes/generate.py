"""GenerateNode — call LLM to generate code fix.

Effect node: makes an external LLM API call.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    KEY_CONFIG,
    KEY_GEN_EVENT_ID,
    KEY_MODEL,
    KEY_PROMPT,
    KEY_RAW_RESPONSE,
    NODE_TYPE_EFFECT,
)
from side_projects.graph_runner.effect_wrapper import (
    EffectLog,
    get_noop_logger,
    wrap_llm_call,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class GenerateNode(BaseNode):
    NAME = "GenerateNode"
    INPUT_KEYS = frozenset({KEY_PROMPT, KEY_MODEL, KEY_CONFIG})
    OUTPUT_KEYS = frozenset({KEY_RAW_RESPONSE, KEY_GEN_EVENT_ID})
    NODE_TYPE = NODE_TYPE_EFFECT

    def __init__(self, effect_log: EffectLog | None = None) -> None:
        self.effect_log = effect_log

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        from core.pipeline.llm import call_model

        prompt = inputs[KEY_PROMPT]
        model = inputs[KEY_MODEL]

        result = wrap_llm_call(
            self.NAME, self.effect_log,
            call_model,
            prompt, model=model, raw=True,
            logger=get_noop_logger(),
        )

        return NodeResult(outputs={
            KEY_RAW_RESPONSE: result.response,
            KEY_GEN_EVENT_ID: result.event_id,
        })
