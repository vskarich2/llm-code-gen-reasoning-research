"""NormalizeNode — normalize parsed generation into reasoning artifact.

Wraps reasoning_v2.normalize_generation_v2().
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from core.constants.pipeline_constants import (
    KEY_CASE,
    KEY_CONDITION,
    KEY_NORMALIZED_REASONING,
    KEY_PARSED_GENERATION,
    NODE_TYPE_PURE,
)
from core.evaluation.reasoning_v2 import normalize_generation_v2
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class NormalizeNode(BaseNode):
    NAME = "NormalizeNode"
    INPUT_KEYS = frozenset({KEY_PARSED_GENERATION, KEY_CASE, KEY_CONDITION})
    OUTPUT_KEYS = frozenset({KEY_NORMALIZED_REASONING})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        artifact = normalize_generation_v2(
            inputs[KEY_PARSED_GENERATION],
            inputs[KEY_CASE],
            inputs[KEY_CONDITION],
        )
        return NodeResult(outputs={KEY_NORMALIZED_REASONING: artifact})
