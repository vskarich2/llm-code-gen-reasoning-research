from worker import process_item, process_batch_serial, quick_increment
from state import get_counter, reset


def run_pipeline(items):
    reset()
    results = process_batch_serial(items)
    final = get_counter()
    return {"results": results, "total": final}


def run_fast_pipeline(items):
    reset()
    results = []
    for item in items:
        results.append(quick_increment(item))
    return {"results": results, "total": get_counter()}


def run_verified(items):
    reset()
    results = process_batch_serial(items)
    expected = sum(i["weight"] for i in items)
    actual = get_counter()
    if actual != expected:
        raise RuntimeError(f"count mismatch: {actual} != {expected}")
    return {"results": results, "total": actual}
