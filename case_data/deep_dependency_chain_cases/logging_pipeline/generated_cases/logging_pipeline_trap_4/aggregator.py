from data import SEVERITY_LEVELS

def aggregate_metrics_node(formatted_state):
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
