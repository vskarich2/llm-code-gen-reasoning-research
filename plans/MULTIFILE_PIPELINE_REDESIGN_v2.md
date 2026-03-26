# T3 Multi-File Pipeline Redesign v2 (Corrected)

**Date:** 2026-03-24
**Supersedes:** MULTIFILE_PIPELINE_REDESIGN_v1.md
**Prerequisite:** audits/pipeline_audit_20260324.md

**v1 defects corrected in this revision:**
1. Removed all synthetic namespace flattening
2. Removed fallback-to-original in primary evaluation path
3. Full directory structure preserved everywhere
4. Deterministic token overflow policy with priority-based reduction
5. Strict error taxonomy with explicit metric inclusion rules
6. Import summary treated as potentially biasing; calibration experiment designed
7. Legacy removal timeline defined with hard cutoff

---

## 1. FINAL ARCHITECTURE (CORRECTED)

### 1.1 System Overview

```
cases.json           PromptBuilder            call_model()
    |                     |                        |
    v                     v                        v
+------------+    +---------------+          +-----------+
| CaseLoader |    | TokenBudget   |          | LLM       |
| (manifest  |--->| (priority-    |--------->| (budget-  |
|  + import  |    |  based        |          |  enforced)|
|  graph)    |    |  reduction)   |          +-----------+
+------------+    +---------------+                |
                                                   v
+------------+    +---------------+          +-----------+
| Logger     |<---| SubprocessEval|<---------| StrictRecon|
| (error     |    | (real modules |          | (FAIL on  |
|  taxonomy) |    |  real imports)|          |  missing) |
+------------+    +---------------+          +-----------+
```

### 1.2 File-System-Based Execution (No Flattening)

Each case evaluation writes real `.py` files to a temp directory **preserving full relative paths**, runs a test harness in a subprocess with `PYTHONPATH` set to the common root.

```python
def evaluate_case(manifest, reconstructed_files, test_module_path):
    with tempfile.TemporaryDirectory(prefix=f"t3_{manifest.case_id}_") as tmpdir:
        # 1. Write every file preserving directory structure
        for rel_path, content in reconstructed_files.items():
            target = Path(tmpdir) / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            # Create __init__.py in every directory for package imports
            _ensure_init_files(target.parent, Path(tmpdir))

        # 2. Copy test module into tmpdir
        harness_path = Path(tmpdir) / "_t3_harness.py"
        harness_code = _generate_harness(manifest, test_module_path)
        harness_path.write_text(harness_code, encoding="utf-8")

        # 3. Compute PYTHONPATH: the tmpdir root so all imports resolve
        python_path = str(Path(tmpdir))

        # 4. Run in subprocess
        result = subprocess.run(
            [sys.executable, str(harness_path)],
            cwd=tmpdir,
            env={
                "PYTHONPATH": python_path,
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            },
            capture_output=True, timeout=30, text=True,
        )
        return _parse_harness_output(result)
```

### 1.3 Test Harness: Real Module Imports (No Flattening)

**v1 had `_ns.__dict__.update(...)` namespace merging. This is removed.**

The new test harness imports each file as a real Python module and passes a `mods` dict to the test function:

```python
# _t3_harness.py (generated per case)
import sys, json, importlib

# Import each case file as a real module
mods = {}
for mod_path in {module_import_paths}:       # e.g., ["cache_writer", "cache_reader", "user_repo", "user_service"]
    mods[mod_path] = importlib.import_module(mod_path)

# The test function receives the mods dict
{test_function_source}

try:
    passed, reasons = test(mods)
except Exception as e:
    passed = False
    reasons = [f"test harness crashed: {e}"]

print(json.dumps({{"pass": passed, "reasons": reasons}}))
sys.exit(0 if passed else 1)
```

**Consequence: all 58 test functions across 28 test files must be rewritten.**

The old signature was:
```python
def test(mod):
    save_user = getattr(mod, "save_user", None)
```

The new signature is:
```python
def test(mods):
    save_user = getattr(mods["user_service"], "save_user", None)
    get_display_name = getattr(mods["cache_reader"], "get_display_name", None)
```

This is not optional. The test rewrite is part of Phase 2.

**For single-file cases**, `mods` has exactly one entry. The test accesses `mods["config"]` (or whatever the single module is named). This is the same code path -- no special casing.

### 1.4 Directory Structure Preservation

**All paths are full relative paths throughout the entire pipeline.**

In `cases.json`:
```json
"code_files": [
    "code_snippets/hidden_dependency_hard/cache_writer.py",
    "code_snippets/hidden_dependency_hard/cache_reader.py"
]
```

In the prompt:
```
### FILE 1/4: code_snippets/hidden_dependency_hard/cache_writer.py ###
```

In the LLM output schema:
```json
{
    "files": {
        "code_snippets/hidden_dependency_hard/cache_writer.py": "...",
        "code_snippets/hidden_dependency_hard/cache_reader.py": "UNCHANGED"
    }
}
```

In the temp directory:
```
tmpdir/
  code_snippets/
    hidden_dependency_hard/
      __init__.py
      cache_writer.py
      cache_reader.py
      user_repo.py
      user_service.py
```

**`Path(path).name` is never used.** Basenames are never extracted, compared, or relied upon.

The PYTHONPATH is set to `tmpdir`, and the harness import paths are computed from the full relative paths:
```python
# "code_snippets/hidden_dependency_hard/cache_writer.py"
#  -> import path: "code_snippets.hidden_dependency_hard.cache_writer"
#  -> mods key: "cache_writer" (the leaf module name, for test convenience)
```

Wait -- the mods dict key must be deterministic. We use the **leaf module name** as the dict key (e.g., `"cache_writer"`) because that is what the code's own `import` statements use (`from cache_writer import cache_put`). The full import path is used for `importlib.import_module()`, but the dict key matches the module's local import name.

**Edge case: two files with the same basename in different directories.** This cannot happen within a single case (Python imports would be ambiguous too). The case JSON is validated at load time to reject this.

### 1.5 Strict Reconstruction (No Fallback in Primary Path)

```python
@dataclass
class ReconstructionResult:
    status: str                   # "SUCCESS", "FAILED_MISSING_FILES", "FAILED_EMPTY_FILES", etc.
    files: dict[str, str]         # rel_path -> content (only populated on SUCCESS)
    changed_files: set[str]       # rel_paths the model modified
    missing_files: set[str]       # rel_paths absent from model response
    extra_files: set[str]         # rel_paths model added that weren't in manifest
    syntax_errors: dict[str, str] # rel_path -> error message
    format_violation: bool        # True if response structure is wrong

def reconstruct_strict(manifest, model_files: dict[str, str]) -> ReconstructionResult:
    """Primary reconstruction. FAILS if any file is missing. No fallback."""
    expected = set(manifest.file_paths)
    provided = set(model_files.keys())
    missing = expected - provided

    if missing:
        return ReconstructionResult(
            status="FAILED_MISSING_FILES",
            files={},
            changed_files=set(),
            missing_files=missing,
            extra_files=provided - expected,
            syntax_errors={},
            format_violation=True,
        )

    final_files = {}
    changed = set()
    syntax_errors = {}

    for rel_path in manifest.file_paths:
        value = model_files[rel_path]
        if value.strip() == "UNCHANGED":
            final_files[rel_path] = manifest.files[rel_path]
        elif isinstance(value, str) and value.strip():
            # AST validation
            try:
                ast.parse(value)
            except SyntaxError as e:
                syntax_errors[rel_path] = str(e)
            final_files[rel_path] = value
            changed.add(rel_path)
        else:
            return ReconstructionResult(
                status="FAILED_EMPTY_FILES",
                files={},
                changed_files=set(),
                missing_files=set(),
                extra_files=set(),
                syntax_errors={},
                format_violation=True,
            )

    if syntax_errors:
        return ReconstructionResult(
            status="FAILED_SYNTAX_ERRORS",
            files=final_files,        # populated for logging/debugging
            changed_files=changed,
            missing_files=set(),
            extra_files=provided - expected,
            syntax_errors=syntax_errors,
            format_violation=False,    # format was ok, code was bad
        )

    return ReconstructionResult(
        status="SUCCESS",
        files=final_files,
        changed_files=changed,
        missing_files=set(),
        extra_files=provided - expected,
        syntax_errors={},
        format_violation=False,
    )
```

**Salvage path (secondary analysis ONLY):**

```python
def reconstruct_salvage(manifest, model_files: dict[str, str]) -> ReconstructionResult:
    """Fallback reconstruction for secondary analysis. Fills missing files from originals."""
    # Same as strict, but missing files -> use original
    # Result is tagged status="SALVAGED"
    # MUST NOT flow into primary metrics
```

The salvage path is invoked ONLY when:
1. `reconstruct_strict()` returned a failure status
2. The analysis pipeline explicitly requests salvaged results for secondary LEG analysis
3. The result is tagged `reconstruction_mode="salvaged"` in every log record and metric

**It is a programming error to include salvaged results in primary metrics. This is enforced by assertion in the metric computation code.**

---

## 2. CRITICAL DESIGN DECISIONS (UPDATED)

### 2.1 Output Format: File-Dict with Strict Tier Classification

**Requested format:** `{"reasoning": "...", "files": {"path": "content|UNCHANGED"}}`

**Parser tiers** (in order):

| Tier | Format | `response_format` tag | Primary metrics? |
|------|--------|-----------------------|-----------------|
| 0 | `files` dict (new format) | `file_dict` | Yes |
| 1 | `code` as dict (model used code key but returned per-file dict) | `code_dict` | Yes (treated as file_dict) |
| 2 | `code` as string (old format) | `code_string` | No -- secondary only |
| 3 | markdown code block extraction | `code_block` | No -- secondary only |
| 4 | raw fallback | `raw_fallback` | No -- excluded entirely |

**Metric inclusion rules:**
- **Primary metrics** (pass rate, LEG, scores): ONLY Tier 0 and Tier 1 results.
- **Secondary metrics** (analysis, comparison): Tier 2 and 3 results with explicit `response_format` filter.
- **Excluded entirely:** Tier 4 (raw_fallback). These are infrastructure failures.

**Token overhead:** The `files` format adds ~12 tokens for UNCHANGED entries + ~50 tokens for the output instruction change. Under 1% of typical response. Not a concern.

### 2.2 Prompt File Organization: Dependency-Ordered, Full Paths

Files are ordered by topological sort of the import graph (dependency-first), with alphabetical tiebreaking. Full relative paths are used in the prompt.

```
## Codebase ({N} files)

### FILE 1/{N}: code_snippets/hidden_dependency_hard/cache_writer.py ###
```python
{content}
```

### FILE 2/{N}: code_snippets/hidden_dependency_hard/cache_reader.py ###
```python
{content}
```
...
```

**Import summary** is a separate, controlled component (see section 2.4).

### 2.3 Token Budget: Deterministic Priority-Based Reduction

When `estimated_tokens > budget`, the system applies a **deterministic reduction** before sending the prompt. This is not a warning -- it is an action.

**File priority classification (computed per case):**

```python
def classify_file_priority(manifest):
    """Assign priority to each file based on role in the bug."""
    priorities = {}
    bug_file = manifest.reference_fix_file  # from case JSON
    direct_deps = manifest.import_graph.get(bug_file, [])
    reverse_deps = [f for f, deps in manifest.import_graph.items() if bug_file in deps]

    for f in manifest.file_paths:
        if f == bug_file:
            priorities[f] = "CRITICAL"        # always included in full
        elif f in direct_deps or f in reverse_deps:
            priorities[f] = "DIRECT_DEPENDENCY"  # always included in full
        else:
            priorities[f] = "SECONDARY"       # eligible for summarization/drop
    return priorities
```

**Reduction algorithm:**

```python
def reduce_prompt_to_budget(manifest, condition, budget):
    """Deterministic reduction. Returns (prompt, overflow_metadata)."""
    priorities = classify_file_priority(manifest)

    # Level 0: Full prompt (no reduction)
    prompt = build_full_prompt(manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return prompt, {"token_overflow": False}

    # Level 1: Strip blank lines and trailing whitespace from SECONDARY files
    for f in manifest.file_paths:
        if priorities[f] == "SECONDARY":
            manifest.files[f] = _strip_whitespace(manifest.files[f])
    prompt = build_full_prompt(manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return prompt, {"token_overflow": True, "reduction_level": 1,
                        "files_included": list(manifest.file_paths),
                        "files_summarized": [], "files_dropped": []}

    # Level 2: Summarize SECONDARY files (signature-only: def/class lines + docstrings)
    summarized = []
    for f in manifest.file_paths:
        if priorities[f] == "SECONDARY":
            manifest.files[f] = _extract_signatures(manifest.files[f])
            summarized.append(f)
    prompt = build_full_prompt(manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return prompt, {"token_overflow": True, "reduction_level": 2,
                        "files_included": [f for f in manifest.file_paths if f not in summarized],
                        "files_summarized": summarized, "files_dropped": []}

    # Level 3: Drop SECONDARY files entirely
    dropped = []
    included = []
    for f in manifest.file_paths:
        if priorities[f] == "SECONDARY":
            dropped.append(f)
        else:
            included.append(f)
    prompt = build_reduced_prompt(manifest, included, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return prompt, {"token_overflow": True, "reduction_level": 3,
                        "files_included": included,
                        "files_summarized": [], "files_dropped": dropped}

    # Level 4: Cannot fit even CRITICAL + DIRECT files. Flag as infeasible.
    return prompt, {"token_overflow": True, "reduction_level": 4,
                    "infeasible": True,
                    "files_included": included, "files_dropped": dropped}
```

**Invariant:** The overflow metadata is always logged. No silent truncation. If `reduction_level >= 2`, this is a known confound recorded in the result.

**Output format adjustment:** When files are dropped from the prompt, they are ALSO removed from the expected `files` dict in the output instruction. The model is only asked to return files it was shown.

### 2.4 Import Summary: Controlled Component with Calibration Experiment

**Decision: Import summary is NOT assumed neutral. It is treated as a potentially biasing intervention.**

**Default behavior:** Import summary is EXCLUDED from the baseline condition. It is available as an optional component that can be added to any condition.

**Calibration experiment specification:**

```
Experiment: IMPORT_SUMMARY_CALIBRATION
Design: Within-subjects (same cases, same model, two conditions)
  Condition A: baseline (no import summary)
  Condition B: baseline + import summary

Cases: All multi-file cases (N >= 15)
Models: At least 2 (one small, one large)
Metrics:
  - pass_rate_delta = pass_rate_B - pass_rate_A
  - leg_rate_delta = leg_rate_B - leg_rate_A
  - reasoning_correct_delta = reasoning_correct_B - reasoning_correct_A

Interpretation:
  - If |pass_rate_delta| < 3% AND |leg_rate_delta| < 2%:
      Import summary is neutral. May be included in all conditions.
  - If pass_rate_delta > 3%:
      Import summary is a performance-affecting intervention.
      MUST be treated as a separate condition OR excluded entirely.
  - If leg_rate_delta > 2%:
      Import summary affects reasoning quality measurement.
      MUST NOT be included in LEG analysis conditions.

Timeline: Run BEFORE any production ablation with the new system.
Blocking: Results of this experiment determine whether import summary
          is included in the final prompt template.
```

### 2.5 Error Taxonomy: Strict 5-Level Classification

| Error type | Definition | Primary metrics? | LEG analysis? | System metrics? |
|------------|-----------|-----------------|---------------|-----------------|
| `format_violation` | Response missing `files` key, or missing file entries | **No** | **No** | Yes (format compliance rate) |
| `parse_error` | Cannot extract valid JSON from response | **No** | **No** | Yes |
| `reconstruction_failure` | Syntax errors in reconstructed files, or empty file values | **No** | Reasoning only (code=fail) | Yes |
| `execution_error` | Test harness crashes (ImportError, RuntimeError, timeout) | **Yes** (fail) | **Yes** | Yes |
| `logic_failure` | Test runs, invariant check fails | **Yes** (fail) | **Yes** | Yes |
| `logic_pass` | Test runs, invariant check passes | **Yes** (pass) | **Yes** | Yes |

**Metric inclusion rules, formally:**

```python
def include_in_primary_metrics(result) -> bool:
    """Only results where reconstruction succeeded and tests ran."""
    return result["error_type"] in ("execution_error", "logic_failure", "logic_pass")

def include_in_leg_analysis(result) -> bool:
    """Only results where we have both execution outcome AND evaluable reasoning."""
    return (include_in_primary_metrics(result)
            or (result["error_type"] == "reconstruction_failure"
                and result["reasoning"] is not None
                and len(result["reasoning"].strip()) > 0))

def include_in_system_metrics(result) -> bool:
    """All results."""
    return True
```

**LEG nuance for reconstruction_failure:** If reconstruction fails due to syntax errors but the model's `reasoning` field contains substantive analysis, we can still evaluate reasoning correctness via the LLM classifier. Code is scored as `code_correct=False` (it didn't run). This enables LEG detection: the model may have diagnosed the bug correctly but produced syntactically invalid code.

**format_violation and parse_error are EXCLUDED from LEG analysis.** Rationale: if the model didn't produce a parseable response, there is no reliable reasoning field to evaluate. Including these would inflate LEG rates with noise.

---

## 3. FAILURE MODE FIXES (REWRITTEN)

### 3.1 Concatenation -> Real Filesystem Modules

**Current:** `exec_eval.py:689-728` concatenates all files with `"\n\n".join()`, strips imports, executes via `exec()`.

**New:** Each file written to its full relative path under `tmpdir`. Python's import system resolves cross-file imports naturally. No concatenation anywhere in the execution path.

**Why correct:** Python's module system is designed for separate files. Concatenation destroyed module identity, caused last-definition-wins shadowing, and required import stripping. All of these artifacts disappear.

**What about test functions?** Tests are rewritten to accept `mods` dict (section 1.3). Each module is imported independently. Cross-module calls work through real Python imports within the subprocess.

### 3.2 Import Stripping -> Deletion

**Current:** `parse.py:404-433` `strip_local_imports()` deletes non-stdlib imports. Two inconsistent STDLIB lists exist (`parse.py:397` vs `validate_cases_v2.py:29`).

**New:** `strip_local_imports()` is not called in any execution path. Files import each other via standard Python imports. The function and both STDLIB lists are deleted.

**`validate_cases_v2.py`** is also updated to use the new subprocess-based execution (it currently concatenates too).

### 3.3 sys.modules Leakage -> Subprocess Isolation

**Current:** `exec_eval.py:34-54` registers modules in `sys.modules` via `exec()`.

**New:** Each case runs in a subprocess. When the subprocess exits, all state is reclaimed. Parent process `sys.modules` is never touched.

### 3.4 Thread Safety -> Subprocess Isolation

**Current:** `ThreadPoolExecutor` shares memory. `random.random` monkey-patching is globally visible.

**New:** Each thread spawns a subprocess. Monkey-patching (if any test still needs it) happens inside the subprocess, invisible to other threads.

### 3.5 Parser Tier Bias -> Tier Classification + Metric Exclusion

**Current:** 4-tier cascade. Raw fallback uses entire response as code. No classification recorded.

**New:** 5-tier cascade with `response_format` tag on every result. Primary metrics include only Tier 0-1 (file_dict, code_dict). Tier 2-3 go to secondary analysis. Tier 4 excluded entirely.

### 3.6 Partial Edit Bias -> Strict Reconstruction (No Fallback)

**Current:** `_assemble_program()` ALWAYS prepends original files. Model that returns one function gets everything for free.

**New:** Primary path: `reconstruct_strict()` FAILS if any file is missing from model output. Model must explicitly return `UNCHANGED` for files it didn't modify. No free assembly. Salvage path exists for secondary analysis only, explicitly tagged.

### 3.7 Token Truncation -> Priority-Based Deterministic Reduction

**Current:** Zero awareness. Silent truncation at API level.

**New:** Token estimation before every call. If over budget, deterministic 4-level reduction with full logging (section 2.3). No silent truncation.

### 3.8 Multi-File vs Single-File Bias -> Unified Execution Path

**Current:** Single-file cases skip assembly. Multi-file cases go through assembly. Different code paths.

**New:** All cases go through the same path: reconstruct -> write to tmpdir -> subprocess harness. Single-file case = one module in `mods`. No special casing.

---

## 4. IMPLEMENTATION PLAN (PHASES, UPDATED)

### Phase 0: Instrumentation + STDLIB Fix (no behavior change)

**Changes:**

1. **Delete duplicate STDLIB lists.** Create `_stdlib.py` with single canonical `STDLIB_MODULES`. Both `parse.py` and `validate_cases_v2.py` import from it.

2. **Add `response_format` tag** to `parse.py:parse_model_response()`. Every return dict gets a `"response_format"` key. Values: `"json_direct"`, `"json_lenient"`, `"json_substring"`, `"code_block"`, `"raw_fallback"`.

3. **Add token counting** to `execution.py:run_single()`. Install `tiktoken`. Log `prompt_tokens` and `token_budget_exceeded` in every record.

4. **Add empty-file assertion** in `runner.py:load_cases()`.

5. **Add file-dict parser tier** (`_try_file_dict()`) as Tier 0 in `parse.py`. Does NOT change behavior for existing prompts (they don't produce `files` key). Only activates when model responds with new format.

**What stays the same:** All execution logic, all prompts, all scoring, all test functions.

**Risks:** Minimal (additive instrumentation).

**Rollback:** Remove new log fields. One-line changes.

**Deliverable:** Run existing benchmark. Analyze: response_format distribution, token counts per case/condition, assembly crutch rates.

---

### Phase 1: Output Format + Strict Reconstruction

**Changes:**

1. **New `_JSON_OUTPUT_INSTRUCTION_V2`** in `llm.py` requesting `files` dict format with full relative paths and UNCHANGED sentinel.

2. **New `reconstructor.py`** module with `reconstruct_strict()` and `reconstruct_salvage()` as specified in section 1.5.

3. **New `_format_code_files_v2()`** in `prompts.py` with `### FILE N/M: full/relative/path.py ###` delimiters and dependency-ordered listing.

4. **Wire new parser + reconstructor into execution pipeline.** When `response_format == "file_dict"`:
   - Call `reconstruct_strict(manifest, parsed_files)`
   - If `status == "SUCCESS"`: proceed to execution (still old backend in Phase 1)
   - If `status != "SUCCESS"`: record as `reconstruction_failure`, score 0, do NOT execute

   When `response_format == "code_string"` (old format):
   - Use old `_assemble_program()` path (Phase 1 only -- removed in Phase 3)
   - Tag result as `legacy_path=True`

5. **Token budget reduction** (section 2.3). `reduce_prompt_to_budget()` applied before every `call_model()`.

6. **Import summary calibration experiment** run (section 2.4). Results determine whether import summary is included going forward.

**What stays the same:** Execution backend (still in-process `exec()`). All test functions. All conditions/nudges.

**Risks:**
- Models may not follow file-dict format initially. **Mitigation:** Tier 2 (code_string) fallback exists. Track format compliance rate.
- Token reduction may change results for large cases. **Mitigation:** `reduction_level` logged. Cases with reduction_level >= 2 flagged in analysis.

**Rollback:** Set `_JSON_OUTPUT_INSTRUCTION = _JSON_OUTPUT_INSTRUCTION_V1`. Bypass reconstructor. One flag flip.

---

### Phase 2: Subprocess Execution + Test Rewrite

**Changes:**

1. **New `subprocess_eval.py`** module implementing `evaluate_in_subprocess()` as specified in section 1.2.

2. **Rewrite all 58 test functions across 28 test files** to use `test(mods)` signature instead of `test(mod)`.

   Mechanical transformation:
   ```python
   # OLD:
   def test(mod):
       save_user = getattr(mod, "save_user", None)
       get_display_name = getattr(mod, "get_display_name", None)

   # NEW:
   def test(mods):
       save_user = getattr(mods["user_service"], "save_user", None)
       get_display_name = getattr(mods["cache_reader"], "get_display_name", None)
   ```

   Each test file's rewrite requires knowing which functions live in which module. This mapping comes from the case manifest (which module defines which symbols). For single-file cases, the test simply accesses the one module in `mods`.

   **This rewrite is validated by running `validate_cases_v2.py` with the new execution backend** (see Phase 2 validation below).

3. **New test harness generator** `_generate_harness()` as specified in section 1.3.

4. **Update `exec_evaluate()`** to dispatch to subprocess path when reconstruction result is available:
   ```python
   def exec_evaluate(case, code_or_recon_result):
       if isinstance(code_or_recon_result, ReconstructionResult):
           if code_or_recon_result.status != "SUCCESS":
               return _result(case_id, False, 0.0,
                              [f"reconstruction failed: {code_or_recon_result.status}"],
                              ...)
           return _exec_evaluate_subprocess(case, code_or_recon_result)
       else:
           # Legacy path -- TEMPORARY, removed in Phase 3
           return _exec_evaluate_legacy(case, code_or_recon_result)
   ```

5. **Update `validate_cases_v2.py`** to use subprocess execution. This serves as the primary validation that the test rewrite is correct.

**Phase 2 validation (BLOCKING):**
- Run `validate_cases_v2.py` on ALL cases with BOTH old and new backends.
- Every case that passes with old backend MUST pass with new backend.
- Every case that fails with old backend MUST fail with new backend.
- Any discrepancy is investigated before proceeding.

**What stays the same:** All prompt logic. All conditions/nudges. `evaluator.py`. `RunLogger`. `runner.py` orchestration.

**Risks:**
- Test rewrite introduces bugs. **Mitigation:** `validate_cases_v2.py` equivalence check is blocking.
- Cross-module state reset in tests may not work the same way. Old tests did `getattr(mod, "_store", None)` and cleared it. New tests do `getattr(mods["cache_writer"], "_store", None)`. State is now per-module (correct), but may require adjusting reset logic. **Mitigation:** Each test is individually validated.
- Subprocess overhead. ~0.2s per case x 1250 evals = ~4 min extra on a 20-30 min run. Acceptable.

**Rollback:** Flag `USE_SUBPROCESS = False` in exec_eval.py. Legacy path still exists.

---

### Phase 3: Legacy Removal + Hardening

**Trigger for Phase 3:** ALL of the following must be true:
1. Phase 2 validation passes (100% equivalence on validate_cases_v2)
2. At least one full ablation run completes with new system
3. Import summary calibration experiment is complete
4. format_violation rate is under 20% for target models

**Changes:**

1. **Delete legacy execution path:**
   - Remove `_assemble_program()` from `exec_eval.py`
   - Remove `_exec_evaluate_legacy()` branch
   - Remove `load_module_from_code()` (no callers left)
   - Remove `strip_local_imports()` from `parse.py`
   - Remove `_stdlib.py` (no callers left)
   - Remove `_JSON_OUTPUT_INSTRUCTION_V1` from `llm.py`

2. **Delete parser Tiers 2-4 from primary path.** Keep them in a `_legacy_parse.py` module for forensic analysis of old logs. The primary `parse_model_response()` accepts ONLY Tier 0 (file_dict) and Tier 1 (code_dict). Anything else returns `parse_error`.

3. **Enforce metric inclusion rules** with runtime assertions:
   ```python
   def compute_primary_metrics(results):
       for r in results:
           assert r["error_type"] not in ("format_violation", "parse_error"), \
               f"BUG: {r['error_type']} in primary metrics for {r['case_id']}"
   ```

4. **Validation test suite** (`tests/test_pipeline.py`):
   - Roundtrip test (all UNCHANGED -> identical)
   - Missing file rejection test
   - Import resolution test (multi-file cross-import)
   - Cross-case isolation test
   - Token budget reduction test
   - Parallel safety test
   - Format robustness test (minor whitespace, trailing commas)

5. **Update `validate_cases_v2.py`** to remove all concatenation code. It now uses exclusively the subprocess path.

**What is permanently removed:**
- `strip_local_imports()` and all STDLIB lists
- `_assemble_program()` and the concatenation model
- `load_module_from_code()` and in-process `exec()`
- Old parser fallback tiers (from primary path)
- `_JSON_OUTPUT_INSTRUCTION_V1`

**Rollback:** Not possible without reverting to Phase 2 state. This is intentional -- Phase 3 should only be entered when Phase 2 is fully validated.

---

## 5. VALIDATION PLAN (EXPANDED)

### 5.1 Roundtrip Test

```python
def test_roundtrip_all_unchanged():
    for case in load_all_cases():
        manifest = build_manifest(case)
        model_response = {"files": {f: "UNCHANGED" for f in manifest.file_paths}}
        result = reconstruct_strict(manifest, model_response)
        assert result.status == "SUCCESS"
        assert result.files == manifest.files
        assert result.changed_files == set()
        assert result.missing_files == set()
```

### 5.2 Old vs New System Comparison (BLOCKING for Phase 2)

**Run on: ALL cases x baseline condition x gpt-4.1-nano**

| Check | Old system | New system | Expected |
|-------|-----------|-----------|----------|
| Case passes | True | True | Same |
| Case fails | True | True | Same |
| Case passes (old) but fails (new) | -- | -- | Investigate: was old inflated by assembly? |
| Case fails (old) but passes (new) | -- | -- | Investigate: was old broken by concatenation? |

Acceptable: new system may show FEWER passes on multi-file cases (assembly crutch removed). This is correct.

Unacceptable: new system shows FEWER passes on single-file cases (these should be identical).

### 5.3 Multi-File Import Resolution Stress Test

```python
def test_cross_module_imports():
    """3-file case with chain: api -> service -> models."""
    files = {
        "code_snippets/test_case/models.py":
            "class Account:\n    def __init__(self): self.balance = 0",
        "code_snippets/test_case/service.py":
            "from models import Account\ndef create(): return Account()",
        "code_snippets/test_case/api.py":
            "from service import create\ndef handle(): a = create(); return a.balance",
    }
    test_src = '''
def test(mods):
    handle = getattr(mods["api"], "handle", None)
    if not handle: return False, ["handle not found"]
    result = handle()
    if result != 0: return False, [f"expected 0, got {result}"]
    return True, ["ok"]
'''
    result = evaluate_in_subprocess("cross_import_test", files, test_src)
    assert result["pass"]
```

### 5.4 Format Robustness Test

```python
def test_whitespace_in_unchanged():
    """UNCHANGED with surrounding whitespace still recognized."""
    manifest = build_manifest(SAMPLE_CASE)
    model_files = {f: "  UNCHANGED  " for f in manifest.file_paths}
    result = reconstruct_strict(manifest, model_files)
    assert result.status == "SUCCESS"

def test_missing_file_rejected():
    """Response missing one file -> FAILED_MISSING_FILES."""
    manifest = build_manifest(MULTI_FILE_CASE)
    model_files = {manifest.file_paths[0]: "UNCHANGED"}  # missing 3 files
    result = reconstruct_strict(manifest, model_files)
    assert result.status == "FAILED_MISSING_FILES"
    assert len(result.missing_files) == len(manifest.file_paths) - 1

def test_extra_file_recorded():
    """Response with extra files -> recorded in extra_files, but SUCCESS."""
    manifest = build_manifest(SAMPLE_CASE)
    model_files = {f: "UNCHANGED" for f in manifest.file_paths}
    model_files["nonexistent.py"] = "# extra"
    result = reconstruct_strict(manifest, model_files)
    assert result.status == "SUCCESS"
    assert "nonexistent.py" in result.extra_files
```

### 5.5 Cross-Case Isolation Test

```python
def test_no_state_leakage():
    files_a = {"code_snippets/a/shared.py": "STATE = []\ndef mutate(): STATE.append(1)"}
    files_b = {"code_snippets/b/shared.py": "STATE = []\ndef check(): return len(STATE)"}

    test_a = 'def test(mods): mods["shared"].mutate(); return True, ["ok"]'
    test_b = 'def test(mods): n = mods["shared"].check(); return (n == 0, [f"leaked: {n}"])'

    evaluate_in_subprocess("a", files_a, test_a)
    result_b = evaluate_in_subprocess("b", files_b, test_b)
    assert result_b["pass"], "State leaked between subprocesses"
```

### 5.6 Import Summary Calibration (section 2.4)

Run before Phase 3. Results determine whether import summary enters the prompt template.

### 5.7 Token Budget Reduction Validation

```python
def test_reduction_levels():
    """Verify each reduction level produces valid, shorter prompts."""
    manifest = build_manifest(LARGE_CASE)  # 5+ files

    for budget in [20000, 5000, 2000, 500]:
        prompt, metadata = reduce_prompt_to_budget(manifest, "baseline", budget)
        actual_tokens = estimate_tokens(prompt)
        if not metadata.get("infeasible"):
            assert actual_tokens <= budget, \
                f"Reduction failed: {actual_tokens} > {budget}"
        # Verify metadata is complete
        assert "files_included" in metadata
        assert "files_dropped" in metadata
        assert "files_summarized" in metadata
```

---

## 6. RISK ANALYSIS + MITIGATIONS

### R1: Test Rewrite Introduces Bugs

**Risk:** 58 test functions rewritten. Any bug invalidates evaluation.

**Likelihood:** Medium. The transformation is mechanical but touches every test.

**Mitigation:**
- `validate_cases_v2.py` equivalence check is BLOCKING for Phase 2.
- Each test is run against the reference fix (must pass) AND the buggy code (must fail).
- A script generates the `mods` key mapping from case JSON + AST analysis, reducing manual error.

### R2: Models Fail to Produce File-Dict Format

**Risk:** Pass rate drops due to format_violation, not reasoning failure.

**Likelihood:** High for weaker models. gpt-4.1-nano may struggle.

**Mitigation:**
- Format violations are EXCLUDED from primary metrics. They show up in system metrics (format compliance rate).
- If format compliance < 80% for a model, we report this as a limitation.
- The output instruction is tunable. We can add examples, simplify wording, etc.

### R3: Priority-Based Token Reduction Changes Results

**Risk:** Dropping or summarizing secondary files changes the information available to the model.

**Likelihood:** Low (most cases fit within budget). When triggered, results are flagged.

**Mitigation:**
- `reduction_level` logged in every result.
- Analysis stratifies by reduction level.
- Cases with `reduction_level >= 2` are flagged as confounded.

### R4: Subprocess Overhead

**Risk:** 0.2s per subprocess x 1250 evals = 4 extra minutes.

**Likelihood:** Certain but acceptable.

**Mitigation:** Not needed. 4 minutes on a 20-30 minute API-bound run is negligible.

### R5: Import Summary Experiment Shows Bias

**Risk:** Import summary significantly changes pass rates, invalidating conditions that included it.

**Likelihood:** Unknown (that's why we're testing).

**Mitigation:** The experiment is run BEFORE import summary is deployed. If it shows bias, import summary is excluded or treated as a separate condition. No results are retroactively invalidated because import summary is not used until the experiment clears it.

### R6: Salvage Path Leaks into Primary Metrics

**Risk:** Programming error causes salvaged results to be counted in primary metrics, inflating pass rates.

**Mitigation:** Runtime assertion in metric computation:
```python
assert all(r["reconstruction_mode"] != "salvaged" for r in primary_results), \
    "BUG: salvaged results in primary metrics"
```

### R7: Directory Structure Causes Import Resolution Differences

**Risk:** Files in `code_snippets/hidden_dependency_hard/` import each other with `from cache_writer import cache_put` (flat import), but the directory structure creates a package. Python may require `from code_snippets.hidden_dependency_hard.cache_writer import cache_put`.

**Likelihood:** High. This is a real issue.

**Mitigation:** PYTHONPATH must include the case-specific subdirectory, not just tmpdir root.

```python
# For case with files in code_snippets/hidden_dependency_hard/
# PYTHONPATH = tmpdir/code_snippets/hidden_dependency_hard
case_dir = _find_common_parent(manifest.file_paths)
python_path = str(Path(tmpdir) / case_dir)
```

This means `cache_writer.py` is importable as `import cache_writer` from within the subprocess, matching how the original source files import each other.

The full directory structure is still written to disk (preserving path integrity), but PYTHONPATH points to the leaf directory where the `.py` files live. This is the ONLY correct behavior -- it matches what the original code expects.

**Validation:** The multi-file import stress test (section 5.3) explicitly tests this.

### R8: Legacy Removal is Irreversible

**Risk:** Phase 3 deletes legacy code. If issues are discovered later, rollback requires git revert.

**Mitigation:**
- Phase 3 entrance criteria are strict (section 4, Phase 3).
- Git history preserves all deleted code.
- Phase 3 is only entered after a full ablation run validates Phase 2.
- The legacy code is moved to `_legacy/` directory before deletion, tagged with a git commit, so it's trivially recoverable.
