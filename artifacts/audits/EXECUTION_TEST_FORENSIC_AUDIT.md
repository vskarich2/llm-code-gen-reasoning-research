# Execution Test Forensic Audit

**Date:** 2026-03-30
**Scope:** All 28 test files in `tests_v2/`, the `exec_eval.py` harness, and `code_assembly.py`
**Standard:** Adversarial — assume guilty until proven innocent

---

## Section A — Executive Verdict

**The test suite is broadly trustworthy for its intended purpose but has specific structural weaknesses that must be disclosed.**

**Strong:**
- State management families (aliasing, stale cache, mutable default, partial update) are well-designed with multi-call sequences that genuinely test the invariant
- Rollback/compensation tests (partial_rollback, invariant_partial_fail) use failure injection correctly
- The harness provides good isolation via unique module names per case
- Tests detect the actual bug mechanism, not just symptoms, in most families

**Weak:**
- Race condition cases (lost_update, check_then_act, false_fix_deadlock) test simulated interleavings defined in the *buggy code itself*, not the model's code — the model's fix must work within the case's simulation framework, which constrains valid fixes
- Several single-assertion tests (overdetermination, config_shadowing, lost_update) are too minimal to distinguish correct fixes from lucky coincidences
- Retry tests (retry_dup) only test the success path — they never inject failures, so a `break` on first try passes without testing retry behavior at all
- No test has an explicit negative check (regression against known wrong fixes)

**Highest-risk flaws:**
1. **Race condition simulation lock-in** — models must use the case's step-function framework, not real concurrency primitives
2. **retry_dup success-only testing** — the core retry behavior (retry on failure, then succeed) is never tested
3. **No degenerate-code guards** — a model that returns `def sequential_double_increment(): return 2` passes lost_update

**Caveat for preliminary results:** Pass rates on race condition cases and retry cases should be interpreted as "model produced code that works within the case's simulation framework" rather than "model fixed the concurrency/retry bug." This is a meaningful distinction for the paper.

---

## Section B — Harness-Level Findings

### B1: No degenerate-code rejection
**Severity:** HIGH
**Location:** `exec_eval.py:746-755`
**Problem:** The only code validation is `len(code.strip()) < 10`. A model could return hardcoded functions that satisfy the test without implementing any logic.
**Example:** `def sequential_double_increment(): return 2` passes test_lost_update.
**Impact:** Inflates pass rates for simple cases where the expected output is a constant.
**Recommendation:** Add structural checks — verify the model's code references the case's key functions/variables (e.g., `get()`, `_set()`, `_value` for lost_update).

### B2: Mutation test is weak idempotency check, not adversarial
**Severity:** MEDIUM
**Location:** `exec_eval.py:993-1020`
**Problem:** Mutation test calls `test_fn(mod)` twice on the same module. This catches tests that mutate state without reset, but does NOT catch degenerate code or wrong fixes that happen to be idempotent.
**Impact:** Mutation test provides false confidence — passing it does not mean the fix is robust.
**Recommendation:** Add a third run with modified inputs (e.g., different batch data) to detect hardcoded returns.

### B3: Test dispatch fallback chain can mask missing tests
**Severity:** LOW
**Location:** `exec_eval.py:581-624` (`_load_v2_test`)
**Problem:** If `test_c()` is missing, the loader tries `test()`, then `test_a()`. A case labeled difficulty=C could silently run the A-level test.
**Impact:** Would only matter if test files are incomplete, which they currently are not.
**Recommendation:** Add assertion that the difficulty-level function exists, or log a warning.

### B4: sys.modules never cleaned up
**Severity:** LOW
**Location:** `exec_eval.py:51`
**Problem:** Every `load_module_from_code` call adds to `sys.modules` but never removes. In a 3480-case ablation, this adds ~3500 entries.
**Impact:** Memory growth, no functional issue. Could slow imports in long runs.
**Recommendation:** Delete module from `sys.modules` after test completes.

---

## Section C — Invariant-Family Audit

### C1: Aliasing (alias_config a/b/c)
**Intends to measure:** Shared reference mutation — `create_config()` must return independent dicts.
**Actually measures:** Exactly that. Two calls, check second is uncontaminated.
**Strengths:** State reset before test. Checks both return value AND global DEFAULTS.
**Weak spots:** Only checks one contamination scenario (timeout override). Doesn't check deep nesting.
**False positives:** None likely — `.copy()` is required.
**False negatives:** A model that copies only top-level keys but shares nested dicts would pass.
**Rating: STRONG**

### C2: Stale Cache (stale_cache a/b/c)
**Intends to measure:** Cache invalidation after write.
**Actually measures:** Update-then-read sequence detects stale cache.
**Strengths:** Good — write, read, write, read sequence. Checks value equality.
**Weak spots:** Single key tested. Doesn't test cache expiry or multi-key consistency.
**False positives:** None likely.
**False negatives:** Model that invalidates only for key "p1" but not others would pass.
**Rating: STRONG**

### C3: Mutable Default (mutable_default a/b/c)
**Intends to measure:** Default argument accumulation across calls.
**Actually measures:** Two calls with independent inputs, checks second call's result is clean.
**Strengths:** Well-designed. Level C tests decorator closure isolation, which is non-trivial.
**Weak spots:** None significant.
**Rating: STRONG**

### C4: Partial Rollback (partial_rollback a/b/c)
**Intends to measure:** Compensation/rollback on failure.
**Actually measures:** Failure injection → check state restored. Good.
**Strengths:** Multiple assertions (available, reserved, audit_log). Proper try/except for expected errors.
**Weak spots:** Only tests one failure scenario per level. Doesn't test partial success (3 of 5 items committed, then failure).
**Rating: STRONG**

### C5: Effect Order (effect_order a/b/c)
**Intends to measure:** Per-item side effects vs batch-end side effects.
**Actually measures:** Cardinality check — `len(snapshots) == 3` for 3 items.
**Strengths:** Clean, direct test of the invariant.
**Weak spots:** Doesn't check order of snapshots (only count). A model that calls snapshot() 3 times at the end would pass.
**Adversarial example:** `for item in items: _counter += item` followed by `for _ in items: snapshot()` passes but has wrong timing.
**Rating: ADEQUATE** — count is correct but ordering is not verified.

### C6: Race Conditions (lost_update, check_then_act, false_fix_deadlock, async_race_lock)
**Intends to measure:** Atomicity / lock correctness.
**Actually measures:** Whether the model's code works within a step-function simulation framework defined by the case's own code.

**Critical structural issue:** The race condition cases don't use real threads. They use `run_steps()` and `make_increment_steps()` defined in the buggy code. The test calls `mod.sequential_double_increment()` and `mod.interleaved_double_increment()`, which are functions in the case code that SET UP the interleaving.

This means:
1. The model must understand and preserve the step-function simulation framework
2. The model cannot just "add a lock" — it must restructure the steps to be atomic
3. Valid concurrency fixes using `threading.Lock` or `asyncio` would fail because they don't match the simulation model

**lost_update / check_then_act specifically:**
- `test_lost_update.py` has 2 assertions on 2 function calls. Zero state validation.
- A model that returns `def sequential_double_increment(): return 2; def interleaved_double_increment(): return 2` passes.
- The test doesn't verify the model actually uses `get()`, `_set()`, or any counter logic.

**false_fix_deadlock:**
- Slightly better — checks both `sequential_transfers()` and `interleaved_transfers()` return dicts with A+B=200.
- But still: `def sequential_transfers(): return {"A": 100, "B": 100}` passes.

**async_race_lock:**
- Best of the group — checks that each result has 'before' and 'after' fields, proving `process_item` (with locking) was used instead of `quick_increment`.
- Harder to fake — model must produce the right data structure.

**Rating: WEAK** (lost_update, check_then_act), **ADEQUATE** (false_fix_deadlock), **STRONG** (async_race_lock)

### C7: Retry Duplication (retry_dup a/b/c)
**Intends to measure:** Retry loops don't duplicate messages.
**Actually measures:** Single successful call produces exactly one message.

**Critical flaw:** All three levels call with `fail_first=False` or equivalent (the send always succeeds on first try). The retry loop is never actually exercised. A model that removes the retry loop entirely passes because the first attempt succeeds.

**test_a:** `retry_send("hello", max_retries=2)` — always succeeds first try.
**test_b:** `send_with_retry("order_123", max_retries=2, fail_first=False)` — explicit no-failure.
**test_c:** `ingest("payment_456", max_pipeline_retries=2, fail_first=False)` — explicit no-failure.

**Missing test:** `send_with_retry("msg", max_retries=2, fail_first=True)` — should succeed after retry but produce exactly 1 message.

**Rating: WEAK** — tests only the degenerate case where retry is unnecessary.

### C8: Temporal Drift (temporal_drift a/b/c)
**Intends to measure:** Raw statistics computed on original data, not transformed data.
**Actually measures:** Exact numeric assertions on specific input values.
**Strengths:** Concrete numeric checks (raw_max=80, raw_min=10, raw_sum=190).
**Weak spots:** Fixed test data means model could hardcode `{"raw_max": 80, "raw_min": 10}`.
**Rating: ADEQUATE** — correct invariant but vulnerable to hardcoding.

### C9: Use Before Set (use_before_set a/b/c)
**Intends to measure:** Stale variable from previous call leaking into next call.
**Actually measures:** Two calls, second with empty/different input, check result reflects current call.
**Strengths:** Well-designed — the two-call pattern directly tests the bug.
**Rating: STRONG**

### C10: Missing Branch (missing_branch a/b/c)
**Intends to measure:** Missing case in dispatch/dict.
**Actually measures:** Call with the missing role, check non-empty/correct permissions.
**Strengths:** Direct test of the missing case.
**Weak spots:** Only tests the missing role. Doesn't verify existing roles still work correctly.
**Rating: ADEQUATE** — would benefit from regression check on existing roles.

### C11: Index Misalign (index_misalign a/b/c)
**Intends to measure:** Parallel data structure synchronization.
**Actually measures:** Insert/delete operations, then verify alignment.
**Strengths:** Multi-step mutation sequences with position-specific assertions. Level C tests three-way sync.
**Rating: STRONG**

### C12: Hidden Dep Multihop
**Intends to measure:** Write-through cache must overwrite (not put-if-absent).
**Actually measures:** Two saves with different names, read returns second.
**Strengths:** Direct test. Checks intermediate state (name1=="Alice") before second save.
**Rating: STRONG**

### C13: Feature Flag Drift
**Intends to measure:** Flag propagation through call chain.
**Actually measures:** `checkout(use_new_pricing=True)` → total==900 (discounted) not 1000.
**Strengths:** Numeric assertion tied to specific pricing logic. Also checks flag cleanup.
**Weak spots:** Only one call. Model could hardcode total=900.
**Rating: ADEQUATE**

### C14: Invariant Partial Fail
**Intends to measure:** Balance conservation after failed transfer.
**Actually measures:** Monkey-patches `random.random` to trigger failure, checks balance conserved.
**Strengths:** Proper try/finally for random restoration. Checks both sender and receiver.
**Weak spots:** Only tests one failure path. Doesn't test successful transfer to verify it also works.
**Rating: STRONG** for what it tests, but should also verify the happy path.

### C15: Overdetermination / Config Shadowing
**Intends to measure:** Stale cache overwrite / structural config default.
**Actually measures:** Minimal — single call, single assertion on output value.
**Weak spots:** `def run_system_check(): return {"request": {"timeout": 30}, "background": {"timeout": 30}}` passes config_shadowing. `def serve_request(id): return {"value": 99}` passes overdetermination.
**Rating: WEAK** — both are trivially satisfiable by hardcoding.

### C16: L3 Pipeline / Commit Gate
**Intends to measure:** Multi-step causal necessity (commit + freeze_view both required).
**Actually measures:** Three assertions (frozen==True, stable non-empty, total==30) for l3_state_pipeline. Three properties (total, consistency, preview) for commit_gate.
**Strengths:** Good composite checks — each assertion probes a different pipeline step.
**Rating: ADEQUATE** — harder to fake because three independent properties must hold simultaneously.

---

## Section D — Case-Level Red Flags

### D1: lost_update
**Intended:** Non-atomic read-modify-write under interleaving.
**Actual:** Two function calls, check both return 2.
**Weakness:** Trivially passable by `return 2`. No structural check on model code.
**Degenerate pass:** `def sequential_double_increment(): return 2`
**Valid fail:** Model that adds real threading.Lock would fail if it doesn't preserve the step-function simulation.
**Fix:** Add assertion that `_value` was actually modified (e.g., `assert mod.get() == 2 after interleaved`), or add a third interleaving pattern.

### D2: check_then_act
**Intended:** TOCTTOU race on balance check.
**Actual:** Same structure as lost_update — two function calls, check return values.
**Weakness:** Same — `def sequential_withdrawals(): return 20` passes.
**Fix:** Same as D1.

### D3: retry_dup_a/b/c (all three)
**Intended:** Retry loop produces exactly one message.
**Actual:** Only tests success-on-first-attempt. Retry path never exercised.
**Weakness:** Model that removes retry loop entirely passes.
**Degenerate pass:** `def retry_send(msg, max_retries=2): _sent.append(msg)` (no retry, no loop).
**Fix:** Add test with `fail_first=True` that verifies: (a) retry happened, (b) exactly 1 message stored.

### D4: overdetermination
**Intended:** Stale cache masked by fresh writer.
**Actual:** Two updates, one read, check value==99.
**Weakness:** Trivially passable by hardcoding.
**Fix:** Add a second test with different values, or verify intermediate state.

### D5: config_shadowing
**Intended:** Structural default masked by config layer.
**Actual:** Single function call, check two fields equal 30.
**Weakness:** Trivially passable by hardcoding.
**Fix:** Test with different config values, or verify the config propagation chain.

### D6: effect_order_a
**Intended:** Snapshot per item, not per batch.
**Actual:** Checks `len(snapshots) == 3`.
**Weakness:** Doesn't verify snapshot values or ordering.
**Adversarial pass:** Snapshot 3 times at batch end with wrong values.
**Fix:** Check `snapshots == [10, 30, 60]` (running totals after each item).

---

## Section E — Trustworthiness Ranking

### STRONG (reliable oracle, hard to game)
- alias_config (a/b/c)
- stale_cache (a/b/c)
- mutable_default (a/b/c)
- partial_rollback (a/b/c)
- index_misalign (a/b/c)
- use_before_set (a/b/c)
- hidden_dep_multihop
- invariant_partial_fail
- async_race_lock

### ADEQUATE (correct invariant, minor gaps)
- early_return (a/b/c)
- partial_update (a/b/c)
- lazy_init (a/b/c)
- missing_branch (a/b/c)
- temporal_drift (a/b/c)
- wrong_condition (a/b/c)
- silent_default (a/b/c)
- feature_flag_drift
- l3_state_pipeline
- commit_gate
- ordering_dependency
- cache_invalidation_order

### WEAK (significant oracle gaps)
- lost_update
- check_then_act
- false_fix_deadlock
- retry_dup (a/b/c)
- overdetermination
- config_shadowing

### MISLEADING (none)
No test is actively misleading — even weak tests measure something real. But the weak tests should not be cited as evidence of concurrency bug fixing capability.

---

## Section F — Improvement Plan

### Priority 1: Critical fixes before trusting results
1. **retry_dup: Add failure-then-retry test** — call with `fail_first=True`, assert exactly 1 message after successful retry
2. **lost_update / check_then_act: Add structural assertion** — verify model code actually calls `get()`/`_set()` or modifies the step functions, not just returns a constant

### Priority 2: High-value test hardening
3. **effect_order: Check snapshot values, not just count** — assert `snapshots == [10, 30, 60]`
4. **overdetermination / config_shadowing: Add second test with different values** — prevents hardcoded returns
5. **false_fix_deadlock: Add balance check per-account** — verify A≥0 and B≥0 individually, not just sum

### Priority 3: Missing coverage
6. **partial_rollback: Test partial success** — 3 of 5 items succeed, then failure on item 4, verify items 1-3 rolled back
7. **invariant_partial_fail: Test happy path** — verify successful transfer also conserves balance
8. **missing_branch: Regression on existing roles** — verify admin/user still work after moderator is added

### Priority 4: Adversarial regression tests
9. **All race condition cases: Add "return constant" rejection** — verify model code actually uses the case's counter/account primitives
10. **temporal_drift: Add second input dataset** — prevents hardcoded raw_stats

### Priority 5: Optional improvements
11. **Harness: Clean up sys.modules after each test**
12. **Harness: Add structural validation (model code must define certain functions)**
13. **Test dispatch: Warn if difficulty-level function is missing and fallback is used**

---

## Section G — Concrete Proposed Test Additions

### G1: retry_dup — failure-then-success test
```python
# After existing test_a:
mod.reset()  # or mod._sent = []
mod.retry_send("world", max_retries=3, fail_first=True)  # first attempt fails
sent = mod.get_sent()
assert len(sent) == 1, "retry produced duplicate after failure+success"
assert sent[0] == "world"
```

### G2: lost_update — anti-hardcoding check
```python
# After existing assertions:
# Verify the module actually uses the counter mechanism
assert hasattr(mod, '_value'), "model removed counter state"
assert hasattr(mod, 'get'), "model removed get()"
# Run with different initial state
mod.reset()
mod._set(10)
read_a, write_a = mod.make_increment_steps()
read_b, write_b = mod.make_increment_steps()
mod.run_steps([(read_a, ()), (write_a, ()), (read_b, ()), (write_b, ())])
assert mod.get() == 12, "hardcoded return detected"
```

### G3: effect_order — value check
```python
# Replace len check with value check:
snapshots = mod.get_snapshots()  # or mod._snapshots
assert snapshots == [10, 30, 60], f"wrong snapshot values: {snapshots}"
```

### G4: overdetermination — second value test
```python
# After first test:
mod.reset()
mod.update_product("P2", lambda: 7)
mod.update_product("P2", lambda: 13)
result = mod.serve_request("P2")
assert result["value"] == 13, "hardcoded to 99"
```

### G5: false_fix_deadlock — per-account bounds
```python
# After existing checks:
assert seq.get("A", 0) >= 0, f"account A negative: {seq['A']}"
assert seq.get("B", 0) >= 0, f"account B negative: {seq['B']}"
assert interleaved.get("A", 0) >= 0, f"account A negative in interleaved"
assert interleaved.get("B", 0) >= 0, f"account B negative in interleaved"
```

### G6: partial_rollback — partial success scenario
```python
# New test: 5 items, failure on item 3
mod.add_product("SKU-200", 5)
mod.set_gateway_fail_after(2)  # fails on 3rd charge
try:
    mod.place_batch_order("SKU-200", quantities=[1,1,1,1,1], price=10.0)
except ValueError:
    pass
# All 5 items should be available (none permanently reserved)
assert mod.available("SKU-200") == 5
```

### G7: check_then_act — anti-hardcoding
```python
# Different starting balance
mod.reset()
mod.create_account("bob", 200)
check_a, act_a = mod.make_withdraw_steps("bob", 150)
check_b, act_b = mod.make_withdraw_steps("bob", 150)
mod.run_steps([(check_a, ()), (act_a, ()), (check_b, ()), (act_b, ())])
assert mod.get_balance("bob") == 50, "sequential withdrawal wrong"
```
