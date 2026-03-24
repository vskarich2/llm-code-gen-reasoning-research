# L3 Counterfactual Cases — Final Plan (v4)

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 3 L3 cases extending the V2 benchmark
**Supersedes:** v1, v2, v3

---

## 0. Corrected L3 Definition

L3 requires **identifying causal necessity among multiple plausible explanations when the observed failure does not directly reveal the cause.**

A case is L3 if:

1. The test **FAILS** on buggy code and **PASSES** only on the correct fix (standard testability)
2. The failure message is **non-diagnostic** — it reports WHAT went wrong but not WHY or WHERE
3. **Multiple components** are plausible causes of the failure from local inspection
4. The model must determine **which component is causally necessary** for correctness by reasoning about what would happen if each candidate cause were modified

The key L3 property: **trial-and-error can find the fix, but understanding requires causal necessity reasoning.** The test distinguishes correct from incorrect — but the failure signal does not point to the root cause. The model must reason about but-for dependence across the causal graph to efficiently identify which of several plausible components is the actual cause.

This is distinct from L2, where the failure signal typically points toward the cause (e.g., "stock leaked: was 10, now 7" directly implicates the reservation logic).

---

## 1. Repo Structure

```
T3_code_generation_MVP/
  code_snippets_v2/
    overdetermination/
      writer_a.py
      writer_b.py
      store.py
      api.py
    config_shadowing/
      defaults.py
      env_config.py
      service.py
    commit_gate/
      state.py
      reducers.py
      selectors.py
      pipeline.py
      api.py

  tests_v2/
    test_overdetermination.py
    test_config_shadowing.py
    test_commit_gate.py

  reference_fixes/
    overdetermination.py
    config_shadowing.py
    commit_gate.py
```

---

## 2. Case Designs

---

### Case 1: overdetermination (L3)

**Task prompt:** "Product updates sometimes show stale data. Both `write_fresh` and `write_cached` write product data to the store. Simplify `update_product` by removing the redundant writer. Return the updated code."

#### Code

**store.py**
```python
_data = {}
_versions = {}

def write(key, value, version=None):
    _data[key] = value
    if version is not None:
        _versions[key] = version

def read(key):
    return _data.get(key)

def get_version(key):
    return _versions.get(key, 0)

def reset():
    _data.clear()
    _versions.clear()
```

**writer_a.py**
```python
from store import write

_counter = 0

def write_fresh(key, compute_fn):
    """Compute value fresh and write with version tracking."""
    global _counter
    _counter += 1
    value = compute_fn()
    write(key, value, version=_counter)
    return value

def reset():
    global _counter
    _counter = 0
```

**writer_b.py**
```python
from store import write

_cache = {}

def write_cached(key, compute_fn):
    """Write from cache if available, else compute and cache."""
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])  # no version
    return _cache[key]

def reset():
    _cache.clear()
```

**api.py**
```python
from store import read, get_version
from writer_a import write_fresh
from writer_b import write_cached

def update_product(product_id, compute_fn):
    """Update product data. Uses both writers (redundant)."""
    write_fresh(product_id, compute_fn)
    write_cached(product_id, compute_fn)
    return read(product_id)

def serve_request(product_id):
    """Serve product data with version."""
    return {"value": read(product_id), "version": get_version(product_id)}
```

#### The Bug

`write_cached` uses a stale cache: on the second call to `update_product` with a new `compute_fn`, `write_cached` returns the cached value from the FIRST call, overwriting the fresh value that `write_fresh` just wrote. The final store value is stale.

Both writers appear to do the same thing on the first call. The staleness only manifests on the second call with a different value.

#### Test

```python
def test(mod):
    """Non-diagnostic failure: reports wrong value, does not name the cause."""
    if hasattr(mod, 'reset'): mod.reset()

    mod.update_product("P1", lambda: 42)
    mod.update_product("P1", lambda: 99)  # update with new value

    result = mod.serve_request("P1")
    if result["value"] != 99:
        return False, [f"unexpected value after update: got {result['value']}, expected 99"]
    return True, ["product data correct after update"]
```

**Non-diagnostic failure message:** `"unexpected value after update: got 42, expected 99"`. This says WHAT is wrong (stale value) but not WHY (which writer caused it) or WHERE (writer_b's cache).

#### Why L3

The failure message ("unexpected value after update") is consistent with multiple plausible causes:

- **writer_a is broken** — maybe `write_fresh` doesn't actually compute fresh values
- **writer_b overwrites** — maybe `write_cached` writes a stale value after `write_fresh`
- **store.write has a bug** — maybe the store doesn't properly overwrite
- **The compute_fn is wrong** — maybe lambda: 99 doesn't return 99

The model must determine which component is **causally necessary** for the staleness. The but-for test: "but for `write_cached` running after `write_fresh`, would the store contain 99?" Yes — `write_fresh` correctly writes 99 with a version. `write_cached` then overwrites with 42 (cached from the first call). The fix is to remove `write_cached`.

The model cannot rely on the error message to identify the cause. It must trace the execution of `update_product` across two calls, understand the cache semantics of `write_cached`, and apply but-for reasoning to determine that `write_cached` (not `write_fresh`) is the overdetermining cause that introduces staleness.

#### Reference Fix

In `api.py`, remove the `write_cached` call:

```python
def update_product(product_id, compute_fn):
    write_fresh(product_id, compute_fn)
    return read(product_id)
```

#### LEG Failure Type

`HIDDEN_DEPENDENCY` — the cache in writer_b creates a hidden dependency between the first and second calls.

---

### Case 2: config_shadowing (L3)

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
    """Defaults merged with environment overrides."""
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
    """Request handler — uses full config chain (timeout=30, correct)."""
    return {"timeout": get_config()["timeout"], "source": "request"}

def run_background_job():
    """Background job — reads defaults directly (timeout=5, WRONG)."""
    return {"timeout": get_defaults()["timeout"], "source": "background"}

def run_system_check():
    """Run both paths and return results."""
    return {
        "request": handle_request(),
        "background": run_background_job(),
    }
```

#### The Bug

`defaults.py` has `timeout: 5` (wrong). `env_config.py` overrides to 30. `handle_request()` uses the full config chain → gets 30 (correct by accident). `run_background_job()` uses `get_defaults()` directly → gets 5 (wrong).

The structural cause is the bad default. The env override is a contingent mask.

#### Test

```python
def test(mod):
    """Non-diagnostic: reports wrong timeout, does not identify config layer."""
    if hasattr(mod, 'reset'): mod.reset()

    result = mod.run_system_check()
    req = result["request"]["timeout"]
    bg = result["background"]["timeout"]

    if req != 30:
        return False, [f"request timeout incorrect: got {req}, expected 30"]
    if bg != 30:
        return False, [f"background timeout incorrect: got {bg}, expected 30"]
    return True, ["all timeouts correct"]
```

**Non-diagnostic failure message:** `"background timeout incorrect: got 5, expected 30"`. Says the background timeout is wrong but not WHERE the 5 comes from or WHICH config layer to fix.

#### Why L3

Multiple plausible fixes exist:

- **Fix A (structural):** Change `defaults.py` timeout from 5 to 30. Both paths now use correct default. The env override becomes redundant (still correct).
- **Fix B (contingent):** Change `run_background_job()` to call `get_config()` instead of `get_defaults()`. Background now gets the override. But the default is still wrong — any future path using `get_defaults()` will inherit 5.

**Both fixes pass the test.** Fix A changes `defaults.py`. Fix B changes `service.py`. The test checks `request==30` and `background==30` — both fixes achieve this.

The model must determine: is the default the **structural cause** (it's wrong in the source of truth) or is the background job's config choice the cause? The but-for test: "but for the bad default, would any code path produce a wrong timeout?" No — if the default were 30, both `get_config()` and `get_defaults()` would return 30.

**Scoring:** Both fixes pass the test (score 1.0 on functional correctness). The `causal_correctness` metric checks whether `defaults.py` was modified: if yes → structural fix (1.0). If only `service.py` was modified → contingent fix (0.7). This distinction is measured by the scoring system, not the test.

#### Reference Fix

In `defaults.py`: `"timeout": 5` → `"timeout": 30`.

#### LEG Failure Type

`PARTIAL_STATE_UPDATE` — the default is structurally wrong but partially masked by the env override.

---

### Case 3: commit_gate (L3)

**Task prompt:** "The pipeline has redundant steps. `stage()` already writes data to the state, so `commit()` and `freeze_view()` appear to be unnecessary wrappers. Remove the redundant steps to simplify `process_batch`. Return the updated code."

#### Code

**state.py**
```python
def make_state(entries):
    return {
        "raw": list(entries),
        "pending": [],
        "stable": [],
        "view": [],
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

**pipeline.py**
```python
from state import make_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize

def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    commit(st)
    freeze_view(st)
    return st, materialize(st)
```

**api.py**
```python
from pipeline import process_batch
from selectors import get_committed_total, get_display_items
from reducers import stage

def ingest(entries):
    st, items = process_batch(entries)
    total = get_committed_total(st)
    return {"items": items, "total": total}

def preview(entries):
    """Preview without committing — stage only, no commit."""
    from state import make_state
    from reducers import normalize, collapse
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)  # stage WITHOUT commit — intentional
    return {"items": list(st["view"]), "frozen": st["meta"]["frozen"]}
```

#### The Bug (or rather, the trap)

There IS no bug in the current code. The task CLAIMS commit() and freeze_view() are redundant. The model must determine that they are NOT redundant — each is causally necessary for a different downstream consumer:

- `commit()` is necessary for `get_committed_total()` — it sets `frozen=True`, which is a precondition
- The stage/commit separation is necessary for `preview()` — preview calls stage WITHOUT commit

#### Test

```python
def test(mod):
    """Non-diagnostic: checks ingest and preview outcomes without naming steps."""
    entries = [{"id": "a", "val": 10}, {"id": "b", "val": 20}]

    # Test ingest
    result = mod.ingest(entries)
    if result["total"] is None:
        return False, ["ingest returned null total"]
    if result["total"] != 30:
        return False, [f"ingest total={result['total']}, expected 30"]

    # Test preview
    preview = mod.preview(entries)
    if preview["frozen"]:
        return False, ["preview should not freeze state"]
    if len(preview["items"]) != 2:
        return False, [f"preview items count={len(preview['items'])}, expected 2"]

    return True, ["ingest and preview both correct"]
```

**Non-diagnostic failure messages:**
- If commit() removed: `"ingest returned null total"` — doesn't say "commit() is missing" or "frozen is False"
- If stage+commit merged: `"preview should not freeze state"` — doesn't say "stage and commit must be separate"

#### Why L3

The task explicitly claims two steps are redundant. The model must determine that NEITHER is redundant by applying two but-for tests:

1. "But for commit(), would get_committed_total() return a value?" → No, it returns None (frozen gate).
2. "But for the stage/commit separation, would preview() avoid freezing?" → No, a merged function would set frozen=True during preview.

Multiple plausible "fixes" exist:
- Remove commit() (test fails — null total)
- Remove freeze_view() (test may pass — but the pipeline semantics are degraded)
- Merge stage+commit (test fails — preview freezes)
- Keep all steps (test passes — correct answer)

The failure messages ("null total", "preview should not freeze") do NOT name the pipeline steps. The model must trace through `ingest → process_batch → commit → frozen=True → get_committed_total checks frozen` to connect the failure to the cause.

#### Reference Fix

No code change — the correct answer is to keep the pipeline as-is and explain why each step is necessary. For the test: the buggy code IS the correct code. The "bug" is the task's false claim of redundancy.

Wait — this breaks our validation pipeline (test must FAIL on buggy code). Let me reframe.

**Reframed:** The buggy version HAS commit() and freeze_view() already removed (someone applied the "simplification" the task describes). The task says "the simplified pipeline broke ingest and preview — restore the necessary steps."

**Buggy pipeline.py:**
```python
def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # commit(st)      — REMOVED as "redundant"
    # freeze_view(st) — REMOVED as "redundant"
    return st, materialize(st)
```

**Task prompt (revised):** "After simplifying the pipeline by removing commit() and freeze_view(), ingest() returns null totals and preview() behavior is wrong. Determine which removed steps are necessary and restore them. Return the updated code."

Now:
- Buggy code: commit and freeze_view removed → test FAILS (null total) ✓
- Reference fix: restore both → test PASSES ✓

The L3 character: the failure message says "null total" — the model must trace through the selector to find that `frozen=False` causes the null, then trace back to find that `commit()` sets frozen. Then it must ALSO discover that freeze_view is necessary (or at least not harmful) and that stage/commit must remain separate for preview.

#### Reference Fix (revised)

In `pipeline.py`, restore commit() and freeze_view():
```python
def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    commit(st)       # restored
    freeze_view(st)  # restored
    return st, materialize(st)
```

#### LEG Failure Type

`INVARIANT_VIOLATION` — removing commit violates the frozen gate invariant.

---

## 3. Classification

| Case | Pearl Level | L3 Mechanism | Non-Diagnostic Failure |
|---|---|---|---|
| **overdetermination** | L3 | Multiple plausible causes (writer_a broken? writer_b stale? store bug?). Model must identify which writer is causally necessary via but-for reasoning on the cache. | "unexpected value after update: got 42, expected 99" |
| **config_shadowing** | L3 | Multiple valid fixes (fix default vs patch background). Model must identify structural vs contingent cause. Both fixes pass the test — scoring distinguishes structural correctness. | "background timeout incorrect: got 5, expected 30" |
| **commit_gate** | L3 | Multiple removed steps to evaluate. Model must determine which are causally necessary for which downstream consumers via but-for reasoning. | "ingest returned null total" / "preview should not freeze state" |

---

## 4. Scoring

| Score | Condition |
|---|---|
| 1.0 | Correct fix addressing the structural cause |
| 0.7 | Contingent fix — passes test but doesn't address root cause (config_shadowing only) |
| 0.5 | Code runs, invariant fails |
| 0.2 | Code errors but reasoning identifies causal necessity |
| 0.0 | Code errors, reasoning wrong |

The 0.7 tier applies only to `config_shadowing` where two fixes pass the test. For `overdetermination` and `commit_gate`, wrong fixes fail the test (score 0.0 or 0.5).

**causal_correctness metric:** For config_shadowing, checks whether `defaults.py` was modified (structural fix = 1.0) vs only `service.py` (contingent fix = 0.7).

---

## 5. LEG Compatibility

All 3 cases use existing `FAILURE_TYPES` enum:
- overdetermination → `HIDDEN_DEPENDENCY`
- config_shadowing → `PARTIAL_STATE_UPDATE`
- commit_gate → `INVARIANT_VIOLATION`

LEG_true measures: did the model's reasoning correctly identify the causal mechanism? For L3 cases, this means: did the reasoning identify WHICH component is causally necessary and WHY?

The blind evaluator receives: code + non-diagnostic failure message + reasoning. It judges whether the reasoning identifies the root cause. The non-diagnostic failure message is the L3 signal — it forces the evaluator to assess whether the model reasoned beyond the error message to the structural cause.

---

## 6. Retry Prompt

Standard retry_harness prompt with one addition for L3 cases:

```
=== Test Results (FAILED) ===
unexpected value after update: got 42, expected 99

Note: the error message reports the symptom, not the cause.
Multiple components could be responsible.
Determine which component is causally necessary for correct behavior.
```

The "Note" line is added for L3 cases only. It does NOT name the components or the cause — it just signals that the model should reason about causation rather than pattern-matching the error message.

---

## 7. Implementation Roadmap

```
Phase 1: Create case directories + code files (3 cases × 4-5 files = ~14 files)
Phase 2: Write tests (3 test files, ~30 lines each)
Phase 3: Write reference fixes (3 files)
Phase 4: Write CASE_DOC.md (3 files)
Phase 5: Add to cases_v2.json (3 entries)
Phase 6: Update MASTER_CASE_PEARL_MAPPING.md
Phase 7: Run validate_cases_v2.py
Phase 8: Baseline experiment (3 cases × 2 models)
```

Estimated: ~500 lines of benchmark code, ~50 lines of retry_harness changes.

---

## 8. Key Insight

> L3 in code benchmarks does not require indistinguishable outcomes. It requires **non-diagnostic failures with multiple plausible causes**, where the model must apply causal necessity reasoning to identify the root cause. The test catches the wrong fix — but the error message doesn't point to the right one. The model must reason about "but for X, would Y change?" to bridge the gap between symptom and cause.
