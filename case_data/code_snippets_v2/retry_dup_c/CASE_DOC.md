# Case: retry_dup_c

**Family:** retry_dup
**Difficulty:** C (Hard)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Messages appearing 3-4 times. Fix the retry logic. Return the updated code.

## What the Code Does

A three-file message ingestion system with nested retry logic.

**store.py** provides `append(msg)` and `notify(msg)` -- non-idempotent operations that each add one entry per call.

**sender.py** has `send_with_retry()` which wraps `send()` in a retry loop. This version correctly includes `break` on success:
```python
def send_with_retry(msg, max_retries=2, fail_first=False):
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            break  # correctly breaks on success
        except ConnectionError:
            continue
```

**pipeline.py** wraps `send_with_retry()` in ANOTHER retry loop:
```python
def ingest(msg, max_pipeline_retries=2, fail_first=False):
    for attempt in range(max_pipeline_retries):
        try:
            send_with_retry(msg, max_retries=2, fail_first=fail_first)
            # BUG: no break -- pipeline always retries, doubling sends
        except Exception:
            continue
    _ingest_log.append(msg)
    return True
```

The inner retry (`send_with_retry`) correctly breaks on success. But the outer retry (`ingest`) has NO `break` -- it always runs all `max_pipeline_retries` iterations. Each iteration successfully sends the message (via the inner retry), so the message is stored `max_pipeline_retries` times.

A distractor function `batch_ingest()` legitimately calls `send_with_retry` without retry, suggesting the pattern is fine.

## The Bug

The outer retry loop in `ingest()` lacks a `break` after `send_with_retry()` succeeds. Since `send_with_retry` returns `True` without raising, the `except` branch never triggers, and the loop runs all iterations. With `max_pipeline_retries=2`, the message is stored and notified twice (or more with higher retry counts).

The nested retry creates a **multiplicative** duplication risk: outer_retries x inner_retries potential duplications if both loops lack breaks. Here, the inner loop is correct but the outer loop is broken.

## The Correct Fix

Add `break` after `send_with_retry()` in `ingest()`:

```python
def ingest(msg, max_pipeline_retries=2, fail_first=False):
    for attempt in range(max_pipeline_retries):
        try:
            send_with_retry(msg, max_retries=2, fail_first=fail_first)
            break  # success, stop pipeline retry
        except Exception:
            continue
    _ingest_log.append(msg)
    return True
```

**Lines changed:** 1 (add `break` after `send_with_retry` call)

## What the Test Checks

1. Reset all module state (`_messages = []`, `_notifications = []`, `_attempt_count = 0`, `_ingest_log = []`)
2. Call `ingest("payment_456", max_pipeline_retries=2, fail_first=False)`
3. **Assert:** `len(get_messages()) == 1` -- message stored exactly once through nested retry

## Why This Is Difficult for LLMs

- **Nested retry is the hard pattern:** The model must understand TWO retry loops and identify which one is broken. The inner loop (`send_with_retry`) is correct. The outer loop (`ingest`) is broken. Models often fix the inner loop (which is already correct) or add deduplication instead of fixing the outer break.
- **Trap: adding outer retry makes it worse.** The F6 trap is especially strong here -- an LLM that "improves reliability" by increasing `max_pipeline_retries` would make the duplication worse. The intervention (more retries) doubles the problem.
- **Three-file trace:** Understanding the full effect chain requires: `pipeline.ingest()` -> `sender.send_with_retry()` -> `sender.send()` -> `store.append()` + `store.notify()`.
- **Distractor function:** `batch_ingest()` in `pipeline.py` calls `send_with_retry` without its own retry, suggesting the sender's retry is sufficient. This might lead models to remove the outer retry entirely rather than adding a `break`.
- **The `except Exception` in ingest catches too broadly**, but narrowing it is not the fix -- the missing `break` is.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform deterministic state tracing across modules through nested control flow: trace the outer loop in `ingest()` to see it lacks a `break`, then follow each iteration into `send_with_retry()` -> `send()` -> `store.append()` + `store.notify()`. This is forward path analysis through three levels of nesting across three files -- multi-step causal propagation verifying the mechanism at each retry boundary to determine that the outer loop runs all iterations despite inner success.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism at the pipeline level is the source of multiplication. The "intervention" (pipeline-level retry for reliability) doubles the message count. The nested structure means both layers of retry must be correct; a model that focuses on only one layer leaves the other broken.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug involves three files and nested control flow. No single-function analysis reveals the full duplication chain.

**L2 (deep)** because the model must trace two nested retry loops across three files, verify the mechanism at each level (inner has `break`, outer does not), and propagate the causal effect of the missing `break` through the nested execution to count the resulting duplications. This is multi-step causal propagation with mechanism verification at each retry boundary.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The missing `break`, the loop iteration count, and the side-effect accumulation are all directly observable from tracing the actual control flow.

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- nested retry loops without proper success exits create multiplicative duplication of non-idempotent side effects. The three-file architecture distributes the retry logic across layers, making the duplication source hard to localize.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot reason about nested retry across 3 files |
| 4o-mini | CSF | May fix the wrong layer or add deduplication instead of break |
| 5-mini | CSF | Nested retry with distractor is near the capability boundary |
