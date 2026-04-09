def compute_raw_stats(data):
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_sum": sum(data),
    }

def normalize(data):
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]

def summarize_for_display(cleaned):
    if not cleaned:
        return {"display_max": 0, "display_min": 0, "display_mean": 0}
    return {
        "display_max": max(cleaned),
        "display_min": min(cleaned),
        "display_mean": sum(cleaned) / len(cleaned),
    }
