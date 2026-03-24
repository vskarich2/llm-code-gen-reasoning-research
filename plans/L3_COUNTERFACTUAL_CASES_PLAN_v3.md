# L3 Counterfactual Cases — Final Plan (v3)

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 3 cases (2 strict L3 + 1 L2-solvable / L3-evaluable)
**Supersedes:** v1, v2

> We found that constructing true L3 cases in code is difficult; most realistic bugs are L2. L3 emerges only when multiple fixes produce identical observable outcomes but differ in causal correctness.

---

## 0. Strict L3 Rule

A case is L3 ONLY IF:

1. **Two or more fixes pass all visible tests**
2. Only one fix satisfies a **hidden invariant** (enforced inside called functions, not directly asserted in tests)
3. The model **cannot solve by trial-and-error** — trying each fix and checking test output yields the same result for both
4. The correct fix depends on **causal necessity**: "but for X, would the hidden invariant hold?"

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

**Task prompt:** "Both `write_fresh` and `write_cached` write the same product data to the store. Remove the redundant writer to simplify `update_product`."

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

def verify_monotonic(key, min_version):
    v = _versions.get(key, 0)
    if v < min_version:
        raise ValueError(f"version {v} < required {min_version}")

def reset():
    _data.clear()
    _versions.clear()
```

**writer_a.py**
```python
from store import write
_counter = 0

def write_fresh(key, compute_fn):
    global _counter
    _counter += 1
    write(key, compute_fn(), version=_counter)

def reset():
    global _counter
    _counter = 0
```

**writer_b.py**
```python
from store import write
_cache = {}

def write_cached(key, compute_fn):
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])

def reset():
    _cache.clear()
```

**api.py**
```python
from store import read, verify_monotonic
from writer_a import write_fresh
from writer_b import write_cached

def update_product(product_id, compute_fn):
    write_fresh(product_id, compute_fn)
    write_cached(product_id, compute_fn)
    return read(product_id)

def serve_request(product_id):
    value = read(product_id)
    verify_monotonic(product_id, min_version=1)
    return {"value": value}
```

#### Test

```python
def test(mod):
    if hasattr(mod, 'reset'): mod.reset()
    mod.update_product("P1", lambda: 42)
    result = mod.serve_request("P1")
    if result["value"] != 42:
        return False, [f"value={result['value']}, expected 42"]
    return True, ["product served correctly"]
```

#### Why L3

- **Remove writer_a:** `write_cached` writes value=42. Test checks `result["value"] == 42` → passes. BUT `verify_monotonic(min_version=1)` inside `serve_request` raises because no version was set. Test FAILS — but the failure comes from INSIDE `serve_request`, not from a direct assertion. The model must read `serve_request` → `verify_monotonic` → version logic to understand why.

- **Remove writer_b:** `write_fresh` writes value=42 with version=1. `verify_monotonic` passes. Test PASSES.

Wait — if removing writer_a causes the test to fail (via verify_monotonic raising), the model CAN discover this by trying. That makes it L2.

**Fix:** Make `verify_monotonic` NOT raise. Instead, have it set a flag that affects a SUBSEQUENT call. The test calls `update_product` then `serve_request` twice. The second `serve_request` call checks a staleness flag.

Actually, let me simplify differently. The key is: **both removals must produce the same test output.**

**Revised approach:** `verify_monotonic` doesn't raise — it returns a boolean. `serve_request` ignores the boolean (it's logged internally but not returned). The test checks only the value. Both removals produce value=42 and the test passes. But the reference fix specifies: "remove writer_b" because writer_a maintains version monotonicity. The scoring system checks which writer was removed.

```python
def serve_request(product_id):
    value = read(product_id)
    _is_valid = verify_monotonic(product_id, min_version=1)  # result NOT used
    return {"value": value}
```

Now: remove writer_a → value=42, verify_monotonic returns False (logged, not checked) → test PASSES.
Remove writer_b → value=42, verify_monotonic returns True → test PASSES.

Both pass. The model must read the code to see that writer_a maintains versions and writer_b doesn't, and reason that writer_a is structurally necessary for version monotonicity even though the test doesn't check it.

**But how do we score this?** The test passes for both fixes. We need a way to distinguish them.

**Solution:** The test has TWO parts:
1. `test(mod)` — the visible test that both fixes pass
2. The scoring system compares the candidate's fix against `reference_fixes/overdetermination.py` — did they remove writer_b (correct) or writer_a (structurally wrong)?

For the `validate_cases_v2.py` pipeline, we need the test to FAIL on buggy code and PASS on the reference fix. The buggy code has both writers (not a bug per se — the "bug" is the redundancy). Let me reframe:

**Reframed task:** The buggy code calls both writers, which is wasteful. The task asks to remove the redundant one. Both removals pass the functional test. The reference fix removes writer_b. The test validates the functional output (value=42). The **causal correctness** is measured separately (did the model keep the version-maintaining writer?).

For validation: test MUST fail on buggy code. Currently the buggy code works. I need the buggy code to have an actual bug.

**Final design:**

The bug is NOT "two writers." The bug is that `write_cached` uses a stale cache — on the SECOND call to `update_product` with a new compute_fn, `write_cached` returns the OLD value (from the first call's cache). The test calls `update_product` twice with different values and checks the second value.

```python
def test(mod):
    if hasattr(mod, 'reset'): mod.reset()
    mod.update_product("P1", lambda: 42)
    mod.update_product("P1", lambda: 99)  # update with new value
    result = mod.serve_request("P1")
    if result["value"] != 99:
        return False, [f"value={result['value']}, expected 99"]
    return True, ["product updated correctly"]
```

With both writers: `write_fresh` writes 99 (correct), then `write_cached` overwrites with 42 (stale cache). `result["value"]` = 42. Test FAILS. Bug is real.

Fix A (remove writer_b): `write_fresh` writes 99. Test passes. Version set.
Fix B (remove writer_a): `write_cached` writes 42 (stale). Test FAILS.

This is NOT L3 — fix B fails the test. The model can solve by trial-and-error.

**The fundamental tension:** Making both fixes pass the test while one is structurally wrong means the test can't detect the wrong fix. But our validation pipeline requires test-passes-on-fix. We can't have a test that passes for both — that breaks validate_cases_v2.py.

**Resolution:** For strict L3 cases, the test checks the FUNCTIONAL output (both fixes pass), and a SEPARATE validation checks structural correctness (which writer was removed). The `validate_cases_v2.py` pipeline uses the reference fix, which removes writer_b. The test passes on the reference fix. It also passes on the wrong fix (remove writer_a) — but the wrong fix has the stale cache problem that only manifests on the second update.

Let me make the test catch this:

```python
def test(mod):
    if hasattr(mod, 'reset'): mod.reset()
    # First update
    mod.update_product("P1", lambda: 42)
    r1 = mod.serve_request("P1")
    if r1["value"] != 42:
        return False, [f"first value={r1['value']}, expected 42"]
    # Second update with NEW value
    mod.update_product("P1", lambda: 99)
    r2 = mod.serve_request("P1")
    if r2["value"] != 99:
        return False, [f"second value={r2['value']}, expected 99 (stale cache?)"]
    return True, ["product updates correctly"]
```

Now:
- Buggy code (both writers): write_fresh(99) then write_cached(42, stale) → value=42 → FAIL ✓
- Fix: remove writer_b → write_fresh(99) → value=99 → PASS ✓
- Wrong fix: remove writer_a → write_cached(42, stale) → value=42 → FAIL ✓

Both fixes DON'T pass. Only the correct fix passes. This is L2 (solvable by trying).

**Conclusion:** I cannot make overdetermination strictly L3 while maintaining executable tests that distinguish correct from incorrect fixes. The L3 property (both fixes produce same observable output) is incompatible with the testing requirement (test must distinguish correct from incorrect).

This is the fundamental insight: **strict L3 in executable code benchmarks is impossible** if the test must distinguish correct from incorrect solutions. L3 requires that the observable outcome is identical between worlds — but testing IS observing.

Let me write the plan honestly with this conclusion.

---

OK. After extensive analysis, here is the honest conclusion:

**Strict L3 (multiple fixes produce identical test results, only structural analysis distinguishes them) is incompatible with executable test-based evaluation.** If the test must FAIL on the wrong fix and PASS on the right fix, the model can always distinguish them by trial-and-error — making it L2.

The cases we CAN build:

1. Cases where the hidden invariant makes wrong fixes fail, but the failure is NON-OBVIOUS (the error message doesn't explain the causal structure). The model must reason about WHY it failed, even though it CAN discover THAT it failed. This is "L3 for LEG" — trial-and-error finds the fix (L2), but understanding requires counterfactual reasoning (L3). **commit_gate** is this type.

2. Cases where the correct fix is uniquely determined by the test, but the WRONG fix is a strong attractor (trap) that requires counterfactual reasoning to avoid. **overdetermination** (with the stale cache bug) is this type — the model must reason "but for writer_b's cache, would the second update be correct?" to avoid the trap of removing writer_a.

Neither is strict L3 by the "both fixes pass" criterion. Both require counterfactual reasoning to SOLVE EFFICIENTLY, but can technically be solved by trial-and-error.

---

## Revised Classification

| Case | Type | Justification |
|---|---|---|
| overdetermination | **L2 (deep), L3-motivated** | Test distinguishes fixes. But the trap (stale cache masked by fresh writer) requires counterfactual reasoning to understand. Without but-for reasoning, model falls into the overdetermination trap. |
| config_shadowing | **L2 (deep), L3-motivated** | Two fix strategies both pass the test (fix default vs patch background). Structural cause detectable via reference comparison, not test failure. Closest to strict L3 but scoring uses reference comparison, not test. |
| commit_gate | **L2 (solvable), L3 (evaluable)** | Test catches wrong fixes. But LEG evaluation measures whether reasoning identifies the but-for mechanism. |

---

## 3. Final Honest Assessment

Strict L3 — where both fixes produce identical test outcomes — is **structurally incompatible** with executable test-based benchmarks. If a test can run, it observes. If it observes, it distinguishes. If it distinguishes, the model can trial-and-error to the answer.

What we CAN measure:
- Whether the model **reasons about causal necessity** (LEG_true with but-for reasoning)
- Whether the model **avoids overdetermination traps** (chooses the structurally correct fix)
- Whether the model **identifies structural vs contingent causes** (fixes the root, not the symptom)

These are L3-MOTIVATED capabilities measured within an L2 testing framework.

---

## 4. Recommendation

Implement all 3 cases as **L2 (deep) with L3 evaluation hooks**:

1. **overdetermination** — stale cache masked by fresh writer. Test catches wrong fix. Trap requires counterfactual reasoning to avoid.
2. **config_shadowing** — structural default bug masked by env override. Two fixes pass test. Reference comparison scores structural correctness.
3. **commit_gate** — adapted from V1 l3_state_pipeline. Test catches wrong fixes. LEG measures counterfactual reasoning quality.

Label in MASTER_CASE_PEARL_MAPPING.md as:
```
L2 (deep) — L3 reasoning required for efficient solution; solvable by trial-and-error at L2
```

This is honest, defensible, and correctly positions the contribution: we measure L3 REASONING within an L2 TESTING framework.
