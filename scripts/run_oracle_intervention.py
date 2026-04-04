"""Full Oracle Intervention Ablation — Main Entrypoint.

Usage:
    .venv/bin/python scripts/run_oracle_intervention.py \
        --stage all --config config_storage/v2_canonical_smoke.yaml \
        --logs logs/v2_targeted_50trial_canonical ... \
        --workers-openai 200 --workers-anthropic 50 \
        --output-dir artifacts/audits/oracle_intervention
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from oracle_extract import run_stage_0
from oracle_label import run_stage_1, load_existing_labels, _event_key
from oracle_metrics import (
    compute_pooled_metrics, compute_intervention_deltas,
    compute_test_A, compute_test_B, compute_test_C, compute_test_D,
    compute_reasoning_stability, compute_unjudgable_shift,
    compute_reconstruction_control, compute_model_regimes,
    compute_exclusion_sensitivity,
)
from oracle_report import format_report


def load_matched_events(output_dir):
    """Load matched_events.jsonl."""
    p = Path(output_dir) / "matched_events.jsonl"
    return [json.loads(l) for l in open(p)]


def load_cases(project_root):
    """Load cases_v2.json with code_files_contents."""
    cases = json.loads(Path("cases_v2.json").read_text())
    by_id = {}
    for c in cases:
        c["code_files_contents"] = {
            p: Path(p).read_text()
            for p in c["code_files"] if Path(p).exists()}
        by_id[c["id"]] = c
    return by_id


def join_results(labels, events):
    """Join oracle labels with execution case_data."""
    label_map = {}
    for k, v in labels.items():
        label_map[k] = v

    joined = []
    for e in events:
        k = _event_key(e)
        lbl = label_map.get(k)
        if not lbl:
            continue
        row = dict(e)
        row["reasoning_truth"] = lbl["reasoning_truth"]
        row["justification"] = lbl.get("justification", "")
        row["parse_error"] = lbl.get("parse_error")
        row["prompt_hash"] = lbl.get("prompt_hash", "")
        ep = row["execution_pass"]
        rt = row["reasoning_truth"]
        row["leg_strict"] = (rt == "CORRECT" and not ep)
        row["leg_soft"] = (
            rt in ("CORRECT", "PARTIAL") and not ep)
        row["lucky_fix"] = (rt == "WRONG" and ep)
        joined.append(row)
    return joined


def run_reliability(events, cases_by_id, config, output_dir):
    """Dual-prompt reliability check on 50 random events."""
    from oracle_label import _eval_single, is_unjudgable
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from core.registry.prompt_registry import load_prompt_registry
    try:
        load_prompt_registry()
    except RuntimeError:
        pass
    print("Reliability check: 50 samples × 3 calls (parallel)",
          flush=True)

    # Filter to judgable events
    judgable = [
        e for e in events
        if not is_unjudgable(
            e.get("root_cause", ""), e.get("fix_strategy", ""))]
    sample = random.sample(judgable, min(50, len(judgable)))

    # Submit all 150 calls in parallel
    tasks = []  # (index, variant, event)
    for i, e in enumerate(sample):
        tasks.append((i, "a", e))
        tasks.append((i, "a2", e))
        tasks.append((i, "b", e))

    call_results = {}  # (index, variant) -> label
    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = {}
        for idx, var, e in tasks:
            pv = "b" if var == "b" else "a"
            fut = pool.submit(
                _eval_single, e, cases_by_id, config, pv)
            futures[fut] = (idx, var)
        for fut in as_completed(futures):
            idx, var = futures[fut]
            try:
                r = fut.result()
                call_results[(idx, var)] = r["reasoning_truth"]
            except Exception:
                call_results[(idx, var)] = "UNJUDGABLE"

    results = []
    for i, e in enumerate(sample):
        results.append({
            "case_id": e["case_id"], "model": e["model"],
            "label_a": call_results.get((i, "a"), "?"),
            "label_a2": call_results.get((i, "a2"), "?"),
            "label_b": call_results.get((i, "b"), "?"),
        })
    print(f"  All 150 reliability calls complete", flush=True)

    # Compute agreement
    n = len(results)
    agree_aa2 = sum(
        1 for r in results if r["label_a"] == r["label_a2"]) / n
    agree_ab = sum(
        1 for r in results if r["label_a"] == r["label_b"]) / n

    # Cohen's kappa (A vs B)
    labels = ["CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"]
    from collections import Counter
    a_counts = Counter(r["label_a"] for r in results)
    b_counts = Counter(r["label_b"] for r in results)
    pe = sum(
        (a_counts.get(l, 0) / n) * (b_counts.get(l, 0) / n)
        for l in labels)
    kappa = (agree_ab - pe) / (1 - pe) if pe < 1 else 1.0

    reliability = {
        "n": n,
        "agree_a_a2": f"{agree_aa2:.1%}",
        "agree_a_b": f"{agree_ab:.1%}",
        "kappa_a_b": f"{kappa:.3f}",
        "kappa_numeric": kappa,
        "samples": results,
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "reliability_check.json").write_text(
        json.dumps(reliability, indent=2))

    print(f"  Agreement A-A2: {agree_aa2:.1%}", flush=True)
    print(f"  Agreement A-B:  {agree_ab:.1%}", flush=True)
    print(f"  Kappa A-B:      {kappa:.3f}", flush=True)

    if kappa < 0.5:
        raise RuntimeError(
            f"RELIABILITY FAILURE: kappa={kappa:.3f} < 0.5. "
            f"STOPPING. Revise evaluator prompt.")

    return reliability


def run_stage_3(output_dir, reliability=None):
    """Compute all metrics and write report."""
    print("Stage 3: Analysis", flush=True)
    joined_path = Path(output_dir) / "joined_results.jsonl"
    rows = [json.loads(l) for l in open(joined_path)]
    print(f"  Loaded {len(rows)} joined rows", flush=True)

    pooled = compute_pooled_metrics(rows)
    deltas = compute_intervention_deltas(rows)
    tests_a = compute_test_A(rows)
    tests_b = compute_test_B(rows)
    tests_c = compute_test_C(rows)
    tests_d = compute_test_D(rows)
    stability = compute_reasoning_stability(rows)
    unjdg = compute_unjudgable_shift(rows)
    recon = compute_reconstruction_control(rows)
    regimes = compute_model_regimes(rows)
    exclusion = compute_exclusion_sensitivity(rows)

    tables = {
        "pooled": pooled, "deltas": deltas,
        "tests_a": tests_a, "tests_b": tests_b,
        "tests_c": tests_c, "tests_d": tests_d,
        "stability": stability, "unjudgable_shift": unjdg,
        "reconstruction_control": recon,
        "model_regimes": regimes, "exclusion": exclusion,
    }

    out = Path(output_dir)
    (out / "tables.json").write_text(
        json.dumps(tables, indent=2, default=str))

    report = format_report(
        pooled, deltas, tests_a, tests_b, tests_c, tests_d,
        stability, unjdg, recon, regimes, exclusion, pooled,
        len(rows), reliability)
    (out / "analysis.md").write_text(report)
    print(f"  Wrote analysis.md and tables.json", flush=True)

    # Print summary
    for cond in ["baseline_v2", "leg_reduction_v2",
                 "leg_reduction_lean_v2"]:
        m = pooled.get(cond, {})
        print(f"  {cond}: correct={m.get('correct','?'):.1%} "
              f"pass={m.get('pass','?'):.1%} "
              f"P|C={m.get('pass_given_C','?'):.1%} "
              f"LEG={m.get('strict_leg','?'):.1%}", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description="Full Oracle Intervention Ablation")
    ap.add_argument("--config", required=True)
    ap.add_argument("--logs", nargs="+", default=[])
    ap.add_argument("--stage", default="all",
                    choices=["0", "1", "reliability", "2", "3", "all"])
    ap.add_argument("--workers-openai", type=int, default=200)
    ap.add_argument("--workers-anthropic", type=int, default=50)
    ap.add_argument("--output-dir",
                    default="artifacts/audits/oracle_intervention")
    args = ap.parse_args()

    from core.config.experiment_config import load_config, get_config
    load_config(args.config)
    config = get_config()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases_by_id = load_cases(".")

    stages = (["0", "reliability", "1", "2", "3"]
              if args.stage == "all" else [args.stage])

    reliability = None

    for stage in stages:
        if stage == "0":
            run_stage_0(args.logs, args.output_dir)

        elif stage == "reliability":
            events = load_matched_events(args.output_dir)
            reliability = run_reliability(
                events, cases_by_id, config, args.output_dir)

        elif stage == "1":
            events = load_matched_events(args.output_dir)

            # Split by provider for different parallelism
            openai_events = [
                e for e in events
                if not e["model"].startswith("claude")]
            anthropic_events = [
                e for e in events
                if e["model"].startswith("claude")]

            print(f"Stage 1: {len(openai_events)} OpenAI events "
                  f"({args.workers_openai} workers), "
                  f"{len(anthropic_events)} Anthropic events "
                  f"({args.workers_anthropic} workers)",
                  flush=True)

            # Need prompt registry for assembly
            from core.registry.prompt_registry import load_prompt_registry
            try:
                load_prompt_registry()
            except RuntimeError:
                pass  # already loaded

            if openai_events:
                run_stage_1(
                    openai_events, cases_by_id, config,
                    args.output_dir, args.workers_openai)
            if anthropic_events:
                run_stage_1(
                    anthropic_events, cases_by_id, config,
                    args.output_dir, args.workers_anthropic)

        elif stage == "2":
            events = load_matched_events(args.output_dir)
            labels = load_existing_labels(args.output_dir)
            joined = join_results(labels, events)
            jpath = out / "joined_results.jsonl"
            with open(jpath, "w") as f:
                for r in joined:
                    f.write(json.dumps(r) + "\n")
            print(f"Stage 2: Joined {len(joined)} rows → {jpath}",
                  flush=True)
            unlabeled = len(events) - len(joined)
            if unlabeled > 0:
                print(f"  WARNING: {unlabeled} events have no "
                      f"oracle label", flush=True)

        elif stage == "3":
            # Load reliability if exists
            rpath = out / "reliability_check.json"
            if rpath.exists():
                reliability = json.loads(rpath.read_text())
            run_stage_3(args.output_dir, reliability)


if __name__ == "__main__":
    main()
