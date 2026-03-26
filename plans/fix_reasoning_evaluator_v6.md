# Fix Plan: Reasoning Evaluator — Measurement Repair

**Version:** v6 (FINAL — APPROVED FOR EXECUTION)
**Date:** 2026-03-26
**Status:** Plan complete. Execution blocked until Go/No-Go checklist (Section 17) is satisfied.
**Supersedes:** fix_reasoning_evaluator_v5.md
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## CHANGELOG (v5 -> v6)

| Change | What | Rationale |
|---|---|---|
| Added Section 6.5 | Fix C component ablation: 3 configurations tested separately in Phase 1 to isolate representation vs prompt effects | Non-identifiability: coupling representation change and prompt change prevents attributing causal effect |
| Added Section 8.13 | Extraction correctness audit: validate extracted E1 against manual annotation, not just check non-empty | Non-empty root_cause can be WRONG. Presence is insufficient; correctness is required. |
| Added Section 2.1 | Extraction correctness guarantee with enforcement mechanism | Silent false positives from incorrect extraction must be structurally impossible |
| Updated Section 8.4 | New stop condition: incorrect extracted root_cause producing YES triggers hard failure | |
| Updated Section 16.10 | New regression test: extraction-correctness-guard | |
| Updated Section 17 | Go/No-Go item 13: extraction correctness audit script ready | |

All v5 constraints preserved unchanged.

---

## PART I: MEASUREMENT REPAIR

### 1. Executive Summary

**All cross-condition reasoning comparisons produced by this system are currently invalid.** The reasoning evaluator (`evaluator.py:llm_classify`) is not format-invariant. The same model reasoning expressed in baseline freeform format and LEG structured format receives systematically different classifier verdicts. This is a structural defect.

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

Enforced as permanent regression test (Section 16.1) using minimal reproducible cases (Section 8.6).

#### 2.1 Extraction Correctness Guarantee

> It is impossible for the evaluator to produce `reasoning_correct=True` based on an incorrect extracted root cause without triggering a validation failure.

**Enforcement mechanism** (three layers):

**Layer 1 — Phase 1 extraction audit (Section 8.13)**: For every locked audit case where extraction is applied, the extracted `root_cause` (E1) is compared against the manually annotated E1. If the extraction is wrong (does not match the annotated root cause) AND the classifier produces YES, this is a **silent false positive** and triggers an immediate hard failure. Fix C cannot proceed with this extraction method.

**Layer 2 — Phase 4 flip audit**: For every case where the new evaluator (with extraction/normalization) produces `reasoning_correct=True` but the old evaluator produced `False`, the extracted E1 is manually inspected. If E1 is incorrect in ANY such case, the flip is classified as EXTRACTION_ERROR in the disagreement taxonomy and counted against the fix. If >= 2 such cases exist in the Phase 4 audit sample, the fix is rejected.

**Layer 3 — Permanent regression test (Section 16.10)**: A test case with a known-incorrect extracted root cause is permanently maintained. The test asserts that if this incorrect E1 reaches the classifier, the system either (a) detects the extraction error before classification, or (b) the classifier returns NO. If the classifier returns YES on an incorrect E1, the test fails.

### 3. Unconditional Correctness Fixes

Applied immediately, before hypothesis testing.

**Fix D — Parse Recovery Gate**: Return `reasoning_correct=None` instead of `False` when reasoning is lost.

**Fix E — eval_model Parameter Bug**: Replace `model = "gpt-5.4-mini"` on evaluator.py:171 with `model = eval_model or "gpt-5.4-mini"`. Log `eval_model_actual` in every result.

---

## PART II: HYPOTHESIS VALIDATION

### 4. Hypotheses and Falsification Experiments

#### H1: Classifier Brevity Bias

**Experiment P0-1**: 15 cases, 4 versions each (full + 3 compressions).

**CONFIRMED**: >= 5/15 flip YES->NO while E1-E3 preserved.
**FALSIFIED**: <= 2/15.
**INCONCLUSIVE**: 3-4/15. Expand to 25 (cycle 1). Cap: 2 cycles. After cap: CONFIRMED if >= 4/25, FALSIFIED if < 4/25, or UNRESOLVABLE (treat confirmed).

**Controls**:
- P0-2: 5 terse-correct. ALL YES. Any NO: **classifier disqualified** (8.8).
- P0-3: 5 verbose-wrong. ALL NO. Any YES: **classifier disqualified**.

#### H2: Reasoning Information Loss

**Experiments P0-4/P0-5**: 10 LEG cases. Annotation + classifier comparison.

**CONFIRMED**: diag < full on E1-E3 in >= 7/10, AND >= 6/10 flip NO->YES.
**FALSIFIED**: diag has E1-E3 in >= 8/10, or < 3/10 flip.
**INCONCLUSIVE**: Expand to 20 (cycle 1). Cap: 2 cycles.

#### H3: Parse Failure Corruption

**Experiments P0-6/P0-7**: Census + raw inspection.

**CONFIRMED**: >= 5% in any non-baseline condition.
**FALSIFIED**: < 1% everywhere.
**INCONCLUSIVE**: 1-5%. Inspect all (cycle 1). Cap: 2 cycles.

#### P0-0: eval_model Isolation (PREREQUISITE ZERO)

Locked audit set x 2 models. Label-by-label. > 5 flips: dual-report all experiments.

#### P0-PROMPT: Prompt Sensitivity

10 cases x 2 prompts. > 1/10 differ: prompt-sensitive.

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

Primary annotator: re-label 5-case subset, self-consistency >= 90%.
Second annotator: same 5 cases, inter-annotator >= 85%.

If self < 90%: refine rubric, re-annotate.
If inter < 85%: resolve disagreements, re-annotate if > 2/5 change. If < 85% after clarification: H2 conclusions downgraded.

---

### 6. Candidate Fixes

#### 6.1 Prohibited and Permitted Fields

**HARD RULE**: `plan_steps` and `verification` excluded from primary reasoning input.

**Permitted** (subject to leakage audit 8.9): `bug_diagnosis`, `issues_found[].description/evidence`, `invariants_checked[].invariant` (FAIL only).

>= 3/10 leakage flips: issues_found and invariants excluded. Fix A dead. Fix C only.

#### 6.2 Fix A: Enriched Reasoning (FALLBACK ONLY)

Risk: HIGH. Permitted only if Fix C fails Phase 1.

#### 6.3 Fix B: Classifier Prompt Redesign

Risk: MEDIUM-HIGH. Changes all conditions.

#### 6.4 Fix C: Normalized Intermediate Representation (PRIMARY PATH)

Canonical slots: `root_cause` (E1), `manifestation` (E2), `mechanism_or_invariant` (E3), `evidence`. fix_rationale EXCLUDED.

**LEG mapping**: direct.
**Baseline mapping**: rule-based FIRST -> LLM fallback on empty E1/E2 -> raw passthrough if both fail.

**Extraction failure criteria**: Rule-based empty root_cause in > 2/10 locked audit = broken. LLM fallback empty root_cause in > 1/10 = broken. Both broken: Fix C cannot proceed.

**Extraction CORRECTNESS criteria** (Section 8.13): Extracted E1 must match manually annotated E1 in >= 8/10 locked audit cases. If < 8/10: extraction is unreliable, Fix C cannot proceed.

#### 6.5 Fix C Component Ablation (MANDATORY in Phase 1)

Fix C couples two changes: (1) the representation change (freeform -> normalized slots) and (2) the classifier prompt change (new prompt evaluating slots). These MUST be tested separately to isolate causal effects.

**Three configurations tested in Phase 1**:

| Config | Representation | Classifier Prompt | Purpose |
|---|---|---|---|
| **C-repr-old** | Normalized slots (Fix C representation) | OLD classifier prompt (current _CLASSIFY_PROMPT) | Isolates representation effect. The old prompt receives the normalized text rendered as a flat string. |
| **C-raw-new** | Raw freeform reasoning (no normalization) | NEW classifier prompt (slot-aware) | Isolates prompt effect. The new prompt receives raw text and must evaluate it without slot structure. |
| **C-full** | Normalized slots | NEW classifier prompt | Full Fix C. Both changes combined. |

Each configuration is run on the locked audit set (30 cases) + 10 additional LEG cases.

**Results MUST be reported as a 3-way comparison table**: per-condition reasoning_correct rate for C-repr-old, C-raw-new, and C-full.

**Interpretation**:
- If C-repr-old improves over current AND C-raw-new does not: the representation change is the active ingredient. The prompt change is unnecessary.
- If C-raw-new improves over current AND C-repr-old does not: the prompt change is the active ingredient. The representation is unnecessary.
- If both improve independently and C-full improves more: both contribute. Document relative magnitudes.
- If C-full does NOT improve over C-repr-old or C-raw-new alone: there is an interaction effect. Debug before deploying C-full.

**All three configurations MUST pass the locked audit set drift test (Section 9.2) independently.** A configuration that causes > 1 unjustified flip is rejected regardless of aggregate improvement.

This ablation is non-negotiable. Without it, any conclusion about "what fixed the evaluator" is not scientifically attributable.

#### 6.6 Fix D: Parse Gate (UNCONDITIONAL)

#### 6.7 Fix E: eval_model Bug (UNCONDITIONAL)

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
| P0-0 | eval_model isolation (30 x 2 models) | Drift quantified | N/A |
| P0-1 | H1 Brevity (15 x 4 compressions) | >= 5/15 flip | <= 2/15 |
| P0-2 | H1 Neg: terse-correct (5) | All YES | Any NO: **disqualify** |
| P0-3 | H1 Neg: verbose-wrong (5) | All NO | Any YES: **disqualify** |
| P0-4 | H2 Semantic annotation (10 LEG) | diag < full >= 7/10 | diag == full >= 8/10 |
| P0-5 | H2 Classifier effect (10) | >= 6/10 flip | < 3/10 |
| P0-6 | H3 Parse census | >= 5% any condition | < 1% everywhere |
| P0-7 | H3 Raw inspection | Raw has reasoning | Raw empty |
| P0-PROMPT | Prompt sensitivity (10 x 2) | Quantified | N/A |
| P0-STAB | Stochastic stability (20 x 3, temp=0) | 100% consistent | Any inconsistency |

#### 8.2 Phase 0 Exit Conditions (BLOCKING)

1. Refinement cap: max TWO cycles per hypothesis. After cap: accept or UNRESOLVABLE (treat confirmed).
2. Control failure (P0-2 or P0-3): classifier disqualified -> 8.8.
3. Every verdict cites experiment ID + numeric result.
4. P0-0 > 5 flips: dual-report.

#### 8.3 Audit Logging (MANDATORY)

20 fields per case per experiment. No logs = no results.

Fields: `experiment_id`, `case_id`, `condition`, `raw_model_output`, `parsed_reasoning`, `enriched_reasoning`, `normalized_representation`, `extraction_method`, `extraction_failed`, `extraction_e1_correct` (from 8.13 audit, if applicable), `parse_error`, `parse_category`, `recovery_method`, `classifier_prompt`, `classifier_raw_output`, `classifier_verdict`, `classifier_failure_type`, `classifier_parse_error`, `eval_model_intended`, `eval_model_actual`, `semantic_elements`.

(21 fields total with the added `extraction_e1_correct`.)

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
| Holdout disagree with Phase 0 by > 15pp | Overfit -> reject |
| Incorrect extracted E1 produces classifier YES | **Hard failure** -> Fix C extraction rejected |
| >= 2 Phase 4 flips (old=NO, new=YES) have incorrect E1 | Fix rejected |

#### 8.5 Stochastic Stability

20 cases x 3 runs at temp=0. Required: **100% consistency**. Unstable: mandatory 3-call majority voting.

#### 8.6 Minimal Reproducible Cases

- **H1 minimal**: R_full (YES) + R_short (same E1-E3, NO).
- **H2 minimal**: bug_diagnosis (NO) + +issues_found (YES).
- **H3 minimal**: raw with reasoning + parse error + False.

Ground truth anchors for all regression tests.

#### 8.7 Disagreement Taxonomy (Phase 4)

| Category | Definition |
|---|---|
| PARSE_RELATED | Old: empty reasoning -> NO. New: gated -> None. |
| BREVITY_RELATED | Same text, different verdict |
| INFORMATION_RELATED | New has additional content |
| FORMAT_DEPENDENT_PROMPT_FAILURE | Same semantics, prompt phrasing causes difference |
| CLASSIFIER_ERROR | Neither verdict matches rubric |
| EXTRACTION_ERROR | New evaluator YES, but extracted E1 is incorrect |

#### 8.8 Classifier Disqualification

Hard trigger: ANY control fails after fixes. No tuning.
1. Hybrid. 2. Rule-based. 3. Abandon automated reasoning. code_correct only.

#### 8.9 Enrichment Leakage Audit

Every NO->YES flip inspected. MECHANISM_RECOVERY vs SOLUTION_LEAKAGE. >= 3/10 leakage: enrichment rejected.

#### 8.10 Plan Compliance Verification

##### Pre-Phase Checklists

**Pre-Phase 0**:

| # | Item | Verification |
|---|---|---|
| 1 | eval_model bug fixed | Programmatic: grep |
| 2 | Parse gate active | Programmatic: unit test |
| 3 | All 21 audit log fields in code | Programmatic: mock test |
| 4 | temperature=0 confirmed | Programmatic: inspect kwargs |
| 5 | Locked audit set (30 cases) | File exists, stratified |
| 6 | Holdout set (8 cases, no overlap) | Programmatic: intersection empty |
| 7 | Phase 0 case set (remaining) | Programmatic: union = 58 |
| 8 | Minimal case templates | Manual: directory exists |
| 9 | Canary script tested | Programmatic: runs on mock |
| 10 | Budget caps defined | Manual: file exists |

**Pre-Phase 1**:

| # | Item | Verification |
|---|---|---|
| 1 | Phase 0 report with all verdicts | File exists |
| 2 | All P0 experiments have complete logs | Programmatic: count records |
| 3 | Minimal cases filled for confirmed hypotheses | Manual: non-empty |
| 4 | Inter-rater >= 85% | In Phase 0 report |
| 5 | Controls passed | Programmatic: parse results |
| 6 | Component ablation plan (6.5) ready | Manual: 3 configs defined |
| 7 | Extraction correctness audit script ready (8.13) | Programmatic: script exists |

**Pre-Phase 4**:

| # | Item | Verification |
|---|---|---|
| 1 | Phase 1 report delivered | File exists |
| 2 | All Phase 1 stop conditions passed | In report |
| 3 | Component ablation results documented | In report |
| 4 | Canary (5 cases, dual scoring) passed | Programmatic |
| 5 | Holdout not contaminated | Programmatic: scan logs |
| 6 | Budget cap defined | File exists |

##### Post-Phase Checklists

**Post-Phase 0**: All experiments ran. All logs complete. Verdict table present. Each verdict cites ID + number.

**Post-Phase 1**: Ablation (6.5) results for all 3 configs. Extraction correctness (8.13) results. Label-level comparison documented.

**Post-Phase 4**: Dual scores logged. Taxonomy applied. Holdout comparison done. Budget checked.

**Any missing item: phase invalid. Re-run.**

#### 8.11 Holdout Case Set

8 cases (~14%), never in Phase 0/1. Stratified. Phase 4 only. > 15pp gap with non-holdout: overfit, reject fix. Programmatic contamination check.

#### 8.12 Cost Protection

**Canary**: 3-5 cases before any run > 20 calls. 5 checks (parsing, classifier, logging, eval_model, completeness). Any fail: abort.

**Budget caps**: Phase 0: 500. Phase 1: 300. Phase 4: 1500. Defined in `audit/budget.json`. Exceeded: hard stop.

**Cost logging**: timestamp, model, prompt_tokens_est, purpose per call.

#### 8.13 Extraction Correctness Audit (MANDATORY for Fix C)

Presence of a non-empty `root_cause` does NOT guarantee correctness. An extraction that produces "import ordering issue" when the real root cause is "shared mutable reference" is a silent false positive path: the classifier might say YES to a confidently-stated-but-wrong root cause.

**Audit protocol**:

1. For at least 10 locked audit cases where extraction (rule-based or LLM) is applied:
   a. Record the extracted `root_cause` (E1) text.
   b. Compare against the manually annotated E1 from the semantic completeness rubric (Section 5).
   c. Score: MATCH (extracted E1 names the same defect as annotated E1), PARTIAL (related but imprecise), MISMATCH (different defect).

2. **Extraction correctness threshold**: >= 8/10 cases must be MATCH or PARTIAL. If < 8/10: extraction is unreliable. Fix C CANNOT proceed with this extraction method. Debug extraction, improve rules, re-audit. If still < 8/10 after one improvement cycle: Fix C is blocked. Fall back to Fix A.

3. **Silent false positive check**: For every case where:
   - Extraction was applied (normalized representation used), AND
   - New evaluator produces `reasoning_correct=True`, AND
   - Old evaluator produced `reasoning_correct=False`

   Manually inspect the extracted E1. Is it actually correct?

   - If E1 is correct: the flip is legitimate (evaluator improvement). Log as INFORMATION_RELATED.
   - If E1 is incorrect but classifier said YES: **this is a silent false positive**. The evaluator credited the model for reasoning it did not actually produce. This triggers a **hard failure** in the stop conditions (Section 8.4). The extraction method must be fixed or Fix C is rejected.

4. **Log field**: Every case with extraction records `extraction_e1_correct` = MATCH / PARTIAL / MISMATCH / NOT_AUDITED. This field is part of the audit log (Section 8.3).

---

### 9. Backward Compatibility

#### 9.1 Locked Audit Set

30 baseline cases, stratified. At least 5 v2-only. 15 YES, 15 NO. No overlap with holdout.

#### 9.2 Label-Level Stability

ALL 30 match: confirmed. 1 flip: justified. 2-3: each justified. > 3: abort.

**Each Fix C configuration (6.5) is tested against the locked audit set independently.** A configuration causing > 1 unjustified flip is rejected regardless of aggregate.

---

### 10. Denominator and Reporting Policy

#### 10.1 Rate Computations

N_total, N_classified, N_unclassified, N_parse_failed, N_recovered. Rates use N_classified.

#### 10.2 Mandatory Rules

All five N columns in every table. > 10pp unclassified gap: comparison excluded from ALL figures, tables, claims.

#### 10.3 None Handling

None excluded from rates. Never False. Always reported.

---

### 11. Decision Framework

| H1 | H2 | H3 | Fix Path |
|---|---|---|---|
| CONFIRMED | FALSIFIED | Any | Fix B or Fix C (component ablation determines which component needed) |
| FALSIFIED | CONFIRMED | Any | Fix C primary. Fix A fallback only if Fix C fails. |
| CONFIRMED | CONFIRMED | Any | Fix C (only symmetric fix). Ablation (6.5) determines if prompt change also needed. |
| FALSIFIED | FALSIFIED | CONFIRMED | Fix D only |
| CONFIRMED | CONFIRMED | CONFIRMED | Fix D first, Fix E, then Fix C |
| ALL FALSIFIED | | | Null-result report |
| Any UNRESOLVABLE | | | Treat confirmed. Fix C. |

Fix D/E: unconditional. Fix C: primary. Fix A: last resort.

**The component ablation (6.5) refines the decision**: if C-repr-old is sufficient alone, the prompt change is deferred. If C-raw-new is sufficient alone, normalization is deferred. The ablation prevents shipping unnecessary changes.

---

### 12. Rollout Phases

#### Phase 0: Measurement Audit (BLOCKING GATE)

1. Verify Pre-Phase 0 Checklist.
2. Fix eval_model, apply parse gate.
3. Canary (3 cases).
4. P0-0, P0-PROMPT, P0-STAB.
5. P0-1 through P0-7.
6. Semantic annotation with inter-rater.
7. Minimal reproducible cases.
8. Post-Phase 0 Checklist.
9. Phase 0 report.

**Gate**: All hypotheses resolved. Controls pass. Stability verified. Checklists complete.

#### Phase 1: Offline Experiments

1. Pre-Phase 1 Checklist.
2. Select fix per decision framework.
3. Implement behind flag.
4. Canary (5 cases).
5. **Component ablation (6.5): run all 3 configs on locked audit + 10 LEG cases.**
6. **Extraction correctness audit (8.13): 10 locked audit cases.**
7. All controls on each configuration.
8. Stochastic stability on each configuration.
9. P1-LEAK-ISSUES audit.
10. Phase 1 report with ablation table and extraction audit.

**Gate**: Ablation results documented. Extraction >= 8/10 correct. Drift <= 1 justified per config. Controls pass. No silent false positives.

#### Phase 2: Choose Fix

Review reports. Select configuration based on ablation results. Document citing experiment IDs.

#### Phase 3: Implement Behind Flag

Default OFF. Both paths when ON. Fix D ON by default.

#### Phase 4: Dual-Score Shadow Run (MANDATORY)

1. Pre-Phase 4 Checklist.
2. Canary (5 cases, dual).
3. 58 cases x conditions x 1 trial, dual scoring.
4. Holdout cases evaluated.
5. Per-condition disagreement rates.
6. Scaled audit: <= 20% -> 10/condition. > 20% -> 20/condition.
7. **Disagreement taxonomy including EXTRACTION_ERROR category.**
8. **For every old=NO/new=YES flip in audit: verify extracted E1 correctness (8.13 step 3).**
9. Holdout vs non-holdout (overfit check).
10. Post-Phase 4 Checklist.
11. Phase 4 report.

**Gate**: Directionally correct >= 80%. Locked set stable. Controls pass. Holdout within 15pp. No extraction false positives (>= 2 incorrect E1 with YES -> reject). Budget OK.

#### Phase 5: Switch Primary Metric

Only if Phase 4 passes all gates. Switch. Archive. Document.

---

### 13. Do Not Do

1. Do NOT classify empty reasoning as incorrect.
2. Do NOT switch metric without Phase 4 shadow.
3. Do NOT change prompt AND representation simultaneously without ablation (6.5).
4. Do NOT fold heuristic recovery into primary metrics.
5. Do NOT accept aggregate improvement if label audit shows > 1 unjustified flip.
6. Do NOT assume baseline and LEG rates must converge.
7. Do NOT include plan_steps or verification in primary input.
8. Do NOT leave eval_model hard-coded.
9. Do NOT run experiments without complete audit logs.
10. Do NOT skip annotation or inter-rater check.
11. Do NOT proceed phases without checklists.
12. Do NOT report comparisons with > 10pp unclassified gap.
13. Do NOT iterate on classifier after control failure. Disqualify.
14. Do NOT use unstable classifier without voting.
15. Do NOT use holdout cases in Phase 0/1.
16. Do NOT proceed with large run without canary.
17. Do NOT treat non-empty extraction as correct without the extraction correctness audit (8.13).
18. Do NOT deploy Fix C without completing the component ablation (6.5) — representation and prompt changes must be separately attributable.

---

### 14. Metrics for Success

| Metric | Target | Type |
|---|---|---|
| Format invariance (minimal cases) | 100% same verdict | Invariant |
| Parse false negative rate | 0% | Correctness |
| Locked audit drift (30 cases) per config | <= 1 justified flip | Stability |
| Shadow disagreement: directionally correct | >= 80% audited flips | Quality |
| Holdout vs non-holdout gap | <= 15pp | Generalization |
| Unclassified rate | > 10pp gap invalidates comparison | Transparency |
| verbose-wrong controls | 100% NO | Safety |
| terse-correct controls | 100% YES | Safety |
| Stochastic stability at temp=0 | 100% | Reliability |
| Inter-rater agreement | >= 85% | Rubric validity |
| Extraction correctness (E1) | >= 8/10 MATCH/PARTIAL | Extraction validity |
| Extraction false positives (incorrect E1 -> YES) | 0 | Guarantee |
| Canary pass rate | 100% before every large run | Infrastructure |
| Component ablation: all 3 configs reported | Required | Identifiability |

---

### 15. Risk Analysis

#### 15.1 Enrichment Asymmetry
Fix A creates asymmetry. Fix C eliminates it. Fix A is fallback only.

#### 15.2 Extraction Errors
Rule-based first, LLM fallback, raw passthrough. Correctness validated (8.13), not just presence. Incorrect E1 -> YES is a hard failure.

#### 15.3 Classifier Model Sensitivity
P0-0 quantifies. Dual-report if high.

#### 15.4 Denominator Asymmetry
10pp rule. Invalid comparisons excluded.

#### 15.5 Overfitting
Holdout set detects. 15pp threshold rejects.

#### 15.6 Classifier Unreliability
Disqualification trigger. Three-tier contingency.

#### 15.7 Implementation Drift
Pre/post checklists. Programmatic verification.

#### 15.8 Cost Overrun
Canary + budget caps + automatic abort.

#### 15.9 Non-Identifiability (NEW)
Component ablation (6.5) isolates representation vs prompt effects. Without ablation, causal attribution is impossible. Ablation is mandatory.

#### 15.10 Silent Extraction False Positives (NEW)
Extraction correctness guarantee (2.1) with three enforcement layers prevents incorrect E1 from producing undetected YES verdicts.

---

### 16. Permanent Regression Tests

ALL tests reference minimal reproducible cases. Breakage = immediate failure.

#### 16.1 Measurement Invariance (CORE)

```
test_measurement_invariance_h1:
    Input: {H1_minimal}.R_full and {H1_minimal}.R_short (same E1-E3).
    Assert: Identical verdict.

test_measurement_invariance_h2:
    Input: {H2_minimal}.diag_only and {H2_minimal}.with_issues.
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
test_eval_model_honored: Fails if eval_model ignored.
test_eval_model_logged: eval_model_actual present.
```

#### 16.5 Stochastic Stability

```
test_deterministic_temp_zero: 3 runs identical.
```

#### 16.6 Denominator Integrity

```
test_none_excluded: 3 None in 10 -> denominator 7.
test_unclassified_reported: N_unclassified present.
```

#### 16.7 Solution Leakage Guard

```
test_plan_steps_excluded: Not in classifier input.
test_verification_excluded: Not in classifier input.
```

#### 16.8 Controls

```
test_terse_correct_yes: YES.
test_verbose_wrong_no: NO.
```

#### 16.9 Holdout Integrity

```
test_holdout_not_in_phase0: Scan logs.
test_holdout_not_in_phase1: Scan logs.
```

#### 16.10 Extraction Correctness Guard (NEW)

```
test_incorrect_e1_does_not_produce_yes:
    Given: A normalized representation where root_cause (E1) is known to be INCORRECT
           (e.g., "import ordering issue" when the real cause is "shared mutable reference").
    When: Passed to the classifier.
    Then: classifier_verdict is NO.
    Note: If classifier says YES on an incorrect E1, this is a silent false positive.
          The test MUST fail. This enforces the guarantee in Section 2.1.

test_extraction_correctness_logged:
    Given: Any case with extraction applied.
    Then: extraction_e1_correct field is present in audit log.
    Note: The field may be NOT_AUDITED for non-audit cases, but must exist.
```

---

### 17. Go/No-Go Checklist (EXECUTION PREREQUISITE)

Execution BLOCKED until ALL items satisfied.

| # | Prerequisite | Verification | Status |
|---|---|---|---|
| 1 | eval_model bug fixed | Programmatic: grep | [ ] |
| 2 | Parse gate implemented | Programmatic: unit test | [ ] |
| 3 | All 21 audit log fields in code | Programmatic: mock test | [ ] |
| 4 | temperature=0 confirmed | Programmatic: inspect kwargs | [ ] |
| 5 | Locked audit set (30 cases) | File exists, stratified | [ ] |
| 6 | Holdout set (8 cases, no overlap) | Programmatic: intersection empty | [ ] |
| 7 | Phase 0 case set (remaining) | Programmatic: union = 58 | [ ] |
| 8 | Minimal case templates prepared | Manual: directory exists | [ ] |
| 9 | Canary script tested on mock | Programmatic: exits 0 | [ ] |
| 10 | Budget caps in audit/budget.json | Manual: file exists | [ ] |
| 11 | Regression tests 16.3-16.4 passing | Programmatic: pytest passes | [ ] |
| 12 | Plan v6 reviewed and approved | Sign-off recorded | [ ] |
| 13 | Extraction correctness audit script ready | Programmatic: script exists, runs on 1 mock case | [ ] |

**Any unchecked item: execution MUST NOT begin.**

Checked-off table stored in `audit/go_no_go.json` with timestamps.
