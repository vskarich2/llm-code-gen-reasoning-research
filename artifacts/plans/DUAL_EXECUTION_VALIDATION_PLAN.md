# Dual Execution Validation Plan — Stress Testing + Metrics Integration

**Date:** 2026-03-30
**Purpose:** Break the dual execution system, quantify infrastructure error, connect to LEG measurement

---

## 1. STRESS TESTING PLAN

### 1.1 Import Resolution Stress

**Target:** Expose cases where concat assembly and module execution disagree on import handling.

| Test ID | Pattern | Expected Behavior | Failure Detection |
|---|---|---|---|
| IMP-01 | 3-level chain: A→B→C→D (each imports next) | Module: pass (2-pass resolves). Concat: depends on assembly. | module_only_pass = assembly bug |
| IMP-02 | Circular: A imports B, B imports A | Module: 2-pass handles. Concat: flattened, no issue. | Track which system fails |
| IMP-03 | Mixed: `import A` + `from B import f` + `A.g()` | Module: native. Concat: namespace synthesis + from-import strip. | Disagreement on A.g() |
| IMP-04 | Alias chain: `import A as X; from A import f as g; X.h(); g()` | Module: native. Concat: rename g→f + namespace for X. | Verify both produce same result |
| IMP-05 | Partial override: model modifies 1 of 3 files | Module: override in sys.modules. Concat: append model code. | Check override semantics match |
| IMP-06 | Diamond dependency: A→B, A→C, B→D, C→D | Module: D loaded once. Concat: D content duplicated. | State duplication bugs |
| IMP-07 | Model adds NEW import not in originals: `import json` inside function | Both should work. | Verify no false strip |
| IMP-08 | Model writes `from __future__ import annotations` | Must be first statement. Concat may break ordering. | SyntaxError in concat |

**Implementation:**
```python
# tests/stress/test_import_stress.py
# For each test: build synthetic case, run both paths, compare
# Measure: agreement_rate, disagreement_type distribution
```

### 1.2 sys.modules Isolation Stress

**Target:** Prove no state leakage between consecutive module executions.

| Test ID | Scenario | Detection Method |
|---|---|---|
| ISO-01 | Run same case 10x, check pass rate = constant | variance(pass) must be 0 |
| ISO-02 | Run case A (sets global), then case B (reads global) | B must not see A's state |
| ISO-03 | Case with module-level `_cache = {}` — run twice | Second run must not see first run's cache |
| ISO-04 | Run case A that imports `metrics`, then case B that also imports `metrics` | B gets fresh metrics module |
| ISO-05 | Module that modifies `sys.path` | sys.path must be restored |
| ISO-06 | 100 consecutive runs of random cases | No sys.modules growth |

**Implementation:**
```python
# tests/stress/test_isolation_stress.py
def test_repeated_execution_deterministic():
    results = [run_module_execution(case, code, test_fn) for _ in range(10)]
    assert all(r.test_passed == results[0].test_passed for r in results)

def test_no_sys_modules_growth():
    baseline = len(sys.modules)
    for case in all_cases[:20]:
        run_module_execution(case, ...)
    assert len(sys.modules) <= baseline + 5  # small tolerance
```

### 1.3 Execution Order / State Stress

**Target:** Find cases where concatenation order vs module init order produces different results.

| Test ID | Scenario | Expected |
|---|---|---|
| ORD-01 | Module A sets `X=0`, module B does `X+=1`, test checks X | Concat: X=1 (B after A). Module: B's X is module-local. |
| ORD-02 | Module A has side effect on import (prints, modifies global) | Concat: runs once. Module: runs in 2-pass (may run twice). |
| ORD-03 | Model code depends on function defined in original's module scope | Concat: last-def-wins. Module: model overrides module dict. |

**Key question:** How many real benchmark cases have execution-order-sensitive behavior?

### 1.4 Disagreement Classifier Stress

**Target:** Feed adversarial inputs to the classifier and verify stability.

| Test ID | Input | Expected Classification |
|---|---|---|
| CLS-01 | Nested exception: `RuntimeError` wrapping `ImportError` | assembly_failure_likely (inner ImportError) |
| CLS-02 | Error message containing "import" but is `ValueError` | NOT assembly_failure (check error type, not just keywords) |
| CLS-03 | Both fail, concat with NameError, module with ImportError | consistent_failure/different_error |
| CLS-04 | Partial test: concat runs 2 tests, module runs 1 | test_inconsistency |
| CLS-05 | Empty error strings, both fail | consistent_failure (both fail, no distinguishing info) |
| CLS-06 | Very long traceback (>10KB) | Must not crash or slow down |
| CLS-07 | Unicode in error messages | Must not crash |
| CLS-08 | Same case, 100 runs → must produce identical classification | Determinism proof |

### 1.5 Non-Determinism Stress

**Target:** Quantify variance in both execution paths across repeated runs.

**Method:**
```python
for case in all_58_cases:
    for trial in range(5):
        concat_result = exec_evaluate(case, code)
        module_result = run_module_execution(case, code, test_fn)
        record(case, trial, concat_result["pass"], module_result.test_passed)

# Compute:
#   per-case variance in concat pass rate
#   per-case variance in module pass rate
#   per-case variance in agreement
```

**Expected:** Temperature=0.0 → model output is deterministic per case. Execution should be fully deterministic. Any variance = state leakage or ordering bug.

### 1.6 Scale Stress

**Target:** Full 58-case × 3-model × 2-condition × 5-trial run with dual execution enabled.

**Measure:**
- Total runtime overhead from dual execution (expected: <20% since module exec is simple)
- Agreement rate per model
- Assembly failure rate per model
- Disagreement type distribution per condition

---

## 2. METRICS DESIGN

### 2.1 Core Dual Execution Metrics

| Metric | Formula | Interpretation |
|---|---|---|
| `agreement_rate` | `Σ(agreement) / N` | How often concat and module agree |
| `assembly_failure_rate` | `Σ(concat_fail AND module_pass) / N` | Infrastructure-induced false failures |
| `module_failure_rate` | `Σ(concat_pass AND module_fail) / N` | Cases where module execution adds failure |
| `semantic_divergence_rate` | `Σ(both_pass AND outputs_differ) / N` | Behavioral difference between execution models |

### 2.2 LEG Adjustment

| Metric | Formula | Interpretation |
|---|---|---|
| `LEG_raw` | `Σ(reasoning_correct AND concat_fail) / N_evaluated` | Standard LEG — includes infra errors |
| `LEG_adjusted` | `Σ(reasoning_correct AND concat_fail AND module_fail) / N_evaluated` | LEG after removing assembly bugs |
| `LEG_infrastructure` | `LEG_raw - LEG_adjusted` | Infrastructure contribution to LEG |
| `assembly_bias` | `LEG_infrastructure / LEG_raw` | What fraction of LEG is infrastructure error |

**Critical insight:** If `assembly_bias > 0.1` (>10% of LEG is infrastructure), the benchmark conclusions about model reasoning quality are compromised.

### 2.3 Confidence-Weighted Assembly Error Rate

```python
weighted_assembly_error = Σ(confidence_i * is_assembly_failure_i) / N
```

Where `confidence_i` comes from the disagreement classifier. This down-weights uncertain classifications.

### 2.4 Per-Dimension Metrics

Break down all of the above by:
- **model** (gpt-5-mini, gpt-4o-mini, gpt-4.1-nano)
- **condition** (baseline, leg_reduction)
- **family** (alias_config, effect_order, etc.)
- **difficulty** (A, B, C, single)
- **file count** (1-file vs 2-file vs 3-file)

**Hypothesis to test:** Assembly failure rate should increase with file count (more imports to handle).

---

## 3. METRICS INTEGRATION

### 3.1 Where Metrics Are Computed

The canonical metrics pipeline is `live_metrics.py:compute_metrics()`. This is where the new dual execution metrics should be added.

### 3.2 Fields to Add to `compute_metrics()`

```python
# After existing metrics computation:

# Dual execution metrics
dual_events = [e for e in events if "dual_execution" in e]
n_dual = len(dual_events)

if n_dual > 0:
    m["dual_execution"] = {
        "n": n_dual,
        "agreement_rate": Σ(agreement) / n_dual,
        "assembly_failure_rate": Σ(concat_fail AND module_pass) / n_dual,
        "module_failure_rate": Σ(concat_pass AND module_fail) / n_dual,
        "semantic_divergence_rate": Σ(both_pass AND disagreement_type=="semantic_divergence") / n_dual,
        "disagreement_type_distribution": Counter(disagreement_type),
    }

    # LEG adjustment (requires reasoning_correct)
    evaluated = [e for e in dual_events if e.get("reasoning_correct") is not None]
    if evaluated:
        leg_raw = Σ(rc==True AND pass==False) / len(evaluated)
        leg_adjusted = Σ(rc==True AND pass==False AND NOT module_only_pass) / len(evaluated)
        m["dual_execution"]["LEG_raw"] = leg_raw
        m["dual_execution"]["LEG_adjusted"] = leg_adjusted
        m["dual_execution"]["LEG_infrastructure"] = leg_raw - leg_adjusted
        m["dual_execution"]["assembly_bias"] = (leg_raw - leg_adjusted) / leg_raw if leg_raw > 0 else 0
```

### 3.3 Dashboard Integration

Add new section to `write_dashboard()`:

```
──────────────────────────────────────────────────────────────────────
  S8: DUAL EXECUTION (infrastructure vs model failure)
──────────────────────────────────────────────────────────────────────
  Agreement rate:        95.2%
  Assembly failure rate:  3.1%  (concat fails, module passes)
  Module failure rate:    1.7%  (concat passes, module fails)

  LEG raw:              18.9%
  LEG adjusted:         17.5%  (removes assembly-induced LEG)
  Infrastructure bias:   7.4%  of LEG is infrastructure error

  Disagreement types:
    assembly_failure_likely:    18
    module_execution_failure:   10
    semantic_divergence:         2
    consistent_failure:          5
```

### 3.4 Events Schema Extension

No schema change needed — `dual_execution` is already a dict field in the result. It flows through `_emit_metrics_event` into events.jsonl. The metrics computation reads it from there.

---

## 4. IMPLEMENTATION PLAN

### 4.1 Files to Create

| File | Purpose | Priority |
|---|---|---|
| `tests/stress/test_import_stress.py` | Import resolution stress tests (IMP-01 through IMP-08) | HIGH |
| `tests/stress/test_isolation_stress.py` | sys.modules isolation tests (ISO-01 through ISO-06) | HIGH |
| `tests/stress/test_classifier_stress.py` | Adversarial classifier inputs (CLS-01 through CLS-08) | MEDIUM |
| `tests/stress/test_nondeterminism.py` | Repeated execution variance measurement | MEDIUM |
| `scripts/run_dual_execution_analysis.py` | Full-scale dual execution analysis script | HIGH |

### 4.2 Files to Modify

| File | Change | Priority |
|---|---|---|
| `live_metrics.py:compute_metrics()` | Add dual execution metrics computation | HIGH |
| `live_metrics.py:write_dashboard()` | Add S8 dashboard section | HIGH |
| `execution.py:_emit_metrics_event()` | Propagate dual_execution fields to events.jsonl | HIGH |

### 4.3 Functions to Add

```python
# live_metrics.py
def _compute_dual_execution_metrics(events: list[dict]) -> dict:
    """Compute all dual execution metrics from events with dual_execution field."""

def _compute_leg_adjusted(events: list[dict]) -> dict:
    """Compute LEG_raw, LEG_adjusted, and assembly_bias."""

# scripts/run_dual_execution_analysis.py
def run_analysis(run_dirs: list[Path]) -> dict:
    """Load events, compute dual metrics, produce report."""

def detect_nondeterminism(events: list[dict]) -> dict:
    """Compute per-case variance in dual execution results across trials."""
```

### 4.4 Integration Sequence

1. **Phase 1:** Add dual execution metrics to `compute_metrics()` and dashboard
2. **Phase 2:** Implement stress tests (import, isolation, classifier)
3. **Phase 3:** Run full-scale analysis on existing ablation data
4. **Phase 4:** Extend `_emit_metrics_event` to include dual execution in events.jsonl
5. **Phase 5:** Run new ablation with dual execution enabled, analyze LEG adjustment

---

## 5. SUCCESS CRITERIA

The validation is complete when:

- [ ] All 8 import stress tests pass on both execution paths
- [ ] All 6 isolation tests confirm zero leakage
- [ ] Classifier produces correct type for all 8 adversarial inputs
- [ ] 5x repeated execution shows 0 variance on deterministic cases
- [ ] Full 58-case analysis produces agreement_rate > 90%
- [ ] LEG_adjusted is computed and differs from LEG_raw by a measurable amount
- [ ] Dashboard displays dual execution section
- [ ] events.jsonl includes dual_execution field

---

## 6. CONNECTION TO RESEARCH

### What this proves:

If `assembly_bias` > 0:
→ Some fraction of the reported LEG rate is NOT model reasoning failure — it's infrastructure error.
→ The paper must report LEG_adjusted, not just LEG_raw, or the conclusions about model reasoning quality are inflated.

If `assembly_failure_rate` correlates with model (higher for gpt-5-mini):
→ The benchmark is systematically biased against models that write more sophisticated import patterns.
→ Pass rate comparisons between models are not fair without adjustment.

If `semantic_divergence_rate` > 0:
→ The concatenation model alters Python semantics in ways that affect test outcomes.
→ The execution model choice is a confound, not just an implementation detail.

### What goes in the paper:

Table: "Infrastructure Error Analysis"
- Agreement rate across all evaluations
- Assembly failure rate by model
- LEG_raw vs LEG_adjusted
- Cases where disagreement flipped the category (e.g., LEG → true_success)

This is the evidence that the benchmark is measuring model capability, not infrastructure artifacts.
