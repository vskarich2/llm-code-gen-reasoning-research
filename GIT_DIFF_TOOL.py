#!/usr/bin/env python3
"""Dump git diff between HEAD and HEAD~1 for Python files only.

Default: copies diff to clipboard via pbcopy.
With -o/--output: writes to specified file instead.

Usage:
    python scripts/git_diff_py.py           # → clipboard
    python scripts/git_diff_py.py -o out.diff  # → file
"""

import argparse
import subprocess
import sys


def get_commit_hash(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git diff HEAD~1..HEAD for Python files only.",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Write diff to this file instead of clipboard.",
    )
    args = parser.parse_args()

    head = get_commit_hash("HEAD")
    parent = get_commit_hash("HEAD~1")

    result = subprocess.run(
        ["git", "diff", parent, head, "--", "*.py", "*.yaml", "*.yml", "*.json", "*.j2"],
        capture_output=True, text=True, check=True,
    )

    diff = result.stdout
    lines = diff.count("\n")

    if args.output:
        with open(args.output, "w") as f:
            f.write(diff)
        print(f"{parent[:12]}..{head[:12]} → {args.output} ({lines} lines)")
    else:
        subprocess.run(
            ["pbcopy"], input=diff, text=True, check=True,
        )
        print(f"{parent[:12]}..{head[:12]} → clipboard ({lines} lines)")


if __name__ == "__main__":
    main()
