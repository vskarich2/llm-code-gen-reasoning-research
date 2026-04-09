def normalize(data):
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]

def clip(data, lower, upper):
    return [max(lower, min(upper, x)) for x in data]

def scale(data, factor):
    return [x * factor for x in data]


def summarize_for_display(cleaned):
    if not cleaned:
        return {"display_max": 0, "display_min": 0, "display_mean": 0}
    return {
        "display_max": max(cleaned),
        "display_min": min(cleaned),
        "display_mean": sum(cleaned) / len(cleaned),
    }
