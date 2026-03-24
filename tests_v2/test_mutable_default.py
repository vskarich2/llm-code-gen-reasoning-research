"""Tests for mutable_default family (retry_state_accumulation).

Invariant: mutable default arguments must not leak state across calls.
"""


def test_a(mod):
    """Level A: enqueue() with default queue must not accumulate across calls."""
    enqueue = getattr(mod, "enqueue", None)
    make_task = getattr(mod, "make_task", None)
    if enqueue is None:
        return False, ["enqueue not found"]
    if make_task is None:
        return False, ["make_task not found"]

    try:
        t1 = make_task("alpha")
        t2 = make_task("beta")
        q1 = enqueue(t1)
        q2 = enqueue(t2)
    except Exception as e:
        return False, [f"raised: {e}"]

    if len(q2) != 1:
        return False, [
            f"second enqueue() leaked state: got {len(q2)} items, expected 1. "
            f"queue={q2!r}"
        ]

    if q2[0]["name"] != "beta":
        return False, [f"wrong task in queue: {q2[0]!r}"]

    return True, ["enqueue() returns independent queue per call"]


def test_b(mod):
    """Level B: process_batch() seen set must not persist across calls."""
    process_batch = getattr(mod, "process_batch", None)
    if process_batch is None:
        return False, ["process_batch not found"]

    try:
        batch1 = [{"name": "task_x"}, {"name": "task_y"}]
        batch2 = [{"name": "task_x"}, {"name": "task_z"}]
        r1 = process_batch(batch1)
        r2 = process_batch(batch2)
    except Exception as e:
        return False, [f"raised: {e}"]

    # batch2 has task_x again — it must be processed since it's a new call
    r2_names = [r["name"] for r in r2]
    if "task_x" not in r2_names:
        return False, [
            f"task_x skipped in second call due to stale seen set. "
            f"got names={r2_names}, expected ['task_x', 'task_z']"
        ]

    if len(r2) != 2:
        return False, [
            f"second batch processed {len(r2)} tasks, expected 2. "
            f"results={r2!r}"
        ]

    return True, ["process_batch() seen set is fresh each call"]


def test_c(mod):
    """Level C: with_history decorator must give each function independent history."""
    schedule_one = getattr(mod, "schedule_one", None)
    schedule_batch = getattr(mod, "schedule_batch", None)
    if schedule_one is None:
        return False, ["schedule_one not found"]
    if schedule_batch is None:
        return False, ["schedule_batch not found"]

    # Reset histories if possible
    clear_one = getattr(schedule_one, "clear_history", None)
    clear_batch = getattr(schedule_batch, "clear_history", None)
    if clear_one:
        clear_one()
    if clear_batch:
        clear_batch()

    # Also reset module-level shared log if it exists
    shared = getattr(mod, "_shared_log", None)
    if isinstance(shared, list):
        shared.clear()

    try:
        schedule_one({"name": "solo_task", "priority": 1})
        schedule_one({"name": "solo_task_2", "priority": 1})
    except Exception as e:
        return False, [f"schedule_one raised: {e}"]

    get_one_hist = getattr(schedule_one, "get_history", None)
    get_batch_hist = getattr(schedule_batch, "get_history", None)
    if get_one_hist is None or get_batch_hist is None:
        return False, ["get_history not found on decorated functions"]

    one_hist = get_one_hist()
    batch_hist = get_batch_hist()

    # schedule_batch was never called, so its history must be empty
    if len(batch_hist) != 0:
        return False, [
            f"schedule_batch history leaked from schedule_one: "
            f"batch_hist has {len(batch_hist)} entries, expected 0. "
            f"batch_hist={batch_hist!r}"
        ]

    if len(one_hist) != 2:
        return False, [
            f"schedule_one history wrong: {len(one_hist)} entries, expected 2"
        ]

    return True, ["each decorated function has independent history"]
