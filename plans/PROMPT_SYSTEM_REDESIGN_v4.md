# Prompt System Redesign — Architecture Document v4

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** v1, v2, v3

---

## SECTION A — Architecture Stack

---

### A1: PromptComponent

**What it is:** An immutable block of Jinja2 template text, loaded from a file at startup.

**Fields:**
- `name` — globally unique identifier
- `source_path` — file path relative to `prompts/components/`
- `template` — compiled Jinja2 template object (StrictUndefined)
- `required_variables` — `frozenset[str]`, extracted from Jinja2 AST
- `content_hash` — SHA-256 of raw source text
- `child_slots` — ordered list of named child slot declarations (may be empty). See Section A-Nesting.

**Invariants:**
- Immutable after load.
- `required_variables` computed by AST walk.
- No control flow except `{% block %}` declarations for child slots (validated at startup — `{% if %}`, `{% for %}`, `{% macro %}` rejected).
- Duplicate `name` is fatal at startup.

**Forbidden:**
- Business logic.
- Knowledge of conditions, models, cases, execution.
- Importing or referencing other components by name (child slots are structural declarations, not component references).

---

### A2: PromptSpec

**What it is:** A static registered recipe declaring the structure of a prompt family.

**Fields:**
- `name` — globally unique identifier
- `stage` — one of: `generation`, `classifier`, `critique`, `contract_elicit`, `contract_code`, `contract_retry`, `retry_initial`, `retry_feedback`, `evaluator`
- `slots` — ordered list of `SlotDeclaration` objects
- `response_contract` — name of the ResponseContract
- `required_context_providers` — set of ContextProvider names
- `allowed_transforms` — set of PromptTransform names (whitelist). Empty = no transforms allowed.
- `allowed_strategies` — set of ExecutionStrategy names
- `standalone` — boolean. If true, selectable as top-level ablation target.

**SlotDeclaration:**
- `name` — unique within spec
- `cardinality` — `singleton` or `stack`
- `default_component` — component name or null
- `allows_nesting` — boolean. If true, transforms may target child slots declared by the component occupying this slot. If false, child slots are ignored.

**Invariants:**
- Immutable after registration.
- All defaults, contracts, transforms, strategies validated at startup.

---

### A-Nesting: Controlled Nesting Model

Nesting is allowed under these explicit rules:

1. **A component may declare child slots** in its template using `{% block slot_name %}{% endblock %}`. These are structural declarations, not content.

2. **A parent slot must have `allows_nesting = true`** for child slots to be targetable by transforms. If `allows_nesting = false`, the component's child slots are rendered as empty blocks.

3. **Transforms may target child slots** using dotted notation: `parent_slot.child_slot`. The parent slot must be occupied (the child slot exists only when a component with that child declaration occupies the parent).

4. **Nesting is exactly one level deep.** A child slot's component may NOT declare its own child slots. This is validated at startup: if a component occupying a child slot declares further children, startup fails.

5. **Rendering order:** Parent component is rendered first. Child slot content is injected into the rendered parent at the `{% block %}` positions. The Jinja2 template inheritance mechanism handles this natively.

**When nesting is appropriate:**
- A reasoning scaffold component declares a `verification_steps` child slot.
- A transform inserts specific verification step content into that child slot.
- The parent scaffold controls the surrounding structure; the child controls the specific steps.

**When nesting is NOT appropriate:**
- Simple append of nudge text after the base prompt. Use stack slots at the spec level instead.

**Current system usage:** No current prompts require nesting. All existing prompts compose at the spec level via stack slots. Nesting exists as a capability for future structured prompts (e.g., multi-section reasoning scaffolds) without requiring a redesign.

---

### A3: PromptTransform

**What it is:** A pure structural modification targeting specific slots in a PromptSpec. Transforms operate on **current slot state** (after all prior transforms), not on the original spec state.

**Fields:**
- `name` — globally unique identifier
- `operations` — ordered list of slot operations:
  - `insert(component_name, slot_name)` — singleton, must be empty
  - `replace(component_name, slot_name)` — singleton, overwrites
  - `remove(slot_name)` — singleton, clears
  - `remove(slot_name, component_name)` — stack, removes named entry
  - `append(component_name, slot_name)` — stack, adds to end
  - `prepend(component_name, slot_name)` — stack, adds to front
  - `append(component_name, parent_slot.child_slot)` — nested child slot (if parent allows nesting)
- `additional_context_variables` — extra variables needed
- `compatible_specs` — set of PromptSpec names
- `compatible_contracts` — set of ResponseContract names
- `selection_rule` — optional, for dynamic component resolution (Section F)

**Key semantic: transforms compose via slot state, not transform identity.**

A transform sees the slot contents left by all prior transforms. It does NOT know which transforms ran before it. It CAN depend on structural state (e.g., "append to the nudge stack that already contains items"). It CANNOT depend on transform identity (e.g., "only apply if transform X ran").

This means:
- Transform A inserts a reasoning scaffold into `nudge` stack
- Transform B appends verification steps into `nudge` stack (or into the scaffold's child slot if the scaffold declares one and the parent slot allows nesting)
- B does not know A's name. B sees that the nudge stack has content and appends after it.

**Invariants:**
- Stateless and pure.
- Targets only slots declared by the spec (or child slots declared by components in those slots).
- Applying the same transform twice: appends twice to stack (valid), or fails on occupied singleton (detected as error at assembly).
- Transforms may NOT introduce new spec-level slots. They may target existing child slots in components.

**Forbidden:**
- Text generation, variable binding, LLM calls, I/O.
- Modifying the ResponseContract.
- Depending on transform identity (only structural state).

---

### A4: ResponseContract

**What it is:** A first-class registry object owning the complete response processing pipeline.

**Fields:**
- `name` — globally unique identifier
- `output_instruction_component` — component name or null
- `pipeline` — the ordered response processing chain (see below)
- `error_classification` — mapping from failure types to categories
- `reconstruction_policy` — `file_dict`, `code_blob`, or `metadata_only`

**Response Processing Pipeline (strict order, no reordering):**

```
STAGE 1: PARSE
  Input:  raw response string
  Output: ParseResult {success, format_detected, fields, parse_error, raw_fallback_used}
  Failure behavior:
    - If success=false and raw_fallback_used=false → TOTAL_FAILURE
    - If success=false and raw_fallback_used=true → DEGRADED (continue with raw_fallback data)
    - If success=true → continue
  Logging: format_detected, parse_error, raw_fallback_used
  Parser tiers: configurable per contract. Default: full tier chain (file_dict → lenient → json_direct → code_block → raw_fallback).
    A contract MAY restrict tiers (e.g., classifier contract allows only verdict_parser, no fallback).

STAGE 2: NORMALIZE
  Input:  ParseResult
  Output: NormalizedParseResult
  Operations: applied in order from contract's normalization_policy list.
    Current normalizations: strip_markdown_fences, unescape_newlines.
  Failure behavior: normalization never fails. It transforms or leaves unchanged.
  Logging: which normalizations were applied, whether any changed the data.
  Normalization happens BEFORE validation. Validator sees the normalized result.

STAGE 3: VALIDATE
  Input:  NormalizedParseResult, contract's schema
  Output: ValidationResult {valid, violations[]}
  Failure behavior:
    - Violations are recorded but do NOT block downstream processing.
    - Downstream code receives both the parse result AND the validation result.
    - The evaluation pipeline decides whether to proceed with degraded data.
  Logging: all violations with field names and violation types.

STAGE 4: RECONSTRUCT
  Input:  NormalizedParseResult, reconstruction_policy
  Output: ReconstructedResult {code, reconstruction_status, changed_files, syntax_errors}
  Applies only when reconstruction_policy != metadata_only.
  For file_dict: invokes reconstruct_strict() with file contents.
  For code_blob: extracts code field directly.
  Failure behavior:
    - Reconstruction failure (syntax errors, missing files) is logged and annotated.
    - Does NOT block downstream. Evaluation receives reconstruction status.
  Logging: reconstruction_status, changed_files, syntax_errors, recovery_applied.

STAGE 5: RETURN
  Output: InterpretedResponse {parse_result, normalization_applied, validation_result, reconstruction_result, error_category}
  error_category: one of SUCCESS, DEGRADED, PARSE_FAILURE, RECONSTRUCTION_FAILURE, TOTAL_FAILURE
    Determined by the worst stage outcome.
```

**Whether parser failure blocks downstream:** No. The pipeline always runs to completion. Each stage annotates its result. The evaluation pipeline receives the full InterpretedResponse and decides how to proceed based on `error_category`. This matches the current system's behavior where `raw_fallback` produces degraded but usable data.

**Whether contracts can restrict parser tiers:** Yes. The `raw_verdict` contract for the classifier restricts parsing to the verdict parser only (no fallback chain). The `leg_structured` contract restricts to the LEG parser only. The `json_v2_filedict` contract uses the full tier chain. This is declared in the contract and enforced by the parser dispatcher.

---

### A5: ContextProvider (DAG Model)

**What it is:** A scoped supplier of variables. Providers form a directed acyclic graph where providers may depend on other providers' outputs.

**Dependency rules:**
- Each provider declares its dependencies as a set of other provider names.
- The dependency graph is validated at startup for acyclicity. Cycle detected → fatal startup error.
- Resolution order is topological: providers are invoked in dependency order so that all inputs are available.
- A provider's output is immutable once produced for a given scope.

**Ownership rules:**
- Every variable has exactly one owning provider. Two providers declaring the same variable name is a fatal startup error.
- Truncation happens ONLY in the owning provider.
- A provider that depends on another provider's output records the upstream provenance hash in its own provenance record.

**Concrete provider DAG:**

```
TaskContextProvider (no deps)
  → task, case_id, failure_mode, hard_constraints

CodeContextProvider (depends on: TaskContextProvider)
  → code_files_block, file_paths, file_entries
  (derives code_files_block from case["code_files_contents"] using _format_code_files;
   records upstream: hash of each source file)

SCMContextProvider (depends on: TaskContextProvider)
  → scm_edges_text, scm_constraints_text, scm_invariants_text, ...
  (reads from scm_data/{case_id}.json; records upstream: hash of SCM file)

OutputInstructionContextProvider (depends on: CodeContextProvider)
  → file_entries
  (derives from file_paths; records upstream: file_paths hash)

ClassifierContextProvider (depends on: TaskContextProvider, execution output)
  → failure_types, classifier_task, classifier_code, classifier_reasoning
  (truncates from full values; records: original hash, truncated hash, lengths, limit)
  NOTE: "execution output" is not a provider — it is runtime state passed explicitly.
  ClassifierContextProvider receives parsed reasoning/code as constructor args
  from the execution engine, not from another provider. This is a lifecycle boundary,
  not a provider dependency.

RetryContextProvider (depends on: TaskContextProvider, CodeContextProvider, iteration state)
  → original_code, previous_code, test_output, critique_json, contract_json, adaptive_hint, trajectory_context
  NOTE: iteration state (previous attempt results) is passed explicitly from the
  execution engine, not from another provider. Same lifecycle boundary as above.

ContractContextProvider (depends on: TaskContextProvider, CodeContextProvider, contract state)
  → contract_json, contract_schema_text, violations_text
  NOTE: contract data comes from the CGE execution stage, not from a provider.
```

**Lifecycle boundaries:** Some providers receive runtime state that comes from LLM call results within the same execution strategy. This state is NOT provided by other providers — it crosses the provider/execution boundary. The execution engine passes it explicitly when constructing the provider instance for that stage. This is the correct design because:
- Provider outputs for a given scope are immutable
- LLM call results are produced by the execution engine, not by providers
- Mixing "data that exists before any LLM call" with "data produced by a previous LLM call" requires explicit handoff, not implicit dependency

**Provenance chaining for derived variables:**
```
{
  "name": "code_files_block",
  "provider": "CodeContextProvider",
  "raw": false,
  "derivation": "format_code_files",
  "value_hash": "3b1c...",
  "upstream": [
    {"variable": "code_files_contents.config.py", "hash": "a7f2...", "provider": "case_data"},
    {"variable": "code_files_contents.utils.py", "hash": "e4d1...", "provider": "case_data"}
  ]
}
```

**Caching:** Providers cache per their declared lifecycle scope. Cache key is the hash of all inputs (constructor args + upstream provider outputs). If the cache key matches, the cached output is reused. Cache is invalidated when lifecycle scope changes (new case, new iteration).

---

### A6: ComponentBinding

**What it is:** A resolved assignment of a component to a slot with full provenance.

**Fields:**
- `slot_name` — which slot (may include dotted path for child slots)
- `component_name` — resolved component name
- `component_hash` — content hash
- `source` — `"spec_default"`, `"transform:{name}"`, `"selection_rule:{tier}"`
- `override_tier` — `"case_override"`, `"family_failure_mode"`, `"failure_mode"`, `"generic_default"`, or `null` (for non-selection-rule bindings)
- `position_in_stack` — integer index for stack slots, null for singletons
- `replaced` — name of previously bound component if this binding replaced one, null otherwise

---

### A7: ResolvedPromptPlan

**What it is:** Structural provenance, created after spec resolution and transform application, BEFORE rendering.

**Fields:**
- `spec_name`, `transforms_applied` (ordered), `response_contract_name`
- `bindings` — ordered list of ComponentBinding
- `required_variables` — union of all component requirements
- `required_providers` — set of provider names
- `plan_hash` — SHA-256 of canonical serialization

**Invariants:**
- Immutable. Deterministic. Can be validated before rendering.

---

### A8: RenderedPrompt

**What it is:** Concrete rendered artifact for a single LLM call.

**Fields:**
- `plan` — reference to ResolvedPromptPlan
- `rendered_parts` — ordered `(component_name, rendered_text, rendered_hash)` tuples
- `bound_variables` — `{var_name: VariableProvenance}` dict
- `final_prompt` — joined string
- `final_prompt_hash` — SHA-256 of final_prompt
- `context_provider_versions` — `{provider_name: cache_key_hash}`

**Invariants:**
- Immutable. Deterministic. Created once per LLM call.

---

### A9: ExecutionStrategy

**What it is:** An explicit orchestration model with typed stage transitions and explicit state passing.

**Fields:**
- `name` — globally unique identifier
- `stages` — ordered list of `StageDeclaration`
- `stop_conditions` — typed conditions for early termination
- `state_schema` — typed declaration of the state object passed between stages

**StageDeclaration:**
- `stage_name` — identifier within the strategy
- `stage_type` — `llm_call` or `local_computation` (gate checks are local, not LLM)
- `spec_name` — PromptSpec for this stage (null for local_computation stages)
- `transforms_source` — `"experiment"` or `"internal"`
- `internal_transforms` — list of transforms (only when source = internal)
- `context_providers` — provider names for this stage
- `response_contract` — contract name (must match spec's contract)
- `inputs` — typed list of state fields consumed from prior stages
- `outputs` — typed list of state fields produced by this stage
- `gate` — typed condition determining whether this stage executes

**Typed gate conditions (not strings):**
- `always` — stage always executes
- `prior_failed(stage_name)` — executes if named prior stage's evaluation failed
- `gate_violated(stage_name)` — executes if named prior stage's gate check found violations
- `iteration_limit_not_reached(max)` — for retry loops
- `not_converged` — for retry loops, combined with iteration_limit

**State object:** A typed dict that accumulates across stages. Each stage declares which fields it reads (inputs) and which it writes (outputs). The execution engine validates:
- All inputs are available (produced by a prior stage or initial state)
- No output name collisions (two stages writing the same field is fatal)
- State is immutable once written (a stage cannot overwrite a previous stage's output)

**Concrete example for `retry_harness`:**

```
state_schema:
  initial_code: str          # from case data
  current_code: str          # updated each iteration
  current_eval: dict         # evaluation result
  test_output: str           # test failure details
  critique: dict | null      # from critique stage
  iteration: int             # counter
  converged: bool            # stop flag

stages:
  - name: "initial_generation"
    type: llm_call
    spec: "retry_initial"
    transforms_source: "experiment"
    inputs: []
    outputs: [current_code, current_eval, test_output]
    gate: always

  - name: "critique"
    type: llm_call
    spec: "retry_critique"
    transforms_source: "internal"
    inputs: [current_code, test_output]
    outputs: [critique]
    gate: prior_failed("initial_generation") OR prior_failed("retry_generation")

  - name: "retry_generation"
    type: llm_call
    spec: "retry_feedback"
    transforms_source: "internal"
    inputs: [initial_code, current_code, test_output, critique]
    outputs: [current_code, current_eval, test_output]  # overwrites prior iteration
    gate: not_converged AND iteration_limit_not_reached(5)

  - name: "classify"
    type: llm_call
    spec: "classify_reasoning"
    transforms_source: "internal"
    inputs: [current_code, current_eval]
    outputs: [classification]
    gate: always
```

Note: `retry_generation` overwrites `current_code` etc. This is allowed because it is the same logical field updated per iteration, not a collision between two different stages. The state schema declares `current_code` as mutable-per-iteration.

**Partial execution logging:** If a strategy aborts mid-execution (API error, stop condition), all completed stages' RenderedPrompts and InterpretedResponses are logged. The strategy logs which stages completed and which were skipped, with the reason.

---

### A10: ExperimentCondition

**What it is:** A researcher-facing config bundle. NOT a runtime primitive.

**Config fields:**
- `name` — researcher-facing label
- `base_spec` — PromptSpec name (generation stage)
- `transforms` — ordered list of transform names
- `execution_strategy` — strategy name
- `response_contract` — optional override (defaults to spec's contract)

**Researcher-controlled:** `base_spec`, `transforms`, `execution_strategy`.
**Strategy-internal:** classifier spec, critique spec, retry feedback spec, internal transforms.
**Forbidden overrides:** classifier contract, strategy-internal transforms, strategy-internal specs.

---

## SECTION B — System Engine Boundaries

### B1: SelectionEngine

**Owns:** Resolving abstract component references to concrete component names.

**Precedence ladder:**
1. Explicit case override: `{base_name}_{case_id}`
2. Family + failure_mode: `{base_name}_{family}_{failure_mode}`
3. Failure_mode only: `{base_name}_{failure_mode}`
4. Generic default: `{base_name}_generic`

**Tie-breaking:** At each tier, at most one component may match. Two components matching at the same tier (e.g., two components both named `nudge_diagnostic_hidden_dependency`) is impossible because component names are globally unique (enforced at registry load). If the naming convention COULD produce ambiguity (e.g., case_id contains an underscore that collides with the tier separator), the registry validation phase checks for this at startup and fails with a descriptive error listing the ambiguous names.

**Caching:** Selection results are cached per (transform, case_id) pair for the duration of a case's evaluation. Cache is invalidated on new case.

### B2: AssemblyEngine

**Owns:** PromptSpec → ResolvedPromptPlan → RenderedPrompt.

**The single prompt build path.** This is the ONE function that constructs prompts.

**Enforcement mechanism:** `call_model()` is modified to require a `RenderedPrompt` object, not a raw string. The function signature becomes:

```
call_model(rendered_prompt: RenderedPrompt, model: str) → str
```

`call_model` extracts `rendered_prompt.final_prompt` internally and passes it to the API. It also extracts the assembly manifest for logging.

**This makes bypass structurally impossible.** There is no way to call the LLM without first producing a RenderedPrompt through the AssemblyEngine. A developer who tries to pass a raw string gets a type error.

**During migration (Phase A):** A temporary compatibility wrapper allows raw strings with a deprecation warning. This wrapper is removed in Phase B.

### B3: ExecutionEngine

**Owns:** Orchestrating LLM calls per ExecutionStrategy.

For each stage:
1. Constructs context providers with appropriate runtime state
2. Calls AssemblyEngine → RenderedPrompt
3. Calls `call_model(rendered_prompt, model)` → raw response
4. Calls ResponseInterpreter → InterpretedResponse
5. Updates strategy state with stage outputs
6. Evaluates next stage's gate condition

**Forbidden:** Prompt construction, response parsing, transform application.

### B4: ResponseInterpreter

**Owns:** Processing responses per ResponseContract pipeline (parse → normalize → validate → reconstruct).

**Forbidden:** Prompt construction, LLM calls, modifying raw response.

---

## SECTION C — Unified Registry Validation Phase

A single validation pass runs at startup, after all components, specs, transforms, contracts, strategies, and providers are loaded. The validation is exhaustive and fails fatally on any inconsistency.

**Checks (in order):**

1. **Component uniqueness:** No duplicate component names.
2. **Component template validity:** All templates compile. No forbidden control flow. All `required_variables` extracted.
3. **Component child slot validity:** If a component declares child slots, verify the slot names are valid identifiers.
4. **Nesting depth:** No component in a child slot position declares its own children (depth limit = 1).
5. **Spec completeness:** All `default_component` names exist. All `response_contract` names exist. All `allowed_transforms` exist. All `allowed_strategies` exist.
6. **Slot naming:** No duplicate slot names within a spec.
7. **Transform validity:** All `compatible_specs` exist. All `compatible_contracts` exist. All slot references in operations exist in the target specs.
8. **Transform-spec compatibility:** For each transform, every spec in `compatible_specs` must list this transform in its `allowed_transforms`. Bidirectional check.
9. **Transform-contract compatibility:** For each transform, every contract in `compatible_contracts` must be the contract of at least one compatible spec.
10. **Selection rule satisfiability:** For each transform with a selection rule, verify that at least the generic default component (`{base_name}_generic`) exists. Warn (not fatal) if case-specific or failure-mode-specific components are missing for known cases.
11. **Selection ambiguity:** For all component names matching `{base_name}_{suffix}` patterns, verify no two components at the same tier could match the same case. Fatal if ambiguity detected.
12. **Contract completeness:** All `output_instruction_component` names (if non-null) exist as components. All parsers are registered. All validators are registered. All normalizations are registered.
13. **Strategy validity:** All `spec_name` references exist. All specs have this strategy in their `allowed_strategies`. State schema is internally consistent (all inputs available from prior outputs or initial state). Gate conditions reference valid stage names. Dependency graph is acyclic.
14. **Provider validity:** All providers declare valid dependencies. Dependency graph is acyclic. No variable name appears in more than one provider's output set.
15. **Experiment config validity:** All `base_spec`, `transforms`, `execution_strategy`, `response_contract` references exist. Transform-spec and transform-contract compatibility holds. Forbidden overrides are not present.

**Output:** Either all checks pass (run proceeds) or a list of all errors found (run aborts with full error report). Validation does NOT stop at first error — it collects all errors for a single diagnostic dump.

---

## SECTION D — Selection Precedence (strengthened)

### Uniqueness guarantees:

- Component names are globally unique (Check 1 above).
- The tier separator is `__` (double underscore), not `_`. This prevents collision between `nudge_diagnostic_hidden_dependency` (one component name) and a case_id that happens to contain `hidden_dependency`. Convention: `{base_name}__{tier_value}`. Example: `nudge_diagnostic__hidden_dependency`, `nudge_diagnostic__alias_config_a`.
- At startup, Check 11 verifies that for every selection rule, at most one component matches each case at each tier. If two components both match the same case at tier 3 (failure_mode), that is fatal.

### Explicit mapping overrides:

If the naming convention is insufficient for a particular case, the manifest supports explicit mappings:

```yaml
selection_overrides:
  nudge_diagnostic:
    case_overrides:
      alias_config_a: "nudge_diagnostic__custom_alias_a"
    failure_mode_overrides:
      HIDDEN_DEPENDENCY: "nudge_diagnostic__hidden_dep_v2"
```

These overrides take precedence over naming-convention resolution. They are validated at startup (referenced components must exist).

---

## SECTION E — Debugging Surface

### E1: Prompt Inspection

Every RenderedPrompt can be exported as a human-readable inspection format:

```
=== PROMPT INSPECTION ===
Spec:      generation_baseline
Transforms: [add_nudge_diagnostic]
Contract:  json_v2_filedict
Plan Hash: d41d...

COMPONENTS (4):
  [1] task_block (spec_default)
      hash: a3f2...
      --- 450 chars ---

  [2] code_files_block (spec_default)
      hash: 7b1c...
      --- 1274 chars ---

  [3] nudge_diagnostic__hidden_dependency (transform:add_nudge_diagnostic, tier:failure_mode)
      hash: e9d4...
      --- 320 chars ---

  [4] output_instruction_v2 (contract:json_v2_filedict)
      hash: 1f0a...
      --- 280 chars ---

VARIABLES (5):
  task: hash=e4d1... len=450 provider=TaskContextProvider
  code_files_block: hash=3b1c... len=1274 provider=CodeContextProvider (derived)
  file_entries: hash=9a2b... len=89 provider=OutputInstructionContextProvider (derived)
  ...

FINAL PROMPT: hash=d41d... len=2324

=== END INSPECTION ===
```

### E2: Prompt Diff

Given two RenderedPrompts (e.g., from two conditions on the same case), a diff tool produces:

```
=== PROMPT DIFF: baseline vs diagnostic ===
Spec:       SAME (generation_baseline)
Contract:   SAME (json_v2_filedict)
Transforms: DIFF
  baseline:   []
  diagnostic: [add_nudge_diagnostic]

Components:
  [1] task_block:        SAME (hash a3f2...)
  [2] code_files_block:  SAME (hash 7b1c...)
  [3] nudge slot:        DIFF
      baseline:   (empty)
      diagnostic: nudge_diagnostic__hidden_dependency (hash e9d4..., 320 chars)
  [4] output_instruction: SAME (hash 1f0a...)

Variables:
  task:             SAME
  code_files_block: SAME
  file_entries:     SAME

Final prompt:
  baseline:   hash=aaaa... len=2004
  diagnostic: hash=bbbb... len=2324
  text diff:  +320 chars (nudge block inserted between code_files and output_instruction)
```

### E3: Variable Diff

For comparing the same condition across two cases:

```
=== VARIABLE DIFF: alias_config_a vs lost_update (diagnostic) ===
  task:             DIFF (hash a→b, len 450→620)
  code_files_block: DIFF (hash c→d, len 1274→2100)
  nudge component:  DIFF (diagnostic__hidden_dependency → diagnostic__temporal_ordering)
```

### E4: Implementation expectation

These inspection and diff formats are produced by utility functions that take RenderedPrompt objects as input. They are not part of the core pipeline — they are debugging tools. They write to stdout or to a file, not to the call log. The call log contains the machine-readable manifest; these tools produce the human-readable view.

---

## SECTION F — Performance and Scaling

### F1: Runtime Overhead

| Operation | Cost | Frequency | Impact |
|---|---|---|---|
| Registry load + validation | ~100ms | Once at startup | Negligible |
| Component hashing (SHA-256) | ~1ms per component, ~50 components | Once at startup | Negligible |
| Plan resolution (spec + transforms) | ~0.1ms | Per LLM call | Negligible |
| Context collection | ~1ms (truncation, formatting) | Per LLM call | Negligible |
| Jinja2 rendering | ~0.5ms per component | Per LLM call | Negligible |
| Provenance record construction | ~0.1ms per variable | Per LLM call | Negligible |
| API call | 2,000-15,000ms | Per LLM call | **Dominant** |

The assembly pipeline adds <5ms per LLM call. API calls take 2,000-15,000ms. The overhead is <0.1% of total runtime.

### F2: Memory

- Component templates: ~50 components × ~2KB avg = ~100KB
- Registry metadata: ~50KB
- Per-call RenderedPrompt: ~20KB (prompt text + manifest)
- Per-call provenance: ~5KB

Total memory for the prompt system: <1MB. Negligible compared to Python process overhead (~50MB) and response text accumulation.

### F3: Log Size

Per LLM call, the assembly manifest adds ~2KB to the call log JSON. For a 116-event run with 232 calls, that is ~464KB additional logging. Current call logs are ~4MB per run. The manifest adds ~10%.

### F4: Optional vs Always-On

| Feature | Mode | Justification |
|---|---|---|
| Assembly manifest logging | Always-on | Required for reproducibility. Small cost. |
| Variable provenance | Always-on | Required for debugging. Small cost. |
| Component hashing | Always-on (startup only) | Required for drift detection. One-time cost. |
| Prompt inspection format | On-demand | Debugging tool. Not part of normal pipeline. |
| Prompt diff | On-demand | Analysis tool. Not part of normal pipeline. |
| Full variable preview in provenance | Configurable | Preview first N chars. Default N=100. Set N=0 to disable. |

---

## SECTION G — Migration Plan

### Phase A: Legacy-Equivalent Migration

**Goal:** The new architecture produces byte-identical prompts to the old system. Zero intentional behavior changes.

**Step A0: Extract components**
- Create `prompts/components/` with one `.jinja2` file per component.
- Content is byte-identical to current Python f-strings (with `{var}` → `{{ var }}`).
- Verification: render each template with test variables, compare against f-string output.

**Step A1: Build registry + AssemblyEngine (shadow mode)**
- Implement registry, context providers, assembly pipeline.
- At every existing prompt construction call site, ALSO call AssemblyEngine and compare output.
- Comparison: SHA-256 of both strings. If different, log both strings and abort.

**Step A2: Staged rollout by execution strategy**
- Order: `single_call` (covers baseline + all nudge conditions) → `repair_loop` → `contract_gated` → `retry_harness`.
- For each strategy: migrate call sites, run smoke test (alias_config_a, baseline + leg_reduction), compare call log hashes.
- Then run full ablation (all cases, all conditions for that strategy), compare all prompt hashes.

**Step A3: Migrate classifier and evaluator**
- Replace `_CLASSIFY_PROMPT.format(...)` with AssemblyEngine call.
- Compare classifier prompts (including truncation — must be identical).

**Step A4: Enforce RenderedPrompt-only call_model**
- Change `call_model` signature to require RenderedPrompt.
- Add temporary compatibility wrapper for any remaining raw-string callers.
- Grep codebase for direct string calls — all must be migrated.

**Equivalence gates (ALL must pass per step):**
- **Text equivalence:** SHA-256 match of final prompt string for every call.
- **Contract equivalence:** Same parser invoked, same ParseResult fields.
- **Parse-path equivalence:** Same downstream evaluation result (pass/fail, score) for a reference set of cases.
- **Metric equivalence:** For a full ablation run, pass_rate and LEG_rate per condition must be within 0 of the old system (since prompts are identical, results should be identical up to model nondeterminism at temperature=0).

**Rollback trigger:** Any text equivalence failure after investigation. Any parse-path equivalence failure. Any metric divergence beyond expected temperature-0 variation (which should be zero for deterministic models).

**Staged rollout by case count:**
1. Single case smoke test (1 case × 2 conditions)
2. 5-case validation (5 cases × 2 conditions)
3. Full ablation (58 cases × 2 conditions)

### Phase B: Architecture-Native Improvements

**Goal:** Deliberate, reviewed improvements using the new architecture. Never mixed with Phase A.

**Each change must:**
1. Be a separate, reviewable modification to a component file or manifest entry
2. Include before/after prompt comparison for all affected cases
3. Be flagged in experiment metadata: `prompt_version: "native_v{N}"`
4. Not be combined with other changes in the same experiment run

**Example Phase B changes:**
- Unify generic and case-specific nudge variants (replace 8 pairs with selection-rule resolution)
- Standardize whitespace between components
- Add schema validation to response contracts
- Improve classifier prompt based on error analysis

### Subsumption and Retirement

**Default approach: wrap and subsume, not delete.**

The existing `templates.py` is subsumed by the PromptRegistry. Rather than deleting it, the registry imports and extends its functionality (template loading, hashing, validation). The old module becomes an internal implementation detail of the registry, not a separate system.

The existing parser tier chain in `parse.py` is subsumed by ResponseContract's pipeline configuration. The parsers themselves are reused — the contract just controls which ones run.

**Retirement criteria (after extended stability):**
1. New system has been the sole production path for at least 2 full experiment cycles
2. Zero regression bugs attributable to the new system
3. All old entry points have zero callers (verified by grep + test coverage)
4. Team consensus that the old code is dead

Only then is the old code deleted. Until then, it remains as commented-out or unreachable code, not actively maintained but not deleted.

---

## SECTION H — Design Risks

### H1: Transform Explosion
**Risk:** Many conditions → many transforms. **Mitigation:** Most transforms are structurally identical (one append to nudge stack). They are manifest entries, not code. Adding a condition = one text file + one manifest entry.

### H2: Config Sprawl
**Risk:** Multiple YAML files to maintain. **Mitigation:** Exhaustive startup validation catches all errors. Clear directory structure.

### H3: Invalid Comparability
**Risk:** Multi-dimension condition differences. **Mitigation:** Analysis tool checks dimension count per pair. Config makes all dimensions visible.

### H4: Prompt Lineage Ambiguity
**Risk:** Component files modified after a run. **Mitigation:** Run metadata logs all component hashes + git hash. Raw prompt string in call logs is always sufficient for replay.

### H5: DAG Complexity
**Risk:** Provider dependencies become complex. **Mitigation:** Current system has 7 providers with a shallow DAG (max depth 2). Startup validation enforces acyclicity. Provenance records chain through dependencies.

### H6: Nesting Misuse
**Risk:** Developers add unnecessary nesting complexity. **Mitigation:** Depth limit of 1. Most prompts use flat stack slots. Nesting is opt-in per slot (`allows_nesting = true`). No current prompts require it.

### H7: Shadow Mode Performance
**Risk:** Running two paths doubles assembly time. **Mitigation:** Assembly is <5ms. API calls are 2,000-15,000ms. Shadow mode overhead is <0.1%.

### H8: Migration-Phase Confusion
**Risk:** Someone makes Phase B improvements during Phase A. **Mitigation:** Phase A runs are tagged `prompt_version: "legacy_equivalent"`. Any component file change during Phase A that alters the final prompt hash is detected by the equivalence gate and blocks the run.

---

*End of v4 design document. No implementation performed.*
