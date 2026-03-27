# Prompt System Redesign — Architecture Document v6

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** v1–v5
**Scope of change from v5:** Precision corrections to provider lifecycle, PromptIdentity, versioning, and stage-scoped validation. All other sections unchanged from v5.

---

## CHANGED SECTIONS ONLY

Sections not listed here are identical to v5 and incorporated by reference.

---

## A5: ContextProvider (revised — stage-scoped graphs)

### Provider Graph Is Stage-Scoped

Each stage in an ExecutionStrategy has its own **complete, self-contained provider graph**. There is no global mutable DAG. StageOutputProviders are not "injected" — they are declared members of a stage's graph, known at strategy definition time.

### Provider Graph Construction

A stage's provider graph is constructed deterministically at stage entry from two sources:

1. **Static providers:** Always available. Declared in the PromptSpec's `required_context_providers`. Instantiated once per case and reused across stages that need them.

2. **StageOutputProviders:** Available only if their source stage has completed. Declared in the ExecutionStrategy's stage definition as explicit provider entries.

The ExecutionStrategy declares, for each stage, the **complete list of providers** that stage's graph contains:

```
stages:
  - name: "generation"
    providers: [TaskContextProvider, CodeContextProvider, SCMContextProvider, OutputInstructionContextProvider]

  - name: "classify"
    providers: [TaskContextProvider, ClassifierInputProvider(source_stage="generation")]
```

`ClassifierInputProvider(source_stage="generation")` means: this provider wraps the output of the "generation" stage. It is not dynamically injected — it is a declared graph member whose instantiation is deferred until the source stage completes.

### Provider Graph Lifecycle

1. **Strategy validation (startup):** For each stage, verify that all declared providers can be satisfied:
   - Static providers: always available (validated against registry).
   - StageOutputProviders: their `source_stage` must be a prior stage in the strategy's execution order AND that prior stage must not be gated by a condition that could prevent it from running. If a StageOutputProvider depends on a conditional stage, the consuming stage must also be conditional with a compatible gate (e.g., "only classify if generation succeeded").

2. **Stage entry (runtime):** The ExecutionEngine constructs the stage's provider graph:
   - Static providers: retrieved from per-case cache (instantiated on first use, cached for case lifetime).
   - StageOutputProviders: instantiated from the state log entry for the named source stage. If the source stage did not execute (gated), the consuming stage must also be gated and should not reach this point. If it does (logic error), assembly fails with: `"PROVIDER ERROR: StageOutputProvider for '{source_stage}' requested but stage did not execute."` This is a strategy definition bug, caught at startup validation for well-formed strategies.

3. **Assembly:** The AssemblyEngine receives the constructed provider graph. It resolves dependencies within the graph (topological order), collects variables, renders. The graph is read-only during assembly.

4. **Stage exit:** The provider graph is discarded. StageOutputProviders are not retained across stages. The next stage constructs its own graph.

### Dependency Rules Within a Stage Graph

- Static providers may depend on other static providers (e.g., `CodeContextProvider` depends on `TaskContextProvider`).
- StageOutputProviders may depend on static providers (e.g., `ClassifierInputProvider` depends on `TaskContextProvider` for truncation config).
- StageOutputProviders may NOT depend on other StageOutputProviders within the same stage. Cross-stage data flows through the state log, not through provider-to-provider dependencies.
- Dependency graph within each stage must be acyclic. Validated at startup per stage.

---

## A11: PromptIdentity (revised — includes contract and provider configuration)

### Definition

```
PromptIdentity = SHA-256(
  spec_name,
  sorted(transforms_applied),
  sorted(component_bindings as (slot, component_name, component_hash) tuples),
  response_contract_identity,
  provider_configuration_hash
)
```

### ResponseContract Identity

Each ResponseContract has a `contract_hash` computed at startup:

```
contract_hash = SHA-256(
  name,
  output_instruction_component_hash or "null",
  parser_name,
  validator_name or "null",
  sorted(normalization_policy),
  reconstruction_policy,
  sorted(error_policy as (category, decision) tuples)
)
```

If any field of the contract changes (different parser, different error policy, different normalization), the `contract_hash` changes, which changes the PromptIdentity. This makes behavioral drift from contract changes detectable.

### Provider Configuration Hash

Each stage's provider graph has a `provider_config_hash` computed at stage entry:

```
provider_config_hash = SHA-256(
  sorted(
    (provider_name, provider_version_hash)
    for each provider in the stage's graph
  )
)
```

Where `provider_version_hash` is:

- For static providers: SHA-256 of the provider's structural configuration (variable names owned, derivation functions declared, truncation limits). This does NOT include runtime values — it captures the provider's behavioral contract.
- For StageOutputProviders: SHA-256 of (source_stage_name, variable_names_owned, derivation_functions_declared).

**What "provider structural configuration" includes:**
- The set of variable names the provider outputs
- The names of derivation/transformation functions applied (e.g., `"format_code_files"`, `"truncate"`)
- For truncation providers: the truncation limits from config (e.g., `max_reasoning_chars=1000`)
- NOT the actual values (those change per case)

This means: if someone changes the classifier's `max_reasoning_chars` from 1000 to 1500, the `provider_version_hash` changes, the `provider_config_hash` changes, the PromptIdentity changes. The drift is detectable.

### Identity Stability

PromptIdentity is stable across cases within the same condition (same spec, transforms, components, contract, provider config). It varies only when the prompt *configuration* changes, not when the prompt *content* changes (different case = different variables = different `final_prompt_hash`, but same PromptIdentity).

---

## A-Versioning: Behavioral Component Versioning (NEW)

Every behavioral component in the system has a version hash computed at startup and logged in run metadata.

| Component Type | Version Hash Includes | Logged Where |
|---|---|---|
| PromptComponent | Raw source text | `metadata.json: component_hashes` |
| ResponseContract | All fields per contract_hash formula above | `metadata.json: contract_hashes` |
| ContextProvider (static) | Variable names, derivation functions, config params | `metadata.json: provider_hashes` |
| ContextProvider (StageOutput) | Source stage, variable names, derivations | Computed per stage, logged in call manifest |
| SelectionRule | Mapping entries + fallback chain | `metadata.json: selection_rule_hashes` |

### Drift Detection Across Runs

At the start of each run, all version hashes are written to `metadata.json`. To detect drift between two runs:

1. Load both `metadata.json` files.
2. Compare `component_hashes` — any difference means a prompt template changed.
3. Compare `contract_hashes` — any difference means parsing/validation behavior changed.
4. Compare `provider_hashes` — any difference means variable construction behavior changed (e.g., truncation limits).
5. Compare `selection_rule_hashes` — any difference means component selection logic changed.

If ALL hashes match, the two runs used identical prompt infrastructure. Differences in results are attributable to model behavior or case data, not to prompt system changes.

---

## Section C — Unified Registry Validation Phase (revised — stage-scoped)

Checks 1–15 unchanged from v5. Additions:

16. **Selection coverage:** Unchanged from v5.

17. **Experiment dimension analysis:** Unchanged from v5.

18. **Stage provider graph validation (NEW):** For each strategy, for each stage:
   - Construct the stage's provider graph (static + StageOutputProviders).
   - Verify all providers in the graph have a valid dependency chain within the graph.
   - Verify the dependency graph is acyclic.
   - Verify all variables required by the stage's spec + transforms are provided by some provider in the graph.
   - Verify StageOutputProviders' source stages are reachable (not unconditionally gated) in all execution paths that reach the consuming stage.

19. **Behavioral version computation (NEW):** Compute and cache all version hashes (components, contracts, providers, selection rules). These are used for PromptIdentity computation and logged to metadata.

Fatal if any stage has an unresolvable provider graph. This catches missing provider declarations at startup, not at execution time.

---

## Section E — Migration Equivalence (addendum)

### Behavioral Version Equivalence (NEW)

During Phase A shadow mode, in addition to text equivalence and parse-path equivalence, verify:

- **Contract equivalence:** The ResponseContract selected by the new system has the same `contract_hash` as the implicit contract used by the old system. (The old system does not compute contract hashes — equivalence is verified by confirming the same parser function is invoked and the same error handling behavior occurs.)

- **Provider equivalence:** The variables produced by the new system's providers have the same value hashes as the variables produced by the old system's ad-hoc construction. This is checked per-call during shadow mode.

These checks ensure the new system is not just producing the same prompt text, but also processing responses identically and constructing variables identically.

---

## Section G — Performance (addendum)

### Version Hash Computation Cost

| Operation | When | Cost |
|---|---|---|
| Component content hashes | Startup | ~50 × 0.01ms = 0.5ms |
| Contract hashes | Startup | ~6 × 0.01ms = 0.06ms |
| Provider version hashes | Startup | ~10 × 0.01ms = 0.1ms |
| Selection rule hashes | Startup | ~20 × 0.01ms = 0.2ms |
| PromptIdentity | Per condition (cached) | ~0.1ms × ~20 conditions = 2ms |
| Provider config hash | Per stage per call | ~0.05ms |

Total additional startup cost: <3ms. Per-call cost: <0.1ms. Negligible.

---

*End of v6 design document. All sections not explicitly revised here are identical to v5 and incorporated by reference. No implementation performed.*
