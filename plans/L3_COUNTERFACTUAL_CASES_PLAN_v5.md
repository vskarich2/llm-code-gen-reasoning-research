# L3 Counterfactual Cases — Final Plan (v5)

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 2 L3 cases + 1 deep L2 case
**Supersedes:** v1–v4

---

## 0. L3 Definition (Final)

L3 requires **identifying causal necessity by reasoning about what would happen if candidate causes were removed or altered (but-for reasoning).**

A case is L3 if:

1. The model **cannot solve it by forward tracing alone** — following the execution step-by-step from input to output does not uniquely identify the root cause
2. The model must construct and evaluate a **counterfactual**: "if component X were absent/different, would the outcome change?"
3. Multiple components are plausible causes, and the model must determine **which is causally necessary** via but-for elimination

**The discriminating test:** Can a model that perfectly traces forward execution (but never asks "what if X were absent?") solve this case? If yes → L2. If no → L3.

---

## 1. Classification

| Case | Level | Justification |
|---|---|---|
| **config_shadowing** | **L3** | Multiple fixes pass the test. Structural vs contingent cause requires counterfactual: "but for the env override, would the system still work?" Forward tracing of the current execution shows everything working on the request path — the model must reason about what happens WITHOUT the override to identify the structural cause. |
| **commit_gate** | **L3** | Two steps removed, each causally necessary for a different consumer. Failure message ("null total") does not isolate which step. Model must evaluate two counterfactuals: "what if commit were present?" and "what if freeze_view were present?" Neither is answerable by forward tracing the buggy code — the steps are absent. |
| **overdetermination** | **L2 (deep)** | Solvable by forward tracing: trace `update_product` call-by-call, observe that `write_cached` overwrites `write_fresh`'s value on the second call. No counterfactual needed — the execution sequence reveals the cause directly. |

---

## 2. Repo Structure

```
T3_code_generation_MVP/
  code_snippets_v2/
    config_shadowing/           # L3
      defaults.py
      env_config.py
      service.py
    commit_gate/                # L3
      state.py
      reducers.py
      selectors.py
      pipeline.py
      api.py
    overdetermination/          # L2 (deep)
      writer_a.py
      writer_b.py
      store.py
      api.py

  tests_v2/
    test_config_shadowing.py
    test_commit_gate.py
    test_overdetermination.py

  reference_fixes/
    config_shadowing.py
    commit_gate.py
    overdetermination.py
```

---

## 3. Case Designs

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

Forward tracing the buggy code shows: `run_background_job()` calls `get_defaults()` which returns `timeout: 5`. A pure forward-tracer would fix `run_background_job` to call `get_config()` instead — this passes the test.

But this is a **contingent fix**. The model must ask the counterfactual: "but for the env override in `get_config()`, would `handle_request()` also use timeout=5?" The answer is yes — the default is structurally wrong. The env override MASKS the bad default on the request path. Without the override, BOTH paths would fail.

A model that only forward-traces never discovers this. It sees `handle_request()` returning 30 and concludes that path is fine. Only by reasoning "what if the env override were absent?" does the model discover the structural cause.

**Two fixes pass the test:**
- Fix A (structural): change `defaults.py` timeout to 30. Root cause addressed.
- Fix B (contingent): change `run_background_job` to call `get_config()`. Symptom addressed.

Both produce `request=30, background=30`. The test passes for both.

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

#### Scoring

- Fix A (modify `defaults.py`): score **1.0** — structural cause addressed
- Fix B (modify `service.py` only): score **0.7** — contingent fix, test passes but root cause remains

Detection: the scoring system checks whether `defaults.py` was modified. If only `service.py` changed → contingent fix → 0.7.

#### Reference Fix

`defaults.py`: `"timeout": 5` → `"timeout": 30`

#### LEG Type: `PARTIAL_STATE_UPDATE`

---

### Case 2: commit_gate (L3)

**Task prompt:** "After simplifying the pipeline by removing `commit()` and `freeze_view()`, `ingest()` returns null totals and preview behaves incorrectly. Determine which removed steps are necessary and restore them. Return the updated code."

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

def get_display_items(st):
    return list(st["view"])
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
from selectors import get_committed_total
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
```

#### Why L3

Two steps are removed. The failure message says `"null total"`. Forward tracing the buggy code shows: `process_batch` runs `stage` but not `commit` or `freeze_view`. Then `ingest` calls `get_committed_total` which checks `frozen` — it's `False` → returns `None`.

A forward-tracer could identify that `commit` sets `frozen=True` and restore it. **But this only solves ONE of two problems.** The model must ALSO evaluate the second counterfactual: "what if I merge stage+commit instead of restoring them separately?" This requires reasoning about `preview()`:

- `preview()` calls `stage()` WITHOUT `commit()` — intentionally.
- If stage and commit were merged, `preview()` would set `frozen=True`, breaking preview semantics.
- The model must ask: "but for the separation of stage and commit, would preview still work?"

This second counterfactual is NOT discoverable by forward-tracing the buggy code. The buggy code has BOTH steps removed, so the model sees neither. It must:
1. Consider restoring commit → evaluate what commit does (sets frozen) → understand why total works
2. Consider merging stage+commit → evaluate what preview does (calls stage alone) → understand why merging breaks preview
3. Consider restoring freeze_view → evaluate what freeze_view does (rebuilds view from stable) → determine if it's necessary

Three absent steps, each with a different but-for justification. The model cannot forward-trace steps that don't exist in the code — it must reason counterfactually about what each step WOULD do if restored.

#### Test

```python
def test(mod):
    entries = [{"id": "a", "val": 10}, {"id": "b", "val": 20}]

    result = mod.ingest(entries)
    if result["total"] is None:
        return False, ["total is null after ingest"]
    if result["total"] != 30:
        return False, [f"total={result['total']}, expected 30"]

    preview_result = mod.preview(entries)
    if preview_result["frozen"]:
        return False, ["preview should not freeze state"]
    if len(preview_result["items"]) != 2:
        return False, [f"preview items={len(preview_result['items'])}, expected 2"]

    return True, ["ingest and preview correct"]
```

**Non-diagnostic failures:**
- `"total is null after ingest"` — doesn't say "commit is missing" or "frozen is False"
- `"preview should not freeze state"` — doesn't say "stage and commit must be separate"

#### Plausible Wrong Fixes

1. **Restore only commit:** Total works (frozen=True). But freeze_view not restored — view built from pending, not stable. Currently equivalent, but semantically incorrect. Test passes (stage sets view = data, which is correct for this case). So this is a partial fix that passes.
2. **Merge stage+commit into one function:** Total works. But preview calls the merged function → sets frozen=True → test fails ("preview should not freeze").
3. **Restore commit+freeze_view as separate calls:** Both tests pass. Correct fix.

Fix 1 (commit only) passes the test. Fix 3 (both) passes the test. The model must reason about whether freeze_view is necessary — and the answer depends on future usage, not current test coverage. This is the structural vs contingent distinction again. For scoring: both pass at 1.0 since the test can't distinguish them. But the reference fix restores both.

#### Reference Fix

In `pipeline.py`, restore both lines:
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

(Same as v4 — writer_a with fresh computation + version, writer_b with cache, api calls both.)

#### Why L2, Not L3

The model can solve this by forward tracing: trace `update_product("P1", lambda: 42)` then `update_product("P1", lambda: 99)`. On the second call:
1. `write_fresh("P1", lambda: 99)` → writes 99 to store
2. `write_cached("P1", lambda: 99)` → cache has "P1": 42 from first call → writes 42

The stale value (42) is directly observable by forward execution. No counterfactual needed.

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

## 4. Why These Classifications Are Correct

| Test | config_shadowing | commit_gate | overdetermination |
|---|---|---|---|
| Can forward tracing alone find the fix? | **No.** Forward trace of buggy code shows background returns 5. Forward fix: change background to call `get_config()`. This passes the test but is a contingent fix. Structural cause (bad default) is only discoverable by asking "what if the env override were absent?" | **No.** Two steps are absent from the code. The model must reason about what each step WOULD do if present — it cannot forward-trace code that doesn't exist. | **Yes.** Trace two calls to `update_product` and observe `write_cached` overwrites with stale value. |
| Does it require but-for reasoning? | **Yes.** "But for the env override, would the request path work?" → No. The default is structurally wrong. | **Yes.** "But for commit, would total be non-null?" → No (frozen gate). "But for stage/commit separation, would preview avoid freezing?" → No. | **No.** The cause is directly visible in the execution trace. |
| Pearl Level | **L3** | **L3** | **L2 (deep)** |

---

## 5. Scoring

| Score | Condition |
|---|---|
| 1.0 | Structural fix — addresses root cause |
| 0.7 | Contingent fix — passes test but root cause unaddressed (config_shadowing only) |
| 0.5 | Code runs, invariant fails |
| 0.2 | Code errors but reasoning identifies causal necessity |
| 0.0 | Code errors, reasoning wrong |

**causal_correctness** metric:
- config_shadowing: 1.0 if `defaults.py` modified, 0.7 if only `service.py` modified
- commit_gate: 1.0 if both `commit()` and `freeze_view()` restored, 0.8 if only `commit()` restored
- overdetermination: 1.0 if `write_cached` removed (standard pass/fail)

---

## 6. LEG Compatibility

All cases use existing `FAILURE_TYPES` enum. No changes to LEG evaluation module.

| Case | LEG Type | LEG Signal |
|---|---|---|
| config_shadowing | PARTIAL_STATE_UPDATE | Does reasoning identify the default as the structural cause, not just the background path? |
| commit_gate | INVARIANT_VIOLATION | Does reasoning identify why commit() is necessary (frozen gate) and why stage/commit must be separate (preview)? |
| overdetermination | HIDDEN_DEPENDENCY | Does reasoning identify the cache as the source of staleness? |

---

## 7. Implementation Roadmap

```
Phase 1: Create 3 case directories + code files (~13 files total)
Phase 2: Write 3 test files
Phase 3: Write 3 reference fixes
Phase 4: Write 3 CASE_DOC.md files
Phase 5: Add to cases_v2.json (3 entries)
Phase 6: Run validate_cases_v2.py
Phase 7: Update MASTER_CASE_PEARL_MAPPING.md (add 2 L3 + 1 L2 deep)
Phase 8: Baseline experiment
```

~400 lines of benchmark code. ~20 lines of retry_harness changes (counterfactual note in retry prompt for L3 cases).

---

## 8. Key Insight

> L3 in code benchmarks emerges when the model must reason about code that ISN'T there — absent steps, masked defaults, overriding configurations. Forward tracing can only follow code that exists. When the root cause is the ABSENCE of a step or the PRESENCE of a mask, the model must construct a counterfactual: "what would this system do if the absent step were present?" or "what would happen without the mask?" This is but-for reasoning — Pearl's L3 — applied to executable systems.
