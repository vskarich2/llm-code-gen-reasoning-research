"""ReconstructNode — reconstruct code files from parsed output.

Wraps reconstructor.reconstruct_strict() and builds the materialized
code string + artifact ID.
Pure node: no side effects.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.pipeline.reconstructor import ReconstructionResult, reconstruct_strict
from side_projects.graph_runner.constants import (
    ARTIFACT_ID_NONE,
    CASE_FIELD_LOGICAL_FILE_KEYS,
    FILE_MARKER_MODIFIED,
    FILE_MARKER_UNCHANGED,
    GENERATION_CONTRACT,
    KEY_ARTIFACT_ID,
    KEY_CASE,
    KEY_PARSED_GENERATION,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    NODE_TYPE_PURE,
    RECON_MISSING_FILES,
    RECON_SUCCESS,
    STATUS_GENERATION_CONTRACT_VIOLATION,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


def build_full_code(
    recon: ReconstructionResult,
    logical_paths: list[str],
) -> str:
    """Build full materialized code string with file markers."""
    if recon.status != RECON_SUCCESS or not recon.files:
        return ""
    parts: list[str] = []
    for path in logical_paths:
        if path in recon.files:
            marker = (
                FILE_MARKER_MODIFIED if path in recon.changed_files
                else FILE_MARKER_UNCHANGED
            )
            parts.append(f"# [{marker}] {path}\n{recon.files[path]}")
    return "\n\n".join(parts)


def compute_artifact_id(recon: ReconstructionResult) -> str:
    """Deterministic hash of reconstructed code."""
    if recon.status != RECON_SUCCESS or not recon.files:
        return ARTIFACT_ID_NONE
    content = json.dumps(
        dict(recon.files), sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class ReconstructNode(BaseNode):
    NAME = "ReconstructNode"
    INPUT_KEYS = frozenset({KEY_PARSED_GENERATION, KEY_CASE})
    OUTPUT_KEYS = frozenset({KEY_RECON, KEY_RECONSTRUCTED_CODE, KEY_ARTIFACT_ID})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        parsed_gen = inputs[KEY_PARSED_GENERATION]
        case = inputs[KEY_CASE]

        logical_files = case.get(CASE_FIELD_LOGICAL_FILE_KEYS)
        if not logical_files:
            raise ValueError(
                f"case missing {CASE_FIELD_LOGICAL_FILE_KEYS!r} — "
                "load_cases() must be called before reconstruction"
            )
        logical_paths = list(logical_files.keys())

        # Check generation output contract
        if parsed_gen.parse_valid and parsed_gen.full_json:
            missing = GENERATION_CONTRACT - set(
                parsed_gen.full_json.keys(),
            )
            if missing:
                recon = ReconstructionResult(
                    status=STATUS_GENERATION_CONTRACT_VIOLATION, files={},
                )
                return NodeResult(outputs={
                    KEY_RECON: recon,
                    KEY_RECONSTRUCTED_CODE: "",
                    KEY_ARTIFACT_ID: ARTIFACT_ID_NONE,
                })

        recon = ReconstructionResult(
            status=RECON_MISSING_FILES, files={},
        )
        if parsed_gen.files_dict:
            recon = reconstruct_strict(
                logical_paths, logical_files, parsed_gen.files_dict,
            )

        code = build_full_code(recon, logical_paths)
        artifact_id = compute_artifact_id(recon)

        return NodeResult(outputs={
            KEY_RECON: recon,
            KEY_RECONSTRUCTED_CODE: code,
            KEY_ARTIFACT_ID: artifact_id,
        })
