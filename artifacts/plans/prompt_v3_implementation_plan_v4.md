# Prompt V3 Implementation Plan — v4.1 (FINAL)

**Supersedes:** prompt_v3_implementation_plan_v3.md
**Date:** 2026-04-03
**Status:** PLAN ONLY
**v4.1 changes:** (1) Removed unsafe brace-counting JSON validation, replaced with json.loads + strict prefix/trailing/schema checks. (2) Added generation schema validation stage before reconstruction.

---

## Changes from v3

v3 was structurally and enforcement-correct. v4 eliminates the last edge-case drift and debugging traps. No redesign — only final tightening.

| v3 gap | v4 fix |
|---|---|
| generation_schema_variant inferred from condition name | Explicit config field, no string heuristics |
| Commitment normalization allows duplicates/whitespace | Canonicalized: whitespace-collapsed, deduplicated by lowercase |
| JSON extraction tolerates prefix text | Strict: JSON must start at position 0 after stripping |
| files dict values not type-checked | Must be strings |
| Classifier input code may differ from execution code | Single canonical_code_snapshot invariant |
| Retry validation crashes entire run | Fails attempt, continues loop |
| Commitments not enforced for v3 classifier at runtime | Assert non-empty before classifier call |
| VALID_FAILURE_TYPES provenance unspecified | Single canonical source in contracts |
| Classifier parse_error allows partial metric computation | Hard skip on parse_error |
| Prompt identity not fully logged | generation_prompt_name + classifier_prompt_name + critique_prompt_name |
| Multiple/nested JSON not fully rejected | Removed unsafe brace counting — json.loads + prefix/trailing/schema is sufficient |
| Generation output not validated before reconstruction | Explicit validate_generation_schema_v3() stage added |

---

## All prior sections (1-13, 14, 15, 16, 17) carried forward from v3

Unchanged. This document adds §18 only.

---

## 18. Final Corrections (v4 additions)

### 18.1 generation_schema_variant from config, not condition name

Remove:
```python
if condition.endswith("_v3") or condition == "baseline_v3":
    ev["generation_schema_variant"] = "v3"
```

Replace with `EvaluationConfig` field:

```python
@dataclass
class EvaluationConfig:
    # ... existing ...
    generation_schema_variant: str = "v2"  # "v2" | "v3"
```

Config parsing:
```python
generation_schema_variant=eval_section.get("generation_schema_variant", "v2"),
```

Event logging:
```python
ev["generation_schema_variant"] = config.evaluation.generation_schema_variant
```

YAML usage:
```yaml
evaluation:
  generation_schema_variant: "v3"
  classifier_schema_variant: "v3_json"
```

No condition-name inference. No string heuristics.

### 18.2 Commitment canonicalization

Replace v3's simple strip with:

```python
normalized = []
seen = set()

for c in raw_code_commitments:
    if not isinstance(c, str):
        continue
    s = " ".join(c.strip().split())  # collapse whitespace
    s_lower = s.lower()
    if s_lower and s_lower not in seen:
        seen.add(s_lower)
        normalized.append(s)

if len(normalized) > 5:
    normalized = normalized[:5]
    normalization_notes.append("truncated_commitments_to_5")
```

Stores original casing but deduplicates by lowercase. Whitespace is normalized. Empty strings rejected.

### 18.3 Strict JSON-at-position-0

Replace v3's permissive prefix handling with:

```python
stripped = _strip_debug(raw).strip()

first_brace = stripped.find("{")
if first_brace != 0:
    result.parse_error = f"non_json_prefix: text before JSON at position {first_brace}"
    return result

last_brace = stripped.rfind("}")
if last_brace == -1:
    result.parse_error = "no_closing_brace"
    return result

json_str = stripped[:last_brace + 1]
trailing = stripped[last_brace + 1:].strip()
if trailing:
    result.parse_error = f"trailing_text_after_json: {trailing[:50]!r}"
    return result
```

No prefix text tolerated. No trailing text tolerated. JSON must be the entire response (after debug stripping).

### 18.4 files dict value type enforcement

In `parser_v2.py` or `reconstructor.py`, after extracting `files_dict`:

```python
for path, content in files_dict.items():
    if not isinstance(content, str):
        raise ValueError(
            f"File {path}: expected str, got {type(content).__name__}. "
            f"Model may have output a list, dict, or null."
        )
```

This catches models outputting `null`, `[]`, `{}`, or nested structures for file values.

### 18.5 Single canonical_code_snapshot invariant

After reconstruction produces the final code, store it as one immutable reference:

```python
canonical_code_snapshot = recon.get_merged_code()  # or equivalent
```

This SAME object is passed to:
- `exec_canonical()` for execution
- `build_classifier_v2_vars()` as the `code` variable
- event logging as `_extracted_code`

Enforcement:

```python
# In execution_v2.py, after reconstruction:
canonical_code = _get_canonical_code(recon, parsed_gen)

# Execution
exec_result = exec_canonical(case, parsed_gen, recon, config, logger, attempt)

# Classifier — must use same code
classifier_vars, source = build_classifier_v2_vars(
    artifact, case, canonical_code, config
)
```

The variable name `canonical_code` makes the invariant self-documenting. No stage may reparse, reload, or reconstruct code independently.

### 18.6 Retry failure handling — fail attempt, not run

Replace v3's `raise ValueError(...)` in retry validation with:

```python
class RetryValidationError(Exception):
    """Retry attempt produced invalid output. Attempt fails, loop continues."""
    pass
```

In the retry loop, catch and continue:

```python
try:
    # ... parse, normalize, validate ...
    _validate_retry_artifact(artifact, parsed_gen, expected_keys)
except RetryValidationError as e:
    trajectory.append({
        "attempt": attempt_idx,
        "pass": False,
        "score": 0.0,
        "parse_valid": False,
        "error": str(e),
    })
    continue  # try next attempt
```

The attempt is recorded as failed with the validation error. The retry loop continues. The run is not killed.

### 18.7 Commitments required for v3 classifier

Before classifier call, when using v3:

```python
if config.evaluation.classifier_schema_variant == "v3_json":
    if (artifact.normalized_code_commitments is None
            or len(artifact.normalized_code_commitments) == 0):
        classifier_result = ClassifierResultV2(
            parse_error="skipped:no_commitments_for_v3",
            classifier_schema_variant="v3_json",
        )
        # skip classifier LLM call — commitments are required input
```

This does not crash. It skips classification and records why.

### 18.8 VALID_FAILURE_TYPES single canonical source

`VALID_FAILURE_TYPES` is defined in `core/evaluation/reasoning.py` (line 24-28). This is the single canonical source.

Enforcement chain:
1. `evaluator_v2.py:_get_valid_failure_types()` imports from `core.evaluation.reasoning`
2. `build_classifier_v2_vars()` passes `", ".join(sorted(VALID_FAILURE_TYPES))` as `failure_types` variable into the prompt
3. `parse_classifier_v3_output()` validates against the same `VALID_FAILURE_TYPES`

Hard invariant: the set passed into the prompt MUST be the same set used for parser validation. Both import from the same source. No separate definition allowed.

### 18.9 parse_error blocks metric computation

Already partially implemented in `derive_v2_signals()` (returns `classifier_failure_v2` when any dimension is None). Strengthen with explicit check in `execution_v2.py` and `retry_v2.py`:

```python
if classifier_result.parse_error is not None:
    # Do not derive signals — classification is invalid
    signals = V2Signals(
        v2_category="classifier_failure_v2",
        legacy_compat_category="classifier_parse_failed",
    )
else:
    signals = derive_v2_signals(...)
```

No partial metric computation from a parse-failed classifier. No fallback logic.

### 18.10 Prompt identity logging

Add to `assemble_v2_result()`:

```python
ev["generation_prompt_name"] = condition  # condition encodes generation prompt
ev["classifier_prompt_name"] = config.evaluation.classifier_template
```

For retry conditions, also log critique template name. Add to retry event assembly:

```python
ev["critique_prompt_name"] = critique_component_name  # e.g., "critique_mismatch_v3"
```

These are in addition to the existing prompt hashes logged by `call_logger`. Explicit names are for debugging ergonomics; hashes are for reproducibility.

### 18.11 JSON validation — json.loads only, no brace counting

**REMOVED:** All brace-counting logic from v3. Brace counting is NOT JSON-safe — it miscounts braces inside string values (e.g., `"failure_type": "dict_access {missing_key}"` is valid JSON but would be misinterpreted).

The v3 parser (§14.1) already uses the correct approach. The complete validation chain is:

1. `_strip_debug(raw).strip()` — remove debug section
2. Strict prefix: JSON must start at position 0 (`first_brace != 0` → error, per §18.3)
3. Strict trailing: no text after last `}` (per §18.3)
4. `json.loads(stripped)` — if this fails, it's not valid JSON
5. Closed-schema validation: exact 5-key check (per §14.1)
6. Value validation: dimensions ∈ {CORRECT, INCORRECT}, failure_type ∈ VALID_FAILURE_TYPES (per §14.1)

No custom JSON parsing. No brace counting. `json.loads` is the only JSON validator.

### 18.12 Generation schema validation before reconstruction (NEW)

Add an explicit **generation schema validation stage** in `execution_v2.py` and `retry_v2.py`, immediately after `parser_v2` parsing and before reasoning normalization or reconstruction.

```python
class GenerationSchemaError(Exception):
    """Generation output does not match required schema."""
    pass


def validate_generation_schema_v3(full_json: dict, expected_file_keys: set):
    """Validate v3 generation output schema. Raises GenerationSchemaError."""
    if full_json is None:
        raise GenerationSchemaError("full_json is None")

    required_keys = {"root_cause", "fix_strategy", "code_commitments", "files"}
    actual_keys = set(full_json.keys())
    missing = required_keys - actual_keys
    if missing:
        raise GenerationSchemaError(f"missing_keys: {missing}")

    # Type checks
    if not isinstance(full_json["root_cause"], str) or not full_json["root_cause"].strip():
        raise GenerationSchemaError("root_cause must be non-empty string")

    if not isinstance(full_json["fix_strategy"], str) or not full_json["fix_strategy"].strip():
        raise GenerationSchemaError("fix_strategy must be non-empty string")

    if not isinstance(full_json["code_commitments"], list):
        raise GenerationSchemaError("code_commitments must be list")

    if not isinstance(full_json["files"], dict):
        raise GenerationSchemaError("files must be dict")

    # File value types
    for path, content in full_json["files"].items():
        if not isinstance(content, str):
            raise GenerationSchemaError(
                f"file {path}: value must be string, got {type(content).__name__}"
            )

    # File key completeness
    actual_file_keys = set(full_json["files"].keys())
    if actual_file_keys != expected_file_keys:
        raise GenerationSchemaError(
            f"files key mismatch: expected={expected_file_keys}, got={actual_file_keys}"
        )
```

Called in `execution_v2.py` after parsing, before normalization:

```python
# STAGE 3b: Validate generation schema (v3 only)
if config.evaluation.generation_schema_variant == "v3":
    try:
        validate_generation_schema_v3(
            parsed_gen.full_json,
            expected_file_keys=set(code_files.keys()),
        )
    except GenerationSchemaError as e:
        # Mark as parse failure — skip reconstruction, classifier, metrics
        parsed_gen = ParsedGenerationV2(
            parse_status="failed",
            parse_error=f"generation_schema_error: {e}",
            # ... carry forward other fields
        )
```

Called identically in `retry_v2.py` for each retry attempt. On failure:
- Attempt is marked as failed with the schema error
- Reconstruction is skipped
- Classifier is skipped
- Retry loop continues to next attempt (per §18.6)
- Run is NOT killed

---

## 19. FINAL CONSISTENCY INVARIANT

For any successful attempt:

- A single `canonical_code_snapshot` MUST be produced after reconstruction
- The SAME snapshot MUST be used for:
  - execution (`exec_canonical`)
  - classification (`build_classifier_v2_vars` → `code` variable)
  - event logging (`_extracted_code`)
- No stage may reparse, reload, or reconstruct code independently
- `artifact_id` (if computed) MUST be derived from this snapshot

For any event:

- `generation_schema_variant` MUST come from `config.evaluation.generation_schema_variant`
- `classifier_schema_variant` MUST come from `config.evaluation.classifier_schema_variant`
- `generation_prompt_name` MUST be logged
- `classifier_prompt_name` MUST be logged
- `critique_prompt_name` MUST be logged (for retry conditions)
- No prompt identity may be inferred from condition name at analysis time — it must be in the event

For any classifier with `parse_error is not None`:

- `derive_v2_signals()` MUST NOT be called
- `v2_category` MUST be set to `"classifier_failure_v2"`
- No partial dimension values may propagate to metrics

For any retry attempt with schema validation failure:

- The attempt MUST be recorded as failed with the error
- The retry loop MUST continue to the next attempt
- The run MUST NOT crash
