"""Pipeline integrity checks.

Centralized gates that catch silent data-quality bugs before they
waste API calls or produce meaningless metrics. Every check either
logs a warning or raises RuntimeError — no silent failures.

Called from: evaluator_v2, execution_v2, orchestrate (smoke gate).
"""

import logging

_log = logging.getLogger("t3.checks")


def check_classifier_code_nonempty(code: str, case_id: str) -> None:
    """Warn if the classifier will receive empty code.

    Empty code causes all code-dependent dimensions
    (commitments_satisfied, reasoning_code_alignment,
    commitments_code_consistency) to degenerate into plausibility
    checks with no discriminative power.
    """
    if not code or not code.strip():
        _log.warning(
            "CLASSIFIER_EMPTY_CODE case=%s: code string is empty. "
            "Code-dependent classifier dimensions will be meaningless.",
            case_id,
        )


def check_reconstruction_produced_code(
    recon_status: str,
    recon_files: dict,
    materialized_code: str,
    logical_paths: list[str],
) -> None:
    """Hard gate: if reconstruction succeeded with files, code MUST exist.

    Catches path-matching bugs where recon.files has content but the
    materialized code string is empty (e.g., logical_paths don't match
    recon.files keys).

    Raises RuntimeError with diagnostic info.
    """
    if recon_status == "SUCCESS" and recon_files and not materialized_code.strip():
        raise RuntimeError(
            f"CLASSIFIER CODE GATE: recon SUCCESS with "
            f"{len(recon_files)} files but materialized code is empty. "
            f"This is a path-matching bug — "
            f"logical_paths={logical_paths}, "
            f"recon.files keys={sorted(recon_files.keys())}"
        )


def check_smoke_classifier_visibility(ev: dict, label: str) -> None:
    """Smoke gate check: classifier must have received non-empty code.

    Called after a smoke case completes. If the classifier ran but
    _extracted_code is empty, the classifier saw no code and all
    code-dependent dimensions are meaningless.

    Raises RuntimeError to abort the run before wasting API calls.
    """
    if ev.get("classifier_ran") and not ev.get("_extracted_code"):
        raise RuntimeError(
            f"SMOKE GATE FAILED ({label}): classifier ran but "
            f"_extracted_code is empty. Classifier received no code — "
            f"all code-dependent dimensions are meaningless."
        )
