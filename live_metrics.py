"""Live metrics for T3 ablation experiments — process-based architecture.

Architecture:
  - Each worker process writes events to its own events.jsonl via emit_event()
  - A separate dashboard process (scripts/update_dashboards.py) scans run dirs
    every 30 seconds, aggregates events, and writes per-model dashboards
  - No shared mutable state. No threads. No queues. No sinks.

Key functions:
  emit_event()              — validate + write one event (worker process)
  read_events_safe()        — read events from a single file (skip corrupt lines)
  aggregate_model_events()  — discover + read all events for a model
  compute_metrics()         — pure function: events list → metrics dict
  compute_trial_progress()  — per-trial completion status
  write_dashboard()         — atomic dashboard file write
"""

import glob
import json
import logging
import os
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("t3.live_metrics")

# ============================================================
# EVENT SCHEMA
# ============================================================

REQUIRED_EVENT_KEYS = {"model", "trial", "run_id", "case_id", "condition", "timestamp"}

FIELD_TYPES = {
    "model": str,
    "trial": int,
    "run_id": str,
    "case_id": str,
    "condition": str,
    "timestamp": str,
}


# ============================================================
# EVENT EMITTER (called from worker processes)
# ============================================================

def emit_event(event: dict, events_path: Path) -> None:
    """Validate and write one event to events_path. Durable (fsync).

    Opens/closes file per call. No buffered I/O. Raw OS calls.
    Raises ValueError on schema/type violation (hard crash of worker).
    """
    # Inject timestamp
    event["timestamp"] = datetime.now().isoformat()

    # Validate required keys
    missing = REQUIRED_EVENT_KEYS - event.keys()
    if missing:
        raise ValueError(f"Event missing required keys: {missing}")

    # Validate field types
    for key, expected_type in FIELD_TYPES.items():
        if not isinstance(event[key], expected_type):
            raise ValueError(
                f"Event field '{key}' must be {expected_type.__name__}, "
                f"got {type(event[key]).__name__}"
            )

    line = json.dumps(event, default=str) + "\n"
    fd = os.open(str(events_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


# ============================================================
# SAFE EVENT FILE READER
# ============================================================

def read_events_safe(events_path: Path) -> list[dict]:
    """Read all valid events from a JSONL file. Skip corrupt/incomplete lines.

    - Reads entire file as a snapshot (f.read())
    - Splits on newline boundaries
    - Each line parsed independently; JSONDecodeError → skip
    - Never crashes due to malformed input
    """
    if not events_path.exists():
        return []

    try:
        with open(events_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        _log.error("Failed to read %s: %s", events_path, e)
        return []

    events = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            events.append(event)
        except json.JSONDecodeError:
            # Incomplete trailing line or corrupted — skip silently.
            # Will be picked up next cycle if mid-write.
            continue
    return events


# ============================================================
# RUN DIRECTORY DISCOVERY + AGGREGATION
# ============================================================

def aggregate_model_events(model: str, ablation_dir: Path) -> list[dict]:
    """Discover all run directories for a model and read their events.

    - Skips directories without events.jsonl
    - Returns flat list of all valid events across all trials
    """
    pattern = str(ablation_dir / f"run_{model}_t*")
    dirs = sorted(glob.glob(pattern))

    all_events = []
    for d in dirs:
        d_path = Path(d)
        events_path = d_path / "events.jsonl"
        if not events_path.exists():
            # Directory exists but no events file yet — skip
            continue
        events = read_events_safe(events_path)
        all_events.extend(events)

    return all_events


# ============================================================
# TRIAL PROGRESS
# ============================================================

def compute_trial_progress(model: str, ablation_dir: Path, n_trials: int) -> list[dict]:
    """Compute per-trial completion status for a model.

    Returns list of dicts with: trial, actual, expected, status.
    """
    pattern = str(ablation_dir / f"run_{model}_t*")
    dirs = sorted(glob.glob(pattern))

    progress = []
    for d in dirs:
        d_path = Path(d)
        events_path = d_path / "events.jsonl"
        metadata_path = d_path / "metadata.json"

        # Extract trial number from directory name
        dir_name = d_path.name
        try:
            # Format: run_{model}_t{trial}_{uuid}
            parts = dir_name.split("_t")
            trial_part = parts[-1].split("_")[0]
            trial = int(trial_part)
        except (IndexError, ValueError):
            trial = -1

        if not events_path.exists():
            continue

        events = read_events_safe(events_path)
        actual = len(events)

        # Read expected from metadata
        expected = 0
        metadata_error = None
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                expected = metadata.get("total_jobs", 0)
            except (json.JSONDecodeError, OSError) as e:
                metadata_error = str(e)

        if metadata_error:
            status = "ERROR"
        elif expected > 0 and actual >= expected:
            status = "COMPLETE"
        elif actual > 0:
            status = "IN_PROGRESS"
        else:
            status = "NOT_STARTED"

        progress.append({
            "trial": trial,
            "actual": actual,
            "expected": expected,
            "status": status,
            "metadata_error": metadata_error,
        })

    return progress


# ============================================================
# METRICS COMPUTATION (pure function)
# ============================================================

def compute_metrics(events: list[dict], total_jobs: int) -> dict:
    """Compute all dashboard metrics from a flat event list.

    Pure function — no side effects, no state.
    Events must all be for the same model (asserted).

    NOTE: Metrics are computed at the EVENT LEVEL (not case-aggregated).
    These may differ from paper results which use case-level aggregation.
    """
    m = {}
    n = len(events)
    m["total_jobs"] = total_jobs
    m["completed_jobs"] = n
    m["percent_complete"] = round(100 * n / total_jobs, 2) if total_jobs > 0 else 0

    if n == 0:
        return m

    # Enforce model purity
    models_seen = set(e.get("model") for e in events)
    assert len(models_seen) <= 1, (
        f"compute_metrics received events from multiple models: {models_seen}"
    )

    # Enforce required metric fields
    for e in events:
        if "pass" not in e:
            raise RuntimeError(
                f"Missing 'pass' field in event: case_id={e.get('case_id')}, "
                f"condition={e.get('condition')}, trial={e.get('trial')}"
            )

    # --- PER-CONDITION METRICS ---
    conditions = sorted(set(e.get("condition", "?") for e in events))

    cond_metrics = {}
    for cond in conditions:
        ce = [e for e in events if e.get("condition") == cond]
        cn = len(ce)
        if cn == 0:
            continue

        # PRIMARY METRIC: pass rate (from code execution — trustworthy)
        pass_rate = sum(1 for e in ce if e.get("pass")) / cn

        # SECONDARY: reasoning-derived metrics (UNRELIABLE — classifier disqualified
        # per Phase 0 reasoning_evaluator_audit. Kept for informational purposes only. Do NOT use for
        # scientific conclusions.)
        leg_count = sum(
            1 for e in ce
            if e.get("reasoning_correct") is True and e.get("code_correct") is not True
        )
        leg_rate = leg_count / cn

        lucky_count = sum(
            1 for e in ce
            if e.get("reasoning_correct") is not True and e.get("code_correct") is True
        )
        lucky_rate = lucky_count / cn

        reasoning_correct_events = [e for e in ce if e.get("reasoning_correct") is True]
        if reasoning_correct_events:
            exec_reasoning = sum(
                1 for e in reasoning_correct_events if e.get("code_correct") is True
            ) / len(reasoning_correct_events)
        else:
            exec_reasoning = None

        # Count how many events have reasoning_correct=None (parse failures / gated)
        rc_none = sum(1 for e in ce if e.get("reasoning_correct") is None)

        cond_metrics[cond] = {
            "n": cn,
            "pass_rate": round(pass_rate, 4),
            # Reasoning-derived (UNRELIABLE — see reasoning_evaluator_audit/phase0_report.md)
            "leg_rate": round(leg_rate, 4),
            "lucky_fix_rate": round(lucky_rate, 4),
            "exec_reasoning": round(exec_reasoning, 4) if exec_reasoning is not None else None,
            "reasoning_unknown": rc_none,
        }

    m["condition_metrics"] = cond_metrics

    # --- DELTAS (baseline vs leg_reduction) ---
    bl = cond_metrics.get("baseline", {})
    lr = cond_metrics.get("leg_reduction", {})
    if bl and lr:
        m["delta_pass"] = round(lr["pass_rate"] - bl["pass_rate"], 4)
        m["delta_leg"] = round(lr["leg_rate"] - bl["leg_rate"], 4)
        m["delta_lucky"] = round(lr["lucky_fix_rate"] - bl["lucky_fix_rate"], 4)

    # --- CI STATUS ---
    min_n = min(cm["n"] for cm in cond_metrics.values()) if cond_metrics else 0
    m["ci_status"] = "CI NOT STABLE" if min_n < 10 else "SE computed"

    # --- CASE STABILITY ---
    # Per (case_id, condition): count distinct pass values across trials
    from collections import defaultdict
    case_cond_passes = defaultdict(set)
    for e in events:
        key = (e.get("case_id"), e.get("condition"))
        case_cond_passes[key].add(bool(e.get("pass")))

    disagreements = sum(1 for vals in case_cond_passes.values() if len(vals) > 1)
    stable = sum(1 for vals in case_cond_passes.values() if len(vals) == 1)
    m["stable_cases"] = stable
    m["unstable_cases"] = disagreements

    # --- REGIME CLASSIFICATION ---
    # Based on code_correct only (reasoning classifier is unreliable)
    delta_pass = m.get("delta_pass", 0)
    overall_pass = m.get("pass_rate", 0)

    if overall_pass < 0.5:
        m["regime"] = "LOW-PASS"
    elif abs(delta_pass) < 0.05:
        m["regime"] = "NEUTRAL"
    elif delta_pass > 0.05:
        m["regime"] = "INTERVENTION-HELPS"
    else:
        m["regime"] = "INTERVENTION-HURTS"

    # --- FIGURE READINESS ---
    # (set by dashboard from trial_progress, not computed here)
    m["figure_readiness"] = "NOT READY"

    # --- TOP CASES ---
    case_stats = defaultdict(lambda: {"pass": [], "leg": [], "lucky": []})
    for e in events:
        cid = e.get("case_id", "?")
        case_stats[cid]["pass"].append(1 if e.get("pass") else 0)
        is_leg = 1 if (e.get("reasoning_correct") is True and e.get("code_correct") is not True) else 0
        case_stats[cid]["leg"].append(is_leg)
        is_lucky = 1 if (e.get("reasoning_correct") is not True and e.get("code_correct") is True) else 0
        case_stats[cid]["lucky"].append(is_lucky)

    # Sort case_ids for deterministic ordering
    sorted_cases = sorted(case_stats.keys())

    def _mean(lst):
        return sum(lst) / len(lst) if lst else 0

    case_leg_rates = [(cid, _mean(case_stats[cid]["leg"])) for cid in sorted_cases]
    case_lucky_rates = [(cid, _mean(case_stats[cid]["lucky"])) for cid in sorted_cases]

    # Intervention delta per case
    case_deltas = []
    for cid in sorted_cases:
        bl_events = [e for e in events if e.get("case_id") == cid and e.get("condition") == "baseline"]
        lr_events = [e for e in events if e.get("case_id") == cid and e.get("condition") == "leg_reduction"]
        if bl_events and lr_events:
            bl_pass = sum(1 for e in bl_events if e.get("pass")) / len(bl_events)
            lr_pass = sum(1 for e in lr_events if e.get("pass")) / len(lr_events)
            case_deltas.append((cid, round(lr_pass - bl_pass, 4)))

    m["top5_leg"] = sorted(case_leg_rates, key=lambda x: -x[1])[:5]
    m["top5_lucky"] = sorted(case_lucky_rates, key=lambda x: -x[1])[:5]
    m["top5_delta"] = sorted(case_deltas, key=lambda x: -x[1])[:5]

    # --- OVERALL RATES ---
    m["pass_rate"] = round(sum(1 for e in events if e.get("pass")) / n, 4)
    m["leg_rate"] = round(overall_leg, 4)

    return m


# ============================================================
# DASHBOARD GUARDS
# ============================================================

def validate_metrics(metrics: dict, model: str) -> list[str]:
    """Post-computation validation. Returns list of warnings.

    Raises RuntimeError for degenerate metrics that indicate pipeline failure.
    """
    completed = metrics.get("completed_jobs", 0)
    if completed < 10:
        return []

    errors = []
    cond_metrics = metrics.get("condition_metrics", {})
    all_zero_pass = all(cm.get("pass_rate", 0) == 0 for cm in cond_metrics.values())
    if all_zero_pass and cond_metrics:
        errors.append(
            f"pass_rate == 0 across ALL conditions for {model} "
            f"({completed} events). Pipeline is likely broken."
        )

    if metrics.get("pass_rate", 0) == 0:
        errors.append(
            f"overall pass_rate == 0 for {model} ({completed} evals)."
        )

    return errors


# ============================================================
# FORMATTING HELPERS
# ============================================================

def _fmt_pct(val, width=8):
    if val is None:
        return "   N/A".ljust(width)
    return f"{val * 100:>{width}.2f}%"


def _fmt_num(val, width=8):
    if val is None:
        return "   N/A".ljust(width)
    return f"{val:>{width}}"


# ============================================================
# DASHBOARD WRITER
# ============================================================

def write_dashboard(metrics: dict, dashboard_path: Path) -> None:
    """Write dashboard to file atomically (temp + fsync + replace)."""
    lines = []
    w = lines.append

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 72)
    w("  LIVE METRICS DASHBOARD")
    w(f"  Last updated: {now}")
    w("=" * 72)
    w("")
    w("  NOTE: Metrics are computed at the EVENT LEVEL (not case-aggregated).")
    w("  These may differ from paper results which use case-level aggregation.")
    w("")

    # --- PROGRESS ---
    w("[PROGRESS]")
    completed = metrics.get("completed_jobs", 0)
    total = metrics.get("total_jobs", "?")
    pct = metrics.get("percent_complete", 0)
    w(f"  Completed:  {completed} / {total} eval calls  ({pct:.1f}%)")
    w("")

    # --- TRIAL PROGRESS ---
    trial_progress = metrics.get("trial_progress", [])
    if trial_progress:
        complete_count = sum(1 for t in trial_progress if t["status"] == "COMPLETE")
        total_trials = len(trial_progress)
        w(f"  Completed trials: {complete_count} / {total_trials}")
        for t in sorted(trial_progress, key=lambda x: x["trial"]):
            status = t["status"]
            actual = t["actual"]
            expected = t["expected"]
            w(f"    Trial {t['trial']}: {actual:>3}/{expected} {status}")
        w("")

    if completed == 0:
        w("  (no events yet)")
        w("")
        w("=" * 72)
        _write_atomic(lines, dashboard_path)
        return

    # --- CONDITION COMPARISON ---
    cond_metrics = metrics.get("condition_metrics", {})
    if cond_metrics:
        w("[CONDITION COMPARISON]")
        w("  Pass  = code passes execution tests (PRIMARY — trustworthy)")
        w("  LEG   = reasoning correct but code wrong (UNRELIABLE — classifier disqualified)")
        w("  Lucky = code correct but reasoning wrong (UNRELIABLE — classifier disqualified)")
        w("  E|R   = P(code correct | reasoning correct) (UNRELIABLE)")
        w("  NOTE: LEG/Lucky/E|R depend on reasoning classifier which failed Phase 0 controls.")
        w("        See reasoning_evaluator_audit/phase0_report.md. Only Pass rate is scientifically valid.")
        w("")
        w(f"  {'Condition':<20} {'N':>5} {'Pass':>8} {'LEG':>8} {'Lucky':>8} {'E|R':>8}")
        w(f"  {'─' * 60}")
        for cond, cm in sorted(cond_metrics.items()):
            er = f"{cm['exec_reasoning']:.4f}" if cm["exec_reasoning"] is not None else "N/A"
            w(f"  {cond:<20} {cm['n']:>5} {cm['pass_rate']:>7.4f} {cm['leg_rate']:>7.4f} "
              f"{cm['lucky_fix_rate']:>7.4f} {er:>8}")
        w("")

    # --- DELTAS ---
    if "delta_pass" in metrics:
        w("[DELTAS (leg_reduction - baseline)]")
        w("  How much the leg_reduction intervention changed each rate vs baseline.")
        w(f"  Pass:  {metrics['delta_pass']:+.4f}  (PRIMARY — trustworthy)")
        w(f"  LEG:   {metrics['delta_leg']:+.4f}  (UNRELIABLE)")
        w(f"  Lucky: {metrics['delta_lucky']:+.4f}  (UNRELIABLE)")
        w("")

    # --- CI STATUS ---
    w(f"[CI STATUS] {metrics.get('ci_status', 'N/A')}")
    w("  Whether enough samples exist per condition to compute standard errors.")
    w("  'SE computed' = ≥10 events per condition. 'CI NOT STABLE' = <10.")
    w("")

    # --- STABILITY ---
    w("[CASE STABILITY]")
    w("  A case is 'stable' if it passes or fails consistently across all trials.")
    w("  'Unstable' = mixed pass/fail across trials (nondeterministic).")
    w(f"  Stable cases:   {metrics.get('stable_cases', 0)}")
    w(f"  Unstable cases: {metrics.get('unstable_cases', 0)}")
    w("")

    # --- REGIME ---
    w(f"[REGIME CLASSIFICATION] {metrics.get('regime', 'N/A')}")
    w("  EXECUTION-LIMITED = LEG >15%: models reason correctly but fail to produce")
    w("    correct code. The bottleneck is code generation, not understanding.")
    w("  ALIGNED = LEG <10% and pass delta >5%: reasoning and code quality track.")
    w("  MIXED = neither pattern dominates.")
    w("")

    # --- TOP CASES ---
    for label, key, desc in [
        ("LEG Rate", "top5_leg",
         "Cases with the highest reasoning-correct-but-code-wrong rate."),
        ("Lucky Fix Rate", "top5_lucky",
         "Cases with the highest code-correct-but-reasoning-wrong rate."),
        ("Intervention Delta", "top5_delta",
         "Cases where leg_reduction improved pass rate the most vs baseline."),
    ]:
        top = metrics.get(key, [])
        if top:
            w(f"[TOP 5 — {label}]")
            w(f"  {desc}")
            for cid, val in top:
                w(f"  {cid:<36} {val:>8.4f}")
            w("")

    # --- FIGURE READINESS ---
    w(f"[FIGURE READINESS] {metrics.get('figure_readiness', 'NOT READY')}")
    w("  READY = all trials complete. PRELIMINARY = ≥1 trial done. NOT READY = none.")
    w("")

    # --- PAPER FIGURES + STATS PREVIEW ---
    w("[PAPER FIGURES + STATS PREVIEW]")
    if cond_metrics:
        for cond, cm in sorted(cond_metrics.items()):
            w(f"  {cond}:")
            w(f"    Pass rate:  {cm['pass_rate']:.4f}")
            w(f"    LEG rate:   {cm['leg_rate']:.4f}")
            w(f"    Lucky fix:  {cm['lucky_fix_rate']:.4f}")
            er_str = f"{cm['exec_reasoning']:.4f}" if cm['exec_reasoning'] is not None else "N/A"
            w(f"    Exec|Reas:  {er_str}")
    w("")

    w("=" * 72)
    w(f"  END — {completed}/{total} eval calls")
    w("=" * 72)

    _write_atomic(lines, dashboard_path)


def _write_atomic(lines: list[str], dashboard_path: Path) -> None:
    """Write lines to temp file, fsync, then atomic replace."""
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    tmp_path = dashboard_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(dashboard_path))
    except OSError as e:
        _log.error("Dashboard write failed: %s", e)
