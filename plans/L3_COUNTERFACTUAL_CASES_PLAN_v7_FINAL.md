# L3 Counterfactual Cases — Final Plan (v7)

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 2 L3 cases + 1 deep L2 case
**Supersedes:** v1–v6

---

## 0. L3 Definition

L3 requires **identifying causal necessity by evaluating what would happen if candidate components were present or absent (but-for reasoning), and comparing this to the observed outcome.**

Specifically, the model must:

1. Observe a failure in the current code
2. Identify multiple plausible causes that could explain the failure
3. **Construct and evaluate an alternative execution** for each candidate cause — "if this component were present/absent/different, would the outcome change?"
4. Determine which components are **causally necessary** based on this counterfactual evaluation

**The alternative execution must be necessary to determine causal necessity. If forward reasoning alone suffices, the case is L2.**

L3 cases are not necessarily more complex than L2 cases, but differ qualitatively in requiring causal necessity reasoning rather than forward propagation.

---

## 1. Classification

| Case | Level | Justification |
|---|---|---|
| **config_shadowing** | **L3** | Forward tracing finds a contingent fix that passes the test. The structural cause is only identifiable by constructing a counterfactual: "if the env override were absent, would the request path also fail?" The model must evaluate an alternative execution that does not exist in the current code. |
| **commit_gate** | **L3** | Two absent steps, each independently necessary for a different downstream consumer. The failure does not isolate which step is responsible. The model must construct two alternative executions — reasoning about code that does not exist in the buggy version — to determine which components to restore. |
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

But this fix is contingent — it routes around the bad default rather than fixing it. To identify the structural cause, the model must construct an alternative execution that does not exist in the current code: "what would `handle_request()` return if `_OVERRIDES` did not contain `timeout`?" In this alternative execution, `get_config()` would return `{"timeout": 5}` — revealing that the default is structurally wrong and the env override is masking it.

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

#### Scoring

The `causal_correctness` metric checks:
1. Whether `defaults.py` was modified (file-level detection)
2. Whether the DEFAULTS dict's `"timeout"` value is 30 in the candidate code (value-level verification)

Both checks must pass for score 1.0. This prevents edge cases where `defaults.py` is modified but the timeout value is not actually corrected.

If only `service.py` is modified and `defaults.py` still has `timeout: 5` → contingent fix → 0.7.

#### Reference Fix

`defaults.py`: `"timeout": 5` → `"timeout": 30`

#### LEG Type: `PARTIAL_STATE_UPDATE`

---

### Case 2: commit_gate (L3)

**Task prompt:** "After simplifying the pipeline by removing `commit()` and `freeze_view()`, the system is broken. Restore the necessary steps. Return the updated code."

#### Real-World Motivation

This case reflects a common pattern in data processing systems: **staged vs committed state with view consistency**. Real systems (databases, event sourcing, CQRS architectures) maintain separation between:

- **Pending state** — data written but not yet validated/committed
- **Committed state** — data that has passed all checks and is the source of truth
- **View state** — a derived representation used by consumers, rebuilt from committed data

The `commit()` step (promoting pending to committed with a gate flag) and the `freeze_view()` step (rebuilding the consumer-facing view from the committed source of truth) serve different downstream consumers. Removing either one breaks a different invariant. This pattern appears whenever a system must support both "write and query" (needs commit) and "preview without side effects" (needs stage/commit separation).

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
    """Promote pending to stable. Sorts by id for canonical ordering. Sets frozen gate."""
    st["stable"] = sorted(st["pending"], key=lambda e: e["id"])
    st["meta"]["frozen"] = True

def freeze_view(st):
    """Rebuild view from committed (stable) data."""
    st["view"] = list(st["stable"])

def materialize(st):
    return list(st["view"])
```

**selectors.py**
```python
def get_committed_total(st):
    """Returns total only if state is committed (frozen). None otherwise."""
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

**pipeline.py (BUGGY — both steps removed)**
```python
from state import make_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize

def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # commit(st)       — removed as "redundant"
    # freeze_view(st)  — removed as "redundant"
    return st, materialize(st)
```

**api.py**
```python
from pipeline import process_batch
from selectors import get_committed_total, get_view_digest, get_committed_digest
from reducers import stage
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
    """Full pipeline: ingest then verify view is consistent with committed data."""
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

#### Why Both Steps Are Independently Necessary

**commit() is necessary for `get_committed_total`:**
- `commit()` sorts pending into stable and sets `frozen=True`
- `get_committed_total()` checks `frozen` — returns `None` if `False`
- Without commit: `frozen=False`, total is `None`

**freeze_view() is necessary for view-committed consistency:**
- `stage()` sets `view = pending` (insertion order, unsorted)
- `commit()` sets `stable = sorted(pending)` (canonical id order)
- `freeze_view()` sets `view = stable` (sorted, matching committed)
- Without freeze_view: `view` is unsorted (from stage), `stable` is sorted (from commit) → `get_view_digest() != get_committed_digest()` → `consistent=False`

| Restoration | committed_total | view-committed consistent | preview frozen | Test Result |
|---|---|---|---|---|
| Neither | None | False | False | **FAIL** (null total) |
| commit only | 30 | **False** (view unsorted, stable sorted) | False | **FAIL** (inconsistent) |
| freeze_view only | **None** (frozen=False) | False | False | **FAIL** (null total) |
| **Both** | 30 | True | False | **PASS** |

#### Test

```python
def test(mod):
    entries = [{"id": "b", "val": 20}, {"id": "a", "val": 10}]  # intentionally unsorted

    # Test ingest — requires commit
    result = mod.ingest(entries)
    if result["total"] is None:
        return False, ["committed total is null"]
    if result["total"] != 30:
        return False, [f"committed total={result['total']}, expected 30"]

    # Test consistency — requires freeze_view
    verified = mod.ingest_and_verify(entries)
    if not verified["consistent"]:
        return False, ["view and committed data are inconsistent"]

    # Test preview — must not freeze
    preview_result = mod.preview(entries)
    if preview_result["frozen"]:
        return False, ["preview must not freeze state"]

    return True, ["ingest, consistency, and preview all correct"]
```

**Non-diagnostic failure messages:**
- `"committed total is null"` — does not say "commit is missing" or "frozen is False"
- `"view and committed data are inconsistent"` — does not say "freeze_view is missing"
- `"preview must not freeze state"` — does not say "stage and commit must be separate"

#### Why L3

Two steps are absent from the buggy code. The model cannot forward-trace code that doesn't exist. It must construct alternative executions:

1. "If `commit()` were restored, what would happen?" The model must read `commit()`'s implementation (sorts pending, sets frozen), then mentally execute: `stage` runs → `commit` runs → `frozen=True`, `stable=sorted`. Then check: does `get_committed_total` work? Yes — frozen is True. Does the view match? No — view is still unsorted from stage. **Conclusion: commit alone is insufficient.**

2. "If `freeze_view()` were also restored, what would happen?" The model must read `freeze_view()`'s implementation (copies stable to view), then mentally execute: after commit, `view = stable` (sorted). Now `get_view_digest() == get_committed_digest()`. **Conclusion: both steps together are sufficient.**

This is counterfactual reasoning about absent code. The model builds a mental execution of functions that are not called in the buggy version, predicts their effects on state, and determines that both are causally necessary for the observed invariants.

#### Scoring

- Restore both `commit()` + `freeze_view()`: **1.0**
- Any partial restoration: **0.0** (test fails)

No ambiguity. Both steps required. The test enforces the necessity of each.

#### Reference Fix

In `pipeline.py`, restore both calls:
```python
    stage(st, merged)
    commit(st)
    freeze_view(st)
```

#### LEG Type: `INVARIANT_VIOLATION`

---

### Case 3: overdetermination (L2 deep)

**Task prompt:** "Product updates sometimes show stale data. Both `write_fresh` and `write_cached` write product data. Simplify by removing the redundant writer. Return the updated code."

#### Code

**store.py** — key-value store with reset.
**writer_a.py** — `write_fresh(key, compute_fn)`: computes fresh value, writes with version counter.
**writer_b.py** — `write_cached(key, compute_fn)`: caches result of first call, writes cached value on subsequent calls (no version).
**api.py** — `update_product` calls both writers; `serve_request` reads value.

(Full code unchanged from v6.)

#### Why L2

Forward tracing two calls to `update_product`:
1. First call: both writers compute and write 42. Store has 42.
2. Second call: `write_fresh` computes and writes 99. Then `write_cached` writes 42 (from cache). Store has 42 — stale.

The cause is directly visible in the execution trace. No counterfactual needed.

#### Test

```python
def test(mod):
    if hasattr(mod, 'reset'): mod.reset()
    mod.update_product("P1", lambda: 42)
    mod.update_product("P1", lambda: 99)
    result = mod.serve_request("P1")
    if result["value"] != 99:
        return False, [f"unexpected value after update: got {result['value']}, expected 99"]
    return True, ["product data correct"]
```

#### Reference Fix

Remove `write_cached` call from `update_product`.

#### LEG Type: `HIDDEN_DEPENDENCY`

---

## 3. Scoring Summary

| Case | 1.0 | 0.7 | 0.0 |
|---|---|---|---|
| config_shadowing | Fix `defaults.py` (timeout=30 verified) | Fix `service.py` only (contingent) | Test fails |
| commit_gate | Restore both `commit` + `freeze_view` | — | Any partial restoration |
| overdetermination | Remove `write_cached` | — | Wrong removal or no change |

No scoring contradictions. For config_shadowing, both file-modification AND value-correctness are verified to prevent edge cases.

---

## 4. LEG Compatibility

| Case | LEG Type | What LEG Measures |
|---|---|---|
| config_shadowing | PARTIAL_STATE_UPDATE | Does reasoning identify the default as the structural cause, not just the background path? |
| commit_gate | INVARIANT_VIOLATION | Does reasoning identify WHY commit (frozen gate) and freeze_view (view consistency) are each independently necessary? |
| overdetermination | HIDDEN_DEPENDENCY | Does reasoning identify the cache as the staleness source? |

All types from existing `FAILURE_TYPES` enum. No changes to LEG module.

---

## 5. Implementation Roadmap

```
Phase 1: Create 3 case directories + code files (~13 files)
Phase 2: Write 3 test files
Phase 3: Write 3 reference fixes
Phase 4: Write 3 CASE_DOC.md
Phase 5: Add to cases_v2.json (3 entries)
Phase 6: Run validate_cases_v2.py — all 6 checks must pass
Phase 7: Update MASTER_CASE_PEARL_MAPPING.md (2 L3 + 1 L2 deep)
Phase 8: Baseline experiment (3 cases × 2 models)
```

Estimated: ~500 lines of benchmark code. ~20 lines of retry_harness changes.

---

## 6. Key Insight

> L3 in code benchmarks emerges when correctness depends on reasoning about alternative executions, including absent steps and masked structural causes. Forward tracing follows code that exists. When the root cause is the absence of a step or the presence of a configuration mask, the model must construct an alternative execution — "what would this system do if the absent step were present?" or "what would happen without the mask?" — and compare it to the observed outcome. This is but-for reasoning applied to executable systems.
>
> L3 cases are not necessarily more complex than L2 cases, but differ qualitatively in requiring causal necessity reasoning rather than forward propagation. A model that perfectly traces forward execution but never asks "what would happen if this component were absent?" will solve L2 cases but fail L3 cases.
