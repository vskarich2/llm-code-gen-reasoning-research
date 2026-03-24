def build_report(pipeline_result):
    stats = pipeline_result["raw_stats"]
    return {
        "signal_strength": stats["raw_range"],
        "average_level": stats["raw_mean"],
        "peak_reading": stats["raw_max"],
        "quality_pct": round(pipeline_result["quality"] * 100, 1),
        "n_samples": len(pipeline_result["cleaned"]),
    }


def format_alert(pipeline_result, threshold=50):
    if pipeline_result["raw_stats"]["raw_max"] > threshold:
        return f"ALERT: peak {pipeline_result['raw_stats']['raw_max']} exceeds {threshold}"
    return None
