from data import SEVERITY_LEVELS

def aggregate_metrics_node(formatted_state):
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
