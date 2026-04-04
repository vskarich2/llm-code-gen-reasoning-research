# Module Execution Audit: Can module_exec Replace CodeAssembler?

## 1. Executive Verdict

**module_exec is NOT ready to be canonical.** It correctly solves the alias-recursion
bug (the delegation pattern works with real modules), but it has its own critical
failure: when model code replaces a module AND imports from that same module
(e.g., model replaces `config.py` but writes `from config import DEFAULTS`), the
module system creates a circular self-import. The concat path handles this because
all symbols are already in the flat namespace.

Neither system is sound. The concat path destroys module boundaries (causing
recursion on delegation patterns). The module path preserves module boundaries
but breaks on self-referential imports (a common pattern where the model imports
constants from the module it's fixing).

**Both systems are wrong, in complementary ways.**

---

## 2. Hot Path Reconstruction

The canonical evaluation path for all v2 conditions:

```
runner.py:_run_one_inner()
  → execution_v2.py:run_v2()
    → reconstructor.py:reconstruct_strict()          [extract per-file code]
    → join changed files with "\n\n"                  [flatten to single string]
    → exec_eval.py:exec_evaluate(case, code)
      → code_assembly.py:CodeAssembler().assemble()   [import rewrite + concat]
        → _rewrite_imports_safe()                      [alias rename, THE BUG]
        → concatenate originals + model                [namespace flattening]
      → load_module_from_code(assembled_code)          [exec in single namespace]
      → test_fn(mod)                                   [run invariant test]
```

**module_exec.py is NEVER called on this path.** It exists only in:
- `evaluator.py:233` (v1 dual-execution side-channel, results discarded)
- `tests/test_dual_execution.py` (unit tests)
- `tests/stress/test_isolation_stress.py` (stress tests)
- `tests/stress/test_import_stress.py` (stress tests)

---

## 3. Contract Comparison

### Input contract

| Property | exec_evaluate (concat) | module_exec |
|---|---|---|
| Receives | `(case: dict, code: str)` | `(case: dict, model_code: str, test_fn)` |
| Code format | Single concatenated string | Single concatenated string |
| Case requirements | code_files, code_files_contents, failure_mode | code_files, code_files_contents, reference_fix |
| Test function | Resolved internally (_CASE_TESTS or _load_v2_test) | Passed as argument |

**DIFFERENT (breaking):** module_exec requires the caller to resolve the test
function. exec_evaluate resolves it internally. Any replacement would need to
either internalize test resolution or require all callers to pass it.

### Output contract

| Property | exec_evaluate | module_exec |
|---|---|---|
| Returns | `dict` with pass, score, reasons, execution, etc. | `ModuleExecResult` dataclass |
| Pass signal | `result["pass"]` (bool) | `result.test_passed` (bool) |
| Score | 0.0 / 0.1 / 0.2 / 0.5 / 1.0 | Not computed |
| Failure reasons | `result["reasons"]` (list) | `result.test_reasons` (list) |
| Assembly metadata | Full provenance (assembly_used, risky, sources, etc.) | load_passes only |
| Error tracking | syntax_error, runtime_error, assembly_error | error_type, error_message, error_traceback |

**DIFFERENT (breaking):** The return structures are completely different. Every
downstream consumer (execution_v2.py, evaluator_v2.py, metrics_v2.py, logging,
dashboard) expects the exec_evaluate dict format. module_exec returns a dataclass
with different field names and no score computation.

---

## 4. Behavioral Comparison

### Side-by-side on real cases

| Test | Files | Concat | Module | Match | Notes |
|---|---|---|---|---|---|
| effect_order_b (delegation) | 2 | **FAIL** | **PASS** | DIFFER | Concat: recursion. Module: correct. |
| effect_order_b (inline) | 2 | PASS | PASS | MATCH | Both handle inline pattern. |
| alias_config_b | 2 | PASS | **FAIL** | DIFFER | Module: self-import circular. Concat: flat namespace has DEFAULTS. |

### Category-level comparison

| Category | Assessment | Details |
|---|---|---|
| Execution semantics | **DIFFERENT (breaking)** | Concat: single namespace. Module: per-file namespace. Different behavior on alias imports AND self-imports. |
| Import resolution | **DIFFERENT (breaking)** | Concat: AST rewrite + rename. Module: real Python imports via sys.modules. Different failure modes. |
| Namespace behavior | **DIFFERENT (breaking)** | Concat: all symbols in one dict. Module: symbols in separate module dicts + merged view for test. |
| Exception handling | Different (harmless) | Concat: catches SyntaxError/NameError/ImportError separately. Module: generic Exception with type tracking. |
| Return structure | **DIFFERENT (breaking)** | Completely different return types. No score in module_exec. |
| Logging compatibility | **DIFFERENT (breaking)** | exec_evaluate returns assembly metadata consumed by logging. module_exec has none. |
| Retry compatibility | Identical | Both receive same code string. |
| Evaluator expectations | **DIFFERENT (breaking)** | Downstream expects exec_evaluate dict format. |
| Performance | Different (harmless) | Module: 2-pass loading (~2x exec time). Concat: single exec. |

---

## 5. Failure Modes of module_exec

### Confirmed failures

1. **Self-referential import**: Model replaces `config.py` but writes
   `from config import DEFAULTS`. The module imports from itself. On first
   pass, `DEFAULTS` is not yet defined. On second pass, it may or may not
   resolve depending on execution order. **Confirmed on `alias_config_b`.**

2. **Override detection fragility**: module_exec determines which module to
   replace using `reference_fix.file` or function-name matching. If neither
   works (model defines functions not in reference_fix), it falls back to
   appending to the last module — incorrect behavior.

### Not confirmed but plausible

3. **Module-level side effects**: If original `config.py` has `_cache = load_data()`
   at module level, and model replaces it, the side effect runs with the model's
   code, not the original. In concat, it runs in the order of concatenation
   (originals first, model last).

4. **sys.modules pollution**: module_exec registers modules in `sys.modules`.
   The cleanup in the `finally` block should handle this, but concurrent test
   execution could conflict.

### Handled correctly

5. **Circular imports**: The 2-pass loading handles mutual imports between modules.
   Confirmed working in `test_dual_execution.py::test_two_pass_handles_circular`.

6. **Alias imports**: `from metrics import reset as metrics_reset` works correctly
   with real modules. No alias rewriting needed. Confirmed working.

7. **State isolation**: `sys.modules` cleanup verified in stress tests.

---

## 6. Why module_exec Was Never Wired In

### Evidence

1. **Commit message**: `"Milestone commit."` — no description of intent, no migration
   plan documented.

2. **Docstring**: `"This is a SIDE-CHANNEL execution system. It does NOT affect
   canonical results."` — explicitly designed as comparison, not replacement.

3. **Return type mismatch**: `ModuleExecResult` has no `score` field, no assembly
   metadata, no `execution` sub-dict. Wiring it in would require rewriting every
   downstream consumer.

4. **Self-import bug**: The `alias_config_b` failure demonstrates that module_exec
   can't handle the common pattern where model code imports from the module it's
   replacing. This was likely discovered during development and the module path
   was parked as a comparison tool rather than fixed.

5. **Override detection**: The heuristic for determining which module the model
   replaces is fragile. The concat path doesn't need this — it just appends
   model code last and relies on Python's last-definition-wins.

### Verdict

This was not neglect. It was an **incomplete migration** that hit real technical
blockers (self-import, override detection, return format) and was parked as a
side-channel rather than completed.

---

## 7. Test Coverage Gap

### What test_dual_execution.py tests

- Basic single-file execution: PASS
- Syntax error handling: PASS
- Multi-file basic imports: PASS
- Alias imports (`from X import Y as Z`): PASS
- Module-qualified imports (`import X; X.func()`): PASS
- Circular imports (2-pass): PASS
- Comparison logic (agreement/disagreement): PASS
- State isolation (sys.modules cleanup): PASS

### What it does NOT test

- **Self-referential imports**: Model code that imports from the module it replaces.
  This is the exact pattern that breaks module_exec on `alias_config_b`.
- **Override detection edge cases**: Model code that doesn't define the expected
  function. Fallback to "last module" is never tested.
- **Semantic equivalence with concat path**: No test runs the SAME code through
  both paths and compares results.
- **Real benchmark cases**: All tests use synthetic 2-3 line modules, not actual
  benchmark code.

### Why the alias-recursion bug wasn't caught

The concat path's recursion bug requires three conditions:
1. Multi-file case
2. Model writes `from X import Y as Z` (aliased import)
3. Model also defines function `Y` (name collision after rename)

No test combines all three. `test_from_import_as_rewritten` tests the alias
rename but not the collision. `test_duplicate_defs_detected` tests collisions
but not via rename. The intersection is untested.

---

## 8. Migration Risk Assessment

### If we replace CodeAssembler with module_exec

| Risk | Level | Description |
|---|---|---|
| Self-import breakage | **HIGH** | Any model code that does `from X import Y` where X is the module being replaced will fail. This is a COMMON pattern (model imports constants from the file it's fixing). Estimated: 30-50% of multi-file cases affected. |
| Return format incompatibility | **HIGH** | Every downstream consumer (execution_v2, evaluator_v2, metrics_v2, logging, dashboard) expects exec_evaluate's dict format. Requires adapter or rewrite. |
| Override detection failures | **MEDIUM** | When reference_fix metadata is missing or wrong, module_exec may replace the wrong module or append to the wrong file. |
| Score computation missing | **MEDIUM** | module_exec doesn't compute the 0.0/0.1/0.2/0.5/1.0 score ladder. Would need to be added. |
| Performance regression | **LOW** | 2-pass loading is ~2x slower per case. Negligible at benchmark scale. |
| Reproducibility break | **LOW** | Different execution path = different pass/fail on some cases. Would need to re-baseline all results. |

---

## 9. Final Verdict

**module_exec is NOT ready to be canonical.** It solves the alias-recursion bug
but introduces the self-import bug, which affects more cases than the recursion
bug does.

The correct fix is a **hybrid approach**:

1. Keep module_exec's per-module namespace isolation (fixes recursion)
2. Before loading a module that imports from itself, inject the original module's
   symbols into its namespace (fixes self-import)
3. Add the score computation and return format from exec_evaluate
4. Add proper override detection that handles edge cases

This is essentially: module_exec + a pre-seeding step where original module
contents are loaded first, then the model's replacement is loaded into the
same namespace (allowing self-imports to resolve from the original).

---

## 10. Required Next Steps (No Code)

### Before any switch

1. **Build self-import test set**: Identify every multi-file case where the
   reference fix imports from the file being fixed. Count them.

2. **Run module_exec on ALL 58 cases with reference fixes**: Compare against
   concat path. Count disagreements. Classify each as improvement/regression/neutral.

3. **Design the pre-seeding mechanism**: Determine how to inject original module
   symbols before model code loads, so self-imports resolve.

4. **Write the missing tests**:
   - Alias import + local redefinition → assert no recursion
   - Self-referential import → assert resolves correctly
   - Override detection edge cases → assert correct module replaced
   - Semantic equivalence: same code through both paths → same result

5. **Build the return format adapter**: module_exec result → exec_evaluate dict
   format, including score computation.

6. **Re-run contaminated cases**: The 9 affected cases through the fixed path.
   Compare against contaminated data to quantify measurement error.

### Do NOT

- Do NOT switch canonical path without completing steps 1-4
- Do NOT delete CodeAssembler until module_exec handles all its cases
- Do NOT assume module_exec is correct because it handles the recursion case
