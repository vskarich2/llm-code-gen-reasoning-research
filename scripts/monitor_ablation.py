#!/usr/bin/env python
"""Live ablation monitor — checks every 30s, surfaces problems and findings.

Usage:
    .venv/bin/python scripts/monitor_ablation.py

Reads events.jsonl from all run dirs under logs/ablation_full/,
computes per-model dashboards, writes them to logs/dashboard_*.txt,
and prints a live summary with anomaly detection.
"""

import os
import sys
import time
import signal
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logging_.live_metrics import read_events_safe, compute_metrics, write_dashboard

ABLATION_DIR = Path("logs/ablation_full")
MODELS = ["gpt-5-mini", "gpt-4o-mini", "gpt-4.1-nano"]
N_CASES = 58
N_CONDITIONS = 2
N_TRIALS = 5
TOTAL_PER_MODEL = N_CASES * N_CONDITIONS * N_TRIALS  # 580
REFRESH = 30

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def collect_events(model):
    """Read all events for a model across all trial timestamp dirs."""
    model_dir = ABLATION_DIR / model
    if not model_dir.exists():
        return []
    events = []
    for ts_dir in sorted(model_dir.iterdir()):
        if not ts_dir.is_dir():
            continue
        ef = ts_dir / "events.jsonl"
        if ef.exists():
            events.extend(read_events_safe(ef))
    return events


def check_process_health():
    """Check if runner processes are still alive by looking at log staleness."""
    issues = []
    log_dir = ABLATION_DIR
    for log_file in sorted(log_dir.glob("*.log")):
        mtime = os.path.getmtime(log_file)
        age = time.time() - mtime
        if age > 300:  # 5 minutes stale
            issues.append(f"STALE: {log_file.name} (last update {age:.0f}s ago)")
    return issues


def detect_anomalies(model, metrics):
    """Return list of anomaly strings for a model's metrics."""
    issues = []
    n = metrics.get("completed_jobs", 0)
    if n == 0:
        return ["NO EVENTS — process may not have started"]

    # System health
    pf = metrics.get("parse_failure_rate", 0)
    cf = metrics.get("classifier_parse_failure_rate", 0)
    nr = metrics.get("no_reasoning_rate", 0)
    if pf > 0.05:
        issues.append(f"parse_failure_rate={pf:.1%} — pipeline may be broken")
    if cf > 0.05:
        issues.append(f"classifier_parse_failure={cf:.1%} — prompt drift?")
    if nr > 0.10:
        issues.append(f"no_reasoning={nr:.1%} — model not producing structured reasoning")

    # Signal
    leg = metrics.get("leg_count", 0)
    lucky = metrics.get("lucky_fix_count", 0)
    if n > 20 and leg == 0:
        issues.append("LEG=0 after 20+ evals — classifier may be broken")
    if n > 50 and lucky == 0:
        issues.append("lucky_fix=0 after 50+ evals — reasoning eval may not be working")

    # Classifier health
    ch = metrics.get("confidence_high_rate")
    if ch is not None and ch > 0.95 and n > 20:
        issues.append(f"confidence HIGH={ch:.0%} — classifier too lenient")

    # Intervention
    dp = metrics.get("delta_pass", 0)
    if n > 50 and abs(dp) < 0.01:
        issues.append(f"delta_pass={dp:+.3f} — intervention has no effect")

    # Success to worse transitions
    s2w = metrics.get("success_to_worse", 0)
    l2s = metrics.get("leg_to_success", 0)
    if s2w > l2s and s2w > 3:
        issues.append(f"success->worse ({s2w}) > leg->success ({l2s}) — intervention may be harmful")

    return issues


def detect_findings(model, metrics):
    """Return list of interesting findings."""
    findings = []
    n = metrics.get("completed_jobs", 0)
    if n < 10:
        return findings

    # LEG signal
    lr = metrics.get("leg_rate", 0)
    if lr > 0.10:
        findings.append(f"LEG rate {lr:.1%} — strong reasoning-execution gap signal")

    # Intervention effect
    dp = metrics.get("delta_pass", 0)
    if dp > 0.05:
        findings.append(f"delta_pass={dp:+.3f} — intervention HELPS")
    elif dp < -0.05:
        findings.append(f"delta_pass={dp:+.3f} — intervention HURTS")

    # LEG reduction
    dl = metrics.get("delta_leg", 0)
    if dl < -0.05:
        findings.append(f"delta_leg={dl:+.3f} — LEG intervention reduces LEG (good)")

    # Transitions
    l2s = metrics.get("leg_to_success", 0)
    if l2s > 0:
        findings.append(f"{l2s} cases: LEG -> true_success (intervention fixed reasoning-execution gap)")

    # Anomalous cases
    flips = metrics.get("anomaly_flips", [])
    for cid, direction in flips[:3]:
        findings.append(f"FLIP: {cid} — {direction}")

    return findings


def print_summary(all_metrics):
    """Print compact cross-model summary."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'=' * 78}")
    print(f"  ABLATION MONITOR — {now}")
    print(f"{'=' * 78}")

    # Progress table
    print(f"\n  {'Model':<20} {'Done':>6} {'Total':>6} {'Pct':>6} {'Pass':>7} {'LEG':>7} {'Delta':>7} {'Regime':<20}")
    print(f"  {'─' * 88}")
    for model in MODELS:
        m = all_metrics.get(model, {})
        done = m.get("completed_jobs", 0)
        pr = m.get("pass_rate", 0)
        lr = m.get("leg_rate", 0)
        dp = m.get("delta_pass", 0)
        regime = m.get("regime", "—")
        pct = m.get("percent_complete", 0)
        print(f"  {model:<20} {done:>6} {TOTAL_PER_MODEL:>6} {pct:>5.1f}% "
              f"{pr:>6.1%} {lr:>6.1%} {dp:>+6.3f} {regime:<20}")

    # Anomalies
    any_issues = False
    for model in MODELS:
        m = all_metrics.get(model, {})
        issues = detect_anomalies(model, m)
        if issues:
            if not any_issues:
                print(f"\n  ANOMALIES:")
                any_issues = True
            for issue in issues:
                print(f"    [{model}] {issue}")

    # Process health
    proc_issues = check_process_health()
    if proc_issues:
        print(f"\n  PROCESS HEALTH:")
        for issue in proc_issues:
            print(f"    {issue}")

    # Findings
    any_findings = False
    for model in MODELS:
        m = all_metrics.get(model, {})
        findings = detect_findings(model, m)
        if findings:
            if not any_findings:
                print(f"\n  FINDINGS:")
                any_findings = True
            for f in findings:
                print(f"    [{model}] {f}")

    if not any_issues and not any_findings and not proc_issues:
        total_done = sum(m.get("completed_jobs", 0) for m in all_metrics.values())
        print(f"\n  All clear. {total_done} total evals completed.")

    print()


def main():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    print(f"Ablation monitor started: {len(MODELS)} models, refresh={REFRESH}s")
    print(f"  Expected: {TOTAL_PER_MODEL} evals per model ({N_CASES} x {N_CONDITIONS} x {N_TRIALS})")
    print(f"  Ablation dir: {ABLATION_DIR}")

    while not _stop:
        all_metrics = {}
        for model in MODELS:
            events = collect_events(model)
            if events:
                metrics = compute_metrics(events, TOTAL_PER_MODEL)
                all_metrics[model] = metrics

                # Write per-model dashboard
                dashboard_path = Path(f"logs/dashboard_{model}.txt")
                write_dashboard(metrics, dashboard_path)
            else:
                all_metrics[model] = {"completed_jobs": 0}

        print_summary(all_metrics)

        # Check if all done
        total_done = sum(m.get("completed_jobs", 0) for m in all_metrics.values())
        total_expected = TOTAL_PER_MODEL * len(MODELS)
        if total_done >= total_expected:
            print("  ALL MODELS COMPLETE.")
            break

        for _ in range(REFRESH):
            if _stop:
                break
            time.sleep(1)

    print("Monitor stopped.")


if __name__ == "__main__":
    main()
