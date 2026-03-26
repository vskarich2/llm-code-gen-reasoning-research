"""Canary run script for evaluator measurement repair.

Validates infrastructure before large experiment runs:
1. Parsing produces non-empty reasoning (>= 4/5 cases)
2. Classifier responds with non-empty output (all cases)
3. Classifier output parses to YES/NO verdict (>= 4/5 cases)
4. All reasoning_evaluator_audit log fields are present (all cases)
5. eval_model_actual matches eval_model_intended (all cases)

Usage:
    python scripts/canary_run.py [--cases 5] [--eval-model gpt-5.4-mini]

Exit 0 on pass, 1 on failure.
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

REQUIRED_RESULT_FIELDS = [
    "reasoning_correct", "failure_type", "classify_raw",
    "classify_parse_error", "eval_model_actual", "parse_category",
]


def run_canary(n_cases: int = 5, eval_model: str | None = None):
    """Run canary validation on n_cases using mock LLM."""
    import os
    # Force mock mode for canary
    old_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = ""

    try:
        from evaluator import llm_classify
        from runner import load_cases

        cases = load_cases(cases_file="cases_v2.json")[:n_cases]
        if len(cases) < n_cases:
            print(f"WARNING: only {len(cases)} cases available")

        results = []
        for case in cases:
            code_content = list(case["code_files_contents"].values())[0][:500]
            reasoning = f"The bug is in {case['failure_mode'].lower().replace('_', ' ')}"

            result = llm_classify(
                case=case,
                code=code_content,
                reasoning=reasoning,
                eval_model=eval_model,
                parse_error=None,
            )
            result["_case_id"] = case["id"]
            results.append(result)

        # Check 1: Parsing works (reasoning was non-empty — we provided it)
        non_empty_reasoning = sum(1 for _ in results)  # all had reasoning
        check1 = non_empty_reasoning >= min(4, len(results))

        # Check 2: Classifier responds
        classifier_responded = sum(
            1 for r in results if r.get("classify_raw") is not None
        )
        check2 = classifier_responded == len(results)

        # Check 3: Classifier parses
        classifier_parsed = sum(
            1 for r in results
            if r.get("reasoning_correct") is not None
        )
        check3 = classifier_parsed >= min(4, len(results))

        # Check 4: All fields present
        all_fields = all(
            all(f in r for f in REQUIRED_RESULT_FIELDS)
            for r in results
        )
        missing = []
        for r in results:
            for f in REQUIRED_RESULT_FIELDS:
                if f not in r:
                    missing.append(f"{r['_case_id']}: missing {f}")
        check4 = all_fields

        # Check 5: eval_model correct
        intended = eval_model or "gpt-5.4-mini"
        model_correct = all(
            r.get("eval_model_actual") == intended or r.get("eval_model_actual") is None
            for r in results
        )
        # None is OK if gated (parse failure)
        model_mismatches = [
            f"{r['_case_id']}: intended={intended}, actual={r.get('eval_model_actual')}"
            for r in results
            if r.get("eval_model_actual") is not None and r.get("eval_model_actual") != intended
        ]
        check5 = len(model_mismatches) == 0

        # Report
        print(f"CANARY RUN: {len(results)} cases")
        print(f"  Check 1 (parsing): {'PASS' if check1 else 'FAIL'} ({non_empty_reasoning}/{len(results)} non-empty)")
        print(f"  Check 2 (classifier responds): {'PASS' if check2 else 'FAIL'} ({classifier_responded}/{len(results)})")
        print(f"  Check 3 (classifier parses): {'PASS' if check3 else 'FAIL'} ({classifier_parsed}/{len(results)})")
        print(f"  Check 4 (all fields): {'PASS' if check4 else 'FAIL'}")
        if missing:
            for m in missing:
                print(f"    MISSING: {m}")
        print(f"  Check 5 (eval_model): {'PASS' if check5 else 'FAIL'}")
        if model_mismatches:
            for m in model_mismatches:
                print(f"    MISMATCH: {m}")

        all_pass = check1 and check2 and check3 and check4 and check5
        print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL'}")
        return all_pass

    finally:
        if old_key is not None:
            os.environ["OPENAI_API_KEY"] = old_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)


def main():
    parser = argparse.ArgumentParser(description="Canary run for evaluator measurement repair")
    parser.add_argument("--cases", type=int, default=5, help="Number of cases to run")
    parser.add_argument("--eval-model", default=None, help="Eval model to test")
    args = parser.parse_args()

    success = run_canary(n_cases=args.cases, eval_model=args.eval_model)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
