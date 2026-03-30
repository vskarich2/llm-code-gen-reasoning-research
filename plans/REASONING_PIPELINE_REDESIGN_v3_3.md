# Reasoning Pipeline Redesign v3.3 — Final Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval
**Supersedes:** v1, v2, v3, v3.1, v3.2

---

## DIFF FROM V3.2

### CHANGED:
- Validation: `reasoning_present` split into `reasoning_attempted` (fields exist in JSON) and `reasoning_present` (fields have content)
- Classifier gating: runs if `reasoning_present == True`, skipped otherwise. No other gating conditions.
- `unclassified` split into 3 explicit categories: `no_reasoning`, `classifier_failed`, `parse_failed`
- Grounded mode: enforced — skips grounded evaluation for cases without `ground_truth_invariant`, logs `grounded_skipped`
- Classifier output parsing: aggressive normalization + strict field count validation
- `reasoning_fields_present` demoted to debug-only (not in events.jsonl)
- Added anti-template-collapse line to generation prompt

---

## FIX 1: `reasoning_attempted` vs `reasoning_present`

Two distinct signals:

```python
def validate_reasoning(reasoning_obj, raw_json):
    """Distinguish 'model tried' from 'model produced content'."""

    # Did the model include reasoning fields in its JSON at all?
    attempted = any(
        field in raw_json for field in REQUIRED_REASONING_FIELDS
    )

    # Do the fields contain actual content?
    present = any(
        reasoning_obj.get(f, "").strip() and len(reasoning_obj[f].strip()) >= MIN_FIELD_LENGTH
        for f in REQUIRED_REASONING_FIELDS
    )

    return {
        "reasoning_attempted": attempted,
        "reasoning_present": present,
    }
```

**Semantics:**
- `attempted=True, present=True` → model produced reasoning. Classifier runs.
- `attempted=True, present=False` → model included empty fields. Classifier skipped. Category: `no_reasoning`.
- `attempted=False, present=False` → model didn't even try (e.g., returned only code). Classifier skipped. Category: `no_reasoning`.

Both fields logged in events.jsonl. Analysis can distinguish "didn't try" from "tried but empty."

---

## FIX 2: Classifier Gating — One Rule, No Exceptions

```python
if reasoning_validation["reasoning_present"]:
    # Run classifier. Always. No min_length gate. No fields_present gate.
    classify_result = run_classifier(reasoning_obj, case, code, config)
else:
    # Skip. Explicit null result.
    classify_result = NULL_CLASSIFIER_RESULT
```

That's the ONLY branching point. If `reasoning_present == True`, the classifier runs regardless of how many fields are present or how long they are. The classifier judges quality — gating logic does not.

---

## FIX 3: Split `unclassified` Into Explicit Categories

The old single `unclassified` bucket is replaced by 3 distinct failure categories:

```python
def compute_category(code_correct, reasoning_correct, reasoning_present, classifier_failed, parse_failed):
    if parse_failed:
        return "parse_failed"
    if not reasoning_present:
        return "no_reasoning"
    if reasoning_correct is None and classifier_failed:
        return "classifier_failed"
    if reasoning_correct is None:
        return "classifier_failed"  # catch-all for None reasoning_correct when reasoning was present
    if reasoning_correct and code_correct:
        return "true_success"
    if reasoning_correct and not code_correct:
        return "leg"
    if not reasoning_correct and code_correct:
        return "lucky_fix"
    return "true_failure"
```

**Categories:**

| Category | Meaning | Counts toward reasoning metrics? |
|---|---|---|
| `true_success` | Correct reasoning + correct code | YES |
| `leg` | Correct reasoning + wrong code | YES |
| `lucky_fix` | Wrong reasoning + correct code | YES |
| `true_failure` | Wrong reasoning + wrong code | YES |
| `no_reasoning` | Model didn't produce reasoning content | NO (coverage metric only) |
| `classifier_failed` | Classifier ran but output couldn't be parsed | NO (logged as classifier error) |
| `parse_failed` | Model output couldn't be parsed at all | NO (logged as parse error) |

**Reporting rule:** Every report shows:
- Total cases
- Cases by category (all 7)
- Reasoning coverage = `(total - no_reasoning - parse_failed) / total`
- Reasoning quality = `true_success + leg` / `(true_success + leg + lucky_fix + true_failure)`

---

## FIX 4: Grounded Mode — Enforce Invariant Presence

```python
def should_run_grounded(case, classifier_mode):
    """Determine if grounded mode can run for this case."""
    if classifier_mode != "grounded":
        return False
    gt_invariant = case.get("ground_truth_invariant", "")
    gt_failure_mode = case.get("failure_mode", "")
    if not gt_invariant.strip() or not gt_failure_mode.strip():
        return False
    return True
```

**Behavior:**
- If `classifier_mode == "grounded"` but case lacks ground truth → run in blind mode for that case, log `grounded_skipped: true`
- Disagreement rate computed ONLY over cases where both modes ran
- No empty-string ground truth ever reaches the classifier

**Logged:**
```json
{
  "classifier_mode": "grounded",
  "grounded_skipped": false,
  "grounded_reason": null
}
```
or:
```json
{
  "classifier_mode": "grounded",
  "grounded_skipped": true,
  "grounded_reason": "missing_ground_truth_invariant"
}
```

---

## FIX 5: Hardened Classifier Output Parsing

```python
VALID_DIMENSIONS = {"YES", "PARTIAL", "NO"}

def parse_classify_output(raw):
    """Parse classifier output with aggressive normalization."""
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]

    if not lines:
        return {"parse_error": "empty_classifier_output"}

    # Line 1: dimensions — normalize whitespace and case
    dims_line = lines[0]
    parts = [p.strip().upper() for p in dims_line.split(";")]

    if len(parts) < 5:
        return {"parse_error": f"expected_5_fields_got_{len(parts)}"}

    # Validate each dimension
    dims = {}
    for i, (name, val) in enumerate([
        ("mechanism_identified", parts[0]),
        ("invariant_identified", parts[1]),
        ("fix_alignment", parts[2]),
        ("reasoning_code_alignment", parts[3]),
    ]):
        if val in VALID_DIMENSIONS:
            dims[name] = val
        else:
            return {"parse_error": f"invalid_dimension_{name}_{val}"}

    dims["failure_type"] = parts[4]

    # Line 2: explanation (required)
    explanation = lines[1] if len(lines) > 1 else ""

    return {
        **dims,
        "explanation": explanation,
        "parse_error": None,
    }
```

**Handles:**
- `YES ; YES ; YES ; YES ; TYPE` (spaces around semicolons) → normalized
- `yes;yes;yes;yes;TYPE` (lowercase) → uppercased
- `YES;YES;YES` (too few fields) → `parse_error`
- `MAYBE;YES;YES;YES;TYPE` (invalid value) → `parse_error`

When `parse_error` is set: `reasoning_correct = None`, category = `classifier_failed`.

---

## REMAINING DESIGN (unchanged from v3.2)

Everything else from v3.2 carries forward unchanged:

- **Generation prompt:** 4 reasoning fields + grounding rules + "Avoid repeating generic phrases. Your explanation must be specific to this code."
- **LEG schema:** 4 reasoning fields + `self_check` + `revision_note` + `attempt_number` + `previous_attempt_summary`
- **Classifier prompt:** 4-dimension evaluation with decision criteria + few-shot examples + mandatory explanation. Grounded mode adds ground truth.
- **`compute_reasoning_correct()`:** strict/lenient/raw modes, configurable.
- **Logging:** `reasoning_obj` in run.jsonl, dimensions + explanation in audit block, schema version = 2 (hardcoded, mismatch = crash).
- **Metrics:** coverage + quality always separate. Blind + grounded + disagreement when available.
- **Consistency check:** Trivial only (fix claimed but tests fail).

---

## EVENTS.JSONL SCHEMA (final)

```json
{
  "reasoning_schema_version": 2,
  "reasoning_attempted": true,
  "reasoning_present": true,
  "reasoning_correct": true,
  "classifier_mechanism": "YES",
  "classifier_invariant": "YES",
  "classifier_fix_align": "YES",
  "classifier_code_align": "YES",
  "classifier_mode": "blind",
  "classifier_explanation": "...",
  "grounded_skipped": false,
  "failure_type": "HIDDEN_DEPENDENCY",
  "category": "true_success",
  "reasoning_execution_consistent": true
}
```

---

## IMPLEMENTATION PHASES (unchanged)

R0 → R1 → R2 → R3 → R4 → R5 → R6

---

## FAILURE MODE COVERAGE (final)

| Mode | Detectable | Category |
|------|-----------|----------|
| Correct reasoning + correct code | YES | `true_success` |
| Correct reasoning + wrong code | YES | `leg` |
| Wrong reasoning + correct code | YES | `lucky_fix` |
| Wrong reasoning + wrong code | YES | `true_failure` |
| Model didn't produce reasoning | YES | `no_reasoning` |
| Classifier output unparseable | YES | `classifier_failed` |
| Model output unparseable | YES | `parse_failed` |
| Generic/template reasoning | YES | classifier returns NO/PARTIAL |
| Right invariant, wrong mechanism | YES | mechanism NO, invariant YES |
| Right mechanism, wrong invariant | YES | mechanism YES, invariant NO |
| Right reasoning, wrong location | YES | mechanism NO (grounded mode) |
| Classifier error (wrong judgment) | MEASURABLE | blind vs grounded disagreement |
| Subtle errors fooling both modes | NOT DETECTABLE | requires human evaluation |

---

*End of v3.3 plan. Zero backward compatibility. One schema. One pipeline. Explicit failure categories.*
