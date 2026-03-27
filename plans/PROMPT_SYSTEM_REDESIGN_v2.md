# Prompt System Redesign — Architecture Document v2

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** PROMPT_SYSTEM_REDESIGN.md (v1)

---

## SECTION A — Core Layered Abstractions

### A1: PromptComponent

**Responsibility:** One immutable block of template text, loaded from a file at startup.

**Fields:**
- `name` — unique identifier (e.g., `"task_block"`, `"nudge_diagnostic_hidden_dependency"`)
- `source_path` — file path relative to `prompts/` directory
- `template` — the Jinja2 template object (compiled at load time)
- `required_variables` — set of variable names extracted from the template AST at load time
- `content_hash` — SHA-256 of the raw source text (computed at load time, before compilation)

**Invariants:**
- Immutable after load. No runtime modification of template text.
- `required_variables` is computed by walking the Jinja2 AST, not by regex. This catches nested references and filters.
- A component with no variables has `required_variables = frozenset()`.
- `name` is globally unique within the registry. Duplicate registration is a fatal startup error.

**Forbidden behaviors:**
- No logic beyond Jinja2 variable substitution and whitespace control. No `{% if %}`, no `{% for %}`, no `{% macro %}`. If a template contains control flow, startup validation rejects it. (This constraint is already enforced by the existing `templates.py:preflight_validate_templates()` function.)
- No imports, no Python expressions, no filters beyond `|default`.
- No knowledge of conditions, models, cases, or execution.

---

### A2: PromptSpec

**Responsibility:** A static, registered recipe that declares the structure of a prompt family. Defines which components compose a prompt and what ResponseContract governs the expected output.

**Fields:**
- `name` — unique identifier (e.g., `"generation_baseline"`, `"classify_reasoning"`, `"cge_elicit"`)
- `components` — ordered list of component names (the default assembly order)
- `response_contract` — name of the ResponseContract that governs this spec's output
- `insertion_points` — named slots where PromptTransforms may inject or replace components (see Section C)

**Invariants:**
- Immutable after registration.
- All component names must exist in the PromptRegistry at startup validation.
- The named `response_contract` must exist in the registry at startup validation.
- `insertion_points` are named positions in the component list (e.g., `"after:task_block"`, `"before:output_instruction"`, `"replace:nudge_slot"`). Each slot name is unique within the spec.

**Forbidden behaviors:**
- No text content. A PromptSpec contains names, not strings.
- No runtime state. A PromptSpec does not know which case is running.
- No variable binding. Variables are provided by ContextProviders, not by the spec.

---

### A3: PromptTransform

**Responsibility:** A pure, stateless structural modification that maps a PromptSpec's component list to a new component list. This is how conditions modify prompts.

**Fields:**
- `name` — unique identifier (e.g., `"add_nudge_diagnostic"`, `"add_scm_evidence"`)
- `operations` — ordered list of operations, each one of:
  - `insert(component_name, at=insertion_point_name)` — adds a component at a named slot
  - `replace(component_name, at=insertion_point_name)` — replaces the component at a named slot
  - `remove(insertion_point_name)` — removes the component at a named slot (leaves slot empty)
- `required_context_variables` — additional variables that the injected components need (merged into context requirements)
- `compatible_specs` — set of PromptSpec names this transform is valid for (validated at startup)
- `compatible_contracts` — set of ResponseContract names this transform is valid with (validated at startup)

**Invariants:**
- Stateless and pure. Given the same PromptSpec, a transform always produces the same modified component list.
- A transform can only operate on insertion points declared by the PromptSpec. Referencing a nonexistent insertion point is a fatal error.
- Multiple transforms can be composed by applying them sequentially. Order of application is declared in config and is deterministic.

**Forbidden behaviors:**
- No text generation. A transform references component names, never raw text.
- No variable binding. Transforms declare what variables they need; they do not provide values.
- No LLM calls, no I/O, no side effects.
- No modification of the ResponseContract. If a transform needs a different contract, it is incompatible with the spec.

---

### A4: ResponseContract

**Responsibility:** Declares the full output agreement between a prompt and its parser. Owns the output instruction, parsing strategy, validation, and reconstruction policy.

**Fields:**
- `name` — unique identifier (e.g., `"json_v2_filedict"`, `"json_v1_code"`, `"raw_text_verdict"`, `"leg_structured"`, `"raw_json_critique"`)
- `output_instruction_component` — name of the PromptComponent that contains the output format instruction. `null` if the prompt embeds its own schema (LEG) or expects free-form response (critique).
- `parser_name` — identifier for which parser function processes the response (e.g., `"standard"`, `"leg"`, `"classify_verdict"`, `"raw_json"`)
- `expected_schema` — structural description of what the parser expects. Not enforced programmatically — exists for documentation and logging.
- `reconstruction_policy` — one of:
  - `"file_dict"` — response contains per-file content, requires reconstruction via `reconstruct_strict`
  - `"code_blob"` — response contains a single code string
  - `"metadata_only"` — response is classifier/critique output, no code reconstruction
- `validator_name` — optional post-parse validation function name (e.g., `"validate_file_dict_completeness"`, `null`)

**Invariants:**
- Immutable after registration.
- If `output_instruction_component` is not null, that component must exist in the registry.
- `parser_name` must map to a registered parser function.
- A ResponseContract is the SOLE authority on how to interpret a response. The prompt spec and transforms must not contain parsing logic.

**Forbidden behaviors:**
- No prompt text. The output instruction is a PromptComponent referenced by name.
- No parsing logic. The contract declares the parser; it does not implement it.
- No model-specific behavior. The same contract governs all models.

**Concrete contracts for the current system:**

| Contract Name | Output Instruction Component | Parser | Reconstruction | Notes |
|---|---|---|---|---|
| `json_v2_filedict` | `output_instruction_v2` | `standard` | `file_dict` | Default for generation |
| `json_v1_code` | `output_instruction_v1` | `standard` | `code_blob` | Legacy single-code format |
| `leg_structured` | `null` (schema is in prompt body) | `leg` | `code_blob` | LEG revision-trace format |
| `raw_text_verdict` | `null` | `classify_verdict` | `metadata_only` | Classifier: `YES/NO ; TYPE` |
| `raw_json_critique` | `null` | `raw_json` | `metadata_only` | Critique/contract elicit |
| `raw_json_contract` | `null` | `raw_json` | `metadata_only` | CGE contract elicitation |

---

### A5: ContextProvider

**Responsibility:** A named, scoped supplier of variables for prompt assembly. Each provider owns a specific domain of data and validates its own output.

**Concrete providers:**

| Provider Name | Owns | Lifecycle | Variables Provided |
|---|---|---|---|
| `TaskContextProvider` | Case metadata | Per-case | `task`, `case_id`, `failure_mode`, `hard_constraints` |
| `CodeContextProvider` | Code file formatting | Per-case | `code_files_block`, `file_paths`, `file_entries` |
| `SCMContextProvider` | Structural causal model data | Per-case (lazy-loaded from `scm_data/`) | `scm_edges_text`, `scm_constraints_text`, `scm_invariants_text`, `scm_functions_text`, `scm_variables_text`, `scm_critical_constraint`, `scm_critical_evidence` |
| `ClassifierContextProvider` | Classifier-specific inputs | Per-evaluation | `failure_types`, `classifier_task` (truncated), `classifier_code` (truncated), `classifier_reasoning` (truncated) |
| `RetryContextProvider` | Retry loop state | Per-iteration | `original_code`, `previous_code`, `test_output`, `critique_json`, `contract_json`, `adaptive_hint`, `trajectory_context` |
| `ContractContextProvider` | CGE contract data | Per-CGE-step | `contract_json`, `contract_schema_text`, `violations_text` |
| `ResponseContractContextProvider` | Output instruction variables | Per-spec | `file_entries` (for V2 instruction) |

**Each provider must:**
- Declare the set of variable names it provides.
- Validate that all provided variables are non-null and correctly typed before returning.
- Log the provenance of each variable: source, value hash, original length, truncated length (if applicable).
- Be stateless across calls (may hold case data for a single case's lifetime).

**Variable provenance record (per variable, per call):**

```
{
  "name": "classifier_reasoning",
  "provider": "ClassifierContextProvider",
  "value_hash": "a7f2...",
  "original_length": 3200,
  "truncated_to": 1000,
  "preview": "The bug is that create_config() assigns...",
  "source": "parsed.reasoning"
}
```

**Forbidden behaviors:**
- No prompt text generation. Providers supply values, not templates.
- No knowledge of which components will consume the variables.
- No LLM calls or I/O (except SCMContextProvider reading static data files).

---

### A6: ResolvedPrompt

**Responsibility:** The fully materialized runtime artifact for a single LLM call. Created by the assembly pipeline, consumed by the call executor and the logger. This is the bridge between the static registry and the runtime call.

**Fields:**
- `spec_name` — which PromptSpec was used
- `transforms_applied` — ordered list of transform names applied
- `response_contract_name` — which ResponseContract governs this call
- `final_components` — ordered list of `(component_name, content_hash)` tuples after transforms
- `bound_variables` — dict of `{var_name: VariableProvenance}` for every variable used
- `rendered_parts` — ordered list of rendered strings (one per component)
- `final_prompt` — the joined string sent to the LLM
- `final_prompt_hash` — SHA-256 of `final_prompt`
- `context_provider_versions` — dict of `{provider_name: provider_hash}` for each provider that contributed

**Invariants:**
- Created exactly once per LLM call.
- Immutable after creation.
- `final_prompt` is deterministic: same spec + same transforms + same variables = same string.
- `final_prompt_hash` uniquely identifies the exact prompt text.

**Forbidden behaviors:**
- No modification after creation.
- No LLM calls. The ResolvedPrompt is an artifact, not an actor.
- No parsing logic.

---

### A7: ExecutionStrategy

**Responsibility:** Controls the number, ordering, and dependencies of LLM calls for a single case evaluation. An execution strategy is NOT a condition and NOT a prompt transform.

**Concrete strategies:**

| Strategy Name | LLM Calls | Specs Used | Control Flow |
|---|---|---|---|
| `single_call` | 1 generation + 1 classifier | `generation_{condition}`, `classify_reasoning` | Linear |
| `repair_loop` | 1-2 generation + 1-2 classifier | `generation_diagnostic`, `repair_feedback`, `classify_reasoning` | Attempt 1, if fail: attempt 2 with error feedback |
| `contract_gated` | 2-3 generation + 1 classifier | `cge_elicit`, `cge_code`, `cge_retry` (optional), `classify_reasoning` | Elicit → code → gate → optional retry → evaluate |
| `retry_harness` | 1-K generation + 0-K critique + 1 classifier | `retry_initial`, `retry_feedback`, `retry_critique`, `classify_reasoning` | Loop with stopping conditions |

**Invariants:**
- An execution strategy declares which PromptSpecs it uses. All must exist in the registry.
- An execution strategy does not construct prompts. It calls `assemble_prompt(spec_name, transforms, context)` for each LLM call.
- The classifier call is always the same spec (`classify_reasoning`), regardless of strategy.

**Forbidden behaviors:**
- No inline prompt text.
- No modification of PromptSpecs or components.
- No bypassing of `assemble_prompt`.

---

## SECTION B — Resolution Pipeline

### Complete deterministic pipeline for every LLM call:

```
STEP 1: STRATEGY SELECTION
  Input:  condition name (from config)
  Action: Map condition → (execution_strategy, base_spec_name, transforms[])
          This mapping is in the experiment config YAML.
  Output: execution_strategy name, base_spec_name, ordered transform names
  Validation: All names must exist in registry.

STEP 2: SPEC RESOLUTION
  Input:  base_spec_name
  Action: registry.get_spec(base_spec_name) → PromptSpec
  Output: PromptSpec (immutable)
  Validation: Spec exists. All its components exist.

STEP 3: TRANSFORM APPLICATION
  Input:  PromptSpec, ordered transforms[]
  Action: For each transform in order:
    a. Validate transform is compatible with spec (transform.compatible_specs)
    b. Validate transform is compatible with spec's response contract (transform.compatible_contracts)
    c. Apply operations (insert/replace/remove) to component list
    d. Merge transform.required_context_variables into required variable set
  Output: Modified component list, accumulated required variables
  Validation: All insertion points exist. No duplicate insertions. All compatibility checks pass.

STEP 4: RESPONSE CONTRACT RESOLUTION
  Input:  PromptSpec.response_contract name
  Action: registry.get_contract(name) → ResponseContract
  If contract has output_instruction_component:
    Append that component to the end of the component list.
  Output: Final ordered component list, ResponseContract
  Validation: Contract exists. Output instruction component exists (if specified).

STEP 5: CONTEXT COLLECTION
  Input:  Required variables (from components + transforms), case dict, execution state
  Action: For each required variable:
    a. Identify which ContextProvider owns it
    b. Call provider to get value + provenance
    c. Validate value is non-null and correct type
  Output: PromptContext (variables dict), VariableProvenance[] (per-variable audit records)
  Validation: All required variables are provided. Missing variable → fatal error.

STEP 6: RENDERING
  Input:  Ordered component list, PromptContext
  Action: For each component in order:
    a. Retrieve compiled Jinja2 template from registry
    b. Render: template.render(**context) → string
    c. Record (component_name, content_hash, rendered_hash)
  Output: Rendered parts list
  Validation: Jinja2 StrictUndefined mode — any undefined variable raises immediately.

STEP 7: JOIN
  Input:  Rendered parts list
  Action: "\n\n".join(parts) → final_prompt string
  Output: final_prompt, final_prompt_hash

STEP 8: RESOLVED PROMPT CONSTRUCTION
  Input:  All outputs from steps 1-7
  Action: Construct ResolvedPrompt object with all fields populated.
  Output: ResolvedPrompt (immutable)

STEP 9: LOGGING
  Input:  ResolvedPrompt
  Action: Write assembly manifest to call context (consumed by call_logger when call_model fires):
    spec_name, transforms_applied, response_contract_name, final_components (with hashes),
    bound_variables (with provenance), final_prompt_hash, context_provider_versions
  Output: Manifest attached to call context.

STEP 10: API CALL
  Input:  ResolvedPrompt.final_prompt, model name
  Action: call_model(prompt=final_prompt, model=model)
          call_model is ALWAYS raw. No output instruction logic inside call_model.
  Output: Response string.

STEP 11: RESPONSE PROCESSING
  Input:  Response string, ResolvedPrompt.response_contract
  Action: Invoke parser identified by contract.parser_name.
          Invoke validator identified by contract.validator_name (if any).
          Apply reconstruction policy.
  Output: Parsed result.
```

---

## SECTION C — Deterministic Composition Rules

### C1: Insertion Points

Every PromptSpec declares named insertion points as positions relative to its component list. Example for `generation_baseline`:

```
components: [task_block, code_files_block, nudge_slot, output_instruction]
insertion_points:
  nudge_slot: between code_files_block and output_instruction (initially empty)
```

`nudge_slot` is a placeholder. By default it renders nothing. A transform can insert a component there.

### C2: Operations

**insert(component, at=slot):** Places the named component at the slot position. If the slot already has content (from a previous transform), this is a fatal error — use `replace` instead.

**replace(component, at=slot):** Replaces whatever is at the slot with the new component. If the slot is empty, this is equivalent to `insert`.

**remove(slot):** Clears the slot. If the slot is already empty, this is a no-op.

### C3: Ordering Precedence

Transforms are applied in the order declared in config. This order is deterministic and logged. Example:

```yaml
conditions:
  diagnostic:
    transforms: ["add_nudge_diagnostic"]
  guardrail_strict:
    transforms: ["add_nudge_guardrail", "add_hard_constraints"]
```

For `guardrail_strict`, `add_nudge_guardrail` is applied first (inserts into `nudge_slot`), then `add_hard_constraints` is applied second (inserts into a `constraints_slot` after the nudge). If both targeted the same slot, the second would need to use `replace`, not `insert`.

### C4: Conflict Handling

- **Two inserts at the same slot:** Fatal error at assembly time. Logged with both transform names and the conflicting slot.
- **Replace on a non-empty slot:** Allowed. The replaced component name is logged as `"replaced: {old_name} → {new_name}"`.
- **Remove on an empty slot:** No-op. Logged as `"remove on empty slot {slot_name} (no-op)"`.
- **Transform references nonexistent slot:** Fatal error at startup validation.

### C5: Invalid Combinations (checked at startup)

| Combination | Rule | Error |
|---|---|---|
| Transform × incompatible Spec | `transform.compatible_specs` must include the spec name | `"Transform '{t}' is not compatible with spec '{s}'"` |
| Transform × incompatible Contract | `transform.compatible_contracts` must include the contract name | `"Transform '{t}' is not compatible with contract '{c}'"` |
| Spec × Contract mismatch | Spec's `response_contract` must be a registered contract | `"Spec '{s}' references unknown contract '{c}'"` |
| Strategy × missing Spec | All specs named by a strategy must exist | `"Strategy '{st}' references unknown spec '{s}'"` |

### C6: Concrete example

Config:
```yaml
conditions:
  scm_constrained_evidence:
    base_spec: "generation_baseline"
    transforms: ["add_scm_constrained_evidence"]
    execution_strategy: "single_call"
```

Resolution:
1. Load `generation_baseline` spec: `[task_block, code_files_block, nudge_slot, output_instruction]`
2. Apply `add_scm_constrained_evidence`: inserts `nudge_scm_constrained_evidence` at `nudge_slot`
3. Result: `[task_block, code_files_block, nudge_scm_constrained_evidence, output_instruction]`
4. ResponseContract: `json_v2_filedict` → output_instruction_component = `output_instruction_v2`
5. `output_instruction` in the component list is the slot; contract appends `output_instruction_v2` there
6. Context providers: TaskContextProvider + CodeContextProvider + SCMContextProvider + ResponseContractContextProvider
7. Render each component with context → join → final prompt

---

## SECTION D — Reproducibility Model

### D1: Authoritative replay artifact

**The raw prompt string (`ResolvedPrompt.final_prompt`).**

This is the exact text sent to the LLM. Given this string and the model name, the API call can be reproduced byte-for-byte (modulo model nondeterminism at temperature > 0).

Already logged in `calls/{call_id}.json` as `prompt_raw`.

### D2: Authoritative provenance artifact

**The ResolvedPrompt assembly manifest.**

This contains: spec name, transforms applied (ordered), component names with content hashes, variable provenance (names, hashes, truncation metadata), response contract name, final prompt hash.

This is logged alongside each call in the call logger.

### D3: What proves which prompt ran

The `final_prompt_hash` in the assembly manifest. If two calls have the same `final_prompt_hash`, they sent the same text to the LLM.

### D4: What proves which values were injected

The `bound_variables` dict in the assembly manifest. Each entry contains:
- Variable name
- Provider name
- Value hash
- Original length and truncated length (if applicable)
- Preview (first 100 chars)

Given the variable provenance records, you can verify: "this classifier call used reasoning text with hash X, truncated from 3200 to 1000 chars."

### D5: How drift is detected

At the start of every run, the PromptRegistry computes content hashes for all components and logs them to `metadata.json`. To check for drift:

1. Load the manifest from a completed run's `metadata.json` → `component_hashes` dict
2. Load the current component files → compute current hashes
3. Compare. Any mismatch means the component was modified since the run.

Within a run, drift is impossible (components are frozen in memory at startup).

Across runs, drift is detected by comparing the `component_hashes` dict in each run's metadata.

---

## SECTION E — Template Engine Decision

**Decision: Reuse the existing Jinja2 system.**

**Justification:**

1. The existing `templates.py` already implements: template loading from files, `StrictUndefined` mode (missing variables raise immediately), content hashing via `init_template_hashes()`, preflight validation that rejects control flow (`{% if %}`, `{% for %}`), and a template registry with `render()` and `render_with_metadata()`.

2. Jinja2's `StrictUndefined` environment satisfies the "zero silent failures" requirement: any undefined variable in a template causes an immediate `UndefinedError`.

3. Jinja2 handles braces in code content correctly when variables are passed as pre-formatted strings (the code files block is already formatted before injection, so Jinja2 never sees raw Python braces as template syntax).

4. The existing preflight validation (`preflight_validate_templates()`) already rejects templates with control flow. This enforces the "no logic in components" invariant.

5. Determinism: Jinja2 rendering is deterministic given the same template + variables. No randomness, no environment-dependent behavior.

6. `str.format()` is rejected because: it cannot detect undefined variables without manual checking, it collides with JSON braces (`{` and `}` must be doubled), and it lacks the existing validation infrastructure.

**What changes:** The existing template system becomes the primary rendering engine instead of a dead code path. The f-string prompt construction in Python source files is deleted. Component text files become the Jinja2 templates.

---

## SECTION F — Ablation Dimensions

Five independent ablation dimensions. Each can be varied while holding others constant:

### F1: Prompt Spec

The base prompt structure. Varying this means using a different set of components.

Example ablation: `generation_baseline` vs `generation_leg` — completely different prompt structures.

### F2: Transforms

Which nudges/interventions are applied to the base spec. Varying this means adding, removing, or swapping transforms.

Example ablation: `baseline` (no transforms) vs `diagnostic` (add diagnostic nudge) vs `guardrail` (add guardrail nudge). Same base spec, different transforms.

### F3: Response Contract

How the output is structured, parsed, and validated. Varying this means changing the output instruction and parser.

Example ablation: `json_v1_code` vs `json_v2_filedict` — same prompt body, different output format.

### F4: Execution Strategy

How many LLM calls are made and how they relate. Varying this means changing the call structure.

Example ablation: `single_call` vs `repair_loop` vs `retry_harness` — different execution patterns.

### F5: Model

Which LLM processes the prompt. Varying this is already config-driven.

**Clean ablation requirement:** To compare two conditions scientifically, exactly one dimension must differ. The config schema enforces this by making each dimension an independent config field:

```yaml
conditions:
  baseline:
    base_spec: "generation_baseline"
    transforms: []
    response_contract: "json_v2_filedict"
    execution_strategy: "single_call"
  diagnostic:
    base_spec: "generation_baseline"      # SAME
    transforms: ["add_nudge_diagnostic"]  # DIFFERENT
    response_contract: "json_v2_filedict"  # SAME
    execution_strategy: "single_call"      # SAME
```

If two conditions differ on multiple dimensions, that is visible in the config and flagged in the analysis.

---

## SECTION G — Migration Plan

### Phase 0: Extract components (no runtime change)

**Action:** For every prompt string in Python source, create a `.jinja2` file in `prompts/components/` with byte-identical content (replacing Python `{var}` with Jinja2 `{{ var }}`).

**Invariant:** `diff` between the rendered Jinja2 output and the current Python f-string output must be empty for every prompt, given the same variables.

**Rollback:** Delete the `prompts/components/` directory. No runtime code was changed.

**Verification:** Script that renders each template with test variables and compares against the f-string output.

### Phase 1: Build registry + assemble_prompt (shadow mode)

**Action:** Implement PromptRegistry, ResponseContract registry, ContextProviders, and `assemble_prompt()`. Create `prompts/manifest.yaml` with all specs, transforms, and contracts.

Wire shadow mode: at every existing prompt construction call site, ALSO call `assemble_prompt()` and assert the output is identical to the existing f-string output. If they differ, log the divergence and fail the run.

**Invariant:** Every LLM call produces the exact same prompt string from both paths. Verification is structural: character-by-character comparison, plus hash comparison.

**Definition of "identical":** `hashlib.sha256(old_prompt.encode()).hexdigest() == hashlib.sha256(new_prompt.encode()).hexdigest()`. Not just "similar" — exact byte match.

**Rollback:** Remove shadow mode calls. Registry code exists but is not invoked.

**Verification:** Run full ablation (all 4 models × 2 conditions × 58 cases). Zero divergences.

### Phase 2: Migrate by execution strategy (one at a time)

**Order:** `single_call` first (simplest, covers baseline + all nudge conditions), then `repair_loop`, then `contract_gated`, then `retry_harness`.

For each strategy:
1. Replace old prompt construction with `assemble_prompt()` call
2. Run the same cases as before
3. Compare `calls_flat.txt` output: hash of each prompt must match the shadow-mode verification run
4. If any hash differs: stop, investigate, fix before proceeding

**Invariant per phase:** The set of `final_prompt_hash` values for all calls must be identical between old and new paths.

**Rollback condition:** If more than 0 prompt hashes differ after fixing obvious issues (whitespace, encoding), revert the strategy migration and re-enter Phase 1 shadow mode for investigation.

### Phase 3: Migrate classifier and evaluator prompts

**Action:** Replace `_CLASSIFY_PROMPT.format(...)` with `assemble_prompt("classify_reasoning", ...)`. Replace `_CRIT_LITE_BLIND_PROMPT.format(...)` and conditioned variant.

**Invariant:** Classifier prompts match byte-for-byte. Truncation metadata is now logged explicitly.

**Rollback:** Revert classifier call sites only.

### Phase 4: Delete old code

**Deletion criteria:** A function/constant is deleted ONLY when:
1. No call site references it (verified by grep)
2. Shadow mode confirmed the new path produces identical output
3. At least one full ablation has completed successfully on the new path

**Delete:**
- `execution.py:build_prompt()` and its 18-branch if/elif
- All inline prompt constants (`_CLASSIFY_PROMPT`, nudge strings, etc.)
- `llm.py:_JSON_OUTPUT_INSTRUCTION_V1`, `_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE`
- `llm.py` output instruction append logic (make `call_model` always raw)
- `nudges/router.py` per-case mapping
- Old `templates.py` (replaced by registry that subsumes its functionality)

**Rollback:** Not applicable — old code is deleted only after new path is proven.

### Phase 5: Enhanced logging

**Action:** Add ResolvedPrompt assembly manifest to call logger. Add variable provenance records. Add truncation metadata for classifier.

**Invariant:** Every call JSON file contains a `prompt_assembly` field with the full manifest.

---

## SECTION H — Design Risks

### H1: Transform explosion

**Risk:** With 16+ conditions and growing, the number of transforms may proliferate. Each is a named object with compatibility declarations.

**Mitigation:** Most transforms are structurally identical (insert one component at `nudge_slot`). The manifest declares them declaratively — no new Python code per transform. Adding a new nudge condition means: (1) write one text file, (2) add one entry to manifest.yaml. No code change.

**Residual risk:** If transforms become structurally diverse (multi-slot, conditional insertion), the simple insert/replace/remove model may not suffice. Current system has no such transforms.

### H2: Config sprawl

**Risk:** `manifest.yaml` + experiment config + per-case SCM data = multiple YAML files to maintain. Errors in one can break runs.

**Mitigation:** All YAML is validated at startup. The manifest is validated against the registry (all referenced components exist). The experiment config is validated against the manifest (all referenced specs/transforms exist). Errors are fatal and descriptive.

**Residual risk:** YAML merge conflicts in multi-contributor environment. Mitigated by keeping the manifest stable (new conditions add entries, rarely modify existing ones).

### H3: Invalid comparability

**Risk:** Two conditions that differ on multiple ablation dimensions (spec + transform + contract) are compared as if they differ on one. The system allows this — it does not enforce single-dimension ablation.

**Mitigation:** The config makes all dimensions visible. An analysis script can check: for each pair of conditions being compared, how many dimensions differ? If more than one, flag the comparison as confounded.

**Residual risk:** The flag is advisory, not blocking. A researcher can ignore it.

### H4: Prompt lineage ambiguity

**Risk:** After modifying a component file, old runs' logged hashes no longer match. An auditor cannot tell whether the old prompt was the current file content or a previous version.

**Mitigation:** Component files are in git. The run metadata includes `git_hash`. Given the git hash + component name, the exact file content at run time can be recovered via `git show {hash}:prompts/components/{name}`.

**Residual risk:** If someone modifies a component and does not commit before running, the git hash points to the pre-modification version. The content hash in the run log would not match the git version. Detectable but confusing.

### H5: Replay breakage

**Risk:** A ResolvedPrompt from logs references component names that have been renamed or deleted. Replay cannot reconstruct the prompt.

**Mitigation:** Component names are stable identifiers. Renaming a component is a breaking change that requires updating all specs and manifests — git diff makes this visible. The raw prompt string (`prompt_raw` in call logs) is always sufficient for replay even if component provenance cannot be reconstructed.

**Residual risk:** Provenance reconstruction fails for very old runs after major refactors. Raw replay always works.

### H6: Spec proliferation

**Risk:** Each condition that uses a fundamentally different prompt structure (not just a nudge) needs its own PromptSpec. LEG, CGE-elicit, CGE-code, CGE-retry, retry-initial, retry-feedback, retry-critique, classify — that is already 8+ specs beyond the base generation spec.

**Mitigation:** This is inherent complexity, not accidental complexity. The current system has exactly the same number of prompt structures — they are just hidden inside Python functions. Making them explicit specs is a net improvement in clarity.

**Residual risk:** None. The number of specs equals the number of structurally distinct prompts, which is fixed by the experimental design.

### H7: Context provider ordering and staleness

**Risk:** A ContextProvider caches data that becomes stale (e.g., retry context from a previous iteration used in the current iteration).

**Mitigation:** Each provider declares its lifecycle (per-case, per-iteration, per-evaluation). The assembly pipeline calls providers at the declared lifecycle boundary. RetryContextProvider is called fresh each iteration. Staleness is impossible if lifecycle is respected.

**Residual risk:** A developer bypasses the provider and passes stale data directly. Enforcement tests can check that `assemble_prompt` is the only consumer of context data.

### H8: Jinja2 template syntax in code content

**Risk:** Python code containing `{{ }}` or `{% %}` could be misinterpreted by Jinja2 as template syntax.

**Mitigation:** Code file content is passed as a pre-rendered variable (`code_files_block`). The Jinja2 template references `{{ code_files_block }}` which outputs the already-formatted string. Jinja2 never parses the code content as a template. This is the same approach the existing system uses.

**Residual risk:** If someone puts `{{ }}` inside a component text file (not a variable reference), Jinja2 will try to interpret it. Caught at render time with a clear error.

---

*End of v2 design document. No implementation performed.*
