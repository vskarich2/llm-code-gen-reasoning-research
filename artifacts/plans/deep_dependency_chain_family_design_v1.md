# Design Memo: `deep_dependency_chain` Family

**Date:** 2026-04-03
**Status:** DESIGN MEMO — awaiting approval

---

## 1. Family Definition

`deep_dependency_chain` measures whether a model can trace a bug's causal effect through a pipeline of 3+ sequential transformations where the symptom appears at the terminal stage, the root cause exists at or near the source stage, and plausible partial fixes exist at one or more intermediate stages. The defining property is that intermediate-node patches partially repair the symptom — they pass some tests but fail generalization invariants — creating a gradient of wrong fixes at each hop of the chain. The model must reject these locally-coherent intermediate patches and trace the full chain to the correct intervention point.

This is not about hidden dependencies (where the connection between cause and effect is non-obvious) or about competing causal hypotheses (where the model must disambiguate). It is about the **length** of the causal chain the model must traverse and the **temptation** of partial fixes at intermediate nodes.

---

## 2. Why This Family Is Needed

### What the current benchmark covers

The existing cross-boundary cases measure specific failure modes:

| Case | Hops | Defining Challenge |
|---|---|---|
| `hidden_dep_multihop` | 3 | Hidden semantic difference between two similar functions (`cache_put` vs `cache_put_if_absent`) |
| `feature_flag_drift` | 2 | Unused parameter at API entry point |
| `config_shadowing` | 2 | Parallel paths diverge at config layer |
| `commit_gate` / `l3_state_pipeline` | 2 | Two interdependent operations removed together |
| `cache_invalidation_order` | 2 | Missing multi-step atomic operation |
| `invariant_partial_fail` | 1 | Local exception safety within one function |

### What is missing

None of these cases have all three of:
1. **Long chain (3+ intermediate transformations)** where data flows through multiple processing stages
2. **Partial-fix attractors at intermediate nodes** where patching node B or C partially repairs the symptom
3. **Generalization invariants that distinguish intermediate patches from root fixes**

The closest case is `hidden_dep_multihop` (3 hops), but its challenge is a semantic distinction between similarly-named functions, not chain traversal. A model that understands `cache_put` vs `cache_put_if_absent` solves it at hop 1 — it doesn't need to trace the full chain.

`deep_dependency_chain` fills the gap: cases where the chain itself is the reasoning challenge, and where stopping at any intermediate node produces a locally-coherent but globally-broken fix.

### Empirical motivation

From the global calibration analysis: cases with cross-boundary reasoning show the highest LEG rates (60-98%). Models understand bugs but can't produce fixes that span the full system graph. The intervention data shows that critique and reasoning-only both help on these cases (+27pp average for high-LEG intervention-responsive cluster). A family that directly measures chain-traversal depth would sharpen these claims.

---

## 3. Discriminator Against Existing Families

### vs `hidden_dep_multihop`

**hidden_dep_multihop:** The dependency is *hidden* — two functions with similar names (`refresh_user_snapshot` vs `sync_user_to_cache`) have different overwrite semantics. The challenge is discovering that the dependency exists, not traversing a long chain. The fix is a one-function-name change.

**deep_dependency_chain:** The dependencies are *visible* — the chain A→B→C→D is obvious from imports and call structure. The challenge is that fixing B or C partially works, and the model must reject those partial fixes and trace to A.

**Discriminator:** If the primary difficulty is discovering a non-obvious dependency, it's `hidden_dep_multihop`. If the dependencies are visible but the chain is long enough that intermediate patches tempt the model, it's `deep_dependency_chain`.

### vs `false_fix_attractor`

**false_fix_attractor:** One dominant wrong target near the symptom. The attractor is attractive because of proximity.

**deep_dependency_chain:** Multiple wrong targets at different chain depths. The intermediate-node patches are not "attractors" in the sense of being closest to the symptom — they're at interior nodes. The defining feature is the gradient: patches get progressively more correct as you move upstream.

**Discriminator:** If there's exactly one dominant wrong target (the symptom-proximal one), it's `false_fix_attractor`. If there are wrong targets at multiple depths along a processing chain, each partially repairing the symptom, it's `deep_dependency_chain`.

### vs `misinferred_dependency`

**misinferred_dependency:** Two or more comparably plausible causal hypotheses that require disambiguation. The challenge is evaluating competing explanations.

**deep_dependency_chain:** One clear causal chain with one root cause. The challenge is not "which cause?" but "how far upstream must I trace?" There are no competing hypotheses — just intermediate nodes that look like sufficient fixes.

**Discriminator:** If the model must choose between competing causes, it's `misinferred_dependency`. If the model must decide how far upstream along a single causal chain to intervene, it's `deep_dependency_chain`.

### vs `abstraction_leak`

**abstraction_leak:** Correct root cause identified, fix applied at the wrong abstraction layer (caller vs callee, producer vs consumer).

**deep_dependency_chain:** The chain has 3+ nodes. The model may fix at the right "layer" conceptually but at the wrong node in the chain. The distinction: abstraction_leak is about vertical layer confusion (e.g., caller compensates for callee bug). deep_dependency_chain is about horizontal chain position (e.g., fixing transformation C when the bug is in transformation A).

**Discriminator:** If the model identifies the root cause correctly but patches the wrong layer (upstream/downstream confusion), it's `abstraction_leak`. If the model patches an intermediate transformation in a long processing chain instead of tracing to the source, it's `deep_dependency_chain`.

### vs `intervention_boundary`

**intervention_boundary:** Correct target function, incomplete implementation (missing co-effects).

**deep_dependency_chain:** Wrong target function entirely — the model is at the wrong node in the chain.

**Discriminator:** If the model targets the right function but the fix is incomplete, it's `intervention_boundary`. If the model targets the wrong function (an intermediate node) because it didn't trace far enough, it's `deep_dependency_chain`.

### vs `control_flow_trap`

**control_flow_trap:** The model misunderstands which execution path is taken.

**deep_dependency_chain:** The execution path is clear — data flows through A→B→C→D. The model understands the path but stops tracing too early.

**Discriminator:** If the model is confused about which code path runs, it's `control_flow_trap`. If the model follows the correct path but doesn't trace it far enough, it's `deep_dependency_chain`.

---

## 4. Failure Mechanism

The canonical failure structure:

```
Source: A produces data/state
  ↓ transform
Intermediate: B processes A's output, introduces derived state
  ↓ transform
Intermediate: C processes B's output, derives further
  ↓ consume
Endpoint: D uses C's output, symptom manifests here
```

The bug is in A (or at the A→B boundary). The symptom appears at D.

The model sees D fail. It traces backward:
- **At D:** adds compensation/null-check/fallback. Passes the immediate test case. Fails generalization (new inputs expose the stale upstream data).
- **At C:** adds recomputation or coercion. Partially works. Fails when B's output format changes or when a second consumer of C bypasses the fix.
- **At B:** adds validation or correction. Works better. Fails when A's contract is exercised through a different path or with different inputs.
- **At A:** fixes the root cause. All invariants pass.

The gradient of partial correctness is the family's defining property. Each hop closer to A is a better fix but not yet complete.

---

## 5. Inclusion Rule

A case belongs in `deep_dependency_chain` if and only if ALL of the following hold:

1. Data or state flows through a chain of **3 or more distinct transformations** (functions, classes, or modules) from source to symptom.
2. The root cause is at or near the source of the chain, and the symptom manifests at or near the terminal end.
3. At least **two intermediate nodes** in the chain admit partial fixes that repair the symptom for the primary test case but fail at least one generalization or chain-integrity invariant.
4. The chain structure is **discoverable from the code** — imports, function calls, and data flow make the chain visible. The challenge is traversal depth, not discovery.
5. The correct fix requires intervention at a **specific node** that is not the symptom site and not the most obvious intermediate node.

---

## 6. Exclusion Rule

A case does NOT belong in `deep_dependency_chain` if:

1. The chain has fewer than 3 transformation steps (use `false_fix_attractor` or `abstraction_leak` instead).
2. No intermediate node admits a partial fix that passes any tests (the chain is just long, not tempting).
3. The primary challenge is discovering a hidden dependency rather than traversing a visible chain (use `hidden_dep_multihop`).
4. The primary challenge is choosing between competing causal explanations (use `misinferred_dependency`).
5. The fix requires coordinated changes at multiple nodes simultaneously rather than fixing one upstream node (that's `intervention_boundary` with co-effects).
6. The chain is artificially long — gratuitous wrappers that add hops without adding reasoning challenge.

---

## 7. Adjacent-Family Boundaries

| Situation | Classification |
|---|---|
| Chain exists but the hidden dependency at one hop is the real challenge | `hidden_dep_multihop` |
| Chain exists but there's only one obvious wrong target (the endpoint) | `false_fix_attractor` |
| Chain exists but two nodes are equally plausible root causes | `misinferred_dependency` |
| Chain is short (2 hops), model fixes wrong layer | `abstraction_leak` |
| Model reaches correct node but fix is incomplete | `intervention_boundary` |
| Model confused about which execution path the chain takes | `control_flow_trap` |
| **Chain is 3+ hops, intermediate patches partially work, model must trace to source** | **`deep_dependency_chain`** |

**Mandatory assignment rule:** If a case has 3+ hops AND at least 2 intermediate partial-fix attractors, it is `deep_dependency_chain` regardless of whether it also involves hidden dependencies or competing causes. The chain-traversal challenge dominates.

---

## 8. Structural Difficulty Ladder

| Property | A | B | C |
|---|---|---|---|
| Chain length (hops) | 3 | 4 | 5+ |
| Files/modules | 2 | 3 | 4+ |
| Intermediate partial-fix points | 1 | 2 | 3+ |
| Distractor functions | 0-1 | 2-3 | 4+ |
| Partial symptom repair at intermediate | Test passes partially | Primary test passes, generalization fails | Primary test and 1 generalization pass, chain-integrity fails |
| Fix requires coordinated changes | No (single node) | No (single node) | Yes (node + one downstream update) |
| Cross-boundary reasoning | Partial (chain within 2 files) | Required (chain spans 3 files) | Required (chain spans 4+ files, data format changes between modules) |

What makes C genuinely hard: the chain spans multiple files, data is transformed at each step (not just passed through), and the partial fix at the penultimate node passes both the primary test AND one generalization test — only the chain-integrity invariant catches it.

---

## 9. Observed Failure Pattern To Validate

In Stage 2 calibration, classify each failed model output into:

| Category | Definition |
|---|---|
| **Endpoint patch** | Model modifies the terminal consumer (D) — adds compensation, null-check, or fallback |
| **Intermediate patch** | Model modifies one of the interior nodes (B or C) — adds validation, recomputation, or coercion |
| **Source-direction, incomplete** | Model targets the correct source region but the implementation is wrong or incomplete |
| **Unrelated failure** | Model modifies an unrelated function, produces parse error, or makes no meaningful change |

**Validation thresholds:**
- ≥30% of failures must be "endpoint patch" (confirms the endpoint is an attractor)
- ≥20% of failures must be "intermediate patch" (confirms intermediate nodes tempt models)
- Combined "endpoint patch" + "intermediate patch" ≥50% (confirms the chain structure drives failures)
- If <50% combined: the case is not producing chain-specific failures. Redesign or reclassify.

---

## 10. Trap Design Principles

Every `deep_dependency_chain` case must include at least 4 trap fixes, one from each archetype:

### Archetype 1: Endpoint Compensation
Patch the terminal consumer to handle the malformed upstream data. Examples: add null-check, add fallback default, add type coercion.

Why it's wrong: fixes the symptom for existing inputs but any new input that triggers a different failure mode at the endpoint will break. The upstream data is still wrong.

### Archetype 2: Intermediate Recomputation
Patch an interior node to recompute or re-derive the correct value from scratch, bypassing the broken upstream. Example: node C re-fetches from the source instead of using B's output.

Why it's wrong: duplicates logic, creates inconsistency between C's recomputed value and B's cached/derived value. Other consumers of B's output still see the broken value.

### Archetype 3: Intermediate Validation/Coercion
Patch an interior node to validate or coerce its input into the expected shape. Example: node B adds `if x is None: x = default_value` before processing.

Why it's wrong: masks the upstream error. The default value may not be semantically correct for all inputs. Hides the real problem from monitoring/logging.

### Archetype 4: Downstream Propagation Fix
Patch the node immediately downstream of the root cause to correct the data as it passes through. Example: node B normalizes A's output before forwarding to C.

Why it's wrong: closest to the root cause and most tempting. Fails when A's output is consumed by a different path that doesn't go through B. The generalization invariant catches this.

---

## 11. Invariant Design Principles

Every `deep_dependency_chain` case requires four invariant classes:

### Trap-Catching Invariant
Tests the primary symptom with the original failing input. Must fail for endpoint patches (archetype 1) — the most superficial fix.

Mechanism: use a second input configuration where the endpoint compensation doesn't apply. Example: if the endpoint patch adds a null-check, provide an input where the upstream produces a non-null but semantically wrong value.

### Generalization Invariant
Tests with at least two distinct input configurations that exercise different paths through the chain. Must fail for intermediate patches (archetypes 2-3) that work for one input pattern but not others.

Mechanism: the second configuration should exercise a branch or format that the intermediate patch doesn't handle. Example: the intermediate validation catches missing values but not values of the wrong type.

### Causal-Location Invariant
Verifies that the fix is at the correct node in the chain. Must fail when the fix is at an intermediate node (archetype 4) instead of the root cause.

Mechanism: test a second consumer path that uses the same upstream data but doesn't go through the patched intermediate. Example: if B is patched, test the path A→C→E that bypasses B.

### Chain-Integrity Invariant
Verifies that the data is correct at every node in the chain, not just at the endpoint. Must fail when any intermediate node still produces malformed output, even if the endpoint now works.

Mechanism: add test functions that read intermediate state directly. Example: `assert get_intermediate_b_output() == expected_b_value` in addition to testing the final output.

---

## 12. Example Case Concepts

### Concept 1: `price_pipeline_drift`
**Domain:** E-commerce pricing pipeline
**Chain:** `price_source.py` (fetches base prices) → `discount_engine.py` (applies discounts) → `tax_calculator.py` (computes tax) → `checkout_renderer.py` (displays final price)
**Bug:** `price_source` returns prices in cents but the chain expects dollars. Everything downstream is 100x too high.
**Trap:** Fix `checkout_renderer` to divide by 100. Fix `tax_calculator` to adjust input. Fix `discount_engine` to scale.
**Root fix:** `price_source` should return dollars.
**Why deep_dependency_chain:** 4-hop chain, partial fixes at each intermediate node.
**Difficulty:** B (3 files, 2 intermediate attractors)

### Concept 2: `auth_context_propagation`
**Domain:** Web application auth middleware
**Chain:** `auth_middleware.py` (extracts user context from token) → `permission_resolver.py` (resolves permissions from user context) → `resource_gate.py` (checks permissions against resource) → `api_handler.py` (serves resource)
**Bug:** `auth_middleware` strips the `org_id` field from the user context during normalization. Downstream, `permission_resolver` can't resolve org-scoped permissions, so `resource_gate` denies access.
**Trap:** Fix `api_handler` to bypass gate for certain resources. Fix `resource_gate` to fall back to user-level permissions. Fix `permission_resolver` to infer org from user profile.
**Root fix:** `auth_middleware` must preserve `org_id` during normalization.
**Why deep_dependency_chain:** 4-hop chain, each intermediate fix partially works but breaks org-level permission isolation.
**Difficulty:** C (4 files, 3 intermediate attractors, fix requires understanding permission model)

### Concept 3: `event_transform_pipeline`
**Domain:** Event processing / ETL
**Chain:** `event_source.py` (produces raw events) → `normalizer.py` (normalizes field names) → `enricher.py` (adds derived fields) → `writer.py` (writes to output store)
**Bug:** `normalizer` lowercases all field names, but `enricher` expects CamelCase for a specific field (`userId` → `userid`). The enricher's lookup fails silently, producing null-enriched events.
**Trap:** Fix `writer` to handle null enrichments. Fix `enricher` to accept lowercase. Fix the specific field mapping.
**Root fix:** `normalizer` must preserve case for identity fields or map them to a canonical form that `enricher` expects.
**Why deep_dependency_chain:** 4-hop chain, null-enrichment flows through to writer where symptom appears.
**Difficulty:** B (3 files, 2 intermediate attractors)

### Concept 4: `search_index_pipeline`
**Domain:** Search engine indexing
**Chain:** `document_loader.py` (loads documents) → `tokenizer.py` (extracts tokens) → `index_builder.py` (builds inverted index) → `search_api.py` (queries index)
**Bug:** `document_loader` includes metadata fields (timestamps, IDs) in the content field. Tokenizer blindly tokenizes these, polluting the index with numeric garbage. Search results are wrong.
**Trap:** Fix `search_api` to filter out numeric tokens from queries. Fix `index_builder` to skip numeric tokens. Fix `tokenizer` to filter.
**Root fix:** `document_loader` must separate content from metadata before passing to tokenizer.
**Why deep_dependency_chain:** 4-hop chain, each intermediate filter partially cleans the data but metadata-derived false matches persist.
**Difficulty:** B (3 files, 2 intermediate attractors)

### Concept 5: `billing_derivation_chain`
**Domain:** SaaS billing
**Chain:** `usage_collector.py` (collects raw usage events) → `aggregator.py` (aggregates per-period) → `rate_engine.py` (applies pricing tiers) → `invoice_renderer.py` (generates invoice)
**Bug:** `usage_collector` double-counts events that span a period boundary (events with a start time in period N and end time in period N+1). The aggregator sums them twice.
**Trap:** Fix `invoice_renderer` to cap charges. Fix `rate_engine` to apply a safety discount. Fix `aggregator` to deduplicate (partially works but loses legitimate duplicate events).
**Root fix:** `usage_collector` must split boundary-spanning events or assign each to exactly one period.
**Why deep_dependency_chain:** 4-hop chain, the double-count propagates and amplifies through aggregation and rating.
**Difficulty:** C (4 files, 3 intermediate attractors, deduplication at aggregator is the strongest trap)

### Concept 6: `config_derivation_cascade`
**Domain:** Application configuration
**Chain:** `env_loader.py` (reads environment variables) → `config_parser.py` (parses and validates) → `derived_settings.py` (computes derived settings from config) → `service.py` (uses derived settings)
**Bug:** `env_loader` reads `MAX_CONNECTIONS` as a string ("100") instead of int. `config_parser` doesn't type-coerce. `derived_settings` computes `pool_size = max_connections * 2` which becomes string concatenation ("100100") in Python. `service` fails when trying to open "100100" connections.
**Trap:** Fix `service` to cap pool_size. Fix `derived_settings` to int() before math. Fix `config_parser` to coerce.
**Root fix:** `env_loader` must return typed values (int for numeric env vars).
**Why deep_dependency_chain:** 4-hop chain, the type error propagates silently until it causes a nonsensical value in derived settings.
**Difficulty:** A (2 files feasible, 1 intermediate attractor, type error is universally understood)

---

## 13. Recommended First Two Cases

### First Prototype: `config_derivation_cascade` (Difficulty A)

**Why best first choice:** Simplest chain structure. The type-propagation bug is universally understood. The partial fix at `derived_settings` (add `int()`) is the obvious trap that every model will attempt. Easy to validate — the chain is short enough to verify but long enough to measure.

**Likely trap behavior:** >60% of models will add `int()` in `derived_settings.py` instead of fixing `env_loader.py`. This is the strongest intermediate attractor because it's the closest correct-looking fix to the symptom.

**Likely model failure pattern:** Models will trace from `service.py` (symptom: can't open "100100" connections) to `derived_settings.py` (string concatenation) and fix there. Few will trace further to `env_loader.py`.

**Not redundant because:** No current case has a type-propagation chain. `config_shadowing` is about parallel paths, not chain depth. `stale_config_reload` is about reference semantics, not type coercion.

**Implementation complexity:** Low — 3 files, simple Python, no external dependencies.

**Validation feasibility:** High — the chain-integrity invariant (check that `config_parser` output is typed correctly) is easy to write.

### Second Prototype: `event_transform_pipeline` (Difficulty B)

**Why best second choice:** The 4-module ETL chain is a realistic software pattern. The case-sensitivity bug at the normalizer is subtle enough that models will trace partway but not all the way. The enricher produces null values that flow silently to the writer, creating a non-obvious propagation path.

**Likely trap behavior:** ~40% endpoint patch (writer handles nulls), ~30% enricher patch (accept lowercase), ~20% specific field mapping hack. <10% trace to normalizer.

**Likely model failure pattern:** Models will see null enrichment values in the writer output, trace to the enricher, and fix the lookup there. The case-sensitivity origin in the normalizer is 2 hops upstream — most models won't trace that far.

**Not redundant because:** No current case has a data-transformation pipeline where normalization at one stage silently breaks lookup at a later stage. `hidden_dep_multihop` has a similar "function name confusion" but the chain is different (cache read vs cache write, not a sequential ETL pipeline).

**Implementation complexity:** Medium — 4 files, but each is simple (10-15 lines). The key design challenge is making the normalizer's case-folding look intentional (not an obvious bug) while making the enricher's case-sensitive lookup look correct (because it IS correct — the normalizer broke the contract).

**Validation feasibility:** High — chain-integrity invariant checks that each stage produces correctly-typed output. Generalization invariant uses a second event with different field patterns.

---

## 14. Validation and Calibration Plan

### Stage 2 Calibration Setup

- **Models:** 2 minimum (one weak: gpt-4.1-nano, one strong: gpt-5-mini)
- **Trials:** 10 per model per condition
- **Conditions:** baseline, critique (strict), reasoning-only
- **Cases:** Both prototype cases

### Output Labeling

For each failed model output, classify:
1. Which file(s) the model modified
2. Which node in the chain was targeted (endpoint / intermediate / source)
3. Whether the fix is a compensation, recomputation, validation, or structural change
4. Map to: endpoint_patch / intermediate_patch / source_direction_incomplete / unrelated

### Success Criteria

The family is validated if:
- Combined endpoint_patch + intermediate_patch ≥50% of failures across both cases
- At least one intermediate node is targeted by ≥20% of failed attempts (trap activation)
- Baseline pass rate is between 10% and 85% (not floor, not ceiling)
- At least one intervention delta ≥10pp (intervention-sensitive)
- The two cases produce distinguishable failure patterns (not identical — the difficulty ladder works)

### Redesign Triggers

- <30% combined endpoint + intermediate patches → chain structure not driving failures. Models fail randomly. Redesign traps.
- 0% intermediate patches → intermediate attractors too weak. Make partial fixes more appealing.
- >85% baseline → too easy. Add hops or remove hints.
- Cases produce identical failure distributions → difficulty ladder not working. Increase separation.

---

## 15. Risks and Failure Modes

### Risk 1: Collapses Into `hidden_dep_multihop`

**How:** If the chain's intermediate nodes don't admit partial fixes, the case reduces to "trace through code to find hidden bug" — which is `hidden_dep_multihop`.

**Mitigation:** The inclusion rule requires ≥2 intermediate partial-fix points. If partial fixes don't exist, the case doesn't qualify. Validate during case authoring by manually confirming that each intermediate patch passes at least one test assertion.

### Risk 2: Traps Are Too Weak

**How:** Intermediate patches are obviously wrong, so models skip them and trace to the root cause. Trap activation <20%.

**Mitigation:** Each trap must pass the primary test case. The trap-catching invariant uses a second input configuration. If models skip the trap, it means the primary test is too easy (doesn't exercise the intermediate fix). Redesign the primary test to make the intermediate fix look more complete.

### Risk 3: Models Fail Randomly

**How:** Models don't follow the chain at all — they make unrelated changes or produce parse errors. Family-specific failure rate <50%.

**Mitigation:** This indicates the case is too complex (floor). Reduce chain length or add more explicit hints in the task prompt about where the symptom is.

### Risk 4: Invariants Only Test Symptom Repair

**How:** All invariants test the endpoint behavior. An intermediate patch that repairs the endpoint passes everything. The chain-integrity invariant is missing.

**Mitigation:** Mandatory chain-integrity invariant that directly tests intermediate state. Every `deep_dependency_chain` case must have at least one invariant that reads state from an intermediate node and verifies its correctness independently of the endpoint.

### Risk 5: The Hard Version Is Just "Hard Bug," Not "Long Chain"

**How:** C-level cases are hard because the code is complex, not because the chain is long. Difficulty comes from code volume, not reasoning depth.

**Mitigation:** Difficulty levels are defined by chain properties (hops, intermediate attractors, cross-file scope), not by code volume. Each file should be <30 lines. The difficulty must come from the reasoning required to traverse the chain, not from parsing complex code.

### Risk 6: Overlap With `false_fix_attractor` on Endpoint Cases

**How:** A model that patches the endpoint is doing exactly what `false_fix_attractor` describes — fixing near the symptom.

**Mitigation:** The endpoint patch is one of several traps, not the only one. In `false_fix_attractor`, there's one dominant attractor. In `deep_dependency_chain`, there are multiple attractors at different chain depths. If >80% of failures target only the endpoint, reclassify as `false_fix_attractor`.

---

## 16. Final Recommendation

**Is this family worth adding?** Yes. The current benchmark has no case where intermediate-node patches create a gradient of partial correctness along a multi-hop chain. This is a common failure pattern in real software maintenance — developers fix the closest broken thing instead of tracing upstream. The family is empirically distinguishable from existing families if intermediate-node patches activate at ≥20% rates.

**What exact shape should it take?** Start with 2 cases:
- A-level: `config_derivation_cascade` — type propagation chain, 3 hops, 1 intermediate attractor
- B-level: `event_transform_pipeline` — ETL normalization chain, 4 hops, 2 intermediate attractors

Each case must have the 4 invariant classes (trap-catching, generalization, causal-location, chain-integrity). Each must have 4 traps (one per archetype). Validate against Stage 2 calibration criteria before promoting.

**Which prototype should be built first?** `config_derivation_cascade`. It's the simplest to implement (3 files, ~50 lines total), the type-propagation bug is universally understood, and the intermediate `int()` fix is the strongest trap archetype. If this case doesn't produce chain-specific failure patterns, the family is unlikely to work at any difficulty level.
