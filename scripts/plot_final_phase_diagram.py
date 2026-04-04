# scripts/plot_final_phase_diagram.py

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# =========================
# LOAD DATA
# =========================
df = pd.read_csv("outputs/tables/behavioral_cases_processed.csv")

# Ensure required columns exist
required_cols = ["case", "base", "LEG", "delta_crit", "delta_ro", "delta_retry"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    raise ValueError(f"Missing required columns: {missing}")

# =========================
# DERIVED FIELDS
# =========================
df["delta_max"] = df[["delta_crit", "delta_ro", "delta_retry"]].max(axis=1, skipna=True)

# =========================
# PLOT SETUP
# =========================
plt.figure(figsize=(10, 8))

# Scatter
sc = plt.scatter(
    df["base"],
    df["LEG"],
    c=df["delta_max"],
    cmap="YlOrRd",
    vmin=0,
    vmax=40,
    s=100,
    edgecolors="black",
    alpha=0.9
)

# =========================
# BOUNDARIES
# =========================

plt.axvline(x=10, linestyle="--", linewidth=2.5, color="black", alpha=0.8)
plt.axvline(x=90, linestyle="--", linewidth=2.5, color="black", alpha=0.8)
plt.axhline(y=60, linestyle="--", linewidth=2.5, color="black", alpha=0.8)

# =========================
# SHADED REGIONS
# =========================

# Representation-limited (left)
plt.fill_betweenx(
    y=[0, 100],
    x1=0,
    x2=10,
    alpha=0.12
)

# Ceiling (right)
plt.fill_betweenx(
    y=[0, 100],
    x1=90,
    x2=100,
    alpha=0.12
)

# =========================
# HIGHLIGHT RINGS FOR KEY CASES
# =========================

def highlight_case(name):
    row = df[df["case"] == name]
    if len(row) == 0:
        return
    x = row["base"].values[0]
    y = row["LEG"].values[0]
    plt.scatter(
        x, y,
        s=260,
        facecolors='none',
        edgecolors='black',
        linewidth=2.2,
        zorder=5
    )

highlight_case("stale_config_reload")
highlight_case("config_shadowing")

# =========================
# ANNOTATIONS (KEY CASES)
# =========================

def annotate_case(name, label, dx=2, dy=2):
    row = df[df["case"] == name]
    if len(row) == 0:
        return
    x = row["base"].values[0]
    y = row["LEG"].values[0]
    plt.annotate(
        label,
        (x, y),
        xytext=(x + dx, y + dy),
        fontsize=10,
        arrowprops=dict(arrowstyle="-", lw=1)
    )

annotate_case("async_race_lock", "representation limit", dx=3, dy=3)
annotate_case("stale_config_reload", "convertible LEG", dx=3, dy=3)
annotate_case("config_shadowing", "pseudo-LEG", dx=3, dy=-5)
annotate_case("dual_cause_ambiguous", "ambiguous", dx=3, dy=3)

# =========================
# REGION LABELS
# =========================

plt.text(2, 50, "Representation-limited", fontsize=11, rotation=90, va="center")
plt.text(92, 50, "Solved / ceiling", fontsize=11, rotation=90, va="center")

# =========================
# COLORBAR
# =========================

cbar = plt.colorbar(sc)
cbar.set_label("Max Δpass (pp)")

# =========================
# AXES / TITLE
# =========================

plt.xlabel("Baseline Pass Rate (%)")
plt.ylabel("LEG Rate (%)")
plt.title("LLM Behavioral Phase Diagram: Baseline vs LEG")

plt.xlim(0, 100)
plt.ylim(0, 100)

plt.grid(True, linestyle="--", alpha=0.3)

# =========================
# SAVE
# =========================

plt.tight_layout()
plt.savefig("outputs/figures/final_phase_diagram.png", dpi=300)
plt.close()
