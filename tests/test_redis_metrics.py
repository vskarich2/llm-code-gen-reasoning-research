"""Tests for the stream-only Redis emitter and dashboard derivation logic.

Unit tests (no Redis required):
  - Event field completeness
  - Difficulty extraction
  - Dashboard metric computation (pass rate, LEG rate, breakdowns)
  - Empty/missing data handling

Integration tests (require local Redis):
  - Stream write + read roundtrip
  - Graceful behavior when Redis is down
"""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from redis_metrics import extract_difficulty, emit_event, stream_key, is_enabled
from redis_live_dashboard import (
    compute_metrics,
    compute_by_field,
    compute_attempt_table,
    compute_failure_modes,
    compute_case_hotspots,
)


# ---------------------------------------------------------------------------
# Unit: difficulty extraction
# ---------------------------------------------------------------------------

def test_extract_difficulty():
    assert extract_difficulty("alias_config_a") == "A"
    assert extract_difficulty("cache_inv_b") == "B"
    assert extract_difficulty("partial_rollback_c") == "C"
    assert extract_difficulty("l3_state_pipeline") == "L3"
    assert extract_difficulty("check_then_act") == "other"
    assert extract_difficulty("lost_update") == "other"


def test_stream_key_format():
    assert stream_key("abc123") == "t3:events:abc123"


# ---------------------------------------------------------------------------
# Unit: dashboard derivation — pass rate, LEG rate
# ---------------------------------------------------------------------------

def _make_event(passed=True, leg=False, lucky=False, model="m1", condition="baseline",
                failure_type="", case_id="case_a", num_attempts="1", difficulty="A"):
    cat = "true_success" if passed and not lucky else ("lucky_fix" if lucky else ("leg" if leg else "true_failure"))
    return {
        "timestamp": "2026-03-25T10:00:00",
        "ts_ms": "1000",
        "run_id": "test",
        "model": model,
        "condition": condition,
        "trial": "1",
        "case_id": case_id,
        "pass": str(passed),
        "score": "1.0" if passed else "0.0",
        "category": cat,
        "leg_true": str(leg),
        "lucky_fix": str(lucky),
        "true_success": str(passed and not lucky and not leg),
        "reasoning_correct": "True" if (passed or leg) else "False",
        "code_correct": str(passed),
        "failure_type": failure_type,
        "num_attempts": num_attempts,
        "difficulty": difficulty,
        "response_format": "file_dict",
        "reconstruction_status": "SUCCESS",
        "prompt_tokens": "500",
        "token_budget_exceeded": "False",
        "elapsed_seconds": "1.5",
    }


def test_compute_metrics_basic():
    events = [
        _make_event(passed=True),
        _make_event(passed=False, leg=True),
        _make_event(passed=True, lucky=True),
        _make_event(passed=False),
    ]
    m = compute_metrics(events)
    assert m["total"] == 4
    assert m["passed"] == 2
    assert m["failed"] == 2
    assert abs(m["pass_rate"] - 0.5) < 0.01
    assert m["leg_count"] == 1
    assert abs(m["leg_rate_over_failures"] - 0.5) < 0.01  # 1 LEG out of 2 failures
    assert m["lucky_count"] == 1


def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m["empty"] is True


def test_compute_by_model():
    events = [
        _make_event(passed=True, model="gpt-nano"),
        _make_event(passed=False, leg=True, model="gpt-nano"),
        _make_event(passed=True, model="gpt-mini"),
    ]
    by_model = compute_by_field(events, "model")
    assert len(by_model) == 2
    nano = [r for r in by_model if r["name"] == "gpt-nano"][0]
    assert nano["total"] == 2
    assert nano["passed"] == 1
    assert nano["leg"] == 1
    assert abs(nano["leg_rate"] - 0.5) < 0.01


def test_compute_by_condition():
    events = [
        _make_event(passed=True, condition="baseline"),
        _make_event(passed=False, condition="baseline"),
        _make_event(passed=True, condition="retry_no_contract"),
    ]
    by_cond = compute_by_field(events, "condition")
    bl = [r for r in by_cond if r["name"] == "baseline"][0]
    assert bl["total"] == 2
    assert abs(bl["pass_rate"] - 0.5) < 0.01


def test_compute_attempt_table():
    events = [
        _make_event(passed=False, num_attempts="1"),
        _make_event(passed=False, num_attempts="1"),
        _make_event(passed=True, num_attempts="3"),
    ]
    table = compute_attempt_table(events)
    att1 = [r for r in table if r["name"] == "1"][0]
    assert att1["total"] == 2
    assert att1["passed"] == 0
    att3 = [r for r in table if r["name"] == "3"][0]
    assert att3["passed"] == 1


def test_compute_failure_modes():
    events = [
        _make_event(passed=False, failure_type="HIDDEN_DEPENDENCY", leg=True),
        _make_event(passed=False, failure_type="HIDDEN_DEPENDENCY"),
        _make_event(passed=False, failure_type="TEMPORAL_ORDERING", leg=True),
        _make_event(passed=True),
    ]
    top_failures, top_leg = compute_failure_modes(events, min_count=1)
    assert len(top_failures) == 2
    hd = [f for f in top_failures if f["failure_type"] == "HIDDEN_DEPENDENCY"][0]
    assert hd["count"] == 2
    assert hd["leg_count"] == 1
    assert abs(hd["leg_rate"] - 0.5) < 0.01


def test_compute_case_hotspots():
    events = [
        _make_event(passed=False, leg=True, case_id="hard_case"),
        _make_event(passed=False, leg=True, case_id="hard_case"),
        _make_event(passed=False, leg=True, case_id="other_case"),
        _make_event(passed=True, case_id="easy_case"),
    ]
    hotspots = compute_case_hotspots(events, top_k=5)
    assert hotspots[0]["case_id"] == "hard_case"
    assert hotspots[0]["leg_count"] == 2
    assert hotspots[1]["case_id"] == "other_case"
    assert hotspots[1]["leg_count"] == 1


def test_compute_by_difficulty():
    events = [
        _make_event(passed=True, difficulty="A"),
        _make_event(passed=False, difficulty="A", leg=True),
        _make_event(passed=False, difficulty="C"),
    ]
    by_diff = compute_by_field(events, "difficulty")
    a = [r for r in by_diff if r["name"] == "A"][0]
    assert a["total"] == 2
    assert abs(a["pass_rate"] - 0.5) < 0.01
    assert a["leg"] == 1


def test_missing_optional_fields():
    """Events with missing optional fields should not crash derivation."""
    events = [
        {"timestamp": "2026-03-25T10:00:00", "pass": "True"},  # minimal
        {"timestamp": "2026-03-25T10:00:01", "pass": "False", "leg_true": "True"},
    ]
    m = compute_metrics(events)
    assert m["total"] == 2
    assert m["passed"] == 1
    # By-field should handle missing keys gracefully
    by_model = compute_by_field(events, "model")
    assert len(by_model) >= 1  # all grouped under "unknown"


# ---------------------------------------------------------------------------
# Unit: emitter graceful failure
# ---------------------------------------------------------------------------

def test_emit_without_redis():
    """emit_event returns False without crashing when Redis is unavailable."""
    result = emit_event(
        run_id="test",
        model="gpt-test",
        trial=1,
        case_id="test_a",
        condition="baseline",
        ev={"pass": True, "alignment": {"category": "true_success"}},
    )
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Integration: Redis roundtrip (requires local Redis)
# ---------------------------------------------------------------------------

@pytest.fixture
def redis_client():
    try:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0",
                                 socket_connect_timeout=1, decode_responses=True)
        r.ping()
        return r
    except Exception:
        pytest.skip("Redis not available")


def test_stream_roundtrip(redis_client):
    """Write events to stream, read them back, verify fields."""
    import redis_metrics
    # Force reconnect
    redis_metrics._client = None
    redis_metrics._warned = False

    run_id = "test_roundtrip_stream"
    skey = stream_key(run_id)

    # Clean up
    redis_client.delete(skey)

    # Emit 3 events
    ev_pass = {"pass": True, "score": 1.0, "alignment": {"category": "true_success"},
               "failure_type": "", "num_attempts": 1}
    ev_leg = {"pass": False, "score": 0.0, "alignment": {"category": "leg"},
              "failure_type": "HIDDEN_DEPENDENCY", "num_attempts": 2}
    ev_fail = {"pass": False, "score": 0.0, "alignment": {"category": "true_failure"},
               "failure_type": "TEMPORAL_ORDERING", "num_attempts": 1}

    assert emit_event(run_id, "gpt-test", 1, "case_a", "baseline", ev_pass)
    assert emit_event(run_id, "gpt-test", 1, "case_b", "baseline", ev_leg)
    assert emit_event(run_id, "gpt-test", 1, "case_c", "retry", ev_fail)

    # Read back
    from redis_live_dashboard import read_stream
    events = read_stream(redis_client, skey)
    assert len(events) == 3

    # Verify fields on first event
    e0 = events[0]
    assert e0["case_id"] == "case_a"
    assert e0["pass"] == "True"
    assert e0["category"] == "true_success"
    assert e0["leg_true"] == "False"
    assert "timestamp" in e0
    assert "ts_ms" in e0

    # Verify LEG event
    e1 = events[1]
    assert e1["leg_true"] == "True"
    assert e1["failure_type"] == "HIDDEN_DEPENDENCY"
    assert e1["num_attempts"] == "2"

    # Compute metrics from stream
    m = compute_metrics(events)
    assert m["total"] == 3
    assert m["passed"] == 1
    assert abs(m["pass_rate"] - 1/3) < 0.01
    assert m["leg_count"] == 1

    # Clean up
    redis_client.delete(skey)


def test_stream_empty(redis_client):
    """Dashboard handles empty stream without crashing."""
    from redis_live_dashboard import read_stream, render_dashboard
    events = read_stream(redis_client, "t3:events:nonexistent_run")
    assert events == []
    output = render_dashboard("nonexistent", events)
    assert "No events yet" in output
