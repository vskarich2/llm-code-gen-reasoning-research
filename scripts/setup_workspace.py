#!/usr/bin/env python3
"""Set up case_testing_gym/ with editable copies of benchmark cases.

Usage:
    .venv/bin/python scripts/setup_workspace.py                # all cases
    .venv/bin/python scripts/setup_workspace.py async_race_lock stale_config_reload  # specific cases
"""

import json
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CASES_FILE = PROJECT / "cases_v2.json"
WORKSPACE = PROJECT / "case_testing_gym"


def setup_case(case_entry):
    case_id = case_entry["id"]
    dest = WORKSPACE / case_id
    dest.mkdir(parents=True, exist_ok=True)

    # Copy buggy code files
    for rel_path in case_entry["code_files"]:
        src = PROJECT / rel_path
        if not src.exists():
            print(f"  WARNING: {rel_path} not found, skipping")
            continue
        shutil.copy2(src, dest / src.name)

    # Write TASK.txt
    task = case_entry.get("task", "")
    family = case_entry.get("family", "")
    difficulty = case_entry.get("difficulty", "")
    description = case_entry.get("description", "")

    task_text = (
        f"case_id: {case_id}\n"
        f"family: {family}\n"
        f"difficulty: {difficulty}\n"
        f"\n"
        f"--- DESCRIPTION ---\n"
        f"{description}\n"
        f"\n"
        f"--- TASK ---\n"
        f"{task}\n"
    )
    (dest / "TASK.txt").write_text(task_text)

    n_files = len(case_entry["code_files"])
    print(f"  {case_id:<35} {n_files} files")


def main():
    with open(CASES_FILE) as f:
        cases = json.load(f)

    # Filter to requested cases or all
    if len(sys.argv) > 1:
        requested = set(sys.argv[1:])
        targets = [c for c in cases if c["id"] in requested]
        missing = requested - {c["id"] for c in targets}
        if missing:
            print(f"Not found: {missing}")
            sys.exit(1)
    else:
        targets = cases

    WORKSPACE.mkdir(exist_ok=True)

    # Write .gitignore
    gitignore = WORKSPACE / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# Workspace copies — do not commit\n*\n")

    print(f"Setting up {len(targets)} cases in case_testing_gym/\n")
    for case in targets:
        setup_case(case)

    print(f"\nDone. Edit files in case_testing_gym/<case_id>/, then test with:")
    print(f"  .venv/bin/python scripts/test_case.py --dir case_testing_gym/<case_id>")


if __name__ == "__main__":
    main()
