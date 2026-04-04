# Canonical Execution: Final Plan (3 Files)

## Files

```
exec_canonical.py          # ALL execution logic: materialize, subprocess, classify
harness/run_case.py        # Dumb subprocess entry point: import, test, emit JSON
join_and_score.py           # Reasoning/execution join + LEG detection + scoring
```

That's it.

---

## File 1: exec_canonical.py

### Public API

```python
def exec_canonical(case, parsed_gen, recon, config, logger, attempt=0):
    """
    Canonical disk-backed execution. Returns exec_evaluate-compatible dict.

    1. Materialize package on disk
    2. Spawn subprocess
    3. Parse result
    4. Classify execution
    5. Write artifacts
    6. Emit WAL events
    7. Cleanup
    """
```

One function. One entry point. Called from execution_v2.py.

### Internal functions (all in same file, not exported)

```python
def _materialize_package(case, recon, project_root, run_dir, attempt):
    """
    Create temp dir with:
      pkg/
        __init__.py
        {module_a}.py
        {module_b}.py
      harness/
        run_case.py       (copied from project)
      case_meta.json

    For each file in case["code_files"]:
      if in recon.changed_files: write model version
      else: write original from case["code_files_contents"]

    Returns: Path to package dir
    """
```

```python
def _run_subprocess(pkg_dir, project_root, timeout=30):
    """
    cmd = [sys.executable, "harness/run_case.py"]
    cwd = pkg_dir
    PYTHONPATH = pkg_dir/pkg : project_root
    timeout enforced
    stdout captured → parse as JSON
    stderr captured → store for debug

    Returns: dict (parsed JSON from subprocess, or error dict)

    Error dicts:
      {"status": "timeout", ...}
      {"status": "crash", "exit_code": N, "stderr": "..."}
      {"status": "invalid_output", "stdout": "..."}
    """
```

```python
def _classify(subprocess_result, recon_status, parse_status):
    """
    Maps subprocess result to canonical category.

    Categories:
      PARSE_FAILURE          (parse_status != success)
      RECONSTRUCTION_FAILURE (recon_status != SUCCESS)
      BUILD_FAILURE          (package dir creation failed)
      IMPORT_FAILURE         (ImportError / ModuleNotFoundError)
      SYNTAX_FAILURE         (SyntaxError)
      NAME_ERROR             (NameError)
      RUNTIME_FAILURE        (other exception during import/test setup)
      TIMEOUT                (subprocess exceeded time limit)
      INVARIANT_CRASH        (test function raised exception)
      INVARIANT_FAILURE      (test returned False)
      EXECUTION_SUCCESS      (test returned True)

    Also attaches:
      subtype: raw exception class name
      score: 0.0 / 0.1 / 0.2 / 1.0

    Returns: exec_evaluate-compatible dict with all required fields
    """
```

### Score ladder

```
PARSE_FAILURE              → 0.0
RECONSTRUCTION_FAILURE     → 0.0
BUILD_FAILURE              → 0.0
IMPORT_FAILURE             → 0.0
SYNTAX_FAILURE             → 0.0
NAME_ERROR                 → 0.0
RUNTIME_FAILURE            → 0.0
TIMEOUT                    → 0.0
INVARIANT_CRASH            → 0.1
INVARIANT_FAILURE          → 0.2
EXECUTION_SUCCESS          → 1.0
```

### Return dict

Exact same shape as current exec_evaluate() output:

```python
{
    "pass": bool,
    "score": float,
    "reasons": list[str],
    "failure_modes": list[str],
    "execution": {
        "status": str,
        "ran": bool,
        "passed_tests": int,
        "total_tests": int,
        "runtime_error": str | None,
        "error_message": str | None,
        "syntax_error": str | None,
        "assembly_used": False,     # always False on canonical path
        "assembly_error": False,
        "assembly_risky": False,
        "rename_error": False,
        "assembly_sources": None,
        "invariant_pass": bool | None,
        "mutation_pass": None,      # not implemented in canonical path
    },
    "execution_category": str,      # NEW: canonical category
    "execution_subtype": str | None, # NEW: exception class name
    "_extracted_code": str,
    "_assembled_code": str,         # in canonical path: "disk_backed"
}
```

Downstream consumers (execution_v2, evaluator_v2, metrics_v2, logging) see the
same dict they see today. No adapter needed.

### Artifact writing

Inside exec_canonical, after classification:

```python
# Write artifacts to pkg_dir/artifacts/ (if --keep-eval-dirs)
if config.execution.keep_eval_dirs:
    _write_json(pkg_dir / "artifacts" / "execution_result.json", subprocess_result)
    _write_json(pkg_dir / "artifacts" / "classified_result.json", classified)
```

Two lines. Inline. No separate module.

### WAL emission

```python
logger.log_event("subprocess_completed", {
    "case_id": case["id"],
    "attempt": attempt,
    "status": subprocess_result.get("status"),
    "passed": subprocess_result.get("passed"),
    "execution_category": classified["execution_category"],
    "execution_time_ms": subprocess_result.get("execution_time_ms"),
}, phase="execution", condition=condition)
```

One call. Inline.

### Cleanup

```python
if not config.execution.keep_eval_dirs:
    shutil.rmtree(pkg_dir, ignore_errors=True)
```

One line. Inline.

### Total size estimate: ~200 lines

---

## File 2: harness/run_case.py

### What it does

1. Read case_meta.json from cwd
2. Add project_root to sys.path
3. Find all .py files in pkg/ (exclude __init__.py)
4. Import each with importlib.import_module
5. Build merged namespace (Option B — simple, explicit, 8 lines)
6. Resolve test function from tests_v2
7. Run test_fn(merged)
8. Emit JSON to stdout

### Merged namespace (Option B, kept minimal)

```python
merged = types.ModuleType("_t3_merged")
merged.__dict__["__builtins__"] = __builtins__
for mod in loaded_modules:
    for key, val in vars(mod).items():
        if not key.startswith("__"):
            merged.__dict__[key] = val
```

8 lines. No helper function. No recursion. Last module wins on conflicts (same
as concat path's last-def-wins). Explicit.

Why Option B not Option A: Changing all test functions to accept a modules dict
is a separate migration. The merged namespace is a 8-line compatibility shim
that lets existing tests work unchanged. It can be removed when tests are updated.

### Test function resolution

```python
family = meta["family"]
difficulty = meta.get("difficulty", "a")

# Try specific difficulty, then generic
for func_name in [f"test_{difficulty}", "test", "test_a"]:
    try:
        mod = importlib.import_module(f"tests_v2.test_{family}")
        test_fn = getattr(mod, func_name, None)
        if test_fn:
            break
    except ImportError:
        pass
```

### Result JSON schema

```json
{
  "status": "ok",
  "passed": true,
  "failure_reasons": [],
  "error_type": null,
  "error_message": null,
  "traceback": null,
  "modules_loaded": ["metrics", "processor"],
  "functions_detected": ["reset", "process_batch", "get_counter"],
  "execution_time_ms": 41
}
```

`functions_detected`: list of all non-dunder callable names found in merged
namespace. Cheap to collect (one list comprehension). Required for debugging
and reasoning/execution mismatch analysis.

### Error handling

Every exception caught. Never crashes without emitting JSON.

```python
try:
    # all logic here
except Exception as e:
    result["status"] = "error"
    result["error_type"] = type(e).__name__
    result["error_message"] = str(e)
    result["traceback"] = traceback.format_exc()

print(json.dumps(result))
```

### Hard rules

- No business logic
- No classification
- No retries
- No logging beyond stdout JSON
- No imports from the parent project (except tests_v2 via sys.path)

### Total size estimate: ~80 lines

---

## File 3: join_and_score.py

### Public API

```python
def join_and_score(parsed_gen, classifier_result, exec_result, case, condition):
    """
    Combine reasoning evaluation + execution result into LEG analysis record.

    Returns dict with:
      execution_pass, execution_category,
      mechanism_correct, commitments_valid, alignment_positive,
      leg_candidate, lucky_fix_candidate,
      reasoning_execution_alignment,
      v2_category, legacy_compat_category
    """
```

### What it wraps

This is a thin wrapper around existing logic:

- `metrics_v2.derive_v2_signals()` — already computes mechanism_correct,
  commitments_valid, alignment_positive, v2_category
- `evaluator_v2.assemble_v2_result()` — already assembles the full ev dict

The new function adds:
- `execution_category` from the classified result
- `leg_candidate = mechanism_correct and not execution_pass`
- `lucky_fix_candidate = execution_pass and not mechanism_correct`
- `reasoning_execution_alignment = "aligned" | "misaligned" | "unknown"`

### Why a separate file

This is the ONLY piece of logic that crosses the reasoning/execution boundary.
It deserves to be visible and auditable, not buried inside a 400-line orchestrator.
It's also the piece that researchers will modify most often when refining LEG
definitions.

### Total size estimate: ~60 lines

---

## Integration into execution_v2.py

### Current code (line ~122)

```python
exec_result = exec_evaluate(case, code)
```

### New code

```python
from exec_canonical import exec_canonical

if config.execution.mode == "canonical":
    exec_result = exec_canonical(
        case, parsed_gen, recon, config, logger, attempt=0
    )
else:
    # Legacy path (concat/flatten) — for comparison only
    code = "\n\n".join(changed_parts)
    exec_result = exec_evaluate(case, code)
```

The `recon` object (from reconstructor.py, already computed at line ~114) is
passed directly. No flattening step.

### Config

```yaml
execution:
  mode: "canonical"              # canonical | legacy
  keep_eval_dirs: false          # retain disk packages for debugging
  subprocess_timeout: 30         # seconds
```

---

## What Happens to Existing Files

| File | Action |
|---|---|
| `exec_eval.py` | Untouched. `exec_evaluate()` remains for legacy mode. |
| `code_assembly.py` | Untouched. Not called on canonical path. |
| `module_exec.py` | Untouched. Superseded but kept for reference. |
| `execution_v2.py` | ~15 line change at the exec call site. |
| `experiment_config.py` | Add `mode`, `keep_eval_dirs`, `subprocess_timeout` fields. |
| `parser_v2.py` | Untouched. |
| `reconstructor.py` | Untouched. |
| `evaluator_v2.py` | Untouched. |
| `metrics_v2.py` | Untouched. |
| `retry_v2.py` | Change exec call to use exec_canonical per attempt. |
| `logging_core.py` | Untouched. |
| `parallel_runner.py` | Untouched. |

---

## Retry Changes

In `retry_v2.py`, the inner loop currently calls:

```python
exec_result = exec_evaluate(case, code)
```

This becomes:

```python
exec_result = exec_canonical(case, parsed_gen, recon, config, logger, attempt=k)
```

Each attempt k gets its own package directory (`attempt_0/`, `attempt_1/`).
Fresh subprocess. No shared state. The retry harness passes only the information
the retry condition specifies (test feedback, critique text, previous raw response)
between attempts.

---

## Package Construction Detail

For case `effect_order_b` (2 files), model changed `processor.py`:

```
/tmp/t3_eval_XXXXXXXX/
  pkg/
    __init__.py                    # empty
    metrics.py                     # ORIGINAL (from case["code_files_contents"])
    processor.py                   # MODEL'S VERSION (from recon.files, in changed_files)
  harness/
    run_case.py                    # copied from project_root/harness/run_case.py
  case_meta.json                   # {"case_id": "effect_order_b", "family": "side_effect_order", ...}
```

PYTHONPATH set to: `{tmpdir}/pkg:{project_root}`

So inside processor.py, `from metrics import increment` resolves to the
on-disk `metrics.py` via standard Python import machinery.

No rewriting. No renaming. No flattening. Python does what Python does.

---

## Failure Modes

| Failure | Where detected | Category | Score |
|---|---|---|---|
| Parse failed | Before exec_canonical called | PARSE_FAILURE | 0.0 |
| Reconstruction failed | Before exec_canonical called | RECONSTRUCTION_FAILURE | 0.0 |
| Temp dir creation fails | _materialize_package | BUILD_FAILURE | 0.0 |
| File write fails | _materialize_package | BUILD_FAILURE | 0.0 |
| SyntaxError on import | Subprocess | SYNTAX_FAILURE | 0.0 |
| ImportError | Subprocess | IMPORT_FAILURE | 0.0 |
| NameError | Subprocess | NAME_ERROR | 0.0 |
| Other exception on import | Subprocess | RUNTIME_FAILURE | 0.0 |
| Timeout | subprocess.run timeout | TIMEOUT | 0.0 |
| Test crashes | Subprocess test_fn raises | INVARIANT_CRASH | 0.1 |
| Test returns False | Subprocess test_fn returns (False, reasons) | INVARIANT_FAILURE | 0.2 |
| Test returns True | Subprocess test_fn returns (True, reasons) | EXECUTION_SUCCESS | 1.0 |
| Subprocess emits bad JSON | _run_subprocess | treated as RUNTIME_FAILURE | 0.0 |
| Subprocess non-zero exit | _run_subprocess | treated as RUNTIME_FAILURE | 0.0 |

Every failure is loud. No silent fallbacks.

---

## Validation Plan

### Step 1: Reference fixes (all 58 cases)

Run every case with its reference fix through canonical path.
Compare against legacy path.

Pass criterion: 0 regressions. Every reference fix that passes legacy
also passes canonical.

### Step 2: Recursion-affected cases (9 cases)

Run with actual gpt-5-mini model output.
Verify no recursion errors.
Verify delegation pattern works.

### Step 3: Self-import cases

Run alias_config_b and similar.
Verify `from config import DEFAULTS` resolves correctly when model
replaces config.py (DEFAULTS defined at module level in model's code).

### Step 4: Full comparison run

Run 4-model 5-trial ablation through both paths.
Count disagreements. Classify each.
All disagreements should be in the 9 known-affected cases.

### Tests to write

1. Materialize package for 2-file case → verify files exist, importable
2. Run subprocess on simple case → verify JSON result
3. Subprocess timeout → verify timeout result
4. Delegation pattern (effect_order_b) → verify PASS (not recursion)
5. Self-import pattern (alias_config_b) → verify correct behavior
6. Result format → verify matches exec_evaluate contract

---

## Size Budget

| File | Lines | Purpose |
|---|---|---|
| `exec_canonical.py` | ~200 | Everything: materialize, subprocess, classify, artifacts, WAL |
| `harness/run_case.py` | ~80 | Dumb subprocess entry: import, test, emit JSON |
| `join_and_score.py` | ~60 | Reasoning/execution join, LEG detection |
| execution_v2.py changes | ~15 | Switch exec call |
| experiment_config.py changes | ~5 | Add mode/timeout/keep fields |
| retry_v2.py changes | ~10 | Switch exec call per attempt |
| Tests | ~200 | 6 test functions |
| **Total** | **~570** | |
