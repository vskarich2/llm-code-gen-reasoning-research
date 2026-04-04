# Classifier Adversarial Probe Design — Plan v2

**Date**: 2026-03-31
**Revision**: v2 — extends v1 with Type F (realistic near-miss), Type G (code/reasoning decoupling), 4D scoring, increased sample size, confidence calibration.

## What Changed from v1

1. Added Type F (realistic near-miss from real logs) — 18 probes from actual failed model outputs
2. Added Type G (correct code + wrong reasoning) — 6 probes testing classifier leakage
3. Expanded scoring from 1D (mechanism_identified) to full 4D evaluation
4. Tightened expected label definitions — no ambiguous "WRONG or PARTIAL"
5. Increased sample size: 39 probes × 10 trials = 390 classifier calls
6. Added confidence calibration analysis
7. Separated adversarial / realistic / leakage FN rates

## Core Objective

Calibrate the classifier's false negative rate: how often does it return mechanism_identified=CORRECT when the reasoning is actually wrong?

Determine whether the 99.5% mc=True rate reflects real LLM capability or classifier blindness.

---

## 1. PROBE TAXONOMY

### Type A: WRONG MECHANISM, COHERENT CODE (3 probes)

Fabricate a root cause that is factually wrong about the code but internally consistent. Produce code that implements the wrong fix.

| Probe | Case | Adversarial Root Cause | Code Change |
|-------|------|----------------------|-------------|
| A-01 | stale_cache_a | "get_product reads from _db instead of _cache when product exists" | Add `if pid in _db: return _db[pid]` to get_product |
| A-02 | config_shadowing | "create_config performs a shallow copy instead of deep copy" | Change create_config to use copy.deepcopy |
| A-03 | invariant_partial_fail | "execute_transfer doesn't validate negative balances before debit" | Add `if sender.balance < amount: raise ValueError` |

**Expected**: mechanism_identified = WRONG
**Acceptable outputs**: mechanism_identified = WRONG only
**If CORRECT**: Classifier cannot detect wrong-but-coherent reasoning

### Type B: RIGHT KEYWORDS, WRONG CAUSAL CHAIN (3 probes)

Use correct bug-type keywords but describe a different causal mechanism.

| Probe | Case | Adversarial Root Cause | Code Change |
|-------|------|----------------------|-------------|
| B-01 | stale_cache_a | "_cache uses a TTL that expires too quickly" (no TTL exists) | Add a TTL mechanism to _cache |
| B-02 | lost_update | "counter's initial _value is wrong" | Change initial _value from 0 to 1 |
| B-03 | alias_config_c | "DEFAULTS is imported by value, not reference" | Wrap DEFAULTS access in dict() |

**Expected**: mechanism_identified != CORRECT
**Acceptable outputs**: WRONG or PARTIAL
**If CORRECT**: Classifier is keyword-matching, not evaluating causal chains

### Type C: VAGUE MECHANISM (3 probes)

Generic bug description without specific function names, variable names, or code anchors.

| Probe | Case | Adversarial Root Cause | Code Change |
|-------|------|----------------------|-------------|
| C-01 | stale_cache_a | "There is a data consistency issue where stale values are returned after modification" | Original buggy code (no change) |
| C-02 | config_shadowing | "The configuration system has a bug where some functions read wrong values" | Original buggy code (no change) |
| C-03 | invariant_partial_fail | "The transfer has a state management issue" | Original buggy code (no change) |

**Expected**: mechanism_identified != CORRECT
**Acceptable outputs**: WRONG or PARTIAL
**If CORRECT**: Classifier doesn't enforce "concrete code anchor" from its own rubric

### Type D: CORRECT MECHANISM — POSITIVE CONTROL (3 probes)

Actual correct root cause, correct fix strategy, reference fix code.

| Probe | Case | Root Cause | Code |
|-------|------|-----------|------|
| D-01 | stale_cache_a | "update_product writes DB but doesn't invalidate _cache" | Reference fix: add _cache.pop(product_id, None) |
| D-02 | config_shadowing | "DEFAULTS timeout is 5 instead of 30, masked by env override on request path" | Reference fix: change timeout to 30 |
| D-03 | invariant_partial_fail | "sender.balance decremented before credit; no rollback on failure" | Reference fix: try/except with sender.balance += amount |

**Expected**: mechanism_identified = CORRECT
**Acceptable outputs**: CORRECT only
**If not CORRECT**: Classifier is broken in both directions

### Type E: CORRECT SYMPTOM, WRONG CAUSE (3 probes)

Accurately describe observable symptom but attribute it to the wrong mechanism.

| Probe | Case | Adversarial Root Cause | Code Change |
|-------|------|----------------------|-------------|
| E-01 | stale_cache_a | "After update_product, get_product returns old data because _db.update creates a new dict entry instead of modifying in place" | Change _db update to re-assign |
| E-02 | config_shadowing | "run_background_job uses wrong timeout because DEFAULTS is mutated by create_config" (create_config doesn't mutate DEFAULTS) | Add DEFAULTS copy in create_config |
| E-03 | lost_update | "Counter reaches wrong value because apply_steps doesn't lock the counter" (bug is in make_increment_steps, not apply_steps) | Add lock to apply_steps |

**Expected**: mechanism_identified != CORRECT
**Acceptable outputs**: WRONG or PARTIAL
**If CORRECT**: Classifier accepts symptom description as mechanism identification

### Type F: REALISTIC NEAR-MISS FROM REAL LOGS (18 probes) — HIGHEST PRIORITY

Real model outputs extracted from actual ablation logs. No modification to reasoning or code. These test the classifier on its actual input distribution.

**Source**: 18 candidates from `audits/type_f_probe_candidates.md`, extracted from worker directories.

**6 highest-value probes** (classifier gave ALL 4 dimensions CORRECT despite wrong mechanism):

| Probe | Case | Model | What's Wrong |
|-------|------|-------|-------------|
| F-03 | cache_invalidation_order | gpt-5.4-mini | Model says "no fix needed" for a known bug. 4/4 CORRECT. |
| F-09 | hidden_dep_multihop | gpt-4o-mini | save_user gets overwrite=False when it needs True — the exact trap. 4/4 CORRECT. |
| F-10 | hidden_dep_multihop | gpt-5-mini | Uses only_if_absent=True for save_user, preserving the bug it claims to fix. 4/4 CORRECT. |
| F-11 | hidden_dep_multihop | gpt-5.4-mini | Chooses cache_put_if_absent as consolidation target (wrong one). 4/4 CORRECT. |
| F-14 | invariant_partial_fail | gpt-5-mini | Diagnoses the real issue but fixes logging separation instead of adding rollback. 4/4 CORRECT. |
| F-16 | lost_update | claude-sonnet-4 | Generated code functionally identical to buggy original (only docstrings changed "BUG" → "FIXED"). 4/4 CORRECT. |

**Remaining 12 probes** (F-01, F-02, F-04 through F-08, F-12, F-13, F-15, F-17, F-18): mixed classifier results, various models. Full details in `audits/type_f_probe_candidates.md`.

**Construction**: For each probe, extract from the worker directory:
- root_cause and fix_strategy from calls/000001.json (generation call, parsed from response)
- code from calls/000001.json (generated files)
- Feed through the classifier pipeline exactly as production does

**Expected**: mechanism_identified != CORRECT (for the 6 high-value probes where mechanism is verifiably wrong)
**Note**: For the remaining 12, the "correct" label must be determined per-probe based on manual review of whether the mechanism identification is genuinely correct. Some may legitimately be CORRECT despite the code failing.

**If CORRECT on the 6 high-value probes**: This is a TRUE in-distribution false negative — the classifier fails on real model outputs under normal operating conditions.

### Type G: CORRECT CODE, WRONG REASONING — LEAKAGE TEST (6 probes)

Take a passing solution from logs, replace reasoning with an incorrect explanation. Tests whether the classifier evaluates code correctness instead of reasoning quality.

| Probe | Case | Source Model | Wrong Root Cause |
|-------|------|-------------|-----------------|
| G-01 | stale_cache_a | gpt-4.1-nano | "get_product's shallow copy via dict() shares nested mutable objects with _db" |
| G-02 | config_shadowing | gpt-5-mini | "run_background_job calls get_defaults() instead of get_config(), bypassing _OVERRIDES" (the trap fix) |
| G-03 | invariant_partial_fail | gpt-4.1-nano | "record_transfer_attempt in ledger shows status='pending' permanently — inconsistent audit trail" |
| G-04 | lost_update | gpt-4.1-nano | "run_steps executes all steps sequentially; interleaved_double_increment arranges steps in wrong order" |
| G-05 | alias_config_c | gpt-4.1-nano | "ConfigMiddleware.__init__ caches create_config() at instantiation; reset_defaults() creates stale middleware" |
| G-06 | cache_invalidation_order | gpt-4.1-nano | "cache_conditional_set has off-by-one in version comparison; initial version should start at -1" |

**Construction**: Keep the model's correct generated code exactly as-is (it passes tests). Replace root_cause and fix_strategy with the wrong reasoning above. Generate a fix_strategy consistent with each wrong root_cause.

**Expected**: mechanism_identified != CORRECT
**Acceptable outputs**: WRONG or PARTIAL
**If CORRECT**: Classifier is using code outcome to judge reasoning — it's cheating

---

## 2. SAMPLING STRATEGY

### Type F Construction from Logs

1. For each of the 18 Type F probes, the worker directory path is known (recorded in `audits/type_f_probe_candidates.md`)
2. Read `calls/000001.json` from each worker directory to extract:
   - `response_raw`: the full model response
   - Parse it using `parse_v2_execution` to get root_cause, fix_strategy, files_dict
3. Read original case code files from cases_v2.json
4. Reconstruct code files using `reconstruct_strict` (same as production)
5. Feed (root_cause, fix_strategy, code, case) through `build_classifier_v2_vars` → `assembly_engine.build` → `call_model` → `parse_classifier_v2_output`

### Model Coverage

| Model | Type F probes | Type G probes | Total |
|-------|--------------|--------------|-------|
| gpt-4.1-nano | 3 | 4 | 7 |
| gpt-4o-mini | 5 | 0 | 5 |
| gpt-5-mini | 4 | 0 | 4 |
| gpt-5.4-mini | 4 | 0 | 4 |
| claude-sonnet-4 | 2 | 0 | 2 |

Types A-E use hand-crafted inputs (model-independent).

### Case Coverage

| Case | A | B | C | D | E | F | G | Total |
|------|---|---|---|---|---|---|---|-------|
| stale_cache_a | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 6 |
| config_shadowing | 1 | 0 | 1 | 1 | 1 | 4 | 1 | 9 |
| invariant_partial_fail | 1 | 0 | 1 | 1 | 0 | 4 | 1 | 8 |
| lost_update | 0 | 1 | 0 | 0 | 1 | 3 | 1 | 6 |
| alias_config_c | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 2 |
| cache_invalidation_order | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 4 |
| hidden_dep_multihop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 4 |

---

## 3. SCORING FRAMEWORK

### 4D Evaluation

Every probe is scored on all 4 classifier dimensions:

| Dimension | What it measures | Strict threshold |
|-----------|-----------------|-----------------|
| mechanism_identified | Was the root cause correctly identified? | CORRECT = True |
| commitments_extracted | Were fix commitments extracted from reasoning? | CORRECT or PARTIAL = True |
| commitments_satisfied | Does the code satisfy the stated commitments? | CORRECT or PARTIAL = True |
| reasoning_code_alignment | Does the code match the reasoning? | CORRECT = True |

### Correctness Definitions

| Metric | Definition |
|--------|-----------|
| **Strict correctness** | ALL 4 dimensions = CORRECT |
| **Weak correctness (mc)** | mechanism_identified = CORRECT |
| **Partial detection** | ANY dimension = PARTIAL or WRONG |
| **Full detection** | mechanism_identified = WRONG |

### Per-Probe Evaluation

For adversarial probes (A, B, C, E, F-high-value, G):

| Outcome | Classification |
|---------|---------------|
| mechanism_identified = CORRECT | **FALSE NEGATIVE** — classifier missed wrong reasoning |
| mechanism_identified = PARTIAL | **PARTIAL DETECTION** — classifier flagged but didn't reject |
| mechanism_identified = WRONG | **TRUE POSITIVE** — classifier correctly identified wrong reasoning |

For control probes (D):

| Outcome | Classification |
|---------|---------------|
| mechanism_identified = CORRECT | **TRUE POSITIVE** — classifier correctly accepted right reasoning |
| mechanism_identified != CORRECT | **FALSE POSITIVE** — classifier incorrectly rejected right reasoning |

### Expected Labels (Strict, No Ambiguity)

| Type | Expected mechanism_identified | Pass criterion |
|------|------------------------------|---------------|
| A | WRONG | mechanism_identified = WRONG |
| B | != CORRECT | mechanism_identified != CORRECT |
| C | != CORRECT | mechanism_identified != CORRECT |
| D | CORRECT | mechanism_identified = CORRECT |
| E | != CORRECT | mechanism_identified != CORRECT |
| F (6 high-value) | != CORRECT | mechanism_identified != CORRECT |
| F (12 remaining) | Per-probe manual label | Per-probe evaluation |
| G | != CORRECT | mechanism_identified != CORRECT |

---

## 4. METRICS

### Primary Metrics

| Metric | Formula | What it tells us |
|--------|---------|-----------------|
| **FN rate (adversarial)** | (Type A+B+C+E probes with mc=CORRECT) / (total A+B+C+E trials) | Classifier blindness to synthetic wrong reasoning |
| **FN rate (realistic)** | (Type F high-value probes with mc=CORRECT) / (total F high-value trials) | Classifier blindness to real model errors — the most important metric |
| **FN rate (leakage)** | (Type G probes with mc=CORRECT) / (total G trials) | Whether classifier uses code correctness as proxy for reasoning quality |
| **TP rate (control)** | (Type D probes with mc=CORRECT) / (total D trials) | Classifier baseline accuracy on correct reasoning |

### Per-Dimension Accuracy

For each dimension d in {mechanism_identified, commitments_extracted, commitments_satisfied, reasoning_code_alignment}:

- **Detection rate**: % of adversarial probes where dimension d != CORRECT
- **Control accuracy**: % of control probes where dimension d = CORRECT

### Joint Accuracy

- **Strict false negative rate**: % of adversarial probes with ALL 4 dimensions = CORRECT
- **Any-dimension detection rate**: % of adversarial probes with at least 1 dimension != CORRECT

### Confidence Calibration

For each probe trial, record the classifier's confidence (HIGH/MEDIUM/LOW).

| Analysis | Method |
|----------|--------|
| Confidence on false negatives | What % of FN trials have HIGH confidence? |
| Confidence on true positives | What % of TP trials have HIGH confidence? |
| Overconfidence rate | (HIGH confidence FN) / (all HIGH confidence trials) |

If the classifier outputs HIGH confidence on false negatives at the same rate as on true positives, confidence has zero discriminative value.

---

## 5. STATISTICAL PLAN

### Sample Size

| Category | Probes | Trials/probe | Total trials |
|----------|--------|-------------|-------------|
| Adversarial (A+B+C+E) | 12 | 10 | 120 |
| Realistic (F) | 18 | 10 | 180 |
| Leakage (G) | 6 | 10 | 60 |
| Control (D) | 3 | 10 | 30 |
| **Total** | **39** | **10** | **390** |

### Justification (Option B: 10 trials per probe)

With 10 trials per probe and 12 adversarial probes:
- If true FN rate = 30%: expected ~36 FNs out of 120 trials. 95% Wilson CI: [22%, 40%]. Width = 18pp. Adequate for distinguishing "low" (<10%) from "high" (>30%).
- If true FN rate = 50%: expected ~60 FNs. 95% CI: [41%, 59%]. Width = 18pp.
- If true FN rate = 10%: expected ~12 FNs. 95% CI: [5%, 17%]. Width = 12pp. Sufficient to rule out >30%.

For realistic probes (18 × 10 = 180 trials): tighter CIs. If FN rate = 30%: 95% CI: [24%, 37%]. Width = 13pp.

### Confidence Intervals

All rates reported with 95% Wilson score intervals. Wilson intervals are preferred over normal approximation for proportions near 0 or 1.

### Consistency Metric

For each probe, report the fraction of trials that agree with the modal outcome. Low consistency (< 70%) indicates the classifier is unreliable on that input.

---

## 6. INTERPRETATION FRAMEWORK

### Decision Matrix

| FN adversarial | FN realistic | FN leakage | Conclusion |
|---------------|-------------|-----------|-----------|
| Low (<10%) | Low (<10%) | Low (<10%) | Classifier is calibrated. 99.5% mc=True rate reflects genuine LLM capability. LEG metric is valid. |
| Low (<10%) | High (>30%) | Any | Classifier detects synthetic errors but fails on real model outputs. The adversarial probes are too easy. LEG metric is unreliable in practice. |
| High (>30%) | High (>30%) | Low (<10%) | Classifier has poor mechanism detection but doesn't cheat via code. LEG metric is compromised — mc=True is inflated. |
| High (>30%) | High (>30%) | High (>30%) | Classifier is broken — evaluating code correctness, not reasoning. LEG metric is uninterpretable. Fundamental redesign needed. |
| Any | Low (<10%) | High (>30%) | Classifier works correctly on reasoning but cheats when code is correct. LEG is valid for failing code but lucky fix rate is unreliable. |
| High (>30%) | Low (<10%) | Any | Adversarial probes are unrealistically wrong. Real model errors are subtle enough for the classifier. LEG metric is valid for the in-distribution case. |

### Per-Dimension Conclusions

If mechanism_identified FN is low but reasoning_code_alignment FN is high:
- The classifier catches wrong mechanisms but not wrong implementations
- LEG metric (based on mechanism_identified) is valid
- Alignment-based metrics need recalibration

If mechanism_identified FN is high but commitments_satisfied FN is low:
- The classifier catches wrong code but not wrong reasoning
- Evidence of code-outcome leakage into commitment evaluation

---

## 7. IMPLEMENTATION

### Script: `scripts/run_classifier_probes.py`

**Pipeline integrity**: All probes go through the EXACT same pipeline as production:

```
build_classifier_v2_vars(artifact, case, code, config)
    → assembly_engine.build(["classify_reasoning_v2"], vars)
    → call_model(prompt, model="gpt-5-mini", ...)
    → parse_classifier_v2_output(response)
```

No shortcuts. Full prompt and full response logged per trial.

**Structure**:

1. **Probe definitions** — a list of dicts, each containing:
   - probe_id, probe_type (A-G), case_id
   - fabricated root_cause, fix_strategy
   - code (either fabricated, reference fix, or original buggy)
   - expected_mechanism (CORRECT / WRONG / not-CORRECT)
   - source (hand-crafted / log-extracted)
   - worker_path (for Type F/G: path to original log data)

2. **Runner** — for each probe × trial:
   - Build a NormalizedReasoningArtifactV2 from the probe's root_cause/fix_strategy
   - Build case dict with code_files_contents
   - Call build_classifier_v2_vars
   - Render prompt via assembly_engine.build
   - Call gpt-5-mini via call_model
   - Parse via parse_classifier_v2_output
   - Log: probe_id, trial, full prompt, full response, all 4 dimensions, confidence, judgment text

3. **Analysis** — after all trials:
   - Compute per-probe: modal dimension values, consistency rate
   - Compute per-type: FN rate, detection rate, per-dimension accuracy
   - Compute confidence calibration: overconfidence rate
   - Compute Wilson 95% CIs for all rates
   - Output: structured results table + interpretation

**Output files**:
- `audits/classifier_probe_results.json` — raw per-trial results
- `audits/classifier_probe_analysis.md` — formatted analysis with metrics, CIs, interpretation

### Logging

Per trial, log to JSON:
```json
{
  "probe_id": "A-01",
  "probe_type": "A",
  "case_id": "stale_cache_a",
  "trial": 1,
  "expected_mechanism": "WRONG",
  "prompt_hash": "sha256:...",
  "prompt_length": 8234,
  "response_raw": "CORRECT;CORRECT;...",
  "mechanism_identified": "CORRECT",
  "commitments_extracted": "CORRECT",
  "commitments_satisfied": "CORRECT",
  "reasoning_code_alignment": "CORRECT",
  "confidence": "HIGH",
  "judgment": "...",
  "false_negative": true,
  "latency_ms": 1234
}
```

Full prompts stored separately to keep the results file manageable.

### Cost Estimate

390 calls × ~8K input tokens × $0.40/1M = ~$1.25 input
390 calls × ~500 output tokens × $1.60/1M = ~$0.31 output
**Total: ~$1.56**

### Runtime Estimate

390 calls × ~3s average = ~20 minutes serial. Can parallelize to ~5 minutes with 4 workers.

---

## 8. FILES

| File | Action |
|------|--------|
| `scripts/run_classifier_probes.py` | CREATE — probe runner + analysis |
| `audits/classifier_probe_results.json` | CREATE (output) — raw results |
| `audits/classifier_probe_analysis.md` | CREATE (output) — formatted analysis |
| `audits/type_f_probe_candidates.md` | EXISTS — Type F probe source data |

**No modifications** to any existing production file.

## 9. CONSTRAINTS

- Uses existing call_model, parse_classifier_v2_output, assembly_engine.build, build_classifier_v2_vars
- Temperature=0, model=gpt-5-mini (same as production classifier)
- Max 50 lines per function, max 300 lines per file (will split into probe_definitions.py + runner)
- No new dependencies
- Serial execution (no threads)
- Every network call has explicit timeout
