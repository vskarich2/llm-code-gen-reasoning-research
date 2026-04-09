# FORENSIC META-ANALYSIS: Experimental Report Synthesis

**Date:** 2026-04-08
**Scope:** All analyses in `analysis/analysis_best_current_reports/`
**Method:** Cross-file extraction, verification, reconciliation

---

## EVALUATION SEMANTICS

This section defines the three independent evaluation axes used across all experiments. Every subsequent section depends on these definitions. Read this first.

### Three Evaluators, Three Questions

| Evaluator | Question it answers | Sees ground truth? | Sees generated code? | Sees execution results? |
|---|---|---|---|---|
| **Oracle** | Does the model's stated root cause match the TRUE bug mechanism? | YES | NO | NO |
| **Classifier** | Does the model's code follow from its stated reasoning? | NO | YES | NO |
| **Execution (Spec Oracle)** | Does the model's code actually fix the bug? | NO (uses tests) | YES (runs it) | IS the result |

These three axes are **independent by design**. Each evaluates a different relationship:

- **Oracle** evaluates: reasoning → ground truth (Is the diagnosis correct?)
- **Classifier** evaluates: reasoning → code (Does the code implement the stated diagnosis?)
- **Execution** evaluates: code → correctness (Does the code pass the tests?)

### What Classifier CORRECT Means and Does Not Mean

The classifier prompt (`classify_reasoning_v3.j2`) states explicitly:

> "You are NOT evaluating whether the fix is correct. You are NOT using ground truth. You are ONLY checking whether the model's reasoning is self-consistent and whether the code follows that reasoning."

**Classifier CORRECT = the model's code faithfully implements its stated reasoning.** It means the model did what it said it would do. It does NOT mean the model did the right thing.

A model that:
- Identifies a wrong mechanism (oracle = WRONG)
- Builds a coherent fix strategy around that wrong mechanism
- Writes code that faithfully implements that wrong strategy

will receive **Classifier = CORRECT, Oracle = WRONG, Execution = FAIL**. This is a coherent failure, not an evaluator error.

### What Oracle CORRECT Means and Does Not Mean

The oracle prompt (`oracle_reasoning_truth_enriched.j2`) states explicitly:

> "You must NOT consider whether the developer's proposed fix would actually work in code. You must NOT consider any generated or modified code — you are evaluating the REASONING, not the implementation."

**Oracle CORRECT = the model's root_cause text correctly identifies the true bug mechanism.** It does NOT mean the model's code fixes the bug. A model can perfectly describe the mechanism and still produce broken code.

### Oracle-Classifier Disagreement is Expected

The ~50% disagreement rate between oracle and classifier on DDC cases (v3_v4_audit: 51-54%) is **structural, not anomalous**. It means roughly half of all trials involve a model that coherently implements a wrong mechanism. This is informative data about how models fail — not evidence of evaluator malfunction.

The four possible states:

| Oracle | Classifier | Meaning |
|---|---|---|
| CORRECT | CORRECT | Model identified the right mechanism AND code follows from that reasoning |
| CORRECT | INCORRECT | Model identified the right mechanism BUT code contradicts its own reasoning |
| WRONG | CORRECT | Model identified the wrong mechanism BUT code faithfully implements that wrong reasoning |
| WRONG | INCORRECT | Model identified the wrong mechanism AND code doesn't even follow its own reasoning |

Oracle=WRONG + Classifier=CORRECT is the **coherent failure** state. It is the most common disagreement pattern and the most important one for understanding model behavior.

### Four Outcome Categories

Combining all three axes produces four behaviorally distinct categories:

**(A) TRUE LEG (Reasoning-Execution Gap)**
- Oracle: CORRECT (mechanism right)
- Classifier: CORRECT (reasoning aligned with code)
- Execution: FAIL
- Meaning: The model understood the bug, built a coherent plan, but the code does not work. This is a pure implementation quality failure.

**(B) COHERENT FAILURE (Wrong Mechanism)**
- Oracle: WRONG (mechanism wrong)
- Classifier: CORRECT (reasoning aligned with code)
- Execution: FAIL
- Meaning: The model built a complete, self-consistent argument for the wrong thing. The code faithfully fixes a bug that does not exist. Hints that assume correct reasoning will fail on these cases.

**(C) LUCKY FIX**
- Oracle: WRONG or PARTIAL
- Execution: PASS
- Meaning: The model's stated reasoning is incorrect, but the code happens to fix the bug anyway. The model got the right answer for the wrong reason.

**(D) FULL SUCCESS**
- Oracle: CORRECT
- Classifier: CORRECT
- Execution: PASS
- Meaning: The model understood the bug, built a coherent plan, and produced working code. All three axes aligned.

**Note on the classifier's role in LEG:** True LEG (category A) requires Classifier=CORRECT because if the code does not follow from the reasoning, the failure is not an execution gap — it is a reasoning-code disconnect. The classifier distinguishes "understood but couldn't implement" (LEG) from "understood but wrote unrelated code" (incoherent failure).

---

## STEP 1 — INVENTORY + TIMELINE

### File Inventory

| # | File | Modified | Type |
|---|------|----------|------|
| 1 | `ddc_ablation_audit_4omini.md` | Apr 6 02:36 | Experiment report |
| 2 | `hint_ablation_v3_analysis.md` | Apr 6 03:18 | Analysis report |
| 3 | `hint_ablation_v3_results.json` | Apr 6 03:03 | Data (filtered) |
| 4 | `hint_ablation_v4_results.json` | Apr 6 03:36 | Data (full) |
| 5 | `hint_ablation_v4_full.json` | Apr 6 03:39 | Raw data (169KB) |
| 6 | `hint_ablation_combined_analysis.md` | Apr 6 03:58 | Synthesis report |
| 7 | `v3_v4_oracle_classifier_deep_audit.md` | Apr 6 04:15 | Audit report |
| 8 | `ddc_recomputed_metrics.json` | Apr 6 04:27 | Recomputed data |
| 9 | `ddc_metrics_audit.md` | Apr 6 04:36 | Audit report |
| 10 | `hint_effectiveness_report.md` | Apr 6 06:44 | Synthesis report |
| 11 | `swebench_validation.md` | Apr 7 00:30 | Validation study |
| 12 | `swebench_audit_71_cases.md` | Apr 7 01:06 | Audit report |
| 13 | `pearl_mapping_code/case_mapping.md` | Apr 6 20:10 | Taxonomy analysis |
| 14 | `analysis_scripts/recompute_ddc_metrics.py` | Apr 6 20:59 | Computation script |

### Analysis Timeline Table

| analysis_name | date | models | conditions | cases | trials | dataset | notes |
|---|---|---|---|---|---|---|---|
| ddc_ablation_audit_4omini | Apr 6 (run: 01:42) | gpt-4o-mini | 2 (baseline_v3, critique_strict_v3) | 38 | 5 per condition | DDC synthetic | Only ablation with multi-trial design |
| hint_ablation_v3_analysis | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 8 (c1-c8) | 28 | 1 per (model,cond,case) | DDC synthetic | Hints run only on baseline-failed cases |
| hint_ablation_v4_results | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 7 (v4c1-v4c7) | 8-23 per model | 1 per (model,cond,case) | DDC synthetic | New impl axis + changed critique prompt |
| hint_ablation_combined | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 15 (v3+v4) | 8-23 per model | 1 per (model,cond,case) | DDC synthetic | Merges v3+v4 |
| v3_v4_oracle_classifier_audit | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 14 (v3+v4) | 703 total records | 1 | DDC synthetic | Forensic audit of evaluator calibration |
| ddc_metrics_audit | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 15 | 703 total records | 1 | DDC synthetic | 3-axis recomputation from WAL files |
| hint_effectiveness_report | Apr 6 | gpt-4o-mini, gpt-5-mini, gpt-5.4-mini | 17 across 5 ablation rounds | DDC: 8-23; V2: 72 | 1 | DDC + V2 synthetic | Broadest synthesis; adds trace_value + fix_not_consumer |
| swebench_validation | Apr 7 | gpt-5.4-mini | 1 (single-shot) | 31 | 1 | SWE-bench Verified (multi-file) | Validation on real-world bugs |
| swebench_audit_71_cases | Apr 7 | gpt-5.4-mini | 1 (single-shot) | 71 (59 evaluated) | 1 | SWE-bench subset | Larger SWE-bench evaluation |
| pearl_mapping | Apr 6 | N/A | N/A | ~72 (all cases_v2) | N/A | V2 synthetic | Taxonomy reclassification, no experiments |

### Evolution of Key Concepts

| Aspect | Early (v3 ablation) | Mid (v4 / metrics audit) | Late (SWE-bench) |
|---|---|---|---|
| **LEG definition** | mechanism_correct AND NOT execution_pass | mechanism_correct AND location_correct AND NOT execution_pass (stricter) | oracle_correct AND execution_fail (SWE-bench adapted) |
| **Conditions** | 8 v3 hints (location + scope + anti-compensation) | +7 v4 hints (added implementation axis) | No hints; single-shot baseline |
| **Evaluation** | Generic oracle + spec oracle | 3-axis decomposition (mechanism / location / execution) | oracle_reasoning_truth_enriched (strict) |
| **Dataset** | DDC synthetic only | DDC synthetic + V2 synthetic | SWE-bench real-world |
| **Cases** | 28 tested | 703 records recomputed | 31-71 SWE-bench tasks |

---

## STEP 2 — DEFINITIONS (STRICT)

### 1. LEG (Reasoning-Execution Gap)

**Canonical definition (corrected, from ddc_metrics_audit):**
> LEG = mechanism_correct AND location_correct AND NOT execution_pass

The model correctly identified the bug mechanism (what), touched the correct file (where), but produced code that does not fix the bug (how). This is strictly an implementation quality failure.

Under the full 3-evaluator model, true LEG further requires Classifier=CORRECT: the model's code must follow from its reasoning. If the code contradicts its own stated reasoning, that is an incoherent failure, not an execution gap.

**Variants observed:**

| Version | Definition | Source | Issue |
|---|---|---|---|
| Old LEG | mechanism_correct AND NOT execution_pass | Used in early v3 analyses | Overcounts: includes location errors (40 cases reclassified) |
| Corrected LEG | mechanism_correct AND location_correct AND NOT execution_pass | ddc_metrics_audit, recompute script | Canonical. Reduces old count from 164 to 124 |
| SWE-bench LEG | oracle_correct AND execution_fail | swebench_validation, swebench_audit | Simpler 2-axis version; no separate location check |
| R+E- (ddc_ablation_audit) | Generic oracle=CORRECT but spec oracle=fail | ddc_ablation_audit_4omini | Equivalent to old LEG; uses oracle terminology |

**Critical note:** The old LEG definition overcounted by ~24% (40/164 cases). Those 40 cases were models that described the mechanism correctly but fixed the wrong file entirely -- these are location errors, not execution gaps.

### 2. Classifier

**What it evaluates:** Alignment between the model's stated reasoning and its generated code. Does the code implement the stated diagnosis and fix strategy?

**Prompt source:** `core/prompts/components/classify_reasoning_v3.j2`

**Four dimensions:**
1. `reasoning_internal_consistency` -- Does the fix strategy follow from the root cause?
2. `commitments_internal_consistency` -- Do code commitments follow from the fix strategy?
3. `commitments_code_consistency` -- Does the code implement the stated commitments?
4. `reasoning_code_alignment` -- Does the code reflect the stated fix strategy?

**Input:** Task description, model's root_cause, fix_strategy, code_commitments, full assembled code (with [MODIFIED] and [UNCHANGED] markers).

**Does NOT see:** Ground truth mechanism, execution results, file diffs, test outcomes.

**What Classifier CORRECT means:** The model's code faithfully implements its stated reasoning. The reasoning-to-code pipeline is internally coherent.

**What Classifier CORRECT does NOT mean:** The model identified the correct mechanism. A model that coherently fixes the wrong bug receives Classifier=CORRECT. This is not an error -- it is measuring a different axis.

**Observed rates:**
- SWE-bench (swebench_audit): 58/59 = 98.3% CORRECT
- DDC: ~50% agreement with oracle

**Interpretation:** The 98% rate on SWE-bench means models almost always write code that follows from their own reasoning. The ~50% oracle disagreement on DDC means roughly half of all DDC trials involve models that coherently implement a wrong mechanism. The classifier detects alignment; the oracle detects truth. These are independent measurements.

### 3. Oracle (Generic Oracle)

**What it evaluates:** Whether the model's root_cause text correctly identifies the TRUE bug mechanism as described in the ground truth.

**Prompt source:** `core/prompts/components/oracle_reasoning_truth_enriched.j2`

**Input:** Task description, original buggy code, ground truth bug specification (bug_type, bug_location, mechanism_source, mechanism_property, mechanism_steps, mechanism_outcome, trap_description), model's root_cause and fix_strategy.

**Does NOT see:** Generated code, execution results, changed files, classifier output.

**Output:** CORRECT / PARTIAL / WRONG / UNJUDGABLE + one-sentence justification.

**Key rubric constraints:**
- "You must NOT consider whether the developer's proposed fix would actually work in code."
- "You must NOT consider any generated or modified code -- you are evaluating the REASONING, not the implementation."
- "Describing what goes wrong (failure outcome) is NOT the same as identifying WHY it goes wrong (mechanism)."

**Known design limitation (leniency):** The oracle evaluates mechanism description without evaluating intervention location or file choice. This means a model that correctly describes the causal chain in text but fixes the wrong file receives Oracle=CORRECT. This is by design: the oracle measures reasoning quality, not intervention quality. 40 wrong-file-correct-oracle cases are documented in the v3_v4_audit.

### 4. Spec Oracle (Execution)

**What it evaluates:** Whether the model's generated code actually fixes the bug. On DDC cases, it classifies the fix depth (A/B/C/D/F) by matching test results against known patch profiles.

**Type:** Deterministic, code-based. Runs invariant functions via subprocess execution.

**Output:** Depth A (root fix), B-D (trap-level fix), or F (worse than any known trap); pass/fail.

**Error rate:** 0% across 703 DDC records (v3_v4_audit). Depth A = pass is a perfect bijection. This is the only perfectly calibrated evaluator in the pipeline.

**On SWE-bench:** The Docker test harness serves this role. Pass = all FAIL_TO_PASS tests pass AND zero PASS_TO_PASS regressions.

### 5. Hints / Interventions

**Taxonomy (3 axes, established in v4):**

| Axis | Hint Names | What it tells the model |
|---|---|---|
| **Location** | first_corruption, trace_value | WHERE the bug is (first corruption point) |
| **Implementation** | transformation_localization, no_refactor, fix_not_consumer | HOW to fix (direct correction, don't restructure) |
| **Scope** | minimality, single_file, no_touch | What NOT to touch (limit file count, minimize changes) |
| **Anti-compensation** | anti_compensation | Don't compensate downstream; fix the source |
| **Combined** | first_corruption_minimality, anti_compensation_single_file, location_impl, location_scope_impl, impl_scope | Multi-axis combinations |
| **Control** | retry_only | No hint content; just re-attempt |

**Critique prompt versions:**
- v3: "Your implementation may not fully reflect your reasoning" -- FLAWED: reinforces incorrect reasoning by assuming reasoning is correct
- v4+: "Your previous fix did not pass. Consider this feedback:" -- NEUTRAL: allows model to reconsider its mechanism

**All hints are:** single sentences appended to the retry prompt after a failed first attempt. Deterministic (not LLM-generated). Applied at attempt 1 (a1) after attempt 0 (a0) fails.

---

## STEP 3 — PER-ANALYSIS EXTRACTION

### 3.1 ddc_ablation_audit_4omini

| Field | Value |
|---|---|
| **Hypothesis** | Directed depth hints on retry improve pass rates when LLMs fix at wrong depth |
| **Conditions run** | baseline_v3 (no hint), critique_strict_v3 (directed hint on retry) |
| **Conditions missing** | gentle hint, explicit hint (mentioned from prior gpt-5-mini testing, not run here) |
| **Key results** | Baseline: 77/190 = 41%; Critique: 83/190 = 44%; Delta: +3pp |
| **LEG (R+E-)** | 72 instances across both conditions (uses old LEG definition: oracle CORRECT + execution FAIL, without location check) |
| **Hint fix rate** | 4/96 hints = 4.2% converted failure to pass |
| **Caveats** | Aggregate obscures true effect (24/38 cases identical between conditions); hint can hurt (2 regressions); conditions are independent runs, not paired; oracle leniency documented (51+ wrong-file-correct-oracle instances) |

### 3.2 hint_ablation_v3_analysis

| Field | Value |
|---|---|
| **Hypothesis** | Where and why hints work varies by model failure mode |
| **Conditions run** | 8 v3 hints (retry, first-corruption, anti-comp, minimal, no-touch, first+min, 1-file, anti+1f) |
| **Conditions missing** | None |
| **Key results** | 37 total fixes; 14/28 cases fixable; gpt-5.4-mini: 11 fixable cases; gpt-4o-mini: 3; gpt-5-mini: 2 |
| **Caveats** | 8 WARNING cases where gpt-4o-mini returns 0 files (possible false positives); no repeated trials; uneven trial counts; no formal LEG metric computed |

### 3.3 hint_ablation_combined_analysis

| Field | Value |
|---|---|
| **Hypothesis** | Combined multi-axis hints outperform single-axis; implementation axis is the missing piece |
| **Conditions run** | 15 conditions (8 v3 + 7 v4) |
| **Conditions missing** | None |
| **Key results** | 70 total fixes (37 v3 + 33 v4); Best hint: v4c7_location_scope_impl (10 fixes, 27%); Worst: v4c4_no_refactor (1 fix, 3%) |
| **Caveats** | v3 vs v4 confounded by critique prompt change; gpt-5.4-mini over_edit_rate 0.875-1.0; scope hints don't reduce file count, only improve edit quality |

### 3.4 v3_v4_oracle_classifier_deep_audit

| Field | Value |
|---|---|
| **Hypothesis** | Generic oracle is insufficiently discriminating for multi-file DDC cases |
| **Conditions run** | All 14 v3+v4 conditions (703 records, 56 hand-audited) |
| **Conditions missing** | c7 not mentioned in v3 |
| **Key results** | R+E-: 24% (v3), 22% (v4); Oracle CORRECT rate: 46% (v3), 45% (v4); Wrong-file-correct-oracle: 40 cases; Oracle-classifier disagreement: 51-54%; Spec oracle: 0% error rate |
| **Evaluator semantics note** | The 51-54% oracle-classifier disagreement is expected: it measures the rate of coherent failures (Oracle=WRONG, Classifier=CORRECT). These are models that built internally-consistent reasoning around an incorrect mechanism. The classifier is functioning correctly when it calls these CORRECT -- it is measuring alignment, not truth. |

### 3.5 ddc_metrics_audit (3-axis recomputation)

| Field | Value |
|---|---|
| **Hypothesis** | Old LEG overcounts by including location errors; 3-axis decomposition reveals distinct failure types |
| **Conditions run** | 15 conditions x 3 models = 703 records |
| **Conditions missing** | None |
| **Key results** | Old LEG: 164 to New LEG: 124 (40 reclassified as location errors); gpt-4o-mini: mech 0.31, loc 0.81, exec 0.41, LEG 0.149; gpt-5-mini: mech 0.57, loc 0.78, exec 0.72, LEG 0.125; gpt-5.4-mini: mech 0.60, loc 0.97, exec 0.59, LEG 0.242 |
| **Caveats** | gpt-5.4-mini changes 4-5 files (inflates location_correct to 0.97 mechanically); gpt-5-mini n=8 per condition (unreliable per-condition estimates); zero reconstruction failures |

### 3.6 hint_effectiveness_report

| Field | Value |
|---|---|
| **Hypothesis** | Hint library should be case-type-aware and model-aware |
| **Conditions run** | 17 hints across 5 ablation rounds (v3, v4, v2_hint, trace_value, fix_not_consumer) |
| **Conditions missing** | no-touch NOT tested on V2 cases; gpt-5.4-mini and gpt-5-mini NOT tested on V2 |
| **Key results** | DDC best: gpt-5.4-mini + no-touch = 57%; DDC worst: gpt-4o-mini + fix_not_consumer = 0%; V2 (gpt-4o-mini): trace_value 21%, first_corruption 20%; 17/72 V2 cases hint-fixable |
| **Caveats** | Title says "4 MODELS" but only 3 reported; denominators inconsistent between sections; V2 tested with gpt-4o-mini only |

### 3.7 swebench_validation (31 multi-file tasks)

| Field | Value |
|---|---|
| **Hypothesis** | LEG is the dominant failure mode on real-world multi-file bugs |
| **Conditions run** | 1 (single-shot baseline, gpt-5.4-mini) |
| **Conditions missing** | No hints, no retries, no multi-model comparison |
| **Key results** | Exec pass: 2/31 = 6.5%; Oracle correct: 22/31 = 71%; LEG: 19/31 = 61%; Exec given oracle correct: 2/22 = 9.1% |
| **Caveats** | Single attempt per task; multi-file filter (harder subset); some cases reference "v5 context-file run" (configuration mixing); 381 P2P regressions across 6 cases |

### 3.8 swebench_audit_71_cases

| Field | Value |
|---|---|
| **Hypothesis** | Same as above, on larger subset |
| **Conditions run** | 1 (single-shot baseline, gpt-5.4-mini) |
| **Conditions missing** | No hints, no retries, no multi-model comparison |
| **Key results** | Exec pass: 7/59 = 11.9%; Oracle correct: 41/59 = 69.5%; LEG: 36/59 = 61.0%; Exec given oracle correct: 7/41 = 17.1%; Classifier RIC: 58/59 = 98.3% |
| **Evaluator semantics note** | The 98.3% classifier CORRECT rate means that in 58 of 59 cases, the model's code faithfully implements its stated reasoning. This does NOT mean the model's reasoning is correct in 98% of cases. The oracle measures that separately: 69.5% mechanism correctness. The gap (98% alignment vs 69.5% truth) quantifies the coherent failure rate: ~29% of cases have aligned-but-wrong reasoning. |
| **Caveats** | 8 cases not evaluated (too large); 4 cases had no oracle; strict partial_mode (PARTIAL=incorrect); includes feature requests labeled as bugs |

### 3.9 pearl_mapping

| Field | Value |
|---|---|
| **Hypothesis** | Current L3 cases are actually deep L2 under strict Pearl hierarchy |
| **Conditions run** | N/A (taxonomy analysis, not experiment) |
| **Key results** | All former L3 cases downgraded to L2; 16 cases = L1; ~56 cases = L2; 3 cases = near-L3; 0 cases = true L3 |
| **Caveats** | None -- this is a definitional analysis, not empirical |

---

## STEP 4 — CROSS-ANALYSIS AGGREGATION

### Comparability Matrix

| Comparison | Compatible? | Reason |
|---|---|---|
| v3 vs v4 hint conditions (DDC) | PARTIALLY | Same cases/models but critique prompt changed between rounds |
| Across models on same DDC condition | YES | Same cases, same conditions, same evaluation |
| DDC vs V2 cases | NO | Different case structure (multi-file pipeline vs single-file) |
| DDC vs SWE-bench | NO | Synthetic vs real-world; different evaluation harnesses |
| swebench_validation vs swebench_audit | PARTIALLY | Same model, same method, overlapping but different case subsets |
| ddc_ablation_audit vs hint_ablation | NO | Different trial counts (5 vs 1), different case selection (all vs failed-only) |

### Unified Aggregated Results Table (DDC dataset, 3-axis metrics, from ddc_recomputed_metrics.json)

This is the ONLY table where cross-condition aggregation is valid, since all rows use the same dataset, same evaluation, and same recomputation script.

| Model | Condition | n | Mechanism | Localization | Execution | Pass Rate | LEG Rate | Lucky | Avg Files |
|---|---|---|---|---|---|---|---|---|---|
| **gpt-4o-mini** | c1_retry_only | 23 | 0.38 | 0.75 | 0.50 | 0.13 | 0.13 | 0.00 | 1.13 |
| | c2_first_corruption | 23 | 0.45 | 0.78 | 0.43 | 0.13 | 0.17 | 0.00 | 1.13 |
| | c3_anti_compensation | 23 | 0.48 | 1.00 | 0.30 | 0.13 | 0.30 | 0.00 | 1.43 |
| | c6_first_corruption_min | 23 | 0.41 | 0.89 | 0.50 | 0.17 | 0.17 | 0.00 | 1.09 |
| | c8_no_touch | 22 | 0.20 | 0.75 | 0.00 | 0.00 | 0.14 | 0.00 | 0.86 |
| | v4c6_location_impl | 22 | 0.38 | 0.75 | 0.50 | 0.18 | 0.13 | 0.04 | 1.05 |
| | v4c7_location_scope_impl | 21 | 0.50 | 0.90 | 0.33 | 0.13 | 0.26 | 0.00 | 1.00 |
| **gpt-5-mini** | c1_retry_only | 8 | 0.50 | 0.50 | 1.00 | 0.25 | 0.00 | 0.00 | 1.25 |
| | c2_first_corruption | 8 | 0.63 | 1.00 | 0.80 | 0.50 | 0.13 | 0.00 | 1.63 |
| | c6_first_corruption_min | 8 | 0.75 | 0.83 | 0.60 | 0.38 | 0.25 | 0.00 | 1.00 |
| | v4c3_transformation | 8 | 0.63 | 1.00 | 0.80 | 0.50 | 0.13 | 0.00 | 1.63 |
| | v4c6_location_impl | 8 | 0.63 | 1.00 | 0.80 | 0.50 | 0.13 | 0.00 | 1.50 |
| | v4c7_location_scope_impl | 8 | 0.50 | 1.00 | 1.00 | 0.50 | 0.00 | 0.00 | 1.00 |
| **gpt-5.4-mini** | c1_retry_only | 16 | 0.40 | 1.00 | 0.50 | 0.19 | 0.19 | 0.00 | 4.69 |
| | c2_first_corruption | 16 | 1.00 | 1.00 | 0.50 | 0.50 | 0.50 | 0.00 | 5.00 |
| | c3_anti_compensation | 16 | 0.69 | 1.00 | 0.73 | 0.50 | 0.19 | 0.00 | 4.69 |
| | c8_no_touch | 16 | 0.56 | 1.00 | 0.78 | 0.63 | 0.13 | 0.19 | 4.25 |
| | v4c1_first_corruption | 16 | 0.88 | 1.00 | 0.64 | 0.56 | 0.31 | 0.00 | 5.00 |
| | v4c6_location_impl | 16 | 0.63 | 1.00 | 0.80 | 0.56 | 0.13 | 0.06 | 5.00 |
| | v4c7_location_scope_impl | 16 | 0.81 | 0.92 | 0.67 | 0.56 | 0.25 | 0.06 | 4.44 |

*(Table shows selected conditions; full data in ddc_recomputed_metrics.json with all 15 conditions x 3 models)*

### Model-Level Aggregates (DDC, all conditions pooled)

| Model | n | Mechanism Accuracy (Oracle) | Localization Accuracy | Execution Fidelity | LEG Rate | Avg Files |
|---|---|---|---|---|---|---|
| gpt-4o-mini | 343 | 0.31 | 0.81 | 0.41 | 0.149 | ~1.0 |
| gpt-5-mini | 120 | 0.57 | 0.78 | 0.72 | 0.125 | ~1.3 |
| gpt-5.4-mini | 240 | 0.60 | 0.97 | 0.59 | 0.242 | ~4.7 |

**Source:** ddc_metrics_audit, verified against ddc_recomputed_metrics.json and recompute script.

**Interpretation through evaluator semantics:** Mechanism accuracy is the oracle's truth measure. gpt-5.4-mini's 0.60 mechanism accuracy means the oracle judged 60% of its root_cause texts as correctly identifying the true mechanism. The remaining 40% are oracle=WRONG -- but many of those have Classifier=CORRECT, meaning the model coherently implemented a wrong mechanism. The 0.97 localization accuracy is inflated by touching ~5 files per case (mechanically increases probability of including the correct file).

### SWE-bench Results (NOT aggregatable with DDC)

| Study | Model | n | Exec Pass | Oracle Correct | LEG Rate | Exec given Oracle Correct |
|---|---|---|---|---|---|---|
| swebench_validation | gpt-5.4-mini | 31 | 6.5% | 71.0% | 61% | 9.1% |
| swebench_audit_71 | gpt-5.4-mini | 59 | 11.9% | 69.5% | 61% | 17.1% |

The consistent 61% LEG rate across both studies is notable. On SWE-bench, the classifier's 98.3% alignment rate means coherent failures (Oracle=WRONG, Classifier=CORRECT) account for approximately 29% of cases -- the model builds a complete, self-consistent argument for the wrong mechanism in nearly one-third of attempts.

### Hint Fix Rates (DDC, from hint_effectiveness_report)

| Hint | All-Model Fixes/Attempts | Rate |
|---|---|---|
| v4c7_location_scope_impl | 10/37 | 27% |
| c8_no_touch | 8/40 | 20% |
| v4c6_location_impl | 8/36 | 22% |
| v4c1_first_corruption | 7/39 | 18% |
| c3_anti_compensation | 6/37 | 16% |
| c1_retry_only | 3/39 | 8% |
| v4c4_no_refactor | 1/36 | 3% |

---

## STEP 5 — CONSISTENT THEMES (HIGH CONFIDENCE ONLY)

### Theme 1: The Reasoning-Execution Gap is Real and Dominant

**Claim:** Models correctly identify bug mechanisms far more often than they produce working fixes. The gap between correct understanding (oracle) and correct implementation (execution) is the primary failure mode.

**Evidence:**
- DDC (ddc_metrics_audit): gpt-5.4-mini mechanism accuracy 0.60 but execution fidelity only 0.59 (of correctly-localized cases)
- SWE-bench validation: 71% oracle correct but only 9.1% exec pass
- SWE-bench audit: 69.5% oracle correct but only 17.1% exec given correct
- LEG accounts for 61% of failures on SWE-bench (both studies independently)
- LEG accounts for 12.5-24.2% of DDC trials depending on model

**Mechanism:** Models describe the causal chain correctly (oracle=CORRECT) and build code that follows from their reasoning (classifier=CORRECT), but the code does not pass tests (execution=FAIL). The failure is in the reasoning-to-working-code translation, not in understanding or internal coherence.

### Theme 2: Better Reasoning Does Not Automatically Mean Better Code

**Claim:** Improvements in mechanism understanding (oracle accuracy) and localization do not translate proportionally to implementation quality (execution fidelity).

**Evidence:**
- gpt-5.4-mini has the HIGHEST mechanism accuracy (0.60) and near-perfect localization (0.97) but the HIGHEST LEG rate (0.242)
- gpt-5-mini has the BEST execution fidelity (0.72) and LOWEST LEG rate (0.125) despite lower mechanism accuracy (0.57)
- gpt-4o-mini has the lowest mechanism accuracy (0.31) but LEG rate (0.149) is lower than gpt-5.4-mini

**Mechanism:** gpt-5.4-mini's high localization is inflated by changing ~5 files per case (mechanically increases probability of hitting the correct file). Its higher reasoning enables it to correctly diagnose more cases, but its code quality doesn't keep pace -- producing more true LEG cases where diagnosis is right but implementation fails.

### Theme 3: Multi-Axis Hints Outperform Single-Axis Hints

**Claim:** Hints that combine location + implementation (+ scope) information consistently outperform single-axis hints.

**Evidence:**
- v4c7_location_scope_impl: highest fix rate (27%, 10/37 fixes) across all hints
- v4c6_location_impl: 22% (8/36)
- Single-axis hints: location only (v4c1) 18%; scope only (v4c2) 5%; impl only (v4c3) 12%
- Pattern holds for gpt-5.4-mini: locatn 56.2%, lo+im 56.2%, lo+im+sc 56.2% pass rate vs scope 18.8%
- Pattern holds for gpt-5-mini: lo+im 50%, lo+im+sc 50% vs scope 12.5%

**Mechanism:** Each axis addresses a distinct failure mode. Location alone does not help if the model does not know HOW to fix; implementation alone does not help if the model is in the wrong file.

### Theme 4: Failure Modes Are Model-Specific

**Claim:** Different models fail in characteristically different ways, and the optimal intervention depends on the model's failure mode.

**Evidence:**
- **gpt-5.4-mini:** Over-editing (avg 4.7 files, over_edit_rate 0.875-1.0). Always touches the correct file but breaks things with excessive changes. Fixes are REIMPLEMENTED (45/50 in combined analysis). High oracle accuracy but high LEG rate -- understands the bug but cannot implement cleanly.
- **gpt-5-mini:** Depth confusion / wrong file (avg 1.3 files). Precise but targets wrong file. Fixes are REDIRECTED (6/6 in combined analysis). When pointed at the right file, execution fidelity is the highest of all models (0.72).
- **gpt-4o-mini:** Coherent failures dominate. Oracle accuracy is lowest (0.31) -- the model builds internally-consistent arguments for incorrect mechanisms. Classifier would score many of these CORRECT because the code follows the (wrong) reasoning. Hints rarely help (3-14% fix rate) because they assume the model's mechanism understanding is salvageable.

**Source:** hint_ablation_v3_analysis, hint_ablation_combined_analysis, hint_effectiveness_report (all three independently identify this pattern).

### Theme 5: Some Cases Are Fundamentally Unfixable by Hints

**Claim:** When the model has a fundamentally wrong causal model of the system, no single-sentence hint can redirect it. These are coherent failures (Oracle=WRONG, Classifier=CORRECT) that resist intervention.

**Evidence:**
- billing_aggregation: 0 fixes across ALL hints, ALL models, ALL 5 ablation rounds (hint_effectiveness_report)
- billing_aggregation: 0/5 pass rate in both baseline and critique conditions (ddc_ablation_audit)
- Pattern: model always blames tier resolution (plan_resolver.py) instead of unit aggregation (collector.py)
- config_derivation_chain (trap_1): 0 fixes for gpt-4o-mini and gpt-5-mini across all hints

**Mechanism:** The model's internal representation of the system's causal structure is wrong at a fundamental level. The classifier would score these CORRECT because the code faithfully implements the wrong causal theory. The oracle scores them WRONG because the theory does not match ground truth. Hints that say "fix earlier in the chain" do not help when the model disagrees about what the chain IS.

### Theme 6: The Three Evaluators Serve Distinct, Non-Redundant Roles

**Claim:** The spec oracle (execution), generic oracle (truth), and classifier (alignment) each measure a genuinely different axis. No evaluator is redundant or uninformative.

**Evidence:**
- Spec oracle: 0% error rate across 703 DDC records; perfectly calibrated for execution correctness
- Generic oracle: 46% CORRECT on DDC; measures mechanism truth with documented leniency (40 wrong-file-correct-oracle cases)
- Classifier: ~98% CORRECT on SWE-bench, ~50% oracle-classifier disagreement on DDC
- The ~50% disagreement is the classifier doing its job: detecting coherent failures where Oracle=WRONG but Classifier=CORRECT

**Role of each evaluator:**
- **Spec oracle** answers: "Did it work?" -- the ground truth of execution. Perfectly reliable.
- **Generic oracle** answers: "Did the model understand the bug?" -- the ground truth of reasoning. Systematically lenient (credits mechanism description even when the model fixes the wrong file).
- **Classifier** answers: "Did the model do what it said it would do?" -- the ground truth of alignment. High CORRECT rates are expected and correct. The classifier's value is in identifying the *minority* of cases where code contradicts reasoning (Classifier=INCORRECT), which represents a distinct failure mode from coherent-but-wrong.

---

## STEP 6 — FAILURE MODES + MECHANISMS

The four outcome categories (from Evaluation Semantics) map to distinct failure modes with different behavioral signatures:

### FM-A: True LEG (Oracle=CORRECT, Classifier=CORRECT, Execution=FAIL)

**Description:** Model correctly identifies the bug mechanism, writes code that follows from its reasoning, but the code does not fix the bug. Pure implementation quality failure.

**Where it appears:** Dominant failure mode across ALL analyses. 124 corrected LEG cases on DDC (ddc_metrics_audit). 36/59 = 61% of SWE-bench cases (swebench_audit). 19/31 = 61% of multi-file SWE-bench (swebench_validation).

**Sub-modes (from SWE-bench taxonomy):**
- Empty patch (37% of SWE-bench LEG): Model understands but produces no code changes
- Missing multi-file propagation (16%): Fixes one file correctly, misses second
- Cosmetic-only patch (11%): Touches right files but only reformats
- Subtle semantic error (11%): Fix is 80-90% correct but fails on edge cases
- Destructive over-editing (11%): Correct fix direction but breaks unrelated tests
- Helper not integrated (5%): Writes correct function but does not call it

**DDC-specific sub-mode:** Correct mechanism, wrong depth (downstream compensation). Model describes the causal chain but applies the fix at a downstream node. 72 R+E- instances in ddc_ablation_audit. Examples: auth_context fixes resolver.py instead of normalizer.py; config_derivation fixes deriver.py instead of parser.py.

### FM-B: Coherent Failure (Oracle=WRONG, Classifier=CORRECT, Execution=FAIL)

**Description:** Model builds a complete, internally-consistent argument for the wrong mechanism. The code faithfully implements a fix for a bug that is not the real bug. The classifier correctly scores this CORRECT because the code follows the reasoning. The oracle correctly scores this WRONG because the reasoning does not match ground truth.

**Where it appears:**
- DDC: ~50% of oracle-classifier disagreement cases (v3_v4_audit: 194 v3 disagreements, 159 v4 disagreements)
- SWE-bench: ~29% of cases (98% classifier CORRECT minus 69.5% oracle CORRECT)
- gpt-4o-mini: most affected (oracle accuracy only 0.31, meaning ~69% of cases are wrong-mechanism, and the classifier confirms the reasoning is internally coherent in most of those)

**Key insight:** These cases are NOT addressable by execution-focused hints (which assume the model's mechanism is correct). They require mechanism-level correction -- redirecting the model's understanding of WHAT is wrong, not HOW to fix it.

**Canonical example:** billing_aggregation -- model consistently identifies tier resolution (plan_resolver.py) as the cause, builds a coherent fix for that theory, and the code faithfully implements that fix. The classifier scores CORRECT. The oracle scores WRONG. The execution fails. No hint across 5 ablation rounds and 17 hint variants produces a single fix.

### FM-C: Lucky Fix (Oracle=WRONG, Execution=PASS)

**Description:** Model's stated reasoning is incorrect, but the generated code happens to fix the bug anyway. The model got the right answer for the wrong reason.

**Where it appears:** Rare across all analyses.
- DDC: 4 instances in ddc_ablation_audit; 8 total in ddc_metrics_audit
- SWE-bench validation: 1/31 (sphinx-8120: wrong mechanism but passing code)
- SWE-bench audit: 2/59

**Metrics link:** These inflate pass rates if used as evidence that the model "understood" the bug. The oracle correctly identifies these as WRONG mechanism. Execution pass alone is insufficient to measure understanding.

### FM-D: Over-Editing (gpt-5.4-mini specific)

**Description:** Model touches the correct file but also edits 4-5 additional files unnecessarily, introducing new bugs.

**Where it appears:** gpt-5.4-mini across ALL conditions: avg_files_changed 4.1-5.0, over_edit_rate 0.875-1.0.

**Evaluator interaction:** Inflates localization_accuracy to 0.97 (touching 5 files when 1 is correct guarantees hitting it). These cases often have Oracle=CORRECT (mechanism understood) and Classifier=CORRECT (code follows reasoning, which includes "fix these 5 files"), but Execution=FAIL because the extra edits break the system. This is a variant of true LEG where the implementation failure mode is specifically scope over-expansion.

### FM-E: Trap Anchoring (DDC-specific)

**Description:** In trap variants, the model anchors on an existing partial fix (the trap) rather than tracing to the root cause.

**Where it appears:** DDC cases with trap suffixes. Example: event_etl_chain_trap_3 -- model reproduces the trap_3 heuristic (preserve case for values with _ or -) instead of removing all lowercasing.

**Evaluator interaction:** The oracle may score CORRECT (model describes the right mechanism in text) while the spec oracle scores depth D or F (code implements the trap, not the root fix). The classifier scores CORRECT because the trap-level fix is coherent with the model's stated reasoning. The directed hint specifically targets this mode and is the only intervention that reliably fixes it.

### FM-F: False Positive Pass (Zero-File "Fix")

**Description:** Model returns 0 changed files on retry, and the test "passes" on original unmodified code.

**Where it appears:** hint_ablation_v3_analysis: 8 WARNING cases, all gpt-4o-mini.

**Metrics link:** These inflate fix counts if not filtered. The model gave up rather than fixing anything, and the test happened to pass on the baseline code. These are NOT true fixes.

---

## STEP 7 — CASE STUDIES

### Case Study 1: event_etl_chain_trap_3 (True LEG, Hint-Fixable)

**Bug pattern:** normalizer.py lowercases user_id, causing 'SYSADMIN' to become 'sysadmin', breaking case-sensitive USER_PROFILES lookup. Trap_3 heuristic: preserve case for values containing _ or - (works on primary dataset, fails on edge cases).

**Model behavior (gpt-4o-mini, ddc_ablation_audit):**
- Baseline: 1/5 pass (20%). Model reproduces the trap_3 heuristic.
- Critique+hint: 5/5 pass (100%). After directed hint "trace the data flow backward," model removes all lowercasing entirely.
- Delta: +80pp -- the largest improvement of any case in the entire experiment set.

**Evaluator analysis:** This is textbook true LEG. Oracle=CORRECT (model describes the lowercasing mechanism correctly). Classifier=CORRECT (trap-level fix follows from the stated reasoning). Execution=FAIL (trap fix fails on edge cases). The hint converts a true LEG into full success by redirecting the implementation from trap-level to root-level.

**Cross-analysis verification:** Consistent across ddc_ablation_audit (3/5 a0-to-a1 conversions), hint_ablation_v3_analysis (fixable), and hint_effectiveness_report (listed as hint-fixable).

### Case Study 2: billing_aggregation (Coherent Failure, Unfixable)

**Bug pattern:** collector.py has a timezone-boundary grouping bug in aggregate_usage. Model consistently blames tier resolution in plan_resolver.py.

**Model behavior:**
- 0% pass rate across ALL models, ALL conditions, ALL 5 ablation rounds
- 0/5 baseline, 0/5 critique in ddc_ablation_audit
- 0 fixes across 17 hints in hint_effectiveness_report

**Evaluator analysis:** This is the canonical coherent failure. Oracle=WRONG (model identifies wrong mechanism). Classifier=CORRECT (code faithfully implements the wrong fix). Execution=FAIL. The classifier's CORRECT score does not indicate the model is on the right track -- it indicates the model is *coherently* on the wrong track. No execution-level hint helps because the mechanism understanding is fundamentally wrong.

**Cross-analysis verification:** Consistently 0 across every analysis. The most robust negative result in the corpus.

### Case Study 3: gpt-5-mini REDIRECTED Fixes (Localization Failure, Hint-Fixable)

**Bug pattern:** Various DDC cases where the correct file is upstream (normalizer.py, serializer.py) but model targets downstream (resolver.py, transport.py).

**Model behavior:**
- All 6 of gpt-5-mini's fixes in the combined analysis were REDIRECTED (changed target file)
- auth_context_chain_trap_5: resolver.py to normalizer.py after first+min hint
- serialization_pipeline_chain_trap_1: transport.py to serializer.py after first-corruption hint
- The model is precise (1 file) but pointed at the wrong target

**Evaluator analysis:** Before hint: Oracle may be CORRECT (mechanism described in text matches), Classifier=CORRECT (code follows from reasoning about the wrong file), but execution fails because the wrong file was modified. The oracle's leniency here (crediting mechanism description without checking file choice) is documented. After hint: the model redirects to the correct file, and execution passes. This is a localization failure, not a LEG.

**Cross-analysis verification:** hint_ablation_v3_analysis, hint_ablation_combined, hint_effectiveness_report all independently identify this pattern.

---

## STEP 8 — WHAT IS RELIABLE VS NOT

### HIGH CONFIDENCE

| Finding | Basis | Sample Size | Consistency |
|---|---|---|---|
| LEG is dominant failure mode (50-61% of failures) | swebench_validation (61%), swebench_audit (61%), ddc analyses (variable but consistent) | 59-703 | Replicated across datasets |
| Spec oracle has 0% error rate on DDC | v3_v4_audit (703/703) | 703 | Perfect |
| Old LEG overcounted by ~24% | ddc_metrics_audit (164 to 124) | 703 | Verified by recompute script |
| Model failure modes are model-specific | hint_ablation_v3, combined, effectiveness (all 3 independently) | 703 | Consistent |
| billing_aggregation is unfixable by hints | 5 ablation rounds, 17 hints, 3 models | ~100+ trials | Zero fixes ever |
| Multi-axis hints > single-axis hints | hint_ablation_combined, v4_results, effectiveness | ~350 | Consistent ranking |
| gpt-5.4-mini over-edits (4-5 files avg) | All DDC analyses | 240 | Universal |
| Oracle-classifier disagreement (~50% on DDC) reflects coherent failures, not evaluator error | v3_v4_audit (703 records, 56 hand-audited) | 703 | Structurally explained by evaluator design |

### MEDIUM CONFIDENCE

| Finding | Basis | Limitation |
|---|---|---|
| LEG rate of 61% on SWE-bench | Two studies (31 and 59 cases) | Single model (gpt-5.4-mini), single attempt, no retries |
| Generic oracle is systematically lenient | v3_v4_audit (40 cases documented) | Leniency is by design; the 40 cases may not fully characterize the scope |
| Hint effectiveness varies 3-57% | hint_effectiveness_report | 1 trial per case-hint-model; no statistical power; uneven denominators |
| Coherent failures account for ~29% of SWE-bench attempts | Derived from 98% classifier CORRECT vs 69.5% oracle CORRECT | Approximate; assumes classifier and oracle independence |
| gpt-5-mini has best execution fidelity (0.72) | ddc_metrics_audit | n=120 (smallest); 8 per condition |

### LOW CONFIDENCE

| Finding | Limitation |
|---|---|
| gpt-4o-mini hint fixes (3-14% rate) | 8 WARNING false-positive cases in v3; possible inflation |
| v3 vs v4 hint comparisons | Confounded by critique prompt change; cannot isolate hint effect from prompt effect |
| Specific per-condition pass rates for gpt-5-mini | n=8 per condition; any single case flip changes the rate by 12.5pp |
| hint_ablation_v3_results.json data | Shows only passing cases (filtered view); misleading if interpreted as full results |
| "4 MODELS" claim in hint_effectiveness_report | Only 3 models reported; fourth model unknown |
| V2 hint effectiveness generalization | Tested with gpt-4o-mini only; no cross-model data for V2 cases |

### Findings That Should NOT Be Trusted

1. **hint_ablation_v3_results.json** as a standalone data source: This JSON shows only already-passing cases with pass_rate=1.0 and tiny case counts (1-4). It is a filtered view, NOT a complete results file. Using it alone gives wildly misleading conclusions.

2. **Any claim that classifier CORRECT implies mechanism correctness.** The classifier measures reasoning-code alignment, not truth. A ~98% classifier CORRECT rate paired with a ~70% oracle CORRECT rate means ~28% of cases are coherent failures where the model faithfully implements a wrong mechanism. The classifier is functioning correctly in those cases -- it detected alignment. The oracle detected the wrong mechanism.

3. **gpt-4o-mini "fixes" from zero-file returns:** The 8 WARNING cases in hint_ablation_v3 where gpt-4o-mini returned 0 files are false positives (test passed on unmodified code).

4. **Direct v3 vs v4 comparisons:** The critique prompt changed between rounds. Any v3-vs-v4 delta reflects BOTH the hint content difference AND the prompt framing difference. These cannot be separated.

5. **Per-condition results for gpt-5-mini:** With n=8 per condition, a single case flip changes any metric by 12.5pp. These are directional estimates, not precise measurements.

---

## STEP 9 — FINAL SYNTHESIS

### 1. What We KNOW (Robust Conclusions)

**A. The Reasoning-Execution Gap is real, large, and consistent.** Models correctly identify bug mechanisms (oracle=CORRECT) 57-71% of the time but convert that understanding to working code (execution=PASS) only 9-59% of the time. On SWE-bench multi-file bugs, the conversion rate is 9-17%. On synthetic DDC cases, it is 41-72% depending on model. LEG accounts for 61% of SWE-bench failures and 12-24% of DDC trial outcomes.

**B. The 3-axis decomposition (mechanism / location / execution) is analytically valuable.** It reveals that the old LEG metric overcounted by ~24%, conflating location errors with execution errors. The corrected definition isolates true implementation quality failures. Each axis represents a distinct failure mode addressable by different interventions.

**C. Coherent failures are pervasive and distinct from LEG.** Approximately 50% of DDC trials and ~29% of SWE-bench trials involve models that build internally-consistent arguments for wrong mechanisms (Oracle=WRONG, Classifier=CORRECT). These are not evaluator disagreements -- they are a distinct failure category where the model's entire reasoning chain is self-consistent but factually wrong. Hints that assume correct reasoning fail on these cases.

**D. Hints help, but modestly and unevenly.** The best hint (location+scope+impl combined) fixes 27% of attempted cases; plain retry fixes 8%. Hints are most effective for gpt-5.4-mini (up to 57% fix rate) and nearly useless for gpt-4o-mini (3-14%). Effectiveness depends on matching the hint type to the model's specific failure mode.

**E. Some failures are fundamentally resistant to single-sentence hints.** When the model has a wrong causal model (coherent failure), no hint tested across 5 ablation rounds and 17 hint variants produced a single fix on billing_aggregation.

**F. The three evaluators are complementary, not redundant.** The spec oracle measures execution (0% error). The generic oracle measures mechanism truth (systematic leniency on location). The classifier measures reasoning-code alignment (high CORRECT rates are expected). Each captures information the others cannot. Oracle-classifier disagreement is structurally expected and informative -- it quantifies the coherent failure rate.

### 2. What We THINK (Promising but Uncertain)

**A. LEG may be even higher on truly complex real-world bugs.** The 61% figure comes from gpt-5.4-mini only. Other models may have different LEG profiles on SWE-bench (not tested).

**B. Implementation-axis hints may be the key differentiator for stronger models.** gpt-5-mini's best fixes came from implementation (v4c3: 50%) and combined (v4c6/c7: 50%) hints, suggesting that as models improve at mechanism and location, the bottleneck shifts to implementation quality. But n=8 makes this uncertain.

**C. The critique prompt matters more than any individual hint.** The v3-to-v4 prompt change (from reasoning-reinforcing to neutral) may account for a significant portion of the improvement, but the effect cannot be isolated.

**D. The classifier could be used to detect incoherent failures.** The minority of cases where Classifier=INCORRECT represent a distinct failure mode (code contradicts stated reasoning) that is currently unexplored as a diagnostic signal.

### 3. What Is WRONG or Misleading in Prior Analyses

**A. The old LEG definition inflated LEG counts by ~24%.** Reports using mechanism_correct AND NOT execution_pass (without the location check) attribute location errors to the execution gap. The ddc_metrics_audit corrected this.

**B. Prior analyses mischaracterize classifier CORRECT as uninformative.** The classifier does not measure truth -- but it does measure alignment. Calling it "useless" discards the information it provides about coherent failures. A high classifier CORRECT rate paired with a lower oracle CORRECT rate is diagnostic: it quantifies how often models build internally-consistent but factually wrong reasoning chains.

**C. Prior analyses treat oracle-classifier disagreement as an anomaly.** The ~50% disagreement rate on DDC is not an evaluator problem. It is a measurement of coherent failure prevalence. Treating it as noise obscures one of the most important behavioral findings.

**D. hint_ablation_v3_results.json is misleading if read standalone.** Shows only passing cases, making it appear every condition has 100% pass rate.

**E. The "4 MODELS" claim in hint_effectiveness_report is incorrect.** Only 3 models are reported.

**F. gpt-5.4-mini's 0.97 localization accuracy is mechanically inflated.** Touching ~5 files when only 1 is correct guarantees a high hit rate. This is not evidence of superior localization ability.

**G. v3 vs v4 comparisons are confounded.** The critique prompt change between rounds means no direct comparison isolates hint effectiveness alone.

### 4. What Should Be Ignored Going Forward

1. **hint_ablation_v3_results.json** -- use ddc_recomputed_metrics.json instead
2. **Old LEG definition** -- always use the corrected (3-axis) version
3. **gpt-5-mini per-condition precision** -- n=8 is insufficient for reliable per-condition estimates
4. **v3 vs v4 direct comparisons** -- confounded by prompt change
5. **gpt-4o-mini "fixes" flagged as WARNING** in v3 analysis -- these are false positives

### 5. What Should Be Reinterpreted Going Forward

1. **Classifier data is informative, not disposable.** The classifier measures reasoning-code alignment. Its high CORRECT rate, combined with the oracle's lower CORRECT rate, quantifies the coherent failure rate. Future analyses should report the Oracle x Classifier cross-tabulation explicitly.

2. **Oracle-classifier disagreement is a behavioral measurement.** It measures how often models coherently implement wrong mechanisms. This should be reported as a first-class metric, not dismissed as evaluator noise.

3. **The four outcome categories (Full Success, True LEG, Coherent Failure, Lucky Fix) should replace the binary pass/fail framing.** Each category has different behavioral implications and responds differently to interventions.
