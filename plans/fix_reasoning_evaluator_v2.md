# Fix Plan: Reasoning Evaluator — Measurement Repair

**Version:** v2
**Date:** 2026-03-25
**Status:** Plan only. No code changes.
**Supersedes:** fix_reasoning_evaluator.md (v1)
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## 1. Executive Summary

**Current baseline-vs-LEG reasoning comparisons are invalid.** The reasoning evaluator (`evaluator.py:llm_classify`) is not format-invariant: the same model reasoning expressed in baseline freeform format and LEG structured format receives systematically different classifier verdicts. This is not a suspected bias — it is a structural defect in how reasoning reaches the classifier.

Three independent pathologies interact:

1. **H1 — Classifier brevity bias**: The LLM judge penalizes short reasoning even when semantically correct, because the prompt instructs conservative evaluation.
2. **H2 — Reasoning information loss**: The LEG-reduction condition maps only `bug_diagnosis` (one sentence) to the classifier's `reasoning` input, discarding `plan_steps`, `revision_history`, `verification`, and `invariants_checked`. The retry harness discards `plan` steps.
3. **H3 — Parse failure corruption**: When parsing fails, `reasoning=""` reaches the classifier, which produces a definitive `reasoning_correct=False` instead of `None`. This injects false negatives into conditions with higher parse failure rates.

Additionally, **evaluator.py:171 hard-codes `model = "gpt-5.4-mini"`**, completely ignoring the `eval_model` parameter passed by callers. Every experiment that intended to use a different eval model silently used the hard-coded default. This must be treated as part of the measurement system failure.

**Until these defects are characterized and repaired, ALL cross-condition reasoning comparisons — including LEG rate, true_success rate, and reasoning_action_gap — are unreliable for conditions that use non-baseline output formats (LEG-reduction, retry harness, contract-gated).** Baseline-only results are unaffected by H2 and H3, but may be affected by H1 if the classifier's brevity sensitivity varies with model or prompt.

No code will be written until Phase 0 (measurement audit) and Phase 1 (offline experiments) are complete.

---

## 2. Hypotheses and Falsification Experiments

### H1: Classifier Brevity Bias

**Claim**: The LLM classifier (`_CLASSIFY_PROMPT`) produces systematically lower `reasoning_correct=True` rates for semantically equivalent reasoning expressed in shorter form.

**Causal mechanism**: The prompt says "Be conservative: only YES if the reasoning clearly identifies the correct mechanism" and "Vague reasoning ('I fixed the bug') is NOT correct reasoning." These instructions conflate brevity with vagueness.

**Falsification experiment** (Phase 0):

Take 15 cases from existing data where baseline `reasoning_correct=YES` with high confidence (verified manually). For each, create three compressed versions:

- **Compression A**: First sentence of the original reasoning only.
- **Compression B**: Manually written one-sentence root-cause summary that names the mechanism correctly (simulating what a skilled model would produce in `bug_diagnosis`).
- **Compression C**: Extract `bug_diagnosis` from actual LEG-reduction output for the same case (if available), or construct a LEG-style terse summary.

Run the classifier on all 4 versions (full + 3 compressed) for each case. Record verdicts.

**H1 is confirmed if**: >= 5/15 cases flip YES->NO on any compression regime while the semantic content (per the rubric in Section 3) is preserved.

**H1 is falsified if**: <= 2/15 cases flip, indicating the classifier tolerates brevity when the mechanism is named correctly. In this case, the gap between baseline and LEG is likely explained by H2 (genuine information loss), not pure format bias.

**Controls**:
- **Negative control (known-terse-but-correct)**: 5 manually written one-sentence summaries that correctly identify the mechanism. Must classify as YES. If they don't, the classifier has a fundamental brevity problem regardless of enrichment.
- **Negative control (known-verbose-but-wrong)**: 5 verbose paragraphs (200+ words) that sound plausible but identify the WRONG mechanism. Must classify as NO. If they classify as YES, the classifier rewards verbosity over correctness.

### H2: Reasoning Information Loss

**Claim**: The mapping from structured LEG output to the classifier's `reasoning` input systematically discards causal elements that the classifier requires to produce a YES verdict.

**Causal mechanism**: execution.py:486 maps `reasoning = lr_parsed["bug_diagnosis"]`. The full mechanistic reasoning — plan steps, verification evidence, invariant analysis, issue descriptions — is stored in `lr_parsed` but never reaches the classifier.

**Falsification experiment** (Phase 0):

For 10 cases where LEG-reduction produced valid structured output:

1. Run the classifier on `bug_diagnosis` only (current behavior).
2. Run the classifier on all LEG fields concatenated into a single text block.
3. Apply the semantic completeness rubric (Section 3) to both `bug_diagnosis` alone and the full LEG output.

**H2 is confirmed if**: The full LEG output scores higher on the semantic rubric AND the classifier verdicts flip NO->YES in >= 6/10 cases when given the full output.

**H2 is falsified if**: The full LEG output does NOT contain additional causal elements beyond `bug_diagnosis` (i.e., `bug_diagnosis` already captures everything), or the classifier verdicts do not change even with full evidence. In this case, the problem is purely H1 (classifier sensitivity), not information loss.

### H3: Parse Failure Corruption

**Claim**: Parse failures cause `reasoning=""` to reach the classifier, which then produces `reasoning_correct=False` — a false negative that is indistinguishable from genuinely incorrect reasoning.

**Causal mechanism**: `parse_structured_output()` failure -> fallback to `parse_model_response()` -> possible `reasoning=""` -> classifier runs on empty input -> returns NO.

**Falsification experiment** (Phase 0):

1. Count parse failure rates per condition across existing ablation data. For each condition: total cases, cases with `parse_error` set, cases with `reasoning=""` AND `parse_error` set.
2. For the `reasoning=""` + `parse_error` cases: inspect the raw model output. Does the raw output contain recognizable reasoning text that was lost in parsing?

**H3 is confirmed if**: >= 5% of cases in any condition have `reasoning=""` due to parse failure, AND the raw output for those cases contains identifiable reasoning text.

**H3 is falsified if**: Parse failure rates are negligible (< 1%) across all conditions, or parse failures genuinely correspond to cases where the model produced no reasoning.

### Additional: eval_model Parameter Bug

**Claim**: evaluator.py:171 hard-codes `model = "gpt-5.4-mini"`, ignoring the `eval_model` parameter.

**Falsification**: Read the code. Line 171: `model = "gpt-5.4-mini"`. The parameter `eval_model` on line 143 is never referenced in the function body. This is confirmed, not a hypothesis. It is a bug.

**Impact**: All experiments that specified `eval_model` (e.g., retry harness passes `eval_model=LEG_EVAL_MODEL="gpt-5-mini"` via runner.py:200) silently used `gpt-5.4-mini` instead. Classifier behavior may differ between models. This is a confound for any analysis of eval model sensitivity.

---

## 3. Semantic Completeness Rubric

To distinguish genuine information loss (H2) from pure format bias (H1), reasoning must be evaluated against a checklist of required causal elements.

### Required Elements

| Element | Definition | Example (alias_config_a) |
|---|---|---|
| **E1: Root Cause** | Names the specific defect or mechanism | "create_config returns DEFAULTS by reference" |
| **E2: Manifestation Path** | Explains HOW the bug produces observable failure | "Caller mutations corrupt global state, affecting subsequent calls" |
| **E3: Invariant or Mechanism** | Names the violated principle or causal rule | "Aliasing: shared mutable reference" or "Function purity violated" |
| **E4: Fix Rationale** (optional) | Explains why the fix addresses the root cause | "Returning dict(DEFAULTS) creates an independent copy" |

### Annotation Protocol

For each matched baseline/LEG case in the H1/H2 experiments:

1. Annotate the **baseline reasoning** for E1-E4 presence. Binary: present (1) or absent (0).
2. Annotate the **LEG bug_diagnosis** alone for E1-E4.
3. Annotate the **full LEG output** (all structured fields) for E1-E4.
4. Record element counts: `baseline_elements`, `leg_diag_elements`, `leg_full_elements`.

### Interpretation Rules

- If `baseline_elements == leg_diag_elements`: Information loss is NOT the problem. Brevity alone is causing the classifier gap (H1 dominant).
- If `baseline_elements > leg_diag_elements` BUT `baseline_elements == leg_full_elements`: Information IS present in LEG output but not reaching the classifier (H2 dominant). Enrichment is the correct fix.
- If `baseline_elements > leg_full_elements`: The LEG schema genuinely captures LESS reasoning. The classifier gap partially reflects real information differences, not just format bias. Enrichment would partially help but cannot close the full gap.

This annotation study is MANDATORY before selecting a fix. Without it, any "enrichment" fix is unvalidated.

---

## 4. Parse Failure Taxonomy and Handling Policy

### 4.1 Taxonomy

| Category | Definition | Source | Example |
|---|---|---|---|
| **REASONING_LOST** | Parse succeeded for code but failed for reasoning; reasoning field is empty | parse_model_response raw_fallback, parse_structured_output missing_key:reasoning | `reasoning=""`, `code="def f(): ..."` |
| **CODE_LOST** | Parse failed entirely; both code and reasoning empty or code is raw text | parse_model_response raw_fallback | `code=raw_text`, `reasoning=""` |
| **PARTIAL_JSON_RECOVERED** | JSON malformed but reasoning/code extracted via lenient/substring parser | _try_json_lenient, _try_json_substring | `parse_error="lenient-json: ..."` |
| **MALFORMED_BUT_RECOVERED** | Strict parser failed, legacy fallback succeeded with non-empty reasoning | parse_structured_output fail + parse_model_response success | `valid_schema=False`, reasoning non-empty |
| **STRUCTURE_MISSING** | LEG/retry specific: required structured fields absent, bug_diagnosis defaults to empty | parse_leg_reduction_output schema failures | `lr_parsed["bug_diagnosis"]=""` |
| **CLEAN** | No parse error; all fields present and typed correctly | Any parser tier 0-3 success | `parse_error=None` |

### 4.2 Handling Policy

| Category | Classification Allowed? | reasoning_correct Behavior | Reporting |
|---|---|---|---|
| **CLEAN** | YES | Normal classifier output (True/False) | Counted in classified denominator |
| **PARTIAL_JSON_RECOVERED** | YES, with flag | Normal, but flag `reasoning_recovery="partial_json"` | Counted in classified denominator; recovery count reported separately |
| **MALFORMED_BUT_RECOVERED** | YES, with flag | Normal, but flag `reasoning_recovery="fallback_parser"` | Counted in classified denominator; recovery count reported separately |
| **REASONING_LOST** | NO | `reasoning_correct=None`, `classify_parse_error="REASONING_LOST"` | Counted in unclassified; excluded from classified denominator |
| **CODE_LOST** | NO | `reasoning_correct=None`, `classify_parse_error="CODE_LOST"` | Counted in unclassified |
| **STRUCTURE_MISSING** | NO | `reasoning_correct=None`, `classify_parse_error="STRUCTURE_MISSING"` | Counted in unclassified |

### 4.3 Heuristic Recovery

Recovery attempts (e.g., regex extraction of bug_diagnosis from malformed JSON) are permitted ONLY as a secondary analysis. They must NEVER silently enter the primary metrics.

If recovery is attempted:
- Tag the case with `reasoning_recovery="heuristic"`.
- Log the recovery input and output.
- Report recovered cases in a SEPARATE column, never blended with CLEAN cases.
- Recovery confidence: LOW (regex-based), MEDIUM (partial JSON parse), HIGH (structured fallback with non-empty fields).

---

## 5. Candidate Fixes

### Fix A: Enriched Reasoning Input (Text Concatenation)

**Mechanism**: Before calling `llm_classify`, concatenate all reasoning-bearing fields from the parsed output into a single text string. Baseline: pass-through. LEG: bug_diagnosis + plan_steps + issues + invariants. Retry: reasoning + plan.

**Why enrichment may itself bias the metric**: Enrichment gives LEG/retry conditions MORE evidence than baseline receives. A baseline case produces ~300 chars of freeform reasoning. An enriched LEG case could produce ~1500 chars of structured text including plan steps, verification evidence, and invariant analysis. This asymmetry can introduce false positives:

- **Plan step leakage**: A plan step like "return dict(DEFAULTS) instead of DEFAULTS" contains the fix itself. A classifier seeing this might infer reasoning correctness from the fix quality rather than from the diagnosis. Baseline reasoning does not include an explicit plan-step list.
- **Verification evidence leakage**: Verification entries like `"status": "PASS", "evidence": "dict() creates independent copy"` contain direct evidence of correct understanding. Baseline reasoning does not include structured self-verification.
- **Length advantage**: More text = more keywords matching the classifier's internal heuristics for "clearly identifies the mechanism." This is the inverse of the brevity bias — an unearned verbosity bonus.

**Pros**: Simple to implement; preserves classifier prompt; recovers information that genuinely exists.

**Cons**: Creates measurement asymmetry (enriched conditions get more evidence than baseline); may inflate reasoning_correct for LEG/retry; not format-invariant — still depends on condition-specific field extraction.

**Risk level**: HIGH. Must be validated via A/B comparison before adoption.

---

### Fix B: Classifier Prompt Redesign

**Mechanism**: Modify `_CLASSIFY_PROMPT` to explicitly tolerate brevity, handle structured reasoning, and evaluate semantic content over format.

**Pros**: Addresses H1 directly; applies uniformly to all conditions; does not create information asymmetry.

**Cons**: Changes the measurement instrument for ALL conditions including baseline; requires re-running all experiments; hard to calibrate (relaxing conservatism risks false positives); all prior results become incomparable.

**Risk level**: MEDIUM-HIGH. Addressable if prompt change is validated against a locked audit set and all changed labels are manually justified.

---

### Fix C: Normalized Intermediate Representation

**Mechanism**: Define a canonical reasoning representation with fixed slots:

```
{
    "root_cause": str,          # E1
    "manifestation": str,       # E2
    "mechanism_or_invariant": str,  # E3
    "fix_rationale": str | None,    # E4
    "evidence": list[str],      # supporting quotes/references
}
```

Baseline freeform reasoning is mapped into this representation via a lightweight extraction step (could be LLM-based or rule-based). LEG structured output maps naturally:
- `root_cause` = `bug_diagnosis`
- `manifestation` = extracted from `issues_found[].description` + `invariants_checked[].evidence`
- `mechanism_or_invariant` = extracted from `invariants_checked[].invariant`
- `fix_rationale` = extracted from `plan_steps[].intended_effect`
- `evidence` = extracted from `verification[].evidence`

The classifier then evaluates the normalized representation, not raw format-specific text. The classifier prompt is redesigned to accept the normalized format.

**Pros**: True format invariance — all conditions pass through the same representation. Eliminates information asymmetry. Cleanly separates "what the model said" from "how it said it." Most rigorous long-term fix. Enables the semantic completeness rubric (Section 3) to be applied programmatically.

**Cons**: Requires an extraction step for baseline reasoning (introduces a new failure point). The extraction itself may lose information or introduce errors. More complex to implement. Requires classifier prompt redesign (same cost as Fix B). LLM-based extraction doubles API calls for baseline conditions.

**Risk level**: MEDIUM. Higher implementation cost but lower measurement risk than Fix A, because the representation is symmetric across conditions.

---

### Fix D: Parse Recovery Gate

**Mechanism**: Prevent classification on corrupt reasoning input per the taxonomy in Section 4. Return `reasoning_correct=None` instead of `False` when reasoning is lost.

**Pros**: Eliminates false negatives from parse failures (H3). Simple. Correct by construction.

**Cons**: Increases unclassified rate. Does not fix H1 or H2.

**Risk level**: LOW. This is a correctness fix, not a measurement change. Should be applied regardless of which other fix is chosen.

---

### Fix E: eval_model Parameter Bug Fix

**Mechanism**: Replace `model = "gpt-5.4-mini"` on evaluator.py:171 with `model = eval_model or "gpt-5.4-mini"`.

**Pros**: Trivial. Correct. Required regardless.

**Cons**: Changes classifier model for callers that were passing eval_model, which means their results will change.

**Risk level**: LOW, but must be logged. All experiments after the fix will use the correct model; all experiments before it used the hard-coded model.

---

## 6. Validation Matrix

### 6.1 Phase 0 Experiments (Measurement Audit — No Production Changes)

| ID | Experiment | Input | Expected if Hypothesis Holds | Stop Condition |
|---|---|---|---|---|
| P0-1 | H1 Brevity bias (15 cases x 4 compressions) | Full + 3 compressed reasoning per case | >= 5/15 flip YES->NO on any compression | If 0/15 flip: H1 falsified, skip prompt-level fixes |
| P0-2 | H1 Negative: terse-correct | 5 one-sentence correct summaries | All classify YES | If any classify NO: classifier has fundamental brevity problem |
| P0-3 | H1 Negative: verbose-wrong | 5 long wrong explanations | All classify NO | If any classify YES: classifier rewards verbosity over correctness |
| P0-4 | H2 Information audit (10 LEG cases) | Annotate E1-E4 for bug_diagnosis vs full LEG output | bug_diagnosis missing >= 1 element that full output has | If bug_diagnosis has all elements: H2 falsified |
| P0-5 | H2 Enrichment effect | Run classifier on bug_diagnosis-only vs full LEG text | >= 6/10 flip NO->YES | If < 3/10 flip: enrichment does not help |
| P0-6 | H3 Parse failure census | Count per-condition parse failures in existing data | >= 5% rate in any non-baseline condition | If < 1% everywhere: H3 negligible |
| P0-7 | H3 Reasoning inspection | For REASONING_LOST cases, inspect raw output | Raw contains reasoning text that was lost | If raw is also empty: genuine no-reasoning |
| P0-8 | eval_model bug confirmation | Read evaluator.py:171 | `model = "gpt-5.4-mini"` ignoring parameter | Already confirmed |

### 6.2 Audit Logging Requirements

For EVERY case evaluated in Phase 0 and Phase 1 experiments, the following MUST be preserved:

| Field | Description |
|---|---|
| `case_id` | Benchmark case identifier |
| `condition` | Experimental condition |
| `raw_model_output` | Complete model response (before any parsing) |
| `parsed_reasoning` | The reasoning field after parsing (what the classifier currently receives) |
| `enriched_reasoning` | The enriched reasoning (if applicable) |
| `parse_error` | Parse error code, if any |
| `parse_category` | Taxonomy category from Section 4 |
| `recovery_method` | None, partial_json, fallback_parser, heuristic |
| `classifier_prompt` | Complete prompt sent to the classifier LLM |
| `classifier_raw_output` | Raw response from the classifier LLM |
| `classifier_verdict` | Parsed YES/NO/None |
| `classifier_failure_type` | Parsed failure type |
| `classifier_parse_error` | Classifier output parse error, if any |
| `eval_model_used` | Actual model used for classification (to detect the line 171 bug) |
| `semantic_elements` | E1-E4 annotation (if in annotation study) |

Any experiment result without these fields is invalid and must be discarded.

### 6.3 Stop Conditions (Hard Abort Criteria)

| Condition | Abort Action |
|---|---|
| More than 1/10 known-good YES cases flip to NO under any proposed change | Abort that change. Debug before proceeding. |
| More than 1/10 known-good NO cases flip to YES under any proposed change | Abort that change. False positive risk too high. |
| Enriched-vs-raw disagreement exceeds 30% on baseline conditions | Enrichment is modifying baseline behavior. Abort enrichment. |
| Baseline label drift exceeds 1% on locked audit set (unless each flip is manually justified) | Abort rollout. Measurement instrument has changed. |
| Unclassified rate exceeds 20% for any condition after gating | Parse failure rate too high. Fix parsing before gating. |
| verbose-wrong controls classify as YES after any prompt change | Prompt change rewards verbosity. Revert. |

### 6.4 Positive and Negative Controls

| Control Type | Cases | Expected Verdict | Purpose |
|---|---|---|---|
| Known-correct-verbose | 10 baseline cases with manually verified correct reasoning | YES | Regression guard |
| Known-incorrect-verbose | 10 cases with manually verified wrong reasoning (verbose) | NO | False positive guard |
| Known-correct-terse | 5 manually written one-sentence correct root-cause identifications | YES | Brevity tolerance test |
| Known-incorrect-terse | 5 one-sentence wrong mechanism identifications | NO | Terse false positive guard |
| Known-verbose-wrong | 5 long paragraphs with plausible but wrong mechanism | NO | Verbosity bias test |

These controls must be run on EVERY proposed evaluator change. Any failure on controls blocks rollout.

---

## 7. Backward Compatibility — Strict Target

"Baseline results must not change" is insufficient. The strict target is:

**Locked Audit Set**: Select 30 baseline cases (stratified by failure_mode and difficulty) where `reasoning_correct` is confidently correct based on manual inspection. These 30 cases form the locked audit set.

**Label-Level Stability**: Under any proposed evaluator change, run the locked audit set through the new evaluator. Compare label-by-label (not aggregate rate).

- If ALL 30 labels match: compatibility confirmed.
- If 1-3 labels change: each change MUST be inspected. The raw input (before and after) must be logged and the change must be explainable as a genuine improvement (e.g., a parse failure was correctly gated). Document each flip in a table: case_id, old verdict, new verdict, raw reasoning, explanation.
- If > 3 labels change: abort rollout. The evaluator has changed too much.

**No quiet drift. No "within noise." Label-level drift matters.**

---

## 8. Denominator and Reporting Policy

### 8.1 Definitions

For each condition, report:

| Metric | Formula |
|---|---|
| `N_total` | Total cases evaluated |
| `N_classified` | Cases where `reasoning_correct` is True or False (not None) |
| `N_unclassified` | Cases where `reasoning_correct` is None |
| `N_parse_failed` | Cases where `parse_category` is REASONING_LOST, CODE_LOST, or STRUCTURE_MISSING |
| `N_recovered` | Cases where `reasoning_recovery` is not None |
| `reasoning_correct_rate` | `sum(reasoning_correct == True) / N_classified` |
| `leg_rate` | `sum(reasoning_correct == True AND code_correct == False) / N_classified` |
| `true_success_rate` | `sum(reasoning_correct == True AND code_correct == True) / N_classified` |
| `lucky_fix_rate` | `sum(reasoning_correct == False AND code_correct == True) / N_classified` |
| `true_failure_rate` | `sum(reasoning_correct == False AND code_correct == False) / N_classified` |

### 8.2 Mandatory Reporting

Every results table MUST include columns for: `N_total`, `N_classified`, `N_unclassified`, `N_parse_failed`, `N_recovered`.

If `N_unclassified / N_total > 10%` for any condition, a warning must be printed: "High unclassified rate for {condition}: {rate}%. Rates may not be representative."

If `N_unclassified` rates differ by more than 5pp between conditions being compared, the comparison must include a note: "Denominator differs by {X}pp. Direct rate comparison may be misleading."

### 8.3 None Handling

`reasoning_correct=None` cases are EXCLUDED from all rate computations. They are NEVER counted as False. They are NEVER silently dropped. They are always reported in the unclassified column.

---

## 9. Decision Framework

After Phase 0 experiments are complete, select the fix based on evidence:

| H1 Result | H2 Result | H3 Result | Recommended Fix |
|---|---|---|---|
| Confirmed (classifier penalizes brevity) | Weak (bug_diagnosis is informationally complete) | Any | Fix B (prompt redesign) or Fix C (normalized representation). Enrichment (Fix A) is unnecessary and would create asymmetry. |
| Weak (classifier tolerates brevity) | Confirmed (information loss is real) | Any | Fix A (enrichment) with mandatory A/B validation. Fix C as long-term replacement. |
| Confirmed | Confirmed (both contribute) | Any | Fix C (normalized representation) as primary. It addresses both. Fix A as interim if Fix C timeline is too long, with A/B validation. |
| Weak | Weak | Confirmed (parse failures dominate) | Fix D (parse gate) only. H1/H2 may not need fixing. |
| Confirmed | Confirmed | Confirmed | Phased: Fix D first (correctness), then Fix C (format invariance). Fix E (eval_model bug) immediately. |
| All weak | All weak | All weak | Re-examine the data. The problem may be smaller than hypothesized, or the experiments were not sensitive enough. |

**Fix D (parse gate) and Fix E (eval_model bug) are applied regardless of hypothesis results.** They are correctness fixes, not measurement changes.

---

## 10. Rollout Phases

### Phase 0: Measurement Audit (no production changes)

- Run experiments P0-1 through P0-8.
- Produce the semantic completeness annotation for 10 matched cases.
- Count parse failures per condition.
- Fix the eval_model parameter bug (Fix E). This is a trivial correctness fix, not a measurement change.
- Deliver: Phase 0 report with hypothesis verdicts.

### Phase 1: Offline Evaluation Experiments (no production changes)

- Based on Phase 0 results, select candidate fix(es) per decision framework (Section 9).
- Implement candidate fix behind a flag (`use_enriched_reasoning=False` default).
- Run locked audit set through both old and new evaluator. Compare label-by-label.
- Run positive and negative controls. Verify all stop conditions pass.
- Deliver: Phase 1 report with label-level comparison and control results.

### Phase 2: Choose Fix Based on Evidence

- Review Phase 0 and Phase 1 reports.
- Select final fix. Document rationale.
- If no fix passes all stop conditions, iterate on design before proceeding.

### Phase 3: Implement Behind Flag

- Implement chosen fix in production code.
- Default OFF. Activated only via explicit flag or config.
- Old evaluator path remains fully functional.
- Both paths produce output simultaneously when flag is ON (dual scoring).

### Phase 4: Dual-Score Shadow Run

- Run full ablation (58 cases x selected conditions x 1 trial) with dual scoring ON.
- For EVERY case, log both `reasoning_correct_raw` (old path) and `reasoning_correct_new` (new path).
- Compute disagreement rate per condition.
- Audit a stratified sample of disagreements (10 per condition): for each, determine whether the old or new verdict is correct by applying the semantic completeness rubric.
- Deliver: Phase 4 report with per-condition disagreement rates and sample audit results.

**Shadow run is MANDATORY. It is not optional validation.** Without it, there is no evidence that the new evaluator is better, not just different.

### Phase 5: Switch Primary Metric

- Only if Phase 4 shadow results validate the change:
  - Disagreement rate is explainable and directionally correct.
  - Locked audit set labels are stable (< 3 flips, all justified).
  - All stop conditions pass.
  - All controls pass.
- Switch primary metric to new evaluator.
- Archive all old results for comparison.
- Document the change in the paper methodology.

---

## 11. Do Not Do

1. **Do NOT silently reclassify parse failures as incorrect reasoning.** If reasoning is unrecoverable, the result is None, not False. No exceptions.

2. **Do NOT silently switch the production metric from raw reasoning to enriched reasoning without completing the dual-score shadow run (Phase 4).** Enrichment is an intervention on the measurement, not a neutral plumbing fix.

3. **Do NOT change the classifier prompt AND the reasoning input format at the same time.** That destroys identifiability — you cannot tell which change caused the result change. Prompt changes and input changes must be tested in separate experiments.

4. **Do NOT fold heuristic parse recovery into primary metrics without labeling it.** Regex-recovered reasoning is NOT equivalent to cleanly parsed reasoning. It must be reported separately or excluded.

5. **Do NOT accept aggregate improvements if label-level audit looks bad.** An aggregate rate improvement of +5% is meaningless if the 30-case locked audit set shows 4+ label flips. Label-level stability is the gating criterion, not aggregate rates.

6. **Do NOT assume baseline and LEG reasoning_correct rates MUST converge.** They should be comparable IF the measurement is format-invariant, but the model may genuinely reason differently in structured vs freeform modes. The goal is measurement validity, not rate equality.

7. **Do NOT treat enrichment as low-risk.** Enrichment gives LEG/retry conditions more evidence than baseline. This can inflate reasoning_correct and create a new asymmetry. It must be validated as rigorously as any other measurement change.

8. **Do NOT leave the hard-coded eval_model on line 171 unfixed during any audit experiment.** Every audit experiment must use the intended eval model, not the accidentally hard-coded one. Fix E is a prerequisite for all other experiments.

9. **Do NOT run Phase 1+ experiments without the audit logging requirements from Section 6.2.** If the artifacts are not preserved, the experiment cannot be reviewed or reproduced.

10. **Do NOT skip the semantic completeness annotation study.** Without it, "enrichment helps" could mean "we gave the classifier more keywords to pattern-match" rather than "we restored genuine reasoning content." The annotation study is the ONLY way to distinguish these.

---

## 12. Metrics for Success (Revised)

| Metric | Target | Rationale |
|---|---|---|
| Classifier agreement under semantically equivalent reformulations | >= 90% (same verdict on full vs compressed reasoning when semantic elements are preserved) | Calibration goal: format invariance |
| Parse-induced false negative rate | 0% (no case where reasoning_correct=False AND parse_category is REASONING_LOST/STRUCTURE_MISSING) | Correctness goal: parse failures must not produce False |
| Baseline label drift on locked audit set (30 cases) | <= 1 flip (must be manually justified) | Stability goal: measurement instrument continuity |
| Enriched-vs-raw disagreement: audited on stratified sample | Disagreement must be directionally correct in >= 80% of audited flips (new verdict matches manual semantic rubric) | Quality goal: changes are improvements, not noise |
| Unclassified rate per condition | Reported explicitly; no silent denominator shifts; warning if > 10% | Transparency goal |
| verbose-wrong controls | 100% classify as NO under any evaluator change | Safety goal: no verbosity reward |
| terse-correct controls | 100% classify as YES under any evaluator change | Safety goal: brevity must not penalize correctness |

**Note**: "Reasoning accuracy gap between baseline and LEG <= X%" is NOT a success criterion. The gap should reflect genuine capability differences (if any), not measurement artifacts. The goal is to make the measurement valid, not to force a particular outcome.

---

## 13. Risk Analysis (Revised)

### 13.1 Enrichment Creates New Asymmetry

**Risk**: Fix A gives structured-output conditions (LEG, retry) systematically more classifier input than baseline. Plan steps, verification evidence, and invariant analysis are forms of reasoning that baseline does not present separately. This could inflate reasoning_correct for structured conditions.

**Specific example**: For case `alias_config_a`, baseline reasoning might say "The bug is aliasing — create_config returns DEFAULTS by reference." Enriched LEG reasoning would say "Bug Diagnosis: shared mutable reference. Plan: return dict(DEFAULTS) to create independent copy. Verification: dict() confirmed to create copy — PASS. Invariant: function purity — PASS." The enriched version contains fix rationale and verification evidence that the baseline version does not. The classifier may credit the LEG response for depth it would not credit the baseline for.

**Mitigation**: Fix C (normalized representation) avoids this by mapping BOTH formats to the same representation. If Fix A is used as interim, the A/B shadow run (Phase 4) must specifically audit cases where enriched LEG flips to YES while matched baseline stays at a comparable level.

### 13.2 Extraction Errors in Normalized Representation

**Risk**: Fix C requires extracting structured slots from baseline freeform text. This extraction step is itself error-prone. If it drops E2 (manifestation) from a baseline response, a previously-YES case could flip to NO — not because of evaluator improvement but because of extraction failure.

**Mitigation**: Extraction must be validated against the locked audit set before deployment. Each extraction result must be logged alongside the original text so that extraction errors can be detected.

### 13.3 Classifier Model Sensitivity

**Risk**: Brevity bias (H1) may be model-specific. The hard-coded `gpt-5.4-mini` may handle terse reasoning differently than `gpt-5-mini` or `gpt-4o-mini`. Fixing the eval_model bug could shift classifier behavior independently of any other change.

**Mitigation**: Phase 0 experiments must record which eval model was used. After fixing the eval_model bug, re-run the locked audit set to measure label drift attributable to the model change alone (before any other fix).

### 13.4 Increased Unclassified Rate Hides Problems

**Risk**: The parse gate (Fix D) converts False to None for parse-failure cases. If parse failures are condition-dependent, the gate creates condition-dependent sample size reduction. Conditions with higher parse failure rates have smaller effective N, making their rate estimates less precise and potentially masking real effects.

**Mitigation**: Mandatory reporting of N_classified per condition (Section 8). If N_classified differs by more than 10% between compared conditions, rate comparisons must be flagged.

### 13.5 Overfitting Controls to Current Cases

**Risk**: The 30-case locked audit set and the 10-case annotation study are drawn from current benchmark cases. If the evaluator is tuned to work well on these specific cases, it may fail on new cases added later.

**Mitigation**: Controls must include a mix of difficulty levels, failure modes, and case families. At least 5 of the 30 locked audit cases should be v2-only cases (not in the original v1 benchmark) to reduce overfitting risk.

---

## 14. Permanent Regression Tests

These tests must be added to the test suite and run on every change to the evaluation pipeline, regardless of which fix is adopted.

### 14.1 Format Invariance Tests

```
test_same_semantic_content_different_formats:
    Given: A reasoning text R that identifies root cause correctly.
    When: R is presented as (a) freeform paragraph, (b) one-sentence summary,
          (c) structured {diagnosis, plan, evidence} block.
    Then: Classifier verdict is the same for all three formats.

test_empty_reasoning_never_false_with_parse_error:
    Given: reasoning="" AND parse_error is set.
    Then: reasoning_correct is None, not False.

test_baseline_passthrough_unchanged:
    Given: Standard parsed dict with reasoning="some text" and no LEG fields.
    Then: The reasoning string reaching the classifier is byte-for-byte identical
          to the input reasoning string.
```

### 14.2 Brevity Robustness Tests

```
test_terse_correct_classified_yes:
    Given: reasoning="shared mutable reference causes aliasing" (one sentence, correct).
    Then: reasoning_correct == True.

test_verbose_wrong_classified_no:
    Given: reasoning=(200-word paragraph identifying wrong mechanism).
    Then: reasoning_correct == False.
```

### 14.3 Parse Robustness Tests

```
test_reasoning_lost_produces_none:
    Given: parse_category == REASONING_LOST.
    Then: reasoning_correct is None.

test_structure_missing_produces_none:
    Given: parse_category == STRUCTURE_MISSING.
    Then: reasoning_correct is None.

test_recovered_reasoning_flagged:
    Given: reasoning recovered via fallback parser.
    Then: reasoning_recovery field is set and non-None.
```

### 14.4 eval_model Tests

```
test_eval_model_parameter_honored:
    Given: llm_classify called with eval_model="test-model".
    Then: The actual model used in the API call is "test-model", not "gpt-5.4-mini".

test_eval_model_logged:
    Given: Any evaluation.
    Then: The eval result contains eval_model_used field matching the actual model.
```

### 14.5 Denominator Integrity Tests

```
test_none_excluded_from_rates:
    Given: 10 cases where 3 have reasoning_correct=None.
    Then: reasoning_correct_rate denominator is 7, not 10.

test_unclassified_reported:
    Given: Any results summary.
    Then: N_unclassified is present and non-negative.
```
