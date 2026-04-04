# Deep Adversarial Audit: cases_v2 Execution Tests

**Date**: 2026-03-30
**Auditor**: Claude (adversarial mode)
**Scope**: All 28 test oracle families in `tests_v2/`, the `exec_eval.py` evaluator,
`exec_canonical.py` + `harness/run_case.py`, and all 51 cases in `cases_v2.json`.

---

## Section A -- Executive Verdict

**The test suite is NOT broadly trustworthy for research use without significant caveats.**

The tests are *directionally useful* -- they catch obvious wrong answers and test the right
general invariants. But a hostile adversarial analysis reveals systemic weaknesses that can
produce both false positives (wrong code passing) and false negatives (correct code failing).

### What is strong

- The **concurrency family** (lost_update, check_then_act, false_fix_deadlock) has
  anti-hardcoding checks and multi-scenario coverage. These are the best-designed tests.
- The **mutable_default** family directly tests state isolation across calls.
- The **retry_dup** family tests the exact invariant (exactly-once delivery).
- The **effect_order** family checks both count and value correctness of per-item effects.

### What is weak

- **3 families are MISLEADING** (wrong_condition, partial_rollback, invariant_partial_fail):
  trivially wrong code can pass these tests. No-op functions, always-False predicates, and
  functions that skip all processing can all score 1.0.
- **Multiple families lack happy-path tests**: they verify failure handling but never confirm
  the function actually works correctly. This is the single highest-risk pattern.
- **The merged-namespace architecture** (both concat and disk-backed paths) silently masks
  cross-file import bugs, making multi-file cases test something fundamentally different
  from what they claim.
- **V2 cases have NO mutation tests**: the mutation test system in exec_eval.py only covers
  V1 case IDs. All V2 cases get `(True, ["no mutation tests for this case"])`.

### Highest-risk flaws (ranked)

1. **No-op degenerate passes** in partial_rollback and invariant_partial_fail (CRITICAL)
2. **Always-restrictive degenerate passes** in wrong_condition (CRITICAL)
3. **Missing happy-path verification** across ~8 families (HIGH)
4. **Merged namespace masks cross-file bugs** for all 38 multi-file cases (HIGH)
5. **No mutation tests for V2 cases** (MEDIUM)
6. **Fragile state reset via hardcoded variable names** (MEDIUM)

### Caveats needed for preliminary results

If using this benchmark for preliminary results today:

1. Results for `wrong_condition`, `partial_rollback`, and `invariant_partial_fail` families
   should be flagged as potentially inflated -- pass rates may include degenerate passes.
2. Multi-file case pass rates may not reflect true cross-file reasoning ability since
   both execution paths flatten to a single namespace.
3. Pass rates should NOT be interpreted as "model fixed the bug correctly" -- they should
   be interpreted as "model produced code that satisfies the tested assertions", which is
   a weaker claim.
4. The absence of happy-path tests means a model that "fixes" a bug by disabling the
   feature entirely would score as a pass in several families.

---

## Section B -- Harness-Level Findings

### B.1: Merged namespace masks cross-file import behavior

**Severity**: HIGH
**Files**: `exec_eval.py:33-52` (load_module_from_code), `harness/run_case.py:98-148` (merged namespace)
**Problem**: Both execution paths flatten all files into a single namespace/module:
- `exec_eval.py` concatenates code and `exec()`s it into one module
- `harness/run_case.py` imports each `.py` from `pkg/` then merges all names into a single `types.ModuleType`

**Why it matters**: The 38 multi-file cases (e.g., `stale_cache_c` with `catalog.py`, `cache.py`, `api.py`)
claim to test cross-boundary reasoning. But in both execution paths, `from cache import cache_get` is
never tested -- all names are already available in the flat namespace. A model that puts everything in a
single file would score identically to one that correctly maintains file boundaries.

**Bad measurement**: Cross-boundary pass rates are inflated. The tests cannot distinguish between
"model understands module boundaries" and "model dumped everything into one namespace."

**Recommendation**: For multi-file cases, the test oracle should verify:
1. Import statements between modules resolve correctly
2. Cross-file function calls work through the expected import path
3. Module-level state is properly scoped

### B.2: V2 cases have no mutation tests

**Severity**: MEDIUM
**File**: `exec_eval.py:676-691`
**Problem**: `_run_mutation_tests()` looks up `case_id` in `_CASE_TESTS`, which only contains
V1 case IDs. All V2 cases (the entire `cases_v2.json` suite of 51 cases) get:
```python
return True, ["no mutation tests for this case"]
```
This means the mutation test always passes, contributing `passed_tests += 1` without testing anything.

**Why it matters**: The mutation test is supposed to verify that the test setup is idempotent and
that repeated runs produce consistent results. Without it, we can't detect tests that pass
on first run but fail on second run (state leakage).

**Bad measurement**: `total_tests` and `passed_tests` counts are inflated by 1 for every V2 case,
making the test appear more rigorous than it is. The `mutation_pass: True` field is always True
for V2 cases, providing false confidence.

**Recommendation**: Either remove mutation tests from V2 scoring or implement per-family
mutation tests in the `tests_v2/` modules.

### B.3: State reset depends on hardcoded variable names

**Severity**: MEDIUM
**Files**: All `tests_v2/test_*.py` files
**Problem**: Tests reset module state by directly assigning to known internal variable names:
```python
if hasattr(mod, "_counter"):
    mod._counter = 0
if hasattr(mod, "_snapshots"):
    mod._snapshots = []
```
If a model renames `_counter` to `_total` or `_snapshots` to `_history`, the reset silently
doesn't happen. The test then runs against contaminated state from module initialization.

**Why it matters**: For stateful cases, this can cause:
- False positives: stale state happens to match expected values
- False negatives: accumulated state causes unexpected values

**Bad measurement**: Non-deterministic test results depending on model implementation details.

**Recommendation**: Where possible, use a `reset()` function as the primary reset mechanism
(many cases already have this). Add a check: if no `reset()` exists and no known variables
were found, emit a warning in the test result.

### B.4: Concat path code assembly may introduce false failures

**Severity**: MEDIUM
**File**: `exec_eval.py:699-726` (_assemble_program)
**Problem**: The `CodeAssembler` in the concat path does import rewriting, duplicate definition
detection, and rename error detection. These are complex transformations that can introduce
spurious failures:
- `rename_error`: if the model uses a slightly different function name, the test fails
  with "original buggy function would run instead of model's fix" even if the logic is correct
- Import rewriting may resolve differently than the canonical disk-backed path

**Why it matters**: Discrepancies between concat and disk-backed paths produce disagreement
in dual execution, which is tracked but not used for scoring. However, researchers may draw
conclusions from concat-path scores that differ from canonical-path scores.

**Bad measurement**: Concat-path results may have higher error rates due to assembly artifacts,
not due to model code quality.

**Recommendation**: Document which execution path produces the canonical score and deprecate
or remove the other.

### B.5: Test dispatch search order may cause silent wrong-test binding

**Severity**: LOW
**File**: `harness/run_case.py:156-175`
**Problem**: Test resolution tries `test_{difficulty}`, then `test`, then `test_a` in order.
If a case has `difficulty: "C"` (capital C) but the test file defines `test_c` (lowercase),
the search looks for `test_C` first (which doesn't exist), then falls through to `test`
or `test_a`. This means a Level C case might run the Level A test.

Looking at the code: `difficulty = meta.get("difficulty", "a").lower()` -- OK, the meta loader
lowercases the difficulty. But `cases_v2.json` has difficulty values like `"a"`, `"b"`, `"c"`,
and `"C"`, `"L3"`. Let me check...

The `exec_eval.py:_load_v2_test()` at line 593 does:
```python
level = case.get("difficulty", "").lower()
```
And then at line 611:
```python
fn = getattr(mod, f"test_{level}", None)
```

So for `"L3"` difficulty, it looks for `test_l3`. For `"C"`, it looks for `test_c`.
For the L3 cases (`l3_state_pipeline`, `cache_invalidation_order`, etc.), the test files
define `test()` not `test_l3()`. So the fallback chain works.

But in `harness/run_case.py`, the same fallback exists. Low severity because the chain
resolves correctly for all current cases.

**Recommendation**: Add a test that verifies every case resolves to a specific test function
and log which function was resolved.

---

## Section C -- Invariant-Family Audit

### C.1: alias_config (3 variants)

**Intended**: `create_config()` returns a fresh dict; mutating one config must not affect DEFAULTS or future calls.

**Actual test**:
- `test_a`: Creates cfg1 with override, creates cfg2 clean, checks cfg2 has original values.
- `test_b`: Same as test_a plus cache clearing.
- `test_c`: Two `handle_request` calls, checks second is clean.

**Strengths**:
- Tests the core invariant (isolation between calls).
- Checks DEFAULTS not corrupted.
- test_c tests through an API layer.

**Weak spots**:
- **test_a/b never verify overrides were applied**: `cfg1 = create({"timeout": 5})` is called but
  `cfg1["timeout"] == 5` is never asserted. A function that ignores overrides entirely would pass.
- No identity check (`cfg1 is not cfg2`) to catch trivial pass where same object is returned.
- test_a/b don't test mutation after creation: `cfg1["new_key"] = True; assert "new_key" not in cfg2`.

**Likely false positives**: `create_config` that always returns `{"timeout": 30, "retries": 3, "debug": False}` regardless of overrides passes test_a and test_b.

**Likely false negatives**: None identified.

**Adversarial counterexample that passes**:
```python
def create_config(overrides=None):
    return {"timeout": 30, "retries": 3, "debug": False}  # ignores overrides
```

**Recommendations**:
1. Add `assert cfg1.get("timeout") == 5` after calling `create({"timeout": 5})`.
2. Add identity check: `assert cfg1 is not cfg2`.
3. Add post-creation mutation test: mutate cfg1, verify cfg2 unaffected.

---

### C.2: partial_update (3 variants)

**Intended**: Derived/dependent fields stay in sync after updates.

**Actual test**:
- test_a: name change -> display_name must update
- test_b: first_name change -> full_name must recompute
- test_c: email change -> verified must reset

**Strengths**:
- Tests check specific field values after mutation.
- test_c verifies the user was previously verified (tests the transition).

**Weak spots**:
- **test_c doesn't check cached_greeting**: Case metadata says the bug involves "clear cached_greeting"
  but the test never verifies it. The `old_greeting` variable is captured but never used.
- test_a/b don't verify other fields are unchanged (could mask over-broad updates).

**Metadata mismatch**: `cases_v2.json` for partial_update_c lists the fix as:
"fix_pattern: set verified=False and clear cached_greeting on email change". The test only
checks verified=False.

**Adversarial counterexample that passes test_c**:
```python
def update_profile(user, changes):
    for k, v in changes.items():
        user[k] = v
    if "email" in changes:
        user["verified"] = False
    # cached_greeting never updated -- test still passes
```

**Recommendations**:
1. Add cached_greeting check in test_c after email change.
2. Verify unchanged fields remain unchanged.

---

### C.3: stale_cache (3 variants)

**Intended**: `get_product()` returns current data after `update_product()`.

**Strengths**:
- Tests the read-after-write invariant directly.
- Uses add->read->update->read sequence.

**Weak spots**:
- Only one update-read cycle. Doesn't test:
  - Add->read->update->update->read (latest of multiple updates)
  - Delete->read (should return None or error)
  - Concurrent add and read patterns

**Degenerate pass**: Model could bypass the cache entirely (always read from DB) and pass.
This is technically a valid fix but doesn't demonstrate understanding of cache invalidation.

**Recommendations**:
1. Add a second update-read cycle to verify consistency holds over time.
2. Verify get_product is actually using the cache (e.g., check it's faster or check cache state).

---

### C.4: lazy_init (3 variants)

**Intended**: After reset + reconfigure, getters must reflect new config.

**Weak spots**:
- test_a manually resets `_default_host` (implementation detail). If model uses a different capture mechanism, this reset is wrong.
- No test verifies the "before" state (that defaults are initially correct).
- A model that always returns the last `configure()` argument without implementing lazy evaluation would pass.

**Recommendations**:
1. Verify initial state before configure().
2. Test configure->get->configure_different->get sequence.
3. Remove direct `_default_host` manipulation; rely on `reset_settings()` only.

---

### C.5: mutable_default (3 variants)

**Intended**: Mutable default arguments must not leak state across calls.

**Strengths**:
- test_a: Checks queue length after second call (directly tests accumulation).
- test_b: Checks overlapping items in second batch are processed (not "seen").
- test_c: Checks cross-function history independence.

**This is one of the stronger families.**

**Minor weakness**: test_a doesn't check q1 has exactly 1 item (only checks q2).

**Recommendations**:
1. Add `assert len(q1) == 1` in test_a.
2. Add a third call in test_b to strengthen accumulation detection.

---

### C.6: effect_order (3 variants)

**Intended**: Side effects (snapshot/emit/audit) happen per-item, not once at batch end.

**Strengths**:
- Checks both count (len == 3) AND values (running totals / IDs).
- Good coverage of the specific bug pattern.

**Weak spots**:
- Resets state via direct variable assignment (`mod._counter = 0`), fragile to renames.
- test_a assumes specific snapshot values `[10, 30, 60]`. A model that computes these
  differently but correctly (e.g., accumulator stored differently) could fail.
  Actually, these are running sums: 10, 10+20=30, 30+30=60. The test IS checking the right invariant.

**Recommendations**:
1. Prefer `mod.reset()` over direct variable assignment.
2. Add a second batch call to verify state is properly reset between batches.

---

### C.7: use_before_set (3 variants)

**Intended**: Variables must reflect current call's state, not prior state.

**Strengths**:
- Tests the exact stale-data bug (call with data, then call with empty/low data).

**Weak spots**:
- test_b: Checks `r2["status"] == "loaded"` is False and `r2["count"] != 0`. But doesn't
  check what the correct status SHOULD be. `{"status": "error", "count": 0}` would pass.
- test_c: Returns None as "correct" for below-threshold records. But doesn't test that
  above-threshold records actually work (the first call's result is captured but not checked
  against a specific expected value).

**Adversarial counterexample for test_b**:
```python
def run_pipeline(data):
    return {"status": "empty", "count": 0}  # always returns empty, never processes
```

**Recommendations**:
1. test_b: Assert the correct status value for empty input (e.g., "empty" or "idle").
2. test_b: Verify r1 is correct (count > 0, status = "loaded").
3. test_c: Verify r1 is not None and has the expected value.

---

### C.8: retry_dup (3 variants)

**Intended**: Each message appears exactly once after successful send.

**Strengths**:
- Directly tests the core invariant (no duplication on success).
- test_b also verifies notification count.

**Weak spots**:
- Tests only the success-on-first-try path. Doesn't test the case where the
  first attempt fails and the second succeeds (which is where retry duplication bugs
  commonly appear with different logic).
- test_a uses `max_retries=2` with a send that always succeeds. The bug (missing break)
  would cause 2 sends. But if a model adds a break but gets the retry logic wrong on
  failure-then-success, the test wouldn't catch it.

**Recommendations**:
1. Add a test where first attempt fails and second succeeds, verify exactly 1 message.
2. Add a test where all attempts fail, verify 0 messages.

---

### C.9: partial_rollback (3 variants) -- CRITICAL WEAKNESS

**Intended**: If multi-step operation fails mid-sequence, prior steps must be compensated.

**CRITICAL PROBLEM**: None of the three tests verify the happy path (successful order).

**Adversarial counterexample that passes ALL THREE tests**:
```python
def place_order(inv_or_sku, wallet_or_qty, qty_or_price, price=None):
    pass  # does absolutely nothing
```
- test_a: `inv.available()` returns 10 (unchanged). Pass.
- test_b: `mod.available("SKU-100")` returns 10 (set by add_product). Pass.
- test_c: `mod.available("WIDGET-1")` returns 20 (set by add_product). `mod.get_audit_log()` returns []. Pass.

The tests expect ValueError to be raised (`except ValueError: pass`) but a no-op that doesn't
raise is also silently accepted because the except block uses `pass`.

**Why this is CRITICAL**: A model can score 1.0 on all partial_rollback variants by removing
the function body entirely. This makes the pass rate for this family meaningless.

**Recommendations**:
1. **Add a successful order test first**: verify that a well-funded order succeeds, inventory
   decreases, payment processes.
2. **THEN test the failure path**: verify rollback on failure.
3. Change the try/except to track whether the exception was raised:
   ```python
   raised = False
   try:
       mod.place_order(...)
   except ValueError:
       raised = True
   if not raised:
       return False, ["place_order did not raise ValueError on failed payment"]
   ```

---

### C.10: temporal_drift (3 variants)

**Intended**: `raw_stats` must reflect original data, not normalized data.

**Strengths**:
- Uses specific input values where raw != normalized, making detection possible.

**Weak spots**:
- **Doesn't verify normalization still works**: A model that removes the normalization step
  entirely (just computes raw_stats from raw data and returns raw data as "normalized") passes.
- Doesn't check `result["normalized"]` or any non-raw_stats output.

**Adversarial counterexample**:
```python
def pipeline(data):
    return {
        "raw_stats": {"raw_max": max(data), "raw_min": min(data), "raw_sum": sum(data)},
        "normalized": data,  # no normalization at all
        "result": data
    }
```

**Recommendations**:
1. Also verify that normalized data IS normalized (values between 0 and 1, or whatever the spec requires).
2. Verify that the pipeline produces both correct raw_stats AND correct normalized output.

---

### C.11: missing_branch (3 variants)

**Intended**: All documented roles must receive correct permissions.

**Weak spots**:
- Tests ONLY check the missing role. They never verify existing roles still work.
- A model that gives ALL roles maximum permissions would pass.

**Adversarial counterexample for test_a**:
```python
def get_permissions(role):
    return {"read", "write", "delete", "admin"}  # everyone gets everything
```
This passes because moderator gets "read" and "delete".

**Recommendations**:
1. Also test an existing role (e.g., "viewer") still gets its original permissions.
2. Add a negative test: unknown role should get empty permissions or raise.

---

### C.12: wrong_condition (3 variants) -- CRITICAL WEAKNESS

**Intended**: Rate limiting conditions must use correct operators.

**CRITICAL PROBLEM**: All three tests only check the boundary/rejection case. None verify
that legitimate requests are still allowed.

**Adversarial counterexamples**:
- test_a: `def is_rate_limited(count, limit): return True` passes (always blocks).
- test_b: `def is_allowed(**kw): return False` passes (always denies).
- test_c: `def should_allow(**kw): return False` passes (always blocks).

**Why this is CRITICAL**: A model that "fixes" the bug by making the function always reject
(the maximally conservative implementation) scores 1.0 on all three variants. This is the
exact opposite of a correct fix -- it would break all legitimate traffic.

**Recommendations**:
1. **Add complementary allow test**:
   - test_a: Also check `is_rate_limited(4, 5)` returns False (under limit).
   - test_b: Also check `is_allowed(rpm=50, limit=100, daily=5000, quota=10000)` returns True.
   - test_c: Also check `should_allow(valid_token, under_limit, non_exempt)` returns True.
2. Consider adding a "must allow at least one scenario" meta-assertion.

---

### C.13: early_return (3 variants)

**Intended**: Every payment call produces a ledger/audit entry, even on early-return paths.

**Strengths**:
- Tests count of ledger entries across different call types.

**Weak spots**:
- Only checks ledger ENTRY COUNT, not content. A model that appends dummy entries on every
  call would pass without actually processing anything.
- Doesn't verify that the normal (non-early-return) path produces correct entries.

**Recommendations**:
1. Verify ledger entry content (amount, type, etc.) not just count.
2. Add a test for the specific early-return trigger: verify the zero-amount entry has the correct amount recorded.

---

### C.14: index_misalign (3 variants)

**Intended**: Parallel data structures must stay synchronized after mutations.

**Strengths**:
- test_a: Checks both inserted position and shifted position.
- test_b: Checks rendered output (behavioral, not structural).

**Weak spots**:
- test_c: Falls back to "render doesn't crash" if validate() doesn't exist. A model that
  returns pre-computed render results without maintaining internal consistency would pass.
- No test inserts multiple columns and verifies alignment still holds.

**Recommendations**:
1. test_c: Assert specific rendered values, not just non-empty.
2. Add multi-mutation test: insert, delete, insert, verify.

---

### C.15: silent_default (3 variants)

**Intended**: Flag lookups must return actual configured value, not silent fallback.

**Strengths**:
- Tests the exact key mismatch scenario.

**Weak spots**:
- State reset assigns to `mod.FLAGS` directly. If model restructures the data, reset is wrong.
- test_a: Only tests one flag. A model that special-cases "darkMode" but gets others wrong passes.
- No negative test: verify that a truly disabled flag returns False.

**Recommendations**:
1. Test multiple flags (at least one True, one False).
2. Add a negative test for a flag that should be False.

---

### C.16: l3_state_pipeline

**Intended**: commit() and freeze_view() are both necessary for pipeline correctness.

**Strengths**:
- Tests three separate properties: frozen gate, stable data, committed total.

**Weak spots**:
- Only tests with 2 entries. Doesn't test dedup or collapse behavior.
- Doesn't test that view matches stable after freeze_view (the consistency assertion is
  in the separate test_commit_gate.py for the commit_gate family, not here).

**Recommendations**:
1. Add a test with duplicate entries to verify normalize/collapse still works.
2. Verify view contents match stable contents.

---

### C.17: cache_invalidation_order

**Intended**: Cache must be properly updated after writes.

**Strengths**:
- Simple and direct test of the core invariant.

**Weak spots**:
- Only tests `update_record`/`read_record`. The case has `safe_update` and
  `cache_conditional_set` (version-based cache) that are NEVER tested.
- The case description mentions "cache ordering" and "version-based conditional set"
  but the test only checks basic cache consistency.

**Metadata mismatch**: The case claims to test cache invalidation *ordering* but the test
only checks that reads after writes return the latest value -- which is a cache *correctness*
test, not an ordering test.

**Recommendations**:
1. Add a test that exercises `safe_update` and verifies version-based cache behavior.
2. Add a test where `update_record` and `safe_update` interleave.

---

### C.18: feature_flag_drift

**Intended**: `use_new_pricing` flag must propagate to pricing computation.

**Strengths**:
- Tests exact expected total (900 vs 1000).
- Verifies flag cleanup after checkout.

**Weak spots**:
- A model that passes `use_new_pricing` as a parameter directly to `compute_price`
  (bypassing the flag system) would pass. The test checks the output, not the mechanism.
- Doesn't test that checkout WITHOUT the flag uses v1 pricing.

**Adversarial counterexample**:
```python
def checkout(customer, items, use_new_pricing=False):
    total = 0
    for item in items:
        price = item["base"] * item["qty"]
        if use_new_pricing and item["qty"] >= 10:
            price *= 0.9
        total += price
    return {"total": total}  # bypasses entire flag/pricing system
```

**Recommendations**:
1. Add a test without `use_new_pricing=True` to verify v1 pricing still works.
2. Test that the flag system itself works (is_enabled, enable, disable).

---

### C.19: invariant_partial_fail -- CRITICAL WEAKNESS

**Intended**: Balance conservation after failed transfer.

**CRITICAL PROBLEM**: A no-op execute_transfer passes.

The test patches `random.random` to return 0.0 (forcing failure), then calls
`execute_transfer(sender, receiver, 50)`. It expects RuntimeError to be raised
but silently accepts no exception (`except RuntimeError: pass`).

After the call, it checks `sender.balance + receiver.balance == 100` (the initial total).

A no-op function satisfies this: sender stays at 100, receiver stays at 0. Total = 100. Pass.

**Even worse**: A function that only debits without crediting would also fail conservation
(100-50 + 0 = 50 != 100), so the test WOULD catch that. But a function that does nothing
at all passes. The test cannot distinguish between "correctly rolled back" and "never
started."

**Recommendations**:
1. Add a success-path test: with random returning 0.99 (above threshold), verify transfer
   completes correctly (sender=50, receiver=50).
2. Change the except block to verify the exception was actually raised.
3. After the failure, verify that the debit WAS attempted and then rolled back
   (check ledger entries, for example).

---

### C.20: async_race_lock

**Intended**: run_verified must use process_item (with locking) not quick_increment.

**Strengths**:
- Checks for "before"/"after" keys in results, which are specific to the locking path.
- Checks total is correct.

**Weak spots**:
- A model could add before/after fields to quick_increment without implementing locking,
  and the test would pass.
- The test doesn't verify actual mutual exclusion (locking).

**Recommendations**:
1. Verify that try_lock/unlock are actually called (check state changes).
2. Add a concurrent-like scenario (two interleaved process_item calls) to test atomicity.

---

### C.21: hidden_dep_multihop

**Intended**: save_user write-through cache must overwrite on second save.

**Strengths**:
- Tests the exact two-save scenario.
- Tests through the full stack (save -> cache -> read).

**Weak spots**:
- Only tests save-save-read. Doesn't test:
  - rename_user (another path to cache staleness)
  - delete_user followed by save_user
  - bulk_warm_cache behavior

**Recommendations**:
1. Add rename_user test: rename -> read -> verify name updated.

---

### C.22: config_shadowing

**Intended**: Both request and background paths use timeout=30.

**Strengths**:
- Tests both code paths.

**Weak spots**:
- Trivially simple. A model that hardcodes `return {"timeout": 30, "source": "request"}` passes.
- No test for other config values (retries, etc.).
- No test that verifies the config hierarchy (DEFAULTS -> env_config -> service) works for arbitrary values.

**Recommendations**:
1. Test with a different config value to verify the hierarchy, not just the hardcoded 30.
2. Verify that the fix changes the right layer (defaults.py) not the service layer.

---

### C.23: commit_gate

**Intended**: Both commit() and freeze_view() are independently necessary.

**Strengths**:
- Tests three independent properties: total, consistency, preview isolation.
- Unsorted input catches models that don't implement proper sorting in commit().

**Weak spots**:
- Each call (ingest, ingest_and_verify, preview) creates fresh state. Doesn't test state
  accumulation or incremental updates.

**Recommendations**:
1. Add incremental update test (ingest once, then update with new entries).

---

### C.24: overdetermination

**Intended**: After two updates, store contains the latest value.

**Strengths**:
- Uses lambdas to generate different values (42 then 99).

**Weak spots**:
- Only two updates. A model that just stores the last value without understanding the
  dual-writer problem would pass by accident if write_cached is simply removed.
  But that IS the correct fix, so this is actually fine.

**Recommendations**:
1. Add a third update and verify latest.
2. Verify version tracking is correct.

---

### C.25-C.28: Concurrency family (lost_update, check_then_act, ordering_dependency, false_fix_deadlock)

**Intended**: Various concurrency-related invariants.

**THESE ARE THE STRONGEST TESTS IN THE SUITE.**

**Strengths**:
- lost_update and check_then_act have anti-hardcoding checks (test with non-default starting values).
- Both sequential and interleaved scenarios tested.
- Structural checks verify all functions still exist.
- false_fix_deadlock checks conservation, no negatives, and no deadlock.
- ordering_dependency checks exact log output.

**Weak spots**:
- Anti-hardcoding tests only use one alternative value. Two would be more robust.
- ordering_dependency doesn't test triple-ordering (a before init, b before init, then init).
- false_fix_deadlock doesn't verify the specific amounts after transfer (only total and non-negative).

**Recommendations**:
1. Add a second anti-hardcoding check with different values.
2. ordering_dependency: add a test where multiple items arrive before init.

---

## Section D -- Case-Level Red Flags

### D.1: wrong_condition_a -- MISLEADING

**Case ID**: wrong_condition_a
**Intended**: Fix `>` to `>=` in is_rate_limited.
**Actual test**: Only checks `is_rate_limited(5, 5) == True`.
**Weakness**: `return True` passes (always rate-limit).
**Example incorrect code that passes**: `def is_rate_limited(c, l): return True`
**Example valid code that fails**: None identified.
**Fix**: Add `assert is_rate_limited(4, 5) == False`.

### D.2: wrong_condition_b -- MISLEADING

**Case ID**: wrong_condition_b
**Intended**: Fix `or` to `and` in is_allowed.
**Actual test**: Only checks one denied scenario.
**Weakness**: `return False` passes (always deny).
**Fix**: Add `assert is_allowed(50, 100, 5000, 10000) == True`.

### D.3: wrong_condition_c -- MISLEADING

**Case ID**: wrong_condition_c
**Intended**: Fix operator precedence in should_allow.
**Actual test**: Only checks one rejection scenario.
**Weakness**: `return False` passes.
**Fix**: Add test where non-expired, under-limit, non-exempt should be allowed.

### D.4: partial_rollback_a -- MISLEADING

**Case ID**: partial_rollback_a
**Intended**: Failed charge must release inventory.
**Actual test**: Only checks failure path.
**Weakness**: No-op place_order passes.
**Example incorrect code that passes**: `def place_order(*a): pass`
**Fix**: Add successful order test first.

### D.5: partial_rollback_b -- MISLEADING

Same issue as D.4 but with gateway_fail pattern.

### D.6: partial_rollback_c -- MISLEADING

Same issue as D.4 but also checks audit log cleanup.

### D.7: invariant_partial_fail -- MISLEADING

**Case ID**: invariant_partial_fail
**Intended**: Balance conservation on transfer failure.
**Actual test**: Only checks total after forced failure.
**Weakness**: No-op execute_transfer preserves totals trivially.
**Fix**: Add success path test with random returning 0.99.

### D.8: temporal_drift_a/b/c -- WEAK

**Case ID**: temporal_drift_a, temporal_drift_b, temporal_drift_c
**Intended**: raw_stats from original data, not normalized.
**Actual test**: Only checks raw_stats.
**Weakness**: Model can remove normalization entirely and pass.
**Fix**: Also verify normalized output.

### D.9: partial_update_c -- WEAK (metadata mismatch)

**Case ID**: partial_update_c
**Intended**: Email change resets verified AND clears cached_greeting.
**Actual test**: Only checks verified.
**Weakness**: Half the fix surface is untested.
**Fix**: Assert cached_greeting changed after email update.

### D.10: cache_invalidation_order -- WEAK (metadata mismatch)

**Case ID**: cache_invalidation_order
**Intended**: Cache ordering with version-based conditional set.
**Actual test**: Only tests basic read-after-write.
**Weakness**: safe_update and cache_conditional_set are never exercised.
**Fix**: Add tests for safe_update path.

---

## Section E -- Trustworthiness Ranking

### STRONG (reliable signal, anti-gaming measures present)
- `lost_update` -- anti-hardcoding, multi-scenario, structural checks
- `check_then_act` -- anti-hardcoding, multi-scenario, structural checks
- `false_fix_deadlock` -- multi-scenario, conservation, no-negative checks
- `mutable_default` (all variants) -- direct isolation test, cross-function

### ADEQUATE (tests the right invariant but has minor gaps)
- `alias_config` -- tests isolation but misses override verification
- `stale_cache` -- tests read-after-write correctly
- `retry_dup` -- tests exactly-once correctly
- `effect_order` -- tests per-item effects correctly
- `ordering_dependency` -- tests both orderings
- `hidden_dep_multihop` -- tests overwrite correctly
- `overdetermination` -- tests latest value correctly
- `commit_gate` -- tests three properties
- `l3_state_pipeline` -- tests frozen gate and total
- `early_return` -- tests entry count
- `index_misalign` -- tests alignment
- `missing_branch` -- tests missing role

### WEAK (significant gaps, may allow wrong code to pass)
- `partial_update_c` -- untested cached_greeting (metadata mismatch)
- `use_before_set` -- doesn't verify correct status/values
- `lazy_init` -- fragile state reset, no before-state check
- `temporal_drift` -- doesn't verify normalization works
- `silent_default` -- fragile reset, single-flag check
- `config_shadowing` -- trivially simple, no hierarchy verification
- `async_race_lock` -- checks proxy (before/after fields) not actual locking
- `cache_invalidation_order` -- ignores version-based features (metadata mismatch)
- `feature_flag_drift` -- doesn't test without flag, bypasses flag system

### MISLEADING (trivially wrong code can pass)
- `wrong_condition_a` -- `return True` passes
- `wrong_condition_b` -- `return False` passes
- `wrong_condition_c` -- `return False` passes
- `partial_rollback_a` -- no-op passes
- `partial_rollback_b` -- no-op passes
- `partial_rollback_c` -- no-op passes
- `invariant_partial_fail` -- no-op passes

---

## Section F -- Improvement Plan

### Priority 1: CRITICAL fixes (before trusting ANY results)

1. **Fix wrong_condition tests**: Add complementary allow-path assertions.
   Each test must verify at least one scenario where the function SHOULD allow.
   - Estimated effort: 15 lines per test variant (9 total).

2. **Fix partial_rollback tests**: Add successful-order test before the failure test.
   Each test must verify that a well-funded order succeeds and reduces inventory.
   - Estimated effort: 10 lines per test variant (3 total).

3. **Fix invariant_partial_fail test**: Add success-path test with random > 0.3.
   Verify transfer completes: sender debited, receiver credited.
   - Estimated effort: 15 lines.

### Priority 2: HIGH-value test hardening

4. **Add override verification to alias_config**: Assert cfg1 received the override.
5. **Fix partial_update_c**: Assert cached_greeting changed after email update.
6. **Add normalization check to temporal_drift**: Verify normalized output in addition to raw_stats.
7. **Add success-path test to retry_dup**: Test failure-then-success path.
8. **Add flag-off test to feature_flag_drift**: Verify v1 pricing without flag.
9. **Add existing-role test to missing_branch**: Verify "viewer" still has read-only.
10. **Fix use_before_set**: Verify r1 (the non-edge case) returns correct values.

### Priority 3: Harness cleanup / unification

11. **Remove mutation test inflation**: Stop counting V2 mutation tests as passed (they don't run).
12. **Document canonical execution path**: Specify which path produces research-grade scores.
13. **Add test-function resolution test**: Verify every case resolves to a specific function.
14. **Make state reset robust**: Prefer `reset()` function over direct variable assignment.

### Priority 4: Additional edge cases

15. **Multi-call accumulation tests** for all stateful families (call 3+ times, not just 2).
16. **Identity checks** for alias_config (cfg1 is not cfg2).
17. **Multi-mutation tests** for index_misalign (insert, delete, insert, verify).
18. **safe_update/version tests** for cache_invalidation_order.
19. **Multi-item before-init test** for ordering_dependency.

### Priority 5: Adversarial regression tests

20. **Add "always-True" and "always-False" regression tests** for wrong_condition.
21. **Add "no-op function" regression test** for partial_rollback and invariant_partial_fail.
22. **Add "remove normalization" regression test** for temporal_drift.
23. **Add "hardcode output" regression test** for config_shadowing and feature_flag_drift.
24. **Add "give everyone admin" regression test** for missing_branch.

### Priority 6: Optional longer-term improvements

25. **Module isolation tests** for multi-file cases (verify imports resolve correctly).
26. **Property-based fuzzing** for stale_cache (random add/update/read sequences).
27. **Difficulty-calibration audit**: verify a/b/c variants are actually increasing in difficulty.
28. **Cross-execution-path consistency test**: verify concat and disk-backed paths agree on all cases.

---

## Section G -- Concrete Proposed Test Additions

### G.1: wrong_condition -- add allow-path tests

```python
# In test_a, ADD after the existing assertion:
result_under = is_rate_limited(4, 5)
if result_under:
    return False, ["is_rate_limited(4, 5) should return False (under limit)"]

result_zero = is_rate_limited(0, 5)
if result_zero:
    return False, ["is_rate_limited(0, 5) should return False (no requests)"]

# In test_b, ADD:
result_ok = is_allowed(requests_per_minute=50, rate_limit=100,
                       daily_total=5000, daily_quota=10000)
if not result_ok:
    return False, ["is_allowed should return True when both rate and quota are within limits"]

# In test_c, ADD:
result_valid = should_allow(
    client_id="regular-client", count=50, limit=100,
    timestamp=95, now=100, window_seconds=60,
    exempt_list=set())
if not result_valid:
    return False, ["should_allow should return True for valid non-expired under-limit request"]
```

### G.2: partial_rollback -- add happy-path test

```python
# In test_a, ADD before the failure test:
inv_ok = mod.Inventory(10)
wallet_ok = mod.Wallet(100)  # enough balance
mod.place_order(inv_ok, wallet_ok, 3, 10.0)  # should succeed
if inv_ok.available() != 7:
    return False, [f"successful order: available={inv_ok.available()}, expected 7"]

# In test_b, ADD:
mod.set_gateway_fail(False)
mod.place_order("SKU-100", 2, 10.0)
if mod.available("SKU-100") != 8:
    return False, [f"successful order: available={mod.available('SKU-100')}, expected 8"]

# In test_c, ADD:
mod.set_gateway_fail(False)
mod.place_order("WIDGET-1", 3, 5.0)
if mod.available("WIDGET-1") != 17:
    return False, [f"successful order: available={mod.available('WIDGET-1')}, expected 17"]
audit = mod.get_audit_log()
if len(audit) != 1:
    return False, [f"successful order should produce 1 audit entry, got {len(audit)}"]
```

### G.3: invariant_partial_fail -- add success path

```python
# ADD before the failure test:
sender_ok = Account("s2", 100)
receiver_ok = Account("r2", 0)
_random_mod.random = lambda: 0.99  # above threshold, no failure
execute_transfer(sender_ok, receiver_ok, 50)
if sender_ok.balance != 50:
    return False, [f"success path: sender balance={sender_ok.balance}, expected 50"]
if receiver_ok.balance != 50:
    return False, [f"success path: receiver balance={receiver_ok.balance}, expected 50"]
```

### G.4: temporal_drift -- verify normalization preserved

```python
# ADD in test_a after raw_stats check:
normalized = result.get("normalized", result.get("result", []))
if normalized == data:
    return False, ["case_data was not normalized -- normalization step may have been removed"]
if max(normalized) > 1.0:
    return False, [f"normalized max={max(normalized)}, expected <= 1.0"]
```

### G.5: alias_config -- verify overrides applied

```python
# In test_a, ADD after cfg1 = create({"timeout": 5}):
if cfg1.get("timeout") != 5:
    return False, [f"override not applied: cfg1['timeout']={cfg1.get('timeout')}, expected 5"]

# ADD identity check:
if cfg1 is cfg2:
    return False, ["create_config returned same object for both calls"]
```

### G.6: partial_update_c -- verify cached_greeting

```python
# ADD after the email update:
new_greeting = user.get("cached_greeting")
if new_greeting == old_greeting and old_greeting is not None:
    return False, [
        f"cached_greeting not updated after email change: "
        f"still {new_greeting!r}"
    ]
```

### G.7: missing_branch -- verify existing roles

```python
# In test_a, ADD:
viewer_perms = get_perms("viewer")
if "write" in viewer_perms or "delete" in viewer_perms:
    return False, [f"viewer should not have write/delete, got: {viewer_perms}"]
admin_perms = get_perms("admin")
if "admin" not in admin_perms and "delete" not in admin_perms:
    return False, [f"admin should have admin/delete, got: {admin_perms}"]
```

### G.8: use_before_set -- verify non-edge case works

```python
# In test_b, ADD before the empty-input test:
if r1["count"] != 3:
    return False, [f"first call count={r1['count']}, expected 3"]
if r1["status"] != "loaded":
    return False, [f"first call status={r1['status']!r}, expected 'loaded'"]

# In test_c, ADD:
if r1 is None or r1.get("id") != "h1":
    return False, [f"first call (high-value records) should return h1, got {r1}"]
```

### G.9: cache_invalidation_order -- test safe_update

```python
# ADD a second test path:
for attr in ("_data", "_version", "_tables"):
    d = getattr(mod, attr, None)
    if isinstance(d, dict):
        d.clear()

safe_put = getattr(mod, "safe_put", None)
if safe_put:
    safe_put("k2", "v1")
    r1 = read_record("k2")
    safe_put("k2", "v2")
    r2 = read_record("k2")
    if r2 != "v2":
        return False, [f"safe_put stale: {r2!r}, expected 'v2'"]
```

### G.10: Adversarial regression -- no-op detection

For partial_rollback and invariant_partial_fail, add a meta-check:

```python
# Verify the function isn't a no-op by checking it has at least some effect
# when conditions are right (successful path).
# If the successful-path test passes but produces no state change, flag it.
```

This is already covered by G.2 and G.3 above.

---

## Appendix: Case Coverage Matrix

| Family | Variants | Happy Path | Failure Path | Multi-Call | Anti-Hardcode | State Reset | Rating |
|--------|----------|------------|--------------|------------|---------------|-------------|--------|
| alias_config | a,b,c | PARTIAL | YES | YES | NO | YES | ADEQUATE |
| partial_update | a,b,c | YES | N/A | NO | NO | NO | ADEQUATE |
| stale_cache | a,b,c | YES | N/A | NO | NO | YES | ADEQUATE |
| lazy_init | a,b,c | PARTIAL | N/A | NO | NO | FRAGILE | WEAK |
| mutable_default | a,b,c | YES | N/A | YES | NO | YES | STRONG |
| effect_order | a,b,c | YES | N/A | NO | NO | FRAGILE | ADEQUATE |
| use_before_set | a,b,c | PARTIAL | N/A | YES | NO | FRAGILE | WEAK |
| retry_dup | a,b,c | YES | NO | NO | NO | YES | ADEQUATE |
| partial_rollback | a,b,c | **NO** | YES | NO | NO | YES | **MISLEADING** |
| temporal_drift | a,b,c | PARTIAL | N/A | NO | NO | NO | WEAK |
| missing_branch | a,b,c | PARTIAL | NO | NO | NO | NO | WEAK |
| wrong_condition | a,b,c | **NO** | YES | NO | NO | NO | **MISLEADING** |
| early_return | a,b,c | YES | N/A | YES | NO | YES | ADEQUATE |
| index_misalign | a,b,c | YES | N/A | NO | NO | YES | ADEQUATE |
| silent_default | a,b,c | YES | NO | NO | NO | FRAGILE | WEAK |
| l3_state_pipeline | 1 | YES | N/A | NO | NO | NO | ADEQUATE |
| cache_inv_order | 1 | YES | N/A | NO | NO | YES | WEAK |
| feature_flag_drift | 1 | YES | N/A | NO | NO | YES | WEAK |
| invariant_partial_fail | 1 | **NO** | YES | NO | NO | YES | **MISLEADING** |
| async_race_lock | 1 | YES | N/A | NO | NO | YES | WEAK |
| hidden_dep_multihop | 1 | YES | N/A | YES | NO | YES | ADEQUATE |
| config_shadowing | 1 | YES | N/A | NO | NO | NO | WEAK |
| commit_gate | 1 | YES | N/A | NO | NO | NO | ADEQUATE |
| overdetermination | 1 | YES | N/A | YES | NO | YES | ADEQUATE |
| lost_update | 1 | YES | YES | YES | **YES** | YES | **STRONG** |
| check_then_act | 1 | YES | YES | YES | **YES** | YES | **STRONG** |
| ordering_dependency | 1 | YES | YES | NO | NO | YES | ADEQUATE |
| false_fix_deadlock | 1 | YES | YES | YES | NO | YES | **STRONG** |

Legend:
- Happy Path: Does the test verify the function works correctly in the normal case?
- Failure Path: Does the test verify failure handling / boundary behavior?
- Multi-Call: Does the test call the main function 2+ times to check state accumulation?
- Anti-Hardcode: Does the test use varying inputs to prevent hardcoded outputs?
- State Reset: Does the test properly reset module state before running?
