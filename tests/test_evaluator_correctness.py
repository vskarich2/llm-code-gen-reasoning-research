"""L0: Evaluator Correctness Validation.

Validates exec_evaluate itself by cross-checking against a minimal harness.
Positive/negative controls for all 58 cases are in test_oracle_correctness.py.
This file adds the cross-check: bypass exec_evaluate and compare results.
"""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from exec_eval import exec_evaluate, load_module_from_code, _load_v2_test, _assemble_program
from validate_cases_v2 import load_reference_code, load_case_code


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


# ============================================================
# CROSS-CHECK: bypass exec_evaluate
# ============================================================


class TestEvaluatorCrossCheck:
    """Run reference fix through exec_evaluate AND through a minimal direct harness.
    Assert both agree and both pass."""

    @pytest.mark.parametrize(
        "case_id",
        [
            "alias_config_a",
            "alias_config_b",
            "stale_cache_a",
            "partial_update_a",
            "mutable_default_a",
        ],
    )
    def test_cross_check_single_and_multi_file(self, case_id):
        case = _load_case(case_id)
        ref_code = load_reference_code(case)
        assert ref_code is not None

        # Path A: through exec_evaluate (full pipeline)
        result_a = exec_evaluate(case, ref_code)

        # Path B: minimal harness — load module, call test function directly
        test_fn = _load_v2_test(case)
        assert test_fn is not None, f"No test function for {case_id}"

        # Assemble code same way exec_evaluate does, then load
        asm = _assemble_program(ref_code, case)
        mod = load_module_from_code(asm["code"], f"crosscheck_{case_id}")
        passed_b, reasons_b = test_fn(mod)

        # Assert both agree
        assert result_a["pass"] == passed_b, (
            f"CROSS-CHECK DIVERGENCE for {case_id}: "
            f"exec_evaluate pass={result_a['pass']}, direct pass={passed_b}. "
            f"exec reasons={result_a.get('reasons', [])}, direct reasons={reasons_b}"
        )

        # Assert both pass (ref fix is known correct from L-1)
        assert result_a["pass"] is True, (
            f"exec_evaluate failed on reference fix for {case_id}: "
            f"{result_a.get('reasons', [])}"
        )
        assert (
            passed_b is True
        ), f"Direct harness failed on reference fix for {case_id}: {reasons_b}"

    @pytest.mark.parametrize("case_id", ["alias_config_a", "stale_cache_a"])
    def test_cross_check_buggy_code_both_fail(self, case_id):
        """Both paths must agree that buggy code fails."""
        case = _load_case(case_id)
        buggy_code = load_case_code(case)

        result_a = exec_evaluate(case, buggy_code)

        test_fn = _load_v2_test(case)
        asm = _assemble_program(buggy_code, case)
        mod = load_module_from_code(asm["code"], f"crosscheck_buggy_{case_id}")
        passed_b, _ = test_fn(mod)

        assert result_a["pass"] == passed_b, f"CROSS-CHECK DIVERGENCE on buggy code for {case_id}"
        assert result_a["pass"] is False


# ============================================================
# EVALUATOR ASSEMBLY CORRECTNESS
# ============================================================


class TestEvaluatorAssembly:
    """Verify assembly doesn't corrupt code for multi-file cases."""

    def test_multifile_assembly_preserves_definitions(self):
        """For a multi-file case, assembly must preserve all definitions."""
        case = _load_case("alias_config_b")
        ref_code = load_reference_code(case)
        asm = _assemble_program(ref_code, case)
        assert asm["assembly_used"] is True
        # The assembled code must contain create_config
        assert "create_config" in asm["code"]

    def test_singlefile_no_assembly(self):
        """Single-file cases should not use assembly."""
        case = _load_case("alias_config_a")
        ref_code = load_reference_code(case)
        asm = _assemble_program(ref_code, case)
        assert asm["assembly_used"] is False
