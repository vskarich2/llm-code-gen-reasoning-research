#!/usr/bin/env python
"""Extract failure reasons and scores from a run's metadata log.

Usage:
    python scripts/extract_metadata.py <metadata_jsonl> [--case <case_id>] [--failures-only]

Examples:
    python scripts/extract_metadata.py logs/gpt-4o-mini_20260323_151334.jsonl
    python scripts/extract_metadata.py logs/gpt-4o-mini_20260323_151334.jsonl --failures-only
    python scripts/extract_metadata.py logs/gpt-4o-mini_20260323_151334.jsonl --case alias_trivial
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Extract metadata from T3 logs")
    parser.add_argument("log_file", help="Path to metadata .jsonl file")
    parser.add_argument("--case", help="Filter to specific case_id")
    parser.add_argument("--failures-only", action="store_true", help="Only show failures")
    args = parser.parse_args()

    with open(args.log_file) as f:
        for i, line in enumerate(f, 1):
            entry = json.loads(line)
            cid = entry["case_id"]
            if args.case and cid != args.case:
                continue

            ev = entry.get("evaluation", {})
            ex = entry.get("execution", {})
            passed = ev.get("pass", False)

            if args.failures_only and passed:
                continue

            score = ev.get("score", 0)
            gap = ev.get("reasoning_action_gap", False)
            inv = ex.get("invariant_pass")
            syn = ex.get("syntax_error")
            ran = ex.get("ran")

            status = "PASS" if passed else "FAIL"
            gap_mark = " GAP" if gap else ""
            print(
                f"L{i:2d} {cid:<32} {status} score={score:.1f} inv={inv} ran={ran} syn={bool(syn)}{gap_mark}"
            )

            if not passed:
                err = ex.get("error_message") or ex.get("syntax_error")
                if err:
                    print(f"     error: {str(err)[:120]}")


if __name__ == "__main__":
    main()
