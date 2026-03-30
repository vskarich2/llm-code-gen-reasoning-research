# Reasoning Pipeline Redesign — Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval before implementation
**Priority:** HIGH — fixes fundamental measurement failure

---

## 1. ROOT-CAUSE AUDIT

### Current reasoning path failures:

**F1: Baseline does not elicit reasoning.**
The output instruction says `"reasoning" MUST be a non-null string explaining your analysis` — but the task prompt never asks the model to identify the root cause, explain the mechanism, state the broken invariant, or describe the fix strategy. The model can write "I fixed the bug" and satisfy the schema. The classifier then judges this against "correctly identifies the TRUE failure mechanism" — a standard the model was never asked to meet.

**F2: LEG elicits one-sentence reasoning buried in schema theater.**
LEG asks for `"bug_diagnosis": "<one sentence: root cause>"`. The rest of the 80-line prompt is structural scaffolding (revision_history arrays, verification arrays, invariants_checked, changes_made, code_before/code_after). The actual reasoning payload is ~50 chars out of 8-16KB. The model spends output tokens on compliance rather than thinking.

**F3: Classifier receives the wrong object.**
For baseline: the classifier receives `parsed["reasoning"]` which is whatever free-form text the model put in the `"reasoning"` JSON field — typically 1-3 sentences of varying quality.
For LEG: the classifier receives `lr_parsed["bug_diagnosis"]` mapped to `parsed["reasoning"]` — one sentence.
Neither is the full reasoning trace. The classifier judges a lossy surrogate.

**F4: Classifier prompt is ungrounded.**
The classifier is told to judge "the TRUE failure mechanism" but has no ground truth. It must infer from the task description and code what the true mechanism is. For complex multi-file cases, this is unreliable.

**F5: Schema is misaligned across pipeline stages.**
- Generation: asks for `"reasoning"` (free text) or `"bug_diagnosis"` (one sentence)
- Parser: extracts `reasoning` (string, may be empty)
- Logger: stores `parsed.reasoning` and `audit.parsed_reasoning` (same string)
- Classifier: receives `reasoning` (same string, formerly truncated)
- Metrics: stores `reasoning_correct` (boolean from classifier)

There is no structured reasoning object. Reasoning is a flat string throughout.

---

## 2. REVISED DESIGN

### A. New Reasoning Schema (shared across all conditions)

One structured reasoning object, used by baseline AND LEG:

```json
{
  "root_cause": "The function returns a reference to the global DEFAULTS dict instead of a copy. Any caller that modifies the result mutates shared state.",
  "failure_mechanism": "When create_config() is called twice and the first caller modifies the result, the second caller sees the mutation because both hold references to the same dict object.",
  "broken_invariant": "Each call to create_config() must return an independent dict that does not share state with other calls or with DEFAULTS.",
  "fix_strategy": "Return dict(DEFAULTS) or DEFAULTS.copy() to create a shallow copy, breaking the reference sharing.",
  "files": { ... }
}
```

**Fields:**
- `root_cause`: What the bug IS and where it lives. 1-3 sentences.
- `failure_mechanism`: HOW the bug manifests at runtime. Concrete scenario. 1-3 sentences.
- `broken_invariant`: The semantic contract the bug violates. One statement.
- `fix_strategy`: WHY the proposed fix addresses the mechanism. 1-2 sentences.
- `files`: Patched code (unchanged from current system).

**Design rationale:** Four focused fields that the classifier can evaluate independently. Each maps to a specific dimension of reasoning quality. No chain-of-thought, no compliance arrays, no revision scaffolding. Compact, high-signal, mandatory.

### B. Baseline Prompt Changes

Replace `output_instruction_v1.j2` and `output_instruction_v2.j2` with a single new instruction that requests the reasoning schema:

**New `output_instruction_v2.j2`:**

```
Return your response as a single valid JSON object with this schema:

{
  "root_cause": "<what the bug is and where it lives>",
  "failure_mechanism": "<how the bug manifests at runtime — concrete scenario>",
  "broken_invariant": "<the semantic contract the bug violates>",
  "fix_strategy": "<why your fix addresses the mechanism, not just symptoms>",
  "files": { {{ file_entries }} }
}

RULES:
- All four reasoning fields are REQUIRED and must be non-empty substantive text.
- "root_cause" must identify the actual bug, not restate the task.
- "failure_mechanism" must describe a concrete runtime scenario where the bug causes incorrect behavior.
- "broken_invariant" must state a specific contract (e.g., "each call returns an independent copy").
- "fix_strategy" must explain why your code change fixes the mechanism.
- "files" must contain one entry for EVERY file listed above.
- For files you did NOT modify, set the value to "UNCHANGED".
- Return ONLY the JSON object, nothing else.
```

V1 format gets the same reasoning fields but with `"code"` instead of `"files"`.

### C. LEG Prompt Changes

Replace the current 80-line LEG schema with a compact reasoning-centric format:

```
{{ task }}

{{ code_files_block }}

You MUST respond with a SINGLE valid JSON object. Follow this schema:

{
  "root_cause": "<what the bug is and where it lives>",
  "failure_mechanism": "<how the bug manifests at runtime>",
  "broken_invariant": "<the semantic contract the bug violates>",
  "fix_strategy": "<why your fix addresses the mechanism>",
  "self_check": "<verify: does your fix preserve the invariant under all paths? cite specific code>",
  "revision_note": "<if you found an issue during self_check, what did you change and why? null if no revision needed>",
  "files": { ... }
}

PROCEDURE:
1. DIAGNOSE: Identify root cause, mechanism, and broken invariant.
2. PLAN: Describe fix strategy.
3. CODE: Write the fix in "files".
4. SELF-CHECK: Re-read your code. Verify the invariant holds. Check edge cases. Write findings in "self_check".
5. REVISE (if needed): If self_check found issues, fix them. Describe what changed in "revision_note".

RULES:
- All reasoning fields REQUIRED.
- self_check must reference your actual code, not generic statements.
- revision_note is null if no revision was needed.
- Return ONLY the JSON object.
```

**What changed from current LEG:**
- Removed: `plan_steps[]`, `revision_history[]`, `verification[]`, `invariants_checked[]`, `issues_found[]`, `changes_made[]`, `changed_functions[]`, `code_before`, `code_after`, `internal_revisions`
- Added: `self_check` (the model's own verification, in prose), `revision_note` (what changed if self-check failed)
- Same 4 reasoning fields as baseline + 2 LEG-specific fields
- Total schema overhead: ~15 lines vs ~70 lines. Same reasoning depth, 80% less noise.

### D. Classifier Prompt Changes

Replace `classify_reasoning.j2` with a multi-dimensional evaluation:

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

{% if revision_note %}
## Revision Note
{{ revision_note }}
{% endif %}

# Task Description
{{ task }}

# Code Produced
```python
{{ code }}
```

# Evaluate Each Dimension

1. mechanism_identified: Did the reasoning correctly identify the actual failure mechanism?
   YES = correct mechanism identified and explained
   PARTIAL = partially correct or vague
   NO = wrong mechanism or missing

2. invariant_identified: Did the reasoning identify the correct broken contract/invariant?
   YES = correct invariant stated
   PARTIAL = related but imprecise
   NO = wrong or missing

3. fix_alignment: Does the stated fix strategy logically address the identified mechanism?
   YES = fix directly addresses the mechanism
   PARTIAL = fix is related but incomplete
   NO = fix does not address the mechanism

4. reasoning_code_alignment: Does the generated code match the stated reasoning?
   YES = code implements what reasoning describes
   PARTIAL = partially matches
   NO = code contradicts or ignores reasoning

# Failure Type
Choose EXACTLY one: {{ failure_types }}

# Output
Return EXACTLY one line:
<mechanism_identified>;<invariant_identified>;<fix_alignment>;<reasoning_code_alignment>;<failure_type>

Values: YES, PARTIAL, or NO for each dimension.

Example:
YES;YES;YES;YES;HIDDEN_DEPENDENCY
PARTIAL;NO;YES;PARTIAL;INVARIANT_VIOLATION

Return ONLY this one line.
```

**What changed:**
- Input: 4 structured reasoning fields instead of one flat string
- Output: 4 dimensions + failure type instead of one boolean + failure type
- Derived `reasoning_correct`: computed transparently from the 4 dimensions

### E. Derived `reasoning_correct`

```python
def compute_reasoning_correct(mechanism, invariant, fix_align, code_align):
    """Derive reasoning_correct from 4 classifier dimensions."""
    if mechanism == "YES" and invariant in ("YES", "PARTIAL"):
        return True
    if mechanism == "PARTIAL" and invariant == "YES" and fix_align == "YES":
        return True
    return False
```

This is explicit, auditable, and documented. No more opaque single-boolean judgment.

### F. Classifier Grounding

Two modes, selected by config:

**Blind mode (default for experiments):** Classifier receives only the model's reasoning + task + code. No ground truth. This preserves experimental validity — the classifier must judge reasoning on its own.

**Grounded mode (for evaluation audit):** Classifier additionally receives:
- `case.failure_mode` (e.g., "HIDDEN_DEPENDENCY")
- `case.trap` (the specific trap the case tests)

This enables checking whether the classifier agrees with ground truth, without contaminating experimental results.

Config field:
```yaml
evaluation:
  classifier_mode: "blind"  # or "grounded"
```

### G. Parser Changes

The parser must extract the 4 reasoning fields from JSON responses. For baseline (V1/V2):

```python
# In parse.py, for JSON responses:
reasoning_obj = {
    "root_cause": parsed.get("root_cause", ""),
    "failure_mechanism": parsed.get("failure_mechanism", ""),
    "broken_invariant": parsed.get("broken_invariant", ""),
    "fix_strategy": parsed.get("fix_strategy", ""),
}
result["reasoning_obj"] = reasoning_obj
# Flatten for backward compat:
result["reasoning"] = f"{reasoning_obj['root_cause']} {reasoning_obj['failure_mechanism']}"
```

For LEG:
```python
reasoning_obj = {
    "root_cause": parsed.get("root_cause", ""),
    "failure_mechanism": parsed.get("failure_mechanism", ""),
    "broken_invariant": parsed.get("broken_invariant", ""),
    "fix_strategy": parsed.get("fix_strategy", ""),
    "self_check": parsed.get("self_check", ""),
    "revision_note": parsed.get("revision_note"),
}
result["reasoning_obj"] = reasoning_obj
```

### H. Logging Changes

`run.jsonl` stores the full structured reasoning object:

```json
{
  "parsed": {
    "reasoning_obj": {
      "root_cause": "...",
      "failure_mechanism": "...",
      "broken_invariant": "...",
      "fix_strategy": "..."
    },
    "reasoning": "... (flattened for backward compat)"
  },
  "audit": {
    "classifier_input_reasoning": { ... },
    "classifier_dimensions": {
      "mechanism_identified": "YES",
      "invariant_identified": "YES",
      "fix_alignment": "YES",
      "reasoning_code_alignment": "PARTIAL"
    },
    "classifier_verdict": true,
    "classifier_failure_type": "HIDDEN_DEPENDENCY"
  }
}
```

`events.jsonl` stores the derived boolean + dimensions:

```json
{
  "reasoning_correct": true,
  "classifier_mechanism": "YES",
  "classifier_invariant": "YES",
  "classifier_fix_align": "YES",
  "classifier_code_align": "PARTIAL",
  "failure_type": "HIDDEN_DEPENDENCY"
}
```

### I. Metrics Changes

- `reasoning_correct` is now computed from 4 dimensions via `compute_reasoning_correct()`
- LEG rate = cases where `mechanism_identified == "YES"` but `code_correct == false`
- New metric: `mechanism_identification_rate` = fraction where `mechanism_identified == "YES"`
- New metric: `invariant_identification_rate`
- New metric: `reasoning_code_alignment_rate`
- Existing `category` (true_success, leg, lucky_fix, true_failure) still computed from `reasoning_correct` + `code_correct`

---

## 3. IMPLEMENTATION PHASES

### Phase R1: Update templates (no parser/evaluator changes yet)

1. Create new `output_instruction_v2.j2` with 4 reasoning fields
2. Create new `output_instruction_v1.j2` with 4 reasoning fields
3. Create new `leg_reduction.j2` with compact schema
4. Create new `classify_reasoning.j2` with 4-dimension evaluation
5. Update `registry.yaml` if needed

### Phase R2: Update parser

1. Extract `reasoning_obj` dict from JSON responses
2. Flatten to `reasoning` string for backward compat
3. Handle LEG `self_check` and `revision_note`
4. Update `_leg_to_parse_format` conversion

### Phase R3: Update classifier pipeline

1. Update `llm_classify()` to pass 4 reasoning fields as separate variables
2. Update `parse_classify_output()` to parse 4-dimension response
3. Implement `compute_reasoning_correct()` derivation
4. Add `classifier_mode` config support (blind/grounded)

### Phase R4: Update logging + metrics

1. Store `reasoning_obj` in run.jsonl
2. Store classifier dimensions in audit block
3. Add new dimension fields to events.jsonl
4. Update `compute_category()` if needed

### Phase R5: Tests

1. Prompt/parser alignment: generation prompts request 4 reasoning fields, parser extracts them
2. Classifier alignment: classifier receives full reasoning object, returns 4 dimensions
3. Logging integrity: reasoning_obj survives generation → parse → classify → log
4. Metric integrity: `reasoning_correct` computed from structured dimensions
5. Reconstruction: from logs alone, reconstruct exactly what classifier saw

---

## 4. BACKWARD COMPATIBILITY

Old runs with `"reasoning": "free text"` format will:
- Parse with `reasoning_obj = None` (field not present in old responses)
- Fall back to `reasoning` string for classifier input
- Log `reasoning_obj: null` in run.jsonl
- Continue to work with existing metrics (single boolean `reasoning_correct`)

New runs will have both `reasoning_obj` (structured) and `reasoning` (flattened) for transition.

---

## 5. WHAT THIS DOES NOT CHANGE

- Execution tests (code correctness from running code — unchanged)
- Reconstruction (file-dict → code assembly — unchanged)
- Case structure (cases_v2.json — unchanged)
- Config structure (conditions, models — unchanged except new `classifier_mode` field)
- Call logging (provenance — unchanged, reasoning_obj added to variables)

---

*End of plan. Awaiting approval before implementation.*
