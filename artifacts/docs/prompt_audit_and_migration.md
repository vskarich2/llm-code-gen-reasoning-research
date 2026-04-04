# Prompt Audit & Migration Analysis

---

## 1. CURRENT STATE AUDIT

### 1.1 Code Generation Prompt (baseline_v2)

**Location:** `core/prompts/components/task_and_code.j2` + `core/prompts/components/output_instruction_v3.j2`
**Loaded by:** `core/pipeline/orchestration/execution_v2.py` via `_get_compiler_registry()` → manifest lookup
**Condition name:** `baseline_v2` → components `["task_and_code", "output_instruction_v3"]`

**Actual Content:**
- `task_and_code.j2`: Bare `{{ task }}` + `{{ code_files_block }}` — no framing
- `output_instruction_v3.j2`: Instructs JSON output with `root_cause`, `fix_strategy`, `files`

**Output Schema (as implemented):**
```json
{
  "root_cause": "...",
  "fix_strategy": "...",
  "files": { "path": "contents or UNCHANGED" }
}
```

**Parsing:** `parser_v2.py` extracts `full_json` and `files_dict`. Tolerant of surrounding text. Recovery parser handles fence stripping, escape fixing, triple-quote repair.

**Observed Issues:**
- **No `code_commitments` field** in baseline_v2 output schema. Only LEG variants ask for commitments.
- **No explicit instruction to avoid markdown** — says "No markdown inside file values" but doesn't say "no markdown wrapping"
- **No instruction to avoid explanations** — model can prepend/append text around JSON
- **Schema line is constructed in Python** (`execution_v2.py:97-108`), not in the template — fragile coupling
- **"UNCHANGED" sentinel** is a string convention, not enforced at parse level

### 1.2 Blind/Line Classifier (classify_reasoning_v2)

**Location:** `core/prompts/components/classify_reasoning_v2.j2`
**Loaded by:** `execution_v2.py:227` via `_compile_prompt((config.evaluation.classifier_template,), classifier_vars)`
**Parser:** `core/evaluation/evaluator_v2.py:parse_classifier_v2_output()`

**Output Schema (as implemented):**
```
Line 1: MECHANISM;COMMITMENTS_EXTRACTED;COMMITMENTS_SATISFIED;ALIGNMENT;FAILURE_TYPE
Line 2: HIGH | MEDIUM | LOW
Line 3: Counterfactual: <sentence>
Line 4: Evidence: <bullets>
Line 5: Judgment: <sentences>
```

Dimensions use `CORRECT | PARTIAL | WRONG` (3-way, not 2-way as target spec requires).

**Observed Issues:**
- **Uses 3-way scale (CORRECT/PARTIAL/WRONG)** — target spec requires 2-way (CORRECT/INCORRECT)
- **Allows PARTIAL** — creates ambiguity in downstream LEG computation (`commitments_valid = ce in ("CORRECT", "PARTIAL")`)
- **Requires free-text sections** (Counterfactual, Evidence, Judgment) — these are not strictly necessary and add parsing fragility
- **Canonical commitment patterns hardcoded** for only 10/30 bug families — 20 families have no reference, causing inflated CORRECT scores
- **In grounded mode, sees ground truth** — "for calibration only" but the evaluator LLM may use it as the answer
- **Evaluates reasoning→code consistency, NOT reasoning correctness** — the prompt explicitly says "NOT: Is the reasoning correct?" This means `mechanism_identified = CORRECT` can fire when the model identifies the wrong bug but states it consistently
- **5 semicolons on line 1** — fragile; any formatting deviation causes parse failure

### 1.3 Oracle Classifier

**Location:** `core/evaluation/oracle_eval/reasoning_truth_prompt.j2`
**Loaded by:** `evaluators/reasoning_truth.py:render_prompt()` (standalone, not in v2 pipeline)
**Parser:** `evaluators/reasoning_truth.py:parse_response()` — expects 2 lines

**Output Schema (as implemented):**
```
Line 1: CORRECT | PARTIAL | WRONG | UNJUDGABLE
Line 2: <one-sentence justification>
```

**Observed Issues:**
- **Does NOT use execution results** — contrary to the target spec which says oracle "uses execution results". The oracle currently evaluates reasoning ONLY against ground truth mechanism. It never sees code, execution, or test output.
- **Different output schema from blind classifier** — 4 possible labels (includes UNJUDGABLE) vs classifier's 3×4 dimension matrix. Target spec wants them to share the same schema.
- **Not integrated into v2 pipeline** — runs as post-hoc batch script only
- **Prompt is NOT persisted** — only `prompt_hash` and `response_raw` are saved

### 1.4 Retry Critique (one-sentence)

**Location:** `core/prompts/components/critique_mismatch_v2.j2`
**Loaded by:** `retry_v2.py:_generate_critique()` → `_compile_prompt(("critique_mismatch_v2",), vars)` for strict variant; other variants use `critique_strict.j2`, `critique_moderate.j2`, `critique_aggressive.j2`
**Parser:** `retry_v2.py:_truncate_to_one_sentence()` — truncates multi-sentence responses

**Output Schema:** Free text, one sentence. `_truncate_to_one_sentence()` enforces by splitting on `. ` and taking the first sentence.

**Observed Issues:**
- **`critique_mismatch_v2.j2` is NOT used for strict variant** — the code maps `"strict" → "critique_strict"`, `"moderate" → "critique_moderate"`, etc. `critique_mismatch_v2.j2` is used only via direct compilation, not the variant system. This is confusing.
- **Multiple critique templates exist** (strict, moderate, aggressive, reasoning_only, mismatch_v2) — unclear which one produces best signal
- **Post-hoc truncation** via `_truncate_to_one_sentence()` means the model may produce multi-sentence output and lose important content when truncated
- **Prescriptive check** (`_check_prescriptive()`) flags critiques that suggest fixes — but this only logs, doesn't reject
- **"NO MISMATCH" sentinel** — if model outputs this, no critique is used. This is correct but the sentinel is case-sensitive and whitespace-sensitive

### 1.5 LEG Lean Prompt

**Location:** `core/prompts/components/leg_reduction_lean_v2.j2`
**Loaded by:** Manifest: `leg_reduction_lean_v2` → components `["leg_reduction_lean_v2"]`
**Parser:** Same as baseline — `parser_v2.py`

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

**Observed Issues:**
- **Embeds task + code inline** (via `{{ task }}` and `{{ code_files_block }}`) rather than using the `task_and_code.j2` component — duplicated rendering pattern
- **Asks for `risk_check`** — adds complexity without clear evidence it improves outcomes (analysis showed LEG lean ≈ baseline in aggregate)
- **"Quick check" framing** is informal — models may produce chatty risk_check text
- **No explicit "no markdown" or "no explanation" instruction** — relies on "ONLY JSON output" at the end

### 1.6 Reasoning-Only Retry Prompt

**Location:** `core/prompts/components/critique_reasoning_only.j2`
**Loaded by:** `retry_v2.py:_generate_critique()` when variant = `"reasoning_only"`
**Parser:** Same as other critique — `_truncate_to_one_sentence()`

**Output Schema:** Free text, one sentence.

**Observed Issues:**
- **Does NOT produce code** — this is a critique prompt, not a generation prompt. It outputs one sentence identifying a reasoning weakness. The actual retry generation is done by `critique_retry.j2` which feeds the critique back with the previous response.
- **Strict no-code rule** — "Do NOT mention code, functions, variables, files" — this prevents concrete actionable feedback
- **Output is `NO_WEAKNESS`** (different sentinel from `NO MISMATCH` used by mismatch critique) — inconsistent
- **Very abstract** — "identify the weakest claim" produces philosophical critiques rather than actionable error identification (confirmed by our async_race_lock analysis)

---

## 2. GAP ANALYSIS

### 2.1 Code Generation Prompt

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| No `code_commitments` in baseline | `root_cause`, `fix_strategy`, `files` only | `files` + `code_commitments` required | Commitments only available for LEG conditions; baseline LEG measurement relies on classifier extracting implicit commitments, which is unreliable |
| No "no explanations" instruction | Parser tolerates surrounding text | Must be JSON-only | Parser handles it, but extra text wastes tokens and occasionally confuses models |
| No "no markdown" instruction | Ambiguous | Explicit ban | Models sometimes wrap JSON in ` ```json ` fences, triggering recovery parser |
| Schema constructed in Python | Schema line built in execution_v2.py | Should be in template | Fragile; template and code can drift apart |

### 2.2 Blind Classifier

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| 3-way scale (CORRECT/PARTIAL/WRONG) | All 4 dimensions use 3-way | 2-way (CORRECT/INCORRECT) | `PARTIAL` creates ambiguity — `commitments_valid` counts PARTIAL as valid, inflating LEG-positive rate |
| Free-text sections required | Counterfactual/Evidence/Judgment mandatory | JSON output, no explanations | Parse failures from formatting issues inflate `classifier_failure_v2` category |
| Evaluates consistency not correctness | "NOT: Is the reasoning correct?" | Should evaluate whether mechanism is actually correct | `mechanism_identified = CORRECT` fires for consistently wrong reasoning — the core measurement gap identified in async_race_lock analysis |
| 10/30 families have canonical patterns | 20 families rely on LLM judgment alone | All families need patterns, or classifier needs different strategy | Inflated CORRECT scores for uncovered families |
| Semicolon-delimited text output | 5 fields on line 1 | JSON output | Any formatting deviation causes total parse failure |

### 2.3 Oracle Classifier

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Not integrated in pipeline | Post-hoc batch script only | Should be optional Stage 6b | Cannot correlate oracle verdict with per-attempt data in real time |
| No execution signal used | Reasoning-only evaluation | Target says "uses execution results" | Missing execution-conditioned oracle judgment |
| Different schema from blind classifier | 4-label (CORRECT/PARTIAL/WRONG/UNJUDGABLE) | Should match blind classifier schema | Cannot directly compare oracle vs classifier verdicts |
| Prompt not persisted | Only hash + response saved | Full prompt must be stored | Cannot audit oracle decisions |

### 2.4 Retry Critique

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Multiple competing templates | strict/moderate/aggressive/mismatch_v2 | Should be one canonical template | Unclear which template produces best signal; experiments mix templates |
| Post-hoc truncation | Model produces multi-sentence, truncated to 1 | Should enforce 1 sentence in prompt | Lost information from truncation |
| Inconsistent sentinel | `NO MISMATCH` vs `NO_MISMATCH` | Should be one canonical value | String comparison bugs possible |

### 2.5 LEG Lean

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Duplicates task+code rendering | Inlines `{{ task }}` + `{{ code_files_block }}` | Should compose with task_and_code.j2 | Template drift — if task_and_code changes, lean doesn't |
| risk_check adds noise | Optional field, often chatty | Target says "minimal and structured" | Extra tokens, no clear value add |

### 2.6 Reasoning-Only Retry

| Gap | Current | Target | Pipeline Risk |
|---|---|---|---|
| Not a generation prompt | Produces one critique sentence | Target says "Output must follow STRICT code generation format" | This is a critique prompt, not a retry-generation prompt. The actual retry generation is `critique_retry.j2`. The target spec may be conflating critique with generation. |
| Too abstract | "Do NOT mention code, functions, variables" | Should identify specific reasoning weakness | Produces vague philosophical critiques that don't help models fix concrete errors |

---

## 3. REQUIRED CHANGES

### 3.1 Code Generation Prompt

**Must Remove:**
- Nothing to remove — current prompt is minimal

**Must Add:**
- `code_commitments` field to baseline output schema
- Explicit "No markdown wrapping" instruction
- Explicit "No explanations outside JSON" instruction
- Schema should be in the template, not constructed in Python

**Must Tighten:**
- "Return ONLY the JSON object" needs stronger enforcement language

### 3.2 Blind Classifier

**Must Remove:**
- `PARTIAL` as a valid dimension value — collapse to CORRECT/INCORRECT
- Free-text sections (Counterfactual, Evidence, Judgment) — move to optional DEBUG section
- Canonical commitment patterns (or expand to cover all 30 families)

**Must Add:**
- Explicit instruction to evaluate mechanism CORRECTNESS, not just consistency
- JSON output format instead of semicolon-delimited text
- All 20 missing bug family canonical patterns

**Must Tighten:**
- Remove "NOT: Is the reasoning correct?" — this is the core measurement gap
- Make ground truth evaluation mandatory in grounded mode (not "for calibration only")

### 3.3 Oracle Classifier

**Must Remove:**
- Nothing

**Must Add:**
- Integration into v2 pipeline as Stage 6b (per oracle integration plan)
- Prompt persistence
- Optionally: execution result signal (but this changes the oracle's purpose)

**Must Tighten:**
- Consider aligning output schema with classifier (4-dim JSON vs 2-line text)

### 3.4 Retry Critique

**Must Remove:**
- Multiple competing templates — consolidate to one
- Post-hoc truncation — enforce in prompt

**Must Add:**
- Stronger one-sentence enforcement
- Consistent sentinel value

**Must Tighten:**
- Prohibit generic statements more explicitly

### 3.5 LEG Lean

**Must Remove:**
- Inline task/code rendering — compose with task_and_code.j2 instead
- risk_check field (or make it a single word: SAFE/RISKY)

**Must Tighten:**
- More explicit JSON-only instruction

### 3.6 Reasoning-Only Retry

**Must Remove:**
- "Do NOT mention code" restriction — this prevents useful feedback

**Must Add:**
- Allow referencing code constructs (functions, variables)
- Still prohibit suggesting specific fixes

**Must Tighten:**
- Clearer distinction between "reasoning weakness" and "code suggestion"

---

## 4. FINAL REWRITTEN PROMPTS

### 4.1 Code Generation Prompt (baseline_v2)

```
{{ task }}

{{ code_files_block }}

Fix the bug. Return your response as a SINGLE valid JSON object. No other text.

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

RULES:
- "root_cause": must name a specific function/variable and the causal mechanism, not just symptoms
- "fix_strategy": must describe a concrete code change at a specific location
- "code_commitments": 1-3 testable statements in "<scope> must <action>" form
- "files": must include EVERY file. Use "UNCHANGED" for unmodified files. Full contents for modified files.
- No markdown. No explanations. No extra text. ONLY the JSON object.
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
## Ground Truth
Bug type: {{ ground_truth_failure_mode }}
Bug location: {{ ground_truth_trap }}
{% if ground_truth_invariant %}
Invariant: {{ ground_truth_invariant }}
{% endif %}
{% endif %}

Evaluate FOUR dimensions. For each, answer CORRECT or INCORRECT.

1. mechanism_identified: Did the reasoning identify the ACTUAL bug mechanism (not just symptoms)?
2. commitments_extracted: Are there specific, testable commitments implied by the reasoning?
3. commitments_satisfied: Does the code implement those commitments?
4. reasoning_code_alignment: Does the code match the stated fix strategy?

If uncertain on any dimension, answer INCORRECT.

Return ONLY this JSON:

{"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"}
```

### 4.3 Oracle Classifier Prompt

Keep current oracle prompt (`reasoning_truth_prompt.j2`) as-is — it is well-designed for its purpose. The target spec's requirement that oracle "uses execution results" conflicts with the oracle's design principle of evaluating reasoning in isolation. The current design is correct for measuring whether the model identified the true bug mechanism.

Changes needed:
- Integrate into pipeline (Stage 6b per plan)
- Persist full prompt in event dict

### 4.4 Retry Critique Prompt (one-sentence)

```
You are comparing a developer's stated reasoning to their code.

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}

Code:
{{ code }}

Task: {{ task }}

Write EXACTLY one sentence describing the specific mismatch between the stated fix strategy and what the code actually does. Name the function or variable that diverges.

If there is no mismatch, write: NO_MISMATCH

Rules:
- Exactly one sentence. No more.
- Be concrete: name the function, variable, or operation.
- Do NOT suggest a fix.
- Do NOT describe multiple issues.
```

### 4.5 LEG Lean Prompt

```
{{ task }}

{{ code_files_block }}

Fix the bug. Return a SINGLE valid JSON object. No other text.

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

### 4.6 Reasoning-Only Retry Critique Prompt

```
You are auditing a developer's reasoning about a software bug.

Root Cause: {{ root_cause }}
Fix Strategy: {{ fix_strategy }}

Write EXACTLY one sentence identifying the weakest or most unsupported claim in the reasoning. You may reference specific functions or variables mentioned in the reasoning, but do NOT suggest code changes or fixes.

If the reasoning is fully coherent, write: NO_WEAKNESS

Rules:
- Exactly one sentence.
- Focus on: vagueness, missing causal links, unsupported assumptions, or internal contradictions.
- Do NOT suggest fixes.
```

---

## 5. PARSING / VALIDATION IMPACT

### 5.1 Code Generation Parser (`parser_v2.py`)

**If `code_commitments` is added to baseline:**
- `parser_v2.py` does NOT validate individual field presence — it only checks that `full_json` parses and `files` dict exists
- No parser changes needed. The field will be extracted by `reasoning_v2.py:normalize_generation_v2()` which already handles optional fields
- **Safe to add without parser changes**

### 5.2 Classifier Parser (`evaluator_v2.py`)

**If switching from semicolon text to JSON output:**
- `parse_classifier_v2_output()` (lines 123-231) must be rewritten
- Current parser: splits on `\n`, then on `;`, validates dimension values against `{CORRECT, PARTIAL, WRONG}`
- New parser: `json.loads()` the response, validate keys + values against `{CORRECT, INCORRECT}`
- **Breaking change — parser must be updated simultaneously with prompt**
- `V2_VALID_DIMENSION_VALUES` in `contracts_v2.py` must change from `{CORRECT, PARTIAL, WRONG}` to `{CORRECT, INCORRECT}`
- `derive_v2_signals()` in `metrics_v2.py` must update: `commitments_valid = (ce == "CORRECT")` instead of `ce in ("CORRECT", "PARTIAL")`

### 5.3 Retry Logic (`retry_v2.py`)

- `_truncate_to_one_sentence()` can be kept as safety net but should rarely trigger with the improved prompt
- Sentinel value standardization: change all checks to `NO_MISMATCH` (underscore version)
- No structural changes needed

### 5.4 Downstream Metrics

- **LEG computation changes** if PARTIAL is removed: `reasoning_correct_compat` becomes `mechanism_correct AND commitments_valid AND alignment_positive` where each is strictly `== "CORRECT"` (no PARTIAL acceptance)
- All analysis scripts using `reasoning_correct` will produce different numbers — this is a deliberate recalibration, not a bug
- **Must re-run experiments after classifier change** to get consistent measurements

---

## 6. MIGRATION PLAN

### Step 1: Add `code_commitments` to baseline generation prompt
- Update `output_instruction_v3.j2` with `code_commitments` field
- Update `schema_line` construction in `execution_v2.py` to include commitments
- **Test:** Run 2 cases, verify `code_commitments` appears in parsed JSON
- **Invariant:** Existing fields (`root_cause`, `fix_strategy`, `files`) still parse correctly
- **Risk:** Models may produce empty commitments — handle as `[]` not error

### Step 2: Consolidate retry critique templates
- Merge `critique_strict.j2`, `critique_moderate.j2`, `critique_aggressive.j2` into one `critique_mismatch_v2.j2` with the rewritten prompt
- Standardize sentinel to `NO_MISMATCH`
- **Test:** Run retry condition, verify critique is exactly one sentence
- **Invariant:** Retry loop still functions; `_truncate_to_one_sentence()` rarely triggers

### Step 3: Update LEG lean prompt
- Replace `leg_reduction_lean_v2.j2` with rewritten version (removes risk_check)
- **Test:** Run lean condition, verify JSON output parses with `code_commitments`
- **Invariant:** Pass rate and LEG rate are comparable to pre-change (within noise)

### Step 4: Update reasoning-only critique
- Replace `critique_reasoning_only.j2` with rewritten version
- **Test:** Run reasoning-only retry, verify critique mentions specific reasoning elements
- **Invariant:** Critique is still one sentence; `NO_WEAKNESS` sentinel works

### Step 5: Update classifier prompt (HIGHEST RISK)
- Replace `classify_reasoning_v2.j2` with JSON-output version
- **Simultaneously update:**
  - `evaluator_v2.py:parse_classifier_v2_output()` — new JSON parser
  - `contracts_v2.py:V2_VALID_DIMENSION_VALUES` — `{CORRECT, INCORRECT}`
  - `metrics_v2.py:derive_v2_signals()` — remove PARTIAL handling
- **Test:** Run 10 cases across 3 conditions, compare old vs new classifier outputs
- **Invariant:** No `classifier_failure_v2` from parsing; all 4 dimensions populated
- **Detection:** If >20% of classifier responses fail JSON parsing, the prompt needs iteration

### Step 6: Integrate oracle into pipeline
- Follow oracle integration plan v1
- **Test:** Run with `evaluation.oracle.enabled: true`, verify oracle verdict + prompt in event dict
- **Invariant:** Oracle LLM call appears in `calls_flat/`; verdict matches post-hoc batch labels
