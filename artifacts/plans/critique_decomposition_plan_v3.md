# Critique Effect Decomposition — Plan v3

**Date**: 2026-04-01
**Revision**: v3 — micro-revision of v2. Three targeted fixes: (1) residual code context limitation for reasoning-only arm, (2) dual-reference EA attribution, (3) pilot noise disclaimer.

**What changed from v2**: Added Section 4.3.1 (context leakage limitation), extended Section 3.4 with dual-reference EA, added Section 4.8.1 (pilot interpretation constraint). No other changes.

---

## 1. Objective

Decompose critique's total pass rate gain into:

1. **Execution alignment** — critique helps correct reasoners implement better code
2. **Reasoning repair** — critique causes models to revise their mechanism identification
3. **Lucky fixes / noise** — critique increases passes for wrong reasoners

Determine the proportional contribution of each channel.

---

## 2. Verified Data State

### 2.1 What Exists

| Asset | Location | Count | Status |
|-------|----------|-------|--------|
| Critique stage2 events | logs/retry_critique_stage2/merged_events.jsonl | 3,000 case.end | VERIFIED |
| Oracle labels (final reasoning) | audits/oracle_critique/oracle_labels.jsonl | 3,000 | VERIFIED |
| Initial reasoning (call 1) | logs/retry_critique_stage2/*/workers/*/attempt_001/calls/000001.json | 750 critique workers | EXISTS, NOT YET EXTRACTED |
| Critique text (call 2→3) | logs/retry_critique_stage2/*/workers/*/attempt_001/calls/000003.json | 694 with critique text | VERIFIED CLEAN (0/100 GT leakage) |

### 2.2 Schema Verification

- case.end `v2_artifact.raw_root_cause` reflects **FINAL** attempt reasoning (verified: matches call 3, not call 1)
- `retry_passed_at`: 0=passed initial (56), 1=passed retry 1 (118), 2=passed retry 2 (34), None=never passed (542)
- Call counts: 2 (56 workers, no retry), 4 (158, 1 retry), 6 (504, 2 retries)
- Conditions: baseline_v2 (750), leg_reduction_lean_v2 (750), retry_bare_retry_v2 (750), retry_leg_critique_strict_v2 (750)
- 10 cases, 6 models, 50 trials, fully matched

### 2.3 Ground Truth Leakage Check

**PASSED.** 100 critique texts manually inspected:
- 0/100 contain verbatim bug type, invariant, or location
- 98/100 reference the model's own reasoning ("the fix strategy says...", "the root cause claims...")
- 0/100 use ground truth language

The reasoning repair channel is valid.

---

## 3. Stage A — Metric Decomposition

### Step A1: Extract Initial Reasoning (no API calls)

For each of the 750 critique workers in `logs/retry_critique_stage2/*/workers/*critique*/attempt_001/calls/000001.json`:
- Parse `response_raw` as JSON
- Extract `root_cause` and `fix_strategy`
- Write to `audits/oracle_critique/initial_reasoning.jsonl`

Schema per row:
```json
{
    "case_id": "...", "model": "...", "trial": 1,
    "root_cause_initial": "...",
    "fix_strategy_initial": "...",
    "parse_success": true
}
```

**Expected failures**: ~4% malformed JSON (based on main pipeline parse failure rate for 4o-mini). Use same JSON recovery logic. Mark unrecoverable as `parse_success: false`.

**Time**: 5 minutes, no API calls.

### Step A2: Oracle-Label Initial Reasoning (750 API calls)

Run the oracle evaluator on the 750 initial reasoning extracts. Identical pipeline to the main oracle run:
- `build_oracle_spec` from cases_v2.json
- `load_buggy_code` from code_snippets_v2/
- `render_prompt` with initial root_cause/fix_strategy
- Call gpt-5-mini, temperature=0
- Parse response → reasoning_truth_initial

**Output**: `audits/oracle_critique/initial_oracle_labels.jsonl`

Schema per row:
```json
{
    "case_id": "...", "model": "...", "trial": 1,
    "condition": "retry_leg_critique_strict_v2",
    "reasoning_truth_initial": "CORRECT",
    "justification_initial": "..."
}
```

**Cost**: ~$1.50. **Time**: ~2 minutes with 200 workers.

### Step A3: Build Transition Matrix

Join three data sources on (case_id, model, trial):

1. `initial_oracle_labels.jsonl` → reasoning_truth_initial
2. `oracle_labels.jsonl` (existing, critique condition only) → reasoning_truth_final
3. `matched_events.jsonl` (critique condition only) → execution_pass

For each critique worker, produce:
```json
{
    "case_id": "...", "model": "...", "trial": 1,
    "reasoning_initial": "PARTIAL",
    "reasoning_final": "CORRECT",
    "execution_pass": true,
    "transition": "P→C"
}
```

Compute the 3×3 transition matrix (Table C from plan v1):

| Initial → Final | Count | % | Pass rate |
|----------------|-------|---|-----------|

### Step A4: Compute Channel Attribution

#### Dual-Reference Execution Alignment

The execution alignment estimate depends on which condition is used as the reference for "what P(pass|CORRECT) would be without critique." The critique condition uses the lean prompt for its initial generation, so both baseline and lean are relevant references.

Define:

```
EA_baseline = P(C→C) × [P(pass|C→C) - P(pass|CORRECT,baseline)]
EA_lean     = P(C→C) × [P(pass|C→C) - P(pass|CORRECT,lean)]
```

**Interpretation rule:**
- If EA_baseline ≈ EA_lean → the attribution is stable and reference-insensitive
- If they differ substantially (>5pp) → the execution alignment estimate is reference-sensitive and BOTH values must be reported

**Requirement**: Report BOTH EA_baseline and EA_lean in Table D. Use EA_lean as the primary estimate (since critique's initial prompt matches lean), and EA_baseline as the secondary estimate.

#### Reasoning Repair Contribution

```
RR = Σ_{upgrade transitions} P(transition) × [P(pass|transition) - P(pass|initial_label,baseline)]
```
Upgrade transitions: W→C, W→P, P→C. For each, the contribution is the fraction of triples in that cell times the pass rate gain over what that initial reasoning quality achieves at baseline.

#### Lucky Fix / Noise Contribution

```
LF = ΔP(pass) - EA - RR
```
Residual. Includes W→W pass rate changes, degradation transitions, and any measurement noise.

### Step A5: Compute Per-Case and Per-Model Breakdowns

For each of the 10 cases:
- Transition distribution
- Dominant channel
- Cell sizes (flag if any cell < 5)

For each of the 6 models:
- Same breakdown

### Step A6: Reconstruction Control

Compute P(reconstruction_status=SUCCESS) per condition. If |Δ| > 5pp between baseline and critique, flag.

Recompute Tables C and D on recon-only subset.

---

## 4. Stage B — Targeted Ablation

### 4.1 Decision Gate

Run Stage B ONLY IF Stage A reveals actionable structure. Exact criteria:

| Stage A Finding | Stage B Decision |
|----------------|-----------------|
| EA > 50% of gain AND specific cases identifiable | RUN: test execution alignment cases |
| RR > 50% of gain | RUN: test reasoning repair with reasoning-only pilot |
| LF > 40% of gain | DO NOT RUN. Investigate noise source. |
| Recon Δ > 5pp | DO NOT RUN. Fix measurement first. |
| No clear dominant channel | RUN with mixed case selection |

### 4.2 Ablation Arms

| Arm | Condition | Purpose |
|-----|-----------|---------|
| A | baseline_v2 | Control |
| B | retry_bare_retry_v2 | Tests whether a second attempt alone helps (no critique feedback) |
| C | retry_leg_critique_strict_v2 | Full critique (existing) |
| D | retry_reasoning_only_critique_v1 | NEW: reasoning-only critique (pilot, 5 trials) |

### 4.3 Reasoning-Only Critique Implementation

**New critique prompt** (add to `_CRITIQUE_PROMPTS` in `retry_v2.py`):

```python
"reasoning_only": """You are auditing a developer's stated reasoning about a software bug.

You are given ONLY the developer's reasoning. You do NOT see their code.

ROOT CAUSE:
{root_cause}

FIX STRATEGY:
{fix_strategy}

Task:
Write exactly ONE sentence identifying the weakest, most unsupported, or most internally inconsistent claim in the developer's reasoning.

Strict CLAUDE_RULES:
- Do NOT mention code, functions, variables, files, or implementation details
- Do NOT suggest fixes or edits
- Do NOT reference any code the developer may have produced
- Only identify reasoning weaknesses: vagueness, internal contradictions, unsupported causal claims, or missing logical steps
- If the reasoning is fully coherent and specific, output exactly: NO_WEAKNESS

Output:
One sentence only."""
```

**Key difference from full critique**: This prompt receives `root_cause` and `fix_strategy` but **NOT `code`**. It cannot identify reasoning-code mismatches. It can only identify internal reasoning weaknesses.

**Wiring**:
- Add `"reasoning_only"` to `_CRITIQUE_PROMPTS` dict
- Add condition name `retry_reasoning_only_critique_v1` to `constants.py` V2_CONDITIONS
- Add to `_resolve_critique_variant`: `if "reasoning_only" in condition: return "reasoning_only"`
- In `_generate_critique`: when variant is `"reasoning_only"`, pass empty string for `code` parameter so the prompt gets `{code}` = `""`. Or better: use the dedicated `reasoning_only` template which doesn't have a `{code}` field at all.

**Retry prompt**: Same as full critique: "Your previous attempt may not fully reflect your reasoning. Critique: {critique_text}. Revise your code."

#### 4.3.1 Limitation: Residual Code Context

Although the reasoning-only critique prompt does not include code, the generation model has already seen the buggy code during its initial attempt (call 1) and produced code in its initial response. The model retains internal memory of both the buggy code and its own generated code from that attempt.

Therefore: this intervention removes explicit code feedback from the critique but does NOT remove the model's internal memory of the code.

This arm isolates the absence of explicit reasoning-code mismatch feedback, NOT a pure reasoning-only setting. Any observed effect cannot be interpreted as purely reasoning repair; it may still include implicit execution alignment via latent code recall.

The correct interpretation of results from this arm is:

- If reasoning-only ≈ full critique → the explicit code-linkage in the critique sentence is not the active ingredient; the model can self-correct from a weaker signal
- If reasoning-only < full critique → the explicit code-linkage is a critical ingredient that the model's latent code memory cannot substitute for
- If reasoning-only ≈ bare retry → the reasoning-only feedback provides no value beyond a second attempt

### 4.4 Case Selection

Select cases AFTER Stage A results, using these rules:

**Category A1 — Execution alignment cases** (2 cases):
- Select from cases where C→C is the largest transition cell AND C→C pass rate under critique > C→C pass rate under baseline by > 20pp
- These are cases where correct reasoners benefit most from critique feedback

**Category A2 — Reasoning repair cases** (2 cases):
- Select from cases where P→C or W→C transitions are > 15% of critique triples AND these transitions have pass rate > 30%
- These are cases where critique actually changes understanding

**Category C2 — Negative controls** (1-2 cases):
- Select from cases where critique Δpass ≈ 0 or negative
- Verify that the ablation measurement is not biased

### 4.5 Models

- gpt-4o-mini (weaker, execution-limited)
- gpt-5.4-mini (stronger, capable)

Mirror this for the reasoning-only pilot.

### 4.6 Trial Counts

| Arm | Trials per cell | Purpose |
|-----|----------------|---------|
| A: baseline | 50 | Confirmatory |
| B: bare retry | 50 | Confirmatory |
| C: full critique | 50 | Confirmatory |
| D: reasoning-only (pilot) | 5 | Exploratory only |

### 4.7 Total Scope

Main Stage B:
- 5-6 cases × 2 models × 3 arms × 50 trials = 1,500-1,800 events

Reasoning-only pilot:
- 5 cases × 2 models × 1 arm × 5 trials = 50 events

**Total**: ~1,850 events
**Cost**: ~$37-55 generation + ~$5 oracle labeling = ~$42-60
**Time**: ~30 minutes with 100+ workers

### 4.8 Stage B Analysis

For the main ablation (arms A/B/C):
- Recompute all Stage A metrics on fresh data
- Test whether Stage A findings replicate
- Compare bare retry vs full critique to isolate critique content value

For the reasoning-only pilot (arm D):
- Report pass rate, P(CORRECT), P(pass|CORRECT) if oracle-labeled
- Compare: D vs B (reasoning-only vs bare retry) and D vs C (reasoning-only vs full critique)
- Interpretation per Section 4.3.1 limitations

#### 4.8.1 Pilot Interpretation Constraint

The reasoning-only arm uses 5 trials per cell and is underpowered. With 5 trials per (case, model) cell, the standard error of a pass rate estimate is up to ±22pp (at p=0.5). High variance and occasional reversals across cases and models are expected.

Results from this pilot are directional only and MUST NOT be used for significance claims or definitive conclusions. The pilot is used solely to determine whether the intervention is worth scaling to a full ablation (50 trials per cell). Apply the escalation rule in Section 4.9 strictly.

### 4.9 Escalation Rule for Pilot

Promote reasoning-only critique to full ablation (50 trials) ONLY IF:
- Consistent positive delta over bare retry across selected cases
- Recovers ≥ 50% of full critique pass rate gain
- No obvious confounds

If it fails: drop immediately, do not expand.

---

## 5. Output Tables

### From Stage A

**Table A**: Condition-level summary (revalidation of existing metrics)

| Condition | N | P(C) | P(P) | P(W) | Pass | P\|C | P\|P | P\|W | Recon% |
|-----------|---|------|------|------|------|------|------|------|--------|

**Table B**: Critique vs baseline deltas with CIs

| Metric | Baseline | Critique | Δ | 95% CI |
|--------|----------|----------|---|--------|

**Table C**: Transition matrix (THE KEY TABLE)

| Initial → Final | N | % | Pass rate | Contribution to Δ Pass (pp) |
|----------------|---|---|-----------|---------------------------|

**Table D**: Channel attribution summary

| Channel | Contribution (pp) vs baseline | Contribution (pp) vs lean | % of total gain |
|---------|-------------------------------|--------------------------|----------------|

**Table E**: Per-case dominant channel

| Case | N | Baseline pass | Critique pass | Δ | EA contrib | RR contrib | LF contrib | Dominant |
|------|---|--------------|--------------|---|-----------|-----------|-----------|----------|

**Table F**: Per-model breakdown

| Model | N | EA% | RR% | LF% | Regime |
|-------|---|-----|-----|-----|--------|

### From Stage B (if run)

**Table G**: Fresh ablation results

| Case | Model | Baseline | Bare retry | Full critique | Reasoning-only | Critique - Retry |
|------|-------|----------|-----------|--------------|----------------|-----------------|

---

## 6. Interpretation Logic (unchanged from v1)

| Pattern | Signal | Conclusion |
|---------|--------|-----------|
| EA > 50%, ΔP(C) < 5pp | P(pass\|C→C) drives gain | Critique is execution alignment |
| RR > 30%, P→C and W→C frequent | Upward transitions drive gain | Critique is reasoning repair |
| LF > 40%, P(pass\|W→W) rising | Wrong reasoners passing more | Gains are noise, downgrade claims |
| Mixed EA + RR | Both channels contribute | Report proportions, both are real |
| Recon Δ > 5pp | Formatting artifact | Stop, fix measurement |

---

## 7. Risks

| Risk | Detection | Mitigation |
|------|-----------|-----------|
| Initial reasoning unparseable (>20%) | Count parse failures in Step A1 | Mark UNJUDGABLE_INITIAL, report rate, caveat decomposition |
| Small transition cells (<5 per cell) | Cell size check in Step A5 | Pool across models for case-level, flag underpowered cells |
| Oracle noise in transitions (~12%) | Based on kappa=0.56 | Bound noise contribution: ~12% of transitions may be artifactual. Report sensitivity. |
| Critique prompt leaks ground truth | Already checked | PASSED: 0/100 leakage |
| Bare retry = full critique (no content value) | Stage B comparison | If B ≈ C, critique feedback is irrelevant — second attempt is the active ingredient |
| Conditioning on initial reasoning is post-treatment | Initial prompt differs (lean vs baseline) | Report critique vs lean AND critique vs baseline separately |
| Reasoning-only prompt too weak/strong | Pilot results | If no signal at 5 trials, drop. Do not over-interpret. |
| EA reference sensitivity | Compare EA_baseline vs EA_lean | If they differ >5pp, report both and caveat |
| Reasoning-only pilot noise | 5 trials per cell = ±22pp SE | Directional only, no significance claims, escalation rule only |
| Residual code context in reasoning-only arm | Cannot be eliminated | Interpret as "absence of explicit mismatch feedback" not "pure reasoning repair" |

---

## 8. Action Sequence

### Stage A (total: ~30 minutes, ~$1.50)

1. Extract initial reasoning from 750 critique worker call files → `initial_reasoning.jsonl` (5 min)
2. Oracle-label 750 initial reasoning extracts with 200 workers → `initial_oracle_labels.jsonl` (2 min, ~$1.50)
3. Join initial labels + final labels + execution → transition dataset (2 min)
4. Compute transition matrix (Table C) and channel attribution (Table D) with dual-reference EA (5 min)
5. Compute per-case (Table E) and per-model (Table F) breakdowns (5 min)
6. Compute reconstruction control (2 min)
7. Review against decision thresholds → go/no-go for Stage B (5 min)

### Stage B (total: ~45 minutes, ~$42-60, IF triggered)

8. Implement reasoning-only critique prompt in retry_v2.py (10 min)
9. Select cases based on Stage A results per Section 4.4 rules (5 min)
10. Create config YAML and launch ablation with 100+ workers (5 min)
11. Wait for generation (~20 min)
12. Oracle-label new data (~5 min)
13. Compute Table G and pilot comparison (5 min)
14. Apply escalation rule for reasoning-only pilot (Section 4.9)
