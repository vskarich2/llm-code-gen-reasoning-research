"""Retrospective AST evaluation — strict + relaxed + partial tiers."""

import ast
import csv
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from checkers import CASE_RULES, find_function

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def load_case_end_events(paths):
    events = []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                ev = json.loads(line)
                if ev.get("event_type") == "case.end":
                    events.append(ev)
    return events


def evaluate_event(ev):
    case_id = ev["case_id"]
    payload = ev.get("payload", {})
    model = ev.get("model", "unknown")
    condition = ev.get("context", {}).get("condition", "unknown")
    trial = ev.get("trial", 0)
    recon_status = payload.get("reconstruction_status")
    exec_pass = payload.get("pass", False)
    v2_category = payload.get("v2_category", "")
    mechanism_correct = payload.get("mechanism_correct", False)

    base = {
        "case_id": case_id, "model": model, "condition": condition,
        "trial": trial, "recon_success": recon_status == "SUCCESS",
        "exec_pass": exec_pass, "v2_category": v2_category,
        "mechanism_correct": mechanism_correct,
    }

    if case_id not in CASE_RULES:
        base.update(ast_assessable=False, reason="no_rules")
        return base

    if recon_status != "SUCCESS":
        base.update(ast_assessable=False, reason="recon_failed")
        return base

    code = payload.get("_extracted_code", "")
    if not code.strip():
        base.update(ast_assessable=False, reason="empty_code")
        return base

    try:
        tree = ast.parse(code)
    except SyntaxError:
        base.update(ast_assessable=False, reason="syntax_error")
        return base

    func_name, strict_fn, relaxed_fn, anti_fn = CASE_RULES[case_id]
    func_node = find_function(tree, func_name)
    if func_node is None:
        base.update(ast_assessable=True, ast_strict=False, ast_relaxed=False,
                    ast_partial=False, anti_found=False, reason="function_not_found")
        _add_categories(base)
        return base

    strict_ok = strict_fn(func_node)
    relaxed_ok = relaxed_fn(func_node)
    anti_found = anti_fn(func_node) if anti_fn else False

    ast_strict = strict_ok and not anti_found
    ast_relaxed = relaxed_ok and not anti_found
    ast_partial = relaxed_ok and not strict_ok  # relaxed passes but strict doesn't

    base.update(
        ast_assessable=True,
        ast_strict=ast_strict,
        ast_relaxed=ast_relaxed,
        ast_partial=ast_partial,
        anti_found=anti_found,
        reason="evaluated",
        code_snippet=code[:500],  # for lucky fix audit
    )
    _add_categories(base)
    return base


def _add_categories(row):
    ep = row.get("exec_pass", False)

    # Strict categories
    s = row.get("ast_strict", False)
    if s and ep:
        row["ast_cat_strict"] = "TRUE_SUCCESS"
    elif s and not ep:
        row["ast_cat_strict"] = "AST_CORRECT_FAILURE"
    elif not s and ep:
        row["ast_cat_strict"] = "LUCKY_FIX"
    else:
        row["ast_cat_strict"] = "FULL_FAILURE"

    # Relaxed categories
    r = row.get("ast_relaxed", False)
    if r and ep:
        row["ast_cat_relaxed"] = "TRUE_SUCCESS"
    elif r and not ep:
        row["ast_cat_relaxed"] = "AST_CORRECT_FAILURE"
    elif not r and ep:
        row["ast_cat_relaxed"] = "LUCKY_FIX"
    else:
        row["ast_cat_relaxed"] = "FULL_FAILURE"

    # LEG + lucky fix derived
    row["LEG_strict"] = s and not ep
    row["LEG_relaxed"] = r and not ep
    row["LEG_text"] = row.get("v2_category") == "LEG_v2"
    row["lucky_strict"] = not s and ep
    row["lucky_relaxed"] = not r and ep


def find_all_merged_events():
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    paths = []
    for dirpath, dirs, files in os.walk(logs_dir):
        for f in files:
            if f == "merged_events.jsonl":
                paths.append(os.path.join(dirpath, f))
    return sorted(paths)


def print_matrix(label, assessable, cat_key):
    cats = defaultdict(int)
    for r in assessable:
        cats[r.get(cat_key, "?")] += 1
    total = len(assessable)
    ts = cats.get("TRUE_SUCCESS", 0)
    acf = cats.get("AST_CORRECT_FAILURE", 0)
    lf = cats.get("LUCKY_FIX", 0)
    ff = cats.get("FULL_FAILURE", 0)

    print(f"\n{'':20s} {'Exec Pass':>12s} {'Exec Fail':>12s} {'Total':>8s}")
    print(f"{'AST Correct':20s} {ts:>12d} {acf:>12d} {ts+acf:>8d}")
    print(f"{'AST Incorrect':20s} {lf:>12d} {ff:>12d} {lf+ff:>8d}")
    print(f"{'Total':20s} {ts+lf:>12d} {acf+ff:>12d} {total:>8d}")
    print(f"\nAST_CORRECT_FAILURE: {acf}/{total} = {acf/max(total,1)*100:.1f}%")
    print(f"LUCKY_FIX: {lf}/{total} = {lf/max(total,1)*100:.1f}%")
    print(f"AST_correct: {(ts+acf)}/{total} = {(ts+acf)/max(total,1)*100:.1f}%")
    print(f"Exec_pass: {(ts+lf)}/{total} = {(ts+lf)/max(total,1)*100:.1f}%")
    return ts, acf, lf, ff


def main():
    print("=== AST Phase 1 — Strict + Relaxed Tiers ===\n")

    all_paths = find_all_merged_events()
    events = load_case_end_events(all_paths)
    target_cases = set(CASE_RULES.keys())
    target_events = [e for e in events if e["case_id"] in target_cases]
    results = [evaluate_event(ev) for ev in target_events]

    # Write CSV
    csv_path = os.path.join(os.path.dirname(__file__), "ast_retro_results.csv")
    fieldnames = [
        "case_id", "model", "condition", "trial",
        "recon_success", "ast_assessable",
        "ast_strict", "ast_relaxed", "ast_partial", "anti_found",
        "ast_cat_strict", "ast_cat_relaxed",
        "exec_pass", "v2_category", "mechanism_correct",
        "LEG_strict", "LEG_relaxed", "LEG_text",
        "lucky_strict", "lucky_relaxed", "reason",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    assessable = [r for r in results if r.get("ast_assessable")]
    not_assessable = [r for r in results if not r.get("ast_assessable")]

    print(f"Total target events: {len(results)}")
    print(f"  Assessable: {len(assessable)}")
    print(f"  Not assessable: {len(not_assessable)}")
    na_reasons = defaultdict(int)
    for r in not_assessable:
        na_reasons[r.get("reason", "?")] += 1
    if na_reasons:
        print(f"  Reasons: {dict(na_reasons)}")

    # ── STRICT MATRIX ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STRICT MATRIX (recon-only)")
    print("=" * 60)
    s_ts, s_acf, s_lf, s_ff = print_matrix("strict", assessable, "ast_cat_strict")

    # ── RELAXED MATRIX ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RELAXED MATRIX (recon-only)")
    print("=" * 60)
    r_ts, r_acf, r_lf, r_ff = print_matrix("relaxed", assessable, "ast_cat_relaxed")

    # ── COMPARISON ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STRICT vs RELAXED COMPARISON")
    print("=" * 60)
    total_a = len(assessable)
    print(f"\n{'Metric':<30s} {'Strict':>10s} {'Relaxed':>10s} {'Delta':>10s}")
    print(f"{'AST_correct_rate':<30s} {(s_ts+s_acf)/total_a*100:>9.1f}% {(r_ts+r_acf)/total_a*100:>9.1f}% {((r_ts+r_acf)-(s_ts+s_acf))/total_a*100:>+9.1f}%")
    print(f"{'AST_CORRECT_FAILURE':<30s} {s_acf/total_a*100:>9.1f}% {r_acf/total_a*100:>9.1f}% {(r_acf-s_acf)/total_a*100:>+9.1f}%")
    print(f"{'LUCKY_FIX':<30s} {s_lf/total_a*100:>9.1f}% {r_lf/total_a*100:>9.1f}% {(r_lf-s_lf)/total_a*100:>+9.1f}%")

    # ── LEG COMPARISON ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("LEG COMPARISON")
    print("=" * 60)
    leg_s = sum(1 for r in assessable if r.get("LEG_strict"))
    leg_r = sum(1 for r in assessable if r.get("LEG_relaxed"))
    leg_t = sum(1 for r in assessable if r.get("LEG_text"))
    print(f"\nLEG_strict:  {leg_s}/{total_a} = {leg_s/total_a*100:.1f}%")
    print(f"LEG_relaxed: {leg_r}/{total_a} = {leg_r/total_a*100:.1f}%")
    print(f"LEG_text:    {leg_t}/{total_a} = {leg_t/total_a*100:.1f}%")

    # ── AGREEMENT WITH EVALUATOR ──────────────────────────────────
    print("\n" + "=" * 60)
    print("AST_RELAXED vs MECHANISM_CORRECT AGREEMENT")
    print("=" * 60)
    agree = sum(1 for r in assessable if r.get("ast_relaxed") == r.get("mechanism_correct"))
    print(f"\nAgreement: {agree}/{total_a} = {agree/total_a*100:.1f}%")
    ast_yes_mc_no = sum(1 for r in assessable if r.get("ast_relaxed") and not r.get("mechanism_correct"))
    ast_no_mc_yes = sum(1 for r in assessable if not r.get("ast_relaxed") and r.get("mechanism_correct"))
    print(f"  AST=correct, mech=wrong: {ast_yes_mc_no}")
    print(f"  AST=incorrect, mech=correct: {ast_no_mc_yes}")

    # ── PER-CASE BREAKDOWN (RELAXED) ─────────────────────────────
    print("\n" + "=" * 60)
    print("PER-CASE BREAKDOWN (RELAXED)")
    print("=" * 60)
    case_data = defaultdict(lambda: defaultdict(int))
    for r in assessable:
        cid = r["case_id"]
        case_data[cid]["total"] += 1
        case_data[cid][r.get("ast_cat_relaxed", "?")] += 1
        if r.get("LEG_relaxed"):
            case_data[cid]["LEG_r"] += 1
        if r.get("lucky_relaxed"):
            case_data[cid]["LF_r"] += 1

    print(f"\n{'Case':<25s} {'N':>5s} {'TS':>5s} {'ACF':>5s} {'LF':>5s} {'FF':>5s} "
          f"{'ACF%':>6s} {'LF%':>6s}")
    for cid in sorted(case_data.keys()):
        cd = case_data[cid]
        n = cd["total"]
        print(f"{cid:<25s} {n:>5d} "
              f"{cd.get('TRUE_SUCCESS',0):>5d} "
              f"{cd.get('AST_CORRECT_FAILURE',0):>5d} "
              f"{cd.get('LUCKY_FIX',0):>5d} "
              f"{cd.get('FULL_FAILURE',0):>5d} "
              f"{cd.get('AST_CORRECT_FAILURE',0)/max(n,1)*100:>5.1f}% "
              f"{cd.get('LUCKY_FIX',0)/max(n,1)*100:>5.1f}%")

    # ── PER-MODEL (RELAXED) ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("PER-MODEL BREAKDOWN (RELAXED)")
    print("=" * 60)
    model_data = defaultdict(lambda: defaultdict(int))
    for r in assessable:
        m = r["model"]
        model_data[m]["total"] += 1
        model_data[m][r.get("ast_cat_relaxed", "?")] += 1

    print(f"\n{'Model':<25s} {'N':>5s} {'TS':>5s} {'ACF':>5s} {'LF':>5s} {'FF':>5s} "
          f"{'ACF%':>6s} {'LF%':>6s} {'AST%':>6s}")
    for m in sorted(model_data.keys()):
        md = model_data[m]
        n = md["total"]
        ts_ = md.get("TRUE_SUCCESS", 0)
        acf_ = md.get("AST_CORRECT_FAILURE", 0)
        lf_ = md.get("LUCKY_FIX", 0)
        ff_ = md.get("FULL_FAILURE", 0)
        print(f"{m:<25s} {n:>5d} {ts_:>5d} {acf_:>5d} {lf_:>5d} {ff_:>5d} "
              f"{acf_/max(n,1)*100:>5.1f}% "
              f"{lf_/max(n,1)*100:>5.1f}% "
              f"{(ts_+acf_)/max(n,1)*100:>5.1f}%")

    # ── LUCKY FIX AUDIT SAMPLE ────────────────────────────────────
    print("\n" + "=" * 60)
    print("LUCKY FIX AUDIT (relaxed)")
    print("=" * 60)
    lucky_events = [r for r in results if r.get("ast_cat_relaxed") == "LUCKY_FIX"
                    and r.get("ast_assessable") and r.get("code_snippet")]
    sample_size = min(50, len(lucky_events))
    if lucky_events:
        random.seed(42)
        sample = random.sample(lucky_events, sample_size)
        audit_path = os.path.join(os.path.dirname(__file__), "lucky_fix_audit.csv")
        with open(audit_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "case_id", "model", "condition", "trial",
                "ast_strict", "ast_relaxed", "anti_found",
                "code_snippet", "classification", "notes",
            ], extrasaction="ignore")
            w.writeheader()
            for r in sample:
                r["classification"] = ""  # to be filled manually
                r["notes"] = ""
                w.writerow(r)
        print(f"\n  Sampled {sample_size} of {len(lucky_events)} lucky fix events")
        print(f"  Written to {audit_path}")
        print(f"  → MANUAL REVIEW REQUIRED: classify each as")
        print(f"     1=valid_alternative, 2=true_lucky_fix, 3=rule_failure")
    else:
        print("\n  No lucky fix events found (relaxed).")

    # ── DECISION ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DECISION")
    print("=" * 60)
    r_acf_rate = r_acf / max(total_a, 1) * 100
    r_lf_rate = r_lf / max(total_a, 1) * 100
    print(f"\n  LEG_relaxed = {r_acf_rate:.1f}%")
    print(f"  LUCKY_FIX_relaxed = {r_lf_rate:.1f}%")
    print(f"  Lucky fix drop from strict: {s_lf/total_a*100:.1f}% → {r_lf_rate:.1f}%")

    if r_acf_rate > 5.0:
        print(f"\n  ✓ LEG_relaxed > 5% — clean signal confirmed")
    elif r_acf_rate > 2.0:
        print(f"\n  ~ LEG_relaxed > 2% — signal present but weak")
    else:
        print(f"\n  ✗ LEG_relaxed ≤ 2% — signal too weak")


if __name__ == "__main__":
    main()
