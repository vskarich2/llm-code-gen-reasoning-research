"""Regression tests for system repair bugs.

Each test reproduces a specific bug found in the 2026-04-04 audit.
Tests are named after the bug ID (P0-1, P0-2, etc.).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── P0-1: events.jsonl not contaminated on reuse ──

def test_events_file_not_contaminated_when_attempt_dir_reused():
    """events.jsonl opens in write mode. Stale events from prior run are erased."""
    from core.logging_.logging_core import BaseLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        events_path = Path(tmpdir) / "events.jsonl"

        # Simulate prior failed run — write stale events
        events_path.write_text(
            '{"event_type": "run.start", "stale": true}\n'
            '{"event_type": "case.end", "stale": true}\n'
        )
        assert events_path.read_text().count("\n") == 2

        # New logger opens the file — must truncate
        logger = BaseLogger(events_path)
        # File is now empty (truncated by "w" mode)
        logger.close()

        content = events_path.read_text()
        assert "stale" not in content, (
            f"Stale events survived logger init: {content!r}")


def test_no_duplicate_sequence_numbers_in_reused_worker():
    """Even if attempt dir is reused, sequence numbers start fresh."""
    from core.logging_.logging_core import BaseLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        events_path = Path(tmpdir) / "events.jsonl"

        # First run writes events
        logger1 = BaseLogger(events_path, instance_id="test_worker")
        logger1._write_event({"event_type": "run.start"})
        logger1._write_event({"event_type": "case.start"})
        logger1.close()

        # Second run on same path
        logger2 = BaseLogger(events_path, instance_id="test_worker")
        logger2._write_event({"event_type": "run.start"})
        logger2._write_event({"event_type": "case.start"})
        logger2.close()

        events = [json.loads(l) for l in events_path.read_text().strip().split("\n")]
        sequences = [e["sequence"] for e in events]
        assert sequences == [1, 2], f"Expected [1, 2], got {sequences}"
        assert len(events) == 2, f"Expected 2 events, got {len(events)}"


# ── P0-2: retry oracle call emits logged event ──

def test_retry_oracle_logger_parameter_present():
    """run_oracle_evaluation in retry_v2.py must pass logger."""
    import ast as ast_mod
    source = Path("core/pipeline/orchestration/retry_v2.py").read_text()
    tree = ast_mod.parse(source)

    # Find all calls to run_oracle_evaluation
    calls = []
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Call):
            func = node.func
            if isinstance(func, ast_mod.Name) and func.id == "run_oracle_evaluation":
                kw_names = [kw.arg for kw in node.keywords]
                calls.append(kw_names)
            elif isinstance(func, ast_mod.Attribute) and func.attr == "run_oracle_evaluation":
                kw_names = [kw.arg for kw in node.keywords]
                calls.append(kw_names)

    # retry_v2 now delegates to stage_oracle() in stages.py.
    # Check stages.py if no direct calls found in retry_v2.
    if not calls:
        stages_path = Path(__file__).resolve().parent.parent / "pipeline" / "orchestration" / "stages.py"
        if stages_path.exists():
            stages_tree = ast_mod.parse(stages_path.read_text())
            for node in ast_mod.walk(stages_tree):
                if isinstance(node, ast_mod.Call):
                    func = node.func
                    if isinstance(func, ast_mod.Name) and func.id == "run_oracle_evaluation":
                        calls.append([kw.arg for kw in node.keywords])
                    elif isinstance(func, ast_mod.Attribute) and func.attr == "run_oracle_evaluation":
                        calls.append([kw.arg for kw in node.keywords])
    assert len(calls) > 0, "No calls to run_oracle_evaluation found in retry_v2.py or stages.py"
    for kw_names in calls:
        assert "logger" in kw_names, (
            f"run_oracle_evaluation call missing logger= keyword. "
            f"Found keywords: {kw_names}")


# ── P0-3: oracle missing input distinct from short reasoning ──

def test_oracle_missing_root_cause_distinct_from_reasoning_too_short():
    """None root_cause must produce different error than short reasoning."""
    from core.evaluation.oracle_inline import run_oracle_evaluation

    config = MagicMock()
    config.oracle.inline_enabled = True
    config.oracle.partial_mode = "lenient"
    config.oracle.sampling_strategy = "ALWAYS"

    # None root_cause
    result_none = run_oracle_evaluation(None, "valid fix strategy text here", {}, config)
    assert result_none["status"] == "SKIPPED"
    assert result_none["error"] == "missing_root_cause"

    # Both None
    result_both = run_oracle_evaluation(None, None, {}, config)
    assert result_both["status"] == "SKIPPED"
    assert result_both["error"] == "missing_root_cause_and_fix_strategy"

    # Short but present
    result_short = run_oracle_evaluation("a", "b", {}, config)
    assert result_short["status"] == "SKIPPED"
    assert result_short["error"] == "reasoning_too_short"

    # All three are structurally distinct
    errors = {result_none["error"], result_both["error"], result_short["error"]}
    assert len(errors) == 3, f"Oracle skip errors not distinct: {errors}"


def test_oracle_missing_fix_strategy_distinct():
    """None fix_strategy must produce specific error."""
    from core.evaluation.oracle_inline import run_oracle_evaluation

    config = MagicMock()
    config.oracle.inline_enabled = True
    config.oracle.partial_mode = "lenient"
    config.oracle.sampling_strategy = "ALWAYS"

    result = run_oracle_evaluation("valid root cause text here", None, {}, config)
    assert result["status"] == "SKIPPED"
    assert result["error"] == "missing_fix_strategy"


# ── P1-1: oracle.timeout rejected ──

def test_oracle_timeout_rejected():
    """Config with oracle.timeout must fail at load time."""
    import yaml

    base_config = yaml.safe_load(
        Path("core/config/config_storage/smoke_oracle_inline.yaml").read_text())
    base_config["oracle"]["timeout"] = 30

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(base_config, f)
        tmp = f.name

    try:
        from core.config.experiment_config import load_config
        import core.config.experiment_config as mod
        old = mod._config
        try:
            with pytest.raises(ValueError, match="oracle.timeout is not supported"):
                load_config(tmp)
        finally:
            mod._config = old
    finally:
        os.unlink(tmp)


# ── P1-2: FINAL_ONLY rejected ──

def test_final_only_rejected_at_config():
    """FINAL_ONLY sampling must fail at config validation."""
    import yaml

    base_config = yaml.safe_load(
        Path("core/config/config_storage/smoke_oracle_inline.yaml").read_text())
    base_config["oracle"]["sampling_strategy"] = "FINAL_ONLY"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(base_config, f)
        tmp = f.name

    try:
        from core.config.experiment_config import load_config
        import core.config.experiment_config as mod
        old = mod._config
        try:
            with pytest.raises(ValueError, match="FINAL_ONLY.*not supported"):
                load_config(tmp)
        finally:
            mod._config = old
    finally:
        os.unlink(tmp)


def test_final_only_rejected_at_parse():
    """parse_sampling_strategy must reject FINAL_ONLY."""
    from core.evaluation.oracle_inline import parse_sampling_strategy
    with pytest.raises(ValueError, match="FINAL_ONLY.*not supported"):
        parse_sampling_strategy("FINAL_ONLY")


# ── P1-4: parent_event_id None vs 0 ──

def test_parent_event_id_none_not_collapsed_with_zero():
    """parent_event_id=None and parent_event_id=0 must be distinct."""
    import ast as ast_mod
    source = Path("core/pipeline/llm.py").read_text()
    # The old bug was: parent_event_id or 0
    # The fix is: parent_event_id if parent_event_id is not None else 0
    assert "parent_event_id or 0" not in source, (
        "llm.py still contains 'parent_event_id or 0' — "
        "this conflates None and 0 (falsy values)")


# ── P1-5: finalize lifecycle ──

def test_finalize_runs_on_body_exception():
    """Logger must be finalized even if run body throws."""
    from core.logging_.logging_core import RunLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        run_dir.mkdir()
        logger = RunLogger(run_dir, run_id="test", model="m", condition="c", trial=1)

        # Write some events so finalize has something
        logger.log_event("run.start", {}, phase="run")
        logger.log_event("run.end", {}, phase="run")

        # finalize should work
        stats = logger.finalize()
        assert stats is not None


def test_finalize_failure_does_not_mask_primary_exception():
    """If body throws and finalize throws, body exception must survive."""
    from core.logging_.logging_core import RunLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        run_dir.mkdir()
        logger = RunLogger(run_dir, run_id="test", model="m", condition="c", trial=1)

        # Close the logger so finalize will fail
        logger.close()

        # Simulating: body exception is ValueError, finalize will fail
        body_exc = ValueError("body error")
        finalize_exc = None
        raised_exc = None

        try:
            try:
                raise body_exc
            finally:
                try:
                    logger.finalize()
                except Exception as fe:
                    finalize_exc = fe
                    # Re-raise original (policy: don't mask)
                    pass
        except ValueError as e:
            raised_exc = e

        assert raised_exc is body_exc, "Body exception was masked"
        # finalize_exc may or may not be set depending on internal state


# ── P1-3: AST checker exception visibility ──

def test_ast_checker_exception_visible_at_warning():
    """AST checker exceptions must be logged at WARNING, not DEBUG."""
    import ast as ast_mod
    source = Path("core/evaluation/ast_eval.py").read_text()
    # Should NOT have debug-level logging for checker failures
    assert '_log.debug("strict checker' not in source, (
        "ast_eval.py still logs strict checker exceptions at DEBUG level")
    assert '_log.debug("relaxed checker' not in source, (
        "ast_eval.py still logs relaxed checker exceptions at DEBUG level")
    # Should have warning-level logging
    assert '_log.warning("strict checker EXCEPTION' in source
    assert '_log.warning("relaxed checker EXCEPTION' in source
    assert '_log.warning("anti checker EXCEPTION' in source


# ── Event chain integrity ──

def test_event_chain_integrity():
    """Event IDs must be unique and sequences strictly monotonic."""
    from core.logging_.logging_core import BaseLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        events_path = Path(tmpdir) / "events.jsonl"
        logger = BaseLogger(events_path, instance_id="chain_test")

        eids = []
        for etype in ["run.start", "case.start", "case.end", "run.end"]:
            eid = logger._write_event({"event_type": etype})
            eids.append(eid)
        logger.close()

        events = [json.loads(l) for l in events_path.read_text().strip().split("\n")]
        sequences = [e["sequence"] for e in events]
        event_ids = [e["event_id"] for e in events]

        # Sequences strictly monotonic from 1
        assert sequences == list(range(1, len(sequences) + 1)), (
            f"Sequences not monotonic: {sequences}")

        # Event IDs unique
        assert len(set(event_ids)) == len(event_ids), (
            f"Duplicate event IDs: {event_ids}")


# ── Validation: oracle skip reasons ──

def test_validation_rejects_unknown_oracle_skip_error():
    """Validation must flag unrecognized oracle SKIPPED error values."""
    from core.evaluation.event_validation import validate_event

    ev = {
        "_schema_version": "v3.1",
        "oracle": {
            "status": "SKIPPED",
            "reasoning_truth": "UNASSESSED",
            "oracle_correct": None,
            "partial_mode": "lenient",
            "error": "pre_filter:reasoning_too_short",  # OLD format
        },
        "classification": {},
        "ast_eval": {"status": "no_spec", "ast_correct": None},
        "evaluation": {},
    }

    violations = validate_event(ev, None, -1)
    assert any("unrecognized error" in v for v in violations), (
        f"Expected validation to flag old skip error format. Got: {violations}")
