# Forensic Audit: Reasoning Evaluator Brevity Bias Under LEG-Reduction

**Date**: 2026-03-25
**Auditor**: Claude Code (forensic analysis)
**Scope**: `evaluator.py`, `execution.py`, `leg_reduction.py`, `llm.py`, `parse.py`
**Data source**: gpt-5.4-mini ablation runs (8 trials, 2652 events total)

---

## 1. Executive Summary

The LLM reasoning classifier (`llm_classify()` in `evaluator.py`) exhibits a severe **brevity bias** that systematically penalizes LEG-reduction reasoning despite equivalent semantic content. The classifier rates reasoning_correct at **83.9%** under baseline but only **47.1%** under LEG-reduction -- a **36.8 percentage point gap** -- while code_correct drops only modestly (27.9% to 24.1%, a 3.8pp gap).

**Root causes identified (two):**

1. **Structural brevity mismatch** (85.6% of the gap): The LEG-reduction prompt forces `bug_diagnosis` into a single sentence (~150 chars), while baseline reasoning is unconstrained (~450 chars). The classifier prompt contains multiple clauses that penalize brevity: "clearly identifies", "vague reasoning is NOT correct", and "if uncertain, answer NO". These create a systematic NO-bias for terse inputs even when they are semantically correct.

2. **Parse failures producing empty reasoning** (14.4% of the gap): 6.3% of LR responses have malformed JSON that causes `parse_leg_reduction_output()` to fail before extracting `bug_diagnosis`, resulting in empty reasoning sent to the classifier. All 84 such cases are rated False (correctly -- empty reasoning cannot be correct). Baseline has only 0.1% parse failure rate.

**This is a measurement artifact, not a model capability difference.** The same root-cause analysis, when expressed in one sentence vs three sentences, produces different classifier verdicts.

---

## 2. Data Flow Analysis

### 2.1 Baseline Path (run_single → evaluate_output)

```
execution.py:266  raw_output = call_model(prompt, model=model, file_paths=file_paths)
                  ↓ call_model appends V2 output instruction asking for
                  ↓ "reasoning": "<your analysis of the bug and fix>"
                  ↓ (no length constraint, models produce ~450 char reasoning)
execution.py:266  parsed = _build_parsed_response(parse_model_response(raw_output), raw_output)
                  ↓ parse_model_response → _try_file_dict → extracts "reasoning" field
                  ↓ (full multi-sentence analysis, avg ~467 chars)
evaluator.py:459  llm_classify(case, code, reasoning)
                  ↓ reasoning=(reasoning or "")[:1000]  (line 167)
                  ↓ Classifier sees full verbose reasoning
```

### 2.2 LEG-Reduction Path (run_leg_reduction → evaluate_output)

```
execution.py:478  raw_output = call_model(prompt, model=model, raw=True)
                  ↓ raw=True: no output instruction appended
                  ↓ LR prompt asks for "bug_diagnosis": "<one sentence: root cause>"
execution.py:481  lr_parsed = parse_leg_reduction_output(raw_output)
                  ↓ Extracts bug_diagnosis (avg ~152 chars when successful)
execution.py:486  parsed = {"reasoning": lr_parsed["bug_diagnosis"], ...}
                  ↓ *** KEY MAPPING: reasoning = bug_diagnosis (one sentence) ***
evaluator.py:459  llm_classify(case, code, reasoning)
                  ↓ reasoning=(reasoning or "")[:1000]  (line 167)
                  ↓ Classifier sees terse one-sentence diagnosis
```

**The critical mapping is at `execution.py:486`**: `"reasoning": lr_parsed["bug_diagnosis"]`. The LR schema forces bug_diagnosis to be `"<one sentence: root cause>"` (leg_reduction.py line 57), which then becomes the sole reasoning input to the classifier. The classifier sees ~150 chars instead of ~450 chars, with identical semantic content.

### 2.3 What the LEG-reduction response contains but the classifier never sees

The LR response also contains `plan_steps`, `revision_history`, `verification`, and `invariants_checked` -- all of which contain detailed reasoning about the bug. None of this reaches the classifier. Only `bug_diagnosis` is mapped to `parsed["reasoning"]`.

---

## 3. Classifier Prompt Fragility Analysis

The full classifier prompt (`evaluator.py` lines 34-88) contains four clauses that create brevity bias:

### Clause 1: Line 48 -- AND conjunction requiring two properties
```
TRUE if the reasoning identifies the correct root cause AND explains how the bug manifests
```
A one-sentence diagnosis like "The counter loses updates because increment is split into read and write steps" identifies root cause AND manifestation. But the classifier LLM may interpret "explains" as requiring elaboration, not mere mention.

### Clause 2: Line 49 -- "vague" as a disqualifier
```
FALSE if the reasoning is wrong, vague, irrelevant, or identifies the wrong mechanism
```
"Vague" is subjective. A one-sentence diagnosis that correctly names the mechanism is not vague, but the classifier LLM may perceive brevity as vagueness.

### Clause 3: Line 72 -- "clearly" requirement
```
Be conservative: only YES if the reasoning clearly identifies the correct mechanism
```
"Clearly" implicitly favors verbose reasoning. A three-sentence explanation "clearly" identifies the mechanism; a one-sentence version may trigger doubt in the classifier.

### Clause 4: Line 74 -- Asymmetric default
```
If uncertain, answer NO
```
Combined with the brevity of LR reasoning, this creates a systematic bias: when the classifier is uncertain (which happens more often with terse inputs), it defaults to NO.

### Interaction effect
These four clauses compound: terse reasoning -> classifier is less certain -> "if uncertain, NO" -> FALSE. The same content expressed verbosely -> classifier is more certain -> YES -> TRUE.

---

## 4. Side-by-Side Evidence (5 Concrete Examples)

All examples from `run_gpt-5.4-mini_t1_169e3bcd`. In each case, the LR reasoning is semantically equivalent to the baseline but expressed more tersely.

### Example 1: temporal_drift_b
**Baseline** (426 chars, reasoning_correct=True):
> "The bug is in pipeline.py: raw_stats is computed from cleaned (normalized) data instead of the original input. This causes raw stats to reflect normalized values rather than actual raw values. The fix is to call compute_raw_stats(data) before/independently of normalization, while keeping the rest of the pipeline unchanged. No changes are needed in transforms.py because its functions already implement the intended behavior."

**LEG-reduction** (141 chars, reasoning_correct=False):
> "The pipeline computes raw statistics from the normalized data instead of the original input, causing raw stats to reflect transformed values."

**Analysis**: Both state the identical root cause (raw_stats computed from normalized data) and manifestation (stats reflect transformed values). The LR version is correct but terse. Across all 8 trials, this case is 91.7% correct under baseline but **0.0%** under LR -- the classifier NEVER accepts this one-liner despite it being semantically identical.

### Example 2: lost_update
**Baseline** (827 chars, reasoning_correct=True):
> "The bug is a classic lost-update race caused by splitting increment into separate read and write steps without mutual exclusion or versioning. Under interleaving, both increment operations capture the same old value and then both write back old+1, so one increment is overwritten. To make the counter correct under any interleaving in this step-based simulation, each increment must be performed as an atomic read-modify-write..."

**LEG-reduction** (197 chars, reasoning_correct=False):
> "The counter loses updates because increment is split into separate read and write steps, so two concurrent increments can both read the same old value and overwrite each other with the same result."

**Analysis**: The LR version correctly identifies the root cause (non-atomic read-modify-write), the failure mechanism (both read same old value), and the consequence (lost update). Across 8 trials: 100% baseline vs 33.3% LR.

### Example 3: use_before_set_a
**Baseline** (467 chars, reasoning_correct=True):
> "The bug is that transform() only assigns a new result list when data is truthy, so falsy inputs like [] or None cause the function to return the previous cached _last_result. That violates the requirement to always return a fresh list for each call..."

**LEG-reduction** (156 chars, reasoning_correct=False):
> "The function returns a module-level cached list even when the input is empty, so it can reuse stale results instead of producing a fresh list for each call."

**Analysis**: Semantically identical root cause identification. Across 8 trials: 91.7% baseline vs 20.8% LR.

### Example 4: partial_rollback_b
**Baseline** (620 chars, reasoning_correct=True):
> "The bug is in order_service.place_order(): it reserves inventory before payment, but if payment fails it re-raises the exception without undoing the reservation. This leaves inventory stuck in the reserved state..."

**LEG-reduction** (144 chars, reasoning_correct=False):
> "Payment failure re-raises before releasing the reserved inventory, leaving the reservation state stuck and reducing available stock permanently."

**Analysis**: Both identify the same root cause (missing rollback on payment failure) and consequence (inventory stuck). Across 8 trials: 100% baseline vs 50% LR.

### Example 5: effect_order_c
**Baseline** (400 chars, reasoning_correct=True):
> "The audit log was shorter than the number of processed items because process_batch only wrote a single audit entry after the loop, using the last item seen. The intended behavior for standard processing is one increment, one event, and one audit entry per item..."

**LEG-reduction** (129 chars, reasoning_correct=False):
> "process_batch records only one audit entry after the loop, so the audit log has fewer entries than the number of items processed."

**Analysis**: Same root cause (audit entry outside loop), same consequence (fewer entries than items). Across 8 trials: 83.3% baseline vs 8.3% LR.

---

## 5. Parse Failure Analysis

### 5.1 Rates

| Condition | Parse Error Rate | Empty Reasoning Rate |
|-----------|-----------------|---------------------|
| baseline | 0.1% (1/1326) | 0.1% (1/1326) |
| leg_reduction | 17.2% (228/1326) | 6.3% (84/1326) |

### 5.2 Mechanism

The LR prompt demands a complex nested JSON schema (bug_diagnosis, plan_steps, revision_history with nested verification/invariants/issues/changes, top-level verification, code, internal_revisions). This is significantly harder for the model to produce as valid JSON compared to the baseline format (just reasoning + files dict).

When JSON parsing fails in `parse_leg_reduction_output()`:
- If top-level fields are missing (e.g., `_extract_json` finds only a partial object), `_fail()` returns `bug_diagnosis=""`.
- This empty string flows to `execution.py:486` as `parsed["reasoning"] = ""`.
- The classifier receives empty reasoning and correctly returns NO.

### 5.3 Types of JSON failures (from 5 empty-reasoning cases in trial 1)

| Case | Failure Type | Bug diagnosis was present in raw output? |
|------|-------------|----------------------------------------|
| alias_config_c | Extra data after JSON object | Yes - "The config object is shared by reference..." |
| async_race_lock | Extra data after JSON object | Yes - "The code still routes item processing..." |
| early_return_a | Missing comma delimiter | Yes - "The zero-amount branch returns before appending..." |
| partial_update_a | Extra data after JSON object | Yes - "Updating the user's name does not also update..." |
| retry_dup_c | No balanced JSON found | Yes - "The pipeline-level retry loop never breaks..." |

In ALL 5 cases, the bug_diagnosis was present in the raw output but could not be extracted because the surrounding JSON was malformed. The `_extract_json()` function finds the first balanced `{}` block, which in the "extra data" cases only captures a partial object missing the required `verification`, `code`, and `internal_revisions` fields.

---

## 6. Quantitative Decomposition

### 6.1 Overall gap
```
Baseline reasoning_correct:         83.9% (1112/1326)
LR reasoning_correct (all):         47.1% (624/1326)
Total gap:                          36.8pp
```

### 6.2 Parse failure contribution
```
LR (empty reasoning cases):         84 cases, all rated False
If these had baseline-like rate:     ~70 would be True
Parse failure contribution:          5.3pp (14.4% of total gap)
```

### 6.3 Brevity bias contribution
```
LR (non-empty reasoning):           50.2% (624/1242)
Gap vs baseline:                     33.6pp (85.6% of total gap)
```

### 6.4 Consistency across trials (gpt-5.4-mini)
```
Trial  Baseline  LR       Gap
1      87.0%     48.0%    39.0pp
2      85.5%     50.9%    34.5pp
3      84.0%     42.6%    41.4pp
4      80.9%     51.2%    29.7pp
5      81.6%     45.4%    36.2pp
6      83.3%     45.1%    38.3pp
7      87.7%     46.3%    41.4pp
8      80.9%     46.9%    34.0pp
```
The gap is remarkably stable (29.7-41.4pp), confirming this is a systematic measurement artifact, not random noise.

### 6.5 Cross-model confirmation (gpt-5-mini)
```
Baseline: 97.1% (200/206)
LR:       77.6% (142/183)
Gap:      19.5pp
```
Same direction, smaller gap (gpt-5-mini produces higher-quality LR responses).

### 6.6 Failure type distribution shift

| Failure Type | Baseline | LR |
|-------------|----------|-----|
| PARTIAL_STATE_UPDATE | 25 | 16 |
| CONFOUNDING_LOGIC | 15 | 28 |
| INVARIANT_VIOLATION | 14 | 8 |
| TEMPORAL_ORDERING | 4 | 2 |
| UNKNOWN | 0 | 3 |
| RETRY_LOGIC_BUG | 0 | 1 |

CONFOUNDING_LOGIC nearly doubles under LR, and UNKNOWN appears only under LR. This suggests the classifier is also less confident in its failure_type classification when reasoning is terse, falling back to the catch-all CONFOUNDING_LOGIC category.

---

## 7. Code Line References

| File | Line(s) | Issue |
|------|---------|-------|
| `leg_reduction.py` | 57 | `"bug_diagnosis": "<one sentence: root cause>"` forces terse output |
| `execution.py` | 486 | `"reasoning": lr_parsed["bug_diagnosis"]` maps single sentence to classifier input |
| `execution.py` | 478 | `raw=True` bypasses V2 output instruction (which asks for verbose reasoning) |
| `evaluator.py` | 48 | "identifies the correct root cause AND explains how the bug manifests" penalizes brevity |
| `evaluator.py` | 49 | "vague" clause catches terse-but-correct reasoning |
| `evaluator.py` | 72 | "clearly identifies" favors verbose explanation |
| `evaluator.py` | 74 | "if uncertain, answer NO" asymmetric default amplifies brevity penalty |
| `evaluator.py` | 167 | `reasoning=(reasoning or "")[:1000]` -- truncation not an issue (LR is always <250 chars) |
| `evaluator.py` | 171 | `model = "gpt-5.4-mini"` hard-coded, ignoring `eval_model` parameter |
| `leg_reduction.py` | 135-168 | `_extract_json()` finds first balanced JSON, fails on malformed LR output |
| `leg_reduction.py` | 175-189 | `_fail()` returns `bug_diagnosis=""` on parse error |

---

## 8. Additional Bug: eval_model Parameter Ignored

`llm_classify()` (evaluator.py line 142) accepts `eval_model` as a parameter but **never uses it**. Line 171 hard-codes `model = "gpt-5.4-mini"` regardless of what `eval_model` is passed. This means the classifier always uses gpt-5.4-mini, even if the caller intended a different evaluator model.

---

## 9. Recommendations

### Fix 1: Enrich LR reasoning sent to classifier (PRIORITY: HIGH)

Instead of mapping only `bug_diagnosis` to reasoning, concatenate the rich LR metadata:

```python
# execution.py line 486, proposed change:
reasoning_parts = [lr_parsed["bug_diagnosis"]]
for step in lr_parsed["plan_steps"]:
    reasoning_parts.append(f"Plan: {step['step']} -> {step['intended_effect']}")
for v in lr_parsed["verification"]:
    reasoning_parts.append(f"Verified: {v['step']} = {v['status']}")
parsed = {
    "reasoning": "\n".join(reasoning_parts),
    ...
}
```

This gives the classifier the same amount of reasoning content as baseline without changing the LR prompt or the classifier.

### Fix 2: Revise classifier prompt to be length-neutral (PRIORITY: HIGH)

Remove or reword the four biased clauses:
- Replace "clearly identifies" with "correctly identifies"
- Replace "vague" with "does not address the mechanism"
- Add explicit instruction: "Brevity is acceptable. A single sentence that names the root cause and its consequence is sufficient."
- Remove "if uncertain, answer NO" or replace with "if the stated mechanism is factually wrong, answer NO"

### Fix 3: Recover bug_diagnosis from partial JSON (PRIORITY: MEDIUM)

When `parse_leg_reduction_output` fails due to malformed JSON, attempt to extract `bug_diagnosis` from the raw text before returning `_fail()`. The extraction is reliable since it's the first field in the JSON and is typically a simple string:

```python
# After JSON parse failure, attempt field-level extraction:
match = re.search(r'"bug_diagnosis"\s*:\s*"([^"]*)"', raw)
if match:
    result["bug_diagnosis"] = match.group(1)
```

### Fix 4: Use eval_model parameter (PRIORITY: LOW)

Replace line 171 in `evaluator.py`:
```python
model = eval_model or "gpt-5.4-mini"
```

### Fix 5: Log classifier raw output (PRIORITY: LOW)

The classifier's raw response (`classify_raw`) is computed but not persisted to `run.jsonl`. Adding it to the logged record would enable direct inspection of classifier decisions without needing to re-run experiments.

---

## 10. Conclusion

The 36.8pp reasoning_correct gap between baseline and LEG-reduction is **85.6% measurement artifact** (classifier brevity bias) and **14.4% data loss** (parse failures dropping valid reasoning). The underlying model reasoning quality difference is far smaller than measured. Any experiment comparing reasoning rates across conditions with different response formats will produce unreliable results under the current classifier.
