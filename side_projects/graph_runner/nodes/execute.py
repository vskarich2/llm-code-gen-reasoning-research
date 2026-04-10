"""ExecuteNode — run generated code against test suite.

Effect node: executes subprocess.
CRITICAL: Must run AFTER all classifier nodes (blindness constraint).
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.runtime.constants import (
    CASE_FIELD_TEMPLATE,
    EXEC_KEY_EXECUTION,
    EXEC_KEY_EXECUTION_CATEGORY,
    EXEC_KEY_FAILURE_TYPE,
    EXEC_KEY_PASS,
    EXEC_KEY_RAN,
    EXEC_KEY_REASONS,
    EXEC_KEY_SCORE,
    EXEC_KEY_STATUS,
    EXEC_STATUS_NOT_EXECUTED,
    EXEC_STRUCTURAL_FAILURE,
    KEY_CASE,
    KEY_CONFIG,
    KEY_EXECUTION_RESULT,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_RECON,
    NODE_TYPE_EFFECT,
    STATUS_GENERATION_CONTRACT_VIOLATION,
    TEMPLATE_SWEBENCH_REAL_WORLD,
)
from side_projects.graph_runner.runtime.effect_wrapper import (
    EffectLog,
    get_noop_logger,
    wrap_subprocess_call,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


class ExecuteNode(BaseNode):
    NAME = "ExecuteNode"
    INPUT_KEYS = frozenset({
        KEY_RECON, KEY_PARSED_GENERATION, KEY_CASE, KEY_CONFIG,
    })
    OUTPUT_KEYS = frozenset({KEY_EXECUTION_RESULT, KEY_PASSED})
    NODE_TYPE = NODE_TYPE_EFFECT

    def __init__(self, effect_log: EffectLog | None = None) -> None:
        self.effect_log = effect_log

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        recon = inputs[KEY_RECON]
        parsed_gen = inputs[KEY_PARSED_GENERATION]
        case = inputs[KEY_CASE]
        config = inputs[KEY_CONFIG]

        if recon.status == STATUS_GENERATION_CONTRACT_VIOLATION:
            exec_result = {
                EXEC_KEY_PASS: False,
                EXEC_KEY_SCORE: 0.0,
                EXEC_KEY_REASONS: ["Generation contract violation"],
                EXEC_KEY_EXECUTION_CATEGORY: EXEC_STRUCTURAL_FAILURE,
                EXEC_KEY_FAILURE_TYPE: STATUS_GENERATION_CONTRACT_VIOLATION,
                EXEC_KEY_EXECUTION: {
                    EXEC_KEY_STATUS: EXEC_STATUS_NOT_EXECUTED,
                    EXEC_KEY_RAN: False,
                },
            }
        elif case.get(CASE_FIELD_TEMPLATE) == TEMPLATE_SWEBENCH_REAL_WORLD:
            from side_projects.graph_runner.nodes._swebench_helper import (
                build_swebench_exec_result,
            )
            exec_result = build_swebench_exec_result(case)
        else:
            from core.pipeline.execution.exec_canonical import exec_canonical
            exec_result = wrap_subprocess_call(
                self.NAME, self.effect_log,
                exec_canonical,
                case, parsed_gen, recon, config,
                None,  # logger
                attempt=0,
            )

        passed = exec_result.get(EXEC_KEY_PASS, False)

        return NodeResult(outputs={
            KEY_EXECUTION_RESULT: exec_result,
            KEY_PASSED: passed,
        })
