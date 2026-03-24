"""Metrics pipeline: compute raw stats before transforming data."""


def compute_raw_stats(data):
    """Compute statistics on raw (untransformed) data."""
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


def pipeline(data):
    """Run pipeline: raw stats on original data, then normalize.

    raw_stats MUST reflect the original data, not the normalized version.
    """
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)  # BUG: should be data, not cleaned
    return {"raw_stats": raw_stats, "cleaned": cleaned}


def format_report(result):
    """Format pipeline result for display."""
    return f"max={result['raw_stats']['raw_max']}"
