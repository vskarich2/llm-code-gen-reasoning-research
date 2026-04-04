#!/usr/bin/env python3
"""Case-centric analysis pipeline for experiment logs.

Usage:
    # As a script
    .venv/bin/python load_logs.py logs/v2_targeted_50trial_tranche4

    # As a library
    from analysis.load_logs import load_logs, prepare_df, run_analysis
    df = load_logs(["logs/v2_targeted_50trial_tranche4"])
    df = prepare_df(df)
    results = run_analysis(df, condition_pairs=[("baseline_v2", "leg_reduction_v2")])

Handles both log formats:
  - Newer (v2_*): top-level merged_events.jsonl with event_type field
  - Older: nested events.jsonl with flat case-result rows
"""

import json
import sys
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Private helpers: loading
# ---------------------------------------------------------------------------

def _load_case_metadata(cases_path):
    """Load cases_v2.json → dict mapping case_id to metadata.

    Returns dict: case_id → {family, difficulty, causal_depth}.
    Raises FileNotFoundError if cases_path does not exist.
    """
    path = Path(cases_path)
    if not path.exists():
        raise FileNotFoundError(f"Cases file not found: {path}")
    with open(path) as f:
        cases = json.load(f)
    return {
        c["id"]: {
            "family": c["family"],
            "difficulty": c["difficulty"],
            "causal_depth": c["causal_depth"],
        }
        for c in cases
    }


def _load_v2_events(jsonl_path, source):
    """Extract case.end rows from a v2-format merged_events.jsonl."""
    rows = []
    with open(jsonl_path) as f:
        for line in f:
            ev = json.loads(line)
            if ev.get("event_type") != "case.end":
                continue
            payload = ev.get("payload", {})
            execution = ev.get("execution", {})
            reasoning = ev.get("reasoning", {})
            v2 = payload.get("v2_artifact", {})
            ps_raw = v2.get("parse_status")
            rows.append({
                "source": source,
                "run_id": ev.get("run", {}).get("run_id"),
                "case_id": ev.get("case_id"),
                "model": ev.get("model"),
                "condition": ev.get("condition"),
                "trial_idx": ev.get("trial"),
                "attempt_idx": ev.get("attempt"),
                "pass": payload.get("pass"),
                "score": payload.get("score"),
                "tests_passed": execution.get("tests_passed"),
                "tests_total": execution.get("tests_run"),
                "reasoning_correct": reasoning.get("reasoning_correct"),
                "mechanism_label": reasoning.get("failure_type"),
                "parse_success": (
                    1 if ps_raw == "success"
                    else (0 if ps_raw is not None else None)
                ),
                "runtime_ms": execution.get("runtime_ms"),
                "timestamp": ev.get("timestamp"),
            })
    return rows


def _load_legacy_events(jsonl_path, source):
    """Extract case rows from an older-format events.jsonl."""
    rows = []
    with open(jsonl_path) as f:
        for line in f:
            ev = json.loads(line)
            if "case_id" not in ev:
                continue
            rows.append({
                "source": source,
                "run_id": ev.get("run_id"),
                "case_id": ev.get("case_id"),
                "model": ev.get("model"),
                "condition": ev.get("condition"),
                "trial_idx": ev.get("trial"),
                "attempt_idx": ev.get("num_attempts"),
                "pass": ev.get("pass"),
                "score": ev.get("score"),
                "tests_passed": None,
                "tests_total": None,
                "reasoning_correct": ev.get("reasoning_correct"),
                "mechanism_label": ev.get("failure_type"),
                "parse_success": None,
                "runtime_ms": (ev.get("elapsed_seconds") or 0) * 1000,
                "timestamp": ev.get("timestamp"),
            })
    return rows


def _find_jsonl_files(log_dir):
    """Find all loadable jsonl files in a log directory.

    Returns list of (path, format) where format is 'v2' or 'legacy'.
    """
    results = []
    top_merged = log_dir / "merged_events.jsonl"
    if top_merged.exists():
        return [(top_merged, "v2")]
    for p in sorted(log_dir.rglob("merged_events.jsonl")):
        results.append((p, "v2"))
    merged_paths = {r[0] for r in results}
    for p in sorted(log_dir.rglob("events.jsonl")):
        if (p.parent / "merged_events.jsonl") not in merged_paths:
            results.append((p, "legacy"))
    return results


# ---------------------------------------------------------------------------
# Public API: loading
# ---------------------------------------------------------------------------

def load_logs(log_dirs, cases_path="cases_v2.json"):
    """Load one or more log directories into a DataFrame.

    Each row is one case evaluation (one model x condition x case x trial).
    Joins family/difficulty/causal_depth from cases_path.
    """
    all_rows = []
    for log_dir in log_dirs:
        log_dir = Path(log_dir)
        if not log_dir.exists():
            print(f"WARNING: {log_dir} does not exist, skipping",
                  file=sys.stderr)
            continue
        source = log_dir.name
        files = _find_jsonl_files(log_dir)
        if not files:
            print(f"WARNING: no event files in {log_dir}, skipping",
                  file=sys.stderr)
            continue
        for path, fmt in files:
            if fmt == "v2":
                all_rows.extend(_load_v2_events(path, source))
            else:
                all_rows.extend(_load_legacy_events(path, source))

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["trial_idx"] = pd.to_numeric(df["trial_idx"], errors="coerce")
    df["score"] = pd.to_numeric(df["score"], errors="coerce")

    _join_case_metadata(df, cases_path)
    return df


def _join_case_metadata(df, cases_path):
    """Join family/difficulty/causal_depth from cases file onto df."""
    try:
        meta = _load_case_metadata(cases_path)
    except FileNotFoundError:
        print(f"WARNING: {cases_path} not found, skipping metadata join",
              file=sys.stderr)
        df["family"] = None
        df["difficulty"] = None
        df["causal_depth"] = None
        return
    for field in ("family", "difficulty", "causal_depth"):
        df[field] = df["case_id"].map(
            lambda cid, f=field: meta.get(cid, {}).get(f)
        )
    unmatched = df[df["family"].isna()]["case_id"].unique()
    if len(unmatched) > 0:
        print(f"WARNING: {len(unmatched)} case_ids not in metadata: "
              f"{list(unmatched)[:5]}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Public API: preparation
# ---------------------------------------------------------------------------

def prepare_df(df):
    """Validate schema, enforce types, add derived columns.

    Raises ValueError if required columns are missing or trial_idx has nulls.
    Filters rows with parse_success == 0 if that column has case_data.
    Adds: leg_true, lucky_fix, is_first_attempt.
    """
    required = ["case_id", "model", "condition", "trial_idx",
                "pass", "reasoning_correct"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if df["trial_idx"].isna().any():
        n = df["trial_idx"].isna().sum()
        raise ValueError(f"trial_idx has {n} null values")

    df = df.copy()
    df["trial_idx"] = df["trial_idx"].astype(int)
    df["pass"] = pd.to_numeric(df["pass"].astype(float), errors="coerce")
    df["reasoning_correct"] = pd.to_numeric(
        df["reasoning_correct"].astype(float), errors="coerce"
    )

    # Filter parse failures
    if "parse_success" in df.columns and df["parse_success"].notna().any():
        n_bad = (df["parse_success"] == 0).sum()
        if n_bad > 0:
            print(f"Filtering {n_bad} rows with parse_success==0",
                  file=sys.stderr)
            df = df[df["parse_success"] != 0].copy()

    # Derived columns (additive only)
    rc = df["reasoning_correct"]
    ps = df["pass"]
    df["leg_true"] = ((rc == 1) & (ps == 0)).astype(int)
    df["lucky_fix"] = ((rc == 0) & (ps == 1)).astype(int)
    df["is_first_attempt"] = (df.get("attempt_idx") == 1)
    return df


# ---------------------------------------------------------------------------
# Public API: pairing validation
# ---------------------------------------------------------------------------

def validate_pairing(df, condition_a, condition_b):
    """Validate that (case_id, model, trial_idx) pairs are balanced.

    Raises ValueError with diagnostics on any mismatch.
    """
    sub = df[df["condition"].isin([condition_a, condition_b])]
    # Check for duplicates
    dup_key = ["case_id", "model", "trial_idx", "condition"]
    dups = sub[sub.duplicated(subset=dup_key, keep=False)]
    if len(dups) > 0:
        examples = dups[dup_key].head(5).to_string(index=False)
        raise ValueError(
            f"Duplicate (case_id, model, trial_idx, condition) rows:\n"
            f"{examples}"
        )
    # Check coverage balance
    counts = (sub.groupby(["case_id", "model", "condition"])["trial_idx"]
              .count().unstack("condition"))
    missing_a = counts[counts[condition_a].isna()]
    missing_b = counts[counts[condition_b].isna()]
    if len(missing_a) > 0 or len(missing_b) > 0:
        parts = []
        if len(missing_a) > 0:
            parts.append(f"Missing {condition_a} for:\n"
                         f"{missing_a.head().to_string()}")
        if len(missing_b) > 0:
            parts.append(f"Missing {condition_b} for:\n"
                         f"{missing_b.head().to_string()}")
        raise ValueError("Unbalanced pairing:\n" + "\n".join(parts))
    # Check equal trial counts (warn, not raise — real case_data has minor
    # imbalances from crashed/failed trials; inner join handles this)
    mismatched = counts[counts[condition_a] != counts[condition_b]]
    if len(mismatched) > 0:
        print(f"WARNING: trial count mismatch for {len(mismatched)} "
              f"(case_id, model) groups — inner join will pair what "
              f"matches:\n{mismatched.head().to_string()}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Public API: analysis functions
# ---------------------------------------------------------------------------

_AGG_COLS = {
    "pass": ("pass_rate", "mean"),
    "reasoning_correct": ("reasoning_rate", "mean"),
    "leg_true": ("leg_rate", "mean"),
    "lucky_fix": ("lucky_fix_rate", "mean"),
}


def compute_leg_rates(df):
    """LEG decomposition grouped by (model, condition)."""
    agg = {v[0]: (k, v[1]) for k, v in _AGG_COLS.items()}
    agg["count"] = ("pass", "count")
    return df.groupby(["model", "condition"]).agg(**agg)


def compute_family_effects(df):
    """LEG decomposition grouped by (family, model, condition)."""
    agg = {v[0]: (k, v[1]) for k, v in _AGG_COLS.items()}
    agg["count"] = ("pass", "count")
    return df.groupby(["family", "model", "condition"]).agg(**agg)


def compute_paired_deltas(df, condition_a, condition_b):
    """Row-level paired deltas between two conditions.

    Pairs on (case_id, model, trial_idx). Calls validate_pairing first.
    Returns DataFrame with columns: case_id, model, trial_idx,
    pass_a, pass_b, reasoning_correct_a, reasoning_correct_b,
    leg_true_a, leg_true_b, delta_pass, delta_reasoning, delta_leg.
    """
    validate_pairing(df, condition_a, condition_b)
    keep = ["case_id", "model", "trial_idx",
            "pass", "reasoning_correct", "leg_true"]
    idx = ["case_id", "model", "trial_idx"]
    a = (df[df["condition"] == condition_a][keep]
         .set_index(idx).add_suffix("_a"))
    b = (df[df["condition"] == condition_b][keep]
         .set_index(idx).add_suffix("_b"))
    paired = a.join(b, how="inner").reset_index()
    paired["delta_pass"] = paired["pass_b"] - paired["pass_a"]
    paired["delta_reasoning"] = (paired["reasoning_correct_b"]
                                 - paired["reasoning_correct_a"])
    paired["delta_leg"] = paired["leg_true_b"] - paired["leg_true_a"]
    return paired


def _agg_deltas(paired, group_cols):
    """Aggregate paired deltas by group_cols with mean, std, count."""
    delta_cols = ["delta_pass", "delta_reasoning", "delta_leg"]
    agg_spec = {}
    for c in delta_cols:
        agg_spec[f"mean_{c}"] = (c, "mean")
        agg_spec[f"std_{c}"] = (c, "std")
    agg_spec["count"] = ("delta_pass", "count")
    return paired.groupby(group_cols).agg(**agg_spec)


def compute_case_model_deltas(df, condition_a, condition_b,
                              _paired=None):
    """Primary analysis artifact: delta table indexed by (case_id, model).

    Returns mean/std of delta_pass, delta_reasoning, delta_leg per
    (case_id, model) pair across trials.
    """
    if _paired is None:
        _paired = compute_paired_deltas(df, condition_a, condition_b)
    return _agg_deltas(_paired, ["case_id", "model"])


def compute_family_deltas(df, condition_a, condition_b, _paired=None):
    """Delta table indexed by (family, model).

    Returns mean/std of delta_pass, delta_reasoning, delta_leg per
    (family, model) pair across all trials and cases.
    """
    if _paired is None:
        _paired = compute_paired_deltas(df, condition_a, condition_b)
    paired = _paired.copy()
    family_map = df[["case_id", "family"]].drop_duplicates().set_index(
        "case_id")["family"]
    paired["family"] = paired["case_id"].map(family_map)
    return _agg_deltas(paired, ["family", "model"])


def compute_case_heterogeneity(df, condition_a, condition_b,
                               _paired=None):
    """Per-case heterogeneity analysis across models.

    Returns dict with:
      per_case: DataFrame (has_help, has_hurt, heterogeneous,
                best_model, worst_model, spread, family)
      heterogeneity_rate: float
      n_heterogeneous: int
      n_cases: int
    """
    cm = compute_case_model_deltas(df, condition_a, condition_b,
                                   _paired=_paired)
    family_map = (df[["case_id", "family"]].drop_duplicates()
                  .set_index("case_id")["family"])
    records = []
    for case_id, grp in cm.groupby("case_id"):
        deltas = grp["mean_delta_pass"]
        records.append({
            "case_id": case_id,
            "has_help": (deltas > 0).any(),
            "has_hurt": (deltas < 0).any(),
            "heterogeneous": (deltas > 0).any() and (deltas < 0).any(),
            "best_model": deltas.idxmax()[1],
            "worst_model": deltas.idxmin()[1],
            "spread": deltas.max() - deltas.min(),
            "family": family_map.get(case_id),
        })
    per_case = pd.DataFrame(records).set_index("case_id")
    n_het = int(per_case["heterogeneous"].sum())
    return {
        "per_case": per_case,
        "heterogeneity_rate": n_het / len(per_case) if len(per_case) else 0.0,
        "n_heterogeneous": n_het,
        "n_cases": len(per_case),
    }


# ---------------------------------------------------------------------------
# Public API: orchestrator
# ---------------------------------------------------------------------------

def run_analysis(df, condition_pairs, first_attempt_only=False):
    """Run full analysis pipeline.

    Args:
        df: prepared DataFrame (output of prepare_df)
        condition_pairs: list of (condition_a, condition_b) tuples
        first_attempt_only: if True, filter to is_first_attempt == True

    Returns dict with leg_rates, family_effects, and comparisons keyed
    by condition pair.
    """
    if first_attempt_only:
        df = df[df["is_first_attempt"]].copy()
    result = {
        "leg_rates": compute_leg_rates(df),
        "family_effects": compute_family_effects(df),
        "comparisons": {},
    }
    for cond_a, cond_b in condition_pairs:
        paired = compute_paired_deltas(df, cond_a, cond_b)
        delta_cols = ["delta_pass", "delta_reasoning", "delta_leg"]
        result["comparisons"][f"{cond_a}_vs_{cond_b}"] = {
            "paired_raw": paired,
            "delta_overall": paired[delta_cols].mean(),
            "delta_by_model": paired.groupby("model")[delta_cols].agg(
                ["mean", "std", "count"]),
            "delta_by_case": paired.groupby("case_id")[delta_cols].agg(
                ["mean", "std", "count"]),
            "case_model_deltas": compute_case_model_deltas(
                df, cond_a, cond_b, _paired=paired),
            "family_deltas": compute_family_deltas(
                df, cond_a, cond_b, _paired=paired),
            "heterogeneity": compute_case_heterogeneity(
                df, cond_a, cond_b, _paired=paired),
        }
    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <log_dir> [log_dir ...]")
        sys.exit(1)

    raw = load_logs(sys.argv[1:])
    if raw.empty:
        print("No case_data loaded.")
        sys.exit(1)

    df = prepare_df(raw)
    print(f"Loaded {len(df)} rows | "
          f"models={df['model'].unique().tolist()} | "
          f"conditions={df['condition'].unique().tolist()}")

    # Detect valid condition pairs: only pair conditions co-occurring
    # in the same source (prevents cross-source mismatches)
    pairs = []
    for source, sdf in df.groupby("source"):
        conds = sdf["condition"].unique().tolist()
        baselines = [c for c in conds if "baseline" in c]
        treatments = [c for c in conds if c not in baselines]
        pairs.extend((b, t) for b in baselines for t in treatments)

    if not pairs:
        print("\nNo baseline/treatment pairs detected. Printing leg_rates.")
        print(compute_leg_rates(df).to_string())
        sys.exit(0)

    print(f"\nCondition pairs: {pairs}")
    results = run_analysis(df, condition_pairs=pairs)

    print("\n=== LEG Rates ===")
    print(results["leg_rates"].to_string())

    # Show first comparison details
    first_key = list(results["comparisons"].keys())[0]
    comp = results["comparisons"][first_key]
    print(f"\n=== Comparison: {first_key} ===")

    print(f"\nDelta overall:\n{comp['delta_overall'].to_string()}")

    print(f"\nFamily deltas (head 10):")
    print(comp["family_deltas"].head(10).to_string())

    print(f"\nCase×model deltas (head 10):")
    print(comp["case_model_deltas"].head(10).to_string())

    het = comp["heterogeneity"]
    print(f"\nHeterogeneity: {het['n_heterogeneous']}/{het['n_cases']} "
          f"cases ({het['heterogeneity_rate']:.1%})")

    print(f"\nDelta by case (head 10):")
    print(comp["delta_by_case"].head(10).to_string())
