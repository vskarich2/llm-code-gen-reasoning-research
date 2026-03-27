#!/usr/bin/env python
"""Live terminal dashboard for T3 ablation runs via Redis.

Reads a Redis Stream for a given run_id, computes all metrics at read time,
and prints a formatted dashboard to the terminal. Refreshes every N seconds.

Usage:
    python scripts/redis_live_dashboard.py --run-id <run_id>
    python scripts/redis_live_dashboard.py --run-id <run_id> --refresh 5
    python scripts/redis_live_dashboard.py --run-id <run_id> --tail 100

Requires: redis (pip install redis), Redis server running on localhost:6379.
"""

import argparse
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# Stream reader
# ---------------------------------------------------------------------------


def read_stream(client, stream_key: str, max_events: int = 0) -> list[dict]:
    """Read all events from a Redis Stream. Returns list of flat dicts."""
    events = []
    last_id = "0-0"
    batch = 500
    while True:
        entries = client.xrange(stream_key, min=last_id, count=batch)
        if not entries:
            break
        for entry_id, fields in entries:
            fields["_id"] = entry_id
            events.append(fields)
            last_id = entry_id
        # Advance past the last entry we saw
        last_id = _increment_id(last_id)
        if len(entries) < batch:
            break
        if max_events and len(events) >= max_events:
            events = events[:max_events]
            break
    return events


def _increment_id(stream_id: str) -> str:
    """Increment a Redis Stream ID to use as exclusive lower bound."""
    parts = stream_id.split("-")
    if len(parts) == 2:
        return f"{parts[0]}-{int(parts[1]) + 1}"
    return stream_id


# ---------------------------------------------------------------------------
# Metric computation (pure functions — all derivation at read time)
# ---------------------------------------------------------------------------


def _bool(s: str) -> bool:
    return s.lower() == "true"


def compute_metrics(events: list[dict]) -> dict:
    """Compute all dashboard metrics from raw stream events."""
    if not events:
        return {"empty": True}

    total = len(events)
    passed = sum(1 for e in events if _bool(e.get("pass", "False")))
    failed = total - passed
    leg_count = sum(1 for e in events if _bool(e.get("leg_true", "False")))
    lucky_count = sum(1 for e in events if _bool(e.get("lucky_fix", "False")))
    true_success = sum(1 for e in events if _bool(e.get("true_success", "False")))

    first_ts = events[0].get("timestamp", "")
    last_ts = events[-1].get("timestamp", "")

    # Parse timestamps for elapsed
    elapsed = ""
    try:
        t0 = datetime.fromisoformat(first_ts)
        t1 = datetime.fromisoformat(last_ts)
        delta = t1 - t0
        mins, secs = divmod(int(delta.total_seconds()), 60)
        elapsed = f"{mins}m {secs}s"
    except Exception:
        pass

    return {
        "empty": False,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / total if total else 0,
        "leg_count": leg_count,
        "leg_rate_over_failures": leg_count / failed if failed else 0,
        "leg_rate_overall": leg_count / total if total else 0,
        "lucky_count": lucky_count,
        "true_success": true_success,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "elapsed": elapsed,
    }


def compute_by_field(events: list[dict], field: str) -> list[dict]:
    """Group events by a field and compute pass/LEG rates per group."""
    groups = defaultdict(lambda: {"total": 0, "passed": 0, "leg": 0})
    for e in events:
        key = e.get(field, "unknown")
        groups[key]["total"] += 1
        if _bool(e.get("pass", "False")):
            groups[key]["passed"] += 1
        if _bool(e.get("leg_true", "False")):
            groups[key]["leg"] += 1

    result = []
    for key in sorted(groups.keys()):
        g = groups[key]
        t = g["total"]
        result.append(
            {
                "name": key,
                "total": t,
                "passed": g["passed"],
                "pass_rate": g["passed"] / t if t else 0,
                "leg": g["leg"],
                "leg_rate": g["leg"] / t if t else 0,
            }
        )
    return result


def compute_attempt_table(events: list[dict]) -> list[dict]:
    """Compute pass/LEG rate by attempt index (num_attempts field)."""
    return compute_by_field(events, "num_attempts")


def compute_failure_modes(events: list[dict], min_count: int = 2) -> tuple[list[dict], list[dict]]:
    """Top failure modes by count, and top LEG-inducing failure modes."""
    failed = [e for e in events if not _bool(e.get("pass", "False"))]

    ft_counts = Counter(e.get("failure_type", "unknown") for e in failed)
    ft_leg = Counter(
        e.get("failure_type", "unknown") for e in failed if _bool(e.get("leg_true", "False"))
    )

    top_failures = []
    for ft, count in ft_counts.most_common(10):
        if not ft:
            continue
        top_failures.append(
            {
                "failure_type": ft,
                "count": count,
                "leg_count": ft_leg.get(ft, 0),
                "leg_rate": ft_leg.get(ft, 0) / count if count else 0,
            }
        )

    top_leg = sorted(
        [f for f in top_failures if f["count"] >= min_count and f["leg_count"] > 0],
        key=lambda x: x["leg_rate"],
        reverse=True,
    )
    return top_failures, top_leg


def compute_case_hotspots(events: list[dict], top_k: int = 10) -> list[dict]:
    """Top cases by LEG count."""
    leg_by_case = Counter(
        e.get("case_id", "unknown") for e in events if _bool(e.get("leg_true", "False"))
    )
    total_by_case = Counter(e.get("case_id", "unknown") for e in events)

    hotspots = []
    for case_id, leg_count in leg_by_case.most_common(top_k):
        total = total_by_case[case_id]
        hotspots.append(
            {
                "case_id": case_id,
                "leg_count": leg_count,
                "total": total,
                "leg_rate": leg_count / total if total else 0,
            }
        )
    return hotspots


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_dashboard(run_id: str, events: list[dict]) -> str:
    """Render the full dashboard as a string."""
    lines = []
    w = 72  # dashboard width

    m = compute_metrics(events)

    lines.append("=" * w)
    lines.append(f"  T3 LIVE DASHBOARD — run_id: {run_id}")
    lines.append("=" * w)

    if m["empty"]:
        lines.append("  No events yet.")
        return "\n".join(lines)

    # Section 1: Run summary
    lines.append(f"  Events: {m['total']:>5}    Elapsed: {m['elapsed']}")
    lines.append(f"  Latest: {m['last_ts']}")
    lines.append("")

    # Section 2: Overall metrics
    lines.append(f"  {'Metric':<28} {'Value':>10}")
    lines.append(f"  {'-'*40}")
    lines.append(f"  {'Total evaluations':<28} {m['total']:>10}")
    lines.append(f"  {'Passed':<28} {m['passed']:>10}")
    lines.append(f"  {'Failed':<28} {m['failed']:>10}")
    lines.append(f"  {'Pass rate':<28} {m['pass_rate']:>9.1%}")
    lines.append(f"  {'LEG count':<28} {m['leg_count']:>10}")
    lines.append(f"  {'LEG rate (over failures)':<28} {m['leg_rate_over_failures']:>9.1%}")
    lines.append(f"  {'LEG rate (overall)':<28} {m['leg_rate_overall']:>9.1%}")
    lines.append(f"  {'Lucky fix count':<28} {m['lucky_count']:>10}")
    lines.append(f"  {'True success count':<28} {m['true_success']:>10}")
    lines.append("")

    # Section 3: By model
    by_model = compute_by_field(events, "model")
    if by_model:
        lines.append(f"  {'Model':<22} {'Tot':>5} {'Pass':>5} {'Rate':>6} {'LEG':>5} {'LRate':>6}")
        lines.append(f"  {'-'*52}")
        for r in by_model:
            lines.append(
                f"  {r['name']:<22} {r['total']:>5} {r['passed']:>5} {r['pass_rate']:>5.1%} {r['leg']:>5} {r['leg_rate']:>5.1%}"
            )
        lines.append("")

    # Section 4: By condition
    by_cond = compute_by_field(events, "condition")
    if by_cond:
        lines.append(
            f"  {'Condition':<28} {'Tot':>5} {'Pass':>5} {'Rate':>6} {'LEG':>5} {'LRate':>6}"
        )
        lines.append(f"  {'-'*58}")
        for r in by_cond:
            lines.append(
                f"  {r['name']:<28} {r['total']:>5} {r['passed']:>5} {r['pass_rate']:>5.1%} {r['leg']:>5} {r['leg_rate']:>5.1%}"
            )
        lines.append("")

    # Section 5: By attempt index
    by_attempt = compute_attempt_table(events)
    if by_attempt and len(by_attempt) > 1:
        lines.append(
            f"  {'Attempts':<12} {'Tot':>5} {'Pass':>5} {'Rate':>6} {'LEG':>5} {'LRate':>6}"
        )
        lines.append(f"  {'-'*42}")
        for r in by_attempt:
            lines.append(
                f"  {r['name']:<12} {r['total']:>5} {r['passed']:>5} {r['pass_rate']:>5.1%} {r['leg']:>5} {r['leg_rate']:>5.1%}"
            )
        lines.append("")

    # Section 6: Failure modes
    top_failures, top_leg = compute_failure_modes(events)
    if top_failures:
        lines.append(f"  {'Failure Mode':<30} {'Count':>6} {'LEG':>5} {'LRate':>6}")
        lines.append(f"  {'-'*50}")
        for f in top_failures[:8]:
            lines.append(
                f"  {f['failure_type']:<30} {f['count']:>6} {f['leg_count']:>5} {f['leg_rate']:>5.1%}"
            )
        lines.append("")

    # Section 7: By difficulty
    by_diff = compute_by_field(events, "difficulty")
    if by_diff:
        lines.append(
            f"  {'Difficulty':<12} {'Tot':>5} {'Pass':>5} {'Rate':>6} {'LEG':>5} {'LRate':>6}"
        )
        lines.append(f"  {'-'*42}")
        for r in by_diff:
            lines.append(
                f"  {r['name']:<12} {r['total']:>5} {r['passed']:>5} {r['pass_rate']:>5.1%} {r['leg']:>5} {r['leg_rate']:>5.1%}"
            )
        lines.append("")

    # Section 8: Case hotspots
    hotspots = compute_case_hotspots(events)
    if hotspots:
        lines.append(f"  {'Case (top LEG)':<30} {'LEG':>5} {'Tot':>5} {'LRate':>6}")
        lines.append(f"  {'-'*48}")
        for h in hotspots[:8]:
            lines.append(
                f"  {h['case_id']:<30} {h['leg_count']:>5} {h['total']:>5} {h['leg_rate']:>5.1%}"
            )
        lines.append("")

    lines.append(f"  [refreshing every {{refresh}}s — Ctrl-C to exit]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="T3 live dashboard (Redis stream reader)")
    parser.add_argument("--run-id", required=True, help="Run ID to monitor")
    parser.add_argument("--refresh", type=int, default=2, help="Refresh interval in seconds")
    parser.add_argument("--tail", type=int, default=0, help="Max events to read (0 = all)")
    parser.add_argument(
        "--redis-url", default=None, help="Redis URL (default: T3_REDIS_URL or localhost:6379)"
    )
    args = parser.parse_args()

    redis_url = args.redis_url or os.environ.get("T3_REDIS_URL", "redis://localhost:6379/0")

    try:
        import redis
    except ImportError:
        print("ERROR: redis package not installed. Run: pip install redis", file=sys.stderr)
        sys.exit(1)

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
        client.ping()
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis at {redis_url}: {e}", file=sys.stderr)
        print("Start Redis with: brew install redis && redis-server", file=sys.stderr)
        sys.exit(1)

    skey = f"t3:events:{args.run_id}"
    print(f"Connected to Redis. Watching stream: {skey}")
    print(f"Refresh: {args.refresh}s. Ctrl-C to exit.\n")

    try:
        while True:
            events = read_stream(client, skey, max_events=args.tail)
            output = render_dashboard(args.run_id, events)
            # Replace {refresh} placeholder
            output = output.replace("{refresh}", str(args.refresh))

            # Clear screen and print
            print("\033[2J\033[H", end="")  # ANSI clear + home
            print(output)

            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
