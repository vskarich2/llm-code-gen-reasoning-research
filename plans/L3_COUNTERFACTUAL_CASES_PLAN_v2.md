# L3 Counterfactual Cases — Implementation Plan v2

**Date:** 2026-03-24
**Status:** PLAN ONLY — awaiting approval
**Scope:** 5 cases (3 true L3, 2 hard L2 with counterfactual structure)
**Supersedes:** L3_COUNTERFACTUAL_CASES_PLAN.md

---

## 0. What Makes a Case Truly L3

A case is L3 under these strict constraints:

1. The model **cannot solve it by trying both options and checking which passes**. Tests expose only one execution path. The counterfactual world is NOT directly testable by the model.

2. The model must **infer causal necessity** from the code structure — reasoning about what WOULD happen if a step were absent, without being shown that scenario.

3. A **contingent fix** (one that works in the observed path but not in hidden scenarios) must be detectable and penalized. The test catches contingent fixes through indirect invariants that the model cannot game by trial-and-error.

**The hard rule:** If the model can solve the case by forward-simulating each candidate change and checking test results, it is L2, not L3. L3 requires the model to reason about scenarios it cannot directly observe or test.

---

## 1. Repo Architecture

```
T3_code_generation_MVP/
  code_snippets_v2/
    overdetermination/          # Case 1 (L3)
      writer_a.py
      writer_b.py
      store.py
      api.py
    config_shadowing/           # Case 2 (L3)
      defaults.py
      env_config.py
      service.py
      background.py
    preemption/                 # Case 3 (L3) — replaces cache_warmup
      handler_primary.py
      handler_fallback.py
      dispatcher.py
      registry.py
    causal_sufficiency/         # Case 4 (hard L2) — replaces metric_attribution
      validator_a.py
      validator_b.py
      pipeline.py
      audit.py
    commit_gate/                # Case 5 (L3, kept from v1)
      state.py
      reducers.py
      selectors.py
      pipeline.py
      api.py

  tests_v2/
    test_overdetermination.py
    test_config_shadowing.py
    test_preemption.py
    test_causal_sufficiency.py
    test_commit_gate.py

  reference_fixes/
    overdetermination.py
    config_shadowing.py
    preemption.py
    causal_sufficiency.py
    commit_gate.py
```

---

## 2. Case Designs

---

### Case 1: Overdetermination — Dual Writer Masking (L3)

#### Scenario

Two writers (`writer_a` and `writer_b`) both write to a shared store. Both produce the **same observable value** — all visible tests pass with either writer present. The task says "remove the redundant writer to simplify."

The hidden difference: `writer_a` computes a fresh value AND sets a monotonic version counter. `writer_b` copies the value from a cache but does NOT update the version counter. A downstream `api.get_with_version()` function reads both the value and the version. The version counter is used by an **internal consistency check** (`store.verify_monotonic()`) that is called inside `api.serve_request()` — the model can see this code but the test does NOT separately assert on the version.

#### Why This Is L3

The model cannot solve this by "try removing each writer and see which test passes." **Both removals produce the same observable value in the test.** The test calls `api.serve_request()` which internally calls `store.verify_monotonic()` — but the verification is buried inside the API call, not exposed as a separate assertion. The model must READ the code of `store.verify_monotonic()` and `api.serve_request()` to understand that the version counter matters, then reason: "but for writer_a's version update, would the monotonic invariant hold?" This cannot be determined by running the test — it requires reading code the test exercises indirectly.

#### Code Structure

**store.py:**
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

def verify_monotonic(key, expected_min_version):
    """Internal consistency check. Called by api.serve_request()."""
    actual = _versions.get(key, 0)
    if actual < expected_min_version:
        raise ValueError(f"version regression: {actual} < {expected_min_version}")
    return True
```

**writer_a.py:**
```python
from store import write

_call_count = 0

def write_fresh(key, compute_fn):
    """Compute fresh value and write with version."""
    global _call_count
    _call_count += 1
    value = compute_fn()
    write(key, value, version=_call_count)  # updates version
    return value
```

**writer_b.py:**
```python
from store import write

_cache = {}

def write_cached(key, compute_fn):
    """Write cached value (or compute if not cached)."""
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])  # NO version update
    return _cache[key]
```

**api.py:**
```python
from store import read, get_version, verify_monotonic
from writer_a import write_fresh
from writer_b import write_cached

def update_product(product_id, compute_fn):
    """Update product using both writers (redundant)."""
    write_fresh(product_id, compute_fn)
    write_cached(product_id, compute_fn)
    return read(product_id)

def serve_request(product_id):
    """Serve a product request with version verification."""
    value = read(product_id)
    version = get_version(product_id)
    verify_monotonic(product_id, expected_min_version=1)  # hidden invariant
    return {"value": value, "version": version}
```

#### Test Design

```python
def test(mod):
    """Test calls update_product then serve_request.
    Does NOT separately test version. Does NOT remove either writer.
    The invariant is checked INSIDE serve_request via verify_monotonic.
    """
    mod.update_product("P1", lambda: 42)
    result = mod.serve_request("P1")
    if result["value"] != 42:
        return False, ["wrong value"]
    # Test succeeds if serve_request doesn't raise.
    # If model removes writer_a, writer_b writes value=42 but version stays 0.
    # verify_monotonic(expected_min_version=1) would raise ValueError.
    # If model removes writer_b, writer_a writes value=42 AND sets version=1.
    # verify_monotonic passes.
    return True, ["serve_request succeeded with correct value"]
```

**Critical:** The test does NOT assert `result["version"] >= 1`. The version check happens INSIDE `serve_request` via `verify_monotonic`. The model must read the api.py code to discover this hidden invariant. It cannot trial-and-error its way to the answer because both writers produce value=42 — the test only fails if `verify_monotonic` raises, which requires understanding the version semantics.

#### Reference Fix

Remove `write_cached` call from `update_product`. Keep `write_fresh`.

#### LEG Failure Type

`HIDDEN_DEPENDENCY` — the version counter dependency is hidden inside `serve_request`.

---

### Case 2: Config Shadowing — Structural vs Contingent Cause (L3)

#### Scenario

Configuration loads from three sources: `defaults.py` (timeout=5, WRONG), `env_config.py` (timeout=30, correct override), `service.py` (reads config). The task says "the background job uses the wrong timeout."

The key: `service.py` has TWO code paths — `handle_request()` uses `get_config()` which applies the env override, and `run_background_job()` uses `get_defaults()` directly (no override). The test exercises BOTH paths, but the model sees only one test function that calls both.

#### Why This Is L3

The model cannot find the bug by forward-tracing a single change. It must reason: "the default is wrong (timeout=5). The request path works because env overrides it. But for the env override, the request path would also use timeout=5." Then it must discover that `run_background_job()` already uses the unoverridden default — this IS the counterfactual world made real. The model must identify that the default (structural cause) must be fixed, not the env config (contingent mask).

The test does NOT remove the env config. It tests both paths in one call. The model must read `service.py` to see that `run_background_job` bypasses the override chain.

#### Code Structure

**defaults.py:**
```python
DEFAULTS = {"timeout": 5, "retries": 3}  # BUG: timeout should be 30

def get_defaults():
    return dict(DEFAULTS)
```

**env_config.py:**
```python
_ENV_OVERRIDES = {"timeout": 30}

def get_config():
    """Merge defaults with env overrides."""
    from defaults import get_defaults
    config = get_defaults()
    config.update(_ENV_OVERRIDES)
    return config
```

**service.py:**
```python
from env_config import get_config
from defaults import get_defaults

def handle_request():
    """Request handler — uses full config chain."""
    config = get_config()  # gets timeout=30 (overridden)
    return {"timeout": config["timeout"], "source": "request"}

def run_background_job():
    """Background job — uses defaults directly (no override)."""
    config = get_defaults()  # gets timeout=5 (BAD)
    return {"timeout": config["timeout"], "source": "background"}
```

**background.py:**
```python
from service import run_background_job, handle_request

def run_full_cycle():
    """Run both a request and a background job."""
    req = handle_request()
    bg = run_background_job()
    return {"request": req, "background": bg}
```

#### Test Design

```python
def test(mod):
    """Test that both request and background paths use correct timeout."""
    result = mod.run_full_cycle()
    req_timeout = result["request"]["timeout"]
    bg_timeout = result["background"]["timeout"]

    if req_timeout != 30:
        return False, [f"request timeout={req_timeout}, expected 30"]
    if bg_timeout != 30:
        return False, [f"background timeout={bg_timeout}, expected 30"]
    return True, ["both paths use correct timeout"]
```

**Critical:** The test checks BOTH paths. A model that "fixes" the env config or adds an override to `run_background_job` would pass the test but leave the structural cause (bad default) in place. The test catches this because if someone later adds a third path that uses `get_defaults()`, it would inherit the bad timeout. BUT — the test itself doesn't test this third path. The model must fix the DEFAULT, not patch the background job.

However, patching `run_background_job` to use `get_config()` instead of `get_defaults()` would ALSO pass the test. This is a **contingent fix** — it works but doesn't address the structural cause. We detect this with the scoring system: full pass (1.0) requires fixing `defaults.py`; a contingent fix (change background to use get_config) scores 0.7.

How to distinguish: the reference fix changes `defaults.py` (timeout=30). The validation checks whether `defaults.py` was modified. If only `service.py` was modified, it's a contingent fix.

#### Reference Fix

In `defaults.py`: change `"timeout": 5` to `"timeout": 30`.

#### LEG Failure Type

`PARTIAL_STATE_UPDATE` — the default is structurally wrong but partially masked.

---

### Case 3: Preemption — Masked Handler (L3, replaces cache_warmup)

#### Scenario

A request dispatcher routes to handlers. `handler_primary` handles the request AND registers itself in a `registry`. `handler_fallback` also handles the request but does NOT register. The dispatcher calls primary first; if primary succeeds, fallback is never called.

The task says "handler_fallback is dead code — it's never reached. Remove it." But handler_fallback is NOT dead code: it is the registered backup in the registry. If primary is removed or fails, the registry's `get_registered_handler()` returns fallback (because primary registered itself, and registry keeps a history). The removal of fallback breaks the registry's invariant.

Wait — that's still forward-traceable. Let me redesign.

#### Revised Scenario

Two handlers both process requests. `handler_primary` processes AND sets a completion flag. `handler_fallback` processes but does NOT set the flag. In the current code, BOTH run (the dispatcher calls both). The task says "both handlers do the same thing — remove the fallback to simplify."

The hidden structure: `dispatcher.process()` calls both handlers, then checks the completion flag. The flag is set by primary only. A downstream `registry.verify_completion()` checks the flag. If fallback is removed, nothing changes (primary still sets the flag). If PRIMARY is removed but fallback kept, the flag is never set and `verify_completion` fails.

The trap: "remove the fallback" is the CORRECT action (it's truly redundant for the observable output). But the task prompt says "remove the redundant handler" — and the model must determine WHICH handler is redundant. Both produce the same output. But only primary sets the completion flag that `verify_completion` checks.

This is overdetermination with a twist: the model must determine which of two overdetermining causes is the necessary one, based on a hidden side effect (completion flag).

#### Why This Is L3

Both handlers produce the same value. Removing either one produces the same value in the test. But the completion flag — checked INSIDE `dispatcher.process()` via `registry.verify_completion()` — is only set by primary. The model cannot determine which handler to keep by testing; it must read the code to discover the hidden side effect and reason: "but for primary's completion flag, would verify_completion pass?"

#### Code Structure

**handler_primary.py:**
```python
def handle(request):
    """Process request and mark completion."""
    result = {"status": "ok", "data": request["data"].upper()}
    return result

def get_side_effects():
    """Primary handler sets completion flag."""
    return {"sets_complete": True}
```

**handler_fallback.py:**
```python
def handle(request):
    """Process request (backup path). No side effects."""
    result = {"status": "ok", "data": request["data"].upper()}
    return result

def get_side_effects():
    return {"sets_complete": False}
```

**registry.py:**
```python
_completion_flags = {}

def mark_complete(request_id):
    _completion_flags[request_id] = True

def verify_completion(request_id):
    """Check that request was properly completed. Called by dispatcher."""
    if not _completion_flags.get(request_id):
        raise RuntimeError(f"request {request_id} not marked complete")
    return True

def reset():
    _completion_flags.clear()
```

**dispatcher.py:**
```python
from handler_primary import handle as primary_handle
from handler_fallback import handle as fallback_handle
from registry import mark_complete, verify_completion

def process(request):
    """Process request through both handlers, verify completion."""
    request_id = request.get("id", "unknown")

    # Both handlers run (task says: "redundant — remove one")
    result_a = primary_handle(request)
    mark_complete(request_id)  # completion side effect tied to primary path
    result_b = fallback_handle(request)

    # Verify completion (hidden invariant)
    verify_completion(request_id)

    return result_a  # returns primary result
```

#### Test Design

```python
def test(mod):
    """Process a request. Does NOT test handlers individually."""
    if hasattr(mod, 'reset'):
        mod.reset()
    request = {"id": "R1", "data": "hello"}
    result = mod.process(request)
    if result["status"] != "ok":
        return False, ["status not ok"]
    if result["data"] != "HELLO":
        return False, [f"data={result['data']}, expected HELLO"]
    return True, ["request processed successfully"]
```

The test calls `process()` which calls `verify_completion()` internally. If the model removes the primary handler AND the `mark_complete` call, `verify_completion` raises. If the model removes the fallback handler, everything still works.

BUT: a model that just removes the `fallback_handle(request)` line passes the test. That's the correct answer. The L3 reasoning is: "but for the primary handler's `mark_complete`, would `verify_completion` succeed? No — fallback doesn't set the flag."

**Hmm — this is still solvable by trying both removals.** The model could remove primary (test fails) then remove fallback (test passes). That's trial-and-error, not counterfactual reasoning.

Let me fix this: make BOTH removals pass the test in isolation, but only one is correct for structural reasons.

#### Revised Design (Preemption — True L3)

Actually, let me reconsider. The constraint says: "the model cannot solve by trying both options and seeing which passes." For this to work, BOTH options must pass the visible test. The distinction must come from a structural property the test doesn't directly check.

**New approach:** Both handlers produce correct output. Both removals pass the test. But `handler_primary` has a property that `handler_fallback` doesn't: it is **idempotent** (calling it twice produces the same result). The downstream `dispatcher` relies on idempotency for retry safety. The test doesn't test idempotency directly. The model must read the retry logic in `dispatcher.py` and reason: "but for handler_primary's idempotency, would retry be safe?"

This is too contrived. Let me step back and acknowledge: making BOTH removals pass the observable test while one is structurally wrong is very hard to achieve without artificial complexity. The constraint "model cannot solve by trial-and-error" is in tension with "tests must be deterministic and executable."

**Resolution:** I'll keep preemption as a **hard L2 case** with counterfactual structure, not a strict L3. The plan should be honest about which cases are strictly L3 vs which have L3 flavor but are solvable by careful forward analysis.

#### Revised Classification

Case 3 (preemption) → **L2 (deep) with counterfactual structure**. The model must reason about which handler is necessary, but it CAN determine this by trying both removals. The counterfactual reasoning helps but isn't strictly required.

---

### Case 4: Causal Sufficiency — Redundant Validator (Hard L2, replaces metric_attribution)

#### Scenario

Two validators check an input pipeline. `validator_a` checks format. `validator_b` checks business rules. Both must pass for the pipeline to proceed. The task says "validator_a is redundant — validator_b already catches format errors."

The truth: `validator_b` catches MOST format errors (because it parses the input), but NOT all (some format errors produce valid-looking but semantically wrong parsed output). `validator_a` catches ALL format errors at the syntactic level.

This is a **causal sufficiency** question: is `validator_b` sufficient to replace `validator_a`? Answer: no, because `validator_b` is not sufficient — it misses a class of format errors that produce valid-looking parses.

#### Why This Is Hard L2 (Not Strict L3)

The model CAN discover this by forward-tracing: read `validator_b`'s parsing logic, find inputs that produce valid-looking but wrong parses, verify that `validator_a` catches them. This is L2 — forward simulation of a specific input through both validators. The model doesn't need to compare alternative worlds; it needs to find a counterexample.

But it has counterfactual flavor: "but for validator_a, would malformed input X be caught?" The answer is no for specific X values.

#### Code Structure

**validator_a.py:** Syntactic format check (strict regex).
**validator_b.py:** Business rule check (parses input, applies rules — misses certain malformed inputs that parse as valid).
**pipeline.py:** Runs both validators, then processes.
**audit.py:** Logs validation outcomes.

#### Test Design

Test passes valid input through both validators and malformed input that validator_b misses. Model must keep validator_a to catch the edge case.

---

### Case 5: Commit Gate — But-For Causation (L3, kept from v1)

Unchanged from v1 plan. This is the strongest L3 case.

#### Why This Is Strictly L3

The task says "commit() and freeze_view() are redundant." The model CANNOT determine this by testing because:

1. Removing commit() causes `get_committed_total()` to return `None` — the test catches this. So the model could discover this by trying.

BUT:

2. Merging stage+commit causes `preview()` to set `frozen=True` as a side effect — breaking preview semantics. The test checks preview behavior. The model could discover this by trying.

So actually, both can be discovered by trial-and-error. The L3 character comes from the fact that the model must evaluate TWO but-for tests simultaneously and understand that each step is necessary for a DIFFERENT downstream consumer. A model that removes commit (test fails) and then puts it back might not understand WHY it failed — it just knows "removing commit breaks things."

**The L3 claim rests on:** the model must understand causal necessity (WHY commit is needed, not just THAT removing it fails). The LEG evaluation measures this: does the model's REASONING correctly identify the mechanism (frozen gate for selectors + separation for preview)?

This is L3 in the LEG sense: the model may discover the test failure by trial-and-error (L2), but to demonstrate understanding (LEG_true), it must reason about but-for causation.

---

## 3. Revised Case Classification

| Case | Classification | Justification |
|---|---|---|
| **overdetermination** | **L3** | Both removals produce correct value. Only reading hidden `verify_monotonic` inside `serve_request` reveals which writer is necessary. Model cannot solve by test output alone — must read code to discover hidden invariant. |
| **config_shadowing** | **L3** | Both fix strategies (fix default vs patch background) pass the test. Model must identify structural vs contingent cause. Contingent fix detectable by reference-fix comparison, not by test failure. |
| **preemption** | **L2 (deep)** | Model CAN determine correct removal by trying both. Counterfactual structure present but not required. |
| **causal_sufficiency** | **L2 (deep)** | Model CAN find counterexample by forward analysis. Sufficiency question has counterfactual flavor but is solvable by L2 reasoning. |
| **commit_gate** | **L3 (for LEG)** | Model can discover failures by trial-and-error, but LEG evaluation measures whether reasoning identifies the causal mechanism (but-for commit → frozen gate; but-for separation → preview breaks). |

**Honest count: 2 strict L3, 1 L3-for-LEG, 2 hard L2.**

---

## 4. Contract Schema (Unchanged from v1)

Same contract format. The `counterfactual_contract` field is metadata for analysis:

```json
{
    "counterfactual_contract": {
        "causal_variable": "the step whose necessity is tested",
        "but_for_test": "if {causal_variable} were absent, would {invariant} hold?",
        "expected_answer": "NO",
        "invariant_held_fixed": "downstream invariant",
        "competing_world": "description of alternative execution"
    }
}
```

---

## 5. Retry Prompt Design (Unchanged from v1)

Same retry prompt with counterfactual feedback section. For strict L3 cases, the retry feedback says "serve_request raised ValueError" or "background timeout=5" — it does NOT explain the counterfactual reasoning. The model must connect the error to the causal structure.

---

## 6. Scoring

| Score | Condition |
|---|---|
| 1.0 | Structural fix — addresses root cause |
| 0.7 | Contingent fix — passes test but doesn't fix structural cause (detectable via reference comparison) |
| 0.5 | Code runs, invariant fails |
| 0.2 | Code errors but reasoning correct (LEG) |
| 0.0 | Code errors, reasoning wrong |

The 0.7 tier is critical for L3: it captures models that pass the test by contingent fixes (e.g., patching background.py instead of fixing defaults.py).

---

## 7. Failure Mode Taxonomy

| Case | L3 Subtype | Expected Mistake | LEG Type |
|---|---|---|---|
| overdetermination | Overdetermination | Removes writer_a (the necessary one) because writer_b looks simpler | HIDDEN_DEPENDENCY |
| config_shadowing | Structural vs contingent | Patches background path instead of fixing default | PARTIAL_STATE_UPDATE |
| preemption | Preemption (L2) | Removes primary handler (keeps flag-less fallback) | HIDDEN_DEPENDENCY |
| causal_sufficiency | Sufficiency (L2) | Removes validator_a (misses edge-case format errors) | EDGE_CASE_MISSED |
| commit_gate | But-for necessity | Removes "redundant" commit or merges stage+commit | INVARIANT_VIOLATION |

---

## 8. Implementation Roadmap

Same phases as v1:

1. **Phase 1:** Create 5 case directories, code files, tests, reference fixes, CASE_DOC.md
2. **Phase 2:** Add to cases_v2.json, update MASTER_CASE_PEARL_MAPPING.md
3. **Phase 3:** ~50 lines retry_harness.py (counterfactual feedback + causal_correctness)
4. **Phase 4:** Baseline experiment, verify LEG evaluation fires correctly

### Key Design Constraint for Implementation

For the two strict L3 cases (overdetermination, config_shadowing):
- Tests must NOT include separate assertions for the hidden invariant
- The hidden invariant must be checked INSIDE a function the test calls
- The model must READ the source code to discover the invariant — it is not surfaced in the test output

For commit_gate:
- Tests DO show the failure when commit is removed — the L3 character is measured by LEG (did the model reason about WHY, not just THAT)

---

## 9. Compatibility (Same as v1)

All systems compatible. No changes to LEG evaluation module, failure_classifier, diff_gate, contract.py, or runner.py. ~50 lines in retry_harness.py.
