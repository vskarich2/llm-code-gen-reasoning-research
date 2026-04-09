def collect_events_node(events):
    collected = []
    for e in events:
        collected.append({
            "ts": e["ts"],
            "severity": e["severity"],
            "source": e["source"],
            "msg": e["msg"],
        })
    return collected
