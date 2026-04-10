"""OracleAggregationNode — aggregate multiple oracle results.

Pure node. Decouples downstream logic from specific oracle implementations.
Produces oracle_summary with a .primary field for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.runtime.constants import (
    FIELD_ALL,
    FIELD_ORACLE_CORRECT,
    FIELD_PRIMARY,
    FIELD_PRIMARY_ID,
    FIELD_REASONING_TRUTH,
    KEY_ORACLE_RESULTS,
    KEY_ORACLE_SUMMARY,
    NODE_TYPE_PURE,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


class OracleAggregationNode(BaseNode):
    NAME = "OracleAggregationNode"
    INPUT_KEYS = frozenset({KEY_ORACLE_RESULTS})
    OUTPUT_KEYS = frozenset({KEY_ORACLE_SUMMARY})
    NODE_TYPE = NODE_TYPE_PURE

    def __init__(self, oracle_order: list[str] | None = None) -> None:
        self.oracle_order = oracle_order or []

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        oracle_results = inputs[KEY_ORACLE_RESULTS]

        if not oracle_results:
            return NodeResult(outputs={
                KEY_ORACLE_SUMMARY: {
                    FIELD_PRIMARY: {},
                    FIELD_ALL: {},
                    FIELD_ORACLE_CORRECT: None,
                    FIELD_REASONING_TRUTH: None,
                },
            })

        # Primary = first oracle in config order
        primary_id = self.resolve_primary(oracle_results)
        primary = oracle_results[primary_id]

        summary = {
            FIELD_PRIMARY: primary,
            FIELD_ALL: dict(oracle_results),
            FIELD_ORACLE_CORRECT: primary.get(FIELD_ORACLE_CORRECT),
            FIELD_REASONING_TRUTH: primary.get(FIELD_REASONING_TRUTH),
            FIELD_PRIMARY_ID: primary_id,
        }

        return NodeResult(outputs={KEY_ORACLE_SUMMARY: summary})

    def resolve_primary(
        self, oracle_results: dict[str, Any],
    ) -> str:
        """Return the primary oracle ID (first in config order)."""
        for oid in self.oracle_order:
            if oid in oracle_results:
                return oid
        # Fallback: first key in dict (insertion order)
        return next(iter(oracle_results))
