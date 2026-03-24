# T3 Code Generation Pipeline -- Full Audit and Redesign

**Date:** 2026-03-24
**Scope:** Module loading, prompt construction, execution pipeline for multi-file code generation evaluation
**Status:** Complete audit with actionable redesign

---

## 1. FAILURE MODES (grounded in current code)

### A. Prompt Construction Failures

**A1. File boundary ambiguity in prompt**
`prompts.py:225-229` -- `_format_code_files()` formats files as:
```
=== path/to/file.py ===
\```python
<code>
\```
```
The delimiter `=== path ===` is **not machine-parseable from the LLM's perspective**. There is no explicit "this is file 1 of N" or "FILE_START/FILE_END" marker. The model must infer file boundaries from a human-readable convention. If a file internally contains `===` strings or markdown code fences, boundaries become ambiguous.

**A2. No file ordering contract**
`prompts.py:226-228` iterates `code_files.items()`. In Python 3.7+ dict ordering is insertion-order, which comes from `cases.json`'s `code_files` array. But there is **no explicit ordering specification** in the prompt itself. The model receives files in whatever order `cases.json` lists them. If two cases list files in different orders for the same bug pattern, this is a confound.

**A3. Missing files are silently skipped**
`runner.py:110-113` -- `load_cases()` reads files from disk:
```python
for rel_path in case["code_files"]:
    full_path = BASE_DIR / rel_path
    code_files[rel_path] = full_path.read_text(encoding="utf-8").strip()
```
If `full_path` doesn't exist, this **crashes**. That's correct (fail-fast). But there's **no check that all files loaded successfully before prompt construction**. If a file is empty after `.strip()`, it's silently included as an empty string.

**A4. No token budget enforcement**
`llm.py:47` appends `_JSON_OUTPUT_INSTRUCTION` to every non-raw prompt. There is **zero token counting**. For large multi-file cases (e.g., `l3_state_pipeline` with 5 files + nudge text + JSON instruction), the total prompt can exceed a model's context window. The system has no awareness of this. OpenAI would silently truncate or error, and the system would record a parse failure -- **biasing results against cases with more files**.

**A5. JSON instruction appended unconditionally**
`llm.py:47`: `full_prompt = prompt if raw else prompt + _JSON_OUTPUT_INSTRUCTION`. The JSON output instruction is 200+ tokens. For non-raw calls, this is always appended -- even when the condition's prompt (e.g., structured_reasoning) has its own output format specification. **Two competing output format instructions** corrupt the model's response.

**A6. Hidden dependency omission -- no dependency graph in prompt**
The prompt includes source files but **never explains import relationships**. The model must infer that `from cache_writer import sync_user_to_cache` in `user_service.py` means `sync_user_to_cache` is defined in `cache_writer.py`. For models with weak cross-file reasoning, this is a silent penalty.

**A7. Context overload for nudged conditions**
`prompts.py:207-218` -- diagnostic and guardrail nudges add 300-600 tokens each. Combined with 4-5 source files, the JSON instruction, and the task, the total prompt for `guardrail_strict` can reach 3000+ tokens. Models with smaller effective context are disproportionately penalized. **This is an uncontrolled confound** across conditions.

### B. Multi-File Semantics Failures

**B1. Import stripping destroys cross-file semantics**
`parse.py:404-433` -- `strip_local_imports()` removes all non-stdlib imports. This is applied both at **prompt assembly time** (via `exec_eval.py:42`) and when loading modules. The problem: models that produce `from cache_writer import cache_put` are having that import silently deleted. If the model's code depends on that import for semantic correctness, the stripped version may pass tests only because of the assembly step -- not because the model produced correct code.

**B2. Concatenation destroys module boundaries**
`validate_cases_v2.py:63-68` -- `load_case_code()` joins all files with `"\n\n".join()`. `exec_eval.py:689-702` does the same in `_assemble_program()`. After concatenation, if two files define the same function name (e.g., `clear()` in file A and file B), **Python's last-definition-wins** behavior silently picks one. There is no namespacing.

**B3. Relative vs absolute import mismatch**
The case files use `from cache_writer import cache_put` (absolute, treating siblings as top-level). After concatenation and import stripping, these references resolve only if the function is defined in the same concatenated namespace. If a model produces `from .cache_writer import cache_put` (relative import), the import stripper may not catch it (it only strips `from .` prefix lines -- `parse.py:422`), causing a runtime crash scored as a model failure.

**B4. Module-level state initialization order**
When files are concatenated, module-level code executes top-to-bottom. If file A initializes `_store = {}` and file B's module-level code reads from `_store`, the order in `case["code_files"]` determines whether it works. **This is a hidden dependency on JSON array order.**

**B5. Assembly overlay semantics are fragile**
`exec_eval.py:661-744` -- `_assemble_program()` prepends original (buggy) files, then appends model output. The model's definitions override the originals via Python's last-definition-wins. But:
- If the model only redefines 2 of 4 functions, the other 2 remain buggy.
- If the model defines a function with a different name (rename), the original buggy function still runs (`rename_error` detection at line 717-725 catches this but only for the primary fix target).
- Constants and class definitions from originals persist and may conflict with model's versions.

### C. LLM Interaction Failures

**C1. Model returns multi-file code as single block**
`parse.py:42-52` -- When the model returns `{"code": {"file1.py": "...", "file2.py": "..."}}` (a dict), the parser joins them with `# filename\ncontent` comments. This destroys file boundaries. The assembled code is then treated as a single flat namespace. This is a **data loss** failure.

**C2. Model produces partial edits**
The prompt asks the model to "return the updated code" -- all of it. But models frequently return only the changed function(s). The `_assemble_program()` step compensates by prepending originals. However, this means a model that returns complete files (overriding everything) and a model that returns one function (relying on assembly) are scored identically. **This conflates model capability with infrastructure scaffolding.**

**C3. Model ignores some files entirely**
For the 5-file `l3_state_pipeline` case, a model may fix only `pipeline.py` and ignore `state.py`, `selectors.py`, etc. The assembly step fills in the originals, so the fix may still pass -- but only if the bug is localized to `pipeline.py`. If the model should have changed `state.py` too, the assembly masks the failure.

**C4. Raw fallback contaminates scoring**
`parse.py:202-215` -- When no JSON or code blocks are found, the **entire raw response** (including English reasoning) is used as code. This inevitably fails to compile, scored as `pass=False`. But the failure is classified alongside genuine logic failures, **conflating model formatting with model reasoning**.

**C5. Code-as-dict silently munged**
`parse.py:42-52` -- When the model returns code as a dict, it's converted to `# filename\ncontent`. This transformation is logged as SEVERE but **execution continues**. The resulting code may have duplicate definitions or broken references due to the artificial concatenation.

### D. Reconstruction Failures

**D1. No file-level output mapping**
The system extracts a **single code string** from the model's response. There is no mechanism to map model output back to specific files. `extract_all_code_blocks()` (`parse.py:377-390`) attempts to find filename hints in comments above code blocks, but this is best-effort heuristic matching with no guarantees.

**D2. Assembly may produce duplicate definitions silently passing**
`exec_eval.py:706-708` detects duplicates between original and model code, flagging `assembly_risky=True`. But this flag is **informational only** -- execution proceeds regardless. A model that accidentally redefines a helper function with different behavior may silently break invariants that the test doesn't specifically check.

**D3. No structural validation of reconstructed code**
After assembly, the code is `exec()`'d. There is no AST validation that expected functions exist, have correct signatures, or maintain expected class hierarchies. If the model changes a function signature, it may pass the invariant test but break callers that the test doesn't exercise.

**D4. Import stripping can break stdlib usage**
`parse.py:397-401` -- `STDLIB_MODULES` is a manual list of 20 modules. If a case uses `datetime`, `enum`, `logging`, or other stdlib modules **not in this list**, their imports get stripped. `validate_cases_v2.py:29-33` has a different, broader list. **Inconsistency between the two strippers is a latent bug.**

### E. Execution Environment Failures

**E1. No PYTHONPATH isolation**
`exec_eval.py:34-54` -- `load_module_from_code()` registers modules in `sys.modules`. These persist across cases within the same process. If case A defines a module with a function `foo()` and case B also defines `foo()` but expects different behavior, stale `sys.modules` entries can leak. The `_load_counter` mitigates name collisions but **does not prevent cross-case state pollution via global objects**.

**E2. Working directory not controlled**
No code sets `os.chdir()` or controls CWD before execution. If a case's code uses relative file paths, behavior depends on where the runner was invoked.

**E3. Thread-safety gaps in parallel mode**
`runner.py:213` -- `ThreadPoolExecutor` shares a single process. `sys.modules` mutations in `load_module_from_code()` are **globally visible to all threads**. `itertools.count()` is atomic on CPython (`exec_eval.py:31`) but `sys.modules[mod_name] = mod` is not guarded by the GIL for the full registration sequence. This is a **data race** under parallel execution.

**E4. No subprocess isolation for test execution**
All code is `exec()`'d in-process. A misbehaving model output could modify global state (`sys.path`, `os.environ`, imported modules) and contaminate subsequent cases. There is no sandbox.

**E5. random.random monkey-patching is not thread-safe**
`exec_eval.py:244-254` -- `_test_retry_causality` patches `random.random` globally. Under `--parallel > 1`, another thread executing simultaneously would see the patched random, producing non-deterministic test results.

### F. Evaluation Bias

**F1. Assembly scaffolding benefits models that produce partial code**
Models that return only the changed function get the full original codebase prepended. Models that attempt to return all files but get one wrong are penalized more harshly. **This systematically benefits less capable models** that produce minimal output.

**F2. Parse tier fallback biases toward models that follow format**
The 4-tier parser (`parse.py:171-215`) tries JSON -> lenient JSON -> JSON substring -> code block -> raw. Models that happen to match an earlier tier get cleaner code extraction. Models that produce valid code but outside expected wrappers get the raw fallback, which almost always fails. **This is a formatting test, not a reasoning test.**

**F3. Token-count asymmetry across conditions**
`baseline` gets `task + files` only. `guardrail_strict` gets `task + files + guardrail nudge + hard_constraints`. The latter can be 2-3x longer. For models near context limits, this silently degrades performance. **This confounds nudge effectiveness with context capacity.**

**F4. Multi-file cases are disproportionately noisy**
Assembly introduces reconstruction noise (duplicates, ordering, import stripping). Single-file cases bypass assembly entirely (`exec_eval.py:679-687`). Multi-file case results are systematically less reliable than single-file results. **Any comparison that pools both types is biased.**

**F5. Lenient parser accepts malformed JSON with data loss**
`parse.py:82-122` -- `_try_json_lenient` uses regex to extract code from malformed JSON. The regex `r'"code"\s*:\s*"(.*)"` may capture only part of the code field if the code contains unescaped quotes. **Silent data truncation** is logged but not flagged in results.

**F6. LLM classifier uses truncated inputs**
`evaluator.py:165-167` -- task is truncated to 800 chars, code to 2000 chars, reasoning to 1000 chars. For multi-file cases, 2000 chars of code is roughly 50 lines -- capturing maybe 1-2 of 4 files. The classifier makes judgments on **incomplete information**, systematically disadvantaging complex cases.

---

## 2. BEST PRACTICES

### 2.1 File Representation in Prompt

**Canonical format** (unambiguous, machine-parseable):

```
# FILE MANIFEST
# Total files: 4
# Files: cache_writer.py, cache_reader.py, user_repo.py, user_service.py

### FILE 1 of 4: cache_writer.py ###
```python
<full file contents>
```
### END FILE: cache_writer.py ###

### FILE 2 of 4: cache_reader.py ###
```python
<full file contents>
```
### END FILE: cache_reader.py ###
```

**Rules:**
- Every file has an explicit start marker with ordinal (N of M) and filename
- Every file has an explicit end marker repeating the filename
- The manifest at the top lists all files and their count
- Files are ordered deterministically: **topological sort by import dependency**, with ties broken alphabetically
- Empty files are never included -- if a file is empty, the case is invalid

### 2.2 Prompt Structure

```
[SYSTEM]
You are fixing a bug in a Python codebase.

[TASK]
{task description}

[CODEBASE]
{file manifest + file blocks per 2.1}

[IMPORT RELATIONSHIPS]
- user_service.py imports from: cache_writer.py (sync_user_to_cache), user_repo.py (save_to_db)
- cache_reader.py imports from: cache_writer.py (_store)

[BUG DESCRIPTION]
{task -- reworded as bug if needed}

[CONDITION-SPECIFIC NUDGE]
{diagnostic/guardrail/etc. -- ONLY if condition != baseline}

[OUTPUT FORMAT]
{see 2.3}
```

**Order rationale:**
1. System role first (primes the model)
2. Task before code (model reads code with task in mind)
3. Import relationships explicitly stated (removes inference burden -- this is infrastructure, not reasoning)
4. Nudge after code (references specific functions the model just read)
5. Output format last (freshest in context, most likely to be followed)

### 2.3 LLM Output Format

**Choice: Full-file rewrites** (not diffs).

**Justification:**
- Diffs require models to count line numbers accurately -- they are bad at this
- Diffs require a diff application step that can fail silently
- Full rewrites are deterministic to reconstruct -- what you see is what you get
- Full rewrites are larger but modern context windows handle 4-5 file rewrites
- For your benchmark, correctness > token efficiency

**Enforced format:**

```
Return your response as JSON:
{
  "reasoning": "your analysis of the bug",
  "files": {
    "cache_writer.py": "full updated contents of cache_writer.py",
    "cache_reader.py": "full updated contents of cache_reader.py (or UNCHANGED if not modified)",
    "user_repo.py": "UNCHANGED",
    "user_service.py": "full updated contents of user_service.py"
  }
}

Rules:
- The "files" object MUST contain an entry for EVERY file listed in the manifest.
- If a file is not modified, set its value to the exact string "UNCHANGED".
- Do NOT omit any file from the "files" object.
- Each file value must contain the COMPLETE file contents, not a diff or partial edit.
- Do NOT include markdown formatting inside file values.
```

### 2.4 Reconstruction Rules

1. Parse JSON response -> extract `files` dict
2. For each file in the original manifest:
   - If the file key exists in response and value != "UNCHANGED": use model's version
   - If the file key exists and value == "UNCHANGED": use original version
   - If the file key is **missing**: **REJECT THE RESPONSE** (model violated format contract)
3. Validate: the set of filenames in reconstructed repo == the set in original manifest (exactly)
4. Validate: every reconstructed file parses as valid Python (`ast.parse()`)
5. If any validation fails: record as `format_violation`, score 0, do NOT attempt execution

### 2.5 Execution Environment

```python
# For each case evaluation:
import tempfile, subprocess, sys

with tempfile.TemporaryDirectory() as tmpdir:
    # Write reconstructed files to tmpdir preserving directory structure
    for filepath, content in reconstructed_files.items():
        (Path(tmpdir) / filepath).parent.mkdir(parents=True, exist_ok=True)
        (Path(tmpdir) / filepath).write_text(content)

    # Run test as subprocess with controlled environment
    result = subprocess.run(
        [sys.executable, "-c", test_runner_code],
        cwd=tmpdir,
        env={"PYTHONPATH": tmpdir, "PATH": os.environ["PATH"]},
        capture_output=True,
        timeout=30,
    )
```

**Rules:**
- Each case runs in a **subprocess** with a **clean temp directory**
- `PYTHONPATH` is set to the temp directory root
- No shared state between cases
- Timeout enforced (30s default)
- Imports resolve naturally because files are on disk with correct names

---

## 3. ARCHITECTURE PROPOSAL

### Core Design: File Manifest System with Subprocess Isolation

```
+----------------+     +-----------------+     +----------------+
| Case Loader    |---->| Prompt Builder  |---->| LLM Client     |
| (manifest)     |     | (canonical)     |     | (token-aware)  |
+----------------+     +-----------------+     +-------+--------+
                                                        |
                                                        v
+----------------+     +-----------------+     +----------------+
| Result Logger  |<----| Evaluator       |<----| Reconstructor  |
| (append-only)  |     | (subprocess)    |     | (strict)       |
+----------------+     +-----------------+     +----------------+
```

### 3.1 Case Loader (`case_loader.py`)

```python
@dataclass
class CaseManifest:
    case_id: str
    files: dict[str, str]         # filename -> content (ordered)
    file_order: list[str]         # explicit ordering
    import_graph: dict[str, list[str]]  # file -> [files it imports from]
    task: str
    failure_mode: str
    hard_constraints: list[str]
    test_module: str              # path to test file
    test_function: str            # function name in test file
    total_token_estimate: int     # pre-computed

def load_case(case_dict: dict, base_dir: Path) -> CaseManifest:
    files = {}
    for rel_path in case_dict["code_files"]:
        content = (base_dir / rel_path).read_text(encoding="utf-8")
        assert content.strip(), f"Empty file: {rel_path}"
        filename = Path(rel_path).name
        files[filename] = content

    import_graph = _compute_import_graph(files)
    file_order = _topological_sort(files.keys(), import_graph)

    return CaseManifest(
        case_id=case_dict["id"],
        files=files,
        file_order=file_order,
        import_graph=import_graph,
        task=case_dict["task"],
        failure_mode=case_dict["failure_mode"],
        hard_constraints=case_dict.get("hard_constraints", []),
        test_module=...,
        test_function=...,
        total_token_estimate=_estimate_tokens(files, case_dict["task"]),
    )
```

### 3.2 Prompt Builder (`prompt_builder.py`)

```python
def build_prompt(manifest: CaseManifest, condition: str,
                 token_budget: int = 8000) -> tuple[str, PromptMetadata]:
    """Build prompt with token awareness. Returns (prompt, metadata)."""

    # Pre-check: will this fit?
    estimated = manifest.total_token_estimate + _condition_overhead(condition)
    if estimated > token_budget:
        raise TokenBudgetExceeded(
            f"Case {manifest.case_id} needs ~{estimated} tokens, "
            f"budget is {token_budget}"
        )

    sections = []
    sections.append(_system_section())
    sections.append(_task_section(manifest.task))
    sections.append(_codebase_section(manifest))  # uses canonical format from 2.1
    sections.append(_imports_section(manifest.import_graph))

    if condition != "baseline":
        sections.append(_condition_section(manifest, condition))

    sections.append(_output_format_section(manifest.file_order))

    prompt = "\n\n".join(sections)

    metadata = PromptMetadata(
        case_id=manifest.case_id,
        condition=condition,
        file_count=len(manifest.files),
        file_order=manifest.file_order,
        token_estimate=estimated,
        has_nudge=condition != "baseline",
    )

    return prompt, metadata
```

### 3.3 Reconstructor (`reconstructor.py`)

```python
@dataclass
class ReconstructionResult:
    success: bool
    files: dict[str, str]         # filename -> final content
    model_changed: set[str]       # filenames the model modified
    model_unchanged: set[str]     # filenames marked UNCHANGED
    model_missing: set[str]       # filenames model failed to include
    validation_errors: list[str]
    format_violation: bool

def reconstruct(manifest: CaseManifest, model_response: dict) -> ReconstructionResult:
    """Strictly reconstruct repo from model response.

    model_response must have a 'files' dict mapping filename -> content|"UNCHANGED".
    """
    model_files = model_response.get("files", {})

    if not isinstance(model_files, dict):
        return ReconstructionResult(
            success=False, files={}, model_changed=set(),
            model_unchanged=set(), model_missing=set(manifest.file_order),
            validation_errors=["'files' is not a dict"],
            format_violation=True,
        )

    expected = set(manifest.file_order)
    provided = set(model_files.keys())
    missing = expected - provided

    if missing:
        return ReconstructionResult(
            success=False, files={}, model_changed=set(),
            model_unchanged=set(), model_missing=missing,
            validation_errors=[f"Missing files: {missing}"],
            format_violation=True,
        )

    final_files = {}
    changed = set()
    unchanged = set()
    errors = []

    for filename in manifest.file_order:
        value = model_files[filename]
        if value == "UNCHANGED":
            final_files[filename] = manifest.files[filename]
            unchanged.add(filename)
        elif isinstance(value, str) and value.strip():
            # Validate syntax
            try:
                ast.parse(value)
            except SyntaxError as e:
                errors.append(f"{filename}: syntax error: {e}")
            final_files[filename] = value
            changed.add(filename)
        else:
            errors.append(f"{filename}: empty or non-string value")

    return ReconstructionResult(
        success=len(errors) == 0,
        files=final_files,
        model_changed=changed,
        model_unchanged=unchanged,
        model_missing=set(),
        validation_errors=errors,
        format_violation=False,
    )
```

### 3.4 Subprocess Evaluator (`subprocess_eval.py`)

```python
def evaluate_in_subprocess(
    case_id: str,
    reconstructed_files: dict[str, str],
    test_code: str,
    timeout: int = 30,
) -> ExecutionResult:
    """Run reconstructed code + test in isolated subprocess."""

    with tempfile.TemporaryDirectory(prefix=f"t3_{case_id}_") as tmpdir:
        # Write all files to disk
        for filename, content in reconstructed_files.items():
            filepath = Path(tmpdir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        # Write test runner
        test_runner = Path(tmpdir) / "_t3_test_runner.py"
        test_runner.write_text(test_code, encoding="utf-8")

        # Execute in clean subprocess
        result = subprocess.run(
            [sys.executable, str(test_runner)],
            cwd=tmpdir,
            env={
                "PYTHONPATH": tmpdir,
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            },
            capture_output=True,
            timeout=timeout,
            text=True,
        )

        return ExecutionResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            passed=result.returncode == 0,
            timeout=False,
        )
```

### Design Justification

| Decision | Why |
|----------|-----|
| Full-file rewrites over diffs | Diffs require line counting accuracy models lack. Full rewrites are deterministic to reconstruct. |
| File manifest with explicit count | Prevents silent file drops. Model knows exactly what's expected. |
| UNCHANGED sentinel | Models can skip unmodified files without re-emitting them, reducing token cost. Sentinel is unambiguous. |
| Subprocess isolation | Eliminates cross-case contamination, sys.modules leaks, global state mutation. |
| Temp directory with real files | Imports resolve naturally. No import stripping needed. No concatenation. |
| Token budget pre-check | Prevents silent truncation. Surfaces cases that don't fit. |
| AST validation before execution | Catches syntax errors in reconstructed code before runtime, with precise file attribution. |
| Import graph in prompt | Removes inference burden from model. Makes cross-file dependencies explicit. |

---

## 4. INVARIANTS

These must be enforced with runtime assertions (not documentation).

### Loading Invariants
```
INV-L1: forall file in case.code_files: file exists AND len(file.content.strip()) > 0
INV-L2: len(manifest.files) == len(case.code_files)
INV-L3: manifest.test_function is not None  (preflight -- already enforced in runner.py:122-145)
```

### Prompt Invariants
```
INV-P1: prompt contains exactly len(manifest.files) FILE START markers
INV-P2: prompt contains exactly len(manifest.files) FILE END markers
INV-P3: set(filenames in prompt) == set(manifest.file_order)
INV-P4: token_estimate(prompt) <= token_budget
INV-P5: forall condition, output_format_section appears exactly once (no double-format)
```

### Reconstruction Invariants
```
INV-R1: set(reconstructed.files.keys()) == set(manifest.file_order)  (no missing, no extra)
INV-R2: forall file in reconstructed.files: ast.parse(file.content) succeeds
INV-R3: if model_response missing any file key -> format_violation=True, score=0
INV-R4: no file content is empty string after reconstruction
```

### Execution Invariants
```
INV-E1: each case executes in its own subprocess (PID != parent PID)
INV-E2: PYTHONPATH == tmpdir (no leakage from host environment)
INV-E3: test result is determined ONLY by subprocess exit code + stdout
INV-E4: timeout is enforced (subprocess.TimeoutExpired -> score=0, reason="timeout")
INV-E5: no test modifies global state visible to other tests (subprocess isolation guarantees this)
```

### Logging Invariants
```
INV-LOG1: every LLM call produces exactly one log record (already enforced by RunLogger)
INV-LOG2: log.model == run.model for every record (already enforced by RunLogger._check_invariants)
INV-LOG3: no log record is written after close_run_log() (already enforced)
INV-LOG4: format_violation is logged distinctly from logic_failure (NEW -- not currently tracked)
```

### Scoring Invariants
```
INV-S1: format_violation -> score=0, pass=False (formatting failure != reasoning failure)
INV-S2: assembly_error -> tracked separately, never conflated with logic failure
INV-S3: raw_fallback -> flagged in results, excluded from primary metrics
INV-S4: parse_error -> flagged in results, excluded from primary metrics
```

---

## 5. VALIDATION TESTS

### Test 1: Multi-File Roundtrip (load -> prompt -> parse -> reconstruct -> identical)
```python
def test_roundtrip():
    """Simulated model returns UNCHANGED for all files -> reconstructed == original."""
    manifest = load_case(SAMPLE_CASE)
    prompt, meta = build_prompt(manifest, "baseline")

    # Simulate perfect model response
    model_response = {
        "reasoning": "no changes needed",
        "files": {f: "UNCHANGED" for f in manifest.file_order}
    }

    result = reconstruct(manifest, model_response)
    assert result.success
    assert result.files == manifest.files
    assert result.model_missing == set()
```

### Test 2: Truncation Detection
```python
def test_token_budget_exceeded():
    """Cases that exceed token budget must raise, not silently truncate."""
    manifest = load_case(LARGE_CASE)
    with pytest.raises(TokenBudgetExceeded):
        build_prompt(manifest, "guardrail_strict", token_budget=500)
```

### Test 3: Missing File Detection
```python
def test_missing_file_rejected():
    """Model response missing a file -> format_violation, not silent fallback."""
    manifest = load_case(MULTI_FILE_CASE)  # 4 files
    model_response = {
        "reasoning": "...",
        "files": {manifest.file_order[0]: "UNCHANGED"}  # only 1 of 4
    }
    result = reconstruct(manifest, model_response)
    assert not result.success
    assert result.format_violation
    assert len(result.model_missing) == 3
```

### Test 4: Import Resolution (subprocess)
```python
def test_imports_resolve_naturally():
    """Files written to disk can import each other without stripping."""
    files = {
        "cache_writer.py": "def cache_put(k, v): pass",
        "user_service.py": "from cache_writer import cache_put\ndef save(): cache_put('a', 1)",
    }
    test_code = "from user_service import save; save(); print('OK')"
    result = evaluate_in_subprocess("test_case", files, test_code)
    assert result.passed
```

### Test 5: Cross-Case Isolation
```python
def test_no_cross_case_leakage():
    """Case A's global state does not leak into case B."""
    files_a = {"mod.py": "STATE = []\ndef add(x): STATE.append(x)"}
    files_b = {"mod.py": "STATE = []\ndef get(): return STATE"}

    # Run A first (adds to STATE)
    eval_a = evaluate_in_subprocess("case_a", files_a,
        "from mod import add; add(1); add(2)")

    # Run B second (STATE should be empty)
    eval_b = evaluate_in_subprocess("case_b", files_b,
        "from mod import get; assert get() == [], f'leaked: {get()}'")

    assert eval_b.passed  # B's STATE is independent of A
```

### Test 6: Adversarial Formatting
```python
def test_code_containing_delimiters():
    """File content containing '### FILE' markers does not break parsing."""
    files = {
        "tricky.py": '# ### FILE 1 of 1: fake.py ###\nprint("not a delimiter")'
    }
    manifest = CaseManifest(files=files, file_order=["tricky.py"], ...)
    prompt, _ = build_prompt(manifest, "baseline")
    # Verify prompt has exactly 1 real FILE START marker
    assert prompt.count("### FILE 1 of 1:") == 1
```

### Test 7: UNCHANGED Sentinel Correctness
```python
def test_unchanged_preserves_original():
    """UNCHANGED files use original content, not empty or mangled."""
    manifest = load_case(MULTI_FILE_CASE)
    model_response = {
        "reasoning": "...",
        "files": {f: ("UNCHANGED" if i > 0 else "def fixed(): pass")
                  for i, f in enumerate(manifest.file_order)}
    }
    result = reconstruct(manifest, model_response)
    for fname in manifest.file_order[1:]:
        assert result.files[fname] == manifest.files[fname]
```

### Test 8: Parallel Execution Safety
```python
def test_parallel_no_interference():
    """Running 4 cases in parallel produces identical results to serial."""
    cases = load_all_cases()[:4]
    serial_results = [run_case(c) for c in cases]
    parallel_results = run_parallel(cases, workers=4)
    for s, p in zip(serial_results, parallel_results):
        assert s.passed == p.passed
        assert s.score == p.score
```

---

## 6. MIGRATION PLAN

### Phase 0: Immediate (no behavior change, fixes safety bugs)

1. **Sync STDLIB_MODULES** between `parse.py:397` and `validate_cases_v2.py:29`. Use a single canonical source. (15 min)

2. **Add empty-file check** in `runner.py:load_cases()`:
```python
assert content.strip(), f"Empty file after strip: {rel_path}"
```
(5 min)

3. **Track format_violation distinctly** in results. Add `"format_violation"` key alongside `"parse_error"`. Do not change scoring -- just record it. (30 min)

4. **Add `_raw_fallback` filter** to analysis scripts. Any result with `_raw_fallback=True` should be flagged and optionally excluded from primary metrics. (20 min)

### Phase 1: Output Format (medium effort, high impact)

5. **Change output format from single-code to file-dict**. Update `llm.py:_JSON_OUTPUT_INSTRUCTION` to request the `files` dict format from section 2.3. Update `parse.py` to handle the new format. Keep old parser as fallback tier.

6. **Implement reconstructor** (`reconstructor.py` from section 3.3). Wire it into `exec_eval.py` replacing `_assemble_program()`.

7. **Update prompt format** to use canonical file markers from section 2.1. Update `prompts.py:_format_code_files()`.

### Phase 2: Execution Isolation (medium effort, critical for correctness)

8. **Implement subprocess evaluation** (`subprocess_eval.py` from section 3.4). Replace `load_module_from_code()` + `exec()` with temp-directory-based subprocess execution.

9. **Remove import stripping** entirely. With real files on disk in a subprocess, imports resolve naturally. Delete `strip_local_imports()` and its duplicates.

10. **Add token budget checks** to prompt builder. Log warnings for cases near the budget. Reject cases that exceed it.

### Phase 3: Hardening (lower urgency)

11. **Add import graph to prompt** (section 2.2). Compute from AST analysis of case files.

12. **Write all validation tests** from section 5.

13. **Add AST validation** of reconstructed files before execution.

### What Can Remain

- `runner.py` orchestration logic (conditions, parallelism, logging) -- structurally sound
- `evaluator.py` evaluation pipeline (exec + LLM classify + alignment) -- correct architecture
- `RunLogger` class -- well-designed with proper invariants
- `cases.json` / `cases_v2.json` format -- adequate, just add `import_graph` field
- All test functions in `exec_eval.py` -- reusable as-is (they test modules, which will still work in subprocess)
- LLM classifier -- independent of reconstruction

### What Must Change

- `_format_code_files()` -> canonical format with explicit delimiters
- `_JSON_OUTPUT_INSTRUCTION` -> file-dict format
- `_assemble_program()` -> proper reconstructor
- `load_module_from_code()` + `exec()` -> subprocess isolation
- `strip_local_imports()` -> deleted
- `parse_model_response()` -> add file-dict parsing tier
- `_try_json_direct()` -> handle `code` as dict properly (map to file-dict format)

---

## 7. RECOMMENDED TOOLS/LIBRARIES

| Tool | Purpose | Where |
|------|---------|-------|
| `tiktoken` | Accurate token counting for OpenAI models | Token budget checks in prompt builder |
| `ast` (stdlib) | Parse validation of reconstructed Python files | Reconstructor validation step |
| `subprocess` (stdlib) | Process isolation for test execution | Replace in-process `exec()` |
| `tempfile` (stdlib) | Clean temp directories per case | Subprocess evaluator |
| `networkx` (or manual topo sort) | Import dependency graph + topological ordering | Case loader for file ordering |
| `deepdiff` | Precise comparison for roundtrip tests | Validation test suite |
| `pytest` | Validation test runner | All tests from section 5 |

No exotic dependencies needed. The key insight is that `subprocess` + `tempfile` from stdlib eliminate 80% of the failure modes (cross-case contamination, import stripping, module namespace collisions, thread safety) with zero external dependencies.
