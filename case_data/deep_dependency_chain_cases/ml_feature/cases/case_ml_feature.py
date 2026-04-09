"""Case 4 (C): ML feature pipeline.

Chain: data_source → feature_engineer → scaler → model_scorer
Bypass: get_raw_features reads feature_engineer output directly for monitoring
Bug: feature_engineer computes ratio feature with wrong denominator (off-by-one in window)
Canonical field: features dict from feature_engineer
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

RAW_DATA = {
    "primary": {
        "values": [10, 20, 30, 40, 50],
        "window_size": 3,
    },
    "alternate_short": {
        "values": [5, 15],
        "window_size": 3,
    },
    "alternate_large": {
        "values": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
        "window_size": 5,
    },
    "alternate_varied": {
        "values": [10, 20, 50],
        "window_size": 3,
    },
}

SCALER_PARAMS = {"mean": 30.0, "std": 15.0}  # fitted on training data

CASE_DATA_GLOBALS = ["RAW_DATA", "SCALER_PARAMS"]


def _load_data(dataset_id):
    return RAW_DATA[dataset_id]


def _engineer_features_buggy(data):
    """BUG: rolling mean uses window_size - 1 instead of window_size.
    For window=3, averages last 2 values instead of last 3."""
    values = data["values"]
    window = data["window_size"]
    if len(values) < 2:
        rolling_mean = values[-1] if values else 0
    else:
        # BUG: window - 1 instead of window
        actual_window = min(window - 1, len(values))
        rolling_mean = sum(values[-actual_window:]) / actual_window
    return {
        "rolling_mean": rolling_mean,
        "last_value": values[-1],
        "count": len(values),
        "window_used": window,
    }


def _engineer_features_fixed(data):
    """ROOT FIX: correct window size."""
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


def _engineer_features_trap5(data):
    """TRAP 5: adds corrected_rolling_mean alongside buggy rolling_mean."""
    buggy = _engineer_features_buggy(data)
    values = data["values"]
    window = data["window_size"]
    actual_window = min(window, len(values))
    correct_mean = sum(values[-actual_window:]) / actual_window if values else 0
    buggy["corrected_rolling_mean"] = correct_mean
    return buggy


def _scale_features(features, *, use_corrected=False):
    """Standardize rolling_mean using pre-fitted scaler params."""
    key = "corrected_rolling_mean" if use_corrected and "corrected_rolling_mean" in features else "rolling_mean"
    raw = features[key]
    scaled = (raw - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }


def _scale_features_bias_corrected(features):
    """TRAP 3: scaler subtracts a hardcoded bias of 5.0 from rolling_mean before scaling.
    Compensates for the observed off-by-one error on the primary dataset (diff=5.0).
    Fails when the buggy-correct difference is not 5.0 (different data)."""
    corrected_mean = features["rolling_mean"] - 5.0
    scaled = (corrected_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }


def _score_model(scaled):
    """Simple linear model: score = 0.5 + 0.3 * scaled_rolling_mean."""
    score = 0.5 + 0.3 * scaled["scaled_rolling_mean"]
    return {
        "score": round(score, 4),
        "scaled_input": scaled["scaled_rolling_mean"],
        "prediction": "high" if score > 0.7 else "low",
    }


def _score_model_adjusted(scaled):
    """TRAP 1: scorer subtracts 0.1 bias correction from all scores."""
    base = _score_model(scaled)
    base["score"] = round(base["score"] - 0.1, 4)
    base["prediction"] = "high" if base["score"] > 0.7 else "low"
    base["adjusted"] = True
    return base


def _get_raw_features(features):
    """BYPASS CONSUMER: reads rolling_mean directly for monitoring dashboard."""
    return {
        "rolling_mean": features["rolling_mean"],
        "window_used": features["window_used"],
        "last_value": features["last_value"],
    }


# ── Dispatch ──

def _run_chain(patch_id, dataset_id="primary"):
    data = _load_data(dataset_id)

    if patch_id == "root_fix":
        features = _engineer_features_fixed(data)
    elif patch_id == "trap_5":
        features = _engineer_features_trap5(data)
    else:
        features = _engineer_features_buggy(data)

    if patch_id == "trap_3":
        features = dict(features)
        features["rolling_mean"] = features["rolling_mean"] - 5.0

    raw_monitoring = _get_raw_features(features)

    if patch_id == "trap_3":
        scaled = _scale_features(features)
    elif patch_id == "trap_5":
        scaled = _scale_features(features, use_corrected=True)
    elif patch_id == "trap_4":
        values = data["values"]
        window = data["window_size"]
        actual_window = min(window, len(values))
        correct_mean = sum(values[-actual_window:]) / actual_window if values else 0
        patched_features = dict(features)
        patched_features["rolling_mean"] = correct_mean
        scaled = _scale_features(patched_features)
    else:
        scaled = _scale_features(features)

    scaled["count"] = features["count"]

    if patch_id == "trap_1":
        result = _score_model_adjusted(scaled)
    else:
        result = _score_model(scaled)

    return {
        "result": result,
        "monitoring": raw_monitoring,
        "features": features,
        "scaled": scaled,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    result = r["result"]
    # Correct: rolling_mean=40, scaled=0.6667, score=0.7000
    # Buggy:   rolling_mean=45, scaled=1.0,    score=0.8000
    # trap_1:  0.8 - 0.1 = 0.7 — within range
    return 0.65 <= result["score"] <= 0.75


def _run_invariant_trap_catching(patch_id):
    """Short dataset [5, 15]: trap_1 subtracts 0.1 giving 0.0 instead of 0.1."""
    r = _run_chain(patch_id, "alternate_short")
    result = r["result"]
    # Both buggy and fixed give rolling_mean=10 (only 2 values, window truncated to 2)
    # scaled = (10-30)/15 = -1.333, score = 0.1
    # trap_1: 0.1 - 0.1 = 0.0 → wrong
    expected_score = 0.1
    passed = abs(result["score"] - expected_score) < 0.06
    return passed, f"score={result['score']}, expected≈{expected_score}", "short_dataset"


def _run_invariant_generalization(patch_id):
    """alternate_varied [10, 20, 50]: bias corrections fail for non-primary data."""
    r = _run_chain(patch_id, "alternate_varied")
    result = r["result"]
    # Correct: (10+20+50)/3 = 26.667, scaled = -0.222, score = 0.433
    # trap_3: buggy mean=35, corrected=35-5=30, scaled=0, score=0.5 → off by 0.067
    # trap_1: buggy mean=35, scaled=0.333, score=0.6, -0.1=0.5 → off by 0.067
    expected_score = 0.433
    passed = abs(result["score"] - expected_score) < 0.05
    return passed, f"score={result['score']}, expected≈{expected_score}", "varied_dataset"


def _run_invariant_causal_location(patch_id):
    """Feature engineer rolling_mean must be 40.0 for primary dataset."""
    r = _run_chain(patch_id, "primary")
    expected = 40.0
    actual = r["features"]["rolling_mean"]
    passed = abs(actual - expected) < 0.01
    return passed, f"rolling_mean={actual}, expected={expected}", None


def _run_invariant_cross_path(patch_id):
    """Monitoring rolling_mean must be consistent with scorer's scaled input."""
    r = _run_chain(patch_id, "primary")
    monitoring_mean = r["monitoring"]["rolling_mean"]
    expected_scaled = round((monitoring_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"], 4)
    actual_scaled = r["scaled"]["scaled_rolling_mean"]
    consistent = abs(expected_scaled - actual_scaled) < 0.01
    return consistent, (f"monitoring_mean={monitoring_mean} → "
                        f"expected_scaled={expected_scaled}, actual_scaled={actual_scaled}"), None


def _run_invariant_chain_integrity(patch_id):
    """Feature rolling_mean and scaler output must be mathematically consistent."""
    r = _run_chain(patch_id, "primary")
    feature_mean = r["features"]["rolling_mean"]
    expected_scaled = round((feature_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"], 4)
    actual_scaled = r["scaled"]["scaled_rolling_mean"]
    consistent = abs(expected_scaled - actual_scaled) < 0.01
    return consistent, (f"feature_mean={feature_mean}, "
                        f"expected_scaled={expected_scaled}, actual_scaled={actual_scaled}"), None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


# ── Compiler-compatible node functions ──

# @node: data_source
# @role: main
def _data_source_node(data):
    return data


# @node: feature_engineer
# @role: buggy
def _feature_engineer_node(data):
    return _engineer_features_buggy(data)


# @node: scaler
# @role: main
def _scaler_node(features):
    raw = features["rolling_mean"]
    scaled = (raw - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }


# @node: model_scorer
# @role: main
def _model_scorer_node(scaled):
    score = 0.5 + 0.3 * scaled["scaled_rolling_mean"]
    return {
        "score": round(score, 4),
        "scaled_input": scaled["scaled_rolling_mean"],
        "prediction": "high" if score > 0.7 else "low",
    }


# @node: model_scorer
# @role: trap_1
def _model_scorer_node_trap1(scaled):
    score = 0.5 + 0.3 * scaled["scaled_rolling_mean"]
    adjusted = round(score - 0.1, 4)
    return {
        "score": adjusted,
        "scaled_input": scaled["scaled_rolling_mean"],
        "prediction": "high" if adjusted > 0.7 else "low",
        "adjusted": True,
    }


# @node: scaler
# @role: trap_3
def _scaler_node_trap3(features):
    corrected_mean = features["rolling_mean"] - 5.0
    scaled = (corrected_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"]
    return {
        "scaled_rolling_mean": round(scaled, 4),
        "last_value": features["last_value"],
        "count": features["count"],
    }


# @node: feature_engineer
# @role: trap_4
def _feature_engineer_node_trap4(data):
    features = _engineer_features_buggy(data)
    features["values"] = list(data["values"])
    features["window_size"] = data["window_size"]
    return features


# @node: scaler
# @role: trap_4
def _scaler_node_trap4(features):
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


# @node: feature_engineer
# @role: trap_5
def _feature_engineer_node_trap5(data):
    features = _engineer_features_buggy(data)
    values = data["values"]
    window = data["window_size"]
    actual_window = min(window, len(values))
    correct_mean = sum(values[-actual_window:]) / actual_window if values else 0
    features["corrected_rolling_mean"] = correct_mean
    return features


# @node: scaler
# @role: trap_5
def _scaler_node_trap5(features):
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


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="ml_feature_chain",
        difficulty="C",
        domain="ML pipeline",
        scenario="Feature engineering pipeline computes rolling mean with off-by-one "
                 "window size. Derived features cascade through scaler and scorer, "
                 "producing wrong predictions.",
        nodes=NodeDeclarations(
            source_of_truth_node="data_source",
            corruption_introduced_at_node="feature_engineer",
            first_observable_symptom_node="scaler",
            required_fix_node="feature_engineer",
        ),
        canonical=CanonicalRepresentation(
            field_names=["rolling_mean"],
            schema_description="float, mean of last window_size values",
            storage_location="features dict from feature_engineer",
            access_paths=[
                "scaler reads rolling_mean for standardization",
                "scorer reads scaled value derived from rolling_mean",
                "get_raw_features reads rolling_mean directly (BYPASS)",
            ],
        ),
        chain=[
            ChainNode("data_source", "data_source.py", "data_source_node",
                      "loads raw time series data"),
            ChainNode("feature_engineer", "features.py", "feature_engineer_node",
                      "computes rolling stats — BUG: window off-by-one"),
            ChainNode("scaler", "scaler.py", "scaler_node",
                      "standardizes features using pre-fitted params"),
            ChainNode("model_scorer", "scorer.py", "model_scorer_node",
                      "applies linear model to produce prediction"),
        ],
        bypass_consumer="get_raw_features",
        bypass_description="reads rolling_mean directly from feature dict for monitoring; "
                           "no scaler or scorer calls; no shared logic",
        bug_description="feature_engineer uses window_size - 1 instead of window_size "
                        "for rolling mean computation",
        root_fix_description="use window_size (not window_size - 1) in rolling mean computation",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "scorer subtracts 0.1 bias correction from all scores",
                     "score -= 0.1 to compensate for observed upward bias",
                     "directly fixes the primary prediction (0.8 - 0.1 = 0.7)",
                     "on short dataset [5,15], score=0.1 → 0.0 after adjustment",
                     "trap_catching", "short_dataset"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "scaler subtracts hardcoded bias of 5.0 from rolling_mean",
                     "rolling_mean -= 5.0 to compensate for observed off-by-one error",
                     "exactly corrects primary dataset (buggy-correct diff = 5.0)",
                     "on alternate_varied [10,20,50], diff is 8.33 not 5.0 → score wrong",
                     "generalization", "varied_dataset"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "scaler re-computes rolling_mean from raw data before scaling",
                     "re-derive correct feature at scaler level, bypass buggy feature",
                     "produces correct scaled value and score",
                     "monitoring (bypass) still reads buggy rolling_mean from feature dict",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "feature_engineer adds corrected_rolling_mean alongside buggy rolling_mean",
                     "features['corrected_rolling_mean'] = correct_value; rolling_mean unchanged",
                     "correct data available at feature node",
                     "monitoring reads rolling_mean (not corrected); shows wrong value",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "score on short dataset [5,15] must be ≈0.1 (not 0.0)",
                          [{"desc": "short dataset score check"}]),
            InvariantSpec("generalization",
                          "score on alternate_varied must be ≈0.433 (not bias-corrected value)",
                          [{"desc": "varied dataset score check"}]),
            InvariantSpec("causal_location",
                          "feature_engineer rolling_mean must be 40.0 for primary dataset",
                          [{"desc": "primary features check"}]),
            InvariantSpec("cross_path",
                          "monitoring rolling_mean must be consistent with scorer's scaled input",
                          [{"desc": "monitoring vs scorer consistency"}]),
            InvariantSpec("chain_integrity",
                          "feature rolling_mean and scaler output must be mathematically consistent",
                          [{"desc": "feature-scaler consistency"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
