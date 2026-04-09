"""MetricsNode — compute evaluation signals from aggregated outputs.

Reads from oracle_summary and classifier_summary (aggregated),
NOT from raw individual results. Reimplements the evaluation
computation from execution_v2._compute_evaluation().
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    EXEC_KEY_EXECUTION_CATEGORY,
    EXEC_SUCCESS,
    FIELD_CANONICAL_DIMS,
    FIELD_ORACLE_CORRECT,
    FIELD_PRIMARY,
    FIELD_REASONING_TRUTH,
    KEY_ARTIFACT_ID,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CONFIG,
    KEY_DISAGREEMENT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_SUMMARY,
    KEY_PARSED_GENERATION,
    KEY_RECON,
    KEY_ROUTING,
    KEY_SIGNALS,
    NODE_TYPE_PURE,
    RECON_SUCCESS,
    ROUTE_SOURCE_NONE,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class MetricsNode(BaseNode):
    NAME = "MetricsNode"
    INPUT_KEYS = frozenset({
        KEY_ORACLE_SUMMARY, KEY_CLASSIFIER_SUMMARY,
        KEY_EXECUTION_RESULT, KEY_NORMALIZED_REASONING,
        KEY_PARSED_GENERATION, KEY_ARTIFACT_ID,
        KEY_ROUTING, KEY_RECON, KEY_CONFIG,
    })
    OUTPUT_KEYS = frozenset({KEY_SIGNALS, KEY_DISAGREEMENT, KEY_EVALUATION})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        oracle_summary = inputs[KEY_ORACLE_SUMMARY]
        classifier_summary = inputs[KEY_CLASSIFIER_SUMMARY]
        exec_result = inputs[KEY_EXECUTION_RESULT]
        artifact = inputs[KEY_NORMALIZED_REASONING]
        parsed_gen = inputs[KEY_PARSED_GENERATION]
        artifact_id = inputs[KEY_ARTIFACT_ID]
        routing = inputs[KEY_ROUTING]
        recon = inputs[KEY_RECON]
        config = inputs[KEY_CONFIG]

        primary_oracle = oracle_summary.get(FIELD_PRIMARY, {})
        primary_classifier = classifier_summary.get(FIELD_PRIMARY)
        canonical_dims = classifier_summary.get(FIELD_CANONICAL_DIMS, {})

        signals = self.derive_signals(
            canonical_dims, exec_result, artifact,
        )
        disagreement = self.compute_disagreement(
            primary_classifier, primary_oracle, config,
        )
        evaluation = self.compute_evaluation(
            routing, recon, exec_result,
            primary_classifier, primary_oracle,
            artifact_id, canonical_dims,
        )

        return NodeResult(outputs={
            KEY_SIGNALS: signals,
            KEY_DISAGREEMENT: disagreement,
            KEY_EVALUATION: evaluation,
        })

    def derive_signals(
        self, canonical_dims: dict, exec_result: dict,
        artifact: Any,
    ) -> Any:
        """Derive V2 signals from canonical classifier dims."""
        from core.evaluation.metrics_v2 import derive_v2_signals
        code_correct = exec_result.get("pass", False)
        commitments_source = (
            getattr(artifact, "commitments_source", "none") or "none"
        )
        return derive_v2_signals(
            canonical_dims, code_correct, commitments_source,
        )

    def compute_disagreement(
        self, classifier_result: Any,
        oracle_result: dict, config: Any,
    ) -> dict:
        """Compute oracle-classifier disagreement."""
        from core.evaluation.oracle_inline import compute_disagreement
        return compute_disagreement(
            classifier_result, oracle_result, config,
        )

    def compute_evaluation(
        self, routing: Any, recon: Any,
        exec_result: dict, classification: Any,
        oracle_result: dict, artifact_id: str,
        canonical_dims: dict,
    ) -> dict:
        """Compute full evaluation dict.

        Reimplements _compute_evaluation from execution_v2.py
        using aggregated summary outputs.
        """
        execution_category = exec_result.get(EXEC_KEY_EXECUTION_CATEGORY)
        execution_pass = (execution_category == EXEC_SUCCESS)
        reconstruction_success = (recon.status == RECON_SUCCESS)
        source = getattr(routing, "selected_source", ROUTE_SOURCE_NONE)
        routing_valid = (source != ROUTE_SOURCE_NONE)

        oracle_label = oracle_result.get(FIELD_REASONING_TRUTH)
        oracle_correct = oracle_result.get(FIELD_ORACLE_CORRECT)
        r_bool = oracle_correct

        classifier_ran = (
            classification is not None
            and getattr(classification, "parse_error", "skip") is None
        )

        if classifier_ran and canonical_dims:
            ric = canonical_dims.get("reasoning_internal_consistency")
            ccc = canonical_dims.get("commitments_satisfied")
            t_bool = (ric == "CORRECT") and (ccc == "CORRECT")
            dims = {
                "RIC": ric,
                "CIC": canonical_dims.get("commitments_extracted"),
                "CCC": ccc,
                "RCA": canonical_dims.get("reasoning_code_alignment"),
            }
        else:
            t_bool = None
            dims = {"RIC": None, "CIC": None, "CCC": None, "RCA": None}

        # Outcome classification
        if not routing_valid or not reconstruction_success:
            outcome = "serialization_failure"
        elif oracle_label is None:
            outcome = "oracle_not_available"
        elif not classifier_ran:
            outcome = "classifier_not_run"
        elif r_bool is True and execution_pass is True:
            outcome = "interpretable_success"
        elif r_bool is False and execution_pass is True:
            outcome = "lucky_fix"
        elif r_bool is True and execution_pass is False:
            outcome = "LEG"
        elif r_bool is False and execution_pass is False:
            if t_bool is True:
                outcome = "coherent_incorrect"
            elif t_bool is False:
                outcome = "incoherent_incorrect"
            else:
                outcome = "reasoning_failure_unknown"
        else:
            outcome = "unclassified"

        leg_subtype = None
        if outcome == "LEG":
            if t_bool is True:
                leg_subtype = "execution_failure"
            elif t_bool is False:
                leg_subtype = "translation_failure"
            else:
                leg_subtype = "unknown"

        quadrant_rt = None
        if isinstance(r_bool, bool) and isinstance(t_bool, bool):
            quadrant_rt = f"R{int(r_bool)}_T{int(t_bool)}"
        quadrant_re = None
        if isinstance(r_bool, bool):
            quadrant_re = f"R{int(r_bool)}_E{int(execution_pass)}"

        return {
            "execution_pass": execution_pass,
            "reconstruction_success": reconstruction_success,
            "routing_valid": routing_valid,
            "execution_category": execution_category,
            "oracle_label": oracle_label,
            "oracle_correct": oracle_correct,
            "reasoning_correct": r_bool,
            "classifier_ran": classifier_ran,
            "classifier_dims": dims,
            "translation_consistent": t_bool,
            "outcome_class": outcome,
            "LEG": outcome == "LEG",
            "LEG_subtype": leg_subtype,
            "quadrant_RT": quadrant_rt,
            "quadrant_RE": quadrant_re,
            "artifact_id": artifact_id,
        }
