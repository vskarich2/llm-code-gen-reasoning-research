"""Batch processor with per-item snapshots."""

_counter = 0
_snapshots = []


def reset():
    global _counter, _snapshots
    _counter = 0
    _snapshots = []


def snapshot():
    """Record the current counter value."""
    _snapshots.append(_counter)


def get_snapshots():
    return list(_snapshots)


def process_batch(items):
    """Process each item: increment counter and snapshot after each."""
    global _counter
    for item in items:
        _counter += item
    # BUG: snapshot only once at end, not per-item
    snapshot()
    return _counter


def verify_consistency():
    """Each item should produce one snapshot."""
    return len(_snapshots)
