# Reasoning Pipeline Redesign — Final Implementation Plan v2

**Date:** 2026-03-28
**Status:** IMPLEMENTATION-READY
**Supersedes:** all prior versions

---

## DIFF FROM FINAL v1

| # | Fix | Change |
|---|-----|--------|
| 1 | `present` requires ALL fields | `any()` → `all()` |
| 2 | `failure_type` validated | Unknown → `"UNKNOWN"`, raw value logged separately |
| 3 | `reasoning_lengths` structured | `{field: {length: N, present: bool}}` |
| 4 | Classifier parse enforces EXACTLY 3 lines | `< 3` → `!= 3` |
| 5 | Metric denominators explicitly defined | Documented per metric |
| 6 | `classifier_failed` split | `classifier_parse_failed` + `classifier_no_verdict` |
| 7 | `reasoning_execution_consistent` removed | Redundant with `reasoning_code_alignment` |
| 8 | Whitespace normalization | `.strip()` + collapse applied everywhere |

---

## VALIDATION LOGIC (final)

```python
REQUIRED_REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")
MIN_FIELD_LENGTH = 10

def validate_reasoning(reasoning_obj, raw_json):
    attempted = all(field in raw_json for field in REQUIRED_REASONING_FIELDS)

    lengths = {}
    for f in REQUIRED_REASONING_FIELDS:
        val = reasoning_obj.get(f, "").strip()
        lengths[f] = {"length": len(val), "present": bool(val and len(val) >= MIN_FIELD_LENGTH)}

    present = all(lengths[f]["present"] for f in REQUIRED_REASONING_FIELDS)

    return {
        "reasoning_attempted": attempted,
        "reasoning_present": present,
        "reasoning_lengths": lengths,
    }
```

---

## CLASSIFIER OUTPUT PARSING (final)

```python
VALID_DIMENSIONS = {"YES", "PARTIAL", "NO"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
VALID_FAILURE_TYPES = {
    "HIDDEN_DEPENDENCY", "TEMPORAL_ORDERING", "INVARIANT_VIOLATION",
    "PARTIAL_STATE_UPDATE", "RETRY_LOGIC_BUG", "EDGE_CASE_MISSED",
    "LOGGING_INCONSISTENCY", "CONFOUNDING_LOGIC", "UNKNOWN",
}

def parse_classify_output(raw):
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]

    if len(lines) != 3:
        return {"parse_error": f"expected_3_lines_got_{len(lines)}"}

    # Line 1: dimensions
    parts = [p.strip().upper() for p in lines[0].split(";")]
    if len(parts) != 5:
        return {"parse_error": f"expected_5_fields_got_{len(parts)}"}

    dims = {}
    for name, val in [
        ("mechanism_identified", parts[0]),
        ("invariant_identified", parts[1]),
        ("fix_alignment", parts[2]),
        ("reasoning_code_alignment", parts[3]),
    ]:
        if val not in VALID_DIMENSIONS:
            return {"parse_error": f"invalid_dimension_{name}_{val}"}
        dims[name] = val

    failure_type_raw = parts[4]
    dims["failure_type"] = failure_type_raw if failure_type_raw in VALID_FAILURE_TYPES else "UNKNOWN"
    dims["failure_type_raw"] = failure_type_raw

    # Line 2: confidence
    confidence = lines[1].strip().upper()
    if confidence not in VALID_CONFIDENCE:
        return {"parse_error": f"invalid_confidence_{confidence}"}
    dims["confidence"] = confidence

    # Line 3: explanation
    explanation = lines[2].strip()
    if not explanation:
        return {"parse_error": "missing_explanation"}
    dims["explanation"] = explanation

    dims["parse_error"] = None
    return dims
```

---

## CATEGORY COMPUTATION (final)

8 explicit categories:

```python
def compute_category(code_correct, reasoning_correct, reasoning_present,
                     classifier_parse_error, parse_failed):
    if parse_failed:
        return "parse_failed"
    if not reasoning_present:
        return "no_reasoning"
    if classifier_parse_error:
        return "classifier_parse_failed"
    if reasoning_correct is None:
        return "classifier_no_verdict"
    if reasoning_correct and code_correct:
        return "true_success"
    if reasoning_correct and not code_correct:
        return "leg"
    if not reasoning_correct and code_correct:
        return "lucky_fix"
    return "true_failure"
```

| Category | Meaning | In coverage? | In quality? |
|---|---|---|---|
| `true_success` | Correct reasoning + correct code | YES | YES |
| `leg` | Correct reasoning + wrong code | YES | YES |
| `lucky_fix` | Wrong reasoning + correct code | YES | YES |
| `true_failure` | Wrong reasoning + wrong code | YES | YES |
| `no_reasoning` | Model didn't produce reasoning | NO | NO |
| `classifier_parse_failed` | Classifier output couldn't be parsed | NO | NO |
| `classifier_no_verdict` | Classifier ran but produced no verdict (raw mode) | NO | NO |
| `parse_failed` | Model output couldn't be parsed at all | NO | NO |

---

## METRIC DEFINITIONS (final, with explicit denominators)

```
total_cases = N (all cases in the run)

coverage = count(category in COVERED_SET) / total_cases
  where COVERED_SET = {true_success, leg, lucky_fix, true_failure}
  denominator: total_cases

quality = count(reasoning_correct == True) / count(category in COVERED_SET)
  denominator: covered cases only

disagreement = count(blind != grounded) / count(grounded_executed == True)
  denominator: cases where grounded actually ran

confidence_distribution = {HIGH: N, MEDIUM: M, LOW: L}
  over: covered cases only

disagreement_by_confidence = {HIGH: rate, MEDIUM: rate, LOW: rate}
  over: grounded_executed cases, bucketed by confidence
```

---

## EVENTS.JSONL SCHEMA (final)

```json
{
  "reasoning_schema_version": 2,
  "reasoning_attempted": true,
  "reasoning_present": true,
  "reasoning_lengths": {
    "root_cause": {"length": 87, "present": true},
    "failure_mechanism": {"length": 142, "present": true},
    "broken_invariant": {"length": 61, "present": true},
    "fix_strategy": {"length": 95, "present": true}
  },
  "reasoning_correct": true,
  "classifier_mechanism": "YES",
  "classifier_invariant": "YES",
  "classifier_fix_align": "YES",
  "classifier_code_align": "YES",
  "classifier_confidence": "HIGH",
  "classifier_mode": "blind",
  "classifier_explanation": "...",
  "classifier_parse_error": null,
  "classifier_failure_type": "HIDDEN_DEPENDENCY",
  "classifier_failure_type_raw": "HIDDEN_DEPENDENCY",
  "grounded_attempted": false,
  "grounded_executed": false,
  "grounded_reason": null,
  "category": "true_success"
}
```

---

## EVERYTHING ELSE

All other sections from FINAL v1 carry forward unchanged:

- Generation prompt schemas (baseline + LEG)
- Grounding instructions
- Classifier prompt (4-dimension + confidence + explanation, few-shot examples, grounded mode)
- `compute_reasoning_correct()` (strict/lenient/raw)
- Classifier gating (one branch: `reasoning_present == True`)
- Grounded mode enforcement (`should_run_grounded()`)
- Schema version enforcement at runtime
- Consistency check: REMOVED (was `reasoning_execution_consistent`)
- File-by-file change list
- Implementation order (R1–R7)
- Test suite (all suites from FINAL v1, plus fixes below)
- Out of scope items

---

## ADDITIONAL TESTS (from fixes)

```
test_present_requires_all_fields → 1 field populated, 3 empty → present=False
test_present_all_populated → all 4 populated → present=True
test_unknown_failure_type_normalized → "TYPO_TYPE" → failure_type="UNKNOWN", failure_type_raw="TYPO_TYPE"
test_reasoning_lengths_structured → each field has {length, present}
test_classifier_extra_lines_rejected → 4 lines → parse_error="expected_3_lines_got_4"
test_classifier_exactly_3_lines → 3 lines → parsed correctly
test_classifier_parse_failed_category → parse error → "classifier_parse_failed"
test_classifier_no_verdict_category → raw mode → "classifier_no_verdict"
test_all_partial_warning → all dims PARTIAL → warning logged
test_coverage_excludes_all_failure_categories → no_reasoning + classifier_parse_failed + classifier_no_verdict + parse_failed all excluded
```

---

*End of final plan v2. Zero backward compatibility. One schema. One pipeline. 8 explicit categories. Strict parsing. Honest metrics.*
