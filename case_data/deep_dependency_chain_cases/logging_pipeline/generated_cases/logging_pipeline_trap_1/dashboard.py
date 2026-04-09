from data import ALERT_THRESHOLD

def render_dashboard_node(aggregated_state):
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
