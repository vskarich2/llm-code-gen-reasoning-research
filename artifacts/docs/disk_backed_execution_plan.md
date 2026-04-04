# Disk-Backed Execution System: Implementation Plan

## 1. System Architecture

```
execution_v2.py:run_v2()
  │
  ├── reconstructor.py:reconstruct_strict()
  │     input: manifest_paths, manifest_files, parsed_gen.files_dict
  │     output: ReconstructionResult with files dict + changed_files set
  │
  ├── package_builder.py:build_eval_package()            [NEW]
  │     input: case dict + recon.files + recon.changed_files + project_root
  │     output: temp directory path containing real Python package
  │
  │     temp_dir/
  │       pkg/
  │         __init__.py          (empty, makes pkg importable)
  │         metrics.py           (original OR model-replaced)
  │         processor.py         (original OR model-replaced)
  │       harness.py             (test harness entry point)
  │       case_meta.json         (case_id, family, difficulty, project_root)
  │
  ├── subprocess_runner.py:run_eval_subprocess()         [NEW]
  │     input: temp directory path, timeout
  │     spawns: .venv/bin/python {temp_dir}/harness.py
  │     env: PYTHONPATH={temp_dir}/pkg:{project_root}
  │     cwd: temp_dir
  │     output: parsed JSON from subprocess stdout
  │
  ├── adapter.py:adapt_result()                          [NEW]
  │     input: subprocess JSON result + case dict
  │     output: dict matching exec_evaluate() contract exactly
  │
  └── [existing pipeline continues: classify, metrics, assemble, log]
```

### Boundaries

- **package_builder** touches filesystem only. No code execution.
- **subprocess_runner** spawns a process only. No filesystem creation. No result
  interpretation beyond JSON parsing.
- **harness.py** runs inside the subprocess only. Completely isolated from the
  parent process. No shared memory, no sys.modules leakage.
- **adapter** is pure data transformation. No I/O, no execution.

---

## 2. File Responsibilities

### package_builder.py

**Inputs:**
- `case` dict (with `code_files`, `code_files_contents`)
- `model_files` dict (`{rel_path: code_string}` from reconstruct_strict)
- `changed_files` set (which files the model modified)
- `project_root` string (absolute path for test function access)

**Outputs:** Path to temp directory.

**Responsibilities:**
- Create temp directory via `tempfile.mkdtemp(prefix="t3_eval_")`
- Create `pkg/` subdirectory with empty `__init__.py`
- For each file in `case["code_files"]`:
  - Extract module name from path: `metrics.py` from `code_snippets_v2/effect_order_b/metrics.py`
  - If file is in `changed_files`: write model's version from `model_files`
  - Else: write original from `case["code_files_contents"]`
  - Destination: `temp_dir/pkg/{module_name}`
- Write `case_meta.json` with case_id, family, difficulty, project_root
- Copy harness.py template into temp_dir root

**Constraints:**
- Must create valid Python package (importable via bare module names)
- File names must match original module names exactly
- No import rewriting. No AST manipulation. No renaming. Ever.
- Must handle the case where model_files is empty (all UNCHANGED)

### subprocess_runner.py

**Inputs:**
- `temp_dir` Path (from package_builder)
- `timeout` float (seconds, default 30)

**Outputs:** Dict parsed from subprocess stdout JSON.

**Responsibilities:**
- Read `case_meta.json` from temp_dir to get `project_root`
- Construct PYTHONPATH: `{temp_dir}/pkg:{project_root}`
  - `temp_dir/pkg` so bare imports (`from metrics import X`) resolve
  - `project_root` so `from tests_v2.test_X import test_Y` resolves
- Construct command: `[sys.executable, str(temp_dir / "harness.py")]`
- Set cwd: `temp_dir`
- Spawn via `subprocess.run()` with `capture_output=True`, `text=True`, `timeout=timeout`
- On success: parse stdout as JSON, return dict
- On `TimeoutExpired`: return `{"error": "timeout", "timeout_seconds": timeout}`
- On non-zero exit: return `{"error": "crash", "exit_code": N, "stderr": stderr[-500:]}`
- On JSON parse failure: return `{"error": "invalid_output", "stdout": stdout[-500:]}`

**Constraints:**
- Must NOT import or execute any model code in the parent process
- Must enforce timeout strictly
- Must capture stderr for debugging but never treat it as result data

### harness.py

This file is a template that gets copied into each temp_dir. It is the entry
point for the subprocess.

**Inputs:** Reads `case_meta.json` from cwd. Imports modules from PYTHONPATH.

**Outputs:** Single JSON object to stdout. Nothing else on stdout.

**Responsibilities:**
1. Read `case_meta.json` → get case_id, family, difficulty, project_root
2. Add project_root to sys.path (for test function access)
3. Resolve test function:
   - Try: `from tests_v2.test_{family} import test_{difficulty}`
   - Fallback: `from tests_v2.test_{family} import test`
   - Fallback: `from tests_v2.test_{family} import test_a`
4. Discover all .py files in pkg/ (excluding __init__.py)
5. Import each as a real Python module via `importlib.import_module(name)`
6. Build merged namespace module:
   - `merged = types.ModuleType("merged")`
   - For each imported module: copy all non-dunder attributes into merged
7. Call `test_fn(merged)` → `(passed: bool, reasons: list[str])`
8. Emit JSON result to stdout
9. On ANY exception: emit error JSON with type, message, traceback
10. Always exit 0 (result is in JSON, not exit code)

**Why merged namespace:** The existing test functions expect all symbols in one
module object. They call `mod.reset()`, `mod.process_batch()`, `mod.get_counter()`
— functions from different source files. The merged namespace provides this view
WITHOUT flattening execution. Each file executes in its own real module with real
imports. The merge happens AFTER execution, for test access only.

### adapter.py

**Inputs:** Raw JSON dict from subprocess, case dict, extracted code string.

**Outputs:** Dict matching `exec_evaluate()` return format exactly.

**Responsibilities:**
- Map `subprocess.passed` → `result["pass"]`
- Compute score:
  - No code / build failure: 0.0
  - Import/syntax error: 0.0
  - Test crash (exception): 0.1
  - Test logic failure: 0.2
  - Timeout: 0.0
  - Test passed: 1.0
- Build `result["reasons"]` from subprocess reasons + error info
- Build `result["execution"]` sub-dict with all required fields
- Set assembly fields to benign defaults (assembly_used=False, assembly_error=False, etc.)
- Include `_extracted_code` and `_assembled_code` for debugging

**Constraints:**
- Output must be indistinguishable from exec_evaluate output for ALL downstream consumers
- All existing exec_evaluate fields must be present
- Score ladder must match existing behavior

---

## 3. Execution Flow (Step-by-step)

1. `run_v2()` calls `reconstruct_strict(manifest_paths, manifest_files, parsed_gen.files_dict)`
   → Returns `ReconstructionResult` with `files` dict and `changed_files` set.

2. `run_v2()` calls `build_eval_package(case, recon.files, recon.changed_files, project_root)`:
   - Creates `temp_dir/pkg/` with `__init__.py`
   - For each case file: writes original or model version to `pkg/{module}.py`
   - Writes `case_meta.json`
   - Copies `harness.py`
   - Returns `temp_dir`

3. `run_v2()` calls `run_eval_subprocess(temp_dir, timeout=30)`:
   - Reads case_meta.json for project_root
   - Sets PYTHONPATH = `temp_dir/pkg:project_root`
   - Spawns: `.venv/bin/python harness.py`
   - Captures stdout/stderr
   - Parses stdout JSON
   - Returns result dict

4. `run_v2()` calls `adapt_result(subprocess_result, case, extracted_code)`:
   - Maps to exec_evaluate format
   - Computes score
   - Returns compatible dict

5. `run_v2()` calls `cleanup_package(temp_dir)` (or defers if debug flag set)

6. Pipeline continues with result dict through stages 6-9 (classify, metrics,
   assemble, log) — completely unchanged.

---

## 4. Package Construction Semantics

### Directory structure example

For case `effect_order_b` (2 files: metrics.py, processor.py), where model
modified processor.py:

```
/tmp/t3_eval_XXXXXXXX/
  pkg/
    __init__.py              (empty)
    metrics.py               (ORIGINAL from case — model didn't change it)
    processor.py             (MODEL'S VERSION — model changed this file)
  harness.py                 (test harness template)
  case_meta.json             ({"case_id": "effect_order_b", ...})
```

### File placement rules

- Module names derived from filename only: `code_snippets_v2/effect_order_b/processor.py` → `processor.py`
- All files go in `pkg/` as flat siblings (no case currently uses nested dirs)
- `__init__.py` is always empty (makes `pkg` a package, nothing more)
- Original files come from `case["code_files_contents"]`
- Model files come from `recon.files` where `rel_path in recon.changed_files`
- Files NOT in `changed_files` get the original version (model said UNCHANGED)

### Import resolution after construction

The source files contain bare imports like `from metrics import increment`.
Setting PYTHONPATH to include `temp_dir/pkg/` means these resolve to the
on-disk files. No rewriting needed. Python's standard import machinery handles
everything.

If model replaces `processor.py` and it contains `from metrics import increment`,
Python imports `metrics.py` from `pkg/` — which is the ORIGINAL file. Correct.

If model replaces `config.py` and it contains `DEFAULTS = {...}` at module level
followed by `def create_config(): ...`, then `from config import DEFAULTS` in
another file resolves correctly because `config.py` is on disk with DEFAULTS
defined.

---

## 5. Subprocess Design

### Invocation

```python
cmd = [sys.executable, str(temp_dir / "harness.py")]
env = os.environ.copy()
env["PYTHONPATH"] = f"{temp_dir / 'pkg'}{os.pathsep}{project_root}"
result = subprocess.run(
    cmd,
    capture_output=True,
    timeout=timeout,
    cwd=str(temp_dir),
    env=env,
    text=True,
)
```

### Working directory

`temp_dir` (harness.py is at this level, reads case_meta.json from here).

### PYTHONPATH

Two entries, separated by `os.pathsep`:
1. `temp_dir/pkg` — so `from metrics import X` resolves to pkg/metrics.py
2. `project_root` — so `from tests_v2.test_aliasing import test_a` resolves

### Timeout

Default 30 seconds. Configurable via parameter. `subprocess.TimeoutExpired`
caught and converted to structured error.

### Communication protocol

- **Stdout:** Exactly one JSON object followed by newline. Harness prints nothing
  else to stdout.
- **Stderr:** Free-form (Python tracebacks, warnings). Captured, stored for debug,
  never parsed as result.
- **Exit code:** 0 on normal completion (pass or fail). Non-zero only on unhandled
  crash in harness itself.

---

## 6. Harness Execution Model

Inside the subprocess:

```
Step 1: Read case_meta.json
  → case_id, family, difficulty, project_root

Step 2: Configure sys.path
  → Add project_root (for tests_v2 access)
  → pkg/ is already on PYTHONPATH from env

Step 3: Resolve test function
  → Import from tests_v2.test_{family}
  → Try test_{difficulty}, then test, then test_a
  → If not found: emit error JSON, exit

Step 4: Discover pkg modules
  → List pkg/*.py, exclude __init__.py
  → Sort alphabetically (deterministic order)

Step 5: Import each module
  → importlib.import_module(module_name)
  → Each module gets its own real namespace
  → Cross-module imports resolve via PYTHONPATH to on-disk files
  → No 2-pass loading needed (Python handles circular imports natively)

Step 6: Build merged namespace
  → merged = types.ModuleType("_t3_merged")
  → For each module, copy non-dunder attrs into merged.__dict__
  → Last module wins on name conflicts (same as concat path's last-def-wins)

Step 7: Run test
  → passed, reasons = test_fn(merged)

Step 8: Emit JSON
  → {"passed": bool, "reasons": [...], "error": null, ...}

On exception at any step:
  → {"passed": false, "reasons": [], "error": "TypeName", "message": "...", "traceback": "..."}
```

---

## 7. Result Format + Adapter

### Subprocess result schema

```json
{
  "passed": true,
  "reasons": ["all invariants satisfied"],
  "error": null,
  "error_message": null,
  "error_traceback": null,
  "modules_loaded": ["metrics", "processor"],
  "execution_time_ms": 45
}
```

### Adapter mapping to exec_evaluate format

```
subprocess.passed           → result["pass"]
subprocess.reasons          → result["reasons"]
subprocess.error == null    → result["execution"]["ran"] = true
subprocess.error != null    → depends on error type (see scoring)
subprocess.modules_loaded   → result["execution"]["assembly_sources"]

Score computation:
  error == "timeout"                         → 0.0
  error == "crash"                           → 0.0
  error == "SyntaxError"                     → 0.0
  error == "ImportError" or "ModuleNotFound" → 0.0
  error == "NameError"                       → 0.0
  error is other exception type              → 0.1
  passed == false (test logic failure)       → 0.2
  passed == true                             → 1.0

Backward-compat fields (always set):
  assembly_used = False
  assembly_error = False
  assembly_risky = False
  rename_error = False
  assembly_sources = {"subprocess": True}
```

---

## 8. Isolation Guarantees

- **No sys.modules leakage:** Subprocess is a separate Python process. Its
  sys.modules die with the process.
- **No cross-run contamination:** New temp directory + new subprocess per
  evaluation. Zero shared state.
- **No parent process pollution:** Model code never executes in the runner
  process. Only the subprocess loads it.
- **Deterministic execution:** Same files on disk → same Python import
  resolution → same execution. No dependency on prior runs, no in-memory
  state.
- **Filesystem cleanup:** `shutil.rmtree(temp_dir)` after result captured.
  Optional `--keep-eval-dirs` flag for debugging.

---

## 9. Failure Modes

| Failure | How detected | Result |
|---|---|---|
| Model code syntax error | Python SyntaxError on import in subprocess | error="SyntaxError", score=0.0 |
| Missing module import | Python ImportError in subprocess | error="ImportError", score=0.0 |
| Runtime error during module load | Exception during import | error="{type}", score=0.0 |
| Undefined name in model code | NameError during import or test | error="NameError", score=0.0 |
| Test function crashes | Exception during test_fn() | error="{type}", score=0.1 |
| Test function returns False | Normal return, passed=False | score=0.2 |
| Subprocess timeout | subprocess.TimeoutExpired in runner | error="timeout", score=0.0 |
| Harness can't find test function | ImportError in harness step 3 | error="test_not_found", score=0.0 |
| case_meta.json missing/corrupt | FileNotFoundError/JSONDecodeError in harness | error="metadata_error", score=0.0 |
| Harness emits invalid JSON | json.JSONDecodeError in runner | error="invalid_output", score=0.0 |
| Temp dir creation fails | OSError in package_builder | Exception propagates to caller |
| Model output has no code | Caught before package_builder (existing check in run_v2) | score=0.0 |
| Infinite recursion in model code | RecursionError in subprocess | error="RecursionError", score=0.1 |

---

## 10. Migration Strategy

### What gets replaced

`exec_eval.py:exec_evaluate()` is NOT modified. A new function
`exec_evaluate_subprocess()` is created that calls
package_builder → subprocess_runner → adapter. The call site in
`execution_v2.py:run_v2()` switches between them based on a config flag.

### What remains untouched

- `reconstructor.py` — still extracts per-file code from model JSON
- `execution_v2.py` — still orchestrates stages 1-9, only the exec call changes
- `parser_v2.py`, `evaluator_v2.py`, `metrics_v2.py` — unchanged
- `logging_core.py`, `parallel_runner.py`, `merge_run.py` — unchanged
- All test functions in `tests_v2/` — unchanged
- `code_assembly.py` — kept but no longer on hot path when flag is set
- `exec_eval.py:exec_evaluate()` — kept for comparison and fallback

### Integration point

In `execution_v2.py:run_v2()`, current code:

```python
exec_result = exec_evaluate(case, code)
```

Becomes:

```python
if config.execution.use_subprocess_eval:
    exec_result = exec_evaluate_subprocess(case, recon)
else:
    exec_result = exec_evaluate(case, code)
```

### Config flag

```yaml
execution:
  use_subprocess_eval: false  # default: existing behavior
```

Set `true` to use disk-backed subprocess execution.

---

## 11. Validation Plan

### Phase 1: Reference fix validation

Run all 58 cases with reference fixes through both old and new paths.
Compare pass/fail.

Expected:
- Single-file cases (19): identical results
- Multi-file cases (39): mostly identical, some may differ where concat path
  had silent bugs

Success criterion: 0 regressions (cases that pass on old but fail on new
with reference fixes). Any regression indicates a harness or package builder bug.

### Phase 2: Known-affected cases

Run the 9 recursion-affected cases with actual gpt-5-mini model output through
the new path.

Expected: Cases that crashed with "maximum recursion depth exceeded" on the
concat path now pass (if model code was actually correct).

Success criterion: All 9 cases produce a result without recursion error.

### Phase 3: Self-import cases

Specifically test cases where models import from the module they're fixing:
- `alias_config_b`: model replaces config.py, imports DEFAULTS from config
- Other multi-file cases with similar patterns

Expected: Python's native import system handles this correctly because the
file is on disk.

Success criterion: No circular import failures.

### Phase 4: Full A/B comparison

Run the main 4-model 5-trial ablation through both paths (old and new).
Compare all 3,480 results.

Classify every difference as:
- Expected improvement (recursion bug fixed)
- Neutral (different import resolution, same pass/fail)
- Regression (must investigate)

Success criterion: 0 unexplained regressions. All differences attributable
to documented assembly bugs.

### Tests to add

1. **Package builder test**: Build package for multi-file case, verify all
   files present, verify __init__.py exists, verify module names correct.

2. **Subprocess runner test**: Run harness on simple case, verify JSON
   output, verify timeout works, verify cleanup.

3. **Adapter test**: Feed known subprocess results, verify exec_evaluate
   format matches exactly.

4. **Harness test**: Run harness standalone on a built package, verify
   test function resolves, verify merged namespace has all symbols.

5. **Recursion case test**: Build package for effect_order_b with
   delegation pattern, run through subprocess, verify PASS (not recursion).

6. **Self-import case test**: Build package for alias_config_b with
   self-referencing model code, run through subprocess, verify correct behavior.

7. **Equivalence test**: Run 10+ cases through both old and new paths,
   verify identical pass/fail on cases not affected by known assembly bugs.

---

## Scaffolding

### package_builder.py

```python
"""Build a real Python package on disk for subprocess evaluation."""

import json
import shutil
import tempfile
from pathlib import Path


_HARNESS_TEMPLATE = Path(__file__).parent / "eval_harness.py"


def build_eval_package(
    case: dict,
    model_files: dict,
    changed_files: set,
    project_root: str,
) -> Path:
    """Materialize a real Python package from case + model output.

    Args:
        case: benchmark case with code_files, code_files_contents
        model_files: {rel_path: code_string} from reconstruct_strict
        changed_files: set of rel_paths the model modified
        project_root: absolute path to project root (for test access)

    Returns:
        Path to temp directory containing pkg/ and harness.py
    """
    # TODO: create temp dir
    # TODO: create pkg/ with __init__.py
    # TODO: for each case file: write original or model version
    # TODO: write case_meta.json
    # TODO: copy harness template
    # TODO: return temp_dir path
    pass


def cleanup_package(temp_dir: Path) -> None:
    """Remove temp directory. Call after results are captured."""
    # TODO: shutil.rmtree with error handling
    pass
```

### subprocess_runner.py

```python
"""Execute evaluation in an isolated subprocess."""

import json
import os
import subprocess
import sys
from pathlib import Path


def run_eval_subprocess(
    temp_dir: Path,
    timeout: float = 30.0,
) -> dict:
    """Spawn subprocess to evaluate model code.

    Args:
        temp_dir: path from build_eval_package
        timeout: max execution time in seconds

    Returns:
        dict with passed, reasons, error fields
    """
    # TODO: read case_meta.json for project_root
    # TODO: build PYTHONPATH = temp_dir/pkg : project_root
    # TODO: build command = [sys.executable, harness.py]
    # TODO: subprocess.run with capture_output, timeout, env, cwd
    # TODO: handle TimeoutExpired
    # TODO: handle non-zero exit
    # TODO: parse stdout JSON
    # TODO: handle JSON parse failure
    # TODO: return result dict
    pass
```

### eval_harness.py

```python
"""Subprocess harness — executed inside temp_dir.

Imports model code as real Python modules, runs test, emits JSON result.
This file is copied into each temp_dir by package_builder.
"""

import importlib
import json
import os
import sys
import traceback
import types
from pathlib import Path


def main():
    """Entry point for subprocess evaluation."""
    result = {
        "passed": False,
        "reasons": [],
        "error": None,
        "error_message": None,
        "error_traceback": None,
        "modules_loaded": [],
    }

    try:
        # TODO: read case_meta.json from cwd
        # TODO: add project_root to sys.path
        # TODO: resolve test function from tests_v2
        # TODO: discover .py files in pkg/
        # TODO: import each module via importlib
        # TODO: build merged namespace module
        # TODO: run test_fn(merged)
        # TODO: populate result with passed/reasons
        pass

    except Exception as e:
        result["error"] = type(e).__name__
        result["error_message"] = str(e)
        result["error_traceback"] = traceback.format_exc()

    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

### adapter.py

```python
"""Convert subprocess results to exec_evaluate-compatible format."""


def adapt_result(
    subprocess_result: dict,
    case: dict,
    extracted_code: str = "",
) -> dict:
    """Map subprocess output to exec_evaluate return format.

    Args:
        subprocess_result: parsed JSON from subprocess stdout
        case: benchmark case dict (for failure_mode)
        extracted_code: model code string (for debugging field)

    Returns:
        dict matching exec_evaluate() contract exactly
    """
    # TODO: determine pass/fail from subprocess_result
    # TODO: compute score (0.0 / 0.1 / 0.2 / 1.0)
    # TODO: build reasons list
    # TODO: build execution sub-dict with all required fields
    # TODO: handle timeout, crash, invalid output cases
    # TODO: set assembly compat fields to defaults
    # TODO: return complete result dict
    pass
```
