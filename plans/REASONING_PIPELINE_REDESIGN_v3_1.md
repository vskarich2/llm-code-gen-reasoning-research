# Reasoning Pipeline Redesign v3.1 — Final Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval
**Supersedes:** v1, v2, v3

---

## DIFF FROM V3

### REMOVED:
- All causal marker validation (`CAUSAL_MARKERS`, keyword detection, scenario detection)
- All surface-text heuristics (`validate_failure_mechanism`, `no_causal_explanation`, `no_concrete_scenario`)
- Field-level issue taxonomy (`field_issues` dict with `"no_code_reference"`, `"generic_filler"`, etc.)
- `overall_score` field (0-4 scoring)
- Task-restatement detection (80% overlap check)
- Token overlap invariant alignment metric
- Regex-based function name matching in consistency check
- String-based code→reasoning consistency heuristics
- `reasoning_quality: "degraded"` category (replaced by simpler model)
- Silent exclusion from aggregate metrics

### CHANGED:
- Validation reduced to: field presence + minimum length + field count. Nothing else.
- `reasoning_execution_consistent` simplified to one trivial check only
- All semantic judgment delegated exclusively to classifier
- Metric reporting: coverage and quality always reported separately, never merged
- Grounded mode elevated from calibration tool to first-class evaluation mode
- Classifier explanation strengthened: must reference reasoning + code

### ADDED:
- `reasoning_coverage` metric (% of outputs with reasoning present)
- `reasoning_quality_given_present` metric (classifier verdict conditional on presence)
- `classifier_disagreement_rate` (blind vs grounded)
- Adversarial test: correct reasoning, wrong location
- Explicit layer separation table

---

## ARCHITECTURE: LAYER SEPARATION

| Layer | Responsibility | What it DOES | What it MUST NOT DO |
|-------|---------------|--------------|---------------------|
| **Prompt** | Elicit reasoning | Ask for root_cause, failure_mechanism, broken_invariant, fix_strategy with grounding instructions | Judge reasoning quality |
| **Parser** | Extract structure | Pull JSON fields into `reasoning_obj` dict | Validate semantics, filter content, score quality |
| **Validation** | Check presence | `reasoning_present: bool`, `reasoning_fields_present: int (0-4)`, `reasoning_min_length_ok: bool` | Keyword matching, NLP heuristics, causal marker detection |
| **Classifier** | Evaluate semantics | Judge mechanism, invariant, fix alignment, reasoning-code alignment. Return 4 dimensions + explanation | Make execution decisions, modify data |
| **Metrics** | Aggregate results | Compute coverage, quality, regime categories. Report separately. | Silently exclude cases, mix blind/grounded |

**Hard rule:** No layer may perform the responsibilities of another layer.

---

## A. GENERATION PROMPT (reasoning elicitation)

**Reasoning schema (shared across baseline and LEG):**

```json
{
  "root_cause": "<what the bug is — name the function/variable and the causal relationship>",
  "failure_mechanism": "<how the bug manifests — describe a concrete scenario with cause and effect>",
  "broken_invariant": "<the semantic contract the bug violates — must be a testable statement>",
  "fix_strategy": "<why your code change fixes the mechanism — reference your actual change>",
  "files": { ... }
}
```

**Grounding instructions (in generation prompt):**

```
GROUNDING RULES:
- "root_cause" must name the specific function and variable where the bug lives and explain the causal relationship.
- "failure_mechanism" must describe a concrete scenario showing how data flows or state changes lead to incorrect behavior. Include cause and effect.
- "broken_invariant" must be a specific, testable statement about expected program behavior.
- "fix_strategy" must reference your actual code change and explain why it addresses the mechanism.
- Do not write generic statements. Do not restate the task. Ground every claim in the actual code.
```

**LEG additions:**

```json
{
  "root_cause": "...",
  "failure_mechanism": "...",
  "broken_invariant": "...",
  "fix_strategy": "...",
  "self_check": "<verify your fix against the invariant — reference specific code>",
  "revision_note": "<what changed from prior attempt and why — null if first attempt>",
  "attempt_number": 0,
  "previous_attempt_summary": null,
  "files": { ... }
}
```

---

## B. PARSER (structure extraction only)

**What the parser does:**

```python
def extract_reasoning_obj(parsed_json):
    """Extract reasoning fields. No semantic validation."""
    return {
        "root_cause": parsed_json.get("root_cause", ""),
        "failure_mechanism": parsed_json.get("failure_mechanism", ""),
        "broken_invariant": parsed_json.get("broken_invariant", ""),
        "fix_strategy": parsed_json.get("fix_strategy", ""),
        # LEG-only (present if LEG schema):
        "self_check": parsed_json.get("self_check", ""),
        "revision_note": parsed_json.get("revision_note"),
        "attempt_number": parsed_json.get("attempt_number", 0),
        "previous_attempt_summary": parsed_json.get("previous_attempt_summary"),
    }
```

**Backward compatibility:** If response has old `"reasoning"` field but no structured fields:
```python
if "root_cause" not in parsed_json and "reasoning" in parsed_json:
    # Old schema — store flat string, no structured obj
    reasoning_obj = None
    reasoning_text = parsed_json["reasoning"]
else:
    reasoning_obj = extract_reasoning_obj(parsed_json)
    reasoning_text = f"{reasoning_obj['root_cause']} {reasoning_obj['failure_mechanism']}"
```

`parsed["reasoning_obj"]` is the structured object (or None for old schema).
`parsed["reasoning"]` is the flat string (always present, for backward compat).

---

## C. VALIDATION (presence check only)

```python
REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")
MIN_FIELD_LENGTH = 10  # chars

def validate_reasoning_presence(reasoning_obj):
    """Check presence and minimum length. No semantic judgment."""
    if reasoning_obj is None:
        return {"reasoning_present": False, "reasoning_fields_present": 0, "reasoning_min_length_ok": False}

    fields_present = sum(
        1 for f in REASONING_FIELDS
        if reasoning_obj.get(f, "").strip() and len(reasoning_obj.get(f, "").strip()) >= MIN_FIELD_LENGTH
    )

    return {
        "reasoning_present": fields_present > 0,
        "reasoning_fields_present": fields_present,
        "reasoning_min_length_ok": fields_present == len(REASONING_FIELDS),
    }
```

That's it. No keyword matching. No NLP. No scoring taxonomy.

---

## D. CLASSIFIER (all semantic evaluation)

**Input:** Full reasoning_obj (4 fields, or 6 for LEG) + task + code.

**Classifier prompt:**

```
You are evaluating the quality of a developer's reasoning about a software bug.
You are ONLY evaluating reasoning. You are NOT judging code correctness.

# Developer's Reasoning

## Root Cause
{{ root_cause }}

## Failure Mechanism
{{ failure_mechanism }}

## Broken Invariant
{{ broken_invariant }}

## Fix Strategy
{{ fix_strategy }}

{% if self_check %}
## Self-Check
{{ self_check }}
{% endif %}

# Task Description
{{ task }}

# Code Produced
```python
{{ code }}
```

{% if classifier_mode == "grounded" %}
# Ground Truth
Bug type: {{ ground_truth_failure_mode }}
Bug location: {{ ground_truth_trap }}
{% if ground_truth_invariant %}
Known invariant: {{ ground_truth_invariant }}
{% endif %}
Compare the developer's reasoning against this ground truth.
{% endif %}

# Evaluate Each Dimension

1. mechanism_identified:
   YES = correctly identifies the specific function/variable AND the causal chain
   PARTIAL = identifies the general area but is vague or incomplete about the mechanism
   NO = wrong mechanism, different bug, or only restates the task

2. invariant_identified:
   YES = states the specific testable property that the bug violates
   PARTIAL = states a related but imprecise property
   NO = no invariant, or irrelevant invariant

3. fix_alignment:
   YES = fix strategy directly addresses the identified mechanism
   PARTIAL = fix is in the right area but incomplete
   NO = fix does not address the mechanism or contradicts reasoning

4. reasoning_code_alignment:
   YES = generated code implements what reasoning describes
   PARTIAL = code partially implements reasoning
   NO = code contradicts reasoning or is unchanged

Failure type — choose one: {{ failure_types }}

# Output
Return EXACTLY two lines:
Line 1: <mechanism>;<invariant>;<fix_align>;<code_align>;<failure_type>
Line 2: <explanation referencing the developer's reasoning AND the code behavior>

Examples:
YES;YES;YES;YES;HIDDEN_DEPENDENCY
Reasoning correctly identifies shared reference aliasing in create_config and fix creates a copy via dict().

NO;PARTIAL;NO;NO;UNKNOWN
Reasoning claims a concurrency issue but the actual bug is aliasing. Invariant is vaguely related but mechanism is wrong.

Return ONLY these two lines.
```

---

## E. METRIC COMPUTATION

### `reasoning_correct` derivation:

```python
def compute_reasoning_correct(dims, mode="strict"):
    m = dims["mechanism_identified"]
    i = dims["invariant_identified"]
    f = dims["fix_alignment"]

    if mode == "strict":
        return m == "YES" and i in ("YES", "PARTIAL") and f in ("YES", "PARTIAL")
    elif mode == "lenient":
        return m in ("YES", "PARTIAL") and i in ("YES", "PARTIAL")
    elif mode == "raw":
        return None  # defer to analysis
```

Config: `evaluation.reasoning_correct_mode: "strict"` (default).

### Reporting — two separate metrics, never merged:

**Metric A: Reasoning Coverage**
```
reasoning_coverage = (cases with reasoning_present == True) / total_cases
```

**Metric B: Reasoning Quality (conditional)**
```
reasoning_quality = (cases with reasoning_correct == True) / (cases with reasoning_present == True)
```

**Hard rule:** Aggregate pass rate, LEG rate, etc. are always reported BOTH:
- over all cases (including missing reasoning → reasoning_correct=None → category="unclassified")
- over cases with reasoning present only

Both numbers are in every report. No silent exclusion.

### Blind vs Grounded metrics:

```
blind_reasoning_accuracy = reasoning_quality computed in blind mode
grounded_reasoning_accuracy = reasoning_quality computed in grounded mode
classifier_disagreement_rate = |blind ≠ grounded| / total
```

All three reported when grounded mode runs are available.

---

## F. LOGGING

**events.jsonl (per evaluation):**
```json
{
  "reasoning_schema_version": 2,
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

**run.jsonl (per evaluation, in audit block):**
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
    "classifier_input_fields": ["root_cause", "failure_mechanism", "broken_invariant", "fix_strategy"],
    "classifier_dimensions": {
      "mechanism_identified": "YES",
      "invariant_identified": "YES",
      "fix_alignment": "YES",
      "reasoning_code_alignment": "YES"
    },
    "classifier_explanation": "Reasoning correctly identifies shared reference...",
    "classifier_mode": "blind",
    "classifier_verdict": true,
    "classifier_failure_type": "HIDDEN_DEPENDENCY"
  }
}
```

**call_logger (prompt_assembly provenance):**
Classifier call logs the full reasoning_obj in the variables dict, enabling reconstruction.

---

## G. REASONING-EXECUTION CONSISTENCY (trivial only)

One check. No heuristics.

```python
def check_reasoning_execution_consistent(reasoning_obj, ev):
    """Trivial consistency: claims fix but tests fail."""
    if reasoning_obj and reasoning_obj.get("fix_strategy", "").strip() and not ev.get("pass"):
        return False
    return True
```

All meaningful consistency checking is the classifier's job (`reasoning_code_alignment` dimension).

---

## H. SCHEMA VERSIONING (runtime enforced)

```python
def validate_reasoning_schema_version(config, events_path):
    """Refuse to write mismatched schema versions to same run directory."""
    if not events_path.exists():
        return
    first_line = open(events_path).readline().strip()
    if not first_line:
        return
    import json
    existing = json.loads(first_line).get("reasoning_schema_version", 1)
    current = 2  # hardcoded — this is schema v2
    if existing != current:
        raise RuntimeError(
            f"SCHEMA VERSION MISMATCH: existing={existing}, current={current}. Use a new run_dir."
        )
```

---

## I. ADVERSARIAL TEST SUITE

```python
class TestAdversarialReasoning:

    def test_correct_reasoning_correct_code(self):
        """All dimensions YES → true_success."""

    def test_correct_reasoning_wrong_code(self):
        """Reasoning correct but code doesn't implement it → LEG."""

    def test_wrong_reasoning_correct_code(self):
        """Code correct but reasoning describes different bug → lucky_fix."""

    def test_wrong_reasoning_wrong_code(self):
        """Everything wrong → true_failure."""

    def test_generic_template_reasoning(self):
        """Plausible but non-specific reasoning → classifier should detect."""

    def test_correct_invariant_wrong_mechanism(self):
        """Right invariant, wrong causal chain → mechanism NO, invariant YES."""

    def test_correct_mechanism_wrong_invariant(self):
        """Right mechanism, wrong invariant → mechanism YES, invariant NO/PARTIAL."""

    def test_correct_reasoning_wrong_location(self):
        """Correct bug type and invariant but applied to wrong function/file.
        Classifier MUST detect this as mechanism NO (wrong location)."""

    def test_task_restatement_as_reasoning(self):
        """Model restates task as reasoning → classifier should return NO on mechanism."""

    def test_missing_reasoning_excluded(self):
        """Empty reasoning → reasoning_present=False, classifier skipped, category=unclassified."""
```

---

## J. FAILURE MODE COVERAGE

| Failure Mode | Detectable? | How |
|---|---|---|
| Correct reasoning + correct code | YES | classifier: all YES + execution pass |
| Correct reasoning + wrong code (LEG) | YES | classifier: mechanism YES + execution fail |
| Wrong reasoning + correct code (lucky fix) | YES | classifier: mechanism NO + execution pass |
| Wrong reasoning + wrong code | YES | classifier: mechanism NO + execution fail |
| Generic/template reasoning | YES | classifier: mechanism NO or PARTIAL (no specific identification) |
| Correct invariant, wrong mechanism | YES | classifier: mechanism NO, invariant YES |
| Correct mechanism, wrong invariant | YES | classifier: mechanism YES, invariant NO |
| Correct reasoning, wrong location | YES | classifier: mechanism NO (wrong function in grounded mode) |
| Missing reasoning | YES | validation: reasoning_present=False, excluded from reasoning metrics |
| Classifier error | MEASURABLE | disagreement rate between blind and grounded modes |

**Not detectable:**
- Subtle reasoning errors that fool both blind and grounded classifiers (requires human evaluation)
- Cases where ground truth is ambiguous (multiple valid mechanisms)

---

## IMPLEMENTATION PHASES

- **R0:** Add `ground_truth_invariant` to cases with SCM data. Add `classifier_mode` and `reasoning_schema_version` to config.
- **R1:** New generation templates (output_instruction_v1.j2, v2.j2, leg_reduction.j2, classify_reasoning.j2)
- **R2:** Parser: extract `reasoning_obj`, `validate_reasoning_presence()`
- **R3:** Classifier: new prompt, 4-dimension + explanation parsing, `compute_reasoning_correct()`, blind/grounded modes
- **R4:** Logging: reasoning_obj, validation, dimensions, explanation in run.jsonl + events.jsonl. Schema version enforcement.
- **R5:** Metrics: coverage + quality separation, disagreement rate
- **R6:** Tests: regime classification, adversarial suite, presence validation

---

*End of v3.1 plan. Awaiting approval.*
