"""Recompute DDC evaluation metrics using 3-axis decomposition.

Reads ONLY from WAL (events.jsonl) files across v3 and v4 hint ablation runs.
Produces:
  - analysis/ddc_recomputed_metrics.json   (aggregates per model×condition)
  - analysis/ddc_case_level_metrics.jsonl  (per-case records)
  - analysis/ddc_metrics_audit.md          (human-readable audit report)

Axes:
  1. mechanism_correct  — oracle says reasoning describes the bug mechanism
  2. location_correct   — model changed the file containing the root cause
  3. execution_pass     — spec oracle depth==A or test passed
"""

import json
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "analysis"
OUT_DIR.mkdir(exist_ok=True)

CASES_V2 = json.load(open(PROJECT_ROOT / "case_data" / "cases_v2.json"))
CASE_MAP = {c["id"]: c for c in CASES_V2}

DDC_FAMILIES = {
    "auth_context_chain", "billing_aggregation_chain", "config_derivation_chain",
    "event_etl_chain", "logging_pipeline_chain", "ml_feature_chain",
    "search_index_chain", "serialization_pipeline_chain",
}

LOG_DIRS = [
    PROJECT_ROOT / "logs" / "hint_ablation_v3",
    PROJECT_ROOT / "logs" / "hint_ablation_v4",
]

MODELS = ["gpt-4o-mini", "gpt-5.4-mini", "gpt-5-mini"]


def _parse_generation(attempt_dir, attempt_idx):
    """Parse the generation call for a specific attempt index."""
    gen_files = sorted((attempt_dir / "calls_flat").glob("*_generation.txt"))
    # Each attempt has: generation, oracle, classifier(s)
    # Attempt 0 = gen_files[0], attempt 1 = gen_files[1] (if exists)
    target = None
    gen_count = 0
    for gf in gen_files:
        if "_generation.txt" in gf.name:
            if gen_count == attempt_idx:
                target = gf
                break
            gen_count += 1

    if target is None:
        return [], "", ""

    text = target.read_text()
    rs = text.find("--- RESPONSE ---")
    if rs < 0:
        return [], "", ""

    resp_text = text[rs + len("--- RESPONSE ---"):].strip()
    # Strip markdown fences
    if resp_text.startswith("```"):
        resp_text = resp_text.split("\n", 1)[1] if "\n" in resp_text else resp_text
        if "```" in resp_text:
            resp_text = resp_text[:resp_text.rfind("```")]

    try:
        resp = json.loads(resp_text)
        changed = [k for k, v in resp.get("files", {}).items() if v != "UNCHANGED"]
        return changed, resp.get("root_cause", ""), resp.get("fix_strategy", "")
    except (json.JSONDecodeError, TypeError):
        return [], "", ""


def load_all_records():
    """Load all case.end events from v3 and v4 WAL files."""
    records = []

    for log_dir in LOG_DIRS:
        if not log_dir.exists():
            continue
        version = "v3" if "v3" in log_dir.name else "v4"

        for run_dir in sorted(log_dir.iterdir()):
            if not run_dir.is_dir():
                continue

            # Parse model and condition from run dir name
            model = cond = None
            for m in MODELS:
                safe = m.replace(".", "_").replace("-", "_")
                if safe in run_dir.name:
                    model = m
                    cond = run_dir.name.split(safe + "_")[-1].split("_001")[0]
                    break
            if not model or not cond:
                continue

            workers_dir = run_dir / "workers"
            if not workers_dir.exists():
                continue

            for worker in workers_dir.iterdir():
                attempt_dir = worker / "attempt_001"
                events_path = attempt_dir / "events.jsonl"
                if not events_path.exists():
                    continue
                if not (attempt_dir / "metrics.json").exists():
                    continue

                case_id = worker.name.split("__trial_001__")[-1]

                # Skip non-DDC cases
                family = case_id.split("_trap_")[0] if "_trap_" in case_id else case_id
                if family not in DDC_FAMILIES:
                    continue

                for line in open(events_path):
                    ev = json.loads(line)
                    if ev.get("event_type") != "case.end":
                        continue

                    p = ev.get("payload", {})
                    traj = p.get("trajectory", [])
                    oracle = p.get("oracle", {})
                    so = p.get("spec_oracle", {})

                    # Determine final attempt index
                    n_attempts = len(traj)
                    final_idx = n_attempts - 1 if n_attempts > 0 else 0

                    # Parse final attempt's changed files from raw generation call
                    changed_files, root_cause, fix_strategy = _parse_generation(
                        attempt_dir, final_idx)

                    # Get reference fix file
                    case_info = CASE_MAP.get(case_id, {})
                    ref_file = case_info.get("reference_fix", {}).get("file", "")

                    records.append({
                        "version": version,
                        "model": model,
                        "condition": cond,
                        "case_id": case_id,
                        "family": family,
                        "attempt_idx": final_idx,
                        "n_attempts": n_attempts,
                        "oracle_label": oracle.get("reasoning_truth", "UNKNOWN"),
                        "oracle_correct": oracle.get("oracle_correct"),
                        "spec_depth": so.get("llm_depth", {}).get("depth", "?") if so else "?",
                        "test_pass": p.get("pass", False),
                        "changed_files": changed_files,
                        "reference_fix_file": ref_file,
                        "root_cause": root_cause[:200],
                        "fix_strategy": fix_strategy[:200],
                        "attempt_path": str(attempt_dir),
                    })
                    break

    return records


def deduplicate(records):
    """Deduplicate by (model, condition, case_id). Keep last seen."""
    seen = {}
    for r in records:
        key = (r["model"], r["condition"], r["case_id"])
        seen[key] = r
    return list(seen.values())


def compute_metrics(records):
    """Compute 3-axis metrics for each record."""
    per_case = []

    for r in records:
        # Axis 1: mechanism_correct
        if r["oracle_label"] == "UNKNOWN" or r["oracle_correct"] is None:
            mechanism_correct = None
        else:
            mechanism_correct = r["oracle_label"] in {"CORRECT", "PARTIAL"}

        # Changed files
        changed = r["changed_files"]
        if changed is None:
            changed = []

        # No attempt detection
        no_attempt = len(changed) == 0

        # Axis 2: location_correct
        ref = r["reference_fix_file"]
        if not ref:
            location_correct = None  # unknown
        else:
            location_correct = ref in changed

        # Axis 3: execution_pass
        depth = r["spec_depth"]
        if depth == "A":
            execution_pass = True
        elif r["test_pass"] and not no_attempt:
            execution_pass = True
        else:
            execution_pass = False

        if no_attempt:
            execution_pass = False

        # Derived: LEG
        LEG = (
            mechanism_correct is True
            and location_correct is True
            and not execution_pass
        )

        # Derived: Lucky
        Lucky = (
            (mechanism_correct is not True or location_correct is not True)
            and execution_pass
        )

        per_case.append({
            "version": r["version"],
            "model": r["model"],
            "condition": r["condition"],
            "case_id": r["case_id"],
            "family": r["family"],
            "mechanism_correct": mechanism_correct,
            "location_correct": location_correct,
            "execution_pass": execution_pass,
            "LEG": LEG,
            "Lucky": Lucky,
            "num_files_changed": len(changed),
            "no_attempt": no_attempt,
            "oracle_label": r["oracle_label"],
            "spec_depth": r["spec_depth"],
            "changed_files": changed,
            "reference_fix_file": r["reference_fix_file"],
            "root_cause": r["root_cause"],
        })

    return per_case


def aggregate(per_case):
    """Aggregate per (model, condition)."""
    groups = defaultdict(lambda: defaultdict(list))
    for r in per_case:
        groups[r["model"]][r["condition"]].append(r)

    out = {}
    for model in sorted(groups):
        out[model] = {}
        for cond in sorted(groups[model]):
            rows = groups[model][cond]
            n = len(rows)

            def safe_mean(vals):
                vals = [v for v in vals if v is not None and isinstance(v, (bool, int, float))]
                return round(sum(vals) / len(vals), 4) if vals else None

            # Mechanism accuracy: over all cases with known oracle
            mech_vals = [r["mechanism_correct"] for r in rows if r["mechanism_correct"] is not None]

            # Localization accuracy: only over mechanism_correct==True
            loc_vals = [r["location_correct"] for r in rows
                        if r["mechanism_correct"] is True and r["location_correct"] is not None]

            # Execution fidelity: only over mechanism_correct AND location_correct
            exec_vals = [r["execution_pass"] for r in rows
                         if r["mechanism_correct"] is True and r["location_correct"] is True]

            out[model][cond] = {
                "num_cases": n,
                "mechanism_accuracy": safe_mean(mech_vals),
                "localization_accuracy": safe_mean(loc_vals),
                "execution_fidelity": safe_mean(exec_vals),
                "pass_rate": safe_mean([r["execution_pass"] for r in rows]),
                "LEG_rate": safe_mean([r["LEG"] for r in rows]),
                "Lucky_rate": safe_mean([r["Lucky"] for r in rows]),
                "avg_files_changed": safe_mean([r["num_files_changed"] for r in rows]),
                "no_attempt_rate": safe_mean([r["no_attempt"] for r in rows]),
            }

    return out


def write_audit_report(per_case, agg):
    """Write human-readable audit report."""
    lines = []
    def w(s=""): lines.append(s)

    w("=" * 100)
    w("DDC METRICS AUDIT: 3-AXIS RECOMPUTATION")
    w("=" * 100)
    w()

    w("METRIC DEFINITIONS")
    w("-" * 60)
    w("mechanism_correct:  oracle_label in {CORRECT, PARTIAL}")
    w("  Evaluates: did the model's root_cause text describe the bug mechanism?")
    w("  Does NOT evaluate: intervention location, file choice, code correctness")
    w()
    w("location_correct:   reference_fix.file in changed_files")
    w("  Evaluates: did the model touch the file containing the root cause?")
    w("  Deterministic — no LLM judgment involved")
    w()
    w("execution_pass:     spec_oracle.depth == 'A' OR test_pass == True")
    w("  Evaluates: did the model's code actually fix the bug?")
    w("  Uses spec oracle (code-based, 0% error rate) as primary signal")
    w()
    w("LEG (corrected):    mechanism_correct AND location_correct AND NOT execution_pass")
    w("  The model understood the bug AND touched the right file BUT the code was wrong")
    w("  This is stricter than the old LEG which only required mechanism_correct")
    w()
    w("Lucky:              (NOT mechanism_correct OR NOT location_correct) AND execution_pass")
    w("  The model passed despite wrong reasoning OR wrong file")
    w()

    w("COMPARISON VS OLD METRICS")
    w("-" * 60)
    w("Old LEG = mechanism_correct AND NOT execution_pass")
    w("  Problem: counted cases where model described mechanism but fixed wrong file")
    w("  These are not execution gaps — they are location errors")
    w()
    w("New LEG = mechanism_correct AND location_correct AND NOT execution_pass")
    w("  Only counts cases where the model knew what AND where, but failed how")
    w()

    # Compute old vs new LEG
    old_leg = sum(1 for r in per_case if r["mechanism_correct"] and not r["execution_pass"])
    new_leg = sum(1 for r in per_case if r["LEG"])
    location_errors = sum(1 for r in per_case if r["mechanism_correct"]
                          and r["location_correct"] is False and not r["execution_pass"])
    w(f"Old LEG total: {old_leg}")
    w(f"New LEG total: {new_leg}")
    w(f"Reclassified as location errors: {location_errors}")
    w(f"  (cases that were old-LEG but are NOT new-LEG because location_correct=False)")
    w()

    # Aggregate table
    w("AGGREGATE TABLE")
    w("-" * 100)
    header = f"{'model':<14} {'condition':<35} {'n':>3} {'mech':>5} {'loc':>5} {'exec':>5} {'pass':>5} {'LEG':>5} {'lucky':>5} {'files':>5}"
    w(header)
    w("-" * 100)

    for model in sorted(agg):
        for cond in sorted(agg[model]):
            a = agg[model][cond]
            def fmt(v):
                return f"{v:.2f}" if v is not None else "  n/a"
            w(f"{model:<14} {cond:<35} {a['num_cases']:>3} "
              f"{fmt(a['mechanism_accuracy']):>5} {fmt(a['localization_accuracy']):>5} "
              f"{fmt(a['execution_fidelity']):>5} {fmt(a['pass_rate']):>5} "
              f"{fmt(a['LEG_rate']):>5} {fmt(a['Lucky_rate']):>5} {fmt(a['avg_files_changed']):>5}")
    w()

    # Top 10 LEG cases
    w("TOP LEG CASES (mechanism + location correct, execution failed)")
    w("-" * 100)
    leg_cases = [r for r in per_case if r["LEG"]]
    # Group by case_id, count occurrences
    leg_counts = defaultdict(int)
    for r in leg_cases:
        leg_counts[(r["model"], r["case_id"])] += 1
    for (model, cid), count in sorted(leg_counts.items(), key=lambda x: -x[1])[:10]:
        ex = next(r for r in leg_cases if r["model"] == model and r["case_id"] == cid)
        w(f"  {model} × {cid}: {count} occurrences")
        w(f"    changed: {ex['changed_files']}, ref: {ex['reference_fix_file']}")
        w(f"    root_cause: {ex['root_cause'][:120]}")
    w()

    # Top 10 Lucky cases
    w("TOP LUCKY CASES (execution passed despite wrong mechanism or location)")
    w("-" * 100)
    lucky_cases = [r for r in per_case if r["Lucky"]]
    lucky_counts = defaultdict(int)
    for r in lucky_cases:
        lucky_counts[(r["model"], r["case_id"])] += 1
    for (model, cid), count in sorted(lucky_counts.items(), key=lambda x: -x[1])[:10]:
        ex = next(r for r in lucky_cases if r["model"] == model and r["case_id"] == cid)
        w(f"  {model} × {cid}: {count} occurrences")
        w(f"    mechanism={ex['mechanism_correct']}, location={ex['location_correct']}")
        w(f"    changed: {ex['changed_files']}, ref: {ex['reference_fix_file']}")
        w(f"    root_cause: {ex['root_cause'][:120]}")
    w()

    # Examples: mechanism correct but wrong location
    w("EXAMPLES: MECHANISM CORRECT, WRONG LOCATION")
    w("-" * 100)
    mech_wrong_loc = [r for r in per_case if r["mechanism_correct"]
                      and r["location_correct"] is False and not r["execution_pass"]]
    seen = set()
    count = 0
    for r in mech_wrong_loc:
        key = (r["model"], r["case_id"])
        if key in seen: continue
        seen.add(key)
        w(f"  {r['model']} × {r['case_id']}:")
        w(f"    changed: {r['changed_files']}, correct: {r['reference_fix_file']}")
        w(f"    root_cause: {r['root_cause'][:120]}")
        count += 1
        if count >= 8: break
    w()

    # Examples: correct location but failed execution
    w("EXAMPLES: CORRECT LOCATION, FAILED EXECUTION (true LEG)")
    w("-" * 100)
    true_leg = [r for r in per_case if r["LEG"]]
    seen = set()
    count = 0
    for r in true_leg:
        key = (r["model"], r["case_id"])
        if key in seen: continue
        seen.add(key)
        w(f"  {r['model']} × {r['case_id']}:")
        w(f"    changed: {r['changed_files']}, correct: {r['reference_fix_file']}")
        w(f"    root_cause: {r['root_cause'][:120]}")
        count += 1
        if count >= 8: break
    w()

    # Model differences across axes
    w("MODEL COMPARISON ACROSS AXES")
    w("-" * 100)
    for model in sorted(agg):
        all_rows = [r for r in per_case if r["model"] == model]
        n = len(all_rows)
        mech = sum(1 for r in all_rows if r["mechanism_correct"]) / n if n else 0
        loc_eligible = [r for r in all_rows if r["mechanism_correct"]]
        loc = sum(1 for r in loc_eligible if r["location_correct"]) / len(loc_eligible) if loc_eligible else 0
        exec_eligible = [r for r in all_rows if r["mechanism_correct"] and r["location_correct"]]
        exe = sum(1 for r in exec_eligible if r["execution_pass"]) / len(exec_eligible) if exec_eligible else 0
        leg = sum(1 for r in all_rows if r["LEG"]) / n if n else 0
        w(f"  {model} (n={n}):")
        w(f"    mechanism_accuracy:     {mech:.2f}  ({sum(1 for r in all_rows if r['mechanism_correct'])}/{n})")
        w(f"    localization_accuracy:  {loc:.2f}  ({sum(1 for r in loc_eligible if r['location_correct'])}/{len(loc_eligible)} of mechanism-correct)")
        w(f"    execution_fidelity:     {exe:.2f}  ({sum(1 for r in exec_eligible if r['execution_pass'])}/{len(exec_eligible)} of mechanism+location correct)")
        w(f"    LEG_rate:              {leg:.3f}  ({sum(1 for r in all_rows if r['LEG'])}/{n})")
        w()

    return "\n".join(lines)


def main():
    print("Loading records from WAL files...")
    records = load_all_records()
    print(f"  Loaded {len(records)} raw records")

    records = deduplicate(records)
    print(f"  After dedup: {len(records)} records")

    print("Computing 3-axis metrics...")
    per_case = compute_metrics(records)

    print("Aggregating...")
    agg = aggregate(per_case)

    # Write outputs
    with open(OUT_DIR / "ddc_case_level_metrics.jsonl", "w") as f:
        for r in per_case:
            # Remove non-serializable fields
            out = {k: v for k, v in r.items() if k != "attempt_path"}
            f.write(json.dumps(out) + "\n")
    print(f"  Wrote {len(per_case)} records to analysis/ddc_case_level_metrics.jsonl")

    with open(OUT_DIR / "ddc_recomputed_metrics.json", "w") as f:
        json.dump(agg, f, indent=2)
    print(f"  Wrote aggregates to analysis/ddc_recomputed_metrics.json")

    report = write_audit_report(per_case, agg)
    with open(OUT_DIR / "ddc_metrics_audit.md", "w") as f:
        f.write(report)
    print(f"  Wrote audit report to analysis/ddc_metrics_audit.md")

    # Summary stats
    total_leg = sum(1 for r in per_case if r["LEG"])
    total_lucky = sum(1 for r in per_case if r["Lucky"])
    total_pass = sum(1 for r in per_case if r["execution_pass"])
    print(f"\nSummary: {len(per_case)} records, {total_pass} pass, {total_leg} LEG, {total_lucky} Lucky")


if __name__ == "__main__":
    main()
