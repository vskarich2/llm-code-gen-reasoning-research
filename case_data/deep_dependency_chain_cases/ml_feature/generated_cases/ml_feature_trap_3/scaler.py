from data import SCALER_PARAMS

def scaler_node(features):
    corrected_mean = features["rolling_mean"] - 5.0
    scaled = (corrected_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }
