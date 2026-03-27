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

    # Create a temp directory for test logs
    import tempfile

    test_log_dir = Path(tempfile.mkdtemp(prefix="t3_test_logs_"))

    test_model = "gpt-4.1-nano"
    init_run_log(test_model, log_dir=test_log_dir)

    yield

    close_run_log()
    # Clean up temp directory
    import shutil

    shutil.rmtree(test_log_dir, ignore_errors=True)
