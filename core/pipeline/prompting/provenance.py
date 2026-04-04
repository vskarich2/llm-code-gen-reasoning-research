"""Provenance artifact construction and serialization.

Every field in provenance must reflect an actual guarantee,
not an aspiration. See plan v4 Section 13 for honesty policy.
"""

from __future__ import annotations

import json
from typing import Any

from core.pipeline.prompting.contracts import CompiledPrompt


def serialize_provenance(compiled: CompiledPrompt) -> str:
    """Serialize provenance to JSON string for logging."""
    return json.dumps(compiled.provenance, indent=2, sort_keys=True)


def provenance_summary(compiled: CompiledPrompt) -> dict[str, Any]:
    """Compact provenance for inline logging (not full artifact)."""
    return {
        "program": compiled.program_name,
        "condition": compiled.condition,
        "components": list(compiled.component_order),
        "prompt_hash": compiled.final_prompt_hash[:16],
        "composition_hash": compiled.composition_hash[:16],
        "structural_valid": compiled.structural_valid,
        "accessed_count": len(compiled.accessed_inputs),
        "unused_count": len(compiled.unused_inputs),
    }
