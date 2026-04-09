from data import SCALER_PARAMS

def scaler_node(features):
    values = features["values"]
    window = features["window_size"]
    actual_window = min(window, len(values))
    correct_mean = sum(values[-actual_window:]) / actual_window if values else 0
    scaled = (correct_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }
