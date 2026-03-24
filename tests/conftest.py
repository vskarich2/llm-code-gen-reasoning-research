"""Shared test fixtures.

Ensures a RunLogger is active for any test that calls write_log.
"""
import sys
import os
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# FORCE mock mode for ALL tests — never use real API in test suite
os.environ["OPENAI_API_KEY"] = "sk-dummy"

import pytest

BASE = Path(__file__).resolve().parents[1]
_session_logger_initialized = False


@pytest.fixture(autouse=True)
def _ensure_run_logger():
    """Auto-fixture: ensure a RunLogger exists for tests that trigger write_log.

    Creates one logger per test to avoid cross-test contamination.
    Cleans up after each test.
    """
    from execution import get_current_log_path, init_run_log, close_run_log

    # If a logger is already active (from a test that manually created one), skip
    if get_current_log_path() is not None:
        yield
        return

    # Clean stale test logs, init logger, yield, close
    logs_dir = BASE / "logs"
    logs_dir.mkdir(exist_ok=True)
    for f in logs_dir.glob("_test-auto_*"):
        f.unlink(missing_ok=True)

    # Use the model name that tests actually use, so RunLogger model check passes.
    # All test functions use "gpt-4.1-nano" as the mock model.
    test_model = "gpt-4.1-nano"
    # Remove any stale log files for this model to avoid timestamp collision
    for f in logs_dir.glob(f"{test_model}*"):
        f.unlink(missing_ok=True)

    try:
        init_run_log(test_model)
    except FileExistsError:
        import time
        time.sleep(1)
        init_run_log(test_model)

    yield

    close_run_log()
    # Clean up test log files
    for f in logs_dir.glob(f"{test_model}*"):
        f.unlink(missing_ok=True)
