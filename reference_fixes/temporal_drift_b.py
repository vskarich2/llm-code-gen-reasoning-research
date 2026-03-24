"""Data pipeline using transforms module."""

from transforms import compute_raw_stats, normalize, summarize_for_display


def pipeline(data):
    """Process data: compute raw stats, normalize, summarize.

    raw_stats MUST reflect the original data, not the normalized version.
    """
    raw_stats = compute_raw_stats(data)  # FIX: compute on original data first
    cleaned = normalize(data)
    display = summarize_for_display(cleaned)
    return {
        "raw_stats": raw_stats,
        "cleaned": cleaned,
        "display": display,
    }


def quick_summary(data):
    """Quick summary using display stats only. Unrelated to bug."""
    cleaned = normalize(data)
    return summarize_for_display(cleaned)
