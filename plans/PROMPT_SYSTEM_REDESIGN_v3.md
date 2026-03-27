# Prompt System Redesign — Architecture Document v3

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** v1, v2

---

## SECTION A — Architecture Stack

Ten named abstractions, layered from static registry objects to runtime artifacts.

---

### A1: PromptComponent

**What it is:** An immutable block of Jinja2 template text, loaded from a file at startup.

**Fields:**
- `name` — globally unique identifier
- `source_path` — file path relative to `prompts/components/`
- `template` — compiled Jinja2 template object (StrictUndefined)
- `required_variables` — `frozenset[str]`, extracted from Jinja2 AST at load time
- `content_hash` — SHA-256 of raw source text, computed before compilation

**Invariants:**
- Immutable after load.
- `required_variables` is computed by Jinja2 AST walk, not regex.
- No control flow in templates. `preflight_validate_templates()` (existing function) rejects `{% if %}`, `{% for %}`, `{% macro %}` at startup.
- Duplicate `name` registration is a fatal startup error.

**Forbidden:**
- Logic beyond variable substitution and whitespace control.
- Knowledge of conditions, models, cases, execution.
- Importing or referencing other components.

---

### A2: PromptSpec

**What it is:** A static, registered recipe declaring the structure of a prompt family. Defines slots, default components, and constraints.

**Fields:**
- `name` — globally unique identifier (e.g., `"generation_baseline"`, `"classify_reasoning"`, `"cge_elicit"`)
- `stage` — one of: `generation`, `classifier`, `critique`, `contract_elicit`, `contract_code`, `contract_retry`, `retry_initial`, `retry_feedback`, `evaluator`. This is a structural tag, not a runtime value.
- `slots` — ordered list of `SlotDeclaration` objects (see below)
- `response_contract` — name of the ResponseContract
- `required_context_providers` — set of ContextProvider names that must be present
- `allowed_transforms` — set of PromptTransform names (whitelist). Empty set = no transforms allowed.
- `allowed_strategies` — set of ExecutionStrategy names this spec may appear in
- `standalone` — boolean. If true, this spec can be used as a top-level experiment ablation target. If false, it is strategy-internal only (e.g., `retry_feedback` is not a valid ablation target).

**SlotDeclaration:**
- `name` — slot identifier, unique within this spec
- `cardinality` — `singleton` or `stack`
- `default_component` — component name (may be null for empty slots)
- `extensible` — boolean. If false, transforms may not introduce new child slots here.

Slot semantics:
- `singleton` slot holds exactly zero or one component. `insert` on an occupied singleton is fatal. `replace` overwrites. `remove` clears.
- `stack` slot holds an ordered sequence of zero or more components. `append` adds to end. `prepend` adds to front. `replace` is forbidden on stack slots (use `remove` + `append`). `remove(component_name)` removes a specific named entry from the stack.

**Invariants:**
- Immutable after registration.
- All `default_component` names must exist in the PromptRegistry.
- The `response_contract` name must exist in the registry.
- All `allowed_transforms` names must exist.
- All `allowed_strategies` names must exist.
- Slot names are unique within the spec.

**Forbidden:**
- Text content.
- Runtime state.
- Variable binding.
- Knowledge of which case or condition is active.

**Concrete specs for the current system:**

| Spec Name | Stage | Standalone | Slots |
|---|---|---|---|
| `generation_baseline` | generation | yes | `[task(S), code_files(S), nudge(stack), constraints(stack), output_instruction(S)]` |
| `generation_leg` | generation | yes | `[task(S), code_files(S), leg_schema(S), leg_procedure(S), leg_rules(S)]` |
| `cge_elicit` | contract_elicit | no | `[task(S), code_files(S), analysis_instruction(S), contract_schema(S)]` |
| `cge_code` | contract_code | no | `[task(S), code_files(S), contract_commitment(S), compliance_instructions(S), output_instruction(S)]` |
| `cge_retry` | contract_retry | no | `[task(S), code_files(S), violations(S), contract_commitment(S), fix_instruction(S), output_instruction(S)]` |
| `retry_initial` | retry_initial | no | `[task(S), code_files(S), alignment_extra(S?), output_instruction(S)]` |
| `retry_feedback` | retry_feedback | no | `[task(S), original_code(S), previous_attempt(S), test_results(S), critique(S?), contract(S?), hint(S?), trajectory(S?), fix_instruction(S), alignment_extra(S?), output_instruction(S)]` |
| `retry_critique` | critique | no | `[code_under_test(S), test_results(S), critique_schema(S)]` |
| `retry_contract_elicit` | contract_elicit | no | `[task(S), contract_schema(S)]` |
| `classify_reasoning` | classifier | no | `[role_definition(S), anti_bias_instructions(S), task_definition(S), failure_types(S), inputs(S), rules(S), output_format(S)]` |
| `evaluate_reasoning_blind` | evaluator | no | `[evaluator_role(S), inputs(S), evaluation_phases(S), failure_types(S), verdict_rules(S), output_format(S)]` |
| `evaluate_reasoning_conditioned` | evaluator | no | same as blind + `[system_detected_type(S)]` |

(`S` = singleton, `stack` = stack slot, `S?` = singleton, default empty/null)

---

### A3: PromptTransform

**What it is:** A pure, stateless structural modification targeting specific slots in a PromptSpec.

**Fields:**
- `name` — globally unique identifier
- `operations` — ordered list of slot operations:
  - `insert(component_name, slot_name)` — for singleton slots only, slot must be empty
  - `replace(component_name, slot_name)` — for singleton slots only, replaces current occupant
  - `remove(slot_name)` — clears a singleton slot
  - `remove(slot_name, component_name)` — removes a specific entry from a stack slot
  - `append(component_name, slot_name)` — for stack slots only, adds to end
  - `prepend(component_name, slot_name)` — for stack slots only, adds to front
- `additional_context_variables` — extra variables the injected components need
- `compatible_specs` — set of PromptSpec names (validated against spec's `allowed_transforms`)
- `compatible_contracts` — set of ResponseContract names
- `selection_rule` — how this transform's components are resolved (see Section F)

**Invariants:**
- Stateless and pure.
- Targets only slots declared by the spec. Referencing a nonexistent slot is fatal at startup validation.
- Singleton operations obey singleton rules. Stack operations obey stack rules. Mismatch is fatal.
- Multiple transforms compose by sequential application in config-declared order. Each transform sees the result of all prior transforms.
- A transform is NOT allowed to introduce new slots. The spec owns all slot declarations.
- Transforms are NOT idempotent by default. Applying the same transform twice appends twice to a stack, or fails on an occupied singleton. Config must not declare the same transform twice.

**Forbidden:**
- Text generation.
- Variable binding or value provision.
- LLM calls, I/O, side effects.
- Modifying the ResponseContract.
- Introducing new slots.
- Depending on the output of another transform (transforms see only the slot state, not other transforms' identities).

**Concrete transforms for the current system:**

| Transform Name | Operations | Compatible Specs | Notes |
|---|---|---|---|
| `add_nudge_diagnostic` | `append(resolved_component, "nudge")` | `generation_baseline` | Component resolved by selection rule |
| `add_nudge_guardrail` | `append(resolved_component, "nudge")` | `generation_baseline` | Component resolved by selection rule |
| `add_hard_constraints` | `append(nudge_hard_constraints, "constraints")` | `generation_baseline` | Uses `hard_constraints` variable |
| `add_nudge_counterfactual` | `append(nudge_counterfactual, "nudge")` | `generation_baseline` | Fixed component |
| `add_nudge_reason_then_act` | `append(nudge_reason_then_act, "nudge")` | `generation_baseline` | Fixed component |
| `add_nudge_self_check` | `append(nudge_self_check, "nudge")` | `generation_baseline` | Fixed component |
| `add_nudge_counterfactual_check` | `append(nudge_cf_check, "nudge")` | `generation_baseline` | Fixed component |
| `add_nudge_test_driven` | `append(nudge_test_driven, "nudge")` | `generation_baseline` | Fixed component |
| `add_structured_reasoning` | `append(nudge_structured_reasoning, "nudge")` | `generation_baseline` | Fixed component |
| `add_free_form_reasoning` | `append(nudge_free_form, "nudge")` | `generation_baseline` | Fixed component |
| `add_branching_reasoning` | `append(nudge_branching, "nudge")` | `generation_baseline` | Fixed component |
| `add_scm_descriptive` | `append(nudge_scm_descriptive, "nudge")` | `generation_baseline` | Requires SCMContextProvider |
| `add_scm_constrained` | `append(nudge_scm_constrained, "nudge")` | `generation_baseline` | Requires SCMContextProvider |
| `add_scm_evidence` | `append(nudge_scm_evidence, "nudge")` | `generation_baseline` | Requires SCMContextProvider |
| `add_scm_evidence_minimal` | `append(nudge_scm_evidence_min, "nudge")` | `generation_baseline` | Requires SCMContextProvider |
| `add_evidence_only` | `append(nudge_evidence_only, "nudge")` | `generation_baseline` | Requires SCMContextProvider |
| `add_length_control` | `append(nudge_length_control, "nudge")` | `generation_baseline` | Fixed component |

---

### A4: ResponseContract

**What it is:** A first-class registry object that owns the complete agreement between a prompt and its response processing chain.

**Fields:**
- `name` — globally unique identifier
- `output_instruction_component` — component name for the output format instruction, or `null`
- `parser` — a reference to a registered parser object (not a string name)
- `validator` — a reference to a registered validator object, or `null`
- `schema` — structural schema descriptor that the validator enforces
- `reconstruction_policy` — one of: `file_dict`, `code_blob`, `metadata_only`
- `normalization_policy` — ordered list of post-parse normalizations to apply (e.g., `["strip_markdown_fences", "unescape_newlines"]`), or empty list
- `error_classification` — mapping from parse failure types to error categories:
  - `format_mismatch` → the response does not match the expected structure at all
  - `partial_parse` → some fields extracted, others missing
  - `schema_violation` → structure matches but field values violate constraints
  - `total_failure` → no usable content extracted

**Parser interface (what the parser must satisfy):**
- Input: raw response string
- Output: a typed `ParseResult` containing:
  - `success` — boolean
  - `format_detected` — which format tier matched (e.g., `file_dict`, `json_direct`, `code_block`, `raw_fallback`)
  - `fields` — extracted dict (keys depend on contract schema)
  - `parse_error` — string or null
  - `raw_fallback_used` — boolean
- The parser MUST NOT modify the raw response. It extracts; it does not transform.

**Validator interface (what the validator must satisfy):**
- Input: `ParseResult`
- Output: `ValidationResult` containing:
  - `valid` — boolean
  - `violations` — list of `{field, violation_type, message}`
- The validator checks structural completeness and field constraints against the contract's `schema`.
- A validation failure does NOT discard the parse result. It annotates it. Downstream code decides whether to proceed with degraded data.

**Schema enforcement:**
The `schema` field is NOT documentation-only. It is consumed by the validator at runtime. The validator compares the `ParseResult.fields` against the schema and produces violations for:
- Missing required fields
- Wrong field types
- Fields present but empty when required non-empty
- Unexpected fields (logged as warnings, not errors)

**Concrete contracts:**

| Contract | Output Instruction | Parser | Validator | Reconstruction | Normalization |
|---|---|---|---|---|---|
| `json_v2_filedict` | `output_instruction_v2` | `standard_parser` | `filedict_validator` | `file_dict` | `[strip_fences, unescape_newlines]` |
| `json_v1_code` | `output_instruction_v1` | `standard_parser` | `code_field_validator` | `code_blob` | `[strip_fences]` |
| `leg_structured` | `null` | `leg_parser` | `leg_schema_validator` | `code_blob` | `[]` |
| `raw_verdict` | `null` | `verdict_parser` | `null` | `metadata_only` | `[]` |
| `raw_json_freeform` | `null` | `json_parser` | `null` | `metadata_only` | `[]` |

---

### A5: ContextProvider

**What it is:** A scoped, validated supplier of variables for prompt rendering. Each provider owns a defined set of variables and is the sole authority on their values.

**Ownership rules:**
- Every variable has exactly one owning provider. No shared ownership.
- Provider outputs are immutable once collected for a call. No mutation after collection.
- Truncation happens ONLY in the owning provider. No downstream truncation.
- Providers MAY NOT depend on other providers' outputs. The dependency graph is flat (depth 1): providers read from case data, execution state, or static files — never from each other.
- Derived variables (e.g., `code_files_block` derived from `code_files`) must record upstream provenance: the source data hash and the transformation applied.

**Concrete providers:**

| Provider | Lifecycle | Variables Owned | Derived? |
|---|---|---|---|
| `TaskContextProvider` | per-case | `task`, `case_id`, `failure_mode`, `hard_constraints` | No (raw from case dict) |
| `CodeContextProvider` | per-case | `code_files_block`, `file_paths`, `file_entries` | Yes: `code_files_block` derived from `case["code_files_contents"]` via `_format_code_files()`. Provenance: hash of each source file + formatting function version. |
| `SCMContextProvider` | per-case, lazy | `scm_edges_text`, `scm_constraints_text`, `scm_invariants_text`, `scm_functions_text`, `scm_variables_text`, `scm_critical_constraint`, `scm_critical_evidence` | Yes: derived from `scm_data/{case_id}.json`. Provenance: hash of SCM data file. |
| `ClassifierContextProvider` | per-eval | `failure_types`, `classifier_task`, `classifier_code`, `classifier_reasoning` | Yes: truncated from full values. Provenance: original hash, truncated hash, original length, truncated length, truncation limit. |
| `RetryContextProvider` | per-iteration | `original_code`, `previous_code`, `test_output`, `critique_json`, `contract_json`, `adaptive_hint`, `trajectory_context` | Mixed: `original_code` is raw, `critique_json` is serialized from dict. Provenance recorded per variable. |
| `ContractContextProvider` | per-CGE-step | `contract_json`, `contract_schema_text`, `violations_text` | Yes: serialized from dicts. Provenance: hash of source dict. |
| `OutputInstructionContextProvider` | per-spec | `file_entries` | Yes: derived from `file_paths`. Provenance: hash of file_paths list. |

**Variable provenance record:**
```
{
  "name": "classifier_reasoning",
  "provider": "ClassifierContextProvider",
  "raw": false,
  "derivation": "truncated",
  "source_hash": "a7f2...",
  "value_hash": "3b1c...",
  "source_length": 3200,
  "value_length": 1000,
  "truncation_limit": 1000,
  "upstream": {
    "source_variable": "parsed.reasoning",
    "source_provider": null
  },
  "preview": "The bug is that create_config() assigns..."
}
```

For non-derived variables:
```
{
  "name": "task",
  "provider": "TaskContextProvider",
  "raw": true,
  "derivation": null,
  "value_hash": "e4d1...",
  "value_length": 450,
  "upstream": null,
  "preview": "Refactor this configuration module for clarity..."
}
```

**Caching:** Providers cache their output for the declared lifecycle scope. `TaskContextProvider` caches per-case (same output for baseline and leg_reduction on the same case). `RetryContextProvider` caches per-iteration (new output each iteration). Cache is invalidated when lifecycle scope changes.

---

### A6: ComponentBinding

**What it is:** A resolved assignment of a specific component to a specific slot, with full provenance of how and why it was selected.

**Fields:**
- `slot_name` — which slot this occupies
- `component_name` — which component was selected
- `component_hash` — content hash of the component
- `source` — how it was selected:
  - `"spec_default"` — the spec's default component for this slot
  - `"transform:{transform_name}"` — a transform inserted/replaced it
  - `"selection_rule:{rule_description}"` — a selection rule resolved it (see Section F)
- `override_tier` — which precedence tier selected this (see Section F):
  - `"case_override"`, `"family_failure_mode"`, `"failure_mode"`, `"generic_default"`
- `position_in_stack` — integer index if this is a stack slot entry, null for singletons

**Invariant:** Every component in the final assembly has exactly one ComponentBinding. The binding is created during plan resolution and is immutable.

---

### A7: ResolvedPromptPlan

**What it is:** The structural provenance artifact, created after spec resolution and transform application but BEFORE rendering. Captures the full "recipe" without any variable values or rendered text.

**Fields:**
- `spec_name` — which PromptSpec
- `transforms_applied` — ordered list of transform names
- `response_contract_name` — which ResponseContract
- `bindings` — ordered list of `ComponentBinding` objects (the final slot→component assignments)
- `required_variables` — union of all component `required_variables` across all bindings
- `required_providers` — set of ContextProvider names needed
- `plan_hash` — SHA-256 of the canonical serialization of (spec_name, transforms, bindings)

**Invariants:**
- Immutable after creation.
- Deterministic: same spec + same transforms + same selection rule inputs = same plan.
- Can be validated BEFORE rendering: check that all required providers are available, all required variables can be supplied.

**Purpose:** Separates "what will we build" from "building it." Plan validation catches errors (missing provider, incompatible transform) before any rendering or API calls happen.

---

### A8: RenderedPrompt

**What it is:** The concrete rendered artifact for a single LLM call. Created by rendering a ResolvedPromptPlan with a collected context.

**Fields:**
- `plan` — reference to the ResolvedPromptPlan
- `rendered_parts` — ordered list of `(component_name, rendered_text, rendered_hash)` tuples
- `bound_variables` — dict of `{var_name: VariableProvenance}` for every variable consumed
- `final_prompt` — the joined string (`"\n\n".join(rendered_parts)`)
- `final_prompt_hash` — SHA-256 of `final_prompt`
- `context_provider_versions` — dict of `{provider_name: cache_key_hash}`

**Invariants:**
- Immutable after creation.
- `final_prompt` is deterministic: same plan + same variable values = same string.
- Created exactly once per LLM call.

**Forbidden:**
- Modification after creation.
- LLM calls or I/O.
- Parsing logic.

---

### A9: ExecutionStrategy

**What it is:** An explicit orchestration model that declares the call graph for a single case evaluation.

**Fields:**
- `name` — globally unique identifier
- `stages` — ordered list of `StageDeclaration` objects:
  - `stage_name` — identifier within the strategy (e.g., `"attempt_1"`, `"critique"`, `"evaluate"`)
  - `spec_name` — which PromptSpec to use (static binding)
  - `transforms_source` — `"experiment"` (researcher-controlled, from ExperimentCondition) or `"internal"` (strategy-owned, not researcher-facing)
  - `internal_transforms` — list of transform names applied unconditionally by the strategy (only used when `transforms_source = "internal"`)
  - `context_providers` — list of ContextProvider names needed for this stage
  - `response_contract` — contract name (must match the spec's declared contract)
  - `depends_on` — list of prior stage names whose output is needed
  - `conditional` — boolean. If true, this stage only executes if a runtime condition is met (e.g., "only retry if attempt_1 failed")
  - `condition_expression` — string describing the runtime gate (e.g., `"prior_stage_failed"`, `"gate_violated"`)
- `stop_conditions` — list of conditions that terminate the strategy early (for retry loops)
- `classifier_stage` — name of the classifier stage (always present, always last non-conditional)

**Invariants:**
- All `spec_name` references must exist in the registry.
- All specs must have `this_strategy_name` in their `allowed_strategies`.
- The `depends_on` graph must be acyclic.
- `transforms_source = "experiment"` means the transforms come from the ExperimentCondition config. `transforms_source = "internal"` means transforms are hardwired by the strategy and not researcher-controllable.
- Every strategy must include exactly one classifier stage (unless it is a pure generation strategy with external evaluation).

**Forbidden:**
- Inline prompt text.
- Modifying PromptSpecs or components.
- Bypassing `assemble_prompt`.
- Mixing experiment-controlled and internal transforms for the same stage.

**Concrete strategies:**

| Strategy | Stages | Notes |
|---|---|---|
| `single_call` | `[generation(experiment), classify(internal)]` | Simplest. Generation transforms are experiment-controlled. Classifier is internal. |
| `repair_loop` | `[attempt_1(experiment), attempt_2(internal, conditional), classify(internal)]` | Attempt 2 uses repair_feedback spec with error context. |
| `contract_gated` | `[elicit(internal), code(experiment), gate_check(no LLM), retry(internal, conditional), classify(internal)]` | Gate check is not an LLM call. Retry is conditional on gate failure. |
| `retry_harness` | `[initial(experiment), {feedback(internal)+critique(internal, conditional)}×K, classify(internal)]` | Loop with stopping conditions. Critique is conditional on failure. |

---

### A10: ExperimentCondition

**What it is:** A researcher-facing named bundle in the experiment config. NOT a runtime primitive — it is a configuration-layer concept that decomposes into architectural primitives.

**Fields (in config YAML):**
- `name` — researcher-facing label (e.g., `"baseline"`, `"diagnostic"`, `"scm_constrained_evidence"`)
- `base_spec` — PromptSpec name for the generation stage
- `transforms` — ordered list of PromptTransform names (applied to the generation spec only)
- `execution_strategy` — ExecutionStrategy name
- `response_contract` — (optional override) ResponseContract name. If omitted, uses the spec's default.

**What it is NOT:**
- Not a runtime object. It is deserialized from YAML into the architectural primitives above.
- Not an orchestrator. The ExecutionStrategy orchestrates.
- Not a prompt builder. The assembly engine builds.

**Researcher-facing fields (safe to vary in ablations):**
- `transforms` — the primary ablation dimension for nudge/intervention experiments
- `base_spec` — for experiments comparing fundamentally different prompt structures
- `execution_strategy` — for experiments comparing retry vs single-call

**Strategy-internal fields (NOT researcher-facing):**
- Classifier spec, critique spec, retry feedback spec — these are bound by the strategy, not the researcher.
- Internal transforms applied by strategy stages.

**Forbidden overrides:**
- Classifier response contract (must remain `raw_verdict`).
- Strategy-internal transforms (researcher cannot modify critique prompts via the condition config).
- Spec/strategy compatibility violations (validated at config load time).

---

## SECTION B — System Engine Boundaries

Four runtime boundaries, each with explicit ownership.

### B1: SelectionEngine

**Owns:** Resolving abstract references to concrete component names using the selection precedence model.

**Input:** Transform with a `selection_rule`, case metadata.
**Output:** Resolved component name.

**What it does:**
- Evaluates the selection precedence ladder (Section F) to pick a specific component.
- Records the selection decision and override tier in the ComponentBinding.

**Forbidden:**
- Rendering text.
- Making LLM calls.
- Modifying specs, transforms, or components.
- Accessing execution state beyond case metadata.

### B2: AssemblyEngine

**Owns:** The entire pipeline from PromptSpec → ResolvedPromptPlan → RenderedPrompt. This is the ONE function that builds prompts.

**Input:** ExperimentCondition (deserialized), case dict, execution state, stage name.
**Output:** RenderedPrompt.

**What it does:**
1. Looks up PromptSpec from registry
2. Applies transforms (delegating component resolution to SelectionEngine)
3. Resolves ResponseContract (appends output instruction component if needed)
4. Constructs ResolvedPromptPlan
5. Validates plan (all variables satisfiable, all providers available)
6. Collects context from ContextProviders
7. Renders each component via Jinja2
8. Constructs RenderedPrompt
9. Returns RenderedPrompt (which carries the full manifest for logging)

**Forbidden:**
- Making LLM calls.
- Parsing responses.
- Knowing about execution strategy control flow.
- Containing business logic about when to retry or evaluate.

### B3: ExecutionEngine

**Owns:** Orchestrating LLM calls according to an ExecutionStrategy.

**Input:** ExperimentCondition, case dict, model name.
**Output:** Final evaluation result.

**What it does:**
1. Looks up ExecutionStrategy
2. For each stage in the strategy:
   a. Calls AssemblyEngine to build the RenderedPrompt
   b. Logs the RenderedPrompt manifest to call context
   c. Calls `call_model(rendered_prompt.final_prompt, model)` — always raw, no output instruction logic in call_model
   d. Passes response to ResponseInterpreter
   e. Uses interpretation result to decide next stage (conditional stages, stopping conditions)
3. Returns final evaluation dict

**Forbidden:**
- Constructing prompts (that is AssemblyEngine's job).
- Parsing responses (that is ResponseInterpreter's job).
- Modifying PromptSpecs or transforms.

### B4: ResponseInterpreter

**Owns:** Processing a raw LLM response according to a ResponseContract.

**Input:** Raw response string, ResponseContract.
**Output:** Interpreted result (parsed fields, validation result, reconstruction result).

**What it does:**
1. Invokes the contract's parser → ParseResult
2. Invokes the contract's validator (if any) → ValidationResult
3. Applies normalization policy → normalized ParseResult
4. Applies reconstruction policy (if applicable) → reconstructed code
5. Classifies any errors according to the contract's error classification
6. Returns the full interpretation chain

**Forbidden:**
- Making LLM calls.
- Constructing prompts.
- Modifying the response string.
- Knowledge of which condition or case produced the response.

---

## SECTION C — Composition Model

### C1: Slot Types

**Singleton slot:** Holds zero or one component.
- `insert(component)` — places component. Fatal if slot is occupied.
- `replace(component)` — overwrites occupant. Allowed whether slot is empty or occupied. Logs the replacement.
- `remove()` — clears the slot. No-op if already empty.

**Stack slot:** Holds an ordered sequence of zero or more components.
- `append(component)` — adds to end of stack.
- `prepend(component)` — adds to front of stack.
- `remove(component_name)` — removes the named entry. Fatal if not found in stack.
- `insert` and `replace` are forbidden on stack slots (use append/prepend + remove).

### C2: Transform Ordering

Transforms are applied in the order declared in the ExperimentCondition config. This order is deterministic, logged, and part of the ResolvedPromptPlan.

Each transform sees the slot state after all prior transforms. A transform CANNOT depend on which other transforms ran — it sees only the current slot contents.

### C3: Collision Rules

| Situation | Singleton | Stack |
|---|---|---|
| Two inserts | Fatal error | N/A (use append) |
| Two appends | N/A | Both components added in transform order |
| Insert then replace | Fatal (insert fails on occupied) | N/A |
| Replace then replace | Second overwrites first, both logged | N/A |
| Append then remove(same) | Component is added then removed = net empty | Component is added then removed = net empty |

### C4: Concrete Examples

**Example 1: Diagnostic condition with hard constraints**

Config:
```yaml
diagnostic_strict:
  base_spec: "generation_baseline"
  transforms: ["add_nudge_diagnostic", "add_hard_constraints"]
```

Slot state evolution:
```
Initial:     [task(occupied), code_files(occupied), nudge(empty stack), constraints(empty stack), output_instruction(occupied)]
After add_nudge_diagnostic:  nudge stack = [nudge_diagnostic_hidden_dependency]
After add_hard_constraints:  constraints stack = [nudge_hard_constraints]
Final:       [task, code_files, nudge_diagnostic_hidden_dependency, nudge_hard_constraints, output_instruction_v2]
```

**Example 2: Two nudges on the same stack**

Config:
```yaml
diagnostic_plus_self_check:
  base_spec: "generation_baseline"
  transforms: ["add_nudge_diagnostic", "add_nudge_self_check"]
```

Slot state:
```
nudge stack after both: [nudge_diagnostic_..., nudge_self_check]
```

Both land in the `nudge` stack slot, ordered by config-declared transform order.

**Example 3: Case-specific override replacing generic**

Config:
```yaml
diagnostic:
  base_spec: "generation_baseline"
  transforms: ["add_nudge_diagnostic"]
```

The `add_nudge_diagnostic` transform has a `selection_rule` that resolves the component based on case metadata (Section F). For case `alias_config_a` with `failure_mode="HIDDEN_DEPENDENCY"`, the SelectionEngine resolves to `nudge_diagnostic_hidden_dependency` (case-specific). For a case with no specific nudge, it resolves to `nudge_diagnostic_generic_dependency`.

### C5: Nesting

Components do not own child components. There is no nesting. Slots are flat. A stack slot is a flat ordered list, not a tree.

If a future need arises for nested composition, it would be modeled as multiple stack slots (e.g., `reasoning_nudge` stack and `verification_nudge` stack) rather than nested components.

---

## SECTION D — Selection Precedence Model

### D1: The Override Ladder

When a transform's `selection_rule` must resolve a component name, the SelectionEngine evaluates these tiers in order, returning the first match:

1. **Explicit case override:** A component named `{base_name}_{case_id}` exists in the registry. Example: `nudge_diagnostic_alias_config_a`.
2. **Family + failure_mode:** A component named `{base_name}_{family}_{failure_mode}` exists. Example: `nudge_diagnostic_aliasing_hidden_dependency`.
3. **Failure_mode only:** A component named `{base_name}_{failure_mode}` exists. Example: `nudge_diagnostic_hidden_dependency`.
4. **Generic default:** A component named `{base_name}_generic` exists. Example: `nudge_diagnostic_generic`.

If no tier matches, assembly fails with a fatal error naming the transform, the case, and the failed resolution.

### D2: Selection Rule Declaration

A transform declares its selection rule as:

```
selection_rule:
  base_name: "nudge_diagnostic"
  resolve_by: ["case_id", "family+failure_mode", "failure_mode", "generic"]
  case_metadata_fields: ["case_id", "family", "failure_mode"]
```

This is evaluated by the SelectionEngine using case metadata. The resolved component name and the tier that matched are recorded in the ComponentBinding.

### D3: Fixed-Component Transforms

Most transforms do not use selection rules. They reference a fixed component name:

```
operations:
  - append: {component: "nudge_counterfactual", slot: "nudge"}
```

No selection rule needed. The component is always the same regardless of case metadata.

---

## SECTION E — Layered Equivalence for Migration

### E1: Text Equivalence

`SHA-256(old_final_prompt) == SHA-256(new_final_prompt)`

Both paths produce the same byte sequence. This is the primary migration gate.

### E2: Plan Equivalence

The old path does not produce a ResolvedPromptPlan. During shadow mode, the new path produces one. Plan equivalence means: the plan's `bindings` list, when rendered, produces a text-equivalent prompt.

Plan equivalence is a STRONGER check than text equivalence because it also verifies that the component decomposition is correct (same components in the same order producing the same text).

### E3: Contract Equivalence

The old path implicitly selects a parser based on `raw=True/False` and the condition. The new path explicitly names a ResponseContract. Contract equivalence means: the same parser function is invoked for both paths, producing the same ParseResult on the same input.

Verified by: running the old parser and the new contract's parser on the same response string and comparing ParseResult fields.

### E4: Provenance Equivalence

Only meaningful after full migration. Two runs are provenance-equivalent if their ResolvedPromptPlans have the same `plan_hash` (same spec, transforms, bindings).

### E5: Parse-Path Equivalence

The old path uses one of: `parse_model_response`, `parse_leg_reduction_output`, `parse_classify_output`. The new path uses the contract's declared parser. Parse-path equivalence means: given the same raw response, both paths produce the same downstream evaluation result (pass/fail, score, reasoning_correct).

Verified by: comparing evaluation dicts field-by-field.

---

## SECTION F — Migration: Two Distinct Phases

### Phase A: Legacy-Equivalent Migration

**Goal:** Reproduce current behavior exactly using the new architecture. Zero intentional behavior changes.

**Steps:**
1. Extract component text files (Phase 0 from v2)
2. Build registry + assemble_prompt in shadow mode (Phase 1 from v2)
3. Migrate call sites by execution strategy (Phase 2 from v2)
4. Migrate classifier/evaluator (Phase 3 from v2)

**Equivalence gate:** Text equivalence + parse-path equivalence for every call in a full ablation run.

**Rollback trigger:** Any non-zero divergence in text equivalence after investigation. Any parse-path divergence.

**What is NOT allowed during Phase A:**
- Fixing "bad" prompts or prompt logic
- Reordering components even if the current order seems wrong
- Normalizing whitespace, newlines, or spacing between components
- Changing selection logic (even if the current per-case mapping seems arbitrary)

Phase A proves the new architecture can express the old system exactly. Nothing more.

### Phase B: Architecture-Native Improvements

**Goal:** Fix known issues using the new architecture's capabilities. Each change is deliberate, reviewed, and logged.

**Steps (each is an independent, reviewable change):**
1. Unify generic and case-specific nudge variants (replace duplicates with selection-rule-based resolution)
2. Clean up whitespace/formatting inconsistencies between prompts
3. Standardize component boundaries (e.g., move output instruction from implicit append to explicit component)
4. Add truncation logging to classifier context provider
5. Add schema validation to response contracts
6. Remove dead template files that are now superseded by components

**Each change must:**
- Be logged as a deliberate deviation from legacy behavior
- Include a before/after comparison of affected prompts
- Be flagged in experiment metadata: `"prompt_version": "architecture_native_v1"` vs `"prompt_version": "legacy_equivalent"`
- Not be mixed with other changes in the same run

**How experiments distinguish legacy-equivalent vs architecture-native:**
The experiment config includes a `prompt_version` field. Runs with `"legacy_equivalent"` used Phase A prompts. Runs with `"architecture_native_v1"` used Phase B prompts. These are never compared as if they were the same prompt system.

---

## SECTION G — Experiment Config Model

### G1: Researcher-Facing Fields

```yaml
conditions:
  baseline:
    base_spec: "generation_baseline"        # researcher-controlled
    transforms: []                           # researcher-controlled
    execution_strategy: "single_call"        # researcher-controlled
    # response_contract: inherited from spec default unless overridden

  diagnostic:
    base_spec: "generation_baseline"
    transforms: ["add_nudge_diagnostic"]
    execution_strategy: "single_call"

  leg_reduction:
    base_spec: "generation_leg"
    transforms: []
    execution_strategy: "single_call"

  retry_adaptive:
    base_spec: "generation_baseline"
    transforms: []
    execution_strategy: "retry_harness"
```

### G2: Strategy-Internal Fields (NOT in experiment config)

These are defined in the strategy registry, not in the experiment config:

- Which spec the classifier stage uses (`classify_reasoning`)
- Which spec the critique stage uses (`retry_critique`)
- Which internal transforms the retry feedback stage applies
- Which response contract the classifier uses (`raw_verdict`)

**Researchers cannot override these.** If a researcher needs to experiment with classifier prompts, that is a separate experiment with a different strategy definition — not a condition-level override.

### G3: Forbidden Overrides (enforced at config load)

| Field | Forbidden For | Reason |
|---|---|---|
| `response_contract` | classifier stages | Changing classifier parsing would invalidate all comparisons |
| `base_spec` | strategy-internal stages | e.g., cannot swap `retry_feedback` spec from condition config |
| `transforms` | strategy-internal stages | Cannot inject nudges into critique or classifier prompts from condition config |
| `execution_strategy` | conditions using strategy-internal specs | e.g., `retry_feedback` cannot be used with `single_call` strategy |

### G4: Ablation Safety

For two conditions to be scientifically comparable, they must differ on exactly one dimension. The config schema makes all dimensions visible. An analysis tool can check:

```
For each pair (condition_A, condition_B):
  diff_count = 0
  if A.base_spec != B.base_spec: diff_count += 1
  if A.transforms != B.transforms: diff_count += 1
  if A.execution_strategy != B.execution_strategy: diff_count += 1
  if A.response_contract != B.response_contract: diff_count += 1
  if diff_count > 1: WARN "confounded comparison"
```

---

## SECTION H — Compatibility Matrix

### H1: Transform × Spec Compatibility

| Transform | Valid Specs | Invalid Specs | Enforcement |
|---|---|---|---|
| `add_nudge_*` (all nudge transforms) | `generation_baseline` | All others | Spec's `allowed_transforms` whitelist |
| `add_scm_*` (all SCM transforms) | `generation_baseline` | All others | Additionally requires `SCMContextProvider` |
| `add_hard_constraints` | `generation_baseline` | All others | Requires `hard_constraints` variable in context |

### H2: Spec × Strategy Compatibility

| Spec | Valid Strategies | Invalid Strategies | Enforcement |
|---|---|---|---|
| `generation_baseline` | `single_call`, `repair_loop`, `retry_harness` | `contract_gated` (uses its own specs) | Spec's `allowed_strategies` |
| `generation_leg` | `single_call` | All multi-step strategies | LEG is single-call by design |
| `cge_elicit`, `cge_code`, `cge_retry` | `contract_gated` only | All others | Strategy-owned specs |
| `retry_initial`, `retry_feedback`, `retry_critique` | `retry_harness` only | All others | Strategy-owned specs |
| `classify_reasoning` | All strategies (as classifier stage) | None as generation stage | `standalone = false` |

### H3: Spec × Contract Compatibility

| Spec | Valid Contracts | Invalid Contracts |
|---|---|---|
| `generation_baseline` | `json_v2_filedict`, `json_v1_code` | `leg_structured`, `raw_verdict`, `raw_json_freeform` |
| `generation_leg` | `leg_structured` | All others |
| `classify_reasoning` | `raw_verdict` | All others |
| `retry_critique` | `raw_json_freeform` | All others |
| `cge_elicit` | `raw_json_freeform` | All others |

### H4: Enforcement Points

All compatibility checks run at startup (config load + registry validation). No compatibility check happens at runtime. If a run starts, all combinations have been pre-validated.

Fatal error format: `"COMPATIBILITY ERROR: {entity_a} ({type_a}) is not compatible with {entity_b} ({type_b}). Declared valid: {valid_set}."`

---

## SECTION I — Operational Failure Policy

### I1: Failure Classes

| Phase | Failure Class | Severity | Abort Scope | Logging | Dry-Run | Shadow Mode |
|---|---|---|---|---|---|---|
| Startup | Registry component missing | FATAL | Entire run | Error log + stderr | Report + stop | Report + stop |
| Startup | Registry spec references missing component | FATAL | Entire run | Error log + stderr | Report + stop | Report + stop |
| Startup | Compatibility violation | FATAL | Entire run | Error log + stderr | Report + stop | Report + stop |
| Startup | Config references missing spec/transform/contract | FATAL | Entire run | Error log + stderr | Report + stop | Report + stop |
| Startup | Jinja2 template syntax error | FATAL | Entire run | Error log with file path + line | Report + stop | Report + stop |
| Startup | Jinja2 template contains control flow | FATAL | Entire run | Error log with file path | Report + stop | Report + stop |
| Assembly | Missing context variable | FATAL | Current case | Error log with variable name + provider + spec | Skip case, continue run | Log divergence, continue |
| Assembly | Selection rule finds no matching component | FATAL | Current case | Error log with case_id + transform + tiers tried | Skip case, continue run | Log divergence, continue |
| Assembly | Transform targets nonexistent slot | FATAL | Entire run (config error) | Error log | Report + stop | Report + stop |
| Assembly | Singleton slot collision (two inserts) | FATAL | Current case | Error log with both transforms | Skip case, continue run | Log divergence, continue |
| Rendering | Jinja2 UndefinedError | FATAL | Current case | Error log with template name + variable | Skip case, continue run | Log divergence, continue |
| Execution | API call failure | RETRIABLE | Current call | Error log with call_id + error | Skip case | Log + continue |
| Response | Parser returns `success=false` | DEGRADED | None (continue with degraded data) | Warning log with parse_error | N/A | Log + continue |
| Response | Validator returns violations | DEGRADED | None (continue with annotated data) | Warning log with violations | N/A | Log + continue |
| Response | Contract mismatch (parser returns unexpected structure) | FATAL | Current case | Error log with contract + actual structure | Skip case, continue run | Log + continue |
| Logging | Call log write failure | NON-FATAL | None | Error to stderr | N/A | N/A |

### I2: Dry-Run Mode

A full dry-run mode that exercises the entire pipeline without making LLM calls:
- Loads registry, validates all components/specs/contracts
- Loads experiment config, validates all conditions
- For each case × condition: resolves plan, collects context, renders prompt, logs manifest
- Reports any errors found
- Does NOT call `call_model`
- Exits with code 0 if all cases/conditions resolve cleanly, code 1 otherwise

---

## SECTION J — Subsystem Subsumption and Deletion

### J1: Subsumption Criteria

An old subsystem is eligible for deletion ONLY when ALL of the following are true:

1. The new subsystem produces text-equivalent output for every input the old subsystem handled (verified by full ablation run).
2. The new subsystem logs strictly more information (all old logging is preserved or superseded).
3. The new subsystem's error handling is at least as strict (no silent failures that the old system caught).
4. Zero call sites reference the old subsystem (verified by grep).
5. At least one full ablation run has completed successfully on the new path with zero divergences.

### J2: Specific Subsumption Plan

| Old Subsystem | New Subsystem | Subsumption Evidence Required |
|---|---|---|
| `execution.py:build_prompt()` 18-branch dispatch | SelectionEngine + AssemblyEngine | Text equivalence for all 18 conditions on all cases |
| `nudges/router.py` per-case mapping | SelectionEngine override ladder | Same component selected for every (case, condition) pair |
| `nudges/core.py` operator functions | Component text files + transforms | Byte-identical rendered nudge text |
| `prompts.py` case-specific nudges | Component text files + selection rules | Byte-identical rendered nudge text |
| `llm.py` output instruction append | OutputInstruction components in specs | Output instruction text identical in final prompt |
| `evaluator.py:_CLASSIFY_PROMPT` | `classify_reasoning` spec + components | Byte-identical classifier prompt |
| `leg_reduction.py:build_leg_reduction_prompt` | `generation_leg` spec + components | Byte-identical LEG prompt |
| `contract.py` prompt builders | CGE spec + components | Byte-identical CGE prompts |
| `retry_harness.py` prompt builders | Retry specs + components | Byte-identical retry prompts |
| `templates.py` + `templates/*.jinja2` (current dead system) | PromptRegistry (subsumes template loading, hashing, validation) | Registry provides all functionality of current templates.py |

### J3: Post-Deletion Audit

After each deletion:
- Run the full test suite
- Run a single-case smoke test (`alias_config_a`, baseline + leg_reduction)
- Verify `calls_flat.txt` hashes match the pre-deletion verification run
- Grep the codebase for any remaining references to the deleted subsystem

### J4: Rollback

If post-deletion audit fails:
- Revert the deletion commit
- Re-enter shadow mode to investigate the discrepancy
- Do not re-attempt deletion until the root cause is identified and fixed

---

## SECTION K — Design Risks

### K1: Transform Explosion

**Risk:** Each new nudge condition adds a transform + component. With 16 nudge conditions and growing, the manifest becomes large.

**Mitigation:** Transforms for simple nudges are structurally identical (one `append` operation to the `nudge` stack slot). They differ only in which component they reference. A code generator or manifest template could produce them, but even manually, each is 4 lines of YAML. The manifest is append-only for new conditions.

**Residual risk:** Acceptable. The manifest size scales linearly with the number of conditions, which is bounded by experimental design.

### K2: Config Sprawl

**Risk:** `manifest.yaml` + experiment config + component text files + SCM data = many files.

**Mitigation:** Clear directory structure: `prompts/components/` for text, `prompts/manifest.yaml` for structure, `configs/` for experiments. Startup validation catches all structural errors before any LLM calls.

### K3: Invalid Comparability

**Risk:** Researcher compares two conditions that differ on multiple dimensions.

**Mitigation:** Analysis tool checks dimension-count per pair. Config makes all dimensions visible. This is advisory — the system does not block multi-dimension comparisons, but it flags them.

### K4: Prompt Lineage Ambiguity

**Risk:** Component files modified after a run. Old run's hashes no longer match current files.

**Mitigation:** Run metadata logs all component hashes at startup. Git hash logged in metadata. `git show {hash}:prompts/components/{name}` recovers exact text. Raw prompt string in call logs is always sufficient for replay.

### K5: Replay Breakage

**Risk:** Component renamed or deleted. Old run's provenance references dead names.

**Mitigation:** Raw prompt string (`prompt_raw` in call logs) is the authoritative replay artifact. Provenance is the authoritative audit artifact. If provenance references are broken, replay still works from the raw string.

### K6: Spec Proliferation

**Risk:** Each structurally distinct prompt needs its own spec. Currently 12+ specs.

**Mitigation:** This is inherent complexity made explicit. The current system has the same number of structurally distinct prompts hidden in Python functions. Making them named specs is a net improvement.

### K7: Context Provider Staleness

**Risk:** Provider caches stale data across lifecycle boundaries.

**Mitigation:** Each provider declares its lifecycle. The assembly engine invalidates provider caches at lifecycle boundaries. RetryContextProvider is fresh each iteration. TaskContextProvider is fresh each case. Enforcement: providers do not share state.

### K8: Shadow Mode Performance

**Risk:** Running two prompt assembly paths doubles assembly time during migration.

**Mitigation:** Assembly is fast (string formatting). API calls dominate runtime by 1000x. Shadow mode adds negligible overhead.

---

*End of v3 design document. No implementation performed.*
