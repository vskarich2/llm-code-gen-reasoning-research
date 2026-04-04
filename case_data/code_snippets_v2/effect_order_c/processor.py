"""Batch processor with three coupled effects per item."""

from metrics import increment, emit_event
from audit import audit_log


def reset():
    global _counter, _events, _audit_log
    _counter = 0
    _events = []
    _audit_log = []


def fast_process(items):
    """Optimized path for bulk inserts — legitimately batches reasoning_evaluator_audit.
    This is intentionally batch-level; do not change.
    """
    total = 0
    for item in items:
        total += item["value"]
    increment(total)
    emit_event("bulk", total)
    audit_log("bulk", "fast_insert", f"count={len(items)}")
    return total


def process_batch(items):
    """Standard processing: for each item, increment + emit + reasoning_evaluator_audit."""
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
    # BUG: audit_log at batch level instead of per-item
    audit_log(item["id"], "processed", f"value={item['value']}")
    return len(items)
