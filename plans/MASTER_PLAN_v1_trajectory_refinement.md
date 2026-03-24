# Trajectory Augmentation — Control/Analysis Refinement

**Date:** 2026-03-23
**Type:** Delta to `MASTER_PLAN_v1_trajectory_augmentation.md`
**Scope:** Tighten control/analysis boundary, add raw signals, add failure_persistence

---

## 1. Control vs Analysis Signal Table

| Signal | Type | Used In | Why |
|---|---|---|---|
| `consecutive_same_failure` (int) | **CONTROL** | Retry prompt escalation | Simple counter. If same type repeats 3x, escalate. No derived labels needed. |
| `similarity_to_previous` (float) | **CONTROL** | Stagnation detection + forced rewrite | Direct measurement. >0.95 for 3 steps = stagnation. |
| `score_improving` (bool) | **CONTROL** | Search broadening | `scores[-1] > scores[-2]`. Binary, noise-free. |
| `failure_type` (str) | **CONTROL** (individual) | Adaptive hint selection | Single classifier output per attempt. Already confidence-gated. |
| | | | |
| `trajectory_dynamics` (dict) | **ANALYSIS** | Post-hoc reporting only | Derived from multiple signals. Noisy. Not real-time safe. |
| `transition_entropy` (float) | **ANALYSIS** | Regime classification | Requires full sequence. Meaningless mid-loop. |
| `trajectory_stability` (float) | **ANALYSIS** | Research metrics | Aggregate. |
| `oscillation_rate` (float) | **ANALYSIS** | Research metrics | Aggregate. |
| `failure_persistence` (dict) | **ANALYSIS** | REI detection | Aggregate. |
| `convergence_depth` (float) | **ANALYSIS** | Research metrics | Only known after loop ends. |
| `local_fix_ratio` (float) | **ANALYSIS** | Research metrics | Aggregate. |

**Rule:** Nothing in the ANALYSIS column may appear in an `if` statement inside the retry loop. Control signals are computed incrementally (O(1) per iteration). Analysis signals are computed post-hoc (after the loop).

**Parameterized thresholds:**
```python
SIMILARITY_THRESHOLD = 0.95       # for stagnation detection
SCORE_EPSILON = 0.05              # scores within epsilon are "same"
PERSISTENCE_ESCALATION_COUNT = 2  # consecutive same failures before escalation
```
All thresholds are module-level constants. No magic numbers in control logic.

---

## 2. Updated Logging Schema

### Per-iteration — no changes from previous augmentation

Same 3 new fields: `code_hash`, `failure_type`, `similarity_to_previous`. These are raw measurements, not derived labels.

### Per-summary — add raw signal sequences

```python
summary = {
    # ... all existing fields unchanged ...

    # RAW SIGNALS (sequences — always logged, always available for post-hoc analysis)
    "score_sequence": [e["score"] for e in trajectory],
    "failure_type_sequence": [e.get("failure_type") for e in trajectory],
    "similarity_sequence": [e.get("similarity_to_previous") for e in trajectory],
    "num_type_changes": sum(1 for i in range(1, len(ft_seq)) if ft_seq[i] != ft_seq[i-1]),
    "num_score_reversals": _count_reversals(score_seq),
    "consecutive_same_failure_lengths": _run_lengths(ft_seq),

    # DERIVED ANALYSIS SIGNALS (computed post-hoc, NOT used in control)
    "failure_transitions": _compute_transitions(ft_seq),
    "transition_entropy": _compute_transition_entropy(transitions),
    "trajectory_dynamics": _classify_trajectory_dynamics(trajectory),
    "trajectory_stability": _trajectory_stability_score(ft_seq),
    "oscillation_rate": _oscillation_rate(trajectory),
    "convergence_depth": _compute_convergence_depth(trajectory),
    "failure_persistence": _compute_failure_persistence(ft_seq),
}
```

**New helper for raw signals (~15 lines):**

```python
def _count_reversals(scores):
    """Count score direction changes."""
    return sum(1 for i in range(2, len(scores))
               if (scores[i-1] - scores[i-2]) * (scores[i] - scores[i-1]) < 0)

def _run_lengths(sequence):
    """Lengths of consecutive identical runs.

    Input: ["A", "A", "B", "B", "B", "A"]
    Output: [2, 3, 1]
    """
    if not sequence:
        return []
    lengths = []
    current = 1
    for i in range(1, len(sequence)):
        if sequence[i] == sequence[i-1]:
            current += 1
        else:
            lengths.append(current)
            current = 1
    lengths.append(current)
    return lengths
```

`score_sequence` and `failure_type_sequence` are already derivable from the trajectory array, but logging them as flat lists makes post-hoc analysis trivial (no need to unpack nested dicts). `consecutive_same_failure_lengths` is the raw data behind failure_persistence — always available regardless of how the metric evolves.

---

## 3. Updated Retry Loop Logic (Control Signals Only)

### What's IN the loop (simple, incremental, reliable)

```python
# Tracked incrementally inside the loop:
consecutive_same_failure = 0   # reset when failure_type changes
consecutive_high_sim = 0       # reset when similarity drops below threshold

# After classification, before building retry prompt:
if k > 0 and not ev["pass"]:
    current_type = classification["failure_type_final"] if classification else None
    prev_type = trajectory[-1].get("failure_type") if trajectory else None

    # Control Signal 1: Same failure repeating
    # Fallback: if classifier returns UNKNOWN for both, compare error messages
    types_match = (current_type and current_type == prev_type
                   and current_type != "UNKNOWN")
    if not types_match and (not current_type or current_type == "UNKNOWN"):
        # Classifier uncertain — fall back to error message similarity
        prev_msg = trajectory[-1].get("error", {}).get("message", "")
        curr_msg = error_obj.get("message", "")
        if prev_msg and curr_msg:
            types_match = SequenceMatcher(None, prev_msg, curr_msg).ratio() > 0.8

    if types_match:
        consecutive_same_failure += 1
    else:
        consecutive_same_failure = 0

    # Control Signal 2: High code similarity (parameterized threshold)
    if attempt_similarity and attempt_similarity > SIMILARITY_THRESHOLD:
        consecutive_high_sim += 1
    else:
        consecutive_high_sim = 0

    # Control Signal 3: Score not improving (epsilon-tolerant)
    score_improving = ev["score"] > prev_score + SCORE_EPSILON
```

### Prompt escalation rules (ONLY these 3 triggers)

```python
trajectory_context = None
if use_adaptive and k >= 1 and not ev["pass"]:

    # Rule 1: Same failure 3+ times → escalate
    if consecutive_same_failure >= 2:  # 3 consecutive same type (current + 2 prior)
        trajectory_context = (
            f"The same failure ({current_type}) has persisted for "
            f"{consecutive_same_failure + 1} attempts. "
            f"Your previous approaches are not working. "
            f"Try a fundamentally different strategy."
        )

    # Rule 2: High similarity 3+ times → force different approach
    elif consecutive_high_sim >= PERSISTENCE_ESCALATION_COUNT:  # parameterized
        trajectory_context = (
            "Your last 3 attempts produced nearly identical code. "
            "You must make a meaningfully different change. "
            "Reconsider your assumptions about the root cause."
        )

    # Rule 3: Score stagnant or regressing for 2+ attempts → broaden
    elif k >= 2 and not score_improving and ev["score"] <= trajectory[-2].get("score", 0) + SCORE_EPSILON:
        trajectory_context = (
            "Your score has not improved in the last 2 attempts. "
            "Consider a broader approach to the problem."
        )
```

### What's NOT in the loop

These are explicitly **excluded from control logic**:

- `trajectory_dynamics["pattern"]` — NOT checked in any `if` statement
- `transition_entropy` — NOT computed until post-hoc
- `oscillation_rate` — NOT computed until post-hoc
- `trajectory_stability` — NOT computed until post-hoc
- `failure_persistence` — NOT computed until post-hoc

The loop only uses: `consecutive_same_failure` (counter), `consecutive_high_sim` (counter), `score_improving` (bool). All three are O(1) per iteration and cannot cascade.

---

## 4. Failure Persistence Metric

### Definition

Two complementary measures of how "stuck" the model is on one failure type:

```python
def _compute_failure_persistence(failure_type_sequence, error_messages=None):
    """Measures how dominated the trajectory is by a single failure type.

    Robust to classifier noise: when failure_type is UNKNOWN, falls back
    to error_message similarity to determine if the underlying failure
    is actually the same.

    Args:
        failure_type_sequence: ["TEMPORAL", "TEMPORAL", "UNKNOWN", ...]
        error_messages: parallel list of error message strings (optional)

    Returns dict with:
      longest_run: longest consecutive run of same failure (noise-corrected)
      dominant_fraction: fraction of failures that are the most common type
      dominant_type: the most common failure type (or null)
      unknown_rate: fraction of UNKNOWN classifications
    """
    types = [t for t in failure_type_sequence if t is not None]
    if not types:
        return {"longest_run": 0, "dominant_fraction": 0.0,
                "dominant_type": None, "unknown_rate": 0.0}

    unknown_count = sum(1 for t in types if t == "UNKNOWN")

    # Noise-corrected types: replace UNKNOWN with neighbor type if
    # error messages are similar (>0.8 ratio) to adjacent attempts
    corrected = list(types)
    if error_messages and unknown_count > 0:
        msgs = [m for m in error_messages if m is not None]
        for i in range(len(corrected)):
            if corrected[i] == "UNKNOWN" and i < len(msgs):
                # Look at previous non-UNKNOWN neighbor
                for j in range(i - 1, -1, -1):
                    if corrected[j] != "UNKNOWN" and j < len(msgs):
                        if SequenceMatcher(None, msgs[j], msgs[i]).ratio() > 0.8:
                            corrected[i] = corrected[j]
                        break

    # Longest consecutive run (on corrected types)
    longest = 1
    current = 1
    for i in range(1, len(corrected)):
        if corrected[i] == corrected[i-1] and corrected[i] != "UNKNOWN":
            current += 1
            longest = max(longest, current)
        else:
            current = 1

    # Dominant type fraction (exclude UNKNOWN from counting)
    non_unknown = [t for t in corrected if t != "UNKNOWN"]
    if non_unknown:
        counts = Counter(non_unknown)
        dominant_type, dominant_count = counts.most_common(1)[0]
        dominant_fraction = round(dominant_count / len(types), 3)
    else:
        dominant_type = None
        dominant_fraction = 0.0

    return {
        "longest_run": longest,
        "dominant_fraction": dominant_fraction,
        "dominant_type": dominant_type,
        "unknown_rate": round(unknown_count / len(types), 3),
    }
```

Called in summary construction with error messages for noise correction:
```python
error_msgs = [e.get("error", {}).get("message", "") for e in trajectory]
summary["failure_persistence"] = _compute_failure_persistence(ft_seq, error_msgs)
```

### Interpretation

| longest_run | dominant_fraction | Meaning |
|---|---|---|
| = n_failed | 1.0 | Pure REI: same failure every attempt. Model is stuck on one issue. |
| ≥ 3 | > 0.7 | Strong REI signal: mostly the same failure with brief deviations. |
| 1-2 | < 0.5 | CSF or divergence: failure type unstable across attempts. |

### Where logged

In summary under `"failure_persistence"`:
```json
{
    "longest_run": 4,
    "dominant_fraction": 0.8,
    "dominant_type": "TEMPORAL_ORDERING"
}
```

And the raw data is always available in `consecutive_same_failure_lengths` (the run-length encoding).

---

## 5. Rationale

### Why this improves robustness

**Problem with the previous design:** `trajectory_dynamics["pattern"]` labels (OSCILLATION, DIVERGENCE, etc.) were derived from multiple noisy signals (classifier output, score sequences, similarity ratios) and then used to modify retry prompts. If any upstream signal was wrong, the derived label could be wrong, and the prompt escalation could be counterproductive — making the model's behavior WORSE.

**This refinement fixes it by:**

1. **Control uses only raw signals.** `consecutive_same_failure` is a counter. `consecutive_high_sim` is a threshold on a float. `score_improving` is a comparison. None of these depend on the classifier being correct about the SPECIFIC type — they only care about "same or different" and "similar or not." Even if the classifier assigns the wrong type, the control logic still works: "same wrong type 3 times" correctly triggers escalation.

2. **Analysis signals are rich but isolated.** Transition entropy, oscillation rate, trajectory dynamics — these produce the interesting research metrics. But because they're computed AFTER the loop, they can't destabilize it. We get the full analytical power without the fragility.

3. **Raw sequences are always available.** Even if every derived metric turns out to be wrong, the raw `score_sequence`, `failure_type_sequence`, `similarity_sequence`, and `consecutive_same_failure_lengths` are in the log. Any post-hoc analysis can recompute anything.

**Design principle applied:** Simple, reliable control + rich offline analysis > complex real-time control.
