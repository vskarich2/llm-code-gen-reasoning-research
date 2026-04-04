#!/usr/bin/env python
"""Test a code string against a case's invariant function.

Usage:
    python scripts/test_invariant.py <test_name> <code_file>
    python scripts/test_invariant.py <test_name> --inline 'code here'

Examples:
    python scripts/test_invariant.py alias_mutation_shadow scripts/fixtures/alias_correct.py
    python scripts/test_invariant.py retry_ack_duplication scripts/fixtures/retry_correct.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pipeline import _CASE_TESTS, load_module_from_code
from core.pipeline import assemble_code


def main():
    parser = argparse.ArgumentParser(description="Test code against a T3 invariant")
    parser.add_argument("test_name", help="Key in _CASE_TESTS (e.g. alias_mutation_shadow)")
    parser.add_argument("code_file", nargs="?", help="Path to .py file with code to test")
    parser.add_argument("--inline", help="Inline code string to test")
    parser.add_argument("--case-id", help="Case ID for assembly context (uses cases_v2.json)")
    args = parser.parse_args()

    if args.test_name not in _CASE_TESTS:
        print(f"Unknown test: {args.test_name}")
        print(f"Available: {', '.join(sorted(_CASE_TESTS.keys()))}")
        sys.exit(1)

    if args.inline:
        code = args.inline
    elif args.code_file:
        code = Path(args.code_file).read_text()
    else:
        print("Provide either a code_file or --inline")
        sys.exit(1)

    # Build case context for assembly
    import json
    cases = json.loads((Path(__file__).resolve().parents[1] / "cases_v2.json").read_text())
    case = None
    if args.case_id:
        case = next((c for c in cases if c["id"] == args.case_id), None)
    if case is None:
        # Try to match test_name to a case
        case = next((c for c in cases if c["id"] == args.test_name), None)
    if case is None:
        # Minimal case — single file, no assembly needed
        case = {"code_files": [], "code_files_contents": {}, "failure_mode": "TEST", "reference_fix": {}}

    # Assemble through canonical path
    asm = assemble_code(code, case)
    if asm.status != "SUCCESS":
        print(f"ASSEMBLY ERROR: {asm.errors}")
        sys.exit(1)

    try:
        mod = load_module_from_code(asm.code, "test_mod")
    except Exception as e:
        print(f"LOAD ERROR: {e}")
        sys.exit(1)

    test_fn = _CASE_TESTS[args.test_name]
    passed, reasons = test_fn(mod)
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {reasons}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
