#!/usr/bin/env python3
"""Run the test for a single benchmark case against its current code on disk.

Usage:
    .venv/bin/python scripts/test_case.py <case_id>
    .venv/bin/python scripts/test_case.py <case_id> --ref     # test the reference fix
    .venv/bin/python scripts/test_case.py --all                # test all cases
    .venv/bin/python scripts/test_case.py --all --ref          # test all reference fixes
    .venv/bin/python scripts/test_case.py --dir case_testing_gym/async_race_lock  # test case_testing_gym copy

Examples:
    .venv/bin/python scripts/test_case.py async_race_lock
    .venv/bin/python scripts/test_case.py stale_config_reload --ref
    .venv/bin/python scripts/test_case.py --dir case_testing_gym/stale_config_reload
    .venv/bin/python scripts/test_case.py --all
"""

import argparse
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT)
sys.path.insert(0, str(PROJECT))


_previous_imports = []


def load_module(file_paths, extra_fix=None):
    """Load case files via real imports, matching the canonical pipeline.

    Writes files to a temp directory, imports each as a real Python module
    via importlib, and merges all symbols into a single namespace.
    The extra_fix file is imported last so its definitions override.
    """
    # Clean up modules from the previous call so successive cases
    # don't see stale modules. Deferred to here (not after test)
    # because runtime imports inside function bodies need sys.modules
    # entries to survive until the test finishes.
    for name in _previous_imports:
        sys.modules.pop(name, None)
    _previous_imports.clear()

    tmp = tempfile.mkdtemp(prefix="t3_test_")
    try:
        (Path(tmp) / "__init__.py").write_text("")

        # Collect modules: code files sorted by basename, fix last
        modules = []
        for fp in sorted(file_paths, key=lambda p: os.path.basename(p)):
            basename = os.path.basename(fp)
            if basename == "__init__.py":
                continue
            shutil.copy2(fp, os.path.join(tmp, basename))
            modules.append(os.path.splitext(basename)[0])

        # Import code modules
        sys.path.insert(0, tmp)
        loaded = {}
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            loaded[mod_name] = mod
            _previous_imports.append(mod_name)

        # Import and apply reference fix
        if extra_fix:
            fix_basename = os.path.basename(extra_fix)
            shutil.copy2(extra_fix, os.path.join(tmp, fix_basename))
            fix_stem = os.path.splitext(fix_basename)[0]
            fix_mod = importlib.import_module(fix_stem)
            _previous_imports.append(fix_stem)

            # Patch fix-defined symbols into every code module that
            # references the same name. This ensures import-time
            # bindings (e.g. `from pipeline import process_batch` in
            # api.py) are updated to use the fixed version.
            fix_attrs = {
                k: v for k, v in vars(fix_mod).items()
                if not k.startswith("__")
            }
            for code_mod in loaded.values():
                for key, val in fix_attrs.items():
                    if key in vars(code_mod):
                        setattr(code_mod, key, val)
            loaded[fix_stem] = fix_mod
            modules.append(fix_stem)

        # Merge namespace — last writer wins (fix overrides originals)
        merged = types.ModuleType("case_module")
        merged.__dict__["__builtins__"] = __builtins__
        for mod_name in modules:
            if mod_name not in loaded:
                continue
            for key, val in vars(loaded[mod_name]).items():
                if key.startswith("__"):
                    continue
                merged.__dict__[key] = val

        return merged
    finally:
        # Remove temp dir from sys.path but keep modules in
        # sys.modules — runtime imports in function bodies need them.
        try:
            sys.path.remove(tmp)
        except ValueError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def run_case(case_entry, use_ref=False, override_dir=None):
    case_id = case_entry["id"]
    family = case_entry["family"]
    code_files = case_entry["code_files"]
    difficulty = case_entry.get("difficulty", "").lower()

    # Find test — use importlib.util to load from canonical path
    from core.config.paths import TESTS_V2_DIR
    test_path = TESTS_V2_DIR / f"test_{family}.py"
    if not test_path.exists():
        return "SKIP", f"no test file: {test_path}"
    spec = importlib.util.spec_from_file_location(f"test_{family}", test_path)
    test_mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(test_mod)
    except Exception as e:
        return "SKIP", f"test module load failed: {e}"

    # Try difficulty-specific test first, then generic
    test_fn = None
    for name in [f"test_{difficulty}", "test"]:
        test_fn = getattr(test_mod, name, None)
        if test_fn is not None:
            break

    if test_fn is None:
        return "SKIP", "no test function found"

    # Resolve file paths
    if override_dir:
        # Use .py files from the override directory
        override_path = Path(override_dir)
        file_paths = sorted(str(p) for p in override_path.glob("*.py"))
        if not file_paths:
            return "SKIP", f"no .py files in {override_dir}"
    else:
        file_paths = [str(PROJECT / "case_data" / fp) for fp in code_files]

    ref_fix = None
    if use_ref:
        from core.config.paths import REFERENCE_FIXES_DIR
        ref_path = REFERENCE_FIXES_DIR / f"{case_id}.py"
        if ref_path.exists():
            ref_fix = str(ref_path)
        else:
            return "SKIP", f"no reference fix: {ref_path.name}"

    # Check all files exist
    for fp in file_paths:
        if not os.path.exists(fp):
            return "SKIP", f"missing file: {fp}"

    # Load and test
    try:
        mod = load_module(file_paths, ref_fix)
        passed, reasons = test_fn(mod)
        status = "PASS" if passed else "FAIL"
        msg = reasons[0] if reasons else ""
        return status, msg
    except Exception as e:
        return "ERROR", f"{type(e).__name__}: {e}"


def resolve_case_from_dir(dir_path, cases):
    """Find the matching case entry for a case_testing_gym directory."""
    dir_path = Path(dir_path)

    # Try reading case_id from TASK.txt
    task_file = dir_path / "TASK.txt"
    if task_file.exists():
        for line in task_file.read_text().splitlines():
            if line.startswith("case_id:"):
                case_id = line.split(":", 1)[1].strip()
                for c in cases:
                    if c["id"] == case_id:
                        return c

    # Fall back to directory name
    case_id = dir_path.name
    for c in cases:
        if c["id"] == case_id:
            return c

    return None


def main():
    parser = argparse.ArgumentParser(description="Test a benchmark case")
    parser.add_argument("case_id", nargs="?", help="Case ID to test")
    parser.add_argument("--ref", action="store_true",
                        help="Test the reference fix instead of buggy code")
    parser.add_argument("--all", action="store_true", help="Test all cases")
    parser.add_argument("--dir", help="Test .py files from this directory instead of canonical code")
    args = parser.parse_args()

    if not args.case_id and not args.all and not args.dir:
        parser.print_help()
        sys.exit(1)

    with open(PROJECT / "cases_v2.json") as f:
        cases = json.load(f)

    # --dir mode: test a case_testing_gym directory
    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"Directory not found: {args.dir}")
            sys.exit(1)

        case_entry = resolve_case_from_dir(dir_path, cases)
        if case_entry is None:
            print(f"Could not match directory '{args.dir}' to a case in cases_v2.json")
            sys.exit(1)

        py_files = sorted(dir_path.glob("*.py"))
        print(f"  Testing: {case_entry['id']}")
        print(f"  Source:  {dir_path}/")
        print(f"  Files:   {', '.join(p.name for p in py_files)}")
        print()

        status, msg = run_case(case_entry, use_ref=args.ref, override_dir=str(dir_path))

        if status == "PASS":
            symbol = "\033[32m✓\033[0m"
        elif status == "FAIL":
            symbol = "\033[31m✗\033[0m"
        elif status == "ERROR":
            symbol = "\033[33m!\033[0m"
        else:
            symbol = "\033[90m-\033[0m"

        print(f"  {symbol} {status}: {msg}")
        sys.exit(0 if status == "PASS" else 1)

    # Normal mode
    if args.all:
        targets = cases
    else:
        targets = [c for c in cases if c["id"] == args.case_id]
        if not targets:
            print(f"Case '{args.case_id}' not found in cases_v2.json")
            sys.exit(1)

    passed_count = 0
    failed_count = 0
    skip_count = 0
    error_count = 0

    for case in targets:
        status, msg = run_case(case, use_ref=args.ref)
        case_id = case["id"]

        if status == "PASS":
            symbol = "\033[32m✓\033[0m"
            passed_count += 1
        elif status == "FAIL":
            symbol = "\033[31m✗\033[0m"
            failed_count += 1
        elif status == "ERROR":
            symbol = "\033[33m!\033[0m"
            error_count += 1
        else:
            symbol = "\033[90m-\033[0m"
            skip_count += 1

        short_msg = msg[:70] if msg else ""
        print(f"  {symbol} {case_id:<35} {status:<6} {short_msg}")

    if args.all:
        total = len(targets)
        print(f"\n  {passed_count} passed, {failed_count} failed, {error_count} errors, {skip_count} skipped / {total} total")
        if args.ref:
            if failed_count > 0:
                print(f"  WARNING: {failed_count} reference fixes do not pass their tests!")


if __name__ == "__main__":
    main()
