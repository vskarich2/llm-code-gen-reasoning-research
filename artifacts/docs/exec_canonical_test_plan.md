# Canonical Execution: Test Plan

## Test Data Sources

| Source | What | Count |
|---|---|---|
| `cases_v2.json` | All 58 benchmark cases with original code + reference fixes | 58 |
| `logs/v2_full_4model_5trial/merged_run.jsonl` | Real model outputs from 4 models × 5 trials | 3,480 rows |
| `logs/v2_full_4model_5trial/**/calls/*.json` | Raw model responses with full prompt/response | 3,000+ files |
| Multi-file cases | 39 cases with 2-5 files each | 39 |
| Known recursion-affected cases | 9 cases where concat path produces RecursionError | 9 |
| Known failure families | 22 distinct bug families | 22 |

All tests use REAL data. No synthetic toy cases except for deliberate failure injection.

---

## Test Files

```
tests/test_exec_canonical.py       # Core execution correctness
tests/test_exec_stress.py          # Full benchmark + real model outputs
tests/test_exec_isolation.py       # State leakage, retry contamination
tests/test_exec_determinism.py     # Repeatability, ordering independence
tests/test_exec_classification.py  # Failure category accuracy + injection
```

---

## File 1: test_exec_canonical.py

### Test 1.1: Single-file reference fix passes

For each of the 19 single-file cases:
- Load case from cases_v2.json with code_files_contents populated
- Build ReconstructionResult from reference fix
- Call exec_canonical()

ASSERT per case:
- `result["pass"] == True`
- `result["execution_category"] == "EXECUTION_SUCCESS"`
- `result["score"] == 1.0`
- `result["execution"]["ran"] == True`
- `result["execution"]["passed_tests"] == result["execution"]["total_tests"]`

ASSERT aggregate:
- 19/19 pass (0 failures allowed for reference fixes on single-file)

### Test 1.2: Multi-file reference fix passes

For each of the 39 multi-file cases:
- Load case with code_files_contents
- Build ReconstructionResult from reference fix
- Call exec_canonical()

ASSERT per case:
- `result["pass"] == True`
- `result["execution_category"] == "EXECUTION_SUCCESS"`

ASSERT aggregate:
- 39/39 pass
- If any fail, print case_id + error + full subprocess stderr

This is the most critical test. If reference fixes don't pass through the
canonical path, the system is broken.

### Test 1.3: Buggy code fails

For each of the 58 cases:
- Use ORIGINAL buggy code as reconstruction (no model changes)
- Call exec_canonical()

ASSERT per case:
- `result["pass"] == False`
- `result["score"] < 1.0`

ASSERT aggregate:
- 58/58 fail (buggy code must fail its own tests)
- If any pass, the test function is broken, not the execution system

### Test 1.4: Package disk structure

Pick 5 multi-file cases (effect_order_b, alias_config_c, l3_state_pipeline,
cache_invalidation_order, invariant_partial_fail).

For each:
- Call _materialize_package()
- Inspect the resulting directory

ASSERT:
- `pkg/` exists and is a directory
- `pkg/__init__.py` exists and is empty
- For each case code_file: corresponding .py exists in pkg/
- File contents match reconstruction input (exact byte comparison)
- No extra files in pkg/ (only expected modules + __init__.py)
- `harness/run_case.py` exists
- `case_meta.json` exists and is valid JSON with required fields

### Test 1.5: Subprocess result schema

Run 10 cases (mix of pass and fail).

ASSERT for every result:
- `"pass" in result`
- `"score" in result`
- `"reasons" in result and isinstance(result["reasons"], list)`
- `"execution" in result and isinstance(result["execution"], dict)`
- `"execution_category" in result`
- `result["execution"]["assembly_used"] == False`
- `result["score"] in (0.0, 0.1, 0.2, 1.0)`

### Test 1.6: Return format matches exec_evaluate contract

Run 5 cases through BOTH exec_canonical and exec_evaluate (legacy).

For passing cases, ASSERT:
- Same set of top-level keys
- Same `pass` value (for single-file cases where both should agree)
- `execution` sub-dict has all required fields

This verifies downstream consumers (evaluator_v2, metrics_v2) won't break.

---

## File 2: test_exec_stress.py

### Test 2.1: All 58 reference fixes

Run ALL 58 cases with reference fixes through exec_canonical.

Track:
```python
results = {
    "total": 0,
    "pass": 0,
    "fail": 0,
    "by_category": Counter(),
    "by_family": defaultdict(lambda: {"pass": 0, "fail": 0}),
    "failures": []  # list of (case_id, category, error)
}
```

ASSERT:
- `results["pass"] == 58`
- `results["fail"] == 0`
- Zero IMPORT_FAILURE, SYNTAX_FAILURE, RUNTIME_FAILURE, BUILD_FAILURE

Print full summary table.

### Test 2.2: All 58 buggy codes

Same as 2.1 but with original buggy code.

ASSERT:
- `results["fail"] == 58`
- Most categories are INVARIANT_FAILURE (test logic failure, not crash)
- Zero BUILD_FAILURE (buggy code is still valid Python)
- Count INVARIANT_CRASH separately — these indicate fragile tests

### Test 2.3: Real model outputs (gpt-5-mini baseline)

Load model outputs from `logs/v2_full_4model_5trial/merged_run.jsonl`.
Filter to gpt-5-mini baseline_v2 (58 rows, one per case).

For each row:
- Extract case_id and reconstruct the model's file changes
- Load the original response from calls/ directory
- Parse with parse_v2_execution
- Reconstruct with reconstruct_strict
- Run exec_canonical

Track pass/fail distribution.

ASSERT:
- Zero BUILD_FAILURE (all model outputs are processable)
- Zero crashes in the harness itself (invalid_output, non-zero exit)
- Pass rate within 10pp of the legacy path's recorded pass rate
  (difference expected only on recursion-affected cases)

### Test 2.4: Known recursion cases

The 9 cases where concat path produces RecursionError:
- effect_order_b, effect_order_c
- retry_dup_b, retry_dup_c
- partial_rollback_b, partial_rollback_c
- use_before_set_b, use_before_set_c
- async_race_lock

For each, load a gpt-5-mini model output that triggered recursion on the
legacy path (from the contamination audit — these are stored in calls/ dirs).

Run through exec_canonical.

ASSERT:
- ZERO RecursionError
- execution_category is NOT "RUNTIME_FAILURE with subtype RecursionError"
- If the model's code was actually correct: EXECUTION_SUCCESS
- If the model's code had a real bug: INVARIANT_FAILURE (not recursion crash)

This is the test that proves the architecture fix works.

### Test 2.5: Delegation pattern specific

Manually construct the gpt-5-mini delegation pattern for effect_order_b:

```python
from metrics import increment, emit_event, reset as metrics_reset

def reset():
    metrics_reset()

def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
    return len(items)
```

Run through exec_canonical.

ASSERT:
- `result["pass"] == True`
- `result["execution_category"] == "EXECUTION_SUCCESS"`
- No RecursionError anywhere in result or subprocess stderr

This is the smoking gun test. The exact code that breaks concat must work here.

### Test 2.6: Multi-model comparison

Load model outputs for all 4 models on a subset of 10 cases.
Run each through exec_canonical.

Track pass rates by model.

ASSERT:
- No systematic model-specific crashes
- gpt-5-mini pass rate is NOT artificially depressed (compare against
  legacy path — canonical should be equal or better)

Print comparison table.

---

## File 3: test_exec_isolation.py

### Test 3.1: No state leakage across sequential runs

Pick 3 stateful cases:
- mutable_default_a (MUTABLE_DEFAULT)
- stale_cache_a (STALE_CACHE)
- retry_dup_a (RETRY_DUPLICATION)

For each:
- Run exec_canonical 3 times sequentially with SAME input

ASSERT:
- All 3 results are identical (same pass/fail, same score, same reasons)
- No drift between runs

### Test 3.2: No state leakage across different cases

Run:
1. exec_canonical(mutable_default_a, reference_fix) → PASS
2. exec_canonical(stale_cache_a, buggy_code) → FAIL
3. exec_canonical(mutable_default_a, reference_fix) → PASS

ASSERT:
- Result 1 == Result 3 (running a different case in between doesn't affect it)

### Test 3.3: Retry attempt isolation

Simulate retry scenario:
1. exec_canonical(effect_order_b, attempt=0, buggy_model_code) → FAIL
2. exec_canonical(effect_order_b, attempt=1, fixed_model_code) → PASS

ASSERT:
- Attempt 1 result is not contaminated by attempt 0
- Attempt 1 uses a different temp directory
- If attempt 0 introduced module-level state, attempt 1 doesn't see it

### Test 3.4: Temp directory uniqueness

Run exec_canonical 5 times, capture pkg_dir paths.

ASSERT:
- All 5 paths are different
- None overlap
- After cleanup, none exist on disk

### Test 3.5: sys.modules not polluted

Before and after running exec_canonical:
- Snapshot `set(sys.modules.keys())`

ASSERT:
- No new modules added that start with case module names
  (no `metrics`, `processor`, `config` etc. leaked into parent)

---

## File 4: test_exec_determinism.py

### Test 4.1: Same input same output (5 repetitions)

Pick 5 cases (mix of pass/fail, single/multi-file).

For each case, run exec_canonical 5 times with identical input.

ASSERT:
- All 5 results are byte-identical when serialized to JSON
  (same pass, score, reasons, category, modules_loaded)

### Test 4.2: Ordering independence

Run cases in order: [A, B, C, D, E]
Run cases in order: [E, D, C, B, A]
Run cases in order: [C, A, E, B, D]

ASSERT:
- Result for each case is identical across all 3 orderings

### Test 4.3: Parallel independence

Run 5 cases simultaneously (via ThreadPoolExecutor or sequential — the
subprocess isolation should make this safe).

Compare results against sequential execution.

ASSERT:
- Identical results

---

## File 5: test_exec_classification.py

### Test 5.1: EXECUTION_SUCCESS

Use reference fix for any case.

ASSERT:
- `result["execution_category"] == "EXECUTION_SUCCESS"`
- `result["score"] == 1.0`

### Test 5.2: INVARIANT_FAILURE

Use buggy code for any case (the bug makes the test return False).

ASSERT:
- `result["execution_category"] == "INVARIANT_FAILURE"`
- `result["score"] == 0.2`

### Test 5.3: SYNTAX_FAILURE (injected)

Take a valid case. Inject syntax error into model code:

```python
def process_batch(items)   # missing colon
    return len(items)
```

ASSERT:
- `result["execution_category"] == "SYNTAX_FAILURE"`
- `result["score"] == 0.0`
- `"SyntaxError" in result["execution"]["error_message"]`

### Test 5.4: IMPORT_FAILURE (injected)

Take a valid case. Inject bad import:

```python
from nonexistent_module import something
```

ASSERT:
- `result["execution_category"] == "IMPORT_FAILURE"`
- `result["score"] == 0.0`

### Test 5.5: NAME_ERROR (injected)

Take a valid case. Reference undefined variable:

```python
def process_batch(items):
    return undefined_variable
```

ASSERT:
- `result["execution_category"] == "NAME_ERROR"`
- `result["score"] == 0.0`

### Test 5.6: TIMEOUT (injected)

Take a valid case. Inject infinite loop:

```python
def process_batch(items):
    while True:
        pass
```

Run with timeout=3 (short).

ASSERT:
- `result["execution_category"] == "TIMEOUT"`
- `result["score"] == 0.0`
- Completes within timeout + small buffer (doesn't hang)

### Test 5.7: INVARIANT_CRASH (injected)

Take a valid case. Inject code that raises during test execution:

```python
def process_batch(items):
    raise RuntimeError("deliberate crash")
```

ASSERT:
- `result["execution_category"] == "INVARIANT_CRASH"`
- `result["score"] == 0.1`
- `"RuntimeError" in str(result["execution"])`

### Test 5.8: RECONSTRUCTION_FAILURE

Pass a reconstruction result with status="FAILED_MISSING_FILES".

ASSERT:
- `result["execution_category"] == "RECONSTRUCTION_FAILURE"`
- `result["score"] == 0.0`
- Subprocess was NOT spawned

### Test 5.9: BUILD_FAILURE (injected)

Make temp dir creation fail (e.g., pass invalid path).

ASSERT:
- `result["execution_category"] == "BUILD_FAILURE"`
- `result["score"] == 0.0`

### Test 5.10: Category exhaustiveness

Collect all results from tests 5.1-5.9.

ASSERT:
- Every defined category was triggered at least once
- No result has an undefined category
- Category + score mapping is consistent with the spec

---

## Cross-Cutting Requirements

### Every test prints results

```python
def _print_summary(results):
    print(f"\n{'='*60}")
    print(f"  Total: {results['total']}")
    print(f"  Pass:  {results['pass']} ({100*results['pass']/results['total']:.0f}%)")
    print(f"  Fail:  {results['fail']}")
    if results.get('by_category'):
        print(f"  Categories:")
        for cat, n in sorted(results['by_category'].items()):
            print(f"    {cat}: {n}")
    if results.get('failures'):
        print(f"  First 5 failures:")
        for cid, cat, err in results['failures'][:5]:
            print(f"    {cid}: {cat} — {err[:80]}")
    print(f"{'='*60}")
```

### Every test uses real case loading

```python
@pytest.fixture(scope="module")
def all_cases():
    """Load all 58 cases with code_files_contents populated."""
    cases = json.load(open("cases_v2.json"))
    for case in cases:
        for rel_path in case["code_files"]:
            case.setdefault("code_files_contents", {})
            case["code_files_contents"][rel_path] = Path(rel_path).read_text().strip()
    return {c["id"]: c for c in cases}
```

### Every test that loads model outputs

```python
def _load_model_outputs(ablation_dir, model, condition):
    """Load real model outputs from ablation logs."""
    rows = [json.loads(l) for l in open(f"{ablation_dir}/merged_run.jsonl")]
    return [r for r in rows if r["model"] == model and r["condition"] == condition]
```

### Failure is always actionable

Every assertion failure must print:
- case_id
- expected vs actual
- full subprocess stderr if available
- execution_category
- error_message

---

## Test Counts

| File | Tests | Cases exercised |
|---|---|---|
| test_exec_canonical.py | 6 tests | 58 + 58 + 39 + 19 + 10 + 5 = 189 executions |
| test_exec_stress.py | 6 tests | 58 + 58 + 58 + 9 + 1 + 40 = 224 executions |
| test_exec_isolation.py | 5 tests | 9 + 3 + 2 + 5 + 1 = 20 executions |
| test_exec_determinism.py | 3 tests | 25 + 15 + 5 = 45 executions |
| test_exec_classification.py | 10 tests | 10 executions |
| **TOTAL** | **30 tests** | **~488 exec_canonical calls** |

Each call spawns a real subprocess. At ~0.5s per call (including cleanup),
total test time: ~4 minutes. Acceptable.

---

## Mandatory Ablation Data Tests

### Test: Recursion contamination eliminated

Load ALL 121 recursion-contaminated rows from the contamination audit.
For each, extract the model's raw response, reconstruct, run through
exec_canonical.

ASSERT:
- Zero RecursionError in any result
- Every case that was EXECUTION_SUCCESS on the legacy path is still
  EXECUTION_SUCCESS on canonical
- Cases that were RecursionError on legacy are now either EXECUTION_SUCCESS
  (model code was actually correct) or INVARIANT_FAILURE (model code had
  a real bug, now correctly detected)

This is the definitive test that the architecture fix works on real
contaminated data.

### Test: gpt-5-mini pass rate correction

Compare gpt-5-mini pass rates:
- Legacy path (from merged_run.jsonl)
- Canonical path (from this test run)

For the 6 affected cases (effect_order_b/c, retry_dup_b/c, partial_rollback_b/c):

ASSERT:
- Canonical pass rate >= legacy pass rate
- The difference is exactly the recursion-contaminated rows

Print the corrected vs original pass rates.
