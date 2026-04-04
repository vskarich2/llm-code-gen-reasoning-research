# `deep_dependency_chain` — Family Specification v5

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v4.md

---

## 1. Family Definition

A `deep_dependency_chain` case is one where:

1. A canonical shared representation exists at some node in the system graph.
2. Corruption is introduced at or near that node, producing a malformed canonical representation.
3. The corrupted representation flows through a chain of 3+ transforming nodes, each producing derived state.
4. The symptom manifests at a terminal consumer.
5. Each intermediate node admits a plausible local fix that (a) solves the primary symptom, (b) preserves local semantic coherence, (c) looks defensible to a competent reviewer, and (d) fails under alternate downstream usage or cross-path consumption.
6. At least one bypass consumer reads the canonical field(s) directly, without calling any transformation function in the main chain, and is code-path independent from the main chain.
7. Full correctness requires restoring the canonical field(s) at the corruption site.
8. The root fix must make ALL consumer paths correct without path-specific logic or conditional branching on call site.

### Boundary Tests

**Graph-reveal test:** Hand the model a diagram of A → B → C → D with all consumer paths named. If the case is still hard → candidate. If not → `hidden_dep_multihop`.

**Upstream-visibility test:** Annotate the corruption site and the canonical field explicitly. Re-evaluate all traps. If traps collapse (no longer plausible) OR root fix becomes trivial → case is NOT `deep_dependency_chain`. This test must be run during validation, not merely described.

**Path-independence test:** The root fix must make all consumer paths correct without path-specific branching. If it cannot → the "root fix" is a disguised Trap 5 and the case must be redesigned.

---

## 2. Ontology

Every case must declare:

| Label | Definition |
|---|---|
| `source_of_truth_node` | Node that owns the canonical shared representation |
| `corruption_introduced_at_node` | Node where the canonical representation is first corrupted |
| `first_observable_symptom_node` | Earliest node where a consumer observes incorrect behavior |
| `required_fix_node` | Node where the fix must be applied (always = corruption site) |

### Canonical Shared Representation

A representation is canonical iff:
- It is read by ≥2 independent consumers (at least one chain, at least one bypass)
- No downstream transformation is required to interpret it correctly
- It is authoritative across paths

For each case, declare:

| Property | Required |
|---|---|
| `canonical_field_name(s)` | The specific field(s) constituting the canonical representation |
| `canonical_schema` | Expected shape and types |
| `canonical_storage_location` | Module/dict/object that holds it |
| `canonical_access_paths` | ALL code paths that read the canonical field(s) |

### Canonical Field Identity Rigidity

- The canonical field must be the ONLY field used by at least one consumer (the bypass consumer).
- Alternate fields (introduced by Trap 5) must be ignored by at least one consumer.
- If an alternate field can silently replace the canonical field across ALL consumer paths without any consumer noticing → the case is invalid (the canonical field is not truly canonical).

---

## 3. Discriminator

### Primary Rule

A case is `deep_dependency_chain` only if the primary source of model failure, after the dependency graph is known AND the corruption site is identified, is failure to propagate the fix to the canonical field(s) despite multiple plausible local fixes at derived nodes.

### Dominance Test

- If removing discovery difficulty eliminates most failures → `hidden_dep_multihop`
- If removing discovery difficulty does NOT eliminate most failures → `deep_dependency_chain`
- If genuinely balanced → annotate `primary: deep_dependency_chain, secondary: hidden_dep_multihop`

### Boundary Table

| Adjacent Family | What model must discover | What model must propagate | Where wrong fix lands | Why NOT deep_dependency_chain |
|---|---|---|---|---|
| `hidden_dep_multihop` | Which dependency exists | Fix to discovered site | Function model didn't know was relevant | Revealing graph removes challenge |
| `false_fix_attractor` | Nothing hidden | Nothing — single hop | One dominant symptom-proximal target | One attractor, no gradient of intermediate fixes |
| `misinferred_dependency` | Which of 2+ competing causes is correct | Fix to correct cause | Wrong cause's site | Multiple root hypotheses; deep_dependency_chain has one cause, one corruption site |
| `intervention_boundary` | Nothing — correct target identified | Complete implementation | Right function, incomplete fix | Model at correct node, fix incomplete; deep_dependency_chain model at WRONG node, fix locally complete |
| `abstraction_leak` | Nothing — correct cause identified | Fix at correct layer | Wrong abstraction layer | Vertical layer confusion; deep_dependency_chain is horizontal chain-position confusion |

---

## 4. Trap Taxonomy

### Trap 1: Endpoint Compensation (Depth D)

Patch terminal consumer to handle malformed upstream data.

- **Attractive because:** Directly addresses user-visible symptom. Matches "fix where it breaks."
- **Fails because:** Canonical field still corrupt. Alternate inputs defeat compensation. Bypass consumer sees corrupt data.

### Trap 2: Intermediate Recomputation (Depth C)

Patch interior node to re-derive correct values, bypassing corrupted intermediate.

- **Attractive because:** Produces correct output for this node.
- **Fails because:** Creates inconsistency between this node's output and other nodes' derived state.

### Trap 3: Validation Masking (Depth C/B)

Patch interior node to detect and coerce malformed input.

- **Attractive because:** Defensive programming. Handles observed failure.
- **Fails because:** Coercion is input-class-specific. Different class defeats it.

### Trap 4: Downstream Override (Depth B)

Patch node immediately downstream of corruption to normalize corrupt value before forwarding.

**Classification rule (mechanical):**
A fix is Trap 4 iff:
- Modification occurs strictly downstream of the corruption node (the corruption node's code is unmodified)
- AND the canonical field at the corruption node is unchanged

**Edge cases:**
- Field aliasing at downstream node (reads canonical, writes corrected local copy) → Trap 4
- Conditional overwrite at downstream node (`if bad: fix`) → Trap 4
- Partial overwrite of canonical field at downstream node → Trap 4 (corruption node untouched)

- **Attractive because:** Closest non-root fix. Appears to address the source.
- **Fails because:** Canonical field still corrupt at corruption node. Bypass consumer reads it directly.

### Trap 5: Partial Upstream Fix (Depth B/A-adjacent) — FAMILY-DISTINGUISHING

Fix a derived representation instead of the canonical field. Model traces to the corruption node but introduces an alternate representation while leaving the canonical field corrupt.

**Classification rule (mechanical):**
A fix is Trap 5 iff:
- Modification occurs at OR above the corruption node (the corruption node's code IS modified)
- AND the canonical field is NOT mutated to produce correct values
- AND an alternate representation is introduced: new field, conditional logic path, or parallel data structure

**Edge cases:**
- Model adds new field at corruption node, leaves canonical field unchanged → Trap 5
- Model conditionally overwrites canonical field for some inputs but not all → Trap 5 (canonical field not universally corrected)
- Model partially overwrites canonical field (correct for primary test, wrong for generalization input) → Trap 5 if an alternate path/field is also introduced; otherwise reclassify as incomplete root fix (depth A with failed invariants → classified as `mixed`)

- **Attractive because:** IS at the right node. Adds correct data. Looks like careful migration.
- **Fails because:** Canonical field remains corrupt. Bypass consumer reads canonical field, not alternate.

### Trap Minimality Rule

For each trap in a case: mentally remove the trap and re-evaluate. If the failure distribution is unchanged (remaining traps cover the same depth and rejection pattern), the trap is redundant and must be deleted. Every trap must contribute unique signal.

---

## 5. Invariants

### 5.1 Failure Attribution Guarantee

For any failing patch, exactly ONE invariant must be PRIMARY. Primary = the invariant with the minimal falsification condition — the narrowest check that this specific patch violates.

If two invariants have equally minimal falsification conditions for the same patch → the case is invalid and must be redesigned to separate their scope.

### 5.2 Definitions

**Trap-catching invariant**
- **Falsification condition:** Execute chain with a second input where the endpoint compensation does not apply. The invariant passes iff the endpoint produces correct output for the second input without compensation logic activating.
- **Passes iff:** Endpoint output matches expected value for second input.
- **Rejects:** Trap 1 (PRIMARY). Compensation handles first input but not second.
- **Does not reject:** Traps 3-5 (they fix upstream of endpoint; endpoint receives correct data for both inputs).
- **Why unique:** No other invariant tests the endpoint with alternate inputs. Generalization tests intermediate nodes. Causal-location tests the corruption node. Cross-path tests the bypass consumer.

**Generalization invariant**
- **Falsification condition:** Execute chain with an input from a different input class that the validation/coercion does not handle.
- **Passes iff:** Chain produces correct output for the alternate input class.
- **Rejects:** Trap 3 (PRIMARY). Coercion handles one input class but not the other.
- **Does not reject:** Trap 5 (operates at corruption node, handles all input classes through its alternate representation).
- **Why unique:** No other invariant tests input-class coverage at intermediate nodes. Trap-catching tests the endpoint. Causal-location tests the corruption node's output format, not the intermediate's input handling.

**Causal-location invariant**
- **Falsification condition:** Directly call the corruption node's function and assert that the canonical field(s) in its output match the canonical schema exactly.
- **Passes iff:** `output[canonical_field_name]` matches `canonical_schema` for the test input. No "any correct output" — the canonical field specifically must be correct.
- **Rejects:** Traps 1-4 (all leave corruption node unmodified or only modify downstream). Trap 5 ALSO FAILS this invariant because Trap 5 does not mutate the canonical field — the canonical field remains corrupt even though a new field is added.
- **Does not reject:** Root fix (which corrects the canonical field in-place).
- **Why unique:** Only invariant that directly inspects the corruption node's canonical field output. Cross-path inspects the bypass consumer. Chain-integrity inspects intermediate nodes. Trap-catching inspects the endpoint.

**Cross-path consistency invariant**
- **Falsification condition:** Execute both the primary chain path and the bypass consumer path. Assert they produce consistent results derived from the same canonical field.
- **Passes iff:** Primary chain output and bypass consumer output agree on values derived from the canonical field.
- **Bypass consumer structural requirements:**
  - Must read the canonical field directly
  - Must NOT call any transformation function in the main chain
  - Must NOT reference alternate or derived fields
  - Must be code-path independent from the main chain (no shared transformation logic)
- **If bypass path shares any transformation logic with main chain → case is invalid.**
- **Rejects:** Trap 4 (PRIMARY) and Trap 5 (PRIMARY). Trap 4 fixes the main chain but bypass reads the corrupt canonical field. Trap 5 introduces an alternate field that the main chain uses, but bypass reads the canonical field.
- **Does not reject:** Root fix (canonical field corrected, both paths see same correct data).
- **Why unique for Trap 4:** Causal-location also rejects Trap 4, but cross-path is PRIMARY for Trap 4 because it is the more specific signal: causal-location says "corruption node output wrong" (true for all non-root fixes); cross-path says "bypass consumer disagrees with main chain" (specific to fixes that repair the chain but not the canonical field).
- **Why unique for Trap 5:** Causal-location rejects Trap 5 because the canonical field is unchanged. Cross-path ALSO rejects Trap 5. But cross-path is PRIMARY for Trap 5 because it is the tighter signal: the bypass consumer specifically reads the canonical field that Trap 5 left corrupt, producing a concrete inconsistency between the two paths. Causal-location catches a broader class of failures (any non-root fix). Cross-path catches specifically the "alternate representation" failure mode.

**Chain-integrity invariant**
- **Falsification condition:** Call helper functions that expose intermediate state at each chain node. Assert each node's output matches expected values for the test input.
- **Passes iff:** Every intermediate node's output is internally consistent and correct.
- **Rejects:** Trap 2 (PRIMARY). Recomputation fixes one node but leaves another node's output based on corrupt data. Chain-integrity detects the inconsistency between nodes.
- **Does not reject:** Trap 5 (chain-integrity checks intermediate nodes; Trap 5 operates at corruption node, and intermediate nodes may all produce correct output if they read the alternate field).
- **Why unique:** Only invariant that checks ALL intermediate nodes independently. Causal-location checks only the corruption node. Cross-path checks only the bypass consumer. Chain-integrity catches inter-node inconsistencies that no other invariant detects.

### 5.3 Invariant × Trap Matrix

| | Trap 1 (endpoint) | Trap 2 (recompute) | Trap 3 (masking) | Trap 4 (override) | Trap 5 (partial upstream) |
|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | secondary | secondary | secondary | pass |
| **Generalization** | secondary | secondary | **PRIMARY** | secondary | pass |
| **Causal-location** | secondary | secondary | secondary | secondary | secondary |
| **Cross-path** | secondary | secondary | secondary | **PRIMARY** | **PRIMARY** |
| **Chain-integrity** | secondary | **PRIMARY** | secondary | secondary | pass or secondary |

No cell contains "ambiguous." Every PRIMARY is unique per trap. Causal-location is secondary for all traps (it catches all non-root fixes but is never the tightest discriminator for any specific trap).

---

## 6. Depth Metric

### Semantic Fix Classification

| Depth | Label | Definition |
|---|---|---|
| A | `root_fix` | Canonical field(s) corrected in-place at corruption node. No downstream compensation required. ALL five invariants pass when this modification is applied alone. |
| B | `proximal_derived_fix` | Modification at or adjacent to corruption node. Canonical field NOT corrected. Alternate representation introduced OR downstream normalization applied. At least one invariant fails. |
| C | `distal_intermediate_fix` | Modification at intermediate node 2+ hops from corruption. Canonical and proximal representations unchanged. |
| D | `endpoint_compensation` | Modification only at terminal consumer. All upstream representations unchanged. |
| mixed | `multi_level_fix` | Edits at multiple chain levels without clean dominance. |
| — | `unrelated` | No meaningful causal correction. |

### Classification Procedure

1. Identify all functions/files the model modified.
2. For each modification, determine which chain node it targets.
3. **Root-fix test:** Does the modification at the corruption node, applied alone, pass ALL five invariants?
   - Yes → A (`root_fix`).
   - No → continue.
4. **Dominance test:** Is there a single modification that, if it were the only edit, would pass the primary test (even if it fails some invariants)?
   - Yes → classify by that modification's chain position (B/C/D).
   - No single modification suffices → `mixed`.
5. If multiple modifications exist and one dominates (passes primary test alone), classify by the dominant modification's position. If no dominance → `mixed`.
6. If no modification addresses any chain node → `unrelated`.

**Key constraint:** A fix is `root_fix` (A) ONLY IF all five invariants pass when it is applied alone. An incorrect root-level edit that fails any invariant is classified as B (`proximal_derived_fix`) or `mixed`, never A.

---

## 7. Validation Criteria

### Hard Requirements (Case Acceptance)

1. At least two distinct non-root fixes must be plausible: each must solve the primary symptom, preserve local coherence, look defensible, and fail at least one invariant.
2. At least one upstream-near-root trap (Trap 4 or 5) must fail ONLY on cross-path consistency (passes trap-catching, generalization, and chain-integrity).
3. The root fix must be the unique fix passing all five invariants.
4. The root fix must satisfy path-independence: all consumer paths correct without path-specific logic.
5. The bypass consumer must read the canonical field directly, call no main-chain transformation functions, reference no alternate fields, and share no transformation logic with the main chain.
6. Baseline pass rate must be between 5% and 80% across calibration models.
7. **Empirical trap activation:** At least TWO calibration models (one weak-tier, one mid-tier) must each produce a non-root fix that passes the primary test AND fails at least one invariant. If fewer than two models fall for traps → case rejected.
8. **Upstream-visibility enforcement:** Annotate the corruption site and canonical field explicitly. Re-evaluate all traps. If any trap becomes implausible OR the root fix becomes trivial → case is NOT `deep_dependency_chain`.

### Calibration Targets (Expected Patterns)

- Weaker models tend toward D or unrelated.
- Mid-tier models tend toward C or B.
- Stronger models tend toward A.
- At least 2 distinct depth levels represented among failures.

---

## 8. Case-Construction Checklist

1. Define the canonical shared representation (field names, schema, storage location, ALL access paths).
2. Define where corruption is introduced and the specific bug.
3. Enumerate all downstream transforms (what each transforms, what derived state it produces).
4. Enumerate all consumers. At least one bypass consumer that reads canonical field directly with NO shared transformation logic with main chain.
5. Propose at least 3 incorrect but plausible local fixes. Each must: solve primary symptom, preserve local coherence, look defensible, fail only under alternate path/consumer/input.
6. Show the primary test each incorrect fix passes (concrete input + output).
7. Show the specific invariant each incorrect fix fails (map to matrix; confirm exactly one PRIMARY per fix).
8. Show the root fix and prove it passes all 5 invariants.
9. Boundary audit: apply graph-reveal test, upstream-visibility test, path-independence test.
10. Predict depth gradient: for each model tier, predict depth and why.
11. **Minimality check:** Remove each chain node one at a time. If the case still produces plausible intermediate fixes at ≥2 depths → the removed node was unnecessary → delete it. Chain must be the shortest that still produces the phenomenon.
12. **Trap minimality check:** Remove each trap one at a time. If the failure distribution is unchanged → the trap was redundant → delete it. Every trap must contribute unique signal.
13. **Upstream-visibility enforcement:** Annotate corruption site explicitly. Re-evaluate traps. If any collapse → case invalid.
14. **Failure attribution check:** For every trap, confirm exactly one invariant is PRIMARY. If two invariants tie → redesign the case.

---

## 9. Case 1: `request_context_chain` (Difficulty B)

### 9.1 Node Declarations

| Label | Value |
|---|---|
| `source_of_truth_node` | `request_parser.py` |
| `corruption_introduced_at_node` | `normalizer.py` |
| `first_observable_symptom_node` | `enricher.py` |
| `required_fix_node` | `normalizer.py` |

### 9.2 Canonical Shared Representation

| Property | Value |
|---|---|
| `canonical_field_name` | `user_id` |
| `canonical_schema` | `str` matching `[A-Z]+-\d+` (e.g., `"USR-00042"`, `"ADMIN-001"`) |
| `canonical_storage_location` | Normalized request dict returned by `normalizer.normalize()` |
| `canonical_access_paths` | (1) enricher → reads `user_id` for DB lookup; (2) handler → reads `user_id` for response; (3) `get_audit_log()` → reads `user_id` for audit (BYPASS) |

**Rigidity check:** `get_audit_log()` reads ONLY `user_id`. It does not read `canonical_id` or any alternate field. If Trap 5 introduces `canonical_id`, `get_audit_log()` ignores it.

**Bypass independence:** `get_audit_log()` reads `enriched["user_id"]` directly. It calls no enricher, normalizer, or parser functions. It shares no transformation logic with the main chain.

### 9.3 Chain

```
request_parser.parse_request(raw)
  → {"user_id": "USR-00042", "timestamp": "2026-04-01T10:00:00", "action": "purchase", "amount": "150.00"}

normalizer.normalize(parsed)                     ← CORRUPTION: strips "USR-" prefix
  → {"user_id": "00042", "timestamp": 1743505200, "action": "purchase", "amount": 150.0}

enricher.enrich(normalized)                      ← FIRST SYMPTOM: lookup fails
  → {"user_id": "00042", "tier": "basic", "discount": 0}

handler.handle(enriched)                         ← TERMINAL: wrong discount
handler.get_audit_log(enriched)                  ← BYPASS: reads user_id directly
```

### 9.4 Bug

`normalizer.normalize()` contains `result["user_id"] = parsed["user_id"].replace("USR-", "")`. The prefix is part of the canonical ID format.

### 9.5 Root Fix

```python
result["user_id"] = parsed["user_id"]  # preserve canonical ID
```

**Path-independence:** All three consumer paths (enricher, handler, audit log) see the correct `user_id` without path-specific logic.

**All invariants pass:** Trap-catching (second user works), generalization (ADMIN- user works), causal-location (`normalize()` output has correct `user_id`), cross-path (audit log matches handler), chain-integrity (all nodes correct).

### 9.6 Traps

**Trap 1 — Endpoint compensation (D):** `handler.handle()` adds loyalty discount if `tier == "basic"` and amount > 100 → gives 10% instead of correct 20%.
- Passes primary test (non-zero discount).
- **PRIMARY rejection: trap-catching.** Second user `"USR-00099"` IS basic tier → loyalty hack gives 10% to genuine basic user (should be 0%).

**Trap 3 — Validation masking (C):** `enricher.enrich()` tries `user_db.get("USR-" + user_id)` on lookup failure.
- Passes primary test (`"USR-00042"` found).
- **PRIMARY rejection: generalization.** User `"ADMIN-001"` → enricher tries `"USR-ADMIN-001"` → not found → wrong tier.

**Trap 4 — Downstream override (B):** `enricher.enrich()` re-prefixes and stores `enriched["user_id"] = "USR-" + normalized["user_id"]`.
- Passes primary test (enriched dict has `"USR-00042"`).
- **PRIMARY rejection: cross-path.** `normalizer.normalize()` output still has `user_id: "00042"`. The enricher fixed the enriched dict, but `get_audit_log()` receives the enriched dict whose `user_id` was re-prefixed by the enricher. Wait — if the enricher overwrites `enriched["user_id"]`, then `get_audit_log(enriched)` reads the corrected value. The cross-path invariant must test NORMALIZER output, not enricher output.

**Correction:** The bypass consumer must read from the normalizer's output, not the enricher's. Revise: add a `get_normalized_request()` function that returns the normalizer's output dict for audit compliance purposes. This function reads `user_id` from the normalizer's output directly and shares no transformation logic with enricher/handler.

Revised bypass: `normalizer.get_normalized_for_audit()` → reads `user_id` from normalized dict.

**Trap 4 revised rejection:** `normalizer.normalize()` output `user_id` is still `"00042"`. `get_normalized_for_audit()` returns `"00042"`. Handler response has `"USR-00042"` (from enricher re-prefix). Inconsistency: audit record says `"00042"`, handler says `"USR-00042"`. **PRIMARY rejection: cross-path.**

**Trap 5 — Partial upstream fix (B):** `normalizer.normalize()` adds `canonical_id` field, still strips `user_id`:
```python
result["user_id"] = parsed["user_id"].replace("USR-", "")
result["canonical_id"] = parsed["user_id"]
```
- Passes primary test (if enricher reads `canonical_id`).
- **PRIMARY rejection: cross-path.** `get_normalized_for_audit()` reads `user_id` → `"00042"`. Handler (via enricher using `canonical_id`) shows `"USR-00042"`. Inconsistency.

### 9.7 Invariant × Trap Verification

| Invariant | Trap 1 (handler) | Trap 3 (enricher search) | Trap 4 (enricher re-prefix) | Trap 5 (canonical_id) | Root fix |
|---|---|---|---|---|---|
| Trap-catching | **PRIMARY: FAIL** | pass | pass | pass | PASS |
| Generalization | secondary: fail | **PRIMARY: FAIL** | secondary: fail | pass | PASS |
| Causal-location | secondary: fail | secondary: fail | secondary: fail | secondary: fail (user_id still stripped) | PASS |
| Cross-path | secondary: fail | secondary: fail | **PRIMARY: FAIL** | **PRIMARY: FAIL** | PASS |
| Chain-integrity | secondary: fail | secondary: fail (enriched user_id "00042") | pass | secondary: fail (normalized user_id stripped) | PASS |

Every trap has exactly one PRIMARY. Root fix is the unique fix passing all 5.

### 9.8 Boundary Audit

- **Graph-reveal test:** Drawing the chain does not remove difficulty. Enricher prefix-search and normalizer canonical_id remain attractive. **PASS.**
- **Upstream-visibility test:** Annotating "user_id is canonical, normalizer strips prefix" — Trap 5 (adding canonical_id) remains attractive as a "migration" approach. **PASS.**
- **Path-independence:** Root fix makes all paths correct without branching. **PASS.**

---

## 10. Case 2: `billing_aggregation_chain` (Difficulty C)

### 10.1 Node Declarations

| Label | Value |
|---|---|
| `source_of_truth_node` | `collector.py` |
| `corruption_introduced_at_node` | `collector.py` |
| `first_observable_symptom_node` | `plan_resolver.py` |
| `required_fix_node` | `collector.py` |

### 10.2 Canonical Shared Representation

| Property | Value |
|---|---|
| `canonical_field_name` | `units` |
| `canonical_schema` | `int`, exact count of events in the UTC billing period |
| `canonical_storage_location` | Usage record dicts returned by `collector.aggregate_usage()` |
| `canonical_access_paths` | (1) plan_resolver → reads `units` for tier assignment; (2) rate_engine → reads `units` via resolved record; (3) `collector.get_usage_summary()` → reads `units` directly (BYPASS) |

**Rigidity check:** `get_usage_summary()` reads ONLY `units`. It does not read `corrected_units` or any alternate field.

**Bypass independence:** `get_usage_summary()` calls `aggregate_usage()` and reads the `units` field from its output. It calls no plan_resolver, rate_engine, or invoice_builder functions. It shares no transformation logic with the billing chain.

### 10.3 Chain

```
collector.aggregate_usage(events, tz_offset_hours)   ← CORRUPTION + SOURCE
  BUG: groups by event["timestamp"][:10] (local date) instead of UTC
  → [{"period": "2026-04-01", "units": 85}]   (should be 100)

  ├─▶ collector.get_usage_summary(events) → {"2026-04-01": 85}   ← BYPASS

plan_resolver.resolve(usage_record)                  ← FIRST SYMPTOM
  tiers: 0-50 = starter ($0.20), 51-100 = growth ($0.10), 101+ = enterprise ($0.05)
  85 → growth at $0.10   (should be 100 → enterprise at $0.05)

rate_engine.compute_charges(resolved)
  85 × $0.10 = $8.50   (should be 100 × $0.05 = $5.00)

invoice_builder.build_invoice(charges)               ← TERMINAL
  → wrong total + wrong tier
```

### 10.4 Bug

`collector.aggregate_usage()` groups by `event["timestamp"][:10]` (local-time date string). With `tz_offset_hours=-1`, 15 events with local timestamps on April 1 have UTC timestamps on March 31. The April 1 period gets 85 instead of 100.

The root fix is independent of pricing/tier mechanics. It is purely about timestamp conversion: the collector must convert to UTC before extracting the billing-period date.

### 10.5 Root Fix

```python
def aggregate_usage(events, tz_offset_hours=0):
    by_period = {}
    for event in events:
        utc_ts = to_utc(event["timestamp"], tz_offset_hours)
        period = utc_ts[:10]
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in by_period.items()]
```

**Path-independence:** Corrects `units` in the canonical representation. All consumers (plan_resolver, rate_engine, invoice_builder, dashboard) see correct units without path-specific logic.

### 10.6 Traps

**Trap 1 — Endpoint compensation (D):** `invoice_builder.build_invoice()` adds: if `tier == "growth"` and `subtotal > 8.00`, apply 41% adjustment.
- Passes primary test: $8.50 × 0.59 ≈ $5.02.
- **PRIMARY rejection: trap-catching.** Legitimate 85-unit growth user (no timezone issue) should pay $8.50. Adjustment wrongly reduces their bill to $5.02.

**Trap 3 — Validation masking (B):** `plan_resolver.resolve()` adds tolerance: if `units >= tier_boundary × 0.80`, bump to higher tier. Enterprise boundary = 101, so threshold = 80.8. Since 85 ≥ 81 → bump to enterprise.
- Passes primary test: enterprise tier at $0.05, 85 × $0.05 = $4.25.
- **PRIMARY rejection: generalization.** User with 42 units: growth boundary = 51, threshold = 40.8. Since 42 ≥ 41 → bumped from starter ($0.20) to growth ($0.10). Bill drops from $8.40 to $4.20 — 50% undercharge for a legitimate starter user.

**Trap 2 — Intermediate recomputation (C):** `rate_engine.compute_charges()` re-aggregates units from raw events instead of using the resolved record's `units`.
- Passes primary test: recomputed 100 units, but tier is still "growth" (from plan_resolver using 85). Charges = 100 × $0.10 = $10.00.
- **PRIMARY rejection: chain-integrity.** Plan resolver output: 85 units / growth. Rate engine charges for 100 units at growth rate. The resolved record says 85 but charges are for 100 — internally inconsistent. Invoice shows "growth tier" but unit count doesn't match tier assignment.

**Trap 4 — Timezone hack (A-wrong):** `collector.aggregate_usage()` adds +1 hour to all timestamps before grouping.
- Passes primary test: for `tz_offset=-1`, adding 1 hour converts to UTC. 100 units.
- **PRIMARY rejection: cross-path.** For `tz_offset=+5` events, adding 1 hour shifts timestamps further from UTC instead of closer. `get_usage_summary()` returns wrong units for UTC+5. Also: dashboard (bypass) for the primary timezone shows correct units (100), but the hack is input-specific. Actually — for the primary test, the hack works, so cross-path passes for that input. The failure is on generalization (UTC+5 input). Let me reconsider.

Revised: Trap 4's PRIMARY rejection is **generalization** (UTC+5 input defeats the hack). But generalization is already PRIMARY for Trap 3. Two traps share a PRIMARY invariant → violates failure attribution guarantee.

**Resolution:** Trap 4 is mechanically distinct from Trap 3. Trap 3 fails generalization because the tolerance is too aggressive for small unit counts (different input VALUE). Trap 4 fails generalization because the offset is wrong for different timezones (different input CLASS — different tz_offset parameter). These are different inputs testing different properties. The generalization invariant uses two test inputs: one alternate-value (for Trap 3) and one alternate-class (for Trap 4). Trap 3 fails on the alternate-value input. Trap 4 fails on the alternate-class input. The PRIMARY is distinguished by WHICH generalization input triggers failure.

To make this unambiguous: split generalization into two concrete test assertions. Trap 3's PRIMARY = generalization assertion A (alternate unit count). Trap 4's PRIMARY = generalization assertion B (alternate timezone). These are distinct falsification conditions under the same invariant umbrella.

**Trap 5 — Partial upstream fix (A, derived):** `collector.aggregate_usage()` adds `corrected_units` field alongside `units`:
```python
record["units"] = local_count           # still 85
record["corrected_units"] = utc_count   # 100
```
- Passes primary test (if plan_resolver reads `corrected_units`): 100 → enterprise → $5.00.
- **PRIMARY rejection: cross-path.** `get_usage_summary()` returns `units: 85`. Invoice says 100 / enterprise / $5.00. Dashboard says 85. Inconsistency.

### 10.7 Invariant × Trap Verification

| Invariant | Trap 1 (invoice) | Trap 2 (rate recount) | Trap 3 (resolver tolerance) | Trap 4 (tz hack) | Trap 5 (corrected_units) | Root fix |
|---|---|---|---|---|---|---|
| Trap-catching (legit 85-unit user) | **PRIMARY: FAIL** | pass | pass | pass | pass | PASS |
| Generalization-A (42-unit user) | secondary: fail | secondary: fail | **PRIMARY: FAIL** | pass | pass | PASS |
| Generalization-B (UTC+5 events) | secondary: fail | secondary: fail | secondary: fail | **PRIMARY: FAIL** | pass | PASS |
| Causal-location (collector units) | secondary: fail | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |
| Cross-path (dashboard vs invoice) | secondary: fail | secondary: fail | secondary: fail | secondary: fail | **PRIMARY: FAIL** | PASS |
| Chain-integrity (resolver ↔ rate) | secondary: fail | **PRIMARY: FAIL** | secondary: fail | secondary: fail | secondary: fail | PASS |

Every trap has exactly one PRIMARY. Root fix passes all. No attribution ambiguity.

Note: generalization is split into two concrete assertions (A and B) with distinct falsification targets. This is operationally one invariant with two test inputs, but the two inputs have distinct rejection roles.

### 10.8 Boundary Audit

- **Graph-reveal test:** Chain is explicit. Timezone hack and corrected_units remain attractive with full graph knowledge. **PASS.**
- **Upstream-visibility test:** Annotating "units is canonical, collector corrupts via local-time grouping" — Trap 4 (timezone hack) remains attractive because it IS a timezone fix, just not a general one. Trap 5 (corrected_units) remains attractive as a migration approach. **PASS.**
- **Path-independence:** Root fix (UTC conversion) corrects `units` for all consumers without branching. **PASS.**
- **Minimality check:** Remove plan_resolver → case becomes "wrong count → wrong charge" with no tier-boundary interaction. Trap 3 (tolerance) disappears. Failure distribution loses a depth level. Plan_resolver is load-bearing. Remove rate_engine → Trap 2 (recomputation inconsistency) disappears. Chain-integrity invariant loses its primary target. Rate_engine is load-bearing.

### 10.9 Predicted Depth Gradient

- **Weak (nano):** D (invoice adjustment) or unrelated.
- **Mid (4omini):** C (resolver tolerance) or B (rate recount). Traces to tier assignment.
- **Strong-mid (5mini):** B/A-wrong (timezone hack). Traces to collector, applies constant offset.
- **Strong (54mini, gpt5):** A (UTC conversion). Understands canonical `units` must reflect UTC periods.
