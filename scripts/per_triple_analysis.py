#!/usr/bin/env python3
"""Per (case, model, condition) breakdown of all stats."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"

INCLUDE_PREFIXES = [
    "global_calibration",
    "retry_critique_stage0",
    "retry_critique_stage1",
    "retry_critique_stage2",
    "stage_b_critique",
    "stage_b_critique_r2",
    "stage_c_critique",
    "v2_full_4model_10trial_canonical",
    "v2_targeted_50trial",
    "v2_anthropic_haiku45",
    "v2_anthropic_sonnet46",
    "v2_gpt5_50trial",
]

COND_SHORT = {
    "baseline_v2": "base",
    "retry_bare_retry_v2": "retry",
    "leg_reduction_lean_v2": "lean",
    "retry_leg_critique_strict_v2": "crit",
    "retry_reasoning_only_critique_v1": "ro",
    "leg_reduction_v2": "full",
}

MODEL_SHORT = {
    "gpt-4.1-nano": "nano",
    "gpt-4o-mini": "4omini",
    "gpt-5-mini": "5mini",
    "gpt-5.4-mini": "54mini",
    "gpt-5": "gpt5",
    "claude-haiku-4-5-20251001": "haiku45",
    "claude-sonnet-4-20250514": "sonnet4",
    "claude-sonnet-4-6": "sonnet46",
    "claude-3-haiku-20240307": "haiku3",
}

CLUSTERS = {
    "Severe LEG": ["feature_flag_drift", "false_fix_deadlock"],
    "Moderate LEG": [
        "check_then_act", "overdetermination", "missing_branch_c",
        "hidden_dep_multihop", "config_shadowing", "invariant_partial_fail",
        "async_race_lock", "lost_update",
    ],
    "Reasoning-limited": ["l3_state_pipeline", "async_race_lock"],
    "Lucky fix": [
        "cache_invalidation_order", "use_before_set_a",
        "use_before_set_b", "use_before_set_c",
    ],
}


def get_cluster(case_id):
    for cluster, cases in CLUSTERS.items():
        if case_id in cases:
            return cluster
    return "Capable"


def parse_events(path):
    events = []
    if not path.exists():
        return events
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            break
    return events


def extract(log_dir, source):
    records = []
    for ef in sorted(log_dir.rglob("workers/*/attempt_*/events.jsonl")):
        for e in parse_events(ef):
            if e.get("event_type") != "case.end":
                continue
            p = e.get("payload", {})
            ex = e.get("execution", {})
            r = e.get("reasoning", {})
            cond = (
                p.get("retry_mode")
                or e.get("condition")
                or e.get("context", {}).get("condition")
            )
            if not cond or cond == "null":
                cond = e.get("context", {}).get("condition") or "baseline_v2"
            records.append({
                "source": source,
                "case_id": e.get("case_id") or e.get("context", {}).get("case_id"),
                "model": e.get("model"),
                "trial": e.get("trial"),
                "condition": cond,
                "passed": bool(ex.get("passed")),
                "score": p.get("score", 0),
                "mechanism_correct": bool(p.get("mechanism_correct")),
                "failure_type": p.get("failure_type") or r.get("failure_type"),
                "v2_category": p.get("v2_category") or p.get("category"),
                "mechanism_dim": p.get("mechanism_identified_dim"),
                "alignment_dim": p.get("reasoning_code_alignment_dim"),
                "retry_passed_at": p.get("retry_passed_at"),
            })
    return records


def load_all():
    recs = []
    for d in sorted(LOGS.iterdir()):
        if not d.is_dir():
            continue
        if not any(d.name.startswith(p) for p in INCLUDE_PREFIXES):
            continue
        for mf in d.glob("**/manifest.json"):
            rd = mf.parent
            try:
                md = json.loads(mf.read_text())
                ok = sum(
                    1 for v in md.get("work_items", {}).values()
                    if isinstance(v, dict) and v.get("state") == "SUCCEEDED"
                )
                if ok == 0:
                    continue
            except Exception:
                continue
            r = extract(rd, str(rd.relative_to(LOGS)))
            if r:
                recs.extend(r)
    return pd.DataFrame(recs)


def regime_classify(pb, dr, dc, dro, T=0.20):
    if pb >= 0.9:
        return "CEIL"
    if max(dr, dc, dro) < T:
        return "NONE"
    if dr >= T and dc < dr + T and dro < dr + T:
        return "RETRY"
    if dc >= T and dc >= dro + T:
        return "CRIT"
    if dro >= T and dro >= dc + T:
        return "RO"
    if dc >= T and dro >= T and abs(dc - dro) < T:
        return "EQUIV"
    return "NONE"


def main():
    df = load_all()
    df["model_short"] = df["model"].map(MODEL_SHORT).fillna(df["model"])
    df["cond_short"] = df["condition"].map(COND_SHORT).fillna(df["condition"])
    df = df.drop_duplicates(subset=["case_id", "model", "trial", "condition"])
    df["leg_true"] = df["mechanism_correct"] & ~df["passed"]
    df["cluster"] = df["case_id"].apply(get_cluster)

    # Aggregate to (case, model, condition) level
    agg = df.groupby(["case_id", "model_short", "condition", "cond_short", "cluster"]).agg(
        n=("passed", "count"),
        pass_rate=("passed", "mean"),
        score_mean=("score", "mean"),
        mech_rate=("mechanism_correct", "mean"),
        leg_rate=("leg_true", "mean"),
    ).reset_index()

    # Build baseline lookup
    base = agg[agg["condition"] == "baseline_v2"][
        ["case_id", "model_short", "pass_rate", "leg_rate", "n"]
    ].rename(columns={"pass_rate": "pass_base", "leg_rate": "leg_base", "n": "n_base"})

    # Merge treatments with baseline
    treat = agg[agg["condition"] != "baseline_v2"].copy()
    treat = treat.merge(base, on=["case_id", "model_short"], how="left")
    treat["delta"] = treat["pass_rate"] - treat["pass_base"]

    # Also compute regime per (case, model)
    retry_rates = agg[agg["condition"] == "retry_bare_retry_v2"][
        ["case_id", "model_short", "pass_rate"]
    ].rename(columns={"pass_rate": "pr_retry"})
    crit_rates = agg[agg["condition"] == "retry_leg_critique_strict_v2"][
        ["case_id", "model_short", "pass_rate"]
    ].rename(columns={"pass_rate": "pr_crit"})
    ro_rates = agg[agg["condition"] == "retry_reasoning_only_critique_v1"][
        ["case_id", "model_short", "pass_rate"]
    ].rename(columns={"pass_rate": "pr_ro"})

    regime_df = base.copy()
    regime_df = regime_df.merge(retry_rates, on=["case_id", "model_short"], how="left")
    regime_df = regime_df.merge(crit_rates, on=["case_id", "model_short"], how="left")
    regime_df = regime_df.merge(ro_rates, on=["case_id", "model_short"], how="left")
    regime_df = regime_df.dropna(subset=["pr_retry", "pr_crit", "pr_ro"])
    regime_df["regime"] = regime_df.apply(
        lambda r: regime_classify(
            r["pass_base"],
            r["pr_retry"] - r["pass_base"],
            r["pr_crit"] - r["pass_base"],
            r["pr_ro"] - r["pass_base"],
        ), axis=1
    )
    regime_lookup = dict(zip(
        zip(regime_df["case_id"], regime_df["model_short"]),
        regime_df["regime"],
    ))

    # ================================================================
    # TABLE 1: Full triple-level table
    # ================================================================
    print("=" * 160)
    print("  FULL (CASE, MODEL, CONDITION) TABLE")
    print("  Sorted by case, then model, then condition")
    print("=" * 160)

    header = (
        f"{'case_id':<30} {'model':<10} {'condition':<10} "
        f"{'pass%':>7} {'N':>5} {'mech%':>7} {'LEG%':>7} {'score':>7} "
        f"{'base%':>7} {'Δ':>7} {'regime':>7} {'cluster':<16}"
    )
    print(header)
    print("-" * len(header))

    for _, row in agg.sort_values(["case_id", "model_short", "cond_short"]).iterrows():
        case_id = row["case_id"]
        model = row["model_short"]
        cs = row["cond_short"]
        pr = row["pass_rate"]
        n = int(row["n"])
        mr = row["mech_rate"]
        lr = row["leg_rate"]
        sc = row["score_mean"]
        cluster = row["cluster"]

        # Get baseline for delta
        brow = base[(base["case_id"] == case_id) & (base["model_short"] == model)]
        if len(brow) > 0 and cs != "base":
            pb = brow.iloc[0]["pass_base"]
            delta = pr - pb
            delta_s = f"{delta:>+6.0%} "
            base_s = f"{pb:>6.0%} "
        elif cs == "base":
            delta_s = f"{'—':>7}"
            base_s = f"{'—':>7}"
        else:
            delta_s = f"{'—':>7}"
            base_s = f"{'—':>7}"

        regime = regime_lookup.get((case_id, model), "—")

        print(
            f"{case_id:<30} {model:<10} {cs:<10} "
            f"{pr:>6.0%} {n:>5} {mr:>6.0%} {lr:>6.0%} {sc:>6.2f} "
            f"{base_s} {delta_s} {regime:>7} {cluster:<16}"
        )

    # ================================================================
    # TABLE 2: Wide format — one row per (case, model), columns = conditions
    # ================================================================
    print(f"\n{'=' * 160}")
    print("  WIDE FORMAT: PASS RATES — one row per (case, model)")
    print(f"{'=' * 160}")

    cond_order = ["base", "retry", "crit", "ro", "lean", "full"]
    pivot = agg.pivot_table(
        index=["case_id", "model_short"],
        columns="cond_short",
        values="pass_rate",
    )
    pivot_n = agg.pivot_table(
        index=["case_id", "model_short"],
        columns="cond_short",
        values="n",
    )

    cols_present = [c for c in cond_order if c in pivot.columns]
    header = (
        f"{'case_id':<30} {'model':<10} "
        + "".join(f"{c:>12}" for c in cols_present)
        + f" {'regime':>7}"
    )
    print(header)
    print("-" * len(header))

    for (case_id, model), row in pivot.sort_index().iterrows():
        parts = f"{case_id:<30} {model:<10} "
        for c in cols_present:
            v = row.get(c)
            nv = pivot_n.loc[(case_id, model)].get(c) if (case_id, model) in pivot_n.index else None
            if pd.notna(v) and pd.notna(nv):
                parts += f"{v:>7.0%}({int(nv):>3})"
            else:
                parts += f"{'—':>12}"
        regime = regime_lookup.get((case_id, model), "—")
        parts += f" {regime:>7}"
        print(parts)

    # ================================================================
    # TABLE 3: Interesting triples — largest deltas
    # ================================================================
    print(f"\n{'=' * 160}")
    print("  TOP 40 LARGEST POSITIVE DELTAS (treatment - baseline)")
    print(f"{'=' * 160}")

    top_pos = treat.dropna(subset=["delta"]).nlargest(40, "delta")
    header = (
        f"{'case_id':<30} {'model':<10} {'condition':<10} "
        f"{'base%':>7} {'treat%':>7} {'Δ':>7} {'N_treat':>7} {'N_base':>7} {'cluster':<16}"
    )
    print(header)
    print("-" * len(header))
    for _, r in top_pos.iterrows():
        print(
            f"{r['case_id']:<30} {r['model_short']:<10} {r['cond_short']:<10} "
            f"{r['pass_base']:>6.0%} {r['pass_rate']:>6.0%} {r['delta']:>+6.0%} "
            f"{int(r['n']):>7} {int(r['n_base']):>7} {r['cluster']:<16}"
        )

    print(f"\n{'=' * 160}")
    print("  TOP 40 LARGEST NEGATIVE DELTAS (treatment - baseline)")
    print(f"{'=' * 160}")

    top_neg = treat.dropna(subset=["delta"]).nsmallest(40, "delta")
    print(header)
    print("-" * len(header))
    for _, r in top_neg.iterrows():
        print(
            f"{r['case_id']:<30} {r['model_short']:<10} {r['cond_short']:<10} "
            f"{r['pass_base']:>6.0%} {r['pass_rate']:>6.0%} {r['delta']:>+6.0%} "
            f"{int(r['n']):>7} {int(r['n_base']):>7} {r['cluster']:<16}"
        )

    # ================================================================
    # TABLE 4: Per-triple significance (Fisher exact test on pass counts)
    # ================================================================
    print(f"\n{'=' * 160}")
    print("  STATISTICALLY SIGNIFICANT TRIPLES (Fisher exact, p<0.05, N_base>=10, N_treat>=10)")
    print(f"{'=' * 160}")

    header = (
        f"{'case_id':<30} {'model':<10} {'condition':<10} "
        f"{'base%':>7} {'treat%':>7} {'Δ':>7} "
        f"{'N_b':>5} {'N_t':>5} {'p':>8} {'sig':>4} {'cluster':<16}"
    )
    print(header)
    print("-" * len(header))

    sig_rows = []
    for _, r in treat.dropna(subset=["pass_base", "delta"]).iterrows():
        nb = r["n_base"]
        nt = r["n"]
        if nb < 10 or nt < 10:
            continue
        pb = r["pass_base"]
        pt = r["pass_rate"]
        # Fisher exact: [[pass_base, fail_base], [pass_treat, fail_treat]]
        a = int(round(pb * nb))
        b = int(nb - a)
        c = int(round(pt * nt))
        d = int(nt - c)
        _, p = sp_stats.fisher_exact([[a, b], [c, d]])
        if p < 0.05:
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*"
            sig_rows.append((r, p, sig))

    sig_rows.sort(key=lambda x: x[1])
    for r, p, sig in sig_rows:
        print(
            f"{r['case_id']:<30} {r['model_short']:<10} {r['cond_short']:<10} "
            f"{r['pass_base']:>6.0%} {r['pass_rate']:>6.0%} {r['delta']:>+6.0%} "
            f"{int(r['n_base']):>5} {int(r['n']):>5} {p:>7.4f} {sig:>4} {r['cluster']:<16}"
        )

    print(f"\n  Total significant triples: {len(sig_rows)}")
    # Summarize by direction
    pos = sum(1 for r, _, _ in sig_rows if r["delta"] > 0)
    neg = sum(1 for r, _, _ in sig_rows if r["delta"] < 0)
    print(f"  Positive (treatment helps): {pos}")
    print(f"  Negative (treatment hurts): {neg}")

    # By condition
    print(f"\n  By condition:")
    from collections import Counter
    cond_counts = Counter()
    cond_pos = Counter()
    cond_neg = Counter()
    for r, _, _ in sig_rows:
        cs = r["cond_short"]
        cond_counts[cs] += 1
        if r["delta"] > 0:
            cond_pos[cs] += 1
        else:
            cond_neg[cs] += 1
    for cs in sorted(cond_counts.keys()):
        print(f"    {cs:<10} total={cond_counts[cs]:>3}  +{cond_pos[cs]:>2} / -{cond_neg[cs]:>2}")

    print("\nDone.")


if __name__ == "__main__":
    main()
