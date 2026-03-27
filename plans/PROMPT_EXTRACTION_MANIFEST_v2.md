# Prompt Extraction Manifest v2 — Consolidated

**Date:** 2026-03-27
**Status:** MANIFEST ONLY — awaiting approval before extraction
**Source prompts:** 46
**Proposed components:** 12

---

## COMPONENT SYSTEM

---

### C1: `task_and_code.j2`

**Absorbs:** P1 (build_base_prompt), P42 (retry initial prompt base)

**Variables:** `{{ task }}`, `{{ code_files_block }}`

**Structure:**
```
{{ task }}

{{ code_files_block }}
```

**Justification:** Foundation for all generation prompts. Used directly for baseline, and as the opening section for every other generation prompt. Retry initial is just this + optional alignment nudge.

---

### C2: `nudge_diagnostic.j2`

**Absorbs:** P2-P5 (case-specific diagnostics), P10-P13 (generic diagnostics)

**Variables:** `{{ diagnostic_text }}`

**Structure:**
```
{{ diagnostic_text }}
```

The `diagnostic_text` variable is resolved by the selection engine from the nudge registry (8 entries: 4 case-specific, 4 generic, selected by override ladder). The text entries are stored as keyed values in `prompts/registry.yaml`, not as separate files.

**Justification:** All 8 diagnostic variants are structurally identical — static text appended after the base prompt. They differ only in content. One template, 8 registry entries.

---

### C3: `nudge_guardrail.j2`

**Absorbs:** P6-P9 (case-specific guardrails), P14-P17 (generic guardrails), P18 (hard constraints)

**Variables:** `{{ guardrail_text }}`, `{{ hard_constraints_section }}`

**Structure:**
```
{{ guardrail_text }}
{% if hard_constraints_section %}

{{ hard_constraints_section }}
{% endif %}
```

Wait — v7 bans `{% if %}`. Revised approach: `hard_constraints_section` defaults to empty string. Jinja2 renders it as nothing when empty. No control flow needed:

**Revised structure:**
```
{{ guardrail_text }}

{{ hard_constraints_section }}
```

When no hard constraints exist, `hard_constraints_section` is `""` and the trailing whitespace is harmless (stripped by join).

`guardrail_text` resolved by selection engine (8 entries). `hard_constraints_section` provided by context provider (formatted bullet list or empty string).

**Justification:** Guardrail + hard constraints always co-occur in the `guardrail_strict` condition. Merging avoids a separate hard constraints component. 8 guardrail text variants + optional hard constraints = 1 template.

---

### C4: `nudge_reasoning.j2`

**Absorbs:** P19-P23 (counterfactual, reason_then_act, self_check, counterfactual_check, test_driven), P24-P26 (structured, free_form, branching), P42 alignment extra

**Variables:** `{{ reasoning_text }}`

**Structure:**
```
{{ reasoning_text }}
```

`reasoning_text` resolved by selection engine from 9 entries (5 intervention strategies + 3 reasoning modes + 1 alignment extra).

**Justification:** All 9 are structurally identical — static text appended as a reasoning scaffold. One template, 9 registry entries.

---

### C5: `nudge_scm.j2`

**Absorbs:** P27-P32 (all 6 SCM prompts)

**Variables:** `{{ scm_mode }}`, `{{ scm_content }}`

`scm_content` is a pre-rendered block produced by the SCMContextProvider. The provider accepts a `mode` parameter (`descriptive`, `constrained`, `constrained_evidence`, `constrained_evidence_minimal`, `evidence_only`, `length_control`) and produces the fully formatted text block including all edges/constraints/invariants/functions/variables appropriate for that mode.

**Structure:**
```
{{ scm_content }}
```

**Justification:** All 6 SCM prompts share the same structural role (causal analysis appended to base). They differ in which SCM data is included and how it's formatted. Moving the formatting logic into the SCMContextProvider (which already fetches the data) eliminates 6 templates. The provider is the right owner because it already has the SCM data and knows the mode. The template just renders the pre-formatted block.

---

### C6: `cge_stage.j2`

**Absorbs:** P33 (contract elicit), P34 (code from contract), P35 (retry after violations)

**Variables:** `{{ task }}`, `{{ code_files_block }}`, `{{ cge_instruction }}`

**Structure:**
```
{{ task }}

{{ code_files_block }}

{{ cge_instruction }}
```

`cge_instruction` is a pre-rendered block produced by the ContractContextProvider based on the CGE stage:
- `elicit`: analysis instruction + contract schema
- `code`: contract commitment + compliance instructions
- `retry`: violations list + contract commitment + fix instruction

**Justification:** All 3 CGE prompts share identical structure: task + code + stage-specific instruction. The instruction block varies by stage but is provided as a single rendered variable. One template, 3 instruction variants produced by the context provider.

---

### C7: `leg_reduction.j2`

**Absorbs:** P36 (LEG reduction prompt)

**Variables:** `{{ task }}`, `{{ code_files_block }}`

**Structure:** Task + code + embedded JSON schema + procedure steps + rules. This is a single large template (~80 lines). The schema and procedure are static text within the template, not variables.

**Justification:** Cannot be merged with any other component. The LEG schema is unique and self-contained. The task/code variables overlap with C1 but the rest of the template is entirely different.

---

### C8: `classify_reasoning.j2`

**Absorbs:** P37 (classifier prompt)

**Variables:** `{{ failure_types }}`, `{{ task }}`, `{{ code }}`, `{{ reasoning }}`

**Structure:** Role definition + anti-bias instructions + task definition + failure types list + inputs (task, reasoning, code) + rules + output format instruction.

**Justification:** Cannot be merged. Unique role (classifier, not agent). Unique output format (`YES/NO ; TYPE`). Unique variable set (truncated inputs).

---

### C9: `evaluate_reasoning.j2`

**Absorbs:** P38 (blind evaluator), P39 (conditioned evaluator)

**Variables:** `{{ code }}`, `{{ error_category }}`, `{{ error_message }}`, `{{ test_reasons }}`, `{{ reasoning }}`, `{{ system_detected_section }}`

**Structure:** Evaluator role + inputs + evaluation phases + failure types + verdict rules + output format. `system_detected_section` is empty string for blind mode, or `## System-Detected Failure Type\n{classifier_type}` for conditioned mode.

**Justification:** P38 and P39 are identical except for one optional section. One template with `system_detected_section` defaulting to empty string. No control flow needed.

---

### C10: `retry_stage.j2`

**Absorbs:** P40 (critique), P41 (contract elicit), P43 (retry feedback), P44 (repair feedback)

**Variables:** `{{ retry_content }}`

**Structure:**
```
{{ retry_content }}
```

`retry_content` is a pre-rendered block produced by the RetryContextProvider based on the retry stage:
- `critique`: code under test + test results + JSON schema for response
- `contract_elicit`: task + JSON schema for intent
- `feedback`: task + original code + previous attempt + test results + optional sections (critique, contract, hint, trajectory) + fix instruction
- `repair_feedback`: error reasons + fix instruction

**Justification:** All 4 retry-related prompts serve different stages of the retry harness. Rather than 4 templates with overlapping variables, one template renders a pre-formatted block from the provider. The provider owns the formatting logic because it owns the retry state (previous code, test output, critique, etc.).

---

### C11: `output_instruction_v1.j2`

**Absorbs:** P45 (V1 JSON output instruction)

**Variables:** none

**Structure:** Static text: "Return your response as a single valid JSON object..." with reasoning/plan/code schema.

**Justification:** Cannot be merged with V2 — different schema. Used by all non-raw, non-V2 prompts.

---

### C12: `output_instruction_v2.j2`

**Absorbs:** P46 (V2 file-dict output instruction)

**Variables:** `{{ file_entries }}`

**Structure:** Static text: "Return your response as a single valid JSON object..." with reasoning/files schema, `file_entries` lists the expected file paths.

**Justification:** Cannot be merged with V1 — different schema structure (files dict vs code field).

---

## COMPONENT SUMMARY TABLE

| # | Component | Source Prompts | Variables | Role | Stage |
|---|---|---|---|---|---|
| C1 | `task_and_code.j2` | P1, P42 | task, code_files_block | agent | generation |
| C2 | `nudge_diagnostic.j2` | P2-P5, P10-P13 | diagnostic_text | agent | generation |
| C3 | `nudge_guardrail.j2` | P6-P9, P14-P17, P18 | guardrail_text, hard_constraints_section | agent | generation |
| C4 | `nudge_reasoning.j2` | P19-P26, alignment extra | reasoning_text | agent | generation |
| C5 | `nudge_scm.j2` | P27-P32 | scm_content | agent | generation |
| C6 | `cge_stage.j2` | P33-P35 | task, code_files_block, cge_instruction | agent | CGE |
| C7 | `leg_reduction.j2` | P36 | task, code_files_block | agent | generation |
| C8 | `classify_reasoning.j2` | P37 | failure_types, task, code, reasoning | classifier | classify |
| C9 | `evaluate_reasoning.j2` | P38-P39 | code, error_category, error_message, test_reasons, reasoning, system_detected_section | evaluator | evaluate |
| C10 | `retry_stage.j2` | P40-P41, P43-P44 | retry_content | agent/eval | retry |
| C11 | `output_instruction_v1.j2` | P45 | (none) | format | all |
| C12 | `output_instruction_v2.j2` | P46 | file_entries | format | all |

**Total: 12 components.**

---

## NUDGE TEXT REGISTRY ENTRIES

Stored in `prompts/registry.yaml` under `nudge_texts:`, not as separate files:

**Diagnostic (8 entries):**
- `diagnostic__hidden_dependency` (case-specific, from prompts.py)
- `diagnostic__temporal_causal_error` (case-specific)
- `diagnostic__invariant_violation` (case-specific)
- `diagnostic__state_semantic_violation` (case-specific)
- `diagnostic__generic_dependency` (generic, from nudges/core.py)
- `diagnostic__generic_invariant` (generic)
- `diagnostic__generic_temporal` (generic)
- `diagnostic__generic_state` (generic)

**Guardrail (8 entries):**
- `guardrail__hidden_dependency` (case-specific)
- `guardrail__temporal_causal_error` (case-specific)
- `guardrail__invariant_violation` (case-specific)
- `guardrail__state_semantic_violation` (case-specific)
- `guardrail__generic_dependency` (generic)
- `guardrail__generic_invariant` (generic)
- `guardrail__generic_temporal` (generic)
- `guardrail__generic_state` (generic)

**Reasoning (9 entries):**
- `reasoning__counterfactual`
- `reasoning__reason_then_act`
- `reasoning__self_check`
- `reasoning__counterfactual_check`
- `reasoning__test_driven`
- `reasoning__structured`
- `reasoning__free_form`
- `reasoning__branching`
- `reasoning__alignment_extra`

**Total: 25 registry text entries + 12 structural components.**

---

## MERGE JUSTIFICATIONS

| Merge | From | Into | Why Valid |
|---|---|---|---|
| 8 diagnostic nudges → 1 template | P2-P5 + P10-P13 | C2 | Identical structure: static text appended to base. Only content differs. Selection engine resolves which text. |
| 9 guardrail nudges → 1 template | P6-P9 + P14-P17 + P18 | C3 | Identical structure: constraint text + optional hard constraints. Hard constraints provided as variable (empty when absent). |
| 9 reasoning nudges → 1 template | P19-P26 + alignment | C4 | Identical structure: static reasoning scaffold text. Only content differs. |
| 6 SCM prompts → 1 template | P27-P32 | C5 | Same structural role (causal analysis block). Provider renders mode-specific content. |
| 3 CGE prompts → 1 template | P33-P35 | C6 | Identical structure: task + code + stage instruction. Provider renders stage-specific instruction. |
| 2 evaluator prompts → 1 template | P38-P39 | C9 | Identical except one optional section. Empty-string variable for blind mode. |
| 4 retry prompts → 1 template | P40-P41, P43-P44 | C10 | Same execution context (retry harness). Provider renders stage-specific content. |

---

## WHAT IS NOT MERGED AND WHY

| Component | Why Not Merged |
|---|---|
| C1 `task_and_code.j2` | Foundation for all generation. Cannot merge with nudges (they append to it, not replace it). |
| C7 `leg_reduction.j2` | Unique 80-line schema. Cannot parameterize into task_and_code without control flow. |
| C8 `classify_reasoning.j2` | Different role (classifier vs agent). Different output format. Different variable set. |
| C11/C12 output instructions | V1 and V2 have fundamentally different JSON schemas (code field vs files dict). Cannot parameterize without control flow. |

---

## FINAL COUNT

- **12 structural `.j2` components**
- **25 nudge text entries** in `registry.yaml`
- **0 loose text files**

All prompt content lives in either a `.j2` template or a `registry.yaml` entry. Nothing outside the registry model.

---

*End of manifest v2. Awaiting approval before extraction.*
