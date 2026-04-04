# `deep_dependency_chain` — Family Specification v3

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v2.md

---

## 1. Family Definition

A `deep_dependency_chain` case is one where:

1. A canonical shared representation exists at some node in the system graph.
2. Corruption is introduced at or near that node, producing a malformed canonical representation.
3. The corrupted representation flows through a chain of 3+ transforming nodes, each producing derived state.
4. The symptom manifests at a terminal consumer.
5. Each intermediate node admits a plausible local fix that (a) restores correctness in that node's derived representation, (b) passes the primary test, (c) preserves local semantic coherence, but (d) leaves the canonical shared representation corrupt.
6. At least one bypass consumer reads the canonical representation directly, exposing the inconsistency that intermediate fixes leave intact.
7. Full correctness requires restoring the canonical shared representation at the corruption site.

The family measures: **failure to propagate a causal fix to the canonical representation when locally-coherent intermediate patches exist at every derived node.**

The dependency graph is visible. The chain structure is discoverable from imports and call signatures. The challenge is not finding the chain — it is rejecting attractive intermediate patches and tracing to the canonical representation.

**Boundary test:** If you handed the model a diagram of A → B → C → D and named all consumer paths, would the case still be hard? If yes, it is a candidate for `deep_dependency_chain`. If revealing the graph structure removes the difficulty, it belongs in `hidden_dep_multihop`.

---

## 2. Ontology

Every `deep_dependency_chain` case must declare these four nodes explicitly:

| Label | Definition | Example (Case 1) | Example (Case 2) |
|---|---|---|---|
| `source_of_truth_node` | The node that owns the canonical shared representation | `request_parser.py` (produces canonical request with full user_id) | `collector.py` (produces canonical usage records) |
| `corruption_introduced_at_node` | The node where the canonical representation is first corrupted | `normalizer.py` (strips ID prefix during normalization) | `collector.py` (groups by local date instead of UTC) |
| `first_observable_symptom_node` | The earliest node where a consumer can observe incorrect behavior | `enricher.py` (user lookup fails, defaults to wrong tier) | `plan_resolver.py` (assigns wrong tier due to undercounted units) |
| `required_fix_node` | The node where the fix must be applied to restore the canonical representation for all consumers | `normalizer.py` | `collector.py` |

If `corruption_introduced_at_node` and `source_of_truth_node` are the same module, the bug corrupts the canonical representation at its origin. If they differ, the source produces correct data and a downstream node corrupts it.

The `required_fix_node` is always the `corruption_introduced_at_node`. The fix restores the canonical representation at the point where it was damaged.

---

## 3. Discriminator

### Primary Rule

A case is `deep_dependency_chain` only if the primary source of model failure, **after the relevant dependency graph is known**, is failure to propagate sufficiently upstream to the canonical representation despite multiple plausible local fixes at derived nodes.

Use `deep_dependency_chain` only when **revealing the dependency graph does not remove the core challenge.**

### Dominance Test

If both dependency-discovery difficulty and propagation-to-root difficulty are present:

- If removing the discovery difficulty (e.g., by annotating which functions depend on which) would eliminate most model failures → `hidden_dep_multihop`
- If removing the discovery difficulty would NOT eliminate most model failures because intermediate patches remain attractive → `deep_dependency_chain`
- If genuinely balanced, annotate: `primary: deep_dependency_chain, secondary: hidden_dep_multihop`

### Full Boundary Table

| Adjacent Family | What model must discover | What model must propagate | Where wrong fix lands | Why it is NOT deep_dependency_chain |
|---|---|---|---|---|
| `hidden_dep_multihop` | Which dependency exists (non-obvious connection) | Fix to the discovered dependency site | At a function the model didn't know was relevant | The chain is short or absent once the dependency is found. Revealing the graph removes the challenge. |
| `false_fix_attractor` | Nothing hidden — symptom and attractor are obvious | Nothing — single-hop fix | At the one dominant symptom-proximal target | One dominant wrong target, no gradient of intermediate fixes. No chain of transforming nodes with derived representations. |
| `misinferred_dependency` | Which of 2+ competing causes is correct | Fix to the correct cause | At the wrong cause's site | Multiple root hypotheses. In deep_dependency_chain, there is one canonical representation and one corruption site — no ambiguity about WHICH cause, only about HOW FAR to propagate. |
| `intervention_boundary` | Nothing — correct target identified | Complete implementation at correct target | At the right function with missing co-effects | Model reaches the correct node but fix is incomplete. In deep_dependency_chain, model reaches the WRONG node (an intermediate) and the fix is locally complete but globally insufficient. |
| `abstraction_leak` | Nothing — correct cause identified | Fix at the correct layer (caller vs callee) | At the wrong abstraction layer of the correct entity | Vertical layer confusion. deep_dependency_chain is horizontal chain-position confusion — model fixes a derived representation instead of the canonical one. |

### Appendix Boundary Proof

**Why this is not `hidden_dep_multihop`:** In `hidden_dep_multihop`, the challenge is that `refresh_user_snapshot` and `sync_user_to_cache` look similar but have different overwrite semantics. Once you discover this semantic distinction, the fix is a one-line function name change. Drawing the dependency graph eliminates the problem. In `deep_dependency_chain`, the dependency graph is already visible — the model can see that normalizer feeds enricher feeds handler — but the model still fails because the enricher-level fix looks correct and passes the primary test.

**Why this is not `false_fix_attractor`:** In `false_fix_attractor`, there is one dominant wrong target (the symptom-proximal one) and one right target. In `deep_dependency_chain`, there are wrong targets at multiple depths — each one more upstream and more correct than the last — creating a gradient. The Trap 5 (partial upstream fix) is especially distinctive: it looks like a root fix but repairs only a derived representation.

**Why this is not `intervention_boundary`:** In `intervention_boundary`, the model reaches the correct function and the fix is incomplete (missing co-effects). In `deep_dependency_chain`, the model reaches a locally-correct fix at a node that is NOT the required fix node — the fix is complete at that node but the canonical representation remains corrupt.

---

## 4. Trap Taxonomy (5 Required)

### Trap 1: Endpoint Compensation

Patch the terminal consumer to handle the malformed data it receives.

- **Looks attractive because:** Directly addresses the user-visible symptom. Matches the debugging instinct "fix where it breaks." Preserves all upstream contracts.
- **Fails because:** The canonical representation is still corrupt. New inputs that trigger different failure modes at the endpoint are unhandled. The bypass consumer sees the same corrupt data.
- **Primary rejection invariant:** Trap-catching (alternate input at endpoint).

### Trap 2: Intermediate Recomputation

Patch an interior node to re-derive correct values from an upstream source, bypassing the corrupted intermediate.

- **Looks attractive because:** Produces correct output for this node. Appears to be a clean workaround.
- **Fails because:** Creates inconsistency between this node's recomputed value and other nodes' derived values. The canonical representation is unchanged. The bypass consumer and chain-integrity checks expose the split.
- **Primary rejection invariant:** Chain-integrity (intermediate output still wrong at other nodes).

### Trap 3: Validation Masking

Patch an interior node to detect and silently coerce malformed input into an acceptable shape.

- **Looks attractive because:** Defensive programming is considered good practice. The coercion handles the observed failure case.
- **Fails because:** The coerced default is semantically wrong for input classes outside the primary test. The canonical representation is unchanged. The bypass consumer sees uncoerced corrupt data.
- **Primary rejection invariant:** Generalization (alternate input class defeats the coercion).

### Trap 4: Downstream Override

Patch the node immediately downstream of the corruption to normalize the canonical representation's corrupt value before forwarding.

- **Looks attractive because:** Closest non-root fix. Appears to address the issue at its source. Preserves the downstream chain.
- **Fails because:** The canonical representation is still corrupt. The bypass consumer reads the canonical representation directly and sees the corrupt value.
- **Primary rejection invariant:** Cross-path consistency (bypass consumer observes stale/corrupt canonical representation).

### Trap 5: Partial Upstream Fix (CRITICAL — Family-Distinguishing Trap)

Fix a derived representation instead of the canonical shared representation. The model traces partway upstream — past the endpoint, past intermediate nodes — but restores correctness in one derived representation while leaving the canonical shared representation corrupt.

- **Looks attractive because:** It IS upstream. It looks like a root fix. It restores correctness for the primary consumer path. A competent reviewer might accept it.
- **Fails because:** The canonical shared representation remains corrupt. The bypass consumer (which reads the canonical representation directly, not the derived one) still observes corruption. The cross-path consistency invariant catches it.
- **Primary rejection invariant:** Cross-path consistency (canonical representation still corrupt for bypass consumer).

**For every case, the spec must answer:**
- What is the canonical shared representation?
- What derived representation does Trap 5 repair instead?
- Which bypass consumer exposes the inconsistency?

---

## 5. Invariants

### 5.1 Invariant × Trap Matrix

| Invariant | Trap 1 (endpoint) | Trap 2 (recompute) | Trap 3 (masking) | Trap 4 (override) | Trap 5 (partial upstream) |
|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | pass | pass | pass | pass |
| **Generalization** | fail | fail | **PRIMARY** | fail | pass |
| **Causal-location** | fail | fail | fail | fail | pass |
| **Cross-path consistency** | fail | fail | fail | **PRIMARY** | **PRIMARY** |
| **Chain-integrity** | fail | **PRIMARY** | fail | fail | fail |

Each invariant has exactly one primary rejection target. No two invariants are redundant.

### 5.2 Invariant Definitions

**Trap-catching invariant:**
- **Unique job:** Kill endpoint-only compensation.
- **Mechanism:** Second input configuration where the endpoint compensation does not apply. Example: if Trap 1 adds a fallback for null values, the second input produces a non-null but semantically wrong value that the fallback does not catch.
- **Falsification target:** Trap 1 only.

**Generalization invariant:**
- **Unique job:** Kill input-class-specific hacks and tolerance tricks.
- **Mechanism:** Third input configuration from a different input class that the validation/coercion does not handle. Example: if Trap 3 adds `"USR-"` prefix matching, use an `"ADMIN-"` prefixed ID.
- **Falsification target:** Trap 3 primarily; also catches Traps 1, 2.

**Causal-location invariant:**
- **Unique job:** Prove corruption still exists upstream of the patched node.
- **Mechanism:** Directly test the output of the corruption-introduction node. Example: call `normalizer.normalize()` and assert the output matches expected canonical form. If any fix is downstream of normalizer, the normalizer output is still wrong.
- **Falsification target:** Traps 1-4 (all downstream fixes). Trap 5 passes this because it IS at the corruption node — but repairs a derived representation, not the canonical one.

**Cross-path consistency invariant:**
- **Unique job:** Prove the canonical shared representation is still corrupt by testing a bypass consumer.
- **Mechanism:** A second API path reads the canonical representation without going through the patched intermediate chain. Both paths must observe consistent state from the canonical representation.
- **Falsification target:** Traps 4 and 5 primarily. This is the ONLY invariant that catches Trap 5.

**Chain-integrity invariant:**
- **Unique job:** Verify every node in the chain produces correct derived output, independent of the endpoint.
- **Mechanism:** Helper functions expose intermediate state at each node. Test asserts each node's output matches expected values.
- **Falsification target:** Trap 2 primarily (recomputation fixes one node but leaves others wrong).

---

## 6. Depth Metric

### Semantic Fix Classification

For each model output, classify the fix by its causal depth. Classification is NOT based on which file was edited. It is based on what the fix accomplishes causally.

| Depth | Label | Definition |
|---|---|---|
| A | `root_fix` | Patch eliminates corruption at its introduction point. The canonical shared representation is restored for ALL consumers. No downstream compensation remains necessary. |
| B | `proximal_derived_fix` | Patch corrects a derived representation at the node adjacent to the corruption site. The canonical shared representation remains corrupt. At least one bypass consumer still observes corruption. |
| C | `distal_intermediate_fix` | Patch corrects an intermediate transformation but not the canonical or proximal derived representation. Multiple bypass consumers observe corruption. |
| D | `endpoint_compensation` | Patch compensates only at the terminal consumer or output renderer. All upstream representations remain corrupt. |
| mixed | `multi_level_fix` | Edits at multiple chain levels without clean dominance. Example: patches both endpoint and an intermediate. |
| — | `unrelated` | No meaningful causal correction. Wrong function, parse error, no change. |

### Classification Procedure

1. Identify which functions/files the model modified.
2. For each modification, determine which node in the chain it targets.
3. Determine whether the canonical shared representation is restored (check: does the corruption-introduction node now produce correct output?).
4. If yes → `root_fix` (A).
5. If no, determine the most-upstream node that was corrected:
   - Adjacent to corruption → `proximal_derived_fix` (B)
   - Interior intermediate → `distal_intermediate_fix` (C)
   - Terminal only → `endpoint_compensation` (D)
6. If modifications span 2+ levels with no single dominant correction → `multi_level_fix`.
7. If no modification addresses any chain node → `unrelated`.

---

## 7. Validation Criteria

### Hard Requirements (Case Acceptance)

These must be met or the case is rejected:

1. At least two distinct non-root fixes must be plausible: each must (a) pass the primary test input, (b) preserve local semantic coherence at the patched node, (c) look defensible to a competent reviewer.
2. At least one upstream-near-root trap (Trap 4 or Trap 5) must survive the trap-catching, generalization, and causal-location invariants — failing ONLY on cross-path consistency or chain-integrity.
3. The root fix must be the unique fix that passes ALL five invariants.
4. The bypass consumer must be structurally present and exercised by the cross-path consistency invariant.
5. Baseline pass rate must be between 5% and 80% across calibration models (not floor, not ceiling).

### Calibration Targets (Expected Patterns, Not Acceptance Criteria)

These are expected patterns that validate the family is producing the intended signal. Failure to meet them triggers investigation, not automatic rejection:

- Weaker models tend to produce fixes at depth D (endpoint) or unrelated.
- Mid-tier models tend to produce fixes at depth C or B (intermediate).
- Stronger models tend to reach depth A (root).
- Across the calibration model set, at least 2 distinct depth levels should be represented among failures.

### Aspirational Gradients

- The depth distribution should shift upstream as model capability increases.
- Intervention conditions (critique, reasoning-only) should shift the depth distribution upstream relative to baseline.

---

## 8. Case-Construction Checklist

For each candidate `deep_dependency_chain` case, the author must complete all 10 steps:

1. **Define the canonical shared representation.** What data structure or value is the single source of truth? Where does it live?
2. **Define where corruption is introduced.** Which node transforms the canonical representation incorrectly? What is the specific bug?
3. **Enumerate all downstream transforms.** List each node, what it transforms, and what derived representation it produces.
4. **Enumerate all consumers, including at least one bypass consumer.** The bypass consumer must read the canonical representation without passing through the intermediate chain.
5. **Propose at least 3 incorrect but plausible local fixes.** Each must: solve the primary symptom, preserve local semantic coherence, look defensible to a reviewer, and fail only under alternate path/consumer/input.
6. **Show the primary test each incorrect fix passes.** Concrete input + expected output.
7. **Show the specific invariant each incorrect fix fails.** Map to the invariant × trap matrix.
8. **Show the root fix and prove it passes all 5 invariants.** Concrete code change + all 5 invariant outcomes.
9. **Run a boundary audit against neighboring families.** Answer: why is this not hidden_dep_multihop? Not false_fix_attractor? Not intervention_boundary?
10. **Predict the depth gradient.** For each model tier (weak/mid/strong), predict which depth level they are most likely to produce and why.

---

## 9. Case 1: `request_context_chain` (Difficulty B)

### 9.1 Node Declarations

| Label | Value |
|---|---|
| `source_of_truth_node` | `request_parser.py` — produces canonical request dict with full `user_id` (e.g., `"USR-00042"`) |
| `corruption_introduced_at_node` | `normalizer.py` — strips `"USR-"` prefix from `user_id` during field normalization |
| `first_observable_symptom_node` | `enricher.py` — user lookup fails because DB keys use prefixed IDs |
| `required_fix_node` | `normalizer.py` |

### 9.2 File Layout and Chain

```
request_parser.py  (Source)
  │  parse_request(raw) → {"user_id": "USR-00042", "timestamp": "...", "action": "purchase", "amount": "150.00"}
  ▼
normalizer.py  (Corruption site — REQUIRED FIX HERE)
  │  normalize(parsed) → {"user_id": "00042", ...}  ← BUG: strips "USR-" prefix
  ▼
enricher.py  (First symptom)
  │  enrich(normalized) → {"user_id": "00042", "tier": "basic", "discount": 0}  ← lookup fails, defaults to basic
  ▼
handler.py  (Terminal consumer)
  │  handle(enriched) → response with wrong discount
  │
  └─ get_audit_log(enriched) → audit record  ← BYPASS CONSUMER (reads user_id from enriched dict)
```

### 9.3 Canonical Shared Representation

The `user_id` field as produced by `request_parser.parse_request()`. Canonical format: `"USR-NNNNN"`. This value is consumed by: enricher (for DB lookup), handler (for response), audit log (for compliance record).

### 9.4 Bug

`normalizer.normalize()` strips the `"USR-"` prefix from `user_id`, producing `"00042"` instead of `"USR-00042"`. The normalizer correctly converts timestamps (string → epoch) and amounts (string → float), but the ID stripping is incorrect — the prefix is part of the canonical ID format.

### 9.5 Root Fix

In `normalizer.py`, remove the prefix-stripping line:

```python
def normalize(parsed):
    return {
        "user_id": parsed["user_id"],          # preserve canonical ID
        "timestamp": parse_timestamp(parsed["timestamp"]),
        "action": parsed["action"].lower(),
        "amount": float(parsed["amount"]),
    }
```

### 9.6 Trap Fixes

**Trap 1 — Endpoint compensation (D):**
In `handler.py`, add: if `tier == "basic"` and amount > 100, apply a 10% "loyalty discount."
- **Passes primary test:** User gets a discount (10% instead of correct 20%, but non-zero).
- **Looks attractive:** Reasonable business logic. Addresses the user-visible complaint.
- **Killed by trap-catching invariant:** Second user `"USR-00099"` IS genuinely basic tier. The loyalty hack gives them 10% when they should get 0%.

**Trap 3 — Validation masking (C):**
In `enricher.py`, when user lookup fails, try `user_db.get("USR-" + user_id)`.
- **Passes primary test:** User `"USR-00042"` is found, correct tier assigned.
- **Looks attractive:** Defensive lookup. Handles the immediate failure.
- **Killed by generalization invariant:** User `"ADMIN-001"` → enricher tries `"USR-ADMIN-001"` → not found → wrong tier. Also, `user_id` in enriched dict is still `"00042"`.

**Trap 4 — Downstream override (B→C):**
In `enricher.py`, re-prefix `user_id` before lookup AND store the re-prefixed version: `enriched["user_id"] = "USR-" + user_id`.
- **Passes primary test:** Lookup works, enriched dict has correct-looking ID for primary path.
- **Looks attractive:** Closest to root. Appears to fully resolve the issue for the enricher's consumers.
- **Killed by cross-path consistency invariant:** The `normalizer.normalize()` output still produces `"00042"`. Any consumer that reads normalizer output directly (or any future consumer added after normalizer but before enricher) sees the stripped ID.

**Trap 5 — Partial upstream fix (B):**
In `normalizer.py`, add a `canonical_id` field that preserves the original user_id, but still strip `user_id` for "backward compatibility":
```python
result["user_id"] = parsed["user_id"].replace("USR-", "")  # still strips
result["canonical_id"] = parsed["user_id"]                   # adds new field
```
- **Passes primary test:** If enricher is updated to use `canonical_id`, lookup works.
- **Looks attractive:** Adds the correct data. Appears to be a careful migration approach.
- **Killed by cross-path consistency invariant:** `handler.handle()` and `get_audit_log()` read `user_id`, not `canonical_id`. They still see `"00042"`. The canonical shared representation (`user_id` field in the normalized dict) is still corrupt.

**Trap 5 details:**
- Canonical shared representation: `user_id` field in normalized request dict
- Derived representation repaired by Trap 5: new `canonical_id` field (not part of the canonical schema)
- Bypass consumer exposing inconsistency: `get_audit_log()` reads `user_id`, not `canonical_id`

### 9.7 Invariant × Trap Verification

| Invariant | Trap 1 (handler loyalty) | Trap 3 (enricher prefix search) | Trap 4 (enricher re-prefix + store) | Trap 5 (normalizer canonical_id) | Root fix |
|---|---|---|---|---|---|
| Trap-catching (2nd user, basic tier) | **FAIL** (gives discount to basic user) | PASS | PASS | PASS | PASS |
| Generalization (ADMIN-001 user) | FAIL | **FAIL** (USR-ADMIN-001 not found) | FAIL (USR-ADMIN-001) | PASS (canonical_id correct) | PASS |
| Causal-location (normalizer output check) | FAIL | FAIL | FAIL | FAIL (user_id still stripped) | PASS |
| Cross-path (audit log user_id) | FAIL | FAIL | FAIL (normalizer output still wrong) | **FAIL** (audit reads user_id, not canonical_id) | PASS |
| Chain-integrity (each node output) | FAIL | FAIL (enriched user_id still "00042") | PASS (enriched user_id fixed) | FAIL (normalized user_id still stripped) | PASS |

Root fix is the unique fix passing all 5 invariants.

### 9.8 Boundary Audit

- **Not hidden_dep_multihop:** The chain request_parser → normalizer → enricher → handler is visible from imports. Revealing it does not remove the challenge — intermediate fixes remain attractive.
- **Not false_fix_attractor:** Multiple wrong targets at different depths (handler, enricher, normalizer), not one dominant symptom-proximal target.
- **Not intervention_boundary:** Trap 4 and Trap 5 are locally complete — they fully solve the patched node's problem. The failure is that the canonical representation is still corrupt, not that the fix is incomplete.

### 9.9 Predicted Depth Gradient

- **Weak models (nano):** Likely depth D (handler compensation) or C (enricher prefix search). Will see the symptom in handler, trace to enricher, and fix there.
- **Mid-tier models (4omini, 5mini):** Likely depth C or B (enricher re-prefix, or normalizer canonical_id). Will trace past the enricher to the normalizer but produce a Trap 5 fix that adds a new field instead of fixing the existing one.
- **Strong models (54mini, gpt5):** Likely depth A (root fix). Will recognize that `user_id` is the canonical field and must be preserved as-is.

---

## 10. Case 2: `billing_aggregation_chain` (Difficulty C)

### 10.1 Node Declarations

| Label | Value |
|---|---|
| `source_of_truth_node` | `collector.py` — produces canonical usage records per billing period |
| `corruption_introduced_at_node` | `collector.py` — groups events by local-time date instead of UTC billing period |
| `first_observable_symptom_node` | `plan_resolver.py` — assigns wrong tier due to undercounted units |
| `required_fix_node` | `collector.py` |

### 10.2 File Layout and Chain

```
collector.py  (Source + Corruption site — REQUIRED FIX HERE)
  │  aggregate_usage(events, tz_offset) → [{"period": "2026-04-01", "units": 85}]
  │  BUG: uses event["timestamp"][:10] (local date) instead of converting to UTC first
  │  Events near midnight local time assigned to wrong period → undercounts some periods
  │
  ├─▶ get_usage_summary(events) → {"2026-04-01": 85}  ← BYPASS CONSUMER (dashboard)
  │
  ▼
plan_resolver.py  (First symptom)
  │  resolve(usage_record) → {"tier": "growth", "unit_rate": 0.10, "units": 85}
  │  85 units → "growth" tier (should be 100 units → "enterprise" at $0.05/unit)
  ▼
rate_engine.py
  │  compute_charges(resolved) → {"subtotal": 8.50, "tier": "growth"}
  │  85 × $0.10 = $8.50 (should be 100 × $0.05 = $5.00)
  ▼
invoice_builder.py  (Terminal consumer)
  │  build_invoice(charges) → invoice with wrong total and wrong tier
```

### 10.3 Canonical Shared Representation

The per-period usage record produced by `collector.aggregate_usage()`. Canonical form: `{"period": "YYYY-MM-DD", "units": N}` where `period` is a UTC billing date and `units` is the exact count of events in that UTC period. This is consumed by: plan_resolver (via chain), and usage_dashboard (bypass consumer, directly from collector).

### 10.4 Bug

`collector.aggregate_usage()` groups events by `event["timestamp"][:10]` — the date portion of the local-time timestamp string. For events near midnight local time, this assigns them to the wrong UTC billing period. 15 events in a test set are misassigned, producing 85 units instead of 100 for the target period.

### 10.5 Root Fix

In `collector.py`, convert timestamps to UTC before extracting the date:

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

### 10.6 Trap Fixes

**Trap 1 — Endpoint compensation (D):**
In `invoice_builder.py`, add: if tier is "growth" and subtotal > $8, apply a 40% "enterprise adjustment" discount.
- **Passes primary test:** Subtotal drops from $8.50 to $5.10 (close to correct $5.00).
- **Looks attractive:** Business-level billing adjustment. Common pattern in invoicing.
- **Killed by trap-catching invariant:** Run with a user who legitimately has 85 units (no timezone issue). The adjustment wrongly discounts their valid growth-tier bill.

**Trap 3 — Validation masking (B):**
In `plan_resolver.py`, add 15% tolerance on tier boundaries: if units are within 15% of a boundary, bump to higher tier.
- **Passes primary test:** 85 is within 18% of 100 → bumped to "enterprise."
- **Looks attractive:** Defensive tier assignment. Handles edge cases.
- **Killed by generalization invariant:** User at 55 units gets bumped from "starter" to "growth" (55 is within 9% of 51 boundary — wait, that's within tolerance). Different example: user at 45 units bumped from starter to growth when they shouldn't be. The tolerance is too aggressive for small counts.

**Trap 2 — Recomputation at rate engine (C):**
In `rate_engine.py`, re-count units from the original events list instead of using the usage record.
- **Passes primary test:** 100 correct units × $0.10 growth rate = $10.00. Wait — that's worse because tier is still "growth." So the rate engine would need the correct count AND the correct tier. This trap demonstrates inconsistency: the re-counted units don't match the tier assignment.
- **Looks attractive:** Appears to get the "real" count.
- **Killed by chain-integrity invariant:** Plan resolver output says 85 units/growth tier, but rate engine uses 100 units with growth rate. The outputs are internally inconsistent. The invoice shows "growth tier" but charges for 100 units at growth rate ($10.00) — more than either the correct ($5.00) or original wrong ($8.50) amount.

**Trap 4 — Partial upstream fix (A, but wrong):**
In `collector.py`, add `+1` hour offset to all timestamps before grouping — a timezone hack that happens to work for the primary test (UTC-1 offset).
- **Passes primary test:** For UTC-1, adding 1 hour converts to UTC. Events group correctly.
- **Looks attractive:** Appears to fix the timezone issue. IS in the correct file.
- **Killed by generalization invariant:** For UTC+5 users, adding 1 hour shifts events the wrong direction, producing a DIFFERENT miscount.

**Trap 5 — Partial upstream fix (A, derived repair):**
In `collector.py`, add a `corrected_units` field alongside the original `units`:
```python
record["units"] = naive_count           # still wrong
record["corrected_units"] = utc_count   # correct but not used by consumers
```
- **Passes primary test:** If plan_resolver is updated to read `corrected_units`, it assigns the correct tier.
- **Looks attractive:** Preserves backward compatibility. Adds the correct data.
- **Killed by cross-path consistency invariant:** `get_usage_summary()` returns `units` (the wrong value). Dashboard shows 85 units; invoice shows 100 units. Customer complains about inconsistency.

**Trap 5 details:**
- Canonical shared representation: `units` field in usage record
- Derived representation repaired: `corrected_units` field (not part of canonical schema)
- Bypass consumer: `get_usage_summary()` reads `units` directly

### 10.7 Invariant × Trap Verification

| Invariant | Trap 1 (invoice adjust) | Trap 2 (rate recount) | Trap 3 (resolver tolerance) | Trap 4 (timezone hack) | Trap 5 (corrected_units) | Root fix |
|---|---|---|---|---|---|---|
| Trap-catching (legitimate 85-unit user) | **FAIL** | PASS | PASS | PASS | PASS | PASS |
| Generalization (UTC+5 events) | FAIL | FAIL | **FAIL** (aggressive bumping) | **FAIL** (wrong direction) | PASS | PASS |
| Causal-location (collector output units) | FAIL | FAIL | FAIL | FAIL (only works for UTC-1) | FAIL (units field still wrong) | PASS |
| Cross-path (dashboard vs invoice) | FAIL | FAIL | FAIL | FAIL | **FAIL** (dashboard reads units) | PASS |
| Chain-integrity (each node output consistent) | FAIL | **FAIL** (rate ≠ tier) | FAIL (tier doesn't match actual units) | FAIL | FAIL | PASS |

Root fix is the unique fix passing all 5 invariants.

### 10.8 Boundary Audit

- **Not hidden_dep_multihop:** The chain collector → resolver → rate_engine → invoice_builder is explicit. The bypass consumer (dashboard) is declared in the same file. Revealing the graph does not remove the challenge.
- **Not false_fix_attractor:** 5 distinct traps at 4 different depths. No single dominant attractor.
- **Not intervention_boundary:** Trap 4 and Trap 5 are at the correct file (collector.py) but fix the wrong thing. They are locally complete; the failure is that the canonical `units` field remains corrupt.
- **Not misinferred_dependency:** There is one root cause (timezone-naive grouping). No competing hypothesis.

### 10.9 Predicted Depth Gradient

- **Weak models (nano):** Likely depth D (invoice adjustment) or unrelated. Will see the overcharge symptom and patch the invoice.
- **Mid-tier models (4omini):** Likely depth C or B (resolver tolerance or rate engine recount). Will trace to the tier assignment and fix there.
- **Strong-mid models (5mini):** Likely depth B or A-wrong (timezone hack or corrected_units field). Will trace to the collector but produce a partial fix.
- **Strong models (54mini, gpt5):** Likely depth A (UTC conversion). Will recognize the canonical representation must be fixed at the source.

### 10.10 What Makes This C-Level

- 4 files, 4 transformation hops
- Timezone arithmetic adds genuine computational difficulty to the root fix
- The tier-boundary interaction means the bug's effect is non-linear (85 units → wrong tier → wrong rate → cascading overcharge)
- Trap 4 (timezone hack) IS in the correct file and IS a timezone fix — it just doesn't generalize. This is the hardest trap to reject.
- The corrected_units Trap 5 requires understanding that the canonical field name matters, not just the value.
