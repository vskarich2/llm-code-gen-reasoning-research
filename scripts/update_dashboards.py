#!/usr/bin/env python
"""Live per-model dashboard updater for T3 ablation experiments.

Runs as a separate long-lived process. Every 30 seconds:
  - Scans run directories for each model
  - Aggregates all events from per-run events.jsonl files
  - Writes per-model dashboard files atomically

Stateless: every cycle rebuilds from disk. No caching, no incremental reads.

Usage:
    .venv/bin/python scripts/update_dashboards.py \
        --ablation-dir logs/ablation_runs \
        --models gpt-5.4-mini,gpt-5-mini,gpt-4o-mini \
        --n-cases 58 --n-conditions 2 --n-trials 8

Monitor:
    watch -n5 cat logs/dashboard_gpt-5-mini.txt
"""

import argparse
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_metrics import (
    aggregate_model_events,
    compute_metrics,
    compute_trial_progress,
    write_dashboard,
)

REFRESH_INTERVAL = 30  # seconds

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def main():
    parser = argparse.ArgumentParser(description="Live dashboard updater")
    parser.add_argument("--ablation-dir", required=True, help="Path to ablation_runs/")
    parser.add_argument("--models", required=True, help="Comma-separated model names")
    parser.add_argument("--n-cases", type=int, required=True)
    parser.add_argument("--n-conditions", type=int, required=True)
    parser.add_argument("--n-trials", type=int, required=True)
    parser.add_argument("--refresh", type=int, default=REFRESH_INTERVAL)
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    ablation_dir = Path(args.ablation_dir)
    models = [m.strip() for m in args.models.split(",")]
    total_jobs_per_model = args.n_cases * args.n_conditions * args.n_trials

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    print(f"Dashboard updater started: {len(models)} models, refresh={args.refresh}s")
    print(f"  total_jobs_per_model = {args.n_cases} × {args.n_conditions} × {args.n_trials} = {total_jobs_per_model}")

    while not _stop:
        for model in models:
            try:
                events = aggregate_model_events(model, ablation_dir)
                metrics = compute_metrics(events, total_jobs_per_model)
                trial_progress = compute_trial_progress(model, ablation_dir, args.n_trials)
                metrics["trial_progress"] = trial_progress

                # Determine figure readiness from trial progress
                complete = sum(1 for t in trial_progress if t["status"] == "COMPLETE")
                if complete >= args.n_trials:
                    metrics["figure_readiness"] = "READY"
                elif complete >= 1:
                    metrics["figure_readiness"] = "PRELIMINARY"
                else:
                    metrics["figure_readiness"] = "NOT READY"

                dashboard_path = Path(f"logs/dashboard_{model}.txt")
                write_dashboard(metrics, dashboard_path)
            except Exception as e:
                print(f"  [WARN] Dashboard update failed for {model}: {e}", file=sys.stderr)

        if args.once:
            break

        # Sleep in small increments so we can respond to signals
        for _ in range(args.refresh):
            if _stop:
                break
            time.sleep(1)

    # Final update before exit
    print("Dashboard updater: final update before exit")
    for model in models:
        try:
            events = aggregate_model_events(model, ablation_dir)
            metrics = compute_metrics(events, total_jobs_per_model)
            trial_progress = compute_trial_progress(model, ablation_dir, args.n_trials)
            metrics["trial_progress"] = trial_progress
            complete = sum(1 for t in trial_progress if t["status"] == "COMPLETE")
            metrics["figure_readiness"] = "READY" if complete >= args.n_trials else (
                "PRELIMINARY" if complete >= 1 else "NOT READY"
            )
            dashboard_path = Path(f"logs/dashboard_{model}.txt")
            write_dashboard(metrics, dashboard_path)
        except Exception as e:
            print(f"  [WARN] Final dashboard update failed for {model}: {e}", file=sys.stderr)

    print("Dashboard updater stopped.")


if __name__ == "__main__":
    main()
