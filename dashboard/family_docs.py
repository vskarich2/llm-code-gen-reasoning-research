"""Per-family documentation for the Family Breakdown tab.

FAMILY_DOCS: general overview (rendered in tab-level documentation expander).
FAMILY_NARRATIVES: per-family descriptions (rendered inside case reference panels).
"""

FAMILY_DOCS = """\
**What this tab is for:** identifying which bug types are hardest and where the reasoning-execution gap concentrates.

**How to read it:**
- Compare **Pass%** across families within a model-condition: which bug types are hardest?
- Compare **LEG%** across families: high LEG = model understands the bug but can't implement the fix.
- Low LEG + low Pass% = model doesn't even understand those bugs. Different problem.
- High **Lucky%** = tests may not discriminate enough for that bug type.

**Column legend:** Pass% = pass rate, LEG% = LEG rate, Lucky% = lucky fix rate, R% = reasoning rate, N = count.

---

### Difficulty levels

Every family that has multiple cases follows the same difficulty progression:

| Level | Meaning | Files | Causal depth |
|-------|---------|-------|-------------|
| **A** | Single file, bug and fix in the same function. No distractors. | 1 | L1 (direct) |
| **B** | Cross-function. Bug is in one function but manifests through another. One distractor/trap. | 2 | L2 (indirect) |
| **C** | Cross-boundary. Bug spans 3+ files. Multiple traps that look like valid fixes but aren't. | 3+ | L2-L3 (deep causal) |
| **L3** | Deep causal chain. Fix requires understanding non-obvious multi-step state dependencies. | 4-5 | L3 |

The key insight: **the same underlying bug mechanism gets harder to find as you add indirection and traps.** A model that solves alias_config_a but fails alias_config_c can identify `DEFAULTS.copy()` in isolation but can't trace the reference through multiple files.
"""

FAMILY_NARRATIVES: dict[str, str] = {
    "alias_config": """\
**Shared reference aliasing** — `create_config()` returns `DEFAULTS` by reference instead of copying it. Any caller that mutates the returned dict corrupts the global defaults.

*Oracle ground truth: failure_mode=ALIASING*

**A:** single file, one function. Fix: `config = dict(DEFAULTS)`. One line.
**B:** cross-function: `app.py` has `get_settings()` that caches and mutates the reference. **Trap:** `merge_overrides()` correctly copies — looks like it's already handled, but the bug is upstream.
**C:** 3 files. Reference leaks through middleware. **Trap:** models "fix" `merge_overrides()` instead of `create_config`.
""",

    "stale_cache": """\
**Missing cache invalidation** — `update_product()` writes to DB but doesn't invalidate the cache, so `get_product()` returns stale data.

*Oracle ground truth: failure_mode=STALE_CACHE*

**A:** add `_cache.pop(product_id, None)` after the DB write.
**B:** cache in separate file with `warm()` function. **Trap:** `warm()` pre-populates but doesn't invalidate stale entries.
**C:** two cache layers (shared + local). `invalidate_shared()` called but `invalidate_local()` is not. **Trap:** shared invalidation looks sufficient but local cache is separate.
""",

    "effect_order": """\
**Side effect outside loop** — a side-effect call (snapshot/emit/audit) fires once at batch level instead of per-item inside the loop.

*Oracle ground truth: failure_mode=SIDE_EFFECT_ORDER*

**A:** `snapshot()` after the loop instead of inside it.
**B:** `emit_event()` in separate file. **Trap:** batching emit looks like optimization.
**C:** 3 files. `audit_log()` imported from separate module. **Trap:** `fast_process()` in another file legitimately batches — models "fix" the wrong function.
""",

    "mutable_default": """\
**Mutable default argument** — `def enqueue(task, queue=[])` shares the default list across all calls, accumulating state.

*Oracle ground truth: failure_mode=MUTABLE_DEFAULT*

**A:** fix: `queue=None` + `if queue is None: queue = []`.
**B:** cross-function with `seen` set. **Trap:** `seen` deduplication looks intentional but is the same mutable-default bug.
**C:** sharing hidden behind decorator closure. **Trap:** decorator pattern looks correct — shared state is an implementation detail.
""",

    "early_return": """\
**Skipped side effect on early return** — `process_payment()` returns early and skips a required ledger/audit recording.

*Oracle ground truth: failure_mode=EARLY_RETURN*

**A:** early return skips `ledger.record()`.
**B:** ledger in separate file. **Trap:** `ledger.get_summary` handles missing gracefully — looks resilient.
**C:** 3 files. Audit in separate module. **Trap:** caching in audit module is correct — models refactor the cache instead of fixing the early return.
""",

    "partial_rollback": """\
**Missing compensation on failure** — multi-step operation fails partway through but doesn't roll back completed steps.

*Oracle ground truth: failure_mode=PARTIAL_ROLLBACK*

**A:** `inventory.reserve()` succeeds, `wallet.charge()` fails, inventory stays reserved.
**B:** inventory in separate file. **Trap:** notifications list is not the bug.
**C:** 3 files. Payment gateway in separate module. **Trap:** models add retry logic instead of rollback — retry doesn't help if payment is permanently rejected.
""",

    "partial_update": """\
**Incomplete field sync** — `update_profile()` changes email but doesn't update dependent fields (display_name, verified status).

*Oracle ground truth: failure_mode=PARTIAL_STATE_UPDATE*

**A:** single file, one function.
**B:** validation in separate file. **Trap:** `validate_name` exists but doesn't fix the sync.
**C:** 3 files. **Trap:** `validate_email()` only validates format — doesn't reset verified flag. Models fix the validator instead of the update function.
""",

    "index_misalign": """\
**Parallel structure desync** — `add_entry()` appends to one parallel array but not all of them, causing index misalignment.

*Oracle ground truth: failure_mode=INDEX_MISALIGN*

**A:** single file, straightforward.
**B:** `render` looks correct in isolation. **Trap:** renderer works fine, data structure is wrong.
**C:** `recalculate_widths()` exists but is never called. **Trap:** models add recalculation in wrong place or fix renderer instead of data structure.
""",

    "missing_branch": """\
**Unhandled case in dispatch** — `get_permissions()` handles "admin" and "user" but not "moderator", silently returning empty permissions.

*Oracle ground truth: failure_mode=MISSING_BRANCH*

**A:** single file.
**B:** `validate_role` exists but doesn't fix dispatch. **Trap:** validation checks existence, not handling.
**C:** both auth.py and middleware.py need the fix. **Trap:** fixing only middleware doesn't fix auth.py.
""",

    "wrong_condition": """\
**Operator/precedence error** — comparison uses wrong operator (`>=` vs `>`, `or` vs `and`) causing off-by-one or always-true conditions.

*Oracle ground truth: failure_mode=WRONG_CONDITION*

**A:** single wrong operator.
**B:** `or` reads naturally in English. **Trap:** English-language reading is wrong in Python.
**C:** operator precedence bug. **Trap:** `a or b and c` reads as `(a or b) and c` but evaluates as `a or (b and c)`.
""",

    "silent_default": """\
**Key name mismatch** — `is_enabled()` looks up `"feature_x"` but config stores `"feature-x"`. `.get()` silently returns the default.

*Oracle ground truth: failure_mode=SILENT_DEFAULT*

**A:** single file, obvious mismatch.
**B:** `validate_config` checks top-level only. **Trap:** validation exists but doesn't catch nested key mismatch.
**C:** fallback chain across 3 files. **Trap:** every layer has the same mismatch, so fallback "works" but always returns default.
""",

    "lazy_init": """\
**Eager capture breaks lifecycle** — module-level variable captures a reference at import time. `reset_settings()` replaces the object but the captured reference still points to the old one.

*Oracle ground truth: failure_mode=INIT_ORDER*

**A:** single file.
**B:** client imports correctly but captures eagerly. **Trap:** import looks correct.
**C:** `client.refresh()` exists but handler doesn't call it. **Trap:** refresh mechanism is correct but never invoked.
""",

    "temporal_drift": """\
**Computation on wrong-stage data** — `raw_stats` computed AFTER transformation, so it reflects transformed data instead of original.

*Oracle ground truth: failure_mode=TEMPORAL_DRIFT*

**A:** single file, reorder computation.
**B:** `summarize_for_display` looks like `raw_stats`. **Trap:** they use different keys — not interchangeable.
**C:** 3 files. **Trap:** consolidating raw_stats and summarize looks like simplification but they serve different purposes.
""",

    "retry_dup": """\
**Missing break causes duplicate processing** — `retry_send()` loops on failure but doesn't break on success, so successful send gets repeated.

*Oracle ground truth: failure_mode=RETRY_DUPLICATION*

**A:** single file, add break.
**B:** store append is non-idempotent. **Trap:** store looks like it should handle duplicates.
**C:** outer retry wrapper in third file. **Trap:** adding another retry layer makes duplicates exponentially worse.
""",

    "use_before_set": """\
**Conditional variable unset** — variable only assigned inside `if` branch. When condition is false, variable is used unset → `NameError`.

*Oracle ground truth: failure_mode=USE_BEFORE_SET*

**A:** single file, initialize before conditional.
**B:** `loader.status` looks like it should always be set. **Trap:** status is only set on success path.
**C:** initialization inside loop in wrong scope. **Trap:** default inside loop body gets reset every iteration.
""",

    "async_race_lock": """\
**Lock removal breaks atomicity** — `process_item()` uses `try_lock/unlock` for atomic read-increment-read. Refactoring replaces it with `quick_increment()` which drops the lock.

*Oracle ground truth: failure_mode=RACE_CONDITION*

No A/B variants. Inherently a cross-boundary concurrency problem — atomicity only matters with multiple callers through shared state.
""",

    "hidden_dep_multihop": """\
**Function semantic mismatch** — `save_user()` must use `cache_put` (always overwrite) so `get_display_name()` returns the latest name. Refactoring swaps in `cache_put_if_absent` which only writes if key doesn't exist — stale name persists.

*Oracle ground truth: failure_mode=HIDDEN_DEPENDENCY*

Dependency chain: `save_user → sync_user_to_cache → cache_put`. The "if_absent" variant looks safer but breaks write-through semantics. Requires understanding the multi-hop data flow.
""",

    "commit_gate": """\
**Removed causal steps** — `process_batch()` had `commit(st)` and `freeze_view(st)` calls removed as "redundant." `commit` sets a frozen gate that selectors depend on; `freeze_view` rebuilds materialized view from stable state.

*Oracle ground truth: failure_mode=INVARIANT_VIOLATION*

**Trap:** restoring only `commit` passes total-value check but fails consistency check. Both calls form a causal dependency chain.
""",

    "l3_state_pipeline": """\
**Removed causal steps** — same pattern as `commit_gate`. `process_batch()` needs both `commit(st)` and `freeze_view(st)` restored.

*Oracle ground truth: failure_mode=STATE_SEMANTIC_VIOLATION*

**Trap:** restoring only one of the two calls passes partial checks but fails the full invariant. The calls gate each other: commit → freeze_view → materialize.
""",

    "cache_invalidation_order": """\
**Invalidation ordering dependency** — removing the `invalidate` call before `set` in `update_record` breaks version tracking that `cache_conditional_set` depends on.

*Oracle ground truth: failure_mode=CACHE_ORDERING*

**Trap:** removing invalidation looks like simplification but breaks the ordering contract between cache operations.
""",

    "check_then_act": """\
**Non-atomic check-then-act** — `make_withdraw_steps` separates balance check from withdrawal. Both checks pass but balance goes negative between them.

*Oracle ground truth: failure_mode=RACE_CONDITION*

**Trap:** locking only the check — both checks still pass because the act is unprotected.
""",

    "config_shadowing": """\
**Structural default masked by override** — `DEFAULTS` has `timeout: 5` but a runtime override masks it. The real fix is changing the structural default to 30, not the override chain.

*Oracle ground truth: failure_mode=PARTIAL_STATE_UPDATE*

**Trap:** fixing `background` to call `get_config()` instead of `get_defaults()` is a contingent fix that passes the test but leaves the structural cause.
""",

    "false_fix_deadlock": """\
**Circular lock ordering** — `make_transfer_b_to_a_steps` acquires locks in B→A order while `a_to_b` acquires A→B, causing deadlock.

*Oracle ground truth: failure_mode=RACE_CONDITION*

**Trap:** removing locks "fixes" deadlock but introduces race conditions. Adding timeout hides the bug.
""",

    "feature_flag_drift": """\
**Parameter not propagated** — `checkout(use_new_pricing=True)` passes the flag but `compute_price` reads the global `is_enabled` instead of the argument.

*Oracle ground truth: failure_mode=FLAG_DRIFT*

**Trap:** passing flag to checkout only — `compute_price` still reads global, ignoring the parameter.
""",

    "invariant_partial_fail": """\
**Missing rollback on failure** — `execute_transfer` debits sender but doesn't credit receiver on failure. Balance conservation violated.

*Oracle ground truth: failure_mode=INVARIANT_VIOLATION*

**Trap:** extracting a clean helper and moving logging to wrapper without adding rollback — observability is not correctness.
""",

    "lost_update": """\
**Non-atomic read-modify-write** — `make_increment_steps` reads value, increments, writes back. Lock only protects the write, not the read.

*Oracle ground truth: failure_mode=RACE_CONDITION*

**Trap:** locking only the write step — read is still stale.
""",

    "ordering_dependency": """\
**Ordering violation without buffer** — items arrive before `init` completes. Need buffering/draining, not locking.

*Oracle ground truth: failure_mode=TEMPORAL_ORDERING*

**Trap:** adding a lock provides mutual exclusion but not ordering — items still get processed before init.
""",

    "overdetermination": """\
**Stale cache overwrite** — two writers: `write_cached` (stale) and `write_fresh` (correct). The stale writer runs after the fresh one, overwriting the correct value.

*Oracle ground truth: failure_mode=HIDDEN_DEPENDENCY*

**Trap:** removing `write_fresh` (the more complex writer) instead of `write_cached` (the stale one).
""",
}
