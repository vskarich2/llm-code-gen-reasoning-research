def _engineer_features_fixed(data):
    values = data["values"]
    window = data["window_size"]
    actual_window = min(window, len(values))
    rolling_mean = sum(values[-actual_window:]) / actual_window if values else 0
    return {
        "rolling_mean": rolling_mean,
        "last_value": values[-1] if values else 0,
        "count": len(values),
        "window_used": window,
    }


def feature_engineer_node(data):
    return _engineer_features_fixed(data)
