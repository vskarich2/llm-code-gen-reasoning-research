"""ASTNode — AST structural verification of reconstructed code.

Runs before execution. Checks that reconstructed files are syntactically
valid Python via ast.parse().
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    AST_REASON_RECON_FAILED,
    AST_STATUS_NOT_MEASURABLE,
    CASE_FIELD_ID,
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CASE,
    KEY_RECON,
    NODE_TYPE_PURE,
    RECON_SUCCESS,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class ASTNode(BaseNode):
    NAME = "ASTNode"
    INPUT_KEYS = frozenset({KEY_RECON, KEY_CASE, KEY_ARTIFACT_ID})
    OUTPUT_KEYS = frozenset({KEY_AST_RESULT})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        recon = inputs[KEY_RECON]
        artifact_id = inputs[KEY_ARTIFACT_ID]

        if recon.status == RECON_SUCCESS and recon.files:
            from core.evaluation.ast_eval import check_ast_patterns
            result = check_ast_patterns(
                reconstructed_files=dict(recon.files),
                case_id=inputs[KEY_CASE].get(CASE_FIELD_ID, ""),
                artifact_id=artifact_id,
            )
        else:
            from core.evaluation.ast_eval import ASTResult
            result = ASTResult(
                status=AST_STATUS_NOT_MEASURABLE,
                reason=AST_REASON_RECON_FAILED,
                artifact_id=artifact_id,
            )

        return NodeResult(outputs={KEY_AST_RESULT: result})
