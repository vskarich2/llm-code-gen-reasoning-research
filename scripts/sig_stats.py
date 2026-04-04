import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# =========================
# CONFIG
# =========================
# Required columns in your dataframe:
# case_id, model, trial_idx, condition, pass, leg_true, score (optional)
#
# condition values must include:
#   - "baseline"
#   - "LEG"
#
# Modify these names if needed.

BASELINE = "baseline"
TREATMENT = "LEG"

# Threshold for defining "meaningful" help/hurt (avoid noise sign flips)
DELTA_THRESHOLD = 0.0  # set to 0.01 if you want stricter filtering

# Number of permutations for significance test
N_PERM = 2000
RANDOM_SEED = 42

# =========================
# LOAD YOUR DATA
# =========================
# Replace with your actual loading logic
# df = pd.read_csv("your_logs.csv")

# ---- MOCK STRUCTURE CHECK ----
required_cols = ["case_id", "model", "trial_idx", "condition", "pass", "leg_true"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    raise ValueError(f"Missing required columns: {missing}")

# Optional continuous metric
HAS_SCORE = "score" in df.columns

# =========================
# 1. AGGREGATE TO CASE × MODEL × CONDITION
# =========================
agg = (
    df.groupby(["case_id", "model", "condition"])
    .agg(
        pass_rate=("pass", "mean"),
        leg_rate=("leg_true", "mean"),
        score_mean=("score", "mean") if HAS_SCORE else ("pass", "mean"),  # dummy if absent
    )
    .reset_index()
)

# =========================
# 2. COMPUTE DELTAS (LEG - BASELINE)
# =========================
def compute_delta(metric_name):
    pivot = agg.pivot_table(
        index=["case_id", "model"],
        columns="condition",
        values=metric_name
    )

    if BASELINE not in pivot.columns or TREATMENT not in pivot.columns:
        raise ValueError(f"Missing required conditions for metric {metric_name}")

    pivot = pivot.copy()
    pivot["delta"] = pivot[TREATMENT] - pivot[BASELINE]
    pivot = pivot.reset_index()

    return pivot

delta_pass = compute_delta("pass_rate")
delta_leg = compute_delta("leg_rate")
delta_score = compute_delta("score_mean") if HAS_SCORE else None

# =========================
# 3. DEFINE HELP / HURT
# =========================
def classify_delta(df_delta):
    df_delta = df_delta.copy()

    def label(d):
        if d > DELTA_THRESHOLD:
            return "help"
        elif d < -DELTA_THRESHOLD:
            return "hurt"
        else:
            return "neutral"

    df_delta["effect"] = df_delta["delta"].apply(label)
    return df_delta

delta_pass = classify_delta(delta_pass)
delta_leg = classify_delta(delta_leg)
if delta_score is not None:
    delta_score = classify_delta(delta_score)

# =========================
# 4. CASE-LEVEL HETEROGENEITY (HTE)
# =========================
def compute_hte(df_delta):
    results = []

    for case_id, group in df_delta.groupby("case_id"):
        effects = set(group["effect"])

        has_help = "help" in effects
        has_hurt = "hurt" in effects

        H = int(has_help and has_hurt)

        results.append({
            "case_id": case_id,
            "has_help": has_help,
            "has_hurt": has_hurt,
            "HTE": H
        })

    hte_df = pd.DataFrame(results)
    hte_rate = hte_df["HTE"].mean()

    return hte_df, hte_rate

hte_pass_df, hte_pass_rate = compute_hte(delta_pass)
hte_leg_df, hte_leg_rate = compute_hte(delta_leg)

print("\n=== HTE RATE (PASS) ===")
print(f"{hte_pass_rate:.3f}")

print("\n=== HTE RATE (LEG) ===")
print(f"{hte_leg_rate:.3f}")

# =========================
# 5. PERMUTATION TEST (SIGNIFICANCE)
# =========================
rng = np.random.default_rng(RANDOM_SEED)

def permutation_test(metric_col):
    observed_hte_rate = None
    perm_rates = []

    # Precompute observed
    observed_delta = compute_delta(metric_col)
    observed_delta = classify_delta(observed_delta)
    _, observed_hte_rate = compute_hte(observed_delta)

    # Prepare working copy
    df_perm = df.copy()

    for _ in range(N_PERM):
        df_shuffled = df_perm.copy()

        # Shuffle condition labels within each matched unit (case, model, trial)
        def shuffle_conditions(group):
            conds = group["condition"].values.copy()
            rng.shuffle(conds)
            group = group.copy()
            group["condition"] = conds
            return group

        df_shuffled = (
            df_shuffled
            .groupby(["case_id", "model", "trial_idx"], group_keys=False)
            .apply(shuffle_conditions)
        )

        # Recompute deltas
        agg_shuffled = (
            df_shuffled.groupby(["case_id", "model", "condition"])
            .agg(val=(metric_col, "mean"))
            .reset_index()
        )

        pivot = agg_shuffled.pivot_table(
            index=["case_id", "model"],
            columns="condition",
            values="val"
        )

        if BASELINE not in pivot.columns or TREATMENT not in pivot.columns:
            continue

        pivot["delta"] = pivot[TREATMENT] - pivot[BASELINE]
        pivot = pivot.reset_index()

        pivot = classify_delta(pivot.rename(columns={"delta": "delta"}))
        _, perm_rate = compute_hte(pivot)

        perm_rates.append(perm_rate)

    perm_rates = np.array(perm_rates)

    p_value = np.mean(perm_rates >= observed_hte_rate)

    return observed_hte_rate, p_value, perm_rates

print("\n=== PERMUTATION TEST (PASS) ===")
obs_pass, p_pass, _ = permutation_test("pass")
print(f"Observed HTE rate: {obs_pass:.3f}")
print(f"p-value: {p_pass:.4f}")

print("\n=== PERMUTATION TEST (LEG) ===")
obs_leg, p_leg, _ = permutation_test("leg_true")
print(f"Observed HTE rate: {obs_leg:.3f}")
print(f"p-value: {p_leg:.4f}")

# =========================
# 6. MIXED-EFFECTS MODEL (INTERACTION)
# =========================
# Tests whether condition effect differs across models

print("\n=== MIXED EFFECTS MODEL (PASS) ===")
model_pass = smf.mixedlm(
    "pass ~ condition * model",
    data=df,
    groups=df["case_id"],
    re_formula="~1"
).fit()
print(model_pass.summary())

print("\n=== MIXED EFFECTS MODEL (LEG) ===")
model_leg = smf.mixedlm(
    "leg_true ~ condition * model",
    data=df,
    groups=df["case_id"],
    re_formula="~1"
).fit()
print(model_leg.summary())

if HAS_SCORE:
    print("\n=== MIXED EFFECTS MODEL (SCORE) ===")
    model_score = smf.mixedlm(
        "score ~ condition * model",
        data=df,
        groups=df["case_id"],
        re_formula="~1"
    ).fit()
    print(model_score.summary())

# =========================
# 7. OUTPUT TABLE (FINAL)
# =========================
def summarize_delta(df_delta, metric_name):
    summary = (
        df_delta.groupby("model")["delta"]
        .agg(["mean", "std", "count"])
        .reset_index()
    )
    summary["metric"] = metric_name
    return summary

summary_pass = summarize_delta(delta_pass, "pass")
summary_leg = summarize_delta(delta_leg, "leg")
summary_score = summarize_delta(delta_score, "score") if HAS_SCORE else None

final_summary = pd.concat(
    [summary_pass, summary_leg] + ([summary_score] if summary_score is not None else []),
    ignore_index=True
)

print("\n=== DELTA SUMMARY ===")
print(final_summary)

