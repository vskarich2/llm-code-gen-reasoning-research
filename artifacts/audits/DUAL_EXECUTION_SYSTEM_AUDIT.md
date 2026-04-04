# Dual Execution System — Implementation Audit

**Date:** 2026-03-30
**Scope:** Parallel module-based execution + disagreement classification for measuring assembly-induced failures

---

## 1. System Overview

The dual execution system runs every evaluation case through TWO independent execution paths:

1. **Canonical (concat)** — the existing `CodeAssembler` → `load_module_from_code` → `exec` pipeline. This is ground truth for all pass/fail metrics.
2. **Module (side-channel)** — real Python modules registered in `sys.modules` with native import resolution. This is comparison-only.

After both run, a **disagreement classifier** determines WHY they disagree, categorizing each case as model failure vs infrastructure failure.

### Architecture

```
evaluator.py:evaluate_output()
  │
  ├─ Step 1: exec_evaluate(case, code)          ← CANONICAL (unchanged)
  │    └─ CodeAssembler → concat → exec → test
  │    └─ Returns: pass/fail + reasons + execution details
  │
  ├─ Step 1.5: run_module_execution(case, code)  ← SIDE-CHANNEL (new)
  │    └─ Register modules in sys.modules
  │    └─ 2-pass exec (handle dependencies)
  │    └─ Run same test function
  │    └─ Clean sys.modules
  │    └─ Returns: ModuleExecResult
  │
  ├─ compare_results(concat_pass, module_result)  ← COMPARISON (new)
  │    └─ agreement / concat_only_pass / module_only_pass / etc.
  │
  ├─ classify_disagreement(concat, module)        ← CLASSIFICATION (new)
  │    └─ Deterministic root cause analysis
  │    └─ Returns: DisagreementResult (type, subtype, confidence, evidence)
  │
  └─ result["dual_execution"] = {...}             ← LOGGED (new)
```

### Invariants

- Canonical pipeline is untouched — all pass/fail, LEG, category metrics use concat only
- Module execution never modifies canonical outputs
- Zero shared state between executions (concat runs first)
- Module execution wrapped in try/except — can never crash canonical pipeline

---

## 2. Files Created

### `module_exec.py` (234 lines)

The module-based execution engine. Runs model code as real Python modules.

| Function | Lines | Purpose |
|---|---|---|
| `run_module_execution(case, model_code, test_fn)` | 21 | Main entry — dispatches to single or multi-file |
| `_exec_single_file(model_code, case_id, test_fn, result)` | 15 | Direct exec for 1-file cases |
| `_exec_multi_file(model_code, case, ..., test_fn, result)` | 128 | Full module system for multi-file cases |
| `_run_test(mod, test_fn, result)` | 12 | Run test function on module, record results |
| `compare_results(concat_pass, module_result)` | 16 | Structured comparison dict |

**`ModuleExecResult` dataclass:**
- `executed`, `test_ran`, `test_passed`, `test_reasons`
- `error_type`, `error_message`, `error_traceback`
- `modules_loaded`, `load_passes`, `cleanup_done`

**Multi-file execution pipeline:**
1. Build module map (original files + model override for target module)
2. Save and clean `sys.modules` for case module names
3. Create empty module shells and register in `sys.modules`
4. Two-pass execution (pass 1: exec all, pass 2: retry failures)
5. Merge all module namespaces for test compatibility
6. Run test function
7. Cleanup: remove case modules from `sys.modules`, restore saved

**State isolation:**
- `sys.modules` is saved before and restored after every execution
- Each case runs in a fresh module namespace
- No leakage verified by tests (`test_no_sys_modules_leakage`, `test_consecutive_runs_isolated`)

### `disagreement_classifier.py` (258 lines)

Deterministic classification of dual execution disagreements.

| Function | Lines | Purpose |
|---|---|---|
| `classify_disagreement(concat_result, module_result)` | 148 | Main classifier — pure function, strict priority |
| `_extract_signals(concat_result, module_result)` | 24 | Extract diagnostic signals from both results |
| `_extract_keywords(text)` | 10 | Match error text against known patterns |
| `_extract_error_type(error)` | 11 | Extract exception class name from error string |

**`DisagreementResult` dataclass:**
- `type` — primary classification (exactly one, mutually exclusive)
- `subtype` — refinement within type
- `confidence` — 0.0 to 1.0, deterministic scoring
- `evidence` — key signals used for classification

**Classification types (strict priority order):**

| Priority | Type | Condition | Subtypes |
|---|---|---|---|
| 1 | `test_inconsistency` | Different test counts | early_failure, partial_execution, test_harness_mismatch |
| 2 | `agreement` | Same pass + same tests_passed | (none) |
| 3 | `assembly_failure_likely` | Concat fails, module passes | import_resolution_failure, missing_symbol_after_strip, namespace_binding_failure, unclassified_concat_failure |
| 4 | `module_execution_failure` | Concat passes, module fails | circular_import_failure, module_init_order_failure, unclassified_module_failure |
| 5 | `semantic_divergence` | Both pass, different results | state_order_difference, test_result_difference |
| 6 | `consistent_failure` | Both fail, different results | same_error, different_error |
| 7 | `unknown` | Nothing else matched | (always includes raw evidence) |

**Signal extraction keywords:**
- Import-related: ModuleNotFoundError, ImportError, "no module named", "cannot import name"
- Name-related: NameError, "is not defined"
- Attribute-related: AttributeError, "has no attribute"
- Circular: "circular", "partially initialized"

**Confidence scoring:**
- 1.0 — exact pattern match (e.g., clear ModuleNotFoundError in concat, module passes)
- 0.8 — strong signal match (NameError heuristic)
- 0.5 — weak/unclassified match
- 0.0 — unknown

---

## 3. Files Modified

### `evaluator.py`

**Step 1.5 added** (lines ~228-265) between exec_evaluate and llm_classify:

```python
# Step 1.5: Dual execution — module-based comparison (side-channel only)
try:
    mod_result = run_module_execution(case, code, test_fn)
    dual_comparison = compare_results(exec_pass, mod_result)
    disagreement = classify_disagreement(concat_for_classify, module_for_classify)
    result["dual_execution"] = {
        **dual_comparison,
        "disagreement_type": disagreement.type,
        "disagreement_subtype": disagreement.subtype,
        "disagreement_confidence": disagreement.confidence,
        "disagreement_evidence": disagreement.evidence,
    }
except Exception:
    pass  # NEVER crash canonical pipeline
```

The dual execution is fully wrapped in try/except. If module execution crashes, the canonical pipeline continues unaffected. The `result["dual_execution"]` field is only present when dual execution succeeds.

---

## 4. How Results Are Logged

### Event-level logging (events.jsonl)

The `dual_execution` dict is propagated through the evaluation result into whatever logging the downstream pipeline uses. When `_emit_metrics_event` writes to events.jsonl, the dual_execution field is available in the `ev` dict.

**Example event with dual execution:**
```json
{
  "case_id": "effect_order_b",
  "condition": "baseline",
  "pass": true,
  "dual_execution": {
    "agreement": true,
    "both_pass": true,
    "both_fail": false,
    "concat_only_pass": false,
    "module_only_pass": false,
    "module_executed": true,
    "module_test_ran": true,
    "module_error_type": "",
    "module_error_message": "",
    "module_load_passes": 1,
    "disagreement_type": "agreement",
    "disagreement_subtype": null,
    "disagreement_confidence": 1.0,
    "disagreement_evidence": {"pass": true, "tests_passed": 1}
  }
}
```

**Example event with disagreement:**
```json
{
  "case_id": "effect_order_c",
  "condition": "leg_reduction",
  "pass": false,
  "dual_execution": {
    "agreement": false,
    "both_pass": false,
    "both_fail": false,
    "concat_only_pass": false,
    "module_only_pass": true,
    "module_executed": true,
    "module_test_ran": true,
    "module_error_type": "",
    "module_error_message": "",
    "module_load_passes": 2,
    "disagreement_type": "assembly_failure_likely",
    "disagreement_subtype": "import_resolution_failure",
    "disagreement_confidence": 1.0,
    "disagreement_evidence": {
      "concat_error_type": "NameError",
      "keywords": ["import", "is not defined"]
    }
  }
}
```

### Run-level logging (run.jsonl)

The `dual_execution` dict is part of the evaluation result that flows into the run.jsonl audit block.

### Console logging

Mismatches are logged at INFO level:
```
DUAL EXEC MISMATCH: effect_order_c — type=assembly_failure_likely subtype=import_resolution_failure concat=False module=True
```

---

## 5. How to Analyze Results

After an ablation run, the dual execution data can be analyzed by:

1. **Counting agreement rate:**
```python
events = [json.loads(l) for l in open("events.jsonl")]
dual = [e["dual_execution"] for e in events if "dual_execution" in e]
agreement = sum(1 for d in dual if d["agreement"]) / len(dual)
```

2. **Finding assembly-induced failures:**
```python
assembly_bugs = [e for e in events
                 if e.get("dual_execution", {}).get("disagreement_type") == "assembly_failure_likely"]
```

3. **Comparing pass rates:**
```python
concat_pass = sum(1 for e in events if e["pass"]) / len(events)
module_pass = sum(1 for e in events if e.get("dual_execution", {}).get("module_only_pass") or e["pass"]) / len(events)
```

4. **Breakdown by disagreement type:**
```python
from collections import Counter
types = Counter(e.get("dual_execution", {}).get("disagreement_type") for e in events)
```

---

## 6. Tests

| Test File | Tests | Covers |
|---|---|---|
| `test_dual_execution.py` | 13 | Single/multi-file execution, alias imports, module-qualified imports, circular imports, comparison logic, state isolation |
| `test_disagreement_classifier.py` | 25 | All 7 classification types, subtypes, priority order, confidence scoring, determinism |
| **Total** | **38** | |

---

## 7. What This Does NOT Do

- Does NOT change pass/fail decisions — canonical concat is always ground truth
- Does NOT replace CodeAssembler — assembly still runs for every case
- Does NOT modify any existing metric — LEG, category, reasoning_correct all unchanged
- Does NOT add latency to critical path — module execution runs after canonical, and any failure is swallowed
- Does NOT persist module state — sys.modules cleaned after every execution

---

## 8. What This Enables

1. **Quantify assembly-induced failures** — every `module_only_pass` case is a case the model got right but our infrastructure scored wrong
2. **Validate assembly fixes** — when CodeAssembler is improved, the disagreement rate should drop
3. **Compare execution models** — if module execution shows higher pass rate on multi-file cases, it validates the hybrid migration plan
4. **Identify semantic divergence** — cases where both pass but produce different outputs reveal where concatenation alters Python semantics
5. **Build evidence for migration** — Phase 0 of the concat→module migration plan is exactly this: run both, compare, log discrepancies
