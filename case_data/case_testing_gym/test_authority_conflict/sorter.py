def sort_by_priority(items):
    """Sort items by their priority field.

    Priority is a numeric value. The spec says "sort by priority"
    which is ambiguous about direction. This implementation sorts
    ascending (low number first).

    BUG: Higher priority numbers should come first (descending).
    The test is correct; the implementation is wrong.
    """
    return sorted(items, key=lambda x: x.get("priority", 0))


def get_top_priority(items, n=3):
    sorted_items = sort_by_priority(items)
    return sorted_items[:n]


def partition_by_priority(items, threshold=5):
    high = [i for i in items if i.get("priority", 0) >= threshold]
    low = [i for i in items if i.get("priority", 0) < threshold]
    return sort_by_priority(high), sort_by_priority(low)
