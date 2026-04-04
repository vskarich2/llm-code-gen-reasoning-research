# ============================================================
# OPERATOR GUIDE: Inspecting and debugging live experiments
# ============================================================
#
# LAYOUT:
#   run_dir/
#     orchestrator.lock         <- Lock. One orchestrator.
#     config.snapshot.yaml      <- Frozen config.
#     manifest.json             <- CANONICAL STATE.
#     merged_events.jsonl       <- DERIVED analysis artifact. Not for resume.
#     workers/{work_id}/
#       attempt_001/
#         trial_config.yaml     <- Derived config for this attempt.
#         stdout.log            <- Live-tailable. Source unbuffered (-u).
#         stderr.log            <- Errors appear immediately.
#         events.jsonl          <- Flushed + fsynced per event.
#         run_summary.json      <- Convenience. Not authoritative.
#         heartbeat.json        <- Every 30s. Shows current case + PID.
#       attempt_002/            <- Created on retry. Prior attempt preserved.
#
# TRUST:  manifest > events.jsonl > everything else
# RESUME: Only manifest.json drives decisions. merged/heartbeat/stdout ignored.
#
# -- FIRST FILE TO INSPECT --
#
#   During live run:      tail -f workers/*/attempt_*/stdout.log
#   After failed run:     jq '.work_items|to_entries[]|select(.value.state=="FAILED")|{id:.key,err:.value.error}' manifest.json
#   Before resuming:      jq '[.work_items[].state]|group_by(.)|map({(.[0]):length})|add' manifest.json
#   Suspect merge bugs:   jq -r '.event_id' merged_events.jsonl | sort | uniq -d
#   Suspect signal bugs:  jq '.status' manifest.json
#
# -- TRIAGE COMMANDS (copy-paste) --
#
#   State summary:
#     jq '[.work_items[].state]|group_by(.)|map({(.[0]):length})|add' manifest.json
#   RUNNING items:
#     jq '.work_items|to_entries[]|select(.value.state=="RUNNING")|.key' manifest.json
#   Retried items (attempt>1):
#     jq '.work_items|to_entries[]|select(.value.attempt>1)|{id:.key,attempt:.value.attempt,state:.value.state}' manifest.json
#   Stale heartbeats:
#     for d in workers/*/attempt_*/; do
#       ts=$(cat "${d}heartbeat.json" 2>/dev/null | jq -r .updated_at)
#       [ -n "$ts" ] && echo "$d $ts"
#     done | sort -k2
#   Nonzero exits:
#     jq '.work_items|to_entries[]|select(.value.exit_code!=null and .value.exit_code!=0)|{id:.key,exit:.value.exit_code}' manifest.json
#   SUCCEEDED missing merged_at:
#     jq '.work_items|to_entries[]|select(.value.state=="SUCCEEDED" and .value.merged_at==null)|.key' manifest.json
#   Stuck in MERGING:
#     jq '.work_items|to_entries[]|select(.value.state=="MERGING")|.key' manifest.json
#   Duplicate event_ids:
#     jq -r '.event_id' merged_events.jsonl | sort | uniq -d
#   Correctness errors in events:
#     jq 'select(.event_type | startswith("case.error"))' workers/*/attempt_*/events.jsonl
#   You should NEVER need stderr.log to determine why a case failed.
#   If you do, that is a bug in structured error promotion.
#
# ============================================================

"""Failure-proof experiment orchestrator for T3 benchmark.

This design uses OS processes only. It does not use threads,
ThreadPoolExecutor, ProcessPoolExecutor, or threading primitives.

Usage:
    python orchestrate.py --config experiment.yaml
    python orchestrate.py --config experiment.yaml --dry-run
    python orchestrate.py --config experiment.yaml --resume
    python orchestrate.py --config experiment.yaml --resume --rerun-failed
    python orchestrate.py --config experiment.yaml --rebuild-merged
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from core.config.paths import (
    MANIFEST_FILENAME, EVENTS_FILENAME, MERGED_EVENTS_FILENAME,
    CONFIG_SNAPSHOT_FILENAME, LOCK_FILENAME, HEARTBEAT_FILENAME,
    TRIAL_CONFIG_FILENAME, STDOUT_LOG_FILENAME, STDERR_LOG_FILENAME,
)

sys.stdout.reconfigure(line_buffering=True)


# ============================================================
# CONCURRENCY: process-only, no threading primitives
# ============================================================

_stop_requested = False


def _signal_handler(signum, frame):
    global _stop_requested
    _stop_requested = True


def install_signal_handlers():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass(frozen=True)
class WorkItem:
    work_id: str          # "{safe_model}__{condition}__trial_{NNN}__{case_id}"
    model: str
    condition: str
    trial: int
    case_id: str          # single case per work item
    expected_cases: int   # always 1


def make_work_id(model: str, condition: str, trial: int, case_id: str) -> str:
    safe_model = model.replace(".", "_").replace("/", "_")
    return f"{safe_model}__{condition}__trial_{trial:03d}__{case_id}"


@dataclass
class WorkItemState:
    work_id: str
    model: str
    condition: str
    trial: int
    case_id: str
    expected_cases: int     # always 1
    state: str              # PENDING|CLAIMED|RUNNING|MERGING|SUCCEEDED|FAILED|ABORTED
    attempt: int            # starts at 1, increments per retry
    instance_id: str        # "{work_id}__attempt_{attempt:03d}"
    worker_dir: str         # "workers/{work_id}/attempt_{attempt:03d}"
    claimed_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    merged_at: str | None = None
    exit_code: int | None = None
    completed_cases: int = 0
    terminal_case_events: int = 0
    validation: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class Manifest:
    schema_version: str     # "1.0"
    run_id: str
    config_sha256: str
    created_at: str
    status: str             # initializing|running|completed|aborted|failed
    work_items: dict[str, WorkItemState] = field(default_factory=dict)
    lock: dict = field(default_factory=dict)  # informational copy only


@dataclass
class ActiveWorker:
    work_id: str
    process: subprocess.Popen
    pid: int
    stdout_path: Path
    stderr_path: Path
    stdout_fh: object       # open file handle
    stderr_fh: object       # open file handle
    worker_dir: Path
    launched_at: float       # time.monotonic()
    trial_config_path: Path


@dataclass
class ValidationResult:
    ok: bool
    worker_start_seen: bool = False
    worker_end_seen: bool = False
    run_end_seen: bool = False
    expected_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    case_counts_match: bool = False
    duplicate_terminal_cases: list = field(default_factory=list)
    missing_cases: list = field(default_factory=list)
    parse_errors: int = 0
    max_sequence: int = 0
    sequence_contiguous: bool = False
    instance_id_match: bool = False
    error_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "worker_start_seen": self.worker_start_seen,
            "worker_end_seen": self.worker_end_seen,
            "run_end_seen": self.run_end_seen,
            "expected_cases": self.expected_cases,
            "completed_cases": self.completed_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "case_counts_match": self.case_counts_match,
            "duplicate_terminal_cases": self.duplicate_terminal_cases,
            "missing_cases": self.missing_cases,
            "parse_errors": self.parse_errors,
            "max_sequence": self.max_sequence,
            "sequence_contiguous": self.sequence_contiguous,
            "instance_id_match": self.instance_id_match,
            "error_summary": self.error_summary,
        }


class IllegalTransition(RuntimeError):
    pass


_SIGKILL_WAIT_SECONDS = 5  # infrastructure constant, not experimental config


# ============================================================
# STATE MACHINE
# ============================================================

_LEGAL_TRANSITIONS = {
    "PENDING": {"CLAIMED"},
    "CLAIMED": {"RUNNING", "FAILED", "ABORTED"},
    "RUNNING": {"MERGING", "ABORTED"},
    "MERGING": {"SUCCEEDED", "FAILED", "ABORTED"},
}


def mark_state(manifest: Manifest, work_id: str, new_state: str, **updates) -> bool:
    """Transition a work item to a new state. Idempotent if already in target state.
    Raises IllegalTransition if the transition is not allowed."""
    item = manifest.work_items[work_id]
    if item.state == new_state:
        return False
    allowed = _LEGAL_TRANSITIONS.get(item.state, set())
    if new_state not in allowed:
        raise IllegalTransition(f"{item.state} -> {new_state} for {work_id}")
    item.state = new_state
    for k, v in updates.items():
        setattr(item, k, v)
    return True


def count_by_state(manifest: Manifest) -> dict[str, int]:
    """Derive state counts from work items. No stored counters."""
    return dict(Counter(item.state for item in manifest.work_items.values()))


# ============================================================
# ATOMIC WRITE PROTOCOLS
# ============================================================

def atomic_write_json(target_path: Path, data: dict) -> None:
    """Atomic replace: temp -> write -> fsync file -> os.replace -> fsync dir.
    Target transitions old->new in one os.replace call.
    NOT the same as crash-tolerant append. See atomic_append_events."""
    target_path = Path(target_path)
    tmp_path = target_path.with_suffix(".tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp_path), str(target_path))
    dir_fd = os.open(str(target_path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_append_events(merged_path: Path, events: list[dict]) -> None:
    """Crash-tolerant append: open append -> write -> flush -> fsync.
    Last line may be truncated on crash. Prefix parser handles this.
    Dedup by event_id on re-merge prevents double-counting.
    NOT atomic replace — different guarantee."""
    if not events:
        return
    content = "".join(json.dumps(e, default=str) + "\n" for e in events)
    with open(merged_path, "a") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


# ============================================================
# MANIFEST SERIALIZATION
# ============================================================

def manifest_to_dict(manifest: Manifest) -> dict:
    """Serialize Manifest to JSON-safe dict. work_items keyed by work_id."""
    items = {}
    for wid, item in manifest.work_items.items():
        items[wid] = {
            "work_id": item.work_id,
            "model": item.model,
            "condition": item.condition,
            "trial": item.trial,
            "case_id": item.case_id,
            "expected_cases": item.expected_cases,
            "state": item.state,
            "attempt": item.attempt,
            "instance_id": item.instance_id,
            "worker_dir": item.worker_dir,
            "claimed_at": item.claimed_at,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
            "merged_at": item.merged_at,
            "exit_code": item.exit_code,
            "completed_cases": item.completed_cases,
            "terminal_case_events": item.terminal_case_events,
            "validation": item.validation,
            "error": item.error,
        }
    return {
        "schema_version": manifest.schema_version,
        "run_id": manifest.run_id,
        "config_sha256": manifest.config_sha256,
        "created_at": manifest.created_at,
        "status": manifest.status,
        "work_items": items,
        "lock": manifest.lock,
    }


def dict_to_manifest(d: dict) -> Manifest:
    """Deserialize dict (from JSON) to Manifest."""
    items = {}
    for wid, item_d in d.get("work_items", {}).items():
        items[wid] = WorkItemState(
            work_id=item_d["work_id"],
            model=item_d["model"],
            condition=item_d["condition"],
            trial=item_d["trial"],
            case_id=item_d["case_id"],
            expected_cases=item_d["expected_cases"],
            state=item_d["state"],
            attempt=item_d["attempt"],
            instance_id=item_d["instance_id"],
            worker_dir=item_d["worker_dir"],
            claimed_at=item_d.get("claimed_at"),
            started_at=item_d.get("started_at"),
            finished_at=item_d.get("finished_at"),
            merged_at=item_d.get("merged_at"),
            exit_code=item_d.get("exit_code"),
            completed_cases=item_d.get("completed_cases", 0),
            terminal_case_events=item_d.get("terminal_case_events", 0),
            validation=item_d.get("validation", {}),
            error=item_d.get("error"),
        )
    return Manifest(
        schema_version=d["schema_version"],
        run_id=d["run_id"],
        config_sha256=d["config_sha256"],
        created_at=d["created_at"],
        status=d["status"],
        work_items=items,
        lock=d.get("lock", {}),
    )


# ============================================================
# LOCK PROTOCOL
# ============================================================

def acquire_lock(run_dir: Path, force: bool = False) -> bool:
    """Acquire orchestrator lock. Returns True if acquired.
    orchestrator.lock governs exclusivity. manifest.lock is informational only.
    No control flow may depend on manifest lock copy."""
    lock_path = run_dir / LOCK_FILENAME
    if lock_path.exists() and not force:
        try:
            lock = json.loads(lock_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass  # corrupt lock file treated as stale
        else:
            if lock.get("holder_hostname") == socket.gethostname():
                try:
                    os.kill(lock["holder_pid"], 0)
                    print(
                        f"ERROR: Lock held by live process PID {lock['holder_pid']} "
                        f"on this host. Use --force-lock-recovery if certain.",
                        flush=True,
                    )
                    return False
                except (ProcessLookupError, OSError):
                    pass  # stale PID
            else:
                try:
                    hb = datetime.fromisoformat(lock["heartbeat_at"].rstrip("Z"))
                    if (datetime.utcnow() - hb).total_seconds() < 300:
                        print(
                            f"ERROR: Lock held by PID {lock['holder_pid']} on "
                            f"{lock['holder_hostname']} (heartbeat {lock['heartbeat_at']}). "
                            f"Use --force-lock-recovery if certain.",
                            flush=True,
                        )
                        return False
                except (KeyError, ValueError):
                    pass  # malformed heartbeat treated as stale

    if lock_path.exists():
        try:
            stale = json.loads(lock_path.read_text())
            print(
                f"WARNING: Recovering stale lock from PID {stale.get('holder_pid')} "
                f"on {stale.get('holder_hostname')} "
                f"(heartbeat: {stale.get('heartbeat_at')})",
                flush=True,
            )
        except (json.JSONDecodeError, OSError):
            print("WARNING: Recovering corrupt lock file", flush=True)

    atomic_write_json(lock_path, {
        "holder_pid": os.getpid(),
        "holder_hostname": socket.gethostname(),
        "acquired_at": datetime.utcnow().isoformat() + "Z",
        "heartbeat_at": datetime.utcnow().isoformat() + "Z",
    })
    return True


def release_lock(run_dir: Path) -> None:
    """Release lock on clean exit. On crash, lock becomes stale."""
    lock_path = run_dir / LOCK_FILENAME
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def refresh_lock_heartbeat(run_dir: Path) -> None:
    """Update lock heartbeat. Called every 60s in main loop."""
    lock_path = run_dir / LOCK_FILENAME
    if not lock_path.exists():
        return
    try:
        lock = json.loads(lock_path.read_text())
        lock["heartbeat_at"] = datetime.utcnow().isoformat() + "Z"
        atomic_write_json(lock_path, lock)
    except (json.JSONDecodeError, OSError):
        pass


# ============================================================
# WORK ITEM GENERATION
# ============================================================

def resolve_case_ids(config) -> list[str]:
    """Resolve case IDs from config. Returns frozen list."""
    from core.pipeline.orchestration.runner import load_cases
    cases = load_cases(case_id=None, cases_file=config.cases.source)
    if config.cases.case_ids:
        case_id_set = set(config.cases.case_ids)
        cases = [c for c in cases if c["id"] in case_id_set]
    if config.cases.max_cases and config.cases.max_cases > 0:
        cases = cases[:config.cases.max_cases]
    return [c["id"] for c in cases]


def generate_work_items(config, case_ids: list[str]) -> list[WorkItem]:
    """Generate per-case work items. Deterministic ordering."""
    items = []
    for model_spec in config.models.generation:
        for condition_name in sorted(config.conditions.keys()):
            for trial in range(1, config.trials + 1):
                for cid in case_ids:
                    work_id = make_work_id(model_spec.name, condition_name, trial, cid)
                    items.append(WorkItem(
                        work_id=work_id,
                        model=model_spec.name,
                        condition=condition_name,
                        trial=trial,
                        case_id=cid,
                        expected_cases=1,
                    ))
    return items


def initialize_manifest(config, work_items: list[WorkItem], run_id: str) -> Manifest:
    """Create a fresh manifest with all items PENDING."""
    items = {}
    for item in work_items:
        instance_id = f"{item.work_id}__attempt_001"
        items[item.work_id] = WorkItemState(
            work_id=item.work_id,
            model=item.model,
            condition=item.condition,
            trial=item.trial,
            case_id=item.case_id,
            expected_cases=item.expected_cases,
            state="PENDING",
            attempt=1,
            instance_id=instance_id,
            worker_dir=f"workers/{item.work_id}/attempt_001",
        )
    return Manifest(
        schema_version="1.0",
        run_id=run_id,
        config_sha256=config._config_sha256,
        created_at=datetime.utcnow().isoformat() + "Z",
        status="initializing",
        work_items=items,
    )


# ============================================================
# DERIVED CONFIG
# ============================================================

def derive_trial_config(parent_config, item: WorkItem, attempt: int,
                        worker_dir: Path) -> dict:
    """Create ephemeral per-worker config. Not user-authored. Overwritten on retry."""
    from core.config.experiment_config import config_to_dict
    d = config_to_dict(parent_config)
    d["trials"] = 1
    d["run"]["trial"] = item.trial
    d["run"]["run_id"] = f"{item.work_id}__attempt_{attempt:03d}"
    d["run"]["run_dir"] = str(worker_dir)
    d["models"]["generation"] = [
        m for m in d["models"]["generation"] if m["name"] == item.model
    ]
    d["conditions"] = {
        k: v for k, v in d["conditions"].items() if k == item.condition
    }
    d["execution"]["num_workers"] = 1
    d["cases"]["case_ids"] = [item.case_id]
    d["_parent_config_sha256"] = parent_config._config_sha256
    d["_work_id"] = item.work_id
    d["_instance_id"] = f"{item.work_id}__attempt_{attempt:03d}"
    d["_attempt"] = attempt
    return d


# ============================================================
# PREFIX-SAFE EVENT PARSER
# ============================================================

def parse_events_prefix(path: Path) -> tuple[list[dict], int]:
    """Parse events.jsonl stopping at first malformed line.
    Returns (valid_events, parse_error_count)."""
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


# ============================================================
# WORKER VALIDATION
# ============================================================

def validate_worker_artifacts(item: WorkItemState, worker_dir: Path) -> ValidationResult:
    """Validate worker events against completion semantics.
    Success requires: worker.start + worker.end + run.end + case count match +
    no duplicates + contiguous sequence + instance_id match."""
    events_path = worker_dir / EVENTS_FILENAME
    if not events_path.exists():
        return ValidationResult(ok=False, error_summary="events.jsonl not found")
    events, parse_errors = parse_events_prefix(events_path)
    if not events:
        return ValidationResult(ok=False, parse_errors=parse_errors,
                                error_summary="events.jsonl empty or unparseable")

    worker_start_seen = False
    worker_end_seen = False
    run_end_seen = False
    instance_id_match = False
    case_terminals = {}  # case_id -> count
    passed = 0
    failed = 0
    sequences = []

    for e in events:
        et = e.get("event_type", "")
        seq = e.get("sequence")
        if seq is not None:
            sequences.append(seq)

        if et == "worker.start" or (et == "pipeline_state" and e.get("context", {}).get("step") == "run_start"):
            worker_start_seen = True
            if e.get("instance_id") == item.instance_id:
                instance_id_match = True

        if et == "worker.end" or (et == "pipeline_state" and e.get("context", {}).get("step") == "run_end"):
            if et == "worker.end":
                worker_end_seen = True
            if et == "pipeline_state" and e.get("context", {}).get("step") == "run_end":
                run_end_seen = True

        if et == "run.end":
            run_end_seen = True

        if et in ("case.end", "execution_eval"):
            cid = e.get("case_id") or e.get("context", {}).get("case_id")
            if cid:
                case_terminals[cid] = case_terminals.get(cid, 0) + 1
                ex = e.get("execution", {})
                if ex.get("passed"):
                    passed += 1
                else:
                    failed += 1

        if et in ("case.failed", "error"):
            cid = e.get("case_id") or e.get("context", {}).get("case_id")
            if cid:
                case_terminals[cid] = case_terminals.get(cid, 0) + 1
                failed += 1

    completed = sum(1 for c in case_terminals.values() if c >= 1)
    duplicates = [cid for cid, count in case_terminals.items() if count > 1]
    expected_case_ids = [item.case_id]
    missing = [cid for cid in expected_case_ids if cid not in case_terminals]
    case_match = completed == item.expected_cases

    # Sequence contiguity (within this attempt)
    seq_contiguous = True
    if sequences:
        sequences_sorted = sorted(sequences)
        for i in range(1, len(sequences_sorted)):
            if sequences_sorted[i] != sequences_sorted[i - 1] + 1:
                seq_contiguous = False
                break

    # For backward compat: treat run.start as worker.start if no explicit worker.start
    if not worker_start_seen:
        for e in events:
            if e.get("event_type") == "run.start" or (
                e.get("event_type") == "pipeline_state"
                and e.get("context", {}).get("step") == "run_start"
            ):
                worker_start_seen = True
                instance_id_match = True  # legacy events don't have instance_id
                break

    # For backward compat: treat run.end as worker.end if no explicit worker.end
    if not worker_end_seen and run_end_seen:
        worker_end_seen = True

    ok = (
        worker_start_seen
        and worker_end_seen
        and run_end_seen
        and case_match
        and len(duplicates) == 0
        and len(missing) == 0
        and parse_errors == 0
        and seq_contiguous
        and instance_id_match
    )

    errors_list = []
    if not worker_start_seen:
        errors_list.append("worker.start missing")
    if not worker_end_seen:
        errors_list.append("worker.end missing")
    if not run_end_seen:
        errors_list.append("run.end missing")
    if not case_match:
        errors_list.append(f"cases: {completed}/{item.expected_cases}")
    if duplicates:
        errors_list.append(f"duplicate terminals: {duplicates}")
    if missing:
        errors_list.append(f"missing cases: {missing}")
    if parse_errors:
        errors_list.append(f"{parse_errors} parse errors")
    if not seq_contiguous:
        errors_list.append("sequence gaps")
    if not instance_id_match:
        errors_list.append("instance_id mismatch")

    return ValidationResult(
        ok=ok,
        worker_start_seen=worker_start_seen,
        worker_end_seen=worker_end_seen,
        run_end_seen=run_end_seen,
        expected_cases=item.expected_cases,
        completed_cases=completed,
        passed_cases=passed,
        failed_cases=failed,
        case_counts_match=case_match,
        duplicate_terminal_cases=duplicates,
        missing_cases=missing,
        parse_errors=parse_errors,
        max_sequence=max(sequences) if sequences else 0,
        sequence_contiguous=seq_contiguous,
        instance_id_match=instance_id_match,
        error_summary="; ".join(errors_list),
    )


# ============================================================
# MERGE
# ============================================================

def merge_worker_events(item: WorkItemState, worker_dir: Path,
                        merged_path: Path) -> tuple[bool, int]:
    """Merge one worker's events into merged_events.jsonl.
    Idempotent: skips events whose event_id already exists.
    Returns (success, events_appended)."""
    worker_events, errs = parse_events_prefix(worker_dir / EVENTS_FILENAME)
    if errs > 0 or not worker_events:
        return False, 0

    existing_ids = set()
    if merged_path.exists():
        existing, _ = parse_events_prefix(merged_path)
        existing_ids = {e.get("event_id") for e in existing if e.get("event_id")}

    new = [e for e in worker_events if e.get("event_id") not in existing_ids]

    if new:
        atomic_append_events(merged_path, new)

    return True, len(new)


def rebuild_merged_events(manifest: Manifest, run_dir: Path) -> int:
    """Rebuild merged_events.jsonl from scratch using SUCCEEDED workers only.
    Deterministic given manifest + retained worker dirs. Returns events written."""
    merged_path = run_dir / MERGED_EVENTS_FILENAME
    all_events = []
    missing_count = 0
    total_succeeded = 0

    for wid, item in manifest.work_items.items():
        if item.state != "SUCCEEDED":
            continue
        total_succeeded += 1
        wd = run_dir / item.worker_dir
        if not (wd / EVENTS_FILENAME).exists():
            missing_count += 1
            print(f"  WARNING: {wid} SUCCEEDED but worker dir missing", flush=True)
            continue
        events, errors = parse_events_prefix(wd / EVENTS_FILENAME)
        if errors == 0:
            all_events.extend(events)

    if missing_count > 0 and total_succeeded > 0:
        pct = missing_count / total_succeeded * 100
        print(
            f"  WARNING: {missing_count}/{total_succeeded} SUCCEEDED items "
            f"missing worker dirs ({pct:.0f}%). Rebuild incomplete.",
            flush=True,
        )

    all_events.sort(key=lambda e: (e.get("timestamp", ""), e.get("sequence", 0)))
    tmp = merged_path.with_suffix(".rebuild_tmp")
    with open(tmp, "w") as f:
        for e in all_events:
            f.write(json.dumps(e, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(merged_path))
    return len(all_events)


# ============================================================
# RESUME
# ============================================================

def _is_worker_alive(item: WorkItemState, run_dir: Path) -> tuple[bool, int | None]:
    """Check if orphan worker is still alive. Returns (alive, pid)."""
    worker_dir = run_dir / item.worker_dir
    heartbeat_path = worker_dir / HEARTBEAT_FILENAME
    if not heartbeat_path.exists():
        return False, None
    try:
        hb = json.loads(heartbeat_path.read_text())
        pid = hb.get("pid")
        if pid is None:
            return False, None
        os.kill(pid, 0)
        return True, pid
    except (ProcessLookupError, json.JSONDecodeError, OSError):
        return False, None


def _verify_orphan_pid(pid: int, instance_id: str) -> bool:
    """Verify PID's command line contains the exact instance_id."""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5,
            )
            cmdline = result.stdout.strip()
        else:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\x00", " ")
        return instance_id in cmdline
    except (FileNotFoundError, ProcessLookupError, subprocess.TimeoutExpired, OSError):
        return False


def recover_manifest_for_resume(manifest: Manifest, run_dir: Path,
                                rerun_failed: bool = False,
                                kill_orphans: bool = False) -> Manifest:
    """Reconcile manifest after crash/interrupt. Only SUCCEEDED is trusted."""
    reset_summary = []
    for wid, item in manifest.work_items.items():
        if item.state == "SUCCEEDED":
            continue
        if item.state == "FAILED":
            if rerun_failed:
                item.state = "PENDING"
                item.error = None
                item.validation = {}
                reset_summary.append(f"{wid}: FAILED->PENDING (rerun-failed)")
            continue

        if item.state in ("CLAIMED", "RUNNING"):
            alive, pid = _is_worker_alive(item, run_dir)
            if alive and pid:
                verified = _verify_orphan_pid(pid, item.instance_id)
                if kill_orphans and verified:
                    os.kill(pid, signal.SIGTERM)
                    print(
                        f"  KILLED orphan PID {pid} for {wid} (verified)",
                        flush=True,
                    )
                elif kill_orphans and not verified:
                    print(
                        f"  WARNING: Orphan PID {pid} for {wid} NOT killed "
                        f"(cmdline verification failed)",
                        flush=True,
                    )
                else:
                    print(
                        f"  WARNING: Orphan PID {pid} for {wid} still alive. "
                        f"Wasting API budget. Use --kill-orphans",
                        flush=True,
                    )
            reset_summary.append(f"{wid}: {item.state}->PENDING (stale)")
            item.state = "PENDING"
            continue

        if item.state == "MERGING":
            reset_summary.append(f"{wid}: MERGING->PENDING (incomplete)")
            item.state = "PENDING"
            continue

        if item.state == "ABORTED":
            reset_summary.append(f"{wid}: ABORTED->PENDING")
            item.state = "PENDING"
            continue

    counts = count_by_state(manifest)
    print(
        f"RESUME: {counts.get('SUCCEEDED', 0)} kept, "
        f"{len(reset_summary)} reset to PENDING",
        flush=True,
    )
    for line in reset_summary:
        print(f"  {line}", flush=True)
    return manifest


# ============================================================
# WORKER LAUNCH
# ============================================================

def launch_worker(item: WorkItemState, config, run_dir: Path) -> ActiveWorker:
    """Launch a worker subprocess for one work item."""
    worker_dir = run_dir / item.worker_dir
    worker_dir.mkdir(parents=True, exist_ok=True)

    # Write derived config
    trial_config = derive_trial_config(config, WorkItem(
        work_id=item.work_id, model=item.model, condition=item.condition,
        trial=item.trial, case_id=item.case_id, expected_cases=item.expected_cases,
    ), item.attempt, worker_dir)
    trial_config_path = worker_dir / TRIAL_CONFIG_FILENAME
    with open(trial_config_path, "w") as f:
        yaml.dump(trial_config, f, default_flow_style=False)

    stdout_path = worker_dir / STDOUT_LOG_FILENAME
    stderr_path = worker_dir / STDERR_LOG_FILENAME
    stdout_fh = open(stdout_path, "w", buffering=1)
    stderr_fh = open(stderr_path, "w", buffering=1)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "core.pipeline.orchestration.runner",
         "--config", str(trial_config_path),
         "--instance-id", item.instance_id],
        stdout=stdout_fh,
        stderr=stderr_fh,
        env=env,
    )

    return ActiveWorker(
        work_id=item.work_id,
        process=proc,
        pid=proc.pid,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_fh=stdout_fh,
        stderr_fh=stderr_fh,
        worker_dir=worker_dir,
        launched_at=time.monotonic(),
        trial_config_path=trial_config_path,
    )


def harvest_finished_workers(active: dict[str, ActiveWorker]) -> list[tuple[str, ActiveWorker]]:
    """Poll active workers and return those that have exited."""
    finished = []
    for wid, worker in list(active.items()):
        if worker.process.poll() is not None:
            finished.append((wid, active.pop(wid)))
    return finished


# ============================================================
# TIMEOUT
# ============================================================

def timeout_worker(worker: ActiveWorker, grace_seconds: int) -> int:
    """SIGTERM -> wait grace -> SIGKILL. Returns exit code."""
    worker.process.terminate()
    try:
        worker.process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        worker.process.kill()
        worker.process.wait(timeout=_SIGKILL_WAIT_SECONDS)
    worker.stdout_fh.close()
    worker.stderr_fh.close()
    return worker.process.returncode or -9


# ============================================================
# SHUTDOWN
# ============================================================

def shutdown(active: dict[str, ActiveWorker], manifest: Manifest,
             run_dir: Path, grace_seconds: int) -> None:
    """Graceful shutdown on SIGINT/SIGTERM."""
    for wid, w in active.items():
        w.process.terminate()

    deadline = time.monotonic() + grace_seconds
    while active and time.monotonic() < deadline:
        finished = harvest_finished_workers(active)
        for wid, worker in finished:
            worker.stdout_fh.close()
            worker.stderr_fh.close()
            mark_state(manifest, wid, "MERGING",
                       finished_at=_now_iso(), exit_code=worker.process.returncode)
            v = validate_worker_artifacts(manifest.work_items[wid], worker.worker_dir)
            if v.ok:
                merge_worker_events(
                    manifest.work_items[wid], worker.worker_dir,
                    run_dir / MERGED_EVENTS_FILENAME,
                )
                mark_state(manifest, wid, "SUCCEEDED", merged_at=_now_iso(),
                           completed_cases=v.completed_cases,
                           validation=v.to_dict())
            else:
                mark_state(manifest, wid, "FAILED", error=v.error_summary,
                           validation=v.to_dict())
            atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))
        time.sleep(0.2)

    for wid, worker in list(active.items()):
        worker.process.kill()
        worker.process.wait(timeout=_SIGKILL_WAIT_SECONDS)
        worker.stdout_fh.close()
        worker.stderr_fh.close()
        mark_state(manifest, wid, "ABORTED", finished_at=_now_iso(),
                   exit_code=worker.process.returncode,
                   error="killed during shutdown")

    manifest.status = "aborted"
    atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))


# ============================================================
# HELPERS
# ============================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _print_manifest_summary(manifest: Manifest) -> None:
    counts = count_by_state(manifest)
    parts = ", ".join(f"{c} {s}" for s, c in sorted(counts.items()))
    print(f"  Status: {parts}", flush=True)


# ============================================================
# PREFLIGHT
# ============================================================

# ============================================================
# SMOKE GATE — mandatory pre-launch validation
# ============================================================

_SMOKE_ACCEPTABLE = {"EXECUTION_SUCCESS", "INVARIANT_FAILURE", "INVARIANT_CRASH"}


def _select_smoke_cases(cases, config):
    """Select cases covering distinct execution paths."""
    smoke = {}
    for case in cases:
        if len(case["code_files"]) == 1 and "baseline_single_file" not in smoke:
            smoke["baseline_single_file"] = case
        if len(case["code_files"]) >= 3 and "multi_file" not in smoke:
            smoke["multi_file"] = case
    retry_conds = [c for c, cfg in config.conditions.items()
                   if cfg.retry.enabled]
    if retry_conds:
        smoke["retry"] = cases[0]
    if not smoke.get("baseline_single_file"):
        smoke["baseline_single_file"] = cases[0]
    if not smoke.get("multi_file"):
        smoke["multi_file"] = cases[-1] if len(cases) > 1 else cases[0]
    return smoke


def _select_smoke_models(config):
    """Select models for smoke coverage. At least 1, at most 2."""
    models = [m.name for m in config.models.generation]
    if len(models) <= 1:
        return models
    return [models[0], models[-1]]


def _smoke_execute_case(config, case, condition, run_dir, label,
                        model_name):
    """Run one case through the real execution path."""
    from core.pipeline.orchestration.execution_v2 import run_v2
    from core.logging_.logging_core import RunLogger

    smoke_dir = run_dir / "_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(
        smoke_dir, run_id=f"smoke_{label}",
        model=model_name, condition=condition, trial=0)
    logger.start_run(model=model_name, condition=condition)
    try:
        _, _, ev = run_v2(case, model_name, condition, logger)
    except Exception as e:
        raise RuntimeError(
            f"SMOKE GATE FAILED ({label}): {type(e).__name__}: {e}"
        ) from e
    cat = ev.get("execution_category", "UNKNOWN")
    if cat not in _SMOKE_ACCEPTABLE:
        raise RuntimeError(
            f"SMOKE GATE FAILED ({label}): execution_category={cat}, "
            f"reasons={ev.get('reasons', [])!r}"
        )


def _smoke_gate(config, cases, run_dir):
    """Mandatory pre-launch validation. Aborts on any failure."""
    print("SMOKE GATE: starting...", flush=True)
    smoke_cases = _select_smoke_cases(cases, config)
    smoke_models = _select_smoke_models(config)
    conditions = list(config.conditions.keys())
    baseline_cond = conditions[0]

    # Gate 5: Per-model E2E
    for model_name in smoke_models:
        _smoke_execute_case(config, smoke_cases["baseline_single_file"],
                            baseline_cond, run_dir,
                            f"baseline_{model_name}", model_name)
        print(f"  GATE 5: baseline_{model_name} OK", flush=True)
        if model_name == smoke_models[0]:
            _smoke_execute_case(config, smoke_cases["multi_file"],
                                baseline_cond, run_dir,
                                "multi_file", model_name)
            print("  GATE 5: multi_file OK", flush=True)

    # Gate 5c: Retry (conditional)
    retry_conds = [c for c, cfg in config.conditions.items()
                   if cfg.retry.enabled]
    if "retry" in smoke_cases and retry_conds:
        from core.pipeline.orchestration.retry_v2 import run_retry_v2
        from core.logging_.logging_core import RunLogger
        smoke_dir = run_dir / "_smoke"
        logger = RunLogger(
            smoke_dir, run_id="smoke_retry",
            model=smoke_models[0], condition=retry_conds[0], trial=0)
        logger.start_run(model=smoke_models[0], condition=retry_conds[0])
        try:
            run_retry_v2(smoke_cases["retry"], smoke_models[0],
                         retry_conds[0], logger)
        except Exception as e:
            raise RuntimeError(
                f"SMOKE GATE FAILED (retry): {type(e).__name__}: {e}"
            ) from e
        print("  GATE 5c: retry OK", flush=True)

    print("SMOKE GATE: all checks passed", flush=True)


# ============================================================
# PREFLIGHT VALIDATION
# ============================================================

def preflight_validate(config, case_ids: list[str]) -> None:
    """Run all preflight checks. Raises on failure."""
    from core.pipeline.orchestration.runner import load_cases, preflight_verify_tests
    from core.registry.condition_registry import validate_run

    cases = load_cases(case_id=None, cases_file=config.cases.source)
    if case_ids:
        case_id_set = set(case_ids)
        cases = [c for c in cases if c["id"] in case_id_set]

    preflight_verify_tests(cases)
    validate_run(cases, list(config.conditions.keys()))
    print(f"  Preflight: {len(cases)} cases, {len(config.conditions)} conditions OK",
          flush=True)


# ============================================================
# MAIN SCHEDULING LOOP
# ============================================================

def run_experiment(config, args) -> int:
    """Main orchestrator entry point. Returns exit code."""
    global _stop_requested

    run_dir = Path(config.run.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Lock
    if not acquire_lock(run_dir, force=getattr(args, "force_lock_recovery", False)):
        return 3

    try:
        return _run_experiment_inner(config, args, run_dir)
    finally:
        release_lock(run_dir)


def _run_experiment_inner(config, args, run_dir: Path) -> int:
    global _stop_requested
    install_signal_handlers()

    case_ids = resolve_case_ids(config)
    work_items = generate_work_items(config, case_ids)

    # Resume or fresh
    manifest_path = run_dir / MANIFEST_FILENAME
    if args.resume and manifest_path.exists():
        try:
            manifest = dict_to_manifest(json.loads(manifest_path.read_text()))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"ERROR: Manifest corrupt: {e}", flush=True)
            return 5
        manifest = recover_manifest_for_resume(
            manifest, run_dir,
            rerun_failed=getattr(args, "rerun_failed", False),
            kill_orphans=getattr(args, "kill_orphans", False),
        )
    else:
        run_id = f"{config.experiment.name}__{datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')}"
        preflight_validate(config, case_ids)

        # Smoke gate: end-to-end validation before fan-out
        from core.pipeline.orchestration.runner import load_cases as _load_cases
        smoke_cases = _load_cases(case_id=None, cases_file=config.cases.source)
        if case_ids:
            smoke_cases = [c for c in smoke_cases if c["id"] in set(case_ids)]
        _smoke_gate(config, smoke_cases, run_dir)

        manifest = initialize_manifest(config, work_items, run_id)

        # Snapshot config
        with open(run_dir / CONFIG_SNAPSHOT_FILENAME, "w") as f:
            yaml.dump(json.loads(json.dumps(
                __import__("core.config.experiment_config", fromlist=["config_to_dict"]).config_to_dict(config), default=str
            )), f, default_flow_style=False)

    atomic_write_json(manifest_path, manifest_to_dict(manifest))

    # Dry run
    if args.dry_run:
        pending = [wid for wid, item in manifest.work_items.items()
                   if item.state == "PENDING"]
        print(f"DRY RUN: {len(pending)} pending work items", flush=True)
        for wid in pending[:20]:
            print(f"  {wid}", flush=True)
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more", flush=True)
        return 0

    # Rebuild merged
    if getattr(args, "rebuild_merged", False):
        n = rebuild_merged_events(manifest, run_dir)
        print(f"Rebuilt merged_events.jsonl: {n} events", flush=True)
        return 0

    # Run
    total = len(manifest.work_items)
    pending_count = sum(1 for i in manifest.work_items.values() if i.state == "PENDING")
    print(
        f"ORCHESTRATOR: {total} work items, {pending_count} pending, "
        f"{total - pending_count} already terminal",
        flush=True,
    )

    num_workers = config.execution.num_workers
    timeout_seconds = config.execution.worker_timeout_seconds
    grace_seconds = config.execution.worker_graceful_shutdown_seconds

    active: dict[str, ActiveWorker] = {}
    done_count = 0
    rolling_error_counts: Counter = Counter()
    workers_since_error_summary = 0
    last_lock_refresh = time.monotonic()

    if manifest.status == "initializing":
        manifest.status = "running"

    while True:
        if _stop_requested:
            print("\nShutdown requested...", flush=True)
            shutdown(active, manifest, run_dir, grace_seconds)
            return 2

        # Launch pending items up to num_workers
        pending = [
            wid for wid, item in manifest.work_items.items()
            if item.state == "PENDING"
        ]
        while pending and len(active) < num_workers:
            wid = pending.pop(0)
            item = manifest.work_items[wid]

            # Increment attempt on retry
            if item.attempt > 1 or item.claimed_at is not None:
                item.attempt += 1
                if item.attempt > config.execution.max_orchestrator_attempts:
                    mark_state(manifest, wid, "CLAIMED")
                    mark_state(manifest, wid, "FAILED",
                               error=f"max attempts ({config.execution.max_orchestrator_attempts}) exceeded")
                    atomic_write_json(run_dir / MANIFEST_FILENAME,
                                      manifest_to_dict(manifest))
                    continue
                item.instance_id = f"{wid}__attempt_{item.attempt:03d}"
                item.worker_dir = f"workers/{wid}/attempt_{item.attempt:03d}"

            mark_state(manifest, wid, "CLAIMED", claimed_at=_now_iso())
            atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))

            try:
                worker = launch_worker(item, config, run_dir)
                active[wid] = worker
            except Exception as e:
                mark_state(manifest, wid, "FAILED",
                           error=f"launch failed: {e}", finished_at=_now_iso())
                atomic_write_json(run_dir / MANIFEST_FILENAME,
                                  manifest_to_dict(manifest))
                continue

        # Check for CLAIMED -> RUNNING (process alive)
        for wid in list(active.keys()):
            item = manifest.work_items[wid]
            if item.state == "CLAIMED":
                worker = active[wid]
                if worker.process.poll() is None:
                    mark_state(manifest, wid, "RUNNING", started_at=_now_iso())
                else:
                    # Process died immediately
                    worker.stdout_fh.close()
                    worker.stderr_fh.close()
                    mark_state(manifest, wid, "FAILED",
                               finished_at=_now_iso(),
                               exit_code=worker.process.returncode,
                               error=f"exit code {worker.process.returncode} (immediate)")
                    del active[wid]
                atomic_write_json(run_dir / MANIFEST_FILENAME,
                                  manifest_to_dict(manifest))

        # Harvest finished workers
        finished = harvest_finished_workers(active)
        for wid, worker in finished:
            done_count += 1
            worker.stdout_fh.close()
            worker.stderr_fh.close()
            exitcode = worker.process.returncode

            mark_state(manifest, wid, "MERGING",
                       finished_at=_now_iso(), exit_code=exitcode)
            atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))

            if exitcode != 0:
                mark_state(manifest, wid, "FAILED",
                           error=f"exit code {exitcode}",
                           validation={})
                print(
                    f"[{done_count}/{total}] {wid} FAILED: exit code {exitcode}",
                    flush=True,
                )
            else:
                v = validate_worker_artifacts(manifest.work_items[wid], worker.worker_dir)
                if v.ok:
                    merge_worker_events(
                        manifest.work_items[wid], worker.worker_dir,
                        run_dir / MERGED_EVENTS_FILENAME,
                    )
                    mark_state(manifest, wid, "SUCCEEDED",
                               merged_at=_now_iso(),
                               completed_cases=v.completed_cases,
                               validation=v.to_dict())
                    print(
                        f"[{done_count}/{total}] {wid} SUCCEEDED",
                        flush=True,
                    )
                else:
                    mark_state(manifest, wid, "FAILED",
                               error=v.error_summary,
                               validation=v.to_dict())
                    print(
                        f"[{done_count}/{total}] {wid} FAILED: {v.error_summary}",
                        flush=True,
                    )

                # Count errors for rolling summary
                events, _ = parse_events_prefix(worker.worker_dir / EVENTS_FILENAME)
                for e in events:
                    et = e.get("event_type", "")
                    if et.startswith("case.error."):
                        rolling_error_counts[et.replace("case.error.", "")] += 1
                workers_since_error_summary += 1

            atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))

            # Rolling error summary every 10 workers
            if workers_since_error_summary >= 10 and rolling_error_counts:
                parts = ", ".join(f"{c} {t}" for t, c in rolling_error_counts.most_common())
                print(f"  [rolling errors after {done_count} workers: {parts}]", flush=True)
                workers_since_error_summary = 0

        # Timeout check
        for wid, worker in list(active.items()):
            if time.monotonic() - worker.launched_at > timeout_seconds:
                print(f"  TIMEOUT: {wid} after {timeout_seconds}s", flush=True)
                exitcode = timeout_worker(worker, grace_seconds)
                del active[wid]
                done_count += 1
                mark_state(manifest, wid, "MERGING",
                           finished_at=_now_iso(), exit_code=exitcode)
                v = validate_worker_artifacts(manifest.work_items[wid], worker.worker_dir)
                if v.ok:
                    merge_worker_events(
                        manifest.work_items[wid], worker.worker_dir,
                        run_dir / MERGED_EVENTS_FILENAME,
                    )
                    mark_state(manifest, wid, "SUCCEEDED",
                               merged_at=_now_iso(),
                               completed_cases=v.completed_cases,
                               validation=v.to_dict())
                else:
                    mark_state(manifest, wid, "FAILED",
                               error=f"timeout after {timeout_seconds}s; {v.error_summary}",
                               validation=v.to_dict())
                atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))

        # Lock heartbeat
        if time.monotonic() - last_lock_refresh > 60:
            refresh_lock_heartbeat(run_dir)
            last_lock_refresh = time.monotonic()

        # Check if done
        all_terminal = all(
            item.state in ("SUCCEEDED", "FAILED", "ABORTED")
            for item in manifest.work_items.values()
        )
        no_pending = not any(
            item.state == "PENDING" for item in manifest.work_items.values()
        )
        if all_terminal and not active:
            break
        if no_pending and not active:
            break

        time.sleep(0.5)

    # Finalize
    counts = count_by_state(manifest)
    if counts.get("FAILED", 0) > 0:
        manifest.status = "failed"
    else:
        manifest.status = "completed"

    atomic_write_json(run_dir / MANIFEST_FILENAME, manifest_to_dict(manifest))

    # End-of-run error summary
    if rolling_error_counts:
        parts = ", ".join(f"{c} {t}" for t, c in rolling_error_counts.most_common())
        print(f"\nErrors: {parts}", flush=True)
    else:
        print("\nErrors: none", flush=True)

    _print_manifest_summary(manifest)
    print(f"Output: {run_dir}", flush=True)

    return 0 if manifest.status == "completed" else 1


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="T3 Failure-Proof Orchestrator")
    parser.add_argument("--config", required=True, help="Experiment config YAML")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--kill-orphans", action="store_true")
    parser.add_argument("--force-lock-recovery", action="store_true")
    parser.add_argument("--rebuild-merged", action="store_true")
    args = parser.parse_args()

    from core.config.experiment_config import load_config

    config = load_config(args.config)

    print(f"CONFIG: {args.config} (sha={config._config_sha256})", flush=True)
    print(f"  Models: {[m.name for m in config.models.generation]}", flush=True)
    print(f"  Conditions: {list(config.conditions.keys())}", flush=True)
    print(f"  Trials: {config.trials}", flush=True)

    exit_code = run_experiment(config, args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
