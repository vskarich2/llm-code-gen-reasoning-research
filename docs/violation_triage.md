# Violation Triage Report

**Date:** 2026-03-27
**Tools:** Ruff 0.15.8, Pyright 1.1.408, Semgrep, Import-linter, Vulture

---

## Summary

| Tool | Total | Actionable | Noise |
|------|-------|-----------|-------|
| **Ruff** | 1,766 | ~400 | ~1,366 (fixable auto, stylistic) |
| **Pyright** | 203 | ~50 | ~153 (missing generics in strict mode) |
| **Semgrep** | 9,624 | 54 ERROR + 52 WARNING | 9,518 INFO (noise rules) |
| **Vulture** | 19 | 19 | 0 |
| **Import-linter** | exit 1 | TBD (flat module limitation) | — |
| **TOTAL** | ~11,600 | ~575 | ~11,000 |

**95% of findings are noise** from overly broad semgrep INFO rules and strict pyright generics. The real issues are ~575 findings across 4 buckets.

---

## Bucket 1 — ARCHITECTURE-CRITICAL

### A1: Unused nudge/operator imports in execution.py (8 findings)

- **Files:** execution.py:17
- **Tool:** Vulture, Ruff F401
- **What:** `apply_diagnostic`, `apply_guardrail`, `apply_counterfactual`, `apply_reason_then_act`, `apply_self_check`, `apply_counterfactual_check`, `apply_test_driven`, `apply_guardrail_strict` imported but never called
- **Root cause:** The user's refactoring moved prompt building to `assembly_engine.py` or `prompt_registry.py`, but the old imports in `execution.py` were never cleaned up. These are remnants of the old nudge system.
- **Violated rule:** No dead imports on critical path
- **Priority:** HIGH — these imports mask the real dependency graph
- **Fix type:** QUICK FIX — delete 8 import lines

### A2: Legacy event emission code in execution.py (2 findings)

- **Files:** execution.py:266, execution.py:270
- **Tool:** Vulture
- **What:** `EVENTS_PATH` and `_legacy_emit` imported but unused
- **Root cause:** The legacy dashboard path was replaced by the process-based architecture. These imports are dead.
- **Priority:** HIGH
- **Fix type:** QUICK FIX — delete 2 import lines

### A3: `global` statement usage (38 findings, Semgrep ERROR)

- **Files:** call_logger.py (5), execution.py (3), live_metrics.py (1), and others
- **Tool:** Semgrep `no-global-state`
- **What:** `global _run_dir, _calls_dir, _flat_path, _call_counter, _enabled` etc.
- **Root cause:** The process-based architecture uses module-level globals for per-run state (ablation context, call logger state). This is intentional for process isolation but violates the no-global-state rule.
- **Assessment:** **MIXED.** Some are structural (ablation context — required by design). Some are legacy (e.g., legacy emit path). The semgrep rule is too broad — it should exclude known-intentional globals.
- **Priority:** MEDIUM — separate intentional from accidental globals
- **Fix type:** SYSTEMIC — need a whitelist approach or redesign state management

### A4: Dynamic imports inside functions (58 findings, Semgrep WARNING)

- **Files:** execution.py (12), evaluator.py (4), runner.py (8), retry_harness.py (6), and others
- **Tool:** Semgrep `no-dynamic-import`
- **What:** `from module import X` inside function bodies
- **Root cause:** Two distinct causes:
  1. **Circular import avoidance** (execution.py importing from evaluator, evaluator importing from experiment_config) — these are structural
  2. **Lazy loading for optional deps** (redis_metrics, scm_data) — these are intentional
- **Assessment:** The rule is correct but fires on both legitimate and problematic cases. Most dynamic imports here are avoiding circular deps — a sign of entangled modules.
- **Priority:** LOW (these work correctly; the root cause is circular dep architecture)
- **Fix type:** SYSTEMIC — would require module restructuring to eliminate circular deps

---

## Bucket 2 — INVARIANT-CRITICAL

### I1: Silent exception swallowing (15 findings, Semgrep ERROR)

- **Files:** execution.py (4), live_metrics.py (2), runner.py (2), retry_harness.py (3), and others
- **Tool:** Semgrep `no-silent-except-pass`, `no-swallowed-exception`
- **What:** `try: ... except Exception: pass` or `except: pass`
- **Root cause:** Fire-and-forget patterns in metrics emission, Redis, and legacy event paths. These were added intentionally to prevent metrics failures from crashing the pipeline, but they hide real errors.
- **Violated invariant:** "No silent failures"
- **Priority:** HIGH — these can mask pipeline bugs (the original 0% pass rate bug was partially hidden by silent exceptions)
- **Fix type:** QUICK FIX per instance — replace `pass` with `_log.debug(...)` or `_log.warning(...)`

### I2: Wildcard import (1 finding, Semgrep ERROR)

- **File:** Unknown (1 occurrence)
- **Tool:** Semgrep `no-wildcard-import`
- **What:** `from module import *`
- **Priority:** HIGH
- **Fix type:** QUICK FIX — replace with explicit imports

### I3: Broad exception without re-raise (52 findings, Semgrep WARNING)

- **Files:** execution.py (8), exec_eval.py (6), runner.py (4), evaluator.py (3), and others
- **Tool:** Semgrep `no-broad-except-without-reraise`
- **What:** `except Exception as e:` blocks that log but don't re-raise
- **Root cause:** Defensive coding to keep the pipeline running when individual cases fail. Correct for production resilience but violates fail-fast principle.
- **Assessment:** **SPLIT.** Per-case exception handling (so one failing case doesn't kill the run) is correct. But broad catches that suppress unknown errors are dangerous.
- **Priority:** MEDIUM — audit each: is it catching known failure modes or unknown ones?
- **Fix type:** QUICK FIX per instance — narrow the exception type where possible

---

## Bucket 3 — TYPE / CONTRACT ISSUES

### T1: Missing generic type arguments (92 findings)

- **Files:** execution.py (20), exec_eval.py (18), experiment_config.py (15), runner.py (10), live_metrics.py (8), evaluator.py (8), parse.py (5), others
- **Tool:** Pyright `reportMissingTypeArgument`
- **What:** `dict` instead of `dict[str, Any]`, `list` instead of `list[str]`, etc.
- **Root cause:** Code was written before strict typing was enabled. Functions use bare `dict`, `list`, `tuple` without type parameters.
- **Priority:** LOW — these are correct at runtime, just missing type annotations
- **Fix type:** SYSTEMIC — requires adding type annotations to ~50 function signatures
- **Assessment:** This is 45% of all pyright errors. Fixing these is mechanical but tedious.

### T2: Unused imports (30 Pyright + 135 Ruff F401 = ~135 unique)

- **Files:** execution.py (10), runner.py (5), exec_eval.py (4), experiment_config.py (2), and across test files
- **Tool:** Pyright `reportUnusedImport`, Ruff F401
- **Root cause:** Refactoring left behind imports that are no longer referenced. Some are re-exports (e.g., `from eval_cases import _has, _low  # noqa: F401`).
- **Priority:** MEDIUM — unused imports on the critical path mask the real dependency graph
- **Fix type:** QUICK FIX — `ruff check --fix` can auto-remove most

### T3: Optional member/call access (19 findings)

- **Files:** execution.py (8), evaluator.py (4), live_metrics.py (3), others
- **Tool:** Pyright `reportOptionalCall`, `reportOptionalMemberAccess`
- **What:** Calling methods on values that could be `None`
- **Root cause:** Functions return `X | None` but callers don't check for None before accessing.
- **Priority:** MEDIUM — these are potential runtime errors (though most are guarded by prior logic)
- **Fix type:** QUICK FIX — add None checks or narrow types

### T4: Private member access (13 findings)

- **Files:** runner.py (5), experiment_config.py (4), others
- **Tool:** Pyright `reportPrivateUsage`
- **What:** Accessing `_config_sha256`, `_active_logger`, etc. from outside the defining class/module
- **Root cause:** Internal state accessed for logging/debugging purposes
- **Priority:** LOW
- **Fix type:** QUICK FIX — make these public or add accessor methods

---

## Bucket 4 — HYGIENE / COSMETIC

### H1: Import sorting (188 findings, Ruff I001)

- **Files:** Nearly every .py file
- **Tool:** Ruff I001
- **Root cause:** Black was run but ruff's isort wasn't. The two tools have different import ordering preferences.
- **Priority:** LOWEST
- **Fix type:** QUICK FIX — `ruff check --fix` auto-sorts all imports

### H2: Magic numbers (239 findings, Ruff PLR2004)

- **Files:** exec_eval.py (40), runner.py (20), execution.py (15), retry_harness.py (30), and others
- **Tool:** Ruff PLR2004
- **What:** Numeric literals like `0.5`, `10`, `0.95` in comparisons
- **Root cause:** Configuration thresholds embedded in code. Many are intentional (e.g., `if score > 0.5`, `total_tests = 2`).
- **Priority:** LOWEST — these are mostly domain-specific constants
- **Fix type:** DEFER — extracting all to named constants would reduce readability

### H3: Deferred imports (433 findings, Ruff PLC0415)

- **Files:** Widespread — execution.py, runner.py, evaluator.py, etc.
- **Tool:** Ruff PLC0415
- **What:** Imports not at module top level
- **Root cause:** Same as A4 (circular import avoidance + lazy loading). Ruff and semgrep both flag this.
- **Priority:** LOWEST — these work correctly
- **Fix type:** DEFER — requires module restructuring

### H4: Long exception messages (101 findings, Ruff TRY003)

- **Files:** Throughout
- **Tool:** Ruff TRY003
- **What:** `raise ValueError("long message here")`
- **Root cause:** Detailed error messages are useful for debugging. The rule prefers custom exception classes.
- **Priority:** LOWEST — these messages are the right trade-off for a research codebase
- **Fix type:** DEFER

### H5: Semgrep INFO noise (6,114 findings)

- **Tool:** Semgrep (INFO severity)
- **Rules:** `assign-alias` (3,102), `implicit-none-return` (711), `inplace-mutation-dict/list` (756+), `partial-dict-update` (359), `debug-print` (294), `side-effect-after-loop` (114), `suspicious-comparison` (22)
- **Root cause:** The semgrep ruleset was expanded with extremely broad heuristic rules that flag normal Python patterns (dict assignment, list.append, print statements, for loops followed by function calls).
- **Priority:** NOT ACTIONABLE — these rules should be disabled or scoped to model-generated code only (they were designed for evaluating LLM output, not the benchmark infrastructure)
- **Fix type:** CONFIG CHANGE — remove or scope INFO rules in `.semgrep.yml`

### H6: Semgrep WARNING noise (3,517 findings)

- **Tool:** Semgrep (WARNING severity)
- **Rules:** `no-copy-dict-return` (989), `return-global-mutable` (989), `unreachable-code-after-return` (986), `cache-write-no-invalidate` (431)
- **Root cause:** Same as H5 — overly broad pattern matching. `return-global-mutable` flags every `return` of any variable. `unreachable-code-after-return` flags every `return` followed by any code in the same function. `no-copy-dict-return` flags every `return` of a dict variable.
- **Priority:** NOT ACTIONABLE — these rules are false positives at this scale
- **Fix type:** CONFIG CHANGE — remove these WARNING rules from `.semgrep.yml`

---

## Prioritized Execution Plan

### Phase 1 — Config Cleanup (0 code changes, immediate)

1. **Remove noisy semgrep rules** from `.semgrep.yml`: all INFO rules and the 3 false-positive WARNING rules (`no-copy-dict-return`, `return-global-mutable`, `unreachable-code-after-return`, `cache-write-no-invalidate`). Keep only ERROR rules + `no-broad-except-without-reraise` + `no-dynamic-import`.
   - **Impact:** Reduces semgrep from 9,624 to ~165 findings
   - **Risk:** None — removing noise improves signal

2. **Auto-fix import sorting**: `ruff check --fix` for I001
   - **Impact:** Eliminates 188 findings
   - **Risk:** None — auto-fix is safe

### Phase 2 — Quick Wins (small code changes)

3. **Delete unused imports** in pipeline files: execution.py, runner.py, exec_eval.py, experiment_config.py
   - **Impact:** Eliminates ~20 Vulture + ~30 Ruff F401 findings on critical path
   - **Risk:** LOW — verify no dynamic usage

4. **Fix silent exception blocks** (I1): Replace `except: pass` with logging in 15 locations
   - **Impact:** Eliminates 15 ERROR-level semgrep findings
   - **Risk:** LOW — behavior unchanged, just adds visibility

5. **Fix wildcard import** (I2): 1 location
   - **Impact:** 1 finding
   - **Risk:** None

### Phase 3 — Type Annotations (mechanical)

6. **Add generic type parameters**: `dict` → `dict[str, Any]`, etc. in function signatures
   - **Impact:** Eliminates ~92 pyright findings
   - **Risk:** None — no runtime change

7. **Add None checks** for optional access (T3)
   - **Impact:** Eliminates ~19 pyright findings
   - **Risk:** LOW

### Phase 4 — Deferred / Won't Fix

8. **Magic numbers** (H2): DEFER — not worth extracting in a research codebase
9. **Deferred imports** (H3/A4): DEFER — requires module restructuring
10. **Long exception messages** (H4): WON'T FIX — detailed messages are correct
11. **Global state** (A3): PARTIAL — whitelist intentional globals, fix accidental ones

---

## Risks

1. **Auto-fixing imports may break re-exports**: Some `import X  # noqa: F401` patterns are intentional re-exports. Verify before bulk deletion.
2. **Removing silent exceptions may surface hidden failures**: Test after each change.
3. **Semgrep rule removal must preserve the 8 ERROR rules**: Don't accidentally remove critical invariant checks.

---

## Noise / Exclusions

| Category | Count | Action |
|----------|-------|--------|
| Semgrep INFO rules | 6,114 | Remove from config — these are for LLM output evaluation, not infrastructure |
| Semgrep WARNING false positives | 3,406 | Remove 4 overly-broad rules |
| Ruff PLC0415 (deferred imports) | 433 | Suppress — architectural, not fixable without restructure |
| Ruff PLR2004 (magic numbers) | 239 | Suppress — domain constants are acceptable |
| Ruff TRY003 (long messages) | 101 | Suppress — detailed errors are correct |
| Pyright reportMissingTypeArgument | 92 | Fix mechanically in Phase 3 |
| Test file violations | ~400 | Exclude from pipeline checks — tests have different standards |
