#!/usr/bin/env python
"""T3 Ablation Analysis — maximum-rigor formal audit.

Usage:
    .venv/bin/python scripts/ablation_analysis.py logs/ablation_lag
    .venv/bin/python scripts/ablation_analysis.py logs/ablation_lag logs/ablation_full
    .venv/bin/python scripts/ablation_analysis.py logs/ablation_lag --output-dir analysis_out
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ============================================================
# DATA LOADING
# ============================================================


def load_runs(run_dirs: list[Path]) -> list[dict]:
    """Load all events from one or more ablation run directories.

    Scans recursively for events.jsonl files. Skips corrupt lines.
    Never silently drops data — logs every skip.
    """
    events = []
    skipped = 0
    files_read = 0

    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        if not run_dir.exists():
            print(f"  WARNING: run_dir does not exist: {run_dir}", file=sys.stderr)
            continue
        for events_file in sorted(run_dir.rglob("events.jsonl")):
            files_read += 1
            for line_num, line in enumerate(events_file.open(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    event["_source_file"] = str(events_file)
                    event["_source_line"] = line_num
                    events.append(event)
                except json.JSONDecodeError:
                    skipped += 1
                    print(f"  WARNING: corrupt line {line_num} in {events_file}", file=sys.stderr)

    print(f"  Loaded {len(events)} events from {files_read} files ({skipped} corrupt lines skipped)")
    return events


# ============================================================
# NORMALIZATION
# ============================================================


def normalize_events(events: list[dict]) -> list[dict]:
    """Normalize events to a common schema. Handle missing fields safely."""
    for e in events:
        e.setdefault("case_id", None)
        e.setdefault("model", None)
        e.setdefault("condition", None)
        e.setdefault("trial", None)
        e.setdefault("pass", None)
        e.setdefault("score", None)
        e.setdefault("reasoning_correct", None)
        e.setdefault("code_correct", e.get("pass"))
        e.setdefault("category", None)
        e.setdefault("failure_type", None)
        e.setdefault("confidence", None)
        e.setdefault("parse_error", None)
        e.setdefault("parse_tier", None)
        e.setdefault("parse_repaired", None)
        e.setdefault("code_present", None)
        e.setdefault("reasoning_present", None)
        e.setdefault("reasoning_attempted", None)
        e.setdefault("elapsed_seconds", None)

        # Infer family and difficulty from case_id
        cid = e["case_id"] or ""
        if cid.endswith("_a"):
            e["difficulty"] = "A"
            e["family"] = cid[:-2]
        elif cid.endswith("_b"):
            e["difficulty"] = "B"
            e["family"] = cid[:-2]
        elif cid.endswith("_c"):
            e["difficulty"] = "C"
            e["family"] = cid[:-2]
        else:
            e["difficulty"] = "single"
            e["family"] = cid

        # Infer failure_mode from category if not present
        e.setdefault("failure_mode", None)

    # Filter out events with no case_id
    before = len(events)
    events = [e for e in events if e["case_id"] is not None]
    if len(events) < before:
        print(f"  WARNING: dropped {before - len(events)} events with no case_id", file=sys.stderr)

    return events


# ============================================================
# METRIC HELPERS
# ============================================================


@dataclass
class MetricAccumulator:
    """Tracks numerator/denominator for a rate metric."""
    numerator: int = 0
    denominator: int = 0

    @property
    def rate(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def add(self, value: bool | None):
        if value is not None:
            self.denominator += 1
            if value:
                self.numerator += 1

    def to_dict(self) -> dict:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate": round(self.rate, 6) if self.rate is not None else None,
        }


def _safe_rate(num, denom):
    if denom == 0:
        return None
    return round(num / denom, 6)


def _compute_group_metrics(events: list[dict]) -> dict:
    """Compute all metrics for a group of events."""
    n = len(events)
    if n == 0:
        return {"total_samples": 0}

    # Execution
    passed = sum(1 for e in events if e["pass"] is True)
    failed = sum(1 for e in events if e["pass"] is False)
    executed = passed + failed
    code_correct_count = sum(1 for e in events if e["code_correct"] is True)

    # Parse
    parse_failed = sum(1 for e in events if e.get("parse_error") and "SEVERE" in str(e.get("parse_error", "")))
    parse_failed += sum(1 for e in events if e.get("category") == "parse_failed")
    code_present_count = sum(1 for e in events if e.get("code_present") is True)

    # Reasoning
    rc_true = sum(1 for e in events if e["reasoning_correct"] is True)
    rc_false = sum(1 for e in events if e["reasoning_correct"] is False)
    rc_none = sum(1 for e in events if e["reasoning_correct"] is None)
    rc_evaluated = rc_true + rc_false

    # LEG and lucky fix
    leg_true = sum(1 for e in events
                   if e["reasoning_correct"] is True and e["code_correct"] is not True)
    lucky_fix = sum(1 for e in events
                    if e["reasoning_correct"] is not True and e["code_correct"] is True)

    # Conditional probabilities
    rc_true_events = [e for e in events if e["reasoning_correct"] is True]
    exec_given_reason = _safe_rate(
        sum(1 for e in rc_true_events if e["code_correct"] is True),
        len(rc_true_events)
    )

    cc_true_events = [e for e in events if e["code_correct"] is True]
    reason_given_exec = _safe_rate(
        sum(1 for e in cc_true_events if e["reasoning_correct"] is True),
        len(cc_true_events)
    )

    # Disagreement
    disagreement = sum(1 for e in events
                       if e["reasoning_correct"] is not None
                       and e["code_correct"] is not None
                       and e["reasoning_correct"] != e["code_correct"])

    # Categories
    category_counts = defaultdict(int)
    for e in events:
        cat = e.get("category") or "unknown"
        category_counts[cat] += 1

    # Confidence
    conf_counts = defaultdict(int)
    for e in events:
        c = e.get("confidence")
        if c:
            conf_counts[c] += 1

    # Failure types
    ftype_counts = defaultdict(int)
    for e in events:
        ft = e.get("failure_type")
        if ft:
            ftype_counts[ft] += 1

    return {
        "total_samples": n,
        "pass_rate": {"numerator": passed, "denominator": n, "rate": _safe_rate(passed, n)},
        "execution_rate": {"numerator": executed, "denominator": n, "rate": _safe_rate(executed, n)},
        "parse_failure_rate": {"numerator": parse_failed, "denominator": n, "rate": _safe_rate(parse_failed, n)},
        "reasoning_evaluated": {"numerator": rc_evaluated, "denominator": n, "rate": _safe_rate(rc_evaluated, n)},
        "reasoning_correct_rate": {"numerator": rc_true, "denominator": rc_evaluated, "rate": _safe_rate(rc_true, rc_evaluated)},
        "reasoning_none_count": rc_none,
        "leg_true_rate": {"numerator": leg_true, "denominator": n, "rate": _safe_rate(leg_true, n)},
        "lucky_fix_rate": {"numerator": lucky_fix, "denominator": n, "rate": _safe_rate(lucky_fix, n)},
        "disagreement_rate": {"numerator": disagreement, "denominator": rc_evaluated, "rate": _safe_rate(disagreement, rc_evaluated)},
        "exec_given_reason": exec_given_reason,
        "reason_given_exec": reason_given_exec,
        "category_counts": dict(category_counts),
        "confidence_counts": dict(conf_counts),
        "failure_type_counts": dict(ftype_counts),
    }


# ============================================================
# GLOBAL METRICS (per model, per condition)
# ============================================================


def compute_global_metrics(events: list[dict]) -> dict:
    """Compute metrics grouped by model and condition."""
    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    result = {"models": {}, "conditions": {}, "model_x_condition": {}}

    for model in models:
        model_events = [e for e in events if e["model"] == model]
        result["models"][model] = _compute_group_metrics(model_events)

        for cond in conditions:
            mc_events = [e for e in model_events if e["condition"] == cond]
            result["model_x_condition"][(model, cond)] = _compute_group_metrics(mc_events)

    for cond in conditions:
        cond_events = [e for e in events if e["condition"] == cond]
        result["conditions"][cond] = _compute_group_metrics(cond_events)

    result["overall"] = _compute_group_metrics(events)
    return result


# ============================================================
# CASE-LEVEL ANALYSIS
# ============================================================


def compute_case_metrics(events: list[dict]) -> dict:
    """Per-case metrics with variance across trials and models."""
    cases = sorted(set(e["case_id"] for e in events if e["case_id"]))
    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    case_metrics = {}
    for cid in cases:
        ce = [e for e in events if e["case_id"] == cid]
        m = _compute_group_metrics(ce)

        # Per-model pass rates
        per_model = {}
        for model in models:
            me = [e for e in ce if e["model"] == model]
            if me:
                per_model[model] = _safe_rate(
                    sum(1 for e in me if e["pass"] is True), len(me)
                )

        # Per-condition pass rates
        per_condition = {}
        for cond in conditions:
            conde = [e for e in ce if e["condition"] == cond]
            if conde:
                per_condition[cond] = _safe_rate(
                    sum(1 for e in conde if e["pass"] is True), len(conde)
                )

        # Variance across trials (per model)
        trial_variances = {}
        for model in models:
            trials = sorted(set(e["trial"] for e in ce if e["model"] == model and e["trial"] is not None))
            if len(trials) >= 2:
                trial_rates = []
                for t in trials:
                    te = [e for e in ce if e["model"] == model and e["trial"] == t]
                    if te:
                        trial_rates.append(sum(1 for e in te if e["pass"] is True) / len(te))
                if trial_rates:
                    mean = sum(trial_rates) / len(trial_rates)
                    var = sum((r - mean) ** 2 for r in trial_rates) / len(trial_rates)
                    trial_variances[model] = round(var, 6)

        # Model split: max - min pass rate across models
        model_rates = [v for v in per_model.values() if v is not None]
        model_split = (max(model_rates) - min(model_rates)) if len(model_rates) >= 2 else 0

        m["per_model_pass_rate"] = per_model
        m["per_condition_pass_rate"] = per_condition
        m["trial_variances"] = trial_variances
        m["model_split"] = round(model_split, 6)
        m["family"] = ce[0].get("family", "unknown") if ce else "unknown"
        m["difficulty"] = ce[0].get("difficulty", "unknown") if ce else "unknown"
        m["failure_mode"] = ce[0].get("failure_mode", "unknown") if ce else "unknown"

        case_metrics[cid] = m

    return case_metrics


# ============================================================
# FAMILY / FAILURE MODE ANALYSIS
# ============================================================


def compute_family_metrics(events: list[dict]) -> dict:
    """Aggregate metrics by family, failure_mode, and difficulty."""
    result = {"by_family": {}, "by_failure_mode": {}, "by_difficulty": {}}

    for group_key, field_name in [
        ("by_family", "family"),
        ("by_failure_mode", "failure_mode"),
        ("by_difficulty", "difficulty"),
    ]:
        groups = sorted(set(e.get(field_name, "unknown") for e in events))
        for g in groups:
            ge = [e for e in events if e.get(field_name) == g]
            if ge:
                m = _compute_group_metrics(ge)
                # Per-model within group
                models = sorted(set(e["model"] for e in ge if e["model"]))
                m["per_model"] = {}
                for model in models:
                    me = [e for e in ge if e["model"] == model]
                    m["per_model"][model] = {
                        "pass_rate": _safe_rate(sum(1 for e in me if e["pass"] is True), len(me)),
                        "leg_rate": _safe_rate(
                            sum(1 for e in me if e["reasoning_correct"] is True and e["code_correct"] is not True),
                            len(me)
                        ),
                        "n": len(me),
                    }
                result[group_key][g] = m

    return result


# ============================================================
# INTERVENTION ANALYSIS (condition deltas)
# ============================================================


def compute_condition_deltas(events: list[dict]) -> dict:
    """Compute deltas for each non-baseline condition vs baseline."""
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))
    models = sorted(set(e["model"] for e in events if e["model"]))
    families = sorted(set(e.get("family", "unknown") for e in events))

    if "baseline" not in conditions:
        return {"error": "no baseline condition found"}

    result = {"per_condition": {}, "per_condition_x_model": {}, "condition_x_family": {}}

    for cond in conditions:
        if cond == "baseline":
            continue

        # Global delta
        bl_events = [e for e in events if e["condition"] == "baseline"]
        cd_events = [e for e in events if e["condition"] == cond]
        bl_m = _compute_group_metrics(bl_events)
        cd_m = _compute_group_metrics(cd_events)

        bl_pass = bl_m["pass_rate"]["rate"] or 0
        cd_pass = cd_m["pass_rate"]["rate"] or 0
        bl_leg = bl_m["leg_true_rate"]["rate"] or 0
        cd_leg = cd_m["leg_true_rate"]["rate"] or 0
        bl_lucky = bl_m["lucky_fix_rate"]["rate"] or 0
        cd_lucky = cd_m["lucky_fix_rate"]["rate"] or 0

        result["per_condition"][cond] = {
            "delta_pass": round(cd_pass - bl_pass, 6),
            "delta_leg": round(cd_leg - bl_leg, 6),
            "delta_lucky": round(cd_lucky - bl_lucky, 6),
            "baseline_pass": bl_pass,
            "condition_pass": cd_pass,
            "baseline_n": bl_m["total_samples"],
            "condition_n": cd_m["total_samples"],
        }

        # Per-model delta
        for model in models:
            bl_me = [e for e in bl_events if e["model"] == model]
            cd_me = [e for e in cd_events if e["model"] == model]
            if not bl_me or not cd_me:
                continue
            bl_pr = sum(1 for e in bl_me if e["pass"] is True) / len(bl_me)
            cd_pr = sum(1 for e in cd_me if e["pass"] is True) / len(cd_me)
            bl_lr = sum(1 for e in bl_me if e["reasoning_correct"] is True and e["code_correct"] is not True) / len(bl_me)
            cd_lr = sum(1 for e in cd_me if e["reasoning_correct"] is True and e["code_correct"] is not True) / len(cd_me)

            result["per_condition_x_model"][(cond, model)] = {
                "delta_pass": round(cd_pr - bl_pr, 6),
                "delta_leg": round(cd_lr - bl_lr, 6),
                "baseline_pass": round(bl_pr, 6),
                "condition_pass": round(cd_pr, 6),
                "baseline_n": len(bl_me),
                "condition_n": len(cd_me),
            }

        # Per-family delta (condition x family heatmap)
        for family in families:
            bl_fe = [e for e in bl_events if e.get("family") == family]
            cd_fe = [e for e in cd_events if e.get("family") == family]
            if not bl_fe or not cd_fe:
                continue
            bl_pr = sum(1 for e in bl_fe if e["pass"] is True) / len(bl_fe)
            cd_pr = sum(1 for e in cd_fe if e["pass"] is True) / len(cd_fe)
            result["condition_x_family"][(cond, family)] = {
                "delta_pass": round(cd_pr - bl_pr, 6),
                "baseline_pass": round(bl_pr, 6),
                "condition_pass": round(cd_pr, 6),
                "n": len(bl_fe) + len(cd_fe),
            }

    return result


# ============================================================
# TRIAL CONSISTENCY
# ============================================================


def compute_trial_variance(events: list[dict]) -> dict:
    """Compute variance of pass_rate and LEG across trials."""
    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    result = {"per_model_condition": {}, "unstable_flags": []}

    for model in models:
        for cond in conditions:
            mc_events = [e for e in events if e["model"] == model and e["condition"] == cond]
            trials = sorted(set(e["trial"] for e in mc_events if e["trial"] is not None))
            if len(trials) < 2:
                continue

            pass_rates = []
            leg_rates = []
            for t in trials:
                te = [e for e in mc_events if e["trial"] == t]
                n = len(te)
                if n == 0:
                    continue
                pr = sum(1 for e in te if e["pass"] is True) / n
                lr = sum(1 for e in te
                         if e["reasoning_correct"] is True and e["code_correct"] is not True) / n
                pass_rates.append(pr)
                leg_rates.append(lr)

            if pass_rates:
                pass_mean = sum(pass_rates) / len(pass_rates)
                pass_var = sum((r - pass_mean) ** 2 for r in pass_rates) / len(pass_rates)
                leg_mean = sum(leg_rates) / len(leg_rates)
                leg_var = sum((r - leg_mean) ** 2 for r in leg_rates) / len(leg_rates)

                entry = {
                    "trials": len(trials),
                    "pass_mean": round(pass_mean, 6),
                    "pass_variance": round(pass_var, 6),
                    "pass_std": round(pass_var ** 0.5, 6),
                    "leg_mean": round(leg_mean, 6),
                    "leg_variance": round(leg_var, 6),
                    "leg_std": round(leg_var ** 0.5, 6),
                    "trial_pass_rates": [round(r, 4) for r in pass_rates],
                }
                result["per_model_condition"][(model, cond)] = entry

                if pass_var > 0.01:
                    result["unstable_flags"].append({
                        "model": model, "condition": cond,
                        "pass_variance": round(pass_var, 6),
                        "reason": "HIGH VARIANCE in pass_rate across trials",
                    })

    return result


# ============================================================
# PARSE / DATA QUALITY AUDIT
# ============================================================


def compute_parse_audit(events: list[dict]) -> dict:
    """Audit parse quality and data completeness."""
    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))
    n = len(events)

    # Field completeness
    fields = ["pass", "reasoning_correct", "code_correct", "category",
              "failure_type", "confidence", "parse_error", "code_present",
              "reasoning_present", "elapsed_seconds"]
    completeness = {}
    for f in fields:
        present = sum(1 for e in events if e.get(f) is not None)
        completeness[f] = {"present": present, "total": n, "rate": _safe_rate(present, n)}

    # Parse failures per model and condition
    parse_by_model = {}
    for model in models:
        me = [e for e in events if e["model"] == model]
        pf = sum(1 for e in me if e.get("category") == "parse_failed")
        parse_by_model[model] = {"parse_failed": pf, "total": len(me), "rate": _safe_rate(pf, len(me))}

    parse_by_condition = {}
    for cond in conditions:
        ce = [e for e in events if e["condition"] == cond]
        pf = sum(1 for e in ce if e.get("category") == "parse_failed")
        parse_by_condition[cond] = {"parse_failed": pf, "total": len(ce), "rate": _safe_rate(pf, len(ce))}

    # Reasoning availability
    reasoning_available = sum(1 for e in events if e["reasoning_correct"] is not None)
    no_reasoning = sum(1 for e in events if e.get("category") == "no_reasoning")
    classifier_failed = sum(1 for e in events if e.get("category") == "classifier_parse_failed")

    # Correlation: parse failure vs model
    # Correlation: parse failure vs LEG
    leg_events_with_parse = [e for e in events if e.get("category") == "leg" and e.get("parse_error")]
    leg_events_total = sum(1 for e in events if e.get("category") == "leg")

    return {
        "field_completeness": completeness,
        "parse_by_model": parse_by_model,
        "parse_by_condition": parse_by_condition,
        "reasoning_available": {"count": reasoning_available, "total": n, "rate": _safe_rate(reasoning_available, n)},
        "no_reasoning_count": no_reasoning,
        "classifier_failed_count": classifier_failed,
        "leg_with_parse_error": {"count": len(leg_events_with_parse), "total": leg_events_total},
    }


# ============================================================
# OUTPUT GENERATION
# ============================================================


def generate_outputs(events, global_m, case_m, family_m, deltas, trial_v, parse_a, output_dir):
    """Generate all output files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    # ── CONSOLE SUMMARY ──
    _print_console_summary(events, global_m, case_m, family_m, deltas, trial_v, parse_a)

    # ── JSON REPORT ──
    report = {
        "global_metrics": {
            "overall": global_m["overall"],
            "per_model": global_m["models"],
            "per_condition": global_m["conditions"],
            "per_model_x_condition": {
                f"{m}|{c}": v for (m, c), v in global_m["model_x_condition"].items()
            },
        },
        "condition_deltas": {
            "per_condition": deltas.get("per_condition", {}),
            "per_condition_x_model": {
                f"{c}|{m}": v for (c, m), v in deltas.get("per_condition_x_model", {}).items()
            },
        },
        "trial_variance": {
            f"{m}|{c}": v for (m, c), v in trial_v.get("per_model_condition", {}).items()
        },
        "parse_audit": parse_a,
        "family_metrics": family_m,
    }
    with open(output_dir / "analysis_summary.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    # ── CSV: per_model_metrics ──
    with open(output_dir / "per_model_metrics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "condition", "n", "pass_rate", "leg_rate", "lucky_fix_rate",
                     "disagreement_rate", "exec_given_reason", "reason_given_exec",
                     "parse_failure_rate", "reasoning_evaluated_rate"])
        for model in models:
            for cond in conditions:
                m = global_m["model_x_condition"].get((model, cond), {})
                if not m or m.get("total_samples", 0) == 0:
                    continue
                w.writerow([
                    model, cond, m["total_samples"],
                    m["pass_rate"]["rate"],
                    m["leg_true_rate"]["rate"],
                    m["lucky_fix_rate"]["rate"],
                    m["disagreement_rate"]["rate"],
                    m["exec_given_reason"],
                    m["reason_given_exec"],
                    m["parse_failure_rate"]["rate"],
                    m["reasoning_evaluated"]["rate"],
                ])

    # ── CSV: per_case_metrics ──
    with open(output_dir / "per_case_metrics.csv", "w", newline="") as f:
        w = csv.writer(f)
        header = ["case_id", "family", "difficulty", "n", "pass_rate", "leg_rate",
                   "lucky_fix_rate", "model_split"]
        for model in models:
            header.append(f"pass_{model}")
        for cond in conditions:
            header.append(f"pass_{cond}")
        w.writerow(header)

        for cid in sorted(case_m.keys()):
            cm = case_m[cid]
            row = [
                cid, cm["family"], cm["difficulty"], cm["total_samples"],
                cm["pass_rate"]["rate"],
                cm["leg_true_rate"]["rate"],
                cm["lucky_fix_rate"]["rate"],
                cm["model_split"],
            ]
            for model in models:
                row.append(cm["per_model_pass_rate"].get(model))
            for cond in conditions:
                row.append(cm["per_condition_pass_rate"].get(cond))
            w.writerow(row)

    # ── CSV: per_condition_metrics ──
    with open(output_dir / "per_condition_metrics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["condition", "model", "delta_pass", "delta_leg", "baseline_pass",
                     "condition_pass", "baseline_n", "condition_n"])
        for (cond, model), v in sorted(deltas.get("per_condition_x_model", {}).items()):
            w.writerow([cond, model, v["delta_pass"], v["delta_leg"],
                         v["baseline_pass"], v["condition_pass"],
                         v["baseline_n"], v["condition_n"]])

    # ── CSV: family_aggregates ──
    with open(output_dir / "family_aggregates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group_type", "group_name", "n", "pass_rate", "leg_rate",
                     "lucky_fix_rate", "disagreement_rate"])
        for group_type in ["by_family", "by_failure_mode", "by_difficulty"]:
            for name, m in sorted(family_m.get(group_type, {}).items()):
                w.writerow([
                    group_type.replace("by_", ""), name, m["total_samples"],
                    m["pass_rate"]["rate"],
                    m["leg_true_rate"]["rate"],
                    m["lucky_fix_rate"]["rate"],
                    m["disagreement_rate"]["rate"],
                ])

    print(f"\n  Outputs written to {output_dir}/")
    print(f"    analysis_summary.json")
    print(f"    per_model_metrics.csv")
    print(f"    per_case_metrics.csv")
    print(f"    per_condition_metrics.csv")
    print(f"    family_aggregates.csv")

    # ── OPTIONAL: plots ──
    _try_generate_plots(events, global_m, case_m, family_m, deltas, output_dir)


def _print_console_summary(events, global_m, case_m, family_m, deltas, trial_v, parse_a):
    """Print human-readable console summary."""
    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    print()
    print("=" * 90)
    print("  T3 ABLATION ANALYSIS — FORMAL AUDIT")
    print(f"  {len(events)} events, {len(models)} models, {len(conditions)} conditions")
    print("=" * 90)

    # ── SECTION 1: GLOBAL METRICS ──
    print()
    print("─" * 90)
    print("  1. GLOBAL METRICS (per model × condition)")
    print("─" * 90)
    print()
    print(f"  {'Model':<20} {'Cond':<18} {'N':>5} {'Pass%':>7} {'LEG%':>7} {'Lucky%':>7} "
          f"{'Disagr%':>8} {'P(E|R)':>7} {'P(R|E)':>7} {'Parse%':>7}")
    print(f"  {'─' * 86}")

    for model in models:
        for cond in conditions:
            m = global_m["model_x_condition"].get((model, cond), {})
            if not m or m.get("total_samples", 0) == 0:
                continue
            print(f"  {model:<20} {cond:<18} {m['total_samples']:>5} "
                  f"{_fmt_rate(m['pass_rate']['rate']):>7} "
                  f"{_fmt_rate(m['leg_true_rate']['rate']):>7} "
                  f"{_fmt_rate(m['lucky_fix_rate']['rate']):>7} "
                  f"{_fmt_rate(m['disagreement_rate']['rate']):>8} "
                  f"{_fmt_rate(m['exec_given_reason']):>7} "
                  f"{_fmt_rate(m['reason_given_exec']):>7} "
                  f"{_fmt_rate(m['parse_failure_rate']['rate']):>7}")

    # ── SECTION 2: INTERVENTION DELTAS ──
    if deltas.get("per_condition_x_model"):
        print()
        print("─" * 90)
        print("  2. INTERVENTION DELTAS (vs baseline)")
        print("─" * 90)
        print()
        print(f"  {'Model':<20} {'Condition':<18} {'ΔPass':>8} {'ΔLEG':>8} {'BL Pass':>8} {'Cond Pass':>10}")
        print(f"  {'─' * 64}")
        for (cond, model), v in sorted(deltas["per_condition_x_model"].items()):
            dp = v["delta_pass"]
            tag = "HELPS" if dp > 0.03 else ("HURTS" if dp < -0.03 else "")
            print(f"  {model:<20} {cond:<18} {dp:>+7.1%} {v['delta_leg']:>+7.1%} "
                  f"{v['baseline_pass']:>7.1%} {v['condition_pass']:>9.1%}  {tag}")

    # ── SECTION 3: TOP CASES ──
    print()
    print("─" * 90)
    print("  3. TOP CASES")
    print("─" * 90)

    # Hardest
    sorted_by_pass = sorted(case_m.items(), key=lambda x: x[1]["pass_rate"]["rate"] or 1)
    print(f"\n  Top 10 HARDEST cases:")
    print(f"  {'Case':<30} {'Pass%':>7} {'LEG%':>7} {'Lucky%':>7} {'Split':>7}")
    for cid, cm in sorted_by_pass[:10]:
        print(f"  {cid:<30} {_fmt_rate(cm['pass_rate']['rate']):>7} "
              f"{_fmt_rate(cm['leg_true_rate']['rate']):>7} "
              f"{_fmt_rate(cm['lucky_fix_rate']['rate']):>7} "
              f"{cm['model_split']:>6.1%}")

    # Highest LEG
    sorted_by_leg = sorted(case_m.items(),
                           key=lambda x: x[1]["leg_true_rate"]["rate"] or 0, reverse=True)
    print(f"\n  Top 10 HIGHEST LEG cases:")
    print(f"  {'Case':<30} {'LEG%':>7} {'Pass%':>7} {'Family':<20}")
    for cid, cm in sorted_by_leg[:10]:
        print(f"  {cid:<30} {_fmt_rate(cm['leg_true_rate']['rate']):>7} "
              f"{_fmt_rate(cm['pass_rate']['rate']):>7} {cm['family']:<20}")

    # Highest lucky fix
    sorted_by_lucky = sorted(case_m.items(),
                             key=lambda x: x[1]["lucky_fix_rate"]["rate"] or 0, reverse=True)
    print(f"\n  Top 10 HIGHEST LUCKY FIX cases:")
    print(f"  {'Case':<30} {'Lucky%':>7} {'Pass%':>7} {'Family':<20}")
    for cid, cm in sorted_by_lucky[:10]:
        lr = cm["lucky_fix_rate"]["rate"]
        if lr and lr > 0:
            print(f"  {cid:<30} {_fmt_rate(lr):>7} "
                  f"{_fmt_rate(cm['pass_rate']['rate']):>7} {cm['family']:<20}")

    # Highest model split
    sorted_by_split = sorted(case_m.items(), key=lambda x: x[1]["model_split"], reverse=True)
    print(f"\n  Top 10 MODEL-SPLIT cases:")
    print(f"  {'Case':<30} {'Split':>7}", end="")
    for model in models:
        print(f" {model[:12]:>12}", end="")
    print()
    for cid, cm in sorted_by_split[:10]:
        print(f"  {cid:<30} {cm['model_split']:>6.1%}", end="")
        for model in models:
            r = cm["per_model_pass_rate"].get(model)
            print(f" {_fmt_rate(r):>12}", end="")
        print()

    # ── SECTION 4: FAMILY ANALYSIS ──
    print()
    print("─" * 90)
    print("  4. FAMILY ANALYSIS")
    print("─" * 90)
    print()
    print(f"  {'Family':<25} {'N':>5} {'Pass%':>7} {'LEG%':>7} {'Lucky%':>7} {'Disagr%':>8}")
    print(f"  {'─' * 62}")
    for name, m in sorted(family_m.get("by_family", {}).items(),
                          key=lambda x: x[1]["pass_rate"]["rate"] or 0):
        print(f"  {name:<25} {m['total_samples']:>5} "
              f"{_fmt_rate(m['pass_rate']['rate']):>7} "
              f"{_fmt_rate(m['leg_true_rate']['rate']):>7} "
              f"{_fmt_rate(m['lucky_fix_rate']['rate']):>7} "
              f"{_fmt_rate(m['disagreement_rate']['rate']):>8}")

    # By difficulty
    print()
    print(f"  {'Difficulty':<15} {'N':>5} {'Pass%':>7} {'LEG%':>7} {'Lucky%':>7}")
    print(f"  {'─' * 40}")
    for name, m in sorted(family_m.get("by_difficulty", {}).items()):
        print(f"  {name:<15} {m['total_samples']:>5} "
              f"{_fmt_rate(m['pass_rate']['rate']):>7} "
              f"{_fmt_rate(m['leg_true_rate']['rate']):>7} "
              f"{_fmt_rate(m['lucky_fix_rate']['rate']):>7}")

    # ── SECTION 5: TRIAL CONSISTENCY ──
    print()
    print("─" * 90)
    print("  5. TRIAL CONSISTENCY")
    print("─" * 90)
    print()
    print(f"  {'Model':<20} {'Condition':<18} {'Trials':>6} {'Pass μ':>7} {'Pass σ':>7} "
          f"{'LEG μ':>7} {'LEG σ':>7}")
    print(f"  {'─' * 68}")
    for (model, cond), v in sorted(trial_v.get("per_model_condition", {}).items()):
        print(f"  {model:<20} {cond:<18} {v['trials']:>6} "
              f"{v['pass_mean']:>6.1%} {v['pass_std']:>6.1%} "
              f"{v['leg_mean']:>6.1%} {v['leg_std']:>6.1%}")

    unstable = trial_v.get("unstable_flags", [])
    if unstable:
        print(f"\n  UNSTABLE FLAGS ({len(unstable)}):")
        for flag in unstable:
            print(f"    {flag['model']}/{flag['condition']}: {flag['reason']} "
                  f"(var={flag['pass_variance']:.4f})")

    # ── SECTION 6: PARSE AUDIT ──
    print()
    print("─" * 90)
    print("  6. DATA QUALITY AUDIT")
    print("─" * 90)
    print()
    print(f"  Field completeness:")
    for field, info in sorted(parse_a["field_completeness"].items()):
        status = "OK" if info["rate"] and info["rate"] > 0.95 else "LOW"
        print(f"    {field:<25} {info['present']:>5}/{info['total']:>5} ({_fmt_rate(info['rate']):>7}) {status}")

    print(f"\n  Parse failures by model:")
    for model, info in sorted(parse_a["parse_by_model"].items()):
        print(f"    {model:<20} {info['parse_failed']:>4}/{info['total']:>5} ({_fmt_rate(info['rate']):>7})")

    print(f"\n  Reasoning availability: {parse_a['reasoning_available']['count']}/{parse_a['reasoning_available']['total']}")
    print(f"  No reasoning: {parse_a['no_reasoning_count']}")
    print(f"  Classifier failed: {parse_a['classifier_failed_count']}")

    # ── SECTION 7: DIAGNOSTIC SUMMARY ──
    print()
    print("=" * 90)
    print("  DIAGNOSTIC SUMMARY")
    print("=" * 90)
    _print_diagnostic(events, global_m, case_m, deltas, trial_v, parse_a)


def _print_diagnostic(events, global_m, case_m, deltas, trial_v, parse_a):
    """Print top insights, risks, and trustworthiness assessment."""
    models = sorted(set(e["model"] for e in events if e["model"]))
    n = len(events)

    print()
    print("  TOP INSIGHTS:")

    # 1. Best/worst model
    model_pass = {m: global_m["models"][m]["pass_rate"]["rate"] for m in models
                  if m in global_m["models"] and global_m["models"][m]["pass_rate"]["rate"] is not None}
    if model_pass:
        best = max(model_pass, key=model_pass.get)
        worst = min(model_pass, key=model_pass.get)
        print(f"    1. Best model: {best} ({model_pass[best]:.1%}), "
              f"worst: {worst} ({model_pass[worst]:.1%})")

    # 2. Intervention effect
    for cond, v in deltas.get("per_condition", {}).items():
        dp = v["delta_pass"]
        direction = "helps" if dp > 0.03 else ("hurts" if dp < -0.03 else "neutral")
        print(f"    2. {cond} intervention: {dp:+.1%} overall ({direction})")

    # 3. LEG signal
    overall_leg = global_m["overall"]["leg_true_rate"]["rate"]
    if overall_leg:
        print(f"    3. Overall LEG rate: {overall_leg:.1%} — "
              f"{'strong signal' if overall_leg > 0.1 else 'weak signal'}")

    print()
    print("  TOP RISKS:")

    # 1. Reasoning reliability
    rc_rate = parse_a["reasoning_available"]["rate"]
    if rc_rate and rc_rate < 0.9:
        print(f"    1. Reasoning available for only {rc_rate:.1%} of events — metrics are partial")
    else:
        # Check invariant_identified WRONG rate as proxy for classifier fairness
        print(f"    1. WARNING: reasoning_correct may be distorted by classifier penalizing "
              f"missing fields (invariant_identified) in non-baseline conditions")

    # 2. Parse failures
    total_parse = sum(v["parse_failed"] for v in parse_a["parse_by_model"].values())
    if total_parse > 0:
        print(f"    2. {total_parse} parse failures across all models — "
              f"these are scored as failures, not excluded")

    # 3. Trial variance
    unstable = trial_v.get("unstable_flags", [])
    if unstable:
        print(f"    3. {len(unstable)} model/condition pairs have HIGH variance across trials")
    else:
        print(f"    3. Trial variance is low — results are stable")

    print()
    # Trustworthiness
    issues = 0
    if rc_rate and rc_rate < 0.8:
        issues += 1
    if total_parse / n > 0.05:
        issues += 1
    if len(unstable) > 2:
        issues += 1

    if issues == 0:
        print("  ASSESSMENT: Results are TRUSTWORTHY for research use.")
        print("  Execution metrics (pass_rate) are reliable.")
        print("  Reasoning metrics should be interpreted with caution due to classifier limitations.")
    elif issues == 1:
        print("  ASSESSMENT: Results are MOSTLY TRUSTWORTHY.")
        print("  Execution metrics are reliable. One data quality concern flagged above.")
    else:
        print("  ASSESSMENT: Results have SIGNIFICANT DATA QUALITY ISSUES.")
        print("  Execution metrics may be reliable but reasoning metrics are questionable.")


def _fmt_rate(r):
    if r is None:
        return "—"
    return f"{r:.1%}"


def _try_generate_plots(events, global_m, case_m, family_m, deltas, output_dir):
    """Generate plots if matplotlib is available."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not available — skipping plots)")
        return

    models = sorted(set(e["model"] for e in events if e["model"]))
    conditions = sorted(set(e["condition"] for e in events if e["condition"]))

    # Plot 1: Pass rate by model × condition
    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(models))
    width = 0.8 / len(conditions)
    for i, cond in enumerate(conditions):
        rates = []
        for model in models:
            m = global_m["model_x_condition"].get((model, cond), {})
            r = m.get("pass_rate", {}).get("rate", 0) or 0
            rates.append(r)
        bars = ax.bar([xi + i * width for xi in x], rates, width, label=cond)
    ax.set_ylabel("Pass Rate")
    ax.set_title("Pass Rate by Model × Condition")
    ax.set_xticks([xi + width * (len(conditions) - 1) / 2 for xi in x])
    ax.set_xticklabels(models, rotation=15, ha="right")
    ax.legend()
    ax.set_ylim(0, 1)
    plt.tight_layout()
    plt.savefig(output_dir / "pass_rate_by_model_condition.png", dpi=150)
    plt.close()

    # Plot 2: LEG rate by model × condition
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, cond in enumerate(conditions):
        rates = []
        for model in models:
            m = global_m["model_x_condition"].get((model, cond), {})
            r = m.get("leg_true_rate", {}).get("rate", 0) or 0
            rates.append(r)
        ax.bar([xi + i * width for xi in x], rates, width, label=cond)
    ax.set_ylabel("LEG Rate")
    ax.set_title("LEG Rate by Model × Condition")
    ax.set_xticks([xi + width * (len(conditions) - 1) / 2 for xi in x])
    ax.set_xticklabels(models, rotation=15, ha="right")
    ax.legend()
    ax.set_ylim(0, 0.5)
    plt.tight_layout()
    plt.savefig(output_dir / "leg_rate_by_model_condition.png", dpi=150)
    plt.close()

    # Plot 3: Family pass rates
    fam_data = family_m.get("by_family", {})
    if fam_data:
        families = sorted(fam_data.keys(), key=lambda f: fam_data[f]["pass_rate"]["rate"] or 0)
        rates = [fam_data[f]["pass_rate"]["rate"] or 0 for f in families]
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.barh(range(len(families)), rates)
        ax.set_yticks(range(len(families)))
        ax.set_yticklabels(families, fontsize=8)
        ax.set_xlabel("Pass Rate")
        ax.set_title("Pass Rate by Family")
        ax.set_xlim(0, 1)
        plt.tight_layout()
        plt.savefig(output_dir / "pass_rate_by_family.png", dpi=150)
        plt.close()

    # Plot 4: Condition x Family heatmap
    cxf = deltas.get("condition_x_family", {})
    if cxf:
        conds_nbl = [c for c in conditions if c != "baseline"]
        families_all = sorted(set(f for (c, f) in cxf.keys()))
        if conds_nbl and families_all:
            matrix = []
            for fam in families_all:
                row = []
                for cond in conds_nbl:
                    v = cxf.get((cond, fam), {})
                    row.append(v.get("delta_pass", 0))
                matrix.append(row)

            fig, ax = plt.subplots(figsize=(8, max(6, len(families_all) * 0.3)))
            import numpy as np
            data = np.array(matrix)
            im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-0.5, vmax=0.5)
            ax.set_xticks(range(len(conds_nbl)))
            ax.set_xticklabels(conds_nbl, rotation=45, ha="right")
            ax.set_yticks(range(len(families_all)))
            ax.set_yticklabels(families_all, fontsize=7)
            ax.set_title("ΔPass Rate: Condition vs Family")
            plt.colorbar(im, ax=ax, label="ΔPass")
            plt.tight_layout()
            plt.savefig(output_dir / "condition_x_family_heatmap.png", dpi=150)
            plt.close()

    print(f"  Plots saved to {output_dir}/")


# ============================================================
# MAIN
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="T3 Ablation Analysis")
    parser.add_argument("run_dirs", nargs="+", help="One or more ablation run directories")
    parser.add_argument("--output-dir", default="analysis_output", help="Output directory")
    args = parser.parse_args()

    run_dirs = [Path(d) for d in args.run_dirs]
    print(f"  Loading runs from: {[str(d) for d in run_dirs]}")

    events = load_runs(run_dirs)
    if not events:
        print("  ERROR: no events loaded. Exiting.", file=sys.stderr)
        sys.exit(1)

    events = normalize_events(events)
    print(f"  Normalized {len(events)} events")

    global_m = compute_global_metrics(events)
    case_m = compute_case_metrics(events)
    family_m = compute_family_metrics(events)
    deltas = compute_condition_deltas(events)
    trial_v = compute_trial_variance(events)
    parse_a = compute_parse_audit(events)

    generate_outputs(events, global_m, case_m, family_m, deltas, trial_v, parse_a, args.output_dir)


if __name__ == "__main__":
    main()
