"""Pre-write WAL event validation.

Checks structural presence, semantic consistency, and trajectory invariants
before event emission. Violations are logged and flagged, never silently
swallowed.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("t3.event_validation")


def validate_event(ev: dict, trajectory: list | None, best_idx: int) -> list[str]:
    """Validate event dict before WAL emission.

    Uses == (value equality) throughout — never `is` (pointer identity).
    Returns list of violation descriptions. Empty list = valid.
    """
    violations: list[str] = []
    _check_structural(ev, violations)
    _check_semantic(ev, violations)
    if trajectory:
        _check_trajectory(ev, trajectory, best_idx, violations)
    return violations


def _check_structural(ev: dict, violations: list[str]) -> None:
    """Check required sections exist with required fields."""
    if ev.get("_schema_version") != "v3.1":
        violations.append(
            f"wrong _schema_version: {ev.get('_schema_version')!r}")

    oracle = ev.get("oracle")
    if oracle is None:
        violations.append("missing payload.oracle")
    else:
        if oracle.get("status") is None:
            violations.append("oracle.status is null")
        if oracle.get("reasoning_truth") is None:
            violations.append("oracle.reasoning_truth is null")

    if "classification" not in ev:
        violations.append("missing payload.classification")

    if "ast_eval" not in ev:
        violations.append("missing payload.ast_eval")

    if "evaluation" not in ev:
        violations.append("missing payload.evaluation")


def _check_semantic(ev: dict, violations: list[str]) -> None:
    """Cross-field consistency checks."""
    oracle = ev.get("oracle", {})
    rt = oracle.get("reasoning_truth")
    oc = oracle.get("oracle_correct")
    pm = oracle.get("partial_mode", "lenient")

    if rt and oc is not None and rt not in ("UNASSESSED", "UNJUDGABLE"):
        if pm == "strict":
            expected = (rt == "CORRECT")
        else:
            expected = rt in ("CORRECT", "PARTIAL")
        if oc != expected:
            violations.append(
                f"oracle_correct={oc} inconsistent with "
                f"reasoning_truth={rt} under partial_mode={pm}")

    # Oracle skip reason must be specific, not generic
    oracle_status = oracle.get("status")
    oracle_error = oracle.get("error")
    _VALID_SKIP_ERRORS = frozenset({
        "missing_root_cause", "missing_fix_strategy",
        "missing_root_cause_and_fix_strategy", "reasoning_too_short",
    })
    if oracle_status == "SKIPPED" and oracle_error not in _VALID_SKIP_ERRORS:
        violations.append(
            f"oracle status=SKIPPED with unrecognized error={oracle_error!r}. "
            f"Valid: {sorted(_VALID_SKIP_ERRORS)}")

    ast = ev.get("ast_eval", {})
    ast_status = ast.get("status")
    ast_correct = ast.get("ast_correct")
    if ast_status == "measured_correct" and ast_correct is not True:
        violations.append(
            f"ast_status=measured_correct but ast_correct={ast_correct}")
    if ast_status == "measured_incorrect" and ast_correct is not False:
        violations.append(
            f"ast_status=measured_incorrect but ast_correct={ast_correct}")
    if ast_status in ("no_spec", "not_measurable") and ast_correct is not None:
        violations.append(
            f"ast_status={ast_status} but ast_correct={ast_correct}")


def _check_trajectory(
    ev: dict, trajectory: list, best_idx: int, violations: list[str],
) -> None:
    """Trajectory invariant checks (INV-TRAJ-1 through INV-TRAJ-7)."""
    n = len(trajectory)

    if ev.get("num_attempts") != n:
        violations.append(
            f"num_attempts={ev.get('num_attempts')} != "
            f"len(trajectory)={n}")

    required_keys = ("execution", "oracle", "classifier", "ast",
                     "reasoning_disagreement")
    for k, entry in enumerate(trajectory):
        if entry.get("attempt") != k:
            violations.append(
                f"trajectory[{k}].attempt={entry.get('attempt')} != {k}")
        for key in required_keys:
            if key not in entry:
                violations.append(f"trajectory[{k}] missing '{key}'")

    if 0 <= best_idx < n:
        best = trajectory[best_idx]
        if ev.get("oracle") != best.get("oracle"):
            violations.append(
                "payload.oracle != trajectory[best_idx].oracle")
        if ev.get("classification") != best.get("classifier"):
            violations.append(
                "payload.classification != trajectory[best_idx].classifier")
        if ev.get("ast_eval") != best.get("ast"):
            violations.append(
                "payload.ast_eval != trajectory[best_idx].ast")


def apply_validation(ev: dict, trajectory: list | None,
                     best_idx: int, cid: str) -> None:
    """Run validation and attach violations to event if any found."""
    violations = validate_event(ev, trajectory, best_idx)
    if violations:
        _log.error("PRE-WRITE VALIDATION FAILED for %s: %s", cid, violations)
        ev["_validation_violations"] = violations
