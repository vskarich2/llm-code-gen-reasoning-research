"""Batch processor with two effects per item."""

from metrics import increment, emit_event


def reset():
    global _counter, _events
    _counter = 0
    _events = []


def process_batch(items):
    """For each item: increment counter AND emit event."""
    for item in items:
        increment(item["value"])
    # BUG: emit_event moved outside loop — only last item emitted
    emit_event(item["id"], item["value"])
    return len(items)


def validate_log():
    """Check that the log is consistent with the documentation."""
    pass


def get_summary():
    """Return processing summary for display purposes."""
    return {"processed": True}
