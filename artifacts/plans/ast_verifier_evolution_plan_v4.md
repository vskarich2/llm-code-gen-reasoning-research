# AST Verifier Evolution Plan v4 — Measurement Instrument Finalization

**Date:** 2026-04-03
**Supersedes:** v3 where specified
**Scope:** 6 new sections closing the remaining gaps

---

## 1. Decision-Level Impact of AST

### What decisions the system makes

The system classifies each failure into a stage. Without AST, there are 2 stages. With AST, there are 3.

### Measured decision-level impact (20,031 events, 3,837 failures)

**Without AST (2-stage classification):**

| Stage | Count | % of failures |
|-------|-------|---------------|
| Reasoning fail (oracle=wrong) | 1,320 | 34.4% |
| Other fail (oracle=correct, exec=fail) | 2,517 | 65.6% |

**With AST (3-stage classification):**

| Stage | Count | % of failures |
|-------|-------|---------------|
| Reasoning fail | 1,320 | 34.4% |
| Structural fail (oracle=correct, AST=incorrect) | 275 | 7.2% |
| Execution fail (oracle=correct, AST=correct) | 2,242 | 58.4% |

**AST reclassifies 275 events (7.2% of failures)** from the undifferentiated "other fail" bucket into "structural fail." These are cases where the oracle says the model reasoned correctly but AST says the code doesn't implement the correct structure. Without AST, these are invisible — lumped with execution failures.

### How often AST changes the per-event verdict

| Comparison | Disagreement rate | Events reclassified |
|-----------|-------------------|---------------------|
| AST vs execution | 14.9% | 2,985 (2,531 AST-correct+exec-fail + 454 AST-wrong+exec-pass) |
| AST vs old classifier | 8.7% | 1,743 |
| AST vs oracle | 6.6% | 1,322 |

### Are the reclassifications correct?

**AST uniquely correct (oracle confirms AST was right, execution was wrong):** 2,242 events.
**AST uniquely wrong (oracle confirms execution was right, AST was wrong):** 154 events.
**Net: AST correctly reclassifies 2,088 events** that execution alone misclassifies.

### Verdict

AST changes the failure-stage classification for 7.2% of failures. It correctly reclassifies >14x more events than it incorrectly reclassifies (2,242 vs 154). The 3-stage decomposition is not just more detailed — it is more accurate as measured against the oracle.

---

## 2. Unknown-State Prevalence and Impact

### Measured prevalence (estimated from current LUCKY_FIX bucket)

Under the proposed `unknown` policy, events currently labeled as LUCKY_FIX (AST=incorrect, exec=pass) would become `unknown` if no anti-pattern is found.

**Overall unknown rate: 454 events (2.3%)**

### Per-family unknown rates

| Family | N | Unknown | Unknown% | Action |
|--------|---|---------|----------|--------|
| l3_state_pipeline | 659 | 229 | 34.7% | **Exclude from AST accuracy** — too many unknowns |
| use_before_set | 1,201 | 69 | 5.7% | Report but flag |
| index_misalign | 209 | 9 | 4.3% | Report but flag |
| temporal_drift | 1,064 | 38 | 3.6% | Acceptable |
| partial_rollback | 611 | 16 | 2.6% | Acceptable |
| All others | — | <2% each | — | Acceptable |

### At what unknown rate does AST become unreliable?

**Threshold: 10%.** If >10% of a family's events are `unknown`, the AST signal for that family is too noisy to drive conclusions. The family should be:
- Reported with an explicit unknown count
- Excluded from family-level AST accuracy claims
- Investigated for missing equivalence classes

Currently only l3_state_pipeline (34.7%) exceeds this. This is expected — it's a known partial-fix case where models keep `commit()` but remove `freeze_view()`.

### Reporting policy

| Context | How unknown is shown |
|---------|---------------------|
| Per-event tables | Separate column: `ast_alignment = correct / incorrect / unknown / unassessable` |
| Accuracy claims | Denominator = correct + incorrect only. Unknown excluded. Must state: "N events excluded as structurally indeterminate" |
| Family summaries | Show all four counts: N_correct, N_incorrect, N_unknown, N_unassessable |
| Model comparisons | Unknown rate shown per model. If model A has 5% unknown and model B has 1%, that's informative (A uses more novel approaches) |
| Paper figures | Unknown shown as a third bar or separate row, not lumped with incorrect |

### Unknown × execution interaction

| AST | Exec | Count (est.) | Label | Interpretation |
|-----|------|------|-------|----------------|
| unknown | pass | 454 | `alternative_candidate` | Likely valid novel repair. Promote to known patterns after manual review. |
| unknown | fail | ~0 (estimated) | `indeterminate_failure` | Cannot determine if failure is structural or semantic. Exclude from decomposition. |

The estimated unknown+fail count is near zero because the `unknown` state requires no anti-pattern AND target-function modification — if the model modified the right function and no bug pattern remains, it's unusual for execution to also fail. This will be validated empirically.

---

## 3. Execution Failure Labeling Protocol

### Categories (mutually exclusive, priority-ordered)

When labeling an AST-correct execution failure, apply the FIRST matching rule:

| Priority | Category | Rule | Source |
|----------|----------|------|--------|
| 1 | `import_failure` | `execution_category == "IMPORT_FAILURE"` | Automatic from exec_canonical |
| 2 | `name_scope_error` | `execution_category == "NAME_ERROR"` | Automatic from exec_canonical |
| 3 | `runtime_crash` | `execution_category == "INVARIANT_CRASH"` | Automatic from exec_canonical |
| 4 | `wrong_value_literal` | `failure_reasons` contains "expected" AND ("got" OR "!=") | Rule-based regex on failure text |
| 5 | `missing_attribute` | `failure_reasons` contains "not found" OR "has no attribute" | Rule-based regex |
| 6 | `unexpected_exception` | `failure_reasons` contains "raised" | Rule-based regex |
| 7 | `test_contract_mismatch` | `failure_reasons` contains "type" AND ("expected" OR "returned") | Rule-based regex |
| 8 | `unclassified_invariant` | None of the above match | Manual review required |

### Assignment method

- **Priorities 1-3:** Fully automatic from `execution_category`. Zero ambiguity.
- **Priorities 4-7:** Rule-based regex on `failure_reasons` text. Applied in priority order — first match wins.
- **Priority 8:** Events not matching any rule go to manual review.

### Manual review protocol (for `unclassified_invariant` events)

1. Read the failure_reasons text
2. Read the generated code (target function)
3. Read the test (tests_v2/test_{family}.py)
4. Classify as one of categories 4-7, or create a new sub-category with justification
5. Record: case_id, family, model, classification, confidence (high/medium/low), notes

**No inter-annotator agreement check required** for the initial decomposition (this is exploratory, not a labeling study). If the decomposition becomes a paper table, add a second annotator on a 50-event subsample.

### Preventing post-hoc interpretation bias

- Rules are applied BEFORE reading the generated code. The execution_category and failure_reasons determine the label, not the code content.
- Manual review is only for events that escape rule-based classification.
- The rule set is frozen before analysis begins. No adding rules after seeing results.
- Categories are descriptive (what went wrong) not causal (why the model failed).

### Expected distribution (from 1,046 prior sample)

| Category | Count | % | Method |
|----------|-------|---|--------|
| import_failure | 85 | 8.1% | Automatic |
| name_scope_error | 90 | 8.6% | Automatic |
| runtime_crash | 2 | 0.2% | Automatic |
| wrong_value_literal | 201 | 19.2% | Rule-based |
| unexpected_exception | 125 | 12.0% | Rule-based |
| unclassified_invariant | 543 | 51.9% | Manual review needed |

The 543 unclassified events (52%) are the priority for manual review. Of these, a 200-event stratified sample will be classified manually. The remainder will be estimated from the sample proportions.

---

## 4. AST vs Simple Structural Baseline Experiment

### Design

Compare four structural signals against the oracle as ground truth on the same 20,031-event dataset.

### Baselines

| Signal | What it checks | Cost to implement |
|--------|---------------|-------------------|
| **Execution only** | Did the code pass the test? | Zero (existing) |
| **Old classifier** | Did the LLM say mechanism_correct? | Zero (existing) |
| **Locus probe** | Did the model change the right file? (`def {func_name}` in `_extracted_code`) | 5 lines of code |
| **AST structural** | Full pattern matching (current system) | Existing |

### Metrics per signal

For each signal S and oracle O:

```
agreement(S, O) = P(S == O)
unique_correct(S) = events where S is correct and all other signals are wrong
false_positive(S) = P(S=correct | O=wrong)
false_negative(S) = P(S=wrong | O=correct)
```

### Measured results (from current data)

| Signal | Oracle agreement | Unique correct events | Net reclassification |
|--------|-----------------|----------------------|---------------------|
| Execution only | 84.4% | 0 (baseline) | — |
| Old classifier | 90.5% | N/A (different property) | — |
| AST structural | **93.4%** | **2,088 net** | +9.0pp over exec |

### Locus probe (to be measured)

The locus probe checks only: "Does the model's output contain a function definition matching `reference_fix.function`?" This is a 5-line check. If it achieves >90% oracle agreement, full AST pattern matching may be partially redundant for some families.

**Experiment:** Implement the locus probe, run on the 20,031-event dataset, compute oracle agreement. Compare per-family against full AST.

**Expected result:** Locus probe will agree with oracle at ~88-90% (above execution, below AST). The 3-5% gap between locus probe and full AST represents the value of pattern-level checking beyond simple "did the model touch the right function."

**Decision criterion:** If locus probe + execution achieves >92% oracle agreement, the incremental value of full AST pattern matching is <1.5pp, and the complexity may not be justified for low-gap families. If it achieves <90%, full AST is clearly justified.

### Per-family comparison design

For each family, compute:
```
value_of_full_AST = agreement(AST, oracle) - agreement(locus_probe, oracle)
```

Families where `value_of_full_AST < 2pp` may not need full pattern matching — the locus probe is sufficient. Families where it's >5pp clearly benefit from full AST.

---

## 5. Claim-Aware Verification: In or Out

### Decision: DEFER (Option 2)

**Rationale:**
1. 30% of current commitments are too vague for reliable claim mapping
2. Text-heuristic claim parsing (Option A) will produce noisy metrics with unknown false-alignment rate
3. The claim-aware signal's incremental value over truth-aware verification is unquantified
4. Implementing claim verification well requires either prompt changes (new experiments) or a robust NLU layer (engineering cost)
5. The paper's core contribution (execution-fidelity bottleneck) does not depend on claim-aware verification

**What this means for the plan:**
- Remove claim-aware verification from the main pipeline rollout
- Remove `ast_claim_alignment`, `claims_checked`, `claims_matched` from the result schema
- Keep the claim schema DESIGN (Section 2 of v3) as a documented future direction
- If claim verification is revisited, it should be a separate paper contribution with its own validation

**What remains:**
- `ast_truth_alignment` (patch vs canonical fix patterns)
- `ast_location_match` (did model change the right place)
- `ast_alternative_candidate` (novel repair detected)
- `checkability` (typed uncheckability level)

This reduces the result schema to 4 core fields plus status, which is simpler and every field is defensible.

---

## 6. Revised Core Analysis Framing

### The central axis: AST-correct execution failures

Everything connects to one number:

```
2,242 events where the model produced the correct structural fix
but execution still failed
```

This is 58.4% of all failures. It is measured on 20,031 oracle-labeled events. It is deterministic and reproducible.

### Why this matters

Without AST, these 2,242 events are invisible. They're lumped into "reasoning correct but execution fails" — which could mean the model got the reasoning right but the code wrong (structural failure) or the code right but the execution wrong (fidelity failure). AST separates these:

- 275 events: reasoning correct, structure wrong → **structural translation failure**
- 2,242 events: reasoning correct, structure correct, execution fails → **execution fidelity failure**

### The decomposition that AST enables

```
All failures (3,837)
├── Reasoning failure: 1,320 (34.4%)  — oracle says wrong
├── Structural translation failure: 275 (7.2%)  — oracle correct, AST incorrect
└── Execution fidelity failure: 2,242 (58.4%)  — oracle correct, AST correct, exec fails
    ├── Import/dependency: ~8%
    ├── Name/scope error: ~9%
    ├── Wrong value/literal: ~19%
    ├── Unexpected exception: ~12%
    └── Unclassified invariant: ~52% (manual decomposition needed)
```

### How interventions affect this axis

| Condition | Execution fidelity failures (% of assessable) |
|-----------|----------------------------------------------|
| baseline | 14.2% |
| lean | 9.8% |
| full LEG | 9.8% |
| retry_bare | 15.1% |
| retry_critique | 10.6% |
| **retry_reasoning_only** | **6.7%** |

Reasoning-only critique reduces execution fidelity failures from 14.2% to 6.7% — a 53% reduction. This is the paper's strongest intervention finding, and it is ONLY visible through the AST layer.

### How models differ on this axis

| Model | AST-correct exec-fail rate |
|-------|--------------------------|
| gpt-4o-mini | 28.4% |
| gpt-5 | 48.8% (small N) |
| claude-haiku-4.5 | 43.6% (small N) |
| gpt-4.1-nano | 4.1% |
| gpt-5-mini | 13.7% |
| gpt-5.4-mini | 10.4% |
| claude-sonnet-4.6 | 30.1% |
| claude-sonnet-4 | 0.0% |

### What the paper should frame

The paper contribution is NOT "we built an AST checker." The contribution is:

> Using deterministic structural verification, we decompose code generation failures into three stages — reasoning, structural translation, and execution fidelity — and show that 58% of failures occur at the execution stage, after correct reasoning and correct structure. This execution-fidelity gap is model-stratified, family-stratified, and intervention-responsive.

AST is the instrument. The decomposition is the finding. The execution-fidelity gap is the contribution.
