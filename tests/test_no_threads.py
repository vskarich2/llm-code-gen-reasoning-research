"""Tests proving ThreadPoolExecutor and thread-based parallelism are removed.

These are permanent regression tests. If any fail, threading has been
reintroduced and must be removed immediately.
"""

import os
import sys
import subprocess
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE_DIR = Path(__file__).parent.parent

# Source files to audit (exclude test files, benchmark content, venv)
SOURCE_FILES = [
    "runner.py", "execution.py", "llm.py", "evaluator.py",
    "parse.py", "retry_harness.py", "contract.py", "diff_gate.py",
    "leg_reduction.py", "leg_evaluator.py", "live_metrics.py",
    "condition_registry.py", "config.py", "templates.py",
    "constants.py", "reconstructor.py", "preflight_check.py",
    "prompts.py", "reasoning_prompts.py", "scm_prompts.py",
    "nudges/router.py", "nudges/operators.py", "nudges/mapping.py",
    "nudges/core.py",
]


class TestNoThreadPoolExecutor:
    """ThreadPoolExecutor must not exist in any source file."""

    def test_no_threadpoolexecutor_import(self):
        for f in SOURCE_FILES:
            path = BASE_DIR / f
            if not path.exists():
                continue
            content = path.read_text()
            assert "ThreadPoolExecutor" not in content or "No threads. No ThreadPoolExecutor" in content, (
                f"ThreadPoolExecutor found in {f}. "
                f"Thread-based parallelism is forbidden. Use process-based parallelism."
            )

    def test_no_concurrent_futures_import(self):
        for f in SOURCE_FILES:
            path = BASE_DIR / f
            if not path.exists():
                continue
            content = path.read_text()
            assert "from concurrent.futures import" not in content, (
                f"concurrent.futures import found in {f}. "
                f"Thread-based parallelism is forbidden."
            )
            assert "import concurrent" not in content, (
                f"concurrent import found in {f}."
            )


class TestNoInfrastructureThreading:
    """No threading module usage in infrastructure code."""

    def test_no_threading_import_in_source(self):
        for f in SOURCE_FILES:
            path = BASE_DIR / f
            if not path.exists():
                continue
            content = path.read_text()
            assert "import threading" not in content, (
                f"'import threading' found in {f}. "
                f"Infrastructure code must not use threads. "
                f"Execution is serial within each process."
            )

    def test_no_threading_lock_in_source(self):
        for f in SOURCE_FILES:
            path = BASE_DIR / f
            if not path.exists():
                continue
            content = path.read_text()
            assert "threading.Lock" not in content, (
                f"threading.Lock found in {f}. "
                f"Locks are not needed — execution is serial."
            )

    def test_no_thread_name_logging(self):
        """Thread name in log messages indicates thread-aware code."""
        for f in SOURCE_FILES:
            path = BASE_DIR / f
            if not path.exists():
                continue
            content = path.read_text()
            assert "thread=" not in content.lower() or "# No threads" in content, (
                f"Thread-name logging found in {f}. "
                f"Remove thread references from log messages."
            )


class TestRunAllIsSerial:
    """run_all() must execute serially with no parallelism option."""

    def test_run_all_signature_no_max_workers(self):
        """run_all must not accept max_workers parameter."""
        import inspect
        from runner import run_all
        sig = inspect.signature(run_all)
        assert "max_workers" not in sig.parameters, (
            f"run_all still has max_workers parameter. "
            f"Remove it — execution is always serial."
        )

    def test_parallel_flag_is_deprecated(self):
        """--parallel flag must not trigger thread creation."""
        from runner import main
        import inspect
        source = inspect.getsource(main)
        assert "ThreadPoolExecutor" not in source
        assert "max_workers" not in source


class TestRunLoggerNoLock:
    """RunLogger must not use threading locks."""

    def test_no_lock_attribute(self):
        from execution import RunLogger
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            logger = RunLogger(
                tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "c.jsonl",
                model="test", run_id="test",
            )
            assert not hasattr(logger, "_lock"), (
                "RunLogger still has _lock attribute. "
                "Remove threading.Lock — execution is serial."
            )
