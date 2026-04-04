# Invariant Test System Overhaul -- Plan v3

**Task type**: FEATURE (measurement architecture redesign)
**Date**: 2026-03-30
**Status**: AWAITING APPROVAL
**Revision**: v3 -- targeted fixes to v2 addressing 6 remaining conceptual gaps

---

## Changes from v2

v2 was assessed at conceptual correctness 9/10, rigor 8/10. Six specific gaps were identified. v3 addresses each with surgical additions. Sections not listed below are UNCHANGED from v2.

### New sections added
- **Section 3.7**: Mechanism Evidence Strength Levels (Requirement 1)
- **Section 3.8**: Equivalence Consistency Constraint (Requirement 2)
- **Section 7.4**: Formal PARTIAL vs LUCKY Disambiguation (Requirement 3)
- **Section 7.5**: Boundary Integrity Checks (Requirement 4)
- **Section 13**: Validation Methodology Statement (Requirement 6)

### Sections modified
- **Section 4.1**: Schema updated with `mechanism_evidence_level` field
- **Section 4.2**: Three new hard schema constraints added (Requirement 5)
- **Section 7.1**: MeasurementVerdict updated with `mechanism_evidence_level` field
- **Section 7.2**: Classification procedure updated with PARTIAL/LUCKY precedence rule
- **Section 9.1**: Family table updated with mechanism evidence level assignments
- **Section 12**: Two new risks added

---

## Table of Contents (v3 additions marked with +)

1. What This Benchmark Is Actually Measuring *(unchanged)*
2. Diagnosis: Root Causes of Current System Failure *(unchanged)*
3. Mechanism vs Outcome Equivalence Policy *(3.1-3.6 unchanged)*
   - 3.7 Mechanism Evidence Strength Levels **(+NEW)**
   - 3.8 Equivalence Consistency Constraint **(+NEW)**
4. Invariant Specification System *(4.1 schema expanded, 4.2 constraints added)*
5. Isolation Model and Its Limits *(unchanged)*
6. Target Measurement Architecture *(unchanged)*
7. Candidate Evaluation Layer
   - 7.1-7.3 *(MeasurementVerdict updated, classification updated)*
   - 7.4 Formal PARTIAL vs LUCKY Disambiguation **(+NEW)**
   - 7.5 Boundary Integrity Checks **(+NEW)**
8. Benchmark Meta-Validation Layer *(unchanged)*
9. Family-Level Policy Assignments *(table updated with evidence levels)*
10. Benchmark Versioning Policy *(unchanged)*
11. Migration Plan *(unchanged)*
12. Risks *(two new entries)*
13. Validation Methodology Statement **(+NEW)**

---

## COMPLETE v3 CONTENT

Below are ALL sections. Sections unchanged from v2 are included by reference. Sections that are new or modified are written in full.

---

## Sections 1-2: UNCHANGED FROM v2

*(What This Benchmark Is Actually Measuring, Diagnosis)*

---

## Section 3: MECHANISM VS OUTCOME EQUIVALENCE POLICY

### 3.1-3.6: UNCHANGED FROM v2

*(Core Distinction, Equivalence Policy Taxonomy, Decision Procedure, Classification Rules, Concrete Examples, How Mechanism Constraints Are Enforced)*

### 3.7 Mechanism Evidence Strength Levels (NEW)

v2 treated mechanism checks as binary: `mechanism_pass: bool | None`. This is insufficient. There are four distinct levels of mechanism evidence, and each invariant must specify which level is required.

#### 3.7.1 Level Definitions

| Level | Name | Definition | What It Proves | How to Check |
|---|---|---|---|---|
| `NONE` | No mechanism evidence | Mechanism is not part of the invariant. Behavioral correctness is sufficient. | N/A | No check needed |
| `EXISTENCE` | Subsystem present | The subsystem (cache, retry loop, lock, config layer) exists in the loaded module as a named entity. | The model did not delete the subsystem. Does NOT prove the subsystem is used. | `hasattr(mod, '_cache')`, `hasattr(mod, 'retry_send')`, `callable(getattr(mod, 'cache_invalidate', None))` |
| `EXERCISE` | Subsystem used | The subsystem was invoked during test execution. Observable state in the subsystem changed, or traces show it was called. | The model preserved and used the subsystem, not just declared it. Does NOT prove the subsystem is necessary for correctness. | After read: `len(mod._cache) > 0`. After retry with failure: `mod._attempt_count >= 2`. After lock: `mod._locks` was modified. |
| `NECESSITY` | Subsystem required for correctness | Disabling or bypassing the subsystem causes the test to fail. The subsystem is not decorative -- it is load-bearing. | The model's fix depends on the subsystem. Removing the subsystem would break correctness. | Monkeypatch the subsystem to a no-op. Re-run the behavioral test. If it still passes, the subsystem is not necessary. If it fails, necessity is proven. |

#### 3.7.2 Level Relationships

NECESSITY implies EXERCISE implies EXISTENCE.

If an invariant requires `NECESSITY`, the test must verify all three lower levels as prerequisites. If an invariant requires `EXERCISE`, it must also verify `EXISTENCE`. This is a strict hierarchy.

#### 3.7.3 When Each Level Is Required

| Scenario | Required Level | Rationale |
|---|---|---|
| `behavior_only` policy | `NONE` | No mechanism constraint |
| Subsystem preservation but bug is local | `EXISTENCE` | Subsystem must survive the fix but need not be actively used in the tested path |
| Subsystem preservation and bug is IN the subsystem | `EXERCISE` | The fix must engage the subsystem to address the bug |
| Subsystem IS the point of the case (cache invalidation, retry semantics, lock ordering) | `NECESSITY` | Bypassing the subsystem is the primary degenerate pattern to exclude |

#### 3.7.4 How NECESSITY Is Checked

NECESSITY checking requires a **counterfactual probe**: temporarily disable the subsystem and verify that correctness breaks. This is done via monkeypatch, not AST analysis.

Concrete procedure:
```
1. Run the behavioral test (Phases B-D). Record: behavior_passes = True/False.
2. If behavior_passes:
   a. Monkeypatch the target subsystem to a no-op:
      - For cache: mod._cache = type('NoCache', (), {'get': lambda s,k: None, 'set': lambda s,k,v: None, ...})()
      - For retry: replace retry loop body with single direct call
      - For lock: replace acquire/release with no-ops
   b. Re-run Phase C (INVARIANT) only.
   c. If Phase C still passes: subsystem is NOT necessary. Evidence level = EXERCISE at best.
   d. If Phase C now fails: subsystem IS necessary. Evidence level = NECESSITY confirmed.
```

This is more expensive than EXERCISE checking (requires a second test run) and should only be used for families that require it. See Section 9.1 for assignments.

#### 3.7.5 Examples

**stale_cache_b** (required: EXERCISE)
- EXISTENCE: `hasattr(mod, '_cache')` or `hasattr(mod, '_data')` -- cache dict exists
- EXERCISE: After `get_product("p1")`, `mod._cache` or `mod._data` contains key "p1" -- cache was populated by the read
- Why not NECESSITY: For stale_cache, even if the cache were bypassed, the correct value would be returned from DB. The invariant is about the cache being coherent, not about it being necessary for correctness. EXERCISE proves it's used; NECESSITY would be vacuous because DB reads are always correct.

**retry_dup_a** (required: NECESSITY)
- EXISTENCE: `hasattr(mod, 'retry_send')` or the function contains a loop/recursion
- EXERCISE: After `retry_send("msg", fail_first=True)`, `mod._attempt_count >= 2` -- retry loop executed multiple times
- NECESSITY: Monkeypatch `send()` to always succeed. Remove the retry loop by replacing `retry_send` with a direct call to `send`. Re-run test. If the test still passes (because `fail_first` is mocked to always succeed first try), then the retry loop is not necessary for THIS specific test input. This reveals that NECESSITY for retry_dup requires the `fail_first=True` test path. Without that path, retry is never necessary.

**effect_order_a** (required: EXERCISE)
- EXISTENCE: `mod._snapshots` list exists, `mod.get_snapshots` callable
- EXERCISE: After `process_batch([10, 20, 30])`, snapshots == `[10, 30, 60]` (running totals prove per-item snapshot timing). The VALUES themselves are the exercise evidence -- they can only be `[10, 30, 60]` if snapshot was called after each item's counter increment.
- Why not NECESSITY: The snapshot mechanism is exercised and its correctness proven by the values. Disabling snapshots would trivially fail the test (no snapshots returned). NECESSITY adds no signal.

**false_fix_deadlock** (required: NECESSITY)
- EXISTENCE: `acquire()` and `release()` functions exist
- EXERCISE: `mod._locks` dict was modified during transfer execution
- NECESSITY: Replace `acquire`/`release` with no-ops. Re-run interleaved transfer test. If no deadlock error occurs AND balances are correct, the locking subsystem was decorative. If the test fails (deadlock simulation or incorrect balances), locks are necessary.

### 3.8 Equivalence Consistency Constraint (NEW)

#### 3.8.1 The Rule

> **Similar bug classes MUST share equivalence policy unless explicitly justified.**

This prevents silent policy divergence where semantically similar cases receive different mechanism requirements without rationale.

#### 3.8.2 Enforcement

Bug classes are defined by `bug_pattern_class` in `cases_v2.json`. Families sharing the same `bug_pattern_class` must share the same equivalence policy OR have an explicit justification for divergence.

**Consistency groups** (from `bug_pattern_class`):

| Bug Pattern Class | Families | Expected Shared Policy |
|---|---|---|
| `shared_reference_mutation` | alias_config | `behavior_only` |
| `partial_state_update` | partial_update, commit_gate, lost_update, index_misalign | Must share unless boundary_type differs |
| `hidden_dependency` | stale_cache, effect_order, early_return, overdetermination, hidden_dep_multihop, ordering_dependency | `behavior_plus_subsystem_preservation` for cross-file; `behavior_only` for local |
| `execution_model_mismatch` | lazy_init, false_fix_deadlock | `behavior_plus_lifecycle_preservation` or `behavior_plus_subsystem_preservation` |
| `retry_state_accumulation` | mutable_default, retry_dup | Diverges: mutable_default is `behavior_only` (no subsystem), retry_dup is `subsystem_preservation` (retry loop is a subsystem). **Justified**: mutable_default's bug is in the language construct (default argument), not in a subsystem. |
| `edge_case_omission` | use_before_set, wrong_condition, check_then_act, missing_branch | `behavior_only` |
| `implicit_schema` | temporal_drift, silent_default | `behavior_only` or `behavior_plus_side_effect_preservation` depending on whether side effects exist |

#### 3.8.3 Divergence Justification Requirements

When two families in the same bug class have different policies, the invariant spec for BOTH must include a `policy_divergence_justification` field explaining:
1. Why this family differs from its siblings
2. What property of this family's mechanism makes the default policy inappropriate
3. How the divergent policy aligns with the benchmark's measurement goals

**Example divergence**: `mutable_default` vs `retry_dup` (both `retry_state_accumulation`)
```yaml
# In retry_dup spec:
policy_divergence_justification:
  sibling: mutable_default
  sibling_policy: behavior_only
  this_policy: behavior_plus_subsystem_preservation
  reason: >
    mutable_default's bug is a Python language-level issue (mutable default argument).
    There is no subsystem to preserve -- the fix is about argument handling.
    retry_dup's bug is about a missing break in a retry LOOP. The retry loop is a
    distinct subsystem with its own semantics (failure detection, retry counting,
    backoff). Removing the loop is not equivalent to fixing the break -- it changes
    the system's failure-recovery capability.
```

#### 3.8.4 META-8 Enhancement

The existing META-8 (Equivalence Policy Consistency) check is extended to include:

```
For each bug_pattern_class with multiple families:
    Collect all policies assigned to families in this class
    If policies are not identical:
        For each divergent family:
            Assert: policy_divergence_justification is present and non-empty
            Log: "DIVERGENCE: {family} has {policy} while class default is {other}. Justification: {text}"
    If any divergence lacks justification: FAIL
```

---

## Section 4: INVARIANT SPECIFICATION SYSTEM

### 4.1 Full Schema (UPDATED -- additions marked with >>)

```yaml
invariant:
  # --- IDENTITY --- (unchanged)
  invariant_id: string
  family: string
  case_id: string
  bug_pattern: string
  semantic_domain: string

  # --- EQUIVALENCE POLICY --- (updated)
  equivalence_policy: enum
  acceptable_mechanisms: list[str]
  forbidden_mechanisms: list[str]
  classification_if_behavior_passes_but_mechanism_fails: enum

  >> mechanism_evidence_level: enum    # NONE | EXISTENCE | EXERCISE | NECESSITY
                                       # Required evidence strength (Section 3.7)
                                       # Must be set for every invariant.
                                       # NONE iff equivalence_policy == behavior_only.

  >> policy_divergence_justification: dict | null
                                       # Required if this family's policy diverges from
                                       # its bug_pattern_class siblings (Section 3.8)

  # --- SCOPE --- (unchanged)
  scope: enum
  boundary_type: enum
  temporal_scope: string
  statefulness: enum

  # --- STATE SURFACES --- (unchanged)
  observational_surface: list[str]
  hidden_state_surface: list[str]
  required_unchanged_state: list[str]

  # --- STATE TRANSITION --- (unchanged)
  pre_state: ...
  trigger: ...
  required_post_state: ...
  forbidden_post_state: ...

  # --- MECHANISM --- (updated)
  mechanism_requirements:
    required: boolean
    >> evidence_level: enum            # NONE | EXISTENCE | EXERCISE | NECESSITY
                                       # Mirrors top-level mechanism_evidence_level.
                                       # Included here for self-contained mechanism block.
    constraints: list[dict]
    preserved_subsystems: list[str]
    forbidden_bypasses: list[str]
    >> necessity_probe: dict | null    # Required if evidence_level == NECESSITY
                                       # {target_subsystem: str,
                                       #  monkeypatch: str,
                                       #  expected_phase_c_result: "fail"}

  mechanism_evidence_requirements: list[str]

  # --- BOUNDARY INTEGRITY --- (NEW, see Section 7.5)
  >> boundary_checks: list[dict] | null
                                       # Required if boundary_type != "local"
                                       # Each: {type: str, description: str, check: str}
                                       # type: "call_routing" | "source_of_truth" | "dependency_direction"
                                       # check: observable behavioral check

  # --- PARTIAL / LUCKY FIX CRITERIA --- (updated, see Section 7.4)
  partial_fix_criteria: list[dict]
  lucky_fix_criteria: list[str]
  >> partial_vs_lucky_precedence: string  # "lucky_overrides_partial" | "partial_default"
                                          # See Section 7.4 for semantics

  # --- ANTI-DEGENERATE --- (unchanged)
  degenerate_pass_patterns: list[dict]

  # --- COMPLEMENT, MUTATION, ADVERSARIAL --- (unchanged)
  complement_conditions: list[dict]
  minimal_happy_path: dict
  minimal_failure_path: dict | null
  mutation_sensitivity: list[str]
  adversarial_dimensions: list[str]

  # --- ENVIRONMENT --- (unchanged)
  environment_assumptions: list[str]
  nondeterminism_controls: list[dict]

  # --- RESET --- (unchanged)
  reset_requirements: ...

  # --- STRENGTH --- (unchanged)
  semantic_strength_level: enum
  current_strength_assessment: string
  strength_gaps: list[str]
```

### 4.2 Schema Constraints (UPDATED -- new constraints marked with >>)

Hard rules from v2 (1-9) remain unchanged. Three new constraints added:

```
>> 10. Every invariant MUST have mutation_sensitivity with >= 2 entries specifying
       distinct input variations that produce different expected outputs.
       (Requirement 5: >=2 input variations)

>> 11. Every invariant with statefulness != "stateless" MUST have at least one
       action_sequence in trigger containing >= 2 sequential calls with state
       verification between them.
       (Requirement 5: >=2 sequential calls for stateful invariants)

>> 12. Every invariant with mechanism_evidence_level in {EXERCISE, NECESSITY}
       MUST have at least one entry in degenerate_pass_patterns with pattern
       type "bypass_*" that represents removing the target subsystem.
       (Requirement 5: >=1 bypass attempt test for mechanism-sensitive invariants)

>> 13. mechanism_evidence_level MUST be set for every invariant. It MUST be NONE
       if and only if equivalence_policy == "behavior_only".
       (Requirement 1: mechanism evidence is always specified)

>> 14. If mechanism_evidence_level == NECESSITY, then mechanism_requirements.necessity_probe
       MUST be defined with a concrete monkeypatch target and expected failure.
       (Requirement 1: NECESSITY level has concrete probe)

>> 15. If boundary_type != "local" AND equivalence_policy includes "boundary_preservation",
       then boundary_checks MUST be non-empty.
       (Requirement 4: boundary-sensitive invariants have boundary checks)
```

### 4.3-4.4: UNCHANGED FROM v2

*(Strength Criteria, Automatic Disqualifiers)*

---

## Section 5-6: UNCHANGED FROM v2

*(Isolation Model and Its Limits, Target Measurement Architecture)*

---

## Section 7: CANDIDATE EVALUATION LAYER

### 7.1 MeasurementVerdict Schema (UPDATED)

```python
@dataclass
class PhaseResult:
    phase: str                    # "precondition" | "happy_path" | "invariant" |
                                  # "adversarial" | "mechanism" | "boundary"
    invariant_id: str
    passed: bool
    assertions_total: int
    assertions_passed: int
    failure_details: list[str]
    state_diff: dict | None

@dataclass
class MeasurementVerdict:
    case_id: str
    variant: str

    # --- Primary classification ---
    classification: str           # TRUE_FIX | PARTIAL_FIX | LUCKY_FIX | BCMV |
                                  # DEGENERATE_PASS | TRAP_FIX | FAIL |
                                  # CRASH | PARSE_FAILURE

    # --- Behavioral dimension ---
    behavior_pass: bool

    # --- Mechanism dimension --- (UPDATED)
    mechanism_pass: bool | None
    mechanism_evidence: list[str]
    mechanism_evidence_level_required: str   # NONE | EXISTENCE | EXERCISE | NECESSITY
    mechanism_evidence_level_achieved: str   # NONE | EXISTENCE | EXERCISE | NECESSITY
                                             # Highest level for which all checks passed.
                                             # mechanism_pass = (achieved >= required)

    # --- Boundary dimension --- (NEW)
    boundary_pass: bool | None    # Did boundary integrity checks pass? None if not required.
    boundary_evidence: list[str]

    # --- Phase detail ---
    phases: list[PhaseResult]

    # --- Degenerate detection ---
    degenerate_pattern_detected: str | None

    # --- State ---
    state_isolation_verified: bool
    unchanged_state_violations: list[str]

    # --- Anti-cheat ---
    anti_hardcoding_passed: bool

    # --- Partial fix detail ---
    invariants_satisfied: list[str]
    invariants_violated: list[str]

    # --- Partial vs Lucky --- (NEW)
    partial_or_lucky_detail: str | None  # If PARTIAL_FIX or LUCKY_FIX, explains which and why

    # --- Metadata ---
    equivalence_policy: str
    execution_model: str
```

### 7.2 Classification Decision Procedure (UPDATED -- step 3.5 added)

```
1. Did the code parse/compile/load?
   NO -> CRASH or PARSE_FAILURE

2. Did Phase B (HAPPY_PATH) pass?
   NO -> Check if it's a no-op/constant -> DEGENERATE_PASS (if detected) or FAIL

3. Did Phase C (INVARIANT) pass?
   NO -> Check which assertions failed:
         Some passed, some failed -> candidate for PARTIAL_FIX
         All failed -> FAIL

3.5 PARTIAL vs LUCKY precedence (NEW -- see Section 7.4):
   If candidate is PARTIAL_FIX from step 3:
     Run Phase D (ADVERSARIAL) on the PASSING assertions only.
     If any passing assertion fails under adversarial input:
       -> LUCKY_FIX (overrides PARTIAL_FIX per Section 7.4)
     Else:
       -> PARTIAL_FIX (failure is structural, not input-dependent)

4. Did Phase D (ADVERSARIAL) pass?
   NO -> If standard input passed but variant failed -> LUCKY_FIX
   NO -> If complement failed -> FAIL (one-sided implementation)

5. Is mechanism required by equivalence_policy?
   YES -> Compute mechanism_evidence_level_achieved (Section 3.7):
          Check EXISTENCE. If fail -> BCMV (subsystem missing)
          Check EXERCISE. If fail -> BCMV (subsystem present but unused)
          If required level is NECESSITY: run necessity probe.
            If subsystem not necessary -> BCMV (subsystem decorative)
          If achieved >= required -> proceed
   NO -> proceed

5.5 Are boundary checks required? (NEW)
   YES -> Did Phase F (BOUNDARY) pass?
          NO -> BCMV (behavior correct but boundary violated)
          YES -> proceed
   NO -> proceed

6. Was a forbidden_post_state pattern detected?
   YES -> DEGENERATE_PASS

7. Does the fix match a declared trap_fix_detection pattern?
   YES -> TRAP_FIX

8. All checks pass -> TRUE_FIX
```

### 7.3: UNCHANGED FROM v2

*(Phase Specifications -- with Phase F added below in 7.5)*

### 7.4 Formal PARTIAL vs LUCKY Disambiguation (NEW)

#### 7.4.1 Definitions

**PARTIAL_FIX**: The model's code satisfies a proper subset of the invariant's clauses. The failures are **consistent across inputs** -- the same clauses fail regardless of what test data is used. The failure is structural (part of the fix is missing), not accidental.

Formally:
```
PARTIAL_FIX iff:
  EXISTS clause set S ⊂ invariant_clauses where:
    for all tested inputs I: clauses in S pass AND clauses not in S fail
```

**LUCKY_FIX**: The model's code satisfies the invariant only for the specific tested inputs. Under input variation (different values, different orderings, different sizes), some previously-passing clauses fail. The success is **input-dependent**, not structural.

Formally:
```
LUCKY_FIX iff:
  EXISTS clause C in invariant_clauses where:
    EXISTS input I1 where C passes AND
    EXISTS input I2 where C fails
```

#### 7.4.2 Precedence Rule

> **LUCKY overrides PARTIAL if the failure is input-dependent.**

If a model's code passes 2 of 3 invariant clauses (candidate PARTIAL_FIX), but one of the 2 passing clauses fails under a different input (adversarial phase), the classification is LUCKY_FIX, not PARTIAL_FIX.

Rationale: PARTIAL_FIX implies the model understood part of the problem and implemented that part correctly. LUCKY_FIX implies the model didn't reliably solve even the parts that appeared to work. LUCKY is a weaker signal than PARTIAL, and misclassifying LUCKY as PARTIAL inflates confidence in the model's reasoning.

#### 7.4.3 Detection Procedure

```
1. Run Phase C (INVARIANT) with standard inputs.
   Record: clauses_passed, clauses_failed.

2. If clauses_passed is non-empty AND clauses_failed is non-empty:
   -> Candidate PARTIAL_FIX.

3. For each clause in clauses_passed:
   Run the same clause with adversarial inputs (from mutation_sensitivity).
   If clause fails under ANY adversarial input:
     -> Mark clause as input_dependent.

4. If ANY clause is input_dependent:
   -> Classification = LUCKY_FIX (precedence over PARTIAL)
   -> partial_or_lucky_detail = "Clauses {X} passed for standard inputs but failed
      for adversarial inputs {Y}. Success is input-dependent, not structural."

5. If NO clause is input_dependent:
   -> Classification = PARTIAL_FIX
   -> partial_or_lucky_detail = "Clauses {X} pass consistently. Clauses {Y} fail
      consistently. Fix addresses invariants {X_ids} but not {Y_ids}."
```

#### 7.4.4 Examples

**Example 1: PARTIAL_FIX**
Case: `commit_gate`. Model restores `commit(st)` but not `freeze_view(st)`.
- Clause "total not null" -> PASS (commit sets frozen gate)
- Clause "view consistent with committed" -> FAIL (freeze_view missing)
- Adversarial: different entries -> "total not null" still passes
- Classification: PARTIAL_FIX (commit is structurally present, freeze_view is structurally absent)

**Example 2: LUCKY_FIX**
Case: `stale_cache_a`. Model invalidates cache only for key "p1".
- Standard test with key "p1" -> PASS (invalidation works for this key)
- Adversarial test with key "p2" -> FAIL (invalidation doesn't work for other keys)
- Classification: LUCKY_FIX (success is input-dependent on the key being "p1")

**Example 3: Precedence override**
Case: `wrong_condition_b`. Model writes `return rate_ok or (quota_ok and rate_ok)`.
- Standard test (rate OK, quota exceeded) -> correctly blocks (PASS)
- Adversarial test (rate exceeded, quota OK) -> incorrectly allows (FAIL)
- The "blocks when quota exceeded" clause passes for standard inputs but the overall logic is still wrong.
- Without the complement test this would look like PARTIAL (some clauses pass).
- With adversarial input, the passing clause is revealed as input-dependent.
- Classification: LUCKY_FIX (overrides PARTIAL per precedence rule)

### 7.5 Boundary Integrity Checks (NEW)

#### 7.5.1 The Problem

The current harness flattens all files into a merged namespace. Cross-file invariants (config_shadowing, hidden_dep_multihop, overdetermination, stale_cache_b/c, retry_dup_b/c) cannot be verified because module boundaries don't exist at test time.

AST-based checking (reading the model's source to verify `from X import Y` statements) is fragile, implementation-coupled, and unavailable in the subprocess execution path.

#### 7.5.2 The Solution: Observable Behavioral Boundary Checks

Boundary integrity is verified by **observing the behavioral consequences of module boundaries**, not by reading source code. Three check types:

**Type 1: Call Routing**
Verify that function X calls function Y by monkeypatching Y and observing the effect on X's output.

```
check_type: call_routing
description: "update_product must call cache.invalidate (not bypass cache)"
check:
  1. Save original cache.invalidate
  2. Replace mod.cache_invalidate (or mod.invalidate) with a tracking wrapper
  3. Call mod.update_product("p1", price=99)
  4. Verify the wrapper was called with key "p1"
  5. Restore original
```

If `update_product` bypasses the cache, the wrapper is never called. This proves routing without reading source code.

**Type 2: Source of Truth**
Verify that a specific module's state is the authoritative data source by modifying it directly and observing downstream effects.

```
check_type: source_of_truth
description: "db._tables must be the source of truth for read_record"
check:
  1. Call mod.update_record("k1", "from_api")
  2. Directly modify mod._tables["records"]["k1"] = "from_db_hack"
  3. Invalidate cache: mod.cache_invalidate("k1") if available
  4. Call mod.read_record("k1")
  5. Result must be "from_db_hack" (DB is source of truth, not a parallel store)
```

**Type 3: Dependency Direction**
Verify that module A depends on module B (not the reverse) by testing that changes in B propagate to A.

```
check_type: dependency_direction
description: "service.py must depend on defaults.py (not hardcode its own defaults)"
check:
  1. Modify mod.DEFAULTS["timeout"] = 99 (change the source)
  2. Call mod.run_system_check()
  3. Both request and background timeouts must now be 99
  4. If they remain 30: service.py is hardcoding, not reading from defaults.py
```

#### 7.5.3 Which Families Need Boundary Checks

Only families with `boundary_type != "local"` AND `equivalence_policy` including `boundary_preservation`:

| Family | Boundary Check | Type |
|---|---|---|
| stale_cache_b/c | update_product must route through cache invalidation | call_routing |
| config_shadowing | service.py must read from defaults.py, not hardcode | dependency_direction |
| hidden_dep_multihop | save_user must route through cache write | call_routing |
| overdetermination | update_product must use writer module, not direct store access | call_routing |
| retry_dup_b/c | send_with_retry must use store module for persistence | call_routing |

#### 7.5.4 Phase F: BOUNDARY

Added as a new phase in the CandidateEvaluator:

**Phase F: BOUNDARY** (conditional on boundary_checks being non-empty)
- Source: `invariant.boundary_checks`
- Purpose: Verify module boundaries are preserved via behavioral probes
- Technique: Monkeypatch + observe (Section 7.5.2)
- On failure: BCMV (behavior correct but boundaries violated -- the model flattened or rewired the module structure)

Phase F runs AFTER Phase E (MECHANISM) and BEFORE the final classification in step 6.

#### 7.5.5 Limitations

Boundary checks via monkeypatch have limitations:
- They can only test boundaries that are observable through the merged namespace's attribute access
- If the model inlines a function's body (rather than calling it), the monkeypatch won't intercept it
- They prove routing at the call level, not at the import/module level

These limitations are acceptable because:
- The benchmark's primary metric is behavioral correctness (Phases B-D)
- Boundary checks are a secondary signal for mechanism-sensitive families
- The merged namespace is a known limitation documented in Section 5
- Full module isolation (subprocess with proper imports) is the long-term fix (Phase 4 of migration)

---

## Section 8: UNCHANGED FROM v2

*(Benchmark Meta-Validation Layer)*

---

## Section 9: FAMILY-LEVEL POLICY ASSIGNMENTS (UPDATED)

### 9.1 Complete Assignment Table (with mechanism evidence level)

| Family | Equivalence Policy | Mechanism Evidence Level | Boundary Checks | Current Strength | Target Strength |
|---|---|---|---|---|---|
| alias_config | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| partial_update | `behavior_only` | NONE | No | USABLE | STRONG |
| stale_cache (a) | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| stale_cache (b,c) | `subsystem_preservation` | EXERCISE | call_routing | STRONG | RESEARCH_GRADE |
| lazy_init | `lifecycle_preservation` | EXERCISE | No | USABLE | STRONG |
| mutable_default | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| effect_order | `side_effect_timing` | EXERCISE | No | USABLE | STRONG |
| use_before_set | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| retry_dup (a) | `subsystem_preservation` | NECESSITY | No | **WEAK** | RESEARCH_GRADE |
| retry_dup (b,c) | `subsystem_preservation` | NECESSITY | call_routing | **WEAK** | RESEARCH_GRADE |
| partial_rollback | `compensation_semantics` | EXERCISE | No | **WEAK** | RESEARCH_GRADE |
| temporal_drift | `side_effect_preservation` | NONE | No | USABLE | STRONG |
| missing_branch | `behavior_only` | NONE | No | USABLE | STRONG |
| wrong_condition | `behavior_only` | NONE | No | **WEAK** | STRONG |
| early_return | `side_effect_preservation` | NONE | No | USABLE | STRONG |
| index_misalign | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| silent_default (a,b) | `behavior_only` | NONE | No | USABLE | STRONG |
| silent_default (c) | `propagation_semantics` | EXERCISE | No | USABLE | STRONG |
| l3_state_pipeline | `subsystem_preservation` | EXERCISE | No | USABLE | STRONG |
| cache_invalidation_order | `subsystem_preservation` | EXERCISE | No | USABLE | STRONG |
| feature_flag_drift | `propagation_semantics` | EXERCISE | No | USABLE | STRONG |
| invariant_partial_fail | `compensation_semantics` | EXERCISE | No | **WEAK** | RESEARCH_GRADE |
| async_race_lock | `subsystem_preservation` | EXERCISE | No | STRONG | RESEARCH_GRADE |
| hidden_dep_multihop | `subsystem_preservation` | EXERCISE | call_routing | STRONG | RESEARCH_GRADE |
| config_shadowing | `propagation_semantics` | EXERCISE | dependency_direction | **WEAK** | STRONG |
| commit_gate | `subsystem_preservation` | EXERCISE | No | USABLE | STRONG |
| overdetermination | `subsystem_preservation` | EXERCISE | call_routing | USABLE | STRONG |
| lost_update | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| check_then_act | `behavior_only` | NONE | No | STRONG | RESEARCH_GRADE |
| ordering_dependency | `behavior_only` | NONE | No | USABLE | STRONG |
| false_fix_deadlock | `subsystem_preservation` | NECESSITY | No | STRONG | RESEARCH_GRADE |

### 9.2 Policy Justifications: UNCHANGED FROM v2

### 9.3 Evidence Level Justifications for Non-Obvious Assignments

**retry_dup = NECESSITY**: The retry loop is the entire point. EXERCISE proves the loop ran. But a model could include a decorative retry loop that runs but doesn't affect correctness (e.g., the `break` is present and works, but the loop could be removed and the function would still succeed on first try for the tested inputs). NECESSITY proves the loop is load-bearing -- that without it, the fail_first=True test path would produce wrong results.

**false_fix_deadlock = NECESSITY**: Locks are the entire point. A model could include lock acquire/release calls that are decorative (the step-based simulation doesn't actually interleave). NECESSITY proves that removing locks causes the interleaved test to fail.

**partial_rollback = EXERCISE (not NECESSITY)**: The compensation mechanism must be exercised (evidence: inventory was reserved then released). But NECESSITY checking (disabling compensation and re-running) is complex because the "no compensation" case is the original bug. The fact that the happy path shows state change AND the failure path shows state restoration is sufficient EXERCISE evidence.

**stale_cache_b/c = EXERCISE (not NECESSITY)**: Cache EXERCISE (cache populated after read) proves the cache exists and is used. NECESSITY (disable cache, re-test) would always show correct results (DB reads are always fresh), so it would report the cache as unnecessary -- which is technically true but misleading. The case tests cache *coherence*, not cache *necessity*.

---

## Section 10: UNCHANGED FROM v2

*(Benchmark Versioning Policy)*

---

## Section 11: UNCHANGED FROM v2

*(Migration Plan -- Phase 3 now includes boundary check implementation for applicable families. Phase 4 includes NECESSITY probes for retry_dup and false_fix_deadlock.)*

---

## Section 12: RISKS (UPDATED -- two new entries)

### 12.1-12.8: UNCHANGED FROM v2

### 12.9 NECESSITY Probe False Negatives (NEW)

The NECESSITY counterfactual probe (monkeypatch subsystem to no-op, re-test) may produce false negatives if the monkeypatch is incomplete. For example, if the cache is spread across multiple internal variables and only one is patched, the probe may report "subsystem necessary" when it actually tested an incomplete bypass.

**Mitigation**: NECESSITY probes must patch at the subsystem's public interface, not internal state. For cache: patch `cache_get`/`cache_set` functions. For locks: patch `acquire`/`release`. For retry: patch the loop control. Each necessity_probe in the spec must identify the exact patch target and be validated during META-3.

### 12.10 Boundary Check Inlining Evasion (NEW)

If a model inlines a function's body (copies the code rather than calling the function), monkeypatch-based call-routing checks won't detect this. The boundary appears intact (function exists, is callable) but is not actually used.

**Mitigation**: This is a known limitation of behavioral boundary checking. For families where inlining is a realistic model behavior, EXERCISE-level mechanism evidence (e.g., cache state populated after read) provides a secondary signal. If the model inlines the cache read logic but still maintains cache state, the EXERCISE check catches it. If the model inlines AND removes cache state, the EXISTENCE check catches it. The risk is models that inline, remove internal state, but produce correct outputs -- these are correctly classified as BCMV.

---

## 13. VALIDATION METHODOLOGY STATEMENT (NEW)

### 13.1 What This System Is

This measurement system uses **behavioral validation combined with observable-structure probing**. It is a hybrid approach.

It is NOT:
- Pure behavioral testing (which cannot distinguish mechanism-preserving from mechanism-violating fixes)
- Pure structural analysis (which would require AST/source-code inspection and would be brittle)
- Formal verification (which would require mathematical proof of invariant satisfaction)

It IS:
- Behavioral testing for output correctness (Phases B, C, D)
- Observable-structure probing for mechanism evidence (Phase E)
- Monkeypatch-based routing verification for boundary integrity (Phase F)
- Counterfactual probing for subsystem necessity (NECESSITY level)

### 13.2 Why Hybrid

Pure behavioral testing produces false positives: a cache-bypassing implementation is behaviorally indistinguishable from a cache-fixing implementation when tested at the API level.

Pure structural analysis produces false negatives: a valid fix using a different coding style or different function decomposition would fail a structural check looking for the reference fix's exact pattern.

The hybrid approach uses behavioral checks as the primary signal (these are robust to implementation variation) and observable-structure probes as a secondary signal (these disambiguate mechanism-equivalent from mechanism-violating fixes). The secondary signal is always checked via runtime behavior (monkeypatch, state inspection), never via source code analysis.

### 13.3 Strength of Each Validation Layer

| Layer | What It Catches | What It Misses | Trust Level |
|---|---|---|---|
| Behavioral (Phases B-D) | Incorrect outputs, missing functionality, one-sided logic, hardcoded values | Mechanism violations that produce correct outputs | HIGH -- directly observable, input-output relationship |
| Observable-Structure (Phase E) | Missing subsystems, unused subsystems, decorative subsystems | Inlined subsystem logic, correct mechanism via different internal structure | MEDIUM -- indirect observation, depends on subsystem having observable state |
| Boundary Routing (Phase F) | Bypassed module calls, hardcoded consumers, reversed dependencies | Inlined function bodies, monkeypatch-evasive patterns | MEDIUM-LOW -- monkeypatch coverage depends on interface granularity |
| Counterfactual Necessity | Decorative subsystems that exist and run but aren't needed | Subsystems that are needed for untested paths but not the tested path | MEDIUM -- depends on test coverage of the subsystem's critical path |

### 13.4 What This System Does NOT Claim

1. It does NOT claim to detect all mechanism violations. A sufficiently adversarial model could produce a fix that satisfies all behavioral and structural checks while using an entirely different internal mechanism. The system detects the most common violation patterns (bypass, removal, decorative inclusion) but not all possible ones.

2. It does NOT claim that BCMV classification is always correct. A fix classified as BCMV may actually be a valid alternative mechanism that the invariant spec's `acceptable_mechanisms` list didn't anticipate. This is a spec incompleteness issue, not a system design issue.

3. It does NOT claim that NECESSITY probes are comprehensive. A subsystem may be necessary for paths not exercised by the current test. NECESSITY is proven relative to the tested paths, not all possible paths.

4. It does NOT claim that boundary checks prove true module isolation. The merged-namespace execution model fundamentally prevents testing import-level isolation. Boundary checks probe call-level routing within the merged namespace, which is a weaker guarantee.

### 13.5 Honest Assessment

The behavioral layer (Phases B-D) is HIGH confidence. It is well-understood, input-output based, and robust to implementation variation. Any weakness in this layer comes from insufficient input coverage, which is addressed by the adversarial and anti-hardcoding requirements (Section 4.2 constraints 10-12).

The mechanism layer (Phases E-F) is MEDIUM confidence. It catches the most common degenerate patterns (subsystem removal, bypass, decorative inclusion) but can be evaded by sophisticated adversarial implementations. For a research benchmark evaluating current-generation LLMs, this is sufficient -- current models are not adversarially optimizing against the evaluation harness. If future models exhibit this behavior, the mechanism layer must be strengthened with deeper probes or full module isolation.

The classification layer (Section 7.2) is HIGH confidence for the binary dimension (behavior pass/fail) and MEDIUM confidence for the multi-class dimension (TRUE_FIX vs BCMV vs PARTIAL vs LUCKY). The PARTIAL/LUCKY disambiguation (Section 7.4) adds rigor, but edge cases remain where the boundary between the two is ambiguous.

Overall: this system is suitable for **preliminary research reporting** with the classifications used as analytical signals, not as ground truth labels. The behavioral pass rate is trustworthy. The mechanism classifications are informative but should be reported with the methodology statement attached.
