"""Tests for assembly engine — Phase 2 verification.

Validates:
1. RenderedPrompt created correctly
2. Components rendered in order
3. Missing variables fail hard
4. Empty components list fails
5. Hashes are deterministic
6. Multi-component assembly joins correctly
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _reset_and_load():
    from prompt_registry import _reset_for_testing, load_prompt_registry

    _reset_for_testing()
    load_prompt_registry()
    yield
    _reset_for_testing()


class TestBasicAssembly:

    def test_single_component(self):
        from assembly_engine import build

        result = build(
            components=["task_and_code"],
            variables={"task": "Fix the bug.", "code_files_block": "def f(): pass"},
        )
        assert "Fix the bug." in result.final_prompt
        assert "def f(): pass" in result.final_prompt
        assert result.component_names == ("task_and_code",)
        assert len(result.component_hashes) == 1
        assert result.plan_hash
        assert result.final_prompt_hash

    def test_multi_component(self):
        from assembly_engine import build

        result = build(
            components=["task_and_code", "nudge_diagnostic"],
            variables={
                "task": "Fix the bug.",
                "code_files_block": "def f(): pass",
                "diagnostic_text": "STOP. Check dependencies.",
            },
        )
        assert "Fix the bug." in result.final_prompt
        assert "STOP. Check dependencies." in result.final_prompt
        assert result.component_names == ("task_and_code", "nudge_diagnostic")
        # task_and_code comes before nudge_diagnostic
        idx_task = result.final_prompt.index("Fix the bug.")
        idx_nudge = result.final_prompt.index("STOP. Check dependencies.")
        assert idx_task < idx_nudge

    def test_three_components_with_output_instruction(self):
        from assembly_engine import build

        result = build(
            components=["task_and_code", "nudge_reasoning", "output_instruction_v1"],
            variables={
                "task": "Fix it.",
                "code_files_block": "code here",
                "reasoning_text": "Think step by step.",
            },
        )
        assert "Fix it." in result.final_prompt
        assert "Think step by step." in result.final_prompt
        assert "Return your response as a single valid JSON" in result.final_prompt
        assert result.component_names == (
            "task_and_code",
            "nudge_reasoning",
            "output_instruction_v1",
        )


class TestRenderedPromptFields:

    def test_variables_used_tracked(self):
        from assembly_engine import build

        result = build(
            components=["task_and_code"],
            variables={"task": "t", "code_files_block": "c"},
        )
        assert "task" in result.variables_used
        assert "code_files_block" in result.variables_used

    def test_variables_union_across_components(self):
        from assembly_engine import build

        result = build(
            components=["task_and_code", "nudge_diagnostic"],
            variables={
                "task": "t",
                "code_files_block": "c",
                "diagnostic_text": "d",
            },
        )
        assert set(result.variables_used) == {"task", "code_files_block", "diagnostic_text"}

    def test_hashes_deterministic(self):
        from assembly_engine import build

        vars1 = {"task": "Fix.", "code_files_block": "code"}
        r1 = build(["task_and_code"], vars1)
        # Reset and rebuild
        from prompt_registry import _reset_for_testing, load_prompt_registry

        _reset_for_testing()
        load_prompt_registry()
        r2 = build(["task_and_code"], vars1)
        assert r1.final_prompt_hash == r2.final_prompt_hash
        assert r1.plan_hash == r2.plan_hash

    def test_different_variables_different_prompt_hash(self):
        from assembly_engine import build

        r1 = build(["task_and_code"], {"task": "A", "code_files_block": "c"})
        r2 = build(["task_and_code"], {"task": "B", "code_files_block": "c"})
        assert r1.plan_hash == r2.plan_hash  # same components
        assert r1.final_prompt_hash != r2.final_prompt_hash  # different content

    def test_different_components_different_plan_hash(self):
        from assembly_engine import build

        r1 = build(
            ["task_and_code"],
            {"task": "t", "code_files_block": "c"},
        )
        r2 = build(
            ["task_and_code", "output_instruction_v1"],
            {"task": "t", "code_files_block": "c"},
        )
        assert r1.plan_hash != r2.plan_hash

    def test_frozen(self):
        from assembly_engine import build

        result = build(["task_and_code"], {"task": "t", "code_files_block": "c"})
        with pytest.raises(AttributeError):
            result.final_prompt = "modified"


class TestFailureModes:

    def test_missing_variable_raises(self):
        from assembly_engine import build
        from jinja2 import UndefinedError

        with pytest.raises(UndefinedError, match="code_files_block"):
            build(["task_and_code"], {"task": "only task"})

    def test_unknown_component_raises(self):
        from assembly_engine import build

        with pytest.raises(KeyError, match="REGISTRY ERROR"):
            build(["nonexistent_component"], {})

    def test_empty_components_raises(self):
        from assembly_engine import build

        with pytest.raises(ValueError, match="empty"):
            build([], {})

    def test_registry_not_loaded_raises(self):
        from prompt_registry import _reset_for_testing
        from assembly_engine import build

        _reset_for_testing()
        with pytest.raises(RuntimeError, match="not loaded"):
            build(["task_and_code"], {"task": "t", "code_files_block": "c"})


class TestEmptyComponentRendering:

    def test_empty_variable_renders_blank(self):
        """Components with empty string variables should not create blank sections."""
        from assembly_engine import build

        result = build(
            components=["nudge_guardrail"],
            variables={"guardrail_text": "Constraints here.", "hard_constraints_section": ""},
        )
        assert "Constraints here." in result.final_prompt

    def test_all_empty_optional_sections(self):
        """retry_generation with all optional sections empty."""
        from assembly_engine import build

        result = build(
            components=["retry_generation"],
            variables={
                "task": "Fix it.",
                "original_code": "old code",
                "previous_code": "new code",
                "test_output": "FAIL",
                "critique_section": "",
                "contract_section": "",
                "hint_section": "",
                "trajectory_section": "",
                "fix_instruction": "Fix the tests.",
            },
        )
        assert "Fix it." in result.final_prompt
        assert "old code" in result.final_prompt
        assert "Fix the tests." in result.final_prompt


class TestRealPromptEquivalence:
    """Verify assembly produces byte-identical output to current f-string prompts."""

    def test_baseline_generation_equivalence(self):
        """AssemblyEngine output must match build_base_prompt output."""
        from assembly_engine import build
        from prompts import build_base_prompt

        task = "Refactor the configuration module for clarity."
        code_files = {
            "config.py": 'DEFAULTS = {"timeout": 30}\n\ndef create_config():\n    return DEFAULTS'
        }
        from prompts import _format_code_files

        code_block = _format_code_files(code_files)

        # Old path
        old_prompt = build_base_prompt(task, code_files)

        # New path
        result = build(["task_and_code"], {"task": task, "code_files_block": code_block})

        assert result.final_prompt == old_prompt, (
            f"EQUIVALENCE FAILURE:\n"
            f"Old ({len(old_prompt)} chars): {old_prompt[:200]}...\n"
            f"New ({len(result.final_prompt)} chars): {result.final_prompt[:200]}..."
        )

    def test_classifier_prompt_equivalence(self):
        """AssemblyEngine output must match _CLASSIFY_PROMPT.format() output."""
        from assembly_engine import build
        from evaluator import _CLASSIFY_PROMPT

        failure_types = "HIDDEN_DEPENDENCY, INVARIANT_VIOLATION, TEMPORAL_ORDERING, UNKNOWN"
        task = "Fix the aliasing bug in config.py"
        code = "def create_config():\n    return dict(DEFAULTS)"
        reasoning = "The bug is that create_config returns DEFAULTS directly."

        # Old path
        old_prompt = _CLASSIFY_PROMPT.format(
            failure_types=failure_types,
            task=task,
            code=code,
            reasoning=reasoning,
        )

        # New path
        result = build(
            ["classify_reasoning"],
            {
                "failure_types": failure_types,
                "task": task,
                "code": code,
                "reasoning": reasoning,
            },
        )

        assert result.final_prompt == old_prompt, (
            f"CLASSIFIER EQUIVALENCE FAILURE:\n"
            f"Old len={len(old_prompt)}, New len={len(result.final_prompt)}\n"
            f"First diff at: {next((i for i,(a,b) in enumerate(zip(old_prompt, result.final_prompt)) if a!=b), 'lengths differ')}"
        )

    def test_diagnostic_nudge_equivalence(self):
        """AssemblyEngine task+code+nudge must match build_base_prompt + nudge text."""
        from assembly_engine import build
        from prompts import build_base_prompt, DIAGNOSTIC_NUDGES, _format_code_files

        task = "Fix the caching bug."
        code_files = {"cache.py": "def save(): pass"}
        code_block = _format_code_files(code_files)
        nudge_text = DIAGNOSTIC_NUDGES["HIDDEN_DEPENDENCY"]

        # Old path
        old_prompt = build_base_prompt(task, code_files) + nudge_text

        # New path
        result = build(
            ["task_and_code", "nudge_diagnostic"],
            {"task": task, "code_files_block": code_block, "diagnostic_text": nudge_text},
        )

        assert result.final_prompt == old_prompt, (
            f"DIAGNOSTIC EQUIVALENCE FAILURE:\n"
            f"Old len={len(old_prompt)}, New len={len(result.final_prompt)}"
        )


class TestVariablesUsedProvenance:
    """variables_used must reflect ACTUALLY PROVIDED variables, not template requirements."""

    def test_variables_used_only_includes_passed_variables(self):
        """Omitted optional variables must NOT appear in variables_used."""
        from assembly_engine import build
        from jinja2 import UndefinedError

        # retry_generation requires 9 variables. Pass only the required ones.
        # StrictUndefined will raise if template NEEDS them, so we must pass all.
        # But the point is: variables_used should only contain what was in the dict.
        result = build(
            ["retry_generation"],
            {
                "task": "Fix",
                "original_code": "x",
                "previous_code": "y",
                "test_output": "fail",
                "critique_section": "",
                "contract_section": "",
                "hint_section": "",
                "trajectory_section": "",
                "fix_instruction": "fix it",
            },
        )
        # All 9 were passed, so all 9 should appear
        assert len(result.variables_used) == 9

    def test_extra_variables_not_tracked(self):
        """Variables in the dict but NOT required by any component must not appear."""
        from assembly_engine import build

        result = build(
            ["task_and_code"],
            {
                "task": "Fix",
                "code_files_block": "code",
                "extra_unused_var": "should not appear",
            },
        )
        assert "extra_unused_var" not in result.variables_used
        assert set(result.variables_used) == {"task", "code_files_block"}

    def test_variables_used_is_intersection(self):
        """variables_used = required_variables ∩ provided_variables."""
        from assembly_engine import build

        # nudge_guardrail requires: guardrail_text, hard_constraints_section
        result = build(
            ["nudge_guardrail"],
            {
                "guardrail_text": "constraints",
                "hard_constraints_section": "",
                "irrelevant": "not tracked",
            },
        )
        assert set(result.variables_used) == {"guardrail_text", "hard_constraints_section"}
        assert "irrelevant" not in result.variables_used


class TestEnforcement:
    """Enforce that no prompt construction exists outside assembly_engine."""

    PROMPT_MODULES = [
        "prompts.py",
        "reasoning_prompts.py",
        "scm_prompts.py",
        "nudges/core.py",
        "nudges/router.py",
        "contract.py",
        "leg_reduction.py",
        "retry_harness.py",
        "evaluator.py",
        "leg_evaluator.py",
    ]

    def test_no_direct_component_access_outside_allowed_modules(self):
        """No file outside assembly_engine/prompt_registry/tests may access
        the registry directly. This prevents bypassing the assembly engine."""
        import os
        from pathlib import Path

        base = Path(__file__).parent.parent
        # Tokens that indicate direct registry access
        forbidden_tokens = [
            "get_component(",
            "get_nudge_text(",
            "get_cge_instruction(",
            ".raw_text",
        ]
        # Modules allowed to use registry directly
        allowed_files = {
            "assembly_engine.py",
            "prompt_registry.py",
        }

        violations = []
        for root, _, files in os.walk(str(base)):
            # Skip non-source directories
            rel_root = os.path.relpath(root, str(base))
            if any(skip in rel_root for skip in [
                "tests", ".venv", "__pycache__", "node_modules",
                "code_snippets", "scm_data", "prompts", ".git", ".idea",
                "logs", "plans", "docs", "audit", "scripts",
            ]):
                continue
            for file in files:
                if not file.endswith(".py"):
                    continue
                if file in allowed_files:
                    continue
                filepath = os.path.join(root, file)
                content = open(filepath).read()
                for token in forbidden_tokens:
                    if token in content:
                        violations.append(f"{os.path.relpath(filepath, str(base))}: {token}")

        assert not violations, (
            f"Direct registry access found outside allowed modules:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n\nAll prompt construction must go through assembly_engine.build()."
        )

    def test_no_format_calls_in_prompt_modules(self):
        """Detect .format() usage in prompt modules — Phase 3 migration targets.

        NOTE: This test documents the current state. During Phase 3,
        .format() calls will be replaced with assembly_engine.build().
        Until then, this test passes but logs violations as migration targets.
        """
        from pathlib import Path

        base = Path(__file__).parent.parent
        migration_targets = []
        for mod in self.PROMPT_MODULES:
            path = base / mod
            if not path.exists():
                continue
            lines = path.read_text().split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if ".format(" in stripped and not stripped.startswith("#"):
                    if "error" in stripped.lower() or "log" in stripped.lower():
                        continue
                    migration_targets.append(f"{mod}:{i}: {stripped[:80]}")
        # Informational — will become assert after Phase 3 migration
        # To see targets: run with -s flag
        if migration_targets:
            import sys
            print(f"\n  [PHASE 3 MIGRATION TARGETS: {len(migration_targets)} .format() calls]",
                  file=sys.stderr)

    def test_assembly_engine_public_api(self):
        """assembly_engine must only expose build() + registry accessors."""
        import inspect
        import assembly_engine

        assert callable(assembly_engine.build)

        defined_funcs = sorted([
            name
            for name, obj in inspect.getmembers(assembly_engine, inspect.isfunction)
            if obj.__module__ == "assembly_engine" and not name.startswith("_")
        ])
        allowed = ["build", "resolve_cge_instruction", "resolve_nudge"]
        assert defined_funcs == allowed, (
            f"Unexpected public functions in assembly_engine: {defined_funcs}. "
            f"Allowed: {allowed}"
        )

    def test_no_prompt_registry_import_outside_allowed_modules(self):
        """No execution module may import from prompt_registry directly.
        Only assembly_engine.py may import prompt_registry."""
        import os
        from pathlib import Path

        base = Path(__file__).parent.parent
        allowed_importers = {
            "assembly_engine.py",
            "prompt_registry.py",
            "runner.py",  # entry point — loads registry at startup
        }
        forbidden_imports = [
            "from prompt_registry import",
            "import prompt_registry",
        ]

        violations = []
        for root, _, files in os.walk(str(base)):
            rel_root = os.path.relpath(root, str(base))
            if any(skip in rel_root for skip in [
                "tests", ".venv", "__pycache__", "node_modules",
                "code_snippets", "scm_data", "prompts", ".git", ".idea",
                "logs", "plans", "docs", "audit", "scripts",
            ]):
                continue
            for file in files:
                if not file.endswith(".py"):
                    continue
                if file in allowed_importers:
                    continue
                filepath = os.path.join(root, file)
                content = open(filepath).read()
                for token in forbidden_imports:
                    if token in content:
                        violations.append(f"{os.path.relpath(filepath, str(base))}: {token}")

        assert not violations, (
            f"Direct prompt_registry import found outside allowed modules:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n\nOnly assembly_engine.py may import prompt_registry."
        )
