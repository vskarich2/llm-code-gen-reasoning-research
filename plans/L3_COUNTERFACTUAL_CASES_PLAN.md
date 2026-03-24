# L3 Counterfactual Cases — Implementation Plan

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 5 new L3 cases extending the V2 benchmark
**Compatible with:** cases_v2.json schema, retry_harness.py, LEG evaluation module, CGE (contract.py + diff_gate.py), validate_cases_v2.py

---

## 0. What Makes These Cases L3

Every case in this plan requires the model to apply a **but-for test**: *"If step X had not occurred, would invariant Y still hold?"*

This is distinct from L2 (which asks *"What happens if I apply change X?"*) because the model must:
1. Consider the actual execution (world where X is present)
2. Construct an alternative world (X absent or modified)
3. Predict the outcome in the alternative world
4. Compare both worlds to establish **causal necessity**

The model cannot solve these cases by forward-tracing a single proposed change. It must evaluate whether an **existing** step is necessary by reasoning about its absence.

---

## 1. Repo Architecture

### Directory Structure

```
T3_code_generation_MVP/
  code_snippets_v2/
    overdetermination/          # Case 1
      writer_a.py
      writer_b.py
      store.py
      api.py
    config_shadowing/           # Case 2
      defaults.py
      env_config.py
      runtime_config.py
      service.py
    cache_warmup/               # Case 3
      cache.py
      loader.py
      warmup.py
      api.py
    metric_attribution/         # Case 4
      collector.py
      emitter.py
      pipeline.py
      reporter.py
    commit_gate/                # Case 5
      state.py
      reducers.py
      selectors.py
      pipeline.py
      api.py

  tests_v2/
    test_overdetermination.py
    test_config_shadowing.py
    test_cache_warmup.py
    test_metric_attribution.py
    test_commit_gate.py

  reference_fixes/
    overdetermination.py
    config_shadowing.py
    cache_warmup.py
    metric_attribution.py
    commit_gate.py
```

### Per-Case File Counts

| Case | Files | Lines (est.) | L3 Subtype |
|---|---|---|---|
| overdetermination | 4 | ~120 | Overdetermination |
| config_shadowing | 4 | ~130 | Structural vs contingent |
| cache_warmup | 4 | ~110 | Temporal/path dependence |
| metric_attribution | 4 | ~120 | Causal attribution |
| commit_gate | 5 | ~140 | But-for causation (adapted from V1 l3_state_pipeline) |

---

## 2. Test Design (Per Case)

### Case 1: Overdetermination — Dual Writer Masking

**Scenario:** Two independent writers (`writer_a` and `writer_b`) both write the same key to a shared store. The task says to "remove the redundant writer." Both writers produce the same value, so removing either one individually doesn't break the test — the other masks the absence.

**Bug:** The code has a subtle difference: `writer_a` computes the value fresh (correct), `writer_b` uses a cached value (potentially stale). The task asks which writer to remove, and the model must determine which is **causally necessary** — i.e., but for which writer, would the store contain stale data?

#### a. Factual Test
- Both writers run. Store contains correct value. Test passes.
- The observable behavior is the same regardless of which writer runs last.

#### b. Counterfactual Tests (TWO tests, one per world)
- **World A (writer_a removed):** Only `writer_b` writes. Store contains cached/stale value. Test FAILS — stale data detected.
- **World B (writer_b removed):** Only `writer_a` writes. Store contains fresh value. Test PASSES.

The model must determine: `writer_a` is causally necessary (but-for `writer_a`, data is stale). `writer_b` is NOT causally necessary (but-for `writer_b`, data is still correct).

#### c. Failure Mode
Baseline: model removes `writer_a` (the one that looks "redundant" because it does extra work — recomputation vs cache). This is the overdetermination trap: both writes succeed, so naive analysis says either can be removed.

#### d. Success Criteria
Model removes `writer_b` (the cached writer) and keeps `writer_a` (the fresh writer). Test checks that store value is fresh after the retained writer runs.

#### e. LEG Failure Type
`HIDDEN_DEPENDENCY` — the dependency between writer_a's fresh computation and the store's correctness is masked by writer_b's presence.

---

### Case 2: Config Shadowing — Structural vs Contingent Cause

**Scenario:** Configuration is loaded from three sources in priority order: `runtime_config` > `env_config` > `defaults`. The task reports that "the default timeout is wrong" and asks to fix it.

**Bug:** The default timeout in `defaults.py` IS wrong (set to 5 instead of 30). But `env_config.py` ALSO sets timeout to 30, shadowing the bad default. If the model fixes the default, the system still works (correct by accident, via shadowing). But if someone later removes the env config, the bug resurfaces.

The model must determine: is the default the **structural cause** (it's wrong in the source of truth) or only a **contingent cause** (the env override masks it)?

#### a. Factual Test
- All three config sources active. `get_timeout()` returns 30 (from env override). Test passes.

#### b. Counterfactual Tests
- **World A (env_config removed):** `get_timeout()` returns 5 (bad default exposed). Test FAILS.
- **World B (defaults fixed to 30, env_config removed):** `get_timeout()` returns 30 (from fixed default). Test PASSES.
- **World C (defaults fixed to 30, env_config present):** Same result as factual. Test PASSES.

The model must fix the default (structural cause) even though the system currently works (contingent masking by env).

#### c. Failure Mode
Baseline: model sees `get_timeout()` returns 30 and concludes "no bug" or "just update the default" without understanding that the env config is the contingent cause that masks it.

#### d. Success Criteria
Model changes `defaults.py` to set timeout=30. The test verifies correctness BOTH with and without the env override.

#### e. LEG Failure Type
`PARTIAL_STATE_UPDATE` — the default is partially correct (masked by env) but structurally wrong.

---

### Case 3: Cache Warmup — Temporal/Path Dependence

**Scenario:** A cache is warmed by `warmup.py` during startup. The `api.py` reads from cache. A `loader.py` loads data from source. The warmup path and the loader path produce the same data, but the warmup writes to cache BEFORE the loader validates data. If warmup runs first, stale/invalid data is cached. If loader runs first, valid data is cached.

**Bug:** The system currently works because in production, loader runs first (by convention). But the warmup function writes to cache unconditionally, and if warmup ever runs first (e.g., during tests or restart), it caches unvalidated data.

The model must determine: is the current correctness **path-dependent** (depends on execution order) or **structurally guaranteed** (order-independent)?

#### a. Factual Test (loader-first order)
- Loader validates and caches data. Warmup runs but data is already cached (no-op). API reads correct data. Test passes.

#### b. Counterfactual Test (warmup-first order)
- Warmup writes unvalidated data to cache. Loader runs but cache hit prevents re-loading. API reads unvalidated data. Test FAILS.

The model must determine: the current correctness is but-for the execution order. But for loader running first, the cache would contain bad data.

#### c. Failure Mode
Baseline: model sees the system works and concludes "no bug." Or model adds validation to warmup (correct fix) but only because it traces the warmup path, not because it reasons about path dependence.

#### d. Success Criteria
Model adds validation to warmup (so warmup writes valid data regardless of order), OR adds a check in warmup that skips if loader hasn't run yet. Test runs both orderings and verifies correctness in both.

#### e. LEG Failure Type
`TEMPORAL_ORDERING` — the bug is order-dependent.

---

### Case 4: Metric Attribution — Logging Order

**Scenario:** A metrics pipeline has a `collector` (gathers raw data), an `emitter` (publishes events), and a `reporter` (generates summary). The pipeline processes items and both emits events and records metrics. The task reports "metric totals are wrong" and asks to fix.

**Bug:** `emitter.emit()` and `collector.record()` are called in the wrong order. `emit()` reads from `collector.get_total()`, but `record()` hasn't run yet for the current item, so `emit()` publishes the PREVIOUS total (off-by-one-item). The final total after all items is correct (last record runs, then emit reads it), so aggregate tests pass but per-event attribution is wrong.

The model must determine: is `record()` causally necessary BEFORE `emit()` for each item? But for `record()` preceding `emit()`, would per-event metrics be correct?

#### a. Factual Test (aggregate)
- After all items: `reporter.get_total()` returns correct sum. Test passes.

#### b. Counterfactual Test (per-event attribution)
- For each event: `event.total_at_time` must equal the running sum including the current item. Test FAILS because emit reads pre-record total.

The model must apply the but-for test per-item: but for record() preceding emit(), would each event's total be correct?

#### c. Failure Mode
Baseline: model sees aggregate total is correct and concludes "no bug." Or model moves `emit()` but doesn't understand WHY the ordering matters (per-event vs aggregate attribution).

#### d. Success Criteria
Model reorders to `record()` before `emit()` within the per-item loop. Per-event totals match running sum.

#### e. LEG Failure Type
`TEMPORAL_ORDERING` — the but-for question is about ordering, not presence/absence.

---

### Case 5: Commit Gate — But-For Causation (Adapted from V1)

**Scenario:** Adapted from `l3_state_pipeline` (the only confirmed L3 case in the current benchmark). A state pipeline has `stage()→commit()→freeze_view()`. The task claims "commit() and freeze_view() are redundant steps that can be removed."

**Bug:** Neither step is redundant. `commit()` is causally necessary for `get_committed_total()` (sets `frozen=True` gate). The stage/commit separation is causally necessary for `preview()` (which calls stage without commit). The model must apply TWO but-for tests.

This is a clean reimplementation of the V1 case with the V2 test infrastructure (deterministic tests, state isolation, retry-safe).

#### a. Factual Test
- Full pipeline: `stage→commit→freeze_view`. `get_committed_total()` returns sum. `preview()` returns uncommitted view. Both pass.

#### b. Counterfactual Tests (TWO)
- **But-for commit:** Remove `commit()`. `frozen` stays `False`. `get_committed_total()` returns `None`. Test FAILS.
- **But-for separation:** Merge `stage+commit` into one call. `preview()` now sets `frozen=True` as side effect. Preview behavior changes. Test FAILS.

#### c. Failure Mode
Baseline: model removes `commit()` (it "looks redundant" because stage already writes data) or merges stage+commit (they "do similar things").

#### d. Success Criteria
Model keeps all three steps intact and explains why each is necessary for a specific downstream consumer.

#### e. LEG Failure Type
`INVARIANT_VIOLATION` — the but-for test reveals that removing steps violates downstream invariants.

---

## 3. Contract Schema Design

### Standard L3 Contract Format

L3 cases extend the existing CGE contract schema with counterfactual-specific fields:

```json
{
    "root_cause": "string — the causal relationship being tested",
    "must_change": ["file::function — functions the model MAY modify"],
    "must_not_change": ["file::function — functions that must remain intact"],
    "required_effects": ["from ALLOWED_EFFECTS vocabulary"],

    "counterfactual_contract": {
        "causal_variable": "the step/function whose necessity is being tested",
        "but_for_test": "if {causal_variable} were absent, would {invariant} still hold?",
        "expected_answer": "NO — {causal_variable} is causally necessary",
        "invariant_held_fixed": "the downstream invariant that must not change",
        "competing_world": "description of the alternative execution without the causal variable"
    },

    "invariants": ["precise invariant statements"]
}
```

### Full Example: commit_gate

```json
{
    "root_cause": "commit() and freeze_view() appear redundant but are each causally necessary for different downstream consumers",
    "must_change": [],
    "must_not_change": [
        "pipeline.py::process_batch",
        "state.py::make_state",
        "selectors.py::get_committed_total",
        "api.py::preview"
    ],
    "required_effects": ["preserve_effect_order"],
    "counterfactual_contract": {
        "causal_variable": "commit()",
        "but_for_test": "if commit() were removed, would get_committed_total() still return the correct sum?",
        "expected_answer": "NO — commit() sets frozen=True which is a precondition for get_committed_total()",
        "invariant_held_fixed": "get_committed_total() returns sum of stable entries",
        "competing_world": "stage() runs but frozen stays False; get_committed_total() returns None"
    },
    "invariants": [
        "get_committed_total() returns correct sum after process_batch()",
        "preview() returns uncommitted view without setting frozen=True"
    ]
}
```

### Compatibility with ALLOWED_EFFECTS

The existing `ALLOWED_EFFECTS` vocabulary in `contract.py` is sufficient. L3 cases primarily use:
- `preserve_effect_order` — step ordering is causally necessary
- `guard_side_effect` — step presence is causally necessary

No new effects needed. The `counterfactual_contract` field is an EXTENSION, not a replacement — it sits alongside the existing fields.

---

## 4. Retry Loop Prompt Design

### System Prompt (unchanged from retry_harness.py)

The existing retry harness system prompt works for L3 cases. No changes needed.

### User Prompt — Initial (k=0)

Uses the existing `_build_initial_prompt(case)` from retry_harness.py. The task string in the case definition is the only input.

### User Prompt — Retry (k>0)

Extended from `_build_retry_prompt()` to include counterfactual feedback when the test provides it:

```python
def _build_retry_prompt_l3(case, original_code, prev_code, test_output,
                            critique, contract, counterfactual_feedback):
    parts = [case["task"]]
    parts.append(f"\n=== Original Code ===\n{original_code}")
    parts.append(f"\n=== Your Previous Attempt ===\n```python\n{prev_code}\n```")
    parts.append(f"\n=== Test Results (FAILED) ===\n{test_output}")

    # L3-specific: counterfactual test feedback
    if counterfactual_feedback:
        parts.append(f"\n=== Counterfactual Analysis ===")
        for cf in counterfactual_feedback:
            parts.append(f"- Without '{cf['removed_step']}': {cf['outcome']}")

    if critique:
        parts.append(f"\n=== Diagnosis ===\n{json.dumps(critique, indent=2)}")
    if contract:
        parts.append(f"\n=== Your Intended Fix ===\n{json.dumps(contract, indent=2)}")

    parts.append("\nDo NOT remove or merge steps unless you can prove they are NOT causally necessary.")
    parts.append("For each step you consider removing, ask: 'If this step were absent, would all downstream consumers still work?'")
    parts.append("Return the complete updated code.")
    return "\n".join(parts)
```

**Key design decision:** The retry prompt includes the counterfactual test results ("Without commit(): get_committed_total returns None"). This gives the model the but-for evidence it needs without doing the reasoning for it — the model still must decide what to do with the evidence.

### Compatibility with LEG Evaluation

The retry prompt does NOT change how reasoning is extracted or evaluated. The LEG blind evaluator receives the model's reasoning text and the test failure — same interface as all other cases. The `counterfactual_feedback` appears in the prompt (input) but is not part of the reasoning output.

The LEG failure types that apply to L3 cases:
- `INVARIANT_VIOLATION` — model removes a causally necessary step, breaking an invariant
- `TEMPORAL_ORDERING` — model reorders causally dependent steps
- `HIDDEN_DEPENDENCY` — model misses a masked dependency (overdetermination)
- `PARTIAL_STATE_UPDATE` — model fixes one world but not the structural cause

All are in the existing `FAILURE_TYPES` enum. No new types needed.

---

## 5. CGE / Diff Validation Plan

### How Diffs Are Evaluated

L3 cases use the existing `diff_gate.validate()` from `diff_gate.py` with the standard 6 checks:

1. `_check_must_change` — verifies model modified the right functions (or in L3 cases, kept them intact)
2. `_check_must_not_change` — L3 cases have LARGE `must_not_change` lists (the model should NOT remove pipeline steps)
3. `_check_required_effects` — `preserve_effect_order` check
4. `_check_ordering` — ordering constraints
5. `_check_retry_safety` — not typically relevant for L3
6. `_check_rollback` — not typically relevant for L3

### L3-Specific Validation: Rejection Rules

| Rejection Signal | Detection | Meaning |
|---|---|---|
| Removed causally necessary function | `must_not_change` function absent from output | Model failed the but-for test — removed a necessary step |
| Merged separated functions | Two `must_not_change` functions replaced by one | Model conflated structurally separate operations |
| Added unnecessary wrapper | New function wraps existing steps without changing behavior | Model over-engineered without understanding causality |
| Fixed the wrong world | Counterfactual test passes but factual test fails | Model addressed the alternative scenario, not the actual bug |

### Compatibility with Existing Diff Gate

No changes to `diff_gate.py` needed. The existing `must_not_change` check covers the primary L3 validation (don't remove necessary steps). The `counterfactual_contract` field is metadata for analysis — it is not checked by the diff gate at runtime.

---

## 6. Scoring + Metrics

### Pass/Fail Criteria

| Criterion | Definition |
|---|---|
| **Full pass** | Both factual test AND all counterfactual tests pass |
| **Factual-only pass** | Factual test passes but at least one counterfactual test fails (model preserved behavior but doesn't understand why) |
| **Full fail** | Factual test fails |

### Scores

| Score | Condition |
|---|---|
| 1.0 | Full pass — both worlds correct |
| 0.7 | Factual-only pass — system works but structural cause not addressed |
| 0.5 | Code runs, invariant fails (silent failure) |
| 0.2 | Code errors but reasoning identifies the causal necessity |
| 0.0 | Code errors, no correct reasoning |

The 0.7 tier is new and specific to L3: it captures cases where the model's fix is **contingently correct** (works in the current configuration) but **structurally incomplete** (would break if the masking cause were removed). This directly measures whether the model reasons about causal necessity.

### Retry Count Metric

Standard from retry_harness.py: `iterations_to_success`, `total_iterations_executed`, `convergence_slope`.

### Causal Correctness Metric (NEW)

```python
def _compute_causal_correctness(case, trajectory):
    """Did the model address the structural cause, not just the contingent one?

    Returns float in [0, 1]:
      1.0 = structural cause fixed (all counterfactual tests pass)
      0.5 = contingent fix only (factual passes, counterfactual fails)
      0.0 = nothing fixed
    """
    last = trajectory[-1]
    if not last["pass"]:
        return 0.0
    # Run counterfactual tests
    cf_results = last.get("counterfactual_results", {})
    if not cf_results:
        return 1.0  # no counterfactual tests → standard pass
    all_cf_pass = all(cf_results.values())
    if all_cf_pass:
        return 1.0
    return 0.5
```

Logged in the summary as `causal_correctness`.

### LEG Integration

LEG metrics are computed identically to all other cases:
- `leg_true` from blind evaluator verdict + classifier agreement + test failure
- `leg_coupling` / `leg_execution` from alignment (if retry_alignment condition)
- `leg_keyword_only` from keyword signal (backward compat)

The `causal_correctness` metric is ORTHOGONAL to LEG — it measures whether the fix addresses structural vs contingent causation, while LEG measures whether reasoning identified the failure mechanism.

---

## 7. Failure Mode Taxonomy

| Case | L3 Subtype | Expected Model Mistake | LEG Failure Type |
|---|---|---|---|
| **overdetermination** | Overdetermination | Removes the causally necessary writer (masked by redundant writer) | HIDDEN_DEPENDENCY |
| **config_shadowing** | Structural vs contingent | Fixes only the contingent cause or declares "no bug" because system works | PARTIAL_STATE_UPDATE |
| **cache_warmup** | Temporal/path dependence | Doesn't test alternative execution orders; assumes current order is guaranteed | TEMPORAL_ORDERING |
| **metric_attribution** | Causal attribution | Sees correct aggregate total and misses per-event ordering requirement | TEMPORAL_ORDERING |
| **commit_gate** | But-for causation | Removes "redundant" commit() without checking if downstream selectors need it | INVARIANT_VIOLATION |

### Predicted Regime Distribution

| Model | overdetermination | config_shadowing | cache_warmup | metric_attribution | commit_gate |
|---|---|---|---|---|---|
| nano | CSF-L3 | CSF-L3 | CSF-L3 | CSF-L3 | CSF-L3 |
| 4o-mini | CSF-L3 | REI or CSF-L3 | REI | REI | CSF-L3 |
| 5-mini | CSF-L3 | CSF-L3 | CSF-L3 | CSF-L3 | CSF-L3 |

These are hypotheses. The key prediction: L3 cases should show **higher CSF rates and lower REI rates** than L2 (deep) cases, because the but-for reasoning required is qualitatively harder than forward simulation.

---

## 8. Implementation Roadmap

### Phase 1: Infrastructure (no new code in retry_harness or runner)

```
Step 1: Create 5 case directories under code_snippets_v2/
Step 2: Write buggy code files for each case (4-5 files per case)
Step 3: Write reference fixes (1 file per case — the primary fix file)
Step 4: Write test files in tests_v2/ with both factual and counterfactual tests
Step 5: Write CASE_DOC.md for each case
Step 6: Run validate_cases_v2.py on all 5 — all 6 checks must pass
```

### Phase 2: Case Metadata

```
Step 7: Add 5 entries to cases_v2.json with full schema
        - causal_depth: "L3"
        - New field: counterfactual_contract (the but-for test spec)
        - ground_truth_bug with L3-specific type labels
Step 8: Update MASTER_CASE_PEARL_MAPPING.md with 5 new L3 entries
```

### Phase 3: Retry Prompt Extension (minimal)

```
Step 9: Add _build_retry_prompt_l3 to retry_harness.py
        - Only called when case has counterfactual_contract field
        - Falls back to standard _build_retry_prompt otherwise
        - ~20 lines of new code
Step 10: Add counterfactual test result extraction to _safe_evaluate
        - Tests return both factual and counterfactual results
        - Counterfactual results logged in trajectory entry
        - ~10 lines
```

### Phase 4: Scoring Extension (minimal)

```
Step 11: Add _compute_causal_correctness to retry_harness.py
        - Logged in summary alongside existing metrics
        - ~15 lines
Step 12: Add 0.7 score tier to _safe_evaluate for factual-only passes
        - ~5 lines
```

### Phase 5: Validation

```
Step 13: Run baseline experiment: 5 cases × 2 models (nano, 4o-mini)
Step 14: Verify LEG evaluation fires correctly (blind evaluator + classifier)
Step 15: Verify causal_correctness metric distinguishes structural from contingent fixes
Step 16: Check that retry loop feedback includes counterfactual results
```

### Dependencies

```
Phase 1-2: No dependencies on other work. Can start immediately.
Phase 3-4: Requires retry_harness.py access. ~50 lines total change.
Phase 5: Requires API keys for model calls.
```

### Estimated Output

- 5 case directories with 4-5 Python files each (~22 files)
- 5 test files
- 5 reference fixes
- 5 CASE_DOC.md files
- 5 entries in cases_v2.json
- ~50 lines of retry_harness.py changes
- ~600 lines of new benchmark code total

---

## 9. Compatibility Checklist

| System | Compatible? | Notes |
|---|---|---|
| `cases_v2.json` schema | Yes | New `counterfactual_contract` field is additive; all existing fields preserved |
| `validate_cases_v2.py` | Yes | Standard 6 checks work. Tests include both factual and counterfactual assertions |
| `retry_harness.py` | Yes with ~50 lines | Counterfactual feedback in retry prompt; causal_correctness metric |
| `runner.py` | Yes | No changes — cases load through existing `load_cases()` |
| `LEG evaluation module` | Yes, no changes | Blind evaluator receives reasoning+code+error. Failure types from existing enum |
| `failure_classifier.py` | Yes, no changes | Classifies errors from existing error categories |
| `diff_gate.py` | Yes, no changes | `must_not_change` covers L3 validation (don't remove necessary steps) |
| `contract.py` | Yes | `counterfactual_contract` is a new field; existing parsing handles unknown fields gracefully |
| `MASTER_CASE_PEARL_MAPPING.md` | Needs update | Add 5 new L3 entries to §3 and flat table |
