# Instrument Validation Summary

**Date:** 2026-04-03
**Data:** 6262 assessable events with oracle + AST + execution labels

---

## A. Oracle Reliability

**What it measures:** Whether the model's verbal reasoning (root_cause + fix_strategy) correctly identifies the bug mechanism, judged by gpt-5-mini with access to ground truth.

**Reliability assessment:**
- Oracle agrees with AST on 82.8% of events (joint OK or joint wrong)
- Oracle says correct + AST says wrong: 190 events (3.0%)
  - Of these, 108 (57%) pass execution → oracle is right, AST is too strict
  - 82 (43%) fail execution → either true reasoning-structure gap (~80%) or oracle overcall (~20%)
- Estimated oracle false positive rate: ~0.3% of all events, ~20% of the oracle=T/ast=F/exec=F subset

**Weaknesses:**
- Oracle tests depth of mechanism understanding, not just correctness. cache_invalidation_order shows 7% oracle correct but 64% AST correct — models find valid fixes without articulating the full mechanism.
- Oracle is an LLM judge (gpt-5-mini). It may have its own biases, particularly on complex cases.
- PARTIAL label is ambiguous — lumped with CORRECT in our analysis.

**Verdict:** Oracle is a reasonably reliable measure of trace-level reasoning. False positive rate is low (~0.3% overall). Main limitation is that it tests mechanism articulation depth, not just fix correctness.

## B. AST Reliability

**What it measures:** Whether the model's generated code contains the structural fix pattern that satisfies the case invariant.

**Reliability assessment:**
- AST correct rate: 87.2%
- 1,046 events where AST=correct but execution fails
  - 85% are INVARIANT_FAILURE (correct structure, wrong semantic details)
  - 9% are NAME_ERROR (correct structure, broken references)
  - 5% are IMPORT_FAILURE (correct structure, broken imports)
- Estimated AST false positive rate: ~10% of AST-correct failures
  - Some try/except blocks have decorative compensation (invariant_partial_fail)
  - Some name-error cases may reflect structural issues the checker misses

**Weaknesses:**
- AST cannot verify semantic correctness within correct structure (wrong values, wrong bindings)
- AST is pattern-based, not invariant-proving. It checks necessary conditions, not sufficient conditions.
- 11 cases are not AST-measurable (lock ordering, atomicity, literal values)
- Relaxed equivalence classes may still miss some valid alternatives (2% lucky fix rate)

**Verdict:** AST is a reliable structural proxy with ~10% over-acceptance rate on execution-failing events. It correctly identifies structural intent but cannot verify semantic precision.

## C. Execution Reliability

**What it measures:** Whether the model's code passes the invariant test when run in a subprocess.

**Reliability assessment:**
- Execution is the behavioral ground truth — it tests actual code behavior
- No known false positives (tests are deterministic with fixed random seeds)
- Possible false negatives: l3_state_pipeline test was too weak (now fixed)
- Execution failures are real: INVARIANT_FAILURE (wrong output), NAME_ERROR (undefined variable), IMPORT_FAILURE (broken imports)

**Weaknesses:**
- Test surface may not cover all invariant properties (l3_state_pipeline was missing freeze_view check)
- Reconstruction artifacts can prevent execution of otherwise correct code (3,004 unassessable events)
- Multi-file cases are more prone to import/scoping failures that are pipeline issues, not model issues

**Verdict:** Execution is the most reliable of the three instruments. Main risk is test-surface incompleteness, which we've partially addressed.

## D. Remaining Uncertainties

1. **Oracle-AST correlation (5.4x):** When oracle is wrong, AST is usually wrong too. This means the conditional decomposition underestimates structure failure by 3.6x compared to the marginal rate. The decomposition is correct as conditional, but readers must not interpret it as marginal.
2. **AST over-acceptance on invariant_partial_fail:** ~10-15% of AST-correct events for this case may have decorative try/except that doesn't truly compensate. This inflates Stage 3 by ~5% for this case.
3. **Oracle depth sensitivity:** Oracle tests mechanism articulation depth, which varies by case. cache_invalidation_order shows valid fixes with low oracle scores because the reasoning path is different from the ground truth, not wrong.
4. **PARTIAL label handling:** We lump PARTIAL with CORRECT. If PARTIAL were treated as wrong, oracle correct rate would drop by ~5-10%.
5. **Test coverage:** Only l3_state_pipeline had a confirmed test gap. Others are likely complete but not audited.

## E. Confidence in Current Metrics

| Metric | Confidence | Main risk | Estimated bias |
|--------|-----------|-----------|---------------|
| P(oracle_correct) = 85.8% | HIGH | Oracle overcall on shallow-but-valid reasoning | +0.3% overestimate |
| P(ast_correct) = 87.2% | HIGH | AST over-acceptance of decorative patterns | +1-2% overestimate |
| P(exec_pass) = 73.2% | VERY HIGH | Test incompleteness (1 case fixed) | ~0% bias |
| P(exec_fail\|ast_correct) = 15.1% | HIGH | AST FP inflates denominator slightly | Overestimate by ~1-2pp |
| Execution gap = 56.2% of failures | MODERATE-HIGH | Oracle-AST correlation inflates Stage 3 relative to marginal | Conditional is correct; marginal would be different |

**Bottom line:** All three instruments are sufficiently reliable for the core claim. The corrected decomposition shifts <2% of failures between stages. The dominant finding — execution fidelity is the primary bottleneck — is robust to all corrections tested.