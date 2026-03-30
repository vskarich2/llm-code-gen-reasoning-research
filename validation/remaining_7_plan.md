# Plan: Remaining 7 Zero-Variant Cases

Each case below includes: the exact bug, the exact mutation needed, and the AST construct to target.

---

## 1. mutable_default_c (3 files, decorator pattern)

**The bug:** `with_history` decorator creates a shared `history` list at decoration time. Each decorated function (`schedule_one`, `schedule_batch`) gets its own independent history — BUT if the decorator itself used a mutable default or shared state, history would leak.

**The fix:** The reference fix already uses a closure-local `history = []` per decorated function. The buggy version presumably shares history across decorated functions.

**Mutation strategy:** The reference fix is in `scheduler.py`, not `queue.py` (which is what `reference_fix.file` says — metadata bug). The mutation must operate on `scheduler.py`.

**AST transform needed:**
- Find the `with_history` decorator function
- Move `history = []` from inside the closure to module level (shared across all decorated functions)
- OR: Replace `history = []` with `history = _SHARED_HISTORY` and add module-level `_SHARED_HISTORY = []`

**New operator:** `HoistVariableToModuleLevel` — move a local variable assignment to module scope, making it shared.

---

## 2. missing_branch_b (2 files, dict dispatch table)

**The bug:** `_ROLE_DISPATCH` dict in `auth.py` is missing `"guest": guest_access`. Fix adds it.

**The diff is one line:** `+ "guest": guest_access,`

**Mutation strategy:** Remove the `"guest"` key from the dispatch dict in the reference fix.

**AST transform needed:**
- Find dict literal assigned to `_ROLE_DISPATCH`
- Remove the `"guest"` entry

**Why current operator fails:** The `RemoveDictEntryOperator` looks for keys in `self.keys_to_try` which includes `"moderator"`, `"service_account"`, etc. but NOT `"guest"`. Simple fix: add `"guest"` to the keys list.

**Fix:** Add `"guest"` to `RemoveDictEntryOperator.keys_to_try`.

---

## 3. wrong_condition_b (2 files, multi-function condition)

**The bug:** In `policy.py`, the condition logic is split across `check_rate()` and `check_quota()`. The fix changes `<` to `<=` or vice versa in one of these functions. But the current `FlipComparison` operator targets `>=` → `>` and `<=` → `<`.

**The actual code uses `<` (strict less-than):**
```python
def check_rate(requests_per_minute, rate_limit):
    return requests_per_minute < rate_limit
```

**Mutation strategy:** Flip `<` to `<=` (the inverse direction — allow one extra request past the limit).

**AST transform needed:**
- Find `ast.Lt` comparisons and flip to `ast.LtE`
- OR find `ast.Lt` and flip to `ast.Gt` (completely wrong direction)

**New operator extension:** Extend `FlipComparison` to also handle `Lt → LtE` and `Gt → GtE`.

---

## 4. wrong_condition_c (3 files, operator precedence)

**The bug:** `return not expired and under_limit or exempt` — due to Python operator precedence, this is parsed as `((not expired) and under_limit) or exempt`, not the intended `(not expired) and (under_limit or exempt)`.

**The fix adds explicit parentheses:**
```python
return not expired and (under_limit or exempt)
```

**Mutation strategy:** Remove the parentheses around `(under_limit or exempt)` — revert to the buggy precedence.

**AST transform needed:**
- Find `BoolOp(And, [UnaryOp(Not, expired), BoolOp(Or, [under_limit, exempt])])`
- Flatten it to `BoolOp(Or, [BoolOp(And, [UnaryOp(Not, expired), under_limit]), exempt])`

**New operator:** `FlattenBoolOpPrecedence` — remove explicit grouping in boolean expressions.

---

## 5. silent_default_b (2 files, wrong string literal)

**The bug:** `get_flag("features.analytics.enabled")` — plural "features" instead of singular "feature". The config dict uses "feature" so the lookup silently returns the default.

**The fix:** Change `"features.analytics.enabled"` to `"feature.analytics.enabled"`.

**Mutation strategy:** Change the string constant back to the buggy version.

**AST transform needed:**
- Find `ast.Constant(value="feature.analytics.enabled")` in the reference fix
- Change it to `"features.analytics.enabled"`

**New operator:** `CorruptStringLiteral` — change a specific string constant to a plausible-but-wrong variant. For this family: add/remove a letter to create a key mismatch.

---

## 6. silent_default_c (3 files, wrong env var key)

**The bug:** `_ENV_KEY_MAP` has `"dark_mode": "FEATURE_DARKMODE"` — missing underscore. Should be `"FEATURE_DARK_MODE"`.

**The fix:** Change `"FEATURE_DARKMODE"` to `"FEATURE_DARK_MODE"`.

**Mutation strategy:** Change the string constant back to the buggy version.

**AST transform:** Same as silent_default_b — `CorruptStringLiteral` targeting the env key map.

---

## 7. invariant_partial_fail (4 files, try/except rollback)

**The bug:** `execute_transfer` debits the sender, then attempts to credit the receiver. If the credit fails (random 30% chance), the sender's balance is reduced but the receiver's isn't increased — conservation violated.

**The fix:** Wrap the credit in try/except and restore sender.balance on failure:
```python
try:
    # credit receiver
except RuntimeError:
    sender.balance += amount  # rollback
    raise
```

**Mutation strategy:** Remove the try/except block — let the debit happen without rollback protection.

**AST transform needed:**
- Find `ast.Try` block in `execute_transfer`
- Replace it with just the try-body statements (unwrap the try/except)

**New operator:** `UnwrapTryExcept` — remove try/except, keeping only the try body. This removes the rollback protection.

---

## Implementation Priority

| Case | Difficulty | New operator needed |
|------|-----------|-------------------|
| missing_branch_b | Easy | Just add `"guest"` to existing keys list |
| silent_default_b | Easy | `CorruptStringLiteral` (change one string) |
| silent_default_c | Easy | Same operator, different target |
| wrong_condition_b | Easy | Extend `FlipComparison` with `Lt→LtE` |
| invariant_partial_fail | Medium | `UnwrapTryExcept` |
| wrong_condition_c | Medium | `FlattenBoolOpPrecedence` |
| mutable_default_c | Hard | `HoistVariableToModuleLevel` (multi-edit plan) |

**Expected outcome:** 6/7 cases should be reachable with targeted operators. `mutable_default_c` is genuinely hard (decorator semantics) and may remain as the single holdout.
