# Prompt Extraction Manifest — Phase 1A

**Date:** 2026-03-27
**Status:** MANIFEST ONLY — awaiting approval before extraction
**Total source prompts discovered:** 46
**Proposed component count:** 14

---

## FULL PROMPT INVENTORY

---

### PROMPT 1
**SOURCE:** `prompts.py:199-204`, function `build_base_prompt()`
**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Minimal baseline: task description + formatted code files block
**VARIABLES:** `task`, `code_files_block`
**PROPOSED COMPONENT:** `task_and_code.j2`
**REUSE GROUP:** G1
**NOTES:** Foundation for ALL generation prompts. Every condition starts here.

---

### PROMPTS 2–5 (case-specific diagnostic nudges)
**SOURCE:** `prompts.py:12-94`, dict `DIAGNOSTIC_NUDGES`
- P2: `HIDDEN_DEPENDENCY` (lines 12-36)
- P3: `TEMPORAL_CAUSAL_ERROR` (lines 38-54)
- P4: `INVARIANT_VIOLATION` (lines 56-73)
- P5: `STATE_SEMANTIC_VIOLATION` (lines 75-94)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Case-specific diagnostic nudges referencing specific function names and state variables
**VARIABLES:** none (static text, appended to base)
**PROPOSED COMPONENT:** `nudge_diagnostic_case_specific.j2` (one file with `{{ nudge_text }}` variable, actual text comes from case metadata or selection mapping)
**REUSE GROUP:** G2a
**NOTES:** These 4 are structurally identical (diagnostic text appended to base). Differ only in content. Will become 4 separate text entries in the selection mapping, all using the same structural component.

---

### PROMPTS 6–9 (case-specific guardrail nudges)
**SOURCE:** `prompts.py:100-195`, dict `GUARDRAIL_NUDGES`
- P6: `HIDDEN_DEPENDENCY` (lines 100-121)
- P7: `TEMPORAL_CAUSAL_ERROR` (lines 123-144)
- P8: `INVARIANT_VIOLATION` (lines 146-169)
- P9: `STATE_SEMANTIC_VIOLATION` (lines 171-195)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Case-specific mandatory constraint text
**VARIABLES:** none (static text)
**PROPOSED COMPONENT:** `nudge_guardrail_case_specific.j2` (same pattern as G2a)
**REUSE GROUP:** G2b
**NOTES:** Same structure as diagnostic nudges. 4 text variants, one structural component.

---

### PROMPTS 10–13 (generic diagnostic operators)
**SOURCE:** `nudges/core.py:14-122`
- P10: `_dependency_check_diagnostic` (lines 14-31)
- P11: `_invariant_guard_diagnostic` (lines 41-58)
- P12: `_temporal_robustness_diagnostic` (lines 68-86)
- P13: `_state_lifecycle_diagnostic` (lines 96-115)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Generic diagnostic reasoning scaffolds (not case-specific)
**VARIABLES:** none (static text appended to base)
**PROPOSED COMPONENT:** same as G2a — `nudge_diagnostic_case_specific.j2`. These are the generic-tier fallback texts in the selection mapping.
**REUSE GROUP:** G2a
**NOTES:** Near-duplicates of P2–P5 at a higher abstraction level. The selection engine picks case-specific (P2-P5) or generic (P10-P13) based on override ladder. All use the same structural component.

---

### PROMPTS 14–17 (generic guardrail operators)
**SOURCE:** `nudges/core.py:129-249`
- P14: `_dependency_check_guardrail` (lines 129-150)
- P15: `_invariant_guard_guardrail` (lines 160-183)
- P16: `_temporal_robustness_guardrail` (lines 193-216)
- P17: `_state_lifecycle_guardrail` (lines 226-249)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Generic mandatory constraint text
**VARIABLES:** none
**PROPOSED COMPONENT:** same as G2b — `nudge_guardrail_case_specific.j2`. Generic-tier fallbacks.
**REUSE GROUP:** G2b
**NOTES:** Same relationship to P6-P9 as P10-P13 have to P2-P5.

---

### PROMPT 18 (strict guardrail / hard constraints)
**SOURCE:** `nudges/core.py:263-278`, function `build_strict_guardrail()`
**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** "HARD CONSTRAINTS" header + bulleted list from case metadata
**VARIABLES:** `hard_constraints_bullets`
**PROPOSED COMPONENT:** `nudge_hard_constraints.j2`
**REUSE GROUP:** G3
**NOTES:** Structurally unique — uses dynamic hard_constraints from case metadata.

---

### PROMPTS 19–23 (generic reasoning operators)
**SOURCE:** `nudges/core.py:285-447`
- P19: `_counterfactual_generic` (lines 285-307)
- P20: `_reason_then_act_generic` (lines 321-344)
- P21: `_self_check_generic` (lines 358-381)
- P22: `_counterfactual_check_generic` (lines 395-414)
- P23: `_test_driven_generic` (lines 428-447)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Reasoning intervention nudges (counterfactual, reason-then-act, self-check, etc.)
**VARIABLES:** none (static text)
**PROPOSED COMPONENT:** `nudge_reasoning_intervention.j2` (one structural component, `{{ nudge_text }}` variable). Each intervention becomes a separate text file loaded by the selection mapping.
**REUSE GROUP:** G4
**NOTES:** All 5 are structurally identical: static text appended to base prompt. Differ only in content. Rather than 5 separate `.j2` files, one structural component + 5 text files in the selection mapping.

Actually — reconsideration: these 5 are each unique reasoning strategies with no selection logic (no case-specific variants). They should be 5 separate `.j2` files for clarity. Revising.

**REVISED PROPOSED COMPONENTS:**
- `nudge_counterfactual.j2`
- `nudge_reason_then_act.j2`
- `nudge_self_check.j2`
- `nudge_counterfactual_check.j2`
- `nudge_test_driven.j2`

**REVISED REUSE GROUP:** G4a through G4e (each unique, no selection variants)

Wait — this conflicts with the <20 component target. Let me reconsider. These 5 + the 3 reasoning prompts (P24-P26) + the diagnostic/guardrail nudges all share the same structural role: "text appended to base prompt in the nudge slot." They could all be individual text files loaded into a single `nudge_block.j2` component that just renders `{{ nudge_text }}`. The selection engine resolves which text to load.

**FINAL DECISION:** One structural component `nudge_block.j2` with variable `{{ nudge_text }}`. All 22 nudge variants (P2-P17, P19-P23, P24-P26) become text entries in the selection mapping. This is the v7 architecture's intent: transforms append components to the nudge stack slot, and the component just renders the selected text.

**FINAL PROPOSED COMPONENT:** `nudge_block.j2`
**FINAL REUSE GROUP:** G2 (all nudges)

---

### PROMPTS 24–26 (reasoning interface modes)
**SOURCE:** `reasoning_prompts.py:10-52`
- P24: `build_structured_reasoning` (lines 10-20)
- P25: `build_free_form_reasoning` (lines 23-28)
- P26: `build_branching_reasoning` (lines 31-52)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Reasoning scaffold variants
**VARIABLES:** none (static text)
**PROPOSED COMPONENT:** `nudge_block.j2` (same as G2)
**REUSE GROUP:** G2
**NOTES:** Same structure as all other nudges — static text in the nudge slot.

---

### PROMPTS 27–32 (SCM prompts)
**SOURCE:** `scm_prompts.py:9-218`
- P27: `build_scm_descriptive` (lines 9-30)
- P28: `build_scm_constrained` (lines 33-63)
- P29: `build_scm_constrained_evidence` (lines 66-130)
- P30: `build_scm_constrained_evidence_minimal` (lines 133-164)
- P31: `build_evidence_only` (lines 167-195)
- P32: `build_length_matched_control` (lines 198-218)

**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** SCM-derived causal analysis scaffolds with varying evidence levels
**VARIABLES:** `scm_edges_text`, `scm_constraints_text`, `scm_invariants_text`, `scm_functions_text`, `scm_variables_text`, `scm_critical_constraint`, `scm_critical_evidence` (from SCMContextProvider)
**PROPOSED COMPONENT:** These CANNOT share one component because they have different structures and different variables. Each needs its own `.j2` file. However, the structural pattern is the same (text appended to base in nudge slot). They are 6 separate nudge text templates.
**PROPOSED COMPONENTS:**
- `nudge_scm_descriptive.j2`
- `nudge_scm_constrained.j2`
- `nudge_scm_evidence.j2`
- `nudge_scm_evidence_minimal.j2`
- `nudge_evidence_only.j2`
- `nudge_length_control.j2`

**REUSE GROUP:** G5 (SCM family — each unique due to different variables)
**NOTES:** Unlike the plain nudges (which are static text), SCM nudges require Jinja2 variables. They cannot be reduced to a single `nudge_block.j2` with `{{ nudge_text }}`. They need their own templates.

---

### PROMPTS 33–35 (contract-gated execution)
**SOURCE:** `contract.py:154-215`
- P33: `build_contract_prompt` (lines 154-168)
- P34: `build_code_from_contract_prompt` (lines 171-192)
- P35: `build_retry_prompt` (lines 195-215)

**TYPE:** role=agent, stage=contract_elicit / contract_code / contract_retry
**CONTENT SUMMARY:** Three CGE-stage prompts — elicit contract, generate code from contract, retry after violations
**VARIABLES:**
- P33: `task`, `code_files_block`, `contract_schema_text`
- P34: `task`, `code_files_block`, `contract_json`
- P35: `task`, `code_files_block`, `contract_json`, `violations_text`
**PROPOSED COMPONENTS:**
- `cge_elicit.j2`
- `cge_code.j2`
- `cge_retry.j2`

**REUSE GROUP:** G6 (CGE family — each unique)

---

### PROMPT 36 (LEG reduction)
**SOURCE:** `leg_reduction.py:44-128`, function `build_leg_reduction_prompt()`
**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Plan-verify-revise prompt with full JSON revision trace schema
**VARIABLES:** `task`, `code_files_block`
**PROPOSED COMPONENT:** `leg_reduction.j2`
**REUSE GROUP:** G7 (unique)
**NOTES:** Long template (~80 lines) with embedded JSON schema. Cannot be decomposed further without losing coherence.

---

### PROMPT 37 (classifier)
**SOURCE:** `evaluator.py:34-88`, constant `_CLASSIFY_PROMPT`
**TYPE:** role=classifier, stage=classify
**CONTENT SUMMARY:** Evaluate reasoning correctness + classify failure type
**VARIABLES:** `failure_types`, `task`, `code`, `reasoning`
**PROPOSED COMPONENT:** `classify_reasoning.j2`
**REUSE GROUP:** G8 (unique)

---

### PROMPTS 38–39 (LEG evaluator)
**SOURCE:** `leg_evaluator.py:27-93`
- P38: `_CRIT_LITE_BLIND_PROMPT` (lines 27-88)
- P39: `_CRIT_LITE_CONDITIONED_PROMPT` (lines 90-93)

**TYPE:** role=evaluator, stage=evaluate
**CONTENT SUMMARY:** LEG-specific reasoning evaluation (blind and conditioned variants)
**VARIABLES:** P38: `code`, `error_category`, `error_message`, `test_reasons`, `reasoning`. P39: same + `classifier_type`
**PROPOSED COMPONENT:** `evaluate_reasoning.j2` (one template with optional `{{ classifier_type }}` section, controlled by variable presence)
**REUSE GROUP:** G9
**NOTES:** P39 is P38 + one extra section. A single template with `{% if classifier_type is defined %}` would normally violate the "no control flow" rule. Instead: two separate templates — `evaluate_reasoning_blind.j2` and `evaluate_reasoning_conditioned.j2`. The conditioned version includes the extra section statically.

**REVISED COMPONENTS:**
- `evaluate_reasoning_blind.j2`
- `evaluate_reasoning_conditioned.j2`

---

### PROMPT 40 (critique)
**SOURCE:** `retry_harness.py:841-858`, function `_call_critique()`
**TYPE:** role=evaluator, stage=critique
**CONTENT SUMMARY:** Structured failure diagnosis for retry harness
**VARIABLES:** `code_under_test`, `test_output`
**PROPOSED COMPONENT:** `retry_critique.j2`
**REUSE GROUP:** G10 (unique)

---

### PROMPT 41 (retry contract elicit)
**SOURCE:** `retry_harness.py:878-887`, function `_elicit_contract()`
**TYPE:** role=agent, stage=contract_elicit
**CONTENT SUMMARY:** Lightweight intent elicitation before retry loop
**VARIABLES:** `task`
**PROPOSED COMPONENT:** `retry_contract_elicit.j2`
**REUSE GROUP:** G11 (unique)

---

### PROMPT 42 (retry initial)
**SOURCE:** `retry_harness.py:906-912`, function `_build_initial_prompt()`
**TYPE:** role=agent, stage=retry_initial
**CONTENT SUMMARY:** Base prompt + optional alignment extra
**VARIABLES:** `task`, `code_files_block` (reuses task_and_code.j2) + optional `alignment_extra`
**PROPOSED COMPONENT:** Reuses `task_and_code.j2` (G1). The alignment extra is a separate nudge component `nudge_alignment_extra.j2` appended via transform.
**REUSE GROUP:** G1 + G12

---

### PROMPT 43 (retry feedback)
**SOURCE:** `retry_harness.py:915-935`, function `_build_retry_prompt()`
**TYPE:** role=agent, stage=retry_feedback
**CONTENT SUMMARY:** Multi-section retry prompt with original code, previous attempt, test results, critique, contract, hint, trajectory
**VARIABLES:** `task`, `original_code`, `previous_code`, `test_output`, `critique_json`, `contract_json`, `adaptive_hint`, `trajectory_context`
**PROPOSED COMPONENT:** `retry_feedback.j2`
**REUSE GROUP:** G13 (unique)
**NOTES:** Most complex template. Many optional sections (critique, contract, hint, trajectory may be absent). These will be Jinja2 variables that render as empty string when not provided.

---

### PROMPT 44 (repair loop feedback)
**SOURCE:** `execution.py:613`, inline in `run_repair_loop()`
**TYPE:** role=agent, stage=generation
**CONTENT SUMMARY:** Appends "Your previous attempt FAILED with: {errors}" to the diagnostic prompt
**VARIABLES:** `error_reasons`
**PROPOSED COMPONENT:** `repair_feedback.j2`
**REUSE GROUP:** G14 (unique)

---

### PROMPTS 45–46 (output instructions)
**SOURCE:** `llm.py:14-53`
- P45: `_JSON_OUTPUT_INSTRUCTION_V1` (lines 14-29)
- P46: `_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE` (lines 32-45)

**TYPE:** role=other, stage=all (appended by call_model)
**CONTENT SUMMARY:** JSON output format instructions
**VARIABLES:** P45: none. P46: `file_entries`
**PROPOSED COMPONENTS:**
- `output_instruction_v1.j2`
- `output_instruction_v2.j2`

**REUSE GROUP:** G15 (output instructions)

---

## COMPONENT CONSOLIDATION TABLE

| # | Component Name | Used By (source prompts) | Variables | Description |
|---|---|---|---|---|
| 1 | `task_and_code.j2` | P1, P42 | `task`, `code_files_block` | Base prompt: task + formatted code files |
| 2 | `nudge_block.j2` | P2-P17, P19-P26 | `nudge_text` | Generic nudge wrapper — renders selected nudge text |
| 3 | `nudge_hard_constraints.j2` | P18 | `hard_constraints_bullets` | Hard constraints from case metadata |
| 4 | `nudge_scm_descriptive.j2` | P27 | `scm_edges_text`, `scm_failure_text` | SCM descriptive |
| 5 | `nudge_scm_constrained.j2` | P28 | `scm_edges_text`, `scm_constraints_text`, `scm_invariants_text` | SCM constrained |
| 6 | `nudge_scm_evidence.j2` | P29 | `scm_functions_text`, `scm_variables_text`, `scm_edges_text`, `scm_invariants_text`, `scm_critical_constraint`, `scm_constraints_text` | SCM full evidence |
| 7 | `nudge_scm_evidence_minimal.j2` | P30 | `scm_edges_text`, `scm_constraints_text`, `scm_invariants_text` | SCM minimal evidence |
| 8 | `nudge_evidence_only.j2` | P31 | `scm_functions_text`, `scm_variables_text`, `scm_constraints_text`, `scm_invariants_text` | Evidence only (no edges) |
| 9 | `nudge_length_control.j2` | P32 | none | Token-matched filler |
| 10 | `cge_elicit.j2` | P33 | `task`, `code_files_block`, `contract_schema_text` | CGE step 1 |
| 11 | `cge_code.j2` | P34 | `task`, `code_files_block`, `contract_json` | CGE step 2 |
| 12 | `cge_retry.j2` | P35 | `task`, `code_files_block`, `contract_json`, `violations_text` | CGE step 4 |
| 13 | `leg_reduction.j2` | P36 | `task`, `code_files_block` | LEG plan-verify-revise |
| 14 | `classify_reasoning.j2` | P37 | `failure_types`, `task`, `code`, `reasoning` | Reasoning classifier |
| 15 | `evaluate_reasoning_blind.j2` | P38 | `code`, `error_category`, `error_message`, `test_reasons`, `reasoning` | LEG blind evaluator |
| 16 | `evaluate_reasoning_conditioned.j2` | P39 | same + `classifier_type` | LEG conditioned evaluator |
| 17 | `retry_critique.j2` | P40 | `code_under_test`, `test_output` | Retry critique |
| 18 | `retry_contract_elicit.j2` | P41 | `task` | Retry contract elicit |
| 19 | `retry_feedback.j2` | P43 | `task`, `original_code`, `previous_code`, `test_output`, `critique_json`, `contract_json`, `adaptive_hint`, `trajectory_context` | Retry feedback |
| 20 | `repair_feedback.j2` | P44 | `error_reasons` | Repair loop attempt 2 |
| 21 | `nudge_alignment_extra.j2` | P42 (alignment mode) | none | Alignment emphasis for retry |
| 22 | `output_instruction_v1.j2` | P45 | none | V1 JSON output instruction |
| 23 | `output_instruction_v2.j2` | P46 | `file_entries` | V2 file-dict output instruction |

**Total: 23 components.**

---

## REDUNDANCY ANALYSIS

### Fully Redundant (will be merged)

| Group | Prompts | Current Files | Merged Into | How |
|---|---|---|---|---|
| Case-specific diagnostics + generic diagnostics | P2-P5 + P10-P13 | `prompts.py` + `nudges/core.py` | `nudge_block.j2` + 8 text entries in selection mapping | Selection engine picks case-specific or generic based on override ladder. One structural component. |
| Case-specific guardrails + generic guardrails | P6-P9 + P14-P17 | `prompts.py` + `nudges/core.py` | `nudge_block.j2` + 8 text entries in selection mapping | Same pattern. |

### Near-Duplicates (unified)

| Pair | Difference | Resolution |
|---|---|---|
| `_CRIT_LITE_BLIND_PROMPT` vs `_CRIT_LITE_CONDITIONED_PROMPT` | Conditioned adds one `## System-Detected Failure Type` section | Two separate templates. Conditioned includes the extra section statically. |
| `_CLASSIFY_PROMPT` vs `_CRIT_LITE_BLIND_PROMPT` | Different input structure, different output phrasing, same conceptual purpose | Two separate templates. They serve different stages (classifier vs evaluator). |
| `build_contract_prompt()` (contract.py) vs `_elicit_contract()` (retry_harness.py) | Same purpose (elicit intent), different schema, different context | Two separate templates. CGE contract has full schema; retry contract is lightweight. |

### Text Variants (selection-mapped, not duplicated)

22 nudge variants (P2-P17, P19-P26) become text entries in the selection mapping, all rendered through one `nudge_block.j2` component. Each text entry is stored as a separate file in `prompts/nudge_texts/` and loaded by the selection engine.

---

## REVISED COMPONENT COUNT

| Category | Components | Count |
|---|---|---|
| Base | `task_and_code.j2` | 1 |
| Nudge structural | `nudge_block.j2`, `nudge_hard_constraints.j2`, `nudge_alignment_extra.j2` | 3 |
| SCM nudges | 6 templates (each has unique variables) | 6 |
| CGE | 3 templates | 3 |
| LEG | 1 template | 1 |
| Classifier | 1 template | 1 |
| Evaluator | 2 templates (blind + conditioned) | 2 |
| Retry | 3 templates (critique, contract_elicit, feedback) | 3 |
| Repair | 1 template | 1 |
| Output instructions | 2 templates | 2 |
| **TOTAL** | | **23** |

Plus **22 nudge text files** in `prompts/nudge_texts/` (not `.j2` templates — plain text loaded by selection engine):
- 4 case-specific diagnostics
- 4 generic diagnostics
- 4 case-specific guardrails
- 4 generic guardrails
- 5 reasoning interventions (counterfactual, reason_then_act, self_check, counterfactual_check, test_driven)
- 3 reasoning modes (structured, free_form, branching)

**23 structural components + 22 nudge text files = 45 total files in `prompts/`.**

This exceeds the initial 10-15 target. Justification: the 22 nudge text files are not components — they are data loaded by the selection engine. The 23 actual `.j2` components are the structural templates. If we count only structural components, the number is 23. If we strictly insist on fewer, the only further reduction is merging the 6 SCM nudges into one parameterized template, which would require control flow (`{% if %}`) and violate the v7 architecture's "no control flow" rule.

**23 structural components is the honest minimum without violating architectural constraints.**

---

*End of manifest. Awaiting approval before extraction.*
