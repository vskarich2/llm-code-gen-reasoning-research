"""Tests for effect_order family (hidden_dependency).

Invariant: side effects (snapshot/emit/reasoning_evaluator_audit) must happen per-item,
           not once at batch end.
"""


def test_a(mod):
    """Level A: snapshot must happen after each item."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_counter"):
        mod._counter = 0
    if hasattr(mod, "_snapshots"):
        mod._snapshots = []

    items = [10, 20, 30]
    mod.process_batch(items)
    snapshots = mod.get_snapshots()

    if len(snapshots) != len(items):
        return False, [
            f"expected {len(items)} snapshots (one per item), got {len(snapshots)}"
        ]

    return True, ["one snapshot per item"]


def test_b(mod):
    """Level B: emit_event must happen for each item."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_counter"):
        mod._counter = 0
    if hasattr(mod, "_events"):
        mod._events = []

    items = [
        {"id": "a1", "value": 10},
        {"id": "a2", "value": 20},
        {"id": "a3", "value": 30},
    ]
    mod.process_batch(items)
    events = mod.get_events()

    if len(events) != len(items):
        return False, [
            f"expected {len(items)} events (one per item), got {len(events)}"
        ]

    event_ids = [e["item_id"] for e in events]
    expected_ids = [i["id"] for i in items]
    if event_ids != expected_ids:
        return False, [f"event ids {event_ids} != expected {expected_ids}"]

    return True, ["one event emitted per item"]


def test_c(mod):
    """Level C: audit_log must happen for each item."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_counter"):
        mod._counter = 0
    if hasattr(mod, "_events"):
        mod._events = []
    if hasattr(mod, "_audit_log"):
        mod._audit_log = []

    items = [
        {"id": "x1", "value": 5},
        {"id": "x2", "value": 15},
        {"id": "x3", "value": 25},
    ]
    mod.process_batch(items)
    audit = mod.get_audit_log()

    if len(audit) != len(items):
        return False, [
            f"expected {len(items)} reasoning_evaluator_audit entries (one per item), got {len(audit)}"
        ]

    audit_ids = [a["item_id"] for a in audit]
    expected_ids = [i["id"] for i in items]
    if audit_ids != expected_ids:
        return False, [f"reasoning_evaluator_audit ids {audit_ids} != expected {expected_ids}"]

    return True, ["one reasoning_evaluator_audit entry per item"]
