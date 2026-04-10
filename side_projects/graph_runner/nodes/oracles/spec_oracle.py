"""SpecOracleNode — DDC depth classification via spec-driven invariants.

Wraps spec_oracle.run_spec_oracle(). Conditional: only runs for DDC cases.
Pure node: no side effects (spec oracle is deterministic).
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.runtime.constants import (
    CASE_FIELD_ID,
    DDC_FAMILIES,
    DDC_TRAP_SEPARATOR,
    KEY_CASE,
    KEY_EXECUTION_RESULT,
    KEY_SPEC_ORACLE_RESULT,
    NODE_TYPE_PURE,
)
from core.evaluation.spec_oracle import run_spec_oracle
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


def is_ddc_case(case: dict[str, Any]) -> bool:
    """Check if case belongs to a DDC family."""
    case_id = case.get(CASE_FIELD_ID, "")
    family = (
        case_id.split(DDC_TRAP_SEPARATOR)[0]
        if DDC_TRAP_SEPARATOR in case_id
        else case_id
    )
    return family in DDC_FAMILIES


class SpecOracleNode(BaseNode):
    NAME = "SpecOracleNode"
    INPUT_KEYS = frozenset({KEY_EXECUTION_RESULT, KEY_CASE})
    OUTPUT_KEYS = frozenset({KEY_SPEC_ORACLE_RESULT})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        case = inputs[KEY_CASE]
        exec_result = inputs[KEY_EXECUTION_RESULT]

        if is_ddc_case(case):
            result = run_spec_oracle(case, exec_result)
        else:
            result = None

        return NodeResult(outputs={KEY_SPEC_ORACLE_RESULT: result})
