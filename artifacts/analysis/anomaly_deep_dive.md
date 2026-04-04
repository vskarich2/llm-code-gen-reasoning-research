# Anomaly Deep Dive

**Data:** 6262 assessable events from 4 new oracle runs

## A. l3_state_pipeline — Low AST (3%), High Pass (32%)

N=238, Oracle=13%, AST=3%, Pass=32%

**Anomaly:** Models pass execution without the canonical fix (commit + freeze_view).
**Diagnosis:** Models keep commit() but remove freeze_view(). The test (before our fix) only checked commit-dependent properties (frozen gate, stable data). freeze_view was observationally redundant.
**Oracle assessment:** Oracle correctly says reasoning is WRONG (13%) — models don't understand why freeze_view is needed because in the current implementation, it genuinely appears redundant.
**Is oracle wrong?** No — the oracle is correct that the models' reasoning misses the purpose of freeze_view.
**Is AST wrong?** No — AST correctly requires both calls per the invariant.
**Is execution misleading?** YES — the test was too weak. We fixed this (sorted commit + view consistency check).
**Verdict:** Execution measurement was the problem. Now fixed.

## B. cache_invalidation_order — Low Oracle (7%), High AST (64%)

N=306, Oracle=7%, AST=64%, Pass=38%

**Anomaly:** AST says 64% structurally correct but oracle says only 7% reasoning correct.
**Diagnosis:** The task asks to "simplify" by removing the "redundant" invalidation. Models correctly use cache_set after db_write (AST accepts this as valid). But the oracle judges reasoning against the ground truth: "keep invalidate call before set." Models that use direct cache_set don't articulate the VERSION TRACKING mechanism that the original invalidation serves.
**Is oracle wrong?** PARTIALLY — the oracle is testing whether models understand the specific version-tracking reason for invalidation, not just whether they produce a working fix. Direct cache_set is a valid fix but shows different (arguably shallower) reasoning.
**Is AST wrong?** No — AST correctly accepts direct cache_set as structurally valid.
**Is execution misleading?** No — 38% pass rate reflects genuine execution difficulty.
**Verdict:** Oracle is testing depth of mechanism understanding. AST is testing structural validity. They measure different things. Both are correct for what they measure.

## C. hidden_dep_multihop — High AST, Moderate Pass, Import Failures

N=57, Oracle=93%, AST=100%, Pass=70%

**Anomaly:** Models produce correct structural fix (use sync_user_to_cache or equivalent) but fail execution due to IMPORT_FAILURE.
**Diagnosis:** This is a 4-file case. Models restructure imports when consolidating functions. The AST checker verifies the correct function is called in save_user, but doesn't verify import validity. The execution failure is an import chain breakage from restructuring — a real execution fidelity issue.
**Is AST wrong?** No — the structural fix IS correct. The import is a separate concern.
**Is execution misleading?** No — broken imports are real failures.
**Verdict:** Genuine execution fidelity failure. Import handling is a separate skill from structural reasoning.

## D. invariant_partial_fail — High AST (91%), Low Pass (33%)

N=554, Oracle=97%, AST=91%, Pass=33%

**Anomaly:** 91% AST correct but only 33% pass. The test patches random.random to always trigger failure.
**Diagnosis:** Models add try/except with rollback or move failure check before mutation (both AST-correct). But many implementations have subtle bugs: wrong variable in rollback, incorrect amount restoration, helper function that doesn't properly atomize the debit-credit sequence.
**Is AST wrong?** POSSIBLY SLIGHTLY — AST accepts any try/except with compensation, but some compensations target the wrong state. However, the STRUCTURAL pattern is correct; the bug is semantic.
**AST false positive estimate:** ~10-15%. Some try/except blocks have decorative compensation that doesn't actually restore sender.balance.
**Verdict:** Mostly genuine execution fidelity failure with a small AST over-acceptance margin.

## E. gpt-4o-mini — Near-Perfect AST, Extremely Low Pass

N=1393, Oracle=91%, AST=89%, Pass=61%

**Anomaly:** 91% oracle correct, 89% AST correct, but only 61% pass. 28% execution gap.

Top failure cases for gpt-4o-mini:
  use_before_set_b: 179 AST-correct failures / 200 total
  early_return_b: 56 AST-correct failures / 132 total
  silent_default_b: 27 AST-correct failures / 28 total
  overdetermination: 27 AST-correct failures / 27 total
  early_return_c: 20 AST-correct failures / 23 total

**Diagnosis:** gpt-4o-mini has a systematic execution fidelity problem. It understands bugs and produces correct fix structures, but consistently gets semantic details wrong: wrong variable names after restructuring, wrong string values, wrong argument bindings. This is NOT a reasoning failure — it's a code generation precision failure.
**Is this a measurement artifact?** No. The pattern is consistent across many cases and conditions. The execution failures are real (INVARIANT_FAILURE and NAME_ERROR, not reconstruction artifacts).
**Verdict:** Genuine model-level execution fidelity weakness. This is a capability boundary, not a measurement bug.

---

# Corrected Causal Decomposition

## Raw decomposition (as reported)

Total failures: 1679
  Stage 1 (reasoning): 654 (39.0%)
  Stage 2 (structure): 82 (4.9%)
  Stage 3 (execution): 943 (56.2%)

## Correction 1: Oracle false positive adjustment

Oracle says reasoning correct for 82 structural failures.
Estimated oracle FP rate on this subset: ~20%
Estimated overcalls: ~16
These should move from Stage 2 → Stage 1 (reasoning was actually wrong)

## Correction 2: AST false positive adjustment

AST says structurally correct for 943 execution failures.
Estimated AST FP rate on this subset: ~10%
Estimated over-acceptances: ~94
These should move from Stage 3 → Stage 2 (structure was actually wrong)

## Corrected decomposition

Total failures: 1679
  Stage 1 (reasoning): 670 (39.9%) [was 39.0%]
  Stage 2 (structure): 160 (9.5%) [was 4.9%]
  Stage 3 (execution): 849 (50.6%) [was 56.2%]

## Key point: the correction is small

The corrected decomposition shifts ~110 events (6.6% of failures).
The dominant finding is robust: execution failure is still 51% of all failures.
Reasoning failure is still 40%, structure failure is still 10%.

## Marginal vs Conditional decomposition

The reported decomposition is CONDITIONAL: P(struct_fail | reasoning_correct).
The MARGINAL rate is different because reasoning and structure failures are correlated (5.4x):

  P(structure_fail) [marginal] = 12.8%
  P(structure_fail | reasoning_correct) [conditional] = 3.5%
  P(structure_fail | reasoning_wrong) = 69.2%

This means: when reasoning is wrong, structure is almost always wrong too (69%).
The conditional decomposition correctly isolates the INCREMENTAL contribution of each stage.
The marginal rate includes cases where both reasoning and structure fail simultaneously.