"""Tests for prompt provenance logging — Phase 11.

Validates that from a logged call record alone, the exact prompt
can be reconstructed and its hash matches.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _reset_all():
    from prompt_registry import _reset_for_testing, load_prompt_registry
    _reset_for_testing()
    load_prompt_registry()
    yield
    _reset_for_testing()


class TestProvenanceLogging:

    def test_provenance_set_and_consumed(self):
        """set_prompt_provenance stores data, _consume_provenance returns and clears it."""
        from call_logger import set_prompt_provenance, _consume_provenance
        from assembly_engine import build

        r = build(["task_and_code"], {"task": "Fix.", "code_files_block": "code"})
        set_prompt_provenance(r, {"task": "Fix.", "code_files_block": "code"},
                              condition="baseline", config_name="test")

        prov = _consume_provenance()
        assert prov is not None
        assert prov["component_names"] == ["task_and_code"]
        assert prov["final_prompt_hash"] == r.final_prompt_hash
        assert prov["condition"] == "baseline"
        assert prov["config_name"] == "test"
        assert "task" in prov["variables"]
        assert prov["variables"]["task"] == "Fix."

        # Second consume returns None (already consumed)
        assert _consume_provenance() is None

    def test_provenance_in_call_record(self, tmp_path):
        """emit_call includes prompt_assembly field when provenance is set."""
        from call_logger import init_call_logger, close_call_logger, emit_call
        from call_logger import set_call_context, set_prompt_provenance
        from assembly_engine import build

        init_call_logger(tmp_path)

        r = build(["task_and_code"], {"task": "Fix.", "code_files_block": "code"})
        set_prompt_provenance(r, {"task": "Fix.", "code_files_block": "code"},
                              condition="baseline")
        set_call_context(phase="generation", case_id="test_case")
        emit_call(model="test", prompt_raw=r.final_prompt, response_raw="resp",
                  elapsed_seconds=0.1)

        close_call_logger()

        record = json.loads((tmp_path / "calls" / "000001.json").read_text())
        assert "prompt_assembly" in record
        pa = record["prompt_assembly"]
        assert pa["component_names"] == ["task_and_code"]
        assert pa["final_prompt_hash"] == r.final_prompt_hash
        assert pa["condition"] == "baseline"
        assert "task" in pa["variables"]

    def test_provenance_absent_when_not_set(self, tmp_path):
        """If provenance is not set, prompt_assembly is null."""
        from call_logger import init_call_logger, close_call_logger, emit_call
        from call_logger import set_call_context

        init_call_logger(tmp_path)
        set_call_context(phase="classifier", case_id="test")
        emit_call(model="test", prompt_raw="raw", response_raw="resp",
                  elapsed_seconds=0.1)
        close_call_logger()

        record = json.loads((tmp_path / "calls" / "000001.json").read_text())
        assert record["prompt_assembly"] is None


class TestPromptReconstruction:
    """The critical test: reconstruct prompt from log entry alone."""

    def test_reconstruct_baseline_from_log(self, tmp_path):
        """Given only a call log entry, reconstruct the exact prompt."""
        from call_logger import init_call_logger, close_call_logger, emit_call
        from call_logger import set_call_context, set_prompt_provenance
        from assembly_engine import build
        from jinja2 import Environment, StrictUndefined

        init_call_logger(tmp_path)

        # Build a prompt
        variables = {"task": "Refactor config.", "code_files_block": "def f(): pass"}
        r = build(["task_and_code"], variables)
        set_prompt_provenance(r, variables, condition="baseline")
        set_call_context(phase="generation", case_id="test")
        emit_call(model="test", prompt_raw=r.final_prompt, response_raw="resp",
                  elapsed_seconds=0.1)
        close_call_logger()

        # Now reconstruct from the log entry ONLY
        record = json.loads((tmp_path / "calls" / "000001.json").read_text())
        pa = record["prompt_assembly"]

        # Reconstruct: load components by name, render with logged variables
        from prompt_registry import get_component
        env = Environment(undefined=StrictUndefined)
        parts = []
        for comp_name in pa["component_names"]:
            comp = get_component(comp_name)
            template = env.from_string(comp.raw_text)
            rendered = template.render(**pa["variables"])
            parts.append(rendered)
        reconstructed = "".join(parts)

        # Verify hash matches
        logged_hash = pa["final_prompt_hash"]
        reconstructed_hash = hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()[:16]

        assert reconstructed_hash == logged_hash, (
            f"RECONSTRUCTION FAILURE: "
            f"logged_hash={logged_hash}, reconstructed_hash={reconstructed_hash}, "
            f"logged_prompt_len={record['prompt_length']}, reconstructed_len={len(reconstructed)}"
        )

    def test_reconstruct_nudge_condition_from_log(self, tmp_path):
        """Reconstruct a diagnostic nudge prompt from log entry."""
        from call_logger import init_call_logger, close_call_logger, emit_call
        from call_logger import set_call_context, set_prompt_provenance
        from assembly_engine import build, resolve_nudge

        init_call_logger(tmp_path)

        nudge_text = resolve_nudge("diagnostic__generic_dependency")
        variables = {
            "task": "Fix caching bug.",
            "code_files_block": "def save(): pass",
            "diagnostic_text": nudge_text,
        }
        r = build(["task_and_code", "nudge_diagnostic"], variables)
        set_prompt_provenance(r, variables, condition="diagnostic")
        set_call_context(phase="generation", case_id="test")
        emit_call(model="test", prompt_raw=r.final_prompt, response_raw="resp",
                  elapsed_seconds=0.1)
        close_call_logger()

        # Reconstruct
        record = json.loads((tmp_path / "calls" / "000001.json").read_text())
        pa = record["prompt_assembly"]

        from prompt_registry import get_component
        from jinja2 import Environment, StrictUndefined
        env = Environment(undefined=StrictUndefined)
        parts = []
        for comp_name in pa["component_names"]:
            comp = get_component(comp_name)
            rendered = env.from_string(comp.raw_text).render(**pa["variables"])
            parts.append(rendered)
        reconstructed = "".join(parts)

        logged_hash = pa["final_prompt_hash"]
        reconstructed_hash = hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()[:16]
        assert reconstructed_hash == logged_hash

    def test_reconstruct_with_output_instruction(self, tmp_path):
        """Reconstruct a prompt that includes output instruction."""
        from call_logger import init_call_logger, close_call_logger, emit_call
        from call_logger import set_call_context, set_prompt_provenance
        from assembly_engine import build

        init_call_logger(tmp_path)

        variables = {
            "task": "Fix.",
            "code_files_block": "code",
            "schema_line": '{"reasoning": "...", "files": {"a.py": "..."}}',
        }
        r = build(["task_and_code", "output_instruction_v2"], variables)
        set_prompt_provenance(r, variables, condition="baseline")
        set_call_context(phase="generation", case_id="test")
        emit_call(model="test", prompt_raw=r.final_prompt, response_raw="resp",
                  elapsed_seconds=0.1)
        close_call_logger()

        record = json.loads((tmp_path / "calls" / "000001.json").read_text())
        pa = record["prompt_assembly"]

        from prompt_registry import get_component
        from jinja2 import Environment, StrictUndefined
        env = Environment(undefined=StrictUndefined)
        parts = []
        for comp_name in pa["component_names"]:
            comp = get_component(comp_name)
            rendered = env.from_string(comp.raw_text).render(**pa["variables"])
            parts.append(rendered)
        reconstructed = "".join(parts)

        assert hashlib.sha256(reconstructed.encode()).hexdigest()[:16] == pa["final_prompt_hash"]


class TestProvenanceCompleteness:

    def test_all_variables_logged(self):
        """Every variable passed to build() must appear in provenance."""
        from call_logger import set_prompt_provenance, _consume_provenance
        from assembly_engine import build

        variables = {
            "task": "Fix the bug.",
            "code_files_block": "def f(): pass",
            "diagnostic_text": "Check dependencies.",
        }
        r = build(["task_and_code", "nudge_diagnostic"], variables)
        set_prompt_provenance(r, variables, condition="diagnostic")

        prov = _consume_provenance()
        for key, val in variables.items():
            assert key in prov["variables"], f"Variable '{key}' missing from provenance"
            assert prov["variables"][key] == val, f"Variable '{key}' value mismatch"

    def test_component_hashes_logged(self):
        """Component hashes must match registry hashes."""
        from call_logger import set_prompt_provenance, _consume_provenance
        from assembly_engine import build
        from prompt_registry import get_component

        r = build(["task_and_code"], {"task": "t", "code_files_block": "c"})
        set_prompt_provenance(r, {"task": "t", "code_files_block": "c"})

        prov = _consume_provenance()
        for name, logged_hash in zip(prov["component_names"], prov["component_hashes"]):
            comp = get_component(name)
            assert comp.content_hash == logged_hash, f"Hash mismatch for {name}"
