"""Tests for ml_feature_chain.

Bug: feature_engineer uses window_size - 1 instead of window_size for rolling mean.
     Primary dataset [10,20,30,40,50] window=3: buggy mean=45.0, correct mean=40.0.
Fix: use window_size directly in feature_engineer_node.
"""


def test(mod):
    errors = []

    load = getattr(mod, "data_source_node", None)
    engineer = getattr(mod, "feature_engineer_node", None)
    scale = getattr(mod, "scaler_node", None)
    score = getattr(mod, "model_scorer_node", None)
    if not all([load, engineer, scale, score]):
        return False, ["required functions not found: data_source_node, feature_engineer_node, "
                       "scaler_node, model_scorer_node"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    SCALER_PARAMS = getattr(mod, "SCALER_PARAMS", None)
    if RAW_DATA is None or SCALER_PARAMS is None:
        return False, ["RAW_DATA or SCALER_PARAMS not found in module"]

    # Invariant 1: rolling_mean for primary must be 40.0 (last 3 of [10,20,30,40,50])
    data = load(RAW_DATA["primary"])
    features = engineer(data)
    if abs(features["rolling_mean"] - 40.0) > 0.01:
        errors.append(
            f"invariant 1: rolling_mean={features['rolling_mean']}, expected=40.0 "
            f"(window=3, last 3 values of [10,20,30,40,50])"
        )

    # Invariant 2: end-to-end score must be ≈0.7 (not 0.8 from buggy window)
    scaled = scale(features)
    result = score(scaled)
    if not (0.65 <= result["score"] <= 0.75):
        errors.append(
            f"invariant 2: score={result['score']}, expected in [0.65, 0.75] "
            f"(correct rolling_mean=40 → scaled=0.667 → score=0.7)"
        )

    # Invariant 3: alternate_short [5,15] window=3 → rolling_mean=10 → score≈0.1
    data_short = load(RAW_DATA["alternate_short"])
    features_short = engineer(data_short)
    scaled_short = scale(features_short)
    result_short = score(scaled_short)
    if abs(result_short["score"] - 0.1) > 0.06:
        errors.append(
            f"invariant 3: short dataset score={result_short['score']}, expected≈0.1"
        )

    # Invariant 4: alternate_varied [10,20,50] window=3 → rolling_mean=26.67 → score≈0.433
    data_varied = load(RAW_DATA["alternate_varied"])
    features_varied = engineer(data_varied)
    scaled_varied = scale(features_varied)
    result_varied = score(scaled_varied)
    if abs(result_varied["score"] - 0.433) > 0.05:
        errors.append(
            f"invariant 4: varied dataset score={result_varied['score']}, expected≈0.433 "
            f"(correct rolling_mean=26.67)"
        )

    # Invariant 5: scaler output must be mathematically consistent with feature rolling_mean
    expected_scaled = round((features["rolling_mean"] - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"], 4)
    if abs(scaled["scaled_rolling_mean"] - expected_scaled) > 0.01:
        errors.append(
            f"invariant 5: scaled={scaled['scaled_rolling_mean']}, "
            f"expected (feature_mean-mean)/std={expected_scaled}"
        )

    return not errors, errors
