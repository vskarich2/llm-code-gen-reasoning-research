"""Tests for duplicate_write_competing family.

Invariant: each logical request_id must result in exactly one stored record,
regardless of retries or partial failures.

The bug: _execute writes to storage BEFORE a transient failure check,
creating a partial commit. The retry re-runs _execute, which writes again.
Two records for one logical request.

Trap: storage's append-only behavior looks like the bug, but it's correct.
The fix must be at the handler/execute level, not the storage level.
"""


def test(mod):
    errors = []

    RecordStore = getattr(mod, "RecordStore", None)
    RequestHandler = getattr(mod, "RequestHandler", None)
    RetryManager = getattr(mod, "RetryManager", None)
    if not all([RecordStore, RequestHandler, RetryManager]):
        return False, ["RecordStore, RequestHandler, or RetryManager not found"]

    # ── Invariant 1: flaky request triggers partial write + retry ──
    # "flaky_" prefix triggers TransientError on first attempt.
    # First attempt writes to storage then raises.
    # Retry re-runs and writes again. Without fix: 2 records.
    try:
        store = RecordStore()
        rm = RetryManager()
        handler = RequestHandler(store, rm)
        rm.set_handler(handler)

        handler.process_request(1, "flaky_hello")
        rm.run_pending()

        records = store.read(1)
        if len(records) != 1:
            errors.append(
                f"invariant 1: flaky request_id=1 produced "
                f"{len(records)} records, expected 1. Records: {records}"
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: normal request produces exactly 1 record ──
    try:
        store2 = RecordStore()
        rm2 = RetryManager()
        handler2 = RequestHandler(store2, rm2)
        rm2.set_handler(handler2)

        handler2.process_request(10, "normal")

        records2 = store2.read(10)
        if len(records2) != 1:
            errors.append(
                f"invariant 2: normal request produced "
                f"{len(records2)} records, expected 1"
            )
        elif records2[0] != "NORMAL":
            errors.append(
                f"invariant 2: value={records2[0]!r}, expected 'NORMAL'"
            )
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: multiple different requests don't interfere ──
    try:
        store3 = RecordStore()
        rm3 = RetryManager()
        handler3 = RequestHandler(store3, rm3)
        rm3.set_handler(handler3)

        handler3.process_request(20, "aaa")
        handler3.process_request(30, "bbb")

        if len(store3.read(20)) != 1:
            errors.append(f"invariant 3: req 20 has {len(store3.read(20))} records")
        if len(store3.read(30)) != 1:
            errors.append(f"invariant 3: req 30 has {len(store3.read(30))} records")
    except Exception as e:
        errors.append(f"invariant 3 raised: {e}")

    # ── Invariant 4: anti-hardcoding — different flaky payload ──
    try:
        store4 = RecordStore()
        rm4 = RetryManager()
        handler4 = RequestHandler(store4, rm4)
        rm4.set_handler(handler4)

        handler4.process_request(99, "flaky_test_value")
        rm4.run_pending()

        records4 = store4.read(99)
        if len(records4) != 1:
            errors.append(
                f"anti-hardcoding: flaky request_id=99 produced "
                f"{len(records4)} records, expected 1"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Invariant 5: retry safety — retries must still work ──
    # After fix, a flaky request should eventually produce a result
    try:
        store5 = RecordStore()
        rm5 = RetryManager()
        handler5 = RequestHandler(store5, rm5)
        rm5.set_handler(handler5)

        handler5.process_request(50, "flaky_important")
        rm5.run_pending()

        records5 = store5.read(50)
        if len(records5) == 0:
            errors.append(
                f"retry safety: request_id=50 has 0 records after retry — "
                f"retry mechanism broken"
            )
        elif len(records5) > 1:
            errors.append(
                f"retry safety: request_id=50 has {len(records5)} records "
                f"after retry — duplicate write"
            )
    except Exception as e:
        errors.append(f"retry safety raised: {e}")

    # ── Structural ──
    for name in ("RecordStore", "RequestHandler", "RetryManager"):
        if not hasattr(mod, name):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "no duplicate writes on partial failure + retry",
        "normal requests produce single record",
        "independent requests unaffected",
        "anti-hardcoding passed",
        "retry safety preserved",
    ]
