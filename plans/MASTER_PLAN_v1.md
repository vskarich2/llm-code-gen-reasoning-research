# T3 Benchmark — Master Migration & Ablation Plan

**Date:** 2026-03-23
**Goal:** Unified benchmark system running V2 cases through the full pipeline (baseline + retry + CGE), ready for the definitive ablation experiment.
**Incorporates:** `retry_ablation_implementation_plan_v1.md`, `SYSTEM_AUDIT_AND_NEXT_STEPS.md`, `retry_ablation_final_microfixes.md`

---

## 0. Why This Plan Exists

We have two benchmark systems that don't talk to each other:

- **V1** (37 cases): battle-tested with 1000+ API runs, proven evaluation bugs fixed, retry harness works — but ad-hoc structure, no difficulty families, 20 inconsistent failure_modes
- **V2** (45 cases): clean design, 15 families × 3 levels, full metadata (ground_truth_bug, reference_fix, test_contract) — but zero LLM runs and not connected to the pipeline

Running two systems doubles maintenance and splits analysis. The migration unifies them.

---

## 1. Deep System Audit — Data Plumbing Analysis

### 1A. Critical Data Handoff Chain

```
cases.json → runner.py:load_cases()
    ↓ populates case["code_files_contents"]
    ↓
build_prompt(case, condition)
    ↓ reads case["task"], case["code_files_contents"]
    ↓
call_model(prompt, model)
    ↓ returns raw string
    ↓
parse_model_response(raw)          ← PARSE PATH 1 (retry harness)
    ↓ returns {reasoning, code, ...}
    ↓
evaluate_output(case, raw)         ← RE-PARSES raw internally (PARSE PATH 2)
    ↓ calls exec_evaluate(case, raw)
    ↓     ↓ parse_model_response(raw) again
    ↓     ↓ extract code
    ↓     ↓ load module
    ↓     ↓ _CASE_TESTS[case_id](mod) → (bool, reasons)
    ↓ returns ev dict
    ↓
write_log(...)
```

### 1B. Verified Working Handoffs

| Handoff | Status | Evidence |
|---|---|---|
| cases.json → runner.py | ✅ | 37 v1 cases load correctly |
| build_prompt for all 22 conditions | ✅ | test_all_conditions passes |
| call_model → parse_model_response | ✅ | 3 smoke tests with real API |
| exec_evaluate → _CASE_TESTS for v1 | ✅ | 234 tests pass |
| retry_harness full loop | ✅ | 68 unit tests + 3 real API runs |
| Per-iteration + summary logging | ✅ | Log integrity invariants verified |
| Parse consistency check | ✅ | Divergence warning implemented |

### 1C. BROKEN Handoffs (Must Fix Before Ablation)

| Handoff | Problem | Impact | Fix |
|---|---|---|---|
| **cases_v2.json → runner.py** | runner.py hardcodes `cases.json` | Cannot run v2 cases | Add `--cases` flag |
| **exec_evaluate → _CASE_TESTS for v2** | No v2 case IDs in dispatch table | All v2 cases score 0.5 ("no test") — **FALSE POSITIVES** | Bridge to v2 dynamic test loader |
| **evaluator._REASONING_SIGNALS for v2** | 10 of 15 v2 failure_modes have no signals | `reasoning_valid` always False for those cases — **biases REI detection** | Add signal keywords for v2 modes |

### 1D. Silent Failure Risks

| Risk | Where | Consequence | Detection |
|---|---|---|---|
| V2 case returns `pass=True, score=0.5` with no test | exec_eval.py:818 | Case appears "partially correct" when it was never tested | Check: no run should have `score=0.5` — add assertion |
| Critique JSON parse fails silently | retry_harness.py:464 | `_valid=False` critique contaminates signals | Already handled: invalid critiques excluded from estimate |
| V2 code_files with multi-file imports | exec_eval.py strip_local_imports | Syntax error after stripping | V2 Level A/B are single-file — risk only at Level C |
| Model returns partial code (function only) | parse.py / exec_eval.py | Module can't load, scores 0.0 | This is a real model behavior, not a plumbing bug |

### 1E. Test Coverage Gaps

| Area | Coverage | Gap |
|---|---|---|
| V1 pipeline (runner → eval → log) | 234 tests | Well covered |
| V2 case validation (buggy fails, fixed passes) | 45 tests | Well covered |
| **V2 cases through exec_eval.py** | **0 tests** | **CRITICAL — the bridge doesn't exist yet** |
| **V2 cases through runner.py** | **0 tests** | **CRITICAL — runner can't load v2** |
| Failure classifier | 0 tests | Not implemented yet |
| Retry_adaptive condition | 0 tests | Not implemented yet |
| Shadow analysis script | 0 tests | Not implemented yet |
| V2 reasoning signals | 0 tests | Signals don't exist for 10/15 modes |

---

## 2. Migration Plan: Unify V1 + V2

### 2A. Decision: V2 as Primary, 6 V1 Trap Cases Migrated

**Why V2 as primary:**
- Clean family structure (15 × 3) enables difficulty analysis
- Dynamic test loading (no 700-line dispatch table to maintain)
- Full metadata (ground_truth_bug, reference_fix, test_contract)
- All 45 cases validated (load, fail-buggy, pass-fixed, idempotent)

**Why keep 6 V1 trap cases:**
- They test adversarial task prompts (trap compliance) — V2 doesn't have this
- They have 1000+ API runs of experimental data
- They are the cases where REI was discovered and characterized

**Cases to migrate:**

| V1 Case | Why | V2 Family Slot |
|---|---|---|
| l3_state_pipeline | 100% REI, trap archetype | `v1_trap` family, level D |
| cache_invalidation_order | Version-tracking trap | `v1_trap` family, level D |
| feature_flag_drift | Cross-file flag trap | `v1_trap` family, level D |
| invariant_partial_fail | Incomplete rollback trap | `v1_trap` family, level D |
| async_race_lock | Only concurrency case | `v1_trap` family, level D |
| hidden_dep_multihop | 4-file dependency trap | `v1_trap` family, level D |

**Why NOT more V1 cases:**
- The 19 difficulty ladder cases (trivial/easy/med/hard) are superseded by V2's cleaner A/B/C
- The 4 easy calibration cases are covered by V2 Level A
- The v1 eval bugs (alias_trivial `inherit`, retry_ack `get_sent` dict/string) are fixed but fragile — v2 tests are cleaner

### 2B. Migration Steps

**Step 1: Bridge exec_eval.py to v2 test loader (~15 lines)**

```python
# In exec_eval.py, modify the dispatch:
def exec_evaluate(case, output):
    ...
    test_fn = _CASE_TESTS.get(case_id)
    if test_fn is None:
        # Try v2 dynamic loader
        test_fn = _load_v2_test(case)
    if test_fn is None:
        return _result(case_id, True, 0.5, ...)  # existing fallback
```

```python
def _load_v2_test(case):
    """Dynamically load test from tests_v2/ for v2 cases."""
    family = case.get("family")
    level = case.get("difficulty", "").lower()
    if not family or not level:
        return None
    test_path = BASE / "tests_v2" / f"test_{family}.py"
    if not test_path.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"test_{family}", test_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, f"test_{level}", None)
```

**Why this approach:** Minimal change. V1 cases continue using `_CASE_TESTS`. V2 cases get routed to their own tests. No code duplication. Test signature is already compatible: `fn(mod) -> (bool, list[str])`.

**Step 2: Add --cases flag to runner.py (~5 lines)**

```python
parser.add_argument("--cases", default="cases.json")
# In load_cases():
cases_path = BASE_DIR / args.cases
```

**Step 3: Add reasoning signals for v2 failure_modes (~30 lines)**

Add to `evaluator.py:_REASONING_SIGNALS`:
```python
"EARLY_RETURN": ["return", "early", "exit", "skip", "short-circuit"],
"INDEX_MISALIGN": ["index", "off-by-one", "offset", "boundary", "range"],
"MISSING_BRANCH": ["branch", "case", "condition", "else", "fallthrough"],
"MUTABLE_DEFAULT": ["mutable", "default", "shared", "argument", "parameter"],
"PARTIAL_STATE_UPDATE": ["partial", "incomplete", "update", "all fields"],
"SILENT_DEFAULT": ["default", "silent", "None", "fallback", "missing"],
"STALE_CACHE": ["stale", "cache", "invalidat", "fresh", "ttl"],
"TEMPORAL_DRIFT": ["timing", "order", "drift", "before", "after"],
"USE_BEFORE_SET": ["uninitial", "before set", "None", "not yet", "undefined"],
"WRONG_CONDITION": ["condition", "wrong", "inverted", "negat", "opposite"],
```

**Step 4: Add 6 v1 trap cases to cases_v2.json (~60 lines of JSON)**

Enrich each with v2 metadata fields and add to cases_v2.json as a `v1_trap` family with difficulty "D" (harder than C — adversarial task prompt). Their tests remain in `exec_eval._CASE_TESTS` (the bridge handles both paths).

**Step 5: Add fail-fast for score=0.5 (~3 lines)**

In exec_eval.py, when returning the "no test defined" result, log a WARNING:
```python
if test_fn is None:
    logging.getLogger("t3.exec_eval").warning(
        "NO TEST for case %s — returning score=0.5 (unverified)", case_id)
```

And in the retry harness, treat score=0.5 as a pipeline error rather than a pass.

### 2C. What Gets Dropped

| V1 Component | Action | Reason |
|---|---|---|
| 19 difficulty ladder cases (trivial/easy/med/hard variants) | **DROP** | Superseded by V2 A/B/C |
| 4 easy calibration cases (easy_temporal, etc.) | **DROP** | Superseded by V2 Level A |
| `cases.json` | **KEEP as archive** | Historical data reference; runner defaults to v2 |
| `eval_cases.py` (700 lines of heuristic evaluators) | **KEEP but deprioritize** | Still used as fallback by evaluator.py; not on critical path |
| V1-specific tests in `tests/` | **KEEP** | They test pipeline infrastructure, not just v1 cases |

---

## 3. Retry Ablation Implementation (from `retry_ablation_implementation_plan_v1.md`)

### What's already done:
- Core retry harness (68 tests) ✅
- Two conditions: retry_no_contract, retry_with_contract ✅
- All helpers: critique, contract, metrics, regime classification ✅

### What's left (incorporating micro-fixes):

**Phase 1: failure_classifier.py** (~120 lines + ~80 lines tests)
- Heuristic-only, no ground truth leakage
- 4-rule priority: critique keywords → error category → reason keywords → UNKNOWN
- Tests use synthetic data only

**Phase 2: Retry harness upgrades** (~120 lines modified)
- `use_adaptive` parameter
- ADAPTIVE_HINTS dict per failure type
- Confidence-gated hint selection (≥0.5 → specific hint, <0.5 → DEFAULT)
- Per-iteration: classification, intervention, hint_used_type, attempt_similarity, attempt_progress, latent_signal
- Per-summary: first_pass_success, recovered_on_retry, retry_effectiveness, failure_sequence, failure_transitions, trajectory_failure_pattern, classifier_coverage, latent_execution_gap, attempt_diversity, error_trajectory_detailed
- Rename: trajectory_pattern → status_sequence
- Stagnation upgrade: SequenceMatcher similarity > 0.95 for 3 consecutive

**Phase 3: runner.py** (~5 lines)
- Add `retry_adaptive` condition

**Phase 4: Analysis scripts** (~200 lines)
- `scripts/shadow_analysis.py` — post-hoc condition comparison
- `ablation_config.yaml` + `scripts/run_ablation_config.py`

---

## 4. Plumbing Verification Plan

### 4A. Bridge Verification Tests (NEW — must write before ablation)

```python
# tests/test_v2_bridge.py

def test_v2_case_loads_through_runner():
    """V2 case loads via --cases cases_v2.json."""
    cases = load_cases(cases_file="cases_v2.json")
    assert len(cases) == 51  # 45 v2 + 6 migrated traps
    assert all("code_files_contents" in c for c in cases)

def test_v2_case_evaluates_with_correct_test():
    """V2 case routes to tests_v2/ test, not 'no test defined'."""
    case = get_case("alias_config_a", cases_file="cases_v2.json")
    # Run with reference fix (should pass)
    ref_code = load_reference_fix(case)
    result = exec_evaluate(case, wrap_as_response(ref_code))
    assert result["pass"] is True
    assert result["score"] == 1.0  # NOT 0.5

def test_v2_case_fails_on_buggy_code():
    """V2 buggy code fails the v2 test."""
    case = get_case("alias_config_a", cases_file="cases_v2.json")
    buggy_code = load_buggy_code(case)
    result = exec_evaluate(case, wrap_as_response(buggy_code))
    assert result["pass"] is False

def test_v1_trap_case_still_works():
    """Migrated v1 trap cases still use _CASE_TESTS dispatch."""
    case = get_case("l3_state_pipeline", cases_file="cases_v2.json")
    # This should route through _CASE_TESTS, not tests_v2/
    ...

def test_no_case_returns_0_5():
    """No case should score 0.5 'no test defined' in the v2 set."""
    cases = load_cases(cases_file="cases_v2.json")
    for case in cases:
        buggy = load_buggy_code(case)
        result = exec_evaluate(case, wrap_as_response(buggy))
        assert result["score"] != 0.5, f"{case['id']} has no test!"

def test_reasoning_signals_exist_for_all_v2_modes():
    """Every v2 failure_mode has at least 1 reasoning signal keyword."""
    from evaluator import _REASONING_SIGNALS
    cases = load_cases(cases_file="cases_v2.json")
    modes = set(c["failure_mode"] for c in cases)
    for mode in modes:
        assert mode in _REASONING_SIGNALS, f"No signals for {mode}"
```

### 4B. End-to-End Plumbing Test

```python
def test_full_pipeline_v2_case():
    """One v2 case through the entire pipeline: load → prompt → mock LLM → eval → log."""
    init_run_log("test-model")
    case = get_case("alias_config_a", cases_file="cases_v2.json")
    cid, cond, ev = run_single(case, "test-model", "baseline")

    # Verify the full chain worked
    assert cid == "alias_config_a"
    assert cond == "baseline"
    assert "pass" in ev
    assert "score" in ev
    assert ev["score"] != 0.5  # was actually tested, not fallback

    # Verify log was written
    log_path = get_current_log_path()
    assert log_path.exists()
```

### 4C. Data Integrity Invariants (run after every real API experiment)

From the existing invariant system, extended for v2:

```
I1: len(trajectory) == total_iterations_executed
I2: converged == trajectory[-1]["pass"]
I3: iterations_to_success correct or null
I4: num_retries == total_attempts - 1
I5: total_model_calls == gen + critique + contract
I6: no "_valid" in logged critique
I7: contract_used matches condition
I9: critique_valid consistency
NEW I10: No case scores 0.5 (all cases have tests)
NEW I11: All v2 failure_modes have reasoning signals
NEW I12: V1 trap cases still route through _CASE_TESTS
```

---

## 5. Implementation Order (Safe Sequence)

```
PHASE A: V2 Bridge (unblock v2 cases) — CRITICAL PATH
  A1. Add --cases flag to runner.py                              [5 lines]
  A2. Add _load_v2_test() bridge in exec_eval.py                [20 lines]
  A3. Add reasoning signals for 10 v2 failure_modes              [30 lines]
  A4. Add fail-fast warning for score=0.5                        [3 lines]
  A5. Write tests/test_v2_bridge.py                              [80 lines]
  A6. Run: pytest tests/ → all pass (234 old + ~10 new)
  A7. Smoke: runner.py --cases cases_v2.json --model gpt-4o-mini
            --conditions baseline --case-id alias_config_a       [1 API call]

PHASE B: V1 Trap Migration
  B1. Enrich 6 trap cases with v2 metadata fields                [60 lines JSON]
  B2. Add to cases_v2.json as v1_trap family                     [merge]
  B3. Verify trap cases still evaluate correctly                 [test]
  B4. Run: validate_cases_v2.py → 51/51 pass

PHASE C: Calibration Run (BEFORE building more infrastructure)
  C1. Baseline on full v2: 51 cases × gpt-4o-mini               [51 API calls]
  C2. Baseline on full v2: 51 cases × gpt-5-mini                [51 API calls]
  C3. Analyze: pass rate by level (A/B/C/D)
  C4. If Level A < 50% pass → cases too hard, adjust
  C5. If Level C > 30% pass → cases too easy, adjust
  C6. STOP if calibration fails. Fix cases before proceeding.

PHASE D: Failure Classifier + Adaptive Retry
  D1. failure_classifier.py + tests                              [200 lines]
  D2. retry_harness.py upgrades (use_adaptive, all new fields)   [120 lines]
  D3. runner.py: add retry_adaptive                              [5 lines]
  D4. Update existing tests + add new tests                      [80 lines]
  D5. Run: pytest tests/ → all pass

PHASE E: Smoke Test (Real API)
  E1. 3 cases × 3 conditions × gpt-4o-mini:
      alias_config_a (easy), partial_rollback_c (hard), l3_state_pipeline (trap)
      baseline, retry_no_contract, retry_adaptive
  E2. Inspect logs: all new fields present
  E3. Verify classifier produces varied outputs
  E4. Verify adaptive hints appear in retry prompts (k>0 only)
  E5. Run data integrity invariants I1-I12 on logs

PHASE F: Analysis Scripts + Config
  F1. scripts/shadow_analysis.py                                 [150 lines]
  F2. ablation_config.yaml + scripts/run_ablation_config.py      [80 lines]
  F3. Test shadow analysis on smoke test data

PHASE G: Go/No-Go
  G1. All tests pass (300+)
  G2. Smoke test clean
  G3. Calibration data validates difficulty gradient
  G4. Shadow analysis produces valid output
  G5. No fail-fast triggers
  → GO or NO-GO decision

PHASE H: Full Ablation
  H1. 51 cases × 5 conditions × 2 models
      (baseline, repair_loop, retry_no_contract, retry_with_contract, retry_adaptive)
  H2. Monitor for anomalies
  H3. Run shadow_analysis.py
  H4. Run data integrity invariants
  H5. Generate analysis report
```

---

## 6. Experiment Spec (Full Ablation)

**Models:** gpt-4o-mini, gpt-5-mini
**Conditions (5):** baseline, repair_loop, retry_no_contract, retry_with_contract, retry_adaptive
**Cases (51):** 45 v2 + 6 migrated v1 traps

**Call estimate:**
- baseline: 51 × 2 = 102
- repair_loop: 51 × 2 × 2 = 204 max
- retry_no_contract: 51 × 2 × 9 = 918 max
- retry_with_contract: 51 × 2 × 10 = 1020 max
- retry_adaptive: 51 × 2 × 9 = 918 max
- **Total: ~600 realistic, ~3162 worst case**

**Hypotheses:**

| # | Hypothesis | Test |
|---|---|---|
| H1 | Level A ≈ Heuristic for 4o-mini (>60% baseline) | Phase C calibration |
| H2 | Level C ≈ CSF (retry doesn't converge) | Phase H: convergence by level |
| H3 | Level D (traps) = 100% REI (trap compliance) | Phase H: REI rate on trap cases |
| H4 | CGE helps REI but not CSF | Phase H: CGE delta by regime |
| H5 | retry_adaptive > retry_no_contract on REI | Phase H: conditional comparison |
| H6 | error_entropy low for REI, high for CSF | Phase H: entropy by regime |
| H7 | bug_pattern_class predicts regime | Phase H: regime × pattern cross-tab |

---

## 7. Risks and Anti-Patterns

### DO NOT

1. **Do NOT run the ablation before calibration (Phase C).** If v2 cases are miscalibrated, the entire experiment is wasted.

2. **Do NOT mix v1 and v2 data in analysis.** V1 ablation data (19 conditions × 3 models) is for the original 18 cases. V2 data is for the new 51 cases. Analyze separately.

3. **Do NOT skip the bridge tests (Phase A5).** The score=0.5 false positive is the most dangerous silent failure — it makes untested cases look "partially correct."

4. **Do NOT add more conditions.** 5 conditions × 51 cases × 2 models is already 500+ calls minimum. Each additional condition costs ~100+ calls.

5. **Do NOT build Phase 2 cases (100+) before Phase 1 is validated.** 51 cases is enough for all planned analyses.

6. **Do NOT over-refine regime classification.** The current heuristic is good for exploratory work. Upgrade only for paper claims, using experimental data.

### WATCH FOR

- **V2 Level C cases may cause syntax errors** (multi-file concatenation). Monitor score=0.0 rate.
- **Model non-determinism:** Plan for ≥2 replications on key conditions.
- **Token limits on trap cases** (4-5 files). Monitor for truncation.
- **Classifier collapse:** If one failure type dominates >90%, the adaptive hints are not differentiating.

---

## 8. File Change Summary

| Phase | File | Action | Lines |
|---|---|---|---|
| A | runner.py | MODIFY: --cases flag | 5 |
| A | exec_eval.py | MODIFY: _load_v2_test bridge | 20 |
| A | evaluator.py | MODIFY: add 10 v2 reasoning signal sets | 30 |
| A | exec_eval.py | MODIFY: score=0.5 warning | 3 |
| A | tests/test_v2_bridge.py | CREATE | 80 |
| B | cases_v2.json | MODIFY: add 6 trap cases | 60 (JSON) |
| D | failure_classifier.py | CREATE | 120 |
| D | tests/test_failure_classifier.py | CREATE | 80 |
| D | retry_harness.py | MODIFY: adaptive + all new fields | 120 |
| D | tests/test_retry_harness.py | MODIFY: 10 new tests + renames | 60 |
| D | runner.py | MODIFY: retry_adaptive | 5 |
| F | scripts/shadow_analysis.py | CREATE | 150 |
| F | ablation_config.yaml | CREATE | 30 |
| F | scripts/run_ablation_config.py | CREATE | 50 |
| **Total** | | | **~810 new/modified lines** |
