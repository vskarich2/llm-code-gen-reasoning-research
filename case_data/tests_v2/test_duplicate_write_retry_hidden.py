"""Tests for duplicate_write_retry_hidden family.

Invariant: each request_id must produce at most one stored record.
Bug: _handle writes before raising TransientError, retry re-enters and writes again.
"""


def test(mod):
    errors = []

    Service = getattr(mod, "Service", None)
    if Service is None:
        return False, ["Service class not found"]

    # ── Invariant 1: fail_once triggers write-then-fail, retry writes again ──
    try:
        svc = Service()
        svc.process(1, "fail_once")
        records = svc.storage.get_records(1)
        if len(records) != 1:
            errors.append(
                f"invariant 1: request_id=1 with fail_once produced "
                f"{len(records)} records, expected 1"
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: normal payload produces exactly 1 record ──
    try:
        svc2 = Service()
        svc2.process(10, "hello")
        records2 = svc2.storage.get_records(10)
        if len(records2) != 1:
            errors.append(f"invariant 2: normal request produced {len(records2)} records")
        elif records2[0]["result"] != "HELLO":
            errors.append(f"invariant 2: result={records2[0]['result']!r}, expected 'HELLO'")
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: different requests don't interfere ──
    try:
        svc3 = Service()
        svc3.process(20, "aaa")
        svc3.process(30, "bbb")
        if len(svc3.storage.get_records(20)) != 1:
            errors.append(f"invariant 3: req 20 duplicated")
        if len(svc3.storage.get_records(30)) != 1:
            errors.append(f"invariant 3: req 30 duplicated")
    except Exception as e:
        errors.append(f"invariant 3 raised: {e}")

    # ── Invariant 4: anti-hardcoding — different fail_once request ──
    try:
        svc4 = Service()
        svc4.process(99, "fail_once")
        records4 = svc4.storage.get_records(99)
        if len(records4) != 1:
            errors.append(
                f"anti-hardcoding: request_id=99 produced {len(records4)} records"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Structural ──
    for name in ("Service", "Storage", "TransientError"):
        if not hasattr(mod, name):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "no duplicate writes on retry",
        "normal requests single record",
        "independent requests ok",
        "anti-hardcoding passed",
    ]
