# Invariant Test System Overhaul -- Plan v4

**Task type**: FEATURE (measurement architecture redesign)
**Date**: 2026-03-30
**Status**: AWAITING APPROVAL
**Revision**: v4 -- targeted fixes to v3 addressing 5 remaining gaps

---

## Changes from v3

v3 was assessed as near-research-grade with 5 specific remaining gaps. v4 addresses each. Only changed/new sections are written in full below. All other sections from v2/v3 are unchanged and incorporated by reference.

### Modifications
- **Section 3.7.4**: NECESSITY made explicitly conditional with trigger coverage proof requirement (Req 1)
- **Section 3.7 addendum (3.7.6)**: NECESSITY conditional downgrade rule added (Req 1)
- **Section 3.4 addendum (3.4.2)**: BCMV split into 5 subtypes (Req 2)
- **Section 7.1**: MeasurementVerdict updated with `bcmv_subtype` field (Req 2)
- **Section 7.2**: Classification step 5 updated to assign BCMV subtype (Req 2)
- **Section 7.5 addendum (7.5.6)**: Boundary Signal Confidence levels added (Req 3)
- **Section 4.1**: Schema updated with `boundary_confidence` field (Req 3)
- **Section 9.1**: Family table updated with boundary confidence (Req 3)
- **Section 4.2**: New hard constraint 16: strength gating (Req 4)
- **Section 10.2**: Version boundary rules updated for strength gating (Req 4)
- **Section 4.2**: New hard constraint 17: compositional adversarial (Req 5)
- **Section 4.1**: Schema `mutation_sensitivity` expanded with structural variation types (Req 5)

---

## 3.7.4 How NECESSITY Is Checked (REVISED -- conditional validity added)

v3's NECESSITY probe procedure is retained but now wrapped in a validity precondition.

### 3.7.4.1 Conditional Validity Rule

> **NECESSITY is only valid if the test exercises the triggering conditions under which the subsystem is required.**

A NECESSITY claim says: "without this subsystem, correctness breaks." But correctness can only break if the test path actually NEEDS the subsystem. If the test only exercises the success-on-first-try path, a retry loop is never needed, and a NECESSITY probe will (correctly) report the loop as unnecessary -- not because it's decorative, but because the test didn't reach the path that requires it.

Therefore:

```
NECESSITY is valid iff:
  1. The invariant's trigger exercises the subsystem's critical path
  2. The critical path is the one where the subsystem is load-bearing
  3. The invariant spec explicitly documents which trigger conditions
     constitute the critical path
```

If the trigger conditions are NOT exercised, the NECESSITY requirement automatically **downgrades to EXERCISE**.

### 3.7.4.2 Required Spec Fields for NECESSITY

Every invariant with `mechanism_evidence_level == NECESSITY` must define:

```yaml
mechanism_requirements:
  evidence_level: NECESSITY
  necessity_conditions:
    critical_path_trigger: string     # What test action exercises the critical path
                                      # e.g., "retry_send with fail_first=True"
    trigger_exercised_by: string      # Which phase/action exercises it
                                      # e.g., "Phase C action_sequence[1]"
    coverage_proof: string            # How we know the critical path was reached
                                      # e.g., "_attempt_count >= 2 proves retry loop executed"
    downgrade_if_not_exercised: string # What happens if critical path is not reached
                                      # Always: "EXERCISE" (automatic downgrade)
  necessity_probe:
    target_subsystem: string
    monkeypatch: string
    expected_phase_c_result: "fail"
    critical_path_required: boolean   # true = probe only valid during critical path
```

### 3.7.4.3 Concrete Examples of Conditional NECESSITY

**retry_dup_a**:
```yaml
necessity_conditions:
  critical_path_trigger: "retry_send('msg', max_retries=3, fail_first=True)"
  trigger_exercised_by: "Phase C action_sequence[1] (failure-then-success path)"
  coverage_proof: "_attempt_count >= 2 after fail_first=True call"
  downgrade_if_not_exercised: "EXERCISE"
```
If the test only runs with `fail_first=False` (success on first try), the retry loop is never needed. NECESSITY automatically downgrades to EXERCISE. The coverage proof (`_attempt_count >= 2`) confirms the critical path was reached.

**false_fix_deadlock**:
```yaml
necessity_conditions:
  critical_path_trigger: "interleaved_transfers() with cross-lock acquisition"
  trigger_exercised_by: "Phase C interleaved transfer scenario"
  coverage_proof: "interleaved test returns state dict (not error dict)"
  downgrade_if_not_exercised: "EXERCISE"
```
If the interleaved transfer test is not run (only sequential), lock ordering doesn't matter. NECESSITY downgrades to EXERCISE. The coverage proof (no deadlock error) confirms the interleaving path was reached.

### 3.7.6 Automatic Downgrade Rule (NEW)

```
At evaluation time:
  If mechanism_evidence_level == NECESSITY:
    Check: was necessity_conditions.critical_path_trigger exercised?
    Evidence: does coverage_proof hold?
    If NO:
      Downgrade to EXERCISE for this evaluation.
      Log: "NECESSITY downgraded to EXERCISE: critical path not exercised.
            Trigger: {critical_path_trigger}. Coverage proof not satisfied."
      mechanism_evidence_level_achieved is capped at EXERCISE.
    If YES:
      Run necessity_probe as specified in v3.
```

This prevents false NECESSITY failures when the test environment doesn't reach the critical path (e.g., randomness mock doesn't trigger failure, or interleaving doesn't produce the expected ordering).

---

## 3.4.2 BCMV Subtypes (NEW)

v3 treated BCMV as a single classification. This overloads the signal. A model that removes a cache entirely is mechanistically different from a model that includes a decorative cache that doesn't do anything. Both are "behavior correct, mechanism violating" but they represent different failure modes of model reasoning.

### 3.4.2.1 Subtype Definitions

| Subtype | Code | Definition | What It Reveals |
|---|---|---|---|
| **Subsystem Removal** | `BCMV_REMOVAL` | The model deleted or gutted the target subsystem. The subsystem no longer exists as a functional entity. | Model chose simplification over repair. Did not engage with the subsystem's semantics. |
| **Subsystem Bypass** | `BCMV_BYPASS` | The subsystem exists but the code path avoids it. The fix routes around the subsystem rather than through it. | Model identified the subsystem as the problem source but chose avoidance over repair. |
| **Boundary Violation** | `BCMV_BOUNDARY` | Behavior is correct but module boundaries are violated. Fix is in the wrong file, or cross-module routing is rewired. | Model solved the problem but misunderstood the system architecture. |
| **Decorative Mechanism** | `BCMV_DECORATIVE` | The subsystem exists and runs, but is not load-bearing. Removing it wouldn't change the outcome. Only detectable at NECESSITY level. | Model included the mechanism for appearance but it's not functionally integrated. |
| **Non-Necessary Mechanism** | `BCMV_NON_NECESSARY` | The subsystem is exercised (EXERCISE passes) but NECESSITY probe shows it's not required for correctness on tested paths. This may indicate the test doesn't cover the critical path (see Section 3.7.4) rather than a model deficiency. | Ambiguous signal -- may be test gap or model gap. Should be reported but not counted as BCMV for scoring without investigation. |

### 3.4.2.2 Detection Rules

```
BCMV subtype assignment:

If EXISTENCE check fails:
  -> BCMV_REMOVAL (subsystem deleted)

If EXISTENCE passes but EXERCISE fails:
  -> BCMV_BYPASS (subsystem present but unused)

If EXISTENCE and EXERCISE pass but NECESSITY fails:
  If necessity_conditions.critical_path_trigger was exercised:
    -> BCMV_DECORATIVE (subsystem runs but isn't needed)
  If necessity_conditions.critical_path_trigger was NOT exercised:
    -> BCMV_NON_NECESSARY (ambiguous -- test didn't reach critical path)

If boundary checks fail (Phase F):
  -> BCMV_BOUNDARY (behavior correct, boundaries wrong)
```

### 3.4.2.3 Aggregation for Reporting

For the primary benchmark metric: all BCMV subtypes are aggregated as BCMV (not PASS).

For detailed analysis:
- `BCMV_REMOVAL` and `BCMV_BYPASS` are the strongest signals of mechanism misunderstanding
- `BCMV_BOUNDARY` indicates architectural misunderstanding
- `BCMV_DECORATIVE` indicates superficial mechanism inclusion
- `BCMV_NON_NECESSARY` is a WEAK signal that may reflect test limitations rather than model limitations -- it should be flagged in the report with the caveat from Section 3.7.4

### 3.4.2.4 Impact on MeasurementVerdict

The `MeasurementVerdict` (Section 7.1) is updated:

```python
@dataclass
class MeasurementVerdict:
    # ... all existing fields from v3 ...

    # --- BCMV detail --- (NEW)
    bcmv_subtype: str | None      # BCMV_REMOVAL | BCMV_BYPASS | BCMV_BOUNDARY |
                                   # BCMV_DECORATIVE | BCMV_NON_NECESSARY | None
    bcmv_evidence: list[str]       # What specific check failed and how
```

### 3.4.2.5 Impact on Classification Procedure

Step 5 of the classification procedure (Section 7.2) is updated:

```
5. Is mechanism required by equivalence_policy?
   YES -> Compute mechanism_evidence_level_achieved:
          EXISTENCE check:
            FAIL -> classification = BCMV, bcmv_subtype = BCMV_REMOVAL
          EXERCISE check:
            FAIL -> classification = BCMV, bcmv_subtype = BCMV_BYPASS
          If required level is NECESSITY:
            Check necessity_conditions.critical_path_trigger exercised:
              NOT EXERCISED -> downgrade to EXERCISE (Section 3.7.6)
              EXERCISED -> run necessity probe:
                FAIL -> classification = BCMV, bcmv_subtype = BCMV_DECORATIVE
          If achieved >= required -> proceed
   NO -> proceed

5.5 Are boundary checks required?
   YES -> Did Phase F (BOUNDARY) pass?
          NO -> classification = BCMV, bcmv_subtype = BCMV_BOUNDARY
          YES -> proceed
   NO -> proceed
```

---

## 7.5.6 Boundary Signal Confidence (NEW)

### 7.5.6.1 The Problem

Not all boundary checks provide equal confidence. A monkeypatch-based call-routing check that intercepts a function AND observes state change is stronger than one that only intercepts the call. A dependency-direction check that mutates the upstream source AND observes downstream change is stronger than one that only checks the downstream value.

Without confidence levels, all boundary evidence is treated equally, which can lead to overinterpretation of weak boundary signals.

### 7.5.6.2 Confidence Level Definitions

| Level | Name | Definition | Requirements |
|---|---|---|---|
| `HIGH` | Strong routing + state evidence | The check proves call routing AND observes correlated state changes in both caller and callee. | Monkeypatch intercepts the call AND downstream state reflects the intercepted call's effect. |
| `MEDIUM` | Routing only | The check proves a function was called via monkeypatch interception, but does not observe correlated state change. | Monkeypatch intercepts the call. No state correlation required. |
| `LOW` | Indirect / weak | The check infers routing from indirect evidence (e.g., the callee's state changed, so the caller must have called it). No direct interception. | State change observed in callee's module. No monkeypatch interception. |

### 7.5.6.3 Examples

**stale_cache_b (boundary_confidence: HIGH)**
```
1. Monkeypatch cache_invalidate with tracking wrapper     -> call routing intercepted
2. Call update_product("p1", price=99)                    -> triggers the path
3. Verify wrapper was called with key "p1"                -> call routing confirmed
4. Verify cache no longer contains stale value for "p1"   -> state effect confirmed
Result: HIGH confidence (routing + state correlation)
```

**overdetermination (boundary_confidence: MEDIUM)**
```
1. Monkeypatch write_fresh with tracking wrapper          -> call routing intercepted
2. Call update_product("P1", lambda: 42)                  -> triggers the path
3. Verify wrapper was called                              -> call routing confirmed
4. No independent state correlation check                 -> routing only
Result: MEDIUM confidence (routing without state correlation)
```

**config_shadowing (boundary_confidence: HIGH)**
```
1. Modify DEFAULTS["timeout"] = 99                        -> mutate upstream source
2. Call run_system_check()                                -> trigger downstream
3. Verify both request and background timeout == 99       -> downstream reflects upstream
4. Both state mutation AND downstream observation present -> full propagation proven
Result: HIGH confidence (propagation + state correlation)
```

### 7.5.6.4 Schema Addition

The invariant schema's `boundary_checks` entries are extended:

```yaml
boundary_checks:
  - type: "call_routing"
    description: "update_product must call cache.invalidate"
    check: "monkeypatch + state observation"
    confidence: HIGH         # HIGH | MEDIUM | LOW
    confidence_rationale: "Intercepts cache_invalidate call AND verifies cache state change"
```

### 7.5.6.5 How Confidence Affects Classification

Boundary confidence does NOT change the pass/fail decision. Phase F either passes or fails.

Boundary confidence IS reported in the MeasurementVerdict for downstream analysis:

```python
@dataclass
class MeasurementVerdict:
    # ... existing fields ...
    boundary_confidence: str | None   # HIGH | MEDIUM | LOW | None
```

When reporting BCMV_BOUNDARY classifications:
- HIGH confidence: strong claim that boundary was violated
- MEDIUM confidence: moderate claim, may warrant manual review
- LOW confidence: weak claim, should be reported as "possible boundary violation" not asserted

### 7.5.6.6 Family Assignments

| Family | Boundary Check Type | Confidence | Rationale |
|---|---|---|---|
| stale_cache_b/c | call_routing + state | HIGH | Intercept invalidate + verify cache cleared |
| config_shadowing | dependency_direction + state | HIGH | Mutate upstream + observe downstream |
| hidden_dep_multihop | call_routing + state | HIGH | Intercept cache_put + verify cache populated |
| overdetermination | call_routing | MEDIUM | Intercept write_fresh call, no independent state check |
| retry_dup_b/c | call_routing | MEDIUM | Intercept store call, no independent state check |

---

## 4.2 Schema Constraints (UPDATED -- two new constraints)

All constraints from v3 (1-15) remain unchanged. Two new constraints added:

```
>> 16. STRENGTH GATING (MANDATORY):
       If ANY invariant in the benchmark has semantic_strength_level < USABLE,
       the benchmark MUST NOT be used for reporting research results.
       This is a hard gate, not a recommendation.
       Violation produces: "BENCHMARK INVALID: {N} invariants below USABLE threshold.
       Cases: {list}. Fix these before reporting."
       Enforcement: META-7 (strength validation) is promoted from WARNING to BLOCKING
       for ALL invariants, not just mechanism-sensitive ones.

>> 17. COMPOSITIONAL ADVERSARIAL (MANDATORY):
       Every invariant MUST have at least one adversarial test where the input
       differs from the standard test input in at least TWO of the following
       structural dimensions:
         (a) value magnitude (different numbers, different strings)
         (b) collection size (different length list, different number of items)
         (c) element ordering (reversed, shuffled, interleaved differently)
         (d) structural shape (different keys, different nesting depth)
         (e) type variation (int vs float, list vs tuple, where spec allows)
       The adversarial input must differ in >= 2 dimensions, not just scalar
       value changes.
       This prevents adversarial tests that only vary "10 -> 20" without
       testing structural sensitivity.
```

### 4.2.1 Compositional Adversarial -- Concrete Examples

**What constraint 17 requires** (at least one test varying >= 2 structural dimensions):

**alias_config_a** (current adversarial: `create_config({"timeout": 42})` -- scalar value change only):
```
Required compositional adversarial:
  create_config({"timeout": 42, "new_key": True, "nested": {"a": 1}})
  Dimensions varied:
    (a) value magnitude: 42 instead of 5
    (d) structural shape: new_key and nested dict not in standard test
  Minimum 2 dimensions: SATISFIED
```

**stale_cache_a** (current: add/update/read with "p1" and price 25.0):
```
Required compositional adversarial:
  add_product("product_xyz", "Gadget", 100.0)  # different key, different name, different price
  add_product("product_abc", "Thing", 0.01)    # second product (collection size change)
  update_product("product_xyz", price=999.99)
  Dimensions varied:
    (a) value magnitude: different prices and names
    (b) collection size: two products instead of one
  Minimum 2 dimensions: SATISFIED
```

**effect_order_a** (current: `process_batch([10, 20, 30])` -- 3 items):
```
Required compositional adversarial:
  process_batch([5, 15, 25, 35, 45])           # 5 items instead of 3
  Expected snapshots: [5, 20, 45, 80, 125]     # different values AND different count
  Dimensions varied:
    (a) value magnitude: different numbers
    (b) collection size: 5 items instead of 3
  Minimum 2 dimensions: SATISFIED
```

**lost_update** (current anti-hardcoding: start from 10 instead of 0):
```
Required compositional adversarial:
  reset(); _set(100)
  Three increments (not two): read_a, read_b, read_c, write_a, write_b, write_c
  Expected sequential result: 103
  Dimensions varied:
    (a) value magnitude: starting from 100
    (b) collection size: 3 increments instead of 2
  Minimum 2 dimensions: SATISFIED
```

**wrong_condition_b** (current: one denied scenario):
```
Required compositional adversarial:
  is_allowed(rpm=0, rate_limit=1, daily=0, quota=1)          -> True (minimal limits)
  is_allowed(rpm=999, rate_limit=1000, daily=9999, quota=10000) -> True (near-limit)
  Dimensions varied:
    (a) value magnitude: extreme values (0, 999, 9999)
    (d) structural shape: all-minimal vs all-near-limit (different constraint profiles)
  Minimum 2 dimensions: SATISFIED
```

### 4.2.2 What Constraint 17 Rejects

Adversarial tests that only vary a single scalar value:
- `pipeline([10, 50, 30, 80, 20])` vs `pipeline([100, 200, 300, 400, 500])` -- same size, same shape, only values differ. This is ONE dimension (value magnitude). REJECTED.
- `is_rate_limited(4, 5)` vs `is_rate_limited(5, 5)` -- same types, same structure, different values at boundary. ONE dimension. REJECTED as the sole adversarial test (it can exist alongside a compositional one).

The constraint requires AT LEAST ONE test that varies >= 2 dimensions. It does not prohibit simpler adversarial tests in addition to the compositional one.

---

## 10.2 Version Boundaries (UPDATED -- strength gating added)

| Version | Definition | Breaking Change? |
|---|---|---|
| V2.0 | Current system (outcome-only tests, binary pass/fail) | Baseline |
| V2.1 | WEAK families fixed + strength gating enforced. **If any invariant remains < USABLE after fixes, V2.1 cannot be released for reporting.** | **YES** |
| V2.2 | USABLE families strengthened, BCMV classification introduced with subtypes | **YES** |
| V2.3 | Full measurement architecture (MeasurementVerdict, all families at STRONG+) | **YES** |

### 10.2.1 Strength Gating at Version Boundaries

The strength gate (constraint 16) is enforced at EVERY version boundary:

```
Before releasing V2.N results:
  Run META-7 (strength validation) on ALL invariants.
  If ANY invariant has strength < USABLE:
    BLOCK release.
    Report: "Cannot release V2.N: {list of sub-USABLE invariants}."
    Action: fix the invariants or exclude the cases from reporting.

Excluding cases:
  If a case cannot be brought to USABLE (e.g., the invariant is fundamentally
  ambiguous or the case design is flawed), it MAY be excluded from the reported
  benchmark subset. Excluded cases must be listed in the methodology section
  with justification.
  The reported pass rate denominator must reflect only included cases.
```

---

## 12. RISKS (two new entries)

### 12.11 BCMV Subtype Misassignment (NEW)

BCMV subtypes depend on the mechanism evidence hierarchy (EXISTENCE -> EXERCISE -> NECESSITY). If EXISTENCE is checked but the subsystem was renamed by the model (e.g., `_cache` renamed to `_store`), EXISTENCE fails and the subtype is BCMV_REMOVAL even though the subsystem exists under a different name. This is a false BCMV_REMOVAL.

**Mitigation**: EXISTENCE checks should look for MULTIPLE possible names where renaming is plausible. The invariant spec's `preserved_subsystems` field should list alternative names: `["_cache", "_data", "_store", "_cache_store"]`. EXISTENCE passes if ANY of the listed names is found. This is a spec authoring responsibility enforced by META-5 review.

### 12.12 Compositional Adversarial Over-Specification (NEW)

Constraint 17 requires inputs varying in >= 2 structural dimensions. For simple families (e.g., `wrong_condition`), finding a natural 2-dimension variation may be forced and artificial. A rate limiter doesn't naturally have "collection size" or "structural shape" variations.

**Mitigation**: The 5 structural dimensions include `(a) value magnitude` and `(e) type variation`. For scalar-input families, varying value magnitude + type (e.g., int vs float limits, zero vs negative vs large) satisfies the constraint naturally. The constraint does not require that ALL dimensions are applicable -- it requires that at least 2 of the 5 are varied in at least one adversarial test.

---

## Summary of All v4 Changes

| Requirement | Section | Change |
|---|---|---|
| 1: NECESSITY conditional | 3.7.4 (revised), 3.7.6 (new) | NECESSITY valid only when critical path exercised; auto-downgrades to EXERCISE otherwise; specs must define trigger conditions and coverage proof |
| 2: BCMV subtypes | 3.4.2 (new) | 5 subtypes: REMOVAL, BYPASS, BOUNDARY, DECORATIVE, NON_NECESSARY; detection rules; aggregation policy; MeasurementVerdict updated |
| 3: Boundary confidence | 7.5.6 (new) | HIGH/MEDIUM/LOW levels; family assignments; confidence affects reporting weight, not pass/fail |
| 4: Strength gating | 4.2 constraint 16, 10.2.1 | Hard gate: ANY invariant < USABLE blocks benchmark for reporting. Not a recommendation. |
| 5: Compositional adversarial | 4.2 constraint 17, 4.2.1-4.2.2 | >= 1 adversarial test varying >= 2 of 5 structural dimensions; concrete examples; rejection criteria |
