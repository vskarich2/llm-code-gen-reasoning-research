# Fix Plan: Reasoning Evaluator — Brevity Bias, Parse Failures, Evaluation Non-Invariance

**Version:** v1
**Date:** 2026-03-25
**Status:** Plan only. No code changes.
**Scope:** evaluator.py, execution.py, parse.py, leg_reduction.py, retry_harness.py

---

## 1. Problem Definition

### 1.1 Brevity Bias (Causal Mechanism)

The LLM reasoning classifier (`evaluator.py:llm_classify`) receives a `reasoning` field that varies dramatically in format and length across conditions:

- **Baseline conditions**: `reasoning` is the model's freeform paragraph(s). Typically 200-800 characters. Contains rich causal explanation, mechanism identification, and fix rationale.
- **LEG-reduction condition**: `reasoning` is mapped to `lr_parsed["bug_diagnosis"]` — a SINGLE SENTENCE (execution.py:486). The full reasoning is distributed across `plan_steps`, `revision_history[].verification`, `revision_history[].issues_found`, and `revision_history[].invariants_checked`. None of this reaches the classifier.
- **Retry harness conditions**: `reasoning` is the "reasoning" JSON field from `parse_structured_output()`, which requires a strict schema. If parsing fails (non-trivial rate), `reasoning_k` falls back to whatever the lenient `parse_model_response()` extracts — which may be empty, truncated, or the wrong field entirely.

The classifier prompt says: "Be conservative: only YES if the reasoning clearly identifies the correct mechanism." A one-sentence `bug_diagnosis` like "The bug is caused by shared mutable state in DEFAULTS" is structurally penalized relative to a baseline reasoning paragraph that walks through the mechanism step by step — even when both identify the SAME mechanism correctly.

This is not a model capability difference. It is a **measurement artifact**: the same model's understanding is evaluated against different amounts of evidence depending on the output format.

### 1.2 Parse Failure Impact

Parse failures in `parse_structured_output()` (retry harness) and `parse_leg_reduction_output()` (LEG-reduction) have cascading effects:

1. **Retry harness**: If `valid_schema=False`, code falls back to `parse_model_response()` which may extract reasoning from the wrong field or return `""`. The eval_parsed dict then has `reasoning=""`. The classifier sees empty reasoning and returns `NO` — a correct classification for wrong reasons (it's classifying the parse failure, not the model's actual reasoning).

2. **LEG-reduction**: If `parse_leg_reduction_output()` fails, `lr_parsed["bug_diagnosis"]` defaults to `""`. The parsed dict (execution.py:486) then has `reasoning=""`. Same downstream corruption.

3. **Baseline/standard conditions**: `parse_model_response()` has a 7-tier fallback. The raw_fallback tier returns `reasoning=""`. Cases that hit raw_fallback have systematically different classifier input than cases that parse correctly.

In all three cases, parse failure silently converts a model that DID produce valid reasoning into a model that appears to have NO reasoning. The `parse_error` field is logged but not acted on by the classifier — the classifier still runs and produces a definitive YES/NO on empty reasoning.

### 1.3 Evaluation Non-Invariance

The same model reasoning about the same bug, expressed in two structurally different formats (baseline vs LEG), produces systematically different classifier verdicts. This violates the fundamental measurement requirement: the classifier should evaluate **semantic content**, not **format**.

Concretely:
- Baseline: `"The bug is in create_config which returns a reference to DEFAULTS. Any mutation by the caller corrupts the global state. The fix is to return dict(DEFAULTS) — a shallow copy."` → Classifier sees full mechanism → YES
- LEG: `"The bug is caused by shared mutable reference to DEFAULTS dict."` (bug_diagnosis only) → Classifier sees terse summary → NO (penalized for brevity despite correct identification)

The LEG model's `plan_steps`, `revision_history`, `verification` contain the SAME mechanistic detail, but none of it reaches the classifier.

### 1.4 Why Current Results Are Invalid

- **LEG rate for leg_reduction condition is artificially inflated**: The condition measures (code_wrong, reasoning_correct). If reasoning is systematically misclassified as incorrect due to brevity, cases that should be `true_failure` (wrong code, wrong reasoning) are correctly classified, BUT cases that should be `leg` (wrong code, correct reasoning) are misclassified as `true_failure`. The LEG rate is UNDER-counted for LEG-reduction, making the condition appear to reduce LEG when it may not.
- **Baseline-vs-condition comparisons are confounded**: Any condition-vs-baseline reasoning comparison reflects format effects, not capability effects.
- **Unclassified rate hides parse failures**: Cases where `reasoning_correct=None` (classifier parse failure OR model parse failure) are bucketed as "unclassified" and silently excluded from rates. If parse failure rates differ between conditions, the denominator changes, biasing all rates.

---

## 2. Root Cause Breakdown

### A. Brevity Bias

**Why the classifier prompt causes bias:**

The classifier prompt (`_CLASSIFY_PROMPT`) instructs: "Be conservative: only YES if the reasoning clearly identifies the correct mechanism" and "Vague reasoning ('I fixed the bug') is NOT correct reasoning." These instructions are correct for their intended purpose, but they interact pathologically with input length:

- A one-sentence `bug_diagnosis` like "shared mutable reference to DEFAULTS dict" DOES identify the correct mechanism — it names the aliasing bug precisely. But an LLM judge following "be conservative" interprets brevity as potential vagueness.
- The prompt says "identifies the correct root cause AND explains how the bug manifests." A one-sentence diagnosis may identify the root cause but not explicitly explain manifestation (callers mutate global state → subsequent calls see corrupted config). The explanation IS present in `plan_steps` and `revision_history`, but those are never passed.

**Why LEG format triggers it:**

The LEG-reduction schema was designed for a DIFFERENT purpose: auditable self-correction. It distributes reasoning across structured fields:

```
bug_diagnosis:    "shared mutable reference"     ← only this reaches classifier
plan_steps:       ["return copy", "verify callers"]  ← discarded
revision_history: [verification, invariants, issues]  ← discarded
```

execution.py:486 maps ONLY `bug_diagnosis` to `reasoning`. This was a conscious design choice (keep the interface simple), but it creates an information bottleneck.

The truncation at evaluator.py:167 `(reasoning or "")[:1000]` is not the primary issue — most baseline reasoning is under 1000 chars. The issue is that for LEG, the reasoning IS 20-50 chars (one sentence), and the rest of the mechanistic detail is in other fields that are never concatenated.

### B. Parse Failures

**Where failures occur:**

1. `parse_structured_output()` (parse.py:356): Requires `reasoning`, `plan`, `code` keys with correct types. Failures:
   - `extraction_error: NO_JSON_OBJECT_FOUND` — model returned non-JSON
   - `extraction_error: UNBALANCED_JSON` — model returned malformed JSON
   - `missing_key: plan` — model omitted plan field
   - `plan_not_list` — model used string instead of list

2. `parse_leg_reduction_output()` (leg_reduction.py): Requires full revision trace schema. Many more failure modes:
   - Missing `revision_history` array
   - Missing nested verification/invariants arrays
   - Invalid status values ("pass" instead of "PASS")

3. `parse_model_response()` fallback chain (parse.py:224): The raw_fallback tier (tier 4) sets `reasoning=""` and `code=raw.strip()` — meaning the entire response becomes "code" and reasoning is lost.

**How they corrupt reasoning input:**

The corruption path is:

```
parse failure → reasoning="" → classifier receives empty reasoning
→ classifier correctly says "NO" (empty reasoning is not correct reasoning)
→ result logged as reasoning_correct=False
→ BUT this is a measurement failure, not a model capability result
```

The `parse_error` field IS set and IS logged in the eval result. But:
- The classifier runs anyway (no gate on parse errors)
- No downstream analysis distinguishes "reasoning_correct=False because model's reasoning was wrong" from "reasoning_correct=False because reasoning was lost in parsing"

### C. Information Loss

**What reasoning is discarded:**

For LEG-reduction (`execution.py:484-490`):
- `plan_steps`: List of `{step, intended_effect}` — contains the fix strategy
- `revision_history[].verification`: Per-step pass/fail with evidence — contains mechanistic validation
- `revision_history[].invariants_checked`: Invariant analysis with evidence — contains invariant identification
- `revision_history[].issues_found`: Issue descriptions with evidence — contains failure mechanism identification
- `revision_history[].changes_made`: Change descriptions — contains fix rationale

For retry harness (`retry_harness.py:1061-1077`):
- `plan` (list of plan steps) — parsed but not included in eval_parsed["reasoning"]
- Previous iteration reasoning (trajectory context) — only current iteration's reasoning reaches classifier

**Why this matters:**

The T3 benchmark's core metric is the 2x2 alignment matrix. The reasoning axis (correct/incorrect) is the ONLY dimension that distinguishes LEG from true_failure, and true_success from lucky_fix. If reasoning classification is biased by format, ALL four categories are contaminated, and the benchmark's primary finding — the existence and prevalence of LEG — cannot be trusted for conditions that use non-baseline output formats.

---

## 3. Design Goals (NON-NEGOTIABLE)

1. **Format invariance**: The classifier must produce the same verdict for the same semantic content regardless of whether it arrives as a single `reasoning` string, a structured `{bug_diagnosis, plan_steps, verification}` object, or a `{reasoning, plan, code}` triple. If a model correctly identifies the bug mechanism, the verdict must be YES regardless of output structure.

2. **Semantic correctness over verbosity**: A concise, correct identification ("shared mutable reference causes aliasing") must score the same as a verbose correct identification. The classifier must evaluate what was said, not how much was said.

3. **Robustness to malformed outputs**: Parse failures must not silently produce `reasoning_correct=False`. If reasoning cannot be extracted, the result must be `reasoning_correct=None` (unclassified) with an explicit reason, NOT a false negative.

4. **Zero silent failure**: Every case where reasoning cannot be evaluated must be explicitly flagged in the output with a machine-readable reason. No case should appear in the classified denominator if its reasoning input was corrupted or missing.

5. **Backward compatibility**: Existing baseline results must not change. The fix must only affect cases where reasoning was previously discarded or misrepresented.

---

## 4. Proposed Fixes

### Fix Option A: Enriched Reasoning Input

**Mechanism**: Before calling `llm_classify`, concatenate ALL reasoning-bearing fields into a single `enriched_reasoning` string. For LEG-reduction: `bug_diagnosis + plan_steps + verification + issues_found`. For retry harness: `reasoning + plan`. For baseline: pass-through (no change).

**How it works**:
1. Define a `build_enriched_reasoning(parsed: dict, condition: str) -> str` function.
2. For standard conditions: return `parsed["reasoning"]` (no change).
3. For LEG-reduction: concatenate structured fields:
   ```
   Bug Diagnosis: {bug_diagnosis}
   Plan: {step1.step}: {step1.intended_effect} ...
   Issues Found: {issue1.description}: {issue1.evidence} ...
   Invariants: {inv1.invariant}: {inv1.status} — {inv1.evidence} ...
   ```
4. For retry harness: concatenate `reasoning + plan`:
   ```
   {reasoning}
   Plan: {plan[0]}, {plan[1]}, ...
   ```
5. Pass `enriched_reasoning` to `llm_classify` instead of raw `reasoning`.

**Pros**:
- Non-invasive: only changes the input to `llm_classify`, not the classifier itself.
- Backward-compatible: baseline path is unchanged.
- Preserves all existing classifier behavior — just gives it more evidence.
- Easy to test: compare classifications with and without enrichment.

**Cons**:
- Increases input length for LEG/retry conditions, which could hit the 1000-char truncation limit in `llm_classify`. Must increase or remove the limit.
- The concatenation format itself could introduce classifier artifacts (does the classifier respond differently to "Bug Diagnosis:" headers vs free text?).
- Does not fix the classifier's intrinsic conservatism toward short reasoning.

**Failure risks**:
- If the concatenated format is unfamiliar to the classifier model, it might classify WORSE than before.
- Long enriched reasoning could cause the classifier to over-weight irrelevant detail.

---

### Fix Option B: Classifier Prompt Redesign

**Mechanism**: Rewrite `_CLASSIFY_PROMPT` to explicitly handle structured reasoning and to evaluate semantic correctness regardless of length.

**Changes to the prompt**:
1. Add explicit instruction: "Reasoning may be presented as a single diagnosis, a structured plan, or a detailed revision trace. Evaluate the CONTENT, not the format or length."
2. Add instruction: "A correct one-sentence identification of the root cause IS correct reasoning, even without elaboration."
3. Remove or weaken "Be conservative: only YES if the reasoning CLEARLY identifies..." — replace with "YES if the reasoning identifies the correct root cause, even if briefly stated."
4. Add examples of short-but-correct reasoning:
   ```
   Example: "The bug is aliasing — create_config returns DEFAULTS by reference" → YES
   ```

**Pros**:
- Addresses the root cause: the classifier's conservatism toward brevity.
- Works regardless of input format.
- No changes to data flow or pipeline structure.

**Cons**:
- Prompt changes affect ALL conditions, including baseline. This could change baseline results, breaking backward compatibility.
- Relaxing conservatism could increase false positives (vague reasoning incorrectly classified as correct).
- Hard to calibrate: how "relaxed" is enough without being too permissive?
- Requires re-running all experiments to establish new baselines.

**Failure risks**:
- Could flip the bias: instead of penalizing brevity, the new prompt might reward vague short statements like "I fixed the ordering" (which is NOT correct reasoning).
- Any prompt change is a fundamental measurement change. All prior results become incomparable.

---

### Fix Option C: Dual-Format Evaluation

**Mechanism**: Run the classifier TWICE for conditions with structured output: once on raw reasoning (as today), once on enriched reasoning. Report both. Use the enriched result as primary.

**How it works**:
1. For each case, produce `reasoning_raw` (current behavior) and `reasoning_enriched` (from Option A).
2. Call `llm_classify()` twice.
3. Store both results: `reasoning_correct_raw`, `reasoning_correct_enriched`.
4. Use `reasoning_correct_enriched` for primary metrics.
5. Log the disagreement: cases where raw=NO but enriched=YES are the EXACT cases affected by brevity bias.

**Pros**:
- Provides direct measurement of the bias (disagreement count IS the bias magnitude).
- No backward compatibility break (raw results still available).
- Can be validated empirically: if enriched flips NO→YES, does the reasoning actually deserve YES?
- Publication-ready: "We observed N% disagreement between raw and enriched classification, indicating format-dependent evaluation."

**Cons**:
- Doubles classifier API calls for LEG/retry conditions (cost).
- Adds complexity to the evaluation pipeline.
- If both are wrong in different ways, which do you trust?

**Failure risks**:
- Enriched classifier could be wrong in new ways (over-counting).
- Two "truths" in the system creates confusion about which number is real.

---

### Fix Option D: Parse Recovery Layer

**Mechanism**: Add a pre-classifier gate that prevents evaluation on corrupt reasoning input, and a recovery layer that attempts to extract reasoning from raw output when structured parsing fails.

**How it works**:
1. **Gate**: If `reasoning` is empty/None AND `parse_error` is set, DO NOT run the classifier. Set `reasoning_correct=None` with `classify_parse_error="reasoning_lost_in_parse"`.
2. **Recovery for retry harness**: If `parse_structured_output()` fails, attempt to extract reasoning from raw output using a targeted regex: find "reasoning" key in malformed JSON, or find explanatory text before code blocks.
3. **Recovery for LEG-reduction**: If `parse_leg_reduction_output()` fails, attempt to extract `bug_diagnosis` from malformed JSON using targeted regex.
4. **Never produce reasoning_correct=False from empty reasoning**.

**Pros**:
- Eliminates the worst failure mode: empty reasoning being classified as incorrect.
- Recovery layer salvages genuine reasoning from malformed output.
- Gate ensures clean measurement: unclassified cases are explicitly separated from false negatives.

**Cons**:
- Does not fix brevity bias for LEG-reduction (bug_diagnosis is still short even when parsing succeeds).
- Recovery layer adds fragile regex parsing that may itself be wrong.
- Gate increases unclassified rate, reducing sample size.

**Failure risks**:
- Recovery regex could extract wrong text as "reasoning".
- Higher unclassified rate could hide real condition effects.

---

## 5. Chosen Approach

### Primary: Option A (Enriched Reasoning Input) + Option D (Parse Recovery Layer)

### Justification

**Option A** fixes the core information loss problem. LEG-reduction's mechanistic reasoning IS present in the model output — it's just in structured fields that never reach the classifier. Enrichment is a data-plumbing fix, not a measurement change. The classifier sees the same kind of content (mechanistic reasoning text), just more of it. This preserves the classifier's calibration.

**Option D** fixes the parse failure corruption problem. Empty reasoning should never produce a definitive `reasoning_correct=False`. The gate is a correctness fix, not an opinion change.

**Why NOT Option B**: Changing the classifier prompt changes the measurement instrument. All prior results become incomparable. This is a last resort, not a first fix.

**Why NOT Option C as primary**: The dual evaluation is valuable for validation but too expensive for production. It will be used in the validation phase (Section 6), not in the production fix.

### Combined Design

```
1. Parse model output (existing pipeline, no change)
2. NEW: Build enriched_reasoning from all available fields
3. NEW: Gate — if enriched_reasoning is empty AND parse_error is set, skip classifier
4. Call llm_classify with enriched_reasoning
5. Existing downstream (alignment, categories, etc.)
```

### Enrichment Logic (exact specification)

```
def build_enriched_reasoning(parsed: dict, lr_parsed: dict | None = None) -> str:
    """Build enriched reasoning from all available fields.

    For standard conditions: returns parsed["reasoning"] unchanged.
    For LEG-reduction: concatenates bug_diagnosis + plan_steps + issues + invariants.
    For retry harness: concatenates reasoning + plan.
    """
    parts = []

    # 1. Primary reasoning (always present)
    reasoning = parsed.get("reasoning") or ""
    if reasoning.strip():
        parts.append(reasoning.strip())

    # 2. Plan steps (from parse_structured_output or LEG)
    plan = parsed.get("plan") or []
    if plan and isinstance(plan, list):
        plan_text = "; ".join(str(s) for s in plan[:10])
        parts.append(f"Plan: {plan_text}")

    # 3. LEG-specific fields
    if lr_parsed:
        # Plan steps with intended effects
        for step in (lr_parsed.get("plan_steps") or [])[:5]:
            if isinstance(step, dict):
                parts.append(f"Step: {step.get('step', '')} -> {step.get('intended_effect', '')}")

        # Issues found (from last revision)
        revisions = lr_parsed.get("revision_history") or []
        if revisions:
            last_rev = revisions[-1] if isinstance(revisions[-1], dict) else {}
            for issue in (last_rev.get("issues_found") or [])[:3]:
                if isinstance(issue, dict):
                    parts.append(f"Issue: {issue.get('description', '')} Evidence: {issue.get('evidence', '')}")
            for inv in (last_rev.get("invariants_checked") or [])[:3]:
                if isinstance(inv, dict) and inv.get("status") == "FAIL":
                    parts.append(f"Invariant violated: {inv.get('invariant', '')} Evidence: {inv.get('evidence', '')}")

    return "\n".join(parts) if parts else ""
```

### Gate Logic (exact specification)

```
# In llm_classify, BEFORE calling the LLM:
enriched = build_enriched_reasoning(parsed, lr_parsed)
if not enriched.strip():
    if parsed.get("parse_error"):
        return {
            "reasoning_correct": None,  # NOT False
            "failure_type": None,
            "classify_raw": None,
            "classify_parse_error": f"reasoning_lost_in_parse:{parsed['parse_error']}",
        }
    # Truly empty reasoning (model produced no reasoning)
    # This IS a valid classifier input — classify as NO
```

### Truncation Limit Change

Current: `(reasoning or "")[:1000]` in llm_classify.

New: `enriched_reasoning[:2000]`. The enriched reasoning for LEG cases will be longer (500-1500 chars typically), so the limit must increase. 2000 chars is sufficient for any single-condition reasoning while staying within classifier model context limits.

---

## 6. Validation Plan

### A. Truncation Test

**Purpose**: Verify that truncated correct reasoning is not misclassified.

**Input**: Take 10 known-correct baseline reasoning strings (cases where reasoning_correct=YES in existing data). Truncate each to the first sentence only.

**Procedure**:
1. Run classifier on full reasoning → expect YES for all 10.
2. Run classifier on first-sentence-only → record results.
3. If any flip YES→NO, the classifier has brevity bias.

**Expected outcome**: At least 3/10 flip YES→NO (confirming the bias exists).

**Failure condition**: If 0/10 flip, the bias may not exist and this fix is unnecessary. Investigate further before proceeding.

### B. Format Invariance Test

**Purpose**: Verify that enriched LEG reasoning produces the same classification as semantically equivalent baseline reasoning.

**Input**: Select 10 cases where:
- Baseline reasoning_correct = YES
- LEG-reduction bug_diagnosis alone would likely produce NO (short, terse)
- LEG-reduction full structured output contains the same mechanistic detail

**Procedure**:
1. Run classifier on baseline reasoning → expect YES.
2. Run classifier on LEG bug_diagnosis only → record (expect many NO).
3. Run classifier on enriched LEG reasoning (bug_diagnosis + plan_steps + issues + invariants) → expect YES.

**Expected outcome**: Enriched LEG matches baseline verdict in >= 8/10 cases. Bug_diagnosis-only matches in <= 5/10 cases.

**Failure condition**: If enriched LEG still produces NO in > 5/10 cases, the enrichment format may be confusing the classifier. Adjust concatenation format.

### C. Parse Recovery Test

**Purpose**: Verify the gate correctly handles parse failures.

**Input**: Construct 5 parse failure scenarios:
1. Empty string reasoning, parse_error set → expect reasoning_correct=None
2. Whitespace-only reasoning, parse_error set → expect reasoning_correct=None
3. Correct reasoning, no parse_error → expect reasoning_correct=YES/NO (normal flow)
4. Empty reasoning, NO parse_error → expect reasoning_correct=NO (legitimate empty reasoning)
5. Long correct reasoning, parse_error set (contradictory) → expect reasoning_correct based on reasoning content (parse_error from non-reasoning field)

**Expected outcome**: Cases 1-2 return None. Cases 3-4 return a verdict. Case 5 returns a verdict.

**Failure condition**: If case 1 or 2 returns False instead of None, the gate is not working.

### D. Known-Good Cases

**Purpose**: Verify the enrichment does not BREAK correct classifications.

**Input**: 20 cases from existing data where reasoning_correct is confidently correct (verified by manual inspection):
- 10 where reasoning_correct = YES (correct reasoning)
- 10 where reasoning_correct = NO (genuinely wrong reasoning)

**Procedure**: Run classifier with enriched reasoning on all 20.

**Expected outcome**: All 20 maintain their original classification. Zero flips.

**Failure condition**: If ANY of the 10 YES cases flip to NO, the enrichment is HARMING correct classifications. If ANY of the 10 NO cases flip to YES, the enrichment is introducing false positives. Either failure blocks the fix.

### E. Dual-Evaluation Validation (Option C, validation only)

**Purpose**: Quantify the magnitude of brevity bias in production data.

**Input**: Full ablation run on 58 cases x {baseline, leg_reduction} conditions.

**Procedure**: Run classifier twice per LEG case: once with bug_diagnosis only, once with enriched reasoning. Compute disagreement rate.

**Expected outcome**: Disagreement rate of 10-30% (enriched flips NO→YES, indicating recovered reasoning). If < 5%, the problem is smaller than hypothesized. If > 40%, the enrichment may be over-permissive.

**Failure condition**: If enriched flips YES→NO (more conservative than raw), something is wrong with the enrichment format.

---

## 7. Metrics for Success

| Metric | Current (Estimated) | Target | How to Measure |
|---|---|---|---|
| Reasoning accuracy gap (baseline vs LEG-reduction) | 15-25% difference | <= 5% difference | Run both conditions, compare reasoning_correct rate |
| Parse failure → false negative rate | ~100% (all parse failures produce False) | 0% (all produce None) | Count cases where parse_error is set AND reasoning_correct=False |
| Classification consistency on identical reasoning | Unknown | >= 95% (same verdict on repeated runs) | Run classifier 3x on same inputs, measure agreement |
| Unclassified rate (reasoning_correct=None) | ~2% (only classifier LLM failures) | ~5-8% (includes parse failures) | Count None / total. Acceptable increase from gating parse failures. |
| Format invariance: enriched LEG vs baseline on matched cases | N/A | >= 85% agreement | Matched-case comparison as in test B |

---

## 8. Risk Analysis

### 8.1 Enrichment Introduces New Bias

**Risk**: The concatenated enriched reasoning has a distinctive format ("Bug Diagnosis: X. Plan: Y. Issue: Z.") that the classifier model may respond to differently than free-text reasoning. The classifier could learn to associate this format with correctness or incorrectness.

**Mitigation**: Test with shuffled field order and varying header labels to confirm the classifier is responding to content, not format. If format matters, remove headers and concatenate with plain newlines.

### 8.2 Overfitting to Current Benchmark

**Risk**: The enrichment logic is designed for T3's specific output schemas (LEG-reduction, retry harness). If new conditions or schemas are added, the enrichment function won't know about them, silently reverting to the old behavior.

**Mitigation**: The enrichment function MUST be the single point of reasoning extraction for ALL conditions. New conditions must add their fields to `build_enriched_reasoning()` or the code fails a preflight check. Add an assertion: if `condition` is not in the enrichment function's known conditions, raise an error.

### 8.3 Increased Unclassified Rate

**Risk**: The gate (Option D) converts parse-failure-induced `False` to `None`. This reduces the classified sample size. If parse failure rates differ between conditions, the denominator change could create new biases in rate comparisons.

**Mitigation**: Report unclassified rate per condition alongside all metrics. If unclassified rate > 15% for any condition, investigate the parse failure root cause. The correct fix is to improve parsing, not to remove the gate.

### 8.4 Enrichment Too Permissive

**Risk**: Adding plan_steps, issues, and invariants to the classifier input gives the classifier MORE text to find keywords in. This could cause false positives: a model with wrong reasoning but correct-sounding plan steps gets classified as YES.

**Mitigation**: Validation test D (known-good NO cases) catches this. If false positive rate increases, restrict enrichment to only `bug_diagnosis` + `issues_found` (the most reasoning-dense fields), excluding plan_steps and invariants.

### 8.5 Breaking Existing Baseline Results

**Risk**: If the enrichment accidentally modifies baseline condition inputs (which should be pass-through), all baseline results change.

**Mitigation**: The enrichment function returns `parsed["reasoning"]` unchanged for standard conditions. Unit test: baseline enrichment == raw reasoning, byte-for-byte.

---

## 9. Rollout Plan

### Phase 1: Implement (estimated 2-4 hours)

1. Add `build_enriched_reasoning()` function to evaluator.py
2. Add gate logic to `llm_classify()`: skip classifier on empty reasoning + parse_error
3. Wire enrichment into execution.py:
   - `run_single()`: pass `parsed` to enrichment (no change, standard conditions use pass-through)
   - `run_leg_reduction()`: pass `lr_parsed` to enrichment so structured fields are included
   - `run_contract_gated()`: pass contract-specific fields if applicable
   - Retry harness: pass `plan` from `parse_structured_output()` to enrichment
4. Increase truncation limit from 1000 to 2000 in `llm_classify()`
5. Add `reasoning_enrichment_source` field to eval result (tracks which fields contributed)

### Phase 2: Run Validation Tests (estimated 1-2 hours)

1. Run test A (truncation test) — confirm bias exists
2. Run test C (parse recovery) — confirm gate works
3. Run test D (known-good cases) — confirm no regressions
4. Run test B (format invariance) — confirm enrichment fixes the gap

**Gate**: If test D shows ANY regression (correct classifications flipped), STOP. Debug before proceeding.

### Phase 3: Small Ablation (estimated 2-4 hours)

1. Run 10 cases x {baseline, leg_reduction, retry_no_contract} x 1 trial with the fix
2. Compare reasoning_correct rates across conditions
3. Confirm gap has narrowed per Section 7 metrics
4. Run test E (dual evaluation) on these 10 cases to quantify bias magnitude

### Phase 4: Compare Metrics (estimated 1 hour)

1. Compare Phase 3 results against existing ablation data
2. Confirm:
   - Baseline rates unchanged (within noise)
   - LEG/retry rates shifted toward baseline (gap narrowed)
   - Unclassified rate is within acceptable bounds (5-8%)
   - No new failure modes introduced

### Phase 5: Full Run (estimated 4-8 hours)

1. Run full ablation: 58 cases x all conditions x N trials
2. Regenerate all metrics and dashboards
3. Archive pre-fix results for comparison
4. Document the fix in the paper methodology section

---

## 10. Regression Protection

### New Tests (MUST be added before Phase 5)

#### 10.1 Format Invariance Tests (`tests/test_reasoning_invariance.py`)

```
test_baseline_reasoning_unchanged:
    - Input: standard parsed dict with reasoning="correct explanation"
    - Assert: build_enriched_reasoning returns the same string

test_leg_enrichment_includes_diagnosis:
    - Input: LEG parsed dict with bug_diagnosis="aliasing bug"
    - Assert: enriched output contains "aliasing bug"

test_leg_enrichment_includes_plan_steps:
    - Input: LEG parsed with plan_steps=[{step: "copy defaults", intended_effect: "prevent aliasing"}]
    - Assert: enriched output contains "copy defaults" and "prevent aliasing"

test_leg_enrichment_includes_issues:
    - Input: LEG parsed with issues_found=[{description: "shared reference", evidence: "line 5"}]
    - Assert: enriched output contains "shared reference"

test_empty_reasoning_with_parse_error_returns_none:
    - Input: parsed with reasoning="", parse_error="extraction_error"
    - Assert: llm_classify returns reasoning_correct=None

test_empty_reasoning_without_parse_error_classifies_normally:
    - Input: parsed with reasoning="", parse_error=None
    - Assert: llm_classify returns reasoning_correct=False (not None)
```

#### 10.2 Brevity Robustness Tests (`tests/test_brevity_robustness.py`)

```
test_one_sentence_correct_reasoning_classified_yes:
    - Input: reasoning="The bug is shared mutable reference to DEFAULTS dict causing aliasing"
    - Case: alias_config_a
    - Assert: reasoning_correct == True (with real classifier or known-good mock)

test_verbose_wrong_reasoning_classified_no:
    - Input: reasoning="I examined the code thoroughly and found that the issue is with
              the import statements being in the wrong order. Python requires imports to
              be at the top of the file..."  (long but wrong)
    - Assert: reasoning_correct == False
```

#### 10.3 Parse Robustness Tests (`tests/test_parse_recovery.py`)

```
test_parse_failure_does_not_produce_false:
    - For each parse failure type (empty, malformed JSON, missing key):
    - Assert: if reasoning is lost, reasoning_correct is None, not False

test_enriched_reasoning_never_empty_when_raw_has_content:
    - Input: raw output containing recognizable reasoning (in any format)
    - Assert: build_enriched_reasoning produces non-empty output

test_enrichment_source_tracked:
    - For each condition type:
    - Assert: reasoning_enrichment_source field is set and accurate
```

#### 10.4 End-to-End Regression Tests

```
test_baseline_results_unchanged_after_fix:
    - Run 5 baseline cases with mock LLM
    - Assert: results match pre-fix baseline results exactly

test_leg_results_improved_after_fix:
    - Run 5 LEG cases with mock LLM
    - Assert: reasoning_correct rate >= pre-fix rate (fix only helps, never hurts)
```
