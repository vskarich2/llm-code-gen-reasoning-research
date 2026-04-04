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

        progress.append(
            {
                "trial": trial,
                "actual": actual,
                "expected": expected,
                "status": status,
                "metadata_error": metadata_error,
            }
        )

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
    from collections import defaultdict

    m = {}
    n = len(events)
    m["total_jobs"] = total_jobs
    m["completed_jobs"] = n
    m["percent_complete"] = round(100 * n / total_jobs, 2) if total_jobs > 0 else 0

    if n == 0:
        return m

    # Enforce model purity
    models_seen = set(e.get("model") for e in events)
    assert (
        len(models_seen) <= 1
    ), f"compute_metrics received events from multiple models: {models_seen}"

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
            1
            for e in ce
            if e.get("reasoning_correct") is True and e.get("code_correct") is not True
        )
        leg_rate = leg_count / cn

        lucky_count = sum(
            1
            for e in ce
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

            # Per-condition category counts
        cond_cats = defaultdict(int)
        for e in ce:
            cond_cats[e.get("category", "unknown")] += 1

        # Per-condition reasoning quality
        cond_dims = [e for e in ce if e.get("mechanism_identified") is not None]
        n_cd = len(cond_dims)
        reasoning_quality = {}
        if n_cd > 0:
            for dim in ("mechanism_identified", "invariant_identified", "causal_chain_complete",
                         "fix_alignment", "reasoning_code_alignment"):
                correct = sum(1 for e in cond_dims if e.get(dim) == "CORRECT")
                partial = sum(1 for e in cond_dims if e.get(dim) == "PARTIAL")
                wrong = sum(1 for e in cond_dims if e.get(dim) == "WRONG")
                reasoning_quality[dim] = {
                    "correct": round(correct / n_cd, 4),
                    "partial": round(partial / n_cd, 4),
                    "wrong": round(wrong / n_cd, 4),
                }

        # Per-condition confidence
        cond_conf = [e for e in ce if e.get("confidence") is not None]
        n_cc = len(cond_conf)
        confidence_dist = {}
        if n_cc > 0:
            confidence_dist = {
                "HIGH": round(sum(1 for e in cond_conf if e.get("confidence") == "HIGH") / n_cc, 4),
                "MEDIUM": round(sum(1 for e in cond_conf if e.get("confidence") == "MEDIUM") / n_cc, 4),
                "LOW": round(sum(1 for e in cond_conf if e.get("confidence") == "LOW") / n_cc, 4),
            }

        # Per-condition failure rates
        parse_fail = cond_cats.get("parse_failed", 0)
        cls_fail = cond_cats.get("classifier_parse_failed", 0)
        no_reas = cond_cats.get("no_reasoning", 0)

        cond_metrics[cond] = {
            "n": cn,
            "pass_rate": round(pass_rate, 4),
            "leg_rate": round(leg_rate, 4),
            "lucky_fix_rate": round(lucky_rate, 4),
            "exec_reasoning": round(exec_reasoning, 4) if exec_reasoning is not None else None,
            "reasoning_unknown": rc_none,
            # Regime distribution per condition
            "regime_distribution": {
                "true_success": {"count": cond_cats.get("true_success", 0), "pct": round(cond_cats.get("true_success", 0) / cn, 4)},
                "leg": {"count": cond_cats.get("leg", 0), "pct": round(cond_cats.get("leg", 0) / cn, 4)},
                "lucky_fix": {"count": cond_cats.get("lucky_fix", 0), "pct": round(cond_cats.get("lucky_fix", 0) / cn, 4)},
                "true_failure": {"count": cond_cats.get("true_failure", 0), "pct": round(cond_cats.get("true_failure", 0) / cn, 4)},
            },
            # Reasoning quality per condition
            "reasoning_quality": reasoning_quality,
            "reasoning_evaluated": n_cd,
            # Confidence per condition
            "confidence_distribution": confidence_dist,
            # Failure rates per condition
            "parse_failure_rate": round(parse_fail / cn, 4),
            "classifier_failure_rate": round(cls_fail / cn, 4),
            "no_reasoning_rate": round(no_reas / cn, 4),
            # Failure type breakdown per condition
            "failure_type_counts": dict(
                sorted(
                    ((ft, sum(1 for e in ce if e.get("failure_type") == ft))
                     for ft in set(e.get("failure_type") for e in ce if e.get("failure_type"))),
                    key=lambda x: -x[1]
                )
            ),
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
        is_leg = (
            1 if (e.get("reasoning_correct") is True and e.get("code_correct") is not True) else 0
        )
        case_stats[cid]["leg"].append(is_leg)
        is_lucky = (
            1 if (e.get("reasoning_correct") is not True and e.get("code_correct") is True) else 0
        )
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
        bl_events = [
            e for e in events if e.get("case_id") == cid and e.get("condition") == "baseline"
        ]
        lr_events = [
            e for e in events if e.get("case_id") == cid and e.get("condition") == "leg_reduction"
        ]
        if bl_events and lr_events:
            bl_pass = sum(1 for e in bl_events if e.get("pass")) / len(bl_events)
            lr_pass = sum(1 for e in lr_events if e.get("pass")) / len(lr_events)
            case_deltas.append((cid, round(lr_pass - bl_pass, 4)))

    m["top5_leg"] = sorted(case_leg_rates, key=lambda x: -x[1])[:5]
    m["top5_lucky"] = sorted(case_lucky_rates, key=lambda x: -x[1])[:5]
    m["top5_delta"] = sorted(case_deltas, key=lambda x: -x[1])[:5]

    # --- OVERALL RATES ---
    m["pass_rate"] = round(sum(1 for e in events if e.get("pass")) / n, 4)
    overall_leg = sum(
        1 for e in events
        if e.get("reasoning_correct") is True and e.get("code_correct") is not True
    ) / n
    m["leg_rate"] = round(overall_leg, 4)

    # ================================================================
    # SECTION 1 — SYSTEM HEALTH
    # ================================================================
    cats = defaultdict(int)
    for e in events:
        cats[e.get("category", "unknown")] += 1

    m["category_counts"] = dict(cats)
    m["parse_failure_rate"] = round(cats.get("parse_failed", 0) / n, 4)
    m["classifier_parse_failure_rate"] = round(cats.get("classifier_parse_failed", 0) / n, 4)
    m["no_reasoning_rate"] = round(cats.get("no_reasoning", 0) / n, 4)

    # Coverage
    unique_cases = set(e.get("case_id") for e in events)
    m["evaluated_cases"] = len(unique_cases)

    # Latency
    latencies = [e.get("elapsed_seconds") for e in events if e.get("elapsed_seconds") is not None]
    if latencies:
        m["avg_latency"] = round(sum(latencies) / len(latencies), 2)
        m["max_latency"] = round(max(latencies), 2)
    else:
        m["avg_latency"] = None
        m["max_latency"] = None

    # ================================================================
    # SECTION 2 — REGIME DISTRIBUTION
    # ================================================================
    m["true_success_count"] = cats.get("true_success", 0)
    m["leg_count"] = cats.get("leg", 0)
    m["lucky_fix_count"] = cats.get("lucky_fix", 0)
    m["true_failure_count"] = cats.get("true_failure", 0)

    m["true_success_rate"] = round(cats.get("true_success", 0) / n, 4)
    m["lucky_fix_rate"] = round(cats.get("lucky_fix", 0) / n, 4)
    m["true_failure_rate"] = round(cats.get("true_failure", 0) / n, 4)

    # ================================================================
    # SECTION 3 — INTERVENTION TRANSITIONS
    # ================================================================
    # Per-case: baseline category → leg_reduction category
    transitions = defaultdict(int)
    case_bl_cat = {}
    case_lr_cat = {}
    for e in events:
        cid = e.get("case_id")
        cat = e.get("category", "unknown")
        if e.get("condition") == "baseline":
            case_bl_cat[cid] = cat
        elif e.get("condition") == "leg_reduction":
            case_lr_cat[cid] = cat

    for cid in case_bl_cat:
        if cid in case_lr_cat:
            bl_c = case_bl_cat[cid]
            lr_c = case_lr_cat[cid]
            transitions[(bl_c, lr_c)] += 1

    m["transitions"] = {f"{a}->{b}": count for (a, b), count in
                        sorted(transitions.items(), key=lambda x: -x[1])}

    # Key transition metrics
    m["leg_to_success"] = transitions.get(("leg", "true_success"), 0)
    m["failure_to_success"] = transitions.get(("true_failure", "true_success"), 0)
    m["success_to_worse"] = sum(
        transitions.get(("true_success", dest), 0)
        for dest in ("leg", "true_failure", "lucky_fix", "parse_failed", "no_reasoning")
    )

    # ================================================================
    # SECTION 4 — REASONING QUALITY
    # ================================================================
    dims_events = [e for e in events if e.get("mechanism_identified") is not None]
    n_dims = len(dims_events)
    if n_dims > 0:
        for dim in ("mechanism_identified", "invariant_identified", "causal_chain_complete",
                     "fix_alignment", "reasoning_code_alignment"):
            correct = sum(1 for e in dims_events if e.get(dim) == "CORRECT")
            partial = sum(1 for e in dims_events if e.get(dim) == "PARTIAL")
            wrong = sum(1 for e in dims_events if e.get(dim) == "WRONG")
            m[f"{dim}_correct_rate"] = round(correct / n_dims, 4)
            m[f"{dim}_partial_rate"] = round(partial / n_dims, 4)
            m[f"{dim}_wrong_rate"] = round(wrong / n_dims, 4)
        m["reasoning_evaluated_count"] = n_dims
    else:
        m["reasoning_evaluated_count"] = 0

    # 2x2 matrix
    m["matrix_correct_pass"] = cats.get("true_success", 0)
    m["matrix_correct_fail"] = cats.get("leg", 0)
    m["matrix_wrong_pass"] = cats.get("lucky_fix", 0)
    m["matrix_wrong_fail"] = cats.get("true_failure", 0)

    # ================================================================
    # SECTION 5 — CLASSIFIER HEALTH
    # ================================================================
    conf_events = [e for e in events if e.get("confidence") is not None]
    n_conf = len(conf_events)
    if n_conf > 0:
        m["confidence_high_rate"] = round(
            sum(1 for e in conf_events if e.get("confidence") == "HIGH") / n_conf, 4)
        m["confidence_medium_rate"] = round(
            sum(1 for e in conf_events if e.get("confidence") == "MEDIUM") / n_conf, 4)
        m["confidence_low_rate"] = round(
            sum(1 for e in conf_events if e.get("confidence") == "LOW") / n_conf, 4)
    else:
        m["confidence_high_rate"] = None
        m["confidence_medium_rate"] = None
        m["confidence_low_rate"] = None

    # ================================================================
    # SECTION 6 — CASE ANOMALIES (top 5 each)
    # ================================================================
    # LEG cases (reasoning correct + code fail)
    m["anomaly_leg_cases"] = [(cid, r) for cid, r in case_leg_rates if r > 0][:5]
    # Lucky fix cases (reasoning wrong + code pass)
    m["anomaly_lucky_cases"] = [(cid, r) for cid, r in case_lucky_rates if r > 0][:5]
    # Baseline→LEG flips (different pass outcome)
    flips = []
    for cid in sorted(case_bl_cat.keys()):
        if cid not in case_lr_cat:
            continue
        bl_e = next((e for e in events if e.get("case_id") == cid and e.get("condition") == "baseline"), None)
        lr_e = next((e for e in events if e.get("case_id") == cid and e.get("condition") == "leg_reduction"), None)
        if bl_e and lr_e and bl_e.get("pass") != lr_e.get("pass"):
            direction = "BL_pass->LR_fail" if bl_e["pass"] else "BL_fail->LR_pass"
            flips.append((cid, direction))
    m["anomaly_flips"] = flips[:5]

    # ================================================================
    # SECTION 8 — DUAL EXECUTION (infrastructure vs model failure)
    # ================================================================
    # dual_execution case_data may be in top-level event or in extra section
    dual_events = [e for e in events if e.get("dual_execution") is not None
                   or (isinstance(e.get("extra"), dict) and e["extra"].get("dual_execution") is not None)]

    def _get_dual(e):
        d = e.get("dual_execution")
        if d is None and isinstance(e.get("extra"), dict):
            d = e["extra"].get("dual_execution")
        return d or {}

    n_dual = len(dual_events)
    if n_dual > 0:
        agreement = sum(1 for e in dual_events if _get_dual(e).get("agreement"))
        assembly_suspect = sum(1 for e in dual_events if _get_dual(e).get("assembly_suspect"))
        assembly_confirmed = sum(1 for e in dual_events if _get_dual(e).get("assembly_confirmed"))
        module_only_pass = sum(1 for e in dual_events if _get_dual(e).get("module_only_pass"))
        concat_only_pass = sum(1 for e in dual_events if _get_dual(e).get("concat_only_pass"))

        # Disagreement type distribution
        dtype_counts = defaultdict(int)
        for e in dual_events:
            dt = _get_dual(e).get("disagreement_type", "none")
            dtype_counts[dt] += 1

        m["dual_execution"] = {
            "n": n_dual,
            "agreement_rate": round(agreement / n_dual, 4),
            "assembly_suspect_rate": round(assembly_suspect / n_dual, 4),
            "assembly_confirmed_rate": round(assembly_confirmed / n_dual, 4),
            "module_only_pass_rate": round(module_only_pass / n_dual, 4),
            "concat_only_pass_rate": round(concat_only_pass / n_dual, 4),
            "disagreement_type_counts": dict(dtype_counts),
        }

        # LEG adjustment (conservative — removes only assembly_confirmed)
        evaluated = [e for e in dual_events if e.get("reasoning_correct") is not None]
        n_eval = len(evaluated)
        if n_eval > 0:
            leg_raw = sum(1 for e in evaluated
                          if e.get("reasoning_correct") is True and e.get("pass") is False)
            leg_adjusted = sum(1 for e in evaluated
                               if e.get("reasoning_correct") is True
                               and e.get("pass") is False
                               and not _get_dual(e).get("assembly_confirmed"))
            leg_broad = sum(1 for e in evaluated
                            if e.get("reasoning_correct") is True
                            and e.get("pass") is False
                            and not _get_dual(e).get("assembly_suspect"))

            leg_raw_rate = round(leg_raw / n_eval, 4) if n_eval else 0
            leg_adj_rate = round(leg_adjusted / n_eval, 4) if n_eval else 0
            leg_broad_rate = round(leg_broad / n_eval, 4) if n_eval else 0
            infra_conservative = leg_raw_rate - leg_adj_rate
            bias_conservative = round(infra_conservative / leg_raw_rate, 4) if leg_raw_rate > 0 else 0

            m["dual_execution"]["LEG_raw"] = leg_raw_rate
            m["dual_execution"]["LEG_adjusted_conservative"] = leg_adj_rate
            m["dual_execution"]["LEG_adjusted_broad"] = leg_broad_rate
            m["dual_execution"]["LEG_infrastructure_conservative"] = round(infra_conservative, 4)
            m["dual_execution"]["assembly_bias_conservative"] = bias_conservative
            m["dual_execution"]["n_evaluated"] = n_eval

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
        errors.append(f"overall pass_rate == 0 for {model} ({completed} evals).")

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
    """Write 7-section research dashboard to file atomically."""
    lines = []
    w = lines.append

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    completed = metrics.get("completed_jobs", 0)
    total = metrics.get("total_jobs", "?")
    pct = metrics.get("percent_complete", 0)

    w("=" * 78)
    w("  T3 LIVE METRICS DASHBOARD")
    w(f"  Updated: {now}    Progress: {completed}/{total} ({pct:.1f}%)")
    w("=" * 78)

    # --- TRIAL PROGRESS ---
    trial_progress = metrics.get("trial_progress", [])
    if trial_progress:
        complete_count = sum(1 for t in trial_progress if t["status"] == "COMPLETE")
        total_trials = len(trial_progress)
        w(f"  Trials: {complete_count}/{total_trials} complete")

    if completed == 0:
        w("  (no events yet)")
        w("=" * 78)
        _write_atomic(lines, dashboard_path)
        return

    cond_metrics = metrics.get("condition_metrics", {})

    # ==================================================================
    # SECTION 1 — SYSTEM HEALTH
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S1: SYSTEM HEALTH")
    w("─" * 78)

    pf = metrics.get("parse_failure_rate", 0)
    cf = metrics.get("classifier_parse_failure_rate", 0)
    nr = metrics.get("no_reasoning_rate", 0)
    health_ok = pf < 0.05 and cf < 0.05 and nr < 0.05

    w(f"  parse_failure:      {pf:>7.2%}  {'OK' if pf < 0.05 else 'ALERT >5%'}")
    w(f"  classifier_failure: {cf:>7.2%}  {'OK' if cf < 0.05 else 'ALERT >5%'}")
    w(f"  no_reasoning:       {nr:>7.2%}  {'OK' if nr < 0.05 else 'ALERT >5%'}")
    w(f"  coverage:           {metrics.get('evaluated_cases', 0)} cases evaluated")
    avg_lat = metrics.get("avg_latency")
    if avg_lat is not None:
        w(f"  avg_latency:        {avg_lat:.1f}s   max: {metrics.get('max_latency', 0):.1f}s")
    w(f"  status:             {'HEALTHY' if health_ok else 'DEGRADED'}")

    # Per-condition failure rates
    if cond_metrics:
        w("")
        w(f"  {'Condition':<20} {'Parse':>8} {'Cls.Fail':>8} {'NoReas':>8}")
        w(f"  {'─' * 48}")
        for cond, cm in sorted(cond_metrics.items()):
            w(f"  {cond:<20} {cm.get('parse_failure_rate',0):>7.2%} "
              f"{cm.get('classifier_failure_rate',0):>7.2%} "
              f"{cm.get('no_reasoning_rate',0):>7.2%}")

    # ==================================================================
    # SECTION 2 — REGIME DISTRIBUTION
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S2: REGIME DISTRIBUTION")
    w("─" * 78)

    ts = metrics.get("true_success_count", 0)
    lg = metrics.get("leg_count", 0)
    lf = metrics.get("lucky_fix_count", 0)
    tf = metrics.get("true_failure_count", 0)

    w(f"  true_success:  {ts:>4}  ({metrics.get('true_success_rate',0):>7.2%})")
    w(f"  LEG:           {lg:>4}  ({metrics.get('leg_rate',0):>7.2%})")
    w(f"  lucky_fix:     {lf:>4}  ({metrics.get('lucky_fix_rate',0):>7.2%})")
    w(f"  true_failure:  {tf:>4}  ({metrics.get('true_failure_rate',0):>7.2%})")

    # Signal check
    signals = []
    if lg == 0:
        signals.append("LEG=0 — classifier may be broken")
    if lf == 0 and completed > 10:
        signals.append("lucky_fix=0 — reasoning eval may not be working")
    if ts / completed > 0.9 and completed > 10:
        signals.append("true_success >90% — check difficulty")
    if signals:
        for s in signals:
            w(f"  WARNING: {s}")

    # Per-condition regime
    if cond_metrics:
        w("")
        w(f"  {'Condition':<20} {'N':>5} {'Pass':>7} {'LEG':>7} {'Lucky':>7} {'Fail':>7}")
        w(f"  {'─' * 58}")
        for cond, cm in sorted(cond_metrics.items()):
            rd = cm.get("regime_distribution", {})
            w(f"  {cond:<20} {cm['n']:>5} "
              f"{rd.get('true_success',{}).get('pct',0):>6.2%} "
              f"{rd.get('leg',{}).get('pct',0):>6.2%} "
              f"{rd.get('lucky_fix',{}).get('pct',0):>6.2%} "
              f"{rd.get('true_failure',{}).get('pct',0):>6.2%}")

    # ==================================================================
    # SECTION 3 — INTERVENTION EFFECT
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S3: INTERVENTION EFFECT")
    w("─" * 78)

    if "delta_pass" in metrics:
        dp = metrics["delta_pass"]
        dl = metrics.get("delta_leg", 0)
        dlk = metrics.get("delta_lucky", 0)
        w(f"  delta_pass:   {dp:>+.4f}  {'HELPS' if dp > 0.05 else 'HURTS' if dp < -0.05 else 'NEUTRAL'}")
        w(f"  delta_leg:    {dl:>+.4f}")
        w(f"  delta_lucky:  {dlk:>+.4f}")
        w(f"  regime:       {metrics.get('regime', 'N/A')}")
    else:
        w("  (need both baseline and leg_reduction for deltas)")

    # Transitions
    trans = metrics.get("transitions", {})
    if trans:
        w("")
        w("  Transitions (baseline -> intervention):")
        l2s = metrics.get("leg_to_success", 0)
        f2s = metrics.get("failure_to_success", 0)
        s2w = metrics.get("success_to_worse", 0)
        w(f"    LEG -> true_success:      {l2s:>3}  {'GOOD' if l2s > 0 else ''}")
        w(f"    true_failure -> success:   {f2s:>3}  {'GOOD' if f2s > 0 else ''}")
        w(f"    true_success -> worse:     {s2w:>3}  {'BAD' if s2w > 0 else ''}")
        w("")
        w("  All transitions:")
        for t, count in sorted(trans.items(), key=lambda x: -x[1]):
            w(f"    {t:<40s} {count:>3}")

    # ==================================================================
    # SECTION 4 — REASONING QUALITY
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S4: REASONING QUALITY")
    w("─" * 78)

    n_eval = metrics.get("reasoning_evaluated_count", 0)
    w(f"  evaluated: {n_eval}/{completed}")
    if n_eval > 0:
        w("")
        w(f"  {'Dimension':<30s} {'CORRECT':>8} {'PARTIAL':>8} {'WRONG':>8}")
        w(f"  {'─' * 56}")
        for dim in ("mechanism_identified", "invariant_identified", "causal_chain_complete",
                     "fix_alignment", "reasoning_code_alignment"):
            cr = metrics.get(f"{dim}_correct_rate", 0)
            pr = metrics.get(f"{dim}_partial_rate", 0)
            wr = metrics.get(f"{dim}_wrong_rate", 0)
            w(f"  {dim:<30s} {cr:>7.2%} {pr:>7.2%} {wr:>7.2%}")

    # 2x2 matrix
    w("")
    w("  Reasoning x Execution Matrix:")
    w(f"  {'':20s} {'code PASS':>12} {'code FAIL':>12}")
    w(f"  {'reasoning CORRECT':<20s} {metrics.get('matrix_correct_pass',0):>12} {metrics.get('matrix_correct_fail',0):>12}")
    w(f"  {'reasoning WRONG':<20s} {metrics.get('matrix_wrong_pass',0):>12} {metrics.get('matrix_wrong_fail',0):>12}")

    # Per-condition reasoning quality
    if cond_metrics:
        for cond, cm in sorted(cond_metrics.items()):
            rq = cm.get("reasoning_quality", {})
            if rq:
                w(f"")
                w(f"  {cond} ({cm.get('reasoning_evaluated',0)} evaluated):")
                for dim, vals in rq.items():
                    w(f"    {dim:<28s} C={vals['correct']:>5.2%}  P={vals['partial']:>5.2%}  W={vals['wrong']:>5.2%}")

    # ==================================================================
    # SECTION 5 — CLASSIFIER HEALTH
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S5: CLASSIFIER HEALTH")
    w("─" * 78)

    ch = metrics.get("confidence_high_rate")
    if ch is not None:
        cm_rate = metrics.get("confidence_medium_rate", 0)
        cl = metrics.get("confidence_low_rate", 0)
        w(f"  HIGH:   {ch:>7.2%}")
        w(f"  MEDIUM: {cm_rate:>7.2%}")
        w(f"  LOW:    {cl:>7.2%}")
        if ch > 0.9:
            w("  WARNING: >90% HIGH — classifier may be too lenient")
        if cl > 0.3:
            w("  WARNING: >30% LOW — classifier may be confused")
    else:
        w("  (no classifier results yet)")

    # Per-condition confidence
    if cond_metrics:
        w("")
        w(f"  {'Condition':<20} {'HIGH':>8} {'MEDIUM':>8} {'LOW':>8}")
        w(f"  {'─' * 48}")
        for cond, cm_data in sorted(cond_metrics.items()):
            cd = cm_data.get("confidence_distribution", {})
            if cd:
                w(f"  {cond:<20} {cd.get('HIGH',0):>7.2%} {cd.get('MEDIUM',0):>7.2%} {cd.get('LOW',0):>7.2%}")

    # ==================================================================
    # SECTION 6 — CASE ANOMALIES
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S6: CASE ANOMALIES")
    w("─" * 78)

    anomaly_leg = metrics.get("anomaly_leg_cases", [])
    anomaly_lucky = metrics.get("anomaly_lucky_cases", [])
    anomaly_flips = metrics.get("anomaly_flips", [])

    if anomaly_leg:
        w("  LEG cases (reasoning correct, code wrong):")
        for cid, rate in anomaly_leg:
            w(f"    {cid:<36s} {rate:>6.2%}")

    if anomaly_lucky:
        w("  Lucky fix cases (reasoning wrong, code correct):")
        for cid, rate in anomaly_lucky:
            w(f"    {cid:<36s} {rate:>6.2%}")

    if anomaly_flips:
        w("  Baseline/LEG flips (different pass outcome):")
        for cid, direction in anomaly_flips:
            w(f"    {cid:<36s} {direction}")

    if not anomaly_leg and not anomaly_lucky and not anomaly_flips:
        w("  (no anomalies detected)")

    # ==================================================================
    # SECTION 7 — FAILURE TYPE BREAKDOWN
    # ==================================================================
    w("")
    w("─" * 78)
    w("  S7: FAILURE TYPE BREAKDOWN")
    w("─" * 78)

    if cond_metrics:
        for cond, cm_data in sorted(cond_metrics.items()):
            ftc = cm_data.get("failure_type_counts", {})
            if ftc:
                w(f"  {cond}:")
                for ft, count in ftc.items():
                    w(f"    {ft:<30s} {count:>4}")
                w("")

    # ==================================================================
    # SECTION 8 — DUAL EXECUTION
    # ==================================================================
    dual = metrics.get("dual_execution")
    if dual and dual.get("n", 0) > 0:
        w("")
        w("─" * 78)
        w("  S8: DUAL EXECUTION (infrastructure vs model failure)")
        w("─" * 78)
        w(f"  events with dual data: {dual['n']}")
        w(f"  agreement rate:          {dual['agreement_rate']:>7.1%}")
        w(f"  assembly suspect rate:   {dual['assembly_suspect_rate']:>7.1%}  (concat fail, module pass)")
        w(f"  assembly confirmed rate: {dual['assembly_confirmed_rate']:>7.1%}  (high-confidence infra error)")
        w(f"  module only pass rate:   {dual['module_only_pass_rate']:>7.1%}")
        w(f"  concat only pass rate:   {dual['concat_only_pass_rate']:>7.1%}")

        if "LEG_raw" in dual:
            w("")
            w(f"  LEG raw:                 {dual['LEG_raw']:>7.1%}")
            w(f"  LEG adjusted (conserv.): {dual['LEG_adjusted_conservative']:>7.1%}  (removes confirmed infra)")
            w(f"  LEG adjusted (broad):    {dual['LEG_adjusted_broad']:>7.1%}  (removes all suspects — EXPLORATORY)")
            w(f"  infrastructure bias:     {dual['assembly_bias_conservative']:>7.1%}  (fraction of LEG from infra)")

        dtypes = dual.get("disagreement_type_counts", {})
        if dtypes:
            w("")
            w("  disagreement types:")
            for dt, count in sorted(dtypes.items(), key=lambda x: -x[1]):
                w(f"    {dt:<35s} {count:>4}")

    # ==================================================================
    # FOOTER
    # ==================================================================
    w("─" * 78)
    w(f"  CI: {metrics.get('ci_status', 'N/A')}  |  "
      f"Stable: {metrics.get('stable_cases', 0)}  Unstable: {metrics.get('unstable_cases', 0)}  |  "
      f"Figures: {metrics.get('figure_readiness', 'NOT READY')}")
    w("=" * 78)
    w(f"  END — {completed}/{total} eval calls")
    w("=" * 78)

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
