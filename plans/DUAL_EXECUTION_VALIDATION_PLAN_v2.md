# Dual Execution Validation Plan v2

**Date:** 2026-03-30
**Status:** Corrected validation protocol

---

## 0. Trust Hierarchy (Non-Negotiable)

This document defines three layers with STRICT trust ordering:

| Layer | Role | Trust Level |
|---|---|---|
| **Concat execution** | Benchmark canonical execution path. ALL official pass/fail, LEG, category metrics use this. | CANONICAL — defines ground truth for the benchmark |
| **Module execution** | Diagnostic side-channel. Approximates native Python module semantics. | DIAGNOSTIC — provides evidence, not truth |
| **Disagreement classifier** | Interpretation layer over the two outputs. Produces hypotheses about root cause. | INTERPRETIVE — classifications are hypotheses, not facts |

**Rules:**
- Module execution NEVER overrides canonical results.
- Disagreement classifications are EVIDENCE, not proof.
- Adjusted metrics are CONSERVATIVE bounds, not corrections.
- No claim about infrastructure error is valid without manual verification of a representative sample.

---

## 1. Disagreement Taxonomy

### 1.1 Assembly Suspect vs Assembly Confirmed

| Category | Definition | Confidence | Use |
|---|---|---|---|
| `assembly_suspect` | `concat_fail AND module_pass` | Low — module pass may be coincidental | Broad diagnostic bucket. NOT used for metric adjustment. |
| `assembly_confirmed` | `assembly_suspect AND disagreement_type == "assembly_failure_likely" AND disagreement_confidence >= 0.8 AND error evidence is import/name/attribute related` | High — multiple signals converge | Used for conservative metric adjustment. Subject to manual audit. |

**`assembly_suspect` includes cases where:**
- Module execution succeeds for reasons unrelated to the import issue (e.g., different evaluation path, test harness difference, ordering luck)
- The concat failure is a genuine model bug that the module system happens to mask

**`assembly_confirmed` requires:**
- Classifier type is `assembly_failure_likely`
- Classifier confidence ≥ 0.8
- Concat error contains at least one of: `ModuleNotFoundError`, `ImportError`, `NameError` with import-related context, `AttributeError` on module-like object
- Module execution test actually ran and passed (not just "executed without crash")

### 1.2 Module Failure Categories

| Category | Definition | Meaning |
|---|---|---|
| `module_suspect` | `concat_pass AND module_fail` | Module execution introduces a failure that concat avoids. May indicate module system limitation (load order, circular deps) OR a case where concat's flattening accidentally fixes a real bug. |
| `module_confirmed` | `module_suspect AND disagreement_type == "module_execution_failure" AND confidence >= 0.8` | High-confidence module system limitation. |

**Key point:** `module_suspect` does NOT mean concat is right. Concat may be accidentally passing a case that should fail. Without an independent oracle, neither system is authoritative.

---

## 2. Metric Definitions

### 2.1 Raw Metrics (from canonical execution only)

```
LEG_raw = P(reasoning_correct == True AND concat_pass == False)
    denominator: events where reasoning_correct is not None

lucky_fix_raw = P(reasoning_correct == False AND concat_pass == True)
    denominator: events where reasoning_correct is not None

pass_rate = P(concat_pass == True)
    denominator: all events
```

These are the OFFICIAL metrics. They are NOT adjusted.

### 2.2 Diagnostic Metrics (from dual execution)

```
agreement_rate = P(concat_pass == module_pass)
    denominator: events where module execution completed

assembly_suspect_rate = P(concat_fail AND module_pass)
    denominator: events where module execution completed

assembly_confirmed_rate = P(assembly_confirmed)
    denominator: events where module execution completed

module_suspect_rate = P(concat_pass AND module_fail)
    denominator: events where module execution completed
```

These are DIAGNOSTIC. They describe the dual execution system's behavior, not model quality.

### 2.3 Conservative Adjusted Metrics

```
LEG_adjusted_conservative =
    P(reasoning_correct == True AND concat_fail AND NOT assembly_confirmed)
    denominator: events where reasoning_correct is not None AND module execution completed

LEG_infrastructure_conservative = LEG_raw - LEG_adjusted_conservative

assembly_bias_conservative = LEG_infrastructure_conservative / LEG_raw
    (0 if LEG_raw == 0)
```

**Interpretation:**
- `LEG_adjusted_conservative` removes ONLY high-confidence infrastructure errors from LEG.
- `assembly_bias_conservative` is the fraction of LEG that is attributable to confirmed infrastructure error.
- This is the PAPER-FACING metric. It is an UPPER BOUND on true LEG (i.e., LEG_adjusted_conservative ≤ true_LEG ≤ LEG_raw).

### 2.4 Exploratory Adjusted Metrics (clearly marked)

```
LEG_adjusted_broad =
    P(reasoning_correct == True AND concat_fail AND NOT assembly_suspect)
    denominator: events where reasoning_correct is not None AND module execution completed

assembly_bias_broad = (LEG_raw - LEG_adjusted_broad) / LEG_raw
```

**Interpretation:**
- `LEG_adjusted_broad` removes ALL suspected infrastructure errors, including unconfirmed ones.
- This is a LOWER BOUND on true LEG. It may over-correct.
- Labeled EXPLORATORY. NOT for primary paper claims. May be reported as a bound.

### 2.5 Confidence-Weighted Metrics

```
weighted_assembly_suspect_rate = Σ(confidence_i * is_assembly_suspect_i) / N_dual

weighted_infrastructure_bias = Σ(confidence_i * is_assembly_suspect_i * is_leg_raw_i) / N_leg_raw
```

These provide a continuous estimate instead of binary thresholds. Useful for sensitivity analysis.

### 2.6 Required Stratifications

ALL metrics above MUST be computed per:
- model
- condition
- family
- difficulty (A/B/C/single)
- file count (1/2/3+)

The stratification by file count is critical: assembly failures are hypothesized to concentrate in 2+ file cases.

---

## 3. Stress Testing Protocol

### 3.1 Import Resolution Stress

| Test ID | Pattern | Hypothesis | Measured Outcome | Diagnostic Value |
|---|---|---|---|---|
| IMP-01 | 3-level chain: A→B→C→D | Module execution should succeed more often than concat on deep chains. May still fail if 2-pass is insufficient. | module_pass_rate, concat_pass_rate, disagreement distribution | Measures chain depth sensitivity |
| IMP-02 | Circular: A↔B | Module execution may fail on 2-pass for true circular `from X import Y` patterns. Concat flattens, no issue. | Which system fails, what error | Tests 2-pass limits |
| IMP-03 | Mixed: `import A` + `from B import f` + `A.g()` | Both systems should succeed for well-formed cases. Concat uses namespace synthesis; module uses native. | Agreement, execution correctness | Validates namespace synthesis |
| IMP-04 | Alias chain: `import A as X; from A import f as g; X.h(); g()` | Both should succeed. Concat uses AST rename + namespace. | Verify identical test results | Validates alias + qualified handling |
| IMP-05 | Partial override: model modifies 1 of 3 files | Tests override semantics. Concat: last-def-wins. Module: module replacement. | Verify overridden function is the model's version in both | Critical for semantic equivalence |
| IMP-06 | Diamond: A→B, A→C, B→D, C→D | Module: D loaded once (Python default). Concat: D content appears once in original block. | Verify D's state is consistent | Tests duplicate content handling |
| IMP-07 | `from __future__ import annotations` | Must be first statement. Concat ordering may break this. Module: per-file, always first. | SyntaxError in concat? | Tests ordering sensitivity |
| IMP-08 | Model adds `import json` inside function body | Both should succeed. Concat should not strip intra-function imports. | Verify no false stripping | Tests strip scope awareness |

**Expected outcomes are HYPOTHESES.** Each test records both systems' behavior. Disagreements become diagnostic data, not automatic verdicts.

### 3.2 sys.modules Isolation

| Test ID | Protocol | Invariant | Detection |
|---|---|---|---|
| ISO-01 | Run case X 10 times consecutively | `pass` result identical all 10 times | `variance(pass) == 0` |
| ISO-02 | Run case A (writes `metrics._cache = [1,2,3]`), then case B (reads `metrics._cache`) | B sees empty/fresh cache | `metrics._cache == []` in B |
| ISO-03 | Snapshot `sys.modules.keys()` for case-relevant names before and after | After == before (exact set match) | `set(after_keys & case_names) == set()` |
| ISO-04 | 20 consecutive runs of random cases | `sys.modules.keys()` at end == baseline | Exact key comparison, not length |
| ISO-05 | Module that does `sys.path.append(...)` | sys.path restored after | `sys.path == original_path` |
| ISO-06 | Module that does `import builtins; builtins.X = 1` | builtins.X does not exist after cleanup | `not hasattr(builtins, 'X')` |

**Strict invariant:** For case module names, `sys.modules` must contain EXACTLY the same keys after execution as before. Not approximately. Exactly.

### 3.3 Non-Determinism

**Protocol:**
1. Select 10 cases (mix of single-file, 2-file, 3-file)
2. For each case, with fixed model output:
   - Run concat execution 5 times → record pass/fail sequence
   - Run module execution 5 times → record pass/fail sequence
   - Run disagreement classifier 5 times on same inputs → record classification sequence
3. Compute:
   - Per-case pass variance (must be 0 for deterministic settings)
   - Per-case classification stability (must be identical all 5 runs)
4. Run with INTERLEAVED case ordering (A,B,A,B,A,B) to detect ordering-dependent leakage
5. Run with RANDOMIZED ordering (shuffle cases) to detect ordering sensitivity

**Acceptance criteria:**
- Zero variance in pass/fail for both systems on deterministic (temp=0) model outputs
- Zero variance in disagreement classification
- If any variance detected: investigate and document as state leakage

### 3.4 Disagreement Classifier Stress

| Test ID | Input | Expected Type | Why It Matters |
|---|---|---|---|
| CLS-01 | Concat: `RuntimeError` wrapping `ImportError` | `assembly_failure_likely` | Tests keyword extraction from nested errors |
| CLS-02 | Concat: `ValueError("missing import data")` | NOT `assembly_failure_likely` (keyword "import" in message but wrong error type) | Tests that classification uses error TYPE, not just keywords |
| CLS-03 | Both fail: concat NameError, module ImportError | `consistent_failure/different_error` | Tests consistent failure with different root causes |
| CLS-04 | Concat: 2 tests run. Module: 1 test run. | `test_inconsistency` | Tests test count mismatch detection |
| CLS-05 | Both fail, empty error strings | `agreement` (both fail, same test count) | Tests graceful handling of missing evidence |
| CLS-06 | Traceback > 10KB | Same as shorter version | Tests performance/truncation handling |
| CLS-07 | Unicode error: `UnicodeDecodeError` | Correct classification, no crash | Tests encoding robustness |
| CLS-08 | 100 identical runs | Identical classification all 100 times | Tests determinism |

### 3.5 Semantic Divergence Measurement

**What is compared:**
- `test_passed` (boolean) — primary
- `test_reasons` (list of strings) — secondary, if available
- Test function return values are the only observable output. We do NOT have stdout capture for individual test runs.

**Observable semantic divergence:**
- Both pass, but different `test_reasons` text → `semantic_divergence/test_result_difference`
- Both pass, same `test_reasons` text → `agreement`

**Limitation:** The current system does not capture per-test-function return values or side effects beyond pass/fail + reasons. Semantic divergence measurement is LIMITED to test pass/fail + reason strings. This must be stated explicitly in any research use.

---

## 4. Manual Audit Protocol

### 4.1 Purpose

Automated classification produces HYPOTHESES. Manual audit produces EVIDENCE.

No claim about infrastructure error rate is valid for publication without manual verification.

### 4.2 Protocol

After running the full stress suite and at least one complete ablation with dual execution:

1. **Sample selection:**
   - Top 10 `assembly_confirmed` cases by confidence (highest confidence first)
   - Top 10 `assembly_suspect` but NOT confirmed cases
   - Top 5 `module_execution_failure` cases
   - Top 5 cases where `both_fail` with different errors

2. **Per-case inspection:**
   - Read the model's generated code
   - Read the concat-assembled code
   - Read the error messages from both systems
   - Determine: is the classifier's hypothesis correct?
   - Record: `manual_verdict = "confirmed" | "rejected" | "ambiguous"`

3. **Compute manual audit accuracy:**
   ```
   classifier_precision = P(manual_confirmed | assembly_confirmed)
   classifier_recall = P(assembly_confirmed | manual_confirmed)
   ```

4. **Threshold validation:**
   - If `classifier_precision < 0.8`: the conservative adjusted metrics are still too aggressive. Tighten the confidence threshold.
   - If `classifier_precision >= 0.9`: the conservative adjusted metrics are defensible for the paper.

### 4.3 Artifact

Produce: `audits/dual_execution_manual_audit.md`

Containing: case ID, model, condition, concat error, module result, classifier classification, manual verdict, reasoning.

---

## 5. Success Criteria

The validation is complete when:

| Criterion | Required | Measured How |
|---|---|---|
| Isolation proven | Zero case-specific module names in sys.modules after cleanup, across 20+ consecutive runs | ISO-01 through ISO-06 |
| Determinism proven | Zero variance in pass/fail and classification across 5 repeated runs, for 10 cases | Non-determinism protocol |
| Classifier accuracy proven | Manual audit precision ≥ 0.8 on `assembly_confirmed` | Manual audit of top 10 cases |
| Conservative LEG adjustment bounded | `assembly_bias_conservative` computed and reported with confidence interval | Metric computation on ablation data |
| Stratified metrics available | All metrics broken down by model, condition, family, file count | Metric computation |
| Disagreement distribution interpretable | No more than 5% of events classified as `unknown` | Classifier on full ablation |
| Module execution stable | Agreement rate computable and stable across trials | Full ablation dual execution |

**The following are NOT success criteria:**
- "Agreement rate > X%" — agreement rate is descriptive, not prescriptive
- "Module execution passes more cases than concat" — this is not required or expected
- "LEG_adjusted is lower than LEG_raw" — it might not be, and that would be a valid finding

---

## 6. Research Connection

### 6.1 What the paper reports

| Metric | Label | Interpretation |
|---|---|---|
| `LEG_raw` | "LEG (unadjusted)" | Includes all sources of model-correct-code-wrong, including infrastructure |
| `LEG_adjusted_conservative` | "LEG (infrastructure-adjusted)" | Removes high-confidence infrastructure errors. Conservative upper bound on true LEG. |
| `assembly_bias_conservative` | "Infrastructure bias" | Fraction of LEG attributable to confirmed assembly errors |
| `assembly_confirmed_rate` | "Confirmed assembly error rate" | Rate of cases where concat assembly demonstrably corrupted model output |

### 6.2 What the paper DOES NOT claim

- Module execution is more correct than concat (it is a different execution model, not a better one)
- All `assembly_suspect` cases are infrastructure errors (many may be coincidental module-pass)
- LEG_adjusted_broad is the true LEG (it may over-correct)

### 6.3 How disagreement affects interpretation

If `assembly_bias_conservative > 0.05` (>5% of LEG is confirmed infrastructure):
→ "The benchmark's LEG measurement is materially affected by assembly infrastructure. The adjusted rate removes confirmed infrastructure errors, but the true LEG lies between LEG_adjusted_conservative and LEG_raw."

If `assembly_bias_conservative < 0.02` (<2%):
→ "Infrastructure-induced LEG is negligible. The canonical LEG measurement is not meaningfully contaminated."

If `assembly_confirmed_rate` correlates with model (higher for certain models):
→ "The benchmark's code execution system introduces model-dependent bias through import handling. Pass rate comparisons between models should be interpreted with this caveat."

### 6.4 What disagreement signals mean

| Signal | Meaning | NOT Meaning |
|---|---|---|
| `concat_fail AND module_pass` | Concat assembly MAY have corrupted the code | Module execution is definitely correct |
| `concat_pass AND module_fail` | Module execution MAY have an infrastructure limitation | Concat execution is definitely correct |
| `assembly_confirmed` | High-confidence evidence of concat infrastructure error | Proof that the model's code is correct |
| `semantic_divergence` | The two execution models produce different behavior on the same code | One is right and the other is wrong |

---

## 7. Implementation Plan

### 7.1 Files to Create

| File | Purpose | Priority |
|---|---|---|
| `tests/stress/test_import_stress.py` | IMP-01 through IMP-08 | HIGH |
| `tests/stress/test_isolation_stress.py` | ISO-01 through ISO-06 | HIGH |
| `tests/stress/test_nondeterminism.py` | 5x repeated runs, interleaved, randomized | HIGH |
| `tests/stress/test_classifier_stress.py` | CLS-01 through CLS-08 | MEDIUM |
| `scripts/run_dual_analysis.py` | Compute all dual execution metrics from ablation data | HIGH |

### 7.2 Files to Modify

| File | Change | Priority |
|---|---|---|
| `live_metrics.py:compute_metrics()` | Add dual execution metric computation (section 2 formulas) | HIGH |
| `live_metrics.py:write_dashboard()` | Add S8 section with dual execution metrics | HIGH |
| `execution.py:_emit_metrics_event()` | Propagate `dual_execution` dict to events.jsonl | HIGH |

### 7.3 Functions to Add

```python
# live_metrics.py
def _compute_dual_metrics(events: list[dict]) -> dict:
    """Compute agreement_rate, assembly_suspect/confirmed, module_suspect, LEG adjustments."""

# scripts/run_dual_analysis.py
def compute_leg_adjustment(events: list[dict]) -> dict:
    """Compute LEG_raw, LEG_adjusted_conservative, LEG_adjusted_broad, assembly_bias."""

def generate_top_disagreements(events: list[dict], n: int = 20) -> list[dict]:
    """Extract top disagreement cases for manual audit."""

def compute_stratified_metrics(events: list[dict]) -> dict:
    """Compute all metrics stratified by model, condition, family, file_count."""
```

### 7.4 Execution Sequence

1. Implement metrics computation in `live_metrics.py`
2. Implement dashboard S8 section
3. Implement stress tests
4. Run one complete ablation with dual execution enabled
5. Compute metrics on ablation data
6. Generate top disagreement cases
7. Perform manual audit on sample
8. Compute classifier precision
9. If precision ≥ 0.8: report conservative adjusted metrics
10. If precision < 0.8: tighten confidence threshold, re-audit
