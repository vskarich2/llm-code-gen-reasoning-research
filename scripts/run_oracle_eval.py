"""Oracle-grounded reasoning evaluator — post-hoc TRUE LEG computation.

Compares model reasoning against ground-truth bug mechanisms.
Parallelized via subprocess workers (no threads).

Usage:
    .venv/bin/python scripts/run_oracle_eval.py \
        --config config_storage/v2_canonical_smoke.yaml \
        --logs logs/v2_targeted_50trial_canonical \
        --sample 500 --workers 4
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
VALID_LABELS = {"CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"}


def load_events(log_dirs):
    """Extract case.end events with reasoning fields."""
    rows = []
    for ld in log_dirs:
        merged = Path(ld) / "merged_events.jsonl"
        if not merged.exists():
            print(f"  WARN: {merged} not found", flush=True)
            continue
        for line in open(merged):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "case.end":
                continue
            p = ev.get("payload", {})
            art = p.get("v2_artifact", {})
            rows.append({
                "case_id": ev.get("case_id"),
                "model": ev.get("model"),
                "condition": ev.get("condition"),
                "trial": ev.get("trial"),
                "root_cause": art.get("raw_root_cause", ""),
                "fix_strategy": art.get("raw_fix_strategy", ""),
                "parse_status": art.get("parse_status", ""),
                "execution_pass": p.get("pass", False),
                "recon_status": p.get("reconstruction_status"),
                "old_mc": p.get("mechanism_correct"),
            })
    return rows


def stratified_sample(rows, n):
    """Sample n rows, stratified by model × condition × pass/fail."""
    buckets = defaultdict(list)
    for r in rows:
        key = (r["model"], r["condition"], r["execution_pass"])
        buckets[key].append(r)

    sampled = []
    per_bucket = max(1, n // len(buckets)) if buckets else 0
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        take = min(per_bucket, len(bucket))
        sampled.extend(bucket[:take])

    # Fill remainder round-robin
    remaining = n - len(sampled)
    if remaining > 0:
        pool = [r for r in rows if r not in sampled]
        sampled.extend(pool[:remaining])

    return sampled[:n]


def evaluate_batch(batch, cases_by_id, config_path):
    """Evaluate a batch of rows. Called in worker subprocess."""
    from core.config.experiment_config import load_config, get_config
    load_config(config_path)
    config = get_config()

    from core.evaluation.oracle_eval.reasoning_truth import (
        build_oracle_spec, load_buggy_code, render_prompt,
        parse_response, is_unjudgable)
    from core.pipeline import call_model

    results = []
    for i, row in enumerate(batch):
        case = cases_by_id.get(row["case_id"])
        if not case:
            results.append(_make_result(row, "UNJUDGABLE", "",
                                        "case_not_found"))
            continue

        rc = row["root_cause"]
        fs = row["fix_strategy"]

        if is_unjudgable(rc, fs):
            results.append(_make_result(row, "UNJUDGABLE", "",
                                        "pre_filter"))
            continue

        oracle = build_oracle_spec(case)
        buggy_code = load_buggy_code(case, PROJECT_ROOT)
        prompt = render_prompt(oracle, rc, fs, buggy_code)

        t0 = time.monotonic()
        try:
            cr = call_model(
                prompt, model=config.models.evaluator.name,
                raw=True, logger=None, phase="oracle_eval")
            raw_resp = cr.response
        except Exception as e:
            results.append(_make_result(
                row, "UNJUDGABLE", "", f"call_error:{e!s:.80}"))
            continue
        elapsed = int((time.monotonic() - t0) * 1000)

        label, justification, err = parse_response(raw_resp)
        results.append(_make_result(
            row, label, justification, err,
            raw_resp=raw_resp, latency_ms=elapsed,
            prompt_hash=hashlib.sha256(
                prompt.encode()).hexdigest()[:16]))

        status = "FN!" if (label == "CORRECT"
                           and not row["execution_pass"]) else ""
        print(f"  [{i+1:4d}/{len(batch)}] {row['case_id'][:22]:22s} "
              f"{row['model'][:18]:18s} → {label:10s} {status}",
              flush=True)

    return results


def _make_result(row, label, justification, error,
                 raw_resp="", latency_ms=0, prompt_hash=""):
    """Build a result dict."""
    ep = row["execution_pass"]
    return {
        "case_id": row["case_id"],
        "model": row["model"],
        "condition": row["condition"],
        "trial": row["trial"],
        "reasoning_truth": label,
        "justification": justification,
        "execution_pass": ep,
        "leg_strict": label == "CORRECT" and not ep,
        "leg_soft": label in ("CORRECT", "PARTIAL") and not ep,
        "lucky_fix": label == "WRONG" and ep,
        "old_mc": row["old_mc"],
        "parse_error": error,
        "response_raw": raw_resp,
        "latency_ms": latency_ms,
        "prompt_hash": prompt_hash,
    }


def run_parallel(rows, cases_by_id, config_path, n_workers):
    """Split rows across n_workers subprocesses."""
    if n_workers <= 1:
        return evaluate_batch(rows, cases_by_id, config_path)

    # Serialize work items
    chunks = [[] for _ in range(n_workers)]
    for i, row in enumerate(rows):
        chunks[i % n_workers].append(row)

    # Write chunks + cases to temp files
    cases_file = Path(tempfile.mktemp(suffix=".json", prefix="orc_cases_"))
    cases_file.write_text(json.dumps(
        {cid: c for cid, c in cases_by_id.items()},
        default=str))

    chunk_files = []
    for ci, chunk in enumerate(chunks):
        cf = Path(tempfile.mktemp(
            suffix=".json", prefix=f"orc_chunk{ci}_"))
        cf.write_text(json.dumps(chunk))
        chunk_files.append(cf)

    # Launch workers
    procs = []
    result_files = []
    for ci, cf in enumerate(chunk_files):
        rf = Path(tempfile.mktemp(
            suffix=".json", prefix=f"orc_result{ci}_"))
        result_files.append(rf)
        cmd = [
            sys.executable, __file__,
            "--worker-mode",
            "--chunk-file", str(cf),
            "--cases-file", str(cases_file),
            "--result-file", str(rf),
            "--config", config_path,
        ]
        print(f"  Launching worker {ci} ({len(chunks[ci])} items)",
              flush=True)
        procs.append(subprocess.Popen(
            cmd, stdout=sys.stdout, stderr=sys.stderr))

    # Wait for all
    for p in procs:
        p.wait()

    # Collect results
    all_results = []
    for rf in result_files:
        if rf.exists():
            all_results.extend(json.loads(rf.read_text()))
            rf.unlink()

    # Cleanup
    cases_file.unlink(missing_ok=True)
    for cf in chunk_files:
        cf.unlink(missing_ok=True)

    return all_results


def worker_main(args):
    """Worker subprocess entry point."""
    chunk = json.loads(Path(args.chunk_file).read_text())
    cases_raw = json.loads(Path(args.cases_file).read_text())

    # Rebuild code_files_contents for each case
    for cid, case in cases_raw.items():
        case["code_files_contents"] = {
            p: Path(p).read_text()
            for p in case.get("code_files", [])
            if Path(p).exists()
        }

    results = evaluate_batch(chunk, cases_raw, args.config)
    Path(args.result_file).write_text(json.dumps(results))


def compute_metrics(results):
    """Compute all metrics."""
    valid = [r for r in results if r["reasoning_truth"] != "UNJUDGABLE"]
    n = len(valid)
    if n == 0:
        return {"total": len(results), "evaluated": 0, "coverage": 0,
                "label_dist": {}, "unjudgable": len(results)}

    labels = Counter(r["reasoning_truth"] for r in results)
    m = {
        "total": len(results),
        "evaluated": n,
        "unjudgable": labels.get("UNJUDGABLE", 0),
        "coverage": n / len(results) if results else 0,
        "label_dist": dict(labels),
    }

    correct = sum(1 for r in valid if r["reasoning_truth"] == "CORRECT")
    m["correct_rate"] = correct / n
    m["partial_rate"] = sum(
        1 for r in valid if r["reasoning_truth"] == "PARTIAL") / n
    m["wrong_rate"] = sum(
        1 for r in valid if r["reasoning_truth"] == "WRONG") / n

    m["leg_strict"] = sum(1 for r in valid if r["leg_strict"]) / n
    m["leg_soft"] = sum(1 for r in valid if r["leg_soft"]) / n
    m["lucky_fix"] = sum(1 for r in valid if r["lucky_fix"]) / n

    old_mc_true = sum(
        1 for r in valid if r["old_mc"] is True) / n if n else 0
    m["old_mc_true_rate"] = old_mc_true
    m["calibration_delta"] = old_mc_true - m["correct_rate"]

    # Per-model
    by_model = defaultdict(list)
    for r in valid:
        by_model[r["model"]].append(r)
    m["per_model"] = {}
    for model, mrs in sorted(by_model.items()):
        mn = len(mrs)
        mc = sum(1 for r in mrs if r["reasoning_truth"] == "CORRECT")
        m["per_model"][model] = {
            "n": mn,
            "correct_rate": mc / mn,
            "leg_strict": sum(1 for r in mrs if r["leg_strict"]) / mn,
            "lucky_fix": sum(1 for r in mrs if r["lucky_fix"]) / mn,
        }

    return m


def format_report(results, metrics):
    """Format markdown analysis."""
    L = ["# Oracle Reasoning Evaluator — Stage 1 Results", "",
         f"**Date**: {datetime.now().isoformat()[:10]}",
         f"**Total samples**: {metrics.get('total', 0)}",
         f"**Evaluated**: {metrics.get('evaluated', 0)}",
         f"**Coverage**: {metrics.get('coverage', 0):.1%}", ""]

    L += ["## 1. Label Distribution", "",
          "| Label | Count | Rate |",
          "|-------|-------|------|"]
    for label in ["CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"]:
        c = metrics.get("label_dist", {}).get(label, 0)
        r = c / metrics["total"] if metrics["total"] else 0
        L.append(f"| {label} | {c} | {r:.1%} |")

    L += ["", "## 2. TRUE LEG Metrics", "",
          f"- **Strict LEG**: {metrics.get('leg_strict', 0):.1%}",
          f"- **Soft LEG**: {metrics.get('leg_soft', 0):.1%}",
          f"- **Lucky fix**: {metrics.get('lucky_fix', 0):.1%}", "",
          "## 3. Calibration", "",
          f"- Old mc=True rate: {metrics.get('old_mc_true_rate', 0):.1%}",
          f"- New CORRECT rate: {metrics.get('correct_rate', 0):.1%}",
          f"- **Delta**: {metrics.get('calibration_delta', 0):.1%}", ""]

    L += ["## 4. Per-Model Breakdown", "",
          "| Model | N | CORRECT | LEG_strict | Lucky |",
          "|-------|---|---------|------------|-------|"]
    for model, ms in sorted(metrics.get("per_model", {}).items()):
        L.append(f"| {model[:25]} | {ms['n']} | "
                 f"{ms['correct_rate']:.1%} | "
                 f"{ms['leg_strict']:.1%} | "
                 f"{ms['lucky_fix']:.1%} |")

    L += ["", "## 5. Sample Results", "",
          "| Case | Model | Cond | Truth | Pass | LEG? | Justification |",
          "|------|-------|------|-------|------|------|---------------|"]
    for r in results[:50]:
        leg = "LEG" if r["leg_strict"] else ""
        lf = "LUCKY" if r["lucky_fix"] else ""
        tag = leg or lf or ""
        j = r["justification"][:60].replace("|", "/")
        L.append(f"| {r['case_id'][:18]} | {r['model'][:15]} | "
                 f"{r['condition'][:8]} | {r['reasoning_truth']} | "
                 f"{'P' if r['execution_pass'] else 'F'} | "
                 f"{tag} | {j} |")

    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="Oracle-grounded reasoning evaluator")
    ap.add_argument("--config", required=True)
    ap.add_argument("--logs", nargs="+", default=[])
    ap.add_argument("--sample", type=int, default=0,
                    help="0 = all events")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--output-dir", default="artifacts/audits/oracle_eval")
    # Worker mode (internal)
    ap.add_argument("--worker-mode", action="store_true")
    ap.add_argument("--chunk-file", default="")
    ap.add_argument("--cases-file", default="")
    ap.add_argument("--result-file", default="")
    args = ap.parse_args()

    if args.worker_mode:
        worker_main(args)
        return

    if not args.logs:
        ap.error("--logs is required in non-worker mode")

    print("Oracle Reasoning Evaluator — Stage 1", flush=True)
    print(f"Logs: {args.logs}", flush=True)

    # Load events
    rows = load_events(args.logs)
    print(f"Loaded {len(rows)} case.end events", flush=True)

    # Sample
    if args.sample > 0 and args.sample < len(rows):
        rows = stratified_sample(rows, args.sample)
        print(f"Sampled {len(rows)} events (stratified)", flush=True)

    # Load cases
    cases = json.loads(Path("cases_v2.json").read_text())
    cases_by_id = {c["id"]: c for c in cases}
    for c in cases:
        c["code_files_contents"] = {
            p: Path(p).read_text()
            for p in c["code_files"] if Path(p).exists()}

    # Run
    print(f"Running with {args.workers} workers...", flush=True)
    results = run_parallel(
        rows, cases_by_id, args.config, args.workers)

    # Metrics
    metrics = compute_metrics(results)

    # Output
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items() if k != "response_raw"}
            for r in results]
    (out / "results.json").write_text(json.dumps(slim, indent=2))
    (out / "results_full.json").write_text(json.dumps(results, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    report = format_report(results, metrics)
    (out / "analysis.md").write_text(report)

    print(f"\nOutput: {out}/", flush=True)
    print(f"  CORRECT rate: {metrics.get('correct_rate', 0):.1%} "
          f"(old mc=True: {metrics.get('old_mc_true_rate', 0):.1%})",
          flush=True)
    print(f"  Strict LEG:   {metrics.get('leg_strict', 0):.1%}",
          flush=True)
    print(f"  Lucky fix:    {metrics.get('lucky_fix', 0):.1%}",
          flush=True)


if __name__ == "__main__":
    main()
