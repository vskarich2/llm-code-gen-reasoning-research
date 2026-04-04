#!/usr/bin/env python3
"""Minimal subprocess entry point for canonical execution.

Discovers and imports modules from disk, builds merged test namespace
with conflict detection and call-level tracing, runs test, emits
structured JSON to stdout.

No business logic. No classification. No retries. No logging beyond stdout JSON.
"""

import functools
import importlib
import json
import os
import sys
import time
import traceback
import types
from pathlib import Path


def main():
    result = {
        "status": "error",
        "passed": False,
        "failure_reasons": [],
        "error_type": None,
        "error_message": None,
        "traceback": None,
        "modules_loaded": [],
        "functions_detected": [],
        "functions_called": [],
        "merge_conflicts": [],
        "execution_trace": [],
        "execution_time_ms": 0,
    }

    try:
        t0 = time.monotonic()

        # ── 1. Read case_meta.json ───────────────────────────────
        meta = json.loads(Path("case_meta.json").read_text())
        case_id = meta["case_id"]
        family = meta["family"]
        difficulty = meta.get("difficulty", "a")
        project_root = meta["project_root"]

        result["execution_trace"].append(f"meta_loaded: {case_id}")

        # ── 2. Discover modules in pkg/ ──────────────────────────
        pkg_dir = Path("pkg")
        module_files = sorted([
            f.stem for f in pkg_dir.glob("*.py")
            if f.name != "__init__.py"
        ])
        result["execution_trace"].append(f"discovered: {module_files}")

        # ── 3. Import each module ────────────────────────────────
        loaded = {}
        for mod_name in module_files:
            try:
                mod = importlib.import_module(mod_name)
                loaded[mod_name] = mod
                result["modules_loaded"].append(mod_name)
                result["execution_trace"].append(f"import: {mod_name}")
            except SyntaxError as e:
                result["error_type"] = "SyntaxError"
                result["error_message"] = str(e)
                result["traceback"] = traceback.format_exc()
                result["execution_time_ms"] = int(
                    (time.monotonic() - t0) * 1000)
                print(json.dumps(result))
                return
            except (ImportError, ModuleNotFoundError) as e:
                result["error_type"] = type(e).__name__
                result["error_message"] = str(e)
                result["traceback"] = traceback.format_exc()
                result["execution_time_ms"] = int(
                    (time.monotonic() - t0) * 1000)
                print(json.dumps(result))
                return
            except NameError as e:
                result["error_type"] = "NameError"
                result["error_message"] = str(e)
                result["traceback"] = traceback.format_exc()
                result["execution_time_ms"] = int(
                    (time.monotonic() - t0) * 1000)
                print(json.dumps(result))
                return
            except Exception as e:
                result["error_type"] = type(e).__name__
                result["error_message"] = str(e)
                result["traceback"] = traceback.format_exc()
                result["execution_time_ms"] = int(
                    (time.monotonic() - t0) * 1000)
                print(json.dumps(result))
                return

        # ── 4. Build merged namespace with conflict detection ────
        merged = types.ModuleType("_t3_merged")
        merged.__dict__["__builtins__"] = __builtins__
        conflicts = []
        name_to_source = {}
        _calls_log = []

        for mod_name in module_files:
            if mod_name not in loaded:
                continue
            for key, val in vars(loaded[mod_name]).items():
                if key.startswith("__"):
                    continue
                if key in name_to_source:
                    conflicts.append(key)
                name_to_source[key] = mod_name
                # Wrap callables with tracer
                if callable(val):
                    def _make_tracer(fn_name, fn):
                        @functools.wraps(fn)
                        def traced(*args, **kwargs):
                            _calls_log.append(fn_name)
                            result["execution_trace"].append(
                                f"call: {fn_name}")
                            return fn(*args, **kwargs)
                        traced.__name__ = fn_name
                        traced.__qualname__ = fn_name
                        # Copy custom attributes (e.g. decorator-added
                        # methods like .get_history, .clear_history)
                        for attr in dir(fn):
                            if (not attr.startswith("__")
                                    and not hasattr(traced, attr)):
                                try:
                                    setattr(traced, attr,
                                            getattr(fn, attr))
                                except (AttributeError, TypeError):
                                    pass
                        return traced
                    merged.__dict__[key] = _make_tracer(key, val)
                else:
                    merged.__dict__[key] = val

        result["merge_conflicts"] = sorted(set(conflicts))
        result["functions_detected"] = sorted([
            k for k, v in merged.__dict__.items()
            if not k.startswith("__") and callable(v)
        ])
        n_callables = len(result["functions_detected"])
        n_conflicts = len(result["merge_conflicts"])
        result["execution_trace"].append(
            f"merged: {n_callables} callables, {n_conflicts} conflicts")

        # ── 5. Resolve test function ─────────────────────────────
        import importlib.util as _ilu

        tests_dir = os.path.join(project_root, "case_data", "tests_v2")
        test_path = os.path.join(tests_dir, f"test_{family}.py")

        if not os.path.exists(test_path):
            result["error_type"] = "TestResolutionError"
            result["error_message"] = f"Test file not found: {test_path}"
            result["execution_time_ms"] = int(
                (time.monotonic() - t0) * 1000)
            print(json.dumps(result))
            return

        spec = _ilu.spec_from_file_location(
            f"_t3_test_{family}", test_path)
        test_mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(test_mod)

        test_fn = None
        test_fn_name = None
        for func_name in [f"test_{difficulty}", "test", "test_a"]:
            fn = getattr(test_mod, func_name, None)
            if fn is not None:
                test_fn = fn
                test_fn_name = func_name
                break

        if test_fn is None:
            result["error_type"] = "TestResolutionError"
            result["error_message"] = (
                f"No test found for family={family}, "
                f"difficulty={difficulty}")
            result["execution_time_ms"] = int(
                (time.monotonic() - t0) * 1000)
            print(json.dumps(result))
            return

        result["execution_trace"].append(f"test_fn: {test_fn_name}")

        # ── 6. Run test ──────────────────────────────────────────
        result["execution_trace"].append("test_start")
        try:
            test_result = test_fn(merged)
            if isinstance(test_result, tuple) and len(test_result) >= 2:
                passed, reasons = test_result[0], test_result[1]
            else:
                passed = bool(test_result)
                reasons = []

            result["passed"] = bool(passed)
            result["failure_reasons"] = (
                reasons if isinstance(reasons, list) else [str(reasons)])
            result["status"] = "ok"
            result["execution_trace"].append(
                f"test_end: {'pass' if passed else 'fail'}")
        except Exception as e:
            result["error_type"] = type(e).__name__
            result["error_message"] = str(e)
            result["traceback"] = traceback.format_exc()
            result["execution_trace"].append(
                f"exception: {type(e).__name__}")

        # ── 7. Finalize ──────────────────────────────────────────
        result["functions_called"] = sorted(set(_calls_log))
        result["execution_time_ms"] = int(
            (time.monotonic() - t0) * 1000)

    except Exception as e:
        result["error_type"] = type(e).__name__
        result["error_message"] = str(e)
        result["traceback"] = traceback.format_exc()

    print(json.dumps(result))


if __name__ == "__main__":
    main()
