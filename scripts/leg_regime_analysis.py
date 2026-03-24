#!/usr/bin/env python
"""LEG_true × Trajectory Regime cross-analysis.

Reads finalized retry harness logs and produces:
- regime_summary.csv
- regime_leg_enrichment.csv
- subtype_by_regime.csv
- condition_comparison.csv
- transition_matrix.csv
- analysis_summary.json
- warnings.txt

Usage:
    python scripts/leg_regime_analysis.py \
        --input logs/gpt-4o-mini_*.jsonl \
        --cases cases_v2.json \
        --output-dir analysis/leg_regime/
"""

import argparse
import glob
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from failure_classifier import FAILURE_TYPE_SET

# ============================================================
# CONSTANTS
# ============================================================

ALLOWED_CONDITIONS = {
    "retry_no_contract", "retry_with_contract", "retry_adaptive", "retry_alignment",
}

_REGIME_NORMALIZE = {
    "single_shot": "SINGLE_SHOT",
    "MONOTONIC_FIX": "MONOTONIC_FIX",
    "OSCILLATING_FIX": "OSCILLATING_FIX",
    "OSCILLATION": "OSCILLATION",
    "DIVERGENCE": "DIVERGENCE",
    "STAGNATION": "STAGNATION",
    "UNCLASSIFIED": "UNCLASSIFIED",
    "monotonic_fix": "MONOTONIC_FIX",
    "oscillating_fix": "OSCILLATING_FIX",
    "oscillation": "OSCILLATION",
    "divergence": "DIVERGENCE",
    "stagnation": "STAGNATION",
    "unclassified": "UNCLASSIFIED",
    "single_shot_success": "SINGLE_SHOT",
}

ALLOWED_REGIMES = {
    "SINGLE_SHOT", "MONOTONIC_FIX", "OSCILLATING_FIX",
    "OSCILLATION", "DIVERGENCE", "STAGNATION", "UNCLASSIFIED", "UNKNOWN",
}

REGIME_GROUPS = {
    "SINGLE_SHOT": "converged", "MONOTONIC_FIX": "converged", "OSCILLATING_FIX": "converged",
    "STAGNATION": "stagnation", "DIVERGENCE": "divergence",
    "OSCILLATION": "oscillation", "UNCLASSIFIED": "other", "UNKNOWN": "other",
}

TRANSITION_STATES = ("SUCCESS", "FAILURE_NO_LEG", "LEG_TRUE_UNTYPED", "LEG_COUPLING", "LEG_EXECUTION")


# ============================================================
# LOADER
# ============================================================

def load_summaries(input_paths):
    """Load summary records from JSONL files."""
    summaries = []
    for pattern in input_paths:
        for fpath in sorted(glob.glob(pattern)):
            with open(fpath) as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("iteration") == "summary":
                        r["_source_file"] = fpath
                        summaries.append(r)
    return summaries


def load_case_metadata(cases_path):
    """Load case difficulty/family from cases JSON."""
    cases = json.loads(Path(cases_path).read_text())
    meta = {}
    for c in cases:
        meta[c["id"]] = {
            "difficulty": c.get("difficulty", "?"),
            "family": c.get("family", "?"),
            "failure_mode": c.get("failure_mode", "?"),
        }
    return meta


# ============================================================
# VALIDATION
# ============================================================

def validate(summaries, warnings):
    """Run validation checks. Returns list of valid summaries."""
    valid = []
    for s in summaries:
        cid = s.get("case_id", "")
        cond = s.get("condition", "")
        model = s.get("model", "")

        if not cid:
            warnings.append(f"ERROR: missing case_id in {s.get('_source_file')}")
            continue
        if cond not in ALLOWED_CONDITIONS:
            warnings.append(f"ERROR: invalid condition '{cond}' for {cid}")
            continue
        if not model:
            warnings.append(f"ERROR: missing model for {cid}")
            continue
        if not isinstance(s.get("converged"), bool):
            warnings.append(f"ERROR: converged not bool for {cid}/{cond}")
            continue

        traj = s.get("trajectory")
        if not isinstance(traj, list) or len(traj) < 1:
            warnings.append(f"WARNING: empty/missing trajectory for {cid}/{cond}, skipping")
            continue
        if s.get("total_iterations_executed") != len(traj):
            warnings.append(f"ERROR: iteration count mismatch for {cid}/{cond}")
            continue

        td = s.get("trajectory_dynamics")
        if not isinstance(td, dict) or "pattern" not in td:
            warnings.append(f"WARNING: missing trajectory_dynamics for {cid}/{cond}, skipping")
            continue

        valid.append(s)
    return valid


# ============================================================
# REGIME NORMALIZATION
# ============================================================

def normalize_regime(raw, warnings, context=""):
    n = _REGIME_NORMALIZE.get(raw)
    if n:
        return n
    warnings.append(f"WARNING: unknown regime '{raw}' for {context}, mapped to UNKNOWN")
    return "UNKNOWN"


# ============================================================
# RUN-LEVEL DERIVED METRICS
# ============================================================

def compute_run_metrics(s, warnings):
    """Compute all run-level metrics from a summary record."""
    traj = s["trajectory"]
    cid = s["case_id"]
    cond = s["condition"]

    # Evaluator enabled
    evaluator_enabled = any(
        e.get("llm_eval_blind_verdict") is not None for e in traj
    )

    failed = [e for e in traj if not e.get("pass", True)]
    failed_count = len(failed)

    # Evaluated failed: leg_true is True or False (not None)
    evaluated_failed = [e for e in failed if e.get("leg_true") is not None]
    evaluated_failed_count = len(evaluated_failed)

    # LEG counts — only failed attempts with leg_true explicitly True
    leg_true_count = sum(1 for e in failed if e.get("leg_true") is True)
    ever_leg_true = leg_true_count > 0 if evaluator_enabled else None

    # Rate within run
    leg_true_rate = (
        round(leg_true_count / evaluated_failed_count, 3)
        if evaluated_failed_count > 0 else None
    )

    # Persistence
    max_streak = 0
    current = 0
    for e in traj:
        if not e.get("pass", True) and e.get("leg_true") is True:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    # First LEG attempt
    first_leg = None
    if ever_leg_true:
        for e in traj:
            if not e.get("pass", True) and e.get("leg_true") is True:
                first_leg = e.get("attempt", 0)
                break

    # LEG to success
    leg_to_success = False
    for i in range(len(traj) - 1):
        if (not traj[i].get("pass", True)
                and traj[i].get("leg_true") is True
                and traj[i + 1].get("pass", False)):
            leg_to_success = True
            break

    # Subtype counts (only failed + leg_true)
    coupling_count = sum(1 for e in failed if e.get("leg_coupling") is True)
    execution_count = sum(1 for e in failed if e.get("leg_execution") is True)

    # Dominant subtype
    dominant = None
    if cond == "retry_alignment" and leg_true_count > 0:
        if coupling_count > execution_count:
            dominant = "coupling"
        elif execution_count > coupling_count:
            dominant = "execution"
        elif coupling_count == execution_count and coupling_count > 0:
            dominant = "mixed"
        else:
            dominant = "none"

    # Alignment scores
    scores = [e["alignment_step_coverage"] for e in traj
              if e.get("alignment_step_coverage") is not None]
    align_mean = round(mean(scores), 3) if scores else None
    align_std = round(stdev(scores), 3) if len(scores) >= 2 else None
    align_min = round(min(scores), 3) if scores else None
    align_max = round(max(scores), 3) if scores else None

    regime = normalize_regime(
        s.get("trajectory_dynamics", {}).get("pattern", "UNKNOWN"),
        warnings, f"{cid}/{cond}"
    )

    return {
        "case_id": cid,
        "condition": cond,
        "model": s["model"],
        "converged": s["converged"],
        "total_iterations": s["total_iterations_executed"],
        "failed_count": failed_count,
        "evaluator_enabled": evaluator_enabled,
        "evaluated_failed_count": evaluated_failed_count,
        "ever_leg_true": ever_leg_true,
        "leg_true_count": leg_true_count,
        "leg_true_rate_within_run": leg_true_rate,
        "leg_true_persistence": max_streak,
        "first_leg_true_attempt": first_leg,
        "leg_true_to_success": leg_to_success,
        "leg_coupling_count": coupling_count,
        "leg_execution_count": execution_count,
        "dominant_leg_subtype": dominant,
        "alignment_score_mean": align_mean,
        "alignment_score_std": align_std,
        "alignment_score_min": align_min,
        "alignment_score_max": align_max,
        "regime": regime,
        "regime_group": REGIME_GROUPS.get(regime, "other"),
    }


# ============================================================
# ATTEMPT-LEVEL STATE
# ============================================================

def compute_attempt_state(attempt):
    """Assign transition state from pass, leg_true, alignment_success."""
    if attempt.get("pass", False):
        return "SUCCESS"
    if attempt.get("leg_true") is not True:
        return "FAILURE_NO_LEG"
    # leg_true is True
    alignment = attempt.get("alignment_success")
    if alignment is True:
        return "LEG_EXECUTION"
    elif alignment is False:
        return "LEG_COUPLING"
    else:
        return "LEG_TRUE_UNTYPED"


# ============================================================
# TRANSITION MATRIX
# ============================================================

def build_transition_matrix(summaries, run_metrics_list):
    """Build transition counts from trajectories."""
    counts = defaultdict(lambda: defaultdict(int))  # (model, cond) -> {(from, to) -> count}

    for s, rm in zip(summaries, run_metrics_list):
        if not rm["evaluator_enabled"]:
            continue
        traj = s["trajectory"]
        key = (rm["model"], rm["condition"])
        states = [compute_attempt_state(e) for e in traj]
        for i in range(len(states) - 1):
            counts[key][(states[i], states[i + 1])] += 1

    return counts


# ============================================================
# STATISTICAL TESTS
# ============================================================

def fisher_exact_test(a, b, c, d):
    """2x2 Fisher exact test. Returns (odds_ratio, p_value)."""
    try:
        from scipy.stats import fisher_exact
        table = [[a, b], [c, d]]
        odds, p = fisher_exact(table, alternative="two-sided")
        return round(odds, 3), round(p, 4)
    except ImportError:
        # scipy not available — return None
        return None, None
    except Exception:
        return None, None


def proportion_ztest(x1, n1, x2, n2):
    """Two-proportion z-test. Returns (z, p, ci_low, ci_high)."""
    if n1 == 0 or n2 == 0:
        return None, None, None, None
    p1 = x1 / n1
    p2 = x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    if p_pool == 0 or p_pool == 1:
        return None, None, None, None
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None, None, None, None
    z = (p1 - p2) / se
    # Two-sided p from normal approx
    p_val = 2 * (1 - _norm_cdf(abs(z)))
    diff = p1 - p2
    se_diff = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) if n1 > 0 and n2 > 0 else 0
    ci_lo = round(diff - 1.96 * se_diff, 4)
    ci_hi = round(diff + 1.96 * se_diff, 4)
    return round(z, 3), round(p_val, 4), ci_lo, ci_hi


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ============================================================
# CSV WRITER
# ============================================================

def write_csv(path, rows, columns):
    with open(path, "w") as f:
        f.write(",".join(columns) + "\n")
        for row in rows:
            vals = [str(row.get(c, "")) if row.get(c) is not None else "" for c in columns]
            f.write(",".join(vals) + "\n")


# ============================================================
# MAIN ANALYSIS
# ============================================================

def run_analysis(summaries, run_metrics_list, case_meta, output_dir, min_cell, warnings):
    os.makedirs(output_dir, exist_ok=True)

    # ── Table 1: regime_summary ──
    groups = defaultdict(list)
    for rm in run_metrics_list:
        groups[(rm["model"], rm["condition"], rm["regime"])].append(rm)

    regime_rows = []
    for (model, cond, regime), runs in sorted(groups.items()):
        eval_runs = [r for r in runs if r["evaluator_enabled"]]
        leg_runs = [r for r in eval_runs if r["ever_leg_true"] is not None]

        row = {
            "model": model, "condition": cond, "regime": regime,
            "regime_group": REGIME_GROUPS.get(regime, "other"),
            "run_count": len(runs),
            "evaluator_run_count": len(eval_runs),
            "convergence_rate": round(sum(1 for r in runs if r["converged"]) / len(runs), 3),
        }
        if leg_runs:
            row["ever_leg_true_rate"] = round(sum(1 for r in leg_runs if r["ever_leg_true"]) / len(leg_runs), 3)
            row["mean_leg_true_count"] = round(mean(r["leg_true_count"] for r in leg_runs), 2)
            row["mean_leg_true_persistence"] = round(mean(r["leg_true_persistence"] for r in leg_runs), 2)
            rates = [r["leg_true_rate_within_run"] for r in leg_runs if r["leg_true_rate_within_run"] is not None]
            row["mean_leg_true_rate_within_run"] = round(mean(rates), 3) if rates else None
        regime_rows.append(row)

    write_csv(f"{output_dir}/regime_summary.csv", regime_rows,
              ["model", "condition", "regime", "regime_group", "run_count",
               "evaluator_run_count", "convergence_rate", "ever_leg_true_rate",
               "mean_leg_true_count", "mean_leg_true_persistence", "mean_leg_true_rate_within_run"])

    # ── Table 2: regime_leg_enrichment ──
    enrichment_rows = []
    model_groups = defaultdict(list)
    for rm in run_metrics_list:
        if rm["evaluator_enabled"] and rm["ever_leg_true"] is not None:
            model_groups[rm["model"]].append(rm)

    for model, runs in sorted(model_groups.items()):
        regimes_seen = set(r["regime"] for r in runs)
        for regime in sorted(regimes_seen):
            in_r = [r for r in runs if r["regime"] == regime]
            out_r = [r for r in runs if r["regime"] != regime]

            in_leg = sum(1 for r in in_r if r["ever_leg_true"])
            out_leg = sum(1 for r in out_r if r["ever_leg_true"])

            rate_in = in_leg / len(in_r) if in_r else 0
            rate_out = out_leg / len(out_r) if out_r else 0
            ratio = round(rate_in / rate_out, 3) if rate_out > 0 else None

            a, b = in_leg, len(in_r) - in_leg
            c, d = out_leg, len(out_r) - out_leg
            odds, p = fisher_exact_test(a, b, c, d)

            enrichment_rows.append({
                "model": model, "regime": regime,
                "leg_true_rate_in_regime": round(rate_in, 3),
                "leg_true_rate_outside_regime": round(rate_out, 3),
                "enrichment_ratio": ratio,
                "fisher_odds_ratio": odds, "fisher_p_value": p,
                "small_sample_flag": min(a + b, c + d) < 5,
                "evaluator_runs_in_regime": len(in_r),
                "evaluator_runs_outside": len(out_r),
            })

    write_csv(f"{output_dir}/regime_leg_enrichment.csv", enrichment_rows,
              ["model", "regime", "leg_true_rate_in_regime", "leg_true_rate_outside_regime",
               "enrichment_ratio", "fisher_odds_ratio", "fisher_p_value",
               "small_sample_flag", "evaluator_runs_in_regime", "evaluator_runs_outside"])

    # ── Table 3: subtype_by_regime ──
    subtype_rows = []
    for model, runs in sorted(model_groups.items()):
        align_leg = [r for r in runs if r["condition"] == "retry_alignment" and r["ever_leg_true"]]
        regime_sub = defaultdict(list)
        for r in align_leg:
            regime_sub[r["regime"]].append(r)
        for regime, rs in sorted(regime_sub.items()):
            total_c = sum(r["leg_coupling_count"] for r in rs)
            total_e = sum(r["leg_execution_count"] for r in rs)
            total = total_c + total_e
            subtype_rows.append({
                "model": model, "regime": regime, "leg_true_runs": len(rs),
                "coupling_count": total_c, "execution_count": total_e,
                "coupling_fraction": round(total_c / total, 3) if total > 0 else None,
                "execution_fraction": round(total_e / total, 3) if total > 0 else None,
            })

    if subtype_rows:
        write_csv(f"{output_dir}/subtype_by_regime.csv", subtype_rows,
                  ["model", "regime", "leg_true_runs", "coupling_count", "execution_count",
                   "coupling_fraction", "execution_fraction"])

    # ── Table 4: condition_comparison ──
    comparison_rows = []
    conditions_found = sorted(set(r["condition"] for r in run_metrics_list))
    if len(conditions_found) >= 2:
        cond_a, cond_b = conditions_found[0], conditions_found[-1]
        for model in sorted(set(r["model"] for r in run_metrics_list)):
            for diff in sorted(set(case_meta.get(r["case_id"], {}).get("difficulty", "?")
                                   for r in run_metrics_list if r["model"] == model)):
                runs_a = [r for r in run_metrics_list
                          if r["model"] == model and r["condition"] == cond_a
                          and case_meta.get(r["case_id"], {}).get("difficulty") == diff]
                runs_b = [r for r in run_metrics_list
                          if r["model"] == model and r["condition"] == cond_b
                          and case_meta.get(r["case_id"], {}).get("difficulty") == diff]

                for metric_name, getter in [
                    ("convergence_rate", lambda rs: sum(1 for r in rs if r["converged"]) / len(rs) if rs else None),
                    ("ever_leg_true_rate", lambda rs: (
                        sum(1 for r in rs if r["evaluator_enabled"] and r["ever_leg_true"]) /
                        max(sum(1 for r in rs if r["evaluator_enabled"] and r["ever_leg_true"] is not None), 1)
                    ) if any(r["evaluator_enabled"] for r in rs) else None),
                ]:
                    va = getter(runs_a)
                    vb = getter(runs_b)
                    delta = round(vb - va, 3) if va is not None and vb is not None else None
                    underpowered = len(runs_a) < 10 or len(runs_b) < 10

                    comparison_rows.append({
                        "model": model, "difficulty": diff, "metric": metric_name,
                        "condition_a": cond_a, "condition_a_value": round(va, 3) if va else None,
                        "condition_b": cond_b, "condition_b_value": round(vb, 3) if vb else None,
                        "delta": delta, "p_value": None, "underpowered": underpowered,
                    })

    if comparison_rows:
        write_csv(f"{output_dir}/condition_comparison.csv", comparison_rows,
                  ["model", "difficulty", "metric", "condition_a", "condition_a_value",
                   "condition_b", "condition_b_value", "delta", "p_value", "underpowered"])

    # ── Table 5: transition_matrix ──
    trans_counts = build_transition_matrix(summaries, run_metrics_list)
    trans_rows = []
    for (model, cond), pairs in sorted(trans_counts.items()):
        # Row totals for normalization
        row_totals = defaultdict(int)
        for (fs, ts), cnt in pairs.items():
            row_totals[fs] += cnt
        for (fs, ts), cnt in sorted(pairs.items()):
            prob = round(cnt / row_totals[fs], 3) if row_totals[fs] > 0 else 0.0
            trans_rows.append({
                "model": model, "condition": cond,
                "from_state": fs, "to_state": ts,
                "count": cnt, "probability": prob,
            })

    write_csv(f"{output_dir}/transition_matrix.csv", trans_rows,
              ["model", "condition", "from_state", "to_state", "count", "probability"])

    # ── analysis_summary.json ──
    summary_json = {
        "total_summaries_loaded": len(summaries),
        "valid_summaries": len(run_metrics_list),
        "evaluator_enabled_runs": sum(1 for r in run_metrics_list if r["evaluator_enabled"]),
        "models": sorted(set(r["model"] for r in run_metrics_list)),
        "conditions": sorted(set(r["condition"] for r in run_metrics_list)),
        "regimes_seen": sorted(set(r["regime"] for r in run_metrics_list)),
        "warning_count": len(warnings),
    }
    with open(f"{output_dir}/analysis_summary.json", "w") as f:
        json.dump(summary_json, f, indent=2)

    # ── warnings.txt ──
    with open(f"{output_dir}/warnings.txt", "w") as f:
        f.write("\n".join(warnings) if warnings else "No warnings.\n")

    return summary_json


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="LEG_true × Trajectory Regime Analysis")
    parser.add_argument("--input", nargs="+", required=True, help="JSONL log files (glob supported)")
    parser.add_argument("--cases", required=True, help="Path to cases_v2.json")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--models", default=None, help="Comma-separated model filter")
    parser.add_argument("--conditions", default=None, help="Comma-separated condition filter")
    parser.add_argument("--difficulty", default=None, help="Comma-separated difficulty filter")
    parser.add_argument("--min-runs-per-cell", type=int, default=5)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    warnings = []

    # Load
    summaries = load_summaries(args.input)
    case_meta = load_case_metadata(args.cases)

    if not summaries:
        print("ERROR: no summary records found in input files")
        sys.exit(1)

    # Filter
    if args.models:
        models = set(args.models.split(","))
        summaries = [s for s in summaries if s.get("model") in models]
    if args.conditions:
        conds = set(args.conditions.split(","))
        summaries = [s for s in summaries if s.get("condition") in conds]
    if args.difficulty:
        diffs = set(args.difficulty.split(","))
        summaries = [s for s in summaries
                     if case_meta.get(s.get("case_id"), {}).get("difficulty") in diffs]

    if not summaries:
        print("ERROR: no runs match filters")
        sys.exit(1)

    # Validate
    summaries = validate(summaries, warnings)
    if args.strict and any(w.startswith("WARNING") for w in warnings):
        print("STRICT MODE: warnings found, exiting")
        for w in warnings:
            print(f"  {w}")
        sys.exit(1)

    if not summaries:
        print("ERROR: no valid summaries after validation")
        sys.exit(1)

    # Compute run-level metrics
    run_metrics = [compute_run_metrics(s, warnings) for s in summaries]

    # Run analysis
    summary = run_analysis(summaries, run_metrics, case_meta, args.output_dir,
                           args.min_runs_per_cell, warnings)

    print(f"Analysis complete: {summary['valid_summaries']} runs, "
          f"{summary['evaluator_enabled_runs']} with evaluator")
    print(f"Output: {args.output_dir}/")
    if warnings:
        print(f"Warnings: {len(warnings)} (see {args.output_dir}/warnings.txt)")


if __name__ == "__main__":
    main()
