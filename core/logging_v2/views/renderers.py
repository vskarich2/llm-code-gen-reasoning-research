"""Pure view renderer functions. No side effects. No filesystem access.

Each renderer: (ir: RunIR, config: LoggingV2Config) -> str
"""

from __future__ import annotations

import json
from typing import Any

from core.logging_v2.config import LoggingV2Config
from core.logging_v2.enums import EventType, StatName
from core.logging_v2.views.intermediate import RunIR


def render_summary(ir: RunIR, config: LoggingV2Config) -> str:
    lines = [
        f"# Run Summary: {ir.manifest.experiment_name}",
        "",
        f"- Run ID: {ir.manifest.run_id}",
        f"- Status: {ir.manifest.status.value}",
        f"- Started: {ir.manifest.start_timestamp}",
        f"- Ended: {ir.manifest.end_timestamp or 'N/A'}",
        f"- Git: {ir.manifest.git_short_sha} ({ir.manifest.git_branch})"
        + (" DIRTY" if ir.manifest.git_dirty else ""),
        f"- Seed: {ir.manifest.seed}",
        f"- Models: {', '.join(m['name'] for m in ir.manifest.models)}",
        f"- Total events: {len(ir.events)}",
        f"- Total calls: {len(ir.calls)}",
        f"- Cases: {len(ir.events_by_case)}",
        "",
        f"## Description",
        ir.manifest.experiment_description,
        "",
        f"## Tags",
        ", ".join(ir.manifest.experiment_tags),
    ]
    return "\n".join(lines)


def render_timeline(ir: RunIR, config: LoggingV2Config) -> str:
    lines = ["# Timeline", ""]
    for event in ir.events:
        lines.append(
            f"[{event.seq:08d}] {event.timestamp} "
            f"{event.event_type.value} "
            f"case={event.case_id or '-'} "
            f"node={event.node or '-'} "
            f"trial={event.trial if event.trial is not None else '-'}"
        )
    return "\n".join(lines)


def render_failures(ir: RunIR, config: LoggingV2Config) -> str:
    failure_types = {
        EventType.RUN_FAILED,
        EventType.CASE_FAILED,
        EventType.ENGINE_GRAPH_FAILED,
        EventType.ENGINE_NODE_FAILED,
        EventType.LLM_CALL_FAILED,
    }
    failures = [e for e in ir.events if e.event_type in failure_types]
    lines = [f"# Failures ({len(failures)} total)", ""]
    for f in failures:
        error = f.payload.get("error", "unknown")
        lines.append(
            f"- [{f.seq:08d}] {f.event_type.value} "
            f"case={f.case_id or '-'} "
            f"node={f.node or '-'}: {error}"
        )
    return "\n".join(lines)


def render_llm_calls(ir: RunIR, config: LoggingV2Config) -> str:
    lines = [f"# LLM Calls ({len(ir.calls)} total)", ""]
    lines.append(
        "| # | Model | Node | Case | Trial | Latency | Status |"
    )
    lines.append("|---|-------|------|------|-------|---------|--------|")
    for i, call in enumerate(ir.calls):
        lines.append(
            f"| {i+1} | {call.model} | {call.node} | "
            f"{call.case_id} | {call.trial} | "
            f"{call.latency_ms}ms | {call.status.value} |"
        )
    return "\n".join(lines)


def render_trial_table(ir: RunIR, config: LoggingV2Config) -> str:
    completed = [
        e for e in ir.events
        if e.event_type == EventType.CASE_COMPLETED
    ]
    lines = [f"# Trial Table ({len(completed)} cases)", ""]
    lines.append("| Case | Condition | Model | Trial | Passed | Outcome |")
    lines.append("|------|-----------|-------|-------|--------|---------|")
    for e in completed:
        lines.append(
            f"| {e.case_id or '-'} | {e.condition or '-'} | "
            f"{e.model or '-'} | {e.trial if e.trial is not None else '-'} | "
            f"{e.payload.get('passed', '-')} | "
            f"{e.payload.get('outcome_class', '-')} |"
        )
    return "\n".join(lines)


def render_index(ir: RunIR, config: LoggingV2Config) -> str:
    data = {
        "run_id": ir.manifest.run_id,
        "experiment_name": ir.manifest.experiment_name,
        "status": ir.manifest.status.value,
        "total_events": len(ir.events),
        "total_calls": len(ir.calls),
        "cases": sorted(ir.events_by_case.keys()),
        "event_types": sorted(
            set(e.event_type.value for e in ir.events),
        ),
    }
    return json.dumps(data, indent=2, default=str)


def render_case_detail(
    case_id: str, ir: RunIR, config: LoggingV2Config,
) -> str:
    events = ir.events_by_case.get(case_id, [])
    calls = ir.calls_by_case.get(case_id, [])
    lines = [f"# Case: {case_id}", ""]
    lines.append(f"Events: {len(events)}")
    lines.append(f"Calls: {len(calls)}")
    lines.append("")
    lines.append("## Event Timeline")
    for e in events:
        lines.append(
            f"  [{e.seq:08d}] {e.event_type.value} "
            f"node={e.node or '-'} trial={e.trial if e.trial is not None else '-'}"
        )
    lines.append("")
    lines.append("## Calls")
    for c in calls:
        lines.append(
            f"  {c.node} trial={c.trial} "
            f"latency={c.latency_ms}ms status={c.status.value}"
        )
    return "\n".join(lines)
