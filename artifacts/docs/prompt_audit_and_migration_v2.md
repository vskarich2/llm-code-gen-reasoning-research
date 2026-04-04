# Prompt Audit & Migration Analysis — v2

**Supersedes:** prompt_audit_and_migration.md
**Date:** 2026-04-03
**Changes since v1:** `output_instruction_v3.j2` updated to include `code_commitments` in baseline. `schema_line` in `execution_v2.py` updated to include commitments. `reasoning_v2.py` already handles commitment extraction.

---

## 1. CURRENT STATE AUDIT

### 1.1 Code Generation Prompt (baseline_v2)

**Location:** `core/prompts/components/task_and_code.j2` + `core/prompts/components/output_instruction_v3.j2`
**Loaded by:** `execution_v2.py` → manifest lookup → condition `baseline_v2` → components `["task_and_code", "output_instruction_v3"]`

**Actual Content:**
- `task_and_code.j2`: Bare `{{ task }}` + `{{ code_files_block }}` in section tags
- `output_instruction_v3.j2`: Instructs JSON output with `root_cause`, `fix_strategy`, `code_commitments`, `files`

**Output Schema (as implemented):**
```json
{
  "root_cause": "<...>",
  "fix_strategy": "<...>",
  "code_commitments": ["<scope> must <action>", ...],
  "files": { "path": "contents or UNCHANGED" }
}
```

**Schema line (Python-constructed in execution_v2.py:280-284):**
```
{"root_cause": "<...>", "fix_strategy": "<...>", "code_commitments": ["<scope> must <action>", ...], "files": {<file_keys>}}
```

**Parsing:** `parser_v2.py` extracts `full_json` and `files_dict`. Commitment extraction handled by `reasoning_v2.py:218-227` — detects `code_commitments` field, sets `commitments_source = "explicit"`.

**Issues (remaining after update):**
- Schema line is still constructed in Python (`execution_v2.py:280-284`), not in the template — template and code can drift
- No explicit "no markdown wrapping" instruction — only "No markdown inside file values"
- No explicit "no explanations" — only "Return ONLY the JSON object"
- `schema_line` is empty string for non-baseline conditions — those conditions use their own templates (LEG lean, LEG full) which have their own inline schemas
- **Retry `schema_line` does NOT include `code_commitments`** — `retry_v2.py:336-338` still uses old schema without commitments

### 1.2 Blind/Line Classifier (classify_reasoning_v2)

**Location:** `core/prompts/components/classify_reasoning_v2.j2` (316 lines)
**Loaded by:** `execution_v2.py:227` via `_compile_prompt((config.evaluation.classifier_template,), classifier_vars)`
**Parser:** `core/evaluation/evaluator_v2.py:parse_classifier_v2_output()`

**Output Schema:**
```
Line 1: MECHANISM;COMMITMENTS_EXTRACTED;COMMITMENTS_SATISFIED;ALIGNMENT;FAILURE_TYPE
Line 2: HIGH | MEDIUM | LOW
Line 3: Counterfactual: <sentence>
Line 4: Evidence: <bullets>
Line 5: Judgment: <sentences>
```

**Issues (unchanged from v1 audit):**
- 3-way scale (CORRECT/PARTIAL/WRONG) — target requires 2-way (CORRECT/INCORRECT)
- Evaluates consistency, not correctness — prompt says "NOT: Is the reasoning correct?"
- 10/30 bug families have canonical patterns — 20 uncovered
- Semicolon text output — fragile parsing
- Free-text sections (Counterfactual/Evidence/Judgment) add parsing risk
- Ground truth in grounded mode labeled "for calibration only" — evaluator LLM may ignore it

### 1.3 Oracle Classifier

**Location:** `core/evaluation/oracle_eval/reasoning_truth_prompt.j2`
**Loaded by:** `evaluators/reasoning_truth.py:render_prompt()` — standalone, NOT in v2 pipeline
**Parser:** `evaluators/reasoning_truth.py:parse_response()` — expects 2 lines

**Output Schema:**
```
Line 1: CORRECT | PARTIAL | WRONG | UNJUDGABLE
Line 2: <one-sentence justification>
```

**Issues (unchanged):**
- Not integrated into v2 pipeline
- Does not use execution results (contrary to target spec)
- Different schema from blind classifier
- Prompt not persisted

### 1.4 Retry Critique (one-sentence)

**Location:** Multiple templates used by different variants:
- `critique_mismatch_v2.j2` — used via direct compilation (not variant system)
- `critique_strict.j2` — mapped from `retry_leg_critique_strict_v2` condition
- `critique_moderate.j2` — mapped from `retry_leg_critique_moderate_v2` condition
- `critique_aggressive.j2` — mapped from `retry_leg_critique_aggressive_v2` condition

**Loaded by:** `retry_v2.py:_generate_critique()` → `_compile_prompt((comp_name,), crit_vars)`

**Key difference between variants:**
| Variant | Can name code entities? | Behavioral language? |
|---|---|---|
| strict | Only if already in root_cause/fix_strategy | Preferred |
| moderate | If needed for clarity | Allowed |
| aggressive | If supported by reasoning+code | Allowed |
| mismatch_v2 | Yes, freely | Yes |

**Output:** Free text, one sentence. `_truncate_to_one_sentence()` enforces post-hoc.
**Sentinel:** `NO MISMATCH` (with space) for mismatch variants, `NO_MISMATCH` (with underscore) for strict/moderate/aggressive.

**Issues:**
- Inconsistent sentinel: `NO MISMATCH` vs `NO_MISMATCH` across templates
- `critique_mismatch_v2.j2` is NOT used by the variant dispatch system — it's a separate template used for direct compilation. The actual experiment conditions use strict/moderate/aggressive.
- Post-hoc truncation loses information

### 1.5 LEG Lean Prompt

**Location:** `core/prompts/components/leg_reduction_lean_v2.j2`
**Loaded by:** Manifest: `leg_reduction_lean_v2` → components `["leg_reduction_lean_v2"]`

**Output Schema:**
```json
{
  "root_cause": "...",
  "code_commitments": ["..."],
  "fix_strategy": "...",
  "risk_check": "...",
  "files": { ... }
}
```

**Issues (unchanged):**
- Inlines `{{ task }}` + `{{ code_files_block }}` instead of composing with `task_and_code.j2`
- `risk_check` field adds noise without clear value
- "Quick check" framing is informal

### 1.6 Reasoning-Only Retry Critique

**Location:** `core/prompts/components/critique_reasoning_only.j2`
**Loaded by:** `retry_v2.py:_generate_critique()` when condition contains `reasoning_only`

**Output:** Free text, one sentence. Sentinel: `NO_WEAKNESS`.

**Issues (unchanged):**
- "Do NOT mention code, functions, variables" prevents concrete feedback
- Too abstract — produces philosophical critiques
- Different sentinel from mismatch variants

---

## 2. GAP ANALYSIS

### 2.1 Code Generation (baseline_v2)

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| ~~No code_commitments~~ | **FIXED** — now included in schema | Required | ~~Commitment-dependent metrics unreliable for baseline~~ Now resolved |
| Retry schema missing commitments | `retry_v2.py:336-338` schema has no `code_commitments` | Should match generation schema | Retry attempts produce responses without commitments — inconsistent with first attempt |
| Schema in Python not template | `schema_line` built in execution_v2.py | Should be in template | Template and code can drift; LEG conditions have inline schemas that may diverge |
| No explicit anti-markdown | "No markdown inside file values" only | "No markdown wrapping" | Models sometimes wrap JSON in fences → triggers recovery parser |

### 2.2 Blind Classifier

| Gap | Current | Target | Pipeline Risk | Severity |
|---|---|---|---|---|
| 3-way → 2-way | CORRECT/PARTIAL/WRONG | CORRECT/INCORRECT | PARTIAL inflates `commitments_valid` and `reasoning_correct_compat` | **HIGH** — directly affects LEG measurement |
| Consistency not correctness | "NOT: Is the reasoning correct?" | Must evaluate actual correctness | `mechanism_identified = CORRECT` fires for consistently wrong reasoning | **CRITICAL** — the async_race_lock finding |
| 20 families uncovered | 10/30 have canonical patterns | All families or different strategy | Inflated CORRECT for uncovered families | **HIGH** |
| Text output format | Semicolons + free text | JSON | Parse failures inflate `classifier_failure_v2` | **MEDIUM** |

### 2.3 Oracle Classifier

| Gap | Current | Target | Status |
|---|---|---|---|
| Not in pipeline | Post-hoc only | Stage 6b | Plan exists (oracle_eval_integration_plan_v1) |
| No execution signal | Reasoning-only | Target says use execution | **Intentional design** — oracle evaluates mechanism identification, not execution. Current is correct. |
| Schema mismatch | 4-label text | 4-dim JSON (like classifier) | Alignment would help but changes oracle's purpose |

### 2.4 Retry Critique

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Multiple templates | 4 variants + mismatch_v2 | One canonical | Unclear which produces best signal |
| Inconsistent sentinels | `NO MISMATCH` / `NO_MISMATCH` | Single value | String comparison edge cases |
| Post-hoc truncation | Truncates multi-sentence | Enforce in prompt | Lost critique content |
| mismatch_v2 not in variant dispatch | Separate from strict/moderate/aggressive | Should be one system | Confusing; experiments may use wrong template |

### 2.5 LEG Lean

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Inline task+code | Duplicates rendering | Compose with task_and_code.j2 | Template drift |
| risk_check noise | Extra field | Minimal structure | Wasted tokens, chatty output |

### 2.6 Reasoning-Only Retry

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| No code references allowed | "Do NOT mention code" | Allow referencing code constructs | Critiques too abstract to be actionable |
| Different sentinel | `NO_WEAKNESS` | Standardize | Inconsistent with mismatch sentinel |

---

## 3. REQUIRED CHANGES

### 3.1 Code Generation (baseline_v2) — MOSTLY DONE

**Already done:**
- `code_commitments` added to `output_instruction_v3.j2`
- `schema_line` updated in `execution_v2.py`
- `reasoning_v2.py` already extracts commitments

**Still needed:**
- Update `retry_v2.py:336-338` schema_line to include `code_commitments`
- Add explicit "Do not wrap in markdown fences" to `output_instruction_v3.j2`

### 3.2 Blind Classifier — BREAKING CHANGE

**Must change (all simultaneously):**
1. Prompt: 3-way → 2-way (CORRECT/INCORRECT)
2. Prompt: Remove "NOT: Is the reasoning correct?" — replace with instruction to evaluate actual mechanism correctness
3. Prompt: Switch output from semicolons to JSON
4. Add canonical patterns for remaining 20 bug families
5. Parser `evaluator_v2.py`: rewrite for JSON input
6. `contracts_v2.py`: update `V2_VALID_DIMENSION_VALUES`
7. `metrics_v2.py`: remove PARTIAL handling

### 3.3 Oracle Classifier — ADDITIVE

- Integrate into pipeline (Stage 6b)
- Persist prompt in event dict
- No prompt changes needed

### 3.4 Retry Critique — CONSOLIDATION

1. Standardize sentinel to `NO_MISMATCH` across all templates
2. Consolidate strict/moderate/aggressive into one template with a `{{ specificity }}` variable
3. Retire `critique_mismatch_v2.j2` or make it the canonical template

### 3.5 LEG Lean — MINOR

1. Remove `risk_check` (or make one-word: SAFE/RISKY)
2. Compose with `task_and_code.j2` instead of inlining

### 3.6 Reasoning-Only Retry — MINOR

1. Remove "Do NOT mention code, functions, variables" restriction
2. Keep "Do NOT suggest fixes"
3. Standardize sentinel to `NO_MISMATCH`

---

## 4. FINAL REWRITTEN PROMPTS

### 4.1 Code Generation Prompt (baseline_v2)

Current `output_instruction_v3.j2` is **already correct** after the update. Only addition:

Add after "Return ONLY the JSON object":
```
Do not wrap in markdown code fences.
```

### 4.2 Blind Classifier Prompt

```
You are evaluating a developer's reasoning about a bug.

## Developer Reasoning

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}
{% if code_commitments %}
Code Commitments: {{ code_commitments }}
{% endif %}

## Task
{{ task }}

## Code Produced
{{ code }}

{% if classifier_mode == "grounded" %}
## Ground Truth (use this to verify the developer's mechanism identification)
Bug type: {{ ground_truth_failure_mode }}
Bug location: {{ ground_truth_trap }}
{% if ground_truth_invariant %}
Invariant: {{ ground_truth_invariant }}
{% endif %}
{% endif %}

## Instructions

Evaluate FOUR dimensions. For each, answer CORRECT or INCORRECT only.

1. mechanism_identified
   Did the reasoning identify the ACTUAL root cause of the bug?
   CORRECT = names the right function/variable and the right causal mechanism.
   INCORRECT = wrong mechanism, wrong location, describes only symptoms, or too vague.
   {% if classifier_mode == "grounded" %}Use the ground truth to verify.{% endif %}

2. commitments_extracted
   Does the reasoning contain specific, testable fix obligations?
   CORRECT = at least one commitment in "<scope> must <action>" form (explicit or implied).
   INCORRECT = no commitments, or only vague statements.

3. commitments_satisfied
   Does the code implement the commitments?
   CORRECT = all stated commitments are implemented in code.
   INCORRECT = any commitment is missing, contradicted, or only partially implemented.

4. reasoning_code_alignment
   Does the code match the stated fix strategy?
   CORRECT = code changes match what the reasoning describes.
   INCORRECT = code does something different from stated reasoning.

Return ONLY this JSON. No other text.

{"mechanism_identified": "...", "commitments_extracted": "...", "commitments_satisfied": "...", "reasoning_code_alignment": "..."}
```

### 4.3 Oracle Classifier Prompt

**No changes.** Current oracle prompt is well-designed. It correctly evaluates reasoning against ground truth mechanism without seeing code or execution results. This is the right design — changing it to include execution results would conflate two independent signals.

Needed: pipeline integration (Stage 6b) and prompt persistence.

### 4.4 Retry Critique Prompt (consolidated)

```
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
```

This replaces: `critique_mismatch_v2.j2`, `critique_strict.j2`, `critique_moderate.j2`, `critique_aggressive.j2`.

### 4.5 LEG Lean Prompt

```
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
```

Changes from current: removed `risk_check`.

### 4.6 Reasoning-Only Retry Critique Prompt

```
You are auditing a developer's reasoning about a software bug.

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}

Write EXACTLY one sentence identifying the weakest or most unsupported claim in the reasoning. You may reference functions or variables the developer mentions, but do NOT suggest code changes.

If the reasoning is fully coherent, write exactly: NO_MISMATCH

Rules:
- Exactly one sentence.
- Focus on: vagueness, missing causal links, unsupported assumptions, or internal contradictions.
- Do NOT suggest fixes or code changes.
```

Changes from current: allows referencing code constructs mentioned in reasoning; standardized sentinel to `NO_MISMATCH`.

---

## 5. PARSING / VALIDATION IMPACT

### 5.1 Code Generation Parser (`parser_v2.py`)

- **No changes needed.** Parser extracts `full_json` and `files_dict` without validating individual fields. `code_commitments` flows through to `reasoning_v2.py` which already handles it.
- Adding "no markdown fences" to prompt reduces recovery parser invocations but doesn't require parser changes.

### 5.2 Classifier Parser (`evaluator_v2.py`) — BREAKING

If switching to JSON output:
- **Rewrite `parse_classifier_v2_output()`** — current: splits lines + semicolons. New: `json.loads()` + key validation.
- **Update `ClassifierResultV2` dataclass** — remove `counterfactual`, `evidence`, `judgment`, `confidence` fields (or make optional).
- **Update `V2_VALID_DIMENSION_VALUES`** in `contracts_v2.py` — from `{"CORRECT", "PARTIAL", "WRONG"}` to `{"CORRECT", "INCORRECT"}`.
- **Update `derive_v2_signals()`** in `metrics_v2.py`:
  - `mechanism_correct = (m == "CORRECT")` — unchanged
  - `commitments_valid = (ce == "CORRECT")` — was `ce in ("CORRECT", "PARTIAL")`
  - `alignment_positive = (rca == "CORRECT")` — unchanged
  - Remove PARTIAL handling in `compute_reasoning_correct()` in `reasoning.py`

### 5.3 Retry Logic (`retry_v2.py`)

- **Update retry `schema_line`** to include `code_commitments`
- **Standardize sentinel** checks to `NO_MISMATCH` (currently mixed)
- `_truncate_to_one_sentence()` kept as safety net

### 5.4 Downstream Analysis

- **All LEG rates will change** when PARTIAL is removed from classifier. This is a deliberate recalibration.
- `analysis/load_logs.py` reads `reasoning_correct` from events — no code change needed, but new experiments will produce different values.
- Dashboard `metrics_registry.py` — no changes, reads whatever the events contain.
- **Must re-run experiments after classifier prompt change** to get consistent data.

### 5.5 Failure Type Removal

The current classifier requires `failure_type` on line 1. The rewritten prompt removes it (not in the JSON schema). This means:
- `classifier_result.failure_type` will be empty/None
- `mechanism_label` in events will be None
- Dashboard and analysis that group by `mechanism_label` will lose this signal
- **Decision needed:** Keep failure_type in JSON output, or drop it and rely on case metadata's `failure_mode` field instead.

**Recommendation:** Add `failure_type` to the JSON output to preserve this signal:
```json
{"mechanism_identified": "...", "commitments_extracted": "...", "commitments_satisfied": "...", "reasoning_code_alignment": "...", "failure_type": "..."}
```

---

## 6. MIGRATION PLAN

### Step 1: Retry schema_line fix (LOW RISK)
- Update `retry_v2.py:336-338` to include `code_commitments` in schema
- **Test:** Run retry condition, verify model outputs `code_commitments` in response
- **Invariant:** Retry loop still functions

### Step 2: Add "no markdown fences" to generation prompt (LOW RISK)
- Add line to `output_instruction_v3.j2`
- **Test:** Run baseline, verify no ` ```json ` wrapping in responses
- **Invariant:** Parse success rate stays same or improves

### Step 3: Consolidate critique templates (MEDIUM RISK)
- Replace 4 critique templates with one canonical template
- Standardize sentinel to `NO_MISMATCH` everywhere
- Update `retry_v2.py:_resolve_critique_variant()` to always use canonical
- **Test:** Run retry_strict and retry_reasoning_only, verify one-sentence critiques
- **Invariant:** Retry recovery rate comparable to pre-change

### Step 4: Update LEG lean prompt (MEDIUM RISK)
- Replace `leg_reduction_lean_v2.j2` with rewritten version (no risk_check)
- **Test:** Run lean condition, verify JSON output parses with `code_commitments`, no `risk_check`
- **Invariant:** Pass rate comparable (within noise)
- **Note:** Old logs have `risk_check`; new logs won't. Analysis scripts handle missing fields.

### Step 5: Update reasoning-only critique (LOW RISK)
- Replace `critique_reasoning_only.j2` with rewritten version
- **Test:** Run reasoning-only retry, verify critiques reference specific reasoning elements
- **Invariant:** Critique is one sentence; sentinel works

### Step 6: Update classifier prompt + parser (HIGHEST RISK — all-or-nothing)
- Replace `classify_reasoning_v2.j2` with JSON-output version
- Simultaneously update:
  - `evaluator_v2.py:parse_classifier_v2_output()` — JSON parser
  - `contracts_v2.py:V2_VALID_DIMENSION_VALUES` — `{"CORRECT", "INCORRECT"}`
  - `metrics_v2.py:derive_v2_signals()` — remove PARTIAL
  - `reasoning.py:compute_reasoning_correct()` — remove PARTIAL promotion
- **Test:** Run 10 cases × 3 conditions, verify:
  - 0% classifier parse failures
  - All 4 dimensions populated as CORRECT/INCORRECT
  - LEG/lucky_fix categories compute without errors
- **Invariant:** No `classifier_failure_v2` from parsing
- **Detection:** If >10% parse failures, prompt needs iteration on models that struggle with JSON-only output

### Step 7: Oracle integration (ADDITIVE — safe)
- Per oracle_eval_integration_plan_v1
- **Test:** `evaluation.oracle.enabled: true`, verify oracle prompt + response in events
- **Invariant:** Pipeline behavior unchanged when oracle disabled
