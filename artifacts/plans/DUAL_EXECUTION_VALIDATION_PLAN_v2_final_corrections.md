# Dual Execution Validation Plan v2 — Final Corrections

**Date:** 2026-03-30
**Scope:** Six targeted methodological corrections

---

## CORRECTION 1: Constrained `expected_imported_symbols`

**Replaces the `expected_imported_symbols` definition in the `assembly_confirmed` formal definition.**

---

### Definition

```python
expected_imported_symbols =
    symbols originating from stripped/rewritten imports in AssemblyResult.rewrites_applied
    MINUS symbols that are reassigned before their first use in the assembled code
```

### Reassignment Detection

A symbol is considered reassigned if ANY of the following appear in the AST of the code block where the symbol is used (the file from which the import was stripped):

```python
reassigned(symbol) =
    EXISTS node in ast.walk(file_tree) WHERE:
        (isinstance(node, ast.Assign) AND symbol in {t.id for t in node.targets if isinstance(t, ast.Name)})
        OR (isinstance(node, ast.AugAssign) AND isinstance(node.target, ast.Name) AND node.target.id == symbol)
        OR (isinstance(node, ast.For) AND isinstance(node.target, ast.Name) AND node.target.id == symbol)
        OR (isinstance(node, ast.FunctionDef) AND node.name == symbol)
        OR (isinstance(node, ast.ClassDef) AND node.name == symbol)
```

### Scope Rules

- Only top-level scope is analyzed. Nested function/class scopes are NOT traversed.
- If a symbol is reassigned at top level, it is excluded from `expected_imported_symbols` regardless of ordering (conservative: we do not attempt to determine whether reassignment occurs before or after usage).
- Rationale: tracking definition-use ordering within a single scope requires control flow analysis. In the absence of that, excluding all reassigned symbols is conservative and prevents false positives.

### Conservative Fallback

```python
if AST parse of the relevant file fails:
    expected_imported_symbols = empty set
    # Cannot determine which symbols were import-originated
    # has_missing_symbol = False for all symbols
```

If reassignment detection itself fails (e.g., malformed AST node):
```python
    exclude the symbol (treat as reassigned)
```

### Updated `has_missing_symbol`

```python
has_missing_symbol =
    concat_error_type == "NameError"
    AND missing_symbol in expected_imported_symbols
    AND NOT reassigned(missing_symbol)
```

---

## CORRECTION 2: Hardened Attribute Error Parsing

**Replaces the `has_namespace_error` extraction logic.**

---

### Extraction Protocol

The `error_object_name` is extracted from the AttributeError message using the following ordered attempts:

```python
# Attempt 1: Standard CPython format
#   "'SimpleNamespace' object has no attribute 'func'"
#   "'metrics' object has no attribute 'reset'"
match = re.match(r"'(\w+)' object has no attribute '(\w+)'", error_message)
if match:
    error_object_name = match.group(1)  # NOT the attribute, the object type/name

# Attempt 2: Module-style format
#   "module 'metrics' has no attribute 'reset'"
match = re.match(r"module '(\w+)' has no attribute", error_message)
if match:
    error_object_name = match.group(1)
```

### Cross-Reference

```python
# Check against synthesized namespace names from AssemblyResult
synthesized_namespace_names = {
    r["effective_name"]
    for r in assembly_result.qualified_imports_resolved
}
```

### Failure Default

```python
if extraction fails (no regex match, or error_message is None/empty):
    error_object_name = None
    has_namespace_error = False

if error_object_name is not None:
    has_namespace_error =
        concat_error_type == "AttributeError"
        AND error_object_name in synthesized_namespace_names
else:
    has_namespace_error = False
```

### Constraints

- Extraction is best-effort. Failure to extract ALWAYS defaults to `False`.
- The regex patterns are ordered by specificity. If neither matches, extraction fails silently.
- No exception may propagate from error message parsing. All parsing is wrapped in try/except with default `False`.
- Python version changes to error message format will cause extraction failure, which defaults to `False` (conservative).

---

## CORRECTION 3: Manual Audit with Inter-Annotator Reliability

**Replaces section 4.2 in the v2 plan. Extends the three-strata sampling with dual-reviewer protocol.**

---

### Sampling Strata

Unchanged from v2 corrections:

| Stratum | Selection Criteria | Sample Size |
|---|---|---|
| A: High-confidence confirmed | `assembly_confirmed AND confidence >= 0.9` | min(10, available) |
| B: Near-threshold | `assembly_suspect AND confidence in [0.7, 0.85]` | min(10, available) |
| C: Low-confidence suspect | `assembly_suspect AND confidence < 0.7` | min(10, available) |

### Dual-Reviewer Protocol

From the total audited sample (up to 30 cases), a MINIMUM of 5 cases MUST be reviewed by a second independent reviewer.

**Selection of dual-review cases:** At least 2 from Stratum A, at least 2 from Stratum B, and at least 1 from Stratum C. If fewer cases are available in a stratum, allocate to the next stratum.

**Independence requirements:**
- Reviewers evaluate cases without seeing each other's verdicts
- Reviewers receive identical materials: model code, assembled code, concat error, module result, case metadata
- Reviewers do NOT receive the classifier's classification (to prevent anchoring)
- After independent evaluation, verdicts are compared

**Verdict categories (same for both reviewers):**
- `confirmed_infrastructure` — the concat failure is caused by assembly/import handling
- `confirmed_model_bug` — the concat failure is caused by the model's code being wrong
- `ambiguous` — cannot determine root cause with confidence
- `module_coincidental` — the module pass is coincidental (module system masks a real bug)

### Computed Metrics

```python
inter_annotator_agreement = P(reviewer1_verdict == reviewer2_verdict)
    computed over the dual-reviewed subset

per_stratum_precision = P(manual == confirmed_infrastructure | stratum)
    using primary reviewer for non-dual cases, consensus for dual-reviewed cases

consensus_rule:
    if reviewer1 == reviewer2: use shared verdict
    if reviewer1 != reviewer2: classify as "ambiguous" (conservative)
```

### Decision Rules

| Outcome | Action |
|---|---|
| `inter_annotator_agreement >= 0.8` | Audit protocol is reliable. Proceed with adjusted metrics. |
| `inter_annotator_agreement in [0.6, 0.8)` | Audit has moderate reliability. Report adjusted metrics with explicit caveat about audit uncertainty. |
| `inter_annotator_agreement < 0.6` | Audit protocol is unreliable. Adjusted LEG metrics MUST NOT be reported. Only LEG_raw is valid. This is Method Failure Condition F7 (see below). |

---

## CORRECTION 4: Formalized Threshold Sensitivity

**Replaces the threshold sensitivity check in Method Failure Conditions (F3).**

---

### Computation Protocol

```python
dataset = all events with dual_execution data from the ablation run
thresholds = [0.6, 0.7, 0.8, 0.9]

for t in thresholds:
    assembly_confirmed_rate_at_t = P(
        assembly_suspect
        AND disagreement_type == "assembly_failure_likely"
        AND disagreement_confidence >= t
        AND (has_import_error OR has_missing_symbol OR has_namespace_error)
    )

rates = {t: assembly_confirmed_rate_at_t for t in thresholds}
baseline = rates[0.8]  # the operational threshold
max_rate = max(rates.values())
min_rate = min(rates.values())

relative_range = (max_rate - min_rate) / baseline if baseline > 0 else float('inf')
```

### Failure Condition F3 (revised)

```
CONDITION: relative_range > 0.5
    (confirmed rate varies by more than 50% relative to baseline
     across the threshold sweep)

INTERPRETATION: The classification boundary is unstable. The choice of
confidence threshold dominates the infrastructure error estimate more than
the underlying data.

CONSEQUENCE: Report assembly_confirmed_rate as a range [min_rate, max_rate],
not a point estimate. LEG_adjusted_conservative must also be reported as a
range corresponding to the threshold sweep.
```

### Required Parameters

- Dataset is fixed across all threshold evaluations (same events, same classifications)
- All other parameters (assembly_suspect definition, signal extraction) are fixed
- Only the confidence threshold varies
- Results table: threshold → rate, with baseline highlighted

---

## CORRECTION 5: Unstable Case Handling

**Replaces the unstable case handling in section 5 (Success Criteria) and section 6 (Research Connection).**

---

### Stability Determination

```python
for each (case_id, model, condition) tuple:
    runs = all dual execution results for this tuple across trials

    module_outcomes = [r.module_pass for r in runs if r.module_executed]

    if len(set(module_outcomes)) > 1:
        stability = "unstable"
    elif len(module_outcomes) == 0:
        stability = "no_data"
    else:
        stability = "stable"
```

### Metric Computation Rules

```
ALL dual-execution adjusted metrics (LEG_adjusted_conservative, LEG_adjusted_broad,
assembly_confirmed_rate, assembly_bias) are computed on STABLE CASES ONLY.
```

Unstable cases are:
- Excluded from the denominator of adjusted metrics
- Counted and reported separately:

```python
unstable_case_rate = N_unstable / N_total
unstable_case_list = [(case_id, model, condition, module_outcomes)]
```

### Reporting Requirement

Every report that includes adjusted metrics MUST state:

> "Adjusted metrics are computed on {N_stable} stable cases ({stable_pct:.1%} of total). {N_unstable} unstable cases ({unstable_pct:.1%}) are excluded due to non-deterministic module execution and reported separately."

If `unstable_case_rate > 0.10` (more than 10% of cases are unstable):

> Method Failure Condition F5 is triggered. The module execution diagnostic is unreliable for a material fraction of cases. Adjusted metrics are computed on the stable subset only and MUST be interpreted as applying to that subset, not the full benchmark.

---

## CORRECTION 6: Confidence Semantics Clarification

**New subsection to be inserted at the beginning of section 2 (Metric Definitions) in the v2 plan.**

---

### Confidence Score Semantics

The `disagreement_confidence` field produced by the disagreement classifier is an **ordinal rule-strength score**, NOT a calibrated probability.

| Score | Meaning | Assigned When |
|---|---|---|
| 1.0 | Exact rule match | Classifier pattern matches unambiguously (e.g., `ModuleNotFoundError` in concat, module passes) |
| 0.8 | Strong signal match | Primary signal present with supporting evidence (e.g., `NameError` + symbol in stripped import list) |
| 0.5 | Weak heuristic match | Partial or indirect signal (e.g., concat fails, module passes, but error type is not import-related) |
| 0.0 | No classification | `unknown` type — no rule matched |

### Constraints

- Confidence scores MUST NOT be interpreted as probabilities (e.g., "80% chance this is an infrastructure error")
- Confidence scores MUST NOT be used in probabilistic models, Bayesian updates, or statistical tests that assume calibrated likelihoods
- Confidence scores ARE valid for:
  - Ordinal thresholding (e.g., `>= 0.8` for confirmed)
  - Ranking (higher confidence = stronger evidence)
  - Weighted aggregation (as a rule-strength weight, not a probability weight)
- The relationship between confidence scores and actual classification accuracy is established EMPIRICALLY via manual audit, not assumed

### Validation

The manual audit (Correction 3) produces per-stratum precision values that empirically calibrate what each confidence level means. If `precision_at_0.8 >= 0.8`, then the 0.8 threshold is empirically validated as a reasonable boundary. If not, the threshold must be adjusted until empirical precision meets the requirement.

---

## NEW: Method Failure Condition F7

**Add to the Method Failure Conditions section.**

---

### F7. Inter-Annotator Disagreement

```
CONDITION: inter_annotator_agreement < 0.6
    (computed over the dual-reviewed subset of manual audit cases)

INTERPRETATION: Two independent reviewers cannot agree on whether a
disagreement is infrastructure error or model error. The manual audit
itself is unreliable, which means:
    - per-stratum precision values are not trustworthy
    - the confidence threshold has not been empirically validated
    - assembly_confirmed cannot be trusted

CONSEQUENCE: Adjusted LEG metrics MUST NOT be reported. Only LEG_raw
is valid. The dual execution system can still report raw agreement/
disagreement counts and type distributions, but no claim about
infrastructure error rates is defensible.
```

### Updated Summary Table (F1-F7)

| Condition | Threshold | What Fails | What Remains Valid |
|---|---|---|---|
| F1 | precision < 0.8 | All adjusted metrics | LEG_raw, raw counts |
| F2 | classification flips | All typed classifications | Raw agreement/disagreement counts |
| F3 | rate change >50% | Point estimates | Range estimates |
| F4 | unknown > 5% | Precision of adjusted metrics | Metrics with explicit uncertainty |
| F5 | module variance > 0 for >10% | Adjusted metrics on full set | Adjusted metrics on stable subset |
| F6 | suspect >> 3× confirmed | Representativeness of confirmed | Both rates reported with caveat |
| F7 | inter-annotator < 0.6 | Manual audit validation | LEG_raw, raw counts, type distributions |
