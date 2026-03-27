"""Tests for V2 case integration into the pipeline.

Verifies:
  - V2 cases load through runner.py
  - V2 cases route to tests_v2/ tests (not 'no test defined')
  - V2 buggy code fails, reference fixes pass
  - No case scores 0.5 (all have tests)
  - All V2 failure_modes have reasoning signals
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

BASE = Path(__file__).resolve().parents[1]


def _load_v2_cases():
    return json.loads((BASE / "cases_v2.json").read_text())


def _concat_code(case):
    parts = []
    for fp in case["code_files"]:
        parts.append((BASE / fp).read_text().strip())
    return "\n\n".join(parts)


def _wrap(code):
    return f"```python\n{code}\n```"


# ── V2 cases load through runner ──────────────────────────


def test_v2_cases_load():
    from runner import load_cases

    cases = load_cases(cases_file="cases_v2.json")
    assert len(cases) >= 45
    assert all("code_files_contents" in c for c in cases)
    assert all("id" in c for c in cases)


def test_v2_cases_have_required_fields():
    cases = _load_v2_cases()
    for c in cases:
        assert "id" in c, f"missing id"
        assert "task" in c, f"{c.get('id')}: missing task"
        assert "code_files" in c, f"{c.get('id')}: missing code_files"
        assert "failure_mode" in c, f"{c.get('id')}: missing failure_mode"
        assert "family" in c, f"{c.get('id')}: missing family"
        assert "difficulty" in c, f"{c.get('id')}: missing difficulty"


# ── V2 cases route to correct tests ──────────────────────


def test_v2_case_has_test_function():
    """Every V2 case must have a loadable test function."""
    from exec_eval import _load_v2_test

    cases = _load_v2_cases()
    for c in cases:
        # Skip any migrated v1 trap cases (they use _CASE_TESTS)
        if c.get("family") == "v1_trap":
            continue
        fn = _load_v2_test(c)
        assert (
            fn is not None
        ), f"No test for {c['id']} (family={c.get('family')}, diff={c.get('difficulty')})"


def test_v2_buggy_code_fails_test():
    """V2 buggy code must FAIL the invariant test."""
    from exec_eval import exec_evaluate

    cases = _load_v2_cases()
    # Test a sample from each family
    tested_families = set()
    for c in cases:
        fam = c.get("family", "")
        if fam in tested_families or fam == "v1_trap":
            continue
        tested_families.add(fam)
        buggy = _concat_code(c)
        result = exec_evaluate(c, buggy)
        assert not result["pass"], f"{c['id']}: buggy code should FAIL but got pass=True"
        assert result["score"] != 0.5, f"{c['id']}: scored 0.5 (no test found!)"


def test_v2_reference_fix_passes_test():
    """V2 reference fix must PASS the invariant test."""
    from exec_eval import exec_evaluate

    cases = _load_v2_cases()
    tested_families = set()
    for c in cases:
        fam = c.get("family", "")
        if fam in tested_families or fam == "v1_trap":
            continue
        if not c.get("reference_fix"):
            continue
        tested_families.add(fam)
        ref_code = c["reference_fix"].get("code", "")
        if not ref_code:
            continue
        result = exec_evaluate(c, ref_code)
        assert result[
            "pass"
        ], f"{c['id']}: reference fix should PASS but got {result.get('reasons', [])}"


def test_no_v2_case_scores_0_5():
    """No V2 case should get score=0.5 'no test defined'."""
    from exec_eval import exec_evaluate

    cases = _load_v2_cases()
    for c in cases:
        if c.get("family") == "v1_trap":
            continue
        buggy = _concat_code(c)
        result = exec_evaluate(c, buggy)
        assert result["score"] != 0.5, f"{c['id']}: no test found (score=0.5)"


# ── Reasoning signals exist for all V2 modes ─────────────


def test_all_v2_failure_modes_have_signals():
    from evaluator import _REASONING_SIGNALS

    cases = _load_v2_cases()
    modes = set(c["failure_mode"] for c in cases if c.get("family") != "v1_trap")
    for mode in modes:
        assert mode in _REASONING_SIGNALS, f"No reasoning signals for failure_mode={mode}"
        assert len(_REASONING_SIGNALS[mode]) >= 1, f"Empty signals for {mode}"
