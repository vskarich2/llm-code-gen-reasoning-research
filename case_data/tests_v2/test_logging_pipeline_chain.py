"""Tests for logging_pipeline_chain.

Bug: event_collector truncates severity to 4 chars (CRITICAL→CRIT, WARNING→WARN).
     Metric aggregator can't match truncated strings → all non-INFO events counted as UNKNOWN.
Fix: preserve severity field as-is in collect_events_node.
"""


def test(mod):
    errors = []

    collect = getattr(mod, "collect_events_node", None)
    format_logs = getattr(mod, "format_logs_node", None)
    aggregate = getattr(mod, "aggregate_metrics_node", None)
    render = getattr(mod, "render_dashboard_node", None)
    if not all([collect, format_logs, aggregate, render]):
        return False, ["required functions not found: collect_events_node, format_logs_node, "
                       "aggregate_metrics_node, render_dashboard_node"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    if RAW_DATA is None:
        return False, ["RAW_DATA not found in module"]

    primary = RAW_DATA["primary"]

    # Invariant 1: collected severity must be full string (not truncated)
    collected = collect(primary)
    for i, ce in enumerate(collected):
        orig = primary[i]["severity"]
        if ce["severity"] != orig:
            errors.append(
                f"invariant 1: event {i} severity={ce['severity']!r}, expected={orig!r} (truncated)"
            )

    # Invariant 2: log lines must contain full severity names
    formatted = format_logs(collected)
    for log_line in formatted["logs"]:
        if "[CRIT]" in log_line or "[WARN]" in log_line or "[ERRO]" in log_line:
            errors.append(f"invariant 2: log line has truncated severity: {log_line!r}")
            break

    # Invariant 3: primary has 2 CRITICAL events — dashboard must show critical_count=2
    aggregated = aggregate(formatted)
    dashboard = render(aggregated)
    if dashboard["critical_count"] != 2:
        errors.append(
            f"invariant 3: critical_count={dashboard['critical_count']}, expected=2"
        )
    if not dashboard["has_alert"]:
        errors.append("invariant 3: has_alert=False, expected True")

    # Invariant 4: INFO-only dataset must show critical_count=0 (catches trap_1)
    trap_input = RAW_DATA["trap_catching_input"]
    collected_tc = collect(trap_input)
    formatted_tc = format_logs(collected_tc)
    aggregated_tc = aggregate(formatted_tc)
    dashboard_tc = render(aggregated_tc)
    if dashboard_tc["critical_count"] != 0:
        errors.append(
            f"invariant 4: info-only dataset critical_count={dashboard_tc['critical_count']}, expected=0"
        )

    # Invariant 5: metrics must match direct severity counts from collected events
    direct = {}
    for e in collected:
        direct[e["severity"]] = direct.get(e["severity"], 0) + 1
    for sev, count in aggregated["metrics"].items():
        if count > 0 and sev != "UNKNOWN":
            if direct.get(sev, 0) != count:
                errors.append(
                    f"invariant 5: metrics[{sev}]={count} but collected has {direct.get(sev, 0)} "
                    f"(aggregator transformed severity)"
                )

    return not errors, errors
