"""AST-based structural verification of generated code.

Non-gating analytical stage. Executes whenever a case has AST coverage.
Missing spec is explicitly recorded, not silently omitted.

Uses the mature checker system from scripts/ast_phase1/checkers.py as the
detection backend. That module provides strict/relaxed/anti/partial checkers
for 21 case families covering 52 of 58 benchmark cases.

Status states:
  no_spec          — no AST spec for this case
  not_measurable   — spec exists but code not parseable or no files
  measured_correct — relaxed check passes AND anti check fails (if present)
  measured_incorrect — relaxed check fails OR anti check passes
"""

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("t3.ast_eval")

# Lazy import of the checker system
_checker_module = None
_checker_fixes_module = None


def _load_checkers():
    """Load the AST checker modules from core.evaluation."""
    global _checker_module, _checker_fixes_module
    if _checker_module is not None:
        return

    try:
        from core.evaluation import ast_checkers
        _checker_module = ast_checkers
    except Exception as e:
        _log.warning("Failed to import ast_checkers: %s", e)
        return

    try:
        from core.evaluation import ast_checker_overrides
        _checker_fixes_module = ast_checker_overrides
    except ImportError:
        _checker_fixes_module = None


def _get_rules(case_id: str):
    """Get checker rules for a case. Returns (rules_tuple, is_module_level) or (None, False)."""
    _load_checkers()
    if _checker_module is None:
        return None, False

    # Check overrides first (v2 fixes for specific cases)
    if _checker_fixes_module is not None:
        # checker_fixes_v2 uses CHECKER_V2_OVERRIDES
        overrides = getattr(_checker_fixes_module, "CHECKER_V2_OVERRIDES", {})
        if not overrides:
            overrides = getattr(_checker_fixes_module, "CASE_RULES_OVERRIDES", {})
        module_level = getattr(_checker_fixes_module, "MODULE_LEVEL_CASES", {})
        if case_id in overrides:
            return overrides[case_id], False
        if case_id in module_level:
            return module_level[case_id], True

    rules = getattr(_checker_module, "CASE_RULES", {})
    if case_id in rules:
        return rules[case_id], False

    return None, False


@dataclass
class ASTResult:
    status: str                          # no_spec | not_measurable | measured_correct | measured_incorrect
    ast_correct: bool | None = None      # True/False for measured_*, None otherwise
    ast_score: float | None = None       # 1.0 if correct, 0.0 if incorrect, None if not measurable
    patterns_matched: list[str] = field(default_factory=list)
    patterns_missing: list[str] = field(default_factory=list)
    reason: str | None = None            # populated for not_measurable
    artifact_id: str = "no_artifact"
    strict_pass: bool | None = None      # strict checker result
    relaxed_pass: bool | None = None     # relaxed checker result
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "ast_correct": self.ast_correct,
            "ast_score": self.ast_score,
            "patterns_matched": self.patterns_matched,
            "patterns_missing": self.patterns_missing,
            "reason": self.reason,
            "artifact_id": self.artifact_id,
            "strict_pass": self.strict_pass,
            "relaxed_pass": self.relaxed_pass,
        }


def check_ast_patterns(reconstructed_files: dict[str, str] | None,
                       case_id: str,
                       artifact_id: str = "no_artifact") -> ASTResult:
    """Check AST patterns for a case using the ast_phase1 checker system.

    Args:
        reconstructed_files: dict of {filename: code_content} from reconstruction.
                            Must be the SAME snapshot used for execution.
        case_id: case identifier for checker lookup.
        artifact_id: hash of the reconstructed code.

    Returns ASTResult with one of four statuses.
    """
    rules, is_module_level = _get_rules(case_id)

    # No checker for this case
    if rules is None:
        return ASTResult(status="no_spec", artifact_id=artifact_id)

    # No files to analyze
    if not reconstructed_files:
        return ASTResult(status="not_measurable", reason="no_reconstructed_files",
                         artifact_id=artifact_id)

    # Concatenate all files for analysis (same as execution assembly)
    combined_code = "\n\n".join(reconstructed_files.values())

    # Parse into AST
    try:
        tree = ast.parse(combined_code)
    except SyntaxError as e:
        return ASTResult(status="not_measurable",
                         reason=f"syntax_error: {e}",
                         artifact_id=artifact_id)

    # Unpack rules: (func_name, strict_fn, relaxed_fn, anti_fn, partial_fn)
    func_name, strict_fn, relaxed_fn, anti_fn, partial_fn = rules

    if is_module_level:
        # Module-level check: pass the tree directly
        target = tree
    else:
        _load_checkers()
        find_function = getattr(_checker_module, "find_function", None)
        if find_function is None:
            return ASTResult(status="not_measurable", reason="find_function not available",
                             artifact_id=artifact_id)
        target = find_function(tree, func_name)
        if target is None:
            return ASTResult(
                status="measured_incorrect",
                ast_correct=False,
                ast_score=0.0,
                patterns_missing=[f"function '{func_name}' not found"],
                artifact_id=artifact_id,
                detail=f"target function '{func_name}' not found in code",
            )

    # Run checkers (None means no checker defined — not an error)
    if strict_fn is not None:
        try:
            strict_ok = strict_fn(target)
        except Exception as e:
            strict_ok = False
            _log.warning("strict checker EXCEPTION for case=%s func=%s: %s", case_id, func_name, e)
    else:
        strict_ok = False

    if relaxed_fn is not None:
        try:
            relaxed_ok = relaxed_fn(target)
        except Exception as e:
            relaxed_ok = False
            _log.warning("relaxed checker EXCEPTION for case=%s func=%s: %s", case_id, func_name, e)
    else:
        relaxed_ok = False

    anti_found = False
    if anti_fn is not None:
        try:
            anti_found = anti_fn(target)
        except Exception as e:
            anti_found = False
            _log.warning("anti checker EXCEPTION for case=%s func=%s: %s", case_id, func_name, e)

    # Determine correctness: relaxed pass AND no anti-pattern
    correct = relaxed_ok and not anti_found

    matched = []
    missing = []
    if strict_ok:
        matched.append("strict")
    if relaxed_ok:
        matched.append("relaxed")
    if anti_found:
        missing.append("anti_pattern_present")
    if not relaxed_ok:
        missing.append("relaxed_check_failed")

    return ASTResult(
        status="measured_correct" if correct else "measured_incorrect",
        ast_correct=correct,
        ast_score=1.0 if correct else 0.0,
        patterns_matched=matched,
        patterns_missing=missing,
        artifact_id=artifact_id,
        strict_pass=strict_ok,
        relaxed_pass=relaxed_ok,
        detail=f"strict={strict_ok}, relaxed={relaxed_ok}, anti={anti_found}",
    )
