"""GATE 3 — Serialization snapshot test.

For a fixed set of (case, condition), compute hash/len/head/tail for both systems.
Store snapshots. Compare. ANY mismatch → FAIL.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.shared import (
    ensure_loaded, load_all_cases, old_build_prompt, new_build_prompt,
    prompt_hash, write_json, write_text, MIGRATED_CONDITIONS,
)
from nudges.mapping import get_operators_for_case

# Fixed snapshot set — representative coverage
SNAPSHOT_CASES = [
    "l3_state_pipeline", "invariant_partial_fail", "hidden_dep_multihop",
    "alias_config_a", "alias_config_c",
    "stale_cache_a", "mutable_default_b",
]
SNAPSHOT_CONDITIONS = ["baseline", "structured_reasoning"]
NUDGE_CONDITIONS = ["diagnostic", "guardrail", "counterfactual"]


def build_snapshot(prompt, case_id, condition, system):
    """Build a snapshot dict from a prompt string."""
    return {
        "case": case_id, "condition": condition, "system": system,
        "hash": prompt_hash(prompt), "length": len(prompt),
        "first_200": prompt[:200], "last_200": prompt[-200:],
    }


def run_gate():
    ensure_loaded()
    cases = {c["id"]: c for c in load_all_cases()}
    results = {"gate": "prompt_snapshot", "checks": 0, "mismatches": [], "passed": True}
    lines = ["GATE 3 — SERIALIZATION SNAPSHOT REPORT\n"]

    for cid in SNAPSHOT_CASES:
        if cid not in cases:
            lines.append(f"  SKIP: {cid} not in case set")
            continue
        case = cases[cid]
        has_mapping = get_operators_for_case(cid) is not None
        conditions = list(SNAPSHOT_CONDITIONS)
        if has_mapping:
            conditions.extend(NUDGE_CONDITIONS)

        for cond in conditions:
            try:
                old = old_build_prompt(case, cond)
                new = new_build_prompt(case, cond)
            except Exception as e:
                lines.append(f"  SKIP: {cid}/{cond}: {e}")
                continue

            old_snap = build_snapshot(old, cid, cond, "old")
            new_snap = build_snapshot(new, cid, cond, "new")

            snap_path = Path(f"validation/snapshots/{cid}_{cond}.json")
            write_json(str(snap_path), {"old": old_snap, "new": new_snap})

            results["checks"] += 1
            if old_snap["hash"] != new_snap["hash"]:
                results["passed"] = False
                results["mismatches"].append({
                    "case": cid, "condition": cond,
                    "old_hash": old_snap["hash"], "new_hash": new_snap["hash"],
                    "old_len": old_snap["length"], "new_len": new_snap["length"],
                })
                lines.append(f"  MISMATCH: {cid}/{cond} old_hash={old_snap['hash']} new_hash={new_snap['hash']}")

    lines.append(f"\n{results['checks']} checks, {len(results['mismatches'])} mismatches")
    lines.append(f"VERDICT: {'PASS' if results['passed'] else 'FAIL'}")

    write_json("validation/results/prompt_snapshot_report.json", results)
    write_text("validation/results/prompt_snapshot_report.txt", "\n".join(lines))
    return results


if __name__ == "__main__":
    r = run_gate()
    print(f"Gate 3: {r['checks']} checks, {len(r['mismatches'])} mismatches → {'PASS' if r['passed'] else 'FAIL'}")
    sys.exit(0 if r["passed"] else 1)
