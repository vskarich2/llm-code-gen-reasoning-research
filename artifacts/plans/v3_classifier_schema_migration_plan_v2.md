# V3 Classifier Schema Migration Plan v2

Supersedes v1. Incorporates all 10 corrections from review.

---

## Changes from v1

| # | v1 Defect | v2 Fix |
|---|---|---|
| 1 | `_extract_canonical_dims` good but no guard against mixed state | Add assertion: if both v2 AND v3 fields populated → crash |
| 2 | `commitments_valid` uses PARTIAL on v3 path; v3 schema only allows CORRECT/INCORRECT | Remove PARTIAL from v3 path entirely; all v3 comparisons use `== "CORRECT"` |
| 3 | Extra JSON keys tolerated | Strict: reject any key outside the 8 expected |
| 4 | Justification validation only checks non-empty | Add: reject `<`/`>`, reject length < 10, reject all-identical |
| 5 | Test plan asserts metric equivalence with v2 | Remove equivalence assertion; test only internal consistency and no-crash |
| 6 | Dashboard integration across multiple views | Limit to pipeline trace view only |
| 7 | v3 detection uses single field null check | Assert: if any v3 field exists, all 4 must exist |
| 8 | No explicit removal audit of old field direct access | All direct access to `mechanism_identified`, `commitments_extracted`, `commitments_satisfied` routed through mapping |
| 9 | 16 tests | Reduced to 5 essential |
| 10 | Over-iteration risk | Ship after implementing these fixes |

---

## Implementation spec (file by file)

### 1. `core/evaluation/evaluator_v2.py`

**ClassifierResultV2 — add fields:**
```python
# V3 dimensions
reasoning_internal_consistency: str | None = None
commitments_internal_consistency: str | None = None
commitments_code_consistency: str | None = None
# reasoning_code_alignment already exists

# V3 justifications (debug only — MUST NOT affect metrics)
reasoning_internal_consistency_justification: str = ""
commitments_internal_consistency_justification: str = ""
commitments_code_consistency_justification: str = ""
reasoning_code_alignment_justification: str = ""
```

**`_extract_canonical_dims()` — new function, SINGLE SOURCE OF TRUTH:**
```python
def _extract_canonical_dims(result: ClassifierResultV2) -> dict:
    """THE ONLY SOURCE OF TRUTH FOR DIMENSION MAPPING.
    
    Maps v3 or v2 classifier fields to canonical signal names.
    No other code may read dimension fields directly from the result.
    """
    v3_fields = (
        result.reasoning_internal_consistency,
        result.commitments_internal_consistency,
        result.commitments_code_consistency,
    )
    v2_fields = (
        result.mechanism_identified,
        result.commitments_extracted,
        result.commitments_satisfied,
    )
    
    v3_populated = any(f is not None for f in v3_fields)
    v2_populated = any(f is not None for f in v2_fields)
    
    if v3_populated and v2_populated:
        raise RuntimeError(
            "Mixed classifier state: both v2 and v3 dimension fields "
            "are populated. This indicates a parser bug."
        )
    
    if v3_populated:
        # All v3 fields must be present if any is
        if not all(f is not None for f in v3_fields):
            raise RuntimeError(
                "Partial v3 classifier state: some v3 fields are None. "
                f"reasoning_ic={result.reasoning_internal_consistency}, "
                f"commitments_ic={result.commitments_internal_consistency}, "
                f"commitments_cc={result.commitments_code_consistency}"
            )
        return {
            "mechanism_identified": result.reasoning_internal_consistency,
            "commitments_extracted": result.commitments_internal_consistency,
            "commitments_satisfied": result.commitments_code_consistency,
            "reasoning_code_alignment": result.reasoning_code_alignment,
        }
    
    return {
        "mechanism_identified": result.mechanism_identified,
        "commitments_extracted": result.commitments_extracted,
        "commitments_satisfied": result.commitments_satisfied,
        "reasoning_code_alignment": result.reasoning_code_alignment,
    }
```

**`parse_classifier_v3_output()` — rewrite expected keys and validation:**

Expected keys (strict, exact match):
```python
_V3_EXPECTED_KEYS = {
    "reasoning_internal_consistency",
    "commitments_internal_consistency",
    "commitments_code_consistency",
    "reasoning_code_alignment",
    "reasoning_internal_consistency_justification",
    "commitments_internal_consistency_justification",
    "commitments_code_consistency_justification",
    "reasoning_code_alignment_justification",
}
_V3_DIMENSION_KEYS = {
    "reasoning_internal_consistency",
    "commitments_internal_consistency",
    "commitments_code_consistency",
    "reasoning_code_alignment",
}
_V3_JUSTIFICATION_KEYS = {
    "reasoning_internal_consistency_justification",
    "commitments_internal_consistency_justification",
    "commitments_code_consistency_justification",
    "reasoning_code_alignment_justification",
}
_V3_VALID_DIMS = frozenset({"CORRECT", "INCORRECT"})
```

Schema check — strict, no extra keys:
```python
if set(d.keys()) != _V3_EXPECTED_KEYS:
    extra = set(d.keys()) - _V3_EXPECTED_KEYS
    missing = _V3_EXPECTED_KEYS - set(d.keys())
    result.parse_error = f"schema_mismatch: extra={extra}, missing={missing}"
    return result
```

Dimension validation:
```python
for key in _V3_DIMENSION_KEYS:
    val = d[key]
    if val not in _V3_VALID_DIMS:
        result.parse_error = f"invalid_dimension: {key}={val!r}"
        return result
```

Justification validation:
```python
for key in _V3_JUSTIFICATION_KEYS:
    val = d[key]
    if not isinstance(val, str) or len(val.strip()) < 10:
        result.parse_error = f"justification_too_short: {key} ({len(str(val))} chars)"
        return result
    if "<" in val or ">" in val:
        result.parse_error = f"justification_contains_placeholder: {key}"
        return result

# Reject all-identical justifications (copy-paste bug)
justifications = [d[k].strip() for k in _V3_JUSTIFICATION_KEYS]
if len(set(justifications)) == 1:
    result.parse_error = "all_justifications_identical"
    return result
```

Populate result:
```python
result.reasoning_internal_consistency = d["reasoning_internal_consistency"]
result.commitments_internal_consistency = d["commitments_internal_consistency"]
result.commitments_code_consistency = d["commitments_code_consistency"]
result.reasoning_code_alignment = d["reasoning_code_alignment"]

result.reasoning_internal_consistency_justification = d["reasoning_internal_consistency_justification"]
result.commitments_internal_consistency_justification = d["commitments_internal_consistency_justification"]
result.commitments_code_consistency_justification = d["commitments_code_consistency_justification"]
result.reasoning_code_alignment_justification = d["reasoning_code_alignment_justification"]

result.parse_error = None
return result
```

**`assemble_v2_result()` — use canonical mapping:**

Replace direct field access:
```python
# BEFORE
ev["mechanism_identified_dim"] = classifier.mechanism_identified
ev["commitments_extracted_dim"] = classifier.commitments_extracted
ev["commitments_satisfied_dim"] = classifier.commitments_satisfied
ev["reasoning_code_alignment_dim"] = classifier.reasoning_code_alignment

# AFTER
canonical = _extract_canonical_dims(classifier)
ev["mechanism_identified_dim"] = canonical["mechanism_identified"]
ev["commitments_extracted_dim"] = canonical["commitments_extracted"]
ev["commitments_satisfied_dim"] = canonical["commitments_satisfied"]
ev["reasoning_code_alignment_dim"] = canonical["reasoning_code_alignment"]
```

---

### 2. `core/evaluation/metrics_v2.py`

**`derive_v2_signals()` — NO PARTIAL on v3 path:**

The function receives canonical dims (already mapped). But the v3 schema only produces CORRECT/INCORRECT, never PARTIAL. The `in ("CORRECT", "PARTIAL")` check is harmless (PARTIAL never appears), but for clarity:

No change needed. The canonical mapping outputs CORRECT or INCORRECT from v3 fields. The `in ("CORRECT", "PARTIAL")` check still works correctly — it just never matches PARTIAL on v3 data. This is safe.

---

### 3. `core/pipeline/orchestration/execution_v2.py`

**`_derive_metrics()` — use canonical mapping:**
```python
# BEFORE
signals = derive_v2_signals(
    classifier_dims={
        "mechanism_identified": classifier_result.mechanism_identified,
        "commitments_extracted": classifier_result.commitments_extracted,
        "commitments_satisfied": classifier_result.commitments_satisfied,
        "reasoning_code_alignment": classifier_result.reasoning_code_alignment,
    },
    ...
)

# AFTER
from core.evaluation.evaluator_v2 import _extract_canonical_dims
signals = derive_v2_signals(
    classifier_dims=_extract_canonical_dims(classifier_result),
    ...
)
```

**`_compute_evaluation()` — use canonical mapping:**
```python
# BEFORE
if classifier_ran:
    M = (classification.mechanism_identified == "CORRECT")
    C = (classification.commitments_satisfied == "CORRECT")
    A = (classification.reasoning_code_alignment == "CORRECT")

# AFTER
if classifier_ran:
    canonical = _extract_canonical_dims(classification)
    M = (canonical["mechanism_identified"] == "CORRECT")
    C = (canonical["commitments_satisfied"] == "CORRECT")
    A = (canonical["reasoning_code_alignment"] == "CORRECT")
```

**`_assemble_result()` — add justifications to classification section:**
```python
ev["classification"] = {
    # Canonical dimensions (from mapping)
    "mechanism_identified": canonical["mechanism_identified"],
    "commitments_extracted": canonical["commitments_extracted"],
    "commitments_satisfied": canonical["commitments_satisfied"],
    "reasoning_code_alignment": canonical["reasoning_code_alignment"],
    # V3 raw dimensions (for audit — None if v2 parser used)
    "reasoning_internal_consistency": classifier_result.reasoning_internal_consistency,
    "commitments_internal_consistency": classifier_result.commitments_internal_consistency,
    "commitments_code_consistency": classifier_result.commitments_code_consistency,
    # Justifications (debug only)
    "reasoning_internal_consistency_justification": classifier_result.reasoning_internal_consistency_justification,
    "commitments_internal_consistency_justification": classifier_result.commitments_internal_consistency_justification,
    "commitments_code_consistency_justification": classifier_result.commitments_code_consistency_justification,
    "reasoning_code_alignment_justification": classifier_result.reasoning_code_alignment_justification,
    # Existing fields
    "classifier_ran": ...,
    "classifier_skipped_reason": ...,
    "classifier_mode": ...,
    "classifier_template": ...,
    "classifier_schema_variant": ...,
    "commitment_state": ...,
    "artifact_id": ...,
}
```

---

### 4. `core/pipeline/orchestration/retry_v2.py`

**Replace direct classifier field access with canonical mapping:**

Every place that reads `classifier_result.mechanism_identified` etc. must go through `_extract_canonical_dims()`. Specifically lines 508-510 and 592-608.

---

### 5. `core/prompts/component_metadata.yaml`

**Update `classify_reasoning_v3` entry:**

Remove `failure_types` (already done). No other metadata changes needed — the template variables (`root_cause`, `fix_strategy`, `task`, `code`, `classifier_mode`, `code_commitments`) are unchanged. The justification fields are outputs, not inputs.

---

### 6. Dashboard — pipeline trace view ONLY

**`dashboard/views/pipeline_trace.py`:**

Add justification display in the classifier detail section. When a case is expanded and the classifier section is shown, display justifications below the dimension values:

```python
# In classifier detail section
for dim_name, label in [
    ("reasoning_internal_consistency", "Reasoning ↔ Strategy"),
    ("commitments_internal_consistency", "Commitments ↔ Strategy"),
    ("commitments_code_consistency", "Commitments ↔ Code"),
    ("reasoning_code_alignment", "Strategy ↔ Code"),
]:
    val = row.get(f"classifier_{dim_name}", "—")
    just = row.get(f"classifier_{dim_name}_justification", "")
    st.markdown(f"**{label}:** {val}")
    if just:
        st.caption(f"  {just}")
```

**`dashboard/schema.py`:**

Add schema entries for the 4 justification fields so they're extracted from events. Dimension fields use existing `classifier_mechanism`, `classifier_commitments`, etc. schema entries which read from `payload.classification.*`.

**NO changes to:**
- `dashboard/data/evaluation_fields.py`
- `dashboard/derived_fields.py`
- `dashboard/metrics_registry.py`
- `dashboard/views/three_axis.py`
- `dashboard/views/overview.py`
- `dashboard/views/ast_analysis.py`

---

### 7. Removal audit

After implementation, run:
```bash
grep -rn "classifier_result\.mechanism_identified\|classifier_result\.commitments_extracted\|classifier_result\.commitments_satisfied" core/ --include="*.py" | grep -v __pycache__ | grep -v "_extract_canonical_dims"
```

Must return ZERO matches. Every direct access must be routed through `_extract_canonical_dims()`.

Also:
```bash
grep -rn "classification\.mechanism_identified\|classification\.commitments_extracted\|classification\.commitments_satisfied" core/ --include="*.py" | grep -v __pycache__ | grep -v "_extract_canonical_dims" | grep -v "ev\[\"classification\"\]"
```

Must return ZERO matches except for the event dict construction in `_assemble_result()`.

---

### 8. Test plan (5 tests)

| # | Test | Pass criterion |
|---|---|---|
| 1 | Parse valid v3 JSON (8 fields) | All dims and justifications populated, parse_error=None |
| 2 | Parse v3 JSON missing one field | parse_error mentions the missing field |
| 3 | `_extract_canonical_dims` with v3 result | Returns correct mapping, v2 fields None |
| 4 | Run E2E smoke (canonical_smoke_test.yaml) | 25/25 succeed, no crashes |
| 5 | Justifications in ev["classification"] but NOT in ev["mechanism_correct"] etc. | Justifications quarantined |

---

### 9. Implementation order

1. Add new fields to `ClassifierResultV2`
2. Add `_extract_canonical_dims()` to `evaluator_v2.py`
3. Rewrite `parse_classifier_v3_output()` for new 8-field schema
4. Update `assemble_v2_result()` to use canonical mapping
5. Update `_derive_metrics()` and `_compute_evaluation()` to use canonical mapping
6. Update `_assemble_result()` classification section with justifications
7. Update `retry_v2.py` to use canonical mapping
8. Update `component_metadata.yaml` if needed
9. Add justification fields to `dashboard/schema.py`
10. Add justification display to `dashboard/views/pipeline_trace.py`
11. Run removal audit (grep for direct field access)
12. Run canonical smoke test
