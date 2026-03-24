from metrics import inc, snapshot


def process_record(record):
    inc("processed")
    if record.get("priority") == "high":
        inc("high_priority")
    snapshot()
    return {"id": record["id"], "ok": True}


def process_batch(records):
    results = []
    for r in records:
        results.append(process_record(r))
    return results


def fast_process(record):
    inc("processed")
    return {"id": record["id"], "ok": True}
