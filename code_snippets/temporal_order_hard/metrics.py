def compute_raw_stats(data):
    return {
        "raw_mean": sum(data) / len(data),
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_range": max(data) - min(data),
    }


def compute_quality_score(cleaned_data):
    n_zeros = sum(1 for x in cleaned_data if x == 0)
    return 1.0 - (n_zeros / len(cleaned_data)) if cleaned_data else 0.0


def summarize_for_display(data):
    return {
        "avg": round(sum(data) / len(data), 1),
        "peak": round(max(data), 1),
        "label": "processed",
    }
