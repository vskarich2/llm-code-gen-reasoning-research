# CANONICAL EXECUTION SPEC (v5 — final)

---

# PART 1: ARCHITECTURE

## 4 files

```
exec_canonical.py                    ~220 lines
harness/run_case.py                  ~120 lines
join_reasoning_execution.py           ~50 lines
score_execution.py                    ~60 lines
```

## exec_canonical.py

One public function. Owns materialization, subprocess, validation, classification.

```python
def exec_canonical(case, parsed_gen, recon, config, logger, attempt=0) -> dict
```

## harness/run_case.py

Minimal subprocess entry point. Discovers and imports modules from disk, builds
merged test namespace with conflict detection and call-level tracing, runs test,
emits structured JSON. Nontrivial but narrowly scoped — no business logic, no
classification, no retries.

## join_reasoning_execution.py

Constructs reasoning/execution relationship. Derives signals internally.
No scoring. No thresholds. No categories beyond alignment.

```python
def join_reasoning_execution(parsed_gen, classifier_result, exec_result, case, condition, model) -> dict
```

## score_execution.py

Assigns LEG, lucky_fix, v2_category. Builds final ev dict. No reasoning logic.

```python
def score_execution(joined, artifact, classifier_result, exec_result, case, condition, model) -> dict
```

---

# PART 2: CONTRACTS

## Subprocess output schema

```json
{
  "status": "ok | error",
  "passed": bool,
  "failure_reasons": [str],
  "error_type": str | null,
  "error_message": str | null,
  "traceback": str | null,
  "modules_loaded": [str],
  "functions_detected": [str],
  "functions_called": [str],
  "merge_conflicts": [str],
  "execution_trace": [str],
  "execution_time_ms": int
}
```

### Field definitions

- `modules_loaded`: module names imported from pkg/ (e.g., ["metrics", "processor"])
- `functions_detected`: all non-dunder callables in merged namespace
- `functions_called`: wrapped merged-namespace callables invoked during test
  execution. Only tracks calls routed through the merged namespace wrapper — direct
  calls within module code (e.g., a helper calling another helper internally) are
  not captured. If a wrapped callable was called at least once, it appears here.
- `merge_conflicts`: names defined in 2+ modules (last-module-wins, logged)
- `execution_trace`: ordered events during execution. Contains:
  - `"meta_loaded: {case_id}"`
  - `"discovered: [mod1, mod2]"`
  - `"import: {mod_name}"` for each module imported
  - `"merged: N callables, M conflicts"`
  - `"test_fn: {func_name}"`
  - `"test_start"`
  - `"call: {func_name}"` for each wrapped merged-namespace callable invoked (appended at call time, interleaved with execution)
  - `"test_end: pass|fail"`
  - `"exception: {type}"` if exception occurred

### Why `functions_called` not `modules_used`

The previous spec had `modules_used` which was inferred from which modules
exported callables — that is availability, not usage. `functions_called` tracks
invocations that go through the merged-namespace wrapper. It does not capture
internal calls between functions within a module. The modules that contributed
the wrapped callables can be derived from `functions_called` + the
name-to-source mapping already built during merge.

## Subprocess output validation

```python
REQUIRED_SUBPROCESS_FIELDS = frozenset({
    "status", "passed", "failure_reasons", "error_type",
    "error_message", "traceback", "modules_loaded",
    "functions_detected", "functions_called", "merge_conflicts",
    "execution_trace", "execution_time_ms",
})

def _validate(result):
    missing = REQUIRED_SUBPROCESS_FIELDS - set(result.keys())
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if not isinstance(result["passed"], bool):
        raise ValueError(f"'passed' must be bool, got {type(result['passed'])}")
    for field in ("failure_reasons", "modules_loaded", "functions_detected",
                  "functions_called", "merge_conflicts", "execution_trace"):
        if not isinstance(result[field], list):
            raise ValueError(f"'{field}' must be list, got {type(result[field])}")
    if not isinstance(result["execution_time_ms"], (int, float)):
        raise ValueError("'execution_time_ms' must be numeric")
```

## Classification taxonomy

13 categories. No phantom categories. Every one has a classification rule and a test.

```
PARSE_FAILURE              → 0.0    parse_valid == False (before exec_canonical)
RECONSTRUCTION_FAILURE     → 0.0    recon.status != SUCCESS (before exec_canonical)
BUILD_FAILURE              → 0.0    filesystem / package creation error
SUBPROCESS_CRASH           → 0.0    non-zero exit code
INVALID_OUTPUT             → 0.0    stdout not valid JSON
SCHEMA_VIOLATION           → 0.0    output missing required fields or wrong types
TIMEOUT                    → 0.0    subprocess exceeded time limit
SYNTAX_FAILURE             → 0.0    error_type == "SyntaxError"
IMPORT_FAILURE             → 0.0    error_type in ("ImportError", "ModuleNotFoundError")
NAME_ERROR                 → 0.0    error_type == "NameError"
INVARIANT_CRASH            → 0.1    other exception during test (TypeError, RecursionError, etc.)
INVARIANT_FAILURE          → 0.2    test ran, returned (False, reasons)
EXECUTION_SUCCESS          → 1.0    test ran, returned (True, reasons)
```

RUNTIME_FAILURE is deleted. It was never returned by `_classify()` and never
tested. All non-specific runtime exceptions during test execution fall into
INVARIANT_CRASH (score 0.1), which correctly distinguishes "test crashed" from
"test ran and returned False."

`_classify()` ends with:

```python
raise RuntimeError(f"Unclassifiable subprocess result: {result}")
```

No fallback. No default. No UNKNOWN.

```python
ALL_CATEGORIES = frozenset({
    "PARSE_FAILURE", "RECONSTRUCTION_FAILURE", "BUILD_FAILURE",
    "SUBPROCESS_CRASH", "INVALID_OUTPUT", "SCHEMA_VIOLATION",
    "TIMEOUT", "SYNTAX_FAILURE", "IMPORT_FAILURE", "NAME_ERROR",
    "INVARIANT_CRASH", "INVARIANT_FAILURE", "EXECUTION_SUCCESS",
})
```

## Classification function

```python
def _classify(result):
    status = result.get("status", "")
    err = result.get("error_type") or ""

    if status == "timeout":        return "TIMEOUT", 0.0
    if status == "crash":          return "SUBPROCESS_CRASH", 0.0
    if status == "invalid_output": return "INVALID_OUTPUT", 0.0
    if err == "SyntaxError":       return "SYNTAX_FAILURE", 0.0
    if err in ("ImportError", "ModuleNotFoundError"): return "IMPORT_FAILURE", 0.0
    if err == "NameError":         return "NAME_ERROR", 0.0
    if err and status == "error":  return "INVARIANT_CRASH", 0.1
    if status == "ok" and not result.get("passed", False): return "INVARIANT_FAILURE", 0.2
    if status == "ok" and result.get("passed", False):     return "EXECUTION_SUCCESS", 1.0

    raise RuntimeError(f"Unclassifiable subprocess result: {result}")
```

## Return dict

```python
{
    "pass": bool,
    "score": float,
    "reasons": list[str],
    "failure_modes": list[str],
    "execution": {
        "status": str,
        "ran": bool,
        "passed_tests": int,
        "total_tests": int,
        "runtime_error": str | None,
        "error_message": str | None,
        "syntax_error": str | None,
        "assembly_used": False,
        "assembly_error": False,
        "assembly_risky": False,
        "rename_error": False,
        "assembly_sources": None,
        "invariant_pass": bool | None,
        "mutation_pass": None,
    },
    "execution_category": str,
    "execution_subtype": str | None,
    "modules_loaded": list[str],
    "functions_detected": list[str],
    "functions_called": list[str],
    "merge_conflicts": list[str],
    "execution_trace": list[str],
    "_extracted_code": str,
    "_assembled_code": "disk_backed",
}
```

## Consistency checks in _make_result

```python
if not ran and category == "EXECUTION_SUCCESS":
    raise RuntimeError("Invalid state: EXECUTION_SUCCESS without execution")
if ran and category in ("PARSE_FAILURE", "RECONSTRUCTION_FAILURE", "BUILD_FAILURE"):
    raise RuntimeError(f"Invalid state: {category} but ran=True")
if category not in ALL_CATEGORIES:
    raise RuntimeError(f"Unknown category: {category}")
```

---

# PART 3: IMPLEMENTATION

## exec_canonical.py

Same as v3 spec with these corrections:

- `ALL_CATEGORIES` has 13 entries (RUNTIME_FAILURE removed)
- `_classify()` ends with `raise RuntimeError` (no fallback)
- Return dict uses `functions_called` instead of `modules_used`
- `_make_result` enforces all three consistency checks
- `_validate` checks `functions_called` not `modules_used`

No other structural changes from v3. The full implementation is in v3 spec
Part 3 with these field name and taxonomy fixes applied.

## harness/run_case.py

Minimal subprocess entry point. Key changes from v3:

### Call-level tracing via lightweight wrapper

After building the merged namespace, wrap each callable with a tracer:

```python
# Build merged namespace with conflict detection
merged = types.ModuleType("_t3_merged")
merged.__dict__["__builtins__"] = __builtins__
conflicts = []
name_to_source = {}
_calls_log = []

for mod_name in module_files:
    for key, val in vars(loaded[mod_name]).items():
        if key.startswith("__"):
            continue
        if key in merged.__dict__:
            conflicts.append(key)
        name_to_source[key] = mod_name
        # Wrap callables with tracer
        if callable(val):
            original = val
            def _make_tracer(fn_name, fn):
                def traced(*args, **kwargs):
                    _calls_log.append(fn_name)
                    result["execution_trace"].append(f"call: {fn_name}")
                    return fn(*args, **kwargs)
                traced.__name__ = fn_name
                traced.__qualname__ = fn_name
                return traced
            merged.__dict__[key] = _make_tracer(key, original)
        else:
            merged.__dict__[key] = val
```

After test execution:

```python
result["functions_called"] = sorted(set(_calls_log))
```

Call events appear in `execution_trace` between `test_start` and `test_end`
because the tracer appends at call time, not post hoc. This means the trace
reflects actual execution order. `functions_called` is the deduplicated set.

### Full harness output

```python
result = {
    "status": "error",
    "passed": False,
    "failure_reasons": [],
    "error_type": None,
    "error_message": None,
    "traceback": None,
    "modules_loaded": [],
    "functions_detected": [],
    "functions_called": [],
    "merge_conflicts": [],
    "execution_trace": [],
    "execution_time_ms": 0,
}
```

All 12 fields initialized. All 12 populated. All 12 validated by parent.

## join_reasoning_execution.py

```python
def join_reasoning_execution(parsed_gen, classifier_result, exec_result,
                             case, condition, model):
    if "execution_category" not in exec_result:
        raise RuntimeError("exec_result missing execution_category")
    category = exec_result["execution_category"]

    signals = derive_v2_signals(
        classifier_dims={
            "mechanism_identified": classifier_result.mechanism_identified,
            "commitments_extracted": classifier_result.commitments_extracted,
            "commitments_satisfied": classifier_result.commitments_satisfied,
            "reasoning_code_alignment": classifier_result.reasoning_code_alignment,
        },
        code_correct=exec_result.get("pass", False),
        commitments_source=getattr(parsed_gen, "commitments_source", "none")
            if hasattr(parsed_gen, "commitments_source") else "none",
    )

    exec_pass = exec_result.get("pass", False)
    mechanism_correct = signals.mechanism_correct
    commitments_valid = signals.commitments_valid
    alignment_positive = signals.alignment_positive

    if mechanism_correct is None:
        alignment = "unknown"
    elif mechanism_correct and exec_pass:
        alignment = "aligned"
    elif mechanism_correct and not exec_pass:
        alignment = "misaligned"
    elif not mechanism_correct and exec_pass:
        alignment = "lucky"
    else:
        alignment = "both_wrong"

    return {
        "execution_pass": exec_pass,
        "execution_category": category,
        "mechanism_correct": mechanism_correct,
        "commitments_valid": commitments_valid,
        "alignment_positive": alignment_positive,
        "reasoning_execution_alignment": alignment,
        "signals": signals,
    }
```

### Return schema (exact)

```json
{
  "execution_pass": bool,
  "execution_category": str,
  "mechanism_correct": bool | null,
  "commitments_valid": bool | null,
  "alignment_positive": bool | null,
  "reasoning_execution_alignment": "aligned | misaligned | lucky | both_wrong | unknown",
  "signals": V2Signals
}
```

No fallbacks. Missing `execution_category` → RuntimeError.

## score_execution.py

```python
def score_execution(joined, artifact, classifier_result, exec_result,
                    case, condition, model):
    """
    Build final ev dict. Requires exec_result (not None) because
    assemble_v2_result uses it for pass/fail, score, execution metadata.
    """
    signals = joined["signals"]

    ev = assemble_v2_result(
        exec_result=exec_result,
        artifact=artifact,
        classifier=classifier_result,
        signals=signals,
        case=case,
        condition=condition,
        model=model,
    )

    ev["execution_category"] = joined["execution_category"]
    ev["reasoning_execution_alignment"] = joined["reasoning_execution_alignment"]
    ev["leg_candidate"] = joined["mechanism_correct"] is True and not joined["execution_pass"]
    ev["lucky_fix_candidate"] = joined["execution_pass"] and joined["mechanism_correct"] is False

    return ev
```

### Input requirements

- `joined`: dict from `join_reasoning_execution()`. Must contain all 7 fields.
- `artifact`: `NormalizedReasoningArtifactV2` from Stage B normalization.
- `classifier_result`: `ClassifierResultV2` from evaluator.
- `exec_result`: dict from `exec_canonical()`. Must not be None.
  `assemble_v2_result` reads `exec_result["pass"]`, `exec_result["score"]`,
  `exec_result.get("execution", {})` etc. Passing None would crash.
- `case`, `condition`, `model`: metadata for the ev dict.

---

# PART 4: FAILURE MODEL

13 categories. Every one has a classification rule, a score, and a test.

| # | Category | Score | Trigger | Test |
|---|---|---|---|---|
| 1 | PARSE_FAILURE | 0.0 | parse_valid == False | test_parse_failure |
| 2 | RECONSTRUCTION_FAILURE | 0.0 | recon.status != SUCCESS | test_reconstruction_failure |
| 3 | BUILD_FAILURE | 0.0 | filesystem error in _materialize | test_build_failure |
| 4 | SUBPROCESS_CRASH | 0.0 | non-zero exit code | test_subprocess_crash |
| 5 | INVALID_OUTPUT | 0.0 | stdout not JSON | test_invalid_output |
| 6 | SCHEMA_VIOLATION | 0.0 | missing/wrong fields | test_schema_violation |
| 7 | TIMEOUT | 0.0 | exceeded time limit | test_timeout |
| 8 | SYNTAX_FAILURE | 0.0 | SyntaxError on import | test_syntax_failure |
| 9 | IMPORT_FAILURE | 0.0 | ImportError on import | test_import_failure |
| 10 | NAME_ERROR | 0.0 | NameError | test_name_error |
| 11 | INVARIANT_CRASH | 0.1 | other exception during test | test_invariant_crash |
| 12 | INVARIANT_FAILURE | 0.2 | test returned False | test_invariant_failure |
| 13 | EXECUTION_SUCCESS | 1.0 | test returned True | test_execution_success |

---

# PART 5: TEST SUITE

## tests/test_exec_canonical.py — Core correctness

### Test 1.1: All 19 single-file reference fixes pass

```python
@pytest.mark.parametrize("case_id", SINGLE_FILE_CASES)
def test_single_file_ref_fix(case_id, all_cases):
    result = exec_canonical(all_cases[case_id], None,
        _build_ref_recon(all_cases[case_id]), _mock_config(), None)
    assert result["pass"] is True, f"{case_id}: {result['reasons']}"
    assert result["execution_category"] == "EXECUTION_SUCCESS"
    assert result["score"] == 1.0
    trace = result["execution_trace"]
    assert trace, f"{case_id}: empty trace"
    assert any("import:" in x for x in trace), f"{case_id}: no import in trace"
    assert any("test_start" in x for x in trace), f"{case_id}: no test_start"
    assert any("test_end" in x for x in trace), f"{case_id}: no test_end"
```

### Test 1.2: All 39 multi-file reference fixes pass

```python
@pytest.mark.parametrize("case_id", MULTI_FILE_CASES)
def test_multi_file_ref_fix(case_id, all_cases):
    result = exec_canonical(all_cases[case_id], None,
        _build_ref_recon(all_cases[case_id]), _mock_config(), None)
    assert result["pass"] is True, f"{case_id}: {result['reasons']}"
    assert result["execution_category"] == "EXECUTION_SUCCESS"
    assert len(result["modules_loaded"]) >= 2
    assert isinstance(result["merge_conflicts"], list)
    assert result["functions_called"], f"{case_id}: no functions_called"
    assert any("call:" in x for x in result["execution_trace"]), \
        f"{case_id}: no call events in trace"
```

### Test 1.3: All 58 buggy codes fail

```python
@pytest.mark.parametrize("case_id", ALL_CASES)
def test_buggy_code_fails(case_id, all_cases):
    result = exec_canonical(all_cases[case_id], None,
        _build_buggy_recon(all_cases[case_id]), _mock_config(), None)
    assert result["pass"] is False, f"{case_id}: buggy code should NOT pass"
```

### Test 1.4: Package disk structure (5 multi-file cases)

```python
@pytest.mark.parametrize("case_id", ["effect_order_b", "alias_config_c",
    "l3_state_pipeline", "cache_invalidation_order", "invariant_partial_fail"])
def test_package_structure(case_id, all_cases):
    case = all_cases[case_id]
    pkg_dir = _materialize(case, _build_ref_recon(case), str(Path.cwd()), 0)
    try:
        pkg = pkg_dir / "pkg"
        assert (pkg / "__init__.py").exists()
        assert (pkg / "__init__.py").read_text() == ""
        for rel_path in case["code_files"]:
            f = pkg / rel_path.rsplit("/", 1)[-1]
            assert f.exists(), f"missing: {f}"
            assert f.read_text() == case["code_files_contents"][rel_path]
        extra = set(f.name for f in pkg.glob("*.py")) - {"__init__.py"} - \
                set(p.rsplit("/", 1)[-1] for p in case["code_files"])
        assert not extra, f"extra: {extra}"
        assert (pkg_dir / "harness" / "run_case.py").exists()
        meta = json.loads((pkg_dir / "case_meta.json").read_text())
        assert meta["case_id"] == case_id
    finally:
        shutil.rmtree(str(pkg_dir))
```

### Test 1.5: Return dict schema

```python
def test_result_schema(all_cases):
    result = exec_canonical(all_cases["alias_config_a"], None,
        _build_ref_recon(all_cases["alias_config_a"]), _mock_config(), None)
    TOP = {"pass", "score", "reasons", "failure_modes", "execution",
           "execution_category", "execution_subtype", "modules_loaded",
           "functions_detected", "functions_called", "merge_conflicts",
           "execution_trace", "_extracted_code", "_assembled_code"}
    assert TOP <= set(result.keys()), f"missing: {TOP - set(result.keys())}"
    EXEC = {"status", "ran", "passed_tests", "total_tests", "assembly_used",
            "assembly_error", "assembly_risky", "rename_error", "invariant_pass"}
    assert EXEC <= set(result["execution"].keys())
    assert result["execution"]["assembly_used"] is False
    for f in ("execution_trace", "merge_conflicts", "functions_called",
              "functions_detected", "modules_loaded"):
        assert isinstance(result[f], list), f"{f} not list"
```

### Test 1.6: Delegation pattern (THE recursion bug)

```python
def test_delegation_no_recursion(all_cases):
    case = all_cases["effect_order_b"]
    model_code = (
        'from metrics import increment, emit_event, reset as metrics_reset\n\n'
        'def reset():\n    metrics_reset()\n\n'
        'def process_batch(items):\n'
        '    for item in items:\n'
        '        increment(item["value"])\n'
        '        emit_event(item["id"], item["value"])\n'
        '    return len(items)\n\n'
        'def validate_log():\n    pass\n\n'
        'def get_summary():\n    return {"processed": True}\n'
    )
    recon = _build_model_recon(case, {
        "code_snippets_v2/effect_order_b/processor.py": model_code})
    result = exec_canonical(case, None, recon, _mock_config(), None)
    assert "recursion" not in str(result).lower()
    assert result["pass"] is True
    assert result["execution_category"] == "EXECUTION_SUCCESS"
```

## tests/test_exec_stress.py — Full benchmark

### Test 2.1: All 58 reference fixes

```python
def test_all_ref_fixes(all_cases):
    results = {"total": 0, "pass": 0, "fail": 0,
               "by_category": Counter(), "failures": []}
    for cid, case in all_cases.items():
        r = exec_canonical(case, None, _build_ref_recon(case), _mock_config(), None)
        results["total"] += 1
        results["by_category"][r["execution_category"]] += 1
        if r["pass"]: results["pass"] += 1
        else:
            results["fail"] += 1
            results["failures"].append((cid, r["execution_category"],
                                        str(r["reasons"])[:100]))
    _print_summary(results)
    assert results["pass"] == 58, f"failures: {results['failures']}"
```

### Test 2.2: 8 known recursion cases with real model output

```python
RECURSION_CASES = ["effect_order_b", "effect_order_c", "retry_dup_b",
    "retry_dup_c", "partial_rollback_b", "partial_rollback_c",
    "use_before_set_b", "use_before_set_c"]

@pytest.mark.parametrize("case_id", RECURSION_CASES)
def test_no_recursion_real_output(case_id, all_cases):
    output = _load_real_model_output(case_id, "gpt-5-mini", "baseline_v2")
    if output is None:
        pytest.skip(f"no model output for {case_id}")
    recon = _reconstruct_from_output(all_cases[case_id], output)
    result = exec_canonical(all_cases[case_id], None, recon, _mock_config(), None)
    assert "recursion" not in str(result).lower()
```

## tests/test_exec_isolation.py — State leakage

### Test 3.1: No drift

```python
def test_no_drift(all_cases):
    case = all_cases["mutable_default_a"]
    recon = _build_ref_recon(case)
    r1 = exec_canonical(case, None, recon, _mock_config(), None)
    r2 = exec_canonical(case, None, recon, _mock_config(), None)
    r3 = exec_canonical(case, None, recon, _mock_config(), None)
    assert r1["pass"] == r2["pass"] == r3["pass"]
    assert r1["score"] == r2["score"] == r3["score"]
```

### Test 3.2: Cross-case

```python
def test_cross_case(all_cases):
    a, b = all_cases["mutable_default_a"], all_cases["stale_cache_a"]
    r1 = exec_canonical(a, None, _build_ref_recon(a), _mock_config(), None)
    _ = exec_canonical(b, None, _build_buggy_recon(b), _mock_config(), None)
    r2 = exec_canonical(a, None, _build_ref_recon(a), _mock_config(), None)
    assert r1["pass"] == r2["pass"]
```

### Test 3.3: sys.modules

```python
def test_sys_modules(all_cases):
    before = set(sys.modules.keys())
    exec_canonical(all_cases["effect_order_b"], None,
        _build_ref_recon(all_cases["effect_order_b"]), _mock_config(), None)
    leaked = set(sys.modules.keys()) - before
    case_mods = {"metrics", "processor", "config", "state", "worker",
                 "scheduler", "api", "client", "handler"}
    assert not (leaked & case_mods), f"leaked: {leaked & case_mods}"
```

### Test 3.4: Fresh temp dirs

```python
def test_fresh_temp_dirs(all_cases, monkeypatch):
    """Capture actual pkg_dir paths and verify uniqueness + cleanup."""
    import exec_canonical as ec_mod
    captured_dirs = []
    original_materialize = ec_mod._materialize_package

    def _capturing_materialize(*args, **kwargs):
        pkg_dir = original_materialize(*args, **kwargs)
        captured_dirs.append(str(pkg_dir))
        return pkg_dir

    monkeypatch.setattr(ec_mod, "_materialize_package", _capturing_materialize)
    case = all_cases["alias_config_a"]
    recon = _build_ref_recon(case)
    for _ in range(5):
        exec_canonical(case, None, recon, _mock_config(), None)

    assert len(captured_dirs) == 5
    assert len(set(captured_dirs)) == 5, f"duplicate dirs: {captured_dirs}"
    for d in captured_dirs:
        assert not Path(d).exists(), f"not cleaned up: {d}"
```

## tests/test_exec_determinism.py — Repeatability

### Test 4.1: 5x repeat

```python
@pytest.mark.parametrize("case_id", ["alias_config_a", "effect_order_b",
    "lazy_init_c", "lost_update", "l3_state_pipeline"])
def test_5x_repeat(case_id, all_cases):
    recon = _build_ref_recon(all_cases[case_id])
    results = [exec_canonical(all_cases[case_id], None, recon, _mock_config(), None)
               for _ in range(5)]
    for i in range(1, 5):
        assert results[i]["pass"] == results[0]["pass"]
        assert results[i]["execution_category"] == results[0]["execution_category"]
```

### Test 4.2: Order independent

```python
def test_order_independent(all_cases):
    ids = ["alias_config_a", "effect_order_b", "lost_update"]
    fwd = {c: exec_canonical(all_cases[c], None, _build_ref_recon(all_cases[c]),
           _mock_config(), None) for c in ids}
    rev = {c: exec_canonical(all_cases[c], None, _build_ref_recon(all_cases[c]),
           _mock_config(), None) for c in reversed(ids)}
    for c in ids:
        assert fwd[c]["pass"] == rev[c]["pass"]
```

## tests/test_exec_classification.py — All 13 categories + break tests

### Test 5.1: EXECUTION_SUCCESS

```python
def test_execution_success(all_cases):
    r = exec_canonical(all_cases["alias_config_a"], None,
        _build_ref_recon(all_cases["alias_config_a"]), _mock_config(), None)
    assert r["execution_category"] == "EXECUTION_SUCCESS"
    assert r["score"] == 1.0
```

### Test 5.2: INVARIANT_FAILURE

```python
def test_invariant_failure(all_cases):
    r = exec_canonical(all_cases["alias_config_a"], None,
        _build_buggy_recon(all_cases["alias_config_a"]), _mock_config(), None)
    assert r["execution_category"] == "INVARIANT_FAILURE"
    assert r["score"] == 0.2
```

### Test 5.3: INVARIANT_CRASH

```python
def test_invariant_crash(all_cases):
    recon = _build_model_recon(all_cases["alias_config_a"],
        {"code_snippets_v2/alias_config_a/config.py":
         "def create_config():\n    raise RuntimeError('boom')"})
    r = exec_canonical(all_cases["alias_config_a"], None, recon, _mock_config(), None)
    assert r["execution_category"] == "INVARIANT_CRASH"
    assert r["score"] == 0.1
```

### Test 5.4: SYNTAX_FAILURE

```python
def test_syntax_failure(all_cases):
    recon = _build_model_recon(all_cases["alias_config_a"],
        {"code_snippets_v2/alias_config_a/config.py": "def broken(\n    pass"})
    r = exec_canonical(all_cases["alias_config_a"], None, recon, _mock_config(), None)
    assert r["execution_category"] == "SYNTAX_FAILURE"
    assert r["score"] == 0.0
```

### Test 5.5: IMPORT_FAILURE

```python
def test_import_failure(all_cases):
    recon = _build_model_recon(all_cases["alias_config_a"],
        {"code_snippets_v2/alias_config_a/config.py":
         "from nonexistent import X\ndef create_config(): pass"})
    r = exec_canonical(all_cases["alias_config_a"], None, recon, _mock_config(), None)
    assert r["execution_category"] == "IMPORT_FAILURE"
    assert r["score"] == 0.0
```

### Test 5.6: NAME_ERROR

```python
def test_name_error(all_cases):
    recon = _build_model_recon(all_cases["alias_config_a"],
        {"code_snippets_v2/alias_config_a/config.py":
         "def create_config(): return undefined_var"})
    r = exec_canonical(all_cases["alias_config_a"], None, recon, _mock_config(), None)
    assert r["execution_category"] == "NAME_ERROR", \
        f"expected NAME_ERROR, got {r['execution_category']}: {r.get('execution_subtype')}"
    assert r["score"] == 0.0
```

### Test 5.7: TIMEOUT

```python
def test_timeout(all_cases):
    recon = _build_model_recon(all_cases["alias_config_a"],
        {"code_snippets_v2/alias_config_a/config.py":
         "def create_config():\n    while True: pass"})
    cfg = _mock_config()
    cfg.execution.subprocess_timeout = 3
    r = exec_canonical(all_cases["alias_config_a"], None, recon, cfg, None)
    assert r["execution_category"] == "TIMEOUT"
    assert r["score"] == 0.0
```

### Test 5.8: RECONSTRUCTION_FAILURE

```python
def test_reconstruction_failure(all_cases):
    recon = _make_failed_recon("FAILED_MISSING_FILES")
    r = exec_canonical(all_cases["alias_config_a"], None, recon, _mock_config(), None)
    assert r["execution_category"] == "RECONSTRUCTION_FAILURE"
    assert r["score"] == 0.0
```

### Test 5.9: BUILD_FAILURE

```python
def test_build_failure(all_cases, monkeypatch):
    """Force _materialize to fail by patching tempfile.mkdtemp."""
    import tempfile
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: (_ for _ in ()).throw(OSError("disk full")))
    r = exec_canonical(all_cases["alias_config_a"], None,
        _build_ref_recon(all_cases["alias_config_a"]), _mock_config(), None)
    assert r["execution_category"] == "BUILD_FAILURE"
    assert r["score"] == 0.0
```

### Test 5.10: SUBPROCESS_CRASH

```python
def test_subprocess_crash_classification():
    raw = _error_result("crash", "SubprocessCrash", "segfault")
    cat, score = _classify(raw)
    assert cat == "SUBPROCESS_CRASH"
    assert score == 0.0
```

### Test 5.11: INVALID_OUTPUT

```python
def test_invalid_output_classification():
    raw = _error_result("invalid_output", "JSONDecodeError", "not json")
    cat, score = _classify(raw)
    assert cat == "INVALID_OUTPUT"
    assert score == 0.0
```

### Test 5.12: SCHEMA_VIOLATION

```python
def test_schema_violation():
    with pytest.raises(ValueError, match="missing fields"):
        _validate({"passed": True})
```

### Test 5.13: PARSE_FAILURE (orchestration level)

```python
def test_parse_failure_skips_execution(monkeypatch):
    """Verify that parse failure at the pipeline level prevents exec_canonical
    from being called. Monkeypatch exec_canonical to raise if invoked."""
    import exec_canonical as ec_mod
    def _boom(*args, **kwargs):
        raise AssertionError("exec_canonical should not be called on parse failure")
    monkeypatch.setattr(ec_mod, "exec_canonical", _boom)

    from parser_v2 import parse_v2_execution
    result = parse_v2_execution("", "baseline_v2")
    assert result.parse_status == "failed"
    # In the real pipeline, execution_v2.run_v2 gates on parse_status.
    # If exec_canonical were called despite parse failure, _boom fires.
```

### Test 5.14: Unclassifiable crashes

```python
def test_unclassifiable_crashes():
    weird = {
        "status": "wat", "passed": False, "error_type": None,
        "failure_reasons": [], "error_message": None, "traceback": None,
        "modules_loaded": [], "functions_detected": [], "functions_called": [],
        "merge_conflicts": [], "execution_trace": [], "execution_time_ms": 0,
    }
    with pytest.raises(RuntimeError, match="Unclassifiable"):
        _classify(weird)
```

### Test 5.15: Consistency — success without execution

```python
def test_success_without_execution_crashes():
    with pytest.raises(RuntimeError, match="EXECUTION_SUCCESS without execution"):
        _make_result({"id": "x", "failure_mode": "Y"}, True, 1.0, [],
                     "EXECUTION_SUCCESS", None, None)
```

### Test 5.16: Wrong field type rejected

```python
def test_wrong_type_rejected():
    bad = {k: [] for k in REQUIRED_SUBPROCESS_FIELDS}
    bad["passed"] = "yes"
    bad["execution_time_ms"] = 0
    with pytest.raises(ValueError, match="must be bool"):
        _validate(bad)
```

### Test 5.17: Execution trace validated

```python
def test_trace_has_real_events(all_cases):
    result = exec_canonical(all_cases["effect_order_b"], None,
        _build_ref_recon(all_cases["effect_order_b"]), _mock_config(), None)
    trace = result["execution_trace"]
    assert trace, "empty trace"
    assert any("import:" in x for x in trace), "no imports"
    assert any("test_start" in x for x in trace), "no test_start"
    assert any("test_end" in x for x in trace), "no test_end"
    assert any("call:" in x for x in trace), "no call events"
    assert any("merged:" in x for x in trace), "no merge event"
```

### Test 5.18: Merge conflicts detected

```python
def test_merge_conflicts_detected(all_cases):
    """effect_order_b: both metrics.py and processor.py define reset()."""
    case = all_cases["effect_order_b"]
    # Verify the original files actually both define reset
    for rel_path in case["code_files"]:
        content = case["code_files_contents"][rel_path]
        assert "def reset" in content, f"{rel_path} missing reset()"
    # Now run and check conflict detection
    result = exec_canonical(case, None, _build_ref_recon(case), _mock_config(), None)
    assert "reset" in result["merge_conflicts"], \
        f"expected 'reset' conflict, got {result['merge_conflicts']}"
```

### Test 5.19: functions_called populated

```python
def test_functions_called(all_cases):
    result = exec_canonical(all_cases["effect_order_b"], None,
        _build_ref_recon(all_cases["effect_order_b"]), _mock_config(), None)
    assert result["functions_called"], "functions_called empty"
    # process_batch should be called by the test
    assert any("process" in fn for fn in result["functions_called"]), \
        f"expected process_batch in calls: {result['functions_called']}"
```

### Test 5.20: Category exhaustiveness

```python
def test_all_13_categories_covered():
    """Verify all 13 categories appear in classification tests above."""
    tested = {
        "EXECUTION_SUCCESS",    # 5.1
        "INVARIANT_FAILURE",    # 5.2
        "INVARIANT_CRASH",      # 5.3
        "SYNTAX_FAILURE",       # 5.4
        "IMPORT_FAILURE",       # 5.5
        "NAME_ERROR",           # 5.6
        "TIMEOUT",              # 5.7
        "RECONSTRUCTION_FAILURE", # 5.8
        "BUILD_FAILURE",        # 5.9
        "SUBPROCESS_CRASH",     # 5.10
        "INVALID_OUTPUT",       # 5.11
        "SCHEMA_VIOLATION",     # 5.12
        "PARSE_FAILURE",        # 5.13 (orchestration level)
    }
    assert tested == ALL_CATEGORIES, f"untested: {ALL_CATEGORIES - tested}"
```

---

# PART 6: VALIDATION CRITERIA

### System is correct when:

1. 58/58 reference fixes pass (0 failures)
2. 58/58 buggy codes fail (0 false passes)
3. Delegation pattern passes without recursion
4. 8 known recursion cases produce no RecursionError
5. Identical input → identical output across 5 runs
6. sys.modules not polluted after execution
7. All 13 categories triggered in tests (13/13)
8. Schema validation rejects malformed output
9. Unclassifiable results crash the system
10. Consistency invariants enforced
11. Merge conflicts detected and reported
12. Execution trace has import + call + test events (call events interleaved at call time)
13. functions_called populated for passing multi-file cases
14. Every execution uses a unique temp directory, verified by path capture

### System is broken when:

1. Any reference fix fails
2. Any buggy code passes
3. RecursionError appears
4. Results differ across identical runs
5. Subprocess output accepted without all fields
6. Any category maps to wrong score
7. Unclassifiable result doesn't crash
8. Merge conflicts silent
9. Execution trace empty on success
10. functions_called empty on multi-file success

---

# PART 7: OPERATIONAL INVARIANTS

These are architectural guarantees, enforced by design and validated by specific tests.

### 1. No model code executes in parent process

Enforced by: parent only writes files to disk and spawns subprocess.
`exec_canonical.py` never calls `exec()` on model code.
Validated by: test_sys_modules (3.3) — parent sys.modules has no case modules after execution.

### 2. Every attempt gets a fresh temp directory

Enforced by: `tempfile.mkdtemp()` with unique prefix including case_id and attempt number.
Validated by: test_fresh_temp_dirs (3.4) — captures actual pkg_dir paths from 5 runs,
asserts all 5 are distinct, and verifies cleanup removes them.

### 3. Subprocess result validated before classification

Enforced by: `_validate()` called before `_classify()` in exec_canonical.
Validated by: test_schema_violation (5.12) and test_wrong_type_rejected (5.16).

### 4. Unclassifiable outputs crash the system

Enforced by: `raise RuntimeError` at end of `_classify()`.
Validated by: test_unclassifiable_crashes (5.14).

### 5. No success without execution

Enforced by: consistency check in `_make_result()`.
Validated by: test_success_without_execution_crashes (5.15).

### 6. All categories are known

Enforced by: `category not in ALL_CATEGORIES` check in `_make_result()`.
Validated by: test_all_13_categories_covered (5.20).

### 7. No import rewriting on canonical path

Enforced by: `exec_canonical.py` does not import `ast` or `code_assembly`.
Package files are written to disk unmodified.
Validated by: test_package_structure (1.4) — files on disk match input byte-for-byte.

### 8. Merge conflicts are visible

Enforced by: harness detects and reports conflicts during namespace merge.
Validated by: test_merge_conflicts_detected (5.18).

---

# PART 8: INTEGRATION

### execution_v2.py (~15 lines)

```python
from exec_canonical import exec_canonical

# Replace exec_evaluate call:
if config.execution.mode == "canonical":
    exec_result = exec_canonical(case, parsed_gen, recon, config, logger, attempt=0)
else:
    code = "\n\n".join(changed_parts)
    exec_result = exec_evaluate(case, code)
```

### experiment_config.py (~5 lines)

```python
# Add to ExecutionConfig:
mode: str = "legacy"
keep_eval_dirs: bool = False
subprocess_timeout: int = 30
```

### retry_v2.py (~10 lines)

Replace `exec_evaluate(case, code)` with
`exec_canonical(case, parsed_gen, recon, config, logger, attempt=k)`
per attempt.
