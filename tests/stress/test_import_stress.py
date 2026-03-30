"""Import resolution stress tests for dual execution system."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from module_exec import run_module_execution, ModuleExecResult
from code_assembly import assemble


def _make_case(files, ref_func=""):
    return {
        "id": "stress_test",
        "code_files": list(files.keys()),
        "code_files_contents": files,
        "failure_mode": "TEST",
        "reference_fix": {"function": ref_func} if ref_func else {},
    }


def _pass_test(mod):
    return True, ["pass"]


def _check_attr(name):
    def _test(mod):
        return hasattr(mod, name), [f"has {name}: {hasattr(mod, name)}"]
    return _test


# IMP-01: 3-level dependency chain
class TestDeepChain:
    def test_3_level_chain(self):
        case = _make_case({
            "d.py": "VALUE = 42",
            "c.py": "from d import VALUE\ndef get_c(): return VALUE",
            "b.py": "from c import get_c\ndef get_b(): return get_c()",
            "a.py": "from b import get_b\ndef get_a(): return get_b()",
        }, ref_func="get_a")
        model = "from b import get_b\ndef get_a(): return get_b()"

        def _test(mod):
            if hasattr(mod, "get_a"):
                return mod.get_a() == 42, [f"got {mod.get_a()}"]
            return False, ["no get_a"]

        r = run_module_execution(case, model, _test)
        # Module execution should handle this via 2-pass
        assert r.executed, f"Failed: {r.error_type}: {r.error_message}"

        # Compare with concat
        asm = assemble(model, case, mode="safe")
        # Concat may or may not succeed depending on assembly handling


# IMP-02: Circular imports
class TestCircularImports:
    def test_mutual_import(self):
        case = _make_case({
            "mod_x.py": "from mod_y import fy\ndef fx(): return fy() + 1",
            "mod_y.py": "def fy(): return 10",
        }, ref_func="fx")
        model = "from mod_y import fy\ndef fx(): return fy() + 1"

        def _test(mod):
            if hasattr(mod, "fx"):
                return mod.fx() == 11, [f"got {mod.fx()}"]
            return False, ["no fx"]

        r = run_module_execution(case, model, _test)
        assert r.executed


# IMP-03: Mixed import patterns
class TestMixedImports:
    def test_import_and_from_import(self):
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass\nCOUNTER = 0",
            "processor.py": "from metrics import increment",
        }, ref_func="process")
        model = "import metrics\nfrom metrics import increment\ndef process():\n    increment(1)\n    return metrics.COUNTER"

        r = run_module_execution(case, model, _pass_test)
        assert r.executed, f"Failed: {r.error_type}: {r.error_message}"


# IMP-05: Partial override
class TestPartialOverride:
    def test_model_modifies_one_of_three(self):
        case = _make_case({
            "config.py": "X = 1",
            "utils.py": "from config import X\ndef get(): return X",
            "main.py": "from utils import get\ndef run(): return get()",
        }, ref_func="run")
        # Model only modifies config.py
        model = "X = 99"

        def _test(mod):
            if hasattr(mod, "run"):
                val = mod.run()
                return val == 99, [f"got {val}"]
            if hasattr(mod, "get"):
                val = mod.get()
                return val == 99, [f"got {val} from get"]
            return False, ["no run or get"]

        r = run_module_execution(case, model, _test)
        assert r.executed


# IMP-07: Stdlib import inside function body
class TestStdlibInFunction:
    def test_import_json_in_function(self):
        case = _make_case({
            "a.py": "pass",
            "b.py": "pass",
        })
        model = "def f():\n    import json\n    return json.dumps({'x': 1})"

        def _test(mod):
            if hasattr(mod, "f"):
                return mod.f() == '{"x": 1}', [f"got {mod.f()}"]
            return False, ["no f"]

        r = run_module_execution(case, model, _test)
        assert r.executed
        assert r.test_passed

        asm = assemble(model, case, mode="safe")
        assert asm.status == "SUCCESS"
