"""Shared test discovery infrastructure.

Extracted from exec_eval.py. Used by preflight_check.py and runner.py
for verifying every case has a resolvable test function.

These are pure utilities with no v1-specific semantics.
"""

import importlib
import importlib.util
import itertools
import sys
from pathlib import Path
from types import ModuleType

from core.config.paths import PROJECT_ROOT

_PROJECT_ROOT = PROJECT_ROOT

_load_counter = itertools.count(1)


def load_module_from_code(code: str, name: str = "candidate") -> ModuleType:
    """Load a string of Python code as a module.

    Import stripping is handled by CodeAssembler BEFORE this function.
    This function does NOT strip imports — it receives already-assembled code.
    Thread-safe: uses itertools.count() (atomic on CPython).
    """
    mod_name = f"_t3_exec_{name}_{next(_load_counter)}"

    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__builtins__"] = __builtins__

    try:
        exec(compile(code, f"<{mod_name}>", "exec"), mod.__dict__)  # noqa: S102
    except SyntaxError as e:
        raise SyntaxError(f"Candidate code syntax error: {e}") from e

    sys.modules[mod_name] = mod
    return mod


def _load_v2_test(case):
    """Dynamically load test from tests_v2/ for v2 cases.

    V2 tests are organized as tests_v2/test_{family}.py with
    test_a(mod), test_b(mod), test_c(mod), or test(mod) functions.

    Raises RuntimeError if test file exists but expected function is missing.
    Returns None only if no test file exists at all.
    """
    family = case.get("family")
    level = case.get("difficulty", "").lower()

    # V1 cases lack family/difficulty — try case_id as family with test() fallback
    if not family:
        family = case.get("id", "")
        level = ""
    if not family:
        return None

    from core.config.paths import TESTS_V2_DIR
    test_path = TESTS_V2_DIR / f"test_{family}.py"
    if not test_path.exists():
        return None

    spec = importlib.util.spec_from_file_location(f"_t3_v2_test_{family}", test_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Try difficulty-specific function first, then generic test()
    fn = None
    if level:
        fn = getattr(mod, f"test_{level}", None)
    if fn is None:
        fn = getattr(mod, "test", None)
    if fn is None:
        fn = getattr(mod, "test_a", None)
    if fn is None:
        raise RuntimeError(
            f"Test file {test_path} exists but has no usable test function. "
            f"Case: {case.get('id')}, family: {family}, difficulty: {level!r}. "
            f"Available functions: {[x for x in dir(mod) if x.startswith('test')]}"
        )
    return fn
