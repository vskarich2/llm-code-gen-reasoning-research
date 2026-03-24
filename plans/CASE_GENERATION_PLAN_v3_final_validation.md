# Case Generation Plan v3 — Final Validation Pass

**Date:** 2026-03-23
**Type:** 7 final fixes applied to v3-corrections. This is the last revision before implementation.
**Rule:** These fixes supersede the corresponding definitions in v3-corrections. All other v3-corrections content remains valid.

---

## Final Fix 1: reasoning_consistent Strengthened

### Problem

Current definition: `reasoning_valid == True on ≥50% of failing iterations`. This delegates entirely to the existing `reasoning_valid` signal, which is a keyword-match heuristic (checks if the model's text mentions terms from a signal list). A model that mentions "rollback" in passing would be marked as reasoning_valid=True even if its reasoning is wrong.

### Revised Definition

`reasoning_consistent` is TRUE if **either** of the following holds:

**Condition A (critique-based):**
```
critique_accuracy >= 0.5
```
Where `critique_accuracy` is computed per Final Fix 4 below (matching against `ground_truth_bug.location` or `ground_truth_bug.invariant`).

**Condition B (reasoning-match):**
```
reasoning_valid == True on ≥50% of failing iterations
AND the model's reasoning text contains at least one term from ground_truth_bug.type
```

The conjunction in Condition B prevents false positives from generic keyword matching. `ground_truth_bug.type` is a short label like `"shared_reference_mutation"` or `"missing_rollback"` — the model must reference the actual mechanism, not just adjacent vocabulary.

**Pseudocode:**

```python
def reasoning_consistent(per_iteration, ground_truth_bug, critique_accuracy):
    # Condition A: critique feedback identifies the correct bug
    if critique_accuracy >= 0.5:
        return True

    # Condition B: model's reasoning identifies the correct bug
    failing = [it for it in per_iteration if not it["pass"]]
    if not failing:
        return False  # no failures to analyze

    n_valid = sum(1 for it in failing if it["reasoning_valid"])
    ratio = n_valid / len(failing)

    if ratio < 0.5:
        return False

    # Additional check: reasoning must reference the actual bug type
    bug_type_terms = ground_truth_bug["type"].lower().replace("_", " ").split()
    for it in failing:
        reasoning_text = (it.get("reasoning_text") or "").lower()
        if any(term in reasoning_text for term in bug_type_terms):
            return True

    return False
```

**Note:** This requires logging the model's reasoning text per iteration (already in the `_responses.jsonl` file). The `reasoning_text` field is extracted during parsing, not a new log requirement.

---

## Final Fix 2: edit_distance Defined Explicitly

### Problem

The v3-corrections define `diff_localized` as `edit_distance_to_bug ≤ 1` but never define the distance function.

### Explicit Definition

**Edit distance to bug** is a discrete metric with three values:

| Distance | Definition | Example |
|---|---|---|
| **0** | Model edited the **same function** that contains the bug | Bug in `create_config()`, model edited `create_config()` |
| **1** | Model edited a **different function in the same file** as the bug | Bug in `config.py::create_config()`, model edited `config.py::merge_overrides()` |
| **2** | Model edited a **different file** from the bug | Bug in `config.py::create_config()`, model edited `app.py::get_settings()` |

**Computation:**

```python
def edit_distance_to_bug(edited_functions: list[str], ground_truth_location: str) -> int:
    """
    edited_functions: list of "file.py::function_name" that the model modified
    ground_truth_location: "file.py::function_name" where the bug lives

    Returns: minimum distance from any edited function to the bug location
    """
    gt_file, gt_func = ground_truth_location.split("::")

    min_dist = 2  # worst case: different file
    for edit in edited_functions:
        ed_file, ed_func = edit.split("::")
        if ed_file == gt_file and ed_func == gt_func:
            return 0  # same function — best possible
        elif ed_file == gt_file:
            min_dist = min(min_dist, 1)  # same file, different function
        # else: different file, stays at 2

    return min_dist
```

**diff_localized** is then:

```python
diff_localized = (edit_distance_to_bug <= 1)
```

Meaning the model's edits are in the **same file** as the bug. Edits that only touch other files are not localized.

**Per-iteration:** Computed on each iteration's candidate code by diffing against original at function granularity and extracting the list of `edited_functions`.

---

## Final Fix 3: Regime Assignment as Deterministic Priority Logic

### Problem

The 6-row truth table in v3-corrections has ambiguity (the `—` values for `diff_localized` mean "don't care", but implementation must handle all combinations) and doesn't handle edge cases like single-iteration runs or inconsistent signals across replications.

### Replacement: Priority Logic

```python
def assign_regime(mechanism_signals: dict, outcome: dict) -> str:
    """
    Deterministic regime assignment from mechanism signals.
    Priority order: REI > Heuristic > CSF (with mixed as escape hatch).
    """
    rc = mechanism_signals["reasoning_consistent"]
    es = mechanism_signals["error_stable"]
    dl = mechanism_signals["diff_localized"]
    pm = mechanism_signals["progress_made"]  # see Final Fix 6

    # Pass on first try — no retry data to classify mechanism
    if outcome["initial_pass"]:
        return "heuristic"

    # Primary classification
    if rc and es:
        return "REI"          # knows the bug, stuck on consistent error
    elif (not rc) and es:
        return "heuristic"    # doesn't identify bug, but errors are stable (pattern matching)
    elif not es:
        return "CSF"          # errors are unstable — no causal model

    # Should not reach here, but defensive
    return "CSF"
```

**Sub-labels (for detailed analysis, not primary regime):**

After the primary assignment, annotate with a sub-label:

```python
if regime == "REI" and not dl:
    sub_label = "REI_misdirected"    # right reasoning, wrong edit location
elif regime == "REI" and pm:
    sub_label = "REI_improving"      # making progress toward fix
elif regime == "heuristic" and not dl:
    sub_label = "heuristic_scattered" # pattern matching with scattered edits
elif regime == "CSF" and rc:
    sub_label = "CSF_unstable"       # identifies bug but can't converge
else:
    sub_label = regime
```

**Logged as:**
```json
"failure_regime": "REI",
"failure_regime_sub": "REI_misdirected"
```

**Handling inconsistent signals across replications:**

When 3 replications produce different regime assignments (e.g., 2×REI + 1×CSF):
- Use **majority vote** for the primary label
- If no majority (all three differ), assign `"mixed"`
- Log all three individual labels for transparency

```python
def assign_regime_with_replications(regimes: list[str]) -> str:
    from collections import Counter
    counts = Counter(regimes)
    top, top_count = counts.most_common(1)[0]
    if top_count > len(regimes) / 2:
        return top
    return "mixed"
```

---

## Final Fix 4: critique_accuracy Tightened

### Problem

Current definition: feedback matches if it "references the correct function" OR "describes a violation matching the invariant (substring match on key terms)." The substring match is too loose — matching "balance" in a conservation case could trigger on irrelevant text.

### Revised Definition

A failing iteration's feedback **matches ground truth** if EITHER:

**Match A — Location match:**
The test `error_message` contains the function name from `ground_truth_bug.location`.

```python
def location_match(error_message: str, ground_truth_location: str) -> bool:
    func_name = ground_truth_location.split("::")[-1]  # e.g., "create_config"
    return func_name in error_message
```

**Match B — Invariant match:**
The test `error_message` contains **at least 2** of the substantive terms from `ground_truth_bug.invariant` (after stripping stopwords).

```python
STOPWORDS = {"must", "the", "a", "an", "is", "be", "not", "that", "to", "and", "or", "of", "in", "on"}

def invariant_match(error_message: str, ground_truth_invariant: str) -> bool:
    terms = [t.lower() for t in ground_truth_invariant.split() if t.lower() not in STOPWORDS and len(t) > 2]
    msg_lower = error_message.lower()
    hits = sum(1 for t in terms if t in msg_lower)
    return hits >= 2
```

**Requiring 2+ term matches** prevents false positives from single common words.

**critique_accuracy computation:**

```python
def critique_accuracy(per_iteration, ground_truth_bug):
    failing = [it for it in per_iteration if not it["pass"]]
    if not failing:
        return 1.0  # no failures, nothing to critique

    n_match = sum(
        1 for it in failing
        if location_match(it["error_message"], ground_truth_bug["location"])
        or invariant_match(it["error_message"], ground_truth_bug["invariant"])
    )
    return n_match / len(failing)
```

---

## Final Fix 5: silent_failure Refined

### Problem

Current definition: `code_parseable AND code_runnable AND error_type == "invariant_violation" AND not pass`. Missing: the output must be structurally valid (not an empty string, not a traceback, not a partial result).

### Revised Definition

```python
silent_failure = (
    code_parseable == True
    and code_runnable == True
    and error_type == "invariant_violation"   # test ran, invariant failed
    and not pass_
    and output_structurally_valid == True      # NEW: output has expected shape
)
```

**`output_structurally_valid`** is a new per-iteration boolean:

| Field | Type | Definition |
|---|---|---|
| `output_structurally_valid` | bool | The function under test returned a value of the expected type/shape (not None, not empty, not a traceback string). The output LOOKS correct but ISN'T. |

**How to compute:**

The test function already produces this signal implicitly. If the function-under-test returns a value and the test proceeds to invariant checking (rather than catching an exception), the output is structurally valid. Formally:

```python
output_structurally_valid = (
    code_runnable == True
    and error_type != "runtime_error"
    and error_type != "syntax_error"
    and error_type != "no_code"
)
```

This is equivalent to: the code executed to completion and returned something testable.

**Updated log schema for per_iteration:**

```json
{
    "iteration": 1,
    "pass": false,
    "score": 0.5,
    "error_type": "invariant_violation",
    "error_message": "stock leaked: was 10, now 7",
    "silent_failure": true,
    "output_structurally_valid": true,
    "reasoning_valid": true,
    "code_parseable": true,
    "code_runnable": true
}
```

---

## Final Fix 6: Add progress_made Signal

### Addition to mechanism_signals

```json
"mechanism_signals": {
    "reasoning_consistent": true,
    "error_stable": true,
    "diff_localized": true,
    "progress_made": false
}
```

**Definition:**

| Signal | Type | Definition | How to Compute |
|---|---|---|---|
| `progress_made` | bool | Score improved in at least one iteration compared to the first failing iteration | `any(it["score"] > per_iteration[first_failing_idx]["score"] for it in per_iteration[first_failing_idx+1:])` |

**Pseudocode:**

```python
def progress_made(per_iteration: list[dict]) -> bool:
    failing_scores = [it["score"] for it in per_iteration if not it["pass"]]
    if len(failing_scores) <= 1:
        return False  # single iteration, no trajectory to measure
    first_score = failing_scores[0]
    return any(s > first_score for s in failing_scores[1:])
```

**How it interacts with regime assignment:**

`progress_made` is NOT used in the primary regime assignment (Fix 3 uses `reasoning_consistent`, `error_stable`, `diff_localized`). It is used for the sub-label:

- `REI` + `progress_made=True` → `REI_improving` (the retry is helping but hasn't succeeded yet)
- `REI` + `progress_made=False` → `REI` (stuck — reasoning is correct but no score improvement)
- `CSF` + `progress_made=True` → `CSF_with_noise` (score fluctuated upward randomly, not real progress — since `error_stable=False`, this is noise)

**Why it's a separate signal, not part of primary classification:**

Progress-based signals are outcome-adjacent (they describe WHAT happened to the score), not mechanism-based (they don't tell you WHY). Including them in primary regime assignment would partially reintroduce the circularity from the original v3 design. They're safe as sub-labels because the primary classification is already determined.

---

## Final Fix 7: Signal Validation Invariant

### Problem

If any mechanism signal cannot be computed (e.g., single-iteration run with no retry data, or code was completely unparseable on all iterations), `failure_regime` should not be silently assigned a default.

### Invariant

**RULE: failure_regime MUST be derivable from mechanism_signals. If any signal is missing or uncomputable, the record MUST be flagged.**

### Implementation

```python
def validate_and_assign_regime(mechanism_signals: dict, outcome: dict) -> tuple[str, bool]:
    """
    Returns: (regime_label, is_degraded)
    is_degraded=True means one or more signals could not be computed.
    """
    required = ["reasoning_consistent", "error_stable", "diff_localized", "progress_made"]
    missing = [s for s in required if s not in mechanism_signals or mechanism_signals[s] is None]

    if missing:
        # Cannot compute regime reliably
        return "unclassifiable", True

    regime = assign_regime(mechanism_signals, outcome)  # Fix 3 logic
    return regime, False
```

**Cases where signals are uncomputable:**

| Scenario | Which signals are affected | Resolution |
|---|---|---|
| Single iteration (K=1), model passed | All signals except diff_localized | `failure_regime = "heuristic"` (pass_first_try override), `degraded = False` |
| Single iteration, model failed | `error_stable` (needs ≥2 iterations), `progress_made` (needs ≥2) | `error_stable = True` (by convention: single error = stable), `progress_made = False` (no trajectory). Regime is computable |
| All iterations produced unparseable code | `reasoning_consistent` (no reasoning text to analyze), `diff_localized` (no code to diff) | `failure_regime = "unclassifiable"`, `degraded = True` |
| Model returned empty responses | All signals | `failure_regime = "unclassifiable"`, `degraded = True` |

**Logged as:**

```json
"mechanism_metrics": {
    "mechanism_signals": {
        "reasoning_consistent": true,
        "error_stable": true,
        "diff_localized": null,
        "progress_made": false
    },
    "failure_regime": "unclassifiable",
    "failure_regime_sub": null,
    "regime_degraded": true,
    "regime_degraded_reason": "diff_localized uncomputable: all iterations produced unparseable code"
}
```

**Analysis filtering:** `regime_degraded = True` records are **included in pass-rate analyses** (they're real failures) but **excluded from regime-stratified analyses** (their regime label is unreliable). This is an additional filtering rule alongside Fix 9 (which excludes pass_first_try from retry analyses).

---

## Summary of Final Fixes

| # | What Was Fixed | Supersedes |
|---|---|---|
| FF-1 | `reasoning_consistent` now requires critique_accuracy ≥ 0.5 OR reasoning_valid + bug_type term match | Corrections Fix 1 signal definition |
| FF-2 | `edit_distance_to_bug` explicitly defined as 0/1/2 discrete metric | Corrections Fix 1 diff_localized reference |
| FF-3 | Regime assignment is deterministic priority logic (if/elif/else) with majority vote for replications | Corrections Fix 1 truth table |
| FF-4 | `critique_accuracy` requires location match OR 2+ invariant term matches (not single keyword) | Corrections Fix 2 definition |
| FF-5 | `silent_failure` now requires `output_structurally_valid` (not just code_runnable) | Corrections Fix 8 definition |
| FF-6 | `progress_made` added as 4th mechanism signal (sub-label, not primary classifier) | New |
| FF-7 | Missing/uncomputable signals → `"unclassifiable"` + `regime_degraded=True`, excluded from regime analyses | New |

### Remaining Assumptions

1. **Reasoning text is available per iteration.** This is already logged in `_responses.jsonl`. The `reasoning_text` field is extracted during parsing (via `parse_model_response`). No new logging infrastructure needed.

2. **Function-level diffing is feasible.** Computing `edited_functions` requires comparing candidate code against original at the `def` boundary level. Python's `ast` module can extract function names; string diffing identifies which functions changed. This is a utility function, not a research assumption.

3. **Single-iteration convention: `error_stable = True`.** A single data point has zero entropy — it is maximally "stable" by definition. This convention makes single-iteration baseline runs classifiable without special-casing.

4. **`progress_made` is deliberately not in the primary classifier.** This avoids reintroducing outcome-based circularity. Progress is an observable effect, not a mechanism. It enriches the sub-label taxonomy but doesn't determine the primary regime.

5. **`unclassifiable` is a valid regime label for analysis.** It should appear in ≤5% of records (only when code is completely unparseable). If it exceeds 5%, the cases or the model configuration need investigation.

---

## Complete Mechanism Signals Schema (Final)

```json
"mechanism_signals": {
    "reasoning_consistent": true,
    "error_stable": true,
    "diff_localized": true,
    "progress_made": false
}
```

**Derivation chain:**

```
ground_truth_bug (from case schema)
    → critique_accuracy (per-iteration feedback vs ground truth)
    → reasoning_consistent (critique_accuracy ≥ 0.5 OR reasoning_valid + type match)

per_iteration.error_type (from test harness)
    → error_entropy (Shannon entropy over categories)
    → error_stable (entropy < 0.5)

candidate_code diff vs original (function-level)
    → edit_distance_to_bug (0/1/2)
    → diff_localized (distance ≤ 1)

per_iteration.score sequence
    → progress_made (any score increase)

mechanism_signals
    → failure_regime (priority logic: REI if rc+es, heuristic if !rc+es, CSF if !es)
    → failure_regime_sub (annotated with diff_localized + progress_made)
```

Every step is computable from logged data + case schema. No human labeling. No circular dependencies. No ambiguity.
