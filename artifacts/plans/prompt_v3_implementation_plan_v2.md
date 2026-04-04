# Prompt V3 Implementation Plan — v2

**Supersedes:** prompt_v3_implementation_plan_v1.md
**Date:** 2026-04-03
**Status:** PLAN ONLY

---

## 1. Implementation Strategy

**Add new templates in parallel.** Old v2 prompts remain for rollback and A/B comparison. New v3 prompts are added as new `.j2` files, new manifest entries, new condition names. Parser selection via explicit `classifier_schema_variant` field, not template-name prefix.

---

## 2. Corrected Code Generation Schema

The v3 code generation prompt outputs the **same field set** as the current v2 pipeline requires:

```json
{
  "root_cause": "<specific mechanism with function/variable>",
  "fix_strategy": "<concrete code change>",
  "code_commitments": ["<scope> must <action>"],
  "files": {
    "path/to/file.py": "full file contents or UNCHANGED"
  }
}
```

**Hard invariants:**
- `root_cause` and `fix_strategy` are REQUIRED — consumed by classifier, critique, reasoning normalization, retry, and event logging
- `code_commitments` is REQUIRED — consumed by classifier and metrics
- `files` must contain **every** file key from the case. Unchanged files must be exactly the string `"UNCHANGED"`. Modified files must contain **complete** file contents.
- `baseline_v3`, `leg_reduction_lean_v3`, and all retry generation paths use this **identical** schema
- Parser (`parser_v2.py`), reasoning normalization (`reasoning_v2.py`), reconstruction (`reconstructor.py`), and event logging do not branch on "first attempt vs retry" for schema shape

---

## 3. Exact New Prompts

### 3.1 `output_instruction_v4.j2`

Composed with `task_and_code.j2` via manifest (not self-contained).

```jinja2
<<SECTION:output_instruction>>
You are given a Python codebase with one or more files and a failing test.

Your task is to produce a corrected version of the code that fixes the bug.

You MUST return a JSON object with EXACTLY the following fields:

{
  "root_cause": "<name the specific function/variable and explain the causal bug mechanism>",
  "fix_strategy": "<describe the exact code change and why it fixes the root cause>",
  "code_commitments": [
    "<scope> must <action>"
  ],
  "files": {
    {{ file_keys_example }}
  }
}

REQUIREMENTS:
- "root_cause": must name a specific function/variable and the causal mechanism, not just symptoms
- "fix_strategy": must describe a concrete code change at a specific location
- "code_commitments": 1-3 testable statements in "<scope> must <action>" form. Must be concrete and non-generic.
- "files": must include EVERY file listed. For unchanged files, use exactly "UNCHANGED". For modified files, include FULL file contents.

GOOD code_commitments:
- "create_config must return a copy of DEFAULTS instead of the original dict"
- "cache must be cleared before recomputation to avoid stale reads"
- "rollback must restore sender balance on failure"

BAD code_commitments (FORBIDDEN):
- "fix bug"
- "improve logic"
- "make it work"

OUTPUT RULES:
- Output ONLY valid JSON
- No explanations
- No markdown fences
- No extra text
<<END_SECTION:output_instruction>>
```

**Component metadata:**
```yaml
output_instruction_v4:
  version: "1.0.0"
  description: "V4 strict JSON output with root_cause + fix_strategy + code_commitments + files"
  required_inputs: [file_keys_example]
  optional_inputs: []
  control_inputs: []
  input_types: {file_keys_example: str}
  conditional_groups: []
  exports: [output_instruction]
  dependencies: []
  before: []
```

**Manifest entry:**
```yaml
baseline_v3:
  components: ["task_and_code", "output_instruction_v4"]
  nudge:
    type: "none"
  include_output_instruction: false
  label: "BASELINE_V3"
```

### 3.2 `classify_reasoning_v3.j2`

Self-contained (not composed with other templates).

```jinja2
<<SECTION:evaluation_instruction>>
You are evaluating whether a model correctly understood a bug and produced a valid fix.

## INPUTS

Task: {{ task }}

Model's Root Cause: {{ root_cause }}
Model's Fix Strategy: {{ fix_strategy }}
{% if code_commitments %}
Model's Code Commitments: {{ code_commitments }}
{% endif %}

Code Produced:
{{ code }}

{% if classifier_mode == "grounded" %}
## Ground Truth
Bug type: {{ ground_truth_failure_mode }}
Bug location: {{ ground_truth_trap }}
{% if ground_truth_invariant %}
Invariant: {{ ground_truth_invariant }}
{% endif %}
{% endif %}

## TASK

Evaluate FOUR dimensions and classify the failure type.

1. mechanism_identified: Did the model correctly identify the ACTUAL root cause?
   CORRECT = names the right function/variable and the right causal mechanism
   INCORRECT = wrong mechanism, wrong location, describes only symptoms, or too vague

2. commitments_extracted: Do the commitments reflect the actual fix behavior?
   CORRECT = specific and match the correct fix
   INCORRECT = generic, vague, or unrelated

3. commitments_satisfied: Does the code implement the commitments correctly?
   CORRECT = all stated commitments are implemented
   INCORRECT = any commitment is missing, contradicted, or only partially implemented

4. reasoning_code_alignment: Does the code match the stated fix strategy?
   CORRECT = code changes match what the reasoning describes
   INCORRECT = code does something different from stated reasoning

5. failure_type: Choose one from: {{ failure_types }}

If unsure on any dimension, choose INCORRECT.

## OUTPUT FORMAT (STRICT)

Return EXACTLY this JSON. No other text.

{"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT", "failure_type": "ALIASING"}

RULES:
- Each dimension MUST be "CORRECT" or "INCORRECT"
- failure_type MUST be from the list above
- No nulls, no explanations, no extra fields
- Do NOT execute code. Judge only from logic and structure.
<<END_SECTION:evaluation_instruction>>
```

**Component metadata:**
```yaml
classify_reasoning_v3:
  version: "1.0.0"
  description: "V3 binary JSON classifier (4 dimensions + failure_type, CORRECT/INCORRECT only)"
  required_inputs: [root_cause, fix_strategy, task, code, failure_types]
  optional_inputs: [code_commitments, risk_check]
  control_inputs: [classifier_mode]
  input_types:
    root_cause: str
    fix_strategy: str
    task: str
    code: str
    failure_types: str
    code_commitments: str
    classifier_mode: str
  conditional_groups:
    - condition: "classifier_mode == 'grounded'"
      required: [ground_truth_failure_mode, ground_truth_trap]
      optional: [ground_truth_invariant]
  exports: [evaluation_instruction]
  dependencies: []
  before: []
```

### 3.3 `oracle_classifier_v2.j2`

Self-contained. Uses execution results + ground truth.

```jinja2
<<SECTION:evaluation_instruction>>
You are evaluating whether a model's code fix is correct using execution results.

## INPUTS

Task: {{ task }}

Original Buggy Code:
{{ buggy_code }}

Model's Root Cause: {{ root_cause }}
Model's Fix Strategy: {{ fix_strategy }}
{% if code_commitments %}
Model's Code Commitments: {{ code_commitments }}
{% endif %}

Execution Result: {{ exec_result }}

## Ground Truth
Bug type: {{ bug_type }}
Bug location: {{ bug_location }}
Invariant: {{ invariant }}
Fix pattern: {{ fix_pattern }}
Mechanism: {{ mechanism_description }}

## TASK

Evaluate FOUR dimensions and classify the failure type.

1. mechanism_identified: Did the model correctly identify the actual root cause?
   CORRECT = matches the ground truth mechanism
   INCORRECT = different mechanism, symptoms only, or wrong location

2. commitments_extracted: Do the commitments reflect the correct fix?
   CORRECT = specific and aligned with ground truth fix pattern
   INCORRECT = generic, vague, or unrelated

3. commitments_satisfied: Is the fix correct according to execution?
   If tests FAIL → INCORRECT
   If tests PASS → CORRECT only if logic is also sound

4. reasoning_code_alignment: Does reasoning match actual behavior?
   CORRECT = reasoning and execution outcome are consistent
   INCORRECT = reasoning claims one thing, execution shows another

5. failure_type: Choose one from: {{ failure_types }}

IMPORTANT: A fix can PASS tests but have INCORRECT reasoning (lucky fix). A fix can FAIL tests but have CORRECT reasoning (LEG). Evaluate both dimensions independently.

## OUTPUT FORMAT (STRICT)

Return EXACTLY this JSON. No other text.

{"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT", "failure_type": "ALIASING"}

RULES:
- Each dimension MUST be "CORRECT" or "INCORRECT"
- failure_type MUST be from the list above
- No nulls, no explanations, no extra fields
<<END_SECTION:evaluation_instruction>>
```

**Component metadata:**
```yaml
oracle_classifier_v2:
  version: "1.0.0"
  description: "Oracle classifier with execution results, binary JSON, 4 dimensions + failure_type"
  required_inputs: [task, buggy_code, root_cause, fix_strategy, exec_result, bug_type, bug_location, invariant, fix_pattern, mechanism_description, failure_types]
  optional_inputs: [code_commitments]
  control_inputs: []
  input_types:
    task: str
    buggy_code: str
    root_cause: str
    fix_strategy: str
    exec_result: str
    code_commitments: str
  conditional_groups: []
  exports: [evaluation_instruction]
  dependencies: []
  before: []
```

### 3.4 `critique_mismatch_v3.j2`

Same as spec. Sentinel: `NO_MISMATCH`.

```jinja2
<<SECTION:critique_instruction>>
You are comparing a developer's stated reasoning to their code.

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}

Code:
{{ code }}

Task: {{ task }}

Write EXACTLY one sentence describing the specific mismatch between the stated fix strategy and what the code actually does. Name the function or variable that diverges.

If there is no mismatch, write exactly: NO_MISMATCH

Rules:
- Exactly one sentence. No more.
- Be concrete: name the function, variable, or operation.
- Do NOT suggest a fix.
- Do NOT describe multiple issues — pick the most important one.
<<END_SECTION:critique_instruction>>
```

**Component metadata:**
```yaml
critique_mismatch_v3:
  version: "1.0.0"
  description: "One-sentence mismatch critique, standardized NO_MISMATCH sentinel"
  required_inputs: [root_cause, fix_strategy, code, task]
  optional_inputs: []
  control_inputs: []
  input_types: {root_cause: str, fix_strategy: str, code: str, task: str}
  conditional_groups: []
  exports: [critique_instruction]
  dependencies: []
  before: []
```

### 3.5 `leg_reduction_lean_v3.j2`

Self-contained (inlines task + code). Same output schema as baseline_v3 **minus `risk_check`**. `risk_check` absence is tolerated downstream — `reasoning_v2.py:214-216` defaults to empty string.

```jinja2
<<SECTION:reasoning_instruction>>
{{ task }}

{{ code_files_block }}

Fix the bug. Return a SINGLE valid JSON object. No other text. No markdown fences.

## Instructions

1. Identify the bug mechanism: name the function/variable and the causal issue.
2. Write 1-2 commitments your fix must satisfy, each as: "<scope> must <action>"
3. Describe the exact code change.

{
  "root_cause": "<specific mechanism>",
  "fix_strategy": "<concrete code change>",
  "code_commitments": ["<scope> must <action>"],
  "files": {
    {{ file_keys_example }}
  }
}

RULES:
- All fields REQUIRED
- "code_commitments": 1-2 testable items
- "files": include ALL files. "UNCHANGED" for unmodified. Full contents for modified.
- No markdown. No explanations. ONLY the JSON object.
<<END_SECTION:reasoning_instruction>>
```

**Component metadata:**
```yaml
leg_reduction_lean_v3:
  version: "1.0.0"
  description: "V3 LEG lean: minimal scaffold, no risk_check, same schema as baseline_v3"
  required_inputs: [task, code_files_block, file_keys_example]
  optional_inputs: []
  control_inputs: []
  input_types: {task: str, code_files_block: str, file_keys_example: str}
  conditional_groups: []
  exports: [reasoning_instruction]
  dependencies: []
  before: []
```

### 3.6 `critique_reasoning_only_v2.j2`

Same as spec. Sentinel standardized to `NO_MISMATCH`.

```jinja2
<<SECTION:critique_instruction>>
You are auditing a developer's reasoning about a software bug.

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}

Write EXACTLY one sentence identifying the weakest or most unsupported claim in the reasoning. You may reference functions or variables the developer mentions, but do NOT suggest code changes.

If the reasoning is fully coherent, write exactly: NO_MISMATCH

Rules:
- Exactly one sentence.
- Focus on: vagueness, missing causal links, unsupported assumptions, or internal contradictions.
- Do NOT suggest fixes or code changes.
<<END_SECTION:critique_instruction>>
```

**Component metadata:**
```yaml
critique_reasoning_only_v2:
  version: "1.0.0"
  description: "Reasoning-only critique, allows code entity references, NO_MISMATCH sentinel"
  required_inputs: [root_cause, fix_strategy]
  optional_inputs: []
  control_inputs: []
  input_types: {root_cause: str, fix_strategy: str}
  conditional_groups: []
  exports: [critique_instruction]
  dependencies: []
  before: []
```

---

## 4. Schema Variant Dispatch

### 4.1 Explicit field, not prefix hack

Add to `EvaluationConfig`:

```python
classifier_schema_variant: str = "v2_semicolon"  # "v2_semicolon" | "v3_json"
```

Parse from YAML:

```python
classifier_schema_variant=eval_section.get("classifier_schema_variant", "v2_semicolon"),
```

### 4.2 Parser selection

In `execution_v2.py` and `retry_v2.py`, after classifier LLM call:

```python
if config.evaluation.classifier_schema_variant == "v3_json":
    classifier_result = parse_classifier_v3_output(classify_result.response)
else:
    classifier_result = parse_classifier_v2_output(classify_result.response)
```

### 4.3 Logged in event

`assemble_v2_result()` already logs `classifier.classifier_schema_variant` via:

```python
ev["classifier_schema_variant"] = classifier.classifier_schema_variant
```

The v3 parser sets `classifier_schema_variant = "v3_json"` in the result. The v2 parser sets `"v2_5line"`. This flows into the event and is available for analysis segmentation.

### 4.4 Old logs

Old events have `classifier_schema_variant = "v2_5line"` (or absent). Analysis code can segment by this field. No old-log parsing is affected.

---

## 5. failure_type Decision

**Decision: Preserve `failure_type` in the new classifier JSON output.**

Justification:
- `ev["failure_type"]` is consumed by `dashboard/schema.py` (as `mechanism_label`), analysis scripts, and the canonical event schema
- Removing it would break analysis of new runs without a consumer migration
- The classifier already receives `failure_types` as a variable — adding it to the output JSON is trivial
- The oracle prompt also includes `failure_type` for consistency

The v3 classifier and oracle JSON schema is:

```json
{
  "mechanism_identified": "CORRECT" | "INCORRECT",
  "commitments_extracted": "CORRECT" | "INCORRECT",
  "commitments_satisfied": "CORRECT" | "INCORRECT",
  "reasoning_code_alignment": "CORRECT" | "INCORRECT",
  "failure_type": "<from failure_types list>"
}
```

Parser validates: 4 dimensions ∈ {"CORRECT", "INCORRECT"}, failure_type ∈ valid set.

---

## 6. Blind vs Oracle Separation

### Blind classifier

- Primary evaluation signal for the reasoning axis
- No execution input
- No oracle contamination
- Results stored in canonical event fields: `mechanism_identified_dim`, `commitments_extracted_dim`, `commitments_satisfied_dim`, `reasoning_code_alignment_dim`, `mechanism_correct`, `commitments_valid`, `alignment_positive`
- Used to compute `v2_category` (LEG_v2, interpretable_success, etc.)

### Oracle classifier

- Optional parallel signal, controlled by `evaluation.oracle.enabled`
- Receives execution results — separate evaluative frame
- Results stored in **separate event keys**: `oracle_verdict`, `oracle_mechanism`, `oracle_commitments`, `oracle_satisfied`, `oracle_alignment`, `oracle_failure_type`, `oracle_prompt`, `oracle_response_raw`
- **Does NOT participate** in `v2_category` or `reasoning_correct_compat` computation
- Purely additive metadata for analysis
- Can be cross-tabulated with blind classifier to measure classifier accuracy

---

## 7. Event / Logging Additions

New events from v3 runs must include:

| Field | Source | Purpose |
|---|---|---|
| `classifier_schema_variant` | `ClassifierResultV2.classifier_schema_variant` | "v2_5line" or "v3_json" — enables analysis segmentation |
| `classifier_prompt_variant` | `ClassifierResultV2.classifier_prompt_variant` | "classify_reasoning_v2" or "classify_reasoning_v3" |
| `condition` | Already logged | "baseline_v2" vs "baseline_v3" — encodes prompt family |
| `oracle_*` fields | Oracle result dict (if enabled) | 6 oracle-specific fields in `extra` section |

**No new fields needed in the canonical `reasoning` section.** The `classifier_schema_variant` goes into `extra` (which it already does via `assemble_v2_result`). The `condition` field already distinguishes v2 from v3 runs.

Analysis code segments by:
- `condition` — which generation prompt was used
- `classifier_schema_variant` — which classifier output format was used
- `oracle_verdict` presence — whether oracle ran

---

## 8. PARTIAL Removal Impact — Explicit

### Code-compatible without modification

- `mechanism_correct = (m == "CORRECT")` — works for both v2 and v3
- `commitments_valid = (ce in ("CORRECT", "PARTIAL"))` — v3 never produces PARTIAL, so effectively `== "CORRECT"`. No code change needed.
- `alignment_positive = (rca == "CORRECT")` — same
- `reasoning_correct_compat` — same rollup logic, tighter bar

### Semantic changes

- `commitments_valid` becomes stricter: v2 accepts PARTIAL (partial implementation = valid), v3 does not. A case that was `commitments_valid = True` under v2 (because of PARTIAL) may become `commitments_valid = False` under v3 if the v3 classifier calls it INCORRECT.
- **LEG rates will differ** between v2 and v3 runs on the same cases. This is intentional recalibration.
- `v2_category` distribution will shift: fewer `interpretable_success` (bar raised), potentially more `full_failure_v2`.

### Analysis requirements

- **Never pool v2 and v3 LEG rates** in the same aggregate without explicit recalibration language
- **Segment by `classifier_schema_variant`** in all cross-run analysis
- `analysis/load_logs.py` and `dashboard/metrics_registry.py` need no code changes — they consume the boolean signals which are computed correctly for both schemas

---

## 9. Retry Generation Congruence

**Hard invariant:** Retry generation outputs use the **exact same schema** as first-pass generation.

- Retry `schema_line` for v3 conditions:
  ```python
  schema_line = (
      '{"root_cause": "<...>", "fix_strategy": "<...>", '
      '"code_commitments": ["<scope> must <action>", ...], '
      '"files": {' + file_keys_example + '}}'
  )
  ```
- `critique_retry.j2` already passes `schema_line` as a template variable — no change needed to the critique_retry template
- Parser, reasoning normalization, reconstruction, and event logging apply identically to first-pass and retry outputs
- No branching on "first attempt vs retry" for schema shape

---

## 10. Sentinel Standardization

### Current state

| Location | Sentinel |
|---|---|
| `critique_mismatch_v2.j2` | `NO MISMATCH` (space) |
| `critique_strict.j2` | `NO_MISMATCH` (underscore) |
| `critique_moderate.j2` | `NO_MISMATCH` |
| `critique_aggressive.j2` | `NO_MISMATCH` |
| `critique_reasoning_only.j2` | `NO_WEAKNESS` |
| `retry_v2.py:288` check | Handles all of: `NO_MISMATCH`, `NO MISMATCH`, `NO_WEAKNESS`, `NO WEAKNESS` |

### New state

| Location | Sentinel |
|---|---|
| `critique_mismatch_v3.j2` | `NO_MISMATCH` |
| `critique_reasoning_only_v2.j2` | `NO_MISMATCH` |
| `retry_v2.py:288` check | Unchanged — already handles all variants for backward compat |

Old templates and old logs continue using old sentinels. `retry_v2.py:288` already handles all 4 variants. No code change needed for backward compatibility.

---

## 11. Implementation Sequence

### Gate 0: Pre-flight

- Render all 6 new templates through the compiler with sample variables → verify they produce valid output
- Compile parser golden tests: 3 valid v3 JSON classifier outputs, 2 malformed
- Dry-run `_get_compiler_registry()` with new manifest entries → verify no load errors

### Gate 1: Templates (zero risk)

1. Create 6 new `.j2` files in `core/prompts/components/`
2. Add 6 component metadata entries in `core/prompts/component_metadata.yaml`
3. Add manifest entries for `baseline_v3`, `leg_reduction_lean_v3`, `critique_mismatch_v3`
4. Add condition registry entries for v3 conditions

### Gate 2: Parser + contracts (additive)

5. Add `V3_VALID_DIMENSION_VALUES = frozenset({"CORRECT", "INCORRECT"})` to `contracts_v2.py`
6. Add `baseline_v3`, `leg_reduction_lean_v3` to `CONDITION_TO_SCHEMA` and `V2_CONDITIONS`
7. Add `parse_classifier_v3_output()` to `evaluator_v2.py`
8. Add `classifier_schema_variant` to `EvaluationConfig` + config parser
9. Update `build_classifier_v2_vars()` to pass `code_commitments` from artifact

### Gate 3: Pipeline wiring (conditional logic)

10. Update `execution_v2.py`: parser selection by `classifier_schema_variant`
11. Update `execution_v2.py`: `schema_line` construction for v3 conditions
12. Update `retry_v2.py`: v3 critique variant dispatch + v3 schema_line
13. Update `retry_v2.py`: `_resolve_critique_variant()` for v3 conditions

### Gate 4: Smoke test (one case, one condition)

14. Run `baseline_v3` on `partial_update_a`, 1 trial → verify:
    - Generation output has all 4 required fields
    - Files dict has all keys, UNCHANGED used correctly
    - Classifier returns valid v3 JSON
    - Event has `classifier_schema_variant = "v3_json"`
    - LEG/category metrics compute

### Gate 5: Comparison run

15. Run `baseline_v2` + `baseline_v3` + `leg_reduction_lean_v3` on 2 cases, 2 trials → verify:
    - Both conditions produce valid events
    - v2 and v3 events have different `classifier_schema_variant`
    - Metrics compute for both without errors

### Gate 6: Oracle (optional, behind flag)

16. Add oracle wiring per oracle integration plan
17. Run with `evaluation.oracle.enabled: true` → verify oracle fields in event

---

## 12. Required Tests

### Generation path

| Test | Verification |
|---|---|
| `baseline_v3` first-pass output | JSON has `root_cause`, `fix_strategy`, `code_commitments`, `files` |
| `baseline_v3` files dict | All case file keys present |
| `baseline_v3` UNCHANGED sentinel | Unchanged files use exact string `"UNCHANGED"` |
| `baseline_v3` modified files | Modified files contain full contents (not diff, not partial) |
| `baseline_v3` retry output | Same schema as first-pass (including `code_commitments`) |
| `leg_reduction_lean_v3` output | Same schema minus `risk_check`. `risk_check` absent or empty. |

### Blind classifier

| Test | Verification |
|---|---|
| Valid v3 JSON | `parse_classifier_v3_output()` returns all 4 dimensions + failure_type, `parse_error = None` |
| Extra text around JSON | Parser strips and parses, or fails cleanly |
| Missing key | `parse_error` set, dimensions = None |
| Invalid enum value | `parse_error` set (e.g., `"PARTIAL"` in v3 → error) |
| PARTIAL in v3 | Must be rejected by parser (not a valid v3 value) |

### Oracle classifier

| Test | Verification |
|---|---|
| Same JSON format as blind | Same parser works. All 4 dims + failure_type present. |
| Execution result usage | `commitments_satisfied = INCORRECT` when tests fail |

### Critique

| Test | Verification |
|---|---|
| `critique_mismatch_v3` | Exactly one sentence or `NO_MISMATCH` |
| `critique_reasoning_only_v2` | Exactly one sentence or `NO_MISMATCH` |
| Multi-sentence response | `_truncate_to_one_sentence()` fires as safety net |

### Backward compatibility

| Test | Verification |
|---|---|
| Old v2 classifier output | `parse_classifier_v2_output()` still works on semicolon format |
| Mixed v2+v3 experiment | Both conditions produce valid events, analyzable together |
| `classifier_schema_variant` in events | v2 events: `"v2_5line"`, v3 events: `"v3_json"` |
| Analysis segmentation | `load_logs.py` can filter by `classifier_schema_variant` |

---

## 13. Example Config for V3

```yaml
experiment:
  name: "v3_prompt_test"
  seed: 42

run:
  trial: 1
  run_id: "v3_test"
  run_dir: "logs/v3_prompt_test"

models:
  generation:
    - name: "gpt-4.1-nano"
      temperature: 0.0
      max_tokens: 128000
  evaluator:
    name: "gpt-5-mini"
    temperature: 0.0
    max_tokens: 128000

conditions:
  baseline_v3:
    retry:
      enabled: false
  leg_reduction_lean_v3:
    retry:
      enabled: false

evaluation:
  classifier_mode: "grounded"
  classifier_template: "classify_reasoning_v3"
  classifier_schema_variant: "v3_json"
  subprocess_timeout: 30
  leg:
    enabled: true

cases:
  source: "case_data/cases_v2.json"
  case_ids:
    - "partial_update_a"
    - "alias_config_a"

execution:
  num_workers: 4
  token_budgets:
    default: 12000

trials: 2
```
