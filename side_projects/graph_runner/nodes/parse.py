"""ParseNode — parse raw LLM response into structured output.

Wraps the 3-tier parser (execution, recovery, format).
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from core.constants.pipeline_constants import (
    KEY_CONDITION,
    KEY_FORMAT_PARSE,
    KEY_RAW_RESPONSE,
    KEY_RECOVERY_PARSE,
    KEY_STRICT_PARSE,
    NODE_TYPE_PURE,
)
from core.pipeline.parsing.parser_v2 import (
    parse_v2_execution,
    parse_v2_format,
    parse_v2_recovery,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


class ParseNode(BaseNode):
    NAME = "ParseNode"
    INPUT_KEYS = frozenset({KEY_RAW_RESPONSE, KEY_CONDITION})
    OUTPUT_KEYS = frozenset({KEY_STRICT_PARSE, KEY_RECOVERY_PARSE, KEY_FORMAT_PARSE})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        raw = inputs[KEY_RAW_RESPONSE]
        condition = inputs[KEY_CONDITION]

        strict = parse_v2_execution(raw, condition)
        recovery = parse_v2_recovery(raw, condition)
        fmt = parse_v2_format(raw, condition)

        return NodeResult(outputs={
            KEY_STRICT_PARSE: strict,
            KEY_RECOVERY_PARSE: recovery,
            KEY_FORMAT_PARSE: fmt,
        })
