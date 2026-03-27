# Prompt System Redesign — Architecture Document v1

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation

---

## SECTION 1 — CURRENT SYSTEM FAILURE ANALYSIS

### F1: Seven independent prompt construction paths

Prompts are built in 7 uncoordinated locations:

1. `execution.py:build_prompt()` — 18-branch if/elif dispatches to nudge operators
2. `contract.py` — 3 functions build CGE prompts with inline f-strings
3. `leg_reduction.py` — 1 function builds LEG prompt with inline schema
4. `retry_harness.py` — 2 builder functions + 2 secondary call prompts
5. `evaluator.py:llm_classify()` — format-fills a constant string
6. `leg_evaluator.py:evaluate_reasoning()` — format-fills 2 constant strings
7. `llm.py:call_model()` — silently appends output instruction (V1/V2/none)

Each path assembles prompts using ad-hoc f-string concatenation. There is no shared assembly logic, no common validation, and no shared logging of what components were used.

### F2: Implicit output instruction coupling

`call_model()` appends `_JSON_OUTPUT_INSTRUCTION_V1` or `_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE` to every prompt UNLESS the caller passes `raw=True`. This creates invisible coupling:

- Callers must know when to set `raw=True` (LEG, contract elicit, classifier)
- Forgetting `raw=True` on a new prompt corrupts output with conflicting schema instructions
- The output instruction is chosen by `call_model` based on global config, not per-prompt intent
- The parser expects the output format that matches the instruction — if they drift, parsing breaks

### F3: Dead template system

A complete Jinja2 template system exists (`templates.py`, `templates/*.jinja2`) with content-hashing and strict validation. It is registered, tested, and unused. All runtime prompt construction uses Python f-strings in individual modules. The templates and the f-strings contain near-identical text — two sources of "truth" that will inevitably diverge.

### F4: Duplicated nudge variants

Diagnostic and guardrail nudges exist in two parallel sets:
- 4 case-specific variants in `prompts.py` (reference specific function names)
- 4 generic variants in `nudges/core.py` (reference general patterns)

The router (`nudges/router.py`) decides which variant to use based on a hard-coded per-case mapping. This mapping is not in config, not in case metadata, and not discoverable without reading the router source.

### F5: No prompt identity

After a run, there is no record of:
- Which template or function built the prompt
- Which nudge operator was selected
- Which output instruction was appended
- What truncation was applied (classifier)
- What SCM data was fetched (SCM conditions)

The call logger captures the final assembled string, but not the assembly provenance. This means: given a prompt in the logs, you cannot determine which code path produced it without re-running the experiment and comparing strings.

### F6: Condition impurity

Conditions are not pure transformations. Some conditions:
- Modify the prompt text (nudges) — pure
- Change the output schema (LEG) — impure, changes parsing
- Introduce multi-step execution flows (CGE: 3 calls) — impure, changes control flow
- Add retry loops (retry_*) — impure, changes execution structure
- Use a different parser (LEG: `parser="leg"`) — impure, changes downstream processing

A "condition" currently means "an arbitrary behavioral variant" rather than "a prompt transformation." This makes conditions non-composable and non-comparable.

### F7: Truncation is invisible

The classifier prompt truncates `task`, `code`, and `reasoning` based on config limits. This happens silently inside `llm_classify()`. The truncated text — which is what the classifier actually judges — is not logged. The call logger captures the final prompt (which contains truncated inputs), but there is no record of what was cut.

### F8: Format-parse tight coupling

Each prompt implicitly declares an output format by its instruction text:
- V1 prompts → parser expects `{"reasoning": ..., "plan": ..., "code": ...}`
- V2 prompts → parser expects `{"reasoning": ..., "files": {...}}`
- LEG prompts → parser expects `{"bug_diagnosis": ..., "revision_history": ..., "code": ...}`
- Classifier → parser expects `YES/NO ; FAILURE_TYPE`
- Critique → parser expects `{"failure_type": ..., "root_cause": ...}`

If any prompt instruction changes the expected output format without updating the corresponding parser, evaluation silently degrades (raw_fallback) or crashes.

---

## SECTION 2 — CORE ABSTRACTIONS

### A1: PromptComponent

**Responsibility:** One logical block of text within a prompt.

**Fields:**
- `name` — unique identifier (e.g., `"task_block"`, `"nudge_diagnostic_dependency"`, `"output_v2"`)
- `content` — the text string (with `{variable}` placeholders)
- `required_variables` — set of variable names this component needs
- `content_hash` — SHA-256 of `content` (computed once at load time)

**Invariants:**
- Content is immutable after load. No runtime modification.
- Every placeholder in `content` must appear in `required_variables`.
- A component with no placeholders has `required_variables = {}`.

**NOT allowed to:**
- Contain logic (if/else, loops)
- Reference other components
- Import anything
- Know about conditions, models, or execution

### A2: PromptSpec

**Responsibility:** A complete, ordered recipe for assembling one prompt. Declares which components to use and in what order.

**Fields:**
- `name` — identifier (e.g., `"baseline_generation"`, `"leg_reduction_generation"`, `"classify_reasoning"`)
- `components` — ordered list of component names
- `output_format` — one of: `"v1"`, `"v2"`, `"raw"`, `"leg_schema"` (determines which output instruction component, if any, is appended)
- `parser` — one of: `"standard"`, `"leg"`, `"raw_text"`, `"raw_json"` (declares which parser to use on the response)

**Invariants:**
- All named components must exist in the PromptRegistry.
- `output_format` determines which output instruction component is appended (or none for `"raw"`). This is explicit — not hidden inside `call_model`.
- `parser` is a declaration, not logic. It tells the evaluation pipeline which parser to invoke.
- A PromptSpec is immutable after construction.

**NOT allowed to:**
- Contain text
- Contain logic
- Reference models or cases
- Be modified at runtime

### A3: PromptRegistry

**Responsibility:** The single source of truth for all components and specs. Everything is loaded once at startup and frozen.

**Contents:**
- All PromptComponents (loaded from text files)
- All PromptSpecs (loaded from a manifest YAML)
- Content hashes for every component

**Operations:**
- `get_component(name) → PromptComponent` — fails loud if not found
- `get_spec(name) → PromptSpec` — fails loud if not found
- `get_hash(component_name) → str` — content hash for logging
- `list_specs() → list[str]` — all registered spec names
- `validate()` — checks all specs reference existing components, all components have valid placeholders

**Invariants:**
- Populated exactly once at startup (before any LLM calls).
- Immutable after initialization.
- Every component referenced by any spec must exist.
- No component may be registered twice.

**NOT allowed to:**
- Build prompts (that is `assemble_prompt`'s job)
- Know about conditions or cases
- Modify component content
- Be re-initialized

### A4: Condition

**Responsibility:** A pure transformation that maps one PromptSpec to another PromptSpec.

**Signature:** `condition_name → (base_spec) → modified_spec`

**What a condition can do:**
- Add a component (e.g., append a nudge component)
- Replace a component (e.g., swap output instruction)
- Change `output_format` or `parser` (explicitly, for conditions like LEG)

**What a condition CANNOT do:**
- Modify component text
- Introduce new variables
- Make LLM calls
- Change execution flow (no multi-step logic)

**How multi-step conditions (CGE, retry) are handled:**

CGE and retry are NOT conditions. They are **execution strategies** that invoke multiple PromptSpecs in sequence. A CGE execution strategy uses three PromptSpecs: `cge_elicit`, `cge_code`, `cge_retry`. Each is a standalone spec with its own components, output format, and parser. The execution strategy orchestrates the sequence; the prompt system just builds each one independently.

This separation is critical: a "condition" transforms a prompt. An "execution strategy" orchestrates multiple prompts. They are different abstractions and must not be merged.

---

## SECTION 3 — PROMPT BUILD PIPELINE

### Step-by-step flow for every LLM call:

```
1. RESOLVE SPEC
   Input: condition_name, stage (generation / classification / critique / ...)
   Action: Look up base PromptSpec from registry. Apply condition transformation.
   Output: Final PromptSpec (list of component names + output_format + parser)
   Validation: All component names exist in registry.

2. COLLECT VARIABLES
   Input: case dict, model name, execution state
   Action: Build a flat dict of all available variables:
     task, code_files_block, failure_types, contract_json, violations_text, ...
   Output: PromptContext dict
   Validation: None yet (validated in step 4).

3. RESOLVE OUTPUT INSTRUCTION
   Input: PromptSpec.output_format
   Action: If output_format is "v1" → append "output_v1" component.
           If output_format is "v2" → append "output_v2" component.
           If output_format is "raw" → append nothing.
           If output_format is "leg_schema" → append nothing (schema is in the prompt body).
   Output: Final ordered component list.
   Validation: output_format is a known value.

4. ASSEMBLE
   Input: Ordered component list + PromptContext dict
   Action: For each component:
     a. Retrieve component from registry
     b. Check required_variables ⊆ PromptContext.keys()
     c. Format: component.content.format(**context)
     d. Append to parts list
   Output: parts list (list of strings)
   Validation: Missing variable → fatal error (not silent default).

5. JOIN
   Input: parts list
   Action: "\n\n".join(parts) → final prompt string
   Output: Final prompt string + assembly manifest

6. LOG
   Input: Final prompt string + assembly manifest
   Action: Record to call context:
     - spec_name
     - component_names (ordered)
     - component_hashes (ordered)
     - variable_names_used
     - output_format
     - parser
     - final_prompt_hash
   Output: Logged. Prompt string passed to call_model.

7. CALL
   Input: Final prompt string, model name
   Action: call_model(prompt, model, raw=True)
   Note: call_model ALWAYS receives raw=True. The output instruction is already
         in the prompt (or not, for raw format). call_model no longer appends anything.
   Output: Response string.
```

**Critical change from current system:** `call_model()` loses its output instruction logic entirely. It becomes a thin wrapper around the API call. The output instruction is a component like any other, assembled in step 3. This eliminates the `raw=True` coupling.

### Data flow diagram:

```
config.yaml
  → condition name
  → PromptRegistry.get_spec(condition, stage)
  → condition transformation (if any)
  → final PromptSpec

case dict + execution state
  → PromptContext dict

PromptSpec + PromptContext
  → assemble_prompt()
  → (final_string, manifest)

manifest → call_logger context
final_string → call_model(prompt, model, raw=True)
```

---

## SECTION 4 — CONDITION SYSTEM REDESIGN

### Current conditions and their classification:

| Condition | Current behavior | Classification | New design |
|-----------|-----------------|----------------|------------|
| `baseline` | No modification | **Pure** | Identity transformation (returns base spec unchanged) |
| `diagnostic` | Appends case-specific or generic nudge text | **Pure** | Adds `nudge_diagnostic_{operator}` component to spec |
| `guardrail` | Appends case-specific or generic constraint text | **Pure** | Adds `nudge_guardrail_{operator}` component to spec |
| `guardrail_strict` | Appends hard constraints from case metadata | **Pure** | Adds `nudge_guardrail_strict` component (with `hard_constraints` variable) |
| `counterfactual` | Appends counterfactual check text | **Pure** | Adds `nudge_counterfactual` component |
| `reason_then_act` | Appends two-step reasoning scaffold | **Pure** | Adds `nudge_reason_then_act` component |
| `self_check` | Appends verification step | **Pure** | Adds `nudge_self_check` component |
| `counterfactual_check` | Appends failure analysis | **Pure** | Adds `nudge_counterfactual_check` component |
| `test_driven` | Appends behavioral requirements | **Pure** | Adds `nudge_test_driven` component |
| `structured_reasoning` | Appends step-by-step scaffold | **Pure** | Adds `nudge_structured_reasoning` component |
| `free_form_reasoning` | Appends minimal "think carefully" | **Pure** | Adds `nudge_free_form` component |
| `branching_reasoning` | Appends tree-of-thought structure | **Pure** | Adds `nudge_branching` component |
| `scm_descriptive` | Appends SCM edges from case data | **Pure** | Adds `nudge_scm_descriptive` component (with SCM variables) |
| `scm_constrained` | Appends SCM + verification steps | **Pure** | Adds `nudge_scm_constrained` component |
| `scm_constrained_evidence` | Appends full evidence catalog | **Pure** | Adds `nudge_scm_evidence` component |
| `scm_constrained_evidence_minimal` | Appends critical evidence subset | **Pure** | Adds `nudge_scm_evidence_minimal` component |
| `evidence_only` | Appends catalogs without edges | **Pure** | Adds `nudge_evidence_only` component |
| `length_matched_control` | Appends token-matched filler | **Pure** | Adds `nudge_length_control` component |
| `leg_reduction` | Different prompt, different schema, different parser | **Impure** | Separate PromptSpec: `leg_reduction_generation`. Spec declares `output_format="raw"`, `parser="leg"`. NOT a transformation of baseline — it is a different spec entirely. |
| `contract_gated` | 3 sequential LLM calls with different prompts | **Impure** | Execution strategy, not a condition. Uses 3 specs: `cge_elicit`, `cge_code`, `cge_retry`. |
| `repair_loop` | 2 sequential attempts with error feedback | **Impure** | Execution strategy. Uses specs: `generation` (attempt 1) + `repair_feedback` (attempt 2). |
| `retry_*` (4 variants) | Multi-iteration loop with critique, contract, adaptive hints | **Impure** | Execution strategy. Uses specs: `retry_initial`, `retry_feedback`, `retry_critique`, `retry_contract_elicit`. |

### Summary of redesign:

- **16 conditions** remain as pure transformations (add a nudge component to base spec)
- **1 condition** (LEG) becomes a distinct PromptSpec (not a transformation of baseline)
- **6 conditions** (CGE, repair_loop, retry_*) become execution strategies that compose multiple PromptSpecs

### Per-case nudge selection:

Currently, `nudges/router.py` hard-codes which operator applies to which case_id. In the new system, operator selection is config-driven:

```yaml
conditions:
  diagnostic:
    nudge_component: "nudge_diagnostic_{failure_mode}"
```

The `{failure_mode}` variable is resolved from `case["failure_mode"]` at assembly time. No hard-coded per-case mapping. The generic/specific distinction disappears: there is one nudge component per failure mode, loaded from a text file.

---

## SECTION 5 — LOGGING + REPRODUCIBILITY

### What must be logged (per LLM call):

```json
{
  "call_id": 108,
  "prompt_assembly": {
    "spec_name": "baseline_generation",
    "condition": "diagnostic",
    "components": [
      {"name": "task_block", "hash": "a3f2..."},
      {"name": "code_files_block", "hash": "7b1c..."},
      {"name": "nudge_diagnostic_hidden_dependency", "hash": "e9d4..."},
      {"name": "output_v2", "hash": "1f0a..."}
    ],
    "output_format": "v2",
    "parser": "standard",
    "variables_used": ["task", "code_files_block", "file_entries"],
    "final_prompt_hash": "d41d..."
  },
  "prompt_raw": "... (full text) ...",
  "response_raw": "... (full text) ...",
  ...
}
```

### Exact reconstruction from logs:

Given `prompt_assembly`, an engineer can:

1. Look up each component by name in the registry
2. Verify each component's content hash matches the logged hash
3. If hashes match → the template text has not changed since the run
4. If hashes differ → the template was modified after the run (flag as non-reproducible)
5. The `variables_used` list + the `prompt_raw` together fully specify what happened

Given only `prompt_raw` (without assembly metadata):

1. The full prompt string is sufficient to reproduce the exact API call
2. But you cannot determine provenance (which components, which condition) without assembly metadata

**Both are logged.** The assembly metadata enables provenance tracking. The raw string enables exact reproduction.

### Classifier-specific logging:

The classifier applies truncation. The assembly manifest must include:

```json
{
  "truncation": {
    "task_original_length": 1200,
    "task_truncated_to": 800,
    "code_original_length": 4500,
    "code_truncated_to": 2000,
    "reasoning_original_length": 3000,
    "reasoning_truncated_to": 1000
  }
}
```

This makes truncation visible and auditable.

---

## SECTION 6 — MIGRATION PLAN

### Phase 0: Extract component text files (NO behavior change)

1. For every prompt string currently in Python source, create a text file in `prompts/` with identical content.
2. Verify byte-for-byte equivalence between text file and Python source.
3. No runtime changes. Existing code still uses Python strings.

**Deliverable:** `prompts/` directory with all component text files. Verification script that diffs Python source against text files.

### Phase 1: Build PromptRegistry + assemble_prompt (parallel path)

1. Implement PromptRegistry: loads components from `prompts/`, loads specs from `prompts/manifest.yaml`.
2. Implement `assemble_prompt(spec_name, context)` function.
3. Add a validation mode: for every LLM call, assemble the prompt BOTH ways (old path + new path) and assert string equality.
4. Run a full ablation in validation mode. Every call must produce identical prompts from both paths.

**Deliverable:** New prompt system running in shadow mode alongside existing code. Zero divergence confirmed.

### Phase 2: Switch call sites (one at a time)

1. Start with `baseline` condition (simplest). Replace `build_prompt(case, "baseline")` with `assemble_prompt("baseline_generation", context)`.
2. Run ablation. Confirm results identical.
3. Repeat for each condition, one at a time. After each switch, run the condition and confirm.
4. After all generation prompts migrated, switch classifier prompt.
5. After classifier, switch retry/CGE prompts.

**Deliverable:** All call sites migrated. Old prompt functions are dead code.

### Phase 3: Delete old code

1. Remove `build_prompt()` and its 18-branch if/elif.
2. Remove all inline prompt constants (`_CLASSIFY_PROMPT`, nudge strings, etc.).
3. Remove dead Jinja2 template system.
4. Remove `nudges/router.py` per-case mapping (replaced by config + failure_mode variable).

**Deliverable:** Single prompt construction path. Zero duplication.

### Phase 4: Remove output instruction from call_model

1. Make `call_model` always behave as `raw=True`. Remove the output instruction append logic.
2. Output instruction is now a component in every PromptSpec that needs one.
3. Remove `_JSON_OUTPUT_INSTRUCTION_V1`, `_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE` from `llm.py`.
4. Remove `raw` parameter from `call_model` signature.

**Deliverable:** `call_model` is a thin API wrapper. No prompt logic.

### Phase 5: Enhance logging

1. Add assembly manifest to call logger (component names, hashes, variables).
2. Add truncation logging for classifier calls.
3. Verify reconstruction: given logged manifest + registry, reproduce exact prompt string.

**Deliverable:** Full observability. Prompt provenance in every call log.

### Validation at every phase:

- Run the same single case (`alias_config_a`, baseline + leg_reduction) before and after each phase
- Compare `calls_flat.txt` output byte-for-byte
- If any divergence: stop, investigate, fix before proceeding

---

## SECTION 7 — FAILURE MODES OF THIS DESIGN

### FM1: Variable name mismatch

A component requires `{code_files_block}` but the context provides `{code_block}`. Assembly fails at step 4 with a missing variable error.

**Mitigation:** `validate()` at startup checks that all component variables can be satisfied by the union of all possible context variables. But some variables are stage-specific (e.g., `contract_json` only exists for CGE). Validation must be per-spec, not global.

**Residual risk:** A new variable added to a component but not to the context builder. Caught at first run, not at startup.

### FM2: Component ordering matters

Components are concatenated in order. Swapping the order of `nudge` and `output_instruction` changes the prompt semantics (the nudge should come before the output instruction).

**Mitigation:** PromptSpec declares explicit ordering. But there is no validation that ordering is "correct" — only that it is deterministic.

**Residual risk:** A misconfigured spec puts the output instruction before the task block. The system will build and log this prompt faithfully — it will just produce bad results.

### FM3: Hash collision or staleness

Component hashes are computed at startup. If someone edits a text file mid-run, the logged hash no longer matches the file on disk.

**Mitigation:** Hashes are computed once at startup and frozen. The file on disk may change, but the in-memory content (and its hash) are what the prompt actually used. Reconstruction compares logged hash against current file hash — if they differ, the log warns "component modified since run."

**Residual risk:** None for correctness. Only for post-hoc reconstruction.

### FM4: Execution strategies bypass the prompt system

CGE and retry are execution strategies that call `assemble_prompt` multiple times. If a developer adds a new execution strategy that constructs prompts inline (reverting to the current pattern), the single-path invariant is violated.

**Mitigation:** The enforcement tests (like `test_canonical_pipeline.py`) must be extended to verify: no call to `call_model` exists outside execution strategies, and all execution strategies use `assemble_prompt`.

**Residual risk:** Enforcement tests can be bypassed. Code review is the final defense.

### FM5: Context variable explosion

As the system grows, `PromptContext` accumulates more variables. Some variables are only relevant to specific stages. Passing a 30-key context dict to every assembly call is noisy.

**Mitigation:** Each component declares `required_variables`. Assembly only validates and uses those. Extra variables in the context are ignored. This is intentional — a permissive context with strict component requirements.

**Residual risk:** A typo in a variable name silently goes unused (the component didn't need it). No data loss, but wasted computation.

### FM6: Migration regression window

During Phase 2, some conditions use the new path and some use the old path. If a bug is introduced in the new path, it affects only migrated conditions. This creates a period where different conditions have different prompt construction reliability.

**Mitigation:** Phase 1's shadow validation mode catches divergence. Phase 2 migrates one condition at a time with full ablation validation. The window is narrow and monitored.

**Residual risk:** A subtle divergence (e.g., trailing whitespace difference) passes string comparison but affects model behavior. Unlikely but possible with tokenization-sensitive models.

### FM7: Manifest YAML becomes a single point of failure

All prompt configuration lives in `prompts/manifest.yaml`. A syntax error, missing entry, or merge conflict in this file breaks the entire system.

**Mitigation:** `validate()` at startup catches all structural errors before any LLM calls. The manifest is YAML (human-readable, diffable, mergeable). Content is in separate text files, so manifest conflicts are structural only (which spec uses which components), not content conflicts.

**Residual risk:** Standard YAML risks (indentation errors, merge conflicts). Same risk as the existing `configs/*.yaml` files.

---

*End of design document. No implementation performed.*
