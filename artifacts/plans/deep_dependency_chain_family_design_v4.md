# `deep_dependency_chain` — Family Specification v4

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v3.md

---

## 1. Family Definition

A `deep_dependency_chain` case is one where:

1. A canonical shared representation exists at some node in the system graph.
2. Corruption is introduced at or near that node, producing a malformed canonical representation.
3. The corrupted representation flows through a chain of 3+ transforming nodes, each producing derived state.
4. The symptom manifests at a terminal consumer.
5. Each intermediate node admits a plausible local fix that (a) solves the primary symptom, (b) preserves local semantic coherence, (c) looks defensible to a competent reviewer, and (d) fails under alternate downstream usage or cross-path consumption.
6. At least one bypass consumer reads the canonical representation directly, exposing the inconsistency that intermediate fixes leave intact.
7. Full correctness requires restoring the canonical shared representation at the corruption site.
8. The root fix must make ALL consumer paths correct without path-specific logic or conditional branching on call site.

### Boundary Tests

**Graph-reveal test:** If you handed the model a diagram of A → B → C → D and named all consumer paths, would the case still be hard? If yes → candidate `deep_dependency_chain`. If no → `hidden_dep_multihop`.

**Upstream-visibility test:** If you explicitly annotated "this is the canonical representation and it is corrupted here," would the problem become trivial? If yes → the case is a localization problem, not a propagation problem, and does not belong in this family. If no → propagation difficulty remains and the case is valid.

**Path-independence test:** Does the root fix make all consumer paths correct without path-specific branching? If yes → valid root fix. If no → the "root fix" is a disguised Trap 5 and the case needs redesign.

---

## 2. Ontology

Every case must declare:

| Label | Definition |
|---|---|
| `source_of_truth_node` | The node that owns the canonical shared representation |
| `corruption_introduced_at_node` | The node where the canonical representation is first corrupted |
| `first_observable_symptom_node` | The earliest node where a consumer observes incorrect behavior |
| `required_fix_node` | The node where the fix must be applied (always = corruption site) |

### Canonical Shared Representation (Formal Definition)

A representation is canonical iff:
- It is read by ≥2 independent consumers (at least one through the chain, at least one bypass)
- No downstream transformation is required to interpret it correctly
- It is intended to be authoritative across paths

For each case, declare:
- `canonical_field_name(s)`: The specific field(s) that constitute the canonical representation
- `canonical_schema`: The expected shape and types of the canonical fields
- `canonical_storage_location`: Which module/dict/object holds it
- `canonical_access_paths`: ALL code paths that read the canonical fields (chain path + bypass path(s))

---

## 3. Discriminator

### Primary Rule

A case is `deep_dependency_chain` only if the primary source of model failure, after the relevant dependency graph is known AND the corruption site is identified, is failure to propagate the fix to the canonical representation despite multiple plausible local fixes at derived nodes.

Use this family only when:
- Revealing the dependency graph does not remove the core challenge (graph-reveal test)
- Explicitly identifying the corruption site does not make the fix trivial (upstream-visibility test)

### Dominance Test for Mixed Cases

If both dependency-discovery difficulty and propagation-to-root difficulty are present:

- If removing discovery difficulty eliminates most model failures → `hidden_dep_multihop`
- If removing discovery difficulty does NOT eliminate most failures because intermediate patches remain attractive → `deep_dependency_chain`
- If genuinely balanced → annotate `primary: deep_dependency_chain, secondary: hidden_dep_multihop`

### Full Boundary Table

| Adjacent Family | What model must discover | What model must propagate | Where wrong fix lands | Why NOT deep_dependency_chain |
|---|---|---|---|---|
| `hidden_dep_multihop` | Which dependency exists (non-obvious) | Fix to discovered site | Function model didn't know was relevant | Revealing the graph removes the challenge. Chain is short once dependency is found. |
| `false_fix_attractor` | Nothing hidden | Nothing — single hop | One dominant symptom-proximal target | One attractor, no gradient. No chain of transforming nodes with plausible intermediate fixes. |
| `misinferred_dependency` | Which of 2+ competing causes is correct | Fix to correct cause | Wrong cause's site | Multiple root hypotheses. In deep_dependency_chain, one canonical representation, one corruption site, no ambiguity about WHICH cause. |
| `intervention_boundary` | Nothing — correct target identified | Complete implementation | Right function, incomplete fix | Model reaches correct node, fix is incomplete. In deep_dependency_chain, model reaches WRONG node and fix is locally complete. |
| `abstraction_leak` | Nothing — correct cause identified | Fix at correct layer | Wrong abstraction layer of correct entity | Vertical layer confusion. deep_dependency_chain is horizontal chain-position confusion. |

---

## 4. Trap Taxonomy

### Trap 1: Endpoint Compensation (Depth D)

Patch the terminal consumer to handle malformed upstream data.

- **Attractive because:** Directly addresses user-visible symptom. Matches debugging instinct "fix where it breaks."
- **Fails because:** Canonical representation still corrupt. Alternate inputs defeat the compensation. Bypass consumer sees corrupt data.

### Trap 2: Intermediate Recomputation (Depth C)

Patch an interior node to re-derive correct values from scratch, bypassing the corrupted intermediate.

- **Attractive because:** Produces correct output for this node. Appears to be a clean workaround.
- **Fails because:** Creates inconsistency between this node's recomputed value and other nodes' derived values. Chain-integrity check exposes the split.

### Trap 3: Validation Masking (Depth C/B)

Patch an interior node to detect and silently coerce malformed input.

- **Attractive because:** Defensive programming. Handles the observed failure case.
- **Fails because:** Coercion is input-class-specific. Different input class defeats it. Bypass consumer sees uncoerced data.

### Trap 4: Downstream Override (Depth B)

Patch the node immediately downstream of the corruption to normalize the canonical representation's corrupt value before forwarding.

**Formal classification rule:** A fix is Trap 4 iff:
- It operates strictly downstream of the corruption node
- AND the canonical representation is untouched at and upstream of the corruption node
- AND it rewrites the corrupt value in transit

- **Attractive because:** Closest non-root fix. Appears to address the issue at its source for the primary path.
- **Fails because:** Canonical representation still corrupt at the corruption node. Bypass consumer reads the canonical representation directly and sees corrupt data.

### Trap 5: Partial Upstream Fix (Depth B/A-adjacent) — FAMILY-DISTINGUISHING

Fix a derived representation instead of the canonical shared representation. The model traces to the corruption node but restores correctness in a new or alternate field while leaving the canonical field corrupt.

**Formal classification rule:** A fix is Trap 5 iff:
- It operates at or above the corruption node
- AND it does NOT mutate the canonical field(s) in-place
- AND it introduces an alternate representation: new field, conditional override, selective path usage, or parallel data structure

**Formal discriminator (Trap 4 vs Trap 5):**
- Trap 4: operates strictly DOWNSTREAM of corruption node; canonical representation untouched upstream
- Trap 5: operates AT or ABOVE corruption node; canonical field unchanged; alternate representation introduced

- **Attractive because:** It IS at the right node. It adds the correct data. A competent reviewer might accept it as a careful migration.
- **Fails because:** The canonical field(s) remain corrupt. Bypass consumers read the canonical field, not the alternate. Cross-path consistency invariant catches it.

**Required declarations per case:**
- What is the canonical shared representation? (field name, schema, location)
- What derived representation does Trap 5 repair instead? (new field name, where introduced)
- Which bypass consumer exposes the inconsistency? (function name, which field it reads)

---

## 5. Invariants

### 5.1 Failure Attribution Protocol

**Primary failure** = the invariant that fails under minimal perturbation of the patch. It is the tightest discriminator — the invariant that a developer would encounter first when testing the patch.

**Secondary failure** = an invariant that also fails but would not be the first signal encountered. It fails because the patch is globally insufficient, not because it targets this invariant's specific concern.

Attribution rule: when analyzing a model output, attribute the failure to the invariant with the **most specific falsification condition** that the patch violates. If two invariants fail for the same structural reason, the one with the narrower scope is primary.

### 5.2 Invariant Definitions

**Trap-catching invariant**
- **Unique job:** Kill endpoint-only compensation.
- **Formal falsification condition:** Execute the chain with a second input where the endpoint compensation does not apply. The compensation must be input-specific (e.g., handles null but not wrong-type; handles missing field but not wrong value).
- **Minimal distinguishing example:** Trap 1 adds a null-check at endpoint. Second input produces a non-null but semantically wrong value. Trap 1 passes the null-check and produces wrong output. No other invariant would catch this specific failure because the upstream chain produces a non-null corrupt value that passes causal-location, cross-path, and chain-integrity checks at the endpoint level.
- **Why no other invariant catches this first:** Causal-location tests the corruption node's output, not the endpoint's handling of alternate inputs. Cross-path tests the bypass consumer, which doesn't go through the endpoint. Chain-integrity tests intermediate nodes, not endpoint behavior.

**Generalization invariant**
- **Unique job:** Kill input-class-specific hacks and tolerance tricks.
- **Formal falsification condition:** Execute the chain with an input from a different class (different ID format, different timezone, different data type) that the validation/coercion/tolerance does not handle.
- **Minimal distinguishing example:** Trap 3 adds prefix matching for `"USR-"` IDs. Input with `"ADMIN-"` prefix fails the prefix match. Trap-catching invariant would not catch this because the endpoint compensation is not involved. Causal-location would also fail, but causal-location tests the corruption node's output format, not the intermediate node's input handling — the failure reason is different (wrong input class vs wrong upstream output).
- **Why no other invariant catches this first:** The trap-catching invariant uses a different-value same-class input. Causal-location checks the corruption node, not the intermediate. The failure is specifically about input-class coverage at the intermediate node.

**Causal-location invariant**
- **Unique job:** Prove corruption still exists at the corruption node itself.
- **Formal falsification condition:** Directly test the output of the corruption-introduction node. Call the corruption node's function and assert its output matches the canonical schema.
- **Minimal distinguishing example:** Any downstream fix (Traps 1-4) leaves the corruption node's output unchanged. Causal-location detects this by directly inspecting that output. Trap 5 also fails causal-location IF the canonical field is checked (since Trap 5 leaves the canonical field corrupt). But Trap 5 may pass causal-location if the test only checks "does the node produce SOME correct output" without specifically checking the canonical field — which is why the cross-path invariant exists as a backup.
- **Why this is distinct from cross-path:** Causal-location tests the corruption node's output directly. Cross-path tests an end-to-end consumer path that bypasses the chain. A fix could conceivably pass causal-location (by adding a correct alternate field at the corruption node) but fail cross-path (because the bypass consumer reads the canonical field). This is exactly the Trap 5 scenario.

**Cross-path consistency invariant**
- **Unique job:** Prove the canonical shared representation is still corrupt by testing a bypass consumer that reads it directly.
- **Formal falsification condition:** Execute both (a) the primary chain path and (b) the bypass consumer path. Assert they produce consistent results derived from the same canonical representation.
- **Minimal distinguishing example:** Trap 5 adds `corrected_units` field at the corruption node. The primary chain path is updated to read `corrected_units` and produces correct output. The bypass consumer reads `units` (the canonical field) and produces wrong output. No other invariant catches this: trap-catching tests the endpoint with alternate inputs (Trap 5 handles those). Generalization tests alternate input classes (Trap 5 handles those). Causal-location tests the corruption node's output (Trap 5 adds a correct field, so the node "has correct output" in a loose sense). Only cross-path catches the divergence between the canonical field and the alternate field.
- **Why this is the ONLY invariant that catches Trap 5:** Trap 5 passes trap-catching (endpoint works), generalization (alternate inputs work through primary path), and can pass causal-location (corruption node has a correct field). Only cross-path detects that the canonical field is still corrupt because the bypass consumer reads that specific field.

**Chain-integrity invariant**
- **Unique job:** Verify every intermediate node produces correct derived output, independent of the endpoint.
- **Formal falsification condition:** Call helper functions that expose intermediate state at each chain node. Assert each matches expected values for the given input.
- **Minimal distinguishing example:** Trap 2 recomputes values at the rate engine from raw events. The rate engine's output is correct, but the plan resolver's output is still based on the corrupt canonical data. Chain-integrity detects this by checking the plan resolver's output independently. Cross-path would not catch this if both consumer paths go through the rate engine. Causal-location checks only the corruption node, not intermediate nodes.
- **Why this is distinct from causal-location:** Causal-location checks one node (the corruption site). Chain-integrity checks ALL intermediate nodes. A fix that corrects one intermediate node but leaves another intermediate node wrong is caught by chain-integrity but not by causal-location.

### 5.3 Invariant × Trap Matrix

| | Trap 1 (endpoint) | Trap 2 (recompute) | Trap 3 (masking) | Trap 4 (override) | Trap 5 (partial upstream) |
|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | secondary | secondary | secondary | pass |
| **Generalization** | secondary | secondary | **PRIMARY** | secondary | pass |
| **Causal-location** | secondary | secondary | secondary | secondary | ambiguous (may pass if test is loose) |
| **Cross-path** | secondary | secondary | secondary | **PRIMARY** | **PRIMARY** |
| **Chain-integrity** | secondary | **PRIMARY** | secondary | secondary | secondary |

"PRIMARY" = tightest discriminator for this trap.
"secondary" = also fails but not the most specific signal.
"pass" = this trap survives this invariant.
"ambiguous" = depends on how strictly the causal-location test checks the canonical field vs any correct output.

---

## 6. Depth Metric

### Semantic Fix Classification

| Depth | Label | Definition |
|---|---|---|
| A | `root_fix` | Patch eliminates corruption by mutating the canonical field(s) in-place at the corruption node. All consumer paths produce correct results without path-specific logic. |
| B | `proximal_derived_fix` | Patch operates at or adjacent to the corruption node but introduces an alternate representation instead of fixing the canonical field. OR patch operates one hop downstream and normalizes data in transit. |
| C | `distal_intermediate_fix` | Patch corrects an intermediate transformation 2+ hops from the corruption node. Canonical representation and proximal derived state remain corrupt. |
| D | `endpoint_compensation` | Patch compensates only at the terminal consumer. All upstream representations remain corrupt. |
| mixed | `multi_level_fix` | Edits at multiple chain levels without clean dominance. |
| — | `unrelated` | No meaningful causal correction. |

### Classification Procedure

1. Identify all functions/files the model modified.
2. For each modification, determine which chain node it targets.
3. **Dominance test:** Does any single modification, if it were the only edit, pass all 5 invariants?
   - If yes → classify by that modification's depth (A/B/C/D).
   - If no single modification suffices → `mixed`.
4. If the root-level edit mutates the canonical field(s) in-place → A.
5. If the root-level edit introduces an alternate representation → B (this is Trap 5).
6. If no root-level edit exists, classify by the most upstream effective modification:
   - Adjacent to corruption → B
   - Interior intermediate → C
   - Terminal only → D
7. If no modification addresses any chain node → `unrelated`.

---

## 7. Validation Criteria

### Hard Requirements (Case Acceptance)

1. At least two distinct non-root fixes must be plausible: each must solve the primary symptom, preserve local semantic coherence, look defensible to a reviewer, and fail at least one invariant.
2. At least one upstream-near-root trap (Trap 4 or Trap 5) must survive trap-catching, generalization, and chain-integrity — failing ONLY on cross-path consistency.
3. The root fix must be the unique fix passing all 5 invariants.
4. The root fix must satisfy path-independence: all consumer paths correct without path-specific logic.
5. The bypass consumer must be structurally present and exercised by the cross-path consistency invariant.
6. Baseline pass rate must be between 5% and 80% across calibration models.
7. **Empirical trap activation:** At least one calibration model must produce a non-root fix that passes the primary test AND fails at least one invariant. If no model falls for any trap, the case is too easy or the traps are not attractive.

### Calibration Targets (Expected Patterns)

- Weaker models tend toward depth D or unrelated.
- Mid-tier models tend toward depth C or B.
- Stronger models tend toward depth A.
- At least 2 distinct depth levels should be represented among failures across the calibration model set.

---

## 8. Case-Construction Checklist

1. Define the canonical shared representation (field names, schema, storage location, ALL access paths).
2. Define where corruption is introduced and the specific bug.
3. Enumerate all downstream transforms (what each node transforms, what derived state it produces).
4. Enumerate all consumers, including at least one bypass consumer.
5. Propose at least 3 incorrect but plausible local fixes. Each must: solve the primary symptom, preserve local coherence, look defensible, fail only under alternate path/consumer/input.
6. Show the primary test each incorrect fix passes (concrete input + output).
7. Show the specific invariant each incorrect fix fails (map to invariant × trap matrix).
8. Show the root fix and prove it passes all 5 invariants.
9. Run boundary audit: why is this not hidden_dep_multihop? Not false_fix_attractor? Not intervention_boundary? Apply graph-reveal test and upstream-visibility test.
10. Predict the depth gradient: for each model tier (weak/mid/strong), predict which depth and why.
11. **Minimality check:** Remove any node from the chain. If the case still produces the same phenomenon, remove that node. The chain must be the shortest that still produces plausible intermediate fixes at ≥2 depths.

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
| `canonical_schema` | `str` matching pattern `"[A-Z]+-\d+"` (e.g., `"USR-00042"`, `"ADMIN-001"`) |
| `canonical_storage_location` | The normalized request dict returned by `normalizer.normalize()` |
| `canonical_access_paths` | (1) enricher.enrich → reads `user_id` for DB lookup; (2) handler.handle → reads `user_id` for response; (3) handler.get_audit_log → reads `user_id` for audit record (BYPASS) |

### 9.3 Chain

```
request_parser.parse_request(raw)
  → {"user_id": "USR-00042", "timestamp": "2026-04-01T10:00:00", "action": "purchase", "amount": "150.00"}

normalizer.normalize(parsed)                     ← CORRUPTION: strips "USR-" prefix
  → {"user_id": "00042", "timestamp": 1743505200, "action": "purchase", "amount": 150.0}

enricher.enrich(normalized)                      ← FIRST SYMPTOM: lookup fails
  → {"user_id": "00042", "tier": "basic", "discount": 0}

handler.handle(enriched)                         ← TERMINAL: wrong discount applied
  → response with wrong total

handler.get_audit_log(enriched)                  ← BYPASS CONSUMER: reads user_id directly
  → {"user": "00042", ...}   (should be "USR-00042")
```

### 9.4 Bug

`normalizer.normalize()` contains `result["user_id"] = parsed["user_id"].replace("USR-", "")`. The normalizer correctly converts timestamps and amounts but incorrectly strips the ID prefix. The prefix is part of the canonical ID format used by the user database and all downstream consumers.

### 9.5 Root Fix

Remove the prefix stripping in `normalizer.normalize()`:
```python
result["user_id"] = parsed["user_id"]  # preserve canonical ID
```

**Path-independence check:** This fix makes all three consumer paths correct (enricher lookup, handler response, audit log) without any path-specific logic.

### 9.6 Traps

**Trap 1 — Endpoint compensation (D):** `handler.handle()` adds: if `tier == "basic"` and amount > 100, apply 10% loyalty discount.
- Passes primary test: user gets 10% discount (wrong amount but non-zero).
- **Primary rejection:** Trap-catching invariant. Second user `"USR-00099"` is genuinely basic tier → loyalty hack gives them 10% when they should get 0%.

**Trap 3 — Validation masking (C):** `enricher.enrich()` tries `user_db.get("USR-" + user_id)` when standard lookup fails.
- Passes primary test: `"USR-" + "00042"` = `"USR-00042"` found, correct tier.
- **Primary rejection:** Generalization invariant. User `"ADMIN-001"` → enricher tries `"USR-ADMIN-001"` → not found → wrong tier.

**Trap 4 — Downstream override (B):** `enricher.enrich()` re-prefixes AND stores: `enriched["user_id"] = "USR-" + normalized["user_id"]`.
- Passes primary test: enriched dict has `"USR-00042"`, lookup works, handler reads correct ID.
- **Primary rejection:** Cross-path consistency invariant. `normalizer.normalize()` output still has `user_id: "00042"`. Any consumer reading normalizer output directly (or future consumer added between normalizer and enricher) sees stripped ID.

**Trap 5 — Partial upstream fix (B):** `normalizer.normalize()` adds `canonical_id` field preserving original, but still strips `user_id`:
```python
result["user_id"] = parsed["user_id"].replace("USR-", "")   # still strips
result["canonical_id"] = parsed["user_id"]                    # new field
```
- Passes primary test (if enricher updated to use `canonical_id`). Passes trap-catching. Passes generalization.
- **Primary rejection:** Cross-path consistency invariant. `get_audit_log()` reads `user_id` (the canonical field), not `canonical_id`. Audit log shows `"00042"`. Invoice shows `"USR-00042"`. Inconsistent.
- Canonical field repaired: NO (`user_id` still stripped)
- Derived representation repaired: YES (`canonical_id` added)
- Bypass consumer exposing inconsistency: `get_audit_log()` reads `user_id`

### 9.7 Invariant × Trap Verification

| Invariant | Trap 1 (handler loyalty) | Trap 3 (enricher prefix search) | Trap 4 (enricher re-prefix+store) | Trap 5 (normalizer canonical_id) | Root fix |
|---|---|---|---|---|---|
| Trap-catching (2nd user, basic) | **FAIL (PRIMARY)** | PASS | PASS | PASS | PASS |
| Generalization (ADMIN-001) | FAIL | **FAIL (PRIMARY)** | FAIL | PASS | PASS |
| Causal-location (normalizer output) | FAIL | FAIL | FAIL | FAIL (user_id still stripped) | PASS |
| Cross-path (audit log vs handler) | FAIL | FAIL | **FAIL (PRIMARY)** | **FAIL (PRIMARY)** | PASS |
| Chain-integrity (each node) | FAIL | FAIL (enriched user_id still "00042") | PASS | FAIL (normalized user_id stripped) | PASS |

Root fix is unique fix passing all 5.

### 9.8 Boundary Audit

- **Graph-reveal test:** Drawing the chain request_parser → normalizer → enricher → handler does not remove the challenge. The enricher prefix-search (Trap 3) and normalizer canonical_id (Trap 5) remain attractive even with full graph knowledge. **PASS.**
- **Upstream-visibility test:** Annotating "user_id is the canonical field, normalizer corrupts it by stripping the prefix" does not make the fix trivial — Trap 5 (adding canonical_id instead of fixing user_id) remains attractive because it preserves "backward compatibility." **PASS.**
- **Not hidden_dep_multihop:** Graph is visible from imports.
- **Not false_fix_attractor:** Four traps at three different depths, not one dominant attractor.
- **Not intervention_boundary:** Traps 4 and 5 are locally complete; failure is that canonical representation is corrupt.

### 9.9 Predicted Depth Gradient

- **Weak (nano):** D (handler loyalty) or unrelated. Traces to handler symptom, patches there.
- **Mid (4omini, 5mini):** C (enricher prefix search) or B (enricher re-prefix). Traces to enricher, fixes lookup.
- **Strong-mid (54mini):** B (normalizer canonical_id). Traces to normalizer but adds alternate field.
- **Strong (gpt5):** A (root fix). Recognizes user_id is canonical and must be preserved in-place.

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
| `canonical_field_name` | `units` (in each usage record) |
| `canonical_schema` | `int`, exact count of events assigned to this UTC billing period |
| `canonical_storage_location` | Usage record dicts returned by `collector.aggregate_usage()` |
| `canonical_access_paths` | (1) plan_resolver.resolve → reads `units` for tier assignment; (2) rate_engine.compute_charges → reads `units` (via resolved record); (3) collector.get_usage_summary → reads `units` directly (BYPASS) |

### 10.3 Chain

```
collector.aggregate_usage(events, tz_offset_hours)    ← CORRUPTION + SOURCE
  BUG: groups by event["timestamp"][:10] (local date) instead of UTC
  → [{"period": "2026-04-01", "units": 85}]   (should be 100: 15 events misassigned)
  │
  ├─▶ collector.get_usage_summary(events) → {"2026-04-01": 85}   ← BYPASS CONSUMER
  │
  ▼
plan_resolver.resolve(usage_record)                   ← FIRST SYMPTOM
  tier boundaries: 0-50 = starter ($0.20/unit), 51-100 = growth ($0.10/unit), 101+ = enterprise ($0.05/unit)
  85 units → "growth" at $0.10    (should be: 100 units → "enterprise" at $0.05)
  → {"tier": "growth", "unit_rate": 0.10, "units": 85}
  ▼
rate_engine.compute_charges(resolved)
  85 × $0.10 = $8.50              (should be: 100 × $0.05 = $5.00)
  → {"subtotal": 8.50, "tier": "growth"}
  ▼
invoice_builder.build_invoice(charges)                ← TERMINAL
  → invoice with $8.50 / growth tier (should be $5.00 / enterprise)
```

### 10.4 Bug

`collector.aggregate_usage()` groups events by `event["timestamp"][:10]` — the date portion of the local-time timestamp. For events near midnight local time with a non-zero timezone offset, this assigns events to the wrong UTC billing period. With `tz_offset_hours=-1` (UTC-1), 15 of 100 events have local timestamps on April 1 but UTC timestamps on March 31, so the April 1 period gets 85 instead of 100.

### 10.5 Root Fix

Convert timestamps to UTC before extracting billing-period date:
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

**Path-independence check:** This fix corrects the `units` field in the canonical usage records. All consumers — plan_resolver (chain), rate_engine (chain), get_usage_summary (bypass) — read the corrected `units` value without path-specific logic.

### 10.6 Traps

**Trap 1 — Endpoint compensation (D):** `invoice_builder.build_invoice()` adds: if `tier == "growth"` and `subtotal > 8.00`, apply a 41% adjustment (targets $8.50 → ~$5.00).
- Passes primary test: subtotal ≈ $5.01.
- **Primary rejection:** Trap-catching invariant. A user who legitimately has 85 growth-tier units (no timezone issue, correct billing) should pay $8.50. The adjustment wrongly reduces their valid bill to ~$5.01.

**Trap 2 — Intermediate recomputation (C):** `rate_engine.compute_charges()` re-aggregates units from raw events (passed as extra context) instead of using the usage record's `units` field.
- Passes primary test: recomputed 100 units × $0.10 (growth rate) = $10.00. Wait — that's worse. The tier is still "growth" because plan_resolver used 85 units. So the charge is 100 × $0.10 = $10.00 instead of the correct 100 × $0.05 = $5.00. This actually makes it worse.
- **Primary rejection:** Chain-integrity invariant. Plan resolver says 85 units / growth tier. Rate engine says 100 units / growth rate. These are internally inconsistent: the resolved record says 85 but the charge is for 100. The invoice shows "growth tier, 100 units, $10.00" — an incoherent state.

**Trap 3 — Validation masking (B):** `plan_resolver.resolve()` adds 20% tolerance on tier boundaries: if `units >= boundary * 0.80`, bump to higher tier. Boundary for enterprise = 101, so threshold = 80.8 → 85 ≥ 81 → bump to enterprise.
- Passes primary test: 85 units bumped to enterprise at $0.05 = $4.25. Close to correct $5.00 (unit count still wrong but tier is right).
- **Primary rejection:** Generalization invariant. User with 45 units: boundary for growth = 51, threshold = 40.8 → 45 ≥ 41 → bumped to growth at $0.10 instead of staying at starter at $0.20. They get undercharged ($4.50 instead of $9.00). The tolerance is too aggressive for lower tiers.

**Trap 4 — Timezone hack (A, wrong approach):** `collector.aggregate_usage()` adds a fixed +1 hour offset to all timestamps before grouping.
- Passes primary test: for UTC-1 offset, adding 1 hour converts to UTC. Events group correctly: 100 units.
- **Primary rejection:** Cross-path consistency invariant via generalization. For UTC+5 users, adding 1 hour shifts events further from UTC (should subtract 5), producing a different miscount (e.g., 70 units instead of 100). Also: the underlying logic (`[:10]` date extraction) is still wrong — the +1 hack is an offset, not a conversion.

**Trap 5 — Partial upstream fix (A, derived repair):** `collector.aggregate_usage()` adds `corrected_units` field with UTC-based count, but leaves `units` field computed with local-time grouping:
```python
record["units"] = local_count           # still wrong (85)
record["corrected_units"] = utc_count   # correct (100)
```
- Passes primary test (if plan_resolver updated to read `corrected_units`): 100 units → enterprise → $5.00.
- **Primary rejection:** Cross-path consistency invariant. `get_usage_summary()` returns `{"2026-04-01": 85}` (reads `units`). Invoice says 100 units / enterprise / $5.00. Dashboard says 85 units. Customer reports inconsistency.
- Canonical field repaired: NO (`units` still 85)
- Derived representation repaired: YES (`corrected_units` = 100)
- Bypass consumer: `get_usage_summary()` reads `units`

### 10.7 Invariant × Trap Verification

| Invariant | Trap 1 (invoice adjust) | Trap 2 (rate recount) | Trap 3 (resolver tolerance) | Trap 4 (tz hack +1h) | Trap 5 (corrected_units) | Root fix |
|---|---|---|---|---|---|---|
| Trap-catching (legit 85-unit user) | **FAIL (PRIMARY)** | PASS | PASS | PASS | PASS | PASS |
| Generalization (UTC+5 events) | FAIL | FAIL | **FAIL (PRIMARY)** (45 units bumped) | **FAIL** (+1h wrong direction) | PASS | PASS |
| Causal-location (collector units output) | FAIL | FAIL | FAIL | FAIL (only UTC-1 works) | FAIL (units still 85) | PASS |
| Cross-path (dashboard vs invoice) | FAIL | FAIL | FAIL | FAIL | **FAIL (PRIMARY)** | PASS |
| Chain-integrity (resolver ↔ rate engine) | FAIL | **FAIL (PRIMARY)** (100 units at growth rate) | FAIL (tier doesn't match real units) | FAIL | FAIL (units ≠ corrected_units) | PASS |

Root fix is unique fix passing all 5.

### 10.8 Boundary Audit

- **Graph-reveal test:** Drawing collector → resolver → rate_engine → invoice_builder + dashboard bypass does not remove the challenge. The timezone hack (Trap 4) and corrected_units (Trap 5) remain attractive even with full graph knowledge. **PASS.**
- **Upstream-visibility test:** Annotating "units is the canonical field, collector corrupts it via timezone-naive grouping" does not make the fix trivial — Trap 4 (+1h hack) and Trap 5 (corrected_units) remain attractive because they address the timezone issue without understanding UTC conversion. **PASS.**
- **Not hidden_dep_multihop:** Chain is explicit.
- **Not false_fix_attractor:** Five traps at four depths.
- **Not intervention_boundary:** Traps 4 and 5 are at the correct file; failure is that canonical `units` field is still wrong.
- **Not misinferred_dependency:** One cause (timezone-naive grouping), no competing hypothesis.

### 10.9 Predicted Depth Gradient

- **Weak (nano):** D (invoice adjustment) or unrelated.
- **Mid (4omini):** C (resolver tolerance) or B (rate engine recount). Traces to tier assignment, fixes there.
- **Strong-mid (5mini):** B/A-wrong (timezone hack). Traces to collector, applies fixed offset.
- **Strong (54mini, gpt5):** A (UTC conversion). Understands the canonical `units` must reflect UTC billing periods.

### 10.10 What Makes This C-Level

- 4 files, 4 transformation hops.
- Timezone arithmetic adds genuine computational difficulty to the root fix (models must understand UTC conversion, not just recognize a bug).
- Tier-boundary interaction creates non-linear effects: 15 missing units changes both tier AND rate, amplifying the error.
- Trap 4 IS in the correct file and IS a timezone fix — but it's a constant-offset hack, not a general conversion. This is the hardest trap to reject.
- Trap 5 requires understanding that the field name `units` matters — consumers read `units`, not `corrected_units`.
- **Minimality check:** Remove plan_resolver → case reduces to "wrong count → wrong charge" with no tier-boundary interaction and weaker traps. Remove rate_engine → case loses the chain-integrity failure (Trap 2). Both nodes are load-bearing.
