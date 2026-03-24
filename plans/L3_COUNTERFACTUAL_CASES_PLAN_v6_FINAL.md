# L3 Counterfactual Cases — Final Plan (v6)

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 2 L3 cases + 1 deep L2 case
**Supersedes:** v1–v5

---

## 0. L3 Definition (Final)

L3 requires **identifying causal necessity by evaluating what would happen if candidate components were present or absent (but-for reasoning), and comparing this to the observed outcome.**

Specifically, the model must:

1. Observe a failure in the current code
2. Identify multiple plausible causes that could explain the failure
3. **Construct and evaluate an alternative execution** for each candidate cause — "if this component were present/absent/different, would the outcome change?"
4. Determine which components are **causally necessary** based on this counterfactual evaluation

**The discriminating test:** Can a model that perfectly traces forward execution (but never constructs an alternative execution to compare against) solve this case? If yes → L2. If no → L3.

---

## 1. Classification

| Case | Level | Justification |
|---|---|---|
| **config_shadowing** | **L3** | Forward tracing finds a contingent fix that passes the test. The structural cause is only identifiable by constructing a counterfactual: "if the env override were absent, would the request path also fail?" The model must evaluate an alternative execution that does not exist in the current code. |
| **commit_gate** | **L3** | Two absent steps, each independently necessary. The failure does not isolate which step is responsible. The model must construct two alternative executions: "what would happen if commit were restored?" and "what would happen if freeze_view were restored?" — reasoning about code that does not exist in the buggy version. |
| **overdetermination** | **L2 (deep)** | Forward tracing of two `update_product` calls directly reveals that `write_cached` overwrites with a stale value. No alternative execution needed. |

---

## 2. Case Designs

---

### Case 1: config_shadowing (L3)

**Task prompt:** "The background job uses the wrong timeout (5 instead of 30). Fix the configuration. Return the updated code."

#### Code

**defaults.py**
```python
DEFAULTS = {"timeout": 5, "retries": 3}  # BUG: timeout should be 30

def get_defaults():
    return dict(DEFAULTS)
```

**env_config.py**
```python
_OVERRIDES = {"timeout": 30}

def get_config():
    from defaults import get_defaults
    cfg = get_defaults()
    cfg.update(_OVERRIDES)
    return cfg
```

**service.py**
```python
from env_config import get_config
from defaults import get_defaults

def handle_request():
    return {"timeout": get_config()["timeout"], "source": "request"}

def run_background_job():
    return {"timeout": get_defaults()["timeout"], "source": "background"}

def run_system_check():
    return {"request": handle_request(), "background": run_background_job()}
```

#### Why L3

Forward tracing the buggy code: `run_background_job()` → `get_defaults()` → returns `{"timeout": 5}`. A forward-tracer fixes `run_background_job` to call `get_config()` instead. Test passes.

But this fix is contingent. To identify the structural cause, the model must construct an alternative execution that does not exist in the current code: "what would `handle_request()` return if `_OVERRIDES` did not contain `timeout`?" In this alternative execution, `get_config()` would return `{"timeout": 5}` — revealing that the default is structurally wrong and the env override is masking it.

The model never observes `handle_request()` failing. It must construct the counterfactual to discover that the request path's correctness is contingent on the override.

#### Test

```python
def test(mod):
    if hasattr(mod, 'reset'): mod.reset()
    result = mod.run_system_check()
    req = result["request"]["timeout"]
    bg = result["background"]["timeout"]
    if req != 30:
        return False, [f"request timeout incorrect: {req}"]
    if bg != 30:
        return False, [f"background timeout incorrect: {bg}"]
    return True, ["all timeouts correct"]
```

Two fixes pass:
- Fix A (structural): `defaults.py` timeout 5→30. Score **1.0**.
- Fix B (contingent): `service.py` background calls `get_config()`. Score **0.7**.

#### Reference Fix

`defaults.py`: `"timeout": 5` → `"timeout": 30`

#### LEG Type: `PARTIAL_STATE_UPDATE`

---

### Case 2: commit_gate (L3)

**Task prompt:** "After simplifying the pipeline by removing `commit()` and `freeze_view()`, the system is broken. Restore the necessary steps. Return the updated code."

#### Code

**state.py**
```python
def make_state(entries):
    return {
        "raw": list(entries),
        "pending": [], "stable": [], "view": [],
        "meta": {"version": 0, "frozen": False},
    }
```

**reducers.py**
```python
def normalize(raw):
    return [dict(e) for e in raw]

def collapse(entries):
    merged = {}
    for e in entries:
        merged[e["id"]] = e
    return list(merged.values())

def stage(st, data):
    st["pending"] = list(data)
    st["view"] = list(data)
    st["meta"]["version"] += 1

def commit(st):
    st["stable"] = list(st["pending"])
    st["meta"]["frozen"] = True

def freeze_view(st):
    st["view"] = list(st["stable"])

def materialize(st):
    return list(st["view"])
```

**selectors.py**
```python
def get_committed_total(st):
    if not st["meta"]["frozen"]:
        return None
    return sum(e.get("val", 0) for e in st["stable"])

def get_view_total(st):
    return sum(e.get("val", 0) for e in st["view"])
```

**pipeline.py (BUGGY — both steps removed)**
```python
from state import make_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize

def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # commit(st)       — removed
    # freeze_view(st)  — removed
    return st, materialize(st)
```

**api.py**
```python
from pipeline import process_batch
from selectors import get_committed_total, get_view_total
from reducers import stage, commit
from state import make_state

def ingest(entries):
    st, items = process_batch(entries)
    total = get_committed_total(st)
    return {"items": items, "total": total}

def preview(entries):
    from reducers import normalize, collapse
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    return {"items": list(st["view"]), "frozen": st["meta"]["frozen"]}

def ingest_and_verify(entries):
    """Full pipeline: ingest then verify view matches committed."""
    st, items = process_batch(entries)
    committed_total = get_committed_total(st)
    view_total = get_view_total(st)
    return {
        "items": items,
        "committed_total": committed_total,
        "view_total": view_total,
        "view_matches_committed": committed_total == view_total,
    }
```

#### Why Both Steps Are Independently Necessary

**commit() is necessary for `get_committed_total`:**
- `commit()` sets `frozen=True` and copies `pending→stable`
- `get_committed_total()` checks `frozen` — returns `None` if `False`
- Without commit: `frozen=False`, total is `None`

**freeze_view() is necessary for `ingest_and_verify`:**
- `stage()` sets `view = pending` (from raw merged data)
- `commit()` sets `stable = pending` (same data at this point)
- `freeze_view()` sets `view = stable` (rebuilds view from committed data)
- Without freeze_view: `view` is set by `stage()` and `stable` is set by `commit()`. In the simple case they contain the same data. BUT: `ingest_and_verify()` checks `view_matches_committed` — it compares `get_view_total(st)` against `get_committed_total(st)`.

Wait — if both are set from `pending` (which equals `merged`), they'll have the same values. `view_matches_committed` would be `True` even without `freeze_view`. That means `freeze_view` is NOT necessary for the test to pass.

Let me fix this. I need `freeze_view` to be genuinely necessary. The issue: after `stage`, `view = pending`. After `commit`, `stable = pending`. So `view == stable` trivially. `freeze_view` just sets `view = stable` — a no-op in this sequence.

**Fix:** Make `commit()` transform the data (e.g., sort, or add a computed field), so `stable ≠ pending`. Then `freeze_view()` rebuilds view from the transformed stable, and without it, view is stale (from stage's raw pending).

**Revised commit:**
```python
def commit(st):
    """Commit pending to stable. Sorts by id and sets frozen."""
    st["stable"] = sorted(st["pending"], key=lambda e: e["id"])
    st["meta"]["frozen"] = True
```

Now:
- `stage()` sets `view = pending` (unsorted)
- `commit()` sets `stable = sorted(pending)` (sorted) + `frozen=True`
- `freeze_view()` sets `view = stable` (sorted)

Without `freeze_view`: `view` is unsorted (from stage), `stable` is sorted (from commit). `get_view_total` and `get_committed_total` return the same SUM (order doesn't affect sum). So the totals still match.

This still doesn't make `freeze_view` necessary for a sum check. I need a check that is ORDER-SENSITIVE.

**Revised selectors.py:**
```python
def get_committed_total(st):
    if not st["meta"]["frozen"]:
        return None
    return sum(e.get("val", 0) for e in st["stable"])

def get_view_digest(st):
    """Order-sensitive digest of view items."""
    return "|".join(e["id"] for e in st["view"])

def get_committed_digest(st):
    """Order-sensitive digest of committed items."""
    if not st["meta"]["frozen"]:
        return None
    return "|".join(e["id"] for e in st["stable"])
```

**Revised api.py `ingest_and_verify`:**
```python
def ingest_and_verify(entries):
    st, items = process_batch(entries)
    committed_total = get_committed_total(st)
    view_digest = get_view_digest(st)
    committed_digest = get_committed_digest(st)
    return {
        "items": items,
        "committed_total": committed_total,
        "consistent": view_digest == committed_digest,
    }
```

Now:
- With both steps: view=sorted (from freeze_view rebuilding from sorted stable), committed=sorted → digests match → `consistent=True`
- commit only (no freeze_view): view=unsorted (from stage), committed=sorted → digests DON'T match → `consistent=False`
- freeze_view only (no commit): frozen=False → committed_total=None, committed_digest=None → `consistent=False` (None != string)

**Both steps are independently necessary.** Removing either one causes the test to fail.

#### Test

```python
def test(mod):
    entries = [{"id": "b", "val": 20}, {"id": "a", "val": 10}]  # intentionally unsorted

    # Test ingest
    result = mod.ingest(entries)
    if result["total"] is None:
        return False, ["committed total is null"]
    if result["total"] != 30:
        return False, [f"committed total={result['total']}, expected 30"]

    # Test consistency (requires freeze_view)
    verified = mod.ingest_and_verify(entries)
    if not verified["consistent"]:
        return False, ["view and committed data are inconsistent"]

    # Test preview (must not freeze)
    preview_result = mod.preview(entries)
    if preview_result["frozen"]:
        return False, ["preview must not freeze state"]

    return True, ["ingest, consistency, and preview all correct"]
```

**Non-diagnostic failures:**
- `"committed total is null"` — doesn't say commit is missing
- `"view and committed data are inconsistent"` — doesn't say freeze_view is missing
- `"preview must not freeze state"` — doesn't say stage/commit must be separate

**Critical:** Restoring only commit → `"view and committed data are inconsistent"` (freeze_view missing). Restoring only freeze_view → `"committed total is null"` (commit missing). Both must be restored.

#### Why L3

Two steps are absent. The model must construct TWO alternative executions:

1. "If commit() were restored, what would happen?" → `frozen=True`, `stable=sorted(pending)`, total=30. But view is still unsorted (from stage) → inconsistent.
2. "If freeze_view() were ALSO restored, what would happen?" → view rebuilt from sorted stable → consistent.

Neither alternative execution exists in the current code. The model must reason about absent code — constructing counterfactual executions for code it must write. Forward tracing the buggy code only shows: stage runs, nothing else happens, total is null. The model cannot forward-trace `commit()` or `freeze_view()` because they are not called.

#### Reference Fix

In `pipeline.py`, restore both:
```python
    stage(st, merged)
    commit(st)
    freeze_view(st)
```

#### Scoring

- Restore both commit + freeze_view: **1.0**
- Restore commit only: **0.0** (test fails — inconsistent)
- Restore freeze_view only: **0.0** (test fails — null total)
- Neither restored: **0.0** (test fails — null total)

No ambiguity. Both steps required. No partial credit for partial restoration — the test enforces necessity of both.

#### LEG Type: `INVARIANT_VIOLATION`

---

### Case 3: overdetermination (L2 deep)

Unchanged from v5. Forward-traceable. See v5 §2 Case 3 for full design.

---

## 3. Scoring Summary

| Case | 1.0 | 0.7 | 0.0 |
|---|---|---|---|
| config_shadowing | Fix defaults.py | Fix service.py only (contingent) | Test fails |
| commit_gate | Restore both commit+freeze_view | — | Any partial restoration |
| overdetermination | Remove write_cached | — | Remove write_fresh or no change |

**No scoring contradictions.** Every score level maps to a clearly defined fix category. The test outcome and the scoring are aligned:

- config_shadowing: both fixes pass the test → scoring distinguishes structural (1.0) from contingent (0.7) via reference comparison
- commit_gate: only the complete fix passes the test → scoring is binary (1.0 or 0.0)
- overdetermination: only the correct removal passes → binary

---

## 4. LEG Compatibility

| Case | LEG Type | What LEG Measures |
|---|---|---|
| config_shadowing | PARTIAL_STATE_UPDATE | Does reasoning identify the default as the structural cause (not just the background path)? |
| commit_gate | INVARIANT_VIOLATION | Does reasoning identify WHY commit (frozen gate) and freeze_view (view consistency) are each necessary? |
| overdetermination | HIDDEN_DEPENDENCY | Does reasoning identify the cache as the staleness source? |

All types from existing `FAILURE_TYPES` enum. No changes to LEG module.

---

## 5. Implementation Roadmap

```
Phase 1: Create 3 case directories + code files (~13 files)
Phase 2: Write 3 test files
Phase 3: Write 3 reference fixes
Phase 4: Write 3 CASE_DOC.md
Phase 5: Add to cases_v2.json
Phase 6: Run validate_cases_v2.py
Phase 7: Update MASTER_CASE_PEARL_MAPPING.md
Phase 8: Baseline experiment
```

---

## 6. Key Insight

> L3 in code benchmarks emerges when the model must reason about code that ISN'T there — absent steps, masked defaults, overriding configurations. Forward tracing follows code that exists. When the root cause is the absence of a step or the presence of a mask, the model must construct an alternative execution: "what would this system do if the absent step were present?" or "what would happen without the mask?" This is but-for reasoning — Pearl's L3 — applied to executable systems.
