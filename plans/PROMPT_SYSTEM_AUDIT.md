# Full-System Prompting Audit Report

**Date:** 2026-03-27
**Status:** AUDIT ONLY — no implementation

---

## 1. PROMPT INVENTORY (EXHAUSTIVE)

### 1.1 Agent Generation Prompts

| ID | File | Function/Constant | Role | Purpose | Input Variables | Output Contract |
|----|------|-------------------|------|---------|-----------------|-----------------|
| P01 | `prompts.py:199` | `build_base_prompt()` | Agent | Minimal baseline: task + code files | `task`, `code_files` | JSON V1 or V2 (appended by call_model) |
| P02 | `prompts.py:11-95` | `build_diagnostic_prompt()` | Agent | Case-specific diagnostic nudge (4 failure modes) | `task`, `code_files`, `failure_mode` | JSON V1/V2 |
| P03 | `prompts.py:99-196` | `build_guardrail_prompt()` | Agent | Case-specific constraint enforcement (4 failure modes) | `task`, `code_files`, `failure_mode` | JSON V1/V2 |
| P04 | `nudges/core.py:14-38` | `_dependency_check_diagnostic()` | Agent | Generic dependency audit nudge | `base` prompt | JSON V1/V2 |
| P05 | `nudges/core.py:41-65` | `_invariant_guard_diagnostic()` | Agent | Generic invariant reasoning nudge | `base` prompt | JSON V1/V2 |
| P06 | `nudges/core.py:68-93` | `_temporal_robustness_diagnostic()` | Agent | Generic temporal data flow nudge | `base` prompt | JSON V1/V2 |
| P07 | `nudges/core.py:96-122` | `_state_lifecycle_diagnostic()` | Agent | Generic state lifecycle nudge | `base` prompt | JSON V1/V2 |
| P08 | `nudges/core.py:129-157` | `_dependency_check_guardrail()` | Agent | Generic dependency constraint enforcement | `base` prompt | JSON V1/V2 |
| P09 | `nudges/core.py:160-190` | `_invariant_guard_guardrail()` | Agent | Generic invariant constraint enforcement | `base` prompt | JSON V1/V2 |
| P10 | `nudges/core.py:193-223` | `_temporal_robustness_guardrail()` | Agent | Generic temporal constraint enforcement | `base` prompt | JSON V1/V2 |
| P11 | `nudges/core.py:226-256` | `_state_lifecycle_guardrail()` | Agent | Generic state constraint enforcement | `base` prompt | JSON V1/V2 |
| P12 | `nudges/core.py:263-278` | `build_strict_guardrail()` | Agent | Hard constraints from case metadata | `base`, `hard_constraints` list | JSON V1/V2 |
| P13 | `nudges/core.py:285-314` | `_counterfactual_generic()` | Agent | Counterfactual state transition check | `base` prompt | JSON V1/V2 |
| P14 | `nudges/core.py:321-351` | `_reason_then_act_generic()` | Agent | Two-step: forced reasoning before code | `base` prompt | JSON V1/V2 |
| P15 | `nudges/core.py:358-388` | `_self_check_generic()` | Agent | Post-solution verification step | `base` prompt | JSON V1/V2 |
| P16 | `nudges/core.py:395-421` | `_counterfactual_check_generic()` | Agent | Counterfactual failure analysis before submit | `base` prompt | JSON V1/V2 |
| P17 | `nudges/core.py:428-454` | `_test_driven_generic()` | Agent | Behavioral requirements check | `base` prompt | JSON V1/V2 |
| P18 | `reasoning_prompts.py:10-20` | `build_structured_reasoning()` | Agent | Step-by-step reasoning scaffold | `base` prompt | JSON V1/V2 |
| P19 | `reasoning_prompts.py:23-28` | `build_free_form_reasoning()` | Agent | No structure, just "think carefully" | `base` prompt | JSON V1/V2 |
| P20 | `reasoning_prompts.py:31-52` | `build_branching_reasoning()` | Agent | Tree-of-thought: two approaches, pick one | `base` prompt | JSON V1/V2 |
| P21 | `scm_prompts.py:9-30` | `build_scm_descriptive()` | Agent | SCM edges presented informationally | `base`, `case_id` (fetches SCM) | JSON V1/V2 |
| P22 | `scm_prompts.py:33-63` | `build_scm_constrained()` | Agent | SCM + forced 4-step verification | `base`, `case_id` | JSON V1/V2 |
| P23 | `scm_prompts.py:66-130` | `build_scm_constrained_evidence()` | Agent | SCM + full F*/V*/E*/I*/C* evidence catalog | `base`, `case_id` | JSON V1/V2 |
| P24 | `scm_prompts.py:133-164` | `build_scm_constrained_evidence_minimal()` | Agent | SCM + critical evidence subset only | `base`, `case_id` | JSON V1/V2 |
| P25 | `scm_prompts.py:167-195` | `build_evidence_only()` | Agent | F*/V*/C*/I* catalogs but NO edges (forces inference) | `base`, `case_id` | JSON V1/V2 |
| P26 | `scm_prompts.py:198-200` | `build_length_matched_control()` | Agent | Token-count-matched filler (ablation control) | `base`, `case_id` | JSON V1/V2 |

### 1.2 Multi-Step Agent Prompts

| ID | File | Function/Constant | Role | Purpose | Input Variables | Output Contract |
|----|------|-------------------|------|---------|-----------------|-----------------|
| P27 | `contract.py:154-168` | `build_contract_prompt()` | Agent | Elicit execution contract (CGE step 1) | `task`, `code_files`, `CONTRACT_SCHEMA_TEXT` | Raw JSON (raw=True) |
| P28 | `contract.py:171-192` | `build_code_from_contract_prompt()` | Agent | Generate code from contract (CGE step 2) | `task`, `code_files`, `contract` dict | JSON V1/V2 |
| P29 | `contract.py:195-215` | `build_retry_prompt()` | Agent | Retry after gate violations (CGE step 4) | `task`, `code_files`, `contract`, `violations` | JSON V1/V2 |
| P30 | `leg_reduction.py:44-128` | `build_leg_reduction_prompt()` | Agent | Plan-verify-revise in single call with full trace schema | `task`, `code_files` | Raw JSON (own schema) |

### 1.3 Retry Harness Prompts

| ID | File | Function/Constant | Role | Purpose | Input Variables | Output Contract |
|----|------|-------------------|------|---------|-----------------|-----------------|
| P31 | `retry_harness.py:906-912` | `_build_initial_prompt()` | Agent | First attempt in retry loop | `case`, `use_alignment` | JSON V1/V2 |
| P32 | `retry_harness.py:915-935` | `_build_retry_prompt()` | Retry | Subsequent attempts with error feedback | `case`, `original_code`, `prev_code`, `test_output`, `critique`, `contract`, `adaptive_hint`, `trajectory_context` | JSON V1/V2 |
| P33 | `retry_harness.py:899-903` | `_ALIGNMENT_EXTRA` | Agent (modifier) | Emphasis on structured plan field | (constant) | Appended to other prompts |

### 1.4 Evaluator / Classifier Prompts

| ID | File | Function/Constant | Role | Purpose | Input Variables | Output Contract |
|----|------|-------------------|------|---------|-----------------|-----------------|
| P34 | `evaluator.py:34-88` | `_CLASSIFY_PROMPT` | Classifier | Judge reasoning correctness + failure type | `failure_types`, `task`, `code`, `reasoning` | Raw text: `YES/NO ; FAILURE_TYPE` |
| P35 | `leg_evaluator.py:27-88` | `_CRIT_LITE_BLIND_PROMPT` | Evaluator | LEG-specific blind evaluation (no prior classification) | `code`, `error_category`, `error_message`, `test_reasons`, `reasoning` | Raw text: `VERDICT ; FAILURE_TYPE` |
| P36 | `leg_evaluator.py:90-93` | `_CRIT_LITE_CONDITIONED_PROMPT` | Evaluator | LEG-specific conditioned evaluation (with classifier type) | Same + `classifier_type` | Raw text: `VERDICT ; FAILURE_TYPE` |

### 1.5 Retry Support Prompts (secondary LLM calls)

| ID | File | Function/Constant | Role | Purpose | Input Variables | Output Contract |
|----|------|-------------------|------|---------|-----------------|-----------------|
| P37 | `retry_harness.py:841-858` | `_call_critique()` | Evaluator | Structured failure diagnosis after failed attempt | `code_k`, `test_output` | Raw JSON: `{failure_type, root_cause, ...}` |
| P38 | `retry_harness.py:878-887` | `_elicit_contract()` | Agent | Lightweight intent elicitation before retry loop | `case["task"]` | Raw JSON: `{bug_identified, fix_approach, invariants}` |

### 1.6 Output Instructions (appended by call_model)

| ID | File | Constant/Function | Purpose | When Applied |
|----|------|--------------------|---------|--------------|
| P39 | `llm.py:14-29` | `_JSON_OUTPUT_INSTRUCTION_V1` | Force JSON with reasoning/plan/code fields | Default for all non-raw calls when format=v1 |
| P40 | `llm.py:32-45` | `_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE` | Force file-dict JSON with UNCHANGED sentinel | When format=v2 and file_paths provided |

### 1.7 Jinja2 Templates (registered but NOT primary path)

| Template | File | Variables | Notes |
|----------|------|-----------|-------|
| `base.jinja2` | `templates/` | `task`, `code_files_block` | Mirrors P01 |
| `classify.jinja2` | `templates/` | `failure_types`, `task`, `code`, `reasoning` | Mirrors P34 |
| `contract_elicit.jinja2` | `templates/` | `task`, `code_files_block`, `contract_schema` | Mirrors P27 |
| `contract_code.jinja2` | `templates/` | `task`, `code_files_block`, `contract_json` | Mirrors P28 |
| `contract_retry.jinja2` | `templates/` | `task`, `code_files_block`, `contract_json`, `violations_text` | Mirrors P29 |
| `retry.jinja2` | `templates/` | `task`, `code_files_block`, `previous_code`, `test_output`, ... | Mirrors P32 |
| `repair_feedback.jinja2` | `templates/` | `task`, `code_files_block`, `error_reasons` | Repair loop feedback |

**Total: 40 prompt definitions across 11 files.**

---

## 2. PROMPT CONSTRUCTION PIPELINE

### 2.1 Generation Prompt Flow (baseline + nudged conditions)

```
case dict
  ↓
execution.py:build_prompt(case, condition)
  ↓
prompts.py:build_base_prompt(task, code_files)     → base string
  ↓
nudges/router.py:apply_{condition}(case_id, base)  → base + nudge suffix
  ↓
llm.py:call_model(prompt, model, file_paths)
  ↓
llm.py: prompt + _JSON_OUTPUT_INSTRUCTION_V1 or V2 → full_prompt
  ↓
OpenAI API
```

**Variable introduction points:**
- `task` — from `case["task"]` at `build_prompt`
- `code_files` — from `case["code_files_contents"]` at `build_prompt`
- `failure_mode` — from `case["failure_mode"]` via `nudges/router.py` per-case mapping
- `file_paths` — from `case["code_files_contents"].keys()` at `run_single`
- JSON output instruction — chosen in `call_model` based on `_get_output_format()` (config) and `file_paths`

**Hidden transformations:**
1. `_format_code_files()` in `prompts.py` wraps each file in `### FILE N/M: {path} ###` delimiters with triple-backtick Python fences
2. `call_model()` silently appends output instruction unless `raw=True`
3. Nudge router does per-case lookup to select which diagnostic/guardrail variant applies — this mapping is hard-coded in `nudges/router.py`

**Implicit defaults:**
- If condition is not recognized, `build_prompt` raises `ValueError`
- If nudge operator not found for a case_id, generic operator is used
- If `output_format` config is not set, defaults to `"v1"`

### 2.2 LEG-Reduction Prompt Flow

```
case dict
  ↓
execution.py:run_leg_reduction()
  ↓
leg_reduction.py:build_leg_reduction_prompt(task, code_files)
  → self-contained prompt with own JSON schema (NOT V1/V2)
  ↓
llm.py:call_model(prompt, model, raw=True)
  → NO output instruction appended (raw=True)
  ↓
OpenAI API
```

**Critical difference:** LEG prompt defines its OWN output schema (revision_history, verification, etc.) and uses `raw=True` to bypass V1/V2 output instruction. The V1/V2 instruction is still appended by `call_model` because `raw=True` is NOT passed — actually checking code: `raw_output = call_model(prompt, model=model, raw=True)` at execution.py:760. So `raw=True` IS set. No output instruction appended.

### 2.3 Contract-Gated Prompt Flow

```
case dict
  ↓
contract.py:build_contract_prompt(task, code_files)
  → raw=True (no output instruction)
  ↓
OpenAI API → contract JSON
  ↓
contract.py:parse_contract(raw) → contract dict
  ↓
contract.py:build_code_from_contract_prompt(task, code_files, contract)
  → raw=False (output instruction V1/V2 appended)
  ↓
OpenAI API → code JSON
  ↓
[Optional: gate fails]
  ↓
contract.py:build_retry_prompt(task, code_files, contract, violations)
  → raw=False (output instruction appended)
  ↓
OpenAI API → retry code JSON
```

**Three separate LLM calls**, each with different prompt construction and different raw/non-raw behavior.

### 2.4 Classifier Prompt Flow

```
evaluate_case() → evaluate_output() → llm_classify()
  ↓
evaluator.py: _CLASSIFY_PROMPT.format(failure_types, task, code, reasoning)
  → truncated by config limits (max_task_chars, max_code_chars, max_reasoning_chars)
  ↓
llm.py:call_model(prompt, model=eval_model, raw=True)
  → NO output instruction (raw=True)
  ↓
OpenAI API → "YES ; FAILURE_TYPE" or "NO ; FAILURE_TYPE"
```

**Hidden transformation:** Truncation happens silently. If reasoning is 5000 chars and `max_reasoning_chars=1000`, the classifier sees only the first 1000. This is config-controlled but invisible at the prompt level.

### 2.5 Retry Harness Prompt Flow

```
Iteration 0:
  _build_initial_prompt(case) → build_base_prompt(task, code_files)
  → call_model(prompt, model) [V1/V2 appended]

Iteration k>0:
  _build_retry_prompt(case, original_code, prev_code, test_output, critique, ...)
  → concatenation of: task + original code + previous attempt + test results
    + optional critique + optional contract + optional adaptive hint
    + optional trajectory context
  → call_model(prompt, model) [V1/V2 appended]

Between iterations (on failure):
  _call_critique(model, code_k, error_obj, ev) → call_model(raw=True)
```

**Variable accumulation:** Each retry iteration adds more context. By iteration 5, the prompt contains the original code, the failed attempt, test output, critique JSON, contract JSON, adaptive hint, and trajectory feedback — all concatenated with `\n`.join().

---

## 3. PROMPT COUPLING ANALYSIS

### 3.1 Tight Coupling

| Coupling | From | To | Breaks if... |
|----------|------|----|-------------|
| V1 output schema | `llm.py:_JSON_OUTPUT_INSTRUCTION_V1` | `parse.py:_try_json_direct()` | Output instruction changes field names (reasoning/plan/code) |
| V2 output schema | `llm.py:_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE` | `parse.py:_try_file_dict()` | File-dict structure changes (reasoning/files) |
| Classifier output format | `evaluator.py:_CLASSIFY_PROMPT` "Return EXACTLY one line" | `evaluator.py:parse_classify_output()` | Expected format `YES/NO ; TYPE` changes |
| LEG schema | `leg_reduction.py` prompt schema | `leg_reduction.py:parse_leg_reduction_output()` | Any field rename in revision_history/verification/code |
| Critique schema | `retry_harness.py:_call_critique()` | `retry_harness.py:860-866` JSON parsing | Any field rename in failure_type/root_cause/... |
| Contract schema | `contract.py:CONTRACT_SCHEMA_TEXT` | `contract.py:parse_contract()` | Any field rename in root_cause/must_change/... |

### 3.2 Hidden Coupling

| Coupling | Description |
|----------|-------------|
| Code fence format | `prompts.py:_format_code_files()` wraps code in triple-backtick `python` fences. The parser's raw_fallback (`parse.py:_try_code_block()`) looks for these same fences. If the formatting changes, parse fallback breaks. |
| UNCHANGED sentinel | V2 instruction tells model to use `"UNCHANGED"`. `reconstructor.py` checks for this exact string. If instruction wording changes, reconstruction breaks. |
| Nudge per-case mapping | `nudges/router.py` hard-codes which case_id gets which operator. Adding a new case requires updating this mapping — not discoverable from config. |
| SCM data dependency | `scm_prompts.py` calls `get_scm(case_id)` which reads from `scm_data/`. If SCM data doesn't exist for a case, prompt silently falls back to base prompt (no error). |
| Retry prompt accumulation | `_build_retry_prompt` concatenates all feedback as raw strings. No structure — just `\n.join(parts)`. Reordering parts could change model behavior. |
| `raw=True` bypass | Some prompts need `raw=True` to avoid V1/V2 instruction collision (LEG, contract elicit, classifier). Forgetting `raw=True` on a new prompt would corrupt its output with conflicting JSON schema instructions. |

---

## 4. DUPLICATION + CODE PATH AUDIT

### 4.1 Distinct Prompt Generation Code Paths

**7 distinct code paths generate prompts:**

1. `execution.py:build_prompt()` → dispatches to ~18 conditions via if/elif chain
2. `contract.py` → 3 functions (elicit, code, retry) — independent of build_prompt
3. `leg_reduction.py` → 1 function — independent of build_prompt
4. `retry_harness.py` → 2 functions (initial, retry) + 2 secondary (critique, contract) — independent
5. `evaluator.py:llm_classify()` → 1 classifier prompt — independent
6. `leg_evaluator.py:evaluate_reasoning()` → 2 evaluator prompts — independent
7. `llm.py:call_model()` → appends output instruction to all non-raw prompts

### 4.2 Duplication Found

| Duplication | Files | Description |
|-------------|-------|-------------|
| Base prompt construction | `prompts.py:build_base_prompt()` vs `retry_harness.py:_build_initial_prompt()` | `_build_initial_prompt` calls `build_base_prompt` — not duplication, but tight coupling |
| Code file formatting | `prompts.py:_format_code_files()` used by ALL prompt builders | Single source — good. BUT `contract.py` imports it from prompts.py, creating cross-module dependency |
| Diagnostic nudge text | `prompts.py` (case-specific variants) vs `nudges/core.py` (generic variants) | TWO parallel sets of diagnostic nudges: 4 case-specific in prompts.py, 4 generic in nudges/core.py. Different text, same purpose. |
| Guardrail nudge text | `prompts.py` (case-specific variants) vs `nudges/core.py` (generic variants) | Same duplication: 4 case-specific, 4 generic |
| Classifier prompt | `evaluator.py:_CLASSIFY_PROMPT` vs `templates/classify.jinja2` | Nearly identical text in two places. The Jinja2 template is registered but NOT used at runtime — the constant string wins. |
| Contract prompts | `contract.py` functions vs `templates/contract_*.jinja2` | Same issue: templates exist but functions use inline f-strings |
| Retry prompt | `retry_harness.py:_build_retry_prompt()` vs `templates/retry.jinja2` | Template exists but is NOT used |

**Key finding:** The Jinja2 template system (`templates.py`) is fully implemented and registered but is a DEAD CODE PATH for all prompts except possibly the config-driven template lookup. The actual prompt construction uses Python f-strings in the individual modules.

### 4.3 Near-Duplicate Prompt Variants

| Variant A | Variant B | Difference |
|-----------|-----------|------------|
| `_dependency_check_diagnostic()` (generic) | `HIDDEN_DEPENDENCY` nudge in `prompts.py` (case-specific) | Generic says "list ALL side effects"; case-specific references specific functions by name |
| `_invariant_guard_diagnostic()` (generic) | `INVARIANT_VIOLATION` nudge in `prompts.py` (case-specific) | Generic says "identify the key correctness invariant"; case-specific names the exact invariant |
| `_CLASSIFY_PROMPT` (evaluator.py) | `_CRIT_LITE_BLIND_PROMPT` (leg_evaluator.py) | Both classify reasoning correctness. Different input format (CLASSIFY uses task/code/reasoning; CRIT_LITE uses code/error/reasoning). Different output instructions. Overlapping purpose. |

---

## 5. VARIABILITY ANALYSIS

### 5.1 What CAN Be Ablated Today

| Dimension | Mechanism | Config-driven? |
|-----------|-----------|----------------|
| Which condition runs | `config.conditions` keys | YES |
| Generation model | `config.models.generation[0].name` | YES |
| Evaluator model | `config.models.evaluator.name` | YES |
| Output format (V1/V2) | `config.execution.output_format` | YES |
| Truncation limits | `config.models.evaluator.max_*_chars` | YES |
| Max retry attempts | `config.retry_defaults.max_attempts` | YES |
| Token budgets | `config.execution.token_budgets` | YES |
| Temperature | `config.models.generation[0].temperature` | YES |

### 5.2 What CANNOT Be Ablated Today

| Dimension | Why Not | What Would Need to Change |
|-----------|---------|---------------------------|
| Prompt text for any condition | Hard-coded in Python functions | Move to external templates, load by config key |
| Output instruction text | Hard-coded constants in `llm.py` | Move to config or template |
| Classifier prompt text | Hard-coded constant in `evaluator.py` | Move to template |
| Nudge text | Hard-coded in `nudges/core.py` and `prompts.py` | Move to external files |
| SCM evidence format | Hard-coded f-strings in `scm_prompts.py` | Parameterize format |
| LEG reduction schema | Hard-coded in `leg_reduction.py` | Move schema to config/template |
| Per-case nudge assignment | Hard-coded in `nudges/router.py` | Move to case metadata or config |
| Critique prompt structure | Hard-coded in `retry_harness.py` | Move to template |
| Retry feedback composition | Hard-coded concatenation order in `_build_retry_prompt` | Parameterize components |
| Code file formatting | Hard-coded fence + delimiter style in `_format_code_files` | Parameterize |

### 5.3 What Prevents Prompt Ablation

1. **No indirection layer.** Prompts are inline Python f-strings. To swap a prompt, you edit source code.
2. **No registry.** There is no mapping from `(condition, stage) → prompt template`. The `build_prompt()` if/elif chain IS the registry.
3. **Output instruction is coupled to call_model.** You cannot override the output instruction per-prompt without passing `raw=True` and managing it yourself.
4. **No version tracking.** Prompt text has no version identifier. Changing a prompt mid-experiment is invisible.

---

## 6. SUB-PROMPT STRUCTURE BREAKDOWN

### 6.1 Generation Prompt (baseline + nudged)

```
[COMPONENT 1: Task Description]         — from case["task"], always present
[COMPONENT 2: Code Files Block]         — from _format_code_files(), always present
[COMPONENT 3: Nudge/Intervention]       — condition-specific suffix, ABSENT for baseline
[COMPONENT 4: Output Instruction]       — V1 or V2, appended by call_model(), always present (unless raw)
```

Components 1-2 are reusable. Component 3 varies per condition. Component 4 is implicit.

### 6.2 LEG-Reduction Prompt

```
[COMPONENT 1: Task Description]         — same as baseline
[COMPONENT 2: Code Files Block]         — same as baseline
[COMPONENT 3: Schema Definition]        — the JSON schema with revision_history etc.
[COMPONENT 4: Procedure Steps]          — STEP 1 through STEP 5 instructions
[COMPONENT 5: Rules]                    — validation rules for the schema
```

Components 3-5 are entangled — changing the schema requires changing the procedure and rules. NOT independently swappable.

### 6.3 Contract-Gated Prompts

Step 1 (Elicit):
```
[COMPONENT 1: Task Description]
[COMPONENT 2: Code Files Block]
[COMPONENT 3: Analysis Instruction]     — "analyze this codebase and identify causal dependencies"
[COMPONENT 4: Contract Schema]          — CONTRACT_SCHEMA_TEXT constant
```

Step 2 (Code Gen):
```
[COMPONENT 1: Task Description]
[COMPONENT 2: Code Files Block]
[COMPONENT 3: Contract Commitment]      — full contract JSON
[COMPONENT 4: Compliance Instructions]  — "Modify ONLY must_change, maintain ALL invariants..."
```

### 6.4 Classifier Prompt

```
[COMPONENT 1: Role Definition]          — "You are evaluating whether..."
[COMPONENT 2: Anti-Bias Instructions]   — "Do NOT assume code is correct..."
[COMPONENT 3: Task Definition]          — two things to determine
[COMPONENT 4: Failure Types List]       — from FAILURE_TYPE_SET
[COMPONENT 5: Inputs]                   — task, reasoning, code (truncated)
[COMPONENT 6: Rules]                    — conservatism, vagueness rejection
[COMPONENT 7: Output Format]            — "Return EXACTLY one line: YES/NO ; TYPE"
```

Components 1-3, 6-7 are reusable across classifier variants. Components 4-5 are variable.

### 6.5 Retry Prompt

```
[COMPONENT 1: Task Description]
[COMPONENT 2: Original Code]            — formatted code files
[COMPONENT 3: Previous Attempt]         — failed code
[COMPONENT 4: Test Results]             — error output
[COMPONENT 5: Critique]                 — optional, JSON
[COMPONENT 6: Contract]                 — optional, JSON
[COMPONENT 7: Adaptive Hint]            — optional, from failure type
[COMPONENT 8: Trajectory Context]       — optional, from trajectory analysis
[COMPONENT 9: Fix Instruction]          — "Fix the failing tests..."
[COMPONENT 10: Alignment Extra]         — optional, plan emphasis
```

10 components, most optional. Concatenated in fixed order. No way to reorder or selectively include without code changes.

---

## 7. FAILURE MODES

### 7.1 Parsing Failures Due to Format Drift

| Risk | Description | Likelihood |
|------|-------------|------------|
| V1/V2 instruction ignored by model | Model returns raw text instead of JSON. Parser falls through to `raw_fallback`. | Medium — happens with smaller models |
| LEG schema partially followed | Model omits `revision_history` or `verification`. Parser marks `schema_compliant=False` but extracts code. | High — observed in ablation runs |
| Classifier returns multi-line | Expected `YES ; TYPE` but model adds explanation. `parse_classify_output()` takes first line only. | Low — but fragile |
| UNCHANGED sentinel misspelled | Model writes "unchanged" or "SAME". Reconstructor treats as modified file. | Medium — observed |

### 7.2 Silent Mismatches Between Evaluator + Generator

| Risk | Description |
|------|-------------|
| Classifier truncation hides context | Generator produces 3000-char reasoning. Classifier sees only first 1000 chars (`max_reasoning_chars`). Classifier judges truncated reasoning, not full reasoning. |
| Code truncation misses the fix | Generator produces 4000-char code. Classifier sees only first 2000 chars (`max_code_chars`). The actual fix may be beyond the truncation point. |
| Failure type vocabulary mismatch | Generator nudges reference specific failure modes (e.g., "aliasing"). Classifier uses a fixed vocabulary (`FAILURE_TYPE_SET`). The mapping is implicit. |

### 7.3 Trace-Output Inconsistency (RAudit-style)

| Risk | Description |
|------|-------------|
| Reasoning evaluated on different text than what was generated | If parser recovery changes the extracted reasoning (e.g., lenient JSON repair), the classifier evaluates recovered text, not original. |
| Code evaluated differs from code classified | Reconstruction may normalize file content (fence stripping, newline unescaping). The classifier sees pre-reconstruction code; execution tests post-reconstruction code. |

### 7.4 Hidden Assumptions

- All generation prompts assume the model understands Python code fences
- V2 assumes model can count files and use UNCHANGED sentinel correctly
- LEG prompt assumes model can self-verify plan against code (the core hypothesis)
- Retry prompt assumes adding more context helps (no evidence of diminishing returns)

---

## 8. LOGGING + VISIBILITY GAP

### 8.1 Can We See the EXACT Prompt Sent to LLM?

**YES** — since the call logger implementation. Every `call_model()` invocation writes the full `prompt_raw` to `calls/{call_id}.json` and `calls_flat.txt`.

### 8.2 Can We Reconstruct Prompt After Run?

**YES** — from `calls/*.json`. Each file contains the complete prompt string including the appended output instruction.

### 8.3 Are Sub-Components Logged?

**NO.** The call logger captures the final assembled string. There is no record of:
- Which nudge was applied
- Which output instruction was chosen (V1 vs V2)
- What truncation was applied to classifier inputs
- What the base prompt was before nudge application
- Which SCM data was fetched and included

**Missing logging points:**
1. `execution.py:build_prompt()` — should log: condition, nudge operator name, base prompt length, final prompt length
2. `llm.py:call_model()` — should log: which output instruction was appended (v1/v2/none)
3. `evaluator.py:llm_classify()` — should log: truncation applied (original vs truncated lengths for task, code, reasoning)
4. `nudges/router.py` — should log: which operator was selected for which case_id

---

## 9. REQUIRED CAPABILITIES FOR NEW SYSTEM

1. **Prompt composability.** A prompt must be assembled from named, swappable components: `base + nudge + output_instruction`. Each component selected by config key, not by Python if/elif.

2. **Sub-prompt modularity.** Each logical component (task block, code block, nudge, output schema, classifier instructions) must be an independently loadable unit — a named template file or config entry.

3. **Swap-in / swap-out mechanism.** Config maps `(condition, stage) → template_name`. Changing a prompt for an ablation means changing one config line, not editing Python source.

4. **Versioning.** Every template must have a content hash logged at run start (the `templates.py` system already does this via `init_template_hashes()`). The hash must appear in run metadata.

5. **Explicit output schemas.** The output instruction (V1/V2/raw/LEG) must be an explicit config choice per condition, not an implicit consequence of `raw=True` in source code.

6. **Full component visibility.** The call logger must record not just the final prompt string, but the component assembly: `{base_template, nudge_template, output_instruction, truncation_applied}`.

7. **Single construction path.** All prompts — generation, classifier, critique, contract — must flow through ONE assembly function that logs components, applies templates, and returns the final string.

---

## 10. MINIMAL REFACTOR PLAN (NO IMPLEMENTATION)

### 10.1 Where Prompt Definitions Should Live

```
prompts/
    generation/
        base.txt
        nudge_diagnostic_dependency.txt
        nudge_diagnostic_invariant.txt
        nudge_guardrail_dependency.txt
        ...
        scm_descriptive.txt
        scm_constrained.txt
        leg_reduction_schema.txt
        contract_elicit.txt
        contract_code.txt
    evaluation/
        classify_reasoning.txt
        crit_lite_blind.txt
        crit_lite_conditioned.txt
    retry/
        critique.txt
        initial.txt
        feedback.txt
    output_instructions/
        v1_json.txt
        v2_filedict.txt
        leg_schema.txt
```

Each file is a plain text template with `{variable}` placeholders. No Python logic. No imports.

### 10.2 How Templates Should Be Structured

Each template is a named text file. A manifest (`prompts/manifest.yaml`) maps:

```yaml
generation:
  baseline:
    template: "generation/base.txt"
    output_instruction: "v2_filedict"
  diagnostic:
    template: "generation/base.txt"
    nudge: "generation/nudge_diagnostic_{failure_mode}.txt"
    output_instruction: "v2_filedict"
  leg_reduction:
    template: "generation/base.txt"
    nudge: "generation/leg_reduction_schema.txt"
    output_instruction: null  # raw mode
evaluation:
  classify:
    template: "evaluation/classify_reasoning.txt"
    output_instruction: null  # raw mode
```

### 10.3 How Variables Should Be Passed

One `PromptContext` dict flows through the entire assembly:

```
{
    "task": str,
    "code_files": dict,
    "code_files_block": str,  # formatted
    "failure_mode": str,
    "case_id": str,
    "condition": str,
    "failure_types": str,     # for classifier
    "contract": dict,         # for CGE
    "violations": list,       # for CGE retry
    ...
}
```

Each template declares which variables it needs. Assembly validates all required variables are present.

### 10.4 How Prompts Should Be Selected/Swapped

```
condition (from config)
  → manifest lookup → template path + nudge path + output_instruction
  → load templates from files
  → assemble: base_template.format(**context) + nudge_template.format(**context) + output_instruction
  → log components: {template_name, nudge_name, output_instruction_name, content_hashes}
  → return final string
```

One function: `assemble_prompt(condition, stage, context) → str`. Called from every code path that currently constructs a prompt. No other prompt construction allowed.

### 10.5 Constraints

- SINGLE code path for prompt construction: `assemble_prompt()`
- ZERO duplication: templates are files, used once
- FULL observability: component names + hashes logged per call
- Ablation by config: swap a template file path in manifest, re-run
- Backward compatible: existing prompts become the initial template files, byte-for-byte identical

---

*End of audit. No implementation performed.*
