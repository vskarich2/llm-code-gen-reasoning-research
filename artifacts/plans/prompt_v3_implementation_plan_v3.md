# Prompt V3 Implementation Plan — v3

**Supersedes:** prompt_v3_implementation_plan_v2.md
**Date:** 2026-04-03
**Status:** PLAN ONLY

---

## Changes from v2

v2 was structurally correct. v3 adds enforcement guarantees, parser strictness, runtime validation, event field additions, and explicit invariant blocks. No structural redesign — only tightening.

| v2 gap | v3 fix |
|---|---|
| Parser accepts extra/missing keys silently | Closed-schema enforcement with exact key set validation |
| failure_type not validated at parse time | Validated against `VALID_FAILURE_TYPES` in parser |
| Retry schema alignment described, not enforced | Runtime assertions on retry artifacts |
| UNCHANGED sentinel not strictly enforced | Whitespace/case normalization rejected |
| code_commitments not canonically normalized | Normalized (stripped) before storage and classifier pass |
| code_commitments not enforced in classifier vars for retry | Assert on both first-pass and retry |
| Oracle isolation stated, not enforced | Explicit invariant: oracle_ fields blocked from metric functions |
| Missing generation_schema_variant in events | Added as logged field |
| Malformed JSON extraction underspecified | First-`{`-to-last-`}` extraction with multi-object rejection |
| Classifier runs on failed parse artifacts | Explicit guard: skip classifier if artifact invalid |
| Max commitments count not enforced | 1-5 range enforced (relaxed from 1-3 to allow model variance) |
| No parser+prompt mismatch pre-test | Added as Gate 0 requirement |

---

## 1-13. Prior Plan Sections

All content from v2 sections 1-13 is carried forward unchanged:
- §1 Implementation Strategy (parallel templates)
- §2 Generation Schema (root_cause + fix_strategy + code_commitments + files)
- §3 Exact Prompts (6 templates with section tags + component metadata)
- §4 Schema Variant Dispatch (explicit classifier_schema_variant field)
- §5 failure_type Decision (preserved in JSON output)
- §6 Blind vs Oracle Separation (oracle purely additive)
- §7 Event/Logging Additions
- §8 PARTIAL Removal Impact
- §9 Retry Generation Congruence
- §10 Sentinel Standardization
- §11 Implementation Sequence (6 gates)
- §12 Required Tests
- §13 Example Config

---

## 14. Enforcement Additions (NEW — all items below are additive to v2)

### 14.1 Closed-Schema Classifier Parser

`parse_classifier_v3_output()` must enforce exact key set and value types:

```python
import json
from core.evaluation.reasoning import VALID_FAILURE_TYPES

V3_EXPECTED_KEYS = {
    "mechanism_identified",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
    "failure_type",
}
V3_VALID_DIMS = frozenset({"CORRECT", "INCORRECT"})


def parse_classifier_v3_output(raw: str) -> ClassifierResultV2:
    result = ClassifierResultV2(
        classify_raw=raw,
        classifier_schema_variant="v3_json",
        classifier_prompt_variant="classify_reasoning_v3",
    )

    stripped = _strip_debug(raw).strip()

    # Extract JSON: first { to last }
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        result.parse_error = "no_json_object_found"
        return result

    json_str = stripped[first_brace:last_brace + 1]

    # Reject multiple JSON objects
    remainder = stripped[last_brace + 1:].strip()
    if remainder.startswith("{"):
        result.parse_error = "multiple_json_objects"
        return result

    try:
        d = json.loads(json_str)
    except json.JSONDecodeError as e:
        result.parse_error = f"json_decode_error: {e}"
        return result

    # Closed schema: exact key set
    if set(d.keys()) != V3_EXPECTED_KEYS:
        extra = set(d.keys()) - V3_EXPECTED_KEYS
        missing = V3_EXPECTED_KEYS - set(d.keys())
        result.parse_error = (
            f"schema_mismatch: extra={extra}, missing={missing}"
        )
        return result

    # Validate dimension values
    for dim_key in ("mechanism_identified", "commitments_extracted",
                    "commitments_satisfied", "reasoning_code_alignment"):
        val = d[dim_key]
        if not isinstance(val, str) or val not in V3_VALID_DIMS:
            result.parse_error = f"invalid_dimension: {dim_key}={val!r}"
            return result

    # Validate failure_type
    ft = d["failure_type"]
    if not isinstance(ft, str):
        result.parse_error = f"invalid_type: failure_type must be string, got {type(ft)}"
        return result
    if ft not in VALID_FAILURE_TYPES:
        result.parse_error = f"invalid_failure_type: {ft}"
        return result

    # All valid — populate result
    result.mechanism_identified = d["mechanism_identified"]
    result.commitments_extracted = d["commitments_extracted"]
    result.commitments_satisfied = d["commitments_satisfied"]
    result.reasoning_code_alignment = d["reasoning_code_alignment"]
    result.failure_type = ft
    result.failure_type_raw = ft
    result.parse_error = None
    return result
```

`VALID_FAILURE_TYPES` comes from `core/evaluation/reasoning.py` (already centralized). Same set used for both v2 and v3 parsers.

### 14.2 Retry Artifact Validation

After parsing retry output in `retry_v2.py`, before classifier:

```python
# Hard invariant: retry output must match generation schema
if artifact.normalized_root_cause is None or artifact.normalized_root_cause.strip() == "":
    raise ValueError(f"Retry attempt {attempt}: missing root_cause")
if artifact.normalized_fix_strategy is None or artifact.normalized_fix_strategy.strip() == "":
    raise ValueError(f"Retry attempt {attempt}: missing fix_strategy")
if parsed_gen.files_dict is None:
    raise ValueError(f"Retry attempt {attempt}: missing files_dict")
expected_keys = set(code_files.keys())
actual_keys = set(parsed_gen.files_dict.keys())
if actual_keys != expected_keys:
    raise ValueError(
        f"Retry attempt {attempt}: files key mismatch: "
        f"expected={expected_keys}, got={actual_keys}"
    )
```

This goes in `retry_v2.py` after `normalize_generation_v2()` call for each attempt.

Note: this validation raises, which causes the attempt to fail cleanly and move to next retry or final classification. It does not silently drop.

### 14.3 UNCHANGED Sentinel Strictness

In `reconstructor.py:reconstruct_strict()`, add to the UNCHANGED detection logic:

```python
# Exact match only — reject whitespace/case variations
if value.strip().upper() == "UNCHANGED" and value != "UNCHANGED":
    return ReconstructionResult(
        status="RECON_SENTINEL_MISMATCH",
        error=f"File {path}: near-match UNCHANGED sentinel: {value!r}. Must be exactly 'UNCHANGED'."
    )
```

This prevents `"unchanged"`, `"UNCHANGED\n"`, `" UNCHANGED "` from being silently accepted or silently treated as code.

### 14.4 Commitment Normalization

In `reasoning_v2.py:normalize_generation_v2()`, after extracting raw commitments:

```python
# Normalize commitments: strip whitespace, reject empty
normalized_code_commitments = [
    c.strip() for c in raw_code_commitments
    if isinstance(c, str) and c.strip()
]

# Enforce count: 1-5 (allow slight model variance above 3)
if len(normalized_code_commitments) > 5:
    normalized_code_commitments = normalized_code_commitments[:5]
    normalization_notes.append("truncated_commitments_to_5")
```

For classifier pass, in `build_classifier_v2_vars()`:

```python
if artifact.normalized_code_commitments:
    variables["code_commitments"] = "; ".join(
        artifact.normalized_code_commitments
    )
```

### 14.5 Classifier Vars Assertion

In `build_classifier_v2_vars()`, after building variables dict:

```python
# Invariant: code_commitments must be present for v3 conditions
# (may be empty string for v2 conditions where model didn't produce them)
assert "code_commitments" in variables or variables.get("code") is None
```

In both `execution_v2.py` and `retry_v2.py`, before classifier call:

```python
assert classifier_vars is not None, "classifier_vars must not be None"
```

### 14.6 Classifier Skip on Parse Failure

In `execution_v2.py` and `retry_v2.py`, before classifier call:

```python
# Do not run classifier if generation parsing failed
if parsed_gen.parse_status != "success":
    classifier_result = ClassifierResultV2(
        parse_error="skipped:generation_parse_failed",
        classifier_schema_variant=config.evaluation.classifier_schema_variant,
    )
    # skip classifier LLM call
```

This is already partially implemented (the `build_classifier_v2_vars` returns None when reasoning fields are missing). The explicit guard makes it a hard invariant.

### 14.7 Oracle Isolation Invariant

Explicit code invariant — add as comment block in `metrics_v2.py`:

```python
# INVARIANT: oracle_ fields must NEVER be used in this module.
# Oracle results are stored in event["extra"]["oracle_*"] and are
# purely additive analysis metadata. They do not affect:
#   - derive_v2_signals()
#   - _compute_v2_category()
#   - _compute_legacy_compat()
#   - reasoning_correct_compat
# If oracle results are needed for analysis, they must be consumed
# by separate analysis code that explicitly joins oracle data.
```

Additionally, `assemble_v2_result()` must NOT read any `oracle_*` fields. Oracle fields are added to the event dict AFTER `assemble_v2_result()` returns, in the caller (`execution_v2.py`).

### 14.8 generation_schema_variant Event Field

Add to `assemble_v2_result()`:

```python
# Generation schema variant for analysis segmentation
condition = ev.get("condition", "")
if condition.endswith("_v3") or condition == "baseline_v3":
    ev["generation_schema_variant"] = "v3"
else:
    ev["generation_schema_variant"] = "v2"
```

Or more robustly, add to `EvaluationConfig`:

```python
generation_schema_variant: str = "v2"  # "v2" | "v3"
```

Parsed from YAML alongside `classifier_schema_variant`. Logged in every event.

### 14.9 Analysis Segmentation Requirement

**Hard rule for all analysis code:**

Any aggregate analysis (pass_rate, LEG_rate, etc.) that spans multiple experiments MUST group by:
- `condition` (which generation prompt)
- `classifier_schema_variant` (which classifier)
- `generation_schema_variant` (which generation schema)

Pooling v2 and v3 runs without explicit version segmentation is forbidden. This applies to:
- `analysis/load_logs.py`
- `dashboard/metrics_registry.py`
- Any ad-hoc analysis scripts

No code changes needed — this is a usage rule, not a code change. But it must be documented.

### 14.10 Malformed JSON Extraction

The parser (§14.1) uses first-`{`-to-last-`}` extraction. Additional guards:

```python
# Reject if extracted JSON contains nested raw text that isn't JSON
# (e.g., model outputs explanation then JSON then more explanation)
pre_json = stripped[:first_brace].strip()
if pre_json and not pre_json.startswith(("```", "---", "#")):
    # Non-trivial text before JSON — still parse but log warning
    pass  # Accept — models sometimes prepend a line
```

If multiple JSON objects exist (checked by `remainder.startswith("{")`), reject. This prevents the parser from picking the wrong object.

### 14.11 Parser + Prompt Mismatch Pre-Test

Added to Gate 0 (pre-flight):

```
Gate 0 step 4: Parser golden test
  - Craft 3 valid v3 classifier JSON strings
  - Feed each into parse_classifier_v3_output()
  - Assert all parse cleanly with correct dimensions + failure_type
  - Craft 3 malformed strings (missing key, extra key, PARTIAL value)
  - Assert all produce parse_error
  - Craft 1 string with invalid failure_type
  - Assert parse_error = "invalid_failure_type"
```

This runs before any LLM calls.

---

## 15. HARD INVARIANTS (verbatim, non-negotiable)

### For every successful generation artifact:

- `root_cause` MUST exist and be non-empty
- `fix_strategy` MUST exist and be non-empty
- `code_commitments` MUST exist and contain 1-5 items
- `files` MUST contain all expected file keys
- Unchanged files MUST be exactly `"UNCHANGED"` (case-sensitive, no whitespace)
- Modified files MUST contain full file contents (not diffs, not partial)

### For every classifier output (v3):

- JSON MUST contain EXACTLY 5 keys: `mechanism_identified`, `commitments_extracted`, `commitments_satisfied`, `reasoning_code_alignment`, `failure_type`
- First 4 values MUST be in `{"CORRECT", "INCORRECT"}`
- `failure_type` MUST be in `VALID_FAILURE_TYPES`
- No extra keys, no missing keys, no null values

### For every retry artifact:

- Schema MUST match generation schema exactly (same 4 required fields)
- File keys MUST match expected set
- No field omissions allowed
- Same UNCHANGED/full-content rules apply

### For every event:

- `classifier_schema_variant` MUST be set (`"v2_5line"` or `"v3_json"`)
- `generation_schema_variant` MUST be set (`"v2"` or `"v3"`)
- `condition` MUST encode prompt family (`baseline_v2` vs `baseline_v3`)
- `oracle_*` fields MUST NOT affect `mechanism_correct`, `commitments_valid`, `alignment_positive`, `v2_category`, or `reasoning_correct_compat`

### For all analysis:

- Never pool v2 and v3 LEG rates without explicit version segmentation
- Always group by `classifier_schema_variant` and `generation_schema_variant`
- Treat v2→v3 LEG rate differences as intentional recalibration, not bugs

---

## 16. Updated Implementation Sequence

### Gate 0: Pre-flight (before any file changes)

1. Render all 6 new templates through compiler with sample variables → verify valid output
2. Verify manifest entries load without errors
3. Verify condition registry entries are syntactically valid
4. **Parser golden tests** (§14.11): 3 valid + 3 malformed + 1 invalid failure_type → all assertions pass
5. Dry-run prompt compilation check through actual compiler for all 6 templates

### Gate 1: Templates (zero risk, additive only)

6. Create 6 new `.j2` files
7. Add 6 component metadata entries
8. Add manifest entries
9. Add condition registry entries

### Gate 2: Parser + contracts + enforcement (additive)

10. Add `V3_VALID_DIMENSION_VALUES` to contracts
11. Add `parse_classifier_v3_output()` with closed-schema enforcement (§14.1)
12. Add `classifier_schema_variant` + `generation_schema_variant` to `EvaluationConfig` + parser
13. Update `build_classifier_v2_vars()` to pass `code_commitments`
14. Add commitment normalization to `reasoning_v2.py` (§14.4)
15. Add UNCHANGED strictness to `reconstructor.py` (§14.3)

### Gate 3: Pipeline wiring (conditional logic)

16. Update `execution_v2.py`: parser selection by `classifier_schema_variant`
17. Update `execution_v2.py`: schema_line for v3 conditions
18. Update `execution_v2.py`: classifier skip on parse failure (§14.6)
19. Update `execution_v2.py`: log `generation_schema_variant` (§14.8)
20. Update `retry_v2.py`: v3 critique dispatch + v3 schema_line
21. Update `retry_v2.py`: retry artifact validation (§14.2)

### Gate 4: Single-case smoke test

22. Run `baseline_v3` on `partial_update_a`, 1 trial
23. Verify: generation has all 4 fields, files use UNCHANGED, classifier returns valid v3 JSON, event has both schema variant fields, metrics compute

### Gate 5: Comparison run

24. Run `baseline_v2` + `baseline_v3` + `leg_reduction_lean_v3` on 2 cases, 2 trials
25. Verify: both schemas produce valid events, `classifier_schema_variant` differs, metrics compute for both

### Gate 6: Oracle (behind flag)

26. Wire oracle per integration plan
27. Run with `evaluation.oracle.enabled: true`
28. Verify: oracle fields in event `extra`, oracle fields NOT in `reasoning` section, `v2_category` unaffected

---

## 17. Updated Test Matrix

### Generation path

| Test | Enforcement point |
|---|---|
| `baseline_v3` emits `root_cause`, `fix_strategy`, `code_commitments`, `files` | parser_v2 + reasoning_v2 |
| All file keys present | Retry artifact validation (§14.2) |
| UNCHANGED exact match (case, whitespace) | reconstructor (§14.3) |
| Modified files contain full contents | reconstructor existing gates |
| Retry output matches first-pass schema | Retry artifact validation (§14.2) |
| `code_commitments` count 1-5 | reasoning_v2 normalization (§14.4) |
| `lean_v3` output has no `risk_check` | reasoning_v2 tolerates absent field |

### Blind classifier

| Test | Enforcement point |
|---|---|
| Valid v3 JSON parses cleanly | parse_classifier_v3_output (§14.1) |
| Extra keys → parse_error | Closed schema check |
| Missing key → parse_error | Closed schema check |
| `"PARTIAL"` → parse_error | V3_VALID_DIMS check |
| Invalid failure_type → parse_error | VALID_FAILURE_TYPES check |
| Extra text before JSON → still parses (first-{-to-last-}) | JSON extraction logic |
| Multiple JSON objects → parse_error | Remainder check |
| Non-string failure_type → parse_error | Type check |

### Oracle classifier

| Test | Enforcement point |
|---|---|
| Same JSON schema as blind | Same parser |
| Oracle fields in `extra`, not `reasoning` | assemble_v2_result wiring |
| `v2_category` unchanged with oracle enabled | Oracle isolation invariant (§14.7) |

### Critique

| Test | Enforcement point |
|---|---|
| One sentence or `NO_MISMATCH` | `_truncate_to_one_sentence()` safety net |
| `NO_WEAKNESS` backward compat | `retry_v2.py:288` existing check |

### Backward compatibility

| Test | Enforcement point |
|---|---|
| Old v2 semicolon output → v2 parser works | `parse_classifier_v2_output()` unchanged |
| Mixed v2+v3 experiment → both analyzable | `classifier_schema_variant` in events |
| `generation_schema_variant` logged | `assemble_v2_result` |
| Analysis segmentation by schema variant | load_logs reads from event fields |
