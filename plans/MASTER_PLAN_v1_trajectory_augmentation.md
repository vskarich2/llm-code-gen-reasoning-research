# Master Plan Augmentation: Trajectory-Aware Failure Modeling

**Date:** 2026-03-23
**Type:** Delta to `MASTER_PLAN_v1.md` — targeted additions only
**Constraint:** <200 additional lines of code, reuse existing infrastructure
**Motivation:** Failures form trajectories (oscillation, divergence, stagnation), not independent events. The retry loop must detect and respond to trajectory dynamics, not just individual failures.

---

## 1. Delta to Existing Plan

### What changes

| Component | Current | After Augmentation |
|---|---|---|
| Trajectory entry | Has `diff`, `predicted_failure_mode` | Adds `code_hash`, `failure_type` (from classifier), `similarity_to_previous` |
| Summary | Has `error_trajectory`, `trajectory_pattern` | Adds `failure_sequence`, `failure_transitions`, `transition_entropy`, `trajectory_dynamics` |
| Retry loop | Breaks on stagnation (diff < 10 chars) | Also detects oscillation + divergence; escalates intervention |
| Metrics | 10 existing | 5 new trajectory metrics |
| `_build_retry_prompt` | Takes `adaptive_hint` | Also takes `trajectory_context` (escalation signal) |

### What does NOT change

- Logging format (still 3-file JSONL, append-only)
- exec_eval.py
- evaluator.py
- runner.py dispatch
- Existing tests (no regressions)

---

## 2. Updated Logging Schema (New Fields Only)

### Per-iteration entry — 3 new fields

```python
entry = {
    # ... all existing fields unchanged ...

    # NEW: trajectory-aware fields
    "code_hash": hashlib.md5(code_k.encode()).hexdigest()[:12],
    "failure_type": classification["failure_type_final"] if classification else None,
    "similarity_to_previous": attempt_similarity,  # already computed, just renamed for clarity
}
```

`code_hash` enables duplicate detection without storing full code in the summary trajectory. `failure_type` is a flat string (promoted from the nested `classification` dict) for easy trajectory analysis. `similarity_to_previous` already exists as `attempt_similarity` in the retry_ablation plan — this is the same field.

**Implementation:** 3 lines added to the entry dict construction at `retry_harness.py:685`. `hashlib` is stdlib, already importable.

### Per-summary — 5 new fields

```python
summary = {
    # ... all existing fields unchanged ...

    # NEW: trajectory dynamics
    "failure_sequence": [e.get("failure_type") for e in trajectory if not e["pass"]],
    "failure_transitions": _compute_transitions(failure_sequence),
    "transition_entropy": _compute_transition_entropy(failure_transitions),
    "trajectory_dynamics": _classify_trajectory_dynamics(trajectory),
    "convergence_depth": _compute_convergence_depth(trajectory),
}
```

Note: `failure_sequence` and `failure_transitions` were already in the retry_ablation plan but not yet implemented. This augmentation specifies them precisely and adds `transition_entropy`, `trajectory_dynamics`, and `convergence_depth`.

---

## 3. New Helper Functions (~80 lines)

### 3A. Transition Computation

```python
def _compute_transitions(failure_sequence):
    """Count consecutive failure type transitions.

    Input: ["TEMPORAL_ORDERING", "TEMPORAL_ORDERING", "HIDDEN_DEPENDENCY"]
    Output: {"TEMPORAL_ORDERING→TEMPORAL_ORDERING": 1, "TEMPORAL_ORDERING→HIDDEN_DEPENDENCY": 1}
    """
    transitions = {}
    for i in range(len(failure_sequence) - 1):
        key = f"{failure_sequence[i]}→{failure_sequence[i+1]}"
        transitions[key] = transitions.get(key, 0) + 1
    return transitions
```

Already designed in the retry_ablation plan as `_count_transitions`. Same function, clearer name.

### 3B. Transition Entropy

```python
def _compute_transition_entropy(transitions):
    """Shannon entropy over transition distribution. Low = stable, high = chaotic.

    Formula: H = -Σ p_i * log2(p_i) where p_i = count_i / total
    Range: 0.0 (single transition type) to log2(n) (uniform)
    """
    if not transitions:
        return 0.0
    total = sum(transitions.values())
    probs = [c / total for c in transitions.values()]
    return round(-sum(p * math.log2(p) for p in probs if p > 0), 3)
```

### 3C. Trajectory Dynamics Classification

```python
def _classify_trajectory_dynamics(trajectory):
    """Classify the failure trajectory pattern.

    Returns dict with booleans for each dynamic, plus the dominant pattern.
    Multiple dynamics can co-occur (e.g., oscillation + partial convergence).
    """
    if len(trajectory) <= 1:
        return {"pattern": "single_shot", "oscillation": False,
                "divergence": False, "stagnation": False, "convergence": False}

    scores = [e["score"] for e in trajectory]
    types = [e.get("failure_type") for e in trajectory if not e["pass"]]
    sims = [e.get("similarity_to_previous") for e in trajectory[1:]
            if e.get("similarity_to_previous") is not None]

    # Oscillation: score direction reverses at least twice
    reversals = 0
    for i in range(2, len(scores)):
        d_prev = scores[i-1] - scores[i-2]
        d_curr = scores[i] - scores[i-1]
        if d_prev * d_curr < 0:
            reversals += 1
    oscillation = reversals >= 2

    # Divergence: failure type changes AND score doesn't improve
    type_changes = sum(1 for i in range(1, len(types)) if types[i] != types[i-1])
    no_improvement = scores[-1] <= scores[0]
    divergence = type_changes >= 2 and no_improvement

    # Stagnation: high similarity for 3+ consecutive attempts
    consec_stag = 0
    max_stag = 0
    for s in sims:
        if s and s > 0.95:
            consec_stag += 1
            max_stag = max(max_stag, consec_stag)
        else:
            consec_stag = 0
    stagnation = max_stag >= 2  # 2 consecutive high-similarity (= 3 similar attempts)

    # Convergence: final score > initial AND passed
    convergence = trajectory[-1]["pass"] and scores[-1] > scores[0]

    # Dominant pattern (priority: convergence > oscillation > divergence > stagnation)
    if convergence:
        pattern = "MONOTONIC_FIX" if not oscillation else "OSCILLATING_FIX"
    elif oscillation:
        pattern = "OSCILLATION"
    elif divergence:
        pattern = "DIVERGENCE"
    elif stagnation:
        pattern = "STAGNATION"
    else:
        pattern = "UNCLASSIFIED"

    return {
        "pattern": pattern,
        "oscillation": oscillation,
        "divergence": divergence,
        "stagnation": stagnation,
        "convergence": convergence,
        "score_reversals": reversals,
        "type_changes": type_changes,
        "max_consecutive_similar": max_stag,
    }
```

### 3D. Convergence Depth

```python
def _compute_convergence_depth(trajectory):
    """How deep into the retry budget did convergence happen?

    Returns float in [0, 1]:
      0.0 = passed on first attempt
      0.2 = passed on attempt 2 of 5
      1.0 = used all attempts (or never converged → null)
      null = did not converge
    """
    if not trajectory:
        return None
    for i, e in enumerate(trajectory):
        if e["pass"]:
            return round(i / max(len(trajectory) - 1, 1), 3) if i > 0 else 0.0
    return None  # never converged
```

---

## 4. Retry Loop Upgrade — Trajectory-Aware Prompting

### 4A. Insertion Point

In `run_retry_harness`, after classification and before building the retry prompt (between lines 682 and 684 in current code), add trajectory analysis:

```python
# --- Trajectory analysis (for retry prompt escalation) ---
trajectory_context = None
if k >= 2 and use_adaptive and not ev["pass"]:
    trajectory_context = _analyze_trajectory_for_retry(trajectory, classification)
```

### 4B. Trajectory Analyzer

```python
def _analyze_trajectory_for_retry(trajectory, current_classification):
    """Analyze trajectory to decide retry escalation.

    Returns context string to append to retry prompt, or None.
    """
    types = [e.get("failure_type") for e in trajectory if not e["pass"] and e.get("failure_type")]
    scores = [e["score"] for e in trajectory]

    if not types:
        return None

    current_type = current_classification["failure_type_final"] if current_classification else None

    # SAME failure repeats 3+ times → escalate
    if len(types) >= 3 and len(set(types[-3:])) == 1:
        return (f"WARNING: The same failure ({types[-1]}) has persisted for {len(types)} attempts. "
                f"Your previous approaches are not working. Try a fundamentally different strategy.")

    # Failure type CHANGED on last attempt → divergence
    if len(types) >= 2 and types[-1] != types[-2]:
        return (f"NOTE: The failure type changed from {types[-2]} to {types[-1]}. "
                f"Your fix may have introduced a new issue. Focus on preserving what was working.")

    # Score oscillating → instability
    if len(scores) >= 3:
        d1 = scores[-2] - scores[-3]
        d2 = scores[-1] - scores[-2]
        if d1 * d2 < 0:  # direction reversal
            return ("CAUTION: Your score is oscillating. Each fix is undoing the previous one. "
                    "Make a minimal, targeted change rather than a large rewrite.")

    return None
```

### 4C. Integration with `_build_retry_prompt`

```python
def _build_retry_prompt(case, original_code, prev_code, test_output,
                        critique, contract, adaptive_hint=None,
                        trajectory_context=None):
    parts = [case["task"]]
    parts.append(f"\n=== Original Code ===\n{original_code}")
    parts.append(f"\n=== Your Previous Attempt ===\n```python\n{prev_code}\n```")
    parts.append(f"\n=== Test Results (FAILED) ===\n{test_output}")
    if critique:
        parts.append(f"\n=== Diagnosis ===\n{json.dumps(_clean_critique_for_log(critique), indent=2)}")
    if contract:
        parts.append(f"\n=== Your Intended Fix ===\n{json.dumps(contract, indent=2)}")
    if adaptive_hint:
        parts.append(f"\n=== Hint ===\n{adaptive_hint}")
    if trajectory_context:                           # NEW
        parts.append(f"\n=== Trajectory Feedback ===\n{trajectory_context}")
    parts.append("\nFix the failing tests with minimal changes to your previous attempt.")
    parts.append("Return the complete updated code.")
    return "\n".join(parts)
```

### 4D. Updated Stop Conditions

The existing stagnation check stays. Add trajectory-aware logging but NOT new stop conditions (we want to observe the full trajectory, not cut it short):

```python
# After existing stop conditions, before prev_code update:
if k >= 2:
    dynamics = _classify_trajectory_dynamics(trajectory)
    if dynamics["oscillation"]:
        _log.info("OSCILLATION detected for %s at iteration %d", case["id"], k)
    if dynamics["divergence"]:
        _log.info("DIVERGENCE detected for %s at iteration %d", case["id"], k)
```

These are observations, not stop conditions. We want the loop to continue so we can measure the full trajectory.

---

## 5. New Metrics (5 total)

### 5A. failure_transition_entropy

**Formula:** `H = -Σ p_i * log2(p_i)` over transition type distribution
**Computed from:** `summary["failure_transitions"]`
**Range:** 0.0 (single repeated transition) to log2(n_types) (uniform)
**Interpretation:** Low entropy = stable failure (REI signature). High entropy = chaotic failure (CSF signature).

### 5B. trajectory_stability_score

**Formula:** `1.0 - (type_changes / (n_failed - 1))` where type_changes = number of consecutive failure type changes
**Computed from:** `failure_sequence`
**Range:** 0.0 (every failure is different type) to 1.0 (same type throughout)
**Interpretation:** High stability + no convergence = strong REI signal. Low stability = CSF or divergence.

```python
def _trajectory_stability_score(failure_sequence):
    if len(failure_sequence) <= 1:
        return 1.0
    changes = sum(1 for i in range(1, len(failure_sequence))
                  if failure_sequence[i] != failure_sequence[i-1])
    return round(1.0 - changes / (len(failure_sequence) - 1), 3)
```

### 5C. oscillation_rate

**Formula:** `score_reversals / (n_attempts - 2)` where score_reversals = number of times score direction changes
**Computed from:** `trajectory_dynamics["score_reversals"]` and `total_iterations_executed`
**Range:** 0.0 (monotonic) to 1.0 (alternates every step)
**Interpretation:** > 0.5 = strong oscillation signal. The model is undoing its fixes.

```python
def _oscillation_rate(trajectory):
    scores = [e["score"] for e in trajectory]
    if len(scores) < 3:
        return 0.0
    reversals = sum(1 for i in range(2, len(scores))
                    if (scores[i-1] - scores[i-2]) * (scores[i] - scores[i-1]) < 0)
    return round(reversals / (len(scores) - 2), 3)
```

### 5D. local_vs_global_fix_ratio

**Formula:** `n_local_fixes / n_total_fixes` where a fix is "local" if `diff.hunks == 1` (single edit location)
**Computed from:** trajectory diffs
**Range:** 0.0 (all global rewrites) to 1.0 (all single-point fixes)
**Interpretation:** High local ratio = model making targeted fixes (REI). Low ratio = model doing rewrites (CSF/heuristic instability).

```python
def _local_vs_global_ratio(trajectory):
    diffs = [e["diff"] for e in trajectory[1:] if e.get("diff")]
    if not diffs:
        return None
    local = sum(1 for d in diffs if d.get("hunks", 0) == 1)
    return round(local / len(diffs), 3)
```

### 5E. convergence_depth

(Defined in §3D above.)

### Integration into `_compute_metrics`

Add to existing function:
```python
# After existing metrics computation:
metrics["transition_entropy"] = _compute_transition_entropy(
    _compute_transitions(failure_seq))
metrics["trajectory_stability"] = _trajectory_stability_score(failure_seq)
metrics["oscillation_rate"] = _oscillation_rate(trajectory)
metrics["local_fix_ratio"] = _local_vs_global_ratio(trajectory)
metrics["convergence_depth"] = _compute_convergence_depth(trajectory)
```

Where `failure_seq` is extracted from trajectory entries.

---

## 6. Integration Points (Phase A–H Mapping)

All trajectory augmentations slot into **Phase D** (Failure Classifier + Adaptive Retry) of the master plan. No other phases change.

| Master Plan Step | Augmentation |
|---|---|
| D1: failure_classifier.py | No change — classifier is prerequisite for failure_type field |
| D2: retry_harness.py upgrades | **ADD:** code_hash, failure_type, similarity_to_previous to entry. **ADD:** failure_transitions, transition_entropy, trajectory_dynamics, convergence_depth to summary. **ADD:** _analyze_trajectory_for_retry(), _classify_trajectory_dynamics(), _compute_transition_entropy(), _trajectory_stability_score(), _oscillation_rate(), _local_vs_global_ratio(), _compute_convergence_depth(). **MODIFY:** _build_retry_prompt to accept trajectory_context. **MODIFY:** _compute_metrics to include 5 new metrics |
| D3: runner.py | No change |
| D4: tests | **ADD:** ~10 tests for new functions (dynamics classification, entropy, stability, oscillation, convergence depth) |
| D5: pytest | Verify 234+ old + all new pass |

**Estimated additional code:** ~80 lines of new helper functions + ~30 lines of integration + ~50 lines of tests = **~160 lines total** (within 200-line budget).

---

## 7. Risk Analysis

### Risk 1: Trajectory analysis causes logging bloat

**Severity:** Low
**Mechanism:** `trajectory_dynamics` dict adds ~8 fields per summary. `failure_transitions` dict size scales with unique transition pairs (max ~10 for 5 iterations).
**Mitigation:** Already capped by max_iterations=5. Worst case: ~500 bytes per summary. Negligible vs existing trajectory array.

### Risk 2: Misclassification cascades through trajectories

**Severity:** Medium
**Mechanism:** If the classifier assigns wrong types, `failure_transitions` and `transition_entropy` are computed over garbage. `trajectory_dynamics.divergence` could fire falsely (type changes that are actually classifier noise, not real divergence).
**Mitigation:** Already addressed: classifier confidence is logged per attempt. Analysis scripts should filter by `classifier_confidence >= 0.5` when computing trajectory metrics. The `classifier_coverage` field in the summary explicitly tracks confident vs uncertain predictions.

### Risk 3: Trajectory-aware prompts (escalation) make the retry loop unstable

**Severity:** Medium
**Mechanism:** The escalation messages ("try a fundamentally different strategy") could cause the model to make larger changes, increasing divergence rather than convergence.
**Mitigation:** Trajectory context is only added when `use_adaptive=True` (the `retry_adaptive` condition). The clean baselines (`retry_no_contract`, `retry_with_contract`) are unaffected. This lets us measure whether trajectory-aware prompting helps or hurts.

### Risk 4: Code hash collisions create false duplicate detection

**Severity:** Very Low
**Mechanism:** MD5 truncated to 12 hex chars (48 bits) has collision probability ~1 in 2^24 for realistic attempt counts (≤5).
**Mitigation:** Code hash is a convenience field for log analysis, not used in any control flow. Full code is available in the responses log.

### Risk 5: Oscillation detection is too sensitive

**Severity:** Low
**Mechanism:** Score moving from 0.2→0.2→0.2 (flat) has zero reversals. But 0.2→0.5→0.2 (one reversal) doesn't meet the `>= 2` threshold. The threshold is conservative.
**Mitigation:** The `trajectory_dynamics` dict reports raw `score_reversals` count, so analysis can use any threshold post-hoc.
