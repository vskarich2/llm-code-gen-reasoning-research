"""ClassifierAggregationNode — aggregate multiple classifier results.

Pure node. Decouples downstream logic from specific classifier implementations.
Produces classifier_summary with a .primary field for backward compatibility.
Uses extract_canonical_dims() as the single source of truth for dimension mapping.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    FIELD_ALL,
    FIELD_CANONICAL_DIMS,
    FIELD_CLASSIFY_EVENT_ID,
    FIELD_PRIMARY,
    FIELD_PRIMARY_ID,
    FIELD_RESULT,
    KEY_CLASSIFIER_RESULTS,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CLASSIFY_EVENT_ID,
    NODE_TYPE_PURE,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class ClassifierAggregationNode(BaseNode):
    NAME = "ClassifierAggregationNode"
    INPUT_KEYS = frozenset({KEY_CLASSIFIER_RESULTS})
    OUTPUT_KEYS = frozenset({KEY_CLASSIFIER_SUMMARY, KEY_CLASSIFY_EVENT_ID})
    NODE_TYPE = NODE_TYPE_PURE

    def __init__(
        self, classifier_order: list[str] | None = None,
    ) -> None:
        self.classifier_order = classifier_order or []

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        classifier_results = inputs[KEY_CLASSIFIER_RESULTS]

        if not classifier_results:
            return NodeResult(outputs={
                KEY_CLASSIFIER_SUMMARY: {
                    FIELD_PRIMARY: None,
                    FIELD_ALL: {},
                    FIELD_CANONICAL_DIMS: {},
                    FIELD_CLASSIFY_EVENT_ID: None,
                    FIELD_PRIMARY_ID: None,
                },
                KEY_CLASSIFY_EVENT_ID: None,
            })

        primary_id = self.resolve_primary(classifier_results)
        primary_entry = classifier_results[primary_id]

        primary_result = primary_entry.get(FIELD_RESULT)
        classify_eid = primary_entry.get(FIELD_CLASSIFY_EVENT_ID)

        # Use canonical dimension extractor from evaluator_v2
        canonical_dims: dict[str, Any] = {}
        if primary_result is not None:
            from core.evaluation.evaluator_v2 import _extract_canonical_dims
            canonical_dims = _extract_canonical_dims(primary_result)

        summary = {
            FIELD_PRIMARY: primary_result,
            FIELD_ALL: dict(classifier_results),
            FIELD_CANONICAL_DIMS: canonical_dims,
            FIELD_CLASSIFY_EVENT_ID: classify_eid,
            FIELD_PRIMARY_ID: primary_id,
        }

        return NodeResult(outputs={
            KEY_CLASSIFIER_SUMMARY: summary,
            KEY_CLASSIFY_EVENT_ID: classify_eid,
        })

    def resolve_primary(
        self, classifier_results: dict[str, Any],
    ) -> str:
        """Return the primary classifier ID (first in config order)."""
        for cid in self.classifier_order:
            if cid in classifier_results:
                return cid
        return next(iter(classifier_results))
