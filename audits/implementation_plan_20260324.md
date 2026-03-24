# T3 Pipeline Redesign -- Implementation-Ready Plan

**Date:** 2026-03-24
**Prerequisite:** pipeline_audit_20260324.md (same directory)
**Goal:** Eliminate fragility and bias in multi-file code loading, prompting, reconstruction, and execution while preserving LEG analysis validity.

---

## 1. FINAL ARCHITECTURE

### 1.1 System Overview

```
cases.json          _format_code_files()      call_model()
    |                      |                       |
    v                      v                       v
+-----------+       +--------------+         +----------+
| CaseLoader|------>| PromptBuilder|-------->| LLM      |
| (manifest)|       | (canonical   |         | (budget- |
|           |       |  delimiters) |         |  aware)  |
+-----------+       +--------------+         +----+-----+
                                                  |
                                                  v
+-----------+       +--------------+         +-----------+
| Logger    |<------| SubprocessEval|<--------| FileRecon |
| (unchanged)|      | (tempdir +   |         | (strict   |
|           |       |  isolation)  |         |  mapping) |
+-----------+       +--------------+         +-----------+
```

### 1.2 File-System-Based Execution

**Current:** `exec()` in-process with concatenated, import-stripped code.
**New:** Each case evaluation writes real `.py` files to a temp directory, runs a test harness in a subprocess with `PYTHONPATH=tmpdir`.

```python
# Pseudocode for the new evaluation path
def evaluate_case(case_manifest, reconstructed_files, test_fn_source):
    with tempfile.TemporaryDirectory(prefix=f"t3_{case_manifest.case_id}_") as tmpdir:
        # 1. Write every file to disk as a real Python module
        for filename, content in reconstructed_files.items():
            (Path(tmpdir) / filename).write_text(content, encoding="utf-8")

        # 2. Write test harness that imports and runs the test function
        harness = _generate_test_harness(test_fn_source, case_manifest)
        (Path(tmpdir) / "_t3_harness.py").write_text(harness, encoding="utf-8")

        # 3. Run in subprocess with controlled env
        result = subprocess.run(
            [sys.executable, "_t3_harness.py"],
            cwd=tmpdir,
            env={"PYTHONPATH": tmpdir, "PATH": os.environ.get("PATH", "")},
            capture_output=True, timeout=30, text=True,
        )

        # 4. Parse harness output (JSON on stdout)
        return _parse_harness_result(result)
```

**Key properties:**
- No `sys.modules` pollution between cases
- No import stripping needed -- files import each other naturally
- No concatenation -- each file is its own module
- Thread-safe -- subprocesses have independent memory
- Timeout-enforced

### 1.3 Test Harness Design

The existing test functions (`tests_v2/test_*.py`) all take a `mod` (module object) parameter and call `getattr(mod, "func_name")`. To preserve these test functions without rewriting them, the subprocess harness works like this:

```python
# _t3_harness.py (generated per case, written to tmpdir)
import importlib, sys, json

# Import all case files as modules, then merge into a single namespace module
# (This is the ONLY place concatenation-like behavior exists, and it's inside
#  the isolated subprocess, not the parent process)
_ns = type(sys)("_t3_candidate")
_ns.__dict__["__builtins__"] = __builtins__

# Import each file and merge its namespace
for modname in {file_list}:
    mod = importlib.import_module(modname.replace(".py", ""))
    _ns.__dict__.update({k: v for k, v in mod.__dict__.items()
                         if not k.startswith("_")})

# Run the test function against the merged namespace
{test_function_source}

passed, reasons = test(_ns)
print(json.dumps({"pass": passed, "reasons": reasons}))
sys.exit(0 if passed else 1)
```

**Why merge into a namespace?** The existing 28 test functions all call `getattr(mod, "save_user")` etc. expecting a flat namespace. Rewriting all tests to use multi-module imports would be a large, risky change. The merge happens inside the subprocess (isolated) and each file was first imported as a real module (imports resolved naturally). This gives us:
- Real import resolution (no stripping)
- Process isolation (no leakage)
- Test function compatibility (no rewrite)

### 1.4 LLM Output Format

**New format -- file-dict with UNCHANGED sentinel:**

```json
{
  "reasoning": "...",
  "files": {
    "cache_writer.py": "def cache_put(k, v):\n    ...",
    "cache_reader.py": "UNCHANGED",
    "user_repo.py": "UNCHANGED",
    "user_service.py": "def save_user(user):\n    ..."
  }
}
```

The `"files"` key is new. The `"code"` key is retained as a fallback (see compatibility design in section 2.1).

### 1.5 Prompt Structure

```
You are fixing a bug in a Python codebase consisting of {N} files.

## Task
{task description}

## Codebase

### FILE 1/{N}: {filename} ###
```python
{content}
```

### FILE 2/{N}: {filename} ###
```python
{content}
```

{... remaining files ...}

## Output Format
Return a JSON object with this schema:
{
  "reasoning": "your analysis of the bug and fix",
  "files": {
    "{filename1}": "complete updated file contents OR the exact string UNCHANGED",
    "{filename2}": "complete updated file contents OR the exact string UNCHANGED"
  }
}

RULES:
- The "files" object MUST contain one entry for EVERY file listed above.
- For files you did not modify, use the exact string "UNCHANGED" as the value.
- For files you modified, include the COMPLETE file contents (not a diff).
- Do NOT include markdown inside file values.
- Return ONLY the JSON object.
```

### 1.6 Reconstruction System

```python
def reconstruct(manifest, model_response):
    """Deterministic: model output + manifest -> file dict."""
    model_files = model_response.get("files", {})
    expected = set(manifest.filenames)
    provided = set(model_files.keys())

    # Detect missing files
    missing = expected - provided
    extra = provided - expected

    result_files = {}
    errors = []
    changed = set()

    for fname in manifest.filenames:
        if fname not in model_files:
            errors.append(f"MISSING: {fname}")
            result_files[fname] = manifest.files[fname]  # fallback to original
            continue
        value = model_files[fname]
        if value == "UNCHANGED":
            result_files[fname] = manifest.files[fname]
        elif isinstance(value, str) and value.strip():
            result_files[fname] = value
            changed.add(fname)
        else:
            errors.append(f"EMPTY_OR_INVALID: {fname}")
            result_files[fname] = manifest.files[fname]  # fallback to original

    return ReconstructionResult(
        files=result_files,
        changed_files=changed,
        missing_files=missing,
        extra_files=extra,
        errors=errors,
        format_violation=len(missing) > 0,
    )
```

**Critical design choice:** When files are missing from the model response, we still reconstruct using originals (so the test can run), but we **flag `format_violation=True`** and record it separately. This way we can:
- Still measure whether the model's logic was correct (for LEG analysis)
- Track format violation rate per model (to detect bias)
- Exclude format violations from primary pass/fail if desired

---

## 2. KEY DESIGN DECISIONS

### 2.1 Output Format: Hybrid with Graceful Degradation

**Decision:** Request `files` dict format. Accept `code` string as fallback. Classify which was used.

**Why not strict file-dict only?**
- Some conditions (contract_gated, leg_reduction) already have their own output schemas with `raw=True`
- If we reject every response without `files`, models that don't follow instructions perfectly get 0% -- this is a formatting test, not a reasoning test
- Prior results used `code` format -- we need comparability

**Concrete implementation:**

```python
def parse_model_response_v2(raw: str, manifest) -> ParsedResponse:
    """Parse with file-dict preference, code-string fallback."""
    parsed = _try_json(raw)
    if parsed is None:
        return ParsedResponse(format="unparseable", ...)

    # Tier 1: files dict (preferred)
    if "files" in parsed and isinstance(parsed["files"], dict):
        return ParsedResponse(
            format="file_dict",
            files=parsed["files"],
            reasoning=parsed.get("reasoning", ""),
        )

    # Tier 2: code-as-dict (model used "code" key but put a dict)
    if "code" in parsed and isinstance(parsed["code"], dict):
        return ParsedResponse(
            format="code_dict",      # tracked -- this is a near-miss
            files=parsed["code"],
            reasoning=parsed.get("reasoning", ""),
        )

    # Tier 3: code-as-string (old format, still accepted)
    if "code" in parsed and isinstance(parsed["code"], str):
        return ParsedResponse(
            format="code_string",    # tracked -- legacy compat
            code=parsed["code"],
            reasoning=parsed.get("reasoning", ""),
        )

    return ParsedResponse(format="unparseable", ...)
```

**Every result records `response_format`:** `"file_dict"`, `"code_dict"`, `"code_string"`, or `"unparseable"`. This enables:
- Filtering analysis by format type
- Detecting whether format compliance varies by model
- A/B comparison: same model, old prompt vs new prompt

**Token cost analysis:**
- UNCHANGED sentinel for 4-file case with 1 file changed: ~3 UNCHANGED strings = ~12 tokens overhead. Negligible.
- Full rewrite of all 4 files: comparable to current "return all updated code" prompt, which already asks for everything.
- Net increase: ~50 tokens in output format instruction + ~12 tokens for UNCHANGED entries. Under 1% of typical response.

### 2.2 Prompt File Organization: Dependency-Ordered with Import Summary

**Decision:** Topological sort by import dependency, dependency-first. Plus a one-line import summary before the files.

**Concrete format:**

```
## Codebase
# Import structure: user_service.py -> cache_writer.py, user_repo.py
#                   cache_reader.py -> cache_writer.py (_store)

### FILE 1/4: cache_writer.py ###
```python
...
```

### FILE 2/4: cache_reader.py ###
...

### FILE 3/4: user_repo.py ###
...

### FILE 4/4: user_service.py ###
...
```

**Why dependency-first ordering?**
- The model reads code top-to-bottom. Reading `cache_writer.py` first means when the model encounters `from cache_writer import cache_put` in `user_service.py`, it already has the definition in context.
- This matches how a human developer would read unfamiliar code.
- Deterministic: `ast`-based import detection + alphabetical tiebreak = reproducible ordering.

**Why import summary?**
- Reduces cognitive load. The model doesn't need to mentally trace imports.
- Two lines, ~30 tokens. Negligible cost.
- Does NOT give away the bug -- it's the same information that's in the code.

**Bias consideration:** The import summary makes cross-file dependencies explicit, which could help all models equally. It does NOT favor one model over another. If anything, it *reduces* bias by removing an irrelevant inference step that penalizes smaller models disproportionately.

**Should this be an ablation?** No. The import summary is infrastructure information, not a reasoning hint. Including it is like including correct indentation -- it's baseline readability. However, the `### FILE N/M` markers and ordering ARE new, so we should run a comparability check (section 5.2).

### 2.3 Import Graph: Include in Prompt, Not as Ablation

**Decision:** Include the 2-line import summary in ALL conditions.

**Rationale:**
- The import graph is computable from the source code. It contains zero information that isn't already in the files.
- Excluding it forces models to spend reasoning capacity on import tracing instead of bug analysis.
- Import tracing ability is not what we're measuring. We're measuring causal reasoning about bugs.
- Making it an ablation would double the number of conditions (import-graph x no-import-graph). Not worth it for infrastructure metadata.

**Implementation:**

```python
def _compute_import_summary(files: dict[str, str]) -> str:
    """AST-based import graph summary."""
    import ast
    graph = {}
    filenames = set(f.replace(".py", "") for f in files.keys())

    for fname, content in files.items():
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                base = node.module.split(".")[0]
                if base in filenames:
                    names = [a.name for a in node.names]
                    imports.append(f"{base}.py ({', '.join(names)})")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in filenames:
                        imports.append(f"{base}.py")
        if imports:
            graph[fname] = imports

    if not graph:
        return ""
    lines = [f"# {f} imports from: {', '.join(deps)}" for f, deps in sorted(graph.items())]
    return "\n".join(lines)
```

### 2.4 Token Budget Strategy

**Decision:** Three-tier approach: measure, warn, mitigate. Never hard-reject.

**Tier 1: Measure (Phase 0)**
Add token estimation to every prompt and log it. Use `tiktoken` for OpenAI models:

```python
import tiktoken

def estimate_tokens(text: str, model: str = "gpt-4.1-nano") -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
```

Log `prompt_tokens` in every record. Immediately reveals which cases are near limits.

**Tier 2: Warn (Phase 1)**
Define per-model budgets:

```python
TOKEN_BUDGETS = {
    "gpt-4.1-nano": 12_000,    # 128k context, but response quality degrades >12k
    "gpt-4o-mini": 12_000,
    "gpt-5-mini": 16_000,
    "default": 10_000,
}
```

If `prompt_tokens > budget * 0.8`, log a warning. If `prompt_tokens > budget`, log SEVERE.

**Tier 3: Mitigate (Phase 3)**
For cases that exceed the budget:

1. **Remove redundant whitespace** (blank lines, trailing spaces) from source files. Safe, ~5-10% savings.
2. **Truncate file-level comments/docstrings** that aren't part of the logic. Heuristic but measurable.
3. **If still over budget after cleanup:** Flag the case as `token_budget_exceeded` in the manifest. Include it in analysis as a known confound. Do NOT silently truncate or silently exclude.

**Why not hard-reject?**
Hard-rejecting cases that exceed the budget means larger/harder cases never run. This biases the benchmark toward simpler cases. Instead, we flag them and let the analysis layer handle it (e.g., stratify results by prompt size).

### 2.5 Error Classification Taxonomy

**Decision:** Five-level classification, strictly defined:

| Category | Definition | Counted in pass/fail? | LEG analysis? |
|----------|------------|----------------------|---------------|
| `format_violation` | Model response missing required files key, or missing files from manifest | Yes (fail) | Yes -- reasoning may still be correct |
| `parse_error` | Cannot extract valid JSON from response at all | Yes (fail) | No -- no reasoning to evaluate |
| `syntax_error` | Reconstructed file(s) fail `ast.parse()` | Yes (fail) | Yes -- reasoning may still be correct |
| `execution_error` | Test harness crashes (import error, runtime error) | Yes (fail) | Yes -- reasoning may still be correct |
| `logic_failure` | Test runs to completion, invariant check fails | Yes (fail) | Yes -- this is the core measurement |

**Additionally tracked but NOT conflated:**

| Tag | Definition | Metric impact |
|-----|-----------|---------------|
| `response_format` | Which parser tier succeeded (`file_dict`, `code_string`, etc.) | Logged, filterable |
| `assembly_used` | Whether original files were prepended (legacy compat path) | Logged, filterable |
| `token_budget_exceeded` | Prompt exceeded model's effective budget | Logged, filterable |
| `_raw_fallback` | Entire raw response used as code (legacy parser path) | Excluded from primary metrics |

**LEG validity:** The LEG (Latent Error Gap) measures whether the model's reasoning identified the correct bug even when its code is wrong. This requires both code evaluation AND reasoning evaluation. Format violations and syntax errors prevent code from running, but the model's *reasoning* field may still be evaluable. Therefore, `format_violation`, `syntax_error`, and `execution_error` are scored as `pass=False` for code correctness, but the LLM classifier still evaluates reasoning. This preserves LEG detection.

**`parse_error` is different:** If we can't extract any response structure at all, there's no reasoning to evaluate. These are excluded from LEG analysis entirely and counted as `unclassified`.

---

## 3. FAILURE MODE FIXES

### 3.1 Concatenation -> Filesystem-Based Execution

**Current behavior** (`exec_eval.py:689-728`): All case files concatenated with `"\n\n".join()`, import-stripped, then the model's code appended at the end. Executed via `exec()` in the parent process. Last definition wins.

**New behavior:** Each file written to a temp directory as a separate `.py` file. Imports resolve naturally via Python's import system. Test runs in subprocess.

**Why correct:** Python modules are designed to be separate files with explicit imports. We were fighting the language's module system. Now we use it as intended.

**Migration:** `_assemble_program()` is replaced by `reconstruct()` + `evaluate_in_subprocess()`. The old function is not deleted immediately -- it's kept as a fallback during Phase 1 (see section 4.2).

### 3.2 Import Stripping -> Deletion

**Current behavior** (`parse.py:404-433`): `strip_local_imports()` removes all non-stdlib imports. Used in `exec_eval.py:42` (module loading) and `exec_eval.py:702-703` (assembly). `STDLIB_MODULES` is a hand-curated frozenset of 20 modules. `validate_cases_v2.py:29-33` has a DIFFERENT list.

**New behavior:** `strip_local_imports()` is not called in the new execution path. Files on disk import each other via standard Python imports. No stripping needed.

**Why correct:** Import stripping existed solely because concatenation destroyed module boundaries. With real files on disk, imports work. Stripping actually BROKE code that used non-listed stdlib modules (`datetime`, `enum`, `logging`).

**Migration:**
- Phase 0: Sync the two STDLIB lists immediately (safety fix).
- Phase 2: New execution path does not call `strip_local_imports()`.
- Phase 3: Delete the function after confirming no code paths use it.

### 3.3 sys.modules Leakage -> Subprocess Isolation

**Current behavior** (`exec_eval.py:34-54`): `load_module_from_code()` registers modules in `sys.modules` with unique names (`_t3_exec_{name}_{counter}`). But module-level globals, class registries, and mutable state in the loaded code persist in the parent process for the entire run.

**New behavior:** Each case evaluation runs in a subprocess. When the subprocess exits, all of its memory is reclaimed by the OS. Zero leakage.

**Why correct:** Process isolation is the only reliable way to prevent cross-case contamination. No amount of cleanup code can guarantee that arbitrary user-submitted code hasn't modified global state.

### 3.4 Thread Safety -> Subprocess Isolation + Serial Option

**Current behavior** (`runner.py:213`): `ThreadPoolExecutor` shares memory. `sys.modules` writes, `random.random` monkey-patching (`exec_eval.py:244-254`), and other global mutations are visible across threads.

**New behavior:** With subprocess execution, thread safety is no longer a concern for test execution. The parent process's threads only dispatch subprocesses (no shared mutable state). The `--parallel N` flag now means N concurrent subprocesses, not N threads sharing a process.

**Implementation:** Replace `ThreadPoolExecutor` with `ProcessPoolExecutor` or simply `concurrent.futures.ThreadPoolExecutor` where each thread spawns a subprocess. The second is simpler and sufficient because the thread itself does no mutable work -- it just calls `subprocess.run()` and reads the result.

### 3.5 Parser Tier Bias -> Structured Classification

**Current behavior** (`parse.py:171-215`): 4-tier cascade (JSON direct -> lenient JSON -> JSON substring -> code block -> raw fallback). Each tier applies different extraction logic. `raw_fallback` uses the entire response as code, which always fails.

**New behavior:** The parser still has tiers (robustness is good), but every result records which tier succeeded:

```python
result["response_format"] = "file_dict"      # Tier 1a: new file-dict format
result["response_format"] = "code_string"    # Tier 1b: old code-string format
result["response_format"] = "code_dict"      # Tier 1c: code key is a dict
result["response_format"] = "lenient_json"   # Tier 2: lenient extraction
result["response_format"] = "code_block"     # Tier 3: markdown code block
result["response_format"] = "raw_fallback"   # Tier 4: raw text (almost always fails)
```

**Bias mitigation:**
- Primary metrics EXCLUDE `raw_fallback` results (these are formatting failures, not reasoning failures).
- Analysis scripts report format distribution per model. If model A gets 90% `file_dict` and model B gets 60% `file_dict` + 30% `code_string`, this is reported as a confound.
- The `response_format` field enables post-hoc stratification.

### 3.6 Partial Edit Bias -> Explicit Per-File Tracking

**Current behavior** (`exec_eval.py:661-744`): `_assemble_program()` always prepends ALL original files, then appends model code. A model that returns one function definition gets the full original codebase for free. A model that returns all files but gets one wrong is penalized.

**New behavior:** The reconstructor maps model output file-by-file:
- Files marked `UNCHANGED`: original used (explicit acknowledgment)
- Files present with content: model's version used (explicit replacement)
- Files missing: original used AS FALLBACK + `format_violation` flag

**Bias fix:** The `changed_files` set in `ReconstructionResult` tells us exactly which files the model attempted to modify. We can now compute:
- `completeness_score`: len(changed_files) / len(files_that_needed_changes)
- `format_compliance`: whether model included all files in response
- `assembly_crutch`: whether the model relied on original files for definitions it should have overridden

This data doesn't change the pass/fail score (which is still determined by test execution), but it enables analysis that separates "got the right answer by fixing the right file" from "got the right answer because assembly filled in missing code."

### 3.7 Token Truncation -> Budget Awareness

**Current behavior:** Zero awareness. `llm.py:47` concatenates prompt + 200-token JSON instruction and sends it. If it exceeds the model's context, the API silently truncates or errors. The system records a parse failure.

**New behavior:** Every prompt is token-counted before sending. The token count is logged. If it exceeds the model's effective budget, a SEVERE warning is logged and `token_budget_exceeded=True` is set in the result. The call still proceeds (we don't reject), but analysis can filter.

**Implementation:**
```python
# In execution.py, before call_model():
from token_budget import estimate_tokens, get_budget

tokens = estimate_tokens(prompt, model)
budget = get_budget(model)
ev_metadata["prompt_tokens"] = tokens
ev_metadata["token_budget_exceeded"] = tokens > budget
if tokens > budget:
    _exec_log.warning(
        "TOKEN BUDGET EXCEEDED: case=%s cond=%s tokens=%d budget=%d",
        case_id, condition, tokens, budget
    )
```

### 3.8 Multi-File vs Single-File Bias -> Unified Execution Path

**Current behavior** (`exec_eval.py:679-687`): Single-file cases skip assembly entirely (`assembly_used=False`). Multi-file cases go through assembly. Different code paths = different failure modes = different noise levels.

**New behavior:** ALL cases go through the same path: write files to disk -> reconstruct -> subprocess evaluation. A single-file case is just a case with `len(manifest.files) == 1`. The subprocess harness imports one module instead of four. Same code path, same failure modes, same noise level.

---

## 4. IMPLEMENTATION PLAN (PHASED)

### Phase 0: Safe Instrumentation (no behavior change)

**Goal:** Visibility into current problems without changing any behavior.

**Changes:**

1. **Sync STDLIB_MODULES** (`parse.py:397` and `validate_cases_v2.py:29`). Extract to a shared `_stdlib.py` module imported by both.

   Files changed: `parse.py`, `validate_cases_v2.py`, new `_stdlib.py`

2. **Add empty-file assertion** in `runner.py:113`:
   ```python
   content = full_path.read_text(encoding="utf-8").strip()
   assert content, f"PREFLIGHT: Empty file {rel_path}"
   code_files[rel_path] = content
   ```

3. **Add `response_format` classification** to `parse.py:parse_model_response()`. Add a `"response_format"` key to every return dict. Values: `"json_direct"`, `"json_lenient"`, `"json_substring"`, `"code_block"`, `"raw_fallback"`.

4. **Add token counting** to `execution.py:run_single()`. Install `tiktoken`. Log `prompt_tokens` in every record.

5. **Add `format_violation` field** to eval results. Initially always `False` (no new behavior). Wired into logging.

6. **Add `assembly_crutch` detection** in `exec_eval.py:_assemble_program()`. When `assembly_used=True` and the model's code defines fewer than 50% of the functions from the original files, log `assembly_crutch=True`.

**What stays the same:** All execution logic, all prompts, all parsing behavior, all scoring.

**Risks:** Minimal -- additive logging only.

**Rollback:** Delete the new fields from log records. No behavior was changed.

**Deliverable:** Run existing benchmark, analyze logs for: format distribution, token counts, assembly crutch rates. This data informs Phase 1 tuning.

---

### Phase 1: Output Format + Reconstruction

**Goal:** New prompt format requesting `files` dict. New reconstructor. Old execution backend still used.

**Changes:**

1. **New `_JSON_OUTPUT_INSTRUCTION_V2`** in `llm.py`:

   ```python
   _JSON_OUTPUT_INSTRUCTION_V2 = """

   Return your response as a single valid JSON object with this schema:

   {"reasoning": "<your explanation>", "files": {"<filename>": "<complete file contents or UNCHANGED>"}}

   RULES:
   - "reasoning" MUST be a non-empty string explaining your analysis.
   - "files" MUST contain one entry for EVERY file in the codebase above.
   - For files you did not modify, set the value to the exact string "UNCHANGED".
   - For files you modified, include the COMPLETE updated file contents.
   - Do NOT include markdown formatting inside file values.
   - Do NOT omit any file.
   - Return ONLY the JSON object."""
   ```

   `call_model()` uses V2 instruction by default. V1 kept as `_JSON_OUTPUT_INSTRUCTION_V1` for backward compat.

2. **New `_format_code_files_v2()`** in `prompts.py`:

   ```python
   def _format_code_files_v2(code_files: dict[str, str]) -> str:
       n = len(code_files)
       parts = []
       for i, (path, contents) in enumerate(code_files.items(), 1):
           fname = Path(path).name
           parts.append(f"### FILE {i}/{n}: {fname} ###\n```python\n{contents}\n```")
       return "\n\n".join(parts)
   ```

   `_format_code_files()` now calls `_format_code_files_v2()` by default.

3. **New `reconstructor.py`** module (as specified in section 1.6).

4. **New parser tier** in `parse.py`: `_try_file_dict()` added as Tier 0 before `_try_json_direct()`:

   ```python
   def _try_file_dict(raw: str) -> dict | None:
       """Tier 0: JSON with 'files' dict."""
       try:
           parsed = json.loads(raw)
           if isinstance(parsed, dict) and "files" in parsed:
               files = parsed["files"]
               if isinstance(files, dict) and all(isinstance(v, str) for v in files.values()):
                   return {
                       "reasoning": parsed.get("reasoning", ""),
                       "files": files,
                       "code": None,  # not used in file-dict path
                       "confidence": parsed.get("confidence"),
                       "parse_error": None,
                       "response_format": "file_dict",
                   }
       except (json.JSONDecodeError, TypeError):
           pass
       return None
   ```

5. **Wire reconstructor into exec_eval.py**. When `parse_result["response_format"] == "file_dict"`:
   - Call `reconstruct(manifest, parse_result["files"])`
   - If reconstruction succeeds: write files to tmpdir, run old `load_module_from_code()` on the concatenated result (still using old execution backend)
   - If reconstruction fails: use original assembly path as fallback

   This means Phase 1 uses the new FORMAT but the old EXECUTION. The reconstructor validates file mapping, but execution still concatenates. This isolates format risk from execution risk.

**What stays the same:** `exec_evaluate()`, `_assemble_program()`, subprocess isolation (not yet), all test functions.

**Risks:**
- Models may not follow the new `files` format. **Mitigation:** Old `code` format still accepted as fallback tier.
- New prompt format changes model behavior. **Mitigation:** Run A/B comparison (section 5.2) before switching production runs.

**Rollback:** Set `_JSON_OUTPUT_INSTRUCTION = _JSON_OUTPUT_INSTRUCTION_V1` in `llm.py`. One-line change.

---

### Phase 2: Subprocess Execution

**Goal:** Replace in-process `exec()` with subprocess evaluation. Remove concatenation. Remove import stripping from execution path.

**Changes:**

1. **New `subprocess_eval.py`** module:

   ```python
   def evaluate_in_subprocess(case_id, files, test_source, timeout=30):
       """Write files to tmpdir, generate harness, run subprocess, parse result."""
   ```

   Full implementation as specified in section 1.2 and 1.3.

2. **New test harness generator** `_generate_test_harness()`:

   ```python
   def _generate_test_harness(test_fn_source: str, filenames: list[str]) -> str:
       """Generate a Python script that imports case files, merges namespace, runs test."""
       modnames = [f.replace(".py", "") for f in filenames]
       import_lines = "\n".join(
           f"import {m}" for m in modnames
       )
       merge_lines = "\n".join(
           f"_ns.__dict__.update({{k: v for k, v in {m}.__dict__.items() if not k.startswith('_')}})"
           for m in modnames
       )
       return f'''
   import sys, json, importlib
   {import_lines}

   _ns = type(sys)("_t3_candidate")
   _ns.__dict__["__builtins__"] = __builtins__
   {merge_lines}

   {test_fn_source}

   try:
       passed, reasons = test(_ns)
   except Exception as e:
       passed = False
       reasons = [f"test crashed: {{e}}"]

   result = {{"pass": passed, "reasons": reasons}}
   print(json.dumps(result))
   sys.exit(0 if passed else 1)
   '''
   ```

3. **Update `exec_evaluate()`** to use subprocess path when reconstruction result is available:

   ```python
   def exec_evaluate(case, code_or_files, ...):
       if isinstance(code_or_files, dict):
           # New path: files dict from reconstructor
           return _exec_evaluate_subprocess(case, code_or_files)
       else:
           # Legacy path: code string (backward compat)
           return _exec_evaluate_legacy(case, code_or_files)
   ```

4. **Remove `strip_local_imports()` calls** from the new execution path. The function itself is kept (validate_cases_v2 still uses it) but marked deprecated.

5. **Update `runner.py` parallel execution.** No change to `ThreadPoolExecutor` -- each thread now calls `subprocess.run()` which is inherently process-isolated.

**What stays the same:** All test functions in `tests_v2/`. `evaluator.py`. `RunLogger`. All conditions/nudges. `runner.py` orchestration.

**Risks:**
- Subprocess overhead adds ~0.1-0.3s per case. For 50 cases x 25 conditions = 1250 evals, this adds ~2-6 minutes. Acceptable for a research benchmark.
- Test harness namespace merge may behave differently from concatenation for edge cases (e.g., module-level `__all__`, `__name__` checks). **Mitigation:** Run equivalence check (section 5.2) on all cases before switching.
- `random.random` monkey-patching in `_test_retry_causality` must happen inside the subprocess, not in the parent. **Mitigation:** The test function source is embedded in the harness, so the patching naturally happens in the subprocess.

**Rollback:** `exec_evaluate()` still has the legacy branch. Set a flag `USE_SUBPROCESS = False` to disable. One-line change.

---

### Phase 3: Prompt Improvements

**Goal:** Dependency-ordered file listing. Import summary. Token budget integration.

**Changes:**

1. **Dependency-aware file ordering** in `runner.py:load_cases()`:

   ```python
   def load_cases(...):
       for case in cases:
           code_files = {}
           for rel_path in case["code_files"]:
               ...
           # Compute dependency order
           ordered = _dependency_sort(code_files)
           case["code_files_contents"] = OrderedDict(
               (k, code_files[k]) for k in ordered
           )
   ```

2. **Import summary** prepended to codebase section in `prompts.py`:

   ```python
   def _format_code_files_v2(code_files):
       import_summary = _compute_import_summary(code_files)
       n = len(code_files)
       parts = []
       if import_summary:
           parts.append(f"# Import structure:\n{import_summary}")
       for i, (path, contents) in enumerate(code_files.items(), 1):
           fname = Path(path).name
           parts.append(f"### FILE {i}/{n}: {fname} ###\n```python\n{contents}\n```")
       return "\n\n".join(parts)
   ```

3. **Token budget logging with warnings** in `execution.py` (already instrumented in Phase 0, now with thresholds).

**What stays the same:** Everything else. This phase is purely prompt-side.

**Risks:** Changing file order may change model behavior for cases where the current order was "lucky." **Mitigation:** Run old-order vs new-order comparison on baseline condition. If pass rate changes significantly for specific cases, investigate.

**Rollback:** Revert `_format_code_files_v2` to V1 behavior. Revert `load_cases` ordering to insertion order.

---

### Phase 4: Hardening

**Goal:** Validation tests, invariant enforcement, edge-case handling.

**Changes:**

1. **`tests/test_pipeline.py`** -- validation test suite (section 5):
   - Roundtrip test
   - Missing file detection
   - Import resolution
   - Cross-case isolation
   - Format robustness
   - Parallel safety

2. **Runtime invariant checks** added to `reconstructor.py`:
   ```python
   assert set(result.files.keys()) == set(manifest.filenames), "INV-R1 violated"
   for fname, content in result.files.items():
       assert content.strip(), f"INV-R4 violated: {fname} is empty"
   ```

3. **AST validation** of reconstructed files before execution:
   ```python
   for fname, content in result.files.items():
       try:
           ast.parse(content)
       except SyntaxError as e:
           result.syntax_errors.append((fname, str(e)))
   ```

4. **`validate_cases_v2.py` updated** to use the new subprocess execution path, verifying that every case passes the same checks with the new system.

5. **Delete deprecated code:**
   - `strip_local_imports()` in `parse.py` (if no remaining callers)
   - `_assemble_program()` in `exec_eval.py` (legacy path removed)
   - `_JSON_OUTPUT_INSTRUCTION_V1` in `llm.py`

**Risks:** Deleting legacy code paths removes the rollback option. Only do this after Phase 2 has been validated across at least one full ablation run.

---

## 5. VALIDATION PLAN

### 5.1 Roundtrip Test

**Goal:** Verify that the new prompt format, parsing, and reconstruction pipeline is lossless.

```python
def test_roundtrip_all_unchanged():
    """Model returns UNCHANGED for all files -> reconstructed == original."""
    for case in load_all_cases():
        manifest = build_manifest(case)
        model_response = {"files": {f: "UNCHANGED" for f in manifest.filenames}}
        result = reconstruct(manifest, model_response)
        assert result.files == manifest.files, f"Roundtrip failed for {case['id']}"
        assert not result.format_violation
        assert len(result.errors) == 0

def test_roundtrip_one_changed():
    """Model returns modified version of one file + UNCHANGED for rest."""
    manifest = build_manifest(SAMPLE_CASE)
    target = manifest.filenames[0]
    model_response = {
        "files": {f: ("def fixed(): pass" if f == target else "UNCHANGED")
                  for f in manifest.filenames}
    }
    result = reconstruct(manifest, model_response)
    assert result.files[target] == "def fixed(): pass"
    for f in manifest.filenames[1:]:
        assert result.files[f] == manifest.files[f]
```

### 5.2 Old vs New System Comparison

**Goal:** Verify the new system does not distort results relative to the old system.

**Methodology:**
1. Run ALL cases with `gpt-4.1-nano` on `baseline` condition using OLD system (current code). Record pass/fail, LEG, scores.
2. Run the SAME cases with the SAME model on `baseline` using NEW system (Phase 2 complete). Record pass/fail, LEG, scores.
3. Compare:

| Metric | Expected | Action if violated |
|--------|----------|--------------------|
| Pass rate delta | < 5% absolute | Investigate case-by-case |
| LEG rate delta | < 3% absolute | Investigate classifier inputs |
| Format violation rate | < 10% | Tune output instruction |
| Failure distribution shape | Similar | Acceptable if explainable (e.g., assembly_crutch cases now correctly fail) |

**Expected differences:**
- Some cases that passed under old system due to assembly crutch may now fail (model didn't actually fix the bug, assembly filled in the answer). This is CORRECT behavior -- the old system was inflating pass rates.
- Format compliance may be lower initially. This is tunable by adjusting the output instruction.

**Critical check:** If the new system shows HIGHER pass rates on multi-file cases, something is wrong (the old system's assembly was masking failures, so new should be equal or lower).

### 5.3 Multi-File Stress Test

```python
def test_multifile_imports_resolve():
    """Multi-file case with cross-file imports executes correctly in subprocess."""
    files = {
        "models.py": "class Account:\n    def __init__(self): self.balance = 0",
        "service.py": "from models import Account\ndef create(): return Account()",
        "api.py": "from service import create\ndef handle(): a = create(); return a.balance",
    }
    test_src = """
def test(mod):
    handle = getattr(mod, "handle", None)
    if not handle:
        return False, ["handle not found"]
    result = handle()
    if result != 0:
        return False, [f"expected 0, got {result}"]
    return True, ["ok"]
"""
    result = evaluate_in_subprocess("stress_test", files, test_src)
    assert result["pass"]
```

### 5.4 Format Robustness Test

```python
def test_minor_format_errors_handled():
    """Model adds extra whitespace, trailing commas, etc."""
    raw_responses = [
        # Extra whitespace in UNCHANGED
        '{"reasoning": "ok", "files": {"a.py": "  UNCHANGED  ", "b.py": "def f(): pass"}}',
        # Trailing newline in file content
        '{"reasoning": "ok", "files": {"a.py": "UNCHANGED", "b.py": "def f(): pass\\n"}}',
        # Missing reasoning (should still parse files)
        '{"files": {"a.py": "UNCHANGED", "b.py": "def f(): pass"}}',
    ]
    for raw in raw_responses:
        result = parse_model_response_v2(raw, manifest)
        assert result.response_format in ("file_dict",), f"Failed: {raw[:50]}"
```

### 5.5 Isolation Test

```python
def test_subprocess_isolation():
    """Mutations in case A do not affect case B."""
    files_a = {"shared.py": "GLOBAL = []\ndef mutate(): GLOBAL.append(1); return GLOBAL"}
    files_b = {"shared.py": "GLOBAL = []\ndef check(): return len(GLOBAL)"}

    test_a = 'def test(mod): mod.mutate(); return True, ["ok"]'
    test_b = 'def test(mod): return (mod.check() == 0, [f"leaked: {mod.check()}"])'

    evaluate_in_subprocess("case_a", files_a, test_a)
    result_b = evaluate_in_subprocess("case_b", files_b, test_b)
    assert result_b["pass"], "Cross-case leakage detected"
```

---

## 6. RISKS AND MITIGATIONS

### R1: Models Don't Follow New Output Format

**Risk:** Models return `{"code": "..."}` instead of `{"files": {...}}` with the new prompt.

**Likelihood:** Medium. gpt-4.1-nano may struggle; gpt-5-mini should comply.

**Mitigation:**
- Keep old `code` key as fallback parser tier (section 2.1).
- Track `response_format` per model. If a model consistently returns old format, the results are still valid -- they're just processed through the legacy reconstruction path.
- Do NOT make format compliance part of the benchmark score. Format compliance is an infrastructure concern, not a reasoning concern.

### R2: Subprocess Overhead Slows Experiment

**Risk:** 1250 subprocess launches add significant time.

**Likelihood:** Low. `subprocess.run()` with a 30s timeout and ~0.2s overhead per launch = ~4 minutes total overhead on a run that currently takes 20-30 minutes of API wait time.

**Mitigation:** Benchmark the overhead. If >10% of total runtime, consider process pooling (keep a warm Python process) or batch multiple cases into one subprocess.

### R3: Test Harness Namespace Merge Differs from Concatenation

**Risk:** Some test that passes under concatenation fails under namespace merge (or vice versa) due to subtle Python import semantics.

**Likelihood:** Low but non-zero. Possible sources: `__name__` checks, `isinstance()` across module boundaries, metaclass registration.

**Mitigation:** Run equivalence check (section 5.2) on ALL cases before switching. Any case that flips result is investigated individually. If the new behavior is correct (the old was masking a real failure), accept it. If the new behavior is wrong (infrastructure bug), fix the harness.

### R4: New System Reveals Assembly-Inflated Pass Rates

**Risk:** Pass rates drop when assembly crutch is removed, making results look worse.

**Likelihood:** High for multi-file cases. This is expected and correct.

**Mitigation:** This is not a risk -- this is the point. The old system was producing inflated results. The new system is more accurate. Report the delta transparently. In the paper, this becomes evidence that the old evaluation methodology was biased.

### R5: Breaking Change to Prior Results Comparability

**Risk:** Results from new system are not directly comparable to prior ablation runs.

**Likelihood:** Certain. Any methodology change breaks strict comparability.

**Mitigation:**
- Phase 0 instrumentation (no behavior change) can be run on old results to retroactively classify format types, assembly crutch rates, etc.
- Run at least one full ablation with both old and new systems on the same model. The delta between systems IS a result worth reporting.
- In the paper, clearly delineate "pre-fix" and "post-fix" results. The fix itself is a methodological contribution.

### R6: Complexity Budget

**Risk:** The new system has more moving parts (reconstructor, subprocess harness, token counter, format classifier).

**Likelihood:** Real concern.

**Mitigation:**
- Each new component is a pure function with clear inputs and outputs.
- `reconstructor.py`: ~60 lines, no state.
- `subprocess_eval.py`: ~80 lines, no state.
- `_generate_test_harness()`: ~30 lines, template-based.
- Token counting: ~10 lines.
- Total new code: ~180 lines. Total code removed (strip_local_imports, _assemble_program, multi-tier parser hacks): ~200 lines. Net is roughly even.
