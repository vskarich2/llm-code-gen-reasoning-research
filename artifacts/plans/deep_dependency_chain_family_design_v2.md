# `deep_dependency_chain` — Family Specification v2

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v1.md

---

## 1. Family Definition

A `deep_dependency_chain` case is one where:

1. A bug originates at an upstream source node A.
2. The system contains a chain A → B → C → ... → D where each node transforms state (not identity passthrough).
3. Each intermediate node admits a plausible local fix that (a) appears semantically correct, (b) passes some inputs, and (c) fails under alternate downstream usage or cross-path consumption.
4. Local fixes produce partial correctness but global inconsistency.
5. Full correctness requires propagating the fix to the true root (A).

A case is INVALID if any intermediate node does not admit a plausible local fix that passes at least the primary test input.

The family measures: **forced global causal propagation under plausible local fixes.** Not multi-hop tracing. Not hidden dependency discovery. The dependency graph is known. The challenge is determining how far upstream the fix must propagate when every intermediate node offers a locally-coherent patch.

---

## 2. Discriminator

### Canonical Rule

If the dependency graph is unclear → `hidden_dep_multihop`
If the dependency graph is known but the model fails to propagate fixes across the full chain → `deep_dependency_chain`

### Full Boundary Table

| Situation | Family |
|---|---|
| Dependency between nodes is non-obvious; must discover which function matters | `hidden_dep_multihop` |
| One dominant wrong target near symptom; no gradient of intermediate fixes | `false_fix_attractor` |
| Two comparably plausible root causes requiring disambiguation | `misinferred_dependency` |
| Correct root cause identified, fix at wrong abstraction layer (caller/callee) | `abstraction_leak` |
| Correct target function, implementation incomplete (missing co-effects) | `intervention_boundary` |
| **Dependency graph visible, 3+ transforming nodes, plausible local fix at each intermediate, model stops short of root** | **`deep_dependency_chain`** |

### Mandatory Assignment Rule

If a case has 3+ transformation hops AND ≥2 intermediate nodes each admitting a plausible local fix that passes the primary test input, it is `deep_dependency_chain` regardless of whether it also involves hidden dependencies. The chain-propagation challenge dominates.

---

## 3. Trap Taxonomy (5 Required)

### Trap 1: Endpoint Compensation

Patch the terminal consumer to handle malformed upstream data. Add null-check, fallback default, or type coercion at D.

**Why it partially works:** Addresses the immediate crash/failure at the symptom site.
**Why it fails globally:** New inputs that trigger a different failure path at D are unhandled. Upstream data remains corrupt for all other consumers.

### Trap 2: Downstream Recomputation

Patch an interior node to re-derive the correct value from scratch, bypassing the broken upstream output.

**Why it partially works:** The recomputed value is correct for the recomputation's input domain.
**Why it fails globally:** Creates inconsistency between the recomputed value and the original chain's cached/derived state. Other consumers of the upstream node's output still see corrupt data.

### Trap 3: Validation Masking

Patch an interior node to validate and silently coerce its input into the expected shape.

**Why it partially works:** Coerced value passes type/shape checks downstream.
**Why it fails globally:** The coerced default is semantically wrong for some input classes. Hides the upstream error from monitoring. Cross-path consumers bypass the validation.

### Trap 4: Downstream Override

Patch the node immediately downstream of the root cause to normalize A's output before forwarding.

**Why it partially works:** Closest to the root. Correctly transforms A's output for the primary path.
**Why it fails globally:** When A's output is consumed by a second path that doesn't go through this node, the second path sees corrupt data. Cross-path consistency invariant catches this.

### Trap 5: Partial Upstream Fix (CRITICAL)

Fix a derived representation instead of the source representation. The model traces partway upstream — past the endpoint, past the intermediates — but fixes B's internal state rather than A's output.

**Why it partially works:** B now produces correct output for the primary chain. Locally indistinguishable from a root fix.
**Why it fails globally:** B's fix only corrects B's output. A still produces corrupt data. Any new consumer added to A (or any existing consumer that bypasses B) sees the original corrupt state. The system is inconsistent: B is patched but A is still broken.

This trap is the most dangerous because it appears upstream and looks like a real fix. It is the distinguishing trap of this family.

---

## 4. Invariants (5 Required)

### 4.1 Trap-Catching Invariant

Tests the primary symptom with a second input configuration that the endpoint compensation does not handle.

**Purpose:** Rejects Trap 1 (endpoint compensation). The endpoint patch handles the first test input but the second input triggers a different failure path at the endpoint.

### 4.2 Generalization Invariant

Tests with ≥2 distinct input configurations that exercise different transformation paths through the chain.

**Purpose:** Rejects Traps 2 and 3 (recomputation, validation masking). The intermediate fix works for one input class but a second input class bypasses or breaks the fix.

### 4.3 Causal-Location Invariant

Verifies the fix is at the correct node by testing a second consumer path that uses the same upstream data but does not pass through the patched intermediate.

**Purpose:** Rejects Trap 4 (downstream override). If B is patched, test path A→C→E that bypasses B. B's fix doesn't help C.

### 4.4 Cross-Path Consistency Invariant (NEW — REQUIRED)

All consumers of shared upstream state must observe consistent behavior.

**Purpose:** Rejects Trap 5 (partial upstream fix). If B is fixed internally but A still produces corrupt output, a second API path that reads A's output directly (without going through B) will see stale/corrupt state.

**Structure:**
```
API path 1: uses chain A → B → C → D (may appear fixed)
API path 2: uses A → X directly (bypasses B, C, D)
Both paths must see consistent state from A.
```

If path 1 returns correct data but path 2 returns corrupt data → FAIL.

### 4.5 Chain-Integrity Invariant

Tests intermediate state directly at each node in the chain, independent of the endpoint.

**Purpose:** Ensures the data is correct at every stage, not just at the terminal consumer. Catches any fix that masks corruption at an intermediate node.

**Structure:** Helper functions `get_node_b_output()`, `get_node_c_output()` expose intermediate state. Test asserts each matches expected values.

---

## 5. Validation Criteria

### Stage 2 Failure Classification

For each failed model output, classify by `chain_depth_of_fix`:

| Depth | Label | Definition |
|---|---|---|
| D | `endpoint_patch` | Model modifies terminal consumer only |
| C | `intermediate_patch_distal` | Model modifies a node 1-2 hops from endpoint |
| B | `intermediate_patch_proximal` | Model modifies node adjacent to root (Trap 5 zone) |
| A | `root_fix_incomplete` | Model targets root but implementation is wrong |
| — | `unrelated` | Model modifies unrelated function or produces parse error |

### Thresholds (HARD)

- ≥60% of failures occur at non-root nodes (D + C + B combined)
- ≥25% of failures MUST be intermediate-node fixes (C + B)
- Root fixes (A, whether complete or incomplete) must NOT exceed 30% of early model behavior (first 10 trials per model)
- If these thresholds are not met → case is rejected and must be redesigned

### Depth Gradient Requirement

Across the calibration model set:
- Weaker models should concentrate fixes at D (endpoint)
- Mid-tier models should concentrate at C or B (intermediate)
- Stronger models should reach A (root)

If all models produce the same depth distribution → the case does not produce a gradient → reject.

---

## 6. Depth Metric

Every `deep_dependency_chain` evaluation must emit:

```python
chain_depth_of_fix: str  # "A" | "B" | "C" | "D" | "unrelated"
```

Determined by which file(s) the model modified:
- Modified only the terminal consumer file → D
- Modified an intermediate file → C or B (by position in chain)
- Modified the source file → A
- Modified unrelated files or no meaningful change → unrelated

This metric is logged in the event `extra` section and used for all family-level analyses.

---

## 7. Case Quality Requirements

All `deep_dependency_chain` cases MUST:

- Be multi-file: ≥3 files for B-level, ≥4 files for C-level
- Contain real transformations at each node (not assignment passthrough)
- Include at least 2 plausible incorrect fixes that pass the primary test input
- Require reasoning across file boundaries (not solvable by reading one file)
- Have a second consumer path that exercises the cross-path consistency invariant
- Produce a measurable depth gradient across model capability tiers

---

## 8. Case 1: `request_context_chain` (Difficulty B)

### 8.1 Scenario

A web application processes API requests through a middleware chain. The `request_parser` extracts fields from raw HTTP input. The `normalizer` canonicalizes field formats. The `enricher` adds derived metadata based on normalized fields. The `handler` uses enriched request to produce a response.

### 8.2 File Layout

```
request_parser.py   — parses raw request dict, extracts fields
normalizer.py       — canonicalizes field formats (dates, names, IDs)
enricher.py         — derives metadata (user tier, region, flags) from normalized fields
handler.py          — uses enriched request to build response
```

### 8.3 Chain

```
A: request_parser.parse_request(raw)
   → produces: {"user_id": "USR-00042", "timestamp": "2026-04-01T10:00:00", "action": "purchase", "amount": "150.00"}

B: normalizer.normalize(parsed)
   → BUG: strips prefix from user_id ("USR-00042" → "00042") for "normalization"
   → produces: {"user_id": "00042", "timestamp": 1743505200, "action": "purchase", "amount": 150.0}

C: enricher.enrich(normalized)
   → looks up user tier by user_id in user_db
   → "00042" not found (db keys are "USR-00042")
   → silently defaults to tier="basic"
   → produces: {"user_id": "00042", ..., "tier": "basic", "discount": 0}

D: handler.handle(enriched)
   → applies discount based on tier
   → user should get 20% premium discount, gets 0%
   → response has wrong total
```

### 8.4 Bug Location

`normalizer.py`: `normalize()` strips the `"USR-"` prefix from `user_id`. The normalizer is supposed to canonicalize dates and amounts (string→int/float) but should NOT strip ID prefixes — the prefix is part of the canonical ID format used by the user database.

### 8.5 Root Fix (Node A/B boundary)

In `normalizer.py`, remove the line that strips the `USR-` prefix:

```python
def normalize(parsed):
    result = {}
    result["user_id"] = parsed["user_id"]  # FIX: preserve full ID
    result["timestamp"] = parse_timestamp(parsed["timestamp"])
    result["action"] = parsed["action"].lower()
    result["amount"] = float(parsed["amount"])
    return result
```

### 8.6 Trap Fixes

**Trap 1 — Endpoint compensation (D):**
In `handler.py`, add a fallback: if `tier == "basic"` and amount > 100, apply a "loyalty discount" of 10%. Partially works for the primary test (user gets some discount) but wrong amount (10% not 20%) and breaks for users who genuinely are basic tier.

**Trap 2 — Validation masking (C):**
In `enricher.py`, when user lookup fails, try stripping/adding prefixes to search for the user: `user_db.get("USR-" + user_id)`. Partially works for `USR-` prefixed IDs but fails for other ID formats (e.g., `ADMIN-` prefix users). Also, the normalized user_id downstream is still `"00042"`, breaking any other consumer that needs the canonical ID.

**Trap 3 — Downstream override (B→C boundary):**
In `enricher.py`, re-prefix the user_id before lookup: `canonical_id = "USR-" + user_id`. Works for the primary lookup but the enriched output still contains `user_id: "00042"` — other consumers of the enriched request (logging, analytics) see the wrong ID.

**Trap 4 — Partial upstream fix (B):**
In `normalizer.py`, instead of removing the stripping, add a separate `canonical_id` field that preserves the original while still stripping `user_id`. The enricher could use `canonical_id` for lookup. But the downstream handler and all other consumers still reference `user_id` (the stripped version), so logging, response headers, and audit trails all show the wrong ID.

### 8.7 Second Consumer Path (Cross-Path Invariant)

```python
# In handler.py:
def get_audit_log(enriched):
    """Returns audit record — must contain canonical user_id."""
    return {
        "user": enriched["user_id"],
        "action": enriched["action"],
        "amount": enriched["amount"],
    }
```

The audit log reads `user_id` from the enriched request. If the normalizer strips the prefix, the audit log records `"00042"` instead of `"USR-00042"`. Traps 2, 3, and 4 that fix the enricher lookup do NOT fix the audit log — the `user_id` field in the enriched dict is still wrong.

### 8.8 Invariants

**Trap-catching:** Call `handle()` with a second user whose ID is `"USR-00099"` (basic tier in DB). The endpoint compensation (Trap 1) applies loyalty discount to this basic-tier user, which is incorrect — basic users should get 0%.

**Generalization:** Call with a user whose ID format is `"ADMIN-001"`. The enricher prefix hack (Trap 2) prepends `"USR-"` which produces `"USR-ADMIN-001"` — not found. The normalizer must preserve arbitrary ID formats, not just `USR-` prefixed ones.

**Causal-location:** Verify that `normalizer.normalize()` output contains the full canonical user_id. If the fix is in the enricher, the normalizer output is still stripped.

**Cross-path consistency:** `handle()` response user_id must match `get_audit_log()` user_id. Both must equal the original canonical ID. If the enricher is patched for lookup but `user_id` field is still stripped, the handler response shows `"00042"` but the correct value is `"USR-00042"`.

**Chain-integrity:** Helper `get_normalized_user_id(raw)` calls parse + normalize and returns the user_id. Must equal the input's user_id exactly. Independently verifiable without running the full chain.

### 8.9 Validation Matrix

| Variant | Trap-catch | Generalization | Causal-loc | Cross-path | Chain-integrity | Overall |
|---|---|---|---|---|---|---|
| No-op (buggy) | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| Root fix (normalizer preserves ID) | PASS | PASS | PASS | PASS | PASS | PASS |
| Trap 1: handler loyalty fallback | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 2: enricher prefix search | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 3: enricher re-prefix for lookup | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 4: normalizer adds canonical_id | PASS | PASS | PASS | FAIL | FAIL | FAIL |

Note: Trap 4 is the hardest to catch — it only fails on cross-path consistency and chain-integrity. This is the Trap 5 archetype (partial upstream fix).

---

## 9. Case 2: `derived_billing_chain` (Difficulty C)

### 9.1 Scenario

A SaaS billing system processes usage events through a 4-stage pipeline. The `collector` aggregates raw events into usage records. The `plan_resolver` maps usage to plan features. The `rate_engine` computes charges based on resolved features. The `invoice_builder` assembles the final invoice. A separate `usage_dashboard` reads the collector's output directly for real-time display.

### 9.2 File Layout

```
collector.py        — aggregates raw usage events into usage records
plan_resolver.py    — resolves usage records against plan definitions
rate_engine.py      — computes charges from resolved features
invoice_builder.py  — assembles final invoice from rated items
```

### 9.3 Chain

```
A: collector.aggregate_usage(events)
   → BUG: groups by calendar day using event["timestamp"][:10] (date portion only)
   → but billing periods are 00:00 UTC to 00:00 UTC, and timestamps are in LOCAL time
   → events near midnight are assigned to wrong billing day
   → produces: {"period": "2026-04-01", "units": 85}  (should be 100 — 15 events misassigned to adjacent day)

B: plan_resolver.resolve(usage_record)
   → maps units to plan tier: 0-50 = "starter", 51-100 = "growth", 101+ = "enterprise"
   → 85 units → "growth" tier (correct tier would be "enterprise" at 100 units)
   → produces: {"tier": "growth", "unit_rate": 0.10, "units": 85}

C: rate_engine.compute_charges(resolved)
   → charges = units * unit_rate = 85 * 0.10 = $8.50
   → should be: 100 * 0.05 = $5.00 (enterprise rate is cheaper per unit)
   → produces: {"subtotal": 8.50, "tier": "growth"}

D: invoice_builder.build_invoice(charges)
   → renders invoice with wrong subtotal and wrong tier
   → symptom: customer is overcharged AND shown wrong tier
```

### 9.4 Bug Location

`collector.py`: `aggregate_usage()` uses naive date extraction (`timestamp[:10]`) instead of converting to UTC first, then extracting the billing-period date. Events near midnight local time are assigned to the wrong period.

### 9.5 Root Fix (Node A)

In `collector.py`, convert timestamps to UTC before grouping:

```python
def aggregate_usage(events, tz_offset_hours=0):
    by_period = {}
    for event in events:
        utc_ts = to_utc(event["timestamp"], tz_offset_hours)
        period = utc_ts[:10]  # FIX: use UTC date, not local date
        by_period.setdefault(period, 0)
        by_period[period] += event["units"]
    return [{"period": p, "units": u} for p, u in by_period.items()]
```

### 9.6 Trap Fixes

**Trap 1 — Endpoint compensation (D):**
In `invoice_builder.py`, add a "billing adjustment" that caps charges at the enterprise rate when units exceed 80. Partially works: reduces overcharge for this specific case. Fails for periods with legitimately low usage (the cap incorrectly downgrades their charges).

**Trap 2 — Recomputation at rate engine (C):**
In `rate_engine.py`, re-count units from raw events instead of using the usage record's `units` field. Partially works for the primary billing period. Fails because the rate engine now has a different unit count than the plan resolver's tier assignment — the tier is still "growth" but the charge is computed on 100 units at the growth rate ($10.00), which is even more wrong.

**Trap 3 — Validation masking at plan resolver (B):**
In `plan_resolver.py`, add a 10% tolerance: if units are within 10% of a tier boundary, bump to the higher tier. Partially works for the primary case (85 is within 15% of 100 → bump to enterprise). Fails for users at 55 units who get incorrectly bumped from starter to growth.

**Trap 4 — Partial upstream fix (A→B boundary):**
In `collector.py`, add a "midnight correction" that adds +1 hour to all timestamps before grouping (a hack for a specific timezone). Works for UTC-1 users. Fails for UTC+5 users where the offset shifts events the wrong direction. Also, the underlying grouping logic is still wrong — it just happens to produce correct results for one timezone.

### 9.7 Second Consumer Path (Cross-Path Invariant)

```python
# In collector.py:
def get_usage_summary(events):
    """Real-time usage display — reads directly from collector output."""
    records = aggregate_usage(events)
    return {r["period"]: r["units"] for r in records}
```

The usage dashboard calls `get_usage_summary()` directly. If traps 1-3 fix the invoice but the collector still misgroups events, the dashboard shows wrong per-day usage. Customer sees corrected invoice but dashboard shows different numbers → inconsistency complaint.

### 9.8 Invariants

**Trap-catching:** Run with events where NO events are near midnight. The endpoint compensation (Trap 1) still applies the cap, reducing charges for a period that was correctly billed → overcharge becomes undercharge.

**Generalization:** Run with events from UTC+5 timezone. The midnight correction hack (Trap 4) shifts events the wrong way, producing a different miscount than the original bug.

**Causal-location:** Verify `collector.aggregate_usage()` output directly: total units across all periods must equal sum of input event units. If any fix is downstream of the collector, the collector output still has the wrong totals.

**Cross-path consistency:** `invoice_builder.build_invoice()` total units must equal `get_usage_summary()` total for the same period. If invoice is fixed via rate engine or plan resolver but collector is still broken, the dashboard shows different numbers.

**Chain-integrity:** For each node, verify output independently:
- Collector: total units = sum of input events (no loss, no double-count)
- Plan resolver: tier matches unit-count according to tier table
- Rate engine: charge = units × rate for assigned tier
- Invoice builder: subtotal matches rate engine output

### 9.9 Validation Matrix

| Variant | Trap-catch | Generalization | Causal-loc | Cross-path | Chain-integrity | Overall |
|---|---|---|---|---|---|---|
| No-op (buggy) | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| Root fix (UTC conversion) | PASS | PASS | PASS | PASS | PASS | PASS |
| Trap 1: invoice cap | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 2: rate engine recount | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 3: plan resolver tolerance | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| Trap 4: midnight hour hack | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |

---

## 10. Summary

| Property | Case 1: `request_context_chain` | Case 2: `derived_billing_chain` |
|---|---|---|
| Difficulty | B | C |
| Files | 4 | 4 |
| Chain hops | 4 (A→B→C→D) | 4 (A→B→C→D) |
| Intermediate attractors | 3 (enricher prefix, enricher re-prefix, normalizer canonical_id) | 3 (rate recount, plan tolerance, midnight hack) |
| Trap 5 present | Yes (normalizer canonical_id) | Yes (midnight hour hack) |
| Cross-path consumer | Audit log | Usage dashboard |
| Root cause | Normalizer strips ID prefix | Collector groups by local date not UTC |
| What makes C harder | — | Timezone arithmetic, tier-boundary interaction, charge cascades |
| Real transformation at each node | Parse→Normalize→Enrich→Handle | Aggregate→Resolve→Rate→Invoice |
