"""sys.modules isolation stress tests."""

import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from module_exec import run_module_execution


def _make_case(files, case_id="iso_test"):
    return {
        "id": case_id,
        "code_files": list(files.keys()),
        "code_files_contents": files,
        "failure_mode": "TEST",
        "reference_fix": {},
    }


def _pass_test(mod):
    return True, ["pass"]


# ISO-01: Repeated execution deterministic
class TestRepeatedExecution:
    def test_10_runs_same_result(self):
        case = _make_case({
            "metrics.py": "_c = 0\ndef inc(): global _c; _c += 1\ndef get(): return _c",
            "main.py": "from metrics import inc, get",
        })
        model = "from metrics import inc, get\ndef f():\n    inc(); inc()\n    return get()"

        def _test(mod):
            if hasattr(mod, "f"):
                return mod.f() == 2, [f"got {mod.f()}"]
            return False, ["no f"]

        results = [run_module_execution(case, model, _test) for _ in range(10)]
        passes = [r.test_passed for r in results]
        assert len(set(passes)) == 1, f"Non-deterministic: {passes}"


# ISO-03: Exact sys.modules key restoration
class TestSysModulesRestoration:
    def test_exact_key_restoration(self):
        case_mods = {"iso_mod_a", "iso_mod_b"}
        case = _make_case({
            "iso_mod_a.py": "X = 1",
            "iso_mod_b.py": "from iso_mod_a import X",
        }, case_id="iso_restore")
        model = "from iso_mod_a import X"

        # Snapshot before
        before_keys = set(sys.modules.keys())

        run_module_execution(case, model, _pass_test)

        # Snapshot after
        after_keys = set(sys.modules.keys())

        # No case-specific modules should remain
        remaining = case_mods & after_keys
        assert remaining == set(), f"Leaked modules: {remaining}"

        # No NEW unexpected modules
        new_keys = after_keys - before_keys
        # Filter out common transient modules (importlib internals)
        new_keys = {k for k in new_keys if not k.startswith("_")}
        assert new_keys == set(), f"New unexpected modules: {new_keys}"


# ISO-04: 20 consecutive runs, no growth
class TestNoGrowth:
    def test_consecutive_runs_no_growth(self):
        baseline = len(sys.modules)
        for i in range(20):
            case = _make_case({
                f"growth_mod_{i}.py": f"V = {i}",
                f"growth_main_{i}.py": f"from growth_mod_{i} import V",
            }, case_id=f"growth_{i}")
            model = f"from growth_mod_{i} import V"
            run_module_execution(case, model, _pass_test)

        final = len(sys.modules)
        # Allow small tolerance for Python internal caching
        assert final <= baseline + 3, f"sys.modules grew: {baseline} → {final}"


# ISO-02: No cross-case contamination
class TestNoCrossContamination:
    def test_state_not_shared(self):
        case_a = _make_case({
            "shared_name.py": "STATE = 'case_a'",
            "reader_a.py": "from shared_name import STATE",
        }, case_id="contam_a")

        case_b = _make_case({
            "shared_name.py": "STATE = 'case_b'",
            "reader_b.py": "from shared_name import STATE",
        }, case_id="contam_b")

        def _check_a(mod):
            return getattr(mod, "STATE", None) == "case_a", [f"STATE={getattr(mod, 'STATE', None)}"]

        def _check_b(mod):
            return getattr(mod, "STATE", None) == "case_b", [f"STATE={getattr(mod, 'STATE', None)}"]

        r_a = run_module_execution(case_a, "from shared_name import STATE", _check_a)
        r_b = run_module_execution(case_b, "from shared_name import STATE", _check_b)

        assert r_a.test_passed, f"Case A failed: {r_a.test_reasons}"
        assert r_b.test_passed, f"Case B failed: {r_b.test_reasons}"
