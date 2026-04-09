from data import SCALER_PARAMS

def scaler_node(features):
    raw = features["rolling_mean"]
    scaled = (raw - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }
