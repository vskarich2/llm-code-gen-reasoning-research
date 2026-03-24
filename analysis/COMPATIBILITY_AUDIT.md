# T3 System Compatibility Audit: Cases × Conditions × Data

**Date:** 2026-03-24

---

## 1. Degrees of Freedom

The system has 4 independent axes that combine to produce an experiment:

| Axis | Options | Count |
|---|---|---|
| **Cases** | v1 (37) + v2 (45) + extensions (7) = 89 total in cases files | 89 |
| **Conditions** | 22 registered in ALL_CONDITIONS | 22 |
| **Models** | Any OpenAI model string | unbounded |
| **Eval model** | LEG_EVAL_MODEL (currently gpt-5-mini) | 1 |

Not all combinations are valid. This audit documents which ones silently degrade.

---

## 2. Condition Categories

### Category A: Universal (work on ANY case, no case-specific data needed)

| Condition | Mechanism | Safe for all cases |
|---|---|---|
| baseline | Terse prompt, no augmentation | YES |
| structured_reasoning | Generic reasoning template | YES |
| free_form_reasoning | Generic reasoning template | YES |
| branching_reasoning | Generic reasoning template | YES |
| contract_gated | Multi-step CGE flow | YES |
| retry_no_contract | Retry loop with test feedback | YES |
| retry_with_contract | Retry + contract context | YES |
| retry_adaptive | Retry + failure-type hints | YES |
| retry_alignment | Retry + plan-code alignment | YES |

**These 9 conditions are safe on all 89 cases.**

### Category B: Case-Specific (need per-case data — SILENTLY DEGRADE if missing)

| Condition | Required Data | Where Defined | Cases With Data |
|---|---|---|---|
| diagnostic | `DIAGNOSTIC_NUDGES[failure_mode]` | prompts.py | **6/89 (7%)** |
| guardrail | `GUARDRAIL_NUDGES[failure_mode]` | prompts.py | **6/89 (7%)** |
| guardrail_strict | `GUARDRAIL_NUDGES[failure_mode]` + `hard_constraints` | prompts.py + cases.json | **6/89 (7%)** |
| repair_loop | `DIAGNOSTIC_NUDGES[failure_mode]` (uses diagnostic for attempt 1) | prompts.py | **6/89 (7%)** |
| counterfactual | `CASE_TO_OPERATORS[case_id]` | nudges/mapping.py | **14/89 (16%)** |
| reason_then_act | `CASE_TO_OPERATORS[case_id]` | nudges/mapping.py | **14/89 (16%)** |
| self_check | `CASE_TO_OPERATORS[case_id]` | nudges/mapping.py | **14/89 (16%)** |
| counterfactual_check | `CASE_TO_OPERATORS[case_id]` | nudges/mapping.py | **14/89 (16%)** |
| test_driven | `CASE_TO_OPERATORS[case_id]` | nudges/mapping.py | **14/89 (16%)** |
| scm_descriptive | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |
| scm_constrained | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |
| scm_constrained_evidence | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |
| scm_constrained_evidence_minimal | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |
| evidence_only | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |
| length_matched_control | `get_scm(case_id)` | scm_data.py | **4/89 (4%)** |

---

## 3. CRITICAL: Silent No-Op Behavior

### What happens when case-specific data is missing

**The condition silently returns the IDENTICAL prompt as baseline.** No error, no warning, no log entry. The experiment records the condition as "diagnostic" but the model received exactly the same prompt as "baseline."

This means: if you run `--conditions baseline,diagnostic` on a v2 case like `alias_config_a`, both conditions produce identical prompts and identical results. The comparison is meaningless — you're comparing baseline to baseline.

### Scale of the problem

| Condition Type | Cases Affected | Silent No-Op Rate |
|---|---|---|
| diagnostic / guardrail / repair_loop | 83/89 | **93%** |
| SCM conditions (all 6) | 85/89 | **96%** |
| guardrail_strict (no hard_constraints) | 67/89 | **75%** |

### Which failure_modes have diagnostic/guardrail nudges?

Only 4 failure_modes (from the original v1 hard cases):
- HIDDEN_DEPENDENCY
- INVARIANT_VIOLATION
- STATE_SEMANTIC_VIOLATION
- TEMPORAL_CAUSAL_ERROR

**19 v2 failure_modes have NO nudges at all:** ALIASING, CACHE_ORDERING, EARLY_RETURN, FLAG_DRIFT, INDEX_MISALIGN, INIT_ORDER, MISSING_BRANCH, MUTABLE_DEFAULT, PARTIAL_ROLLBACK, PARTIAL_STATE_UPDATE, RACE_CONDITION, RETRY_DUPLICATION, SIDE_EFFECT_ORDER, SILENT_DEFAULT, STALE_CACHE, TEMPORAL_DRIFT, TEMPORAL_ORDERING, USE_BEFORE_SET, WRONG_CONDITION.

### Which cases have SCM data?

Only 4 (all from v1 originals):
- hidden_dep_multihop
- temporal_semantic_drift
- invariant_partial_fail
- l3_state_pipeline

### Which cases have CASE_TO_OPERATORS nudge mapping?

Only 14 (all from v1):
- hidden_dep_multihop, temporal_semantic_drift, invariant_partial_fail, l3_state_pipeline
- async_race_lock, idempotency_trap, cache_invalidation_order, partial_rollback_multi
- lazy_init_hazard, external_timing_dep, shared_ref_coupling, log_side_effect_order
- retry_causality, feature_flag_drift

**Zero v2 cases have nudge mappings.**

---

## 4. Cases That Are FULLY Compatible With All 22 Conditions

Only **3 cases** out of 89 have ALL data for ALL conditions:

| Case | nudge | diag | guard | scm | hard |
|---|---|---|---|---|---|
| hidden_dep_multihop | ✓ | ✓ | ✓ | ✓ | ✓ |
| invariant_partial_fail | ✓ | ✓ | ✓ | ✓ | ✓ |
| l3_state_pipeline | ✓ | ✓ | ✓ | ✓ | ✓ |

`temporal_semantic_drift` also has full data but was checked as FULL.

---

## 5. Evaluation Compatibility

### exec_eval._CASE_TESTS (v1 dispatch table)

Contains test functions for **37 v1 cases** only. Hardcoded in exec_eval.py.

### _load_v2_test (v2 dynamic loader)

Looks for `test_{difficulty}(mod)` or `test(mod)` in `tests_v2/test_{family}.py`.

**7 cases with test files that only have `test(mod)` (not `test_c` or `test_l3`):**
- config_shadowing (L3)
- commit_gate (L3)
- overdetermination (C)
- lost_update (C)
- check_then_act (C)
- ordering_dependency (C)
- false_fix_deadlock (C)

These now work after the fix to try `test()` as well as `test_{level}()`. Previously they silently scored 0.5.

### Reasoning signal detection

`evaluator._REASONING_SIGNALS` has keywords for these failure_modes:
- V1 originals: HIDDEN_DEPENDENCY, TEMPORAL_CAUSAL_ERROR, INVARIANT_VIOLATION, STATE_SEMANTIC_VIOLATION, RACE_CONDITION, IDEMPOTENCY_VIOLATION, CACHE_ORDERING, PARTIAL_ROLLBACK, INIT_ORDER, TIMING_DEPENDENCY, SHARED_REFERENCE, SIDE_EFFECT_ORDER, RETRY_DUPLICATION, FLAG_DRIFT
- Easy calibration: EASY_TEMPORAL, EASY_CONSERVATION, EASY_STATE_MACHINE, EASY_ALIASING
- V2 additions: ALIASING, CONSERVATION_VIOLATION, EARLY_RETURN, INDEX_MISALIGN, MISSING_BRANCH, MUTABLE_DEFAULT, PARTIAL_STATE_UPDATE, SILENT_DEFAULT, STALE_CACHE, TEMPORAL_DRIFT, USE_BEFORE_SET, WRONG_CONDITION

**Missing:** TEMPORAL_ORDERING (used by `ordering_dependency` case). This case will always have `reasoning_valid = False`.

---

## 6. Silent Failure Catalog

### SILENT-01: Diagnostic/guardrail conditions produce baseline prompt on 93% of cases

**Severity:** HIGH — makes condition comparisons meaningless
**Trigger:** Any v2 case + diagnostic/guardrail/repair_loop condition
**Behavior:** Returns `base` unchanged because `DIAGNOSTIC_NUDGES[failure_mode]` returns empty string
**Impact:** Experiment shows "diagnostic had no effect" — but the condition was never actually applied
**Fix:** Add diagnostic nudges for all 19 v2 failure_modes, OR restrict experiments to cases with nudge data, OR crash when nudge is missing

### SILENT-02: SCM conditions produce baseline prompt on 96% of cases

**Severity:** HIGH — same as SILENT-01
**Trigger:** Any non-original-4 case + any SCM condition
**Behavior:** `get_scm(case_id)` returns None, `build_scm_*` returns `base` unchanged
**Fix:** Add SCM data for all cases, OR restrict, OR crash

### SILENT-03: guardrail_strict with no hard_constraints

**Severity:** MEDIUM — guardrail_strict degrades to guardrail (which itself may be no-op per SILENT-01)
**Trigger:** 75% of cases have no `hard_constraints`
**Behavior:** `apply_guardrail_strict(case_id, base, [])` — empty constraints list
**Fix:** Add hard_constraints to v2 cases, OR restrict

### SILENT-04: Missing TEMPORAL_ORDERING reasoning signals

**Severity:** LOW — only 1 case (`ordering_dependency`)
**Trigger:** `failure_mode = TEMPORAL_ORDERING`
**Behavior:** `_detected_correct_reasoning` always returns False
**Impact:** `reasoning_valid` and `reasoning_action_gap` always False for this case. Does NOT affect LEG_true.
**Fix:** Add `"TEMPORAL_ORDERING": [...]` to `_REASONING_SIGNALS`

### SILENT-05: retry_adaptive uses classifier for hint selection — classifier may return UNKNOWN

**Severity:** LOW — falls back to DEFAULT hint
**Trigger:** Any case where classifier returns UNKNOWN
**Behavior:** `ADAPTIVE_HINTS["UNKNOWN"]` = generic hint (same as DEFAULT)
**Impact:** Adaptive condition becomes non-adaptive for that attempt. Logged correctly.

### SILENT-06: Duplicate data from the first ablation run (single-pool executor)

**Severity:** MEDIUM — affects gpt-5-mini v3 logs
**Trigger:** The initial single-pool ablation wrote some nano/4o-mini data into 5-mini's log file before being killed
**Behavior:** 5-mini log has 336 summaries instead of 306 — 30 extra entries from other models
**Impact:** Analysis scripts that filter by `model` field are safe. Scripts that count summaries per file will overcount.
**Fix:** Filter by `record["model"]` field, not by filename.

---

## 7. Recommended Safe Condition Sets

### For V2 cases (45 original + 7 extensions):

**Safe:** baseline, structured_reasoning, free_form_reasoning, branching_reasoning, contract_gated, retry_no_contract, retry_with_contract, retry_adaptive, retry_alignment

**Unsafe (silently degrade to baseline):** diagnostic, guardrail, guardrail_strict, repair_loop, all SCM conditions, counterfactual, reason_then_act, self_check, counterfactual_check, test_driven

### For V1 original 14 hard cases:

**Safe:** All 22 conditions (these cases have full data)

### For the 4 SCM cases:

**Safe:** All 22 conditions including SCM variants

---

## 8. Data Source Summary

| Data Source | File | Cases Covered | Content |
|---|---|---|---|
| Diagnostic nudges | `prompts.py:DIAGNOSTIC_NUDGES` | 4 failure_modes | Per-failure-mode reasoning scaffold text |
| Guardrail nudges | `prompts.py:GUARDRAIL_NUDGES` | 4 failure_modes | Per-failure-mode constraint text |
| Nudge operator map | `nudges/mapping.py:CASE_TO_OPERATORS` | 14 case_ids | Case → operator name assignment |
| SCM data | `scm_data.py` | 4 case_ids | Causal graph + evidence IDs |
| Hard constraints | `cases.json / cases_v2.json` | 22/89 cases | Per-case constraint list |
| Reasoning signals | `evaluator.py:_REASONING_SIGNALS` | 30 failure_modes | Per-failure-mode keyword patterns |
| V1 test dispatch | `exec_eval.py:_CASE_TESTS` | 37 case_ids | Hardcoded test function map |
| V2 test files | `tests_v2/test_{family}.py` | 52+ case_ids | Dynamic test loader |
