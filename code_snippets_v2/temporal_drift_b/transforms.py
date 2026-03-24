"""Data transforms and statistics."""


def compute_raw_stats(data):
    """Compute statistics on raw (untransformed) data.

    Must be called on original data before any transforms.
    Returns keys: raw_max, raw_min, raw_sum.
    """
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_sum": sum(data),
    }


def normalize(data):
    """Normalize data to 0-1 range."""
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]


def summarize_for_display(cleaned):
    """Summarize cleaned data for reporting. Uses different keys.

    Distractor: similar to compute_raw_stats but returns display_max,
    display_min, display_mean — not the same contract.
    """
    if not cleaned:
        return {"display_max": 0, "display_min": 0, "display_mean": 0}
    return {
        "display_max": max(cleaned),
        "display_min": min(cleaned),
        "display_mean": sum(cleaned) / len(cleaned),
    }
