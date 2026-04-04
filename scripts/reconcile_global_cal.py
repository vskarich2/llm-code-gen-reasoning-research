#!/usr/bin/env python3
"""Reconcile global calibration manifests after mid-run crash.

Scans disk for completed workers (those with valid events.jsonl containing
run.end), marks them SUCCEEDED in each manifest, resets stale CLAIMED/RUNNING
to PENDING, removes lock files, and merges recovered events.

Also patches the 8 config YAMLs so models run sequentially with up to
400 workers each (the machine's budget) instead of 8×200 in parallel.

Usage:
    python scripts/reconcile_global_cal.py [--dry-run]

After running this, resume each model sequentially:
    python orchestrate.py --config config_storage/global_cal_<model>.yaml \
        --resume --force-lock-recovery
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs" / "global_calibration"
CONFIGS_DIR = PROJECT_ROOT / "config_storage"

MAX_TOTAL_WORKERS = 400

# Model slug -> config filename
MODEL_CONFIGS = {
    "4omini": "global_cal_4omini.yaml",
    "54mini": "global_cal_54mini.yaml",
    "5mini": "global_cal_5mini.yaml",
    "gpt5": "global_cal_gpt5.yaml",
    "haiku45": "global_cal_haiku45.yaml",
    "nano": "global_cal_nano.yaml",
    "sonnet4": "global_cal_sonnet4.yaml",
    "sonnet46": "global_cal_sonnet46.yaml",
}

# ---------------------------------------------------------------------------
# Event parsing (mirrors orchestrate.parse_events_prefix)
# ---------------------------------------------------------------------------


def parse_events_prefix(path: Path) -> tuple[list[dict], int]:
    """Parse events.jsonl, stop at first malformed line."""
    events = []
    errors = 0
    if not path.exists():
        return events, 0
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            errors += 1
            break
    return events, errors


# ---------------------------------------------------------------------------
# Worker validation (mirrors orchestrate.validate_worker_artifacts)
# ---------------------------------------------------------------------------


def validate_worker_on_disk(
    instance_id: str, expected_cases: int, case_id: str,
    worker_dir: Path,
) -> dict:
    """Check if a worker completed successfully on disk.

    Returns dict with 'ok' bool and diagnostic fields.
    """
    events_path = worker_dir / "events.jsonl"
    if not events_path.exists():
        return {"ok": False, "reason": "events.jsonl missing"}

    events, parse_errors = parse_events_prefix(events_path)
    if not events:
        return {"ok": False, "reason": "events.jsonl empty/unparseable"}

    worker_start = False
    worker_end = False
    run_end = False
    iid_match = False
    case_terminals = {}
    passed = 0
    failed = 0
    sequences = []

    for e in events:
        et = e.get("event_type", "")
        seq = e.get("sequence")
        if seq is not None:
            sequences.append(seq)

        if et == "worker.start" or (
            et == "pipeline_state"
            and e.get("context", {}).get("step") == "run_start"
        ):
            worker_start = True
            if e.get("instance_id") == instance_id:
                iid_match = True

        if et == "run.start":
            worker_start = True
            if e.get("instance_id") == instance_id:
                iid_match = True

        if et == "worker.end":
            worker_end = True
        if et == "run.end":
            run_end = True
            worker_end = True  # backward compat

        if et in ("case.end", "execution_eval"):
            cid = (
                e.get("case_id")
                or e.get("context", {}).get("case_id")
            )
            if cid:
                case_terminals[cid] = case_terminals.get(cid, 0) + 1
                ex = e.get("execution", {})
                if ex.get("passed"):
                    passed += 1
                else:
                    failed += 1

        if et in ("case.failed", "error"):
            cid = (
                e.get("case_id")
                or e.get("context", {}).get("case_id")
            )
            if cid:
                case_terminals[cid] = case_terminals.get(cid, 0) + 1
                failed += 1

    completed = sum(1 for c in case_terminals.values() if c >= 1)
    duplicates = [cid for cid, cnt in case_terminals.items() if cnt > 1]
    missing = [case_id] if case_id not in case_terminals else []
    case_match = completed == expected_cases

    seq_contiguous = True
    if sequences:
        ss = sorted(sequences)
        for i in range(1, len(ss)):
            if ss[i] != ss[i - 1] + 1:
                seq_contiguous = False
                break

    ok = (
        worker_start
        and worker_end
        and run_end
        and case_match
        and len(duplicates) == 0
        and len(missing) == 0
        and parse_errors == 0
        and seq_contiguous
        and iid_match
    )

    reasons = []
    if not worker_start:
        reasons.append("no worker.start")
    if not worker_end:
        reasons.append("no worker.end")
    if not run_end:
        reasons.append("no run.end")
    if not case_match:
        reasons.append(f"cases {completed}/{expected_cases}")
    if duplicates:
        reasons.append(f"duplicates: {duplicates}")
    if missing:
        reasons.append(f"missing: {missing}")
    if parse_errors:
        reasons.append(f"{parse_errors} parse errors")
    if not seq_contiguous:
        reasons.append("sequence gaps")
    if not iid_match:
        reasons.append("instance_id mismatch")

    return {
        "ok": ok,
        "reason": "; ".join(reasons) if reasons else "valid",
        "passed": passed,
        "failed": failed,
        "completed_cases": completed,
    }


# ---------------------------------------------------------------------------
# Manifest reconciliation
# ---------------------------------------------------------------------------


def reconcile_model(model_slug: str, run_dir: Path, dry_run: bool) -> dict:
    """Reconcile one model's manifest from disk artifacts.

    Returns summary dict.
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {"error": f"no manifest at {manifest_path}"}

    data = json.loads(manifest_path.read_text())
    items = data["work_items"]

    # Back up original manifest
    backup_path = run_dir / "manifest.pre_reconcile.json"
    if not backup_path.exists() and not dry_run:
        shutil.copy2(manifest_path, backup_path)

    recovered = 0
    reset_to_pending = 0
    already_succeeded = 0
    already_failed = 0
    validation_failures = []
    merged_events = []

    for wid, item in items.items():
        state = item["state"]

        if state == "SUCCEEDED":
            already_succeeded += 1
            continue
        if state == "FAILED":
            already_failed += 1
            continue

        # For PENDING/CLAIMED/RUNNING/MERGING/ABORTED: check disk
        worker_dir = run_dir / item["worker_dir"]
        v = validate_worker_on_disk(
            instance_id=item["instance_id"],
            expected_cases=item["expected_cases"],
            case_id=item["case_id"],
            worker_dir=worker_dir,
        )

        if v["ok"]:
            # Worker completed on disk — mark SUCCEEDED
            now = datetime.now(timezone.utc).isoformat()
            item["state"] = "SUCCEEDED"
            item["finished_at"] = item.get("finished_at") or now
            item["merged_at"] = now
            item["completed_cases"] = v["completed_cases"]
            item["validation"] = {
                "ok": True,
                "reconciled_from_disk": True,
            }
            item["error"] = None
            recovered += 1

            # Collect events for merge
            events_path = worker_dir / "events.jsonl"
            if events_path.exists():
                evts, _ = parse_events_prefix(events_path)
                merged_events.extend(evts)
        else:
            # Worker did not complete — reset to PENDING for retry
            if state != "PENDING":
                item["state"] = "PENDING"
                item["claimed_at"] = None
                item["started_at"] = None
                item["finished_at"] = None
                item["merged_at"] = None
                item["exit_code"] = None
                item["completed_cases"] = 0
                item["validation"] = {}
                item["error"] = None
                reset_to_pending += 1
                if state in ("CLAIMED", "RUNNING") and v["reason"] != "events.jsonl missing":
                    validation_failures.append(
                        f"  {wid}: {state} -> PENDING ({v['reason']})"
                    )

    # Count final states
    final_states = {}
    for item in items.values():
        s = item["state"]
        final_states[s] = final_states.get(s, 0) + 1

    # Write reconciled manifest
    if not dry_run:
        data["status"] = "running"  # allow resume
        # Remove lock info from manifest (informational only)
        data["lock"] = {}

        # Atomic write
        tmp = manifest_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(manifest_path))

        # Merge recovered events into merged_events.jsonl
        merged_path = run_dir / "merged_events.jsonl"
        if merged_events:
            existing_ids = set()
            if merged_path.exists():
                existing, _ = parse_events_prefix(merged_path)
                existing_ids = {
                    e.get("event_id") for e in existing
                    if e.get("event_id")
                }
            new_events = [
                e for e in merged_events
                if e.get("event_id") not in existing_ids
            ]
            if new_events:
                with open(merged_path, "a") as f:
                    for e in new_events:
                        f.write(json.dumps(e, default=str) + "\n")
                    f.flush()
                    os.fsync(f.fileno())

        # Remove stale lock file
        lock_path = run_dir / "orchestrator.lock"
        if lock_path.exists():
            lock_path.unlink()

    return {
        "model": model_slug,
        "total": len(items),
        "recovered": recovered,
        "reset_to_pending": reset_to_pending,
        "already_succeeded": already_succeeded,
        "already_failed": already_failed,
        "final_states": final_states,
        "validation_failures": validation_failures,
        "merged_events": len(merged_events),
    }


# ---------------------------------------------------------------------------
# Config patching
# ---------------------------------------------------------------------------


def patch_configs(
    dry_run: bool,
    pending_counts: dict[str, int],
) -> list[str]:
    """Set num_workers to MAX_TOTAL_WORKERS in each config.

    Since models run sequentially, each gets the full budget.
    pending_counts: {slug: N} from Phase 1 reconciliation results.
    """
    changes = []
    for slug, filename in sorted(MODEL_CONFIGS.items()):
        config_path = CONFIGS_DIR / filename
        if not config_path.exists():
            changes.append(f"  SKIP {filename}: not found")
            continue

        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        old = cfg["execution"]["num_workers"]
        remaining = pending_counts.get(slug, 0)

        new = min(MAX_TOTAL_WORKERS, remaining) if remaining > 0 else old
        if new < 1:
            new = 1

        if old == new:
            changes.append(f"  {filename}: num_workers={old} (unchanged)")
            continue

        cfg["execution"]["num_workers"] = new
        changes.append(
            f"  {filename}: num_workers {old} -> {new}"
            f" ({remaining} pending)"
        )

        if not dry_run:
            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=True)

    return changes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile global calibration manifests after crash",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("GLOBAL CALIBRATION MANIFEST RECONCILIATION")
    print(f"  logs dir: {LOGS_DIR}")
    print(f"  dry_run:  {args.dry_run}")
    print("=" * 60)

    # Phase 1: Reconcile manifests
    print("\n--- Phase 1: Reconcile manifests from disk ---\n")

    total_recovered = 0
    total_remaining = 0
    pending_counts = {}  # slug -> pending count (for Phase 2)
    summaries = []

    for slug in sorted(MODEL_CONFIGS.keys()):
        run_dir = LOGS_DIR / slug
        if not run_dir.exists():
            print(f"  SKIP {slug}: {run_dir} not found")
            continue

        result = reconcile_model(slug, run_dir, args.dry_run)
        summaries.append(result)

        if "error" in result:
            print(f"  {slug}: {result['error']}")
            continue

        succeeded = result["final_states"].get("SUCCEEDED", 0)
        pending = result["final_states"].get("PENDING", 0)
        total_recovered += result["recovered"]
        total_remaining += pending
        pending_counts[slug] = pending

        tag = "[DRY RUN] " if args.dry_run else ""
        print(
            f"  {tag}{slug}: "
            f"recovered {result['recovered']}, "
            f"reset {result['reset_to_pending']}, "
            f"merged {result['merged_events']} events | "
            f"final: {succeeded} SUCCEEDED, {pending} PENDING"
        )
        for line in result.get("validation_failures", []):
            print(f"    {line}")

    print(f"\n  TOTAL: {total_recovered} recovered from disk, "
          f"{total_remaining} remaining to run")

    # Phase 2: Patch config_storage
    print("\n--- Phase 2: Patch config_storage (sequential, 400 workers max) ---\n")
    changes = patch_configs(args.dry_run, pending_counts)
    for line in changes:
        print(line)

    # Phase 3: Print resume commands
    print("\n--- Phase 3: Resume commands (run sequentially) ---\n")

    # Order by remaining items ascending (finish small ones first)
    order = sorted(pending_counts.items(), key=lambda kv: kv[1])

    python = sys.executable
    for slug, remaining in order:
        if remaining == 0:
            print(f"# {slug}: 0 remaining (SKIP)")
            continue
        config = f"config_storage/{MODEL_CONFIGS[slug]}"
        print(
            f"# {slug}: {remaining} remaining\n"
            f"{python} orchestrate.py "
            f"--config {config} "
            f"--resume --force-lock-recovery\n"
        )

    active = [(slug, r) for slug, r in order if r > 0]
    if active:
        print("# Or run all sequentially:")
        configs_list = [
            f"config_storage/{MODEL_CONFIGS[slug]}" for slug, _ in active
        ]
        print("for cfg in \\")
        for i, cfg in enumerate(configs_list):
            end = " \\" if i < len(configs_list) - 1 else ""
            print(f"  {cfg}{end}")
        print("; do")
        print(f"  {python} orchestrate.py "
              f"--config \"$cfg\" --resume --force-lock-recovery")
        print("done")

    if args.dry_run:
        print("\n[DRY RUN] No changes written. Re-run without --dry-run.")


if __name__ == "__main__":
    main()
