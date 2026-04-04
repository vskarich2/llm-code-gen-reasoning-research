#!/usr/bin/env python
"""Generate 5 buggy variants per case and validate against the oracle.

For each of 58 cases:
1. Read the buggy code (original) and reference fix
2. Generate 5 distinct buggy variants based on the family pattern
3. Run each through exec_evaluate to verify it FAILS the test
4. Output to validation/all_buggy_variants.json

Each variant must: compile, run, but FAIL the invariant test.

Usage:
    .venv/bin/python scripts/generate_buggy_variants.py
    .venv/bin/python scripts/generate_buggy_variants.py --family alias_config
    .venv/bin/python scripts/generate_buggy_variants.py --validate-only
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = Path(__file__).resolve().parents[1]

from core.pipeline import exec_evaluate
from core.pipeline.orchestration import load_case_code, load_reference_code


def _load_all_cases():
    cases = json.loads((BASE / "cases_v2.json").read_text())
    for case in cases:
        case["code_files_contents"] = {}
        for rel in case["code_files"]:
            case["code_files_contents"][rel] = (BASE / rel).read_text()
    return cases


# ============================================================
# MUTATION STRATEGIES PER FAMILY
# ============================================================

def _mutate_alias(buggy_code, ref_code, case, idx):
    """Aliasing family: create_config must return independent dict.

    Test checks: create({"timeout": 5}) then create() — cfg2.timeout must be 30.
    So we need variants where the first call's overrides leak into subsequent calls.
    """
    if idx == 0:
        # V1: Original bug — direct reference
        return buggy_code
    if idx == 1:
        # V2: Assign to DEFAULTS directly (mutation corrupts global)
        return ref_code.replace(
            "config = DEFAULTS.copy()",
            "config = DEFAULTS"
        )
    if idx == 2:
        # V3: Copy but update DEFAULTS too (double write)
        return ref_code.replace(
            "    config = DEFAULTS.copy()",
            "    config = DEFAULTS.copy()\n    DEFAULTS.update(overrides or {})"
        )
    if idx == 3:
        # V4: Use global DEFAULTS as backing store (cache pattern)
        return ref_code.replace(
            "    config = DEFAULTS.copy()\n    if overrides:\n        config.update(overrides)\n    return config",
            "    if overrides:\n        DEFAULTS.update(overrides)\n    return DEFAULTS"
        )
    if idx == 4:
        # V5: Return a view that shares the underlying case_data
        return ref_code.replace(
            "config = DEFAULTS.copy()",
            "config = DEFAULTS  # intentional: return reference for performance"
        )
    return buggy_code


def _mutate_mutable_default(buggy_code, ref_code, case, idx):
    """Mutable default: no state shared across calls."""
    strategies = [
        # V1: Original mutable default
        lambda c: c,
        # V2: Use list() as default but assign to module-level
        lambda c: re.sub(
            r"def enqueue\(task, queue=None\):",
            "def enqueue(task, queue=_SHARED):",
            c.replace("if queue is None:", "# removed None check").replace(
                "        queue = []", "")
        ).replace("_SHARED", "[]") if "queue=None" in c else c,
        # V3: Use None but forget to create new list
        lambda c: c.replace("queue = []", "pass  # forgot to initialize"),
        # V4: Create new list but also append to module-level
        lambda c: c.replace(
            "if queue is None:\n        queue = []",
            "if queue is None:\n        queue = []\n    _history.append(task)"
        ) if "queue is None" in c else c,
        # V5: set() instead of list for default (wrong type)
        lambda c: c.replace("queue=None", "queue=set()").replace(
            "queue = []", "queue = set()"
        ).replace("queue.append(task)", "queue.add(task)") if "queue=None" in c else c,
    ]
    if idx < len(strategies):
        return strategies[idx](ref_code if idx > 0 else buggy_code)
    return buggy_code


def _mutate_stale_cache(buggy_code, ref_code, case, idx):
    """Stale cache: reads must reflect latest writes."""
    strategies = [
        # V1: No invalidation (original bug)
        lambda c: c,
        # V2: Invalidate wrong key
        lambda c: c.replace(
            "_cache.pop(product_id, None)",
            "_cache.pop('wrong_key', None)"
        ) if "_cache.pop" in c else c,
        # V3: Clear entire cache (over-invalidation works but let's invalidate BEFORE write)
        lambda c: c.replace(
            "_cache.pop(product_id, None)",
            "pass  # invalidation removed"
        ) if "_cache.pop" in c else c,
        # V4: Invalidate but then re-cache stale case_data
        lambda c: c.replace(
            "_cache.pop(product_id, None)",
            "_cache[product_id] = dict(_db.get(product_id, {}))"  # re-caches BEFORE update
        ).replace(
            "_db[product_id].update(fields)\n    _cache[product_id]",
            "_cache[product_id] = dict(_db.get(product_id, {}))\n    _db[product_id].update(fields)"
        ) if "_cache.pop" in c else c,
        # V5: Only invalidate for specific fields
        lambda c: c.replace(
            "_cache.pop(product_id, None)",
            "if 'price' in fields:\n        _cache.pop(product_id, None)  # only invalidate for price changes"
        ) if "_cache.pop" in c else c,
    ]
    if idx < len(strategies):
        result = strategies[idx](ref_code if idx > 0 else buggy_code)
        return result
    return buggy_code


def _mutate_partial_update(buggy_code, ref_code, case, idx):
    """Partial update: all dependent fields must update."""
    strategies = [
        # V1: Original bug — no display_name sync
        lambda c: c,
        # V2: Sync display_name but to wrong value
        lambda c: c.replace(
            'user["display_name"] = value',
            'user["display_name"] = "display_" + value'
        ) if 'user["display_name"] = value' in c else c,
        # V3: Sync only for non-empty names
        lambda c: c.replace(
            'user["display_name"] = value',
            'if value:\n                user["display_name"] = value'
        ) if 'user["display_name"] = value' in c else c,
        # V4: Set display_name to old name value
        lambda c: c.replace(
            '            user["name"] = value\n            user["display_name"] = value',
            '            old = user.get("name", "")\n            user["name"] = value\n            user["display_name"] = old'
        ) if 'user["display_name"] = value' in c else c,
        # V5: Remove the sync line entirely
        lambda c: c.replace(
            '            user["display_name"] = value  # FIX: sync display_name with name\n',
            ''
        ),
    ]
    if idx < len(strategies):
        return strategies[idx](ref_code if idx > 0 else buggy_code)
    return buggy_code


def _mutate_early_return(buggy_code, ref_code, case, idx):
    """Early return: ledger must have entry for every call."""
    strategies = [
        # V1: Original bug — early return skips ledger
        lambda c: c,
        # V2: Log only non-zero amounts
        lambda c: c.replace(
            '_ledger.append({"amount": 0',
            '# _ledger.append({"amount": 0  # removed'
        ).replace(
            '        return {"status": "skipped", "amount": 0}',
            '        return {"status": "skipped", "amount": 0}'
        ) if '_ledger.append({"amount": 0' in c else c,
        # V3: Append after return (unreachable)
        lambda c: re.sub(
            r'(_ledger\.append.*?skipped.*?\n)(.*?return.*?skipped)',
            r'\2\n    \1',
            c, flags=re.DOTALL
        ) if '_ledger.append' in c and 'skipped' in c else c,
        # V4: Append to wrong list
        lambda c: c.replace("_ledger.append", "_audit.append") if "_ledger.append" in c else c,
        # V5: Conditional append that misses zero
        lambda c: c.replace(
            '_ledger.append({"amount": 0, "description": description, "status": "skipped"})',
            'if amount > 0:\n        _ledger.append({"amount": amount, "description": description, "status": "skipped"})'
        ) if '_ledger.append({"amount": 0' in c else c,
    ]
    if idx < len(strategies):
        return strategies[idx](ref_code if idx > 0 else buggy_code)
    return buggy_code


# Generic fallback — use the original buggy code + trivial variations
def _mutate_generic(buggy_code, ref_code, case, idx):
    """Generic: return original buggy code with minor cosmetic variations."""
    if idx == 0:
        return buggy_code
    # Add comments / rename variables but keep the bug
    variations = [
        buggy_code,
        buggy_code.replace("# BUG:", "# TODO:"),
        buggy_code + "\n# end of file\n",
        re.sub(r'""".*?"""', '"""Refactored."""', buggy_code, count=1, flags=re.DOTALL),
        buggy_code.replace("\n\n\n", "\n\n"),
    ]
    return variations[min(idx, len(variations) - 1)]


FAMILY_MUTATORS = {
    "alias_config": _mutate_alias,
    "mutable_default": _mutate_mutable_default,
    "stale_cache": _mutate_stale_cache,
    "partial_update": _mutate_partial_update,
    "early_return": _mutate_early_return,
}

VARIANT_LABELS = [
    ("direct_bug", "Direct invariant violation (original pattern)"),
    ("conditional_bug", "Conditional fix that misses a code path"),
    ("wrong_target", "Fix applied to wrong target / wrong value"),
    ("deceptive_fix", "Looks fixed but subtle bug remains"),
    ("scope_error", "Fix at wrong scope / unreachable fix"),
]


def generate_variants_for_case(case, buggy_code, ref_code):
    """Generate 5 buggy variants for a case."""
    family = case["family"]
    mutator = FAMILY_MUTATORS.get(family, _mutate_generic)

    variants = []
    for idx in range(5):
        code = mutator(buggy_code, ref_code, case, idx)
        label, desc = VARIANT_LABELS[idx]
        variants.append({
            "variant_id": f"{case['id']}_v{idx+1}",
            "bug_type": label,
            "description": desc,
            "code": code,
        })

    return variants


def validate_variant(case, variant_code):
    """Run variant through exec_evaluate. Returns (passed, error)."""
    try:
        result = exec_evaluate(case, variant_code)
        return result["pass"], result.get("reasons", [])
    except Exception as e:
        return None, [f"CRASH: {type(e).__name__}: {e}"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default=None)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = _load_all_cases()
    if args.family:
        cases = [c for c in cases if c["family"] == args.family]

    all_variants = {}
    total_generated = 0
    total_valid = 0  # correctly fails test
    total_invalid = 0  # incorrectly passes or crashes
    issues = []

    for case in cases:
        cid = case["id"]
        buggy_code = load_case_code(case)
        ref_code = load_reference_code(case)

        if not ref_code:
            print(f"  SKIP {cid}: no reference fix")
            continue

        variants = generate_variants_for_case(case, buggy_code, ref_code)

        case_results = []
        for v in variants:
            passed, reasons = validate_variant(case, v["code"])

            if passed is False:
                status = "VALID"  # correctly fails
                total_valid += 1
            elif passed is True:
                status = "INVALID-PASSES"  # bug not caught
                total_invalid += 1
                issues.append(f"{cid}/{v['variant_id']}: buggy variant PASSES test")
            else:
                status = "CRASH"
                total_invalid += 1
                issues.append(f"{cid}/{v['variant_id']}: CRASH: {reasons}")

            v["validation"] = {
                "status": status,
                "test_passed": passed,
                "reasons": reasons[:3] if reasons else [],
            }
            case_results.append(v)
            total_generated += 1

            if args.verbose:
                print(f"  {v['variant_id']:35s} {status}")

        valid_count = sum(1 for v in case_results if v["validation"]["status"] == "VALID")
        print(f"{cid:30s}: {valid_count}/5 variants correctly fail test")

        all_variants[cid] = {
            "buggy_variants": case_results,
            "valid_count": valid_count,
            "total": len(case_results),
        }

    # Summary
    print()
    print(f"{'=' * 50}")
    print(f"TOTAL: {total_generated} variants generated")
    print(f"  VALID (correctly fails test): {total_valid}")
    print(f"  INVALID (passes or crashes):  {total_invalid}")
    print(f"  Success rate: {total_valid/max(total_generated,1)*100:.1f}%")

    if issues:
        print(f"\nISSUES ({len(issues)}):")
        for issue in issues:
            print(f"  {issue}")

    # Write output
    output_path = BASE / "validation" / "all_buggy_variants.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_variants, f, indent=2, default=str)
    print(f"\nWritten to {output_path}")

    # Write summary
    summary = {
        "total_cases": len(all_variants),
        "total_variants": total_generated,
        "valid": total_valid,
        "invalid": total_invalid,
        "success_rate": round(total_valid / max(total_generated, 1) * 100, 1),
        "issues": issues,
        "per_case": {
            cid: {"valid": d["valid_count"], "total": d["total"]}
            for cid, d in all_variants.items()
        },
    }
    summary_path = BASE / "validation" / "buggy_variant_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
