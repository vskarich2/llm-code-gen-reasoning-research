"""Subprocess-based evaluation for T3 benchmark.

Writes reconstructed files to a temp directory, generates a test harness,
runs the test in an isolated subprocess. No shared state, no import stripping,
no concatenation.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_log = logging.getLogger("t3.subprocess_eval")


def _find_case_package(file_paths: list[str]) -> str:
    """Extract the common parent directory name from file paths.

    All files in a case must share a single parent directory (validated at load time).
    Returns the leaf directory name, e.g., "hidden_dependency_hard".
    """
    parents = set(str(Path(f).parent) for f in file_paths)
    if len(parents) != 1:
        raise ValueError(
            f"Files span multiple directories: {parents}. "
            f"Benchmark requires all case files in a single directory."
        )
    return Path(next(iter(parents))).name


def _generate_harness(canonical_modules: list[str], test_fn_source: str,
                      test_function_name: str = "test") -> str:
    """Generate a test harness script that imports modules and runs the test.

    The harness:
    1. Imports each case module as a real Python module
    2. Builds a `mods` dict keyed by canonical module name
    3. Calls the specified test function with `mods`
    4. Prints JSON result to stdout
    """
    import_lines = "\n".join(
        f'    mods["{m}"] = importlib.import_module("{m}")'
        for m in canonical_modules
    )

    return f'''import importlib, sys, json, types

class _ModsDict(dict):
    """Dict that returns a dummy module for missing keys instead of raising KeyError.
    This allows tests to gracefully handle cases where a module does not exist
    at a given difficulty level (getattr on the dummy returns None)."""
    def __missing__(self, key):
        return types.ModuleType(f"_t3_missing_{{key}}")

mods = _ModsDict()
try:
{import_lines}
except Exception as e:
    print(json.dumps({{"pass": False, "reasons": [f"import error: {{e}}"], "error_type": "execution_error"}}))
    sys.exit(1)

{test_fn_source}

try:
    _t3_test_fn = {test_function_name}
    passed, reasons = _t3_test_fn(mods)
except Exception as e:
    passed = False
    reasons = [f"test harness crashed: {{e}}"]

print(json.dumps({{"pass": passed, "reasons": reasons, "error_type": "logic_pass" if passed else "logic_failure"}}))
sys.exit(0 if passed else 1)
'''


def evaluate_in_subprocess(
    case_id: str,
    file_paths: list[str],
    reconstructed_files: dict[str, str],
    test_fn_source: str,
    canonical_modules: list[str] | None = None,
    test_function_name: str = "test",
    timeout: int = 30,
) -> dict:
    """Run reconstructed code + test in an isolated subprocess.

    Args:
        case_id: case identifier for logging
        file_paths: ordered list of full relative paths
        reconstructed_files: rel_path -> content (from reconstructor)
        test_fn_source: source code of the test function (must define `test(mods)`)
        canonical_modules: list of module stems to import. If None, derived from file_paths.
        timeout: subprocess timeout in seconds

    Returns:
        dict with keys: pass, reasons, error_type, stdout, stderr
    """
    if canonical_modules is None:
        canonical_modules = sorted(Path(f).stem for f in file_paths)

    case_package = _find_case_package(file_paths)

    with tempfile.TemporaryDirectory(prefix=f"t3_{case_id}_") as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create case-local package directory
        pkg_root = tmpdir_path / case_package
        pkg_root.mkdir(parents=True, exist_ok=True)

        # Write each file to the package directory
        for rel_path, content in reconstructed_files.items():
            filename = Path(rel_path).name
            target = pkg_root / filename
            target.write_text(content, encoding="utf-8")

        # Generate and write test harness
        harness_code = _generate_harness(canonical_modules, test_fn_source, test_function_name)
        harness_path = pkg_root / "_t3_harness.py"
        harness_path.write_text(harness_code, encoding="utf-8")

        # Run in subprocess with PYTHONPATH = pkg_root
        env = {
            "PYTHONPATH": str(pkg_root),
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
        }

        try:
            result = subprocess.run(
                [sys.executable, str(harness_path)],
                cwd=str(pkg_root),
                env=env,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
        except subprocess.TimeoutExpired:
            _log.warning("TIMEOUT: case %s exceeded %ds", case_id, timeout)
            return {
                "pass": False,
                "reasons": [f"timeout after {timeout}s"],
                "error_type": "execution_error",
                "stdout": "",
                "stderr": "TimeoutExpired",
            }

        # Parse harness output
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stderr:
            _log.debug("subprocess stderr for %s: %s", case_id, stderr[:500])

        try:
            parsed = json.loads(stdout)
            return {
                "pass": parsed.get("pass", False),
                "reasons": parsed.get("reasons", []),
                "error_type": parsed.get("error_type", "logic_failure"),
                "stdout": stdout,
                "stderr": stderr,
            }
        except (json.JSONDecodeError, TypeError):
            # Harness didn't produce valid JSON -- execution error
            _log.warning(
                "HARNESS OUTPUT PARSE FAILED for %s: stdout=%r stderr=%r",
                case_id, stdout[:200], stderr[:200],
            )
            return {
                "pass": False,
                "reasons": [f"harness output not JSON: {stdout[:100]}",
                            f"stderr: {stderr[:200]}"],
                "error_type": "execution_error",
                "stdout": stdout,
                "stderr": stderr,
            }
