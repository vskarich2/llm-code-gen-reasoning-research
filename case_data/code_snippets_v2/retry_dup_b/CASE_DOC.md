# Case: retry_dup_b

**Family:** retry_dup
**Difficulty:** B (Medium)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Messages appearing twice in store. Fix the retry logic. Return the updated code.

## What the Code Does

A two-file message sending system with retry logic and a persistent store.

**store.py** provides `append(msg)` (adds to `_messages` list) and `notify(msg)` (adds to `_notifications` list). Both are non-idempotent -- each call adds one entry.

**sender.py:**
```python
def send(msg, fail_first=False):
    global _attempt_count
    _attempt_count += 1
    if fail_first and _attempt_count == 1:
        raise ConnectionError("transient failure")
    append(msg)
    notify(msg)
    return True

def send_with_retry(msg, max_retries=2, fail_first=False):
    last_error = None
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            # BUG: no break after success -- continues loop, duplicating
        except ConnectionError as e:
            last_error = e
            continue
    return True
```

The `send()` function appends to the store AND sends a notification on each call. `send_with_retry()` catches transient errors and retries, but has no `break` after success. When `fail_first=False`, `send()` always succeeds, so the loop runs all `max_retries` iterations, duplicating messages and notifications.

## The Bug

`send_with_retry()` lacks a `break` after a successful `send()`. The retry loop always runs to completion (`max_retries` iterations). Since each successful `send()` calls both `append()` and `notify()`, both the message store and notification list accumulate duplicates.

With `max_retries=2` and `fail_first=False`, the message is stored twice and two notifications are sent.

## The Correct Fix

Add `break` after successful send:

```python
def send_with_retry(msg, max_retries=2, fail_first=False):
    last_error = None
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            break  # success, stop retrying
        except ConnectionError as e:
            last_error = e
            continue
    return True
```

**Lines changed:** 1 (add `break` after `send()` call)

## What the Test Checks

1. Reset module state (`_messages = []`, `_notifications = []`, `_attempt_count = 0`)
2. Call `send_with_retry("order_123", max_retries=2, fail_first=False)`
3. **Assert:** `len(get_messages()) == 1` -- message stored exactly once
4. **Assert:** `len(get_notifications()) == 1` -- notification sent exactly once

## Why This Is Difficult for LLMs

- **Cross-file side effects:** The model must understand that `send()` calls `append()` and `notify()` from `store.py`, and that both are non-idempotent (each call adds one entry). The duplication is in `store.py` state, but the bug is in `sender.py` control flow.
- **try/except masking:** The `try/except` block with `continue` on error looks like proper retry logic. The missing `break` after the try-body is easy to overlook because the error path is explicitly handled.
- **Store append is the non-idempotent operation:** The F6 trap is that the retry mechanism (which should improve reliability) is the source of duplication. "Adding more retries" or "adding error handling" would make it worse, not better.
- **Common wrong fix:** Adding deduplication in `store.py` (treats symptom, not cause) or making `send()` idempotent (wrong layer to fix).

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I add a `break` after `send()`, the loop stops on first success, and `append()`/`notify()` in `store.py` each execute exactly once." This requires tracing the intervention's effect across the file boundary to the store's state.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism is itself the source of the duplication. The "fix" mechanism (retry on failure) becomes the "break" mechanism (multiply on success). An LLM that tries to add more error handling or increase retries would amplify the duplication.

### Why This Case Is L2, Not L1 or L3

**Not L1** because the side effects (`append`, `notify`) are defined in `store.py`. The model must cross one file boundary to understand that each `send()` call adds entries to the store.

**Not L3** because there are only two files and one function boundary. The retry/store interaction is a two-hop chain, not a multi-module state evolution.

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- a retry loop wraps non-idempotent operations (store append + notification) without a success exit. The cross-file architecture hides the side effect multiplication.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace non-idempotent effects across file boundary |
| 4o-mini | REI | May identify retry issue but fix at wrong layer (store dedup) |
| 5-mini | CSF | Should trace the cross-file dependency and add the break |
