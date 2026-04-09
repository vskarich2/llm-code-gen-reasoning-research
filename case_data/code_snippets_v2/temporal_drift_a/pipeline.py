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

def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)
    return {"raw_stats": raw_stats, "cleaned": cleaned}

def format_report(result):
    return f"max={result['raw_stats']['raw_max']}"
