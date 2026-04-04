# V3 Classifier Schema Migration Plan v1

## 1. System Touchpoints

Every module that depends on classifier output, with exact file:function:line references.

### Core pipeline (classifier output consumers)

| File | Function | Lines | What it reads | What breaks |
|---|---|---|---|---|
| `core/evaluation/evaluator_v2.py` | `ClassifierResultV2` | 25-43 | Field definitions | Must add 4 new fields + 4 justification fields |
| `core/evaluation/evaluator_v2.py` | `parse_classifier_v3_output()` | 297-368 | Parses JSON → result | Must parse new 8-field schema |
| `core/evaluation/evaluator_v2.py` | `assemble_v2_result()` | 375-459 | Reads all 4 dims from result | Must emit new field names |
| `core/evaluation/metrics_v2.py` | `derive_v2_signals()` | 31-85 | `mechanism_identified`, `commitments_extracted`, `commitments_satisfied`, `reasoning_code_alignment` | Formula inputs change |
| `core/evaluation/metrics_v2.py` | `V2Signals` dataclass | 13-22 | Field definitions | Must reflect new signal names |
| `core/pipeline/orchestration/execution_v2.py` | `_compute_evaluation()` | 554-638 | `classification.mechanism_identified`, `classification.commitments_satisfied`, `classification.reasoning_code_alignment` | M, C, A signals change |
| `core/pipeline/orchestration/execution_v2.py` | `_derive_metrics()` | 516-534 | Passes 4 dims dict to `derive_v2_signals` | Dict keys change |
| `core/pipeline/orchestration/execution_v2.py` | `_assemble_result()` | 744-835 | Builds `ev["classification"]` section | Field names in section change |
| `core/pipeline/orchestration/retry_v2.py` | `run_retry_v2()` | 508-510, 592-608 | Reads classifier dims for trajectory | Field names change |
| `core/evaluation/materialize.py` | `build_attempt_table()` | 129-150 | Reads from evaluation/classification/payload | Column names change |

### Dashboard

| File | Function | Lines | What it reads |
|---|---|---|---|
| `dashboard/schema.py` | Field registry | 118-133, 389-409 | `mechanism_dim`, `commitments_dim`, `satisfied_dim`, `alignment_dim`, `classifier_mechanism`, etc. |
| `dashboard/data/evaluation_fields.py` | `add_three_axis_fields()` | 88-91 | `mechanism_dim`, `satisfied_dim`, `alignment_dim` → derives `mechanism_correct`, `commitments_valid`, `alignment_positive` |
| `dashboard/derived_fields.py` | `_is_leg()`, `_is_lucky_fix()` | 11-20 | `reasoning_correct` |
| `dashboard/metrics_registry.py` | `_reasoning_rate()` | 27-29 | `reasoning_correct` |
| `dashboard/views/pipeline_trace.py` | Classifier parsing | 41-44 | Semicolon-delimited dims |
| `dashboard/views/three_axis.py` | 3-axis visualization | 54-177 | `mechanism_correct`, `commitments_valid`, `alignment_positive`, `reasoning_sufficient` |
| `dashboard/views/overview.py` | Cluster analysis | 98+ | `reasoning_sufficient`, `reasoning_correct` |
| `core/logging_/v2_dashboard.py` | S5 section | 153-156 | `mechanism_identified_dim`, `commitments_extracted_dim`, `commitments_satisfied_dim`, `reasoning_code_alignment_dim` |

### Other

| File | What it reads |
|---|---|
| `core/contracts/contracts_v2.py` | Dimension field names in contract validation |
| `core/evaluation/oracle_inline.py` | `mechanism_identified` for oracle truth comparison |
| `scripts/run_classifier_probes.py` | Reads dims for analysis |
| `scripts/global_cal_analysis.py` | Reads dims for calibration |

---

## 2. Current Dependency Analysis

### `mechanism_identified` (OLD)

**Used in:**
- `_compute_evaluation()`: `M = (classification.mechanism_identified == "CORRECT")` — feeds into R = M ∧ C → outcome_class
- `derive_v2_signals()`: `mechanism_correct = (m == "CORRECT")` → feeds into `reasoning_correct_compat`
- `assemble_v2_result()`: stored as `ev["mechanism_identified_dim"]` and `ev["mechanism_correct"]`
- `ev["classification"]["mechanism_identified"]`: first-class section
- Dashboard: `mechanism_dim` column → `mechanism_correct` boolean

**If removed:** R axis breaks. Outcome class partition breaks. LEG computation breaks. reasoning_correct breaks. All downstream metrics break.

### `commitments_extracted` (OLD)

**Used in:**
- `derive_v2_signals()`: `commitments_valid = (ce in ("CORRECT", "PARTIAL"))` — feeds into `reasoning_correct_compat`
- `assemble_v2_result()`: stored as `ev["commitments_extracted_dim"]` and `ev["commitments_valid"]`
- Dashboard: `commitments_dim` column

**CRITICAL NOTE:** In `_compute_evaluation()`, the C axis uses `commitments_satisfied`, NOT `commitments_extracted`. But in `derive_v2_signals()`, `commitments_valid` uses `commitments_extracted`. This is an existing inconsistency:
- Pipeline R = M ∧ C where C = commitments_satisfied
- Signals reasoning_correct_compat = M ∧ commitments_valid(extracted) ∧ A

**If removed:** `commitments_valid` signal breaks. `reasoning_correct_compat` breaks. But pipeline R axis (which uses `commitments_satisfied`) is unaffected.

### `commitments_satisfied` (OLD)

**Used in:**
- `_compute_evaluation()`: `C = (classification.commitments_satisfied == "CORRECT")` — directly in R = M ∧ C
- `derive_v2_signals()`: `commitments_satisfied_positive = (cs in ("CORRECT", "PARTIAL"))` — supporting signal only
- Dashboard `satisfied_dim` column → `commitments_valid` in V2 fallback path

**If removed:** Pipeline R axis breaks (C gone). Outcome class breaks.

### `reasoning_code_alignment` (OLD — RETAINED)

**Used in:**
- `_compute_evaluation()`: `A = (classification.reasoning_code_alignment == "CORRECT")` — only for LEG subtyping
- `derive_v2_signals()`: `alignment_positive = (rca == "CORRECT")` — feeds into `reasoning_correct_compat`
- Dashboard `alignment_dim` column

**This field is RETAINED in the new schema with the same name.** No migration needed for this field.

---

## 3. Field Mapping Strategy

### OLD → NEW mapping

| Old Field | New Field | Semantic Change |
|---|---|---|
| `mechanism_identified` | `reasoning_internal_consistency` | Was: "did model identify the bug?" Now: "does root cause logically support fix strategy?" — **internal consistency, not correctness** |
| `commitments_extracted` | `commitments_internal_consistency` | Was: "are commitments specific?" Now: "do commitments logically follow from fix strategy?" |
| `commitments_satisfied` | `commitments_code_consistency` | Was: "does code implement commitments?" Now: same but explicitly framed as consistency check |
| `reasoning_code_alignment` | `reasoning_code_alignment` | **UNCHANGED** — same field, same semantics |

### NEW fields (no old equivalent)

| Field | Purpose | Metric impact |
|---|---|---|
| `reasoning_internal_consistency_justification` | Debug/audit only | NONE — must not affect any metric |
| `commitments_internal_consistency_justification` | Debug/audit only | NONE |
| `commitments_code_consistency_justification` | Debug/audit only | NONE |
| `reasoning_code_alignment_justification` | Debug/audit only | NONE |

### Key semantic shift

The old schema asked "is the model's reasoning CORRECT (against ground truth)?" The new schema asks "is the model's reasoning INTERNALLY CONSISTENT?" This is a fundamental reframing. The field mapping preserves structural roles but changes interpretation.

---

## 4. Metric Redefinition

### Current formulas (to be replaced)

**Pipeline `_compute_evaluation()`:**
```
M = (mechanism_identified == "CORRECT")
C = (commitments_satisfied == "CORRECT")
A = (reasoning_code_alignment == "CORRECT")
R = M and C
```

**Signals `derive_v2_signals()`:**
```
mechanism_correct = (mechanism_identified == "CORRECT")
commitments_valid = (commitments_extracted in ("CORRECT", "PARTIAL"))
alignment_positive = (reasoning_code_alignment == "CORRECT")
reasoning_correct_compat = mechanism_correct and commitments_valid and alignment_positive
```

### New formulas

**Pipeline `_compute_evaluation()`:**
```
M = (reasoning_internal_consistency == "CORRECT")
C = (commitments_code_consistency == "CORRECT")
A = (reasoning_code_alignment == "CORRECT")
R = M and C
```

**Signals `derive_v2_signals()`:**
```
mechanism_correct = (reasoning_internal_consistency == "CORRECT")
commitments_valid = (commitments_internal_consistency in ("CORRECT", "PARTIAL"))
alignment_positive = (reasoning_code_alignment == "CORRECT")
commitments_satisfied_positive = (commitments_code_consistency in ("CORRECT", "PARTIAL"))
reasoning_correct_compat = mechanism_correct and commitments_valid and alignment_positive
```

**Derived boolean names DO NOT CHANGE.** `mechanism_correct`, `commitments_valid`, `alignment_positive`, `reasoning_sufficient` remain the same boolean field names. Only their input classifier field names change. This means:
- Dashboard code that reads `mechanism_correct`, `commitments_valid`, etc. does NOT need to change
- `_is_leg()`, `_is_lucky_fix()`, `reasoning_rate` — no changes needed
- `outcome_class` computation — no changes needed
- LEG subtyping — no changes needed (A is unchanged)

### What CANNOT be computed

Nothing. All four new fields map structurally to the four old fields. The metric formulas are identical in structure — only the input field names change inside the parser and signal derivation.

---

## 5. Parser Plan

### V3 JSON parser (`parse_classifier_v3_output`)

**Expected keys (new):**
```python
_V3_EXPECTED_KEYS = {
    "reasoning_internal_consistency",
    "commitments_internal_consistency",
    "commitments_code_consistency",
    "reasoning_code_alignment",
}
```

Plus 4 optional justification keys:
```python
_V3_JUSTIFICATION_KEYS = {
    "reasoning_internal_consistency_justification",
    "commitments_internal_consistency_justification",
    "commitments_code_consistency_justification",
    "reasoning_code_alignment_justification",
}
```

**Validation rules:**
1. JSON must start with `{`, end with `}`, no trailing text
2. All 4 dimension keys MUST be present (missing → parse_error)
3. All 4 justification keys MUST be present (missing → parse_error)
4. Dimension values MUST be `"CORRECT"` or `"INCORRECT"` (invalid → parse_error)
5. Justification values MUST be non-empty strings (empty → parse_error)
6. Extra keys beyond the 8 → tolerated (lenient, for forward compat)
7. Legacy `failure_type` if present → stored in `failure_type_raw`, ignored

**Failure modes:**
- Missing dimension key: `"schema_mismatch: missing={key}"`
- Invalid dimension value: `"invalid_dimension: {key}={val}"`
- Missing justification: `"schema_mismatch: missing={key}_justification"`
- Empty justification: `"empty_justification: {key}"`

### V2 semicolon parser (`parse_classifier_v2_output`)

**No change needed for the v2 parser itself.** It parses old-format responses. If `classifier_schema_variant` is `v2_semicolon`, the old parser runs. If `v3_json`, the new parser runs. This is already the routing logic.

However: the v2 parser produces `ClassifierResultV2` with old field names. The signal derivation and evaluation code must handle both old and new field names based on which parser ran. See Section 6.

---

## 6. Data Model / Structure Changes

### ClassifierResultV2 — add new fields

```python
@dataclass
class ClassifierResultV2:
    # NEW V3 dimensions (None when v2 parser used)
    reasoning_internal_consistency: str | None = None
    commitments_internal_consistency: str | None = None
    commitments_code_consistency: str | None = None
    reasoning_code_alignment: str | None = None  # RETAINED — same name

    # NEW V3 justifications (debug only, never affect metrics)
    reasoning_internal_consistency_justification: str = ""
    commitments_internal_consistency_justification: str = ""
    commitments_code_consistency_justification: str = ""
    reasoning_code_alignment_justification: str = ""

    # OLD V2 dimensions (None when v3 parser used)
    mechanism_identified: str | None = None
    commitments_extracted: str | None = None
    commitments_satisfied: str | None = None
    # reasoning_code_alignment shared with v3 above

    # ... rest of existing fields unchanged
```

### Signal derivation — canonical mapping function

Add a function that maps classifier result → 4 canonical signals regardless of which parser ran:

```python
def _extract_canonical_dims(result: ClassifierResultV2) -> dict:
    """Extract canonical dimension signals from classifier result.

    Maps V3 field names to the canonical signal names used by
    derive_v2_signals() and _compute_evaluation().
    Falls back to V2 field names for old events.

    Returns dict with keys: mechanism_identified, commitments_extracted,
    commitments_satisfied, reasoning_code_alignment — these are the
    canonical signal names consumed by all downstream logic.
    """
    if result.reasoning_internal_consistency is not None:
        # V3 path
        return {
            "mechanism_identified": result.reasoning_internal_consistency,
            "commitments_extracted": result.commitments_internal_consistency,
            "commitments_satisfied": result.commitments_code_consistency,
            "reasoning_code_alignment": result.reasoning_code_alignment,
        }
    else:
        # V2 path (old events)
        return {
            "mechanism_identified": result.mechanism_identified,
            "commitments_extracted": result.commitments_extracted,
            "commitments_satisfied": result.commitments_satisfied,
            "reasoning_code_alignment": result.reasoning_code_alignment,
        }
```

**This is the ONLY place the field mapping exists.** All downstream code (`derive_v2_signals`, `_compute_evaluation`, `_derive_metrics`) calls this function and receives canonical signal names. They do NOT need to know about v3 field names.

### Propagation through pipeline

1. `parse_classifier_v3_output()` populates `result.reasoning_internal_consistency` etc.
2. `_derive_metrics()` calls `_extract_canonical_dims(result)` → gets canonical dict
3. `_compute_evaluation()` calls `_extract_canonical_dims(result)` → gets canonical dict
4. `assemble_v2_result()` writes both old-name `_dim` fields (from canonical mapping) AND new-name fields (from result directly)
5. `ev["classification"]` section writes new field names directly from result

---

## 7. Logging Plan

### Event structure (case.end events)

**Top-level payload fields (backward compat, via `assemble_v2_result`):**
```
ev["mechanism_identified_dim"] → canonical mapping value
ev["commitments_extracted_dim"] → canonical mapping value
ev["commitments_satisfied_dim"] → canonical mapping value
ev["reasoning_code_alignment_dim"] → canonical mapping value
ev["mechanism_correct"] → bool (derived)
ev["commitments_valid"] → bool (derived)
ev["alignment_positive"] → bool (derived)
```

**Classification section (new, via `_assemble_result`):**
```
ev["classification"]["reasoning_internal_consistency"] → raw v3 value
ev["classification"]["commitments_internal_consistency"] → raw v3 value
ev["classification"]["commitments_code_consistency"] → raw v3 value
ev["classification"]["reasoning_code_alignment"] → raw v3 value
ev["classification"]["reasoning_internal_consistency_justification"] → string
ev["classification"]["commitments_internal_consistency_justification"] → string
ev["classification"]["commitments_code_consistency_justification"] → string
ev["classification"]["reasoning_code_alignment_justification"] → string
```

**Justifications are ONLY in the classification section.** They NEVER appear in top-level payload fields, derived signals, or metrics.

---

## 8. Dashboard Plan

### Justification display

Justifications appear in:
1. **Pipeline Trace tab** — in the classifier detail expander, below the dimension values
2. **Case Explorer tab** — in the detail panel when a case is expanded
3. **Three-Axis tab** — NOT displayed (metrics only, no justifications)

Display format:
```
Reasoning ↔ Strategy: CORRECT
  "The fix strategy of using DEFAULTS.copy() directly addresses the stated root cause of aliased mutation."

Commitments ↔ Strategy: CORRECT
  "The commitment to copy on return follows logically from the strategy of eliminating shared references."

Commitments ↔ Code: INCORRECT
  "The code uses dict(DEFAULTS) but the commitment states DEFAULTS.copy(), which are different methods."

Strategy ↔ Code: CORRECT
  "The code changes match the stated fix of breaking the alias by copying."
```

### Justifications MUST NOT appear in:
- Metric computations
- Heatmaps
- Aggregation tables
- Any numeric column
- Any filter that affects data selection

### Schema registry additions

```python
"classifier_reasoning_consistency": {
    "source": "payload.classification.reasoning_internal_consistency",
    "type": "str",
},
"classifier_commitments_consistency": {
    "source": "payload.classification.commitments_internal_consistency",
    "type": "str",
},
"classifier_code_consistency": {
    "source": "payload.classification.commitments_code_consistency",
    "type": "str",
},
# Justifications
"classifier_reasoning_justification": {
    "source": "payload.classification.reasoning_internal_consistency_justification",
    "type": "str",
},
# ... etc for all 4
```

---

## 9. Backward Compatibility Strategy

### This is a VERSIONED migration, not a hard cut.

**Version selection:** `config.evaluation.classifier_schema_variant`
- `v3_json` → uses new v3 parser with new field names
- `v2_semicolon` → uses old v2 parser with old field names

**Both parsers populate `ClassifierResultV2`.** The `_extract_canonical_dims()` function handles both. Downstream code is version-agnostic.

**Old events (already logged):** Continue to work. The dashboard reads both `payload.*_dim` fields (old) and `payload.classification.*` fields (new). The V2 fallback path in `add_three_axis_fields()` reads `mechanism_dim` etc. which are still populated from the canonical mapping.

**New events:** Populate both old-name `_dim` fields (for backward compat) and new-name fields in the classification section.

**Component metadata:** `classify_reasoning_v3.j2` metadata must be updated to remove `failure_types` from required_inputs (already done) and to NOT list the justification fields as required_inputs (they are outputs, not inputs).

---

## 10. Test Plan

| # | Test | What it validates |
|---|---|---|
| 1 | Parse v3 JSON with 8 fields (4 dims + 4 justifications) | New parser accepts complete response |
| 2 | Parse v3 JSON with 4 dims only (no justifications) | Parser rejects: justifications are required |
| 3 | Parse v3 JSON with invalid dimension value | Parser rejects with clear error |
| 4 | Parse v3 JSON with empty justification | Parser rejects with clear error |
| 5 | Parse v3 JSON with legacy `failure_type` extra key | Parser accepts (lenient on extra keys) |
| 6 | Parse v2 semicolon format (old) | Old parser still works unchanged |
| 7 | `_extract_canonical_dims()` with v3 result | Returns canonical dict with correct mapping |
| 8 | `_extract_canonical_dims()` with v2 result | Returns canonical dict with old field names |
| 9 | `derive_v2_signals()` with v3-mapped dims | Produces identical signal structure |
| 10 | `_compute_evaluation()` with v3-mapped dims | Produces correct outcome_class |
| 11 | Justifications NOT in `ev["mechanism_correct"]` etc. | Justifications isolated from metrics |
| 12 | Justifications present in `ev["classification"]` | Justifications logged correctly |
| 13 | Old events load in dashboard | V2 fallback path works |
| 14 | New events load in dashboard | V3 fields populate correctly |
| 15 | LEG computation identical before/after | `outcome_class == "LEG"` rate unchanged on same data |
| 16 | E2E smoke: 5 cases with v3 classifier | All 25 work items succeed with populated fields |

---

## 11. Risk Analysis

### Risk 1: Silent metric drift

**Threat:** New field names accidentally change which signal feeds into reasoning_correct, causing LEG rate to shift without anyone noticing.

**Prevention:** `_extract_canonical_dims()` is the SINGLE mapping point. All downstream code receives canonical names. The mapping is explicit, testable, and auditable. Test #15 validates LEG rate equivalence.

### Risk 2: Justification contamination

**Threat:** Justification strings leak into metric computation, boolean derivation, or aggregation logic.

**Prevention:** Justifications live ONLY on the result object and in `ev["classification"]`. They are NEVER in the canonical dims dict, NEVER in V2Signals, NEVER in top-level payload fields, NEVER in dashboard metric columns. Test #11 validates this.

### Risk 3: Legacy field leakage

**Threat:** Old events with `mechanism_identified` fail to load in new dashboard code.

**Prevention:** `_extract_canonical_dims()` checks `reasoning_internal_consistency is not None` to detect v3 vs v2. V2 events get the old-name path. Dashboard `add_three_axis_fields()` V2 fallback path reads `mechanism_dim` etc. which are always populated regardless of version.

### Risk 4: Partial field population

**Threat:** V3 parser populates `reasoning_internal_consistency` but leaves `mechanism_identified` as None. Code that reads `mechanism_identified` directly (not through `_extract_canonical_dims`) gets None and breaks.

**Prevention:** Audit every direct access to `classifier_result.mechanism_identified` and route through `_extract_canonical_dims()` instead. The canonical mapping function is the firewall. Direct field access on the result object is forbidden outside the mapping function.

### Risk 5: Component metadata drift

**Threat:** `classify_reasoning_v3.j2` template changes fields but `component_metadata.yaml` still lists old required_inputs.

**Prevention:** Already addressed — metadata validation runs unconditionally at registry load. Undeclared variables in the template crash immediately. The metadata must be updated atomically with the template.
