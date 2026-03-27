"""Tests for prompt registry — Phase 1 verification.

Validates:
1. All 14 component files load successfully
2. All 25 nudge text entries load from registry.yaml
3. All 3 CGE instruction entries load
4. Content hashes are computed
5. Required variables are extracted from Jinja2 AST
6. Registry is immutable after load
"""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry before each test."""
    from prompt_registry import _reset_for_testing

    _reset_for_testing()
    yield
    _reset_for_testing()


class TestRegistryLoading:

    def test_loads_all_components(self):
        from prompt_registry import load_prompt_registry

        components = load_prompt_registry()
        expected = [
            "task_and_code",
            "nudge_diagnostic",
            "nudge_guardrail",
            "nudge_reasoning",
            "nudge_scm",
            "cge_stage",
            "leg_reduction",
            "classify_reasoning",
            "evaluate_reasoning_blind",
            "evaluate_reasoning_conditioned",
            "retry_analysis",
            "retry_generation",
            "repair_feedback",
            "output_instruction_v1",
            "output_instruction_v2",
        ]
        for name in expected:
            assert name in components, f"Missing component: {name}"

    def test_component_count(self):
        from prompt_registry import load_prompt_registry

        components = load_prompt_registry()
        # We have 15 .j2 files (14 from manifest + evaluate has blind+conditioned)
        assert len(components) >= 14, f"Expected >=14 components, got {len(components)}"

    def test_all_components_have_hashes(self):
        from prompt_registry import load_prompt_registry

        components = load_prompt_registry()
        for name, comp in components.items():
            assert comp.content_hash, f"Component '{name}' has no content hash"
            assert len(comp.content_hash) == 16, f"Hash length wrong for '{name}'"

    def test_all_components_have_source_path(self):
        from prompt_registry import load_prompt_registry

        components = load_prompt_registry()
        for name, comp in components.items():
            assert comp.source_path.endswith(".j2"), f"'{name}' source not .j2"

    def test_double_load_raises(self):
        from prompt_registry import load_prompt_registry

        load_prompt_registry()
        with pytest.raises(RuntimeError, match="already loaded"):
            load_prompt_registry()


class TestNudgeTexts:

    def test_loads_all_diagnostic_nudges(self):
        from prompt_registry import load_prompt_registry, get_nudge_text

        load_prompt_registry()
        diagnostics = [
            "diagnostic__hidden_dependency",
            "diagnostic__temporal_causal_error",
            "diagnostic__invariant_violation",
            "diagnostic__state_semantic_violation",
            "diagnostic__generic_dependency",
            "diagnostic__generic_invariant",
            "diagnostic__generic_temporal",
            "diagnostic__generic_state",
        ]
        for key in diagnostics:
            text = get_nudge_text(key)
            assert len(text) > 50, f"Nudge '{key}' too short: {len(text)} chars"

    def test_loads_all_guardrail_nudges(self):
        from prompt_registry import load_prompt_registry, get_nudge_text

        load_prompt_registry()
        guardrails = [
            "guardrail__hidden_dependency",
            "guardrail__temporal_causal_error",
            "guardrail__invariant_violation",
            "guardrail__state_semantic_violation",
            "guardrail__generic_dependency",
            "guardrail__generic_invariant",
            "guardrail__generic_temporal",
            "guardrail__generic_state",
        ]
        for key in guardrails:
            text = get_nudge_text(key)
            assert len(text) > 50, f"Guardrail '{key}' too short"

    def test_loads_all_reasoning_nudges(self):
        from prompt_registry import load_prompt_registry, get_nudge_text

        load_prompt_registry()
        reasoning = [
            "reasoning__counterfactual",
            "reasoning__reason_then_act",
            "reasoning__self_check",
            "reasoning__counterfactual_check",
            "reasoning__test_driven",
            "reasoning__structured",
            "reasoning__free_form",
            "reasoning__branching",
            "reasoning__alignment_extra",
        ]
        for key in reasoning:
            text = get_nudge_text(key)
            assert len(text) > 10, f"Reasoning '{key}' too short"

    def test_nudge_count(self):
        from prompt_registry import load_prompt_registry

        load_prompt_registry()
        from prompt_registry import _nudge_texts

        assert len(_nudge_texts) == 25, f"Expected 25 nudge texts, got {len(_nudge_texts)}"

    def test_missing_nudge_raises(self):
        from prompt_registry import load_prompt_registry, get_nudge_text

        load_prompt_registry()
        with pytest.raises(KeyError, match="REGISTRY ERROR"):
            get_nudge_text("nonexistent_nudge")


class TestCGEInstructions:

    def test_loads_all_cge_instructions(self):
        from prompt_registry import load_prompt_registry, get_cge_instruction

        load_prompt_registry()
        for key in ["elicit", "code", "retry"]:
            text = get_cge_instruction(key)
            assert len(text) > 10, f"CGE instruction '{key}' too short"

    def test_cge_count(self):
        from prompt_registry import load_prompt_registry

        load_prompt_registry()
        from prompt_registry import _cge_instructions

        assert len(_cge_instructions) == 3


class TestVariableExtraction:

    def test_task_and_code_variables(self):
        from prompt_registry import load_prompt_registry, get_component

        load_prompt_registry()
        comp = get_component("task_and_code")
        assert "task" in comp.required_variables
        assert "code_files_block" in comp.required_variables

    def test_classify_variables(self):
        from prompt_registry import load_prompt_registry, get_component

        load_prompt_registry()
        comp = get_component("classify_reasoning")
        assert "failure_types" in comp.required_variables
        assert "task" in comp.required_variables
        assert "code" in comp.required_variables
        assert "reasoning" in comp.required_variables

    def test_output_v2_variables(self):
        from prompt_registry import load_prompt_registry, get_component

        load_prompt_registry()
        comp = get_component("output_instruction_v2")
        assert "file_entries" in comp.required_variables

    def test_output_v1_no_variables(self):
        from prompt_registry import load_prompt_registry, get_component

        load_prompt_registry()
        comp = get_component("output_instruction_v1")
        assert len(comp.required_variables) == 0

    def test_leg_reduction_variables(self):
        from prompt_registry import load_prompt_registry, get_component

        load_prompt_registry()
        comp = get_component("leg_reduction")
        assert "task" in comp.required_variables
        assert "code_files_block" in comp.required_variables
        assert "max_internal_revisions" in comp.required_variables


class TestContentEquivalence:
    """Verify registry content matches source strings."""

    def test_diagnostic_nudge_matches_source(self):
        from prompt_registry import load_prompt_registry, get_nudge_text
        from prompts import DIAGNOSTIC_NUDGES

        load_prompt_registry()
        for fm, source_text in DIAGNOSTIC_NUDGES.items():
            key = f"diagnostic__{fm.lower()}"
            registry_text = get_nudge_text(key)
            assert registry_text == source_text, (
                f"Diagnostic nudge '{key}' content mismatch. "
                f"Source: {len(source_text)} chars, Registry: {len(registry_text)} chars"
            )

    def test_guardrail_nudge_matches_source(self):
        from prompt_registry import load_prompt_registry, get_nudge_text
        from prompts import GUARDRAIL_NUDGES

        load_prompt_registry()
        for fm, source_text in GUARDRAIL_NUDGES.items():
            key = f"guardrail__{fm.lower()}"
            registry_text = get_nudge_text(key)
            assert registry_text == source_text, f"Guardrail nudge '{key}' content mismatch"

    def test_generic_nudge_matches_source(self):
        from prompt_registry import load_prompt_registry, get_nudge_text
        from nudges.operators import _REGISTRY as OP_REG
        import nudges.core  # trigger registration

        load_prompt_registry()
        for op_name, op in OP_REG.items():
            source_text = op.build_prompt("")
            # Map operator name to registry key
            kind = op.kind  # "diagnostic" or "guardrail"
            name_map = {
                "DEPENDENCY_CHECK": "generic_dependency",
                "INVARIANT_GUARD": "generic_invariant",
                "TEMPORAL_ROBUSTNESS": "generic_temporal",
                "STATE_LIFECYCLE": "generic_state",
                "DEPENDENCY_CHECK_GUARDRAIL": "generic_dependency",
                "INVARIANT_GUARD_GUARDRAIL": "generic_invariant",
                "TEMPORAL_ROBUSTNESS_GUARDRAIL": "generic_temporal",
                "STATE_LIFECYCLE_GUARDRAIL": "generic_state",
                "COUNTERFACTUAL": None,
                "REASON_THEN_ACT": None,
                "SELF_CHECK": None,
                "COUNTERFACTUAL_CHECK": None,
                "TEST_DRIVEN": None,
            }
            if op_name in name_map and name_map[op_name] is not None:
                key = f"{kind}__{name_map[op_name]}"
            elif op_name == "STRICT_GUARDRAIL":
                continue  # dynamic, tested separately
            else:
                key = f"reasoning__{op_name.lower()}"
            registry_text = get_nudge_text(key)
            assert registry_text == source_text, (
                f"Generic nudge '{key}' (from operator '{op_name}') content mismatch. "
                f"Source: {len(source_text)} chars, Registry: {len(registry_text)} chars"
            )
