# Assembly Path Self-Audit

**Date:** 2026-03-30
**Auditor:** Adversarial self-review

---

## 1. Verdict

**FAIL — 3 confirmed alternate paths remain, 2 unresolved semantic risks.**

---

## 2. Canonical Runtime Path

```
runner.py:run_single/run_leg_reduction
  → execution.py:evaluate_case(case, raw_output)
    → parse_model_response(raw_output)           [parse.py]
    → _build_parsed_response(parse_result)        [execution.py]
    → _do_reconstruction(case, parsed)            [execution.py → reconstructor.py]
    → evaluate_output(case, parsed)               [evaluator.py]
      → exec_evaluate(case, code)                 [exec_eval.py]
        → _assemble_program(code, case)           [exec_eval.py → CodeAssembler]
          → CodeAssembler().assemble(code, case)  [code_assembly.py]
            → _normalize_content()
            → _rewrite_imports_safe() or _strip_imports_compat()
            → concatenate originals + model
            → compile() validation
          → returns AssemblyResult
        → load_module_from_code(asm.code)         [exec_eval.py — NO transformation]
        → exec(compile(code))
        → run test function
```

Import transformation occurs at exactly ONE point: inside `CodeAssembler._process_imports()`.

---

## 3. Non-Runtime Paths

### A. Preflight (`preflight_check.py`)
```
preflight_check.py:check_case()
  → _load_buggy_code(case)
    → assemble_code(concat, case)              ← USES CANONICAL PATH ✓
    → returns asm.code
  → load_module_from_code(code)                ← exec_eval.py, no transformation ✓
  → reference code:
    → assemble_code(ref_code, case)            ← USES CANONICAL PATH ✓
    → load_module_from_code(full_ref)
```
**Status: CLEAN** — routes through CodeAssembler.

### B. Validation (`validate_cases_v2.py`)
```
validate_cases_v2.py:check_loads()
  → load_case_code(case)                       ← raw concat, NO assembly
  → load_module(code, case=case)
    → assemble_code(code, case)                ← USES CANONICAL PATH ✓
    → exec(compile(cleaned))
```
**Status: CLEAN** — routes through CodeAssembler when `case` is provided.

**BUT: `load_module` has a fallback:**
```python
if case is not None:
    asm = assemble_code(code, case)
    cleaned = asm.code
else:
    cleaned = code  # already assembled ← BYPASS PATH
```
If anyone calls `load_module(code)` without `case`, code is exec'd raw — no assembly, no import stripping. Currently all call sites pass `case=case`, but the fallback exists.

### C. Test-only: `test_eval_integration.py` — **VIOLATION**
```
test_eval_integration.py
  → _strip_local_imports(code)                 ← OWN IMPLEMENTATION, NOT CANONICAL
  → load_module_from_code(stripped_code)
```
**Status: CONFIRMED VIOLATION.** This file has its own `_strip_local_imports` with its own `_STDLIB` set. It does NOT use CodeAssembler. It is an independent forked implementation used in 5+ test functions.

### D. Test-only: `test_execution_runs.py` — **VIOLATION**
```
test_execution_runs.py
  → load_module_from_code(code)                ← code passed raw, no assembly
```
**Status: ALTERNATE PATH.** Tests call `load_module_from_code` directly with raw code that has not been assembled. Since `load_module_from_code` no longer strips imports, this is correct only if the code has no local imports. But it's a path that bypasses assembly.

### E. Test-only: `test_oracle_correctness.py`
```
test_oracle_correctness.py
  → _assemble_program(code, case)              ← thin wrapper → CodeAssembler ✓
  → load_module_from_code(asm.code)            ← post-assembly ✓
```
**Status: CLEAN.**

### F. `scripts/test_invariant.py` — **VIOLATION**
```
scripts/test_invariant.py
  → exec(code, mod.__dict__)                   ← raw exec, no assembly at all
```
**Status: CONFIRMED VIOLATION.** This script execs code directly without any import stripping or assembly. If the code has local imports, they will fail with ImportError.

### G. `graph_runner/executors/exec_eval.py`
```
graph_runner/executors/exec_eval.py
  → exec(code, exec_globals)                   ← separate execution system
```
**Status: SEPARATE SYSTEM.** This is the graph_runner's own execution path. It does not use CodeAssembler. It may or may not need assembly — depends on whether it handles multi-file cases.

### H. Single-file path
```
CodeAssembler.assemble()
  → if len(code_contents) <= 1:
    → _process_imports(model_code, local_modules, set())
    → return AssemblyResult(assembly_used=False)
```
**Status: USES CANONICAL PATH** but with empty `all_names` set. The import rewriting still runs, but `all_names` is empty, which means AST name resolution has no namespace context. For single-file cases this is correct since there are no other files to resolve against.

---

## 4. Findings Table

| File | Function | Role | Transforms code? | Canonical? | Risk | Notes |
|---|---|---|---|---|---|---|
| `code_assembly.py` | `CodeAssembler.assemble()` | Canonical assembly | Y | CANONICAL | — | The one path |
| `code_assembly.py` | `_rewrite_imports_safe()` | AST import rewriting | Y | INTERNAL | — | Called only by CodeAssembler |
| `code_assembly.py` | `_strip_imports_compat()` | Compat stripping | Y | INTERNAL | — | Called only by CodeAssembler in compat mode |
| `code_assembly.py` | `_normalize_content()` | Content normalization | Y | INTERNAL | — | Markdown fences, escaped newlines |
| `code_assembly.py` | `assemble_code()` | Convenience wrapper | N (delegates) | PASS-THROUGH | LOW | Pure delegation to CodeAssembler |
| `code_assembly.py` | `assemble_original()` | Convenience wrapper | N (delegates) | PASS-THROUGH | LOW | Concatenates then delegates |
| `exec_eval.py` | `_assemble_program()` | Thin wrapper | N (delegates) | PASS-THROUGH | — | Delegates to CodeAssembler + logging |
| `exec_eval.py` | `load_module_from_code()` | Module loading | N | — | — | compile + exec only, no transformation |
| `validate_cases_v2.py` | `load_module()` | Validation loader | CONDITIONAL | CONDITIONAL | **MEDIUM** | Has `case=None` bypass path |
| `preflight_check.py` | `_load_buggy_code()` | Preflight loader | N (delegates) | CLEAN | — | Uses `assemble_code()` |
| `reconstructor.py` | `_normalize_file_content()` | Content normalization | Y | SEPARATE | **LOW** | Normalizes BEFORE assembly, not import-related |
| **`tests/test_eval_integration.py`** | **`_strip_local_imports()`** | **Forked stripping** | **Y** | **ALTERNATE** | **HIGH** | **Own implementation, own _STDLIB, NOT canonical** |
| **`scripts/test_invariant.py`** | **`exec(code)`** | **Raw exec** | **N** | **BYPASS** | **MEDIUM** | **No assembly at all** |
| `graph_runner/executors/exec_eval.py` | `exec(code)` | Graph runner exec | N | SEPARATE SYSTEM | LOW | Different execution system entirely |

---

## 5. Confirmed Violations

### VIOLATION 1: `tests/test_eval_integration.py:_strip_local_imports`
- **What:** Complete forked implementation of import stripping (lines 57-65)
- **Own _STDLIB set** (lines 32-50) — may diverge from canonical `_stdlib.py`
- **Used by:** `_load_buggy_code()`, `_load_reference_code()`, and 5+ test functions
- **Impact:** Tests validate behavior using a DIFFERENT stripping implementation than runtime. If canonical stripping changes, these tests won't catch the regression.
- **Fix:** Replace with `assemble_code()` calls, same as was done for other test files.

### VIOLATION 2: `validate_cases_v2.py:load_module(case=None)` bypass
- **What:** If `case` is not passed, code is exec'd without assembly
- **Currently safe:** All call sites pass `case=case`
- **Risk:** Future callers could omit `case` and bypass assembly silently
- **Fix:** Remove the `case=None` fallback. Make `case` required.

### VIOLATION 3: `scripts/test_invariant.py` raw exec
- **What:** Line 45: `exec(code, mod.__dict__)` — no assembly, no import stripping
- **Purpose:** CLI tool for manual testing against invariant functions
- **Impact:** Low for benchmark integrity (not part of evaluation pipeline), but violates the single-path invariant
- **Fix:** Route through `assemble_code()` before exec.

---

## 6. Unresolved Semantic Risks

### RISK 1: Module-qualified local imports (`import metrics; metrics.reset()`)
- **Current behavior:** In safe mode, `import metrics` is KEPT when `metrics.func()` usage is detected. Warning emitted.
- **At runtime:** The kept `import metrics` will fail with `ModuleNotFoundError` because `metrics` is not a real module in the concatenated namespace.
- **Impact:** 136 occurrences of this pattern in model code. These cases will fail at load time with an assembly error, same as before. The safe mode choice to keep them is correct (better to fail explicitly than silently corrupt names), but the failure is still an infrastructure limitation.
- **Status:** Known limitation, not a bug. Full mode (rewriting `metrics.func()` → `func()`) would fix it but requires scope analysis.

### RISK 2: Duplicate normalization
- `reconstructor.py:_normalize_file_content()` normalizes markdown fences and escaped newlines during reconstruction.
- `code_assembly.py:_normalize_content()` normalizes the same things during assembly.
- If both run on the same content (reconstruction produces normalized files → assembly normalizes again), the double normalization is idempotent for fences/newlines but the existence of two normalizers is a latent divergence risk.
- **Status:** Not currently a bug. Both normalizers handle the same patterns. But if one is updated without the other, behavior could diverge.

---

## 7. Test Coverage Gaps

1. **No test verifies `test_eval_integration.py` uses canonical path** — it doesn't, and no test catches that.
2. **No test prevents `load_module(case=None)` bypass** — the fallback exists and is untested.
3. **No test for `scripts/test_invariant.py` assembly correctness** — it's a CLI tool with no test coverage.
4. **No test for double normalization idempotency** — reconstructor + assembler both normalize, no test verifies they produce identical results.
5. **No test prevents reintroduction of `strip_local_imports` in parse.py** — the function was deleted but no guard prevents someone adding it back.

---

## 8. Final Judgment

**The invariant is NOT fully enforced.**

The canonical runtime path is clean — `CodeAssembler` is the single assembly point for all production evaluation. Preflight and validation were correctly migrated.

But `test_eval_integration.py` is a confirmed violation with its own forked stripping logic. This means test results from that file are validated against a different transformation than runtime uses. If the canonical assembler changes behavior (e.g., handles aliases differently), those tests won't detect the change.

**Trust level: HIGH for production metrics, MEDIUM for test coverage.**

**Next fix:** Replace `test_eval_integration.py:_strip_local_imports` with `assemble_code()` calls — same surgical fix applied to the other test files. Then make `validate_cases_v2.py:load_module(case)` required (no None fallback).
