# Phase 2 — Assembly Engine Implementation Changes

**Date:** 2026-03-27

---

## Files Created

### 1. `assembly_engine.py` (new — 89 lines)

```python
"""Assembly engine — the SINGLE prompt construction path.

All prompts are built through AssemblyEngine.build(). No other code path
constructs prompts. No f-strings, no .format(), no concatenation for prompts.

Phase 2: Build + render. Components come from the prompt registry.
"""

import hashlib
import logging
from dataclasses import dataclass, field

from jinja2 import Environment, StrictUndefined

from prompt_registry import get_component, is_loaded

_log = logging.getLogger("t3.assembly")

# Single Jinja2 environment — StrictUndefined ensures missing variables are fatal
_env = Environment(undefined=StrictUndefined)


@dataclass(frozen=True)
class RenderedPrompt:
    """Immutable artifact representing one fully assembled prompt."""
    final_prompt: str
    component_names: tuple[str, ...]
    component_hashes: tuple[str, ...]
    variables_used: tuple[str, ...]
    plan_hash: str
    final_prompt_hash: str


def build(components: list[str], variables: dict[str, str]) -> RenderedPrompt:
    """Build a prompt from named components and variables.

    This is the ONE function that constructs prompts. No exceptions.

    Args:
        components: Ordered list of component names from the registry.
        variables: Dict of variable_name -> value for rendering.

    Returns:
        RenderedPrompt with the final string and full provenance.

    Raises:
        RuntimeError: If registry is not loaded.
        KeyError: If a component name is not found.
        jinja2.UndefinedError: If a required variable is missing.
    """
    if not is_loaded():
        raise RuntimeError(
            "Prompt registry not loaded. Call load_prompt_registry() before building prompts."
        )

    if not components:
        raise ValueError("ASSEMBLY ERROR: components list is empty.")

    rendered_parts = []
    comp_names = []
    comp_hashes = []
    all_vars_used = set()

    for comp_name in components:
        comp = get_component(comp_name)
        comp_names.append(comp.name)
        comp_hashes.append(comp.content_hash)
        all_vars_used.update(comp.required_variables)

        # Render with StrictUndefined — missing variable = fatal error
        template = _env.from_string(comp.raw_text)
        rendered = template.render(**variables)
        rendered_parts.append(rendered)

    # Direct concatenation — components own their own whitespace/separators.
    # This matches the old system's behavior where base + nudge are concatenated directly.
    final_prompt = "".join(rendered_parts)

    # Compute hashes
    plan_hash = hashlib.sha256(
        "|".join(f"{n}:{h}" for n, h in zip(comp_names, comp_hashes)).encode()
    ).hexdigest()[:16]

    final_prompt_hash = hashlib.sha256(
        final_prompt.encode("utf-8")
    ).hexdigest()[:16]

    return RenderedPrompt(
        final_prompt=final_prompt,
        component_names=tuple(comp_names),
        component_hashes=tuple(comp_hashes),
        variables_used=tuple(sorted(all_vars_used)),
        plan_hash=plan_hash,
        final_prompt_hash=final_prompt_hash,
    )
```

---

### 2. `tests/test_assembly_engine.py` (new — 18 tests)

```python
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
        assert result.component_names == ("task_and_code", "nudge_reasoning", "output_instruction_v1")


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
                "task": "t", "code_files_block": "c",
                "diagnostic_text": "d",
            },
        )
        assert set(result.variables_used) == {"task", "code_files_block", "diagnostic_text"}

    def test_hashes_deterministic(self):
        from assembly_engine import build
        vars1 = {"task": "Fix.", "code_files_block": "code"}
        r1 = build(["task_and_code"], vars1)
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
        assert r1.plan_hash == r2.plan_hash
        assert r1.final_prompt_hash != r2.final_prompt_hash

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
        from assembly_engine import build
        result = build(
            components=["nudge_guardrail"],
            variables={"guardrail_text": "Constraints here.", "hard_constraints_section": ""},
        )
        assert "Constraints here." in result.final_prompt

    def test_all_empty_optional_sections(self):
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

    def test_baseline_generation_equivalence(self):
        from assembly_engine import build
        from prompts import build_base_prompt

        task = "Refactor the configuration module for clarity."
        code_files = {"config.py": 'DEFAULTS = {"timeout": 30}\n\ndef create_config():\n    return DEFAULTS'}
        from prompts import _format_code_files
        code_block = _format_code_files(code_files)

        old_prompt = build_base_prompt(task, code_files)

        result = build(["task_and_code"], {"task": task, "code_files_block": code_block})

        assert result.final_prompt == old_prompt, (
            f"EQUIVALENCE FAILURE:\n"
            f"Old ({len(old_prompt)} chars): {old_prompt[:200]}...\n"
            f"New ({len(result.final_prompt)} chars): {result.final_prompt[:200]}..."
        )

    def test_classifier_prompt_equivalence(self):
        from assembly_engine import build
        from evaluator import _CLASSIFY_PROMPT

        failure_types = "HIDDEN_DEPENDENCY, INVARIANT_VIOLATION, TEMPORAL_ORDERING, UNKNOWN"
        task = "Fix the aliasing bug in config.py"
        code = "def create_config():\n    return dict(DEFAULTS)"
        reasoning = "The bug is that create_config returns DEFAULTS directly."

        old_prompt = _CLASSIFY_PROMPT.format(
            failure_types=failure_types, task=task, code=code, reasoning=reasoning,
        )

        result = build(["classify_reasoning"], {
            "failure_types": failure_types, "task": task, "code": code, "reasoning": reasoning,
        })

        assert result.final_prompt == old_prompt, (
            f"CLASSIFIER EQUIVALENCE FAILURE:\n"
            f"Old len={len(old_prompt)}, New len={len(result.final_prompt)}\n"
            f"First diff at: {next((i for i,(a,b) in enumerate(zip(old_prompt, result.final_prompt)) if a!=b), 'lengths differ')}"
        )

    def test_diagnostic_nudge_equivalence(self):
        from assembly_engine import build
        from prompts import build_base_prompt, DIAGNOSTIC_NUDGES, _format_code_files

        task = "Fix the caching bug."
        code_files = {"cache.py": "def save(): pass"}
        code_block = _format_code_files(code_files)
        nudge_text = DIAGNOSTIC_NUDGES["HIDDEN_DEPENDENCY"]

        old_prompt = build_base_prompt(task, code_files) + nudge_text

        result = build(
            ["task_and_code", "nudge_diagnostic"],
            {"task": task, "code_files_block": code_block, "diagnostic_text": nudge_text},
        )

        assert result.final_prompt == old_prompt, (
            f"DIAGNOSTIC EQUIVALENCE FAILURE:\n"
            f"Old len={len(old_prompt)}, New len={len(result.final_prompt)}"
        )
```

---

## Files Modified

None. Phase 2 is additive only. No existing call sites were changed.

---

## Test Results

```
18 passed in 0.19s (test_assembly_engine.py)
20 passed in 0.21s (test_prompt_registry.py)
166 passed total (full suite minus pre-existing failures)
0 regressions
```

---

## Equivalence Evidence

Three byte-level equivalence tests verify the new path matches the old path exactly:

| Test | Old Path | New Path | Result |
|------|----------|----------|--------|
| Baseline generation | `build_base_prompt(task, code_files)` | `build(["task_and_code"], {task, code_files_block})` | MATCH |
| Classifier | `_CLASSIFY_PROMPT.format(...)` | `build(["classify_reasoning"], {failure_types, task, code, reasoning})` | MATCH |
| Diagnostic nudge | `build_base_prompt() + DIAGNOSTIC_NUDGES[...]` | `build(["task_and_code", "nudge_diagnostic"], {task, code_files_block, diagnostic_text})` | MATCH |

---

## Key Design Decision: Direct Concatenation

Components are concatenated directly (`"".join(rendered_parts)`) rather than joined with `\n\n`. This is because:

- The old system concatenates `base + nudge_text` directly
- Nudge texts already start with `\n` (their own separator)
- Adding `\n\n` between parts would create extra whitespace not present in the old system
- Byte-level equivalence requires matching the old concatenation behavior exactly

Components own their own whitespace. The assembly engine does not inject separators.

---

## What Phase 2 Does NOT Do

- Does not modify any existing call sites
- Does not change `call_model()`
- Does not change `build_prompt()`, `_CLASSIFY_PROMPT`, or any existing prompt construction
- Does not change the runtime pipeline

The assembly engine exists alongside the old system. Phase 3 (call site migration) wires it into the runtime.
