# Critique Effect Decomposition — Plan v1

**Date**: 2026-04-01

---

## 1. Objective

We already know critique helps. The question is:

**How much of critique's gain comes from:**
1. Reasoning repair (model revises its mechanism identification after critique feedback)
2. Execution alignment (model already had correct reasoning, critique helps it implement correctly)
3. Lucky fixes / noise (model passes with wrong reasoning)

This requires decomposing critique's total pass rate gain into these three channels with exact metrics.

---

## 2. Data Inspection Results

### 2.1 Available Data

**Primary dataset**: `logs/retry_critique_stage2` — 3,000 case.end events.
- 4 conditions: baseline_v2 (750), leg_reduction_lean_v2 (750), retry_bare_retry_v2 (750), retry_leg_critique_strict_v2 (750)
- 6 models: gpt-4o-mini (1000), gpt-5.4-mini (600), claude-sonnet-4-6 (400), gpt-4.1-nano (400), gpt-5-mini (400), claude-haiku-4-5 (200)
- 10 cases, 50 trials
- All 4 conditions present for every (case, model, trial) — fully matched

**Oracle labels**: `audits/oracle_critique/oracle_labels.jsonl` — 3,000 labels covering all 4 conditions.
- Distribution: CORRECT=1261, PARTIAL=845, WRONG=836, UNJUDGABLE=58

### 2.2 Critical Schema Finding

**case.end reflects the FINAL attempt's reasoning, not the initial attempt.** Verified: for a 4-call critique worker, case.end's `raw_root_cause` matches call 3 (retry), not call 1 (initial).

**Consequence**: The oracle labels we already have for the critique condition evaluate the FINAL reasoning. They do NOT tell us what the model's reasoning was BEFORE critique. To decompose reasoning repair vs execution alignment, we need the INITIAL reasoning too.

### 2.3 Retry Metadata Available

- `retry_passed_at`: 0 (passed initial, 56 workers), 1 (passed first retry, 118), 2 (passed second retry, 34), None (never passed, 542)
- Call count per worker: 2 calls (56, no retry needed), 4 calls (158, 1 retry), 6 calls (504, 2 retries)
- `retry_mode`: present in payload, confirms condition

### 2.4 What's Missing

The initial-attempt reasoning for critique workers is NOT in case.end or merged_events.jsonl. It is ONLY in the worker call files:
- `workers/{worker}/attempt_001/calls/000001.json` → `response_raw` → parse JSON → `root_cause`, `fix_strategy`

To oracle-label the initial reasoning, we must walk worker directories and extract call 1 responses. This is feasible but requires a separate extraction + oracle labeling pass.

### 2.5 Fields Verified Present

| Field | Location | Present |
|-------|----------|---------|
| reasoning_truth (final) | oracle_labels.jsonl | YES (all 3000) |
| execution_pass | case.end payload.pass | YES |
| reconstruction_status | case.end payload.reconstruction_status | YES |
| execution_category | case.end payload.execution_category | YES |
| retry_passed_at | case.end payload.retry_passed_at | YES |
| condition | case.end event.condition | YES |
| initial reasoning | worker calls/000001.json | YES (must extract) |
| critique text | worker calls/000003.json prompt_raw | YES (must extract) |

---

## 3. Metric Specification

### 3.1 Per-Condition Metrics (computed from oracle labels + execution data)

For each condition C ∈ {baseline, lean, bare_retry, critique}:

| Metric | Definition |
|--------|-----------|
| P(CORRECT) | count(reasoning_truth=CORRECT) / count(judgable) |
| P(PARTIAL) | count(reasoning_truth=PARTIAL) / count(judgable) |
| P(WRONG) | count(reasoning_truth=WRONG) / count(judgable) |
| P(pass) | count(pass=True) / count(all) |
| P(pass \| CORRECT) | count(pass ∧ CORRECT) / count(CORRECT) |
| P(pass \| PARTIAL) | count(pass ∧ PARTIAL) / count(PARTIAL) |
| P(pass \| WRONG) | count(pass ∧ WRONG) / count(WRONG) |
| P(recon_ok) | count(reconstruction_status=SUCCESS) / count(all) |
| P(pass \| recon_ok) | count(pass ∧ recon_ok) / count(recon_ok) |

**These already exist.** They were computed when we ran the oracle critique analysis earlier. Recompute from joined data to verify.

### 3.2 Delta Metrics (critique vs baseline)

| Metric | Definition | Channel it measures |
|--------|-----------|-------------------|
| ΔP(CORRECT) | P(CORRECT\|critique) - P(CORRECT\|baseline) | Reasoning repair |
| ΔP(pass \| CORRECT) | P(pass\|C,critique) - P(pass\|C,baseline) | Execution alignment |
| ΔP(pass \| PARTIAL) | P(pass\|P,critique) - P(pass\|P,baseline) | Partial-reasoning compensation |
| ΔP(pass \| WRONG) | P(pass\|W,critique) - P(pass\|W,baseline) | Lucky fix shift |
| ΔP(pass) | P(pass\|critique) - P(pass\|baseline) | Total effect |
| ΔP(recon_ok) | P(recon_ok\|critique) - P(recon_ok\|baseline) | Reconstruction artifact |

### 3.3 Decomposition Metrics (NEW — requires initial reasoning)

These metrics require oracle-labeling the INITIAL attempt reasoning for critique workers:

| Metric | Definition |
|--------|-----------|
| reasoning_truth_initial | Oracle label of call 1 reasoning (before critique) |
| reasoning_truth_final | Oracle label of case.end reasoning (after critique) = existing labels |

**Transition matrix** (per critique worker):

| Initial → Final | Count | Pass rate |
|----------------|-------|-----------|
| CORRECT → CORRECT | | P(pass\|CC) |
| CORRECT → PARTIAL | | P(pass\|CP) |
| CORRECT → WRONG | | P(pass\|CW) |
| PARTIAL → CORRECT | | P(pass\|PC) — reasoning repair |
| PARTIAL → PARTIAL | | P(pass\|PP) |
| PARTIAL → WRONG | | P(pass\|PW) |
| WRONG → CORRECT | | P(pass\|WC) — reasoning repair |
| WRONG → PARTIAL | | P(pass\|WP) |
| WRONG → WRONG | | P(pass\|WW) |

**Channel attribution from transition matrix:**

- **Execution alignment** = P(pass | CORRECT→CORRECT, critique) - P(pass | CORRECT, baseline)
  - Same reasoning quality, different pass rate → pure execution improvement

- **Reasoning repair** = contribution from upward transitions (P→C, W→C, W→P) weighted by their pass rates
  - Model improved reasoning AND this led to passing

- **Lucky fix** = P(pass | WRONG→WRONG, critique) - P(pass | WRONG, baseline)
  - Still wrong reasoning, but passing more → noise

### 3.4 Formal Decomposition

Total critique gain:

ΔP(pass) = P(pass|critique) - P(pass|baseline)

Decompose into:

```
ΔP(pass) = Σ_{i→j} P(i→j) × P(pass|i→j,critique) - Σ_i P(i,baseline) × P(pass|i,baseline)
```

where i,j ∈ {CORRECT, PARTIAL, WRONG}.

Practically, group into three channels:

**Channel 1 — Execution alignment**: Among triples where initial reasoning is CORRECT and stays CORRECT:
```
contribution_1 = P(C→C) × [P(pass|C→C,critique) - P(pass|C,baseline)]
```

**Channel 2 — Reasoning repair**: Among triples where initial reasoning improves (P→C, W→C, W→P):
```
contribution_2 = Σ_{i<j} P(i→j) × P(pass|i→j,critique) - P(i→j) × P(pass|i,baseline)
```

**Channel 3 — Lucky fix + noise**: Among triples where reasoning stays WRONG or degrades:
```
contribution_3 = ΔP(pass) - contribution_1 - contribution_2
```

Each contribution is in percentage points. Their sum equals ΔP(pass).

---

## 4. Outcome Decomposition Tables

### Table A: Condition-Level Summary

| Condition | N | P(C) | P(P) | P(W) | P(pass) | P(pass\|C) | P(pass\|P) | P(pass\|W) | P(recon_ok) |
|-----------|---|------|------|------|---------|-----------|-----------|-----------|------------|

Already computed. Revalidate from joined data.

### Table B: Critique vs Baseline Deltas

| Metric | Baseline | Critique | Δ | 95% CI | p-value |
|--------|----------|----------|---|--------|---------|
| P(CORRECT) | | | | | |
| P(pass) | | | | | |
| P(pass\|CORRECT) | | | | | |
| P(pass\|PARTIAL) | | | | | |
| P(pass\|WRONG) | | | | | |
| P(recon_ok) | | | | | |

Use McNemar (matched by case/model/trial) for pass rates. Bootstrap CI for conditional rates.

### Table C: Reasoning Transition Matrix (NEW — requires initial reasoning oracle labels)

| Initial → Final | N | % of total | Pass rate | Contribution to ΔP(pass) |
|----------------|---|-----------|-----------|--------------------------|
| C → C | | | | execution alignment |
| C → P | | | | reasoning degradation |
| C → W | | | | reasoning degradation |
| P → C | | | | reasoning repair |
| P → P | | | | partial compensation |
| P → W | | | | reasoning degradation |
| W → C | | | | reasoning repair |
| W → P | | | | partial upgrade |
| W → W | | | | lucky fix / noise |

### Table D: Channel Attribution Summary

| Channel | Contribution (pp) | % of total gain | Interpretation |
|---------|-------------------|----------------|---------------|
| Execution alignment (C→C) | | | Critique helps correct reasoners implement |
| Reasoning repair (upgrades) | | | Critique fixes wrong reasoning |
| Lucky fix / noise (W→W, degradations) | | | Spurious gains |
| **Total** | | 100% | |

### Table E: Per-Case Breakdown

| Case | N | Baseline pass | Critique pass | Δ | Dominant channel | C→C pass rate | Upgrade rate |
|------|---|--------------|--------------|---|-----------------|--------------|-------------|

### Table F: Reconstruction Control

| Condition | P(recon_ok) | P(pass\|recon_ok) |
|-----------|------------|-------------------|
| baseline | | |
| critique | | |
| Δ | | |

If |Δ P(recon_ok)| > 5pp, reconstruction is a confound.

---

## 5. Interpretation Logic

### Pattern 1: Execution-Alignment Dominant
- ΔP(pass|CORRECT) is large (>15pp)
- ΔP(CORRECT) is small (<5pp)
- C→C is the largest cell AND has the highest pass rate gain
- **Interpretation**: Critique helps models translate correct understanding into working code. The critique feedback identifies implementation gaps.

### Pattern 2: Reasoning-Repair Dominant
- ΔP(CORRECT) is large (>10pp)
- Upward transitions (P→C, W→C) are frequent (>15% of critique triples)
- These transitions have high pass rates
- **Interpretation**: Critique feedback causes models to revise their mechanism identification. The second attempt doesn't just fix code — it fixes understanding.

### Pattern 3: Lucky-Fix Dominant
- ΔP(pass|WRONG) is large (>10pp)
- W→W is the largest contributor to pass rate gain
- ΔP(CORRECT) is flat or negative
- **Interpretation**: Critique is not improving reasoning or execution quality. It's giving wrong-reasoning models more attempts to stumble into passing code. Claims about critique should be downgraded.

### Pattern 4: Mixed
- Multiple channels contribute significantly
- C→C execution gain AND upward transitions both contribute
- **Interpretation**: Critique operates through both channels. Report the proportional contribution of each.

### Pattern 5: Reconstruction Artifact
- ΔP(recon_ok) > 5pp AND ΔP(pass|recon_ok) ≈ 0
- **Interpretation**: Critique helps models produce parseable output, not better code. Gains are formatting artifacts.

---

## 6. Stage A: Metric Computation

### Step 1: Revalidate existing metrics
Recompute Table A from joined oracle + execution data. Verify against previously reported numbers. If discrepancies > 1pp, investigate.

### Step 2: Extract initial reasoning from critique workers
For each critique worker in `logs/retry_critique_stage2/*/workers/*critique*/attempt_001/calls/000001.json`:
- Parse `response_raw` as JSON
- Extract `root_cause` and `fix_strategy`
- Write to `audits/oracle_critique/initial_reasoning.jsonl` with keys: case_id, model, trial, root_cause_initial, fix_strategy_initial

**Scope**: 750 critique workers. No API calls — this is pure file reading and JSON parsing.

**Failure mode**: Some call 1 responses may be malformed JSON (same parse failures as the main pipeline). Use the same recovery logic. If unrecoverable, mark as UNJUDGABLE_INITIAL.

### Step 3: Oracle-label initial reasoning
Run the oracle evaluator on the 750 initial reasoning extracts. Same prompt, same pipeline as the main oracle run.

**Cost**: 750 calls × ~$0.002 = ~$1.50. Time: ~2 minutes with 200 workers.

**Output**: `audits/oracle_critique/initial_oracle_labels.jsonl` with reasoning_truth_initial for each critique triple.

### Step 4: Build transition matrix
Join:
- initial_oracle_labels (reasoning_truth_initial)
- existing oracle_labels (reasoning_truth_final = reasoning_truth for critique condition)
- execution data (pass/fail)

Compute Tables C, D, E, F.

### Step 5: Compute channel attribution
Apply the formal decomposition from Section 3.4.

**Estimated total time for Stage A**: ~30 minutes (mostly the oracle labeling of initial reasoning).

---

## 7. Stage B: Targeted Ablation

### Decision Gate

Run Stage B ONLY IF Stage A reveals:

1. Execution alignment is the dominant channel (>50% of gain) AND
2. There exist specific cases where critique dramatically improves P(pass|C→C) AND
3. We want to test whether a SIMPLER intervention (e.g., critique without the classifier, or critique with a different feedback format) achieves the same effect

If lucky fixes dominate (>40% of gain), do NOT run Stage B. Instead, investigate why and redesign the critique prompt.

If reasoning repair dominates, Stage B should test whether the repair is genuine or whether the second attempt just gives the model another chance to guess differently.

### Ablation Design (if triggered)

**Arms:**
- A: baseline_v2 (control)
- B: retry_bare_retry_v2 (retry without critique feedback — tests whether a second attempt alone helps)
- C: retry_leg_critique_strict_v2 (full critique — existing condition)

**Case Selection (6 cases):**

Category A1 — Strict non-conversions (baseline P(pass|C) < 20%, critique P(pass|C) > 40%):
- Select 2 cases from Stage A where C→C pass rate gain is largest
- These are where execution alignment is strongest

Category A2 — Promising reasoning repair (high P→C or W→C transition rate under critique):
- Select 2 cases where upward transitions are most frequent
- These test whether critique genuinely repairs reasoning

Category C2 — Negative controls (cases where critique does NOT help):
- Select 2 cases where critique Δpass ≈ 0 or negative
- These verify the measurement isn't biased

**Models**: gpt-4o-mini and gpt-5.4-mini (one weaker, one stronger)
**Trials**: 50 per cell
**Total events**: 6 cases × 2 models × 3 arms × 50 trials = 1,800 events
**Cost**: ~$36-72 generation + ~$4 oracle labeling = ~$40-76

**What this ablation answers that Stage A cannot:**
- Does bare retry achieve the same gain as critique? If yes, the critique feedback content is irrelevant — models just need a second attempt.
- Does the effect replicate on new trials? Stage A uses existing data; Stage B generates fresh data.
- Is the effect stable across different trial samples? (Addresses potential overfitting to specific API call outputs.)

---

## 8. Decision Thresholds

| Observation | Decision |
|-------------|----------|
| Execution alignment > 50% of gain AND C→C pass gain > 20pp | Frame critique as execution-alignment intervention. Proceed to Stage B. |
| Reasoning repair > 50% of gain AND P→C transition > 20% | Frame critique as reasoning-repair intervention. Test whether bare retry achieves same repair rate. |
| Lucky fix > 40% of gain | Downgrade critique claims. Investigate whether retry count alone explains gains. Do NOT proceed to Stage B. |
| Reconstruction Δ > 5pp | Flag as confound. Recompute all metrics on recon-only subset before any claims. |
| C→C pass rate LOWER under critique than baseline | Critique may be HARMING correct reasoners (similar to lean). Investigate per-case. |
| UNJUDGABLE_INITIAL > 20% | Initial reasoning extraction is unreliable. Stage A decomposition is compromised. Report with heavy caveat. |

---

## 9. Risks and Failure Modes

### 9.1 Oracle labels reflect final reasoning, not initial
**Status**: VERIFIED. case.end uses call 3 (or call 5) reasoning, not call 1.
**Handling**: Extract initial reasoning from call 1 files (Step 2). Oracle-label separately.

### 9.2 Initial reasoning may be unparseable
Call 1 response is raw JSON. Some models (especially 4o-mini) produce malformed JSON ~4% of the time.
**Handling**: Use same recovery logic as main pipeline. Mark unrecoverable as UNJUDGABLE_INITIAL. Report rate. If >20%, decomposition is unreliable.

### 9.3 The critique text itself leaks ground truth
The critique classifier sees ground truth bug type and invariant (in "grounded" mode). If the critique text passed to the model contains ground-truth-derived information, the model's "improved reasoning" may just be parroting the ground truth.
**Handling**: Inspect 10 critique texts. Check whether they contain ground truth verbatim or only reference the model's own stated commitments. This is a critical validity check.

### 9.4 Retry count confound
Critique workers get 2-6 calls. Bare retry also gets multiple attempts. If critique's gain is proportional to attempt count rather than critique quality, the feedback content is irrelevant.
**Handling**: Compare critique vs bare retry in Stage A. Both have multiple attempts. If bare retry achieves similar gains, critique feedback is not the active ingredient.

### 9.5 Conditioning on initial reasoning is a post-treatment variable
The initial reasoning is itself affected by the condition (critique workers get the lean prompt, baseline workers get the baseline prompt). Strictly, we should only compare critique vs lean (same initial prompt), not critique vs baseline.
**Handling**: Report critique vs baseline AND critique vs lean decompositions separately. The lean comparison is the cleaner one for decomposition. The baseline comparison is for total effect estimation.

### 9.6 Small N per cell after transition matrix split
750 critique workers split into a 3×3 transition matrix = 9 cells. Some cells may have <20 events.
**Handling**: Apply power rules. Do not claim significance for cells with N<20. Report cell sizes alongside all rates.

### 9.7 Oracle evaluator disagreement between initial and final labels
If the oracle evaluator is noisy (kappa=0.56), some apparent P→C transitions may be measurement noise.
**Handling**: Report expected noise rate based on kappa. If ~12% of labels are unreliable (1 - 0.88 agreement), ~12% of transitions may be artifactual. Bound the contribution of noise to the transition matrix.

---

## 10. Action Sequence

1. **Revalidate** existing Table A metrics from joined data (5 min, no API calls)
2. **Extract** initial reasoning from 750 critique worker call files (10 min, no API calls)
3. **Inspect** 10 critique texts for ground truth leakage (10 min, manual)
4. **Oracle-label** 750 initial reasoning extracts (2 min, ~$1.50)
5. **Build** transition matrix (Table C) and channel attribution (Table D) (5 min)
6. **Compute** per-case breakdown (Table E) and reconstruction control (Table F) (5 min)
7. **Review** results against decision thresholds (Section 8)
8. **Decide** whether Stage B ablation is justified
9. **If yes**: define exact case selection based on Stage A findings, then run
