#!/usr/bin/env python
"""Migrate existing call logs to the new calls_flat/ per-file format.

For every calls/ directory found under logs/:
1. Read each JSON call file
2. Write corresponding flat text file to calls_flat/
3. Delete calls_flat.txt (the legacy concatenated dump)
4. Verify 1:1 count

Idempotent: skips directories already converted.

Usage:
    .venv/bin/python scripts/migrate_call_logs.py
    .venv/bin/python scripts/migrate_call_logs.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logging_core import render_call_flat


def migrate_run_dir(run_dir: Path, dry_run: bool = False) -> dict:
    """Migrate one run directory. Returns stats."""
    calls_dir = run_dir / "calls"
    flat_dir = run_dir / "calls_flat"
    legacy_flat = run_dir / "calls_flat.txt"

    if not calls_dir.exists():
        return {"status": "skip", "reason": "no calls/ directory"}

    json_files = sorted(calls_dir.glob("*.json"))
    if not json_files:
        return {"status": "skip", "reason": "no JSON files in calls/"}

    # Check if already migrated
    if flat_dir.exists():
        existing_flat = len(list(flat_dir.glob("*.txt")))
        if existing_flat == len(json_files):
            return {"status": "skip", "reason": f"already migrated ({existing_flat} files)"}

    if dry_run:
        return {"status": "would_migrate", "json_count": len(json_files)}

    # Create calls_flat/
    flat_dir.mkdir(exist_ok=True)

    converted = 0
    errors = []
    for json_path in json_files:
        try:
            record = json.loads(json_path.read_text(encoding="utf-8"))
            phase = record.get("phase", "unknown")
            call_id = record.get("call_id", 0)
            flat_name = f"{call_id:06d}_{phase}.txt"
            flat_path = flat_dir / flat_name
            flat_path.write_text(render_call_flat(record), encoding="utf-8")
            converted += 1
        except Exception as e:
            errors.append(f"{json_path.name}: {e}")

    # Delete legacy flat file
    if legacy_flat.exists():
        legacy_flat.unlink()

    # Verify 1:1
    final_flat_count = len(list(flat_dir.glob("*.txt")))
    if final_flat_count != len(json_files):
        errors.append(f"count mismatch: {len(json_files)} JSON vs {final_flat_count} flat")

    return {
        "status": "migrated",
        "converted": converted,
        "json_count": len(json_files),
        "errors": errors,
        "legacy_deleted": not legacy_flat.exists(),
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate call logs to per-file flat format")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", default="logs/", help="Root path to scan")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"Path not found: {root}")
        return

    # Find all directories containing calls/
    run_dirs = set()
    for calls_dir in root.rglob("calls"):
        if calls_dir.is_dir() and any(calls_dir.glob("*.json")):
            run_dirs.add(calls_dir.parent)

    print(f"Found {len(run_dirs)} run directories with call logs")

    migrated = 0
    skipped = 0
    failed = 0

    for run_dir in sorted(run_dirs):
        result = migrate_run_dir(run_dir, dry_run=args.dry_run)
        status = result["status"]

        if status == "migrated":
            migrated += 1
            errs = result.get("errors", [])
            if errs:
                print(f"  {run_dir}: MIGRATED with {len(errs)} errors")
                for e in errs:
                    print(f"    {e}")
            else:
                print(f"  {run_dir}: MIGRATED ({result['converted']} files)")
        elif status == "skip":
            skipped += 1
        elif status == "would_migrate":
            print(f"  {run_dir}: WOULD MIGRATE ({result['json_count']} files)")
        else:
            failed += 1
            print(f"  {run_dir}: FAILED: {result}")

    print(f"\nDone: {migrated} migrated, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
