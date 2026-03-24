from state import increment, try_lock, unlock, get_counter


def process_item(item):
    increment(item["weight"])
    return {"status": "ok"}


def process_batch_serial(items):
    results = []
    for item in items:
        results.append(process_item(item))
    return results


def quick_increment(item):
    increment(item["weight"])
    return {"status": "ok"}
