# Retry Ablation — Complete Implementation Plan

**Date:** 2026-03-23
**Status:** Implementation-ready
**Prerequisite:** retry_harness.py (implemented, 68 tests passing)

This plan consolidates all design decisions from the multi-pass design sessions (v1→v4 + hardening + correctness + micro-fixes) into a single actionable document. Nothing here is new design — it's all previously approved work that hasn't been coded yet.

---

## 0. Current State (What's Already Implemented)

### Implemented and tested (68 unit tests, 3 real API smoke tests):

| Component | File | Status |
|---|---|---|
| Core retry loop (5 iterations, test feedback) | `retry_harness.py:588` | ✅ |
| `_call_critique` (structured critique via LLM) | `retry_harness.py:428` | ✅ |
| `_elicit_contract` (CGE-lite) | `retry_harness.py:469` | ✅ |
| `_safe_evaluate` (crash-proof eval wrapper) | `retry_harness.py:403` | ✅ |
| `_build_error_object` (structured errors) | `retry_harness.py:111` | ✅ |
| `_infer_failure_mode` (simple failure prediction) | `retry_harness.py:158` | ✅ |
| `_compute_diff` + `_is_stagnated` | `retry_harness.py:64,94` | ✅ |
| `_estimate_reasoning_validity` (non-circular) | `retry_harness.py:195` | ✅ |
| `_classify_outcome` / `_classify_trajectory_type` / `_classify_regime` | `retry_harness.py:234-330` | ✅ |
| `_compute_metrics` + `_compute_critique_accuracy` | `retry_harness.py:334-397` | ✅ |
| Per-iteration logging + summary logging | `retry_harness.py:519-584` | ✅ |
| Runner dispatch: `retry_no_contract`, `retry_with_contract` | `runner.py:112-115` | ✅ |
| `_extracted_code` field in exec_eval.py | `exec_eval.py:60` | ✅ |
| Parse consistency warning | `retry_harness.py:630-642` | ✅ |
| Wallclock timeout (360s total, 60s per iteration) | `retry_harness.py:617-625` | ✅ |

### NOT yet implemented:

| Component | Design Source | Status |
|---|---|---|
| **failure_classifier.py** (heuristic module) | Ablation plan §1 | ❌ |
| **`retry_adaptive` condition** (failure-type hints) | Ablation plan §2-3 | ❌ |
| **Confidence-gated hint selection** | Ablation plan §2 | ❌ |
| **`scripts/shadow_analysis.py`** | Ablation plan §4 | ❌ |
| **`ablation_config.yaml`** + run script | Ablation plan §5 | ❌ |
| **Fail-fast guards** | Ablation plan §7 | ❌ |
| **Micro-fixes** (status_sequence rename, attempt_progress, hint_used_type) | `plans/retry_ablation_final_microfixes.md` | ❌ |
| **Latent correctness signal** | Final tightening §14 | ❌ |
| **Attempt similarity detection** (SequenceMatcher upgrade) | Final tightening §11 | ❌ |
| **Classifier coverage metrics** | Final tightening §12 | ❌ |
| **error_trajectory_detailed** in summary | Final tightening §8 Fix 7 | ❌ |
| **first_pass_success / recovered_on_retry / retry_gain** | Final additions §9 | ❌ |
| **retry_effectiveness** (improved/stagnant/regressed) | Final additions §10 | ❌ |
| **failure_sequence + failure_transitions** in summary | Final tightening §3 | ❌ |
| **trajectory_failure_pattern** classification | Final tightening §19 | ❌ |
| **attempt_diversity** metric | Final tightening §20 | ❌ |

---

## 1. Implementation Plan (Ordered Steps)

### Step 1: failure_classifier.py (NEW FILE)

**Create `failure_classifier.py`** with heuristic-only classification.

```python
FAILURE_TYPES = [
    "TEMPORAL_ORDERING", "HIDDEN_DEPENDENCY", "PARTIAL_STATE_UPDATE",
    "INVARIANT_VIOLATION", "RETRY_LOGIC_BUG", "LOGGING_INCONSISTENCY",
    "CONFOUNDING_LOGIC", "EDGE_CASE_MISSED", "UNKNOWN",
]

def classify_failure(error_obj: dict, critique: dict | None) -> dict:
```

**CRITICAL: No ground truth leakage.** Classifier MUST NOT accept `case` or `case["failure_mode"]` as input. Only `error_obj` and `critique`.

**Priority rules:**
1. critique.failure_type + keyword match on root_cause/invariant_violated (conf 0.8)
2. error_obj.category mapping (conf 0.5)
3. Keyword scan on error_obj.reasons (conf 0.3)
4. Fallback → UNKNOWN (conf 0.0)

**Return schema (ALL fields always present, never null):**
```json
{
    "failure_type_final": "TEMPORAL_ORDERING",
    "critique_failure_type": "logic_error",
    "error_category": "logic",
    "matched_keywords": ["order", "before"],
    "classifier_rule_path": "rule1_critique_keyword",
    "classifier_confidence": 0.8
}
```

**Tests: `tests/test_failure_classifier.py`** — test with synthetic errors only, never case metadata.

### Step 2: Modify retry_harness.py — Add `use_adaptive` + classification + new summary fields

**Changes to `run_retry_harness` signature:**
```python
def run_retry_harness(case, model, max_iterations=5,
                      use_contract=False, use_adaptive=False):
```

**Changes inside the loop (after critique, before trajectory append):**

```python
from failure_classifier import classify_failure, FAILURE_TYPES
from difflib import SequenceMatcher

# Classification (every failed iteration)
classification = None
if not ev["pass"]:
    classification = classify_failure(error_obj, critique)

# Adaptive hint (confidence-gated)
adaptive_hint = None
hint_used_type = None
if use_adaptive and not ev["pass"] and classification:
    if classification["classifier_confidence"] >= 0.5:
        hint_used_type = classification["failure_type_final"]
        adaptive_hint = ADAPTIVE_HINTS.get(hint_used_type, ADAPTIVE_HINTS["UNKNOWN"])
    else:
        hint_used_type = "DEFAULT"
        adaptive_hint = ADAPTIVE_HINTS["UNKNOWN"]

# Attempt similarity (SequenceMatcher upgrade)
attempt_similarity = None
code_length_delta = None
if prev_code:
    attempt_similarity = round(SequenceMatcher(None, prev_code, code_k).ratio(), 3)
    code_length_delta = abs(len(code_k) - len(prev_code))

# Latent correctness signal
latent_signal = _detect_latent_signal(reasoning_k, ev["pass"])

# Attempt progress
attempt_progress = round(k / max_iterations, 3)
```

**Updated trajectory entry:**
```python
entry = {
    # ... all existing fields ...
    "classification": classification,
    "intervention": {
        "type": hint_used_type or (classification["failure_type_final"] if classification else None),
        "confidence": classification["classifier_confidence"] if classification else None,
        "applied": adaptive_hint is not None and hint_used_type != "DEFAULT",
        "hint_text": adaptive_hint,
    } if use_adaptive and not ev["pass"] else None,
    "hint_used_type": hint_used_type,
    "attempt_similarity": attempt_similarity,
    "attempt_progress": attempt_progress,
    "latent_signal": latent_signal,
}
```

**Updated stagnation check:**
```python
# Primary: similarity-based
if k > 0 and attempt_similarity and attempt_similarity > 0.95:
    consecutive_similar += 1
else:
    consecutive_similar = 0
if consecutive_similar >= 3:
    _log.warning("STAGNATION: 3x >0.95 similarity for %s", case["id"])
    break

# Secondary: existing diff + score check (kept)
if k > 0 and diff_k and _is_stagnated(diff_k, ev["score"], prev_score):
    break
```

**Updated `_build_retry_prompt`:**
```python
def _build_retry_prompt(case, original_code, prev_code, test_output,
                        critique, contract, adaptive_hint=None):
    # ... existing parts ...
    if adaptive_hint:
        parts.append(f"\n=== Hint ===\n{adaptive_hint}")
    # ... rest unchanged ...
```

**New summary fields (post-hoc):**
```python
# First-pass attribution
summary["first_pass_success"] = trajectory[0]["pass"]
summary["recovered_on_retry"] = not trajectory[0]["pass"] and trajectory[-1]["pass"]
summary["retry_gain"] = summary["recovered_on_retry"]

# Retry effectiveness
initial, final = trajectory[0]["score"], trajectory[-1]["score"]
summary["retry_effectiveness"] = {
    "improved": final > initial,
    "stagnant": final == initial and len(trajectory) > 1,
    "regressed": final < initial,
}

# Failure sequence + transitions
failed = [e for e in trajectory if not e["pass"] and e.get("classification")]
summary["failure_sequence"] = [e["classification"]["failure_type_final"] for e in failed]
summary["failure_transitions"] = _count_transitions(summary["failure_sequence"])
summary["trajectory_failure_pattern"] = _classify_failure_trajectory(summary["failure_sequence"])

# Error trajectory detailed
summary["error_trajectory_detailed"] = [
    {"category": e["error"]["category"],
     "message": e["error"]["message"][:200],
     "invariant": (e["critique"].get("invariant_violated")
                   if e.get("critique") and e.get("critique_valid") else None)}
    for e in trajectory
]

# Classifier coverage
if failed:
    confident = sum(1 for e in failed if e["classification"]["classifier_confidence"] >= 0.5)
    applied = sum(1 for e in trajectory if e.get("intervention", {}).get("applied"))
    types = Counter(e["classification"]["failure_type_final"] for e in failed)
    summary["classifier_coverage"] = {
        "total_classifications": len(failed),
        "confident_predictions": confident,
        "confident_prediction_rate": round(confident / len(failed), 3),
        "adaptive_applied_count": applied,
        "adaptive_applied_rate": round(applied / len(failed), 3) if failed else 0,
        "type_distribution": dict(types),
    }

# Latent execution gap
latent_entries = [e for e in trajectory if e.get("latent_signal", {}).get("correct_pattern_in_reasoning")]
summary["latent_execution_gap"] = {
    "latent_but_failed": sum(1 for e in latent_entries if not e["pass"]),
    "latent_and_succeeded": sum(1 for e in latent_entries if e["pass"]),
}

# Attempt diversity
similarities = [e.get("attempt_similarity") for e in trajectory[1:]
                if e.get("attempt_similarity") is not None]
summary["attempt_diversity"] = round(1.0 - sum(similarities) / len(similarities), 3) if similarities else 0.0

# Rename: trajectory_pattern → status_sequence (micro-fix #1)
summary["status_sequence"] = ["pass" if e["pass"] else "fail" for e in trajectory]
# (remove old "trajectory_pattern" key)
```

**New helper functions to add:**

```python
ADAPTIVE_HINTS = {
    "TEMPORAL_ORDERING": "Carefully check ordering of operations and when values are computed relative to modifications.",
    "HIDDEN_DEPENDENCY": "Identify any implicit dependencies or shared state that may be affected by your changes.",
    "INVARIANT_VIOLATION": "Ensure all invariants (consistency, conservation, constraints) are preserved.",
    "PARTIAL_STATE_UPDATE": "Ensure all related state variables are updated consistently, not just one component.",
    "RETRY_LOGIC_BUG": "Check for duplicated operations, missing idempotency, or incorrect retry assumptions.",
    "LOGGING_INCONSISTENCY": "Verify that logging and side effects are consistent with the intended operation order.",
    "CONFOUNDING_LOGIC": "Re-evaluate your assumptions and identify the root cause of failure.",
    "EDGE_CASE_MISSED": "Consider edge cases and boundary conditions that your fix may not handle.",
    "UNKNOWN": "Re-evaluate your assumptions and identify the root cause of failure.",
}

_LATENT_KEYWORDS = {
    "TEMPORAL_ORDERING": ["order", "before", "after", "sequence", "timing", "first"],
    "HIDDEN_DEPENDENCY": ["dependency", "import", "missing", "undefined", "hidden"],
    "INVARIANT_VIOLATION": ["invariant", "balance", "conservation", "consistent", "atomic"],
    "PARTIAL_STATE_UPDATE": ["partial", "incomplete", "all fields", "both"],
    "RETRY_LOGIC_BUG": ["retry", "duplicate", "idempotent", "once", "exactly once"],
}

def _detect_latent_signal(reasoning_k, code_passed):
    if code_passed:
        return {"correct_pattern_in_reasoning": False, "latent_reasoning_type": None}
    for ftype, keywords in _LATENT_KEYWORDS.items():
        if any(kw in reasoning_k.lower() for kw in keywords):
            return {"correct_pattern_in_reasoning": True, "latent_reasoning_type": ftype}
    return {"correct_pattern_in_reasoning": False, "latent_reasoning_type": None}

def _count_transitions(sequence):
    transitions = {}
    for i in range(len(sequence) - 1):
        key = f"{sequence[i]}→{sequence[i+1]}"
        transitions[key] = transitions.get(key, 0) + 1
    return transitions

def _classify_failure_trajectory(failure_sequence):
    if len(failure_sequence) <= 1:
        return "single"
    if len(set(failure_sequence)) == 1:
        return "stable"
    if len(failure_sequence) >= 3 and failure_sequence[-1] == failure_sequence[-2]:
        return "converging"
    for i in range(1, len(failure_sequence)):
        if failure_sequence[i] == failure_sequence[i-1]:
            break
    else:
        return "oscillating"
    return "mixed"
```

### Step 3: Modify runner.py — Add `retry_adaptive`

```python
# In ALL_CONDITIONS:
"retry_no_contract", "retry_with_contract", "retry_adaptive",

# In COND_LABELS:
"retry_adaptive": "RA",

# In COND_DESCRIPTIONS:
"retry_adaptive": "Retry harness (adaptive hints)",

# In _run_one():
if condition == "retry_adaptive":
    from retry_harness import run_retry_harness
    return run_retry_harness(case, model, use_contract=False, use_adaptive=True)
```

### Step 4: Update tests

**`tests/test_failure_classifier.py`** (NEW — ~15 tests):
- Classification from critique keywords
- Classification from error category
- Classification from reasons keywords
- UNKNOWN fallback
- Never returns null
- No case metadata in signature
- Confidence values correct per rule

**`tests/test_retry_harness.py`** (UPDATE — ~10 new tests):
- `test_status_sequence_replaces_trajectory_pattern`
- `test_attempt_progress_values`
- `test_hint_used_type_present_on_adaptive`
- `test_hint_used_type_none_on_non_adaptive`
- `test_attempt_similarity_computed`
- `test_latent_signal_detected`
- `test_failure_sequence_in_summary`
- `test_classifier_coverage_in_summary`
- `test_first_pass_success_flag`
- `test_retry_effectiveness_classification`

### Step 5: scripts/shadow_analysis.py (NEW)

Reads logs from a run that includes baseline + retry conditions. Produces:

- Per-case comparison table (baseline vs each retry condition)
- recovery_rate, regression_rate
- avg_attempts_to_success
- cost_per_success (model_calls / recovered cases)
- recovery_by_failure_type
- P(success | failure_type, condition)
- failure_transition_matrix
- delta_success_by_failure_type = P(adaptive) - P(no_contract)

Validation checks: all cases present, no mismatches, logs complete.

### Step 6: ablation_config.yaml + scripts/run_ablation_config.py

Simple YAML config → runner invocation. Specifies models, conditions, cases, parallelism.

### Step 7: Fail-fast guards

Add to retry_harness.py or a monitoring wrapper:
- Abort if UNKNOWN rate > 50%
- Abort if all failure_type_final identical AND avg confidence < 0.3
- Abort if 3+ consecutive attempts with > 0.95 similarity (already implemented in Step 2)
- Warn on classifier collapse (one type > 90%)
- Warn on no improvement after retries for > 80% of cases

---

## 2. Implementation Order (Safe Sequence)

```
Phase 1: Classifier + Tests
  1. failure_classifier.py
  2. tests/test_failure_classifier.py
  3. Run: pytest tests/test_failure_classifier.py → all pass

Phase 2: Retry Harness Upgrades
  4. Add use_adaptive param, ADAPTIVE_HINTS, _detect_latent_signal, _count_transitions, _classify_failure_trajectory
  5. Update trajectory entry with new fields
  6. Update summary with all new fields
  7. Rename trajectory_pattern → status_sequence
  8. Add SequenceMatcher-based stagnation
  9. Update _build_retry_prompt to accept adaptive_hint
  10. Update existing tests for renamed fields
  11. Add new tests for new fields
  12. Run: pytest tests/ → 234+ pass (all old + new)

Phase 3: Runner Wiring
  13. Add retry_adaptive to runner.py
  14. Fix test_all_conditions tests
  15. Run: pytest tests/ → all pass

Phase 4: Smoke Test (REAL API)
  16. Run: 3 cases × 3 conditions × gpt-4o-mini
      Cases: hidden_dep_multihop, retry_ack_medium, conservation_easy
      Conditions: baseline, retry_no_contract, retry_adaptive
  17. Inspect logs: verify all new fields present
  18. Verify classifier produces varied outputs
  19. Verify adaptive hints appear in retry prompts (k>0)
  20. Verify latent signal detected on at least 1 iteration

Phase 5: Analysis Scripts
  21. scripts/shadow_analysis.py
  22. Test on smoke test logs
  23. ablation_config.yaml + run script

Phase 6: Go/No-Go
  24. All tests pass
  25. Smoke test clean
  26. Shadow analysis produces valid output
  27. No fail-fast triggers

Phase 7: Full Ablation
  28. 12 cases × 5 conditions × 2 models (gpt-4o-mini, gpt-5-mini)
  29. Monitor for anomalies
  30. Run shadow_analysis.py on results
```

---

## 3. Experiment Spec (Full Ablation)

**Models:** gpt-4o-mini, gpt-5-mini
**Conditions:** baseline, repair_loop, retry_no_contract, retry_with_contract, retry_adaptive

**Cases (12):**
| Case | Type | Difficulty | Expected Regime |
|---|---|---|---|
| hidden_dep_multihop | Core | hard | CSF |
| invariant_partial_fail | Core | hard | CSF |
| async_race_lock | Core | hard | mixed |
| idempotency_trap | Core | hard | CSF |
| cache_invalidation_order | Core | hard | CSF |
| shared_ref_coupling | Core | hard | mixed |
| retry_causality | Retry | hard | CSF |
| retry_ack_easy | Retry | easy | REI |
| retry_ack_medium | Retry | medium | mixed |
| retry_ack_hard | Retry | hard | CSF |
| conservation_easy | Control | easy | Heuristic |
| alias_easy | Control | easy | Heuristic |

**Call estimate:** ~450 realistic, ~744 worst case

---

## 4. File Change Summary

| File | Action | Changes |
|---|---|---|
| `failure_classifier.py` | **CREATE** | ~120 lines: FAILURE_TYPES, classify_failure(), keyword sets |
| `retry_harness.py` | **MODIFY** | ~120 lines added: use_adaptive param, ADAPTIVE_HINTS, _detect_latent_signal, _count_transitions, _classify_failure_trajectory, classification/intervention/latent/similarity fields in loop, 12 new summary fields, status_sequence rename, SequenceMatcher stagnation |
| `runner.py` | **MODIFY** | ~5 lines: retry_adaptive condition |
| `tests/test_failure_classifier.py` | **CREATE** | ~80 lines: 15 tests |
| `tests/test_retry_harness.py` | **MODIFY** | ~60 lines: 10 new tests + rename fixes |
| `tests/test_all_conditions.py` | **MODIFY** | ~1 line: add retry_adaptive to special set |
| `tests/test_failure_suite.py` | **MODIFY** | ~1 line: add retry_adaptive to special set |
| `scripts/shadow_analysis.py` | **CREATE** | ~150 lines |
| `ablation_config.yaml` | **CREATE** | ~30 lines |
| `scripts/run_ablation_config.py` | **CREATE** | ~50 lines |

**Total new code:** ~600 lines across 5 new files + 4 modified files.
