
import logging
import sys
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("t3.module_exec")


@dataclass
class ModuleExecResult:
    """Result of module-based execution attempt."""
    executed: bool = False         # Did execution attempt complete?
    test_ran: bool = False         # Did the test function run?
    test_passed: bool = False      # Did the test pass?
    test_reasons: list = field(default_factory=list)
    error_type: str = ""           # Exception class name (empty if no error)
    error_message: str = ""        # Exception message
    error_traceback: str = ""      # Full traceback
    modules_loaded: list = field(default_factory=list)
    load_passes: int = 0           # Number of exec passes needed
    cleanup_done: bool = False


def run_module_execution(case: dict, model_code: str, test_fn) -> ModuleExecResult:
    """Execute model code as real Python modules and run the test function.

    Args:
        case: benchmark case dict with code_files, code_files_contents
        model_code: the model's extracted code (may be single file or concatenated changed files)
        test_fn: the invariant test function to run

    Returns:
        ModuleExecResult with execution outcome (NEVER affects canonical results).
    """
    result = ModuleExecResult()
    code_contents = case.get("code_files_contents", {})
    code_files = case.get("code_files", [])

    if not code_contents or len(code_contents) <= 1:
        # Single-file case: no module system needed, just exec directly
        return _exec_single_file(model_code, case.get("id", "?"), test_fn, result)

    # Multi-file case: real module execution
    return _exec_multi_file(model_code, case, code_files, code_contents, test_fn, result)


def _exec_single_file(model_code, case_id, test_fn, result):
    """Single-file execution — direct exec, no module infrastructure."""
    mod = types.ModuleType(f"_t3_modexec_{case_id}")
    mod.__dict__["__builtins__"] = __builtins__
    try:
        exec(compile(model_code, f"<modexec_{case_id}>", "exec"), mod.__dict__)
        result.executed = True
        result.modules_loaded = [case_id]
    except Exception as e:
        result.error_type = type(e).__name__
        result.error_message = str(e)
        result.error_traceback = traceback.format_exc()
        return result

    return _run_test(mod, test_fn, result)


def _exec_multi_file(model_code, case, code_files, code_contents, test_fn, result):
    """Multi-file module execution with 2-pass loading."""
    case_id = case.get("id", "?")
    reference_fix = case.get("reference_fix", {})
    bug_file = reference_fix.get("file", "")
    target_func = reference_fix.get("function", "")

    # Build module map: module_name → (code, is_model_override)
    module_map = {}
    module_names = []
    for rel_path in code_files:
        mod_name = rel_path.rsplit("/", 1)[-1].replace(".py", "")
        original = code_contents.get(rel_path, "")
        module_map[mod_name] = original
        module_names.append(mod_name)

    # Determine which module the model is overriding
    # The model_code typically contains the fix for one specific file.
    # We detect which module it overrides by checking which functions it defines
    # that also exist in original modules.
    import re
    model_defs = set(re.findall(r"^(?:def|class)\s+(\w+)", model_code, re.MULTILINE))

    # Find the best matching module to override
    override_module = None
    if bug_file:
        override_module = bug_file.rsplit("/", 1)[-1].replace(".py", "")
    elif target_func:
        for mod_name, code in module_map.items():
            original_defs = set(re.findall(r"^(?:def|class)\s+(\w+)", code, re.MULTILINE))
            if target_func in original_defs and target_func in model_defs:
                override_module = mod_name
                break

    if override_module and override_module in module_map:
        module_map[override_module] = model_code
    else:
        # Can't determine which module to override — append model code to last module
        # or create a synthetic module
        if module_names:
            module_map[module_names[-1]] = model_code

    # ── Step 1: Clean sys.modules ──
    saved_modules = {}
    for mod_name in module_names:
        if mod_name in sys.modules:
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    try:
        # ── Step 2: Create empty module shells ──
        modules = {}
        for mod_name in module_names:
            mod = types.ModuleType(mod_name)
            mod.__file__ = f"<modexec_{case_id}/{mod_name}>"
            mod.__dict__["__builtins__"] = __builtins__
            sys.modules[mod_name] = mod
            modules[mod_name] = mod

        # ── Step 3: Two-pass execution ──
        for pass_num in range(1, 3):
            all_ok = True
            for mod_name in module_names:
                code = module_map[mod_name]
                try:
                    exec(compile(code, f"<modexec_{case_id}/{mod_name}>", "exec"),
                         modules[mod_name].__dict__)
                except (ImportError, NameError, AttributeError):
                    all_ok = False
                except SyntaxError as e:
                    result.error_type = "SyntaxError"
                    result.error_message = str(e)
                    result.error_traceback = traceback.format_exc()
                    return result
                except Exception as e:
                    if pass_num == 2:
                        result.error_type = type(e).__name__
                        result.error_message = str(e)
                        result.error_traceback = traceback.format_exc()
                        return result
                    all_ok = False

            result.load_passes = pass_num
            if all_ok:
                break

        result.executed = True
        result.modules_loaded = module_names

        # ── Step 4: Find the module to test ──
        # The test function expects a module with the target function
        if target_func:
            test_mod = None
            for mod_name in module_names:
                if hasattr(modules[mod_name], target_func):
                    test_mod = modules[mod_name]
                    break
            if test_mod is None:
                # Try the override module
                test_mod = modules.get(override_module, modules[module_names[-1]])
        else:
            # Default: test against the last module (likely the main one)
            test_mod = modules[module_names[-1]]

        # Inject all module symbols into test_mod for test compatibility
        # (test functions may expect all symbols in one namespace)
        merged_mod = types.ModuleType(f"_t3_modexec_merged_{case_id}")
        merged_mod.__dict__["__builtins__"] = __builtins__
        for mod_name in module_names:
            for k, v in modules[mod_name].__dict__.items():
                if not k.startswith("__"):
                    merged_mod.__dict__[k] = v

        return _run_test(merged_mod, test_fn, result)

    except Exception as e:
        result.error_type = type(e).__name__
        result.error_message = str(e)
        result.error_traceback = traceback.format_exc()
        return result

    finally:
        # ── Step 5: Cleanup sys.modules ──
        for mod_name in module_names:
            sys.modules.pop(mod_name, None)
        # Restore any saved modules
        for mod_name, mod in saved_modules.items():
            sys.modules[mod_name] = mod
        result.cleanup_done = True


def _run_test(mod, test_fn, result):
    """Run the test function on a module and record results."""
    try:
        result.test_ran = True
        passed, reasons = test_fn(mod)
        result.test_passed = passed
        result.test_reasons = reasons if isinstance(reasons, list) else [str(reasons)]
    except Exception as e:
        result.error_type = type(e).__name__
        result.error_message = f"test crashed: {e}"
        result.error_traceback = traceback.format_exc()
    return result


def compare_results(concat_pass: bool, module_result: ModuleExecResult) -> dict:
    """Compare concatenation and module execution results."""
    module_pass = module_result.test_passed if module_result.test_ran else False

    return {
        "agreement": concat_pass == module_pass,
        "both_pass": concat_pass and module_pass,
        "both_fail": not concat_pass and not module_pass,
        "concat_only_pass": concat_pass and not module_pass,
        "module_only_pass": not concat_pass and module_pass,
        "module_executed": module_result.executed,
        "module_test_ran": module_result.test_ran,
        "module_error_type": module_result.error_type,
        "module_error_message": module_result.error_message if module_result.error_message else "",
        "module_load_passes": module_result.load_passes,
    }
