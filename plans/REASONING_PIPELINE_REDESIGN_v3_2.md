# Reasoning Pipeline Redesign v3.2 — Final Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval
**Supersedes:** v1, v2, v3, v3.1

---

## DIFF FROM V3.1

### REMOVED:
- All backward compatibility: `reasoning_obj = None` branch, `"reasoning"` flat field fallback, old-schema detection, conditional parsing
- `reasoning_text` flattened field (was kept for "backward compat")
- Schema version branching logic
- `reasoning_schema_version` config field (hardcoded to 2, no branching)
- Dual-format logging (`"reasoning"` vs `"reasoning_obj"`)

### CHANGED:
- Parser: ONLY extracts structured `reasoning_obj`. Missing fields → hard failure or explicit `reasoning_present=False`. No fallback.
- Logging: ONLY `reasoning_obj` in run.jsonl. No `"reasoning"` flat field.
- Classifier: ALWAYS receives structured fields. Never receives flat string.
- Schema version: hardcoded. Mismatch → `RuntimeError`. No migration.

---

## ARCHITECTURE

5 layers. One schema. One pipeline. Zero ambiguity.

| Layer | Input | Output | Failure Behavior |
|-------|-------|--------|-----------------|
| **Prompt** | case + condition | Generation prompt with 4 reasoning fields + files | N/A |
| **Parser** | raw JSON response | `reasoning_obj` dict (4 fields) or `reasoning_present=False` | Missing required JSON fields → `reasoning_present=False` |
| **Validation** | `reasoning_obj` | `reasoning_present`, `reasoning_fields_present`, `reasoning_min_length_ok` | No semantic checks. Presence only. |
| **Classifier** | 4 reasoning fields + task + code | 4 dimensions + failure_type + explanation | Skipped if `reasoning_present=False` |
| **Metrics** | classifier output + execution result | coverage, quality, regime category | Coverage and quality always reported separately |

---

## A. GENERATION PROMPT

### Response schema (baseline):

```json
{
  "root_cause": "<function/variable + causal relationship>",
  "failure_mechanism": "<concrete scenario with cause and effect>",
  "broken_invariant": "<specific testable behavioral property>",
  "fix_strategy": "<actual code change + why it addresses the mechanism>",
  "files": { ... }
}
```

### Response schema (LEG):

```json
{
  "root_cause": "...",
  "failure_mechanism": "...",
  "broken_invariant": "...",
  "fix_strategy": "...",
  "self_check": "<verify fix against invariant — reference specific code>",
  "revision_note": "<what changed from prior attempt — null if first>",
  "attempt_number": 0,
  "previous_attempt_summary": null,
  "files": { ... }
}
```

### V1 output instruction (single code field):

Same 4 reasoning fields + `"code"` instead of `"files"`.

### Grounding instructions (in all generation prompts):

```
GROUNDING RULES:
- "root_cause" must name the specific function and variable and explain the causal relationship.
- "failure_mechanism" must describe a concrete scenario showing cause and effect.
- "broken_invariant" must be a specific, testable statement about expected behavior.
- "fix_strategy" must reference your actual code change and explain why it addresses the mechanism.
- Do not write generic statements. Ground every claim in the actual code.
```

---

## B. PARSER

### One path. No fallback.

```python
REQUIRED_REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")

def extract_reasoning_obj(parsed_json):
    """Extract structured reasoning. No fallback. No legacy support."""
    obj = {}
    for field in REQUIRED_REASONING_FIELDS:
        obj[field] = parsed_json.get(field, "")
    # LEG-only fields (present if LEG schema)
    obj["self_check"] = parsed_json.get("self_check", "")
    obj["revision_note"] = parsed_json.get("revision_note")
    obj["attempt_number"] = parsed_json.get("attempt_number", 0)
    obj["previous_attempt_summary"] = parsed_json.get("previous_attempt_summary")
    return obj
```

Called for EVERY parsed response. No `if "root_cause" in parsed` branching. The function always returns a dict. Empty strings for missing fields.

### Integration into parse pipeline:

In `_try_json_direct()`, `_try_file_dict()`, and all other parse tiers:

```python
result["reasoning_obj"] = extract_reasoning_obj(parsed)
result["code"] = ...  # unchanged
result["files"] = ...  # unchanged
```

`parsed["reasoning"]` flat field is REMOVED from the parser output. It does not exist. Anything downstream that accessed `parsed["reasoning"]` must be updated to use `parsed["reasoning_obj"]`.

---

## C. VALIDATION

```python
MIN_FIELD_LENGTH = 10

def validate_reasoning_presence(reasoning_obj):
    """Check presence and minimum length. No semantic judgment."""
    fields_present = sum(
        1 for f in REQUIRED_REASONING_FIELDS
        if reasoning_obj.get(f, "").strip() and len(reasoning_obj[f].strip()) >= MIN_FIELD_LENGTH
    )
    return {
        "reasoning_present": fields_present > 0,
        "reasoning_fields_present": fields_present,
        "reasoning_min_length_ok": fields_present == len(REQUIRED_REASONING_FIELDS),
    }
```

---

## D. CLASSIFIER

### Input: always structured.

```python
def build_classifier_variables(reasoning_obj, case, code, classifier_mode, config):
    """Build variables for classify_reasoning template. Always structured."""
    vars = {
        "root_cause": reasoning_obj["root_cause"],
        "failure_mechanism": reasoning_obj["failure_mechanism"],
        "broken_invariant": reasoning_obj["broken_invariant"],
        "fix_strategy": reasoning_obj["fix_strategy"],
        "self_check": reasoning_obj.get("self_check", ""),
        "task": case.get("task", ""),
        "code": code,
        "failure_types": ", ".join(sorted(FAILURE_TYPE_SET)),
        "classifier_mode": classifier_mode,
    }
    if classifier_mode == "grounded":
        vars["ground_truth_failure_mode"] = case.get("failure_mode", "")
        vars["ground_truth_trap"] = case.get("trap", "")
        vars["ground_truth_invariant"] = case.get("ground_truth_invariant", "")
    return vars
```

If `reasoning_present == False`: classifier is NOT called. Result:
```python
{
    "reasoning_correct": None,
    "mechanism_identified": None,
    "invariant_identified": None,
    "fix_alignment": None,
    "reasoning_code_alignment": None,
    "failure_type": None,
    "explanation": None,
}
```

### Output parsing:

```python
def parse_classify_output(raw):
    """Parse 4-dimension + explanation response."""
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    dims_line = lines[0] if lines else ""
    explanation = lines[1] if len(lines) > 1 else ""

    parts = [p.strip().upper() for p in dims_line.split(";")]
    if len(parts) < 5:
        return {"parse_error": f"Expected 5 semicolon-separated fields, got {len(parts)}"}

    VALID = {"YES", "PARTIAL", "NO"}
    return {
        "mechanism_identified": parts[0] if parts[0] in VALID else None,
        "invariant_identified": parts[1] if parts[1] in VALID else None,
        "fix_alignment": parts[2] if parts[2] in VALID else None,
        "reasoning_code_alignment": parts[3] if parts[3] in VALID else None,
        "failure_type": parts[4],
        "explanation": explanation,
        "parse_error": None,
    }
```

### Derivation:

```python
def compute_reasoning_correct(dims, mode="strict"):
    m = dims["mechanism_identified"]
    i = dims["invariant_identified"]
    f = dims["fix_alignment"]

    if any(d is None for d in (m, i, f)):
        return None

    if mode == "strict":
        return m == "YES" and i in ("YES", "PARTIAL") and f in ("YES", "PARTIAL")
    elif mode == "lenient":
        return m in ("YES", "PARTIAL") and i in ("YES", "PARTIAL")
    elif mode == "raw":
        return None
```

---

## E. LOGGING

### events.jsonl:

```json
{
  "reasoning_present": true,
  "reasoning_fields_present": 4,
  "reasoning_correct": true,
  "classifier_mechanism": "YES",
  "classifier_invariant": "YES",
  "classifier_fix_align": "YES",
  "classifier_code_align": "YES",
  "classifier_mode": "blind",
  "failure_type": "HIDDEN_DEPENDENCY",
  "reasoning_execution_consistent": true
}
```

### run.jsonl audit block:

```json
{
  "audit": {
    "reasoning_obj": {
      "root_cause": "...",
      "failure_mechanism": "...",
      "broken_invariant": "...",
      "fix_strategy": "..."
    },
    "reasoning_validation": {
      "reasoning_present": true,
      "reasoning_fields_present": 4,
      "reasoning_min_length_ok": true
    },
    "classifier_dimensions": {
      "mechanism_identified": "YES",
      "invariant_identified": "YES",
      "fix_alignment": "YES",
      "reasoning_code_alignment": "YES"
    },
    "classifier_explanation": "...",
    "classifier_mode": "blind",
    "classifier_verdict": true,
    "classifier_failure_type": "HIDDEN_DEPENDENCY"
  }
}
```

No `"reasoning"` flat field anywhere. No `"parsed_reasoning"` flat field. Only `"reasoning_obj"`.

### Schema version:

Hardcoded `2` in every event. No branching:

```python
event["reasoning_schema_version"] = 2
```

Mismatch with existing events → `RuntimeError` at run start.

---

## F. METRICS

### Reasoning Coverage:

```
reasoning_coverage = count(reasoning_present == True) / total_cases
```

### Reasoning Quality (conditional on presence):

```
reasoning_quality = count(reasoning_correct == True) / count(reasoning_present == True)
```

### Regime categories:

| reasoning_correct | code_correct | Category |
|---|---|---|
| True | True | `true_success` |
| True | False | `leg` |
| False | True | `lucky_fix` |
| False | False | `true_failure` |
| None | any | `unclassified` |

### Reporting rule:

Every aggregate report includes:
- Total cases
- Cases with reasoning present (coverage)
- Reasoning quality (conditional)
- Pass rate over all cases
- Pass rate over cases with reasoning
- LEG rate over cases with reasoning

No silent exclusion. Both numbers always visible.

### Classifier calibration (when grounded mode available):

```
classifier_disagreement_rate = count(blind != grounded) / count(both modes ran)
```

---

## G. CONSISTENCY CHECK (trivial only)

```python
def check_reasoning_execution_consistent(reasoning_obj, ev):
    if reasoning_obj.get("fix_strategy", "").strip() and not ev.get("pass"):
        return False
    return True
```

One check. All real consistency evaluation is the classifier's `reasoning_code_alignment` dimension.

---

## H. IMPLEMENTATION PHASES

- **R0:** Add `ground_truth_invariant` field to case metadata (SCM cases). Add `classifier_mode` to config.
- **R1:** New templates: `output_instruction_v1.j2`, `output_instruction_v2.j2`, `leg_reduction.j2`, `classify_reasoning.j2`
- **R2:** Parser: `extract_reasoning_obj()`, remove `parsed["reasoning"]` flat field, update all downstream consumers
- **R3:** Classifier: new prompt with 4-dimension output, `parse_classify_output()`, `compute_reasoning_correct()`, blind/grounded modes
- **R4:** Logging: `reasoning_obj` in run.jsonl, dimensions in events.jsonl, schema version enforcement
- **R5:** Metrics: coverage + quality separation, disagreement rate
- **R6:** Tests: regime classification, adversarial suite (10 cases), presence validation

---

## I. ADVERSARIAL TEST SUITE

1. Correct reasoning + correct code → `true_success`
2. Correct reasoning + wrong code → `leg`
3. Wrong reasoning + correct code → `lucky_fix`
4. Wrong reasoning + wrong code → `true_failure`
5. Generic template reasoning → classifier detects (mechanism NO/PARTIAL)
6. Correct invariant + wrong mechanism → mechanism NO, invariant YES
7. Correct mechanism + wrong invariant → mechanism YES, invariant NO
8. Correct reasoning + wrong location → mechanism NO (wrong function)
9. Task restatement as reasoning → classifier returns NO
10. Missing reasoning → `reasoning_present=False`, classifier skipped, `unclassified`

---

## J. FAILURE MODE COVERAGE

| Mode | Detectable | How |
|------|-----------|-----|
| Correct reasoning + correct code | YES | classifier all YES + pass |
| Correct reasoning + wrong code (LEG) | YES | classifier YES + fail |
| Wrong reasoning + correct code (lucky) | YES | classifier NO + pass |
| Wrong reasoning + wrong code | YES | classifier NO + fail |
| Generic reasoning | YES | classifier PARTIAL/NO on mechanism |
| Right invariant, wrong mechanism | YES | mechanism NO, invariant YES |
| Right mechanism, wrong invariant | YES | mechanism YES, invariant NO |
| Right reasoning, wrong location | YES | mechanism NO in grounded mode |
| Missing reasoning | YES | validation: not present, category unclassified |
| Classifier error | MEASURABLE | blind vs grounded disagreement rate |
| Subtle errors fooling both modes | NOT DETECTABLE | requires human evaluation |

---

*End of v3.2 plan. Zero backward compatibility. One schema. One pipeline.*
