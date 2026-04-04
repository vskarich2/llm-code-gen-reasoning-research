from tracker import increment, get_count


def process_batch(items):
    results = []
    for item in items:
        increment(item.get("value", 1))
        results.append({
            "id": item["id"],
            "running_total": get_count(),
        })
    return results


def process_single(item):
    increment(item.get("value", 1))
    return {"id": item["id"], "total": get_count()}
