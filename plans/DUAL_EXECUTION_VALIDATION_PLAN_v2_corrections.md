# Dual Execution Validation Plan v2 — Corrections

**Date:** 2026-03-30
**Scope:** Three targeted corrections to the v2 plan

---

## CORRECTION 1: Formal Definition of `assembly_confirmed`

**Replaces section 1.1 `assembly_confirmed` definition in the v2 plan.**

---

### Signal Extraction (computed at classification time)

The following boolean signals MUST be extracted from execution results using typed checks, not string matching:

```python
# Signal 1: Import-class error in concat execution
has_import_error: bool =
    concat_error_type in {"ModuleNotFoundError", "ImportError"}
    WHERE concat_error_type is extracted by matching the exception class name
    from the traceback's final exception line (not from the error message body)

# Signal 2: Missing symbol that should exist from imports
has_missing_symbol: bool =
    concat_error_type == "NameError"
    AND missing_symbol in expected_imported_symbols
    WHERE:
        missing_symbol = the name extracted from "name 'X' is not defined"
        expected_imported_symbols = union of:
            - all aliases from stripped `from X import Y as Z` statements
              (i.e., Z values that were targets of AST rename)
            - all module names from stripped `import X` statements
            - all names from stripped `from X import Y` statements
        These are computed by CodeAssembler during assembly and stored in
        AssemblyResult.rewrites_applied (type="alias_rename" → alias field,
        type="remove_from_import" → names field,
        type="remove_bare_import" → module field,
        type="qualified_import_resolved" → effective_name field)

# Signal 3: Attribute error on synthesized namespace
has_namespace_error: bool =
    concat_error_type == "AttributeError"
    AND error_object_name in synthesized_namespace_names
    WHERE:
        error_object_name = the object name from "'X' object has no attribute 'Y'"
        synthesized_namespace_names = set of effective_name values from
        AssemblyResult.qualified_imports_resolved
```

### Formal Definition

```python
assembly_confirmed =
    assembly_suspect                                    # concat_fail AND module_pass
    AND disagreement_type == "assembly_failure_likely"   # classifier primary type
    AND disagreement_confidence >= 0.8                   # classifier confidence threshold
    AND (
        has_import_error
        OR has_missing_symbol
        OR has_namespace_error
    )
```

### Prohibited Methods

The following are EXPLICITLY FORBIDDEN for `assembly_confirmed` determination:
- Substring matching on error message body (e.g., checking if "import" appears in a RuntimeError message)
- Keyword-only heuristics without error type validation
- Confidence score alone without structural signal
- Any classification that lacks at least one of the three formal signals above

### Required Infrastructure

To compute `has_missing_symbol` and `has_namespace_error`, the AssemblyResult from the canonical concat path MUST be available at classification time. This means:
- `exec_evaluate` must propagate `AssemblyResult` (or its `rewrites_applied` and `qualified_imports_resolved` fields) into the evaluation result
- The disagreement classifier must receive these fields as additional input
- If these fields are unavailable (e.g., single-file case with no assembly), `has_missing_symbol` and `has_namespace_error` are both False, and `assembly_confirmed` can only be True via `has_import_error`

---

## CORRECTION 2: Manual Audit Sampling Protocol

**Replaces section 4.2 in the v2 plan.**

---

### Sampling Strata

The manual audit MUST sample from THREE distinct confidence strata to avoid selection bias. Sampling only high-confidence cases inflates precision by excluding the cases where the classifier is most likely wrong.

| Stratum | Selection Criteria | Sample Size | Purpose |
|---|---|---|---|
| **A: High-confidence confirmed** | `assembly_confirmed == True AND confidence >= 0.9` | min(10, available) | Verify that the strongest signals are genuinely infrastructure errors |
| **B: Near-threshold** | `assembly_suspect == True AND confidence in [0.7, 0.85]` | min(10, available) | Test the classification boundary — this is where errors concentrate |
| **C: Low-confidence suspect** | `assembly_suspect == True AND confidence < 0.7` | min(10, available) | Verify that low-confidence cases are NOT being incorrectly excluded |

### Why Near-Threshold Sampling Is Required

If we only audit high-confidence cases, we learn that the classifier is correct when it is confident. This tells us nothing about whether the confidence threshold is correct. The near-threshold stratum (Stratum B) directly tests whether the 0.8 threshold separates true positives from false positives. If precision drops significantly in Stratum B, the threshold must be increased.

### Per-Case Inspection Protocol

For each sampled case:

1. **Read the model's generated code** — what did the model actually produce?
2. **Read the AssemblyResult** — what rewrites were applied? What was the assembled code?
3. **Read the concat error** — what specific error occurred during concat execution?
4. **Read the module execution result** — did the module system succeed? What was the test result?
5. **Determine root cause:**
   - Is the concat error caused by import stripping / namespace synthesis / AST rewriting?
   - Or is the concat error caused by a genuine model code bug?
   - Or is the module pass coincidental (e.g., module system masks a real bug)?
6. **Record manual verdict:** `confirmed_infrastructure | confirmed_model_bug | ambiguous | module_coincidental`

### Computed Audit Metrics

```python
precision_stratum_A = P(manual == confirmed_infrastructure | stratum == A)
precision_stratum_B = P(manual == confirmed_infrastructure | stratum == B)
precision_stratum_C = P(manual == confirmed_infrastructure | stratum == C)

overall_precision = weighted average across strata

threshold_stability = |precision_A - precision_B|
```

### Decision Rules

| Outcome | Action |
|---|---|
| `precision_A >= 0.9 AND precision_B >= 0.8` | Threshold is valid. Conservative adjusted metrics are defensible. |
| `precision_A >= 0.9 AND precision_B < 0.8` | Threshold too low. Increase to 0.9 and re-audit Stratum B at new boundary. |
| `precision_A < 0.8` | Classifier is unreliable even at high confidence. `assembly_confirmed` cannot be trusted. Adjusted LEG metrics MUST NOT be reported. |
| `precision_C > 0.5` | Threshold may be too high — real infrastructure errors are being excluded. Consider lowering threshold or reporting LEG_adjusted_broad as supplementary. |

### Artifact

Produce: `audits/dual_execution_manual_audit.md`

Contents per case: case_id, model, condition, family, file_count, concat_error, module_result, classifier_type, classifier_confidence, manual_verdict, reasoning (1-2 sentences).

---

## CORRECTION 3: Method Failure Conditions

**New section. Insert after section 5 (Success Criteria) in the v2 plan.**

---

### Definition

A method failure condition is a state where the dual execution adjustment methodology CANNOT produce reliable results. If ANY of the following conditions is met, adjusted LEG metrics MUST NOT be used for research claims. Raw LEG (from canonical concat execution) remains valid.

### F1. Classifier Precision Failure

```
CONDITION: precision_stratum_A < 0.8
           (manual audit shows >20% of high-confidence assembly_confirmed are wrong)

INTERPRETATION: The classifier cannot reliably distinguish infrastructure errors from
model errors even at its highest confidence. All downstream metrics that depend on
assembly_confirmed are unreliable.

CONSEQUENCE: LEG_adjusted_conservative, assembly_bias_conservative, and all derived
metrics MUST NOT be reported. Only LEG_raw is valid.
```

### F2. Classification Instability

```
CONDITION: For any input, repeated classification produces different
           disagreement_type values across runs
           (detected by non-determinism stress test: CLS-08)

INTERPRETATION: The classifier is non-deterministic or stateful. Classification
results are not reproducible.

CONSEQUENCE: ALL disagreement-derived metrics are invalid. Dual execution comparison
data may still be reported as raw agreement/disagreement counts, but NOT as typed
classifications.
```

### F3. Threshold Sensitivity

```
CONDITION: Varying confidence threshold by ±0.1 changes assembly_confirmed_rate
           by more than 50% relative
           (e.g., threshold=0.8 gives rate=3%, threshold=0.7 gives rate=7%)

INTERPRETATION: The classification boundary is unstable. Small methodological
choices dominate the result.

CONSEQUENCE: Report assembly_confirmed_rate as a range (min-max across threshold
sweep), not a point estimate. LEG_adjusted must also be reported as a range.
```

### F4. High Ambiguity Rate

```
CONDITION: P(disagreement_type == "unknown") > 0.05
           (more than 5% of dual execution events cannot be classified)

INTERPRETATION: The classifier's coverage is insufficient. A material fraction
of disagreements are opaque.

CONSEQUENCE: Report the unknown rate explicitly. Adjusted metrics carry an
uncertainty proportional to the unknown rate.
```

### F5. Module Execution Instability

```
CONDITION: Module execution shows non-zero pass/fail variance across repeated
           runs of the same case with identical input
           (detected by non-determinism stress test)

INTERPRETATION: The module execution side-channel is non-deterministic.
assembly_suspect (which depends on module_pass) is unreliable.

CONSEQUENCE: assembly_suspect_rate cannot be used as a metric. Only cases where
module execution is stable across all runs may contribute to assembly_suspect.
Unstable cases must be excluded from adjusted metrics and reported separately.
```

### F6. Excessive Unconfirmed Suspects

```
CONDITION: assembly_suspect_rate > 3 * assembly_confirmed_rate
           (more than 2/3 of suspected infrastructure errors cannot be confirmed)

INTERPRETATION: The gap between suspected and confirmed is too large. Most
disagreements are ambiguous. The confirmed subset may not be representative
of the full infrastructure error population.

CONSEQUENCE: Report both rates. State explicitly that assembly_confirmed is a
lower bound on infrastructure error. LEG_adjusted_conservative is an UPPER bound
on true LEG (it removes only the confirmed fraction). The true infrastructure
contribution may be larger.
```

### Summary Table

| Condition | Threshold | What Fails | What Remains Valid |
|---|---|---|---|
| F1 | precision < 0.8 | All adjusted metrics | LEG_raw, raw dual execution counts |
| F2 | classification flips | All typed classifications | Raw agreement/disagreement counts |
| F3 | rate changes >50% | Point estimates | Range estimates |
| F4 | unknown > 5% | Precision of adjusted metrics | Metrics with explicit uncertainty |
| F5 | module variance > 0 | assembly_suspect for unstable cases | Stable cases only |
| F6 | suspect >> confirmed | Representativeness of confirmed | Both rates reported with caveat |

### Enforcement

These failure conditions MUST be checked BEFORE reporting any adjusted metric. The checking is automated (computed from the stress test and audit results). If any condition is triggered, the analysis script MUST emit a WARNING and append the failure condition to the output report.
