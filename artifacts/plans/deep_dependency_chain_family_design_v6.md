# `deep_dependency_chain` — Family Specification v6

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v5.md

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

**Upstream-visibility test:** Annotate the corruption site and the canonical field explicitly. Re-evaluate all traps. If traps collapse OR root fix becomes trivial → case is NOT `deep_dependency_chain`. This test must be executed during validation.

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
- Alternate fields introduced by Trap 5 must be ignored by at least one consumer.
- If an alternate field can silently replace the canonical field across ALL consumer paths without any consumer noticing → the case is invalid.

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
| `false_fix_attractor` | Nothing hidden | Nothing — single hop | One dominant symptom-proximal target | One attractor, no gradient |
| `misinferred_dependency` | Which of 2+ competing causes | Fix to correct cause | Wrong cause's site | Multiple root hypotheses; deep_dependency_chain has one cause |
| `intervention_boundary` | Nothing — correct target identified | Complete implementation | Right function, incomplete fix | Model at correct node, fix incomplete; deep_dependency_chain model at wrong node, fix locally complete |
| `abstraction_leak` | Nothing — correct cause identified | Fix at correct layer | Wrong abstraction layer | Vertical confusion; deep_dependency_chain is horizontal chain-position confusion |

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
- **Fails because:** Coercion is input-class-specific. Different input class or value range defeats it.

### Trap 4: Downstream Override (Depth B)

Patch node immediately downstream of corruption to normalize corrupt value before forwarding.

**Classification rule:** A fix is Trap 4 iff:
- Modification occurs strictly downstream of the corruption node (corruption node's code unmodified)
- AND canonical field at corruption node is unchanged

**Edge cases:**
- Field aliasing at downstream node → Trap 4
- Conditional overwrite at downstream node → Trap 4
- Partial overwrite of canonical field at downstream node → Trap 4

- **Attractive because:** Closest non-root fix. Appears to address the source.
- **Fails because:** Canonical field still corrupt at corruption node. Bypass consumer reads it directly.

### Trap 5: Partial Upstream Fix (Depth B/A-adjacent) — FAMILY-DISTINGUISHING

Fix a derived representation instead of the canonical field. Model traces to the corruption node but introduces an alternate representation while leaving the canonical field corrupt.

**Classification rule:** A fix is Trap 5 iff:
- Modification occurs at OR above the corruption node (corruption node's code IS modified)
- AND canonical field is NOT mutated to produce correct values
- AND alternate representation is introduced (new field, conditional logic path, or parallel structure)

**Edge cases:**
- Model adds new field, leaves canonical unchanged → Trap 5
- Model conditionally overwrites canonical for some inputs but not all → Trap 5
- Model partially overwrites canonical (works for primary, wrong for generalization) without introducing alternate → reclassify as incomplete root fix → depth mixed

- **Attractive because:** IS at the right node. Adds correct data. Looks like careful migration.
- **Fails because:** Canonical field remains corrupt. Bypass consumer reads canonical, not alternate.

### Trap Minimality Rule

For each trap: remove it and re-evaluate. If the failure distribution is unchanged, the trap is redundant and must be deleted.

---

## 5. Invariants

### 5.1 Invariant Names (Fixed Across All Cases)

Every `deep_dependency_chain` case uses exactly these five invariants:

1. Trap-catching
2. Generalization
3. Causal-location
4. Cross-path consistency
5. Chain-integrity

No sub-invariants. No case-level renaming. No splitting.

An invariant may use multiple test inputs. These are test instances under one invariant, not separate invariants. Attribution records which test instance triggered the failure, but the invariant-level label is always one of the five above.

### 5.2 Attribution Precedence Rule

Primary attribution is based on discriminative specificity, not execution order or input sequence.

When a patch fails multiple invariants, PRIMARY is assigned to the invariant with the narrowest discriminative scope for that patch's failure mode:

1. **Cross-path consistency** — most specific for alternate-representation and downstream-only repair failures. PRIMARY when the patch repairs the main chain but leaves the canonical field corrupt for the bypass consumer.
2. **Chain-integrity** — most specific for inter-node inconsistency failures. PRIMARY when the patch corrects one node but leaves another node's output inconsistent with the correction.
3. **Generalization** — most specific for input-class or input-value brittleness. PRIMARY when the patch works for one input but fails for a different input class or value range.
4. **Trap-catching** — most specific for endpoint-only symptom patching. PRIMARY when the patch compensates at the terminal consumer and a second input defeats the compensation.
5. **Causal-location** — broad diagnostic check. Confirms the corruption node's canonical field is still wrong. NEVER primary if any of Cross-path, Chain-integrity, Generalization, or Trap-catching also fails for the same patch.

**Hard rule:** Causal-location is a diagnostic invariant, not a discriminative invariant. It must never be PRIMARY if any more specific invariant also fails for the same patch.

### 5.3 Test-Instance vs Invariant-Level Attribution

- **Invariant-level attribution:** "This patch fails the Generalization invariant."
- **Test-instance evidence:** "Specifically, it fails on generalization test input 2 (UTC+5 timezone events)."

Downstream metrics aggregate at the invariant level. Case-level debugging uses test-instance evidence. These are distinct layers.

### 5.4 Invariant Definitions

**Trap-catching**
- **Falsification condition:** Execute chain with a second input where the endpoint compensation does not apply. Passes iff endpoint produces correct output for the second input without compensation logic activating.
- **Rejects:** Trap 1 (PRIMARY).
- **Scope:** Endpoint behavior under alternate input.

**Generalization**
- **Falsification condition:** The invariant fails iff there exists at least one alternate input class or alternate input value under which the patch produces incorrect output through the main chain.
- A case may define multiple generalization test inputs. These are test instances under one invariant. Primary attribution within Generalization is recorded at the test-instance level, not by splitting the invariant.
- **Rejects:** Trap 3 (PRIMARY), Trap 4 (PRIMARY when no more specific invariant applies). Different traps fail on different test instances within the same invariant.
- **Scope:** Input-class and input-value coverage at intermediate and near-root nodes.
- **Disambiguation when two traps both fail Generalization:** Each trap fails on a different test instance. The invariant is the same; the evidence differs. Both are attributed to Generalization at the invariant level. At the test-instance level, the record specifies which input exposed which trap.

**Causal-location**
- **Falsification condition:** Directly call the corruption node's function and assert that `output[canonical_field_name]` matches `canonical_schema` exactly for the test input. Passes iff the canonical field is correct.
- **Rejects:** All non-root fixes (secondary). Never PRIMARY — always a broader diagnostic. If a patch fails causal-location AND any of Cross-path, Chain-integrity, Generalization, or Trap-catching, the more specific invariant is PRIMARY.
- **Scope:** Corruption node canonical field correctness.

**Cross-path consistency**
- **Falsification condition:** Execute both the primary chain path and the bypass consumer path. Passes iff they produce consistent results derived from the same canonical field.
- **Bypass consumer structural requirements:**
  - Must read canonical field directly
  - Must NOT call any main-chain transformation function
  - Must NOT reference alternate or derived fields
  - Must be code-path independent (no shared transformation logic with main chain)
  - If bypass shares transformation logic with main chain → case is invalid
- **Rejects:** Trap 4 (PRIMARY), Trap 5 (PRIMARY).
- **Scope:** Canonical field consistency across independent consumer paths.

**Chain-integrity**
- **Falsification condition:** Call helper functions exposing intermediate state at each chain node. Passes iff every node's output is internally consistent and correct.
- **Rejects:** Trap 2 (PRIMARY).
- **Scope:** Inter-node consistency across the transformation chain.

### 5.5 Invariant × Trap Matrix

| | Trap 1 (endpoint) | Trap 2 (recompute) | Trap 3 (masking) | Trap 4 (override) | Trap 5 (partial upstream) |
|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | secondary | secondary | secondary | pass |
| **Generalization** | secondary | secondary | **PRIMARY** | **PRIMARY** | pass |
| **Causal-location** | secondary | secondary | secondary | secondary | secondary |
| **Cross-path** | secondary | secondary | secondary | **PRIMARY** | **PRIMARY** |
| **Chain-integrity** | secondary | **PRIMARY** | secondary | secondary | pass or secondary |

Rules reflected in this matrix:
- Every trap has exactly one PRIMARY invariant.
- Causal-location is never PRIMARY (always secondary when another invariant also fails).
- Trap 4 has two candidates (Generalization, Cross-path). Precedence rule resolves: Cross-path is more specific (tests canonical field across paths) than Generalization (tests input coverage). Cross-path is PRIMARY for Trap 4 when the bypass consumer exposes the failure. Generalization is PRIMARY for Trap 4 only if the bypass consumer is not exercised for that specific test input — but since the cross-path invariant is mandatory for all cases, Cross-path is PRIMARY for Trap 4 in practice.

**Correction to matrix — Trap 4 resolved:**

| | Trap 4 (override) |
|---|---|
| Cross-path | **PRIMARY** |
| Generalization | secondary |

Trap 3 and Trap 4 are now cleanly separated: Trap 3's PRIMARY is Generalization (input brittleness). Trap 4's PRIMARY is Cross-path (bypass consumer sees corrupt canonical field). No collision.

**Final matrix (corrected):**

| | Trap 1 | Trap 2 | Trap 3 | Trap 4 | Trap 5 |
|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | secondary | secondary | secondary | pass |
| **Generalization** | secondary | secondary | **PRIMARY** | secondary | pass |
| **Causal-location** | secondary | secondary | secondary | secondary | secondary |
| **Cross-path** | secondary | secondary | secondary | **PRIMARY** | **PRIMARY** |
| **Chain-integrity** | secondary | **PRIMARY** | secondary | secondary | pass or secondary |

Every trap: exactly one PRIMARY. No invariant is PRIMARY for more than two traps. Causal-location is never PRIMARY.

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
   - Yes → A.
   - No → continue.
4. **Dominance test:** Is there a single modification that, applied alone, passes the primary test (even if some invariants fail)?
   - Yes → classify by that modification's chain position (B/C/D).
   - No single modification suffices → `mixed`.
5. If no modification addresses any chain node → `unrelated`.

A fix is `root_fix` (A) ONLY IF all five invariants pass when it is applied alone. An incorrect root-level edit that fails any invariant is B, C, or mixed — never A.

---

## 7. Validation Criteria

### Hard Requirements (Case Acceptance)

1. At least two distinct non-root fixes must be plausible: each must solve primary symptom, preserve local coherence, look defensible, fail at least one invariant.
2. At least one upstream-near-root trap (Trap 4 or 5) must fail ONLY on Cross-path consistency (passes Trap-catching, Generalization, and Chain-integrity).
3. Root fix must be the unique fix passing all five invariants.
4. Root fix must satisfy path-independence.
5. Bypass consumer must read canonical field directly, call no main-chain functions, reference no alternate fields, share no transformation logic with main chain.
6. Baseline pass rate between 5% and 80% across calibration models.
7. At least TWO calibration models (one weak-tier, one mid-tier) must each produce a non-root fix that passes primary test AND fails at least one invariant.
8. Upstream-visibility enforcement: annotate corruption site and canonical field, re-evaluate traps. If any trap collapses or root fix becomes trivial → case is invalid.

### Calibration Targets

- Weaker models tend toward D or unrelated.
- Mid-tier models tend toward C or B.
- Stronger models tend toward A.
- At least 2 distinct depth levels represented among failures.

---

## 8. Case-Construction Checklist

1. Define canonical shared representation (field names, schema, storage location, ALL access paths).
2. Define corruption site and specific bug.
3. Enumerate all downstream transforms.
4. Enumerate all consumers. At least one bypass consumer reading canonical field directly with NO shared transformation logic.
5. Propose ≥3 incorrect but plausible local fixes.
6. Show primary test each fix passes.
7. Show specific invariant each fix fails (map to matrix; confirm exactly one PRIMARY per fix using precedence rule).
8. Show root fix passes all 5 invariants.
9. Boundary audit: graph-reveal test, upstream-visibility test, path-independence test.
10. Predict depth gradient per model tier.
11. Minimality check: remove each chain node; if phenomenon persists → node unnecessary → delete.
12. Trap minimality check: remove each trap; if distribution unchanged → redundant → delete.
13. Upstream-visibility enforcement: annotate corruption site, re-evaluate traps.
14. Failure attribution check: for every trap, confirm exactly one PRIMARY using precedence rule.

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
| `canonical_access_paths` | (1) enricher → reads `user_id` for DB lookup; (2) handler → reads `user_id` for response; (3) `normalizer.get_normalized_for_audit()` → reads `user_id` for audit (BYPASS) |

**Rigidity:** `get_normalized_for_audit()` reads ONLY `user_id`. It ignores `canonical_id` or any alternate field.

**Bypass independence:** `get_normalized_for_audit()` reads the normalized dict's `user_id` field directly. It calls no enricher, handler, or parser functions. It shares no transformation logic with the main chain.

### 9.3 Chain

```
request_parser.parse_request(raw)
  → {"user_id": "USR-00042", ...}

normalizer.normalize(parsed)                     ← CORRUPTION
  → {"user_id": "00042", ...}

enricher.enrich(normalized)                      ← FIRST SYMPTOM
  → {"user_id": "00042", "tier": "basic", "discount": 0}

handler.handle(enriched)                         ← TERMINAL

normalizer.get_normalized_for_audit()            ← BYPASS
  → reads user_id from normalized dict
```

### 9.4 Bug

`normalizer.normalize()` strips `"USR-"` prefix from `user_id`. The prefix is part of the canonical ID format.

### 9.5 Root Fix

`result["user_id"] = parsed["user_id"]` — preserve canonical ID.

Path-independence: all consumer paths correct without branching. All 5 invariants pass.

### 9.6 Traps

**Trap 1 — Endpoint compensation (D):** `handler.handle()` adds loyalty discount if `tier == "basic"` and amount > 100.
- Passes primary test.
- **PRIMARY: Trap-catching.** Second user `"USR-00099"` IS basic tier → loyalty discount incorrectly applied to genuine basic user.

**Trap 3 — Validation masking (C):** `enricher.enrich()` tries `user_db.get("USR-" + user_id)` on lookup failure.
- Passes primary test.
- **PRIMARY: Generalization.** Test instance: user `"ADMIN-001"` → enricher tries `"USR-ADMIN-001"` → not found → wrong tier.

**Trap 4 — Downstream override (B):** `enricher.enrich()` re-prefixes and stores `enriched["user_id"] = "USR-" + normalized["user_id"]`.
- Passes primary test.
- **PRIMARY: Cross-path.** `get_normalized_for_audit()` returns `user_id: "00042"` (reads normalizer output). Handler response has `"USR-00042"` (enricher re-prefix). Audit and handler disagree.

**Trap 5 — Partial upstream fix (B):** `normalizer.normalize()` adds `canonical_id` preserving original, still strips `user_id`.
- Passes primary test (if enricher reads `canonical_id`).
- **PRIMARY: Cross-path.** `get_normalized_for_audit()` reads `user_id` → `"00042"`. Handler (via enricher using `canonical_id`) shows `"USR-00042"`. Inconsistency.

### 9.7 Invariant × Trap Verification

| Invariant | Trap 1 | Trap 3 | Trap 4 | Trap 5 | Root |
|---|---|---|---|---|---|
| Trap-catching | **PRIMARY: FAIL** | pass | pass | pass | PASS |
| Generalization | secondary: fail | **PRIMARY: FAIL** | secondary: fail | pass | PASS |
| Causal-location | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |
| Cross-path | secondary: fail | secondary: fail | **PRIMARY: FAIL** | **PRIMARY: FAIL** | PASS |
| Chain-integrity | secondary: fail | secondary: fail | pass | secondary: fail | PASS |

Every trap: exactly one PRIMARY. Causal-location: never PRIMARY. Root fix: unique fix passing all 5.

### 9.8 Boundary Audit

- **Graph-reveal:** Chain visible from imports. Traps remain attractive. **PASS.**
- **Upstream-visibility:** Annotating "user_id is canonical, normalizer strips prefix" — Trap 5 remains attractive as migration approach. **PASS.**
- **Path-independence:** Root fix corrects all paths without branching. **PASS.**

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
| `canonical_storage_location` | Usage record dicts from `collector.aggregate_usage()` |
| `canonical_access_paths` | (1) plan_resolver → reads `units`; (2) rate_engine → reads `units` via resolved record; (3) `collector.get_usage_summary()` → reads `units` directly (BYPASS) |

**Rigidity:** `get_usage_summary()` reads ONLY `units`. Ignores `corrected_units` or any alternate.

**Bypass independence:** `get_usage_summary()` calls `aggregate_usage()` and reads `units`. Calls no plan_resolver, rate_engine, or invoice_builder functions. No shared transformation logic.

### 10.3 Chain

```
collector.aggregate_usage(events, tz_offset_hours)   ← CORRUPTION + SOURCE
  BUG: groups by event["timestamp"][:10] (local date, not UTC)
  → [{"period": "2026-04-01", "units": 85}]   (should be 100)

  ├─▶ collector.get_usage_summary(events) → {"2026-04-01": 85}   ← BYPASS

plan_resolver.resolve(usage_record)                  ← FIRST SYMPTOM
  tiers: 0-50 starter ($0.20), 51-100 growth ($0.10), 101+ enterprise ($0.05)
  85 → growth/$0.10   (should be 100 → enterprise/$0.05)

rate_engine.compute_charges(resolved)
  85 × $0.10 = $8.50   (should be 100 × $0.05 = $5.00)

invoice_builder.build_invoice(charges)               ← TERMINAL
```

### 10.4 Bug

`collector.aggregate_usage()` groups by local-time date (`event["timestamp"][:10]`). With `tz_offset_hours=-1`, 15 events have local timestamps on April 1 but UTC timestamps on March 31. April 1 period gets 85 instead of 100.

The root fix is independent of pricing/tier mechanics. It is purely about timestamp conversion.

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

Path-independence: corrects `units` for all consumers without branching. All 5 invariants pass.

### 10.6 Traps

**Trap 1 — Endpoint compensation (D):** `invoice_builder.build_invoice()` applies 41% adjustment when `tier == "growth"` and `subtotal > 8.00`.
- Passes primary test: $8.50 × 0.59 ≈ $5.02.
- **PRIMARY: Trap-catching.** Test instance: legitimate 85-unit growth user (no timezone issue, correct billing). Should pay $8.50. Adjustment wrongly reduces to $5.02.

**Trap 3 — Validation masking (B):** `plan_resolver.resolve()` adds tolerance: if `units >= tier_boundary × 0.80`, bump to higher tier. Enterprise boundary = 101, threshold = 80.8. Since 85 ≥ 81 → bump to enterprise.
- Passes primary test: enterprise at $0.05, 85 × $0.05 = $4.25.
- **PRIMARY: Generalization.** Test instance: user with 42 units. Growth boundary = 51, threshold = 40.8. Since 42 ≥ 41 → bumped from starter ($0.20) to growth ($0.10). Bill: $4.20 instead of correct $8.40. A legitimate starter user is undercharged by 50%.

**Trap 2 — Intermediate recomputation (C):** `rate_engine.compute_charges()` re-aggregates units from raw events instead of using resolved record's `units`.
- Passes primary test: recomputed 100 units. But tier is still "growth" (plan_resolver used 85 units). Charge = 100 × $0.10 = $10.00.
- **PRIMARY: Chain-integrity.** Plan resolver output: {units: 85, tier: growth}. Rate engine uses 100 units at growth rate. The resolved record says 85 but charges are computed on 100 — internal inconsistency.

**Trap 4 — Timezone hack (A-wrong):** `collector.aggregate_usage()` adds +1 hour to all timestamps before grouping.
- Passes primary test: for `tz_offset=-1`, adding 1 hour converts to UTC. Correct 100 units.
- **PRIMARY: Cross-path.** Test instance: events with `tz_offset=+5`. Adding 1 hour shifts further from UTC. `get_usage_summary()` returns wrong units for +5 events. Dashboard and invoice disagree. (This also constitutes a Generalization failure on a different test instance, but Cross-path is more specific per the precedence rule because it detects inconsistency between consumer paths, not just input brittleness.)

**Trap 5 — Partial upstream fix (A, derived):** `collector.aggregate_usage()` adds `corrected_units` alongside `units`:
```python
record["units"] = local_count           # still 85
record["corrected_units"] = utc_count   # 100
```
- Passes primary test (if plan_resolver reads `corrected_units`).
- **PRIMARY: Cross-path.** `get_usage_summary()` returns `units: 85`. Invoice (via corrected chain) says 100 / enterprise / $5.00. Dashboard says 85. Inconsistency.

### 10.7 Invariant × Trap Verification

| Invariant | Trap 1 (invoice) | Trap 2 (rate recount) | Trap 3 (resolver tolerance) | Trap 4 (tz hack) | Trap 5 (corrected_units) | Root |
|---|---|---|---|---|---|---|
| Trap-catching | **PRIMARY: FAIL** | pass | pass | pass | pass | PASS |
| Generalization | secondary: fail | secondary: fail | **PRIMARY: FAIL** | secondary: fail | pass | PASS |
| Causal-location | secondary: fail | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |
| Cross-path | secondary: fail | secondary: fail | secondary: fail | **PRIMARY: FAIL** | **PRIMARY: FAIL** | PASS |
| Chain-integrity | secondary: fail | **PRIMARY: FAIL** | secondary: fail | secondary: fail | secondary: fail | PASS |

Every trap: exactly one PRIMARY. Causal-location: never PRIMARY. Root fix: unique fix passing all 5.

Generalization test instances for Case 2:
- Test instance 1 (42-unit user): exposes Trap 3 (tolerance too aggressive for small counts)
- Test instance 2 (UTC+5 events): exposes Trap 4 (offset hack wrong direction)
- Both are instances of the Generalization invariant. Trap 3's PRIMARY is Generalization (on instance 1). Trap 4's PRIMARY is Cross-path (more specific per precedence rule; the UTC+5 failure manifests as path inconsistency, not just input brittleness). No collision.

### 10.8 Boundary Audit

- **Graph-reveal:** Chain explicit. Timezone hack and corrected_units remain attractive with full graph knowledge. **PASS.**
- **Upstream-visibility:** Annotating "units is canonical, collector corrupts via local-time grouping" — Trap 4 remains attractive (IS a timezone fix, just not general). Trap 5 remains attractive (migration approach). **PASS.**
- **Path-independence:** Root fix (UTC conversion) corrects `units` for all consumers without branching. **PASS.**
- **Minimality:** Removing plan_resolver eliminates Trap 3 and tier-boundary interaction. Removing rate_engine eliminates Trap 2 and chain-integrity target. Both load-bearing.

### 10.9 Predicted Depth Gradient

- **Weak (nano):** D (invoice adjustment) or unrelated.
- **Mid (4omini):** C (resolver tolerance) or B (rate recount).
- **Strong-mid (5mini):** B/A-wrong (timezone hack at collector, constant offset).
- **Strong (54mini, gpt5):** A (UTC conversion).
