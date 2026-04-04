# Code Assembly Audit & Refactor Plan

## Date: 2026-03-30

---

## 1. AUDIT: Current Assembly Pipeline

### 1.1 The Assembly Flow

When a model produces code for a multi-file case, the code goes through this pipeline:

```
Model response
  → parse_model_response() or parser_v2       [parse.py / parser_v2.py]
  → _do_reconstruction()                       [execution.py:303]
      → reconstruct_strict()                   [reconstructor.py:88]
      → join changed files: "\n\n".join()      [execution.py:319]
  → code string passed to exec_evaluate()      [exec_eval.py:789]
      → _assemble_program()                    [exec_eval.py:700]
          → strip_local_imports(original)       [parse.py]
          → strip_local_imports(model_code)     [parse.py]
          → assembled = original + "\n\n" + model
      → load_module_from_code(assembled)       [exec_eval.py:33]
          → strip_local_imports(code) AGAIN     [parse.py]
          → exec(compile(code), mod.__dict__)
```

### 1.2 Files Involved

| File | Responsibility | Lines |
|---|---|---|
| `parse.py` | `strip_local_imports()`, `classify_import()` | 693-790 |
| `reconstructor.py` | Map model file-dict back to case files, normalize content | 1-202 |
| `execution.py` | `_do_reconstruction()` — join changed files into code string | 303-354 |
| `exec_eval.py` | `_assemble_program()` — merge original + model code | 700-786 |
| `exec_eval.py` | `load_module_from_code()` — strip imports + exec | 33-53 |

### 1.3 Bugs Found

#### BUG 1: `strip_local_imports` breaks aliased imports (CONFIRMED — 11 cases affected)

```python
from metrics import reset as metrics_reset
```
Strip removes the import line. `metrics_reset` is now undefined in the code body.

Affected patterns:
- `from X import Y as Z` — 38 occurrences in model code (16 unique)
- `import X as Y` — 2 occurrences
- `import X` with `X.func()` calls — 136 occurrences

#### BUG 2: `strip_local_imports` called TWICE on the same code

1. `_assemble_program()` calls `strip_local_imports(model_code)` at line 742
2. `load_module_from_code()` calls `strip_local_imports(code)` again at line 41

The second call operates on already-stripped code. This is wasteful but not directly harmful — unless the double-strip interacts badly with partially stripped content.

#### BUG 3: Reconstruction joins only CHANGED files, assembly prepends ALL originals

- `_do_reconstruction()` at line 318-319: `parsed["code"] = "\n\n".join(changed_parts)`
  - Only includes files the model modified (not UNCHANGED files)
- `_assemble_program()` at line 732-738: prepends ALL original files
  - This means UNCHANGED files appear from the originals, and changed files appear from the model
  - The model's changed files override the originals (Python last-definition-wins)

This WORKS but is fragile. If the model redefines a function with a different signature, the original module's other functions may still reference the old signature. The override only works at the top-level definition level, not for intra-module calls.

#### BUG 4: No handling of model adding NEW files

If the model returns a file that isn't in the manifest (e.g., creates a helper module), `reconstruct_strict` records it as `extra_files` but drops the content. The model's new file is silently lost.

#### BUG 5: Single-file case skips assembly entirely

`_assemble_program` line 719: `if len(code_contents) <= 1: return model_code`

For single-file cases, the model's code is used directly. But `strip_local_imports` is still called in `load_module_from_code`. If the model writes `import os` and `os` happens to not be in STDLIB_MODULES (due to an incomplete list), the import is stripped and the code breaks.

#### BUG 6: Reconstruction content normalization is incomplete

`reconstructor.py:_normalize_file_content()` handles:
- Markdown fences (```python ... ```)
- Escaped newlines (\\n when no real newlines)

Does NOT handle:
- Triple-quoted strings with unescaped quotes (the nano JSON issue)
- HTML entities (&amp; etc.)
- Unicode escapes
- BOM characters

#### BUG 7: Duplicate stripping has no idempotency guarantee

When `strip_local_imports` runs twice (bug 2), it may produce different results if the first pass partially strips a multi-line import, leaving fragments that the second pass misinterprets.

### 1.4 Architecture Problems

1. **Assembly logic is scattered across 4 files** — parse.py, reconstructor.py, execution.py, exec_eval.py all participate in turning model output into executable code. No single file owns the full pipeline.

2. **No clear contract between stages** — _do_reconstruction() outputs a code string by joining changed files. _assemble_program() receives that string and has no way to know which parts are from the model vs originals. It re-discovers this by regex-matching function names.

3. **strip_local_imports is a string hack** — It works on text, not AST. It can't handle aliases, module-qualified calls, multi-line imports, or conditional imports. Every new LLM import pattern requires a new regex.

4. **No test coverage for assembly edge cases** — The assembly pipeline has no unit tests for aliased imports, module-qualified calls, duplicate definitions, or cross-file dependencies.

5. **Multi-file assembly is concat-based** — All files are concatenated into one Python string and exec'd as a single module. This means:
   - Module boundaries are lost
   - `import X` from one file to another becomes meaningless
   - Module-level variables in different files can collide
   - `__name__` is shared across all files

---

## 2. PLAN: Assembly Module Refactor

### 2.1 New File: `code_assembly.py`

Create a single module that owns the entire assembly pipeline. All assembly logic moves here.

### 2.2 Architecture

```
model output (code string or files dict)
  → CodeAssembler.assemble(model_output, case)
      → Step 1: Resolve files (UNCHANGED → original, changed → model)
      → Step 2: Normalize content (fences, escapes)
      → Step 3: Validate syntax per-file (before any stripping)
      → Step 4: Rewrite imports (AST-based, per-file)
      → Step 5: Concatenate (ordered: originals first, model overrides last)
      → Step 6: Validate assembled result (compile check)
      → returns AssemblyResult
```

### 2.3 AST-Based Import Rewriting

Replace `strip_local_imports` with `rewrite_local_imports`:

```python
def rewrite_local_imports(code: str, local_modules: frozenset) -> str:
    """AST-based import rewriting for concatenated module assembly.

    Instead of deleting import lines and hoping, this:
    1. Parses the code as AST
    2. Finds all imports of local modules
    3. Builds a rewrite map:
       - from X import Y as Z  →  rename Z to Y everywhere
       - import X              →  rewrite X.func() to func() everywhere
       - import X as Y         →  rewrite Y.func() to func() everywhere
    4. Removes the import nodes
    5. Applies the rewrite map to all Name and Attribute nodes
    6. Unparses back to code

    Falls back to line-based stripping if AST parse fails.
    """
```

Rewrite rules:

| Import Pattern | Action |
|---|---|
| `from X import a` | Delete import. `a` is already in namespace from concat. |
| `from X import a as b` | Delete import. Rename all `b` → `a` in code body. |
| `from X import a, b as c` | Delete import. Keep `a`. Rename `c` → `b`. |
| `import X` | Delete import. Rewrite `X.func()` → `func()`, `X.VAR` → `VAR`. |
| `import X as Y` | Delete import. Rewrite `Y.func()` → `func()`, `Y.VAR` → `VAR`. |
| `import X, Y` | Split. Handle each independently. |
| `from X import *` | Delete import. All names already in namespace. |
| `from . import X` | Delete. Relative imports meaningless in concat. |

### 2.4 Per-File Processing

Process each file independently BEFORE concatenation:
1. Parse as AST (catch syntax errors per-file)
2. Identify local imports
3. Apply rewrite rules
4. Unparse
5. Track which names were rewritten (for diagnostics)

Then concatenate the processed files.

### 2.5 Smarter Concatenation Order

Current: original files first, then model code (model overrides originals by last-definition-wins).

Better: for each file in the manifest, use the model's version if provided, otherwise the original. This way:
- No duplicate definitions
- No reliance on Python override semantics
- Clear provenance: each function comes from exactly one source

### 2.6 AssemblyResult Dataclass

```python
@dataclass
class AssemblyResult:
    code: str                        # Final assembled code, ready for exec
    status: str                      # SUCCESS, SYNTAX_ERROR, IMPORT_REWRITE_FAILED
    files_used: dict[str, str]       # path → "model" | "original" | "unchanged"
    rewrites_applied: list[dict]     # [{type, original, rewritten, file}]
    duplicate_defs: list[str]        # Functions defined in multiple files
    rename_error: bool               # Model didn't override expected function
    syntax_errors: dict[str, str]    # Per-file syntax errors (pre-assembly)
    assembly_warnings: list[str]     # Non-fatal issues
```

### 2.7 Migration

1. Create `code_assembly.py` with the new logic
2. Add comprehensive tests: `tests/test_code_assembly.py`
3. Wire into `exec_eval.py`: replace `_assemble_program` + `load_module_from_code` with calls to `CodeAssembler`
4. Remove `strip_local_imports` from `parse.py` (move to `code_assembly.py`)
5. Remove duplicate strip call from `load_module_from_code`

### 2.8 Test Cases for the New Assembly

Must cover:
1. `from X import Y as Z` — alias rewriting
2. `import X` + `X.func()` — module-qualified calls
3. `import X as Y` + `Y.func()` — aliased module calls
4. Multi-file with UNCHANGED files
5. Model adds new function not in originals
6. Model renames a function (rename detection)
7. Model with syntax errors in one file but valid code in another
8. Markdown fences inside file content
9. Triple-quoted docstrings (the nano JSON issue)
10. Empty files / all UNCHANGED
11. Single-file cases (no assembly needed)
12. Model imports stdlib that looks like a local module name

### 2.9 What NOT to Change

- `reconstructor.py` stays — it handles file-dict → resolved files mapping. That's separate from assembly.
- `execution.py:_do_reconstruction()` stays — it orchestrates the reconstruction step.
- The pipeline flow stays the same — just the assembly internals become cleaner.

---

## 3. PRIORITY

**High.** The aliased import bug currently affects 1.6% of evaluations and is concentrated in gpt-5-mini multi-file cases. The AST-based approach would also future-proof against any new import patterns LLMs might produce.

**Estimated scope:** ~200 lines of new code in `code_assembly.py`, ~100 lines of tests. The migration from `exec_eval.py` is mechanical — replacing `_assemble_program` and removing the duplicate strip.
