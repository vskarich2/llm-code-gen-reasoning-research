"""AssembleNode — build the final result dict from all pipeline state.

Reads all prior stage outputs and produces a single final_result dict
matching the case.end event schema.
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.runtime.constants import (
    FIELD_PRIMARY,
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CASE,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CLASSIFY_EVENT_ID,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_DISAGREEMENT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_FINAL_RESULT,
    KEY_FORMAT_PARSE,
    KEY_GEN_EVENT_ID,
    KEY_MODEL,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_SUMMARY,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_PROMPT_META,
    KEY_RAW_RESPONSE,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_RECOVERY_PARSE,
    KEY_RETRY_ELIGIBLE,
    KEY_ROUTING,
    KEY_SIGNALS,
    KEY_SPEC_ORACLE_RESULT,
    KEY_STRICT_PARSE,
    NODE_TYPE_PURE,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


ALL_INPUT_KEYS = frozenset({
    KEY_CASE, KEY_CONDITION, KEY_MODEL, KEY_CONFIG,
    KEY_PARSED_GENERATION, KEY_ROUTING, KEY_PARSE_MODE,
    KEY_RETRY_ELIGIBLE,
    KEY_NORMALIZED_REASONING,
    KEY_RECON, KEY_RECONSTRUCTED_CODE, KEY_ARTIFACT_ID,
    KEY_CLASSIFIER_SUMMARY, KEY_CLASSIFY_EVENT_ID,
    KEY_ORACLE_SUMMARY,
    KEY_AST_RESULT,
    KEY_EXECUTION_RESULT, KEY_PASSED,
    KEY_SPEC_ORACLE_RESULT,
    KEY_SIGNALS, KEY_DISAGREEMENT, KEY_EVALUATION,
    KEY_PROMPT_META, KEY_GEN_EVENT_ID,
    KEY_STRICT_PARSE, KEY_RECOVERY_PARSE, KEY_FORMAT_PARSE,
})


class AssembleNode(BaseNode):
    NAME = "AssembleNode"
    INPUT_KEYS = ALL_INPUT_KEYS
    OUTPUT_KEYS = frozenset({KEY_FINAL_RESULT})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        case = inputs[KEY_CASE]
        condition = inputs[KEY_CONDITION]
        model = inputs[KEY_MODEL]
        exec_result = inputs[KEY_EXECUTION_RESULT]
        evaluation = inputs[KEY_EVALUATION]
        oracle_summary = inputs[KEY_ORACLE_SUMMARY]
        classifier_summary = inputs[KEY_CLASSIFIER_SUMMARY]
        routing = inputs[KEY_ROUTING]
        recon = inputs[KEY_RECON]
        signals = inputs[KEY_SIGNALS]
        ast_result = inputs[KEY_AST_RESULT]
        disagreement = inputs[KEY_DISAGREEMENT]
        spec_oracle = inputs[KEY_SPEC_ORACLE_RESULT]
        prompt_meta = inputs[KEY_PROMPT_META]
        artifact_id = inputs[KEY_ARTIFACT_ID]

        primary_oracle = oracle_summary.get(FIELD_PRIMARY, {})
        primary_classifier = classifier_summary.get(FIELD_PRIMARY)

        result = {
            "case_id": case.get("id", ""),
            "condition": condition,
            "model": model,
            "pass": exec_result.get("pass", False),
            "score": exec_result.get("score", 0.0),

            "evaluation": evaluation,

            "oracle": primary_oracle,

            "classification": self.build_classification_section(
                classifier_summary, artifact_id,
            ),

            "reconstruction": self.build_reconstruction_section(
                routing, recon, inputs,
            ),

            "ast_eval": (
                ast_result.to_dict()
                if hasattr(ast_result, "to_dict")
                else ast_result
            ),

            "reasoning_disagreement": disagreement,

            "prompt_meta": prompt_meta,

            "signals": (
                signals.__dict__
                if hasattr(signals, "__dict__")
                else signals
            ),
        }

        if spec_oracle is not None:
            result["spec_oracle"] = spec_oracle

        return NodeResult(outputs={KEY_FINAL_RESULT: result})

    def build_classification_section(
        self, classifier_summary: dict, artifact_id: str,
    ) -> dict:
        primary = classifier_summary.get(FIELD_PRIMARY)
        canonical = classifier_summary.get("canonical_dims", {})
        classify_eid = classifier_summary.get("classify_event_id")

        section: dict[str, Any] = {}
        section["reasoning_internal_consistency"] = canonical.get(
            "reasoning_internal_consistency",
        )
        section["commitments_extracted"] = canonical.get(
            "commitments_extracted",
        )
        section["commitments_satisfied"] = canonical.get(
            "commitments_satisfied",
        )
        section["reasoning_code_alignment"] = canonical.get(
            "reasoning_code_alignment",
        )
        section["classifier_ran"] = primary is not None
        section["artifact_id"] = artifact_id
        section["classify_event_id"] = classify_eid
        return section

    def build_reconstruction_section(
        self, routing: Any, recon: Any, inputs: dict,
    ) -> dict:
        source = getattr(routing, "selected_source", "none")
        return {
            "parsing_mode": source,
            "strict_parse_valid": getattr(
                routing, "strict_parse_valid", False,
            ),
            "recovery_parse_valid": getattr(
                routing, "recovery_parse_valid", False,
            ),
            "recovery_used": getattr(
                routing, "recovery_used", False,
            ),
            "recon_status": recon.status if recon else "MISSING",
            "artifact_id": inputs.get(KEY_ARTIFACT_ID, ""),
            "parse_mode": inputs.get(KEY_PARSE_MODE, ""),
            "retry_eligible": inputs.get(KEY_RETRY_ELIGIBLE, False),
        }
