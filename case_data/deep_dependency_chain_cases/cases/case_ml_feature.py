"""Case 4 (C): ML feature pipeline.

Chain: data_source → feature_engineer → scaler → model_scorer
Bypass: get_raw_features reads feature_engineer output directly for monitoring
Bug: feature_engineer computes ratio feature with wrong denominator (off-by-one in window)
Canonical field: features dict from feature_engineer
"""

from data.deep_dependency_chain.spec_types import (
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

SCALER_PARAMS = {"mean": 30.0, "std": 15.0}  # fitted on training case_data


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
    Fails when the buggy-correct difference is not 5.0 (different case_data)."""
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
    """TRAP 1: scorer applies correction factor based on count."""
    base = _score_model(scaled)
    # "Correct" for the known bias by adjusting score
    if base["prediction"] == "low" and scaled["count"] >= 3:
        base["score"] = round(base["score"] + 0.15, 4)
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

    # Step A/B: feature engineering
    if patch_id == "root_fix":
        features = _engineer_features_fixed(data)
    elif patch_id == "trap_5":
        features = _engineer_features_trap5(data)
    elif patch_id == "trap_4":
        features = _engineer_features_buggy(data)
    else:
        features = _engineer_features_buggy(data)

    # Bypass consumer
    raw_monitoring = _get_raw_features(features)

    # Step C: scaler
    if patch_id == "trap_3":
        scaled = _scale_features_bias_corrected(features)
    elif patch_id == "trap_5":
        scaled = _scale_features(features, use_corrected=True)
    elif patch_id == "trap_4":
        # Downstream override: re-compute rolling_mean at scaler level
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

    # Step D: scorer
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


# ── Test inputs ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    # Primary case_data: [10, 20, 30, 40, 50], window=3
    # Correct rolling_mean: (30+40+50)/3 = 40.0
    # Buggy rolling_mean: (40+50)/2 = 45.0
    # Correct scaled: (40 - 30) / 15 = 0.6667
    # Correct score: 0.5 + 0.3 * 0.6667 = 0.7
    # Prediction: "high" (score > 0.7 → borderline, let's check)
    # Actually 0.5 + 0.3*0.6667 = 0.7000 → "low" (not > 0.7)
    # Hmm, need to adjust. Let me check buggy:
    # Buggy scaled: (45 - 30) / 15 = 1.0
    # Buggy score: 0.5 + 0.3 * 1.0 = 0.8 → "high"
    # So buggy says "high", correct says "low"
    # Primary symptom: prediction should be "low" for this case_data
    # Wait, that's counterintuitive. Let me reverse: correct answer should be "high"
    # and buggy answer should be wrong.
    #
    # Actually let me just check the score magnitude. The correct rolling_mean is 40.
    # Let me make the primary test about whether the score is in the right range.
    result = r["result"]
    # Correct: rolling_mean=40, scaled=0.6667, score=0.7
    # Accept score in [0.65, 0.75]
    return 0.65 <= result["score"] <= 0.75


def _run_invariant_trap_catching(patch_id):
    """Short dataset [5, 15] with window=3.
    Correct: rolling_mean = (5+15)/2 = 10 (only 2 values, window truncated to 2)
    Buggy: window-1=2, min(2,2)=2, same result: (5+15)/2 = 10. Hmm, same!

    Need a dataset where buggy and correct differ AND trap_1's adjustment fails.
    Use primary dataset but check that scorer doesn't add artificial boost.

    Actually, let me use a dataset where the score should be LOW and trap_1's
    count-based adjustment incorrectly makes it HIGH."""
    r = _run_chain(patch_id, "alternate_short")
    result = r["result"]
    # [5, 15], window=3: both buggy and correct give mean=10 (only 2 values)
    # scaled = (10-30)/15 = -1.333, score = 0.5 + 0.3*(-1.333) = 0.1
    # prediction = "low" (correct)
    # trap_1: count=2 < 3 → adjustment not applied → correct prediction
    # This doesn't catch trap_1!
    #
    # Better: trap_1 adjusts when count >= 3 AND prediction == "low".
    # On primary case_data with buggy features: score = 0.8 → "high" → no adjustment.
    # On primary case_data with correct features: score = 0.7 → "low" → trap_1 adds 0.15 → 0.85 → "high"
    # Wait, but this is the primary test scenario.
    #
    # I need a scenario where: correct features → "low" prediction → trap_1 boosts to "high" → WRONG.
    # Use alternate_large: [100..1000], window=5
    # Correct: mean of last 5 = (600+700+800+900+1000)/5 = 800
    # Buggy: window-1=4, mean of last 4 = (700+800+900+1000)/4 = 850
    r2 = _run_chain(patch_id, "alternate_large")
    result2 = r2["result"]
    # Correct: scaled = (800-30)/15 = 51.33, score = 0.5 + 0.3*51.33 = 15.9 → "high"
    # Buggy: scaled = (850-30)/15 = 54.67, score = 0.5 + 0.3*54.67 = 16.9 → "high"
    # Both are "high" — doesn't help.
    #
    # I need small values where the off-by-one makes the prediction cross the threshold.
    # Let me just check: does the score differ enough from correct?
    # Actually, the trap_catching invariant should catch trap_1 specifically.
    # trap_1 adds 0.15 to "low" predictions when count>=3.
    # With correct features on primary: score=0.7 → "low" → trap_1 makes 0.85 → "high"
    # But primary test accepts [0.65, 0.75]. Trap_1 on primary = 0.85 → outside → fails primary.
    # Wait, trap_1 runs on BUGGY features. Buggy score = 0.8 → "high" → no adjustment.
    # trap_1 only adjusts "low" predictions. With buggy features, prediction is "high" so no change.
    # So trap_1 on primary = same as buggy = 0.8. Primary test: 0.65 ≤ 0.8 ≤ 0.75 → FALSE.
    # trap_1 fails the primary test!
    #
    # That's wrong. Let me reconsider the whole setup.
    pass

    # Placeholder — will fix below
    return True, "placeholder", "alternate"


# I need to redesign the numbers. Let me compute carefully.
# Primary: [10, 20, 30, 40, 50], window=3
# Correct rolling_mean: (30+40+50)/3 = 40.0
# Buggy rolling_mean: (40+50)/2 = 45.0
# Correct scaled: (40-30)/15 = 0.6667 → score = 0.5 + 0.3*0.6667 = 0.7000
# Buggy scaled: (45-30)/15 = 1.0 → score = 0.5 + 0.3*1.0 = 0.8000
#
# The symptom: buggy over-estimates the score (0.8 vs correct 0.7).
# Primary test should check that the score is close to 0.7 (correct).
# Buggy score of 0.8 fails. Root fix score of 0.7 passes.
#
# For trap_1 to pass primary: trap_1 uses buggy features (rolling_mean=45)
# but adjusts the score. To make trap_1 pass, the adjustment must bring
# 0.8 down to ~0.7. Current trap_1 ADDS 0.15 to "low" predictions.
# With buggy features, prediction is "high" (0.8 > 0.7) → no adjustment → 0.8.
# Primary test: 0.65 ≤ 0.8 ≤ 0.75 → FALSE. trap_1 fails primary!
#
# Fix: make trap_1 subtract a correction for "high" predictions instead.

def _score_model_adjusted_v2(scaled):
    """TRAP 1: scorer applies bias correction to bring score closer to expected range."""
    base = _score_model(scaled)
    # Observed: scores tend to be ~0.1 too high due to feature bias
    # "Fix": subtract 0.1 from all scores
    base["score"] = round(base["score"] - 0.1, 4)
    base["prediction"] = "high" if base["score"] > 0.7 else "low"
    base["adjusted"] = True
    return base


def _run_chain_v2(patch_id, dataset_id="primary"):
    """Corrected chain with proper trap_1."""
    data = _load_data(dataset_id)

    if patch_id == "root_fix":
        features = _engineer_features_fixed(data)
    elif patch_id == "trap_5":
        features = _engineer_features_trap5(data)
    else:
        features = _engineer_features_buggy(data)

    if patch_id == "trap_3":
        # Bias correction at feature level: adjust features dict before monitoring + scaling
        features = dict(features)
        features["rolling_mean"] = features["rolling_mean"] - 5.0

    raw_monitoring = _get_raw_features(features)

    if patch_id == "trap_3":
        scaled = _scale_features(features)  # uses bias-corrected features
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
        result = _score_model_adjusted_v2(scaled)
    else:
        result = _score_model(scaled)

    return {
        "result": result,
        "monitoring": raw_monitoring,
        "features": features,
        "scaled": scaled,
    }


# Redefine run_chain
_run_chain = _run_chain_v2


def _run_primary_test_v2(patch_id):
    r = _run_chain(patch_id, "primary")
    result = r["result"]
    # Correct: score ≈ 0.7. Buggy: score = 0.8 (too high).
    # Trap_1: 0.8 - 0.1 = 0.7. Within range.
    return 0.65 <= result["score"] <= 0.75


def _run_invariant_trap_catching_v2(patch_id):
    """Test with alternate_large dataset where the -0.1 adjustment is wrong.
    Large values: correct score is very high. Subtracting 0.1 still leaves it high.
    But the RAW score is different from what monitoring shows.

    Actually: use alternate_short [5, 15].
    Correct mean = (5+15)/2 = 10. Buggy: window-1=2, min(2,2)=2, same: 10.
    Both give same mean (window truncated). scaled = (10-30)/15 = -1.333.
    score = 0.5 + 0.3*(-1.333) = 0.1. prediction = "low".
    trap_1: 0.1 - 0.1 = 0.0. prediction = "low".
    Correct: also 0.1. Expected: score ≈ 0.1.
    trap_1 gives 0.0 instead of 0.1. Is that wrong enough?

    Check: abs(0.0 - 0.1) = 0.1. If tolerance is 0.05, fails. Good."""
    r = _run_chain(patch_id, "alternate_short")
    result = r["result"]
    # Correct score for [5,15] with either buggy or fixed features: ~0.1
    # Trap_1 subtracts 0.1 → 0.0. Wrong.
    expected_score = 0.1
    passed = abs(result["score"] - expected_score) < 0.06
    return passed, f"score={result['score']}, expected≈{expected_score}", "short_dataset"


def _run_invariant_generalization_v2(patch_id):
    """Test with alternate_varied [10, 20, 50], window=3.
    Correct: (10+20+50)/3 = 26.67 → scaled = (26.67-30)/15 = -0.222 → score = 0.433.
    Buggy: (20+50)/2 = 35 → bias-corrected: 35-5=30 → scaled=0 → score=0.5.
    Correct score: 0.433. Trap_3 score: 0.5. Difference: 0.067 → FAIL."""
    r = _run_chain(patch_id, "alternate_varied")
    result = r["result"]
    # Correct rolling_mean = 26.67, correct score ≈ 0.433
    expected_score = 0.433
    passed = abs(result["score"] - expected_score) < 0.05
    return passed, f"score={result['score']}, expected≈{expected_score}", "varied_dataset"


def _run_invariant_causal_location_v2(patch_id):
    """Feature engineer rolling_mean must be correct for primary case_data."""
    r = _run_chain(patch_id, "primary")
    # Correct: (30+40+50)/3 = 40.0
    expected = 40.0
    actual = r["features"]["rolling_mean"]
    passed = abs(actual - expected) < 0.01
    return passed, f"rolling_mean={actual}, expected={expected}", None


def _run_invariant_cross_path_v2(patch_id):
    """Monitoring (bypass) rolling_mean must match scorer's input basis.
    If trap_4 re-computes at scaler but features dict still has buggy mean,
    monitoring shows buggy mean while score reflects correct mean."""
    r = _run_chain(patch_id, "primary")
    monitoring_mean = r["monitoring"]["rolling_mean"]
    # The scorer's input came from scaled features. If trap_4 patched at scaler,
    # the scaled value reflects correct mean but monitoring reads buggy mean.
    # Check: are monitoring and scaled consistent?
    # monitoring_mean → what would scaled be?
    expected_scaled = round((monitoring_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"], 4)
    actual_scaled = r["scaled"]["scaled_rolling_mean"]
    consistent = abs(expected_scaled - actual_scaled) < 0.01
    return consistent, f"monitoring_mean={monitoring_mean} → expected_scaled={expected_scaled}, actual_scaled={actual_scaled}", None


def _run_invariant_chain_integrity_v2(patch_id):
    """Feature rolling_mean and scaler input must be consistent.
    If they disagree, an intermediate node patched the value."""
    r = _run_chain(patch_id, "primary")
    feature_mean = r["features"]["rolling_mean"]
    # Scaled should be (feature_mean - mean) / std
    expected_scaled = round((feature_mean - SCALER_PARAMS["mean"]) / SCALER_PARAMS["std"], 4)
    actual_scaled = r["scaled"]["scaled_rolling_mean"]
    consistent = abs(expected_scaled - actual_scaled) < 0.01
    return consistent, f"feature_mean={feature_mean}, expected_scaled={expected_scaled}, actual_scaled={actual_scaled}", None


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
            ChainNode("data_source", "data_source.py", "load_data",
                      "loads raw time series case_data"),
            ChainNode("feature_engineer", "features.py", "engineer_features",
                      "computes rolling stats — BUG: window off-by-one"),
            ChainNode("scaler", "scaler.py", "scale_features",
                      "standardizes features using pre-fitted params"),
            ChainNode("model_scorer", "scorer.py", "score_model",
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
                     "on varied case_data [10,20,50], features still wrong → score wrong after adjustment",
                     "generalization", "varied_dataset"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "scaler subtracts hardcoded bias of 5.0 from rolling_mean",
                     "rolling_mean -= 5.0 to compensate for observed off-by-one error",
                     "exactly corrects primary case_data (buggy-correct diff = 5.0)",
                     "on varied case_data [10,20,50], diff is 8.33 not 5.0 → score wrong",
                     "generalization", "varied_dataset"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "scaler re-computes rolling_mean from raw case_data before scaling",
                     "re-derive correct feature at scaler level, bypass buggy feature",
                     "produces correct scaled value and score",
                     "monitoring (bypass) still reads buggy rolling_mean from feature dict",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "feature_engineer adds corrected_rolling_mean alongside buggy rolling_mean",
                     "features['corrected_rolling_mean'] = correct_value; rolling_mean unchanged",
                     "correct case_data available at feature node",
                     "monitoring reads rolling_mean (not corrected); shows wrong value",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "score on short dataset [5,15] must be ≈0.1 (not adjusted to 0.0)",
                          [{"desc": "short dataset score check"}]),
            InvariantSpec("generalization",
                          "score on large dataset must be very high (>5.0), not clamped",
                          [{"desc": "large dataset unclamped"}]),
            InvariantSpec("causal_location",
                          "feature_engineer rolling_mean must be 40.0 for primary case_data",
                          [{"desc": "primary features check"}]),
            InvariantSpec("cross_path",
                          "monitoring rolling_mean must be consistent with scorer's scaled input",
                          [{"desc": "monitoring vs scorer consistency"}]),
            InvariantSpec("chain_integrity",
                          "feature rolling_mean and scaler output must be mathematically consistent",
                          [{"desc": "feature-scaler consistency"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test_v2
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching_v2,
        "generalization": _run_invariant_generalization_v2,
        "causal_location": _run_invariant_causal_location_v2,
        "cross_path": _run_invariant_cross_path_v2,
        "chain_integrity": _run_invariant_chain_integrity_v2,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
