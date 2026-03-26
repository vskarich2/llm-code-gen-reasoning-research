# Forensic Execution Audit: Is Model Code Actually Executed?

**Date:** 2026-03-25
**Scope:** runner.py, execution.py, exec_eval.py — code execution pipeline
**Auditor:** Claude (read-only investigation, no code changes)

---

## Executive Summary

**YES, model-generated code IS actually executed by the test harness** for all cases that reach the test phase. The `executed: False / tests_ran: YES` inconsistency is NOT a bug in test execution — it is a misleading reporting artifact caused by a hardcoded `total_tests=2` on an early-return code path where tests never run.

---

## The Inconsistency Under Investigation

From `debug_case_logs.txt`, case `mutable_default_b (baseline)`:

```
executed: False        ← code did NOT run
passed_tests: 0
total_tests: 2         ← implies 2 tests were attempted
tests_ran: YES         ← sanity check flag says YES
```

This appears logically impossible: if code didn't execute, how did 2 tests run?

---

## Execution Pipeline Trace (step-by-step)

### Normal path (e.g., alias_config_a — PASS case)

```
1. runner.py:_run_one_inner → calls run_single(case, model, "baseline")
2. execution.py:run_single → calls _attempt_and_evaluate(case, model, prompt)
3. execution.py:_attempt_and_evaluate:
   a. call_model(prompt) → raw model output (JSON string)
   b. parse_model_response(raw) → parsed dict {code: None, files: {...}, response_format: "file_dict"}
   c. reconstruct_strict() → reconstruction SUCCESS
   d. Wire changed files into parsed["code"] = "<model's fixed code>"
   e. evaluate_output(case, parsed) → calls exec_evaluate(case, code)
4. exec_eval.py:exec_evaluate:
   a. Check code non-empty → PASS (code has content)
   b. _assemble_program(code, case) → assembly result
   c. Check rename_error → FALSE → continues
   d. load_module_from_code(assembled_code) → creates module via exec()
   e. _load_v2_test(case) → loads test function from tests_v2/test_{family}.py
   f. test_fn(mod) → RUNS MODEL CODE via the loaded module → returns (True, [...])
   g. Returns {pass: True, execution: {ran: True, passed_tests: 2, total_tests: 2}}
```

### Rename error path (mutable_default_b — the inconsistent case)

```
1-3. Same as above through reconstruction and code wiring.
4. exec_eval.py:exec_evaluate:
   a. Check code non-empty → PASS
   b. _assemble_program(code, case):
      - model_defs = {process_batch, summarize}
      - original_defs = {create_task, enqueue, dequeue, process_batch, summarize}
      - expected_func = "enqueue" (from case.reference_fix.function)
      - "enqueue" IN original_defs AND NOT IN model_defs
      - rename_error = True
   c. *** EARLY RETURN at line 781 ***
      Returns _result(pass=False, execution={ran=False, total_tests=2})
   d. load_module_from_code is NEVER called
   e. test_fn is NEVER called
   f. NO CODE IS EXECUTED
```

**Root cause of the reporting inconsistency:** `total_tests` is set to `2` at line 760 (`total_tests = 2  # invariant + mutation`) BEFORE any execution logic. When the rename error triggers an early return at line 781, it includes `total_tests=2` in the result even though zero tests were attempted. The debug log generator then sees `total_tests > 0` and reports `tests_ran: YES`.

---

## Answers to Mandatory Questions

### Q1: What code is ACTUALLY executed?

**(A) Model-generated code** — verified behaviorally.

For `alias_config_a`, the model produced code with `DEFAULTS.copy()`. After loading via `exec()`, calling `create_config({"timeout": 5})` followed by `create_config()` returns `timeout=30` (no aliasing). If the ORIGINAL buggy code had run, `timeout` would be `5` (aliasing bug). The behavioral test proves model code is executing.

**Evidence:**
```
cfg1["timeout"]: 5    ← first call overrides
cfg2["timeout"]: 30   ← second call gets clean defaults (model's .copy() fix works)
DEFAULTS["timeout"]: 30 ← globals not mutated
```

If original code ran: `cfg2["timeout"]` would be `5` and `DEFAULTS["timeout"]` would be `5`.

### Q2: Is model-generated code EVER written to disk?

**NO.** The code is compiled from a string and `exec()`'d into an in-memory module object.

- `exec_eval.py:49`: `exec(compile(cleaned, f"<{mod_name}>", "exec"), mod.__dict__)`
- Module has no `__file__` attribute
- No temporary files created
- No disk I/O for code execution

### Q3: How do tests access the code?

**Dynamic `exec()` → module object → passed directly to test function.**

```python
# exec_eval.py:798
mod = load_module_from_code(assembled_code, case_id)  # exec() into module

# exec_eval.py:851
inv_pass, inv_reasons = test_fn(mod)  # test receives module directly
```

No imports, no module reload, no caching. The test function receives the exact module object that was created from the model's code. Tests access functions via `getattr(mod, "function_name")`.

### Q4: Can tests run WITHOUT executing model code?

**NO.** There is no code path where `test_fn(mod)` is called without `mod` being created from model code first.

The call to `test_fn(mod)` at line 851 is only reachable after:
1. Line 762: code is non-empty (otherwise early return with `ran=False`)
2. Line 781: no rename error (otherwise early return with `ran=False`)
3. Line 798: `load_module_from_code(assembled_code)` succeeds (otherwise early return with error)

If any of these fail, the function returns before reaching line 851. **Tests cannot run without model code being loaded into a module.**

Verified: passing empty string → `ran=False, total_tests=2, passed_tests=0, status=failed`. Tests did NOT run.

### Q5: How does `executed: False / tests_ran: YES` occur?

**`total_tests` is hardcoded to 2 at line 760, before any execution logic.** Early-return paths include this value in their result even though no tests ran.

Specifically, for `mutable_default_b`:

```python
# Line 760
total_tests = 2  # invariant + mutation  ← SET HERE

# Line 781-792: rename error detected → EARLY RETURN
if asm.get("rename_error"):
    return _result(case_id, False, 0.0,
                   [...],
                   _exec_info(ran=False, total_tests=total_tests,  # ← INCLUDES total_tests=2
                              assembly_used=..., assembly_error=False,
                              rename_error=True, ...))
```

The debug log generator then computed:
```
tests_ran = total_tests > 0  →  2 > 0  →  YES
```

**This is a REPORTING BUG, not an execution bug.** The `total_tests` field should be `0` on early-return paths where tests never ran, or the sanity check should use `passed_tests > 0 OR (total_tests > 0 AND ran == True)` as the criterion.

### Q6: What is "assembly_used"?

**Assembly** is the process of merging model-generated code with original case files for multi-file cases.

- **Triggers when:** `len(code_files_contents) > 1` (multi-file case)
- **Code path:** `_assemble_program()` at `exec_eval.py:661`
- **What it does:** Concatenates original files (with cross-file imports stripped), then appends model code. Later definitions override earlier ones.
- **Does it bypass model code?** NO. It PREPENDS original code and APPENDS model code. Model definitions override originals via Python's top-to-bottom execution.

For single-file cases: `assembly_used=False`, model code passed through directly.
For multi-file cases: `assembly_used=True`, `assembled = original_cleaned + "\n\n" + model_cleaned`.

### Q7: Is there ANY code path where model output is ignored but tests still run?

**NO.** Every path to `test_fn(mod)` requires `mod` to be loaded from assembled code that includes model output.

Verified by exhaustive check of all return statements in `exec_evaluate`:
- Line 763: `ran=False` — tests don't run
- Line 782: `ran=False` — tests don't run (the rename path)
- Line 800: `ran=False` — syntax error, tests don't run
- Line 808: `ran=False` — NameError/ImportError, tests don't run
- Line 821: `ran=False` — generic load error, tests don't run
- Line 851+: `ran=True` — tests DO run, on the loaded module

**There is no path where tests run on non-model code.**

---

## Root Cause (1-2 sentences)

The `executed: False / tests_ran: YES` inconsistency is a **reporting bug in the sanity check logic**, not an execution bug. `total_tests` is hardcoded to `2` at the top of `exec_evaluate` and included in early-return results where tests never ran, causing downstream checks that use `total_tests > 0` as a proxy for "tests ran" to produce false positives.

The model-generated code IS being executed correctly in all cases that reach the test phase. The `mutable_default_b` case hits an early return because of a **rename error** (case metadata says the fix should override `enqueue`, but the reference fix and model output override `process_batch`/`summarize` instead). This is a case metadata bug, not a pipeline bug.

---

## Summary Table

| Question | Answer | Confidence |
|----------|--------|------------|
| Is model code executed? | **YES** — for all cases that pass the pre-checks | Verified behaviorally |
| Is code written to disk? | **NO** — exec()'d from string in memory | Verified via module inspection |
| How do tests access code? | **Direct module object** passed to test function | Verified via code trace |
| Can tests run without model code? | **NO** — test_fn(mod) is unreachable without prior load | Verified by exhaustive path analysis |
| Why executed=False/tests_ran=YES? | **Reporting bug** — total_tests=2 hardcoded on early-return path | Verified via code trace at lines 760, 781-792 |
| What is assembly_used? | Multi-file merging of original + model code | Verified via code trace |
| Any path ignoring model output? | **NO** — every test path requires model code in module | Verified exhaustively |
