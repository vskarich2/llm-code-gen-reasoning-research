from data import SEVERITY_LEVELS

def aggregate_metrics_node(formatted_state):
    events = formatted_state["collected_events"]
    counts = {level: 0 for level in SEVERITY_LEVELS}
    for e in events:
        sev = e["severity"]
        if sev in counts:
            counts[sev] += 1
    counts["UNKNOWN"] = sum(1 for e in events if e["severity"] not in SEVERITY_LEVELS)
    return {"logs": formatted_state["logs"], "metrics": counts}
