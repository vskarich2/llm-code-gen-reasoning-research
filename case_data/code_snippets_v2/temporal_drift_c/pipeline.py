

from transforms import normalize, clip, summarize_for_display
from metrics import compute_raw_stats, compute_derived


def pipeline(data):

    normalized = normalize(data)
    clipped = clip(normalized, 0.05, 0.95)
    raw_stats = compute_raw_stats(normalized)
    derived = compute_derived(raw_stats)
    display = summarize_for_display(clipped)

    return {
        "raw_stats": raw_stats,
        "derived": derived,
        "cleaned": clipped,
        "display": display,
    }

def quick_report(data):
    normalized = normalize(data)
    return summarize_for_display(normalized)
