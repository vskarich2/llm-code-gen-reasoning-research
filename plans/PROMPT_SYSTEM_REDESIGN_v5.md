# Prompt System Redesign — Architecture Document v5

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** v1, v2, v3, v4

---

## SECTION A — Architecture Stack

---

### A1: PromptComponent

Unchanged from v4. Immutable Jinja2 template text, loaded from file at startup. Fields: `name`, `source_path`, `template`, `required_variables` (frozenset), `content_hash`. May declare `child_slots` via `{% block %}`. No control flow. No business logic.

---

### A2: PromptSpec

Unchanged from v4 except: `allowed_transforms` is validated bidirectionally with transforms. Declares `slots` (singleton or stack, with `allows_nesting` flag), `stage`, `response_contract`, `required_context_providers`, `allowed_strategies`, `standalone`.

---

### A3: PromptTransform

Refined from v4. Operations target slots via current slot state (not original spec). Singleton operations: `insert`, `replace`, `remove`. Stack operations: `append`, `prepend`, `remove(name)`. Child slot operations via dotted notation. Selection rules resolve components dynamically.

**New rule for nesting interaction (fixes v4 issue 3):**

- When a transform replaces a component in a singleton slot that has `allows_nesting = true`, all child slot bindings from prior transforms are **discarded**. The new component's child slots (if any) start empty. Rationale: the child slots belong to the parent component. Replacing the parent invalidates the children.
- When a transform appends to a stack slot, the new component's child slots are independently targetable. They do not inherit content from other stack entries' child slots.
- Ordering within a child slot follows the same rules as spec-level slots: singleton (one component) or stack (ordered by transform application order).
- Two transforms targeting the same child slot: follows the same collision rules as spec-level slots. Two inserts on a singleton child = fatal. Two appends on a stack child = both added in transform order.

---

### A4: ResponseContract

**Significantly revised from v4. The contract now fully owns execution behavior — no downstream ambiguity.**

**Fields:**
- `name` — globally unique identifier
- `output_instruction_component` — component name or null
- `pipeline` — parse → normalize → validate → reconstruct (unchanged from v4)
- `error_policy` — defines behavior for every failure category (NEW)
- `reconstruction_policy` — `file_dict`, `code_blob`, `metadata_only`

**Error Policy (replaces v4's "downstream decides"):**

The contract declares, for each error category, whether processing continues or aborts:

| Error Category | Contract Decision | Logged As |
|---|---|---|
| `TOTAL_FAILURE` (no content extracted) | `abort` or `continue_degraded` | Always logged as ERROR |
| `PARTIAL_PARSE` (some fields missing) | `abort` or `continue_degraded` | Always logged as WARNING |
| `SCHEMA_VIOLATION` (structure ok, values wrong) | `continue_degraded` or `continue_clean` | Logged as WARNING |
| `RECONSTRUCTION_FAILURE` (syntax errors, missing files) | `abort` or `continue_degraded` | Logged as WARNING |
| `NORMALIZATION_CHANGED` (normalization altered data) | `continue_clean` | Logged as INFO |

`abort` = this case is marked as failed with `failure_source=PARSE_FAILURE` or `RECONSTRUCTION_FAILURE`. No evaluation attempted. The error is recorded and the execution strategy moves to the next stage or case.

`continue_degraded` = processing continues with annotated degraded data. `case_validity` is set to `"degraded"`. Evaluation proceeds but results are flagged.

`continue_clean` = not an error condition. Processing continues normally.

**Concrete contract error policies:**

| Contract | TOTAL_FAILURE | PARTIAL_PARSE | SCHEMA_VIOLATION | RECONSTRUCTION_FAILURE |
|---|---|---|---|---|
| `json_v2_filedict` | continue_degraded (raw_fallback) | continue_degraded | continue_degraded | continue_degraded |
| `json_v1_code` | continue_degraded (raw_fallback) | continue_degraded | continue_degraded | N/A |
| `leg_structured` | continue_degraded (fallback extraction) | continue_degraded | continue_degraded | N/A |
| `raw_verdict` | abort (classifier must parse) | abort | N/A | N/A |
| `raw_json_freeform` | continue_degraded | continue_degraded | N/A | N/A |

Note: `raw_verdict` (classifier) aborts on parse failure because a classifier result that cannot be parsed is unusable — the reasoning classification becomes `None`, which is the correct behavior (parse gate). This replaces the current ad-hoc handling with an explicit contract-level decision.

---

### A5: ContextProvider (Unified Model — fixes v4 issue 1)

**The "special injection path" for execution state is eliminated.** ALL variables used in prompt rendering come from providers. Execution state is exposed via `StageOutputProvider` instances.

**Provider types:**

1. **Static providers** — read from case data or static files. No dependencies on execution output.
   - `TaskContextProvider`, `CodeContextProvider`, `SCMContextProvider`, `OutputInstructionContextProvider`

2. **StageOutputProvider** — wraps the output of a prior execution stage as a provider. Created by the ExecutionEngine after each stage completes.
   - `ClassifierInputProvider` — wraps parsed reasoning + code + evaluation result from the generation stage. Owns truncation.
   - `RetryStateProvider` — wraps previous attempt's code, test output, critique. Created fresh each iteration.
   - `ContractStateProvider` — wraps parsed contract JSON from the elicit stage. Created after CGE step 1.

**StageOutputProvider rules:**
- Created by the ExecutionEngine, not by the assembly pipeline.
- Registered into the provider DAG for the specific stage that needs it.
- Immutable once created (wraps a snapshot of stage output).
- Participates in provenance tracking like any other provider.
- Dependency declaration: `ClassifierInputProvider` depends on `TaskContextProvider` (for truncation limits from config). `RetryStateProvider` depends on `CodeContextProvider` (for original code). `ContractStateProvider` depends on `TaskContextProvider`.

**DAG resolution:** Static providers are resolved first (they have no stage output dependencies). StageOutputProviders are created after their source stage completes and injected into the DAG for subsequent stages. The ExecutionEngine manages this lifecycle:

```
Stage 1 (generation):
  Providers available: [TaskCtx, CodeCtx, SCMCtx, OutputInstructionCtx]
  → produces: generation_output

Stage 2 (classify):
  ExecutionEngine creates ClassifierInputProvider(generation_output)
  Providers available: [TaskCtx, ClassifierInputProvider]
  → produces: classification_output
```

**No special injection path.** The ExecutionEngine creates StageOutputProviders and registers them. The AssemblyEngine sees a uniform provider DAG at every stage.

**Provider ownership and uniqueness:** Every variable has exactly one owning provider. StageOutputProviders may NOT redeclare variables owned by static providers. Validated when the StageOutputProvider is registered (before assembly).

---

### A6: ExecutionStrategy State Model (fixes v4 issue 2)

**State is versioned, not mutable-in-place.**

**StageState:** A typed, append-only log of stage outputs. Each stage produces a `StageOutput` record that is appended to the state log. No record is ever modified.

**StageOutput fields:**
- `stage_name` — which stage produced this
- `iteration` — for retry loops, which iteration (0-indexed). For non-loops, always 0.
- `fields` — typed dict of output values
- `timestamp` — when this output was produced
- `fields_hash` — hash of field values for provenance

**Reading state:** When a stage needs an input, it reads from the state log by field name. The resolution rule is: **latest version wins**. For field `current_code`, if the state log contains entries from `initial_generation` (iteration 0) and `retry_generation` (iteration 2), the value from iteration 2 is used.

**Provenance:** Each field read records: which stage wrote it, which iteration, the field hash. This is included in the RenderedPrompt's variable provenance.

**Replay reconstruction:** Given the state log, every stage's inputs can be reconstructed exactly. The log is append-only and immutable, so replay is deterministic.

**Concrete example for retry harness:**

```
State log after 3 iterations:

[0] initial_generation/iter=0: {current_code: "...", current_eval: {...}, test_output: "..."}
[1] critique/iter=0:           {critique: {...}}
[2] retry_generation/iter=1:   {current_code: "...", current_eval: {...}, test_output: "..."}
[3] critique/iter=1:           {critique: {...}}
[4] retry_generation/iter=2:   {current_code: "...", current_eval: {...}, test_output: "..."}
[5] classify/iter=0:           {classification: {...}}

Reading "current_code" at stage 5: resolves to entry [4] (latest)
Reading "critique" at stage 4:    resolves to entry [3] (latest before stage 4)
```

**Gate conditions (typed, from v4):** `always`, `prior_failed(stage_name)`, `gate_violated(stage_name)`, `iteration_limit_not_reached(max)`, `not_converged`. Each evaluates against the state log.

---

### A7: ComponentBinding

Unchanged from v4. Records slot, component, hash, source, override tier, stack position, replacement info.

---

### A8: ResolvedPromptPlan

Unchanged from v4. Structural provenance before rendering. Fields: spec_name, transforms_applied, response_contract_name, bindings, required_variables, required_providers, plan_hash.

---

### A9: RenderedPrompt

Unchanged from v4. Concrete rendered artifact. Fields: plan, rendered_parts, bound_variables, final_prompt, final_prompt_hash, context_provider_versions.

---

### A10: ExperimentCondition

Unchanged from v4. Config-layer bundle decomposing into spec + transforms + strategy + contract.

---

### A11: PromptIdentity (NEW — fixes v4 issue 6)

**What it is:** A formal, unique identifier for a prompt configuration. Distinct from both `plan_hash` and `final_prompt_hash`.

**Definition:**

```
PromptIdentity = hash(
  spec_name,
  sorted(transforms_applied),
  response_contract_name,
  sorted(component_bindings as (slot, component_name, component_hash) tuples)
)
```

**How it differs from existing hashes:**

| Concept | What it captures | Varies with... |
|---|---|---|
| `plan_hash` | Structural recipe (spec + transforms + bindings) | Transform changes, component changes |
| `final_prompt_hash` | Exact rendered text | Variable values (different cases produce different prompts) |
| `PromptIdentity` | Configuration fingerprint | Transform changes, component changes. Does NOT vary with case data. |

**Use cases:**
- **Caching:** Two cases with the same PromptIdentity and same variable values will produce the same final prompt. The assembly engine can cache RenderedPrompt plans by PromptIdentity.
- **Experiment tracking:** All cases within a condition share the same PromptIdentity (because they share the same spec + transforms + components). Different conditions have different PromptIdentities.
- **Deduplication:** If two conditions accidentally produce the same PromptIdentity, the system warns that they are equivalent (no ablation value).
- **Replay:** Given a PromptIdentity + variable values, the exact prompt can be reconstructed.

**Where logged:** In the assembly manifest for every call, alongside `plan_hash` and `final_prompt_hash`.

---

## SECTION B — System Engine Boundaries

### B1: SelectionEngine (revised — fixes v4 issue 5)

**Explicit mapping is the first-class mechanism. Naming convention is the fallback.**

**Resolution order:**

1. **Explicit mapping** in `prompts/manifest.yaml`:
   ```yaml
   selection_mappings:
     nudge_diagnostic:
       case_mappings:
         alias_config_a: "nudge_diagnostic__custom_alias"
       failure_mode_mappings:
         HIDDEN_DEPENDENCY: "nudge_diagnostic__hidden_dep"
         TEMPORAL_ORDERING: "nudge_diagnostic__temporal"
       default: "nudge_diagnostic__generic"
   ```
   The manifest lookup is tried first. If a match is found at any tier, it is used.

2. **Naming convention fallback** (only if no explicit mapping exists for this selection rule):
   - `{base_name}__{case_id}` → `{base_name}__{family}_{failure_mode}` → `{base_name}__{failure_mode}` → `{base_name}__generic`

**Coverage validation at startup:** For every selection rule, and for every case in the case set, the SelectionEngine runs the resolution and verifies that a component is found. If any case has no matching component at any tier, startup fails with: `"SELECTION ERROR: No component found for rule '{rule}' on case '{case_id}' (failure_mode='{fm}'). Tiers tried: [explicit, naming]. Add a mapping or a default component."`

This means: every case is guaranteed to resolve every selection rule before the run starts. No runtime selection failures.

### B2: AssemblyEngine

Unchanged from v4. Single prompt build path. `call_model` requires RenderedPrompt.

### B3: ExecutionEngine

Revised to use StageOutputProviders (A5) and versioned state (A6). Creates StageOutputProviders after each stage and registers them for subsequent stages. Manages state log. Evaluates gate conditions against state log.

### B4: ResponseInterpreter

Revised to enforce contract error policies (A4). No downstream ambiguity — the contract's error_policy determines whether processing continues or aborts for each error category.

---

## SECTION C — Debugging Surface (integrated — fixes v4 issue 7)

### C1: Minimum Always-Logged Data

The following is logged for EVERY LLM call, unconditionally. It is not optional tooling — it is part of the core call log record.

**In `calls/{call_id}.json`:**
```json
{
  "call_id": 108,
  "prompt_raw": "...",
  "response_raw": "...",
  "model": "...",
  "elapsed_seconds": 4.2,
  "prompt_assembly": {
    "prompt_identity": "a1b2c3...",
    "spec_name": "generation_baseline",
    "transforms_applied": ["add_nudge_diagnostic"],
    "response_contract": "json_v2_filedict",
    "components": [
      {"slot": "task", "component": "task_block", "hash": "a3f2...", "source": "spec_default"},
      {"slot": "code_files", "component": "code_files_block", "hash": "7b1c...", "source": "spec_default"},
      {"slot": "nudge[0]", "component": "nudge_diagnostic__hidden_dependency", "hash": "e9d4...", "source": "transform:add_nudge_diagnostic", "tier": "failure_mode"},
      {"slot": "output_instruction", "component": "output_instruction_v2", "hash": "1f0a...", "source": "contract:json_v2_filedict"}
    ],
    "plan_hash": "d41d...",
    "final_prompt_hash": "f7e2..."
  },
  "variable_provenance": [
    {"name": "task", "provider": "TaskContextProvider", "hash": "e4d1...", "length": 450, "raw": true},
    {"name": "code_files_block", "provider": "CodeContextProvider", "hash": "3b1c...", "length": 1274, "raw": false, "derivation": "format_code_files"},
    {"name": "classifier_reasoning", "provider": "ClassifierInputProvider", "hash": "9f3a...", "length": 1000, "raw": false, "derivation": "truncated", "source_length": 3200, "truncation_limit": 1000}
  ]
}
```

This is always written. There is no config flag to disable it. The cost is ~3KB per call, ~700KB per full ablation run. Acceptable.

### C2: Derived Inspection (from logs)

The prompt inspection format and prompt diff format from v4 are derived from the always-logged data above. They are utility functions that read `calls/{call_id}.json` and produce human-readable output.

**Guarantee:** Given any call log file, the inspection and diff tools can reconstruct:
- Which components were used, in what order
- Which variables were injected, from which providers
- What the exact prompt text was
- What the response contract was
- How the prompt differs from another call

This is not optional tooling that might be missing — it reads from data that is always present.

### C3: Inspection in calls_flat.txt

The flat log includes a one-line assembly summary after each call header:

```
[000108] model=gpt-5.4-mini phase=generation case=alias_config_a condition=diagnostic elapsed=4.2s
  → spec=generation_baseline transforms=[add_nudge_diagnostic] contract=json_v2_filedict identity=a1b2c3

=== PROMPT ===
...
```

This adds one line per call. Minimal overhead. Enables quick scanning of which prompt configuration was used without parsing JSON.

---

## SECTION D — Performance (refined — fixes v4 issue 8)

### D1: Worst-Case Analysis

| Scenario | Prompt Size | Hash Cost | Render Cost | Total Assembly |
|---|---|---|---|---|
| Simple baseline (1 file, 500 chars code) | ~2KB | <0.1ms | <0.5ms | <1ms |
| Large case (5 files, 10KB code) | ~15KB | <0.5ms | <1ms | <2ms |
| LEG reduction (large schema) | ~12KB | <0.3ms | <1ms | <2ms |
| Retry iteration 5 (accumulated context) | ~25KB | <0.8ms | <2ms | <3ms |
| Worst case (SCM evidence + large code + retry) | ~40KB | <1ms | <3ms | <5ms |

API call: 2,000-15,000ms. Assembly is always <0.1% of total time.

### D2: Hashing Controls

- Component content hashes: computed once at startup. Cost: ~50 components × ~0.01ms = negligible.
- Variable value hashes: computed per call. For a 40KB prompt with 10 variables, total hashing cost is <1ms.
- `final_prompt_hash`: computed once per call on the joined string. For 40KB, <0.5ms.
- `PromptIdentity`: computed per unique (spec, transforms, bindings) combination. Cached across cases within the same condition.

**No optional hashing.** All hashing is always-on. The cost is negligible even in worst case.

### D3: Memory in Long Runs

A 116-event run (232 LLM calls) produces:
- 232 RenderedPrompt objects: ~20KB each = ~4.5MB peak (can be GC'd after logging)
- State log for retry (worst case 5 iterations × 58 cases): ~50KB per case = ~3MB
- Provider cache: per-case lifecycle, GC'd between cases. Peak ~100KB.
- Total prompt system memory: <10MB. Python process baseline: ~50MB. Negligible.

---

## SECTION E — Migration Equivalence (refined — fixes v4 issue 9)

### E1: Token-Level Equivalence Decision

**String-level equivalence is sufficient. Token-level is explicitly rejected.**

**Justification:**
- Phase A migration goal is: the new system sends the exact same bytes to the API as the old system.
- If the bytes are identical, the tokenization is identical (tokenization is a deterministic function of the input string).
- Token-level comparison would add complexity (requires tiktoken as a dependency in the equivalence checker) without catching any additional errors that byte-level comparison misses.
- The only scenario where byte-identical strings produce different tokens is a tokenizer bug, which is outside our control.

**Acceptable deviations:** NONE during Phase A. Byte identity is required. If the new system produces a prompt that differs by even one character (including whitespace, newlines, trailing spaces), the equivalence gate fails and the migration step is blocked.

**During Phase B:** Intentional changes are expected. Each change is reviewed and logged. Equivalence checking switches from "must be identical" to "must be intentionally different in documented ways."

---

## SECTION F — Experiment Validity Enforcement (fixes v4 issue 10)

### F1: Fatal vs Warning

| Violation | Severity | Reason |
|---|---|---|
| Two conditions in same experiment differ on 3+ dimensions | **FATAL** | Confounded comparison. Cannot isolate variable. |
| Two conditions differ on 2 dimensions | **WARNING** | Potentially intentional (e.g., LEG uses different spec AND different contract). Researcher must acknowledge. |
| Two conditions have same PromptIdentity | **WARNING** | Duplicate condition. No ablation value. |
| Condition uses non-standalone spec as base_spec | **FATAL** | Strategy-internal spec selected as ablation target. |
| Condition overrides classifier contract | **FATAL** | Breaks comparability of reasoning classification. |
| Condition uses transforms incompatible with base_spec | **FATAL** | Caught at startup validation. |
| Condition uses strategy incompatible with base_spec | **FATAL** | Caught at startup validation. |

### F2: When Warnings Become Fatal

The config may include a strictness flag:

```yaml
experiment:
  ablation_strictness: "strict"  # or "permissive"
```

Under `strict` mode: all warnings become fatal. Under `permissive` mode: warnings are logged and the run proceeds. Default: `strict`.

### F3: Single-Dimension Change Validation

At config load, for each pair of conditions declared in the experiment:

```
dimensions = []
if A.base_spec != B.base_spec: dimensions.append("spec")
if A.transforms != B.transforms: dimensions.append("transforms")
if A.execution_strategy != B.execution_strategy: dimensions.append("strategy")
if A.response_contract != B.response_contract: dimensions.append("contract")

if len(dimensions) == 0: WARN "identical conditions"
if len(dimensions) == 1: OK (clean ablation)
if len(dimensions) == 2: WARN "multi-dimension comparison: {dimensions}"
if len(dimensions) >= 3: FATAL "confounded comparison: {dimensions}"
```

---

## SECTION G — Unified Registry Validation Phase

Expanded from v4. Now includes 17 checks:

1-15: Same as v4 (component uniqueness, template validity, child slot depth, spec completeness, slot naming, transform validity, bidirectional compatibility, selection rule satisfiability, selection ambiguity, contract completeness, strategy validity, provider DAG acyclicity, provider variable uniqueness, experiment config validity).

16. **Selection coverage:** For every selection rule, for every case in the experiment's case set, resolution succeeds at some tier. Fatal if any case has no match.

17. **Experiment dimension analysis:** Pairwise condition comparison per F3 above. Fatal or warning depending on strictness mode.

All checks run. All errors collected. Single diagnostic dump on failure.

---

## SECTION H — Migration Plan

### Phase A: Legacy-Equivalent Migration

Unchanged from v4 except:
- Equivalence is byte-level (E1 above). Token-level explicitly rejected.
- StageOutputProviders replace the ad-hoc execution state injection. During Phase A shadow mode, verify that StageOutputProviders produce the same variable values as the old ad-hoc injection.
- `call_model` compatibility wrapper allows raw strings during Phase A. Wrapper logs a deprecation warning per call. Phase A completion criterion includes: zero deprecation warnings in a full run (all callers migrated).

### Phase B: Architecture-Native Improvements

Unchanged from v4. Each change is separate, reviewed, tagged in metadata.

### Subsumption and Retirement

Unchanged from v4. Wrap and subsume, not delete. `templates.py` subsumed by registry. Parsers reused by contracts. Old code remains unreachable until 2 full experiment cycles with zero regressions.

---

## SECTION I — Design Risks

### From v4 (retained):
H1 (Transform Explosion), H2 (Config Sprawl), H3 (Invalid Comparability), H4 (Prompt Lineage Ambiguity), H5 (DAG Complexity), H6 (Nesting Misuse), H7 (Shadow Mode Performance), H8 (Migration-Phase Confusion).

### New:

**H9: StageOutputProvider Lifecycle Complexity**
**Risk:** ExecutionEngine must create and register providers mid-strategy. If a stage fails, the provider for that stage's output may not exist, and downstream stages that depend on it will fail at provider resolution.
**Mitigation:** Gate conditions prevent downstream stages from executing if their dependency stage failed. The ExecutionEngine only creates a StageOutputProvider after a stage succeeds. If a stage fails and a downstream stage's provider is missing, the gate condition (`prior_failed`) prevents the downstream stage from executing. If the gate condition is `always` but the provider is missing, assembly validation catches it (missing required provider) and the case is aborted with a clear error.

**H10: Versioned State Log Growth**
**Risk:** For retry loops with many iterations, the state log grows. Each iteration appends ~10KB.
**Mitigation:** Maximum iterations are bounded by config (default 5, max 10). State log for the worst case: 10 iterations × 10KB = 100KB per case. Negligible.

**H11: PromptIdentity Cache Invalidation**
**Risk:** If a component file is modified between runs, the PromptIdentity changes. Cached results from a prior run are invalid.
**Mitigation:** PromptIdentity includes component hashes. Different file content → different hash → different identity. Cache automatically invalidates. No stale cache risk.

---

*End of v5 design document. No implementation performed.*
