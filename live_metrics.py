"""Live streaming metrics dashboard for T3 ablation experiments.

Architecture:
  - Workers write events to logs/events.jsonl (append-only, one JSON per line)
  - Aggregator thread reads events, computes metrics, writes dashboard
  - Dashboard written atomically via temp file + rename

Usage:
  # In runner.py — start before run, stop after:
  from live_metrics import start_dashboard, stop_dashboard, emit_event
  start_dashboard(total_jobs=N)
  ...  # emit_event() called from execution pipeline
  stop_dashboard()

  # Monitor from terminal:
  watch -n5 cat logs/live_metrics_dashboard.txt
"""

import json
import logging
import os
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev

_log = logging.getLogger("t3.live_metrics")

BASE_DIR = Path(__file__).parent
EVENTS_PATH = BASE_DIR / "logs" / "events.jsonl"
DASHBOARD_PATH = BASE_DIR / "logs" / "live_metrics_dashboard.txt"
DASHBOARD_TMP = BASE_DIR / "logs" / "live_metrics_dashboard.tmp"

REFRESH_INTERVAL = 30  # seconds


# ============================================================
# EVENT EMITTER (called from worker threads)
# ============================================================

_events_lock = threading.Lock()


def emit_event(event: dict) -> None:
    """Append one event to the events log. Thread-safe.

    Required fields: case_id, model, condition, pass.
    All other fields are optional but recommended.
    """
    event["timestamp"] = datetime.now().isoformat()
    line = json.dumps(event, default=str) + "\n"
    with _events_lock:
        try:
            with open(EVENTS_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            _log.error("EVENT WRITE FAILED: %s", e)


# ============================================================
# AGGREGATOR STATE
# ============================================================

class MetricsState:
    """In-memory aggregation of all events."""

    def __init__(self, total_jobs: int = 0):
        self.total_jobs = total_jobs
        self.start_time = time.monotonic()
        self.events: list[dict] = []
        self.file_offset = 0  # byte offset for incremental reads

    def ingest_new_events(self) -> int:
        """Read new events from JSONL since last read. Returns count of new events."""
        if not EVENTS_PATH.exists():
            return 0
        new_count = 0
        try:
            with open(EVENTS_PATH, "r", encoding="utf-8") as f:
                f.seek(self.file_offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        self.events.append(ev)
                        new_count += 1
                    except (json.JSONDecodeError, TypeError):
                        _log.warning("Skipping malformed event line")
                self.file_offset = f.tell()
        except OSError as e:
            _log.error("Failed to read events: %s", e)
        return new_count

    def compute(self) -> dict:
        """Compute all metrics from current state. Returns flat dict."""
        evts = self.events
        n = len(evts)

        # Derive elapsed from event timestamps (survives across runner restarts)
        if evts:
            from datetime import datetime as _dt
            try:
                first_ts = _dt.fromisoformat(evts[0]["timestamp"])
                last_ts = _dt.fromisoformat(evts[-1]["timestamp"])
                elapsed = (last_ts - first_ts).total_seconds()
            except (KeyError, ValueError):
                elapsed = time.monotonic() - self.start_time
        else:
            elapsed = time.monotonic() - self.start_time

        m = {}

        # --- PROGRESS ---
        m["total_jobs"] = self.total_jobs
        m["completed_jobs"] = n
        m["percent_complete"] = round(100 * n / self.total_jobs, 2) if self.total_jobs > 0 else 0
        m["elapsed_seconds"] = round(elapsed, 1)
        m["elapsed_display"] = str(timedelta(seconds=int(elapsed)))
        jps = n / elapsed if elapsed > 0 else 0
        m["jobs_per_second"] = round(jps, 3)
        remaining = (self.total_jobs - n) / jps if jps > 0 else 0
        m["estimated_remaining"] = str(timedelta(seconds=int(remaining)))

        if n == 0:
            return m

        # --- OUTCOMES ---
        passes = [e for e in evts if e.get("pass")]
        fails = [e for e in evts if not e.get("pass")]
        m["pass_rate"] = round(100 * len(passes) / n, 2)
        m["fail_rate"] = round(100 * len(fails) / n, 2)

        attempts = [e.get("num_attempts", 1) for e in evts]
        m["avg_attempts"] = round(mean(attempts), 2) if attempts else 0
        m["median_attempts"] = median(attempts) if attempts else 0

        first_try = [e for e in evts if e.get("num_attempts", 1) == 1 and e.get("pass")]
        m["first_try_success_rate"] = round(100 * len(first_try) / n, 2)
        retry_success = [e for e in passes if e.get("num_attempts", 1) > 1]
        m["retry_success_rate"] = round(100 * len(retry_success) / n, 2)

        # --- REASONING / EXECUTION ---
        rc = [e for e in evts if e.get("reasoning_correct")]
        cc = [e for e in evts if e.get("code_correct")]
        m["reasoning_correct_rate"] = round(100 * len(rc) / n, 2)
        m["code_correct_rate"] = round(100 * len(cc) / n, 2)

        # --- ALIGNMENT / LEG ---
        aligned = [e for e in evts if e.get("reasoning_correct") and e.get("code_correct")]
        misaligned = [e for e in evts if e.get("reasoning_correct") != e.get("code_correct")
                      and e.get("reasoning_correct") is not None]
        m["alignment_rate"] = round(100 * len(aligned) / n, 2)
        m["misalignment_rate"] = round(100 * len(misaligned) / n, 2)

        leg = [e for e in evts if e.get("reasoning_correct") and not e.get("code_correct")]
        m["leg_rate"] = round(100 * len(leg) / n, 2)
        m["leg_count"] = len(leg)

        lucky = [e for e in evts if not e.get("reasoning_correct") and e.get("code_correct")]
        m["lucky_fix_rate"] = round(100 * len(lucky) / n, 2)
        m["lucky_fix_count"] = len(lucky)

        true_success = [e for e in evts if e.get("reasoning_correct") and e.get("code_correct")]
        true_failure = [e for e in evts if not e.get("reasoning_correct") and not e.get("code_correct")]
        m["true_success_count"] = len(true_success)
        m["true_failure_count"] = len(true_failure)

        # --- FAILURE BREAKDOWN ---
        ft_counts = Counter(e.get("failure_type", "UNKNOWN") for e in fails)
        m["failure_type_counts"] = dict(ft_counts.most_common(20))

        # --- MODEL BREAKDOWN (rich per-model stats) ---
        models = sorted(set(e.get("model", "?") for e in evts))
        model_stats = {}
        for mdl in models:
            me = [e for e in evts if e.get("model") == mdl]
            mn = len(me)
            if mn == 0:
                continue
            mp = [e for e in me if e.get("pass")]
            mf = [e for e in me if not e.get("pass")]
            m_rc = [e for e in me if e.get("reasoning_correct")]
            m_cc = [e for e in me if e.get("code_correct")]
            m_true_success = [e for e in me if e.get("reasoning_correct") and e.get("code_correct")]
            m_leg = [e for e in me if e.get("reasoning_correct") and not e.get("code_correct")]
            m_lucky = [e for e in me if not e.get("reasoning_correct") and e.get("code_correct")]
            m_true_failure = [e for e in me if not e.get("reasoning_correct") and not e.get("code_correct")]
            m_aligned = [e for e in me if e.get("reasoning_correct") and e.get("code_correct")]
            m_misaligned = [e for e in me if e.get("reasoning_correct") != e.get("code_correct")
                           and e.get("reasoning_correct") is not None]
            m_attempts = [e.get("num_attempts", 1) for e in me]

            # Per-condition stats for this model
            m_conditions = sorted(set(e.get("condition", "?") for e in me))
            m_cond_stats = {}
            for cond in m_conditions:
                ce = [e for e in me if e.get("condition") == cond]
                cn = len(ce)
                if cn == 0:
                    continue
                cp = [e for e in ce if e.get("pass")]
                cl = [e for e in ce if e.get("reasoning_correct") and not e.get("code_correct")]
                m_cond_stats[cond] = {
                    "n": cn,
                    "pass_rate": round(100 * len(cp) / cn, 2),
                    "leg_rate": round(100 * len(cl) / cn, 2),
                }

            # Per-case stats for this model (for top-5 hardest)
            m_cases = sorted(set(e.get("case_id", "?") for e in me))
            m_case_stats = {}
            for cid in m_cases:
                ce = [e for e in me if e.get("case_id") == cid]
                cn = len(ce)
                if cn == 0:
                    continue
                cp = [e for e in ce if e.get("pass")]
                m_case_stats[cid] = {
                    "n": cn,
                    "pass_rate": round(100 * len(cp) / cn, 2),
                }
            m_hardest5 = []
            if m_case_stats:
                by_hard = sorted(m_case_stats.items(), key=lambda x: x[1]["pass_rate"])
                m_hardest5 = [(k, v["pass_rate"]) for k, v in by_hard[:5]]

            # Failure type breakdown for this model
            m_ft_counts = Counter(e.get("failure_type", "UNKNOWN") for e in mf)

            model_stats[mdl] = {
                "n": mn,
                "pass_rate": round(100 * len(mp) / mn, 2),
                "fail_rate": round(100 * len(mf) / mn, 2),
                "reasoning_correct_rate": round(100 * len(m_rc) / mn, 2),
                "code_correct_rate": round(100 * len(m_cc) / mn, 2),
                "true_success_count": len(m_true_success),
                "leg_count": len(m_leg),
                "leg_rate": round(100 * len(m_leg) / mn, 2),
                "lucky_fix_count": len(m_lucky),
                "lucky_fix_rate": round(100 * len(m_lucky) / mn, 2),
                "true_failure_count": len(m_true_failure),
                "alignment_rate": round(100 * len(m_aligned) / mn, 2),
                "misalignment_rate": round(100 * len(m_misaligned) / mn, 2),
                "avg_attempts": round(mean(m_attempts), 2),
                "median_attempts": median(m_attempts),
                "condition_stats": m_cond_stats,
                "hardest5": m_hardest5,
                "failure_type_counts": dict(m_ft_counts.most_common(10)),
            }
        m["model_stats"] = model_stats

        # --- CONDITION COMPARISON ---
        conditions = sorted(set(e.get("condition", "?") for e in evts))
        cond_stats = {}
        for cond in conditions:
            ce = [e for e in evts if e.get("condition") == cond]
            cn = len(ce)
            if cn == 0:
                continue
            cp = [e for e in ce if e.get("pass")]
            cl = [e for e in ce if e.get("reasoning_correct") and not e.get("code_correct")]
            cond_stats[cond] = {
                "n": cn,
                "pass_rate": round(100 * len(cp) / cn, 2),
                "leg_rate": round(100 * len(cl) / cn, 2),
            }
        m["condition_stats"] = cond_stats

        # Baseline vs intervention delta
        bl = cond_stats.get("baseline", {})
        if bl:
            non_bl = [c for c in cond_stats if c != "baseline"]
            if non_bl:
                avg_int_pass = mean(cond_stats[c]["pass_rate"] for c in non_bl)
                avg_int_leg = mean(cond_stats[c]["leg_rate"] for c in non_bl)
                m["baseline_pass_rate"] = bl["pass_rate"]
                m["intervention_pass_rate"] = round(avg_int_pass, 2)
                m["delta_pass_rate"] = round(avg_int_pass - bl["pass_rate"], 2)
                m["baseline_leg_rate"] = bl["leg_rate"]
                m["intervention_leg_rate"] = round(avg_int_leg, 2)
                m["delta_leg_rate"] = round(avg_int_leg - bl["leg_rate"], 2)

        # --- CASE-LEVEL ---
        cases = sorted(set(e.get("case_id", "?") for e in evts))
        case_stats = {}
        for cid in cases:
            ce = [e for e in evts if e.get("case_id") == cid]
            cn = len(ce)
            if cn == 0:
                continue
            cp = [e for e in ce if e.get("pass")]
            cl = [e for e in ce if e.get("reasoning_correct") and not e.get("code_correct")]
            clf = [e for e in ce if not e.get("reasoning_correct") and e.get("code_correct")]
            case_stats[cid] = {
                "n": cn,
                "pass_rate": round(100 * len(cp) / cn, 2),
                "leg_rate": round(100 * len(cl) / cn, 2),
                "lucky_fix_rate": round(100 * len(clf) / cn, 2),
                "avg_attempts": round(mean(e.get("num_attempts", 1) for e in ce), 2),
            }
        m["case_stats"] = case_stats

        # --- TOP-K INSIGHTS ---
        if case_stats:
            by_leg = sorted(case_stats.items(), key=lambda x: x[1]["leg_rate"], reverse=True)
            by_lucky = sorted(case_stats.items(), key=lambda x: x[1]["lucky_fix_rate"], reverse=True)
            by_hard = sorted(case_stats.items(), key=lambda x: x[1]["pass_rate"])
            by_easy = sorted(case_stats.items(), key=lambda x: x[1]["pass_rate"], reverse=True)
            m["top5_leg"] = [(k, v["leg_rate"]) for k, v in by_leg[:5]]
            m["top5_lucky"] = [(k, v["lucky_fix_rate"]) for k, v in by_lucky[:5]]
            m["hardest5"] = [(k, v["pass_rate"]) for k, v in by_hard[:5]]
            m["easiest5"] = [(k, v["pass_rate"]) for k, v in by_easy[:5]]

        # --- STABILITY (across repeats) ---
        case_cond_repeats = defaultdict(list)
        for e in evts:
            key = (e.get("case_id"), e.get("condition"))
            case_cond_repeats[key].append(1 if e.get("pass") else 0)
        pass_variances = []
        disagree_count = 0
        for key, results in case_cond_repeats.items():
            if len(results) >= 2:
                pass_variances.append(stdev(results))
                if len(set(results)) > 1:
                    disagree_count += 1
        if pass_variances:
            m["variance_pass_rate"] = round(mean(pass_variances), 4)
        m["repeat_disagreement_count"] = disagree_count

        # --- PERFORMANCE ---
        times = [e.get("elapsed_seconds") for e in evts if e.get("elapsed_seconds") is not None]
        if times:
            m["avg_time_per_job"] = round(mean(times), 2)

        # --- RECENT ACTIVITY ---
        m["recent"] = evts[-10:]

        return m


# ============================================================
# DASHBOARD WRITER
# ============================================================

def _fmt_pct(val, width=8):
    if val is None:
        return "   N/A".ljust(width)
    return f"{val:>{width}.2f}%"


def _fmt_num(val, width=8):
    if val is None:
        return "   N/A".ljust(width)
    return f"{val:>{width}}"


def write_dashboard(metrics: dict) -> None:
    """Write the dashboard to a temp file, then atomic rename."""
    lines = []
    w = lines.append  # shorthand

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 72)
    w("  LIVE METRICS DASHBOARD")
    w(f"  Last updated: {now}")
    w("=" * 72)
    w("")

    # --- PROGRESS ---
    w("[PROGRESS]")
    w(f"  Completed:  {metrics.get('completed_jobs', 0)} / {metrics.get('total_jobs', '?')} eval calls"
      f"  ({metrics.get('percent_complete', 0):.1f}%)")
    w(f"  Elapsed:    {metrics.get('elapsed_display', '?')}")
    w(f"  Remaining:  {metrics.get('estimated_remaining', '?')}")
    w(f"  Speed:      {metrics.get('jobs_per_second', 0):.3f} eval calls/sec")
    w("")

    if metrics.get("completed_jobs", 0) == 0:
        w("  (no events yet)")
        _write_atomic(lines)
        return

    # ==================================================================
    # TOTAL — ALL MODELS
    # ==================================================================
    w("=" * 72)
    w("  [TOTAL — ALL MODELS]")
    w("=" * 72)
    w("")

    # --- CORE METRICS ---
    w("  [CORE METRICS]")
    w(f"    Pass rate:          {_fmt_pct(metrics.get('pass_rate'))}")
    w(f"      -- % of attempts where execution test passed")
    w(f"    Fail rate:          {_fmt_pct(metrics.get('fail_rate'))}")
    w(f"      -- % of attempts where execution test failed")
    w(f"    First-try success:  {_fmt_pct(metrics.get('first_try_success_rate'))}")
    w(f"    Retry success:      {_fmt_pct(metrics.get('retry_success_rate'))}")
    w(f"    Avg attempts:       {metrics.get('avg_attempts', 'N/A')}")
    w(f"    Median attempts:    {metrics.get('median_attempts', 'N/A')}")
    w("")

    # --- REASONING / EXECUTION ---
    w("  [REASONING / EXECUTION]")
    w(f"    Reasoning correct:  {_fmt_pct(metrics.get('reasoning_correct_rate'))}")
    w(f"      -- % where LLM classifier judged reasoning identified the correct mechanism")
    w(f"    Code correct:       {_fmt_pct(metrics.get('code_correct_rate'))}")
    w(f"      -- % where execution test passed (ground truth)")
    w("")

    # --- LEG + ALIGNMENT ---
    w("  [LEG + ALIGNMENT]")
    w(f"    True success:       {metrics.get('true_success_count', 0):>6}")
    w(f"      -- Both reasoning and code correct")
    w(f"    LEG:                {metrics.get('leg_count', 0):>6}  ({_fmt_pct(metrics.get('leg_rate')).strip()})")
    w(f"      -- % where reasoning was correct but code failed (Latent Execution Gap)")
    w(f"    Lucky fix:          {metrics.get('lucky_fix_count', 0):>6}  ({_fmt_pct(metrics.get('lucky_fix_rate')).strip()})")
    w(f"      -- % where code passed despite incorrect reasoning")
    w(f"    True failure:       {metrics.get('true_failure_count', 0):>6}")
    w(f"      -- Both reasoning and code wrong")
    w(f"    Alignment rate:     {_fmt_pct(metrics.get('alignment_rate'))}")
    w(f"      -- % where reasoning and code agree (both right or both wrong)")
    w(f"    Misalignment rate:  {_fmt_pct(metrics.get('misalignment_rate'))}")
    w("")

    # --- CONDITION COMPARISON ---
    cond_stats = metrics.get("condition_stats", {})
    if cond_stats:
        w("  [CONDITION COMPARISON]")
        w(f"    {'Condition':<28} {'N':>5} {'Pass%':>8} {'LEG%':>8}")
        w(f"    {'─' * 52}")
        for cond, cs in sorted(cond_stats.items()):
            w(f"    {cond:<28} {cs['n']:>5} {cs['pass_rate']:>7.2f}% {cs['leg_rate']:>7.2f}%")
        if "delta_pass_rate" in metrics:
            w("")
            w(f"    Baseline pass:      {metrics.get('baseline_pass_rate', 'N/A')}%")
            w(f"    Intervention pass:  {metrics.get('intervention_pass_rate', 'N/A')}%")
            w(f"    Delta pass:         {metrics.get('delta_pass_rate', 'N/A'):+.2f}%")
            w(f"    Delta LEG:          {metrics.get('delta_leg_rate', 'N/A'):+.2f}%")
        w("")

    # --- MODEL SUMMARY TABLE ---
    model_stats = metrics.get("model_stats", {})
    if model_stats:
        w("  [MODEL SUMMARY TABLE]")
        w(f"    {'Model':<24} {'N':>5} {'Pass%':>8} {'LEG%':>8} {'Align%':>8} {'Avg Att':>8}")
        w(f"    {'─' * 66}")
        for mdl, ms in sorted(model_stats.items()):
            w(f"    {mdl:<24} {ms['n']:>5} {ms['pass_rate']:>7.2f}% {ms['leg_rate']:>7.2f}%"
              f" {ms['alignment_rate']:>7.2f}% {ms['avg_attempts']:>7.2f}")
        w("")

    # --- FAILURE TYPES ---
    ft = metrics.get("failure_type_counts", {})
    if ft:
        w("  [FAILURE TYPE BREAKDOWN]")
        for ftype, count in sorted(ft.items(), key=lambda x: -x[1]):
            w(f"    {str(ftype or 'UNKNOWN'):<32} {count:>5}")
        w("")

    # --- TOP CASES ---
    if metrics.get("top5_leg"):
        w("  [TOP 5 — Highest LEG Rate]")
        for cid, rate in metrics["top5_leg"]:
            w(f"    {cid:<36} {rate:>6.1f}%")
        w("")

    if metrics.get("hardest5"):
        w("  [TOP 5 — Hardest Cases (lowest pass rate)]")
        for cid, rate in metrics["hardest5"]:
            w(f"    {cid:<36} {rate:>6.1f}%")
        w("")

    if metrics.get("easiest5"):
        w("  [TOP 5 — Easiest Cases (highest pass rate)]")
        for cid, rate in metrics["easiest5"]:
            w(f"    {cid:<36} {rate:>6.1f}%")
        w("")

    if metrics.get("top5_lucky"):
        w("  [TOP 5 — Highest Lucky Fix Rate]")
        for cid, rate in metrics["top5_lucky"]:
            w(f"    {cid:<36} {rate:>6.1f}%")
        w("")

    # --- STABILITY ---
    if "variance_pass_rate" in metrics or "repeat_disagreement_count" in metrics:
        w("  [STABILITY]")
        if "variance_pass_rate" in metrics:
            w(f"    Pass rate stdev (across repeats): {metrics['variance_pass_rate']:.4f}")
        w(f"    Repeat disagreements:             {metrics.get('repeat_disagreement_count', 0)}")
        w("")

    # --- PERFORMANCE ---
    if "avg_time_per_job" in metrics:
        w("  [PERFORMANCE]")
        w(f"    Avg time per eval:  {metrics['avg_time_per_job']:.2f}s")
        w("")

    # ==================================================================
    # PER-MODEL SECTIONS
    # ==================================================================
    if model_stats:
        for mdl, ms in sorted(model_stats.items()):
            w("=" * 72)
            w(f"  [MODEL: {mdl}]")
            w("=" * 72)
            w("")

            mn = ms["n"]

            # --- CORE METRICS ---
            w("  [CORE METRICS]")
            w(f"    N (eval calls):     {_fmt_num(mn)}")
            w(f"    Pass rate:          {_fmt_pct(ms.get('pass_rate'))}")
            w(f"      -- % of attempts where execution test passed")
            w(f"    Fail rate:          {_fmt_pct(ms.get('fail_rate'))}")
            w(f"      -- % of attempts where execution test failed")
            w(f"    Avg attempts:       {ms.get('avg_attempts', 'N/A')}")
            w(f"    Median attempts:    {ms.get('median_attempts', 'N/A')}")
            w("")

            # --- REASONING / EXECUTION ---
            w("  [REASONING / EXECUTION]")
            w(f"    Reasoning correct:  {_fmt_pct(ms.get('reasoning_correct_rate'))}")
            w(f"      -- % where LLM classifier judged reasoning identified the correct mechanism")
            w(f"    Code correct:       {_fmt_pct(ms.get('code_correct_rate'))}")
            w(f"      -- % where execution test passed (ground truth)")
            w("")

            # --- LEG + ALIGNMENT ---
            w("  [LEG + ALIGNMENT]")
            w(f"    True success:       {ms.get('true_success_count', 0):>6}")
            w(f"      -- Both reasoning and code correct")
            w(f"    LEG:                {ms.get('leg_count', 0):>6}  ({_fmt_pct(ms.get('leg_rate')).strip()})")
            w(f"      -- % where reasoning was correct but code failed (Latent Execution Gap)")
            w(f"    Lucky fix:          {ms.get('lucky_fix_count', 0):>6}  ({_fmt_pct(ms.get('lucky_fix_rate')).strip()})")
            w(f"      -- % where code passed despite incorrect reasoning")
            w(f"    True failure:       {ms.get('true_failure_count', 0):>6}")
            w(f"      -- Both reasoning and code wrong")
            w(f"    Alignment rate:     {_fmt_pct(ms.get('alignment_rate'))}")
            w(f"      -- % where reasoning and code agree (both right or both wrong)")
            w(f"    Misalignment rate:  {_fmt_pct(ms.get('misalignment_rate'))}")
            w("")

            # --- CONDITION COMPARISON (per model) ---
            m_cond = ms.get("condition_stats", {})
            if m_cond:
                w("  [CONDITION COMPARISON]")
                w(f"    {'Condition':<28} {'N':>5} {'Pass%':>8} {'LEG%':>8}")
                w(f"    {'─' * 52}")
                for cond, cs in sorted(m_cond.items()):
                    w(f"    {cond:<28} {cs['n']:>5} {cs['pass_rate']:>7.2f}% {cs['leg_rate']:>7.2f}%")
                w("")

            # --- FAILURE TYPES (per model) ---
            m_ft = ms.get("failure_type_counts", {})
            if m_ft:
                w("  [FAILURE TYPE BREAKDOWN]")
                for ftype, count in sorted(m_ft.items(), key=lambda x: -x[1]):
                    w(f"    {str(ftype or 'UNKNOWN'):<32} {count:>5}")
                w("")

            # --- TOP 5 HARDEST (per model) ---
            m_hardest = ms.get("hardest5", [])
            if m_hardest:
                w("  [TOP 5 — Hardest Cases (lowest pass rate)]")
                for cid, rate in m_hardest:
                    w(f"    {cid:<36} {rate:>6.1f}%")
                w("")

    # ==================================================================
    # CASE-LEVEL DETAIL
    # ==================================================================
    case_stats = metrics.get("case_stats", {})
    if case_stats:
        w("=" * 72)
        w("  [CASE-LEVEL DETAIL]")
        w("=" * 72)
        w(f"  {'Case':<36} {'N':>4} {'Pass%':>7} {'LEG%':>7} {'Lucky%':>7} {'Att':>5}")
        w(f"  {'─' * 70}")
        for cid, cs in sorted(case_stats.items()):
            w(f"  {cid:<36} {cs['n']:>4} {cs['pass_rate']:>6.1f}% {cs['leg_rate']:>6.1f}%"
              f" {cs['lucky_fix_rate']:>6.1f}% {cs['avg_attempts']:>5.1f}")
        w("")

    # ==================================================================
    # RECENT ACTIVITY
    # ==================================================================
    recent = metrics.get("recent", [])
    if recent:
        w("=" * 72)
        w("  [RECENT ACTIVITY (last 10)]")
        w("=" * 72)
        for e in recent[-10:]:
            ts = e.get("timestamp", "?")[-8:]  # HH:MM:SS
            cid = e.get("case_id", "?")[:24]
            mdl = e.get("model", "?")[:16]
            cond = e.get("condition", "?")[:16]
            p = "PASS" if e.get("pass") else "FAIL"
            rc = "R:Y" if e.get("reasoning_correct") else "R:N"
            cc = "C:Y" if e.get("code_correct") else "C:N"
            w(f"  {ts}  {cid:<24} {mdl:<16} {cond:<16} {p:<4} {rc} {cc}")
        w("")

    w("=" * 72)
    w(f"  END — {metrics.get('completed_jobs', 0)}/{metrics.get('total_jobs', '?')} eval calls")
    w("=" * 72)

    _write_atomic(lines)


def _write_atomic(lines: list[str]) -> None:
    """Write lines to temp file, then atomic rename to dashboard path."""
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    try:
        with open(DASHBOARD_TMP, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(str(DASHBOARD_TMP), str(DASHBOARD_PATH))
    except OSError as e:
        _log.error("Dashboard write failed: %s", e)


# ============================================================
# AGGREGATOR THREAD
# ============================================================

_aggregator_thread: threading.Thread | None = None
_aggregator_stop = threading.Event()
_metrics_state: MetricsState | None = None


def _aggregator_loop():
    """Main loop: read events, compute metrics, write dashboard."""
    state = _metrics_state
    if state is None:
        return
    while not _aggregator_stop.is_set():
        try:
            new = state.ingest_new_events()
            metrics = state.compute()
            write_dashboard(metrics)
            if new > 0:
                _log.info("Dashboard updated: %d new events, %d total",
                          new, len(state.events))
        except Exception as e:
            _log.error("Aggregator error: %s", e, exc_info=True)
        _aggregator_stop.wait(timeout=REFRESH_INTERVAL)
    # Final update
    try:
        state.ingest_new_events()
        metrics = state.compute()
        write_dashboard(metrics)
    except Exception:
        pass


def start_dashboard(total_jobs: int = 0, clear_events: bool = False) -> None:
    """Start the live metrics dashboard aggregator thread.

    Call ONCE before the experiment starts.
    Set clear_events=True only for the first run in a multi-run ablation.
    """
    global _aggregator_thread, _metrics_state

    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if clear_events and EVENTS_PATH.exists():
        EVENTS_PATH.unlink()

    _metrics_state = MetricsState(total_jobs=total_jobs)
    _aggregator_stop.clear()
    _aggregator_thread = threading.Thread(
        target=_aggregator_loop, name="metrics-aggregator", daemon=True
    )
    _aggregator_thread.start()
    _log.info("Live metrics dashboard started (total_jobs=%d, refresh=%ds)",
              total_jobs, REFRESH_INTERVAL)


def stop_dashboard() -> None:
    """Stop the aggregator thread and write final dashboard."""
    global _aggregator_thread
    _aggregator_stop.set()
    if _aggregator_thread is not None:
        _aggregator_thread.join(timeout=10)
        _aggregator_thread = None
    _log.info("Live metrics dashboard stopped")
