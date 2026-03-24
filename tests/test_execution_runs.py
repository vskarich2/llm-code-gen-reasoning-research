"""Test that exec_eval actually executes code and detects pass/fail."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exec_eval import exec_evaluate, load_module_from_code, extract_code


def _dummy_case():
    return {
        "id": "_test_dummy",
        "failure_mode": "TEST",
        "code_files": [],
        "code_files_contents": {},
    }


def test_correct_code_loads():
    code = "def add(x): return x + 1"
    mod = load_module_from_code(code, "test_correct")
    assert mod.add(5) == 6


def test_broken_code_raises():
    code = "def add(x):\n  return x +"
    try:
        load_module_from_code(code, "test_broken")
        assert False, "should have raised SyntaxError"
    except SyntaxError:
        pass


def test_extract_code_from_fenced():
    text = "Here is the fix:\n```python\ndef f(): return 42\n```\nDone."
    code = extract_code(text)
    assert "def f():" in code
    assert "return 42" in code


def test_exec_evaluate_no_code():
    case = _dummy_case()
    result = exec_evaluate(case, "no code here")
    assert result["pass"] is False
    assert result["score"] == 0.0


def test_exec_evaluate_with_valid_code():
    """exec_evaluate with valid code for a real case that has a test function."""
    case = {
        "id": "easy_conservation",
        "failure_mode": "EASY_CONSERVATION",
        "code_files": [],
        "code_files_contents": {},
    }
    # Provide code that defines the expected functions
    output = 'def transfer(a, b, amount):\n    a["balance"] -= amount\n    b["balance"] += amount\ndef get_total(*accts):\n    return sum(a["balance"] for a in accts)'
    result = exec_evaluate(case, output)
    assert result["execution"]["ran"] is True


def test_exec_evaluate_syntax_error():
    case = _dummy_case()
    output = 'def broken(:'
    result = exec_evaluate(case, output)
    assert result["pass"] is False
    assert result["execution"]["syntax_error"] is not None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
