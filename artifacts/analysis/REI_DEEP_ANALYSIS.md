# Deep Analysis: Reasoning-Execution Inconsistency (REI) in T3 Benchmark

**Date:** 2026-03-23
**Data source:** gpt-4o-mini 19-condition ablation (342 calls), with cross-model comparison from nano and 5-mini
**Log files:** `gpt-4o-mini_20260323_060546*.jsonl`

---

## 1. Scale of the Problem

Across gpt-4o-mini's 342 baseline+intervention calls:

- **151 instances** of reasoning-action gap (model identifies correct issue, code still fails)
- **44% gap rate** overall
- **4 cases show REI on ALL 19 conditions** (l3_state_pipeline, cache_invalidation_order, partial_rollback_multi, feature_flag_drift)

The model "knows the answer" almost half the time but can't translate that knowledge into working code. This is the central finding of the benchmark.

---

## 2. REI Cluster Taxonomy

After analyzing the actual model outputs, the 151 REI instances cluster into **5 distinct failure mechanisms**:

| Cluster | Cases | REI Rate | Mechanism |
|---|---|---|---|
| **A. Trap Compliance** | l3_state_pipeline, cache_invalidation_order, feature_flag_drift | 19/19 each | Model follows the task prompt's suggested "simplification" despite reasoning about why it's dangerous |
| **B. Incomplete Rollback** | invariant_partial_fail, partial_rollback_multi | 8-19/19 | Model describes the atomicity problem, extracts a helper, but doesn't add the compensating action |
| **C. Wrong Abstraction Level** | hidden_dep_multihop, shared_ref_coupling | 6-7/19 | Model correctly identifies the shared-state issue but the fix breaks at the multi-file concatenation level |
| **D. Lock Elision** | async_race_lock, lazy_init_hazard | 15-18/19 | Model mentions concurrency/ordering but removes the guard mechanism as "unnecessary complexity" |
| **E. Shallow Simplification** | easy_temporal | 11/19 | Model understands the ordering constraint but simplifies away the logging/ordering enforcement |

---

## 3. Cluster A: Trap Compliance (The Most Revealing Pattern)

### What's Happening

The task prompt *deliberately pushes the model toward the wrong fix*. The model's reasoning correctly identifies why the suggested change is dangerous, but then *does it anyway*.

This is the purest form of REI: the model has the correct causal model in its reasoning text but its code generation is dominated by instruction-following.

### Example: `l3_state_pipeline` (19/19 conditions show REI)

**Task prompt:** "process_batch and process_incremental have redundant steps. stage() and commit() both copy data into the state, and freeze_view() rebuilds the view that stage() already built. Simplify the pipeline by removing the unnecessary steps."

**The trap:** Removing `commit()` loses the `frozen=True` gate. Removing `freeze_view()` after commit means the view isn't rebuilt from stable data. The task prompt frames these as "redundant" but they serve distinct causal purposes.

**gpt-4o-mini baseline reasoning (verbatim):**
> "The functions `stage()` and `commit()` both copy data into the state, and `freeze_view()` rebuilds the view that `stage()` already built. To simplify the pipeline, we can remove the `freeze_view()` calls from both `process_batch` and `process_incremental`, as the view is already built during staging. This reduces redundancy and streamlines the code."

**What the model did:** Removed `freeze_view()` calls from both pipeline functions. The model's reasoning ECHOES the task prompt's framing ("rebuilds the view that stage() already built") rather than challenging it.

**Why it fails:** The invariant test calls `process_batch(entries)` and checks that `st["meta"]["frozen"]` is True and `st["stable"]` is populated. Without `freeze_view()` after `commit()`, the frozen flag may not be set correctly and the view doesn't reflect committed data.

**The REI mechanism:** The model's reasoning KNOWS stage and commit serve different purposes ("stage() and commit() both copy data into the state") but treats the task prompt's claim of redundancy as authoritative. It doesn't challenge the premise.

**Cross-model comparison:**

gpt-4.1-nano (baseline) produces nearly identical reasoning:
> "The functions process_batch and process_incremental both perform the same sequence of steps... freeze_view() after commit is redundant."

gpt-5-mini (baseline) goes further, explicitly understanding the structure but still complying:
> "I removed the redundant freeze_view reducer and eliminated calls to it from the pipeline... stage() still builds pending and view... commit() copies pending to stable and marks the state frozen."

All three models show the same pattern: correct structural understanding, compliance with the (misleading) task prompt.

### Example: `cache_invalidation_order` (19/19 conditions show REI)

**Task prompt:** "update_record does invalidate then set, which seems redundant. Simplify the cache logic by removing the invalidation step and just writing directly."

**The trap:** `safe_update` uses `cache_conditional_set` with version checking. The invalidate-then-set sequence in `update_record` is NOT redundant — invalidation resets the version counter, which `safe_update` depends on for conflict detection.

**gpt-4o-mini baseline reasoning (verbatim):**
> "The cache logic in the `update_record` function was simplified by removing the cache invalidation step. Instead of invalidating the cache and then setting the new value, we can directly set the new value in the cache after writing to the database. This reduces redundancy and improves performance."

**gpt-4o-mini code:**
```python
def update_record(key, value):
    ver = cache_get_version(key)
    db_write("records", key, value)
    cache_set(key, value, version=ver + 1)
```

**Why it fails:** The version increment `ver + 1` is the model's attempt to preserve versioning, but it's incorrect. The original code uses `cache_invalidate` which resets the version, then `cache_set` which sets version=1. The model's `ver + 1` doesn't match the expected version sequence that `safe_update`'s `cache_conditional_set` checks against.

**The REI mechanism:** The model KNOWS versioning matters (it adds `version=ver + 1`), but it doesn't understand the *protocol* — invalidate resets to 0, set starts at 1, and conditional_set checks this specific sequence. The reasoning shows awareness of the issue but the code implements a plausible-but-wrong version tracking scheme.

### Example: `feature_flag_drift` (19/19 conditions show REI)

**Task prompt:** "The enable/disable pattern in checkout is ugly. Simplify by passing the pricing flag as a parameter instead of mutating global state."

**The trap:** `compute_price` reads `is_enabled('new_pricing')` from global flags internally. Passing `use_new_pricing` as a parameter to checkout doesn't help unless `compute_price` is also changed to accept and use that parameter.

**gpt-4o-mini baseline reasoning (verbatim):**
> "The code has been refactored to remove the reliance on global state for the pricing feature flag. Instead of enabling or disabling the 'new_pricing' flag globally in the checkout function, the flag is now passed as a parameter to the relevant functions. This makes the code cleaner and avoids side effects from mutating global state."

**gpt-4o-mini code:**
```python
def compute_price(base, qty, use_new_pricing=False):
    if use_new_pricing:
        return _v2_price(base, qty)
    return _v1_price(base, qty)
```

**Why it fails:** The model correctly adds `use_new_pricing` to `compute_price`, but the **test** calls `checkout(items, use_new_pricing=True)` which must flow the flag down to `billing.create_invoice` → `compute_price`. The model's code often breaks the call chain — `checkout` passes the flag but `create_invoice` doesn't forward it, or the signature mismatch causes a TypeError.

**The REI mechanism:** The model has the RIGHT idea (parameterize instead of global mutation) but fails at the multi-file plumbing. The fix requires coordinated changes across 4 files (flags.py, pricing.py, billing.py, api.py), and the model typically fixes 2-3 of them correctly but misses one hop in the call chain.

---

## 4. Cluster B: Incomplete Rollback

### Example: `invariant_partial_fail` (8/19 conditions show REI under diagnostic+)

**Task prompt:** "The execute_transfer function has too many logging calls mixed with business logic. Simplify it by extracting the core transfer into a clean helper and moving all observability calls into a wrapper."

**The trap:** The debit-then-credit sequence has a failure window. If the model extracts the core transfer without adding rollback, money is lost on failure.

**gpt-4o-mini diagnostic reasoning (verbatim):**
> "The key correctness invariant being protected is the conservation of value, ensuring that the total amount of money remains unchanged during the transfer process. The failure window occurs between the debit operation on the sender's account and the credit operation on the receiver's account. If an exception occurs after debiting the sender but before crediting the receiver, the system would be left in an inconsistent state where the sender's balance is reduced, but the receiver's balance is not increased."

This is a **textbook-perfect** description of the bug. The model identifies:
1. The invariant (conservation of value)
2. The failure window (between debit and credit)
3. The consequence (inconsistent state)

**gpt-4o-mini code (critical section):**
```python
def core_transfer(sender, receiver, amount):
    sender.balance -= amount
    record_debit(sender.account_id, amount)
    if random.random() < 0.3:
        raise RuntimeError("transient failure during credit")
    receiver.balance += amount
```

**Why it fails:** Despite perfectly describing the failure window, the code STILL debits first, then potentially raises before crediting, with NO rollback of the debit. The model extracted the helper exactly as asked but didn't add the compensating `sender.balance += amount` in the except path.

**The REI mechanism:** The model's reasoning is about the PROBLEM. Its code is about the TASK (extract a helper). These are different goals. The task says "extract and simplify," the reasoning says "there's a failure window." The model satisfies the task without addressing the problem it just described.

**Cross-model comparison:**

gpt-4.1-nano (baseline):
> "I created a new helper function 'perform_transfer' that contains only the business logic of updating balances and recording ledger entries."

Same pattern — describes the risk, extracts the helper, no rollback.

gpt-5-mini (baseline):
> "I refactored execute_transfer by extracting the minimal business logic into two small helpers: _debit_sender and _credit_receiver... _credit_receiver may raise a transient RuntimeError to preserve the original failure behavior."

5-mini actually goes further — it PRESERVES the failure behavior intentionally. It knows the failure exists and keeps it, because the task asked for refactoring, not fixing.

---

## 5. Cluster C: Wrong Abstraction Level

### Example: `hidden_dep_multihop` (7/19 conditions show REI)

**gpt-4o-mini diagnostic reasoning (verbatim):**
> "The functions `refresh_user_snapshot` and `sync_user_to_cache` both interact with the cache by writing user data, but they differ in their behavior: `refresh_user_snapshot` writes only if the key is absent, while `sync_user_to_cache` always writes. To consolidate these functions, I will create a new function `update_user_cache` that takes an additional parameter to control whether to write unconditionally or conditionally."

The model CORRECTLY identifies the semantic difference (always-write vs write-if-absent). But the code often fails because:
1. The 4-file case concatenation produces import errors
2. The model's unified function defaults to the wrong behavior
3. Callers that need always-write get write-if-absent or vice versa

**The REI mechanism:** The model has the right abstraction (parameterized function), but the implementation fails at the integration level. The reasoning is about API design; the failure is about plumbing.

---

## 6. Cluster D: Lock Elision

### Example: `async_race_lock` (15/19 conditions show REI)

**gpt-4o-mini baseline reasoning (verbatim):**
> "The code has been simplified by replacing all instances of `process_item` with `quick_increment`, which directly increments the counter without locking overhead. This reduces complexity and improves performance by eliminating unnecessary locking mechanisms."

The model explicitly describes what it's removing (locking) and why (performance). But the invariant test runs `run_verified()` which depends on the lock to ensure counter accuracy under concurrent access.

**The REI mechanism:** The model treats the lock as "overhead" because the task prompt frames the refactoring as simplification. The reasoning acknowledges the lock exists but categorizes it as unnecessary complexity rather than a correctness mechanism.

---

## 7. Cross-Cutting Patterns

### Pattern 1: Task Prompt Dominance

In 57/151 REI cases (38%), the model's reasoning explicitly echoes the task prompt's framing. The task says "this is redundant, simplify it" and the model agrees in reasoning, even when the "redundant" code serves a critical purpose.

**This is not ignorance — it's compliance.** The model has enough understanding to identify the risk but not enough independence to override the instruction.

### Pattern 2: Reasoning ≠ Planning

In 44/151 REI cases (29%), the model's reasoning correctly diagnoses the PROBLEM but the code solves the TASK. These are different:
- Problem: "there's a failure window between debit and credit"
- Task: "extract business logic into a clean helper"

The model satisfies the task without addressing the problem. Its reasoning is about understanding; its code generation is about instruction-following.

### Pattern 3: Multi-File Plumbing Failure

In 38/151 REI cases (25%), the model's reasoning correctly identifies a cross-file dependency but the code fails to maintain it across file boundaries. This is especially common in 4-file cases (hidden_dep_multihop, feature_flag_drift) where the fix requires coordinated changes across the call chain.

### Pattern 4: Score-Reasoning Paradox

The diagnostic condition (reasoning scaffold) has the HIGHEST REI rate (10/14 cases = 71%). This is counterintuitive but explained by the mechanism: diagnostic prompts cause the model to articulate MORE correct reasoning, which increases the reasoning-action gap without improving the code.

More reasoning scaffolding → more articulated understanding → same broken code → larger measured gap.

---

## 8. Implications for the Retry Harness

The REI analysis directly predicts retry dynamics:

| REI Cluster | Expected Retry Behavior | Why |
|---|---|---|
| A. Trap Compliance | **Flat failure** — model will make the same mistake every retry | The task prompt is the dominant signal; test feedback can't override it |
| B. Incomplete Rollback | **Possible recovery** — test feedback explicitly names the missing rollback | The model already knows the fix; feedback provides the missing "permission" to deviate from the task |
| C. Wrong Abstraction | **Possible recovery with adaptive hints** — HIDDEN_DEPENDENCY hint directs attention to the plumbing | The model's design is right; it just needs to focus on integration |
| D. Lock Elision | **Flat failure** — model will keep removing the lock | Task prompt says "simplify," model will keep simplifying |
| E. Shallow Simplification | **Oscillating** — model may try different simplifications without finding the right one | Multiple plausible simplifications exist |

**Key prediction:** Cluster B (incomplete rollback) and Cluster C (wrong abstraction) are the best candidates for retry recovery. Cluster A and D are likely resistant because the task prompt itself is the adversary.

---

## 9. Quantitative Summary

| Metric | Value |
|---|---|
| Total REI instances (4o-mini, 19 conditions) | 151 / 342 (44%) |
| Cases with 100% REI rate (all conditions) | 4 (l3_state_pipeline, cache_invalidation, partial_rollback, feature_flag_drift) |
| Dominant cluster | A. Trap Compliance (57 instances, 38%) |
| Cluster most likely to benefit from retry | B. Incomplete Rollback |
| Condition with highest REI rate | diagnostic (10/14 = 71%) |
| Condition with lowest REI rate | baseline (8/14 = 57%) |

---

## 10. Key Takeaway

**REI is not a reasoning failure — it's a compliance failure.** The models have sophisticated causal understanding (they describe failure windows, identify semantic differences between similar functions, understand concurrency risks). But their code generation is dominated by the task instruction, which in many cases *asks them to introduce the bug*.

The benchmark's trap design is working as intended: it creates a conflict between "what the task asks for" and "what correctness requires." The REI rate measures how often the model resolves this conflict in favor of the task instruction over its own correct reasoning.

This has direct implications for intervention design:
- **Reasoning scaffolds (diagnostic, SCM) make REI worse** — they increase articulation without changing the compliance behavior
- **Test feedback (retry) may help** — it provides an external authority that conflicts with the task prompt
- **Adaptive hints may help** — they give the model "permission" to deviate from the task
- **The task prompt itself is the adversary** — any intervention that doesn't address the instruction-following dynamic will fail on Cluster A cases
