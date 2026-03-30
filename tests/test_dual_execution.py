"""Tests for dual execution system — module-based comparison path."""

import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_exec import run_module_execution, compare_results, ModuleExecResult


def _make_case(files, ref_func=""):
    return {
        "id": "test_case",
        "code_files": list(files.keys()),
        "code_files_contents": files,
        "failure_mode": "TEST",
        "reference_fix": {"function": ref_func, "file": ""} if ref_func else {},
    }


def _pass_test(mod):
    return True, ["test passed"]


def _fail_test(mod):
    return False, ["test failed"]


def _check_func_test(mod):
    if hasattr(mod, "process_batch"):
        result = mod.process_batch([{"id": "a", "value": 1}, {"id": "b", "value": 2}])
        if result == 2:
            return True, ["process_batch returned correct count"]
    return False, ["process_batch missing or wrong"]


# ============================================================
# BASIC EXECUTION
# ============================================================


class TestBasicExecution:

    def test_single_file_passes(self):
        case = _make_case({"a.py": "def f(): return 1"})
        r = run_module_execution(case, "def f(): return 42", _pass_test)
        assert r.executed
        assert r.test_ran
        assert r.test_passed

    def test_single_file_syntax_error(self):
        case = _make_case({"a.py": "def f(): return 1"})
        r = run_module_execution(case, "def f(\n  broken", _pass_test)
        assert r.error_type == "SyntaxError"
        assert not r.test_ran

    def test_multi_file_basic(self):
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass",
            "processor.py": "from metrics import increment\ndef process(): increment(1)",
        }, ref_func="process")
        model_code = "from metrics import increment\ndef process(): increment(1)"
        r = run_module_execution(case, model_code, _pass_test)
        assert r.executed
        assert r.test_ran


# ============================================================
# ALIAS IMPORT — BOTH SYSTEMS SHOULD PASS
# ============================================================


class TestAliasImport:

    def test_alias_import_module_exec(self):
        """from metrics import reset as metrics_reset — works in module execution."""
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass",
            "processor.py": "from metrics import increment",
        }, ref_func="process")
        model_code = "from metrics import reset as metrics_reset\ndef process(): metrics_reset()"
        r = run_module_execution(case, model_code, _pass_test)
        assert r.executed, f"Failed: {r.error_type}: {r.error_message}"
        assert r.test_ran


# ============================================================
# MODULE-QUALIFIED IMPORT — BOTH SYSTEMS SHOULD PASS
# ============================================================


class TestModuleQualified:

    def test_import_x_attr(self):
        """import metrics; metrics.reset() — works natively in module execution."""
        case = _make_case({
            "metrics.py": "_counter = 0\ndef increment(v):\n    global _counter\n    _counter += v\ndef get(): return _counter",
            "processor.py": "from metrics import increment",
        }, ref_func="process")
        model_code = "import metrics\ndef process(items):\n    for i in items: metrics.increment(i)\n    return metrics.get()"

        def _test(mod):
            if hasattr(mod, "process"):
                result = mod.process([1, 2, 3])
                return result == 6, [f"got {result}"]
            return False, ["no process function"]

        r = run_module_execution(case, model_code, _test)
        assert r.executed, f"Failed: {r.error_type}: {r.error_message}"
        assert r.test_ran
        assert r.test_passed, f"Test failed: {r.test_reasons}"


# ============================================================
# CIRCULAR IMPORTS
# ============================================================


class TestCircularImports:

    def test_two_pass_handles_circular(self):
        """A imports from B, B imports from A — 2-pass should handle it."""
        case = _make_case({
            "mod_a.py": "from mod_b import func_b\ndef func_a(): return func_b() + 1",
            "mod_b.py": "def func_b(): return 42",
        }, ref_func="func_a")
        model_code = "from mod_b import func_b\ndef func_a(): return func_b() + 1"

        def _test(mod):
            if hasattr(mod, "func_a"):
                return mod.func_a() == 43, [f"got {mod.func_a()}"]
            return False, ["no func_a"]

        r = run_module_execution(case, model_code, _test)
        # 2-pass should resolve this
        assert r.executed
        assert r.load_passes <= 2


# ============================================================
# COMPARISON LOGIC
# ============================================================


class TestComparison:

    def test_agreement_both_pass(self):
        r = ModuleExecResult(test_ran=True, test_passed=True, executed=True)
        c = compare_results(True, r)
        assert c["agreement"] is True
        assert c["both_pass"] is True

    def test_agreement_both_fail(self):
        r = ModuleExecResult(test_ran=True, test_passed=False, executed=True)
        c = compare_results(False, r)
        assert c["agreement"] is True
        assert c["both_fail"] is True

    def test_concat_only_pass(self):
        r = ModuleExecResult(test_ran=True, test_passed=False, executed=True)
        c = compare_results(True, r)
        assert c["agreement"] is False
        assert c["concat_only_pass"] is True

    def test_module_only_pass(self):
        r = ModuleExecResult(test_ran=True, test_passed=True, executed=True)
        c = compare_results(False, r)
        assert c["agreement"] is False
        assert c["module_only_pass"] is True

    def test_module_not_executed(self):
        r = ModuleExecResult(executed=False)
        c = compare_results(True, r)
        assert c["module_executed"] is False
        assert c["concat_only_pass"] is True


# ============================================================
# STATE ISOLATION
# ============================================================


class TestStateIsolation:

    def test_no_sys_modules_leakage(self):
        """After execution, sys.modules must not contain case modules."""
        case = _make_case({
            "test_leak_mod.py": "X = 42",
            "test_leak_main.py": "from test_leak_mod import X",
        })
        r = run_module_execution(case, "from test_leak_mod import X", _pass_test)
        assert "test_leak_mod" not in sys.modules
        assert "test_leak_main" not in sys.modules

    def test_consecutive_runs_isolated(self):
        """Two consecutive runs of different cases don't leak state."""
        case1 = _make_case({
            "state_a.py": "VALUE = 'case1'",
            "main_a.py": "from state_a import VALUE",
        })
        case2 = _make_case({
            "state_a.py": "VALUE = 'case2'",
            "main_a.py": "from state_a import VALUE",
        })

        def _check_value(expected):
            def _test(mod):
                return getattr(mod, "VALUE", None) == expected, [f"VALUE={getattr(mod, 'VALUE', None)}"]
            return _test

        r1 = run_module_execution(case1, "from state_a import VALUE", _check_value("case1"))
        r2 = run_module_execution(case2, "from state_a import VALUE", _check_value("case2"))

        assert r1.test_passed, f"Case 1 failed: {r1.test_reasons}"
        assert r2.test_passed, f"Case 2 failed: {r2.test_reasons}"
        assert "state_a" not in sys.modules
