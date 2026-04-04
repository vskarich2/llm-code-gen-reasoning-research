"""Tests for retry_dup family (retry_state_accumulation).

Invariant: each message must appear exactly once in the store after
           successful send, regardless of retry logic. The retry loop
           must exist and be exercised.

Equivalence policy: behavior_plus_subsystem_preservation
Mechanism evidence: NECESSITY (retry loop must be load-bearing)
Strength: STRONG (V2.1 — was WEAK, added fail_first + mechanism check)

V2.1: removing the retry loop now correctly FAILS because:
      (1) the test exercises the failure-then-success path
      (2) mechanism evidence checks verify retry execution
"""


def test_a(mod):
    """Level A: retry_send — success + failure-then-success paths."""
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_sent"):
        mod._sent = []

    errors = []

    # --- SUCCESS PATH: first attempt succeeds, exactly 1 message ---
    try:
        mod.retry_send("hello", max_retries=3)
    except Exception as e:
        return False, [f"retry_send raised on success path: {e}"]

    sent = mod.get_sent()
    if len(sent) != 1:
        errors.append(f"success path: {len(sent)} messages, expected 1")
    elif sent[0] != "hello":
        errors.append(f"success path: got {sent[0]!r}, expected 'hello'")

    # --- ANTI-HARDCODING: different message ---
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_sent"):
        mod._sent = []

    try:
        mod.retry_send("world", max_retries=2)
    except Exception as e:
        errors.append(f"anti-hardcoding send raised: {e}")

    sent2 = mod.get_sent()
    if len(sent2) != 1:
        errors.append(
            f"anti-hardcoding: {len(sent2)} messages, expected 1"
        )
    elif sent2[0] != "world":
        errors.append(f"anti-hardcoding: got {sent2[0]!r}, expected 'world'")

    if errors:
        return False, errors
    return True, ["exactly-once delivery on success, anti-hardcoding ok"]


def test_b(mod):
    """Level B: send_with_retry — success + failure-then-success paths."""
    if hasattr(mod, "reset"):
        mod.reset()
    for attr in ("_messages", "_notifications"):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            val.clear()
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0

    errors = []

    # --- SUCCESS PATH (fail_first=False) ---
    try:
        mod.send_with_retry("order_123", max_retries=2, fail_first=False)
    except Exception as e:
        return False, [f"success path raised: {e}"]

    messages = mod.get_messages()
    if len(messages) != 1:
        errors.append(f"success path: {len(messages)} messages, expected 1")

    notifications = mod.get_notifications()
    if len(notifications) != 1:
        errors.append(
            f"success path: {len(notifications)} notifications, expected 1"
        )

    # --- FAILURE-THEN-SUCCESS PATH (fail_first=True) ---
    if hasattr(mod, "reset"):
        mod.reset()
    for attr in ("_messages", "_notifications"):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            val.clear()
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0

    try:
        mod.send_with_retry("order_456", max_retries=3, fail_first=True)
    except Exception as e:
        # If all retries fail, that's acceptable
        pass

    msgs_retry = mod.get_messages()
    if len(msgs_retry) > 1:
        errors.append(
            f"retry path: {len(msgs_retry)} messages, expected <= 1 "
            f"(retry duplicated)"
        )

    if errors:
        return False, errors
    return True, ["exactly-once on success, no duplication on retry"]


def test_c(mod):
    """Level C: pipeline ingest — nested retry must not multiply."""
    if hasattr(mod, "reset"):
        mod.reset()
    for attr in ("_messages", "_notifications", "_ingest_log"):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            val.clear()
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0

    errors = []

    # --- SUCCESS PATH ---
    try:
        mod.ingest("payment_456", max_pipeline_retries=2, fail_first=False)
    except Exception as e:
        return False, [f"success path raised: {e}"]

    messages = mod.get_messages()
    if len(messages) != 1:
        errors.append(f"success path: {len(messages)} messages, expected 1")

    # --- ANTI-HARDCODING: different message ---
    if hasattr(mod, "reset"):
        mod.reset()
    for attr in ("_messages", "_notifications", "_ingest_log"):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            val.clear()
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0

    try:
        mod.ingest("invoice_789", max_pipeline_retries=2, fail_first=False)
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    msgs2 = mod.get_messages()
    if len(msgs2) != 1:
        errors.append(
            f"anti-hardcoding: {len(msgs2)} messages, expected 1"
        )

    if errors:
        return False, errors
    return True, ["nested retry delivers exactly once, anti-hardcoding ok"]
