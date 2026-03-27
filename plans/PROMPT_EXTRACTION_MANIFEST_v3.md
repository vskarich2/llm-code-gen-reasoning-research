# Prompt Extraction Manifest v3 — Final

**Date:** 2026-03-27
**Status:** MANIFEST ONLY — awaiting approval before extraction
**Proposed components:** 14

---

## CHANGES FROM V2

Only C5, C6, C10 changed. C1-C4, C7-C9, C11-C12 unchanged.

---

### C5: `nudge_scm.j2` (REVISED — structure moved into template)

**Absorbs:** P27-P32 (all 6 SCM prompts)

**Variables:** `{{ scm_mode }}`, `{{ scm_edges_text }}`, `{{ scm_constraints_text }}`, `{{ scm_invariants_text }}`, `{{ scm_functions_text }}`, `{{ scm_variables_text }}`, `{{ scm_critical_id }}`, `{{ scm_critical_why }}`, `{{ scm_critical_trace }}`, `{{ scm_filler_text }}`

All variables are atomic strings supplied by SCMContextProvider. The provider fetches data and formats each field individually. The template owns ALL structural layout.

**Structure:**
```
CAUSAL ANALYSIS

Functions:
{{ scm_functions_text }}

State:
{{ scm_variables_text }}

Dependencies:
{{ scm_edges_text }}

Constraints:
{{ scm_constraints_text }}

Invariants:
{{ scm_invariants_text }}

Critical constraint: {{ scm_critical_id }}
Why fragile: {{ scm_critical_why }}
Failure trace: {{ scm_critical_trace }}

For EACH change you propose, cite which IDs are affected.
After writing code, verify each invariant still holds.
```

Mode handling: the SCMContextProvider supplies empty strings for fields not relevant to the current mode. For `descriptive` mode: only `scm_edges_text` and `scm_critical_trace` are non-empty. For `length_control` mode: `scm_filler_text` is non-empty, all others empty. The template renders all sections; empty sections produce blank lines which are stripped by the assembly engine's join step.

**Provider responsibility:** Supply formatted atomic values (e.g., `scm_edges_text` = newline-joined edge descriptions). NOT assemble sections.

---

### C6: `cge_stage.j2` (REVISED — explicit fields, not opaque instruction block)

**Absorbs:** P33 (elicit), P34 (code from contract), P35 (retry after violations)

**Variables:** `{{ task }}`, `{{ code_files_block }}`, `{{ contract_schema_text }}`, `{{ contract_json }}`, `{{ violations_text }}`, `{{ cge_instruction }}`

**Structure:**
```
{{ task }}

{{ code_files_block }}

{{ contract_schema_text }}

{{ contract_json }}

{{ violations_text }}

{{ cge_instruction }}
```

Mode handling by variable population:
- **Elicit stage:** `contract_schema_text` = full schema. `contract_json` = empty. `violations_text` = empty. `cge_instruction` = "Analyze this codebase and identify causal dependencies. Return ONLY the JSON contract. Do not write code yet."
- **Code stage:** `contract_schema_text` = empty. `contract_json` = full contract. `violations_text` = empty. `cge_instruction` = "Write refactored code that satisfies ALL contract terms. Modify ONLY must_change functions. Maintain ALL invariants."
- **Retry stage:** `contract_schema_text` = empty. `contract_json` = full contract. `violations_text` = formatted list. `cge_instruction` = "Fix EACH violation specifically. Do not change anything else. Return corrected code only."

`cge_instruction` is a short static string (1-3 sentences) — NOT a multi-section block. It is a directive, not a layout. The instruction text entries live in `registry.yaml` under `cge_instructions:`.

**Provider responsibility:** Supply `contract_schema_text` (static text), `contract_json` (serialized dict), `violations_text` (formatted bullet list). All atomic values. Template owns layout.

---

### C10: SPLIT → `retry_analysis.j2` (C10a) + `retry_generation.j2` (C10b)

#### C10a: `retry_analysis.j2`

**Absorbs:** P40 (critique), P41 (retry contract elicit)

**Variables:** `{{ code_under_test }}`, `{{ test_output }}`, `{{ analysis_instruction }}`, `{{ analysis_schema }}`

**Structure:**
```
{{ analysis_instruction }}

{{ code_under_test }}

{{ test_output }}

{{ analysis_schema }}
```

Mode handling:
- **Critique:** `analysis_instruction` = "You are analyzing a code fix attempt that FAILED its tests." `code_under_test` = code. `test_output` = test results. `analysis_schema` = JSON schema for failure_type/root_cause/etc.
- **Contract elicit:** `analysis_instruction` = "Before fixing this bug, state your intent." `code_under_test` = empty. `test_output` = empty (just task in this case — actually, task goes in `analysis_instruction`). `analysis_schema` = JSON schema for bug_identified/fix_approach/invariants.

Revised — contract elicit has different shape. Let me reconsider.

Actually, P41 (contract elicit) is: `task + JSON schema`. P40 (critique) is: `instruction + code + test_output + JSON schema`. These share the pattern "instruction + context + schema" but the context differs. The template handles this with variables that may be empty:

```
{{ analysis_instruction }}

{{ analysis_context }}

{{ analysis_schema }}
```

- **Critique:** `analysis_context` = code block + test results. `analysis_instruction` = "You are analyzing..."
- **Contract elicit:** `analysis_context` = task description. `analysis_instruction` = "Before fixing this bug, state your intent."

`analysis_context` is an atomic formatted string from the provider (either code+tests or task text). NOT a multi-section layout.

Provider responsibility: supply `analysis_context` as a pre-formatted atomic string. This is acceptable — it's a single contextual input, not prompt structure.

#### C10b: `retry_generation.j2`

**Absorbs:** P43 (retry feedback), P44 (repair feedback)

**Variables:** `{{ task }}`, `{{ original_code }}`, `{{ previous_code }}`, `{{ test_output }}`, `{{ critique_section }}`, `{{ contract_section }}`, `{{ hint_section }}`, `{{ trajectory_section }}`, `{{ fix_instruction }}`

**Structure:**
```
{{ task }}

=== Original Code ===
{{ original_code }}

=== Your Previous Attempt ===
{{ previous_code }}

=== Test Results (FAILED) ===
{{ test_output }}

{{ critique_section }}

{{ contract_section }}

{{ hint_section }}

{{ trajectory_section }}

{{ fix_instruction }}
```

Mode handling:
- **Retry feedback (P43):** All sections populated as available. Optional sections (critique, contract, hint, trajectory) are empty strings when not applicable.
- **Repair feedback (P44):** `original_code` = empty. `previous_code` = empty. `critique_section` = empty. `contract_section` = empty. `hint_section` = empty. `trajectory_section` = empty. `test_output` = error reasons. `fix_instruction` = "Fix and return corrected code."

Each `*_section` variable is an atomic formatted string from the RetryContextProvider (e.g., `critique_section` = `"=== Diagnosis ===\n" + json.dumps(critique)` or empty string). These are single labeled blocks, not multi-section layouts.

Provider responsibility: supply each section as a formatted atomic string with its own header. Template owns the overall layout and ordering of sections.

---

## FINAL COMPONENT SUMMARY TABLE

| # | Component | Source Prompts | Key Variables | Structure Visible? |
|---|---|---|---|---|
| C1 | `task_and_code.j2` | P1, P42 | task, code_files_block | YES — two blocks |
| C2 | `nudge_diagnostic.j2` | P2-P5, P10-P13 | diagnostic_text | YES — selected text |
| C3 | `nudge_guardrail.j2` | P6-P9, P14-P17, P18 | guardrail_text, hard_constraints_section | YES — constraint text + optional constraints |
| C4 | `nudge_reasoning.j2` | P19-P26, alignment | reasoning_text | YES — selected text |
| C5 | `nudge_scm.j2` | P27-P32 | scm_functions_text, scm_variables_text, scm_edges_text, scm_constraints_text, scm_invariants_text, scm_critical_* | YES — full causal analysis layout |
| C6 | `cge_stage.j2` | P33-P35 | task, code_files_block, contract_schema_text, contract_json, violations_text, cge_instruction | YES — task + code + contract fields + instruction |
| C7 | `leg_reduction.j2` | P36 | task, code_files_block | YES — schema + procedure |
| C8 | `classify_reasoning.j2` | P37 | failure_types, task, code, reasoning | YES — full classifier layout |
| C9 | `evaluate_reasoning.j2` | P38-P39 | code, error_*, test_reasons, reasoning, system_detected_section | YES — full evaluator layout |
| C10a | `retry_analysis.j2` | P40-P41 | analysis_instruction, analysis_context, analysis_schema | YES — instruction + context + schema |
| C10b | `retry_generation.j2` | P43-P44 | task, original_code, previous_code, test_output, critique_section, contract_section, hint_section, trajectory_section, fix_instruction | YES — full retry layout with labeled sections |
| C11 | `output_instruction_v1.j2` | P45 | (none) | YES — static schema |
| C12 | `output_instruction_v2.j2` | P46 | file_entries | YES — file-dict schema |

**Total: 14 components.**

---

## PROVIDER/TEMPLATE BOUNDARY CONFIRMATION

| Component | Template Owns | Provider Supplies |
|---|---|---|
| C1 | Task + code layout | `task` (raw), `code_files_block` (formatted files) |
| C2 | Nudge placement | `diagnostic_text` (selected text string) |
| C3 | Guardrail + constraints layout | `guardrail_text` (selected), `hard_constraints_section` (formatted bullets or empty) |
| C4 | Reasoning scaffold placement | `reasoning_text` (selected text string) |
| C5 | Full causal analysis section layout (Functions, State, Dependencies, Constraints, Invariants, Critical) | Individual formatted field strings (edges, constraints, etc.) |
| C6 | Task + code + contract fields layout | `contract_schema_text`, `contract_json`, `violations_text` (each atomic), `cge_instruction` (short directive from registry) |
| C7 | LEG schema + procedure + rules | `task`, `code_files_block` |
| C8 | Classifier role + inputs + rules + output format | `failure_types`, `task`, `code`, `reasoning` (each atomic, truncated by provider) |
| C9 | Evaluator role + inputs + phases + rules + output format | Atomic strings, `system_detected_section` (empty or one line) |
| C10a | Instruction + context + schema layout | `analysis_instruction`, `analysis_context`, `analysis_schema` (each atomic) |
| C10b | Full retry layout with section headers | `task`, `original_code`, `previous_code`, `test_output` (atomic), labeled sections (formatted with headers or empty) |
| C11 | V1 JSON schema | (none) |
| C12 | V2 file-dict schema | `file_entries` |

**Confirmation:**
- No component is a pure pass-through wrapper around a single variable
- All multi-section structure lives in templates
- All providers supply atomic data values, not prompt layouts
- C5 (SCM) now shows full section structure in the template, not in the provider
- C6 (CGE) uses explicit fields, not an opaque instruction block
- C10a/C10b split retry into analysis vs generation with visible structure in each

---

## FINAL COUNT

- **14 structural `.j2` components**
- **25 nudge text entries** in `registry.yaml`
- **3 CGE instruction entries** in `registry.yaml`
- **0 prompt layout logic in providers**

---

*End of manifest v3. Awaiting approval before extraction.*
