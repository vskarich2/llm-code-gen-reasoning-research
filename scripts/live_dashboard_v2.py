"""Live V2 dashboard — polls merged_run.jsonl every 30 seconds.

Usage:
    .venv/bin/python scripts/live_dashboard_v2.py logs/.../run_dir

    Or with custom interval:
    .venv/bin/python scripts/live_dashboard_v2.py logs/.../run_dir --interval 10
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline.orchestration import build_merged_run
from core.logging_.v2_metrics import compute_v2_metrics
from core.logging_.v2_dashboard import write_v2_dashboard


def main():
    parser = argparse.ArgumentParser(description="Live V2 dashboard poller")
    parser.add_argument("run_dir", help="Path to run directory")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")
    parser.add_argument("--expected-cases", type=int, default=None)
    parser.add_argument("--expected-conditions", type=int, default=None)
    parser.add_argument("--expected-trials", type=int, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: {run_dir} does not exist")
        sys.exit(1)

    dashboard_path = run_dir / "dashboard_v2.txt"
    prev_metrics = None

    print(f"Live V2 Dashboard")
    print(f"  Run dir: {run_dir}")
    print(f"  Dashboard: {dashboard_path}")
    print(f"  Interval: {args.interval}s")
    print(f"  Ctrl+C to stop")
    print()

    while True:
        try:
            # Step 1: merge run.jsonl files
            try:
                merged_path = build_merged_run(
                    run_dir,
                    strict_completeness=False,
                    strict_schema=False,
                )
            except FileNotFoundError:
                print(f"  [{time.strftime('%H:%M:%S')}] No run.jsonl files yet...")
                time.sleep(args.interval)
                continue
            except ValueError as e:
                print(f"  [{time.strftime('%H:%M:%S')}] Merge error: {e}")
                time.sleep(args.interval)
                continue

            # Step 2: load and compute metrics
            rows = [json.loads(l) for l in open(merged_path)]
            metrics = compute_v2_metrics(
                rows,
                expected_cases=args.expected_cases,
                expected_conditions=args.expected_conditions,
                expected_trials=args.expected_trials,
            )

            # Step 3: write dashboard
            write_v2_dashboard(metrics, dashboard_path, prev_metrics=prev_metrics)

            completed = metrics.get("completed", 0)
            expected = metrics.get("expected", "?")
            delta = ""
            if prev_metrics:
                d = completed - prev_metrics.get("completed", 0)
                if d > 0:
                    delta = f" (+{d})"
            print(f"  [{time.strftime('%H:%M:%S')}] {completed}/{expected}{delta} → {dashboard_path}")

            prev_metrics = metrics

            # Check if complete
            if completed >= metrics.get("expected", float("inf")):
                print(f"\n  Run complete! Final dashboard written.")
                break

        except KeyboardInterrupt:
            print("\n  Stopped.")
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
