"""Redis stream emitter for T3 ablation experiments.

Appends structured events to a Redis Stream alongside existing JSONL logging.
One stream per run. No aggregation in the hot path. All derivation happens
at read time (in the dashboard script or analysis tools).

Hot-path cost: one XADD per evaluation (~1ms local Redis).

Dependencies:
  - redis>=5.0 (pip install redis)
  - Redis server running locally (brew install redis && redis-server)

Failure policy:
  - Redis unavailable on first call: log WARNING once, skip.
  - Subsequent calls: retry connection (not permanently disabled).
  - Never crash the run. Never spam logs.
"""

import logging
import os
import time
from datetime import datetime

_log = logging.getLogger("t3.redis_metrics")

_client = None
_warned = False

REDIS_URL = os.environ.get("T3_REDIS_URL", "redis://localhost:6379/0")
REDIS_TIMEOUT = 1.0  # seconds


def _get_client():
    """Lazy-init Redis client. Retries on each call (not permanently disabled)."""
    global _client, _warned
    if _client is not None:
        try:
            _client.ping()
            return _client
        except Exception:
            _client = None  # stale connection, retry below
    try:
        import redis as _redis_mod
        _client = _redis_mod.Redis.from_url(
            REDIS_URL,
            socket_connect_timeout=REDIS_TIMEOUT,
            socket_timeout=REDIS_TIMEOUT,
            decode_responses=True,
        )
        _client.ping()
        if _warned:
            _log.info("Redis reconnected: %s", REDIS_URL)
        else:
            _log.info("Redis connected: %s", REDIS_URL)
        _warned = False
        return _client
    except Exception as e:
        _client = None
        if not _warned:
            _log.warning("Redis unavailable (%s): %s — streaming disabled until reconnect", REDIS_URL, e)
            _warned = True
        return None


def is_enabled() -> bool:
    """Check if Redis is reachable right now."""
    return _get_client() is not None


def stream_key(run_id: str) -> str:
    """Redis key for a run's event stream."""
    return f"t3:events:{run_id}"


def extract_difficulty(case_id: str) -> str:
    """Extract difficulty level from case_id suffix."""
    if case_id.endswith("_a"):
        return "A"
    elif case_id.endswith("_b"):
        return "B"
    elif case_id.endswith("_c"):
        return "C"
    elif "l3_" in case_id:
        return "L3"
    return "other"


def emit_event(
    run_id: str,
    model: str,
    trial: int | None,
    case_id: str,
    condition: str,
    ev: dict,
    elapsed_seconds: float | None = None,
) -> bool:
    """Append one evaluation event to the run's Redis Stream.

    This is the ONLY Redis operation in the hot path. One XADD, no pipeline,
    no counters, no sorted sets.

    Returns True on success, False on skip/failure. Never raises.
    """
    client = _get_client()
    if client is None:
        return False

    try:
        alignment = ev.get("alignment", {})
        category = alignment.get("category", "")

        event = {
            "timestamp": datetime.now().isoformat(),
            "ts_ms": str(int(time.time() * 1000)),
            "run_id": str(run_id or ""),
            "model": str(model),
            "trial": str(trial or 0),
            "case_id": str(case_id),
            "condition": str(condition),
            # Result
            "pass": str(ev.get("pass", False)),
            "score": str(ev.get("score", 0)),
            # LEG classification
            "category": str(category),
            "leg_true": str(category == "leg"),
            "lucky_fix": str(category == "lucky_fix"),
            "true_success": str(category == "true_success"),
            "reasoning_correct": str(ev.get("reasoning_correct", "")),
            "code_correct": str(ev.get("code_correct", "")),
            # Failure
            "failure_type": str(ev.get("failure_type", "")),
            # Retry
            "num_attempts": str(ev.get("num_attempts", 1)),
            # Pipeline metadata
            "response_format": str(ev.get("response_format", "")),
            "reconstruction_status": str(ev.get("reconstruction_status", "")),
            "prompt_tokens": str(ev.get("prompt_tokens", 0)),
            "token_budget_exceeded": str(ev.get("token_budget_exceeded", False)),
            # Derived
            "difficulty": extract_difficulty(case_id),
            "elapsed_seconds": str(elapsed_seconds or 0),
        }

        client.xadd(stream_key(run_id), event, maxlen=100000)
        return True

    except Exception as e:
        if not _warned:
            _log.warning("Redis emit failed (non-fatal): %s: %s", type(e).__name__, e)
        return False
