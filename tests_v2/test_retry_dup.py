"""Tests for retry_dup family (retry_state_accumulation).

Invariant: each message should appear exactly once in the store
           after a successful send, regardless of retry logic.
"""


def test_a(mod):
    """Level A: retry_send must not duplicate on success."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_sent"):
        mod._sent = []

    mod.retry_send("hello", max_retries=2)
    sent = mod.get_sent()

    if len(sent) != 1:
        return False, [
            f"expected 1 message in _sent after successful send, got {len(sent)}"
        ]

    if sent[0] != "hello":
        return False, [f"expected 'hello', got {sent[0]!r}"]

    return True, ["retry_send stores message exactly once on success"]


def test_b(mod):
    """Level B: send_with_retry must not duplicate in store."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_messages"):
        mod._messages = []
    if hasattr(mod, "_notifications"):
        mod._notifications = []
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0

    mod.send_with_retry("order_123", max_retries=2, fail_first=False)
    messages = mod.get_messages()

    if len(messages) != 1:
        return False, [
            f"expected 1 message in store after successful send, got {len(messages)}"
        ]

    notifications = mod.get_notifications()
    if len(notifications) != 1:
        return False, [
            f"expected 1 notification, got {len(notifications)}"
        ]

    return True, ["send_with_retry stores and notifies exactly once"]


def test_c(mod):
    """Level C: pipeline ingest must not multiply messages through nested retry."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_messages"):
        mod._messages = []
    if hasattr(mod, "_notifications"):
        mod._notifications = []
    if hasattr(mod, "_attempt_count"):
        mod._attempt_count = 0
    if hasattr(mod, "_ingest_log"):
        mod._ingest_log = []

    mod.ingest("payment_456", max_pipeline_retries=2, fail_first=False)
    messages = mod.get_messages()

    if len(messages) != 1:
        return False, [
            f"expected 1 message in store after ingest, got {len(messages)}"
        ]

    return True, ["ingest stores message exactly once through nested retry"]
