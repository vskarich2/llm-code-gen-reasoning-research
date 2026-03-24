"""Test that new conditions modify prompts correctly."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nudges.router import apply_counterfactual_check, apply_test_driven

BASE = "Refactor this code. Return updated code."


def test_counterfactual_check_appends():
    result = apply_counterfactual_check("hidden_dep_multihop", BASE)
    assert len(result) > len(BASE)
    assert BASE in result
    assert "Identify at least two realistic ways your implementation could fail" in result


def test_counterfactual_check_failure_analysis():
    result = apply_counterfactual_check("unknown_case", BASE)
    assert "runtime scenario" in result.lower() or "failure mode" in result.lower()


def test_test_driven_appends():
    result = apply_test_driven("hidden_dep_multihop", BASE)
    assert len(result) > len(BASE)
    assert BASE in result
    assert "Your implementation MUST satisfy the following behavioral requirements" in result


def test_test_driven_invariants():
    result = apply_test_driven("unknown_case", BASE)
    assert "invariant" in result.lower()
    assert "side effects" in result.lower() or "error paths" in result.lower()


def test_original_conditions_unchanged():
    from nudges.router import apply_diagnostic, apply_guardrail
    dx = apply_diagnostic("hidden_dep_multihop", BASE)
    gr = apply_guardrail("hidden_dep_multihop", BASE)
    # These should still modify the prompt (not return base unchanged)
    assert len(dx) > len(BASE)
    assert len(gr) > len(BASE)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
