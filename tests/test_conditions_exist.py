"""Test that all conditions are registered and accessible."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS, COND_DESCRIPTIONS


def test_new_conditions_in_all_conditions():
    assert "counterfactual_check" in ALL_CONDITIONS
    assert "test_driven" in ALL_CONDITIONS
    assert "repair_loop" in ALL_CONDITIONS


def test_new_conditions_in_valid_set():
    assert "counterfactual_check" in VALID_CONDITIONS
    assert "test_driven" in VALID_CONDITIONS
    assert "repair_loop" in VALID_CONDITIONS


def test_labels_exist():
    assert "CC" == COND_LABELS["counterfactual_check"]
    assert "TD" == COND_LABELS["test_driven"]
    assert "RL" == COND_LABELS["repair_loop"]


def test_descriptions_exist():
    assert "counterfactual_check" in COND_DESCRIPTIONS
    assert "test_driven" in COND_DESCRIPTIONS
    assert "repair_loop" in COND_DESCRIPTIONS


def test_old_conditions_still_exist():
    for c in ["baseline", "diagnostic", "guardrail", "guardrail_strict",
              "counterfactual", "reason_then_act", "self_check"]:
        assert c in VALID_CONDITIONS, f"{c} missing"
        assert c in COND_LABELS, f"{c} missing label"


def test_operators_registered():
    from nudges.operators import get
    get("COUNTERFACTUAL_CHECK")  # should not raise
    get("TEST_DRIVEN")  # should not raise


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
