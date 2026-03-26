# Fix Plan: Reasoning Evaluator — Measurement Repair

**Version:** v5 (FINAL)
**Date:** 2026-03-26
**Status:** Plan complete. Execution blocked until Go/No-Go checklist (Section 17) is satisfied.
**Supersedes:** fix_reasoning_evaluator_v4.md
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## CHANGELOG (v4 -> v5)

| Change | What | Rationale |
|---|---|---|
| Added Section 17 | Go/No-Go checklist: 12-item prerequisite list that must ALL be true before execution begins | Prevents starting execution with missing infrastructure |
| Added Section 8.10 | Plan compliance verification: pre-phase and post-phase checklists enforced programmatically | Prevents drift between plan and execution |
| Added Section 8.11 | Holdout case set: 8 cases reserved exclusively for Phase 4, never used in Phase 0 annotation or hypothesis testing | Prevents overfitting fixes to validation cases |
| Added Section 8.12 | Cost protection: canary runs before large experiments, hard budget caps, automatic abort on validation failure | Prevents wasting API spend on broken pipelines |

All v4 constraints are preserved unchanged.

---

## PART I: MEASUREMENT REPAIR

### 1. Executive Summary

**All cross-condition reasoning comparisons produced by this system are currently invalid.** The reasoning evaluator (`evaluator.py:llm_classify`) is not format-invariant. The same model reasoning expressed in baseline freeform format and LEG structured format receives systematically different classifier verdicts. This is a structural defect, not a suspected bias.

Three independent pathologies contribute:

1. **H1 — Classifier brevity bias**: The LLM judge penalizes short reasoning even when semantically correct.
2. **H2 — Reasoning information loss**: The LEG-reduction condition maps only `bug_diagnosis` (one sentence) to the classifier's `reasoning` input, discarding plan_steps, revision_history, verification, and invariants_checked.
3. **H3 — Parse failure corruption**: When parsing fails, `reasoning=""` reaches the classifier, which produces `reasoning_correct=False` instead of `None`, injecting false negatives.

Additionally, evaluator.py:171 hard-codes `model = "gpt-5.4-mini"`, ignoring the `eval_model` parameter.

**Until these defects are characterized and repaired:**
- LEG rate, true_success rate, and reasoning_action_gap are unreliable for all non-baseline conditions.
- No paper-quality claim about reasoning correctness differences across conditions is supportable.
- Baseline-only results are unaffected by H2/H3 but remain subject to H1.

### 2. Measurement Invariance Statement

> Two reasoning inputs that are semantically equivalent under the E1-E3 rubric (Section 5) MUST produce identical classification outcomes, regardless of surface format, length, or structural representation.

This is a measurement invariant, not a design goal. Any evaluator that violates it produces invalid cross-condition comparisons. Enforced as a permanent regression test (Section 16.1) using minimal reproducible cases (Section 8.6).

### 3. Unconditional Correctness Fixes

Applied immediately, before hypothesis testing. These are verified bugs.

**Fix D — Parse Recovery Gate**: Return `reasoning_correct=None` instead of `False` when reasoning is lost (per taxonomy in Section 7).

**Fix E — eval_model Parameter Bug**: Replace `model = "gpt-5.4-mini"` on evaluator.py:171 with `model = eval_model or "gpt-5.4-mini"`. Log `eval_model_actual` in every result.

---

## PART II: HYPOTHESIS VALIDATION

### 4. Hypotheses and Falsification Experiments

#### H1: Classifier Brevity Bias

**Claim**: The classifier produces systematically lower `reasoning_correct=True` rates for semantically equivalent reasoning in shorter form.

**Experiment P0-1**: 15 cases (from Phase 0 case set — NOT holdout) where baseline `reasoning_correct=YES`. Create three compressions per case (A: first sentence, B: manual one-sentence summary, C: actual LEG bug_diagnosis). Run classifier on all 4 versions.

**CONFIRMED**: >= 5/15 flip YES->NO while E1-E3 preserved.
**FALSIFIED**: <= 2/15 flip.
**INCONCLUSIVE**: 3-4/15. Expand to 25 (cycle 1). Hard cap: 2 refinement cycles. After cap: accept as CONFIRMED if >= 4/25, FALSIFIED if < 4/25, or UNRESOLVABLE (treat as confirmed).

**Controls**:
- P0-2: 5 terse-correct summaries. ALL must classify YES. Any NO: **classifier disqualified** (Section 8.8).
- P0-3: 5 verbose-wrong paragraphs. ALL must classify NO. Any YES: **classifier disqualified**.

#### H2: Reasoning Information Loss

**Claim**: LEG-to-classifier mapping discards causal elements required for YES.

**Experiment P0-4/P0-5**: 10 LEG cases (from Phase 0 case set). Annotate E1-E4 for bug_diagnosis alone vs full LEG. Run classifier on bug_diagnosis-only vs +issues_found.

**CONFIRMED**: diag < full on E1-E3 in >= 7/10, AND >= 6/10 flip NO->YES.
**FALSIFIED**: diag has E1-E3 in >= 8/10, or < 3/10 flip.
**INCONCLUSIVE**: Expand to 20 with second annotator (cycle 1). Cap: 2 cycles.

#### H3: Parse Failure Corruption

**Claim**: Parse failures inject false negatives via reasoning="".

**Experiment P0-6/P0-7**: Census of parse failures per condition in existing data. Raw inspection of REASONING_LOST cases.

**CONFIRMED**: >= 5% in any non-baseline condition with reasoning lost.
**FALSIFIED**: < 1% everywhere.
**INCONCLUSIVE**: 1-5%. Inspect all cases (cycle 1). Cap: 2 cycles.

#### P0-0: eval_model Isolation (PREREQUISITE ZERO)

Locked audit set with hard-coded model vs intended eval_model. Label-by-label. If > 5 flips: all experiments dual-report.

#### P0-PROMPT: Prompt Sensitivity

10 cases x 2 prompt phrasings. If > 1/10 differ: classifier is prompt-sensitive, factor into analysis.

---

### 5. Semantic Completeness Rubric

#### 5.1 Elements

| Element | Definition | Example (alias_config_a) |
|---|---|---|
| **E1: Root Cause** | Names the specific defect | "create_config returns DEFAULTS by reference" |
| **E2: Manifestation Path** | HOW the bug produces failure | "Caller mutations corrupt global state" |
| **E3: Invariant or Mechanism** | Violated principle | "Aliasing: shared mutable reference" |
| **E4: Fix Rationale** (optional) | Why the fix works | "dict(DEFAULTS) creates independent copy" |

#### 5.2 Annotation Protocol

Annotate baseline reasoning, LEG bug_diagnosis, and full LEG output for E1-E4 (binary).

#### 5.3 Inter-Rater Reliability

**Primary annotator**: Re-labels 5-case subset on separate day. Self-consistency >= 90%.
**Second annotator**: Same 5 cases independently. Inter-annotator agreement >= 85%.

If self-consistency < 90%: refine rubric, re-annotate.
If inter-annotator < 85%: log disagreements, resolve by discussion. If > 2/5 change: re-annotate with clarified rubric. If < 85% after clarification: H2 conclusions downgraded to "suggestive."

---

### 6. Candidate Fixes

#### 6.1 Prohibited and Permitted Fields

**HARD RULE**: `plan_steps` and `verification` evidence excluded from primary reasoning input. Solution-level information.

**Permitted** (subject to leakage audit 8.9): `bug_diagnosis`, `issues_found[].description/evidence`, `invariants_checked[].invariant` (FAIL only).

If >= 3/10 enrichment flips show leakage (8.9): issues_found and invariants also excluded. Fix A rejected. Fix C only.

#### 6.2 Fix A: Enriched Reasoning (FALLBACK ONLY)

Concatenate permitted fields. Baseline pass-through. Risk: HIGH (asymmetry). Permitted only if Fix C fails Phase 1.

#### 6.3 Fix B: Classifier Prompt Redesign

Risk: MEDIUM-HIGH. Changes all conditions.

#### 6.4 Fix C: Normalized Intermediate Representation (PRIMARY PATH)

Canonical slots: `root_cause` (E1), `manifestation` (E2), `mechanism_or_invariant` (E3), `evidence`. fix_rationale EXCLUDED.

**LEG mapping**: direct.
**Baseline mapping**: rule-based FIRST -> LLM fallback on empty E1/E2 -> raw passthrough if both fail.

**Extraction failure criteria**: Rule-based empty root_cause in > 2/10 locked audit = broken. LLM fallback empty root_cause in > 1/10 = broken. Both broken: Fix C cannot proceed, fall back to Fix A with full Phase 4.

#### 6.5 Fix D: Parse Gate (UNCONDITIONAL)

#### 6.6 Fix E: eval_model Bug (UNCONDITIONAL)

---

### 7. Parse Failure Taxonomy

Six categories: CLEAN, PARTIAL_JSON_RECOVERED, MALFORMED_BUT_RECOVERED, REASONING_LOST, CODE_LOST, STRUCTURE_MISSING.

REASONING_LOST/CODE_LOST/STRUCTURE_MISSING: classification disallowed, reasoning_correct=None.
PARTIAL_JSON/MALFORMED_BUT_RECOVERED: classification allowed with flag.
Heuristic recovery: NEVER in primary metrics.

---

## PART III: EXPERIMENTAL RESULTS AND VALIDATION

### 8. Validation Matrix

#### 8.1 Phase 0 Experiments (BLOCKING GATE)

| ID | Experiment | Confirms if | Falsifies if |
|---|---|---|---|
| P0-0 | eval_model isolation (30 cases x 2 models) | Drift quantified | N/A |
| P0-1 | H1 Brevity (15 cases x 4 compressions) | >= 5/15 flip | <= 2/15 flip |
| P0-2 | H1 Neg: terse-correct (5 cases) | All YES | Any NO: **disqualify** |
| P0-3 | H1 Neg: verbose-wrong (5 cases) | All NO | Any YES: **disqualify** |
| P0-4 | H2 Semantic annotation (10 LEG cases) | diag < full >= 7/10 | diag == full >= 8/10 |
| P0-5 | H2 Classifier effect (10 cases) | >= 6/10 flip | < 3/10 flip |
| P0-6 | H3 Parse census | >= 5% any condition | < 1% everywhere |
| P0-7 | H3 Raw inspection | Raw has reasoning | Raw empty |
| P0-PROMPT | Prompt sensitivity (10 x 2 prompts) | Quantified | N/A |
| P0-STAB | Stochastic stability (20 x 3 runs, temp=0) | 100% consistent | Any inconsistency |

#### 8.2 Phase 0 Exit Conditions (BLOCKING)

1. **Refinement cap**: Max TWO cycles per hypothesis. After cap: accept or UNRESOLVABLE (treat confirmed).
2. **Control failure**: P0-2 or P0-3 fails -> classifier disqualified -> Section 8.8.
3. **Every verdict cites experiment ID + numeric result.** Prose-only conclusions forbidden.
4. **P0-0 > 5 flips**: dual-report all experiments.

#### 8.3 Audit Logging (MANDATORY)

Every case in every experiment must have ALL fields:

`experiment_id`, `case_id`, `condition`, `raw_model_output`, `parsed_reasoning`, `enriched_reasoning`, `normalized_representation`, `extraction_method`, `extraction_failed`, `parse_error`, `parse_category`, `recovery_method`, `classifier_prompt`, `classifier_raw_output`, `classifier_verdict`, `classifier_failure_type`, `classifier_parse_error`, `eval_model_intended`, `eval_model_actual`, `semantic_elements`.

**Any experiment without complete logs is automatically invalid. No exceptions.**

#### 8.4 Stop Conditions (Hard Abort)

| Condition | Action |
|---|---|
| > 1/10 known-good YES flip to NO | Abort change |
| > 1/10 known-good NO flip to YES | Abort change |
| Enriched-vs-raw disagreement > 30% on baseline | Abort enrichment |
| Locked audit drift > 1 justified flip | Abort rollout |
| Unclassified > 20% any condition | Fix parsing first |
| verbose-wrong YES after fix | **Disqualify classifier** |
| terse-correct NO after fix | **Disqualify classifier** |
| Both evaluators disagree with rubric > 20% audited | **Both unreliable** -> 8.8 |
| Holdout cases disagree with Phase 0 cases by > 15pp | Fix is overfit -> reject |

#### 8.5 Stochastic Stability

20 cases x 3 runs at temperature=0. Required: **100% consistency**.

If any case varies at temp=0: verify temperature (inspect API call kwargs). If confirmed unstable: **mandatory majority voting** (3 calls per classification, majority wins). Non-negotiable.

#### 8.6 Minimal Reproducible Cases

For each confirmed hypothesis:
- **H1 minimal**: case_id + R_full (YES) + R_short (same E1-E3, NO).
- **H2 minimal**: case_id + bug_diagnosis (NO) + bug_diagnosis+issues_found (YES).
- **H3 minimal**: raw output with reasoning + parse error causing reasoning="" + False verdict.

Ground truth anchors. ALL regression tests (Section 16) reference these. Breakage = immediate test failure.

#### 8.7 Disagreement Taxonomy (Phase 4)

| Category | Definition |
|---|---|
| PARSE_RELATED | Old: empty reasoning -> NO. New: gated -> None. |
| BREVITY_RELATED | Same text, different verdict from prompt/length sensitivity |
| INFORMATION_RELATED | New has additional content old did not |
| FORMAT_DEPENDENT_PROMPT_FAILURE | Same semantics, different verdict from prompt phrasing |
| CLASSIFIER_ERROR | Neither verdict matches rubric |

Every audited disagreement: exactly one category.

#### 8.8 Classifier Disqualification

**Hard trigger**: ANY control fails after fixes. No further tuning.

1. Hybrid: LLM + rule-based E1-E3 keyword verification.
2. If hybrid fails: purely rule-based.
3. If rule-based too coarse: abandon automated reasoning classification. code_correct only.

#### 8.9 Enrichment Leakage Audit

Every NO->YES flip from enrichment: inspect for fix hints, success markers, code-level solutions.

Classify each: MECHANISM_RECOVERY (legitimate) or SOLUTION_LEAKAGE (illegitimate).

>= 3/10 SOLUTION_LEAKAGE: enrichment rejected. Fix A dead. Fix C only.

#### 8.10 Plan Compliance Verification

##### Pre-Phase Checklists

Before EACH phase begins, the following must be verified. Verification is either programmatic (automated check) or manual (explicit sign-off logged to file).

**Pre-Phase 0 Checklist** (verified before any P0 experiment runs):

| # | Item | Verification Method |
|---|---|---|
| 1 | eval_model bug fixed (line 171 uses eval_model parameter) | Programmatic: grep evaluator.py for hard-coded model, assert absent |
| 2 | Parse gate active (REASONING_LOST -> None, not False) | Programmatic: unit test passes |
| 3 | All 20 audit log fields present in logging code | Programmatic: unit test creates a mock evaluation, asserts all fields exist |
| 4 | temperature=0 confirmed in classifier API call | Programmatic: inspect call_model kwargs in test, assert temperature=0 |
| 5 | Locked audit set defined (30 cases, file exists, stratification verified) | Manual: file exists at `audit/locked_audit_set.json`, spot-check 5 entries |
| 6 | Holdout set defined (8 cases, file exists, no overlap with Phase 0 set) | Programmatic: load both files, assert intersection is empty |
| 7 | Phase 0 case set defined (remaining cases excluding holdout) | Programmatic: union of Phase 0 + holdout == full benchmark |
| 8 | Minimal reproducible case templates prepared (empty, to be filled) | Manual: template files exist at `audit/minimal_cases/` |
| 9 | Canary run script exists and validates parsing, reasoning, logging | Programmatic: script exists and runs on 1 mock case without error |
| 10 | Budget cap defined for Phase 0 | Manual: value recorded in `audit/budget.json` |

**Pre-Phase 1 Checklist**:

| # | Item | Verification Method |
|---|---|---|
| 1 | Phase 0 report delivered with all hypothesis verdicts | Manual: file exists, all 3 verdicts present |
| 2 | All P0 experiments (P0-0 through P0-7, P0-PROMPT, P0-STAB) have complete logs | Programmatic: count log records per experiment, assert >= expected |
| 3 | Minimal reproducible cases filled for each confirmed hypothesis | Manual: non-empty files in `audit/minimal_cases/` |
| 4 | Inter-rater annotation complete with agreement >= 85% | Manual: agreement score recorded in Phase 0 report |
| 5 | No control failures (P0-2, P0-3 all passed) | Programmatic: parse Phase 0 results, assert controls passed |

**Pre-Phase 4 Checklist**:

| # | Item | Verification Method |
|---|---|---|
| 1 | Phase 1 report delivered with label-level comparison | Manual: file exists |
| 2 | All stop conditions from Phase 1 passed | Manual: documented in Phase 1 report |
| 3 | Canary run (5 cases) completed successfully | Programmatic: canary output validated |
| 4 | Budget cap defined for Phase 4 | Manual: value in `audit/budget.json` |
| 5 | Holdout cases verified not used in any prior phase | Programmatic: scan all Phase 0/1 logs, assert no holdout case_ids |

##### Post-Phase Checklists

After EACH phase completes, verify completeness before proceeding.

**Post-Phase 0 Checklist**:

| # | Item |
|---|---|
| 1 | Every required experiment (P0-0 through P0-7, P0-PROMPT, P0-STAB) has a results entry |
| 2 | Every results entry has complete audit logs (spot-check 3 random cases per experiment: all 20 fields present) |
| 3 | Phase 0 report contains a verdict table: H1/H2/H3 each marked CONFIRMED/FALSIFIED/UNRESOLVABLE |
| 4 | Each verdict cites experiment ID and numeric threshold |
| 5 | If any refinement cycles were used: documented with cycle count |
| 6 | Controls (P0-2, P0-3) results explicitly recorded |

**If ANY item fails**: Phase 0 is incomplete. Re-run missing components. Do NOT proceed.

**Post-Phase 4 Checklist**:

| # | Item |
|---|---|
| 1 | Dual scores logged for every case (old + new) |
| 2 | Disagreement taxonomy applied to audited sample |
| 3 | Holdout cases evaluated and compared to Phase 0 cases |
| 4 | Budget cap not exceeded |
| 5 | Phase 4 report delivered |

#### 8.11 Holdout Case Set

**Purpose**: Detect overfitting of evaluator fixes to Phase 0 validation cases.

**Construction**: Reserve 8 cases (approximately 14% of the 58-case benchmark) that are NEVER used in:
- Phase 0 hypothesis experiments (P0-1 through P0-7)
- Semantic completeness annotation
- Locked audit set
- Minimal reproducible case construction

Holdout cases are stratified: at least 2 difficulty levels, at least 3 failure modes.

**Usage**: Holdout cases are evaluated ONLY in Phase 4 shadow run. After Phase 4:

1. Compute per-condition disagreement rate on holdout cases separately.
2. Compute per-condition disagreement rate on non-holdout cases separately.
3. Compare the two rates.

**Overfit detection rule**: If the disagreement rate on holdout cases differs from non-holdout cases by > 15 percentage points (in either direction), the fix is overfit to the validation set. This triggers a **hard stop**: the fix must be re-examined. Possible actions:
- If holdout disagreement is higher: the fix works on familiar cases but not on unseen ones. Likely overfit.
- If holdout disagreement is lower: the fix works better on unseen cases than familiar ones. Unusual but possible; investigate before proceeding.

**Enforcement**: A programmatic check verifies that no holdout case_id appears in any Phase 0 or Phase 1 log file. If contamination is detected, the affected phase is invalid.

#### 8.12 Cost Protection

##### Canary Runs

Before ANY large experiment (defined as > 20 API calls), execute a canary run of 3-5 cases across the relevant conditions. The canary validates:

| Check | Pass Criteria | Abort if |
|---|---|---|
| Parsing works | parsed_reasoning is non-empty for >= 4/5 cases | < 3/5 non-empty |
| Classifier responds | classifier_raw_output is non-empty for all cases | Any empty |
| Classifier parses | classifier_verdict is YES or NO (not None) for >= 4/5 | < 3/5 parsed |
| Logging complete | All 20 audit fields present for all cases | Any field missing |
| eval_model correct | eval_model_actual == eval_model_intended for all cases | Any mismatch |

If ANY check fails: abort the large run immediately. Fix the issue. Re-run canary. Do not proceed until canary passes.

##### Budget Caps

| Phase | Max API Calls | Approximate Cost Ceiling |
|---|---|---|
| Phase 0 (all experiments) | 500 | Defined before execution in `audit/budget.json` |
| Phase 1 (offline experiments) | 300 | Defined before execution |
| Phase 4 (shadow run: 58 cases x conditions x 2 evaluators) | 1500 | Defined before execution |

These caps are recorded in `audit/budget.json` before each phase begins. If a phase exceeds its cap, execution stops automatically. The partially-completed results are preserved but the phase is marked INCOMPLETE and must be reviewed before proceeding.

**Implementation**: The experiment runner tracks cumulative API calls and checks against the cap before each call. If `current_calls >= cap`, raise a hard error.

##### Cost Logging

Every API call logs: `timestamp`, `model`, `prompt_tokens_est`, `purpose` (classifier, generation, extraction). At the end of each phase, total calls and estimated cost are reported.

---

### 9. Backward Compatibility

#### 9.1 Locked Audit Set

30 baseline cases, stratified. At least 5 v2-only. 15 YES, 15 NO. No overlap with holdout set.

#### 9.2 Label-Level Stability

ALL 30 match: confirmed. 1 flip: justified. 2-3: each justified individually. > 3: abort.

---

### 10. Denominator and Reporting Policy

#### 10.1 Rate Computations

N_total, N_classified, N_unclassified, N_parse_failed, N_recovered. All rates use N_classified as denominator.

#### 10.2 Mandatory Rules

Every table includes all five N columns. > 10pp unclassified gap between compared conditions: comparison EXCLUDED from all figures, tables, and claims.

#### 10.3 None Handling

None excluded from rates. Never counted as False. Always reported.

---

### 11. Decision Framework

| H1 | H2 | H3 | Fix Path |
|---|---|---|---|
| CONFIRMED | FALSIFIED | Any | Fix B or Fix C |
| FALSIFIED | CONFIRMED | Any | Fix C primary. Fix A fallback only if Fix C fails. |
| CONFIRMED | CONFIRMED | Any | Fix C (only symmetric fix) |
| FALSIFIED | FALSIFIED | CONFIRMED | Fix D only |
| CONFIRMED | CONFIRMED | CONFIRMED | Fix D first, Fix E, then Fix C |
| ALL FALSIFIED | | | Null-result report |
| Any UNRESOLVABLE | | | Treat confirmed. Fix C. |

Fix D and Fix E: unconditional. Fix C: primary. Fix A: last resort.

---

### 12. Rollout Phases

#### Phase 0: Measurement Audit (BLOCKING GATE)

1. Verify Pre-Phase 0 Checklist (Section 8.10).
2. Fix eval_model bug, apply parse gate.
3. Run canary (3 cases) to validate infrastructure.
4. Run P0-0, P0-PROMPT, P0-STAB.
5. Run P0-1 through P0-7.
6. Semantic annotation with inter-rater check.
7. Construct minimal reproducible cases.
8. Verify Post-Phase 0 Checklist.
9. Deliver Phase 0 report.

**Gate**: All hypotheses resolved. All controls pass. Stability verified. Post-checklist complete.

#### Phase 1: Offline Experiments

1. Verify Pre-Phase 1 Checklist.
2. Select fix per decision framework.
3. Implement behind flag.
4. Run canary (5 cases) to validate new evaluator path.
5. Locked audit set comparison.
6. All controls.
7. Stability test.
8. Fix C extraction validation.
9. P1-LEAK-ISSUES audit.
10. Deliver Phase 1 report.

**Gate**: Drift <= 1 justified flip. Controls pass. Stability 100%. Extraction meets criteria.

#### Phase 2: Choose Fix

Review reports. Select. Document citing experiment IDs.

#### Phase 3: Implement Behind Flag

Default OFF. Both paths active when ON. Fix D ON by default.

#### Phase 4: Dual-Score Shadow Run (MANDATORY)

1. Verify Pre-Phase 4 Checklist.
2. Run canary (5 cases, dual scoring) to validate.
3. 58 cases x conditions x 1 trial, dual scoring.
4. Holdout cases evaluated (first time).
5. Per-condition disagreement rates.
6. Scaled audit: <= 20% disagreement -> 10/condition. > 20% -> 20/condition.
7. Disagreement taxonomy.
8. Holdout vs non-holdout comparison (overfit check).
9. Verify Post-Phase 4 Checklist.
10. Deliver Phase 4 report.

**Gate**: Directionally correct >= 80%. Locked set stable. Controls pass. Holdout within 15pp. Budget not exceeded.

#### Phase 5: Switch Primary Metric

Only if Phase 4 passes all gates. Switch. Archive. Document.

---

### 13. Do Not Do

1. Do NOT classify empty reasoning as incorrect. None, not False.
2. Do NOT switch production metric without Phase 4 shadow run.
3. Do NOT change classifier prompt AND input format simultaneously.
4. Do NOT fold heuristic recovery into primary metrics.
5. Do NOT accept aggregate improvement if label audit shows > 1 unjustified flip.
6. Do NOT assume baseline and LEG rates must converge.
7. Do NOT include plan_steps or verification in primary reasoning input.
8. Do NOT leave eval_model hard-coded during any experiment.
9. Do NOT run experiments without complete audit logs.
10. Do NOT skip semantic annotation or inter-rater check.
11. Do NOT proceed phases without satisfying both pre-checklist and post-checklist.
12. Do NOT report comparisons with > 10pp unclassified gap anywhere.
13. Do NOT iterate on classifier prompts after control failure. Disqualify and replace.
14. Do NOT use unstable classifier (non-100% at temp=0) without mandatory voting.
15. Do NOT use holdout cases in Phase 0 or Phase 1. Holdout is for Phase 4 only.
16. Do NOT proceed with a large run without a passing canary.

---

### 14. Metrics for Success

| Metric | Target | Type |
|---|---|---|
| Format invariance (minimal cases) | 100% same verdict on E1-E3 equivalent inputs | Invariant |
| Parse false negative rate | 0% | Correctness |
| Locked audit drift (30 cases) | <= 1 justified flip | Stability |
| Shadow disagreement: directionally correct | >= 80% audited flips | Quality |
| Holdout vs non-holdout disagreement gap | <= 15pp | Generalization |
| Unclassified rate | Reported; > 10pp gap invalidates comparison | Transparency |
| verbose-wrong controls | 100% NO | Safety |
| terse-correct controls | 100% YES | Safety |
| Stochastic stability at temp=0 | 100% | Reliability |
| Inter-rater agreement | >= 85% | Rubric validity |
| Canary pass rate | 100% before every large run | Infrastructure |

Gap convergence is NOT a success criterion.

---

### 15. Risk Analysis

#### 15.1 Enrichment Asymmetry
Fix A creates asymmetry. Fix C eliminates it. Fix A is fallback only.

#### 15.2 Extraction Errors
Rule-based first, LLM fallback, raw passthrough. Failure criteria defined.

#### 15.3 Classifier Model Sensitivity
P0-0 quantifies. Dual-report if high.

#### 15.4 Denominator Asymmetry
10pp rule. Invalid comparisons excluded from all outputs.

#### 15.5 Overfitting
Holdout set (8 cases) detects. 15pp threshold rejects overfit fixes.

#### 15.6 Classifier Unreliability
Disqualification trigger. Three-tier contingency.

#### 15.7 Implementation Drift
Pre-phase and post-phase checklists. Programmatic verification. No partial execution.

#### 15.8 Cost Overrun
Canary runs. Budget caps. Automatic abort.

---

### 16. Permanent Regression Tests

ALL tests reference minimal reproducible cases. Breakage = immediate failure.

#### 16.1 Measurement Invariance (CORE)

```
test_measurement_invariance_h1:
    Input: {H1_minimal}.R_full and {H1_minimal}.R_short
    Precondition: Both contain identical E1-E3.
    Assert: Identical verdict.

test_measurement_invariance_h2:
    Input: {H2_minimal}.diag_only and {H2_minimal}.with_issues
    Assert: If with_issues=YES, diag_only also YES under repaired evaluator.
```

#### 16.2 Format Invariance

```
test_freeform_vs_normalized: Identical verdict.
test_baseline_passthrough_byte_identical: No transformation when flag OFF.
```

#### 16.3 Parse Robustness

```
test_reasoning_lost_none: {H3_minimal} -> None.
test_structure_missing_none: STRUCTURE_MISSING -> None.
```

#### 16.4 eval_model

```
test_eval_model_honored: eval_model="test-model" -> actual is "test-model". Fails if ignored.
test_eval_model_logged: Result has eval_model_actual.
```

#### 16.5 Stochastic Stability

```
test_deterministic_temp_zero: 3 runs, all identical.
```

#### 16.6 Denominator Integrity

```
test_none_excluded: 3 None in 10 -> denominator 7.
test_unclassified_reported: N_unclassified present.
```

#### 16.7 Solution Leakage Guard

```
test_plan_steps_excluded: Classifier input has no plan_steps content.
test_verification_excluded: Classifier input has no verification evidence.
```

#### 16.8 Controls

```
test_terse_correct_yes: P0-2 case -> YES.
test_verbose_wrong_no: P0-3 case -> NO.
```

#### 16.9 Holdout Integrity

```
test_holdout_not_in_phase0: No holdout case_id in any Phase 0 log.
test_holdout_not_in_phase1: No holdout case_id in any Phase 1 log.
```

---

### 17. Go/No-Go Checklist (EXECUTION PREREQUISITE)

Execution of Phase 0 is BLOCKED until ALL of the following are true. Each item must be verified and signed off.

| # | Prerequisite | Verification | Status |
|---|---|---|---|
| 1 | eval_model bug fix applied (evaluator.py:171) | `grep -n "eval_model or" evaluator.py` returns the fix | [ ] |
| 2 | Parse gate implemented (REASONING_LOST -> None) | Unit test `test_reasoning_lost_produces_none` passes | [ ] |
| 3 | Audit logging: all 20 fields present in logging code | Unit test creates mock eval, asserts all fields | [ ] |
| 4 | temperature=0 confirmed in classifier call path | Unit test or code inspection of llm.py MODEL_CONFIG | [ ] |
| 5 | Locked audit set file created (`audit/locked_audit_set.json`, 30 cases) | File exists, contains 30 entries, stratification checked | [ ] |
| 6 | Holdout set file created (`audit/holdout_set.json`, 8 cases) | File exists, no overlap with locked audit set or Phase 0 set | [ ] |
| 7 | Phase 0 case set file created (remaining cases) | Union of Phase 0 + holdout + locked = all 58 cases | [ ] |
| 8 | Canary run script implemented and tested on 1 mock case | Script runs, validates 5 checks from Section 8.12, exits 0 | [ ] |
| 9 | Budget caps defined in `audit/budget.json` | File exists with Phase 0/1/4 caps | [ ] |
| 10 | Minimal reproducible case template directory created | `audit/minimal_cases/` exists with h1.json, h2.json, h3.json templates | [ ] |
| 11 | Regression tests from Section 16.3-16.4 implemented and passing | `pytest tests/test_parse_gate.py tests/test_eval_model.py` passes | [ ] |
| 12 | This plan (v5) reviewed and approved | Sign-off recorded | [ ] |

**If ANY item is unchecked: execution MUST NOT begin.**

The checked-off version of this table is stored in `audit/go_no_go.json` with timestamps and is the authoritative record of execution readiness.
