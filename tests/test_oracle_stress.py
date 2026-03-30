#!/usr/bin/env python3
"""Oracle stress test for T3 benchmark.

Loads buggy and correct variants from validation/oracle_variants.json,
runs each through exec_evaluate, and verifies:
  - Buggy variants MUST fail (oracle correctly rejects them)
  - Correct variants MUST pass (oracle is not over-constrained)

Writes results to:
  - validation/oracle_stress_test_results.json
  - validation/oracle_stress_test_summary.md

Usage:
    python tests/test_oracle_stress.py
    python tests/test_oracle_stress.py --case alias_config_a
    python tests/test_oracle_stress.py --verbose
"""

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exec_eval import exec_evaluate


def load_cases():
    """Load all cases from cases_v2.json and populate code_files_contents."""
    cases_path = BASE / "cases_v2.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    for case in cases:
        case["code_files_contents"] = {}
        for rel in case.get("code_files", []):
            full_path = BASE / rel
            if full_path.exists():
                case["code_files_contents"][rel] = full_path.read_text(encoding="utf-8")
    return {c["id"]: c for c in cases}


def load_variants():
    """Load variant definitions from oracle_variants.json."""
    variants_path = BASE / "validation" / "oracle_variants.json"
    return json.loads(variants_path.read_text(encoding="utf-8"))


def run_variant(case, variant_code, verbose=False):
    """Run a single variant through exec_evaluate and return result dict."""
    try:
        result = exec_evaluate(case, variant_code)
        passed = result.get("pass", False)
        reasons = result.get("reasons", [])
        exec_status = result.get("execution", {}).get("status", "unknown")
        return {
            "passed": passed,
            "exec_status": exec_status,
            "reasons": reasons,
            "error": None,
        }
    except Exception as e:
        return {
            "passed": None,
            "exec_status": "exception",
            "reasons": [],
            "error": f"{type(e).__name__}: {e}",
        }


def evaluate_case(case_id, case, case_variants, verbose=False):
    """Evaluate all buggy and correct variants for a single case."""
    buggy_results = []
    correct_results = []
    issues = []

    # --- Buggy variants: must FAIL ---
    for i, variant in enumerate(case_variants.get("buggy_variants", [])):
        code = variant["code"]
        failure_type = variant.get("failure_type", "unknown")
        description = variant.get("description", "")

        result = run_variant(case, code, verbose)
        expected = False  # buggy code should fail
        actual = result["passed"]

        entry = {
            "variant_index": i,
            "failure_type": failure_type,
            "description": description,
            "expected_pass": expected,
            "actual_pass": actual,
            "exec_status": result["exec_status"],
            "reasons": result["reasons"],
            "error": result["error"],
            "oracle_correct": (actual == expected),
        }
        buggy_results.append(entry)

        if actual is True:
            issue = (
                f"BUGGY variant {i} ({failure_type}) PASSED when it should FAIL -- "
                f"oracle does not catch: {description}"
            )
            issues.append(issue)
        elif actual is None:
            issue = (
                f"BUGGY variant {i} ({failure_type}) raised exception: {result['error']}"
            )
            issues.append(issue)

    # --- Correct variants: must PASS ---
    for i, variant in enumerate(case_variants.get("correct_variants", [])):
        code = variant["code"]
        description = variant.get("description", "")

        result = run_variant(case, code, verbose)
        expected = True  # correct code should pass
        actual = result["passed"]

        entry = {
            "variant_index": i,
            "description": description,
            "expected_pass": expected,
            "actual_pass": actual,
            "exec_status": result["exec_status"],
            "reasons": result["reasons"],
            "error": result["error"],
            "oracle_correct": (actual == expected),
        }
        correct_results.append(entry)

        if actual is False:
            issue = (
                f"CORRECT variant {i} FAILED when it should PASS -- "
                f"oracle may be over-constrained: {description}. "
                f"Reasons: {result['reasons']}"
            )
            issues.append(issue)
        elif actual is None:
            issue = (
                f"CORRECT variant {i} raised exception: {result['error']}"
            )
            issues.append(issue)

    # Compute rates
    buggy_total = len(buggy_results)
    buggy_rejected = sum(1 for r in buggy_results if r["actual_pass"] is False)
    correct_total = len(correct_results)
    correct_accepted = sum(1 for r in correct_results if r["actual_pass"] is True)

    return {
        "buggy_variants": buggy_results,
        "correct_variants": correct_results,
        "buggy_fail_rate": round(buggy_rejected / buggy_total, 3) if buggy_total else 0,
        "correct_pass_rate": round(correct_accepted / correct_total, 3) if correct_total else 0,
        "issues": issues,
    }


def generate_markdown(results, summary):
    """Generate markdown summary report."""
    lines = []
    lines.append("# Oracle Stress Test Results")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total buggy variants: {summary['total_buggy']}")
    lines.append(f"- Total correct variants: {summary['total_correct']}")
    lines.append(f"- Buggy correctly rejected: {summary['buggy_correctly_rejected']}/{summary['total_buggy']}")
    lines.append(f"- Correct correctly accepted: {summary['correct_correctly_accepted']}/{summary['total_correct']}")
    lines.append("")

    if summary["weak_tests"]:
        lines.append("## Weak Tests (Action Required)")
        lines.append("")
        for wt in summary["weak_tests"]:
            lines.append(f"- {wt}")
        lines.append("")

    # Per-case details
    lines.append("## Per-Case Results")
    lines.append("")

    for case_id, case_data in results.items():
        lines.append(f"### {case_id}")
        lines.append("")
        lines.append(f"- Buggy fail rate: {case_data['buggy_fail_rate']:.1%}")
        lines.append(f"- Correct pass rate: {case_data['correct_pass_rate']:.1%}")
        lines.append("")

        if case_data["issues"]:
            lines.append("**Issues:**")
            for issue in case_data["issues"]:
                lines.append(f"- {issue}")
            lines.append("")

        # Buggy variants table
        lines.append("**Buggy variants:**")
        lines.append("")
        lines.append("| # | Failure Type | Oracle Correct | Status |")
        lines.append("|---|-------------|----------------|--------|")
        for r in case_data["buggy_variants"]:
            mark = "PASS" if r["oracle_correct"] else "FAIL"
            lines.append(
                f"| {r['variant_index']} | {r['failure_type']} | {mark} | "
                f"exec={r['exec_status']} |"
            )
        lines.append("")

        # Correct variants table
        lines.append("**Correct variants:**")
        lines.append("")
        lines.append("| # | Description | Oracle Correct | Status |")
        lines.append("|---|------------|----------------|--------|")
        for r in case_data["correct_variants"]:
            mark = "PASS" if r["oracle_correct"] else "FAIL"
            lines.append(
                f"| {r['variant_index']} | {r['description'][:50]} | {mark} | "
                f"exec={r['exec_status']} |"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Oracle stress test for T3 benchmark")
    parser.add_argument("--case", default=None, help="Run only this case_id")
    parser.add_argument("--verbose", action="store_true", help="Print detailed output")
    args = parser.parse_args()

    print("=" * 60)
    print("T3 Oracle Stress Test")
    print("=" * 60)
    print()

    # Load data
    print("Loading cases from cases_v2.json...")
    cases = load_cases()
    print(f"  Loaded {len(cases)} cases")

    print("Loading variants from validation/oracle_variants.json...")
    variants = load_variants()
    variant_case_ids = list(variants.keys())
    print(f"  Found variants for: {variant_case_ids}")
    print()

    # Filter if --case specified
    if args.case:
        if args.case not in variants:
            print(f"ERROR: case '{args.case}' not found in variants file")
            sys.exit(1)
        variant_case_ids = [args.case]

    # Run evaluations
    all_results = {}
    total_buggy = 0
    total_correct = 0
    buggy_correctly_rejected = 0
    correct_correctly_accepted = 0
    weak_tests = []

    for case_id in variant_case_ids:
        if case_id not in cases:
            print(f"WARNING: case '{case_id}' not found in cases_v2.json, skipping")
            continue

        case = cases[case_id]
        case_variants = variants[case_id]

        n_buggy = len(case_variants.get("buggy_variants", []))
        n_correct = len(case_variants.get("correct_variants", []))
        print(f"Testing {case_id} ({n_buggy} buggy, {n_correct} correct)...")

        result = evaluate_case(case_id, case, case_variants, args.verbose)
        all_results[case_id] = result

        # Accumulate totals
        case_buggy = len(result["buggy_variants"])
        case_correct = len(result["correct_variants"])
        case_buggy_rejected = sum(
            1 for r in result["buggy_variants"] if r["actual_pass"] is False
        )
        case_correct_accepted = sum(
            1 for r in result["correct_variants"] if r["actual_pass"] is True
        )

        total_buggy += case_buggy
        total_correct += case_correct
        buggy_correctly_rejected += case_buggy_rejected
        correct_correctly_accepted += case_correct_accepted

        # Print per-case summary
        buggy_status = "OK" if case_buggy_rejected == case_buggy else "WEAK"
        correct_status = "OK" if case_correct_accepted == case_correct else "OVER-CONSTRAINED"

        print(f"  Buggy:   {case_buggy_rejected}/{case_buggy} rejected [{buggy_status}]")
        print(f"  Correct: {case_correct_accepted}/{case_correct} accepted [{correct_status}]")

        if result["issues"]:
            for issue in result["issues"]:
                print(f"  >> {issue}")
                weak_tests.append(f"{case_id}: {issue}")
        print()

    # Build summary
    summary = {
        "total_buggy": total_buggy,
        "total_correct": total_correct,
        "buggy_correctly_rejected": buggy_correctly_rejected,
        "correct_correctly_accepted": correct_correctly_accepted,
        "weak_tests": weak_tests,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Strip code from results JSON to keep it readable (code is in oracle_variants.json)
    results_output = {
        "cases": all_results,
        "summary": summary,
    }

    # Write results
    results_path = BASE / "validation" / "oracle_stress_test_results.json"
    results_path.write_text(json.dumps(results_output, indent=2, default=str), encoding="utf-8")
    print(f"Results written to: {results_path}")

    # Write markdown
    md_path = BASE / "validation" / "oracle_stress_test_summary.md"
    md_content = generate_markdown(all_results, summary)
    md_path.write_text(md_content, encoding="utf-8")
    print(f"Summary written to: {md_path}")

    # Final summary
    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"  Buggy correctly rejected:  {buggy_correctly_rejected}/{total_buggy}")
    print(f"  Correct correctly accepted: {correct_correctly_accepted}/{total_correct}")

    if weak_tests:
        print()
        print(f"  WEAK TESTS ({len(weak_tests)}):")
        for wt in weak_tests:
            print(f"    - {wt}")
        print()
        print("  STATUS: ISSUES FOUND -- some tests need strengthening")
    else:
        print()
        print("  STATUS: ALL CLEAR -- oracle correctly handles all variants")

    # Exit code: 0 if all good, 1 if issues found
    sys.exit(1 if weak_tests else 0)


if __name__ == "__main__":
    main()
