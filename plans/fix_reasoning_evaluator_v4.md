# Fix Plan: Reasoning Evaluator — Measurement Repair

**Version:** v4 (FINAL)
**Date:** 2026-03-26
**Status:** Plan only. No code changes. Approved for Phase 0 execution.
**Supersedes:** fix_reasoning_evaluator_v3.md
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## PART I: MEASUREMENT REPAIR

This part defines the defects, the core invariant being restored, and the correctness fixes that are applied unconditionally.

### 1. Executive Summary

**All cross-condition reasoning comparisons produced by this system are currently invalid.** The reasoning evaluator (`evaluator.py:llm_classify`) is not format-invariant. The same model reasoning expressed in baseline freeform format and LEG structured format receives systematically different classifier verdicts. This is a structural defect, not a suspected bias.

Three independent pathologies contribute:

1. **H1 — Classifier brevity bias**: The LLM judge penalizes short reasoning even when semantically correct.
2. **H2 — Reasoning information loss**: The LEG-reduction condition maps only `bug_diagnosis` (one sentence) to the classifier's `reasoning` input, discarding plan_steps, revision_history, verification, and invariants_checked.
3. **H3 — Parse failure corruption**: When parsing fails, `reasoning=""` reaches the classifier, which produces `reasoning_correct=False` instead of `None`, injecting false negatives.

Additionally, evaluator.py:171 hard-codes `model = "gpt-5.4-mini"`, ignoring the `eval_model` parameter. Every experiment that specified a different eval model silently used the wrong one.

**Until these defects are characterized and repaired:**
- LEG rate, true_success rate, and reasoning_action_gap are unreliable for all non-baseline conditions.
- No paper-quality claim about reasoning correctness differences across conditions is supportable.
- Baseline-only results are unaffected by H2/H3 but remain subject to H1.

### 2. Measurement Invariance Statement

**The core property this plan restores:**

> Two reasoning inputs that are semantically equivalent under the E1-E3 rubric (Section 5) MUST produce identical classification outcomes, regardless of surface format, length, or structural representation.

This is not a design goal. It is a **measurement invariant**. Any evaluator that violates it produces invalid cross-condition comparisons. This invariant is enforced as a permanent regression test (Section 16.1) using the minimal reproducible cases from Section 8.6.

### 3. Unconditional Correctness Fixes

These are applied immediately, before any hypothesis testing, because they are verified bugs, not measurement design choices.

**Fix D — Parse Recovery Gate**: Prevent classification on corrupt reasoning input per the taxonomy in Section 7. Return `reasoning_correct=None` instead of `False` when reasoning is lost. This is a correctness fix: classifying empty reasoning as "incorrect" conflates parse failure with model failure.

**Fix E — eval_model Parameter Bug**: Replace `model = "gpt-5.4-mini"` on evaluator.py:171 with `model = eval_model or "gpt-5.4-mini"`. Log `eval_model_actual` in every classifier result. This is a verified code defect — the parameter is accepted but ignored.

---

## PART II: HYPOTHESIS VALIDATION

This part defines the three hypotheses, the experiments that test them, and the decision rules that determine which fix is selected.

### 4. Hypotheses and Falsification Experiments

#### H1: Classifier Brevity Bias

**Claim**: The LLM classifier produces systematically lower `reasoning_correct=True` rates for semantically equivalent reasoning expressed in shorter form.

**Falsification experiment** (P0-1):

Take 15 cases from existing data where baseline `reasoning_correct=YES` (verified manually). For each, create three compressed versions:

- **Compression A**: First sentence of the original reasoning only.
- **Compression B**: Manually written one-sentence root-cause summary that names the mechanism correctly. Annotator writes this WITHOUT looking at LEG output.
- **Compression C**: The actual `bug_diagnosis` field from LEG-reduction output for the same case (if available), or a LEG-style terse summary.

Run the classifier on all 4 versions (full + 3 compressed) for each case.

**H1 CONFIRMED if**: >= 5/15 cases flip YES->NO on any compression while E1-E3 elements are preserved per rubric.

**H1 FALSIFIED if**: <= 2/15 cases flip.

**H1 INCONCLUSIVE if**: 3-4/15 flip. Action: expand to 25 cases and re-run. This is refinement cycle 1.

**Refinement cap**: Maximum TWO refinement cycles per hypothesis. After cycle 2, the result MUST be accepted as CONFIRMED (if >= 4/25 flip) or FALSIFIED (if < 4/25), or the hypothesis is declared UNRESOLVABLE and the plan proceeds conservatively (assume confirmed, apply the safer fix).

**Controls**:
- **P0-2: known-terse-but-correct**: 5 one-sentence summaries correctly identifying the mechanism. ALL must classify YES. If ANY classify NO: **classifier disqualification trigger** — proceed directly to Section 8.8.
- **P0-3: known-verbose-but-wrong**: 5 verbose paragraphs (200+ words) identifying the WRONG mechanism. ALL must classify NO. If ANY classify YES: **classifier disqualification trigger** — proceed directly to Section 8.8.

#### H2: Reasoning Information Loss

**Claim**: The mapping from structured LEG output to the classifier's `reasoning` input systematically discards causal elements required for a YES verdict.

**Falsification experiment** (P0-4, P0-5):

For 10 cases where LEG-reduction produced valid structured output:

1. Apply the semantic completeness rubric (Section 5) to `bug_diagnosis` alone, full LEG output, and matched baseline.
2. Run classifier on `bug_diagnosis` only (current behavior).
3. Run classifier on `bug_diagnosis` + `issues_found[].description` only (NO plan_steps, NO verification — see Section 6.1).

**H2 CONFIRMED if**: `bug_diagnosis` alone scores lower on E1-E3 than full LEG output in >= 7/10, AND classifier flips NO->YES in >= 6/10 with additional content.

**H2 FALSIFIED if**: `bug_diagnosis` contains E1-E3 in >= 8/10, or verdicts do not change.

**H2 INCONCLUSIVE if**: Mixed. Action: expand to 20 cases with second annotator. Refinement cycle 1.

**Refinement cap**: Same rule. Maximum TWO cycles. After cycle 2: accept result or declare UNRESOLVABLE (assume confirmed).

#### H3: Parse Failure Corruption

**Claim**: Parse failures cause `reasoning=""` to reach the classifier, producing false negatives.

**Falsification experiment** (P0-6, P0-7):

1. Count parse failure rates per condition across existing ablation data.
2. For REASONING_LOST cases: inspect raw output for identifiable reasoning text.

**H3 CONFIRMED if**: >= 5% of cases in any non-baseline condition have `reasoning=""` due to parse failure, AND raw output contains reasoning.

**H3 FALSIFIED if**: < 1% everywhere, or parse failures correspond to genuine no-reasoning.

**H3 INCONCLUSIVE if**: 1-5% with mixed raw inspection. Action: inspect ALL cases (not sample). Refinement cycle 1. Cap at 2 cycles.

#### eval_model Parameter Bug (P0-0 — PREREQUISITE ZERO)

Run the locked audit set with:
- (A) hard-coded model (`gpt-5.4-mini`)
- (B) intended eval_model (e.g., `gpt-5-mini`)

Record label-by-label comparison. Report drift count. This MUST complete before any other Phase 0 experiment.

If > 5 labels flip: model sensitivity is high. All subsequent experiments run on BOTH models with results side-by-side.

#### P0-PROMPT: Format-Dependent Prompt Failure Test

Run the same 10 reasoning texts through the classifier under two slightly varied prompt phrasings (identical semantics, different surface wording). Record verdicts.

**Purpose**: Detect FORMAT_DEPENDENT_PROMPT_FAILURE — where identical reasoning semantics produce different verdicts due to prompt phrasing.

If > 1/10 cases produce different verdicts across prompt variants, the classifier is prompt-sensitive and this must be factored into all subsequent analysis.

---

### 5. Semantic Completeness Rubric

#### 5.1 Required Elements

| Element | Definition | Example (alias_config_a) |
|---|---|---|
| **E1: Root Cause** | Names the specific defect | "create_config returns DEFAULTS by reference" |
| **E2: Manifestation Path** | Explains HOW the bug produces observable failure | "Caller mutations corrupt global state, affecting subsequent calls" |
| **E3: Invariant or Mechanism** | Names the violated principle or causal rule | "Aliasing: shared mutable reference" |
| **E4: Fix Rationale** (optional) | Explains why the fix addresses the root cause | "Returning dict(DEFAULTS) creates an independent copy" |

#### 5.2 Annotation Protocol

For each matched baseline/LEG case:

1. Annotate **baseline reasoning** for E1-E4. Binary: present (1) / absent (0).
2. Annotate **LEG bug_diagnosis** alone for E1-E4.
3. Annotate **full LEG output** (all structured fields) for E1-E4.
4. Record: `baseline_elements`, `leg_diag_elements`, `leg_full_elements`.

#### 5.3 Inter-Rater Reliability

**Primary annotator**: Re-labels a random 5-case subset on a separate day. Element-level self-consistency required >= 90% (18/20 judgments match).

**Second independent annotator**: Annotates the SAME 5-case subset without seeing the primary annotator's labels. Inter-annotator agreement required >= 85% (17/20 judgments match).

**If self-consistency < 90%**: Refine element definitions, add disambiguation examples, re-annotate full set.

**If inter-annotator agreement < 85%**: Log all disagreement cases. Analyze each: is the rubric ambiguous, or does one annotator misunderstand an element? Resolve disagreements by discussion. If resolution changes > 2/5 labels, re-annotate full set with clarified rubric.

**If agreement < 85% after one clarification round**: The rubric is not reliable enough for causal claims. H2 conclusions based on the rubric are downgraded to "suggestive, not conclusive."

#### 5.4 Interpretation Rules

- `baseline_elements == leg_diag_elements` for >= 8/10: H1 dominant (brevity, not information loss).
- `baseline_elements > leg_diag_elements` BUT `== leg_full_elements` for >= 7/10: H2 dominant (information present but not reaching classifier).
- `baseline_elements > leg_full_elements` for >= 5/10: Genuine information difference. Enrichment cannot fully close gap.

---

### 6. Candidate Fixes

#### 6.1 Prohibited and Permitted Fields

**HARD RULE**: `plan_steps` and `verification` evidence MUST NOT be included in the primary reasoning input to the classifier. These contain solution-level information (the fix itself, post-hoc validation) that baseline does not expose.

**Permitted fields** (subject to Phase 1 leakage audit):
- `bug_diagnosis` (always)
- `issues_found[].description` + `issues_found[].evidence`
- `invariants_checked[].invariant` where status=FAIL

**Leakage audit requirement (P1-LEAK-ISSUES)**: For any case where adding issues_found/invariants flips the verdict NO->YES, inspect the added content for:
- Explicit fix hints (function names, code snippets of the solution)
- Post-hoc success confirmation ("verified that X works")
- Evaluation artifacts ("PASS" status markers)

**If >= 3/10 flips show leakage**: issues_found and invariants are ALSO excluded. Only `bug_diagnosis` is permitted. Enrichment (Fix A) is rejected entirely. Fix C (normalized representation) becomes the ONLY option.

#### 6.2 Fix A: Enriched Reasoning Input (FALLBACK ONLY)

Concatenate permitted fields into a single string. Baseline: pass-through.

**Risk level**: HIGH. Creates information asymmetry. Permitted ONLY as interim fallback if Fix C fails Phase 1.

#### 6.3 Fix B: Classifier Prompt Redesign

Modify `_CLASSIFY_PROMPT` to tolerate brevity and evaluate semantic content.

**Risk level**: MEDIUM-HIGH. Changes all conditions. Requires full re-baselining.

#### 6.4 Fix C: Normalized Intermediate Representation (PRIMARY PATH)

Define canonical reasoning representation mapping to the E1-E3 rubric:

```
{
    "root_cause": str,              # E1
    "manifestation": str,           # E2
    "mechanism_or_invariant": str,  # E3
    "evidence": list[str]           # supporting quotes (NOT fix steps, NOT verification results)
}
```

**fix_rationale is EXCLUDED by design** (solution-level, not reasoning-level).

**LEG mapping** (direct):
- `root_cause` = `bug_diagnosis`
- `manifestation` = `issues_found[].description` (last revision)
- `mechanism_or_invariant` = `invariants_checked[].invariant` where status=FAIL (last revision)
- `evidence` = `issues_found[].evidence` + `invariants_checked[].evidence`

**Baseline mapping** (extraction required — defined priority):

1. **Rule-based extraction FIRST**: Split reasoning into sentences. Classify each sentence as E1/E2/E3 by keyword matching against failure_mode-specific terms. If a sentence contains root-cause keywords (names a defect, references a specific function), assign to E1. If it describes a consequence or failure path, assign to E2. If it names a principle or invariant, assign to E3.

2. **LLM-based extraction ONLY when rule-based produces empty slots for E1 or E2**: Prompt an LLM to extract E1-E3 from the freeform text. Log the extraction prompt and result.

3. **Fallback if extraction produces empty `root_cause` or misses E1**: Pass the raw freeform reasoning unchanged (no normalization). Flag: `extraction_failed=True`.

**Extraction failure criteria**: If rule-based extraction produces empty `root_cause` in > 2/10 locked audit cases, rule-based extraction is broken. If LLM fallback produces empty `root_cause` in > 1/10 locked audit cases, LLM extraction is broken. If BOTH are broken, Fix C cannot proceed. Fall back to Fix A with full Phase 4 validation.

**Classifier prompt redesigned** for normalized format:
```
Does root_cause correctly name the defect?
Does manifestation correctly describe how the failure occurs?
Does mechanism_or_invariant correctly identify the violated principle?
```

#### 6.5 Fix D: Parse Recovery Gate (UNCONDITIONAL)

See Section 3.

#### 6.6 Fix E: eval_model Bug Fix (UNCONDITIONAL)

See Section 3.

---

## PART III: EXPERIMENTAL RESULTS AND VALIDATION

This part defines the validation framework, shadow run protocol, and criteria for accepting or rejecting fixes.

### 7. Parse Failure Taxonomy and Handling Policy

(Unchanged from v3 Section 4. Six categories: CLEAN, PARTIAL_JSON_RECOVERED, MALFORMED_BUT_RECOVERED, REASONING_LOST, CODE_LOST, STRUCTURE_MISSING. Handling policy table unchanged.)

Heuristic recovery NEVER enters primary metrics. Tag, log, report separately.

---

### 8. Validation Matrix

#### 8.1 Phase 0 Experiments (BLOCKING GATE)

| ID | Experiment | Confirms if | Falsifies if | Inconclusive action |
|---|---|---|---|---|
| P0-0 | eval_model isolation (30 cases x 2 models) | Drift quantified | N/A | N/A |
| P0-1 | H1 Brevity (15 cases x 4 compressions) | >= 5/15 flip | <= 2/15 flip | Expand to 25 (cycle 1) |
| P0-2 | H1 Neg: terse-correct (5 cases) | All YES | Any NO: **disqualify** | N/A |
| P0-3 | H1 Neg: verbose-wrong (5 cases) | All NO | Any YES: **disqualify** | N/A |
| P0-4 | H2 Semantic annotation (10 LEG cases) | diag < full in >= 7/10 | diag == full in >= 8/10 | Expand to 20 (cycle 1) |
| P0-5 | H2 Classifier effect (10 cases) | >= 6/10 flip | < 3/10 flip | Expand (cycle 1) |
| P0-6 | H3 Parse census | >= 5% in any condition | < 1% everywhere | Inspect all (cycle 1) |
| P0-7 | H3 Raw inspection | Raw has reasoning | Raw is empty | Classify each case |
| P0-PROMPT | Prompt sensitivity (10 cases x 2 prompts) | Quantified | N/A | N/A |

#### 8.2 Phase 0 Exit Conditions (BLOCKING)

1. **Hard refinement cap**: Maximum TWO refinement cycles per hypothesis. After cycle 2, accept the result (using the conservative threshold) or declare UNRESOLVABLE (treat as confirmed; apply the safer fix).
2. **Control failure**: If P0-2 OR P0-3 fails, the classifier is disqualified. Proceed to Section 8.8 (classifier replacement). No further prompt tuning.
3. **Inconclusive after cap**: Write Phase 0 failure report. Proceed conservatively: assume the hypothesis is confirmed and apply the fix that is safe under that assumption.
4. **P0-0 shows > 5 flips**: All experiments dual-report on both models.

**Every hypothesis verdict MUST cite experiment ID and numeric result. No prose-only conclusions.**

#### 8.3 Audit Logging (MANDATORY — NO EXCEPTIONS)

For EVERY case in ANY experiment (Phase 0 through Phase 5):

| Field | Description |
|---|---|
| `experiment_id` | e.g., P0-1, P1-3 |
| `case_id` | Benchmark case identifier |
| `condition` | Experimental condition |
| `raw_model_output` | Complete model response before parsing |
| `parsed_reasoning` | What classifier currently receives |
| `enriched_reasoning` | Enriched string (if applicable) |
| `normalized_representation` | Normalized slots (if Fix C) |
| `extraction_method` | rule_based, llm_fallback, raw_passthrough, or N/A |
| `extraction_failed` | Boolean |
| `parse_error` | Parse error code |
| `parse_category` | Taxonomy category |
| `recovery_method` | None, partial_json, fallback_parser, heuristic |
| `classifier_prompt` | Complete classifier prompt |
| `classifier_raw_output` | Raw classifier response |
| `classifier_verdict` | YES/NO/None |
| `classifier_failure_type` | Parsed failure type |
| `classifier_parse_error` | Classifier parse error |
| `eval_model_intended` | eval_model parameter as passed |
| `eval_model_actual` | Model actually used |
| `semantic_elements` | E1-E4 annotation (if in study) |

**Any experiment run without complete audit logs is automatically invalid. No logs = no results.**

#### 8.4 Stop Conditions (Hard Abort)

| Condition | Action |
|---|---|
| > 1/10 known-good YES cases flip to NO | Abort change. Debug. |
| > 1/10 known-good NO cases flip to YES | Abort change. |
| Enriched-vs-raw disagreement > 30% on baseline | Abort enrichment. |
| Locked audit drift > 1 justified flip (30 cases) | Abort rollout. |
| Unclassified rate > 20% for any condition | Fix parsing before gating. |
| verbose-wrong control classifies YES after ANY fix | **Classifier disqualified.** Section 8.8. |
| terse-correct control classifies NO after ANY fix | **Classifier disqualified.** Section 8.8. |
| BOTH evaluators disagree with rubric on > 20% of audited cases | **Both unreliable.** Section 8.8. |

#### 8.5 Stochastic Stability

Run classifier 3 times on 20 identical inputs at temperature=0.

**Required**: 100% verdict consistency (20/20 cases produce identical verdicts across 3 runs).

**If any case produces different verdicts at temperature=0**: Verify temperature is actually 0 (check API call). If confirmed unstable at temp=0, enforce **mandatory majority voting**: every classification runs 3 times, majority verdict is the official result. This is non-negotiable — a stochastically unstable classifier cannot be a primary metric without voting.

#### 8.6 Minimal Reproducible Cases

For each confirmed hypothesis, construct a minimal synthetic example:

- **H1 minimal**: case_id + R_full (classifies YES) + R_short (same E1-E3, classifies NO).
- **H2 minimal**: case_id + bug_diagnosis (classifies NO) + bug_diagnosis + issues_found (classifies YES).
- **H3 minimal**: raw output with reasoning + parse_error causing reasoning="" + False verdict.

These minimal cases are the **ground truth anchors**. ALL regression tests in Section 16 MUST reference these cases explicitly. If a future change breaks a minimal case, the test suite MUST fail immediately.

#### 8.7 Disagreement Taxonomy (MANDATORY for Phase 4)

| Category | Definition |
|---|---|
| **PARSE_RELATED** | Old received empty/corrupt reasoning; new received correct or None |
| **BREVITY_RELATED** | Same text, different verdict due to prompt/length sensitivity |
| **INFORMATION_RELATED** | New received additional content that old did not |
| **FORMAT_DEPENDENT_PROMPT_FAILURE** | Same semantics, different verdict due to prompt phrasing differences |
| **CLASSIFIER_ERROR** | Neither verdict matches semantic rubric |

Every audited disagreement MUST be assigned exactly one category.

#### 8.8 Classifier Disqualification and Replacement

**Hard trigger**: If ANY control (P0-2 terse-correct or P0-3 verbose-wrong) fails AFTER fixes, or if both evaluators disagree with rubric on > 20% of audited cases, the LLM classifier is disqualified. **No further prompt tuning.** Immediate transition:

1. **Hybrid evaluator**: LLM classification + rule-based verification against E1-E3 keyword matching on normalized representation.
2. **If hybrid fails controls**: Purely rule-based evaluator using E1-E3 keyword matching. Lower recall, higher precision.
3. **If rule-based too coarse**: Abandon automated reasoning classification. Report only `code_correct` as primary metric. Reasoning classification becomes secondary, explicitly labeled as unreliable.

#### 8.9 Enrichment Leakage Audit

For EVERY case where enrichment (issues_found, invariants) flips verdict NO->YES:

1. Inspect added content for: explicit fix hints, post-hoc success markers, code-level solution descriptions.
2. Classify each flip as MECHANISM_RECOVERY (legitimate — content describes the failure mechanism) or SOLUTION_LEAKAGE (illegitimate — content describes the fix).
3. If >= 3/10 flips are SOLUTION_LEAKAGE: enrichment is rejected. Only `bug_diagnosis` permitted. Fix A is dead. Fix C is the only path.

---

### 9. Backward Compatibility — Strict Target

#### 9.1 Locked Audit Set

30 baseline cases, stratified by failure_mode and difficulty. At least 5 v2-only.

- 15 with reasoning_correct = YES (manually confirmed)
- 15 with reasoning_correct = NO (manually confirmed)

#### 9.2 Label-Level Stability

- ALL 30 match: confirmed.
- 1 flip: log and justify as genuine improvement. Acceptable.
- 2-3 flips: each MUST be individually justified. Any unjustified flip aborts.
- > 3 flips: abort. Measurement instrument has drifted.

---

### 10. Denominator and Reporting Policy

#### 10.1 Rate Computations

| Metric | Formula |
|---|---|
| `N_total` | Total cases evaluated |
| `N_classified` | reasoning_correct is True or False |
| `N_unclassified` | reasoning_correct is None |
| `N_parse_failed` | REASONING_LOST + CODE_LOST + STRUCTURE_MISSING |
| `N_recovered` | reasoning_recovery is not None |
| `reasoning_correct_rate` | sum(True) / N_classified |
| `leg_rate` | sum(True AND NOT code_correct) / N_classified |
| `true_success_rate` | sum(True AND code_correct) / N_classified |
| `lucky_fix_rate` | sum(False AND code_correct) / N_classified |
| `true_failure_rate` | sum(False AND NOT code_correct) / N_classified |

#### 10.2 Mandatory Reporting

Every results table MUST include: `N_total`, `N_classified`, `N_unclassified`, `N_parse_failed`, `N_recovered`.

**Hard rule**: If unclassified rates differ by > 10pp between compared conditions, the comparison is INVALID. It MUST NOT appear in any figure, table, or claim — not as primary, not as secondary, not with a caveat. It is excluded.

#### 10.3 None Handling

None cases excluded from all rates. Never counted as False. Never silently dropped. Always in N_unclassified.

---

### 11. Decision Framework

| H1 | H2 | H3 | Fix Path |
|---|---|---|---|
| CONFIRMED | FALSIFIED | Any | Fix B or Fix C. Fix A unnecessary. |
| FALSIFIED | CONFIRMED | Any | Fix C primary. Fix A interim fallback only if Fix C fails Phase 1. |
| CONFIRMED | CONFIRMED | Any | Fix C. Only fix achieving symmetric representation. |
| FALSIFIED | FALSIFIED | CONFIRMED | Fix D only. |
| CONFIRMED | CONFIRMED | CONFIRMED | Fix D first, Fix E immediately, then Fix C. |
| ALL FALSIFIED | | | Null-result report. No unnecessary fixes. |
| Any UNRESOLVABLE | | | Treat as CONFIRMED. Apply conservative fix (Fix C). |

Fix D and Fix E: unconditional. Fix C: primary in all confirmed cases. Fix A: last resort.

---

### 12. Rollout Phases

#### Phase 0: Measurement Audit (BLOCKING GATE)

1. Fix eval_model bug (Fix E).
2. Run P0-0 (eval_model isolation).
3. Run P0-PROMPT (prompt sensitivity).
4. Run P0-1 through P0-7.
5. Run stochastic stability test (8.5).
6. Semantic completeness annotation with inter-rater check.
7. Construct minimal reproducible cases.
8. Deliver: Phase 0 report with CONFIRMED/FALSIFIED verdicts + numeric evidence.

**Gate**: All hypotheses resolved (max 2 refinement cycles). All controls pass. Stability verified.

#### Phase 1: Offline Experiments (no production changes)

1. Select fix per decision framework.
2. Implement behind flag (default OFF).
3. Locked audit set: label-level comparison old vs new.
4. All controls on new evaluator.
5. Stochastic stability on new evaluator (must pass 100% at temp=0).
6. Fix C: validate extraction on locked audit set. Failure criteria: empty root_cause in > 2/10.
7. P1-LEAK-ISSUES: enrichment leakage audit.
8. Deliver: Phase 1 report.

**Gate**: Drift <= 1 justified flip. Controls pass. Stability passes. Extraction meets criteria (if Fix C).

#### Phase 2: Choose Fix

Review Phase 0 + Phase 1. Select. Document rationale citing experiment IDs. If nothing passes, iterate.

#### Phase 3: Implement Behind Flag

Default OFF. Both paths produce output when ON. Fix D ON by default.

#### Phase 4: Dual-Score Shadow Run (MANDATORY)

1. 58 cases x selected conditions x 1 trial, dual scoring.
2. Log `reasoning_correct_old` and `reasoning_correct_new` per case.
3. Per-condition disagreement rates.
4. **Scaled audit**: if disagreement rate <= 20%, audit 10 per condition. If > 20%, audit 20 per condition. Classify per taxonomy (8.7).
5. For each audited disagreement: determine correct verdict per rubric.
6. Deliver: Phase 4 report.

**Gate**: Directionally correct >= 80% of audited flips. Locked set stable. Controls pass.

#### Phase 5: Switch Primary Metric

Only if Phase 4 passes. Switch default. Archive old results. Document.

---

### 13. Do Not Do

1. Do NOT classify empty reasoning as incorrect. None, not False.
2. Do NOT switch production metric without Phase 4 shadow run.
3. Do NOT change classifier prompt AND input format simultaneously. Test separately.
4. Do NOT fold heuristic recovery into primary metrics.
5. Do NOT accept aggregate improvement if label-level audit shows > 1 unjustified flip.
6. Do NOT assume baseline and LEG rates must converge.
7. Do NOT include plan_steps or verification in primary reasoning input.
8. Do NOT leave eval_model hard-coded during any experiment.
9. Do NOT run experiments without complete audit logs.
10. Do NOT skip semantic annotation or inter-rater check.
11. Do NOT proceed Phase 0 -> Phase 1 if any hypothesis inconclusive (after cap: treat as confirmed).
12. Do NOT report comparisons with > 10pp unclassified gap in ANY figure, table, or claim.
13. Do NOT iterate on classifier prompt tuning after control failure. Disqualify and replace.
14. Do NOT use an unstable classifier (non-100% at temp=0) without mandatory majority voting.

---

### 14. Metrics for Success

| Metric | Target | Type |
|---|---|---|
| Format invariance (minimal cases) | 100% same verdict on E1-E3-equivalent inputs | Invariant |
| Parse false negative rate | 0% | Correctness |
| Locked audit drift (30 cases) | <= 1 justified flip | Stability |
| Shadow disagreement: directionally correct | >= 80% of audited flips | Quality |
| Unclassified rate | Reported; > 10pp gap invalidates comparison | Transparency |
| verbose-wrong controls | 100% NO | Safety |
| terse-correct controls | 100% YES | Safety |
| Stochastic stability at temp=0 | 100% (mandatory voting if not) | Reliability |
| Inter-rater agreement | >= 85% (second annotator) | Rubric validity |

Gap convergence is NOT a success criterion. Measurement validity is.

---

### 15. Risk Analysis

#### 15.1 Enrichment Asymmetry
Even restricted enrichment creates information asymmetry. Fix C eliminates this by normalizing both sides. Fix A is fallback only.

#### 15.2 Extraction Errors (Fix C)
Rule-based extraction is tried first. LLM fallback on failure. Raw passthrough if both fail. Locked audit validates. Extraction failure criteria defined (Section 6.4).

#### 15.3 Classifier Model Sensitivity
P0-0 quantifies. If high: dual-report on both models.

#### 15.4 Denominator Asymmetry
10pp rule prevents invalid comparisons from appearing anywhere.

#### 15.5 Overfitting
5/30 locked cases are v2-only.

#### 15.6 Classifier Unreliability
Contingency defined (Section 8.8). Hard disqualification trigger on control failure.

---

### 16. Permanent Regression Tests

ALL tests reference minimal reproducible cases from Section 8.6. If a minimal case is broken, the test MUST fail immediately.

#### 16.1 Measurement Invariance (CORE)

```
test_measurement_invariance_h1:
    Input: {H1_minimal_case}.R_full and {H1_minimal_case}.R_short
    Precondition: Both contain identical E1-E3 elements per rubric.
    Assert: classifier verdict is identical for R_full and R_short.
    References: H1 minimal reproducible case.

test_measurement_invariance_h2:
    Input: {H2_minimal_case}.bug_diagnosis_only and {H2_minimal_case}.with_issues
    Assert: if with_issues classifies YES, bug_diagnosis_only ALSO classifies YES
            (under the repaired evaluator).
    References: H2 minimal reproducible case.
```

#### 16.2 Format Invariance

```
test_same_content_freeform_vs_normalized:
    Given: Reasoning with E1-E3 present.
    When: Presented as (a) freeform, (b) normalized slots.
    Then: Identical verdict.

test_baseline_passthrough_byte_identical:
    Given: Standard baseline reasoning, no LEG fields, experiment flag OFF.
    Then: String reaching classifier is byte-for-byte identical to input.
```

#### 16.3 Parse Robustness

```
test_reasoning_lost_produces_none:
    Input: {H3_minimal_case}
    Assert: reasoning_correct is None.
    References: H3 minimal reproducible case.

test_structure_missing_produces_none:
    Given: parse_category == STRUCTURE_MISSING.
    Then: reasoning_correct is None.
```

#### 16.4 eval_model

```
test_eval_model_parameter_honored:
    Given: llm_classify(eval_model="test-model").
    Then: Actual model used is "test-model".
    Note: This test MUST fail if eval_model is ever ignored again.

test_eval_model_logged:
    Given: Any evaluation.
    Then: Result contains eval_model_actual matching actual model.
```

#### 16.5 Stochastic Stability

```
test_classifier_deterministic_at_temp_zero:
    Given: Same reasoning, same case, same prompt, temperature=0.
    When: Run 3 times.
    Then: All 3 verdicts identical.
```

#### 16.6 Denominator Integrity

```
test_none_excluded_from_rates:
    Given: 10 cases, 3 None.
    Then: Denominator is 7.

test_unclassified_always_reported:
    Then: N_unclassified present and >= 0.
```

#### 16.7 Solution Leakage Guard

```
test_plan_steps_excluded:
    Given: LEG output with plan_steps.
    Then: Classifier input does NOT contain plan_steps content.

test_verification_excluded:
    Given: LEG output with verification.
    Then: Classifier input does NOT contain verification evidence.
```

#### 16.8 Brevity / Verbosity Controls

```
test_terse_correct_yes:
    Input: known-terse-but-correct case from P0-2.
    Assert: YES.

test_verbose_wrong_no:
    Input: known-verbose-but-wrong case from P0-3.
    Assert: NO.
```
