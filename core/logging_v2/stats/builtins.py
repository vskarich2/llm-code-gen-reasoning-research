"""Built-in stat compute functions. Pure functions of RunIR."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.logging_v2.enums import Axis, EventType
from core.logging_v2.views.intermediate import RunIR


def compute_pass_rate(
    ir: RunIR, axes: list[Axis],
) -> dict[str, Any]:
    completed = [
        e for e in ir.events
        if e.event_type == EventType.CASE_COMPLETED
    ]
    total = len(completed)
    passed = sum(
        1 for e in completed if e.payload.get("passed", False)
    )
    return {
        "total": total,
        "passed": passed,
        "rate": round(passed / total, 4) if total else 0.0,
    }


def compute_leg_rate(
    ir: RunIR, axes: list[Axis],
) -> dict[str, Any]:
    completed = [
        e for e in ir.events
        if e.event_type == EventType.CASE_COMPLETED
    ]
    total = len(completed)
    leg = sum(
        1 for e in completed
        if e.payload.get("outcome_class") == "LEG"
    )
    return {
        "total": total,
        "leg": leg,
        "rate": round(leg / total, 4) if total else 0.0,
    }


def compute_attempt_count(
    ir: RunIR, axes: list[Axis],
) -> dict[str, Any]:
    attempts = [
        e for e in ir.events
        if e.event_type == EventType.CONTROLLER_ATTEMPT_STARTED
    ]
    by_case: dict[str, int] = defaultdict(int)
    for e in attempts:
        if e.case_id:
            by_case[e.case_id] += 1
    return {
        "total_attempts": len(attempts),
        "by_case": dict(by_case),
    }


def compute_parse_rate(
    ir: RunIR, axes: list[Axis],
) -> dict[str, Any]:
    node_completed = [
        e for e in ir.events
        if (e.event_type == EventType.ENGINE_NODE_COMPLETED
            and e.node == "parse")
    ]
    return {"total_parse_completions": len(node_completed)}


def compute_mean_latency(
    ir: RunIR, axes: list[Axis],
) -> dict[str, Any]:
    latencies = [
        c.latency_ms for c in ir.calls
    ]
    if not latencies:
        return {"mean_ms": 0, "count": 0}
    return {
        "mean_ms": round(sum(latencies) / len(latencies)),
        "count": len(latencies),
    }
