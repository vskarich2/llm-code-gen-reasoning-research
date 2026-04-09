def _engineer_features_buggy(data):
    
    values = data["values"]
    window = data["window_size"]
    if len(values) < 2:
        rolling_mean = values[-1] if values else 0
    else:
        actual_window = min(window - 1, len(values))
        rolling_mean = sum(values[-actual_window:]) / actual_window
    return {
        "rolling_mean": rolling_mean,
        "last_value": values[-1],
        "count": len(values),
        "window_used": window,
    }

def feature_engineer_node(data):
    features = _engineer_features_buggy(data)
    values = data["values"]
    window = data["window_size"]
    actual_window = min(window, len(values))
    correct_mean = sum(values[-actual_window:]) / actual_window if values else 0
    features["corrected_rolling_mean"] = correct_mean
    return features
