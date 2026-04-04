# Canonical Execution Architecture: Implementation Plan

This plan implements the disk-backed, process-isolated, whole-file module execution
system as specified in the architecture guide. It replaces the concat/flatten
assembly path as the canonical scoring path.

---

## 1. What We Are Building

A 7-stage evaluation pipeline where:

- Model code is materialized as real Python files on disk
- Execution happens in a fresh subprocess per attempt
- Every stage emits a structured artifact and a WAL event
- Parse, reconstruction, execution, and reasoning failures are categorized separately
- Retries are fully isolated (new package, new subprocess, no shared state)
- The reasoning/execution join is a first-class stage, not an afterthought

---

## 2. Stage Definitions

### Stage A — Parse

**Owner:** `parser_v2.py` (existing, unchanged)

**Input:** Raw model response string, condition name.

**Output:** `ParsedGenerationV2` dataclass.

**Artifact:** `parsed_response.json` — serialized parse result including:
- parse_status, schema_variant, full_json, files_dict
- parse_valid, schema_valid
- Three-tier diagnostics (exec/format/recovery)

**WAL event:** `parse_completed`

**Terminal on failure:** Yes. If `parse_valid == False`, no subsequent stages run.
The case gets `execution_category = PARSE_FAILURE`.

**Changes required:** None to parser_v2.py. Add artifact serialization and WAL event
emission in the orchestrating function.

---

### Stage B — Reconstruct

**Owner:** `reconstructor.py` (existing, unchanged)

**Input:** Case manifest (code_files, code_files_contents), parsed file dict.

**Output:** `ReconstructionResult` with:
- `files`: complete dict of `{rel_path: full_file_contents}` for EVERY case file
- `changed_files`: set of paths the model modified
- `unchanged_files`: set of paths left as original
- `status`: SUCCESS, FAILED_MISSING_FILES, FAILED_SYNTAX_ERRORS

**Artifact:** `reconstruction.json` — the full file map plus metadata.

**WAL event:** `reconstruction_completed`

**Terminal on failure:** Yes. If status != SUCCESS, case gets
`execution_category = RECONSTRUCTION_FAILURE`.

**Rules:**
- Whole-file replacement only. No patching, no splicing.
- Every file in `case["code_files"]` must appear in output.
- Unchanged files use originals from `case["code_files_contents"]`.
- Model's "UNCHANGED" marker is resolved here, not downstream.

**Changes required:** None to reconstructor.py. Reconstruct_strict already
implements these semantics. Add artifact serialization.

---

### Stage C — Materialize Eval Package

**Owner:** `build_eval_package.py` (NEW)

**Input:** Case metadata, reconstruction result, execution config.

**Output:** Self-contained eval package on disk.

**Directory structure:**

```
{run_dir}/cases/{case_id}/{model}/{condition}/trial_{n}/attempt_{k}/
  manifest.json              # package metadata
  case_meta.json             # case_id, family, difficulty, project_root
  pkg/                       # real Python package
    __init__.py              # empty (makes pkg importable)
    metrics.py               # original or model-replaced
    processor.py             # original or model-replaced
    ...
  harness/
    run_case.py              # subprocess entry point
  artifacts/
    parsed_response.json     # from Stage A
    reconstruction.json      # from Stage B
```

**Package construction rules:**
- Module names derived from filename: `code_snippets_v2/effect_order_b/processor.py` → `processor.py`
- All case files placed in `pkg/` as flat siblings (current cases are all flat)
- `__init__.py` is always empty
- Changed files get model's version; unchanged files get original
- No import rewriting. No AST manipulation. No renaming. Zero transformation.
- The package must be importable via bare names (`from metrics import X`) when
  `pkg/` is on PYTHONPATH

**WAL event:** `package_built`

**Artifact:** The directory itself. Optionally retained under `--keep-eval-dirs`.

---

### Stage D — Execute in Fresh Subprocess

**Owner:** `run_eval_subprocess.py` (NEW)

**Input:** Eval package path, timeout config.

**Output:** `SubprocessExecutionResult` (parsed from subprocess stdout JSON).

**Subprocess invocation:**
```
command:    [sys.executable, "harness/run_case.py"]
cwd:        {package_dir}
PYTHONPATH: {package_dir}/pkg:{project_root}
timeout:    30s (configurable)
env:        scrubbed copy of os.environ + PYTHONPATH override
```

**PYTHONPATH semantics:**
- `{package_dir}/pkg` — so bare imports (`from metrics import X`) resolve to on-disk files
- `{project_root}` — so `from tests_v2.test_aliasing import test_a` resolves

**Communication protocol:**
- Stdout: exactly one JSON object. Nothing else.
- Stderr: free-form, captured for debugging, never parsed as result.
- Exit code: 0 on normal completion (pass or fail). Non-zero only on unhandled crash.

**Result schema:**
```json
{
  "status": "ok | timeout | crash | invalid_output",
  "passed": true,
  "tests_run": 1,
  "tests_passed": 1,
  "failure_reasons": [],
  "error_type": null,
  "error_message": null,
  "traceback": null,
  "modules_loaded": ["metrics", "processor"],
  "execution_time_ms": 41
}
```

**Error handling:**
- TimeoutExpired: return `{"status": "timeout", ...}`
- Non-zero exit: return `{"status": "crash", "stderr": ...}`
- Invalid JSON on stdout: return `{"status": "invalid_output", "stdout": ...}`

**WAL event:** `subprocess_completed`

**Rules:**
- New process for every attempt. No reuse.
- No model code executes in parent process. Ever.
- Timeout strictly enforced.

---

### Stage E — Invariant Evaluation (Inside Harness)

**Owner:** `harness/run_case.py` (NEW, runs inside subprocess)

**Input:** Reads `case_meta.json` from cwd. Imports modules from PYTHONPATH.

**Execution sequence:**
1. Read `case_meta.json` → case_id, family, difficulty, project_root
2. Add project_root to sys.path
3. Resolve test function:
   - `from tests_v2.test_{family} import test_{difficulty}`
   - Fallback: `test`, then `test_a`
4. Discover and import all `.py` files in `pkg/` via `importlib.import_module()`
5. Build merged namespace for test compatibility:
   - `merged = types.ModuleType("_t3_merged")`
   - Copy all non-dunder attrs from each module into merged
   - Last module wins on name conflicts
6. Run `test_fn(merged)` → `(passed: bool, reasons: list[str])`
7. Emit JSON result to stdout
8. On ANY exception: emit error JSON with type, message, traceback

**Why merged namespace:** Existing test functions expect `mod.reset()`,
`mod.process_batch()`, `mod.get_counter()` — symbols from different source files.
The merge happens AFTER real module execution, for test compatibility only. Module
boundaries are preserved during execution.

**Transitional note:** The merged namespace is a compatibility layer for current
test functions. The long-term fix is to update test functions to accept a package
object or multiple modules. But that is a separate change and not required for
this migration.

**WAL event:** Embedded in subprocess result (no separate event — the subprocess
is the event).

---

### Stage F — Execution Classification

**Owner:** `classify_execution.py` (NEW)

**Input:** Subprocess result, reconstruction status, parse status.

**Output:** Canonical execution category + subtype.

**Categories:**
```
PARSE_FAILURE                    # Stage A failed
RECONSTRUCTION_FAILURE           # Stage B failed
BUILD_FAILURE                    # Stage C failed (temp dir, file write)
IMPORT_FAILURE                   # Subprocess: ImportError / ModuleNotFoundError
SYNTAX_FAILURE                   # Subprocess: SyntaxError
RUNTIME_FAILURE                  # Subprocess: other exception during import
NAME_ERROR                       # Subprocess: NameError (undefined symbol)
TIMEOUT                          # Subprocess exceeded time limit
INVARIANT_FAILURE                # Test ran, returned False
INVARIANT_CRASH                  # Test raised exception
EXECUTION_SUCCESS                # Test ran, returned True
```

**Subtypes:** The raw exception type (RecursionError, TypeError, AttributeError, etc.)
attached as metadata.

**Score computation:**
```
PARSE_FAILURE              → 0.0
RECONSTRUCTION_FAILURE     → 0.0
BUILD_FAILURE              → 0.0
IMPORT_FAILURE             → 0.0
SYNTAX_FAILURE             → 0.0
RUNTIME_FAILURE            → 0.0
NAME_ERROR                 → 0.0
TIMEOUT                    → 0.0
INVARIANT_CRASH            → 0.1
INVARIANT_FAILURE          → 0.2
EXECUTION_SUCCESS          → 1.0
```

**Adapter to exec_evaluate format:** This stage also produces the dict that
downstream consumers expect (execution_v2.py, evaluator_v2.py, etc.). All fields
from the old exec_evaluate contract are present. Assembly-related fields are set
to benign defaults (assembly_used=False, assembly_error=False).

**WAL event:** `execution_classified`

---

### Stage G — Reasoning/Execution Join

**Owner:** `join_reasoning_execution.py` (NEW)

**Input:** Parsed reasoning fields, classifier result, execution classification.

**Output:** Joined record for LEG analysis.

**Schema:**
```json
{
  "reasoning_present": true,
  "reasoning_parse_ok": true,
  "mechanism_correct": true,
  "commitments_valid": true,
  "alignment_positive": false,
  "execution_pass": false,
  "execution_category": "INVARIANT_FAILURE",
  "leg_candidate": true,
  "lucky_fix_candidate": false,
  "reasoning_execution_alignment": "misaligned",
  "v2_category": "LEG_v2"
}
```

This is what `metrics_v2.derive_v2_signals()` and `evaluator_v2.assemble_v2_result()`
currently compute, restructured as a standalone stage with an explicit artifact.

**WAL event:** `reasoning_execution_joined`

**Changes required:** Minimal. The logic already exists in metrics_v2 and
evaluator_v2. This stage wraps it with artifact serialization and WAL emission.

---

## 3. File Layout

### New files

| File | Stage | Purpose |
|---|---|---|
| `build_eval_package.py` | C | Materialize real Python package on disk |
| `run_eval_subprocess.py` | D | Spawn and manage subprocess |
| `harness/run_case.py` | E | Subprocess entry point (template, copied into each package) |
| `classify_execution.py` | F | Classify execution result into canonical categories |
| `join_reasoning_execution.py` | G | Produce LEG/alignment join record |
| `exec_evaluate_v2.py` | Orchestrator | Calls stages C-F, returns exec_evaluate-compatible dict |

### Existing files (unchanged)

| File | Stage | Notes |
|---|---|---|
| `parser_v2.py` | A | Unchanged. Three-tier parser. |
| `reconstructor.py` | B | Unchanged. Whole-file reconstruction. |
| `evaluator_v2.py` | Post-G | Unchanged. Classifier invocation + result assembly. |
| `metrics_v2.py` | Post-G | Unchanged. Signal derivation. |
| `execution_v2.py` | Orchestrator | Modified: calls exec_evaluate_v2 instead of exec_evaluate |
| `logging_core.py` | WAL | Unchanged. Event emission. |

### Existing files (kept but demoted)

| File | Notes |
|---|---|
| `code_assembly.py` | No longer on canonical path. Kept for legacy/compare mode. |
| `exec_eval.py` | No longer canonical. Kept as `exec_evaluate_legacy()` for A/B comparison. |
| `module_exec.py` | Superseded by the new subprocess path. Kept for reference. |

---

## 4. Disk Layout Per Evaluation

```
{run_dir}/cases/{case_id}/{model}/{condition}/trial_{n}/attempt_{k}/
  manifest.json
  case_meta.json
  pkg/
    __init__.py
    {module_a}.py
    {module_b}.py
    ...
  harness/
    run_case.py
  artifacts/
    parsed_response.json
    reconstruction.json
    execution_request.json
    execution_result.json
    classified_result.json
    joined_result.json
  stdout.txt
  stderr.txt
```

**Retention policy:**
- Default: delete after results captured (cleanup_package)
- `--keep-eval-dirs`: retain all packages for debugging
- Sampled retention: keep every Nth package, or keep on failure only

**This layout means:** Every evaluation is replayable. You can `cd` into the
directory, run `python harness/run_case.py`, and get the exact same result.
No ambient state required.

---

## 5. Retry Isolation

Each retry attempt gets:
- A new package directory (`attempt_0/`, `attempt_1/`, `attempt_2/`)
- A new subprocess
- Fresh file materialization from the retry's parsed output
- No shared temp dir with previous attempts
- No reused modules or interpreter state

The retry harness (`retry_v2.py`) calls stages A-G independently for each attempt.
The only information that flows between attempts is what the retry condition
explicitly provides (test feedback, critique text, previous raw response).

This eliminates retry contamination. The benchmark includes cases specifically
designed to test stateful failure modes (mutable_default, retry_duplication,
stale_cache). If retries share state, those cases become unreliable measurements.

---

## 6. Dual-Path Comparison Mode

During migration, a config flag enables both paths:

```yaml
execution:
  mode: "canonical"           # canonical | legacy | compare
```

- `canonical`: disk-backed subprocess only (new default after migration)
- `legacy`: concat/flatten only (current behavior)
- `compare`: run both, emit disagreement record

Compare mode emits:
```json
{
  "canonical_pass": false,
  "legacy_pass": true,
  "execution_disagreement": true,
  "disagreement_type": "module_semantics"
}
```

Disagreement types:
- `module_semantics`: different import resolution (the alias-recursion class)
- `state_leak`: concat path has cross-module state leakage
- `name_collision`: concat path has last-def-wins shadow
- `identical`: both paths agree
- `unknown`: disagree for unclassified reason

Compare mode is an empirical instrument. It tells us which prior results were
contaminated by assembly semantics. But it is NOT the scoring source of truth.
Only `canonical` mode produces scores.

---

## 7. WAL Event Model

Every stage emits one event:

```json
{
  "event_type": "parse_completed | reconstruction_completed | package_built | subprocess_completed | execution_classified | reasoning_execution_joined",
  "run_id": "...",
  "case_id": "...",
  "model": "...",
  "condition": "...",
  "trial": 1,
  "attempt": 0,
  "timestamp": "...",
  "payload": { ... stage-specific data ... }
}
```

The existing `RunLogger` from `logging_core.py` handles event emission. Each
new stage calls `logger.log_event()` with the appropriate type and payload.

---

## 8. Integration Point

In `execution_v2.py:run_v2()`, the current call:

```python
exec_result = exec_evaluate(case, code)
```

Is replaced by:

```python
if config.execution.mode == "legacy":
    exec_result = exec_evaluate(case, code)
elif config.execution.mode == "compare":
    exec_result = exec_evaluate(case, code)
    canonical_result = exec_evaluate_canonical(case, recon, logger, attempt=0)
    ev["execution_disagreement"] = compare_results(exec_result, canonical_result)
else:  # canonical
    exec_result = exec_evaluate_canonical(case, recon, logger, attempt=0)
```

Where `exec_evaluate_canonical()` calls stages C → D → F and returns a dict
matching the exec_evaluate contract.

The `recon` object (from Stage B) is passed directly — no flattening to a
single code string. The canonical path works with per-file data, not concatenated
strings.

---

## 9. Migration Phases

### Phase 1 — Implement behind flag

Build all new files. Wire into execution_v2.py behind `execution.mode: "canonical"`.
Default remains `"legacy"`. No existing behavior changes.

### Phase 2 — Reference fix validation

Run all 58 cases with reference fixes through both paths. Compare pass/fail.
Expected: identical on single-file, some improvements on multi-file.

Success criterion: 0 regressions (reference fix passes on legacy but fails on
canonical). Any regression = harness or package builder bug.

### Phase 3 — Known-affected case validation

Run the 9 recursion-affected cases with actual gpt-5-mini model output. Verify
they no longer crash. Verify delegation pattern works correctly.

### Phase 4 — Full A/B comparison

Run the 4-model 5-trial ablation through compare mode. Classify all disagreements.
Expected: all disagreements are in the recursion-affected cases and favor canonical.

### Phase 5 — Flip default

Set `execution.mode: "canonical"` as default. Legacy remains available.

### Phase 6 — Deprecate legacy

Remove legacy path from hot path. Keep only for audit/debug mode.

### Phase 7 — Delete concat assembly from scoring

Remove `code_assembly.py` import rewriting from any scoring-relevant code path.
The file can remain for historical reference but must not be callable from
canonical execution.

---

## 10. Hard Rules (Repo Invariants)

1. No model code executes in parent process.
2. Every attempt gets a fresh subprocess.
3. Whole-file replacement only. No patching.
4. No import rewriting on canonical path. Ever.
5. Canonical scoring uses disk-backed module execution only.
6. All stage outputs are serialized to disk (at least optionally).
7. Every stage emits a WAL event.
8. Retries are fully isolated (new package, new subprocess).
9. Execution result schema is strict and versioned.
10. Reasoning/execution join is a first-class stage.

---

## 11. What This Fixes

| Problem | How it's fixed |
|---|---|
| Alias-rename recursion | No import rewriting. Real Python imports. |
| Namespace flattening | Each file in its own module namespace. |
| Cross-module name collision | Python's module system handles this natively. |
| Execution order dependence | Python's import system handles this natively. |
| sys.modules leakage | Fresh subprocess per attempt. |
| Retry contamination | New package + new subprocess per attempt. |
| Assembly artifacts in data | Eliminated by construction. |
| gpt-5-mini penalty for modular code | Correct code now produces correct results. |
| Unclear failure attribution | Parse/reconstruct/execute/invariant classified separately. |
| LEG measurement contamination | Reasoning/execution join with clean execution data. |

---

## 12. What This Does NOT Fix (Out of Scope)

- Test function quality (existing tests_v2/ are unchanged)
- Classifier accuracy (evaluator_v2 is unchanged)
- Parser edge cases (parser_v2 is unchanged)
- Prompt template design (prompts/ are unchanged)
- Parallel runner (parallel_runner.py is unchanged — still works, just calls
  the new exec path)
- Dashboard/metrics (v2_metrics.py, v2_dashboard.py unchanged — they consume
  the same result format)

---

## 13. Estimated Effort

| Component | Effort | Depends on |
|---|---|---|
| `build_eval_package.py` | Small (~80 lines) | Nothing |
| `run_eval_subprocess.py` | Small (~60 lines) | build_eval_package |
| `harness/run_case.py` | Medium (~100 lines) | Test function resolution logic |
| `classify_execution.py` | Small (~50 lines) | Result schema |
| `join_reasoning_execution.py` | Small (~40 lines, mostly wrapping existing) | classify_execution |
| `exec_evaluate_v2.py` (orchestrator) | Medium (~80 lines) | All above |
| execution_v2.py integration | Small (~15 line change) | exec_evaluate_v2 |
| experiment_config.py | Tiny (~3 lines, add mode field) | Nothing |
| Tests | Medium (~200 lines) | All above |
| Phase 2-4 validation runs | Time only | Implementation complete |

Total new code: ~500 lines across 6 files + ~200 lines of tests.
No existing files are deleted or substantially rewritten.
