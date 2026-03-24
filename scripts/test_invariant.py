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
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exec_eval import _CASE_TESTS


def main():
    parser = argparse.ArgumentParser(description="Test code against a T3 invariant")
    parser.add_argument("test_name", help="Key in _CASE_TESTS (e.g. alias_mutation_shadow)")
    parser.add_argument("code_file", nargs="?", help="Path to .py file with code to test")
    parser.add_argument("--inline", help="Inline code string to test")
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

    mod = types.ModuleType("test_mod")
    try:
        exec(code, mod.__dict__)
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
