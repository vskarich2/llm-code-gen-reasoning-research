# `deep_dependency_chain` — Family Specification v7

**Date:** 2026-04-03
**Supersedes:** deep_dependency_chain_family_design_v6.md

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

Patch node strictly downstream of corruption to normalize corrupt value before forwarding.

**Classification rule:** A fix is Trap 4 iff:
- Modification occurs strictly downstream of the corruption node (corruption node's code is unmodified)
- AND canonical field at the corruption node is unchanged
- AND the main chain appears repaired while the bypass consumer still reads the corrupt canonical field

A patch applied at the corruption node that leaves the canonical field wrong for some input classes is NOT a downstream override. It is a near-root incorrect fix and is classified by invariant failure, typically Generalization, unless it introduces an alternate representation (Trap 5).

- **Attractive because:** Closest non-root fix. Appears to address the source.
- **Fails because:** Canonical field still corrupt at corruption node. Bypass consumer reads it directly.

### Trap 5: Partial Upstream Fix (Depth B/A-adjacent) — FAMILY-DISTINGUISHING

Fix a derived representation instead of the canonical field. Model traces to the corruption node but introduces an alternate representation while leaving the canonical field corrupt.

**Classification rule:** A fix is Trap 5 iff:
- Modification occurs at OR above the corruption node
- AND canonical field is NOT mutated to produce correct values
- AND alternate representation is introduced (new field, conditional logic path, or parallel structure)

- **Attractive because:** IS at the right node. Adds correct data. Looks like careful migration.
- **Fails because:** Canonical field remains corrupt. Bypass consumer reads canonical, not alternate.

### Near-Root Incorrect Fix (Not a Numbered Trap)

A patch at the corruption node that attempts to fix the canonical field but does so incorrectly (e.g., works for one input class but not others, uses a hack instead of a general solution). This is NOT Trap 4 (which must be downstream) and NOT Trap 5 (which introduces an alternate representation). It is classified by whichever invariant it fails, typically Generalization.

### Trap Minimality Rule

For each trap: remove it and re-evaluate. If failure distribution unchanged → redundant → delete.

---

## 5. Invariants

### 5.1 Invariant Names (Fixed Across All Cases)

Every `deep_dependency_chain` case uses exactly these five invariants:

1. Trap-catching
2. Generalization
3. Causal-location
4. Cross-path consistency
5. Chain-integrity

No sub-invariants. No case-level renaming. No splitting. Multiple test inputs under one invariant are test instances, not separate invariants.

### 5.2 Attribution Precedence Rule

Primary attribution is based on discriminative specificity, not execution order.

When a patch fails multiple invariants, PRIMARY is the invariant with the narrowest discriminative scope for that patch's failure mode:

1. **Cross-path consistency** — most specific for failures where the main chain appears repaired but the bypass consumer observes different (corrupt) values from the canonical field. PRIMARY requires actual disagreement between consumer paths. If both paths are wrong together (same corrupt canonical field, same wrong output), Cross-path does not fire as PRIMARY — both paths agree on the wrong answer.
2. **Chain-integrity** — most specific for inter-node inconsistency. PRIMARY when one node's output contradicts another node's output within the chain.
3. **Generalization** — most specific for input-class or input-value brittleness. PRIMARY when the patch works for one input but fails for a different input class or value range.
4. **Trap-catching** — most specific for endpoint-only symptom patching. PRIMARY when a second input defeats endpoint compensation.
5. **Causal-location** — broad diagnostic. Confirms corruption node's canonical field is still wrong. NEVER primary if any of Cross-path, Chain-integrity, Generalization, or Trap-catching also fails for the same patch.

**Cross-path fires as PRIMARY only when the two consumer paths produce different results.** If a patch leaves the canonical field wrong and both consumer paths read the same wrong canonical field, they agree (both wrong). That is not a Cross-path failure — it is a Generalization or Causal-location failure.

### 5.3 Test-Instance vs Invariant-Level Attribution

- **Invariant-level:** "This patch fails the Generalization invariant."
- **Test-instance evidence:** "Specifically, it fails on test input 2 (UTC+5 events)."

Metrics aggregate at invariant level. Debugging uses test-instance evidence.

### 5.4 Invariant Definitions

**Trap-catching**
- **Falsification condition:** Execute chain with a second input where endpoint compensation does not apply. Passes iff endpoint produces correct output for second input.
- **Rejects:** Trap 1 (PRIMARY).

**Generalization**
- **Falsification condition:** Fails iff there exists at least one alternate input class or value under which the patch produces incorrect output through the main chain. May use multiple test inputs. Primary attribution recorded at test-instance level.
- **Rejects:** Trap 3 (PRIMARY). Near-root incorrect fixes (PRIMARY).

**Causal-location**
- **Falsification condition:** Call corruption node's function, assert `output[canonical_field_name]` matches `canonical_schema` exactly. Passes iff canonical field is correct.
- **Rejects:** All non-root fixes (secondary). Never PRIMARY.

**Cross-path consistency**
- **Falsification condition:** Execute primary chain path and bypass consumer path. Passes iff they produce consistent results derived from the canonical field. Fires as PRIMARY only when the two paths disagree — one appears correct, the other shows corrupt canonical data.
- **Bypass consumer requirements:** reads canonical field directly; calls no main-chain functions; references no alternate fields; shares no transformation logic with main chain. If bypass shares logic → case invalid.
- **Rejects:** Trap 4 (PRIMARY — downstream override repairs main chain, bypass still reads corrupt canonical). Trap 5 (PRIMARY — alternate field feeds main chain, bypass reads corrupt canonical field).

**Chain-integrity**
- **Falsification condition:** Call helpers exposing intermediate state at each node. Passes iff every node's output is consistent and correct.
- **Rejects:** Trap 2 (PRIMARY — recomputation creates inter-node inconsistency).

### 5.5 Invariant × Trap Matrix

| | Trap 1 (endpoint) | Trap 2 (recompute) | Trap 3 (masking) | Trap 4 (downstream override) | Trap 5 (partial upstream) | Near-root incorrect fix |
|---|---|---|---|---|---|---|
| **Trap-catching** | **PRIMARY** | secondary | secondary | secondary | pass | secondary |
| **Generalization** | secondary | secondary | **PRIMARY** | secondary | pass | **PRIMARY** |
| **Causal-location** | secondary | secondary | secondary | secondary | secondary | secondary |
| **Cross-path** | secondary | secondary | secondary | **PRIMARY** | **PRIMARY** | secondary |
| **Chain-integrity** | secondary | **PRIMARY** | secondary | secondary | pass or secondary | secondary |

Rules:
- Every numbered trap has exactly one PRIMARY.
- Causal-location is never PRIMARY.
- Cross-path is PRIMARY only for Trap 4 and Trap 5 — patches where the main chain appears repaired but the bypass consumer reads the corrupt canonical field (path disagreement).
- Near-root incorrect fixes (at corruption node, canonical field still wrong for some inputs, no alternate representation) are PRIMARY on Generalization.
- Trap 4 must be strictly downstream. If a patch modifies the corruption node, it is not Trap 4.

---

## 6. Depth Metric

### Semantic Fix Classification

| Depth | Label | Definition |
|---|---|---|
| A | `root_fix` | Canonical field(s) corrected in-place at corruption node. No downstream compensation. ALL five invariants pass when applied alone. |
| B | `proximal_derived_fix` | Modification at or adjacent to corruption node. Canonical field NOT corrected. Alternate representation introduced OR downstream normalization. At least one invariant fails. |
| C | `distal_intermediate_fix` | Modification at intermediate node 2+ hops from corruption. Canonical and proximal representations unchanged. |
| D | `endpoint_compensation` | Modification only at terminal consumer. All upstream unchanged. |
| mixed | `multi_level_fix` | Edits at multiple chain levels without clean dominance. |
| — | `unrelated` | No meaningful causal correction. |

### Classification Procedure

1. Identify all functions/files modified.
2. Map each modification to a chain node.
3. **Root-fix test:** Does the corruption-node modification, applied alone, pass ALL five invariants? Yes → A. No → continue.
4. **Dominance test:** Single modification that alone passes primary test? Yes → classify by position (B/C/D). No → mixed.
5. No chain-node modification → unrelated.

A fix is A ONLY IF all five invariants pass when applied alone.

---

## 7. Validation Criteria

### Hard Requirements

1. ≥2 distinct non-root fixes plausible: each passes primary test, fails ≥1 invariant.
2. ≥1 upstream-near-root trap (Trap 4 or 5) fails ONLY on Cross-path (passes Trap-catching, Generalization, Chain-integrity).
3. Root fix uniquely passes all five invariants.
4. Root fix satisfies path-independence.
5. Bypass consumer: reads canonical field directly, no main-chain functions, no alternate fields, no shared transformation logic.
6. Baseline pass rate 5%-80%.
7. ≥2 calibration models (one weak, one mid) each produce non-root fix passing primary test and failing ≥1 invariant.
8. Upstream-visibility enforcement: annotate corruption site, re-evaluate traps. If any collapse → case invalid.

### Calibration Targets

- Weaker models → D or unrelated.
- Mid-tier → C or B.
- Stronger → A.
- ≥2 depth levels represented.

---

## 8. Case-Construction Checklist

1. Define canonical shared representation (field names, schema, storage, ALL access paths).
2. Define corruption site and bug.
3. Enumerate downstream transforms.
4. Enumerate consumers. ≥1 bypass consumer with NO shared transformation logic.
5. ≥3 incorrect plausible fixes.
6. Show primary test each fix passes.
7. Show invariant each fix fails (map to matrix; one PRIMARY per fix via precedence rule).
8. Show root fix passes all 5.
9. Boundary audit: graph-reveal, upstream-visibility, path-independence.
10. Predict depth gradient per tier.
11. Minimality: remove each node; if phenomenon persists → delete node.
12. Trap minimality: remove each trap; if distribution unchanged → delete trap.
13. Upstream-visibility enforcement: annotate, re-evaluate.
14. Attribution check: one PRIMARY per fix via precedence.

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
| `canonical_schema` | `str` matching `[A-Z]+-\d+` |
| `canonical_storage_location` | Normalized request dict from `normalizer.normalize()` |
| `canonical_access_paths` | (1) enricher reads `user_id`; (2) handler reads `user_id`; (3) `normalizer.get_normalized_for_audit()` reads `user_id` (BYPASS) |

**Rigidity:** `get_normalized_for_audit()` reads ONLY `user_id`. Ignores alternate fields.

**Bypass independence:** Reads normalized dict's `user_id` directly. Calls no enricher/handler/parser functions. No shared transformation logic.

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
```

### 9.4 Bug

`normalizer.normalize()` strips `"USR-"` prefix from `user_id`.

### 9.5 Root Fix

`result["user_id"] = parsed["user_id"]`

All 5 invariants pass. Path-independent.

### 9.6 Traps

**Trap 1 — Endpoint compensation (D):** `handler.handle()` adds loyalty discount if `tier == "basic"` and amount > 100.
- Passes primary test.
- **PRIMARY: Trap-catching.** Second user `"USR-00099"` IS basic → loyalty discount incorrectly applied.

**Trap 3 — Validation masking (C):** `enricher.enrich()` tries `user_db.get("USR-" + user_id)` on failure.
- Passes primary test.
- **PRIMARY: Generalization.** User `"ADMIN-001"` → `"USR-ADMIN-001"` → not found.

**Trap 4 — Downstream override (B):** `enricher.enrich()` re-prefixes and stores `enriched["user_id"] = "USR-" + normalized["user_id"]`. Enricher code is modified; normalizer code is NOT modified.
- Passes primary test. Main chain produces correct `user_id` in enriched dict.
- **PRIMARY: Cross-path.** `get_normalized_for_audit()` reads normalizer output → `"00042"`. Handler response (via enricher) → `"USR-00042"`. Paths disagree. This is genuine Cross-path: one path sees repaired data (main chain through enricher), one path sees corrupt canonical field (bypass reads normalizer output directly).

**Trap 5 — Partial upstream fix (B):** `normalizer.normalize()` adds `canonical_id`, still strips `user_id`.
- Passes primary test (if enricher reads `canonical_id`).
- **PRIMARY: Cross-path.** `get_normalized_for_audit()` reads `user_id` → `"00042"`. Handler (via enricher using `canonical_id`) → `"USR-00042"`. Paths disagree.

### 9.7 Invariant × Trap Verification

| Invariant | Trap 1 | Trap 3 | Trap 4 | Trap 5 | Root |
|---|---|---|---|---|---|
| Trap-catching | **PRIMARY: FAIL** | pass | pass | pass | PASS |
| Generalization | secondary: fail | **PRIMARY: FAIL** | secondary: fail | pass | PASS |
| Causal-location | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |
| Cross-path | secondary: fail | secondary: fail | **PRIMARY: FAIL** | **PRIMARY: FAIL** | PASS |
| Chain-integrity | secondary: fail | secondary: fail | pass | secondary: fail | PASS |

Every trap: one PRIMARY. Causal-location: never PRIMARY. Root fix: unique.

Cross-path is correctly PRIMARY for Trap 4: the enricher repairs the main-chain data, but the bypass consumer reads the normalizer's output directly and sees the corrupt canonical field. The two paths disagree.

### 9.8 Boundary Audit

- **Graph-reveal:** PASS. Traps remain attractive with full graph.
- **Upstream-visibility:** PASS. Trap 5 remains attractive as migration.
- **Path-independence:** PASS. Root fix corrects all paths without branching.

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
| `canonical_schema` | `int`, exact count of events in UTC billing period |
| `canonical_storage_location` | Usage record dicts from `collector.aggregate_usage()` |
| `canonical_access_paths` | (1) plan_resolver reads `units`; (2) rate_engine reads `units`; (3) `collector.get_usage_summary()` reads `units` (BYPASS) |

**Rigidity:** `get_usage_summary()` reads ONLY `units`. Ignores `corrected_units`.

**Bypass independence:** Calls `aggregate_usage()` and reads `units`. No plan_resolver/rate_engine/invoice_builder calls. No shared transformation logic.

### 10.3 Chain

```
collector.aggregate_usage(events, tz_offset_hours)   ← CORRUPTION + SOURCE
  BUG: groups by local date, not UTC
  → [{"period": "2026-04-01", "units": 85}]   (should be 100)

  ├─▶ collector.get_usage_summary(events)   ← BYPASS: returns {"2026-04-01": 85}

plan_resolver.resolve(usage_record)                  ← FIRST SYMPTOM
  tiers: 0-50 starter ($0.20), 51-100 growth ($0.10), 101+ enterprise ($0.05)
  85 → growth/$0.10   (should be 100 → enterprise/$0.05)

rate_engine.compute_charges(resolved)
  85 × $0.10 = $8.50   (should be 100 × $0.05 = $5.00)

invoice_builder.build_invoice(charges)               ← TERMINAL
```

### 10.4 Bug

`collector.aggregate_usage()` groups by `event["timestamp"][:10]` (local date). With `tz_offset=-1`, 15 events misassigned. April 1 gets 85 instead of 100.

Root fix is independent of pricing/tier mechanics — purely timestamp conversion.

### 10.5 Root Fix

Convert to UTC before date extraction:
```python
utc_ts = to_utc(event["timestamp"], tz_offset_hours)
period = utc_ts[:10]
```

All 5 invariants pass. Path-independent.

### 10.6 Traps

**Trap 1 — Endpoint compensation (D):** `invoice_builder.build_invoice()` applies 41% adjustment when `tier == "growth"` and `subtotal > 8.00`.
- Passes primary test: $8.50 × 0.59 ≈ $5.02.
- **PRIMARY: Trap-catching.** Legitimate 85-unit growth user (no timezone issue). Should pay $8.50. Adjustment wrongly reduces to $5.02.

**Trap 3 — Validation masking (B):** `plan_resolver.resolve()` adds tolerance: if `units >= tier_boundary × 0.80`, bump to higher tier. Enterprise boundary = 101, threshold = 80.8. Since 85 ≥ 81 → enterprise.
- Passes primary test: enterprise at $0.05, 85 × $0.05 = $4.25.
- **PRIMARY: Generalization.** Test instance: user with 42 units. Growth boundary = 51, threshold = 40.8. Since 42 ≥ 41 → bumped starter→growth. Bill $4.20 instead of correct $8.40.

**Trap 2 — Intermediate recomputation (C):** `rate_engine.compute_charges()` re-aggregates from raw events instead of using resolved `units`.
- Passes primary test: recomputed 100 units. But tier = growth (plan_resolver used 85). Charge = 100 × $0.10 = $10.00.
- **PRIMARY: Chain-integrity.** Resolved record: 85 units/growth. Rate engine charges for 100 units at growth rate. Internal inconsistency.

**Trap 4 — Downstream override (B):** `plan_resolver.resolve()` adds a pre-processing step that re-aggregates units from raw events (passed as extra context) before tier assignment, while leaving `collector.aggregate_usage()` unmodified.
- Passes primary test: plan_resolver sees 100 units → enterprise → $0.05. Rate engine uses resolved record with 100 units. Invoice correct.
- Main chain is repaired. Collector code is unmodified. Canonical `units` field in collector output is still 85.
- **PRIMARY: Cross-path.** `get_usage_summary()` returns `{"2026-04-01": 85}`. Invoice says 100/enterprise/$5.00. Dashboard and invoice disagree. This is genuine Cross-path: main chain (through plan_resolver's re-aggregation) shows 100, bypass consumer (reading collector's canonical `units`) shows 85.

**Near-root incorrect fix (at collector, not a numbered trap):** `collector.aggregate_usage()` adds +1 hour to all timestamps before grouping.
- Passes primary test for `tz_offset=-1`: adding 1h converts to UTC.
- Fails for `tz_offset=+5`: +1h shifts wrong direction.
- This is at the corruption node. It modifies `collector.py`. It does NOT introduce an alternate representation (no new field). It attempts to fix the canonical field but does so incorrectly for some inputs.
- **PRIMARY: Generalization.** Test instance: UTC+5 events. The +1h hack produces wrong counts for +5.
- This is NOT Trap 4 (not downstream — it modifies the corruption node). NOT Trap 5 (no alternate representation). It is a near-root incorrect fix, classified by Generalization.

**Trap 5 — Partial upstream fix (A, derived):** `collector.aggregate_usage()` adds `corrected_units` alongside `units`:
```python
record["units"] = local_count           # still 85
record["corrected_units"] = utc_count   # 100
```
- Passes primary test (if plan_resolver reads `corrected_units`).
- **PRIMARY: Cross-path.** `get_usage_summary()` returns `units: 85`. Invoice (via corrected chain) says 100/enterprise/$5.00. Dashboard says 85. Paths disagree.

### 10.7 Invariant × Trap Verification

| Invariant | Trap 1 (invoice) | Trap 2 (rate recount) | Trap 3 (resolver tolerance) | Trap 4 (resolver re-aggregate) | Near-root (+1h hack) | Trap 5 (corrected_units) | Root |
|---|---|---|---|---|---|---|---|
| Trap-catching | **PRIMARY: FAIL** | pass | pass | pass | pass | pass | PASS |
| Generalization | secondary: fail | secondary: fail | **PRIMARY: FAIL** | secondary: fail | **PRIMARY: FAIL** | pass | PASS |
| Causal-location | secondary: fail | secondary: fail | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |
| Cross-path | secondary: fail | secondary: fail | secondary: fail | **PRIMARY: FAIL** | secondary: fail | **PRIMARY: FAIL** | PASS |
| Chain-integrity | secondary: fail | **PRIMARY: FAIL** | secondary: fail | secondary: fail | secondary: fail | secondary: fail | PASS |

Every trap and near-root fix: exactly one PRIMARY. Causal-location: never PRIMARY. Root fix: unique.

Cross-path is correctly PRIMARY for Trap 4: plan_resolver's re-aggregation repairs the main chain, but the bypass consumer reads the collector's canonical `units` field directly (still 85). The paths disagree (main chain → 100, bypass → 85).

Cross-path is correctly PRIMARY for Trap 5: corrected_units feeds the main chain, but bypass reads `units`. Paths disagree.

Generalization is correctly PRIMARY for the near-root +1h hack: both paths see the same wrong `units` for UTC+5 (no disagreement between paths — both wrong together). This is input brittleness, not path inconsistency.

Generalization test instances for Case 2:
- Instance 1 (42-unit user): exposes Trap 3 (tolerance too aggressive)
- Instance 2 (UTC+5 events): exposes near-root +1h hack (wrong direction)

### 10.8 Boundary Audit

- **Graph-reveal:** PASS. Traps remain attractive with full graph.
- **Upstream-visibility:** PASS. Near-root hack and Trap 5 remain attractive even when corruption is annotated.
- **Path-independence:** PASS. Root fix corrects `units` for all consumers without branching.
- **Minimality:** Removing plan_resolver eliminates Trap 3, Trap 4, and tier interaction. Removing rate_engine eliminates Trap 2 and chain-integrity target. Both load-bearing.

### 10.9 Predicted Depth Gradient

- **Weak (nano):** D (invoice adjustment) or unrelated.
- **Mid (4omini):** C (resolver tolerance) or B (rate recount).
- **Strong-mid (5mini):** Near-root (+1h hack at collector) or B (Trap 4 resolver re-aggregate).
- **Strong (54mini, gpt5):** A (UTC conversion).

### 10.10 What Makes This C-Level

- 4 files, 4 transformation hops.
- Timezone arithmetic adds genuine computational difficulty.
- Tier-boundary interaction amplifies the error non-linearly.
- Near-root hack IS in the correct file and IS a timezone fix — but it is a constant-offset hack, not a general conversion.
- Trap 4 (plan_resolver re-aggregation) is a true downstream override that repairs the main chain — only Cross-path catches it.
- Trap 5 requires understanding that the field name `units` matters — consumers read `units`, not `corrected_units`.
