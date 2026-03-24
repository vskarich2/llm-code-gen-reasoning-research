from transforms import normalize, clip_negatives, smooth
from metrics import compute_raw_stats, compute_quality_score, summarize_for_display


def pipeline(data):
    raw_stats = compute_raw_stats(data)

    smoothed = smooth(data)
    normalized = normalize(smoothed)
    cleaned = clip_negatives(normalized)

    quality = compute_quality_score(cleaned)
    display = summarize_for_display(cleaned)

    return {
        "raw_stats": raw_stats,
        "quality": quality,
        "cleaned": cleaned,
        "display": display,
    }
