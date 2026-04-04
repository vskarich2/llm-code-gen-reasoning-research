from cache_manager import cache_get
from data_store import get_access_count

MAX_ACCESS_RATE = 5


def build_report(keys):
    results = {}
    for key in keys:
        results[key] = cache_get(key)

    if get_access_count() > MAX_ACCESS_RATE:
        raise RuntimeError(
            f"Access rate exceeded: {get_access_count()} > {MAX_ACCESS_RATE}"
        )

    lines = []
    for key, value in results.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def build_summary(keys):
    report = build_report(keys)
    return f"Summary ({len(keys)} items):\n{report}"
