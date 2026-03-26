# T3 Multi-File Pipeline Redesign v3

**Date:** 2026-03-24
**Supersedes:** MULTIFILE_PIPELINE_REDESIGN_v2.md
**Prerequisite:** audits/pipeline_audit_20260324.md

**v2 defects corrected in this revision:**
1. PYTHONPATH redesigned: case-local package materialization with tmpdir as repo root
2. `mods` dict uses fully-qualified import path as canonical key; short aliases as secondary
3. Token reduction is side-effect-free (operates on PromptView, never mutates manifest)
4. Prompt explicitly discloses reduction state to the model
5. Formal LEG rule table covering all 7 reconstruction/reasoning combinations
6. Import-summary calibration expanded with format, token, and reconstruction metrics
7. Formal old-vs-new pipeline calibration experiment added as first-class validation
8. Seven new validation tests covering all corrected areas

**Retained from v2 (unchanged):**
- No synthetic namespace flattening
- No fallback-to-original in primary evaluation path
- Strict reconstruction with FAIL on missing files
- 5-level error taxonomy
- Subprocess isolation
- Legacy removal timeline with hard cutoff criteria

---

## 1. FINAL ARCHITECTURE (CORRECTED)

### 1.1 System Overview

```
cases.json           PromptBuilder            call_model()
    |                     |                        |
    v                     v                        v
+------------+    +---------------+          +-----------+
| CaseLoader |    | PromptView    |          | LLM       |
| (manifest, |--->| (immutable    |--------->| (budget-  |
|  import    |    |  reduced view,|          |  enforced)|
|  graph,    |    |  disclosure)  |          +-----------+
|  pkg layout|    +---------------+                |
+------------+                                     v
                  +---------------+          +-----------+
+------------+    | SubprocessEval|<---------| StrictRecon|
| Logger     |<---| (tmpdir,      |          | (FAIL on  |
| (error     |    |  real modules,|          |  missing, |
|  taxonomy, |    |  PYTHONPATH=  |          |  no       |
|  LEG rules)|    |  tmpdir)      |          |  fallback)|
+------------+    +---------------+          +-----------+
```

### 1.2 Execution Model

Each case evaluation:
1. Materializes a **case-local package** under tmpdir so flat sibling imports resolve from `PYTHONPATH=tmpdir`
2. Writes real `.py` files preserving full relative paths
3. Runs a test harness in a subprocess
4. Parses JSON output from the harness

---

## 2. IMPORT ROOT / MODULE IDENTITY DESIGN

### 2.1 The Import Problem

All 100+ case files across `code_snippets/` and `code_snippets_v2/` use **flat sibling imports**:
```python
from cache_writer import cache_put        # NOT from code_snippets.hidden_dependency_hard.cache_writer
from models import Account                # NOT relative: from .models import Account
```

Verified empirically: zero cases use package-qualified or relative imports. Zero cases have files at different directory depths. Zero cases have duplicate basenames within the same case.

### 2.2 Chosen Approach: Case-Local Package Materialization

**Approach B: Preserve existing case-local import style. Materialize a package layout under tmpdir that makes flat imports resolve with `PYTHONPATH=tmpdir`.**

**Implementation:**

```python
def materialize_case(tmpdir: Path, manifest, reconstructed_files: dict[str, str]):
    """Write files to tmpdir in a layout where flat sibling imports resolve.

    All case files share a common parent directory (verified at load time).
    We extract that directory name and create it under tmpdir as the
    import root.

    Layout:
        tmpdir/
            {case_package}/          <-- this goes on sys.path
                cache_writer.py
                cache_reader.py
                user_service.py
                user_repo.py
    """
    case_dir = manifest.case_package  # e.g., "hidden_dependency_hard"

    pkg_root = tmpdir / case_dir
    pkg_root.mkdir(parents=True, exist_ok=True)

    for rel_path, content in reconstructed_files.items():
        # rel_path = "code_snippets/hidden_dependency_hard/cache_writer.py"
        # We write to: tmpdir/hidden_dependency_hard/cache_writer.py
        filename = Path(rel_path).name
        target = pkg_root / filename
        target.write_text(content, encoding="utf-8")

    return pkg_root  # This becomes PYTHONPATH
```

**PYTHONPATH** is set to `str(pkg_root)`, i.e., `tmpdir/hidden_dependency_hard/`. From there, `import cache_writer` resolves naturally.

**Why `PYTHONPATH = tmpdir` alone does not work:** If we wrote files to `tmpdir/code_snippets/hidden_dependency_hard/cache_writer.py` and set `PYTHONPATH=tmpdir`, then Python would require `from code_snippets.hidden_dependency_hard.cache_writer import cache_put`. That contradicts every existing case file's import style.

**Why `PYTHONPATH = pkg_root` is correct:** The case files already assume flat sibling imports. `pkg_root` is the directory that contains all sibling `.py` files. Setting it as the sole `PYTHONPATH` entry means `import cache_writer` finds `cache_writer.py` directly. This is exactly how the files were designed to be imported.

**Full relative paths are preserved** in:
- The manifest (for identification and logging)
- The prompt (so the model sees the original project structure)
- The LLM output schema (so the model returns paths matching the prompt)
- The reconstruction result (for provenance)

But the **execution layout** uses the case-local package root. This is an explicit, documented transformation.

### 2.3 Supported Import Style

The benchmark supports **exactly one** import style: **flat sibling imports**.

```python
# SUPPORTED:
from cache_writer import cache_put
import cache_writer

# NOT SUPPORTED (and not used by any current case):
from code_snippets.hidden_dependency_hard.cache_writer import cache_put
from .cache_writer import cache_put
```

### 2.4 Import Consistency Validation (Preflight)

At case load time, the following checks run. Any failure is fatal:

```python
def validate_import_consistency(case: dict):
    """Preflight: verify case files have consistent, supported import structure."""
    file_paths = case["code_files"]

    # CHECK 1: All files in same directory
    parents = set(str(Path(f).parent) for f in file_paths)
    assert len(parents) == 1, (
        f"Case {case['id']}: files span multiple directories: {parents}. "
        f"Benchmark requires all case files in a single directory."
    )

    # CHECK 2: No duplicate basenames
    basenames = [Path(f).name for f in file_paths]
    dupes = [b for b, c in Counter(basenames).items() if c > 1]
    assert not dupes, (
        f"Case {case['id']}: duplicate basenames: {dupes}. "
        f"Flat sibling imports require unique basenames."
    )

    # CHECK 3: All cross-file imports are flat sibling style
    sibling_modules = {Path(f).stem for f in file_paths}
    for rel_path in file_paths:
        content = load_file(rel_path)
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    raise ValueError(
                        f"Case {case['id']}: {rel_path} uses relative import "
                        f"(level={node.level}). Not supported."
                    )
                if node.module and "." in node.module:
                    base = node.module.split(".")[0]
                    if base in sibling_modules:
                        raise ValueError(
                            f"Case {case['id']}: {rel_path} uses qualified import "
                            f"'from {node.module} import ...'. Use flat import instead."
                        )
```

### 2.5 `mods` Dict Key Design

**Canonical key:** The fully-qualified import path as seen from `PYTHONPATH`.

Since `PYTHONPATH` points to the case-local package root (e.g., `tmpdir/hidden_dependency_hard/`), and files sit directly in that directory, the fully-qualified import path IS the stem name:

```python
# File: tmpdir/hidden_dependency_hard/cache_writer.py
# PYTHONPATH: tmpdir/hidden_dependency_hard/
# Fully-qualified import path: "cache_writer"
# Canonical mods key: "cache_writer"
```

This is NOT a basename shortcut. It IS the fully-qualified path under the import root. The two happen to coincide because the benchmark enforces flat sibling imports.

**If the benchmark ever supports nested packages**, the canonical key would become the dotted path (e.g., `"services.cache_writer"`). The current flat-sibling constraint makes this a non-issue today, but the architecture is forward-compatible.

**Collision prevention:** The preflight check (section 2.4, CHECK 2) guarantees unique basenames per case. If two files had the same stem, the preflight would reject the case before any test runs.

**Test harness `mods` dict construction:**

```python
# In _t3_harness.py (generated per case):
import importlib, sys, json

mods = {}
for mod_name in {canonical_module_names}:  # ["cache_writer", "cache_reader", "user_repo", "user_service"]
    mods[mod_name] = importlib.import_module(mod_name)
```

**Test signature and usage:**

```python
def test(mods):
    # Canonical key = fully-qualified import path (which is the stem name)
    save_user = getattr(mods["user_service"], "save_user", None)
    get_display_name = getattr(mods["cache_reader"], "get_display_name", None)
```

### 2.6 Manifest `case_package` Derivation

```python
@dataclass
class CaseManifest:
    case_id: str
    file_paths: list[str]          # full relative paths from cases.json
    files: dict[str, str]          # full_rel_path -> content (immutable after load)
    case_package: str              # common parent directory name (e.g., "hidden_dependency_hard")
    canonical_modules: list[str]   # ["cache_writer", "cache_reader", ...] (import-order sorted)
    import_graph: dict[str, list[str]]  # module_stem -> [imported module_stems]
    task: str
    failure_mode: str
    hard_constraints: list[str]
    reference_fix_file: str | None
    test_module_path: str
    test_function_name: str

def build_manifest(case: dict, base_dir: Path) -> CaseManifest:
    file_paths = case["code_files"]
    # case_package = common parent, e.g., "code_snippets/hidden_dependency_hard" -> "hidden_dependency_hard"
    common_parent = str(Path(file_paths[0]).parent)
    case_package = Path(common_parent).name  # leaf directory name

    canonical_modules = sorted(Path(f).stem for f in file_paths)
    # ... (import graph computation, file loading, etc.)
```

---

## 3. TOKEN BUDGET AND REDUCTION DESIGN

### 3.1 Immutable Manifest, Mutable PromptView

Token reduction **never mutates the manifest**. It produces an immutable `PromptView`:

```python
@dataclass(frozen=True)
class PromptView:
    """Immutable snapshot of what the model will see. Created from manifest + reduction."""
    files_full: dict[str, str]        # rel_path -> full content (shown in full)
    files_summarized: dict[str, str]  # rel_path -> signature-only content
    files_dropped: list[str]          # rel_paths not shown at all
    reduction_level: int              # 0=none, 1=whitespace, 2=summarized, 3=dropped, 4=infeasible
    original_file_count: int          # from manifest
    token_estimate: int               # estimated tokens of final prompt
    infeasible: bool                  # True if even critical files exceed budget
```

### 3.2 Reduction Algorithm (Side-Effect Free)

```python
def build_prompt_view(manifest: CaseManifest, condition: str, budget: int) -> PromptView:
    """Build an immutable PromptView within token budget. Never mutates manifest."""
    import copy

    priorities = classify_file_priority(manifest)
    # Work on copies -- manifest is never touched
    working_files = dict(manifest.files)  # shallow copy of the dict; values are strings (immutable)

    # Level 0: Full prompt
    view = PromptView(
        files_full=dict(working_files), files_summarized={},
        files_dropped=[], reduction_level=0,
        original_file_count=len(manifest.files), token_estimate=0, infeasible=False,
    )
    prompt = _render_prompt(view, manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return PromptView(**{**vars(view), "token_estimate": tokens})

    # Level 1: Strip whitespace from SECONDARY files (work on copies)
    files_l1 = {}
    for f, content in working_files.items():
        if priorities[f] == "SECONDARY":
            files_l1[f] = _strip_whitespace(content)
        else:
            files_l1[f] = content
    view_l1 = PromptView(
        files_full=files_l1, files_summarized={}, files_dropped=[],
        reduction_level=1, original_file_count=len(manifest.files),
        token_estimate=0, infeasible=False,
    )
    prompt = _render_prompt(view_l1, manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return PromptView(**{**vars(view_l1), "token_estimate": tokens})

    # Level 2: Summarize SECONDARY files (signatures only)
    files_full_l2 = {}
    files_summarized_l2 = {}
    for f, content in working_files.items():
        if priorities[f] == "SECONDARY":
            files_summarized_l2[f] = _extract_signatures(content)
        else:
            files_full_l2[f] = content
    view_l2 = PromptView(
        files_full=files_full_l2, files_summarized=files_summarized_l2,
        files_dropped=[], reduction_level=2,
        original_file_count=len(manifest.files), token_estimate=0, infeasible=False,
    )
    prompt = _render_prompt(view_l2, manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return PromptView(**{**vars(view_l2), "token_estimate": tokens})

    # Level 3: Drop SECONDARY files entirely
    files_full_l3 = {f: c for f, c in working_files.items() if priorities[f] != "SECONDARY"}
    dropped = [f for f in manifest.file_paths if priorities[f] == "SECONDARY"]
    view_l3 = PromptView(
        files_full=files_full_l3, files_summarized={}, files_dropped=dropped,
        reduction_level=3, original_file_count=len(manifest.files),
        token_estimate=0, infeasible=False,
    )
    prompt = _render_prompt(view_l3, manifest, condition)
    tokens = estimate_tokens(prompt)
    if tokens <= budget:
        return PromptView(**{**vars(view_l3), "token_estimate": tokens})

    # Level 4: Infeasible
    return PromptView(
        files_full=files_full_l3, files_summarized={}, files_dropped=dropped,
        reduction_level=4, original_file_count=len(manifest.files),
        token_estimate=tokens, infeasible=True,
    )
```

### 3.3 What Gets Logged

Every call logs the full `PromptView` metadata:

```python
log_record["prompt_view"] = {
    "reduction_level": view.reduction_level,
    "original_file_count": view.original_file_count,
    "files_full": list(view.files_full.keys()),
    "files_summarized": list(view.files_summarized.keys()),
    "files_dropped": view.files_dropped,
    "token_estimate": view.token_estimate,
    "infeasible": view.infeasible,
}
```

The original manifest is unchanged and available for re-runs, alternate conditions, and debugging.

### 3.4 Task-Definition Transparency Under Reduction

**The prompt explicitly tells the model what it is seeing.**

At reduction level 0 (no reduction), no disclosure is needed.

At reduction level 1 (whitespace stripped), no disclosure is needed (whitespace is not semantically meaningful).

At reduction level 2 (files summarized):

```
## Codebase ({N} files total, {S} shown as signatures only due to context limits)

### FILE 1/{N}: code_snippets/hidden_dependency_hard/cache_writer.py ###
```python
{full content}
```

### FILE 2/{N}: code_snippets/hidden_dependency_hard/user_service.py ###
```python
{full content}
```

### FILE 3/{N}: code_snippets/hidden_dependency_hard/user_repo.py (SIGNATURES ONLY -- full file omitted due to context limits) ###
```python
{signature-only content}
```

NOTE: File user_repo.py is shown as signatures only. It may contain
relevant implementation details not visible here. Exercise caution
when reasoning about code that calls functions defined in this file.
```

At reduction level 3 (files dropped):

```
## Codebase ({N} files total, {D} omitted due to context limits)

### FILE 1/{K}: code_snippets/hidden_dependency_hard/cache_writer.py ###
```python
{full content}
```

### FILE 2/{K}: code_snippets/hidden_dependency_hard/user_service.py ###
```python
{full content}
```

NOTE: The following files exist in this codebase but were omitted due to context limits:
- code_snippets/hidden_dependency_hard/user_repo.py
- code_snippets/hidden_dependency_hard/audit.py
These files may contain relevant code. Your fix should not depend on modifying
these files, but be aware that functions imported from them may have specific behaviors.
```

**Output contract under reduction:**
- The `files` dict in the output format instruction lists ONLY files shown in full.
- Summarized and dropped files are NOT listed in the expected output.
- The model is instructed: "You may ONLY modify files shown in full above."

**Confound tracking:**
- Results with `reduction_level >= 2` are flagged `task_reduced=True`.
- Analysis scripts report task_reduced rate and can stratify primary metrics by reduction level.
- Cases where reduction was applied are explicitly flagged in any publication table.

---

## 4. RECONSTRUCTION + ERROR TAXONOMY RULES

### 4.1 Strict Reconstruction

Unchanged from v2 section 1.5. `reconstruct_strict()` FAILS if any expected file is missing. No fallback in primary path. Salvage path is secondary-only with runtime assertions preventing primary metric contamination.

### 4.2 Error Taxonomy

| Error type | Definition | Trigger condition |
|------------|-----------|-------------------|
| `parse_error` | Cannot extract valid JSON from response | JSON parsing fails on all tiers |
| `format_violation` | Response parsed but missing `files` key, or `files` missing expected entries | `reconstruct_strict()` returns FAILED_MISSING_FILES or FAILED_EMPTY_FILES |
| `reconstruction_failure` | Files present but have syntax errors | `reconstruct_strict()` returns FAILED_SYNTAX_ERRORS |
| `execution_error` | Reconstructed files valid but test harness crashes | Subprocess returns non-zero + stderr contains ImportError/RuntimeError/timeout |
| `logic_failure` | Test ran to completion, invariant check failed | Subprocess harness reports pass=False |
| `logic_pass` | Test ran to completion, invariant check passed | Subprocess harness reports pass=True |

---

## 5. METRIC INCLUSION RULES (FULL LEG RULE TABLE)

### 5.1 LEG Definitions

- **code_correct**: True if and only if `error_type == "logic_pass"`.
- **reasoning_evaluable**: True if `reasoning` field is a non-empty string AND `response_format` is Tier 0 or 1 (file_dict or code_dict).
- **reasoning_correct**: As determined by the LLM classifier (True/False/None).

### 5.2 Full Rule Table

| # | error_type | reasoning field | code_correct | reasoning_evaluable | reasoning_correct | In primary metrics? | In LEG analysis? | In system metrics? | LEG category |
|---|------------|----------------|-------------|--------------------|--------------------|--------------------|-----------------|--------------------|-------------|
| 1 | `logic_pass` | non-empty | True | True | True | **Yes** | **Yes** | Yes | true_success |
| 2 | `logic_pass` | non-empty | True | True | False | **Yes** | **Yes** | Yes | lucky_fix |
| 3 | `logic_pass` | non-empty | True | True | None (classifier failed) | **Yes** | No (unclassified) | Yes | unclassified |
| 4 | `logic_pass` | empty/missing | True | False | N/A | **Yes** | No | Yes | unclassified |
| 5 | `logic_failure` | non-empty | False | True | True | **Yes** | **Yes** | Yes | **leg** (reasoning-execution gap) |
| 6 | `logic_failure` | non-empty | False | True | False | **Yes** | **Yes** | Yes | true_failure |
| 7 | `logic_failure` | non-empty | False | True | None | **Yes** | No (unclassified) | Yes | unclassified |
| 8 | `logic_failure` | empty/missing | False | False | N/A | **Yes** | No | Yes | unclassified |
| 9 | `execution_error` | non-empty | False | True | True | **Yes** | **Yes** | Yes | **leg** |
| 10 | `execution_error` | non-empty | False | True | False | **Yes** | **Yes** | Yes | true_failure |
| 11 | `execution_error` | non-empty | False | True | None | **Yes** | No (unclassified) | Yes | unclassified |
| 12 | `execution_error` | empty/missing | False | False | N/A | **Yes** | No | Yes | unclassified |
| 13 | `reconstruction_failure` | non-empty | False | True | True | **No** | **Yes** (secondary LEG) | Yes | **leg** (secondary) |
| 14 | `reconstruction_failure` | non-empty | False | True | False | **No** | **Yes** (secondary LEG) | Yes | true_failure (secondary) |
| 15 | `reconstruction_failure` | non-empty | False | True | None | **No** | No | Yes | unclassified |
| 16 | `reconstruction_failure` | empty/missing | False | False | N/A | **No** | No | Yes | excluded |
| 17 | `format_violation` | any | False | **False** | N/A | **No** | **No** | Yes | excluded |
| 18 | `parse_error` | N/A | False | **False** | N/A | **No** | **No** | Yes | excluded |

**Key rules encoded in this table:**

- **Rows 17-18:** `format_violation` and `parse_error` are NEVER in LEG analysis. Reasoning from malformed responses is not trustworthy.
- **Rows 13-14:** `reconstruction_failure` with evaluable reasoning enters LEG analysis but is tagged `secondary`. It is reported separately from primary LEG and MUST NOT be mixed into primary LEG rates without explicit disclosure.
- **Rows 5, 9:** These are the core LEG cases. Reasoning correct + code fails.
- **Rows 2:** Lucky fix. Code passes + reasoning wrong.
- **Row 3, 7, 11, 15:** Classifier failure -> unclassified. Not in LEG.

### 5.3 Enforcement

```python
def classify_result(result: dict) -> dict:
    """Assign LEG category. Machine-enforceable from the rule table."""
    et = result["error_type"]
    reasoning = result.get("reasoning", "")
    reasoning_eval = (
        isinstance(reasoning, str) and len(reasoning.strip()) > 0
        and result.get("response_format") in ("file_dict", "code_dict")
    )
    rc = result.get("reasoning_correct")  # True/False/None

    code_correct = (et == "logic_pass")
    in_primary = et in ("logic_pass", "logic_failure", "execution_error")
    in_leg = False
    in_leg_secondary = False
    category = "excluded"

    if in_primary and reasoning_eval:
        if rc is True and code_correct:
            category = "true_success"
            in_leg = True
        elif rc is False and code_correct:
            category = "lucky_fix"
            in_leg = True
        elif rc is True and not code_correct:
            category = "leg"
            in_leg = True
        elif rc is False and not code_correct:
            category = "true_failure"
            in_leg = True
        elif rc is None:
            category = "unclassified"
    elif et == "reconstruction_failure" and reasoning_eval:
        if rc is True:
            category = "leg"
            in_leg_secondary = True
        elif rc is False:
            category = "true_failure"
            in_leg_secondary = True
    elif in_primary and not reasoning_eval:
        category = "unclassified"

    return {
        "code_correct": code_correct,
        "reasoning_evaluable": reasoning_eval,
        "reasoning_correct": rc,
        "in_primary_metrics": in_primary,
        "in_leg_analysis": in_leg,
        "in_leg_secondary": in_leg_secondary,
        "in_system_metrics": True,
        "leg_category": category,
    }
```

---

## 6. VALIDATION PLAN

### 6.1 Repo-Root Import Test (NEW)

```python
def test_repo_root_imports():
    """Verify PYTHONPATH=pkg_root makes flat sibling imports work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = Path(tmpdir) / "test_case"
        pkg.mkdir()
        (pkg / "models.py").write_text("class Foo:\n    x = 1")
        (pkg / "service.py").write_text("from models import Foo\ndef get(): return Foo.x")
        result = subprocess.run(
            [sys.executable, "-c", "from service import get; assert get() == 1; print('OK')"],
            cwd=pkg, env={"PYTHONPATH": str(pkg), "PATH": os.environ["PATH"]},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
```

### 6.2 Canonical Module Key Test (NEW)

```python
def test_canonical_mods_keys():
    """Verify mods dict keys match fully-qualified import paths."""
    manifest = build_manifest(SAMPLE_MULTI_FILE_CASE)
    harness_code = _generate_harness(manifest, "dummy_test.py")
    # Parse the generated harness to extract mods keys
    for mod_name in manifest.canonical_modules:
        assert f'mods["{mod_name}"]' in harness_code or f"importlib.import_module(\"{mod_name}\")" in harness_code
    # Verify no basename-only shortcuts that differ from canonical
    assert "Path(" not in harness_code, "Harness must not derive keys from Path operations"
```

### 6.3 Reduction Immutability Test (NEW)

```python
def test_reduction_does_not_mutate_manifest():
    """Token reduction must not change the original manifest."""
    manifest = build_manifest(LARGE_CASE)
    original_files = dict(manifest.files)  # snapshot
    original_paths = list(manifest.file_paths)

    # Run reduction at aggressive budget
    view = build_prompt_view(manifest, "baseline", budget=500)

    # Manifest must be unchanged
    assert manifest.files == original_files, "Manifest files were mutated"
    assert manifest.file_paths == original_paths, "Manifest file_paths were mutated"
    # PromptView may differ
    assert view.reduction_level >= 1, "Expected reduction at budget=500"
```

### 6.4 Reduction Disclosure Test (NEW)

```python
def test_reduction_disclosure_in_prompt():
    """Reduced prompt must explicitly disclose summarized/dropped files."""
    manifest = build_manifest(LARGE_CASE)

    # Level 2: summarized
    view_l2 = build_prompt_view(manifest, "baseline", budget=3000)
    if view_l2.reduction_level == 2:
        prompt = render_prompt(view_l2, manifest, "baseline")
        for f in view_l2.files_summarized:
            assert "SIGNATURES ONLY" in prompt, f"Summarized file {f} not disclosed"
        assert "context limits" in prompt.lower()

    # Level 3: dropped
    view_l3 = build_prompt_view(manifest, "baseline", budget=1000)
    if view_l3.reduction_level == 3:
        prompt = render_prompt(view_l3, manifest, "baseline")
        for f in view_l3.files_dropped:
            fname = Path(f).name
            assert fname in prompt, f"Dropped file {f} not mentioned in prompt"
        assert "omitted" in prompt.lower()
```

### 6.5 LEG Classification Table Test (NEW)

```python
def test_leg_classification_all_rows():
    """Verify every row of the LEG rule table produces correct classification."""
    test_cases = [
        # (error_type, reasoning, response_format, reasoning_correct, expected_category, expected_primary, expected_leg)
        ("logic_pass",  "good analysis", "file_dict", True,  "true_success", True, True),
        ("logic_pass",  "wrong analysis","file_dict", False, "lucky_fix",    True, True),
        ("logic_pass",  "analysis",      "file_dict", None,  "unclassified", True, False),
        ("logic_pass",  "",              "file_dict", None,  "unclassified", True, False),
        ("logic_failure","good analysis","file_dict", True,  "leg",          True, True),
        ("logic_failure","wrong",        "file_dict", False, "true_failure", True, True),
        ("execution_error","good",       "file_dict", True,  "leg",          True, True),
        ("execution_error","wrong",      "file_dict", False, "true_failure", True, True),
        ("reconstruction_failure","good","file_dict", True,  "leg",          False, False),  # in_leg_secondary=True
        ("reconstruction_failure","good","file_dict", False, "true_failure", False, False),
        ("reconstruction_failure","",    "file_dict", None,  "excluded",     False, False),
        ("format_violation", "any",      "file_dict", None,  "excluded",     False, False),
        ("parse_error",      "",         "raw_fallback",None,"excluded",     False, False),
    ]
    for et, reasoning, fmt, rc, exp_cat, exp_primary, exp_leg in test_cases:
        result = {"error_type": et, "reasoning": reasoning, "response_format": fmt, "reasoning_correct": rc}
        classified = classify_result(result)
        assert classified["leg_category"] == exp_cat, f"Row {et}/{reasoning[:10]}: got {classified['leg_category']}"
        assert classified["in_primary_metrics"] == exp_primary
        assert classified["in_leg_analysis"] == exp_leg
```

### 6.6 Import Summary Calibration Harness Test (NEW)

```python
def test_import_summary_experiment_infrastructure():
    """Verify calibration experiment can produce matched pairs."""
    manifest = build_manifest(MULTI_FILE_CASE)
    prompt_without = render_prompt(
        build_prompt_view(manifest, "baseline", budget=20000), manifest, "baseline"
    )
    prompt_with = render_prompt(
        build_prompt_view(manifest, "baseline_with_import_summary", budget=20000), manifest,
        "baseline", include_import_summary=True,
    )
    # With-summary prompt must be longer
    assert len(prompt_with) > len(prompt_without)
    # Both must contain all files
    for f in manifest.file_paths:
        assert Path(f).name in prompt_without
        assert Path(f).name in prompt_with
    # Only the with-summary prompt contains import structure
    assert "imports from" in prompt_with.lower() or "import structure" in prompt_with.lower()
    assert "imports from" not in prompt_without.lower()
```

### 6.7 Old-vs-New Pipeline Comparison Harness Test (NEW)

```python
def test_old_new_comparison_infrastructure():
    """Verify comparison experiment can run both pipelines on same case."""
    case = load_single_case("alias_config_a")

    # Old pipeline: concatenation + exec
    old_result = run_old_pipeline(case, model="mock")

    # New pipeline: reconstruction + subprocess
    new_result = run_new_pipeline(case, model="mock")

    # Both must produce valid result dicts with required fields
    for r in [old_result, new_result]:
        assert "pass" in r
        assert "error_type" in r
        assert "score" in r
    # For mock model, results should be deterministic across repeated calls
```

### 6.8 Existing Tests (from v2, retained)

- Roundtrip test (all UNCHANGED -> identical)
- Missing file rejection test
- Cross-module import stress test
- Format robustness (whitespace in UNCHANGED, extra files)
- Cross-case isolation test
- Token budget reduction levels test
- Parallel safety test

---

## 7. CALIBRATION EXPERIMENTS

### 7.1 Import Summary Calibration

```
Experiment: IMPORT_SUMMARY_CALIBRATION
Design: Within-subjects, paired comparison
  Condition A: baseline (no import summary)
  Condition B: baseline + import summary

Cases: All multi-file cases from cases_v2.json where len(code_files) >= 2
       Minimum N = 15 cases. If fewer, include multi-file cases from cases.json.
Models: gpt-4.1-nano, gpt-4o-mini (one small, one medium)
Trials: 1 per model (temperature=0 ensures determinism)

Outcome measures:
  1. pass_rate_delta = pass_rate_B - pass_rate_A
  2. leg_rate_delta = leg_rate_B - leg_rate_A
  3. reasoning_correct_delta
  4. format_compliance_rate_delta (file_dict rate B vs A)
  5. parse_failure_rate_delta
  6. avg_prompt_tokens_delta (B should be ~30-50 tokens larger)
  7. avg_completion_tokens_delta (may change if model reasons differently)
  8. reconstruction_failure_rate_delta

Interpretation thresholds:
  - |pass_rate_delta| < 3% AND |leg_rate_delta| < 2%:
      -> Neutral. Import summary may be included in all conditions.
  - pass_rate_delta > 3%:
      -> Performance-affecting. Either:
         (a) Treat as separate condition (import_summary = new condition), OR
         (b) Exclude from default prompt template.
  - leg_rate_delta > 2%:
      -> Affects reasoning measurement. MUST NOT be in LEG conditions.
  - format_compliance_rate_delta > 5%:
      -> Import summary affects output formatting. Report as confound.
  - reconstruction_failure_rate_delta > 3%:
      -> Import summary affects code quality. Report and investigate.

Decision matrix:
  - Neutral on all -> include in all conditions (simplest, no confound)
  - Affects pass but not LEG -> include as separate experimental condition
  - Affects LEG -> exclude from default, available as opt-in condition
  - Affects formatting -> investigate prompt interaction, do not deploy

Timeline: Run after Phase 1 is complete (new prompt format active).
Blocking: Results gate Phase 3 deployment.
```

### 7.2 Old-vs-New Pipeline Calibration (MANDATORY)

```
Experiment: PIPELINE_CALIBRATION
Purpose: Quantify infrastructure-induced bias in old system.
         This is appendix-quality evidence for a methodology section.

Design: Between-systems, same model, same cases
  System A: Old pipeline (concatenation + assembly + in-process exec)
  System B: New pipeline (file-dict + strict reconstruction + subprocess)

Cases: Stratified sample:
  - 5 single-file cases (A-level difficulty)
  - 5 multi-file 2-file cases (B-level)
  - 5 multi-file 3+-file cases (C-level)
  - At least 3 hard mechanistic cases (invariant_partial_fail, l3_state_pipeline, hidden_dep_multihop)
  Total: 18-20 cases minimum

Models: gpt-4.1-nano (budget model, most sensitive to infrastructure effects)
Conditions: baseline only (isolates infrastructure effect from nudge effects)
Trials: 1 per system (temperature=0)

Outcome measures:
  1. pass_rate by file-count stratum (single / 2-file / 3+-file)
  2. LEG rate by stratum
  3. lucky_fix rate by stratum
  4. format_violation rate (System B only -- System A has no format requirement)
  5. reconstruction_failure rate (System B only)
  6. assembly_crutch rate (System A only -- cases where model output lacked definitions filled by assembly)
  7. failure_type_distribution per system

Interpretation:
  - Single-file pass rate: Should be IDENTICAL (same model, same prompt structure modulo delimiters).
    Delta > 2%: investigation required (prompt format effect).

  - Multi-file pass rate System B < System A:
    EXPECTED if System A's assembly crutch was inflating results.
    This is not a bug -- it is evidence of infrastructure-induced bias in the old system.
    Report magnitude: "Assembly assistance inflated multi-file pass rates by X%."

  - Multi-file pass rate System B > System A:
    UNEXPECTED. Investigate whether old concatenation/import-stripping was breaking valid code.

  - LEG rate System B != System A:
    Investigate whether the reasoning classifier sees different code in each system.
    System A's classifier saw concatenated code (potentially different from what actually ran).
    System B's classifier sees per-file code (matches what ran).

  - lucky_fix rate System B < System A:
    EXPECTED. Old system's assembly filled in correct code the model didn't produce,
    making it look like the model fixed the bug. New system doesn't do this.

Output: A comparison table suitable for a paper appendix:

  | Metric          | Old Pipeline | New Pipeline | Delta  | Interpretation |
  |-----------------|-------------|-------------|--------|----------------|
  | pass (1-file)   | X%          | Y%          | Y-X    | Should be ~0   |
  | pass (2-file)   | X%          | Y%          | Y-X    | Assembly effect |
  | pass (3+-file)  | X%          | Y%          | Y-X    | Assembly effect |
  | LEG rate        | X%          | Y%          | Y-X    | Classifier input effect |
  | lucky_fix rate  | X%          | Y%          | Y-X    | Assembly inflation |

Timeline: Run after Phase 2 is complete (both systems operational).
Blocking: Results gate Phase 3 (legacy removal).
          If single-file delta > 2%, Phase 3 is blocked until root cause is found.
```

---

## 8. PHASED IMPLEMENTATION PLAN

### Phase 0: Instrumentation (no behavior change)

Unchanged from v2. Adds: `response_format` tags, token counting, empty-file assertions, file-dict parser tier.

**Additionally:** Add import consistency validation (section 2.4) to `load_cases()`. This runs at startup and fails fast if any case violates the flat-sibling-import contract.

### Phase 1: Output Format + Strict Reconstruction + Token Budget

1. New `_JSON_OUTPUT_INSTRUCTION_V2` in `llm.py` with `files` dict format.
2. New `reconstructor.py` with `reconstruct_strict()` / `reconstruct_salvage()`.
3. New `_format_code_files_v2()` with `### FILE N/M` delimiters.
4. New `prompt_view.py` with immutable `PromptView` and `build_prompt_view()`.
5. Task-definition disclosure in prompt for reduction levels 2-3.
6. Wire into execution pipeline. Old `_assemble_program()` retained as temporary fallback for Tier 2-3 responses.
7. Import summary calibration experiment (section 7.1).

**Rollback:** Revert to V1 output instruction. One flag.

### Phase 2: Subprocess Execution + Test Rewrite

1. New `subprocess_eval.py` with case-local package materialization (section 2.2).
2. Rewrite all 58 test functions to `test(mods)` signature with canonical module keys.
3. New test harness generator.
4. Update `exec_evaluate()` to dispatch to subprocess path.
5. Update `validate_cases_v2.py` to subprocess path.
6. **Phase 2 blocking validation:** `validate_cases_v2.py` equivalence on all cases.
7. **Pipeline calibration experiment** (section 7.2).

**Rollback:** `USE_SUBPROCESS = False` flag. Legacy path still exists.

### Phase 3: Legacy Removal + Hardening

**Entrance criteria (ALL must be true):**
1. Phase 2 `validate_cases_v2` equivalence: 100% match
2. Pipeline calibration experiment complete, single-file delta < 2%
3. Import summary calibration experiment complete
4. At least one full ablation run with new system
5. Format compliance > 80% for all target models

**Changes:**
1. Delete `_assemble_program()`, `load_module_from_code()`, `strip_local_imports()`, `_stdlib.py`, `_JSON_OUTPUT_INSTRUCTION_V1`.
2. Delete parser Tiers 2-4 from primary path (archive to `_legacy_parse.py`).
3. Runtime assertions enforcing metric inclusion rules.
4. Full validation test suite (section 6).

**Removal is permanent.** Git history preserves old code. Legacy code moved to `_legacy/` directory in a tagged commit before deletion.

---

## 9. RISKS + MITIGATIONS

### R1: Test Rewrite Introduces Bugs
58 test functions rewritten. **Mitigation:** `validate_cases_v2` equivalence check is blocking. Each test validated against reference fix (pass) and buggy code (fail). Script generates mods-key mapping from AST analysis.

### R2: Models Fail to Produce File-Dict Format
**Mitigation:** Format violations excluded from primary metrics. Format compliance rate reported per model. Output instruction tunable.

### R3: Token Reduction Changes Task Definition
**Mitigation:** PromptView is immutable, manifest unchanged. Prompt explicitly discloses reduction. Results flagged `task_reduced=True`. Analysis stratifies by reduction level.

### R4: Subprocess Overhead
~0.2s x 1250 evals = 4 min on a 20-30 min run. Negligible.

### R5: Import Summary Experiment Shows Bias
**Mitigation:** Experiment runs before deployment. If biased, summary is excluded or treated as separate condition.

### R6: Salvage Path Leaks into Primary Metrics
**Mitigation:** Runtime assertion: `assert all(r["reconstruction_mode"] != "salvaged" for r in primary_results)`.

### R7: Pipeline Calibration Shows Unexpected Single-File Divergence
**Mitigation:** Blocks Phase 3 until root cause identified and fixed.

### R8: Case-Local Package Root Assumption Breaks on Future Cases
The benchmark currently constrains all case files to a single directory with flat imports (validated at preflight). If future cases need nested packages, the `case_package` derivation and PYTHONPATH computation must be extended. **Mitigation:** Preflight validation (section 2.4) will reject invalid cases immediately, preventing silent failures. Extension path is documented.

### R9: Immutable PromptView Adds Complexity
**Mitigation:** `PromptView` is a frozen dataclass (~15 lines). `build_prompt_view()` is a pure function (~60 lines). Net complexity is low.

### R10: Old-vs-New Calibration Reveals Old Results Were Inflated
This is not a risk -- it is a finding. The calibration experiment is designed to quantify infrastructure-induced bias. If the old system inflated multi-file pass rates, that is important evidence for the methodology section of the paper.
