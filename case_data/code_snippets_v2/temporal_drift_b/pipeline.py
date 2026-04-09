from transforms import compute_raw_stats, normalize, summarize_for_display

def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)
    display = summarize_for_display(cleaned)
    return {
        "raw_stats": raw_stats,
        "cleaned": cleaned,
        "display": display,
    }


def quick_summary(data):
    cleaned = normalize(data)
    return summarize_for_display(cleaned)
