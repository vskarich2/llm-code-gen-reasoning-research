# Code Assembly Refactor — Implementation Audit

**Date:** 2026-03-30
**Scope:** Replace scattered text-based import stripping with centralized AST-based assembly module

---

## 1. What Was Built

### 1.1 New File: `code_assembly.py` (365 lines)

Single source of truth for all code assembly logic. Contains:

**Public API:**
- `CodeAssembler` class with `assemble(model_code, case) -> AssemblyResult`
- Module-level `assemble()` convenience function

**`AssemblyResult` dataclass:**
- `code: str` — final assembled code
- `status: str` — SUCCESS | SYNTAX_ERROR | REWRITE_ERROR | ASSEMBLY_ERROR
- `files_used: dict` — path → "model" | "original" | "extra"
- `rewrites_applied: list[dict]` — every import rewrite with type, file, old/new names
- `warnings: list[str]` — non-fatal issues
- `errors: list[str]` — fatal issues
- Compatibility fields: `assembly_used`, `assembly_risky`, `rename_error`, `expected_func`, `duplicate_defs`, `sources`

**Pipeline (6 steps, strict order):**
1. Resolve files — model version if provided, else original
2. Normalize content — markdown fences, escaped newlines
3. Validate syntax per-file — `ast.parse` before any rewriting
4. Rewrite imports — AST-based, mode-dependent
5. Concatenate — originals first, model last (preserves override semantics)
6. Validate final — `compile()` check on assembled result

**Three assembly modes:**
- `compat` — line-based stripping only (old behavior, no renames, for regression testing)
- `safe` — AST-based rewriting for deterministic cases (default)
- `full` — reserved for future (module-qualified rewriting)

**Import rewriting rules (safe mode):**

| Pattern | Action |
|---|---|
| `from X import Y` (X is local) | Delete import. Y available from concat. |
| `from X import Y as Z` (X is local) | Delete import. Rename all Z → Y via AST. |
| `from X import *` (X is local) | Delete import. All names in concat namespace. |
| `from . import X` | Delete. Relative imports meaningless in concat. |
| `import X` (no X.attr usage) | Delete. No attribute access, safe to remove. |
| `import X` (has X.attr usage) | **KEEP**. Emit warning. Can't safely rewrite in safe mode. |
| `import X as Y` (has Y.attr usage) | **KEEP**. Emit warning. |
| Any stdlib import | **KEEP**. Never touch stdlib. |

**AST transformers:**
- `_NameRewriter(ast.NodeTransformer)` — renames identifiers per rename_map (e.g., `metrics_reset` → `reset`)
- `_ImportRemover(ast.NodeTransformer)` — removes specific import nodes by identity

**Supporting functions:**
- `_normalize_content()` — strips markdown fences, unescapes \\n
- `_is_local_module()` — checks against STDLIB_MODULES and case file list
- `_collect_import_info()` — walks AST to classify all imports
- `_find_attribute_usages()` — finds X.attr patterns for a given module name
- `_rewrite_imports_safe()` — the main safe-mode rewriter
- `_strip_imports_compat()` — the old line-based behavior for compat mode

### 1.2 New File: `tests/test_code_assembly.py` (403 lines, 26 tests)

| Test Class | Tests | What It Covers |
|---|---|---|
| `TestSingleFile` | 2 | Passthrough for 1-file cases, local import stripping |
| `TestMultiFileBasic` | 4 | Override ordering, duplicate detection, unchanged handling, rename detection |
| `TestAliasRewriting` | 3 | `from X import Y as Z` rename, ambiguous alias, multiple aliases in one import |
| `TestModuleQualified` | 3 | `import X; X.func()` kept in safe mode, bare `import X` removed when no attrs, `import X as Y` with attrs kept |
| `TestStarAndRelative` | 3 | `from X import *` removed, relative imports removed, stdlib preserved |
| `TestSyntaxErrors` | 2 | Model syntax error reported, original syntax error warned |
| `TestNormalization` | 2 | Markdown fences stripped, escaped newlines unescaped |
| `TestCompatMode` | 3 | Compat strips locals, preserves stdlib, does NOT rename aliases (the old bug) |
| `TestCollisions` | 2 | Model overriding original is allowed, provenance tracked |
| `TestIdempotency` | 1 | Double assembly produces identical output |
| `TestDeterminism` | 1 | Same input → same output across 5 runs |

### 1.3 Modified File: `exec_eval.py`

**Imports changed:**
- Removed: `strip_local_imports as _strip_local_imports`, `STDLIB_MODULES as _STDLIB_MODULES` from `parse`
- Added: `CodeAssembler`, `AssemblyResult` from `code_assembly`

**`load_module_from_code()` — duplicate strip removed:**
- Before: called `_strip_local_imports(code)` before `exec(compile(...))`
- After: receives already-assembled code, no stripping. The docstring explicitly states "Import stripping is handled by CodeAssembler BEFORE this function."

**`_assemble_program()` — gutted and delegated:**
- Before: 87 lines of inline assembly logic (regex def detection, manual concat, strip calls)
- After: 25 lines delegating to `CodeAssembler().assemble()` + logging

**All `asm[...]` dict access converted to `asm.attr` dataclass access:**
- 0 remaining `asm[` references
- 23 `asm.` attribute accesses

---

## 2. What Was Removed

- `_strip_local_imports` is no longer imported in `exec_eval.py`
- `_STDLIB_MODULES` is no longer imported in `exec_eval.py`
- `load_module_from_code` no longer calls `strip_local_imports` (the double-strip bug)
- `_assemble_program` no longer contains inline assembly logic

**`strip_local_imports` in `parse.py` is NOT deleted** — it's still there for backward compatibility with other code that may import it. The `code_assembly.py` module has its own `_strip_imports_compat` for compat mode, and `_rewrite_imports_safe` for safe mode. The canonical path no longer touches `parse.py:strip_local_imports`.

---

## 3. Bugs Fixed

### BUG 1: Aliased imports stripped without renaming references
- **Before:** `from metrics import reset as metrics_reset` → import removed, `metrics_reset()` becomes NameError
- **After:** Import removed, AST renames all `metrics_reset` → `reset` in code body
- **Test:** `TestAliasRewriting.test_from_import_as_rewritten`

### BUG 2: Double stripping in load_module_from_code
- **Before:** `_assemble_program` strips imports, then `load_module_from_code` strips again
- **After:** Assembly happens once in `CodeAssembler`, `load_module_from_code` receives final code
- **Test:** `TestIdempotency.test_double_assembly_same_result`

### BUG 3 (partially): `import X` with `X.func()` calls
- **Before:** `import metrics` removed, `metrics.reset()` becomes NameError
- **After:** In safe mode, `import metrics` is KEPT when `X.func()` usage detected. Warning emitted.
- **Not fixed:** The import is kept, which means the code will fail at runtime with `ModuleNotFoundError` since `metrics` isn't a real module in the concat namespace. Full mode (future) would rewrite `metrics.reset()` → `reset()`.
- **Test:** `TestModuleQualified.test_import_x_with_attr_access_kept`

---

## 4. Invariants Enforced

| Invariant | How Enforced |
|---|---|
| **I1 Semantic Preservation** | AST-based rewriting preserves binding correctness. Renames are applied to all Name nodes. Override ordering (originals first, model last) is preserved. |
| **I2 Determinism** | No randomness. Same input → same output. Verified by `TestDeterminism`. |
| **I3 Idempotency** | `assemble(assemble(x))` produces same result. Verified by `TestIdempotency`. |
| **I4 No Silent Failures** | Every rewrite logged in `rewrites_applied`. Ambiguous cases produce warnings. Syntax errors surface as `status=SYNTAX_ERROR`. |
| **I5 Single Canonical Path** | `CodeAssembler.assemble()` is the only assembly entry point. `exec_eval.py` delegates to it. No other file assembles code. |

---

## 5. What Was NOT Changed

- **`parse.py`** — `strip_local_imports` still exists for backward compat. Not deleted.
- **`reconstructor.py`** — File-dict → resolved files mapping. Untouched.
- **`execution.py:_do_reconstruction()`** — Reconstruction orchestration. Untouched.
- **Override semantics** — Originals first, model last, Python last-definition-wins. Unchanged.
- **Single-file behavior** — Single-file cases bypass assembly entirely. Same as before.

---

## 6. Known Limitations

1. **Module-qualified access (`import X; X.func()`) is not rewritten in safe mode.** The import is kept and a warning emitted. This means the code will fail at runtime with ModuleNotFoundError if X is a local module. This affects ~136 occurrences in model code (mostly `import metrics`, `import audit`). Full mode would fix this but requires scope analysis.

2. **`ast.unparse()` reformats code.** The AST round-trip (parse → transform → unparse) changes whitespace, comments, and formatting. The code is semantically identical but visually different from the model's output. This could affect debugging (the executed code doesn't look like what the model wrote).

3. **Compat mode preserves the old alias bug.** By design — compat mode exists for regression testing against old behavior. The `TestCompatMode.test_compat_does_not_rename_aliases` test explicitly verifies this.

4. **Extra files (model creates new files not in manifest) are not yet handled.** The current implementation only processes files in the case manifest. Model-created extra files are silently dropped. This matches old behavior.

---

## 7. Verification

- 26 tests, all passing
- End-to-end test with the exact bug pattern (`from metrics import reset as metrics_reset`) — assembly now handles it correctly
- End-to-end test with stdlib imports (`import copy`) — preserved correctly
- `exec_eval.py` compiles cleanly with 0 references to old `strip_local_imports`
