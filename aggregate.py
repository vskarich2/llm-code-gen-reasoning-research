"""Experiment aggregator for T3 benchmark.

Reads events.jsonl from ALL completed runs and produces aggregated metrics.
Consumes the full event stream, not just case summaries.

Usage:
    .venv/bin/python aggregate.py --experiment experiments/my_experiment/
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from logging_core import read_events, CALL_EVENT_TYPES, write_json_atomic


def collect_all_events(experiment_dir: Path) -> tuple[list[dict], list[dict]]:
    """Read all events from an experiment.

    Returns: (orchestrator_events, run_events)
    """
    experiment_dir = Path(experiment_dir)

    # Control plane
    orch_events = read_events(experiment_dir / "events.jsonl")

    # Execution plane — find all per-run events.jsonl
    run_events = []
    for events_file in sorted(experiment_dir.rglob("*/events.jsonl")):
        if events_file.parent == experiment_dir:
            continue  # skip the orchestrator-level file
        run_events.extend(read_events(events_file))

    return orch_events, run_events


def aggregate_experiment(experiment_dir: str | Path) -> dict:
    """Aggregate metrics from a completed experiment."""
    experiment_dir = Path(experiment_dir)
    agg_dir = experiment_dir / "aggregated"
    agg_dir.mkdir(exist_ok=True)

    orch_events, run_events = collect_all_events(experiment_dir)

    # ============================================================
    # PER-MODEL METRICS
    # ============================================================

    per_model: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "pass_rates": [], "scores": [], "total_cases": 0,
        "gen_latencies": [], "classify_latencies": [],
        "parse_errors": 0, "api_errors": 0, "total_calls": 0,
        "failure_types": defaultdict(int),
    }))

    for e in run_events:
        model = e.get("model", "?")
        condition = e.get("condition", "?")
        et = e["event_type"]
        payload = e.get("payload", {})

        if et == "case.end":
            per_model[model][condition]["pass_rates"].append(1 if payload.get("pass") else 0)
            per_model[model][condition]["scores"].append(payload.get("score", 0))
            per_model[model][condition]["total_cases"] += 1
            ft = payload.get("failure_type")
            if ft:
                per_model[model][condition]["failure_types"][ft] += 1

        elif et == "case.failed":
            per_model[model][condition]["pass_rates"].append(0)
            per_model[model][condition]["total_cases"] += 1

        elif et == "call.generate":
            lat = payload.get("latency_ms")
            if lat is not None:
                per_model[model][condition]["gen_latencies"].append(lat)
            per_model[model][condition]["total_calls"] += 1
            if payload.get("error"):
                per_model[model][condition]["api_errors"] += 1

        elif et == "call.classify":
            lat = payload.get("latency_ms")
            if lat is not None:
                per_model[model][condition]["classify_latencies"].append(lat)
            per_model[model][condition]["total_calls"] += 1

        elif et == "parse.result":
            if payload.get("error"):
                per_model[model][condition]["parse_errors"] += 1

    # Compute summaries
    per_model_summary = {}
    for model, conditions in per_model.items():
        per_model_summary[model] = {}
        for condition, data in conditions.items():
            rates = data["pass_rates"]
            n = len(rates)
            mean_pass = sum(rates) / n if n else 0
            std_pass = (sum((r - mean_pass) ** 2 for r in rates) / n) ** 0.5 if n > 1 else 0
            gen_lats = data["gen_latencies"]
            cls_lats = data["classify_latencies"]

            per_model_summary[model][condition] = {
                "pass_rate": round(mean_pass, 4),
                "pass_rate_std": round(std_pass, 4),
                "total_cases": data["total_cases"],
                "mean_score": round(sum(data["scores"]) / n, 4) if n else 0,
                "avg_gen_latency_ms": round(sum(gen_lats) / len(gen_lats)) if gen_lats else None,
                "avg_classify_latency_ms": round(sum(cls_lats) / len(cls_lats)) if cls_lats else None,
                "total_calls": data["total_calls"],
                "parse_error_rate": round(data["parse_errors"] / data["total_cases"], 4) if data["total_cases"] else 0,
                "api_error_rate": round(data["api_errors"] / data["total_calls"], 4) if data["total_calls"] else 0,
                "failure_types": dict(data["failure_types"]),
            }

    write_json_atomic(agg_dir / "per_model.json", per_model_summary)

    # ============================================================
    # PER-CONDITION METRICS (across models)
    # ============================================================

    per_condition: dict[str, list[float]] = defaultdict(list)
    for model, conditions in per_model_summary.items():
        for condition, data in conditions.items():
            per_condition[condition].append(data["pass_rate"])

    per_condition_summary = {}
    for condition, rates in per_condition.items():
        per_condition_summary[condition] = {
            "mean_pass_rate": round(sum(rates) / len(rates), 4) if rates else 0,
            "models": len(rates),
        }

    write_json_atomic(agg_dir / "per_condition.json", per_condition_summary)

    # ============================================================
    # PER-TRIAL METRICS (for stability analysis)
    # ============================================================

    per_trial: dict[str, dict[str, dict[int, list]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for e in run_events:
        if e["event_type"] == "case.end":
            model = e.get("model", "?")
            condition = e.get("condition", "?")
            trial = e.get("trial", 0)
            per_trial[model][condition][trial].append(1 if e["payload"].get("pass") else 0)

    per_trial_summary = {}
    for model, conditions in per_trial.items():
        per_trial_summary[model] = {}
        for condition, trials in conditions.items():
            per_trial_summary[model][condition] = {
                str(t): round(sum(rates) / len(rates), 4) if rates else 0
                for t, rates in sorted(trials.items())
            }

    write_json_atomic(agg_dir / "per_trial.json", per_trial_summary)

    # ============================================================
    # PER-TRACE METRICS (trace-level analysis)
    # ============================================================

    traces: dict[str, dict] = {}
    for e in run_events:
        tid = e.get("trace_id")
        if tid is None:
            continue
        if tid not in traces:
            traces[tid] = {
                "trace_id": tid,
                "case_id": e.get("case_id"),
                "model": e.get("model"),
                "condition": e.get("condition"),
                "trial": e.get("trial"),
                "events": [],
            }
        traces[tid]["events"].append({
            "event_type": e["event_type"],
            "event_id": e["event_id"],
            "payload": e.get("payload", {}),
        })

    # Extract trace-level summary
    per_trace_summary = []
    for tid, trace in traces.items():
        case_end = None
        gen_latency = None
        classify_latency = None
        for ev in trace["events"]:
            if ev["event_type"] == "case.end":
                case_end = ev["payload"]
            elif ev["event_type"] == "call.generate":
                gen_latency = ev["payload"].get("latency_ms")
            elif ev["event_type"] == "call.classify":
                classify_latency = ev["payload"].get("latency_ms")

        if case_end:
            per_trace_summary.append({
                "trace_id": tid,
                "case_id": trace["case_id"],
                "model": trace["model"],
                "condition": trace["condition"],
                "trial": trace["trial"],
                "pass": case_end.get("pass"),
                "score": case_end.get("score"),
                "code_correct": case_end.get("code_correct"),
                "reasoning_correct": case_end.get("reasoning_correct"),
                "failure_type": case_end.get("failure_type"),
                "gen_latency_ms": gen_latency,
                "classify_latency_ms": classify_latency,
            })

    write_json_atomic(agg_dir / "per_trace.json", per_trace_summary)

    # ============================================================
    # DASHBOARD
    # ============================================================

    dashboard = {
        "per_model": per_model_summary,
        "per_condition": per_condition_summary,
        "per_trial": per_trial_summary,
        "total_runs": len(set(e.get("run_id") for e in run_events if e.get("run_id"))),
        "total_cases_evaluated": sum(
            d["total_cases"] for m in per_model_summary.values() for d in m.values()
        ),
    }

    write_json_atomic(agg_dir / "dashboard.json", dashboard)

    print(f"Aggregation complete: {agg_dir}", flush=True)
    print(f"  Models: {list(per_model_summary.keys())}", flush=True)
    print(f"  Conditions: {list(per_condition_summary.keys())}", flush=True)
    for model, conditions in per_model_summary.items():
        for condition, data in conditions.items():
            print(f"  {model}/{condition}: pass={data['pass_rate']:.1%} ({data['total_cases']} cases)", flush=True)

    return dashboard


def main():
    parser = argparse.ArgumentParser(description="T3 Experiment Aggregator")
    parser.add_argument("--experiment", required=True, help="Experiment directory")
    args = parser.parse_args()

    aggregate_experiment(args.experiment)


if __name__ == "__main__":
    main()
