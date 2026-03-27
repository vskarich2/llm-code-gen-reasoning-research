# Prompt System Redesign — Architecture Document v7

**Date:** 2026-03-27
**Status:** DESIGN ONLY — not approved for implementation
**Supersedes:** v1–v6
**Scope of change from v6:** Split PromptIdentity into PromptConfigIdentity and PromptCallIdentity. All other sections unchanged from v5/v6 and incorporated by reference.

---

## A11: Prompt Identity (revised — two-level identity model)

### A11a: PromptConfigIdentity

**What it is:** A configuration-level fingerprint that uniquely identifies the prompt *recipe* for a given experimental condition. Stable across all stages, all cases, and all calls within that condition.

**Definition:**

```
PromptConfigIdentity = SHA-256(
  spec_name,
  sorted(transforms_applied),
  sorted(component_bindings as (slot, component_name, component_hash) tuples),
  response_contract_hash
)
```

**What it includes:**
- Which spec structure is used
- Which transforms modify it (and in what order)
- Which concrete components fill each slot (with their content hashes)
- Which response contract governs the output (with its behavioral hash)

**What it excludes:**
- Stage-specific provider configuration (that belongs to PromptCallIdentity)
- Variable values (those change per case)
- Execution strategy internals (stage ordering, gate conditions)

**Properties:**
- Identical for every call within a condition that uses the same spec + transforms + contract (e.g., all 58 baseline generation calls share one PromptConfigIdentity).
- Different between conditions that differ on any structural dimension.
- Does NOT vary across stages. The classifier stage has its own PromptConfigIdentity (different spec, different contract), independent of the generation stage's identity.

**Use cases:**

| Use Case | How PromptConfigIdentity Is Used |
|---|---|
| **Experiment grouping** | All calls with the same PromptConfigIdentity belong to the same prompt configuration. Ablation analysis groups results by PromptConfigIdentity. |
| **Condition comparison** | Two conditions are structurally identical iff their generation-stage PromptConfigIdentities match. Detected at config load and warned as duplicate. |
| **Drift detection across runs** | Compare PromptConfigIdentity between runs. If it changed, the prompt configuration changed (component edit, transform change, contract change). |
| **Experiment metadata** | Logged once per condition in `metadata.json` under `condition_identities`. |

**Collision detection:** At config load, for each pair of conditions, compare their PromptConfigIdentities. If two conditions have the same PromptConfigIdentity, warn: `"Conditions '{A}' and '{B}' have identical prompt configuration (PromptConfigIdentity={hash}). No ablation value."` This is a warning under permissive mode, fatal under strict mode.

---

### A11b: PromptCallIdentity

**What it is:** A call-level fingerprint that uniquely identifies the complete context of a single LLM call. Varies per stage, per iteration, and per provider configuration.

**Definition:**

```
PromptCallIdentity = SHA-256(
  PromptConfigIdentity,
  stage_name,
  iteration_index,
  provider_config_hash
)
```

Where `provider_config_hash` is the stage-scoped hash from v6:

```
provider_config_hash = SHA-256(
  sorted(
    (provider_name, provider_version_hash)
    for each provider in this stage's graph
  )
)
```

**What it includes:**
- Everything in PromptConfigIdentity (prompt recipe)
- Which stage this call belongs to (generation, classifier, critique, etc.)
- Which iteration (for retry loops; 0 for non-loops)
- Which provider configuration is active (truncation limits, derivation functions, stage output sources)

**What it excludes:**
- Variable values (those change per case — captured by `final_prompt_hash`)

**Properties:**
- Unique per (condition, stage, iteration, provider config) combination.
- Two calls with the same PromptCallIdentity and the same variable values will produce the same `final_prompt_hash`. This is the caching invariant.
- Different iterations of a retry loop have different PromptCallIdentities (different `iteration_index`), even if the prompt spec and transforms are the same.

**Use cases:**

| Use Case | How PromptCallIdentity Is Used |
|---|---|
| **Caching** | The AssemblyEngine caches ResolvedPromptPlans by PromptCallIdentity. Two calls with the same PromptCallIdentity reuse the same plan (only variable collection and rendering differ). |
| **Logging** | Logged in every `calls/{call_id}.json` under `prompt_call_identity`. |
| **Debugging** | "Show me all calls with this PromptCallIdentity" returns every case evaluated with the same prompt configuration at the same stage. |
| **Deduplication** | If two calls in the same run have the same PromptCallIdentity AND the same `final_prompt_hash`, they sent identical bytes to the API. Detectable as redundant calls. |

**Collision detection:** PromptCallIdentity collisions within a run are expected (many cases share the same call identity at the generation stage). PromptCallIdentity + `final_prompt_hash` collisions within a run indicate duplicate API calls (same prompt sent twice). Logged as INFO, not an error — this can happen legitimately (e.g., two cases with identical code files).

---

### A11c: Logging Both Identities

**In `metadata.json` (per run):**

```json
{
  "condition_identities": {
    "baseline": {
      "generation": "a1b2c3...",
      "classifier": "d4e5f6..."
    },
    "diagnostic": {
      "generation": "g7h8i9...",
      "classifier": "d4e5f6..."
    }
  }
}
```

Note: classifier PromptConfigIdentity is the same across conditions (same classifier spec + contract). Generation PromptConfigIdentity differs (different transforms).

**In `calls/{call_id}.json` (per call):**

```json
{
  "call_id": 108,
  "prompt_config_identity": "a1b2c3...",
  "prompt_call_identity": "j0k1l2...",
  "prompt_assembly": {
    "spec_name": "generation_baseline",
    "transforms_applied": ["add_nudge_diagnostic"],
    "response_contract": "json_v2_filedict",
    "stage_name": "generation",
    "iteration_index": 0,
    "components": [...],
    "plan_hash": "...",
    "final_prompt_hash": "..."
  }
}
```

**In `calls_flat.txt` (per call, one-line summary):**

```
[000108] model=gpt-5.4-mini phase=generation case=alias_config_a condition=diagnostic elapsed=4.2s
  → config_id=a1b2c3 call_id=j0k1l2 spec=generation_baseline transforms=[add_nudge_diagnostic]
```

---

### A11d: Summary of Identity Hierarchy

```
PromptConfigIdentity (condition-level)
  = f(spec, transforms, component_bindings, contract)
  Stable across: cases, stages, iterations
  Varies with: condition changes

  PromptCallIdentity (call-level)
    = f(PromptConfigIdentity, stage, iteration, provider_config)
    Stable across: cases (same stage/iteration)
    Varies with: stage, iteration, provider config changes

    final_prompt_hash (instance-level)
      = SHA-256(rendered prompt text)
      Varies with: every case (different variable values)
```

Three levels. Each serves a distinct purpose. No overlap. No ambiguity.

---

*End of v7 design document. All sections not explicitly revised here are identical to v5/v6 and incorporated by reference. No implementation performed.*
