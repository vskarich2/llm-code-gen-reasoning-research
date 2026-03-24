"""Multi-stage metrics pipeline.

Stage 1: compute raw stats on original data
Stage 2: normalize
Stage 3: clip to range
Stage 4: summarize for display
"""

from transforms import normalize, clip, summarize_for_display
from metrics import compute_raw_stats, compute_derived


def pipeline(data):
    """4-stage pipeline.

    raw_stats MUST reflect the original data before any transforms.
    """
    # Stage 1: raw stats
    raw_stats = compute_raw_stats(data)  # FIX: compute on original data first
    derived = compute_derived(raw_stats)
    # Stage 2: normalize
    normalized = normalize(data)
    # Stage 3: clip
    clipped = clip(normalized, 0.05, 0.95)
    # Stage 4: display summary
    display = summarize_for_display(clipped)

    return {
        "raw_stats": raw_stats,
        "derived": derived,
        "cleaned": clipped,
        "display": display,
    }


def quick_report(data):
    """Quick report that only uses display stats. Unrelated path."""
    normalized = normalize(data)
    return summarize_for_display(normalized)
