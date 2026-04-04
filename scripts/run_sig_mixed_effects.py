# Mixed-effects setup for LEG analysis (pass + LEG rate)
# Adapted to load from events.jsonl in ablation log directories.
#
# Usage:
#   .venv/bin/python scripts/run_sig_mixed_effects.py
#   .venv/bin/python scripts/run_sig_mixed_effects.py --logs logs/v2_targeted_50trial_canonical

import argparse
import json
import glob
import sys

import pandas as pd
import numpy as np
import statsmodels.api as sm
import statsmodels.formula.api as smf

DEFAULT_LOG_DIRS = ["logs/v2_targeted_50trial_canonical"]

# -----------------------------
# 1. Load case_data from events.jsonl
# -----------------------------

def load_events(log_dirs):
    rows = []
    for log_dir in log_dirs:
        for f in sorted(glob.glob(
                f"{log_dir}/**/events.jsonl", recursive=True)):
            with open(f) as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("event_type") != "case.end":
                        continue
                    p = ev.get("payload", {})

                    # Determine reconstruction success
                    recon_status = p.get("reconstruction_status")
                    exec_cat = p.get("execution_category", "")
                    reasons = " ".join(p.get("reasons", [])).lower()
                    recon_ok = not (
                        recon_status not in (None, "SUCCESS")
                        or exec_cat in (
                            "RECONSTRUCTION_FAILURE",
                            "BUILD_FAILURE",
                            "PARSE_FAILURE",
                        )
                        or "no extractable code" in reasons
                        or "rename error" in reasons
                        or "assembly error" in reasons
                    )

                    mc = p.get("mechanism_correct")
                    passed = p.get("pass", False)

                    rows.append({
                        "case_id": ev.get("case_id"),
                        "model": ev.get("model"),
                        "trial": ev.get("trial"),
                        "condition": ev.get("condition"),
                        "pass_bin": int(passed),
                        "recon_ok": recon_ok,
                        "reasoning_correct": mc,
                        "leg": int(mc is True and not passed),
                    })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--logs", nargs="+", default=DEFAULT_LOG_DIRS)
    args = parser.parse_args()

    print(f"Loading from: {args.logs}")
    df = load_events(args.logs)

    print(f"Total rows: {len(df)}")
    print(f"Models: {sorted(df['model'].unique())}")
    print(f"Conditions: {sorted(df['condition'].unique())}")
    print(f"Cases: {df['case_id'].nunique()}")
    print(f"Trials: {sorted(df['trial'].unique())}")
    print()

    # -----------------------------
    # 2. Clean + encode
    # -----------------------------
    df = df.dropna(subset=["pass_bin", "model", "condition", "case_id"])
    df["model"] = df["model"].astype("category")
    df["condition"] = df["condition"].astype("category")
    df["case_id"] = df["case_id"].astype("category")

    df_recon = df[df["recon_ok"] == True].copy()

    print(f"After cleaning: {len(df)} rows "
          f"({len(df_recon)} with successful reconstruction)")
    print()

    # -----------------------------
    # 3. GEE models (all case_data)
    # -----------------------------
    print("=" * 80)
    print("GEE PASS MODEL (all case_data)")
    print("=" * 80)
    try:
        gee_pass = smf.gee(
            "pass_bin ~ C(condition) * C(model)",
            groups="case_id",
            data=df,
            family=sm.families.Binomial(),
        ).fit()
        print(gee_pass.summary())
    except Exception as e:
        print(f"Failed: {e}")
        gee_pass = None

    print()
    print("=" * 80)
    print("GEE LEG MODEL (all case_data)")
    print("=" * 80)
    try:
        gee_leg = smf.gee(
            "leg ~ C(condition) * C(model)",
            groups="case_id",
            data=df,
            family=sm.families.Binomial(),
        ).fit()
        print(gee_leg.summary())
    except Exception as e:
        print(f"Failed: {e}")
        gee_leg = None

    # -----------------------------
    # 4. GEE models (recon-only)
    # -----------------------------
    print()
    print("=" * 80)
    print("GEE PASS MODEL (reconstruction-only)")
    print("=" * 80)
    try:
        gee_pass_recon = smf.gee(
            "pass_bin ~ C(condition) * C(model)",
            groups="case_id",
            data=df_recon,
            family=sm.families.Binomial(),
        ).fit()
        print(gee_pass_recon.summary())
    except Exception as e:
        print(f"Failed: {e}")
        gee_pass_recon = None

    print()
    print("=" * 80)
    print("GEE LEG MODEL (reconstruction-only)")
    print("=" * 80)
    try:
        gee_leg_recon = smf.gee(
            "leg ~ C(condition) * C(model)",
            groups="case_id",
            data=df_recon,
            family=sm.families.Binomial(),
        ).fit()
        print(gee_leg_recon.summary())
    except Exception as e:
        print(f"Failed: {e}")
        gee_leg_recon = None

    # -----------------------------
    # 5. Marginal effects
    # -----------------------------
    if gee_pass is not None:
        print()
        print("=" * 80)
        print("MARGINAL EFFECTS (PASS, all case_data)")
        print("=" * 80)
        try:
            marginal = gee_pass.get_margeff(at="overall")
            print(marginal.summary())
        except Exception as e:
            print(f"Marginal effects failed: {e}")

    if gee_pass_recon is not None:
        print()
        print("=" * 80)
        print("MARGINAL EFFECTS (PASS, recon-only)")
        print("=" * 80)
        try:
            marginal_r = gee_pass_recon.get_margeff(at="overall")
            print(marginal_r.summary())
        except Exception as e:
            print(f"Marginal effects failed: {e}")

    # -----------------------------
    # 6. Conversion metric
    # -----------------------------
    print()
    print("=" * 80)
    print("CONVERSION TABLE (all case_data)")
    print("=" * 80)
    conv = compute_conversion(df)
    if len(conv) > 0:
        print(conv.sort_values(
            "conversion", ascending=False
        ).head(25).to_string(index=False))

    print()
    print("=" * 80)
    print("CONVERSION TABLE (recon-only)")
    print("=" * 80)
    conv_r = compute_conversion(df_recon)
    if len(conv_r) > 0:
        print(conv_r.sort_values(
            "conversion", ascending=False
        ).head(25).to_string(index=False))

    # -----------------------------
    # 7. Summary comparison
    # -----------------------------
    print()
    print("=" * 80)
    print("STRICT vs RECON-ONLY: GEE coefficient comparison")
    print("=" * 80)
    if gee_pass is not None and gee_pass_recon is not None:
        strict_params = gee_pass.params
        recon_params = gee_pass_recon.params
        common = sorted(
            set(strict_params.index) & set(recon_params.index))
        print(f"{'Parameter':<50s} {'Strict':>8s} "
              f"{'Recon':>8s} {'Delta':>8s}")
        print("-" * 80)
        for param in common:
            s = strict_params[param]
            r = recon_params[param]
            d = r - s
            print(f"{param:<50s} {s:>8.4f} "
                  f"{r:>8.4f} {d:>+8.4f}")


def compute_conversion(df):
    out = []
    for (case, model), g in df.groupby(["case_id", "model"]):
        base = g[g["condition"] == "baseline_v2"]
        for cond in [
            "leg_reduction_v2",
            "leg_reduction_lean_v2",
        ]:
            treat = g[g["condition"] == cond]
            if len(base) == 0 or len(treat) == 0:
                continue
            base_leg = base["leg"].mean()
            treat_leg = treat["leg"].mean()
            base_pass = base["pass_bin"].mean()
            treat_pass = treat["pass_bin"].mean()
            leg_drop = base_leg - treat_leg
            pass_gain = treat_pass - base_pass
            if leg_drop <= 0.05 and pass_gain <= 0.05:
                continue
            conv = (
                pass_gain / leg_drop
                if leg_drop > 0
                else np.nan
            )
            out.append({
                "case": case,
                "model": model,
                "condition": cond.replace(
                    "leg_reduction_", ""
                ).replace("_v2", ""),
                "base_leg": f"{base_leg:.0%}",
                "treat_leg": f"{treat_leg:.0%}",
                "leg_drop": f"{leg_drop:+.0%}",
                "base_pass": f"{base_pass:.0%}",
                "treat_pass": f"{treat_pass:.0%}",
                "pass_gain": f"{pass_gain:+.0%}",
                "conversion": (
                    f"{conv:.0%}" if not np.isnan(conv)
                    else "N/A"
                ),
            })
    return pd.DataFrame(out)


if __name__ == "__main__":
    main()
