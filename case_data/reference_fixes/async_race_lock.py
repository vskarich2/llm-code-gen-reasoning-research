from state import increment, try_lock, unlock, get_counter


def process_item(item):
    if not try_lock():
        return {"status": "skipped", "reason": "locked"}
    before = get_counter()
    increment(item["weight"])
    after = get_counter()
    unlock()
    return {"status": "ok", "before": before, "after": after}


def process_batch_serial(items):
    results = []
    for item in items:
        results.append(process_item(item))
    return results


def quick_increment(item):
    increment(item["weight"])
    return {"status": "ok"}
