"""Extraction correctness reasoning_evaluator_audit script for Fix C validation.

Compares extracted E1 (root_cause) against manually annotated E1
for locked reasoning_evaluator_audit cases. Required for Go/No-Go item 13.

Usage:
    python scripts/extraction_correctness_audit.py --annotations reasoning_evaluator_audit/e1_annotations.json

annotations JSON format:
[
    {"case_id": "...", "annotated_e1": "...", "extracted_e1": "...", "match": "MATCH|PARTIAL|MISMATCH"}
]

Exits 0 if >= 8/10 MATCH or PARTIAL. Exits 1 otherwise.
"""

import argparse
import json
import sys
from pathlib import Path


def audit(annotations_path: str):
    data = json.load(open(annotations_path))
    total = len(data)

    if total < 10:
        print(f"FAIL: Need at least 10 annotations, got {total}")
        return False

    matches = sum(1 for d in data if d["match"] in ("MATCH", "PARTIAL"))
    mismatches = [d for d in data if d["match"] == "MISMATCH"]

    print(f"Extraction Correctness Audit: {total} cases")
    print(f"  MATCH/PARTIAL: {matches}/{total}")
    print(f"  MISMATCH: {len(mismatches)}/{total}")

    if mismatches:
        print("\n  Mismatches:")
        for d in mismatches:
            print(
                f"    {d['case_id']}: annotated={d['annotated_e1']!r}, extracted={d['extracted_e1']!r}"
            )

    threshold = 8
    passed = matches >= threshold
    print(f"\n  Threshold: >= {threshold}/{total} MATCH/PARTIAL")
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", required=True)
    args = parser.parse_args()

    if not Path(args.annotations).exists():
        print(f"Annotations file not found: {args.annotations}")
        print("This script validates extraction correctness. Create annotations first.")
        sys.exit(1)

    passed = audit(args.annotations)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
