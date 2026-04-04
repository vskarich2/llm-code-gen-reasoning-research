# Type F Probe Candidates: Near-Miss Adversarial Probes for Classifier

Generated: 2026-03-31

## Overview

These 18 candidates are real failed model outputs where pass=False but mechanism_correct=True
(LEG cases) with reconstruction_status=SUCCESS and execution_category=INVARIANT_FAILURE.
They represent the most important class of probes: in-distribution examples where reasoning
is partially correct or subtly wrong, but the classifier scored mechanism_identified=CORRECT.

**Source files:** merged_events.jsonl from v2_targeted_50trial_canonical and v2_anthropic_50trial_v2
**Total pool:** 1537 qualifying candidates across 5 target cases
**Selection criteria:** Diversity across case_id (5), model (5), condition (2), and failure pattern

---

## CACHE_INVALIDATION_ORDER (3 probes)

### Actual bug
The task tells the model: "The update_record function does an invalidate then a set, which
seems redundant. Remove the unnecessary cache invalidation step." But the invalidate-then-set
ordering is INTENTIONAL for version tracking. Removing the 'redundant' invalidation breaks
cache_conditional_set which depends on version state being reset by invalidation.

The REAL fix: the invalidation is NOT redundant. The correct answer is to recognize that
removing it would break safe_update's version-tracking semantics.

---

### PROBE F-01: cache_invalidation_order | gpt-4.1-nano | baseline_v2 | trial=14

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4_1-nano__baseline_v2__trial_014__cache_invalidation_order/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The update_record function performs a cache_invalidate followed by
cache_set, which is redundant because cache_set overwrites the cache entry directly, making
the invalidation step unnecessary."

**Fix strategy (model):** "Remove the cache_invalidate call from update_record, leaving only
the cache_set operation to update the cache directly."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY

**Classifier judgment:** "The produced code precisely implements the stated fix (the
invalidation line was removed from update_record and replaced by a direct cache_set). However,
the reasoning ignored a hidden dependency (version tracking used by safe_update/
cache_conditional_set)."

**MY ASSESSMENT: PARTIALLY CORRECT (leans WRONG)**
The model correctly identifies that invalidate-then-set exists in update_record and that
cache_set overwrites. But the model FAILS to recognize that the invalidation resets version
state needed by cache_conditional_set. The model took the task description at face value
("seems redundant") without questioning the premise. The mechanism identification of
"redundancy" is superficially correct but misses the deeper causal chain. This is a TEXTBOOK
near-miss: the model identifies the right functions but misdiagnoses why they interact.

**PROBE VALUE: HIGH** - Tests whether classifier can distinguish "identified the right code
location" from "understood the actual mechanism."

---

### PROBE F-02: cache_invalidation_order | gpt-4o-mini | baseline_v2 | trial=2

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4o-mini__baseline_v2__trial_002__cache_invalidation_order/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The update_record function writes to the database but also calls
cache_invalidate, which is unnecessary since the cache is not being updated directly after
the write."

**Fix strategy (model):** "Remove the cache_invalidate call from the update_record function."

**Classifier verdict:** CORRECT;WRONG;WRONG;CORRECT;HIDDEN_DEPENDENCY

**Classifier judgment:** "The submitted code does implement the developer's explicit change
(it removed cache_invalidate from update_record), so the reasoning and code align on that
edit. However the extracted commitment (to remove invalidation) violates canonical
cache-consistency obligations."

**MY ASSESSMENT: WRONG**
The model fails even more clearly than Probe F-01. It claims cache_invalidate is "unnecessary"
but the invalidation is CRITICAL for version tracking. The root cause diagnosis is factually
incorrect -- the cache IS being updated (via cache_set in the original), and the invalidation
serves a version-reset purpose. Notably the classifier DID catch this partially (commitments
WRONG, satisfaction WRONG).

**PROBE VALUE: MEDIUM** - The classifier already partially caught this one (WRONG on two
dims), but mechanism_identified was still CORRECT, which is the key question.

---

### PROBE F-03: cache_invalidation_order | gpt-5.4-mini | leg_reduction_lean_v2 | trial=26

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5_4-mini__leg_reduction_lean_v2__trial_026__cache_invalidation_order/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The bug is in service.update_record, which only calls db_write and
never synchronizes the cache state; the unnecessary invalidate-then-set pattern is not present
in this code path."

**Fix strategy (model):** "No code change is needed in the current files because update_record
already omits cache invalidation."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;INVARIANT_VIOLATION

**Classifier judgment:** "The code matches the developer's stated reasoning exactly:
update_record does not touch the cache and only writes to the DB. However, that choice violates
the necessary invariant (reads returning the latest value)."

**MY ASSESSMENT: WRONG**
This is the most egregious case. The model claims "no code change is needed" when the actual
bug is that update_record SHOULD have cache synchronization. The model essentially says the
buggy code is already correct. Yet the classifier gave ALL FOUR dimensions CORRECT. This is
a critical classifier failure that a probe must test.

**PROBE VALUE: VERY HIGH** - Classifier gave 4/4 CORRECT to reasoning that says "no fix
needed" for a known bug. This is the strongest adversarial probe in the set.

---

## CONFIG_SHADOWING (4 probes)

### Actual bug
run_background_job() calls get_defaults() which returns timeout=5 (the base default).
handle_request() calls get_config() which merges with _OVERRIDES to get timeout=30. The task
says: "Fix the configuration." The correct fix: change run_background_job to use get_config()
so it gets the overridden timeout=30. HOWEVER, many test harnesses also check that
DEFAULTS["timeout"] is 30 (not just that run_background_job returns 30), so the config_shadowing
test may require BOTH fixes.

---

### PROBE F-04: config_shadowing | gpt-4.1-nano | baseline_v2 | trial=4

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4_1-nano__baseline_v2__trial_004__config_shadowing/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The run_background_job() function retrieves the timeout value from
get_defaults(), which returns DEFAULTS with timeout=5, not the overridden value of 30."

**Fix strategy (model):** "Modify run_background_job() to call get_config() instead of
get_defaults()."

**Classifier verdict:** CORRECT;CORRECT;WRONG;WRONG;PARTIAL_STATE_UPDATE

**Classifier judgment:** "The developer correctly identified the mechanism and made a precise
commitment to change run_background_job to call get_config(), but the produced code did not
implement that change; run_background_job still calls get_defaults()."

**MY ASSESSMENT: PARTIALLY CORRECT**
The root cause identification IS correct -- run_background_job does call get_defaults() when
it should call get_config(). But the model failed to implement its own fix (code still has
get_defaults). This is a reasoning-to-code gap, not a mechanism-identification error. The
classifier correctly caught the implementation failure (WRONG on commitments_satisfied and
reasoning_code_alignment).

**PROBE VALUE: HIGH** - Tests a scenario where mechanism identification is genuinely correct
but code implementation fails. The classifier should give mechanism_identified=CORRECT, and it
does. Tests whether probe framework handles this correctly.

---

### PROBE F-05: config_shadowing | gpt-4o-mini | baseline_v2 | trial=1

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4o-mini__baseline_v2__trial_001__config_shadowing/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The function run_background_job uses get_defaults() to retrieve the
timeout value, which returns the default timeout of 5 instead of the overridden value of 30."

**Fix strategy (model):** "Change the run_background_job function to use get_config() instead
of get_defaults()."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;CORRECT;PARTIAL_STATE_UPDATE

**Classifier judgment:** "The developer's explicit commitment is implemented (run_background_job
uses get_config()). However, the fix is partial: the module still contains DEFAULTS with
timeout=5 and shadowed local get_config/get_defaults definitions."

**MY ASSESSMENT: CORRECT (but incomplete fix)**
The mechanism identification is genuinely correct: the model correctly identifies that
run_background_job uses the wrong config source. The code DOES implement the fix (switching
to get_config). But the test still fails because the test also checks other invariants
(DEFAULTS value, structural residue). This is a case where mechanism was correct but the fix
was too narrow.

**PROBE VALUE: MEDIUM** - Less interesting for adversarial testing because the mechanism
really is correct. But useful as a "true positive" calibration probe.

---

### PROBE F-06: config_shadowing | gpt-5-mini | baseline_v2 | trial=1

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5-mini__baseline_v2__trial_001__config_shadowing/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "service.run_background_job calls get_defaults() which returns the
base DEFAULTS dict with timeout 5. The environment overrides are never used by
run_background_job."

**Fix strategy (model):** "Replace the call to get_defaults() inside run_background_job with
get_config(). Remove the unused import of get_defaults."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;PARTIAL;PARTIAL_STATE_UPDATE

**Classifier judgment:** "The code implements the key behavioral fix (run_background_job now
calls get_config()). However, the file still contains the old DEFAULTS/get_defaults/local
get_config definitions."

**MY ASSESSMENT: CORRECT (incomplete cleanup)**
Same pattern as F-05. Mechanism is genuinely correct. Code implements the core fix but leaves
structural artifacts. Tests fail due to import shadowing or DEFAULTS residue.

**PROBE VALUE: LOW** - Similar to F-05, useful mainly as calibration.

---

### PROBE F-07: config_shadowing | gpt-5.4-mini | leg_reduction_v2 | trial=11

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5_4-mini__leg_reduction_v2__trial_011__config_shadowing/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "run_background_job calls get_defaults(), which returns DEFAULTS with
timeout=5. get_config() applies the override to get timeout=30."

**Fix strategy (model):** "Change defaults.py so default timeout=30, AND change service.py so
run_background_job uses get_config()."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;PARTIAL_STATE_UPDATE

**Classifier judgment:** "The code matches the stated fix strategy: DEFAULTS timeout is
updated to 30 and run_background_job now uses get_config(). No contradiction between reasoning
and code."

**MY ASSESSMENT: CORRECT (but overkill fix that still fails tests)**
This model found a NOVEL approach: change BOTH the default AND the config path. The mechanism
identification is correct. The fix is structurally correct but still fails tests -- likely
because the test checks specific call patterns or the structural changes broke imports.

**PROBE VALUE: MEDIUM** - Interesting as a "correct mechanism, creative fix, still fails" case.

---

## HIDDEN_DEP_MULTIHOP (4 probes)

### Actual bug
Two cache write functions: refresh_user_snapshot (uses cache_put_if_absent -- only writes if
key absent) and sync_user_to_cache (uses cache_put -- always overwrites). The task asks to
consolidate them. The TRAP: save_user() calls refresh_user_snapshot, but it NEEDS cache_put
(overwrite) semantics to ensure writes are visible. If you consolidate to use
cache_put_if_absent, save_user stops updating the cache on rename operations.

---

### PROBE F-08: hidden_dep_multihop | gpt-4.1-nano | baseline_v2 | trial=12

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4_1-nano__baseline_v2__trial_012__hidden_dep_multihop/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "Both sync_user_to_cache and refresh_user_snapshot perform similar
cache update operations. refresh_user_snapshot uses cache_put_if_absent, while
sync_user_to_cache uses cache_put, causing different behaviors."

**Fix strategy (model):** "Consolidate into a single function update_user_cache with a
parameter to determine overwrite behavior. Update all callers."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;WRONG;HIDDEN_DEPENDENCY

**Classifier judgment:** "Code partially follows the stated fix but fails to fully implement:
some callers not replaced, old imports remain, references undefined cache_writer."

**MY ASSESSMENT: PARTIALLY CORRECT**
The model correctly identifies the SYMPTOM (two functions with different semantics) but does
not identify the HIDDEN DEPENDENCY: save_user NEEDS overwrite semantics. The consolidation
approach is on the right track but the implementation is broken (undefined references).
Critically, the model does give save_user overwrite=True which would be correct IF the code
actually worked.

**PROBE VALUE: HIGH** - The model's reasoning hovers right at the boundary. It sees the
semantic difference but doesn't articulate WHY overwrite matters for save_user specifically.

---

### PROBE F-09: hidden_dep_multihop | gpt-4o-mini | leg_reduction_lean_v2 | trial=2

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4o-mini__leg_reduction_lean_v2__trial_002__hidden_dep_multihop/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The functions both handle caching user data but in slightly different
ways, leading to redundancy and potential inconsistencies."

**Fix strategy (model):** "Consolidate into sync_user_cache with an overwrite parameter.
Update all calls."

**Classifier verdict:** CORRECT;CORRECT;WRONG;CORRECT;HIDDEN_DEPENDENCY

**Classifier judgment:** "Code consolidates correctly and updates callers. However save_user
uses overwrite=False, leaving a hidden dependency that causes stale reads."

**MY ASSESSMENT: PARTIALLY CORRECT (leans WRONG)**
The model identifies the two functions have different semantics but FAILS to recognize which
semantic save_user needs. It gives save_user overwrite=False (put_if_absent) when save_user
NEEDS overwrite=True (cache_put). This is the EXACT trap the case is designed to test. The
classifier caught commitments_satisfied=WRONG but mechanism_identified=CORRECT.

**PROBE VALUE: VERY HIGH** - This is a perfect near-miss. The model sees the consolidation
opportunity, implements a clean parameterized function, but gets the critical flag BACKWARDS
for save_user. Tests whether the classifier recognizes that "correct structure, wrong
parameter" means the mechanism understanding was incomplete.

---

### PROBE F-10: hidden_dep_multihop | gpt-5-mini | baseline_v2 | trial=4

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5-mini__baseline_v2__trial_004__hidden_dep_multihop/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "Two separate functions with overlapping responsibilities. refresh_user_snapshot
used cache_put_if_absent, sync_user_to_cache used cache_put. Callers used the wrong helper."

**Fix strategy (model):** "Remove refresh_user_snapshot, consolidate into sync_user_to_cache(user,
only_if_absent=False). Replace all refresh_user_snapshot calls with sync_user_to_cache(user,
only_if_absent=True)."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY

**Classifier judgment:** "Code faithfully implements the stated fix: two helpers consolidated,
all former refresh_user_snapshot call sites replaced. However, developer reasoning missed a
hidden dependency (save_user must unconditionally overwrite the cache)."

**MY ASSESSMENT: PARTIALLY CORRECT (subtle WRONG)**
The model explicitly says "callers used the wrong helper" which is on the right track. But
then it consolidates and gives save_user only_if_absent=True, which PRESERVES the bug. The
model's reasoning identified the right problem (wrong helper usage) but then chose the wrong
default (keep the put_if_absent behavior for save_user). Classifier gave ALL FOUR CORRECT.

**PROBE VALUE: VERY HIGH** - All four classifier dimensions CORRECT, but the model's fix
preserves the exact bug it claims to fix. This tests whether the classifier can distinguish
"structurally clean consolidation" from "semantically correct fix."

---

### PROBE F-11: hidden_dep_multihop | gpt-5.4-mini | baseline_v2 | trial=1

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5_4-mini__baseline_v2__trial_001__hidden_dep_multihop/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "Two overlapping helpers that write the same cache key with different
semantics. Callers only use refresh_user_snapshot, leaving sync_user_to_cache as a duplicate."

**Fix strategy (model):** "Consolidate into sync_user_to_cache(user) using
cache_put_if_absent. Remove refresh_user_snapshot. Update all callers."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY

**Classifier judgment:** "Code precisely implements the stated fix. However, that reasoning
mandated cache_put_if_absent, which preserves existing cache entry and fails the hidden-
dependency invariant."

**MY ASSESSMENT: WRONG**
The model explicitly chooses cache_put_if_absent as the consolidated behavior, which is the
WRONG choice. save_user needs cache_put (overwrite). The model's reasoning frames it as
"callers only use refresh_user_snapshot" which is true but misses that save_user SHOULD be
using sync_user_to_cache (overwrite). The classifier gave 4/4 CORRECT.

**PROBE VALUE: VERY HIGH** - 4/4 CORRECT from classifier for reasoning that cements the
exact bug in place by choosing the wrong consolidation target.

---

## INVARIANT_PARTIAL_FAIL (4 probes)

### Actual bug
execute_transfer debits sender (sender.balance -= amount) THEN may fail before crediting
receiver (receiver.balance += amount). No rollback on failure, so money is "lost." The task
asks to "extract core transfer into a helper and move observability to a wrapper" but the
REAL bug is the missing rollback, not the logging placement.

---

### PROBE F-12: invariant_partial_fail | gpt-4.1-nano | baseline_v2 | trial=3

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4_1-nano__baseline_v2__trial_003__invariant_partial_fail/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "execute_transfer mixes business logic with logging and observability
calls, causing tight coupling."

**Fix strategy (model):** "Extract core transfer logic into perform_transfer (balance updates
and ledger without emit calls). Wrapper handles all logging/emit calls."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;PARTIAL;INVARIANT_VIOLATION

**Classifier judgment:** "Commitments partially implemented. Critically, no rollback or
compensation restores sender.balance on exception."

**MY ASSESSMENT: WRONG (surface-level correct, misses actual bug)**
The model identifies the SURFACE issue (logging mixed with logic) but completely misses the
ACTUAL bug (no rollback on partial failure). The task is DESIGNED to misdirect models into
refactoring logging when the real problem is atomicity. The mechanism of "logging coupling" is
a red herring; the invariant violation (sender.balance + receiver.balance must be conserved)
is the real mechanism.

**PROBE VALUE: HIGH** - Tests whether the classifier recognizes that "correct about the
surface structure" does not equal "identified the actual failure mechanism."

---

### PROBE F-13: invariant_partial_fail | gpt-4o-mini | baseline_v2 | trial=2

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4o-mini__baseline_v2__trial_002__invariant_partial_fail/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "Too many logging calls mixed with business logic, specifically
record_transfer_attempt, emit_failure_alert, and emit_transfer_event."

**Fix strategy (model):** "Extract core_transfer and move all observability into
execute_transfer_with_logging."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;PARTIAL;LOGGING_INCONSISTENCY

**Classifier judgment:** "Implementation left emit_failure_alert inside core_transfer. Code
only partially satisfies fix strategy."

**MY ASSESSMENT: WRONG**
Same pattern as F-12. Model addresses the logging/observability concern but misses the
fundamental atomicity problem. Even if ALL logging were perfectly separated, the code would
still fail because sender.balance -= amount executes before the possible failure, with no
rollback.

**PROBE VALUE: HIGH** - Same pattern as F-12. Validates consistent probe behavior.

---

### PROBE F-14: invariant_partial_fail | gpt-5-mini | baseline_v2 | trial=1

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5-mini__baseline_v2__trial_001__invariant_partial_fail/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "execute_transfer mixes business logic with observability.
Ledger/audit calls interleaved with balance mutations means an exception mid-transfer leaves
balances and recorded entries out of sync."

**Fix strategy (model):** "Extract _apply_transfer for pure balance changes. Move all
ledger/audit to wrapper. Use snapshots to record what actually happened."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;INVARIANT_VIOLATION

**Classifier judgment:** "Code faithfully implements the stated refactor. However, the code
still allows transient failure to leave balances inconsistent because there is no rollback."

**MY ASSESSMENT: PARTIALLY CORRECT (the best of the invariant_partial_fail set)**
This model comes CLOSEST to understanding the real bug. It mentions "exception mid-transfer
leaves balances out of sync" which IS the actual mechanism. But the fix strategy still focuses
on logging separation rather than rollback. The model sees the symptom (inconsistent state
after failure) but prescribes the wrong treatment (separate observability rather than add
rollback). Classifier gave ALL FOUR CORRECT.

**PROBE VALUE: VERY HIGH** - This is the most subtle probe. The model's root cause MENTIONS
the real issue (out-of-sync balances) but the fix addresses a different problem (logging
separation). Tests whether classifier distinguishes "mentioned the real problem in diagnosis"
from "actually fixed the real problem."

---

### PROBE F-15: invariant_partial_fail | gpt-5.4-mini | baseline_v2 | trial=1

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5_4-mini__baseline_v2__trial_001__invariant_partial_fail/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "execute_transfer mixes transfer state changes with observability
side effects. The core transfer flow is hard to isolate and reuse."

**Fix strategy (model):** "Extract balance mutation into helper. Wrapper records attempt,
calls helper, records debit/credit after each balance change, emits events."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;PARTIAL;INVARIANT_VIOLATION

**Classifier judgment:** "High-level strategy followed but violates specific commitment to
record ledger entries 'after each corresponding balance change.' Conservation invariant at
risk."

**MY ASSESSMENT: PARTIALLY CORRECT**
This model's fix strategy is more sophisticated -- it promises to record ledger entries "after
each corresponding balance change" which WOULD help if implemented correctly. But the code
puts both debit and credit recording AFTER _transfer_core returns (not interleaved with
mutations), which means on failure, neither is recorded correctly.

**PROBE VALUE: HIGH** - Tests the gap between a sophisticated fix strategy and its
implementation.

---

## LOST_UPDATE (3 probes)

### Actual bug
make_increment_steps() creates closures with a shared `captured` dict. Under interleaving,
both read 0 then both write 1, losing one update. The fix requires making the read-modify-write
ATOMIC (either read at write time, or use compare-and-swap, or serialize access). Simply
making `captured` per-call does NOT fix it because both step_reads can still observe the same
_value before either step_write runs.

---

### PROBE F-16: lost_update | claude-sonnet-4 | leg_reduction_lean_v2 | trial=19

**Worker:** `logs/v2_anthropic_50trial_v2/workers/claude-sonnet-4-20250514__leg_reduction_lean_v2__trial_019__lost_update/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "make_increment_steps creates closures that share the same captured
dictionary, causing both operations to overwrite each other's read values when interleaved."

**Fix strategy (model):** "Create a new captured dictionary for each call to
make_increment_steps by moving dictionary creation inside the function."

**Classifier verdict:** CORRECT;CORRECT;CORRECT;CORRECT;ALIASING

**Classifier judgment:** "Code faithfully implements the developer's stated fix. However, that
fix does not address the underlying non-atomic read-modify-write."

**MY ASSESSMENT: WRONG**
The model's diagnosis is factually incorrect. The `captured` dict was ALREADY per-call in the
original code (created inside make_increment_steps). The original code comments even say
`captured = {}` is inside the function. The model claims "shared dictionary" but each call
already gets its own dict. The real problem is that both step_reads observe the same _value
(global state), not that they share a captured dict. The generated code is IDENTICAL to the
original buggy code.

**PROBE VALUE: VERY HIGH** - Classifier gave 4/4 CORRECT for a "fix" that is literally
identical to the buggy original. The model misidentified the sharing granularity (thought
captured was shared when it wasn't). This is a pure false positive.

---

### PROBE F-17: lost_update | gpt-4o-mini | baseline_v2 | trial=7

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-4o-mini__baseline_v2__trial_007__lost_update/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The captured dictionary is used to store the current value. When two
increments interleave, both read the same value before either writes back."

**Fix strategy (model):** "Modify step_write to take the value directly from step_read's
return value instead of using the shared captured dictionary."

**Classifier verdict:** CORRECT;CORRECT;PARTIAL;PARTIAL;TEMPORAL_ORDERING

**Classifier judgment:** "Code partially implements the API change (step_write takes parameter)
but the calling site computes read_a()/read_b() eagerly outside run_steps, so the race
remains."

**MY ASSESSMENT: PARTIALLY CORRECT**
The model correctly identifies the read-modify-write race. The fix approach (pass value from
read to write) is conceptually sound but the implementation is broken: step_write now takes a
parameter, but interleaved_double_increment calls read_a() and read_b() EAGERLY during tuple
construction, so both reads still execute before either write. Also, the generated code
includes markdown fences (```python) which would cause parse errors.

**PROBE VALUE: HIGH** - Interesting case: correct diagnosis, creative fix idea, broken
implementation. Tests whether classifier can catch the subtle eager-evaluation problem.

---

### PROBE F-18: lost_update | gpt-5.4-mini | baseline_v2 | trial=8

**Worker:** `logs/v2_targeted_50trial_canonical/workers/gpt-5_4-mini__baseline_v2__trial_008__lost_update/attempt_001`
**Classifier model:** gpt-5-mini

**Root cause (model):** "The lost update comes from using a shared module-level _value with a
split read-modify-write sequence. Both step_reads can read the same _value before either
step_write runs."

**Fix strategy (model):** "Change the increment to be performed atomically instead of as
separate read and write steps. Replace the split closure with a single step that does
get() and _set(get()+1) in one operation."

**Classifier verdict:** CORRECT;CORRECT;WRONG;WRONG;TEMPORAL_ORDERING

**Classifier judgment:** "Developer correctly diagnosed root cause and committed to atomic
increment. Produced code still uses split captured dict and separate read/write steps.
Implementation does not follow stated fix."

**MY ASSESSMENT: CORRECT diagnosis, FAILED implementation**
This model has the BEST diagnosis of all 18 probes. It correctly identifies the non-atomic
read-modify-write on shared global state and proposes the right fix (atomic increment). But
the generated code is UNCHANGED from the original. This is pure reasoning-to-code gap.

**PROBE VALUE: HIGH** - Tests a clean case where mechanism identification is genuinely correct
but code implementation fails completely. The classifier correctly caught this (WRONG on
commitments_satisfied and alignment).

---

## Summary: Probe Quality Rankings

### VERY HIGH value (best adversarial probes):

| Probe | Case | Model | Why |
|-------|------|-------|-----|
| F-03 | cache_invalidation_order | gpt-5.4-mini | Says "no fix needed" for known bug, 4/4 CORRECT from classifier |
| F-09 | hidden_dep_multihop | gpt-4o-mini | Perfect consolidation, but save_user gets overwrite=False (the bug) |
| F-10 | hidden_dep_multihop | gpt-5-mini | All 4/4 CORRECT but preserves exact bug with only_if_absent=True |
| F-11 | hidden_dep_multihop | gpt-5.4-mini | 4/4 CORRECT, chooses cache_put_if_absent as consolidation target (wrong) |
| F-14 | invariant_partial_fail | gpt-5-mini | Mentions real issue (inconsistent state), but fixes logging instead. 4/4 CORRECT |
| F-16 | lost_update | claude-sonnet-4 | "Fix" is identical to original buggy code. 4/4 CORRECT |

### HIGH value:

| Probe | Case | Model | Why |
|-------|------|-------|-----|
| F-01 | cache_invalidation_order | gpt-4.1-nano | Identifies right location, misses version tracking |
| F-04 | config_shadowing | gpt-4.1-nano | Correct diagnosis, code doesn't implement fix |
| F-08 | hidden_dep_multihop | gpt-4.1-nano | Right approach, broken implementation (undefined refs) |
| F-12 | invariant_partial_fail | gpt-4.1-nano | Surface issue identified, real bug (no rollback) missed |
| F-13 | invariant_partial_fail | gpt-4o-mini | Same pattern as F-12 |
| F-15 | invariant_partial_fail | gpt-5.4-mini | Sophisticated strategy, poor implementation |
| F-17 | lost_update | gpt-4o-mini | Correct diagnosis, creative fix, eager-eval breaks it |
| F-18 | lost_update | gpt-5.4-mini | Best diagnosis, zero implementation |

### MEDIUM value (calibration probes):

| Probe | Case | Model | Why |
|-------|------|-------|-----|
| F-02 | cache_invalidation_order | gpt-4o-mini | Classifier already caught it partially |
| F-05 | config_shadowing | gpt-4o-mini | Mechanism genuinely correct, test too strict |
| F-07 | config_shadowing | gpt-5.4-mini | Creative approach, still fails tests |

### LOW value:

| Probe | Case | Model | Why |
|-------|------|-------|-----|
| F-06 | config_shadowing | gpt-5-mini | Correct mechanism, structural residue |

---

## Cross-cutting Observations

1. **Classifier systematically over-credits mechanism identification.** In 6 of 18 cases,
   the classifier gave ALL FOUR dimensions CORRECT despite the mechanism being partially or
   fully wrong. The classifier is biased toward CORRECT when reasoning "sounds right."

2. **The hardest probes exploit the task's misdirection.** Cases like invariant_partial_fail
   and cache_invalidation_order have tasks that LEAD models toward the wrong mechanism. Models
   that follow the task description verbatim get scored CORRECT on mechanism, but their fix
   doesn't address the real bug.

3. **Consolidation cases (hidden_dep_multihop) produce the most subtle near-misses.** Models
   create structurally clean code but get the CRITICAL parameter wrong (overwrite=True vs
   False). This is the hardest for classifiers to catch because the code looks good.

4. **lost_update reveals a unique failure mode: unchanged code scored as "fix."** Probe F-16
   generates code IDENTICAL to the original and gets 4/4 CORRECT. This is the clearest
   classifier calibration failure.

5. **Model diversity matters.** claude-sonnet-4 on lost_update (F-16) shows a different
   failure mode than the GPT models. gpt-5-mini on invariant_partial_fail (F-14) shows the
   most sophisticated reasoning but still fails.
