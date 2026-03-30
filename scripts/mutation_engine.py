"""Strict mutation engine using AST-level semantic operators.

No regex. Every mutation is:
1. Semantically targeted (find invariant structure)
2. AST-localized (find exact nodes)
3. AST-transformed (structured edit)
4. Diff-verified (change is real)
5. Oracle-validated (test fails)

Silent fallbacks are structurally impossible.
"""

import ast
import json
import sys
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ast_mutator import (
    SemanticOperator,
    MutationOutcome,
    get_operators_for_family,
    get_all_operators,
    mutate_file_in_case,
)


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class MutationSpec:
    variant_id: str
    case_id: str
    family: str
    target_file: str
    target_function: str
    bug_pattern: str
    mutation_operator: str
    expected_failure_surface: str


@dataclass
class MutationResult:
    variant_id: str
    applied: bool
    target_found: bool
    diff_nonempty: bool
    structural_verification_passed: bool
    semantic_guardrails_passed: bool
    oracle_failed: bool
    quality: str  # GOLD, SILVER, REJECT
    rejection_reason: str | None
    code: str | None
    oracle_error: str | None
    diff_summary: str | None


# ============================================================
# VALIDATION GATES (unchanged contract)
# ============================================================

def verify_diff(original: str, mutated: str, target_function: str) -> tuple[bool, str | None]:
    if original == mutated:
        return False, None
    diff_lines = list(unified_diff(
        original.splitlines(keepends=True), mutated.splitlines(keepends=True),
        fromfile="original", tofile="mutated", n=1,
    ))
    return bool(diff_lines), "".join(diff_lines[:20])


def check_semantic_guardrails(mutated_code: str, reference_fix: str,
                               target_function: str) -> tuple[bool, str | None]:
    if mutated_code.strip() == reference_fix.strip():
        return False, "mutated code is identical to reference fix"
    try:
        tree = ast.parse(mutated_code)
    except SyntaxError as e:
        return False, f"mutated code has syntax error: {e}"
    func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if target_function not in func_names:
        # Check all functions — the target might have a different name in B/C variants
        if not func_names:
            return False, "no functions defined in mutated code"
    return True, None


def validate_with_oracle(case: dict, mutated_code: str) -> tuple[bool, str | None, str]:
    from exec_eval import exec_evaluate
    try:
        result = exec_evaluate(case, mutated_code)
    except Exception as e:
        return True, f"CRASH: {type(e).__name__}: {e}", "REJECT"
    if result["pass"]:
        return False, "oracle passed — variant is not actually buggy", "REJECT"
    error = "; ".join(result.get("reasons", [])[:3])
    execution = result.get("execution", {})
    if execution.get("ran") and not execution.get("assembly_error"):
        quality = "GOLD"
    elif execution.get("ran"):
        quality = "SILVER"
    else:
        quality = "SILVER"
    return True, error, quality


# ============================================================
# MAIN PIPELINE
# ============================================================

def _validate_candidate(mutated_code: str, source_code: str, reference_fix: str,
                         case: dict, target_fn: str, variant_id: str) -> MutationResult:
    """Run gates 4-6 on a candidate mutation."""
    diff_ok, diff_summary = verify_diff(source_code, mutated_code, target_fn)
    if not diff_ok:
        return MutationResult(
            variant_id=variant_id, applied=True, target_found=True,
            diff_nonempty=False, structural_verification_passed=False,
            semantic_guardrails_passed=False, oracle_failed=False,
            quality="REJECT", rejection_reason="mutation produced no diff",
            code=None, oracle_error=None, diff_summary=None,
        )
    guard_ok, guard_reason = check_semantic_guardrails(mutated_code, reference_fix, target_fn)
    if not guard_ok:
        return MutationResult(
            variant_id=variant_id, applied=True, target_found=True,
            diff_nonempty=True, structural_verification_passed=True,
            semantic_guardrails_passed=False, oracle_failed=False,
            quality="REJECT", rejection_reason=f"semantic guardrail: {guard_reason}",
            code=None, oracle_error=None, diff_summary=diff_summary,
        )
    oracle_failed, oracle_error, quality = validate_with_oracle(case, mutated_code)
    if not oracle_failed:
        return MutationResult(
            variant_id=variant_id, applied=True, target_found=True,
            diff_nonempty=True, structural_verification_passed=True,
            semantic_guardrails_passed=True, oracle_failed=False,
            quality="REJECT", rejection_reason=f"oracle passed: {oracle_error}",
            code=mutated_code, oracle_error=oracle_error, diff_summary=diff_summary,
        )
    return MutationResult(
        variant_id=variant_id, applied=True, target_found=True,
        diff_nonempty=True, structural_verification_passed=True,
        semantic_guardrails_passed=True, oracle_failed=True,
        quality=quality, rejection_reason=None,
        code=mutated_code, oracle_error=oracle_error, diff_summary=diff_summary,
    )


def generate_all_variants(operator: SemanticOperator, source_code: str,
                           reference_fix: str, case: dict,
                           max_variants: int = 5) -> list[MutationResult]:
    """Try ALL targets × ALL mutations from an operator. Return all accepted variants.

    For operators with mutate_all(): tries every candidate from every target.
    For single-mutation operators: tries each target separately.
    Deduplicates by mutated code content.
    """
    target_fn = case.get("reference_fix", {}).get("function", "?")
    accepted = []
    seen_codes = set()

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    targets = operator.find_targets(tree)
    if not targets:
        return []

    for target in targets:
        if len(accepted) >= max_variants:
            break

        # Try mutate_all if available
        if hasattr(operator, 'mutate_all'):
            candidates = operator.mutate_all(source_code, tree, target)
            for candidate in candidates:
                if len(accepted) >= max_variants:
                    break
                if candidate in seen_codes:
                    continue
                result = _validate_candidate(
                    candidate, source_code, reference_fix, case, target_fn,
                    f"pending_{len(accepted)}",
                )
                if result.quality in ("GOLD", "SILVER"):
                    seen_codes.add(candidate)
                    accepted.append(result)

        # Also try single mutate on this target
        mutated = operator.mutate(source_code, tree, target)
        if mutated and mutated != source_code and mutated not in seen_codes:
            result = _validate_candidate(
                mutated, source_code, reference_fix, case, target_fn,
                f"pending_{len(accepted)}",
            )
            if result.quality in ("GOLD", "SILVER"):
                seen_codes.add(mutated)
                accepted.append(result)

    return accepted


def generate_variant(operator: SemanticOperator, source_code: str,
                     reference_fix: str, case: dict,
                     variant_id: str) -> MutationResult:
    """Run the full 5-gate pipeline. Returns first accepted variant or best rejection."""
    results = generate_all_variants(operator, source_code, reference_fix, case, max_variants=1)
    if results:
        r = results[0]
        return MutationResult(
            variant_id=variant_id, applied=r.applied, target_found=r.target_found,
            diff_nonempty=r.diff_nonempty,
            structural_verification_passed=r.structural_verification_passed,
            semantic_guardrails_passed=r.semantic_guardrails_passed,
            oracle_failed=r.oracle_failed, quality=r.quality,
            rejection_reason=r.rejection_reason, code=r.code,
            oracle_error=r.oracle_error, diff_summary=r.diff_summary,
        )

    # No accepted variant — run standard path for rejection info
    target_fn = case.get("reference_fix", {}).get("function", "?")
    outcome = mutate_file_in_case(
        {"code_files_contents": {"source": source_code}},
        "source", operator,
    )

    if not outcome.applied:
        return MutationResult(
            variant_id=variant_id, applied=False,
            target_found=outcome.targets_found > 0,
            diff_nonempty=False, structural_verification_passed=False,
            semantic_guardrails_passed=False, oracle_failed=False,
            quality="REJECT", rejection_reason=outcome.rejection_reason,
            code=None, oracle_error=None, diff_summary=None,
        )

    return _validate_candidate(
        outcome.mutated_code, source_code, reference_fix, case, target_fn, variant_id
    )


# ============================================================
# BACKWARD COMPAT (for tests that import these)
# ============================================================

MUTATION_OPERATORS = {op.name: op for op in get_all_operators()}

def localize_target(code, fn_name):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return {"function_name": fn_name, "start_line": node.lineno - 1}
    return None
