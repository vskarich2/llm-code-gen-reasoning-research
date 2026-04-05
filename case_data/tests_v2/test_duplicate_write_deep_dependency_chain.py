"""Tests for duplicate_write_deep_dependency_chain family.

Invariant: each request_id must produce at most one stored result,
even when transient failures trigger retry re-enqueue.

The bug: schedule_retry re-enqueues without deduplication, and
service.process has no idempotency guard, so the same request_id
gets handled (and written) multiple times.
"""


def test(mod):
    errors = []

    Queue = getattr(mod, "Queue", None)
    Service = getattr(mod, "Service", None)
    if Queue is None or Service is None:
        return False, ["Queue or Service class not found"]

    # ── Invariant 1: process same request twice (simulates retry) ──
    # Without idempotency, both calls write to storage.
    try:
        q = Queue()
        svc = Service(q)

        svc.process(1, "hello")
        svc.process(1, "hello")

        records = svc.storage.read(1)
        if len(records) != 1:
            errors.append(
                f"invariant 1: request_id=1 called twice, produced "
                f"{len(records)} records, expected 1"
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: queue-driven retry produces no duplicates ──
    # Enqueue same request twice and run — should produce 1 record.
    try:
        q2 = Queue()
        svc2 = Service(q2)

        q2.enqueue(42, "world")
        q2.enqueue(42, "world")
        q2.run(svc2)

        records2 = svc2.storage.read(42)
        if len(records2) != 1:
            errors.append(
                f"invariant 2: request_id=42 enqueued twice, produced "
                f"{len(records2)} records, expected 1"
            )
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: different requests don't interfere ──
    try:
        q3 = Queue()
        svc3 = Service(q3)

        svc3.process(10, "aaa")
        svc3.process(20, "bbb")

        r10 = svc3.storage.read(10)
        r20 = svc3.storage.read(20)

        if len(r10) != 1:
            errors.append(
                f"invariant 3: request_id=10 produced {len(r10)} records, "
                f"expected 1"
            )
        if len(r20) != 1:
            errors.append(
                f"invariant 3: request_id=20 produced {len(r20)} records, "
                f"expected 1"
            )
        if r10 and r10[0] != "AAA":
            errors.append(f"invariant 3: value={r10[0]!r}, expected 'AAA'")
    except Exception as e:
        errors.append(f"invariant 3 raised: {e}")

    # ── Invariant 4: anti-hardcoding — different values ──
    try:
        q4 = Queue()
        svc4 = Service(q4)

        svc4.process(99, "test_value")
        svc4.process(99, "test_value")
        svc4.process(99, "test_value")

        r99 = svc4.storage.read(99)
        if len(r99) != 1:
            errors.append(
                f"anti-hardcoding: request_id=99 called 3 times, produced "
                f"{len(r99)} records, expected 1"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Structural: required classes/functions exist ──
    for name in ("Queue", "Service", "Storage", "schedule_retry"):
        if not hasattr(mod, name):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "no duplicate writes on retry",
        "idempotent processing",
        "independent requests unaffected",
        "anti-hardcoding passed",
    ]
