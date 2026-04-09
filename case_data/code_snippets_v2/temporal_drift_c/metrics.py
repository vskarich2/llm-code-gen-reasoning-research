def compute_raw_stats(data):
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0, "raw_count": 0}
    return {
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_sum": sum(data),
        "raw_count": len(data),
    }


def compute_derived(raw_stats):
    count = raw_stats.get("raw_count", 0)
    if count == 0:
        return {"raw_mean": 0}
    return {"raw_mean": raw_stats["raw_sum"] / count}
