#!/usr/bin/env python
"""Generate buggy variants using AST-level semantic mutation operators.

Every accepted variant passes all gates:
1. Semantic target found
2. AST mutation applied
3. Diff verified
4. Semantic guardrails passed
5. Oracle fails

Usage:
    .venv/bin/python scripts/generate_buggy_variants_v2.py
    .venv/bin/python scripts/generate_buggy_variants_v2.py --family alias_config
"""

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = Path(__file__).resolve().parents[1]

from scripts.mutation_engine import generate_variant, generate_all_variants, MutationResult
from scripts.ast_mutator import get_operators_for_family, get_all_operators
from validate_cases_v2 import load_reference_code


def _load_all_cases():
    cases = json.loads((BASE / "cases_v2.json").read_text())
    for case in cases:
        case["code_files_contents"] = {}
        for rel in case["code_files"]:
            case["code_files_contents"][rel] = (BASE / rel).read_text()
    return cases


def _get_source_variants(case: dict) -> list[str]:
    """Get multiple source code variants to try mutation on.

    Returns: [merged_reference_fix, per-file fixes merged with other originals]
    This handles cases where the reference fix file is different from what metadata says.
    """
    from validate_cases_v2 import load_reference_code as _load_ref
    sources = []

    # Strategy 1: standard merged reference fix
    merged = _load_ref(case)
    if merged:
        sources.append(merged)

    # Strategy 2: try each reference fix file merged with the OTHER original files
    ref_path = Path(BASE / "reference_fixes" / f"{case['id']}.py")
    if ref_path.exists():
        raw_fix = ref_path.read_text()
        bug_file = case.get("reference_fix", {}).get("file", "")

        # For each code file, try using raw_fix as that file + originals for others
        for code_file in case["code_files"]:
            other_parts = []
            for rel in case["code_files"]:
                if rel == code_file:
                    continue
                content = case.get("code_files_contents", {}).get(rel, "")
                if content:
                    other_parts.append(content)

            combined = "\n\n".join(other_parts + [raw_fix]) if other_parts else raw_fix
            if combined not in sources:
                sources.append(combined)

    return sources


def generate_for_case(case: dict, target_count: int = 5) -> list[MutationResult]:
    """Generate up to target_count accepted variants for a case."""
    cid = case["id"]
    family = case["family"]

    source_variants = _get_source_variants(case)
    if not source_variants:
        return []

    family_ops = get_operators_for_family(family)
    all_ops = get_all_operators()
    ordered_ops = family_ops + [op for op in all_ops if op not in family_ops]

    accepted = []
    seen_operators = set()

    for operator in ordered_ops:
        if len(accepted) >= target_count:
            break
        if operator.name in seen_operators:
            continue
        seen_operators.add(operator.name)

        # Try each source variant, collecting ALL accepted from this operator
        for source_code in source_variants:
            if len(accepted) >= target_count:
                break

            new_variants = generate_all_variants(
                operator, source_code, source_variants[0], case,
                max_variants=target_count - len(accepted),
            )

            for r in new_variants:
                if len(accepted) >= target_count:
                    break
                # Check dedup against already-accepted code
                if r.code and any(a.code == r.code for a in accepted):
                    continue
                accepted.append(MutationResult(
                    variant_id=f"{cid}_v{len(accepted)+1}",
                    applied=r.applied, target_found=r.target_found,
                    diff_nonempty=r.diff_nonempty,
                    structural_verification_passed=r.structural_verification_passed,
                    semantic_guardrails_passed=r.semantic_guardrails_passed,
                    oracle_failed=r.oracle_failed, quality=r.quality,
                    rejection_reason=r.rejection_reason, code=r.code,
                    oracle_error=r.oracle_error, diff_summary=r.diff_summary,
                ))

            if new_variants:
                break  # got results from this source, move to next operator

    return accepted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default=None)
    parser.add_argument("--target", type=int, default=5)
    args = parser.parse_args()

    cases = _load_all_cases()
    if args.family:
        cases = [c for c in cases if c["family"] == args.family]

    all_results = {}
    total_accepted = 0
    total_gold = 0
    total_silver = 0
    cases_with_zero = []

    for case in cases:
        cid = case["id"]
        accepted = generate_for_case(case, target_count=args.target)

        gold = sum(1 for r in accepted if r.quality == "GOLD")
        silver = sum(1 for r in accepted if r.quality == "SILVER")
        total_accepted += len(accepted)
        total_gold += gold
        total_silver += silver

        if not accepted:
            cases_with_zero.append(cid)

        all_results[cid] = {
            "accepted": len(accepted),
            "gold": gold,
            "silver": silver,
            "variants": [
                {
                    "variant_id": r.variant_id,
                    "quality": r.quality,
                    "oracle_error": r.oracle_error,
                    "diff_summary": r.diff_summary[:200] if r.diff_summary else None,
                    "code": r.code,
                }
                for r in accepted
            ],
        }

        quality_str = f"({gold}G {silver}S)" if accepted else "(0)"
        print(f"{cid:30s}: {len(accepted)}/{args.target} accepted {quality_str}")

    print()
    print(f"{'=' * 50}")
    print(f"TOTAL: {total_accepted} accepted ({total_gold} GOLD, {total_silver} SILVER)")
    print(f"Cases with variants: {len(cases) - len(cases_with_zero)}/{len(cases)}")
    if cases_with_zero:
        print(f"Cases with ZERO variants ({len(cases_with_zero)}):")
        for cid in cases_with_zero[:15]:
            print(f"  {cid}")
        if len(cases_with_zero) > 15:
            print(f"  ... and {len(cases_with_zero) - 15} more")

    output_path = BASE / "validation" / "accepted_buggy_variants.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nWritten to {output_path}")


if __name__ == "__main__":
    main()
