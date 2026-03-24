"""Ingestion pipeline with its own retry around sender."""

from sender import send_with_retry, reset_sender
from store import get_messages

_ingest_log = []


def reset():
    global _ingest_log, _messages, _notifications, _attempt_count
    _ingest_log = []
    _messages = []
    _notifications = []
    _attempt_count = 0


def ingest(msg, max_pipeline_retries=2, fail_first=False):
    """Ingest a message with pipeline-level retry."""
    for attempt in range(max_pipeline_retries):
        try:
            send_with_retry(msg, max_retries=2, fail_first=fail_first)
            break  # FIX: break after successful send to avoid duplicates
        except Exception:
            continue
    _ingest_log.append(msg)
    return True


def get_ingest_log():
    return list(_ingest_log)


def batch_ingest(messages):
    """Ingest multiple messages. Legitimate batch — no retry needed."""
    for msg in messages:
        send_with_retry(msg, max_retries=1)
    return len(messages)
