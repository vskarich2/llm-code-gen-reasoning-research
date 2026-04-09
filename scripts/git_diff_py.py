#!/usr/bin/env python3
"""Dump git diff between HEAD and HEAD~1 for Python files only.

Usage:
    python scripts/git_diff_py.py output.diff
"""

import subprocess
import sys


def get_commit_hash(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output_file>", file=sys.stderr)
        sys.exit(1)

    output_path = sys.argv[1]
    head = get_commit_hash("HEAD")
    parent = get_commit_hash("HEAD~1")

    result = subprocess.run(
        ["git", "diff", parent, head, "--", "*.py"],
        capture_output=True, text=True, check=True,
    )

    with open(output_path, "w") as f:
        f.write(result.stdout)

    lines = result.stdout.count("\n")
    print(f"{parent[:12]}..{head[:12]} → {output_path} ({lines} lines)")


if __name__ == "__main__":
    main()
