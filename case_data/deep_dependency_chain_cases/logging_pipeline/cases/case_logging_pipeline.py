"""Case 5 (B): Logging/metrics pipeline.

Chain: event_collector → log_formatter → metric_aggregator → dashboard_renderer
Bypass: get_raw_events reads event_collector output directly for compliance export
Bug: event_collector truncates the severity field to 4 chars ("CRITICAL" → "CRIT")
Canonical field: severity in collected event records
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

RAW_EVENTS = {
    "primary": [
        {"ts": 1000, "severity": "CRITICAL", "source": "db", "msg": "connection timeout"},
        {"ts": 1001, "severity": "WARNING", "source": "cache", "msg": "eviction spike"},
        {"ts": 1002, "severity": "CRITICAL", "source": "api", "msg": "rate limit hit"},
        {"ts": 1003, "severity": "INFO", "source": "db", "msg": "query completed"},
        {"ts": 1004, "severity": "WARNING", "source": "api", "msg": "slow response"},
    ],
    "alternate_error": [
        {"ts": 2000, "severity": "ERROR", "source": "auth", "msg": "token expired"},
        {"ts": 2001, "severity": "ERROR", "source": "auth", "msg": "invalid signature"},
        {"ts": 2002, "severity": "CRITICAL", "source": "auth", "msg": "key rotation failed"},
    ],
    "trap_catching_input": [
        {"ts": 3000, "severity": "INFO", "source": "scheduler", "msg": "job started"},
        {"ts": 3001, "severity": "INFO", "source": "scheduler", "msg": "job completed"},
        {"ts": 3002, "severity": "WARNING", "source": "scheduler", "msg": "job slow"},
    ],
}

RAW_DATA = RAW_EVENTS

SEVERITY_LEVELS = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
ALERT_THRESHOLD = "CRITICAL"

CASE_DATA_GLOBALS = ["RAW_DATA", "RAW_EVENTS", "SEVERITY_LEVELS", "ALERT_THRESHOLD"]


def _collect_events_buggy(events):
    """BUG: truncates severity to 4 chars. CRITICAL → CRIT, WARNING → WARN."""
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"][:4],  # BUG: truncation
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected


def _collect_events_fixed(events):
    """ROOT FIX: preserve severity field as-is."""
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"],
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected


def _collect_events_trap5(events):
    """TRAP 5: adds original_severity alongside truncated severity."""
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"][:4],  # still truncated
            "original_severity": e["severity"],  # alternate field
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected


def _format_log(collected_event):
    """Formats one event into a log line."""
    return f"[{collected_event['severity']}] {collected_event['ts']} {collected_event['source']}: {collected_event['msg']}"


def _format_logs(collected_events):
    """Format all collected events."""
    return [_format_log(e) for e in collected_events]


def _aggregate_metrics(collected_events):
    """Count events by severity level. Uses exact severity string match."""
    counts = {level: 0 for level in SEVERITY_LEVELS}
    for e in collected_events:
        sev = e["severity"]
        if sev in counts:
            counts[sev] += 1
    unknown = sum(1 for e in collected_events if e["severity"] not in SEVERITY_LEVELS)
    counts["UNKNOWN"] = unknown
    return counts


def _aggregate_metrics_fuzzy(collected_events):
    """TRAP 3: fuzzy match — if severity starts with known level prefix, count it."""
    counts = {level: 0 for level in SEVERITY_LEVELS}
    counts["UNKNOWN"] = 0
    for e in collected_events:
        sev = e["severity"]
        matched = False
        for level in SEVERITY_LEVELS:
            if level.startswith(sev) or sev.startswith(level):
                counts[level] += 1
                matched = True
                break
        if not matched:
            counts["UNKNOWN"] += 1
    return counts


def _render_dashboard(metrics):
    """Render dashboard from aggregated metrics."""
    total = sum(metrics.values())
    alert_count = metrics.get("CRITICAL", 0)
    has_alert = alert_count > 0
    return {
        "total_events": total,
        "critical_count": alert_count,
        "has_alert": has_alert,
        "breakdown": dict(metrics),
    }


def _render_dashboard_patched(metrics):
    """TRAP 1: dashboard checks for UNKNOWN events and adds them to CRITICAL."""
    total = sum(metrics.values())
    alert_count = metrics.get("CRITICAL", 0) + metrics.get("UNKNOWN", 0)
    has_alert = alert_count > 0
    return {
        "total_events": total,
        "critical_count": alert_count,
        "has_alert": has_alert,
        "breakdown": dict(metrics),
        "unknown_promoted": metrics.get("UNKNOWN", 0),
    }


def _get_raw_events(collected_events):
    """BYPASS CONSUMER: reads severity directly from collected events for compliance export."""
    return [{"severity": e["severity"], "source": e["source"], "ts": e["ts"]}
            for e in collected_events]


# ── Dispatch ──

def _run_chain(patch_id, dataset="primary"):
    events = RAW_EVENTS[dataset]

    if patch_id == "root_fix":
        collected = _collect_events_fixed(events)
    elif patch_id == "trap_5":
        collected = _collect_events_trap5(events)
    else:
        collected = _collect_events_buggy(events)

    raw_export = _get_raw_events(collected)
    logs = _format_logs(collected)

    if patch_id == "trap_3":
        metrics = _aggregate_metrics_fuzzy(collected)
    elif patch_id == "trap_5":
        adjusted = []
        for e in collected:
            ae = dict(e)
            ae["severity"] = e.get("original_severity", e["severity"])
            adjusted.append(ae)
        metrics = _aggregate_metrics(adjusted)
    elif patch_id == "trap_4":
        TRUNC_MAP = {"CRIT": "CRITICAL", "WARN": "WARNING", "ERRO": "ERROR", "INFO": "INFO"}
        adjusted = []
        for e in collected:
            ae = dict(e)
            ae["severity"] = TRUNC_MAP.get(e["severity"], e["severity"])
            adjusted.append(ae)
        metrics = _aggregate_metrics(adjusted)
    else:
        metrics = _aggregate_metrics(collected)

    if patch_id == "trap_1":
        dashboard = _render_dashboard_patched(metrics)
    else:
        dashboard = _render_dashboard(metrics)

    return {
        "dashboard": dashboard,
        "raw_export": raw_export,
        "collected": collected,
        "metrics": metrics,
        "logs": logs,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    d = r["dashboard"]
    return d["has_alert"] is True and d["critical_count"] >= 2


def _run_invariant_trap_catching(patch_id):
    """All-INFO/WARNING dataset. critical_count must be 0.
    Trap 1 promotes UNKNOWN to CRITICAL → false alert."""
    r = _run_chain(patch_id, "trap_catching_input")
    d = r["dashboard"]
    passed = d["critical_count"] == 0
    return passed, f"critical_count={d['critical_count']}, expected=0", "info_only_dataset"


def _run_invariant_generalization(patch_id):
    """Log lines must contain full severity names, not truncated versions."""
    r = _run_chain(patch_id, "primary")
    for log_line in r["logs"]:
        if "[CRIT]" in log_line:
            return False, f"log contains truncated severity: {log_line}", "log_format"
        if "[WARN]" in log_line:
            return False, f"log contains truncated severity: {log_line}", "log_format"
    return True, "log lines use full severity names", "log_format"


def _run_invariant_causal_location(patch_id):
    """Collected events severity must match original (not truncated)."""
    r = _run_chain(patch_id, "primary")
    for i, ce in enumerate(r["collected"]):
        original = RAW_EVENTS["primary"][i]["severity"]
        if ce["severity"] != original:
            return False, f"event {i}: severity={ce['severity']!r}, expected={original!r}", None
    return True, "collected severity matches original", None


def _run_invariant_cross_path(patch_id):
    """Compliance export CRITICAL count must match dashboard CRITICAL count."""
    r = _run_chain(patch_id, "primary")
    dashboard_critical = r["dashboard"]["critical_count"]
    export_critical = sum(1 for e in r["raw_export"] if e["severity"] == "CRITICAL")
    consistent = dashboard_critical == export_critical
    return consistent, f"dashboard_critical={dashboard_critical}, export_critical={export_critical}", None


def _run_invariant_chain_integrity(patch_id):
    """Metrics breakdown must match direct count of collected event severities."""
    r = _run_chain(patch_id, "primary")
    direct_counts = {}
    for e in r["collected"]:
        sev = e["severity"]
        direct_counts[sev] = direct_counts.get(sev, 0) + 1
    metrics = r["metrics"]
    for sev, count in metrics.items():
        if count > 0 and sev != "UNKNOWN":
            direct = direct_counts.get(sev, 0)
            if direct != count:
                return False, (f"metrics[{sev}]={count} but direct count from "
                               f"collected={direct} (aggregator transformed severity)"), None
    return True, "metrics match collected events", None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


# ── Compiler-compatible node functions ──

# @node: event_collector
# @role: buggy
def _collect_events_node(events):
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"][:4],
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected


# @node: log_formatter
# @role: main
def _format_logs_node(collected_events):
    return {
        "collected_events": collected_events,
        "logs": [_format_log(e) for e in collected_events],
    }


# @node: metric_aggregator
# @role: main
def _aggregate_metrics_node(formatted_state):
    events = formatted_state["collected_events"]
    counts = {level: 0 for level in SEVERITY_LEVELS}
    for e in events:
        sev = e["severity"]
        if sev in counts:
            counts[sev] += 1
    counts["UNKNOWN"] = sum(1 for e in events if e["severity"] not in SEVERITY_LEVELS)
    return {"logs": formatted_state["logs"], "metrics": counts}


# @node: dashboard_renderer
# @role: main
def _render_dashboard_node(aggregated_state):
    metrics = aggregated_state["metrics"]
    total = sum(metrics.values())
    alert_count = metrics.get(ALERT_THRESHOLD, 0)
    return {
        "total_events": total,
        "critical_count": alert_count,
        "has_alert": alert_count > 0,
        "breakdown": dict(metrics),
    }


# @node: dashboard_renderer
# @role: trap_1
def _render_dashboard_node_trap1(aggregated_state):
    metrics = aggregated_state["metrics"]
    total = sum(metrics.values())
    alert_count = metrics.get(ALERT_THRESHOLD, 0) + metrics.get("UNKNOWN", 0)
    return {
        "total_events": total,
        "critical_count": alert_count,
        "has_alert": alert_count > 0,
        "breakdown": dict(metrics),
        "unknown_promoted": metrics.get("UNKNOWN", 0),
    }


# @node: metric_aggregator
# @role: trap_3
def _aggregate_metrics_node_trap3(formatted_state):
    events = formatted_state["collected_events"]
    counts = {level: 0 for level in SEVERITY_LEVELS}
    counts["UNKNOWN"] = 0
    for e in events:
        sev = e["severity"]
        matched = False
        for level in SEVERITY_LEVELS:
            if level.startswith(sev) or sev.startswith(level):
                counts[level] += 1
                matched = True
                break
        if not matched:
            counts["UNKNOWN"] += 1
    return {"logs": formatted_state["logs"], "metrics": counts}


# @node: metric_aggregator
# @role: trap_4
def _aggregate_metrics_node_trap4(formatted_state):
    trunc_map = {
        "CRIT": "CRITICAL", "WARN": "WARNING",
        "ERRO": "ERROR", "INFO": "INFO",
    }
    events = formatted_state["collected_events"]
    adjusted = []
    for e in events:
        ae = dict(e)
        ae["severity"] = trunc_map.get(e["severity"], e["severity"])
        adjusted.append(ae)
    counts = {level: 0 for level in SEVERITY_LEVELS}
    for ae in adjusted:
        sev = ae["severity"]
        if sev in counts:
            counts[sev] += 1
    counts["UNKNOWN"] = sum(
        1 for ae in adjusted if ae["severity"] not in SEVERITY_LEVELS
    )
    return {"logs": formatted_state["logs"], "metrics": counts}


# @node: event_collector
# @role: trap_5
def _collect_events_node_trap5(events):
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"][:4],
            "original_severity": e["severity"],
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected


# @node: metric_aggregator
# @role: trap_5
def _aggregate_metrics_node_trap5(formatted_state):
    events = formatted_state["collected_events"]
    adjusted = []
    for e in events:
        ae = dict(e)
        ae["severity"] = e.get("original_severity", e["severity"])
        adjusted.append(ae)
    counts = {level: 0 for level in SEVERITY_LEVELS}
    for ae in adjusted:
        sev = ae["severity"]
        if sev in counts:
            counts[sev] += 1
    counts["UNKNOWN"] = sum(
        1 for ae in adjusted if ae["severity"] not in SEVERITY_LEVELS
    )
    return {"logs": formatted_state["logs"], "metrics": counts}


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="logging_pipeline_chain",
        difficulty="B",
        domain="logging/observability",
        scenario="Event collector truncates severity field to 4 chars. "
                 "Downstream metric aggregator fails to recognize truncated severity "
                 "strings, producing wrong alert counts.",
        nodes=NodeDeclarations(
            source_of_truth_node="event_collector",
            corruption_introduced_at_node="event_collector",
            first_observable_symptom_node="metric_aggregator",
            required_fix_node="event_collector",
        ),
        canonical=CanonicalRepresentation(
            field_names=["severity"],
            schema_description="str, one of INFO/WARNING/ERROR/CRITICAL (full name)",
            storage_location="collected event dicts from event_collector",
            access_paths=[
                "log_formatter reads severity for log line rendering",
                "metric_aggregator reads severity for counting",
                "get_raw_events reads severity directly (BYPASS for compliance export)",
            ],
        ),
        chain=[
            ChainNode("event_collector", "collector.py", "collect_events_node",
                      "collects raw events — BUG: truncates severity to 4 chars"),
            ChainNode("log_formatter", "formatter.py", "format_logs_node",
                      "formats events into log lines using severity"),
            ChainNode("metric_aggregator", "aggregator.py", "aggregate_metrics_node",
                      "counts events by severity level"),
            ChainNode("dashboard_renderer", "dashboard.py", "render_dashboard_node",
                      "renders dashboard from aggregated metrics"),
        ],
        bypass_consumer="get_raw_events",
        bypass_description="reads severity directly from collected events for compliance "
                           "export; no formatter/aggregator/dashboard calls; no shared logic",
        bug_description="event_collector truncates severity to 4 chars "
                        "(CRITICAL→CRIT, WARNING→WARN). Aggregator doesn't recognize "
                        "truncated strings → events counted as UNKNOWN.",
        root_fix_description="preserve severity field as-is (remove [:4] truncation)",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "dashboard promotes UNKNOWN events to CRITICAL count",
                     "critical_count = CRITICAL + UNKNOWN",
                     "directly fixes the alert count on dashboard",
                     "compliance export has 0 CRITICAL (truncated to CRIT) "
                     "but dashboard shows 2 → disagreement",
                     "cross_path", None),
            TrapSpec("trap_3", "validation_masking", "C",
                     "aggregator uses fuzzy prefix matching for severity",
                     "if known_level.startswith(truncated): count as that level",
                     "correctly maps CRIT→CRITICAL for metric counting",
                     "compliance export still shows truncated severity; "
                     "log lines still show [CRIT] not [CRITICAL]",
                     "generalization", "log_format"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "aggregator maps truncated severity back to full name before counting",
                     "TRUNC_MAP = {CRIT: CRITICAL, WARN: WARNING, ...}",
                     "produces correct metric counts",
                     "compliance export (bypass) still has truncated severity; "
                     "log lines still show [CRIT]",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "collector adds original_severity field alongside truncated severity",
                     "event['original_severity'] = full_name; severity still truncated",
                     "correct data available; aggregator uses original_severity",
                     "compliance export reads severity (not original_severity); "
                     "export shows truncated values",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "INFO-only dataset must show critical_count=0",
                          [{"desc": "no-critical dataset"}]),
            InvariantSpec("generalization",
                          "log lines must contain full severity names, not truncated",
                          [{"desc": "log format check"}]),
            InvariantSpec("causal_location",
                          "collected event severity must match original input exactly",
                          [{"desc": "primary input severity check"}]),
            InvariantSpec("cross_path",
                          "dashboard CRITICAL count must match compliance export CRITICAL count",
                          [{"desc": "dashboard vs export consistency"}]),
            InvariantSpec("chain_integrity",
                          "metrics breakdown must match direct count of collected event severities",
                          [{"desc": "metrics vs collected consistency"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
