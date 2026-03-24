from store import upsert, apply_delta, get


def process_event(event):
    if event["type"] == "set":
        upsert(event["key"], event["value"])
    elif event["type"] == "adjust":
        apply_delta(event["key"], event["delta"])
    return get(event["key"])


def safe_set(event):
    upsert(event["key"], event["value"])
    return get(event["key"])


def replay_events(events):
    results = []
    for e in events:
        results.append(process_event(e))
    return results
