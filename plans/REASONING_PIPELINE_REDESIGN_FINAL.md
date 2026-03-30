# Reasoning Pipeline Redesign — Final Implementation Plan

**Date:** 2026-03-28
**Status:** IMPLEMENTATION-READY
**Supersedes:** all prior versions (v1–v3.3)

---

## FILE-BY-FILE CHANGE LIST

| File | Changes | Why |
|------|---------|-----|
| `prompts/components/output_instruction_v1.j2` | Rewrite: 4 reasoning fields + grounding rules + anti-template line | Baseline must elicit structured reasoning |
| `prompts/components/output_instruction_v2.j2` | Rewrite: 4 reasoning fields + grounding rules + anti-template line | Same, file-dict format |
| `prompts/components/leg_reduction.j2` | Rewrite: compact schema with 4 reasoning fields + self_check + revision_note | Remove schema theater, keep self-correction |
| `prompts/components/classify_reasoning.j2` | Rewrite: 4-dimension + confidence + explanation, few-shot examples, grounded mode support | Classifier must evaluate structured reasoning multi-dimensionally |
| `parse.py` | Add `extract_reasoning_obj()`, add `validate_reasoning()`, remove flat `"reasoning"` field | Parser extracts structured reasoning, validates presence |
| `evaluator.py` | Rewrite `llm_classify()`: pass structured fields, parse 3-line output, `compute_reasoning_correct()`, blind/grounded modes | Classifier pipeline end-to-end |
| `execution.py` | Update `_build_parsed_response()`, `_propagate_observability()`, `_compute_failure_source()`, `evaluate_case()`, `RunLogger._write_locked()`, `_emit_metrics_event()` | Reasoning obj flows through entire pipeline |
| `experiment_config.py` | Add `classifier_mode`, `reasoning_correct_mode` to EvaluationConfig | Config-driven classifier behavior |
| `runner.py` | Add schema version enforcement at run start | Prevent mixed schemas |
| `prompts/prompt_manifest.yaml` | No change (component names unchanged) | — |
| `prompts/registry.yaml` | No change | — |
| `assembly_engine.py` | No change | — |
| `prompt_registry.py` | No change | — |
| `call_logger.py` | No change (provenance already captures variables) | — |

---

## SCHEMAS

### Generation Response Schema (baseline V2)

```json
{
  "root_cause": "<function/variable + causal relationship>",
  "failure_mechanism": "<concrete scenario with cause and effect>",
  "broken_invariant": "<specific testable behavioral property>",
  "fix_strategy": "<actual code change + why it addresses the mechanism>",
  "files": { ... }
}
```

### Generation Response Schema (LEG)

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

### Classifier Output Schema (3 lines)

```
Line 1: <mechanism>;<invariant>;<fix_align>;<code_align>;<failure_type>
Line 2: <HIGH|MEDIUM|LOW>
Line 3: <explanation referencing reasoning and code behavior>
```

### events.jsonl Schema

```json
{
  "reasoning_schema_version": 2,
  "reasoning_attempted": true,
  "reasoning_present": true,
  "reasoning_lengths": {"root_cause": 87, "failure_mechanism": 142, "broken_invariant": 61, "fix_strategy": 95},
  "reasoning_correct": true,
  "classifier_mechanism": "YES",
  "classifier_invariant": "YES",
  "classifier_fix_align": "YES",
  "classifier_code_align": "YES",
  "classifier_confidence": "HIGH",
  "classifier_mode": "blind",
  "classifier_explanation": "...",
  "classifier_parse_error": null,
  "grounded_attempted": false,
  "grounded_executed": false,
  "grounded_reason": null,
  "failure_type": "HIDDEN_DEPENDENCY",
  "category": "true_success",
  "reasoning_execution_consistent": true
}
```

### run.jsonl Audit Block

```json
{
  "audit": {
    "reasoning_obj": {"root_cause": "...", "failure_mechanism": "...", "broken_invariant": "...", "fix_strategy": "..."},
    "reasoning_validation": {"reasoning_attempted": true, "reasoning_present": true},
    "reasoning_lengths": {"root_cause": 87, "failure_mechanism": 142, "broken_invariant": 61, "fix_strategy": 95},
    "classifier_dimensions": {"mechanism_identified": "YES", "invariant_identified": "YES", "fix_alignment": "YES", "reasoning_code_alignment": "YES"},
    "classifier_confidence": "HIGH",
    "classifier_explanation": "...",
    "classifier_parse_error": null,
    "classifier_mode": "blind",
    "grounded_attempted": false,
    "grounded_executed": false,
    "grounded_reason": null,
    "classifier_verdict": true,
    "classifier_failure_type": "HIDDEN_DEPENDENCY"
  }
}
```

---

## VALIDATION LOGIC

```python
REQUIRED_REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")
MIN_FIELD_LENGTH = 10

def validate_reasoning(reasoning_obj, raw_json):
    attempted = all(field in raw_json for field in REQUIRED_REASONING_FIELDS)
    present = any(
        reasoning_obj.get(f, "").strip() and len(reasoning_obj[f].strip()) >= MIN_FIELD_LENGTH
        for f in REQUIRED_REASONING_FIELDS
    )
    lengths = {f: len(reasoning_obj.get(f, "").strip()) for f in REQUIRED_REASONING_FIELDS}
    return {
        "reasoning_attempted": attempted,
        "reasoning_present": present,
        "reasoning_lengths": lengths,
    }
```

---

## CLASSIFIER GATING

```python
if reasoning_validation["reasoning_present"]:
    classify_result = run_classifier(reasoning_obj, case, code, config)
else:
    classify_result = {
        "mechanism_identified": None, "invariant_identified": None,
        "fix_alignment": None, "reasoning_code_alignment": None,
        "failure_type": None, "confidence": None, "explanation": None,
        "parse_error": None,
    }
```

One branch. No other conditions.

---

## CLASSIFIER OUTPUT PARSING

```python
VALID_DIMENSIONS = {"YES", "PARTIAL", "NO"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}

def parse_classify_output(raw):
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]

    if len(lines) < 3:
        return {"parse_error": f"expected_3_lines_got_{len(lines)}"}

    # Line 1: dimensions
    parts = [p.strip().upper() for p in lines[0].split(";")]
    if len(parts) < 5:
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
    dims["failure_type"] = parts[4]

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

Parse error → `classifier_failed` category. `reasoning_correct = None`. Exact error string logged in `classifier_parse_error`.

---

## CATEGORY COMPUTATION

```python
def compute_category(code_correct, reasoning_correct, reasoning_present, classifier_parse_error, parse_failed):
    if parse_failed:
        return "parse_failed"
    if not reasoning_present:
        return "no_reasoning"
    if classifier_parse_error:
        return "classifier_failed"
    if reasoning_correct is None:
        return "classifier_failed"
    if reasoning_correct and code_correct:
        return "true_success"
    if reasoning_correct and not code_correct:
        return "leg"
    if not reasoning_correct and code_correct:
        return "lucky_fix"
    return "true_failure"
```

---

## `reasoning_correct` DERIVATION

```python
def compute_reasoning_correct(dims, mode="strict"):
    m = dims.get("mechanism_identified")
    i = dims.get("invariant_identified")
    f = dims.get("fix_alignment")
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

## METRIC DEFINITIONS

**Coverage:**
```
coverage = count(category in {"true_success", "leg", "lucky_fix", "true_failure"}) / total
```
Excludes: `no_reasoning`, `classifier_failed`, `parse_failed`.

**Reasoning Quality (conditional):**
```
quality = count(reasoning_correct == True) / count(category in {"true_success", "leg", "lucky_fix", "true_failure"})
```

**Classifier Disagreement (grounded mode):**
```
disagreement = count(blind_verdict != grounded_verdict) / count(grounded_executed == True)
```
Computed ONLY over cases where `grounded_executed == True`.

**Confidence Distribution:**
```
{HIGH: N, MEDIUM: M, LOW: L} overall and per failure_mode
```

**Disagreement by Confidence:**
```
disagreement_rate_at_HIGH, disagreement_rate_at_MEDIUM, disagreement_rate_at_LOW
```

---

## GROUNDED MODE

```python
def should_run_grounded(case, classifier_mode):
    if classifier_mode != "grounded":
        return False, "not_requested"
    gt_inv = case.get("ground_truth_invariant", "").strip()
    gt_mode = case.get("failure_mode", "").strip()
    if not gt_inv or not gt_mode:
        return False, "missing_ground_truth"
    return True, None
```

Logged as:
```json
{
  "grounded_attempted": true,
  "grounded_executed": true,
  "grounded_reason": null
}
```
or:
```json
{
  "grounded_attempted": true,
  "grounded_executed": false,
  "grounded_reason": "missing_ground_truth"
}
```

---

## CONSISTENCY CHECK (trivial only)

```python
def check_reasoning_execution_consistent(reasoning_obj, ev):
    if reasoning_obj.get("fix_strategy", "").strip() and not ev.get("pass"):
        return False
    return True
```

---

## SCHEMA VERSION ENFORCEMENT

```python
CURRENT_REASONING_SCHEMA = 2

def enforce_schema_version(events_path):
    if not events_path.exists():
        return
    first = open(events_path).readline().strip()
    if not first:
        return
    import json
    v = json.loads(first).get("reasoning_schema_version", 1)
    if v != CURRENT_REASONING_SCHEMA:
        raise RuntimeError(f"Schema mismatch: existing={v}, current={CURRENT_REASONING_SCHEMA}")
```

---

## TEST SUITE

### Validation tests

```
test_no_fields_present → attempted=False, present=False
test_partial_fields_present → attempted=False (not all), present depends on content
test_all_fields_present_empty → attempted=True, present=False
test_all_fields_present_populated → attempted=True, present=True
```

### Classifier parse tests

```
test_valid_3_lines → all fields parsed
test_too_few_dimension_fields → parse_error="expected_5_fields_got_N"
test_invalid_dimension_value → parse_error="invalid_dimension_X_Y"
test_missing_confidence_line → parse_error="expected_3_lines_got_1"
test_invalid_confidence → parse_error="invalid_confidence_MAYBE"
test_missing_explanation → parse_error="missing_explanation"
test_whitespace_normalization → " YES ; YES ; YES ; YES ; TYPE " → parsed correctly
test_lowercase_normalization → "yes;yes;yes;yes;type" → parsed correctly
```

### Category tests

```
test_true_success → reasoning_correct=True, code_correct=True
test_leg → reasoning_correct=True, code_correct=False
test_lucky_fix → reasoning_correct=False, code_correct=True
test_true_failure → reasoning_correct=False, code_correct=False
test_no_reasoning → reasoning_present=False
test_classifier_failed → classifier parse error
test_parse_failed → model output unparseable
test_coverage_excludes_failures → classifier_failed and parse_failed NOT in coverage
```

### Grounded mode tests

```
test_grounded_executed → ground truth present, both modes run
test_grounded_skipped → ground truth missing, grounded_executed=False, reason logged
test_disagreement_excludes_skipped → only executed pairs counted
```

### Logging tests

```
test_classifier_parse_error_logged → exact error string in events.jsonl
test_classifier_confidence_logged → HIGH/MEDIUM/LOW in events.jsonl
test_reasoning_lengths_logged → per-field char counts in events.jsonl
test_grounded_flags_logged → attempted/executed/reason in events.jsonl
test_reasoning_obj_in_run_jsonl → full structured object in audit block
test_explanation_in_audit → classifier explanation in audit block
```

### Metric tests

```
test_coverage_formula → excludes no_reasoning + classifier_failed + parse_failed
test_quality_formula → correct / (correct + incorrect), conditional on coverage
test_confidence_distribution → counts per bucket
test_disagreement_by_confidence → rate per bucket
```

---

## IMPLEMENTATION ORDER

1. **Templates** — output_instruction_v1.j2, v2.j2, leg_reduction.j2, classify_reasoning.j2
2. **Config** — add `classifier_mode`, `reasoning_correct_mode` to EvaluationConfig + default.yaml
3. **Parser** — `extract_reasoning_obj()`, `validate_reasoning()`, remove flat `"reasoning"` field, update all parse tiers
4. **Evaluator** — `llm_classify()` rewrite, `parse_classify_output()`, `compute_reasoning_correct()`, `compute_category()`, grounded mode
5. **Execution pipeline** — update `_build_parsed_response()`, `evaluate_output()`, `_propagate_observability()`, `_emit_metrics_event()`, `RunLogger._write_locked()`
6. **Runner** — schema version enforcement at run start
7. **Tests** — all suites listed above

---

## WHAT REMAINS INTENTIONALLY OUT OF SCOPE

- Human evaluation of classifier accuracy (requires manual labeling, not automated)
- `ground_truth_invariant` population for all cases (only SCM cases have it initially)
- Automatic classifier improvement based on disagreement data (analysis, not pipeline)
- Multi-model classifier ensembling (future work)

---

*End of final plan. Zero backward compatibility. One schema. One pipeline. Explicit failure categories. Mandatory confidence. Mandatory explanation.*
