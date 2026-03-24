# System Audit: Research System for LLM Code Generation Evaluation

**Date:** 2026-03-23
**Type:** End-to-end audit aligning implementation with validated research framework

---

## 1. Current System Snapshot

### 1A. Pipeline Architecture

```
Case Definition (cases.json / cases_v2.json)
    ↓
Prompt Construction (prompts.py, execution.py)
    ↓ dispatch by condition:
    │
    ├── baseline/DX/GR/GS/CF/RA/SC/CC/TD → run_single()
    │       ↓
    │   call_model() → parse_model_response() → evaluate_output()
    │       ↓
    │   write_log() → per-iteration JSONL
    │
    ├── repair_loop → run_repair_loop()     [legacy, 2-attempt fixed]
    │       ↓
    │   attempt 1 → eval → if fail → attempt 2 with error feedback
    │
    ├── contract_gated → run_contract_gated()
    │       ↓
    │   elicit contract → generate code → gate_validate() → retry if gate fails
    │
    ├── retry_no_contract → run_retry_harness(use_contract=False)
    │       ↓
    │   generate → eval → critique → retry (up to 5 iterations)
    │   full trajectory logged
    │
    └── retry_with_contract → run_retry_harness(use_contract=True)
            ↓
        elicit contract → generate → eval → critique → retry
        contract context provided on retries
```

**Key files:**
| File | Lines | Role |
|---|---|---|
| `runner.py` | 275 | Orchestrator: loads cases, dispatches conditions |
| `execution.py` | 377 | Single-shot + repair_loop + CGE execution + logging |
| `retry_harness.py` | 787 | Full retry system with trajectory logging |
| `evaluator.py` | 253 | Dispatch to exec_eval + reasoning signals + evidence scoring |
| `exec_eval.py` | 874 | Execution-based invariant tests per case |
| `eval_cases.py` | 720 | Heuristic text-matching evaluators (fallback) |
| `contract.py` | 215 | CGE contract parsing + prompt builders |
| `diff_gate.py` | 519 | Contract gate validation (6 structural checks) |
| `parse.py` | 284 | Model response parsing (JSON, code blocks, fallbacks) |
| `prompts.py` | 229 | Diagnostic/guardrail nudge library |

### 1B. Benchmark Sets

| Set | Cases | Coverage | Status |
|---|---|---|---|
| **v1** (`cases.json`) | 37 | 18 original hard + 19 difficulty variants | Production. Validated with 3 models × 19 conditions. Known evaluation bugs (alias_trivial, retry_ack_trivial) |
| **v2** (`cases_v2.json`) | 45 | 15 families × 3 levels (A/B/C) | Newly generated. 45/45 pass loads/fails_buggy/passes_fixed/idempotent. Not yet tested with LLMs |

### 1C. Existing Experiments (Completed)

| Experiment | Data | Finding |
|---|---|---|
| 19-condition full run (18 cases × 3 models) | `logs/*_055552.jsonl` etc. | Baseline pass rates: nano 0%, 4o-mini 28%, 5-mini 6% |
| CGE controlled (3 runs × 3 models × 18 cases) | 9 log files (072xxx–074xxx) | CGE +1.0 nano, -2.0 4o-mini, 0.0 5-mini |
| 37-case baselines (2 timepoints) | 143xxx and 151xxx logs | Pass rate shift suggests eval code changed between runs |
| Regime analysis | `REGIME_ANALYSIS_20260323.md` | 3-regime framework confirmed: REI, Heuristic, CSF |

### 1D. What logging_v2 Is

logging_v2 lives in `../logging_v2/` (the multi-agent debate system's event logger). It is **not integrated with the T3 code generation pipeline**. T3 uses its own 3-file JSONL logging (`execution.py: write_log()`). These are separate systems.

---

## 2. Gaps vs Research Goals

### GAP 1: Two benchmark sets, neither complete

- **v1** has production run data but known evaluation bugs and no difficulty ladder
- **v2** has correct structure and tests but zero experimental data
- No bridge between them: the 12 cases referenced in the ablation plan are v1 cases, not v2

**Impact:** Cannot run the ablation experiment on v2 cases until runner.py is updated to load v2. Cannot use v1 data for v2 analysis because the cases are different.

### GAP 2: failure_classifier.py does not exist

The ablation plan specifies `failure_classifier.py` as the first implementation step. It doesn't exist yet. Without it, `retry_adaptive` cannot work.

**Impact:** Only 2 of the planned 5 ablation conditions are currently runnable: `retry_no_contract`, `retry_with_contract`. The other 3 (`baseline`, `retry_adaptive`) — baseline works through runner.py, but retry_adaptive needs the classifier.

### GAP 3: Retry harness regime classification is approximate

`retry_harness.py:_classify_regime()` uses `reasoning_consistent AND diff_small → REI`, `NOT reasoning_consistent AND NOT diff_small → CSF`. This is directionally correct but doesn't match the refined v4 plan's mechanism-signal definitions (which use `error_stable` via entropy, `diff_localized` via edit distance, `progress_made`). The current implementation uses `diff_small` (avg chars changed < 100) as a proxy for localization — crude but functional.

**Impact:** Regime labels in current logs are usable for exploratory analysis but not for paper claims. The refined definitions in v4 are more rigorous.

### GAP 4: No ground_truth_bug field in v1 cases

v1 cases don't have `ground_truth_bug` (with `.type`, `.location`, `.invariant`). This field is required by the v4 plan's `critique_accuracy` computation. v2 cases have it.

**Impact:** Critique accuracy cannot be computed for v1 runs. v2 cases support it.

### GAP 5: CGE and retry are cleanly separated — good

CGE (`contract_gated`) and retry (`retry_no_contract`, `retry_with_contract`) are already separate conditions dispatched through different code paths. CGE goes through `execution.py:run_contract_gated()`. Retry goes through `retry_harness.py`. They share the same evaluation path (`evaluate_output()`). This is correct architecture.

### GAP 6: No ablation_config.yaml or run script

The ablation plan references `ablation_config.yaml` and `scripts/run_ablation_config.py`. Neither exists.

### GAP 7: shadow_analysis.py does not exist

Post-hoc analysis script for comparing conditions. Referenced in ablation plan but not yet written.

### GAP 8: v2 cases not integrated into runner.py

runner.py hard-codes `cases.json` path. v2 cases use a different file (`cases_v2.json`) with different schema fields. runner.py needs `--cases` flag or auto-detection.

---

## 3. Immediate Fixes (HIGH PRIORITY)

These are the minimum changes needed to run the ablation experiment.

### Fix 1: Add --cases flag to runner.py

```python
# In runner.py main():
parser.add_argument("--cases", default="cases.json",
                    help="Path to cases JSON file")
# In load_cases():
cases_path = BASE_DIR / args.cases  # instead of hardcoded "cases.json"
```

**Effort:** 3 lines. **Unblocks:** running v2 cases through the existing pipeline.

### Fix 2: Apply micro-fixes from retry_ablation_final_microfixes.md

Three changes to `retry_harness.py`:
1. Rename `trajectory_pattern` → `status_sequence`
2. Add `attempt_progress = k / max_iterations` per entry
3. Add `hint_used_type` per entry (null for non-adaptive)

**Effort:** ~15 lines. **Unblocks:** cleaner logging for analysis.

### Fix 3: Create minimal failure_classifier.py

The ablation plan has a complete spec. Implement the 4-rule priority classifier:
1. Critique keyword match (conf 0.8)
2. Error category mapping (conf 0.5)
3. Keyword scan on reasons (conf 0.3)
4. UNKNOWN (conf 0.0)

**Effort:** ~80 lines + tests. **Unblocks:** `retry_adaptive` condition.

### Fix 4: Add retry_adaptive condition to runner.py

```python
# In runner.py _run_one():
if condition == "retry_adaptive":
    from retry_harness import run_retry_harness
    return run_retry_harness(case, model, use_contract=False, use_adaptive=True)
```

Requires `retry_harness.py` to accept `use_adaptive` parameter and integrate with `failure_classifier.py`.

**Effort:** ~40 lines in retry_harness.py + 1 line in runner.py. **Unblocks:** the key experimental condition.

### Fix 5: Create ablation_config.yaml + run script

```yaml
models: [gpt-4o-mini, gpt-5-mini]
conditions: [baseline, retry_no_contract, retry_with_contract, retry_adaptive]
cases_file: cases_v2.json
max_iterations: 5
replications: 1  # increase to 3 for final
```

**Effort:** Config file + ~30 line script. **Unblocks:** reproducible experiment execution.

---

## 4. Regime Classification Design

### Current State

`retry_harness.py:_classify_regime()` already implements a basic version:

```python
if n == 1 and converged: regime = "heuristic"
elif reasoning_consistent and diff_small: regime = "REI"
elif not reasoning_consistent and not diff_small: regime = "CSF"
elif not critique_consistent: regime = "CSF"
else: regime = "mixed"
```

### Recommended Upgrade (aligned with v4 plan)

Do NOT replace the current implementation wholesale. Instead, add the refined signals alongside:

```python
def _classify_regime_v2(trajectory, ground_truth_bug=None):
    """V2 regime classification using mechanism signals.

    Falls back to v1 if ground_truth_bug not available.
    """
    signals = _compute_mechanism_signals(trajectory, ground_truth_bug)

    if not trajectory or trajectory[0].get("pass"):
        return "heuristic", signals

    rc = signals["reasoning_consistent"]
    es = signals["error_stable"]
    dl = signals["diff_localized"]

    if rc and es:
        regime = "REI"
    elif (not rc) and es and dl:
        regime = "heuristic"
    elif (not rc) and es and (not dl):
        regime = "heuristic_weak"
    else:
        regime = "CSF"

    return regime, signals
```

Log BOTH `failure_regime` (current) and `failure_regime_v2` (new) in the summary. This allows comparing the two classifiers without breaking existing log consumers.

**When to upgrade:** After the first v2 experiment run. Use v1 classification for exploratory work, v2 for paper claims.

---

## 5. Benchmark Expansion Plan

### Status: COMPLETE

The v2 benchmark (45 cases, 15 families × 3 levels) is built and validated:

- 45/45 pass loads, fails_buggy, passes_fixed, idempotent
- 15 families across 7 bug_pattern_classes
- 3 difficulty levels (L1/L2/L3 causal depth)
- Full schema with ground_truth_bug, structural metadata, test contracts

### What Remains

1. **First LLM run:** Execute baseline on v2 with 4o-mini + nano to calibrate difficulty
2. **Calibration pass:** Adjust cases where pass rates fall outside expected bands (§8 of v4 plan)
3. **Integration:** Connect v2 cases to retry harness by adding `--cases cases_v2.json` flag

### What NOT to do

- Do NOT generate more cases before the first calibration run
- Do NOT mix v1 and v2 cases in the same analysis
- Do NOT attempt Phase 2 (100+ cases) until v2 is validated experimentally

---

## 6. Experiment Plan (Next Steps)

### Phase A: Calibration (before ablation)

**Goal:** Verify v2 cases produce the expected difficulty gradient.

```
Run 1: ../.venv/bin/python runner.py --cases cases_v2.json --model gpt-4o-mini --conditions baseline --parallel 6
Run 2: ../.venv/bin/python runner.py --cases cases_v2.json --model gpt-4.1-nano --conditions baseline --parallel 6
```

**Expected:** ~70% pass on Level A, ~45% on Level B, ~20% on Level C for 4o-mini.

**If calibration fails:** Adjust specific cases using the levers in v4 plan §8.

**API calls:** ~90 (45 cases × 2 models)

### Phase B: Retry Ablation (the main experiment)

**Prerequisite:** Fixes 1-5 from §3 implemented.

```
For each model in [gpt-4o-mini, gpt-5-mini]:
  For each condition in [baseline, retry_no_contract, retry_with_contract, retry_adaptive]:
    runner.py --cases cases_v2.json --model {model} --conditions {condition} --parallel 6
```

**API calls:** ~450 minimum (45 cases × 2 models × 5 conditions × ~1-5 iterations per retry)

**Metrics to collect:** (all are already logged by retry_harness.py)
- Pass@1 per condition
- Converged@K (K=1,2,3,5)
- outcome_type distribution
- failure_regime distribution
- trajectory_type distribution
- convergence_slope
- error_entropy
- critique_accuracy

### Phase C: CGE Comparison

Run CGE (`contract_gated`) on v2 cases to compare with retry:

```
runner.py --cases cases_v2.json --model gpt-4o-mini --conditions contract_gated --parallel 6
```

**API calls:** ~135 (45 × 3 model calls per case for contract + code + gate)

**Key analysis:** CGE delta by bug_pattern_class and difficulty level. Compare with retry delta.

### Hypotheses to Test

| # | Hypothesis | Test |
|---|---|---|
| H1 | Level A cases are Heuristic for 4o-mini (>60% baseline pass) | Phase A baseline pass rate by level |
| H2 | Level C cases are mostly CSF (retry doesn't converge) | Phase B convergence rate by level |
| H3 | CGE helps REI cases but not CSF | Phase C: CGE delta stratified by regime |
| H4 | retry_adaptive outperforms retry_no_contract on REI cases | Phase B: conditional comparison stratified by regime |
| H5 | error_entropy distinguishes REI (low) from CSF (high) | Phase B: entropy distribution by observed regime |
| H6 | bug_pattern_class predicts regime | Phase B: regime distribution by pattern class |

---

## 7. Risks / Anti-Patterns

### DO NOT

1. **Do NOT treat v1 and v2 data as comparable.** Different cases, different tests, different evaluation code. Analyze separately.

2. **Do NOT run the full ablation before calibration.** If Level A cases are too hard or Level C too easy, the entire experiment produces no signal. Calibrate first.

3. **Do NOT build a complex analysis pipeline before having data.** Write the analysis scripts AFTER the first experiment produces logs. The log schema is already defined — the scripts can be written against it.

4. **Do NOT attempt to reconcile logging_v2 (debate system) with T3 logging.** They are separate systems for separate purposes. T3's 3-file JSONL is sufficient.

5. **Do NOT over-refine regime classification before experimental data.** The current `_classify_regime()` in retry_harness.py is good enough for exploratory analysis. Upgrade to v2 classification only when writing paper claims.

6. **Do NOT add more conditions.** 4 retry conditions (baseline + 3 retry variants) + CGE is already 5 conditions × 45 cases × 2 models = 450+ API calls. Adding DX/GR/GS/etc. to v2 cases multiplies cost without proportional insight.

7. **Do NOT generate Phase 2 cases (100+) yet.** The 45 v2 cases are sufficient for all planned analyses. Scale only after the framework is validated on this set.

### WATCH FOR

- **Evaluation bugs in v2:** The validation pipeline checks buggy→fail and fixed→pass, but doesn't verify that the test is testing the RIGHT thing. The first LLM run will reveal if any tests are too permissive (false passes) or too strict (false fails).

- **Non-determinism in 4o-mini:** The CGE controlled experiment showed std=1.53 across 3 runs for 4o-mini baseline. Single-run results on v2 may not be reproducible. Plan for at least 2 replications on the key conditions.

- **Token limits on Level C cases:** 3-4 files concatenated may exceed token budgets for smaller models. Monitor for truncation or parse failures.

---

## 8. Implementation Priority Order

```
1. Fix 1: --cases flag on runner.py                    [3 lines, 5 min]
2. Phase A: Calibration runs                           [~90 API calls]
3. Fix 2: Micro-fixes from ablation plan               [15 lines, 15 min]
4. Fix 3: failure_classifier.py                        [80 lines + tests, 1 hr]
5. Fix 4: retry_adaptive in runner.py + harness        [40 lines, 30 min]
6. Fix 5: ablation_config.yaml + run script            [30 lines, 15 min]
7. Phase B: Retry ablation                             [~450 API calls]
8. Phase C: CGE comparison                             [~135 API calls]
9. Analysis scripts (post-hoc)                         [after data exists]
```

Calibration (step 2) before infrastructure (steps 3-6) because it validates the cases before investing in the full ablation pipeline. If calibration reveals problems, we fix cases before building the adaptive retry system.
