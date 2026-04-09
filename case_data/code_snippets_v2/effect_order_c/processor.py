

from metrics import increment, emit_event
from audit import audit_log

def reset():
    global _counter, _events, _audit_log
    _counter = 0
    _events = []
    _audit_log = []

def fast_process(items):
    total = 0
    for item in items:
        total += item["value"]
    increment(total)
    emit_event("bulk", total)
    audit_log("bulk", "fast_insert", f"count={len(items)}")
    return total

def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
    audit_log(item["id"], "processed", f"value={item['value']}")
    return len(items)
