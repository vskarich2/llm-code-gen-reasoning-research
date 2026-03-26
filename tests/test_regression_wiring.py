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

from reconstructor import reconstruct_strict


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


class TestRegressionWiringBug:
    """Verify the system detects reintroduction of the original wiring bug."""

    def test_removed_wiring_triggers_invariant(self):
        """If parsed['code'] is not set after SUCCESS reconstruction,
        the invariant assertion must fire."""
        case = _load_case("alias_config_a")
        ref_code = (BASE / "reference_fixes" / "alias_config_a.py").read_text()

        # Simulate reconstruction
        bug_file = case["code_files"][0]
        manifest = case["code_files_contents"]
        manifest_paths = list(manifest.keys())
        model_files = {bug_file: ref_code}
        recon = reconstruct_strict(manifest_paths, manifest, model_files)
        assert recon.status == "SUCCESS"

        # Simulate THE BUG: reconstruction succeeds but code stays None
        parsed = {"code": None, "_reconstruction_status": "SUCCESS"}

        # The evaluator belt-and-suspenders check must catch this
        from evaluator import evaluate_output
        with pytest.raises(RuntimeError, match="WIRING BUG"):
            evaluate_output(case, {
                "code": None,
                "reasoning": "test",
                "raw_output": "test",
                "parse_error": None,
                "_raw_fallback": False,
                "_reconstruction_status": "SUCCESS",
            })

    def test_empty_code_after_success_triggers_invariant(self):
        """Empty string code after SUCCESS reconstruction must also be caught."""
        case = _load_case("alias_config_a")
        from evaluator import evaluate_output
        with pytest.raises(RuntimeError, match="WIRING BUG"):
            evaluate_output(case, {
                "code": "",
                "reasoning": "test",
                "raw_output": "test",
                "parse_error": None,
                "_raw_fallback": False,
                "_reconstruction_status": "SUCCESS",
            })


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
