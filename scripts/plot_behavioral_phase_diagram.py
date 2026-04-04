#!/usr/bin/env python3
"""Publication-quality phase diagram and supporting figures from behavioral clusters."""

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
INPUT = PROJECT / "outputs" / "analysis" / "behavioral_clusters.txt"
FIG_DIR = PROJECT / "outputs" / "figures"
TAB_DIR = PROJECT / "outputs" / "tables"
FIG_DIR.mkdir(parents=True, exist_ok=True)
TAB_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. PARSE ────────────────────────────────────────────────────────────────

def parse_value(s):
    s = s.strip()
    if s == "—" or s == "":
        return np.nan
    return float(s.replace("%", "").replace("+", ""))

def parse_clusters(path):
    rows = []
    current_cluster = None
    in_data = False

    for line in path.read_text().splitlines():
        stripped = line.strip()

        # Detect cluster header
        m = re.match(r"^([\w\-]+.*?)\s+\(\d+ cases?\)\s*$", stripped)
        if m:
            current_cluster = m.group(1).strip()
            in_data = False
            continue

        if stripped.startswith("Case") and "base" in stripped:
            in_data = True
            continue
        if stripped.startswith("---") or stripped.startswith("───"):
            continue
        if stripped.startswith("Summary:"):
            in_data = False
            continue
        if stripped.startswith("="):
            in_data = False
            continue
        if stripped.startswith("CLUSTER SUMMARY"):
            break

        if in_data and current_cluster and stripped:
            parts = stripped.split()
            if len(parts) < 7:
                continue
            case_name = parts[0]
            try:
                base = parse_value(parts[1])
                dcrit = parse_value(parts[2])
                dro = parse_value(parts[3])
                dretry = parse_value(parts[4])
                leg = parse_value(parts[5])
                mech = parse_value(parts[6])
                n = int(parts[7]) if len(parts) > 7 else np.nan
            except (ValueError, IndexError):
                continue

            rows.append({
                "case": case_name,
                "base": base,
                "delta_crit": dcrit,
                "delta_ro": dro,
                "delta_retry": dretry,
                "LEG": leg,
                "mech": mech,
                "n": n,
                "cluster_label": current_cluster,
            })

    return pd.DataFrame(rows)


df = parse_clusters(INPUT)
assert len(df) > 0, f"Parsed 0 rows from {INPUT}"

# ── 2. DERIVED FIELDS ───────────────────────────────────────────────────────

df["base_norm"] = df["base"] / 100.0
df["LEG_norm"] = df["LEG"] / 100.0
df["delta_max"] = df[["delta_crit", "delta_ro", "delta_retry"]].max(axis=1)
df["delta_gap"] = df["delta_crit"] - df["delta_ro"]


def classify_regime(row):
    if row["base"] <= 5:
        return "representation_limited"
    elif row["LEG"] >= 60 and row["delta_max"] >= 20:
        return "execution_limited"
    elif row["LEG"] >= 60 and row["delta_max"] < 10:
        return "pseudo_leg"
    elif 30 <= row["LEG"] < 60:
        return "ambiguous"
    elif row["base"] >= 90:
        return "ceiling"
    else:
        return "low_leg"


df["regime_label"] = df.apply(classify_regime, axis=1)

# ── STYLE DEFAULTS ───────────────────────────────────────────────────────────

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.linewidth": 0.8,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "figure.dpi": 200,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})

ANNOTATE_CASES = [
    "async_race_lock", "stale_config_reload",
    "config_shadowing", "dual_cause_ambiguous",
]

REGIME_COLORS = {
    "representation_limited": "#d62728",
    "execution_limited": "#2ca02c",
    "pseudo_leg": "#ff7f0e",
    "ambiguous": "#9467bd",
    "low_leg": "#1f77b4",
    "ceiling": "#999999",
}

REGIME_ORDER = [
    "representation_limited", "execution_limited", "pseudo_leg",
    "ambiguous", "low_leg", "ceiling",
]

# ── 3. FIGURE 1 — PHASE DIAGRAM (continuous color) ──────────────────────────

fig, ax = plt.subplots(figsize=(7, 5.5))

vmin, vmax = 0, df["delta_max"].quantile(0.95)
vmax = max(vmax, 20)

sc = ax.scatter(
    df["base"], df["LEG"],
    c=df["delta_max"], cmap="YlOrRd", vmin=vmin, vmax=vmax,
    s=80, edgecolors="black", linewidths=0.5, alpha=0.85, zorder=3,
)

cbar = fig.colorbar(sc, ax=ax, pad=0.02)
cbar.set_label("Max $\\Delta$pass (pp)", fontsize=10)

for _, row in df.iterrows():
    if row["case"] in ANNOTATE_CASES:
        ax.annotate(
            row["case"].replace("_", " "),
            (row["base"], row["LEG"]),
            textcoords="offset points", xytext=(6, 6),
            fontsize=7, fontstyle="italic", color="#333333",
            arrowprops=dict(arrowstyle="-", color="#aaaaaa", lw=0.5),
        )

ax.set_xlabel("Baseline Pass Rate (%)", fontsize=11)
ax.set_ylabel("LEG Rate (%)", fontsize=11)
ax.set_title("LLM Behavioral Phase Diagram: Baseline vs LEG", fontsize=12, fontweight="bold")
ax.set_xlim(-3, 103)
ax.set_ylim(-3, 103)
ax.grid(True, linewidth=0.3, alpha=0.5)

fig.savefig(FIG_DIR / "phase_diagram.png")
plt.close(fig)

# ── 4. FIGURE 2 — REGIME-COLORED PHASE DIAGRAM ─────────────────────────────

fig, ax = plt.subplots(figsize=(7, 5.5))

for regime in REGIME_ORDER:
    sub = df[df["regime_label"] == regime]
    if sub.empty:
        continue
    ax.scatter(
        sub["base"], sub["LEG"],
        c=REGIME_COLORS[regime], label=regime.replace("_", " "),
        s=80, edgecolors="black", linewidths=0.5, alpha=0.85, zorder=3,
    )

for _, row in df.iterrows():
    if row["case"] in ANNOTATE_CASES:
        ax.annotate(
            row["case"].replace("_", " "),
            (row["base"], row["LEG"]),
            textcoords="offset points", xytext=(6, 6),
            fontsize=7, fontstyle="italic", color="#333333",
            arrowprops=dict(arrowstyle="-", color="#aaaaaa", lw=0.5),
        )

ax.set_xlabel("Baseline Pass Rate (%)", fontsize=11)
ax.set_ylabel("LEG Rate (%)", fontsize=11)
ax.set_title("Behavioral Regimes", fontsize=12, fontweight="bold")
ax.set_xlim(-3, 103)
ax.set_ylim(-3, 103)
ax.grid(True, linewidth=0.3, alpha=0.5)
ax.legend(fontsize=8, loc="upper right", framealpha=0.9, edgecolor="#cccccc")

fig.savefig(FIG_DIR / "phase_diagram_regimes.png")
plt.close(fig)

# ── 5. FIGURE 3 — INTERVENTION EFFECT BY REGIME ────────────────────────────

regime_agg = df.groupby("regime_label").agg(
    n=("case", "count"),
    mean_dcrit=("delta_crit", "mean"),
    mean_dro=("delta_ro", "mean"),
    mean_dretry=("delta_retry", "mean"),
).reindex(REGIME_ORDER).dropna(how="all")

fig, ax = plt.subplots(figsize=(8, 4.5))

x = np.arange(len(regime_agg))
w = 0.25

bars_crit = ax.bar(x - w, regime_agg["mean_dcrit"], w, label="$\\Delta$crit", color="#1f77b4", edgecolor="black", linewidth=0.4)
bars_ro = ax.bar(x, regime_agg["mean_dro"], w, label="$\\Delta$ro", color="#ff7f0e", edgecolor="black", linewidth=0.4)
bars_retry = ax.bar(x + w, regime_agg["mean_dretry"], w, label="$\\Delta$retry", color="#2ca02c", edgecolor="black", linewidth=0.4)

ax.set_xticks(x)
ax.set_xticklabels([r.replace("_", "\n") for r in regime_agg.index], fontsize=8)
ax.set_ylabel("Mean $\\Delta$pass (pp)", fontsize=10)
ax.set_title("Intervention Effect by Regime", fontsize=12, fontweight="bold")
ax.axhline(0, color="black", linewidth=0.5)
ax.legend(fontsize=9, loc="upper left")
ax.grid(axis="y", linewidth=0.3, alpha=0.5)

fig.savefig(FIG_DIR / "intervention_by_regime.png")
plt.close(fig)

# ── 6. FIGURE 4 — Δcrit vs Δro ─────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(6, 6))

for regime in REGIME_ORDER:
    sub = df[df["regime_label"] == regime]
    if sub.empty:
        continue
    ax.scatter(
        sub["delta_ro"], sub["delta_crit"],
        c=REGIME_COLORS[regime], label=regime.replace("_", " "),
        s=70, edgecolors="black", linewidths=0.4, alpha=0.85, zorder=3,
    )

lim_lo = min(df["delta_ro"].min(), df["delta_crit"].min()) - 5
lim_hi = max(df["delta_ro"].max(), df["delta_crit"].max()) + 5
ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], "--", color="#888888", linewidth=0.8, zorder=1)

ax.set_xlabel("$\\Delta$ro (pp)", fontsize=11)
ax.set_ylabel("$\\Delta$crit (pp)", fontsize=11)
ax.set_title("Critique vs Reasoning-Only", fontsize=12, fontweight="bold")
ax.legend(fontsize=7, loc="upper left", framealpha=0.9, edgecolor="#cccccc")
ax.grid(True, linewidth=0.3, alpha=0.5)

ax.text(lim_hi - 2, lim_lo + 2, "ro better", fontsize=8, ha="right", color="#888888")
ax.text(lim_lo + 2, lim_hi - 2, "crit better", fontsize=8, ha="left", color="#888888")

fig.savefig(FIG_DIR / "crit_vs_ro.png")
plt.close(fig)

# ── 7. TABLE — REGIME SUMMARY ───────────────────────────────────────────────

summary = df.groupby("regime_label").agg(
    N=("case", "count"),
    avg_base=("base", "mean"),
    avg_LEG=("LEG", "mean"),
    avg_dcrit=("delta_crit", "mean"),
    avg_dro=("delta_ro", "mean"),
    avg_dmax=("delta_max", "mean"),
).reindex(REGIME_ORDER).dropna(how="all")

summary.to_csv(TAB_DIR / "regime_summary.csv")

print(summary.round(1).to_string())

# ── 8. SAVE CLEAN DATA ─────────────────────────────────────────────────────

df.to_csv(TAB_DIR / "behavioral_cases_processed.csv", index=False)

# ── DONE ────────────────────────────────────────────────────────────────────

print(f"\nOutputs:")
for f in [
    FIG_DIR / "phase_diagram.png",
    FIG_DIR / "phase_diagram_regimes.png",
    FIG_DIR / "intervention_by_regime.png",
    FIG_DIR / "crit_vs_ro.png",
    TAB_DIR / "regime_summary.csv",
    TAB_DIR / "behavioral_cases_processed.csv",
]:
    exists = "OK" if f.exists() else "MISSING"
    print(f"  [{exists}] {f.relative_to(PROJECT)}")
