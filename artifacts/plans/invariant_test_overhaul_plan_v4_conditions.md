# Plan v4 -- Approval Conditions (Binding Addendum)

**Date**: 2026-03-30
**Status**: APPROVED WITH CONDITIONS
**Parent**: `plans/invariant_test_overhaul_plan_v4.md` (incorporating v2 and v3)

These 5 conditions are **execution rules**, not suggestions. They are enforced at implementation time, at experiment time, and at reporting time. Violation of any condition invalidates the corresponding results.

---

## Condition 1: Pre-Experiment Spec Compliance Audit

**When**: Before running ANY experiment whose results will be reported.

**What**: Run a machine-checkable audit that verifies every invariant in the benchmark satisfies ALL of the following:

```
Schema constraints 1-17 (Section 4.2 of v3/v4):
  1.  degenerate_pass_patterns non-empty
  2.  stateful -> reset_requirements defined
  3.  failure_injection -> both happy_path and failure_path defined
  4.  mechanism-sensitive -> mechanism_requirements.required with >= 1 constraint
  5.  complement_conditions non-empty
  6.  assertions >= 2 on different state dimensions
  7.  forbidden_post_state.exclusions >= 1
  8.  equivalence_policy set
  9.  non-behavior_only -> acceptable_mechanisms + forbidden_mechanisms non-empty
  10. mutation_sensitivity >= 2 distinct input variations
  11. stateful -> trigger has >= 2 sequential calls
  12. EXERCISE/NECESSITY -> >= 1 bypass degenerate pattern
  13. mechanism_evidence_level set; NONE iff behavior_only
  14. NECESSITY -> necessity_probe defined with monkeypatch target
  15. boundary-sensitive -> boundary_checks non-empty
  16. ALL invariants >= USABLE (hard gate)
  17. >= 1 compositional adversarial (>= 2 structural dimensions)

Mechanism evidence fields:
  - mechanism_evidence_level assigned
  - NECESSITY invariants have necessity_conditions with:
      critical_path_trigger
      trigger_exercised_by
      coverage_proof
      downgrade_if_not_exercised

Adversarial requirements:
  - mutation_sensitivity >= 2 entries
  - >= 1 compositional adversarial varying >= 2 dimensions
  - stateful invariants have >= 2 sequential calls

Boundary checks:
  - boundary-sensitive families have boundary_checks
  - each check has confidence level assigned
```

**Output**: A machine-readable audit report listing each invariant and its compliance status. Any FAIL blocks the experiment.

**Enforcement**: This audit is implemented as a validation script (e.g., `validate_invariant_specs.py`) and run as part of the pre-experiment checklist. It is not a manual review.

---

## Condition 2: Report BCMV Subtypes Separately

**When**: In every results report, dashboard, or analysis that mentions BCMV.

**What**: BCMV MUST be reported as 5 separate counts, never as a single aggregate without the breakdown.

**Required format** (minimum):

```
BCMV breakdown:
  BCMV_REMOVAL:        N1  (subsystem deleted)
  BCMV_BYPASS:         N2  (subsystem present but unused)
  BCMV_BOUNDARY:       N3  (behavior correct, boundaries violated)
  BCMV_DECORATIVE:     N4  (subsystem runs but not load-bearing)
  BCMV_NON_NECESSARY:  N5  (ambiguous -- see Condition 3)
  ────────────────────────
  BCMV total:          N1+N2+N3+N4+N5
```

**Enforcement**: The `MeasurementVerdict` dataclass includes `bcmv_subtype`. Any reporting code that aggregates BCMV without printing the subtype breakdown is non-compliant. Dashboard scripts, analysis notebooks, and summary reports must all include the breakdown.

An aggregate "BCMV rate = X%" line is permitted ONLY if the subtype breakdown appears in the same report section.

---

## Condition 3: BCMV_NON_NECESSARY Is "Uncertain"

**When**: In every results report and in the classification pipeline.

**What**: `BCMV_NON_NECESSARY` is NOT a failure. It is NOT a pass. It is an **uncertain signal** requiring further investigation.

**Classification rules**:
- Do NOT include in the failure count
- Do NOT include in the pass count
- Do NOT include in the BCMV count for primary metrics
- Report separately as: `uncertain_mechanism: N5`

**Required reporting format**:

```
Results (N_total cases, N_valid evaluated):
  TRUE_FIX:            X1
  PARTIAL_FIX:         X2
  LUCKY_FIX:           X3
  BCMV (confirmed):    X4  (REMOVAL + BYPASS + BOUNDARY + DECORATIVE)
  FAIL:                X5
  DEGENERATE_PASS:     X6
  TRAP_FIX:            X7
  ────────────────────────
  Uncertain:           X8  (BCMV_NON_NECESSARY -- requires investigation)
  Excluded:            X9  (CRASH, PARSE_FAILURE, below-USABLE cases)
```

The denominator for pass rate is `N_valid - X8 - X9` (excludes uncertain and excluded).

**Investigation protocol**: For each `BCMV_NON_NECESSARY` result, check:
1. Was the NECESSITY downgrade triggered? (If yes, the test didn't reach the critical path -- this is a test coverage issue, not a model issue.)
2. Can the invariant's trigger be strengthened to exercise the critical path?
3. If the critical path cannot be exercised deterministically, should this invariant's evidence level be downgraded to EXERCISE permanently?

---

## Condition 4: Log NECESSITY Downgrades Explicitly

**When**: At evaluation time, whenever a NECESSITY check is downgraded to EXERCISE per Section 3.7.6.

**What**: Emit a structured log entry with:

```json
{
  "event": "NECESSITY_DOWNGRADE",
  "case_id": "retry_dup_a",
  "invariant_id": "INV-retry_dup_a-001",
  "required_level": "NECESSITY",
  "achieved_level": "EXERCISE",
  "reason": "critical_path_not_exercised",
  "critical_path_trigger": "retry_send with fail_first=True",
  "coverage_proof_expected": "_attempt_count >= 2",
  "coverage_proof_actual": "_attempt_count == 1",
  "action": "downgraded to EXERCISE"
}
```

**Why this matters**: NECESSITY downgrades reveal:
- Where test coverage is insufficient (the critical path wasn't reached)
- Where invariants rely on fragile triggers (randomness mock, failure injection)
- Where the benchmark's mechanism claims are weaker than stated

**Aggregate reporting**: At the end of each experiment run, report:

```
NECESSITY downgrade summary:
  Total NECESSITY invariants:     N
  Fully exercised (no downgrade): M
  Downgraded to EXERCISE:         N-M
  Cases affected: [list]
```

If `N-M > 0`, the report must include a note:
> "{N-M} invariants required NECESSITY-level mechanism evidence but the critical path was not reached during evaluation. These invariants were evaluated at EXERCISE level. Mechanism claims for these cases are weaker than the spec requires."

---

## Condition 5: Separate Benchmark Validity from Model Performance

**When**: In every results report.

**What**: The report MUST distinguish between the benchmark's validity scope and the model's performance within that scope.

**Required reporting format**:

```
Benchmark validity:
  Total cases in benchmark:    T
  Valid cases (>= USABLE):     V
  Excluded cases (< USABLE):   E  [list with reasons]
  Benchmark validity rate:     V/T

Model performance (on valid cases only):
  TRUE_FIX rate:               X1/V
  BCMV rate (confirmed):       X4/V
  FAIL rate:                   X5/V
  ...
```

**Rules**:
- Model performance metrics use `V` (valid cases) as denominator, not `T` (total cases)
- Excluded cases are listed by name with the reason they are below USABLE
- If `E > 0`, the report must include the note: "This benchmark excludes {E} cases that do not meet the USABLE invariant strength threshold. Results are reported on the remaining {V} cases."
- If `E/T > 0.1` (more than 10% excluded), the report must include a prominent warning: "More than 10% of benchmark cases are excluded due to invariant weakness. Benchmark coverage is limited."

**Prohibition**: A report MUST NOT present `TRUE_FIX / T` as the pass rate when `E > 0`. The denominator must always be the valid case count.

---

## Summary

| Condition | Enforcement Point | Violation Consequence |
|---|---|---|
| 1. Spec compliance audit | Pre-experiment | Experiment blocked |
| 2. BCMV subtype reporting | Every report | Report non-compliant |
| 3. BCMV_NON_NECESSARY = uncertain | Classification + reporting | Metrics corrupted if lumped |
| 4. NECESSITY downgrade logging | Evaluation runtime | Mechanism claims unsubstantiated |
| 5. Validity / performance separation | Every report | Pass rates misleading |

These conditions are part of the approved plan. Implementation that does not satisfy them is not compliant with the plan.
