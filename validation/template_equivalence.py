"""GATE 2 — Template-level equivalence across A→C cases within same family.

For each case family, compare old vs new prompts for difficulty A and C.
ANY string mismatch → FAIL immediately.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.shared import (
    ensure_loaded, load_all_cases, old_build_prompt, new_build_prompt,
    prompt_hash, write_json, write_text, MIGRATED_CONDITIONS,
)
from nudges.mapping import get_operators_for_case


def get_family(case_id):
    """Extract family from case ID (strip _a, _b, _c suffix)."""
    for suffix in ("_a", "_b", "_c"):
        if case_id.endswith(suffix):
            return case_id[: -len(suffix)]
    return case_id


def select_family_pairs(cases):
    """Select A and C cases per family (where both exist)."""
    families = defaultdict(dict)
    for c in cases:
        fam = get_family(c["id"])
        if c["id"].endswith("_a"):
            families[fam]["a"] = c
        elif c["id"].endswith("_c"):
            families[fam]["c"] = c
    return {f: pair for f, pair in families.items() if "a" in pair and "c" in pair}


def run_gate():
    ensure_loaded()
    cases = load_all_cases()
    pairs = select_family_pairs(cases)
    mapped_ids = {c["id"] for c in cases if get_operators_for_case(c["id"])}

    results = {"gate": "template_equivalence", "families": len(pairs), "checks": 0,
               "mismatches": [], "passed": True}
    lines = ["GATE 2 — TEMPLATE EQUIVALENCE REPORT\n"]

    for fam, pair in sorted(pairs.items()):
        for diff_key in ("a", "c"):
            case = pair[diff_key]
            has_mapping = case["id"] in mapped_ids
            conditions = MIGRATED_CONDITIONS if has_mapping else ["baseline", "structured_reasoning"]

            for cond in conditions:
                if cond in ("diagnostic", "guardrail", "guardrail_strict", "repair_loop"):
                    if not has_mapping:
                        continue
                try:
                    old = old_build_prompt(case, cond)
                    new = new_build_prompt(case, cond)
                except Exception as e:
                    lines.append(f"  SKIP: {case['id']}/{cond}: {e}")
                    continue

                results["checks"] += 1
                if old != new:
                    results["passed"] = False
                    diff_idx = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), len(min(old, new)))
                    results["mismatches"].append({
                        "case": case["id"], "condition": cond,
                        "old_len": len(old), "new_len": len(new), "diff_at": diff_idx,
                    })
                    lines.append(f"  MISMATCH: {case['id']}/{cond} old={len(old)} new={len(new)} diff@{diff_idx}")

    lines.append(f"\n{results['checks']} checks, {len(results['mismatches'])} mismatches")
    lines.append(f"VERDICT: {'PASS' if results['passed'] else 'FAIL'}")

    write_json("validation/results/template_equivalence_report.json", results)
    write_text("validation/results/template_equivalence_report.txt", "\n".join(lines))
    return results


if __name__ == "__main__":
    r = run_gate()
    print(f"Gate 2: {r['checks']} checks, {len(r['mismatches'])} mismatches → {'PASS' if r['passed'] else 'FAIL'}")
    sys.exit(0 if r["passed"] else 1)
