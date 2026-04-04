"""Run classifier adversarial probes — calibrate false negative rate.

Usage:
    .venv/bin/python scripts/run_classifier_probes.py --config config_storage/v2_canonical_smoke.yaml
    .venv/bin/python scripts/run_classifier_probes.py --config config_storage/v2_canonical_smoke.yaml --trials 5
"""

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DIMS = ["mechanism_identified", "commitments_extracted",
        "commitments_satisfied", "reasoning_code_alignment"]


def wilson_ci(k, n, z=1.96):
    """Wilson score 95% CI for proportion k/n."""
    if n == 0:
        return 0.0, 0.0, 1.0
    p = k / n
    d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d
    m = z * (p * (1 - p) / n + z ** 2 / (4 * n ** 2)) ** 0.5 / d
    return max(0, c - m), c, min(1, c + m)


def build_artifact(root_cause, fix_strategy):
    """Build NormalizedReasoningArtifactV2 for a probe."""
    from core.evaluation.reasoning_v2 import NormalizedReasoningArtifactV2
    return NormalizedReasoningArtifactV2(
        schema_variant="probe", parse_status="success",
        validation_status="valid",
        normalized_root_cause=root_cause,
        normalized_fix_strategy=fix_strategy,
        raw_root_cause=root_cause,
        raw_fix_strategy=fix_strategy,
        commitments_source="none")


def run_trial(probe, case, config):
    """Run single classifier call. Returns result dict."""
    from core.evaluation.evaluator_v2 import (
        build_classifier_v2_vars, parse_classifier_v2_output)
    from core.pipeline import build as asm_build
    from core.pipeline import call_model

    artifact = build_artifact(probe["root_cause"], probe["fix_strategy"])
    bld = build_classifier_v2_vars(artifact, case, probe["code"], config)
    if bld is None or bld[0] is None:
        return {"error": f"classifier vars skipped: {bld}"}

    rendered = asm_build(["classify_reasoning_v2"], bld[0])
    prompt = rendered.final_prompt
    t0 = time.monotonic()
    cr = call_model(prompt, model=config.models.evaluator.name,
                    raw=True, logger=None, phase="classification")
    elapsed = int((time.monotonic() - t0) * 1000)
    parsed = parse_classifier_v2_output(cr.response)

    return {
        "mechanism_identified": parsed.mechanism_identified,
        "commitments_extracted": parsed.commitments_extracted,
        "commitments_satisfied": parsed.commitments_satisfied,
        "reasoning_code_alignment": parsed.reasoning_code_alignment,
        "confidence": parsed.confidence,
        "judgment": parsed.judgment,
        "parse_error": parsed.parse_error,
        "response_raw": cr.response,
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "prompt_length": len(prompt),
        "latency_ms": elapsed,
    }


def resolve_probes(case_by_id):
    """Load all probe definitions."""
    from classifier_probe_defs import (
        get_synthetic_probes, get_type_f_probes, get_type_g_probes)
    return (get_synthetic_probes(case_by_id)
            + get_type_f_probes()
            + get_type_g_probes(case_by_id))


def compute_metrics(results):
    """Compute FN rates, per-dim accuracy, calibration."""
    adv = [r for r in results if r["probe_type"] in "ABCE"]
    real = [r for r in results
            if r["probe_type"] == "F" and r["expected"] == "not_correct"]
    leak = [r for r in results if r["probe_type"] == "G"]
    ctrl = [r for r in results if r["expected"] == "correct"]
    neg = adv + real + leak

    def fn(t):
        c = sum(1 for r in t if r["mechanism_identified"] == "CORRECT")
        lo, _, hi = wilson_ci(c, len(t))
        return {"fn": c, "n": len(t), "rate": c / len(t) if t else 0,
                "ci_lo": lo, "ci_hi": hi}

    m = {"fn_adversarial": fn(adv), "fn_realistic": fn(real),
         "fn_leakage": fn(leak)}

    tp = sum(1 for r in ctrl if r["mechanism_identified"] == "CORRECT")
    m["tp_control"] = {"tp": tp, "n": len(ctrl),
                       "rate": tp / len(ctrl) if ctrl else 0}

    for d in DIMS:
        det = sum(1 for r in neg if r.get(d) != "CORRECT")
        m[f"detect_{d}"] = det / len(neg) if neg else 0

    sfn = sum(1 for r in neg
              if all(r.get(d) == "CORRECT" for d in DIMS))
    m["strict_fn"] = sfn / len(neg) if neg else 0
    ad = sum(1 for r in neg
             if any(r.get(d) != "CORRECT" for d in DIMS))
    m["any_detect"] = ad / len(neg) if neg else 0

    hfn = sum(1 for r in neg if r.get("confidence") == "HIGH"
              and r.get("mechanism_identified") == "CORRECT")
    ha = sum(1 for r in neg if r.get("confidence") == "HIGH")
    m["overconfidence"] = hfn / ha if ha else 0
    return m


def format_analysis(results, metrics):
    """Format analysis as markdown."""
    L = ["# Classifier Adversarial Probe Results", "",
         f"**Date**: {datetime.now().isoformat()[:10]}",
         f"**Total trials**: {len(results)}", "",
         "## 1. False Negative Rates", "",
         "| Category | FN | N | Rate | 95% CI |",
         "|----------|-----|---|------|--------|"]
    for cat in ["adversarial", "realistic", "leakage"]:
        s = metrics[f"fn_{cat}"]
        L.append(f"| {cat} | {s['fn']} | {s['n']} | "
                 f"{s['rate']:.1%} | [{s['ci_lo']:.1%}, {s['ci_hi']:.1%}] |")

    tp = metrics["tp_control"]
    L += ["", f"**Control TP**: {tp['rate']:.1%} ({tp['tp']}/{tp['n']})",
          "", "## 2. Per-Dimension Detection (wrong probes)", "",
          "| Dimension | Detection Rate |",
          "|-----------|---------------|"]
    for d in DIMS:
        L.append(f"| {d} | {metrics[f'detect_{d}']:.1%} |")

    L += ["", f"**Strict FN (all 4 CORRECT)**: {metrics['strict_fn']:.1%}",
          f"**Any-dim detection**: {metrics['any_detect']:.1%}", "",
          "## 3. Confidence Calibration", "",
          f"**Overconfidence (HIGH on FN)**: {metrics['overconfidence']:.1%}",
          "", "## 4. Per-Probe Results", "",
          "| Probe | Type | Case | Expected | Modal | Cons | FN? |",
          "|-------|------|------|----------|-------|------|-----|"]

    for pid in sorted(set(r["probe_id"] for r in results)):
        tr = [r for r in results if r["probe_id"] == pid]
        mc = Counter(r.get("mechanism_identified") for r in tr)
        modal = mc.most_common(1)[0][0] if mc else "?"
        cons = mc.most_common(1)[0][1] / len(tr) if tr else 0
        exp = tr[0]["expected"]
        fn = "YES" if modal == "CORRECT" and exp != "correct" else ""
        L.append(f"| {pid} | {tr[0]['probe_type']} | "
                 f"{tr[0]['case_id'][:22]} | {exp} | {modal} | "
                 f"{cons:.0%} | {fn} |")

    adv = metrics["fn_adversarial"]["rate"]
    real = metrics["fn_realistic"]["rate"]
    leak = metrics["fn_leakage"]["rate"]
    L += ["", "## 5. Interpretation", ""]
    if adv < 0.1 and real < 0.1:
        L.append("Classifier is calibrated. 99.5% mc=True reflects LLM capability.")
    elif real > 0.3 and leak > 0.3:
        L.append("Classifier is broken: evaluates code, not reasoning. LEG uninterpretable.")
    elif real > 0.3:
        L.append("Classifier fails on real outputs. LEG metric unreliable in practice.")
    elif adv > 0.3:
        L.append("Classifier has poor mechanism detection. LEG metric compromised.")
    else:
        L.append("Mixed results. See per-probe table.")
    if leak > 0.3:
        L.append("HIGH leakage: classifier uses code correctness as reasoning proxy.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Classifier adversarial probes")
    ap.add_argument("--config", required=True, help="YAML config file")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--output-dir", default="audits")
    args = ap.parse_args()

    from core.config.experiment_config import load_config, get_config
    from core.registry.prompt_registry import load_prompt_registry

    load_config(args.config)
    config = get_config()
    load_prompt_registry()

    cases = json.loads(Path("cases_v2.json").read_text())
    case_by_id = {c["id"]: c for c in cases}
    for c in cases:
        c["code_files_contents"] = {
            p: Path(p).read_text() for p in c["code_files"]}

    probes = resolve_probes(case_by_id)
    total = len(probes) * args.trials
    print(f"Loaded {len(probes)} probes x {args.trials} trials = "
          f"{total} calls", flush=True)

    results = []
    for probe in probes:
        case = case_by_id[probe["case_id"]]
        for trial in range(1, args.trials + 1):
            r = run_trial(probe, case, config)
            if "error" in r:
                print(f"  [{len(results)+1:4d}] {probe['id']:6s} "
                      f"t={trial} ERROR: {r['error']}", flush=True)
                r.update({d: None for d in DIMS})
                r.setdefault("confidence", None)
            else:
                mc = r["mechanism_identified"]
                fn = " FN!" if (mc == "CORRECT"
                               and probe["expected"] != "correct") else ""
                print(f"  [{len(results)+1:4d}] {probe['id']:6s} "
                      f"t={trial} mech={mc}{fn}", flush=True)
            r["probe_id"] = probe["id"]
            r["probe_type"] = probe["type"]
            r["case_id"] = probe["case_id"]
            r["trial"] = trial
            r["expected"] = probe["expected"]
            results.append(r)

    metrics = compute_metrics(results)
    out = Path(args.output_dir)
    out.mkdir(exist_ok=True)

    slim = [{k: v for k, v in r.items() if k != "response_raw"}
            for r in results]
    (out / "classifier_probe_results.json").write_text(
        json.dumps(slim, indent=2))
    (out / "classifier_probe_results_full.json").write_text(
        json.dumps(results, indent=2))
    md = format_analysis(results, metrics)
    (out / "classifier_probe_analysis.md").write_text(md)

    print(f"\nResults: {out}/classifier_probe_results.json")
    print(f"Analysis: {out}/classifier_probe_analysis.md\n")
    for cat in ["adversarial", "realistic", "leakage"]:
        s = metrics[f"fn_{cat}"]
        print(f"  FN_{cat}: {s['rate']:.1%} "
              f"[{s['ci_lo']:.1%}, {s['ci_hi']:.1%}] "
              f"({s['fn']}/{s['n']})")
    tp = metrics["tp_control"]
    print(f"  TP_control: {tp['rate']:.1%} ({tp['tp']}/{tp['n']})")


if __name__ == "__main__":
    main()
