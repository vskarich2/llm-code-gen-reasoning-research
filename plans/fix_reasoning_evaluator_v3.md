# Fix Plan: Reasoning Evaluator — Measurement Repair

**Version:** v3
**Date:** 2026-03-26
**Status:** Plan only. No code changes.
**Supersedes:** fix_reasoning_evaluator_v2.md
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## 1. Executive Summary

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

No code will be written until Phase 0 (measurement audit) is complete with conclusive hypothesis verdicts.

---

## 2. Hypotheses and Falsification Experiments

### H1: Classifier Brevity Bias

**Claim**: The LLM classifier produces systematically lower `reasoning_correct=True` rates for semantically equivalent reasoning expressed in shorter form.

**Causal mechanism**: The prompt says "Be conservative: only YES if the reasoning clearly identifies the correct mechanism" and "Vague reasoning ('I fixed the bug') is NOT correct reasoning." These instructions conflate brevity with vagueness.

**Falsification experiment** (P0-1):

Take 15 cases from existing data where baseline `reasoning_correct=YES` (verified manually). For each, create three compressed versions:

- **Compression A**: First sentence of the original reasoning only.
- **Compression B**: Manually written one-sentence root-cause summary that names the mechanism correctly (simulating what a skilled model would produce in `bug_diagnosis`). The annotator writes this WITHOUT looking at the LEG output.
- **Compression C**: The actual `bug_diagnosis` field from LEG-reduction output for the same case (if available), or a LEG-style terse summary constructed to match the `bug_diagnosis` format.

Run the classifier on all 4 versions (full + 3 compressed) for each case. Record all verdicts with full audit logs.

**H1 is confirmed if**: >= 5/15 cases flip YES->NO on any compression regime while the semantic content (per the rubric in Section 3) is preserved.

**H1 is falsified if**: <= 2/15 cases flip. In this case the gap between baseline and LEG is explained by H2 (genuine information loss) or H3 (parse corruption), not format bias.

**H1 is inconclusive if**: 3-4/15 flip. In this case, refine the experiment: increase sample to 25 cases, add a second annotator for compression B, and re-run. Do NOT proceed to Phase 1 under inconclusive results.

**Controls**:
- **Negative control: known-terse-but-correct** (P0-2): 5 manually written one-sentence summaries that correctly identify the mechanism. Must ALL classify as YES. If ANY classify as NO, the classifier has a fundamental brevity defect that no enrichment fix can resolve.
- **Negative control: known-verbose-but-wrong** (P0-3): 5 verbose paragraphs (200+ words) that sound plausible but identify the WRONG mechanism. Must ALL classify as NO. If ANY classify as YES, the classifier rewards verbosity over correctness and the measurement instrument is fundamentally unreliable.

### H2: Reasoning Information Loss

**Claim**: The mapping from structured LEG output to the classifier's `reasoning` input systematically discards causal elements that the classifier requires to produce a YES verdict.

**Causal mechanism**: execution.py:486 maps `reasoning = lr_parsed["bug_diagnosis"]`. The full mechanistic reasoning is stored in other fields that never reach the classifier.

**Falsification experiment** (P0-4, P0-5):

For 10 cases where LEG-reduction produced valid structured output:

1. Apply the semantic completeness rubric (Section 3) to `bug_diagnosis` alone, full LEG output, and matched baseline reasoning.
2. Run the classifier on `bug_diagnosis` only (current behavior).
3. Run the classifier on `bug_diagnosis` + `issues_found` only (NO plan_steps, NO verification — see Section 5.1 for why).

**H2 is confirmed if**: `bug_diagnosis` alone scores lower on E1-E4 than full LEG output in >= 7/10 cases, AND classifier verdicts flip NO->YES in >= 6/10 cases when given the additional issues_found content.

**H2 is falsified if**: `bug_diagnosis` contains all elements E1-E3 in >= 8/10 cases (i.e., the one-liner IS informationally complete), or classifier verdicts do not change even with additional content.

**H2 is inconclusive if**: Element scores are mixed (some cases complete, some not) without a clear pattern. In this case, expand annotation to 20 cases with a second annotator and re-run. Do NOT proceed under inconclusive results.

### H3: Parse Failure Corruption

**Claim**: Parse failures cause `reasoning=""` to reach the classifier, which produces `reasoning_correct=False` — a false negative indistinguishable from genuinely incorrect reasoning.

**Falsification experiment** (P0-6, P0-7):

1. Count parse failure rates per condition across existing ablation data: total cases, cases with `parse_error` set, cases with `reasoning=""` AND `parse_error` set.
2. For each REASONING_LOST case: inspect the raw model output. Does the raw output contain recognizable reasoning text that was lost in parsing?

**H3 is confirmed if**: >= 5% of cases in any non-baseline condition have `reasoning=""` due to parse failure, AND the raw output for those cases contains identifiable reasoning text.

**H3 is falsified if**: Parse failure rates are < 1% across all conditions, or parse failures genuinely correspond to cases where the model produced no reasoning.

**H3 is inconclusive if**: Failure rates are 1-5% and raw inspection is mixed. In this case, inspect all cases (not a sample) and classify each as genuine-empty vs lost-in-parse. Do NOT proceed under inconclusive results.

### eval_model Parameter Bug

**Confirmed**: evaluator.py:171 hard-codes `model = "gpt-5.4-mini"`, ignoring the `eval_model` parameter on line 143. This is not a hypothesis — it is a verified code defect.

**Required isolation experiment** (P0-0 — MUST run before all other experiments):

Run the locked audit set (Section 7) with:
- (A) the hard-coded model (`gpt-5.4-mini`)
- (B) the intended eval_model (e.g., `gpt-5-mini`)

Record label-by-label comparison. Report drift count and log every flipped label.

**Purpose**: Isolate the effect of the model change so it is not confounded with later evaluator changes. This is a prerequisite for all Phase 0 experiments.

---

## 3. Semantic Completeness Rubric

### 3.1 Required Elements

| Element | Definition | Example (alias_config_a) |
|---|---|---|
| **E1: Root Cause** | Names the specific defect | "create_config returns DEFAULTS by reference" |
| **E2: Manifestation Path** | Explains HOW the bug produces observable failure | "Caller mutations corrupt global state, affecting subsequent calls" |
| **E3: Invariant or Mechanism** | Names the violated principle or causal rule | "Aliasing: shared mutable reference" or "Function purity violated" |
| **E4: Fix Rationale** (optional) | Explains why the fix addresses the root cause | "Returning dict(DEFAULTS) creates an independent copy" |

### 3.2 Annotation Protocol

For each matched baseline/LEG case in the H1/H2 experiments:

1. Annotate the **baseline reasoning** for E1-E4 presence. Binary: present (1) or absent (0).
2. Annotate the **LEG bug_diagnosis** alone for E1-E4.
3. Annotate the **full LEG output** (all structured fields) for E1-E4.
4. Record element counts: `baseline_elements`, `leg_diag_elements`, `leg_full_elements`.

### 3.3 Inter-Rater Consistency Requirement

The annotator MUST re-label a random subset of 5 cases (out of the 10-15 annotated) on a separate day without access to their prior labels. Compute element-level agreement: for each case x element pair, does the re-label match the original?

**Required agreement**: >= 90% element-level consistency (i.e., out of 5 cases x 4 elements = 20 judgments, at least 18 must match).

**If agreement < 90%**: The rubric is too subjective. Refine element definitions with additional examples and disambiguation rules, then re-annotate the full set. Do NOT use inconsistent annotations to support causal claims.

### 3.4 Interpretation Rules

- If `baseline_elements == leg_diag_elements` for >= 8/10 cases: Information loss is NOT the dominant problem. Brevity alone drives the classifier gap (H1 dominant).
- If `baseline_elements > leg_diag_elements` BUT `baseline_elements == leg_full_elements` for >= 7/10 cases: Information IS present in LEG output but not reaching the classifier (H2 dominant).
- If `baseline_elements > leg_full_elements` for >= 5/10 cases: The LEG schema genuinely captures LESS reasoning. The classifier gap partially reflects real information differences. No enrichment fix can close this component of the gap.

---

## 4. Parse Failure Taxonomy and Handling Policy

### 4.1 Taxonomy

| Category | Definition | Source | Example |
|---|---|---|---|
| **REASONING_LOST** | Parse succeeded for code but reasoning field is empty or None | raw_fallback, missing_key:reasoning | `reasoning=""`, `code="def f(): ..."` |
| **CODE_LOST** | Parse failed entirely; both code and reasoning empty or code is raw text | raw_fallback | `code=raw_text`, `reasoning=""` |
| **PARTIAL_JSON_RECOVERED** | JSON malformed but reasoning/code extracted via lenient/substring parser | _try_json_lenient, _try_json_substring | `parse_error="lenient-json: ..."` |
| **MALFORMED_BUT_RECOVERED** | Strict parser failed, legacy fallback succeeded with non-empty reasoning | valid_schema=False, parse_model_response success | `valid_schema=False`, reasoning non-empty |
| **STRUCTURE_MISSING** | LEG/retry: required structured fields absent, bug_diagnosis defaults to empty | parse_leg_reduction_output schema failures | `lr_parsed["bug_diagnosis"]=""` |
| **CLEAN** | No parse error; all fields present and typed correctly | Parser tier 0-3 success | `parse_error=None` |

### 4.2 Handling Policy

| Category | Classification Allowed? | reasoning_correct Behavior | Reporting |
|---|---|---|---|
| **CLEAN** | YES | Normal classifier output (True/False) | Counted in N_classified |
| **PARTIAL_JSON_RECOVERED** | YES, with flag | Normal; flag `reasoning_recovery="partial_json"` | In N_classified; N_recovered incremented |
| **MALFORMED_BUT_RECOVERED** | YES, with flag | Normal; flag `reasoning_recovery="fallback_parser"` | In N_classified; N_recovered incremented |
| **REASONING_LOST** | NO | `reasoning_correct=None`, `classify_parse_error="REASONING_LOST"` | In N_unclassified; excluded from N_classified |
| **CODE_LOST** | NO | `reasoning_correct=None`, `classify_parse_error="CODE_LOST"` | In N_unclassified |
| **STRUCTURE_MISSING** | NO | `reasoning_correct=None`, `classify_parse_error="STRUCTURE_MISSING"` | In N_unclassified |

### 4.3 Heuristic Recovery Policy

Heuristic recovery (regex extraction from malformed JSON) is permitted ONLY as secondary analysis. It NEVER enters primary metrics.

If recovery is attempted:
- Tag: `reasoning_recovery="heuristic"`.
- Log: recovery input text and output text.
- Report: in a SEPARATE column. Never blended with CLEAN or RECOVERED cases.
- Any result that includes heuristic-recovered cases in a primary metric computation is invalid.

---

## 5. Candidate Fixes

### 5.1 Prohibited Fields in Primary Reasoning Input

**Hard rule**: `plan_steps` and `verification` evidence MUST NOT be included in the primary reasoning input to the classifier unless explicitly validated in a separate gated experiment (P1-LEAK below). These fields contain solution-level information that baseline conditions do not expose:

- `plan_steps[].step` often contains the fix itself (e.g., "return dict(DEFAULTS)"). This is not reasoning ABOUT the bug; it is the solution TO the bug.
- `verification[].evidence` contains post-fix validation (e.g., "dict() confirmed to create copy — PASS"). This is success confirmation, not mechanism identification.

Including these fields in the classifier input gives LEG conditions a structural advantage over baseline, because baseline reasoning typically contains mechanism identification but not explicit fix enumeration or self-verification. This asymmetry invalidates any cross-condition comparison.

**Permitted fields for enrichment** (subject to Phase 1 validation):
- `bug_diagnosis` (always — this is current behavior)
- `issues_found[].description` + `issues_found[].evidence` (these describe the failure mechanism)
- `invariants_checked[].invariant` where status=FAIL (these identify violated invariants)

**Gated experiment P1-LEAK**: If after Phase 0 the permitted fields do not resolve the gap, test adding plan_steps as a SEPARATE experiment. Compare classifier verdicts with and without plan_steps. If the addition flips >= 3/10 extra cases to YES, the flip is likely leakage-driven and plan_steps must remain excluded.

### 5.2 Fix A: Enriched Reasoning Input (Text Concatenation)

**Mechanism**: Concatenate permitted fields (bug_diagnosis + issues_found descriptions + failed invariants) into a single string before calling `llm_classify`. Baseline: pass-through. Retry: reasoning + plan (plan excluded from primary — only reasoning).

**Why enrichment is high-risk**: Enrichment changes the measurement instrument by giving structured-output conditions more evidence than baseline receives. This can inflate reasoning_correct and make cross-condition comparison worse:

- **Information asymmetry**: Even with plan_steps excluded, `issues_found` descriptions are a form of structured analysis that baseline does not separately present.
- **Length advantage**: More text provides more keyword surface for the classifier's internal heuristics.
- **False positive path**: A model that produces wrong reasoning but correct-sounding issue descriptions could flip to YES.

**Risk level**: HIGH. This is an intervention on the evaluator, not a neutral fix. It requires full A/B validation (Phase 4 shadow run) with disagreement taxonomy before adoption.

### 5.3 Fix B: Classifier Prompt Redesign

**Mechanism**: Modify `_CLASSIFY_PROMPT` to explicitly tolerate brevity and evaluate semantic content over format.

**Risk level**: MEDIUM-HIGH. Changes all conditions including baseline. Requires re-running all experiments. Must validate against locked audit set with label-level comparison.

### 5.4 Fix C: Normalized Intermediate Representation (PRIMARY SOLUTION PATH)

**Mechanism**: Define a canonical reasoning representation with fixed slots mapping to the semantic completeness rubric:

```
{
    "root_cause": str,              # E1
    "manifestation": str,           # E2
    "mechanism_or_invariant": str,  # E3
    "fix_rationale": str | None,    # E4
    "evidence": list[str]           # supporting quotes/references
}
```

**Mapping from LEG structured output** (direct, no extraction needed):
- `root_cause` = `bug_diagnosis`
- `manifestation` = `issues_found[].description` (from last revision)
- `mechanism_or_invariant` = `invariants_checked[].invariant` where status=FAIL (from last revision)
- `fix_rationale` = EXCLUDED (this is solution-level, not reasoning-level)
- `evidence` = `issues_found[].evidence` + `invariants_checked[].evidence`

**Mapping from baseline freeform reasoning** (extraction required):
- Rule-based extraction: split reasoning into sentences, classify each as E1/E2/E3/E4 by keyword matching.
- LLM-based extraction (fallback): prompt an LLM to fill the slots from the freeform text.
- If extraction fails: fall back to passing the raw freeform reasoning unchanged.

**Mapping from retry harness**:
- `root_cause` = `reasoning` field (first sentence or main claim)
- `evidence` = `plan` steps (if they describe the problem, not the solution)

**The classifier prompt is redesigned to accept the normalized format**, explicitly evaluating each slot:
```
Does root_cause correctly name the defect? Does manifestation correctly describe how it fails?
Does mechanism_or_invariant correctly identify the violated principle?
```

**Why this is the primary solution path**: Fix C achieves true format invariance because ALL conditions pass through the same representation. It eliminates the information asymmetry problem of Fix A. It naturally enforces the solution-level information exclusion (fix_rationale is excluded by design). It enables the semantic completeness rubric to be applied programmatically.

**Risk**: Extraction errors on baseline freeform text can introduce new failures. Mitigation: validate extraction on the locked audit set. Log extraction results alongside original text. Fall back to raw reasoning if extraction fails.

**Enrichment (Fix A) is a temporary fallback ONLY if Fix C fails Phase 1 validation.** Fix A is permitted as an interim measure while Fix C is developed, but ONLY with full Phase 4 shadow validation and the field restrictions in Section 5.1.

### 5.5 Fix D: Parse Recovery Gate

**Mechanism**: Prevent classification on corrupt reasoning input per Section 4 taxonomy. Return `reasoning_correct=None` instead of `False` when reasoning is lost.

**Risk level**: LOW. Correctness fix. Applied regardless of other fix selection.

### 5.6 Fix E: eval_model Parameter Bug Fix

**Mechanism**: Replace `model = "gpt-5.4-mini"` on evaluator.py:171 with `model = eval_model or "gpt-5.4-mini"`. Log actual model used in every classifier call.

**Risk level**: LOW. Prerequisite for all other experiments. Must be isolated via P0-0.

---

## 6. Validation Matrix

### 6.1 Phase 0 Experiments (Blocking Gate)

| ID | Experiment | Input | Confirms if | Falsifies if | Inconclusive if |
|---|---|---|---|---|---|
| P0-0 | eval_model isolation | Locked audit set x 2 models | Label drift quantified | N/A (always produces data) | N/A |
| P0-1 | H1 Brevity (15 cases x 4) | Full + 3 compressed | >= 5/15 flip | <= 2/15 flip | 3-4/15 flip: expand to 25, re-run |
| P0-2 | H1 Neg: terse-correct | 5 terse correct summaries | N/A (control) | Any classify NO: fundamental defect | N/A |
| P0-3 | H1 Neg: verbose-wrong | 5 verbose wrong paragraphs | N/A (control) | Any classify YES: classifier unreliable | N/A |
| P0-4 | H2 Semantic annotation | 10 LEG cases, E1-E4 rubric | diag < full in >= 7/10 | diag == full in >= 8/10 | Mixed: expand to 20 cases |
| P0-5 | H2 Classifier effect | bug_diagnosis vs +issues_found | >= 6/10 flip NO->YES | < 3/10 flip | 3-5/10: expand sample |
| P0-6 | H3 Parse census | Existing ablation data | >= 5% in any condition | < 1% everywhere | 1-5%: inspect all cases |
| P0-7 | H3 Raw inspection | REASONING_LOST cases | Raw has reasoning text | Raw is empty | Mixed: classify each case |

### 6.2 Phase 0 Exit Conditions (BLOCKING GATE)

Phase 0 MUST produce a conclusive verdict for each hypothesis: CONFIRMED, FALSIFIED, or REFINED (experiment expanded and re-run). The following conditions BLOCK progression to Phase 1:

1. **Any hypothesis is inconclusive after one expansion round**: STOP. Reassess experimental design. Write a Phase 0 failure report explaining why the hypothesis could not be resolved.
2. **Both P0-2 controls fail** (terse-correct classifies NO AND verbose-wrong classifies YES): The classifier is fundamentally unreliable for this task. STOP. Proceed directly to Section 6.8 (classifier replacement contingency).
3. **P0-0 (eval_model isolation) shows > 5 label flips on locked audit set**: Model sensitivity is too high. All subsequent experiments must be run on BOTH models and results reported side-by-side.

**No hand-waving interpretation is permitted.** Each hypothesis verdict must cite specific experiment IDs and numeric results.

### 6.3 Audit Logging Requirements (MANDATORY — NO EXCEPTIONS)

For EVERY case evaluated in ANY experiment (Phase 0 through Phase 5):

| Field | Description |
|---|---|
| `case_id` | Benchmark case identifier |
| `condition` | Experimental condition |
| `raw_model_output` | Complete model response (before any parsing) |
| `parsed_reasoning` | Reasoning field after parsing (what classifier currently receives) |
| `enriched_reasoning` | Enriched reasoning string (if applicable; else None) |
| `normalized_representation` | Normalized slots (if Fix C; else None) |
| `parse_error` | Parse error code, if any |
| `parse_category` | Taxonomy category from Section 4 |
| `recovery_method` | None, partial_json, fallback_parser, heuristic |
| `classifier_prompt` | Complete prompt sent to classifier LLM |
| `classifier_raw_output` | Raw response from classifier LLM |
| `classifier_verdict` | Parsed YES/NO/None |
| `classifier_failure_type` | Parsed failure type |
| `classifier_parse_error` | Classifier output parse error, if any |
| `eval_model_intended` | The eval_model parameter passed by caller |
| `eval_model_actual` | The model actually used (detects line 171 bug) |
| `semantic_elements` | E1-E4 annotation (if in annotation study) |
| `experiment_id` | Which experiment produced this record (P0-1, P1-3, etc.) |

**Hard rule**: Any experiment run without complete audit logs is automatically invalid. No logs = no results. This is not a suggestion.

### 6.4 Stop Conditions (Hard Abort Criteria)

| Condition | Abort Action |
|---|---|
| More than 1/10 known-good YES cases flip to NO under any proposed change | Abort that change. Debug before proceeding. |
| More than 1/10 known-good NO cases flip to YES under any proposed change | Abort that change. False positive risk. |
| Enriched-vs-raw disagreement exceeds 30% on baseline conditions | Enrichment is modifying baseline. Abort enrichment approach. |
| Baseline label drift exceeds 1 flip on locked audit set (30 cases) unless manually justified | Abort rollout. |
| Unclassified rate exceeds 20% for any condition after gating | Fix parsing before gating. |
| verbose-wrong controls classify as YES after any change | Classifier rewards verbosity. Revert change. |
| terse-correct controls classify as NO after any change | Classifier penalizes brevity. Change did not fix H1. |
| BOTH old and new evaluators disagree with semantic rubric on > 20% of audited cases | Both evaluators are unreliable. Proceed to Section 6.8. |

### 6.5 Stochastic Stability Requirement

Before any evaluator (old or new) is used for primary metrics, run the classifier 3 times on 20 identical inputs (same reasoning, same case, same prompt).

**Required**: >= 95% verdict consistency (i.e., out of 20 cases x 3 runs = 60 verdicts, at most 3 cases show any inter-run disagreement).

**If consistency < 95%**: The classifier is stochastically unstable. Mitigation options: (a) use majority vote across 3 calls, (b) increase temperature to 0 (verify it is 0), (c) switch to a more deterministic classifier model. Do NOT use an unstable classifier as a primary metric.

### 6.6 Minimal Reproducible Cases

For EVERY failure mode discovered (H1, H2, H3), construct a minimal synthetic example that reproduces the issue deterministically:

- **H1 minimal case**: A case_id, a full reasoning string R_full that classifies YES, and a compressed R_short (preserving all E1-E3 elements per rubric) that classifies NO. This pair is the canonical brevity bias reproducer.
- **H2 minimal case**: A case_id, a LEG bug_diagnosis that classifies NO, and the same bug_diagnosis + issues_found that classifies YES. This pair is the canonical information loss reproducer.
- **H3 minimal case**: A raw model output containing valid reasoning, a parse_error that causes reasoning="", and the resulting False verdict. This triple is the canonical parse corruption reproducer.

These minimal cases become permanent regression test fixtures.

### 6.7 Disagreement Taxonomy (Mandatory for Phase 4)

For every disagreement between old and new evaluator in the shadow run, classify the disagreement into:

| Category | Definition | Example |
|---|---|---|
| **PARSE_RELATED** | Old evaluator received empty/corrupt reasoning; new evaluator received correct reasoning (or None) | Old: reasoning="" -> NO. New: gated -> None. |
| **BREVITY_RELATED** | Old and new received same reasoning text; difference is due to prompt change or length sensitivity | Same short reasoning. Old: NO. New (prompt redesign): YES. |
| **INFORMATION_RELATED** | New evaluator received additional reasoning content (enrichment or normalization) that old did not | Old: bug_diagnosis only -> NO. New: +issues_found -> YES. |
| **CLASSIFIER_ERROR** | Neither evaluator's verdict matches the semantic rubric (human judgment) | Both wrong, or old right and new wrong. |

**Every disagreement in the audited sample MUST be assigned exactly one category.** If a disagreement does not fit any category, add a new category and document it.

### 6.8 Classifier Replacement Contingency

If after all fixes the classifier still fails controls (terse-correct produces NO, or verbose-wrong produces YES), or if both old and new evaluators disagree with the semantic rubric on > 20% of audited cases, the LLM classifier is fundamentally unreliable for this task.

**Contingency plan**:
1. Replace with a hybrid evaluator: LLM classification + rule-based verification against the semantic completeness rubric (E1-E3 keyword matching on the normalized representation).
2. If hybrid also fails: replace with a purely rule-based evaluator using the E1-E3 keyword matching from the rubric, accepting lower recall in exchange for higher precision.
3. If rule-based is too coarse: abandon automated reasoning classification. Report only code_correct (from execution tests) as the primary metric. Report reasoning classification as a secondary, explicitly-unreliable metric.

This contingency is not expected to trigger, but it MUST be defined because "the classifier is reliable" is an assumption, not a proven fact.

---

## 7. Backward Compatibility — Strict Target

### 7.1 Locked Audit Set

Select 30 baseline cases (stratified by failure_mode and difficulty) where `reasoning_correct` has been manually verified. At least 5 must be v2-only cases.

- 15 cases where reasoning_correct = YES (correct reasoning, manually confirmed)
- 15 cases where reasoning_correct = NO (wrong reasoning, manually confirmed)

### 7.2 Label-Level Stability

Under any proposed evaluator change, run the locked audit set through the new evaluator. Compare label-by-label.

- If ALL 30 labels match: compatibility confirmed.
- If 1 label changes: log case_id, old verdict, new verdict, raw reasoning input (old and new), and justify the change as a genuine improvement. One justified flip is acceptable.
- If 2-3 labels change: each MUST be logged and justified individually. If any flip cannot be explained as a genuine improvement, abort.
- If > 3 labels change: abort rollout. The measurement instrument has drifted beyond acceptable limits.

**No quiet drift. No "within noise." No aggregate comparisons. Label-level stability only.**

---

## 8. Denominator and Reporting Policy

### 8.1 Rate Computations

For each condition, compute and report ALL of the following:

| Metric | Formula |
|---|---|
| `N_total` | Total cases evaluated |
| `N_classified` | Cases where `reasoning_correct` is True or False |
| `N_unclassified` | Cases where `reasoning_correct` is None |
| `N_parse_failed` | Cases in REASONING_LOST, CODE_LOST, or STRUCTURE_MISSING |
| `N_recovered` | Cases where `reasoning_recovery` is not None |
| `reasoning_correct_rate` | `sum(reasoning_correct == True) / N_classified` |
| `leg_rate` | `sum(reasoning_correct == True AND code_correct == False) / N_classified` |
| `true_success_rate` | `sum(reasoning_correct == True AND code_correct == True) / N_classified` |
| `lucky_fix_rate` | `sum(reasoning_correct == False AND code_correct == True) / N_classified` |
| `true_failure_rate` | `sum(reasoning_correct == False AND code_correct == False) / N_classified` |

### 8.2 Mandatory Reporting Rules

1. Every results table MUST include columns for: `N_total`, `N_classified`, `N_unclassified`, `N_parse_failed`, `N_recovered`.
2. If `N_unclassified / N_total > 10%` for any condition: print warning.
3. **Hard rule**: If `N_unclassified` rates differ by > 10 percentage points between conditions being compared, the comparison is INVALID and MUST NOT be reported as a primary result. It may be reported as a secondary result with explicit caveat.

### 8.3 None Handling

`reasoning_correct=None` cases are EXCLUDED from all rate computations. They are NEVER counted as False. They are NEVER silently dropped. They are always reported in the unclassified column.

---

## 9. Decision Framework

After Phase 0 experiments are complete with conclusive verdicts:

| H1 Verdict | H2 Verdict | H3 Verdict | Recommended Fix Path |
|---|---|---|---|
| CONFIRMED | FALSIFIED | Any | Fix B (prompt redesign) or Fix C (normalized repr). Enrichment (Fix A) is unnecessary. |
| FALSIFIED | CONFIRMED | Any | Fix C (normalized repr) as primary. Fix A (restricted enrichment per 5.1) as interim fallback only if Fix C fails Phase 1. |
| CONFIRMED | CONFIRMED | Any | Fix C (normalized repr) — addresses both. It is the only fix that achieves symmetric representation. |
| FALSIFIED | FALSIFIED | CONFIRMED | Fix D (parse gate) only. H1/H2 do not need fixing. |
| CONFIRMED | CONFIRMED | CONFIRMED | Fix D first (correctness), Fix E immediately, then Fix C (format invariance). |
| ALL FALSIFIED | ALL FALSIFIED | ALL FALSIFIED | The problem is smaller than hypothesized, or experiments lacked sensitivity. Write a null-result report. Do not ship unnecessary fixes. |

**Fix D (parse gate) and Fix E (eval_model bug) are applied regardless of hypothesis results.** They are correctness fixes.

**Fix C is the primary solution path in all cases where H1 or H2 is confirmed.** Fix A is a fallback, not a default.

---

## 10. Rollout Phases

### Phase 0: Measurement Audit (BLOCKING GATE)

1. Fix eval_model bug (Fix E). Trivial one-line correctness fix.
2. Run P0-0 (eval_model isolation on locked audit set).
3. Run P0-1 through P0-7.
4. Produce semantic completeness annotations with inter-rater consistency check.
5. Construct minimal reproducible cases for each confirmed hypothesis.
6. Deliver: Phase 0 report with conclusive hypothesis verdicts (CONFIRMED/FALSIFIED) and numeric evidence.

**Exit gate**: All hypotheses resolved. All controls pass. If any hypothesis is inconclusive after expansion, STOP.

### Phase 1: Offline Evaluation Experiments (no production changes)

1. Based on Phase 0 verdicts, select fix per decision framework (Section 9).
2. Implement candidate fix behind flag (default OFF).
3. Run locked audit set through both old and new evaluator. Label-level comparison.
4. Run all positive and negative controls on new evaluator.
5. Run stochastic stability test (20 cases x 3 runs).
6. If Fix C selected: validate extraction on locked audit set. Log every extraction alongside original.
7. Run P1-LEAK test if enrichment fields beyond bug_diagnosis + issues_found are proposed.
8. Deliver: Phase 1 report with label-level drift, control results, stability results.

**Exit gate**: All stop conditions pass. Locked audit drift <= 1 justified flip. All controls pass. Stability >= 95%.

### Phase 2: Choose Fix Based on Evidence

1. Review Phase 0 and Phase 1 reports.
2. Select final fix. Document rationale citing specific experiment IDs and results.
3. If no fix passes all stop conditions, iterate on design. Do NOT force a fix through.

### Phase 3: Implement Behind Flag

1. Implement in production code. Default OFF.
2. Both old and new paths produce output simultaneously when ON.
3. Parse gate (Fix D) is ON by default (it is a correctness fix, not a measurement change).

### Phase 4: Dual-Score Shadow Run (MANDATORY)

1. Run full ablation (58 cases x selected conditions x 1 trial) with dual scoring.
2. Log `reasoning_correct_old` and `reasoning_correct_new` for every case.
3. Compute per-condition disagreement rates.
4. Audit stratified sample: 10 disagreements per condition, classified per disagreement taxonomy (Section 6.7).
5. For each audited disagreement: determine which verdict is correct per semantic rubric.
6. Deliver: Phase 4 report with disagreement rates, taxonomy breakdown, and per-case audit.

**Exit gate**: Disagreement is directionally correct in >= 80% of audited flips. Locked audit set stable. All controls pass. No catastrophic stop condition triggered.

### Phase 5: Switch Primary Metric

1. Only if Phase 4 passes all gates.
2. Switch default to new evaluator.
3. Archive all old results.
4. Document in paper methodology.

---

## 11. Do Not Do

1. **Do NOT silently reclassify parse failures as incorrect reasoning.** If reasoning is unrecoverable, the result is None, not False.

2. **Do NOT silently switch production metric from raw to enriched reasoning without completing Phase 4 shadow run.**

3. **Do NOT change the classifier prompt AND the reasoning input format at the same time.** That destroys identifiability. Test separately.

4. **Do NOT fold heuristic parse recovery into primary metrics.** Report separately or exclude.

5. **Do NOT accept aggregate improvements if label-level audit shows > 1 unjustified flip.**

6. **Do NOT assume baseline and LEG rates must converge.** The goal is measurement validity, not rate equality.

7. **Do NOT include plan_steps or verification evidence in primary reasoning input.** These contain solution-level information. Gated experiment (P1-LEAK) required before any exception.

8. **Do NOT leave the hard-coded eval_model unfixed during any experiment.** Fix E is prerequisite zero.

9. **Do NOT run any experiment without complete audit logs per Section 6.3.** No logs = no results.

10. **Do NOT skip the semantic completeness annotation or the inter-rater consistency check.** Without verified annotations, no causal claim about information loss is supportable.

11. **Do NOT proceed from Phase 0 to Phase 1 if any hypothesis is inconclusive.** Expand and re-run. Uncertainty does not license action.

12. **Do NOT report cross-condition rate comparisons where unclassified rates differ by > 10pp.** Such comparisons are invalid due to denominator asymmetry.

---

## 12. Metrics for Success

| Metric | Target | Type | Rationale |
|---|---|---|---|
| Classifier agreement on semantically equivalent reformulations | >= 90% same verdict | Calibration | Format invariance |
| Parse-induced false negative rate | 0% | Correctness | Parse failures produce None, never False |
| Baseline label drift (locked 30-case set) | <= 1 justified flip | Stability | Measurement continuity |
| Shadow run disagreement: directionally correct | >= 80% of audited flips match rubric | Quality | Changes are improvements, not noise |
| Unclassified rate per condition | Reported; warning > 10%; comparison invalid > 10pp gap | Transparency | No silent denominator shifts |
| verbose-wrong controls | 100% classify NO | Safety | No verbosity reward |
| terse-correct controls | 100% classify YES | Safety | Brevity does not penalize correctness |
| Stochastic stability | >= 95% consistency across 3 runs | Reliability | Classifier is deterministic enough |
| Inter-rater annotation consistency | >= 90% element-level agreement | Rubric validity | Annotations support causal claims |

**"Gap between baseline and LEG <= X%" is NOT a success criterion.** The gap reflects whatever reality exists. The goal is to measure it correctly.

---

## 13. Risk Analysis

### 13.1 Enrichment Creates Asymmetry
Even restricted enrichment (bug_diagnosis + issues_found, excluding plan_steps/verification) gives LEG conditions more text than baseline. This is less severe than unrestricted enrichment but still creates measurable asymmetry. Fix C eliminates this by normalizing both sides.

### 13.2 Extraction Errors in Normalized Representation
Fix C requires extraction from baseline freeform text. If extraction drops E2 or E3, a YES case flips to NO due to extraction failure, not evaluator improvement. Mitigation: locked audit set validation, extraction logged alongside original, fallback to raw reasoning on extraction failure.

### 13.3 Classifier Model Sensitivity
Brevity bias may be model-specific. P0-0 quantifies this. If model sensitivity is high, all experiments must dual-report on both models.

### 13.4 Unclassified Rate Creates Denominator Asymmetry
Parse gate increases unclassified rate for high-parse-failure conditions. The 10pp comparison invalidity rule (Section 8.2) prevents this from silently biasing comparisons.

### 13.5 Overfitting to Current Cases
Locked audit set and annotation study use current benchmark cases. At least 5/30 locked cases must be v2-only to mitigate.

### 13.6 Classifier Fundamental Unreliability
The classifier is assumed to be reliable. If controls fail (Section 6.8), this assumption is wrong. Contingency plan defined.

---

## 14. Permanent Regression Tests

### 14.1 Format Invariance

```
test_same_semantic_content_different_formats:
    Given: Reasoning text R correctly identifying root cause.
    When: R presented as (a) freeform, (b) one-sentence, (c) normalized slots.
    Then: Classifier verdict identical for all three.

test_empty_reasoning_never_false_with_parse_error:
    Given: reasoning="" AND parse_error set.
    Then: reasoning_correct is None, not False.

test_baseline_passthrough_byte_identical:
    Given: Standard parsed dict with reasoning="some text", no LEG fields.
    Then: Reasoning reaching classifier is byte-for-byte identical to input.
    Flagged: If any transformation applied under experiment flag, flag must be OFF.
```

### 14.2 Brevity Robustness

```
test_terse_correct_classified_yes:
    Input: {minimal_h1_case}.R_short (from minimal reproducible case).
    Assert: reasoning_correct == True.

test_verbose_wrong_classified_no:
    Input: 200-word paragraph identifying wrong mechanism.
    Assert: reasoning_correct == False.
```

### 14.3 Parse Robustness

```
test_reasoning_lost_produces_none:
    Given: parse_category == REASONING_LOST.
    Then: reasoning_correct is None.

test_structure_missing_produces_none:
    Given: parse_category == STRUCTURE_MISSING.
    Then: reasoning_correct is None.

test_recovered_reasoning_flagged:
    Given: reasoning recovered via fallback parser.
    Then: reasoning_recovery field is non-None.
```

### 14.4 eval_model

```
test_eval_model_parameter_honored:
    Given: llm_classify(eval_model="test-model").
    Then: Actual model used is "test-model", not "gpt-5.4-mini".

test_eval_model_logged:
    Given: Any evaluation.
    Then: Result contains eval_model_actual matching actual model used.
```

### 14.5 Stochastic Stability

```
test_classifier_deterministic:
    Given: Same reasoning, same case, same prompt.
    When: Run classifier 3 times.
    Then: All 3 verdicts identical.
```

### 14.6 Denominator Integrity

```
test_none_excluded_from_rates:
    Given: 10 cases, 3 with reasoning_correct=None.
    Then: Rate denominator is 7.

test_unclassified_always_reported:
    Given: Any results summary.
    Then: N_unclassified column present and >= 0.
```

### 14.7 Solution Leakage Guard

```
test_plan_steps_not_in_primary_reasoning:
    Given: LEG output with plan_steps.
    Then: The reasoning string sent to classifier does NOT contain plan_steps content
          (unless P1-LEAK experiment explicitly enabled).

test_verification_evidence_not_in_primary_reasoning:
    Given: LEG output with verification[].evidence.
    Then: The reasoning string sent to classifier does NOT contain verification evidence.
```
