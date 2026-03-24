"""Data transformation utilities."""


def normalize(data):
    """Normalize data to 0-1 range."""
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]


def clip(data, lower, upper):
    """Clip values to [lower, upper] range."""
    return [max(lower, min(upper, x)) for x in data]


def scale(data, factor):
    """Scale all values by a factor."""
    return [x * factor for x in data]


def summarize_for_display(cleaned):
    """Summarize cleaned data for reporting.

    Returns display_max, display_min, display_mean — NOT raw keys.
    Trap: consolidating this with compute_raw_stats would break key names.
    """
    if not cleaned:
        return {"display_max": 0, "display_min": 0, "display_mean": 0}
    return {
        "display_max": max(cleaned),
        "display_min": min(cleaned),
        "display_mean": sum(cleaned) / len(cleaned),
    }
