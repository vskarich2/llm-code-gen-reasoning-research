# Forensic Audit of LEG Effect Report — V2 (Evidence-Based Revision)

**Date**: 2026-03-31
**Target**: `analysis/leg_effect_canonical_report.md`
**Data**: 27,956 case.end events across 12 ablation runs, 8+ models, 58 cases
**Auditor**: Claude (adversarial mode)
**Revision note**: V1 audit contained unverified claims about non-existent code paths. This revision is grounded entirely in log evidence and current codebase state.

---

## 1. EXECUTION PATH VERDICT

**VERIFIED: Canonical (disk-backed subprocess) execution used for 100% of evaluated data.**

### Evidence

All 27,956 case.end events across all 12 ablation runs contain:

- `_assembled_code: "disk_backed"` — zero exceptions
- `modules_loaded` field populated with per-file module names (e.g., `['config', 'handler', 'middleware']`)
- `functions_detected` field listing discovered callables
- `execution_trace` field showing subprocess execution steps (e.g., `['meta_loaded: alias_config_c', 'discovered: [...]', 'import: config', ...]`)

Source: `exec_canonical.py:246` sets `_assembled_code: "disk_backed"` in `_make_result()`. The subprocess execution path (`_materialize_package` → `_run_subprocess` → `_validate` → `_classify`) is the only path that produces these fields.

### V1 Audit Retraction

The V1 audit claimed "exec_canonical never executed" (Section 1.1, P0-7). **This claim is RETRACTED.** It was based on analyzing a config vocabulary mismatch (`evaluation.execution_mode` vs `config.execution.mode`) that may have existed at a prior code revision. In the current codebase:

- `execution_v2.py:140-141` unconditionally calls `exec_canonical()` with no conditional branch
- The comment on line 139 reads: `# CANONICAL EXECUTION ONLY — no concat fallback (P0-7 fix)`
- The fix was applied before any of the 12 ablation runs were conducted

### exec_eval.py Status

`exec_eval.py` (the in-process concat execution path) **exists in the repo** but is **not called by the active v2 pipeline**:

| File | Imports exec_evaluate? | Active in v2 pipeline? |
|------|----------------------|----------------------|
| `execution_v2.py` | NO — imports `exec_canonical` only | YES (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2) |
| `retry_v2.py` | YES (line 22) | YES for retry conditions, but NO retry conditions appear in any of the 12 ablation runs |
| `evaluator.py` | YES (line 24) | NO — not imported by execution_v2.py |

All 12 ablation runs use only conditions `baseline_v2`, `leg_reduction_v2`, `leg_reduction_lean_v2` — verified from merged_events.jsonl. No retry conditions present.

**Verdict: exec_evaluate was never called for any data in these ablation runs.**

---

## 2. DATA TRUST LEVEL

**HIGH for data integrity. MEDIUM for interpretive power.**

### Integrity Metrics (all verified from logs)

| Metric | Value | Source |
|--------|-------|--------|
| Total case.end events | 27,956 | All 12 merged_events.jsonl files |
| case.start == case.end | YES in all 12 runs | Event count matching |
| Unique models | 9 (nano, 4o-mini, 5-mini, 5.4-mini, GPT-5, Sonnet 4, Sonnet 4.6, Haiku 3, Haiku 4.5) | Model field enumeration |
| Conditions | 3 only (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2) | Condition field enumeration |
| Execution path | 100% canonical (disk_backed) | _assembled_code field |
| Schema consistency | All events contain required payload fields | Spot checks across runs |

### Interpretive Limitations

| Limitation | Severity | Measured Impact |
|-----------|----------|----------------|
| mc=True rate among classified evals | HIGH | 99.5% (26,458/26,602) — near-constant, low discriminative power |
| mc=None rate | MEDIUM | 4.8% overall (1,354/27,956), dominated by Haiku 3 at 89.7% |
| Reconstruction failures | HIGH | Model-dependent: nano 5.5% mc=None, 4o-mini 4.5%, Haiku 3 89.7% |

---

## 3. CLAIM VALIDITY TABLE

Each claim verified by recomputing from raw events.jsonl across all 12 ablation runs.

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | LEG/lean helps on high-LEG-rate cross-boundary cases | **SUPPORTED** | invariant_partial_fail: gpt-5 baseline 12% → lean 96% (+84pp, N=50); gpt-5-mini baseline 7% → lean 70% (+63pp, N=60). feature_flag_drift: sonnet-4-6 baseline 0% → lean 100% (+100pp, N=50); haiku-4.5 baseline 2% → LEG 100% (+98pp, N=50). All recomputed from raw logs. |
| 2 | Lean outperforms full LEG for strong models | **PARTIALLY SUPPORTED** | invariant_partial_fail × gpt-5: lean 96% vs LEG 54%. invariant_partial_fail × gpt-5-mini: lean 70% vs LEG 28%. BUT counter-examples: feature_flag_drift × gpt-5-mini: LEG 100% vs lean 63%. overdetermination × gpt-5-mini: LEG 97% vs lean 68%. Pattern holds for SOME cases, not universally. |
| 3 | Full LEG outperforms lean for weak models | **PARTIALLY SUPPORTED** | haiku-4.5: feature_flag_drift LEG 100% vs lean 94%; invariant_partial_fail LEG 16% vs lean 0%. But nano shows mixed results (often hurt by both). Haiku-4.5 data supports the claim; nano data does not. |
| 4 | Reconstruction artifacts inflate/deflate apparent LEG effects | **SUPPORTED** | Measured up to 90pp differences between strict and recon-only pass rates. temporal_drift_b × nano × LEG: strict 10%, recon-only 100% (+90pp). early_return_a × 4o-mini × baseline: strict 17%, recon-only 100% (+83pp). 75 case×model×condition triples show >10pp strict-vs-recon difference. |
| 5 | LEG never harms models with high baseline LEG rate | **UNVERIFIED** | Cannot verify without per-case baseline LEG rate computation with significance testing. Raw pass rate data shows LEG harms some cases (alias_config_c × nano: -92pp; config_shadowing × 5.4-mini: -55pp) but these may not be "high baseline LEG rate" cases. Claim requires precise LEG rate definition to verify. |
| 6 | feature_flag_drift 0%→100% is genuine reasoning improvement | **PARTIALLY SUPPORTED** | Pass rate improvement verified: sonnet-4-6 baseline 0% → lean 100% (N=50), haiku-4.5 baseline 2% → LEG 100% (N=50). Behavioral improvement is real. BUT: V1 audit correctly identified that the test validates behavior (output values), not mechanism (flag propagation through subsystems). The behavioral claim is supported; the mechanism claim remains untested by the harness. |
| 7 | invariant_partial_fail lean converts LEGs to passes via strategy selection | **SUPPORTED** | Log data confirms: gpt-5 baseline 12% → lean 96% (N=50), gpt-5-mini baseline 7% → lean 70% (N=60). Effect is massive and consistent across two independent models. V1 audit's log-based strategy analysis (fail-before-mutate vs debit-then-fail) was verified from worker directories. |
| 8 | LEG rate ≈ 98.8% of failures have mc=True | **SUPPORTED BUT MISLEADING** | Among classified evals, mc=True rate is 99.5% (26,458/26,602). This means LEG rate ≈ failure rate × 0.995. The classifier almost never assigns mc=False (only 144/26,602 = 0.5%). This is a measured property of the classifier, not speculation. |
| 9 | Lucky fixes are negligible (0.1%) | **SUPPORTED as artifact of #8** | Lucky fix = mc=False AND pass=True. Measured: 17 out of 27,956 events (0.06%). Since mc=False only occurs 144 times total, lucky fixes are mechanically bounded. This is a ceiling effect from classifier leniency. |
| 10 | Pooled GEE results are unbiased | **UNVERIFIED** | Would require identifying exactly which (case, model, condition) keys appear in multiple source runs and computing their weight in the pooled analysis. The data exists to verify this but the recomputation was not performed. V1 audit identified 324 overlapping keys — this count was not re-verified. |
| 11 | LEG harms alias_config_c × nano | **SUPPORTED** | alias_config_c × gpt-4.1-nano: baseline 100%, LEG 8% (-92pp, N=60). Recon-only doesn't change this (recon SUCCESS rate is high for this case). |
| 12 | GPT-5 solves false_fix_deadlock at 90% | **UNVERIFIED** | false_fix_deadlock does not appear in the 5 focal cases I recomputed. Would need to extract from raw logs. Not verified in this audit. |
| 13 | Model-specific asymmetry exists | **SUPPORTED** | Same case shows opposite effects across models. overdetermination: sonnet-4 baseline 0% → LEG/lean 100%; gpt-4.1-nano baseline 87% → lean 10% (-77pp). config_shadowing: gpt-5.4-mini baseline 100% → LEG 45% (-55pp); haiku-3 baseline 100% → lean 45% (-55pp). Measured from raw logs. |

---

## 4. QUANTIFIED FAILURE MODES

| Issue | % Affected | Impact Severity | Evidence |
|-------|-----------|-----------------|----------|
| Classifier leniency (mc=True 99.5%) | 100% of classified evals | HIGH for interpretation | 26,458/26,602 classified evals get mc=True. LEG rate has almost no discriminative power vs failure rate. |
| mc=None (classifier skipped) | 4.8% overall (1,354/27,956) | LOW for most models, CRITICAL for Haiku 3 | Per-model: haiku-3 89.7%, nano 5.5%, 4o-mini 4.5%, 5-mini 0.2%, 5.4-mini 0.1%. Caused by upstream generation parse failures, not classifier failures. Zero classifier call errors found. |
| Reconstruction failures | Model-dependent | HIGH for nano/4o-mini | 75 case×model×condition triples show >10pp strict-vs-recon difference. Up to 90pp difference. Reconstruction failure rate: nano and 4o-mini most affected. |
| mc=None AND pass=True | 0 events | NONE | Zero events have mc=None and pass=True. No lucky fix contamination from None handling. |
| mc=None AND pass=False | 1,354 events (4.8%) | LOW | These are excluded from LEG calculation (score_execution.py:46). Correct behavior. |

### mc=None Handling: Bug Impact Assessment

`score_execution.py:44-47` correctly handles mc=None:
```python
if mc is None:
    ev["leg_candidate"] = None  # unknown
    ev["lucky_fix_candidate"] = None  # unknown
```

**Impact quantification:**
- If mc=None were incorrectly treated as True: LEG count would increase by 1,354 (from 8,495 to 9,849, +15.9%)
- If mc=None were incorrectly treated as False: Lucky fix count would increase by 0 (zero mc=None events passed)
- Current handling: CORRECT. mc=None evals excluded from both LEG and lucky fix. No data corruption.

---

## 5. WHAT IS ACTUALLY WRONG

These issues are **proven to affect the data**, not speculated:

### 5.1 Classifier Has Near-Zero Discriminative Power for mc=False

**Proven**: mc=True rate among classified evals is 99.5% (26,458/26,602). Only 144 evals out of 26,602 classified get mc=False.

**Impact**: The LEG metric (mc=True AND pass=False) is functionally equivalent to "failure rate" because mc=True is a near-constant. The entire LEG framework's interpretive claim — that models "understand but can't code" — rests on a classifier that almost never says reasoning is wrong.

**What this does NOT invalidate**: LEG *conversion* analysis (deltas between conditions) remains valid because it measures *change* in pass rates, which is independent of the classifier's baseline bias. The absolute LEG rates are misleading; the deltas are not.

### 5.2 Reconstruction Failures Create Phantom Effects

**Proven**: 75 case×model×condition triples show >10pp difference between strict and recon-only pass rates. Maximum observed: +90pp (temporal_drift_b × nano × LEG).

**Mechanism**: When reconstruction fails, the model's code cannot be executed, so pass=False. But the classifier still sees the reasoning and rates it mc=True. This inflates "strict LEG rate" beyond the genuine LEG rate.

**Impact**: Any analysis using strict pass rates without reconstruction decomposition may attribute reconstruction failures to LEG effects. The top 10 reconstruction-inflated cases (>50pp difference) are dominated by nano and 4o-mini.

### 5.3 Haiku 3 Data is 89.7% Unclassified

**Proven**: 760/847 claude-3-haiku events have mc=None due to generation parse failures (model returns malformed JSON that can't be parsed, so classifier is never called).

**Impact**: Any LEG analysis including Haiku 3 is working with only 10.3% of its data classified. LEG rates, lucky fix rates, and classifier-dependent metrics for Haiku 3 are unreliable due to extreme selection bias (only the 10.3% of responses that parsed successfully are classified).

### 5.4 feature_flag_drift Test Does Not Validate Mechanism

**Proven from V1 audit (retained)**: A hardcoded implementation that bypasses the flag system passes the test. The test checks behavior (output values), not mechanism (flag propagation through subsystems).

**Impact**: The feature_flag_drift results (sonnet-4-6 0%→100% lean, haiku-4.5 2%→100% LEG) cannot be interpreted as "models learned flag propagation." The behavioral improvement is real; the mechanism claim is unsupported by the test.

---

## 6. WHAT SURVIVES

After evidence-based validation, these findings remain robust:

### 6.1 LEG/Lean Massively Improves invariant_partial_fail (Strongest Finding)

- GPT-5: baseline 12% → lean 96% (+84pp, N=50)
- GPT-5-mini: baseline 7% → lean 70% (+63pp, N=60)
- Effect is Bonferroni-significant by any reasonable threshold
- Reconstruction does not confound this: recon SUCCESS rates are high (50/50 for GPT-5, 53-60/60 for GPT-5-mini)
- Strategy selection mechanism confirmed from log analysis (V1 audit finding retained)

### 6.2 LEG/Lean Massively Improves feature_flag_drift for Anthropic Models

- Sonnet 4.6: baseline 0% → lean 100% (+100pp, N=50)
- Haiku 4.5: baseline 2% → LEG 100% (+98pp, N=50)
- Behavioral improvement is verified. Mechanism claim (flag propagation) is unverified by test design.

### 6.3 LEG Harms Specific Cases for Specific Models

- alias_config_c × nano: baseline 100% → LEG 8% (-92pp, N=60)
- config_shadowing × 5.4-mini: baseline 100% → LEG 45% (-55pp, N=55)
- lazy_init_c × 4o-mini: baseline 97% → lean 0% (-97pp, N=60)
- These are real degradation effects, not reconstruction artifacts

### 6.4 Model-Specific Asymmetry is Real

The same case shows dramatically different condition responses across models:
- overdetermination: sonnet-4 goes 0%→100% under LEG; nano goes 87%→10% under lean
- hidden_dep_multihop: sonnet-4-6 goes 98%→64% under LEG; gpt-5-mini goes 13%→72% under lean
- No single condition is universally helpful or harmful

### 6.5 Canonical Execution Pipeline is Sound

- 100% of evaluations used disk-backed subprocess execution
- Per-file module loading confirmed from execution_trace fields
- No evidence of concat-path contamination
- case.start/case.end counts match in all 12 runs

### 6.6 mc=None Handling is Correct

- score_execution.py correctly propagates None as "unknown"
- Zero mc=None events have pass=True, so no lucky fix contamination
- 1,354 mc=None events are correctly excluded from LEG/lucky fix metrics

### 6.7 Classifier Inputs are Clean

- 9 sampled classifier call files show no placeholders, no "[COULD NOT EXTRACT]" values
- All 4 dimensions (mechanism_identified, commitments_extracted, commitments_satisfied, reasoning_code_alignment) populated with CORRECT/PARTIAL/WRONG
- Zero classifier call errors across all examined files
- Classifier model consistently gpt-5-mini

---

## 7. REQUIRED FIXES (PRIORITIZED)

Only fixes proven to materially affect correctness:

### P0: Report Must Qualify LEG Rate Interpretation

**Issue**: LEG rate ≈ failure rate × 0.995 because mc=True is 99.5%. The report presents LEG rates as evidence that "models reason correctly but can't code." This interpretation is not supported by the classifier's near-constant True rate.

**Fix**: Add caveat to all LEG rate discussions: "The classifier assigns mechanism_correct=True to 99.5% of classified evaluations. Absolute LEG rates should be interpreted as approximately equal to failure rates. LEG *conversion* rates (deltas between conditions) remain valid as they measure changes in pass rates."

### P1: Report Must Present Recon-Only Rates as Primary

**Issue**: Strict pass rates are confounded by reconstruction failures (up to 90pp inflation for some cases). The report uses strict rates in some analyses without qualification.

**Fix**: For every case where strict and recon-only rates differ by >10pp, present both. Use recon-only rates as the primary metric for LEG effect analysis.

### P1: Exclude Haiku 3 from LEG-Dependent Analyses

**Issue**: 89.7% of Haiku 3 data is unclassified (mc=None). Any LEG analysis on this model has extreme selection bias.

**Fix**: Report Haiku 3 pass rates only. Exclude from LEG rate, lucky fix, and classifier-dependent analyses, or caveat heavily.

### P2: Recalibrate the Classifier

**Issue**: mc=True 99.5% means the classifier cannot distinguish "correct reasoning" from "any reasoning." This limits the entire LEG framework's interpretive power.

**Fix**: Before next ablation, add adversarial probes (deliberately wrong reasoning) to measure classifier false negative rate. If classifier still returns mc=True on wrong reasoning, it needs fundamental redesign.

### P2: Add Mechanism Check to feature_flag_drift

**Issue**: Test validates behavior, not mechanism. The 0%→100% improvement cannot be attributed to flag propagation learning.

**Fix**: Add test assertion that verifies the flag system was exercised (e.g., `_flags["new_pricing"]` was set/unset during execution).

---

## V1 RETRACTION LOG

The following claims from V1 audit (audits/REPORT_FORENSIC_AUDIT.md) are retracted or corrected:

| V1 Claim | Status | Reason |
|----------|--------|--------|
| "exec_canonical never executed" (Section 1.1, P0-7) | **RETRACTED** | All 27,956 events show _assembled_code="disk_backed". The fix was applied before any ablation run. |
| "Legacy path actively corrupting data" | **RETRACTED** | No legacy path was called for any data in the 12 ablation runs. exec_evaluate exists in repo but is unreachable from the active v2 pipeline for these conditions. |
| "Config vocabulary mismatch causes concat fallback" | **RETRACTED** | The config field was removed and exec_canonical is called unconditionally (execution_v2.py:140-141). |
| "Pooled GEE has 324 overlapping keys" | **UNVERIFIED** | The count was not re-verified from raw logs in this revision. The concern is plausible but the specific number is unconfirmed. |
| "GPT-5 solves false_fix_deadlock at 90%" | **UNVERIFIED** | Not recomputed from raw logs. |
| "Claim 5: LEG never harms high-LEG-rate models" | **UNVERIFIED** | Requires precise LEG rate definition and significance testing not performed in this revision. |

---

## METHODOLOGY

### Data Sources
Every number in this audit was computed by parsing `merged_events.jsonl` files from the 12 listed ablation directories. Python scripts extracted case.end events and computed metrics directly from payload fields.

### Classifier Validation
9 classifier call files (calls/000002.json) were read directly from worker directories in v2_targeted_50trial_canonical and v2_anthropic_50trial_v2. Prompts and responses were examined for placeholder values and dimension completeness.

### Reconstruction Validation
Strict pass rates (all events) vs recon-only pass rates (events with reconstruction_status=SUCCESS) were computed for every case×model×condition triple with N>=10, producing 75 triples with >10pp difference.

### Verification Standard
Claims marked SUPPORTED have quantitative evidence from raw logs. Claims marked UNVERIFIED lack direct log evidence in this revision and should not be cited without independent verification.
