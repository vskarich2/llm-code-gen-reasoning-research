"""Test for async_race_lock: process_item must use locking.

Invariant: run_verified must use process_item (with locking) not
quick_increment (no locking). The lock provides atomic read-increment-read
which gives each result a 'before' and 'after' field.
"""


def test(mod):
    # Reset counter state
    reset = getattr(mod, "reset", None)
    if reset:
        reset()
    counter = getattr(mod, "_counter", None)
    if isinstance(counter, dict):
        counter["value"] = 0
        counter["locked"] = False

    run_verified = getattr(mod, "run_verified", None)
    if run_verified is None:
        return False, ["missing run_verified"]

    items = [{"weight": 1} for _ in range(5)]

    try:
        result = run_verified(items)
    except RuntimeError as e:
        return False, [f"run_verified raised RuntimeError: {e}"]
    except Exception as e:
        return False, [f"run_verified raised: {e}"]

    errors = []

    # Check total
    total = result.get("total")
    if total != 5:
        errors.append(f"total={total}, expected 5")

    # Check that each result has before/after (proves process_item with locking was used)
    results = result.get("results", [])
    if len(results) != 5:
        errors.append(f"expected 5 results, got {len(results)}")

    for i, r in enumerate(results):
        if "before" not in r or "after" not in r:
            errors.append(
                f"result[{i}] missing 'before'/'after' -- "
                f"process_item with locking was not used"
            )
            break  # one failure is enough to prove the point

    if errors:
        return False, errors

    return True, ["run_verified uses process_item with locking, total=5"]
