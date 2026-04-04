# Prompt V3 Implementation Plan

**Date:** 2026-04-03
**Status:** PLAN ONLY
**Scope:** Add new prompt family (v3) in parallel to existing v2 prompts

---

## 1. Implementation Strategy

**Strategy: Add new templates in parallel.** Old v2 prompts remain untouched for rollback and A/B comparison.

New templates are added alongside existing ones with a `_v3` suffix. New manifest entries point to new templates. New condition names (`baseline_v3`, etc.) map to the new prompts. The pipeline selects v2 or v3 based on the condition name in the YAML config.

The classifier prompt change is the only one that requires a parallel parser path, because the output format changes from semicolon-delimited text to JSON and from 3-way (CORRECT/PARTIAL/WRONG) to 2-way (CORRECT/INCORRECT). A new parser function is added alongside the old one, selected by a `classifier_schema_variant` field.

**Justification for parallel, not replace:**
- Existing 42,000+ logged events use v2 classifier output format. Replacing in place would break analysis of old logs.
- A/B comparison between v2 and v3 prompts is scientifically valuable — we want to measure whether the new prompts change LEG rates.
- Rollback is trivial: change condition name in config YAML back to v2.

---

## 2. Prompt Inventory and Wiring Map

### 2.1 Code Generation

| | Current | New |
|---|---|---|
| Template | `output_instruction_v3.j2` | `output_instruction_v4.j2` |
| Condition | `baseline_v2` | `baseline_v3` |
| Caller | `execution_v2.py` via manifest | Same, via new manifest entry |
| Parser | `parser_v2.py` | Same — JSON extraction is format-agnostic |
| Strategy | **Add in parallel** | |

### 2.2 Blind Classifier

| | Current | New |
|---|---|---|
| Template | `classify_reasoning_v2.j2` | `classify_reasoning_v3.j2` |
| Config key | `evaluation.classifier_template` | Set to `"classify_reasoning_v3"` |
| Caller | `execution_v2.py:227`, `retry_v2.py:560` | Same call sites, template name from config |
| Parser | `evaluator_v2.py:parse_classifier_v2_output()` | New: `parse_classifier_v3_output()` |
| Strategy | **Add in parallel** with new parser |

### 2.3 Oracle Classifier

| | Current | New |
|---|---|---|
| Template | `reasoning_truth_prompt.j2` | `oracle_classifier_v2.j2` |
| Caller | `evaluators/reasoning_truth.py:render_prompt()` | New: render via prompting compiler |
| Parser | `evaluators/reasoning_truth.py:parse_response()` | New: JSON parser matching blind classifier schema |
| Strategy | **Add in parallel** — new template + new parser function. Old oracle remains for comparison. |

### 2.4 Retry Critique

| | Current | New |
|---|---|---|
| Template | `critique_strict.j2` / `critique_moderate.j2` / `critique_aggressive.j2` / `critique_mismatch_v2.j2` | `critique_mismatch_v3.j2` (one template replaces all 4) |
| Caller | `retry_v2.py:_generate_critique()` | Same, new template name |
| Parser | `_truncate_to_one_sentence()` | Same — kept as safety net |
| Strategy | **Add in parallel** — old variants remain. New conditions use v3 critique. |

### 2.5 LEG Lean

| | Current | New |
|---|---|---|
| Template | `leg_reduction_lean_v2.j2` | `leg_reduction_lean_v3.j2` |
| Condition | `leg_reduction_lean_v2` | `leg_reduction_lean_v3` |
| Parser | `parser_v2.py` | Same |
| Strategy | **Add in parallel** |

### 2.6 Reasoning-Only Retry

| | Current | New |
|---|---|---|
| Template | `critique_reasoning_only.j2` | `critique_reasoning_only_v2.j2` |
| Caller | `retry_v2.py` variant dispatch | New variant entry |
| Parser | `_truncate_to_one_sentence()` | Same |
| Strategy | **Add in parallel** |

---

## 3. Exact New Prompts

All 6 prompts are taken verbatim from the spec. The only modifications are:
- Adding Jinja2 section tags (`<<SECTION:...>>`) required by the compiler
- Adding template variables (`{{ task }}`, `{{ code_files_block }}`, etc.) where the spec uses placeholders
- Adding `{{ file_keys_example }}` for the files schema hint

### 3.1 `output_instruction_v4.j2`

```jinja2
<<SECTION:output_instruction>>
You are given a Python codebase with one or more files and a failing test.

Your task is to produce a corrected version of the code that fixes the bug.

## REQUIREMENTS

1. You must output the FULL corrected code for ALL files.
2. You must NOT omit unchanged files.
3. You must NOT describe changes — only output final code.
4. Your fix must preserve intended functionality and only correct the bug.
5. Do not introduce unrelated changes.

## CRITICAL: STRUCTURED OUTPUT

You MUST return a JSON object with EXACTLY the following fields:

{
  "files": {
    {{ file_keys_example }}
  },
  "code_commitments": [
    "commitment 1",
    "commitment 2"
  ]
}

## CODE COMMITMENTS (VERY IMPORTANT)

Each commitment MUST:
- Refer to a specific code behavior or invariant
- Be testable from the code
- Be concrete and non-generic

GOOD examples:
- "create_config returns a copy of DEFAULTS instead of the original dict"
- "cache is cleared before recomputation to avoid stale reads"
- "rollback restores sender balance on failure"

BAD examples (FORBIDDEN):
- "fix bug"
- "improve logic"
- "make it work"

If commitments are vague or generic, your answer will be rejected.

## OUTPUT RULES

- Output ONLY valid JSON
- No explanations
- No markdown
- No extra text

Failure to follow format = invalid output
<<END_SECTION:output_instruction>>
```

### 3.2 `classify_reasoning_v3.j2`

```jinja2
<<SECTION:evaluation_instruction>>
You are evaluating whether a model correctly understood a bug and produced a valid fix.

You are given:
- Original code
- Model-generated fixed code
- Model-provided code_commitments

You MUST evaluate the reasoning WITHOUT executing the code.

## INPUTS

Task: {{ task }}

Code Produced:
{{ code }}

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}
{% if code_commitments %}
Code Commitments: {{ code_commitments }}
{% endif %}

{% if classifier_mode == "grounded" %}
## Ground Truth
Bug type: {{ ground_truth_failure_mode }}
Bug location: {{ ground_truth_trap }}
{% if ground_truth_invariant %}
Invariant: {{ ground_truth_invariant }}
{% endif %}
{% endif %}

## TASK

Determine whether the model:
1. Identified the correct underlying mechanism of the bug
2. Produced commitments that correspond to the correct fix
3. Produced code consistent with those commitments

## DEFINITIONS

mechanism_identified: Did the model correctly identify the root cause of the bug?
- CORRECT if the fix targets the actual root cause
- INCORRECT if it fixes symptoms or unrelated logic

commitments_extracted: Do the commitments reflect the actual fix behavior?
- CORRECT if commitments are specific and match the correct fix
- INCORRECT if generic, vague, or unrelated

commitments_satisfied: Do the commitments describe a correct solution?
- CORRECT if the commitments describe a correct fix
- INCORRECT if they describe an incorrect or incomplete fix

reasoning_code_alignment: Does the code implement the commitments?
- CORRECT if code implements the commitments
- INCORRECT if mismatch exists

## OUTPUT FORMAT (STRICT)

Return EXACTLY this JSON. No other text.

{"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"}

RULES:
- You MUST choose CORRECT or INCORRECT for EACH field
- You MUST NOT output null, missing fields, or explanations
- If unsure, choose INCORRECT

Do NOT execute code. Do NOT assume correctness from tests. Judge only from logic and structure.
<<END_SECTION:evaluation_instruction>>
```

**Compatibility note:** The new classifier template uses the same input variables as the current one (`root_cause`, `fix_strategy`, `code`, `task`, `classifier_mode`, ground truth fields). The variable `code_commitments` is new — `build_classifier_v2_vars()` must be updated to pass it. The variable `failure_types` is removed (no longer needed). The variable `risk_check` is removed.

### 3.3 `oracle_classifier_v2.j2`

```jinja2
<<SECTION:evaluation_instruction>>
You are evaluating whether a model's code fix is correct using execution results.

You are given:
- Original code
- Model-generated fixed code
- Model-provided code_commitments
- Execution result (pass/fail + error details)

## INPUTS

Task: {{ task }}

Original Buggy Code:
{{ buggy_code }}

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}
{% if code_commitments %}
Code Commitments: {{ code_commitments }}
{% endif %}

Execution Result: {{ exec_result }}

## Ground Truth
Bug type: {{ bug_type }}
Bug location: {{ bug_location }}
Invariant: {{ invariant }}
Fix pattern: {{ fix_pattern }}
Mechanism: {{ mechanism_description }}

## TASK

Determine whether the model:
1. Identified the correct mechanism
2. Proposed valid commitments
3. Produced correct code according to execution
4. Aligned reasoning with actual behavior

## OUTPUT FORMAT (STRICT)

Return EXACTLY this JSON. No other text.

{"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"}

RULES:
- All fields MUST be present
- No nulls, no explanations
- If uncertain, choose INCORRECT

EXECUTION USAGE:
- If tests FAIL → commitments_satisfied = INCORRECT
- If tests PASS → commitments_satisfied may be CORRECT, but still verify logic
- A fix can PASS tests but still have INCORRECT reasoning
- A fix can FAIL tests but still have CORRECT reasoning (LEG case)

Evaluate both dimensions separately.
<<END_SECTION:evaluation_instruction>>
```

### 3.4 `critique_mismatch_v3.j2`

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

### 3.5 `leg_reduction_lean_v3.j2`

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
  "code_commitments": ["<scope> must <action>"],
  "fix_strategy": "<concrete code change>",
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

### 3.6 `critique_reasoning_only_v2.j2`

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

---

## 4. Exact Implementation Plan

### 4.1 New template files (6 new files)

| File | Type | Purpose |
|---|---|---|
| `core/prompts/components/output_instruction_v4.j2` | NEW | V3 code generation output instruction |
| `core/prompts/components/classify_reasoning_v3.j2` | NEW | V3 binary classifier (JSON output) |
| `core/prompts/components/oracle_classifier_v2.j2` | NEW | V3 oracle with execution + JSON output |
| `core/prompts/components/critique_mismatch_v3.j2` | NEW | V3 consolidated critique |
| `core/prompts/components/leg_reduction_lean_v3.j2` | NEW | V3 LEG lean (no risk_check) |
| `core/prompts/components/critique_reasoning_only_v2.j2` | NEW | V3 reasoning-only critique |

### 4.2 Prompt manifest (`core/prompts/prompt_manifest.yaml`) — ADDITIVE

Add new condition entries:

```yaml
  baseline_v3:
    components: ["task_and_code", "output_instruction_v4"]
    nudge:
      type: "none"
    include_output_instruction: false
    label: "BASELINE_V3"

  leg_reduction_lean_v3:
    components: ["leg_reduction_lean_v3"]
    nudge:
      type: "none"
    include_output_instruction: false
    label: "LEG_LEAN_V3"

  critique_mismatch_v3:
    components: ["critique_mismatch_v3"]
    nudge:
      type: "none"
    include_output_instruction: false
    label: "CRITIQUE_V3"
```

### 4.3 Component metadata (`core/prompts/component_metadata.yaml`) — ADDITIVE

Add metadata entries for all 6 new components with required_inputs, optional_inputs, exports.

### 4.4 Condition registry (`core/registry/condition_registry.py`) — ADDITIVE

Add new condition specs:

```python
"baseline_v3": ConditionSpec(
    name="baseline_v3",
    universal=True,
    description="V3 baseline: strict JSON with code_commitments",
    prompt_template="baseline_v3",
),
"leg_reduction_lean_v3": ConditionSpec(
    name="leg_reduction_lean_v3",
    universal=True,
    description="V3 LEG lean: minimal reasoning scaffold, no risk_check",
    prompt_template="leg_reduction_lean_v3",
),
```

Add v3 retry conditions similarly.

### 4.5 Contracts (`core/contracts/contracts_v2.py`) — ADDITIVE

Add:

```python
V3_VALID_DIMENSION_VALUES = frozenset({"CORRECT", "INCORRECT"})
```

Add `baseline_v3` and `leg_reduction_lean_v3` to `CONDITION_TO_SCHEMA` and `V2_CONDITIONS` (or a new `V3_CONDITIONS` set).

### 4.6 Evaluator (`core/evaluation/evaluator_v2.py`) — ADDITIVE

Add new parser function:

```python
def parse_classifier_v3_output(raw: str) -> ClassifierResultV2:
    """Parse v3 binary JSON classifier output."""
    result = ClassifierResultV2(classify_raw=raw, classifier_schema_variant="v3_json")
    
    stripped = _strip_debug(raw).strip()
    try:
        d = json.loads(stripped)
    except json.JSONDecodeError as e:
        result.parse_error = f"json_decode_error: {e}"
        return result
    
    required = ("mechanism_identified", "commitments_extracted",
                "commitments_satisfied", "reasoning_code_alignment")
    for key in required:
        val = d.get(key)
        if val not in ("CORRECT", "INCORRECT"):
            result.parse_error = f"invalid_value: {key}={val}"
            return result
    
    result.mechanism_identified = d["mechanism_identified"]
    result.commitments_extracted = d["commitments_extracted"]
    result.commitments_satisfied = d["commitments_satisfied"]
    result.reasoning_code_alignment = d["reasoning_code_alignment"]
    result.parse_error = None
    return result
```

Update `build_classifier_v2_vars()` to pass `code_commitments` from artifact:

```python
if artifact.normalized_code_commitments:
    variables["code_commitments"] = ", ".join(artifact.normalized_code_commitments)
```

### 4.7 Execution pipeline (`core/pipeline/orchestration/execution_v2.py`) — ADDITIVE

After classifier call, select parser based on template:

```python
if config.evaluation.classifier_template.startswith("classify_reasoning_v3"):
    classifier_result = parse_classifier_v3_output(classify_result.response)
else:
    classifier_result = parse_classifier_v2_output(classify_result.response)
```

Update `schema_line` construction to handle v3 conditions:

```python
if condition in ("baseline_v3",):
    schema_line = '{"files": {' + file_keys_example + '}, "code_commitments": ["...", "..."]}'
```

### 4.8 Retry pipeline (`core/pipeline/orchestration/retry_v2.py`) — ADDITIVE

Add `critique_mismatch_v3` to variant dispatch:

```python
variant_to_component = {
    "strict": "critique_strict",
    "moderate": "critique_moderate",
    "aggressive": "critique_aggressive",
    "reasoning_only": "critique_reasoning_only",
    "strict_v3": "critique_mismatch_v3",
    "reasoning_only_v2": "critique_reasoning_only_v2",
}
```

Update `_resolve_critique_variant()` to map v3 conditions to v3 critique templates.

Update retry `schema_line` to include `code_commitments` for v3 conditions.

### 4.9 Metrics (`core/evaluation/metrics_v2.py`) — NO CHANGE NEEDED

`derive_v2_signals()` already handles the case where dimension values are CORRECT or not. With V3 binary output:
- `mechanism_correct = (m == "CORRECT")` — works as-is
- `commitments_valid = (ce in ("CORRECT", "PARTIAL"))` — with V3 this becomes `(ce == "CORRECT")` since PARTIAL never appears. No code change needed — `"CORRECT" in ("CORRECT", "PARTIAL")` is True.
- Same for `alignment_positive` and `commitments_satisfied_positive`.

The existing logic is backward-compatible with binary values. PARTIAL simply never appears in v3 outputs, so the `in ("CORRECT", "PARTIAL")` check degrades to `== "CORRECT"`. No metrics code changes required.

### 4.10 Oracle integration — STAGED

The new oracle classifier (`oracle_classifier_v2.j2`) has a different variable set than the current oracle (adds `exec_result`, `code_commitments`). This requires:
- New `build_oracle_v2_vars()` function in evaluator_v2.py
- New `parse_oracle_v2_output()` function (same as `parse_classifier_v3_output`)
- Wiring into Stage 6b per oracle integration plan

This is staged after the blind classifier migration. The oracle integration plan (v1) provides the exact wiring. The new oracle template uses the same JSON output schema as the blind classifier, so the same parser works for both.

### 4.11 Analysis code — NO CHANGES

- `analysis/load_logs.py` reads `reasoning_correct` from events — binary values produce the same boolean
- `dashboard/leg_scanner.py` reads the same fields — no changes
- `dashboard/metrics_registry.py` — no changes

---

## 5. Naming Convention

| Prompt type | Current name | New name |
|---|---|---|
| Code generation | `output_instruction_v3.j2` | `output_instruction_v4.j2` |
| Blind classifier | `classify_reasoning_v2.j2` | `classify_reasoning_v3.j2` |
| Oracle classifier | `reasoning_truth_prompt.j2` | `oracle_classifier_v2.j2` |
| Retry critique | `critique_mismatch_v2.j2` / `critique_strict.j2` / etc. | `critique_mismatch_v3.j2` |
| LEG lean | `leg_reduction_lean_v2.j2` | `leg_reduction_lean_v3.j2` |
| Reasoning-only | `critique_reasoning_only.j2` | `critique_reasoning_only_v2.j2` |

Condition names:

| Current | New |
|---|---|
| `baseline_v2` | `baseline_v3` |
| `leg_reduction_lean_v2` | `leg_reduction_lean_v3` |
| `retry_leg_critique_strict_v2` | `retry_leg_critique_strict_v3` |
| `retry_reasoning_only_critique_v1` | `retry_reasoning_only_critique_v2` |

---

## 6. Binary vs Legacy Decisions

| Decision | Choice | Justification |
|---|---|---|
| New blind classifier in parallel | **Yes** | Old classifier stays for old log analysis. New runs use v3 binary classifier via `evaluation.classifier_template: "classify_reasoning_v3"`. |
| Legacy parser retained | **Yes** | `parse_classifier_v2_output()` stays for backward compatibility with old event data. New `parse_classifier_v3_output()` used for new runs. Parser selected by `classifier_schema_variant` field. |
| New runs use only CORRECT/INCORRECT | **Yes** | V3 classifier template only allows CORRECT/INCORRECT. PARTIAL cannot appear. |
| Oracle integration timing | **Same migration, behind config flag** | `evaluation.oracle.enabled: true` + `evaluation.oracle.template: "oracle_classifier_v2"`. Default: disabled. Landed in same PR but independently controllable. |
| Old prompts remain available | **Yes** | Config `conditions: { baseline_v2: ... }` still works. Config `conditions: { baseline_v3: ... }` uses new prompts. A/B comparison possible in same experiment. |

---

## 7. Parsing / Evaluator Congruence

### 7.1 Code Generation (`output_instruction_v4.j2`)

- **Parser:** `parser_v2.py:parse_v2_execution()` — extracts JSON, gets `files_dict`
- **Contract:** Must produce `{"files": {...}, "code_commitments": [...]}`
- **Parser changes:** None. Parser extracts `full_json` generically. `reasoning_v2.py` already handles `code_commitments`.
- **Failure mode if not updated:** None — parser is format-agnostic.

### 7.2 Blind Classifier (`classify_reasoning_v3.j2`)

- **Parser:** New `parse_classifier_v3_output()` — `json.loads()` + key validation
- **Contract:** Must produce `{"mechanism_identified": "CORRECT"|"INCORRECT", ...}` — exactly 4 keys, each binary
- **Parser changes:** New function required. Old function unchanged.
- **Failure mode if not updated:** If old parser receives JSON, it will fail on line 1 (no semicolons) → `classifier_failure_v2`. **Must use new parser.**
- **Selection logic:** `execution_v2.py` selects parser based on `config.evaluation.classifier_template`.

### 7.3 Oracle Classifier (`oracle_classifier_v2.j2`)

- **Parser:** Same as blind v3 — `parse_classifier_v3_output()` (same JSON schema)
- **Contract:** Same 4-key JSON
- **Parser changes:** Reuses blind v3 parser
- **Failure mode if not updated:** Same as blind — old parser fails on JSON input

### 7.4 Retry Critique (`critique_mismatch_v3.j2`)

- **Parser:** `_truncate_to_one_sentence()` (unchanged)
- **Contract:** One sentence or `NO_MISMATCH`
- **Parser changes:** None
- **Failure mode:** None — same format as current

### 7.5 LEG Lean (`leg_reduction_lean_v3.j2`)

- **Parser:** `parser_v2.py` (unchanged)
- **Contract:** JSON with `root_cause`, `code_commitments`, `fix_strategy`, `files`
- **Parser changes:** None
- **Note:** No `risk_check` field. `reasoning_v2.py` handles missing fields gracefully.

### 7.6 Reasoning-Only (`critique_reasoning_only_v2.j2`)

- **Parser:** `_truncate_to_one_sentence()` (unchanged)
- **Contract:** One sentence or `NO_MISMATCH` (standardized sentinel)
- **Parser changes:** Update sentinel check in `retry_v2.py` from `NO_WEAKNESS` to `NO_MISMATCH` for v2 variant
- **Failure mode:** If sentinel not updated, reasoning-only critique never recognizes coherent reasoning → always produces a critique

---

## 8. Risk Register

| Risk | Why it happens | Detection | Mitigation |
|---|---|---|---|
| Old logs incompatible with new parser | v2 events have PARTIAL + semicolon format | `parse_classifier_v3_output()` would fail on old data | Parser selection by `classifier_schema_variant` — old logs use old parser |
| LEG rates shift | PARTIAL removal tightens `commitments_valid` | Compare v2 vs v3 LEG rates on same cases | Expected and intentional. Document as recalibration. |
| Retry produces no commitments | `schema_line` not updated for v3 retry | Retry JSON responses missing `code_commitments` | Update retry `schema_line` in same PR |
| Models struggle with JSON-only classifier | Some models add explanations around JSON | `json.loads()` fails → `parse_error` | Prompt says "No other text" + strip surrounding text before parsing |
| Dashboard expects `failure_type` field | v3 classifier doesn't produce failure_type | `mechanism_label` column is None in dashboard | Accept — `failure_type` comes from case metadata, not classifier. Dashboard already shows case `failure_mode`. |
| Oracle + blind classifier semantics diverge | Oracle sees execution results, blind doesn't | Compare oracle vs blind verdicts on same cases | By design — oracle is the ground truth comparator |
| A/B comparison confusing | Same experiment can mix v2 and v3 conditions | Condition name includes version (baseline_v2 vs baseline_v3) | Clear naming prevents confusion |
| `code_commitments` variable missing from classifier vars | `build_classifier_v2_vars()` doesn't pass it | v3 classifier sees empty commitments | Update `build_classifier_v2_vars()` to include commitments from artifact |

---

## 9. Implementation Sequence

1. **Add 6 new template files** — zero risk, additive only
2. **Add manifest entries** for `baseline_v3`, `leg_reduction_lean_v3`, `critique_mismatch_v3` — additive
3. **Add component metadata** for new templates — additive
4. **Add condition registry entries** for v3 conditions — additive
5. **Add `V3_CONDITIONS` to contracts** + update `CONDITION_TO_SCHEMA` — additive
6. **Add `parse_classifier_v3_output()`** to `evaluator_v2.py` — additive, does not affect v2 path
7. **Update `build_classifier_v2_vars()`** to pass `code_commitments` — additive, v2 template ignores extra variables
8. **Update `execution_v2.py`** to select parser by classifier template name — conditional logic
9. **Update `retry_v2.py`** to map v3 conditions to v3 critique templates + update schema_line for v3
10. **Run smoke test** with v3 conditions — verify full pipeline
11. **Run 10-case comparison** v2 vs v3 on same cases — verify metrics compute
12. **(Optional) Wire oracle v2** behind `evaluation.oracle.enabled` flag

---

## 10. Required Tests

| Test | What to verify | Expected output |
|---|---|---|
| `baseline_v3` generation | JSON with `files` + `code_commitments`, no markdown | Valid JSON, commitments are list of strings |
| `baseline_v3` retry | Retry prompt includes `code_commitments` in schema | Model produces commitments in retry response |
| `classify_reasoning_v3` | Returns strict JSON with 4 binary fields | `{"mechanism_identified": "CORRECT", ...}` — no PARTIAL |
| `classify_reasoning_v3` parse | `parse_classifier_v3_output()` returns populated result | All 4 dimensions set, `parse_error = None` |
| `classify_reasoning_v3` malformed | Parser rejects non-JSON gracefully | `parse_error` set, dimensions = None |
| `critique_mismatch_v3` | One sentence or `NO_MISMATCH` | No multi-sentence output |
| `critique_reasoning_only_v2` | One sentence or `NO_MISMATCH` (new sentinel) | Standardized sentinel |
| `leg_reduction_lean_v3` | JSON with `root_cause`, `code_commitments`, `fix_strategy`, `files` — no `risk_check` | Valid JSON, no risk_check field |
| Old v2 logs | Still parseable with old parser | `parse_classifier_v2_output()` works on old events |
| Metrics computation | `derive_v2_signals()` produces valid LEG/category for binary inputs | No errors, categories compute correctly |
| A/B comparison | Run same cases with v2 and v3 conditions in one experiment | Both produce valid events with correct schemas |
