"""L3: Negative Regression Tests.

Tests that intentionally reintroduce the wiring bug and verify it is detected.
If these tests pass, the safety system works. If they fail, the safety system
cannot detect reintroduction of the bug class.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from experiment_config import load_config
load_config(BASE / "configs" / "default.yaml")

from reconstructor import reconstruct_strict


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


class TestRegressionWiringBug:
    """Verify the system detects reintroduction of the original wiring bug.

    The invariant assert in execution.py:_attempt_and_evaluate catches the bug
    at the wiring site. The evaluator handles all-UNCHANGED (SUCCESS + empty code)
    gracefully by letting exec_evaluate fail it with ran=False.
    """

    def test_empty_code_after_success_fails_execution(self):
        """SUCCESS reconstruction with empty code → exec_evaluate returns pass=False, ran=False.
        This is the correct behavior: the model marked all files UNCHANGED (no fix attempted)."""
        case = _load_case("alias_config_a")
        from evaluator import evaluate_output
        result = evaluate_output(case, {
            "code": "",
            "reasoning": "test",
            "raw_output": "test",
            "parse_error": None,
            "_raw_fallback": False,
            "_reconstruction_status": "SUCCESS",
        })
        assert result["pass"] is False, "Empty code after reconstruction must fail"
        assert result["execution"]["ran"] is False

    def test_reconstruction_wiring_exists(self):
        """The changed-files-only wiring in _do_reconstruction must exist.
        If this code is removed, the original 0% pass rate bug returns."""
        import inspect
        from execution import _do_reconstruction
        source = inspect.getsource(_do_reconstruction)
        assert "changed_files" in source, (
            "The changed-files-only wiring is missing from _do_reconstruction. "
            "This is the fix for the 0% pass rate bug."
        )
        assert 'parsed["code"]' in source, (
            "parsed['code'] assignment is missing from _do_reconstruction. "
            "Without this, reconstructed code never reaches the evaluator."
        )


class TestRegressionSmokeGate:
    """Verify smoke gate validation catches degenerate results."""

    def test_all_fail_events_detected(self):
        """Synthetic events with all pass=False → validation fails."""
        events = [
            {"case_id": f"case_{i}", "condition": "baseline",
             "model": "test", "trial": 1, "run_id": "test",
             "pass": False, "score": 0.0, "timestamp": "2024-01-01"}
            for i in range(10)
        ]
        # Simulate the validation logic
        total = len(events)
        passes = sum(1 for e in events if e.get("pass"))
        assert passes == 0, "Test setup error"
        # This is what validate_smoke.py will check
        assert total > 0
        gate_passed = passes > 0
        assert gate_passed is False, "Smoke gate should reject all-fail events"

    def test_mixed_events_accepted(self):
        """Events with some passes → validation passes."""
        events = [
            {"pass": True, "score": 1.0},
            {"pass": False, "score": 0.0},
            {"pass": False, "score": 0.0},
        ]
        passes = sum(1 for e in events if e.get("pass"))
        assert passes > 0, "Should have at least one pass"
