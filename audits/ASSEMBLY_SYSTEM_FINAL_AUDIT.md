# Assembly System — Final Audit & Summary

**Date:** 2026-03-30
**Scope:** Complete rewrite of code assembly from scattered text hacks to a single canonical AST-based system

---

## 1. Problem Statement

The T3 benchmark assembles multi-file Python programs by concatenating case files + model output into a single module and exec'ing it. Local inter-file imports (`from metrics import reset`) must be removed since the imported names are already in the concatenated namespace.

Before this work, import stripping was:
- Scattered across 5 files (parse.py, exec_eval.py, validate_cases_v2.py, preflight_check.py, test_eval_integration.py)
- Implemented 3 different ways (each with its own stdlib set and edge case handling)
- Text-based (regex line matching, no AST awareness)
- Broken on aliased imports (`from X import Y as Z` → Z becomes undefined)
- Broken on module-qualified access (`import X; X.func()` → ModuleNotFoundError)
- Applied twice in the exec path (double stripping in _assemble_program + load_module_from_code)

**Impact:** 47 evaluations across ablation runs (1.88% of all evals) failed due to assembly bugs, not model failures. These were concentrated in gpt-5-mini which writes more sophisticated import patterns.

---

## 2. What Was Built

### New file: `code_assembly.py` (828 lines)

Single source of truth for all code assembly. Contains:

**Pipeline (7 steps, strict order):**
1. Resolve files — model version if provided, else original
2. Normalize content — markdown fences, escaped newlines
3. Validate syntax per-file — `ast.parse` before any rewriting
4. Rewrite imports (safe mode) — AST-based alias handling
5. Concatenate — originals first, model last (preserves override semantics)
5.7. Resolve module-qualified imports — namespace synthesis
6. Validate final — `compile()` check on assembled result

**Three assembly modes:**
- `compat` — line-based stripping only (old behavior, for regression testing)
- `safe` — AST-based rewriting + qualified import resolution (default)
- `full` — reserved for future

**Key components:**

| Function | Purpose | Lines |
|---|---|---|
| `CodeAssembler.assemble()` | Main entry point | 32 |
| `CodeAssembler._assemble_multi_file()` | Full pipeline for multi-file cases | 151 |
| `_rewrite_imports_safe()` | AST-based import rewriting (aliases, star, relative) | 134 |
| `_resolve_qualified_imports()` | Namespace synthesis for `import X; X.func()` | 137 |
| `_build_export_table()` | Per-module export analysis | 27 |
| `_detect_dynamic_access()` | getattr/__dict__ detection | 18 |
| `_detect_shadowing()` | Module name reassignment detection | 11 |
| `_normalize_content()` | Markdown fence + escaped newline handling | 33 |
| `_strip_imports_compat()` | Legacy line-based stripping (compat mode) | 22 |

**`AssemblyResult` dataclass:**
```
code, status, files_used, rewrites_applied, warnings, errors,
assembly_used, assembly_risky, rename_error, expected_func, duplicate_defs, sources,
qualified_imports_resolved, qualified_imports_failed, qualified_import_warnings
```

### New file: `tests/test_code_assembly.py` (36 tests)

| Test Class | Tests | Covers |
|---|---|---|
| TestSingleFile | 2 | Passthrough, local import stripping |
| TestMultiFileBasic | 4 | Override ordering, duplicates, unchanged, rename detection |
| TestAliasRewriting | 3 | `from X import Y as Z`, ambiguous alias, multiple aliases |
| TestModuleQualified | 3 | `import X; X.func()` resolved, bare import removed, aliased module resolved |
| TestStarAndRelative | 3 | Star imports, relative imports, stdlib preservation |
| TestSyntaxErrors | 2 | Model syntax error, original syntax error |
| TestNormalization | 2 | Markdown fences, escaped newlines |
| TestCompatMode | 3 | Compat strips, preserves stdlib, does NOT rename (old bug) |
| TestCollisions | 2 | Model override allowed, provenance tracked |
| TestIdempotency | 1 | Double assembly = same result |
| TestDeterminism | 1 | Same input → same output |
| TestQualifiedImports | 10 | Resolution, alias, constant, missing symbol, dynamic, collision, shadowing, stdlib, regression, execution |

### New file: `tests/test_assembly_invariant.py` (8 enforcement tests)

Scans the entire repo to prevent regression:
- No forked `strip_local_imports` definitions
- No hardcoded `_STDLIB` sets
- No imports of stripping functions from parse.py
- No internal assembly transformer usage outside code_assembly.py
- validate_cases_v2.py load_module requires case (no bypass)
- scripts use canonical assembly
- _assemble_program is thin wrapper
- load_module_from_code has no transformation

---

## 3. Bugs Fixed

### BUG 1: Aliased imports stripped without renaming references
**Before:** `from metrics import reset as metrics_reset` → import removed, `metrics_reset()` → NameError
**After:** Import removed, AST renames all `metrics_reset` → `reset` in code body
**Affected:** 38 occurrences in model code (16 unique patterns)

### BUG 2: Module-qualified imports fail at runtime
**Before:** `import metrics; metrics.reset()` → import removed by safe mode, `metrics` undefined → ModuleNotFoundError
**After:** Import removed, `SimpleNamespace` synthesized at end of code: `metrics = SimpleNamespace(reset=reset, increment=increment, ...)`
**Affected:** 136 occurrences in model code

### BUG 3: Double stripping in load_module_from_code
**Before:** `_assemble_program` strips imports, then `load_module_from_code` strips again
**After:** Assembly happens once in CodeAssembler. `load_module_from_code` receives final code, does NOT transform.

### BUG 4: Forked stdlib sets with missing modules
**Before:** `preflight_check.py` had hardcoded 21-module set, missing `time`, `tempfile`, `threading`, `importlib`
**After:** All code uses canonical 25-module `STDLIB_MODULES` from `_stdlib.py` via CodeAssembler

### BUG 5: Forked stripping logic in test file
**Before:** `test_eval_integration.py` had its own `_strip_local_imports` with its own `_STDLIB` — tests validated against a different transformation than runtime
**After:** Tests use `assemble_code()` through the canonical path

---

## 4. What Was Deleted

| Deleted | Location | Reason |
|---|---|---|
| `strip_local_imports()` | `parse.py` | Replaced by CodeAssembler |
| `classify_import()` | `parse.py` | Internal to deleted function |
| `STDLIB_MODULES` import | `parse.py` | No longer needed |
| `_strip_local_imports()` | `validate_cases_v2.py` | Replaced by `assemble_code()` |
| `_strip_local_imports()` | `preflight_check.py` | Replaced by `assemble_code()` |
| `_STDLIB` hardcoded set | `preflight_check.py` | Uses canonical via CodeAssembler |
| `_strip_local_imports()` | `tests/test_eval_integration.py` | Replaced by `assemble_code()` |
| `_STDLIB` hardcoded set | `tests/test_eval_integration.py` | Uses canonical via CodeAssembler |
| `_strip_local_imports` import | `exec_eval.py` | Uses CodeAssembler |
| `_STDLIB_MODULES` import | `exec_eval.py` | No longer needed |
| `assembly/imports.py` | Entire file | Intermediate abstraction, deleted |
| Inline assembly logic | `exec_eval.py:_assemble_program` | Replaced by CodeAssembler delegation |
| Double strip call | `exec_eval.py:load_module_from_code` | Removed — receives pre-assembled code |

---

## 5. What Was Modified

| File | Change |
|---|---|
| `exec_eval.py` | `_assemble_program` → thin wrapper around CodeAssembler. `load_module_from_code` → no transformation. All `asm[...]` → `asm.attr`. |
| `validate_cases_v2.py` | `load_module(case)` required. Uses `assemble_code()`. |
| `preflight_check.py` | Uses `assemble_code()`. No own stdlib or stripping. |
| `scripts/test_invariant.py` | Uses `assemble_code()` + `load_module_from_code()`. No raw exec. |
| `tests/test_eval_integration.py` | Uses `assemble_code()`. No own stripping. |
| `tests/test_assembly.py` | Removed `_strip_local_imports` import. Uses `_assemble_program` which delegates to CodeAssembler. |
| `tests/test_parse.py` | Uses `assemble()` instead of deleted `_strip_local_imports`. |
| `tests/test_invariants.py` | Uses `assemble_code()` instead of deleted `_strip_local_imports`. |
| `tests/test_failure_suite.py` | Uses `assemble_code()` instead of deleted `strip_local_imports`. |
| `tests/test_correctness_fixes.py` | Rewritten to test via `assemble_code()` with synthetic cases. |

---

## 6. Architecture After Changes

```
runner.py
  → execution.py:evaluate_case()
    → parse_model_response()                    [parse.py — parsing only, no assembly]
    → _do_reconstruction()                      [reconstructor.py — file mapping only]
    → evaluate_output()
      → exec_evaluate()                         [exec_eval.py]
        → _assemble_program()                   [thin wrapper]
          → CodeAssembler().assemble()          [code_assembly.py — THE ONE PATH]
            Step 1: resolve files
            Step 2: normalize content
            Step 3: syntax check per-file
            Step 4: rewrite imports (AST-based)
              - from X import Y: delete
              - from X import Y as Z: delete + rename Z→Y
              - from X import *: delete
              - import X (no attr): delete
              - import X (with X.attr): leave for step 5.7
              - relative: delete
              - stdlib: preserve
            Step 5: concatenate (originals first, model last)
            Step 5.5: duplicate + rename detection
            Step 5.7: resolve qualified imports
              - build export table from originals
              - verify all X.attr exist in exports
              - check for collisions, dynamic access, shadowing
              - remove import X
              - synthesize SimpleNamespace at end
            Step 6: compile() validation
          → returns AssemblyResult
        → load_module_from_code(asm.code)       [NO transformation — pure compile+exec]
        → run test function
```

**Invariant:** Every code path that reaches `exec()` has been processed by `CodeAssembler.assemble()`. No exceptions. Enforced by 8 repo-scanning tests.

---

## 7. Known Limitations

1. **Dynamic access (`getattr(X, ...)`) blocks resolution.** The import is kept, which causes ModuleNotFoundError at runtime. This is correct behavior — we surface the error rather than silently corrupting bindings. Affects ~0 cases in practice (no model code uses getattr on local modules).

2. **Cross-module symbol collision causes REWRITE_ERROR.** If `metrics.reset()` and `audit.reset()` are both used and both modules define `reset`, assembly fails. The model would need to use `from X import` syntax instead. Rare in practice.

3. **ast.unparse reformats code.** The AST round-trip changes whitespace and comments. The executed code looks different from the model's output. This could complicate debugging.

4. **Compat mode preserves the old alias bug.** By design — compat mode exists for regression testing. The default is safe mode.

---

## 8. Metric Impact

| Metric | Before | After |
|---|---|---|
| Assembly-caused failures | 47/2498 (1.88%) | 0 (for alias/qualified patterns) |
| gpt-5-mini false failures | 38/580 (6.6%) | ~0 |
| Forked stdlib sets | 2 (missing 4 modules) | 0 |
| Independent stripping implementations | 5 | 1 |
| Assembly code paths | 5+ | 1 |
| Tests enforcing invariant | 0 | 8 |
| Total assembly tests | ~24 | 44 (36 unit + 8 invariant) |

---

## 9. Verification

- **133 tests passing** (36 assembly + 8 invariant + 24 integration + 51 reasoning + 7 parse + 7 correctness)
- **End-to-end verified:** `import metrics; metrics.increment(); metrics.emit_event()` on real case `effect_order_b` — passes
- **Repo-wide grep confirms:** zero forked implementations, zero bypass paths, zero hardcoded stdlib sets
- **Enforcement tests prevent regression:** any reintroduction of alternate paths will fail CI
