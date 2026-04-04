# Case: retry_dup_a

**Family:** retry_dup
**Difficulty:** A (Easy)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Refactor this message sender for clarity. Return the updated code.

## What the Code Does

A single-file message sender (`sender.py`) with a retry wrapper around a `send()` function.

```python
_sent = []

def send(msg):
    """Send a message. Always succeeds. Appends to _sent."""
    _sent.append(msg)
    return True

def retry_send(msg, max_retries=2):
    """Send with retry. Should only send once if first attempt succeeds."""
    for attempt in range(max_retries):
        result = send(msg)
        if not result:
            continue  # BUG: should break on success, not continue on failure
    return True
```

`send()` always succeeds (returns `True`). The retry loop iterates `max_retries` times regardless, because the `if not result: continue` guard never triggers -- `result` is always `True`, so the `continue` is dead code. The loop runs all iterations, calling `send()` each time.

## The Bug

The retry loop lacks a `break` on success. Since `send()` always returns `True`, the condition `if not result` is never true. The loop runs all `max_retries` iterations, appending the message to `_sent` on every attempt. With `max_retries=2`, the message appears twice in `_sent`.

The logic is inverted: the code says "if failure, continue" but should say "if success, break." The `continue` statement is dead code -- it never executes.

## The Correct Fix

Add a `break` after successful send:

```python
def retry_send(msg, max_retries=2):
    for attempt in range(max_retries):
        result = send(msg)
        if result:
            break  # success, stop retrying
    return True
```

**Lines changed:** 1 (change `if not result: continue` to `if result: break`, or add `break` after the send call)

## What the Test Checks

1. Reset module state (`_sent = []`)
2. Call `retry_send("hello", max_retries=2)`
3. **Assert:** `len(get_sent()) == 1` -- message stored exactly once
4. **Assert:** `get_sent()[0] == "hello"` -- correct message content

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize variable names or add docstrings without recognizing the missing `break`.
- **The code "works" in a sense:** It sends the message and returns `True`. The duplication is silent -- the caller sees success, and no exception is raised.
- **Inverted logic pattern:** The `if not result: continue` construct looks like error handling. Models often see `continue` in retry loops and assume it is correct. The actual logic is backwards -- the guard should be on success (`break`), not on failure (`continue`).
- **Common wrong fix:** Adding deduplication to `_sent` (treats the symptom, not the cause) or removing the retry loop entirely (changes the API).

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is entirely visible within `retry_send()`. The loop structure, the always-true return from `send()`, and the missing `break` are all in one function. The model needs only to associate the retry pattern with the need for a success-exit.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism itself is the problem. The intervention (retry on failure) doubles the side effect because it lacks a success exit. The mechanism that should improve reliability (retry) instead causes duplication. An LLM that tries to "improve" the retry logic (e.g., increase `max_retries`) would make the duplication worse.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `send()` is defined in the same file and its behavior (always succeeds, appends to list) is trivially visible. No cross-file reasoning needed.

**Not L3** because there is no multi-step state evolution or temporal ordering. The bug is a single structural issue (missing `break`).

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- a retry loop wraps a non-idempotent operation without a success exit, causing the operation to execute multiple times. The "always succeeds" nature of `send()` makes the retry loop a pure multiplier.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize retry pattern but fail to add the break |
| 4o-mini | Heuristic | Likely to notice the loop runs too many times |
| 5-mini | CSF | Should identify the missing break in the retry loop |
