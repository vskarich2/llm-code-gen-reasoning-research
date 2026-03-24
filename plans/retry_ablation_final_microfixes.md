# Retry Ablation — Final Micro-Fix Plan

**Date:** 2026-03-23
**Status:** PLAN ONLY — awaiting approval
**Scope:** 3 micro-fixes, no structural changes

---

## 1. File-Level Changes

### 1.1 `retry_harness.py`

**Rename: `trajectory_pattern` → `status_sequence`**

Location: summary construction (~line 420 area, in `run_retry_harness`)

```python
# BEFORE:
summary["trajectory_pattern"] = ["pass" if e["pass"] else "fail" for e in trajectory]

# AFTER:
summary["status_sequence"] = ["pass" if e["pass"] else "fail" for e in trajectory]
```

Also update any internal references to `trajectory_pattern` in:
- `_classify_trajectory_type` (reads scores, not this field — no change needed)
- Invariant I1 assertion in tests (update key name)

**Add: `attempt_progress` per trajectory entry**

Location: trajectory entry construction, inside the main loop

```python
# In the loop, when building entry dict:
entry = {
    ...
    "attempt_progress": round(k / max_iterations, 3),
    ...
}
```

This is a pure computation — no dependencies, no side effects.

**Add: `hint_used_type` per trajectory entry**

Location: after adaptive hint selection, in the main loop

```python
# After confidence gating logic:
if use_adaptive and not ev["pass"]:
    if classification["classifier_confidence"] >= 0.5:
        hint_used_type = classification["failure_type_final"]
    else:
        hint_used_type = "DEFAULT"
else:
    hint_used_type = None  # not a retry condition, or passed

entry = {
    ...
    "hint_used_type": hint_used_type,
    ...
}
```

Note: `hint_used_type` is `None` for:
- `baseline` condition (no retry)
- `retry_no_contract` and `retry_with_contract` (no adaptive)
- Passing iterations (no hint needed)

It is a string for `retry_adaptive` on failed iterations:
- The actual failure type if confidence ≥ 0.5
- `"DEFAULT"` if confidence < 0.5

---

### 1.2 `scripts/shadow_analysis.py`

**Rename reference:** `trajectory_pattern` → `status_sequence`

Any code reading summary logs must use the new field name.

```python
# BEFORE:
pattern = summary.get("trajectory_pattern", [])

# AFTER:
pattern = summary.get("status_sequence", [])
```

---

### 1.3 `tests/test_retry_harness.py`

**Update invariant I1:**

```python
# BEFORE:
assert len(summary["trajectory_pattern"]) == summary["total_iterations_executed"]

# AFTER:
assert len(summary["status_sequence"]) == summary["total_iterations_executed"]
```

**Add tests for new fields:**

```python
def test_attempt_progress_values():
    """attempt_progress = k / max_iterations for each entry."""
    for i, e in enumerate(summary["trajectory"]):
        expected = round(i / 5, 3)  # max_iterations=5
        assert e["attempt_progress"] == expected

def test_hint_used_type_present_on_adaptive():
    """retry_adaptive entries have hint_used_type on failed iterations."""
    for e in summary["trajectory"]:
        if not e["pass"] and summary["condition"] == "retry_adaptive":
            assert e["hint_used_type"] is not None
            assert e["hint_used_type"] in FAILURE_TYPES + ["DEFAULT"]

def test_hint_used_type_none_on_non_adaptive():
    """Non-adaptive conditions have hint_used_type = None."""
    # For retry_no_contract runs
    for e in summary["trajectory"]:
        if summary["condition"] == "retry_no_contract":
            assert e["hint_used_type"] is None

def test_status_sequence_matches_trajectory():
    """status_sequence derived from trajectory pass/fail."""
    expected = ["pass" if e["pass"] else "fail" for e in summary["trajectory"]]
    assert summary["status_sequence"] == expected
```

---

## 2. Updated Schemas

### 2.1 Trajectory Entry (additions only)

```json
{
    "attempt_progress": 0.2,          // NEW: k / max_iterations
    "hint_used_type": "TEMPORAL_ORDERING",  // NEW: actual hint type or "DEFAULT" or null
    // ... all existing fields unchanged ...
}
```

### 2.2 Summary (rename + no additions)

```json
{
    "status_sequence": ["fail", "fail", "pass"],     // RENAMED from trajectory_pattern
    "trajectory_failure_pattern": "converging",       // UNCHANGED
    // ... all other fields unchanged ...
}
```

---

## 3. Backward Compatibility

**This is a BREAKING CHANGE** for the `trajectory_pattern` field.

- The field `trajectory_pattern` no longer exists in summary records
- Replaced by `status_sequence`
- Any code reading `trajectory_pattern` from NEW logs will fail

**Impact assessment:**
- `scripts/shadow_analysis.py` — not yet implemented, no break
- `scripts/extract_metadata.py` — does not reference this field, no break
- Previous log files — unaffected (they keep their old field names)
- `tests/test_retry_harness.py` — will be updated as part of this change
- No external consumers exist

**Decision:** Breaking change is acceptable. The field has only existed for one session and no external consumers depend on it. Previous logs are archived with their own schema.

---

## 4. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `hint_used_type` inconsistent with `intervention.applied` | Low | Medium | Test assertion: `hint_used_type != None` iff `intervention.applied == True` OR confidence < 0.5 with DEFAULT |
| `attempt_progress` wrong on stagnation break | Low | Low | Progress is k/max_iterations regardless of early termination — this is by design (shows where in the budget the run stopped) |
| Shadow analysis reads old field name | None | None | shadow_analysis.py not yet written — will use new name from the start |
| Existing invariant tests reference old field | Certain | Low | Update tests in same commit |

**No high-risk items.** All changes are additive or simple renames with no logic changes.

---

## 5. Validation Plan

### Unit tests (run immediately after changes):
1. `test_attempt_progress_values` — verify k/max for each entry
2. `test_hint_used_type_present_on_adaptive` — non-null on adaptive failures
3. `test_hint_used_type_none_on_non_adaptive` — null on other conditions
4. `test_status_sequence_matches_trajectory` — derived correctly

### Integration (smoke test):
1. Run 1 case with `retry_adaptive` → verify `hint_used_type` in logs
2. Run 1 case with `retry_no_contract` → verify `hint_used_type` is null
3. Verify `status_sequence` appears (not `trajectory_pattern`)
4. Verify `attempt_progress` increases monotonically

### Regression:
1. All 234+ existing tests pass
2. All 9 data integrity invariants pass (with I1 updated)
3. Smoke test from previous session still works (alias_trivial, idempotency_trap)

---

## Summary

Three micro-fixes:
1. **Rename** `trajectory_pattern` → `status_sequence` (clarity)
2. **Add** `attempt_progress` = k/max_iterations per entry (convergence curves)
3. **Add** `hint_used_type` per entry (tracks what hint was actually used after confidence gating)

Breaking change on `trajectory_pattern` — acceptable, no external consumers. All changes are in `retry_harness.py` + tests. Estimated: ~15 lines of code changes + ~20 lines of test additions.
