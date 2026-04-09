"""SWE-bench execution result builder.

Extracted from stages.py _swebench_exec_result() to avoid
importing the V2 orchestration layer.
"""

from __future__ import annotations

from core.constants.pipeline_constants import (
    EXEC_INVARIANT_FAILURE,
    EXEC_STRUCTURAL_FAILURE,
    EXEC_SUCCESS,
    EXEC_SYNTAX_FAILURE,
)


def build_swebench_exec_result(case: dict) -> dict:
    """Build exec_result from pre-computed SWE-bench Docker results."""
    swe = case.get("_swebench", {})
    resolved = swe.get("resolved_v5", False)
    fail_cat = swe.get("failure_category_v5", "UNKNOWN")

    if resolved:
        category = EXEC_SUCCESS
    elif fail_cat == "EMPTY_PATCH":
        category = EXEC_STRUCTURAL_FAILURE
    elif fail_cat in ("SYNTAX_ERROR", "IMPORT_ERROR"):
        category = EXEC_SYNTAX_FAILURE
    else:
        category = EXEC_INVARIANT_FAILURE

    return {
        "pass": resolved,
        "score": 1.0 if resolved else 0.0,
        "reasons": [] if resolved else [f"SWE-bench Docker: {fail_cat}"],
        "failure_modes": [] if resolved else [fail_cat],
        "execution": {
            "status": "passed" if resolved else "failed",
            "ran": True,
            "passed_tests": 1 if resolved else 0,
            "total_tests": 1,
            "runtime_error": None,
            "invariant_pass": resolved,
            "mutation_pass": None,
        },
        "execution_category": category,
        "execution_subtype": None if resolved else fail_cat,
        "modules_loaded": [],
        "functions_detected": [],
        "functions_called": [],
        "merge_conflicts": [],
        "execution_trace": [],
        "reconstruction_status": None,
        "semantic_diagnostics": {
            "missing_required_definitions": False,
            "missing_definition_names": [],
        },
        "_extracted_code": "",
        "_assembled_code": "swebench_docker",
    }
