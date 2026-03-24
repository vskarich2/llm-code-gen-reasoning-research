#!/usr/bin/env python
"""Extract model responses from a run's response log.

Usage:
    python scripts/extract_responses.py <responses_jsonl> [--case <case_id>] [--code-only]

Examples:
    python scripts/extract_responses.py logs/gpt-4o-mini_20260323_151334_responses.jsonl
    python scripts/extract_responses.py logs/gpt-4o-mini_20260323_151334_responses.jsonl --case alias_trivial
    python scripts/extract_responses.py logs/gpt-4o-mini_20260323_151334_responses.jsonl --case alias_trivial --code-only
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Extract responses from T3 logs")
    parser.add_argument("log_file", help="Path to _responses.jsonl file")
    parser.add_argument("--case", help="Filter to specific case_id")
    parser.add_argument("--code-only", action="store_true", help="Print only the code field")
    args = parser.parse_args()

    with open(args.log_file) as f:
        for i, line in enumerate(f, 1):
            entry = json.loads(line)
            cid = entry.get("case_id", "unknown")
            if args.case and cid != args.case:
                continue

            raw = entry.get("raw_response", "")
            if args.code_only:
                try:
                    parsed = json.loads(raw)
                    code = parsed.get("code", "")
                    print(f"--- L{i}: {cid} ---")
                    print(code)
                except (json.JSONDecodeError, TypeError):
                    print(f"--- L{i}: {cid} (unparseable) ---")
                    print(raw[:500])
            else:
                print(f"--- L{i}: {cid} ---")
                print(raw[:3000])
            print()


if __name__ == "__main__":
    main()
