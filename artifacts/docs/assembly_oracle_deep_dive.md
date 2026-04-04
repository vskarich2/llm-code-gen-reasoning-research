# Assembly & Oracle Deep Dive

**Date:** 2026-03-28
**Scope:** exec_eval.py assembly pipeline, import stripping, test execution, metadata integrity
**Verdict:** The assembly system is FUNCTIONALLY CORRECT for 38/39 multi-file cases. 1 confirmed metadata bug (mutable_default_b). The duplicate-definition pattern is BY DESIGN and works because Python's last-definition-wins semantics are deterministic. However, there are structural risks that could produce wrong results under specific model output patterns.

---

## How Assembly Works

For multi-file cases (39 of 58), `_assemble_program()` (exec_eval.py:700) does:

1. **Collect originals:** Concatenate all case files in `code_files` order
2. **Strip imports:** Remove cross-file imports via `strip_local_imports()` (parse.py:657)
3. **Collect model code:** Strip its imports too
4. **Concatenate:** `original_cleaned + "\n\n" + model_cleaned`
5. **Detect duplicates:** Regex for `def X` / `class X` in both halves
6. **Detect rename:** Check if `reference_fix.function` exists in originals but not in model defs
7. **Return assembled code** for `exec()` into a single module

The result: every function is defined at least twice — once from originals, once from model code. Python's last-definition-wins means the model's versions override the originals.

---

## Confirmed Bugs

### Bug 1: mutable_default_b metadata mismatch (CONFIRMED)

- `reference_fix.function = "enqueue"` but the reference fix file defines `process_batch` and `summarize`
- `enqueue` is in `queue.py` (original), not `worker.py` (where the fix is)
- The rename check fires: `enqueue` in original_defs, not in model_defs → `rename_error=True`
- Reference fix FAILS evaluation with `ran=False, score=0.0`
- **Impact:** Any model that correctly fixes `process_batch` (the real bug) but doesn't redefine `enqueue` will get a false FAIL
- **In production ablation data:** This case had 12% baseline pass rate — the rename error was firing on most correct fixes

### Bug 2: mutable_default_c triple decoration (CONFIRMED RISK)

The assembled code has `with_history` defined 3 times and `@with_history` applied 3 times to `schedule_one`/`schedule_batch`. Python executes all 3 decoration sequences at module load time. The LAST one wins (the model's correct version), but the first two create intermediate state (bound decorator closures) that consume memory and could interact with mutable module-level state.

Currently the tests pass because the last definition is correct and the intermediate decorations are garbage-collected. But if a model's code introduces shared state, the intermediate decorations could interfere.

**Impact:** Low (current tests pass), but architecturally fragile.

---

## No Other Metadata Bugs Found

Checked all 39 multi-file cases. Only `mutable_default_b` triggers `rename_error` with the reference fix. All other reference fixes correctly pass `exec_evaluate()`.

The 10 cases with `reference_fix.function` misalignment identified in the system audit are NOT bugs for the evaluator — they're metadata quality issues. The rename check ONLY fires when:
- `reference_fix.function` IS in `original_defs` (the function exists in the buggy code)
- AND it's NOT in `model_defs` (the model didn't redefine it)

For 8 of the 10 misaligned cases, the metadata function IS in the originals but the reference fix ALSO redefines it (or it's a single-file case where rename check is skipped). Only `mutable_default_b` actually triggers the false failure.

---

## Import Stripping Analysis

`strip_local_imports()` (parse.py:657) removes:
- Relative imports (`from . import`, `import .`)
- Single-line imports of non-stdlib modules (`from config import X` → stripped if `config` not in STDLIB_MODULES)
- Multi-line imports via regex

**What it preserves:**
- All stdlib imports (os, sys, re, json, etc. — 35 modules in `_stdlib.py`)
- Imports with dots (`from pathlib.something import X` — preserved because `"." in mod`)

**Potential issue:** If a model's code imports a stdlib module that's NOT in the STDLIB_MODULES list (e.g., `uuid`, `decimal`, `struct`), the import gets stripped and the code will fail with `NameError`. Current list has 35 modules — Python stdlib has ~200+.

**Checked:** No current test case uses a stdlib module outside the list. But a model COULD import one, and it would be silently stripped.

---

## Duplicate Definition Behavior

All 38 passing multi-file cases have duplicate function definitions. This is BY DESIGN:
- Original `def create_config()` at line 30 (buggy)
- Model `def create_config()` at line 90 (fixed)
- Python uses the last definition → model's version runs

**This works correctly** because:
1. Function definitions are pure declarations — they don't execute side effects
2. Module-level variable initializations (`_db = {}`, `_cache = {}`) that appear twice are idempotent (resetting to empty dict)
3. No case has module-level function CALLS between the original and model sections (except `mutable_default_c` with decorators)

**Risk:** If a model produces code with module-level function calls (e.g., `register("handler", my_func)`), those calls would execute with the ORIGINAL function definitions (before the model's overrides are loaded). The model's overrides would then replace the functions, but the registration would point to the old versions.

**Current impact:** None — no test case exhibits this pattern. But it's an architectural weakness.

---

## Module-Level State Double-Init

| Statement | Cases affected | Impact |
|-----------|---------------|--------|
| `_db = {}` | stale_cache_b/c, cache_invalidation_order | Safe — resets to same empty state |
| `_cache = {}` | stale_cache_b/c | Safe — resets to same empty state |
| `_store = {}` | stale_cache_b, hidden_dep_multihop | Safe — same |
| `_counter = 0` | effect_order_b/c | Safe — resets to same value |
| `_snapshots = []` | effect_order_b/c | Safe — resets to same value |
| `_ledger = []` | early_return_b/c | Safe — resets to same value |
| `_sent = []` | retry_dup_b/c | Safe — resets to same value |
| `DEFAULTS = {...}` | alias_config_b/c, config_shadowing | **DEPENDS** — if model changes DEFAULTS value, the second init overwrites with model's version (correct) |
| `@with_history` | mutable_default_c | **RISKY** — decorator executes 3 times (see Bug 2) |

All double-inits are currently safe because they reset to the same values. The model's section is always LAST, so its values win.

---

## Test Execution Path (verified)

After assembly and module loading, `exec_evaluate` does:

1. **Find test function:** `_CASE_TESTS.get(case_id)` or `_load_v2_test(case)` (never fails — preflight_verify_tests checked)
2. **Run invariant test:** `test_fn(mod)` → `(passed, reasons)` — the test operates on the loaded module
3. **Run mutation test:** `_run_mutation_tests(mod, case_id)` — runs the SAME test twice for idempotency
4. **Both must pass** for overall `pass=True`

The test function receives the module object (`mod`). It accesses functions via `getattr(mod, "create_config")`. Since the module was loaded from assembled code where the model's definitions are last, `getattr` returns the model's version.

**Verified:** All 38 passing multi-file cases produce `pass=True` with reference fixes. The assembly + test execution path is correct for these cases.

---

## Summary of Risks

| Risk | Severity | Likelihood | Cases affected |
|------|----------|-----------|----------------|
| mutable_default_b rename_error false FAIL | **HIGH** | CERTAIN (confirmed) | 1 case |
| Stdlib import stripping on model code | MEDIUM | Low (no case uses exotic stdlib) | All multi-file |
| Module-level call ordering with assembly | MEDIUM | Low (only mutable_default_c) | 1 case |
| mutable_default_c triple decoration | LOW | Low (tests pass currently) | 1 case |
| Model code with register/init calls | LOW | Theoretical (no case exhibits) | All multi-file |

---

## Recommended Fixes

1. **Fix mutable_default_b metadata:** Change `reference_fix.function` from `"enqueue"` to `"process_batch"` in cases_v2.json — this is the function the fix actually modifies
2. **Expand STDLIB_MODULES:** Add `uuid`, `decimal`, `struct`, `contextlib`, `weakref`, `operator`, `bisect`, `heapq`, `statistics` — common modules a model might import
3. **Add metadata validation to validate_cases_v2.py:** Check that `reference_fix.function` appears in the reference fix code's function definitions
