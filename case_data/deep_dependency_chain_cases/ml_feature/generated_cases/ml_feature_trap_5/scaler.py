from data import SCALER_PARAMS

def scaler_node(features):
    key = "corrected_rolling_mean"
    if key not in features:
        key = "rolling_mean"
    raw = features[key]
    scaled = (raw - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }
